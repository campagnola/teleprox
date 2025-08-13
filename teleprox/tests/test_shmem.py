import numpy as np

from teleprox import start_process, SharedNDArray


def test_shared_ndarray():
    proc = start_process('test_shared_ndarray', start_local_server=False)
    cli = proc.client
    shared = SharedNDArray.copy(np.array([1, 2, 3]))
    rmt_shared = cli.transfer(shared)
    assert rmt_shared.data.shape == shared.data.shape

    # test closing nicely
    proc.stop()
    assert shared.data[0] == 1
