# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `RPCClient` is now shared by every thread in a process instead of created per thread. A dedicated I/O thread owns the zmq socket for the client's whole life; callers on any thread hand it a request and wait on the `Future`, so a connection costs one socket and one thread per remote server rather than one of each per calling thread per server. The per-thread registry and the three cleanup paths that closed a thread's sockets when it stopped (thread-local sentinel, `Thread` GC finalizer, `__del__`) are gone, along with the leak they existed to bound: a client now lives until it is closed or the process exits. `RPCClient.clients_by_thread` is replaced by `RPCClient.clients_by_address`, keyed by `(address, local_server)` — a process that proxies through more than one local server still gets one connection per server, because the local server decides which address the remote end calls back on
- A client's zmq IDENTITY is now `host.process.connN:address` rather than `host.process.thread:address`. Connections are no longer per thread, and a ROUTER refuses a second peer claiming an identity it already has
- `local_server="lazy"` is now read by the client's I/O thread while a call is outstanding, rather than by the calling thread inside `process_until_future`. The contract is unchanged — a lazy server answers requests that arise from the calls you make and stays silent otherwise — but the handler runs on the I/O thread, not on the thread that made the call
- `RPCServer` proxy bookkeeping (`get_proxy`, object and ref ids, `_proxy_refs`) is now guarded by a lock. Proxies are minted on whichever thread serializes a request, so one local server shared by every caller in a process is now mutated concurrently
- `RPCServer.client_should_handle_requests()` is removed; it existed for the per-thread poller selection that no longer happens. `RPCServer.running_in_this_thread()` covers the remaining case

### Fixed
- Several threads calling `RPCClient.get_client()` for the same unbuilt connection at once no longer each open their own, and no longer receive one that has not finished connecting
- `RPCServer.close()` now stops the server thread it started, instead of leaking it and its socket. The thread sits blocked in `recv_multipart` and `run_forever` re-reads the closed flag only once a message arrives, so a close that set the flag and returned left the thread parked for the life of the process; `close()` now asks the server thread to close by sending it a close request, so the socket is released from the thread that owns it. A caller that opens one server per worker thread (`RPCClient(local_server="threaded")`, whose clients are keyed by thread) accumulated one such thread per worker. There is no fallback for a close request that cannot be delivered: closing the socket from the caller instead would strand the server thread on a socket that no longer exists, so the failure is logged and the server reports itself still `running()`
- `RPCServer.close()` on a server with no reader thread now closes its socket too, which it previously skipped; the disconnect notifications a threaded server sends on close are now written by the thread that owns the socket rather than by the caller. Because the server thread reads the close itself, it is handled between requests: a call already running returns its result instead of losing it to the disconnect the closing thread used to send out from under it. `close()` therefore blocks until that call finishes, for up to its *timeout*, and is idempotent

## [2.4.0]

### Added
- The log record for a failed request now names the action, the calling peer and the exception type and message, so a failure can be identified without reading the traceback

### Changed
- Windows Job Objects now set `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK`, so a daemon grandchild is no longer killed when its parent dies. The job therefore covers only the child process it was created for: processes that child spawns by other means are not cleaned up by it, and with `conda_env` or `shell=True` the job tracks the wrapper process while the teleprox process falls back to polling

### Fixed
- `start_process(exit_on_parent_death=True)` sets up its Windows Job Object again. `CreateJobObject(None, None)` raises `TypeError` on pywin32 >= 311, and the exception was swallowed, leaving every child on the slower parent-death polling fallback
- A peer whose zmq identity is not valid UTF-8 no longer kills the `RPCServer` thread. The identity was decoded eagerly as a logging argument, so a `UnicodeDecodeError` escaped the request handler -- and its fallback -- leaving the process alive but deaf on teleprox
- `LogViewer` now inserts each arriving record at its chronological position instead of re-sorting the whole model per record. The re-sort made ingest quadratic (cost per record grew with the record count), and because records are delivered inline on the Qt thread, a process logging at volume could reach the point where it spent longer sorting than the interval between records and stopped servicing its event loop entirely — for a `QtRPCServer`, that means it stops answering RPC while still holding an open port
- `LogViewer` autoscroll is now coalesced onto a single-shot timer instead of calling `scrollToBottom()` for every inserted row. `scrollToBottom` walks the view layout, so per-row calls were a second quadratic term in the same path; a burst of records now costs one scroll instead of one per record
- Records arriving in a `LogViewer` whose rows are sorted some other way — a header click, with no filters, so the view is attached to the source model and no proxy places arriving rows — no longer append in an order that contradicts the view's own sort indicator. The view's sort is re-applied once per trip through the event loop, not once per record
- A record arriving while `LogViewer.set_records()` is loading a batch no longer leaves the model claiming its rows are in timestamp order when they are not. `set_records` yields to the event loop as it loads, so a live record can land between batch rows; a later record would then be placed by a bisect against rows that only looked sorted
- `LogViewer.set_records()` no longer scrolls once per twenty records over a growing view while loading a batch, and does not re-sort during the load at all; both happen once, after the batch

