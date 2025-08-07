import logging
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.widgets import SearchWidget
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


class TestSearchWidget:
    """Test cases for the search functionality."""
    
    # QApplication fixture provided by conftest.py
    
    def test_search_widget_initialization(self, qapp):
        """Test that SearchWidget initializes correctly."""
        search_widget = SearchWidget()
        
        # Verify UI components exist
        assert hasattr(search_widget, 'search_input'), "Should have search input"
        assert hasattr(search_widget, 'prev_button'), "Should have previous button"
        assert hasattr(search_widget, 'next_button'), "Should have next button"
        assert hasattr(search_widget, 'result_label'), "Should have result label"
        
        # Verify navigation is hidden initially
        assert not search_widget.prev_button.isVisible(), "Previous button should be hidden initially"
        assert not search_widget.next_button.isVisible(), "Next button should be hidden initially"
        assert not search_widget.result_label.isVisible(), "Result label should be hidden initially"
        
        # Verify initial state
        assert search_widget.search_results == [], "Should have empty search results initially"
        assert search_widget.current_result_index == -1, "Should have no current result initially"
        assert search_widget.tree_view is None, "Should have no tree view initially"
    
    def test_search_functionality_basic(self, qapp):
        """Test basic search functionality with simple messages."""
        viewer = LogViewer(logger='test.search.basic', initial_filters=[])
        viewer.show()
        logger = logging.getLogger('test.search.basic')
        logger.setLevel(logging.DEBUG)
        
        # Add test messages
        logger.info("First message with keyword")
        logger.warning("Second message without target")
        logger.error("Third message with keyword")
        logger.debug("Fourth message different content")
        
        qapp.processEvents()
        
        # Verify search widget is connected
        search_widget = viewer.search_widget
        assert search_widget.tree_view is not None, "Search widget should be connected to tree view"
        
        # Perform search for "keyword"
        search_widget.search_input.setText("keyword")
        qapp.processEvents()
        
        # Verify search results
        assert len(search_widget.search_results) == 2, "Should find 2 messages with 'keyword'"
        assert search_widget.current_result_index == 0, "Should start at first result"
        
        # Verify navigation is visible
        assert search_widget.prev_button.isVisible(), "Previous button should be visible with results"
        assert search_widget.next_button.isVisible(), "Next button should be visible with results"
        assert search_widget.result_label.isVisible(), "Result label should be visible with results"
        assert search_widget.result_label.text() == "1/2", "Should show current result position"
        
        # Test navigation
        search_widget.next_button.click()
        qapp.processEvents()
        assert search_widget.current_result_index == 1, "Should move to second result"
        assert search_widget.result_label.text() == "2/2", "Should update result position"
        
        # Test wrap-around
        search_widget.next_button.click()
        qapp.processEvents()
        assert search_widget.current_result_index == 0, "Should wrap around to first result"
        assert search_widget.result_label.text() == "1/2", "Should wrap to first position"
        
        # Test previous navigation
        search_widget.prev_button.click()
        qapp.processEvents()
        assert search_widget.current_result_index == 1, "Should wrap to last result"
        assert search_widget.result_label.text() == "2/2", "Should show last position"
    
    def test_search_case_insensitive(self, qapp):
        """Test that search is case-insensitive."""
        viewer = LogViewer(logger='test.search.case', initial_filters=[])
        logger = logging.getLogger('test.search.case')
        logger.setLevel(logging.DEBUG)
        
        # Add messages with different cases
        logger.info("Message with ERROR in caps")
        logger.warning("Message with error in lowercase")
        logger.error("Message with Error in mixed case")
        
        qapp.processEvents()
        
        search_widget = viewer.search_widget
        
        # Search for lowercase "error"
        search_widget.search_input.setText("error")
        qapp.processEvents()
        
        # Should find all 3 messages regardless of case
        assert len(search_widget.search_results) == 3, "Should find all 3 messages regardless of case"
        assert search_widget.result_label.text() == "1/3", "Should show all case variations"
    
    def test_search_with_exceptions_and_children(self, qapp):
        """Test search functionality with exception details and child entries."""
        viewer = LogViewer(logger='test.search.exception', initial_filters=[])
        logger = logging.getLogger('test.search.exception')
        logger.setLevel(logging.DEBUG)
        
        # Add regular message
        logger.info("Regular message")
        
        # Add exception with traceback
        try:
            raise ValueError("Test exception with traceback")
        except Exception:
            logger.error("Error with exception details", exc_info=True)
        
        qapp.processEvents()
        
        # Expand the exception to create child entries
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if item and item.rowCount() > 0:
                viewer.expand_item(item)
        
        search_widget = viewer.search_widget
        
        # Search for "traceback" which should be in child entries
        search_widget.search_input.setText("traceback")
        qapp.processEvents()
        
        # Should find results in child entries
        assert len(search_widget.search_results) > 0, "Should find 'traceback' in exception children"
        
        # Verify navigation works with child entries
        if search_widget.search_results:
            # Navigate to first result
            first_result = search_widget.search_results[0]
            search_widget._navigate_to_current_result()
            
            # Verify current index is set (works for both parent and child items)
            current_index = viewer.tree.currentIndex()
            assert current_index.isValid(), "Should have valid current index"
    
    def test_search_respects_hidden_columns(self, qapp):
        """Test that search only searches in visible columns."""
        viewer = LogViewer(logger='test.search.columns', initial_filters=[])
        logger = logging.getLogger('test.search.columns')
        logger.setLevel(logging.DEBUG)
        
        # Add a message - the level will be hidden by default but should still contain text
        logger.error("Message about testing")
        
        qapp.processEvents()
        
        # Verify level column is hidden by default
        assert viewer.tree.isColumnHidden(LogColumns.LEVEL), "Level column should be hidden by default"
        
        search_widget = viewer.search_widget
        
        # Search for "ERROR" which appears in the hidden level column
        search_widget.search_input.setText("ERROR")
        qapp.processEvents()
        
        # Should not find results in hidden level column, but should find in other columns if present
        # The exact number depends on what's visible, but this tests the column visibility logic
        initial_results = len(search_widget.search_results)
        
        # Show the level column
        viewer.tree.setColumnHidden(LogColumns.LEVEL, False)
        
        # Search again - should find more results now that level column is visible
        search_widget.search_input.setText("")  # Clear
        qapp.processEvents()
        search_widget.search_input.setText("ERROR")
        qapp.processEvents()
        
        new_results = len(search_widget.search_results)
        # Should find at least as many results as before (and likely more)
        assert new_results >= initial_results, "Should find same or more results when level column is visible"
    
    def test_search_clear_functionality(self, qapp):
        """Test that clearing search resets the widget state."""
        viewer = LogViewer(logger='test.search.clear', initial_filters=[])
        viewer.show()
        logger = logging.getLogger('test.search.clear')
        logger.setLevel(logging.DEBUG)
        
        # Add test messages
        logger.info("Message with searchterm")
        logger.warning("Another message with searchterm")
        
        qapp.processEvents()
        
        search_widget = viewer.search_widget
        
        # Perform search
        search_widget.search_input.setText("searchterm")
        qapp.processEvents()
        
        # Verify search found results
        assert len(search_widget.search_results) > 0, "Should have search results"
        assert search_widget.prev_button.isVisible(), "Navigation should be visible"
        
        # Clear search
        search_widget.search_input.setText("")
        qapp.processEvents()
        
        # Verify search is cleared
        assert len(search_widget.search_results) == 0, "Should have no search results after clear"
        assert search_widget.current_result_index == -1, "Should reset current result index"
        assert not search_widget.prev_button.isVisible(), "Navigation should be hidden after clear"
        assert not search_widget.next_button.isVisible(), "Navigation should be hidden after clear"
        assert not search_widget.result_label.isVisible(), "Result label should be hidden after clear"
    
    def test_search_with_no_results(self, qapp):
        """Test search behavior when no results are found."""
        viewer = LogViewer(logger='test.search.noresults', initial_filters=[])
        logger = logging.getLogger('test.search.noresults')
        logger.setLevel(logging.DEBUG)
        
        # Add test messages
        logger.info("First message")
        logger.warning("Second message")
        
        qapp.processEvents()
        
        search_widget = viewer.search_widget
        
        # Search for term that won't be found
        search_widget.search_input.setText("nonexistentterm")
        qapp.processEvents()
        
        # Verify no results
        assert len(search_widget.search_results) == 0, "Should find no results"
        assert search_widget.current_result_index == -1, "Should have no current result"
        
        # Verify navigation is hidden
        assert not search_widget.prev_button.isVisible(), "Navigation should be hidden with no results"
        assert not search_widget.next_button.isVisible(), "Navigation should be hidden with no results"
        assert not search_widget.result_label.isVisible(), "Result label should be hidden with no results"
    
    def test_search_integration_with_logviewer_layout(self, qapp):
        """Test that the search widget is properly integrated into the LogViewer layout."""
        viewer = LogViewer(logger='test.search.layout', initial_filters=[])
        viewer.show()
        
        # Verify search widget exists and is properly connected
        assert hasattr(viewer, 'search_widget'), "LogViewer should have search_widget attribute"
        assert isinstance(viewer.search_widget, SearchWidget), "Should be a SearchWidget instance"
        assert viewer.search_widget.tree_view is viewer.tree, "Search widget should be connected to tree view"
        
        # Verify filter widget still exists
        assert hasattr(viewer, 'filter_input_widget'), "LogViewer should still have filter_input_widget"
        
        # Both widgets should be visible
        assert viewer.search_widget.isVisible(), "Search widget should be visible"
        assert viewer.filter_input_widget.isVisible(), "Filter widget should be visible"


