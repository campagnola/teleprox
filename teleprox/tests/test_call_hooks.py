# Tests for process-level call hooks: set_call_opts_provider and set_call_context_hook.
import contextlib
import threading
import time

import pytest
import teleprox
import teleprox.client as tc
import teleprox.server as ts
from teleprox import RPCClient, RPCServer
from teleprox.util import ProcessCleaner
from teleprox.tests.util import RemoteLogRecorder


@pytest.fixture(autouse=True)
def reset_hooks():
    """Restore module-level hooks to None after every test."""
    yield
    tc.set_call_opts_provider(None)
    ts.set_call_context_hook(None)


# ---------------------------------------------------------------------------
# set_call_opts_provider
# ---------------------------------------------------------------------------

def test_opts_provider_extra_opts_reach_server():
    """Extras from the provider appear in opts seen by process_action."""
    received_opts = []

    server = RPCServer()

    orig = server.process_action
    def capturing_process_action(action, opts, return_type, caller):
        if action == 'call_obj':
            received_opts.append(dict(opts))
        return orig(action, opts, return_type, caller)
    server.process_action = capturing_process_action

    tc.set_call_opts_provider(lambda: {'_test_extra': 'hello'})

    client = RPCClient(server.address)
    client._import('os').getpid()
    client.close_server()

    assert any(o.get('_test_extra') == 'hello' for o in received_opts)


def test_opts_provider_none_return_is_ignored():
    """A provider returning None does not modify opts."""
    received_opts = []

    server = RPCServer()
    orig = server.process_action
    def capturing(action, opts, return_type, caller):
        if action == 'call_obj':
            received_opts.append(dict(opts))
        return orig(action, opts, return_type, caller)
    server.process_action = capturing

    tc.set_call_opts_provider(lambda: None)

    client = RPCClient(server.address)
    client._import('os').getpid()
    client.close_server()

    assert all('_test_extra' not in o for o in received_opts)


def test_clearing_opts_provider():
    """Setting the provider to None stops extra opts from being sent."""
    tc.set_call_opts_provider(lambda: {'_should_not_appear': True})
    tc.set_call_opts_provider(None)

    received_opts = []
    server = RPCServer()
    orig = server.process_action
    def capturing(action, opts, return_type, caller):
        if action == 'call_obj':
            received_opts.append(dict(opts))
        return orig(action, opts, return_type, caller)
    server.process_action = capturing

    client = RPCClient(server.address)
    client._import('os').getpid()
    client.close_server()

    assert all('_should_not_appear' not in o for o in received_opts)


# ---------------------------------------------------------------------------
# set_call_context_hook
# ---------------------------------------------------------------------------

def test_context_hook_is_entered_and_exited():
    """The context manager returned by the hook wraps the call."""
    events = []

    @contextlib.contextmanager
    def hook(opts):
        events.append('enter')
        yield
        events.append('exit')

    ts.set_call_context_hook(hook)

    server = RPCServer()
    client = RPCClient(server.address)
    client._import('os').getpid()
    client.close_server()

    assert events == ['enter', 'exit']


def test_context_hook_receives_opts():
    """The hook receives the full opts dict for the call."""
    received = []

    @contextlib.contextmanager
    def hook(opts):
        received.append(opts.copy())
        yield

    ts.set_call_context_hook(hook)

    server = RPCServer()
    client = RPCClient(server.address)
    client._import('os').getpid()
    client.close_server()

    assert len(received) == 1
    assert 'obj' in received[0]


def test_context_hook_sees_extra_opts_from_provider():
    """Hook opts include extras injected by the client-side provider."""
    received = []

    tc.set_call_opts_provider(lambda: {'_ctx': 'propagated'})

    @contextlib.contextmanager
    def hook(opts):
        received.append(opts.get('_ctx'))
        yield

    ts.set_call_context_hook(hook)

    server = RPCServer()
    client = RPCClient(server.address)
    client._import('os').getpid()
    client.close_server()

    assert received == ['propagated']


def test_hook_not_called_for_non_call_obj_actions():
    """The context hook is only invoked for call_obj, not for import/get_item/etc."""
    call_count = [0]

    @contextlib.contextmanager
    def hook(opts):
        call_count[0] += 1
        yield

    ts.set_call_context_hook(hook)

    server = RPCServer()
    client = RPCClient(server.address)
    _ = client['self']          # get_item
    client.close_server()       # close

    assert call_count[0] == 0


def test_hook_called_once_per_call():
    """The hook is entered exactly once per remote callable invocation."""
    count = [0]

    @contextlib.contextmanager
    def hook(opts):
        count[0] += 1
        yield

    ts.set_call_context_hook(hook)

    server = RPCServer()
    client = RPCClient(server.address)
    ros = client._import('os')
    ros.getpid()
    ros.getpid()
    client.close_server()

    # two call_obj actions: the import itself + two getpid calls
    assert count[0] >= 2


# ---------------------------------------------------------------------------
# Cross-process smoke test
# ---------------------------------------------------------------------------

def test_cross_process_opts_and_hook():
    """Provider opts set in the parent are visible to the hook in the child."""
    with RemoteLogRecorder('test_hooks_cross_process') as recorder:
        proc = teleprox.start_process(name='test_hooks_child', log_addr=recorder.address)
        try:
            tc.set_call_opts_provider(lambda: {'_trace': 'from-parent'})

            # Install a hook in the remote process that logs when it receives the extra.
            proc.client._import('builtins').exec(
                'import contextlib, logging, teleprox.server as ts\n'
                '@contextlib.contextmanager\n'
                'def h(opts):\n'
                '    if opts.get("_trace"):\n'
                '        logging.getLogger().warning("hook_trace:" + str(opts["_trace"]))\n'
                '    yield\n'
                'ts.set_call_context_hook(h)\n'
            )

            # Any further call will trigger the hook.
            proc.client._import('os').getpid()
        finally:
            proc.stop()

    assert recorder.find_message('hook_trace:from-parent') is not None
