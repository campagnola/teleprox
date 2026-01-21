import contextlib
import importlib
import sys

HAVE_QT = None
QT_LIB = None
qt_lib_order = ['PyQt6', 'PySide6', 'PyQt5', 'PySide2']


def check_qt_imported():
    """Check if a Qt library has been imported.

    Returns
    -------
    HAVE_QT : bool | None
        True if a Qt library has been imported, False if none are importable, None if none have been imported yet.
    """
    global HAVE_QT, QT_LIB
    if HAVE_QT is None:
        for qt_lib in qt_lib_order:
            if (
                f'{qt_lib}.QtCore' in sys.modules
                or f'{qt_lib}.QtGui' in sys.modules
                or f'{qt_lib}.QtWidgets' in sys.modules
            ):
                HAVE_QT = True
                QT_LIB = qt_lib
                break
    return HAVE_QT


check_qt_imported()


qt_namespace = None


def import_qt(qt_lib=None):
    """Import a Qt library and return a namespace with its objects."""
    global HAVE_QT, QT_LIB, qt_namespace
    if not HAVE_QT:
        check_qt_imported()

    if HAVE_QT is True and qt_lib is not None and qt_lib != QT_LIB:
        raise ValueError(f'Already imported Qt library: {QT_LIB}')

    if qt_namespace is not None:
        return qt_namespace

    # search all qt libs unless specified
    qt_libs = qt_lib_order if qt_lib is None else [qt_lib]

    # import first available
    if not HAVE_QT:
        HAVE_QT = False
        for qt_lib in qt_libs:
            with contextlib.suppress(ImportError):
                importlib.import_module(f'{qt_lib}.QtCore')
                HAVE_QT = True
                QT_LIB = qt_lib
                break
    if not HAVE_QT:
        raise ImportError(
            f'No importable Qt library found (tried {", ".join(qt_libs)})'
        )

    qt_namespace = {}
    qtcore = importlib.import_module(f'{QT_LIB}.QtCore')
    qt_namespace.update(qtcore.__dict__)
    qtgui = importlib.import_module(f'{QT_LIB}.QtGui')
    qt_namespace.update(qtgui.__dict__)
    qtwidgets = importlib.import_module(f'{QT_LIB}.QtWidgets')
    qt_namespace.update(qtwidgets.__dict__)
    try:
        qttest = importlib.import_module(QT_LIB + '.QtTest')
        qt_namespace.update(qttest.__dict__)
    except ImportError:
        pass  # QtTest might not be available in all distributions

    if 'PySide' not in QT_LIB:
        qt_namespace['Signal'] = qt_namespace[
            'pyqtSignal'
        ]  # for compatibility with PySide

    # PyQt5 vs PyQt6 compatibility: Various Qt enums moved to sub-namespaces
    # Create a Qt namespace class that provides backward compatibility
    class QtCompat:
        """Compatibility wrapper for Qt namespace differences between PyQt5 and PyQt6.

        In PyQt6, many Qt enums were moved from the Qt namespace into sub-namespaces.
        This wrapper provides backward compatibility by searching common sub-namespaces.
        """
        def __init__(self, qt_class):
            self._qt = qt_class
            # List of PyQt6 enum sub-namespaces to search for missing attributes
            self._enum_namespaces = [
                'ItemDataRole',       # UserRole, DisplayRole, etc.
                'ConnectionType',     # QueuedConnection, DirectConnection, etc.
                'AlignmentFlag',      # AlignCenter, AlignLeft, etc.
                'CaseSensitivity',    # CaseInsensitive, CaseSensitive
                'SortOrder',          # AscendingOrder, DescendingOrder
                'Orientation',        # Horizontal, Vertical
                'ScrollBarPolicy',    # ScrollBarAsNeeded, ScrollBarAlwaysOff, etc.
                'ContextMenuPolicy',  # CustomContextMenu, DefaultContextMenu, etc.
                'ItemFlag',           # ItemIsEnabled, ItemIsSelectable, etc.
            ]

        def __getattr__(self, name):
            # First try the direct attribute (PyQt5 style)
            if hasattr(self._qt, name):
                return getattr(self._qt, name)

            # PyQt6: Search enum sub-namespaces
            for ns in self._enum_namespaces:
                if hasattr(self._qt, ns):
                    enum_class = getattr(self._qt, ns)
                    if hasattr(enum_class, name):
                        return getattr(enum_class, name)

            # Otherwise fall through to the original error
            return getattr(self._qt, name)

    qt_namespace['Qt'] = QtCompat(qt_namespace['Qt'])

    # PyQt5 vs PyQt6 compatibility: QSizePolicy enums moved to QSizePolicy.Policy
    class QSizePolicyCompat:
        """Compatibility wrapper for QSizePolicy enum differences between PyQt5 and PyQt6."""
        def __init__(self, qsizepolicy_class):
            self._qsp = qsizepolicy_class

        def __getattr__(self, name):
            # First try the direct attribute (PyQt5 style)
            if hasattr(self._qsp, name):
                return getattr(self._qsp, name)

            # PyQt6: Try Policy sub-namespace for Expanding, Fixed, etc.
            if hasattr(self._qsp, 'Policy') and hasattr(self._qsp.Policy, name):
                return getattr(self._qsp.Policy, name)

            # Otherwise fall through to the original error
            return getattr(self._qsp, name)

        def __call__(self, *args, **kwargs):
            """Allow creating instances of QSizePolicy."""
            return self._qsp(*args, **kwargs)

    qt_namespace['QSizePolicy'] = QSizePolicyCompat(qt_namespace['QSizePolicy'])

    # PyQt5 vs PyQt6 compatibility: Generic wrapper for classes with enum migrations
    def create_enum_compat_wrapper(qt_class, enum_namespaces):
        """Create a compatibility wrapper for a Qt class with enum sub-namespaces.

        Parameters
        ----------
        qt_class : type
            The Qt class to wrap
        enum_namespaces : list of str
            List of enum sub-namespace names to search for missing attributes
        """
        class EnumCompat:
            def __init__(self):
                self._qt_class = qt_class
                self._enum_namespaces = enum_namespaces

            def __getattr__(self, name):
                # First try the direct attribute (PyQt5 style)
                if hasattr(self._qt_class, name):
                    return getattr(self._qt_class, name)

                # PyQt6: Search enum sub-namespaces
                for ns in self._enum_namespaces:
                    if hasattr(self._qt_class, ns):
                        enum_class = getattr(self._qt_class, ns)
                        if hasattr(enum_class, name):
                            return getattr(enum_class, name)

                # Otherwise fall through to the original error
                return getattr(self._qt_class, name)

            def __call__(self, *args, **kwargs):
                """Allow creating instances of the wrapped class."""
                return self._qt_class(*args, **kwargs)

        return EnumCompat()

    # Wrap QAbstractItemView for EditTrigger enums
    qt_namespace['QAbstractItemView'] = create_enum_compat_wrapper(
        qt_namespace['QAbstractItemView'],
        ['EditTrigger', 'SelectionMode', 'SelectionBehavior', 'ScrollHint', 'ScrollMode']
    )

    # Wrap QItemSelectionModel for SelectionFlag enums
    qt_namespace['QItemSelectionModel'] = create_enum_compat_wrapper(
        qt_namespace['QItemSelectionModel'],
        ['SelectionFlag']
    )

    # Wrap QFont for StyleHint enums with special handling for renamed enums
    class QFontCompat:
        """Compatibility wrapper for QFont with enum migrations and renames."""
        def __init__(self):
            self._qt_class = qt_namespace['QFont']
            self._enum_namespaces = ['StyleHint', 'Weight']
            # Map of PyQt5 names -> PyQt6 names for renamed enums
            self._renames = {
                'TypeWriter': 'Monospace',  # QFont.TypeWriter -> QFont.StyleHint.Monospace
            }

        def __getattr__(self, name):
            # First try the direct attribute (PyQt5 style)
            if hasattr(self._qt_class, name):
                return getattr(self._qt_class, name)

            # Check if this is a renamed enum
            if name in self._renames:
                new_name = self._renames[name]
                # Try to find the new name in enum sub-namespaces
                for ns in self._enum_namespaces:
                    if hasattr(self._qt_class, ns):
                        enum_class = getattr(self._qt_class, ns)
                        if hasattr(enum_class, new_name):
                            return getattr(enum_class, new_name)

            # PyQt6: Search enum sub-namespaces
            for ns in self._enum_namespaces:
                if hasattr(self._qt_class, ns):
                    enum_class = getattr(self._qt_class, ns)
                    if hasattr(enum_class, name):
                        return getattr(enum_class, name)

            # Otherwise fall through to the original error
            return getattr(self._qt_class, name)

        def __call__(self, *args, **kwargs):
            """Allow creating instances of QFont."""
            return self._qt_class(*args, **kwargs)

    qt_namespace['QFont'] = QFontCompat()

    # Wrap QSortFilterProxyModel to provide filterRegExp() compatibility
    _original_qsortfilterproxymodel = qt_namespace['QSortFilterProxyModel']

    class QSortFilterProxyModelCompat(_original_qsortfilterproxymodel):
        """QSortFilterProxyModel with PyQt5/6 compatibility for filterRegExp methods."""

        def filterRegExp(self):
            """PyQt5 compatibility method."""
            if hasattr(super(), 'filterRegExp'):
                return super().filterRegExp()
            # PyQt6: convert QRegularExpression to a simple object with pattern() method
            regex = self.filterRegularExpression()
            class RegExpCompat:
                def __init__(self, qregularexpression):
                    self._regex = qregularexpression
                def pattern(self):
                    return self._regex.pattern() if self._regex else ""
            return RegExpCompat(regex)

        def setFilterRegExp(self, pattern):
            """PyQt5 compatibility method."""
            if hasattr(super(), 'setFilterRegExp'):
                return super().setFilterRegExp(pattern)
            # PyQt6: use our helper function
            from teleprox.qt_util import import_qt
            qt_ns = import_qt()
            qt_ns['set_regex_filter'](self, pattern)

    qt_namespace['QSortFilterProxyModel'] = QSortFilterProxyModelCompat

    def make_qapp():
        """Create a QApplication object if one does not already exist.

        Returns
        -------
        app : QApplication
            The QApplication object.
        """
        app = qt_namespace['QApplication'].instance()
        if app is None:
            app = qt_namespace['QApplication']([])
        return app

    qt_namespace['make_qapp'] = make_qapp

    def exec_menu(menu, pos):
        """Execute menu at position (PyQt5/6 compatible).

        Parameters
        ----------
        menu : QMenu
            The menu to execute.
        pos : QPoint
            The position to show the menu at.

        Returns
        -------
        QAction or None
            The selected action, or None if no action was selected.
        """
        try:
            return menu.exec(pos)
        except AttributeError:
            return menu.exec_(pos)

    def exec_app(app):
        """Execute QApplication event loop (PyQt5/6 compatible).

        Parameters
        ----------
        app : QApplication
            The application to execute.

        Returns
        -------
        int
            The exit code.
        """
        try:
            return app.exec()
        except AttributeError:
            return app.exec_()

    def set_regex_filter(proxy_model, pattern):
        """Set regex filter pattern on a QSortFilterProxyModel (PyQt5/6 compatible).

        Parameters
        ----------
        proxy_model : QSortFilterProxyModel
            The proxy model to set the filter on.
        pattern : str
            The regex pattern to filter with. Empty string clears the filter.
        """
        # Check Qt library version, not method existence (our wrapper adds methods to both)
        if 'PyQt6' in QT_LIB or 'PySide6' in QT_LIB:
            # PyQt6/PySide6 - uses QRegularExpression
            regex = qt_namespace['QRegularExpression'](pattern if pattern else "")

            # In PyQt6, case sensitivity must be set on the QRegularExpression, not the proxy
            # Check the proxy's filterCaseSensitivity setting and apply it to the regex
            if hasattr(proxy_model, 'filterCaseSensitivity'):
                case_sensitivity = proxy_model.filterCaseSensitivity()
                # CaseInsensitive = 0, CaseSensitive = 1 in Qt
                if case_sensitivity == qt_namespace['Qt'].CaseInsensitive:
                    # Set case insensitive option (in PatternOption sub-namespace in PyQt6)
                    QRE = qt_namespace['QRegularExpression']
                    if hasattr(QRE, 'PatternOption'):
                        # PyQt6 style
                        regex.setPatternOptions(QRE.PatternOption.CaseInsensitiveOption)
                    else:
                        # PySide6 style (might be different)
                        regex.setPatternOptions(QRE.CaseInsensitiveOption)

            proxy_model.setFilterRegularExpression(regex)
        else:
            # PyQt5/PySide2 - uses QRegExp
            proxy_model.setFilterRegExp(pattern if pattern else "")

    qt_namespace['exec_menu'] = exec_menu
    qt_namespace['exec_app'] = exec_app
    qt_namespace['set_regex_filter'] = set_regex_filter

    return qt_namespace
