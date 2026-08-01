"""
Late-answer catch-up — the per-session Claude Code sibling of dm_inbox_reconcile
(§4.4 of src/rnd/v0.1.9/2026.08.01-late-answer-handback.md, store row `7bb0a7df`).

When a human answers a blocking ask, the answer is persisted durably but handed
back only by waking an in-memory dict; if that entry is gone (server bounce,
dropped SSE stream), the answer is stored and never travels and the asking
session times out and re-asks. This module is the durable at-least-once path: a
returning session PULLS everything answered in its absence and surfaces it as
replayed context — mirroring the human client's recovery behavior.

Two drivers call `surface_owed_answers`:
    1. cc_notification_listener._on_connected — the listener process, on every
       connect edge (a respawn after a bounce IS a first connect).
    2. user_prompt_submit.py — the hook process, at start-of-turn. This covers
       what the on-connect hook structurally cannot: the listener process being
       DEAD, not merely its socket. The shared HWM file dedupes the two for free.

⚠️ DELIBERATE DIVERGENCE FROM THE DM SIBLING — read before "fixing" it:
`dm_inbox_reconcile.surface_dm_inbox` SUPPRESSES output on first seed, so
activation never replays a live session's pre-existing backlog. **Ruling 3
requires the OPPOSITE here** — a returning session must pull everything
accumulated in its absence, and a listener respawn after a bounce IS a first
connect. So this module has **NO seed suppression**: the first reconcile surfaces
every owed answer. Do not pattern-match against the sibling and re-add it.

⚠️ AUTH LANE (the plan's one silent-failure surface, D-V1): the fetch reads the
hook X-API-Key lane (task_store_client.read_api_key / _request), which resolves
to the HUMAN OWNER's user_id — the same lane dm_inbox_reconcile uses. It must
NEVER read the listener's ambient service-account `self._user_id`: that returns a
correct-looking, SILENTLY EMPTY list. Retrieval here is persona-keyed anyway
(ruling 6), so the endpoint is called with `persona`, never a user_id — but the
listener's _on_connected override MUST hand this module the persona, not lean on
its own `self._user_id`. D-V1 (real-DB, Rachel's tier) is the negative control.

Replayed answers surface as context, NEVER as an interrupt or a synthesized tool
result (matching dm_inbox_reconcile's no-interrupt contract). Never raises.
"""

import json
import os
import urllib.parse
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

HWM_FILENAME_TEMPLATE   = ".ask-answer-hwm-{session_id}.json"
SURFACED_LOG_TEMPLATE   = ".ask-surfaced-{session_id}.log"    # cross-process side-log (O_APPEND)
SURFACED_IDS_CAP        = 500        # bound the durable dedup ledger (FIFO tail)
DEFAULT_LIMIT           = 200
DEFAULT_TIMEOUT_SECONDS = 1.5        # bounded — connect/turn boundary
DEFAULT_API_BASE_URL    = "http://localhost:7999"
CATCHUP_LOG_NAME        = "answer-catchup.log"


# ── Small pure helpers ────────────────────────────────────────────────────────

