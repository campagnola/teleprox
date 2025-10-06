# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0]

### Added
- Added `LogViewer.set_records()` method for bulk log replacement
- Enhanced log viewer with disconnected operation capability
- Added copy functionality to context menu for log entries
- Improved text export functionality with all fields included
- Added custom LogViewer example with documentation links
- Enhanced exception handling for differently serialized exc_info
- Added rate limiting for UI responsiveness during high-volume logging

### Fixed
- Fixed log record references that had been lost during processing
- Fixed code line clicking functionality in log viewer traceback frames
- Improved exception handling for pre-stringed exc_info
- Enhanced copy functionality to work from any sub-item in log viewer
- Fixed recursion error in proxy object deletion

### Changed
- Applied selective black code formatting for consistency
- Enhanced data attribute handling using attrs instead of Qt data
- Moved text export functionality into dedicated export.py module
- Refactored export behavior out of main LogViewer class
- Code refactoring for improved clarity and simplicity

## [2.0.0]

### Added

#### Callback Support
- **Major Feature**: Added comprehensive callback support for bidirectional communication between client and server processes
- Callbacks can now be passed as arguments to remote method calls and executed on the originating process
- Support for threaded callback execution and proper error handling in callback chains
- Callback functions are transparently proxied across process boundaries

#### Enhanced Log Viewer
- **Log Viewer Overhaul**: Complete rewrite of the log viewer with modern Qt architecture
  - Switched from QTreeWidget to QTreeView with QStandardItemModel for better performance
  - Added dynamic sorting capabilities for all log columns
  - Implemented advanced filtering system with field-specific filters
  - Added search functionality with real-time filtering
  - New column layout including logger name, thread, and process information
  - Clickable code lines that jump to source locations
  - Enhanced exception display with full stack traces and exception chains
  - Auto-scrolling functionality for real-time log monitoring
  - Export functionality for saving filtered log data
  - Color-coded log levels and thread identification
  - Context menu with copy functionality

#### Process and Server Management
- Made `run_thread` and `read_and_process_one` methods public for better extensibility
- Enhanced process cleanup and error detection during bootstrap
- Improved process lookup error handling
- Better structured remote exception information

### Changed

#### API Changes
- **Breaking**: Made `server` and `local_server` private attributes to encourage proper API usage
- **Breaking**: Removed automatic client caching in `_client` attribute
- **Breaking**: Clients no longer start with a local server by default - users must explicitly choose server types
- Enhanced proxy options serialization for better cross-process compatibility
- Improved handling of lazy proxy timeout errors with better error messages

#### Code Quality and Style
- Selectively applied black code formatting (100-character line limit)
- Enhanced error handling with purposeful exceptions instead of assertions
- Improved numpy subclass detection to prevent unnecessary proxying
- Better log level management with milder default logging
- Enhanced docstring format using numpy style for initialization parameters

#### Testing Infrastructure
- Comprehensive test suite expansion with new test categories:
  - Callback functionality tests
  - Log viewer component tests
  - Process management tests
  - Serialization and proxy behavior tests
- Improved test isolation and cleanup procedures
- Enhanced Qt application fixture management
- Better test organization with shared utility code

### Fixed

#### Core Functionality
- **Critical**: Fixed numpy array serialization bug that caused issues with structured arrays
- Fixed infinite recursion issues in proxy deletion
- Resolved race conditions in multi-threaded socket listening
- Fixed proxy identity and caching issues for same objects across different contexts
- Improved garbage collection for proxy objects

#### Log System
- Fixed log viewer filtering bugs that could hide expansion handles
- Corrected thread and process name attribution in log records
- Fixed exception serialization issues in remote logging
- Resolved auto-scrolling behavior in log viewer
- Fixed search functionality edge cases

#### Process Management
- Better detection and handling of bootstrap errors
- Improved process cleanup to prevent stray processes after tests
- Fixed client shutdown race conditions
- Enhanced error detection during spawning

### Internal

#### Architecture Improvements
- Servers are no longer thread-global, improving isolation and resource management
- Enhanced client-server communication with better error propagation
- Improved proxy configuration system with better hash-based caching
- Better separation of concerns between different server types

#### Development Experience
- Added comprehensive CLAUDE.md documentation with development commands and architecture overview
- Enhanced debugging capabilities with better structured logging
- Improved development workflow with better test organization
- Enhanced code documentation and inline comments

---

*Note: This changelog covers changes since commit 45b3fea (March 26, 2025). Earlier version history is not included in this changelog.*