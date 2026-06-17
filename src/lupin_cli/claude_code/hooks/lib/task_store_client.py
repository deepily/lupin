"""
Task-store mirror — hook-side REST client for /api/tasks/* (Phase 2).

Stdlib-urllib only (the hook lane carries no third-party HTTP dependency).
Auth is the §4.1 AC2 hook-writer lane: `X-API-Key` read from the host key
file `src/conf/keys/notification-api-claude-code-dev` — the SAME key file
the cascade heartbeat scheduler uses (`DEFAULT_KEY_PATH`). No new auth scheme.

Every call returns a uniform `( ok, status_code, body_dict )` triple and
NEVER raises:

    - ok          : True iff a 2xx response was received and parsed
    - status_code : int HTTP status, or None on transport failure
                    (connect refused / timeout / DNS — the C8 spool trigger)
    - body_dict   : parsed-JSON dict on success; { "error": ... } otherwise

The (status_code is None) case is the ONLY spool trigger — a 4xx/5xx is a
received server verdict, not a transport loss (the mirror orchestrator
decides drop-vs-spool from this distinction; plan §3).

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md §1.5.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

KEY_FILE_RELATIVE = "src/conf/keys/notification-api-claude-code-dev"

# Spine Step-2 (store-count seam) — bounded AGGRESSIVE per-request timeout for the
# owed-count read. The Stop hook fires EVERY turn, so this read is the FIRST
# `:7999` dependency on the Stop hot path; a slow/hung server must never stall
# turn-end (cascade review §C). Deliberately tighter than the mirror's
# DEFAULT_TIMEOUT_SECONDS (3.0s) — a 1s cap keeps the worst case (both owed-status
# queries hang) at ~2s, the §C "≤1-2s" budget. Caller may override per-call.
DEFAULT_OWED_TIMEOUT_SECONDS = 1.0


def read_api_key( environ=None ) -> str:
    """
    Read the hook-writer API key from the host key file.

    Requires:
        - environ is a Mapping or None (None → os.environ)
        - LUPIN_ROOT names the project root containing the key file

    Ensures:
        - Returns the stripped key string
        - Returns "" when LUPIN_ROOT is unset or the file is missing /
          unreadable (DEGRADE-SAFE — the server will 401 an empty key and
          the mirror surfaces that as a non-transport failure; never raises)
    """
    if environ is None:
        environ = os.environ
    lupin_root = environ.get( "LUPIN_ROOT", "" )
    if not lupin_root:
        return ""
    try:
        with open( os.path.join( lupin_root, KEY_FILE_RELATIVE ) ) as f:
            return f.read().strip()
    except OSError:
        return ""


def _request( method, url, api_key, timeout, body=None ):
    """
    Issue one HTTP request and normalize the outcome (internal helper).

    Requires:
        - method is "GET" or "POST"
        - url is a full http(s) URL
        - api_key is a string (may be empty — server 401s it)
        - timeout is a positive float
        - body is a JSON-serializable dict or None

    Ensures:
        - Returns ( ok, status_code, body_dict ) per the module contract
        - NEVER raises: transport errors → ( False, None, {"error": ...} );
          HTTP errors → ( False, <status>, <parsed detail or {"error": ...}> );
          unparseable success body → ( False, <status>, {"error": ...} )
    """
    headers = { "X-API-Key": api_key, "Content-Type": "application/json" }
    data    = json.dumps( body ).encode( "utf-8" ) if body is not None else None
    request = urllib.request.Request( url, data=data, headers=headers, method=method )

    try:
        with urllib.request.urlopen( request, timeout=timeout ) as response:
            status = response.status
            raw    = response.read().decode( "utf-8" )
    except urllib.error.HTTPError as e:
        # A received server verdict (4xx/5xx) — NOT a transport loss.
        try:
            detail = json.loads( e.read().decode( "utf-8" ) )
        except Exception:
            detail = { "error": str( e ) }
        return False, e.code, detail if isinstance( detail, dict ) else { "error": detail }
    except Exception as e:
        # Transport failure (refused / timeout / DNS) — the C8 spool trigger.
        return False, None, { "error": f"{type( e ).__name__}: {e}" }

    try:
        parsed = json.loads( raw )
    except json.JSONDecodeError:
        return False, status, { "error": f"unparseable response body: {raw[:200]!r}" }
    if not isinstance( parsed, dict ):
        return False, status, { "error": f"non-object response body: {parsed!r}" }
    return True, status, parsed


def create_task( settings, api_key, payload ):
    """
    POST /api/tasks.

    Requires:
        - settings is the load_task_store_settings() dict
        - payload is the TaskCreateIn-shaped dict

    Ensures:
        - Returns ( ok, status_code, body ) — body is the serialized item on 201
        - Never raises
    """
    return _request( "POST", f"{settings['api_base_url']}/api/tasks", api_key, settings[ "timeout_seconds" ], body=payload )


def transition_task( settings, api_key, item_id, payload ):
    """
    POST /api/tasks/{item_id}/transition.

    Requires:
        - item_id is the store item uuid string
        - payload is the TaskTransitionIn-shaped dict

    Ensures:
        - Returns ( ok, status_code, body ) — body is { item, event } on 200
        - Never raises
    """
    return _request( "POST", f"{settings['api_base_url']}/api/tasks/{item_id}/transition", api_key, settings[ "timeout_seconds" ], body=payload )


def correlate_task( settings, api_key, item_id, payload ):
    """
    POST /api/tasks/{item_id}/correlate (Phase-2 respawn adoption).

    Requires:
        - item_id is the store item uuid string
        - payload is the TaskCorrelateIn-shaped dict

    Ensures:
        - Returns ( ok, status_code, body ) — body is { item, event } on 200
        - Never raises
    """
    return _request( "POST", f"{settings['api_base_url']}/api/tasks/{item_id}/correlate", api_key, settings[ "timeout_seconds" ], body=payload )


def query_by_correlation_key( settings, api_key, correlation_key ):
    """
    GET /api/tasks?correlation_key=... (spool-replay idempotency probe).

    Requires:
        - correlation_key is a non-empty string

    Ensures:
        - Returns ( ok, status_code, body ) — body is { tasks, count } on 200
        - Never raises
    """
    query = urllib.parse.urlencode( { "correlation_key": correlation_key } )
    return _request( "GET", f"{settings['api_base_url']}/api/tasks?{query}", api_key, settings[ "timeout_seconds" ] )


def query_owed( settings, api_key, owner_persona, statuses, project=None, timeout=None ):
    """
    GET /api/tasks owed-row COUNT for one owner (Spine Step-2 store-count seam).

    The flag-gated replacement for the Stop hook's transcript-replay owed
    source. `GET /api/tasks` filters ONE status per call, so this sums the
    server-computed `count` across each owed status — owed-status row sets are
    tiny, so each query is small and never brushes the endpoint's limit cap.
    Bounded by an AGGRESSIVE per-request timeout (the Stop hook fires every
    turn — a slow `:7999` must never stall turn-end; cascade review §C).

    Requires:
        - settings is the load_task_store_settings() dict (provides api_base_url)
        - api_key is a string (may be empty — server 401s it)
        - owner_persona is the persona string the PostToolUse mirror stamped on
          the rows (lowercased; "unknown" when the bridge had no persona)
        - statuses is an iterable of store status strings (the owed set)
        - project is the resolve_project_name() scope, or None to omit the filter
        - timeout overrides DEFAULT_OWED_TIMEOUT_SECONDS (seconds, per request)

    Ensures:
        - Returns ( ok, count ):
            ok    : True iff EVERY per-status query returned a 2xx whose body
                    carried an integer `count`
            count : the summed owed-row count across `statuses` (0 when ok is
                    False, or when `statuses` is empty)
        - ANY transport failure / non-2xx / malformed body (missing or non-int
          `count`) → ( False, 0 ) — the §C fail-safe: the caller does NOT poke
          on a not-ok read (never guess when the store can't be reached)
        - NEVER raises (rides _request's never-raises seam)
    """
    if timeout is None:
        timeout = DEFAULT_OWED_TIMEOUT_SECONDS

    total = 0
    for status in statuses:
        params = { "owner_persona": owner_persona, "status": status }
        if project:
            params[ "project" ] = project
        query = urllib.parse.urlencode( params )
        ok, _status_code, body = _request(
            "GET", f"{settings['api_base_url']}/api/tasks?{query}", api_key, timeout
        )
        if not ok:
            return False, 0
        count = body.get( "count" )
        # bool is a subclass of int — reject a JSON `true`/`false` count
        # explicitly so it never slips through as 1/0 (house no-defensive rule).
        if isinstance( count, bool ) or not isinstance( count, int ):
            return False, 0
        total += count

    return True, total
