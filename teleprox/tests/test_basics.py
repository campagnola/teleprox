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
