# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

from .remote import (get_logger_address, set_logger_address, 
                     get_host_name, set_host_name,
                     get_process_name, set_process_name, 
                     get_thread_name, set_thread_name,
                     start_log_server, LogSender, LogServer)
from .handler import RPCLogHandler, log_exceptions


basic_handler = None
def basic_config(log_level='INFO', exceptions=True, start_server=True):
    """Convenience function to log messages to stderr
    
    Similar to logging.basicConfig, but uses an RPCLogHandler to 
    ensure that messages collceted from multiple processes are
    time-sorted before being displayed. (also colors output by 
    the originating process/thread)

    Optionally log all uncaught exceptions in this process.
    """
    import logging
    global basic_handler
    logger = logging.getLogger('')
    logger.setLevel(log_level)

    basic_handler = RPCLogHandler()
    logger.addHandler(basic_handler)

    if exceptions:
        log_exceptions()

    if start_server:
        start_log_server()
