import logging

from teleprox.log.handler import RPCLogHandler
from teleprox.log.remote import set_process_name, set_thread_name, start_log_server


def pytest_addoption(parser):
    parser.addoption(
        "--log", 
        nargs='?',
        default=None,
        const='DEBUG',
        help="Enable logging at the specified level."
    )


def pytest_configure(config):
    """ called after command line options have been parsed and all plugins and initial conftest files been loaded. """

    # messages originating locally can be easily identified
    set_process_name('main_process')
    set_thread_name('main_thread')

    log_level = config.getoption("--log")
    print("log_level: ", log_level)
    if log_level is not None:
        
        # Set up nice logging for tests:
        # remote processes forward logs to this process
        logger = logging.getLogger()
        #logger.level = logging.DEBUG
        start_log_server(logger)
        # local log messages are time-sorted and colored
        handler = RPCLogHandler()
        logger.addHandler(handler)

        # import logging
        # logging.basicConfig(level=log_level.upper())
