from .qt_util import import_qt

_orig_locals = locals().copy()
locals().update(import_qt())
locals().update(_orig_locals)