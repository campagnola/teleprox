import logging
from teleprox.log.logviewer.viewer import LogViewer, LogModel
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


class TestLogViewerLazyLoading:
    """Test cases for lazy loading functionality using dummy placeholders."""
    
    # QApplication fixture provided by conftest.py
    
    @pytest.fixture
    def log_model(self):
        """Create LogModel for testing."""
        model = LogModel()
        model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message'])
        return model
    
    @pytest.fixture
    def mock_record_with_exc_text(self):
        """Create mock log record with exc_text."""
        class MockRecord:
            def __init__(self):
                self.created = 1234567890.123
                self.processName = "TestProcess"
                self.threadName = "MainThread"
                self.name = "test.logger"
                self.levelno = logging.ERROR
                self.levelname = "ERROR"
                self.exc_info = None
                self.exc_text = "ValueError: Test exception\nLine 1 of traceback\nLine 2 of traceback"
                self.stack_info = None
                
            def getMessage(self):
                return "Test error message with exception"
        
        return MockRecord()
    
    def test_loading_placeholder_creation(self, qapp, log_model, mock_record_with_exc_text):
        """Test that records with exceptions get expandable content."""
        # Simulate adding a record with exception text using the new API
        log_model.append_record(mock_record_with_exc_text)
        
        # Verify record was added
        assert log_model.rowCount() == 1
        parent_item = log_model.item(0, 0)
        
        # Verify it has expandable content (placeholder child)
        assert parent_item.rowCount() == 1
        
        # Verify the placeholder child exists
        placeholder = parent_item.child(0, 0)
        assert placeholder is not None
        assert placeholder.text() == "Loading..."
    
    def test_placeholder_replacement(self, qapp, log_model, mock_record_with_exc_text):
        """Test that placeholders are replaced with actual content."""
        # Add record with exception text using new API
        log_model.append_record(mock_record_with_exc_text)
        parent_item = log_model.item(0, 0)
        
        # Verify it has placeholder initially
        assert parent_item.rowCount() == 1
        placeholder = parent_item.child(0, 0)
        assert placeholder.text() == "Loading..."
        
        # Simulate expansion to replace placeholder with content
        log_model.item_expanded(parent_item)
        
        # Verify replacement occurred - should have exception content now
        assert parent_item.rowCount() >= 1  # Should have at least the exception category
        
        # First child should no longer be "Loading..."
        first_child = parent_item.child(0, 0)
        assert first_child.text() != "Loading..."
    
    def test_logviewer_integration(self, qapp):
        """Test that LogViewer properly integrates with lazy loading."""
        # Create LogViewer
        viewer = LogViewer()
        
        # Create logger that sends to viewer
        logger = logging.getLogger('test.lazy.loading')
        
        # Create record with exception text
        record = logging.LogRecord(
            name='test.lazy.loading',
            level=logging.ERROR,
            pathname='test.py',
            lineno=42,
            msg='Test with exc_text',
            args=(),
            exc_info=None
        )
        record.exc_text = "ValueError: Test exception\nTraceback line 1\nTraceback line 2"
        
        # Send record to viewer
        logger.handle(record)
        
        # Verify model has entries
        assert viewer.model.rowCount() > 0
        
        # Get the log entry item
        log_item = viewer.model.item(0, 0)  # First row, timestamp column
        
        # Verify it has expandable content (placeholder)
        assert log_item.rowCount() == 1
        placeholder = log_item.child(0, 0)
        assert placeholder.text() == "Loading..."
        
        # Simulate UI expansion by expanding the tree view item
        source_index = viewer.model.indexFromItem(log_item)
        tree_index = viewer.map_index_from_model(source_index)
        viewer.tree.expand(tree_index)
        
        # Verify content was loaded after UI expansion
        assert log_item.rowCount() >= 1
        first_child = log_item.child(0, 0)
        assert first_child.text() != "Loading..."
    
    def test_no_placeholder_without_exception(self, qapp):
        """Test that no expandable content is shown for records without exceptions."""
        viewer = LogViewer(logger='test.no.exception')  # Pass logger name to constructor
        logger = logging.getLogger('test.no.exception')
        logger.setLevel(logging.DEBUG)  # Ensure all messages are captured
        
        # Log normal message without exception
        logger.warning("Regular log message")
        
        # Verify model has entry but no expandable content
        assert viewer.model.rowCount() > 0
        log_item = viewer.model.item(0, 0)
        assert log_item.rowCount() == 0  # No children - not expandable


def run_manual_tests():
    """Run basic tests without pytest."""
    # Create QApplication for manual testing (conftest.py only works in pytest)
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])
    
    # Test 1: Basic placeholder functionality
    print("Test 1: Basic placeholder functionality...")
    model = LogModel()
    model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message'])
    
    # Create mock record
    class MockRecord:
        def __init__(self):
            self.created = 1234567890.123
            self.processName = "TestProcess"
            self.threadName = "MainThread"
            self.name = "test.logger"
            self.levelno = logging.ERROR
            self.levelname = "ERROR"
            self.exc_info = None
            self.exc_text = "ValueError: Test exception\nLine 1\nLine 2"
            self.stack_info = None
        def getMessage(self):
            return "Test error message"
    
    parent_item = qt.QStandardItem("Test")
    record = MockRecord()
    model.add_loading_placeholder(parent_item, record)
    
    assert parent_item.rowCount() == 1, "Should have 1 placeholder child"
    assert model.has_loading_placeholder(parent_item), "Should detect placeholder"
    
    model.replace_placeholder_with_content(parent_item)
    assert parent_item.rowCount() > 1, "Should have multiple children after replacement"
    assert not model.has_loading_placeholder(parent_item), "Should not detect placeholder after replacement"
    
    print("✅ Test 1 passed!")
    
    # Test 2: LogViewer integration
    print("Test 2: LogViewer integration...")
    viewer = LogViewer()
    logger = logging.getLogger('test.integration')
    
    record = logging.LogRecord(
        name='test.integration',
        level=logging.ERROR,
        pathname='test.py',
        lineno=42,
        msg='Test with exc_text',
        args=(),
        exc_info=None
    )
    record.exc_text = "ValueError: Integration test\nLine 1\nLine 2"
    logger.handle(record)
    
    assert viewer.model.rowCount() > 0, "Should have log entries"
    log_item = viewer.model.item(0, 0)
    assert viewer.model.has_loading_placeholder(log_item), "Should have placeholder"
    
    print("✅ Test 2 passed!")
    print("All tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()