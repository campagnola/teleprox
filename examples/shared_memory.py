import numpy as np
from teleprox import ProcessSpawner
from teleprox.shmem import SharedNDArray


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
