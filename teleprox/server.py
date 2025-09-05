# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import atexit
import builtins
import logging
import sys
import threading
import traceback

import zmq

from . import log
from . import serializer
from .proxy import ObjectProxy
from .timer import Timer

logger = logging.getLogger(__name__)


class RPCServer(object):
    """Remote procedure call server for invoking requests on proxied objects.

    RPCServer instances are automatically created when using :class:`start_process`.
    It is rarely necessary for the user to interact directly with RPCServer.

    Parameters
    ----------
    address : URL
        Address for RPC server to bind to. Default is ``'tcp://127.0.0.1:*'``.

        **Note:** binding RPCServer to a public IP address is a potential
        security hazard.
    serialize_types : Enumerable of types | None
        List of types that should not be wrapped in an ObjectProxy when
        sent to a remote client. This is used to avoid wrapping objects
        that are already proxies, or that are not safe to proxy.
        Default is `serializer.default_serialize_types`.
    _run_thread : bool
        INTERNAL USE ONLY. If True, then the server will run in a separate
        thread.

    Notes
    -----

    * use :class:`QtRPCServer` to proxy into a qt-enabled process.

    * **RPCServer is not a secure server.** It is intended to be used only on trusted
        networks; anyone with tcp access to the server can execute arbitrary code
        on the server.

    * RPCServer is not a thread-safe class. Possibly use a :class:`RPCClient` to
        communicate with RPCServer from other threads.

    Examples
    --------

    ::

        # In host/process/thread 1:
        server = RPCServer()
        rpc_addr = server.address

        # Publish an object for others to access easily
        server['object_name'] = MyClass()


        # In host/process/thread 2: (you must communicate rpc_addr manually)
        client = RPCClient(rpc_addr)

        # Get a proxy to published object; use this (almost) exactly as you
        # would a local object:
        remote_obj = client['object_name']
        remote_obj.method(...)

        # Or, you can remotely import and operate a module:
        remote_module = client._import("my.module.name")
        remote_obj = remote_module.MyClass()
        remote_obj.method(...)

        # See ObjectProxy for more information on interacting with remote
        # objects, including (a)synchronous communication.

    """

    def __init__(self, address="tcp://127.0.0.1:*", serialize_types=None, _run_thread=True):
        """Initialize the RPC server."""
        self._socket = zmq.Context.instance().socket(zmq.ROUTER)

        self._serialize_types = serialize_types

        # socket will continue attempting to deliver messages up to 5 sec after
        # it has closed. (default is -1, which can cause processes to hang
        # on exit)
        self._socket.linger = 5000

        self._socket.bind(address)
        #: The zmq address where this server is listening (e.g. 'tcp:///127.0.0.1:5678')
        self.address = self._socket.getsockopt(zmq.LAST_ENDPOINT)
        self._closed = False

        # Clients may make requests using any supported serializer, so we should
        # have one of each ready.
        self._serializers = {}
        for ser in serializer.all_serializers.values():
            self._serializers[ser.type] = ser(self)

        # keep track of all clients we have seen so that we can inform them
        # when the server exits.
        self._clients = {}  # {socket_id: serializer_type}

        self._run_thread = None
        self.is_lazy = not _run_thread

        # Objects that may be retrieved by name using client['obj_name']
        self._namespace = {'self': self}

        # Information about objects for which we have sent proxies to other machines.
        # "object ID" is an integer that uniquely identifies each object that
        # has been proxied. Multiple requests for the same object will return
        # proxies with the same object ID. We do _not_ use id(obj) here because
        # Python may re-use these IDs over time.
        self._next_object_id = 0  # uniquely identifies proxied objects
        # "ref ID" is an integer that uniquely identifies a single proxy as it
        # is sent. Multiple requests for the same object will each have a
        # different ref ID. These are used for remote reference counting to
        # ensure that local objects stay alive as long as a remote proxy might
        # still exist for the object.
        self._next_ref_id = 0  # uniquely identifies a proxy reference
        self._proxy_refs = {}  # obj_id: [object, set(refs)]
        self._proxy_id_map = {}  # id(obj): obj_id

        # Make sure we inform clients of closure
        atexit.register(self._atexit)
        if _run_thread:
            self._run_in_thread()

    def __repr__(self):
        return f"<RPCServer {self.address.decode()}>"

    @property
    def serialize_types(self):
        return self._serialize_types or serializer.default_serialize_types

    def get_proxy(self, obj, **kwds):
        """Return an ObjectProxy referring to a local object.

        This proxy can be sent via RPC to any other node.
        """
        rid = self._next_ref_id
        self._next_ref_id += 1
        oid = self._get_object_id(obj)
        type_str = str(type(obj))
        proxy = ObjectProxy(
            self.address,
            oid,
            rid,
            self,
            type_str,
            attributes=(),
            server_is_lazy=self.is_lazy,
            **kwds,
        )
        proxy_ref = self._proxy_refs.setdefault(oid, [obj, set()])
        proxy_ref[1].add(rid)
        # logger.debug("server %s add proxy %d: %s", self.address, oid, obj)
        return proxy

    def _get_object_id(self, obj):
        oid = self._proxy_id_map.get(id(obj), None)
        if oid is None:
            oid = self._next_object_id
            self._next_object_id += 1
            self._proxy_id_map[id(obj)] = oid
        return oid

    def unwrap_proxy(self, proxy):
        """Return the local python object referenced by *proxy*."""
        try:
            oid = proxy._obj_id
            obj = self._proxy_refs[oid][0]
        except KeyError as e:
            raise KeyError(
                f"Invalid proxy object ID {proxy.obj_id!r}."
                " The object may have been released already."
            ) from e
        for attr in proxy._attributes:
            obj = getattr(obj, attr)
        # logger.debug("server %s unwrap proxy %d: %s", self.address, oid, obj)
        return obj

    def __getitem__(self, key):
        return self._namespace[key]

    def __setitem__(self, key, value):
        """Define an object that may be retrieved by name from the client."""
        self._namespace[key] = value

    @staticmethod
    def _read_one(socket):
        parts = socket.recv_multipart()
        if len(parts) != 6:
            raise ValueError(f"Invalid RPC message: expected 6 parts, got {len(parts)}: {parts}")
        name, req_id, action, return_type, ser_type, opts = parts

        msg = {
            'req_id': int(req_id),
            'action': action.decode(),
            'return_type': return_type.decode(),
            'ser_type': ser_type.decode(),
            'opts': opts,
        }
        return name, msg

    def _read_and_process_one(self):
        """Read one message from the rpc socket and invoke the requested
        action.
        """
        if not self.running:
            raise RuntimeError("RPC server socket is already closed.")

        name, msg = self._read_one(self._socket)
        self._process_one(name, msg)

    def _process_one(self, caller, msg):
        """
        Invoke the requested action.

        This method sends back to the client either the return value or an
        error message.
        """
        ser_type = msg['ser_type']
        action = msg['action']
        req_id = msg['req_id']
        return_type = msg.get('return_type', 'auto')

        # remember this caller so we can deliver a disconnect message later
        self._clients[caller] = ser_type

        # Attempt to read message and invoke requested action
        try:
            try:
                ser = self._serializers[ser_type]
            except KeyError as e:
                raise ValueError(f"Unsupported serializer '{ser_type}'") from e
            opts = msg.pop('opts', None)

            logger.debug("RPC recv '%s' from %s [req_id=%s]", action, caller.decode(), req_id)
            logger.debug("    => %s", msg)
            if opts == b'':
                opts = None
            else:
                opts = ser.loads(opts, proxy_opts={})
            logger.debug("    => opts: %s", opts)

            result = self.process_action(action, opts, return_type, caller)
            exc = None
        except Exception:
            logger.exception("    => Exception while processing request %d", req_id)
            exc = sys.exc_info()

        # Send result or error back to client
        if req_id >= 0:
            if exc is None:
                if return_type == 'auto':
                    result = self.auto_proxy(result, self.serialize_types)
                elif return_type == 'proxy':
                    result = self.get_proxy(result)

                try:
                    self._send_result(caller, req_id, rval=result)
                except Exception:
                    logger.exception("    => Failed to send result for %d", req_id)
                    exc = sys.exc_info()
                    self._send_error(caller, req_id, exc)
            else:
                logger.warning("    => returning exception for %d: %s", req_id, exc)
                self._send_error(caller, req_id, exc)

        elif exc is not None:
            # An exception occurred, but client did not request a response.
            # Instead we will dump the exception here.
            sys.excepthook(*exc)

        if action == 'close':
            self._final_close()

    def _send_error(self, caller, req_id, exc):
        exc_str = ["Error while processing request %s [%d]: " % (caller.decode(), req_id)]
        exc_str += traceback.format_stack()
        exc_str += [" < exception caught here >\n"]
        exc_str += traceback.format_exception(*exc)

        # Create structured traceback data for the log viewer
        remote_stack_info = ''.join(traceback.format_stack())
        remote_exc_traceback = ''.join(traceback.format_exception(*exc))

        # Send both legacy format and structured data
        error_data = {
            'type': exc[0].__name__,
            'traceback': exc_str,  # Legacy list of strings for compatibility
            'remote_stack_info': remote_stack_info,  # Stack where exception was caught
            'remote_exc_traceback': remote_exc_traceback,  # Original exception traceback
        }
        self._send_result(caller, req_id, error=error_data)

    def _send_result(self, caller, req_id, rval=None, error=None):
        result = {'action': 'return', 'req_id': req_id, 'rval': rval, 'error': error}
        logger.info("RPC send result to %s [rpc_id=%s]", caller.decode(), result['req_id'])
        logger.debug("    => %s", result)

        # Select the correct serializer for this client
        ser = self._serializers[self._clients[caller]]

        # Serialize and return the result
        data = ser.dumps(result, serialize_types=self.serialize_types)
        self._socket.send_multipart([caller, data])

    def process_action(self, action, opts, return_type, caller):
        """Invoke a single action and return the result."""
        if action == 'call_obj':
            obj = opts['obj']
            fnargs = opts.get('args', ())
            fnkwds = opts.get('kwargs', {})

            # need to do this because some functions do not allow keyword arguments.
            if len(fnkwds) == 0:
                try:
                    result = obj(*fnargs)
                except Exception:
                    logger.warning("Failed to call object %s: %d, %s", obj, len(fnargs), fnargs[1:])
                    raise
            else:
                result = obj(*fnargs, **fnkwds)
            # logger.debug("    => call_obj result: %r", result)
        elif action == 'get_obj':
            result = opts['obj']
        elif action == 'delete':
            proxy_ref = self._proxy_refs[opts['obj_id']]
            proxy_ref[1].remove(opts['ref_id'])
            if len(proxy_ref[1]) == 0:
                del self._proxy_refs[opts['obj_id']]
                del self._proxy_id_map[id(proxy_ref[0])]
            result = None
        elif action == 'get_item':
            result = self[opts['name']]
        elif action == 'set_item':
            self[opts['name']] = opts['obj']
            result = None
        elif action == 'import':
            name = opts['module']
            fromlist = opts.get('fromlist', [])
            mod = builtins.__import__(name, fromlist=fromlist)

            if len(fromlist) == 0:
                parts = name.lstrip('.').split('.')
                result = mod
                for part in parts[1:]:
                    result = getattr(result, part)
            else:
                result = map(mod.__getattr__, fromlist)
        elif action == 'ping':
            result = 'pong'
        elif action == 'close':
            self._closed = True
            # Send a disconnect message to all known clients
            data = {}
            for client, ser_type in self._clients.items():
                if client == caller:
                    # We will send an actual return value to confirm closure
                    # to the caller.
                    continue

                # Select or generate the disconnect message that was serialized
                # correctly for this client.
                if ser_type not in data:
                    ser = self._serializers[ser_type]
                    ser.server = None  # no more server
                    data[ser_type] = ser.dumps({'action': 'disconnect'}, serialize_types=None)
                data_str = data[ser_type]

                # Send disconnect message.
                logger.debug("RPC server sending disconnect message to %r", client)
                self._socket.send_multipart([client, data_str])
            result = True
        else:
            raise ValueError(f"Invalid RPC action '{action}'")

        return result

    def _atexit(self):
        # Process is exiting; do any last-minute cleanup if necessary.
        if not self._closed:
            logger.warning("RPCServer exiting without close()!")
            self.close()

    def close(self):
        """Ask the server to close immediately. Pending requests will be ignored, and the currently active request
        may not send its return value.
        """
        self.process_action('close', None, None, None)

    def _final_close(self):
        # Called after the server has closed and sent its disconnect messages.
        self._socket.close()

    def running(self):
        """Boolean indicating whether the server is still running."""
        return not self._closed

    def run_forever(self):
        """Read and process RPC requests until the server is asked to close."""
        self.is_lazy = False
        self._run_thread = threading.current_thread()
        logger.info(
            f"RPC start server loop: {log.get_host_name()}.{log.get_process_name()}.{log.get_thread_name()}"
            f"@{self.address.decode()}"
        )
        while self.running():
            name, msg = self._read_one(self._socket)
            self._process_one(name, msg)

    def _run_in_thread(self):
        """Call run_forever in a new thread."""
        self._run_thread = threading.Thread(target=self.run_forever, daemon=True)
        self._run_thread.start()

    def client_should_handle_requests(self):
        """Return whether a client is allowed to take over the server's request handling."""
        if self.is_lazy and self.running():
            return True
        return threading.current_thread().ident == self._run_thread.ident

    def auto_proxy(self, obj, no_proxy_types):
        # Return object wrapped in ObjectProxy _unless_ its type is in no_proxy_types.
        for typ in no_proxy_types:
            if isinstance(obj, typ):
                return obj
        return self.get_proxy(obj)

    def start_timer(self, callback, interval, **kwds):
        """Start a timer that invokes *callback* at regular intervals.

        Parameters
        ----------
        callback : Callable
            A Callable object to invoke. This must either be an ObjectProxy or
            an object that is safe to call from the server's thread.
        interval : float
            Minimum time to wait between callback invocations (start to start).
        """
        kwds.setdefault('start', True)
        if not isinstance(callback, ObjectProxy):
            callback = self.get_proxy(callback)
        return Timer(callback, interval, **kwds)
