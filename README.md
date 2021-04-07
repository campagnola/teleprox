Teleprox: simple python object proxies over TCP
===============================================

No declarations required; just access remote objects as if they are local.

Example:

    from teleprox import ProcessSpawner

    # start a new process
    proc = ProcessSpawner()
    
    # import os in the remote process
    remote_os = proc.cli._import('os')

    # call os.getpid() in the remote process
    pid = remote_os.getpid()
    
    proc.stop()

Teleprox was originally developed as pyacq.core.rpc by the French National Center for Scientific Research (CNRS).


Requires
========

- python 3
- pyzmq
- msgpack





