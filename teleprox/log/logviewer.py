# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import logging
import time

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
        self.layout.addWidget(self.filter_input_widget, 0, 0)

        self.model = qt.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message'])
        
        self.proxy_model = qt.QSortFilterProxyModel()
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
        
        # Add items to the model
        self.model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])


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
