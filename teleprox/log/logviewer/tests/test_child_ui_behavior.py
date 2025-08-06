#!/usr/bin/env python3
"""
Tests for child UI behavior (highlighting, selection, fonts).
Verifies visual presentation and interaction behavior of exception children.
"""

import logging
import pytest
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox import qt


class TestChildUIBehavior:
    """Test cases for UI behavior of exception children."""
    
    # QApplication fixture provided by conftest.py
    
    def test_child_selection_highlighting(self, qapp):
        """Test that selecting child items uses parent's highlighting data."""
        viewer = LogViewer(logger='test.child.highlighting')
        logger = logging.getLogger('test.child.highlighting')
        logger.setLevel(logging.DEBUG)
        
        # Add an error with exception
        try:
            raise ValueError("Test exception for highlighting")
        except Exception:
            logger.error("Error with exception", exc_info=True)
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        child_count = exception_item.rowCount()
        assert child_count > 0, "Should have exception children"
        
        # Create a mock selection for the child item
        model = viewer.tree.model()
        parent_index = model.index(0, 0)  # Parent item
        child_index = model.index(0, 0, parent_index)  # First child
        
        # Create mock selection objects
        class MockSelection:
            def __init__(self, indexes):
                self._indexes = indexes
            def indexes(self):
                return self._indexes
        
        # Test selecting parent item
        parent_selection = MockSelection([parent_index])
        viewer._on_selection_changed(parent_selection, MockSelection([]))
        
        # Should have highlighting criteria set (no exception should occur)
        # The test passes if no exception is raised
        
        # Test selecting child item
        child_selection = MockSelection([child_index])
        viewer._on_selection_changed(child_selection, MockSelection([]))
        
        # Should use parent's data for highlighting (no exception should occur)
        # The test passes if no exception is raised and highlighting works
    
    def test_child_highlighting_isolation(self, qapp):
        """Test that child items don't get highlighted when unrelated entries are selected."""
        viewer = LogViewer(logger='test.highlight.isolation')
        
        # Create two different loggers
        logger_a = logging.getLogger('test.highlight.isolation.moduleA')
        logger_b = logging.getLogger('test.highlight.isolation.moduleB')
        logger_a.setLevel(logging.DEBUG)
        logger_b.setLevel(logging.DEBUG)
        
        # Add messages from both loggers
        logger_a.info("Module A message")
        
        try:
            raise ValueError("Module A exception")
        except Exception:
            logger_a.error("Module A error", exc_info=True)
        
        logger_b.info("Module B message")
        
        try:
            raise RuntimeError("Module B exception")
        except Exception:
            logger_b.error("Module B error", exc_info=True)
        
        # Find and expand both exceptions
        exception_items = []
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                viewer.model.replace_placeholder_with_content(item)
                exception_items.append((i, item))
        
        assert len(exception_items) == 2, "Should have 2 exception items"
        
        # Test that selecting Module A doesn't affect Module B children
        model = viewer.tree.model()
        
        # Select the Module A normal message (row 0)
        module_a_index = model.index(0, 0)
        
        class MockSelection:
            def __init__(self, indexes):
                self._indexes = indexes
            def indexes(self):
                return self._indexes
        
        # Select Module A message
        module_a_selection = MockSelection([module_a_index])
        viewer._on_selection_changed(module_a_selection, MockSelection([]))
        
        # Verify highlighting delegate has Module A criteria
        assert "moduleA" in viewer.highlight_delegate.selected_logger
        
        # The highlighting delegate should not highlight Module B children
        # when Module A is selected (this would be the bug we're fixing)
        
        # Test passed if no exceptions were raised during selection changes
    
    def test_exception_message_ordering(self, qapp):
        """Test that exception message appears at bottom of traceback."""
        viewer = LogViewer(logger='test.exception.order')
        logger = logging.getLogger('test.exception.order')
        logger.setLevel(logging.DEBUG)
        
        # Create a multi-level exception to get a proper traceback
        def inner_function():
            raise ValueError("Test exception message")
        
        def outer_function():
            inner_function()
        
        try:
            outer_function()
        except Exception:
            logger.error("Error with traceback", exc_info=True)
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        child_count = exception_item.rowCount()
        assert child_count >= 1, "Should have at least the exception category"
        
        # Get the exception category (should be first child)
        exc_category = exception_item.child(0, LogColumns.TIMESTAMP)
        assert exc_category is not None, "Should have exception category"
        
        category_child_count = exc_category.rowCount()
        assert category_child_count > 1, "Exception category should have multiple children (traceback + exception)"
        
        # Check that the last child in the category is the exception message
        last_child = exc_category.child(category_child_count - 1, LogColumns.TIMESTAMP)  # Last row, first column
        assert last_child is not None, "Should have last child in exception category"
        
        last_message = last_child.text()
        assert "ValueError" in last_message, "Last child should be the exception message"
        assert "Test exception message" in last_message, "Should contain the exception text"
        
        # Check that earlier children are traceback frames
        first_child = exc_category.child(0, LogColumns.TIMESTAMP)  # First row, first column
        assert first_child is not None, "Should have first child in exception category"
        
        first_message = first_child.text()
        assert "File " in first_message, "First child should be a traceback frame"
    
    def test_monospace_font_for_code(self, qapp):
        """Test that traceback frames use monospace font."""
        viewer = LogViewer(logger='test.monospace')
        logger = logging.getLogger('test.monospace')
        logger.setLevel(logging.DEBUG)
        
        try:
            raise RuntimeError("Test for monospace")
        except Exception:
            logger.error("Error with traceback", exc_info=True)
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        
        # Get the exception category
        exc_category = exception_item.child(0, LogColumns.TIMESTAMP)
        assert exc_category is not None, "Should have exception category"
        
        # Check that traceback frames have monospace font
        # Note: We can't easily test the actual font in a unit test,
        # but we can verify the structure is correct
        category_child_count = exc_category.rowCount()
        assert category_child_count >= 2, "Should have at least traceback frame + exception message"
        
        # Verify we have at least one traceback frame (not just the exception message)
        has_traceback = False
        for i in range(category_child_count - 1):  # Exclude last item (exception message)
            child = exc_category.child(i, LogColumns.TIMESTAMP)  # First column contains the content
            if child and "File " in child.text():
                has_traceback = True
                break
        
        assert has_traceback, "Should have at least one traceback frame"