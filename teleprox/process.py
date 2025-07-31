# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import sys
import json
import subprocess
import atexit
from teleprox.log.remote import get_process_name, set_thread_name
from teleprox.log.stdio import StdioLogSender
from teleprox.util import kill_pid
import zmq
import logging
import threading
import time

from .client import RPCClient
from .log import get_logger_address, LogSender


logger = logging.getLogger(__name__)


# used to make all (grand)children of this process easier to identify
# (e.g. so we know if anything is left alive after running tests)
PROCESS_NAME_PREFIX = ''


def start_process(name=None, address="tcp://127.0.0.1:*", qt=False, log_addr=None, 
                 log_level=None, log_stdio=None, executable=None, shell=False, conda_env=None, 
                 serializer='msgpack', start_local_server=False, daemon=False,
                 stdin=None, stdout=None, stderr=None):
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
        records. For non-daemon processes, this will also cause log_stdio to be
        enabled by default.
    log_level : int
        Optional initial log level to assign to the root logger in the new
        process.
    log_stdio : bool | None
        If True, then the new process's stdout and stderr will be captured and
        forwarded as log records. By default, this is True if log_addr is set.
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
    stdin, stdout, stderr : 
        See Popen documentation for details. Not compatible with log_addr.
                
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
    assert daemon in (True, False), f"daemon must be bool; got {repr(daemon)}"
    assert qt in (True, False), f"qt must be bool; got {repr(qt)}"
    assert isinstance(address, (str, bytes)), f"address must be str or bytes; got {repr(address)}"
    assert name is None or isinstance(name, str), f"name must be str or None; got {repr(name)}"
    assert log_addr is None or isinstance(log_addr, (str, bytes)), f"log_addr must be str or None; got {repr(log_addr)}"
    if log_addr is None and not daemon:
        log_addr = get_logger_address()
    assert log_level is None or isinstance(log_level, (int, str)), f"log_level must be int, str, or None; got {repr(log_level)}"
    if log_level is None:
        log_level = logger.getEffectiveLevel()
    elif isinstance(log_level, str):
        log_level = getattr(logging, log_level.upper())
    assert log_stdio in (True, False, None), f'log_stdio must be True, False, or None; got {repr(log_stdio)}'
    if log_stdio is True:
        assert stdout is None and stderr is None, "Cannot use log_stdio with stdout/stderr."
    # If we have a log server and stdio/stderr have not been explicitly set, then
    # turn on stdio logging by default.
    if log_stdio is None and stdout is None and stderr is None and daemon is False:
        log_stdio = log_addr is not None
    if name is None:
        name = get_process_name() + '_child'
    name = PROCESS_NAME_PREFIX + name
    
    # temporary socket to allow the remote process to report its status.
    bootstrap_addr = 'tcp://127.0.0.1:*'
    bootstrap_sock = zmq.Context.instance().socket(zmq.PAIR)
    bootstrap_sock.setsockopt(zmq.RCVTIMEO, 10000)
    bootstrap_sock.bind(bootstrap_addr)
    bootstrap_sock.linger = 1000 # don't let socket deadlock when exiting
    bootstrap_addr = bootstrap_sock.last_endpoint
    
    # Spawn new process
    bootstrap_args = []
    if name is not None:
        bootstrap_args = [name] + bootstrap_args
    if qt is True:
        bootstrap_args.append('--qt')
    if daemon is True:
        bootstrap_args.append('--daemon')
    if log_addr is not None:
        bootstrap_args.extend([
            f'--logaddr={log_addr.decode()}',
            f'--loglevel={log_level}',
        ])
    bootstrap_args.extend([
        f'--listen_addr={address}',
        f'--bootstrap_addr={bootstrap_addr.decode()}',
    ])
    if PROCESS_NAME_PREFIX not in ('', None):
        bootstrap_args.append(
            f'--child_name_prefix={PROCESS_NAME_PREFIX}'
        )
    
    if executable is None:
        if conda_env is None:
            executable = sys.executable
        else:
            executable = 'python'  # let env decide which python to use

    # note: the -u flag is used to force unbuffered stdout/stderr so that all
    # output is captured in real time.
    cmd = (executable, '-u', '-m', 'teleprox.bootstrap') + tuple(bootstrap_args)

    if conda_env is not None:
        cmd = ('conda', 'run', '--no-capture-output', '-n', conda_env) + cmd
    
    if shell is True:
        cmd = ' '.join(cmd)

    popen_kwargs = {
        'stdin': stdin or subprocess.DEVNULL,
        'stdout': stdout,
        'stderr': stderr,
        'shell': shell,
    }
    if daemon is True:
        # daemom processes have no stdio
        assert log_stdio is not True, "Cannot use log_stdio with daemon." 
        assert stdin is None and stdout is None and stderr is None, "Cannot use stdin/stdout/stderr with daemon."
        popen_kwargs['stdin'] = subprocess.DEVNULL
        popen_kwargs['stdout'] = subprocess.DEVNULL
        popen_kwargs['stderr'] = subprocess.DEVNULL
        # use DETACH_PROCESS to prevent the child from being killed when the parent is killed
        # use CREATE_NEW_PROCESS_GROUP to prevent the child from receiving signals from the parent
        if sys.platform == 'win32':
            popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP #subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        if log_stdio is True:
            popen_kwargs['stdout'] = subprocess.PIPE
            popen_kwargs['stderr'] = subprocess.PIPE

    # Start the new process
    proc = subprocess.Popen(cmd, **popen_kwargs)

    # set up stdout/stderr logging if requested
    if log_stdio is True:
        stdio_logger = StdioLogSender(proc, name, log_addr, log_level)
    else:
        stdio_logger = None
        
    logger.info(f'Spawned process "{name}" with pid {proc.pid}')
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
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f'Timed out waiting for process "{self.name}" to exit') from exc
        
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

    def stop(self, timeout=10):
        """Stop the spawned process by asking its RPC server to close.
        """
        if self.proc.poll() is not None:
            # process has already exited
            return
        logger.info(f"Close process: {self.client.address}")
        closed = self.client.close_server(timeout=timeout)
        assert closed is True, f"Server refused to close. (reply: {closed})"

        return self.wait(timeout)

    def poll(self):
        """Return the spawned process's return code, or None if it has not
        exited yet.
        """
        return self.proc.poll()
