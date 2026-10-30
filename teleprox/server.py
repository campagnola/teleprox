import atexit
import builtins
import contextlib
import logging
import sys
import threading
import traceback

import zmq

from . import log


# Process-level hook called around each incoming call_obj execution.
# Set via set_call_context_hook(). Signature: (opts: dict) -> context manager
_call_context_hook = None


def set_call_context_hook(fn):
    """Register a process-level hook that wraps every incoming call_obj execution.

    The hook is called with the full opts dict for the call_obj action and must
    return a context manager.  The remote callable is invoked inside that context
    manager, so the hook can set up (and tear down) any per-call state.

    Only one hook can be registered at a time; calling this again replaces the
    previous one.  Pair with :func:`teleprox.client.set_call_opts_provider` to
    propagate metadata from the calling process into the receiving process.
    """
    global _call_context_hook
    _call_context_hook = fn
from . import serializer
from .proxy import ObjectProxy
from .timer import Timer
from .log import DEBUG1, DEBUG2, DEBUG3

logger = logging.getLogger(__name__)


def _caller_name(caller):
    """Return a printable name for a peer's zmq identity.

    The identity is arbitrary bytes chosen by the peer, so it need not be valid
    UTF-8. It is only ever used for display, and it is normally interpolated as
    a logging argument -- which Python evaluates eagerly, at the call site, so a
    UnicodeDecodeError there escapes the request handler rather than being
    absorbed by logging's own error handling.
    """
    return caller.decode(errors='replace')


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
    run_thread : bool
        If True, then the server will process messages in a separate thread. If False, then you
        must either call `run_forever()` to block and process requests, or you must process
        messages individually by calling `read_and_process_one()`. Default is True.

    Notes
    -----

    * use :class:`QtRPCServer` to proxy into a qt-enabled process.

    * **RPCServer is not a secure server.** It is intended to be used only on trusted
        networks; anyone with tcp access to the server can execute arbitrary code
        on the server.

    * Only the proxy bookkeeping is thread-safe; the objects a request touches are
        not. Possibly use a :class:`RPCClient` to communicate with RPCServer from
        other threads.

    * Bad things will happen if this server's socket is read from more than one place
        at a time. Other than `run_forever`, an RPCClient reads it on the server's
        behalf when it is given this server as a local_server without a running thread
        -- one client at a time, which :func:`claim_lazy_service` enforces.

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

    def __init__(self, address="tcp://127.0.0.1:*", serialize_types=None, run_thread=True):
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
        # Proxies are minted on whichever thread is serializing a request, so a
        # server shared by several callers mutates this bookkeeping concurrently.
        self._proxy_lock = threading.RLock()
        # Held by the one reader responsible for a server that has no run thread.
        self._service_lock = threading.Lock()

        # Make sure we inform clients of closure
        atexit.register(self._atexit)
        if run_thread:
            self._run_in_thread()

    @property
    def is_lazy(self):
        """Boolean indicating whether the server is running in "lazy" mode.

        In lazy mode, the server will only process requests when
        `read_and_process_one()` is called (such as when an RPCClient using it as
        its local server reads the socket on the server's behalf).
        """
        return self._run_thread is None or not self._run_thread.is_alive()

    def __repr__(self):
        return f"<RPCServer {self.address.decode()}>"

    @property
    def serialize_types(self):
        return self._serialize_types or serializer.default_serialize_types

    def get_proxy(self, obj, **kwds):
        """Return an ObjectProxy referring to a local object.

        This proxy can be sent via RPC to any other node.
        """
        with self._proxy_lock:
            rid = self._next_ref_id
            self._next_ref_id += 1
            oid = self._get_object_id(obj)
            type_str = str(type(obj))
            proxy = ObjectProxy.get_object_proxy(
                rpc_addr=self.address,
                obj_id=oid,
                ref_id=rid,
                local_server=self,
                type_str=type_str,
                attributes=(),
                server_is_lazy=self.is_lazy,
                **kwds,
            )
            proxy_ref = self._proxy_refs.setdefault(oid, [obj, set()])
            proxy_ref[1].add(rid)
            # logger.debug("server %s add proxy %d: %s", self.address, oid, obj)
            return proxy

    def _get_object_id(self, obj):
        with self._proxy_lock:
            oid = self._proxy_id_map.get(id(obj), None)
            if oid is None:
                oid = self._next_object_id
                self._next_object_id += 1
                self._proxy_id_map[id(obj)] = oid
            return oid

    def release_proxy_ref(self, obj_id, ref_id):
        """Drop one proxy reference, releasing the object if it was the last."""
        with self._proxy_lock:
            proxy_ref = self._proxy_refs[obj_id]
            proxy_ref[1].remove(ref_id)
            if len(proxy_ref[1]) == 0:
                del self._proxy_refs[obj_id]
                del self._proxy_id_map[id(proxy_ref[0])]

    def claim_lazy_service(self):
        """Claim sole responsibility for reading this server's socket.

        Returns True if the caller may read it. A server with no run thread is
        driven by a client's I/O thread; this keeps a second client from reading
        the same socket, which would corrupt its framing.
        """
        return self._service_lock.acquire(blocking=False)

    def release_lazy_service(self):
        """Give up a claim made by :func:`claim_lazy_service`."""
        with contextlib.suppress(RuntimeError):
            self._service_lock.release()

    def unwrap_proxy(self, proxy):
        """Return the local python object referenced by *proxy*."""
        try:
            oid = proxy._obj_id
            with self._proxy_lock:
                obj = self._proxy_refs[oid][0]
        except KeyError as e:
            raise KeyError(
                f"Invalid proxy object ID {proxy.obj_id!r}."
                " The object may have been released already."
            ) from e
        for attr in proxy._attributes:
            try:
                obj = getattr(obj, attr)
            except Exception as e:
                e.add_note(f"Failed to access attribute '{attr}' of object {obj!r} while unwrapping proxy.")
                raise
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

    def read_and_process_one(self):
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
        opts = None
        try:
            try:
                ser = self._serializers[ser_type]
            except KeyError as e:
                raise ValueError(f"Unsupported serializer '{ser_type}'") from e
            opts = msg.pop('opts', None)

            logger.log(DEBUG2, "RPC recv '%s' from %s [req_id=%s]", action, _caller_name(caller), req_id)
            logger.log(DEBUG1, "    => %s", msg)
            if opts == b'':
                opts = None
            else:
                opts = ser.loads(opts, proxy_opts={})
            logger.log(DEBUG1, "    => opts: %s", opts)

            result = self.process_action(action, opts, return_type, caller)
            exc = None
        except Exception:
            exc = sys.exc_info()
            # Re-establish the call's semantic context (whatever the registered
            # context hook installs, e.g. a tracing context) while logging, so a
            # failed call's error record carries the same context the call ran
            # under. The hook was active only inside process_action's `with
            # call_cm` and is gone by the time control reaches here.
            err_ctx = contextlib.nullcontext()
            if _call_context_hook is not None and action == 'call_obj' and isinstance(opts, dict):
                try:
                    err_ctx = _call_context_hook(opts)
                except Exception:
                    err_ctx = contextlib.nullcontext()
            caller_str = _caller_name(caller)
            try:
                with err_ctx:
                    logger.error(
                        "    => Exception while processing request %d (action=%s from %s): %s: %s",
                        req_id, action, caller_str, exc[0].__name__, exc[1],
                        exc_info=exc,
                    )
            except Exception:
                # Deliberately minimal: this runs when the context hook above
                # misbehaves, so it must not depend on anything that could fail
                # for the same reason.
                logger.error(
                    "    => Exception while processing request %d", req_id, exc_info=exc
                )

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
        exc_str = ["Error while processing request %s [%d]: " % (_caller_name(caller), req_id)]
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
        logger.log(DEBUG2, "RPC send result to %s [rpc_id=%s]", _caller_name(caller), result['req_id'])
        logger.log(DEBUG1, "    => %s", result)

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

            call_cm = _call_context_hook(opts) if _call_context_hook is not None else contextlib.nullcontext()
            # need to do this because some functions do not allow keyword arguments.
            with call_cm:
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
            self.release_proxy_ref(opts['obj_id'], opts['ref_id'])
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
                    ser.disable_proxying()
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

    def close(self, timeout=2.0):
        """Ask the server to close immediately. Pending requests will be ignored, and the currently active request
        may not send its return value.

        Blocks for up to *timeout* seconds for a server thread to finish closing.
        A server that cannot be closed -- because the request never reached its
        thread, or because that thread outlasts *timeout* -- says so in the log
        and reports itself still ``running()``.
        """
        if self._closed:
            # Closing releases the socket, so announcing it a second time would
            # write the disconnect messages to a socket that is already gone.
            return
        run_thread = self._run_thread
        if run_thread is not None and run_thread.is_alive() and run_thread is not threading.current_thread():
            # That thread owns the socket, so it is the only one that may close
            # the server; asking it is the only way in, and there is no fallback.
            # Writing or closing the socket from here would leave it parked in
            # recv_multipart on a socket that no longer exists -- the leaked
            # thread this path exists to prevent.
            if not self._request_close():
                logger.error("Could not stop RPC server %s; it is still running", self.address)
                return
            run_thread.join(timeout=timeout)
            if run_thread.is_alive():
                logger.warning("RPC server %s did not stop within %ss of close()", self.address, timeout)
            return
        self.process_action('close', None, None, None)
        self._final_close()

    def _request_close(self):
        """Ask the server thread to close by sending it a close request.

        A thread blocked in ``recv_multipart`` cannot see the closed flag, and its
        socket belongs to it alone -- closing or writing that socket from another
        thread corrupts the framing the thread is mid-read of. So the only way to
        stop the thread is the way any client would: send it a request. It then
        runs the same close path a remote ``close_server()`` takes, releasing the
        socket from the thread that owns it before the thread exits.

        Returns whether the request was sent.
        """
        socket = zmq.Context.instance().socket(zmq.DEALER)
        try:
            socket.linger = 1000  # give the request time to arrive after we let go
            # Name this socket as a client names itself, so the server's logs say
            # where the close request came from.
            name = f"{log.get_host_name()}.{log.get_process_name()}.{log.get_thread_name()}:close"
            socket.setsockopt(zmq.IDENTITY, name.encode())
            socket.connect(self.address)
            # req_id -1 asks for no reply, so nothing is sent back to this socket.
            socket.send_multipart([b'-1', b'close', b'none', next(iter(self._serializers)).encode(), b''])
        except Exception:
            logger.warning("Could not send close request to RPC server %s", self.address, exc_info=True)
            socket.close()
            return False
        socket.close()
        return True

    def _final_close(self):
        # Called after the server has closed and sent its disconnect messages.
        # Reduce linger so we don't block for 5s waiting to deliver notifications
        # to peers that have already disconnected.  50ms is plenty for loopback.
        if self._socket.closed:
            return
        self._socket.linger = 50
        self._socket.close()

    def running(self):
        """Boolean indicating whether the server is still running."""
        return not self._closed

    def run_forever(self):
        """Read and process RPC requests until the server is asked to close."""
        current = threading.current_thread()
        if self._run_thread is not None and self._run_thread is not current and self._run_thread.is_alive():
            raise RuntimeError(
                "RPCServer is already processing requests in another thread; a second"
                " run_forever would read the same zmq socket from two threads and"
                " corrupt its framing (zmq sockets are not thread-safe)."
            )
        self._run_thread = current
        logger.log(DEBUG2,
            f"RPC start server loop: {log.get_host_name()}.{log.get_process_name()}.{log.get_thread_name()}"
            f"@{self.address.decode()}"
        )
        while self.running():
            try:
                name, msg = self._read_one(self._socket)
            except ValueError as exc:
                # A malformed/partial message (wrong number of multipart frames)
                # usually means a single zmq socket is being read from more than
                # one thread, which is not supported. Log and skip it rather than
                # letting the exception escape and kill this server thread, which
                # would leave the process alive but deaf on teleprox.
                logger.warning("Skipping malformed RPC message: %s", exc)
                continue
            self._process_one(name, msg)

    def _run_in_thread(self):
        """Call run_forever in a new thread."""
        if self._run_thread is not None and self._run_thread.is_alive():
            raise RuntimeError(
                "RPCServer is already processing requests in a thread; starting a"
                " second run_forever thread would read the same zmq socket from two"
                " threads and corrupt its framing (zmq sockets are not thread-safe)."
            )
        self._run_thread = threading.Thread(target=self.run_forever, daemon=True)
        self._run_thread.start()

    def running_in_this_thread(self):
        """Return whether the calling thread is the one reading this server's socket."""
        run_thread = self._run_thread
        return run_thread is not None and run_thread.ident == threading.current_thread().ident

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
