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

    client = RPCClient.get_client(server1.address)

    # test clients are cached
    assert client == RPCClient.get_client(server1.address)
    with pytest.raises(KeyError):
        # can't manually create client for the same address
        RPCClient(server1.address)

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

    client2 = RPCClient(server2.address)
    client2.default_proxy_options['defer_getattr'] = True
    obj3 = client2['test_class']('obj3')
    # send proxy from server1 to server2
    r2 = obj3.test(obj)
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

    client.close_server()
    client.close()

    logger.level = previous_level


@requires_qt
def test_qt_rpc():
    previous_level = logger.level
    # logger.level = logging.DEBUG
    server = QtRPCServer(quit_on_close=False)

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
    with pytest.raises(RuntimeError):
        server_proc.client.ping()

    server_proc.kill()
    client_proc.kill()

    # Clients gracefully handle sudden death of server (with timeout)
    server_proc3 = start_process('test_disconnect_server_proc3')
    server_proc3.kill()

    with pytest.raises(TimeoutError):
        server_proc3.client.ping(timeout=1)

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


def test_callback_without_local_server():
    """Test that callbacks fail properly without local_server."""

    def test_callback(x):
        return x * 2

    proc = start_process('test_callback_proc_no_server', local_server=None)
    try:
        tester = setup_callback_tester(proc.client)

        # This should work (no callback required)
        result = tester.echo(42)
        assert result == 42

        # This should fail (callback required but no local server)
        with pytest.raises(TypeError):
            tester.apply_function(test_callback, 5)
    finally:
        proc.kill()


def test_callback_with_lazy_server():
    """Test basic callback functionality with lazy local_server."""

    def test_callback(x):
        return x * 2

    proc = start_process('test_callback_proc_lazy', local_server="lazy")
    try:
        tester = setup_callback_tester(proc.client)

        # Both should work
        result = tester.echo(42)
        assert result == 42

        result = tester.apply_function(test_callback, 5)
        assert result == 10
    finally:
        proc.kill()


def test_callback_multiple_invocations():
    """Test multiple callback invocations work correctly."""

    def test_callback(x):
        return x * 2

    proc = start_process('test_callback_multiple', local_server="lazy")
    try:
        tester = setup_callback_tester(proc.client)

        # Test multiple callbacks
        results = tester.apply_multiple(test_callback, [1, 2, 3])
        assert results == [2, 4, 6]
    finally:
        proc.kill()


def test_callback_lambda_functions():
    """Test lambda callbacks work correctly."""
    proc = start_process('test_callback_lambda', local_server="lazy")
    try:
        tester = setup_callback_tester(proc.client, tester_name="LambdaTester")

        # Test lambda callback
        result = tester.apply_function(lambda x: x * 3, 4)
        assert result == 12

        # Test lambda with tester name access
        result = tester.apply_function(
            lambda t: f"processed by {tester.get_name()}", None
        )
        assert result == "processed by LambdaTester"
    finally:
        proc.kill()


def test_async_callback_threaded_execution():
    """Test threaded callback execution."""
    callback_results = []

    def recording_callback(tester):
        callback_results.append(f"callback from: {tester.get_name()}")
        return "threaded_response"

    proc = start_process('test_callback_threaded', local_server="threaded")
    try:
        tester = setup_callback_tester(proc.client, tester_name="ThreadedTester")

        # Test single threaded callback
        response = tester.invoke_callback_threaded(recording_callback)
        assert response is None
        start = time.time()
        while not callback_results:
            time.sleep(0.01)
            if (time.time() - start) >= 1:
                raise TimeoutError("Callback did not complete in time")
        assert callback_results == ["callback from: ThreadedTester"]

        # Test repeated threaded callbacks
        callback_results.clear()
        response = tester.repeated_callback_threaded(recording_callback, 2)
        assert response is None
        start = time.time()
        while len(callback_results) < 2:
            time.sleep(0.01)
            if (time.time() - start) >= 1:
                raise TimeoutError(f"Callback did not complete in time: {callback_results}")
        assert callback_results == [
            "callback from: ThreadedTester",
            "callback from: ThreadedTester",
        ]

    finally:
        proc.kill()


def test_callback_error_handling():
    """Test callback error handling scenarios."""

    def failing_callback(x):
        raise ValueError("callback failed")

    def working_callback(x):
        return "success"

    proc = start_process('test_callback_errors', local_server="lazy")
    try:
        tester = setup_callback_tester(proc.client)

        # Working callback should succeed
        result = tester.apply_function(working_callback, None)
        assert result == "success"

        # Failing callback should raise exception
        with pytest.raises(RemoteCallException) as exc_info:
            tester.apply_function(failing_callback, None)
        assert "callback failed" in str(exc_info.value)
    finally:
        proc.kill()


