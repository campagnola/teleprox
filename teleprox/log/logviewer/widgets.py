# UI widgets for log filtering interface including filter tags and input controls
# Contains FilterTagWidget, FilterInputWidget, and HighlightDelegate for log viewer GUI

from teleprox import qt
from .constants import LogColumns


class SearchWidget(qt.QWidget):
    """Widget for searching through log entries with navigation controls."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Create horizontal layout
        self.layout = qt.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(5)
        self.setLayout(self.layout)
        
        # Search input field with clear button
        self.search_input = qt.QLineEdit()
        self.search_input.setPlaceholderText("Search logs...")
        self.search_input.setClearButtonEnabled(True)
        self.layout.addWidget(self.search_input)
        
        # Navigation controls (hidden by default)
        self.prev_button = qt.QPushButton("←")
        self.prev_button.setFixedSize(30, 25)
        self.prev_button.setToolTip("Previous result")
        self.layout.addWidget(self.prev_button)
        
        self.result_label = qt.QLabel("0/0")
        self.result_label.setAlignment(qt.Qt.AlignCenter)
        self.layout.addWidget(self.result_label)
        
        self.next_button = qt.QPushButton("→")
        self.next_button.setFixedSize(30, 25)
        self.next_button.setToolTip("Next result")
        self.layout.addWidget(self.next_button)
        
        # Hide navigation controls initially
        self._hide_navigation()
        
        # Search state
        self.search_results = []  # List of QModelIndex matches
        self.current_result_index = -1
        self.tree_view = None  # Will be set by parent
        
        # Connect signals
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.prev_button.clicked.connect(self._go_to_previous)
        self.next_button.clicked.connect(self._go_to_next)
    
    def set_tree_view(self, tree_view):
        """Set the tree view that this search widget will operate on."""
        self.tree_view = tree_view
    
    def _on_search_text_changed(self, text):
        """Handle search text changes."""
        if not text.strip():
            self._clear_search()
            return
            
        if not self.tree_view:
            return
            
        # Perform search
        self._perform_search(text.strip())
        
        # Update navigation
        self._update_navigation()
        
        # Go to first result if any
        if self.search_results:
            self.current_result_index = 0
            self._navigate_to_current_result()
    
    def _perform_search(self, search_term):
        """Perform case-insensitive substring search through visible tree items."""
        self.search_results = []
        
        if not self.tree_view or not search_term:
            return
            
        model = self.tree_view.model()
        if not model:
            return
            
        search_term_lower = search_term.lower()
        
        # Search through all visible items recursively
        self._search_recursive(model, qt.QModelIndex(), search_term_lower)
    
    def _search_recursive(self, model, parent_index, search_term_lower):
        """Recursively search through tree items and their children."""
        row_count = model.rowCount(parent_index)
        
        for row in range(row_count):
            # Check each visible column for this row
            match_found = False
            
            # Check visible columns only
            for col in range(model.columnCount()):
                if self.tree_view.isColumnHidden(col):
                    continue
                    
                index = model.index(row, col, parent_index)
                if not index.isValid():
                    continue
                    
                # Get display text and check for match
                text = model.data(index, qt.Qt.DisplayRole)
                if text and search_term_lower in str(text).lower():
                    match_found = True
                    break
            
            # If this row matches, add the timestamp column index (column 0) to results
            if match_found:
                timestamp_index = model.index(row, LogColumns.TIMESTAMP, parent_index)
                if timestamp_index.isValid():
                    self.search_results.append(timestamp_index)
            
            # Recursively search children
            timestamp_index = model.index(row, LogColumns.TIMESTAMP, parent_index)
            if timestamp_index.isValid() and model.rowCount(timestamp_index) > 0:
                self._search_recursive(model, timestamp_index, search_term_lower)
    
    def _update_navigation(self):
        """Update navigation controls based on search results."""
        if not self.search_results:
            self._hide_navigation()
        else:
            self._show_navigation()
            self._update_result_label()
    
    def _navigate_to_current_result(self):
        """Navigate to the current search result."""
        if not self.search_results or self.current_result_index < 0:
            return
            
        if not (0 <= self.current_result_index < len(self.search_results)):
            return
            
        result_index = self.search_results[self.current_result_index]
        
        # Set current index (this works for both top-level and child items)
        self.tree_view.setCurrentIndex(result_index)
        
        # Scroll to make sure it's visible
        self.tree_view.scrollTo(result_index, qt.QAbstractItemView.EnsureVisible)
        
        # Update result label
        self._update_result_label()
    
    def _go_to_previous(self):
        """Navigate to previous search result."""
        if not self.search_results:
            return
            
        self.current_result_index = (self.current_result_index - 1) % len(self.search_results)
        self._navigate_to_current_result()
    
    def _go_to_next(self):
        """Navigate to next search result.""" 
        if not self.search_results:
            return
            
        self.current_result_index = (self.current_result_index + 1) % len(self.search_results)
        self._navigate_to_current_result()
    
    def _update_result_label(self):
        """Update the result counter label."""
        if not self.search_results:
            self.result_label.setText("0/0")
        else:
            current = self.current_result_index + 1  # 1-based for display
            total = len(self.search_results)
            self.result_label.setText(f"{current}/{total}")
    
    def _show_navigation(self):
        """Show navigation controls."""
        self.prev_button.show()
        self.result_label.show()  
        self.next_button.show()
    
    def _hide_navigation(self):
        """Hide navigation controls."""
        self.prev_button.hide()
        self.result_label.hide()
        self.next_button.hide()
    
    def _clear_search(self):
        """Clear search state and hide navigation."""
        self.search_results = []
        self.current_result_index = -1
        self._hide_navigation()


class FilterTagWidget(qt.QLineEdit):
    """Widget representing an active filter with built-in clear button."""
    
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setClearButtonEnabled(True)
        self.textChanged.connect(self.adjust_width)
        self.textChanged.connect(self.check_for_removal)
        self.adjust_width()
        
        # Set size policy to fixed
        self.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
    
    def adjust_width(self):
        """Adjust the width of the line edit to fit its content."""
        font_metrics = self.fontMetrics()
        text_width = font_metrics.horizontalAdvance(self.text())
        self.setFixedWidth(text_width + 30)  # Add padding for clear button
    
    def check_for_removal(self):
        """Remove this widget if text is cleared."""
        if not self.text():
            # Store reference to parent widget to emit signal later
            parent_widget = self.parent()
            # Disconnect signals before removal to prevent issues
            self.textChanged.disconnect()
            self.setParent(None)
            self.deleteLater()
            # Emit signal after removal using timer
            if parent_widget and hasattr(parent_widget, '_emit_filters_changed'):
                qt.QTimer.singleShot(0, parent_widget._emit_filters_changed)


class FilterInputWidget(qt.QWidget):
    """Widget for entering and displaying active filters."""
    
    filters_changed = qt.Signal(list)  # Signal emitted when filters change
    export_all_requested = qt.Signal()  # Signal emitted when "Export All to HTML" is requested
    export_filtered_requested = qt.Signal()  # Signal emitted when "Export Filtered to HTML" is requested
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = qt.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(3)
        self.setLayout(self.layout)
        
        self.filter_input = qt.QLineEdit()
        self.filter_input.setPlaceholderText("Filter  [level: N|debug|info|warn|error] [host: ...] [process: ...] [thread: ...] [source: ...] [logger: ...] [message regex]")
        self.filter_input.returnPressed.connect(self.add_filter)
        self.filter_input.editingFinished.connect(self.add_filter)
        self.filter_input.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
        
        self.layout.addWidget(self.filter_input)
        
        # Track invalid filter tags for visual feedback
        self.invalid_filter_tags = set()
        
        # Add menu button with 3-line icon
        self.menu_button = qt.QPushButton()
        self.menu_button.setText("≡")  # 3-line hamburger menu icon
        self.menu_button.setFixedSize(30, 30)
        self.menu_button.setToolTip("Export options")
        self.menu_button.clicked.connect(self._show_menu)
        
        self.layout.addWidget(self.menu_button)
    
    def add_filter(self):
        text = self.filter_input.text().strip()
        if text:
            filter_tag = FilterTagWidget(text)
            filter_tag.textChanged.connect(self._emit_filters_changed)
            self.layout.insertWidget(self.layout.count() - 2, filter_tag)  # Insert before input and menu button
            self.filter_input.clear()
            self._emit_filters_changed()
    
    def get_filter_strings(self):
        """Return a list of current filter strings."""
        filters = []
        for i in range(self.layout.count() - 2):  # Exclude the input widget and menu button
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, FilterTagWidget):
                filters.append(widget.text())
        return filters
    
    def _emit_filters_changed(self):
        """Emit the filters_changed signal with current filter strings."""
        self.filters_changed.emit(self.get_filter_strings())
    
    def set_invalid_filters(self, invalid_filter_fields):
        """Update visual feedback for invalid filter fields.
        
        Args:
            invalid_filter_fields: List of invalid field names (e.g., ['unknown', 'invalid'])
        """
        # Clear previous invalid markings
        self.invalid_filter_tags.clear()
        
        # Find filter tags that contain invalid field names
        for i in range(self.layout.count() - 2):  # Exclude input and menu button
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, FilterTagWidget):
                filter_text = widget.text().strip()
                # Check if this filter contains an invalid field
                if ':' in filter_text:
                    field = filter_text.split(':', 1)[0].strip().lower()
                    if field in invalid_filter_fields:
                        self.invalid_filter_tags.add(widget)
                        widget.setStyleSheet("QLineEdit { border: 2px solid red; }")
                    else:
                        widget.setStyleSheet("")  # Clear any previous styling
                else:
                    widget.setStyleSheet("")  # Clear styling for non-field filters
    
    def _show_menu(self):
        """Show the export context menu."""
        menu = qt.QMenu(self)
        
        # Export All action
        export_all_action = qt.QAction("Export All to HTML", self)
        export_all_action.setToolTip("Export all log entries to HTML file")
        export_all_action.triggered.connect(self.export_all_requested.emit)
        menu.addAction(export_all_action)
        
        # Export Filtered action
        export_filtered_action = qt.QAction("Export Filtered to HTML", self)
        export_filtered_action.setToolTip("Export currently filtered log entries to HTML file")
        export_filtered_action.triggered.connect(self.export_filtered_requested.emit)
        menu.addAction(export_filtered_action)
        
        # Show menu at button position
        button_pos = self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft())
        menu.exec_(button_pos)


class HighlightDelegate(qt.QStyledItemDelegate):
    """Custom delegate that handles row highlighting based on source/logger matching."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_source = None
        self.selected_logger = None
        
    def set_highlight_criteria(self, source, logger):
        """Set the source and logger to highlight."""
        self.selected_source = source
        self.selected_logger = logger
        
    def clear_highlight(self):
        """Clear highlighting criteria."""
        self.selected_source = None
        self.selected_logger = None
    
    def _get_highlight_color(self, highlight_type, is_child, palette):
        """Get the appropriate highlight color based on type and context."""
        base_color = palette.color(palette.Base)
        is_light_theme = base_color.lightness() > 128
        
        # Base alpha values
        if highlight_type == 'source_logger':
            alpha = 90 if is_light_theme else 110
        else:  # source only
            alpha = 40 if is_light_theme else 60
        
        # Reduce alpha for child items to make them more muted
        if is_child:
            alpha = int(alpha * 0.7)
        
        return qt.QColor(128, 128, 0, alpha)
    
    def _should_highlight(self, source, logger):
        """Determine if given source/logger should be highlighted and return type."""
        if not source or not logger:
            return None
        
        if source == self.selected_source and logger == self.selected_logger:
            return 'source_logger'
        elif source == self.selected_source:
            return 'source'
        
        return None
        
    def paint(self, painter, option, index):
        """Custom paint method that adds highlighting."""
        if self.selected_source is None:
            # No highlighting needed
            super().paint(painter, option, index)
            return
            
        # Get source and logger data directly from current model
        model = index.model()
        row = index.row()
        
        try:
            # Check if this is a child item (has parent)
            parent_index = index.parent()
            if parent_index.isValid():
                # This is a child item - check if parent should be highlighted
                parent_source = model.data(model.index(parent_index.row(), LogColumns.SOURCE), qt.Qt.DisplayRole)
                parent_logger = model.data(model.index(parent_index.row(), LogColumns.LOGGER), qt.Qt.DisplayRole)
                
                highlight_type = self._should_highlight(parent_source, parent_logger)
                if highlight_type:
                    highlight_color = self._get_highlight_color(highlight_type, is_child=True, palette=option.palette)
                    painter.fillRect(option.rect, highlight_color)
                
                # Paint the child item content
                super().paint(painter, option, index)
                return
            
            # This is a top-level item - check for highlighting
            current_source = model.data(model.index(row, LogColumns.SOURCE), qt.Qt.DisplayRole)
            current_logger = model.data(model.index(row, LogColumns.LOGGER), qt.Qt.DisplayRole)
            
            highlight_type = self._should_highlight(current_source, current_logger)
            if highlight_type:
                highlight_color = self._get_highlight_color(highlight_type, is_child=False, palette=option.palette)
                painter.fillRect(option.rect, highlight_color)
        except:
            # If anything fails, just paint normally
            pass
            
        # Paint the item content
        super().paint(painter, option, index)