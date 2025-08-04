import logging
import threading
import time

import numpy as np
import pytest

from teleprox import (
    RPCClient,
    RemoteCallException,
    RPCServer,
    QtRPCServer,
    ObjectProxy,
    start_process,
)
from teleprox.tests.check_qt import requires_qt, qt_available

logger = logging.getLogger(__name__)

if qt_available:
    from teleprox import qt

    qapp = qt.make_qapp()


def test_rpc():
    previous_level = logger.level

    # logger.level = logging.DEBUG

    class TestClass(object):
        count = 0

        def __init__(self, name):
            self.name = name
            TestClass.count += 1

        def __del__(self):
            TestClass.count -= 1

        def add(self, x, y):
            return x + y

        def array(self):
            return np.arange(20).astype('int64')

        def sleep(self, t):
            time.sleep(t)

        def get_list(self):
            return [0, 'x', 7]

        def test(self, obj):
            return self.name, obj.name, obj.add(5, 7), obj.array(), obj.get_list()

        def types(self):
            return {
                'int': 7,
                'float': 0.5,
                'str': 'xxx',
                'bytes': bytes('xxx', 'utf8'),
                'ndarray': np.arange(10),
                'dict': {},
                'list': [],
                'ObjectProxy': self,
            }

        def type(self, x):
            return type(x).__name__

    server1 = RPCServer()
    server1['test_class'] = TestClass
    server1['my_object'] = TestClass('obj1')
    serve_thread = threading.Thread(target=server1.run_forever, daemon=True)
    serve_thread.start()

    client = RPCClient.get_client(server1.address)

    # test clients are cached
    assert client == RPCClient.get_client(server1.address)
    try:
        # can't manually create client for the same address
        RPCClient(server1.address)
        assert False, "Should have raised KeyError."
    except KeyError:
        pass

    # get proxy to TestClass instance
    obj = client['my_object']
    assert isinstance(obj, ObjectProxy)

    # check equality with duplicate proxy
    obj2 = client['my_object']
    assert obj == obj2
    assert obj._obj_id == obj2._obj_id
    assert obj._ref_id != obj2._ref_id

    # check hashability
    assert obj in {obj2: None}
    assert obj in set([obj2])

    logger.info("-- Test call with sync return --")
    add = obj.add
    assert isinstance(add, ObjectProxy)
    assert add(7, 5) == 12

    # test return types
    for k, v in obj.types().items():
        assert type(v).__name__ == k
        if k != 'ObjectProxy':
            assert obj.type(v) == k

    # NOTE: msgpack converts list to tuple.
    # See: https://github.com/msgpack/msgpack-python/issues/98
    assert obj.get_list() == [0, 'x', 7]

    logger.info("-- Test async return --")
    fut = obj.sleep(0.1, _sync='async')
    assert not fut.done()
    assert fut.result() is None

    logger.info("-- Test no return --")
    assert obj.add(1, 2, _sync='off') is None

    logger.info("-- Test return by proxy --")
    list_prox = obj.get_list(_return_type='proxy')
    assert isinstance(list_prox, ObjectProxy)
    assert list_prox._type_str == "<class 'list'>"
    assert len(list_prox) == 3
    assert list_prox[2] == 7

    logger.info("-- Test proxy access to server --")
    srv = client['self']
    assert srv.address == server1.address

    logger.info("-- Test remote exception raising --")
    try:
        obj.add(7, 'x')
    except RemoteCallException as err:
        if err.type_str != 'TypeError':
            raise
    else:
        raise AssertionError('should have raised TypeError')

    try:
        client.asdffhgk
        raise AssertionError('should have raised AttributeError')
    except AttributeError:
        pass

    logger.info("-- Test deferred getattr --")
    arr = obj.array(_return_type='proxy')
    dt1 = arr.dtype.name._get_value()
    assert isinstance(dt1, str)
    arr._set_proxy_options(defer_getattr=True)
    dt2 = arr.dtype.name
    assert isinstance(dt2, ObjectProxy)
    assert dt2._obj_id == arr._obj_id
    assert dt2._attributes == ('dtype', 'name')
    dt3 = dt2._undefer()
    assert dt3 == dt2

    logger.info("-- Test remote object creation / deletion --")
    class_proxy = client['test_class']
    obj2 = class_proxy('obj2')
    assert class_proxy.count == 2
    assert obj2.add(3, 4) == 7

    obj2._delete()
    # handler.flush_records()  # log records might have refs to the object
    assert class_proxy.count._get_value() == 1
    try:
        obj2.array()
        assert False, "Should have raised RemoteCallException"
    except RemoteCallException:
        pass

    logger.info("-- Test proxy auto-delete --")
    obj2 = class_proxy('obj2')
    obj2._set_proxy_options(auto_delete=True)
    assert class_proxy.count == 2

    del obj2
    # handler.flush_records()  # log records might have refs to the object
    assert class_proxy.count._get_value() == 1

    logger.info("-- Test timeouts --")
    try:
        obj.sleep(0.2, _timeout=0.01)
    except TimeoutError:
        pass
    else:
        raise AssertionError('should have raised TimeoutError')
    obj.sleep(0.2, _timeout=0.5)

    logger.info("-- Test result order --")
    a = obj.add(1, 2, _sync='async')
    b = obj.add(3, 4, _sync='async')
    assert b.result() == 7
    assert a.result() == 3

    logger.info("-- Test transfer --")
    arr = np.ones(10, dtype='float32')
    arr_prox = client.transfer(arr)
    assert arr_prox.dtype.name == 'float32'
    assert arr_prox.shape._get_value() == (10,)

    logger.info("-- Test import --")
    import os.path as osp

    rosp = client._import('os.path')
    assert osp.abspath(osp.dirname(__file__)) == rosp.abspath(rosp.dirname(__file__))

    logger.info("-- Test proxy sharing between servers --")
    obj._set_proxy_options(defer_getattr=True)
    r1 = obj.test(obj)
    server2 = RPCServer()
    server2['test_class'] = TestClass
    serve_thread2 = threading.Thread(target=server2.run_forever, daemon=True)
    serve_thread2.start()

    client2 = RPCClient(server2.address)
    client2.default_proxy_options['defer_getattr'] = True
    obj3 = client2['test_class']('obj3')
    # send proxy from server1 to server2
    r2 = obj3.test(obj)
    # check that we have a new client between the two servers
    assert (serve_thread2.ident, server1.address) in RPCClient.clients_by_thread
    # check all communication worked correctly
    assert r1[0] == 'obj1'
    assert r2[0] == 'obj3'
    assert r1[1] == r2[1] == 'obj1'
    assert r1[2] == r2[2] == 12
    assert np.all(r1[3] == r2[3])
    assert r1[4] == r2[4]

    logger.info("-- Test publishing objects --")
    arr = np.arange(5, 10)
    client['arr'] = arr  # publish to server1
    s2rpc = client2._import('teleprox')
    s2cli = s2rpc.RPCClient.get_client(client.address)  # server2's client for server1
    assert np.all(s2cli['arr'] == arr)  # retrieve via server2

    logger.info("-- Test JSON client --")
    # Start a JSON client in a remote process
    cli_proc = start_process(name='test_rpc_cli_proc')
    cli = cli_proc.client._import('teleprox').RPCClient(
        server2.address, serializer='json'
    )
    # Check everything is ok..
    assert cli.serializer.type._get_value() == 'json'
    assert cli['test_class']('json-tester').add(3, 4) == 7
    cli_proc.kill()

    logger.info("-- Setup reentrant communication test.. --")

    class PingPong(object):
        def set_other(self, o):
            self.other = o

        def pingpong(self, depth=0):
            if depth > 6:
                return "reentrant!"
            return self.other.pingpong(depth + 1)

    server1['pp1'] = PingPong()
    server2['pp2'] = PingPong()
    pp1 = client['pp1']
    pp2 = client2['pp2']
    pp1.set_other(pp2)
    pp2.set_other(pp1)

    logger.info("-- Test reentrant communication --")
    assert pp1.pingpong() == 'reentrant!'

    logger.info("-- Shut down servers --")
    client2.close_server()
    serve_thread2.join()

    client.close_server()
    client.close()
    serve_thread.join()

    logger.level = previous_level