def _max_iso( a, b ):
    """
    Return the later of two ISO-8601 timestamp strings (None-safe).

    All responded_at values carry the same UTC offset (server `.isoformat()`), so
    lexicographic comparison IS chronological.

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


def _format_answer_block( row ):
    """
    Render one replayed owed-answer as a non-interrupt context block (rulings 6/7):
    the ORIGINAL question, the human's answer, when it was answered, and — when the
    asking session differs from the receiving one — the earlier-session flag. A bare
    answer with no question attached is worse than nothing.

    Requires:
        - row is an owed-answer envelope dict (question, response_value, responded_at,
          from_earlier_session, sender_persona)

    Ensures:
        - Returns a plain-English block; never raises on missing fields
    """
    question = ( row.get( "question" ) or "" ).strip()
    answer   = row.get( "response_value" )
    if isinstance( answer, dict ):
        answer = answer.get( "value", answer )
    responded_at = row.get( "responded_at" ) or "an earlier time"
    lines = [ "[Late answer to a question you asked earlier — context only, no action required]" ]
    if row.get( "from_earlier_session" ):
        lines.append( "(This answers a question asked by an earlier session of this persona.)" )
    lines.append( f"Question: {question}" )
    lines.append( f"Answer: {answer}" )
    lines.append( f"Answered at: {responded_at}" )
    return "\n".join( lines )


# ── Pure reconcile core ───────────────────────────────────────────────────────

def reconcile_answers( session_hash8, rows, state, extra_surfaced_ids=() ):
    """
    Pure core: given fetched owed-answer `rows` + current `state`, return the
    additionalContext of un-surfaced answers and the advanced state. No IO —
    fully unit-testable.

    Retrieval is persona-keyed at the endpoint (ruling 6), so EVERY fetched row is
    already for this persona and is surfaced (earlier-session rows included, flagged)
    — there is NO job_id/session filter here, unlike the DM sibling.

    Requires:
        - session_hash8 is the 8-char session hash (labels logs; NOT a row filter)
        - rows is a list of owed-answer envelope dicts (id, question, response_value,
          responded_at, from_earlier_session, ...)
        - state is {"cursor_ts": <iso|None>, "surfaced_ids": [<notification_id>...]}
        - extra_surfaced_ids: notification_ids already surfaced by the live listener
          arm THIS session (read from the cross-process side-log) — excluded AND
          recorded so the two routes collapse to one surfacing (the §4.3 ledger)

    Ensures:
        - Returns ( context_str, new_state )
        - context has ONE answer block per fresh, non-blank row, oldest-first by
          responded_at
        - Dedup by notification_id against state.surfaced_ids ∪ extra_surfaced_ids
        - cursor_ts advances to the max responded_at across ALL fetched rows (seen,
          not merely surfaced) — cursor is on responded_at, never created_at
        - surfaced_ids = tail-capped dedup of ( existing + extra + newly surfaced )
        - NO seed suppression — first reconcile surfaces everything owed (ruling 3)
        - Never raises
    """
    cursor_ts    = state.get( "cursor_ts" )
    surfaced_ids = list( state.get( "surfaced_ids", [] ) )
    extra        = [ i for i in extra_surfaced_ids if i ]
    surfaced_set = set( surfaced_ids ) | set( extra )

    # Advance cursor by EVERY fetched row (seen), not just surfaced ones, so a
    # re-fetch with since=cursor won't re-return them. Cursor is on responded_at.
    new_cursor = cursor_ts
    for r in rows:
        new_cursor = _max_iso( new_cursor, r.get( "responded_at" ) )

    fresh = [ r for r in rows if r.get( "id" ) not in surfaced_set ]
    fresh.sort( key=lambda r: r.get( "responded_at" ) or "" )

    blocks         = []
    newly_recorded = []
    for r in fresh:
        nid = r.get( "id" )
        if nid:
            newly_recorded.append( nid )
        if not ( r.get( "question" ) or r.get( "response_value" ) ):
            continue                                   # recorded above → no re-fetch loop
        blocks.append( _format_answer_block( r ) )

    new_ids   = _dedup_tail( surfaced_ids + extra + newly_recorded, SURFACED_IDS_CAP )
    new_state = { "cursor_ts": new_cursor, "surfaced_ids": new_ids }
    return "\n\n".join( blocks ), new_state


# ── HWM file IO (durable, /clear-proof — hold-file runtime-state family) ───────

def _base_dir( base_dir=None ):
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _resolve_base_dir
    return _resolve_base_dir( base_dir )


def _hwm_path( session_id, base_dir=None ):
    """Resolve the durable HWM file path (same runtime-state dir as the hold file → /clear-proof)."""
    suffix = ( session_id or "" )[ :8 ]
    return _base_dir( base_dir ) / HWM_FILENAME_TEMPLATE.format( session_id=suffix )


def read_hwm( session_id, base_dir=None ):
    """
    Read the durable high-water mark; default on any miss/corruption (fail-open).

    Ensures:
        - Returns {"cursor_ts": <str|None>, "surfaced_ids": [<str>...]}
        - Missing file / bad JSON / non-dict / wrong field types → the empty
          default (never raises). Unlike the DM sibling there is NO `seeded` flag:
          a missing HWM means "surface everything owed" (ruling 3), not "seed silent."
    """
    path = _hwm_path( session_id, base_dir=base_dir )
    try:
        with open( path ) as f:
            data = json.load( f )
    except ( FileNotFoundError, OSError, json.JSONDecodeError ):
        return { "cursor_ts": None, "surfaced_ids": [] }
    if not isinstance( data, dict ):
        return { "cursor_ts": None, "surfaced_ids": [] }
    cursor = data.get( "cursor_ts" )
    ids    = data.get( "surfaced_ids" )
    return {
        "cursor_ts"    : cursor if isinstance( cursor, str ) else None,
        "surfaced_ids" : ids if isinstance( ids, list ) else [],
    }


def write_hwm( session_id, state, base_dir=None ):
    """
    Persist the high-water mark. Best-effort (returns False on OSError, never
    raises) — a failed persist just means the next pull re-surfaces + retries.
    """
    path = _hwm_path( session_id, base_dir=base_dir )
    try:
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "w" ) as f:
            json.dump( {
                "cursor_ts"    : state.get( "cursor_ts" ),
                "surfaced_ids" : list( state.get( "surfaced_ids", [] ) ),
            }, f )
        return True
    except OSError:
        return False


# ── Cross-process shared side-log (the §4.3 ledger's cross-process hop, K-D1) ──

def _surfaced_log_path( session_id, base_dir=None ):
    """Resolve the append-only side-log the LIVE listener arm writes and the hook folds."""
    suffix = ( session_id or "" )[ :8 ]
    return _base_dir( base_dir ) / SURFACED_LOG_TEMPLATE.format( session_id=suffix )


def append_surfaced_id( session_id, notification_id, base_dir=None ):
    """
    Append one live-surfaced notification_id to the shared side-log — called by the
    listener's :481 notification_responded arm (a DIFFERENT process than the hook).

    POSIX O_APPEND makes small-record writes atomic and lock-free across processes,
    so the listener never races the hook on this file. The hook is sole writer of
    the HWM JSON and folds this log in via reconcile_answers(extra_surfaced_ids=…)
    then compacts it under its own ownership. Best-effort; never raises.

    Requires:
        - session_id, notification_id are non-empty strings

    Ensures:
        - one "<notification_id>\\n" record appended atomically, or a silent no-op
    """
    if not session_id or not notification_id:
        return False
    path = _surfaced_log_path( session_id, base_dir=base_dir )
    try:
        path.parent.mkdir( parents=True, exist_ok=True )
        fd = os.open( str( path ), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644 )
        try:
            os.write( fd, ( str( notification_id ) + "\n" ).encode( "utf-8" ) )
        finally:
            os.close( fd )
        return True
    except OSError:
        return False


def read_surfaced_log( session_id, base_dir=None ):
    """
    Read the cross-process side-log's notification_ids (the ids the live listener
    arm surfaced). Missing file → [] (never raises).
    """
    path = _surfaced_log_path( session_id, base_dir=base_dir )
    try:
        with open( path ) as f:
            return [ line.strip() for line in f if line.strip() ]
    except ( FileNotFoundError, OSError ):
        return []


def _compact_surfaced_log( session_id, base_dir=None ):
    """
    Truncate the side-log after the hook has folded it into the durable HWM — the
    hook is the sole compactor (single-writer of the fold result). Best-effort.
    """
    path = _surfaced_log_path( session_id, base_dir=base_dir )
    try:
        if path.exists():
            path.write_text( "" )
    except OSError:
        pass


# ── Owed-answer fetch (X-API-Key hook lane — NEVER self._user_id) ──────────────

def _resolve_persona( session_id ):
    """
    Resolve THIS session's voice persona (the retrieval key, ruling 6) from the
    session bridge — the same lane the server-side stamp uses. Returns None on any
    failure (a persona-less session's answers are unretrievable by persona — the
    §4.4 accepted gap). Never raises.
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import get_voice_persona
        persona = get_voice_persona( ( session_id or "" )[ :8 ] )
        if persona and persona.get( "name" ):
            return persona.get( "name" )
    except Exception:
        pass
    return None


