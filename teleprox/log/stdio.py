import logging, threading

from teleprox.log.remote import LogSender, set_thread_name


class PipePoller(threading.Thread):    
    def __init__(self, pipe, callback, prefix, name):
        threading.Thread.__init__(self, daemon=True)
        self.pipe = pipe
        self.callback = callback
        self.prefix = prefix
        self.name = name
        self.start()
        
    def run(self):
        set_thread_name(f'{self.name}_poller')
        callback = self.callback
        prefix = self.prefix
        pipe = self.pipe
        while True:
            line = pipe.readline().decode()
            if line == '':
                break
            callback(prefix + line[:-1])


class StdioLogSender:
    """Capture stdout/stderr from a process, convert to log messages, and optionally forward to a log server.

    Messages are logged to self.logger
    If log_addr is given, then a handler is attached to send messages to the log server, and the logger is not propagated.
    """
    def __init__(self, proc, name, log_addr=None, log_level=None):
        self.proc = proc
        self.log_addr = log_addr

        # create a logger for handling stdout/stderr and forwarding to log server
        # TODO id(proc) is not id(self), so this behavior is changed from before. is that okay?
        self.logger = logging.getLogger(__name__ + '.' + str(id(proc)))
        if log_addr is not None:
            self.logger.propagate = False
            self.log_handler = LogSender(log_addr, self.logger)
        if log_level is not None:
            self.logger.level = log_level
        
        # create threads to poll stdout/stderr and generate / send log records
        self.stdout_poller = PipePoller(proc.stdout, self.logger.info, f'[{name}.stdout] ', name=f'{name}_stdout')
        self.stderr_poller = PipePoller(proc.stderr, self.logger.warning, f'[{name}.stderr] ', name=f'{name}_stderr')

