# Tests for QtLogHandler: filter behavior in handle().
#
# QtLogHandler overrides logging.Handler.handle(), so it must apply the handler's
# filters itself. Filters both drop records and enrich them, and a viewer reads the
# attributes an enriching filter attaches.
import logging

from teleprox.log.logviewer.viewer import QtLogHandler


def _record(name='test', msg='hello'):
    return logging.makeLogRecord(
        {'name': name, 'msg': msg, 'levelno': logging.INFO, 'levelname': 'INFO'}
    )


def test_filter_is_called_on_handle(qapp):
    """A filter added to QtLogHandler.handle() is invoked for each record."""
    call_count = [0]

    class CountingFilter(logging.Filter):
        def filter(self, record):
            call_count[0] += 1
            return True

    handler = QtLogHandler()
    handler.addFilter(CountingFilter())

    handler.handle(_record())

    assert call_count[0] == 1


def test_filter_blocking_prevents_delivery(qapp):
    """A filter returning False stops the record from being emitted as a signal."""
    delivered = []
    handler = QtLogHandler()
    handler.new_record.connect(delivered.append)
    handler.addFilter(logging.Filter('acq4'))  # only passes 'acq4' or its children

    handler.handle(_record(name='other', msg='blocked_msg'))
    handler.handle(_record(name='acq4', msg='allowed_msg'))

    assert [r.msg for r in delivered] == ['allowed_msg']


def test_filter_can_enrich_records(qapp):
    """A filter that adds an extra attribute delivers that attribute to the viewer."""

    class EnrichingFilter(logging.Filter):
        def filter(self, record):
            record.custom_field = 'injected'
            return True

    delivered = []
    handler = QtLogHandler()
    handler.new_record.connect(delivered.append)
    handler.addFilter(EnrichingFilter())

    handler.handle(_record(msg='enriched_msg'))

    assert len(delivered) == 1
    assert getattr(delivered[0], 'custom_field', None) == 'injected'


def test_multiple_filters_all_must_pass(qapp):
    """All filters must return True for the record to be delivered."""
    seen_by_second = []

    class RecordingFilter(logging.Filter):
        def filter(self, record):
            seen_by_second.append(record.msg)
            return True

    handler = QtLogHandler()
    handler.addFilter(logging.Filter('acq4'))  # blocks non-acq4 names
    handler.addFilter(RecordingFilter())       # records what passes the first filter

    handler.handle(_record(name='other', msg='should_not_reach_second_filter'))
    handler.handle(_record(name='acq4', msg='should_reach_second_filter'))

    assert seen_by_second == ['should_reach_second_filter']


def test_handle_reports_whether_the_record_was_emitted(qapp):
    """handle() returns whether the record passed the filters, as Handler.handle does."""
    handler = QtLogHandler()
    handler.addFilter(logging.Filter('acq4'))

    assert handler.handle(_record(name='acq4')) is True
    assert handler.handle(_record(name='other')) is False
