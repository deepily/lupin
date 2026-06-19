"""
Commons broadcast endpoints.

Per AC1 + AC2 + AC3 + AC4 + AC5 + AC14 of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md.

**Template**: `src/cosa/rest/routers/speakerphone.py` (per F4 REUSE).

Two endpoints:
- `GET /api/commons/active-sessions` — recipient-preview chip-row data
- `POST /api/commons/broadcast-to-cc-sessions` — fanout to active CC sessions

Design split:
- **Pure-logic helpers** (this module's `_*` and `*` non-route functions) are in
  the 100% coverage gate. All take dependencies explicitly — no module-level
  side effects, no FastAPI plumbing.
- **Route handlers** are thin dispatchers — they pull singletons from the module
  state and delegate to the helpers. Route bodies are `# pragma: no cover`'d to
  keep the gate enforceable from unit tests alone (per AC12: "endpoint
  integration tests do NOT contribute to the gate").
"""

import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.commons_ack_watcher import CommonsAckWatcher
from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    build_sender_id_for_cc,
    find_active_voice_persona_sessions,
)
from lupin_mcp.commons_persona_matcher import match_persona
from lupin_mcp.commons_store import CommonsStore

router = APIRouter( prefix="/api/commons", tags=[ "commons" ] )


# ─── Module-level state — initialized at FastAPI startup (step 8) ───────────

_commons_store         : Optional[ CommonsStore ]                  = None
_commons_rate_limiter  : Optional[ CommonsBroadcastRateLimiter ]   = None
_commons_ack_watcher   : Optional[ CommonsAckWatcher ]             = None
# Threshold for "active enough to receive a broadcast" — set at startup from INI.
_active_session_threshold_seconds : float = 600.0


def init_commons_state(
    store                              : CommonsStore,
    rate_limiter                       : CommonsBroadcastRateLimiter,
    ack_watcher                        : CommonsAckWatcher,
    active_session_threshold_seconds   : float,
) -> None:
    """Wire singletons at FastAPI startup. Idempotent for testing."""
    global _commons_store, _commons_rate_limiter, _commons_ack_watcher
    global _active_session_threshold_seconds
    _commons_store                    = store
    _commons_rate_limiter             = rate_limiter
    _commons_ack_watcher              = ack_watcher
    _active_session_threshold_seconds = float( active_session_threshold_seconds )


# ─── Pydantic models ────────────────────────────────────────────────────────


class BroadcastRequestBody( BaseModel ):
    """POST /broadcast-to-cc-sessions request body."""
    message            : str
    broadcast_id       : Optional[ str ] = None
    require_ack        : bool            = True
    include_originator : bool            = True


class RecipientResolutionError( BaseModel ):
    """
    422 response body when recipient resolution fails for an inter-session DM
    (`_resolve_dm_recipient`, the dm_send / POST /api/dm/send path; per Phase 0
    Q3-rev amendment 2026-05-15).

    Surfaces actionable feedback so the AI caller can self-correct without
    involving the human user. Fields:
    - `error`                      — categorical failure mode (Literal)
    - `supplied_persona`           — original input echoed back
    - `supplied_session_id`        — original input echoed back
    - `resolution_chain_attempted` — which resolution levels were tried
    - `candidate_alternatives`     — currently-active sessions the AI could
                                     try instead (sourced from commons_who()
                                     output at the moment of failure)
    - `suggested_next_action`      — one-sentence guidance string
    """
    error                       : str       = Field( ..., min_length=1 )
    supplied_persona            : Optional[ str ] = Field( default=None )
    supplied_session_id         : Optional[ str ] = Field( default=None )
    resolution_chain_attempted  : List[ str ]              = Field( default_factory=list )
    candidate_alternatives      : List[ Dict[ str, str ] ] = Field( default_factory=list )
    suggested_next_action       : str       = Field( ..., min_length=1 )


# ─── Pure-logic helpers (in 100% coverage gate) ─────────────────────────────


_UUIDV4_RE = re.compile( r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE )

_SYSTEM_REMINDER_OPEN_LC  = "<system-reminder>"
_SYSTEM_REMINDER_CLOSE_LC = "</system-reminder>"


def _body_contains_reminder_framing( body: str ) -> bool:
    """True if body has literal `<system-reminder>` / `</system-reminder>` (case-insensitive) — per T1."""
    lowered = body.lower()
    return _SYSTEM_REMINDER_OPEN_LC in lowered or _SYSTEM_REMINDER_CLOSE_LC in lowered


def validate_broadcast_body( message: Optional[ str ] ) -> Tuple[ bool, Optional[ str ] ]:
    """
    Validate the broadcast `message` field. Returns (valid, error_detail).
    Per AC1: empty/whitespace → 400; system-reminder substring → 400.
    """
    if not isinstance( message, str ) or not message.strip():
        return ( False, "message body is required" )
    if _body_contains_reminder_framing( message ):
        return ( False, "message must not contain system-reminder framing tags" )
    return ( True, None )


def validate_broadcast_id( broadcast_id: Optional[ str ] ) -> Tuple[ bool, Optional[ str ] ]:
    """
    Validate caller-supplied `broadcast_id`. None is allowed (server generates).
    Per AC1: invalid UUIDv4 shape → 400.
    """
    if broadcast_id is None:
        return ( True, None )
    if not isinstance( broadcast_id, str ) or not _UUIDV4_RE.match( broadcast_id ):
        return ( False, "broadcast_id must be a UUIDv4" )
    return ( True, None )


def build_pseudo_sender_id( user_id: str ) -> str:
    """
    Build the server-pseudo-sender-id used for `broadcasts` topic posts.
    Per AC4 + F8: `broadcast-<8-hex-of-sha256(user_id)>`. Hyphen, NEVER `@`
    (would fail `commons_store._HEADER_RE` round-trip).
    """
    digest = hashlib.sha256( user_id.encode( "utf-8" ) ).hexdigest()[ :8 ]
    return f"broadcast-{digest}"