def test_callback_nested_objects():
    """Test callbacks with complex nested object arguments."""
    import numpy as np

    def process_data(data_dict):
        return {
            'sum': sum(data_dict['values']),
            'array_mean': float(data_dict['array'].mean()),
            'message': data_dict['metadata']['message'],
        }

    proc = start_process('test_callback_nested', local_server="lazy")
    try:
        tester = setup_callback_tester(proc.client)

        # Create complex nested data
        complex_data = {
            'values': [1, 2, 3, 4, 5],
            'array': np.array([10, 20, 30]),
            'metadata': {'message': 'processed'},
        }

        result = tester.apply_function(process_data, complex_data)
        assert result['sum'] == 15
        assert result['array_mean'] == 20.0
        assert result['message'] == 'processed'
    finally:
        proc.kill()


def setup_callback_tester(client, instance_name="callback_tester", tester_name=None):
    """Set up a CallbackTester class in the remote process and return a proxy to it.

    Parameters
    ----------
    client : RPCClient
        The client connected to the remote process.
    instance_name : str
        Name for the instance in the remote process's __main__ namespace.
    tester_name : str or None
        Optional name to pass to CallbackTester constructor.

    Returns
    -------
    ObjectProxy
        Proxy to the CallbackTester instance in the remote process.
    """
    # Import modules needed for threaded methods
    threading = client._import("threading")
    queue = client._import("queue")
    time = client._import("time")

    tester_name = f'"{tester_name}"' if tester_name else ''
    exec_code = f'''
class CallbackTester:
    def __init__(self, name=None):
        self.name = name
        self._cb_queue = queue.Queue()
        self._returns = {{}}
        self._thread = threading.Thread(target=self._run_threaded, daemon=True)
        self._thread.start()

    def _run_threaded(self):
        while True:
            callback_func = self._cb_queue.get()
            if callback_func is None:  # Exit signal
                break
            result = callback_func(self)
            self._returns[callback_func] = result

    # Synchronous callback methods
    def apply_function(self, func, value):
        return func(value)

    def apply_multiple(self, func, values):
        return [func(v) for v in values]

    def echo(self, value):
        return value

    def get_name(self):
        return self.name

    # Multithreaded callback methods
    def invoke_callback_threaded(self, callback_func):
        self._cb_queue.put(callback_func)

    def repeated_callback_threaded(self, callback_func, count=3):
        results = []
        for i in range(count):
            self.invoke_callback_threaded(callback_func)

    def stop_threaded(self):
        self._cb_queue.put(None)

import __main__
__main__.{instance_name} = CallbackTester({tester_name})
'''

    client._import('builtins').exec(
        exec_code, {'queue': queue, 'threading': threading, 'time': time}
    )
    return client._import('__main__').__getattr__(instance_name)


@pytest.fixture
def exception_server():
    """Fixture providing server with exception testing class."""

    class ExceptionTester:
        def raise_value_error(self, message="test error"):
            raise ValueError(message)

        def raise_type_error(self, message="type error"):
            raise TypeError(message)

        def raise_runtime_error(self, message="runtime error"):
            raise RuntimeError(message)

        def raise_custom_exception(self):
            class CustomError(Exception):
                pass

            raise CustomError("custom exception message")

        def raise_nested_exception(self):
            try:
                self.raise_value_error("nested")
            except ValueError as e:
                raise RuntimeError("wrapper error") from e

        def raise_exception_with_complex_args(self):
            import numpy as np

            raise ValueError("error with array", np.arange(5))

        def divide_by_zero(self, x, y):
            return x / y

        def access_missing_attribute(self):
            return self.nonexistent_attribute

        def return_then_raise(self, should_raise=False):
            if should_raise:
                raise ValueError("delayed error")
            return "success"

    server = RPCServer()
    server['exception_tester'] = ExceptionTester()
    client = RPCClient.get_client(server.address)
    tester = client['exception_tester']

    yield tester, client

    client.close_server()
    client.close()


def test_basic_exceptions(exception_server):
    """Test basic Python exception types are properly wrapped."""
    tester, client = exception_server

    with pytest.raises(RemoteCallException) as exc_info:
        tester.raise_value_error("custom message")
    assert exc_info.value.type_str == 'ValueError'
    assert "custom message" in str(exc_info.value)

    with pytest.raises(RemoteCallException) as exc_info:
        tester.raise_type_error()
    assert exc_info.value.type_str == 'TypeError'

    with pytest.raises(RemoteCallException) as exc_info:
        tester.raise_runtime_error()
    assert exc_info.value.type_str == 'RuntimeError'


def test_custom_exceptions(exception_server):
    """Test custom user-defined exceptions are handled."""
    tester, client = exception_server

    with pytest.raises(RemoteCallException) as exc_info:
        tester.raise_custom_exception()
    assert "CustomError" in exc_info.value.type_str
    assert "custom exception message" in str(exc_info.value)


def test_nested_exceptions(exception_server):
    """Test exception chaining with 'raise ... from' syntax."""
    tester, client = exception_server

    with pytest.raises(RemoteCallException) as exc_info:
        tester.raise_nested_exception()
    assert exc_info.value.type_str == 'RuntimeError'
    assert "wrapper error" in str(exc_info.value)


