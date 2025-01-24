import pytest
import teleprox
from teleprox.util import assert_pid_dead


def test_kill():
    proc = teleprox.start_process(name='test_kill_proc')
    pid = proc.pid
    assert proc.client._import('os').getpid() == proc.pid
    proc.kill()
    assert_pid_dead(pid)


def test_stop():
    proc = teleprox.start_process(name='test_stop_proc')
    pid = proc.pid
    assert proc.client._import('os').getpid() == proc.pid
    assert proc.poll() is None

    rcode = proc.stop()

    assert rcode == 0
    assert proc.poll() == 0
    assert_pid_dead(pid)


def test_double_stop():
    # Test stop()ing a parent process also causes its child to stop
    proc = teleprox.start_process(name='test_double_stop_proc')
    pid = proc.pid
    proc2 = proc.client._import('teleprox').start_process(name='test_double_stop_proc2')
    pid2 = proc2.pid._get_value()
    proc.stop()  # parent asks child to stop when it exits
    assert_pid_dead(pid)
    assert_pid_dead(pid2)


    # Test kill()ing a parent process does not cause its child to stop
    proc3 = teleprox.start_process(name='test_double_stop_proc3')
    pid3 = proc3.pid
    proc4 = proc3.client._import('teleprox').start_process(name='test_double_stop_proc4')
    pid4 = proc4.pid._get_value()
    proc3.kill()  # parent is killed; no chance to ask child to stop
    assert_pid_dead(pid3)
    with pytest.raises(AssertionError):
        assert_pid_dead(pid4)


    # Test stop()ing a parent process does not cause a daemon child to stop
    # Test stop()ing a parent process also causes its child to stop
    proc5 = teleprox.start_process(name='test_double_stop_proc5')
    pid5 = proc5.pid
    proc6 = proc5.client._import('teleprox').start_process(name='test_double_stop_proc6', daemon=True)
    pid6 = proc6.pid._get_value()
    proc5.stop()  # parent asks child to stop when it exits
    assert_pid_dead(pid5)
    with pytest.raises(AssertionError):
        assert_pid_dead(pid6)


