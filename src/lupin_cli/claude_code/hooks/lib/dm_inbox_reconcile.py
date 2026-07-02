"""
Store-backed DM inbox reconcile — bug 59f355e0, Option A (Mr. Radio ruling
2026-07-02). The durable notifications store becomes the delivery guarantee it
already is; the lossy voice-buffer side-channel is left UNTOUCHED (its losses
are simply made harmless).

Root cause (see src/rnd/v0.1.9/2026.07.02-dm-loss-surfacing-leg-triage.md): a
peer DM (direction=ai_to_ai) that arrives while the recipient is mid-turn is
written to the JSONL voice buffer and surfaced only if a LATER hook drains it in
the same session. If the session ends / parks first, or the drain lands on the
low-salience PostToolUse path, the DM is lost (84 orphaned DMs across 46 stale
buffer files at triage time).

This module adds an at-least-once surfacing path: at UserPromptSubmit
(start-of-turn = fresh attention) it reconciles THIS session's DM inbox against a
durable per-session high-water mark and surfaces any un-surfaced DMs as
`additionalContext` — with NO interrupt/deny (the PreToolUse high-salience deny
keeps serving mid-turn immediacy; this is the guaranteed-delivery backstop).

Design constraints honored (ruling):
    1. Buffer/inject/PreToolUse-deny paths UNTOUCHED — this is purely additive.
    2. High-water mark durable per-session (lives in the heartbeat-hold runtime-
       state dir → survives /clear); dedup by message_id.
    3. Surfaced at UserPromptSubmit as additionalContext, never interrupt/deny.
    4. The 84 stale orphans are NOT replayed here (inventory + a separate dry-run
       janitor sweep live in the triage doc).

Auth reuses the hook-writer X-API-Key lane (task_store_client.read_api_key /
_request) — empirically verified to resolve to the human owner's user_id, so
/api/dm/list returns the owner's full (all-sessions) inbox, which is then
job_id-filtered to this session. NEVER raises on the turn-start hot path.
"""

import json
import urllib.parse
from pathlib import Path

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
    `.isoformat()`), so lexicographic comparison IS chronological.

    Ensures:
        - None + None → None; one None → the other; else the greater string
    """
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _dedup_tail( seq, cap ):
    """
    De-duplicate `seq` preserving first-occurrence order, then keep only the last
    `cap` entries (0 → no cap).

    Ensures:
        - Order-stable dedup, tail-capped when cap > 0 and len > cap
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
    Pure core: given fetched inbox `rows` + current `state`, return the
    additionalContext string of un-surfaced DMs for this session and the advanced
    state. No IO — fully unit-testable.

    Requires:
        - session_hash8 is the 8-char session hash (== job_id on this session's DMs)
        - rows is a list of /api/dm/list serialized DM dicts (job_id, message_id,
          created_at, body, sender_persona, sender_icon, thread_id, ...)
        - state is {"cursor_ts": <iso|None>, "surfaced_ids": [<message_id>...]}
        - extra_surfaced_ids: message_ids already delivered THIS turn (e.g. the
          voice-buffer drain) — excluded from surfacing AND recorded so future
          turns skip them (kills the at-most-one redundant re-surface).

    Ensures:
        - Returns ( context_str, new_state )
        - context contains ONE build_peer_dm_reminder block per fresh, non-blank,
          this-session DM, oldest-first (read order)
        - Dedup by message_id against state.surfaced_ids ∪ extra_surfaced_ids
        - cursor_ts advances to the max created_at across ALL of THIS session's
          fetched rows (seen, not merely surfaced) — never past another session's
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

    Lives in the SAME runtime-state base dir as the heartbeat hold file
    (heartbeat_hold._resolve_base_dir) so it survives /clear. Keyed by the 8-char
    session hash (matches the DM job_id).
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _resolve_base_dir
    suffix = ( session_id or "" )[ :8 ]
    return _resolve_base_dir( base_dir ) / HWM_FILENAME_TEMPLATE.format( session_id=suffix )


def read_hwm( session_id, base_dir=None ):
    """
    Read the durable high-water mark; default on any miss/corruption (fail-open).

    Ensures:
        - Returns {"cursor_ts": <str|None>, "surfaced_ids": [<str>...]}
        - Missing file / bad JSON / non-dict / wrong field types → the empty
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
    Persist the high-water mark. Best-effort (returns False on OSError, never
    raises) — a failed persist just means the next turn re-surfaces + retries.
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
    Resolve api_base_url + timeout, reusing the task-store settings loader (same
    :7999 host). Fails SAFE to localhost defaults on a malformed settings block.
    """
    from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
    try:
        return load_task_store_settings()
    except ValueError:
        return { "api_base_url": DEFAULT_API_BASE_URL, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS }


def _fetch_inbox( since=None, limit=DEFAULT_LIMIT, timeout=DEFAULT_TIMEOUT_SECONDS ):
    """
    GET /api/dm/list (X-API-Key) — the owner's peer-DM inbox, newest-first,
    optionally tailed by `since`. Reuses task_store_client._request's never-raise
    ( ok, status, body ) triple.

    Ensures:
        - Returns ( ok, rows, page_full )
        - ok is False (rows=[], page_full=False) on any transport/HTTP failure or
          a non-dict body / non-list messages (fail-safe — caller surfaces nothing
          and does NOT advance the HWM)
        - page_full = len(rows) >= limit (a full page ⇒ possible truncation)
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
    Best-effort visibility line when a fetch page hit the limit (possible
    truncation of a quiet session's older DMs under fleet-storm traffic — the
    documented known-bound). Never raises.
    """
    try:
        base = Path( log_dir ) if log_dir is not None else ( Path.home() / ".claude" / "sessions" )
        base.mkdir( parents=True, exist_ok=True )
        with open( base / RECONCILE_LOG_NAME, "a" ) as f:
            f.write( f"{( session_id or '' )[:8]} inbox page CAPPED at {count} (possible truncation)\n" )
    except Exception:
        pass


# ── IO shell (the one public entrypoint the hook calls) ───────────────────────

def surface_dm_inbox( session_id, extra_surfaced_ids=(), fetch_fn=None, base_dir=None ):
    """
    Reconcile this session's DM inbox against the durable HWM and return the
    additionalContext of any un-surfaced DMs. The single entrypoint called from
    user_prompt_submit.py.

    Requires:
        - session_id is the stable session id (or "" — returns "")
        - extra_surfaced_ids: message_ids already delivered this turn (voice-buffer
          drain) — excluded + recorded
        - fetch_fn(since, limit) -> ( ok, rows, page_full ); defaults to _fetch_inbox
          (dependency-injected in tests)

    Ensures:
        - Returns the additionalContext string ("" when nothing fresh)
        - On a not-ok fetch: returns "" and does NOT advance the HWM (retry next turn)
        - Persists the advanced HWM on a successful reconcile
        - Never raises (fail-open on the turn-start hot path)
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
