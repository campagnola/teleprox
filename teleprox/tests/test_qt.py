import pytest
import teleprox
from teleprox.client import RemoteCallException
from teleprox.util import ProcessCleaner
from teleprox.tests.check_qt import requires_qt


def test_qt_unimportable():
    with ProcessCleaner(raise_exc=False) as cleaner:
        child = teleprox.start_process('test_qt_import_child')
        cleaner.add(child.name, child.pid)
        rqt = child.client._import('teleprox.qt_util')
        assert rqt.check_qt_imported() is None

        # sabotage qt import on child
        rqt.qt_lib_order = ['PieQt5', 'SyPide2']
        with pytest.raises(RemoteCallException):
            rqt.import_qt()


@requires_qt
def test_qt_import():
    # test that qt is not imported until requested
    with ProcessCleaner(raise_exc=False) as cleaner:
        child = teleprox.start_process('test_qt_import_child')
        cleaner.add(child.name, child.pid)
        rqt = child.client._import('teleprox.qt_util')
        assert rqt.check_qt_imported() is None

        rqt.import_qt()
        # keep track of which qt lib we have
        qt_lib = rqt.QT_LIB._get_value()

    # check that if we import Qt on our own, teleprox.qt won't
    # override that decision
    with ProcessCleaner(raise_exc=False) as cleaner:
        child = teleprox.start_process('test_qt_import_child')
        cleaner.add(child.name, child.pid)
        rqt = child.client._import('teleprox.qt_util')
        assert rqt.check_qt_imported() is None

        child.client._import(qt_lib+'.QtCore')
        assert rqt.check_qt_imported() == True
        assert rqt.QT_LIB._get_value() == qt_lib

        rqt.import_qt()
        assert rqt.QT_LIB._get_value() == qt_lib

    # check that we can explicitly import a qt lib
    with ProcessCleaner(raise_exc=False) as cleaner:
        child = teleprox.start_process('test_qt_import_child')
        cleaner.add(child.name, child.pid)
        rqt = child.client._import('teleprox.qt_util')
        assert rqt.check_qt_imported() is None

        qt_ns = rqt.import_qt(qt_lib)
        assert rqt.QT_LIB._get_value() == qt_lib

        wrong_qt_lib = 'PyQt5' if qt_lib != 'PyQt5' else 'PyQt6'
        with pytest.raises(RemoteCallException):
            rqt.import_qt(wrong_qt_lib)
        
        app = child.client._import('teleprox.qt').QApplication([])
        