#!/usr/bin/env python3
"""
Test to reproduce and verify fix for: filtering causes expanded children to disappear.
This is a critical bug where applying filters makes exception/stack/extra info children vanish.
"""

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


class TestFilteringChildrenDisappear:
    """Test cases for the critical filtering bug where children disappear."""
    
    # QApplication fixture provided by conftest.py
    
    def test_filtering_preserves_expanded_children(self, qapp):
        """
        CRITICAL BUG TEST: Test that filtering does not cause expanded children to disappear.
        
        This test verifies the fix for the bug where applying filters would cause
        previously expanded exception/stack/extra info children to vanish from the UI.
        """
        viewer = LogViewer(logger='test.children.disappear')
        logger = logging.getLogger('test.children.disappear')
        logger.setLevel(logging.DEBUG)
        
        # Add a simple log message
        logger.info("Simple info message")
        
        # Add an error with exception info that will create children
        try:
            raise ValueError("Test exception for children")
        except Exception:
            logger.error("Error with exception", exc_info=True, extra={
                'user_id': 12345,
                'request_data': {'method': 'POST', 'path': '/api/test'},
                'nested_info': {
                    'database': {'connections': 5, 'queries': 23},
                    'cache': {'hits': 45, 'misses': 3}
                }
            })
        
        # Add another simple message
        logger.warning("Warning message")
        
        # Verify we have 3 main log entries
        assert viewer.model.rowCount() == 3, f"Expected 3 log entries, got {viewer.model.rowCount()}"
        
        # Find the error entry (should be the second one, with level ERROR=40)
        error_item = None
        error_row = -1
        for i in range(viewer.model.rowCount()):
            level_item = viewer.model.item(i, LogColumns.LEVEL)
            if level_item and level_item.data(ItemDataRole.LEVEL_NUMBER) == 40:  # ERROR level
                error_item = viewer.model.item(i, LogColumns.TIMESTAMP)
                error_row = i
                break
        
        assert error_item is not None, "Should find error item"
        print(f"Found error item at row {error_row}")
        
        # Check if it has a loading placeholder (indicates expandable content)
        has_placeholder = viewer.model.has_loading_placeholder(error_item)
        print(f"Error item has loading placeholder: {has_placeholder}")
        
        if has_placeholder:
            # Expand the error item to reveal its children
            print("Expanding error item to load children...")
            viewer.model.replace_placeholder_with_content(error_item)
        
        # Count children after expansion
        children_count_before = error_item.rowCount()
        print(f"Children count after expansion: {children_count_before}")
        assert children_count_before > 0, f"Should have children after expansion, got {children_count_before}"
        
        # Get some details about the children for verification
        child_types = []
        for i in range(children_count_before):
            child = error_item.child(i, LogColumns.TIMESTAMP)
            if child:
                child_data = child.data(ItemDataRole.PYTHON_DATA)
                if child_data and isinstance(child_data, dict):
                    child_types.append(child_data.get('type', 'unknown'))
                else:
                    child_types.append('no_data')
        
        print(f"Child types before filtering: {child_types}")
        
        # Now apply a filter that should INCLUDE the error message
        print("Applying level filter that should include ERROR level...")
        viewer.apply_filters(['level: error'])
        
        # Check what's visible in the filtered model
        filtered_model = viewer.tree.model()
        visible_rows = filtered_model.rowCount()
        print(f"Visible rows after filtering: {visible_rows}")
        
        # The error message should still be visible
        assert visible_rows >= 1, f"Should have at least 1 visible row (the error), got {visible_rows}"
        
        # Find the error item in the filtered model
        filtered_error_item = None
        filtered_error_index = None
        for i in range(visible_rows):
            index = filtered_model.index(i, LogColumns.LEVEL)
            level_num = filtered_model.data(index, ItemDataRole.LEVEL_NUMBER)
            if level_num == 40:  # ERROR level
                filtered_error_index = filtered_model.index(i, LogColumns.TIMESTAMP)
                filtered_error_item = filtered_model.itemFromIndex(filtered_error_index) if hasattr(filtered_model, 'itemFromIndex') else None
                break
        
        print(f"Found filtered error item: {filtered_error_item is not None}")
        
        # THIS IS THE CRITICAL TEST: The children should still be there after filtering
        if filtered_error_index:
            children_count_after = filtered_model.rowCount(filtered_error_index)
            print(f"Children count after filtering: {children_count_after}")
            
            # Get child details after filtering for comparison
            child_types_after = []
            for i in range(children_count_after):
                child_index = filtered_model.index(i, LogColumns.TIMESTAMP, filtered_error_index)
                if hasattr(filtered_model, 'data'):
                    child_data = filtered_model.data(child_index, ItemDataRole.PYTHON_DATA)
                    if child_data and isinstance(child_data, dict):
                        child_types_after.append(child_data.get('type', 'unknown'))
                    else:
                        child_types_after.append('no_data')
            
            print(f"Child types after filtering: {child_types_after}")
            
            # This is the assertion that should FAIL if the bug exists
            assert children_count_after == children_count_before, \
                f"Children disappeared after filtering! Before: {children_count_before}, After: {children_count_after}"
            
            assert child_types_after == child_types, \
                f"Child types changed after filtering! Before: {child_types}, After: {child_types_after}"
        else:
            # If we can't access the filtered item directly, this is also a problem
            pytest.fail("Could not access error item children through filtered model")
        
        print("✅ Test passed: Children preserved after filtering!")
    
    def test_multiple_expansions_with_filtering(self, qapp):
        """Test that multiple expanded items maintain their children after filtering."""
        viewer = LogViewer(logger='test.multiple.expansions')
        logger = logging.getLogger('test.multiple.expansions')
        logger.setLevel(logging.DEBUG)
        
        # Add multiple error messages with expandable content
        for i in range(3):
            try:
                raise RuntimeError(f"Test error {i}")
            except Exception:
                logger.error(f"Error message {i}", exc_info=True, extra={
                    'error_id': i,
                    'context': {'operation': f'op_{i}', 'data': {'value': i * 10}}
                })
        
        assert viewer.model.rowCount() == 3, "Should have 3 error entries"
        
        # Expand all error items that have children
        expanded_items = []
        children_counts_before = []
        
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if viewer.model.has_loading_placeholder(item):
                print(f"Expanding error item {i}...")
                viewer.model.replace_placeholder_with_content(item)
                children_count = item.rowCount()
                expanded_items.append(item)
                children_counts_before.append(children_count)
                print(f"Item {i} has {children_count} children after expansion")
        
        assert len(expanded_items) > 0, "Should have at least one expandable item"
        print(f"Expanded {len(expanded_items)} items with children: {children_counts_before}")
        
        # Apply filtering
        viewer.apply_filters(['level: error'])
        
        # Check that all expanded items still have their children
        filtered_model = viewer.tree.model()
        visible_rows = filtered_model.rowCount()
        
        assert visible_rows == len(expanded_items), \
            f"Should have {len(expanded_items)} visible error rows, got {visible_rows}"
        
        # Verify each visible item has the same number of children
        for i in range(visible_rows):
            error_index = filtered_model.index(i, LogColumns.TIMESTAMP)
            children_count_after = filtered_model.rowCount(error_index)
            
            # This should match the corresponding pre-filter count
            expected_count = children_counts_before[i] if i < len(children_counts_before) else 0
            
            assert children_count_after == expected_count, \
                f"Item {i}: children count mismatch. Before: {expected_count}, After: {children_count_after}"
        
        print("✅ Multiple expansions test passed: All children preserved!")


def run_tests():
    """Run the children disappear tests."""
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    test_instance = TestFilteringChildrenDisappear()
    
    try:
        print("Testing filtering children disappear bug...")
        test_instance.test_filtering_preserves_expanded_children(qapp)
        test_instance.test_multiple_expansions_with_filtering(qapp)
        print("\n🎉 All tests passed!")
        return True
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up Qt application
        if qapp:
            qapp.processEvents()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)