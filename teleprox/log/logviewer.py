# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import logging
import time
import re

from teleprox import qt


Stylesheet = """
    body {color: #000; font-family: sans;}
    .entry {}
    .error .message {color: #900}
    .warning .message {color: #740}
    .user .message {color: #009}
    .status .message {color: #090}
    .logExtra {margin-left: 40px;}
    .traceback {color: #555; height: 0px;}
    .timestamp {color: #000;}
"""


# Major log level colors
_level_color_stops = {
    0: (0, 0, 255),      # Blue
    10: (128, 128, 128), # Grey
    20: (0, 0, 0),       # Black
    30: (255, 128, 0),   # Orange
    40: (255, 0, 0),     # Red
    50: (128, 0, 0),     # Dark red
}

# Compute interpolated colors for all levels 0-50
level_colors = {}
for level in range(51):
    # Find the two stops to interpolate between
    lower_stop = max(k for k in _level_color_stops.keys() if k <= level)
    upper_stop = min(k for k in _level_color_stops.keys() if k >= level)
    
    # Interpolate between stops
    lower_r, lower_g, lower_b = _level_color_stops[lower_stop]
    upper_r, upper_g, upper_b = _level_color_stops[upper_stop]
    
    # Calculate interpolation factor
    factor = 1 if lower_stop == upper_stop else (level - lower_stop) / (upper_stop - lower_stop)
    
    # Interpolate each color component
    r = int(lower_r + (upper_r - lower_r) * factor)
    g = int(lower_g + (upper_g - lower_g) * factor)
    b = int(lower_b + (upper_b - lower_b) * factor)
    
    # Convert to hex format
    level_colors[level] = f"#{r:02X}{g:02X}{b:02X}"


available_thread_colors = ['#B00', '#0B0', '#00B', '#BB0', '#B0B', '#0BB', '#CA0', '#C0A', '#0CA', '#AC0', '#A0C', '#0AC']
thread_colors = {}
def thread_color(thread_name):
    global thread_colors
    try:
        return thread_colors[thread_name]
    except KeyError:
        thread_colors[thread_name] = available_thread_colors[len(thread_colors) % len(available_thread_colors)]
        return thread_colors[thread_name]


# Level cipher system for chained filtering
def level_to_cipher(level_int):
    """Convert integer level (0-50) to cipher character for filtering."""
    if 0 <= level_int <= 25:
        return chr(ord('a') + level_int)  # a-z
    elif 26 <= level_int <= 50:
        return chr(ord('A') + (level_int - 26))  # A-Y
    else:
        return 'Z'  # fallback for > 50


def parse_level_value(value_str):
    """Parse level value from user input, supporting both numbers and names."""
    # Standard Python logging level names
    level_names = {
        'debug': 10, 'info': 20, 'warning': 30, 'warn': 30,
        'error': 40, 'critical': 50, 'fatal': 50
    }
    
    value_str = value_str.strip().lower()
    
    # Try parsing as number first
    try:
        return int(value_str)
    except ValueError:
        pass
    
    # Try parsing as level name
    return level_names.get(value_str, 0)


def level_threshold_to_cipher_regex(threshold):
    """Convert level threshold to cipher regex pattern for levels >= threshold."""
    if threshold <= 0:
        return ".*"  # Match all levels
    
    # Create character class with ranges for better readability and performance
    patterns = []
    
    # Add lowercase range if needed (a-z covers 0-25)
    if threshold <= 25:
        start_char = level_to_cipher(threshold)
        patterns.append(f"{start_char}-z")
    
    # Add uppercase range if needed (A-Y covers 26-50)  
    if threshold <= 50:
        if threshold <= 25:
            patterns.append("A-Y")
        else:
            start_char = level_to_cipher(threshold)
            patterns.append(f"{start_char}-Y")
    
    # Add fallback for > 50
    if threshold <= 50:
        patterns.append("Z")
    
    if not patterns:
        return "Z"  # Only match fallback level
    
    # Create character class with ranges
    return f"[{''.join(patterns)}]"


class FilterTagWidget(qt.QLineEdit):
    """Widget representing an active filter with built-in clear button."""
    
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setClearButtonEnabled(True)
        self.textChanged.connect(self.adjust_width)
        self.textChanged.connect(self.check_for_removal)
        self.adjust_width()
        
        # Set size policy to fixed
        self.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
    
    def adjust_width(self):
        """Adjust the width of the line edit to fit its content."""
        font_metrics = self.fontMetrics()
        text_width = font_metrics.horizontalAdvance(self.text())
        self.setFixedWidth(text_width + 30)  # Add padding for clear button
    
    def check_for_removal(self):
        """Remove this widget if text is cleared."""
        if not self.text():
            # Store reference to parent widget to emit signal later
            parent_widget = self.parent()
            # Disconnect signals before removal to prevent issues
            self.textChanged.disconnect()
            self.setParent(None)
            self.deleteLater()
            # Emit signal after removal using timer
            if parent_widget and hasattr(parent_widget, '_emit_filters_changed'):
                qt.QTimer.singleShot(0, parent_widget._emit_filters_changed)


