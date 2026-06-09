# Propagation of gentletask's throughline (semantic task narrative) across the
# teleprox process boundary, built on the call-opts provider / context-hook seam.
#
# When enabled, a client serializes its current throughline frames into each
# outgoing call's opts; the server re-establishes those frames on its own
# throughline singleton for the duration of the call, so task_chain() and
# log filters on the remote side show the full ancestry of the operation.
#
# gentletask is an optional dependency: if it is not importable, enabling
# propagation is a no-op and teleprox behaves exactly as before.
#
# Propagation is OPT-IN. Nothing happens at import; a process must call
# ``enable_throughline_propagation()`` explicitly, once, to wire it up. Because
# the client opts-provider and server context-hook are PROCESS-GLOBAL single
# slots (teleprox's ``set_call_opts_provider`` / ``set_call_context_hook``
# seam), enabling propagation here claims those slots and is therefore mutually
# exclusive with any other code that registers its own provider/hook. To get
# end-to-end propagation, BOTH the client process AND any server/child process
# that should re-establish the context must call
# ``enable_throughline_propagation()``.
import contextlib

try:
    import gentletask
except ImportError:  # pragma: no cover - exercised only when gentletask is absent
    gentletask = None

from . import client as _client
from . import server as _server

# Opts key under which the serialized throughline frames travel. Frames are a
# tuple of plain ``{'name': ...}`` dicts (see SemanticStack.frames()), which the
# default serializers handle directly.
OPTS_KEY = "_throughline_frames"


def _opts_provider():
    """Provider for set_call_opts_provider: emit the caller's throughline frames.

    Returns an empty dict when there are no frames so the merge in
    ``RPCClient.call_obj`` adds nothing.
    """
    if gentletask is None:
        return None
    frames = gentletask.throughline.frames()
    if not frames:
        return {}
    return {OPTS_KEY: frames}


@contextlib.contextmanager
def _context_hook(opts):
    """Hook for set_call_context_hook: re-establish transferred frames, if any.

    Replays the transferred frames onto the server's throughline for the
    duration of the wrapped call via ``throughline.restore()``, then resets.
    Calls that carried no frames (or when gentletask is unavailable) run under
    an unchanged throughline.

    ``restore()`` bypasses the ``required``-key validation that ``throughline``
    enforces on entry, so propagation no longer depends on the client and
    server agreeing on identical ``required`` sets.

    NOTE: restore() REPLACES the stack for the block rather than appending to
    it -- any throughline frames the server already had on this thread are
    HIDDEN for the call duration and restored on exit. The previous
    implementation appended (the server's own frames remained visible beneath
    the transferred ones).
    """
    frames = opts.get(OPTS_KEY) if opts else None
    if gentletask is None or not frames:
        yield
        return
    with gentletask.throughline.restore(frames):
        yield


def enable_throughline_propagation():
    """Wire throughline propagation into this process's client and server.

    Registers the opts provider (client side) and context hook (server side).
    A no-op if gentletask is not installed. Safe to call repeatedly.

    Must be called EXPLICITLY (propagation is opt-in; it is not enabled at
    import). Call it ONCE per process. For end-to-end propagation it must run
    in BOTH the client process and any server/child process that should
    re-establish the transferred context.

    This claims the process-global single provider/hook slots and is therefore
    mutually exclusive with any other user of teleprox's
    ``set_call_opts_provider`` / ``set_call_context_hook`` seam.
    """
    if gentletask is None:
        return
    _client.set_call_opts_provider(_opts_provider)
    _server.set_call_context_hook(_context_hook)


def disable_throughline_propagation():
    """Remove throughline propagation hooks installed by enable_*.

    Clears the provider and hook only if they are the ones we installed, so a
    user who registered their own provider/hook is left untouched.
    """
    if _client._call_opts_provider is _opts_provider:
        _client.set_call_opts_provider(None)
    if _server._call_context_hook is _context_hook:
        _server.set_call_context_hook(None)