## [2.3.1]

### Fixed
- `QtLogHandler.handle()` now applies registered filters before emitting a record, matching `logging.Handler.handle()` (and `LogSender.handle()`, fixed in 2.2.1). Filters added to the handler were silently ignored, so records a filter should have dropped reached the viewer anyway, and records a filter enriched arrived without the attributes the viewer reads

## [2.3.0]

### Added
- `LogViewer._build_row_context_menu(index)` is now a documented extension point: subclasses can override it, call `super()`, and append their own actions to the row context menu instead of reimplementing `_show_row_context_menu` wholesale

### Fixed
- `RPCServer` now refuses to start a second `run_forever` thread on one socket (via `_run_in_thread()` or a direct `run_forever()` call), raising `RuntimeError` instead of silently corrupting the socket's multipart framing; two threads reading one zmq socket is unsupported (issue #40)
- `run_forever` now logs and skips a malformed/partial RPC message instead of letting the `ValueError` escape and kill the server thread, which previously left the process alive but deaf on teleprox (issue #40)

## [2.2.2]

### Fixed
- RPC client sockets are now closed when the owning thread stops, preventing socket leaks from short-lived threads
- Socket teardown is no longer forced at interpreter exit, avoiding errors during shutdown
- `LogSender.close()` now joins the sender thread before closing the socket, ensuring all queued log records are delivered when a process exits quickly
- A failed remote call's "Exception while processing request" error log now re-establishes the call's context hook while logging, so the failure record carries the same context (e.g. a tracing context) a successful call would; previously the hook's context window had already closed

## [2.2.1]

### Added
- Added process-level call hooks: `set_call_opts_provider()` on `RPCClient` and `set_call_context_hook()` on `RPCServer`, enabling metadata propagation (e.g. tracing context) across process boundaries without modifying call sites
- Non-daemon child processes now automatically exit if their parent process disappears
- Log viewer now shows a horizontal scrollbar and expands the message column to content width, preventing long messages from being elided

### Fixed
- `LogSender.handle()` now applies registered filters before queuing log records
- Connections are now properly closed when the owning thread or client dies
- Fixed at-exit segfault caused by emitting a signal on a deleted Qt object
- Fixed Windows 11 process spawning by setting the required detached process flag
- Fixed netstat calls on Windows from opening a visible console window
- Disconnect client when `process.kill()` is called
- Fixed log viewer child row text to use `ROW_DETAILS` data role for reliable column access
- `server_disconnected` renamed from private `_server_disconnected` to public API

### Changed
- `server_disconnected` is now a public attribute on `RPCClient`

## [2.2.0]

### Added
- Added PyQt6 support alongside existing PyQt5 and PySide2 support
- Added PySide6 support
- Added CI test matrix entries for PyQt6 and no-Qt configurations
- Qt submodules (e.g. `QtCore`, `QtWidgets`) are now accessible by name on the shim

### Fixed
- Updated Qt shim to handle lazily-loaded Qt libraries in newer versions
- Fixed logging example for Qt6 compatibility
- Suppressed spurious proxy deletion errors on shutdown

## [2.1.3]

### Added
- Added `set_source_model()` method to ChainedLogFilterManager to enable swapping source models while preserving filter chain
- Added option to set log level for remote log sending independently from root logger

### Fixed
- Fixed bootstrap configuration handling

## [2.1.2]

### Fixed
- Fixed package distribution to include all subpackages

## [2.1.1]

### Fixed
- Fixed lockup in `test_context_menu_copy` test caused by incorrect mock setup for `selectedIndex` attribute

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