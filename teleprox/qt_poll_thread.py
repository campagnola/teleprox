import zmq
from pyqtgraph.Qt import QtCore
from .server import RPCServer


class QtPollThread(QtCore.QThread):
    """Thread that polls an RPCServer socket and sends incoming messages to the
    server by Qt signal.
    
    This allows the RPC actions to be executed in a Qt GUI thread without using
    a timer to poll the RPC socket. Responses are sent back to the poller
    thread by a secondary socket.
    """
    new_request = QtCore.Signal(object, object)  # client, msg
    
    def __init__(self, server):
        # Note: QThread behaves like threading.Thread(daemon=True); a running
        # QThread will not prevent the process from exiting.
        QtCore.QThread.__init__(self)
        self.server = server
        
        # Steal RPC socket from the server; it should not be touched outside the
        # polling thread.
        self.rpc_socket = server._socket
        
        # Create a socket for the Qt thread to send results back to the poller
        # thread
        return_addr = 'inproc://%x' % id(self)
        context = zmq.Context.instance()
        self.return_socket = context.socket(zmq.PAIR)
        self.return_socket.linger = 1000  # don't let socket deadlock when exiting
        self.return_socket.bind(return_addr)
        
        server._socket = context.socket(zmq.PAIR)
        server._socket.linger = 1000  # don't let socket deadlock when exiting
        server._socket.connect(return_addr)

        self.new_request.connect(server._process_one)
        
    def run(self):
        poller = zmq.Poller()
        poller.register(self.rpc_socket, zmq.POLLIN)
        poller.register(self.return_socket, zmq.POLLIN)
        
        while True:
            # Note: poller needs to continue running until server has sent 
            # its final response (which can be after the server claims to be
            # no longer running).
            socks = dict(poller.poll(timeout=100))
            
            if self.return_socket in socks:
                name, data = self.return_socket.recv_multipart()
                #logger.debug("poller return %s %s", name, data)
                if name == 'STOP':
                    break
                self.rpc_socket.send_multipart([name, data])
                
            if self.rpc_socket in socks:
                name, msg = RPCServer._read_one(self.rpc_socket)
                #logger.debug("poller recv %s %s", name, msg)
                self.new_request.emit(name, msg)

        #logger.error("poller exit.")
        
    def stop(self):
        """Ask the poller thread to stop.
        
        This method may only be called from the Qt main thread.
        """
        self.server._socket.send_multipart([b'STOP', b''])
