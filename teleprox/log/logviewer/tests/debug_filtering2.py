#!/usr/bin/env python3
"""
Debug script to test a simple filter proxy to understand the Qt filtering issue.
"""

import sys
from teleprox import qt
from teleprox.log.logviewer.utils import level_to_cipher, level_threshold_to_cipher_regex

app = qt.QApplication(sys.argv)

class DebugLevelProxy(qt.QSortFilterProxyModel):
    """Debug version with explicit filterAcceptsRow to see what's happening."""
    
    def __init__(self):
        super().__init__()
        self.setFilterKeyColumn(3)  # Level column
        self.filter_pattern = ""
        self.accepted_count = 0
        self.rejected_count = 0
    
    def set_pattern(self, pattern):
        self.filter_pattern = pattern
        self.accepted_count = 0
        self.rejected_count = 0
        self.invalidateFilter()
    
    def filterAcceptsRow(self, source_row, source_parent):
        if not self.filter_pattern:
            return True
            
        model = self.sourceModel()
        level_item = model.item(source_row, 3)
        
        if level_item:
            cipher = level_item.data(qt.Qt.UserRole + 2)
            if cipher:
                regex = qt.QRegExp(self.filter_pattern)
                matches = regex.exactMatch(cipher)
                
                level_val = level_item.data(qt.Qt.UserRole)
                print(f"Row {source_row}: level={level_val}, cipher='{cipher}', pattern='{self.filter_pattern}', matches={matches}")
                
                if matches:
                    self.accepted_count += 1
                else:
                    self.rejected_count += 1
                    
                return matches
        
        return False

# Create test model
model = qt.QStandardItemModel()
model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message'])

test_data = [
    (1000.0, "main", "MainThread", "app.core", 10, "Debug startup"),
    (1001.0, "main", "MainThread", "app.ui", 20, "UI initialized"),
    (1002.0, "worker", "Thread-1", "app.core", 20, "Worker started"),
    (1003.0, "worker", "Thread-1", "app.network", 30, "Network warning"),
    (1004.0, "main", "MainThread", "app.core", 40, "Core error"),
    (1005.0, "main", "MainThread", "app.ui", 50, "UI critical error"),
]

for timestamp, process, thread, logger, level, message in test_data:
    timestamp_item = qt.QStandardItem(f"{timestamp:.1f}")
    source_item = qt.QStandardItem(f"{process}/{thread}")
    logger_item = qt.QStandardItem(logger)
    level_item = qt.QStandardItem(str(level))
    level_item.setData(level, qt.Qt.UserRole)
    level_item.setData(level_to_cipher(level), qt.Qt.UserRole + 2)
    message_item = qt.QStandardItem(message)
    
    model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])

print(f"Source model rows: {model.rowCount()}")

# Test the debug proxy
proxy = DebugLevelProxy()
proxy.setSourceModel(model)

print(f"Proxy rows before filter: {proxy.rowCount()}")

# Apply level >= 20 filter
threshold = 20
pattern = level_threshold_to_cipher_regex(threshold)
print(f"Applying pattern: {pattern}")

proxy.set_pattern(pattern)

print(f"Proxy rows after filter: {proxy.rowCount()}")
print(f"Accepted: {proxy.accepted_count}, Rejected: {proxy.rejected_count}")

sys.exit(0)