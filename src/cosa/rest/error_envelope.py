"""
Unhandled-exception envelope — make a 500 self-explaining at the CALLER.

WHY THIS MODULE EXISTS (row b101a60b)
-------------------------------------
A mid-refactor save on the `--reload` :7999 briefly served a state where a call
existed and its def did not. Five DMs 500'd and four sessions each spent minutes
diagnosing their OWN side. Two instruments failed to explain it, and neither was
broken:

  · `/health` returned 200 throughout — CORRECTLY. It is a liveness probe whose
    own docstring reads "designed to always succeed", and it answered "is the
    process up?" accurately. Four people asked it "is the server OK?", which is a
    different question it never claimed to answer. It is not the defect and it
    was NOT widened.

  · The 500 body was the 21-byte string "Internal Server Error". With
    `debug=False` and no registered handler, Starlette's default middleware sends
    exactly that — so the exception class was not discarded by the client, it was
    NEVER SENT. The class existed only in the container log, which is precisely
    where nobody diagnosing at the caller was looking.

This module addresses the second one, and only the second one.

WHAT THE ENVELOPE CARRIES, AND WHAT IT DELIBERATELY DOES NOT
------------------------------------------------------------
    detail             unchanged — "Internal Server Error". The envelope ADDS
                       fields; it never takes away what callers already parse.
    exception_class    the "not my problem" signal. A caller reading `NameError`
                       knows in one glance that its own request is not at fault.
    server_started_at  the reload-generation marker, stamped at the app's module
                       import so every reload re-stamps it. A start instant a few
                       seconds old says "you hit a reload window", turning a
                       diagnosis into a read.

    NOT `str(e)`. Ruled 2026-07-21: nobody has audited what an exception message
    exposes on an authenticated fleet, and an unaudited field is not shipped on
    the strength of it probably being fine. The class name plus a fresh start
    instant already carry the entire signal the outage needed; the message
    carries the unmeasured risk. If someone later audits it and wants it, that is
    an ADDITIVE change against a shipped handler — which is the cheap direction.

SCOPE — this handles UNHANDLED exceptions only. A deliberately raised
`HTTPException` keeps FastAPI's own handling and its existing body, untouched.
"""

from fastapi.responses import JSONResponse


def build_error_envelope( exc, server_started_at ):
    """
    Build the JSON-safe body for an unhandled server exception.

    Requires:
        - exc is the raised exception instance
        - server_started_at is an ISO-8601 string captured at app import — NOT
          "now": a value computed per-request would tick forward on every error
          and could never tell a caller that the process had just restarted,
          which is the entire question this field answers

    Ensures:
        - returns a dict with exactly the keys `detail`, `exception_class`,
          `server_started_at`
        - `detail` is the unchanged "Internal Server Error" string
        - the exception MESSAGE never appears in the result (see module docstring)
        - never raises: reads only the exception's type name
    """
    return {
        "detail"            : "Internal Server Error",
        "exception_class"   : type( exc ).__name__,
        "server_started_at" : server_started_at,
    }


def make_unhandled_exception_handler( server_started_at ):
    """
    Build the exception handler to register on the app, binding ONE start instant.

    The instant is bound here rather than read at call time so the value reported
    is provably the one captured at import — a handler reaching for a module
    global would report a plausible timestamp whether or not it was the real one.

    Requires:
        - server_started_at is the ISO-8601 instant captured at app import

    Ensures:
        - returns a callable ( request, exc ) -> JSONResponse with status 500
          carrying build_error_envelope's body
        - the callable ignores `request` entirely; the envelope says nothing about
          which route failed, only what failed and when the process started
    """
    def _handler( request, exc ):
        return JSONResponse(
            status_code = 500,
            content     = build_error_envelope( exc, server_started_at )
        )

    return _handler
