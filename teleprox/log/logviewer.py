# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import logging
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


class LogTreeWidgetItem(qt.QTreeWidgetItem):
    """Custom QTreeWidgetItem for displaying log messages."""
    
    def __init__(self, rec):
        # Extract relevant information from the log record
        timestamp = rec.created
        source = f"{rec.processName}/{rec.threadName}"
        level = rec.levelname
        message = rec.getMessage()

        # Initialize the QTreeWidgetItem with the extracted information
        super().__init__([str(timestamp), source, level, message])
    """
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
        self.tree = qt.QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(['Timestamp', 'Source', 'Level', 'Message'])
        self.layout.addWidget(self.tree, 0, 0)
        
    def new_record(self, rec):
        # Create a new LogTreeWidgetItem
        item = LogTreeWidgetItem(rec)
        self.tree.addTopLevelItem(item)
        
        

class QtLogHandler(logging.Handler, qt.QObject):
    """Log handler that emits a Qt signal for each record.
    """
    new_record = qt.Signal(object)
    
    def __init__(self):
        logging.Handler.__init__(self)
        qt.QObject.__init__(self)
        
    def handle(self, record):
        self.new_record.emit(record)
