import logging
import sys
from unittest.mock import Mock
from teleprox.log.logviewer.viewer import LogViewer
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


class TestCodeLineClicking:
    """Test cases for code line clicking behavior in traceback frames."""
    
    def test_code_line_click_with_exc_info_source_lines(self, qapp):
        """Test that clicking on traceback frames with file info emits code_line_clicked signal.
        
        This tests the behavior where clicking on source lines in exception tracebacks
        should emit a code_line_clicked signal with file path and line number.
        """
        viewer = LogViewer(logger='test.code.click')
        logger = logging.getLogger('test.code.click')
        logger.setLevel(logging.ERROR)
        
        # Create a mock signal to capture emissions
        signal_mock = Mock()
        viewer.code_line_clicked.connect(signal_mock)
        
        # Generate a real exception with source info to create proper exc_info
        try:
            def sample_function():
                raise ValueError("Test exception with source lines")
            
            sample_function()
        except Exception:
            exc_info = sys.exc_info()
            logger.error("Error with traceback", exc_info=exc_info)
        
        # Process events to ensure the log is fully processed
        qapp.processEvents()
        
        # Find the main log record item and expand it
        main_item = viewer.model.item(0, 0)
        viewer.expand_item(main_item)
        qapp.processEvents()
        
        # Find an item containing source line info by walking the tree
        def find_item_with_text(parent_item, target_text):
            """Recursively find an item whose text contains the target string."""
            for i in range(parent_item.rowCount()):
                child_item = parent_item.child(i, 0)
                if child_item:
                    if target_text in child_item.text():
                        return child_item
                    # Recursively check children
                    if child_item.hasChildren():
                        found = find_item_with_text(child_item, target_text)
                        if found:
                            return found
            return None
        
        # Look for a line that contains file reference (like "File "/path/file.py", line 123")
        source_line_item = find_item_with_text(main_item, "File \"")
        assert source_line_item is not None, "Should find a source line item"
        
        # Simulate clicking by emitting the clicked signal that would be triggered by user interaction
        model_index = viewer.model.indexFromItem(source_line_item)
        tree_index = viewer.map_index_from_model(model_index)
        viewer.tree.clicked.emit(tree_index)
        qapp.processEvents()
        
        # Verify that the signal was emitted with proper file path and line number
        signal_mock.assert_called_once()
        args = signal_mock.call_args[0]
        assert len(args) == 2, "Signal should be called with file_path and line_number"
        
        file_path, line_number = args
        assert isinstance(file_path, str), "File path should be a string"
        assert isinstance(line_number, int), "Line number should be an integer"
        assert file_path.endswith('.py'), "File path should be a Python file"
        assert line_number > 0, "Line number should be positive"