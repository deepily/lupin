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


def _open_owed_connection( api_base_url, timeout ):
    """
    Open ONE keep-alive HTTP(S) connection for the multi-status owed loop (O3).

    `query_owed` issues one `count_only` GET per owed status. The previous
    urllib.urlopen path opened a FRESH socket per status (urllib does no
    connection pooling) — pure per-Stop latency, paid every turn. A single
    http.client connection reused across the status loop amortizes the TCP
    handshake to once per Stop (O3, cascade review §D residue). Scheme-aware:
    an https base resolves to HTTPSConnection (the hook lane is http `:7999`
    today, but the seam must not silently downgrade an https config).

    Requires:
        - api_base_url is the Lupin base URL ("http(s)://host:port", no path)
        - timeout is a positive float — the per-operation socket timeout, so the
          §C ≤1-2s Stop-hot-path budget still bounds each request

    Ensures:
        - Returns an http.client.HTTP(S)Connection (lazy — it connects on the
          first request, never in the constructor)
        - Returns None on ANY parse/constructor failure (e.g. a non-numeric port,
          where urlsplit.port raises ValueError) — the caller fails safe to
          ( False, 0 ); NEVER raises (degrade-safe IO shell)
    """
    try:
        parts = urllib.parse.urlsplit( api_base_url )
        if parts.scheme == "https":
            return http.client.HTTPSConnection( parts.hostname, parts.port, timeout=timeout )
        return http.client.HTTPConnection( parts.hostname, parts.port, timeout=timeout )
    except Exception:
        return None


def _count_on_connection( connection, path_with_query, api_key ):
    """
    Issue ONE `count_only` GET on an existing connection; parse the count (O3).

    Reuses `connection`'s socket (HTTP/1.1 keep-alive). The response body is read
    in FULL so the connection is left ready for the next status query on the
    SAME socket (an unread response would wedge it as ResponseNotReady).

    Requires:
        - connection is an open http.client.HTTP(S)Connection
        - path_with_query is the "/api/tasks?..." count_only owed query
        - api_key is a string (may be empty — server 401s it)

    Ensures:
        - Returns ( ok, count ):
            ok    : True iff a 2xx response carried an integer `count`
            count : that integer (0 when ok is False)
        - ANY transport error / non-2xx / unparseable-or-non-dict body / missing
          or non-int `count` (bool rejected — a JSON true/false must never read
          as 1/0) → ( False, 0 )  (the §C fail-safe)
        - NEVER raises
    """
    try:
        connection.request( "GET", path_with_query, headers={ "X-API-Key": api_key } )
        response = connection.getresponse()
        status   = response.status
        raw      = response.read().decode( "utf-8" )
    except Exception:
        # Transport failure (refused / timeout / DNS / socket reset) — fail safe.
        return False, 0

    if not ( 200 <= status < 300 ):
        # A received server verdict (4xx/5xx) is NOT a clean count — fail safe.
        return False, 0
    try:
        parsed = json.loads( raw )
    except json.JSONDecodeError:
        return False, 0
    if not isinstance( parsed, dict ):
        return False, 0
    count = parsed.get( "count" )
    # bool is a subclass of int — reject a JSON `true`/`false` count explicitly
    # so it never slips through as 1/0 (house no-defensive rule).
    if isinstance( count, bool ) or not isinstance( count, int ):
        return False, 0
    return True, count


def query_owed( settings, api_key, owner_persona, project=None, timeout=None,
                owner_field="owner_persona" ):
    """
    GET /api/tasks owed-row COUNT for one owner (Spine Step-2 store-count seam).

    ONE request, `owed_only=true` — the server defines the owed set.

    PARKED-STATUS (2026-07-19) REWRITE. This used to take a `statuses` tuple,
    fire one count_only request PER status, and SUM. That shape is now
    unbuildable, for two independent reasons:

      1. It CANNOT see a park-expiry rejoin. Park-expiry is computed at READ
         time and never written back, so an EXPIRED parked row still carries
         status="parked" in the column — it matches neither "queued" nor
         "in_progress" and would stay silent forever. Parking would buy
         PERMANENT silence from the one reader that fires the pokes, which is
         the exact defect this build exists to kill.
      2. Server-side admission + a per-status loop DOUBLE-COUNTS: an expired
         parked row would be admitted on the queued call AND again on the
         in_progress call. Parking a row and letting it expire would make the
         board look BUSIER than never parking it — the feature inverts.

    So the status set moved SERVER-side behind a single `owed_only` flag:
    queued U in_progress U (parked AND NOT park-active). No caller holds a
    status tuple any more, which is what makes it fail-CLOSED — there is no
    second thing to remember to pair. STORE_OWED_STATUSES is DELETED from
    stop.py and task_store_drain.py rather than re-pointed: a constant that no
    longer exists cannot drift, and it had already forked into 4 copies.

    Membership is UNCHANGED apart from park: blocked / claimed / review are
    still NOT owed to this reader, exactly as before. Park is legal ONLY from
    ("queued","in_progress"), so every expired-parked row provably came from
    the set this reader already counted — exact RESTORATION, not a widening.

    `count_only=true` (O2 / §G) returns a true SQL COUNT(*) without serializing
    a row, so the count can NEVER saturate at the endpoint's page `limit`.
    Bounded by an AGGRESSIVE socket timeout (the Stop hook fires every turn — a
    slow `:7999` must never stall turn-end; cascade review §C). The O3 reused
    connection is retained but now carries a single request; it costs one
    handshake either way and keeps the timeout/close discipline in one place.

    Requires:
        - settings is the load_task_store_settings() dict (provides api_base_url)
        - api_key is a string (may be empty — server 401s it)
        - owner_persona is the persona string filtered on (lowercased canonical
          key): by default the row's owner (the PostToolUse mirror stamp), or the
          accountable_manager when owner_field="accountable_manager"
        - project is the resolve_project_name() scope, or None to omit the filter
        - timeout overrides DEFAULT_OWED_TIMEOUT_SECONDS (seconds, per request)
        - owner_field selects WHICH persona column the value filters: the default
          "owner_persona" preserves the owed-count behavior; "accountable_manager"
          counts a manager's chase-list (proactive-manager A1 Face A backlog)

    Ensures:
        - Returns ( ok, count ):
            ok    : True iff the query returned a 2xx whose body carried an
                    integer `count`
            count : the server-computed owed-row count (0 when ok is False)
        - ANY transport failure / non-2xx / malformed body (missing or non-int
          `count`) / unresolvable base URL → ( False, 0 ) — the §C fail-safe:
          the caller does NOT poke on a not-ok read (never guess when the store
          can't be reached)
        - The connection is ALWAYS closed
        - NEVER raises
    """
    if timeout is None:
        timeout = DEFAULT_OWED_TIMEOUT_SECONDS

    connection = _open_owed_connection( settings[ "api_base_url" ], timeout )
    if connection is None:
        return False, 0                      # bad base URL → fail safe (never raise)

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
        ok, count = _count_on_connection( connection, path, api_key )
        if not ok:
            return False, 0
        return True, count
    finally:
        connection.close()                   # release the socket (close is idempotent)
