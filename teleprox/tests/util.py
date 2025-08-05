import sys, traceback, logging


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
