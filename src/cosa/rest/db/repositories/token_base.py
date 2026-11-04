"""
Shared behaviour of the token repositories.

The email verification, password reset and refresh token repositories each store a token row with an expiry and
a one-way flag (`used` or `revoked`). They repeat the same live check, the same expired-or-flagged cleanup and,
for the first two, the same creation call. Each keeps its own public method names and passes its own flag.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from cosa.rest.db.repositories.base import BaseRepository, ModelType


class TokenRepositoryBase( BaseRepository[ModelType] ):
    """
    Base for repositories of expiring, single-use token rows.

    Requires:
        - the model has `expires_at` and one boolean flag column
        - a subclass that uses create_token sets default_expires_hours

    Ensures:
        - _is_live and _delete_expired_or behave the same for every token table
    """

    # Set by the subclass whose tokens are created through create_token. RefreshTokenRepository replaces
    # create_token, because its tokens carry a jti and a hash, and leaves this unset.
    default_expires_hours = None

    def create_token( self, token: str, user_id: uuid.UUID, expires_hours: Optional[ int ] = None ) -> ModelType:
        """
        Create a token row that expires after expires_hours.

        Requires:
            - token: unique token string
            - user_id: UUID of the user the token is for
            - expires_hours: validity in hours; None means the class's default_expires_hours

        Ensures:
            - the row is created with used = False
            - expires_at is the current time plus the hours

        Returns:
            The created model instance
        """
        hours = self.default_expires_hours if expires_hours is None else expires_hours
        return self.create(
            token = token,
            user_id = user_id,
            expires_at = datetime.now( timezone.utc ) + timedelta( hours=hours ),
            used = False
        )

    def _is_live( self, token_obj: Optional[ ModelType ], flag_attr: str ) -> bool:
        """
        Say whether a looked-up token row exists, has its flag clear and has not expired.

        Requires:
            - token_obj is the looked-up row or None
            - flag_attr names the row's boolean flag attribute ("used" or "revoked")

        Ensures:
            - returns False for no row, a set flag, or expires_at before now
            - returns True otherwise
        """
        if not token_obj:
            return False

        if getattr( token_obj, flag_attr ):
            return False

        if token_obj.expires_at < datetime.now( timezone.utc ):
            return False

        return True

    def _delete_expired_or( self, flag_column ) -> int:
        """
        Delete the rows that are past expires_at or have the flag column true.

        Requires:
            - flag_column is the model's boolean column ( for example EmailVerificationToken.used )

        Ensures:
            - rows with expires_at before now, or the flag true, are deleted; other rows are kept
            - the session is flushed
            - returns the number of rows deleted
        """
        cutoff_date = datetime.now( timezone.utc )

        result = self.session.query( self.model ).filter(
            ( self.model.expires_at < cutoff_date ) |
            ( flag_column == True )
        ).delete( synchronize_session=False )

        self.session.flush()
        return result
