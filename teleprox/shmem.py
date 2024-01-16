import numpy as np
import multiprocessing.shared_memory as mp_shm


class SharedNDArray:
    def __init__(self, shmem, data):
        self.shmem = shmem
        self.data = data

    @classmethod
    def copy(cls, arr: np.ndarray):
        """Create a SharedNDArray containing a copy of the given array."""
        shmem = mp_shm.SharedMemory(create=True, size=arr.nbytes)
        data = np.ndarray(arr.shape, dtype=arr.dtype, buffer=shmem.buf)
        data[:] = arr[:]
        return cls(shmem, data)
        
    def __reduce__(self):
        return SharedNDArray.__reload__, (self.shmem, self.data.shape, self.data.dtype, self.data.strides)
    
    @classmethod
    def __reload__(cls, shmem, shape, dtype, strides):
        arr = np.ndarray(shape, dtype=dtype, buffer=shmem.buf, strides=strides)
        return SharedNDArray(shmem, arr)
