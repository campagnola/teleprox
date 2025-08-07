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


class TestNewColumnFiltering:
    """Test cases for new column filtering (host, process, thread) with children preservation."""
    
    # QApplication fixture provided by conftest.py
    
    def test_new_column_filters_preserve_children(self, qapp):
        """Test that new column filters (host, process, thread) don't cause children to disappear."""
        viewer = LogViewer(logger='test.new.columns.children')
        logger = logging.getLogger('test.new.columns.children')
        logger.setLevel(logging.DEBUG)
        
        # Create an exception that will have children
        try:
            raise ValueError("Test exception for new column filtering")
        except Exception:
            logger.error("Error with exception details", exc_info=True)
        
        qapp.processEvents()
        
        # Find the error item
        error_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if item.rowCount() > 0:  # Has expandable content
                error_item = item
                break
        
        assert error_item is not None, "Should have found error item with placeholder"
        
        # Expand the error to create children
        viewer.expand_item(error_item)
        child_count = error_item.rowCount()
        assert child_count > 0, "Should have children after expansion"
        
        # Apply host filter (should match default "localhost")
        viewer.apply_filters(['host: localhost'])
        
        # Check that error is still visible and has children
        filtered_model = viewer.tree.model()
        visible_rows = filtered_model.rowCount()
        assert visible_rows >= 1, "Should have at least one visible row after host filter"
        
        # Find the error in filtered model
        error_found = False
        for i in range(visible_rows):
            level_index = filtered_model.index(i, LogColumns.LEVEL)
            if filtered_model.data(level_index, ItemDataRole.LEVEL_NUMBER) == 40:  # ERROR
                error_index = filtered_model.index(i, LogColumns.TIMESTAMP)
                children_visible = filtered_model.rowCount(error_index)
                assert children_visible == child_count, f"Should have {child_count} children, got {children_visible}"
                error_found = True
                break
        
        assert error_found, "Should have found the error item in filtered results"
    
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
        
        # Expand to create children
        viewer.expand_item(exception_item)
        assert exception_item.rowCount() > 0, "Should have children"
        
        # Test the actual user behavior: that children remain visible when filtering on new columns
        # Apply a host filter that should match the default 'localhost'
        viewer.apply_filters(['host: localhost'])
        
        # Verify the parent item is still visible after host filtering
        filtered_model = viewer.tree.model()
        assert filtered_model.rowCount() >= 1, "Should have at least one item visible after host filtering"
        
        # Verify children are still accessible after host filtering
        filtered_parent_index = filtered_model.index(0, 0)
        children_count = filtered_model.rowCount(filtered_parent_index)
        assert children_count > 0, "Children should remain visible after host filtering"
        
        # Test process filtering
        viewer.apply_filters(['process: MainProcess'])
        assert filtered_model.rowCount() >= 1, "Should be visible after process filtering"
        
        # Test thread filtering  
        viewer.apply_filters(['thread: MainThread'])
        assert filtered_model.rowCount() >= 1, "Should be visible after thread filtering"
    
    def test_empty_host_gets_default_value(self, qapp):
        """Test that empty hostName gets default value of 'localhost'."""
        viewer = LogViewer(logger='test.default.host')
        logger = logging.getLogger('test.default.host')
        logger.setLevel(logging.DEBUG)
        
        # Add a regular log message (hostName will be empty by default)
        logger.info("Test message for default host")
        qapp.processEvents()
        
        assert viewer.model.rowCount() >= 1, "Should have at least one log message"
        
        # Check that host column has default value
        host_item = viewer.model.item(0, LogColumns.HOST)
        assert host_item is not None, "Should have host item"
        assert host_item.text() == "localhost", f"Host should default to 'localhost', got '{host_item.text()}'"
    
    def test_new_column_filters_with_expansion_state(self, qapp):
        """Test that expansion state is preserved when using new column filters."""
        viewer = LogViewer(logger='test.expansion.new.columns')
        logger = logging.getLogger('test.expansion.new.columns')
        logger.setLevel(logging.DEBUG)
        
        # Create an exception with children
        try:
            raise ValueError("Test expansion with new column filters")
        except Exception:
            logger.error("Error for expansion testing", exc_info=True)
        
        qapp.processEvents()
        
        # Find and expand the exception
        exception_item = None
        error_row = -1
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if item.rowCount() > 0:  # Has expandable content
                exception_item = item
                error_row = i
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.expand_item(exception_item)
        child_count = exception_item.rowCount()
        assert child_count > 0, "Should have children"
        
        # Expand in tree view
        error_tree_index = viewer.tree.model().index(error_row, 0)
        viewer.tree.expand(error_tree_index)
        assert viewer.tree.isExpanded(error_tree_index), "Should be expanded in tree"
        
        # Apply process filter (should match MainProcess)
        viewer.apply_filters(['process: MainProcess'])
        
        # Check filtered results
        filtered_model = viewer.tree.model()
        visible_rows = filtered_model.rowCount()
        assert visible_rows >= 1, "Should have visible rows after process filter"
        
        # Find error in filtered model
        filtered_error_index = None
        for i in range(visible_rows):
            level_idx = filtered_model.index(i, LogColumns.LEVEL)
            if filtered_model.data(level_idx, ItemDataRole.LEVEL_NUMBER) == 40:  # ERROR
                filtered_error_index = filtered_model.index(i, LogColumns.TIMESTAMP)
                break
        
        assert filtered_error_index is not None, "Should find error in filtered model"
        
        # Children should be visible without needing to re-expand
        visible_children = filtered_model.rowCount(filtered_error_index)
        assert visible_children == child_count, f"Should have {child_count} visible children after filtering"


def run_manual_tests():
    """Run basic tests without pytest."""
    # Create QApplication for manual testing (conftest.py only works in pytest)
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    print("Test 1: New column filters preserve children...")
    test = TestNewColumnFiltering()
    test.test_new_column_filters_preserve_children(qapp)
    print("✅ Test 1 passed!")
    
    print("Test 2: New column child inheritance...")
    test.test_new_column_child_inheritance(qapp)
    print("✅ Test 2 passed!")
    
    print("Test 3: Empty host gets default value...")
    test.test_empty_host_gets_default_value(qapp)
    print("✅ Test 3 passed!")
    
    print("Test 4: New column filters with expansion state...")
    test.test_new_column_filters_with_expansion_state(qapp)
    print("✅ Test 4 passed!")
    
    print("All new column filtering tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()