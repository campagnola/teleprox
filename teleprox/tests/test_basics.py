import time

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


    # With exit_on_parent_death=False, killing the parent does not cascade to the child.
    proc3 = teleprox.start_process(name='test_double_stop_proc3')
    pid3 = proc3.pid
    proc4 = proc3.client._import('teleprox').start_process(
        name='test_double_stop_proc4', exit_on_parent_death=False)
    pid4 = proc4.pid._get_value()
    proc3.kill()
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


def test_exit_on_parent_death():
    """Grandchild exits automatically after its parent is hard-killed.

    P1 spawns P2 with exit_on_parent_death=True (the default).  When P1 is
    hard-killed (no atexit, no graceful shutdown), P2 must exit on its own via
    the Win32 Job Object (immediate) or the parent-PID polling thread (~5 s).
    """
    proc1 = teleprox.start_process(name='test_exit_on_parent_death_p1')
    pid1 = proc1.pid

    # Spawn P2 inside P1 so P1 is P2's direct parent for job-object / polling purposes.
    proc2_proxy = proc1.client._import('teleprox').start_process(
        name='test_exit_on_parent_death_p2'
    )
    pid2 = proc2_proxy.pid._get_value()

    proc1.kill()  # hard kill: atexit and stop() are never called
    assert_pid_dead(pid1)

    # Wait for P2 to exit.  On Windows the Job Object fires immediately; on other
    # platforms the polling thread wakes within 5 s.  Allow 15 s for safety.
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            assert_pid_dead(pid2)
            return  # P2 is gone — test passes
        except AssertionError:
            time.sleep(0.5)

    assert_pid_dead(pid2)  # final attempt; raises with a clear message if still alive