def _load_bridge_fields( bridge_path: Any ) -> Optional[ Dict[ str, Any ] ]:
    """
    Open a bridge file and return its content as dict, or None on failure.
    Extracted so unit tests can mock at the source.
    """
    try:
        with open( bridge_path ) as f:
            return json.load( f )
    except ( json.JSONDecodeError, OSError ):
        return None


def _bridge_last_activity_epoch( bridge: Dict[ str, Any ] ) -> Optional[ float ]:
    """
    Extract the bridge's last-activity epoch seconds. Tries common field names;
    returns None if unparseable. Defensive against schema drift.

    2026-05-13 fix (per `src/rnd/v0.1.7/2026.05.13-broadcast-stale-bridge-phantom.md`):
    falls back to the nested `idle_detection.last_interaction_at` ISO string
    that the real bridge writer (`set_idle_detection_field` in
    `session_bridge.py:1055-1103`) actually populates. The previous lookup at
    top-level `last_activity_epoch` / `last_activity` / `updated_at` matched
    NONE of the fields the writer produces — `_bridge_last_activity_epoch`
    returned None for every bridge and the activity-age filter became a no-op,
    letting dead-PID phantoms through (inside Docker where the host-PID
    liveness check is disabled).
    """
    # Numeric epoch fields — checked first for back-compat with any future
    # writer that adds them.
    for field in ( "last_activity_epoch", "last_activity", "updated_at" ):
        val = bridge.get( field )
        if isinstance( val, ( int, float ) ):
            return float( val )
    # Fallback: ISO string under idle_detection (the field the writer actually uses).
    # Defensive against `idle_detection` being None / list / string (schema drift).
    idle = bridge.get( "idle_detection" )
    if not isinstance( idle, dict ):
        return None
    iso = idle.get( "last_interaction_at" )
    if isinstance( iso, str ) and iso:
        try:
            from datetime import datetime
            return datetime.fromisoformat( iso ).timestamp()
        except ValueError:
            return None
    return None


def project_session_response(
    session_id   : str,
    persona      : Dict[ str, Any ],
    bridge       : Dict[ str, Any ],
) -> Dict[ str, Any ]:
    """
    Build the response dict for one session per AC2 + T8.

    **NEVER includes the bridge Path or any filesystem-derived field.**
    Only these fields are exposed: session_id, persona_name, persona_icon,
    persona_color, last_seen_iso, speakerphone_on.
    """
    # 2026-05-13 fix: same projection mismatch as `_bridge_last_activity_epoch`.
    # Fall back to `idle_detection.last_interaction_at` so the API returns a real
    # ISO string instead of always-None. Per
    # `src/rnd/v0.1.7/2026.05.13-broadcast-stale-bridge-phantom.md`.
    # Defensive: `idle_detection` may be None / list / string under schema drift.
    idle_block = bridge.get( "idle_detection" )
    idle_iso   = idle_block.get( "last_interaction_at" ) if isinstance( idle_block, dict ) else None
    last_seen_iso = (
        bridge.get( "last_activity_iso" )
        or bridge.get( "updated_at_iso" )
        or idle_iso
    )
    return {
        "session_id"      : session_id,
        "persona_name"    : persona.get( "name" ),
        "persona_icon"    : persona.get( "icon" ),
        "persona_color"   : persona.get( "color" ),
        "last_seen_iso"   : last_seen_iso,
        "speakerphone_on" : bool( bridge.get( "speakerphone_on", False ) ),
    }


