#!/usr/bin/env python3
"""
Unit tests for log filtering proxy classes.
Tests FieldFilterProxy and LevelCipherFilterProxy functionality.
"""

import pytest

# Import Qt for testing
try:
    from teleprox import qt
    QStandardItemModel = qt.QStandardItemModel
    QStandardItem = qt.QStandardItem
except ImportError:
    pytest.skip("Qt not available", allow_module_level=True)

# Import the proxy classes we want to test
from teleprox.log.logviewer.proxies import (
    FieldFilterProxy,
    LevelCipherFilterProxy
)
from teleprox.log.logviewer.constants import ItemDataRole, LogColumns


class TestFieldFilterProxy:
    """Test FieldFilterProxy functionality."""
    
    @pytest.fixture
    def mock_model(self):
        """Create a simple mock model for testing."""
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(['Col0', 'Col1', 'Col2', 'Col3'])
        
        # Add test rows
        for i in range(3):
            row = [QStandardItem(f"test{i}_{j}") for j in range(4)]
            model.appendRow(row)
        
        return model
    
    def test_field_filter_proxy_initialization(self):
        """Test FieldFilterProxy initialization."""
        proxy = FieldFilterProxy("test_field", 1)
        assert proxy.field_name == "test_field"
        assert proxy.column == 1
        assert proxy.filterKeyColumn() == 1
        assert proxy.filter_pattern == ""
    
    def test_field_filter_proxy_pattern_setting(self, mock_model):
        """Test setting filter patterns."""
        proxy = FieldFilterProxy("test_field", 1)
        proxy.setSourceModel(mock_model)
        
        # Test empty pattern
        proxy.set_filter_pattern("")
        assert proxy.filterRegExp().pattern() == ""
        
        # Test non-empty pattern  
        proxy.set_filter_pattern("test.*")
        assert proxy.filterRegExp().pattern() == "test.*"
    
    def test_field_filter_proxy_filtering(self, mock_model):
        """Test actual filtering behavior."""
        proxy = FieldFilterProxy("test_field", 1)  # Filter on column 1
        proxy.setSourceModel(mock_model)
        
        # Initially should show all rows
        assert proxy.rowCount() == 3
        
        # Filter to show only rows containing "test0"
        proxy.set_filter_pattern("test0")
        assert proxy.rowCount() == 1
        
        # Clear filter should show all rows again
        proxy.set_filter_pattern("")
        assert proxy.rowCount() == 3


class TestLevelCipherFilterProxy:
    """Test LevelCipherFilterProxy functionality."""
    
    @pytest.fixture
    def cipher_model(self):
        """Create a model with level cipher data."""
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(LogColumns.TITLES)
        
        # Create test data with different level ciphers
        test_levels = [
            ('k', 10),  # DEBUG
            ('u', 20),  # INFO  
            ('E', 30),  # WARNING
            ('O', 40),  # ERROR
            ('Y', 50),  # CRITICAL
        ]
        
        for cipher, level_num in test_levels:
            row = [QStandardItem("") for _ in range(len(LogColumns.TITLES))]
            
            # Set level cipher data
            level_item = row[LogColumns.LEVEL]
            level_item.setData(cipher, ItemDataRole.LEVEL_CIPHER)
            level_item.setData(level_num, ItemDataRole.LEVEL_NUMBER)
            level_item.setText(f"Level {level_num}")
            
            model.appendRow(row)
            
        return model
    
    def test_level_cipher_filter_proxy_initialization(self):
        """Test LevelCipherFilterProxy initialization."""
        proxy = LevelCipherFilterProxy()
        
        # Should filter on LEVEL_CIPHER role of LEVEL column
        assert proxy.filterRole() == ItemDataRole.LEVEL_CIPHER
        assert proxy.filterKeyColumn() == LogColumns.LEVEL
    
    def test_level_cipher_filter_proxy_filtering(self, cipher_model):
        """Test level filtering behavior."""
        proxy = LevelCipherFilterProxy()
        proxy.setSourceModel(cipher_model)
        
        # Initially should show all levels
        assert proxy.rowCount() == 5
        
        # Filter to WARNING+ (should show E, O, Y)
        proxy.set_level_filter("30")  # WARNING level and above
        visible_count = proxy.rowCount()
        assert visible_count == 3  # WARNING, ERROR, CRITICAL
        
        # Filter to ERROR+ (should show O, Y)
        proxy.set_level_filter("40")  # ERROR level and above  
        visible_count = proxy.rowCount()
        assert visible_count == 2  # ERROR, CRITICAL
        
        # Clear filter should show all again
        proxy.set_level_filter("")
        assert proxy.rowCount() == 5
    
    def test_level_cipher_filter_proxy_pattern_setting(self, cipher_model):
        """Test setting level filter patterns."""
        proxy = LevelCipherFilterProxy()
        proxy.setSourceModel(cipher_model)
        
        # Test empty level (should clear filter)
        proxy.set_level_filter("")
        assert proxy.filter_pattern == ""
        
        # Test specific level
        proxy.set_level_filter("30")
        assert proxy.filter_pattern != ""  # Should generate regex
        
        # Pattern should contain appropriate cipher characters
        pattern = proxy.filter_pattern
        assert 'E' in pattern or '[' in pattern  # Should include WARNING+ ciphers