class FilterInputWidget(qt.QWidget):
    """Widget for entering and displaying active filters."""
    
    filters_changed = qt.Signal(list)  # Signal emitted when filters change
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = qt.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(3)
        self.setLayout(self.layout)
        
        self.filter_input = qt.QLineEdit()
        self.filter_input.setPlaceholderText("Filter  [level: N|debug|info|warn|error] [source: ...] [logger: ...] [message regex]")
        self.filter_input.returnPressed.connect(self.add_filter)
        self.filter_input.editingFinished.connect(self.add_filter)
        self.filter_input.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
        
        self.layout.addWidget(self.filter_input)
    
    def add_filter(self):
        text = self.filter_input.text().strip()
        if text:
            filter_tag = FilterTagWidget(text)
            filter_tag.textChanged.connect(self._emit_filters_changed)
            self.layout.insertWidget(self.layout.count() - 1, filter_tag)
            self.filter_input.clear()
            self._emit_filters_changed()
    
    def get_filter_strings(self):
        """Return a list of current filter strings."""
        filters = []
        for i in range(self.layout.count() - 1):  # Exclude the input widget
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, FilterTagWidget):
                filters.append(widget.text())
        return filters
    
    def _emit_filters_changed(self):
        """Emit the filters_changed signal with current filter strings."""
        self.filters_changed.emit(self.get_filter_strings())


