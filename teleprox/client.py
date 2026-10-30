# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import atexit
import collections
import concurrent.futures
import contextlib
import itertools
import logging
import re
import socket as socket_mod
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
from .log import DEBUG1, DEBUG2, DEBUG3

logger = logging.getLogger(__name__)


# Process-level provider called before each outgoing call_obj to supply extra opts.
# Set via set_call_opts_provider(). Signature: () -> dict | None
_call_opts_provider = None


def set_call_opts_provider(fn):
    """Register a process-level provider that adds extra opts to every outgoing call_obj.

    The provider is called with no arguments before each call_obj request and should
    return a dict of extra opts to merge into the call, or None.  Only one provider
    can be registered at a time; calling this again replaces the previous one.

    Use this to attach call-time metadata (e.g. tracing context) that the receiving
    RPCServer can inspect via a complementary hook registered with
    :func:`teleprox.server.set_call_context_hook`.
    """
    global _call_opts_provider
    _call_opts_provider = fn


def _close_all_clients():
    """Close every live client, releasing their zmq sockets before the context goes."""
    for client in RPCClient.all_clients():
        try:
            client.close()
        except Exception:
            logger.debug("Error closing RPC client at exit", exc_info=True)


atexit.register(_close_all_clients)


def _wait_for_future(future, timeout):
    """Block until *future* is done or *timeout* elapses; return whether it is done."""
    done, _ = concurrent.futures.wait([future], timeout=timeout)
    return bool(done)


# Per-thread socketpair used to break a zmq poll when a Future resolves, so a
# thread serving its own requests can block on both at once.
_waiter_pipes = threading.local()


def _waiter_pipe():
    """Return this thread's (read, write) socketpair for interrupting a poll."""
    pipe = getattr(_waiter_pipes, 'pipe', None)
    if pipe is None:
        read_end, write_end = socket_mod.socketpair()
        read_end.setblocking(False)
        write_end.setblocking(False)
        pipe = _waiter_pipes.pipe = (read_end, write_end)
    return pipe


def _notify_socket(sock):
    """Make *sock*'s peer readable, ignoring a buffer that is already full."""
    try:
        sock.send(b'\0')
    except OSError:
        pass


def _drain_socket(sock):
    """Consume everything pending on *sock*."""
    while True:
        try:
            if not sock.recv(4096):
                return
        except OSError:
            return


