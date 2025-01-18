import os, sys, signal


def kill_pid(pid):
    if sys.platform == 'win32':
        # on windows, SIGKILL is not available but we can use any signal other than CTRL_C_EVENT (0) or CTRL_BREAK_EVENT (1)
        # to kill a process
        sig = 2
    else: 
        sig = signal.SIGKILL

    os.kill(pid, sig)


def assert_pid_dead(pid):
    try:
        kill_pid(pid)
        assert False, f"Process {pid} should have exited before this point"
    except (OSError, ProcessLookupError):
        pass

