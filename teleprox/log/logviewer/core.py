# ABOUTME: Core LogViewer implementation with Qt integration and log handling
# ABOUTME: Contains LogViewer widget, QtLogHandler, and main GUI functionality

import logging
import time
import traceback

from teleprox import qt
from .utils import level_colors, thread_color, level_to_cipher
from .widgets import FilterInputWidget, HighlightDelegate
from .filtering import LogFilterProxyModel, USE_CHAINED_FILTERING
from .constants import ItemDataRole


class LogModel(qt.QStandardItemModel):
    """Custom model that supports lazy loading of exception details using dummy placeholders."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def _create_record_attribute_children(self, record):
        """Create child items for all log record attributes (exc_info, stack_info, extra, etc.)."""
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
                exc_sibling_items = [qt.QStandardItem("") for _ in range(5)]
                for sibling_item in exc_sibling_items:
                    # Inherit parent's filter data for Qt-native filtering
                    sibling_item.setData(record.created, ItemDataRole.NUMERIC_TIMESTAMP)
                    sibling_item.setData(record.processName, ItemDataRole.PROCESS_NAME)
                    sibling_item.setData(record.threadName, ItemDataRole.THREAD_NAME)
                    sibling_item.setData(record.name, ItemDataRole.LOGGER_NAME)
                    sibling_item.setData(record.levelno, ItemDataRole.LEVEL_NUMBER)
                    sibling_item.setData(self._get_level_cipher(record.levelno), ItemDataRole.LEVEL_CIPHER)
                    sibling_item.setData(record.getMessage(), ItemDataRole.MESSAGE_TEXT)
                
                children.append([exc_category_item] + exc_sibling_items)
        
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
            exc_text_sibling_items = [qt.QStandardItem("") for _ in range(5)]
            for sibling_item in exc_text_sibling_items:
                # Inherit parent's filter data for Qt-native filtering
                sibling_item.setData(record.created, ItemDataRole.NUMERIC_TIMESTAMP)
                sibling_item.setData(record.processName, ItemDataRole.PROCESS_NAME)
                sibling_item.setData(record.threadName, ItemDataRole.THREAD_NAME)
                sibling_item.setData(record.name, ItemDataRole.LOGGER_NAME)
                sibling_item.setData(record.levelno, ItemDataRole.LEVEL_NUMBER)
                sibling_item.setData(self._get_level_cipher(record.levelno), ItemDataRole.LEVEL_CIPHER)
                sibling_item.setData(record.getMessage(), ItemDataRole.MESSAGE_TEXT)
            
            children.append([exc_category_item] + exc_text_sibling_items)
        
        # Handle stack_info under "Log Message Stack" category
        if hasattr(record, 'stack_info') and record.stack_info:
            stack_category_item = self._create_category_item("Log Message Stack", 'stack_category', record)
            
            # Parse stack info into frames
            stack_frames = self._parse_stack_info(record.stack_info)
            for frame_text in stack_frames:
                stack_row = self._create_child_row("", frame_text, {
                    'type': 'stack_frame',
                    'text': frame_text,
                    'parent_record': record
                }, record)
                stack_category_item.appendRow(stack_row)
            
            # Create properly initialized sibling items for the stack category row
            stack_sibling_items = [qt.QStandardItem("") for _ in range(5)]
            for sibling_item in stack_sibling_items:
                # Inherit parent's filter data for Qt-native filtering
                sibling_item.setData(record.created, ItemDataRole.NUMERIC_TIMESTAMP)
                sibling_item.setData(record.processName, ItemDataRole.PROCESS_NAME)
                sibling_item.setData(record.threadName, ItemDataRole.THREAD_NAME)
                sibling_item.setData(record.name, ItemDataRole.LOGGER_NAME)
                sibling_item.setData(record.levelno, ItemDataRole.LEVEL_NUMBER)
                sibling_item.setData(self._get_level_cipher(record.levelno), ItemDataRole.LEVEL_CIPHER)
                sibling_item.setData(record.getMessage(), ItemDataRole.MESSAGE_TEXT)
            
            children.append([stack_category_item] + stack_sibling_items)
        
        # Handle extra attributes
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
                        children.append(attr_row)
                    else:
                        # Complex value - create category with children
                        attr_category_item = self._create_category_item(attr_name, 'extra_attribute', record)
                        
                        for child_row in attr_children:
                            attr_category_item.appendRow(child_row)
                        
                        # Create properly initialized sibling items for the category row
                        sibling_items = [qt.QStandardItem("") for _ in range(5)]
                        for sibling_item in sibling_items:
                            # Inherit parent's filter data for Qt-native filtering
                            sibling_item.setData(record.created, ItemDataRole.NUMERIC_TIMESTAMP)
                            sibling_item.setData(record.processName, ItemDataRole.PROCESS_NAME)
                            sibling_item.setData(record.threadName, ItemDataRole.THREAD_NAME)
                            sibling_item.setData(record.name, ItemDataRole.LOGGER_NAME)
                            sibling_item.setData(record.levelno, ItemDataRole.LEVEL_NUMBER)
                            sibling_item.setData(self._get_level_cipher(record.levelno), ItemDataRole.LEVEL_CIPHER)
                            sibling_item.setData(record.getMessage(), ItemDataRole.MESSAGE_TEXT)
                        
                        children.append([attr_category_item] + sibling_items)
        
        return children
    
    def _create_category_item(self, name, category_type, parent_record):
        """Create a category item for grouping related log attributes."""
        category_item = qt.QStandardItem(name)
        category_item.setData({
            'type': category_type,
            'name': name,
            'parent_record': parent_record
        }, ItemDataRole.PYTHON_DATA)
        
        # Inherit parent's filter data for Qt-native filtering
        category_item.setData(parent_record.created, ItemDataRole.NUMERIC_TIMESTAMP)
        category_item.setData(parent_record.processName, ItemDataRole.PROCESS_NAME)
        category_item.setData(parent_record.threadName, ItemDataRole.THREAD_NAME)
        category_item.setData(parent_record.name, ItemDataRole.LOGGER_NAME)
        category_item.setData(parent_record.levelno, ItemDataRole.LEVEL_NUMBER)
        category_item.setData(self._get_level_cipher(parent_record.levelno), ItemDataRole.LEVEL_CIPHER)
        category_item.setData(parent_record.getMessage(), ItemDataRole.MESSAGE_TEXT)
        
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
                        frame_row = self._create_child_row("", line.strip(), {
                            'type': 'traceback_frame',
                            'text': line.strip(),
                            'frame_number': j + 1,
                            'parent_record': record
                        }, record)
                        children.append(frame_row)
                
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
                frame_row = self._create_child_row("", line.strip(), {
                    'type': 'traceback_frame',
                    'text': line.strip(),
                    'frame_number': i + 1,
                    'parent_record': parent_record
                }, parent_record)
                children.append(frame_row)
                
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
    
    def _create_child_row(self, label, message, data_dict, parent_record):
        """Create a standardized child row for exception details."""
        # For child rows, put all content in the first column since it will span
        # Create items for each column
        timestamp_item = qt.QStandardItem(message)  # Put the content in first column
        source_item = qt.QStandardItem("")     # Empty source for child
        logger_item = qt.QStandardItem("")     # Empty logger for child  
        level_item = qt.QStandardItem("")      # Empty level for child
        message_item = qt.QStandardItem("")   # Empty since content is in first column
        task_item = qt.QStandardItem("")      # Empty task for child
        
        # Store data in the first item (timestamp column)
        timestamp_item.setData(data_dict, ItemDataRole.PYTHON_DATA)
        
        # INHERIT PARENT'S FILTER DATA so Qt native filtering includes children
        # This allows children to pass the same filters as their parents
        # Set the same data on ALL items so filtering works regardless of which column is checked
        for item in [timestamp_item, source_item, logger_item, level_item, message_item, task_item]:
            item.setData(parent_record.created, ItemDataRole.NUMERIC_TIMESTAMP)
            item.setData(parent_record.processName, ItemDataRole.PROCESS_NAME)
            item.setData(parent_record.threadName, ItemDataRole.THREAD_NAME)
            item.setData(parent_record.name, ItemDataRole.LOGGER_NAME)
            item.setData(parent_record.levelno, ItemDataRole.LEVEL_NUMBER)
            item.setData(self._get_level_cipher(parent_record.levelno), ItemDataRole.LEVEL_CIPHER)
            item.setData(parent_record.getMessage(), ItemDataRole.MESSAGE_TEXT)  # Parent's message for filtering
        
        # Set colors to differentiate from main log entries
        timestamp_item.setForeground(qt.QColor("#444444"))  # Dark gray for child text
        
        # Make exception/stack items not selectable
        for item in [timestamp_item, source_item, logger_item, level_item, message_item, task_item]:
            item.setFlags(qt.Qt.ItemIsEnabled)  # Remove ItemIsSelectable flag
        
        # Apply styling to the first column item (where content is now)
        # Apply monospace font for code-like content
        if data_dict.get('type') in ['traceback_frame', 'stack_frame']:
            # These contain code lines and file paths - use monospace
            monospace_font = qt.QFont("Consolas, Monaco, 'Courier New', monospace")
            monospace_font.setStyleHint(qt.QFont.TypeWriter)
            timestamp_item.setFont(monospace_font)
        
        # Make exception messages bold
        if data_dict.get('type') == 'exception':
            bold_font = timestamp_item.font()
            bold_font.setBold(True)
            timestamp_item.setFont(bold_font)
        
        # Style chain separators
        if data_dict.get('type') == 'chain_separator':
            italic_font = timestamp_item.font()
            italic_font.setItalic(True)
            timestamp_item.setFont(italic_font)
            timestamp_item.setForeground(qt.QColor("#888888"))  # Lighter gray for separators
        
        # Style stack separators
        if data_dict.get('type') == 'stack_separator':
            italic_font = timestamp_item.font()
            italic_font.setItalic(True)
            timestamp_item.setFont(italic_font)
            timestamp_item.setForeground(qt.QColor("#888888"))  # Lighter gray for separators
        
        return [timestamp_item, source_item, logger_item, level_item, message_item, task_item]
    
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
        timestamp_item = qt.QStandardItem("")
        source_item = qt.QStandardItem("")
        logger_item = qt.QStandardItem("")
        level_item = qt.QStandardItem("⏳ Loading...")
        message_item = qt.QStandardItem("Click to expand log details")
        
        # Mark as loading placeholder
        timestamp_item.setData(True, ItemDataRole.IS_LOADING_PLACEHOLDER)
        
        # Style the placeholder
        level_item.setForeground(qt.QColor("#888888"))
        message_item.setForeground(qt.QColor("#888888"))
        message_item.setFont(qt.QFont("Arial", 8, qt.QFont.StyleItalic))
        
        return [timestamp_item, source_item, logger_item, level_item, message_item]
    
    def has_loading_placeholder(self, parent_item):
        """Check if item has a loading placeholder child."""
        if parent_item.rowCount() == 1:
            child = parent_item.child(0, 0)  # Check timestamp column
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


class LogViewer(qt.QWidget):
    """QWidget for displaying and filtering log messages."""
    
    # Signal emitted when user clicks on a stack frame
    stack_frame_clicked = qt.Signal(str, int)  # (filename, line_number)
    
    def __init__(self, logger='', initial_filters=('level: info',), parent=None):
        qt.QWidget.__init__(self, parent=parent)
        
        # Unique ID counter for log entries
        self._next_log_id = 0
        
        # Track filter changes for expansion state preservation
        self._last_filter_strings = []

        # Set up handler to send log records to this widget by signal
        self.handler = QtLogHandler()
        self.handler.new_record.connect(self.new_record)
        if isinstance(logger, str):
            logger = logging.getLogger(logger)
        logger.addHandler(self.handler)
        
        # Set up GUI
        self.layout = qt.QGridLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # Add filter input widget
        self.filter_input_widget = FilterInputWidget()
        self.filter_input_widget.filters_changed.connect(self.apply_filters)
        self.layout.addWidget(self.filter_input_widget, 0, 0)

        self.model = LogModel()
        self.model.setHorizontalHeaderLabels(['Timestamp', 'Source', 'Logger', 'Level', 'Message', 'Task'])
        
        # Create custom proxy model for advanced filtering
        if USE_CHAINED_FILTERING:
            self.proxy_model = LogFilterProxyModel(self.model)
            tree_model = self.proxy_model.final_model
        else:
            self.proxy_model = LogFilterProxyModel()
            self.proxy_model.setSourceModel(self.model)
            tree_model = self.proxy_model
        
        self.tree = qt.QTreeView()
        self.tree.setModel(tree_model)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)  # Make non-editable
        
        # Set up custom header with context menu
        self.header = self.tree.header()
        self.header.setContextMenuPolicy(qt.Qt.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._show_header_context_menu)
        
        # Hide Task column by default
        self.tree.setColumnHidden(5, True)
        
        # Create custom delegate for efficient highlighting (will be set on models)
        self.highlight_delegate = HighlightDelegate(self)
        
        # Set delegate on initial model
        self.tree.setItemDelegate(self.highlight_delegate)
        
        self.tree.setSortingEnabled(True)
        # Ensure chronological sorting from the start
        self._ensure_chronological_sorting()
        
        # Set up selection handling for highlighting
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        
        # Handle tree expansion to replace loading placeholders
        self.tree.expanded.connect(self._on_item_expanded)
        
        self.layout.addWidget(self.tree, 1, 0)
        self.resize(1200, 600)
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 200)
        self.tree.setColumnWidth(2, 100)
        
        # Apply initial filters if provided
        if initial_filters:
            # Add initial filters to the UI
            for filter_expr in initial_filters:
                self.filter_input_widget.filter_input.setText(filter_expr)
                self.filter_input_widget.add_filter()
            
            # Apply the filters
            self.apply_filters(list(initial_filters))

    def new_record(self, rec):
        # Create a new row for the log record
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.created)) + f'{rec.created % 1.0:.3f}'.lstrip('0')
        source = f"{rec.processName}/{rec.threadName}"
        logger_name = rec.name
        level = f"{rec.levelno} - {rec.levelname}"
        message = rec.getMessage()
        
        # Create items for each column
        timestamp_item = qt.QStandardItem(timestamp)
        source_item = qt.QStandardItem(source)
        logger_item = qt.QStandardItem(logger_name)
        level_item = qt.QStandardItem(level)
        message_item = qt.QStandardItem(message)
        task_item = qt.QStandardItem(getattr(rec, 'taskName', ''))
        
        # Set colors based on log level
        level_color = level_colors.get(rec.levelno, "#000000")
        source_color = thread_color(source)
        source_item.setForeground(qt.QColor(source_color))
        level_item.setForeground(qt.QColor(level_color))
        message_item.setForeground(qt.QColor(level_color))
        
        # Assign unique ID to this log entry
        log_id = self._next_log_id
        self._next_log_id += 1
        
        # Store data using named constants
        timestamp_item.setData(rec, ItemDataRole.PYTHON_DATA)  # Store complete log record
        timestamp_item.setData(rec.created, ItemDataRole.NUMERIC_TIMESTAMP)  # Store numeric timestamp
        timestamp_item.setData(log_id, ItemDataRole.LOG_ID)  # Store unique log ID
        source_item.setData(rec.processName, ItemDataRole.PROCESS_NAME)  # Store process name
        source_item.setData(rec.threadName, ItemDataRole.THREAD_NAME)  # Store thread name
        logger_item.setData(rec.name, ItemDataRole.LOGGER_NAME)  # Store logger name
        level_item.setData(rec.levelno, ItemDataRole.LEVEL_NUMBER)  # Store numeric level
        level_item.setData(level_to_cipher(rec.levelno), ItemDataRole.LEVEL_CIPHER)  # Store level cipher
        message_item.setData(rec.getMessage(), ItemDataRole.MESSAGE_TEXT)  # Store message text
        
        # Add items to the model
        self.model.appendRow([timestamp_item, source_item, logger_item, level_item, message_item, task_item])
        
        # Check if this record has any expandable information for lazy loading
        has_expandable_info = (
            (hasattr(rec, 'exc_info') and rec.exc_info and rec.exc_info != (None, None, None)) or
            (hasattr(rec, 'exc_text') and rec.exc_text) or
            (hasattr(rec, 'stack_info') and rec.stack_info) or
            self._has_extra_attributes(rec)
        )
        
        if has_expandable_info:
            # Add loading placeholder for lazy expansion
            self.model.add_loading_placeholder(timestamp_item, rec)
        
        # Ensure sorting is maintained when adding new data
        self._ensure_chronological_sorting()
    
    def _has_extra_attributes(self, record):
        """Check if record has extra attributes beyond standard LogRecord fields."""
        if not hasattr(record, '__dict__'):
            return False
            
        standard_attrs = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
            'module', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
            'thread', 'threadName', 'processName', 'process', 'getMessage',
            'exc_info', 'exc_text', 'stack_info', 'tags', 'taskName'
        }
        
        for attr_name in record.__dict__.keys():
            if attr_name not in standard_attrs and not attr_name.startswith('_'):
                return True
        return False
    
    def _set_child_spans(self, parent_item):
        """Set column spans for all children of a parent item to span full width."""
        # Find the LogViewer instance to access the tree view
        viewer = None
        current = parent_item
        while current:
            if hasattr(current, 'model') and hasattr(current.model(), 'parent'):
                model_parent = current.model().parent()
                if isinstance(model_parent, LogViewer):
                    viewer = model_parent
                    break
            # Try to find the model and work backwards
            if hasattr(current, 'model'):
                model = current.model()
                # Look for LogViewer in the model's parent chain
                test_obj = model
                while test_obj:
                    if isinstance(test_obj, LogViewer):
                        viewer = test_obj
                        break
                    test_obj = getattr(test_obj, 'parent', lambda: None)() if hasattr(test_obj, 'parent') else None
                    if test_obj is None:
                        break
            break
        
        # If we can't find the viewer through the model, we'll need to set spans later
        # This will be called from the LogViewer class
        pass
    
    def _set_child_spans_for_item(self, parent_index, parent_item):
        """Set column spans for all children of the expanded item."""
        current_model = self.tree.model()
        
        # Get the number of columns
        column_count = current_model.columnCount()
        if column_count <= 1:
            return
        
        # Set spans for all children
        child_count = current_model.rowCount(parent_index)
        for child_row in range(child_count):
            child_index = current_model.index(child_row, 0, parent_index)
            # Make the first column span all columns
            self.tree.setFirstColumnSpanned(child_row, parent_index, True)
            
            # Also set spans for any grandchildren recursively
            if current_model.rowCount(child_index) > 0:
                self._set_child_spans_for_item(child_index, None)

    def apply_filters(self, filter_strings):
        """Apply the given filter strings to the proxy model."""
        old_final_model = self.proxy_model.final_model if USE_CHAINED_FILTERING else None
        
        # Save expansion state before changing filters
        expanded_paths = self._save_expansion_state()
        # print(f"Saved expansion state: {expanded_paths}")
        
        self.proxy_model.set_filters(filter_strings)
        
        # Update tree view model if using chained filtering and chain changed
        if USE_CHAINED_FILTERING:
            new_final_model = self.proxy_model.final_model
            if self.tree.model() != new_final_model:
                # Save current selection ID before changing model
                selected_log_id = self._get_selected_item_data()
                
                # Clear selection and highlighting before changing model
                self.tree.selectionModel().clear()
                self.highlight_delegate.clear_highlight()
                
                self.tree.setModel(new_final_model)
                
                # Reapply delegate to new model
                self.tree.setItemDelegate(self.highlight_delegate)
                
                # Reconnect selection handler since model changed
                self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
                
                # Always ensure chronological sorting
                self._ensure_chronological_sorting()
                
                # Restore selection if possible
                if selected_log_id is not None:
                    self._restore_selection(selected_log_id)
                
                # Restore expansion state
                self._restore_expansion_state(expanded_paths)
        
        # Always restore expansion state after any filter change
        # (in case we're not using chained filtering or model didn't change)
        if filter_strings != self._last_filter_strings:
            # print(f"Restoring expansion state: {expanded_log_ids}")
            self._restore_expansion_state(expanded_paths)
        
        # Remember the current filter strings
        self._last_filter_strings = filter_strings[:]
        
    def _ensure_chronological_sorting(self):
        """Ensure the tree view is sorted chronologically by timestamp."""
        current_model = self.tree.model()
        
        # Set sort role to use numeric timestamp from ItemDataRole.NUMERIC_TIMESTAMP
        if hasattr(current_model, 'setSortRole'):
            current_model.setSortRole(ItemDataRole.NUMERIC_TIMESTAMP)
        
        # Apply sorting
        if hasattr(current_model, 'sort'):
            current_model.sort(0, qt.Qt.AscendingOrder)
        
        # Also tell the tree view about the sorting
        self.tree.sortByColumn(0, qt.Qt.AscendingOrder)
    
    def _show_header_context_menu(self, position):
        """Show context menu for column visibility when right-clicking on header."""
        menu = qt.QMenu(self)
        
        # Get column headers
        headers = ['Timestamp', 'Source', 'Logger', 'Level', 'Message', 'Task']
        
        for i, header_text in enumerate(headers):
            action = qt.QAction(header_text, self)
            action.setCheckable(True)
            action.setChecked(not self.tree.isColumnHidden(i))
            action.triggered.connect(lambda checked, col=i: self._toggle_column_visibility(col, checked))
            menu.addAction(action)
        
        menu.exec_(self.header.mapToGlobal(position))
    
    def _toggle_column_visibility(self, column, visible):
        """Toggle visibility of a column."""
        self.tree.setColumnHidden(column, not visible)
    
    def _on_selection_changed(self, selected, deselected):
        """Handle selection changes to highlight related entries."""
        if not selected.indexes():
            # Clear highlighting when nothing is selected
            self.highlight_delegate.clear_highlight()
            self.tree.viewport().update()  # Trigger repaint
            return
        
        # Get the selected row data directly from the current model
        index = selected.indexes()[0]  # Use first selected index
        model = self.tree.model()
        
        # Check if this is a child item (has a parent)
        parent_index = index.parent()
        if parent_index.isValid():
            # This is a child item - use parent's highlighting data
            source_data = model.data(model.index(parent_index.row(), 1), qt.Qt.DisplayRole)
            logger_data = model.data(model.index(parent_index.row(), 2), qt.Qt.DisplayRole)
        else:
            # This is a top-level item - use its own data
            source_data = model.data(model.index(index.row(), 1), qt.Qt.DisplayRole)
            logger_data = model.data(model.index(index.row(), 2), qt.Qt.DisplayRole)
        
        if not source_data or not logger_data:
            self.highlight_delegate.clear_highlight()
            self.tree.viewport().update()
            return
            
        selected_source = source_data
        selected_logger = logger_data
        
        # Set highlighting criteria in the delegate
        self.highlight_delegate.set_highlight_criteria(selected_source, selected_logger)
        
        # Trigger a repaint of the entire tree
        self.tree.viewport().update()
    
    def _on_item_expanded(self, index):
        """Handle tree item expansion to replace loading placeholders and set spans."""
        # Get the item from the current model (could be proxy)
        current_model = self.tree.model()
        
        # Map index back to source model if using proxy
        source_index = index
        if hasattr(current_model, 'mapToSource'):
            source_index = current_model.mapToSource(index)
        
        # Get the actual item from our LogModel
        item = self.model.itemFromIndex(source_index)
        if item and self.model.has_loading_placeholder(item):
            # Replace placeholder with real content
            self.model.replace_placeholder_with_content(item)
        
        # Always set column spans for children when an item is expanded
        # This ensures spans are set even for items that don't have placeholders
        self._set_child_spans_for_item(index, item)
    
    def _get_selected_item_data(self):
        """Get unique ID from currently selected item for selection preservation."""
        selection = self.tree.selectionModel().selectedIndexes()
        if not selection:
            return None
            
        # Get the first selected index
        index = selection[0]
        model = self.tree.model()
        row = index.row()
        
        # Get the unique log ID from the timestamp column
        try:
            log_id = model.data(model.index(row, 0), ItemDataRole.LOG_ID)
            return log_id
        except:
            return None
    
    def _restore_selection(self, selected_log_id):
        """Restore selection to an item with the given unique ID."""
        if selected_log_id is None:
            return
            
        model = self.tree.model()
        
        # Search through the model to find the row with matching log ID
        for row in range(model.rowCount()):
            try:
                log_id = model.data(model.index(row, 0), ItemDataRole.LOG_ID)
                if log_id == selected_log_id:
                    # Found matching row, select it
                    index = model.index(row, 0)
                    self.tree.selectionModel().select(index, qt.QItemSelectionModel.Select | qt.QItemSelectionModel.Rows)
                    self.tree.scrollTo(index)  # Scroll to show the selected item
                    break
            except:
                continue
    
    def _save_expansion_state(self):
        """Save expansion state using LOG_IDs for top-level items and relative paths for children."""
        expanded_items = {}
        current_model = self.tree.model()
        
        if current_model is None:
            return expanded_items
        
        def save_recursive(parent_index, parent_log_id, relative_path):
            for row in range(current_model.rowCount(parent_index)):
                index = current_model.index(row, 0, parent_index)
                current_relative_path = relative_path + [row]
                
                if self.tree.isExpanded(index):
                    if parent_log_id is None:
                        # This is a top-level item, use its LOG_ID
                        log_id = current_model.data(index, ItemDataRole.LOG_ID)
                        if log_id is not None:
                            expanded_items[log_id] = []
                            # Recursively save children under this LOG_ID
                            save_recursive(index, log_id, [])
                    else:
                        # This is a child item, save relative path from parent LOG_ID
                        if parent_log_id not in expanded_items:
                            expanded_items[parent_log_id] = []
                        expanded_items[parent_log_id].append(tuple(current_relative_path))
                        # Recursively save grandchildren
                        save_recursive(index, parent_log_id, current_relative_path)
        
        # Start with top-level items
        save_recursive(current_model.index(-1, -1), None, [])  # Invalid index = root
        
        return expanded_items
    
    def _restore_expansion_state(self, expanded_items):
        """Restore expansion state using LOG_IDs for top-level items and relative paths for children."""
        if not expanded_items:
            return
            
        current_model = self.tree.model()
        if current_model is None:
            return
        
        # First, find all top-level items by LOG_ID and expand them
        log_id_to_index = {}
        for row in range(current_model.rowCount()):
            index = current_model.index(row, 0)
            log_id = current_model.data(index, ItemDataRole.LOG_ID)
            if log_id is not None:
                log_id_to_index[log_id] = index
        
        # Restore expansion for each LOG_ID
        for log_id, child_paths in expanded_items.items():
            parent_index = log_id_to_index.get(log_id)
            if parent_index is None:
                continue  # LOG_ID not found in current model
            
            # Expand the top-level item itself if it has children
            if current_model.rowCount(parent_index) > 0:
                self.tree.expand(parent_index)
                self._set_child_spans_for_item(parent_index, None)
            
            # Restore child expansions using relative paths
            for child_path in child_paths:
                # Navigate from parent using relative path
                current_index = parent_index
                
                for row_num in child_path:
                    if current_index.isValid() and row_num < current_model.rowCount(current_index):
                        current_index = current_model.index(row_num, 0, current_index)
                    else:
                        current_index = qt.QModelIndex()  # Invalid
                        break
                
                # Expand the child if valid (even if it has no children - Qt allows this)
                if current_index.isValid():
                    self.tree.expand(current_index)
                    # Only set spans if it actually has children
                    if current_model.rowCount(current_index) > 0:
                        self._set_child_spans_for_item(current_index, None)
        
        # Also set column spans for all child items (fixes span loss after filtering)
        def set_spans_recursive(parent_index):
            for row in range(current_model.rowCount(parent_index)):
                index = current_model.index(row, 0, parent_index)
                
                # Set column spans for all child items
                if parent_index.isValid():  # Only for child items, not top-level
                    self.tree.setFirstColumnSpanned(row, parent_index, True)
                
                # Recursively set spans for grandchildren
                if current_model.rowCount(index) > 0:
                    set_spans_recursive(index)
        
        # Set spans for all items
        set_spans_recursive(current_model.index(-1, -1))  # Invalid index = root


class QtLogHandlerSignals(qt.QObject):
    """QObject subclass that provides the new_record signal for QtLogHandler."""
    new_record = qt.Signal(object)


class QtLogHandler(logging.Handler):
    """Log handler that emits a Qt signal for each record."""
    
    def __init__(self):
        logging.Handler.__init__(self)
        self._signals = QtLogHandlerSignals()
        self.new_record = self._signals.new_record
        
    def handle(self, record):
        self.new_record.emit(record)