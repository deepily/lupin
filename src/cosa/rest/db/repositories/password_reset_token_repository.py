"""
Password reset token repository for password recovery workflow.

Provides token management for password reset operations.
"""

from typing import Optional

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import PasswordResetToken
from cosa.rest.db.repositories.token_base import TokenRepositoryBase


class PasswordResetTokenRepository(TokenRepositoryBase[PasswordResetToken]):
    """
    Repository for PasswordResetToken model.

    Extends TokenRepositoryBase with password reset-specific methods:
        - Token-based lookup
        - Token marking as used
        - Expired token cleanup
    """

    default_expires_hours = 1

    def __init__( self, session: Session ):
        """
        Initialize PasswordResetTokenRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                token_repo = PasswordResetTokenRepository( session )
                token = token_repo.get_by_token( token_string )
        """
        super().__init__( PasswordResetToken, session )

    def get_by_token( self, token: str ) -> Optional[PasswordResetToken]:
        """
        Get password reset token by token string.

        Requires:
            - token: Token string to lookup

        Ensures:
            - Returns token if found
            - Returns None if not found

        Returns:
            PasswordResetToken instance or None
        """
        return self.session.query( PasswordResetToken ).filter(
            PasswordResetToken.token == token
        ).first()

    def mark_used( self, token: str ) -> bool:
        """
        Mark password reset token as used.

        Requires:
            - token: Token string to mark as used

        Ensures:
            - used set to True
            - Token can no longer be reused

        Returns:
            True if marked, False if token not found

        Example:
            # User reset password successfully
            if token_repo.mark_used( token_string ):
                # Password reset complete
        """
        return self._set_flag( self.get_by_token( token ), "used", True )

    def is_valid( self, token: str ) -> bool:
        """
        Check if password reset token is valid (exists, not used, not expired).

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
                # Token can be used for password reset
            else:
                # Token is invalid, used, or expired
        """
        return self._is_live( self.get_by_token( token ), "used" )

    def cleanup_expired( self ) -> int:
        """
        Delete expired and used password reset tokens.

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
        return self._delete_expired_or( PasswordResetToken.used )
