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


# class LogTreeWidgetItem(qt.QTreeWidgetItem):
#     """Custom QTreeWidgetItem for displaying log messages."""
#     def __init__(self, rec):
#         # Extract relevant information from the log record
#         timestamp = rec.created
#         source = f"{rec.processName}/{rec.threadName}"
        
#         # Format level with number and name
#         level_number = rec.levelno
#         level_name = rec.levelname
#         level = f"{level_number} - {level_name}"
        
#         message = rec.getMessage()
#         time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)) + f'{timestamp % 1.0:.3f}'.lstrip('0')

#         super().__init__([time_str, source, level, message])

#         tc = thread_color(source)
#         self.setForeground(1, qt.QColor(tc))
#         level_color = level_colors.get(level_number, "#000000")
#         self.setForeground(2, qt.QColor(level_color))
#         self.setForeground(3, qt.QColor(level_color))


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
            # Disconnect signals before removal to prevent issues
            self.textChanged.disconnect()
            self.setParent(None)
            self.deleteLater()


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
        self.filter_input.setPlaceholderText("Enter filter criteria...")
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

class LogViewer(qt.QWidget):
    """QWidget for displaying and filtering log messages."""
    def __init__(self, logger='', parent=None):
        qt.QWidget.__init__(self, parent=parent)
        

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
        self.proxy_model = LogFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(qt.Qt.DisplayRole)  # Ensure sorting is based on display text
        
        self.tree = qt.QTreeView()
        self.tree.setModel(self.proxy_model)
        self.tree.setAlternatingRowColors(True)
        
        self.tree.setSortingEnabled(True)
        self.proxy_model.sort(0, qt.Qt.AscendingOrder)  # Sort by the first column (Timestamp) initially
        self.tree.sortByColumn(0, qt.Qt.AscendingOrder)
        self.layout.addWidget(self.tree, 1, 0)
        self.resize(1200, 600)
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 200)
        self.tree.setColumnWidth(2, 100)

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
        
        # Store additional data for filtering
        timestamp_item.setData(rec.created, qt.Qt.UserRole)  # Store numeric timestamp
        source_item.setData(rec.processName, qt.Qt.UserRole)  # Store process name
        source_item.setData(rec.threadName, qt.Qt.UserRole + 1)  # Store thread name
        logger_item.setData(rec.name, qt.Qt.UserRole)  # Store logger name
        level_item.setData(rec.levelno, qt.Qt.UserRole)  # Store numeric level
        message_item.setData(rec.getMessage(), qt.Qt.UserRole)  # Store message text
        
        # Add items to the model
        self.model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])

    def apply_filters(self, filter_strings):
        """Apply the given filter strings to the proxy model."""
        self.proxy_model.set_filters(filter_strings)


class LogFilterProxyModel(qt.QSortFilterProxyModel):
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
