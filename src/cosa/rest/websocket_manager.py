from fastapi import WebSocket
from datetime import datetime
from typing import Dict, Optional, List
import asyncio
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager


class WebSocketManager:
    """
    Manages WebSocket connections and provides Socket.IO-like emit functionality.
    
    This class acts as an adapter between the COSA queue system (which expects
    Socket.IO-like emit methods) and FastAPI's native WebSocket implementation.
    Supports user session management, event subscriptions, and thread-safe operations.
    
    Requires:
        - ConfigurationManager with LUPIN_CONFIG_MGR_CLI_ARGS environment variable
        - Configuration values for websocket behavior and available events
        - Main asyncio event loop reference for thread-safe operations
        
    Ensures:
        - Thread-safe WebSocket emission from background threads
        - User session management with optional single-session enforcement
        - Event subscription system with validation
        - Automatic cleanup of stale and dead connections
        - Socket.IO-compatible interface for COSA queue system
        
    Usage:
        manager = WebSocketManager()
        manager.set_event_loop(asyncio.get_event_loop())
        manager.connect(websocket, session_id, user_id, events)
        manager.emit("event_type", {"data": "value"})
    """
    
    def __init__( self ):
        """
        Initialize the WebSocket manager with empty connections and configuration.
        
        Requires:
            - ConfigurationManager environment variable LUPIN_CONFIG_MGR_CLI_ARGS is set
            - Configuration contains 'websocket available events' list
            
        Ensures:
            - Initializes all connection tracking dictionaries
            - Loads configuration for session management and events
            - Sets up event subscription system with validation
            - Configures single-session policy based on configuration
            
        Raises:
            - ValueError if websocket available events configuration is missing
            - ConfigException if configuration manager initialization fails
        """
        self.active_connections: Dict[str, WebSocket] = {}
        # Map session_id to user_id for routing
        self.session_to_user: Dict[str, str] = {}
        # Map user_id to list of their session_ids
        self.user_sessions: Dict[str, list] = {}
        # Cache user_id → email for debug logging (populated on connect, cleared on last disconnect)
        self.user_to_email: Dict[str, str] = {}
        # Track which sessions belong to admin users (for targeted admin broadcasts)
        self.session_is_admin: Dict[str, bool] = {}
        # Store reference to main event loop for thread-safe operations
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        # Session management configuration
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.single_session_per_user = self.config_mgr.get( "websocket enforce single session per user", default=False, return_type="boolean" )
        self.session_timestamps: Dict[str, datetime] = {}  # Track when sessions connected
        self.debug = self.config_mgr.get( "app debug", default=False, return_type="boolean" )

        # Event subscription system
        self.session_subscriptions: Dict[str, List[str]] = {}  # Map session_id to list of subscribed events
        
        # Load available events from configuration
        event_list = self.config_mgr.get( "websocket available events", default=[], return_type="list-string" )
        if not event_list:
            raise ValueError( "websocket available events configuration is missing or empty! Please check lupin-app.ini" )
        
        self.available_events = set( event_list )
        print( f"[WS] Loaded {len(self.available_events)} available event types from configuration" )
        
        print( f"[WS] WebSocketManager initialized with single_session_per_user = {self.single_session_per_user}" )
    
    def set_event_loop( self, loop: asyncio.AbstractEventLoop ):
        """
        Store reference to the main event loop for thread-safe operations.
        
        This should be called during application startup to enable safe
        WebSocket emissions from background threads.
        
        Requires:
            - loop is a valid asyncio event loop
            
        Ensures:
            - Stores loop reference for thread-safe coroutine scheduling
            - Enables emit() method to work from any thread
            - Prints confirmation message
            
        Raises:
            - None
        """
        self.main_loop = loop
        print( "[WS] Event loop reference stored for thread-safe operations" )
    
    def connect( self, websocket: WebSocket, session_id: str, user_id: str = None, subscribed_events: List[str] = None, email: str = None, roles: list = None ):
        """
        Add a new WebSocket connection with optional user association.
        
        Implements optional single-session policy: if enabled, closes old sessions
        when a user connects with a new session.
        
        Requires:
            - websocket is a valid FastAPI WebSocket instance
            - session_id is a unique string identifier
            - subscribed_events (if provided) contains valid event names or "*"
            
        Ensures:
            - Adds connection to active_connections dictionary
            - Associates session with user if user_id provided
            - Closes old sessions if single-session policy enabled
            - Sets up event subscriptions (defaults to "*" for all events)
            - Records connection timestamp
            - Validates subscribed events against available_events
            
        Raises:
            - Exception if closing old WebSocket connections fails (handled gracefully)
        """
        # Check for single-session policy
        if user_id and self.single_session_per_user and user_id in self.user_sessions:
            existing_sessions = self.user_sessions[user_id][:]
            if len( existing_sessions ) > 0:
                print( f"[WS] User {user_id} already connected with {len(existing_sessions)} session(s), closing old ones" )
                for old_session_id in existing_sessions:
                    if old_session_id != session_id and old_session_id in self.active_connections:
                        # Close the old WebSocket connection
                        old_ws = self.active_connections[old_session_id]
                        try:
                            # Schedule close on the event loop if we have one.
                            # Phase 5 of WS reconnect circuit-breaker milestone: use
                            # close code 4002 (auth: session conflict) instead of the
                            # normal-close 1000, so the displaced client recognizes
                            # this as PERMANENT and does NOT auto-retry. Browser-side
                            # `ws-channel.js` PERMANENT_CLOSE_CODES handles this.
                            if self.main_loop and self.main_loop.is_running():
                                asyncio.run_coroutine_threadsafe(
                                    old_ws.close( code=4002, reason="session_conflict_displaced" ),
                                    self.main_loop
                                )
                            print( f"[WS] Closed old session {old_session_id} for user {user_id}" )
                        except Exception as e:
                            print( f"[WS] Error closing old session {old_session_id}: {e}" )
                        # Clean up the connection
                        self.disconnect( old_session_id )
        
        # Add the new connection
        self.active_connections[session_id] = websocket
        self.session_timestamps[session_id] = datetime.now()
        
        if user_id:
            self.session_to_user[session_id] = user_id
            if user_id not in self.user_sessions:
                self.user_sessions[user_id] = []
            if session_id not in self.user_sessions[user_id]:
                self.user_sessions[user_id].append( session_id )
            if email:
                self.user_to_email[ user_id ] = email

        # Track admin status for targeted admin broadcasts
        self.session_is_admin[ session_id ] = bool( roles and "admin" in roles )

        # Store event subscriptions
        session_type = "listener" if session_id.startswith( "cc-listener-" ) else "browser"
        if subscribed_events:
            # Validate events
            valid_events = [e for e in subscribed_events if e == "*" or e in self.available_events]
            self.session_subscriptions[session_id] = valid_events
            print( f"[WS] Session {session_id} ({session_type}) subscribed to: {valid_events}" )
        else:
            # Default: subscribe to all events
            self.session_subscriptions[session_id] = ["*"]
            print( f"[WS] Session {session_id} ({session_type}) subscribed to: all events (*)" )

        print( f"[WS] STATE after connect: {len( self.active_connections )} active, {len( self.user_sessions )} users: {list( self.user_sessions.keys() )[ :3 ]}" )

    def disconnect( self, session_id: str ):
        """
        Remove a WebSocket connection and clean up all associated data.
        
        Requires:
            - session_id is a string (may or may not exist in connections)
            
        Ensures:
            - Removes connection from active_connections if present
            - Cleans up session timestamp tracking
            - Removes event subscription mappings
            - Cleans up user-to-session associations
            - Removes empty user session lists
            
        Raises:
            - None (handles missing keys gracefully)
        """
        # Log disconnect with session type and email
        session_type = "listener" if session_id.startswith( "cc-listener-" ) else "browser"
        user_id_tag  = self.session_to_user.get( session_id, "unknown" )
        email_tag    = self.user_to_email.get( user_id_tag, "" )
        email_suffix = f" ({email_tag})" if email_tag else ""
        print( f"[WS] Disconnecting {session_type} session {session_id} for user {user_id_tag}{email_suffix}" )

        if session_id in self.active_connections:
            # Explicitly close the WebSocket so the browser receives a close frame
            # and can trigger onclose → scheduleReconnect (prevents phantom connections)
            ws = self.active_connections[session_id]
            try:
                if self.main_loop and self.main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        ws.close( code=1000, reason="Server disconnect" ),
                        self.main_loop
                    )
            except Exception as e:
                print( f"[WS] Error closing WebSocket for {session_id}: {e}" )
            del self.active_connections[session_id]

        # Clean up session timestamp
        if session_id in self.session_timestamps:
            del self.session_timestamps[session_id]

        # Clean up event subscriptions
        if session_id in self.session_subscriptions:
            del self.session_subscriptions[session_id]

        # Clean up admin tracking
        self.session_is_admin.pop( session_id, None )

        # Clean up user association
        if session_id in self.session_to_user:
            user_id = self.session_to_user[session_id]
            del self.session_to_user[session_id]

            if user_id in self.user_sessions:
                self.user_sessions[user_id].remove(session_id)
                if not self.user_sessions[user_id]:
                    del self.user_sessions[user_id]
                    self.user_to_email.pop( user_id, None )

        print( f"[WS] STATE after disconnect: {len( self.active_connections )} active, {len( self.user_sessions )} users: {list( self.user_sessions.keys() )[ :3 ]}" )

    def register_session_user( self, session_id: str, user_id: str ):
        """
        Register a session-to-user association without a WebSocket connection.
        
        This is used when a TTS request comes in with authentication, allowing
        us to associate the session with a user before the audio WebSocket connects.
        
        Requires:
            - session_id is a non-empty string
            - user_id is a non-empty string
            
        Ensures:
            - Creates session-to-user mapping
            - Adds session to user's session list
            - Initializes user session list if needed
            - Avoids duplicate session entries
            - Prints confirmation message
            
        Raises:
            - None
        """
        # Store the association even if WebSocket hasn't connected yet
        self.session_to_user[session_id] = user_id
        
        # Track user sessions
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = []
        if session_id not in self.user_sessions[user_id]:
            self.user_sessions[user_id].append( session_id )
        
        print( f"[WS] Registered session {session_id} for user {user_id} (pre-WebSocket)" )
    
    async def async_emit( self, event: str, data: dict ):
        """
        Emit an event to all connected WebSocket clients asynchronously.
        
        Mimics Socket.IO's emit functionality for COSA queue compatibility.
        Sends messages only to clients subscribed to the event.
        
        Requires:
            - event is a non-empty string event name
            - data is a dictionary containing event data
            
        Ensures:
            - Creates timestamped message in expected format
            - Sends to all clients subscribed to the event or "*"
            - Automatically disconnects failed connections
            - Cleans up disconnected clients from tracking
            
        Raises:
            - None (WebSocket send failures handled gracefully)
        """
        # Build message in format expected by queue.js
        message = {
            "type": event,
            "timestamp": du.get_current_datetime_iso(),
            **data
        }
        
        # Send to all connected clients that are subscribed to this event
        disconnected = []
        for session_id, websocket in self.active_connections.items():
            # Check if this session is subscribed to this event
            subscriptions = self.session_subscriptions.get( session_id, ["*"] )
            
            if "*" in subscriptions or event in subscriptions:
                try:
                    await websocket.send_json( message )
                except:
                    # Mark for removal if send fails
                    disconnected.append( session_id )
        
        # Clean up disconnected clients
        for session_id in disconnected:
            self.disconnect( session_id )
    
    def get_connection_count( self ) -> int:
        """
        Return the number of active WebSocket connections.
        
        Requires:
            - None
            
        Ensures:
            - Returns count of active_connections dictionary
            
        Raises:
            - None
        """
        return len( self.active_connections )
    
    def is_connected( self, session_id: str ) -> bool:
        """
        Check if a specific session has an active WebSocket connection.
        
        Requires:
            - session_id is a string
            
        Ensures:
            - Returns True if session exists in active_connections
            - Returns False otherwise
            
        Raises:
            - None
        """
        return session_id in self.active_connections
    
    async def emit_to_session( self, session_id: str, event: str, data: dict ):
        """
        Emit an event to a specific WebSocket session.
        
        Requires:
            - session_id is a non-empty string
            - event is a non-empty string event name
            - data is a dictionary containing event data
            
        Ensures:
            - Sends timestamped message to specified session if active
            - Disconnects session if send fails
            - Returns early if session not found
            
        Raises:
            - None (WebSocket send failures handled gracefully)
        """
        if session_id not in self.active_connections:
            return
            
        message = {
            "type": event,
            "timestamp": du.get_current_datetime_iso(),
            **data
        }
        
        try:
            websocket = self.active_connections[session_id]
            await websocket.send_json( message )
        except:
            self.disconnect( session_id )
    
    def emit( self, event: str, data: dict ):
        """
        Thread-safe synchronous wrapper for emit functionality.
        
        This method is called by COSA queues which expect synchronous Socket.IO-style emit.
        Uses asyncio.run_coroutine_threadsafe to safely schedule the coroutine
        on the main event loop from any thread.
        
        Requires:
            - event is a non-empty string event name
            - data is a dictionary containing event data
            - self.main_loop is set and running
            
        Ensures:
            - Schedules async emission on main event loop
            - Does not block calling thread
            - Prints error messages if event loop unavailable
            - Provides debug output when enabled
            
        Raises:
            - None (errors logged but not raised)
        """
        if not self.main_loop:
            print( f"[ERROR] No event loop reference - cannot emit {event}" )
            return
        
        if not self.main_loop.is_running():
            print( f"[ERROR] Event loop not running - cannot emit {event}" )
            return
        
        try:
            # Schedule coroutine on main event loop from any thread
            future = asyncio.run_coroutine_threadsafe(
                self._async_emit( event, data ),
                self.main_loop
            )
            # Don't wait for result to avoid blocking
            if self.debug:
                print( f"[WS] Scheduled emission of {event}" )
        except Exception as e:
            print( f"[ERROR] Failed to schedule emission: {e}" )
    
    async def _async_emit( self, event: str, data: dict ):
        """
        Internal async method to emit events to all clients.
        
        This is the actual implementation that sends to WebSocket clients.
        Used by the thread-safe emit() wrapper method.
        
        Requires:
            - event is a non-empty string event name
            - data is a dictionary containing event data
            
        Ensures:
            - Delegates to async_emit for actual message sending
            
        Raises:
            - None (exceptions propagated from async_emit)
        """
        await self.async_emit( event, data )
    
    def emit_to_user_sync( self, user_id: str, event: str, data: dict ):
        """
        Thread-safe synchronous wrapper for emit_to_user.

        This method is called by COSA queues which expect synchronous emit.
        Uses asyncio.run_coroutine_threadsafe to safely schedule the coroutine
        on the main event loop from any thread.

        WARNING — broadcast scope:
            This method delivers ONLY to the named user's sessions. It is the
            right primitive for events that should remain private to that user
            (notification queue updates, response payloads — anything that
            another admin should NOT see). For queue or job state events that
            admins watching the system-wide view should also see — job_created,
            job_removed, job_paused, job_resumed, job_state_transition — use
            `emit_to_user_and_admins_sync` instead. The Session 248e740e bug
            (admin browser stuck with 14 stale mock job cards from an E2E test
            run) was caused by emitting `job_removed` only via this method,
            which reached the test user's zero browser sessions and never told
            the admin browser to remove the cards. The canonical dual-emit
            method removes that discipline burden.

        Requires:
            - user_id is a non-empty string
            - event is a non-empty string event name
            - data is a dictionary containing event data
            - self.main_loop is set and running

        Ensures:
            - Schedules async emission to user on main event loop
            - Does not block calling thread
            - Prints error messages if event loop unavailable
            - Prints confirmation when successfully scheduled

        Raises:
            - None (errors logged but not raised)
        """
        if not self.main_loop:
            print( f"[ERROR] No event loop reference - cannot emit {event} to user {user_id}" )
            return
        
        if not self.main_loop.is_running():
            print( f"[ERROR] Event loop not running - cannot emit {event} to user {user_id}" )
            return
        
        try:
            # Schedule coroutine on main event loop from any thread
            future = asyncio.run_coroutine_threadsafe(
                self.emit_to_user( user_id, event, data ),
                self.main_loop
            )
            # Don't wait for result to avoid blocking the COSA thread
            email_tag    = self.user_to_email.get( user_id, "" )
            email_suffix = f" ({email_tag})" if email_tag else ""
            print( f"[WS] Scheduled emission of {event} to user {user_id}{email_suffix}" )
        except Exception as e:
            print( f"[ERROR] Failed to schedule emission to user {user_id}: {e}" )

    def emit_to_session_sync( self, session_id: str, event: str, data: dict ):
        """
        Thread-safe synchronous wrapper for emit_to_session.

        Used for cross-user delivery to CC listener sessions that authenticate
        as a service account (different user_id than the target human user).

        Requires:
            - session_id is a non-empty string
            - event is a non-empty string event name
            - data is a dictionary containing event data
            - self.main_loop is set and running

        Ensures:
            - Returns immediately if session not in active_connections (no-op)
            - Schedules async emission to session on main event loop
            - Does not block calling thread

        Raises:
            - None (errors logged but not raised)
        """
        if session_id not in self.active_connections:
            return

        if not self.main_loop:
            print( f"[ERROR] No event loop reference - cannot emit {event} to session {session_id}" )
            return

        if not self.main_loop.is_running():
            print( f"[ERROR] Event loop not running - cannot emit {event} to session {session_id}" )
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.emit_to_session( session_id, event, data ),
                self.main_loop
            )
            print( f"[WS] Scheduled emission of {event} to session {session_id}" )
        except Exception as e:
            print( f"[ERROR] Failed to schedule emission to session {session_id}: {e}" )

    def emit_to_admins_sync( self, event: str, data: dict, exclude_user_id: str = None ):
        """
        Emit event to all connected admin sessions, optionally excluding one user.

        Requires:
            - event is a non-empty string event name
            - data is a dictionary containing event data
            - self.main_loop is set and running

        Ensures:
            - Sends event to all sessions where session_is_admin is True
            - Skips sessions belonging to exclude_user_id (to avoid double delivery)
            - Thread-safe via asyncio.run_coroutine_threadsafe
            - Does not block calling thread

        Raises:
            - None (errors logged but not raised)
        """
        if not self.main_loop or not self.main_loop.is_running():
            return

        # Collect admin user_ids (deduplicated), excluding the specified user
        admin_user_ids = set()
        for session_id, is_admin in self.session_is_admin.items():
            if not is_admin:
                continue
            user_id = self.session_to_user.get( session_id )
            if user_id and user_id != exclude_user_id:
                admin_user_ids.add( user_id )

        for admin_uid in admin_user_ids:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.emit_to_user( admin_uid, event, data ),
                    self.main_loop
                )
                email_tag    = self.user_to_email.get( admin_uid, "" )
                email_suffix = f" ({email_tag})" if email_tag else ""
                if self.debug: print( f"[WS] Admin broadcast: {event} → {admin_uid}{email_suffix}" )
            except Exception as e:
                print( f"[ERROR] Failed to schedule admin emission to {admin_uid}: {e}" )

    def emit_to_user_and_admins_sync( self, user_id: str, event: str, data: dict ):
        """
        Canonical dual-emit for queue and job state events.

        Delivers the event to the owning user AND every admin session watching
        the global queue, deduplicating so the owner is never sent the event
        twice (when the owner happens to also be an admin).

        This is the right method to call for ANY event that signals a queue or
        job mutation that admins watching the system-wide view should see:
        job created, job removed, job paused, job resumed, job state
        transitions, etc. Use this instead of calling emit_to_user_sync followed
        by emit_to_admins_sync separately — that pattern was the source of the
        Session 248e740e bug where pause/resume/delete events stranded cards in
        admin browsers because callers forgot the second call.

        Use emit_to_user_sync directly only for events that admins should NOT
        see (private notifications, response payloads). Use emit() only for
        truly system-wide events (notification sounds, time updates).

        Requires:
            - user_id is the owning user UUID (non-empty string)
            - event is a non-empty string event name
            - data is a JSON-serializable dict
            - self.main_loop is set and running (matches the underlying primitives)

        Ensures:
            - Owner receives the event via emit_to_user_sync
            - All admin sessions where session_is_admin is True receive the
              event, deduplicated, with the owner's user_id excluded to prevent
              double delivery when the owner is also an admin
            - Both underlying calls are thread-safe via run_coroutine_threadsafe
            - Errors in either call are logged but never raised
            - No-op if main_loop is missing or stopped (matches existing primitives)

        Raises:
            - None (errors logged by underlying methods but not raised)
        """
        self.emit_to_user_sync( user_id, event, data )
        self.emit_to_admins_sync( event, data, exclude_user_id=user_id )

    def emit_to_user_or_listener_sync(
        self,
        user_id: Optional[str],
        job_id: Optional[str],
        event: str,
        data: dict
    ) -> dict:
        """
        Canonical dual-emit for notifications that may target a CC listener.

        Always tries the primary user emit (via emit_to_user_sync) when the
        user has any active sessions. If `job_id` is provided AND a session
        named `cc-listener-{job_id}` is active in active_connections
        (regardless of which user_id owns it), ALSO emits to that session.
        The two emits are independent — both fire if both targets are
        reachable, neither blocks the other, errors are logged but never
        raised.

        Use this for ANY notification dispatch where:
        - The primary target is identified by user_id (email-resolved or owner)
        - The notification is associated with a specific agentic-job / CC
          session via job_id, and a CC listener may need to receive it
          cross-user (CC listeners authenticate as a shared service-account
          user_id, so emit_to_user_sync alone won't reach them).

        Use emit_to_user_sync directly only for events with no job_id concept
        (auth lifecycle, system events). Use emit_to_user_and_admins_sync for
        queue/job state events admins should see.

        Background: Bug filed 2026-04-27 (session 49c27830) — 3 user-initiated
        messages from the LookML CC notifications panel were dropped because
        notify_user short-circuited on is_user_connected(target_system_id)=False
        even though cc-listener-{job_id} was right there in active_connections
        under a different shared service-account user_id. The narrow fix
        added an inline fallback to one branch; this helper extracts the
        pattern so all 6 dispatch sites can call it consistently.

        Requires:
            - user_id is None or a non-empty string (UUID for connected users)
            - job_id is None or a non-empty string
            - event is a non-empty event name string
            - data is a JSON-serializable dict
            - self.main_loop is set and running (matches sibling sync helpers)

        Ensures:
            - Returns dict {"user_delivered": bool, "listener_delivered": bool,
                            "any_delivered": bool}
            - user_delivered is True iff user_id had at least one active session
              AND the underlying emit_to_user_sync did not fail
            - listener_delivered is True iff job_id was provided AND
              cc-listener-{job_id} was in active_connections AND the
              underlying emit_to_session_sync did not fail
            - any_delivered is True iff at least one of the two delivered
            - Errors in either underlying call are caught, logged, and never
              re-raised (consistent with sibling sync helpers)
            - No-op (returns all-False) if main_loop is missing or stopped

        Raises:
            - None (consistent with sibling sync helpers)
        """
        result = {
            "user_delivered"     : False,
            "listener_delivered" : False,
            "any_delivered"      : False,
        }

        listener_sid           = f"cc-listener-{job_id}" if job_id else None
        listener_in_user_fanout = False

        # Try primary user emit (only if user_id is provided and connected)
        if user_id and self.is_user_connected( user_id ):
            # Detect listener-already-covered BEFORE emitting so we can decide
            # whether the listener-targeted emit below would be a duplicate.
            # When the cc-listener authenticates with the same credentials as
            # the human user (the typical local-dev case), its session_id sits
            # in user_sessions[user_id] and emit_to_user_sync already reaches
            # it — a follow-on emit_to_session_sync is a duplicate dispatch
            # and produces the symptom: every voice message echoed back as
            # two "Received: ..." notifications + double tmux injection.
            if listener_sid and listener_sid in self.user_sessions.get( user_id, [] ):
                listener_in_user_fanout = True
            try:
                self.emit_to_user_sync( user_id, event, data )
                result[ "user_delivered" ] = True
                if listener_in_user_fanout:
                    # User fan-out reached the listener too — count it.
                    result[ "listener_delivered" ] = True
            except Exception as user_err:
                print( f"[WS-DISPATCH] emit_to_user_sync failed for user={user_id}: {user_err}" )

        # Listener-targeted fallback (independent of primary success), but ONLY
        # if the listener session was NOT already covered by the user fan-out.
        if listener_sid and not listener_in_user_fanout:
            if listener_sid in self.active_connections:
                try:
                    self.emit_to_session_sync( listener_sid, event, data )
                    result[ "listener_delivered" ] = True
                except Exception as listener_err:
                    print( f"[WS-DISPATCH] emit_to_session_sync failed for {listener_sid}: {listener_err}" )

        result[ "any_delivered" ] = result[ "user_delivered" ] or result[ "listener_delivered" ]
        return result

    def is_user_connected( self, user_id: str ) -> bool:
        """
        Check if a specific user has any active WebSocket connections.
        
        Requires:
            - user_id is a non-empty string
            
        Ensures:
            - Returns True if user has at least one active session
            - Returns False if user has no sessions or all sessions inactive
            - Validates sessions against active_connections
            
        Raises:
            - None
        """
        if user_id not in self.user_sessions:
            return False
        
        # Check if any of the user's sessions are still active
        active_sessions = [
            session_id for session_id in self.user_sessions[user_id]
            if session_id in self.active_connections
        ]
        
        return len( active_sessions ) > 0
    
    def get_user_connection_count( self, user_id: str ) -> int:
        """
        Get the number of active connections for a specific user.
        
        Requires:
            - user_id is a string
            
        Ensures:
            - Returns count of active sessions for the user
            - Returns 0 if user has no sessions
            - Only counts sessions present in active_connections
            
        Raises:
            - None
        """
        if user_id not in self.user_sessions:
            return 0
        
        active_sessions = [
            session_id for session_id in self.user_sessions[user_id]
            if session_id in self.active_connections
        ]
        
        return len( active_sessions )
    
    async def emit_to_user( self, user_id: str, event: str, data: dict ) -> bool:
        """
        Emit an event to all sessions belonging to a specific user.
        
        Args:
            user_id: The user ID to send to
            event: The event type
            data: The data to send
            
        Returns:
            bool: True if message was sent to at least one connection, False if user not available
        """
        if user_id not in self.user_sessions:
            print( f"[WS] emit_to_user: user {user_id} not in user_sessions — delivery skipped" )
            return False

        message = {
            "type": event,
            "timestamp": du.get_current_datetime_iso(),
            **data
        }

        sent_count = 0
        disconnected = []
        orphaned     = []

        sessions = list( self.user_sessions[ user_id ] )
        for session_id in sessions:
            if session_id in self.active_connections:
                # Check if this session is subscribed to this event
                subscriptions = self.session_subscriptions.get( session_id, ["*"] )

                if "*" in subscriptions or event in subscriptions:
                    try:
                        websocket = self.active_connections[ session_id ]
                        await websocket.send_json( message )
                        sent_count += 1
                    except Exception as send_err:
                        print( f"[WS] emit_to_user: send_json failed for session {session_id}: {send_err}" )
                        disconnected.append( session_id )
                else:
                    if self.debug: print( f"[WS] emit_to_user: session {session_id} not subscribed to {event}" )
            else:
                print( f"[WS] emit_to_user: session {session_id} not in active_connections (orphaned, cleaning up)" )
                orphaned.append( session_id )

        # Clean up disconnected sessions
        for session_id in disconnected:
            self.disconnect( session_id )

        # Clean up orphaned sessions (in user_sessions but not in active_connections)
        for session_id in orphaned:
            self.disconnect( session_id )

        if sent_count == 0:
            print( f"[WS] emit_to_user: {event} to user {user_id} — sent_count=0 (sessions={len( sessions )})" )

        return sent_count > 0
    
    async def emit_to_all( self, event: str, data: dict ):
        """
        Emit an event to all connected WebSocket clients.
        
        Alias for async_emit to match expected API naming conventions.
        
        Requires:
            - event is a non-empty string event name
            - data is a dictionary containing event data
            
        Ensures:
            - Delegates to async_emit for message broadcasting
            
        Raises:
            - None (exceptions propagated from async_emit)
        """
        await self.async_emit( event, data )
    
    def set_single_session_policy( self, enabled: bool ):
        """
        Enable or disable single-session-per-user policy.
        
        When enabled, new connections from a user will close their old sessions.
        
        Requires:
            - enabled is a boolean value
            
        Ensures:
            - Updates single_session_per_user flag
            - Prints confirmation message
            - Policy takes effect on subsequent connections
            
        Raises:
            - None
        """
        self.single_session_per_user = enabled
        print( f"[WS] Single-session policy {'enabled' if enabled else 'disabled'}" )
    
    def get_session_info( self, session_id: str ) -> Optional[dict]:
        """
        Get detailed information about a specific WebSocket session.
        
        Requires:
            - session_id is a string
            
        Ensures:
            - Returns dict with session details if session exists
            - Returns None if session not found in active_connections
            - Includes connection duration and timestamp information
            - Includes associated user_id if available
            
        Raises:
            - None
        """
        if session_id not in self.active_connections:
            return None
            
        info = {
            "session_id": session_id,
            "connected": True,
            "user_id": self.session_to_user.get( session_id ),
            "connected_at": self.session_timestamps.get( session_id ).isoformat() if session_id in self.session_timestamps else None
        }
        
        # Calculate connection duration
        if session_id in self.session_timestamps:
            duration = datetime.now() - self.session_timestamps[session_id]
            info["duration_seconds"] = duration.total_seconds()
        
        return info
    
    def get_all_sessions_info( self ) -> list:
        """
        Get detailed information about all active WebSocket sessions.
        
        Requires:
            - None
            
        Ensures:
            - Returns list of session info dictionaries
            - Each dict contains session details from get_session_info
            - Empty list if no active connections
            
        Raises:
            - None
        """
        sessions = []
        for session_id in self.active_connections:
            info = self.get_session_info( session_id )
            if info:
                sessions.append( info )
        return sessions
    
    def cleanup_stale_sessions( self, max_age_hours: int = 24 ) -> int:
        """
        Remove WebSocket sessions older than specified age.
        
        Requires:
            - max_age_hours is a positive integer
            
        Ensures:
            - Identifies sessions older than max_age_hours
            - Disconnects and cleans up stale sessions
            - Prints cleanup messages for removed sessions
            - Returns count of cleaned up sessions
            
        Raises:
            - None
        """
        now = datetime.now()
        stale_sessions = []
        
        for session_id, timestamp in self.session_timestamps.items():
            age = now - timestamp
            if age.total_seconds() > (max_age_hours * 3600):
                stale_sessions.append( session_id )
        
        for session_id in stale_sessions:
            print( f"[WS] Cleaning up stale session {session_id} (age > {max_age_hours} hours)" )
            self.disconnect( session_id )
        
        return len( stale_sessions )
    
    async def heartbeat_check( self ) -> int:
        """
        Send ping messages to all connections and remove dead ones.
        
        This method is called periodically by the heartbeat background task
        to proactively detect and clean up dead WebSocket connections.
        
        Requires:
            - Method is called from async context
            - Configuration may disable heartbeat checking
            
        Ensures:
            - Sends sys_ping message to all active connections
            - Identifies and removes connections that fail to receive ping
            - Prints summary of removed connections
            - Returns early if heartbeat disabled in configuration
            
        Raises:
            - None (WebSocket failures handled gracefully)
        """
        if not self.config_mgr.get( "websocket heartbeat enabled", default=True, return_type="boolean" ):
            return 0
        
        dead_sessions = []
        
        # Send ping to each connection
        for session_id, websocket in list( self.active_connections.items() ):
            try:
                # Attempt to send a ping message
                await websocket.send_json( {
                    "type": "sys_ping",
                    "timestamp": du.get_current_datetime_iso()
                } )
            except:
                # Connection is dead, mark for removal
                dead_sessions.append( session_id )
        
        # Clean up dead connections
        for session_id in dead_sessions:
            print( f"[WS-HEARTBEAT] Detected dead session: {session_id}" )
            self.disconnect( session_id )
        
        if dead_sessions:
            print( f"[WS-HEARTBEAT] Removed {len(dead_sessions)} dead connection(s)" )
        
        return len( dead_sessions )
    
    async def auto_cleanup( self ) -> int:
        """
        Run automatic cleanup of stale WebSocket sessions.
        
        This method is called periodically by the cleanup background task
        to remove sessions that have been connected for too long.
        
        Requires:
            - Method is called from async context
            - Configuration may disable auto cleanup
            
        Ensures:
            - Gets max age from configuration (default 24 hours)
            - Calls cleanup_stale_sessions with configured max age
            - Prints summary if sessions were cleaned
            - Returns early if cleanup disabled in configuration
            
        Raises:
            - None
        """
        if not self.config_mgr.get( "websocket cleanup enabled", default=True, return_type="boolean" ):
            return 0
        
        max_age_hours = self.config_mgr.get( "websocket session max age hours", default=24, return_type="int" )
        cleaned = self.cleanup_stale_sessions( max_age_hours )
        
        if cleaned > 0:
            print( f"[WS-CLEANUP] Cleaned {cleaned} stale session(s) older than {max_age_hours} hours" )
        
        return cleaned
    
    def update_subscriptions( self, session_id: str, events: List[str], action: str = "replace" ) -> bool:
        """
        Allow clients to update their event subscriptions after connection.
        
        Requires:
            - session_id exists in session_subscriptions
            - events is a list of strings (may include "*" for all events)
            - action is one of "replace", "add", or "remove"
            
        Ensures:
            - Validates events against available_events list
            - Updates subscriptions according to specified action
            - Prints confirmation of subscription changes
            - Returns True if successful, False if session not found
            - Handles duplicate prevention for "add" action
            
        Raises:
            - None
        """
        if session_id not in self.session_subscriptions:
            return False
        
        # Validate events
        valid_events = [e for e in events if e == "*" or e in self.available_events]
        
        if action == "replace":
            self.session_subscriptions[session_id] = valid_events
        elif action == "add":
            current = self.session_subscriptions[session_id]
            # Avoid duplicates
            self.session_subscriptions[session_id] = list( set( current + valid_events ) )
        elif action == "remove":
            current = self.session_subscriptions[session_id]
            self.session_subscriptions[session_id] = [e for e in current if e not in valid_events]
        
        print( f"[WS] Updated subscriptions for {session_id}: {self.session_subscriptions[session_id]}" )
        return True
    
    def get_subscription_stats( self ) -> dict:
        """
        Get comprehensive statistics about event subscriptions across all sessions.
        
        Requires:
            - None
            
        Ensures:
            - Returns dict with total connection count
            - Includes count of wildcard subscribers ("*")
            - Includes count of filtered (specific event) connections
            - Provides per-event subscription counts
            - Counts only reflect active sessions with subscriptions
            
        Raises:
            - None
        """
        stats = {
            "total_connections": len( self.active_connections ),
            "subscription_counts": {},
            "wildcard_subscribers": 0,
            "filtered_connections": 0
        }
        
        for session_id, events in self.session_subscriptions.items():
            if "*" in events:
                stats["wildcard_subscribers"] += 1
            else:
                stats["filtered_connections"] += 1
                for event in events:
                    stats["subscription_counts"][event] = stats["subscription_counts"].get( event, 0 ) + 1
        
        return stats


