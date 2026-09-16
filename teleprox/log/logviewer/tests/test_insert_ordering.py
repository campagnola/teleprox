# Records are placed in timestamp order as they arrive, rather than the model
# being re-sorted per record. Re-sorting per record made ingest quadratic: at a
# few thousand records the Qt thread spent longer sorting than the interval
# between records, which is enough to stall a process that logs at any volume,
# since records are delivered inline on that thread.

import logging

from teleprox import qt
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox.log.logviewer.viewer import LogViewer


def make_record(msg, created, level=logging.INFO):
    rec = logging.LogRecord('test.insert.ordering', level, __file__, 0, msg, (), None)
    rec.created = created
    return rec


def model_timestamps(model):
    return [
        model.item(row, 0).data(ItemDataRole.NUMERIC_TIMESTAMP)
        for row in range(model.rowCount())
    ]


def model_messages(model):
    return [model.item(row, LogColumns.MESSAGE).text() for row in range(model.rowCount())]


class TestInsertOrdering:
    """Ordered insertion, and the absence of per-record re-sorting."""

    def test_out_of_order_records_land_in_order_in_the_source_model(self, qapp):
        """The source model itself is ordered, not just the view on top of it."""
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0

        # Delivery order is deliberately scrambled, including a record that
        # belongs at the very front and one that belongs in the middle.
        for delay in (30, 10, 50, 0, 20, 40):
            viewer.handler.handle(make_record(f"at +{delay}s", base + delay))
        qapp.processEvents()

        assert model_messages(viewer.model) == [
            "at +0s", "at +10s", "at +20s", "at +30s", "at +40s", "at +50s"
        ]
        assert model_timestamps(viewer.model) == [base + d for d in (0, 10, 20, 30, 40, 50)]

    def test_records_sharing_a_timestamp_keep_arrival_order(self, qapp):
        """Equal timestamps must not reorder: the bisect inserts after equals."""
        viewer = LogViewer(logger=None, initial_filters=[])
        for i in range(5):
            viewer.handler.handle(make_record(f"same time {i}", 1_000_000_000.0))
        qapp.processEvents()

        assert model_messages(viewer.model) == [f"same time {i}" for i in range(5)]

    def test_arriving_record_does_not_resort_the_view(self, qapp):
        """The regression guard: no sort is triggered per record."""
        viewer = LogViewer(logger=None, initial_filters=['level: info'])
        base = 1_000_000_000.0

        sorts = []
        viewer.ensure_chronological_sorting = lambda: sorts.append(1)

        # Deliver in order and out of order; neither may provoke a sort.
        for i in range(50):
            viewer.handler.handle(make_record(f"in order {i}", base + i))
        for i in range(50):
            viewer.handler.handle(make_record(f"late {i}", base + 0.5))
        qapp.processEvents()

        assert sorts == [], f"record arrival triggered {len(sorts)} re-sorts"
        assert viewer.model.rowCount() == 100
        assert model_timestamps(viewer.model) == sorted(model_timestamps(viewer.model))

    def test_a_late_record_lands_between_its_neighbours(self, qapp):
        """A record that arrives out of order goes to its place, not the end."""
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0
        for i in range(10):
            viewer.handler.handle(make_record(f"msg {i}", base + i))
        qapp.processEvents()

        viewer.handler.handle(make_record("late msg", base + 4.5))
        qapp.processEvents()

        messages = model_messages(viewer.model)
        assert messages[4:7] == ["msg 4", "late msg", "msg 5"]
        assert model_timestamps(viewer.model) == sorted(model_timestamps(viewer.model))

    def test_records_append_while_the_model_is_sorted_another_way(self, qapp):
        """A non-chronological model has no correct position, so records append.

        Bisecting rows that are not in ascending order would drop the record at
        an arbitrary row, which is worse than putting it at the end.
        """
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0
        for delay in (0, 10, 20, 30):
            viewer.handler.handle(make_record(f"at +{delay}s", base + delay))
        qapp.processEvents()

        # Sort descending by timestamp, which physically reorders the rows.
        viewer.model.setSortRole(ItemDataRole.NUMERIC_TIMESTAMP)
        viewer.model.sort(LogColumns.TIMESTAMP, qt.Qt.SortOrder.DescendingOrder)
        qapp.processEvents()
        assert model_messages(viewer.model) == [
            "at +30s", "at +20s", "at +10s", "at +0s"
        ]

        # A mid-range timestamp: under ascending rows this would bisect into the
        # middle. Here it must go to the end rather than an arbitrary row.
        viewer.handler.handle(make_record("at +15s", base + 15))
        qapp.processEvents()

        assert model_messages(viewer.model) == [
            "at +30s", "at +20s", "at +10s", "at +0s", "at +15s"
        ]

    def test_ordered_insertion_resumes_once_rows_are_chronological_again(self, qapp):
        """Recovering from an external sort must not need a restart."""
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0
        for delay in (0, 10, 20, 30):
            viewer.handler.handle(make_record(f"at +{delay}s", base + delay))
        qapp.processEvents()

        viewer.model.setSortRole(ItemDataRole.NUMERIC_TIMESTAMP)
        viewer.model.sort(LogColumns.TIMESTAMP, qt.Qt.SortOrder.DescendingOrder)
        viewer.model.sort(LogColumns.TIMESTAMP, qt.Qt.SortOrder.AscendingOrder)
        qapp.processEvents()

        # Rows are chronological once more, so a late record finds its place.
        viewer.handler.handle(make_record("at +15s", base + 15))
        qapp.processEvents()

        assert model_messages(viewer.model) == [
            "at +0s", "at +10s", "at +15s", "at +20s", "at +30s"
        ]

    def test_set_records_orders_a_scrambled_batch(self, qapp):
        """Bulk replacement is ordered too, without a per-record sort."""
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0
        recs = [make_record(f"at +{d}s", base + d) for d in (40, 10, 30, 0, 20)]

        viewer.set_records(*recs)
        qapp.processEvents()

        assert model_messages(viewer.model) == [
            "at +0s", "at +10s", "at +20s", "at +30s", "at +40s"
        ]


class TestAutoscrollCoalescing:
    """Autoscroll runs once per event-loop pass, not once per record.

    scrollToBottom walks the view's layout, so calling it per inserted row is
    O(n) per record -- the same quadratic shape as the per-record re-sort.
    """

    def test_burst_of_records_scrolls_once(self, qapp):
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0

        scrolls = []
        viewer.tree.scrollToBottom = lambda: scrolls.append(1)

        for i in range(100):
            viewer.handler.handle(make_record(f"msg {i}", base + i))

        # Nothing yet: the records arrived without the event loop running,
        # which is exactly how they arrive in a process logging inline.
        assert scrolls == []

        qapp.processEvents()
        assert len(scrolls) == 1, f"expected one coalesced scroll, got {len(scrolls)}"

    def test_no_scroll_when_user_has_scrolled_away(self, qapp):
        viewer = LogViewer(logger=None, initial_filters=[])
        scrolls = []
        viewer.tree.scrollToBottom = lambda: scrolls.append(1)

        viewer._should_autoscroll = False
        viewer.handler.handle(make_record("msg", 1_000_000_000.0))
        qapp.processEvents()

        assert scrolls == []