def filter_and_project_sessions(
    raw_sessions                      : List[ Tuple[ Any, str, Dict[ str, Any ] ] ],
    authenticated_user_id             : str,
    active_session_threshold_seconds  : float,
    now_epoch                         : float,
    bridge_loader                     : Callable[ [ Any ], Optional[ Dict[ str, Any ] ] ],
    originator_session_id             : Optional[ str ] = None,
    include_originator                : bool            = True,
    mtime_fn                          : Callable[ [ Any ], float ] = lambda p: p.stat().st_mtime,
) -> Tuple[ List[ Dict[ str, Any ] ], List[ Dict[ str, Any ] ] ]:
    """
    Apply all AC2 filters + T7 + T8 projection to the raw 3-tuple list.

    Returns `( included, filtered_out )` — fanout receipts (F3, 2026-06-11).
    Every gate that previously dropped a session SILENTLY now emits a
    `filtered_out` entry `{ "session_id", "reason" }` (the mtime gate adds
    `age_seconds` + `threshold_seconds`) so a broadcast miss is visible to the
    sender instead of vanishing. Reasons: `bridge_unreadable`,
    `owner_mismatch`, `stale_bridge_mtime`, `bridge_vanished`,
    `originator_excluded` (intentional, reported for completeness).
    See: src/rnd/v0.1.8/2026.06.10-broadcast-miss-duplicate-listener-root-cause.md §3

    1. Open each bridge via `bridge_loader` — skip on parse fail
    2. Filter by `owner_user_id == authenticated_user_id` (T7 + Q9 same-user scoping).
       **Graceful degradation (2026-05-13 fix carried forward to 2026-05-14)**:
       bridges that LACK an `owner_user_id` field pass through. The original
       2026-05-13 fix scoped on the listener's `user_id`, but that turned out
       to be the service-account identity (e.g. `claude.code@<repo>.deepily.ai`),
       NOT the human owner. For any human caller, every stamped bridge was
       therefore rejected — same UX symptom in reverse. Per
       `src/rnd/v0.1.7/2026.05.14-broadcast-listener-stamps-wrong-user-id.md`
       (Option C), scoping now reads a NEW `owner_user_id` field that the
       listener will eventually stamp with the HUMAN OWNER's UUID. Until the
       writer-side change (`_stamp_owner_user_id_on_bridge`) lands, every
       bridge hits the graceful branch and passes through — restoring the
       user's reported symptom from "1 of 4 visible" to "all 4 visible".
       Once the writer lands, the equality branch tightens automatically
       with zero code change here.
       (The legacy `user_id` field is preserved on the bridge for telemetry —
       it identifies the listener service account that wrote the bridge — but
       is no longer used for scoping.)
    3. Filter by LIVENESS (bridge-file mtime newer than threshold) — `mtime_fn`
       is injectable (defaults to `path.stat().st_mtime`) for filesystem-free
       unit tests, mirroring the `now_epoch_fn` injection in `execute_broadcast`.
       Replaces the pre-2026-06-05 `last_interaction_at` interaction-recency
       check so dormant-but-alive workers stay reachable by broadcast.
    4. Optionally exclude originator's session (when `include_originator=False`)
    5. Project to response shape via `project_session_response` (T8 — no Path leak)
    """
    out          : List[ Dict[ str, Any ] ] = [ ]
    filtered_out : List[ Dict[ str, Any ] ] = [ ]
    for path, sid, persona in raw_sessions:
        bridge = bridge_loader( path )
        if bridge is None:
            filtered_out.append( { "session_id": sid, "reason": "bridge_unreadable" } )
            continue
        bridge_owner_user_id = bridge.get( "owner_user_id" )
        # Graceful: include sessions whose bridge has NO owner_user_id field
        # (legacy / un-stamped). Reject only when the bridge has an
        # owner_user_id AND it doesn't match the caller. Once
        # `_stamp_owner_user_id_on_bridge` lands listener-side, the equality
        # branch tightens to strict cross-user isolation.
        if bridge_owner_user_id is not None and bridge_owner_user_id != authenticated_user_id:
            filtered_out.append( { "session_id": sid, "reason": "owner_mismatch" } )
            continue
        # Liveness filter (2026-06-05): key on bridge-file MTIME, not the bridge's
        # `idle_detection.last_interaction_at`. The idle-waiter heartbeat rewrites
        # the bridge on each backoff tick, so an alive-but-dormant session keeps a
        # FRESH mtime even with zero user interaction; a dead session's waiter exits
        # (PPID-death check) and the mtime freezes → ages past the threshold. Since
        # mtime >= last_interaction_at always, this can only INCLUDE MORE live
        # sessions than the old interaction-recency filter, never fewer — which is
        # the whole point: a broadcast must reach dormant-but-alive workers.
        # See src/rnd/v0.1.8/2026.06.05-broadcast-liveness-mtime-filter.md
        try:
            mtime_epoch = mtime_fn( path )
        except OSError:
            # TOCTOU: bridge vanished between enumeration and stat → treat as gone.
            filtered_out.append( { "session_id": sid, "reason": "bridge_vanished" } )
            continue
        if ( now_epoch - mtime_epoch ) > active_session_threshold_seconds:
            filtered_out.append( {
                "session_id"        : sid,
                "reason"            : "stale_bridge_mtime",
                "age_seconds"       : round( now_epoch - mtime_epoch, 1 ),
                "threshold_seconds" : active_session_threshold_seconds,
            } )
            continue
        if not include_originator and originator_session_id is not None and sid == originator_session_id:
            filtered_out.append( { "session_id": sid, "reason": "originator_excluded" } )
            continue
        out.append( project_session_response( sid, persona, bridge ) )
    return ( out, filtered_out )


def perform_fanout(
    broadcast_id          : str,
    message               : str,
    sessions              : List[ Dict[ str, Any ] ],
    sender_user_id        : str,
    store                 : CommonsStore,
    notification_queue    : Any,
    build_sender_id       : Callable[ [ str ], Optional[ str ] ],
) -> Tuple[ int, List[ str ] ]:
    """
    Per-recipient fanout: post to `broadcasts` topic + push `action:broadcast_received` notification.

    Per AC4 + AC5 + F10 (per-recipient failure isolation): if `push_notification`
    fails for recipient K, log + continue. Returns `(successful_count, failed_recipient_sids)`.
    """
    pseudo_sid = build_pseudo_sender_id( sender_user_id )
    successful = 0
    failed: List[ str ] = [ ]
    for s in sessions:
        target_sid = s[ "session_id" ]
        # AC4: per-recipient broadcasts entry
        try:
            store.post(
                topic             = "broadcasts",
                body              = message,
                sender_session_id = pseudo_sid,
                persona_name      = "System Broadcast",
                persona_icon      = "📢",
                persona_color     = "#FFC107",
                metadata          = {
                    "broadcast_id"     : broadcast_id,
                    "target_session_id": target_sid,
                    "sender_user_id"   : sender_user_id,
                },
            )
        except Exception:
            failed.append( target_sid )
            continue
        # AC5: per-session listener notification
        try:
            notification_queue.push_notification(
                message            = "",
                type               = "user_initiated_message",
                title              = "action:broadcast_received",
                sender_id          = build_sender_id( target_sid ),
                job_id             = target_sid[ :8 ],
                user_id            = sender_user_id,
                suppress_ding      = True,
                response_requested = False,
                payload            = {
                    "broadcast_id"   : broadcast_id,
                    "body"           : message,
                    "sender_user_id" : sender_user_id,
                },
            )
            successful += 1
        except Exception:
            failed.append( target_sid )
    return ( successful, failed )


