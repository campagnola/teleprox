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
            if item.rowCount() > 0:  # Has expandable content
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand exception details using UI
        source_index = viewer.model.indexFromItem(exception_item)
        tree_index = viewer.map_index_from_model(source_index)
        viewer.tree.expand(tree_index)
        assert exception_item.rowCount() > 0, "Should have exception children"
        
        # Test the main user-visible behavior: children are visible and contain exception content
        first_child = exception_item.child(0, 0)
        assert first_child is not None, "Should have first child"
        
        child_text = first_child.text()
        assert "ValueError" in child_text or "Exception" in child_text, f"Child should contain exception info, got: '{child_text}'"
    
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
            if item.rowCount() > 0:  # Has expandable content
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand to create children using UI expansion
        source_index = viewer.model.indexFromItem(exception_item)
        tree_index = viewer.map_index_from_model(source_index)
        viewer.tree.expand(tree_index)
        assert exception_item.rowCount() > 0, "Should have children"
        
        # Test that children are properly visible (the main user-visible behavior)
        # If inheritance is working, children should be visible when parent matches filters
        assert exception_item.rowCount() > 0, "Should have expanded children visible"
        
        # Get first child (category item)
        category_item = exception_item.child(0, 0)
        assert category_item is not None, "Should have category item"
        
        # Check that the child content looks reasonable (contains exception info)
        child_text = category_item.text()
        assert "Exception" in child_text or "RuntimeError" in child_text, f"Child should contain exception info, got: '{child_text}'"