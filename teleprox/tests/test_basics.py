import pytest
import teleprox
from teleprox.util import assert_pid_dead


def test_kill():
    proc = teleprox.start_process()
    pid = proc.pid
    assert proc.client._import('os').getpid() == proc.pid
    proc.kill()
    assert_pid_dead(pid)


def test_stop():
    proc = teleprox.start_process()
    pid = proc.pid
    assert proc.client._import('os').getpid() == proc.pid
    assert proc.poll() is None

    rcode = proc.stop()

    assert rcode == 0
    assert proc.poll() == 0
    assert_pid_dead(pid)


def test_double_stop():
    # Test stop()ing a parent process also causes its child to stop
    proc = teleprox.start_process()
    pid = proc.pid
    proc2 = proc.client._import('teleprox').start_process()
    pid2 = proc2.pid._get_value()
    proc.stop()  # parent asks child to stop when it exits
    assert_pid_dead(pid)
    assert_pid_dead(pid2)


    # Test kill()ing a parent process does not cause its child to stop
    proc = teleprox.start_process()
    pid = proc.pid
    proc2 = proc.client._import('teleprox').start_process()
    pid2 = proc2.pid._get_value()
    proc.kill()  # parent is killed; no chance to ask child to stop
    assert_pid_dead(pid)
    with pytest.raises(AssertionError):
        assert_pid_dead(pid2)


    # Test stop()ing a parent process does not cause a daemon child to stop
    # Test stop()ing a parent process also causes its child to stop
    proc = teleprox.start_process()
    pid = proc.pid
    proc2 = proc.client._import('teleprox').start_process(daemon=True)
    pid2 = proc2.pid._get_value()
    proc.stop()  # parent asks child to stop when it exits
    assert_pid_dead(pid)
    with pytest.raises(AssertionError):
        assert_pid_dead(pid2)


