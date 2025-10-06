import logging
import os
import tempfile
from unittest.mock import patch

from teleprox import qt
from teleprox.log.logviewer.constants import LogColumns
from teleprox.log.logviewer.export import format_log_record_as_text, format_log_record_header
from teleprox.log.logviewer.viewer import LogViewer

try:
    import pytest
except ImportError:
    # Mock pytest for basic functionality
    class MockPytest:
        def fixture(self, func):
            return func

    pytest = MockPytest()


class TestLogViewerExport:
    """Test cases for HTML export functionality."""

    # QApplication fixture provided by conftest.py

    def test_export_all_to_html_basic_functionality(self, qapp):
        """Test that export all to HTML creates a valid HTML file with log entries."""
        viewer = LogViewer(logger='test.export.all', initial_filters=[])
        logger = logging.getLogger('test.export.all')
        logger.setLevel(logging.DEBUG)

        # Add various log levels
        logger.debug("Debug message for export")
        logger.info("Info message for export")
        logger.warning("Warning message for export")
        logger.error("Error message for export")
        logger.critical("Critical message for export")

        qapp.processEvents()

        # Create temporary file for export
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp_file:
            temp_filename = tmp_file.name

        try:
            # Mock the file dialog to return our temp file
            with patch('teleprox.qt.QFileDialog.getSaveFileName') as mock_dialog:
                mock_dialog.return_value = (temp_filename, "HTML Files (*.html)")

                # Trigger export all
                viewer._export_all_to_html()

            # Verify file was created and has content
            assert os.path.exists(temp_filename), "Export file should be created"

            with open(temp_filename, 'r', encoding='utf-8') as f:
                html_content = f.read()

            # Verify basic HTML structure
            assert '<!DOCTYPE html>' in html_content, "Should have HTML doctype"
            assert '<html>' in html_content, "Should have HTML tag"
            assert '<head>' in html_content, "Should have head section"
            assert '<title>All Log Entries</title>' in html_content, "Should have correct title"
            assert '<body>' in html_content, "Should have body section"
            assert '</html>' in html_content, "Should close HTML tag"

            # Verify all log messages are present
            assert "Debug message for export" in html_content, "Should contain debug message"
            assert "Info message for export" in html_content, "Should contain info message"
            assert "Warning message for export" in html_content, "Should contain warning message"
            assert "Error message for export" in html_content, "Should contain error message"
            assert "Critical message for export" in html_content, "Should contain critical message"

            # Verify table structure
            assert '<table class="log-table">' in html_content, "Should have log table"
            assert '<th>Timestamp</th>' in html_content, "Should have timestamp header"
            assert '<th>Source</th>' in html_content, "Should have source header"
            assert '<th>Logger</th>' in html_content, "Should have logger header"
            assert '<th>Level</th>' in html_content, "Should have level header"
            assert '<th>Message</th>' in html_content, "Should have message header"

            # Verify CSS classes for different levels
            assert 'class="log-entry level-debug"' in html_content, "Should have debug CSS class"
            assert 'class="log-entry level-info"' in html_content, "Should have info CSS class"
            assert (
                'class="log-entry level-warning"' in html_content
            ), "Should have warning CSS class"
            assert 'class="log-entry level-error"' in html_content, "Should have error CSS class"
            assert (
                'class="log-entry level-critical"' in html_content
            ), "Should have critical CSS class"

        finally:
            # Clean up temp file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def test_export_filtered_to_html_with_filters(self, qapp):
        """Test that export filtered to HTML only includes filtered entries and shows filter criteria."""
        viewer = LogViewer(logger='test.export.filtered', initial_filters=[])
        logger = logging.getLogger('test.export.filtered')
        logger.setLevel(logging.DEBUG)

        # Add messages at different levels
        logger.debug("Debug message - should not appear in filtered export")
        logger.info("Info message - should not appear in filtered export")
        logger.warning("Warning message - should appear in filtered export")
        logger.error("Error message - should appear in filtered export")
        logger.critical("Critical message - should appear in filtered export")

        qapp.processEvents()

        # Apply WARNING level filter through the UI (so it gets tracked properly)
        viewer.filter_input_widget.filter_input.setText('level: warning')
        viewer.filter_input_widget.add_filter()

        # Create temporary file for export
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp_file:
            temp_filename = tmp_file.name

        try:
            # Mock the file dialog to return our temp file
            with patch('teleprox.qt.QFileDialog.getSaveFileName') as mock_dialog:
                mock_dialog.return_value = (temp_filename, "HTML Files (*.html)")

                # Trigger export filtered
                viewer._export_filtered_to_html()

            # Verify file was created and has content
            assert os.path.exists(temp_filename), "Export file should be created"

            with open(temp_filename, 'r', encoding='utf-8') as f:
                html_content = f.read()

            # Verify basic HTML structure
            assert (
                '<title>Filtered Log Entries</title>' in html_content
            ), "Should have filtered title"

            # Verify filter criteria section is present
            assert 'Applied Filters:' in html_content, "Should show applied filters section"
            assert 'level: warning' in html_content, "Should show the applied filter"

            # Verify only WARNING and above messages are present (WARNING=30, ERROR=40, CRITICAL=50)
            assert "Debug message" not in html_content, "Should not contain debug message"
            assert "Info message" not in html_content, "Should not contain info message"
            assert (
                "Warning message - should appear in filtered export" in html_content
            ), "Should contain warning message"
            assert (
                "Error message - should appear in filtered export" in html_content
            ), "Should contain error message"
            assert (
                "Critical message - should appear in filtered export" in html_content
            ), "Should contain critical message"

        finally:
            # Clean up temp file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def test_export_with_exceptions_and_stack_traces(self, qapp):
        """Test that exceptions and stack traces are properly exported with hierarchical structure."""
        viewer = LogViewer(logger='test.export.exceptions', initial_filters=[])
        logger = logging.getLogger('test.export.exceptions')
        logger.setLevel(logging.DEBUG)

        # Add a regular message
        logger.info("Regular info message")

        # Create a multi-level exception to get proper stack trace
        def inner_function():
            raise ValueError("Test exception for export")

        def middle_function():
            inner_function()

        def outer_function():
            middle_function()

        try:
            outer_function()
        except Exception:
            logger.error("Error with full exception details", exc_info=True)

        # Add another message with extra data
        logger.warning(
            "Warning with extra data",
            extra={
                'user_id': 12345,
                'request_data': {'method': 'POST', 'url': '/api/test'},
                'performance': {'duration': 0.123},
            },
        )

        qapp.processEvents()

        # Expand all content for export (this happens automatically during export)
        # But let's manually expand to verify the content is there
        for i in range(viewer.model.rowCount()):
            item = viewer.model.item(i, LogColumns.TIMESTAMP)
            if item and item.rowCount() > 0:
                viewer.expand_item(item)

        # Create temporary file for export
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp_file:
            temp_filename = tmp_file.name

        try:
            # Mock the file dialog to return our temp file
            with patch('teleprox.qt.QFileDialog.getSaveFileName') as mock_dialog:
                mock_dialog.return_value = (temp_filename, "HTML Files (*.html)")

                # Trigger export all (to include exception details)
                viewer._export_all_to_html()

            # Verify file was created and has content
            assert os.path.exists(temp_filename), "Export file should be created"

            with open(temp_filename, 'r', encoding='utf-8') as f:
                html_content = f.read()

            # Verify all top-level messages are present
            assert "Regular info message" in html_content, "Should contain regular message"
            assert (
                "Error with full exception details" in html_content
            ), "Should contain error message"
            assert "Warning with extra data" in html_content, "Should contain warning message"

            # Verify exception details are exported
            assert "ValueError" in html_content, "Should contain exception type"
            assert "Test exception for export" in html_content, "Should contain exception message"

            # Verify stack trace elements are present
            assert (
                "inner_function" in html_content
            ), "Should contain inner function from stack trace"
            assert (
                "middle_function" in html_content
            ), "Should contain middle function from stack trace"
            assert (
                "outer_function" in html_content
            ), "Should contain outer function from stack trace"

            # Verify traceback file references
            assert "File " in html_content, "Should contain file references from traceback"
            assert "line " in html_content, "Should contain line numbers from traceback"

            # Verify extra data from warning message
            assert "user_id" in html_content, "Should contain extra user_id data"
            assert "12345" in html_content, "Should contain user_id value"
            assert "request_data" in html_content, "Should contain request data"
            assert "performance" in html_content, "Should contain performance data"

            # Verify hierarchical structure with child entries
            assert 'class="child-entry"' in html_content, "Should have child entry CSS classes"
            assert 'colspan="5"' in html_content, "Should span all columns for child entries"

            # The content is more important than exact CSS classes
            # Verify that exception and stack trace content are properly exported

        finally:
            # Clean up temp file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def test_export_handles_file_dialog_cancellation(self, qapp):
        """Test that export handles user cancelling the file dialog gracefully."""
        viewer = LogViewer(logger='test.export.cancel', initial_filters=[])
        logger = logging.getLogger('test.export.cancel')
        logger.info("Test message")

        qapp.processEvents()

        # Mock the file dialog to return empty (user cancelled)
        with patch('teleprox.qt.QFileDialog.getSaveFileName') as mock_dialog:
            mock_dialog.return_value = ("", "")  # Empty filename means user cancelled

            # Trigger export all - should not crash
            viewer._export_all_to_html()

            # Trigger export filtered - should not crash
            viewer._export_filtered_to_html()

        # Test passes if no exception was raised

    def test_export_with_no_filters_shows_no_filters_message(self, qapp):
        """Test that filtered export with no filters applied shows appropriate message."""
        viewer = LogViewer(logger='test.export.no.filters', initial_filters=[])
        logger = logging.getLogger('test.export.no.filters')
        logger.info("Test message")

        qapp.processEvents()

        # Don't apply any filters

        # Create temporary file for export
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp_file:
            temp_filename = tmp_file.name

        try:
            # Mock the file dialog to return our temp file
            with patch('teleprox.qt.QFileDialog.getSaveFileName') as mock_dialog:
                mock_dialog.return_value = (temp_filename, "HTML Files (*.html)")

                # Trigger export filtered
                viewer._export_filtered_to_html()

            with open(temp_filename, 'r', encoding='utf-8') as f:
                html_content = f.read()

            # Verify appropriate "no filters" message
            assert 'No filters applied' in html_content, "Should show no filters applied message"

        finally:
            # Clean up temp file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def test_export_error_handling(self, qapp):
        """Test that export handles file write errors gracefully."""
        viewer = LogViewer(logger='test.export.error', initial_filters=[])
        logger = logging.getLogger('test.export.error')
        logger.info("Test message")

        qapp.processEvents()

        # Mock file dialog to return an invalid path (e.g., directory that doesn't exist)
        invalid_path = "/nonexistent/directory/test.html"

        with patch('teleprox.qt.QFileDialog.getSaveFileName') as mock_dialog, patch(
            'teleprox.qt.QMessageBox.critical'
        ) as mock_error:

            mock_dialog.return_value = (invalid_path, "HTML Files (*.html)")

            # Trigger export - should handle error gracefully
            viewer._export_all_to_html()

            # Verify error dialog was shown
            mock_error.assert_called_once()
            args, kwargs = mock_error.call_args
            assert "Export Error" in args[1], "Should show export error dialog title"
            assert "Failed to export logs" in args[2], "Should show export error message"


