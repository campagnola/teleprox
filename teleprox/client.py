# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import concurrent.futures
import contextlib
import logging
import re
import sys
import threading
import time
import traceback
import weakref

import zmq

from teleprox.util import check_tcp_port
from . import log
from .qt_server import QtRPCServer
from .serializer import all_serializers, Serializer
from .server import RPCServer

logger = logging.getLogger(__name__)


class RPCClient(object):
    """Connection to an :class:`RPCServer`.

    Each RPCClient connects to only one server, and may be used from only one
    thread. RPCClient instances are created automatically either through
    :class:`start_process` or by requesting attributes from an :class:`ObjectProxy`.
    In general, it is not necessary for the user to interact directly with
    RPCClient.

    Parameters
    ----------
    address : URL
        Address of RPC server to connect to.
    local_server : "threaded" | "lazy" | RPCServer | None
        None (default):
            Do not proxy through a local RPCServer. This means that the client will not be able
            to proxy objects to the remote server, and will only be able to send simple,
            serializable data types (see ``serialize_types``).
        "threaded":
            Start a dedicated RPCServer in a thread that will proxy data send through this
            client in an asynchronous manner. This allows the client to send callbacks and
            persistent objects safely. It means that processing will happen in a separate thread,
            and therefore thread-safe practices will need to be followed when using this client.
        "lazy":
            Start a dedicated RPCServer that is not actively processing requests, but will
            process them when this client is used. This allows the client to proxy objects
            intended for use during the individual remote calls, but not outside of them.
            Violation of this contract will most likely result in timeouts. Because responses
            from a remote server can themselves be proxied, it may seem like a reference should
            be pointed at a local object directly, but if it lives inside such a remote proxy,
            then it will sneakily not be the case.
        RPCServer:
            Use the given RPCServer instance to handle proxying data sent to the remote server.
            This can be used to share a server between multiple clients.
    serializer : str
        Type of serializer to use when communicating with the remote server.
        Default is 'msgpack'.
    serialize_types : tuple | None
        A tuple of types that may be serialized when sending request arguments to the remote server.
        If a local server is running, then types not in this list will be sent by proxy.
        Otherwise, a TypeError is raised.
        If None, then ``serializer.default_serialize_types`` is used instead.
        This is also used in the construction of the local RPCServer if local_server is dedicated.

    Raises
    ------
    ConnectionRefusedError if no server is running at the given address.
    TimeoutError if the server cannot be reached within the default timeout.
    """

    clients_by_thread = {}  # (thread_id, rpc_addr): client
    clients_by_thread_lock = threading.Lock()

    @staticmethod
    def get_client(address, create=True, **kwargs):
        """Return the RPC client for this thread and a given server address.

        If no client exists already, then a new one will be created. If the
        server is running in the current thread, then return None.

        Parameters
        ----------
        create : bool
            If True, then create a new RPCClient instance if one does not already exist.

        All other parameters are FOR INTERNAL USE ONLY (and are passed to the RPCClient
        constructor).

        See also
        --------

        ``RPCServer.address``
        """
        if isinstance(address, str):
            address = address.encode()
        key = (threading.current_thread().ident, address)

        # Return an existing client if there is one
        with RPCClient.clients_by_thread_lock:
            if key in RPCClient.clients_by_thread:
                client = RPCClient.clients_by_thread[key]
                local_server = kwargs.pop('local_server', client._local_server)
                if kwargs or local_server is not client._local_server:
                    raise ValueError(
                        "Cannot pass arguments to get_client() if it already exists for this address."
                    )
                return client

        if create:
            return RPCClient(address, **kwargs)
        return None

    @staticmethod
    def forget_client(client):
        """Forget a client that is no longer needed."""
        key = (threading.current_thread().ident, client.address)
        with RPCClient.clients_by_thread_lock:
            RPCClient.clients_by_thread.pop(key, None)

    def __init__(
        self,
        address,
        local_server=None,
        serializer='msgpack',
        serialize_types=None,
    ):
        """Initialize a new RPCClient."""
        if isinstance(address, str):
            address = address.encode()

        # pick a unique name: host.pid.tid:rpc_addr
        self.name = f"{log.get_host_name()}.{log.get_process_name()}.{log.get_thread_name()}:{address.decode()}".encode()

        self.serialize_types = serialize_types

        if sys.platform == 'win32' and '0.0.0.0' in str(address):
            logger.warning(f"RPC server address {address} is likely to cause trouble on windows")
        self.address = address

        if local_server in ("threaded", "lazy"):
            self._manage_local_server = True
            self._local_server = RPCServer(
                serialize_types=serialize_types,
                run_thread=(local_server == "threaded"),
            )
        else:
            self._manage_local_server = False
            self._local_server = local_server

        key = (threading.current_thread().ident, address)
        with RPCClient.clients_by_thread_lock:
            if key in RPCClient.clients_by_thread:
                raise KeyError(
                    "An RPCClient instance already exists for this address."
                    " Use RPCClient.get_client(address) instead."
                )
            RPCClient.clients_by_thread[key] = self

        try:
            # Make sure we can reach this address and there is an open socket
            port_status = self.check_address(address)
            if port_status == "closed":
                raise ConnectionRefusedError(f"Connection refused to {address.decode()}")

            # DEALER is fully asynchronous--we can send or receive at any time, and
            # unlike ROUTER, it only connects to a single endpoint.
            self._socket = zmq.Context.instance().socket(zmq.DEALER)
            self._sock_name = self.name
            self._socket.setsockopt(zmq.IDENTITY, self._sock_name)
            # socket will continue attempting to deliver messages up to 1 sec after
            # it has closed. (default is -1, which can cause processes to hang
            # on exit)
            self._socket.linger = 1000
            self._poller = None

            logger.info("RPC connect to %s", address.decode())
            self._socket.connect(address)
            self.next_request_id = 0
            self.futures = weakref.WeakValueDictionary()

            # proxies generated by this client will be assigned these default options
            self.default_proxy_options = {}

            self.connect_established = False
            self.establishing_connect = False
            self._disconnected = False

            # For serializing requests sent to servers and unserializing the responses.
            # When sending requests, this serializer can only generate proxies if it is
            # associated with a local server.
            try:
                self.serializer: Serializer = all_serializers[serializer](self._local_server)
            except KeyError as e:
                raise ValueError(f"Unsupported serializer type '{serializer}'") from e

            self.ensure_connection()
        except Exception:
            RPCClient.clients_by_thread.pop(key, None)
            raise

    @staticmethod
    def check_address(address, timeout=1.0):
        """
        Test if a socket can connect to the given host and port.
        Only TCP addresses are supported.

        Returns:
            "open" - if the socket connects successfully
            "closed" - if the connection is refused
            "timeout" - if the connection times out
            None - non-tcp ports or invalid addresses
        """
        parts = re.match(r'^tcp://(.+):(\d+)$', address.decode())
        if parts is None:
            return None

        host, port = parts.groups()
        port = int(port)
        return check_tcp_port(host, port, timeout)

    def _get_poller(self):
        # Return the poller that should be used to listen for incoming messages
        # This poller is responsible for ensuring that the RPC server in this
        # thread is able to process requests while we are blocked waiting
        # for responses from other servers.
        if self._poller is None:
            if self._local_server is None:
                return None
            elif isinstance(self._local_server, QtRPCServer):
                self._poller = 'qt'
            elif self._local_server.client_should_handle_requests():
                self._poller = zmq.Poller()
                self._poller.register(self._socket, zmq.POLLIN)
                self._poller.register(self._local_server._socket, zmq.POLLIN)
            else:
                return None
        return self._poller

    def disconnected(self):
        """Boolean indicating whether the server has disconnected from the client."""
        if self._disconnected:
            return True

        # check to see if we have received any new messages
        try:
            self._read_and_process_all()
        except zmq.error.ZMQError:
            self._disconnected = True

        return self._disconnected

    def send(
        self,
        action,
        opts=None,
        return_type='auto',
        sync='sync',
        timeout=10.0,
    ):
        """Send a request to the remote process.

        It is not necessary to call this method directly; instead use
        :func:`call_obj`, :func:`get_obj`, :func:`__getitem__`, :func:`__setitem__`,
        :func:`transfer`, :func:`delete`, :func:`import`, or :func:`ping`.

        The request is given a unique ID that is included in the response from
        the server (if any).

        Parameters
        ----------
        action : str
            The action to invoke on the remote process. See list of actions
            below.
        opts : None or dict
            Extra options to be sent with the request. Each action requires a
            different set of options. See list of actions below.
        return_type : 'auto' | 'proxy'
            If 'proxy', then the return value is sent by proxy. If 'auto', then
            the server decides based on the return type whether to send a proxy.
        sync : str
            If 'sync', then block and return the result when it becomes available.
            If 'async', then return a Future instance immediately.
            If 'off', then ask the remote server NOT to send a response and
            return None immediately.
        timeout : float
            The amount of time to wait for a response when in synchronous
            operation (sync='sync'). If the timeout elapses before a response is
            received, then raise TimeoutError.

        Notes
        -----

        The following table lists the actions that are recognized by RPCServer.
        The *action* argument to `send()` may be any string from the *Action*
        column below, and the *opts* argument must be a dict with the keys listed
        in the *Options* column.

        ======== ======================================= ==========================================
        Action   Description                             Options
        -------- --------------------------------------- ------------------------------------------
        call_obj Invoke a callable                       | obj: a proxy to the callable object
                                                         | args: a tuple of positional arguments
                                                         | kwargs: a dict of keyword arguments
        get_obj  Return the object referenced by a proxy | obj: a proxy to the object to return
        get_item Return a named object                   | name: string name of the object to return
        set_item Set a named object                      | name: string name to set
                                                         | value: object to assign to name
        delete   Delete a proxy reference                | obj_id: proxy object ID
                                                         | ref_id: proxy reference ID
        import   Import and return a proxy to a module   | module: name of module to import
        ping     Return 'pong'                           |
        ======== ======================================= ==========================================

        """
        # if self.disconnected():         # This is nice, but very expensive!
        if self._disconnected:
            raise RuntimeError("Cannot send request; server has already disconnected.")

        if sync == 'off':
            req_id = -1
        else:
            req_id = self.next_request_id
            self.next_request_id += 1
        logger.info("RPC request '%s' to %s [req_id=%s]", action, self.address.decode(), req_id)
        logger.debug("    => sync=%s return=%s opts=%s", sync, return_type, opts)

        if opts is None:
            opts_str = b''
        else:
            opts_str = self.serializer.dumps(opts, serialize_types=self.serialize_types)
        ser_type = self.serializer.type.encode()

        msg = [
            str(req_id).encode(),
            action.encode(),
            return_type.encode(),
            ser_type,
            opts_str,
        ]
        self._socket.send_multipart(msg)

        if sync == 'off':
            return

        fut = Future(self, req_id)
        if action == 'close':
            # for server closure we require a little special handling
            fut.add_done_callback(self._close_request_returned)
        self.futures[req_id] = fut

        if sync == 'async':
            return fut
        elif sync == 'sync':
            return fut.result(timeout=timeout)
        else:
            raise ValueError(f'Invalid sync value: {sync}')

    def call_obj(self, obj, args=None, kwargs=None, **kwds):
        """Invoke a remote callable object.

        Parameters
        ----------
        obj : :class:`ObjectProxy`
            A proxy that references an object owned by the connected RPCServer.
        args : tuple
            Arguments to pass to the remote call.
        kwargs : dict
            Keyword arguments to pass to the remote call.
        kwds :
            All extra keyword arguments are passed to :func:`send() <RPCClient.send>`.
        """
        opts = {'obj': obj, 'args': args, 'kwargs': kwargs}
        return self.send('call_obj', opts=opts, **kwds)

    def get_obj(self, obj, **kwds):
        """Return a copy of a remote object.

        Parameters
        ----------
        obj : :class:`ObjectProxy`
            A proxy that references an object owned by the connected RPCServer.
            The object will be serialized and returned if possible, otherwise
            a new proxy is returned.
        kwds :
            All extra keyword arguments are passed to :func:`send() <RPCClient.send>`.
        """
        return self.send('get_obj', opts={'obj': obj}, **kwds)

    def transfer(self, obj, **kwds):
        """Send an object to the remote process and return a proxy to it.

        Parameters
        ----------
        obj : object
            Any object to send to the remote process. If the object is not
            serializable then a proxy will be sent if possible.
        kwds :
            All extra keyword arguments are passed to :func:`send() <RPCClient.send>`.
        """
        kwds['return_type'] = 'proxy'
        return self.send('get_obj', opts={'obj': obj}, **kwds)

    def _import(self, module, **kwds):
        """Import a module in the remote process and return a proxy to it.

        Parameters
        ----------
        module : str
            The name of the module to import.
        kwds :
            All extra keyword arguments are passed to :func:`send() <RPCClient.send>`.
        """
        return self.send('import', opts={'module': module}, **kwds)

    def delete(self, obj, **kwds):
        """Delete an object proxy.

        This informs the remote process that an :class:`ObjectProxy` is no longer
        needed. The remote process will decrement a reference counter and
        delete the referenced object if it is no longer held by any proxies.

        Parameters
        ----------
        obj : :class:`ObjectProxy`
            A proxy that references an object owned by the connected RPCServer.
        kwds :
            All extra keyword arguments are passed to :func:`send() <RPCClient.send>`.

        Notes
        -----

        After a proxy is deleted, it cannot be used to access the remote object
        even if the server has not released the remote object yet. This also
        applies to proxies that are sent to a third process. For example, consider
        three processes A, B, C: first A acquires a proxy to an object owned by
        B. A sends the proxy to C, and then deletes the proxy. If C attempts to
        access this proxy, an exception will be raised because B has already
        remoted the reference held by this proxy. However, if C independently
        acquires a proxy to the same object owned by B, then that proxy will
        continue to function even after A deletes its proxy.
        """
        assert obj._rpc_addr == self.address
        return self.send('delete', opts={'obj_id': obj._obj_id, 'ref_id': obj._ref_id}, **kwds)

    def __getitem__(self, name):
        """Return a named item published by the remote server.

        This provides a sort of "global namespace" for clients to access objects
        that are explicitly published using either :func:`RPCServer.__setitem__`
        or :func:`RPCClient.__setitem__`.
        """
        return self.send('get_item', opts={'name': name}, sync='sync')

    def __setitem__(self, name, obj):
        """Publish an object as a named item on the server.

        The item can be retrieved by the remote process using
        :func:`RPCServer.__getitem__`, or by any client connected to the remote
        server using :func:`RPCClient.__getitem__`.
        """
        # We could make this sync='off', but probably it's safer to block until
        # the transaction is complete.
        return self.send('set_item', opts={'name': name, 'obj': obj}, sync='sync')

    def ensure_connection(self, timeout=1.0):
        """Make sure RPC server is connected and available."""
        if self.establishing_connect:
            return
        self.establishing_connect = True
        try:
            start = time.time()
            while time.time() < start + timeout:
                fut = self.ping(sync='async')
                try:
                    result = fut.result(timeout=0.1)
                    self.connect_established = True
                    return
                except TimeoutError:
                    continue
            raise TimeoutError(
                f"Could not establish connection with RPC server at {self.address.decode()}"
            )
        finally:
            self.establishing_connect = False

    def process_until_future(self, future, timeout=None):
        """Process all incoming messages until receiving a result for *future*.

        If the future result is not raised before the timeout, then raise
        TimeoutError.

        While waiting, the RPCServer for this thread (if any) is also allowed to process
        requests.

        Parameters
        ----------
        future : concurrent.Future instance
            The Future to wait for. When the response for this Future arrives
            from the server, the method returns.
        timeout : float
            Maximum time (seconds) to wait for a response.
        """
        start = time.perf_counter()
        while not future.done():
            # wait patiently with blocking calls.
            if timeout is None:
                itimeout = None
            else:
                dt = time.perf_counter() - start
                itimeout = timeout - dt
                if itimeout < 0:
                    raise TimeoutError("Timeout waiting for Future result.")

            poller = self._get_poller()
            if poller is None:
                self._read_and_process_one(itimeout)
            elif poller == 'qt':
                # Server runs in Qt thread; we need to time-share with Qt event
                # loop.
                from .qt import QApplication

                QApplication.processEvents()
                with contextlib.suppress(TimeoutError):
                    self._read_and_process_one(timeout=0.05)
            else:
                # Poll for input on both the client's socket and the server's
                # socket. This is for lazy or same-thread servers.
                socks = [x[0] for x in poller.poll(itimeout)]
                if self._socket in socks:
                    self._read_and_process_one(timeout=0)
                if self._local_server._socket in socks:
                    self._local_server.read_and_process_one()

    def _read_and_process_one(self, timeout):
        """Read a single message from the remote server and process it by
        calling :func:`process_msg()`.

        Parameters
        ----------
        timeout : float
            Maximum time (seconds) to wait for a message. Use timeout=None to
            block indefinitely.

        """
        # timeout is in seconds; convert to ms
        # use timeout=None to block indefinitely
        if timeout is None:
            timeout = -1
        else:
            timeout = int(timeout * 1000)

        try:
            # NOTE: docs say timeout can only be set before bind, but this
            # seems to work for now.
            self._socket.setsockopt(zmq.RCVTIMEO, timeout)
            msg = self._socket.recv()
            msg = self.serializer.loads(msg, proxy_opts=self.default_proxy_options)
        except zmq.error.Again as exc:
            raise TimeoutError("Timeout waiting for Future result.") from None

        self.process_msg(msg)

    def _read_and_process_all(self):
        # process all messages until none are immediately available.
        try:
            while True:
                self._read_and_process_one(timeout=0)
        except TimeoutError:
            return

    def process_msg(self, msg):
        """Handle one message received from the remote process.

        This takes care of assigning return values or exceptions to existing
        Future instances.
        """
        logger.debug(
            "RPC recv result from %s [req_id=%s]",
            self.address.decode(),
            msg.get('req_id', None),
        )
        logger.debug(f"    => {msg}")
        if msg['action'] == 'return':
            req_id = msg['req_id']
            fut = self.futures.pop(req_id, None)
            if fut is None:
                return
            if msg['error'] is not None:
                error_data = msg['error']
                exc = RemoteCallException(
                    error_data['type'],
                    error_data['traceback'],
                    remote_stack_info=error_data.get('remote_stack_info'),
                    remote_exc_traceback=error_data.get('remote_exc_traceback'),
                )
                fut.set_exception(exc)
            else:
                fut.set_result(msg['rval'])
        elif msg['action'] == 'disconnect':
            self._server_disconnected()
        else:
            raise ValueError(f"Invalid action '{msg['action']}'")

    def _close_request_returned(self, fut):
        try:
            if fut.result() is True:
                # We requested a server closure and the server complied; now
                # handle the disconnect.
                self._server_disconnected()
        except RuntimeError:
            # might have already disconnected before this request finished.
            if self.disconnected():
                pass
            raise

    def _server_disconnected(self):
        # server has disconnected; inform all pending futures.
        # This method can be called two different ways:
        # * this client requested that the server close and it returned True
        # * another client requested that the server close and this client
        #   received a preemptive disconnect message from the server.
        self._disconnected = True
        logger.debug("Received server disconnect from %s", self.address)
        exc = RuntimeError("Cannot receive result; server has already disconnected.")
        for fut in self.futures.values():
            fut.set_exception(exc)
        self.futures.clear()

    def ping(self, sync='sync', **kwds):
        """Ping the server.

        This can be used to test connectivity to the server.
        """
        return self.send('ping', sync=sync, **kwds)

    def close(self):
        """Close this client's socket (but leave the server running)."""
        # reference management is disabled for now..
        # self.send('release_all', return_type=None)
        self._socket.close()
        RPCClient.forget_client(self)
        if self._manage_local_server:
            self._local_server.close()

    def close_server(self, sync='sync', timeout=1.0, **kwds):
        """Ask the server to close.

        The server returns True if it has closed. All clients known to the
        server will be informed that the server has disconnected.

        If the server has already disconnected from this client, then the
        method returns True without error.
        """
        if self.disconnected():
            return True
        return self.send('close', sync=sync, timeout=timeout, **kwds)

    def measure_clock_diff(self):
        """Measure the clock offset between this host and the remote host."""
        rcounter = self._import('time').perf_counter
        ltimes = []
        rtimes = []
        for i in range(10):
            ltimes.append(time.perf_counter())
            rtimes.append(rcounter())
        rtimes = rtimes[:-1]
        dif = [rt - ((lt1 + lt2) * 0.5) for rt, lt1, lt2 in zip(rtimes, ltimes[1:], ltimes[:-1])]
        avg = sum(dif) / len(dif)
        # we can probably constrain this estimate a bit more by looking at
        # min/max times and excluding outliers.
        return avg

    def __del__(self):
        if hasattr(self, 'socket'):
            self.close()


