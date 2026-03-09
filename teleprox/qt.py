import contextlib
import importlib
import sys
from types import ModuleType

# order of preference for Qt libraries to import
qt_lib_order = ['PyQt6', 'PySide6', 'PyQt5', 'PySide2']

# automatically import submodules to make them available for __getattr__
qt_submodules = ['QtCore', 'QtGui', 'QtWidgets', 'QtTest']

QT_LIB = None
HAVE_QT = None


def check_qt_imported():
    """Check if a Qt library has been imported.

    Returns
    -------
    qt_lib : str | None
        The name of the imported Qt library, or None if none have been imported yet.
    """
    for qt_lib in qt_lib_order:
        if (
            f'{qt_lib}.QtCore' in sys.modules
            or f'{qt_lib}.QtGui' in sys.modules
            or f'{qt_lib}.QtWidgets' in sys.modules
        ):
            return qt_lib


def have_qt():
    if HAVE_QT is not None:
        return HAVE_QT
    
    try:
        get_qt_module()
        return True
    except ImportError:
        return False


def get_qt_module() -> ModuleType:
    """Return the top-level module of a Qt library (PyQt or Pyside).
    
    If one is already imported, it will be returned. 
    Otherwise, the first importable library will be imported and returned.

    Order is set by qt_lib_order.
    """
    global QT_LIB, HAVE_QT
    if QT_LIB is not None:
        return QT_LIB

    qt_lib = check_qt_imported()
    if qt_lib is None:
        # check all qt libs in order
        libs_to_check = qt_lib_order
    else:
        # only try importing the already imported library
        libs_to_check = [qt_lib]

    # import first available
    for qt_lib in libs_to_check:
        with contextlib.suppress(ImportError):            
            for submodule in qt_submodules:
                importlib.import_module(f'{qt_lib}.{submodule}')
            HAVE_QT = True
            print(f'Using Qt library: {qt_lib}')
            import traceback
            traceback.print_stack()
            QT_LIB = importlib.import_module(f'{qt_lib}')
            return QT_LIB
    
    HAVE_QT = False
    raise ImportError(f'No importable Qt library found (tried {", ".join(libs_to_check)})')


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
    print(f'Looking up {name} in qt module')
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

