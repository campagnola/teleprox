#!/usr/bin/env python3
"""
Integration test for log filtering with new column layout.
Tests that all filtering functionality works correctly after column changes.
"""

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


class TestColumnFilteringIntegration:
    """Integration tests for filtering with new column layout."""
    
    # QApplication fixture provided by conftest.py
    
    def test_complete_filtering_integration(self, qapp):
        """Comprehensive test of all filtering types with new column layout."""
        viewer = LogViewer(logger='test.integration.filtering')
        logger = logging.getLogger('test.integration.filtering')
        logger.setLevel(logging.DEBUG)
        
        # Add test messages with different attributes
        logger.debug("Debug message from main process")
        logger.info("Info message from worker process") 
        logger.warning("Warning message about connection")
        logger.error("Error in authentication system")
        logger.critical("Critical database failure")
        
        # Verify all messages were added
        assert viewer.model.rowCount() == 5, f"Expected 5 messages, got {viewer.model.rowCount()}"
        
        # Test 1: Level filtering (WARNING and above)
        print("Testing level filtering...")
        print(f"Before filtering: {viewer.model.rowCount()} rows in source model")
        viewer.apply_filters(['level: warning'])
        print(f"After filtering: {viewer.tree.model().rowCount()} rows visible")
        
        # Debug: check what proxy model we're using
        current_model = viewer.tree.model()
        print(f"Current tree model type: {type(current_model)}")
        print(f"Proxy model type: {type(viewer.proxy_model)}")
        
        visible_count = current_model.rowCount()
        assert visible_count == 3, f"Level filter 'warning': expected 3 rows, got {visible_count}"
        
        # Test 2: Level filtering (ERROR and above)
        viewer.apply_filters(['level: error'])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 2, f"Level filter 'error': expected 2 rows, got {visible_count}"
        
        # Test 3: Message content filtering
        viewer.apply_filters(['message: database'])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 1, f"Message filter 'database': expected 1 row, got {visible_count}"
        
        # Test 4: Logger filtering (exact match)
        viewer.apply_filters(['logger: test.integration.filtering'])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 5, f"Logger filter: expected 5 rows, got {visible_count}"
        
        # Test 5: Source filtering (process/thread info)
        viewer.apply_filters(['source: MainProcess'])
        visible_count = viewer.tree.model().rowCount()
        # All messages should be from MainProcess in this test
        assert visible_count == 5, f"Source filter 'MainProcess': expected 5 rows, got {visible_count}"
        
        # Test 6: Combined filtering
        viewer.apply_filters(['level: info', 'message: process'])
        visible_count = viewer.tree.model().rowCount()
        # Should match "Info message from worker process" and any other process messages at info+ level
        assert visible_count >= 1, f"Combined filter: expected at least 1 row, got {visible_count}"
        
        # Test 7: Clear all filters
        viewer.apply_filters([])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 5, f"No filters: expected 5 rows, got {visible_count}"
        
        print("✅ All filtering integration tests passed!")
    
    def test_column_data_mapping(self, qapp):
        """Test that data is stored in the correct columns after layout changes."""
        viewer = LogViewer(logger='test.column.mapping')
        logger = logging.getLogger('test.column.mapping')
        logger.setLevel(logging.DEBUG)
        
        # Add a test message
        logger.warning("Test message for column mapping")
        
        assert viewer.model.rowCount() == 1, "Expected 1 message"
        
        # Check that data is in the correct columns
        row = 0
        
        # Timestamp column
        timestamp_item = viewer.model.item(row, LogColumns.TIMESTAMP)
        assert timestamp_item is not None, "Timestamp item should exist"
        assert timestamp_item.text() != "", "Timestamp should have text"
        
        # Host column (may be empty)
        host_item = viewer.model.item(row, LogColumns.HOST)
        assert host_item is not None, "Host item should exist"
        
        # Process column
        process_item = viewer.model.item(row, LogColumns.PROCESS)
        assert process_item is not None, "Process item should exist"
        assert process_item.text() != "", "Process should have text"
        
        # Thread column
        thread_item = viewer.model.item(row, LogColumns.THREAD)
        assert thread_item is not None, "Thread item should exist"
        assert thread_item.text() != "", "Thread should have text"
        
        # Source column (combined process/thread)
        source_item = viewer.model.item(row, LogColumns.SOURCE)
        assert source_item is not None, "Source item should exist"
        assert source_item.text() != "", "Source should have text"
        assert "/" in source_item.text(), "Source should contain process/thread separator"
        
        # Logger column
        logger_item = viewer.model.item(row, LogColumns.LOGGER)
        assert logger_item is not None, "Logger item should exist"
        assert logger_item.text() == "test.column.mapping", "Logger should match expected name"
        
        # Level column
        level_item = viewer.model.item(row, LogColumns.LEVEL)
        assert level_item is not None, "Level item should exist"
        assert "WARNING" in level_item.text(), "Level should contain WARNING"
        
        # Message column
        message_item = viewer.model.item(row, LogColumns.MESSAGE)
        assert message_item is not None, "Message item should exist"
        assert message_item.text() == "Test message for column mapping", "Message should match"
        
        # Task column (may be empty)
        task_item = viewer.model.item(row, LogColumns.TASK)
        assert task_item is not None, "Task item should exist"
        
        print("✅ Column data mapping test passed!")
    
    def test_filter_data_roles(self, qapp):
        """Test that filtering data roles are stored correctly in new column layout."""
        viewer = LogViewer(logger='test.filter.data')
        logger = logging.getLogger('test.filter.data')
        logger.setLevel(logging.DEBUG)
        
        # Add a test message
        logger.error("Test error message")
        
        assert viewer.model.rowCount() == 1, "Expected 1 message"
        
        row = 0
        
        # Check that filter data is stored in the correct items
        timestamp_item = viewer.model.item(row, LogColumns.TIMESTAMP)
        numeric_timestamp = timestamp_item.data(ItemDataRole.NUMERIC_TIMESTAMP)
        assert numeric_timestamp is not None, "Numeric timestamp should be stored"
        assert isinstance(numeric_timestamp, (int, float)), "Timestamp should be numeric"
        
        source_item = viewer.model.item(row, LogColumns.SOURCE)
        process_name = source_item.data(ItemDataRole.PROCESS_NAME)
        thread_name = source_item.data(ItemDataRole.THREAD_NAME)
        assert process_name is not None, "Process name should be stored"
        assert thread_name is not None, "Thread name should be stored"
        
        logger_item = viewer.model.item(row, LogColumns.LOGGER)
        logger_name = logger_item.data(ItemDataRole.LOGGER_NAME)
        assert logger_name == "test.filter.data", "Logger name should be stored correctly"
        
        level_item = viewer.model.item(row, LogColumns.LEVEL)
        level_number = level_item.data(ItemDataRole.LEVEL_NUMBER)
        level_cipher = level_item.data(ItemDataRole.LEVEL_CIPHER)
        assert level_number == 40, "Level number should be 40 (ERROR)"
        assert level_cipher is not None, "Level cipher should be stored"
        
        message_item = viewer.model.item(row, LogColumns.MESSAGE)
        message_text = message_item.data(ItemDataRole.MESSAGE_TEXT)
        assert message_text == "Test error message", "Message text should be stored correctly"
        
        print("✅ Filter data roles test passed!")


def run_tests():
    """Run the integration tests."""
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    test_instance = TestColumnFilteringIntegration()
    
    try:
        print("Running column filtering integration tests...")
        test_instance.test_complete_filtering_integration(qapp)
        test_instance.test_column_data_mapping(qapp)
        test_instance.test_filter_data_roles(qapp)
        print("\n🎉 All integration tests passed!")
        return True
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up Qt application
        if qapp:
            qapp.processEvents()  # Process any pending events


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)