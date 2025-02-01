import numpy as np
import multiprocessing.shared_memory as mp_shm
import atexit


all_shmem = []

class SharedNDArray:
    """A wrapper for a numpy ndarray that is shared between processes.

    Note that garbage collection on shared memory is somewhat broken.
    See https://github.com/python/cpython/issues/82300
    """
    def __init__(self, shmem, data, close=False):
        self.shmem = shmem
        self.data = data
        self.close = close
        all_shmem.append(shmem)

    @classmethod
    def zeros(cls, shape, dtype, close=True):
        """Create a SharedNDArray filled with zeros."""
        shmem = mp_shm.SharedMemory(create=True, size=np.prod(shape) * np.dtype(dtype).itemsize)
        data = np.ndarray(shape, dtype=dtype, buffer=shmem.buf)
        data.fill(0)
        return cls(shmem, data, close)
    
    @classmethod
    def copy(cls, arr, close):
        """Create a SharedNDArray containing a copy of the given array."""
        shmem = mp_shm.SharedMemory(create=True, size=arr.nbytes)
        data = np.ndarray(arr.shape, dtype=arr.dtype, buffer=shmem.buf)
        data[:] = arr[:]
        return cls(shmem, data, close)
        
    def __reduce__(self):
        return SharedNDArray.__reload__, (self.shmem, self.data.shape, self.data.dtype, self.data.strides)
    
    @classmethod
    def __reload__(cls, shmem, shape, dtype, strides):
        arr = np.ndarray(shape, dtype=dtype, buffer=shmem.buf, strides=strides)
        return SharedNDArray(shmem, arr)


def close_all():
    global all_shmem
    for shmem in all_shmem:
        if shmem.close:
            shmem.close()
            try:
                shmem.unlink()
            except FileNotFoundError:
                pass
    all_shmem = []

atexit.register(close_all)