def execute_broadcast(
    *,
    authenticated_user_id              : str,
    body                               : BroadcastRequestBody,
    store                              : CommonsStore,
    rate_limiter                       : CommonsBroadcastRateLimiter,
    ack_watcher                        : CommonsAckWatcher,
    notification_queue                 : Any,
    active_session_threshold_seconds   : float,
    raw_sessions_fn                    : Callable[ [ ], List[ Tuple[ Any, str, Dict[ str, Any ] ] ] ],
    bridge_loader                      : Callable[ [ Any ], Optional[ Dict[ str, Any ] ] ],
    build_sender_id                    : Callable[ [ str ], Optional[ str ] ],
    now_epoch_fn                       : Callable[ [ ], float ] = time.time,
    mtime_fn                           : Callable[ [ Any ], float ] = lambda p: p.stat().st_mtime,
) -> Dict[ str, Any ]:
    """
    Full broadcast execution pipeline — pure-logic core of the POST endpoint.

    Returns a dict with one of these shapes:
      {"http_status": 400, "detail": "..."}
      {"http_status": 429, "retry_after": float}
      {"http_status": 409, "detail": "broadcast_id collision"}
      {"http_status": 200, "broadcast_id": "...", "recipients": int, "failed_recipients": [...],
       "filtered_out": [...], "status": "..."}

    `filtered_out` (F3 fanout receipts, 2026-06-11) lists every enumerated
    session the recipient filter dropped, with the reason — so a silent
    broadcast miss (e.g. the 8h mtime gate) is visible to the sender. Present
    in BOTH 200 shapes; the zero-recipient response is the case the receipts
    exist for.

    Raises nothing — all error states are returned as dicts for the route
    handler to translate into FastAPI responses.
    """
    # AC1: body validation
    ok, err = validate_broadcast_body( body.message )
    if not ok:
        return { "http_status": 400, "detail": err }
    ok, err = validate_broadcast_id( body.broadcast_id )
    if not ok:
        return { "http_status": 400, "detail": err }

    # AC3: rate limit
    allowed, retry_after = rate_limiter.check_and_record( authenticated_user_id )
    if not allowed:
        return { "http_status": 429, "retry_after": retry_after }

    # AC1 + T9: atomic register (collision → 409)
    broadcast_id = body.broadcast_id or str( uuid.uuid4() )
    if body.require_ack:
        try:
            ack_watcher.register_broadcast( broadcast_id, authenticated_user_id, expected_recipients=0 )
        except ValueError:
            return { "http_status": 409, "detail": "broadcast_id collision" }

    # AC2: enumerate + filter recipients (filtered_out = F3 fanout receipts)
    sessions, filtered_out = filter_and_project_sessions(
        raw_sessions                     = raw_sessions_fn(),
        authenticated_user_id            = authenticated_user_id,
        active_session_threshold_seconds = active_session_threshold_seconds,
        now_epoch                        = now_epoch_fn(),
        bridge_loader                    = bridge_loader,
        originator_session_id            = None,
        include_originator               = body.include_originator,
        mtime_fn                         = mtime_fn,
    )

    # AC2 / Q14: zero recipients
    if not sessions:
        if body.require_ack:
            ack_watcher.unregister_broadcast( broadcast_id )
        return {
            "http_status"       : 200,
            "broadcast_id"      : broadcast_id,
            "recipients"        : 0,
            "failed_recipients" : [ ],
            "filtered_out"      : filtered_out,
            "status"            : "no-active-sessions",
        }

    # AC4 + AC5: fanout
    successful, failed_recipients = perform_fanout(
        broadcast_id       = broadcast_id,
        message            = body.message,
        sessions           = sessions,
        sender_user_id     = authenticated_user_id,
        store              = store,
        notification_queue = notification_queue,
        build_sender_id    = build_sender_id,
    )

    # Update expected_recipients on in-flight entry now that we know N
    if body.require_ack:
        entry = ack_watcher._in_flight.get( broadcast_id )
        if entry is not None:
            entry.expected_recipients = len( sessions )

    return {
        "http_status"       : 200,
        "broadcast_id"      : broadcast_id,
        "recipients"        : successful,
        "failed_recipients" : failed_recipients,
        "filtered_out"      : filtered_out,
        "status"            : "queued",
    }


# ─── Phase 2.5/3.5 Step 2: broadcast-history aggregator helpers ─────────────
# Per src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (AC1 + AC4-AC6).


_RESERVED_TOPICS = { "broadcasts", "broadcast-acks", "presence", "system-events" }


def _entry_passes_same_user_scoping(
    entry                 : Dict[ str, Any ],
    authenticated_user_id : str,
    user_session_ids      : Set[ str ],
    bridge_owner_lookup   : Callable[ [ str ], Optional[ str ] ],
) -> bool:
    """
    Per-entry same-user scoping check.

    Mirrors the graceful-degradation pattern from `filter_and_project_sessions`
    (broadcast filter — Q1 of `2026.05.14-broadcast-listener-stamps-wrong-user-id.md`).

    Returns True iff at least one is satisfied:
      1. `entry.metadata.sender_user_id == authenticated_user_id` (direct attribution —
         e.g. `broadcasts` topic where `perform_fanout` stamps the sender's UUID per AC4
         of the Phase 2 broadcast design)
      2. `entry.metadata.target_session_id` is in `user_session_ids` (you-as-recipient —
         e.g. per-recipient `broadcasts` fanout entries OR broadcast-acks targeting you)
      3. `bridge_owner_lookup(entry.sender_session_id)` matches the caller, OR the lookup
         returns `None` (graceful fallback — bridges lacking `owner_user_id` pass through,
         same pattern as the broadcast-recipient filter; tightens to strict isolation
         once every listener bridge stamps `owner_user_id`)
    """
    md = entry.get( "metadata" ) or { }
    # Branch 1: direct sender-user attribution
    if md.get( "sender_user_id" ) == authenticated_user_id:
        return True
    # Branch 2: target-session attribution
    target_sid = md.get( "target_session_id" )
    if target_sid and target_sid in user_session_ids:
        return True
    # Branch 3: bridge-owner attribution (graceful fallback for un-stamped bridges)
    sender_sid = entry.get( "sender_session_id" )
    if sender_sid:
        owner = bridge_owner_lookup( sender_sid )
        if owner is None:
            return True
        if owner == authenticated_user_id:
            return True
    return False


