import logging
from teleprox import start_process
from teleprox.log import set_process_name, set_thread_name, start_log_server
from teleprox.log.logviewer import LogViewer
from teleprox.log.handler import RPCLogHandler


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

# import pyqtgraph as pg
# pg.mkQApp()
from PyQt5 import QtWidgets
app = QtWidgets.QApplication([])
lv = LogViewer()
lv.show()


proc = start_process(name='child_process')

r_os = proc.client._import('os')
print("Child process PID is:", r_os.getpid())

r_sys = proc.client._import('sys')
r_sys.stdout.write("Hello from child process!\n")

