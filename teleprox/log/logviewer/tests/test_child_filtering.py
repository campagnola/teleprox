import logging
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


class TestChildFiltering:
    """Test cases for child filtering and expansion state preservation."""
    
    # QApplication fixture provided by conftest.py
    
    def test_children_visible_when_parent_matches_filter(self, qapp):
        """Test that exception children are visible when parent matches filter."""
        viewer = LogViewer(logger='test.children.visible')
        logger = logging.getLogger('test.children.visible')
        logger.setLevel(logging.DEBUG)
        
        # Add messages at different levels
        logger.debug("Debug message")
        logger.info("Info message")
        
        # Add an error with exception details and extra attributes
        try:
            raise ValueError("Test exception for filtering")
        except Exception:
            logger.error("Error message with exception", exc_info=True, extra={
                'user_id': 12345,
                'session_data': {'ip': '192.168.1.1', 'browser': 'Chrome'},
                'tags': ['auth', 'security']
            })
        
        logger.warning("Warning message")
        
        assert viewer.model.rowCount() == 4, "Should have 4 log entries"
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, 0)
            if item.rowCount() > 0:  # Has expandable content
                exception_item = item
                break
        
        # Expand exception details using UI
        source_index = viewer.model.indexFromItem(exception_item)
        tree_index = viewer.map_index_from_model(source_index)
        viewer.tree.expand(tree_index)
        child_count = exception_item.rowCount()
        assert child_count > 0, "Should have exception children"
        
        # Recursively count all children and grandchildren
        def count_all_descendants(item):
            total = item.rowCount()
            for i in range(item.rowCount()):
                child = item.child(i, LogColumns.TIMESTAMP)
                if child:
                    total += count_all_descendants(child)
            return total
        
        total_descendants = count_all_descendants(exception_item)
        
        # Apply ERROR level filter
        viewer.apply_filters(['level: error'])
        
        # Check that filtered model shows the error entry
        current_model = viewer.tree.model()
        visible_rows = current_model.rowCount() if current_model else 0
        assert visible_rows >= 1, "Should have at least the error entry visible"
        
        # Check that the error entry has visible children in filtered view
        error_index = current_model.index(0, 0)  # First (and likely only) visible row
        visible_children = current_model.rowCount(error_index)
        assert visible_children > 0, f"Should have visible children after filtering, got {visible_children}"
        
        # The core user behavior: exception content should be visible in children
        # Check that at least one child contains exception information
        found_exception_content = False
        for i in range(visible_children):
            child_index = current_model.index(i, 0, error_index)
            child_text = current_model.data(child_index, qt.Qt.DisplayRole) or ""
            if "Exception" in child_text or "ValueError" in child_text or "user_id" in child_text:
                found_exception_content = True
                break
        
        assert found_exception_content, "Should have exception-related content visible in children after filtering"
    
    def test_expansion_state_preserved_across_filters(self, qapp):
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
            if item.rowCount() > 0:  # Has expandable content
                exception_item = item
                error_row = i
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception using UI
        source_index = viewer.model.indexFromItem(exception_item)
        error_tree_index = viewer.map_index_from_model(source_index)
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
        
        # The core user behavior: item should still be expanded after filtering
        new_model = viewer.tree.model()
        new_error_index = new_model.index(0, 0)  # Should be first visible item
        
        # Most importantly, verify the item is still expanded in the UI
        assert viewer.tree.isExpanded(new_error_index), "Error item should still be expanded after filtering"
        
        # And verify children are still accessible
        visible_children = new_model.rowCount(new_error_index)
        assert visible_children > 0, "Should have visible children after filtering"
        
        # Clear filter and verify children are still accessible
        viewer.apply_filters([])
        
        # Find the error item again by LOG_ID (check in correct column)
        final_model = viewer.tree.model()
        error_found = False
        for i in range(final_model.rowCount()):
            idx = final_model.index(i, 0)
            # LOG_ID is stored in column 0 (timestamp), so this check is correct
            item_log_id = final_model.data(idx, ItemDataRole.LOG_ID)
            if item_log_id == log_id:
                error_found = True
                children_accessible = final_model.rowCount(idx)
                assert children_accessible == child_count, "Should have same number of children after clearing filter"
                break
        
        assert error_found, "Should have found the error item with original LOG_ID"
    
    def test_multiple_expanded_items_with_filtering(self, qapp):
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
            if item.rowCount() > 0:  # Has expandable content
                viewer.expandItem(item)
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


def run_manual_tests():
    """Run basic tests without pytest."""
    # Create QApplication for manual testing (conftest.py only works in pytest)
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    print("Test 1: Children visible when parent matches filter...")
    test = TestChildFiltering()
    test.test_children_visible_when_parent_matches_filter(qapp)
    print("✅ Test 1 passed!")
    
    print("Test 2: Expansion state preserved across filters...")
    test.test_expansion_state_preserved_across_filters(qapp)
    print("✅ Test 2 passed!")
    
    print("Test 3: Multiple expanded items with filtering...")
    test.test_multiple_expanded_items_with_filtering(qapp)
    print("✅ Test 3 passed!")
    
    print("All child filtering tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()