def _project_history_entry( entry: Dict[ str, Any ], topic: str ) -> Dict[ str, Any ]:
    """
    Build the response shape for one history entry.

    Per AC1 + AC5 + AC6: includes `topic` + `topic_kind` so the frontend can render
    the topic-chip-prefix for free-form topics (Q2 ratified — non-reserved get a chip).
    """
    return {
        "ts"                : entry.get( "ts" ),
        "topic"             : topic,
        "topic_kind"        : "reserved" if topic in _RESERVED_TOPICS else "free-form",
        "sender_session_id" : entry.get( "sender_session_id" ),
        "persona_name"      : entry.get( "persona_name" ),
        "persona_icon"      : entry.get( "persona_icon" ),
        "persona_color"     : entry.get( "persona_color" ),
        "body"              : entry.get( "body" ),
        "metadata"          : entry.get( "metadata" ) or { },
    }


def _resolve_since_cutoff(
    since_iso  : Optional[ str ],
    hours      : Optional[ float ],
    now_iso_fn : Callable[ [ ], str ],
) -> Optional[ str ]:
    """
    Resolve the effective `since` cutoff from caller-supplied parameters.

    - If `since_iso` is supplied, use it directly.
    - Else if `hours` is supplied, compute (now - hours) and return its ISO form.
    - Else return None (no cutoff — return all retained entries).

    `now_iso_fn` is injected for testability.
    """
    if since_iso:
        return since_iso
    if hours is not None:
        now_dt = datetime.fromisoformat( now_iso_fn().replace( "Z", "+00:00" ) )
        return ( now_dt - timedelta( hours=hours ) ).isoformat()
    return None


def _dedupe_broadcasts_by_id(
    merged: List[ Tuple[ str, Dict[ str, Any ] ] ],
) -> List[ Tuple[ str, Dict[ str, Any ] ] ]:
    """
    Collapse per-recipient `broadcasts`-topic fanout rows into one row per
    `metadata.broadcast_id`, keeping the first occurrence (newest after the
    DESC sort upstream).

    Required by the Recent Activity surface
    (`src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md`):
    Phase 2's `perform_fanout` (this module, line ~348) writes ONE `broadcasts`
    row per recipient by design — supports the `target_session_id` branch of
    `_entry_passes_same_user_scoping`. For an admin-overview stream those N
    rows are noise; the admin wants "one broadcast = one row".

    Mutation contract: input list is read-only. The kept entry is shallow-copied
    with `target_session_id` stripped from its `metadata` — the dedup'd row
    represents the broadcast as a whole, not any one recipient slice.

    Non-`broadcasts` topics pass through unchanged (e.g. `broadcast-acks`
    per-recipient rows are the intended chip-row UX). Broadcasts-topic entries
    missing `metadata.broadcast_id` pass through unchanged (defensive — a
    malformed entry shouldn't disappear silently).
    """
    seen_broadcast_ids : Set[ str ]                              = set()
    out                : List[ Tuple[ str, Dict[ str, Any ] ] ] = [ ]
    for ( topic, entry ) in merged:
        if topic != "broadcasts":
            out.append( ( topic, entry ) )
            continue
        md  = entry.get( "metadata" ) or { }
        bid = md.get( "broadcast_id" )
        if not isinstance( bid, str ):
            out.append( ( topic, entry ) )
            continue
        if bid in seen_broadcast_ids:
            continue
        seen_broadcast_ids.add( bid )
        new_md             = { k: v for k, v in md.items() if k != "target_session_id" }
        new_entry          = dict( entry )
        new_entry[ "metadata" ] = new_md
        out.append( ( topic, new_entry ) )
    return out


def _dedupe_broadcast_acks_by_recipient(
    merged: List[ Tuple[ str, Dict[ str, Any ] ] ],
) -> List[ Tuple[ str, Dict[ str, Any ] ] ]:
    """
    Collapse `broadcast-acks`-topic rows that share `(broadcast_id,
    sender_session_id, metadata.status)` down to a single row, keeping the
    first occurrence (newest after the DESC sort upstream).

    Symptom case: a single recipient session writes the same ack 3-4× within
    milliseconds (e.g. status="completed" for the same broadcast_id from the
    same sender_session_id). Observed in production
    `io/commons/broadcast-acks.md` on 2026-05-15 around 15:16:43Z, where one
    recipient logged three identical `status="completed"` rows for broadcast
    `adedc24b…` at .852328 / .852596 / .854790 — bodies and metadata
    bit-identical.

    Sister to `_dedupe_broadcasts_by_id` — same shape, different key. The
    underlying write-side multiplicity (something is causing N
    `notification_queue_update` deliveries → N `_handle_broadcast_received`
    → N `_post_ack` calls in `src/lupin_mcp/broadcast_handler.py`) is a
    SEPARATE investigation; this consumer-side filter is the agreed-upon
    shipping fix per Rick's voice direction (2026-05-15 evening, session
    06aba5f7 Arnold 🪨), following the precedent set by the broadcasts-topic
    dedupe (`_dedupe_broadcasts_by_id`) that landed earlier the same day in
    session c4139ece (María 🌸). Bug filing in `bug-fix-queue.md` rev
    2026-05-15 captures the four ranked plausible causes for the write-side
    multiplicity that next investigation should run with.

    Mutation contract: input list is read-only. Only `broadcast-acks` topic
    entries with all three keys present are subject to dedup. Defensive
    passthrough on any missing/non-string key (a malformed entry shouldn't
    disappear silently).

    Non-`broadcast-acks` topics pass through unchanged.
    """
    seen_keys : Set[ Tuple[ str, str, str ] ]            = set()
    out       : List[ Tuple[ str, Dict[ str, Any ] ] ]   = [ ]
    for ( topic, entry ) in merged:
        if topic != "broadcast-acks":
            out.append( ( topic, entry ) )
            continue
        md  = entry.get( "metadata" ) or { }
        bid = md.get( "broadcast_id" )
        sid = entry.get( "sender_session_id" )
        st  = md.get( "status" )
        if not ( isinstance( bid, str ) and isinstance( sid, str ) and isinstance( st, str ) ):
            out.append( ( topic, entry ) )
            continue
        key = ( bid, sid, st )
        if key in seen_keys:
            continue
        seen_keys.add( key )
        out.append( ( topic, entry ) )
    return out


