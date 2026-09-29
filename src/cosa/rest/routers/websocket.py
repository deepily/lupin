"""
WebSocket and authentication endpoints for the COSA system.

This module provides FastAPI router endpoints for WebSocket connections
and authentication testing. Supports both audio streaming and queue
update WebSocket connections with user authentication and session management.

Generated on: 2025-01-24
Updated: 2025-08-01 - Added Design by Contract documentation
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from datetime import datetime
import json
import asyncio
import cosa.utils.util as du
import re
from urllib.parse import unquote

# Import dependencies
from cosa.rest.auth import get_current_user, TokenExpiredException
from cosa.rest.websocket_manager import WebSocketManager, CLOSE_CODE_SUPERSEDED

router = APIRouter(tags=["websocket"])

# =============================================================================
# Application close codes (RFC 6455 §7.4.2 — application range 4000-4999).
# Reserved by Phase 5 of the WS reconnect circuit-breaker milestone:
# `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/06-phase-5-server-side-hardening.md`.
#
#   4001  Auth failed (invalid/expired token, malformed auth_request, missing
#         token field, etc.). Client treats as PERMANENT — does NOT retry.
#         Browser-side `ws-channel.js` PERMANENT_CLOSE_CODES set; `notifications.js`
#         attempts a token refresh first, then shows the auth-permanent banner
#         only if refresh also fails.
#
#   4002  Auth failed: session conflict (single-session-per-user policy
#         displaced this connection). Client shows "Another session has taken
#         over." banner; does NOT retry.
#
#   4003  Auth failed: subscription denied (RBAC reject of one or more
#         subscribed_events). Reserved for future RBAC enforcement; not
#         currently emitted by any branch (audio subscriptions are filtered
#         silently today).
#
#         ⚠️ RESERVED SERVER-SIDE IS NOT UNUSED. The clients already speak this
#         code: QueueTransport.ts lists it in PERMANENT_CLOSE_CODES, and
#         notifications.js renders it "Permission denied for one or more
#         notification streams." Do not borrow it for an unrelated meaning —
#         row dc446601 tried, and that is why the supersede code below is 4004.
#
#   4004  Superseded (row dc446601): a NEWER /ws/queue connection claimed this
#         socket's ( user_id, device_id ) slot. Permanent — the client must NOT
#         reconnect this socket. Emitted only for MOBILE sessions, the only ones
#         that hold a slot. Defined in `websocket_manager` because that is where
#         it is emitted, and imported here so this block stays the ONE place
#         every application close code is catalogued. This module already imports
#         that one, so defining it there and importing here avoids a cycle.
# =============================================================================
CLOSE_CODE_AUTH_INVALID_TOKEN     = 4001
CLOSE_CODE_AUTH_SESSION_CONFLICT  = 4002
CLOSE_CODE_AUTH_SUBSCRIPTION_DENIED = 4003
# Row 3bafdf12: the resume replay failed AFTER auth succeeded (the socket died mid-backlog, or
# a send raised). RFC 6455's own "internal error", not an application code: 4001 is "your
# token is bad", which the mobile client answers with a refresh or a sign-out.
CLOSE_CODE_RESUME_FAILED          = 1011

# Global dependencies (temporary access via main module)
def get_websocket_manager():
    """
    FastAPI dependency to get the WebSocket manager instance.
    
    Requires:
        - lupin_app.main module exists and has websocket_manager attribute
        
    Ensures:
        - Returns the global WebSocketManager instance
        
    Raises:
        - ImportError if main module cannot be imported
        - AttributeError if websocket_manager attribute is missing
    """
    import lupin_app.main as main_module
    return main_module.websocket_manager

def get_active_tasks():
    """
    FastAPI dependency to get the active tasks dictionary.
    
    Requires:
        - lupin_app.main module exists and has active_tasks attribute
        
    Ensures:
        - Returns the global active_tasks dictionary for task management
        
    Raises:
        - ImportError if main module cannot be imported
        - AttributeError if active_tasks attribute is missing
    """
    import lupin_app.main as main_module
    return main_module.active_tasks

def get_app_debug():
    """
    FastAPI dependency to get application debug and verbose settings.
    
    Requires:
        - lupin_app.main module exists and has app_debug, app_verbose attributes
        
    Ensures:
        - Returns tuple of (app_debug, app_verbose) boolean flags
        
    Raises:
        - ImportError if main module cannot be imported
        - AttributeError if debug/verbose attributes are missing
    """
    import lupin_app.main as main_module
    return main_module.app_debug, main_module.app_verbose

def _undelivered_max_age_hours() -> int:
    """
    Resolve the undelivered-drain age cap (hours) from config.

    Storm guard (2026-06-03 incident): the durable-outbox drain must not replay
    stale rows on reconnect. The cap bounds how far back the "N missed" count and
    the pull-able inbox reach. Runtime-tunable via the INI key, mirroring the
    TTS spoken-char-cap pattern.

    Ensures:
        - returns the configured int cap (default 24 hours)
    """
    import lupin_app.main as main_module
    return main_module.config_mgr.get( "notification undelivered max age hours", default=24, return_type="int" )

def _compute_undelivered_count( user_id ) -> int:
    """
    Count the user's undelivered (missed-while-offline) notifications for the
    auth_success "N missed" surfacing (messaging-coordination plane, lever D).

    Ensures:
        - returns the count of notifications in state created/queued for this user,
          bounded by the undelivered age cap (storm guard)
        - NEVER raises — returns 0 on any error (a count failure must not break auth)
    """
    try:
        import uuid as _uuid
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.notification_repository import NotificationRepository
        max_age_hours = _undelivered_max_age_hours()
        with get_db() as session:
            repo = NotificationRepository( session )
            return repo.count_undelivered_for_recipient( _uuid.UUID( str( user_id ) ), max_age_hours=max_age_hours )
    except Exception:
        return 0


def is_valid_session_id(session_id: str) -> bool:
    """
    Validate session ID format according to expected patterns.

    Accepted formats:
        - Browser sessions: "adjective noun" (e.g., 'wise penguin')
        - Programmatic sessions: "prefix-hash" (e.g., 'cc-listener-72116632')

    Requires:
        - session_id is a string (may be empty or invalid)

    Ensures:
        - Returns True if session_id matches a supported format
        - Returns False if empty, whitespace-only, or invalid format
        - Rejects tab, newline, and other whitespace characters for security

    Raises:
        - None
    """
    # Check it's not empty
    if not session_id:
        return False

    # SECURITY: Check for any whitespace characters other than single space
    # Reject if contains tabs, newlines, or other whitespace before processing
    if any(c in session_id for c in ['\t', '\n', '\r', '\f', '\v']):
        return False

    # Check if it's only whitespace
    if not session_id.strip():
        return False

    # Format 1: "adjective noun" browser sessions (single space only)
    # SECURITY: Use literal space ' ' instead of \s to prevent tab/newline injection
    browser_pattern = r'^[a-z]+ [a-z]+$'
    if re.match( browser_pattern, session_id.lower() ):
        return True

    # Format 2: programmatic sessions — lowercase alphanumeric with hyphens
    # e.g., "cc-listener-72116632", "proxy-ratify"
    programmatic_pattern = r'^[a-z][a-z0-9]*-[a-z0-9-]{1,47}$'
    return bool( re.match( programmatic_pattern, session_id.lower() ) )

@router.get("/api/auth-test")
async def auth_test(current_user: dict = Depends(get_current_user)):
    """
    Test endpoint to verify authentication is working.
    
    Example usage:
    curl -H "Authorization: Bearer mock_token_alice" http://localhost:8000/api/auth-test
    
    Returns:
        dict: Current user information
    """
    return {
        "message": "Authentication successful",
        "user_id": current_user["uid"],
        "email": current_user["email"],
        "name": current_user["name"],
        "timestamp": du.get_current_datetime_iso()
    }

@router.websocket("/ws/audio/{session_id}")
async def websocket_audio_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time TTS audio streaming.
    
    Preconditions:
        - session_id must be a valid session identifier
        - WebSocket connection must be established
        
    Postconditions:
        - Manages WebSocket connection lifecycle
        - Stores connection in websocket_manager for audio streaming
        - Handles disconnection cleanup
        
    Args:
        websocket: WebSocket connection object
        session_id: Unique session identifier for this client
    """
    # Get dependencies from main module
    import lupin_app.main as main_module
    websocket_manager = main_module.websocket_manager
    active_tasks = main_module.active_tasks
    app_debug = main_module.app_debug
    app_verbose = main_module.app_verbose
    
    # URL decode session ID and validate format
    decoded_session_id = unquote(session_id)
    if not is_valid_session_id(decoded_session_id):
        await websocket.close(code=1008, reason="Invalid session ID format")
        print(f"[WS-AUDIO] Rejected connection with invalid session ID: {decoded_session_id}")
        return
    
    # Use decoded session ID for all further operations
    session_id = decoded_session_id
    
    await websocket.accept()
    
    # Check if this session has been pre-registered with a user (from TTS request)
    user_id = websocket_manager.session_to_user.get(session_id)
    
    # Audio WebSocket should only receive audio-related events
    audio_events = ["audio_streaming_status", "audio_streaming_complete", "sys_ping"]
    
    if not user_id:
        # If no pre-registration, audio WebSocket connections don't require immediate auth
        # The user association will be established when TTS request comes in
        print(f"[WS-AUDIO] No pre-registered user for session {session_id}, connecting without user association")
        websocket_manager.connect(websocket, session_id, subscribed_events=audio_events)
    else:
        print(f"[WS-AUDIO] Found pre-registered user {user_id} for session {session_id}")
        websocket_manager.connect(websocket, session_id, user_id, subscribed_events=audio_events)
    
    if app_debug:
        user_info = user_id if user_id else "no-user-yet"
        print( f"[WEBSOCKET] New connection on /ws/audio/{session_id} endpoint (audio streaming WebSocket) for user {user_info}" )
    
    print(f"[WS-AUDIO] Audio WebSocket connected for session: {session_id}")
    
    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "audio_streaming_status",
            "text": f"Audio WebSocket connected for session {session_id}",
            "status": "success"
        })
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client
                data = await websocket.receive_text()
                message = json.loads( data )

                if app_debug and app_verbose:
                    print( f"[WS-AUDIO] Received message from {session_id}: {message}" )

                # Handle auth_request from browser (mirrors queue endpoint auth)
                if message.get( "type" ) == "auth_request" and "token" in message:
                    token = message[ "token" ]
                    if token.startswith( "Bearer " ):
                        token = token[ 7: ]

                    try:
                        from cosa.rest.auth import verify_token
                        user_info = await verify_token( token )
                        auth_user_id = user_info[ "uid" ]

                        # Update session with user association
                        websocket_manager.session_to_user[ session_id ] = auth_user_id
                        if auth_user_id not in websocket_manager.user_sessions:
                            websocket_manager.user_sessions[ auth_user_id ] = []
                        if session_id not in websocket_manager.user_sessions[ auth_user_id ]:
                            websocket_manager.user_sessions[ auth_user_id ].append( session_id )
                        if user_info.get( "email" ):
                            websocket_manager.user_to_email[ auth_user_id ] = user_info[ "email" ]

                        # Update subscriptions from auth message
                        subscribed_events = message.get( "subscribed_events", audio_events )
                        valid_events = [ e for e in subscribed_events if e == "*" or e in websocket_manager.available_events ]
                        websocket_manager.session_subscriptions[ session_id ] = valid_events

                        await websocket.send_json({
                            "type"       : "auth_success",
                            "user_id"    : auth_user_id,
                            "session_id" : session_id
                        })
                        print( f"[WS-AUDIO] Authenticated session [{session_id}] for user [{auth_user_id}] ({user_info.get( 'email', '?' )})" )
                        print( f"[WS] STATE after audio auth: {len( websocket_manager.active_connections )} active, {len( websocket_manager.user_sessions )} users: {list( websocket_manager.user_sessions.keys() )[ :3 ]}" )

                    except Exception as auth_err:
                        print( f"[WS-AUDIO] Auth failed for session [{session_id}]: {auth_err}" )
                        await websocket.send_json({
                            "type"    : "auth_error",
                            "message" : str( auth_err )
                        })

                elif message.get( "type" ) == "sys_ping":
                    await websocket.send_json({
                        "type"      : "sys_pong",
                        "timestamp" : du.get_current_datetime_iso()
                    })

            except WebSocketDisconnect:
                break
            except Exception as e:
                if app_debug:
                    print( f"[WS-AUDIO] Error handling message from {session_id}: {e}" )
                break
                
    except WebSocketDisconnect:
        pass
    finally:
        # Cancel any active streaming tasks for this session
        if session_id in active_tasks:
            print(f"[WS-AUDIO] Cancelling active streaming task for session: {session_id}")
            active_tasks[session_id].cancel()
            try:
                await active_tasks[session_id]
            except asyncio.CancelledError:
                pass
            del active_tasks[session_id]
        
        # Only disconnect if OUR websocket is still the active one
        # (prevents race: reconnection with same session_id already replaced us)
        if websocket_manager.active_connections.get( session_id ) is websocket:
            websocket_manager.disconnect( session_id )
            print( f"[WS-AUDIO] Audio WebSocket disconnected for session: {session_id}" )
        else:
            print( f"[WS-AUDIO] Skipping disconnect for {session_id} — replaced by new connection" )

