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