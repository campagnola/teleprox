# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import queue
import socket
import threading
import os
import zmq
import logging
import atexit
import json
import traceback
import types

logger = logging.getLogger(__name__)

# Provide access to process and thread names for logging purposes.
# Python already has a notion of process and thread names, but these are
# apparently difficult to set. 
host_name = socket.gethostname()
process_name = "process-%d" % os.getpid()
thread_names = {}


def set_host_name(name):
    """Set the name of this host used for logging.
    """
    global host_name
    host_name = name


def get_host_name():
    """Return the name of this host used for logging.
    """
    global host_name
    return host_name


def set_process_name(name):
    """Set the name of this process used for logging.
    """
    global process_name
    process_name = name


def get_process_name():
    """Return the name of this process used for logging.
    """
    global process_name
    return process_name


def set_thread_name(name, tid=None):
    """Set the name of a thread used for logging.
    
    If no thread ID is given, then the current thread's ID is used.
    """
    global thread_names
    if tid is None:
        tid = threading.current_thread().ident
    thread_names[tid] = name


def get_thread_name(tid=None):
    """Return the name of a thread used for logging.
    
    If no thread ID is given, then the current thread's ID is used.
    """
    if tid is None:
        tid = threading.current_thread().ident
    return thread_names.get(tid, f'thread-{tid:x}')


# Provide global access to sender / server
server = None
sender = None
server_addr = None


def start_log_server():
    """Create a global log server and attach it to a logger.
    
    Use `get_logger_address()` to return the socket address for the server
    after it has started. On a remote process, call `set_logger_address()` to
    connect it to the server. Then all messages logged remotely will be
    forwarded to the server and handled by the logging system there.
    """
    global server, logger
    if server is not None:
        raise RuntimeError("A global LogServer has already been created.")
    server = LogServer(logger)


def get_logger_address():
    """ Return the address of the global LogServer used by this process.
    
    If a global LogServer has been created in this process, then its address is
    returned. Otherwise, the last address set with `set_logger_address()`
    is used.
    """
    global server, server_addr
    if server is None:
        return server_addr
    else:
        return server.address


def set_logger_address(addr):
    """Set the address to which all log messages should be sent.
    
    This function creates a global LogSender and attaches it to the root logger.
    """
    global sender, server_addr
    if sender is not None:
        sender.connect(addr)
    else:
        sender = LogSender(addr, '')
    server_addr = addr


