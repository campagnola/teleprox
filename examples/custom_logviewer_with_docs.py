# Example: Custom LogViewer with Documentation Links
# Shows how to extend LogModel and LogViewer to handle custom log data like documentation links

import logging
import webbrowser

from teleprox import qt
from teleprox.log.logviewer.constants import ItemDataRole
from teleprox.log.logviewer.log_model import LogModel
from teleprox.log.logviewer.viewer import LogViewer


class CustomLogModel(LogModel):
    """Custom LogModel that handles 'docs' attribute as clickable documentation links."""

    def _get_attribute_handler(self, attr_name):
        """Override to add custom handler for 'docs' attribute."""
        # Check for docs attribute
        if attr_name == 'docs' or attr_name.endswith('_docs'):
            return self._create_docs_children

        # Fall back to parent implementation for all other attributes
        return super()._get_attribute_handler(attr_name)

    def _create_docs_children(self, record, attr_name, attr_value):
        """Create child items for documentation links."""
        children = []

        # Skip if docs is None or empty
        if not attr_value:
            return children

        # Create "Documentation" category
        docs_category_item = self._create_category_item(f"Documentation ({attr_name})", record)

        # Handle different docs formats
        if isinstance(attr_value, str):
            # Single doc link as string
            doc_links = [attr_value]
        elif isinstance(attr_value, (list, tuple)):
            # Multiple doc links
            doc_links = attr_value
        else:
            # Unknown format, convert to string
            doc_links = [str(attr_value)]

        # Create child items for each documentation link
        for i, doc_link in enumerate(doc_links):
            doc_url = str(doc_link).strip()
            if doc_url:
                # Create clickable documentation link item
                doc_row = self._create_child_row(
                    "",
                    f"📖 {doc_url}",  # Using book emoji to indicate it's a doc link
                    {
                        'type': 'documentation_link',
                        'text': doc_url,
                        'url': doc_url,
                        'link_index': i,
                        'parent_record': record,
                    },
                    record,
                )
                docs_category_item.appendRow(doc_row)

        # Create sibling items for the docs category
        sibling_items = self._create_sibling_items_with_filter_data(record)
        children.append([docs_category_item] + sibling_items)

        return children

    def _create_child_row(self, label, message, data_dict, parent_record):
        """Override to make documentation links clickable."""
        child_row = super()._create_child_row(label, message, data_dict, parent_record)

        # Make documentation links clickable
        if data_dict.get('type') == 'documentation_link':
            item = child_row[0]
            item.setFlags(qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable)  # Allow clicking

            # Style documentation links differently
            item.setForeground(qt.QColor("#0066CC"))  # Blue for links
            font = item.font()
            font.setUnderline(True)  # Underline to indicate it's clickable
            item.setFont(font)

        return child_row

    def _create_remote_exception_children(self, exc_value, record):
        """Override to add docs support for exceptions that have getattr(exc, 'docs', [])."""
        # Get the standard remote exception children first
        children = super()._create_remote_exception_children(exc_value, record)

        # Check if this exception has docs attribute
        if hasattr(exc_value, 'docs'):
            docs_attr = getattr(exc_value, 'docs', None)
            if docs_attr:
                # Use our docs handler to create documentation children
                docs_children = self._create_docs_children(record, 'exception_docs', docs_attr)
                children.extend(docs_children)

        return children


class CustomLogViewer(LogViewer):
    """Custom LogViewer that handles documentation link clicks."""

    # Signal emitted when user clicks on a documentation link
    documentation_link_clicked = qt.Signal(str)  # (url)

    def __init__(self, logger='', initial_filters=('level: info',), parent=None):
        # Call parent __init__ first
        super().__init__(logger, initial_filters, parent)

        # Replace the standard model with our custom one
        self._replace_model_with_custom()

        # Connect our custom signal to open URLs in browser
        self.documentation_link_clicked.connect(self._open_documentation_link)

    def _replace_model_with_custom(self):
        """Replace the standard LogModel with our CustomLogModel."""
        from teleprox.log.logviewer.constants import LogColumns
        from teleprox.log.logviewer.filtering import USE_CHAINED_FILTERING

        # Create our custom model
        custom_model = CustomLogModel()
        custom_model.setHorizontalHeaderLabels(LogColumns.TITLES)

        # Replace the model in the proxy
        if USE_CHAINED_FILTERING:
            # For chained filtering, we need to update the source model
            if hasattr(self.proxy_model, 'set_source_model'):
                self.proxy_model.set_source_model(custom_model)
            elif hasattr(self.proxy_model, '_source_model'):
                self.proxy_model._source_model = custom_model
            else:
                # Fallback: recreate proxy with new model
                from teleprox.log.logviewer.filtering import LogFilterProxyModel

                self.proxy_model = LogFilterProxyModel(custom_model)
                self.tree.setModel(self.proxy_model.final_model)
        else:
            # For simple proxy model, just set source model
            self.proxy_model.setSourceModel(custom_model)

        # Update our reference to the model
        self.model = custom_model

    def _on_item_clicked(self, index):
        """Override to handle documentation link clicks."""
        if not index.isValid():
            return

        # Map to source model if using proxy
        source_index = self.map_index_to_model(index)

        # Get the actual item from our LogModel
        item = self.model.itemFromIndex(source_index)
        if not item:
            return

        # Check if this is a documentation link
        data = item.data(ItemDataRole.PYTHON_DATA)
        if data and isinstance(data, dict) and data.get('type') == 'documentation_link':
            url = data.get('url')
            if url:
                # Emit our custom signal for documentation links
                self.documentation_link_clicked.emit(url)
                return

        # Fall back to parent implementation for other click types (code lines, etc.)
        super()._on_item_clicked(index)

    def _open_documentation_link(self, url):
        """Open documentation link in default browser."""
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"Failed to open documentation link {url}: {e}")


