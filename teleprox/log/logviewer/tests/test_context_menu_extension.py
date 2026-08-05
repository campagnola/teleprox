import logging
from unittest.mock import Mock, patch

from teleprox import qt
from teleprox.log.logviewer.constants import LogColumns
from teleprox.log.logviewer.viewer import LogViewer


class TestContextMenuExtension:
    """Test cases for subclasses extending the row context menu."""

    def test_subclass_can_add_action_alongside_copy(self, qapp):
        """A LogViewer subclass overriding _build_row_context_menu can add its
        own action to the menu while inheriting the base Copy action."""

        class ExtendedLogViewer(LogViewer):
            def _build_row_context_menu(self, index):
                menu = super()._build_row_context_menu(index)
                custom_action = qt.QAction("Custom Action", self)
                menu.addAction(custom_action)
                return menu

        viewer = ExtendedLogViewer(logger='test.context.extension')
        logger = logging.getLogger('test.context.extension')
        logger.setLevel(logging.INFO)
        logger.info("Test log message")
        qapp.processEvents()

        model = viewer.tree.model()
        index = model.index(0, LogColumns.TIMESTAMP)

        menu = viewer._build_row_context_menu(index)

        action_labels = [action.text() for action in menu.actions()]
        assert "Custom Action" in action_labels
        assert "Copy" in action_labels

        copy_action = next(a for a in menu.actions() if a.text() == "Copy")
        assert copy_action.selectedIndex == index

        # Verify Copy is still wired to the clipboard handler
        with patch(
            'teleprox.log.logviewer.viewer.qt.QApplication.clipboard'
        ) as mock_clipboard_func:
            mock_clipboard = Mock()
            mock_clipboard_func.return_value = mock_clipboard

            with patch.object(viewer, 'sender', return_value=copy_action):
                viewer._copy_record_to_clipboard()

            mock_clipboard.setText.assert_called_once()
