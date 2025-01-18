import logging
import signal
import sys
import os
import time
import pytest
from teleprox import start_process
from teleprox.log.remote import LogServer, start_log_server
from teleprox.util import assert_pid_dead


def test_daemon():
    """Check that daemon processes can be started and stopped, and outlive their parents.
    """
    pids_to_clean = {}

    got_exception = False
    try:
        # start a child
        child1 = start_process()
        pids_to_clean['child1'] = child1.pid

        # ask the child to start a daemon
        daemon = child1.client._import('teleprox').start_process(daemon=False)
        address = daemon.client.address._get_value()
        pid = daemon.client._import('os').getpid()
        pids_to_clean['daemon'] = pid

        # kill the child; check that we can still connect to daemon
        time.sleep(1)
        print(f"Killing child1 with pid {child1.pid}")
        try:
            child1.kill()
        except Exception as exc:
            try:
                assert_pid_dead(child1.pid)
            except AssertionError:
                print("Failed to kill child1")
            raise exc

        # start second child
        child2 = start_process()
        pids_to_clean['child2'] = child2.pid

        # ask second child to connect to daemon
        daemon_client = child2.client._import('teleprox').RPCClient(address=address)

        # check the daemon works as expected
        assert pid == daemon_client._import('os').getpid()

        # test closing daemon nicely
        daemon_client.close_server()
        time.sleep(0.3)  # wait for server to close

        child2.kill()
    except Exception as exc:
        got_exception = True  # used to mask failures to close processes in finally:
        raise
    finally:
        # Check that all 3 processes have already ended
        for name, pid in pids_to_clean.items():
            failures = []
            try:
                assert_pid_dead(pid)
            except AssertionError:
                failures.append(name)
        # only report kill failures if we didn't get an exception in the main test
        if not got_exception and failures:
            raise AssertionError(f"Failed to kill processes: {failures}") from exc


def test_daemon_stdio():
    """Check that daemon process stdout and stderr are redirected to /dev/null.
    """
    try:
        # Start a log server to catch stdout and stderr from child processes    
        log_records = []
        logger = logging.getLogger('test_daemon_stdio_logger')
        logger.level = logging.DEBUG
        def handler(record):
            log_records.append(record)
            print("LOG:", record)
        logger.addHandler(handler)
        log_server = LogServer(logger)
        log_server.start()

        # create a child process and log all of its stdout/stderr
        child = start_process(name='child_process', log_addr=log_server.address)
        pids_to_clean = {'child': child.pid}

        # create a grandchild process and check that printing from here is logged (because normal children share stdio with parents)
        child2 = child.client._import('teleprox').start_process(name='child2_process')
        pids_to_clean['child2'] = child2.pid
        child2.client._import('builtins').print("from child2")
        time.sleep(0.1)
        assert len(log_records) == 1 and log_records[0].msg == "from child2"

        # create a daemon process and check that printing from here is not logged
        daemon = child.client._import('teleprox').start_process(daemon=True)
        pids_to_clean['daemon'] = daemon.pid
        daemon.client._import('builtins').print("from daemon")
        time.sleep(0.1)
        assert len(log_records) == 1   # no new messages should have been logged

        daemon.kill()
        child.kill()
        child2.kill()

    finally:
        log_server.stop()
        for name, pid in pids_to_clean.items():
            try:
                assert_pid_dead(pid)
            except AssertionError:
                print(f"Failed to kill {name} with pid {pid}")
                raise