class CustomExceptionWithDocs(Exception):
    """Custom exception that includes documentation links."""

    def __init__(self, message, docs=None):
        super().__init__(message)
        self.docs = docs or []


def create_sample_log_records():
    """Create sample log records with documentation links for testing."""
    records = []

    # Create a logger for testing
    logger = logging.getLogger('example.app')

    # Sample 1: Single documentation link
    record1 = logger.makeRecord(
        name='example.app.auth',
        level=logging.INFO,
        fn='auth.py',
        lno=42,
        msg='User authentication successful for %s',
        args=('user123',),
        exc_info=None,
        extra={'docs': ['https://docs.example.com/auth.html#login-flow']},
    )
    records.append(record1)

    # Sample 2: Multiple documentation links
    record2 = logger.makeRecord(
        name='example.app.database',
        level=logging.ERROR,
        fn='db.py',
        lno=150,
        msg='Database connection failed: %s',
        args=('Connection timeout',),
        exc_info=None,
        extra={
            'docs': [
                'https://docs.example.com/database.html#connection-troubleshooting',
                'https://docs.example.com/database.html#timeout-settings',
                'https://support.example.com/kb/db-connection-errors',
            ]
        },
    )
    records.append(record2)

    # Sample 3: Record without docs (should work normally)
    record3 = logger.makeRecord(
        name='example.app.core',
        level=logging.DEBUG,
        fn='core.py',
        lno=25,
        msg='Processing request %s',
        args=('GET /api/users',),
        exc_info=None,
        extra={},
    )
    records.append(record3)

    # Sample 4: Record with custom docs field name
    record4 = logger.makeRecord(
        name='example.app.api',
        level=logging.WARNING,
        fn='api.py',
        lno=88,
        msg='API rate limit exceeded for client %s',
        args=('client_456',),
        exc_info=None,
        extra={'api_docs': ['https://docs.example.com/api.html#rate-limiting']},
    )
    records.append(record4)

    # Sample 5: Record with exception that has docs attribute
    try:
        # Create and raise a custom exception with docs
        exc_with_docs = CustomExceptionWithDocs(
            "Database connection failed",
            docs=[
                'https://docs.example.com/database.html#connection-errors',
                'https://support.example.com/kb/troubleshooting-db-connections',
                'https://docs.example.com/database.html#connection-pooling',
            ],
        )
        raise exc_with_docs
    except CustomExceptionWithDocs:
        import sys

        exc_info = sys.exc_info()  # Get the current exception info
        record5 = logger.makeRecord(
            name='example.app.database',
            level=logging.ERROR,
            fn='db.py',
            lno=200,
            msg='Database error with documentation links in exception',
            args=(),
            exc_info=exc_info,  # Pass the actual exc_info tuple
            extra={},
        )
        records.append(record5)

    return records


def main():
    """Example usage of CustomLogViewer with documentation links."""
    import sys

    app = qt.QApplication(sys.argv)

    # Create custom log viewer
    viewer = CustomLogViewer()
    viewer.setWindowTitle('Custom LogViewer with Documentation Links')
    viewer.resize(1400, 800)

    # Add sample log records
    sample_records = create_sample_log_records()
    viewer.set_records(*sample_records)

    # Connect to a custom handler to show when docs are clicked
    def on_doc_clicked(url):
        print(f"Documentation link clicked: {url}")
        # webbrowser.open(url) is called automatically

    viewer.documentation_link_clicked.connect(on_doc_clicked)

    viewer.show()

    print("Custom LogViewer with Documentation Links Example")
    print("=" * 50)
    print("This example shows how to extend LogModel and LogViewer")
    print("to handle custom log data like documentation links.")
    print()
    print("Features demonstrated:")
    print("- Custom LogModel with docs attribute handler")
    print("- Clickable documentation links in log details")
    print("- Automatic browser opening for documentation")
    print("- Support for single or multiple doc links")
    print("- Exception documentation links via getattr(exc, 'docs', [])")
    print()
    print("Instructions:")
    print("1. Expand any log entry that has documentation links")
    print("2. Click on the blue underlined documentation links")
    print("3. Links will open in your default browser")
    print()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
