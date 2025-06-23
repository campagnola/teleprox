# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Testing
```bash
# IMPORTANT: Use conda environment for all testing
# Correct way to activate conda env in bash scripts:
source /home/luke/miniconda3/bin/activate teleprox

# Run all tests
pytest

# Run tests with logging enabled  
pytest --log=DEBUG

# Run specific test file
pytest teleprox/tests/test_basics.py

# Run single test
pytest teleprox/tests/test_basics.py::test_function_name

# Run log viewer tests specifically
pytest teleprox/log/logviewer/tests/

# Run single log viewer test file
pytest teleprox/log/logviewer/tests/test_level_filtering.py
```

### Installation and Development
```bash
# Install in development mode
pip install -e .

# Install with dependencies
pip install -e .[dev]  # if dev dependencies are defined
```

## Architecture Overview

Teleprox is a Python library for creating object proxies over TCP using ZeroMQ. The core architecture consists of:

### Core Components

- **RPCServer** (`server.py`): Handles incoming RPC requests and manages proxied objects
- **RPCClient** (`client.py`): Connects to RPCServer and sends RPC requests
- **ObjectProxy** (`proxy.py`): Transparent proxy objects that forward method calls and attribute access to remote objects
- **Process Management** (`process.py`): Utilities for spawning and managing remote processes with RPC servers

### Key Design Patterns

1. **Client-Server Architecture**: Each process can act as both client and server, enabling bidirectional communication
2. **Transparent Proxying**: Objects are accessed as if they were local, with automatic serialization/deserialization
3. **Async Support**: Methods can be called synchronously, asynchronously, or fire-and-forget using `_sync` parameter
4. **Qt Integration**: Special Qt server (`qt_server.py`) integrates with Qt event loops

### Communication Flow

1. `start_process()` spawns a new process with an RPCServer
2. Client connects via RPCClient to the server's ZMQ socket
3. Remote objects are accessed through ObjectProxy instances
4. Method calls are serialized (msgpack/pickle), sent over TCP, executed remotely, and results returned

### Logging System

The project includes a sophisticated logging system (`log/` directory):
- Remote processes can forward logs to a central log server
- Qt-based log viewer for real-time log monitoring
- Structured logging with process/thread identification

### Testing Infrastructure

- Comprehensive test suite in `teleprox/tests/`
- Custom pytest configuration with logging and process management
- Tests cover basic RPC, Qt integration, serialization, and failure modes
- Process cleanup ensures no stray processes after tests