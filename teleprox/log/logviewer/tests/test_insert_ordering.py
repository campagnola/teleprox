# Records are placed in timestamp order as they arrive, rather than the model
# being re-sorted per record. Re-sorting per record made ingest quadratic: at a
# few thousand records the Qt thread spent longer sorting than the interval
# between records, which is enough to stall a process that logs at any volume,
# since records are delivered inline on that thread.

import logging

from teleprox import qt
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox.log.logviewer.log_model import LogModel
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
        an arbitrary row, which is worse than putting it at the end. This is the
        model's own rule; a viewer on top of it re-applies its sort instead (see
        TestSortIndicator).
        """
        model = LogModel()
        base = 1_000_000_000.0
        for delay in (0, 10, 20, 30):
            model.append_record(make_record(f"at +{delay}s", base + delay))

        # Sort descending by timestamp, which physically reorders the rows.
        model.setSortRole(ItemDataRole.NUMERIC_TIMESTAMP)
        model.sort(LogColumns.TIMESTAMP, qt.Qt.SortOrder.DescendingOrder)
        assert model_messages(model) == [
            "at +30s", "at +20s", "at +10s", "at +0s"
        ]

        # A mid-range timestamp: under ascending rows this would bisect into the
        # middle. Here it must go to the end rather than an arbitrary row.
        model.append_record(make_record("at +15s", base + 15))

        assert model_messages(model) == [
            "at +30s", "at +20s", "at +10s", "at +0s", "at +15s"
        ]

    def test_blind_append_out_of_order_stops_claiming_ascending_rows(self, qapp):
        """sort=False must not leave the cache asserting an order it does not have.

        The bulk path appends without placing each record, which is only correct
        while the records really do arrive in order. If one does not, a later
        bisect would be run against rows that are not ascending.
        """
        model = LogModel()
        base = 1_000_000_000.0
        for delay in (0, 50, 10):
            model.append_record(make_record(f"at +{delay}s", base + delay), sort=False)

        assert model_timestamps(model) == [base + 0, base + 50, base + 10]
        assert not model.rows_are_chronological()

        # Not bisected into the unsorted rows: appended, as for any model whose
        # rows have no chronologically correct position.
        model.append_record(make_record("at +20s", base + 20))
        assert model_messages(model)[-1] == "at +20s"

    def test_live_record_during_bulk_load_does_not_mislead_a_later_bisect(self, qapp):
        """set_records calls processEvents, so a live record can land mid-batch.

        The batch rows after it are appended blindly, leaving the rows out of
        order. A filter is active here, so the sort at the end of the bulk load
        reorders only the proxy and the source keeps that order.
        """
        viewer = LogViewer(logger=None, initial_filters=['level: info'])
        base = 1_000_000_000.0

        # Queue a live record for the processEvents() inside set_records.
        qt.QTimer.singleShot(0, lambda: viewer.handler.handle(make_record("live", base + 100)))
        viewer.set_records(*[make_record(f"at +{d}s", base + d) for d in (10, 20, 30)])
        qapp.processEvents()

        stamps = model_timestamps(viewer.model)
        assert stamps != sorted(stamps), "live record did not interleave; test is not exercising the case"

        viewer.handler.handle(make_record("at +15s", base + 15))
        qapp.processEvents()

        # +15 must not have been bisected into the middle of unsorted rows.
        assert model_messages(viewer.model)[-1] == "at +15s"


class TestSortIndicator:
    """The rows the view shows must match the order its header advertises."""

    def test_rows_follow_the_view_sort_indicator(self, qapp):
        """Arriving records must not contradict the header's sort indicator.

        With no filters the view is attached to the source model directly, so
        there is no proxy to place arriving rows. Ordered insertion appends them
        instead, which would leave the rows disagreeing with the indicator for
        as long as the view stayed open.
        """
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0
        for delay in (0, 10, 20, 30):
            viewer.handler.handle(make_record(f"at +{delay}s", base + delay))
        qapp.processEvents()

        viewer.tree.sortByColumn(LogColumns.TIMESTAMP, qt.Qt.SortOrder.DescendingOrder)
        qapp.processEvents()
        assert model_messages(viewer.model) == [
            "at +30s", "at +20s", "at +10s", "at +0s"
        ]

        for delay in (40, 50):
            viewer.handler.handle(make_record(f"at +{delay}s", base + delay))
        qapp.processEvents()

        stamps = model_timestamps(viewer.model)
        assert stamps == sorted(stamps, reverse=True), (
            "rows must stay in the order the header indicator shows"
        )

    def test_descending_view_resorts_once_per_burst(self, qapp):
        """Restoring the indicated order must not cost a sort per record.

        Re-sorting per record is what made ingest quadratic in the first place.
        """
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0
        viewer.tree.sortByColumn(LogColumns.TIMESTAMP, qt.Qt.SortOrder.DescendingOrder)
        qapp.processEvents()

        sorts = []
        original_sort = viewer.tree.sortByColumn
        viewer.tree.sortByColumn = lambda *a: (sorts.append(1), original_sort(*a))[1]

        for i in range(50):
            viewer.handler.handle(make_record(f"msg {i}", base + i))
        assert sorts == [], "no sorting before the event loop runs"

        qapp.processEvents()
        assert len(sorts) == 1, f"expected one coalesced re-sort, got {len(sorts)}"

    def test_filter_change_rearms_chronological_sorting(self, qapp):
        """A rebuilt filter chain hands the view a proxy with no sort set.

        Ordered insertion means nothing re-arms it per record any more, so
        apply_filters has to, or the new proxy passes the source order through
        unsorted.
        """
        viewer = LogViewer(logger=None, initial_filters=[])
        base = 1_000_000_000.0
        for delay in (0, 10, 20, 30):
            viewer.handler.handle(make_record(f"at +{delay}s", base + delay))
        qapp.processEvents()

        viewer.apply_filters(['level: info'])
        qapp.processEvents()

        proxy = viewer.tree.model()
        assert proxy is not viewer.model, "a filter should put a proxy in front of the model"
        assert proxy.sortColumn() == LogColumns.TIMESTAMP
        assert proxy.sortRole() == ItemDataRole.NUMERIC_TIMESTAMP

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
