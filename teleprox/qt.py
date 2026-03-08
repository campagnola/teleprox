import importlib
from .qt_util import import_qt

# Ensure Qt is importable and determine which library to use.
# import_qt() raises ImportError if no Qt library is available.
_qt_namespace = import_qt()

# Expose make_qapp and Signal directly so they are always findable.
make_qapp = _qt_namespace['make_qapp']
Signal = _qt_namespace['Signal']

# Submodules to search for attribute lookups, in order.
_QT_SUBMODULES = ['QtCore', 'QtGui', 'QtWidgets', 'QtTest']
_qt_submodule_objects = {}


def _get_submodules():
    from .qt_util import QT_LIB
    if not _qt_submodule_objects:
        for sub in _QT_SUBMODULES:
            try:
                _qt_submodule_objects[sub] = importlib.import_module(f'{QT_LIB}.{sub}')
            except ImportError:
                pass
    return _qt_submodule_objects


def __getattr__(name):
    for mod in _get_submodules().values():
        try:
            return getattr(mod, name)
        except AttributeError:
            pass
    raise AttributeError(f"module 'teleprox.qt' has no attribute {name!r}")
