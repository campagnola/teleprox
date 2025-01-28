import types
import sys
import importlib


HAVE_QT = None
QT_LIB = None
qt_lib_order = ['PyQt6', 'PySide6', 'PyQt5', 'PySide2']

def check_qt_imported():
    """Check if a Qt library has been imported.
    
    Returns
    -------
    HAVE_QT : bool | None
        True if a Qt library has been imported, False if none are importable, None if none have been imported yet."""
    global HAVE_QT, QT_LIB
    if HAVE_QT is None:
        for qt_lib in qt_lib_order:
            if qt_lib+'.QtCore' in sys.modules or qt_lib+'.QtGui' in sys.modules or qt_lib+'.QtWidgets' in sys.modules:
                HAVE_QT = True
                QT_LIB = qt_lib
                break
    return HAVE_QT
    

check_qt_imported()


qt_namespace = None
def import_qt(qt_lib=None):
    """Import a Qt library and return a namespace with its objects.
    """
    global HAVE_QT, QT_LIB, qt_namespace
    if not HAVE_QT:
        check_qt_imported()

    if HAVE_QT is True and qt_lib is not None and qt_lib != QT_LIB:
        raise ValueError(f'Already imported Qt library: {QT_LIB}')    

    if qt_namespace is not None:
        return qt_namespace

    # search all qt libs unless specified    
    qt_libs = qt_lib_order if qt_lib is None else [qt_lib]

    # import first available
    if not HAVE_QT:
        HAVE_QT = False
        for qt_lib in qt_libs:
            try:
                importlib.import_module(qt_lib+'.QtCore')
                HAVE_QT = True
                QT_LIB = qt_lib
                break
            except ImportError:
                pass

    if not HAVE_QT:
        raise ImportError(f'No importable Qt library found (tried {", ".join(qt_libs)})')

    qt_namespace = {}
    qtcore = importlib.import_module(QT_LIB + '.QtCore')
    qt_namespace.update(qtcore.__dict__)
    qtgui = importlib.import_module(QT_LIB + '.QtGui')
    qt_namespace.update(qtgui.__dict__)
    qtwidgets = importlib.import_module(QT_LIB + '.QtWidgets')
    qt_namespace.update(qtwidgets.__dict__)
    
    if 'PySide' not in QT_LIB:
        qt_namespace['Signal'] = qt_namespace['pyqtSignal']  # for compatibility with PySide

    def make_qapp():
        """Create a QApplication object if one does not already exist.
        
        Returns
        -------
        app : QApplication
            The QApplication object.
        """
        app = qt_namespace['QApplication'].instance()
        if app is None:
            app = qt_namespace['QApplication']([])
        return app
    
    qt_namespace['make_qapp'] = make_qapp

    return qt_namespace
