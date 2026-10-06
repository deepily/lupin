"""
Store-backed DM inbox reconcile: the durable store is the delivery guarantee.

The lossy voice-buffer side-channel is left untouched, and its losses are made harmless.

Root cause: a peer DM (direction=ai_to_ai) that arrives while the recipient is
mid-turn is written to the JSONL voice buffer. It is surfaced only if a later
hook drains it in the same session. If the session ends or parks first, or the
drain lands on the low-salience PostToolUse path, the DM is lost. The triage
found 84 orphaned DMs across 46 stale buffer files.

This module adds an at-least-once surfacing path. At UserPromptSubmit
(start of turn, when attention is fresh) it reconciles this session's DM inbox
against a durable per-session high-water mark. It surfaces any un-surfaced DMs
as `additionalContext`, with no interrupt or deny. The PreToolUse high-salience
deny keeps serving mid-turn immediacy; this is the guaranteed-delivery backstop.

Design constraints:
    1. The buffer, inject and PreToolUse-deny paths are untouched. This is purely additive.
    2. The high-water mark is durable per session. It lives in the heartbeat-hold
       runtime-state dir, so it survives /clear. Dedup is by message_id.
    3. DMs are surfaced at UserPromptSubmit as additionalContext, never as interrupt or deny.
    4. The 84 stale orphans are not replayed here. Their inventory and a separate
       dry-run janitor sweep live in the DM-loss triage notes.

Auth reuses the hook-writer X-API-Key lane (task_store_client.read_api_key and
_request). It resolves to the human owner's user_id, so /api/dm/list returns the
owner's full all-sessions inbox, which is then filtered by job_id to this
session. It never raises on the turn-start hot path.
"""

import json
import urllib.parse
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir
from lupin_cli.claude_code.hooks.lib.hook_common import build_peer_dm_reminder


# ── Constants ─────────────────────────────────────────────────────────────────

HWM_FILENAME_TEMPLATE   = ".dm-inbox-hwm-{session_id}.json"
SURFACED_IDS_CAP        = 500        # bound the durable dedup ledger (FIFO tail)
DEFAULT_LIMIT           = 200        # /api/dm/list server cap (_DM_LIST_MAX_LIMIT)
DEFAULT_TIMEOUT_SECONDS = 1.5        # bounded — UserPromptSubmit is a turn boundary
DEFAULT_API_BASE_URL    = "http://localhost:7999"
RECONCILE_LOG_NAME      = "dm-inbox-reconcile.log"


# ── Small pure helpers ────────────────────────────────────────────────────────

def _max_iso( a, b ):
    """
    Return the later of two ISO-8601 timestamp strings (None-safe).

    All /api/dm/list created_at values carry the same UTC offset (server
    `.isoformat()`), so lexicographic comparison is chronological.

    Ensures:
        - None + None gives None; one None gives the other; else the greater string
    """
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _dedup_tail( seq, cap ):
    """
    De-duplicate `seq` keeping first-occurrence order, then keep only the last `cap` entries.

    Ensures:
        - Order-stable dedup, tail-capped when cap > 0 and len > cap (0 means no cap)
    """
    seen = set()
    out  = []
    for x in seq:
        if x in seen:
            continue
        seen.add( x )
        out.append( x )
    if cap and len( out ) > cap:
        return out[ -cap: ]
    return out


# ── Pure reconcile core ───────────────────────────────────────────────────────

