import numpy as np
from teleprox import ProcessSpawner
from teleprox.shmem import SharedNDArray


"""
Note: Python shared memory has some issues at the time of writing..
https://github.com/python/cpython/issues/82300
In particular, it uses resource tracking so that shared memory
won't be leaked on posix systems (windows does this automatically),
but the resource tracking doesn't always work correctly. 

The practical effects are:
- Extra warnings about leaked shared_memory objects appear at exit time 
- Closing any process that has a shared memory object may cause the shared memory
  to be unlinked, preventing other processes from accessing it.
"""

# proc = ProcessSpawner(serializer='msgpack')
proc = ProcessSpawner(name='child_process')

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

# close shared memory on both ends before exiting
remote_shared_arr.shmem.close()
local_shared_arr.shmem.close()
local_shared_arr.shmem.unlink()
