"""
Commons broadcast endpoints.

Design: `src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md`.

The template for this module is `src/cosa/rest/routers/speakerphone.py`.

Two endpoints:
- `GET /api/commons/active-sessions` returns the recipient-preview chip-row data.
- `POST /api/commons/broadcast-to-cc-sessions` fans a message out to active CC sessions.

Design split:
- **Pure-logic helpers** (the `_*` and other non-route functions in this module) are in
  the 100% coverage gate. They take their dependencies explicitly. They have no
  module-level side effects and no FastAPI plumbing.
- **Route handlers** are thin dispatchers. They pull singletons from the module
  state and delegate to the helpers. Route bodies are `# pragma: no cover`, which
  keeps the gate enforceable from unit tests alone. Endpoint integration tests do
  not contribute to the gate.
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
    422 response body when a recipient cannot be resolved for an inter-session DM.

    It is raised by `_resolve_dm_recipient`, on the dm_send and POST /api/dm/send path.
    It gives the AI caller actionable feedback, so the caller can self-correct without
    involving the human user. Fields:
    - `error`                      — categorical failure mode (Literal)
    - `supplied_persona`           — original input echoed back
    - `supplied_session_id`        — original input echoed back
    - `resolution_chain_attempted` — which resolution levels were tried
    - `candidate_alternatives`     — currently-active sessions the AI could
                                     try instead (sourced from commons_who()
                                     output at the moment of failure)
    - `session_id_only_candidates` — active sessions with no persona (released or never
                                     named). They are addressable by `recipient_session_id`
                                     only. They stay out of `candidate_alternatives` so a
                                     nameless row is not mistaken for corruption.
    - `suggested_next_action`      — one-sentence guidance string

    """
    error                       : str       = Field( ..., min_length=1 )
    supplied_persona            : Optional[ str ] = Field( default=None )
    supplied_session_id         : Optional[ str ] = Field( default=None )
    resolution_chain_attempted  : List[ str ]              = Field( default_factory=list )
    candidate_alternatives      : List[ Dict[ str, str ] ] = Field( default_factory=list )
    session_id_only_candidates  : List[ Dict[ str, str ] ] = Field( default_factory=list )
    suggested_next_action       : str       = Field( ..., min_length=1 )


# ─── Pure-logic helpers (in 100% coverage gate) ─────────────────────────────


_UUIDV4_RE = re.compile( r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE )

_SYSTEM_REMINDER_OPEN_LC  = "<system-reminder>"
_SYSTEM_REMINDER_CLOSE_LC = "</system-reminder>"


def _body_contains_reminder_framing( body: str ) -> bool:
    """True if the body holds a `<system-reminder>` or `</system-reminder>` tag, ignoring case."""
    lowered = body.lower()
    return _SYSTEM_REMINDER_OPEN_LC in lowered or _SYSTEM_REMINDER_CLOSE_LC in lowered


def validate_broadcast_body( message: Optional[ str ] ) -> Tuple[ bool, Optional[ str ] ]:
    """
    Validate the broadcast `message` field and return ( valid, error_detail ).

    An empty or whitespace-only message is rejected with a 400. So is a message that
    contains a system-reminder tag.

    """
    if not isinstance( message, str ) or not message.strip():
        return ( False, "message body is required" )
    if _body_contains_reminder_framing( message ):
        return ( False, "message must not contain system-reminder framing tags" )
    return ( True, None )


def validate_broadcast_id( broadcast_id: Optional[ str ] ) -> Tuple[ bool, Optional[ str ] ]:
    """
    Validate the caller-supplied `broadcast_id`, where None is allowed.

    None is allowed because the server generates an id then. An id that is not a
    valid UUIDv4 is rejected with a 400.

    """
    if broadcast_id is None:
        return ( True, None )
    if not isinstance( broadcast_id, str ) or not _UUIDV4_RE.match( broadcast_id ):
        return ( False, "broadcast_id must be a UUIDv4" )
    return ( True, None )


def build_pseudo_sender_id( user_id: str ) -> str:
    """
    Build the server pseudo sender id for `broadcasts` topic posts.

    The form is `broadcast-<8-hex-of-sha256(user_id)>`. It uses a hyphen and never `@`,
    because an `@` would fail the `commons_store._HEADER_RE` round-trip.

    """
    digest = hashlib.sha256( user_id.encode( "utf-8" ) ).hexdigest()[ :8 ]
    return f"broadcast-{digest}"


def _load_bridge_fields( bridge_path: Any ) -> Optional[ Dict[ str, Any ] ]:
    """
    Open a bridge file and return its content as a dict, or None on failure.

    It is separate so unit tests can mock it at the source.

    """
    try:
        with open( bridge_path ) as f:
            return json.load( f )
    except ( json.JSONDecodeError, OSError ):
        return None


