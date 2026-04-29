# Tests for LogSender.handle() respecting registered filters.
import logging
import time

import pytest

from teleprox.log.remote import LogSender, LogServer
from teleprox.tests.util import RemoteLogRecorder


def _make_sender_and_recorder(name):
    """Return a (sender, recorder) pair for local testing."""
    recorder = RemoteLogRecorder(name)
    sender = LogSender(recorder.address)
    return sender, recorder


# ---------------------------------------------------------------------------
# Filter invocation
# ---------------------------------------------------------------------------

def test_filter_is_called_on_handle():
    """A filter added to LogSender.handle() is invoked for each record."""
    call_count = [0]

    class CountingFilter(logging.Filter):
        def filter(self, record):
            call_count[0] += 1
            return True

    sender, recorder = _make_sender_and_recorder('test_filter_called')
    sender.addFilter(CountingFilter())

    record = logging.makeLogRecord({'msg': 'hello', 'levelno': logging.INFO, 'levelname': 'INFO'})
    sender.handle(record)
    time.sleep(0.1)

    assert call_count[0] == 1
    recorder.stop()


def test_filter_blocking_prevents_delivery():
    """A filter returning False stops the record from reaching the log server."""
    sender, recorder = _make_sender_and_recorder('test_filter_block')
    sender.addFilter(logging.Filter('acq4'))  # only passes records named 'acq4' or children

    # This record should be blocked (wrong logger name).
    blocked = logging.makeLogRecord({'name': 'other', 'msg': 'blocked_msg',
                                     'levelno': logging.INFO, 'levelname': 'INFO'})
    # This record should pass.
    allowed = logging.makeLogRecord({'name': 'acq4', 'msg': 'allowed_msg',
                                     'levelno': logging.INFO, 'levelname': 'INFO'})
    sender.handle(blocked)
    sender.handle(allowed)
    time.sleep(0.3)

    assert recorder.find_message('allowed_msg') is not None
    assert recorder.find_message('blocked_msg') is None
    recorder.stop()


def test_filter_can_enrich_records():
    """A filter that adds an extra attribute transmits that attribute to the log server."""

    class EnrichingFilter(logging.Filter):
        def filter(self, record):
            record.custom_field = 'injected'
            return True

    sender, recorder = _make_sender_and_recorder('test_filter_enrich')
    sender.addFilter(EnrichingFilter())

    record = logging.makeLogRecord({'msg': 'enriched_msg',
                                    'levelno': logging.INFO, 'levelname': 'INFO'})
    sender.handle(record)
    time.sleep(0.3)

    rec = recorder.find_message('enriched_msg')
    assert rec is not None
    assert getattr(rec, 'custom_field', None) == 'injected'
    recorder.stop()


def test_multiple_filters_all_must_pass():
    """All filters must return True for the record to be delivered."""
    delivered = []

    class RecordingFilter(logging.Filter):
        def filter(self, record):
            delivered.append(record.msg)
            return True

    sender, recorder = _make_sender_and_recorder('test_multi_filter')
    sender.addFilter(logging.Filter('acq4'))   # blocks non-acq4 names
    sender.addFilter(RecordingFilter())         # records what passes the first filter

    sender.handle(logging.makeLogRecord(
        {'name': 'other', 'msg': 'should_not_reach_second_filter',
         'levelno': logging.INFO, 'levelname': 'INFO'}))
    sender.handle(logging.makeLogRecord(
        {'name': 'acq4', 'msg': 'should_reach_second_filter',
         'levelno': logging.INFO, 'levelname': 'INFO'}))
    time.sleep(0.1)

    assert 'should_not_reach_second_filter' not in delivered
    assert 'should_reach_second_filter' in delivered
    recorder.stop()