class HighlightDelegate(qt.QStyledItemDelegate):
    """Custom delegate that handles row highlighting based on source/logger matching."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_source = None
        self.selected_logger = None
        
    def set_highlight_criteria(self, source, logger):
        """Set the source and logger to highlight."""
        self.selected_source = source
        self.selected_logger = logger
        
    def clear_highlight(self):
        """Clear highlighting criteria."""
        self.selected_source = None
        self.selected_logger = None
        
    def paint(self, painter, option, index):
        """Custom paint method that adds highlighting."""
        if self.selected_source is None:
            # No highlighting needed
            super().paint(painter, option, index)
            return
            
        # Get source and logger data directly from current model (no complex mapping needed)
        model = index.model()
        row = index.row()
        
        try:
            # Get data directly from the current model using data() method
            current_source = model.data(model.index(row, 1), qt.Qt.DisplayRole)
            current_logger = model.data(model.index(row, 2), qt.Qt.DisplayRole)
            
            if current_source and current_logger:
                
                # Determine if this row should be highlighted
                highlight_type = None
                if current_source == self.selected_source and current_logger == self.selected_logger:
                    highlight_type = 'source_logger'
                elif current_source == self.selected_source:
                    highlight_type = 'source'
                
                # Apply highlighting by modifying the option
                if highlight_type:
                    # Get base color for theme detection
                    palette = option.palette
                    base_color = palette.color(palette.Base)
                    
                    # Create highlight colors based on theme
                    if base_color.lightness() > 128:  # Light theme
                        if highlight_type == 'source_logger':
                            highlight_color = qt.QColor(255, 255, 0, 60)  # Stronger yellow
                        else:
                            highlight_color = qt.QColor(255, 255, 0, 30)  # Light yellow
                    else:  # Dark theme
                        if highlight_type == 'source_logger':
                            highlight_color = qt.QColor(255, 255, 0, 80)  # Stronger yellow
                        else:
                            highlight_color = qt.QColor(255, 255, 0, 40)  # Muted yellow
                    
                    # Draw custom background
                    painter.fillRect(option.rect, highlight_color)
        except:
            # If anything fails, just paint normally
            pass
            
        # Paint the item content
        super().paint(painter, option, index)


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


class PythonLogFilterProxyModel(qt.QSortFilterProxyModel):
    """Custom proxy model that supports advanced filtering of log records."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filters = []
        
    def set_filters(self, filter_strings):
        """Set the filter strings and invalidate the filter."""
        self.filters = filter_strings
        self.invalidateFilter()
        
    def filterAcceptsRow(self, source_row, source_parent):
        """Return True if the row should be included in the filtered model."""
        if not self.filters:
            return True
            
        model = self.sourceModel()
        
        # Get all the items for this row
        timestamp_item = model.item(source_row, 0)
        source_item = model.item(source_row, 1)
        logger_item = model.item(source_row, 2)
        level_item = model.item(source_row, 3)
        message_item = model.item(source_row, 4)
        
        # Extract data for filtering
        timestamp = timestamp_item.data(qt.Qt.UserRole) if timestamp_item else 0
        process_name = source_item.data(qt.Qt.UserRole) if source_item else ""
        thread_name = source_item.data(qt.Qt.UserRole + 1) if source_item else ""
        logger_name = logger_item.data(qt.Qt.UserRole) if logger_item else ""
        level_num = level_item.data(qt.Qt.UserRole) if level_item else 0
        message_text = message_item.data(qt.Qt.UserRole) if message_item else ""
        
        # Display text for generic search
        display_texts = [
            timestamp_item.text() if timestamp_item else "",
            source_item.text() if source_item else "",
            logger_name,
            level_item.text() if level_item else "",
            message_text
        ]
        combined_text = " ".join(display_texts).lower()
        
        # Check each filter
        for filter_str in self.filters:
            if not filter_str.strip():
                continue
                
            filter_str = filter_str.strip()
            
            # Parse field-specific filters
            if self._matches_level_filter(filter_str, level_num):
                continue
            elif self._matches_logger_filter(filter_str, logger_name):
                continue
            elif self._matches_thread_filter(filter_str, thread_name):
                continue
            elif self._matches_process_filter(filter_str, process_name):
                continue
            elif self._matches_generic_filter(filter_str, combined_text):
                continue
            else:
                # Filter doesn't match, exclude this row
                return False
                
        return True
        
    def _matches_level_filter(self, filter_str, level_num):
        """Check if filter matches level criteria (e.g., 'level > 10')."""
        level_match = re.match(r'level\s*([><=]+)\s*(\d+)', filter_str, re.IGNORECASE)
        if level_match:
            operator, value = level_match.groups()
            value = int(value)
            if operator == '>':
                return level_num > value
            elif operator == '>=':
                return level_num >= value
            elif operator == '<':
                return level_num < value
            elif operator == '<=':
                return level_num <= value
            elif operator == '=' or operator == '==':
                return level_num == value
        return False
        
    def _matches_logger_filter(self, filter_str, logger_name):
        """Check if filter matches logger criteria (e.g., 'logger: myLogger')."""
        logger_match = re.match(r'logger:\s*(.+)', filter_str, re.IGNORECASE)
        if logger_match:
            pattern = logger_match.group(1).strip()
            try:
                return bool(re.search(pattern, logger_name, re.IGNORECASE))
            except re.error:
                # If regex is invalid, do literal match
                return pattern.lower() in logger_name.lower()
        return False
        
    def _matches_thread_filter(self, filter_str, thread_name):
        """Check if filter matches thread criteria (e.g., 'thread: main.*')."""
        thread_match = re.match(r'thread:\s*(.+)', filter_str, re.IGNORECASE)
        if thread_match:
            pattern = thread_match.group(1).strip()
            try:
                return bool(re.search(pattern, thread_name, re.IGNORECASE))
            except re.error:
                # If regex is invalid, do literal match
                return pattern.lower() in thread_name.lower()
        return False
        
    def _matches_process_filter(self, filter_str, process_name):
        """Check if filter matches process criteria (e.g., 'process: worker.*')."""
        process_match = re.match(r'process:\s*(.+)', filter_str, re.IGNORECASE)
        if process_match:
            pattern = process_match.group(1).strip()
            try:
                return bool(re.search(pattern, process_name, re.IGNORECASE))
            except re.error:
                # If regex is invalid, do literal match
                return pattern.lower() in process_name.lower()
        return False
        
    def _matches_generic_filter(self, filter_str, combined_text):
        """Check if filter matches any text in the record."""
        try:
            return bool(re.search(filter_str, combined_text, re.IGNORECASE))
        except re.error:
            # If regex is invalid, do literal match
            return filter_str.lower() in combined_text


# Chained filtering implementation
class FieldFilterProxy(qt.QSortFilterProxyModel):
    """Base class for field-specific filtering using Qt native regex."""
    
    def __init__(self, field_name, column, parent=None):
        super().__init__(parent)
        self.field_name = field_name
        self.column = column
        self.setFilterKeyColumn(column)
        self.setFilterCaseSensitivity(qt.Qt.CaseInsensitive)
        self.filter_pattern = ""
    
    def set_filter_pattern(self, pattern):
        """Set the filter pattern for this field."""
        self.filter_pattern = pattern
        if pattern:
            self.setFilterRegExp(pattern)
        else:
            self.setFilterRegExp("")