def _bridge_last_activity_epoch( bridge: Dict[ str, Any ] ) -> Optional[ float ]:
    """
    Return the bridge's last-activity time in epoch seconds, or None if unparseable.

    It tries the numeric fields `last_activity_epoch`, `last_activity` and `updated_at` first.
    It then falls back to the ISO string in `idle_detection.last_interaction_at`. That nested
    field is the one the real bridge writer, `set_idle_detection_field` in `session_bridge.py`,
    actually populates. Without the fallback the lookup returns None for every bridge, and the
    activity-age filter does nothing. Dead-PID phantoms then get through inside Docker, where
    the host-PID liveness check is disabled. The function is defensive against schema drift.

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


def _sender_id_for_bridge( session_id, bridge ) -> Optional[ str ]:
    """
    The notification sender_id for a session, read from its bridge.

    Requires:
        - session_id is a string (a full session uuid, or already an 8-hex hash)
        - bridge is a dict (foreign data — any key may be missing or wrong-typed)

    Ensures:
        - Returns the bridge's own `sender_id`, written by the SessionStart hook
          on the host, verbatim — this function does not derive it
        - Returns None when the bridge carries no `sender_id`, or one that is not
          a non-empty string. None, never a sentinel: `"unknown"` has no "#", so
          `sessionHashOf` returns null on the phone, the hash-merge never fires,
          and every unidentified seat collapses onto one bogus rail row. Null is
          already the shape under test there (`focus_chat_bloc.dart`, pinned by
          `focus_live_seat_roster_test.dart`), so it needs no client change
        - Never raises

    Args:
        session_id: The session's id, as the roster reports it
        bridge: The session's bridge dict

    Returns:
        str or None: The sender_id, or None when the bridge does not carry one

    Why no derivation: the function must not derive the id from the bridge's `cwd`.
    A `.git` walk over a host path runs inside the lupin-rest container, where that path
    does not exist. The walk finds nothing and falls back to the cwd basename. A worktree
    seat would then be served under a different identity from the one its notifications use,
    and would appear twice on the focus rail.

    A fallback must not be added. Inferring the project from the path segment before
    `/.claude/worktrees/` is banned, even as a silent last resort. The session is the only
    party that knows its identity. An inference that reads today's layout breaks the day
    someone nests a worktree or renames a repo. A wrong identity that looks like a right
    one is the defect itself, not a mitigation. A bridge with no `sender_id` is a seat the
    server cannot address, and returning None says so.

    """
    sender_id = bridge.get( "sender_id" )
    return sender_id if isinstance( sender_id, str ) and sender_id else None


def project_session_response(
    session_id   : str,
    persona      : Dict[ str, Any ],
    bridge       : Dict[ str, Any ],
) -> Dict[ str, Any ]:
    """
    Build the response dict for one session, with no filesystem-derived field.

    It never includes the bridge Path or any other filesystem-derived field.
    Only these fields are exposed: session_id, sender_id, persona_name,
    persona_icon, persona_color, last_seen_iso, speakerphone_on.

    `sender_id` is the notification routing key, `claude.code@<project>.deepily.ai#<hash8>`,
    read from the bridge through `_sender_id_for_bridge`. It is None when the bridge carries
    none. A client cannot rebuild it from `session_id` alone, because the project segment
    varies per seat. The phone's focus rail keys on the full id, so the roster must serve it.

    `last_seen_iso` falls back to `idle_detection.last_interaction_at` when the bridge has no
    top-level ISO field, so the API returns a real time instead of always None.

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
        "sender_id"       : _sender_id_for_bridge( session_id, bridge ),
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
    Apply the session filters and the response projection to the raw 3-tuple list.

    Returns `( included, filtered_out )`. Every gate that drops a session emits a
    `filtered_out` entry `{ "session_id", "reason" }`. A broadcast miss is therefore visible
    to the sender instead of vanishing. The mtime gate adds `age_seconds` and
    `threshold_seconds`. The reasons are `bridge_unreadable`, `owner_mismatch`,
    `stale_bridge_mtime`, `bridge_vanished` and `originator_excluded`. The last one is
    intentional and reported for completeness.

    1. Open each bridge via `bridge_loader` and skip it on a parse failure.
    2. Filter by `owner_user_id == authenticated_user_id`, which scopes to the same user.
       Bridges that lack an `owner_user_id` field pass through. The listener's own `user_id`
       is the service-account identity, not the human owner, so scoping on it would reject
       every stamped bridge for a human caller. Scoping reads `owner_user_id`, which the
       listener will eventually stamp with the human owner's UUID. Until the writer-side
       change `_stamp_owner_user_id_on_bridge` lands, every bridge takes the pass-through
       branch. After it lands, the equality branch tightens with no change here. The legacy
       `user_id` field stays on the bridge for telemetry and is no longer used for scoping.
    3. Filter by liveness, meaning the bridge-file mtime is newer than the threshold.
       `mtime_fn` is injectable, defaulting to `path.stat().st_mtime`, for filesystem-free
       unit tests. It mirrors the `now_epoch_fn` injection in `execute_broadcast`. The mtime
       is used instead of interaction recency so that dormant-but-alive workers stay reachable.
    4. Optionally exclude the originator's session, when `include_originator=False`.
    5. Project to the response shape via `project_session_response`, so no Path leaks.

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
    Post to the `broadcasts` topic and push `action:broadcast_received`, once per recipient.

    Each recipient is isolated from the others. If `push_notification` fails for one
    recipient, the failure is logged and the loop continues.
    Returns `(successful_count, failed_recipient_sids)`.

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
    Run the full broadcast pipeline, the pure-logic core of the POST endpoint.

    Returns a dict in one of four shapes:

      {"http_status": 400, "detail": "..."}
      {"http_status": 429, "retry_after": float}
      {"http_status": 409, "detail": "broadcast_id collision"}
      {"http_status": 200, "broadcast_id": "...", "recipients": int, "failed_recipients": [...],
       "filtered_out": [...], "status": "..."}

    The field `filtered_out` lists every enumerated session the recipient filter dropped, with the
    reason. A silent broadcast miss, such as the 8h mtime gate, is therefore visible to the
    sender. It is present in both 200 shapes. The zero-recipient response is the case it
    exists for.

    Raises nothing. All error states are returned as dicts for the route handler to
    translate into FastAPI responses.

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
    Check whether one history entry passes same-user scoping.

    It mirrors the pass-through pattern in `filter_and_project_sessions`, the broadcast filter.

    Returns True if at least one of these is satisfied:
      1. `entry.metadata.sender_user_id == authenticated_user_id`. This is direct attribution,
         for example the `broadcasts` topic, where `perform_fanout` stamps the sender's UUID.
      2. `entry.metadata.target_session_id` is in `user_session_ids`. You are the recipient,
         for example per-recipient `broadcasts` fanout entries or broadcast-acks targeting you.
      3. `bridge_owner_lookup(entry.sender_session_id)` matches the caller, or the lookup
         returns `None`. Bridges that lack `owner_user_id` pass through, as in the
         broadcast-recipient filter. This tightens to strict isolation once every listener
         bridge stamps `owner_user_id`.

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

    It includes `topic` and `topic_kind`, so the frontend can render the topic-chip prefix
    for free-form topics. Non-reserved topics get a chip.

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
    Collapse per-recipient `broadcasts` fanout rows into one row per `metadata.broadcast_id`.

    It keeps the first occurrence, which is the newest after the descending sort upstream.

    The Recent Activity surface needs this. `perform_fanout` in this module writes one
    `broadcasts` row per recipient, which supports the `target_session_id` branch of
    `_entry_passes_same_user_scoping`. For an admin-overview stream those rows are noise.
    The admin wants one broadcast as one row.

    Mutation contract: the input list is read-only. The kept entry is shallow-copied
    with `target_session_id` stripped from its `metadata`. The deduplicated row represents
    the broadcast as a whole, not any one recipient slice.

    Topics other than `broadcasts` pass through unchanged. For example, `broadcast-acks`
    per-recipient rows are the intended chip-row UX. Broadcasts-topic entries missing
    `metadata.broadcast_id` also pass through unchanged. A malformed entry should not
    disappear silently.

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
    Collapse `broadcast-acks` rows that share one key into a single row.

    The key is `(broadcast_id, sender_session_id, metadata.status)`. The function keeps the
    first occurrence, which is the newest after the descending sort upstream.

    The symptom case is a single recipient session writing the same ack three or four times
    within milliseconds. For example, one recipient logged three identical
    `status="completed"` rows for the same broadcast, with bodies and metadata bit-identical.

    It is the sister of `_dedupe_broadcasts_by_id`, with the same shape and a different key.
    The write-side multiplicity is a separate problem. Something causes several
    `notification_queue_update` deliveries, which cause several `_handle_broadcast_received`
    calls and several `_post_ack` calls in `src/lupin_mcp/broadcast_handler.py`. This
    consumer-side filter is the agreed fix until that is investigated.

    Mutation contract: the input list is read-only. Only `broadcast-acks` topic entries
    with all three keys present are subject to dedup. Any entry with a missing or
    non-string key passes through. A malformed entry should not disappear silently.

    Topics other than `broadcast-acks` pass through unchanged.

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

    Returns:
        {
            "entries"     : [ ...projected entries, newest first... ],
            "since_used"  : "<iso>" | None,
            "next_cursor" : None,    # v1 — pagination is deferred
        }

    Pipeline:
      1. Resolve the effective `since` cutoff from `since_iso` and `hours`.
      2. Enumerate active topics via `store._all_topic_names()` and drop excluded ones.
      3. For each topic, fetch entries via `store.read(t, since=cutoff, limit=max_ceiling)`.
      4. Apply per-entry same-user scoping via `_entry_passes_same_user_scoping`.
      5. Merge across topics and sort newest-first.
      6. Cap to `min(limit, max_entries_ceiling)`.
      7. Project to the response shape via `_project_history_entry`.

    Design choices: free-form topics keep a topic chip, through `topic_kind` in the projection.
    The caller-supplied `excluded_topics` removes `presence` and `system-events` by default.
    The `hours` window mirrors the history-window dropdown. The stream is flat, sorted by
    `ts` descending across topics.

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
    True when a supplied recipient session id addresses a candidate's canonical session id.

    It tolerates the short and full forms a session advertises about itself.

    Requires:
        - supplied is a non-empty string (pydantic enforces min_length=1)

    Ensures:
        - returns True iff canonical == supplied, or the shorter of the pair is
          a >= 8-char prefix of the longer
        - returns False when canonical is falsy (a null-persona candidate still
          carries a real session_id, so this only guards truly empty ids)
        - never raises

    `get_session_info()` reports a session's `session_id` in short (8-char) form, while the
    bridge scan keys candidates on the full `stable_session_id`. A manager replying to a worker
    that advertised its short id therefore supplies a prefix of the candidate's canonical id,
    and exact equality would miss it. This is the only addressing channel for a null-persona
    worker, which has no name to resolve by.

    Exact equality is tried first. Otherwise the shorter of the two must be a prefix of at
    least 8 characters. The 8-character floor stops a 1-2 character id colliding with every
    candidate. The caller detects and reports ambiguity, meaning more than one candidate
    matching a short prefix. This function does not collapse it.

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
    Resolve an inter-session DM recipient to a concrete session_id and persona_name.

    A supplied session_id takes precedence over persona. The persona chain is exact, then
    case-insensitive, then punctuation- and whitespace-tolerant (the LLM disambiguator is stubbed).
    Failures return a 422 with a `RecipientResolutionError` body. Scoping uses `filter_and_project_sessions`.

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

    def _project( s ):
        return {
            "persona"      : str( s.get( "persona_name" ) or "" ),
            "session_id"   : str( s.get( "session_id" ) or "" ),
            "active_since" : str( s.get( "last_seen_iso" ) or "" ),
        }

    # Named sessions are the persona candidates. A persona-null session (released, or
    # never named) cannot be addressed by name, so it goes in its own labelled bucket.
    candidate_alternatives     = [ _project( s ) for s in active_sessions if s.get( "persona_name" ) ]
    session_id_only_candidates = [
        { **_project( s ), "note": "active, no persona, addressable by session id only" }
        for s in active_sessions if not s.get( "persona_name" )
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
            session_id_only_candidates = session_id_only_candidates,
                suggested_next_action      = "The supplied recipient_session_id is a prefix of more than one active session; supply the full session id (call commons_who() to list them).",
            )
            return { "http_status": 422, "detail": err.model_dump() }
        err = RecipientResolutionError(
            error                      = "recipient_inactive",
            supplied_persona           = recipient_persona,
            supplied_session_id        = recipient_session_id,
            resolution_chain_attempted = [ "session_id_direct", "session_id_prefix" ],
            candidate_alternatives     = candidate_alternatives,
            session_id_only_candidates = session_id_only_candidates,
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
            session_id_only_candidates = session_id_only_candidates,
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
            session_id_only_candidates = session_id_only_candidates,
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
        session_id_only_candidates = session_id_only_candidates,
        suggested_next_action      = "Supply either recipient_session_id or recipient_persona on the request body.",
    )
    return { "http_status": 422, "detail": err.model_dump() }


# ─── Dependency-injection accessors ─────────────────────────────────────────


def get_notification_queue():
    """DI: return the singleton NotificationFifoQueue from main module."""
    import lupin_app.main as main_module
    return main_module.jobs_notification_queue


def _require_initialized():
    """Raise if the commons singletons are not yet wired at app startup."""
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


