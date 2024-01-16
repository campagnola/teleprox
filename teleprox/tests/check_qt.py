import pytest
import teleprox


qt_available = True
qt_reason = ""
p_started = False

try:    
    p = teleprox.ProcessSpawner('tests.check_qt')
    p_started = True
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
    if p_started:
        p.stop()


requires_qt = pytest.mark.skipif(not qt_available, reason=qt_reason)