class LevelCipherFilterProxy(FieldFilterProxy):
    """Handles level filtering using cipher data from UserRole+2."""
    
    def __init__(self, parent=None):
        super().__init__("level", 3, parent)  # Column 3 is level column
        self.setFilterRole(qt.Qt.UserRole + 2)  # Filter on cipher data
        self.setFilterCaseSensitivity(qt.Qt.CaseSensitive)  # Cipher patterns are case-sensitive
    
    def set_level_filter(self, level_value):
        """Set level filter using threshold (levels >= threshold)."""
        if not level_value:
            self.set_filter_pattern("")
            return
            
        threshold = parse_level_value(level_value)
        cipher_regex = level_threshold_to_cipher_regex(threshold)
        self.set_filter_pattern(cipher_regex)


class ChainedLogFilterManager:
    """Manages a chain of proxy models for efficient filtering."""
    
    def __init__(self, source_model, parent=None):
        self.source_model = source_model
        self.proxies = {}
        self.chain_order = []
        self.final_model = source_model
        
        # Available proxy types mapped to column names where possible
        self.proxy_types = {
            'level': lambda: LevelCipherFilterProxy(),
            'logger': lambda: FieldFilterProxy('logger', 2),
            'source': lambda: FieldFilterProxy('source', 1),
            'message': lambda: FieldFilterProxy('message', 4),
        }
    
    def set_filters(self, filter_strings):
        """Parse filters and build/update proxy chain dynamically."""
        if not filter_strings:
            # No filters, use source model directly
            self._rebuild_chain([])
            return
        
        # Parse filters to determine needed proxies
        filter_configs = []
        
        for filter_str in filter_strings:
            filter_str = filter_str.strip()

            if not filter_str:
                continue                
            
            # Parse field-specific filters
            key, colon, value = filter_str.partition(':')
            if colon:
                field = key.strip().lower()
                value = value.strip()
                
                if field not in self.proxy_types:
                    continue

                filter_configs.append((field, value))
            else:
                # Generic search terms apply to message column
                filter_configs.append(('message', filter_str))
        
        # Rebuild chain with filter configs
        self._rebuild_chain(filter_configs)
    
    def _rebuild_chain(self, filter_configs):
        """Rebuild the proxy chain with the specified filter configs in order."""
        # filter_configs is a list of (field, value) tuples in the order they should be applied
        
        # Clear existing proxies
        self.proxies.clear()
        self.chain_order.clear()
        
        # If no filters, use source model directly
        if not filter_configs:
            self.final_model = self.source_model
            return
        
        # Create proxies in the exact order specified
        proxy_list = []
        for i, (field, value) in enumerate(filter_configs):
            if field not in self.proxy_types:
                continue
                
            # Create a unique proxy for each filter (even if same field type)
            proxy = self.proxy_types[field]()
            self._apply_filter_to_proxy(proxy, field, value)
            
            # Use unique key for each proxy to allow multiple of same type
            proxy_key = f"{field}_{i}"
            self.proxies[proxy_key] = proxy
            self.chain_order.append(proxy_key)
            proxy_list.append(proxy)
        
        # Chain the proxies in order: source -> proxy1 -> proxy2 -> ... -> final
        if not proxy_list:
            self.final_model = self.source_model
            return
            
        current_model = self.source_model
        for proxy in proxy_list:
            proxy.setSourceModel(current_model)
            current_model = proxy
        
        self.final_model = current_model
    
    def _apply_filter_to_proxy(self, proxy, field, value):
        """Apply the filter value to the appropriate proxy."""
        if field == 'level':
            proxy.set_level_filter(value)
        elif field in ['source', 'logger', 'message']:
            # For text fields, create regex to match the field
            escaped_pattern = re.escape(value)
            regex_pattern = f".*{escaped_pattern}.*"
            proxy.set_filter_pattern(regex_pattern)
        else:
            # Fallback for any other text fields
            escaped_pattern = re.escape(value)
            regex_pattern = f".*{escaped_pattern}.*"
            proxy.set_filter_pattern(regex_pattern)
    
    def rowCount(self):
        """Return row count of final model."""
        return self.final_model.rowCount()


# Create type alias for easy switching between implementations
# Change this line to switch between Python and Chained filtering
USE_CHAINED_FILTERING = True

if USE_CHAINED_FILTERING:
    LogFilterProxyModel = ChainedLogFilterManager
else:
    LogFilterProxyModel = PythonLogFilterProxyModel


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
