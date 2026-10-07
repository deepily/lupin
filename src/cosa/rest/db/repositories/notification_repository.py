"""
Notification repository for CRUD operations on Notification model.

Provides notification-specific methods beyond base repository functionality,
including sender-based grouping and activity-anchored window loading.
"""

from typing import Optional, List, Dict
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.orm import Session, aliased
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

    # The `type` value every saved broadcast-ack row carries (row 4f320c27). Declared
    # HERE, where the query that reads it lives, and imported by the watcher that
    # writes it — one string, one definition, so the writer and the reader cannot
    # disagree about what an ack row looks like.
    #
    # ⚠️ TWO SQL LITERALS ALSO SPELL IT and cannot import a Python name: the partial
    # index predicate in migration 9184990becdf and the mirroring ORM `Index` in
    # postgres_models.py. Change this and you must change both, or the index silently
    # stops covering the query.
    BROADCAST_ACK_TYPE = "commons_broadcast_ack"

    # Types that are RECORDS, not conversations. A broadcast ack is a tally element
    # addressed to the broadcaster: it has no message body, nobody replies to it, and
    # reading it is what get_latest_acks_for_broadcast is for.
    #
    # 🔴 ONE PREDICATE, SIX QUERIES — the ROSTER reads AND the CONVERSATION reads. The
    # first cut (b9136bcf) excluded acks from the two rosters only, and that was a
    # defect: saving acks put a new row TYPE into a table the conversation reads also
    # walk, so `/api/notifications/active-conversation` began answering with a seat
    # that had merely ACKED, and the history hydration gained date buckets that existed
    # for no other reason. Measured on a throwaway Postgres 2026-09-23 with exactly one
    # saved ack; see src/tests/smoke/test_acks_are_not_conversations.py.
    #
    # NOTHING SURFACED IT, because the multiplexer's normalizeHistoryRow drops an
    # empty-message row at RENDER: the rows were invisible while the counts, the date
    # buckets and the active-conversation pick were all silently wrong.
    #
    # DELIBERATELY NOT APPLIED to count_by_sender or get_by_recipient. Both also return
    # acks, and neither has a caller outside tests — excluding there would be churn in
    # code nothing reads, and an enumeration of call sites is not a predicate.
    #
    # 🔴 THE ROSTER GROUPS BY sender_id AND FILTERS ON NOTHING ELSE, so any row saved
    # into this table becomes a SENDER. Measured 2026-09-23 on a throwaway Postgres —
    # one saved ack, no other notifications — and both roster queries returned it as a
    # live sender with count=1. The multiplexer's strip and sender records hydrate from
    # /api/notifications/senders-visible, so the seat would have appeared in the
    # operator's focus bar purely for having acked a broadcast.
    #
    # This exclusion is correct INDEPENDENTLY of what sender_id an ack carries: even a
    # perfectly attributed ack would inflate that seat's notification_count and drag its
    # last_activity forward, which is a tally element wearing a message's clothes.
    # Raised by Mr. Radio 🦉 on review, 2026-09-23.
    NON_CONVERSATION_TYPES = ( BROADCAST_ACK_TYPE, )

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
        thread_id: Optional[str] = None,
        payload: Optional[dict] = None
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
            - payload stored verbatim when provided, NULL otherwise — the structured
              side-channel a broadcast ack's identity rides in

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
            payload            = payload,
            state              = "created"
        )

    def find_live_unpark_card( self, task_id: uuid.UUID, parked_since: datetime, now: datetime ) -> Optional[Notification]:
        """
        The newest un-park card for this row and this park that is still waiting for an answer.

        Requires:
            - task_id is the parked row; parked_since is when it was parked; now is aware

        Ensures:
            - matches only a card whose server-written payload names this row, made after the park
            - a card is live while it asked a question, is created or delivered, and has not expired
            - an answered, expired or older-park card is not returned
            - returns None when there is none
        """
        return self.session.query( Notification ).filter(
            Notification.payload[ "kind" ].astext    == "unpark_ask",
            Notification.payload[ "task_id" ].astext == str( task_id ),
            Notification.created_at                  >  parked_since,
            Notification.response_requested.is_( True ),
            Notification.state.in_( ( "created", "delivered" ) ),
            Notification.expires_at                  >  now,
        ).order_by( desc( Notification.created_at ) ).first()

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

    def get_dm_thread(
        self,
        thread_id: str,
        recipient_id: uuid.UUID,
        since: Optional[datetime] = None,
        limit: int = 200,
        recipient_session: Optional[str] = None
    ) -> List[Notification]:
        """
        Load one peer-DM conversation thread, oldest first (the `/api/dm/list?thread_id=` read).

        A peer DM has direction='ai_to_ai' and a `thread_id` shared by every message in a conversation.
        `recipient_id` is the sender's own account, not an addressee; `recipient_session` is the addressee filter.

        Requires:
            - thread_id: the conversation id (Notification.thread_id)
            - recipient_id: Valid user UUID (same-user scoping — peer DMs land on the
              sender's own user, so this is always the authenticated user's uuid)
            - since: None (whole thread) or a datetime (only created_at > since)
            - limit: positive int cap on rows returned
            - recipient_session: None (whole thread as before) or an 8-char session
              hash restricting rows to those addressed to that session

        Ensures:
            - returns ai_to_ai, non-hidden rows for this thread + recipient
            - when recipient_session is given, only rows whose job_id equals it
            - when recipient_session is None, behavior is unchanged (account-wide)
            - when since is set, only rows strictly newer than `since`
            - ordered by created_at ascending (oldest first — conversation order)
            - honors limit

        Returns:
            List of Notification instances in chronological order
        """
        query = self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id,
            Notification.thread_id    == thread_id,
            Notification.direction    == "ai_to_ai",
            Notification.is_hidden    == False
        )
        if recipient_session is not None:
            query = query.filter( Notification.job_id == recipient_session )
        if since is not None:
            query = query.filter( Notification.created_at > since )
        return query.order_by(
            Notification.created_at.asc()
        ).limit( limit ).all()

    def get_dm_inbox(
        self,
        recipient_id: uuid.UUID,
        since: Optional[datetime] = None,
        limit: int = 50,
        recipient_session: Optional[str] = None
    ) -> List[Notification]:
        """
        Load the peer-DM inbox, newest first (the `/api/dm/list` no-thread read and poll).

        `recipient_id` scopes to a service account, not an addressee: routers/dm.py stores every DM under the sender's own
        account, so one pool holds the whole fleet. Only `recipient_session` narrows, by matching `job_id`.

        Requires:
            - recipient_id: Valid user UUID (same-account scoping, see above)
            - since: None (whole inbox) or a datetime (only created_at > since)
            - limit: positive int cap on rows returned
            - recipient_session: None (account-wide, the legacy behavior) or an 8-char
              session hash restricting rows to those addressed to it. `job_id` holds a recipient session only for
              direction 'ai_to_ai', so never reuse this filter without that clause. It is cut to 8 characters, so it is
              a prefix match and two sessions sharing 8 hex characters are indistinguishable, an accepted limit

        Ensures:
            - returns ai_to_ai, non-hidden rows for this account
            - when recipient_session is given, only rows whose job_id equals it
            - when recipient_session is None, behavior is unchanged (account-wide),
              which is what keeps the existing client-side-filtering hook working
            - when since is set, only rows strictly newer than `since`
            - ordered by created_at descending (newest first — inbox order)
            - honors limit

        Returns:
            List of Notification instances, newest first
        """
        query = self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id,
            Notification.direction    == "ai_to_ai",
            Notification.is_hidden    == False
        )
        if recipient_session is not None:
            query = query.filter( Notification.job_id == recipient_session )
        if since is not None:
            query = query.filter( Notification.created_at > since )
        return query.order_by(
            desc( Notification.created_at )
        ).limit( limit ).all()

    def get_sender_last_activities( self, recipient_id: uuid.UUID ) -> List[Dict]:
        """
        Get last activity timestamp per sender for a recipient.

        Requires:
            - recipient_id: Valid user UUID

        Ensures:
            - Returns list of {sender_id, last_activity, notification_count}
            - Excludes NON_CONVERSATION_TYPES, so a seat never appears as a sender
              purely for having acked a broadcast
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
            Notification.recipient_id == recipient_id,
            Notification.type.notin_( self.NON_CONVERSATION_TYPES )
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
                Notification.recipient_id == recipient_id,
                Notification.type.notin_( self.NON_CONVERSATION_TYPES )
            ).scalar()

            if last_activity is None:
                return []  # No notifications from this sender

            anchor = last_activity

        # Calculate window start
        window_start = anchor - timedelta( hours=window_hours )

        return self.session.query( Notification ).filter(
            Notification.sender_id == sender_id,
            Notification.recipient_id == recipient_id,
            Notification.type.notin_( self.NON_CONVERSATION_TYPES ),
            Notification.created_at >= window_start,
            Notification.created_at <= anchor
        ).order_by(
            Notification.created_at.asc()  # Oldest first - insertBefore prepends newest to top
        ).all()

    def update_state( self, notification_id: uuid.UUID, new_state: str ) -> Optional[Notification]:
        """
        Set the state of one notification to a new value.

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

        # Update appropriate timestamp based on state.
        # AWARE, not utcnow(): delivered_at / responded_at are TIMESTAMPTZ
        # (postgres_models.py:600/604), and Postgres reads a NAIVE value in the
        # session's TimeZone GUC — so under a non-UTC session the stored instant
        # is shifted by the offset. Measured at exactly 14400s under
        # America/New_York before this changed (row 3b4002fe).
        now = datetime.now( timezone.utc )
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
        # AWARE — same TIMESTAMPTZ reason as update_state above (row 3b4002fe).
        notification.responded_at = datetime.now( timezone.utc )
        notification.state = "responded"

        self.session.flush()
        return notification

    def mark_answer_delivered( self, notification_id: uuid.UUID ) -> Optional[Notification]:
        """
        Stamp the late-answer handback mark (answer_delivered_at) on a notification.

        The only writer of answer_delivered_at, called by the receipt-gated setters: the live SSE waiter being woken,
        the pull endpoint's ack-on-consume and a re-attach landing. Never call it on a send, an emit attempt or merely serving a row.
        Those leave the mark NULL, so the row stays owed and catch-up re-delivers it.

        Requires:
            - notification_id: Valid notification UUID

        Ensures:
            - answer_delivered_at set to now() (idempotent — re-stamping is harmless)
            - the row is otherwise untouched (never deleted; state unchanged)

        Returns:
            Updated Notification instance, or None if not found
        """
        notification = self.get_by_id( notification_id )
        if not notification:
            return None

        # tz-AWARE to match the TIMESTAMPTZ column (Rachel, real-DB D-tier): a naive
        # utcnow() coerces but stores a naive value inconsistent with responded_at /
        # created_at. This is the one reader-critical timestamp, so keep it aware.
        notification.answer_delivered_at = datetime.now( timezone.utc )
        self.session.flush()
        return notification

    def get_answers_owed_for_persona(
        self, sender_persona: str, limit: int = 100,
        max_age_hours: Optional[int] = None, since: Optional[datetime] = None
    ) -> List[Notification]:
        """
        Get the answers owed to a persona: answered asks not yet handed back to it.

        The only reader of answer_delivered_at. The owed predicate has three terms: response_requested, `responded_at` not NULL,
        `answer_delivered_at` NULL. The `responded_at` term is an invariant. An offline or expired persist carries a machine
        default with `responded_at` NULL and must never be served as an owed answer. The predicate is spelled out in full. It uses the same three terms, in the same words, as the ORM partial index in postgres_models.py and the concurrent migration. That coupling is why it is stated here. Retrieval matches on sender_persona alone.

        Requires:
            - sender_persona: a non-empty persona key (never None — a persona-less
              ask stamps NULL and is unretrievable by persona, the accepted gap)
            - max_age_hours: None (no cap) or a positive int (hours), on created_at
            - since: None or a responded_at cursor; only rows answered after it

        Ensures:
            - Returns rows matching the three-term owed predicate for this persona
            - Ordered by responded_at ascending (oldest answer first); honors limit.
              Order and cursor use responded_at, not created_at, so an old ask answered just now is not stranded behind the cursor

        Returns:
            List of owed Notification instances
        """
        query = self.session.query( Notification ).filter(
            Notification.sender_persona == sender_persona,
            Notification.response_requested == True,
            Notification.responded_at.isnot( None ),
            Notification.answer_delivered_at.is_( None )
        )
        if max_age_hours is not None:
            cutoff = datetime.now( timezone.utc ) - timedelta( hours=max_age_hours )
            query  = query.filter( Notification.created_at >= cutoff )
        if since is not None:
            query = query.filter( Notification.responded_at > since )
        return query.order_by(
            Notification.responded_at.asc()
        ).limit( limit ).all()

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
        Get the recipient's undelivered notifications (the pull-able AFK inbox), oldest first.

        A notification still in 'created' or 'queued' never reached the user, who missed it while offline.
        `max_age_hours` stops stale rows replaying as a TTS storm on reconnect. When set,
        only rows newer than the cutoff are returned, including rows that go stale while undelivered.

        Requires:
            - recipient_id: Valid user UUID
            - max_age_hours: None (no age cap) or a positive int (hours)

        Ensures:
            - Returns notifications with state in ('created', 'queued') only
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

    def get_latest_acks_for_broadcast(
        self,
        recipient_id : uuid.UUID,
        broadcast_id : str,
        limit        : int = 500
    ) -> List[Notification]:
        """
        Get the saved acks for one broadcast and one recipient, the latest per acking session.

        Delivery state is ignored here. An ack that landed while a browser was open is already marked delivered.
        The undelivered inbox could therefore not rebuild the tally. There is no ack table; this reads the saved `notifications` rows.
        The latest-wins fold is in Python, not `DISTINCT ON`. That would push the fold into Postgres but bind the method to one dialect. A seat can ack twice, and the set is only dozens of rows.

        Requires:
            - recipient_id: the broadcast originator's user UUID (the authorization
              scope — an ack is readable only by the account it was addressed to)
            - broadcast_id: the broadcast's id as written into payload['broadcast_id']
            - limit: positive int cap on the pre-fold row scan

        Ensures:
            - returns only rows of type 'commons_broadcast_ack' for this recipient
              whose payload['broadcast_id'] matches, whatever their state
            - excludes soft-deleted/archived rows (is_hidden = True)
            - at most one row per payload['session_id'], the newest by created_at
            - a row whose payload carries no session_id is keyed by its own id, so it
              is returned rather than silently collapsed with every other such row
            - ordered newest-first
            - honors limit on the scan, so the fold can only ever shrink the result

        Returns:
            List of Notification instances, one per acking session, newest first
        """
        rows = self.session.query( Notification ).filter(
            Notification.recipient_id == recipient_id,
            Notification.type         == self.BROADCAST_ACK_TYPE,
            Notification.is_hidden    == False,
            Notification.payload[ "broadcast_id" ].astext == broadcast_id
        ).order_by(
            desc( Notification.created_at )
        ).limit( limit ).all()

        latest_per_session = { }
        for row in rows:
            payload    = row.payload or { }
            session_id = payload.get( "session_id" ) or f"__no_session__{row.id}"
            # rows arrive newest-first, so the FIRST sighting of a session is its latest
            if session_id not in latest_per_session:
                latest_per_session[ session_id ] = row
        return list( latest_per_session.values() )

    def count_undelivered_for_recipient( self, recipient_id: uuid.UUID, max_age_hours: Optional[int] = None ) -> int:
        """
        Count the recipient's undelivered notifications (lever D, an accurate "N missed" figure).

        Unlike `get_undelivered_for_recipient`, which caps at `limit` for paging, this count is unbounded, so the
        "N missed" figure is not capped at the page size. The `max_age_hours` cap mirrors the getter, so the count
        matches what is actually pullable and never includes stale rows the getter would skip.

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
        Soft-dismiss the recipient's undelivered notifications (the "reset missed" action).

        Sets is_hidden=True on every row the "N missed while away" badge counts. The notification state is left untouched, keeping the audit trail that these rows were never delivered. The dismiss is reversible: flip is_hidden back. The filter mirrors
        count_undelivered_for_recipient, so afterwards that count is 0 for the same recipient and cap.

        Requires:
            - recipient_id: Valid user UUID
            - max_age_hours: None (dismiss all undelivered) or a positive int (hours)

        Ensures:
            - sets is_hidden=True on rows in state 'created'/'queued', is_hidden=False
            - When max_age_hours is set, only rows newer than the cutoff are dismissed
              (matches the windowed badge — older rows already fall out of the count)
            - does not change notification state (audit trail preserved)
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
            - Returns notifications where state='delivered' and expires_at < now
            - Only includes notifications with non-null expires_at
            - Ordered by expires_at ascending (oldest expiration first)

        Returns:
            List of expired Notification instances
        """
        # AWARE — this `now` is compared against the TIMESTAMPTZ expires_at
        # column. Naive on BOTH sides used to cancel out when the write and the
        # sweep shared a session; it did not when they differed, and a row that
        # had expired was simply never swept. Fixed together with the writer at
        # routers/notifications.py (row 3b4002fe).
        now = datetime.now( timezone.utc )
        return self.session.query( Notification ).filter(
            Notification.state == 'delivered',
            Notification.expires_at.isnot( None ),
            Notification.expires_at < now
        ).order_by(
            Notification.expires_at.asc()
        ).all()

    def mark_expired(
        self,
        notification_id: uuid.UUID,
        apply_default  : bool          = True,
        expected_state : Optional[str] = None
    ) -> Optional[Notification]:
        """
        Mark a notification as expired because its timeout was reached.

        `apply_default` is False on the orphan-sweeper path: nobody waits, so a stamped default would claim an answer reached someone.
        `expected_state` is checked in the `UPDATE`'s `WHERE` clause, not by an `if`: a re-read is served stale from the session identity map.
        Only the committed row can refuse the write, so a human answer landing between read and write is never overwritten.

        Requires:
            - notification_id: Valid notification UUID
            - apply_default: whether to stamp response_default as the answer
            - expected_state: the state the committed row must still be in for
              this write to happen at all, or None to write unconditionally

        Ensures:
            - state set to 'expired'
            - when expected_state is not None, the write happens only if the
              committed row is still in that state; otherwise nothing is
              written and None is returned
            - applies response_default as a "timeout_default" response_value
              when apply_default is True (the default, so every pre-existing
              caller is unchanged) and a default is configured
            - writes no response_value when apply_default is False

        Test: src/tests/smoke/test_mark_expired_refuses_to_overwrite_a_live_answer.py

        Returns:
            Updated Notification instance, or None when the row does not exist or
            expected_state was given and the row had already moved on. A caller that
            must tell these apart asks the row. The sweeper counts both as not its to close.
        """
        if expected_state is not None:
            # synchronize_session="fetch" so an in-session ORM object's state
            # reflects the write. Without it a caller still holding the object
            # would keep reading the pre-update value.
            matched = self.session.query( Notification ).filter(
                Notification.id    == notification_id,
                Notification.state == expected_state
            ).update( { "state": "expired" }, synchronize_session="fetch" )

            if matched == 0:
                return None

            notification = self.get_by_id( notification_id )
            if not notification:
                return None
        else:
            notification = self.get_by_id( notification_id )
            if not notification:
                return None

            notification.state = "expired"

        # If default response was configured, apply it
        if apply_default and notification.response_default:
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
            - All notifications matching sender_id and recipient_id deleted
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
            - Date keys sorted descending (newest first)
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
                Notification.recipient_id == recipient_id,
                Notification.type.notin_( self.NON_CONVERSATION_TYPES )
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
            Notification.type.notin_( self.NON_CONVERSATION_TYPES ),
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
            Notification.recipient_id == recipient_id,
            Notification.type.notin_( self.NON_CONVERSATION_TYPES )
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
            - Excludes NON_CONVERSATION_TYPES, so a seat never appears in the operator
              focus bar purely for having acked a broadcast
            - Excludes senders with all notifications hidden (unless include_hidden)
            - When exclude_job_ids provided, excludes notifications matching those job IDs
              and notifications with NULL job_id (system/direct notifications are "mine")
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
            Notification.recipient_id == recipient_id,
            Notification.type.notin_( self.NON_CONVERSATION_TYPES )
        )

        if not include_hidden:
            query = query.filter( Notification.is_hidden == False )

        # "Not mine" filter: exclude user's own job notifications AND system notifications (NULL job_id)
        if exclude_job_ids is not None:
            query = query.filter(
                Notification.job_id.isnot( None ),
                ~Notification.job_id.in_( exclude_job_ids ) if exclude_job_ids else True
            )

        # Reaped-sender exclusion (bug ee59d5ed — durable, HISTORY-SAFE roster eviction).
        # A `session_reaped` state-update is persisted as a Notification row
        # (session_spawner._default_emit_reap POSTs it; /api/notify persist defaults
        # True). The operator focus bar (this roster query) must DURABLY drop a
        # reaped sender across a page refresh — but WITHOUT destroying its history.
        # is_hidden=True would over-hide: every history/conversation getter filters
        # is_hidden==False, so it is the user's clear-conversation soft-delete. So we
        # evict at the ROSTER query ONLY: exclude any sender_id that has >=1 persisted
        # `session_reaped` row for THIS recipient. Every history/conversation query is
        # untouched → full audit trail preserved. Shared by construction across both
        # reap paths (normal dismiss_sessions AND the orphan-bridge arbiter sweep both
        # emit the same persisted marker). Re-spawn-safe: sender_id carries the 8-hex
        # session suffix (…deepily.ai#<session8>), so a re-spawn is a NEW sender_id,
        # unaffected by a prior session's marker; a once-reaped sender_id stays excluded
        # (that session is dead). Collision window: a NEW live session reusing an
        # already-reaped 8-hex suffix is ~1/2**32 — negligible, accepted explicitly.
        # The type + sender_id + recipient_id single-column indexes back the subquery.
        # Correlated NOT EXISTS (null-safe): NOT-IN would empty the whole roster if the
        # subquery ever yielded a NULL sender_id (SQL `x NOT IN (…, NULL)` → NULL → no
        # rows). sender_id is the NOT-NULL routing key so it is theoretical, but
        # NOT EXISTS is the robust idiom and degrades gracefully.
        reaped_marker = aliased( Notification )
        query = query.filter(
            ~self.session.query( reaped_marker ).filter(
                reaped_marker.sender_id   == Notification.sender_id,   # correlate to the outer row
                reaped_marker.recipient_id == recipient_id,
                reaped_marker.type         == "session_reaped",
            ).exists()
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
            Notification.type.notin_( self.NON_CONVERSATION_TYPES ),
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
              When provided, only deletes notifications whose job_id is not in this list
              and whose job_id is not NULL (system notifications are "mine", not deleted)

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
