# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import sys
import json
import subprocess
import atexit
import zmq
import logging
import threading
import time

from .client import RPCClient
from .log import get_logger_address, LogSender


logger = logging.getLogger(__name__)

def start_process(name=None, address="tcp://127.0.0.1:*", qt=False, log_addr=None, 
                 log_level=None, executable=None, shell=False, conda_env=None, 
                 serializer='msgpack', start_local_server=False, daemon=False):
    """Utility for spawning and bootstrapping a new process with an :class:`RPCServer`.
    
    Automatically creates an :class:`RPCClient` that is connected to the remote 
    process (``spawner.client``).
    
    Parameters
    ----------
    name : str | None
        Optional process name that will be assigned to all remote log records.
    address : str
        ZMQ socket address that the new process's RPCServer will bind to.
        Default is ``'tcp://127.0.0.1:*'``.
        
        **Note:** binding RPCServer to a public IP address is a potential
        security hazard (see :class:`RPCServer`).
    qt : bool
        If True, then start a Qt application in the remote process, and use
        a :class:`QtRPCServer`.
    log_addr : str
        Optional log server address to which the new process will send its log
        records. This will also cause the new process's stdout and stderr to be
        captured and forwarded as log records.
    log_level : int
        Optional initial log level to assign to the root logger in the new
        process.
    executable : str | None
        Optional python executable to invoke. The default value is `sys.executable`.
    shell : bool
        If True, then the executable will be invoked via the shell.
    conda_env : str | None
        Optional name of a conda environment to activate before invoking the
        executable.
    serializer : str
        Serialization format to use for RPC communication. Default is 'msgpack'.
    start_local_server : bool
        If True, then start a local RPCServer in the current process. (See RPCClient)
        This allows sending objects by proxy to the child process (for example, callback
        functions). Default is False.
    daemon : bool
        If True, then the new process will be detached from the parent process, allowing
        it to run indefinitely in the background, even after the parent closes. 
        Default is False.

                
    Examples
    --------
    
    ::
    
        # start a new process
        proc = start_process()
        
        # ask the child process to do some work
        mod = proc._import('my.module')
        mod.do_work()
        
        # close the child process
        proc.close()
        proc.wait()
    """
    #logger.warning("Spawning process: %s %s %s", name, log_addr, log_level)
    assert qt in (True, False)
    assert isinstance(address, (str, bytes))
    assert name is None or isinstance(name, str)
    assert log_addr is None or isinstance(log_addr, (str, bytes)), "log_addr must be str or None; got %r" % log_addr
    if log_addr is None:
        log_addr = get_logger_address()
    assert log_level is None or isinstance(log_level, int)
    if log_level is None:
        log_level = logger.getEffectiveLevel()
    
    # temporary socket to allow the remote process to report its status.
    bootstrap_addr = 'tcp://127.0.0.1:*'
    bootstrap_sock = zmq.Context.instance().socket(zmq.PAIR)
    bootstrap_sock.setsockopt(zmq.RCVTIMEO, 10000)
    bootstrap_sock.bind(bootstrap_addr)
    bootstrap_sock.linger = 1000 # don't let socket deadlock when exiting
    bootstrap_addr = bootstrap_sock.last_endpoint
    
    # Spawn new process
    class_name = 'QtRPCServer' if qt else 'RPCServer'
    args = {'address': address}
    bootstrap_conf = dict(
        class_name=class_name, 
        args=args,
        bootstrap_addr=bootstrap_addr.decode(),
        loglevel=log_level,
        logaddr=log_addr.decode() if log_addr is not None else None,
        qt=qt,
        daemon=daemon,
    )
    
    if executable is None:
        if conda_env is None:
            executable = sys.executable
        else:
            executable = 'python'  # let env decide which python to use

    cmd = (executable, '-m', 'teleprox.bootstrap')

    if conda_env is not None:
        cmd = ('conda', 'run', '--no-capture-output', '-n', conda_env) + cmd
    
    if name is not None:
        cmd = cmd + (name,)

    if shell is True:
        cmd = ' '.join(cmd)

    popen_kwargs = {}
    if daemon is True and sys.platform == 'win32':
        popen_kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    if log_addr is not None:
        if daemon is True:
            raise ValueError("Cannot use daemon=True with log_addr (you must manually set up logging for daemon processes).")

        # start process with stdout/stderr piped
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                        stdout=subprocess.PIPE, shell=shell, **popen_kwargs)
        
        proc.stdin.write(json.dumps(bootstrap_conf).encode())
        proc.stdin.close()
        
        # create a logger for handling stdout/stderr and forwarding to log server
        # TODO id(proc) is not id(self), so this behavior is changed from before. is that okay?
        child_logger = logging.getLogger(__name__ + '.' + str(id(proc)))
        child_logger.propagate = False
        log_handler = LogSender(log_addr, child_logger)
        if log_level is not None:
            logger.level = log_level
        
        # create threads to poll stdout/stderr and generate / send log records
        stdout_poller = PipePoller(proc.stdout, logger.info, '[%s.stdout] '%name)
        stderr_poller = PipePoller(proc.stderr, logger.warning, '[%s.stderr] '%name)
        
    else:
        # don't intercept stdout/stderr
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, shell=shell, **popen_kwargs)
        proc.stdin.write(json.dumps(bootstrap_conf).encode())
        proc.stdin.close()
        
    logger.info("Spawned process: %d", proc.pid)
    if daemon is True and sys.platform != 'win32':
        proc.wait()  # prevent zombie
        proc = None  # prevent trying wait/kill/poll  (but maybe we can still do this on windows?)

    # Receive status information (especially the final RPC address)
    try:
        status = bootstrap_sock.recv_json()
    except zmq.error.Again:
        raise TimeoutError("Timed out waiting for response from spawned process.")
    logger.debug("recv status %s", status)
    bootstrap_sock.send(b'OK')
    bootstrap_sock.close()
    
    if 'address' in status:
        address = status['address']
        #: An RPCClient instance that is connected to the RPCServer in the remote process
        client = RPCClient(address.encode(), serializer=serializer, start_local_server=start_local_server)
    else:
        err = ''.join(status['error'])
        if proc is not None and proc.poll() is not None:
            proc.kill()
        raise RuntimeError(f"Error while spawning process:\n{err}")

    if daemon is True:
        return DaemonProcess(client, name, qt)
    else:
        if log_addr is None:
            return ChildProcess(proc, client, name, qt)
        else:
            return ChildProcess(proc, client, name, qt, child_logger, log_handler, stdout_poller, stderr_poller)