class RPCClient(object):
    """Connection to an :class:`RPCServer`.

    Each RPCClient connects to only one server, and there is at most one client
    per server address in a process. Clients may be used from any thread: a
    dedicated I/O thread owns the zmq socket, and callers hand requests to it and
    wait on a :class:`Future`. RPCClient instances are created automatically
    either through :class:`start_process` or by requesting attributes from an
    :class:`ObjectProxy`. In general, it is not necessary for the user to interact
    directly with RPCClient.

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
            Start a dedicated RPCServer with no thread of its own, which this client's
            I/O thread reads only while a call is outstanding. This allows the client to
            proxy objects intended for use during the individual remote calls, but not
            outside of them: a request that arrives while the client is idle waits.
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

    # Clients are shared by every thread in the process. The local server is part
    # of the key because it decides which address the remote end calls back on,
    # so connections that proxy through different local servers stay distinct.
    clients_by_address = {}  # (rpc_addr, local_server): client
    clients_by_address_lock = threading.Lock()
    _connection_counter = itertools.count()
    # One per key, held while that connection is being built; see get_client.
    _build_locks = {}

    @classmethod
    def all_clients(cls):
        """Return a list of all live clients in this process."""
        with cls.clients_by_address_lock:
            return list(cls.clients_by_address.values())

    @staticmethod
    def get_client(address, create=True, **kwargs):
        """Return this process's RPC client for a given server address.

        If no client exists already, then a new one will be created. The returned
        client may be used from any thread.

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

        key = (address, kwargs.get('local_server', None))

        # Return an existing client if there is one
        with RPCClient.clients_by_address_lock:
            client = RPCClient.clients_by_address.get(key)
            if client is not None and (client._is_closed or client._disconnected):
                # An address outlives the connection that had it: the port may
                # belong to a live server by now, so this one cannot keep the key.
                RPCClient.clients_by_address.pop(key, None)
                client = None
            if client is None and create:
                build_lock = RPCClient._build_locks.setdefault(key, threading.RLock())

        if client is not None:
            kwargs.pop('local_server', None)
            if kwargs:
                raise ValueError(
                    "Cannot pass arguments to get_client() if it already exists for this address."
                )
            return client

        if not create:
            return None

        # Build one connection at a time per key, so that threads arriving
        # together end up sharing one rather than each opening their own.
        with build_lock:
            with RPCClient.clients_by_address_lock:
                client = RPCClient.clients_by_address.get(key)
            if client is not None:
                return client
            return RPCClient(address, **kwargs)

    @classmethod
    def forget_client(cls, client):
        """Forget a client that is no longer needed."""
        with cls.clients_by_address_lock:
            keys_to_remove = [k for k, c in cls.clients_by_address.items() if c is client]
            for key in keys_to_remove:
                cls.clients_by_address.pop(key, None)

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

        # Guards making close() idempotent and safe to call from close(), the
        # atexit hook, and __del__.
        self._is_closed = False
        self._close_lock = threading.Lock()
        # Set up properly below; named here so close() can run after a failed
        # __init__ without tripping over missing attributes.
        self._socket = None
        self._io_thread = None
        self._io_stop = threading.Event()
        self._wake_r = self._wake_w = None
        self._serviced_server = None

        # pick a unique name: host.pid.connN:rpc_addr. This becomes the socket's
        # zmq IDENTITY, and a ROUTER refuses a second peer claiming an identity it
        # already has -- so connections that share an address must still differ.
        conn_id = next(RPCClient._connection_counter)
        self.name = (
            f"{log.get_host_name()}.{log.get_process_name()}"
            f".conn{conn_id}:{address.decode()}"
        ).encode()

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

            logger.log(DEBUG3, "RPC connect to %s", address.decode())
            self._socket.connect(address)
            self.next_request_id = 0
            self.futures = weakref.WeakValueDictionary()

            # Requests queued by caller threads, sent by the I/O thread. The lock
            # also guards next_request_id and futures, so request ids are assigned
            # and queued in the same order they go out on the wire.
            self._outbox = collections.deque()
            self._send_lock = threading.Lock()
            # send() does not return until the I/O thread has handed its message
            # to zmq, so that anything the caller does next -- closing the server,
            # sending on another socket -- still happens after it on the wire.
            self._queued_count = 0
            self._sent_count = 0
            self._sent_cond = threading.Condition(self._send_lock)
            # Events set once the I/O thread has worked through everything that
            # had already arrived; see _sync_io.
            self._io_markers = []
            # Wakes the I/O thread out of poll() when a caller queues a request.
            # A socketpair rather than an inproc socket: any thread may write to
            # it, and no zmq socket is ever touched off the I/O thread.
            self._wake_r, self._wake_w = socket_mod.socketpair()
            self._wake_r.setblocking(False)
            self._wake_w.setblocking(False)
            # zmq.Poller reports a non-zmq socket by file descriptor, not by the
            # object registered, so results are matched against this.
            self._wake_fd = self._wake_r.fileno()
            self._wake_pending = False
            self._io_poller = None
            self._serving_poller = None

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

            # From here on the socket belongs to the I/O thread; no other thread
            # may touch it. Starting the thread is the handoff barrier.
            self._io_thread = threading.Thread(
                target=self._run_io, name=f"rpc-io:{address.decode()}", daemon=True
            )
            self._io_thread.start()

            self.ensure_connection()

            # Registered only now that it is usable: callers look clients up
            # without holding the build lock, so a half-connected client in this
            # table would be handed out and used.
            # Keyed by the resolved server, so a proxy asking for this connection
            # by its server instance finds it even though it was requested by name.
            key = (address, self._local_server)
            with RPCClient.clients_by_address_lock:
                existing = RPCClient.clients_by_address.get(key)
                # A client whose server is gone keeps its registration so that
                # proxies still being cleaned up get the disconnected error
                # rather than a reconnect. It does not own the address, though:
                # the port may since have been taken by a live server.
                if existing is not None and not (existing._is_closed or existing._disconnected):
                    raise KeyError(
                        "An RPCClient instance already exists for this address."
                        " Use RPCClient.get_client(address) instead."
                    )
                RPCClient.clients_by_address[key] = self
        except Exception:
            self.close()
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

    def _server_needing_service(self):
        """Return the local server whose socket this client's I/O thread must read.

        A local server that has its own reader -- a ``"threaded"`` server, or a
        :class:`QtRPCServer` with its poll thread -- reads its own socket and must
        not be touched here. A ``"lazy"`` server has no reader of its own, so this
        client drives it. Only one client may do so; the rest see the claim fail.
        """
        server = self._local_server
        if server is None or isinstance(server, QtRPCServer) or not server.is_lazy:
            return None
        return server if server.claim_lazy_service() else None

    def _run_io(self):
        """Own the client socket: send queued requests and dispatch replies.

        This thread is the socket's only user for the client's whole life, which
        is what lets callers on any thread share one connection.
        """
        self._io_poller = zmq.Poller()
        self._io_poller.register(self._socket, zmq.POLLIN)
        self._io_poller.register(self._wake_r, zmq.POLLIN)
        self._serviced_server = self._server_needing_service()
        if self._serviced_server is not None:
            self._serving_poller = zmq.Poller()
            self._serving_poller.register(self._socket, zmq.POLLIN)
            self._serving_poller.register(self._wake_r, zmq.POLLIN)
            self._serving_poller.register(self._serviced_server._socket, zmq.POLLIN)

        try:
            while not self._io_stop.is_set():
                try:
                    self._io_step(timeout=0.1)
                except zmq.error.ZMQError:
                    raise
                except Exception:
                    # A bad message must not take the transport down with it; the
                    # waiting Future times out instead.
                    logger.warning(
                        "Error processing RPC message from %s", self.address.decode(), exc_info=True
                    )
        except zmq.error.ZMQError:
            logger.log(DEBUG2, "RPC io thread for %s lost its socket", self.address.decode())
        finally:
            # Anything still queued was accepted by send(); zmq's linger carries
            # it even though we are on our way out.
            with contextlib.suppress(zmq.error.ZMQError):
                self._flush_outbox()
            self._server_disconnected_locally()
            if self._serviced_server is not None:
                self._serviced_server.release_lazy_service()
            self._socket.close()
            self._release_io_markers()

    def _io_step(self, timeout):
        """Flush queued requests, then process whatever has arrived.

        Only ever called on the I/O thread, either from its loop or re-entrantly
        from :func:`process_until_future` when a local request handler running on
        this thread makes a call of its own.
        """
        wait = None if timeout is None else timeout * 1000
        while True:
            self._flush_outbox()
            socks = dict(self._current_poller().poll(wait))
            if not socks:
                # Nothing was waiting, so everything received so far is processed.
                self._release_io_markers()
                return
            if self._wake_fd in socks:
                # Cleared first, so a nudge racing the drain still gets written.
                self._wake_pending = False
                _drain_socket(self._wake_r)
            if self._socket in socks:
                msg = self.serializer.loads(
                    self._socket.recv(), proxy_opts=self.default_proxy_options
                )
                self.process_msg(msg)
            if self._serviced_server is not None and self._serviced_server._socket in socks:
                self._serviced_server.read_and_process_one()
            if self._io_stop.is_set():
                return
            # Keep going while messages are already in hand rather than paying
            # for another wakeup per message.
            wait = 0

    def _current_poller(self):
        """Return the poller to block on right now.

        A lazy local server is read only while this client has a call
        outstanding, which is what "lazy" promises: it answers requests that
        arise from the calls we make, and stays silent the rest of the time.
        """
        if self._serviced_server is None:
            return self._io_poller
        with self._send_lock:
            call_in_flight = len(self.futures) > 0
        return self._serving_poller if call_in_flight else self._io_poller

    def _flush_outbox(self):
        """Send every request queued by caller threads. I/O thread only.

        Taken as a batch: under load this is the difference between two lock
        acquisitions per message and two per wakeup.
        """
        with self._send_lock:
            if not self._outbox:
                return
            batch = list(self._outbox)
            self._outbox.clear()
        for msg in batch:
            self._socket.send_multipart(msg)
        with self._sent_cond:
            self._sent_count += len(batch)
            self._sent_cond.notify_all()

    def _wait_until_sent(self, queue_position, timeout=10.0):
        """Block until the I/O thread has put our queued message on the socket."""
        deadline = time.perf_counter() + timeout
        with self._sent_cond:
            while self._sent_count < queue_position:
                if not self._io_thread.is_alive():
                    raise RuntimeError("Cannot send request; client is closed.")
                if not self._sent_cond.wait(timeout=max(0, deadline - time.perf_counter())):
                    raise TimeoutError("Timed out queueing request to the RPC io thread.")

    def _wake_io(self):
        """Nudge the I/O thread out of poll() to pick up newly queued requests.

        One pending nudge is enough however many callers queued, and the I/O
        thread flushes the whole outbox when it wakes.
        """
        if self._wake_pending:
            return
        self._wake_pending = True
        _notify_socket(self._wake_w)

    def _release_io_markers(self):
        """Release threads waiting in :func:`_sync_io`."""
        with self._send_lock:
            markers, self._io_markers = self._io_markers, []
        for marker in markers:
            marker.set()

    def _sync_io(self, timeout=1.0):
        """Block until the I/O thread has worked through everything already received.

        The socket is read on another thread now, so a message that has arrived
        is not necessarily processed yet. Callers that need to act on what the
        server has already told us wait here first.
        """
        io_thread = self._io_thread
        if (
            io_thread is None
            or not io_thread.is_alive()
            or io_thread is threading.current_thread()
        ):
            return
        marker = threading.Event()
        with self._send_lock:
            self._io_markers.append(marker)
        self._wake_io()
        marker.wait(timeout)

    def _server_disconnected_locally(self):
        """Fail pending futures when the I/O thread stops for any reason."""
        if not self._disconnected:
            self.server_disconnected()

    def disconnected(self):
        """Boolean indicating whether the server has disconnected from the client."""
        if not self._disconnected:
            # A disconnect may be sitting unread; report it now rather than on
            # some later call.
            self._sync_io()
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

        # Serialize before taking a request id: this is where unproxyable
        # arguments raise, and the caller should see that rather than a dead
        # request id in the middle of the sequence.
        if opts is None:
            opts_str = b''
        else:
            opts_str = self.serializer.dumps(opts, serialize_types=self.serialize_types)
        ser_type = self.serializer.type.encode()

        fut = None
        with self._send_lock:
            if sync == 'off':
                req_id = -1
            else:
                req_id = self.next_request_id
                self.next_request_id += 1
                fut = Future(self, req_id)
                self.futures[req_id] = fut
            self._outbox.append(
                [
                    str(req_id).encode(),
                    action.encode(),
                    return_type.encode(),
                    ser_type,
                    opts_str,
                ]
            )
            self._queued_count += 1
            queue_position = self._queued_count
        logger.log(DEBUG2, "RPC request '%s' to %s [req_id=%s]", action, self.address.decode(), req_id)
        logger.log(DEBUG1, "    => sync=%s return=%s opts=%s", sync, return_type, opts)
        self._wake_io()
        if threading.current_thread() is self._io_thread:
            # We are the I/O thread: nobody else will flush for us.
            self._flush_outbox()
        elif sync != 'sync':
            # Callers that carry on immediately need to know the request is on
            # the wire before they do anything that depends on it arriving.
            # A 'sync' caller does not: it blocks below until the reply is in.
            self._wait_until_sent(queue_position)

        if sync == 'off':
            return

        if action == 'close':
            # for server closure we require a little special handling
            fut.add_done_callback(self._close_request_returned)

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
        if _call_opts_provider is not None:
            extra = _call_opts_provider()
            if extra:
                opts.update(extra)
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

        Ordinarily this just waits for the I/O thread to deliver the result. Two
        callers do their own work while waiting: a handler running on the I/O
        thread pumps that thread's loop so a nested call can complete, and the Qt
        main thread keeps its event loop turning so a :class:`QtRPCServer` can
        answer requests that arrive meanwhile.

        Parameters
        ----------
        future : concurrent.Future instance
            The Future to wait for. When the response for this Future arrives
            from the server, the method returns.
        timeout : float
            Maximum time (seconds) to wait for a response.
        """
        if threading.current_thread() is self._io_thread:
            self._pump_until_future(future, timeout)
        elif isinstance(self._local_server, QtRPCServer):
            self._process_qt_events_until_future(future, timeout)
        elif self._local_server is not None and self._local_server.running_in_this_thread():
            self._serve_local_requests_until_future(future, timeout)
        elif not _wait_for_future(future, timeout):
            raise TimeoutError("Timeout waiting for Future result.")

    def _pump_until_future(self, future, timeout):
        """Drive the I/O loop until *future* resolves. I/O thread only.

        Reached when a request handler running on this thread calls back out
        through this client. Blocking here would stop the only thread able to
        read the reply, so we keep the loop turning instead.
        """
        start = time.perf_counter()
        while not future.done():
            if timeout is not None and time.perf_counter() - start > timeout:
                raise TimeoutError("Timeout waiting for Future result.")
            self._io_step(timeout=0.05)

    def _serve_local_requests_until_future(self, future, timeout):
        """Wait for *future* while this thread keeps reading its own server socket.

        Reached when the local server's run thread calls out through this client.
        That thread is the only reader of the server socket, so blocking here
        would strand any request the remote end sends while it waits for our
        reply -- including the reply we are waiting for.
        """
        server = self._local_server
        wake_r, wake_w = _waiter_pipe()
        _drain_socket(wake_r)
        future.add_done_callback(lambda fut: _notify_socket(wake_w))

        poller = zmq.Poller()
        poller.register(server._socket, zmq.POLLIN)
        poller.register(wake_r, zmq.POLLIN)

        start = time.perf_counter()
        while not future.done():
            if timeout is None:
                itimeout = None
            else:
                itimeout = timeout - (time.perf_counter() - start)
                if itimeout < 0:
                    raise TimeoutError("Timeout waiting for Future result.")
                itimeout *= 1000
            socks = dict(poller.poll(itimeout))
            if wake_r.fileno() in socks:
                _drain_socket(wake_r)
            if server._socket in socks:
                server.read_and_process_one()

    def _process_qt_events_until_future(self, future, timeout):
        """Wait for *future* while letting the Qt event loop run.

        A QtRPCServer executes requests in the Qt main thread; if that thread
        blocks here, requests arriving in the meantime are never answered.
        """
        from .qt import QApplication

        start = time.perf_counter()
        while not future.done():
            if timeout is not None and time.perf_counter() - start > timeout:
                raise TimeoutError("Timeout waiting for Future result.")
            QApplication.processEvents()
            _wait_for_future(future, 0.01)

    def process_msg(self, msg):
        """Handle one message received from the remote process.

        This takes care of assigning return values or exceptions to existing
        Future instances.
        """
        logger.log(DEBUG2,
            "RPC recv result from %s [req_id=%s]",
            self.address.decode(),
            msg.get('req_id', None),
        )
        logger.log(DEBUG1, f"    => {msg}")
        if msg['action'] == 'return':
            req_id = msg['req_id']
            with self._send_lock:
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
            self.server_disconnected()
        else:
            raise ValueError(f"Invalid action '{msg['action']}'")

    def _close_request_returned(self, fut):
        try:
            if fut.result() is True:
                # We requested a server closure and the server complied; now
                # handle the disconnect.
                self.server_disconnected()
        except RuntimeError:
            # might have already disconnected before this request finished.
            if self.disconnected():
                pass
            raise

    def server_disconnected(self):
        """Handle server disconnection; inform all pending futures.

        This method is called when the server has disconnected from the client.
        It may be triggered in multiple ways:

        * this client requested that the server close and it returned True
        * another client requested that the server close and this client
          received a preemptive disconnect message from the server.
        * the process managing the server called kill() and explicitly notifies
          this client.
        """
        self._disconnected = True
        logger.log(DEBUG2, "Received server disconnect from %s", self.address)
        # Nothing can be sent or received on this connection again, so retire the
        # I/O thread rather than leave one parked for every server that has gone.
        # The client stays registered, so later callers (notably ObjectProxy
        # cleanup) still find it and get the disconnected error rather than an
        # attempt to reconnect to a server that is gone.
        self._io_stop.set()
        exc = RuntimeError("Cannot receive result; server has already disconnected.")
        with self._send_lock:
            pending = list(self.futures.values())
            self.futures.clear()
        for fut in pending:
            if not fut.done():
                fut.set_exception(exc)

    def ping(self, sync='sync', **kwds):
        """Ping the server.

        This can be used to test connectivity to the server.
        """
        return self.send('ping', sync=sync, **kwds)

    def close(self, timeout=2.0):
        """Close this client's socket (but leave the server running).

        The socket is released by the I/O thread that owns it, so this blocks
        until that thread has stopped. Idempotent: may be called from ``close()``,
        the atexit hook, or ``__del__`` without closing twice.
        """
        with self._close_lock:
            if self._is_closed:
                return
            self._is_closed = True
        # reference management is disabled for now..
        # self.send('release_all', return_type=None)
        RPCClient.forget_client(self)

        self._io_stop.set()
        io_thread = self._io_thread
        if io_thread is None:
            # No I/O thread ever ran (a failed __init__), so the socket is still
            # ours to release.
            if self._socket is not None:
                self._socket.close()
            io_stopped = True
        elif io_thread is threading.current_thread():
            # Called from a request handler running on the I/O thread; the loop
            # will unwind and release the socket on its way out.
            io_stopped = False
        else:
            self._wake_io()
            io_thread.join(timeout=timeout)
            io_stopped = not io_thread.is_alive()
            if not io_stopped:
                logger.warning(
                    "RPC client io thread for %s did not stop within %ss",
                    self.address.decode(),
                    timeout,
                )

        if io_stopped:
            # Only safe once nothing is polling them.
            for sock in (self._wake_r, self._wake_w):
                if sock is not None:
                    sock.close()

        if getattr(self, '_manage_local_server', False):
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
        if hasattr(self, '_socket') and not sys.is_finalizing():
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
                f"- This exception was caused by a remote call to {self.client.address.decode()} with ID"
                f" {self.call_id}. The call was made from the following stack:\n"
                f"{''.join(traceback.format_list(self.invocation_stack))}\n==============\n"
            )
            e.add_note(
                f"- The remote exception traceback was:\n"
                f"{''.join(getattr(e, 'tb_str', []))}"
            )
            raise e
