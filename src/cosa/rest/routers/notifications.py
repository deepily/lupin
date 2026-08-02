"""
Notification management endpoints.

Provides REST API endpoints for managing user notifications including
sending notifications from Claude Code, retrieving user notifications,
and managing notification lifecycle (played/deleted status).

Generated on: 2025-01-24
"""

from fastapi import APIRouter, Query, HTTPException, Depends, Body
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Annotated, Literal
import zoneinfo
import asyncio
import json
import uuid
import re

# Import dependencies and services
from ..notification_fifo_queue import NotificationFifoQueue
from ..websocket_manager import WebSocketManager
from ..middleware.api_key_auth import require_api_key, require_api_key_or_jwt
from ..db.database import get_db
from ..db.repositories.notification_repository import NotificationRepository

# Per-session voice persona lookup (see Phase 7 of voice persona R&D)
# Bridge file is canonical state; lookup is best-effort and fail-soft.
try:
    from lupin_cli.claude_code.hooks.lib.session_bridge import get_voice_persona as _bridge_get_voice_persona
except ImportError:
    _bridge_get_voice_persona = None

try:
    from cosa.rest.voice_persona_helpers import display_name_for as _display_name_for
except ImportError:
    _display_name_for = None

# Manager-lineage badge (Rick 2026-06-08): resolve a worker's spawning-manager persona
# so the senders-visible hydration can stamp it (covers the cold-reload gap where an
# EXISTING worker's badge would otherwise wait for the next live voice_persona_assigned).
try:
    from cosa.rest.routers.voice_persona import _resolve_manager_persona
except ImportError:
    _resolve_manager_persona = None


def _voice_persona_for_sender_id( resolved_sender_id ):
    """
    Resolve a sender_id (e.g., 'claude.code@lupin.deepily.ai#c7333045') to a
    voice persona dict by reading the session bridge file. Returns None on
    any failure (sender_id missing #suffix, bridge missing, persona not set,
    or session_bridge module not importable).

    The 8-char prefix after '#' is matched against bridge files via
    find_session_path_by_id (which already understands the prefix-or-full
    form), so we can pass it directly to get_voice_persona.

    Defensively stamps `display_name` on the returned dict if the bridge
    file predates the lowercase-key rename (legacy bridges have only `name`).
    Pool names are stored lowercase no-punctuation per project key convention;
    `display_name` is the proper-noun form for UI rendering.
    """
    if _bridge_get_voice_persona is None or not resolved_sender_id or "#" not in resolved_sender_id:
        return None
    sid_suffix = resolved_sender_id.split( "#", 1 )[ 1 ].strip()
    if not sid_suffix:
        return None
    try:
        persona = _bridge_get_voice_persona( sid_suffix )
    except Exception:
        return None
    if persona and "display_name" not in persona and _display_name_for is not None:
        persona = { **persona, "display_name": _display_name_for( persona.get( "name", "" ) ) }
    return persona


def _manager_persona_for_sender_id( resolved_sender_id ):
    """
    Resolve a sender_id to its SPAWNING MANAGER's persona badge dict
    ({icon,color,name,initial}) for the focus-bar manager badge (Rick 2026-06-08), so a
    force-refreshed page hydrates the badge for EXISTING workers instead of waiting for
    the next live voice_persona_assigned event (the cold-reload gap). Returns None for
    root sessions or any failure. Mirrors _voice_persona_for_sender_id's #-suffix
    (session-prefix) extraction.
    """
    if _resolve_manager_persona is None or not resolved_sender_id or "#" not in resolved_sender_id:
        return None
    sid_suffix = resolved_sender_id.split( "#", 1 )[ 1 ].strip()
    if not sid_suffix:
        return None
    try:
        return _resolve_manager_persona( sid_suffix )
    except Exception:
        return None

router = APIRouter(prefix="/api", tags=["notifications"])

# Global variables that will be injected via dependencies (temporary)
jobs_notification_queue = None
websocket_manager = None

# Global state for pending responses (Phase 2.1 SSE blocking flow)
# {notification_id: {"event": asyncio.Event(), "response_data": None}}
pending_responses = {}

# ── Idempotency cache: prevents duplicate notifications from retry loops ──
# Key: idempotency_key (UUID), Value: (response_dict, timestamp)
# TTL: 60s, max entries: 1000
import threading
import time as time_mod
from collections import OrderedDict

_idempotency_cache = OrderedDict()
_idempotency_lock  = threading.Lock()
_IDEMPOTENCY_TTL   = 60   # seconds
_IDEMPOTENCY_MAX   = 1000

# ── Ask-idempotency index (bug f433fbae D2) ──
# The fire-and-forget cache above stores a whole response dict, which works because
# that path returns a plain dict. The response-required (blocking) path returns a
# StreamingResponse, so it cannot cache-and-replay the same way — instead we remember
# which notification_id a given idempotency_key already minted, and a re-POST with
# that key RE-ATTACHES to the original ask instead of creating a second card. Same
# TTL / max-size policy and lock as the fire-and-forget cache.
# Key: idempotency_key (UUID) → Value: (notification_id, timestamp)
_ask_idempotency_index = OrderedDict()


def _record_ask_idempotency( idempotency_key, notification_id ):
    """
    Remember which notification_id a response-required ask minted for this key.

    Requires:
        - notification_id is the id of a freshly-created response-required notification

    Ensures:
        - a falsy idempotency_key is a no-op (nothing to de-dup on)
        - otherwise the key → notification_id mapping is stored, trimmed to
          _IDEMPOTENCY_MAX (oldest evicted first)
    """
    if not idempotency_key:
        return
    with _idempotency_lock:
        _ask_idempotency_index[ idempotency_key ] = ( notification_id, time_mod.time() )
        while len( _ask_idempotency_index ) > _IDEMPOTENCY_MAX:
            _ask_idempotency_index.popitem( last=False )


def _lookup_ask_idempotency( idempotency_key ):
    """
    Return the notification_id previously minted for this key, or None.

    Ensures:
        - a falsy key returns None
        - entries older than _IDEMPOTENCY_TTL are evicted before the lookup, so a
          stale key never re-attaches to a long-gone ask
        - returns the stored notification_id on a live hit, else None
    """
    if not idempotency_key:
        return None
    with _idempotency_lock:
        now = time_mod.time()
        while _ask_idempotency_index:
            oldest_key, ( _, ts ) = next( iter( _ask_idempotency_index.items() ) )
            if now - ts > _IDEMPOTENCY_TTL:
                _ask_idempotency_index.pop( oldest_key )
            else:
                break
        entry = _ask_idempotency_index.get( idempotency_key )
        return entry[ 0 ] if entry else None


def _read_notification_state_sync( notification_id ):
    """
    Read one notification's {state, response_value, responded_at} for the ask
    re-attach poll (bug f433fbae D2). Mirrors get_notification_response's fetch.

    Ensures:
        - returns None when the row is gone
        - otherwise returns the three fields verbatim (responded_at as a datetime|None)
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        n    = repo.get_by_id( uuid.UUID( str( notification_id ) ) )
        if n is None:
            return None
        return {
            "state"          : n.state,
            "response_value" : n.response_value,
            "responded_at"   : n.responded_at,
        }


def _extract_response_value( response_value ):
    """Pull the scalar answer out of a stored response_value (dict-wrapped or bare),
    coerced to a string RespondedEvent/ExpiredEvent can carry. None → None."""
    if response_value is None:
        return None
    val = response_value.get( "value" ) if isinstance( response_value, dict ) else response_value
    return val if isinstance( val, str ) else json.dumps( val )


async def _ask_reattach_generator( notification_id, timeout_seconds ):
    """
    Re-attach SSE for a duplicate idempotency_key (bug f433fbae D2): stream the
    ORIGINAL ask's outcome by polling its DB row, so a re-POST does not mint a second
    card. Self-contained — never touches the in-memory pending_responses event, so it
    is safe regardless of whether the original stream is alive.

    Ensures:
        - first frame is an ack carrying the ORIGINAL notification_id
        - a landed human answer (responded_at set) yields a `responded` frame
        - a manufactured default (response_value set, not responded) yields an
          `expired` frame with default_used=True
        - budget exhausted with neither yields an `expired` frame with no default
    """
    yield f"data: {json.dumps({'status': 'ack', 'notification_id': notification_id})}\n\n"
    deadline      = datetime.utcnow() + timedelta( seconds=timeout_seconds )
    poll_interval = 2.0
    while True:
        row = await asyncio.to_thread( _read_notification_state_sync, notification_id )
        if row is not None:
            if row[ "responded_at" ] is not None:
                val = _extract_response_value( row[ "response_value" ] )
                yield f"data: {json.dumps({'status': 'responded', 'response': val, 'default_used': False})}\n\n"
                return
            if row[ "response_value" ] is not None:
                val = _extract_response_value( row[ "response_value" ] )
                yield f"data: {json.dumps({'status': 'expired', 'response': val, 'default_used': True, 'timeout': True})}\n\n"
                return
        if datetime.utcnow() >= deadline:
            yield f"data: {json.dumps({'status': 'expired', 'response': None, 'default_used': False, 'timeout': True})}\n\n"
            return
        await asyncio.sleep( min( poll_interval, max( 0.0, ( deadline - datetime.utcnow() ).total_seconds() ) ) )


def _sse_headers():
    """Standard text/event-stream headers shared by every SSE StreamingResponse here."""
    return {
        "Cache-Control"               : "no-cache",
        "X-Accel-Buffering"           : "no",
        "Connection"                  : "keep-alive",
        "Content-Type"                : "text/event-stream",
        "Access-Control-Allow-Origin" : "*",
    }


def get_notification_queue():
    """
    Dependency to get notification queue from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has jobs_notification_queue attribute
        
    Ensures:
        - Returns the notification queue instance
        - Provides access to notification management
        
    Raises:
        - ImportError if main module not available
        - AttributeError if notification queue not found
    """
    # This will be properly injected later
    import lupin_app.main as main_module
    return main_module.jobs_notification_queue

def get_websocket_manager():
    """
    Dependency to get websocket manager from main module.

    Requires:
        - lupin_app.main module is available
        - main_module has websocket_manager attribute

    Ensures:
        - Returns the websocket manager instance
        - Provides access to WebSocket communication

    Raises:
        - ImportError if main module not available
        - AttributeError if websocket manager not found
    """
    import lupin_app.main as main_module
    return main_module.websocket_manager

def get_local_timestamp():
    """
    Get timezone-aware timestamp using configured timezone from ConfigurationManager.
    
    Requires:
        - lupin_app.main module is available
        - config_mgr and app_debug are accessible
        - zoneinfo module is available
        
    Ensures:
        - Returns ISO format timestamp with timezone information
        - Uses configured timezone or defaults to America/New_York
        - Falls back to UTC if timezone configuration is invalid
        - Provides debug output if app_debug is enabled
        
    Raises:
        - None (handles all exceptions with fallback to UTC)
    """
    import lupin_app.main as main_module
    config_mgr = main_module.config_mgr
    app_debug = main_module.app_debug
    
    # Get timezone from config, default to America/New_York (East Coast)
    timezone_name = config_mgr.get("app timezone", default="America/New_York")
    
    
    try:
        # Create timezone-aware datetime
        tz = zoneinfo.ZoneInfo(timezone_name)
        local_time = datetime.now(tz)
        result = local_time.isoformat()


        return result
    except Exception as e:
        # Fallback to UTC if timezone is invalid
        if app_debug: print(f"[TIMEZONE] Warning: Invalid timezone '{timezone_name}', falling back to UTC: {e}")
        return datetime.now().isoformat()


def get_formatted_time_display():
    """
    Get formatted time display string with timezone abbreviation.
    Format: "HH:MM TZ" (e.g., "17:45 EST")

    Requires:
        - lupin_app.main module is available
        - config_mgr is accessible
        - zoneinfo module is available

    Ensures:
        - Returns formatted time string like "17:45 EST"
        - Uses configured timezone or defaults to America/New_York
        - Falls back to simple time format if timezone configuration is invalid
    """
    import lupin_app.main as main_module
    config_mgr = main_module.config_mgr

    timezone_name = config_mgr.get( "app timezone", default="America/New_York" )

    try:
        tz = zoneinfo.ZoneInfo( timezone_name )
        local_time = datetime.now( tz )
        return local_time.strftime( '%H:%M %Z' )
    except Exception as e:
        # Fallback to simple time format
        return datetime.now().strftime( '%H:%M' )


def get_formatted_date_display():
    """
    Get formatted date display string in ISO format (YYYY-MM-DD).
    Uses configured timezone to ensure correct date near midnight.

    Requires:
        - lupin_app.main module is available
        - config_mgr is accessible
        - zoneinfo module is available

    Ensures:
        - Returns formatted date string like "2026-01-08"
        - Uses configured timezone or defaults to America/New_York
        - Falls back to local date if timezone configuration is invalid
    """
    import lupin_app.main as main_module
    config_mgr = main_module.config_mgr

    timezone_name = config_mgr.get( "app timezone", default="America/New_York" )

    try:
        tz = zoneinfo.ZoneInfo( timezone_name )
        local_time = datetime.now( tz )
        return local_time.strftime( '%Y-%m-%d' )
    except Exception:
        # Fallback to simple date format
        return datetime.now().strftime( '%Y-%m-%d' )


def resolve_sender_id( explicit_sender_id: Optional[str], message: str ) -> str:
    """
    Resolve sender ID using precedence: explicit > extracted from [PREFIX] > default.

    Requires:
        - explicit_sender_id is None or a valid sender ID string
        - message is a string

    Ensures:
        - Returns explicit_sender_id if provided
        - Otherwise extracts from [PREFIX] in message (e.g., [LUPIN] -> claude.code@lupin.deepily.ai)
        - Falls back to claude.code@unknown.deepily.ai if no sender can be determined

    Args:
        explicit_sender_id: Explicitly provided sender ID (from --sender-id CLI arg)
        message: Notification message text

    Returns:
        str: Resolved sender ID in claude.code@{project}.deepily.ai format
    """
    # Priority 1: Explicit sender_id
    if explicit_sender_id:
        return explicit_sender_id

    # Priority 2: Extract from [PREFIX] in message
    match = re.match( r'^\[([A-Z]+)\]', message )
    if match:
        project = match.group( 1 ).lower()
        return f"claude.code@{project}.deepily.ai"

    # Priority 3: Default fallback
    return "claude.code@unknown.deepily.ai"


# NOTE: API parameter is 'target_user' for backward compatibility and simplicity.
# Internally, the config system uses 'global_notification_recipient' to support
# future multi-recipient routing. This naming mismatch is intentional.
# API stability takes precedence over naming consistency.
def _persist_notification_sync(
    resolved_sender_id, target_system_id, message, type, priority, title,
    abstract, parsed_response_options, job_id, progress_group_id, is_connected,
    direction="ai_to_human", sender_persona=None, sender_icon=None,
    reply_to=None, thread_id=None
):
    """
    Synchronous DB persist for notify_user — run OFF the event loop via
    asyncio.to_thread (lever B, messaging-coordination plane).

    Moving this blocking DB I/O off the single async event loop stops the notify
    path from stalling every other request under fleet load (the FM-7 black-hole).

    Ensures:
        - creates the Notification row; marks it 'delivered' when is_connected
        - returns the new notification id (str)

    Raises:
        - propagates DB errors to the caller (handled there as non-fatal)
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        db_notification = repo.create_notification(
            sender_id          = resolved_sender_id,
            recipient_id       = uuid.UUID( target_system_id ),
            message            = message.strip(),
            type               = type,
            priority           = priority,
            title              = title,
            abstract           = abstract,
            response_options   = parsed_response_options,
            job_id             = job_id,
            progress_group_id  = progress_group_id,
            direction          = direction,
            sender_persona     = sender_persona,
            sender_icon        = sender_icon,
            reply_to           = reply_to,
            thread_id          = thread_id
        )
        nid = str( db_notification.id )
        if is_connected:
            repo.update_state( db_notification.id, "delivered" )
        return nid