def run_manual_tests():
    """Run basic tests without pytest."""
    # Create QApplication for manual testing (conftest.py only works in pytest)
    qapp = qt.QApplication.instance()
    if qapp is None:
        qapp = qt.QApplication([])

    print("Test 1: Export all to HTML basic functionality...")
    test = TestLogViewerExport()
    test.test_export_all_to_html_basic_functionality(qapp)
    print("✅ Test 1 passed!")

    print("Test 2: Export filtered to HTML with filters...")
    test.test_export_filtered_to_html_with_filters(qapp)
    print("✅ Test 2 passed!")

    print("Test 3: Export with exceptions and stack traces...")
    test.test_export_with_exceptions_and_stack_traces(qapp)
    print("✅ Test 3 passed!")

    print("Test 4: Export handles file dialog cancellation...")
    test.test_export_handles_file_dialog_cancellation(qapp)
    print("✅ Test 4 passed!")

    print("Test 5: Export with no filters shows no filters message...")
    test.test_export_with_no_filters_shows_no_filters_message(qapp)
    print("✅ Test 5 passed!")

    print("Test 6: Export error handling...")
    test.test_export_error_handling(qapp)
    print("✅ Test 6 passed!")

    print("All export tests completed successfully!")


class TestLogRecordTextFormatting:
    """Test cases for LogRecord text formatting functions."""

    def test_format_log_record_header_with_all_default_fields(self):
        """Test that format_log_record_header includes all default LogRecord fields."""
        # Create a LogRecord with standard fields populated
        record = logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='/path/to/test.py',
            lineno=42,
            msg='Test message with args: %s %d',
            args=('hello', 123),
            exc_info=None,
        )

        # Add some additional standard fields that are normally set by logging
        record.funcName = 'test_function'
        record.module = 'test'
        record.filename = 'test.py'
        record.processName = 'TestProcess'
        record.threadName = 'TestThread'

        lines = format_log_record_header(record)
        text_output = '\n'.join(lines)

        # Verify core fields are present
        assert 'Timestamp:' in text_output
        assert 'Source: TestProcess/TestThread' in text_output
        assert 'Logger: test.logger' in text_output
        assert f'Level: {logging.INFO} - INFO' in text_output
        assert 'Message: Test message with args: hello 123' in text_output

        # Verify standard fields are included
        assert 'Args: (\'hello\', 123)' in text_output
        assert 'Filename: test.py' in text_output
        assert 'Funcname: test_function' in text_output
        assert 'Lineno: 42' in text_output
        assert 'Module: test' in text_output
        assert 'Pathname: /path/to/test.py' in text_output
        assert 'Process:' in text_output  # process ID will be present
        assert 'Thread:' in text_output  # thread ID will be present
        assert 'Relative Created:' in text_output and 'ms' in text_output

    def test_format_log_record_header_with_extra_fields(self):
        """Test that format_log_record_header includes user-added extra fields."""
        record = logging.LogRecord(
            name='test.logger',
            level=logging.WARNING,
            pathname='/test.py',
            lineno=10,
            msg='Warning message',
            args=(),
            exc_info=None,
        )

        # Add extra fields that a user might add (this is what logging would do)
        record.user_id = 'user123'
        record.request_id = 'req-456'
        record.custom_data = {'key': 'value', 'number': 42}
        record.performance_metric = 0.123

        lines = format_log_record_header(record)
        text_output = '\n'.join(lines)

        # Verify core fields
        assert 'Logger: test.logger' in text_output
        assert 'Level: 30 - WARNING' in text_output
        assert 'Message: Warning message' in text_output

        # Verify extra fields are included (sorted alphabetically)
        assert 'Custom Data: {\'key\': \'value\', \'number\': 42}' in text_output
        assert 'Performance Metric: 0.123' in text_output
        assert 'Request Id: req-456' in text_output
        assert 'User Id: user123' in text_output

    def test_format_log_record_header_filters_empty_values(self):
        """Test that empty/None values are filtered out from output."""
        record = logging.LogRecord(
            name='test.logger',
            level=logging.ERROR,
            pathname='/test.py',
            lineno=5,
            msg='Error message',
            args=(),  # Empty tuple should be filtered
            exc_info=None,  # None should be filtered
        )

        # Add some fields with empty/None values
        record.empty_string = ''
        record.none_value = None
        record.empty_tuple = ()
        record.valid_field = 'should_appear'

        lines = format_log_record_header(record)
        text_output = '\n'.join(lines)

        # Verify empty values are not included
        assert 'Empty String:' not in text_output
        assert 'None Value:' not in text_output
        assert 'Empty Tuple:' not in text_output
        assert 'Args:' not in text_output  # Empty args should be filtered
        assert 'Exc Info:' not in text_output  # None exc_info should be filtered

        # Verify valid field is included
        assert 'Valid Field: should_appear' in text_output

    def test_format_log_record_header_with_exception_info(self):
        """Test formatting of exception information fields."""
        try:
            raise ValueError("Test exception")
        except Exception:
            exc_info = logging.sys.exc_info()

        record = logging.LogRecord(
            name='test.logger',
            level=logging.ERROR,
            pathname='/test.py',
            lineno=20,
            msg='Error occurred',
            args=(),
            exc_info=exc_info,
        )

        # Add exception text
        record.exc_text = "ValueError: Test exception\n  File test.py, line 20"
        record.stack_info = "Stack trace info here"

        lines = format_log_record_header(record)
        text_output = '\n'.join(lines)

        # Verify exception fields are included when present
        assert 'Exc Info:' in text_output
        assert 'Exception Text: ValueError: Test exception' in text_output
        assert 'Stack Info: Stack trace info here' in text_output

    def test_format_log_record_as_text_basic(self):
        """Test basic format_log_record_as_text functionality."""
        record = logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='/test.py',
            lineno=1,
            msg='Simple message',
            args=(),
            exc_info=None,
        )

        result = format_log_record_as_text(record)

        # Should contain header information
        assert 'Logger: test.logger' in result
        assert 'Message: Simple message' in result
        assert 'Level: 20 - INFO' in result

    def test_format_log_record_as_text_with_child_text(self):
        """Test format_log_record_as_text with child detail."""
        record = logging.LogRecord(
            name='test.logger',
            level=logging.DEBUG,
            pathname='/test.py',
            lineno=1,
            msg='Parent message',
            args=(),
            exc_info=None,
        )

        result = format_log_record_as_text(record, child_text="Child detail info")

        # Should contain both header and child detail
        assert 'Logger: test.logger' in result
        assert 'Child detail:' in result
        assert '  Child detail info' in result


