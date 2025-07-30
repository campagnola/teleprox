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
        self.log_viewer = None
        self.setup_ui()
        self.setup_logging()
        self.setup_signal_handlers()

    def setup_ui(self):
        """Create the UI controls"""
        self.setWindowTitle("Advanced Logging Example - Controller")
        self.setGeometry(100, 100, 400, 300)

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

        # Log controls
        log_group = QtWidgets.QGroupBox("Logging Controls")
        log_layout = QtWidgets.QVBoxLayout()

        self.show_logs_btn = QtWidgets.QPushButton("Show Log Viewer")
        self.show_logs_btn.clicked.connect(self.show_log_viewer)
        log_layout.addWidget(self.show_logs_btn)

        self.test_connection_btn = QtWidgets.QPushButton("Test Connection to Daemon")
        self.test_connection_btn.clicked.connect(self.test_connection)
        self.test_connection_btn.setEnabled(False)
        log_layout.addWidget(self.test_connection_btn)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Output area
        self.output_text = QtWidgets.QTextEdit()
        self.output_text.setMaximumHeight(150)
        layout.addWidget(QtWidgets.QLabel("Output:"))
        layout.addWidget(self.output_text)

        self.setLayout(layout)

    def setup_logging(self):
        """Set up logging for this process"""
        teleprox.log.basic_config(log_level='DEBUG', exceptions=False)
        self.log_address = teleprox.log.get_logger_address()
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

    def log(self, message):
        """Add message to output and log it"""
        self.output_text.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        logging.info(message)

    def start_daemon(self):
        """Start the daemon process with GUI capabilities"""
        try:
            self.log("Starting daemon process...")

            # Start daemon with Qt support and logging directed to this process
            self.daemon = teleprox.start_process(
                'advanced-logging-daemon',
                daemon=True,
                qt=True,  # Enable Qt event loop in daemon
                log_addr=self.log_address,
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
        """Demonstrate reconnecting to the daemon"""
        if not self.daemon_address:
            self.log("No daemon address available for reconnection")
            return

        try:
            self.log("Simulating reconnection...")

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

            # Re-establish logging connection
            new_client._import('teleprox.log').set_logger_address(self.log_address)
            self.log("Re-established logging connection")

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

    def show_log_viewer(self):
        """Show the log viewer window"""
        if self.log_viewer is None:
            self.log_viewer = LogViewer()
        self.log_viewer.show()
        self.log_viewer.raise_()
        self.log_viewer.activateWindow()

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
