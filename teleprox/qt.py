import sys
import importlib


def import_qt_namespace(qt_lib):
    ns = {}
    qtcore = importlib.import_module(qt_lib + '.QtCore')
    ns.update(qtcore.__dict__)
    qtgui = importlib.import_module(qt_lib + '.QtGui')
    ns.update(qtgui.__dict__)
    qtwidgets = importlib.import_module(qt_lib + '.QtWidgets')
    ns.update(qtwidgets.__dict__)
    return ns


HAVE_QT = False
qt_libs = ['PyQt6', 'PySide6', 'PyQt5', 'PySide2']

# already imported?
for qt_lib in qt_libs:
    if qt_lib in sys.modules:
        HAVE_QT = True
        QT_LIB = qt_lib
        break

# import first available
for qt_lib in qt_libs:
    try:
        importlib.import_module(qt_lib)
        HAVE_QT = True
        QT_LIB = qt_lib
        break
    except ImportError:
        pass


if HAVE_QT:
    locals().update(import_qt_namespace(QT_LIB))
    
    if 'PySide' not in QT_LIB:
        Signal = pyqtSignal  # for compatibility with PySide

    def make_qapp():
        """Create a QApplication object if one does not already exist.
        
        Returns
        -------
        app : QApplication
            The QApplication object.
        """
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app
