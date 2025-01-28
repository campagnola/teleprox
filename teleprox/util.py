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
        procs = c.Win32_Process(name=search)
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
