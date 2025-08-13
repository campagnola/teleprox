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


class TestLevelFiltering:
    """Test cases for level filtering functionality."""
    
    # QApplication fixture provided by conftest.py
    
    def test_level_cipher_storage(self, qapp):
        """Test that level cipher values are stored correctly."""
        viewer = LogViewer(logger='test.cipher.storage')
        logger = logging.getLogger('test.cipher.storage')
        logger.setLevel(logging.DEBUG)
        
        # Add messages at different levels
        logger.debug("Debug message")
        logger.info("Info message") 
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")
        
        assert viewer.model.rowCount() == 5
        
        # Check that cipher values are stored correctly
        # Debug=10->k, Info=20->u, Warning=30->E, Error=40->O, Critical=50->Y
        expected_ciphers = ['k', 'u', 'E', 'O', 'Y']  
        for i in range(5):
            level_item = viewer.model.item(i, LogColumns.LEVEL)  # Level column
            cipher = level_item.data(ItemDataRole.LEVEL_CIPHER)
            assert cipher == expected_ciphers[i], f"Row {i}: expected cipher '{expected_ciphers[i]}', got '{cipher}'"
    
    def test_level_filtering_warning_and_above(self, qapp):
        """Test level filtering shows only WARNING and above."""
        viewer = LogViewer(logger='test.level.warning')
        logger = logging.getLogger('test.level.warning')
        logger.setLevel(logging.DEBUG)
        
        # Add messages at different levels
        logger.debug("Debug message")
        logger.info("Info message") 
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")
        
        assert viewer.model.rowCount() == 5
        
        # Apply level filter for WARNING and above
        viewer.apply_filters(['level: warning'])
        
        # Count visible rows after filtering
        current_model = viewer.tree.model()
        visible_rows = current_model.rowCount() if current_model else 0
        
        # Should show WARNING, ERROR, CRITICAL = 3 rows
        assert visible_rows == 3, f"Expected 3 visible rows (WARNING+), got {visible_rows}"
    
    def test_level_filtering_error_and_above(self, qapp):
        """Test level filtering shows only ERROR and above."""
        viewer = LogViewer(logger='test.level.error')
        logger = logging.getLogger('test.level.error')
        logger.setLevel(logging.DEBUG)
        
        # Add messages at different levels
        logger.debug("Debug message")
        logger.info("Info message") 
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")
        
        # Apply level filter for ERROR and above
        viewer.apply_filters(['level: error'])
        
        # Count visible rows after filtering
        current_model = viewer.tree.model()
        visible_rows = current_model.rowCount() if current_model else 0
        
        # Should show ERROR, CRITICAL = 2 rows
        assert visible_rows == 2, f"Expected 2 visible rows (ERROR+), got {visible_rows}"
    
    def test_level_filtering_clear_filter(self, qapp):
        """Test that clearing filters shows all rows again."""
        viewer = LogViewer(logger='test.level.clear')
        logger = logging.getLogger('test.level.clear')
        logger.setLevel(logging.DEBUG)
        
        # Add messages
        logger.debug("Debug message")
        logger.info("Info message") 
        logger.warning("Warning message")
        
        original_count = viewer.model.rowCount()
        assert original_count == 3
        
        # Apply filter
        viewer.apply_filters(['level: warning'])
        filtered_model = viewer.tree.model()
        filtered_count = filtered_model.rowCount() if filtered_model else 0
        assert filtered_count == 1  # Only WARNING
        
        # Clear filter
        viewer.apply_filters([])
        cleared_model = viewer.tree.model()
        cleared_count = cleared_model.rowCount() if cleared_model else 0
        
        # Should show all rows again
        assert cleared_count == original_count, f"Expected {original_count} rows after clearing filter, got {cleared_count}"
    
    def test_level_filtering_no_matches(self, qapp):
        """Test level filtering when no messages match the criteria."""
        viewer = LogViewer(logger='test.level.none')
        logger = logging.getLogger('test.level.none')
        logger.setLevel(logging.DEBUG)
        
        # Add only low-level messages
        logger.debug("Debug message")
        logger.info("Info message")
        
        assert viewer.model.rowCount() == 2
        
        # Apply filter for CRITICAL and above (no matches)
        viewer.apply_filters(['level: critical'])
        
        current_model = viewer.tree.model()
        visible_rows = current_model.rowCount() if current_model else 0
        
        # Should show 0 rows
        assert visible_rows == 0, f"Expected 0 visible rows for CRITICAL+ filter, got {visible_rows}"


def run_manual_tests():
    """Run basic tests without pytest."""
    # Create QApplication for manual testing (conftest.py only works in pytest)
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    print("Test 1: Level cipher storage...")
    test = TestLevelFiltering()
    test.test_level_cipher_storage(qapp)
    print("✅ Test 1 passed!")
    
    print("Test 2: Level filtering WARNING+...")
    test.test_level_filtering_warning_and_above(qapp)
    print("✅ Test 2 passed!")
    
    print("Test 3: Level filtering ERROR+...")
    test.test_level_filtering_error_and_above(qapp)
    print("✅ Test 3 passed!")
    
    print("Test 4: Clear filter...")
    test.test_level_filtering_clear_filter(qapp)
    print("✅ Test 4 passed!")
    
    print("Test 5: No matches...")
    test.test_level_filtering_no_matches(qapp)
    print("✅ Test 5 passed!")
    
    print("All level filtering tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()