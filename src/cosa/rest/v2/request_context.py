"""
Per-request values a v2 door hands DOWN to a job builder without widening every signature.

The one value today is the caller's bearer token. `/api/v2/submit` runs the flow in a worker
thread; a builder that has to call back into the server AS THE CALLER — the mock-job
expeditor test, whose notifications authenticate with the user's JWT — needs it, and the
flow's `submit()` signature (used by a dozen in-process callers) is the wrong place to grow a
credential parameter. A ContextVar travels into `run_in_threadpool` (anyio copies the
context), is scoped to the one request, and reads as None when nothing set it.
"""

from contextvars import ContextVar

_BEARER_TOKEN = ContextVar( "v2_bearer_token", default=None )


def set_bearer_token( token ):
    """
    Requires:
        - token is the caller's raw JWT, or None

    Ensures:
        - returns the ContextVar token to hand to reset_bearer_token
    """
    return _BEARER_TOKEN.set( token )


def reset_bearer_token( reset_token ):
    """Undo set_bearer_token for this context."""
    _BEARER_TOKEN.reset( reset_token )


def get_bearer_token():
    """
    Ensures:
        - returns the caller's raw JWT for this request, or None when none was set
    """
    return _BEARER_TOKEN.get()