def _load_settings():
    from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
    try:
        return load_task_store_settings()
    except ValueError:
        return { "api_base_url": DEFAULT_API_BASE_URL, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS }


def _fetch_owed( persona, session_hash8, since=None, limit=DEFAULT_LIMIT, timeout=DEFAULT_TIMEOUT_SECONDS ):
    """
    GET /api/notifications/answers-owed (X-API-Key) — the answers owed to `persona`.

    ⚠️ Uses the X-API-Key lane (read_api_key / _request), which resolves to the
    human owner — NOT the listener's ambient service-account self._user_id. The
    query is persona-keyed, so no user_id crosses this boundary at all.

    Ensures:
        - Returns ( ok, rows, page_full )
        - ok False (rows=[], page_full=False) on any transport/HTTP failure or a
          non-dict body / non-list answers (fail-safe — caller surfaces nothing and
          does NOT advance the HWM)
        - Never raises
    """
    from lupin_cli.claude_code.hooks.lib import task_store_client as tc

    api_key  = tc.read_api_key()
    settings = _load_settings()
    params   = { "persona": persona, "limit": str( limit ) }
    if session_hash8:
        params[ "session_hash8" ] = session_hash8
    if since:
        params[ "since" ] = since
    url = f"{settings['api_base_url']}/api/notifications/answers-owed?{urllib.parse.urlencode( params )}"

    ok, _status, body = tc._request( "GET", url, api_key, timeout )
    if not ok or not isinstance( body, dict ):
        return False, [], False
    answers = body.get( "answers", [] )
    if not isinstance( answers, list ):
        return False, [], False
    return True, answers, len( answers ) >= limit


