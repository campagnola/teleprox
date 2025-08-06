import logging
import time

from . import log
from .server import RPCServer

logger = logging.getLogger(__name__)


class QtRPCServer(RPCServer):
    """RPCServer that executes actions in the main Qt GUI thread. In this mode,
    messages are polled in a separate thread, but then sent to the Qt event
    loop by signal and processed there.

    This server may be used to create and manage QObjects, QWidgets, etc. It
    uses a separate thread to poll for RPC requests, which are then sent to the
    Qt event loop by signal. This allows the RPC actions to be executed
    in a Qt GUI thread without using a timer to poll the RPC socket. Responses
    are sent back to the poller thread by a secondary socket.
    
    QtRPCServer may be started in newly spawned processes using
    ``start_process(qt=True)``.
    
    Examples
    --------
    
    Spawning in a new process::
        
        # Create new process.
        proc = start_process(qt=True)
        
        # Display a widget in the new process.
        qtwidgets = proc._import('PyQt5.QtWidgets')
        w = qtwidgets.QWidget()
        w.show()
        
    Starting in an existing Qt application::
    
        # Create server.
        # Start listening for requests in a background thread (this call
        # returns immediately).
        server = QtRPCServer()
    """
    def __init__(self, address="tcp://127.0.0.1:*", quit_on_close=True, _run_thread=True):
        """Initialize a new QtRPCServer.

        Parameters
        ----------
        quit_on_close : bool
            If True, then call `QApplication.quit()` when the server is closed.

        Other parameters are the same as for `RPCServer`.
        """
        self.poll_thread = None
        self.quit_on_close = quit_on_close
        RPCServer.__init__(self, address, _run_thread=_run_thread)
        # only import Qt if requested
        from .qt_poll_thread import QtPollThread
        self.poll_thread = QtPollThread(self)

    def run_forever(self):
        while self.poll_thread is None:
            time.sleep(0.1)  # wait for poll thread to be created
        name = f'{log.get_host_name()}.{log.get_process_name()}.{log.get_thread_name()}'
        logger.info("RPC start server: %s@%s", name, self.address.decode())
        self.poll_thread.start()

    def process_action(self, action, opts, return_type, caller):
        # this method is called from the Qt main thread.
        if action == 'close':
            if self.quit_on_close:
                # Qt import deferred
                from teleprox import qt
                qt.QApplication.instance().quit()
            # can't stop poller thread here--that would prevent the return
            # message being sent. In general, it should be safe to leave this thread
            # running anyway.
            # self.poll_thread.stop()
        return RPCServer.process_action(self, action, opts, return_type, caller)

    def _final_close(self):
        # Block for a moment to allow the poller thread to flush any pending
        # messages. Ideally, we could let the poller thread keep the process
        # alive until it is done, but then we can end up with zombie processes...
        time.sleep(0.1)
