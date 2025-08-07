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
        
        # Define test data with delays (in seconds from base_time) - single source of truth
        base_time = 1000000000
        test_data = [
            # (delay, message, level) - delivered out of chronological order
            (30, "Message at +30s", logging.INFO),    # Delivered 1st, should appear 4th
            (10, "Message at +10s", logging.WARNING), # Delivered 2nd, should appear 2nd  
            (50, "Message at +50s", logging.ERROR),   # Delivered 3rd, should appear 5th
            (0,  "Message at +0s",  logging.DEBUG),   # Delivered 4th, should appear 1st
            (20, "Message at +20s", logging.CRITICAL) # Delivered 5th, should appear 3rd
        ]
        
        # Create and deliver LogRecord objects out of chronological order
        for i, (delay, message, level) in enumerate(test_data):
            record = logging.LogRecord(
                name='test.sorting',
                level=level,
                pathname=__file__,
                lineno=50 + i,
                msg=message,
                args=(),
                exc_info=None
            )
            record.created = base_time + delay
            
            # Deliver the record to the viewer
            viewer.handler.handle(record)

        # Process any pending events
        qapp.processEvents()

        # Check both the source model and tree view model
        source_model = viewer.model
        tree_model = viewer.tree.model()

        # Verify we have all 5 messages in both models
        assert source_model.rowCount() == 5, f"Source model should have 5 log entries, got {source_model.rowCount()}"
        assert tree_model.rowCount() == 5, f"Tree model should have 5 log entries, got {tree_model.rowCount()}"

        
        # Expected chronological order (sorted by delay)
        expected_order = sorted(test_data, key=lambda x: x[0])  # Sort by delay
        
        # Verify tree view shows correct chronological order
        for i, (delay, expected_msg, expected_level) in enumerate(expected_order):
            expected_time = base_time + delay
            
            # Check tree view model data
            timestamp_index = tree_model.index(i, LogColumns.TIMESTAMP)
            message_index = tree_model.index(i, LogColumns.MESSAGE)
            level_index = tree_model.index(i, LogColumns.LEVEL)
            
            actual_timestamp = tree_model.data(timestamp_index, ItemDataRole.NUMERIC_TIMESTAMP)
            actual_message = tree_model.data(message_index, qt.Qt.DisplayRole)
            actual_level = tree_model.data(level_index, ItemDataRole.LEVEL_NUMBER)
            
            assert actual_timestamp is not None, f"Row {i} should have numeric timestamp"
            assert abs(actual_timestamp - expected_time) < 0.001, f"Row {i}: expected {expected_time}, got {actual_timestamp}"
            assert expected_msg in actual_message, f"Row {i}: expected '{expected_msg}' in '{actual_message}'"
            assert actual_level == expected_level, f"Row {i}: expected level {expected_level}, got {actual_level}"
    
    def test_sorting_preserved_after_filtering(self, qapp):
        """Test that chronological sorting is preserved when filters are applied and removed."""
        viewer = LogViewer(logger='test.sorting.filtering', initial_filters=[])
        
        # Define test data - single source of truth
        base_time = 1000000000
        test_data = [
            # (delay, message, level) - delivered out of chronological order  
            (40, "Error at +40s", logging.ERROR),
            (10, "Info at +10s", logging.INFO),
            (60, "Warning at +60s", logging.WARNING),
            (20, "Debug at +20s", logging.DEBUG),
            (30, "Error at +30s", logging.ERROR),
        ]
        
        # Deliver out of order
        for delay, message, level in test_data:
            record = logging.LogRecord(
                name='test.sorting.filtering',
                level=level,
                pathname=__file__,
                lineno=150,
                msg=message,
                args=(),
                exc_info=None
            )
            record.created = base_time + delay
            viewer.handler.handle(record)
        
        qapp.processEvents()
        
        # Expected chronological order (sorted by delay)
        expected_order = sorted(test_data, key=lambda x: x[0])  # Sort by delay
        all_messages_order = [msg for delay, msg, level in expected_order]
        
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
        
        # Expected error messages in chronological order
        error_data = [item for item in expected_order if item[2] == logging.ERROR]
        error_messages_order = [msg for delay, msg, level in error_data]
        
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