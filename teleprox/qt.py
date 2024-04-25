
try:
    from PyQt5.QtCore import *
    from PyQt5.QtGui import *
    from PyQt5.QtWidgets import *
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


if HAVE_QT:
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
