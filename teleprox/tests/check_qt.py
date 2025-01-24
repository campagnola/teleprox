import pytest
import teleprox


qt_available = True
qt_reason = ""

try:    
    p = teleprox.start_process()
    qt = p.client._import('teleprox.qt')
    try:
        app = qt.QApplication([], _timeout=1)
    except TimeoutError:
        if p.poll() is not None:
            # subprocess exited; probably means we can't use Qt from this environment
            qt_available = False
            qt_reason = "Qt cannot be used from this environment"

except ImportError as exc:
    qt_available = False
    qt_reason = str(exc)

requires_qt = pytest.mark.skipif(not qt_available, reason=qt_reason)
