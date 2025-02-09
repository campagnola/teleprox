import numpy as np
import multiprocessing.shared_memory as mp_shm
import atexit


all_shmem = []

class SharedNDArray:
    """A wrapper for a numpy ndarray that is shared between processes.

    Typically initialized using SharedNDArray.zeros() or SharedNDArray.copy().

    Parameters
    ----------
    shmem : multiprocessing.shared_memory.SharedMemory
        A SharedMemory instance
    data : ndarray
        A numpy array pointing to the shared memory buffer
    close : bool
        Whether the shared memory should be closed at exit or when 
        close_all() is called.

    Notes
    -----
    Garbage collection on shared memory is somewhat broken
    (see https://github.com/python/cpython/issues/82300).
    In particular, it uses resource tracking so that shared memory
    won't be leaked on posix systems (whereas windows does this automatically),
    but the resource tracking doesn't always work correctly. 

    The practical effects are:
    - Extra warnings about leaked shared_memory objects appear at exit time 
    - Closing any process that has a shared memory object may cause the shared memory
      to be unlinked, preventing other processes from accessing it.
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
    def copy(cls, arr, close=True):
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
