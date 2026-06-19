from cosa.rest.fifo_queue import FifoQueue
from cosa.memory.input_and_output_table import InputAndOutputTable
import cosa.utils.util as du
from datetime import datetime
from typing import Optional, Any, Dict
import uuid


class NotificationItem:
    """
    Simple notification item for queue storage.
    Replaces SolutionSnapshot for lightweight notification management.
    """
    
    def __init__( self, message: str, type: str = "task", priority: str = "medium",
                 source: str = "claude_code", user_id: Optional[str] = None,
                 id: Optional[str] = None, title: str = "",
                 response_requested: bool = False, response_type: Optional[str] = None,
                 response_default: Optional[str] = None, response_options: Optional[dict] = None,
                 timeout_seconds: Optional[int] = None, sender_id: Optional[str] = None,
                 abstract: str = "", suppress_ding: bool = False,
                 job_id: Optional[str] = None, queue_name: Optional[str] = None,
                 progress_group_id: Optional[str] = None,
                 prediction_hint: Optional[dict] = None,
                 display_qualifier_widget: bool = False,
                 session_name: Optional[str] = None,
                 voice_persona: Optional[dict] = None,
                 payload: Optional[dict] = None,
                 direction: str = "ai_to_human",
                 sender_persona: Optional[str] = None,
                 sender_icon: Optional[str] = None,
                 reply_to: Optional[str] = None,
                 thread_id: Optional[str] = None ) -> None:
        """
        Initialize a notification item.

        Requires:
            - message is a non-empty string
            - type is a valid notification type
            - priority is a valid priority level

        Ensures:
            - Creates unique id_hash for queue compatibility (backward compat)
            - Uses provided id if available (Phase 2.2 database ID)
            - Sets timestamp to current time
            - Initializes tracking fields
            - Stores Phase 2.2 response-required fields
            - Sets sender_id with fallback to unknown sender
            - Stores abstract for supplementary context

        Raises:
            - None
        """
        # Use database ID if provided, otherwise generate for backward compatibility
        self.id                 = id if id else str( uuid.uuid4() )
        self.id_hash            = self.id  # Maintain id_hash for backward compatibility
        self.message            = message
        self.title              = title
        self.type               = type
        self.priority           = priority
        self.source             = source
        self.user_id            = user_id
        self.timestamp          = self._get_local_timestamp()
        self.played             = False
        self.play_count         = 0
        self.last_played        = None

        # Phase 2.2 response-required fields
        self.response_requested = response_requested
        self.response_type      = response_type
        self.response_default   = response_default
        self.response_options   = response_options  # Multiple-choice options
        self.timeout_seconds    = timeout_seconds

        # Sender identification for multi-project grouping
        self.sender_id          = sender_id or "claude.code@unknown.deepily.ai"

        # Supplementary context for notification (plan details, URLs, markdown)
        self.abstract           = abstract

        # Suppress notification ding (used for conversational TTS from queue operations)
        self.suppress_ding      = suppress_ding

        # Agentic job ID for routing to job cards (e.g., dr-a1b2c3d4, mock-12345678)
        self.job_id             = job_id

        # Queue where job is running (run/todo/done) - for provisional job card registration
        self.queue_name         = queue_name

        # Progress group ID for in-place DOM updates (notifications sharing this ID update a single element)
        self.progress_group_id  = progress_group_id

        # Prediction engine hint (passed in before WebSocket push, or None during cold start)
        self.prediction_hint    = prediction_hint

        # Display qualifier widget expanded by default (yes/no comment input)
        self.display_qualifier_widget = display_qualifier_widget

        # Human-readable session name for UI header display
        self.session_name = session_name

        # Per-session voice persona (allocated at SessionStart by the
        # voice_persona router). When non-null, the UI passes this voice_id
        # to the TTS endpoint so each session speaks with its own voice.
        # See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md
        self.voice_persona = voice_persona

        # Generic structured payload for custom-typed state-update notifications
        # whose data shape doesn't fit existing typed fields. Carries event-specific
        # dicts for types like "speakerphone_changed" without polluting the
        # schema with one-off fields. None on standard notifications (skipped in to_dict).
        # See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md §6.1
        self.payload = payload

        # Communication-direction axis (provenance, orthogonal to `type`). First-class
        # column on the notifications table; wire JSON keys map 1:1 to columns.
        #   - "ai_to_human"  → AI speaking to the user (the bulk: TTS/cards). Default.
        #   - "human_to_ai"  → the user's voice arriving into an AI session.
        #   - "ai_to_ai"     → a directed peer DM between AI persona sessions.
        # The sender_* fields + reply_to/thread_id carry DM provenance + threading.
        # See: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md
        self.direction      = direction
        self.sender_persona = sender_persona
        self.sender_icon    = sender_icon
        self.reply_to       = reply_to
        self.thread_id      = thread_id

    def _get_local_timestamp( self ) -> str:
        """Get timezone-aware timestamp using configured timezone from ConfigurationManager"""
        try:
            # Import here to avoid circular imports
            import lupin_app.main as main_module
            config_mgr = main_module.config_mgr
            app_debug = main_module.app_debug

            # Get timezone from config, default to America/New_York (East Coast)
            timezone_name = config_mgr.get( "app timezone", default="America/New_York" )

            if app_debug: print( f"[TIMEZONE-DEBUG] NotificationItem using timezone: {timezone_name}" )

            # Use existing util function for timezone-aware datetime, then convert to ISO format
            tz_date = du.get_current_datetime_raw( tz_name=timezone_name )
            result = tz_date.isoformat()

            if app_debug: print( f"[TIMEZONE-DEBUG] NotificationItem timestamp: {result}" )

            return result
        except Exception as e:
            # Fallback to UTC if configuration or timezone is invalid
            print( f"[TIMEZONE] Warning: NotificationItem falling back to UTC: {e}" )
            from datetime import timezone
            return datetime.now( timezone.utc ).isoformat()

    def _get_time_display( self ) -> str:
        """Get formatted time with timezone abbreviation (e.g., '14:30 EST') for UI display."""
        try:
            # Import here to avoid circular imports
            import lupin_app.main as main_module
            config_mgr = main_module.config_mgr

            # Get timezone from config
            timezone_name = config_mgr.get( "app timezone", default="America/New_York" )

            # Get current time in configured timezone
            tz_date = du.get_current_datetime_raw( tz_name=timezone_name )

            # Format as "HH:MM TZ" (e.g., "14:30 EST")
            return tz_date.strftime( '%H:%M %Z' )
        except Exception as e:
            # Fallback to simple time without timezone
            print( f"[TIMEZONE] Warning: time_display falling back to simple format: {e}" )
            return datetime.now().strftime( '%H:%M' )

    def to_dict( self ) -> Dict[str, Any]:
        """Convert notification to dictionary for JSON serialization."""
        return {
            "id"                 : self.id,
            "id_hash"            : self.id_hash,  # Backward compatibility
            "message"            : self.message,
            "title"              : self.title,
            "type"               : self.type,
            "priority"           : self.priority,
            "source"             : self.source,
            "user_id"            : self.user_id,
            "timestamp"          : self.timestamp,
            "time_display"       : self._get_time_display(),  # "HH:MM TZ" for UI display
            "played"             : self.played,
            "play_count"         : self.play_count,
            "last_played"        : self.last_played,
            # Phase 2.2 response-required fields
            "response_requested" : self.response_requested,
            "response_type"      : self.response_type,
            "response_default"   : self.response_default,
            "response_options"   : self.response_options,  # Multiple-choice options
            "timeout_seconds"    : self.timeout_seconds,
            # Sender identification
            "sender_id"          : self.sender_id,
            # Supplementary context
            "abstract"           : self.abstract,
            # Suppress notification ding (conversational TTS)
            "suppress_ding"      : self.suppress_ding,
            # Agentic job ID for routing to job cards
            "job_id"             : self.job_id,
            # Queue where job is running (for provisional job card registration)
            "queue_name"         : self.queue_name,
            # Progress group ID for in-place DOM updates
            "progress_group_id"  : self.progress_group_id,
            # Prediction engine hint (null during cold start)
            "prediction_hint"            : self.prediction_hint,
            # Display qualifier widget expanded by default
            "display_qualifier_widget"   : self.display_qualifier_widget,
            # Human-readable session name for UI header display
            "session_name"               : self.session_name,
            # Per-session voice persona (None when no persona allocated → server uses Sam default)
            "voice_persona"              : self.voice_persona,
            # Generic structured payload for custom-typed notifications (None on standard types)
            "payload"                    : self.payload,
            # Communication-direction axis + DM provenance/threading (first-class columns).
            # Wire keys == column names (1:1; external repr == internal repr).
            "direction"                  : self.direction,
            "sender_persona"             : self.sender_persona,
            "sender_icon"                : self.sender_icon,
            "reply_to"                   : self.reply_to,
            "thread_id"                  : self.thread_id
        }