class LogSender(logging.Handler):
    """Handler for forwarding log messages to a remote LogServer via zmq socket.
    
    Instances of this class can be attached to any python logger using
    `logger.addHandler(log_sender)`.
    
    This can be used with `LogServer` to collect log messages from many remote
    processes to a central logger.
    
    Note: We do not use RPC for this because we have to avoid generating extra
    log messages.
    
    Parameters
    ----------
    address : str | None
        The socket address of a log server. If None, then the sender is
        not connected to a server and `connect()` must be called later.
    logger : str | None
        The name of the python logger to which this handler should be attached.
        If None, then the handler is not attached (use '' for the root logger).
    
    """

    def __init__(self, address=None, logger=None):
        self.socket = None
        logging.Handler.__init__(self)

        # attach to logger if requested
        if isinstance(logger, str):
            logger = logging.getLogger(logger)
        if logger is not None:
            logger.addHandler(self)

        # make thread-safe: handle() may be called from any thread
        # and log records are passed to the server in a background thread.
        self.record_queue = queue.Queue()
        self.thread = threading.Thread(target=self.run, daemon=True, name='teleprox_LogSender')
        self.thread.start()

        if address is not None:
            self.connect(address)

        atexit.register(self.close)

    def handle(self, record):
        self.record_queue.put(record)
        return True

    def run(self):
        while True:
            record = self.record_queue.get()
            if record is None:
                break
            self._handle(record)

    def _handle(self, record):
        global host_name, process_name, thread_names
        if self.socket is None:
            return
        try:
            rec = record.__dict__.copy()
            args = rec.pop('args')
            if len(args) > 0:
                rec['msg'] = rec['msg'] % args
            if process_name is not None:
                rec['processName'] = process_name
            rec['threadName'] = thread_names.get(rec['thread'], rec['threadName'])
            rec['hostName'] = host_name

            # Serialize non-JSON-serializable attributes
            rec = self._serialize_record(record, rec)

            self.socket.send(json.dumps(rec).encode('utf-8'))
        except Exception as e:
            # send manually-formatted json error record for safety
            self.socket.send(
                f'{{"msg": "Error sending log record: {str(e)}", "levelname": "ERROR", "levelno": {logging.ERROR}}}'.encode(
                    'utf-8'))

    def _serialize_record(self, record, rec):
        """Serialize a log record dictionary for JSON transmission.
        
        Converts non-serializable objects to serializable forms:
        - exc_info -> exc_text using handler's formatter
        - Exception objects -> traceback.format_exception() output
        - StackSummary objects -> traceback.format_exception() output
        - Traceback objects -> traceback.format_exception() output
        - Other objects -> string representation as fallback
        """
        serialized = {}

        for key, value in rec.items():
            if key in serialized:
                # specifically: rec['exc_info'] becomes serialized['exc_text'], and we don't want to overwrite that
                # if rec['exc_text'] is also present.
                continue

            if key == 'exc_info' and value is not None:
                # Use handler's formatter to convert exc_info to exc_text
                try:
                    formatter = self.formatter or logging.Formatter()
                    serialized['exc_text'] = formatter.formatException(value)
                    # Don't include exc_info in serialized record
                    continue
                except (TypeError, ValueError):
                    # If exc_info is malformed, fall back to string representation
                    serialized[key] = str(value)
                    continue

            # Try to serialize the value
            try:
                json.dumps(value)  # Test if it's JSON serializable
                serialized[key] = value
            except (TypeError, ValueError):
                # Handle specific non-serializable types
                try:
                    if isinstance(value, Exception):
                        # For Exception objects, format with traceback.format_exception
                        exc_type = type(value)
                        exc_value = value
                        exc_tb = getattr(value, '__traceback__', None)
                        serialized[key] = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
                    elif isinstance(value, types.TracebackType):  # Traceback objects
                        # For Traceback objects, format with traceback.format_tb
                        serialized[key] = ''.join(traceback.format_tb(value))
                    elif isinstance(value, traceback.StackSummary):  # StackSummary objects
                        # For StackSummary objects, use the format method directly
                        serialized[key] = ''.join(value.format())
                    else:
                        # Fallback to string representation for other types
                        serialized[key] = str(value)
                except:
                    # Final fallback to string representation for any formatting errors
                    serialized[key] = str(value)

        return serialized

    def connect(self, addr):
        """Set the address of the LogServer to which log messages should be
        sent. This value should be acquired from `log_server.address` or
        `get_logger_address()`.
        """
        if self.socket is not None:
            self.socket.close()

        self.socket = zmq.Context.instance().socket(zmq.PUSH)
        self.socket.linger = 1000  # don't let socket deadlock when exiting
        self.socket.connect(addr)

    def close(self):
        # if this socket is left open when the process exits, it can lead to
        # deadlock.
        self.record_queue.put(None)
        socket, self.socket = self.socket, None
        if socket is not None:
            socket.close()


class LogServer(threading.Thread):
    """Thread for receiving log records via zmq socket from a LogSender.
    
    Messages are immediately passed to a python logger for local handling.
    
    Parameters
    ----------
    logger : Logger
        The python logger that should handle incoming messages.
    address : str
        The zmq address to which the server should bind. Default is 
        'tcp://127.0.0.1:*'.
    filter_by_level : bool
        If True (default), then only messages with a level greater than or equal
        to the logger's level will be passed to the logger.

    Notes
    -----
    Log messages are passed to a LogServer via a LogSender in a remote process.
    The LogSender is attached to a logger hierarchy, and these loggers must decide
    (by their level) which messages to send to the LogServer. In a sense, this 
    allows loggers in a remote process to become part of the local logging hierarchy.

    However, this also breaks the normal behavior of loggers inheriting their level
    from their parents. Ordinarily once can set the level of the root logger and
    expect most upstream loggers to inherit this level. Remote loggers, on the other
    hand, have their own level which could cause low-level messages to be handled
    in the main process even if the local logger's level is set higher. To avoid this,
    the `filter_by_level` parameter can be set to True to filter out messages that
    are below the local logger's effective level.
    """

    def __init__(self, logger, address='tcp://127.0.0.1:*', filter_by_level=True):
        threading.Thread.__init__(self, daemon=True)
        self.running = True
        self.filter_by_level = filter_by_level
        if isinstance(logger, str):
            logger = logging.getLogger(logger)
        self.logger = logger
        self.socket = zmq.Context.instance().socket(zmq.PULL)
        self.socket.linger = 1000  # don't let socket deadlock when exiting
        self.socket.bind(address)
        self.address = self.socket.last_endpoint
        self.start()

    def stop(self):
        self.running = False

    def run(self):
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        while self.running:
            events = dict(poller.poll(1000))
            if self.socket not in events:
                continue
            msg = self.socket.recv()
            kwds = json.loads(msg)
            rec = logging.makeLogRecord(kwds)
            if self.filter_by_level and rec.levelno < self.logger.getEffectiveLevel():
                continue
            self.logger.handle(rec)
        self.socket.close()
