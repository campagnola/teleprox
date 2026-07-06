#!/usr/bin/env python
"""Reproduce teleprox issue #40: framing corruption from two threads on one zmq socket.

This replicates what ACQ4 does wrong in ``acq4/__main__.py``::

    teleprox_debug_server = RPCServer(addr)   # run_thread defaults True -> starts run_forever thread #1
    teleprox_debug_server._run_in_thread()    # starts run_forever thread #2 on the SAME socket

``RPCServer.__init__`` already starts a ``run_forever`` thread when ``run_thread=True``
(the default), so calling ``_run_in_thread()`` again leaves TWO daemon threads both
calling ``recv_multipart()`` on the same ROUTER socket. libzmq sockets are not
thread-safe, so the two readers steal frames from each other: one ``run_forever`` loop
receives a partial multipart message and raises ``ValueError: Invalid RPC message:
expected 6 parts, got N`` (killing that server thread -> "goes deaf"), and intermittently
the concurrent access trips the fatal libzmq ``Assertion failed: false (src/object.cpp:142)``
SIGABRT instead.

The server runs in a subprocess (as it does inside ACQ4) so a potential SIGABRT does not
take down the harness, and we can watch its stderr for the framing error.

Usage::

    python repro_issue_40.py            # buggy: double run_forever -> corruption within seconds
    python repro_issue_40.py --fixed    # single run_forever -> no corruption (control)
"""

import argparse
import re
import subprocess
import sys
import threading
import time


# ---------------------------------------------------------------------------
# Server subprocess: stands in for the ACQ4 process running `--teleprox`.
# ---------------------------------------------------------------------------
SERVER_SRC = r'''
import sys, time
from teleprox import RPCServer

buggy = "--fixed" not in sys.argv

# RPCServer(run_thread=True) already starts one run_forever thread inside __init__.
server = RPCServer("tcp://127.0.0.1:*")
if buggy:
    # This is exactly what acq4/__main__.py does: start a SECOND run_forever
    # thread on the same socket. Two threads now recv_multipart() concurrently.
    server._run_in_thread()

# Announce the address on stdout so the parent can connect.
print("ADDR " + server.address.decode(), flush=True)

# Sit alive like the ACQ4 process would.
while True:
    time.sleep(0.5)
'''


def run_server():
    """Spawn the stand-in ACQ4 server subprocess and return its Popen handle."""
    args = [sys.executable, "-c", SERVER_SRC]
    if "--fixed" in sys.argv:
        args.append("--fixed")
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def worker(addr, stop, stats, idx):
    """Hammer the server like the MCP client does: import a module + call it.

    Each iteration sends two requests (import + call), matching the
    interleaving of import/call/ping frames seen in the ticket.
    """
    from teleprox import RPCClient

    client = RPCClient.get_client(addr)          # per-thread client
    mod = client._import("os")                    # any importable module
    n = 0
    while not stop.is_set():
        try:
            mod.getpid()                          # any cheap remote call
            n += 1
        except Exception as exc:
            stats[idx] = (n, repr(exc))
            return
    stats[idx] = (n, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed", action="store_true",
                        help="start only one run_forever thread (control: no corruption)")
    parser.add_argument("--threads", type=int, default=4, help="number of client threads")
    parser.add_argument("--duration", type=float, default=20.0, help="seconds to hammer")
    ns = parser.parse_args()

    proc = run_server()

    # Wait for the server to announce its address.
    addr = None
    for _ in range(200):
        line = proc.stdout.readline()
        if line.startswith("ADDR "):
            addr = line[5:].strip()
            break
        if proc.poll() is not None:
            break
    if addr is None:
        print("server failed to start; stderr:\n" + proc.stderr.read())
        proc.kill()
        return 2

    mode = "fixed (single run_forever)" if ns.fixed else "buggy (double run_forever)"
    print(f"server pid={proc.pid} listening at {addr}")
    print(f"mode={mode}  threads={ns.threads}  duration={ns.duration}s")

    # Collect server stderr in the background so we can scan it for the framing error.
    server_err = []
    err_thread = threading.Thread(
        target=lambda: server_err.extend(iter(proc.stderr.readline, "")), daemon=True
    )
    err_thread.start()

    nthreads = ns.threads
    duration = ns.duration
    stop = threading.Event()
    stats = {}
    threads = [
        threading.Thread(target=worker, args=(addr, stop, stats, i))
        for i in range(nthreads)
    ]
    for t in threads:
        t.start()

    # Watch for the server to die, emit the framing error, or any client worker to
    # blow up on corrupted frames, up to `duration`.
    start = time.time()
    verdict = None
    while time.time() - start < duration:
        time.sleep(0.25)
        code = proc.poll()
        if code is not None:
            if code < 0:
                verdict = f"server process died with signal {-code} (SIGABRT=6 => libzmq object.cpp:142)"
            else:
                verdict = f"server process exited with code {code}"
            break
        joined = "".join(server_err)
        if "Invalid RPC message" in joined:
            verdict = "server logged 'Invalid RPC message' (server-side multipart framing corrupted)"
            break
        # Client-side face of the same defect: a worker got a corrupted/merged reply
        # (msgpack ExtraData / unpack error) or timed out because a reply was stolen.
        errored = [(i, e) for i, (_, e) in stats.items() if e]
        if errored:
            i, e = errored[0]
            verdict = f"client thread {i} hit corrupted transport: {e}"
            break

    stop.set()
    for t in threads:
        t.join(timeout=2)

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n--- client results ---")
    for i in range(nthreads):
        calls, exc = stats.get(i, (0, "never finished"))
        print(f"  thread {i}: {calls} calls, error={exc}")

    joined = "".join(server_err)
    framing = re.findall(r"Invalid RPC message: expected 6 parts, got \d+.*", joined)
    print("\n--- server stderr (framing errors) ---")
    if framing:
        for line in framing[:10]:
            print("  " + line)
    else:
        print("  (none)")

    print("\n--- verdict ---")
    if verdict:
        print("  REPRODUCED: " + verdict)
        return 1
    print("  no corruption observed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
