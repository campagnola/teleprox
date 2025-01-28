import logging
import os
import sys
import time

import pytest

import teleprox, teleprox.util, teleprox.process
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

    parser.addoption(
        "--threadtrace", 
        nargs='?',
        default=None,
        const='DEBUG',
        help="Enable ThreadTrace in main process"
    )



def pytest_configure(config):
    """ called after command line options have been parsed and all plugins and initial conftest files been loaded. """

    # messages originating locally can be easily identified
    set_process_name('main_process')
    set_thread_name('main_thread')

    log_level = config.getoption("--log")
    if log_level is not None:
        print(f"Setting log level to {log_level}")
        
        # Set up nice logging for tests:
        # remote processes forward logs to this process
        global logger
        logger = logging.getLogger()
        logger.setLevel(log_level.upper())
        start_log_server(logger)
        # local log messages are time-sorted and colored
        handler = RPCLogHandler()
        logger.addHandler(handler)

        # import logging
        # logging.basicConfig(level=log_level.upper())

    if config.getoption("--threadtrace"):
        from pyqtgraph.debug import ThreadTrace
        global tt
        tt = ThreadTrace()


@pytest.fixture(scope="session", autouse=True)
def process_name_prefix():
    # All (grand)child processes will have this prefix for easy cleanup
    prefix = f'teleprox_test_{os.getpid()}:'
    teleprox.process.PROCESS_NAME_PREFIX = prefix
    yield prefix
    assert teleprox.process.PROCESS_NAME_PREFIX == prefix, "Process name prefix was changed during test run, this is not allowed."


def pytest_collection_modifyitems(items):
    # move the stray child test to the end
    for item in items:
        if item.name == 'test_stray_children':
            items.remove(item)
            items.append(item)
            break
