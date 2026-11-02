"""Tests for RPCClient's threading contract: one client per address, usable from any thread."""

import threading
import time

from teleprox import RPCClient, RPCServer, start_process
from teleprox.tests.test_rpc import setup_callback_tester


def wait_until(predicate, timeout=10.0):
    """Poll *predicate* until it holds, and return whether it did.

    A server closing and its clients hearing about it are separate events: the
    disconnect is a message, so a client that has not read it yet is behind, not
    wrong.
    """
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


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
    assert wait_until(dead.disconnected)

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


def test_get_client_reuses_a_client_that_manages_its_own_local_server():
    """Asking twice for a connection with a managed local server must not open two."""
    server = RPCServer()
    client = None
    try:
        client = RPCClient.get_client(server.address, local_server='lazy')
        assert RPCClient.get_client(server.address, local_server='lazy') is client
    finally:
        if client is not None:
            client.close()
        server.close()


def test_one_lazy_server_serves_callbacks_for_several_clients():
    """A single lazy server shared by two connections must answer calls made through either."""
    local = RPCServer('tcp://127.0.0.1:*', run_thread=False)
    proc1 = start_process('test_shared_lazy_1', local_server=local)
    proc2 = start_process('test_shared_lazy_2', local_server=local)
    try:
        tester1 = setup_callback_tester(proc1.client)
        tester2 = setup_callback_tester(proc2.client)
        assert tester1.apply_function(lambda x: x * 2, 3) == 6
        assert tester2.apply_function(lambda x: x * 3, 3) == 9
    finally:
        proc1.kill()
        proc2.kill()
        local.close()


def test_a_shared_lazy_server_is_taken_over_when_its_reader_goes_away():
    """Whichever client reads the shared server, the others must take over once it stops."""
    local = RPCServer('tcp://127.0.0.1:*', run_thread=False)
    proc1 = start_process('test_lazy_handover_1', local_server=local)
    proc2 = start_process('test_lazy_handover_2', local_server=local)
    try:
        tester2 = setup_callback_tester(proc2.client)
        proc1.kill()
        assert tester2.apply_function(lambda x: x + 1, 1) == 2
    finally:
        proc1.kill()
        proc2.kill()
        local.close()


def test_close_leaves_a_busy_lazy_servers_socket_to_its_io_thread():
    """A managed lazy server belongs to the I/O thread polling it, even when close() gives up waiting."""
    started = threading.Event()
    release = threading.Event()

    def slow_callback(value):
        started.set()
        release.wait(10)
        return value

    proc = start_process('test_close_busy_lazy', local_server='lazy')
    client = proc.client
    local = client._local_server
    try:
        tester = setup_callback_tester(client)
        # The client tracks futures weakly, so the caller's reference is what
        # keeps the call -- and the lazy server that answers it -- alive.
        pending = tester.apply_function(slow_callback, 1, _sync='async')
        assert started.wait(10)
        assert pending is not None

        client.close(timeout=0.1)
        assert local.running()

        release.set()
        assert wait_until(lambda: not local.running())
    finally:
        release.set()
        proc.kill()


def test_a_disconnected_client_releases_its_wakeup_sockets():
    """A client whose server is gone must not hold OS resources until the process exits.

    Nothing obliges a caller to close a client the server has already dropped --
    a killed child process leaves one behind -- so the I/O thread has to release
    what it polled on its way out.
    """
    server = RPCServer('tcp://127.0.0.1:*')
    client = RPCClient(server.address)
    assert client.ping() == 'pong'

    server.close()
    assert wait_until(client.disconnected)
    client._io_thread.join(timeout=5.0)

    assert client._wake_r.fileno() == -1
    assert client._wake_w.fileno() == -1


def test_a_queued_request_reaches_the_socket_without_waiting_for_a_poll_timeout():
    """Every send must wake the I/O thread, however many are already in flight.

    A nudge that is skipped because one looks pending leaves the request sitting
    in the outbox until the I/O thread's poll times out of its own accord.
    """
    server = RPCServer()
    client = RPCClient(server.address)
    try:
        pending = [client.send('ping', sync='async') for _ in range(500)]
        worst = 0.0
        for _ in range(1000):
            start = time.perf_counter()
            pending.append(client.send('ping', sync='async'))
            worst = max(worst, time.perf_counter() - start)
            pending.pop(0)

        assert worst < 0.05, f"a send waited {worst * 1000:.0f} ms to reach the socket"
    finally:
        client.close()
        server.close()
