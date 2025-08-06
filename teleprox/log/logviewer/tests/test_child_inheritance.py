#!/usr/bin/env python3
"""
Tests for data inheritance by exception children.
Verifies that exception/traceback children inherit parent's filtering data.
"""

import logging
import pytest
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox import qt


class TestChildDataInheritance:
    """Test cases for child data inheritance from parent log entries."""
    
    # QApplication fixture provided by conftest.py
    
    def test_children_inherit_parent_filter_data(self, qapp):
        """Test that exception children inherit parent's filter-relevant data."""
        viewer = LogViewer(logger='test.inherit.data')
        logger = logging.getLogger('test.inherit.data')
        logger.setLevel(logging.DEBUG)
        
        # Add an error with exception details
        try:
            raise ValueError("Test exception for data inheritance")
        except Exception:
            logger.error("Error message with exception", exc_info=True)
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand exception details
        viewer.model.replace_placeholder_with_content(exception_item)
        assert exception_item.rowCount() > 0, "Should have exception children"
        
        # Check that children inherited parent's filter data
        parent_level = exception_item.child(0, LogColumns.LEVEL).data(ItemDataRole.LEVEL_NUMBER)
        parent_cipher = exception_item.child(0, LogColumns.LEVEL).data(ItemDataRole.LEVEL_CIPHER)
        parent_logger = exception_item.child(0, LogColumns.LOGGER).data(ItemDataRole.LOGGER_NAME)
        
        # Get original record data for comparison
        original_record = exception_item.data(ItemDataRole.PYTHON_DATA)
        
        assert parent_level == original_record.levelno, "Child should inherit parent's level number"
        assert parent_logger == original_record.name, "Child should inherit parent's logger name"
        assert parent_cipher is not None, "Child should have level cipher"
    
    def test_new_column_child_inheritance(self, qapp):
        """Test that children properly inherit parent's data for new columns."""
        viewer = LogViewer(logger='test.inherit.new.columns')
        logger = logging.getLogger('test.inherit.new.columns')
        logger.setLevel(logging.DEBUG)
        
        # Create an exception with children
        try:
            raise RuntimeError("Test inheritance for new columns")
        except Exception:
            logger.error("Error for inheritance testing", exc_info=True)
        
        qapp.processEvents()
        
        # Find and expand exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand to create children
        viewer.model.replace_placeholder_with_content(exception_item)
        assert exception_item.rowCount() > 0, "Should have children"
        
        # Check that first child (category item) has inherited new column data
        category_item_host = exception_item.child(0, LogColumns.HOST)
        category_item_process = exception_item.child(0, LogColumns.PROCESS)
        category_item_thread = exception_item.child(0, LogColumns.THREAD)
        
        assert category_item_host is not None, "Category item should have host column"
        assert category_item_process is not None, "Category item should have process column"  
        assert category_item_thread is not None, "Category item should have thread column"
        
        # Check that inherited data matches parent
        host_text = category_item_host.text()
        process_text = category_item_process.text()
        thread_text = category_item_thread.text()
        
        # Host should default to localhost for local logs
        assert host_text == 'localhost', f"Child should inherit host 'localhost', got '{host_text}'"
        assert process_text == 'MainProcess', f"Child should inherit process 'MainProcess', got '{process_text}'"
        assert thread_text == 'MainThread', f"Child should inherit thread 'MainThread', got '{thread_text}'"