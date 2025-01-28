import logging
import re
import time
import teleprox
from teleprox.client import RemoteCallException
from teleprox.log.remote import LogServer
from teleprox.util import assert_pid_dead


class Handler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records = []

    def handle(self, record):
        self.records.append(record)
        # print("LOG:", record)
        return True

    def find_message(self, regex):
        for record in self.records:
            if re.search(regex, record.msg):
                return record
        return None
    
    def __str__(self):
        return '\n'.join([str(record) for record in self.records])


def test_log_server():
    log_server = None
    proc = None
    try:
        # Start a log server to catch stdout, stderr, and log messages from child processes
        logger = logging.getLogger('test_log_server_logger')
        logger.level = logging.DEBUG
        logger.propagate = False  # keep these messages for ourselves
        handler = Handler()
        logger.addHandler(handler)
        log_server = LogServer(logger)
        log_server.start()

        proc = teleprox.start_process(name='child_process', log_addr=log_server.address, log_level=logging.INFO)
        # check that we get log records for the child's stdout
        proc.client._import('sys').stdout.write("message 1\n")
        # check that we get log records for the child's stderr
        proc.client._import('sys').stderr.write("message 2\n")
        # check that the child's log messages are propagated to the server
        proc.client._import('logging').getLogger().info("logged message 3")
        # check that log messages are generated for exceptions in the child
        try:
            proc.client._import('fake_module')  # exception should generate a log message
        except RemoteCallException:
            pass

        time.sleep(0.1)  # wait for log messages to be received
        proc.stop()

        expected = [
            (r"\[child_process.stdout\] message 1", logging.INFO),
            (r"\[child_process.stderr\] message 2", logging.WARNING),
            (r"logged message 3", logging.INFO),
            (r".*No module named 'fake_module'.*", logging.WARNING),
        ]
        for regex, level in expected:
            rec = handler.find_message(regex)
            assert rec is not None
            assert rec.levelno == level

    finally:
        if proc is not None:
            assert_pid_dead(proc.pid)
        if log_server is not None:
            log_server.stop()
