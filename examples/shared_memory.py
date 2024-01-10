import logging
import numpy as np
from teleprox import ProcessSpawner
from teleprox.log import set_process_name, set_thread_name, start_log_server
from teleprox.log.logviewer import LogViewer
from teleprox.log.handler import RPCLogHandler
from teleprox.shmem import SharedNDArray

# logger = logging.getLogger()
# logger.level = logging.DEBUG

# handler = RPCLogHandler()
# logger.addHandler(handler)
# # logging.basicConfig()

# # Start a server that will receive log messages from other processes
# start_log_server(logger)
# set_process_name('main_process')
# set_thread_name('main_thread')

# import pyqtgraph as pg
# pg.mkQApp()
# lv = LogViewer()
# lv.show()


# proc = ProcessSpawner(serializer='msgpack')
proc = ProcessSpawner(name='child_process', serializer='msgpack')

# create a local array
arr = np.arange(100).reshape(10, 10)

# copy it to shared memory
local_shared_arr = SharedNDArray.copy(arr)

# send the shared array to the remote process
remote_shared_arr = proc.client.transfer(local_shared_arr)

# use the remote process to compute the mean of the array
# (and verify that the result is correct)
assert local_shared_arr.data.mean() == remote_shared_arr.data.mean()

# modify the local array and verify that the remote array has the same values
local_shared_arr.data[:] = np.random.normal(size=local_shared_arr.data.shape)
assert (remote_shared_arr.data == local_shared_arr.data).all()
