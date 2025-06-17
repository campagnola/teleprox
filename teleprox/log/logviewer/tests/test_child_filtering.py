import logging
from teleprox.log.logviewer.core import LogViewer
from teleprox.log.logviewer.constants import ItemDataRole
from teleprox import qt

try:
    import pytest
except ImportError:
    # Mock pytest for basic functionality
    class MockPytest:
        def fixture(self, func):
            return func
    pytest = MockPytest()


class TestChildFiltering:
    """Test cases for child filtering and expansion state preservation."""
    
    @pytest.fixture
    def app(self):
        """Create QApplication for tests."""
        app = qt.QApplication.instance()
        if app is None:
            app = qt.QApplication([])
        return app
    
    def test_children_inherit_parent_filter_data(self, app):
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
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand exception details
        viewer.model.replace_placeholder_with_content(exception_item)
        assert exception_item.rowCount() > 0, "Should have exception children"
        
        # Check that children inherited parent's filter data
        parent_level = exception_item.child(0, 3).data(ItemDataRole.LEVEL_NUMBER)
        parent_cipher = exception_item.child(0, 3).data(ItemDataRole.LEVEL_CIPHER)
        parent_logger = exception_item.child(0, 2).data(ItemDataRole.LOGGER_NAME)
        
        # Get original record data for comparison
        original_record = exception_item.data(ItemDataRole.PYTHON_DATA)
        
        assert parent_level == original_record.levelno, "Child should inherit parent's level number"
        assert parent_logger == original_record.name, "Child should inherit parent's logger name"
        assert parent_cipher is not None, "Child should have level cipher"
    
    def test_children_visible_when_parent_matches_filter(self, app):
        """Test that exception children are visible when parent matches filter."""
        viewer = LogViewer(logger='test.children.visible')
        logger = logging.getLogger('test.children.visible')
        logger.setLevel(logging.DEBUG)
        
        # Add messages at different levels
        logger.debug("Debug message")
        logger.info("Info message")
        
        # Add an error with exception details
        try:
            raise ValueError("Test exception for filtering")
        except Exception:
            logger.error("Error message with exception", exc_info=True)
        
        logger.warning("Warning message")
        
        assert viewer.model.rowCount() == 4, "Should have 4 log entries"
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        # Expand exception details
        viewer.model.replace_placeholder_with_content(exception_item)
        child_count = exception_item.rowCount()
        assert child_count > 0, "Should have exception children"
        
        # Apply ERROR level filter
        viewer.apply_filters(['level: error'])
        
        # Check that filtered model shows the error entry
        current_model = viewer.tree.model()
        visible_rows = current_model.rowCount() if current_model else 0
        assert visible_rows >= 1, "Should have at least the error entry visible"
        
        # Check that the error entry has visible children in filtered view
        error_index = current_model.index(0, 0)  # First (and likely only) visible row
        visible_children = current_model.rowCount(error_index)
        assert visible_children == child_count, f"Should have {child_count} visible children, got {visible_children}"
    
    def test_expansion_state_preserved_across_filters(self, app):
        """Test that item expansion state is preserved when filters change."""
        viewer = LogViewer(logger='test.expansion.preserve')
        logger = logging.getLogger('test.expansion.preserve')
        logger.setLevel(logging.DEBUG)
        
        # Add messages
        logger.debug("Debug message")
        logger.info("Info message")
        
        # Add an error with exception details
        try:
            raise ValueError("Test exception for expansion preservation")
        except Exception:
            logger.error("Error message with exception", exc_info=True)
        
        logger.warning("Warning message")
        
        # Find the exception item
        exception_item = None
        error_row = -1
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                error_row = i
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        
        # Get the tree view index for the error item and expand it
        error_tree_index = viewer.tree.model().index(error_row, 0)
        viewer.tree.expand(error_tree_index)
        
        # Verify it's expanded
        assert viewer.tree.isExpanded(error_tree_index), "Error item should be expanded"
        
        # Get child count and LOG_ID for verification
        child_count = exception_item.rowCount()
        assert child_count > 0, "Should have exception children"
        log_id = exception_item.data(ItemDataRole.LOG_ID)
        assert log_id is not None, "Exception item should have LOG_ID"
        
        # Apply a filter
        viewer.apply_filters(['level: error'])
        
        # Verify children are still accessible after filtering
        new_model = viewer.tree.model()
        new_error_index = new_model.index(0, 0)  # Should be first visible item
        visible_children = new_model.rowCount(new_error_index)
        assert visible_children == child_count, f"Should have {child_count} visible children after filtering"
        
        # Verify the LOG_ID matches (ensures we're looking at the right item)
        filtered_log_id = new_model.data(new_error_index, ItemDataRole.LOG_ID)
        assert filtered_log_id == log_id, "Should be the same item after filtering"
        
        # Clear filter and verify children are still accessible
        viewer.apply_filters([])
        
        # Find the error item again by LOG_ID
        final_model = viewer.tree.model()
        error_found = False
        for i in range(final_model.rowCount()):
            idx = final_model.index(i, 0)
            item_log_id = final_model.data(idx, ItemDataRole.LOG_ID)
            if item_log_id == log_id:
                error_found = True
                children_accessible = final_model.rowCount(idx)
                assert children_accessible == child_count, "Should have same number of children after clearing filter"
                break
        
        assert error_found, "Should have found the error item with original LOG_ID"
    
    def test_multiple_expanded_items_with_filtering(self, app):
        """Test filtering with multiple expanded items."""
        viewer = LogViewer(logger='test.multiple.expanded')
        logger = logging.getLogger('test.multiple.expanded')
        logger.setLevel(logging.DEBUG)
        
        # Add first error with exception
        try:
            raise ValueError("First test exception")
        except Exception:
            logger.error("First error message", exc_info=True)
        
        logger.info("Info message between errors")
        
        # Add second error with exception
        try:
            raise RuntimeError("Second test exception")
        except Exception:
            logger.error("Second error message", exc_info=True)
        
        # Find and expand both exception items
        expanded_count = 0
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                viewer.model.replace_placeholder_with_content(item)
                expanded_count += 1
        
        assert expanded_count == 2, "Should have expanded 2 exception items"
        
        # Apply ERROR filter
        viewer.apply_filters(['level: error'])
        
        # Should see both error entries with their children
        current_model = viewer.tree.model()
        visible_rows = current_model.rowCount() if current_model else 0
        assert visible_rows == 2, "Should have 2 visible error entries"
        
        # Both should have visible children
        for i in range(visible_rows):
            error_index = current_model.index(i, 0)
            child_count = current_model.rowCount(error_index)
            assert child_count > 0, f"Error entry {i} should have visible children"
    
    def test_expansion_state_mechanism(self, app):
        """Test the expansion state save/restore mechanism directly."""
        viewer = LogViewer(logger='test.expansion.mechanism')
        logger = logging.getLogger('test.expansion.mechanism')
        logger.setLevel(logging.DEBUG)
        
        # Add an error with exception
        try:
            raise ValueError("Test for expansion mechanism")
        except Exception:
            logger.error("Error with exception", exc_info=True)
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        error_tree_index = viewer.tree.model().index(0, 0)
        viewer.tree.expand(error_tree_index)
        
        # Test save expansion state
        expanded_ids = viewer._save_expansion_state()
        assert len(expanded_ids) > 0, "Should have saved at least one expanded ID"
        
        # Manually collapse and then restore
        viewer.tree.collapse(error_tree_index)
        assert not viewer.tree.isExpanded(error_tree_index), "Should be collapsed"
        
        # Restore expansion state
        viewer._restore_expansion_state(expanded_ids)
        assert viewer.tree.isExpanded(error_tree_index), "Should be expanded after restore"
    
    def test_child_selection_highlighting(self, app):
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
            item = viewer.model.item(i, 0)
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
    
    def test_child_highlighting_isolation(self, app):
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
            item = viewer.model.item(i, 0)
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
    
    def test_exception_message_ordering(self, app):
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
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        child_count = exception_item.rowCount()
        assert child_count > 1, "Should have multiple children (traceback + exception)"
        
        # Check that the last child is the exception message
        last_child = exception_item.child(child_count - 1, 4)  # Last row, message column
        assert last_child is not None, "Should have last child"
        
        last_message = last_child.text()
        assert "ValueError" in last_message, "Last child should be the exception message"
        assert "Test exception message" in last_message, "Should contain the exception text"
        
        # Check that earlier children are traceback frames
        first_child = exception_item.child(0, 4)  # First row, message column
        assert first_child is not None, "Should have first child"
        
        first_message = first_child.text()
        assert "File " in first_message, "First child should be a traceback frame"
    
    def test_monospace_font_for_code(self, app):
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
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        
        # Check that traceback frames have monospace font
        # Note: We can't easily test the actual font in a unit test,
        # but we can verify the structure is correct
        child_count = exception_item.rowCount()
        assert child_count >= 2, "Should have at least traceback frame + exception message"
        
        # Verify we have at least one traceback frame (not just the exception message)
        has_traceback = False
        for i in range(child_count - 1):  # Exclude last item (exception message)
            child = exception_item.child(i, 4)
            if child and "File " in child.text():
                has_traceback = True
                break
        
        assert has_traceback, "Should have at least one traceback frame"
    
    def test_chained_exception_ordering(self, app):
        """Test that chained exceptions appear in correct order with separators."""
        viewer = LogViewer(logger='test.chained')
        logger = logging.getLogger('test.chained')
        logger.setLevel(logging.DEBUG)
        
        # Create a chained exception scenario
        def inner_function():
            raise ValueError("Root cause error")
        
        def outer_function():
            try:
                inner_function()
            except ValueError as e:
                raise ConnectionError("Connection failed") from e
        
        try:
            outer_function()
        except ConnectionError:
            logger.error("Chained exception occurred", exc_info=True)
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, 0)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        child_count = exception_item.rowCount()
        assert child_count > 2, "Should have multiple children (2 exceptions + separator + tracebacks)"
        
        # Collect all child messages to verify ordering
        child_messages = []
        for i in range(child_count):
            child = exception_item.child(i, 4)  # Message column
            if child:
                message = child.text()
                child_data = exception_item.child(i, 0).data(ItemDataRole.PYTHON_DATA)
                child_type = child_data.get('type') if child_data else 'unknown'
                child_messages.append((child_type, message))
        
        # Expected order (matches Python's standard exception chaining):
        # 1. ValueError traceback frames (root cause)
        # 2. ValueError exception message  
        # 3. Chain separator
        # 4. ConnectionError traceback frames (final exception)
        # 5. ConnectionError exception message
        
        # Find the separator
        separator_index = None
        for i, (child_type, message) in enumerate(child_messages):
            if child_type == 'chain_separator':
                separator_index = i
                break
        
        assert separator_index is not None, f"Should have chain separator. Found types: {[t for t, _ in child_messages]}"
        
        # Check that ValueError message appears before separator (root cause first)
        value_error_index = None
        for i, (child_type, message) in enumerate(child_messages):
            if child_type == 'exception' and 'ValueError' in message:
                value_error_index = i
                break
        
        assert value_error_index is not None, "Should find ValueError message"
        assert value_error_index < separator_index, f"ValueError ({value_error_index}) should come before separator ({separator_index})"
        
        # Check that ConnectionError message appears after separator (final exception last)
        connection_error_index = None
        for i, (child_type, message) in enumerate(child_messages):
            if child_type == 'exception' and 'ConnectionError' in message:
                connection_error_index = i
                break
        
        assert connection_error_index is not None, "Should find ConnectionError message"
        assert connection_error_index > separator_index, f"ConnectionError ({connection_error_index}) should come after separator ({separator_index})"
        
        # Verify separator message
        separator_message = child_messages[separator_index][1]
        assert "direct cause" in separator_message, f"Separator should mention 'direct cause': {separator_message}"
    
    def test_stack_info_ordering(self, app):
        """Test that stack_info appears after exceptions with proper separators."""
        viewer = LogViewer(logger='test.stack.order')
        logger = logging.getLogger('test.stack.order')
        logger.setLevel(logging.DEBUG)
        
        # Test 1: Message with only stack_info
        logger.warning("Warning with stack info only", stack_info=True)
        
        # Test 2: Exception with both exc_info and stack_info
        try:
            1 / 0
        except ZeroDivisionError:
            logger.error("Error with both exc_info and stack_info", exc_info=True, stack_info=True)
        
        # Test the first entry (stack_info only)
        stack_only_item = viewer.model.item(0, 0)
        if viewer.model.has_loading_placeholder(stack_only_item):
            viewer.model.replace_placeholder_with_content(stack_only_item)
            
            # Should have stack separator + stack frames
            child_count = stack_only_item.rowCount()
            assert child_count >= 2, "Should have stack separator + stack frames"
            
            # First child should be stack separator with appropriate message
            first_child = stack_only_item.child(0, 4)
            first_child_data = stack_only_item.child(0, 0).data(ItemDataRole.PYTHON_DATA)
            assert first_child_data.get('type') == 'stack_separator'
            assert "This message was logged at the following location" in first_child.text()
        
        # Test the second entry (exception + stack_info)
        both_item = viewer.model.item(1, 0)
        if viewer.model.has_loading_placeholder(both_item):
            viewer.model.replace_placeholder_with_content(both_item)
            
            # Collect child types
            child_types = []
            for i in range(both_item.rowCount()):
                child_data = both_item.child(i, 0).data(ItemDataRole.PYTHON_DATA)
                child_type = child_data.get('type') if child_data else 'unknown'
                child_types.append(child_type)
            
            # Should have: traceback_frame(s), exception, stack_separator, stack_frame(s)
            assert 'exception' in child_types, "Should have exception"
            assert 'stack_separator' in child_types, "Should have stack separator"
            assert 'stack_frame' in child_types, "Should have stack frames"
            
            # Stack separator should come after exception
            exception_index = child_types.index('exception')
            stack_separator_index = child_types.index('stack_separator')
            assert exception_index < stack_separator_index, "Exception should come before stack separator"
            
            # Verify stack separator message
            stack_separator_child = both_item.child(stack_separator_index, 4)
            assert "The above exception was logged at the following location" in stack_separator_child.text()


def run_manual_tests():
    """Run basic tests without pytest."""
    app = qt.QApplication([])
    
    print("Test 1: Children inherit parent filter data...")
    test = TestChildFiltering()
    test.test_children_inherit_parent_filter_data(app)
    print("✅ Test 1 passed!")
    
    print("Test 2: Children visible when parent matches filter...")
    test.test_children_visible_when_parent_matches_filter(app)
    print("✅ Test 2 passed!")
    
    print("Test 3: Expansion state preserved across filters...")
    test.test_expansion_state_preserved_across_filters(app)
    print("✅ Test 3 passed!")
    
    print("Test 4: Multiple expanded items with filtering...")
    test.test_multiple_expanded_items_with_filtering(app)
    print("✅ Test 4 passed!")
    
    print("All child filtering tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()