# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

from teleprox import ProcessSpawner
import os
from check_qt import requires_qt


def test_spawner():
    proc = ProcessSpawner()
    cli = proc.client
    
    # check spawned RPC server has a different PID
    ros = cli._import('os')
    assert os.getpid() != ros.getpid()
    
    # test closing nicely
    proc.stop()


def test_serverless_client():
    proc = ProcessSpawner(start_server=False)
    cli = proc.client

    # check spawned RPC server has a different PID
    ros = cli._import('os')
    assert os.getpid() != ros.getpid()

    class CustomType:
        def __init__(self):
            self.x = 1
            self.y = 'a'

        def __eq__(self, a):
            return type(a) == type(self) and a.x == self.x and a.y == self.y

    proxy = cli.transfer(CustomType())
    assert proxy == CustomType()
    # test closing nicely
    proc.stop()


@requires_qt
def test_qt_spawner():
    # start process with QtRPCServer
    proc = ProcessSpawner(qt=True)
    cli = proc.client

    rqt = cli._import('teleprox.qt')
    assert rqt.QApplication.instance() is not None

    # test closing Qt process
    proc.stop()
    