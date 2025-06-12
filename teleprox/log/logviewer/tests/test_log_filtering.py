#!/usr/bin/env python3
"""
Unit tests for log filtering functionality.
Tests the cipher system and chained filter manager without GUI dependencies.
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

# Import the functions and classes we want to test
from teleprox.log.logviewer.utils import (
    level_to_cipher, 
    parse_level_value, 
    level_threshold_to_cipher_regex
)
from teleprox.log.logviewer.proxies import (
    FieldFilterProxy,
    LevelCipherFilterProxy
)
from teleprox.log.logviewer.filtering import ChainedLogFilterManager


class TestLevelCipherSystem:
    """Test the level cipher conversion system."""
    
    def test_level_to_cipher_lowercase(self):
        """Test cipher conversion for levels 0-25 (a-z)."""
        assert level_to_cipher(0) == 'a'
        assert level_to_cipher(10) == 'k'  # debug level
        assert level_to_cipher(20) == 'u'  # info level
        assert level_to_cipher(25) == 'z'
    
    def test_level_to_cipher_uppercase(self):
        """Test cipher conversion for levels 26-50 (A-Y)."""
        assert level_to_cipher(26) == 'A'
        assert level_to_cipher(30) == 'E'  # warning level
        assert level_to_cipher(40) == 'O'  # error level
        assert level_to_cipher(50) == 'Y'  # critical level
    
    def test_level_to_cipher_fallback(self):
        """Test cipher conversion for levels > 50."""
        assert level_to_cipher(51) == 'Z'
        assert level_to_cipher(100) == 'Z'
    
    def test_parse_level_value_numeric(self):
        """Test parsing numeric level values."""
        assert parse_level_value("10") == 10
        assert parse_level_value("20") == 20
        assert parse_level_value("  30  ") == 30  # with whitespace
    
    def test_parse_level_value_names(self):
        """Test parsing standard logging level names."""
        assert parse_level_value("debug") == 10
        assert parse_level_value("DEBUG") == 10
        assert parse_level_value("info") == 20
        assert parse_level_value("INFO") == 20
        assert parse_level_value("warning") == 30
        assert parse_level_value("warn") == 30
        assert parse_level_value("error") == 40
        assert parse_level_value("critical") == 50
        assert parse_level_value("fatal") == 50
    
    def test_parse_level_value_invalid(self):
        """Test parsing invalid level values."""
        assert parse_level_value("invalid") == 0
        assert parse_level_value("") == 0
    
    def test_level_threshold_to_cipher_regex(self):
        """Test regex generation for level thresholds."""
        # Level 0 should match everything
        regex = level_threshold_to_cipher_regex(0)
        assert regex == ".*"
        
        # Level 10 (debug) should match k-z and A-Y and Z
        regex = level_threshold_to_cipher_regex(10)
        assert regex == "[k-zA-YZ]"
        
        # Level 20 (info) should match u-z and A-Y and Z
        regex = level_threshold_to_cipher_regex(20)
        assert regex == "[u-zA-YZ]"
        
        # Level 30 (warning) should match E-Y and Z
        regex = level_threshold_to_cipher_regex(30)
        assert regex == "[E-YZ]"
        
        # Level 60 should only match Z
        regex = level_threshold_to_cipher_regex(60)        
        assert regex == "Z"


class TestChainedFilterManager:
    """Test the chained filter manager."""
    
    @pytest.fixture
    def mock_model(self):
        """Create a mock Qt model with test data."""
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message'])
        
        # Add some test records
        test_records = [
            (1000.0, "main/MainThread", "app.core", 10, "Debug message"),
            (1001.0, "main/MainThread", "app.ui", 20, "Info message"),
            (1002.0, "worker/Thread-1", "app.core", 30, "Warning message"),
            (1003.0, "worker/Thread-1", "app.network", 40, "Error message"),
            (1004.0, "main/MainThread", "app.core", 50, "Critical message"),
        ]
        
        for timestamp, source, logger, level, message in test_records:
            timestamp_item = QStandardItem(f"{timestamp:.1f}")
            timestamp_item.setData(timestamp, Qt.UserRole)
            
            source_item = QStandardItem(source)
            process, thread = source.split('/', 1)
            source_item.setData(process, Qt.UserRole)
            source_item.setData(thread, Qt.UserRole + 1)
            
            logger_item = QStandardItem(logger)
            logger_item.setData(logger, Qt.UserRole)
            
            level_item = QStandardItem(str(level))
            level_item.setData(level, Qt.UserRole)
            level_item.setData(level_to_cipher(level), Qt.UserRole + 2)
            
            message_item = QStandardItem(message)
            message_item.setData(message, Qt.UserRole)
            
            model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])
        
        return model
    
    def test_chained_manager_initialization(self, mock_model):
        """Test that the chained manager initializes correctly."""
        manager = ChainedLogFilterManager(mock_model)
        assert manager.source_model == mock_model
        assert manager.final_model == mock_model
        assert len(manager.proxies) == 0
        assert len(manager.chain_order) == 0
    
    def test_no_filters(self, mock_model):
        """Test that no filters leaves the source model unchanged."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters([])
        
        assert manager.final_model == mock_model
        assert len(manager.proxies) == 0
        assert manager.rowCount() == 5  # All records should be visible
    
    def test_level_filter_parsing(self, mock_model):
        """Test that level filters are parsed correctly."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters(["level: 20"])
        
        assert 'level' in manager.proxies
        assert len(manager.chain_order) == 1
        assert manager.chain_order[0] == 'level'
        assert manager.final_model != mock_model  # Should have proxy in chain
    
    def test_multiple_filter_parsing(self, mock_model):
        """Test parsing multiple different filter types."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters(["level: 20", "logger: app.core", "source: main"])
        
        assert 'level' in manager.proxies
        assert 'logger' in manager.proxies  
        assert 'source' in manager.proxies
        assert len(manager.chain_order) == 3
    
    def test_filter_chain_order(self, mock_model):
        """Test that filters are chained in the order they appear in the filter list."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters(["source: main", "level: 20", "logger: app.core"])
        
        # Should preserve the order filters were added (not reorder them)
        expected_order = ['source', 'level', 'logger']
        assert manager.chain_order == expected_order
    
    def test_dynamic_chain_rebuilding(self, mock_model):
        """Test that the chain rebuilds when filters change."""
        manager = ChainedLogFilterManager(mock_model)
        
        # Start with level filter only
        manager.set_filters(["level: 20"])
        assert len(manager.proxies) == 1
        assert 'level' in manager.proxies
        
        # Add logger filter
        manager.set_filters(["level: 20", "logger: app.core"])
        assert len(manager.proxies) == 2
        assert 'level' in manager.proxies
        assert 'logger' in manager.proxies
        
        # Remove level filter, keep logger
        manager.set_filters(["logger: app.core"])
        assert len(manager.proxies) == 1
        assert 'logger' in manager.proxies
        assert 'level' not in manager.proxies
    
    def test_unknown_filter_ignored(self, mock_model):
        """Test that unknown filter types are ignored."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters(["unknown: value", "level: 20"])
        
        assert len(manager.proxies) == 1
        assert 'level' in manager.proxies
        assert 'unknown' not in manager.proxies


