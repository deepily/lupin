"""
Refresh token repository for JWT refresh token management.

Provides token-specific operations for authentication sessions.
"""

from typing import Optional, List
from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import RefreshToken
from cosa.rest.db.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """
    Repository for RefreshToken model with JWT refresh token operations.

    Extends BaseRepository with refresh token-specific methods:
        - JTI-based lookup
        - User token management
        - Token revocation
        - Expired token cleanup
        - Last used tracking
    """

    def __init__( self, session: Session ):
        """
        Initialize RefreshTokenRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                token_repo = RefreshTokenRepository( session )
                token = token_repo.get_by_jti( jti )
        """
        super().__init__( RefreshToken, session )

    def create_token( self, jti: uuid.UUID, user_id: uuid.UUID, token_hash: str,
                     expires_at: datetime, user_agent: str, ip_address: str ) -> RefreshToken:
        """
        Create new refresh token.

        Requires:
            - jti: JWT ID (unique identifier for this token)
            - user_id: User UUID this token belongs to
            - token_hash: Hashed refresh token value
            - expires_at: Token expiration timestamp (UTC)
            - user_agent: Browser/client user agent string
            - ip_address: Client IP address

        Ensures:
            - Token created with revoked = False
            - created_at set automatically
            - Relationship to user established

        Returns:
            Created RefreshToken instance

        Example:
            token = token_repo.create_token(
                jti = uuid.uuid4(),
                user_id = user.id,
                token_hash = hashlib.sha256( token.encode() ).hexdigest(),
                expires_at = datetime.now( timezone.utc ) + timedelta( days=30 ),
                user_agent = request.headers.get( "User-Agent", "Unknown" ),
                ip_address = request.remote_addr
            )
        """
        return self.create(
            jti = jti,
            user_id = user_id,
            token_hash = token_hash,
            expires_at = expires_at,
            user_agent = user_agent,
            ip_address = ip_address,
            revoked = False
        )

    def get_by_jti( self, jti: uuid.UUID ) -> Optional[RefreshToken]:
        """
        Get refresh token by JWT ID.

        Requires:
            - jti: JWT ID (unique token identifier)

        Ensures:
            - Returns token if found
            - Returns None if not found

        Returns:
            RefreshToken instance or None
        """
        return self.session.query( RefreshToken ).filter(
            RefreshToken.jti == jti
        ).first()

    def get_by_user( self, user_id: uuid.UUID, include_revoked: bool = False ) -> List[RefreshToken]:
        """
        Get all refresh tokens for a user.

        Requires:
            - user_id: User UUID
            - include_revoked: Include revoked tokens (default: False)

        Ensures:
            - Returns active tokens only by default
            - Ordered by created_at descending (newest first)

        Returns:
            List of RefreshToken instances

        Example:
            # Get active tokens only
            active_tokens = token_repo.get_by_user( user_id )

            # Get all tokens including revoked
            all_tokens = token_repo.get_by_user( user_id, include_revoked=True )
        """
        query = self.session.query( RefreshToken ).filter(
            RefreshToken.user_id == user_id
        )

        if not include_revoked:
            query = query.filter( RefreshToken.revoked == False )

        return query.order_by( RefreshToken.created_at.desc() ).all()

    def revoke( self, jti: uuid.UUID ) -> Optional[RefreshToken]:
        """
        Revoke specific refresh token.

        Requires:
            - jti: JWT ID to revoke

        Ensures:
            - revoked set to True
            - Token can no longer be used for refresh

        Returns:
            Updated RefreshToken instance or None if not found

        Example:
            token = token_repo.revoke( jti )
            if token:
                # Token successfully revoked
        """
        token = self.get_by_jti( jti )
        if token:
            token.revoked = True
            self.session.flush()
            return token
        return None

    def revoke_all_for_user( self, user_id: uuid.UUID ) -> int:
        """
        Revoke all active refresh tokens for a user.

        Requires:
            - user_id: User UUID

        Ensures:
            - All non-revoked tokens for user are revoked
            - revoked set to True for all tokens

        Returns:
            Number of tokens revoked

        Example:
            # User logged out from all devices
            count = token_repo.revoke_all_for_user( user_id )
            # count = 3 (revoked 3 active tokens)
        """
        result = self.session.query( RefreshToken ).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False
        ).update(
            {
                RefreshToken.revoked: True
            },
            synchronize_session=False
        )
        self.session.flush()
        return result

    def cleanup_expired( self ) -> int:
        """
        Delete expired and revoked refresh tokens.

        Ensures:
            - Expired tokens (expires_at < now) are deleted
            - Revoked tokens are deleted
            - Active non-expired tokens are preserved

        Returns:
            Number of tokens deleted

        Example:
            # Cleanup expired/revoked tokens (run daily via cron)
            deleted = token_repo.cleanup_expired()
            # deleted = 150 (removed 150 old tokens)
        """
        cutoff_date = datetime.now( timezone.utc )

        # Delete expired tokens OR revoked tokens
        result = self.session.query( RefreshToken ).filter(
            ( RefreshToken.expires_at < cutoff_date ) |
            ( RefreshToken.revoked == True )
        ).delete( synchronize_session=False )

        self.session.flush()
        return result

    def update_last_used( self, jti: uuid.UUID, ip_address: Optional[str] = None ) -> Optional[RefreshToken]:
        """
        Update last used timestamp and optionally IP address for token.

        Requires:
            - jti: JWT ID
            - ip_address: Optional new IP address

        Ensures:
            - last_used_at set to current UTC timestamp
            - ip_address updated if provided
            - Tracks token activity

        Returns:
            Updated RefreshToken instance or None if not found

        Example:
            # User refreshed access token
            token = token_repo.update_last_used( jti, "192.168.1.100" )
        """
        token = self.get_by_jti( jti )
        if token:
            token.last_used_at = datetime.now( timezone.utc )
            if ip_address:
                token.ip_address = ip_address
            self.session.flush()
            return token
        return None

    def is_valid( self, jti: uuid.UUID ) -> bool:
        """
        Check if refresh token is valid (exists, not revoked, not expired).

        Requires:
            - jti: JWT ID to check

        Ensures:
            - Token exists
            - revoked = False
            - expires_at > now (not expired)

        Returns:
            True if token is valid, False otherwise

        Example:
            if token_repo.is_valid( jti ):
                # Token can be used for refresh
            else:
                # Token is revoked, expired, or doesn't exist
        """
        token = self.get_by_jti( jti )
        if not token:
            return False

        if token.revoked:
            return False

        if token.expires_at < datetime.now( timezone.utc ):
            return False

        return True

    def count_active_for_user( self, user_id: uuid.UUID ) -> int:
        """
        Count active (non-revoked, non-expired) tokens for user.

        Requires:
            - user_id: User UUID

        Ensures:
            - Counts only valid tokens
            - Excludes revoked tokens
            - Excludes expired tokens

        Returns:
            Number of active tokens

        Example:
            active_sessions = token_repo.count_active_for_user( user_id )
            if active_sessions > 5:
                # User has many active sessions, maybe revoke old ones
        """
        return self.session.query( RefreshToken ).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now( timezone.utc )
        ).count()

    def delete( self, jti: uuid.UUID ) -> bool:
        """
        Delete refresh token by JTI.

        Requires:
            - jti: JWT ID of token to delete

        Ensures:
            - Token removed from database if exists
            - Returns True if deleted, False if not found

        Returns:
            True if token was deleted, False if not found

        Example:
            deleted = token_repo.delete( jti )
        """
        token = self.get_by_jti( jti )
        if token:
            self.session.delete( token )
            self.session.flush()
            return True
        return False
