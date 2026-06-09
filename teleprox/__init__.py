__version__ = "2.2.1"

from .client import RPCClient, RemoteCallException, Future
from .server import RPCServer
from .qt_server import QtRPCServer
from .proxy import ObjectProxy
from .process import start_process, DaemonProcess, ChildProcess
from .processspawner import ProcessSpawner  # for backward compatibility (use start_process instead)

# Re-export the throughline submodule so callers can opt in to gentletask
# throughline propagation across the process boundary:
#     from teleprox import throughline
#     throughline.enable_throughline_propagation()
# Propagation is OPT-IN and is NOT wired up at import; see throughline.py.
from . import throughline