@requires_qt
def test_qt_rpc():
    previous_level = logger.level
    # logger.level = logging.DEBUG
    server = QtRPCServer(quit_on_close=False)
    server.run_forever()

    # Start a thread that will remotely request a widget to be created in the
    # GUI thread.
    class TestThread(threading.Thread):
        def __init__(self, addr):
            threading.Thread.__init__(self, daemon=True)
            self.addr = addr
            self.done = False
            self.lock = threading.Lock()

        def run(self):
            client = RPCClient(self.addr)
            qt = client._import('teleprox.qt')
            # widget creation happens in main GUI thread; we are working with
            # proxies from here.
            self.l = qt.QLabel('remote-controlled label')
            self.l.show()
            time.sleep(0.3)
            self.l.hide()
            with self.lock:
                self.done = True

    thread = TestThread(server.address)
    thread.start()

    start = time.time()
    while True:
        with thread.lock:
            if thread.done:
                break
        assert time.time() < start + 5.0, "Thread did not finish within 5 sec."
        time.sleep(0.01)
        qapp.processEvents()

    assert 'QLabel' in thread.l._type_str
    server.close()

    logger.level = previous_level


def test_disconnect():
    # ~ logger.level = logging.DEBUG

    # Clients receive notification when server disconnects gracefully
    server_proc = start_process('test_disconnect_server_proc')

    client_proc = start_process('test_disconnect_client_proc')
    cli = client_proc.client._import('teleprox').RPCClient(server_proc.client.address)
    cli.close_server()

    assert cli.disconnected() is True

    # Check that our local client for server_proc knows the server is disconnected, even though
    # it was client_proc that closed the server.
    assert server_proc.client.disconnected() is True
    try:
        print(server_proc.client.ping())
        assert False, "Expected RuntimeError"
    except RuntimeError:
        pass

    server_proc.kill()
    client_proc.kill()

    # Clients receive closure messages even if the server exits without closing
    server_proc2 = start_process('test_disconnect_server_proc2')
    server_proc2.client['self']._closed = 'sabotage!'
    time.sleep(0.1)
    assert server_proc2.client.disconnected() is True

    # add by Sam: force the end of process
    server_proc2.kill()

    # Clients gracefully handle sudden death of server (with timeout)
    server_proc3 = start_process('test_disconnect_server_proc3')
    server_proc3.kill()

    try:
        server_proc3.client.ping(timeout=1)
        assert False, "Expected TimeoutError"
    except TimeoutError:
        pass

    # server doesn't hang up if clients are not available to receive disconnect
    # message
    server_proc4 = start_process('test_disconnect_server_proc4')
    for i in range(4):
        # create a bunch of dead clients
        cp = start_process(f'test_disconnect_client_proc{i}')
        cli = cp.client._import('teleprox').RPCClient(server_proc4.client.address)
        cp.kill()

    start = time.time()
    server_proc4.client.close_server()
    assert time.time() - start < 1.0
    assert server_proc4.client.disconnected() == True

    # add by Sam: force the end of process
    server_proc4.kill()


