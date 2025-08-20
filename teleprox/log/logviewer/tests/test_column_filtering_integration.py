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
    
    def test_level_filtering_with_column_layout(self, qapp):
        """Test level filtering works with new column layout."""
        viewer = LogViewer(logger='test.level.filtering')
        logger = logging.getLogger('test.level.filtering')
        logger.setLevel(logging.DEBUG)
        
        # Add test messages at different levels
        logger.debug("Debug message")
        logger.info("Info message") 
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")
        
        assert viewer.model.rowCount() == 5, "Expected 5 messages"
        
        # Test WARNING level and above
        viewer.apply_filters(['level: warning'])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 3, f"Level filter 'warning': expected 3 rows, got {visible_count}"
        
        # Test ERROR level and above
        viewer.apply_filters(['level: error'])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 2, f"Level filter 'error': expected 2 rows, got {visible_count}"
    
    def test_message_filtering_with_column_layout(self, qapp):
        """Test message content filtering works with new column layout."""
        viewer = LogViewer(logger='test.message.filtering')
        logger = logging.getLogger('test.message.filtering')
        logger.setLevel(logging.DEBUG)
        
        logger.info("Database connection established")
        logger.warning("Network timeout occurred")
        logger.error("Database query failed")
        
        assert viewer.model.rowCount() == 3, "Expected 3 messages"
        
        # Test message content filtering
        viewer.apply_filters(['message: database'])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 2, f"Message filter 'database': expected 2 rows, got {visible_count}"
    
    def test_combined_filtering_with_column_layout(self, qapp):
        """Test combined filtering works with new column layout."""
        viewer = LogViewer(logger='test.combined.filtering')
        logger = logging.getLogger('test.combined.filtering')
        logger.setLevel(logging.DEBUG)
        
        logger.debug("Debug info message")
        logger.info("Info process message")
        logger.warning("Warning process message")
        logger.error("Error system message")
        
        assert viewer.model.rowCount() == 4, "Expected 4 messages"
        
        # Test combined filtering
        viewer.apply_filters(['level: info', 'message: process'])
        visible_count = viewer.tree.model().rowCount()
        assert visible_count == 2, f"Combined filter: expected 2 rows, got {visible_count}"


def run_tests():
    """Run the integration tests."""
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    test_instance = TestColumnFilteringIntegration()
    
    try:
        print("Running column filtering integration tests...")
        test_instance.test_level_filtering_with_column_layout(qapp)
        test_instance.test_message_filtering_with_column_layout(qapp)
        test_instance.test_combined_filtering_with_column_layout(qapp)
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