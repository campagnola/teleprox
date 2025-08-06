#!/usr/bin/env python3
"""
Unit tests for ChainedLogFilterManager.
Tests the coordination and management of multiple filter proxies.
"""

import pytest
from unittest.mock import Mock, MagicMock

# Import Qt for testing
try:
    from teleprox import qt
    QStandardItemModel = qt.QStandardItemModel
except ImportError:
    pytest.skip("Qt not available", allow_module_level=True)

# Import the manager class we want to test
from teleprox.log.logviewer.filtering import ChainedLogFilterManager


class TestChainedLogFilterManager:
    """Test ChainedLogFilterManager functionality."""
    
    @pytest.fixture
    def mock_model(self):
        """Create a mock model for testing."""
        return QStandardItemModel()
    
    def test_chained_manager_initialization(self, mock_model):
        """Test ChainedLogFilterManager initialization."""
        manager = ChainedLogFilterManager(mock_model)
        assert manager.source_model == mock_model
        assert len(manager.proxies) == 0
        assert manager.final_model == mock_model
    
    def test_no_filters(self, mock_model):
        """Test manager behavior with no filters."""
        manager = ChainedLogFilterManager(mock_model)
        
        # With no filters, final_model should be the original model
        assert manager.final_model == mock_model
        assert len(manager.proxies) == 0
    
    def test_single_filter_parsing(self, mock_model):
        """Test parsing and applying a single filter."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters(["level: 30"])
        
        assert len(manager.proxies) == 1
        assert 'level' in manager.proxies
        assert manager.final_model != mock_model  # Should be different after filtering
    
    def test_multiple_filter_parsing(self, mock_model):
        """Test parsing and applying multiple filters."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters(["level: 20", "logger: app.core", "message: error"])
        
        assert len(manager.proxies) == 3
        assert 'level' in manager.proxies
        assert 'logger' in manager.proxies
        assert 'message' in manager.proxies
    
    def test_filter_chain_order(self, mock_model):
        """Test that multiple filters are applied correctly."""
        manager = ChainedLogFilterManager(mock_model)
        
        # Set multiple filters
        manager.set_filters(["level: 30", "logger: test"])
        
        # Should have created proxies for both filters
        assert len(manager.proxies) == 2
        assert 'level' in manager.proxies
        assert 'logger' in manager.proxies
    
    def test_dynamic_chain_rebuilding(self, mock_model):
        """Test that filter chain is rebuilt when filters change."""
        manager = ChainedLogFilterManager(mock_model)
        
        # Start with one filter
        manager.set_filters(["level: 20"])
        first_model = manager.final_model
        assert len(manager.proxies) == 1
        
        # Add another filter - should rebuild chain
        manager.set_filters(["level: 20", "logger: app.core"])
        second_model = manager.final_model
        assert len(manager.proxies) == 2
        
        # Remove level filter, keep logger
        manager.set_filters(["logger: app.core"])
        assert len(manager.proxies) == 1
        assert 'logger' in manager.proxies
        assert 'level' not in manager.proxies
    
    def test_unknown_filter_ignored(self, mock_model):
        """Test that unknown filter types are ignored."""
        manager = ChainedLogFilterManager(mock_model)
        manager.set_filters(["unknown: value", "level: 20"])
        
        # Should only create proxy for known filter type
        assert len(manager.proxies) == 1
        assert 'level' in manager.proxies
        assert 'unknown' not in manager.proxies
    
    def test_empty_filter_list(self, mock_model):
        """Test setting empty filter list."""
        manager = ChainedLogFilterManager(mock_model)
        
        # Start with filters
        manager.set_filters(["level: 20", "logger: test"])
        assert len(manager.proxies) == 2
        
        # Clear filters
        manager.set_filters([])
        assert len(manager.proxies) == 0
        
        # Should return original model
        assert manager.final_model == mock_model
    
    def test_filter_pattern_parsing(self, mock_model):
        """Test parsing of filter patterns."""
        manager = ChainedLogFilterManager(mock_model)
        
        # Test various filter formats
        invalid_filters = manager.set_filters([
            "level: 30",
            "logger: app.module.submodule", 
            "message: error occurred",
            "source: MainProcess/MainThread"
        ])
        
        # Should have no invalid filters
        assert invalid_filters == []
        
        # Should have created proxies for each filter type
        assert len(manager.proxies) == 4
        assert 'level' in manager.proxies
        assert 'logger' in manager.proxies
        assert 'message' in manager.proxies
        assert 'source' in manager.proxies