def test_callbacks():
    """Test proper way to pass callbacks into remote processes."""
    logger.info("-- Test callback functionality --")

    callback_result = []

    def my_callback(tester):
        callback_result.append(f"callback received: {tester.name()}")
        return "callback_response"

    # First, test that callbacks fail without local_server
    proc_no_server = start_process(
        'test_callback_proc_no_server', local_server=None
    )

    # Create a simple function that takes another function as parameter
    # Use built-in functionality rather than publishing our own class
    builtins = proc_no_server.client._import('builtins')

    # This should fail because we can't serialize the function without a local server
    with pytest.raises(TypeError):
        # Use remote map() with our callback so as to execute in the remote process
        builtins.list(builtins.map(my_callback, ["test1", "test2"]))

    proc_no_server.stop()

    # Now test with local_server="threaded" - this should work
    proc_with_server = start_process(
        'test_callback_proc_with_server', local_server="threaded"
    )

    # Define a simple class that can accept and invoke callbacks
    threading = proc_with_server.client._import("threading")
    queue = proc_with_server.client._import("queue")
    time = proc_with_server.client._import("time")

    proc_with_server.client._import("builtins").exec(
        """
import __main__

class CallbackTester:
    def __init__(self):
        self._cb_queue = queue.Queue()
        self._returns = {}
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def name(self):
        return "CallbackTester"

    def _run(self):
        while True:
            callback_func = self._cb_queue.get()
            if callback_func is None:  # Exit signal
                break
            result = callback_func(self)
            self._returns[callback_func] = result

    def invoke_callback(self, callback_func):
        self._cb_queue.put(callback_func)
        while callback_func not in self._returns:
            time.sleep(0.01)
        return self._returns.pop(callback_func)

    def repeated_callback(self, callback_func, count=3):
        results = []
        for i in range(count):
            result = self.invoke_callback(callback_func)
            results.append(result)
        return results

    def stop(self):
        self._cb_queue.put((None, None))

__main__.CallbackTester = CallbackTester
    """,
        {'queue': queue, 'threading': threading, 'time': time},
    )
    tester_with_server = proc_with_server.client._import("__main__").CallbackTester()

    try:
        # Reset callback result
        callback_result.clear()

        # This should work now
        response = tester_with_server.invoke_callback(my_callback)  # !!!timing out!!!
        assert response == "callback_response"
        assert callback_result == ["callback received: CallbackTester"]

        # Test multiple callback invocations
        callback_result.clear()
        responses = tester_with_server.repeated_callback(my_callback, 2)
        assert responses == ["callback_response", "callback_response"]
        assert callback_result == [
            "callback received: CallbackTester",
            "callback received: CallbackTester",
        ]

        # Test lambda callback
        callback_result.clear()
        lambda_response = tester_with_server.invoke_callback(
            lambda x: f"lambda_processed: {x.name()}"
        )
        assert lambda_response == "lambda_processed: CallbackTester"

    finally:
        # TODO if it times out, we probably can't send any more signals
        # tester_with_server.stop()
        proc_with_server.kill()


if __name__ == '__main__':
    # ~ test_rpc()
    test_qt_rpc()
    # ~ test_disconnect()
    # ~ test_callbacks()