def _update_notification_state_sync( notification_id, state ):
    """
    Synchronous notification state update — run OFF the event loop via
    asyncio.to_thread (lever B, surgical pass 2).

    Requires:
        - notification_id is a UUID string
        - state is a valid notification state (e.g. 'delivered')

    Ensures:
        - updates the Notification row's state

    Raises:
        - propagates DB errors to the caller (handled there as non-fatal)
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        repo.update_state( uuid.UUID( notification_id ), state )


def _persist_response_required_sync(
    resolved_sender_id, target_system_id, message, type, priority, title,
    abstract, response_type, response_default, parsed_response_options,
    timeout_seconds, job_id, progress_group_id, state,
    sender_persona=None, sender_icon=None
):
    """
    Synchronous DB persist for a response-required notification — run OFF the
    event loop via asyncio.to_thread (lever B, surgical pass 2).

    This is the blocking-ask hot path: every ask_yes_no / ask_multiple_choice /
    converse from every fleet session lands here. The inline `with get_db()`
    version blocked the shared :7999 event loop on session checkout + two
    round-trips per ask (the FM-7 black-hole).

    Requires:
        - target_system_id is a UUID string
        - timeout_seconds is a positive int
        - state is 'delivered' (user online) or 'expired' (offline default)

    Ensures:
        - creates the response-required Notification row with expiration
        - sets the row state to `state`
        - returns the new notification id (str)

    Raises:
        - propagates DB errors to the caller
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        # Calculate expiration time
        expires_at = datetime.utcnow() + timedelta( seconds=timeout_seconds )
        db_notification = repo.create_notification(
            sender_id          = resolved_sender_id,
            recipient_id       = uuid.UUID( target_system_id ),
            title              = title or message.strip()[:50],
            message            = message.strip(),
            type               = type,
            priority           = priority,
            abstract           = abstract,
            response_requested = True,
            response_type      = response_type,
            response_default   = response_default,
            response_options   = parsed_response_options,
            timeout_seconds    = timeout_seconds,
            expires_at         = expires_at,
            job_id             = job_id,
            progress_group_id  = progress_group_id,
            sender_persona     = sender_persona,
            sender_icon        = sender_icon
        )
        repo.update_state( db_notification.id, state )
        return str( db_notification.id )


def _mark_notification_expired_sync( notification_id ):
    """
    Synchronous expiry mark for a timed-out response-required notification —
    run OFF the event loop via asyncio.to_thread (lever B, surgical pass 2).

    Fires inside the SSE event_generator on ask timeout; the inline version
    blocked the event loop for a DB write at exactly the moment a fleet of
    asks expires together.

    Requires:
        - notification_id is a UUID string

    Ensures:
        - marks the Notification row expired

    Raises:
        - propagates DB errors to the caller
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        repo.mark_expired( uuid.UUID( notification_id ) )


def _submit_response_sync( notification_id, response_value ):
    """
    Synchronous DB read/validate/update for a notification response — run OFF
    the event loop via asyncio.to_thread (lever B, surgical pass 2). Fires per
    ask answer.

    Requires:
        - notification_id is a UUID string
        - response_value is a non-empty str or dict

    Ensures:
        - validates notification exists, is unanswered, and is within the grace
          period when expired
        - persists the response (wrapping plain strings as {value, source})
        - returns ( recipient_id, job_id ) for the WebSocket broadcast

    Raises:
        - HTTPException 404 if the notification does not exist
        - HTTPException 400 if already responded / grace period exceeded
        - HTTPException 500 if the response update fails
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        notification = repo.get_by_id( uuid.UUID( notification_id ) )

        if not notification:
            raise HTTPException(
                status_code = 404,
                detail      = f"Notification {notification_id} not found"
            )

        # Check state - must be 'delivered' or within grace period
        if notification.state == "responded":
            raise HTTPException(
                status_code = 400,
                detail      = "Notification already responded to"
            )

        # Grace period check - read from config (supports pause button feature)
        import lupin_app.main as main_module
        config_mgr = main_module.config_mgr
        grace_period_seconds = config_mgr.get( "notification grace period seconds", default=300, return_type="int" )

        if notification.state == "expired":
            # Check if within grace period
            expires_at = notification.expires_at
            now        = datetime.now( timezone.utc )

            if expires_at and (now - expires_at).total_seconds() > grace_period_seconds:
                raise HTTPException(
                    status_code = 400,
                    detail      = f"Notification expired more than {grace_period_seconds}s ago (grace period exceeded)"
                )

            print(f"[NOTIFY] Accepting late response within grace period ({grace_period_seconds}s)")

        # Capture recipient_id and job_id before session closes (for WebSocket broadcast).
        # job_id is needed for the cross-user CC-listener fallback in the
        # notification_responded broadcast below (Phase C migration 2026-04-27).
        # sender_id + sender_persona are captured for the late-answer handback
        # (§4.3): the asking session's #hash8 is the durable/listener routing key,
        # and sender_persona keys the catch-up pull.
        recipient_id        = str( notification.recipient_id )
        notification_job_id = notification.job_id
        sender_id           = notification.sender_id
        sender_persona      = notification.sender_persona

        # Update database with response (pass dict, not JSON string)
        # Wrap in dict if response_value is a simple string like "yes" or "no"
        if isinstance( response_value, str ):
            response_dict = { "value": response_value, "source": "ui" }
        else:
            response_dict = response_value

        updated = repo.update_response( uuid.UUID( notification_id ), response_dict )

        if not updated:
            raise HTTPException(
                status_code = 500,
                detail      = "Failed to update notification response in database"
            )

        # A dict, not the old 2-tuple (§4.3 step 1) — carries the asking session's
        # sender_id + sender_persona for the handback routing/catch-up keys.
        return {
            "recipient_id"   : recipient_id,
            "job_id"         : notification_job_id,
            "sender_id"      : sender_id,
            "sender_persona" : sender_persona,
        }