def reconcile_context( session_hash8, rows, state, extra_surfaced_ids=() ):
    """
    Pure core: build the additionalContext of un-surfaced DMs for this session plus new state.

    Takes the fetched inbox `rows` and the current `state`. It does no IO, so it is fully unit-testable.

    Requires:
        - session_hash8 is the 8-char session hash (== job_id on this session's DMs)
        - rows is a list of /api/dm/list serialized DM dicts (job_id, message_id,
          created_at, body, sender_persona, sender_icon, thread_id, ...)
        - state is {"cursor_ts": <iso|None>, "surfaced_ids": [<message_id>...]}
        - extra_surfaced_ids: message_ids already delivered this turn (e.g. the
          voice-buffer drain), excluded from surfacing and recorded so future
          turns skip them (this removes the at-most-one redundant re-surface).

    Ensures:
        - Returns ( context_str, new_state )
        - context contains one build_peer_dm_reminder block per fresh, non-blank,
          this-session DM, oldest-first (read order)
        - Dedup by message_id against state.surfaced_ids and extra_surfaced_ids combined
        - cursor_ts advances to the max created_at across all of this session's
          fetched rows (seen, not merely surfaced), never past another session's
          rows, so a quiet session never skips its own not-yet-page-visible DMs
        - surfaced_ids = tail-capped dedup of ( existing + extra + newly surfaced )
        - Never raises
    """
    cursor_ts    = state.get( "cursor_ts" )
    surfaced_ids = list( state.get( "surfaced_ids", [] ) )
    extra        = [ i for i in extra_surfaced_ids if i ]
    surfaced_set = set( surfaced_ids ) | set( extra )

    mine = [ r for r in rows if ( r.get( "job_id" ) or "" ) == session_hash8 ]

    # Advance cursor by EVERY fetched row for this session (seen), not just the
    # ones we surface — so a re-fetch with since=cursor won't re-return them.
    new_cursor = cursor_ts
    for r in mine:
        new_cursor = _max_iso( new_cursor, r.get( "created_at" ) )

    fresh = [ r for r in mine if r.get( "message_id" ) not in surfaced_set ]
    fresh.sort( key=lambda r: r.get( "created_at" ) or "" )

    blocks         = []
    newly_recorded = []
    for r in fresh:
        mid = r.get( "message_id" )
        if mid:
            newly_recorded.append( mid )
        body = ( r.get( "body" ) or "" ).strip()
        if not body:
            continue                                   # recorded (above) → no re-fetch loop
        blocks.append( build_peer_dm_reminder(
            body,
            persona   = r.get( "sender_persona" ),
            icon      = r.get( "sender_icon" ),
            msg_id    = mid,
            thread_id = r.get( "thread_id" ),
        ) )

    new_ids   = _dedup_tail( surfaced_ids + extra + newly_recorded, SURFACED_IDS_CAP )
    new_state = { "cursor_ts": new_cursor, "surfaced_ids": new_ids }
    return "\n".join( blocks ), new_state


# ── HWM file IO (durable, /clear-proof — hold-file runtime-state family) ───────

