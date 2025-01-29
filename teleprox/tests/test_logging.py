import logging
import re
import time
import teleprox
from teleprox.client import RemoteCallException
from teleprox.log.remote import LogServer
from teleprox.util import ProcessCleaner, assert_pid_dead


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


class RemoteLogRecorder:
    """Sets up a log server to receive log messages and a handler to store them.
    """
    def __init__(self, name):
        self.logger = logging.getLogger(name)
        self.logger.level = logging.DEBUG
        self.logger.propagate = False  # keep these messages for ourselves
        self.handler = Handler()
        self.logger.addHandler(self.handler)
        self.log_server = LogServer(self.logger)
        self.log_server.start()
        self.address = self.log_server.address

    def find_message(self, regex):
        return self.handler.find_message(regex)

    def stop(self):
        self.log_server.stop()
        self.logger.removeHandler(self.handler)

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()



def test_log_server():
    logger = None
    proc = None
    try:
        # Start a log server to catch stdout, stderr, and log messages from child processes
        logger = RemoteLogRecorder('test_log_server_logger')

        proc = teleprox.start_process(name='child_process', log_addr=logger.address, log_level=logging.INFO)
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
            (r"child_process.stdout\] message 1", logging.INFO),
            (r"child_process.stderr\] message 2", logging.WARNING),
            (r"logged message 3", logging.INFO),
            (r".*No module named 'fake_module'.*", logging.WARNING),
        ]
        for regex, level in expected:
            rec = logger.find_message(regex)
            assert rec is not None, f"Expected log message not found: {regex}"
            assert rec.levelno == level

    finally:
        if proc is not None:
            assert_pid_dead(proc.pid)
        if logger is not None:
            logger.stop()


def test_quick_exit():
    # can we get log messages if the process exits immediately after generating them?
    with ProcessCleaner() as cleaner:
        with RemoteLogRecorder('test_quick_exit_logger') as logger:
            proc = teleprox.start_process(name='test_quick_exit_logged', log_addr=logger.address, log_level=logging.INFO)
            cleaner.add(proc)
            proc.client._import('logging').getLogger().info("quick exit message")
            proc.stop()

            assert logger.find_message(r"quick exit message") is not None

    with ProcessCleaner() as cleaner:
        with RemoteLogRecorder('test_quick_exit_logger') as logger:
            proc = teleprox.start_process(name='test_quick_exit_stdout', log_addr=logger.address, log_level=logging.INFO)
            cleaner.add(proc)
            proc.client._import('sys').stdout.write("quick exit message\n")
            proc.stop()

            assert logger.find_message(r"quick exit message") is not None


def test_unhandled_exception():
    with ProcessCleaner() as cleaner:
        with RemoteLogRecorder('test_unhandled_exception_logger') as logger:
            proc = teleprox.start_process(name='test_unhandled_exception', log_addr=logger.address, log_level=logging.INFO)
            cleaner.add(proc)

            # should generate an unhandled exception log message
            proc.client._import('os').listdir('nonexistent', _sync='off')

            time.sleep(0.1)  # wait for log messages to be received
            proc.stop()

            assert logger.find_message(r"Unhandled exception") is not None