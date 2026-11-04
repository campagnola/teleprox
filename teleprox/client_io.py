# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.
"""The I/O thread that owns an RPCClient's zmq socket, and the queue feeding it."""

import collections
import contextlib
import logging
import socket as socket_mod
import threading
import time

import zmq

from .log import DEBUG2
from .qt_server import QtRPCServer

logger = logging.getLogger(__name__)


def notify_socket(sock):
    """Make *sock*'s peer readable, ignoring a buffer that is already full."""
    try:
        sock.send(b'\0')
    except OSError:
        pass


def drain_socket(sock):
    """Consume everything pending on *sock*."""
    while True:
        try:
            if not sock.recv(4096):
                return
        except OSError:
            return


class ClientIO:
    """Sole owner of an :class:`RPCClient`'s zmq socket.

    Callers on any thread hand frames to :func:`queue`; this thread is the only
    one that ever touches the socket, which is what lets one connection be
    shared. It also reads a *lazy* local server's socket, since such a server
    has no reader of its own.

    Its lock is a leaf: no client code runs while it is held, so a caller may
    hold a lock of its own across :func:`queue`.

    Parameters
    ----------
    socket : zmq.Socket
        An already-connected DEALER socket. It belongs to this object from here
        on, and is released either by the I/O thread as it unwinds or by
        :func:`release` if the thread never ran.
    address : bytes
        The remote address, for log messages.
    local_server : RPCServer | None
        The server this client proxies through, if any.
    on_message : callable
        Called on the I/O thread with each raw message received.
    on_disconnect : callable
        Called on the I/O thread once the loop has stopped, before the socket is
        released, so pending calls can be failed.
    on_closed : callable
        Called on the I/O thread as the very last act, once nothing is polling
        any of these sockets.
    """

    def __init__(self, socket, address, local_server, on_message, on_disconnect, on_closed):
        self._socket = socket
        self._address = address
        self._local_server = local_server
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._on_closed = on_closed

        self._lock = threading.Lock()
        self._outbox = collections.deque()
        # queue() waits for this thread to reach zmq, so what the caller does
        # next -- close the server, send on another socket -- follows it.
        self._queued_count = 0
        self._sent_count = 0
        self._sent_cond = threading.Condition(self._lock)
        self._markers = []

        self._stop = threading.Event()
        self._thread = None
        self._released = False

        # A socketpair rather than an inproc socket: any thread may write to it
        # without touching a zmq socket off the I/O thread.
        self._wake_r, self._wake_w = socket_mod.socketpair()
        self._wake_r.setblocking(False)
        self._wake_w.setblocking(False)
        # zmq.Poller reports a non-zmq socket by file descriptor, not by the
        # object registered.
        self._wake_fd = self._wake_r.fileno()
        self._poller = None
        self._serving_poller = None
        self._serviced_server = None

    @property
    def socket(self):
        return self._socket

    @property
    def released(self):
        """Whether the socket and wakeup pipe have been closed."""
        return self._released

    def start(self):
        """Hand the socket over and begin serving it."""
        self._thread = threading.Thread(
            target=self._run, name=f"rpc-io:{self._address.decode()}", daemon=True
        )
        self._thread.start()

    def running(self):
        """Whether the I/O thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def owns_current_thread(self):
        """Whether the caller *is* the I/O thread."""
        return self._thread is threading.current_thread()

    def stop(self):
        """Retire the I/O thread.

        Setting the flag and waking the thread are one act: a caller that does
        only the first leaves it parked in poll() for the rest of its timeout.
        """
        self._stop.set()
        self.wake()

    def join(self, timeout):
        """Wait for the I/O thread to let go of the socket; return whether it has.

        False means the thread is still running: either this *is* that thread,
        which releases the socket as its loop unwinds, or it did not stop in
        time and nothing may touch the socket on its behalf.
        """
        thread = self._thread
        if thread is None:
            # Never started, so there is no thread whose job this is.
            self.release()
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def release(self):
        """Close the socket and the wakeup pipe. Only safe once nothing polls them."""
        self._released = True
        self._socket.close()
        for sock in (self._wake_r, self._wake_w):
            sock.close()

    def wake(self):
        """Nudge the I/O thread out of poll().

        Every request writes its own nudge. Skipping one because another looks
        pending loses wakeups, because the drain is a loop and can swallow a byte
        written just after the thread decided a nudge was handled.
        """
        notify_socket(self._wake_w)

    def queue(self, parts):
        """Hand one message to the I/O thread; return its position in the queue.

        Pass that position to :func:`wait_until_sent` to block until it is on
        the wire.
        """
        with self._lock:
            self._outbox.append(parts)
            self._queued_count += 1
            position = self._queued_count
        self.wake()
        return position

    def wait_until_sent(self, position, timeout=10.0):
        """Block until the I/O thread has put message *position* on the socket."""
        deadline = time.perf_counter() + timeout
        with self._sent_cond:
            while self._sent_count < position:
                if not self.running():
                    raise RuntimeError("Cannot send request; client is closed.")
                if not self._sent_cond.wait(timeout=max(0, deadline - time.perf_counter())):
                    raise TimeoutError("Timed out queueing request to the RPC io thread.")

    def flush(self):
        """Send every request queued by caller threads. I/O thread only.

        Taken as a batch: under load this is the difference between two lock
        acquisitions per message and two per wakeup.
        """
        with self._lock:
            if not self._outbox:
                return
            batch = list(self._outbox)
            self._outbox.clear()
        for msg in batch:
            self._socket.send_multipart(msg)
        with self._sent_cond:
            self._sent_count += len(batch)
            self._sent_cond.notify_all()

    def sync(self, timeout=1.0):
        """Block until the I/O thread has worked through everything already received.

        The socket is read on another thread, so a message that has arrived is
        not necessarily processed yet. Callers that need to act on what the
        server has already told us wait here first.
        """
        if not self.running() or self.owns_current_thread():
            return
        marker = threading.Event()
        with self._lock:
            self._markers.append(marker)
        self.wake()
        marker.wait(timeout)

    def _release_markers(self):
        """Release threads waiting in :func:`sync`."""
        with self._lock:
            markers, self._markers = self._markers, []
        for marker in markers:
            marker.set()

    def _run(self):
        """Own the client socket: send queued requests and dispatch replies.

        This thread is the socket's only user for the client's whole life, which
        is what lets callers on any thread share one connection.
        """
        try:
            self._poller = zmq.Poller()
            self._poller.register(self._socket, zmq.POLLIN)
            self._poller.register(self._wake_r, zmq.POLLIN)
            self._claim_lazy_service()

            while not self._stop.is_set():
                if self._serviced_server is None:
                    self._claim_lazy_service()
                try:
                    self.step(timeout=0.1)
                except zmq.error.ZMQError:
                    raise
                except Exception:
                    # A bad message must not take the transport down; the waiting
                    # Future times out instead.
                    logger.warning(
                        "Error processing RPC message from %s",
                        self._address.decode(),
                        exc_info=True,
                    )
        except zmq.error.ZMQError:
            logger.log(DEBUG2, "RPC io thread for %s lost its socket", self._address.decode())
        finally:
            # Anything still queued was accepted by send(); zmq's linger carries it.
            with contextlib.suppress(zmq.error.ZMQError):
                self.flush()
            self._on_disconnect()
            if self._serviced_server is not None:
                self._serviced_server.release_lazy_service()
            # Nobody is obliged to call close() -- a disconnect ends the client's
            # life without it -- and nothing polls these once this thread is gone.
            self.release()
            self._release_markers()
            self._on_closed()

    def step(self, timeout):
        """Flush queued requests, then process whatever has arrived.

        Only ever called on the I/O thread, either from its loop or re-entrantly
        when a local request handler running on this thread makes a call of its own.
        """
        wait = None if timeout is None else timeout * 1000
        while True:
            self.flush()
            socks = dict(self._current_poller().poll(wait))
            if not socks:
                # Nothing was waiting, so everything received so far is processed.
                self._release_markers()
                return
            if self._wake_fd in socks:
                drain_socket(self._wake_r)
            if self._socket in socks:
                self._on_message(self._socket.recv())
            if self._serviced_server is not None and self._serviced_server._socket in socks:
                self._serviced_server.read_and_process_one()
            if self._stop.is_set():
                return
            # Drain what is already in hand rather than pay a wakeup per message.
            wait = 0

    def _current_poller(self):
        """Return the poller to block on right now.

        A lazy local server is read only while a call is outstanding somewhere,
        which is what "lazy" promises: it answers requests that arise from the
        calls its clients make, and stays silent the rest of the time.
        """
        if self._serviced_server is None:
            return self._poller
        if self._serviced_server.lazy_service_needed():
            return self._serving_poller
        return self._poller

    def _server_needing_service(self):
        """Return the local server whose socket this I/O thread must read.

        A local server that has its own reader -- a ``"threaded"`` server, or a
        :class:`QtRPCServer` with its poll thread -- reads its own socket and must
        not be touched here. A ``"lazy"`` server has no reader of its own, so this
        thread drives it. Only one client may do so; the rest see the claim fail.
        """
        server = self._local_server
        if server is None or isinstance(server, QtRPCServer) or not server.is_lazy:
            return None
        if not server.running():
            return None
        return server if server.claim_lazy_service() else None

    def _claim_lazy_service(self):
        """Take responsibility for reading the local server's socket, if it is free.

        Retried while the loop runs: the client holding the claim may close, and
        whichever client is left has to pick the server up.
        """
        server = self._server_needing_service()
        if server is None:
            return
        self._serviced_server = server
        self._serving_poller = zmq.Poller()
        self._serving_poller.register(self._socket, zmq.POLLIN)
        self._serving_poller.register(self._wake_r, zmq.POLLIN)
        self._serving_poller.register(server._socket, zmq.POLLIN)
