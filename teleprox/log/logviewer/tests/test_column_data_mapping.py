#!/usr/bin/env python3
"""
Tests for column data mapping in the log viewer.
Verifies that log data is correctly stored in the appropriate columns.
"""

import logging
import pytest
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox import qt


class TestColumnDataMapping:
    """Test cases for verifying correct column data mapping."""
    
    # QApplication fixture provided by conftest.py
    
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