class RemoteCallException(Exception):
    """Exception raised when a remote procedure call fails.

    Parameters
    ----------
    type_str : str
        The name of the exception class that was raised on the remote server.
        Generated using `exc_info[0].__name__` (e.g., "TypeError", "ValueError").
    tb_str : list of str
        Complete traceback as a list of formatted strings. Structure:
        - First element: "Error while processing request {caller} [{req_id}]: "
        - Middle elements: Stack frames from `traceback.format_stack()`
        - Separator: " < exception caught here >\n"
        - Final elements: Exception traceback from `traceback.format_exception(*exc)`
    remote_stack_info : str or None
        Server-side call stack as a single string, showing where the exception
        was caught. Generated using `''.join(traceback.format_stack())`.
        Used by the log viewer for hierarchical display of the remote stack.
    remote_exc_traceback : str or None
        Original exception traceback as a single string, showing where the
        exception originated. Generated using `''.join(traceback.format_exception(*exc))`.
        Used by the log viewer for hierarchical display of the exception chain.

    Notes
    -----
    The structured remote traceback data (remote_stack_info and remote_exc_traceback)
    is specifically designed for the log viewer, which parses these strings to create
    hierarchical views under "Remote Stack" and "Remote Exception" categories.
    """

    def __init__(self, type_str, tb_str, remote_stack_info=None, remote_exc_traceback=None):
        self.type_str = type_str
        self.tb_str = tb_str
        # Store structured remote traceback data for log viewer
        self.remote_stack_info = remote_stack_info
        self.remote_exc_traceback = remote_exc_traceback

    def __str__(self):
        # Return a concise message instead of the full traceback.
        # Full traceback details are available through structured remote traceback sections
        if self.tb_str and len(self.tb_str) > 0:
            def find_last_note_index(lines):
                for i in reversed(range(len(lines))):
                    if lines[i].startswith("This exception was caused by a remote call to"):
                        return i
                return None
            # ignore notes
            note_start = find_last_note_index(self.tb_str)
            last_line = None
            if note_start is not None:
                last_line = self.tb_str[note_start - 1].strip()
            elif self.tb_str[-1].strip():
                # Extract just the exception type and message from the last line of traceback
                last_line = self.tb_str[-1].strip()
            elif len(self.tb_str) > 1:
                last_line = self.tb_str[-2].strip()
            if last_line and ': ' in last_line:
                return f"Remote {last_line}"
        return f"Remote {self.type_str}"


