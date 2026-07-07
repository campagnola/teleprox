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