def run_manual_text_formatting_tests():
    """Run text formatting tests without pytest."""
    print("Running manual text formatting tests...")

    test = TestLogRecordTextFormatting()

    print("Test 1: Format log record header with all default fields...")
    test.test_format_log_record_header_with_all_default_fields()
    print("✅ Test 1 passed!")

    print("Test 2: Format log record header with extra fields...")
    test.test_format_log_record_header_with_extra_fields()
    print("✅ Test 2 passed!")

    print("Test 3: Format log record header filters empty values...")
    test.test_format_log_record_header_filters_empty_values()
    print("✅ Test 3 passed!")

    print("Test 4: Format log record header with exception info...")
    test.test_format_log_record_header_with_exception_info()
    print("✅ Test 4 passed!")

    print("Test 5: Format log record as text basic...")
    test.test_format_log_record_as_text_basic()
    print("✅ Test 5 passed!")

    print("Test 6: Format log record as text with child text...")
    test.test_format_log_record_as_text_with_child_text()
    print("✅ Test 6 passed!")

    print("All text formatting tests completed successfully!")


if __name__ == "__main__":
    if 'pytest' in globals() and hasattr(pytest, 'main'):
        # Run with pytest if available
        pytest.main([__file__, '-v'])
    else:
        # Run manual tests
        run_manual_tests()
        run_manual_text_formatting_tests()
