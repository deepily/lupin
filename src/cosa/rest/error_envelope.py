"""
Unhandled-exception envelope — make a 500 self-explaining at the caller.

Why this module exists
----------------------
A mid-refactor save on the `--reload` :7999 can serve a state where a call exists
and its def does not. Every caller then gets a 500 and must diagnose its own side.
Two instruments fail to explain that, and neither is broken.

  · `/health` returns 200 throughout, correctly. It is a liveness probe that answers
    "is the process up?" accurately. "Is the server OK?" is a different question
    it never claimed to answer, so it is not widened.

  · The 500 body is the 21-byte string "Internal Server Error". With `debug=False`
    and no registered handler, Starlette's default middleware sends exactly that.
    The exception class is never sent, so it exists only in the container log,
    where nobody diagnosing at the caller is looking.

This module addresses the second one, and only the second one.

What the envelope carries, and what it leaves out
-------------------------------------------------
    - detail: unchanged — "Internal Server Error". The envelope adds
      fields; it never takes away what callers already parse.
    - exception_class: the "not my problem" signal. A caller reading `NameError`
      knows in one glance that its own request is not at fault.
    - server_started_at: the reload-generation marker, stamped at the app's module
      import so every reload re-stamps it. A start instant a few
      seconds old says "you hit a reload window".

    Not `str(e)`. Nobody has audited what an exception message exposes on an
    authenticated fleet. An unaudited field is not shipped on the strength of
    it probably being fine. The class name plus a fresh start instant carry the
    whole signal; the message carries the unmeasured risk. Adding it later is an
    additive change against a shipped handler, which is the cheap direction.

Scope: this handles unhandled exceptions only. A raised `HTTPException` keeps
FastAPI's own handling and its existing body, untouched.
"""

from fastapi.responses import JSONResponse


def build_error_envelope( exc, server_started_at ):
    """
    Build the JSON-safe body for an unhandled server exception.

    Requires:
        - exc is the raised exception instance
        - server_started_at is an ISO-8601 string captured at app import — not
          "now": a value computed per-request would tick forward on every error
          and could never tell a caller that the process had just restarted,
          which is the entire question this field answers

    Ensures:
        - returns a dict with exactly these keys: `detail`, `exception_class`,
          `server_started_at`
        - `detail` is the unchanged "Internal Server Error" string
        - the exception message never appears in the result (see module docstring)
        - never raises: reads only the exception's type name
    """
    return {
        "detail"            : "Internal Server Error",
        "exception_class"   : type( exc ).__name__,
        "server_started_at" : server_started_at,
    }


def make_unhandled_exception_handler( server_started_at ):
    """
    Build the exception handler to register on the app, binding one start instant.

    The instant is bound here rather than read at call time. The reported value is
    then provably the one captured at import. A handler reaching for a module global
    would report a plausible timestamp whether or not it was the real one.

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
