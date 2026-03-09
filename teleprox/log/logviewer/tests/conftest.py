from teleprox.tests.check_qt import qt_available, qt_reason

def pytest_ignore_collect(collection_path, config):
    # Skip all logviewer tests if qt is not available
    if not qt_available:
        return True
    
    return False

# prefer this, but some tests can't even be collected if qt is not available
# def pytest_collection_modifyitems(config, items):
#     # Skip all logviewer tests if Qt is not available
#     if not qt_available:
#         for item in items:
#             item.add_marker(pytest.mark.skip(reason=qt_reason))
