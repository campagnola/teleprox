# ABOUTME: UI widgets for log filtering interface including filter tags and input controls
# ABOUTME: Contains FilterTagWidget, FilterInputWidget, and HighlightDelegate for log viewer GUI

from teleprox import qt


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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = qt.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(3)
        self.setLayout(self.layout)
        
        self.filter_input = qt.QLineEdit()
        self.filter_input.setPlaceholderText("Filter  [level: N|debug|info|warn|error] [source: ...] [logger: ...] [message regex]")
        self.filter_input.returnPressed.connect(self.add_filter)
        self.filter_input.editingFinished.connect(self.add_filter)
        self.filter_input.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
        
        self.layout.addWidget(self.filter_input)
    
    def add_filter(self):
        text = self.filter_input.text().strip()
        if text:
            filter_tag = FilterTagWidget(text)
            filter_tag.textChanged.connect(self._emit_filters_changed)
            self.layout.insertWidget(self.layout.count() - 1, filter_tag)
            self.filter_input.clear()
            self._emit_filters_changed()
    
    def get_filter_strings(self):
        """Return a list of current filter strings."""
        filters = []
        for i in range(self.layout.count() - 1):  # Exclude the input widget
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, FilterTagWidget):
                filters.append(widget.text())
        return filters
    
    def _emit_filters_changed(self):
        """Emit the filters_changed signal with current filter strings."""
        self.filters_changed.emit(self.get_filter_strings())


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
        
    def paint(self, painter, option, index):
        """Custom paint method that adds highlighting."""
        if self.selected_source is None:
            # No highlighting needed
            super().paint(painter, option, index)
            return
            
        # Get source and logger data directly from current model (no complex mapping needed)
        model = index.model()
        row = index.row()
        
        try:
            # Get data directly from the current model using data() method
            current_source = model.data(model.index(row, 1), qt.Qt.DisplayRole)
            current_logger = model.data(model.index(row, 2), qt.Qt.DisplayRole)
            
            if current_source and current_logger:
                
                # Determine if this row should be highlighted
                highlight_type = None
                if current_source == self.selected_source and current_logger == self.selected_logger:
                    highlight_type = 'source_logger'
                elif current_source == self.selected_source:
                    highlight_type = 'source'
                
                # Apply highlighting by modifying the option
                if highlight_type:
                    # Get base color for theme detection
                    palette = option.palette
                    base_color = palette.color(palette.Base)
                    
                    # Create highlight colors based on theme
                    if base_color.lightness() > 128:  # Light theme
                        if highlight_type == 'source_logger':
                            highlight_color = qt.QColor(255, 255, 0, 60)  # Stronger yellow
                        else:
                            highlight_color = qt.QColor(255, 255, 0, 30)  # Light yellow
                    else:  # Dark theme
                        if highlight_type == 'source_logger':
                            highlight_color = qt.QColor(255, 255, 0, 80)  # Stronger yellow
                        else:
                            highlight_color = qt.QColor(255, 255, 0, 40)  # Muted yellow
                    
                    # Draw custom background
                    painter.fillRect(option.rect, highlight_color)
        except:
            # If anything fails, just paint normally
            pass
            
        # Paint the item content
        super().paint(painter, option, index)