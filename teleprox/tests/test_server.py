import logging
import time
import numpy as np
import pytest
import teleprox
from teleprox.util import ProcessCleaner


def test_published_objects():
    with ProcessCleaner() as cleaner:
        proc = teleprox.start_process(name='test_published_objects')
        cleaner.add('proc', proc.pid)

        proxy_to_server = proc.client['self']
        assert proxy_to_server.address == proc.client.address

        proc.client['x'] = 1
        assert proc.client['x'] == 1

        ros = proc.client._import('os')
        proc.client['os'] = ros
        assert proc.client['os'].getpid() == proc.pid

        proc.stop()
