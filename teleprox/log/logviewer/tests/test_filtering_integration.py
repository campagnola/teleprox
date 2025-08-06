#!/usr/bin/env python3
"""
Integration tests for log filtering functionality.
Tests the complete filtering system with realistic data.
"""

import pytest
import sys
import time
import logging
from unittest.mock import Mock, MagicMock

# Import Qt for testing
try:
    from teleprox import qt
    QStandardItemModel = qt.QStandardItemModel
    QStandardItem = qt.QStandardItem
    Qt = qt.Qt
except ImportError:
    pytest.skip("Qt not available", allow_module_level=True)

# Import the classes we want to test
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns
from teleprox.log.logviewer.filtering import ChainedLogFilterManager


class TestFilteringIntegration:
    """Integration tests for the complete filtering system."""
    
    @pytest.fixture
    def full_model(self):
        """Create a realistic model with various log entries."""
        model = QStandardItemModel()
        
        # Define test data - realistic log entries
        test_entries = [
            (10, "app.core", "MainProcess", "MainThread", "Starting application initialization"),
            (20, "app.core", "MainProcess", "MainThread", "Configuration loaded successfully"), 
            (20, "app.ui", "MainProcess", "MainThread", "UI components initialized"),
            (30, "app.network", "MainProcess", "WorkerThread", "Connection timeout detected"),
            (40, "app.core", "MainProcess", "MainThread", "Database connection failed"),
            (50, "app.core", "WorkerProcess", "WorkerThread", "Critical system failure")
        ]
        
        for level, logger, process, thread, message in test_entries:
            row_items = [QStandardItem() for _ in range(model.columnCount() or 9)]
            
            # TIMESTAMP column (0)
            timestamp = int(time.time() * 1000)
            row_items[LogColumns.TIMESTAMP].setText(str(timestamp))
            row_items[LogColumns.TIMESTAMP].setData(timestamp, ItemDataRole.NUMERIC_TIMESTAMP)
            
            # HOST column (1) 
            row_items[LogColumns.HOST].setText("localhost")
            
            # PROCESS column (2)
            row_items[LogColumns.PROCESS].setText(process)
            row_items[LogColumns.PROCESS].setData(process, ItemDataRole.PROCESS_NAME)
            
            # THREAD column (3)
            row_items[LogColumns.THREAD].setText(thread)
            row_items[LogColumns.THREAD].setData(thread, ItemDataRole.THREAD_NAME)
            
            # SOURCE column (4) - combined process/thread
            source = f"{process}/{thread}"
            row_items[LogColumns.SOURCE].setText(source)
            row_items[LogColumns.SOURCE].setData(process, ItemDataRole.PROCESS_NAME)
            row_items[LogColumns.SOURCE].setData(thread, ItemDataRole.THREAD_NAME)
            
            # LOGGER column (5)
            row_items[LogColumns.LOGGER].setText(logger)
            row_items[LogColumns.LOGGER].setData(logger, ItemDataRole.LOGGER_NAME)
            
            # LEVEL column (6)
            row_items[LogColumns.LEVEL].setText(logging.getLevelName(level))
            row_items[LogColumns.LEVEL].setData(level, ItemDataRole.LEVEL_NUMBER)
            # Add cipher data for level filtering
            from teleprox.log.logviewer.utils import level_to_cipher
            cipher = level_to_cipher(level)
            row_items[LogColumns.LEVEL].setData(cipher, ItemDataRole.LEVEL_CIPHER)
            
            # MESSAGE column (7)
            row_items[LogColumns.MESSAGE].setText(message)
            row_items[LogColumns.MESSAGE].setData(message, ItemDataRole.MESSAGE_TEXT)
            
            # TASK column (8)
            row_items[LogColumns.TASK].setText("")  # Empty task
            
            model.appendRow(row_items)
        
        return model
    
    def test_level_filtering_integration(self, full_model):
        """Test level filtering with realistic data."""
        manager = ChainedLogFilterManager(full_model)
        
        # Filter for level >= 20 (info and above)
        manager.set_filters(["level: 20"])
        
        # Should filter out the debug message (level 10)
        # All other messages (20, 30, 40, 50) should remain
        filtered_count = manager.rowCount()
        assert filtered_count == 5  # Original 6 minus 1 debug message
    
    def test_combined_filtering_integration(self, full_model):
        """Test multiple filters working together."""
        manager = ChainedLogFilterManager(full_model)
        
        # Filter for level >= 20 AND logger contains "core"
        manager.set_filters(["level: 20", "logger: core"])
        
        # Should match: app.core level 20, app.core level 40, app.core level 50
        # Should exclude: app.core level 10 (wrong level), app.ui messages (wrong logger), app.network (wrong logger)
        filtered_count = manager.rowCount()
        assert filtered_count == 3
    
    def test_source_thread_filtering_integration(self, full_model):
        """Test source filtering for thread-like data with realistic data."""
        manager = ChainedLogFilterManager(full_model)
        
        # Filter for MainThread in source column
        manager.set_filters(["source: MainThread"])
        
        # Should match 4 records (all MainThread records)
        filtered_count = manager.rowCount()
        assert filtered_count == 4
    
    def test_source_filtering_integration(self, full_model):
        """Test source filtering using the column name."""
        manager = ChainedLogFilterManager(full_model)
        
        # Filter for 'main' in source (should match process names)
        manager.set_filters(["source: main"])
        
        # Should match 5 records (all MainProcess records)
        filtered_count = manager.rowCount()
        assert filtered_count == 5