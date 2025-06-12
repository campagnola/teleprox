# ABOUTME: Core LogViewer implementation with Qt integration and log handling
# ABOUTME: Contains LogViewer widget, QtLogHandler, and main GUI functionality

import logging
import time

from teleprox import qt
from .utils import level_colors, thread_color, level_to_cipher
from .widgets import FilterInputWidget, HighlightDelegate
from .filtering import LogFilterProxyModel, USE_CHAINED_FILTERING


class LogViewer(qt.QWidget):
    """QWidget for displaying and filtering log messages."""
    def __init__(self, logger='', initial_filters=('level: info',), parent=None):
        qt.QWidget.__init__(self, parent=parent)
        
        # Unique ID counter for log entries
        self._next_log_id = 0

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

        self.model = qt.QStandardItemModel()
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
        
        # Store additional data for filtering
        timestamp_item.setData(rec.created, qt.Qt.UserRole)  # Store numeric timestamp
        timestamp_item.setData(log_id, qt.Qt.UserRole + 3)  # Store unique log ID
        source_item.setData(rec.processName, qt.Qt.UserRole)  # Store process name
        source_item.setData(rec.threadName, qt.Qt.UserRole + 1)  # Store thread name
        logger_item.setData(rec.name, qt.Qt.UserRole)  # Store logger name
        level_item.setData(rec.levelno, qt.Qt.UserRole)  # Store numeric level
        level_item.setData(level_to_cipher(rec.levelno), qt.Qt.UserRole + 2)  # Store level cipher
        message_item.setData(rec.getMessage(), qt.Qt.UserRole)  # Store message text
        
        # Add items to the model
        self.model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])
        
        # Ensure sorting is maintained when adding new data
        self._ensure_chronological_sorting()

    def apply_filters(self, filter_strings):
        """Apply the given filter strings to the proxy model."""
        old_final_model = self.proxy_model.final_model if USE_CHAINED_FILTERING else None
        
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
        
    def _ensure_chronological_sorting(self):
        """Ensure the tree view is sorted chronologically by timestamp."""
        current_model = self.tree.model()
        
        # Set sort role to use numeric timestamp from UserRole
        if hasattr(current_model, 'setSortRole'):
            current_model.setSortRole(qt.Qt.UserRole)
        
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
            log_id = model.data(model.index(row, 0), qt.Qt.UserRole + 3)
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
                log_id = model.data(model.index(row, 0), qt.Qt.UserRole + 3)
                if log_id == selected_log_id:
                    # Found matching row, select it
                    index = model.index(row, 0)
                    self.tree.selectionModel().select(index, qt.QItemSelectionModel.Select | qt.QItemSelectionModel.Rows)
                    self.tree.scrollTo(index)  # Scroll to show the selected item
                    break
            except:
                continue


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