def execute_broadcast_history(
    *,
    authenticated_user_id : str,
    store                 : Any,                                          # CommonsStore
    since_iso             : Optional[ str ],
    hours                 : Optional[ float ],
    limit                 : int,
    excluded_topics       : List[ str ],
    max_entries_ceiling   : int,
    user_session_ids_fn   : Callable[ [ ], Set[ str ] ],
    bridge_owner_lookup   : Callable[ [ str ], Optional[ str ] ],
    now_iso_fn            : Callable[ [ ], str ] = lambda: datetime.now( timezone.utc ).isoformat( timespec="microseconds" ),
) -> Dict[ str, Any ]:
    """
    Aggregate commons entries across topics for the broadcast-card Recent Activity stream.

    Per `src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md` (AC1, AC4, AC5,
    AC6, AC9). Ratifications:
      Q2 — topic chips for free-form topics (kept in projection via `topic_kind`)
      Q5 — `presence` + `system-events` excluded by default (caller-supplied
            `excluded_topics` enforces this)
      Q6 — `hours` window mirrors the existing history-window dropdown semantics
      Q7 — flat reverse-chronological (sorted by `ts` DESC across topics)

    Pipeline:
      1. Resolve effective `since` cutoff from (`since_iso`, `hours`).
      2. Enumerate active topics via `store._all_topic_names()`, drop excluded.
      3. For each topic, fetch entries via `store.read(t, since=cutoff, limit=max_ceiling)`.
      4. Apply per-entry same-user scoping via `_entry_passes_same_user_scoping`.
      5. Merge across topics, sort newest-first.
      6. Cap to `min(limit, max_entries_ceiling)`.
      7. Project to the response shape via `_project_history_entry`.

    Returns:
        {
            "entries"     : [ ...projected entries, newest first... ],
            "since_used"  : "<iso>" | None,
            "next_cursor" : None,    # v1 — pagination deferred per design "Open follow-ups"
        }
    """
    cutoff_iso = _resolve_since_cutoff( since_iso, hours, now_iso_fn )

    all_topics       = store._all_topic_names()
    excluded_set     = set( excluded_topics )
    included_topics  = [ t for t in all_topics if t not in excluded_set ]

    user_session_ids = user_session_ids_fn()

    merged: List[ Tuple[ str, Dict[ str, Any ] ] ] = [ ]
    for t in included_topics:
        try:
            raw_entries = store.read( t, since=cutoff_iso, limit=max_entries_ceiling )
        except FileNotFoundError:
            continue
        for e in raw_entries:
            if _entry_passes_same_user_scoping( e, authenticated_user_id, user_session_ids, bridge_owner_lookup ):
                merged.append( ( t, e ) )

    # Sort by ts DESC across all topics (commons store sorts per-topic but ASC when `since` supplied —
    # we need a single global reverse-chrono ordering after merge).
    merged.sort( key=lambda pair: pair[ 1 ].get( "ts" ) or "", reverse=True )

    # Collapse per-recipient `broadcasts` fanout rows: one admin-overview row per broadcast_id.
    # Must precede the limit cap or a small limit truncates within a single broadcast's fanout set.
    merged = _dedupe_broadcasts_by_id( merged )

    # Collapse same-recipient repeated `broadcast-acks` rows: 3-4× write-side multiplicity
    # observed in production (see `_dedupe_broadcast_acks_by_recipient` docstring for the
    # 2026-05-15 forensic data + the ranked write-side root-cause candidates that the next
    # bug-fix-queue cycle should run with).
    merged = _dedupe_broadcast_acks_by_recipient( merged )

    effective_limit = min( limit, max_entries_ceiling )
    merged          = merged[ :effective_limit ]

    entries = [ _project_history_entry( e, t ) for ( t, e ) in merged ]

    return {
        "entries"     : entries,
        "since_used"  : cutoff_iso,
        "next_cursor" : None,
    }


# ─── DM recipient-resolution helpers ───────────────────────────────────────


def _session_id_matches( canonical: Optional[ str ], supplied: str ) -> bool:
    """
    True when a supplied recipient session id addresses a candidate's canonical
    session id, tolerating the short/full forms a session advertises about
    itself (bug d57dbfea).

    `get_session_info()` reports a session's `session_id` in SHORT (8-char)
    form, while the bridge scan keys candidates on the FULL `stable_session_id`.
    So a manager replying to a worker that advertised its short id supplies a
    PREFIX of the candidate's canonical id — exact equality would miss it. This
    is the only addressing channel for a null-persona worker (no name to resolve
    by), so prefix tolerance is what makes it reachable.

    Exact equality is tried first; otherwise the shorter of the two must be a
    >= 8-char prefix of the longer. The 8-char floor avoids a 1-2 char id
    colliding with every candidate. Ambiguity (more than one candidate matching
    a short prefix) is detected and reported by the caller, not collapsed here.

    Requires:
        - supplied is a non-empty string (pydantic enforces min_length=1)

    Ensures:
        - returns True iff canonical == supplied, OR the shorter of the pair is
          a >= 8-char prefix of the longer
        - returns False when canonical is falsy (a null-persona candidate still
          carries a real session_id, so this only guards genuinely-empty ids)
        - never raises
    """
    if not canonical or not supplied:
        return False
    if canonical == supplied:
        return True
    shorter, longer = sorted( ( canonical, supplied ), key=len )
    return len( shorter ) >= 8 and longer.startswith( shorter )


