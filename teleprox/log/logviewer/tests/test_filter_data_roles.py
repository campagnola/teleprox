#!/usr/bin/env python3
"""
Tests for filter data roles in the log viewer.
Verifies that filtering-related data is correctly stored with appropriate ItemDataRole values.
"""

import logging
import pytest
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox import qt


class TestFilterDataRoles:
    """Test cases for verifying correct filter data role storage."""
    
    # QApplication fixture provided by conftest.py
    
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