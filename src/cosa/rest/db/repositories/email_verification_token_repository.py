"""
Email verification token repository for user email confirmation.

Provides token management for email verification workflow.
"""

from typing import Optional
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import EmailVerificationToken
from cosa.rest.db.repositories.base import BaseRepository


class EmailVerificationTokenRepository(BaseRepository[EmailVerificationToken]):
    """
    Repository for EmailVerificationToken model.

    Extends BaseRepository with email verification-specific methods:
        - Token-based lookup
        - Token marking as used
        - Expired token cleanup
    """

    def __init__( self, session: Session ):
        """
        Initialize EmailVerificationTokenRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                token_repo = EmailVerificationTokenRepository( session )
                token = token_repo.get_by_token( token_string )
        """
        super().__init__( EmailVerificationToken, session )

    def create_token( self, token: str, user_id: uuid.UUID, expires_hours: int = 24 ) -> EmailVerificationToken:
        """
        Create new email verification token.

        Requires:
            - token: Unique token string (random URL-safe string)
            - user_id: User UUID this token is for
            - expires_hours: Token validity period in hours (default: 24)

        Ensures:
            - Token created with used = False
            - expires_at set to current time + expires_hours
            - created_at set automatically

        Returns:
            Created EmailVerificationToken instance

        Example:
            token = token_repo.create_token(
                token = secrets.token_urlsafe( 32 ),
                user_id = user.id,
                expires_hours = 24
            )
        """
        return self.create(
            token = token,
            user_id = user_id,
            expires_at = datetime.now( timezone.utc ) + timedelta( hours=expires_hours ),
            used = False
        )

    def get_by_token( self, token: str ) -> Optional[EmailVerificationToken]:
        """
        Get email verification token by token string.

        Requires:
            - token: Token string to lookup

        Ensures:
            - Returns token if found
            - Returns None if not found

        Returns:
            EmailVerificationToken instance or None
        """
        return self.session.query( EmailVerificationToken ).filter(
            EmailVerificationToken.token == token
        ).first()

    def mark_used( self, token: str ) -> bool:
        """
        Mark email verification token as used.

        Requires:
            - token: Token string to mark as used

        Ensures:
            - used set to True
            - Token can no longer be reused

        Returns:
            True if marked, False if token not found

        Example:
            # User clicked verification link
            if token_repo.mark_used( token_string ):
                # Mark user email as verified
                user_repo.mark_email_verified( user_id )
        """
        token_obj = self.get_by_token( token )
        if token_obj:
            token_obj.used = True
            self.session.flush()
            return True
        return False

    def is_valid( self, token: str ) -> bool:
        """
        Check if email verification token is valid (exists, not used, not expired).

        Requires:
            - token: Token string to check

        Ensures:
            - Token exists
            - used = False
            - expires_at > now (not expired)

        Returns:
            True if token is valid, False otherwise

        Example:
            if token_repo.is_valid( token_string ):
                # Token can be used for verification
            else:
                # Token is invalid, used, or expired
        """
        token_obj = self.get_by_token( token )
        if not token_obj:
            return False

        if token_obj.used:
            return False

        if token_obj.expires_at < datetime.now( timezone.utc ):
            return False

        return True

    def cleanup_expired( self ) -> int:
        """
        Delete expired and used email verification tokens.

        Ensures:
            - Expired tokens (expires_at < now) are deleted
            - Used tokens are deleted
            - Active unused tokens are preserved

        Returns:
            Number of tokens deleted

        Example:
            # Cleanup expired/used tokens (run daily via cron)
            deleted = token_repo.cleanup_expired()
        """
        cutoff_date = datetime.now( timezone.utc )

        # Delete expired tokens OR used tokens
        result = self.session.query( EmailVerificationToken ).filter(
            ( EmailVerificationToken.expires_at < cutoff_date ) |
            ( EmailVerificationToken.used == True )
        ).delete( synchronize_session=False )

        self.session.flush()
        return result
