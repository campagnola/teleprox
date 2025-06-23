import traceback
from teleprox import qt
from .constants import ItemDataRole, LogColumns


class LogModel(qt.QStandardItemModel):
    """Custom model that supports lazy loading of exception details using dummy placeholders."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def _get_column_count(self):
        """Get the number of columns based on LogColumns TITLES."""
        return len(LogColumns.TITLES)
    
    def _create_record_attribute_children(self, record):
        """Create child items for all log record attributes (exc_info, stack_info, extra, etc.)."""
        children = []
        
        # Handle exception information
        exc_children = self._create_exception_children(record)
        children.extend(exc_children)
        
        # Handle stack information
        stack_children = self._create_stack_children(record)
        children.extend(stack_children)
        
        # Handle extra attributes
        extra_children = self._create_extra_attribute_children(record)
        children.extend(extra_children)
        
        return children

    def _create_sibling_items_with_filter_data(self, record):
        """Create sibling items (columns 1-8) with inherited filter data for Qt-native filtering.
        
        Note: Column 0 (Timestamp) is handled by the category item itself.
        """
        sibling_items = [qt.QStandardItem("") for _ in range(self._get_column_count() - 1)]
        for sibling_item in sibling_items:
            sibling_item.setData(record.created, ItemDataRole.NUMERIC_TIMESTAMP)
            sibling_item.setData(record.processName, ItemDataRole.PROCESS_NAME)
            sibling_item.setData(record.threadName, ItemDataRole.THREAD_NAME)
            sibling_item.setData(record.name, ItemDataRole.LOGGER_NAME)
            sibling_item.setData(record.levelno, ItemDataRole.LEVEL_NUMBER)
            sibling_item.setData(self._get_level_cipher(record.levelno), ItemDataRole.LEVEL_CIPHER)
            sibling_item.setData(record.getMessage(), ItemDataRole.MESSAGE_TEXT)
        
        # Set display text for new columns so FieldFilterProxy filtering works
        # Note: sibling_items[0] corresponds to LogColumns.HOST (column 1)
        #       sibling_items[1] corresponds to LogColumns.PROCESS (column 2)
        #       sibling_items[2] corresponds to LogColumns.THREAD (column 3)
        host_name = getattr(record, 'hostName', '') or 'localhost'
        sibling_items[LogColumns.HOST - 1].setText(host_name)  # -1 because no timestamp column
        sibling_items[LogColumns.PROCESS - 1].setText(record.processName)
        sibling_items[LogColumns.THREAD - 1].setText(record.threadName)
        
        return sibling_items

    def _set_filter_data_on_item(self, item, record):
        """Set inherited filter data on a single item for Qt-native filtering."""
        item.setData(record.created, ItemDataRole.NUMERIC_TIMESTAMP)
        item.setData(record.processName, ItemDataRole.PROCESS_NAME)
        item.setData(record.threadName, ItemDataRole.THREAD_NAME)
        item.setData(record.name, ItemDataRole.LOGGER_NAME)
        item.setData(record.levelno, ItemDataRole.LEVEL_NUMBER)
        item.setData(self._get_level_cipher(record.levelno), ItemDataRole.LEVEL_CIPHER)
        item.setData(record.getMessage(), ItemDataRole.MESSAGE_TEXT)

    def _set_filter_data_on_row_items(self, items, record):
        """Set inherited filter data on a list of row items for Qt-native filtering."""
        for item in items:
            self._set_filter_data_on_item(item, record)

    def _create_exception_children(self, record):
        """Create child items for exception information (exc_info, exc_text)."""
        children = []
        
        # Handle exc_info under "Exception: {exc}" category
        if hasattr(record, 'exc_info') and record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            if exc_type and exc_value:
                # Create exception category item
                exc_category_name = f"Exception: {exc_value}"
                exc_category_item = self._create_category_item(exc_category_name, 'exception_category', record)
                
                # Add exception details as children of the category
                exception_children = self._create_exception_details(record)
                for child_row in exception_children:
                    exc_category_item.appendRow(child_row)
                
                # Create properly initialized sibling items for the exception category row
                sibling_items = self._create_sibling_items_with_filter_data(record)
                children.append([exc_category_item] + sibling_items)
        
        # Handle exc_text under exception category if no exc_info
        elif hasattr(record, 'exc_text') and record.exc_text:
            exc_category_item = self._create_category_item("Exception Text", 'exception_category', record)
            
            lines = record.exc_text.split('\n')
            for i, line in enumerate(lines):
                if line.strip():
                    line_row = self._create_child_row("", line.strip(), {
                        'type': 'exception_text',
                        'text': line.strip(),
                        'line_number': i + 1,
                        'parent_record': record
                    }, record)
                    exc_category_item.appendRow(line_row)
            
            # Create properly initialized sibling items for the exception text category row
            sibling_items = self._create_sibling_items_with_filter_data(record)
            children.append([exc_category_item] + sibling_items)
        
        return children

    def _create_stack_children(self, record):
        """Create child items for stack information."""
        children = []
        
        # Handle stack_info under "Log Message Stack" category
        if hasattr(record, 'stack_info') and record.stack_info:
            stack_category_item = self._create_category_item("Log Message Stack", 'stack_category', record)
            
            # Parse stack info into frames
            stack_frames = self._parse_stack_info(record.stack_info)
            for frame_text in stack_frames:
                # Use centralized frame processing
                frame_children = self._create_frame_children(frame_text, 'stack_frame', record)
                for frame_row in frame_children:
                    stack_category_item.appendRow(frame_row)
            
            # Create properly initialized sibling items for the stack category row
            sibling_items = self._create_sibling_items_with_filter_data(record)
            children.append([stack_category_item] + sibling_items)
        
        return children

    def _create_extra_attribute_children(self, record):
        """Create child items for extra log record attributes."""
        children = []
        
        if hasattr(record, '__dict__'):
            # Standard LogRecord attributes to exclude
            standard_attrs = {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                'module', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                'thread', 'threadName', 'processName', 'process', 'getMessage',
                'exc_info', 'exc_text', 'stack_info', 'tags', 'taskName'  # exclude our standard ones
            }
            
            for attr_name, attr_value in record.__dict__.items():
                if attr_name not in standard_attrs and not attr_name.startswith('_'):
                    attr_child = self._create_single_extra_attribute_child(attr_name, attr_value, record)
                    if attr_child:
                        children.append(attr_child)
        
        return children

    def _create_single_extra_attribute_child(self, attr_name, attr_value, record):
        """Create a child item for a single extra attribute."""
        # Check if this is a simple value that can be displayed inline
        attr_children = self._create_attribute_children(attr_value, record)
        
        if not attr_children:
            # Simple value - display as "attribute: value"
            try:
                value_str = str(attr_value)
            except:
                try:
                    value_str = repr(attr_value)
                except:
                    value_str = f"<{type(attr_value).__name__} object>"
            
            inline_display = f"{attr_name}: {value_str}"
            attr_row = self._create_child_row("", inline_display, {
                'type': 'simple_attribute',
                'text': inline_display,
                'attr_name': attr_name,
                'attr_value': attr_value,
                'parent_record': record
            }, record)
            return attr_row
        else:
            # Complex value - create category with children
            attr_category_item = self._create_category_item(attr_name, 'extra_attribute', record)
            
            for child_row in attr_children:
                attr_category_item.appendRow(child_row)
            
            # Create properly initialized sibling items for the category row
            sibling_items = self._create_sibling_items_with_filter_data(record)
            return [attr_category_item] + sibling_items
        
        return None
    
    def _create_category_item(self, name, category_type, parent_record):
        """Create a category item for grouping related log attributes."""
        category_item = qt.QStandardItem(name)
        category_item.setData({
            'type': category_type,
            'name': name,
            'parent_record': parent_record
        }, ItemDataRole.PYTHON_DATA)
        
        # Inherit parent's filter data for Qt-native filtering
        self._set_filter_data_on_item(category_item, parent_record)
        
        # Note: Sibling items for category rows are now created where the category is used
        
        # For categories, the text is already in the first column (category_item itself)
        # So no additional changes needed for text placement
        
        # Style category items
        category_item.setForeground(qt.QColor("#0066CC"))  # Blue for categories
        bold_font = category_item.font()
        bold_font.setBold(True)
        category_item.setFont(bold_font)
        
        # Make categories not selectable but expandable
        category_item.setFlags(qt.Qt.ItemIsEnabled)
        
        return category_item
    
    def _create_exception_details(self, record):
        """Create the detailed exception information (same as before)."""
        children = []
        
        # Handle exc_info (including chained exceptions)
        exc_type, exc_value, exc_tb = record.exc_info
        if exc_type and exc_value:
            # Process the full exception chain
            exception_chain = self._build_exception_chain(exc_type, exc_value, exc_tb)
            
            # Add all exceptions in the chain (root cause first, final exception last)
            for i, chain_item in enumerate(exception_chain):
                # Add traceback frames for this exception
                if chain_item['traceback']:
                    tb_lines = traceback.format_tb(chain_item['traceback'])
                    for j, line in enumerate(tb_lines):
                        # Use centralized frame processing
                        frame_children = self._create_frame_children(line, 'traceback_frame', record)
                        children.extend(frame_children)
                
                # Add the exception message
                exc_msg = f"{chain_item['type'].__name__}: {chain_item['value']}"
                exc_row = self._create_child_row("", exc_msg, {
                    'type': 'exception',
                    'text': exc_msg,
                    'parent_record': record
                }, record)
                children.append(exc_row)
                
                # Add chain separator AFTER the exception (if the NEXT exception has a cause_text)
                if i < len(exception_chain) - 1 and exception_chain[i + 1]['cause_text']:
                    separator_row = self._create_child_row("", exception_chain[i + 1]['cause_text'], {
                        'type': 'chain_separator',
                        'text': exception_chain[i + 1]['cause_text'],
                        'parent_record': record
                    }, record)
                    children.append(separator_row)
        
        return children
    
    def _create_attribute_children(self, value, parent_record):
        """Recursively create children for an attribute value."""
        import types
        children = []
        
        # Handle exceptions and stack summaries with existing formatting
        if isinstance(value, Exception):
            # Use similar formatting as exc_info
            exc_msg = f"{type(value).__name__}: {value}"
            exc_row = self._create_child_row("", exc_msg, {
                'type': 'exception',
                'text': exc_msg,
                'parent_record': parent_record
            }, parent_record)
            children.append(exc_row)
            
        elif hasattr(value, '__traceback__') and value.__traceback__:
            # Handle exception with traceback
            tb_lines = traceback.format_tb(value.__traceback__)
            for i, line in enumerate(tb_lines):
                # Use centralized frame processing
                frame_children = self._create_frame_children(line, 'traceback_frame', parent_record)
                children.extend(frame_children)
                
        # Handle lists, tuples
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                item_children = self._create_attribute_children(item, parent_record)
                if item_children:
                    # Create an index item
                    index_item = self._create_child_row("", f"[{i}]", {
                        'type': 'list_index',
                        'text': f"[{i}]",
                        'parent_record': parent_record
                    }, parent_record)
                    # Add the actual content as sub-children
                    for child_row in item_children:
                        index_item[0].appendRow(child_row)
                    children.append(index_item)
                else:
                    # Simple value, show inline
                    try:
                        item_str = str(item)
                    except:
                        item_str = repr(item)
                    item_row = self._create_child_row("", f"[{i}]: {item_str}", {
                        'type': 'list_item',
                        'text': item_str,
                        'parent_record': parent_record
                    }, parent_record)
                    children.append(item_row)
                    
        # Handle dictionaries
        elif isinstance(value, dict):
            for key, dict_value in value.items():
                dict_children = self._create_attribute_children(dict_value, parent_record)
                if dict_children:
                    # Create a key item with children
                    key_item = self._create_child_row("", str(key), {
                        'type': 'dict_key',
                        'text': str(key),
                        'parent_record': parent_record
                    }, parent_record)
                    for child_row in dict_children:
                        key_item[0].appendRow(child_row)
                    children.append(key_item)
                else:
                    # Simple value, show inline
                    try:
                        value_str = str(dict_value)
                    except:
                        value_str = repr(dict_value)
                    key_row = self._create_child_row("", f"{key}: {value_str}", {
                        'type': 'dict_item',
                        'text': value_str,
                        'parent_record': parent_record
                    }, parent_record)
                    children.append(key_row)
                    
        # Handle simple values - return empty list to indicate it should be inline
        else:
            # Don't create children for simple values - they'll be handled inline
            pass
        
        return children
    
    def _parse_stack_info(self, stack_info):
        """Parse stack_info into frames like traceback frames (one item per code line)."""
        frames = []
        lines = stack_info.split('\n')
        
        current_frame = []
        for line in lines:
            line = line.rstrip()
            if not line:
                continue
                
            # Check if this is a file location line (starts with '  File ')
            if line.startswith('  File '):
                # If we have a previous frame, save it
                if current_frame:
                    frames.append('\n'.join(current_frame))
                # Start new frame with the file line
                current_frame = [line]
            elif line.startswith('    '):
                # This is a code line, add to current frame
                if current_frame:
                    current_frame.append(line)
            else:
                # Other lines (like stack header), treat as separate frames
                if current_frame:
                    frames.append('\n'.join(current_frame))
                    current_frame = []
                if line.strip():
                    frames.append(line)
        
        # Don't forget the last frame
        if current_frame:
            frames.append('\n'.join(current_frame))
            
        return frames
    
    def _build_exception_chain(self, exc_type, exc_value, exc_tb):
        """Build the complete exception chain including causes and context."""
        chain = []
        current_exc = exc_value
        current_type = exc_type
        current_tb = exc_tb
        
        while current_exc is not None:
            # Determine cause text for chaining
            cause_text = None
            next_exc = None
            next_type = None
            next_tb = None
            
            # Check for explicit cause (__cause__)
            if hasattr(current_exc, '__cause__') and current_exc.__cause__ is not None:
                cause_text = "The above exception was the direct cause of the following exception:"
                next_exc = current_exc.__cause__ 
                next_type = type(next_exc)
                next_tb = getattr(next_exc, '__traceback__', None)
            # Check for context (__context__) if no explicit cause
            elif hasattr(current_exc, '__context__') and current_exc.__context__ is not None:
                # Only show context if suppress_context is False
                if not getattr(current_exc, '__suppress_context__', False):
                    cause_text = "During handling of the above exception, another exception occurred:"
                    next_exc = current_exc.__context__
                    next_type = type(next_exc)
                    next_tb = getattr(next_exc, '__traceback__', None)
            
            # Add current exception to chain
            chain.append({
                'type': current_type,
                'value': current_exc,
                'traceback': current_tb,
                'cause_text': cause_text
            })
            
            # Move to next in chain
            current_exc = next_exc
            current_type = next_type
            current_tb = next_tb
        
        # Reverse to match Python's standard display order:
        # 1. ValueError + traceback + message (root cause first)
        # 2. "The above exception was the direct cause..." (separator)  
        # 3. ConnectionError + traceback + message (final exception)
        
        return list(reversed(chain))
    
    def _create_frame_children(self, frame_text_or_lines, frame_type, parent_record):
        """Create child rows for traceback or stack frames, handling multi-line frames."""
        children = []
        
        # Handle both single strings and lists of strings
        if isinstance(frame_text_or_lines, str):
            # This is a multi-line frame string, split it
            frame_lines = frame_text_or_lines.rstrip('\n').split('\n')
        else:
            # This is already a list of frame lines
            frame_lines = frame_text_or_lines
        
        for k, frame_line in enumerate(frame_lines):
            if frame_line.strip():  # Skip empty lines
                # Split frame line into parts for selective hyperlink formatting
                frame_parts = self._split_traceback_line(frame_line)
                frame_row = self._create_child_row("", frame_line, {
                    'type': frame_type,
                    'text': frame_line,
                    'line_number': k + 1,
                    'parent_record': parent_record,
                    'frame_parts': frame_parts
                }, parent_record)
                children.append(frame_row)
        
        return children
    
    def _split_traceback_line(self, text):
        """Split a traceback line into parts to identify the clickable file portion."""
        import re
        
        # Pattern to match the file path and line number portion
        # Example: 'File "/path/to/file.py", line 123, in function_name'
        # We want to identify: '/path/to/file.py", line 123'
        file_pattern = r'File "([^"]+)", line (\d+)'
        match = re.search(file_pattern, text)
        
        if match:
            file_path = match.group(1)
            line_number = int(match.group(2))
            # Find the start and end positions of the clickable part
            start_pos = match.start()
            end_pos = match.end()
            
            return {
                'has_file_ref': True,
                'file_path': file_path,
                'line_number': line_number,
                'clickable_start': start_pos,
                'clickable_end': end_pos,
                'full_text': text
            }
        
        # Also check for simple path:line format like '/path/file.py:123'
        simple_pattern = r'([^:]+):(\d+)'
        match = re.search(simple_pattern, text)
        if match:
            file_path = match.group(1)
            line_number = int(match.group(2))
            
            return {
                'has_file_ref': True,
                'file_path': file_path,
                'line_number': line_number,
                'clickable_start': match.start(),
                'clickable_end': match.end(),
                'full_text': text
            }
        
        return {
            'has_file_ref': False,
            'full_text': text
        }
    
    def _create_child_row(self, label, message, data_dict, parent_record):
        """Create a standardized child row for exception details."""
        # For child rows, put all content in the first column since it will span
        # Create items for each column dynamically
        row_items = [qt.QStandardItem("") for _ in range(self._get_column_count())]
        row_items[LogColumns.TIMESTAMP].setText(message)  # Put the content in timestamp column
        
        # Store data in the first item (timestamp column)
        row_items[LogColumns.TIMESTAMP].setData(data_dict, ItemDataRole.PYTHON_DATA)
        
        # INHERIT PARENT'S FILTER DATA so Qt native filtering includes children
        # This allows children to pass the same filters as their parents
        # Set the same data on ALL items so filtering works regardless of which column is checked
        self._set_filter_data_on_row_items(row_items, parent_record)
        
        # INHERIT PARENT'S DISPLAY TEXT for new columns so FieldFilterProxy filtering works
        # FieldFilterProxy uses Qt.DisplayRole (display text), not ItemDataRole values
        host_name = getattr(parent_record, 'hostName', '') or 'localhost'
        row_items[LogColumns.HOST].setText(host_name)
        row_items[LogColumns.PROCESS].setText(parent_record.processName)
        row_items[LogColumns.THREAD].setText(parent_record.threadName)
        
        # Set colors to differentiate from main log entries
        row_items[LogColumns.TIMESTAMP].setForeground(qt.QColor("#444444"))  # Dark gray for child text
        
        # Make exception/stack items not selectable
        for item in row_items:
            item.setFlags(qt.Qt.ItemIsEnabled)  # Remove ItemIsSelectable flag
        
        # Apply styling to the timestamp column item (where content is now)
        # Apply monospace font for code-like content
        if data_dict.get('type') in ['traceback_frame', 'stack_frame']:
            # Use monospace font for all code lines
            monospace_font = qt.QFont("Consolas, Monaco, 'Courier New', monospace")
            monospace_font.setStyleHint(qt.QFont.TypeWriter)
            row_items[LogColumns.TIMESTAMP].setFont(monospace_font)
        
        # Make exception messages bold
        if data_dict.get('type') == 'exception':
            bold_font = row_items[LogColumns.TIMESTAMP].font()
            bold_font.setBold(True)
            row_items[LogColumns.TIMESTAMP].setFont(bold_font)
        
        # Style chain separators
        if data_dict.get('type') == 'chain_separator':
            italic_font = row_items[LogColumns.TIMESTAMP].font()
            italic_font.setItalic(True)
            row_items[LogColumns.TIMESTAMP].setFont(italic_font)
            row_items[LogColumns.TIMESTAMP].setForeground(qt.QColor("#888888"))  # Lighter gray for separators
        
        # Style stack separators
        if data_dict.get('type') == 'stack_separator':
            italic_font = row_items[LogColumns.TIMESTAMP].font()
            italic_font.setItalic(True)
            row_items[LogColumns.TIMESTAMP].setFont(italic_font)
            row_items[LogColumns.TIMESTAMP].setForeground(qt.QColor("#888888"))  # Lighter gray for separators
        
        return row_items
    
    def _get_level_cipher(self, level_int):
        """Get level cipher for a given level number."""
        from .utils import level_to_cipher
        return level_to_cipher(level_int)
    
    def add_loading_placeholder(self, parent_item, record):
        """Add a dummy 'loading...' child to indicate expandable content."""
        # Create loading placeholder row
        loading_row = self._create_loading_placeholder_row()
        
        # Add the placeholder as child
        parent_item.appendRow(loading_row)
        
        # Store the record data in the parent for later expansion
        parent_item.setData(record, ItemDataRole.PYTHON_DATA)
        parent_item.setData(True, ItemDataRole.HAS_CHILDREN)
    
    def _create_loading_placeholder_row(self):
        """Create a dummy 'loading...' row."""
        row_items = [qt.QStandardItem("") for _ in range(self._get_column_count())]
        
        # Set specific content for loading indication
        row_items[LogColumns.LEVEL].setText("⏳ Loading...")
        row_items[LogColumns.MESSAGE].setText("Click to expand log details")
        
        # Mark as loading placeholder
        row_items[LogColumns.TIMESTAMP].setData(True, ItemDataRole.IS_LOADING_PLACEHOLDER)
        
        # Style the placeholder
        row_items[LogColumns.LEVEL].setForeground(qt.QColor("#888888"))
        row_items[LogColumns.MESSAGE].setForeground(qt.QColor("#888888"))
        row_items[LogColumns.MESSAGE].setFont(qt.QFont("Arial", 8, qt.QFont.StyleItalic))
        
        return row_items
    
    def has_loading_placeholder(self, parent_item):
        """Check if item has a loading placeholder child."""
        if parent_item.rowCount() == 1:
            child = parent_item.child(0, LogColumns.TIMESTAMP)  # Check timestamp column
            return child and child.data(ItemDataRole.IS_LOADING_PLACEHOLDER) is True
        return False
    
    def replace_placeholder_with_content(self, parent_item):
        """Replace loading placeholder with actual record attribute details."""
        if not self.has_loading_placeholder(parent_item):
            return
        
        # Get the stored log record
        log_record = parent_item.data(ItemDataRole.PYTHON_DATA)
        if log_record is None:
            return
        
        # Remove the placeholder child
        parent_item.removeRow(0)
        
        # Create and add real record attribute children
        children = self._create_record_attribute_children(log_record)
        for child_row in children:
            parent_item.appendRow(child_row)
        
        # Mark as fetched
        parent_item.setData(True, ItemDataRole.CHILDREN_FETCHED)
