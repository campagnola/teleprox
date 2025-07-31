import logging, time
from .server import RPCServer
from . import log


logger = logging.getLogger(__name__)


class QtRPCServer(RPCServer):
    """RPCServer that executes actions in the main Qt GUI thread.

    This server may be used to create and manage QObjects, QWidgets, etc. It
    uses a separate thread to poll for RPC requests, which are then sent to the
    Qt event loop by signal. This allows the RPC actions to be executed
    in a Qt GUI thread without using a timer to poll the RPC socket. Responses
    are sent back to the poller thread by a secondary socket.
    
    QtRPCServer may be started in newly spawned processes using
    ``start_process(qt=True)``.
    
    Parameters
    ----------
    address : str
        ZMQ address to listen on. Default is ``'tcp://127.0.0.1:*'``.
        
        **Note:** binding RPCServer to a public IP address is a potential
        security hazard. See :class:`RPCServer`.
    quit_on_close : bool
        If True, then call `QApplication.quit()` when the server is closed. 
        
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
        server = QtRPCServer()
        
        # Start listening for requests in a background thread (this call
        # returns immediately).
        server.run_forever()
    """
    def __init__(self, address="tcp://127.0.0.1:*", quit_on_close=True):
        # only import Qt if requested
        from .qt_poll_thread import QtPollThread

        RPCServer.__init__(self, address)
        self.quit_on_close = quit_on_close        
        self.poll_thread = QtPollThread(self)
        
    def run_forever(self):
        name = ('%s.%s.%s' % (log.get_host_name(), log.get_process_name(), 
                              log.get_thread_name()))
        logger.info("RPC start server: %s@%s", name, self.address.decode())
        RPCServer.register_server(self)
        self.poll_thread.start()

    def process_action(self, action, opts, return_type, caller):
        # this method is called from the Qt main thread.
        if action == 'close':
            if self.quit_on_close:
                # Qt import deferred
                from teleprox import qt
                qt.QApplication.instance().quit()
            # can't stop poller thread here--that would prevent the return 
            # message being sent. In general it should be safe to leave this thread
            # running anyway.
            #self.poll_thread.stop()
        return RPCServer.process_action(self, action, opts, return_type, caller)

    def _final_close(self):
        # Block for a moment to allow the poller thread to flush any pending
        # messages. Ideally, we could let the poller thread keep the process
        # alive until it is done, but then we can end up with zombie processes..
        time.sleep(0.1)
