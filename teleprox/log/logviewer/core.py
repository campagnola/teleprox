# ABOUTME: Core LogViewer implementation with Qt integration and log handling
# ABOUTME: Contains LogViewer widget, QtLogHandler, and main GUI functionality

import logging
import time
import traceback

from teleprox import qt
from .utils import level_colors, thread_color, level_to_cipher
from .widgets import FilterInputWidget, HighlightDelegate
from .filtering import LogFilterProxyModel, USE_CHAINED_FILTERING
from .constants import ItemDataRole


class LogModel(qt.QStandardItemModel):
    """Custom model that supports lazy loading of exception details using dummy placeholders."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def _create_exception_children(self, record):
        """Create child items for exception information."""
        children = []
        
        # Handle exc_info
        if hasattr(record, 'exc_info') and record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            if exc_type and exc_value:
                # Exception type and message
                exc_msg = f"{exc_type.__name__}: {exc_value}"
                exc_row = self._create_child_row("", exc_msg, {
                    'type': 'exception',
                    'text': exc_msg,
                    'parent_record': record
                }, record)
                children.append(exc_row)
                
                # Traceback frames
                if exc_tb:
                    tb_lines = traceback.format_tb(exc_tb)
                    for i, line in enumerate(tb_lines):
                        frame_row = self._create_child_row("", line.strip(), {
                            'type': 'traceback_frame',
                            'text': line.strip(),
                            'frame_number': i + 1,
                            'parent_record': record
                        }, record)
                        children.append(frame_row)
        
        # Handle exc_text
        elif hasattr(record, 'exc_text') and record.exc_text:
            lines = record.exc_text.split('\n')
            for i, line in enumerate(lines):
                if line.strip():
                    line_row = self._create_child_row("", line.strip(), {
                        'type': 'exception_text',
                        'text': line.strip(),
                        'line_number': i + 1,
                        'parent_record': record
                    }, record)
                    children.append(line_row)
        
        # Handle stack_info
        if hasattr(record, 'stack_info') and record.stack_info:
            lines = record.stack_info.split('\n')
            for i, line in enumerate(lines):
                if line.strip():
                    stack_row = self._create_child_row("", line.strip(), {
                        'type': 'stack_frame',
                        'text': line.strip(),
                        'frame_number': i + 1,
                        'parent_record': record
                    }, record)
                    children.append(stack_row)
        
        return children
    
    def _create_child_row(self, label, message, data_dict, parent_record):
        """Create a standardized child row for exception details."""
        # Create items for each column
        timestamp_item = qt.QStandardItem("")  # Empty timestamp for child
        source_item = qt.QStandardItem("")     # Empty source for child
        logger_item = qt.QStandardItem("")     # Empty logger for child  
        level_item = qt.QStandardItem("")      # Empty level for child
        message_item = qt.QStandardItem(message)  # Exception/stack message
        
        # Store data in the first item (timestamp column)
        timestamp_item.setData(data_dict, ItemDataRole.PYTHON_DATA)
        
        # INHERIT PARENT'S FILTER DATA so Qt native filtering includes children
        # This allows children to pass the same filters as their parents
        timestamp_item.setData(parent_record.created, ItemDataRole.NUMERIC_TIMESTAMP)
        source_item.setData(parent_record.processName, ItemDataRole.PROCESS_NAME)
        source_item.setData(parent_record.threadName, ItemDataRole.THREAD_NAME)
        logger_item.setData(parent_record.name, ItemDataRole.LOGGER_NAME)
        level_item.setData(parent_record.levelno, ItemDataRole.LEVEL_NUMBER)
        level_item.setData(self._get_level_cipher(parent_record.levelno), ItemDataRole.LEVEL_CIPHER)
        message_item.setData(message, ItemDataRole.MESSAGE_TEXT)  # Child's own message
        
        # Set colors to differentiate from main log entries
        level_item.setForeground(qt.QColor("#666666"))  # Gray for child labels
        message_item.setForeground(qt.QColor("#444444"))  # Dark gray for child text
        
        return [timestamp_item, source_item, logger_item, level_item, message_item]
    
    def _get_level_cipher(self, level_int):
        """Get level cipher for a given level number."""
        from .utils import level_to_cipher
        return level_to_cipher(level_int)
    
    def add_loading_placeholder(self, parent_item, record):
        """Add a dummy 'loading...' child to indicate expandable content."""
        # Create loading placeholder row
        loading_row = self._create_loading_placeholder_row()
        
        # Add the placeholder as child
        parent_item.appendRow(loading_row)
        
        # Store the record data in the parent for later expansion
        parent_item.setData(record, ItemDataRole.PYTHON_DATA)
        parent_item.setData(True, ItemDataRole.HAS_CHILDREN)
    
    def _create_loading_placeholder_row(self):
        """Create a dummy 'loading...' row."""
        timestamp_item = qt.QStandardItem("")
        source_item = qt.QStandardItem("")
        logger_item = qt.QStandardItem("")
        level_item = qt.QStandardItem("⏳ Loading...")
        message_item = qt.QStandardItem("Click to expand exception details")
        
        # Mark as loading placeholder
        timestamp_item.setData(True, ItemDataRole.IS_LOADING_PLACEHOLDER)
        
        # Style the placeholder
        level_item.setForeground(qt.QColor("#888888"))
        message_item.setForeground(qt.QColor("#888888"))
        message_item.setFont(qt.QFont("Arial", 8, qt.QFont.StyleItalic))
        
        return [timestamp_item, source_item, logger_item, level_item, message_item]
    
    def has_loading_placeholder(self, parent_item):
        """Check if item has a loading placeholder child."""
        if parent_item.rowCount() == 1:
            child = parent_item.child(0, 0)  # Check timestamp column
            return child and child.data(ItemDataRole.IS_LOADING_PLACEHOLDER) is True
        return False
    
    def replace_placeholder_with_content(self, parent_item):
        """Replace loading placeholder with actual exception details."""
        if not self.has_loading_placeholder(parent_item):
            return
        
        # Get the stored log record
        log_record = parent_item.data(ItemDataRole.PYTHON_DATA)
        if log_record is None:
            return
        
        # Remove the placeholder child
        parent_item.removeRow(0)
        
        # Create and add real exception children
        children = self._create_exception_children(log_record)
        for child_row in children:
            parent_item.appendRow(child_row)
        
        # Mark as fetched
        parent_item.setData(True, ItemDataRole.CHILDREN_FETCHED)


class LogViewer(qt.QWidget):
    """QWidget for displaying and filtering log messages."""
    
    # Signal emitted when user clicks on a stack frame
    stack_frame_clicked = qt.Signal(str, int)  # (filename, line_number)
    
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
        
        # Set up GUI
        self.layout = qt.QGridLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # Add filter input widget
        self.filter_input_widget = FilterInputWidget()
        self.filter_input_widget.filters_changed.connect(self.apply_filters)
        self.layout.addWidget(self.filter_input_widget, 0, 0)

        self.model = LogModel()
        self.model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message'])
        
        # Create custom proxy model for advanced filtering
        if USE_CHAINED_FILTERING:
            self.proxy_model = LogFilterProxyModel(self.model)
            tree_model = self.proxy_model.final_model
        else:
            self.proxy_model = LogFilterProxyModel()
            self.proxy_model.setSourceModel(self.model)
            tree_model = self.proxy_model
        
        self.tree = qt.QTreeView()
        self.tree.setModel(tree_model)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)  # Make non-editable
        
        # Set up custom header with context menu
        self.header = self.tree.header()
        self.header.setContextMenuPolicy(qt.Qt.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._show_header_context_menu)
        
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
        
        self.layout.addWidget(self.tree, 1, 0)
        self.resize(1200, 600)
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 200)
        self.tree.setColumnWidth(2, 100)
        
        # Apply initial filters if provided
        if initial_filters:
            # Add initial filters to the UI
            for filter_expr in initial_filters:
                self.filter_input_widget.filter_input.setText(filter_expr)
                self.filter_input_widget.add_filter()
            
            # Apply the filters
            self.apply_filters(list(initial_filters))

    def new_record(self, rec):
        # Create a new row for the log record
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.created)) + f'{rec.created % 1.0:.3f}'.lstrip('0')
        source = f"{rec.processName}/{rec.threadName}"
        logger_name = rec.name
        level = f"{rec.levelno} - {rec.levelname}"
        message = rec.getMessage()
        
        # Create items for each column
        timestamp_item = qt.QStandardItem(timestamp)
        source_item = qt.QStandardItem(source)
        logger_item = qt.QStandardItem(logger_name)
        level_item = qt.QStandardItem(level)
        message_item = qt.QStandardItem(message)
        
        # Set colors based on log level
        level_color = level_colors.get(rec.levelno, "#000000")
        source_color = thread_color(source)
        source_item.setForeground(qt.QColor(source_color))
        level_item.setForeground(qt.QColor(level_color))
        message_item.setForeground(qt.QColor(level_color))
        
        # Assign unique ID to this log entry
        log_id = self._next_log_id
        self._next_log_id += 1
        
        # Store data using named constants
        timestamp_item.setData(rec, ItemDataRole.PYTHON_DATA)  # Store complete log record
        timestamp_item.setData(rec.created, ItemDataRole.NUMERIC_TIMESTAMP)  # Store numeric timestamp
        timestamp_item.setData(log_id, ItemDataRole.LOG_ID)  # Store unique log ID
        source_item.setData(rec.processName, ItemDataRole.PROCESS_NAME)  # Store process name
        source_item.setData(rec.threadName, ItemDataRole.THREAD_NAME)  # Store thread name
        logger_item.setData(rec.name, ItemDataRole.LOGGER_NAME)  # Store logger name
        level_item.setData(rec.levelno, ItemDataRole.LEVEL_NUMBER)  # Store numeric level
        level_item.setData(level_to_cipher(rec.levelno), ItemDataRole.LEVEL_CIPHER)  # Store level cipher
        message_item.setData(rec.getMessage(), ItemDataRole.MESSAGE_TEXT)  # Store message text
        
        # Add items to the model
        self.model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])
        
        # Check if this record has exception information for lazy loading
        has_exception_info = (
            (hasattr(rec, 'exc_info') and rec.exc_info and rec.exc_info != (None, None, None)) or
            (hasattr(rec, 'exc_text') and rec.exc_text) or
            (hasattr(rec, 'stack_info') and rec.stack_info)
        )
        
        if has_exception_info:
            # Add loading placeholder for lazy expansion
            self.model.add_loading_placeholder(timestamp_item, rec)
        
        # Ensure sorting is maintained when adding new data
        self._ensure_chronological_sorting()

    def apply_filters(self, filter_strings):
        """Apply the given filter strings to the proxy model."""
        old_final_model = self.proxy_model.final_model if USE_CHAINED_FILTERING else None
        
        # Save expansion state before changing filters
        expanded_log_ids = self._save_expansion_state()
        # print(f"Saved expansion state: {expanded_log_ids}")
        
        self.proxy_model.set_filters(filter_strings)
        
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
                self._restore_expansion_state(expanded_log_ids)
        
        # Always restore expansion state after any filter change
        # (in case we're not using chained filtering or model didn't change)
        if filter_strings != self._last_filter_strings:
            # print(f"Restoring expansion state: {expanded_log_ids}")
            self._restore_expansion_state(expanded_log_ids)
        
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
            current_model.sort(0, qt.Qt.AscendingOrder)
        
        # Also tell the tree view about the sorting
        self.tree.sortByColumn(0, qt.Qt.AscendingOrder)
    
    def _show_header_context_menu(self, position):
        """Show context menu for column visibility when right-clicking on header."""
        menu = qt.QMenu(self)
        
        # Get column headers
        headers = ['Timestamp', 'Source', 'Logger', 'Level', 'Message']
        
        for i, header_text in enumerate(headers):
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
        
        # Get data directly from the current model using the data() method
        # This avoids manual index mapping through proxy chains
        source_data = model.data(model.index(index.row(), 1), qt.Qt.DisplayRole)
        logger_data = model.data(model.index(index.row(), 2), qt.Qt.DisplayRole)
        
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
        """Handle tree item expansion to replace loading placeholders."""
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
            log_id = model.data(model.index(row, 0), ItemDataRole.LOG_ID)
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
                log_id = model.data(model.index(row, 0), ItemDataRole.LOG_ID)
                if log_id == selected_log_id:
                    # Found matching row, select it
                    index = model.index(row, 0)
                    self.tree.selectionModel().select(index, qt.QItemSelectionModel.Select | qt.QItemSelectionModel.Rows)
                    self.tree.scrollTo(index)  # Scroll to show the selected item
                    break
            except:
                continue
    
    def _save_expansion_state(self):
        """Save the expansion state of all items using their unique LOG_IDs."""
        expanded_log_ids = set()
        current_model = self.tree.model()
        
        if current_model is None:
            return expanded_log_ids
        
        # Walk through all visible items and check if they're expanded
        for row in range(current_model.rowCount()):
            index = current_model.index(row, 0)
            if self.tree.isExpanded(index):
                # Get the LOG_ID for this item
                log_id = current_model.data(index, ItemDataRole.LOG_ID)
                # print(f"  Found expanded item at row {row} with LOG_ID {log_id}")
                if log_id is not None:
                    expanded_log_ids.add(log_id)
        
        return expanded_log_ids
    
    def _restore_expansion_state(self, expanded_log_ids):
        """Restore expansion state for items with matching LOG_IDs."""
        if not expanded_log_ids:
            return
            
        current_model = self.tree.model()
        if current_model is None:
            return
        
        # Walk through all visible items and expand those that should be expanded
        for row in range(current_model.rowCount()):
            index = current_model.index(row, 0)
            log_id = current_model.data(index, ItemDataRole.LOG_ID)
            
            if log_id in expanded_log_ids:
                # print(f"  Expanding item at row {row} with LOG_ID {log_id}")
                # Ensure the item has children before trying to expand
                if current_model.rowCount(index) > 0:
                    self.tree.expand(index)
                # else:
                #     print(f"    Item has no children, skipping expansion")


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