def _mark_answer_delivered_sync( notification_id ):
    """
    Stamp answer_delivered_at on a notification — run OFF the event loop via
    asyncio.to_thread. The router's arm of the three RECEIPT-gated setters (§4.3):
    setter (a) calls this when the live SSE waiter is woken (the asking coroutine
    consumed the value). Setters (b)/(c) share the same repo write via the
    answers-owed ack endpoint.

    Requires:
        - notification_id is a UUID string

    Ensures:
        - answer_delivered_at is set (idempotent); the row is never deleted

    Raises:
        - propagates DB errors to the caller (handled there as non-fatal)
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        repo.mark_answer_delivered( uuid.UUID( notification_id ) )


@router.post(
    "/notify",
    summary     = "Send notification",
    description = "Dispatch notification to a user via WebSocket. Supports fire-and-forget or SSE blocking mode for response-required notifications."
)
async def notify_user(
    authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)],
    message: str = Query(..., description="Notification message text"),
    type: str = Query("custom", description="Notification type (task, progress, alert, custom)"),
    direction: str = Query("ai_to_human", description="Communication direction (provenance axis, orthogonal to type): human_to_ai | ai_to_ai | ai_to_human. Defaults to ai_to_human (AI speaking to the user)."),
    priority: str = Query("medium", description="Priority level (low, medium, high, urgent)"),
    target_user: str = Query(..., description="Target user email address (required - configure in CLI config or pass explicitly)"),
    response_requested: bool = Query(False, description="Whether notification requires user response (Phase 2.1)"),
    response_type: Optional[str] = Query(None, description="Response type: yes_no or open_ended (Phase 2.1)"),
    timeout_seconds: int = Query(120, description="Timeout in seconds for response-required notifications"),
    response_default: Optional[str] = Query(None, description="Default response value for timeout/offline (Phase 2.1)"),
    title: Optional[str] = Query(None, description="Terse technical title for voice-first UX (Phase 2.1)"),
    sender_id: Optional[str] = Query(None, description="Sender ID (e.g., claude.code@lupin.deepily.ai). Auto-extracted from [PREFIX] in message if not provided."),
    response_options: Optional[str] = Query(None, description="JSON string of options for multiple_choice type. Structure: {questions: [{question, header, multi_select, options: [{label, description}]}]}"),
    abstract: Optional[str] = Query(None, description="Supplementary context for the notification (plan details, URLs, markdown). Displayed alongside message in action-required cards."),
    job_id: Optional[str] = Query(None, description="Agentic job ID for routing to job cards (e.g., dr-a1b2c3d4, mock-12345678)"),
    queue_name: Optional[str] = Query(None, description="Queue where job is running (run/todo/done). Used for provisional job card registration when notifications arrive before job is fetched."),
    suppress_ding: bool = Query(False, description="Suppress notification sound (ding) while still speaking message via TTS. Used for conversational TTS from queue operations."),
    progress_group_id: Optional[str] = Query(None, description="Progress group ID for in-place DOM updates. Notifications sharing this ID update a single element instead of appending new ones."),
    prediction_hint_override: Optional[str] = Query(None, description="JSON override for prediction_hint (testing/debug). Bypasses PredictionEngine."),
    display_qualifier_widget: bool = Query(False, description="Render yes/no qualifier comment widget expanded by default with softer instructional text."),
    session_name: Optional[str] = Query(None, description="Human-readable session name for UI header display. Updates sender-session-name span in notification history card."),
    idempotency_key: Optional[str] = Query(None, description="UUID idempotency key to prevent duplicate notifications on retry. Same key = same notification, skip push/persist."),
    persist: bool = Query(True, description="Whether to persist a forensic DB row (default True — byte-identical prior behavior). Set False for delivery-only re-attempts (e.g. arbiter re-announce-on-return) so repeated retries of an already-persisted advisory never mint duplicate rows (bug e1bbe011). Live WebSocket delivery + the offline/online outcome are unaffected; only the DB insert is skipped."),
    notification_queue: NotificationFifoQueue = Depends(get_notification_queue),
    ws_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Claude Code notification endpoint for user communication.

    Supports both fire-and-forget notifications (Phase 1) and response-required
    notifications with SSE blocking (Phase 2.1).

    **Fire-and-Forget Mode** (response_requested=False):
    - Queues notification for WebSocket delivery
    - Returns immediately without blocking
    - Existing behavior unchanged

    **Response-Required Mode** (response_requested=True):
    - Creates notification in database with expiration
    - Pushes to WebSocket for UI rendering
    - Returns SSE stream that blocks until response/timeout
    - Supports offline detection (immediate default return)

    Requires:
        - Valid API key (X-API-Key) or Bearer JWT (validated by require_api_key_or_jwt)
        - message is non-empty after stripping whitespace
        - type is one of: task, progress, alert, custom
        - priority is one of: low, medium, high, urgent
        - target_user is a valid email address
        - If response_requested=True: response_type must be "yes_no" or "open_ended"

    Ensures:
        - Validates all input parameters against allowed values
        - Converts target email to system ID for routing
        - Fire-and-forget: Queues notification and returns immediately
        - Response-required: Creates database record, returns SSE stream
        - Offline detection: Returns default immediately if user not connected
        - Logs all notification attempts and results

    Raises:
        - HTTPException with 401 for invalid/missing API key (via middleware)
        - HTTPException with 400 for invalid parameters
        - HTTPException with 503 for offline user without default
        - HTTPException with 500 for delivery failures

    Args:
        authenticated_user_id: Service account user ID (from API key validation)
        message: The notification message text
        type: Type of notification (task, progress, alert, custom)
        priority: Priority level (low, medium, high, urgent)
        target_user: Target user email address
        response_requested: Whether notification requires response (Phase 2.1)
        response_type: Response type (yes_no, open_ended) for Phase 2.1
        timeout_seconds: Timeout for response-required notifications (Phase 2.1)
        response_default: Default value for timeout/offline (Phase 2.1)
        title: Terse technical title for voice-first UX (Phase 2.1)

    Returns:
        dict (fire-and-forget) or StreamingResponse (SSE for response-required)
    """
    # Auth validation handled by require_api_key_or_jwt middleware (API key or Bearer JWT)
    # authenticated_user_id contains the validated user ID

    # Validate notification type
    # Custom state-update types ("voice_persona_assigned", "voice_persona_released",
    # "speakerphone_changed") are server-internal events routed through this
    # subsystem rather than as ad-hoc top-level WS events. See:
    # src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
    valid_types = [
        "task", "progress", "alert", "custom", "user_initiated_message", "session_topic",
        "voice_persona_assigned", "voice_persona_released", "speakerphone_changed",
        "commons_broadcast_ack", "commons_answer_received", "commons_activity",
        "commons_question_received",
        # Worker-reap state-update (2026-06-05): emitted by session_spawner.dismiss_sessions
        # on harvest. envelope sender_id = the reaped worker's sender_id → SenderStore drops
        # its badge + the broadcast card refreshes. Consumer wiring owned by Sam.
        "session_reaped"
    ]
    if type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid notification type: {type}. Valid types: {', '.join(valid_types)}"
        )

    # Validate priority
    valid_priorities = ["low", "medium", "high", "urgent"]
    if priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {priority}. Valid priorities: {', '.join(valid_priorities)}"
        )

    # Validate direction (provenance axis, orthogonal to type)
    valid_directions = ["human_to_ai", "ai_to_ai", "ai_to_human"]
    if direction not in valid_directions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid direction: {direction}. Valid directions: {', '.join(valid_directions)}"
        )

    # Validate message
    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="Please provide a message to send")

    # Phase 2.1: Validate response-required parameters
    if response_requested:
        if not response_type:
            raise HTTPException(
                status_code=400,
                detail="response_type is required when response_requested=True (yes_no or open_ended)"
            )

        valid_response_types = ["yes_no", "open_ended", "multiple_choice", "open_ended_batch"]
        if response_type not in valid_response_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid response_type: {response_type}. Valid types: {', '.join(valid_response_types)}"
            )

        # Validate multiple_choice requires response_options
        if response_type == "multiple_choice" and not response_options:
            raise HTTPException(
                status_code=400,
                detail="response_options is required when response_type=multiple_choice"
            )

        if timeout_seconds <= 0:
            raise HTTPException(
                status_code=400,
                detail="timeout_seconds must be positive"
            )

    # Parse response_options JSON string if provided
    parsed_response_options = None
    if response_options:
        try:
            parsed_response_options = json.loads( response_options )
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid JSON in response_options: {str(e)}"
            )

    # Parse prediction_hint_override JSON string if provided (testing/debug bypass)
    parsed_prediction_hint_override = None
    if prediction_hint_override:
        try:
            parsed_prediction_hint_override = json.loads( prediction_hint_override )
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid JSON in prediction_hint_override: {str( e )}"
            )

    # Normalize Optional[str] → str at the API boundary (FastAPI delivers None for absent query params)
    title    = title or ""
    abstract = abstract or ""

    # Resolve sender_id using precedence: explicit > extracted from [PREFIX] > default
    resolved_sender_id = resolve_sender_id( sender_id, message )

    # Lever E (messaging plane): per-session backpressure. Over the cap → 429 +
    # Retry-After; the caller's durable outbox honors it (queue + retry, never lost),
    # so a throttled runaway worker is slowed without dropping the message.
    from cosa.rest.notify_rate_limiter import check_notify_allowed
    _bp_allowed, _bp_retry = check_notify_allowed( resolved_sender_id )
    if not _bp_allowed:
        raise HTTPException(
            status_code = 429,
            detail      = "notify rate limit exceeded",
            headers     = { "Retry-After": str( int( _bp_retry ) + 1 ) },
        )

    # Log notification (existing logging system)
    mode = "response-required" if response_requested else "fire-and-forget"
    print(f"[NOTIFY] Claude Code notification ({mode}): {type}/{priority} - {message}")
    print(f"[NOTIFY] Sender ID resolved: {resolved_sender_id}")

    try:
        # Look up user in JWT auth database to get their UUID user_id.
        # Lever B (surgical pass 2): get_user_by_email is a blocking SQLAlchemy
        # lookup that ran on EVERY notify — run it OFF the event loop so a slow
        # DB under fleet load can't starve the shared :7999 loop (FM-7).
        from cosa.rest.user_service import get_user_by_email

        user_data = await asyncio.to_thread( get_user_by_email, target_user )
        if not user_data:
            print(f"[NOTIFY] ❌ User not found in auth database: {target_user}")
            raise HTTPException(
                status_code=404,
                detail=f"User not found: {target_user}"
            )

        target_system_id = user_data["id"]
        print( f"[NOTIFY] Resolved user {target_user} → UUID {target_system_id}" )

        # ── Diagnostic: WebSocket state dump for offline debugging ──
        import lupin_app.main as main_module
        if main_module.app_debug and main_module.app_verbose:
            ws_user_keys   = list( ws_manager.user_sessions.keys() )
            ws_active_keys = list( ws_manager.active_connections.keys() )
            print( f"[NOTIFY] 🔍 DIAG target_system_id   = {target_system_id!r}" )
            print( f"[NOTIFY] 🔍 DIAG user_sessions keys  = {ws_user_keys}" )
            print( f"[NOTIFY] 🔍 DIAG active_connections  = {len( ws_active_keys )} sessions: {ws_active_keys[ :5 ]}" )
            for uid, sessions in ws_manager.user_sessions.items():
                active = [ s for s in sessions if s in ws_manager.active_connections ]
                print( f"[NOTIFY] 🔍 DIAG   user={uid!r} sessions={sessions} active={active}" )
        # ── End diagnostic ──

        # Check if user is connected
        is_connected     = ws_manager.is_user_connected( target_system_id )
        connection_count = ws_manager.get_user_connection_count( target_system_id )
        print( f"[NOTIFY] WebSocket connection check: is_connected={is_connected}, count={connection_count}" )

        # Always-on diagnostic when user appears offline (ungated — critical for debugging 503s)
        if not is_connected:
            ws_user_keys   = list( ws_manager.user_sessions.keys() )
            ws_active_keys = list( ws_manager.active_connections.keys() )
            print( f"[NOTIFY] ⚠️ OFFLINE DIAG target_system_id   = {target_system_id!r}" )
            print( f"[NOTIFY] ⚠️ OFFLINE DIAG user_sessions keys  = {ws_user_keys}" )
            print( f"[NOTIFY] ⚠️ OFFLINE DIAG active_connections  = {len( ws_active_keys )} sessions: {ws_active_keys[ :5 ]}" )
            for uid, sessions in ws_manager.user_sessions.items():
                active = [ s for s in sessions if s in ws_manager.active_connections ]
                print( f"[NOTIFY] ⚠️ OFFLINE DIAG   user={uid!r} sessions={sessions} active={active}" )
            print( f"[NOTIFY] ⚠️ OFFLINE DIAG user_to_email = {dict( ws_manager.user_to_email )}" )

        if connection_count > 0:
            user_session_ids  = ws_manager.user_sessions.get( target_system_id, [] )
            active_sessions   = [ s for s in user_session_ids if s in ws_manager.active_connections ]
            # listener_sessions = [ s for s in active_sessions if s.startswith( "cc-listener-" ) ]
            browser_sessions  = [ s for s in active_sessions if not s.startswith( "cc-listener-" ) ]
            print( f"[NOTIFY]   Browser sessions  : {len( browser_sessions )} {browser_sessions}" )
            # print( f"[NOTIFY]   Listener sessions : {len( listener_sessions )} {listener_sessions}" )

            # Cross-user listener discovery: CC listeners authenticate as a service
            # account, so they appear under a different user_id than the target user.
            all_listener_sessions = [
                s for s in ws_manager.active_connections
                if s.startswith( "cc-listener-" )
            ]
            print( f"[NOTIFY]   All CC listeners  : {len( all_listener_sessions )} {all_listener_sessions}" )

        # =================================================================================
        # FIRE-AND-FORGET MODE (Phase 1 - existing behavior)
        # =================================================================================
        if not response_requested:

            # ── Idempotency check: skip duplicate push/persist on retries ──
            if idempotency_key:
                with _idempotency_lock:
                    # Evict expired entries
                    now = time_mod.time()
                    while _idempotency_cache:
                        oldest_key, ( _, ts ) = next( iter( _idempotency_cache.items() ) )
                        if now - ts > _IDEMPOTENCY_TTL:
                            _idempotency_cache.pop( oldest_key )
                        else:
                            break

                    if idempotency_key in _idempotency_cache:
                        cached_response, _ = _idempotency_cache[ idempotency_key ]
                        print( f"[NOTIFY] Idempotency hit: {idempotency_key} — returning cached response" )
                        return cached_response

            # 1. Persist to PostgreSQL (preserves notification history).
            #    Lever B (messaging plane): run the blocking DB I/O OFF the event loop
            #    via asyncio.to_thread so a slow DB under fleet load can't stall the
            #    notify path (and every other request sharing the loop) — the FM-7 fix.
            #    persist=False (bug e1bbe011) skips ONLY the DB insert — a delivery-only
            #    re-attempt (arbiter re-announce-on-return) must NOT mint a duplicate
            #    forensic row on every 300s retry. db_notification_id stays None; all
            #    downstream logic already tolerates None (push_notification falls back
            #    to a generated uuid4; the offline/online responses are id-agnostic).
            db_notification_id = None
            if persist:
                try:
                    db_notification_id = await asyncio.to_thread(
                        _persist_notification_sync,
                        resolved_sender_id, target_system_id, message, type, priority,
                        title, abstract, parsed_response_options, job_id, progress_group_id, is_connected,
                        direction
                    )
                    print( f"[NOTIFY] ✓ Persisted notification {db_notification_id} to PostgreSQL" )

                except Exception as db_error:
                    # Log but don't fail - FIFO queue is the primary delivery mechanism
                    print( f"[NOTIFY] ⚠️ Failed to persist to PostgreSQL (non-fatal): {db_error}" )
            else:
                print( f"[NOTIFY] persist=false — skipping DB row (delivery-only re-attempt, flood-guard)" )

            # 2. If user is offline, attempt cross-user CC-listener fallback
            #    BEFORE giving up. Delegates to the canonical helper
            #    `WebSocketManager.emit_to_user_or_listener_sync` which
            #    encapsulates the dispatch matrix (user-or-listener-or-both)
            #    consistently across all 6 dispatch sites. See
            #    `~/.claude/plans/dazzling-napping-frost.md` (2026-04-27).
            #
            #    Why this matters: CC notification listeners
            #    (`cc-listener-{job_id}` sessions) authenticate as a SHARED
            #    service-account user_id (`claude.code@lupin.deepily.ai`),
            #    which is different from the email-resolved
            #    `target_system_id`. So when a user sends a message from the
            #    UI panel targeting another CC session like
            #    `claude.code@lookml.deepily.ai`,
            #    `is_user_connected(target_system_id)` returns False even
            #    though a `cc-listener-{job_id}` session is right there in
            #    `active_connections`. Bug filed 2026-04-27 by USER
            #    (session b2ce9133).
            #
            #    user_id=None is intentional here: we already know the primary
            #    target is offline (is_connected=False above), so re-checking
            #    inside the helper is redundant. The helper just tries the
            #    listener path.
            if not is_connected and job_id:
                # Lever B (surgical pass 2): the persona lookup reads bridge files
                # (directory scan + JSON load) — blocking file I/O off the loop.
                listener_voice_persona = await asyncio.to_thread(
                    _voice_persona_for_sender_id, resolved_sender_id
                )
                dispatch_result = ws_manager.emit_to_user_or_listener_sync(
                    user_id = None,
                    job_id  = job_id,
                    event   = "notification_queue_update",
                    data    = {
                        "notification": {
                            "id"                : db_notification_id,
                            "id_hash"           : db_notification_id,
                            "type"              : type,
                            "notification_type" : type,
                            "message"           : message.strip(),
                            "priority"          : priority,
                            "job_id"            : job_id,
                            "sender_id"         : resolved_sender_id,
                            "title"             : title,
                            "abstract"          : abstract,
                            "timestamp"         : datetime.utcnow().isoformat(),
                            "voice_persona"     : listener_voice_persona,
                            "direction"         : direction,
                        },
                    },
                )
                if dispatch_result[ "listener_delivered" ]:
                    # Best-effort state update — non-fatal if it fails. Lever B
                    # (surgical pass 2): blocking DB write off the event loop.
                    if db_notification_id:
                        try:
                            await asyncio.to_thread(
                                _update_notification_state_sync, db_notification_id, "delivered"
                            )
                        except Exception as state_err:
                            print( f"[NOTIFY] ⚠️ State update to 'delivered' failed (non-fatal): {state_err}" )

                    listener_sid = f"cc-listener-{job_id}"
                    print( f"[NOTIFY] ✓ Delivered via cc-listener {listener_sid} (cross-user fallback)" )
                    response_dict = {
                        "status"             : "delivered_via_listener",
                        "message"            : f"Notification delivered to CC listener for job {job_id}",
                        "target_user"        : target_user,
                        "target_system_id"   : target_system_id,
                        "connection_count"   : 1,
                        "delivery_path"      : "cc-listener",
                        "listener_session"   : listener_sid,
                    }
                    # Cache for idempotency
                    if idempotency_key:
                        with _idempotency_lock:
                            _idempotency_cache[ idempotency_key ] = ( response_dict, time_mod.time() )
                            while len( _idempotency_cache ) > _IDEMPOTENCY_MAX:
                                _idempotency_cache.popitem( last=False )
                    return response_dict
                # else: helper either had no listener to deliver to OR the
                # emit failed (logged inside the helper). Fall through to
                # user_not_available — DB row remains for forensic recovery.

            # If we reach here, the user is offline AND no usable cc-listener
            # fallback existed. Return user_not_available — DB row remains for
            # forensic recovery.
            if not is_connected:
                print( f"[NOTIFY] User {target_user} ({target_system_id}) is not connected - notification not delivered" )
                response_dict = {
                    "status"             : "user_not_available",
                    "message"            : f"User {target_user} is not connected to queue UI",
                    "target_user"        : target_user,
                    "target_system_id"   : target_system_id,
                    "connection_count"   : 0
                }
                # Cache for idempotency (retries will get the same response without re-persisting)
                if idempotency_key:
                    with _idempotency_lock:
                        _idempotency_cache[ idempotency_key ] = ( response_dict, time_mod.time() )
                        while len( _idempotency_cache ) > _IDEMPOTENCY_MAX:
                            _idempotency_cache.popitem( last=False )
                return response_dict

            # 3. User is connected — push to FIFO queue for live WebSocket delivery.
            #    Lever B (surgical pass 2): persona lookup reads bridge files
            #    (blocking file I/O) — off the event loop.
            voice_persona_payload = await asyncio.to_thread( _voice_persona_for_sender_id, resolved_sender_id )
            notification_item = notification_queue.push_notification(
                message                 = message.strip(),
                type                    = type,
                priority                = priority,
                source                  = "claude_code",
                user_id                 = target_system_id,
                # Use database ID for consistency (mirrors the response-required
                # path below + the offline cc-listener frame above): the live
                # WS frame's id/id_hash must equal the persisted row's UUID so
                # the multiplexer's cold-load hydration can dedupe live
                # re-arrivals against hydrated history by id. None (persist
                # failed — non-fatal by design) falls back to a generated uuid4
                # inside NotificationItem, preserving prior behavior.
                # See: src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md §4
                id                      = db_notification_id,
                title                   = title,
                sender_id               = resolved_sender_id,
                abstract                = abstract,
                suppress_ding           = suppress_ding,
                job_id                  = job_id,
                queue_name              = queue_name,
                progress_group_id       = progress_group_id,
                display_qualifier_widget = display_qualifier_widget,
                session_name             = session_name,
                voice_persona            = voice_persona_payload,
                direction                = direction
            )

            print( f"[NOTIFY] ✓ Notification queued for {target_user} ({target_system_id}) - {connection_count} connection(s)" )
            print( f"[DIAG-JR] job_id={job_id!r} sender_id={resolved_sender_id!r} msg={message.strip()[:60]!r}" )
            response_dict = {
                "status"             : "queued",
                "message"            : f"Notification queued for delivery to {target_user}",
                "target_user"        : target_user,
                "target_system_id"   : target_system_id,
                "connection_count"   : connection_count
            }
            # Cache for idempotency
            if idempotency_key:
                with _idempotency_lock:
                    _idempotency_cache[ idempotency_key ] = ( response_dict, time_mod.time() )
                    while len( _idempotency_cache ) > _IDEMPOTENCY_MAX:
                        _idempotency_cache.popitem( last=False )
            return response_dict

        # =================================================================================
        # RESPONSE-REQUIRED MODE (Phase 2.1 - new SSE blocking behavior)
        # =================================================================================

        # Resolve the session's voice persona ONCE, above the offline branch (§4.2),
        # so BOTH persist paths (offline/expired and online/delivered) can stamp
        # sender_persona — the audit trail is complete regardless of how the ask
        # resolved, and persona-keyed retrieval (ruling 6) needs the key present.
        # The online WS push below REUSES this payload instead of re-reading the
        # bridge file (one fewer bridge read per ask on the hot path).
        # Lever B: bridge-file read is blocking I/O — off the event loop.
        voice_persona_payload = await asyncio.to_thread( _voice_persona_for_sender_id, resolved_sender_id )
        sender_persona = voice_persona_payload.get( "name" ) if voice_persona_payload else None
        sender_icon    = voice_persona_payload.get( "icon" ) if voice_persona_payload else None
        # A persona-less ask (allocation failed) stamps NULL sender_persona, so its
        # answer is unretrievable by persona and will never receive a late answer
        # (§4.4 runbook gap — accepted, near-universal allocation). Make it AUDIBLE
        # rather than silent: a lost late-answer shows in the log, not by Rick
        # noticing an answer never arrived.
        if sender_persona is None:
            print( f"[NOTIFY] ⚠️ response-required ask has NO voice persona (sender_id={resolved_sender_id!r}) — its late answer will be unretrievable by persona (§4.4 accepted gap)" )

        # ── Idempotency for the response-required path (bug f433fbae D2) ──
        # Hoisted above the offline/online split so a re-POST with the same
        # idempotency_key re-attaches to the ORIGINAL ask instead of minting a second
        # card. The fire-and-forget branch already dedups; this is its blocking-path
        # counterpart. The blocking verbs now always stamp a key
        # (cosa_voice_mcp._with_idempotency_key), so notify_user_sync's retry_on_timeout
        # re-POST — and any durable resend — lands here and re-attaches, not duplicates.
        existing_nid = _lookup_ask_idempotency( idempotency_key )
        if existing_nid is not None:
            print( f"[NOTIFY] Idempotency hit (ask): {idempotency_key} → re-attaching to {existing_nid}" )
            return StreamingResponse(
                _ask_reattach_generator( existing_nid, timeout_seconds ),
                media_type = "text/event-stream",
                headers    = _sse_headers()
            )

        # Task 5: Offline Detection — deliver the default immediately, but as an SSE
        # frame the streaming client can actually CONSUME (bug f433fbae D1).
        #
        # The prior return here was a plain JSONResponse: not SSE-framed AND missing
        # the `response` field OfflineEvent requires. notify_user_sync streams the
        # POST and only parses `data: `-prefixed lines, so it could not read that
        # JSON at all — it fell through to a re-attach with no ack id and returned an
        # error dict. Net: the offline default was NEVER delivered (the client
        # plumbing in commit fd11cd30 was inert without this half). Emitting a real
        # SSE OfflineEvent maps the client to exit_code=0 / default_used=True, so the
        # caller stamps `answered: False`: the default is DELIVERED and MARKED as a
        # substitution, never forged into something a human answered.
        if not is_connected:
            if response_default:
                print(f"[NOTIFY] User offline - streaming default immediately: {response_default}")

                # Create notification in PostgreSQL with state='expired'.
                # Lever B (surgical pass 2): blocking DB persist off the event loop.
                notification_id = await asyncio.to_thread(
                    _persist_response_required_sync,
                    resolved_sender_id, target_system_id, message, type, priority,
                    title, abstract, response_type, response_default,
                    parsed_response_options, timeout_seconds, job_id,
                    progress_group_id, "expired",
                    sender_persona, sender_icon
                )

                # Record the key→id mapping so a retry re-attaches here too.
                _record_ask_idempotency( idempotency_key, notification_id )

                async def offline_event_generator():
                    # ack first — hands the client this ask's notification_id so a
                    # mid-stream death can re-attach (§4.5 E-a), same as the online path.
                    yield f"data: {json.dumps({'status': 'ack', 'notification_id': notification_id})}\n\n"
                    # OfflineEvent: `response` carries the default; default_used=True is
                    # the provenance the caller stamps as `answered: False` — the marker
                    # that keeps a substitution from reading as a human decision.
                    yield f"data: {json.dumps({'status': 'offline', 'response': response_default, 'default_used': True})}\n\n"

                return StreamingResponse(
                    offline_event_generator(),
                    media_type = "text/event-stream",
                    headers    = _sse_headers()
                )
            else:
                raise HTTPException(
                    status_code = 503,
                    detail      = "User is offline and no default response provided"
                )

        # User is online - create notification in PostgreSQL (marked delivered).
        # Lever B (surgical pass 2): this is the blocking-ask hot path — every
        # fleet ask_* lands here; blocking DB persist off the event loop.
        notification_id = await asyncio.to_thread(
            _persist_response_required_sync,
            resolved_sender_id, target_system_id, message, type, priority,
            title, abstract, response_type, response_default,
            parsed_response_options, timeout_seconds, job_id,
            progress_group_id, "delivered",
            sender_persona, sender_icon
        )

        # D2 (bug f433fbae): remember this key→id so a same-key re-POST re-attaches
        # to this ask instead of minting a second card.
        _record_ask_idempotency( idempotency_key, notification_id )

        print(f"[NOTIFY] Created response-required notification: {notification_id}")

        # Task 3: Create in-memory event for SSE blocking
        response_event = asyncio.Event()
        pending_responses[notification_id] = {
            "event"         : response_event,
            "response_data" : None
        }

        # DEBUG: Log the response_default value before pushing to queue
        print(f"[DEBUG] Creating notification with response_default: '{response_default}'")
        print(f"[DEBUG] Response type: {response_type}, Timeout: {timeout_seconds}s")

        # ---- Prediction Engine Hook: Generate prediction BEFORE WebSocket push ----
        # Override takes priority (testing/debug), then PredictionEngine, then None (cold start)
        prediction_hint = None
        if parsed_prediction_hint_override is not None:
            prediction_hint = parsed_prediction_hint_override
            print( f"[PREDICTION] Using override hint for {notification_id}: {prediction_hint}" )
        else:
            try:
                from cosa.agents.prediction_engine import get_prediction_engine
                prediction_engine = get_prediction_engine()
                if prediction_engine.enabled:
                    # FM-7 event-loop offload: predict() runs GPU embedding +
                    # LanceDB search synchronously; run it OFF the event loop via
                    # asyncio.to_thread so a slow embedding/search can't stall the
                    # notify path (and /health) — same idiom as the DB persist above.
                    prediction_result = await asyncio.to_thread( prediction_engine.predict, {
                        "message"          : message.strip(),
                        "response_type"    : response_type,
                        "sender_id"        : resolved_sender_id,
                        "response_options" : parsed_response_options,
                    } )
                    # Store prediction result for later outcome recording
                    pending_responses[ notification_id ][ "prediction_result" ] = prediction_result
                    # Store original message in metadata for LanceDB storage
                    if prediction_result.metadata is not None:
                        prediction_result.metadata[ "original_message" ] = message.strip()
                    # Only show hint if confidence exceeds threshold
                    if prediction_result.confidence >= prediction_engine.confidence_threshold:
                        prediction_hint = prediction_result.to_hint_dict()
                    print( f"[PREDICTION] Generated prediction for {notification_id}: "
                           f"type={response_type}, category={prediction_result.category}, "
                           f"conf={prediction_result.confidence:.3f}, hint={'yes' if prediction_hint else 'no'}" )
            except Exception as pred_error:
                print( f"[PREDICTION] ⚠️ Prediction hook error (non-fatal): {pred_error}" )

        # Stage 3 (Krishna's drift-fix): the client gates its 👍🏼/👎🏼 vote controls on the
        # INI vote gate — carry it IN the hint payload so notifications.js cannot drift
        # from the server config. Voting disabled → gate not stamped → no controls offered.
        # An override hint may pre-set the key (to e2e-test both sides of the gate).
        if prediction_hint is not None and "vote_min_confidence_threshold" not in prediction_hint:
            try:
                from cosa.agents.prediction_engine import get_prediction_engine
                vote_engine = get_prediction_engine()
                if vote_engine.hint_voting_enabled:
                    prediction_hint[ "vote_min_confidence_threshold" ] = vote_engine.hint_vote_min_confidence_threshold
            except Exception as gate_error:
                print( f"[PREDICTION] ⚠️ Vote-gate stamp error (non-fatal): {gate_error}" )
        # ---- End Prediction Engine Hook ----

        # Push notification to WebSocket for UI rendering (Phase 2.2 with full fields).
        # voice_persona_payload was resolved ONCE above the offline branch (§4.2) —
        # reuse it here instead of re-reading the bridge file.
        notification_item = notification_queue.push_notification(
            message                  = message.strip(),
            type                     = type,
            priority                 = priority,
            source                   = "claude_code",
            user_id                  = target_system_id,
            id                       = notification_id,  # Use database ID for consistency
            title                    = title or message.strip()[:50],
            response_requested       = True,
            response_type            = response_type,
            response_default         = response_default,
            response_options         = parsed_response_options,  # Multiple-choice options
            timeout_seconds          = timeout_seconds,
            sender_id                = resolved_sender_id,  # Sender-aware notification system
            abstract                 = abstract,  # Supplementary context for action-required cards
            suppress_ding            = suppress_ding,  # Skip notification sound (conversational TTS)
            job_id                   = job_id,  # Agentic job ID for routing to job cards
            queue_name               = queue_name,  # Queue for provisional job card registration
            progress_group_id        = progress_group_id,  # In-place DOM update grouping
            prediction_hint          = prediction_hint,  # Prediction hint (override or engine-generated)
            display_qualifier_widget = display_qualifier_widget,  # Expanded comment widget
            voice_persona            = voice_persona_payload,  # Per-session voice (None → server default)
            direction                = direction  # Provenance axis (human_to_ai|ai_to_ai|ai_to_human)
        )

        # DEBUG: Log the notification_item after creation
        print(f"[DEBUG] Notification item created: {notification_item}")
        print(f"[DEBUG] Notification item.response_default: '{notification_item.response_default}'")
        print(f"[DEBUG] Notification item to_dict(): {notification_item.to_dict()}")

        print(f"[NOTIFY] Pushed notification {notification_id} via WebSocket, starting SSE stream...")

        # Task 3 & 4: SSE event generator with timeout handling
        async def event_generator():
            try:
                # §4.5 E-a: opening ack frame — hands the asking client this ask's
                # notification_id BEFORE we block on the answer, so that if the SSE
                # stream later dies the client can re-attach by polling
                # GET /notifications/response/{id}. Purely additive: consume_sse_stream
                # `continue`s on an unrecognized status, so a client that ignores it is
                # unaffected.
                yield f"data: {json.dumps({'status': 'ack', 'notification_id': notification_id})}\n\n"

                # Wait for response with timeout
                await asyncio.wait_for(
                    response_event.wait(),
                    timeout = timeout_seconds
                )

                # Response received!
                response = pending_responses[notification_id]["response_data"]
                print(f"[NOTIFY] ✓ Response received for {notification_id}: {response}")

                yield f"data: {json.dumps({'status': 'responded', 'response': response, 'default_used': False})}\n\n"

            except asyncio.TimeoutError:
                # Task 4: Timeout - use default value
                print(f"[NOTIFY] ⏱️ Timeout for notification {notification_id}, using default: {response_default}")

                # Mark as expired in PostgreSQL. Lever B (surgical pass 2):
                # blocking DB write off the event loop — a fleet of asks expiring
                # together used to serialize the loop on these writes.
                await asyncio.to_thread( _mark_notification_expired_sync, notification_id )

                # Task 7: Broadcast notification_expired WebSocket event.
                # Phase C migration (2026-04-27): use the canonical dispatch
                # helper so CC listeners on the same job_id also receive the
                # expiry event (they couldn't before — emit_to_user only
                # reached the email-resolved user_id, missing the listener
                # that was registered under a shared service-account user_id).
                try:
                    ws_manager.emit_to_user_or_listener_sync(
                        user_id = target_system_id,
                        job_id  = job_id,
                        event   = "notification_expired",
                        data    = {
                            "notification_id"  : notification_id,
                            "default_used"     : response_default,
                            "timeout"          : True,
                            "timestamp"        : datetime.utcnow().isoformat()
                        }
                    )
                    print(f"[NOTIFY] ✓ Broadcast notification_expired event for {notification_id}")
                except Exception as ws_error:
                    print(f"[NOTIFY] ⚠️ Failed to broadcast notification_expired event: {ws_error}")

                default_response = {
                    "status"       : "expired",
                    "response"     : response_default,
                    "default_used" : True,
                    "timeout"      : True
                }

                yield f"data: {json.dumps(default_response)}\n\n"

            except Exception as e:
                # Unexpected error
                print(f"[NOTIFY] ❌ SSE stream error for {notification_id}: {e}")

                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

            finally:
                # Cleanup
                if notification_id in pending_responses:
                    del pending_responses[notification_id]
                    print(f"[NOTIFY] Cleaned up pending_responses for {notification_id}")

        # Return SSE streaming response
        return StreamingResponse(
            event_generator(),
            media_type = "text/event-stream",
            headers    = {
                "Cache-Control"                : "no-cache",
                "X-Accel-Buffering"            : "no",
                "Connection"                   : "keep-alive",
                "Content-Type"                 : "text/event-stream",
                "Access-Control-Allow-Origin"  : "*"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[NOTIFY] ❌ Notification error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Notification failed: {str(e)}")

@router.post(
    "/notify/response",
    summary     = "Submit notification response",
    description = "Submit user response to a response-required notification. Signals the waiting SSE stream and persists to PostgreSQL."
)
async def submit_notification_response(
    request_body: Dict[str, Any] = Body(..., description="Request body with notification_id and response_value"),
    ws_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Submit user response to a response-required notification (Phase 2.1).

    This endpoint is called by the client UI when the user responds to a notification
    (clicks Yes/No button, submits text input, etc.). It updates the database,
    signals the waiting SSE stream, and broadcasts WebSocket events.

    Requires:
        - notification_id is a valid UUID of an existing notification
        - response_value is a dict with response data
        - Notification exists in database with state='delivered'

    Ensures:
        - Updates database with response_value and state='responded'
        - Signals waiting SSE stream via asyncio.Event
        - Broadcasts notification_responded WebSocket event
        - Accepts responses within grace period (30s after expiration)
        - Returns success confirmation

    Raises:
        - HTTPException with 404 if notification not found
        - HTTPException with 400 if notification already responded/expired (outside grace period)
        - HTTPException with 500 for update failures

    Args:
        notification_id: UUID of the notification
        response_value: Response data dict (structure depends on response_type)

    Returns:
        dict: Success status and response details
    """
    try:
        # Extract fields from request body
        notification_id = request_body.get( "notification_id" )
        response_value  = request_body.get( "response_value" )

        if not notification_id:
            raise HTTPException(
                status_code = 422,
                detail      = "notification_id is required in request body"
            )

        if response_value is None:
            raise HTTPException(
                status_code = 422,
                detail      = "response_value is required in request body"
            )

        # Phase 2.4: Validate and sanitize response_value for open-ended responses
        if isinstance( response_value, str ):
            # Sanitize: Remove HTML/script tags to prevent XSS
            import re
            response_value = re.sub( r'<[^>]+>', '', response_value )

            # Empty check (after stripping whitespace)
            if len( response_value.strip() ) == 0:
                raise HTTPException(
                    status_code = 400,
                    detail      = "Response cannot be empty"
                )

        print(f"[NOTIFY] Response submission for {notification_id}: {response_value}")

        # Get notification from PostgreSQL + persist the response. Lever B
        # (surgical pass 2): blocking DB read/validate/update off the event loop.
        submit_result       = await asyncio.to_thread(
            _submit_response_sync, notification_id, response_value
        )
        recipient_id        = submit_result[ "recipient_id" ]
        notification_job_id = submit_result[ "job_id" ]
        asker_sender_id     = submit_result[ "sender_id" ]
        # The asking session's #hash8 — the listener/durable routing key when the
        # answer must travel by session rather than by job (§4.3 step 2). None when
        # the sender_id carries no #suffix (a root session).
        asker_hash8 = asker_sender_id.split( "#", 1 )[ 1 ].strip() if asker_sender_id and "#" in asker_sender_id else None

        print(f"[NOTIFY] ✓ Updated database with response for {notification_id}")

        # ---- Prediction Engine Hook 2: Record outcome on response ----
        try:
            if notification_id in pending_responses and "prediction_result" in pending_responses[notification_id]:
                from cosa.agents.prediction_engine import get_prediction_engine
                prediction_engine = get_prediction_engine()
                prediction_result = pending_responses[notification_id]["prediction_result"]

                # Determine response type from the prediction result
                resp_type = prediction_result.response_type

                # FM-7 event-loop offload: record_outcome() does 3-5 GPU
                # embeddings + a LanceDB write; run it OFF the event loop so the
                # response path (and /health) can't stall under embedding latency.
                await asyncio.to_thread(
                    prediction_engine.record_outcome,
                    notification_id   = notification_id,
                    prediction_result = prediction_result,
                    actual_value      = response_value,
                    response_type     = resp_type
                )
                print( f"[PREDICTION] ✓ Recorded outcome for {notification_id}" )
        except Exception as pred_error:
            print( f"[PREDICTION] ⚠️ Outcome recording error (non-fatal): {pred_error}" )
        # ---- End Prediction Engine Hook 2 ----

        # Task 2: Signal waiting SSE stream (if it exists)
        if notification_id in pending_responses:
            pending_responses[notification_id]["response_data"] = response_value
            pending_responses[notification_id]["event"].set()  # Wake up SSE stream!
            # Setter (a) of the §4.3 receipt-gated contract: the SSE waiter lives in
            # THIS process and its event is now set, so the asking coroutine WILL
            # consume the value — a genuine receipt. Mark the answer delivered so
            # catch-up never re-hands it. Lever B: DB write off the event loop.
            await asyncio.to_thread( _mark_answer_delivered_sync, notification_id )
            print(f"[NOTIFY] ✓ Signaled SSE stream + marked answer delivered for {notification_id}")
        else:
            # No live SSE waiter here — the answer stays owed (answer_delivered_at
            # NULL) unless the listener frame below is confirmed. The row being owed
            # is what §4.4's catch-up re-delivers; the mark is NEVER set on a send.
            print(f"[NOTIFY] No SSE stream waiting for {notification_id} (may have already completed)")

        # Task 7: Broadcast WebSocket event (notification_responded).
        # Phase C migration (2026-04-27): use the canonical dispatch helper
        # so CC listeners on the same job_id also receive the response event
        # (they couldn't before — emit_to_user only reached the email-resolved
        # recipient_id, missing the listener registered under a shared
        # service-account user_id).
        try:
            # §4.3 step 3 — the one-line live fix (fact 1): fall back to the asking
            # session's #hash8 when the ask carried no job_id (every MCP ask has
            # job_id None), so the notification_responded event reaches the asking
            # session's cc-listener socket byte-for-byte and its :481 arm delivers it.
            ws_manager.emit_to_user_or_listener_sync(
                user_id = recipient_id,
                job_id  = notification_job_id or asker_hash8,
                event   = "notification_responded",
                data    = {
                    "notification_id"  : notification_id,
                    "response_value"   : response_value,
                    "timestamp"        : datetime.utcnow().isoformat(),
                    "time_display"     : get_formatted_time_display(),
                    "date_display"     : get_formatted_date_display()
                }
            )
            print(f"[NOTIFY] ✓ Broadcast notification_responded event for {notification_id}")
        except Exception as e:
            print(f"[NOTIFY] ⚠️ Failed to broadcast WebSocket event: {e}")

        return {
            "status"           : "success",
            "message"          : f"Response recorded for notification {notification_id}",
            "notification_id"  : notification_id,
            "response_value"   : response_value,
            "timestamp"        : datetime.utcnow().isoformat(),
            "time_display"     : get_formatted_time_display(),
            "date_display"     : get_formatted_date_display()
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[NOTIFY] ❌ Response submission error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Response submission failed: {str(e)}")

def _project_undelivered_notification( n ) -> dict:
    """Project a Notification ORM row to a JSON-safe dict for the undelivered inbox (lever D)."""
    return {
        "id"         : str( n.id ),
        "sender_id"  : n.sender_id,
        "title"      : n.title,
        "message"    : n.message,
        "abstract"   : n.abstract,
        "type"       : n.type,
        "priority"   : n.priority,
        "state"      : n.state,
        "job_id"     : n.job_id,
        "created_at" : n.created_at.isoformat() if n.created_at else None,
    }


# NOTE: this static route MUST be registered BEFORE "/notifications/{user_id}" so
# FastAPI does not capture "undelivered" as a {user_id} path parameter.
def _undelivered_max_age_hours() -> int:
    """
    Resolve the undelivered-drain age cap (hours) from config.

    Storm guard (2026-06-03 incident): the durable-outbox drain must not replay
    stale rows on reconnect. The cap bounds how far back the pull-able inbox
    reaches. Runtime-tunable via the INI key.

    Ensures:
        - returns the configured int cap (default 24 hours)
    """
    import lupin_app.main as main_module
    return main_module.config_mgr.get( "notification undelivered max age hours", default=24, return_type="int" )

@router.get(
    "/notifications/undelivered",
    summary     = "Get undelivered (missed) notifications",
    description = "Pull-able AFK inbox (messaging-coordination plane, lever D): the authenticated user's notifications that never reached them (state created/queued) — what they missed while offline."
)
async def get_undelivered_notifications(
    authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)],
    limit: int = Query(100, description="Maximum undelivered notifications to return")
):
    """
    Pull the authenticated user's undelivered (missed-while-offline) notifications.

    Requires:
        - a valid API key or Bearer JWT (authenticated_user_id is the recipient's system UUID)

    Ensures:
        - returns notifications in state 'created'/'queued' (never delivered), oldest-first
        - shape: { status, undelivered_count, notifications, timestamp }

    Raises:
        - HTTPException 400 if authenticated_user_id is not a valid UUID
        - HTTPException 500 on query failure
    """
    try:
        recipient_uuid = uuid.UUID( authenticated_user_id )
    except ( ValueError, AttributeError, TypeError ):
        raise HTTPException( status_code=400, detail="authenticated user id is not a valid UUID" )

    try:
        max_age_hours = _undelivered_max_age_hours()

        def _fetch_undelivered_sync():
            # Lever B (surgical pass 2): blocking DB read off the event loop —
            # this pull-inbox fires per session-return across the whole fleet.
            with get_db() as session:
                repo  = NotificationRepository( session )
                items = repo.get_undelivered_for_recipient( recipient_uuid, limit=limit, max_age_hours=max_age_hours )
                return [ _project_undelivered_notification( n ) for n in items ]

        notifications = await asyncio.to_thread( _fetch_undelivered_sync )
        return {
            "status"            : "success",
            "undelivered_count" : len( notifications ),
            "notifications"     : notifications,
            "timestamp"         : get_local_timestamp()
        }
    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting undelivered for {authenticated_user_id}: {str( e )}" )
        raise HTTPException( status_code=500, detail=f"Failed to get undelivered notifications: {str( e )}" )


def _project_owed_answer( n, requesting_session_hash8=None ):
    """
    Project an owed-answer Notification row to the replayed-answer envelope (§4.3,
    rulings 6/7). Every replayed answer carries its ORIGINAL question text plus its
    responded_at — a bare answer with no question attached is worse than nothing
    (the model would bind it to whatever it is doing now).

    Requires:
        - n is an owed Notification row (responded, not yet handed back)

    Ensures:
        - `question` is the original ask text; `response_value` is the human's answer
        - `from_earlier_session` is True iff the asking session differs from the
          requesting one (ruling 6 — delivered, but FLAGGED as an earlier session's)
    """
    asker_hash8 = n.sender_id.split( "#", 1 )[ 1 ].strip() if n.sender_id and "#" in n.sender_id else None
    from_earlier_session = bool( requesting_session_hash8 and asker_hash8 and asker_hash8 != requesting_session_hash8 )
    return {
        "id"                   : str( n.id ),
        "sender_id"            : n.sender_id,
        "sender_persona"       : n.sender_persona,
        "session_hash8"        : asker_hash8,
        "question"             : n.message,
        "title"                : n.title,
        "abstract"             : n.abstract,
        "response_value"       : n.response_value,
        "responded_at"         : n.responded_at.isoformat() if n.responded_at else None,
        "created_at"           : n.created_at.isoformat() if n.created_at else None,
        "job_id"               : n.job_id,
        "from_earlier_session" : from_earlier_session,
    }


@router.get(
    "/notifications/answers-owed",
    summary     = "Get answers owed to a persona (late-answer handback pull inbox)",
    description = "Persona-keyed pull inbox (§4.4): answered asks not yet handed back to the session that asked. Retrieval matches sender_persona ALONE (ruling 6); session_hash8 sets the earlier-session flag but NEVER filters. Serving does NOT mark delivered — that is the companion /ack (ack-on-consume)."
)
async def get_answers_owed(
    authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)],
    persona: str = Query(..., description="The persona whose owed answers to pull (retrieval key — ruling 6, matched alone)."),
    session_hash8: Optional[str] = Query(None, description="Requesting session's 8-char hash. Sets the earlier-session flag on each envelope; NEVER filters (ruling 6)."),
    since: Optional[str] = Query(None, description="ISO responded_at cursor — only answers responded AFTER it. Cursor advances on responded_at, not created_at."),
    limit: int = Query(100, description="Maximum owed answers to return.")
):
    """
    Pull the answers owed to `persona` — answered asks not yet handed back (§4.4).

    Requires:
        - a valid API key or Bearer JWT (X-API-Key lane resolves the human owner —
          the row's recipient_id; NOT the listener's ambient service-account id.
          D-V1 is the negative control that proves this on real credentials)
        - persona is a non-empty retrieval key

    Ensures:
        - returns owed envelopes (question + answer + responded_at + flag), oldest
          answer first (ordered/cursored on responded_at)
        - SERVING does NOT set answer_delivered_at — only /ack does (ack-on-consume)

    Raises:
        - HTTPException 500 on query failure

    ⚠️ AUTHENTICATED, NOT AUTHORIZED — a RULED design decision, not an oversight
    (Rick, 2026-08-01: "let's leave it where it is, this is one trusted fleet…
    let's make sure we document this behavior"). This endpoint checks that the
    caller holds a valid credential; it does NOT check that the credential
    belongs to `persona`. Any valid key can pull any persona's owed answers.

    This is one property read two ways. `persona` is matched ALONE (ruling 6)
    precisely so a returning session can pull what accumulated in its absence —
    the caller's own identity is never a parameter of the query. That is what
    makes the service-account lane failure unexpressible rather than merely
    unused (the D-V1 negative control), and it is the same reason the endpoint
    cannot tell one caller's request from another's.

    The trust boundary, stated so a later reader need not re-derive it: every
    credential here belongs to a session in this fleet. If that stops being true
    — an outside integration, a shared key, a key that outlives its seat — this
    becomes a real hole, and closing it means binding keys to personas, which
    they are not today. Filed and closed as `fd245188`.
    """
    try:
        max_age_hours = _undelivered_max_age_hours()
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat( since )
            except ValueError:
                raise HTTPException( status_code=400, detail="`since` must be an ISO-8601 timestamp" )

        def _fetch_owed_sync():
            # Lever B: blocking DB read off the event loop — fires per session-return.
            with get_db() as session:
                repo  = NotificationRepository( session )
                items = repo.get_answers_owed_for_persona(
                    persona, limit=limit, max_age_hours=max_age_hours, since=since_dt
                )
                return [ _project_owed_answer( n, requesting_session_hash8=session_hash8 ) for n in items ]

        answers = await asyncio.to_thread( _fetch_owed_sync )
        return {
            "status"      : "success",
            "owed_count"  : len( answers ),
            "answers"     : answers,
            "timestamp"   : get_local_timestamp()
        }
    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting answers-owed for persona {persona!r}: {str( e )}" )
        raise HTTPException( status_code=500, detail=f"Failed to get answers owed: {str( e )}" )


@router.post(
    "/notifications/answers-owed/ack",
    summary     = "Ack a handed-back answer (mark delivered)",
    description = "Setter (b)/(c) of the §4.3 receipt-gated contract: stamp answer_delivered_at for a notification the client has CONSUMED. Ack on consume, never on serve — a dropped serve response must leave the answer owed. The row is never deleted (ruling 2)."
)
async def ack_answer_owed(
    authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)],
    request_body: Dict[str, Any] = Body(..., description="Request body with notification_id")
):
    """
    Ack an owed answer as consumed — the pull/re-attach receipt (§4.3 setters b/c).

    Requires:
        - a valid API key or Bearer JWT
        - request_body.notification_id is a valid UUID string

    Ensures:
        - answer_delivered_at is stamped so catch-up will not re-surface the row
        - the row is NOT deleted (ruling 2)

    Raises:
        - HTTPException 422 if notification_id is missing
        - HTTPException 404 if the notification does not exist
        - HTTPException 500 on update failure
    """
    notification_id = request_body.get( "notification_id" )
    if not notification_id:
        raise HTTPException( status_code=422, detail="notification_id is required in request body" )
    try:
        def _ack_sync():
            with get_db() as session:
                repo   = NotificationRepository( session )
                marked = repo.mark_answer_delivered( uuid.UUID( notification_id ) )
                return marked is not None

        found = await asyncio.to_thread( _ack_sync )
        if not found:
            raise HTTPException( status_code=404, detail=f"Notification {notification_id} not found" )
        return {
            "status"          : "success",
            "notification_id" : notification_id,
            "timestamp"       : get_local_timestamp()
        }
    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error acking answer {notification_id}: {str( e )}" )
        raise HTTPException( status_code=500, detail=f"Failed to ack answer: {str( e )}" )


@router.get(
    "/notifications/response/{notification_id}",
    summary     = "Read one notification's response state (re-attach poll target)",
    description = "PURE READ (§4.5 E-b) of {state, response_value, responded_at} for one notification. The MCP re-attach poll reads this after its SSE stream dies to learn whether the human answered. **No ack** — serving does NOT set answer_delivered_at; the ack is the explicit companion POST /answers-owed/ack. Registered BEFORE /notifications/{user_id} so the static path is not captured as a {user_id}."
)
async def get_notification_response(
    authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)],
    notification_id: str
):
    """
    Read one notification's response state — the re-attach poll target (§4.5 step 2).

    Requires:
        - a valid API key or Bearer JWT
        - notification_id is a UUID string

    Ensures:
        - returns { state, response_value, responded_at } (responded_at ISO or None)
        - PURE READ — never sets answer_delivered_at (serving is not a receipt); the
          caller decides landed-ness on `responded_at IS NOT NULL` and acks separately
        - 404 when the notification does not exist

    Raises:
        - HTTPException 404 if the notification does not exist
        - HTTPException 500 on read failure
    """
    try:
        def _fetch_response_sync():
            with get_db() as session:
                repo = NotificationRepository( session )
                n    = repo.get_by_id( uuid.UUID( notification_id ) )
                if n is None:
                    return None
                return {
                    "state"          : n.state,
                    "response_value" : n.response_value,
                    "responded_at"   : n.responded_at.isoformat() if n.responded_at else None,
                }

        result = await asyncio.to_thread( _fetch_response_sync )
        if result is None:
            raise HTTPException( status_code=404, detail=f"Notification {notification_id} not found" )
        return {
            "status"          : "success",
            "notification_id" : notification_id,
            **result,
            "timestamp"       : get_local_timestamp()
        }
    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error reading response for {notification_id}: {str( e )}" )
        raise HTTPException( status_code=500, detail=f"Failed to read notification response: {str( e )}" )


@router.post(
    "/notifications/undelivered/dismiss",
    summary     = "Dismiss (reset) undelivered notifications",
    description = "Reset the 'N missed while away' badge: soft-dismiss (is_hidden=True) the authenticated user's undelivered notifications (state created/queued). State is preserved (audit trail); the badge and pull-able inbox both drop to zero."
)
async def dismiss_undelivered_notifications(
    authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)]
):
    """
    Soft-dismiss the authenticated user's undelivered (missed-while-offline) notifications.

    Backs the "reset" button beside the "N missed while away" indicator. Sets is_hidden=True
    on every row the badge counts (mirroring the count query, including the 24h age cap) so
    the badge zeroes; notification state is left untouched so the never-delivered audit trail
    survives. Reversible by flipping is_hidden back.

    Requires:
        - a valid API key or Bearer JWT (authenticated_user_id is the recipient's system UUID)

    Ensures:
        - soft-dismisses rows in state 'created'/'queued' within the configured age cap
        - shape: { status, dismissed_count, undelivered_count, timestamp }
        - undelivered_count is the post-dismiss count (0 on success)

    Raises:
        - HTTPException 400 if authenticated_user_id is not a valid UUID
        - HTTPException 500 on update failure
    """
    try:
        recipient_uuid = uuid.UUID( authenticated_user_id )
    except ( ValueError, AttributeError, TypeError ):
        raise HTTPException( status_code=400, detail="authenticated user id is not a valid UUID" )

    try:
        max_age_hours = _undelivered_max_age_hours()

        def _dismiss_undelivered_sync():
            # Lever B (surgical pass 2): blocking DB update off the event loop.
            with get_db() as session:
                repo            = NotificationRepository( session )
                dismissed_count = repo.dismiss_undelivered_for_recipient( recipient_uuid, max_age_hours=max_age_hours )
                remaining       = repo.count_undelivered_for_recipient( recipient_uuid, max_age_hours=max_age_hours )
                return ( dismissed_count, remaining )

        dismissed_count, remaining = await asyncio.to_thread( _dismiss_undelivered_sync )
        print( f"[NOTIFY] Dismissed {dismissed_count} undelivered notification(s) for {authenticated_user_id}" )
        return {
            "status"            : "success",
            "dismissed_count"   : dismissed_count,
            "undelivered_count" : remaining,
            "timestamp"         : get_local_timestamp()
        }
    except Exception as e:
        print( f"[NOTIFY] Error dismissing undelivered for {authenticated_user_id}: {str( e )}" )
        raise HTTPException( status_code=500, detail=f"Failed to dismiss undelivered notifications: {str( e )}" )


class PredictionVoteRequest( BaseModel ):
    """Body for POST /api/notify/prediction-vote/{notification_id}.

    The client supplies the hint context it is voting on. `question` and `response_type`
    are OPTIONAL because the endpoint authoritatively resolves them from the persisted
    notification when the client omits them (the notification.message IS persisted; the
    prediction hint's predicted_value is NOT, so the client must supply predicted_value)."""
    vote            : Literal[ "up", "down" ]
    predicted_value : Any = None
    question        : Optional[ str ] = None
    category        : Optional[ str ] = None
    response_type   : Optional[ str ] = None


@router.post(
    "/notify/prediction-vote/{notification_id}",
    summary     = "Vote on a prediction hint (thumbs up/down → training signal)",
    description = "Record the user's 👍/👎 on a prediction hint. up→approved (reinforce in future CBR retrieval), down→rejected (negative vote — steer away). Writes one human-confirmed organic case into the prediction CBR store; idempotent per notification (re-vote flips state in place)."
)
async def vote_on_prediction_hint(
    notification_id: str,
    body: PredictionVoteRequest,
    authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)]
):
    """
    Record a thumbs up/down vote on a prediction hint as human-confirmed training signal.

    Requires:
        - a valid API key or Bearer JWT
        - body.vote in {"up","down"}, body.question non-empty (Pydantic-validated → 422)

    Ensures:
        - writes/updates exactly one organic CBR case (approved on up / rejected on down)
        - idempotent: a re-vote on the same notification flips the case state in place
        - shape: { status, notification_id, vote, ratification_state, updated, timestamp }

    Raises:
        - HTTPException 422 if record_hint_vote rejects the vote value
        - HTTPException 500 on record failure
    """
    # Resolve question + response_type authoritatively from the persisted notification when
    # the client omits them (notification.message is persisted; predicted_value is not).
    question      = ( body.question or "" ).strip()
    response_type = body.response_type
    try:
        notif_uuid = uuid.UUID( notification_id )
        with get_db() as session:
            notif = NotificationRepository( session ).get_by_id( notif_uuid )
            if notif is not None:
                if not question:      question      = ( notif.message or "" ).strip()
                if not response_type: response_type = notif.response_type
    except ( ValueError, AttributeError, TypeError ):
        pass  # non-UUID id or lookup failure → fall back to whatever the client supplied

    if not question:
        raise HTTPException( status_code=422, detail="could not resolve a question for this notification (none supplied and notification not found)" )
    if body.predicted_value is None:
        raise HTTPException( status_code=422, detail="predicted_value is required to record a prediction vote" )

    try:
        from cosa.agents.prediction_engine import get_prediction_engine
        engine = get_prediction_engine()
        # FM-7 event-loop offload: record_hint_vote() may generate an embedding
        # + write to LanceDB; run it OFF the event loop so the vote path (and
        # /health) can't stall under embedding/store latency.
        result = await asyncio.to_thread(
            engine.record_hint_vote,
            notification_id = notification_id,
            question        = question,
            predicted_value = body.predicted_value,
            category        = body.category,
            response_type   = response_type,
            vote            = body.vote,
        )
        print( f"[NOTIFY] Prediction-hint vote '{body.vote}' for {notification_id} -> {result.get( 'ratification_state' )}" )
        return {
            "status"             : "success",
            "notification_id"    : notification_id,
            "vote"               : body.vote,
            "ratification_state" : result.get( "ratification_state" ),
            "updated"            : result.get( "updated", False ),
            "timestamp"          : get_local_timestamp()
        }
    except ValueError as e:
        raise HTTPException( status_code=422, detail=str( e ) )
    except Exception as e:
        print( f"[NOTIFY] Prediction-hint vote error for {notification_id}: {str( e )}" )
        raise HTTPException( status_code=500, detail=f"Failed to record prediction vote: {str( e )}" )


@router.get(
    "/notifications/{user_id}",
    summary     = "Get user notifications",
    description = "Retrieve notifications for a user from the in-memory FIFO queue with optional played filter and count limit."
)
async def get_user_notifications(
    user_id: str,
    include_played: bool = Query(True, description="Include played notifications"),
    limit: int = Query(50, description="Maximum number of notifications to return"),
    notification_queue: NotificationFifoQueue = Depends(get_notification_queue)
):
    """
    Get notifications for a specific user.
    
    Requires:
        - user_id is a non-empty valid system user ID
        - notification_queue is initialized and accessible
        - include_played is a boolean value
        - limit is a positive integer or None
        
    Ensures:
        - Retrieves all notifications for the specified user
        - Applies include_played filter as requested
        - Limits results to specified number if provided
        - Returns notifications sorted by timestamp (newest first)
        - Includes metadata about query parameters and results
        
    Raises:
        - HTTPException with 500 for query failures
        
    Args:
        user_id: The system user ID (not email)
        include_played: Whether to include already played notifications
        limit: Maximum number of notifications to return
        
    Returns:
        dict: User notifications with metadata
    """
    try:
        notifications = notification_queue.get_user_notifications(
            user_id=user_id,
            include_played=include_played
        )
        
        # Apply limit manually if specified
        if limit and limit < len(notifications):
            notifications = notifications[:limit]
        
        return {
            "status": "success",
            "user_id": user_id,
            "notification_count": len(notifications),
            "include_played": include_played,
            "limit": limit,
            "notifications": notifications,
            "timestamp": get_local_timestamp()
        }
        
    except Exception as e:
        print(f"[NOTIFY] Error getting notifications for {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get notifications: {str(e)}")

@router.get(
    "/notifications/{user_id}/next",
    summary     = "Get next notification",
    description = "Fetch the next unplayed notification for a user without modifying its played state."
)
async def get_next_notification(
    user_id: str,
    notification_queue: NotificationFifoQueue = Depends(get_notification_queue)
):
    """
    Get the next unplayed notification for a user.
    
    Requires:
        - user_id is a non-empty valid system user ID
        - notification_queue is initialized and accessible
        
    Ensures:
        - Retrieves the next unplayed notification if available
        - Does not modify notification played status
        - Returns appropriate status indicating found/not found
        - Includes timestamp for response tracking
        
    Raises:
        - HTTPException with 500 for query failures
        
    Args:
        user_id: The system user ID (not email)
        
    Returns:
        dict: Next notification or null if none available
    """
    try:
        next_notification = notification_queue.get_next_unplayed(user_id)
        
        if next_notification:
            return {
                "status": "found",
                "user_id": user_id,
                "notification": next_notification,
                "timestamp": get_local_timestamp()
            }
        else:
            return {
                "status": "none_available",
                "user_id": user_id,
                "notification": None,
                "timestamp": get_local_timestamp()
            }
            
    except Exception as e:
        print(f"[NOTIFY] Error getting next notification for {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get next notification: {str(e)}")

@router.post(
    "/notifications/{notification_id}/played",
    summary     = "Mark notification played",
    description = "Mark a notification as played with timestamp. Persists to the io_tbl database."
)
async def mark_notification_played(
    notification_id: str,
    notification_queue: NotificationFifoQueue = Depends(get_notification_queue)
):
    """
    Mark a notification as played.
    
    Requires:
        - notification_id is a non-empty valid notification ID
        - notification_queue is initialized and accessible
        - notification with given ID exists in the queue
        
    Ensures:
        - Updates notification played status with timestamp
        - Persists played status to io_tbl database
        - Returns success confirmation with notification details
        - Raises 404 if notification not found
        
    Raises:
        - HTTPException with 404 if notification not found
        - HTTPException with 500 for update failures
        
    Args:
        notification_id: The unique notification ID
        
    Returns:
        dict: Success status and updated notification info
    """
    try:
        # Lever B (surgical pass 2) — the 2026-06-11 wedge smoking gun: the browser
        # fires this endpoint per TTS playback, and mark_played logs to io_tbl with
        # async_embedding=False — TWO synchronous embedding generations plus a
        # LanceDB write into a fragmenting table, formerly ALL on the event loop
        # (stalls grew with daily fragmentation: the 10:48 → 20:23 worsening).
        # mark_played is safe to run on a worker thread: its WS emit goes
        # through the manager's _sync wrappers, which schedule onto the main
        # loop via asyncio.run_coroutine_threadsafe by design, and the queue's
        # shared structures are guarded by the base FifoQueue RLock.
        success = await asyncio.to_thread( notification_queue.mark_played, notification_id )

        if success:
            return {
                "status": "success",
                "message": f"Notification {notification_id} marked as played",
                "notification_id": notification_id,
                "timestamp": get_local_timestamp()
            }
        else:
            raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"[NOTIFY] Error marking notification {notification_id} as played: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to mark notification as played: {str(e)}")

@router.delete(
    "/notifications/{notification_id}",
    summary     = "Delete notification",
    description = "Permanently remove a single notification from the FIFO queue and io_tbl database."
)
async def delete_notification(
    notification_id: str,
    notification_queue: NotificationFifoQueue = Depends(get_notification_queue)
):
    """
    Delete a notification.
    
    Requires:
        - notification_id is a non-empty valid notification ID
        - notification_queue is initialized and accessible
        - notification with given ID exists in the queue
        
    Ensures:
        - Removes notification from queue and io_tbl database
        - Returns success confirmation with deletion details
        - Raises 404 if notification not found
        
    Raises:
        - HTTPException with 404 if notification not found
        - HTTPException with 500 for deletion failures
        
    Args:
        notification_id: The unique notification ID
        
    Returns:
        dict: Success status and deletion info
    """
    try:
        success = notification_queue.delete_by_id_hash(notification_id)
        
        if success:
            return {
                "status": "success",
                "message": f"Notification {notification_id} deleted",
                "notification_id": notification_id,
                "timestamp": get_local_timestamp()
            }
        else:
            raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[NOTIFY] Error deleting notification {notification_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete notification: {str(e)}")


@router.delete(
    "/notifications/bulk/{user_email}",
    summary     = "Bulk delete notifications",
    description = "Delete all notifications for a user from PostgreSQL with optional time window filter."
)
async def bulk_delete_notifications(
    user_email: str,
    hours: Optional[int] = Query( None, description="Filter to notifications within N hours (None = all)" ),
    exclude_own_jobs: bool = Query( False, description="Only delete notifications NOT from user's own jobs (admin 'not mine' filter)" )
):
    """
    Bulk delete notifications for a user within the specified time window.

    This endpoint is used by the "Clear All" button in the Notifications UI.
    It deletes all notifications matching the current history filter.

    Requires:
        - user_email is a valid registered email address
        - hours is None (delete all) or a positive integer (delete within N hours)

    Ensures:
        - All notifications matching user and time filter are permanently deleted
        - When exclude_own_jobs is True, only deletes notifications NOT triggered by
          user's own jobs (and NOT system notifications with NULL job_id)
        - Returns count of deleted notifications

    Raises:
        - HTTPException with 404 if user not found
        - HTTPException with 400 if hours is invalid
        - HTTPException with 500 for deletion failures

    Args:
        user_email: User's email address
        hours: Optional filter - only delete notifications within N hours (None = all)
        exclude_own_jobs: Whether to scope deletion to "not mine" notifications only

    Returns:
        JSON with deleted count and status
    """
    try:
        # Validate hours if provided
        if hours is not None and hours <= 0:
            raise HTTPException(
                status_code = 400,
                detail      = "hours must be a positive integer or null for all notifications"
            )

        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        # Build exclude_job_ids list if "not mine" filter is active
        exclude_job_ids = None
        if exclude_own_jobs:
            from cosa.rest.queue_extensions import user_job_tracker
            user_uid = user_data.get( "uid", "" )
            exclude_job_ids = user_job_tracker.get_jobs_for_user( user_uid )

        with get_db() as session:
            repo = NotificationRepository( session )
            deleted_count = repo.bulk_delete_by_user(
                user_email      = user_email,
                recipient_id    = user_id,
                hours           = hours,
                exclude_job_ids = exclude_job_ids
            )

            filter_desc = f"within {hours} hours" if hours else "all time"
            scope_desc  = " (not-mine only)" if exclude_own_jobs else ""
            print( f"[NOTIFY] Bulk deleted {deleted_count} notifications for {user_email} ({filter_desc}){scope_desc}" )

            return {
                "status"           : "success",
                "user_email"       : user_email,
                "hours_filter"     : hours,
                "exclude_own_jobs" : exclude_own_jobs,
                "deleted_count"    : deleted_count
            }

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error bulk deleting notifications for {user_email}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to bulk delete notifications: {str( e )}"
        )


# =============================================================================
# HISTORY ENDPOINTS (Phase 6 - Sender-Aware Notification System)
# =============================================================================

@router.get(
    "/notifications/senders/{user_email}",
    summary     = "List notification senders",
    description = "Return all distinct senders who have sent notifications to a user with last activity and count."
)
async def get_senders_with_activity(
    user_email: str,
    hours: Optional[int] = Query( None, description="Filter to senders active within N hours" )
):
    """
    Get list of senders with recent notification activity for a user.

    Returns sender IDs ordered by most recent activity, with last activity
    timestamp and notification count. Used by frontend for sender card initialization.

    Requires:
        - user_email is a valid registered email address
        - User exists in auth database

    Ensures:
        - Returns list of {sender_id, last_activity, count} sorted by last_activity desc
        - Optional hours filter limits to recent activity
        - Empty list if no notifications found

    Raises:
        - HTTPException with 404 if user not found
        - HTTPException with 500 for query failures

    Args:
        user_email: User's email address
        hours: Optional filter - only include senders active within N hours

    Returns:
        List of sender activity summaries
    """
    try:
        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        with get_db() as session:
            repo = NotificationRepository( session )
            activities = repo.get_sender_last_activities( user_id )

            # Apply hours filter if specified
            if hours is not None:
                cutoff = datetime.now( timezone.utc ) - timedelta( hours=hours )
                activities = [
                    a for a in activities
                    if a["last_activity"] >= cutoff
                ]

            # Convert datetime to ISO string for JSON serialization
            for activity in activities:
                if activity["last_activity"]:
                    activity["last_activity"] = activity["last_activity"].isoformat()

            print( f"[NOTIFY] Returning {len( activities )} senders for {user_email}" )

            return activities

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting senders for {user_email}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get sender list: {str( e )}"
        )


@router.get(
    "/notifications/conversation/{sender_id}/{user_email}",
    summary     = "Get sender conversation",
    description = "Retrieve time-windowed conversation thread between a specific sender and recipient."
)
async def get_sender_conversation(
    sender_id: str,
    user_email: str,
    hours: int = Query( 24, description="Window size in hours (default: 24)" ),
    anchor: Optional[str] = Query( None, description="ISO timestamp to anchor window around" )
):
    """
    Get conversation history between a sender and recipient.

    Returns notifications in chronological order (oldest first) for chat-style display.
    Uses activity-anchored window loading - window is relative to anchor timestamp
    (defaults to sender's last activity).

    Requires:
        - sender_id is a valid sender identifier (e.g., claude.code@lupin.deepily.ai)
        - user_email is a valid registered email address
        - User exists in auth database

    Ensures:
        - Returns notifications within [anchor - hours, anchor]
        - Notifications sorted chronologically (oldest first)
        - Each notification includes full details for UI rendering
        - Empty list if no notifications found

    Raises:
        - HTTPException with 404 if user not found
        - HTTPException with 500 for query failures

    Args:
        sender_id: Sender identifier
        user_email: User's email address
        hours: Window size in hours (default: 24)
        anchor: Optional ISO timestamp to anchor window around

    Returns:
        List of notification objects for the conversation
    """
    from cosa.config.configuration_manager import ConfigurationManager

    try:
        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        # Parse anchor timestamp if provided
        anchor_dt = None
        if anchor:
            try:
                anchor_dt = datetime.fromisoformat( anchor.replace( 'Z', '+00:00' ) )
            except ValueError:
                raise HTTPException(
                    status_code = 400,
                    detail      = f"Invalid anchor timestamp format: {anchor}"
                )

        # Get timezone from configuration for consistent timestamp serialization
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        timezone_name = config_mgr.get( "app timezone", default="America/New_York" )
        tz = zoneinfo.ZoneInfo( timezone_name )

        # Helper to convert timestamp to local timezone before serialization
        def format_ts( dt ):
            if dt is None:
                return None
            return dt.astimezone( tz ).isoformat()

        def format_time_display( dt ):
            if dt is None:
                return None
            return dt.astimezone( tz ).strftime( '%H:%M %Z' )

        with get_db() as session:
            repo = NotificationRepository( session )
            notifications = repo.get_sender_conversation(
                sender_id    = sender_id,
                recipient_id = user_id,
                anchor       = anchor_dt,
                window_hours = hours
            )

            # Convert to dict for JSON serialization
            result = []
            for notif in notifications:
                result.append( {
                    "id"                 : str( notif.id ),
                    "sender_id"          : notif.sender_id,
                    "message"            : notif.message,
                    "title"              : notif.title,
                    "type"               : notif.type,
                    "priority"           : notif.priority,
                    "state"              : notif.state,
                    "is_hidden"          : notif.is_hidden,
                    "abstract"           : notif.abstract,
                    "created_at"         : format_ts( notif.created_at ),
                    "delivered_at"       : format_ts( notif.delivered_at ),
                    "responded_at"       : format_ts( notif.responded_at ),
                    "response_requested" : notif.response_requested,
                    "response_type"      : notif.response_type,
                    "response_value"     : notif.response_value,
                    "job_id"             : notif.job_id,
                    "progress_group_id"  : notif.progress_group_id,
                    "timestamp"          : format_ts( notif.created_at ),
                    "time_display"       : format_time_display( notif.created_at )
                } )

            print( f"[NOTIFY] Returning {len( result )} notifications for {sender_id} → {user_email}" )

            return result

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting conversation for {sender_id}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get conversation: {str( e )}"
        )


@router.delete(
    "/notifications/conversation/{sender_id}/{user_email}",
    summary     = "Delete sender conversation",
    description = "Permanently delete all notifications from a specific sender to a recipient."
)
async def delete_sender_conversation( sender_id: str, user_email: str ):
    """
    Delete all notifications in a conversation between sender and recipient.

    Allows users to delete an entire conversation (all notifications from a specific
    sender) rather than deleting individual notifications.

    Requires:
        - sender_id is a valid sender identifier (e.g., claude.code@lupin.deepily.ai)
        - user_email is a valid registered email address
        - User exists in auth database

    Ensures:
        - All notifications matching sender_id AND recipient deleted
        - Returns count of deleted notifications
        - Returns 404 if user not found (not if conversation empty)

    Raises:
        - HTTPException with 404 if user not found
        - HTTPException with 500 for deletion failures

    Args:
        sender_id: Sender identifier
        user_email: User's email address

    Returns:
        JSON with deleted count
    """
    try:
        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        with get_db() as session:
            repo = NotificationRepository( session )
            deleted_count = repo.delete_by_sender(
                sender_id    = sender_id,
                recipient_id = user_id
            )

            print( f"[NOTIFY] Deleted {deleted_count} notifications for {sender_id} → {user_email}" )

            return {
                "status"        : "success",
                "sender_id"     : sender_id,
                "user_email"    : user_email,
                "deleted_count" : deleted_count
            }

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error deleting conversation for {sender_id}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to delete conversation: {str( e )}"
        )


@router.get(
    "/notifications/conversation-by-date/{sender_id}/{user_email}",
    summary     = "Get conversation by date",
    description = "Return notifications grouped by date for accordion-style UI rendering."
)
async def get_sender_conversation_by_date(
    sender_id: str,
    user_email: str,
    hours: int = Query( 168, description="Window size in hours (default: 168 = 7 days)" ),
    anchor: Optional[str] = Query( None, description="ISO timestamp to anchor window around" ),
    include_hidden: bool = Query( False, description="Include hidden/archived notifications" )
):
    """
    Get conversation history grouped by date (ISO format).

    Returns notifications organized by date for accordion-style UI display.
    Each date key contains notifications in chronological order.

    Requires:
        - sender_id is a valid sender identifier (e.g., claude.code@lupin.deepily.ai)
        - user_email is a valid registered email address
        - User exists in auth database

    Ensures:
        - Returns dict of date_string -> list of notifications
        - Date keys are ISO format (YYYY-MM-DD) in user's timezone
        - Notifications within each date sorted chronologically

    Args:
        sender_id: Sender identifier
        user_email: User's email address
        hours: Window size in hours (default: 168 = 7 days)
        anchor: Optional ISO timestamp to anchor window around
        include_hidden: Whether to include hidden/archived notifications

    Returns:
        Dict mapping date strings to notification lists
    """
    from cosa.config.configuration_manager import ConfigurationManager

    try:
        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        # Parse anchor timestamp if provided
        anchor_dt = None
        if anchor:
            try:
                anchor_dt = datetime.fromisoformat( anchor.replace( 'Z', '+00:00' ) )
            except ValueError:
                raise HTTPException(
                    status_code = 400,
                    detail      = f"Invalid anchor timestamp format: {anchor}"
                )

        # Get timezone from configuration
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        timezone_name = config_mgr.get( "app timezone", default="America/New_York" )
        tz = zoneinfo.ZoneInfo( timezone_name )

        # Helper to convert timestamp to local timezone before serialization
        def format_ts( dt ):
            if dt is None:
                return None
            return dt.astimezone( tz ).isoformat()

        def format_time_display( dt ):
            if dt is None:
                return None
            return dt.astimezone( tz ).strftime( '%H:%M %Z' )

        with get_db() as session:
            repo = NotificationRepository( session )
            date_groups = repo.get_sender_conversations_by_date(
                sender_id     = sender_id,
                recipient_id  = user_id,
                anchor        = anchor_dt,
                window_hours  = hours,
                include_hidden = include_hidden,
                timezone_name = timezone_name
            )

            # Convert to dict for JSON serialization
            result = {}
            for date_key, notifications in date_groups.items():
                result[ date_key ] = []
                for notif in notifications:
                    result[ date_key ].append( {
                        "id"                 : str( notif.id ),
                        "sender_id"          : notif.sender_id,
                        "message"            : notif.message,
                        "title"              : notif.title,
                        "type"               : notif.type,
                        "priority"           : notif.priority,
                        "state"              : notif.state,
                        "is_hidden"          : notif.is_hidden,
                        "abstract"           : notif.abstract,
                        "created_at"         : format_ts( notif.created_at ),
                        "delivered_at"       : format_ts( notif.delivered_at ),
                        "responded_at"       : format_ts( notif.responded_at ),
                        "response_requested" : notif.response_requested,
                        "response_type"      : notif.response_type,
                        "response_value"     : notif.response_value,
                        "job_id"             : notif.job_id,
                        "progress_group_id"  : notif.progress_group_id,
                        "timestamp"          : format_ts( notif.created_at ),
                        "time_display"       : format_time_display( notif.created_at )
                    } )

            total_count = sum( len( v ) for v in result.values() )
            print( f"[NOTIFY] Returning {total_count} notifications in {len( result )} date groups for {sender_id} → {user_email}" )

            return result

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting date-grouped conversation for {sender_id}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get date-grouped conversation: {str( e )}"
        )


@router.delete(
    "/notifications/date/{sender_id}/{user_email}/{date_string}",
    summary     = "Soft-delete by date",
    description = "Soft-delete all notifications from a sender on a specific date by setting is_hidden flag."
)
async def soft_delete_by_date( sender_id: str, user_email: str, date_string: str ):
    """
    Soft delete all notifications for a sender on a specific date.

    Sets is_hidden=True for matching notifications instead of permanently deleting.
    This preserves data for analysis while hiding from the UI.

    Requires:
        - sender_id is a valid sender identifier (e.g., claude.code@lupin.deepily.ai)
        - user_email is a valid registered email address
        - date_string is ISO format (YYYY-MM-DD)
        - User exists in auth database

    Ensures:
        - Sets is_hidden=True for all matching notifications
        - Uses configured timezone for date interpretation
        - Returns count of hidden notifications

    Args:
        sender_id: Sender identifier
        user_email: User's email address
        date_string: ISO format date (YYYY-MM-DD)

    Returns:
        JSON with hidden count and status
    """
    from cosa.config.configuration_manager import ConfigurationManager

    try:
        # Validate date format
        try:
            from datetime import date as date_type
            date_type.fromisoformat( date_string )
        except ValueError:
            raise HTTPException(
                status_code = 400,
                detail      = f"Invalid date format: {date_string}. Expected YYYY-MM-DD."
            )

        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        # Get timezone from configuration
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        timezone_name = config_mgr.get( "app timezone", default="America/New_York" )

        with get_db() as session:
            repo = NotificationRepository( session )
            hidden_count = repo.soft_delete_by_date(
                sender_id     = sender_id,
                recipient_id  = user_id,
                date_string   = date_string,
                timezone_name = timezone_name
            )

            print( f"[NOTIFY] Soft deleted {hidden_count} notifications for {sender_id} on {date_string}" )

            return {
                "status"       : "success",
                "sender_id"    : sender_id,
                "user_email"   : user_email,
                "date"         : date_string,
                "hidden_count" : hidden_count
            }

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error soft deleting notifications for {sender_id} on {date_string}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to soft delete notifications: {str( e )}"
        )


