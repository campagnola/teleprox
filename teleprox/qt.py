from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *


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