def _resolve_dm_recipient(
    *,
    recipient_session_id  : Optional[ str ],
    recipient_persona     : Optional[ str ],
    authenticated_user_id : str,
    raw_sessions_fn       : Callable[ [ ], List[ Tuple[ Any, str, Dict[ str, Any ] ] ] ],
    bridge_loader         : Callable[ [ Any ], Optional[ Dict[ str, Any ] ] ],
    active_session_threshold_seconds : float,
    now_epoch_fn          : Callable[ [ ], float ] = time.time,
    mtime_fn              : Callable[ [ Any ], float ] = lambda p: p.stat().st_mtime,
) -> Dict[ str, Any ]:
    """
    Resolve an inter-session DM recipient to a concrete session_id + persona_name.

    Per Phase 0 Q3-rev (2026-05-15 ratified):
    - session_id takes precedence over persona when both supplied
    - persona resolution chain: exact → case-insensitive → punct/whitespace-tolerant
      (PHI-4 LLM disambiguator stubbed for v1; can be wired in v1.1)
    - Failures return 422 with rich `RecipientResolutionError` body so the AI
      caller can self-correct (Rick's amendment).

    Same-user scoping via `filter_and_project_sessions` (Phase 2 T7 inheritance).

    Returns:
      {"http_status": 200, "session_id": str, "persona_name": str | None}
      {"http_status": 422, "detail": <RecipientResolutionError model_dump>}
    """
    active_sessions, _filtered_out = filter_and_project_sessions(
        raw_sessions                     = raw_sessions_fn(),
        authenticated_user_id            = authenticated_user_id,
        active_session_threshold_seconds = active_session_threshold_seconds,
        now_epoch                        = now_epoch_fn(),
        bridge_loader                    = bridge_loader,
        originator_session_id            = None,
        include_originator               = True,
        mtime_fn                         = mtime_fn,
    )

    candidate_alternatives = [
        {
            "persona"      : str( s.get( "persona_name" ) or "" ),
            "session_id"   : str( s.get( "session_id" ) or "" ),
            "active_since" : str( s.get( "last_seen_iso" ) or "" ),
        }
        for s in active_sessions
    ]

    if recipient_session_id is not None:
        # Short/full-tolerant matching (d57dbfea): a worker advertises its SHORT
        # session id, but candidates are keyed on the FULL canonical id. Collect
        # every candidate the supplied id addresses; resolve only when exactly
        # one does (an ambiguous short prefix is reported, not silently picked).
        matches = [ s for s in active_sessions if _session_id_matches( s.get( "session_id" ), recipient_session_id ) ]
        if len( matches ) == 1:
            match = matches[ 0 ]
            return {
                "http_status"  : 200,
                "session_id"   : str( match.get( "session_id" ) ),
                "persona_name" : match.get( "persona_name" ),
            }
        if len( matches ) > 1:
            err = RecipientResolutionError(
                error                      = "recipient_session_id_ambiguous",
                supplied_persona           = recipient_persona,
                supplied_session_id        = recipient_session_id,
                resolution_chain_attempted = [ "session_id_direct", "session_id_prefix" ],
                candidate_alternatives     = candidate_alternatives,
                suggested_next_action      = "The supplied recipient_session_id is a prefix of more than one active session; supply the full session id (call commons_who() to list them).",
            )
            return { "http_status": 422, "detail": err.model_dump() }
        err = RecipientResolutionError(
            error                      = "recipient_inactive",
            supplied_persona           = recipient_persona,
            supplied_session_id        = recipient_session_id,
            resolution_chain_attempted = [ "session_id_direct", "session_id_prefix" ],
            candidate_alternatives     = candidate_alternatives,
            suggested_next_action      = "Call commons_who() to enumerate currently-active sessions; the supplied recipient_session_id is not present (or owned by a different user).",
        )
        return { "http_status": 422, "detail": err.model_dump() }

    if recipient_persona is not None:
        candidate_personas = [ s.get( "persona_name", "" ) for s in active_sessions if s.get( "persona_name" ) ]
        # T7-style isolation: `match_persona` can hit the LLM disambiguator chain
        # (Phase 3 wiring) which may raise on PHI-4 model unavailability, network
        # failures, or Haiku stub NotImplementedError. Treat any disambiguator
        # exception as "could not resolve" and fall through to the 422 path so
        # the AI caller gets a clean error contract instead of a 500.
        try:
            matched_persona = match_persona( recipient_persona, candidate_personas )
        except Exception:
            matched_persona = None
        if matched_persona is None:
            err = RecipientResolutionError(
                error                      = "recipient_not_found",
                supplied_persona           = recipient_persona,
                supplied_session_id        = None,
                resolution_chain_attempted = [ "exact", "case_insensitive", "punct_tolerant" ],
                candidate_alternatives     = candidate_alternatives,
                suggested_next_action      = "No active session matched the persona. Call commons_who() to list active personas, or supply recipient_session_id directly.",
            )
            return { "http_status": 422, "detail": err.model_dump() }
        match = next( ( s for s in active_sessions if s.get( "persona_name" ) == matched_persona ), None )
        if match is None:
            err = RecipientResolutionError(
                error                      = "recipient_not_found",
                supplied_persona           = recipient_persona,
                supplied_session_id        = None,
                resolution_chain_attempted = [ "exact", "case_insensitive", "punct_tolerant" ],
                candidate_alternatives     = candidate_alternatives,
                suggested_next_action      = "Internal: persona matched but session lookup failed. Retry shortly.",
            )
            return { "http_status": 422, "detail": err.model_dump() }
        return {
            "http_status"  : 200,
            "session_id"   : str( match.get( "session_id" ) ),
            "persona_name" : matched_persona,
        }

    err = RecipientResolutionError(
        error                      = "recipient_required",
        supplied_persona           = None,
        supplied_session_id        = None,
        resolution_chain_attempted = [ ],
        candidate_alternatives     = candidate_alternatives,
        suggested_next_action      = "Supply either recipient_session_id or recipient_persona on the request body.",
    )
    return { "http_status": 422, "detail": err.model_dump() }


# ─── Dependency-injection accessors ─────────────────────────────────────────


def get_notification_queue():
    """DI: return the singleton NotificationFifoQueue from main module."""
    import lupin_app.main as main_module
    return main_module.jobs_notification_queue


def _require_initialized():
    """Raise if commons singletons not yet wired (step 8 wires them at app startup)."""
    if _commons_store is None or _commons_rate_limiter is None or _commons_ack_watcher is None:
        raise HTTPException( status_code=503, detail="commons subsystem not initialized" )


