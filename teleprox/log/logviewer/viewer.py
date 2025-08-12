# Core LogViewer implementation with Qt integration and log handling
# Contains LogViewer widget, QtLogHandler, and main GUI functionality

import html
import logging
import time

from teleprox import qt
from .utils import level_colors, thread_color, level_to_cipher
from .widgets import FilterInputWidget, HighlightDelegate, HyperlinkTreeView
from .filtering import LogFilterProxyModel, USE_CHAINED_FILTERING
from .constants import ItemDataRole, LogColumns
from .log_model import LogModel


class ExpansionStateManager:
    """Manages saving and restoring tree expansion state using LOG_IDs and relative paths."""
    
    def __init__(self, tree_view):
        self.tree_view = tree_view
    
    def save_state(self):
        """Save current expansion state."""
        expanded_items = {}
        current_model = self.tree_view.model()
        
        if current_model is None:
            return expanded_items
        
        self._collect_expanded_items(current_model.index(-1, -1), None, [], expanded_items)
        return expanded_items
    
    def restore_state(self, expanded_items):
        """Restore expansion state from saved data."""
        if not expanded_items:
            return
            
        current_model = self.tree_view.model()
        if current_model is None:
            return
        
        # Build lookup table for LOG_IDs
        log_id_to_index = self._build_log_id_lookup(current_model)
        
        # Restore expansion for each saved LOG_ID
        for log_id, child_paths in expanded_items.items():
            self._restore_log_id_expansion(log_id, child_paths, log_id_to_index, current_model)
        
        # Set column spans for all items
        self._set_spans_recursive(current_model.index(-1, -1), current_model)
    
    def _collect_expanded_items(self, parent_index, parent_log_id, relative_path, expanded_items):
        """Recursively collect expanded items."""
        current_model = self.tree_view.model()
        
        for row in range(current_model.rowCount(parent_index)):
            index = current_model.index(row, LogColumns.TIMESTAMP, parent_index)
            current_relative_path = relative_path + [row]
            
            if self.tree_view.isExpanded(index):
                if parent_log_id is None:
                    # Top-level item - use its LOG_ID
                    log_id = current_model.data(index, ItemDataRole.LOG_ID)
                    if log_id is not None:
                        expanded_items[log_id] = []
                        self._collect_expanded_items(index, log_id, [], expanded_items)
                else:
                    # Child item - save relative path from parent LOG_ID
                    if parent_log_id not in expanded_items:
                        expanded_items[parent_log_id] = []
                    expanded_items[parent_log_id].append(tuple(current_relative_path))
                    self._collect_expanded_items(index, parent_log_id, current_relative_path, expanded_items)
    
    def _build_log_id_lookup(self, current_model):
        """Build lookup table mapping LOG_IDs to model indices."""
        log_id_to_index = {}
        for row in range(current_model.rowCount()):
            index = current_model.index(row, LogColumns.TIMESTAMP)
            log_id = current_model.data(index, ItemDataRole.LOG_ID)
            if log_id is not None:
                log_id_to_index[log_id] = index
        return log_id_to_index
    
    def _restore_log_id_expansion(self, log_id, child_paths, log_id_to_index, current_model):
        """Restore expansion for a specific LOG_ID and its children."""
        parent_index = log_id_to_index.get(log_id)
        if parent_index is None:
            return  # LOG_ID not found in current model
        
        # Expand the top-level item if it has children
        if current_model.rowCount(parent_index) > 0:
            self.tree_view.expand(parent_index)
            self._set_child_spans_for_item(parent_index)
        
        # Restore child expansions using relative paths
        for child_path in child_paths:
            child_index = self._navigate_to_child(parent_index, child_path, current_model)
            if child_index.isValid():
                self.tree_view.expand(child_index)
                if current_model.rowCount(child_index) > 0:
                    self._set_child_spans_for_item(child_index)
    
    def _navigate_to_child(self, parent_index, child_path, current_model):
        """Navigate from parent to child using relative path."""
        current_index = parent_index
        
        for row_num in child_path:
            if current_index.isValid() and row_num < current_model.rowCount(current_index):
                current_index = current_model.index(row_num, LogColumns.TIMESTAMP, current_index)
            else:
                return qt.QModelIndex()  # Invalid path
        
        return current_index
    
    def _set_child_spans_for_item(self, index):
        """Set column spans for children of an item."""
        current_model = self.tree_view.model()
        for row in range(current_model.rowCount(index)):
            self.tree_view.setFirstColumnSpanned(row, index, True)
    
    def _set_spans_recursive(self, parent_index, current_model):
        """Recursively set column spans for all child items."""
        for row in range(current_model.rowCount(parent_index)):
            index = current_model.index(row, LogColumns.TIMESTAMP, parent_index)
            
            # Set column spans for child items (not top-level)
            if parent_index.isValid():
                self.tree_view.setFirstColumnSpanned(row, parent_index, True)
            
            # Recursively set spans for grandchildren
            if current_model.rowCount(index) > 0:
                self._set_spans_recursive(index, current_model)

