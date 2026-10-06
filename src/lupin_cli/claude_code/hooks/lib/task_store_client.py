"""
Task-store mirror: hook-side REST client for /api/tasks/* (Phase-2).

Stdlib-urllib only (the hook lane carries no third-party HTTP dependency).
Auth is the hook-writer lane: `X-API-Key` read from the host key file
`src/conf/keys/notification-api-claude-code-dev`. It is the same key file
the cascade heartbeat scheduler uses (`DEFAULT_KEY_PATH`). No new auth scheme.

Every call returns a uniform `( ok, status_code, body_dict )` triple and
never raises:

    - ok          : True iff a 2xx response was received and parsed
    - status_code : int HTTP status, or None on transport failure
                    (connect refused / timeout / DNS — the spool trigger)
    - body_dict   : parsed-JSON dict on success; { "error": ... } otherwise

The (status_code is None) case is the only spool trigger. A 4xx/5xx is a
received server verdict, not a transport loss. The mirror orchestrator
decides drop-vs-spool from this distinction.

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md
"""

import http.client
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
#
# 🔴 DELIBERATELY EXCLUDED FROM THE ~30s RELOAD-WINDOW BUMP (row 204911ca,
# 2026-07-20). Every other out-of-process `:7999` client in this repo was raised
# to _SERVER_TRANSPORT_TIMEOUT_SECONDS (30) so it can outlast a `uvicorn
# --reload` window. These two constants were left SHORT on purpose, and the
# reason is not oversight:
#
#   - This read is on the Stop hot path and fires EVERY turn. A 30s budget would
#     stall turn-end by 30s for the duration of any reload — paid by every
#     session on the box, every turn, to rescue a single write.
#   - It does not need rescuing. Transport failure here is the C8 SPOOL trigger:
#     the write degrades to the spool and is reconciled later, rather than being
#     lost. That is the correct shape for a hot-path call, and a longer budget
#     would trade a cheap, already-handled degradation for a universal stall.
#
# So the short budget is LOAD-BEARING, not a leftover. If you are here because a
# grep for reload-window exposure led you to it: the exposure is real and the
# answer is still no. Do not raise these to match the cohort.
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
          unreadable (degrade-safe — the server will 401 an empty key and
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
        - never raises: transport errors → ( False, None, {"error": ...} );
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


def query_blocked_user_rows( settings, api_key, owner_persona, timeout=None ):
    """
    GET this owner's `blocked` rows at full fidelity (the per-user gate-deferral source).

    The Stop hook / arbiter derives `user_chase_until` from these: the soonest future next_chase_ts among rows whose
    blocked_by carries any {kind:"user"} ref. `blocked` rows are excluded from the owed-count query, so they need
    their own fetch. It returns full rows (not count_only) because the caller needs blocked_by and next_chase_ts.

    Requires:
        - settings is the load_task_store_settings() dict (provides api_base_url)
        - api_key is a string (may be empty — server 401s it)
        - owner_persona is the lowercased canonical persona key
        - timeout overrides DEFAULT_OWED_TIMEOUT_SECONDS (seconds, per request)

    Ensures:
        - Returns ( ok, rows ):
            ok   : True iff a 2xx carried a list under `tasks`
            rows : that list of full row dicts (empty list when ok is False)
        - any transport failure / non-2xx / malformed body / missing-or-non-list
          `tasks` → ( False, [] )  (fail-safe: the caller does not suppress on a
          bad read — never silently bury an open user decision on a store outage)
        - Fired only when the session has open hold-file gates (the common zero-gate Stop pays nothing), and
          bounded by the aggressive owed-timeout: a slow :7999 must never stall turn-end
        - never raises
    """
    if timeout is None:
        timeout = DEFAULT_OWED_TIMEOUT_SECONDS
    query = urllib.parse.urlencode( { "owner_persona": owner_persona, "status": "blocked" } )
    ok, _status, body = _request(
        "GET", f"{settings['api_base_url']}/api/tasks?{query}", api_key, timeout )
    if not ok:
        return False, [ ]
    rows = body.get( "tasks" )
    if not isinstance( rows, list ):
        return False, [ ]
    return True, rows


def _open_owed_connection( api_base_url, timeout ):
    """
    Open one keep-alive HTTP(S) connection for the owed count request.

    `query_owed` issues one `count_only` GET behind `owed_only=true`; the owed status set is server-owned.
    Reusing an http.client connection amortizes the TCP handshake to once per Stop, where urllib pays a fresh socket
    per request. Scheme-aware: https resolves to HTTPSConnection, so an https config is never silently downgraded.

    Requires:
        - api_base_url is the Lupin base URL ("http(s)://host:port", no path)
        - timeout is a positive float — the per-operation socket timeout, so the
          one-to-two-second Stop-hot-path budget still bounds each request

    Ensures:
        - Returns an http.client.HTTP(S)Connection (lazy — it connects on the
          first request, never in the constructor)
        - Returns None on any parse/constructor failure (e.g. a non-numeric port,
          where urlsplit.port raises ValueError) — the caller fails safe to
          ( False, 0 ); never raises (degrade-safe IO shell)
    """
    try:
        parts = urllib.parse.urlsplit( api_base_url )
        if parts.scheme == "https":
            return http.client.HTTPSConnection( parts.hostname, parts.port, timeout=timeout )
        return http.client.HTTPConnection( parts.hostname, parts.port, timeout=timeout )
    except Exception:
        return None


def _parse_breakdown( raw_breakdown ):
    """
    Coerce the response's `breakdown` object to a { status: int } dict.

    The breakdown is a reporting refinement of a count that is already trusted. The count carries the fail-safe,
    and by the time this runs the server has answered 2xx with an integer `count`. The caller synthesizes against
    the count alone when the breakdown is unusable.

    Requires:
        - raw_breakdown is whatever `breakdown` decoded to (may be absent / any type)

    Ensures:
        - Returns { status: int } keeping only str→non-bool-int pairs
        - Non-dict input → {}
        - A malformed or absent breakdown degrades to {} and must not fail the read, because failing it would let a
          cosmetic regression suppress the poke, which is worse than a right total with a coarse status
        - bool values are rejected (bool subclasses int — a JSON true must never
          read as 1), as are negative counts (a count cannot be negative; a
          negative one means the wire is lying, not that a bucket is small)
        - never raises
    """
    if not isinstance( raw_breakdown, dict ):
        return { }
    parsed = { }
    for key, value in raw_breakdown.items():
        if not isinstance( key, str ):
            continue
        if isinstance( value, bool ) or not isinstance( value, int ) or value < 0:
            continue
        parsed[ key ] = value
    return parsed


def _count_on_connection( connection, path_with_query, api_key ):
    """
    Issue one `count_only` GET on an existing connection; parse count + breakdown.

    Reuses `connection`'s socket (HTTP/1.1 keep-alive). The response body is read
    in full so the connection is left in a clean state (an unread response would
    wedge it as ResponseNotReady).

    Requires:
        - connection is an open http.client.HTTP(S)Connection
        - path_with_query is the "/api/tasks?..." count_only owed query
        - api_key is a string (may be empty — server 401s it)

    Ensures:
        - Returns ( ok, count, breakdown ):
            ok        : True iff a 2xx response carried an integer `count`
            count     : that integer (0 when ok is False)
            breakdown : { status: int } from the response, or {} when
                        absent/malformed — see _parse_breakdown for why a bad
                        breakdown degrades instead of failing the read
        - any transport error / non-2xx / unparseable-or-non-dict body / missing
          or non-int `count` (bool rejected — a JSON true/false must never read
          as 1/0) → ( False, 0, {} )  (the fail-safe)
        - never raises
    """
    try:
        connection.request( "GET", path_with_query, headers={ "X-API-Key": api_key } )
        response = connection.getresponse()
        status   = response.status
        raw      = response.read().decode( "utf-8" )
    except Exception:
        # Transport failure (refused / timeout / DNS / socket reset) — fail safe.
        return False, 0, { }

    if not ( 200 <= status < 300 ):
        # A received server verdict (4xx/5xx) is NOT a clean count — fail safe.
        return False, 0, { }
    try:
        parsed = json.loads( raw )
    except json.JSONDecodeError:
        return False, 0, { }
    if not isinstance( parsed, dict ):
        return False, 0, { }
    count = parsed.get( "count" )
    # bool is a subclass of int — reject a JSON `true`/`false` count explicitly
    # so it never slips through as 1/0 (house no-defensive rule).
    if isinstance( count, bool ) or not isinstance( count, int ):
        return False, 0, { }
    return True, count, _parse_breakdown( parsed.get( "breakdown" ) )


def _count_on_connection_full( connection, path_with_query, api_key ):
    """
    `_count_on_connection` plus the priority breakdown: one request, four values.

    A sibling, not a fourth return slot. `_count_on_connection` and `query_owed` are asserted as 3-tuples in
    about 30 places. A mass edit of assertions is how a suite quietly loses the property it was pinning.

    Ensures:
        - returns ( ok, count, breakdown, priority_breakdown )
        - identical fail-safe contract to `_count_on_connection`: any transport error
          / non-2xx / unparseable body / missing-or-bool `count` → ( False, 0, {}, {} )
        - `priority_breakdown` degrades to {} on absent/malformed data for the same
          reason `breakdown` does — it is a reporting refinement of a count that is
          already trusted, so it must never fail a read that otherwise succeeded
        - Does not delegate to `_count_on_connection`: that would issue a second GET on the same connection for a body
          already read, doubling the request the Stop hook fires every turn, so the four-line parse is duplicated rather than delegated
        - never raises
    """
    try:
        connection.request( "GET", path_with_query, headers={ "X-API-Key": api_key } )
        response = connection.getresponse()
        status   = response.status
        raw      = response.read().decode( "utf-8" )
    except Exception:
        return False, 0, { }, { }

    if not ( 200 <= status < 300 ):
        return False, 0, { }, { }
    try:
        parsed = json.loads( raw )
    except json.JSONDecodeError:
        return False, 0, { }, { }
    if not isinstance( parsed, dict ):
        return False, 0, { }, { }
    count = parsed.get( "count" )
    if isinstance( count, bool ) or not isinstance( count, int ):
        return False, 0, { }, { }
    return ( True, count,
             _parse_breakdown( parsed.get( "breakdown" ) ),
             _parse_breakdown( parsed.get( "priority_breakdown" ) ) )

def query_owed( settings, api_key, owner_persona, project=None, timeout=None,
                owner_field="owner_persona" ):
    """
    GET the owed-row count for one owner (store-count seam of the Stop hook).

    One request, `owed_only=true`: the server owns the owed set (queued, in_progress, and parked rows whose park has
    expired). No caller holds a status tuple, which makes it fail-closed. A per-status loop is blind to a park-expiry rejoin.

    Requires:
        - settings is the load_task_store_settings() dict (provides api_base_url)
        - api_key is a string (may be empty — server 401s it)
        - owner_persona is the persona string filtered on (lowercased canonical key): by default the row's owner
          (the PostToolUse mirror stamp), or the accountable_manager when owner_field="accountable_manager"
        - project is the resolve_project_name() scope, or None to omit the filter
        - timeout overrides DEFAULT_OWED_TIMEOUT_SECONDS (seconds, per request)
        - owner_field selects which persona column the value filters: the default "owner_persona" preserves the
          owed-count behavior; "accountable_manager" counts a manager's chase-list

    Ensures:
        - Returns ( ok, count, breakdown ):
            ok        : True iff the query returned a 2xx whose body carried an integer `count`
            count     : the server-computed owed-row count (0 when ok is False)
            breakdown : { status: count } over that same admitted set (under owed_only the `parked` key is the
                        expired-parked set), or {} when omitted or malformed: a cosmetic regression must never
                        suppress the poke, so the breakdown degrades while the count still governs
        - sum( breakdown.values() ) == count whenever the server supplied one — two independently computed numbers, asserted rather than derived
        - any transport failure / non-2xx / malformed body (missing or non-int `count`) / unresolvable base URL
          → ( False, 0, {} ) — the fail-safe: the caller does not poke on a not-ok read (never guess when the store can't be reached)
        - Why one request and no per-status loop: park-expiry is computed at read time and never written back, so an expired
          parked row still carries status="parked", matches neither queued nor in_progress and would stay silent forever;
          a loop also double-counts an expired parked row admitted on both calls, making the board look busier than never parking
        - Membership is unchanged apart from park: blocked / claimed / review are still not owed to this reader, and park is legal only
          from ("queued","in_progress"), so every expired-parked row came from the set already counted (restoration, not widening)
        - count_only=true returns a true SQL `COUNT(*)` without serializing a row, so the count can never saturate at the page `limit`;
          the socket timeout is aggressive because the Stop hook fires every turn and a slow `:7999` must never stall turn-end
        - The breakdown is computed server-side on the same admitted set in one `GROUP BY`; without it the caller invented in_progress
          for every row. It is no license to reinstate the per-status loop; test_task_store_client.py asserts exactly one request
        - The connection is always closed; the reused connection carries a single request, costs one handshake either way, and keeps timeout and close discipline in one place
        - never raises
    """
    if timeout is None:
        timeout = DEFAULT_OWED_TIMEOUT_SECONDS

    connection = _open_owed_connection( settings[ "api_base_url" ], timeout )
    if connection is None:
        return False, 0, { }                 # bad base URL → fail safe (never raise)

    try:
        # count_only=true (O2): true COUNT(*), never a page-length saturating at
        # the endpoint's limit cap — a session with >100 owed rows counts exactly.
        # owed_only=true: the server owns the status set (see the docstring —
        # a per-status loop here could neither SEE a park-expiry rejoin nor avoid
        # double-counting one).
        params = { owner_field: owner_persona, "owed_only": "true", "count_only": "true" }
        if project:
            params[ "project" ] = project
        path = f"/api/tasks?{urllib.parse.urlencode( params )}"
        ok, count, breakdown = _count_on_connection( connection, path, api_key )
        if not ok:
            return False, 0, { }
        return True, count, breakdown
    finally:
        connection.close()                   # release the socket (close is idempotent)


def query_owed_breakdowns( settings, api_key, owner_persona, project=None, timeout=None,
                           owner_field="owner_persona" ):
    """
    `query_owed` plus the priority breakdown: the same one request, four values.

    The Stop-hook poke needs to say which rows matter, not only how many. `query_owed` keeps its 3-tuple so its
    roughly 30 existing assertions stay as written. This is the entry point for the one caller wanting the fourth field.

    Ensures:
        - returns ( ok, count, breakdown, priority_breakdown )
        - identical fail-safe contract to `query_owed`: any not-ok read yields
          ( False, 0, {}, {} ) and the caller does not poke
        - issues exactly one HTTP request, like `query_owed`
        - the connection is always closed
        - never raises
    """
    if timeout is None:
        timeout = DEFAULT_OWED_TIMEOUT_SECONDS

    connection = _open_owed_connection( settings[ "api_base_url" ], timeout )
    if connection is None:
        return False, 0, { }, { }

    try:
        params = { owner_field: owner_persona, "owed_only": "true", "count_only": "true" }
        if project:
            params[ "project" ] = project
        path = f"/api/tasks?{urllib.parse.urlencode( params )}"
        ok, count, breakdown, priority_breakdown = _count_on_connection_full( connection, path, api_key )
        if not ok:
            return False, 0, { }, { }
        return True, count, breakdown, priority_breakdown
    finally:
        connection.close()