class NotificationFifoQueue( FifoQueue ):
    """
    FIFO queue for Claude Code notifications with priority handling and io_tbl logging.
    
    Inherits auto-emission of WebSocket events from parent FifoQueue.
    Logs all notifications to InputAndOutputTable for persistence and analytics.
    """
    
    def __init__( self, websocket_mgr: Optional[Any] = None, emit_enabled: bool = True,
                 debug: bool = False, verbose: bool = False,
                 fcm_wake_service: Optional[Any] = None ) -> None:
        """
        Initialize notification queue with io_tbl logging.

        Requires:
            - websocket_mgr is a valid WebSocketManager instance or None
            - emit_enabled is boolean to control auto-emission
            - fcm_wake_service is an FcmWakeService instance or None (S6 silent
              relay — None disables the wake trigger entirely)

        Ensures:
            - Inherits FifoQueue with 'notification' queue name
            - Initializes InputAndOutputTable for logging
            - Sets debug and verbose flags

        Raises:
            - Database connection errors propagated from InputAndOutputTable
        """
        super().__init__(
            websocket_mgr=websocket_mgr,
            queue_name="notification",  # Will emit 'notification_queue_update' events
            emit_enabled=emit_enabled
        )

        self.debug            = debug
        self.verbose          = verbose
        self._io_tbl          = InputAndOutputTable( debug=debug, verbose=verbose )
        self.fcm_wake_service = fcm_wake_service

        if self.debug:
            print( f"NotificationFifoQueue initialized with io_tbl logging" )
    
    def push( self, notification: NotificationItem ) -> None:
        """
        Override parent's push to emit enhanced notification data.
        Prevents double emission while including full notification details.
        
        Requires:
            - notification is a valid NotificationItem instance
            
        Ensures:
            - Adds notification to queue
            - Emits single WebSocket event with full notification data
            - Increments push counter
            
        Raises:
            - None
        """
        # Add to queue data structures under the base FifoQueue lock — this
        # override bypasses the parent's locked push(), and callers reach it
        # from worker threads (e.g. the notify route's asyncio.to_thread work),
        # so unlocked mutation would race the consumer thread.
        with self._lock:
            self.queue_list.append( notification )
            self.queue_dict[ notification.id_hash ] = notification
            self.push_counter += 1

        self._emit_notification_added( notification )

        if self.debug:
            print( f"[NOTIFY-QUEUE] Pushed notification {notification.id_hash} with enhanced WebSocket emission" )
    
    def push_notification( self, message: str, type: str = "task", priority: str = "medium",
                         source: str = "claude_code", user_id: Optional[str] = None,
                         id: Optional[str] = None, title: str = "",
                         response_requested: bool = False, response_type: Optional[str] = None,
                         response_default: Optional[str] = None, response_options: Optional[dict] = None,
                         timeout_seconds: Optional[int] = None, sender_id: Optional[str] = None,
                         abstract: str = "", suppress_ding: bool = False,
                         job_id: Optional[str] = None, queue_name: Optional[str] = None,
                         progress_group_id: Optional[str] = None,
                         prediction_hint: Optional[dict] = None,
                 display_qualifier_widget: bool = False,
                         session_name: Optional[str] = None,
                         voice_persona: Optional[dict] = None,
                         payload: Optional[dict] = None,
                         direction: str = "ai_to_human",
                         sender_persona: Optional[str] = None,
                         sender_icon: Optional[str] = None,
                         reply_to: Optional[str] = None,
                         thread_id: Optional[str] = None ) -> NotificationItem:
        """
        Push a notification with priority handling and io_tbl logging.

        Requires:
            - message is non-empty string
            - type is valid notification type (task, progress, alert, custom)
            - priority is valid priority level (urgent, high, medium, low)

        Ensures:
            - Creates NotificationItem with unique ID (or uses provided database ID)
            - Inserts at correct position based on priority
            - Logs to InputAndOutputTable for persistence
            - Auto-emits WebSocket event via parent class
            - Includes Phase 2.2 response-required fields if provided
            - Sets sender_id for multi-project grouping
            - Includes abstract for supplementary context if provided

        Raises:
            - None (handles errors gracefully)
        """
        # Create notification item with Phase 2.2 fields, sender_id, abstract, and suppress_ding
        notification = NotificationItem(
            message            = message,
            type               = type,
            priority           = priority,
            source             = source,
            user_id            = user_id,
            id                 = id,
            title              = title,
            response_requested = response_requested,
            response_type      = response_type,
            response_default   = response_default,
            response_options   = response_options,  # Multiple-choice options
            timeout_seconds    = timeout_seconds,
            sender_id          = sender_id,
            abstract           = abstract,
            suppress_ding      = suppress_ding,
            job_id             = job_id,
            queue_name         = queue_name,
            progress_group_id        = progress_group_id,
            prediction_hint          = prediction_hint,
            display_qualifier_widget = display_qualifier_widget,
            session_name             = session_name,
            voice_persona            = voice_persona,
            payload                  = payload,
            direction                = direction,
            sender_persona           = sender_persona,
            sender_icon              = sender_icon,
            reply_to                 = reply_to,
            thread_id                = thread_id
        )
        
        # Priority handling - urgent/high go to front, but after other urgent/high
        if priority in [ "urgent", "high" ]:
            # Scan + insert under the base FifoQueue lock: the insert_idx scan
            # and the insertion must be one atomic unit, and this path mutates
            # queue_list/queue_dict directly (it does not go through the
            # parent's locked push()).
            with self._lock:
                # Find insertion point after other urgent/high messages
                insert_idx = 0
                for idx, item in enumerate( self.queue_list ):
                    if hasattr( item, 'priority' ) and item.priority not in [ "urgent", "high" ]:
                        break
                    insert_idx = idx + 1

                # Manual insertion for priority placement
                self.queue_list.insert( insert_idx, notification )
                self.queue_dict[ notification.id_hash ] = notification
                self.push_counter += 1

            self._emit_notification_added( notification )
        else:
            # Normal priority goes to end (use our overridden push method)
            self.push( notification )
        
        # Log to io_tbl for persistence and analytics
        self._log_to_io_tbl( notification )
        
        if self.debug:
            print( f"[NOTIFY-QUEUE] Notification queued: {type}/{priority} - {message[:50]}..." )
        
        return notification
    
    def mark_played( self, notification_id: str ) -> bool:
        """
        Mark a notification as played and update io_tbl.
        
        Requires:
            - notification_id is valid UUID string
            
        Ensures:
            - Updates played status and play count
            - Logs playback event to io_tbl
            - Emits WebSocket update
            
        Raises:
            - None
        """
        # Find notification in queue
        notification = self.queue_dict.get( notification_id )
        if not notification:
            if self.debug:
                print( f"Notification {notification_id} not found for marking as played" )
            return False
        
        # Update playback tracking
        notification.played      = True
        notification.play_count += 1
        notification.last_played = notification._get_local_timestamp()
        
        # Log playback event to io_tbl
        self._log_playback_to_io_tbl( notification )
        
        # Emit update to sync client state
        self._emit_queue_update()
        
        if self.debug:
            print( f"Marked notification {notification_id} as played (count: {notification.play_count})" )

        return True

    def _emit_notification_added( self, notification: NotificationItem ) -> None:
        """
        Emit a `notification_queue_update` WebSocket event for a newly-added notification.

        Shared by `push()` (normal priority path) and `push_notification()` (urgent/high
        priority path) so the emission contract is defined in exactly one place.

        Fans out to the target user (if `notification.user_id` is set) or broadcasts to
        all connected clients, plus a deterministic per-job CC-listener session hand-off
        so service-account listener processes also receive the payload.

        Requires:
            - notification is a fully-populated NotificationItem
            - self.websocket_mgr may be None (silent no-op in that case)
            - self.emit_enabled controls whether emission actually fires

        Ensures:
            - When `user_id` is set: calls `emit_to_user_sync` targeting that user
            - When `user_id` is None: calls `emit` to broadcast to all clients
            - When `job_id` is set: additionally calls `emit_to_session_sync` to
              the deterministic `cc-listener-{job_id}` session so service-account
              CC listeners (which authenticate under a different user_id) receive it
            - event_data carries queue_name, value=size, and the full notification dict
            - Silent no-op when websocket_mgr is None or emit_enabled is False

        Raises:
            - None
        """
        # S6 silent relay: the FCM wake trigger fires on ENQUEUE (this is the
        # single chokepoint both the normal-priority push() and the urgent/high
        # push_notification() paths route through), independent of whether the
        # WS emit below is enabled — the wake exists precisely for the user
        # whose WebSocket isn't there.
        self._maybe_send_fcm_wake( notification )

        if not ( self.websocket_mgr and self.emit_enabled ):
            return

        event_data = {
            "queue_name"   : "notification",
            "value"        : self.size(),
            "notification" : notification.to_dict()
        }

        # Manager-lineage badge — live-path parity with the full-load
        # (senders-visible) hydration (Tiffany 2026-06-17, fixes the spawn-time
        # race root-caused in a16a7281). See _stamp_manager_persona docstring.
        self._stamp_manager_persona( event_data[ "notification" ], notification.sender_id )

        if notification.user_id:
            # Phase E migration (2026-04-27): targeted user + cc-listener
            # cross-user delivery now goes through the canonical dispatch
            # helper. CC listeners authenticate as a shared service-account
            # user_id (different from notification.user_id), so the helper
            # internally handles both the user emit and the listener emit.
            self.websocket_mgr.emit_to_user_or_listener_sync(
                user_id = notification.user_id,
                job_id  = notification.job_id,
                event   = "notification_queue_update",
                data    = event_data,
            )
            if self.debug: print( f"[NOTIFY-QUEUE] Dispatched notification (user={notification.user_id}, job_id={notification.job_id})" )
        else:
            # Broadcast notification - send to all connected clients.
            # Falls outside the helper's scope (helper is user-or-listener,
            # not broadcast). Listener still gets it via the cc-listener
            # session emit below if job_id is set.
            self.websocket_mgr.emit( "notification_queue_update", event_data )
            if self.debug: print( f"[NOTIFY-QUEUE] Broadcast notification to all users" )

            # Even on broadcast, route explicitly to cc-listener-{job_id}
            # if applicable — the listener might not be matching on
            # user_id-keyed broadcasts cleanly. Use the helper with
            # user_id=None to get listener-only delivery.
            if notification.job_id:
                self.websocket_mgr.emit_to_user_or_listener_sync(
                    user_id = None,
                    job_id  = notification.job_id,
                    event   = "notification_queue_update",
                    data    = event_data,
                )

    def _stamp_manager_persona( self, notification_dict: Dict[str, Any], sender_id: Optional[str] ) -> None:
        """
        Stamp the spawning-manager persona badge onto an outbound LIVE notification
        envelope for a CC worker sender, mirroring the senders-visible (full-load)
        hydration so the focus-bar manager-ownership badge appears on a freshly-spawned
        worker WITHOUT a page refresh.

        Background (Rick 2026-06-08 badge; Tiffany 2026-06-17 live-update race fix,
        root-caused in a16a7281): the full-load path stamps `manager_persona` on every
        sender via `_manager_persona_for_sender_id`, so a force-refreshed page always
        shows the badge. The live path previously carried `manager_persona` ONLY inside
        the `voice_persona_assigned` event's `payload`; if that single event raced to a
        null resolve at the worker's spawn instant (the worker's `spawned_by` not yet
        visible to the in-container server through the bind-mount), no later live event
        re-carried the lineage and the badge waited for a manual refresh. Stamping it on
        EVERY CC-sender emit makes the live path self-heal: the worker's next notification
        re-resolves (bridge now settled) and the client patches the badge live.

        Requires:
            - notification_dict is the to_dict() envelope about to be broadcast
            - sender_id may be None or a non-CC id (guarded)

        Ensures:
            - adds top-level "manager_persona" (badge dict, or None for a root session)
              for CC senders (sender_id containing '#'); leaves the dict untouched for
              non-CC senders so the per-emit bridge read is skipped
            - NEVER raises — best-effort, runs inside the WS emit path

        Raises:
            - None
        """
        if not sender_id or "#" not in sender_id:
            return
        try:
            # Deferred import: the notifications router imports THIS module at load
            # time, so a module-level import here would be circular. At first emit
            # (runtime) the router is already loaded, so this just hits the cache.
            from cosa.rest.routers.notifications import _manager_persona_for_sender_id
            notification_dict[ "manager_persona" ] = _manager_persona_for_sender_id( sender_id )
        except Exception as e:
            print( f"[NOTIFY-QUEUE] ⚠️ manager_persona stamp failed for {sender_id}: {type( e ).__name__}: {e}" )

    def _maybe_send_fcm_wake( self, notification: NotificationItem ) -> None:
        """
        Run the S6 §3.3 wake trigger for a newly-enqueued user-targeted notification.

        The full policy (enabled → no-live-mobile-WS → debounce → ≥1 token →
        off-thread send) lives in FcmWakeService.maybe_send_wake; this hook only
        gates on having a service and a target user, so the queue stays decoupled
        from FCM concerns.

        Requires:
            - notification is a fully-populated NotificationItem

        Ensures:
            - Silent no-op when fcm_wake_service is None or user_id is unset
              (broadcast notifications never wake devices)
            - NEVER raises — the notification path must survive any wake failure

        Raises:
            - None
        """
        if self.fcm_wake_service is None or not notification.user_id:
            return
        try:
            status = self.fcm_wake_service.maybe_send_wake( notification.user_id )
            if self.debug and self.verbose: print( f"[NOTIFY-QUEUE] FCM wake trigger for user {notification.user_id}: {status}" )
        except Exception as e:
            print( f"[NOTIFY-QUEUE] ⚠️ FCM wake trigger failed for user {notification.user_id}: {type( e ).__name__}: {e}" )

    def _emit_queue_update( self ) -> None:
        """
        Emit a WebSocket notification_queue_update event reflecting current queue state.

        Used by state-mutating operations that do NOT add a new notification
        (e.g., mark_played) so connected clients can resync unread-count tracking
        without re-fetching the full inbox.

        Requires:
            - self.websocket_mgr may be None (silent no-op in that case)
            - self.emit_enabled controls whether emission actually fires

        Ensures:
            - Broadcasts notification_queue_update with queue_name="notification",
              value=total size, and unplayed_count
            - Silent no-op when websocket_mgr is None or emit_enabled is False

        Raises:
            - None
        """
        if not ( self.websocket_mgr and self.emit_enabled ):
            return

        unplayed_count = sum( 1 for item in self.queue_list if not getattr( item, "played", False ) )
        event_data     = {
            "queue_name"     : "notification",
            "value"          : self.size(),
            "unplayed_count" : unplayed_count
        }
        self.websocket_mgr.emit( "notification_queue_update", event_data )
        if self.debug: print( f"[NOTIFY-QUEUE] _emit_queue_update size={self.size()} unplayed={unplayed_count}" )

    def get_next_unplayed( self, user_id: Optional[str] = None ) -> Optional[NotificationItem]:
        """
        Get the next notification that hasn't been played yet.
        
        Requires:
            - user_id is valid string or None for all users
            
        Ensures:
            - Returns first unplayed notification for user
            - Returns None if no unplayed notifications
            
        Raises:
            - None
        """
        for item in self.queue_list:
            # Check user filter
            if user_id and hasattr( item, 'user_id' ) and item.user_id != user_id:
                continue
            
            # Check if unplayed
            if hasattr( item, 'played' ) and not item.played:
                return item
        
        return None
    
    def get_user_notifications( self, user_id: str, include_played: bool = True ) -> list[NotificationItem]:
        """
        Get notifications for a specific user.
        
        Requires:
            - user_id is non-empty string
            - include_played is boolean
            
        Ensures:
            - Returns list of user's notifications
            - Filters by played status if requested
            
        Raises:
            - None
        """
        notifications = []
        for item in self.queue_list:
            if hasattr( item, 'user_id' ) and item.user_id == user_id:
                if include_played or not getattr( item, 'played', False ):
                    notifications.append( item )
        
        return notifications
    
    def _log_to_io_tbl( self, notification: NotificationItem ) -> None:
        """
        Log notification to InputAndOutputTable for persistence.
        
        Requires:
            - notification is valid NotificationItem
            
        Ensures:
            - Inserts row in io_tbl with notification data
            - Uses standardized format for notifications
            
        Raises:
            - None (handles errors gracefully)
        """
        try:
            # Format notification data for io_tbl
            input_data = f"NOTIFICATION: {notification.type}/{notification.priority}"
            output_data = notification.message
            
            # Insert into io_tbl with notification metadata
            self._io_tbl.insert_io_row(
                date=du.get_current_date(),
                time=du.get_current_time( include_timezone=False ),
                input_type="notification",
                input=input_data,
                output_raw=output_data,
                output_final=f"[{notification.source}] {output_data}",
                async_embedding=True  # Generate embeddings async for performance
            )
            
            if self.verbose:
                print( f"Logged notification {notification.id_hash} to io_tbl" )
                
        except Exception as e:
            if self.debug:
                print( f"Failed to log notification to io_tbl: {e}" )
    
    def _log_playback_to_io_tbl( self, notification: NotificationItem ) -> None:
        """
        Log notification playback event to io_tbl.
        
        Requires:
            - notification is valid NotificationItem with playback data
            
        Ensures:
            - Inserts playback event in io_tbl
            - Tracks user interaction with notifications
            
        Raises:
            - None (handles errors gracefully)
        """
        try:
            # Format playback event for io_tbl
            input_data = f"PLAYBACK: {notification.id_hash}"
            output_data = f"Played notification (count: {notification.play_count})"
            
            # Insert playback event
            self._io_tbl.insert_io_row(
                date=du.get_current_date(),
                time=du.get_current_time( include_timezone=False ),
                input_type="notification_playback",
                input=input_data,
                output_raw=output_data,
                output_final=f"User played: {notification.message[:100]}...",
                async_embedding=False  # Playback events don't need embeddings
            )
            
            if self.verbose:
                print( f"Logged playback event for {notification.id_hash} to io_tbl" )
                
        except Exception as e:
            if self.debug:
                print( f"Failed to log playback event to io_tbl: {e}" )


