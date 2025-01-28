import pytest
import teleprox


qt_available = True
qt_reason = ""

p = teleprox.start_process('check_qt_process')
try:    
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

finally:
    p.client.close_server()
    for i in range(10):
        if p.poll() is not None:
            break
    if p.poll() is None:
        # indicates presence of deadlock; see failure_modes.py exit_deadlock_qt6
        qt_available = False
        qt_reason = "Known exit deadlock in Qt would break tests"
        p.kill()

requires_qt = pytest.mark.skipif(not qt_available, reason=qt_reason)