def test_exceptions_with_complex_args(exception_server):
    """Test exceptions raised with complex arguments like numpy arrays."""
    tester, client = exception_server

    with pytest.raises(RemoteCallException) as exc_info:
        tester.raise_exception_with_complex_args()
    assert exc_info.value.type_str == 'ValueError'


def test_builtin_exceptions(exception_server):
    """Test built-in Python exceptions like ZeroDivisionError."""
    tester, client = exception_server

    with pytest.raises(RemoteCallException) as exc_info:
        tester.divide_by_zero(1, 0)
    assert exc_info.value.type_str == 'ZeroDivisionError'

    with pytest.raises(RemoteCallException) as exc_info:
        tester.access_missing_attribute()
    assert exc_info.value.type_str == 'AttributeError'


def test_async_exceptions(exception_server):
    """Test exceptions in async calls are properly handled."""
    tester, client = exception_server

    future = tester.raise_value_error("async error", _sync='async')
    with pytest.raises(RemoteCallException) as exc_info:
        future.result()
    assert exc_info.value.type_str == 'ValueError'
    assert "async error" in str(exc_info.value)


def test_mixed_success_and_exceptions(exception_server):
    """Test successful calls followed by exceptions work correctly."""
    tester, client = exception_server

    result = tester.return_then_raise(False)
    assert result == "success"

    with pytest.raises(RemoteCallException):
        tester.return_then_raise(True)


def test_no_local_server_blocks_callbacks():
    """Test that local_server=None prevents callback serialization."""

    def test_callback(x):
        return x * 2

    proc = start_process('test_none_local_server', local_server=None)
    try:
        tester = setup_callback_tester(proc.client)

        # This should work (no callback required)
        result = tester.echo(42)
        assert result == 42

        # This should fail (callback required but no local server)
        with pytest.raises(TypeError):
            tester.apply_function(test_callback, 5)

    finally:
        proc.kill()


def test_lazy_local_server():
    """Test lazy local_server supports callbacks synchronously."""

    def test_callback(x):
        return x * 2

    proc = start_process('test_lazy_local_server', local_server='lazy')
    try:
        tester = setup_callback_tester(proc.client)

        # Both should work
        result = tester.echo(42)
        assert result == 42

        result = tester.apply_function(test_callback, 5)
        assert result == 10

        # Test multiple callbacks
        results = tester.apply_multiple(test_callback, [1, 2, 3])
        assert results == [2, 4, 6]

    finally:
        proc.kill()


def test_threaded_local_server():
    """Test threaded local_server supports callbacks asynchronously."""

    def test_callback(x):
        return x * 2

    proc = start_process('test_threaded_local_server', local_server='threaded')
    try:
        tester = setup_callback_tester(proc.client)

        # Both should work
        result = tester.echo(42)
        assert result == 42

        result = tester.apply_function(test_callback, 5)
        assert result == 10

        # Test multiple callbacks
        results = tester.apply_multiple(test_callback, [1, 2, 3])
        assert results == [2, 4, 6]

    finally:
        proc.kill()


def test_shared_local_server():
    """Test multiple processes can share a single RPCServer instance."""

    def test_callback(x):
        return x * 2

    shared_server = RPCServer()
    proc1 = start_process('test_shared1_local_server', local_server=shared_server)
    proc2 = start_process('test_shared2_local_server', local_server=shared_server)

    try:
        # Set up callback testers in both processes
        tester1 = setup_callback_tester(proc1.client, "callback_tester1", "tester1")
        tester2 = setup_callback_tester(proc2.client, "callback_tester2", "tester2")

        # Test callbacks work through shared server
        result1 = tester1.apply_function(test_callback, 10)
        assert result1 == 20

        result2 = tester2.apply_function(test_callback, 15)
        assert result2 == 30

    finally:
        proc1.kill()
        proc2.kill()
        shared_server.close()


def test_shared_local_server_cross_process_objects():
    """Test shared local_server enables cross-process object sharing."""
    shared_server = RPCServer()
    proc1 = start_process('test_shared1_cross_proc', local_server=shared_server)
    proc2 = start_process('test_shared2_cross_proc', local_server=shared_server)

    try:
        # Set up callback testers
        tester1 = setup_callback_tester(proc1.client, "callback_tester1")
        tester2 = setup_callback_tester(proc2.client, "callback_tester2")

        # Test cross-process object sharing through shared server
        shared_server['shared_value'] = 100

        def get_shared_value(unused_arg):
            return shared_server['shared_value']

        # Both processes can access the shared value through callbacks
        value1 = tester1.apply_function(get_shared_value, None)
        value2 = tester2.apply_function(get_shared_value, None)

        assert value1 == 100
        assert value2 == 100

    finally:
        proc1.kill()
        proc2.kill()
        shared_server.close()


if __name__ == '__main__':
    # ~ test_rpc()
    test_qt_rpc()
    # ~ test_disconnect()
    # ~ test_callbacks()
    # ~ test_exception_handling()
    # ~ test_local_server_types()
