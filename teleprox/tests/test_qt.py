import pytest
import teleprox
from teleprox.client import RemoteCallException
from teleprox.util import ProcessCleaner
from teleprox.tests.check_qt import requires_qt


def test_qt_unimportable():
    with ProcessCleaner() as cleaner:
        child = teleprox.start_process('test_qt_import_child')
        cleaner.add(child.name, child.pid)
        rqt = child.client._import('teleprox.qt_util')
        assert rqt.check_qt_imported() is None

        # sabotage qt import on child
        rqt.qt_lib_order = ['PieQt5', 'SyPide2']
        with pytest.raises(RemoteCallException):
            rqt.get_qt_module()
        assert rqt.have_qt() is False

        child.stop()

@requires_qt
def test_qt_import():
    # test that qt is not imported until requested
    with ProcessCleaner() as cleaner:
        child = teleprox.start_process('test_qt_import_child')
        cleaner.add(child.name, child.pid)
        rqt = child.client._import('teleprox.qt_util')
        assert rqt.check_qt_imported() is None

        qt_lib = rqt.get_qt_module().__name__._get_value()

        child.stop()

    # check manual import
    with ProcessCleaner() as cleaner:
        child = teleprox.start_process('test_qt_import_child')
        cleaner.add(child.name, child.pid)
        rqt = child.client._import('teleprox.qt_util')
        assert rqt.check_qt_imported() is None
        child.client._import(qt_lib)
        assert rqt.get_qt_module().__name__._get_value() == qt_lib
        child.stop()