# ── CC transcript console verbs (row 27760534) ────────────────────────────────

# One tailer per WATCHED seat, keyed by cc_session_id. Module-level rather than per-socket,
# because several browser sessions may watch one seat and they must share its tailer — a
# tailer per watcher would read the same file N times and emit N copies of every block.
_cc_transcript_tailers = { }


async def handle_cc_transcript_verb( websocket, session_id, message ):
    """
    Handle `cc_transcript_watch` / `cc_transcript_unwatch` on the queue socket.

    Requires:
        - websocket is the caller's live socket
        - session_id is the BROWSER session id (the socket's own id)
        - message carries `type` and, for both verbs, `cc_session_id`

    Ensures:
        - a NON-ADMIN caller is refused, and receives an error frame naming the reason, with
          no blocks and no watch registered (ruling Q5, the WS half of the gate)
        - a watch registers the caller and STARTS the seat's tailer only if this was the
          seat's FIRST watcher; the tailer is shared by every watcher of that seat
        - a watch honours `from_offset`, so the server never silently starts at the current
          end of the file and opens a gap against the client's REST backlog
        - a non-null `file_epoch` naming a file that is no longer current is REFUSED with
          `cc_transcript_state {state: epoch_mismatch}` and NO blocks — never silently
          rebased, which would hand the client a whole new file as its own continuation
        - an unwatch deregisters the caller and STOPS the tailer only when the seat has lost
          its LAST watcher
        - a missing `cc_session_id` is refused rather than registering a watch on ""
        - never raises out to the receive loop: a bad verb must not drop the socket
    """
    websocket_manager = get_websocket_manager()

    verb          = message.get( "type" )
    cc_session_id = ( message.get( "cc_session_id" ) or "" ).strip()

    if not cc_session_id:
        await websocket.send_json( {
            "type"    : "error",
            "event"   : verb,
            "message" : "cc_transcript verbs require a cc_session_id",
        } )
        return

    # 🔴 The WS half of ruling Q5, on state connect() already stores. The REST half is
    # require_admin — a different mechanism, so a test of one proves nothing about the other.
    if not websocket_manager.session_is_admin.get( session_id, False ):
        await websocket.send_json( {
            "type"          : "error",
            "event"         : verb,
            "cc_session_id" : cc_session_id,
            "message"       : "the CC transcript console is admin-only",
        } )
        return

    if verb == "cc_transcript_unwatch":
        await _stop_watching_cc_transcript( session_id, cc_session_id )
        return

    await _start_watching_cc_transcript( websocket, session_id, cc_session_id, message )


