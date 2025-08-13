# Test LogViewer thread safety for multi-threaded logging
# Ensures messages from non-Qt threads are properly handled via queued signals

import logging
import threading
import time
import pytest
from teleprox.log.logviewer.viewer import LogViewer
from teleprox.log.logviewer.constants import LogColumns
from teleprox import qt


class TestLogViewerThreadSafety:
    """Test LogViewer's thread safety mechanisms."""
    
    # QApplication fixture provided by conftest.py
    
    def test_main_thread_logging(self, qapp):
        """Test that main thread logging works normally."""
        viewer = LogViewer(logger='test.main.thread')
        logger = logging.getLogger('test.main.thread')
        logger.setLevel(logging.DEBUG)
        
        initial_count = viewer.model.rowCount()
        
        # Log from main thread
        logger.info("Main thread message")
        
        # Should be processed immediately
        assert viewer.model.rowCount() == initial_count + 1
        
        # Verify the message
        message_item = viewer.model.item(initial_count, LogColumns.MESSAGE)
        assert message_item.text() == "Main thread message"
    
    def test_background_thread_logging(self, qapp):
        """Test that background thread logging is handled safely."""
        viewer = LogViewer(logger='test.bg.thread')
        logger = logging.getLogger('test.bg.thread')
        logger.setLevel(logging.DEBUG)
        
        initial_count = viewer.model.rowCount()
        messages_received = []
        
        def background_logging():
            logger.info("Background message 1")
            logger.warning("Background message 2")
        
        # Start background thread
        bg_thread = threading.Thread(target=background_logging)
        bg_thread.start()
        bg_thread.join()
        
        # Process queued signals
        qapp.processEvents()
        time.sleep(0.05)  # Brief delay for signal processing
        qapp.processEvents()
        
        # Should have received both messages
        assert viewer.model.rowCount() == initial_count + 2
        
        # Verify messages are from background thread
        for i in range(2):
            source_item = viewer.model.item(initial_count + i, LogColumns.SOURCE)
            source_text = source_item.text()
            # Should not contain "MainThread"
            assert "MainThread" not in source_text
    
    def test_mixed_thread_logging(self, qapp):
        """Test that mixed main and background thread logging works correctly."""
        viewer = LogViewer(logger='test.mixed.thread')
        logger = logging.getLogger('test.mixed.thread')
        logger.setLevel(logging.DEBUG)
        
        initial_count = viewer.model.rowCount()
        
        # Log from main thread
        logger.info("Main message 1")
        
        def background_work():
            logger.info("Background message")
            
        # Log from background thread
        bg_thread = threading.Thread(target=background_work)
        bg_thread.start()
        bg_thread.join()
        
        # Log from main thread again
        logger.info("Main message 2")
        
        # Process queued signals
        qapp.processEvents()
        time.sleep(0.05)
        qapp.processEvents()
        
        # Should have all 3 messages
        assert viewer.model.rowCount() == initial_count + 3
        
        # Verify message content and sources
        main_thread_messages = []
        background_messages = []
        
        for i in range(3):
            source_item = viewer.model.item(initial_count + i, LogColumns.SOURCE)
            message_item = viewer.model.item(initial_count + i, LogColumns.MESSAGE)
            source = source_item.text()
            message = message_item.text()
            
            if "MainThread" in source:
                main_thread_messages.append(message)
            else:
                background_messages.append(message)
        
        # Should have 2 main thread messages and 1 background message
        assert len(main_thread_messages) == 2
        assert len(background_messages) == 1
        
        # Verify specific messages
        assert "Main message 1" in main_thread_messages
        assert "Main message 2" in main_thread_messages
        assert background_messages[0] == "Background message"