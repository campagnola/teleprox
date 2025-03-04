import logging
import os
import signal
import time

import pytest
from teleprox import start_process
import teleprox
from teleprox.log.remote import LogServer, start_log_server
from teleprox.tests import test_logging
from teleprox.util import ProcessCleaner, assert_pid_dead


def test_daemon():
    """Check that daemon processes can be started and stopped, and outlive their parents.
    """
    with ProcessCleaner() as cleaner:
        # start a child
        child1 = start_process('test_daemon_child1')
        cleaner.add('child1', child1.pid)

        # ask the child to start a daemon
        daemon = child1.client._import('teleprox').start_process('test_daemon', daemon=False)
        address = daemon.client.address._get_value()
        pid = daemon.client._import('os').getpid()
        cleaner.add('daemon', pid)

        # kill the child; check that we can still connect to daemon
        time.sleep(1)
        child1.kill()

        # start second child
        child2 = start_process('test_daemon_child2')
        cleaner.add('child2', child2.pid)

        # ask second child to connect to daemon
        daemon_client = child2.client._import('teleprox').RPCClient(address=address)

        # check the daemon works as expected
        assert pid == daemon_client._import('os').getpid()

        # test closing daemon nicely
        daemon_client.close_server()
        time.sleep(0.3)  # wait for server to close

        child2.kill()


def test_daemon_stdio():
    """Check that daemon process stdout and stderr are redirected to /dev/null.
    """
    with ProcessCleaner() as cleaner:
        log_server = None
        try:
            # Start a log server to catch stdout and stderr from child processes    
            logger = logging.getLogger('test_daemon_stdio_logger')
            logger.level = logging.DEBUG
            handler = test_logging.Handler()
            logger.addHandler(handler)
            log_server = LogServer(logger)

            # create a child process and log all of its stdout/stderr
            child = start_process(name='test_daemon_stdio_child', log_addr=log_server.address, log_level=logging.INFO)
            cleaner.add('child', child.pid)

            # create a grandchild process and check that printing from here is logged (because normal children share stdio with parents)
            child2 = child.client._import('teleprox').start_process(name='test_daemon_stdio_child2')
            cleaner.add('child2', child2.pid._get_value())
            child2.client._import('builtins').print("from child2")
            time.sleep(0.3)
            assert handler.find_message("from child2") is not None

            # create a daemon process and check that printing from here is not logged
            daemon = child.client._import('teleprox').start_process(name="test_daemon_stdio_daemon", daemon=True)
            cleaner.add('daemon', daemon.pid._get_value())
            daemon.client._import('builtins').print("from daemon")
            time.sleep(0.3)
            assert handler.find_message("from daemon") is None


            daemon.kill()
            child2.kill()
            child.kill()

        finally:
            if log_server is not None:
                log_server.stop()


@pytest.mark.skip("This test is not working yet")
def test_close_terminal():
    """When a terminal closes, it usually takes all child processes with it.
    Check that this is not true for a daemon process.
    """
    import pty
    with ProcessCleaner() as cleaner:
        lead_fd, follow_fd = pty.openpty()
        proc = teleprox.start_process('test_close_terminal_proc', stdin=follow_fd, stdout=follow_fd, stderr=follow_fd, daemon=True)
        cleaner.add('proc', proc.pid)
        child1 = proc.client._import('teleprox').start_process('test_close_terminal_child1')
        cpid1 = child1.pid._get_value()
        cleaner.add('child1', cpid1)
        child2 = proc.client._import('teleprox').start_process('test_close_terminal_child2', daemon=True)
        cpid2 = child2.pid._get_value()
        cleaner.add('child2', cpid2)

        # close the terminal
        os.close(follow_fd)
        os.close(lead_fd)

        pgid = os.getpgid(proc.pid)
        assert pgid != os.getpgid(os.getpid()), "Process group should have changed"

        # HUP entire process group
        os.killpg(pgid, signal.SIGHUP)

        # check proc and child1 are dead
        assert_pid_dead(proc.pid)
        assert_pid_dead(cpid1)

        # check child2 is still alive
        with pytest.raises(AssertionError):
            assert_pid_dead(cpid2)