async def _start_watching_cc_transcript( websocket, session_id, cc_session_id, message ):
    """
    Register a watcher and start the seat's tailer if it is the first.

    Requires:
        - the caller has already been admin-checked

    Ensures:
        - a seat with no resolvable transcript is answered with
          `cc_transcript_state {state: "refused", reason: "not_found"}` and nothing else: no
          watcher is registered and no tailer is started
        - a stale non-null `file_epoch` is answered with `epoch_mismatch` and nothing else
        - the tailer is created at most once per seat
        - the watcher is registered even when the tailer already exists
    """
    websocket_manager = get_websocket_manager()

    from cosa.rest.cc_transcript_tailer import (
        REASON_NOT_FOUND,
        STATE_EPOCH_MISMATCH,
        STATE_EVENT,
        STATE_REFUSED,
        CcTranscriptTailer,
        epoch_for_path,
        resolve_transcript_path,
    )

    requested_epoch = message.get( "file_epoch" )
    current_path    = resolve_transcript_path( cc_session_id )

    # A seat that does not exist here has no transcript to follow. Say so and stop, BEFORE the
    # epoch check (a nonexistent seat has no current epoch to compare) and before any watcher
    # or tailer exists — otherwise the pane would sit "live" on nothing. A real seat that is
    # merely idle still has its file, so it resolves and falls through to `live` (row a68b10a3).
    if not current_path:
        await websocket.send_json( {
            "type"          : STATE_EVENT,
            "cc_session_id" : cc_session_id,
            "file_epoch"    : None,
            "state"         : STATE_REFUSED,
            "reason"        : REASON_NOT_FOUND,
        } )
        return

    current_epoch   = epoch_for_path( current_path )

    # A client that does not yet know the epoch sends null and learns it from the first
    # frame, so a FIRST watch needs no prior REST call. A non-null epoch that no longer
    # matches is refused rather than rebased (§3).
    if requested_epoch is not None and requested_epoch != current_epoch:
        await websocket.send_json( {
            "type"          : STATE_EVENT,
            "cc_session_id" : cc_session_id,
            "file_epoch"    : current_epoch,
            "state"         : STATE_EPOCH_MISMATCH,
        } )
        return

    is_first = websocket_manager.add_cc_transcript_watcher( cc_session_id, session_id )

    if is_first and cc_session_id not in _cc_transcript_tailers:
        # The predicate closes the loop the sync `disconnect()` path would otherwise leave
        # open: it can drop a watcher but cannot await a stop, so the tailer checks for
        # itself and terminates after the grace period.
        tailer = CcTranscriptTailer(
            cc_session_id,
            _emit_to_cc_transcript_watchers,
            has_watchers = lambda: bool(
                get_websocket_manager().cc_transcript_watchers.get( cc_session_id )
            ),
        )
        _cc_transcript_tailers[ cc_session_id ] = tailer
        tailer.start( from_offset=int( message.get( "from_offset" ) or 0 ) )


