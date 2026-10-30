"""Tests for RPCClient's threading contract: one client per address, usable from any thread."""

import threading

from teleprox import RPCClient, RPCServer, start_process
from teleprox.tests.test_rpc import setup_callback_tester


def test_get_client_returns_the_same_client_in_every_thread():
    """One address means one client, no matter which thread asks for it."""
    server = RPCServer()
    try:
        main_client = RPCClient.get_client(server.address)
        found = []

        def worker():
            found.append(RPCClient.get_client(server.address))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert found == [main_client] * 4
    finally:
        main_client.close()
        server.close()


def test_threads_racing_to_create_one_client_all_get_a_working_one():
    """Only one thread builds a connection; the rest wait for it, not for a husk.

    A client is registered before it finishes connecting, so a second thread
    asking for the same address must not be handed one that is still being set
    up.
    """
    server = RPCServer()
    clients = []
    errors = []
    start = threading.Barrier(6)

    def worker():
        try:
            start.wait()
            client = RPCClient.get_client(server.address)
            assert client.ping() == 'pong'
            clients.append(client)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert errors == []
        assert len({id(c) for c in clients}) == 1
    finally:
        for client in set(clients):
            client.close()
        server.close()


def test_client_outlives_the_thread_that_created_it():
    """A client created on a worker thread stays usable after that thread exits."""
    server = RPCServer()
    created = []
    try:
        def worker():
            created.append(RPCClient.get_client(server.address))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        assert created[0].ping() == 'pong'
    finally:
        for client in created:
            client.close()
        server.close()


def test_get_client_does_not_hand_back_a_client_whose_server_is_gone():
    """An address outlives the connection that had it; ports get reused."""
    server = RPCServer('tcp://127.0.0.1:*')
    address = server.address
    dead = RPCClient.get_client(address)
    assert dead.ping() == 'pong'  # make the server aware of us, so it says goodbye
    server.close()
    assert dead.disconnected()

    server2 = RPCServer(address.decode())
    client = None
    try:
        client = RPCClient.get_client(address)
        assert client is not dead
        assert client.ping() == 'pong'
    finally:
        dead.close()
        if client is not None:
            client.close()
        server2.close()


def test_remote_server_sees_one_connection_per_client_process():
    """Many calling threads share a single connection to the remote server."""
    proc = start_process('test_one_connection_per_process')
    try:
        remote_server = proc.client['self']

        def worker():
            RPCClient.get_client(proc.client.address).ping()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(remote_server._clients) == 1
    finally:
        proc.kill()


def test_concurrent_calls_from_many_threads_stay_intact():
    """Sustained concurrent use of one address must not corrupt zmq framing (issue #40)."""
    proc = start_process('test_concurrent_client_threads')
    try:
        remote_str = proc.client._import('builtins').str
        errors = []

        def worker(worker_id):
            try:
                for i in range(40):
                    payload = f'{worker_id}-{i}' * (i + 1)
                    assert remote_str(payload) == payload
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert proc.client.ping() == 'pong'
    finally:
        proc.kill()


def test_callback_can_call_back_into_the_same_remote_process():
    """A callback invoked by the remote process may itself call that process (reentrancy)."""
    proc = start_process('test_reentrant_callback', local_server='lazy')
    try:
        remote_str = proc.client._import('builtins').str

        def callback(x):
            # Re-enter the remote process from inside a call it is waiting on.
            return remote_str(x * 2)

        tester = setup_callback_tester(proc.client)
        assert tester.apply_function(callback, 5) == '10'
    finally:
        proc.kill()