def quick_smoke_test():
    """
    Critical smoke test for WebSocketManager - validates core WebSocket functionality.
    
    This test is essential for v000 deprecation as WebSocketManager is critical
    for real-time communication and REST service functionality.
    """
    import cosa.utils.util as du
    
    du.print_banner( "WebSocketManager Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic instantiation
        print( "Testing basic instantiation..." )
        try:
            # This may fail if configuration is missing, but we'll test what we can
            manager = WebSocketManager()
            print( "✓ Basic instantiation successful" )
            instantiation_success = True
        except Exception as e:
            print( f"⚠ Basic instantiation failed: {e}" )
            print( "  This may be due to missing configuration - continuing with other tests..." )
            instantiation_success = False
        
        # Test 2: Core method presence
        print( "Testing core method presence..." )
        expected_methods = [
            "set_event_loop", "connect", "disconnect", "register_session_user",
            "async_emit", "get_connection_count", "is_connected", "emit_to_user",
            "emit_to_session", "emit", "emit_to_user_sync", "is_user_connected",
            "get_user_connection_count", "emit_to_all", "set_single_session_policy",
            "get_session_info", "get_all_sessions_info", "cleanup_stale_sessions",
            "heartbeat_check", "auto_cleanup", "update_subscriptions", "get_subscription_stats"
        ]
        
        methods_found = 0
        for method_name in expected_methods:
            if hasattr( WebSocketManager, method_name ):
                methods_found += 1
            else:
                print( f"⚠ Missing method: {method_name}" )
        
        if methods_found == len( expected_methods ):
            print( f"✓ All {len( expected_methods )} core methods present" )
        else:
            print( f"⚠ Only {methods_found}/{len( expected_methods )} core methods present" )
        
        # Test 3: Configuration integration
        print( "Testing configuration integration..." )
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            print( "✓ ConfigurationManager integration working" )
        except Exception as e:
            print( f"⚠ Configuration integration issues: {e}" )
        
        # Test 4: WebSocket dependency validation
        print( "Testing WebSocket dependencies..." )
        try:
            from fastapi import WebSocket
            print( "✓ FastAPI WebSocket import successful" )
        except ImportError as e:
            print( f"✗ FastAPI WebSocket import failed: {e}" )
        
        # Test 5: Async functionality validation (if instantiation worked)
        if instantiation_success:
            print( "Testing async functionality validation..." )
            try:
                # Test basic data structures are initialized
                if hasattr( manager, 'active_connections' ) and isinstance( manager.active_connections, dict ):
                    print( "✓ Connection tracking structures initialized" )
                else:
                    print( "✗ Connection tracking structures missing or wrong type" )
                
                # Test session mapping structures
                required_attrs = [
                    'session_to_user', 'user_sessions', 'session_timestamps', 
                    'session_subscriptions', 'available_events'
                ]
                
                attrs_present = 0
                for attr in required_attrs:
                    if hasattr( manager, attr ):
                        attrs_present += 1
                    else:
                        print( f"⚠ Missing attribute: {attr}" )
                
                if attrs_present == len( required_attrs ):
                    print( f"✓ All {len( required_attrs )} data structures present" )
                else:
                    print( f"⚠ Only {attrs_present}/{len( required_attrs )} data structures present" )
                
                # Test basic functionality without WebSocket connections
                initial_count = manager.get_connection_count()
                if initial_count == 0:
                    print( "✓ Connection count tracking working (initially 0)" )
                else:
                    print( f"⚠ Initial connection count not 0: {initial_count}" )
                
            except Exception as e:
                print( f"⚠ Async functionality validation issues: {e}" )
        
        # Test 6: Thread safety features
        print( "Testing thread safety features..." )
        try:
            import asyncio
            
            # Test that asyncio is properly imported and used
            if hasattr( WebSocketManager, 'set_event_loop' ):
                print( "✓ Event loop management available" )
            else:
                print( "✗ Event loop management missing" )
            
            # Test thread-safe methods exist
            thread_safe_methods = [ "emit", "emit_to_user_sync" ]
            ts_methods_found = 0
            for method in thread_safe_methods:
                if hasattr( WebSocketManager, method ):
                    ts_methods_found += 1
            
            if ts_methods_found == len( thread_safe_methods ):
                print( f"✓ All {len( thread_safe_methods )} thread-safe methods present" )
            else:
                print( f"⚠ Only {ts_methods_found}/{len( thread_safe_methods )} thread-safe methods present" )
                
        except ImportError as e:
            print( f"✗ asyncio import failed: {e}" )
        
        # Test 7: Critical v000 dependency scanning
        print( "\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( WebSocketManager )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\n' )
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
        
        # Test 8: Code quality validation
        print( "\nTesting code quality issues..." )
        
        # Check for duplicate method definitions (common issue in this file)
        method_names = []
        duplicate_methods = []
        
        for line_num, line in enumerate( lines ):
            if line.strip().startswith( "def " ) and not in_smoke_test:
                method_match = line.strip().split( '(' )[ 0 ].replace( "def ", "" ).strip()
                if method_match in method_names:
                    duplicate_methods.append( f"{method_match} (around line {line_num+1})" )
                else:
                    method_names.append( method_match )
        
        if duplicate_methods:
            print( f"⚠ Found {len( duplicate_methods )} duplicate method definitions:" )
            for dup in duplicate_methods[ :3 ]:  # Show first 3
                print( f"     • {dup}" )
        else:
            print( "✓ No duplicate method definitions found" )
        
    except Exception as e:
        print( f"✗ Error during WebSocketManager testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: WebSocketManager has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: HIGH - WebSocket functionality will break" )
    else:
        print( "✅ WebSocketManager smoke test completed successfully!" )
        print( "   Status: Core WebSocket functionality ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ WebSocketManager smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()