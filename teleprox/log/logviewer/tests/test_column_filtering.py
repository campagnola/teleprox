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
        
        # Find and expand the exception
        exception_item = None
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand to create children
        viewer.model.replace_placeholder_with_content(exception_item)
        original_child_count = exception_item.rowCount()
        assert original_child_count > 0, "Should have exception children"
        
        # Test all new column filters
        test_filters = [
            'host: localhost',
            'process: MainProcess', 
            'thread: MainThread'
        ]
        
        for filter_expr in test_filters:
            # Apply filter
            viewer.apply_filters([filter_expr])
            qapp.processEvents()
            
            # Check that parent is still visible
            filtered_model = viewer.tree.model()
            assert filtered_model.rowCount() >= 1, f"Should have visible rows with filter: {filter_expr}"
            
            # Find the exception item in filtered view
            exception_found = False
            for row in range(filtered_model.rowCount()):
                idx = filtered_model.index(row, LogColumns.TIMESTAMP)
                log_id = filtered_model.data(idx, ItemDataRole.LOG_ID)
                original_log_id = exception_item.data(ItemDataRole.LOG_ID)
                
                if log_id == original_log_id:
                    exception_found = True
                    # Check that children are still visible
                    visible_children = filtered_model.rowCount(idx)
                    assert visible_children == original_child_count, \
                        f"Filter '{filter_expr}': Should have {original_child_count} children, got {visible_children}"
                    break
            
            assert exception_found, f"Should find exception item with filter: {filter_expr}"
            
            # Clear filter for next test
            viewer.apply_filters([])
            qapp.processEvents()
    
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
    
    def test_empty_host_gets_default_value(self, qapp):
        """Test that empty hostName gets default value of 'localhost'."""
        viewer = LogViewer(logger='test.default.host')
        logger = logging.getLogger('test.default.host')
        logger.setLevel(logging.DEBUG)
        
        # Add a regular log message (hostName will be empty by default)
        logger.info("Test message for default host")
        qapp.processEvents()
        
        assert viewer.model.rowCount() > 0, "Should have log entries"
        
        # Check that host column has default value
        host_item = viewer.model.item(0, LogColumns.HOST)
        assert host_item is not None, "Should have host column item"
        
        host_text = host_item.text()
        assert host_text == 'localhost', f"Empty hostName should default to 'localhost', got '{host_text}'"
    
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
        
        # Find and expand exception
        exception_item = None
        exception_row = -1
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                exception_item = item
                exception_row = i
                break
        
        assert exception_item is not None, "Should have found exception item"
        
        # Expand the exception
        viewer.model.replace_placeholder_with_content(exception_item)
        child_count = exception_item.rowCount()
        assert child_count > 0, "Should have children"
        
        # Manually expand in tree view
        error_tree_index = viewer.tree.model().index(exception_row, LogColumns.TIMESTAMP)
        viewer.tree.expand(error_tree_index)
        assert viewer.tree.isExpanded(error_tree_index), "Should be expanded"
        
        # Apply new column filter
        viewer.apply_filters(['host: localhost'])
        qapp.processEvents()
        
        # Check that item is still expanded and children are visible
        filtered_model = viewer.tree.model()
        filtered_error_index = filtered_model.index(0, LogColumns.TIMESTAMP)  # Should be first item
        
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