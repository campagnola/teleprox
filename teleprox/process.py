# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import sys
import json
import subprocess
import atexit
from teleprox.util import kill_pid
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
        captured and forwarded as log records. Note: logging is not allowed in
        daemon processes because the parent is not guaranteed to stay alive longer
        than the daemon process.
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


    Notes
    -----

    Daemon processes are used when you expect the child process to continue running past the lifetime of the parent.
    There are multiple, OS-dependent practical effects of starting a daemon process:
    - Closing the terminal that started a parent process will usually cause child processes to be killed as well, unless they are
      started as a daemon (true on both linux and windows)
    - In some cases signals meant for the parent process (such as when you ctrl-c in a terminal) are also sent to children.
      Using a daemon ensures signals are not propagated to the child. (maybe only true on linux?)
    - Children can sometimes share open file handles with their parent (especially stdin/out/err). Starting as a daemon
      ensures that the child process file handles are totally independent of the parent (linux and windows).
    - Normal child processes must be wait()ed on after they die to collect their return code, otherwise they remain as a zombie process.
      Daemon processes do not have to be wait()ed on (linux only).
      
    """
    #logger.warning("Spawning process: %s %s %s", name, log_addr, log_level)
    assert daemon in (True, False)
    assert qt in (True, False)
    assert isinstance(address, (str, bytes))
    assert name is None or isinstance(name, str)
    assert log_addr is None or isinstance(log_addr, (str, bytes)), "log_addr must be str or None; got %r" % log_addr
    if log_addr is None and not daemon:
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
        
        stdio_logger = StdioLogSender(proc, name, log_addr, log_level)
        
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
        return DaemonProcess(client, name, qt, status['pid'])
    else:
        if log_addr is None:
            return ChildProcess(proc, client, name, qt)
        else:
            return ChildProcess(proc, client, name, qt, stdio_logger)


class DaemonProcess:
    def __init__(self, client, name, qt, pid):
        self.client = client
        self.name = name
        self.qt = qt
        self.pid = pid

    def stop(self):
        """Stop the spawned process by asking its RPC server to close.
        """
        logger.info(f"Close daemon process: {self.client.address}")
        closed = self.client.close_server()
        assert closed is True, f"Server refused to close. (reply: {closed})"

    def kill(self):
        """Kill the spawned process immediately."""
        try:
            logger.info("Kill daemon process: %d", self.pid)
            kill_pid(self.pid)
        except (OSError, ProcessLookupError):
            pass


class ChildProcess:
    def __init__(self, proc, client, name, qt, stdio_logger=None):
        self.proc = proc
        self.pid = proc.pid
        self.client = client
        self.name = name
        self.qt = qt
        self.logger = logger
        self.stdio_logger = stdio_logger

        # Automatically shut down process when we exit. 
        atexit.register(self.stop)

    def wait(self, timeout=10):
        """Wait for the process to exit and return its return code.
        """
        start = time.time()

        # Using proc.wait() can deadlock; use communicate() instead.
        # see: https://docs.python.org/2/library/subprocess.html#subprocess.Popen.wait
        try:
            # Turns out communicate() can deadlock too
            self.proc.communicate(timeout=timeout)
        except (AttributeError, ValueError):
            # Python bug: http://bugs.python.org/issue30203
            # Calling communicate on process with closed i/o can generate
            # exceptions.
            pass
        
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
        logger.info("Kill child process: %d", self.proc.pid)
        self.proc.kill()

        return self.wait()

    def stop(self):
        """Stop the spawned process by asking its RPC server to close.
        """
        if self.proc.poll() is not None:
            # process has already exited
            return
        logger.info(f"Close process: {self.client.address}")
        closed = self.client.close_server()
        assert closed is True, f"Server refused to close. (reply: {closed})"

        return self.wait()

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


class StdioLogSender:
    """Capture stdout/stderr from a process and forward to a log server.
    """
    def __init__(self, proc, name, log_addr, log_level=None):
        self.proc = proc
        self.log_addr = log_addr

        # create a logger for handling stdout/stderr and forwarding to log server
        # TODO id(proc) is not id(self), so this behavior is changed from before. is that okay?
        self.child_logger = logging.getLogger(__name__ + '.' + str(id(proc)))
        self.child_logger.propagate = False
        self.log_handler = LogSender(log_addr, self.child_logger)
        if log_level is not None:
            self.child_logger.level = log_level
        
        # create threads to poll stdout/stderr and generate / send log records
        self.stdout_poller = PipePoller(proc.stdout, self.child_logger.info, '[%s.stdout] '%name)
        self.stderr_poller = PipePoller(proc.stderr, self.child_logger.warning, '[%s.stderr] '%name)
