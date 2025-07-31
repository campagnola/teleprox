"""
Every once in a while, we encounter a problem that we can't solve. This forces us to 
write workarounds into the code that we would ideally like to remove later on.

This file documents MWEs for failure modes so we can track them over time.
"""
import time
import teleprox


def exit_deadlock_qt6():
    """This is a deadlock on process exit that can occur when using PyQt6 and zmq.
    https://bugreports.qt.io/browse/QTBUG-133240


    Easy check to reproduce:
        $ python -c "import zmq; import PyQt6.QtWidgets; app = PyQt6.QtWidgets.QApplication([])"    
    ..which hangs immediately.

    The deadlock can be avoided by importing Qt before zmq, but that's not always possible.

    As an extra kicker, _sometimes_ calling proc.communicate(timeout=1) will deadlock the parent as well.
    This means there is a bug that makes communicate() unreliable for stopping all processes.
    """
    proc = teleprox.start_process(name='exit_deadlock_qt6')
    app = proc.client._import('PyQt6.QtWidgets.QApplication')([])
    proc.client.close_server()
    time.sleep(0.5)
    if proc.poll() is None:
        proc.kill()
        raise Exception("Process did not exit")


