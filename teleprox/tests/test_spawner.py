# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.
import logging

import numpy as np
import pytest

from teleprox import ProcessSpawner
import os
from check_qt import requires_qt
from teleprox.shmem import SharedNDArray


def test_spawner():
    proc = ProcessSpawner(name='test_spawner')
    cli = proc.client
    
    # check spawned RPC server has a different PID
    ros = cli._import('os')
    assert os.getpid() != ros.getpid()
    
    # test closing nicely
    proc.stop()


def test_serverless_client():
    proc = ProcessSpawner(name='test_serverless_client', start_local_server=False)
    cli = proc.client

    # check spawned RPC server has a different PID
    ros = cli._import('os')
    assert os.getpid() != ros.getpid()

    class CustomType:
        pass

    with pytest.raises(TypeError):
        cli.transfer(CustomType())

    rmt_os = cli._import('os')
    rmt_os.getpid()


def test_shared_ndarray():
    proc = ProcessSpawner(name='test_shared_ndarray', start_local_server=False)
    cli = proc.client
    shared = SharedNDArray.copy(np.array([1, 2, 3]))
    rmt_shared = cli.transfer(shared)
    assert rmt_shared.data.shape == shared.data.shape

    # test closing nicely
    proc.stop()
    assert shared.data[0] == 1


@requires_qt
def test_qt_spawner():
    # start process with QtRPCServer
    proc = ProcessSpawner(name='test_qt_spawner', qt=True)
    cli = proc.client

    rqt = cli._import('teleprox.qt')
    assert rqt.QApplication.instance() is not None

    # test closing Qt process
    proc.stop()
    