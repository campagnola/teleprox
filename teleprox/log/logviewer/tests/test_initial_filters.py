# Test initial_filters parameter for LogViewer
# Verifies that filters passed to __init__ are immediately active

import logging
import pytest
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import LogColumns
from teleprox import qt


class TestInitialFilters:
    """Test LogViewer initial_filters parameter functionality."""

    def test_initial_filters_applied_immediately(self, qapp):
        """Test that initial_filters are applied when LogViewer is created."""
        # Create viewer with level filter BEFORE adding any log messages
        viewer = LogViewer(logger='test.initial.filters', initial_filters=('level: info',))
        viewer.show()
        qapp.processEvents()

        # Get the logger and set level
        logger = logging.getLogger('test.initial.filters')
        logger.setLevel(logging.DEBUG)

        # Add messages at different levels
        logger.debug("Debug message - should be filtered")
        logger.info("Info message - should be visible")
        logger.warning("Warning message - should be visible")
        logger.error("Error message - should be visible")

        # Process events to ensure messages are added
        qapp.processEvents()

        # Check that filter is working immediately
        # The tree model should only show INFO and above (3 messages)
        visible_count = viewer.tree.model().rowCount()
        print(f"Visible count: {visible_count}")
        print(f"Total count in source model: {viewer.model.rowCount()}")

        # Debug: Print what's visible
        for i in range(visible_count):
            msg = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.MESSAGE), qt.Qt.DisplayRole
            )
            print(f"Visible message {i}: {msg}")

        assert visible_count == 3, f"Expected 3 visible messages, got {visible_count}"

    def test_initial_filters_displayed_in_filter_bar(self, qapp):
        """Test that initial_filters appear in the filter input widget."""
        viewer = LogViewer(logger='test.filter.bar', initial_filters=('level: info', 'logger: test.*'))
        viewer.show()
        qapp.processEvents()

        # Get the filter strings from the filter input widget
        filter_strings = viewer.filter_input_widget.get_filter_strings()

        assert len(filter_strings) == 2, f"Expected 2 filters, got {len(filter_strings)}"
        assert 'level: info' in filter_strings
        assert 'logger: test.*' in filter_strings

    def test_initial_filters_with_empty_tuple(self, qapp):
        """Test that empty initial_filters shows all messages."""
        viewer = LogViewer(logger='test.empty.filters', initial_filters=())
        viewer.show()
        qapp.processEvents()

        logger = logging.getLogger('test.empty.filters')
        logger.setLevel(logging.DEBUG)

        # Add messages at all levels
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        qapp.processEvents()

        # All messages should be visible (no filters)
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 4, f"Expected 4 visible messages, got {visible_count}"

    def test_initial_filters_with_viewer_created_last(self, qapp):
        """Test initial_filters when viewer is created after logger exists."""
        # Setup logger FIRST
        logger = logging.getLogger('test.order.matters')
        logger.setLevel(logging.DEBUG)

        # Create viewer with filter AFTER logger exists
        viewer = LogViewer(logger='test.order.matters', initial_filters=('level: info',))
        viewer.show()
        qapp.processEvents()

        # Add messages
        logger.debug("Debug message - should be filtered")
        logger.info("Info message - should be visible")
        logger.warning("Warning message - should be visible")

        qapp.processEvents()

        # Check filtering works
        visible_count = viewer.tree.model().rowCount()
        print(f"Visible count: {visible_count}")

        for i in range(visible_count):
            msg = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.MESSAGE), qt.Qt.DisplayRole
            )
            print(f"Visible message {i}: {msg}")

        assert visible_count == 2, f"Expected 2 visible messages, got {visible_count}"

    def test_initial_filters_with_no_logger_attached(self, qapp):
        """Test initial_filters when viewer has no logger attached (logger=None)."""
        # Create viewer with no logger but with initial filters
        viewer = LogViewer(logger=None, initial_filters=('level: info',))
        viewer.show()
        qapp.processEvents()

        # Manually create log records and add them
        debug_rec = logging.LogRecord(
            name='test.manual',
            level=logging.DEBUG,
            pathname='',
            lineno=0,
            msg="Debug message - should be filtered",
            args=(),
            exc_info=None,
        )
        info_rec = logging.LogRecord(
            name='test.manual',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg="Info message - should be visible",
            args=(),
            exc_info=None,
        )
        warning_rec = logging.LogRecord(
            name='test.manual',
            level=logging.WARNING,
            pathname='',
            lineno=0,
            msg="Warning message - should be visible",
            args=(),
            exc_info=None,
        )

        # Add records directly via new_record
        viewer.new_record(debug_rec)
        viewer.new_record(info_rec)
        viewer.new_record(warning_rec)

        qapp.processEvents()

        # Check filtering works
        visible_count = viewer.tree.model().rowCount()
        print(f"Visible count: {visible_count}")
        print(f"Total in source model: {viewer.model.rowCount()}")

        for i in range(visible_count):
            msg = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.MESSAGE), qt.Qt.DisplayRole
            )
            level = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.LEVEL), qt.Qt.DisplayRole
            )
            print(f"Visible message {i}: [{level}] {msg}")

        assert visible_count == 2, f"Expected 2 visible messages, got {visible_count}"

    def test_initial_filters_without_processEvents(self, qapp):
        """Test that initial_filters work immediately without calling processEvents."""
        # Create viewer with filter
        viewer = LogViewer(logger='test.no.process', initial_filters=('level: info',))

        # Add logger and messages WITHOUT calling processEvents() first
        logger = logging.getLogger('test.no.process')
        logger.setLevel(logging.DEBUG)

        logger.debug("Debug message - should be filtered")
        logger.info("Info message - should be visible")
        logger.warning("Warning message - should be visible")

        # NOW process events
        qapp.processEvents()

        # Check filtering
        visible_count = viewer.tree.model().rowCount()
        print(f"Visible count without initial processEvents: {visible_count}")
        print(f"Source model count: {viewer.model.rowCount()}")

        for i in range(visible_count):
            msg = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.MESSAGE), qt.Qt.DisplayRole
            )
            level = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.LEVEL), qt.Qt.DisplayRole
            )
            print(f"Visible: [{level}] {msg}")

        assert visible_count == 2, f"Expected 2 visible messages, got {visible_count}"

    def test_initial_filters_with_messages_arriving_during_init(self, qapp):
        """Test initial_filters when messages arrive during LogViewer initialization.

        This reproduces the scenario where logging happens before/during GUI creation,
        and the initial filters should filter those messages immediately.
        """
        # Create a logger FIRST and configure it
        logger = logging.getLogger('test.init.race')
        logger.setLevel(logging.DEBUG)

        # Create LogViewer with initial filter - messages will start arriving
        # as soon as the handler is attached during __init__
        viewer = LogViewer(logger='test.init.race', initial_filters=('level: info',))

        # Immediately send messages (simulating messages arriving during/right after init)
        logger.debug("Debug 1 - should be filtered")
        logger.info("Info 1 - should be visible")
        logger.debug("Debug 2 - should be filtered")
        logger.warning("Warning 1 - should be visible")
        logger.debug("Debug 3 - should be filtered")
        logger.error("Error 1 - should be visible")

        # Process Qt events
        qapp.processEvents()

        # Check that filters are working
        visible_count = viewer.tree.model().rowCount()
        source_count = viewer.model.rowCount()

        print(f"\nInitial state:")
        print(f"  Source model: {source_count} messages")
        print(f"  Visible (filtered): {visible_count} messages")

        for i in range(visible_count):
            msg = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.MESSAGE), qt.Qt.DisplayRole
            )
            level = viewer.tree.model().data(
                viewer.tree.model().index(i, LogColumns.LEVEL), qt.Qt.DisplayRole
            )
            print(f"  Visible {i}: [{level}] {msg}")

        # Should only show INFO and above (3 messages)
        assert source_count == 6, f"Expected 6 messages in source, got {source_count}"
        assert visible_count == 3, f"Expected 3 visible messages with level:info filter, got {visible_count}"

        # Check what logger name is actually stored
        if visible_count > 0:
            logger_name = viewer.model.item(0, LogColumns.LOGGER).text()
            print(f"Logger name in model: '{logger_name}'")

        # Now simulate adding a second filter to verify the workaround
        print("\nAdding second filter...")
        viewer.filter_input_widget.filter_input.setText(f'logger: {logger_name}')
        viewer.filter_input_widget.add_filter()
        qapp.processEvents()

        visible_count_after = viewer.tree.model().rowCount()
        print(f"After adding second filter: {visible_count_after} visible")

        # Should still show the same 3 messages (both filters match)
        assert visible_count_after == 3, f"Expected 3 visible messages after second filter, got {visible_count_after}"
