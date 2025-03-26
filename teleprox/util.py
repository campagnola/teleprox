import re
import socket
import subprocess
import os, sys, signal
import time

import teleprox


def kill_pid(pid):
    if sys.platform == 'win32':
        # on windows, SIGKILL is not available but we can use any signal other than CTRL_C_EVENT (0) or CTRL_BREAK_EVENT (1)
        # to kill a process
        sig = 2
    else: 
        sig = signal.SIGKILL

    os.kill(pid, sig)


def assert_pids_dead(pids):
    """Check that all given pids are dead.
    
    If not, kill them and raise an AssertionError.
    """
    killed = []
    for pid in pids:
        try:
            kill_pid(pid)
            killed.append(pid)
        except (OSError, ProcessLookupError):
            pass
    if killed:
        assert False, f"Process(es) {killed} should have exited before this point"


def assert_pid_dead(pid):
    assert_pids_dead([pid])


def find_procs(search):
    """Find all processes with the given search string in their command line.

    Return (pid, command) for each found process
    """
    if sys.platform == 'linux':
        import subprocess
        processes = subprocess.check_output(['ps', '-e', '-o', 'pid,command']).decode('utf-8').split('\n')
        found_procs = []
        for line in processes:
            pid, _, cmd = line.lstrip().partition(' ')
            if search in cmd:
                found_procs.append((int(pid), line))
        return found_procs
    elif sys.platform == 'win32':
        import wmi
        c = wmi.WMI()
        procs = c.query(f'select ProcessId,CommandLine from Win32_Process where CommandLine like "%{search}%"')
        return [(proc.ProcessId, proc.CommandLine) for proc in procs]
    else:
        raise NotImplementedError(f"find_procs not implemented for platform {sys.platform}")


def kill_procs(search, wait=5):
    """Kill all processes with the given search string in their command line.

    return (pid, command) for each killed process
    """
    procs = find_procs(teleprox.process.PROCESS_NAME_PREFIX)    
    if not procs:
        return []
    time.sleep(wait)  # wait a little longer for cleanup..
    procs = find_procs(teleprox.process.PROCESS_NAME_PREFIX)
    if not procs:
        return []
    for pid, line in procs:
        kill_pid(pid)
    return procs


class ProcessCleaner:
    """Context manager that collects a list of processes to kill when it exits.

    The expectation is that all processes are already dead when the context manager exits.
    This is important because killing the processes may prevent them reporting final errors.
    If not, then an exception will be raised saying which processes are still alive.
    If an exception is raised inside the context, then stray processes will be killed silently and the exception re-raised. 
    """
    def __init__(self):
        self.procs = []

    def add(self, proc_or_name, pid=None):
        if isinstance(proc_or_name, str):
            name = proc_or_name
            assert pid is not None
        else:
            proc = proc_or_name
            name = proc.name
            pid = proc.pid
        assert isinstance(pid, int)
        self.procs.append((name, pid))

    def __enter__(self):
        return self

    def __exit__(self, exc_typ, exc, tb):
        failures = []
        for name, pid in self.procs:
            try:
                assert_pid_dead(pid)
            except AssertionError:
                failures.append(name)
        # only report kill failures if we didn't get an exception in the main test
        if len(failures) > 0 and exc is None:
            raise AssertionError(f"Processes failed to exit: {failures}")
        else:
            return False  # process exception normally, if any


def check_tcp_port(host, port, timeout=1.0):
    """Attempt to determine whether a TCP port is open, closed, or filtered.

    On windows, closed ports will appear to be filtered (we can't tell the difference)
    _except_ when asking about the localhost.

    Returns
    -------
    state : str
        'open', 'closed', or 'timeout'
    """
    # quick check for open local ports on windows
    if host in ('localhost', '127.0.0.1') and sys.platform == 'win32':
        ports = netstat()
        for p in ports:
            if p.proto == 'tcp' and p.addr == '127.0.0.1' and p.port == port:
                return "open"
        return "closed"

    # on linux, we can use a socket to check the port        
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return "open"
        except socket.timeout:
            return "timeout"
        except (ConnectionRefusedError, OSError):
            return "closed"


class Port:
    def __init__(self, proto, addr, port, state, pid):
        self.proto = proto
        self.addr = addr
        self.port = port
        self.state = state
        self.pid = pid


def netstat():
    """Return a list describing all ports in use on the system (listening, established, etc).
    
    Each item in the list is a Port object with attributes proto, addr, port, state, pid.
    """
    
    if sys.platform == 'win32':
        output = subprocess.check_output(['netstat', '-ano']).decode()
        lines = output.split('\n')
        ports = []
        for line in lines:
            parts = re.split(r'\s+', line.strip())
            if len(parts) < 5 or parts[0] not in ('TCP', 'UDP'):
                continue

            proto = parts[0].lower()
            local_addr, local_port = parts[1].rsplit(':', 1)
            state = {'LISTENING': 'LISTEN'}.get(parts[3], parts[3])  # windows uses LISTENING instead of LISTEN
            pid = int(parts[4])
            ports.append(Port(proto, local_addr, int(local_port), state, pid))
    elif sys.platform == 'linux':
        output = subprocess.check_output(['netstat', '-tpln']).decode()
        lines = output.split('\n')
        ports = []
        for line in lines:
            parts = re.split(r'\s+', line.strip())
            if len(parts) < 7 or parts[0] not in ('tcp', 'udp'):
                continue

            proto = parts[0]
            local_addr, local_port = parts[3].rsplit(':', 1)
            state = parts[5]
            pid = int(parts[6].lsplit('/', 1)[0])
            ports.append(Port(proto, local_addr, int(local_port), state, pid))
    else:
        raise NotImplementedError(f"netstat not implemented for platform {sys.platform}")
    return ports
