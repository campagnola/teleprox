"""
ABOUTME: Advanced logging example with daemon process, GUI controls, and reconnection capability
ABOUTME: Demonstrates interactive log generation and remote log collection in a GUI environment
"""
import atexit
import logging
import signal
import sys
import time

from PyQt5 import QtWidgets, QtCore

import teleprox
import teleprox.log
from teleprox.log.remote import LogServer
from teleprox.log.logviewer import LogViewer


def create_daemon_gui():
    """Function to be imported by daemon process to create its own GUI"""

    class DaemonGUI(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.message_count = 0
            self.setup_ui()

        def setup_ui(self):
            self.setWindowTitle("Daemon Process - Independent GUI")
            self.setGeometry(600, 100, 350, 250)

            layout = QtWidgets.QVBoxLayout()

            # Status info
            import os
            pid_label = QtWidgets.QLabel(f"Daemon PID: {os.getpid()}")
            layout.addWidget(pid_label)

            self.status_label = QtWidgets.QLabel("Daemon process is running independently")
            layout.addWidget(self.status_label)

            # Log generation controls
            self.log_btn = QtWidgets.QPushButton("Generate Log Message")
            self.log_btn.clicked.connect(self.generate_log)
            layout.addWidget(self.log_btn)

            self.auto_log_btn = QtWidgets.QPushButton("Start Auto-Logging (5s)")
            self.auto_log_btn.clicked.connect(self.toggle_auto_log)
            layout.addWidget(self.auto_log_btn)

            self.exception_btn = QtWidgets.QPushButton("Create Exception")
            self.exception_btn.clicked.connect(self.create_exception)
            layout.addWidget(self.exception_btn)

            self.message_count_label = QtWidgets.QLabel("Messages sent: 0")
            layout.addWidget(self.message_count_label)

            # Log level selector
            level_layout = QtWidgets.QHBoxLayout()
            level_layout.addWidget(QtWidgets.QLabel("Log Level:"))
            self.level_combo = QtWidgets.QComboBox()
            self.level_combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
            self.level_combo.setCurrentText('INFO')
            level_layout.addWidget(self.level_combo)
            layout.addLayout(level_layout)

            self.setLayout(layout)

            # Timer for auto-logging
            self.auto_timer = QtCore.QTimer()
            self.auto_timer.timeout.connect(self.generate_log)
            self.auto_logging = False

        def generate_log(self):
            self.message_count += 1
            level = self.level_combo.currentText()
            message = f"Daemon-generated message #{self.message_count} (level: {level})"

            # Log at the selected level
            if level == 'DEBUG':
                logging.debug(message)
            elif level == 'INFO':
                logging.info(message)
            elif level == 'WARNING':
                logging.warning(message)
            elif level == 'ERROR':
                logging.error(message)

            self.message_count_label.setText(f"Messages sent: {self.message_count}")

        def toggle_auto_log(self):
            if self.auto_logging:
                self.auto_timer.stop()
                self.auto_log_btn.setText("Start Auto-Logging (5s)")
                self.auto_logging = False
            else:
                self.auto_timer.start(5000)  # 5 seconds
                self.auto_log_btn.setText("Stop Auto-Logging")
                self.auto_logging = True

        def create_exception(self):
            """Create an exception and log it"""
            try:
                # Create a realistic exception scenario
                data = {"key": "value"}
                missing_key = data["nonexistent_key"]  # This will raise KeyError
            except KeyError as e:
                logging.exception("Exception occurred while accessing data")
                self.message_count += 1
                self.message_count_label.setText(f"Messages sent: {self.message_count}")

        def show(self):
            super().show()
            self.raise_()
            self.activateWindow()

    # Create and show the GUI
    gui = DaemonGUI()
    gui.show()
    return gui


class DaemonController(QtWidgets.QWidget):
    """Main controller window that manages the daemon process and log viewing"""

    def __init__(self):
        super().__init__()
        self.daemon = None
        self.daemon_address = None
        self.log_server = None
        self.setup_ui()
        self.setup_logging()
        self.setup_signal_handlers()

    def setup_ui(self):
        """Create the UI controls"""
        self.setWindowTitle("Advanced Logging Example - Controller")
        self.setGeometry(100, 100, 1000, 700)

        layout = QtWidgets.QVBoxLayout()

        # Daemon controls
        daemon_group = QtWidgets.QGroupBox("Daemon Process Control")
        daemon_layout = QtWidgets.QVBoxLayout()

        self.start_daemon_btn = QtWidgets.QPushButton("Start Daemon Process")
        self.start_daemon_btn.clicked.connect(self.start_daemon)
        daemon_layout.addWidget(self.start_daemon_btn)

        self.daemon_status_label = QtWidgets.QLabel("Status: No daemon running")
        daemon_layout.addWidget(self.daemon_status_label)

        self.reconnect_btn = QtWidgets.QPushButton("Reconnect to Daemon")
        self.reconnect_btn.clicked.connect(self.reconnect_daemon)
        self.reconnect_btn.setEnabled(False)
        daemon_layout.addWidget(self.reconnect_btn)

        daemon_group.setLayout(daemon_layout)
        layout.addWidget(daemon_group)

        # Test connection button
        self.test_connection_btn = QtWidgets.QPushButton("Test Connection to Daemon")
        self.test_connection_btn.clicked.connect(self.test_connection)
        self.test_connection_btn.setEnabled(False)
        layout.addWidget(self.test_connection_btn)

        # Embedded log viewer
        log_group = QtWidgets.QGroupBox("Log Viewer")
        log_layout = QtWidgets.QVBoxLayout()

        # Log viewer controls
        viewer_controls = QtWidgets.QHBoxLayout()
        
        self.clear_logs_btn = QtWidgets.QPushButton("Clear Logs")
        self.clear_logs_btn.clicked.connect(self.clear_logs)
        viewer_controls.addWidget(self.clear_logs_btn)
        
        self.load_sample_logs_btn = QtWidgets.QPushButton("Load Sample Historical Logs")
        self.load_sample_logs_btn.clicked.connect(self.load_sample_historical_logs)
        viewer_controls.addWidget(self.load_sample_logs_btn)
        
        viewer_controls.addStretch()  # Push buttons to the left
        log_layout.addLayout(viewer_controls)

        self.log_viewer = LogViewer()
        log_layout.addWidget(self.log_viewer)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        self.setLayout(layout)

    def setup_logging(self):
        """Set up logging for this process"""
        teleprox.log.basic_config(log_level='DEBUG', exceptions=False)
        self.log("Controller logging set up")

    def setup_signal_handlers(self):
        """Set up signal handlers for proper daemon cleanup"""

        def cleanup_and_exit(signum, frame):
            self.log(f"Received signal {signum}, cleaning up...")
            self.cleanup_daemon()
            sys.exit(0)

        # Register handlers for common termination signals
        signal.signal(signal.SIGINT, cleanup_and_exit)
        signal.signal(signal.SIGTERM, cleanup_and_exit)

        # Also register atexit handler as fallback
        atexit.register(self.cleanup_daemon)

    def cleanup_daemon(self):
        """Clean up daemon process if it exists"""
        if self.daemon is not None:
            try:
                self.log(f"Cleaning up daemon process {self.daemon.pid}")
                self.daemon.kill()
                self.daemon = None
            except Exception as e:
                self.log(f"Error cleaning up daemon: {e}")
        
        # Also clean up log server
        self._cleanup_log_server()

    def log(self, message):
        """Log message"""
        logging.info(message)

    def _create_new_log_server(self):
        """Create a new LogServer instance for collecting logs from daemon
        
        NOTE: This creates a new log server each time for testing purposes to demonstrate
        that the daemon can be reconfigured to use different log servers. In normal use,
        you would typically use the global log server throughout the application lifecycle:
        
        # Normal usage (simpler):
        teleprox.log.start_log_server()  # Create global log server once
        log_addr = teleprox.log.get_logger_address()  # Get its address
        # Use log_addr for all daemon processes
        """
        # Clean up any existing log server
        self._cleanup_log_server()
        
        # Create new log server attached to the root logger
        self.log_server = LogServer(logging.getLogger())
        self.log(f"Created new log server at {self.log_server.address}")

    def _cleanup_log_server(self):
        """Clean up existing log server if it exists"""
        if self.log_server is not None:
            try:
                self.log_server.stop()
                self.log_server = None
                self.log("Cleaned up old log server")
            except Exception as e:
                self.log(f"Error cleaning up log server: {e}")

    def start_daemon(self):
        """Start the daemon process with GUI capabilities"""
        try:
            self.log("Starting daemon process...")

            # Create a new log server for this connection
            self._create_new_log_server()

            # Start daemon with Qt support and logging directed to this process
            self.daemon = teleprox.start_process(
                'advanced-logging-daemon',
                daemon=True,
                qt=True,  # Enable Qt event loop in daemon
                log_addr=self.log_server.address,
                log_level=logging.DEBUG
            )

            self.daemon_address = self.daemon.client.address

            # Set up the daemon with its own independent GUI
            try:
                # Get the examples directory path from this process
                import os
                examples_dir = os.path.dirname(os.path.abspath(__file__))
                self.log(f"Examples directory: {examples_dir}")

                # Add examples directory to daemon's Python path
                r_sys = self.daemon.client._import('sys')
                r_sys.path.append(examples_dir)
                self.log("Added examples dir to daemon's Python path")

                # Create QApplication in daemon if it doesn't exist
                r_qtwidgets = self.daemon.client._import('PyQt5.QtWidgets')
                daemon_app = r_qtwidgets.QApplication.instance()
                if daemon_app is None:
                    daemon_app = r_qtwidgets.QApplication([])
                self.log("Created Qt application in daemon")

                # Import daemon GUI module and create the GUI
                daemon_gui_module = self.daemon.client._import('advanced_logging')
                daemon_gui_module.create_daemon_gui()
                self.log("Created independent GUI window in daemon process")

            except Exception as gui_error:
                self.log(f"GUI setup error: {gui_error}")
                # Continue anyway - daemon can still work without GUI

            self.log(f"Daemon started with PID {self.daemon.pid} at {self.daemon_address}")

            # Update UI
            self.start_daemon_btn.setEnabled(False)
            self.reconnect_btn.setEnabled(True)
            self.test_connection_btn.setEnabled(True)
            self.daemon_status_label.setText(f"Status: Daemon running (PID {self.daemon.pid})")

        except Exception as e:
            self.log(f"Failed to start daemon: {e}")

    def reconnect_daemon(self):
        """Demonstrate reconnecting to the daemon with a new log server"""
        if not self.daemon_address:
            self.log("No daemon address available for reconnection")
            return

        try:
            self.log("Simulating reconnection with new log server...")

            # Create a new log server for this reconnection
            old_log_address = self.log_server.address if self.log_server else "none"
            self._create_new_log_server()
            self.log(f"Switched from log server {old_log_address} to {self.log_server.address}")

            # Close existing connection
            if self.daemon and self.daemon.client:
                self.daemon.client.close()
                self.log("Closed existing connection")

            # Create new client connection
            new_client = teleprox.RPCClient.get_client(address=self.daemon_address)

            # Verify connection by getting PID
            r_os = new_client._import('os')
            pid = r_os.getpid()

            self.log(f"Reconnected to daemon at {self.daemon_address} (PID {pid})")

            # Configure daemon to use the new log server
            new_client._import('teleprox.log').set_logger_address(self.log_server.address)
            self.log(f"Configured daemon to use new log server at {self.log_server.address}")

            # Update our reference
            if self.daemon:
                self.daemon.client = new_client

        except Exception as e:
            self.log(f"Reconnection failed: {e}")

    def test_connection(self):
        """Test connection to daemon by getting its PID"""
        if not self.daemon:
            self.log("No daemon available")
            return

        try:
            # Get daemon PID to verify connection
            r_os = self.daemon.client._import('os')
            pid = r_os.getpid()
            self.log(f"Connection test successful - daemon PID: {pid}")
        except Exception as e:
            self.log(f"Connection test failed: {e}")
    
    def clear_logs(self):
        """Clear all logs from the viewer using set_records()"""
        self.log_viewer.set_records()
        self.log("Cleared all logs from viewer")
    
    def load_sample_historical_logs(self):
        """Load sample historical logs to demonstrate set_records() functionality"""
        import datetime
        
        self.log("Loading sample historical logs...")
        
        # Create sample historical log records from a simulated "previous day"
        base_time = time.time() - (24 * 60 * 60)  # 24 hours ago
        historical_records = []
        
        # Create various types of historical log records
        for i in range(10):
            record_time = base_time + (i * 300)  # 5 minutes apart
            
            # Create different types of records
            if i == 0:
                # System startup record
                rec = logging.LogRecord(
                    name='system.startup', 
                    level=logging.INFO, 
                    pathname='/app/startup.py', 
                    lineno=42,
                    msg="System startup initiated", 
                    args=(), 
                    exc_info=None
                )
            elif i == 3:
                # Warning with extra attributes
                rec = logging.LogRecord(
                    name='app.performance', 
                    level=logging.WARNING, 
                    pathname='/app/monitor.py', 
                    lineno=156,
                    msg=f"High memory usage detected: {85.3}%", 
                    args=(), 
                    exc_info=None
                )
                rec.memory_percent = 85.3
                rec.process_count = 47
            elif i == 7:
                # Error with simulated exception
                try:
                    # Simulate an error that would have occurred
                    raise ConnectionError("Database connection timeout after 30s")
                except ConnectionError:
                    exc_info = sys.exc_info()
                
                rec = logging.LogRecord(
                    name='database.connection', 
                    level=logging.ERROR, 
                    pathname='/app/db.py', 
                    lineno=298,
                    msg="Failed to connect to database", 
                    args=(), 
                    exc_info=exc_info
                )
            else:
                # Regular info messages
                messages = [
                    "User authentication successful",
                    "Processing batch job #1247",
                    "Cache cleanup completed", 
                    "Scheduled backup started",
                    "API endpoint /users accessed",
                    "Configuration file reloaded",
                    "Network health check passed"
                ]
                
                rec = logging.LogRecord(
                    name=f'app.module{i}', 
                    level=logging.INFO, 
                    pathname=f'/app/module{i}.py', 
                    lineno=100 + i,
                    msg=messages[i % len(messages)], 
                    args=(), 
                    exc_info=None
                )
            
            # Set the timestamp to our historical time
            rec.created = record_time
            rec.msecs = (record_time % 1) * 1000
            
            # Set realistic process/thread info for historical records
            rec.processName = f"HistoricalProcess-{(i % 3) + 1}"
            rec.threadName = f"Thread-{(i % 2) + 1}"
            
            historical_records.append(rec)
        
        # Use set_records to replace all current logs with historical ones
        self.log_viewer.set_records(*historical_records)
        
        # Log what we just did (this will appear in the viewer since it's a new record)
        yesterday = datetime.datetime.fromtimestamp(base_time).strftime("%Y-%m-%d")
        self.log(f"Loaded {len(historical_records)} historical log records from {yesterday}")
        self.log("Notice how set_records() replaced all existing logs and preserved filters!")

    def closeEvent(self, event):
        """Handle window close event - clean up daemon process"""
        self.cleanup_daemon()
        event.accept()


def main():
    """Main entry point"""
    app = QtWidgets.QApplication(sys.argv)

    controller = DaemonController()
    controller.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
