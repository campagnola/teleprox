import signal
import sys
import os
import time
import pytest
from teleprox import start_process


@pytest.mark.skipif(sys.platform=='win32', reason='posix-specific test skipped on windows')
def test_daemon_posix():
    child1 = start_process()
    daemon = child1.client._import('teleprox').start_process(daemon=True)

    address = daemon.client.address._get_value()

    pid = daemon.client._import('os').getpid()

    child1.kill()

    # test second connection
    child2 = start_process()
    client2 = child2.client._import('teleprox').RPCClient(address=address)
    assert pid == client2._import('os').getpid()

    # test closing nicely
    client2.close_server()
    time.sleep(0.3)  # wait for server to close

    # assert that daemon pid is gone
    try:
        os.kill(pid, signal.SIGKILL)
        assert False, f"Daemon process {pid} should have exited before this point"
    except ProcessLookupError:
        assert True