@router.get(
    "/notifications/sender-dates/{sender_id}/{user_email}",
    summary     = "Get sender date summaries",
    description = "Return lightweight date headers with counts for building accordion UI."
)
async def get_sender_date_summaries(
    sender_id: str,
    user_email: str,
    include_hidden: bool = Query( False, description="Include hidden/archived notifications" )
):
    """
    Get date-grouped summaries for a sender with counts.

    Returns a list of dates with notification counts, useful for
    building the date accordion headers without loading full notifications.

    Requires:
        - sender_id is a valid sender identifier (e.g., claude.code@lupin.deepily.ai)
        - user_email is a valid registered email address
        - User exists in auth database

    Ensures:
        - Returns list of date summaries ordered by date descending
        - Each summary includes date, count, and new_count

    Args:
        sender_id: Sender identifier
        user_email: User's email address
        include_hidden: Whether to include hidden notifications in counts

    Returns:
        List of date summary objects
    """
    from cosa.config.configuration_manager import ConfigurationManager

    try:
        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        # Get timezone from configuration
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        timezone_name = config_mgr.get( "app timezone", default="America/New_York" )

        with get_db() as session:
            repo = NotificationRepository( session )
            summaries = repo.get_sender_date_summaries(
                sender_id      = sender_id,
                recipient_id   = user_id,
                include_hidden = include_hidden,
                timezone_name  = timezone_name
            )

            print( f"[NOTIFY] Returning {len( summaries )} date summaries for {sender_id} → {user_email}" )

            return summaries

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting date summaries for {sender_id}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get date summaries: {str( e )}"
        )


