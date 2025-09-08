# Export functionality for LogViewer
# Contains static functions for exporting log entries to HTML and text formats

import html
import time

from teleprox import qt
from .constants import LogColumns, attrs_not_shown_as_children

# HTML templates
HTML_HEADER = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .log-table {{ border-collapse: collapse; width: 100%; }}
        .log-table th, .log-table td {{ padding: 8px; text-align: left; }}
        .log-table th {{ background-color: #f2f2f2; font-weight: bold; }}
        .log-entry {{ border-bottom: 2px solid #ccc; }}
        .child-entry {{ background-color: #f9f9f9; font-family: monospace; }}
        .exception {{ color: #d9534f; font-weight: bold; }}
        .traceback {{ color: #555; }}
        .timestamp {{ white-space: nowrap; }}
        .level-debug {{ color: #6c757d; }}
        .level-info {{ color: #17a2b8; }}
        .level-warning {{ color: #ffc107; }}
        .level-error {{ color: #dc3545; }}
        .level-critical {{ color: #dc3545; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <p>Generated on {timestamp}</p>"""

HTML_FILTER_CRITERIA_SECTION = """
    <div style="background-color: #f8f9fa; padding: 10px; margin: 10px 0; border-left: 4px solid #007bff;">
        <h3 style="margin: 0 0 8px 0; color: #495057;">Applied Filters:</h3>
        <ul style="margin: 0; padding-left: 20px;">
{filter_items}
        </ul>
    </div>"""

HTML_FILTER_ITEM = (
    """            <li style="font-family: monospace; margin: 2px 0;">{filter_expr}</li>"""
)

HTML_NO_FILTERS = """
    <div style="background-color: #f8f9fa; padding: 10px; margin: 10px 0; border-left: 4px solid #007bff;">
        <h3 style="margin: 0 0 8px 0; color: #495057;">Applied Filters:</h3>
        <p style="margin: 0; font-style: italic; color: #6c757d;">No filters applied</p>
    </div>"""

HTML_TABLE_HEADER = """
    <table class="log-table">
        <thead>
            <tr>
                <th>Timestamp</th>
                <th>Source</th>
                <th>Logger</th>
                <th>Level</th>
                <th>Message</th>
            </tr>
        </thead>
        <tbody>"""

HTML_FOOTER = """        </tbody>
    </table>
</body>
</html>"""

# Level to CSS class mapping
LEVEL_CSS_CLASSES = {
    'DEBUG': 'level-debug',
    'INFO': 'level-info',
    'WARNING': 'level-warning',
    'WARN': 'level-warning',
    'ERROR': 'level-error',
    'CRITICAL': 'level-critical',
}


def export_logs_to_html(model, title, filter_criteria, parent_widget, default_filename="logs.html"):
    """Export log entries to HTML file."""
    filename, _ = qt.QFileDialog.getSaveFileName(
        parent_widget, f"Export {title} to HTML", default_filename, "HTML Files (*.html)"
    )
    if not filename:
        return

    expand_all_content_for_export(parent_widget.model)

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            # Write HTML header
            f.write(HTML_HEADER.format(title=title, timestamp=time.strftime('%Y-%m-%d %H:%M:%S')))

            # Add filter criteria summary if this is a filtered export
            _write_filter_section(f, filter_criteria)

            f.write(HTML_TABLE_HEADER)

            # Write log entries
            _write_model_rows_to_html(f, model, qt.QModelIndex())

            # Write HTML footer
            f.write(HTML_FOOTER)

    except Exception as e:
        # Show error message
        qt.QMessageBox.critical(parent_widget, "Export Error", f"Failed to export logs:\n{e}")


def expand_all_content_for_export(model):
    """Expand all lazy-loaded content in the model for export."""

    def expand_recursive(parent_item):
        # If this item has a loading placeholder, replace it with content
        if getattr(parent_item, 'has_child_placeholder', False):
            model.replace_placeholder_with_content(parent_item)

        # Recursively expand all children
        for row in range(parent_item.rowCount()):
            child_item = parent_item.child(row, 0)
            if child_item:
                expand_recursive(child_item)

    # Expand all top-level items
    for row in range(model.rowCount()):
        top_level_item = model.item(row, 0)
        if top_level_item:
            expand_recursive(top_level_item)


def _write_filter_section(file, filter_criteria):
    """Write the filter criteria section to the HTML file."""
    if filter_criteria is not None:
        if filter_criteria:
            filter_items = '\n'.join(
                HTML_FILTER_ITEM.format(filter_expr=html.escape(filter_expr))
                for filter_expr in filter_criteria
            )
            file.write(HTML_FILTER_CRITERIA_SECTION.format(filter_items=filter_items))
        else:
            file.write(HTML_NO_FILTERS)


def _write_model_rows_to_html(file, model, parent_index, indent_level=0):
    """Recursively write model rows to HTML file."""
    row_count = model.rowCount(parent_index)

    for row in range(row_count):
        # Get data from each column
        column_data = _extract_row_data(model, row, parent_index)

        # Determine CSS class based on content and level
        css_class = _determine_css_class(column_data, model, row, parent_index, indent_level)

        # Write the row
        if indent_level > 0:
            _write_child_row(file, column_data, css_class, indent_level)
        else:
            _write_main_row(file, column_data, css_class)

        # Recursively write child rows
        timestamp_index = model.index(row, LogColumns.TIMESTAMP, parent_index)
        if model.rowCount(timestamp_index) > 0:
            _write_model_rows_to_html(file, model, timestamp_index, indent_level + 1)


def _extract_row_data(model, row, parent_index):
    """Extract all column data for a row."""
    indices = {
        'timestamp': model.index(row, LogColumns.TIMESTAMP, parent_index),
        'source': model.index(row, LogColumns.SOURCE, parent_index),
        'logger': model.index(row, LogColumns.LOGGER, parent_index),
        'level': model.index(row, LogColumns.LEVEL, parent_index),
        'message': model.index(row, LogColumns.MESSAGE, parent_index),
    }

    return {key: model.data(index, qt.Qt.DisplayRole) or "" for key, index in indices.items()}


def _determine_css_class(column_data, model, row, parent_index, indent_level):
    """Determine appropriate CSS classes for the row."""
    css_class = "child-entry" if indent_level > 0 else "log-entry"

    # Add level-specific CSS class
    level_upper = column_data['level'].upper()
    for level_name, css_suffix in LEVEL_CSS_CLASSES.items():
        if level_name in level_upper:
            css_class += f" {css_suffix}"
            break

    # Check if this is an exception or traceback line
    timestamp_index = model.index(row, LogColumns.TIMESTAMP, parent_index)
    python_data = model.data(timestamp_index, qt.Qt.UserRole)
    if python_data and isinstance(python_data, dict):
        data_type = python_data.get('type', '')
        if data_type == 'exception':
            css_class += " exception"
        elif data_type in ['traceback_frame', 'stack_frame']:
            css_class += " traceback"

    return css_class


def _write_child_row(file, column_data, css_class, indent_level):
    """Write a child entry row (spanning all columns)."""
    base_indent = "&nbsp;" * (indent_level * 4)

    # Use the timestamp column content as the main content for child entries
    content = (
        column_data['timestamp'] if column_data['timestamp'].strip() else column_data['message']
    )

    # Add extra indentation for code lines (lines that start with 4+ spaces)
    extra_indent = ""
    if content.startswith("    ") and not content.strip().startswith("File "):
        extra_indent = "&nbsp;" * 8

    file.write(
        f"""            <tr class="{css_class}">
                <td colspan="5">{base_indent}{extra_indent}{html.escape(content)}</td>
            </tr>
"""
    )


def _write_main_row(file, column_data, css_class):
    """Write a main log entry row (using all columns)."""
    file.write(
        f"""            <tr class="{css_class}">
                <td class="timestamp">{html.escape(column_data['timestamp'])}</td>
                <td>{html.escape(column_data['source'])}</td>
                <td>{html.escape(column_data['logger'])}</td>
                <td>{html.escape(column_data['level'])}</td>
                <td>{html.escape(column_data['message'])}</td>
            </tr>
"""
    )


# Text export functions


def format_log_record_as_text(log_record, model=None, source_item=None, child_text=None):
    """Format a log record as plain text, optionally including child detail or full children."""
    lines = format_log_record_header(log_record)

    if child_text is not None:
        # This is a child item - add child detail section
        lines.extend(("", "Child detail:", f"  {child_text}"))
    elif (
        source_item is not None
        and model is not None
        and has_expandable_children(log_record, source_item)
    ):
        # This is a full record with expandable children - add details section
        lines.extend(("", "Details:"))

        # Ensure all lazy content is expanded
        if getattr(source_item, 'has_child_placeholder', False):
            model.replace_placeholder_with_content(source_item)

        # Use model's existing method to get children
        children = model._create_record_attribute_children(log_record)
        lines.extend(format_record_children_as_text(children, indent_level=1))

    return '\n'.join(lines)


def format_log_record_header(log_record):
    """Format the common header information for a log record."""
    lines = []

    # Core fields always shown first
    lines.append(
        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log_record.created))}.{log_record.msecs:03.0f}"
    )
    lines.append(
        f"Source: {getattr(log_record, 'processName', 'Unknown')}/{getattr(log_record, 'threadName', 'Unknown')}"
    )
    lines.append(f"Logger: {log_record.name}")
    lines.append(f"Level: {log_record.levelno} - {log_record.levelname}")
    lines.append(f"Message: {log_record.getMessage()}")

    # Show raw message format string if different from formatted message
    if hasattr(log_record, 'msg') and log_record.msg != log_record.getMessage():
        lines.append(f"Message Format: {log_record.msg}")

    # Standard LogRecord fields (excluding core ones already shown)
    standard_fields = [
        'args',
        'filename',
        'funcName',
        'lineno',
        'module',
        'pathname',
        'process',
        'relativeCreated',
        'stack_info',
        'thread',
        'exc_info',
        'exc_text',
    ]

    for field in standard_fields:
        if hasattr(log_record, field):
            value = getattr(log_record, field)
            if value is not None and value != () and value != '':  # Skip empty/None values
                # Format certain fields specially
                if field == 'args':
                    if value:  # Only show non-empty args
                        lines.append(f"Args: {value}")
                elif field == 'relativeCreated':
                    lines.append(f"Relative Created: {value:.3f}ms")
                elif field in ('exc_info', 'stack_info'):
                    if value:  # Only show if there's actual exception/stack info
                        lines.append(f"{field.replace('_', ' ').title()}: {value}")
                elif field == 'exc_text':
                    if value and value.strip():  # Only show non-empty exception text
                        lines.append(f"Exception Text: {value}")
                else:
                    # Generic field formatting
                    display_name = field.replace('_', ' ').title()
                    lines.append(f"{display_name}: {value}")

    # Add any extra fields not in standard LogRecord fields
    standard_field_set = {
        'name',
        'msg',
        'args',
        'pathname',
        'filename',
        'module',
        'lineno',
        'funcName',
        'created',
        'msecs',
        'relativeCreated',
        'thread',
        'threadName',
        'process',
        'processName',
        'levelname',
        'levelno',
        'exc_info',
        'exc_text',
        'stack_info',
        'getMessage',  # This is a method, not an attribute
    }

    extra_fields = {}
    for attr_name in log_record.__dict__:
        if attr_name not in standard_field_set and not attr_name.startswith('_'):
            value = getattr(log_record, attr_name)
            if value is not None and value != () and value != '':
                extra_fields[attr_name] = value

    # Sort extra fields for consistent output
    for attr_name in sorted(extra_fields.keys()):
        value = extra_fields[attr_name]
        display_name = attr_name.replace('_', ' ').title()
        lines.append(f"{display_name}: {value}")

    return lines


def has_expandable_children(log_record, source_item):
    """Check if the log record has expandable children."""
    # Use same logic as model for consistency
    return getattr(source_item, 'has_child_placeholder', False) or any(
        True
        for k in log_record.__dict__
        if (k not in attrs_not_shown_as_children and not k.startswith('_'))
    )


def format_record_children_as_text(children, indent_level=1):
    """Format record children items as text recursively."""
    indent = "  " * indent_level
    lines = []

    for child_row in children:
        if child_row and len(child_row) > 0:
            child_item = child_row[0]  # First column contains the text
            child_text = child_item.text()
            lines.append(f"{indent}{child_text}")

            # Handle nested children if any exist
            if child_item.rowCount() > 0:
                nested_children = []
                for row in range(child_item.rowCount()):
                    nested_row = [
                        child_item.child(row, col) for col in range(child_item.columnCount())
                    ]
                    nested_children.append(nested_row)
                lines.extend(format_record_children_as_text(nested_children, indent_level + 1))

    return lines
