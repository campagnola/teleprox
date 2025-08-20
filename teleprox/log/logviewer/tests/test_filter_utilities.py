#!/usr/bin/env python3
"""
Unit tests for log filtering utility functions.
Tests the cipher system, parsing functions, and regex generation.
"""

import pytest

# Import the utility functions we want to test
from teleprox.log.logviewer.utils import (
    level_to_cipher, 
    parse_level_value, 
    level_threshold_to_cipher_regex
)


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
    
    def test_level_to_cipher_high_values(self):
        """Test cipher conversion for high levels (Z for 51+)."""
        assert level_to_cipher(51) == 'Z'
        assert level_to_cipher(100) == 'Z'
        assert level_to_cipher(999) == 'Z'


class TestParseLevelValue:
    """Test parsing of level values from filter strings."""
    
    def test_parse_level_value_numeric(self):
        """Test parsing numeric level values."""
        assert parse_level_value("10") == 10
        assert parse_level_value("30") == 30
        assert parse_level_value("40") == 40
    
    def test_parse_level_value_names(self):
        """Test parsing level names (case-insensitive)."""
        assert parse_level_value("debug") == 10
        assert parse_level_value("DEBUG") == 10
        assert parse_level_value("info") == 20
        assert parse_level_value("INFO") == 20
        assert parse_level_value("warning") == 30
        assert parse_level_value("error") == 40
        assert parse_level_value("critical") == 50
    
    def test_parse_level_value_invalid(self):
        """Test parsing invalid level values."""
        assert parse_level_value("invalid") == 0  # Default fallback
        assert parse_level_value("") == 0  # Empty string fallback
        assert parse_level_value("999999") == 999999  # High numbers are valid


class TestLevelThresholdRegex:
    """Test level threshold regex generation."""
    
    def test_level_threshold_to_cipher_regex(self):
        """Test regex generation for level thresholds."""
        import re
        
        # Test WARNING+ (30+) should match E through Y and Z
        regex = level_threshold_to_cipher_regex(30)
        pattern = re.compile(regex)
        
        # Should match WARNING (E), ERROR (O), CRITICAL (Y), and high levels (Z)
        assert pattern.match('E')  # WARNING level
        assert pattern.match('O')  # ERROR level  
        assert pattern.match('Y')  # CRITICAL level
        assert pattern.match('Z')  # High levels
        
        # Should not match levels below WARNING
        assert not pattern.match('a')  # level 0
        assert not pattern.match('u')  # INFO level (20)
        assert not pattern.match('D')  # level 29