"""
Notification repository for CRUD operations on Notification model.

Provides notification-specific methods beyond base repository functionality,
including sender-based grouping and activity-anchored window loading.
"""

from typing import Optional, List, Dict
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case

from cosa.rest.postgres_models import Notification
from cosa.rest.db.repositories.base import BaseRepository


class NotificationRepository( BaseRepository[Notification] ):
    """
    Repository for Notification model with sender-aware operations.

    Extends BaseRepository with notification-specific methods:
        - Sender-based grouping for multi-project views
        - Activity-anchored window loading
        - State management
        - Response tracking
    """

    def __init__( self, session: Session ):
        """
        Initialize NotificationRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                notif_repo = NotificationRepository( session )
                notif = notif_repo.create_notification(...)
        """
        super().__init__( Notification, session )

    def create_notification(
        self,
        sender_id: str,
        recipient_id: uuid.UUID,
        message: str,
        type: str,
        priority: str,
        title: Optional[str] = None,
        abstract: Optional[str] = None,
        response_requested: bool = False,
        response_type: Optional[str] = None,
        response_default: Optional[str] = None,
        response_options: Optional[dict] = None,
        timeout_seconds: Optional[int] = None,
        expires_at: Optional[datetime] = None,
        job_id: Optional[str] = None,
        progress_group_id: Optional[str] = None,
        direction: str = "ai_to_human",
        sender_persona: Optional[str] = None,
        sender_icon: Optional[str] = None,
        reply_to: Optional[str] = None,
        thread_id: Optional[str] = None
    ) -> Notification:
        """
        Create new notification.

        Requires:
            - sender_id: Sender identifier (e.g., claude.code@lupin.deepily.ai)
            - recipient_id: Valid user UUID
            - message: Notification message text
            - type: Notification type (task, progress, alert, custom)
            - priority: Priority level (urgent, high, medium, low)

        Ensures:
            - Notification created with 'created' state
            - created_at set to current timestamp
            - Response fields populated if response_requested
            - Abstract stored if provided (for supplementary context)

        Returns:
            Created Notification instance

        Example:
            with get_db() as session:
                repo = NotificationRepository( session )
                notif = repo.create_notification(
                    sender_id    = "claude.code@lupin.deepily.ai",
                    recipient_id = user.id,
                    message      = "[LUPIN] Build completed",
                    type         = "task",
                    priority     = "medium"
                )
        """
        return self.create(
            sender_id          = sender_id,
            recipient_id       = recipient_id,
            message            = message,
            type               = type,
            priority           = priority,
            title              = title,
            abstract           = abstract,
            response_requested = response_requested,
            response_type      = response_type,
            response_default   = response_default,
            response_options   = response_options,
            timeout_seconds    = timeout_seconds,
            expires_at         = expires_at,
            job_id             = job_id,
            progress_group_id  = progress_group_id,
            direction          = direction,
            sender_persona     = sender_persona,
            sender_icon        = sender_icon,
            reply_to           = reply_to,
            thread_id          = thread_id,
            state              = "created"
        )

    def get_by_recipient( self, recipient_id: uuid.UUID, limit: int = 100, offset: int = 0 ) -> List[Notification]:
        """
        Get notifications for a recipient.

        Requires:
            - recipient_id: Valid user UUID

        Ensures:
            - Returns notifications ordered by created_at descending
            - Applies pagination

        Returns:
            List of Notification instances
        """
        return self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id
        ).order_by(
            desc( Notification.created_at )
        ).limit( limit ).offset( offset ).all()

    def get_sender_last_activities( self, recipient_id: uuid.UUID ) -> List[Dict]:
        """
        Get last activity timestamp per sender for a recipient.

        Requires:
            - recipient_id: Valid user UUID

        Ensures:
            - Returns list of {sender_id, last_activity, notification_count}
            - Ordered by last_activity descending (most recent first)
            - Used for activity-anchored window loading

        Returns:
            List of sender activity summaries

        Example:
            activities = repo.get_sender_last_activities( user.id )
            # [
            #   {"sender_id": "claude.code@lupin.deepily.ai", "last_activity": datetime(...), "count": 5},
            #   {"sender_id": "claude.code@cosa.deepily.ai", "last_activity": datetime(...), "count": 2}
            # ]
        """
        results = self.session.query(
            Notification.sender_id,
            func.max( Notification.created_at ).label( 'last_activity' ),
            func.count( Notification.id ).label( 'notification_count' )
        ).filter(
            Notification.recipient_id == recipient_id
        ).group_by(
            Notification.sender_id
        ).order_by(
            desc( func.max( Notification.created_at ) )
        ).all()

        return [
            {
                "sender_id"     : row.sender_id,
                "last_activity" : row.last_activity,
                "count"         : row.notification_count
            }
            for row in results
        ]

    def get_sender_conversation(
        self,
        sender_id: str,
        recipient_id: uuid.UUID,
        anchor: Optional[datetime] = None,
        window_hours: int = 24
    ) -> List[Notification]:
        """
        Load conversation window relative to anchor (activity-anchored loading).

        Requires:
            - sender_id: Sender identifier
            - recipient_id: Valid user UUID
            - anchor: Reference timestamp (defaults to sender's last activity)
            - window_hours: Hours before anchor to include (default: 24)

        Ensures:
            - Returns notifications within [anchor - window_hours, anchor]
            - Ordered by created_at ascending (oldest first for insertBefore prepend)
            - If anchor is None, uses sender's last activity as anchor

        Returns:
            List of Notification instances in chronological order (oldest first)

        Example:
            # Load last 24 hours relative to sender's last activity
            messages = repo.get_sender_conversation(
                sender_id    = "claude.code@lupin.deepily.ai",
                recipient_id = user.id,
                window_hours = 24
            )
        """
        # If no anchor provided, find sender's last activity
        if anchor is None:
            last_activity = self.session.query(
                func.max( Notification.created_at )
            ).filter(
                Notification.sender_id == sender_id,
                Notification.recipient_id == recipient_id
            ).scalar()

            if last_activity is None:
                return []  # No notifications from this sender

            anchor = last_activity

        # Calculate window start
        window_start = anchor - timedelta( hours=window_hours )

        return self.session.query( Notification ).filter(
            Notification.sender_id == sender_id,
            Notification.recipient_id == recipient_id,
            Notification.created_at >= window_start,
            Notification.created_at <= anchor
        ).order_by(
            Notification.created_at.asc()  # Oldest first - insertBefore prepends newest to top
        ).all()

    def update_state( self, notification_id: uuid.UUID, new_state: str ) -> Optional[Notification]:
        """
        Update notification state.

        Requires:
            - notification_id: Valid notification UUID
            - new_state: Target state (created, queued, delivered, responded, expired, error)

        Ensures:
            - State updated
            - Appropriate timestamp updated based on state transition

        Returns:
            Updated Notification instance or None if not found
        """
        notification = self.get_by_id( notification_id )
        if not notification:
            return None

        notification.state = new_state

        # Update appropriate timestamp based on state
        now = datetime.utcnow()
        if new_state == "delivered":
            notification.delivered_at = now
        elif new_state == "responded":
            notification.responded_at = now

        self.session.flush()
        return notification

    def update_response( self, notification_id: uuid.UUID, response_value: dict ) -> Optional[Notification]:
        """
        Record user response to notification.

        Requires:
            - notification_id: Valid notification UUID
            - response_value: Response data (flexible JSONB storage)

        Ensures:
            - response_value stored
            - responded_at timestamp set
            - state updated to 'responded'

        Returns:
            Updated Notification instance or None if not found

        Example:
            repo.update_response(
                notification_id = notif.id,
                response_value  = {"value": "yes", "source": "ui_button"}
            )
        """
        notification = self.get_by_id( notification_id )
        if not notification:
            return None

        notification.response_value = response_value
        notification.responded_at = datetime.utcnow()
        notification.state = "responded"

        self.session.flush()
        return notification

    def get_pending_for_recipient( self, recipient_id: uuid.UUID ) -> List[Notification]:
        """
        Get pending (unresponded) notifications requiring response.

        Requires:
            - recipient_id: Valid user UUID

        Ensures:
            - Returns notifications where response_requested = True
            - Excludes already responded or expired
            - Ordered by created_at ascending (oldest first)

        Returns:
            List of pending Notification instances
        """
        return self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id,
            Notification.response_requested == True,
            Notification.state.in_( ['created', 'queued', 'delivered'] )
        ).order_by(
            Notification.created_at.asc()
        ).all()

    def get_undelivered_for_recipient( self, recipient_id: uuid.UUID, limit: int = 100, max_age_hours: Optional[int] = None ) -> List[Notification]:
        """
        Get the recipient's UNDELIVERED notifications (the pull-able AFK inbox).

        Lever D of the messaging-coordination plane (FM-18): a notification that
        never reached the user — still in 'created'/'queued', never 'delivered' —
        is what the user "missed" while offline. This is the durable, pull-able
        record so a returning/AFK user can recover what a failed push dropped.

        The `max_age_hours` cap is the structural guard against the durable-outbox
        drain replaying STALE rows as a TTS storm on reconnect (the 2026-06-03
        incident: a server bounce drained months-old undelivered rows). When set,
        only rows newer than the cutoff are returned — applies to today's backlog
        AND any future row that goes stale-while-undelivered (live-path coverage).

        Requires:
            - recipient_id: Valid user UUID
            - max_age_hours: None (no age cap) or a positive int (hours)

        Ensures:
            - Returns notifications with state in ('created', 'queued') ONLY
              (excludes delivered / responded / expired)
            - Excludes soft-deleted/archived rows (is_hidden = True)
            - When max_age_hours is set, excludes rows older than that many hours
            - Ordered by created_at ascending (oldest-first — FIFO recovery)
            - Honors limit

        Returns:
            List of undelivered Notification instances
        """
        query = self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id,
            Notification.state.in_( [ 'created', 'queued' ] ),
            Notification.is_hidden == False
        )
        if max_age_hours is not None:
            cutoff = datetime.now( timezone.utc ) - timedelta( hours=max_age_hours )
            query  = query.filter( Notification.created_at >= cutoff )
        return query.order_by(
            Notification.created_at.asc()
        ).limit( limit ).all()

    def count_undelivered_for_recipient( self, recipient_id: uuid.UUID, max_age_hours: Optional[int] = None ) -> int:
        """
        Count the recipient's UNDELIVERED notifications (lever D — accurate "N missed").

        Unlike `get_undelivered_for_recipient` (which caps at `limit` for paging), this
        is an UNBOUNDED count, so the auth_success "N missed" surfacing is not silently
        capped at the page size. The `max_age_hours` cap mirrors the getter so the
        surfaced "N missed" count matches what is actually pullable (no phantom count
        of stale rows the getter would skip — and no stale-backlog storm trigger).

        Requires:
            - recipient_id: Valid user UUID
            - max_age_hours: None (no age cap) or a positive int (hours)

        Ensures:
            - counts notifications in state 'created'/'queued', excluding is_hidden
            - When max_age_hours is set, excludes rows older than that many hours

        Returns:
            int — the undelivered count
        """
        query = self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id,
            Notification.state.in_( [ 'created', 'queued' ] ),
            Notification.is_hidden == False
        )
        if max_age_hours is not None:
            cutoff = datetime.now( timezone.utc ) - timedelta( hours=max_age_hours )
            query  = query.filter( Notification.created_at >= cutoff )
        return query.count()

    def dismiss_undelivered_for_recipient( self, recipient_id: uuid.UUID, max_age_hours: Optional[int] = None ) -> int:
        """
        Soft-dismiss the recipient's UNDELIVERED notifications (the "reset missed" action).

        Sets is_hidden=True on every row the "N missed while away" badge counts, so the
        badge and the pull-able inbox both drop to zero. The notification STATE is left
        untouched ('created'/'queued') — preserving the honest audit trail that these
        rows were never actually delivered. is_hidden is the column the count/getter
        queries already filter on, so no schema change is needed and the dismiss is
        reversible (flip is_hidden back).

        The filter MIRRORS count_undelivered_for_recipient exactly so that, after this
        call, count_undelivered_for_recipient returns 0 for the same recipient + cap.

        Requires:
            - recipient_id: Valid user UUID
            - max_age_hours: None (dismiss all undelivered) or a positive int (hours)

        Ensures:
            - sets is_hidden=True on rows in state 'created'/'queued', is_hidden=False
            - When max_age_hours is set, only rows newer than the cutoff are dismissed
              (matches the windowed badge — older rows already fall out of the count)
            - does NOT change notification state (audit trail preserved)
            - flushes the session

        Returns:
            int — the number of rows dismissed
        """
        query = self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id,
            Notification.state.in_( [ 'created', 'queued' ] ),
            Notification.is_hidden == False
        )
        if max_age_hours is not None:
            cutoff = datetime.now( timezone.utc ) - timedelta( hours=max_age_hours )
            query  = query.filter( Notification.created_at >= cutoff )
        dismissed = query.update( { Notification.is_hidden: True }, synchronize_session=False )
        self.session.flush()
        return dismissed

    def get_expired_notifications( self ) -> List[Notification]:
        """
        Get all notifications in 'delivered' state past their expires_at.

        Used by background cleanup tasks to identify and expire timed-out notifications.

        Ensures:
            - Returns notifications where state='delivered' AND expires_at < now
            - Only includes notifications with non-null expires_at
            - Ordered by expires_at ascending (oldest expiration first)

        Returns:
            List of expired Notification instances
        """
        now = datetime.utcnow()
        return self.session.query( Notification ).filter(
            Notification.state == 'delivered',
            Notification.expires_at.isnot( None ),
            Notification.expires_at < now
        ).order_by(
            Notification.expires_at.asc()
        ).all()

    def mark_expired( self, notification_id: uuid.UUID ) -> Optional[Notification]:
        """
        Mark notification as expired (timeout reached).

        Requires:
            - notification_id: Valid notification UUID

        Ensures:
            - state set to 'expired'
            - Can optionally apply response_default if configured

        Returns:
            Updated Notification instance or None if not found
        """
        notification = self.get_by_id( notification_id )
        if not notification:
            return None

        notification.state = "expired"

        # If default response was configured, apply it
        if notification.response_default:
            notification.response_value = {"value": notification.response_default, "source": "timeout_default"}

        self.session.flush()
        return notification

    def count_by_sender( self, recipient_id: uuid.UUID ) -> Dict[str, int]:
        """
        Count notifications grouped by sender.

        Requires:
            - recipient_id: Valid user UUID

        Ensures:
            - Returns dict of sender_id -> count

        Returns:
            Dictionary mapping sender IDs to notification counts
        """
        results = self.session.query(
            Notification.sender_id,
            func.count( Notification.id ).label( 'count' )
        ).filter(
            Notification.recipient_id == recipient_id
        ).group_by(
            Notification.sender_id
        ).all()

        return { row.sender_id: row.count for row in results }

    def count_by_job_ids( self, job_ids: List[ str ] ) -> Dict[ str, int ]:
        """
        Bulk count of non-hidden notifications grouped by job_id.

        Single batched query; used to populate `has_interactions` on done/history
        endpoints without N+1 round-trips. Excludes soft-hidden rows for parity
        with the lazy-load endpoint at /api/get-job-interactions/{job_id}.

        Requires:
            - job_ids: list of job_id strings (may be empty)

        Ensures:
            - Returns dict mapping each input job_id to its non-hidden notification count
            - job_ids with zero notifications are present in the result with value 0
            - Empty input returns an empty dict (no DB call)

        Raises:
            - SQLAlchemyError on database failure (caller's responsibility to handle)
        """
        if not job_ids:
            return {}

        results = self.session.query(
            Notification.job_id,
            func.count( Notification.id ).label( 'count' )
        ).filter(
            Notification.job_id.in_( job_ids ),
            Notification.is_hidden == False
        ).group_by(
            Notification.job_id
        ).all()

        counts = { row.job_id: int( row.count ) for row in results }
        # Ensure every input job_id is in the result, even with zero count
        return { job_id: counts.get( job_id, 0 ) for job_id in job_ids }

    def delete_by_sender( self, sender_id: str, recipient_id: uuid.UUID ) -> int:
        """
        Delete all notifications from a sender for a recipient.

        Requires:
            - sender_id: Sender identifier (e.g., claude.code@lupin.deepily.ai)
            - recipient_id: Valid user UUID

        Ensures:
            - All notifications matching sender_id AND recipient_id deleted
            - Returns count of deleted notifications

        Returns:
            Number of notifications deleted

        Example:
            with get_db() as session:
                repo = NotificationRepository( session )
                count = repo.delete_by_sender(
                    sender_id    = "claude.code@lupin.deepily.ai",
                    recipient_id = user.id
                )
                print( f"Deleted {count} notifications" )
        """
        deleted = self.session.query( Notification ).filter(
            Notification.sender_id == sender_id,
            Notification.recipient_id == recipient_id
        ).delete()

        self.session.flush()
        return deleted

    def get_sender_conversations_by_date(
        self,
        sender_id: str,
        recipient_id: uuid.UUID,
        anchor: Optional[datetime] = None,
        window_hours: int = 168,  # Default 7 days
        include_hidden: bool = False,
        timezone_name: str = "America/New_York"
    ) -> Dict[str, List[Notification]]:
        """
        Load conversation grouped by date (ISO format).

        Requires:
            - sender_id: Sender identifier
            - recipient_id: Valid user UUID
            - anchor: Reference timestamp (defaults to sender's last activity)
            - window_hours: Hours before anchor to include (default: 168 = 7 days)
            - include_hidden: Whether to include hidden notifications (default: False)
            - timezone_name: IANA timezone for date grouping (default: America/New_York)

        Ensures:
            - Returns dict of date_string -> list of notifications
            - Date keys sorted descending (newest first: 2025-01-02, 2025-01-01, ...)
            - Each date key is ISO format (YYYY-MM-DD) in specified timezone
            - Notifications within each date ordered by created_at ascending

        Returns:
            Dict mapping date strings to notification lists

        Example:
            conversations = repo.get_sender_conversations_by_date(
                sender_id    = "claude.code@lupin.deepily.ai",
                recipient_id = user.id,
                window_hours = 168  # 7 days
            )
            # {"2025-01-01": [notif1, notif2], "2024-12-31": [notif3]}
        """
        import zoneinfo

        # If no anchor provided, find sender's last activity
        if anchor is None:
            last_activity = self.session.query(
                func.max( Notification.created_at )
            ).filter(
                Notification.sender_id == sender_id,
                Notification.recipient_id == recipient_id
            ).scalar()

            if last_activity is None:
                return {}  # No notifications from this sender

            anchor = last_activity

        # Calculate window start
        window_start = anchor - timedelta( hours=window_hours )

        # Build query
        query = self.session.query( Notification ).filter(
            Notification.sender_id == sender_id,
            Notification.recipient_id == recipient_id,
            Notification.created_at >= window_start,
            Notification.created_at <= anchor
        )

        # Filter hidden unless explicitly requested
        if not include_hidden:
            query = query.filter( Notification.is_hidden == False )

        notifications = query.order_by( Notification.created_at.asc() ).all()

        # Group by date in specified timezone
        try:
            tz = zoneinfo.ZoneInfo( timezone_name )
        except Exception:
            tz = zoneinfo.ZoneInfo( "America/New_York" )  # Fallback

        date_groups: Dict[str, List[Notification]] = {}
        for notif in notifications:
            # Convert to local timezone and extract date
            local_time = notif.created_at.astimezone( tz )
            date_key = local_time.strftime( "%Y-%m-%d" )

            if date_key not in date_groups:
                date_groups[ date_key ] = []
            date_groups[ date_key ].append( notif )

        # Sort dates descending (newest first)
        return dict( sorted( date_groups.items(), reverse=True ) )

    def soft_delete_by_date(
        self,
        sender_id: str,
        recipient_id: uuid.UUID,
        date_string: str,
        timezone_name: str = "America/New_York"
    ) -> int:
        """
        Soft delete all notifications for a sender on a specific date.

        Requires:
            - sender_id: Sender identifier (e.g., claude.code@lupin.deepily.ai)
            - recipient_id: Valid user UUID
            - date_string: ISO format date (YYYY-MM-DD)
            - timezone_name: IANA timezone for date interpretation

        Ensures:
            - Sets is_hidden=True for all matching notifications
            - Uses timezone-aware date boundaries
            - Returns count of hidden notifications

        Returns:
            Number of notifications hidden

        Example:
            with get_db() as session:
                repo = NotificationRepository( session )
                count = repo.soft_delete_by_date(
                    sender_id    = "claude.code@lupin.deepily.ai",
                    recipient_id = user.id,
                    date_string  = "2025-01-01"
                )
                print( f"Hidden {count} notifications" )
        """
        import zoneinfo
        from datetime import date

        try:
            tz = zoneinfo.ZoneInfo( timezone_name )
        except Exception:
            tz = zoneinfo.ZoneInfo( "America/New_York" )  # Fallback

        # Parse date string and create timezone-aware boundaries
        target_date = date.fromisoformat( date_string )
        day_start = datetime( target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tz )
        day_end = datetime( target_date.year, target_date.month, target_date.day, 23, 59, 59, 999999, tzinfo=tz )

        # Update matching notifications to hidden
        updated = self.session.query( Notification ).filter(
            Notification.sender_id == sender_id,
            Notification.recipient_id == recipient_id,
            Notification.created_at >= day_start,
            Notification.created_at <= day_end,
            Notification.is_hidden == False  # Only hide visible ones
        ).update( { "is_hidden": True }, synchronize_session="fetch" )

        self.session.flush()
        return updated

    def get_sender_date_summaries(
        self,
        sender_id: str,
        recipient_id: uuid.UUID,
        include_hidden: bool = False,
        timezone_name: str = "America/New_York"
    ) -> List[Dict]:
        """
        Get date-grouped summaries for a sender with counts.

        Requires:
            - sender_id: Sender identifier
            - recipient_id: Valid user UUID
            - include_hidden: Whether to include hidden notifications
            - timezone_name: IANA timezone for date grouping

        Ensures:
            - Returns list of date summaries ordered by date descending
            - Each summary includes date, count, and new_count

        Returns:
            List of date summary dicts

        Example:
            summaries = repo.get_sender_date_summaries(
                sender_id    = "claude.code@lupin.deepily.ai",
                recipient_id = user.id
            )
            # [{"date": "2025-01-01", "count": 5, "new_count": 2}, ...]
        """
        import zoneinfo

        try:
            tz = zoneinfo.ZoneInfo( timezone_name )
        except Exception:
            tz = zoneinfo.ZoneInfo( "America/New_York" )  # Fallback

        # Build query
        query = self.session.query( Notification ).filter(
            Notification.sender_id == sender_id,
            Notification.recipient_id == recipient_id
        )

        if not include_hidden:
            query = query.filter( Notification.is_hidden == False )

        notifications = query.order_by( Notification.created_at.desc() ).all()

        # Group by date and calculate counts
        date_counts: Dict[str, Dict] = {}
        for notif in notifications:
            local_time = notif.created_at.astimezone( tz )
            date_key = local_time.strftime( "%Y-%m-%d" )

            if date_key not in date_counts:
                date_counts[ date_key ] = { "count": 0, "new_count": 0 }

            date_counts[ date_key ][ "count" ] += 1

            # Count "new" as notifications not yet delivered/responded
            if notif.state in [ "created", "queued" ]:
                date_counts[ date_key ][ "new_count" ] += 1

        # Convert to sorted list (newest first)
        return [
            { "date": date_key, **counts }
            for date_key, counts in sorted( date_counts.items(), reverse=True )
        ]

    def get_sender_last_activities_visible(
        self,
        recipient_id: uuid.UUID,
        include_hidden: bool = False,
        exclude_job_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get last activity timestamp per sender for a recipient (excluding hidden).

        Requires:
            - recipient_id: Valid user UUID
            - include_hidden: Whether to include hidden notifications in counts
            - exclude_job_ids: Optional list of job IDs to exclude (for "not mine" filtering)

        Ensures:
            - Returns list of {sender_id, last_activity, notification_count, new_count}
            - Excludes senders with all notifications hidden (unless include_hidden)
            - When exclude_job_ids provided, excludes notifications matching those job IDs
              AND notifications with NULL job_id (system/direct notifications are "mine")
            - Ordered by last_activity descending (most recent first)

        Returns:
            List of sender activity summaries
        """
        # Build base query
        query = self.session.query(
            Notification.sender_id,
            func.max( Notification.created_at ).label( 'last_activity' ),
            func.count( Notification.id ).label( 'notification_count' ),
            func.sum(
                case(
                    ( Notification.state.in_( [ 'created', 'queued' ] ), 1 ),
                    else_=0
                )
            ).label( 'new_count' )
        ).filter(
            Notification.recipient_id == recipient_id
        )

        if not include_hidden:
            query = query.filter( Notification.is_hidden == False )

        # "Not mine" filter: exclude user's own job notifications AND system notifications (NULL job_id)
        if exclude_job_ids is not None:
            query = query.filter(
                Notification.job_id.isnot( None ),
                ~Notification.job_id.in_( exclude_job_ids ) if exclude_job_ids else True
            )

        results = query.group_by(
            Notification.sender_id
        ).order_by(
            desc( func.max( Notification.created_at ) )
        ).all()

        return [
            {
                "sender_id"     : row.sender_id,
                "last_activity" : row.last_activity,
                "count"         : row.notification_count,
                "new_count"     : row.new_count or 0
            }
            for row in results
        ]

    def get_active_conversation( self, recipient_id: uuid.UUID ) -> Optional[ str ]:
        """
        Get the most recently active sender_id for a recipient.

        Requires:
            - recipient_id: Valid user UUID

        Ensures:
            - Returns the sender_id of the most recent notification
            - Returns None if no notifications exist
            - Used for voice response routing

        Args:
            recipient_id: User's UUID

        Returns:
            Most recent sender_id or None
        """
        result = self.session.query(
            Notification.sender_id
        ).filter(
            Notification.recipient_id == recipient_id,
            Notification.is_hidden == False
        ).order_by(
            desc( Notification.created_at )
        ).first()

        return result.sender_id if result else None

    def bulk_delete_by_user(
        self,
        user_email: str,
        recipient_id: uuid.UUID,
        hours: Optional[int] = None,
        exclude_job_ids: Optional[List[str]] = None
    ) -> int:
        """
        Delete all notifications for a user within the time window.

        Requires:
            - user_email: User's email address (for logging)
            - recipient_id: Valid user UUID
            - hours: Optional filter - only delete notifications within N hours (None = all)
            - exclude_job_ids: Optional list of job IDs to scope deletion to "not mine"
              When provided, only deletes notifications whose job_id is NOT in this list
              AND whose job_id is NOT NULL (system notifications are "mine", not deleted)

        Ensures:
            - All notifications matching filters are permanently deleted
            - Returns count of deleted notifications

        Returns:
            Number of notifications deleted

        Example:
            with get_db() as session:
                repo = NotificationRepository( session )
                count = repo.bulk_delete_by_user(
                    user_email   = "user@example.com",
                    recipient_id = user.id,
                    hours        = 168  # Last week
                )
                print( f"Deleted {count} notifications" )
        """
        from datetime import timezone

        # Build base query
        query = self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id
        )

        # Apply time filter if specified
        if hours is not None:
            cutoff = datetime.now( timezone.utc ) - timedelta( hours=hours )
            query = query.filter( Notification.created_at >= cutoff )

        # "Not mine" filter: only delete notifications NOT from user's own jobs
        if exclude_job_ids is not None:
            query = query.filter(
                Notification.job_id.isnot( None ),
                ~Notification.job_id.in_( exclude_job_ids ) if exclude_job_ids else True
            )

        # Count before deletion (for logging)
        count_before = query.count()

        # Delete matching notifications
        deleted = query.delete( synchronize_session="fetch" )

        self.session.flush()

        filter_label = " (not-mine filter active)" if exclude_job_ids is not None else ""
        print( f"[NOTIFY] Bulk deleted {deleted} notifications for {user_email} (hours filter: {hours}){filter_label}" )

        return deleted

    def get_sessions_for_project( self, recipient_id: uuid.UUID, project: str ) -> List[ Dict ]:
        """
        Get all unique session_ids for a project with activity info.

        Requires:
            - recipient_id: Valid user UUID
            - project: Project name (e.g., "lupin")

        Ensures:
            - Returns list of session dicts with activity info
            - Includes is_active indicator (most recent sender globally)
            - Ordered by last_activity descending

        Args:
            recipient_id: User's UUID
            project: Project name (lowercase)

        Returns:
            List of session summaries: [{ session_id, sender_id, last_activity, count, is_active }]
        """
        from lupin_cli.notifications.notification_models import parse_sender_id

        # Get all sender activities for this user
        all_activities = self.get_sender_last_activities_visible( recipient_id )

        # Get the globally active sender
        active_sender = self.get_active_conversation( recipient_id )

        # Filter to requested project and parse session_ids
        project_sessions = []
        for activity in all_activities:
            parsed = parse_sender_id( activity[ "sender_id" ] )
            if parsed[ "project" ] == project:
                project_sessions.append( {
                    "session_id"    : parsed[ "session_id" ],
                    "sender_id"     : activity[ "sender_id" ],
                    "last_activity" : activity[ "last_activity" ],
                    "count"         : activity[ "count" ],
                    "new_count"     : activity.get( "new_count", 0 ),
                    "is_active"     : activity[ "sender_id" ] == active_sender
                } )

        return project_sessions


def quick_smoke_test():
    """
    Quick smoke test for NotificationRepository - validates CRUD and sender operations.
    """
    import cosa.utils.util as cu

    cu.print_banner( "NotificationRepository Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module imports
        print( "Testing module imports..." )
        from cosa.rest.db.database import get_db
        from cosa.rest.postgres_models import Notification, User
        print( "✓ Imports successful" )

        # Test 2: Repository instantiation
        print( "Testing repository instantiation..." )
        with get_db() as session:
            repo = NotificationRepository( session )
            assert repo is not None
            assert repo.model == Notification
            print( "✓ Repository instantiated correctly" )

        # Test 3: Check repository methods exist
        print( "Testing repository methods..." )
        methods = [
            'create_notification', 'get_by_recipient', 'get_sender_last_activities',
            'get_sender_conversation', 'update_state', 'update_response',
            'get_pending_for_recipient', 'get_expired_notifications', 'mark_expired', 'count_by_sender'
        ]
        for method in methods:
            assert hasattr( NotificationRepository, method ), f"Missing method: {method}"
        print( f"✓ All {len( methods )} repository methods defined" )

        # Test 4: Test with actual database (if available)
        print( "Testing database operations..." )
        try:
            with get_db() as session:
                repo = NotificationRepository( session )

                # Check if we have any users to test with
                user = session.query( User ).first()
                if user:
                    # Test get_sender_last_activities (should work even with no data)
                    activities = repo.get_sender_last_activities( user.id )
                    print( f"  Found {len( activities )} sender(s) for user {user.email}" )

                    # Test count_by_sender
                    counts = repo.count_by_sender( user.id )
                    print( f"  Sender counts: {counts}" )

                    print( "✓ Database operations successful" )
                else:
                    print( "  ⚠ No users found for testing (this is OK for new databases)" )

        except Exception as db_error:
            print( f"  ⚠ Database test skipped: {db_error}" )
            print( "  (This is OK if database is not running)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
