"""
Email verification token repository for user email confirmation.

Provides token management for email verification workflow.
"""

from typing import Optional

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import EmailVerificationToken
from cosa.rest.db.repositories.token_base import TokenRepositoryBase


class EmailVerificationTokenRepository(TokenRepositoryBase[EmailVerificationToken]):
    """
    Repository for EmailVerificationToken model.

    Extends TokenRepositoryBase with email verification-specific methods:
        - Token-based lookup
        - Token marking as used
        - Expired token cleanup
    """

    default_expires_hours = 24

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
        return self._set_flag( self.get_by_token( token ), "used", True )

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
        return self._is_live( self.get_by_token( token ), "used" )

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
        return self._delete_expired_or( EmailVerificationToken.used )