@router.get(
    "/notifications/senders-visible/{user_email}",
    summary     = "List visible senders",
    description = "Enhanced sender list respecting is_hidden flag with unread counts for notification badges."
)
async def get_visible_senders(
    user_email: str,
    hours: Optional[int] = Query( None, description="Filter to senders with activity within N hours" ),
    include_hidden: bool = Query( False, description="Include hidden notifications in counts" ),
    exclude_own_jobs: bool = Query( False, description="Exclude notifications from user's own jobs (admin 'not mine' filter)" )
):
    """
    Get list of senders with visible notifications for a user.

    Enhanced version of get_senders that respects is_hidden flag and
    includes new_count for unread notification badges.

    Requires:
        - user_email is a valid registered email address
        - User exists in auth database

    Ensures:
        - Returns list of sender activity summaries
        - Excludes senders with all notifications hidden (unless include_hidden)
        - When exclude_own_jobs is True, excludes notifications triggered by user's own jobs
          and system notifications (NULL job_id) — only shows "others'" notifications
        - Ordered by last_activity descending (most recent first)
        - Includes new_count for unread badges

    Args:
        user_email: User's email address
        hours: Optional filter for recent activity window
        include_hidden: Whether to include hidden notifications
        exclude_own_jobs: Whether to exclude user's own job notifications (admin filter)

    Returns:
        List of sender activity summaries with counts
    """
    try:
        # Look up user to get UUID
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data["id"] ) if isinstance( user_data["id"], str ) else user_data["id"]

        # Build exclude_job_ids list if "not mine" filter is active
        exclude_job_ids = None
        if exclude_own_jobs:
            from cosa.rest.queue_extensions import user_job_tracker
            user_uid = user_data.get( "uid", "" )
            exclude_job_ids = user_job_tracker.get_jobs_for_user( user_uid )

        with get_db() as session:
            repo = NotificationRepository( session )
            activities = repo.get_sender_last_activities_visible(
                recipient_id   = user_id,
                include_hidden = include_hidden,
                exclude_job_ids = exclude_job_ids
            )

            # Apply hours filter if specified
            if hours is not None:
                cutoff = datetime.now( timezone.utc ) - timedelta( hours=hours )
                activities = [
                    a for a in activities
                    if a["last_activity"] >= cutoff
                ]

            # Convert datetime to ISO string for JSON serialization, and stamp
            # the per-session voice persona on each sender so the UI can render
            # the persona badge on first paint after a force-refresh — without
            # this, senderPersonaMap is empty until the first live notification
            # arrives, and the card renders without a badge.
            # See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md §10 (Layer B)
            for activity in activities:
                if activity["last_activity"]:
                    activity["last_activity"] = activity["last_activity"].isoformat()
                activity["voice_persona"]   = _voice_persona_for_sender_id( activity.get( "sender_id" ) )
                activity["manager_persona"] = _manager_persona_for_sender_id( activity.get( "sender_id" ) )

            filter_label = " (excluding own jobs)" if exclude_own_jobs else ""
            print( f"[NOTIFY] Returning {len( activities )} visible senders for {user_email}{filter_label}" )

            return activities

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting visible senders for {user_email}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get visible sender list: {str( e )}"
        )