class Future(concurrent.futures.Future):
    """Represents a return value from a remote procedure call that has not
    yet arrived.

    Instances of Future are returned from :func:`ObjectProxy.__call__()` when
    used with ``_sync='async'``. This is the mechanism through which remote
    functions may be called asynchronously.

    Use :func:`done()` to determine whether the return value (or an error message)
    has arrived, and :func:`result()` to get the return value. If the remote
    call raised an exception, then calling :func:`result()` will raise
    RemoteCallException with a transcript of the original exception.

    See `concurrent.futures.Future` in the Python documentation for more information.
    """

    def __init__(self, client, call_id):
        concurrent.futures.Future.__init__(self)
        self.client = client
        self.call_id = call_id
        self.invocation_stack = traceback.extract_stack()

    def cancel(self):
        return False

    def result(self, timeout=None):
        """Return the result of this Future.

        If the result is not yet available, then this call will block until
        the result has arrived or the timeout elapses.
        """
        try:
            self.client.process_until_future(self, timeout=timeout)
            return super().result()
        except Exception as e:
            e.add_note(
                # WARNING: this string is used to parse out notes above
                f"This exception was caused by a remote call to {self.client.address.decode()} with ID"
                f" {self.call_id}. The call was made from the following stack:\n"
                f"{''.join(traceback.format_list(self.invocation_stack))}\n==============\n"
            )
            raise e