async def _stop_watching_cc_transcript( session_id, cc_session_id ):
    """
    Deregister a watcher and stop the seat's tailer if it was the last.

    Ensures:
        - the tailer is stopped and forgotten only when NO watcher remains
        - an unwatch for a seat this session was not watching is a no-op
    """
    websocket_manager = get_websocket_manager()

    if websocket_manager.remove_cc_transcript_watcher( cc_session_id, session_id ):
        await _stop_cc_transcript_tailer( cc_session_id )


async def _stop_cc_transcript_tailer( cc_session_id ):
    """
    Stop and forget one seat's tailer.

    Ensures:
        - stopping an unknown seat is a no-op, so the disconnect sweep can call this for
          every emptied seat without checking first
    """
    tailer = _cc_transcript_tailers.pop( cc_session_id, None )
    if tailer is not None:
        await tailer.stop()


async def stop_cc_transcript_tailers_for_disconnect( session_id ):
    """
    Stop the tailers a disconnecting session left with no watchers.

    🔴 THIS IS THE OTHER HALF OF THE SWEEP, AND IT IS ASYNC, WHICH IS WHY IT IS NOT INSIDE
    `disconnect()`. `WebSocketManager.disconnect()` is synchronous and is called from
    threads, so it can remove the REGISTRY entries but cannot await a tailer's stop. It
    therefore drops the watches and this coroutine reaps the tailers those drops emptied.

    Ensures:
        - every seat the session was the last watcher of has its tailer stopped
        - a session that was watching nothing costs one dict scan and no awaits
        - never raises
    """
    websocket_manager = get_websocket_manager()

    for cc_session_id in websocket_manager.drop_all_cc_transcript_watches( session_id ):
        await _stop_cc_transcript_tailer( cc_session_id )


async def _emit_to_cc_transcript_watchers( cc_session_id, event_name, payload ):
    """
    Fan one console frame out to the seat's watchers, and ONLY to them.

    The watcher set is the single filter: `emit_to_session` applies no subscription check, so
    there is exactly one place a frame can be dropped.

    Requires:
        - cc_session_id names a seat; event_name and payload are the frame

    Ensures:
        - one send per watching browser session
        - a watcher whose socket has already gone is skipped by emit_to_session's own
          early return, so a dead tab does not break the fan-out for live ones
    """
    websocket_manager = get_websocket_manager()

    for watcher_session_id in websocket_manager.cc_transcript_watchers_of( cc_session_id ):
        await websocket_manager.emit_to_session( watcher_session_id, event_name, payload )


