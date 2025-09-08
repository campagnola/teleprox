import re
import traceback

from teleprox import qt
from .constants import ItemDataRole, LogColumns, attrs_not_shown_as_children, ignorable_child_attrs
from .utils import level_colors, thread_color


class LogModel(qt.QStandardItemModel):
    """Custom model that supports lazy loading of exception details using dummy placeholders."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Unique ID counter for log entries
        self._next_log_id = 0

    def append_record(self, rec):
        """Append a row of log data, handling lazy loading placeholders for expandable records."""
        self._create_and_add_record_row(rec)

    def set_records(self, *records):
        """Clear all existing records and set new ones, preserving ID counter."""
        # Clear existing data
        self.clear()
        # Reset headers since clear() removes them
        self.setHorizontalHeaderLabels(LogColumns.TITLES)

        # Add each new record
        for rec in records:
            self._create_and_add_record_row(rec)

    def _create_and_add_record_row(self, rec):
        """Create and add a single record row with lazy loading support."""
        # Create items for each column using LogColumns order
        row_items = [
            qt.QStandardItem(self._get_column_text(rec, col_id))
            for col_id in range(len(LogColumns.TITLES))
        ]

        # Set colors based on log level
        level_color = level_colors.get(rec.levelno, "#000000")
        row_items[LogColumns.LEVEL].setForeground(qt.QColor(level_color))
        row_items[LogColumns.MESSAGE].setForeground(qt.QColor(level_color))
        # Set process/thread colors
        source_color = thread_color(self._get_column_text(rec, LogColumns.SOURCE))
        row_items[LogColumns.SOURCE].setForeground(qt.QColor(source_color))

        # Assign unique ID to this log entry
        log_id = self._next_log_id
        self._next_log_id += 1

        # Set all filtering data using centralized method
        self._set_filter_data_on_items(row_items, rec)

        # Set data unique to main row items
        row_items[0].log_record = rec
        row_items[0].setData(log_id, ItemDataRole.LOG_ID)  # Store unique log ID
        row_items[0].setData(
            rec, ItemDataRole.PYTHON_DATA
        )  # Also store LogRecord in Qt data for consistency

        # Add items to the model
        self.appendRow(row_items)

        # Check if this record has any expandable information for lazy loading
        child_attrs = [
            k
            for k in rec.__dict__
            if (
                k not in attrs_not_shown_as_children
                and not k.startswith('_')
                and (k not in ignorable_child_attrs or getattr(rec, k) is not None)
            )
        ]
        row_items[0].child_attrs = child_attrs  # Store child attributes for later expansion

        if len(child_attrs) > 0:
            # Add loading placeholder for lazy expansion
            placeholder = qt.QStandardItem("Loading...")
            self._set_filter_data_on_item(placeholder, rec)
            row_items[0].appendRow([placeholder])
            row_items[0].has_child_placeholder = True
        else:
            row_items[0].has_child_placeholder = False

    def item_expanded(self, item):
        """An item was expanded in a tree view - check if it has a placeholder."""
        if getattr(item, 'has_child_placeholder', False):
            self.replace_placeholder_with_content(item)

    def replace_placeholder_with_content(self, parent_item):
        """Replace loading placeholder with actual record attribute details."""
        if not parent_item.has_child_placeholder:
            return

        # Get the stored log record
        log_record = parent_item.log_record
        if log_record is None:
            return

        # Remove the placeholder child
        parent_item.removeRow(0)
        parent_item.has_child_placeholder = False

        # Create and add real record attribute children
        children = self._create_record_attribute_children(log_record)
        for child_row in children:
            parent_item.appendRow(child_row)

    def _get_column_count(self):
        """Get the number of columns based on LogColumns TITLES."""
        return len(LogColumns.TITLES)

    def _create_record_attribute_children(self, record):
        """Create child items for all log record attributes, routing each to appropriate handler."""
        children = []

        for attr_name, attr_value in record.__dict__.items():
            # Skip standard attributes and private attributes
            if attr_name.startswith('_') or attr_name in attrs_not_shown_as_children:
                continue

            # Route to appropriate handler based on attribute name
            handler = self._get_attribute_handler(attr_name)
            attr_children = handler(record, attr_name, attr_value)
            children.extend(attr_children)

        return children

    def _get_attribute_handler(self, attr_name):
        """Get the appropriate handler function for an attribute based on its name."""
        # Handler patterns in priority order
        handlers = [
            # Exception info handlers
            (
                ['exc_info'],
                lambda name: name == 'exc_info' or name.endswith('_exc_info'),
                self._create_exc_info_children,
            ),
            # Exception text handlers
            (
                ['exc_text'],
                lambda name: name == 'exc_text' or name.endswith('_exc_text'),
                self._create_exc_text_children,
            ),
            # Stack/traceback handlers
            (
                ['stack_info', 'stack', 'traceback'],
                lambda name: (
                    name == 'stack_info'
                    or name.endswith('_stack_info')
                    or name.endswith('_stack')
                    or name.endswith('_traceback')
                ),
                self._create_stack_children,
            ),
        ]

        # Check each handler pattern
        for keywords, matcher, handler_func in handlers:
            if matcher(attr_name):
                return handler_func

        # Default handler for other attributes
        return self._create_generic_attribute_children

    def _create_generic_attribute_children(self, record, attr_name, attr_value):
        """Handle generic attributes that don't match specific patterns."""
        return [self._create_single_extra_attribute_child(attr_name, attr_value, record)]

    def _create_sibling_items_with_filter_data(self, record):
        """Create sibling items (columns 1-8) with inherited filter data for Qt-native filtering.

        Note: Column 0 (Timestamp) is handled by the category item itself.
        """
        sibling_items = [qt.QStandardItem("") for _ in range(self._get_column_count() - 1)]
        self._set_filter_data_on_items(sibling_items, record)

        return sibling_items

    def _set_filter_data_on_item(self, item, record):
        """Set inherited filter data on a single item for Qt-native filtering."""
        item.setData(record.created, ItemDataRole.NUMERIC_TIMESTAMP)
        item.setData(record.processName, ItemDataRole.PROCESS_NAME)
        item.setData(record.threadName, ItemDataRole.THREAD_NAME)
        item.setData(record.name, ItemDataRole.LOGGER_NAME)
        item.setData(record.levelno, ItemDataRole.LEVEL_NUMBER)
        item.setData(self._get_level_cipher(record.levelno), ItemDataRole.LEVEL_CIPHER)
        item.setData(self._get_column_text(record, LogColumns.MESSAGE), ItemDataRole.MESSAGE_TEXT)
        item.setData(self._get_column_text(record, LogColumns.HOST), ItemDataRole.HOST_NAME)
        item.setData(self._get_column_text(record, LogColumns.SOURCE), ItemDataRole.SOURCE_TEXT)
        item.setData(self._get_column_text(record, LogColumns.TASK), ItemDataRole.TASK_NAME)

    def _set_filter_data_on_items(self, items, record):
        """Set inherited filter data on a list of items for Qt-native filtering."""
        for item in items:
            self._set_filter_data_on_item(item, record)

    def _create_exc_info_children(self, record, attr_name, attr_value):
        """Create child items for exception information from a specific attribute."""
        # Skip if exc_info is None or empty
        if not attr_value:
            return []
        # strings get deserialized from log files as-is
        if isinstance(attr_value, str):
            return self._create_exc_text_children(record, attr_name, attr_value)

        # Handle exc_info type
        exc_type, exc_value, exc_tb = attr_value
        category_name = f"Exception ({attr_name}): {exc_value}"
        exc_category_item = self._create_category_item(category_name, record)

        # Add exception details as children of the category
        exception_children = self._create_exception_details(attr_value, record)
        for child_row in exception_children:
            exc_category_item.appendRow(child_row)

        # Check if this is a RemoteCallException - add remote children as siblings
        children = []

        if exc_value:
            remote_children = self._create_remote_exception_children(exc_value, record)
            children.extend(remote_children)

        sibling_items = self._create_sibling_items_with_filter_data(record)
        children.append([exc_category_item] + sibling_items)

        return children

    def _create_exc_text_children(self, record, attr_name, attr_value):
        """Create child items for pre-formatted exception information from a specific attribute."""
        children = []

        # Skip if exc_text is None or empty
        if not attr_value:
            return children

        # Handle exc_text type
        category_name = f"Exception Text ({attr_name})"
        exc_category_item = self._create_category_item(category_name, record)

        lines = attr_value.split('\n')
        for i, line in enumerate(lines):
            if line.strip():
                line_row = self._create_child_row(
                    "",
                    line.strip(),
                    {
                        'type': 'exception_text',
                        'text': line.strip(),
                        'line_number': i + 1,
                        'parent_record': record,
                    },
                    record,
                )
                exc_category_item.appendRow(line_row)

        sibling_items = self._create_sibling_items_with_filter_data(record)
        children.append([exc_category_item] + sibling_items)

        return children

    def _create_stack_children(self, record, attr_name, attr_value):
        """Create child items for stack information from a specific attribute."""
        children = []

        # Skip if stack_info is None or empty
        if not attr_value:
            return children

        category_name = f"Stack ({attr_name})"
        stack_category_item = self._create_category_item(category_name, record)

        # Parse stack info into frames
        stack_frames = self._parse_stack_info(attr_value)
        for frame_text in stack_frames:
            # Use centralized frame processing
            frame_children = self._create_frame_children(frame_text, 'stack_frame', record)
            for frame_row in frame_children:
                stack_category_item.appendRow(frame_row)

        # Create properly initialized sibling items for the stack category row
        sibling_items = self._create_sibling_items_with_filter_data(record)
        children.append([stack_category_item] + sibling_items)

        return children

    def _create_single_extra_attribute_child(self, attr_name, attr_value, record):
        """Create a child item for a single extra attribute."""
        # Check if this is a simple value that can be displayed inline
        attr_children = self._create_attribute_children(attr_value, record)

        if attr_children:
            # Complex value - create category with children
            attr_category_item = self._create_category_item(attr_name, record)

            for child_row in attr_children:
                attr_category_item.appendRow(child_row)

            # Create properly initialized sibling items for the category row
            sibling_items = self._create_sibling_items_with_filter_data(record)
            return [attr_category_item] + sibling_items

        # Simple value - display as "attribute: value"
        try:
            value_str = str(attr_value)
        except (TypeError, ValueError, RuntimeError):
            try:
                value_str = repr(attr_value)
            except (TypeError, ValueError, RuntimeError):
                value_str = f"<{type(attr_value).__name__} object>"

        inline_display = f"{attr_name}: {value_str}"
        return self._create_child_row(
            "",
            inline_display,
            {
                'type': 'simple_attribute',
                'text': inline_display,
                'attr_name': attr_name,
                'attr_value': attr_value,
                'parent_record': record,
            },
            record,
        )

    def _create_category_item(self, text, parent_record):
        """Create a category item for grouping related log attributes."""
        category_item = qt.QStandardItem(text)

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

    def _create_exception_details(self, exc_info, record):
        """Create the detailed exception information."""
        children = []

        # Handle exc_info (including chained exceptions)
        exc_type, exc_value, exc_tb = exc_info
        if exc_type and exc_value:
            # Process the full exception chain
            exception_chain = self._build_exception_chain(exc_type, exc_value, exc_tb)

            # Add all exceptions in the chain (root cause first, final exception last)
            for i, chain_item in enumerate(exception_chain):
                # Add traceback frames for this exception
                if chain_item['traceback']:
                    tb_lines = traceback.format_tb(chain_item['traceback'])
                    for line in tb_lines:
                        # Use centralized frame processing
                        frame_children = self._create_frame_children(
                            line, 'traceback_frame', record
                        )
                        children.extend(frame_children)

                # Add the exception message
                exc_msg = f"{chain_item['type'].__name__}: {chain_item['value']}"
                exc_row = self._create_child_row(
                    "",
                    exc_msg,
                    {'type': 'exception', 'text': exc_msg, 'parent_record': record},
                    record,
                )
                children.append(exc_row)

                # Add chain separator AFTER the exception (if the NEXT exception has a cause_text)
                if i < len(exception_chain) - 1 and exception_chain[i + 1]['cause_text']:
                    separator_row = self._create_child_row(
                        "",
                        exception_chain[i + 1]['cause_text'],
                        {
                            'type': 'chain_separator',
                            'text': exception_chain[i + 1]['cause_text'],
                            'parent_record': record,
                        },
                        record,
                    )
                    children.append(separator_row)

        return children

    def _create_attribute_children(self, value, parent_record):
        """Recursively create children for an attribute value."""

        children = []

        # Handle exceptions and stack summaries with existing formatting
        if isinstance(value, Exception):
            # Use similar formatting as exc_info
            exc_msg = f"{type(value).__name__}: {value}"
            exc_row = self._create_child_row(
                "",
                exc_msg,
                {'type': 'exception', 'text': exc_msg, 'parent_record': parent_record},
                parent_record,
            )
            children.append(exc_row)

        elif hasattr(value, '__traceback__') and value.__traceback__:
            # Handle exception with traceback
            tb_lines = traceback.format_tb(value.__traceback__)
            for line in tb_lines:
                # Use centralized frame processing
                frame_children = self._create_frame_children(line, 'traceback_frame', parent_record)
                children.extend(frame_children)

        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                item_children = self._create_attribute_children(item, parent_record)
                if item_children:
                    # Create an index item
                    index_item = self._create_child_row(
                        "",
                        f"[{i}]",
                        {'type': 'list_index', 'text': f"[{i}]", 'parent_record': parent_record},
                        parent_record,
                    )
                    # Add the actual content as sub-children
                    for child_row in item_children:
                        index_item[0].appendRow(child_row)
                    children.append(index_item)
                else:
                    try:
                        item_str = str(item)
                    except (TypeError, ValueError):
                        item_str = repr(item)
                    item_row = self._create_child_row(
                        "",
                        f"[{i}]: {item_str}",
                        {'type': 'list_item', 'text': item_str, 'parent_record': parent_record},
                        parent_record,
                    )
                    children.append(item_row)

        elif isinstance(value, dict):
            for key, dict_value in value.items():
                dict_children = self._create_attribute_children(dict_value, parent_record)
                if dict_children:
                    # Create a key item with children
                    key_item = self._create_child_row(
                        "",
                        str(key),
                        {'type': 'dict_key', 'text': str(key), 'parent_record': parent_record},
                        parent_record,
                    )
                    for child_row in dict_children:
                        key_item[0].appendRow(child_row)
                    children.append(key_item)
                else:
                    # Simple value, show inline
                    try:
                        value_str = str(dict_value)
                    except (TypeError, ValueError):
                        value_str = repr(dict_value)
                    key_row = self._create_child_row(
                        "",
                        f"{key}: {value_str}",
                        {'type': 'dict_item', 'text': value_str, 'parent_record': parent_record},
                        parent_record,
                    )
                    children.append(key_row)

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
                    cause_text = (
                        "During handling of the above exception, another exception occurred:"
                    )
                    next_exc = current_exc.__context__
                    next_type = type(next_exc)
                    next_tb = getattr(next_exc, '__traceback__', None)

            # Add current exception to chain
            chain.append(
                {
                    'type': current_type,
                    'value': current_exc,
                    'traceback': current_tb,
                    'cause_text': cause_text,
                }
            )

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
                frame_row = self._create_child_row(
                    "",
                    frame_line,
                    {
                        'type': frame_type,
                        'text': frame_line,
                        'line_number': k + 1,
                        'parent_record': parent_record,
                        'frame_parts': frame_parts,
                    },
                    parent_record,
                )
                children.append(frame_row)

        return children

    def _split_traceback_line(self, text):
        """Split a traceback line into parts to identify the clickable file portion."""
        # Pattern to match the file path and line number portion
        # Example: 'File "/path/to/file.py", line 123, in function_name'
        # We want to identify: '/path/to/file.py", line 123'
        # Also check for simple path:line format like '/path/file.py:123'
        match = re.search(r'File "([^"]+)", line (\d+)', text) or re.search(r'([^:]+):(\d+)', text)

        if match:
            file_path = match.group(1)
            line_number = int(match.group(2))
            return {
                'has_file_ref': True,
                'file_path': file_path,
                'line_number': line_number,
                'clickable_start': (match.start()),
                'clickable_end': (match.end()),
                'full_text': text,
            }

        return {'has_file_ref': False, 'full_text': text}

    def _create_child_row(self, label, message, data_dict, parent_record):
        """Create a standardized child row for exception details."""
        # For child rows, put all content in the first column since it will span
        # Create items for each column dynamically
        item = qt.QStandardItem(message)

        # INHERIT PARENT'S FILTER DATA so Qt native filtering includes children
        # This allows children to pass the same filters as their parents
        # Set the same data on ALL items so filtering works regardless of which column is checked
        self._set_filter_data_on_item(item, parent_record)

        # Store the data dict for click handling
        item.setData(data_dict, ItemDataRole.PYTHON_DATA)

        # Set colors to differentiate from main log entries
        item.setForeground(qt.QColor("#444444"))  # Dark gray for child text

        # Make traceback/stack frame items clickable for file navigation
        if data_dict.get('type') in ['traceback_frame', 'stack_frame']:
            item.setFlags(qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable)  # Allow clicking
        else:
            # Make other exception items not selectable
            item.setFlags(qt.Qt.ItemIsEnabled)  # Remove ItemIsSelectable flag

        # Apply styling to the timestamp column item (where content is now)
        # Apply monospace font for code-like content
        text = data_dict.get('text', '')
        should_use_monospace = (
            data_dict.get('type') in ['traceback_frame', 'stack_frame']
            or (
                text.startswith("    ") and not text.strip().startswith("File ")
            )  # Code lines starting with 4+ spaces
            or "^^^^" in text  # Lines with error pointer characters
        )

        if should_use_monospace:
            # Use monospace font for all code lines
            monospace_font = qt.QFont("Consolas, Monaco, 'Courier New', monospace")
            monospace_font.setStyleHint(qt.QFont.TypeWriter)
            item.setFont(monospace_font)

        # Make exception messages bold
        if data_dict.get('type') == 'exception':
            bold_font = item.font()
            bold_font.setBold(True)
            item.setFont(bold_font)

        # Style stack and chain separators
        if data_dict.get('type') in ('stack_separator', 'chain_separator'):
            italic_font = item.font()
            italic_font.setItalic(True)
            item.setFont(italic_font)
            item.setForeground(qt.QColor("#888888"))  # Lighter gray for separators

        return [item]

    def _get_level_cipher(self, level_int):
        """Get level cipher for a given level number."""
        from .utils import level_to_cipher

        return level_to_cipher(level_int)

    def _get_column_text(self, record, col_id):
        """Get display text for a specific column, with caching."""
        # Check if we already have cached values for this record
        if not hasattr(record, '_column_text_cache'):
            record._column_text_cache = {}

        if col_id not in record._column_text_cache:
            # Generate and cache the text for this column
            import time

            if col_id == LogColumns.TIMESTAMP:
                record._column_text_cache[col_id] = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(record.created)
                ) + f'{record.created % 1.0:.3f}'.lstrip('0')
            elif col_id == LogColumns.HOST:
                record._column_text_cache[col_id] = getattr(record, 'hostName', '') or 'localhost'
            elif col_id == LogColumns.PROCESS:
                record._column_text_cache[col_id] = record.processName
            elif col_id == LogColumns.THREAD:
                record._column_text_cache[col_id] = record.threadName
            elif col_id == LogColumns.SOURCE:
                record._column_text_cache[col_id] = f"{record.processName}/{record.threadName}"
            elif col_id == LogColumns.LOGGER:
                record._column_text_cache[col_id] = record.name
            elif col_id == LogColumns.LEVEL:
                record._column_text_cache[col_id] = f"{record.levelno} - {record.levelname}"
            elif col_id == LogColumns.MESSAGE:
                record._column_text_cache[col_id] = record.getMessage()
            elif col_id == LogColumns.TASK:
                record._column_text_cache[col_id] = getattr(record, 'taskName', '')
            else:
                record._column_text_cache[col_id] = ""

        return record._column_text_cache[col_id]

    def _create_remote_exception_children(self, exc_value, record):
        """Create children for remote exception traceback if this is a RemoteCallException."""
        children = []

        # Check if this is a RemoteCallException with remote traceback data
        if hasattr(exc_value, 'remote_stack_info') and exc_value.remote_stack_info:
            # Create "Remote Stack" category
            remote_stack_category = self._create_category_item("Remote Stack", record)

            # Parse remote stack info like we do for regular stack_info
            stack_frames = self._parse_stack_info(exc_value.remote_stack_info)
            for frame_text in stack_frames:
                frame_children = self._create_frame_children(
                    frame_text, 'remote_stack_frame', record
                )
                for frame_row in frame_children:
                    remote_stack_category.appendRow(frame_row)

            # Create sibling items for the remote stack category
            sibling_items = self._create_sibling_items_with_filter_data(record)
            children.append([remote_stack_category] + sibling_items)

        if hasattr(exc_value, 'remote_exc_traceback') and exc_value.remote_exc_traceback:
            # Create "Remote Exception" category
            remote_exc_category = self._create_category_item("Remote Exception", record)

            # Parse remote exception traceback like we do for regular stack_info
            exc_frames = self._parse_stack_info(exc_value.remote_exc_traceback)
            for frame_text in exc_frames:
                frame_children = self._create_frame_children(
                    frame_text, 'remote_exception_frame', record
                )
                for frame_row in frame_children:
                    remote_exc_category.appendRow(frame_row)

            # Create sibling items for the remote exception category
            sibling_items = self._create_sibling_items_with_filter_data(record)
            children.append([remote_exc_category] + sibling_items)

        return children
