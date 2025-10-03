import logging
from unittest.mock import Mock, patch

import pytest

from teleprox import qt
from teleprox.log.logviewer.constants import LogColumns
from teleprox.log.logviewer.viewer import LogViewer


class TestContextMenuCopy:
    """Test cases for right-click context menu copy functionality."""

    def test_context_menu_copy_simple_record(self, qapp):
        """Test that right-clicking on a row shows context menu with copy option."""
        viewer = LogViewer(logger='test.context.menu')
        logger = logging.getLogger('test.context.menu')
        logger.setLevel(logging.INFO)

        # Log a simple message
        logger.info("Test log message")
        qapp.processEvents()

        # Mock clipboard
        with patch(
            'teleprox.log.logviewer.viewer.qt.QApplication.clipboard'
        ) as mock_clipboard_func:
            mock_clipboard = Mock()
            mock_clipboard_func.return_value = mock_clipboard

            # Get the index for the first row
            model = viewer.tree.model()
            index = model.index(0, LogColumns.TIMESTAMP)

            # Mock the sender to provide the position data
            with patch.object(viewer, 'sender') as mock_sender:
                mock_action = Mock()
                mock_action.data.return_value = qt.QPoint(0, 0)  # Position doesn't matter for this test
                mock_sender.return_value = mock_action
                
                # Mock indexAt to return our test index
                with patch.object(viewer.tree, 'indexAt', return_value=index):
                    # Call copy function
                    viewer._copy_record_to_clipboard()

            # Verify clipboard.setText was called
            mock_clipboard.setText.assert_called_once()
            copied_text = mock_clipboard.setText.call_args[0][0]

            # Check that copied text contains the expected fields
            assert "Timestamp:" in copied_text
            assert "Source:" in copied_text
            assert "Logger:" in copied_text
            assert "Level:" in copied_text
            assert "Message:" in copied_text
            assert "Test log message" in copied_text

    def test_context_menu_show_on_right_click(self, qapp):
        """Test that context menu method handles right-clicking properly."""
        viewer = LogViewer(logger='test.context.show')
        logger = logging.getLogger('test.context.show')
        logger.info("Test message for context menu")
        qapp.processEvents()

        # Test with valid index - should not raise exception
        model = viewer.tree.model()
        valid_index = model.index(0, LogColumns.TIMESTAMP)

        # Mock indexAt to return a valid index and mock menu exec to avoid blocking
        with patch.object(viewer.tree, 'indexAt', return_value=valid_index):
            with patch('teleprox.log.logviewer.viewer.qt.QMenu.exec_'):
                # Call should complete without error
                position = qt.QPoint(0, 0)
                try:
                    viewer._show_row_context_menu(position)
                    # If we get here without exception, the method works
                    assert True
                except Exception as e:
                    pytest.fail(f"Context menu method raised exception: {e}")

    def test_context_menu_no_action_on_invalid_index(self, qapp):
        """Test that no context menu is shown when clicking on empty area."""
        viewer = LogViewer(logger='test.context.invalid')

        # Mock QMenu to capture if menu creation is attempted
        with patch('teleprox.log.logviewer.viewer.qt.QMenu') as mock_menu_class:
            # Mock indexAt to return invalid index
            with patch.object(viewer.tree, 'indexAt') as mock_index_at:
                invalid_index = qt.QModelIndex()  # Invalid index
                mock_index_at.return_value = invalid_index

                # Call the context menu method
                position = qt.QPoint(0, 0)
                viewer._show_row_context_menu(position)

                # Verify no menu was created
                mock_menu_class.assert_not_called()
