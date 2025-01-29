import pytest
import teleprox
from teleprox.util import ProcessCleaner


def test_proxy_getattr_setattr():
    with ProcessCleaner() as cleaner:
        proc = teleprox.start_process(name='test_proxy_getattr_setattr')
        cleaner.add(proc)

        ros = proc.client._import('os')
        with pytest.raises(teleprox.RemoteCallException):
            ros.nonexistent['x']

        with pytest.raises(teleprox.RemoteCallException):
            ros.nonexistent['x'] = 1

        proc.stop()