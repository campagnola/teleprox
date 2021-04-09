import pytest
import teleprox


qt_available = True
qt_reason = None

try:
    import pyqtgraph
    
    p = teleprox.ProcessSpawner()
    qt = p.client._import('pyqtgraph.Qt')
    try:
        app = qt.QtGui.QApplication([], _timeout=1)
    except TimeoutError:
        if p.poll() is not None:
            # subprocess exited; probably means we can't use Qt from this environment
            qt_available = False
            qt_reason = "Qt cannot be used from this environment"

except ImportError:
    qt_available = False
    qt_reason = "Could not import pyqtgraph"



requires_qt = pytest.mark.skipif(not qt_available, reason=qt_reason)
