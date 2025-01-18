import logging
import teleprox
from teleprox.client import RemoteCallException
from teleprox.log.remote import LogServer

class TestHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records = []
    def handle(self, record):
        self.records.append(record)
        print("LOG:", record)


def test_log_server():
    try:
        # Start a log server to catch stdout, stderr, and log messages from child processes
        logger = logging.getLogger('test_log_server_logger')
        logger.level = logging.DEBUG
        handler = TestHandler()
        logger.addHandler(handler)
        log_server = LogServer(logger)
        log_server.start()

        proc = teleprox.start_process(name='child_process', log_addr=log_server.address)
        proc.client._import('builtins').print("child stdout")
        proc.client._import('sys').stderr.write("child stderr\n")
        proc.client._import('logging').getLogger().info("child log")
        try:
            proc.client._import('fake_module')  # exception should generate a log message
        except RemoteCallException:
            pass

        assert len(handler.records) == 4
    finally:
        log_server.stop()
        proc.kill()