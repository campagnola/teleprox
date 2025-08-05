# ABOUTME: UI widgets for log filtering interface including filter tags and input controls
# ABOUTME: Contains FilterTagWidget, FilterInputWidget, and HighlightDelegate for log viewer GUI

from teleprox import qt
from .constants import ItemDataRole, LogColumns


class HyperlinkTreeView(qt.QTreeView):
    """Custom QTreeView that shows pointer cursor over hyperlink portions of traceback lines."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
    
    def mouseMoveEvent(self, event):
        """Override mouse move to change cursor over hyperlinks."""
        index = self.indexAt(event.pos())
        cursor = qt.Qt.ArrowCursor  # Default cursor
        
        if index.isValid():
            # Get the item data to check if it's a clickable code line
            model = self.model()
            
            # Map to source model if using proxy
            source_index = index
            if hasattr(model, 'mapToSource'):
                source_index = model.mapToSource(index)
            
            # Get the actual item from the source model
            if hasattr(self.parent(), 'model') and hasattr(self.parent().model, 'itemFromIndex'):
                item = self.parent().model.itemFromIndex(source_index)
                if item:
                    data = item.data(ItemDataRole.PYTHON_DATA)
                    if (data and isinstance(data, dict) and 
                        data.get('type') in ['traceback_frame', 'stack_frame'] and
                        data.get('frame_parts', {}).get('has_file_ref')):
                        cursor = qt.Qt.PointingHandCursor
        
        self.setCursor(cursor)
        super().mouseMoveEvent(event)


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