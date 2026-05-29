"""
API key repository for service account authentication.

Provides API key management operations.
"""

from typing import Optional, List
from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import ApiKey
from cosa.rest.db.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    """
    Repository for ApiKey model with service account authentication operations.

    Extends BaseRepository with API key-specific methods:
        - Key hash-based lookup
        - User API key management
        - Key activation/deactivation
        - Last used tracking
    """

    def __init__( self, session: Session ):
        """
        Initialize ApiKeyRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                api_key_repo = ApiKeyRepository( session )
                key = api_key_repo.get_by_hash( key_hash )
        """
        super().__init__( ApiKey, session )

    def create_key( self, user_id: uuid.UUID, key_hash: str, description: str ) -> ApiKey:
        """
        Create new API key for user.

        Requires:
            - user_id: User UUID this key belongs to
            - key_hash: Hashed API key value (store hash, not raw key!)
            - description: Human-readable description (e.g., "GitHub Actions CI/CD")

        Ensures:
            - Key created with is_active = True
            - created_at set automatically
            - Relationship to user established

        Returns:
            Created ApiKey instance

        Example:
            key = api_key_repo.create_key(
                user_id = service_account.id,
                key_hash = hashlib.sha256( api_key.encode() ).hexdigest(),
                description = "Claude Code notification service"
            )
        """
        return self.create(
            user_id = user_id,
            key_hash = key_hash,
            description = description,
            is_active = True
        )

    def get_by_hash( self, key_hash: str ) -> Optional[ApiKey]:
        """
        Get API key by hash value.

        Requires:
            - key_hash: Hashed API key to lookup

        Ensures:
            - Returns key if found
            - Returns None if not found
            - Includes user relationship

        Returns:
            ApiKey instance or None

        Example:
            # Authenticate API request
            key = api_key_repo.get_by_hash( request_key_hash )
            if key and key.is_active:
                # Valid API key
        """
        return self.session.query( ApiKey ).filter(
            ApiKey.key_hash == key_hash
        ).first()

    def get_by_user( self, user_id: uuid.UUID, include_inactive: bool = False ) -> List[ApiKey]:
        """
        Get all API keys for a user.

        Requires:
            - user_id: User UUID
            - include_inactive: Include deactivated keys (default: False)

        Ensures:
            - Returns active keys only by default
            - Ordered by created_at descending (newest first)

        Returns:
            List of ApiKey instances
        """
        query = self.session.query( ApiKey ).filter(
            ApiKey.user_id == user_id
        )

        if not include_inactive:
            query = query.filter( ApiKey.is_active == True )

        return query.order_by( ApiKey.created_at.desc() ).all()

    def deactivate( self, key_id: uuid.UUID ) -> bool:
        """
        Deactivate API key.

        Requires:
            - key_id: API key UUID

        Ensures:
            - is_active set to False
            - Key can no longer be used for authentication

        Returns:
            True if deactivated, False if not found
        """
        key = self.get_by_id( key_id )
        if key:
            key.is_active = False
            self.session.flush()
            return True
        return False

    def activate( self, key_id: uuid.UUID ) -> bool:
        """
        Reactivate API key.

        Requires:
            - key_id: API key UUID

        Ensures:
            - is_active set to True
            - Key can be used for authentication again

        Returns:
            True if activated, False if not found
        """
        key = self.get_by_id( key_id )
        if key:
            key.is_active = True
            self.session.flush()
            return True
        return False

    def update_last_used( self, key_id: uuid.UUID ) -> bool:
        """
        Update last used timestamp for API key.

        Requires:
            - key_id: API key UUID

        Ensures:
            - last_used_at set to current UTC timestamp
            - Tracks key activity

        Returns:
            True if updated, False if key not found

        Example:
            # Successful API request authenticated
            api_key_repo.update_last_used( key.id )
        """
        key = self.get_by_id( key_id )
        if key:
            key.last_used_at = datetime.now( timezone.utc )
            self.session.flush()
            return True
        return False

    def is_valid( self, key_hash: str ) -> bool:
        """
        Check if API key is valid (exists and active).

        Requires:
            - key_hash: Hashed API key to check

        Ensures:
            - Key exists
            - is_active = True

        Returns:
            True if key is valid, False otherwise
        """
        key = self.get_by_hash( key_hash )
        return key is not None and key.is_active

    def count_active_for_user( self, user_id: uuid.UUID ) -> int:
        """
        Count active API keys for user.

        Requires:
            - user_id: User UUID

        Ensures:
            - Counts only active keys
            - Excludes deactivated keys

        Returns:
            Number of active API keys
        """
        return self.session.query( ApiKey ).filter(
            ApiKey.user_id == user_id,
            ApiKey.is_active == True
        ).count()

    def get_active_keys( self ) -> List[ApiKey]:
        """
        Get all active API keys for authentication middleware.

        Requires:
            - Database connection available

        Ensures:
            - Returns only active keys (is_active = True)
            - Used by middleware to validate incoming API keys

        Returns:
            List of all active ApiKey instances

        Example:
            # Middleware authentication
            active_keys = api_key_repo.get_active_keys()
            for key in active_keys:
                if bcrypt.checkpw( incoming_key, key.key_hash ):
                    # Valid key found
        """
        return self.session.query( ApiKey ).filter(
            ApiKey.is_active == True
        ).all()
