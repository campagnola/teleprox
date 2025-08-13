from .qt_util import import_qt

_orig_locals = locals().copy()
locals().update(import_qt())  # raises ImportError if no Qt library is available
locals().update(_orig_locals)