def quick_smoke_test():
    """
    Quick smoke test for NotificationFifoQueue.
    Tests complete workflow with priority handling and io_tbl logging.
    """
    import cosa.utils.util as du
    
    du.print_banner( "NotificationFifoQueue Smoke Test" )
    
    try:
        # Test queue initialization
        print( "✓ Testing queue initialization..." )
        queue = NotificationFifoQueue( debug=True, verbose=True )
        
        # Test adding notifications with different priorities
        print( "✓ Testing notification addition with priorities..." )
        
        # Add normal priority notification with explicit sender_id
        notif1 = queue.push_notification(
            message="[LUPIN] Normal priority test message",
            type="task",
            priority="medium",
            user_id="test_user",
            sender_id="claude.code@lupin.deepily.ai"
        )

        # Add high priority notification (should go to front) - no sender_id (tests default)
        notif2 = queue.push_notification(
            message="High priority urgent message",
            type="alert",
            priority="high",
            user_id="test_user"
        )

        # Add another normal priority with different sender
        notif3 = queue.push_notification(
            message="[COSA] Another normal message",
            type="progress",
            priority="medium",
            user_id="test_user",
            sender_id="claude.code@cosa.deepily.ai"
        )
        
        # Verify queue order (high priority should be first)
        assert queue.size() == 3, f"Expected 3 items, got {queue.size()}"

        first_item = queue.head()
        assert first_item.priority == "high", f"Expected high priority first, got {first_item.priority}"

        print( f"✓ Queue size: {queue.size()}, first item priority: {first_item.priority}" )

        # Test sender_id functionality
        print( "✓ Testing sender_id propagation..." )
        assert notif1.sender_id == "claude.code@lupin.deepily.ai", f"Expected LUPIN sender_id, got {notif1.sender_id}"
        assert notif2.sender_id == "claude.code@unknown.deepily.ai", f"Expected default sender_id, got {notif2.sender_id}"
        assert notif3.sender_id == "claude.code@cosa.deepily.ai", f"Expected COSA sender_id, got {notif3.sender_id}"

        # Verify sender_id in to_dict() output
        notif1_dict = notif1.to_dict()
        assert "sender_id" in notif1_dict, "sender_id missing from to_dict() output"
        assert notif1_dict[ "sender_id" ] == "claude.code@lupin.deepily.ai", f"sender_id mismatch in to_dict()"

        print( f"✓ sender_id tests passed: LUPIN={notif1.sender_id}, default={notif2.sender_id}, COSA={notif3.sender_id}" )
        
        # Test marking as played
        print( "✓ Testing playback tracking..." )
        success = queue.mark_played( notif2.id_hash )
        assert success, "Failed to mark notification as played"
        assert notif2.played == True, "Notification not marked as played"
        assert notif2.play_count == 1, f"Expected play_count 1, got {notif2.play_count}"
        
        # Test getting unplayed notifications
        print( "✓ Testing unplayed notification retrieval..." )
        unplayed = queue.get_next_unplayed( "test_user" )
        assert unplayed is not None, "Should have unplayed notifications"
        assert unplayed.played == False, "Retrieved notification should be unplayed"
        
        # Test user filtering
        print( "✓ Testing user notification filtering..." )
        user_notifs = queue.get_user_notifications( "test_user", include_played=True )
        assert len( user_notifs ) == 3, f"Expected 3 user notifications, got {len(user_notifs)}"
        
        user_unplayed = queue.get_user_notifications( "test_user", include_played=False )
        assert len( user_unplayed ) == 2, f"Expected 2 unplayed notifications, got {len(user_unplayed)}"
        
        print( "✓ All tests passed! NotificationFifoQueue working correctly." )
        
    except Exception as e:
        print( f"✗ Smoke test failed: {e}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()