@router.get(
    "/notifications/active-conversation/{user_email}",
    summary     = "Get active conversation",
    description = "Return the sender_id of the most recent notification for voice response routing."
)
async def get_active_conversation(
    user_email: str
):
    """
    Get the currently active conversation (most recent sender) for a user.

    Used for voice response routing - responses go to the most recent sender.
    Supports new session-aware sender_id format: claude.code@project.deepily.ai#session_id

    Requires:
        - user_email is a valid registered email address
        - User exists in auth database

    Ensures:
        - Returns the sender_id of the most recent notification
        - Returns null if no notifications exist

    Args:
        user_email: User's email address

    Returns:
        JSON with active_sender_id and user_email
    """
    try:
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data[ "id" ] ) if isinstance( user_data[ "id" ], str ) else user_data[ "id" ]

        with get_db() as session:
            repo = NotificationRepository( session )
            active_sender = repo.get_active_conversation( user_id )

            print( f"[NOTIFY] Active conversation for {user_email}: {active_sender}" )

            return {
                "active_sender_id" : active_sender,
                "user_email"       : user_email
            }

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting active conversation: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get active conversation: {str( e )}"
        )


@router.get(
    "/notifications/project-sessions/{project}/{user_email}",
    summary     = "List project sessions",
    description = "Return all Claude Code sessions for a project with activity counts and active status."
)
async def get_project_sessions(
    project: str,
    user_email: str
):
    """
    Get all sessions for a project with activity details.

    Returns session-level breakdown for a project, showing which session
    is currently active (most recent across all projects).
    Supports parsing session_id from sender_id format: claude.code@project.deepily.ai#session_id

    Requires:
        - project is a valid project name (e.g., "lupin")
        - user_email is a valid registered email address

    Ensures:
        - Returns list of session summaries with is_active indicator
        - Sessions ordered by last_activity descending
        - is_active is true for globally most recent sender

    Args:
        project: Project name (e.g., "lupin")
        user_email: User's email address

    Returns:
        List of session summaries: [{ session_id, sender_id, last_activity, count, is_active }]
    """
    try:
        from cosa.rest.user_service import get_user_by_email

        user_data = get_user_by_email( user_email )
        if not user_data:
            raise HTTPException(
                status_code = 404,
                detail      = f"User not found: {user_email}"
            )

        user_id = uuid.UUID( user_data[ "id" ] ) if isinstance( user_data[ "id" ], str ) else user_data[ "id" ]

        with get_db() as session:
            repo = NotificationRepository( session )
            sessions = repo.get_sessions_for_project( user_id, project.lower() )

            # Convert datetime to ISO string for JSON serialization
            for sess in sessions:
                if sess[ "last_activity" ]:
                    sess[ "last_activity" ] = sess[ "last_activity" ].isoformat()

            print( f"[NOTIFY] Returning {len( sessions )} sessions for {project} → {user_email}" )

            return sessions

    except HTTPException:
        raise
    except Exception as e:
        print( f"[NOTIFY] Error getting project sessions: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get project sessions: {str( e )}"
        )


