# Test LogViewer.set_records() method for bulk record replacement
# Verifies clearing existing records, preserving filters, clearing selection/expansion

import logging
import pytest
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import LogColumns
from teleprox import qt


class TestSetRecords:
    """Test LogViewer.set_records() method functionality."""

    def test_set_records_replaces_all_existing(self, qapp):
        """Test that set_records completely replaces existing records."""
        viewer = LogViewer(logger='test.set.records')
        logger = logging.getLogger('test.set.records')
        logger.setLevel(logging.DEBUG)

        # Add some initial records via normal logging
        logger.info("Initial message 1")
        logger.warning("Initial message 2")

        assert viewer.model.rowCount() == 2

        # Create new log records manually
        new_rec1 = logging.LogRecord(
            name='test.new',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg="New message 1",
            args=(),
            exc_info=None,
        )
        new_rec2 = logging.LogRecord(
            name='test.new',
            level=logging.ERROR,
            pathname='',
            lineno=0,
            msg="New message 2",
            args=(),
            exc_info=None,
        )

        # Replace all records
        viewer.set_records(new_rec1, new_rec2)

        # Should have exactly 2 records (the new ones)
        assert viewer.model.rowCount() == 2

        # Verify the new messages are present
        msg1 = viewer.model.item(0, LogColumns.MESSAGE).text()
        msg2 = viewer.model.item(1, LogColumns.MESSAGE).text()

        assert msg1 == "New message 1"
        assert msg2 == "New message 2"

        # Verify old messages are gone by checking none contain "Initial"
        for row in range(viewer.model.rowCount()):
            msg = viewer.model.item(row, LogColumns.MESSAGE).text()
            assert "Initial" not in msg

    def test_set_records_empty_clears_all(self, qapp):
        """Test that set_records() with no args clears all records."""
        viewer = LogViewer(logger='test.empty.set')
        logger = logging.getLogger('test.empty.set')
        logger.setLevel(logging.DEBUG)

        # Add some records
        logger.info("Message 1")
        logger.warning("Message 2")
        logger.error("Message 3")

        assert viewer.model.rowCount() == 3

        # Clear all records
        viewer.set_records()

        # Should be empty
        assert viewer.model.rowCount() == 0

    def test_set_records_preserves_filters(self, qapp):
        """Test that set_records preserves current filter settings."""
        viewer = LogViewer(logger='test.filter.preserve', initial_filters=('level: info',))
        logger = logging.getLogger('test.filter.preserve')
        logger.setLevel(logging.DEBUG)

        # Add initial records
        logger.debug("Debug message")  # Should be filtered out
        logger.info("Info message")

        # Process events to apply initial filters
        qapp.processEvents()

        # Check that filter is working (debug filtered out)
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 1  # Only info message visible

        # Create new records
        new_debug = logging.LogRecord(
            name='test.new',
            level=logging.DEBUG,
            pathname='',
            lineno=0,
            msg="New debug message",
            args=(),
            exc_info=None,
        )
        new_info = logging.LogRecord(
            name='test.new',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg="New info message",
            args=(),
            exc_info=None,
        )

        # Replace with new records
        viewer.set_records(new_debug, new_info)

        # Process events to apply filters
        qapp.processEvents()

        # Filter should still be active - only info message visible
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 1

        # Verify it's the new info message that's visible
        visible_msg = viewer.tree.model().data(
            viewer.tree.model().index(0, LogColumns.MESSAGE), qt.Qt.DisplayRole
        )
        assert visible_msg == "New info message"

    def test_set_records_clears_selection(self, qapp):
        """Test that set_records clears current selection."""
        viewer = LogViewer(logger='test.selection.clear')
        logger = logging.getLogger('test.selection.clear')
        logger.setLevel(logging.DEBUG)

        # Add records and select one
        logger.info("Message 1")
        logger.warning("Message 2")

        # Select first item
        index = viewer.tree.model().index(0, LogColumns.TIMESTAMP)
        viewer.tree.selectionModel().select(
            index, qt.QItemSelectionModel.Select | qt.QItemSelectionModel.Rows
        )

        # Verify selection exists
        assert len(viewer.tree.selectionModel().selectedIndexes()) > 0

        # Create new record and replace
        new_rec = logging.LogRecord(
            name='test.new',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg="New message",
            args=(),
            exc_info=None,
        )

        viewer.set_records(new_rec)

        # Selection should be cleared
        assert len(viewer.tree.selectionModel().selectedIndexes()) == 0

    def test_set_records_maintains_lazy_loading(self, qapp):
        """Test that set_records maintains lazy loading behavior for expandable records."""
        viewer = LogViewer(logger='test.lazy.loading')

        # Create a record with exception info (should be lazy loaded)
        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        new_rec = logging.LogRecord(
            name='test.exception',
            level=logging.ERROR,
            pathname='',
            lineno=0,
            msg="Error with exception",
            args=(),
            exc_info=exc_info,
        )

        viewer.set_records(new_rec)

        # Should have 1 top-level record
        assert viewer.model.rowCount() == 1

        # The record should have a placeholder child (lazy loading)
        top_item = viewer.model.item(0, 0)
        assert getattr(top_item, 'has_child_placeholder', False) == True
        assert top_item.rowCount() == 1  # Should have placeholder child

        # The child should be the loading placeholder
        placeholder = top_item.child(0, 0)
        assert placeholder.text() == "Loading..."

    def test_set_records_with_various_record_types(self, qapp):
        """Test set_records with different types of log records."""
        viewer = LogViewer(logger='test.various.types')

        # Create records of different levels and attributes
        simple_rec = logging.LogRecord(
            name='test.simple',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg="Simple message",
            args=(),
            exc_info=None,
        )

        # Record with extra attributes
        extra_rec = logging.LogRecord(
            name='test.extra',
            level=logging.WARNING,
            pathname='',
            lineno=0,
            msg="Message with extras",
            args=(),
            exc_info=None,
        )
        extra_rec.custom_attr = "custom value"
        extra_rec.another_attr = {"nested": "data"}

        viewer.set_records(simple_rec, extra_rec)

        # Should have both records
        assert viewer.model.rowCount() == 2

        # Simple record should have no expandable children
        simple_item = viewer.model.item(0, 0)
        assert getattr(simple_item, 'has_child_placeholder', False) == False
        assert simple_item.rowCount() == 0

        # Extra record should have expandable children (due to custom attributes)
        extra_item = viewer.model.item(1, 0)
        assert getattr(extra_item, 'has_child_placeholder', False) == True
        assert extra_item.rowCount() == 1  # Placeholder
