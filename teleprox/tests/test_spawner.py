# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import os

import pytest

from teleprox import start_process
from teleprox.tests.check_qt import requires_qt


def test_spawner():
    proc = start_process('test_spawner_proc')
    cli = proc.client
    
    # check spawned RPC server has a different PID
    ros = cli._import('os')
    assert os.getpid() != ros.getpid()
    
    # test closing nicely
    proc.stop()


def test_serverless_client():
    proc = start_process('test_serverless_client_proc', start_local_server=False)
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
    proc.stop()


@requires_qt
def test_qt_spawner():
    # start process with QtRPCServer
    proc = start_process('test_qt_spawner_proc', qt=True)
    cli = proc.client

    rqt = cli._import('teleprox.qt')
    assert rqt.QApplication.instance() is not None

    # test closing Qt process
    proc.stop()
