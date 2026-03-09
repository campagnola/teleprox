from .qt_util import get_qt_module, qt_submodules


def make_qapp():
    """Create a QApplication object if one does not already exist."""
    app = __getattr__('QApplication').instance()
    if app is None:
        app = __getattr__('QApplication')([])
    return app


qt_shims = {
    'PyQt6': {
        'Signal': 'pyqtSignal',
    },
    'PySide6': {},
    'PyQt5': {
        'Signal': 'pyqtSignal',
    },
    'PySide2': {},
}

lookup_cache = {}


def __getattr__(name):
    # flatten Qt submodules into top-level namespace for convenience, with caching
    if name in lookup_cache:
        return lookup_cache[name]
    
    qt_module = get_qt_module()
    name = qt_shims[qt_module.__name__].get(name, name)

    for sub_name in qt_submodules:
        submodule = getattr(qt_module, sub_name)
        if hasattr(submodule, name):
            value = getattr(submodule, name)
            lookup_cache[name] = value
            return value

    if name in qt_submodules:
        # allow direct access to submodules as well
        value = getattr(qt_module, name)
        lookup_cache[name] = value
        return value

    raise AttributeError(f"Attribute '{name}' not found in Qt submodules: {qt_submodules}")