class DaemonProcess:
    def __init__(self, client, name, qt):
        self.client = client
        self.name = name
        self.qt = qt

    def stop(self):
        """Stop the spawned process by asking its RPC server to close.
        """
        logger.info(f"Close process: {self.client.address}")
        closed = self.client.close_server()
        assert closed is True, f"Server refused to close. (reply: {closed})"


class ChildProcess:
    def __init__(self, proc, client, name, qt, logger=None, log_handler=None, stdout_poller=None, stderr_poller=None):
        self.proc = proc
        self.client = client
        self.name = name
        self.qt = qt
        self.logger = logger
        self.log_handler = log_handler
        self.stdout_poller = stdout_poller
        self.stderr_poller = stderr_poller

        # Automatically shut down process when we exit. 
        atexit.register(self.stop)

    def wait(self, timeout=10):
        """Wait for the process to exit and return its return code.
        """
        # Using proc.wait() can deadlock; use communicate() instead.
        # see: https://docs.python.org/2/library/subprocess.html#subprocess.Popen.wait
        try:            
            self.proc.communicate()
        except (AttributeError, ValueError):
            # Python bug: http://bugs.python.org/issue30203
            # Calling communicate on process with closed i/o can generate
            # exceptions.
            pass
        
        start = time.time()
        sleep = 1e-3
        while True:
            rcode = self.proc.poll()
            if rcode is not None:
                return rcode
            if time.time() - start > timeout:
                raise TimeoutError("Timed out waiting on process exit for %s" % self.name)
            time.sleep(sleep)
            sleep = min(sleep*2, 100e-3)

    def kill(self):
        """Kill the spawned process immediately.
        """
        if self.proc.poll() is not None:
            return
        logger.info("Kill process: %d", self.proc.pid)
        self.proc.kill()

        self.wait()

    def stop(self):
        """Stop the spawned process by asking its RPC server to close.
        """
        if self.proc.poll() is not None:
            # process has already exited
            return
        logger.info(f"Close process: {self.client.address}")
        closed = self.client.close_server()
        assert closed is True, f"Server refused to close. (reply: {closed})"

        self.wait()

    def poll(self):
        """Return the spawned process's return code, or None if it has not
        exited yet.
        """
        return self.proc.poll()


class PipePoller(threading.Thread):
    
    def __init__(self, pipe, callback, prefix):
        threading.Thread.__init__(self, daemon=True)
        self.pipe = pipe
        self.callback = callback
        self.prefix = prefix
        self.start()
        
    def run(self):
        callback = self.callback
        prefix = self.prefix
        pipe = self.pipe
        while True:
            line = pipe.readline().decode()
            if line == '':
                break
            callback(prefix + line[:-1])
