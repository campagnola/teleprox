import sys, traceback, logging, time, re
import threading
from teleprox.log.remote import LogServer


def trace_stdio():
    """Injects a stack trace into stdout and stderr to determine where output is coming from.
    """
    class S:
        def __init__(self, stream):
            self.stream = stream
        def write(self, *args):
            sys.__stdout__.write(''.join(traceback.format_stack()) + '\n')
            sys.__stdout__.flush()
            self.stream.write(repr(args[0]) + '\n', *args[1:])
        def flush(self):
            self.stream.flush()

    sys.stdout = S(sys.__stdout__)
    sys.stderr = S(sys.__stderr__)


class DebugLogHandler(logging.Handler):
    def __init__(self, logger):
        logging.Handler.__init__(self)
        self.logger = logger
    def emit(self, record):
        print(f"Logger {self.logger}[{self.logger.level}] received record[{record.levelno}]: {record.msg}")


def debug_loggers():
    """Attach a DebugLogHandler to all loggers in the logging hierarchy.
    """
    all_loggers = [l for l in logging.Logger.manager.loggerDict.values() if isinstance(l, logging.Logger)] + [logging.getLogger('')]
    for logger in all_loggers:
        logger.addHandler(DebugLogHandler(logger))


def raise_exception_in_stack(depth=3):
    """Raises an exception in the stack at a given depth.
    """
    if depth < 1:
        raise Exception("Raised test exception")
    else:
        raise_exception_in_stack(depth - 1)


def raise_exception_in_thread():
    """Raises an exception in a new thread.
    """
    thread = threading.Thread(target=raise_exception_in_stack)
    thread.start()
    thread.join()  # Wait for the thread to finish, so the exception can be caught in the main thread.


class RecordingLogHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records = []

    def handle(self, record):
        self.records.append(record)
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
        self.handler = RecordingLogHandler()
        self.logger.addHandler(self.handler)
        self.log_server = LogServer(self.logger)
        self.address = self.log_server.address

    def find_message(self, regex, timeout=0.5):
        start_time = time.perf_counter()
        while time.perf_counter() - start_time < timeout:
            rec = self.handler.find_message(regex)
            if rec is not None:
                return rec
            time.sleep(0.1)        

    def stop(self):
        self.log_server.stop()
        self.logger.removeHandler(self.handler)

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


