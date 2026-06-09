# Tests for automatic gentletask throughline propagation across the teleprox boundary.
# Verifies that a caller's throughline frames are serialized into call opts and
# re-established on the server before the remote callable runs.
import contextlib

import pytest

import teleprox
import teleprox.client as tc
import teleprox.server as ts
from teleprox import RPCClient, RPCServer
from teleprox.tests.util import RemoteLogRecorder

gentletask = pytest.importorskip("gentletask")
from teleprox import throughline as tl  # noqa: E402  (imported after skip guard)


@pytest.fixture(autouse=True)
def propagation_enabled():
    """Opt in to throughline propagation for the test, then tear it down.

    Propagation is opt-in (no import-time auto-wiring), so each test enables it
    explicitly here and disables it afterward, leaving the global provider/hook
    slots clear for other tests.
    """
    tl.enable_throughline_propagation()
    yield
    tl.disable_throughline_propagation()


# ---------------------------------------------------------------------------
# Provider: client serializes its current throughline frames into opts
# ---------------------------------------------------------------------------


def test_provider_serializes_current_frames():
    """The opts provider emits the caller's current throughline frames."""
    with gentletask.throughline(name="outer"), gentletask.throughline(name="inner"):
        opts = tc._call_opts_provider()
    assert opts[tl.OPTS_KEY] == ({"name": "outer"}, {"name": "inner"})


def test_provider_returns_none_without_frames():
    """Outside any throughline frame, the provider contributes nothing."""
    opts = tc._call_opts_provider()
    assert not opts


# ---------------------------------------------------------------------------
# Hook: server re-establishes frames before the call runs
# ---------------------------------------------------------------------------


def test_hook_reestablishes_frames():
    """The context hook installs the transferred frames onto the server throughline."""
    seen = []
    cm = ts._call_context_hook({tl.OPTS_KEY: ({"name": "a"}, {"name": "b"})})
    with cm:
        seen.append(gentletask.task_chain())
    assert seen == [("a", "b")]
    # Frames are torn down on exit.
    assert gentletask.task_chain() == ()


def test_hook_replaces_rather_than_appends_server_frames():
    """restore() HIDES the server's own pre-existing frames (replace, not append).

    The previous ExitStack implementation appended, leaving the server's frames
    visible beneath the transferred ones; restore() replaces for the duration of
    the call and resets on exit.
    """
    with gentletask.throughline(name="server_local"):
        cm = ts._call_context_hook({tl.OPTS_KEY: ({"name": "from_client"},)})
        with cm:
            # Only the transferred frame is visible; the server's own is hidden.
            assert gentletask.task_chain() == ("from_client",)
        # The server's own frame is restored after the call.
        assert gentletask.task_chain() == ("server_local",)


def test_hook_without_frames_is_noop():
    """Opts lacking the throughline key leave the server throughline untouched."""
    cm = ts._call_context_hook({"obj": object()})
    with cm:
        assert gentletask.task_chain() == ()


# ---------------------------------------------------------------------------
# In-process round trip (provider -> hook)
# ---------------------------------------------------------------------------


def test_provider_to_hook_roundtrip():
    """Frames emitted by the provider re-establish identically through the hook."""
    with gentletask.throughline(name="op"), gentletask.throughline(name="step"):
        opts = tc._call_opts_provider()

    chain = []
    with ts._call_context_hook(opts):
        chain.append(gentletask.task_chain())
    assert chain == [("op", "step")]


# ---------------------------------------------------------------------------
# Cross-process: the child's throughline shows the parent's ancestry
# ---------------------------------------------------------------------------


def test_cross_process_throughline_ancestry():
    """A remote call run under a parent throughline sees the full ancestry in the child.

    Propagation is opt-in, so both ends must enable it: the parent (provider)
    via the autouse fixture, and the child (hook) via an explicit remote call
    into the child's own ``teleprox.throughline.enable_throughline_propagation``
    before the asserted call.  The child defines a helper that logs its
    task_chain; called under the parent's frames, it should report them.
    """
    with RemoteLogRecorder("test_throughline_xproc") as recorder:
        proc = teleprox.start_process(
            name="test_throughline_child", log_addr=recorder.address
        )
        try:
            # Enable propagation in the child so its server installs the context
            # hook.  teleprox has no per-child init seam, so we drive it as a
            # remote call before the call we assert on.
            proc.client._import("teleprox.throughline").enable_throughline_propagation()

            # Define a remote function that logs the throughline it is running under.
            proc.client._import("builtins").exec(
                "def _report_chain():\n"
                "    import logging, gentletask\n"
                "    logging.getLogger().warning('chain:' + ','.join(gentletask.task_chain()))\n"
                "import builtins as _b; _b._report_chain = _report_chain\n"
            )
            report = proc.client._import("builtins")._report_chain
            with gentletask.throughline(name="parent_op"), gentletask.throughline(
                name="parent_step"
            ):
                report()
        finally:
            proc.stop()

    assert recorder.find_message("chain:parent_op,parent_step") is not None