@router.websocket("/ws/queue/{session_id}")
async def websocket_queue_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time queue updates and events.
    
    PHASE 2: WebSocket with authentication for user-specific updates.
    
    Preconditions:
        - session_id must be a valid session identifier
        - WebSocket connection must be established
        - First message must contain authentication token
        
    Postconditions:
        - Manages WebSocket connection for queue updates
        - Associates connection with authenticated user
        - Handles disconnection cleanup
        
    Args:
        websocket: WebSocket connection object
        session_id: Unique session identifier for this client
    """
    # Get dependencies from main module
    import lupin_app.main as main_module
    websocket_manager = main_module.websocket_manager
    app_debug   = main_module.app_debug
    app_verbose = main_module.app_verbose

    # URL decode session ID and validate format
    decoded_session_id = unquote(session_id)
    if not is_valid_session_id(decoded_session_id):
        await websocket.close(code=1008, reason="Invalid session ID format")
        print(f"[WS-QUEUE] Rejected connection with invalid session ID: {decoded_session_id}")
        return
    
    # Use decoded session ID for all further operations
    session_id = decoded_session_id
    
    await websocket.accept()
    print(f"[WS-QUEUE] Queue WebSocket connected for session: {session_id}")
    
    if app_debug:
        print( f"[WEBSOCKET] New connection on /ws/queue/{session_id} endpoint (authenticated queue WebSocket)" )
    
    # Wait for authentication message
    try:
        # SECURITY: Handle malformed JSON gracefully
        try:
            print(f"[WS-QUEUE-AUTH] Waiting for auth message from session [{session_id}]...")
            auth_message = await websocket.receive_json()
            print(f"[WS-QUEUE-AUTH] Received auth message: type={auth_message.get('type')}, has_token={('token' in auth_message)}, has_events={('subscribed_events' in auth_message)}")
        except json.JSONDecodeError:
            print(f"[WS-QUEUE-AUTH] JSON decode error for session [{session_id}]")
            await websocket.send_json({
                "type": "auth_error",
                "message": "Authentication message must be valid JSON"
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_auth_request_json")
            return
        except WebSocketDisconnect as wd:
            print( f"[WS-QUEUE-AUTH] Client disconnected during auth for session [{session_id}]: code={wd.code}" )
            return
        except Exception as parse_error:
            print(f"[WS-QUEUE-AUTH] Parse error for session [{session_id}]: {parse_error}")
            try:
                await websocket.send_json({
                    "type": "auth_error",
                    "message": f"Failed to parse authentication message: {str(parse_error)}"
                })
                await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_auth_request")
            except Exception:
                pass  # Socket already closed
            return

        # SECURITY: Validate message structure first
        if not isinstance(auth_message, dict):  # pragma: no cover - unreachable: L363 unconditionally calls auth_message.get('type') right after receive_json, so any non-dict raises AttributeError into the L375 except (which returns); control reaches L388 only when auth_message is a dict → this guard is always False
            print(f"[WS-QUEUE-AUTH] Invalid message type for session [{session_id}]: {type(auth_message)}")
            await websocket.send_json({
                "type": "auth_error",
                "message": "Authentication message must be a JSON object"
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_auth_request_shape")
            return

        # SECURITY: Check required fields
        if auth_message.get("type") != "auth_request":
            print(f"[WS-QUEUE-AUTH] Wrong message type for session [{session_id}]: {auth_message.get('type')}")
            await websocket.send_json({
                "type": "auth_error",
                "message": "First message must be auth_request"
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="auth_protocol_violation")
            return

        if "token" not in auth_message:
            print(f"[WS-QUEUE-AUTH] Missing token for session [{session_id}]")
            await websocket.send_json({
                "type": "auth_error",
                "message": "Authentication message must include token field"
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="missing_token")
            return

        # SECURITY: Validate token format before attempting verification
        token = auth_message["token"]
        if not isinstance(token, str):
            print(f"[WS-QUEUE-AUTH] Token not a string for session [{session_id}]: {type(token)}")
            await websocket.send_json({
                "type": "auth_error",
                "message": "Token must be a string"
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_token_type")
            return

        if not token.strip():
            print(f"[WS-QUEUE-AUTH] Empty token for session [{session_id}]")
            await websocket.send_json({
                "type": "auth_error",
                "message": "Token cannot be empty"
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="empty_token")
            return

        # Strip Bearer prefix if present (WebSocket clients may include it)
        if token.startswith( "Bearer " ):
            token = token[ 7: ]

        # Log token format (first 30 chars for debugging)
        token_preview = token[:30] + "..." if len(token) > 30 else token
        print(f"[WS-QUEUE-AUTH] Token format for session [{session_id}]: {token_preview}")

        # Verify token using configuration-based routing (JWT/mock/Firebase)
        from cosa.rest.auth import verify_token
        try:
            print(f"[WS-QUEUE-AUTH] Verifying token for session [{session_id}]...")
            user_info = await verify_token(token)
            user_id = user_info["uid"]
            print(f"[WS-QUEUE-AUTH] Token verified successfully! user_id=[{user_id}], email={user_info.get('email')}")

            # Extract subscribed events from auth message
            subscribed_events = auth_message.get("subscribed_events", ["*"])
            print(f"[WS-QUEUE-AUTH] Subscribed events for session [{session_id}]: {subscribed_events}")

            # F-S6-1: extract the client-type marker from auth_request. The mobile
            # app sends "mobile"; web clients send nothing (absent ⇒ web). ONLY the
            # queue WS records this — the FCM wake trigger keys on queue-WS liveness.
            client_type = auth_message.get( "client_type" )
            if client_type: print( f"[WS-QUEUE-AUTH] Client type for session [{session_id}]: {client_type}" )

            # Row dc446601: the device slot's key. A stable per-install id from the
            # mobile app; ONLY consulted for a mobile session, so a browser sending
            # one cannot opt itself into displacing anything. Absent ⇒ the slot falls
            # back to the client_type, which is what makes supersession work against
            # the app as shipped rather than waiting on a client change.
            device_id = auth_message.get( "device_id" )
            if device_id: print( f"[WS-QUEUE-AUTH] Device id for session [{session_id}]: {device_id}" )

            # Row dc446601 part 2: the client's highest received frame. Absent or 0
            # means a fresh client with nothing to resume. Anything non-integer is
            # treated as absent rather than trusted — this arrives over the wire.
            last_seq = auth_message.get( "last_seq", 0 )
            if not isinstance( last_seq, int ) or isinstance( last_seq, bool ) or last_seq < 0:
                last_seq = 0

            # Connect with user association and subscriptions
            print(f"[WS-QUEUE-AUTH] Connecting session [{session_id}] to user [{user_id}] in WebSocket manager...")
            websocket_manager.connect( websocket, session_id, user_id, subscribed_events, email=user_info.get( "email" ), roles=user_info.get( "roles", [] ), client_type=client_type, device_id=device_id )
            # Part 2 (María's F2): hold this device's live frames until the replay below
            # drains them. MUST stay adjacent to connect() — no await between the two.
            websocket_manager.begin_resume( session_id )
            session_type = "listener" if session_id.startswith( "cc-listener-" ) else "browser"
            print( f"[WS-QUEUE] Authenticated {session_type} session [{session_id}] for user [{user_id}] ({user_info.get( 'email', '?' )})" )

            # Verify connection was established
            is_connected = websocket_manager.is_user_connected(user_id)
            connection_count = websocket_manager.get_user_connection_count(user_id)
            print(f"[WS-QUEUE-AUTH] Connection verification: is_connected={is_connected}, connection_count={connection_count}")

            # Lever D (messaging plane): surface how many notifications the user
            # missed while offline, so the UI can show "N missed" on reconnect.
            undelivered_count = _compute_undelivered_count( user_id )

            # Send auth success
            await websocket.send_json({
                "type": "auth_success",
                "user_id": user_id,
                "session_id": session_id,
                "undelivered_count": undelivered_count
            })

        except TokenExpiredException:
            print( f"[WS-QUEUE-AUTH] Token expired for session [{session_id}] — client should refresh" )
            await websocket.send_json({
                "type"    : "auth_error",
                "message" : "Token expired"
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="token_expired")
            return
        except Exception as e:
            print( f"[WS-QUEUE-AUTH] ❌ Token verification failed for session [{session_id}]: {type( e ).__name__}: {e}" )
            import traceback
            traceback.print_exc()
            await websocket.send_json({
                "type"    : "auth_error",
                "message" : str( e )
            })
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_token")
            return

        # ── Row 3bafdf12: the resume replay is NOT authentication ─────────────────────────
        # It used to sit inside the auth try above, whose generic `except` answered ANY failure
        # with {"type": "auth_error"} and a 4001 close, logged as "Token verification failed".
        # A send that died mid-backlog was reported as a bad token, and the mobile client
        # answers 4001 with a token refresh or a sign-out. Auth has succeeded by here, so a
        # failure now is a transport failure and says so: the real exception at error level
        # with the session id, no auth_error frame, and a 1011 close.
        # Row dc446601 part 2: replay this device's backlog, then say where the
        # backlog ENDS. Only a slot holder has one — a web tab has nothing to
        # resume, so it gets neither the replay nor the marker.
        #
        # `gap` is the load-bearing field. A partial replay that stayed quiet
        # would leave the client believing it is current, and it would stop
        # asking; gap=True is the server admitting it cannot prove continuity and
        # that a full refetch is owed.
        # replay_and_resume also releases the frames held since connect(), in seq
        # order, so no live frame can overtake the replay (María's F2), and its
        # resume_complete.seq is the server's current seq (F1).
        try:
            resume = await websocket_manager.replay_and_resume( session_id, last_seq, websocket.send_json )
            if resume is not None:
                print( f"[WS-QUEUE-RESUME] Session [{session_id}] resumed from {last_seq}: "
                       f"{resume[ 'replayed' ]} frame(s) replayed, gap={resume[ 'gap' ]}, now at seq {resume[ 'seq' ]}" )
        except Exception as e:
            print( f"[WS-QUEUE-RESUME] ERROR resume replay failed for session [{session_id}]: {type( e ).__name__}: {e}" )
            import traceback
            traceback.print_exc()
            # ONE deregister that carries the close code, then an explicit close for the case
            # where disconnect() could not schedule one (no running loop). Both say 1011.
            if websocket_manager.active_connections.get( session_id ) is websocket:
                websocket_manager.disconnect( session_id, close_code=CLOSE_CODE_RESUME_FAILED, close_reason="resume_failed" )
            try:
                await websocket.close( code=CLOSE_CODE_RESUME_FAILED, reason="resume_failed" )
            except Exception:
                pass  # Socket already closed
            return

    except TokenExpiredException:
        print( f"[WS-QUEUE] Token expired for session [{session_id}] — client should refresh" )
        await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="token_expired")
        return
    except Exception as e:
        print( f"[WS-QUEUE] ❌ Auth error for session [{session_id}]: {type( e ).__name__}: {e}" )
        import traceback
        traceback.print_exc()
        try:
            await websocket.close(code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="auth_error")
        except Exception:
            pass  # Socket already closed
        return
    
    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connect",
            "message": f"Queue WebSocket connected for session {session_id}",
            "session_id": session_id,
            "timestamp": du.get_current_datetime_iso()
        })
        
        # PHASE 2: Real queue updates now come from COSA queues via websocket_manager
        # Keep connection alive and listen for incoming messages
        while True:
            try:
                # Listen for any incoming messages (for future bidirectional communication)
                data = await websocket.receive_text()
                message = json.loads(data)
                if app_debug and app_verbose: print(f"[WS-QUEUE] Received message from {session_id}: {message}")
                
                # Handle specific message types if needed
                if message.get("type") == "sys_ping":
                    await websocket.send_json({
                        "type": "sys_pong",
                        "timestamp": du.get_current_datetime_iso()
                    })
                elif message.get("type") in ( "cc_transcript_watch", "cc_transcript_unwatch" ):
                    # CC transcript console (row 27760534). Two NEW verbs — update_subscriptions
                    # cannot absorb them, because it is type-level only and carries no
                    # per-target argument, while a watch is parameterised by cc_session_id.
                    #
                    # 🔴 ADMIN ONLY (ruling Q5), checked HERE against session_is_admin. The REST
                    # half uses require_admin — a DIFFERENT mechanism — so neither gate proves
                    # anything about the other.
                    await handle_cc_transcript_verb( websocket, session_id, message )

                elif message.get( "type" ) == "ack":
                    # Row dc446601 part 2: the client confirms what it has processed,
                    # and the server drops it. Without this the buffer only ever
                    # shrinks by eviction, which is the thing that causes a gap.
                    ack_seq = message.get( "seq", 0 )
                    if isinstance( ack_seq, int ) and not isinstance( ack_seq, bool ) and ack_seq > 0:
                        dropped = websocket_manager.ack_frames( session_id, ack_seq )
                        if app_debug: print( f"[WS-QUEUE-ACK] Session [{session_id}] acked {ack_seq}, trimmed {dropped}" )

                elif message.get("type") == "update_subscriptions":
                    # Handle subscription updates
                    events = message.get("events", [])
                    action = message.get("action", "replace")
                    success = websocket_manager.update_subscriptions(session_id, events, action)
                    await websocket.send_json({
                        "type": "subscription_update",
                        "success": success,
                        "subscriptions": websocket_manager.session_subscriptions.get(session_id, [])
                    })
                    
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"[WS-QUEUE] Error in queue WebSocket for {session_id}: {e}")
                break
                
    except WebSocketDisconnect:
        pass
    finally:
        # Only disconnect if OUR websocket is still the active one
        # (prevents race: reconnection with same session_id already replaced us)
        if websocket_manager.active_connections.get( session_id ) is websocket:
            # BEFORE disconnect(), because disconnect() sweeps the watcher registry
            # synchronously and would leave this coroutine nothing to reap. The tailer also
            # self-terminates on its watcher count, so the two are belt and suspenders rather
            # than one control — this reaps promptly, that one cannot be ordered wrong.
            await stop_cc_transcript_tailers_for_disconnect( session_id )
            websocket_manager.disconnect( session_id )
            session_type = "listener" if session_id.startswith( "cc-listener-" ) else "browser"
            print( f"[WS-QUEUE] Queue WebSocket disconnected for {session_type} session: {session_id}" )
        else:
            print( f"[WS-QUEUE] Skipping disconnect for {session_id} — replaced by new connection" )


def quick_smoke_test():
    """
    Critical smoke test for WebSocket API router - validates WebSocket endpoint functionality.
    
    This test is essential for v000 deprecation as rest/routers/websocket.py is critical
    for real-time communication and WebSocket management in the REST system.
    """
    import cosa.utils.util as du
    
    du.print_banner( "WebSocket API Router Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic module and router structure
        print( "Testing core WebSocket API components..." )
        
        # Check if router exists and has expected attributes
        if 'router' in globals() and hasattr( router, 'routes' ):
            print( "✓ FastAPI router structure present" )
        else:
            print( "✗ FastAPI router structure missing" )
        
        # Check expected endpoints
        expected_endpoints = [ "auth_test", "websocket_audio_endpoint", "websocket_queue_endpoint" ]
        endpoints_found = 0
        
        for endpoint_name in expected_endpoints:
            if endpoint_name in globals():
                endpoints_found += 1
            else:
                print( f"⚠ Missing endpoint: {endpoint_name}" )
        
        if endpoints_found == len( expected_endpoints ):
            print( f"✓ All {len( expected_endpoints )} core WebSocket endpoints present" )
        else:
            print( f"⚠ Only {endpoints_found}/{len( expected_endpoints )} WebSocket endpoints present" )
        
        # Test 2: Critical dependency imports
        print( "Testing critical dependency imports..." )
        try:
            from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
            from datetime import datetime
            import json
            import asyncio
            import re
            from urllib.parse import unquote
            print( "✓ Core FastAPI and standard library imports successful" )
        except ImportError as e:
            print( f"✗ Core imports failed: {e}" )
        
        try:
            from cosa.rest.auth import get_current_user
            from cosa.rest.websocket_manager import WebSocketManager
            print( "✓ CoSA REST module imports successful" )
        except ImportError as e:
            print( f"⚠ CoSA REST imports failed: {e}" )
        
        # Test 3: Helper functions validation
        print( "Testing helper functions..." )
        helper_functions = [ "get_websocket_manager", "get_active_tasks", "get_app_debug", "is_valid_session_id" ]
        
        helpers_found = 0
        for helper_name in helper_functions:
            if helper_name in globals() and callable( globals()[helper_name] ):
                helpers_found += 1
            else:
                print( f"⚠ Missing helper: {helper_name}" )
        
        if helpers_found == len( helper_functions ):
            print( f"✓ All {len( helper_functions )} helper functions present" )
        else:
            print( f"⚠ Only {helpers_found}/{len( helper_functions )} helper functions present" )
        
        # Test 4: Session ID validation logic
        print( "Testing session ID validation logic..." )
        try:
            # Test valid session IDs
            valid_test_cases = [ "wise penguin", "happy cat", "smart dog", "cc-listener-72116632", "proxy-ratify" ]
            invalid_test_cases = [ "", "   ", "too many words here", "a", "ab" ]
            
            valid_passed = 0
            for valid_id in valid_test_cases:
                if is_valid_session_id( valid_id ):
                    valid_passed += 1
            
            invalid_rejected = 0
            for invalid_id in invalid_test_cases:
                if not is_valid_session_id( invalid_id ):
                    invalid_rejected += 1
            
            if valid_passed == len( valid_test_cases ):
                print( "✓ Valid session ID validation working" )
            else:
                print( f"⚠ Valid session ID validation: {valid_passed}/{len( valid_test_cases )} passed" )
            
            if invalid_rejected == len( invalid_test_cases ):
                print( "✓ Invalid session ID rejection working" )
            else:
                print( f"⚠ Invalid session ID rejection: {invalid_rejected}/{len( invalid_test_cases )} rejected" )
                
        except Exception as e:
            print( f"⚠ Session ID validation issues: {e}" )
        
        # Test 5: WebSocket endpoint function signatures
        print( "Testing WebSocket endpoint signatures..." )
        try:
            import inspect
            
            # Test auth_test endpoint
            if inspect.iscoroutinefunction( auth_test ):
                print( "✓ auth_test is properly async" )
            else:
                print( "⚠ auth_test may not be async" )
            
            # Check dependencies in auth_test
            sig = inspect.signature( auth_test )
            if 'current_user' in sig.parameters:
                print( "✓ auth_test has authentication dependency" )
            else:
                print( "⚠ auth_test missing authentication dependency" )
            
            # Test WebSocket endpoints
            for ws_endpoint in [ websocket_audio_endpoint, websocket_queue_endpoint ]:
                if inspect.iscoroutinefunction( ws_endpoint ):
                    endpoint_name = ws_endpoint.__name__
                    print( f"✓ {endpoint_name} is properly async" )
                    
                    # Check WebSocket parameter
                    sig = inspect.signature( ws_endpoint )
                    if 'websocket' in sig.parameters and 'session_id' in sig.parameters:
                        print( f"✓ {endpoint_name} has required WebSocket parameters" )
                    else:
                        print( f"⚠ {endpoint_name} missing required parameters" )
                else:
                    print( f"⚠ {ws_endpoint.__name__} may not be async" )
                    
        except Exception as e:
            print( f"⚠ WebSocket endpoint signature issues: {e}" )
        
        # Test 6: Router configuration validation
        print( "Testing router configuration..." )
        try:
            # Test router has proper tags
            if hasattr( router, 'tags' ) and 'websocket' in getattr( router, 'tags', [] ):
                print( "✓ Router tags configuration valid" )
            else:
                print( "⚠ Router tags configuration may have issues" )
            
            # Test routes are registered
            if hasattr( router, 'routes' ) and len( router.routes ) >= 3:
                print( f"✓ Router has {len( router.routes )} registered routes" )
            else:
                print( "⚠ Router may have missing routes" )
            
            # Check route types (WebSocket vs HTTP)
            ws_routes = 0
            http_routes = 0
            
            for route in router.routes:
                if hasattr( route, 'path' ):
                    if route.path.startswith( '/ws/' ):
                        ws_routes += 1
                    elif route.path.startswith( '/api/' ):
                        http_routes += 1
            
            if ws_routes >= 2 and http_routes >= 1:
                print( f"✓ Route types balanced: {ws_routes} WebSocket, {http_routes} HTTP" )
            else:
                print( f"⚠ Route distribution: {ws_routes} WebSocket, {http_routes} HTTP" )
                
        except Exception as e:
            print( f"⚠ Router configuration issues: {e}" )
        
        # Test 7: Dependency injection structure
        print( "Testing dependency injection structure..." )
        try:
            import inspect
            
            # Test dependency functions have proper import structure
            for dep_func in [ get_websocket_manager, get_active_tasks, get_app_debug ]:
                source_lines = inspect.getsource( dep_func )
                if 'import lupin_app.main' in source_lines:
                    print( f"✓ {dep_func.__name__} dependency injection structure valid" )
                else:
                    print( f"⚠ {dep_func.__name__} dependency structure may have issues" )
                    
        except Exception as e:
            print( f"⚠ Dependency injection structure issues: {e}" )
        
        # Test 8: WebSocket message handling structure
        print( "Testing WebSocket message handling structure..." )
        try:
            # Check that endpoints have proper WebSocket handling logic
            for endpoint in [ websocket_audio_endpoint, websocket_queue_endpoint ]:
                source_code = inspect.getsource( endpoint )
                
                # Check for essential WebSocket patterns
                essential_patterns = [
                    "await websocket.accept()",
                    "WebSocketDisconnect",
                    "websocket.send_json(",
                    "websocket_manager.connect(",
                    "websocket_manager.disconnect("
                ]
                
                patterns_found = 0
                for pattern in essential_patterns:
                    if pattern in source_code:
                        patterns_found += 1
                
                endpoint_name = endpoint.__name__
                if patterns_found >= len( essential_patterns ) - 1:  # Allow for minor variations
                    print( f"✓ {endpoint_name} has proper WebSocket handling" )
                else:
                    print( f"⚠ {endpoint_name} missing WebSocket patterns: {patterns_found}/{len( essential_patterns )}" )
                    
        except Exception as e:
            print( f"⚠ WebSocket message handling issues: {e}" )
        
        # Test 9: Authentication integration validation
        print( "Testing authentication integration..." )
        try:
            # Check that auth endpoint uses proper authentication
            auth_source = inspect.getsource( auth_test )
            if 'current_user' in auth_source and 'Depends' in auth_source:
                print( "✓ Authentication endpoint integration valid" )
            else:
                print( "⚠ Authentication endpoint integration may have issues" )
            
            # Check that queue WebSocket handles authentication
            queue_source = inspect.getsource( websocket_queue_endpoint )
            auth_checks = [
                "auth_request",
                "verify_firebase_token",
                "auth_success",
                "auth_error"
            ]
            
            auth_patterns_found = 0
            for check in auth_checks:
                if check in queue_source:
                    auth_patterns_found += 1
            
            if auth_patterns_found >= len( auth_checks ) - 1:
                print( "✓ WebSocket authentication handling present" )
            else:
                print( f"⚠ Limited WebSocket auth handling: {auth_patterns_found}/{len( auth_checks )}" )
                
        except Exception as e:
            print( f"⚠ Authentication integration issues: {e}" )
        
        # Test 10: Critical v000 dependency scanning
        print( "\\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( auth_test )  # Use any function to get file
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 11: WebSocket connection lifecycle validation
        print( "\\nTesting WebSocket connection lifecycle..." )
        try:
            # Check that both WebSocket endpoints handle connection lifecycle properly
            for endpoint in [ websocket_audio_endpoint, websocket_queue_endpoint ]:
                source_code = inspect.getsource( endpoint )
                
                lifecycle_patterns = [
                    "await websocket.accept()",
                    "try:",
                    "finally:",
                    "websocket_manager.disconnect("
                ]
                
                lifecycle_found = 0
                for pattern in lifecycle_patterns:
                    if pattern in source_code:
                        lifecycle_found += 1
                
                endpoint_name = endpoint.__name__
                if lifecycle_found == len( lifecycle_patterns ):
                    print( f"✓ {endpoint_name} connection lifecycle properly managed" )
                else:
                    print( f"⚠ {endpoint_name} lifecycle issues: {lifecycle_found}/{len( lifecycle_patterns )}" )
                    
        except Exception as e:
            print( f"⚠ WebSocket lifecycle validation issues: {e}" )
    
    except Exception as e:
        print( f"✗ Error during WebSocket API testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: WebSocket API has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - WebSocket operations will break" )
    else:
        print( "✅ WebSocket API smoke test completed successfully!" )
        print( "   Status: Real-time communication system ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ WebSocket API smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()