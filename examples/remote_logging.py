import sys
import logging
import sys
from teleprox import start_process
from teleprox.log import set_process_name, set_thread_name, start_log_server
from teleprox.log.handler import RPCLogHandler
from teleprox.log.logviewer import LogViewer


# Get the python root logger and set its level to DEBUG
logger = logging.getLogger()
logger.level = logging.DEBUG

# Create a handler that prints to stderr with formatting that includes the source
# process and thread.
handler = RPCLogHandler()
logger.addHandler(handler)

# Start a server that will receive log messages from other processes
start_log_server()

# Set the name of this process and thread for logging
set_process_name('main_process')
set_thread_name('main_thread')

# If running interactively, show a UI that will display log messages
if sys.flags.interactive:
    import teleprox.qt
    app = teleprox.qt.QApplication([])
    lv = LogViewer()
    lv.show()


logger.info("Starting child process to test remote logging...")

proc = start_process(name='child_process')

r_os = proc.client._import('os')
print("Child process PID is:", r_os.getpid())

logger.info("Writing 'Hello' to stdout in child process (should be propagated back to log server)")
r_sys = proc.client._import('sys')
r_sys.stdout.write("Hello from child process!\n")

# test making a remote call that raises an exception
logger.warning("Raising an exception in the child process..")
r_util = proc.client._import('teleprox.tests.util')
try:
    r_util.raise_exception_in_stack()
except Exception as e:
    logger.error(f"Exception raised in child process: {e}", exc_info=True)
    
# test an unhandled exception in a thread in the child process
logger.warning("Raising an unhandled exception in the child process..")
r_util.raise_exception_in_thread()

# wait a bit to let the log messages propagate
if not sys.flags.interactive:
    import time
    time.sleep(1)
else:
    print("All done. To see messages in an interactive viewer, run using `python -i`") 
