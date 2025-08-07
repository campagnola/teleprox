import logging
import time
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox import qt

try:
    import pytest
except ImportError:
    # Mock pytest for basic functionality
    class MockPytest:
        def fixture(self, func):
            return func
    pytest = MockPytest()


class TestLogViewerSorting:
    """Test cases for chronological sorting of log messages."""
    
    # QApplication fixture provided by conftest.py
    
    def test_out_of_order_log_records_are_sorted_chronologically(self, qapp):
        """Test that LogRecord objects delivered out of order are sorted chronologically."""
        viewer = LogViewer(logger='test.sorting', initial_filters=[])
        
        # Create timestamps that are intentionally out of order
        base_time = 1000000000
        timestamps = [
            base_time + 30,  # Latest (should appear last)
            base_time + 10,  # Middle 
            base_time + 50,  # Very latest (should appear last)
            base_time + 0,   # Earliest (should appear first)
            base_time + 20,  # Middle-late
        ]
        
        messages = [
            "Message at +30s",
            "Message at +10s", 
            "Message at +50s",
            "Message at +0s",
            "Message at +20s",
        ]
        
        levels = [
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.DEBUG,
            logging.CRITICAL,
        ]
        
        # Create and deliver LogRecord objects out of chronological order
        for i, (timestamp, message, level) in enumerate(zip(timestamps, messages, levels)):
            record = logging.LogRecord(
                name='test.sorting',
                level=level,
                pathname=__file__,
                lineno=50 + i,
                msg=message,
                args=(),
                exc_info=None
            )
            record.created = timestamp
            
            # Deliver the record to the viewer
            viewer.handler.handle(record)

        # Process any pending events
        qapp.processEvents()

        # sorting happens on the model directly connected to the tree        
        model = viewer.tree.model()

        # Verify we have all 5 messages        
        assert model.rowCount() == 5, f"Should have 5 log entries, got {model.rowCount()}"

        # Debug: Print actual order to see what's happening
        for i in range(model.rowCount()):
            timestamp_item = model.item(i, LogColumns.TIMESTAMP)
            message_item = model.item(i, LogColumns.MESSAGE)
            actual_timestamp = timestamp_item.data(ItemDataRole.NUMERIC_TIMESTAMP)
            actual_message = message_item.text()
        
        # Verify they are sorted chronologically by checking timestamps
        expected_order = [
            (base_time + 0, "Message at +0s", logging.DEBUG),
            (base_time + 10, "Message at +10s", logging.WARNING),
            (base_time + 20, "Message at +20s", logging.CRITICAL),
            (base_time + 30, "Message at +30s", logging.INFO),
            (base_time + 50, "Message at +50s", logging.ERROR),
        ]
        
        for i, (expected_time, expected_msg, expected_level) in enumerate(expected_order):
            # Get the timestamp item for this row
            timestamp_item = model.item(i, LogColumns.TIMESTAMP)
            assert timestamp_item is not None, f"Should have timestamp item at row {i}"
            
            # Check the numeric timestamp used for sorting
            actual_timestamp = timestamp_item.data(ItemDataRole.NUMERIC_TIMESTAMP)
            assert actual_timestamp is not None, f"Row {i} should have numeric timestamp"
            assert abs(actual_timestamp - expected_time) < 0.001, f"Row {i}: expected {expected_time}, got {actual_timestamp}"
            
            # Check the message content
            message_item = model.item(i, LogColumns.MESSAGE)
            assert message_item is not None, f"Should have message item at row {i}"
            actual_message = message_item.text()
            assert expected_msg in actual_message, f"Row {i}: expected '{expected_msg}' in '{actual_message}'"
            
            # Check the level
            level_item = model.item(i, LogColumns.LEVEL)
            assert level_item is not None, f"Should have level item at row {i}"
            actual_level = level_item.data(ItemDataRole.LEVEL_NUMBER)
            assert actual_level == expected_level, f"Row {i}: expected level {expected_level}, got {actual_level}"
    
    def test_sorting_preserved_after_filtering(self, qapp):
        """Test that chronological sorting is preserved when filters are applied and removed."""
        viewer = LogViewer(logger='test.sorting.filtering', initial_filters=[])
        
        base_time = 1000000000
        
        # Create out-of-order messages with different levels
        test_data = [
            (base_time + 40, "Error at +40s", logging.ERROR),
            (base_time + 10, "Info at +10s", logging.INFO),
            (base_time + 60, "Warning at +60s", logging.WARNING),
            (base_time + 20, "Debug at +20s", logging.DEBUG),
            (base_time + 30, "Error at +30s", logging.ERROR),
        ]
        
        # Deliver out of order
        for timestamp, message, level in test_data:
            record = logging.LogRecord(
                name='test.sorting.filtering',
                level=level,
                pathname=__file__,
                lineno=150,
                msg=message,
                args=(),
                exc_info=None
            )
            record.created = timestamp
            viewer.handler.handle(record)
        
        qapp.processEvents()
        
        # Verify initial sorting (all messages)
        all_messages_order = [
            "Info at +10s",     # +10
            "Debug at +20s",    # +20
            "Error at +30s",    # +30
            "Error at +40s",    # +40
            "Warning at +60s",  # +60
        ]
        
        model = viewer.tree.model()
        for i, expected_msg in enumerate(all_messages_order):
            message_index = model.index(i, LogColumns.MESSAGE)
            actual_message = model.data(message_index, qt.Qt.DisplayRole)
            assert expected_msg in actual_message, f"Before filtering, row {i}: expected '{expected_msg}' in '{actual_message}'"
        
        # Apply ERROR level filter
        viewer.apply_filters(['level: error'])
        
        # Verify filtered results are still sorted
        filtered_model = viewer.tree.model()
        assert filtered_model.rowCount() == 2, "Should have 2 error messages after filtering"
        
        error_messages_order = [
            "Error at +30s",    # +30 (earlier)
            "Error at +40s",    # +40 (later)
        ]
        
        for i, expected_msg in enumerate(error_messages_order):
            message_index = filtered_model.index(i, LogColumns.MESSAGE)
            actual_message = filtered_model.data(message_index, qt.Qt.DisplayRole)
            assert expected_msg in actual_message, f"After filtering, row {i}: expected '{expected_msg}' in '{actual_message}'"
        
        # Clear filters
        viewer.apply_filters([])
        
        # Verify sorting is still maintained after clearing filters
        final_model = viewer.tree.model()
        assert final_model.rowCount() == 5, "Should have all 5 messages after clearing filters"
        
        for i, expected_msg in enumerate(all_messages_order):
            message_index = final_model.index(i, LogColumns.MESSAGE)
            actual_message = final_model.data(message_index, qt.Qt.DisplayRole)
            assert expected_msg in actual_message, f"After clearing filters, row {i}: expected '{expected_msg}' in '{actual_message}'"


def run_manual_tests():
    """Run basic tests without pytest."""
    # Create QApplication for manual testing (conftest.py only works in pytest)
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    print("Test 1: Out of order log records are sorted chronologically...")
    test = TestLogViewerSorting()
    test.test_out_of_order_log_records_are_sorted_chronologically(qapp)
    print("✅ Test 1 passed!")
    
    print("Test 2: Mixed delivery patterns maintain sorting...")
    test.test_mixed_delivery_patterns_maintain_sorting(qapp)
    print("✅ Test 2 passed!")
    
    print("Test 3: Sorting preserved after filtering...")
    test.test_sorting_preserved_after_filtering(qapp)
    print("✅ Test 3 passed!")
    
    print("All sorting tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()