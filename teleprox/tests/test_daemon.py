import logging
import signal
import sys
import os
import time
import pytest
from teleprox import start_process
from teleprox.log.remote import LogServer, start_log_server
from teleprox.tests import test_logging
from teleprox.util import assert_pid_dead


class ProcessCleaner:
    """Context manager that collects a list of processes to kill when it exits.

    The expectation is that all processes are already dead when the context manager exits. 

    If an exception is raised, the processes are killed before the exception is re-raised.
    If no exception is raised, any processes that are still alive will be killed and cause an exception to be raised.
    """
    def __init__(self):
        self.procs = []

    def add(self, name, pid):
        assert isinstance(pid, int)
        self.procs.append((name, pid))

    def __enter__(self):
        return self

    def __exit__(self, exc_typ, exc, tb):
        failures = []
        for name, pid in self.procs:
            try:
                assert_pid_dead(pid)
            except AssertionError:
                failures.append(name)
        # only report kill failures if we didn't get an exception in the main test
        if failures and exc is None:
            raise AssertionError(f"Processes failed to exit: {failures}")
        else:
            return False  # process exception normally, if any


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
            log_server.start()

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
