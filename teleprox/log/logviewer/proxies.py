# ABOUTME: Qt proxy model implementations for chained log filtering
# ABOUTME: Contains FieldFilterProxy and LevelCipherFilterProxy for advanced filtering chains

from teleprox import qt
from .utils import parse_level_value, level_threshold_to_cipher_regex
from .constants import ItemDataRole, LogColumns


class FieldFilterProxy(qt.QSortFilterProxyModel):
    """Base class for field-specific filtering using Qt native regex."""
    
    def __init__(self, field_name, column, parent=None):
        super().__init__(parent)
        self.field_name = field_name
        self.column = column
        self.setFilterKeyColumn(column)
        self.setFilterCaseSensitivity(qt.Qt.CaseInsensitive)
        self.filter_pattern = ""
        
        # Set custom filter role for fields - all fields now use data roles, not display text
        field_roles = {
            'logger': ItemDataRole.LOGGER_NAME,
            'message': ItemDataRole.MESSAGE_TEXT,
            'host': ItemDataRole.HOST_NAME,
            'process': ItemDataRole.PROCESS_NAME,
            'thread': ItemDataRole.THREAD_NAME,
            'source': ItemDataRole.SOURCE_TEXT,
            'task': ItemDataRole.TASK_NAME,
        }
        
        if field_name in field_roles:
            self.setFilterRole(field_roles[field_name])
    
    def set_filter_pattern(self, pattern):
        """Set the filter pattern for this field."""
        self.filter_pattern = pattern
        if pattern:
            self.setFilterRegExp(pattern)
        else:
            self.setFilterRegExp("")


class LevelCipherFilterProxy(FieldFilterProxy):
    """Handles level filtering using cipher data from LEVEL_CIPHER role."""
    
    def __init__(self, parent=None):
        super().__init__("level", LogColumns.LEVEL, parent)  # Use LogColumns constant
        self.setFilterRole(ItemDataRole.LEVEL_CIPHER)  # Filter on cipher data
        self.setFilterCaseSensitivity(qt.Qt.CaseSensitive)  # Cipher patterns are case-sensitive
    
    def set_level_filter(self, level_value):
        """Set level filter using threshold (levels >= threshold)."""
        if not level_value:
            self.set_filter_pattern("")
            return
            
        threshold = parse_level_value(level_value)
        cipher_regex = level_threshold_to_cipher_regex(threshold)
        self.set_filter_pattern(cipher_regex)