# HTML export template constants
HTML_EXPORT_HEADER = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .log-table {{ border-collapse: collapse; width: 100%; }}
        .log-table th, .log-table td {{ padding: 8px; text-align: left; }}
        .log-table th {{ background-color: #f2f2f2; font-weight: bold; }}
        .log-entry {{ border-bottom: 2px solid #ccc; }}
        .child-entry {{ background-color: #f9f9f9; font-family: monospace; }}
        .exception {{ color: #d9534f; font-weight: bold; }}
        .traceback {{ color: #555; }}
        .timestamp {{ white-space: nowrap; }}
        .level-debug {{ color: #6c757d; }}
        .level-info {{ color: #17a2b8; }}
        .level-warning {{ color: #ffc107; }}
        .level-error {{ color: #dc3545; }}
        .level-critical {{ color: #dc3545; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <p>Generated on {timestamp}</p>"""

HTML_FILTER_CRITERIA_SECTION = """
    <div style="background-color: #f8f9fa; padding: 10px; margin: 10px 0; border-left: 4px solid #007bff;">
        <h3 style="margin: 0 0 8px 0; color: #495057;">Applied Filters:</h3>
        <ul style="margin: 0; padding-left: 20px;">
{filter_items}
        </ul>
    </div>"""

HTML_FILTER_ITEM = """            <li style="font-family: monospace; margin: 2px 0;">{filter_expr}</li>"""

HTML_NO_FILTERS = """
    <div style="background-color: #f8f9fa; padding: 10px; margin: 10px 0; border-left: 4px solid #007bff;">
        <h3 style="margin: 0 0 8px 0; color: #495057;">Applied Filters:</h3>
        <p style="margin: 0; font-style: italic; color: #6c757d;">No filters applied</p>
    </div>"""

HTML_TABLE_HEADER = """
    <table class="log-table">
        <thead>
            <tr>
                <th>Timestamp</th>
                <th>Source</th>
                <th>Logger</th>
                <th>Level</th>
                <th>Message</th>
            </tr>
        </thead>
        <tbody>"""

HTML_EXPORT_FOOTER = """        </tbody>
    </table>
</body>
</html>"""

# Level to CSS class mapping for HTML export
LEVEL_CSS_CLASSES = {
    'DEBUG': 'level-debug',
    'INFO': 'level-info',
    'WARNING': 'level-warning',
    'WARN': 'level-warning',
    'ERROR': 'level-error',
    'CRITICAL': 'level-critical'
}


class LogViewer(qt.QWidget):
    """QWidget for displaying and filtering log messages."""
    
    # Signal emitted when user clicks on any code line (stack frame, traceback, etc.)
    code_line_clicked = qt.Signal(str, int)  # (file_path, line_number)
    
    # Signal for thread-safe message handling - messages from non-Qt threads are re-emitted here
    _message_from_thread_signal = qt.Signal(object)  # log record
    
    def __init__(self, logger='', initial_filters=('level: info',), parent=None):
        qt.QWidget.__init__(self, parent=parent)
        
        # Unique ID counter for log entries
        self._next_log_id = 0
        
        # Track filter changes for expansion state preservation
        self._last_filter_strings = []

        # Set up handler to send log records to this widget by signal
        self.handler = QtLogHandler()
        self.handler.new_record.connect(self.new_record)
        if isinstance(logger, str):
            logger = logging.getLogger(logger)
        logger.addHandler(self.handler)
        
        # Set up thread-safe message handling - queued connection ensures GUI thread execution
        self._message_from_thread_signal.connect(self._process_record, qt.Qt.QueuedConnection)
        
        # Set up GUI
        self.layout = qt.QGridLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # Add filter input widget
        self.filter_input_widget = FilterInputWidget()
        self.filter_input_widget.filters_changed.connect(self.apply_filters)
        self.filter_input_widget.export_all_requested.connect(self._export_all_to_html)
        self.filter_input_widget.export_filtered_requested.connect(self._export_filtered_to_html)
        self.layout.addWidget(self.filter_input_widget, 0, 0)

        self.model = LogModel()
        self.model.setHorizontalHeaderLabels(LogColumns.TITLES)
        
        # Create custom proxy model for advanced filtering
        if USE_CHAINED_FILTERING:
            self.proxy_model = LogFilterProxyModel(self.model)
            tree_model = self.proxy_model.final_model
        else:
            self.proxy_model = LogFilterProxyModel()
            self.proxy_model.setSourceModel(self.model)
            tree_model = self.proxy_model
        
        # Create custom tree view with hyperlink cursor support
        self.tree = HyperlinkTreeView()
        self.tree.setModel(tree_model)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)  # Make non-editable
        
        # Initialize expansion state manager now that tree is created
        self.expansion_manager = ExpansionStateManager(self.tree)
        
        # Set up custom header with context menu
        self.header = self.tree.header()
        self.header.setContextMenuPolicy(qt.Qt.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._show_header_context_menu)
        
        # Hide Task, Level, Host, Process, and Thread columns by default
        self.tree.setColumnHidden(LogColumns.LEVEL, True)  # Level column
        self.tree.setColumnHidden(LogColumns.TASK, True)   # Task column
        self.tree.setColumnHidden(LogColumns.HOST, True)   # Host column
        self.tree.setColumnHidden(LogColumns.PROCESS, True) # Process column
        self.tree.setColumnHidden(LogColumns.THREAD, True) # Thread column
        
        # Create custom delegate for efficient highlighting (will be set on models)
        self.highlight_delegate = HighlightDelegate(self)
        
        # Set delegate on initial model
        self.tree.setItemDelegate(self.highlight_delegate)
        
        self.tree.setSortingEnabled(True)
        # Ensure chronological sorting from the start
        self._ensure_chronological_sorting()
        
        # Set up selection handling for highlighting
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        
        # Handle tree expansion to replace loading placeholders
        self.tree.expanded.connect(self._on_item_expanded)
        
        # Handle clicks on code lines for file/line navigation
        self.tree.clicked.connect(self._on_item_clicked)
        
        self.layout.addWidget(self.tree, 1, 0)
        self.resize(1200, 600)
        
        # Set column widths from constants
        for i, width in enumerate(LogColumns.WIDTHS):
            self.tree.setColumnWidth(i, width)
        
        # Apply initial filters if provided
        if initial_filters:
            # Add initial filters to the UI
            for filter_expr in initial_filters:
                self.filter_input_widget.filter_input.setText(filter_expr)
                self.filter_input_widget.add_filter()
            
            # Apply the filters
            self.apply_filters(list(initial_filters))

    def new_record(self, rec):
        # Check if we're running in the Qt main thread
        current_thread = qt.QThread.currentThread()
        main_thread = qt.QApplication.instance().thread()
        
        if current_thread != main_thread:
            # Re-emit through queued signal to ensure GUI thread execution
            self._message_from_thread_signal.emit(rec)
            return
        
        # Process the record in the GUI thread
        self._process_record(rec)
    
    def _process_record(self, rec):
        """Process a log record in the GUI thread."""
        # Create a new row for the log record
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.created)) + f'{rec.created % 1.0:.3f}'.lstrip('0')
        source = f"{rec.processName}/{rec.threadName}"
        logger_name = rec.name
        level = f"{rec.levelno} - {rec.levelname}"
        message = rec.getMessage()
        
        # Create items for each column using LogColumns order
        row_items = [qt.QStandardItem("") for _ in range(len(LogColumns.TITLES))]
        
        # Populate each column according to the new layout
        row_items[LogColumns.TIMESTAMP].setText(timestamp)
        host_name = getattr(rec, 'hostName', '') or 'localhost'
        row_items[LogColumns.HOST].setText(host_name)
        row_items[LogColumns.PROCESS].setText(rec.processName)
        row_items[LogColumns.THREAD].setText(rec.threadName)
        row_items[LogColumns.SOURCE].setText(source)
        row_items[LogColumns.LOGGER].setText(logger_name)
        row_items[LogColumns.LEVEL].setText(level)
        row_items[LogColumns.MESSAGE].setText(message)
        row_items[LogColumns.TASK].setText(getattr(rec, 'taskName', ''))
        
        # Set colors based on log level
        level_color = level_colors.get(rec.levelno, "#000000")
        source_color = thread_color(source)
        row_items[LogColumns.SOURCE].setForeground(qt.QColor(source_color))
        row_items[LogColumns.LEVEL].setForeground(qt.QColor(level_color))
        row_items[LogColumns.MESSAGE].setForeground(qt.QColor(level_color))
        
        # Assign unique ID to this log entry
        log_id = self._next_log_id
        self._next_log_id += 1
        
        # Store data using named constants
        row_items[LogColumns.TIMESTAMP].setData(rec, ItemDataRole.PYTHON_DATA)  # Store complete log record
        row_items[LogColumns.TIMESTAMP].setData(rec.created, ItemDataRole.NUMERIC_TIMESTAMP)  # Store numeric timestamp
        row_items[LogColumns.TIMESTAMP].setData(log_id, ItemDataRole.LOG_ID)  # Store unique log ID
        row_items[LogColumns.SOURCE].setData(rec.processName, ItemDataRole.PROCESS_NAME)  # Store process name
        row_items[LogColumns.SOURCE].setData(rec.threadName, ItemDataRole.THREAD_NAME)  # Store thread name
        row_items[LogColumns.LOGGER].setData(rec.name, ItemDataRole.LOGGER_NAME)  # Store logger name
        row_items[LogColumns.LEVEL].setData(rec.levelno, ItemDataRole.LEVEL_NUMBER)  # Store numeric level
        row_items[LogColumns.LEVEL].setData(level_to_cipher(rec.levelno), ItemDataRole.LEVEL_CIPHER)  # Store level cipher
        row_items[LogColumns.MESSAGE].setData(rec.getMessage(), ItemDataRole.MESSAGE_TEXT)  # Store message text
        
        # Add items to the model
        self.model.appendRow(row_items)
        
        # Check if this record has any expandable information for lazy loading
        has_expandable_info = (
            (hasattr(rec, 'exc_info') and rec.exc_info and rec.exc_info != (None, None, None)) or
            (hasattr(rec, 'exc_text') and rec.exc_text) or
            (hasattr(rec, 'stack_info') and rec.stack_info) or
            self._has_extra_attributes(rec)
        )
        
        if has_expandable_info:
            # Add loading placeholder for lazy expansion
            self.model.add_loading_placeholder(row_items[LogColumns.TIMESTAMP], rec)
        
        # Ensure sorting is maintained when adding new data
        self._ensure_chronological_sorting()
    
    def _has_extra_attributes(self, record):
        """Check if record has extra attributes beyond standard LogRecord fields."""
        if not hasattr(record, '__dict__'):
            return False
            
        standard_attrs = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
            'module', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
            'thread', 'threadName', 'processName', 'process', 'getMessage',
            'exc_info', 'exc_text', 'stack_info', 'tags', 'taskName'
        }
        
        for attr_name in record.__dict__.keys():
            if attr_name not in standard_attrs and not attr_name.startswith('_'):
                return True
        return False
    
    def _set_child_spans(self, parent_item):
        """Set column spans for all children of a parent item to span full width."""
        # Find the LogViewer instance to access the tree view
        viewer = None
        current = parent_item
        while current:
            if hasattr(current, 'model') and hasattr(current.model(), 'parent'):
                model_parent = current.model().parent()
                if isinstance(model_parent, LogViewer):
                    viewer = model_parent
                    break
            # Try to find the model and work backwards
            if hasattr(current, 'model'):
                model = current.model()
                # Look for LogViewer in the model's parent chain
                test_obj = model
                while test_obj:
                    if isinstance(test_obj, LogViewer):
                        viewer = test_obj
                        break
                    test_obj = getattr(test_obj, 'parent', lambda: None)() if hasattr(test_obj, 'parent') else None
                    if test_obj is None:
                        break
            break
        
        # If we can't find the viewer through the model, we'll need to set spans later
        # This will be called from the LogViewer class
        pass
    

    def apply_filters(self, filter_strings):
        """Apply the given filter strings to the proxy model."""
        old_final_model = self.proxy_model.final_model if USE_CHAINED_FILTERING else None
        
        # Save expansion state before changing filters
        expanded_paths = self.expansion_manager.save_state()
        # print(f"Saved expansion state: {expanded_paths}")
        
        invalid_filters = self.proxy_model.set_filters(filter_strings)
        
        # Update filter input widget with invalid filter feedback
        if hasattr(self.filter_input_widget, 'set_invalid_filters'):
            self.filter_input_widget.set_invalid_filters(invalid_filters)
        
        # Update tree view model if using chained filtering and chain changed
        if USE_CHAINED_FILTERING:
            new_final_model = self.proxy_model.final_model
            if self.tree.model() != new_final_model:
                # Save current selection ID before changing model
                selected_log_id = self._get_selected_item_data()
                
                # Clear selection and highlighting before changing model
                self.tree.selectionModel().clear()
                self.highlight_delegate.clear_highlight()
                
                self.tree.setModel(new_final_model)
                
                # Reapply delegate to new model
                self.tree.setItemDelegate(self.highlight_delegate)
                
                # Reconnect selection handler since model changed
                self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
                
                # Always ensure chronological sorting
                self._ensure_chronological_sorting()
                
                # Restore selection if possible
                if selected_log_id is not None:
                    self._restore_selection(selected_log_id)
                
                # Restore expansion state
                self.expansion_manager.restore_state(expanded_paths)
        
        # Always restore expansion state after any filter change
        # (in case we're not using chained filtering or model didn't change)
        if filter_strings != self._last_filter_strings:
            # print(f"Restoring expansion state: {expanded_log_ids}")
            self.expansion_manager.restore_state(expanded_paths)
        
        # Remember the current filter strings
        self._last_filter_strings = filter_strings[:]
        
    def _ensure_chronological_sorting(self):
        """Ensure the tree view is sorted chronologically by timestamp."""
        current_model = self.tree.model()
        
        # Set sort role to use numeric timestamp from ItemDataRole.NUMERIC_TIMESTAMP
        if hasattr(current_model, 'setSortRole'):
            current_model.setSortRole(ItemDataRole.NUMERIC_TIMESTAMP)
        
        # Apply sorting
        if hasattr(current_model, 'sort'):
            current_model.sort(LogColumns.TIMESTAMP, qt.Qt.AscendingOrder)
        
        # Also tell the tree view about the sorting
        self.tree.sortByColumn(LogColumns.TIMESTAMP, qt.Qt.AscendingOrder)
    
    def _show_header_context_menu(self, position):
        """Show context menu for column visibility when right-clicking on header."""
        menu = qt.QMenu(self)
        
        # Use the column titles from LogColumns constants
        for i, header_text in enumerate(LogColumns.TITLES):
            action = qt.QAction(header_text, self)
            action.setCheckable(True)
            action.setChecked(not self.tree.isColumnHidden(i))
            action.triggered.connect(lambda checked, col=i: self._toggle_column_visibility(col, checked))
            menu.addAction(action)
        
        menu.exec_(self.header.mapToGlobal(position))
    
    def _toggle_column_visibility(self, column, visible):
        """Toggle visibility of a column."""
        self.tree.setColumnHidden(column, not visible)
    
    def _on_selection_changed(self, selected, deselected):
        """Handle selection changes to highlight related entries."""
        if not selected.indexes():
            # Clear highlighting when nothing is selected
            self.highlight_delegate.clear_highlight()
            self.tree.viewport().update()  # Trigger repaint
            return
        
        # Get the selected row data directly from the current model
        index = selected.indexes()[0]  # Use first selected index
        model = self.tree.model()
        
        # Check if this is a child item (has a parent)
        parent_index = index.parent()
        if parent_index.isValid():
            # This is a child item - use parent's highlighting data
            source_data = model.data(model.index(parent_index.row(), LogColumns.SOURCE), qt.Qt.DisplayRole)
            logger_data = model.data(model.index(parent_index.row(), LogColumns.LOGGER), qt.Qt.DisplayRole)
        else:
            # This is a top-level item - use its own data
            source_data = model.data(model.index(index.row(), LogColumns.SOURCE), qt.Qt.DisplayRole)
            logger_data = model.data(model.index(index.row(), LogColumns.LOGGER), qt.Qt.DisplayRole)
        
        if not source_data or not logger_data:
            self.highlight_delegate.clear_highlight()
            self.tree.viewport().update()
            return
            
        selected_source = source_data
        selected_logger = logger_data
        
        # Set highlighting criteria in the delegate
        self.highlight_delegate.set_highlight_criteria(selected_source, selected_logger)
        
        # Trigger a repaint of the entire tree
        self.tree.viewport().update()
    
    def _on_item_expanded(self, index):
        """Handle tree item expansion to replace loading placeholders and set spans."""
        # Get the item from the current model (could be proxy)
        current_model = self.tree.model()
        
        # Map index back to source model if using proxy
        source_index = index
        if hasattr(current_model, 'mapToSource'):
            source_index = current_model.mapToSource(index)
        
        # Get the actual item from our LogModel
        item = self.model.itemFromIndex(source_index)
        if item and self.model.has_loading_placeholder(item):
            # Replace placeholder with real content
            self.model.replace_placeholder_with_content(item)
        
        # Always set column spans for children when an item is expanded
        # This ensures spans are set even for items that don't have placeholders
        self.expansion_manager._set_child_spans_for_item(index)
    
    def _get_selected_item_data(self):
        """Get unique ID from currently selected item for selection preservation."""
        selection = self.tree.selectionModel().selectedIndexes()
        if not selection:
            return None
            
        # Get the first selected index
        index = selection[0]
        model = self.tree.model()
        row = index.row()
        
        # Get the unique log ID from the timestamp column
        try:
            log_id = model.data(model.index(row, LogColumns.TIMESTAMP), ItemDataRole.LOG_ID)
            return log_id
        except:
            return None
    
    def _restore_selection(self, selected_log_id):
        """Restore selection to an item with the given unique ID."""
        if selected_log_id is None:
            return
            
        model = self.tree.model()
        
        # Search through the model to find the row with matching log ID
        for row in range(model.rowCount()):
            try:
                log_id = model.data(model.index(row, LogColumns.TIMESTAMP), ItemDataRole.LOG_ID)
                if log_id == selected_log_id:
                    # Found matching row, select it
                    index = model.index(row, LogColumns.TIMESTAMP)
                    self.tree.selectionModel().select(index, qt.QItemSelectionModel.Select | qt.QItemSelectionModel.Rows)
                    self.tree.scrollTo(index)  # Scroll to show the selected item
                    break
            except:
                continue
    
    
    def _parse_code_line_info(self, text):
        """Parse file path and line number from traceback or stack frame text."""
        import re
        
        # Pattern to match file paths and line numbers in traceback/stack frames
        # Examples:
        #   File "/path/to/file.py", line 123, in function_name
        #   /path/to/file.py:123
        patterns = [
            r'File "([^"]+)", line (\d+)',  # Standard Python traceback format
            r'([^:]+):(\d+)',               # Simple path:line format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                file_path = match.group(1)
                line_number = int(match.group(2))
                return {'file_path': file_path, 'line_number': line_number}
        
        return {'file_path': None, 'line_number': None}
    
    def _on_item_clicked(self, index):
        """Handle clicks on tree items to detect code line clicks."""
        if not index.isValid():
            return
        
        # Get the item data
        model = self.tree.model()
        
        # Map to source model if using proxy
        source_index = index
        if hasattr(model, 'mapToSource'):
            source_index = model.mapToSource(index)
        
        # Get the actual item from our LogModel
        item = self.model.itemFromIndex(source_index)
        if not item:
            return
        
        # Check if this is a code line (traceback_frame or stack_frame)
        data = item.data(ItemDataRole.PYTHON_DATA)
        if not data or not isinstance(data, dict):
            return
        
        item_type = data.get('type')
        if item_type not in ['traceback_frame', 'stack_frame']:
            return
        
        # Check if we have pre-parsed frame parts
        frame_parts = data.get('frame_parts')
        if frame_parts and frame_parts.get('has_file_ref'):
            file_path = frame_parts.get('file_path')
            line_number = frame_parts.get('line_number')
            
            if file_path and line_number:
                # Emit signal with file path and line number
                self.code_line_clicked.emit(file_path, line_number)
        else:
            # Fallback to on-demand parsing for older data
            text = data.get('text', '')
            file_info = self._parse_code_line_info(text)
            
            file_path = file_info.get('file_path')
            line_number = file_info.get('line_number')
            
            if file_path and line_number:
                self.code_line_clicked.emit(file_path, line_number)
    
    def _export_all_to_html(self):
        """Export all log entries to HTML file."""
        self._export_to_html(
            dialog_title="Export All Logs to HTML",
            default_filename="all_logs.html", 
            export_title="All Log Entries",
            use_filtered_model=False
        )
    
    def _export_filtered_to_html(self):
        """Export currently filtered log entries to HTML file."""
        self._export_to_html(
            dialog_title="Export Filtered Logs to HTML",
            default_filename="filtered_logs.html",
            export_title="Filtered Log Entries", 
            use_filtered_model=True
        )
    
    def _export_to_html(self, dialog_title, default_filename, export_title, use_filtered_model):
        """Common export logic for both all and filtered exports."""
        filename, _ = qt.QFileDialog.getSaveFileName(
            self,
            dialog_title,
            default_filename,
            "HTML Files (*.html)"
        )
        
        if filename:
            # Always expand all content in the source model first
            self._expand_all_content_for_export(self.model)
            
            if use_filtered_model:
                # Export filtered logs - get filter criteria and use current tree model
                filter_criteria = self.filter_input_widget.get_filter_strings()
                model_to_export = self.tree.model()
            else:
                # Export all logs - no filter criteria, use source model
                filter_criteria = None
                model_to_export = self.model
            
            self._export_model_to_html(model_to_export, filename, export_title, filter_criteria)
    
    def _expand_all_content_for_export(self, model):
        """Expand all lazy-loaded content in the model for export."""
        def expand_recursive(parent_item):
            # If this item has a loading placeholder, replace it with content
            if model.has_loading_placeholder(parent_item):
                model.replace_placeholder_with_content(parent_item)
            
            # Recursively expand all children
            for row in range(parent_item.rowCount()):
                child_item = parent_item.child(row, 0)
                if child_item:
                    expand_recursive(child_item)
        
        # Expand all top-level items
        for row in range(model.rowCount()):
            top_level_item = model.item(row, 0)
            if top_level_item:
                expand_recursive(top_level_item)
    
    def _export_model_to_html(self, model, filename, title, filter_criteria=None):
        """Export the given model data to HTML file."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                # Write HTML header
                f.write(HTML_EXPORT_HEADER.format(
                    title=title,
                    timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                # Add filter criteria summary if this is a filtered export
                if filter_criteria:
                    if filter_criteria:
                        filter_items = '\n'.join(
                            HTML_FILTER_ITEM.format(filter_expr=html.escape(filter_expr))
                            for filter_expr in filter_criteria
                        )
                        f.write(HTML_FILTER_CRITERIA_SECTION.format(filter_items=filter_items))
                    else:
                        f.write(HTML_NO_FILTERS)
                
                f.write(HTML_TABLE_HEADER)
                
                # Write log entries
                self._write_model_rows_to_html(f, model, qt.QModelIndex())
                
                # Write HTML footer
                f.write(HTML_EXPORT_FOOTER)
                
            # Success - no popup needed
            
        except Exception as e:
            # Show error message
            qt.QMessageBox.critical(
                self,
                "Export Error", 
                f"Failed to export logs:\\n{str(e)}"
            )
    
    def _write_model_rows_to_html(self, file, model, parent_index, indent_level=0):
        """Recursively write model rows to HTML file."""
        import html
        
        row_count = model.rowCount(parent_index)
        for row in range(row_count):
            # Get data from each column
            timestamp_index = model.index(row, LogColumns.TIMESTAMP, parent_index)
            source_index = model.index(row, LogColumns.SOURCE, parent_index) 
            logger_index = model.index(row, LogColumns.LOGGER, parent_index)
            level_index = model.index(row, LogColumns.LEVEL, parent_index)
            message_index = model.index(row, LogColumns.MESSAGE, parent_index)
            
            timestamp = model.data(timestamp_index, qt.Qt.DisplayRole) or ""
            source = model.data(source_index, qt.Qt.DisplayRole) or ""
            logger = model.data(logger_index, qt.Qt.DisplayRole) or ""
            level = model.data(level_index, qt.Qt.DisplayRole) or ""
            message = model.data(message_index, qt.Qt.DisplayRole) or ""
            
            # Determine CSS class based on content and level
            css_class = "child-entry" if indent_level > 0 else "log-entry"
            
            # Add level-specific CSS class
            level_upper = level.upper()
            for level_name, css_suffix in LEVEL_CSS_CLASSES.items():
                if level_name in level_upper:
                    css_class += f" {css_suffix}"
                    break
                
            # Check if this is an exception or traceback line
            python_data = model.data(timestamp_index, qt.Qt.UserRole)
            if python_data and isinstance(python_data, dict):
                data_type = python_data.get('type', '')
                if data_type == 'exception':
                    css_class += " exception"
                elif data_type in ['traceback_frame', 'stack_frame']:
                    css_class += " traceback"
            
            # Write the row with column span for child entries
            if indent_level > 0:
                # Child entries span all columns
                base_indent = "&nbsp;" * (indent_level * 4)  # Base hierarchy indentation
                
                # Use the timestamp column content as the main content for child entries
                content = timestamp if timestamp.strip() else message
                
                # Add extra indentation for code lines (lines that start with 4+ spaces)
                extra_indent = ""
                if content.startswith("    ") and not content.strip().startswith("File "):
                    # This is a code line, add extra indentation
                    extra_indent = "&nbsp;" * 8
                
                file.write(f"""            <tr class="{css_class}">
                <td colspan="5">{base_indent}{extra_indent}{html.escape(content)}</td>
            </tr>
""")
            else:
                # Top-level entries use all columns
                file.write(f"""            <tr class="{css_class}">
                <td class="timestamp">{html.escape(timestamp)}</td>
                <td>{html.escape(source)}</td>
                <td>{html.escape(logger)}</td>
                <td>{html.escape(level)}</td>
                <td>{html.escape(message)}</td>
            </tr>
""")
            
            # Recursively write child rows
            if model.rowCount(timestamp_index) > 0:
                self._write_model_rows_to_html(file, model, timestamp_index, indent_level + 1)


class QtLogHandlerSignals(qt.QObject):
    """QObject subclass that provides the new_record signal for QtLogHandler."""
    new_record = qt.Signal(object)


class QtLogHandler(logging.Handler):
    """Log handler that emits a Qt signal for each record."""
    
    def __init__(self):
        logging.Handler.__init__(self)
        self._signals = QtLogHandlerSignals()
        self.new_record = self._signals.new_record
        
    def handle(self, record):
        self.new_record.emit(record)
