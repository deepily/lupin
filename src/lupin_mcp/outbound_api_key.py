"""
Outbound X-API-Key loader for MCP-server HTTP calls to the Lupin REST API
(`/api/dm/*`, `/api/tasks/*`).

Why this module exists — the silent-swallow defect
--------------------------------------------------
The loader used to be a bare `try: return du.get_api_key(...) except Exception:
return None` inline in `cosa_voice_mcp.py`. Every failure mode — file absent,
file unreadable, LUPIN_ROOT wrong — collapsed to the same `None`, and every
caller reported the same blank string: "MCP outbound X-API-Key unavailable".

On `lupin-host-test` (2026-07-25) the key file was present but mode `600` owned
by uid 1001, while the MCP server ran as a different uid. `os.path.exists()`
answered True, `open()` raised `PermissionError`, the bare `except` erased it,
and `dm_send` / `dm_list` reported `missing_auth_header` with no path, no mode,
and no errno. The permission was a one-line `chmod`; finding it was not.

So this module keeps the RETURN contract identical (a key string or None —
callers are unchanged) and adds a parallel DIAGNOSIS channel: the last failure
is recorded and rendered into the `detail` field callers already emit.
"""

import os
from typing import Optional

# The single long-lived `ck_live_*` API key shared by the notification
# infrastructure, the embedding HTTP endpoints, and this MCP server's outbound
# calls. Named once here so the preflight in `install-cosa-voice.sh` and the
# diagnosis text below cannot drift apart.
KEY_NAME = "notification-api-claude-code-dev"

# Last load failure, as a human-readable clause naming the concrete cause.
# None means "the last load succeeded (or has not been attempted)".
_last_failure: Optional[ str ] = None


def _key_path() -> str:
    """
    Absolute path the key is read from, per the project-root mandate.

    Ensures:
        - returns `<project_root>/src/conf/keys/<KEY_NAME>`
        - returns a "<unresolvable...>" sentinel string rather than raising when
          the project root itself cannot be resolved (this is a diagnosis path;
          it must never be the thing that throws)
    """
    try:
        import cosa.utils.util as du
        return f"{du.get_project_root()}/src/conf/keys/{KEY_NAME}"
    except Exception as e:
        return f"<unresolvable project root: {type( e ).__name__}: {e}>"


def _diagnose( path: str, exc: Optional[ Exception ] ) -> str:
    """
    Build the failure clause for a key that could not be loaded.

    Requires:
        - path is the absolute key path that was attempted
        - exc is the exception raised while reading, or None when the read
          returned no key without raising

    Ensures:
        - names the path in every case
        - when the file is absent, says so
        - when the file exists but is unreadable, reports its mode and owner uid
          alongside the OS error — the `chmod`/`chown` facts, not a guess
        - never raises
    """
    try:
        if not os.path.exists( path ):
            return f"key file not found at {path}"

        if not os.access( path, os.R_OK ):
            try:
                st   = os.stat( path )
                mode = oct( st.st_mode & 0o777 )[ 2: ]
                return (
                    f"key file {path} is not readable by this process "
                    f"(uid {os.getuid()}): mode {mode}, owner uid {st.st_uid}"
                )
            except OSError as stat_err:
                return f"key file {path} is not readable and cannot be stat'ed: {stat_err}"

        if exc is not None:
            return f"key file {path} failed to load: {type( exc ).__name__}: {exc}"

        # Readable, no exception. Distinguish a genuinely empty/whitespace file
        # from "the caller handed us a None key it never loaded here" — reporting
        # the second as the first is a false lead, which is the whole defect this
        # module exists to stop.
        if not open( path ).read().strip():
            return f"key file {path} is readable but empty"

        return (
            f"key file {path} is present and readable — no load failure was recorded, "
            f"so the None key did not originate from this loader"
        )

    except Exception as e:                                   # pragma: no cover - diagnosis must never throw
        return f"key {KEY_NAME} unavailable; diagnosis itself failed: {type( e ).__name__}: {e}"


def load_outbound_api_key() -> Optional[ str ]:
    """
    Load the X-API-Key used for MCP-server outbound HTTP calls.

    Reads `<project_root>/src/conf/keys/<KEY_NAME>` via the project-wide
    `du.get_api_key()` helper — the same key the embedding HTTP endpoints and
    the notification auth infrastructure use.

    Ensures:
        - returns the key string when the file is readable and non-empty
        - returns None on any failure, and records a concrete diagnosis
          retrievable via `outbound_key_failure_detail()`
        - clears the recorded diagnosis on success, so a stale clause can never
          be reported against a later working load
        - never raises
    """
    path = _key_path()
    global _last_failure

    try:
        import cosa.utils.util as du
        key = du.get_api_key( KEY_NAME )
    except Exception as e:
        _last_failure = _diagnose( path, e )
        return None

    if not key:
        _last_failure = _diagnose( path, None )
        return None

    _last_failure = None
    return key


def outbound_key_failure_detail( endpoint: str ) -> str:
    """
    Render the `detail` string for a `missing_auth_header` error dict.

    Requires:
        - endpoint is the REST path the caller could not reach (e.g. "/api/dm/send")

    Ensures:
        - returns "cannot reach <endpoint>: <concrete cause>" when a diagnosis
          was recorded by the most recent `load_outbound_api_key()` call
        - falls back to a fresh diagnosis when none was recorded (a caller that
          was handed a None key it did not load itself)
        - never raises
    """
    cause = _last_failure if _last_failure is not None else _diagnose( _key_path(), None )
    return f"MCP outbound X-API-Key unavailable; cannot reach {endpoint}: {cause}"
