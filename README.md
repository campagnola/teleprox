# Teleprox: simple python object proxies over TCP

[![Tests](https://github.com/campagnola/teleprox/actions/workflows/test.yml/badge.svg)](https://github.com/campagnola/teleprox/actions)
[![PyPI version](https://badge.fury.io/py/teleprox.svg)](https://badge.fury.io/py/teleprox)

No declarations required; just access remote objects as if they are local.

Requires
--------

- python 3
- pyzmq
- msgpack
- numpy (optional; required only for SharedNDArray)


Examples
--------

```python
from teleprox import start_process

# start a new process
proc = start_process()

# import os in the remote process
remote_os = proc.client._import('os')

# call os.getpid() in the remote process
pid = remote_os.getpid()

# or, call getpid asynchronously and wait for the result:
request = remote_os.getpid(_sync='async')
while not request.hasResult():
    time.sleep(0.01)
pid = request.result()

# write to sys.stdout in the remote process, and ignore the return value
remote_sys = proc.client._import('sys')
remote_sys.stdout.write('hello', _sync='off')

proc.stop()
```

Teleprox was originally developed as pyacq.core.rpc by the French National Center for Scientific Research (CNRS).






