import teleprox.process
from teleprox.util import kill_procs


def test_stray_children():
    procs = kill_procs(teleprox.process.PROCESS_NAME_PREFIX)
    if procs:
        msg = f'\n------------- Found {len(procs)} stray teleprox processes: ----------------\n'
        for pid, line in procs:
            msg += f"{pid} {line}\n"
        print(msg)
        raise AssertionError("Stray teleprox processes found and killed (see above)")