def _hwm_path( session_id, base_dir=None ):
    """
    Resolve the durable HWM file path for a session.

    It lives in the same runtime-state base dir as the heartbeat hold file
    (heartbeat_hold._resolve_base_dir) so it survives /clear.
    It is keyed by the 8-char session hash, which matches the DM job_id.
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _resolve_base_dir
    suffix = ( session_id or "" )[ :8 ]
    return _resolve_base_dir( base_dir ) / HWM_FILENAME_TEMPLATE.format( session_id=suffix )


def read_hwm( session_id, base_dir=None ):
    """
    Read the durable high-water mark, returning a default on any miss or corruption.

    A missing file is not seeded: the first reconcile seeds the mark and surfaces
    nothing, so activation never replays a session's pre-existing inbox.
    A file that predates the `seeded` key counts as seeded, so its dedup ledger stands.

    Ensures:
        - Returns {"cursor_ts": <str|None>, "surfaced_ids": [<str>...], "seeded": <bool>}
        - Missing file / bad JSON / non-dict / wrong field types give the empty
          default (never raises)
    """
    path = _hwm_path( session_id, base_dir=base_dir )
    try:
        with open( path ) as f:
            data = json.load( f )
    except ( FileNotFoundError, OSError, json.JSONDecodeError ):
        # NO file yet → NOT seeded: the first reconcile seeds the mark and
        # surfaces nothing, so activation never replays a session's pre-existing
        # inbox (constraint 4 — no replay into live sessions).
        return { "cursor_ts": None, "surfaced_ids": [], "seeded": False }
    if not isinstance( data, dict ):
        return { "cursor_ts": None, "surfaced_ids": [], "seeded": False }
    cursor = data.get( "cursor_ts" )
    ids    = data.get( "surfaced_ids" )
    # A file that exists but predates the `seeded` key was written by an earlier
    # reconcile that already recorded its ids → treat as seeded (default True) so
    # its dedup ledger stands and it does not re-seed.
    return {
        "cursor_ts"    : cursor if isinstance( cursor, str ) else None,
        "surfaced_ids" : ids if isinstance( ids, list ) else [],
        "seeded"       : bool( data.get( "seeded", True ) ),
    }


def write_hwm( session_id, state, base_dir=None ):
    """
    Persist the high-water mark, best-effort (returns False on OSError, never raises).

    A failed persist just means the next turn re-surfaces and retries.
    """
    path = _hwm_path( session_id, base_dir=base_dir )
    try:
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "w" ) as f:
            json.dump( {
                "cursor_ts"    : state.get( "cursor_ts" ),
                "surfaced_ids" : list( state.get( "surfaced_ids", [] ) ),
                "seeded"       : bool( state.get( "seeded", True ) ),
            }, f )
        return True
    except OSError:
        return False


# ── Inbox fetch (X-API-Key hook lane) ─────────────────────────────────────────

def _load_settings():
    """
    Resolve api_base_url and timeout from the task-store settings loader (same :7999 host).

    On a malformed settings block it falls back to the localhost defaults.
    """
    from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
    try:
        return load_task_store_settings()
    except ValueError:
        return { "api_base_url": DEFAULT_API_BASE_URL, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS }


def _fetch_inbox( since=None, limit=DEFAULT_LIMIT, timeout=DEFAULT_TIMEOUT_SECONDS ):
    """
    GET /api/dm/list (X-API-Key): the owner's peer-DM inbox, newest-first.

    The result can be tailed by `since`. It reuses the never-raise ( ok, status, body )
    triple of task_store_client._request.

    Ensures:
        - Returns ( ok, rows, page_full )
        - ok is False (rows=[], page_full=False) on any transport/HTTP failure or
          a non-dict body / non-list messages (fail-safe: caller surfaces nothing
          and does not advance the HWM)
        - page_full = len(rows) >= limit (a full page means possible truncation)
        - Never raises
    """
    from lupin_cli.claude_code.hooks.lib import task_store_client as tc

    api_key  = tc.read_api_key()
    settings = _load_settings()
    params   = { "limit": str( limit ) }
    if since:
        params[ "since" ] = since
    url = f"{settings['api_base_url']}/api/dm/list?{urllib.parse.urlencode( params )}"

    ok, _status, body = tc._request( "GET", url, api_key, timeout )
    if not ok or not isinstance( body, dict ):
        return False, [], False
    msgs = body.get( "messages", [] )
    if not isinstance( msgs, list ):
        return False, [], False
    return True, msgs, len( msgs ) >= limit


def _log_capped( session_id, count, log_dir=None ):
    """
    Write a best-effort log line when a fetch page hit the limit. Never raises.

    A full page can truncate a quiet session's older DMs under fleet-storm
    traffic, which is the known bound.
    """
    try:
        base = Path( log_dir ) if log_dir is not None else sessions_dir()   # row 8ccc20ab: the one seam
        base.mkdir( parents=True, exist_ok=True )
        with open( base / RECONCILE_LOG_NAME, "a" ) as f:
            f.write( f"{( session_id or '' )[:8]} inbox page CAPPED at {count} (possible truncation)\n" )
    except Exception:
        pass


# ── IO shell (the one public entrypoint the hook calls) ───────────────────────

def surface_dm_inbox( session_id, extra_surfaced_ids=(), fetch_fn=None, base_dir=None ):
    """
    Reconcile this session's DM inbox against the durable HWM; return the additionalContext.

    This is the single entrypoint called from user_prompt_submit.py.

    Requires:
        - session_id is the stable session id (or "", which returns "")
        - extra_surfaced_ids: message_ids already delivered this turn (voice-buffer
          drain), excluded and recorded
        - fetch_fn(since, limit) -> ( ok, rows, page_full ); defaults to _fetch_inbox
          (dependency-injected in tests)

    Ensures:
        - Returns the additionalContext string ("" when nothing fresh)
        - On a not-ok fetch: returns "" and does not advance the HWM (retry next turn)
        - Persists the advanced HWM on a successful reconcile
        - Never raises (fail-open on the turn-start hot path)

    Notes:
        - The first reconcile for a session (no HWM yet) seeds the mark. It records
          the current inbox as seen and surfaces nothing, so activation never
          replays a live session's backlog.
    """
    try:
        if not session_id:
            return ""
        hash8 = session_id[ :8 ]
        state = read_hwm( session_id, base_dir=base_dir )

        if fetch_fn is None:
            fetch_fn = _fetch_inbox
        ok, rows, page_full = fetch_fn( since=state.get( "cursor_ts" ), limit=DEFAULT_LIMIT )
        if not ok:
            return ""                                  # fail-open: no HWM advance, retry next turn
        if page_full:
            _log_capped( session_id, len( rows ) )

        context, new_state = reconcile_context(
            hash8, rows, state, extra_surfaced_ids=extra_surfaced_ids
        )
        new_state[ "seeded" ] = True
        # First reconcile for this session (no HWM yet): SEED the mark — record
        # the current inbox as already-seen and advance the cursor, but surface
        # NOTHING. Activation is forward-looking only; it never replays a live
        # session's pre-existing backlog (constraint 4). Delivery is guaranteed
        # for every DM that arrives from this point on.
        if not state.get( "seeded", False ):
            context = ""
        write_hwm( session_id, new_state, base_dir=base_dir )
        return context
    except Exception:
        return ""