# =============================================================================
# GIST GENERATION ENDPOINT (Session 57 - Semantic Session Names)
# =============================================================================

@router.post(
    "/notifications/generate-gist",
    summary     = "Generate session gist",
    description = "Use LLM to generate a concise semantic session name from notification messages."
)
async def generate_session_gist(
    request_body: Dict[ str, Any ] = Body( ..., description="Request body with messages and abstracts lists" )
):
    """
    Generate a 3-4 word gist from conversation messages and abstracts.

    Uses the Gister class (LLM-powered) to extract a concise summary
    from session notifications for semantic session naming. Abstracts
    are prioritized as they contain richer semantic signal (plan details,
    technical context, URLs).

    Requires:
        - messages and/or abstracts are lists of strings
        - At least one message or abstract with content

    Ensures:
        - Returns {"gist": "short summary"} with 3-4 words
        - Prioritizes abstracts (first 5) then messages (next 5) for 10 total
        - Returns "Empty session" for empty inputs

    Raises:
        - HTTPException with 500 for gist generation failures

    Args:
        request_body: Dict containing "messages" and optional "abstracts" lists

    Returns:
        dict: {"gist": "short summary"}
    """
    from cosa.memory.gister import Gister

    try:
        messages  = request_body.get( "messages", [] )
        abstracts = request_body.get( "abstracts", [] )

        if not messages and not abstracts:
            return { "gist": "Empty session" }

        # Combine: prioritize abstracts (stronger signal) then messages
        # Take first 5 abstracts (rich context) + first 5 messages (breadth)
        combined_parts = []
        combined_parts.extend( abstracts[ :5 ] )
        combined_parts.extend( messages[ :5 ] )

        combined = " ".join( combined_parts )

        if not combined.strip():
            return { "gist": "Empty session" }

        print( f"[NOTIFY] Generating session title from {len( messages )} messages + {len( abstracts )} abstracts ({len( combined )} chars)" )
        print( f"[NOTIFY] Combined text preview: {combined[ :200 ]}..." )

        # Use Gister with session title prompt (cache bypassed for this prompt type)
        # The prompt enforces 3-5 words, so no truncation needed
        # FM-7 event-loop offload: get_gist() does a LanceDB cache read +
        # (on miss) a blocking LLM HTTP call; run it OFF the event loop so the
        # gist path (and /health) can't stall under LLM latency.
        gister = Gister( debug=True )
        title = await asyncio.to_thread( gister.get_gist, combined, prompt_key="prompt template for session title" )

        print( f"[NOTIFY] Generated session title: '{title}'" )

        return { "gist": title }

    except Exception as e:
        print( f"[NOTIFY] Error generating gist: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to generate gist: {str( e )}"
        )


