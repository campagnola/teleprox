import pytest
import teleprox
from teleprox.util import ProcessCleaner


def test_proxy_getattr_setattr():
    with ProcessCleaner() as cleaner:
        proc = teleprox.start_process(name='test_proxy_getattr_setattr')
        cleaner.add(proc)

        ros = proc.client._import('os')
        with pytest.raises(teleprox.RemoteCallException):
            ros.nonexistent['x']

        with pytest.raises(teleprox.RemoteCallException):
            ros.nonexistent['x'] = 1

        proc.stop()


def test_proxy_del_infinite_recursion():
    """Test that ObjectProxy.__del__ doesn't cause infinite recursion when auto_delete=True"""
    import pickle
    import gc
    import sys
    import io

    # Capture stderr to check for infinite recursion
    old_stderr = sys.stderr
    captured_stderr = io.StringIO()
    sys.stderr = captured_stderr

    try:
        with ProcessCleaner() as cleaner:
            proc = teleprox.start_process(name='test_proxy_del')
            cleaner.add(proc)

            # Create a proxy with auto_delete=True
            remote_builtins = proc.client._import('builtins')
            remote_builtins._set_proxy_options(auto_delete=True)

            # Verify the setting took effect
            assert remote_builtins._proxy_options['auto_delete'] == True

            # Try to serialize and deserialize the proxy
            # This triggers the bug - the proxy gets into a broken state
            pickled = pickle.dumps(remote_builtins)

            # This will fail due to missing local_server parameter
            # But during the failure, infinite recursion happens in __del__
            try:
                deserialized_proxy = pickle.loads(pickled)
            except TypeError:
                pass  # Expected failure

            proc.stop()

        # Force garbage collection to trigger any remaining __del__ calls
        gc.collect()

    finally:
        # Restore stderr
        sys.stderr = old_stderr

    # Check captured stderr for evidence of infinite recursion
    stderr_output = captured_stderr.getvalue()

    # The test should pass if we do NOT detect infinite recursion (bug is fixed)
    # Look for the recursive pattern in the output using regex to be robust against line number changes
    import re

    has_recursion = (
        'RecursionError: maximum recursion depth exceeded' in stderr_output
        or re.search(r'proxy\.py.*in __getattr__', stderr_output)
        or re.search(r'proxy\.py.*in _deferred_attr', stderr_output)
    )

    assert (
        not has_recursion
    ), f"Detected infinite recursion in stderr - the bug still exists: {stderr_output[:1000]}..."
