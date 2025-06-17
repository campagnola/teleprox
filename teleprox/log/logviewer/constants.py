# ABOUTME: Constants and enums for log viewer data roles and other shared values
# ABOUTME: Centralized location for UserRole slot assignments and configuration constants

from teleprox import qt


class ItemDataRole:
    """Constants for QStandardItem UserRole data slots."""
    # Primary data slot - references to Python objects
    PYTHON_DATA = qt.Qt.UserRole           # LogRecord object, or custom data dict
    
    # Qt-specific data for sorting/filtering/display
    NUMERIC_TIMESTAMP = qt.Qt.UserRole + 1  # float timestamp for sorting
    PROCESS_NAME = qt.Qt.UserRole + 2       # string process name
    THREAD_NAME = qt.Qt.UserRole + 3        # string thread name  
    LOGGER_NAME = qt.Qt.UserRole + 4        # string logger name
    LEVEL_NUMBER = qt.Qt.UserRole + 5       # int level number for sorting
    LEVEL_CIPHER = qt.Qt.UserRole + 6       # string level cipher for filtering
    MESSAGE_TEXT = qt.Qt.UserRole + 7       # string message for filtering
    LOG_ID = qt.Qt.UserRole + 8             # unique int ID for selection tracking
    
    # Lazy loading state
    HAS_CHILDREN = qt.Qt.UserRole + 9       # bool - has unfetched exception data
    CHILDREN_FETCHED = qt.Qt.UserRole + 10  # bool - children already loaded
    IS_LOADING_PLACEHOLDER = qt.Qt.UserRole + 11  # bool - marks dummy "loading..." child