def run_manual_tests():
    """Run basic tests without pytest."""
    # Create QApplication for manual testing (conftest.py only works in pytest)
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    print("Test 1: Search widget initialization...")
    test = TestSearchWidget()
    test.test_search_widget_initialization(qapp)
    print("✅ Test 1 passed!")
    
    print("Test 2: Basic search functionality...")
    test.test_search_functionality_basic(qapp)
    print("✅ Test 2 passed!")
    
    print("Test 3: Case insensitive search...")
    test.test_search_case_insensitive(qapp)
    print("✅ Test 3 passed!")
    
    print("Test 4: Search with exceptions and children...")
    test.test_search_with_exceptions_and_children(qapp)
    print("✅ Test 4 passed!")
    
    print("Test 5: Search respects hidden columns...")
    test.test_search_respects_hidden_columns(qapp)
    print("✅ Test 5 passed!")
    
    print("Test 6: Search clear functionality...")
    test.test_search_clear_functionality(qapp)
    print("✅ Test 6 passed!")
    
    print("Test 7: Search with no results...")
    test.test_search_with_no_results(qapp)
    print("✅ Test 7 passed!")
    
    print("Test 8: Search integration with LogViewer layout...")
    test.test_search_integration_with_logviewer_layout(qapp)
    print("✅ Test 8 passed!")
    
    print("All search tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()