class TestFilterProxies:
    """Test individual filter proxy classes."""
    
    @pytest.fixture
    def mock_model(self):
        """Create a simple mock model for testing."""
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(['Col0', 'Col1', 'Col2', 'Col3'])
        
        # Add a test row
        item0 = QStandardItem("test0")
        item1 = QStandardItem("test1") 
        item2 = QStandardItem("test2")
        item3 = QStandardItem("test3")
        item3.setData('k', Qt.UserRole + 2)  # level cipher
        
        model.appendRow([item0, item1, item2, item3])
        return model
    
    def test_field_filter_proxy_initialization(self):
        """Test FieldFilterProxy initialization."""
        proxy = FieldFilterProxy("test", 1)
        assert proxy.field_name == "test"
        assert proxy.column == 1
        assert proxy.filterKeyColumn() == 1
        assert proxy.filter_pattern == ""
    
    def test_field_filter_proxy_pattern_setting(self, mock_model):
        """Test setting filter patterns."""
        proxy = FieldFilterProxy("test", 1)
        proxy.setSourceModel(mock_model)
        
        # Test empty pattern
        proxy.set_filter_pattern("")
        assert proxy.filterRegExp().pattern() == ""
        
        # Test non-empty pattern  
        proxy.set_filter_pattern("test.*")
        assert proxy.filterRegExp().pattern() == "test.*"
    
    def test_level_cipher_filter_proxy(self, mock_model):
        """Test LevelCipherFilterProxy functionality."""
        proxy = LevelCipherFilterProxy()
        proxy.setSourceModel(mock_model)
        
        # Should filter on UserRole+2 of column 3
        assert proxy.filterRole() == Qt.UserRole + 2
        assert proxy.filterKeyColumn() == 3
        
        # Test level filter setting
        proxy.set_level_filter("10")  # Should create regex for level >= 10
        assert proxy.filter_pattern != ""


class TestIntegration:
    """Integration tests combining multiple components."""
    
    @pytest.fixture
    def full_model(self):
        """Create a full model like the real log viewer would."""
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message'])
        
        # Create realistic test data
        test_data = [
            (1000.0, "main", "MainThread", "app.core", 10, "Debug startup"),
            (1001.0, "main", "MainThread", "app.ui", 20, "UI initialized"),
            (1002.0, "worker", "Thread-1", "app.core", 20, "Worker started"),
            (1003.0, "worker", "Thread-1", "app.network", 30, "Network warning"),
            (1004.0, "main", "MainThread", "app.core", 40, "Core error"),
            (1005.0, "main", "MainThread", "app.ui", 50, "UI critical error"),
        ]
        
        for timestamp, process, thread, logger, level, message in test_data:
            timestamp_item = QStandardItem(f"{timestamp:.1f}")
            timestamp_item.setData(timestamp, Qt.UserRole)
            
            source_item = QStandardItem(f"{process}/{thread}")
            source_item.setData(process, Qt.UserRole)
            source_item.setData(thread, Qt.UserRole + 1)
            
            logger_item = QStandardItem(logger)
            logger_item.setData(logger, Qt.UserRole)
            
            level_item = QStandardItem(str(level))
            level_item.setData(level, Qt.UserRole)
            level_item.setData(level_to_cipher(level), Qt.UserRole + 2)
            
            message_item = QStandardItem(message)
            message_item.setData(message, Qt.UserRole)
            
            model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item])
        
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
        
        # Should match: app.core level 20, app.core level 40
        # Should exclude: app.core level 10 (wrong level), app.ui messages (wrong logger), app.network (wrong logger)
        filtered_count = manager.rowCount()
        assert filtered_count == 2
    
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
        
        # Should match 4 records (all main process records)
        filtered_count = manager.rowCount()
        assert filtered_count == 4


if __name__ == '__main__':
    pytest.main([__file__, "-v"])