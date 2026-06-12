"""
FCM token repository for the mobile silent-relay wake channel (S6).

CRUD over the `fcm_tokens` table — the DURABLE registry the wake trigger
resolves device tokens from (F-S6-S2-1a: the registry must survive parent
restart; this repository reads the database on every call, never a
write-through cache, so a fresh instance rehydrates by construction — the
AC-S6.1 re-instantiate-from-store proof).
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from cosa.rest.postgres_models import FcmToken
from cosa.rest.db.repositories.base import BaseRepository


class FcmTokenRepository( BaseRepository[FcmToken] ):
    """
    Repository for FcmToken rows with upsert-on-token semantics (S6 §3.1).

    Usage:
        with get_db() as session:
            repo = FcmTokenRepository( session )
            repo.upsert_token( token="...", user_id="...", user_email="...", platform="android" )
    """

    def __init__( self, session: Session ):
        """
        Initialize FcmTokenRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Ensures:
            - BaseRepository is bound to the FcmToken model
        """
        super().__init__( FcmToken, session )

    def upsert_token( self, token: str, user_id: str, user_email: str, platform: str = "android" ) -> FcmToken:
        """
        Register a device token, updating the existing row when the token is known.

        Upsert is keyed on the TOKEN (S6 §3.1): a re-registration (mobile app
        login, onTokenRefresh, or WS-reconnect belt) refreshes the user binding
        and last_registered_at instead of duplicating the row. Multiple devices
        per user are allowed — each device has its own token, hence its own row.

        ATOMIC by construction (Rachel R3): a single PostgreSQL
        `INSERT .. ON CONFLICT (token) DO UPDATE` — a read-then-insert sequence
        would race when the same token registers concurrently (login +
        WS-reconnect belt firing together) and 500 on the unique constraint.

        Requires:
            - token is a non-empty FCM registration token string
            - user_id is the authenticated user's uid
            - user_email is the registering user's email (contract field, S6 §3.1)

        Ensures:
            - exactly one row exists for the token afterwards — even under
              concurrent same-token registration
            - the row's user_id/user_email/platform reflect THIS registration
            - last_registered_at is refreshed to now (UTC)
            - the statement is flushed; returns the persisted row

        Returns:
            The persisted FcmToken instance
        """
        statement = pg_insert( FcmToken ).values(
            token      = token,
            user_id    = user_id,
            user_email = user_email,
            platform   = platform
        ).on_conflict_do_update(
            index_elements = [ "token" ],
            set_           = {
                "user_id"            : user_id,
                "user_email"         : user_email,
                "platform"           : platform,
                "last_registered_at" : datetime.now( timezone.utc )
            }
        )
        self.session.execute( statement )
        self.session.flush()
        return self.session.query( FcmToken ).filter( FcmToken.token == token ).first()

    def delete_token( self, token: str ) -> bool:
        """
        Unregister a device token (best-effort logout path, S6 §3.1 amended).

        Requires:
            - token is a string (may be unknown)

        Ensures:
            - the row is deleted when present
            - returns True when a row was deleted, False when the token was unknown
              (idempotent — unregistering twice is not an error)

        Returns:
            bool — whether a registration was removed
        """
        deleted = self.session.query( FcmToken ).filter( FcmToken.token == token ).delete()
        self.session.flush()
        return deleted > 0

    def get_tokens_for_user( self, user_id: str ) -> List[str]:
        """
        Resolve all registered device tokens for a user (the wake-trigger lookup).

        Requires:
            - user_id is a string (may have no registrations)

        Ensures:
            - returns the token strings of every row bound to user_id
            - returns an empty list for unknown users (never None)
            - reads the DATABASE — never an in-memory cache — so a fresh
              repository instance resolves tokens registered before this
              process started (AC-S6.1 rehydration)

        Returns:
            List[str] of FCM token strings
        """
        rows = self.session.query( FcmToken.token ).filter( FcmToken.user_id == user_id ).all()
        return [ row.token for row in rows ]

    def get_by_token( self, token: str ) -> Optional[FcmToken]:
        """
        Fetch a registration row by its token string.

        Requires:
            - token is a string

        Ensures:
            - returns the FcmToken row or None when unknown

        Returns:
            Optional[FcmToken]
        """
        return self.session.query( FcmToken ).filter( FcmToken.token == token ).first()
