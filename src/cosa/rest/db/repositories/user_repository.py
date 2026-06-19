"""
User repository for CRUD operations on User model.

Provides user-specific methods beyond base repository functionality.
"""

from typing import Optional, List
from datetime import datetime
import uuid

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import User
from cosa.rest.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """
    Repository for User model with authentication-specific operations.

    Extends BaseRepository with user-specific methods:
        - Email-based lookup
        - Password updates
        - Role management
        - Account activation/deactivation
        - Email verification
        - Last login tracking
    """

    def __init__( self, session: Session ):
        """
        Initialize UserRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                user_repo = UserRepository( session )
                user = user_repo.get_by_email( "test@example.com" )
        """
        super().__init__( User, session )

    def get_by_email( self, email: str ) -> Optional[User]:
        """
        Get user by email address.

        Requires:
            - email: User email address

        Ensures:
            - Case-insensitive email lookup
            - Returns user if found
            - Returns None if not found

        Returns:
            User instance or None
        """
        return self.session.query( User ).filter(
            User.email == email.lower()
        ).first()

    def create_user( self, email: str, password_hash: str, roles: List[str] = None ) -> User:
        """
        Create new user with email and password.

        Requires:
            - email: User email address (will be lowercased)
            - password_hash: Bcrypt password hash
            - roles: List of role names (default: ["user"])

        Ensures:
            - Email stored in lowercase
            - Default role "user" if none provided
            - is_active = True by default
            - created_at / updated_at set automatically

        Returns:
            Created User instance

        Raises:
            IntegrityError: If email already exists

        Example:
            with get_db() as session:
                user_repo = UserRepository( session )
                user = user_repo.create_user(
                    email = "test@example.com",
                    password_hash = "$2b$12$...",
                    roles = ["user", "admin"]
                )
        """
        if roles is None:
            roles = ["user"]

        return self.create(
            email = email.lower(),
            password_hash = password_hash,
            roles = roles,
            is_active = True,
            email_verified = False
        )

    def update_password( self, user_id: uuid.UUID, new_password_hash: str ) -> Optional[User]:
        """
        Update user password.

        Requires:
            - user_id: User UUID
            - new_password_hash: New bcrypt password hash

        Ensures:
            - Password hash updated
            - updated_at timestamp refreshed

        Returns:
            Updated User instance or None if not found
        """
        return self.update( user_id, password_hash = new_password_hash )

    def update_last_login( self, user_id: uuid.UUID ) -> Optional[User]:
        """
        Update last login timestamp to current UTC time.

        Requires:
            - user_id: User UUID

        Ensures:
            - last_login_at set to current UTC timestamp
            - updated_at timestamp refreshed

        Returns:
            Updated User instance or None if not found
        """
        return self.update( user_id, last_login_at = datetime.utcnow() )

    def update_roles( self, user_id: uuid.UUID, roles: List[str] ) -> Optional[User]:
        """
        Update user roles.

        Requires:
            - user_id: User UUID
            - roles: New list of role names (replaces existing)

        Ensures:
            - Roles list completely replaced (not merged)
            - updated_at timestamp refreshed

        Returns:
            Updated User instance or None if not found

        Example:
            user = user_repo.update_roles(
                user_id,
                ["user", "admin", "moderator"]
            )
        """
        return self.update( user_id, roles = roles )

    def deactivate( self, user_id: uuid.UUID ) -> Optional[User]:
        """
        Deactivate user account.

        Requires:
            - user_id: User UUID

        Ensures:
            - is_active set to False
            - User can no longer log in
            - Existing sessions/tokens remain valid until expiration

        Returns:
            Updated User instance or None if not found
        """
        return self.update( user_id, is_active = False )

    def activate( self, user_id: uuid.UUID ) -> Optional[User]:
        """
        Activate user account.

        Requires:
            - user_id: User UUID

        Ensures:
            - is_active set to True
            - User can log in again

        Returns:
            Updated User instance or None if not found
        """
        return self.update( user_id, is_active = True )

    def mark_email_verified( self, user_id: uuid.UUID ) -> Optional[User]:
        """
        Mark user email as verified.

        Requires:
            - user_id: User UUID

        Ensures:
            - email_verified set to True

        Returns:
            Updated User instance or None if not found
        """
        return self.update(
            user_id,
            email_verified = True
        )

    def get_active_users( self, limit: int = 100, offset: int = 0 ) -> List[User]:
        """
        Get all active users with pagination.

        Requires:
            - limit: Maximum users to return (default: 100)
            - offset: Number of users to skip (default: 0)

        Ensures:
            - Only returns users where is_active = True
            - Ordered by created_at descending (newest first)

        Returns:
            List of active User instances
        """
        return self.session.query( User ).filter(
            User.is_active == True
        ).order_by(
            User.created_at.desc()
        ).limit( limit ).offset( offset ).all()

    def get_by_role( self, role: str, limit: int = 100 ) -> List[User]:
        """
        Get users with specific role.

        Requires:
            - role: Role name to search for (e.g., "admin", "user")
            - limit: Maximum users to return (default: 100)

        Ensures:
            - Searches JSONB roles array
            - Case-sensitive role matching
            - Ordered by created_at descending

        Returns:
            List of User instances with the specified role

        Example:
            admins = user_repo.get_by_role( "admin" )
        """
        return self.session.query( User ).filter(
            User.roles.contains( [role] )  # PostgreSQL JSONB array contains
        ).order_by(
            User.created_at.desc()
        ).limit( limit ).all()

    def count_active_users( self ) -> int:
        """
        Count total number of active users.

        Ensures:
            - Efficient COUNT query
            - Only counts is_active = True users

        Returns:
            Number of active users
        """
        return self.session.query( User ).filter(
            User.is_active == True
        ).count()

    def email_exists( self, email: str ) -> bool:
        """
        Check if email address is already registered.

        Requires:
            - email: Email address to check

        Ensures:
            - Case-insensitive email check
            - Efficient existence query (no user loaded)

        Returns:
            True if email exists, False otherwise
        """
        return self.session.query(
            self.session.query( User ).filter(
                User.email == email.lower()
            ).exists()
        ).scalar()
