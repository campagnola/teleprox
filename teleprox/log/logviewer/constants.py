# Constants and enums for log viewer data roles and other shared values
# Centralized location for UserRole slot assignments and configuration constants

from teleprox import qt

            
# Any log record attributes not in this set should be displayed as a child item 
attrs_not_shown_as_children = {
    'name', 'msg', 'message', 'args', 'levelname', 'levelno', 'pathname', 'filename',
    'module', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
    'thread', 'threadName', 'processName', 'hostName', 'process', 'getMessage',
    'tags', 'taskName',
}
# attributes we can show as children, or ignore if their value is None
ignorable_child_attrs = {'exc_info', 'exc_text', 'stack_info'}


class ItemDataRole:
    """Constants for QStandardItem UserRole data slots."""
    # Primary data slot - references to Python objects
    LOG_RECORD = qt.Qt.UserRole             # LogRecord object, or custom data dict
    ROW_DETAILS = qt.Qt.UserRole + 100      # dict of extra attributes for child items
    
    # Qt-specific data for sorting/filtering/display
    NUMERIC_TIMESTAMP = qt.Qt.UserRole + 1  # float timestamp for sorting
    PROCESS_NAME = qt.Qt.UserRole + 2       # string process name
    THREAD_NAME = qt.Qt.UserRole + 3        # string thread name  
    LOGGER_NAME = qt.Qt.UserRole + 4        # string logger name
    LEVEL_NUMBER = qt.Qt.UserRole + 5       # int level number for sorting
    LEVEL_CIPHER = qt.Qt.UserRole + 6       # string level cipher for filtering
    MESSAGE_TEXT = qt.Qt.UserRole + 7       # string message for filtering
    LOG_ID = qt.Qt.UserRole + 8             # unique int ID for selection tracking
    HOST_NAME = qt.Qt.UserRole + 9          # string host name for filtering
    SOURCE_TEXT = qt.Qt.UserRole + 10       # string source (process/thread) for filtering
    TASK_NAME = qt.Qt.UserRole + 11         # string task name for filtering


class LogColumns:
    """Constants for log viewer column indices."""
    TIMESTAMP = 0
    HOST = 1        # Host name
    PROCESS = 2     # Process name
    THREAD = 3      # Thread name
    SOURCE = 4      # Process/Thread info
    LOGGER = 5      # Logger name
    LEVEL = 6       # Log level
    MESSAGE = 7     # Log message
    TASK = 8        # Task name
    
    # Column titles for header labels
    TITLES = [
        'Timestamp',    # TIMESTAMP
        'Host',         # HOST
        'Process',      # PROCESS
        'Thread',       # THREAD
        'Source',       # SOURCE
        'Logger',       # LOGGER
        'Level',        # LEVEL
        'Message',      # MESSAGE
        'Task'          # TASK
    ]
    
    # Default column widths
    WIDTHS = [
        200,    # TIMESTAMP
        150,    # HOST
        150,    # PROCESS
        150,    # THREAD
        200,    # SOURCE
        100,    # LOGGER
        100,    # LEVEL
        400,    # MESSAGE
        100     # TASK
    ]