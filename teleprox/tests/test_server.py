import logging
import time
import numpy as np
import pytest
import zmq
import teleprox
from teleprox import RPCClient, RPCServer
from teleprox.tests.util import RecordingLogHandler
from teleprox.util import ProcessCleaner


def test_published_objects():
    with ProcessCleaner() as cleaner:
        proc = teleprox.start_process(name='test_published_objects')
        cleaner.add('proc', proc.pid)

        proxy_to_server = proc.client['self']
        assert proxy_to_server.address == proc.client.address

        proc.client['x'] = 1
        assert proc.client['x'] == 1

        ros = proc.client._import('os')
        proc.client['os'] = ros
        assert proc.client['os'].getpid() == proc.pid

        proc.stop()


def test_double_run_in_thread_raises():
    """Starting a second run_forever thread on one socket must be refused.

    Two threads reading a single zmq ROUTER socket corrupts its multipart
    framing (teleprox issue #40), so ``_run_in_thread()`` on a server that is
    already processing in a thread must raise rather than silently spawn a
    second concurrent reader.
    """
    server = RPCServer('tcp://127.0.0.1:*')  # run_thread=True starts one reader
    client = RPCClient.get_client(server.address)
    try:
        with pytest.raises(RuntimeError):
            server._run_in_thread()
        assert client.ping() == 'pong'
        client.close_server()
    finally:
        client.close()


def test_second_run_forever_raises():
    """Calling run_forever on an already-running server must be refused too.

    This closes the direct bypass of the ``_run_in_thread`` guard: starting a
    second reader via ``threading.Thread(target=server.run_forever)`` would also
    corrupt the socket (teleprox issue #40). The guard raises synchronously in
    the calling thread before blocking on the socket.
    """
    server = RPCServer('tcp://127.0.0.1:*')  # run_thread=True starts one reader
    client = RPCClient.get_client(server.address)
    try:
        with pytest.raises(RuntimeError):
            server.run_forever()
        # The original server thread must be unharmed and still serving.
        assert client.ping() == 'pong'
        client.close_server()
    finally:
        client.close()


def test_run_forever_survives_malformed_message():
    """A malformed/partial message is logged and skipped, not fatal to run_forever.

    Previously an unhandled ValueError from ``_read_one`` terminated the server
    thread, leaving the process alive but deaf on teleprox (teleprox issue #40).
    """
    # Record the server's warnings directly; the skip is logged from the server's
    # run_forever thread, which pytest's caplog fixture does not reliably capture.
    server_logger = logging.getLogger('teleprox.server')
    handler = RecordingLogHandler()
    server_logger.addHandler(handler)

    server = RPCServer('tcp://127.0.0.1:*')
    addr = server.address
    try:
        # Send a raw multipart message with the wrong number of parts. The DEALER
        # prepends its identity frame, so the ROUTER sees 3 parts where 6 are
        # expected -- exactly the fragmentation reported in the ticket.
        raw = zmq.Context.instance().socket(zmq.DEALER)
        raw.connect(addr)
        raw.send_multipart([b'ping', b'auto'])
        time.sleep(0.2)  # let the frame deliver and the server process (and skip) it
        raw.close(linger=0)

        client = RPCClient.get_client(addr)
        try:
            # If run_forever died on the malformed message, this ping times out.
            assert client.ping() == 'pong'
            assert handler.find_message('malformed RPC message') is not None
            client.close_server()
        finally:
            client.close()
    finally:
        server_logger.removeHandler(handler)


def test_request_error_log_names_action_caller_and_exception():
    """The failed-request error log must identify the call, not just its id.

    ``RecordingLogHandler.find_message`` matches ``record.msg``, the unrendered
    template, so this asserts on ``getMessage()`` instead -- the template alone
    would match even if the arguments were wrong or missing.
    """
    server_logger = logging.getLogger('teleprox.server')
    handler = RecordingLogHandler()
    server_logger.addHandler(handler)

    server = RPCServer('tcp://127.0.0.1:*')
    client = RPCClient.get_client(server.address)
    try:
        client._import('builtins').exec(
            "def _boom():\n"
            "    raise ValueError('boom')\n"
            "import builtins as _b; _b._boom = _boom\n"
        )
        with pytest.raises(Exception):
            client._import('builtins')._boom()

        rec = handler.find_message('Exception while processing request')
        assert rec is not None
        message = rec.getMessage()
        assert 'action=call_obj' in message
        assert 'ValueError' in message
        assert 'boom' in message
        # The caller is the client's zmq identity, which names the peer.
        assert client._sock_name.decode() in message

        client.close_server()
    finally:
        client.close()
        server_logger.removeHandler(handler)


def test_request_error_log_survives_undecodable_caller():
    """A peer whose zmq identity is not UTF-8 must not kill the server thread.

    The identity is arbitrary bytes chosen by the peer, and it is interpolated
    into the failed-request error log. Evaluating that argument eagerly inside
    the error handler -- and again in its fallback -- let a UnicodeDecodeError
    escape ``_process_one``, which ``run_forever`` does not guard, leaving the
    process alive but deaf on teleprox.
    """
    server = RPCServer('tcp://127.0.0.1:*')
    addr = server.address

    raw = zmq.Context.instance().socket(zmq.DEALER)
    raw.setsockopt(zmq.IDENTITY, b'\xff\xfe not utf-8')
    raw.connect(addr)
    # A well-formed 6-frame request (the DEALER prepends its identity) that
    # carries no call options, so handling it fails and reaches the error log
    # with an undecodable caller.
    raw.send_multipart([b'1', b'call_obj', b'auto', b'msgpack', b''])
    time.sleep(0.2)  # let the frame deliver and the server process it
    raw.close(linger=0)

    client = RPCClient.get_client(addr)
    try:
        # If the error log killed run_forever, this ping times out.
        assert client.ping() == 'pong'
        client.close_server()
    finally:
        client.close()


def test_close_stops_the_server_thread():
    """close() must stop the thread it started, not just raise the closed flag.

    The server thread sits blocked in ``recv_multipart``, and the loop re-reads the
    closed flag only once a message arrives. A close() that sets the flag and
    returns therefore leaves the thread parked on the socket for the life of the
    process; a caller that opens one server per worker thread accumulates them.
    """
    server = RPCServer('tcp://127.0.0.1:*')  # run_thread=True starts the reader
    thread = server._run_thread
    assert thread.is_alive()

    server.close()

    thread.join(timeout=10.0)
    assert not thread.is_alive(), "server thread still running after close()"
    assert not server.running()
    assert server._socket.closed, "server socket still open after close()"


def test_close_releases_the_socket_of_a_lazy_server():
    """A server with no reader thread must still close its socket."""
    server = RPCServer('tcp://127.0.0.1:*', run_thread=False)

    server.close()

    assert not server.running()
    assert server._socket.closed, "server socket still open after close()"
