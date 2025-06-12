#!/usr/bin/env python3
"""
Debug script to understand what's happening with level filtering.
"""

import sys
from teleprox import qt
from teleprox.log.logviewer.utils import (
    level_to_cipher, 
    parse_level_value, 
    level_threshold_to_cipher_regex
)
from teleprox.log.logviewer.filtering import ChainedLogFilterManager

app = qt.QApplication(sys.argv)

# Create test model exactly like in the test
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

print("Adding test data...")
for i, (timestamp, process, thread, logger, level, message) in enumerate(test_data):
    timestamp_item = qt.QStandardItem(f"{timestamp:.1f}")
    timestamp_item.setData(timestamp, qt.Qt.UserRole)
    
    source_item = qt.QStandardItem(f"{process}/{thread}")
    source_item.setData(process, qt.Qt.UserRole)
    source_item.setData(thread, qt.Qt.UserRole + 1)
    
    logger_item = qt.QStandardItem(logger)
    logger_item.setData(logger, qt.Qt.UserRole)
    
    level_item = qt.QStandardItem(str(level))
    level_item.setData(level, qt.Qt.UserRole)
    cipher = level_to_cipher(level)
    level_item.setData(cipher, qt.Qt.UserRole + 2)
    
    message_item = qt.QStandardItem(message)
    message_item.setData(message, qt.Qt.UserRole)
    
    print(f"Row {i}: level={level}, cipher={cipher}")
    model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])

print(f"\nTotal rows in model: {model.rowCount()}")

# Test level filtering
print("\n=== Testing Level Filtering ===")
threshold = 20
regex_pattern = level_threshold_to_cipher_regex(threshold)
print(f"Threshold: {threshold}")
print(f"Generated regex: {regex_pattern}")

# Test what ciphers should match
for level in [10, 20, 30, 40, 50]:
    cipher = level_to_cipher(level)
    regex = qt.QRegExp(regex_pattern)
    matches = regex.exactMatch(cipher)
    print(f"Level {level} -> cipher '{cipher}' -> matches: {matches}")

# Test the actual filter manager
print("\n=== Testing ChainedLogFilterManager ===")
manager = ChainedLogFilterManager(model)
print(f"Initial row count: {manager.rowCount()}")

manager.set_filters(["level: 20"])
print(f"After level:20 filter: {manager.rowCount()}")
print(f"Chain order: {manager.chain_order}")
print(f"Proxies: {list(manager.proxies.keys())}")

if 'level' in manager.proxies:
    level_proxy = manager.proxies['level']
    print(f"Level proxy pattern: '{level_proxy.filter_pattern}'")
    print(f"Level proxy regex: '{level_proxy.filterRegExp().pattern()}'")
    print(f"Level proxy role: {level_proxy.filterRole()}")
    print(f"Level proxy column: {level_proxy.filterKeyColumn()}")
    
    # Check what data the proxy sees
    print("\nChecking data in proxy:")
    for row in range(model.rowCount()):
        level_item = model.item(row, 3)
        level_val = level_item.data(qt.Qt.UserRole)
        cipher_val = level_item.data(qt.Qt.UserRole + 2)
        print(f"  Row {row}: level={level_val}, cipher='{cipher_val}'")

sys.exit(0)