# ─── Route handlers (thin — # pragma: no cover) ─────────────────────────────


@router.get(
    "/active-sessions",
    summary     = "List active CC sessions belonging to the authenticated user",
    description = "Returns same-user-scoped active sessions with persona info for the broadcast recipient preview.",
)
async def get_active_sessions(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
) -> JSONResponse:
    _require_initialized()
    # FM-7 mitigation: the bridge-dir enumeration + per-bridge file reads are blocking
    # I/O; run them OFF the event loop (asyncio.to_thread) so the commons-who flood
    # can't stall the shared :7999 loop under fleet load. Mirrors broadcast (below).
    def _collect_sessions():
        included, _filtered_out = filter_and_project_sessions(
            raw_sessions                     = find_active_voice_persona_sessions(),
            authenticated_user_id            = authenticated_user_id,
            active_session_threshold_seconds = _active_session_threshold_seconds,
            now_epoch                        = time.time(),
            bridge_loader                    = _load_bridge_fields,
            originator_session_id            = None,
            include_originator               = True,
        )
        return included
    sessions = await asyncio.to_thread( _collect_sessions )
    return JSONResponse( content={ "sessions": sessions } )


@router.post(
    "/broadcast-to-cc-sessions",
    summary     = "Fan out a broadcast to active CC sessions belonging to the authenticated user",
    description = "Posts a per-recipient `broadcasts` entry + a per-session listener notification for each active CC session belonging to the caller. Returns the broadcast_id + recipient count + any failed recipients.",
)
async def post_broadcast_to_cc_sessions(   # pragma: no cover
    body: BroadcastRequestBody,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    notification_queue=Depends( get_notification_queue ),
) -> JSONResponse:
    _require_initialized()
    # Lever B (messaging plane): run the blocking store-write + fan-out I/O OFF the
    # event loop (asyncio.to_thread) so the commons-broadcast flood can't stall the
    # shared :7999 loop under fleet load (the other named FM-7 contributor).
    result = await asyncio.to_thread(
        execute_broadcast,
        authenticated_user_id            = authenticated_user_id,
        body                             = body,
        store                            = _commons_store,
        rate_limiter                     = _commons_rate_limiter,
        ack_watcher                      = _commons_ack_watcher,
        notification_queue               = notification_queue,
        active_session_threshold_seconds = _active_session_threshold_seconds,
        raw_sessions_fn                  = find_active_voice_persona_sessions,
        bridge_loader                    = _load_bridge_fields,
        build_sender_id                  = build_sender_id_for_cc,
    )
    http_status = result.pop( "http_status" )
    if http_status == 429:
        retry_after = result[ "retry_after" ]
        raise HTTPException(
            status_code = 429,
            detail      = "rate limit exceeded",
            headers     = { "Retry-After": str( int( retry_after ) + 1 ) },
        )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=200, content=result )


# ─── broadcast-history endpoint ─────────────────────────────────────────────


@router.get(
    "/broadcast-history",
    summary     = "List recent commons traffic for the broadcast-card Recent Activity surface",
    description = "Aggregates entries across all commons topics (excluding the configurable blacklist — defaults to presence + system-events) and returns them newest-first, scoped to the authenticated user. Powers the broadcast-card Recent Activity stream. Per src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (AC1, AC4-AC6).",
)
async def get_broadcast_history(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    since                : Optional[ str ]   = None,
    hours                : Optional[ float ] = None,
    limit                : int               = 200,
) -> JSONResponse:
    _require_initialized()
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    # AC2 — INI feature flag (default True per Q9; flip to False for kill-switch)
    if not config_mgr.get( "commons traffic visibility enabled", return_type="boolean" ):
        return JSONResponse( content={
            "entries"     : [ ],
            "since_used"  : None,
            "next_cursor" : None,
            "disabled"    : True,
        } )

    excluded_topics_raw = config_mgr.get( "commons traffic visibility exclude topics" ) or ""
    excluded_topics     = [ t.strip() for t in excluded_topics_raw.split( "," ) if t.strip() ]
    max_entries_ceiling = int( config_mgr.get( "commons traffic visibility max entries per response", return_type="int" ) )

    # FM-7 mitigation: the one-pass bridge enumeration + the all-topics history read
    # are blocking file I/O; run them OFF the event loop (asyncio.to_thread) so the
    # Recent-Activity poll can't stall the shared :7999 loop. Mirrors broadcast (above).
    def _collect_history():
        # One-pass bridge enumeration: session_id → owner_user_id map. Used by BOTH
        # the user-session resolver (for target_session_id attribution) AND the
        # per-entry bridge_owner_lookup. Avoids walking the bridge dir twice.
        bridge_owner_map: Dict[ str, Optional[ str ] ] = { }
        for path, sid, _persona in find_active_voice_persona_sessions():
            bridge = _load_bridge_fields( path )
            if bridge is not None:
                bridge_owner_map[ sid ] = bridge.get( "owner_user_id" )

        def _user_session_ids():
            # Same graceful-degradation pattern as filter_and_project_sessions:
            # bridges with owner_user_id=None are treated as belonging to ANY user
            # (un-stamped legacy bridges pass through).
            return {
                sid for sid, owner in bridge_owner_map.items()
                if owner is None or owner == authenticated_user_id
            }

        def _bridge_owner_lookup( session_id ):
            # Returns the bridge's owner_user_id, or None for both
            # "session not in map" and "bridge has no owner_user_id".
            return bridge_owner_map.get( session_id )

        return execute_broadcast_history(
            authenticated_user_id = authenticated_user_id,
            store                 = _commons_store,
            since_iso             = since,
            hours                 = hours,
            limit                 = limit,
            excluded_topics       = excluded_topics,
            max_entries_ceiling   = max_entries_ceiling,
            user_session_ids_fn   = _user_session_ids,
            bridge_owner_lookup   = _bridge_owner_lookup,
        )

    result = await asyncio.to_thread( _collect_history )
    return JSONResponse( content=result )


