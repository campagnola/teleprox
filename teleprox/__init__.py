# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

__version__ = "1.0.2"

from .client import RPCClient, RemoteCallException, Future
from .server import RPCServer
from .qt_server import QtRPCServer
from .proxy import ObjectProxy
from .process import start_process, DaemonProcess, ChildProcess
from .processspawner import ProcessSpawner  # for backward compatibility (use start_process instead)
