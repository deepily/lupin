"""
Per-request values a v2 door hands down to a job builder without widening every signature.

The one value today is the caller's bearer token. `/api/v2/submit` runs the flow in a worker
thread. A builder that must call back into the server as the caller needs the token. The
mock-job expeditor test is one such builder, because its notifications authenticate with the
user's JWT. The flow's `submit()` signature has a dozen in-process callers, so it is the
wrong place to add a credential parameter. A ContextVar travels into `run_in_threadpool`,
because anyio copies the context. It is scoped to the one request and reads as None when
nothing set it.
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
