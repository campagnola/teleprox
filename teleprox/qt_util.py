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
    global QT_LIB
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
    QT_LIB = import_qt_lib(libs_to_check)
    return QT_LIB


def import_qt_lib(libs_to_check):
    """Import the first available Qt library from the given list of library names.

    Also adds Qt types to the default serializer types list, so that they can be serialized    
    """
    global HAVE_QT

    qt_module = None
    for qt_lib in libs_to_check:
        with contextlib.suppress(ImportError):            
            for submodule in qt_submodules:
                importlib.import_module(f'{qt_lib}.{submodule}')
            HAVE_QT = True
            # print(f'Using Qt library: {qt_lib}')
            # import traceback
            # traceback.print_stack()
            qt_module = importlib.import_module(f'{qt_lib}')
        
    if HAVE_QT is not True:
        HAVE_QT = False
        raise ImportError(f'No importable Qt library found (tried {", ".join(libs_to_check)})')

    from . import serializer
    qtcore = getattr(qt_module, 'QtCore')
    qtgui = getattr(qt_module, 'QtGui')
    serializer.default_serialize_types += (
        qtgui.QMatrix4x4, qtgui.QMatrix3x3, qtgui.QMatrix2x2, qtgui.QTransform,
        qtgui.QVector3D, qtgui.QVector4D, qtgui.QQuaternion,
        qtcore.QPoint, qtcore.QSize, qtcore.QRect, qtcore.QLine, qtcore.QLineF,
        qtcore.QPointF, qtcore.QSizeF, qtcore.QRectF,
    )

    return qt_module

