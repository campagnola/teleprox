# Core LogViewer implementation with Qt integration and log handling
# Contains LogViewer widget, QtLogHandler, and main GUI functionality

import logging

from teleprox import qt
from .constants import ItemDataRole, LogColumns
from .export import export_logs_to_html, format_log_record_as_text
from .filtering import LogFilterProxyModel, USE_CHAINED_FILTERING
from .log_model import LogModel
from .widgets import FilterInputWidget, HighlightDelegate, SearchWidget


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
                    self._collect_expanded_items(
                        index, parent_log_id, current_relative_path, expanded_items
                    )

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


class LogViewer(qt.QWidget):
    """QWidget for displaying and filtering log messages.

    Arguments
    ---------
    logger : str | logging.Logger | None
        Logger name or instance to attach to. If None, no handler is attached.
    initial_filters : tuple of str
        Initial filter expressions to apply. Default is ('level: info',).
    parent : QWidget | None
        Parent widget (see Qt documentation).
    """

    # Signal emitted when user clicks on any code line (stack frame, traceback, etc.)
    code_line_clicked = qt.Signal(str, int)  # (file_path, line_number)

    # Signal for thread-safe message handling - messages from non-Qt threads are re-emitted here
    _message_from_thread_signal = qt.Signal(object)  # log record

    def __init__(self, logger='', initial_filters=('level: info',), parent=None):
        qt.QWidget.__init__(self, parent=parent)

        # Track filter changes for expansion state preservation
        self._last_filter_strings = []

        # Set up handler to send log records to this widget by signal
        self.handler = QtLogHandler()
        self.handler.new_record.connect(self.new_record)
        if logger is not None:
            if isinstance(logger, str):
                logger = logging.getLogger(logger)
            logger.addHandler(self.handler)

        # Set up thread-safe message handling - queued connection ensures GUI thread execution
        self._message_from_thread_signal.connect(self._process_record, qt.Qt.QueuedConnection)

        # Set up GUI
        self.layout = qt.QGridLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # Create top bar with search widget (left) and filter widget (right)
        top_bar_widget = qt.QWidget()
        top_bar_layout = qt.QHBoxLayout()
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        top_bar_layout.setSpacing(10)
        top_bar_widget.setLayout(top_bar_layout)

        # Add search widget (left side)
        self.search_widget = SearchWidget()
        top_bar_layout.addWidget(self.search_widget)

        # Add filter input widget (right side)
        self.filter_input_widget = FilterInputWidget()
        self.filter_input_widget.filters_changed.connect(self.apply_filters)
        self.filter_input_widget.export_all_requested.connect(self._export_all_to_html)
        self.filter_input_widget.export_filtered_requested.connect(self._export_filtered_to_html)
        top_bar_layout.addWidget(self.filter_input_widget)

        # Make both widgets take equal space
        top_bar_layout.setStretch(0, 1)  # Search widget
        top_bar_layout.setStretch(1, 1)  # Filter widget

        # Add top bar to main layout
        self.layout.addWidget(top_bar_widget, 0, 0)

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
        self.tree = qt.QTreeView()
        self.tree.setModel(tree_model)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)  # Make non-editable

        # Set up right-click context menu
        self.tree.setContextMenuPolicy(qt.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_row_context_menu)

        # Connect search widget to tree view
        self.search_widget.set_tree_view(self.tree)

        # Initialize expansion state manager now that tree is created
        self.expansion_manager = ExpansionStateManager(self.tree)

        # Set up custom header with context menu
        self.header = self.tree.header()
        self.header.setContextMenuPolicy(qt.Qt.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._show_header_context_menu)

        # Hide Task, Level, Host, Process, and Thread columns by default
        self.tree.setColumnHidden(LogColumns.LEVEL, True)  # Level column
        self.tree.setColumnHidden(LogColumns.TASK, True)  # Task column
        self.tree.setColumnHidden(LogColumns.HOST, True)  # Host column
        self.tree.setColumnHidden(LogColumns.PROCESS, True)  # Process column
        self.tree.setColumnHidden(LogColumns.THREAD, True)  # Thread column

        # Create custom delegate for efficient highlighting (will be set on models)
        self.highlight_delegate = HighlightDelegate(self)

        # Set delegate on initial model
        self.tree.setItemDelegate(self.highlight_delegate)

        self.tree.setSortingEnabled(True)
        # Ensure chronological sorting from the start
        self.ensure_chronological_sorting()

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

        # Set up autoscroll functionality - track if user wants to stay at bottom
        self._should_autoscroll = True  # Start with autoscroll enabled

        # Connect scroll bar changes to monitor user scrolling behavior
        scrollbar = self.tree.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll_changed)

        # detect changes to model length
        self.model.rowsInserted.connect(self._on_model_rows_inserted)

    def _on_scroll_changed(self, value):
        scrollbar = self.tree.verticalScrollBar()
        self._should_autoscroll = scrollbar.value() == scrollbar.maximum()

    def _on_model_rows_inserted(self, parent, start, end):
        if self._should_autoscroll:
            self.tree.scrollToBottom()

    def new_record(self, rec, sort=True):
        # Check if we're running in the Qt main thread
        current_thread = qt.QThread.currentThread()
        main_thread = qt.QApplication.instance().thread()

        if current_thread != main_thread:
            # Re-emit through queued signal to ensure GUI thread execution
            self._message_from_thread_signal.emit(rec)
            return

        # Process the record in the GUI thread
        self._process_record(rec, sort=sort)

    def _process_record(self, rec, sort=True):
        """Process a log record in the GUI thread."""
        self.model.append_record(rec)

        if sort:
            self.ensure_chronological_sorting()

    def set_records(self, *recs):
        """Replace all existing records with new ones, clearing selection and expansion but preserving filters."""
        # Clear selection before replacing data
        self.tree.selectionModel().clear()
        self.model.set_records()
        self.highlight_delegate.clear_highlight()

        # Replace all records in the model
        for i, rec in enumerate(recs):
            self.model.append_record(rec)
            if i % 20 == 0:
                qt.QApplication.processEvents()

        # Ensure proper sorting after bulk update
        self.ensure_chronological_sorting()

        # Trigger repaint to clear any highlighting
        self.tree.viewport().update()

    def apply_filters(self, filter_strings):
        """Apply the given filter strings to the proxy model."""
        # Save expansion state before changing filters
        expanded_paths = self.expansion_manager.save_state()
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
                # self._ensure_chronological_sorting()

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

    def ensure_chronological_sorting(self):
        """Ensure the tree view is sorted chronologically by timestamp."""
        current_model = self.tree.model()

        # Set sort role to use numeric timestamp from ItemDataRole.NUMERIC_TIMESTAMP
        if hasattr(current_model, 'setSortRole'):
            current_model.setSortRole(ItemDataRole.NUMERIC_TIMESTAMP)

        self.tree.sortByColumn(LogColumns.TIMESTAMP, qt.Qt.AscendingOrder)

    def _show_header_context_menu(self, position):
        """Show context menu for column visibility when right-clicking on header."""
        menu = qt.QMenu(self)

        # Use the column titles from LogColumns constants
        for i, header_text in enumerate(LogColumns.TITLES):
            action = qt.QAction(header_text, self)
            action.setCheckable(True)
            action.setChecked(not self.tree.isColumnHidden(i))
            action.triggered.connect(
                lambda checked, col=i: self._toggle_column_visibility(col, checked)
            )
            menu.addAction(action)

        menu.exec_(self.header.mapToGlobal(position))

    def _toggle_column_visibility(self, column, visible):
        """Toggle visibility of a column."""
        self.tree.setColumnHidden(column, not visible)

    def _show_row_context_menu(self, position):
        """Show context menu for row operations when right-clicking on a row."""
        # Get the index at the clicked position
        index = self.tree.indexAt(position)
        if not index.isValid():
            return

        menu = qt.QMenu(self)

        # Add copy action
        copy_action = qt.QAction("Copy", self)
        copy_action.selectedIndex = index
        copy_action.triggered.connect(self._copy_record_to_clipboard)
        menu.addAction(copy_action)

        # Show the menu at the cursor position
        menu.popup(self.tree.mapToGlobal(position))

    def _copy_record_to_clipboard(self):
        """Copy the formatted full record for the selected row to the clipboard."""
        index = self.sender().selectedIndex

        # If this is a child item, get the parent's index
        while index.parent().isValid():
            index = index.parent()
        unfiltered_index = self.map_index_to_model(index)
        cell_index = self.model.index(unfiltered_index.row(), 0, index.parent())
        log_record = self.model.itemFromIndex(cell_index).data(ItemDataRole.LOG_RECORD)
        if not log_record:
            return

        formatted_text = format_log_record_as_text(log_record)

        clipboard = qt.QApplication.clipboard()
        clipboard.setText(formatted_text)

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
            source_data = model.data(
                model.index(parent_index.row(), LogColumns.SOURCE), qt.Qt.DisplayRole
            )
            logger_data = model.data(
                model.index(parent_index.row(), LogColumns.LOGGER), qt.Qt.DisplayRole
            )
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
        # Map index back to source model if using proxy
        source_index = self.map_index_to_model(index)

        # Get the actual item from our LogModel
        item = self.model.itemFromIndex(source_index)
        self.model.item_expanded(item)

        # Always set column spans for children when an item is expanded
        # This ensures spans are set even for items that don't have placeholders
        self.expansion_manager._set_child_spans_for_item(index)

    def map_index_to_model(self, tree_index):
        """Map an item index to the top-level source model (mapping through all layers of proxies)."""
        return self.proxy_model.map_index_to_model(tree_index)

    def map_index_from_model(self, model_index):
        """Map an item index from the top-level source model to the current proxy model."""
        return self.proxy_model.map_index_from_model(model_index)

    def expand_item(self, item):
        """Expand an item in the tree view."""
        source_index = self.model.indexFromItem(item)
        tree_index = self.map_index_from_model(source_index)
        self.tree.expand(tree_index)

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
            return model.data(model.index(row, LogColumns.TIMESTAMP), ItemDataRole.LOG_ID)
        except (AttributeError, IndexError, RuntimeError):
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
                    self.tree.selectionModel().select(
                        index, qt.QItemSelectionModel.Select | qt.QItemSelectionModel.Rows
                    )
                    self.tree.scrollTo(index)  # Scroll to show the selected item
                    break
            except (AttributeError, IndexError, RuntimeError):
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
            r'([^:]+):(\d+)',  # Simple path:line format
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

        # Map to source model if using proxy
        source_index = self.map_index_to_model(index)

        # Get the actual item from our LogModel
        item = self.model.itemFromIndex(source_index)
        if not item:
            return

        # Check if this is a code line (traceback_frame or stack_frame)
        data = item.data(ItemDataRole.ROW_DETAILS)
        if not data or data.get('type') == 'primary_item':
            return

        item_type = data.get('type')
        if item_type not in ['traceback_frame', 'stack_frame']:
            return

        # Check if we have pre-parsed frame parts
        frame_parts = data.get('frame_parts')
        if frame_parts and frame_parts.get('has_file_ref'):
            file_path = frame_parts.get('file_path')
            line_number = frame_parts.get('line_number')
        else:
            # Fallback to on-demand parsing for older data
            text = data.get('text', '')
            file_info = self._parse_code_line_info(text)

            file_path = file_info.get('file_path')
            line_number = file_info.get('line_number')

        if file_path and line_number:
            # Emit signal with file path and line number
            self.code_line_clicked.emit(file_path, line_number)

    def _export_all_to_html(self):
        """Export all log entries to HTML file."""
        export_logs_to_html(
            self.model,
            "All Log Entries",
            filter_criteria=None,
            parent_widget=self,
            default_filename="all_logs.html",
        )

    def _export_filtered_to_html(self):
        """Export currently filtered log entries to HTML file."""
        filter_criteria = self.filter_input_widget.get_filter_strings()
        export_logs_to_html(
            self.tree.model(),
            "Filtered Log Entries",
            filter_criteria=filter_criteria,
            parent_widget=self,
            default_filename="filtered_logs.html",
        )


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
