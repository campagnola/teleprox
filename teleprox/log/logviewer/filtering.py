# Log filtering implementations including Python-based and chained Qt proxy models
# Contains PythonLogFilterProxyModel, ChainedLogFilterManager, and filtering utilities

import re
from teleprox import qt
from .utils import parse_level_value, level_threshold_to_cipher_regex
from .proxies import FieldFilterProxy, LevelCipherFilterProxy
from .constants import ItemDataRole, LogColumns


class PythonLogFilterProxyModel(qt.QSortFilterProxyModel):
    """Custom proxy model that supports advanced filtering of log records."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filters = []
        
    def set_filters(self, filter_strings):
        """Set the filter strings and invalidate the filter.
        
        Returns:
            list: Empty list (Python filtering doesn't validate field names)
        """
        self.filters = filter_strings
        self.invalidateFilter()
        return []  # Python filtering doesn't validate field names
        
    def filterAcceptsRow(self, source_row, source_parent):
        """Return True if the row should be included in the filtered model."""
        if not self.filters:
            return True
            
        model = self.sourceModel()
        
        # Get all the items for this row
        timestamp_item = model.item(source_row, LogColumns.TIMESTAMP)
        source_item = model.item(source_row, LogColumns.SOURCE)
        logger_item = model.item(source_row, LogColumns.LOGGER)
        level_item = model.item(source_row, LogColumns.LEVEL)
        message_item = model.item(source_row, LogColumns.MESSAGE)
        
        # Extract data for filtering
        timestamp = timestamp_item.data(ItemDataRole.NUMERIC_TIMESTAMP) if timestamp_item else 0
        process_name = source_item.data(ItemDataRole.PROCESS_NAME) if source_item else ""
        thread_name = source_item.data(ItemDataRole.THREAD_NAME) if source_item else ""
        logger_name = logger_item.data(ItemDataRole.LOGGER_NAME) if logger_item else ""
        level_num = level_item.data(ItemDataRole.LEVEL_NUMBER) if level_item else 0
        message_text = message_item.data(ItemDataRole.MESSAGE_TEXT) if message_item else ""
        
        # Display text for generic search
        display_texts = [
            timestamp_item.text() if timestamp_item else "",
            source_item.text() if source_item else "",
            logger_name,
            level_item.text() if level_item else "",
            message_text
        ]
        combined_text = " ".join(display_texts).lower()
        
        # Check each filter
        for filter_str in self.filters:
            if not filter_str.strip():
                continue
                
            filter_str = filter_str.strip()
            
            # Parse field-specific filters
            if self._matches_level_filter(filter_str, level_num):
                continue
            elif self._matches_logger_filter(filter_str, logger_name):
                continue
            elif self._matches_thread_filter(filter_str, thread_name):
                continue
            elif self._matches_process_filter(filter_str, process_name):
                continue
            elif self._matches_generic_filter(filter_str, combined_text):
                continue
            else:
                # Filter doesn't match, exclude this row
                return False
                
        return True
        
    def _matches_level_filter(self, filter_str, level_num):
        """Check if filter matches level criteria (e.g., 'level > 10')."""
        level_match = re.match(r'level\s*([><=]+)\s*(\d+)', filter_str, re.IGNORECASE)
        if level_match:
            operator, value = level_match.groups()
            value = int(value)
            if operator == '>':
                return level_num > value
            elif operator == '>=':
                return level_num >= value
            elif operator == '<':
                return level_num < value
            elif operator == '<=':
                return level_num <= value
            elif operator == '=' or operator == '==':
                return level_num == value
        return False
        
    def _matches_logger_filter(self, filter_str, logger_name):
        """Check if filter matches logger criteria (e.g., 'logger: myLogger')."""
        logger_match = re.match(r'logger:\s*(.+)', filter_str, re.IGNORECASE)
        if logger_match:
            pattern = logger_match.group(1).strip()
            try:
                return bool(re.search(pattern, logger_name, re.IGNORECASE))
            except re.error:
                # If regex is invalid, do literal match
                return pattern.lower() in logger_name.lower()
        return False
        
    def _matches_thread_filter(self, filter_str, thread_name):
        """Check if filter matches thread criteria (e.g., 'thread: main.*')."""
        thread_match = re.match(r'thread:\s*(.+)', filter_str, re.IGNORECASE)
        if thread_match:
            pattern = thread_match.group(1).strip()
            try:
                return bool(re.search(pattern, thread_name, re.IGNORECASE))
            except re.error:
                # If regex is invalid, do literal match
                return pattern.lower() in thread_name.lower()
        return False
        
    def _matches_process_filter(self, filter_str, process_name):
        """Check if filter matches process criteria (e.g., 'process: worker.*')."""
        process_match = re.match(r'process:\s*(.+)', filter_str, re.IGNORECASE)
        if process_match:
            pattern = process_match.group(1).strip()
            try:
                return bool(re.search(pattern, process_name, re.IGNORECASE))
            except re.error:
                # If regex is invalid, do literal match
                return pattern.lower() in process_name.lower()
        return False
        
    def _matches_generic_filter(self, filter_str, combined_text):
        """Check if filter matches any text in the record."""
        try:
            return bool(re.search(filter_str, combined_text, re.IGNORECASE))
        except re.error:
            # If regex is invalid, do literal match
            return filter_str.lower() in combined_text


class ChainedLogFilterManager:
    """Manages a chain of proxy models for efficient filtering."""
    
    def __init__(self, source_model, parent=None):
        self.source_model = source_model
        self.proxy_chain = []
        self.final_model = source_model
        
        # Available proxy types mapped to column names where possible
        self.proxy_types = {
            'level': lambda: LevelCipherFilterProxy(),
            'logger': lambda: FieldFilterProxy('logger', LogColumns.LOGGER),
            'source': lambda: FieldFilterProxy('source', LogColumns.SOURCE),
            'message': lambda: FieldFilterProxy('message', LogColumns.MESSAGE),
            'host': lambda: FieldFilterProxy('host', LogColumns.HOST),
            'process': lambda: FieldFilterProxy('process', LogColumns.PROCESS),
            'thread': lambda: FieldFilterProxy('thread', LogColumns.THREAD),
        }

    def map_index_from_model(self, source_index):
        """Map an index from the source model to the final proxy output."""
        for proxy in self.proxy_chain:
            source_index = proxy.mapFromSource(source_index)
        return source_index

    def map_index_to_model(self, index):
        """Map an index from the final proxy output back to the source model."""
        for proxy in reversed(self.proxy_chain):
            index = proxy.mapToSource(index)        
        return index

    def set_filters(self, filter_strings):
        """Parse filters and build/update proxy chain dynamically.
        
        Returns:
            list: List of invalid filter field names (empty if all valid)
        """
        if not filter_strings:
            # No filters, use source model directly
            self._rebuild_chain([])
            return []
        
        # Parse filters to determine needed proxies
        filter_configs = []
        invalid_filters = []
        
        for filter_str in filter_strings:
            filter_str = filter_str.strip()

            if not filter_str:
                continue                
            
            # Parse field-specific filters
            key, colon, value = filter_str.partition(':')
            if colon:
                field = key.strip().lower()
                value = value.strip()
                
                if field not in self.proxy_types:
                    # Track invalid field filters for user feedback
                    invalid_filters.append(field)
                    continue

                filter_configs.append((field, value))
            else:
                # Generic search terms apply to message column
                filter_configs.append(('message', filter_str))
        
        # Rebuild chain with filter configs
        self._rebuild_chain(filter_configs)
        
        return invalid_filters
    
    def _rebuild_chain(self, filter_configs):
        """Rebuild the proxy chain with the specified filter configs in order."""
        # filter_configs is a list of (field, value) tuples in the order they should be applied
        
        # Clear existing proxies
        self.proxy_chain = []
        
        # If no filters, use source model directly
        if not filter_configs:
            self.final_model = self.source_model
            return
        
        # Group by field type and use last value for each field (simple behavior for backward compatibility)
        field_map = {}
        for field, value in filter_configs:
            if field in self.proxy_types:
                field_map[field] = value
        
        # Create proxies in the order they first appear in filter_configs
        seen_fields = set()
        self.proxy_chain = []
        for field, value in filter_configs:
            if field in field_map and field not in seen_fields:
                seen_fields.add(field)
                proxy = self.proxy_types[field]()
                self._apply_filter_to_proxy(proxy, field, field_map[field])
                self.proxy_chain.append(proxy)
        
        # Chain the proxies in order: source -> proxy1 -> proxy2 -> ... -> final
        if not self.proxy_chain:
            self.final_model = self.source_model
            return
            
        current_model = self.source_model
        for proxy in self.proxy_chain:
            proxy.setSourceModel(current_model)
            current_model = proxy
        
        self.final_model = current_model
    
    def _apply_filter_to_proxy(self, proxy, field, value):
        """Apply the filter value to the appropriate proxy."""
        if field == 'level':
            proxy.set_level_filter(value)
        elif field in ['source', 'logger', 'message']:
            # For text fields, create regex to match the field
            escaped_pattern = re.escape(value)
            regex_pattern = f".*{escaped_pattern}.*"
            proxy.set_filter_pattern(regex_pattern)
        else:
            # Fallback for any other text fields
            escaped_pattern = re.escape(value)
            regex_pattern = f".*{escaped_pattern}.*"
            proxy.set_filter_pattern(regex_pattern)
    
    def rowCount(self):
        """Return row count of final model."""
        return self.final_model.rowCount()


# Create type alias for easy switching between implementations
# Change this line to switch between Python and Chained filtering
USE_CHAINED_FILTERING = True

if USE_CHAINED_FILTERING:
    LogFilterProxyModel = ChainedLogFilterManager
else:
    LogFilterProxyModel = PythonLogFilterProxyModel