# ── IO shell (the one public entrypoint both drivers call) ─────────────────────

def surface_owed_answers( session_id, persona=None, extra_surfaced_ids=(), fetch_fn=None, base_dir=None ):
    """
    Reconcile this session's owed answers against the durable HWM + the live side-log
    and return the additionalContext of any un-surfaced answers. Called from BOTH
    cc_notification_listener._on_connected and user_prompt_submit.py.

    Requires:
        - session_id is the stable session id (or "" — returns "")
        - persona: the retrieval key; when None it is resolved from the session
          bridge (None ⇒ the persona-less accepted gap ⇒ returns "")
        - extra_surfaced_ids: additional ids to treat as already surfaced (tests /
          callers); the cross-process side-log is folded in automatically
        - fetch_fn(persona, session_hash8, since, limit) -> ( ok, rows, page_full );
          defaults to _fetch_owed (dependency-injected in tests)

    Ensures:
        - Returns the additionalContext string ("" when nothing fresh)
        - Folds the cross-process side-log (live listener arm) into the dedup, so a
          live-surfaced answer is NOT re-surfaced by catch-up (§4.3 one-ledger)
        - On a not-ok fetch: returns "" and does NOT advance the HWM (retry next)
        - Persists the advanced HWM and compacts the side-log on success
        - NO seed suppression (ruling 3) — first pull surfaces everything owed
        - Never raises (fail-open on the connect/turn hot path)
    """
    try:
        if not session_id:
            return ""
        hash8   = session_id[ :8 ]
        persona = persona or _resolve_persona( session_id )
        if not persona:
            return ""                                  # persona-less: unretrievable by persona (accepted gap)

        state = read_hwm( session_id, base_dir=base_dir )
        log_ids = read_surfaced_log( session_id, base_dir=base_dir )
        merged_extra = list( extra_surfaced_ids ) + log_ids

        if fetch_fn is None:
            fetch_fn = _fetch_owed
        ok, rows, page_full = fetch_fn( persona=persona, session_hash8=hash8,
                                        since=state.get( "cursor_ts" ), limit=DEFAULT_LIMIT )
        if not ok:
            return ""                                  # fail-open: no HWM advance, retry next

        context, new_state = reconcile_answers( hash8, rows, state, extra_surfaced_ids=merged_extra )
        write_hwm( session_id, new_state, base_dir=base_dir )
        _compact_surfaced_log( session_id, base_dir=base_dir )
        return context
    except Exception:
        return ""
