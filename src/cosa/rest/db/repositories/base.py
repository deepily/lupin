"""
Base repository pattern implementation with common CRUD operations.

Provides generic repository class that can be extended for specific models.
"""

from typing import TypeVar, Generic, Optional, List, Type, Any
from sqlalchemy.orm import Session
from cosa.rest.postgres_models import Base

ModelType = TypeVar( "ModelType", bound=Base )


class BaseRepository(Generic[ModelType]):
    """
    Base repository providing common CRUD operations for any SQLAlchemy model.

    Generic type parameter ModelType allows type-safe operations:
        user_repo = BaseRepository[User]( User, session )
        user: User = user_repo.get_by_id( user_id )  # Type checker knows this is User

    Requires:
        - model: SQLAlchemy model class (e.g., User, RefreshToken)
        - session: Active SQLAlchemy session

    Ensures:
        - Type-safe operations via Python generics
        - Common CRUD methods available to all repositories
        - No direct session management (caller handles commit/rollback)
    """

    def __init__( self, model: Type[ModelType], session: Session ):
        """
        Initialize repository with model class and database session.

        Requires:
            - model: SQLAlchemy model class to operate on
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                user_repo = BaseRepository( User, session )
                user = user_repo.get_by_id( user_id )
        """
        self.model = model
        self.session = session

    def get_by_id( self, id: Any ) -> Optional[ModelType]:
        """
        Get entity by primary key.

        Requires:
            - id: Primary key value (UUID, int, str, etc.)

        Ensures:
            - Returns entity if found
            - Returns None if not found
            - No exception thrown for missing entity

        Returns:
            Entity instance or None
        """
        return self.session.query( self.model ).filter( self.model.id == id ).first()

    def get_all( self, limit: int = 100, offset: int = 0 ) -> List[ModelType]:
        """
        Get all entities with pagination.

        Requires:
            - limit: Maximum number of entities to return (default: 100)
            - offset: Number of entities to skip (default: 0)

        Ensures:
            - Returns list of entities (may be empty)
            - Applies limit and offset for pagination
            - Ordered by primary key (implicit)

        Returns:
            List of entity instances
        """
        return self.session.query( self.model ).limit( limit ).offset( offset ).all()

    def create( self, **kwargs ) -> ModelType:
        """
        Create new entity.

        Requires:
            - kwargs: Model attributes as keyword arguments

        Ensures:
            - Entity added to session
            - flush() called to get auto-generated ID
            - Commit NOT called (caller must commit)

        Returns:
            Created entity instance (with ID populated)

        Raises:
            SQLAlchemy exceptions for validation or constraint violations

        Example:
            with get_db() as session:
                repo = BaseRepository( User, session )
                user = repo.create(
                    email = "test@example.com",
                    password_hash = "...",
                    roles = ["user"]
                )
                # session.commit() called automatically by get_db()
        """
        entity = self.model( **kwargs )
        self.session.add( entity )
        self.session.flush()  # Get auto-generated ID without committing
        return entity

    def update( self, id: Any, **kwargs ) -> Optional[ModelType]:
        """
        Update entity by ID.

        Requires:
            - id: Primary key value
            - kwargs: Attributes to update

        Ensures:
            - Updates specified attributes only
            - flush() called to propagate changes
            - Commit NOT called (caller must commit)
            - Returns None if entity not found

        Returns:
            Updated entity instance or None

        Example:
            with get_db() as session:
                repo = BaseRepository( User, session )
                user = repo.update( user_id, last_login = datetime.utcnow() )
        """
        entity = self.get_by_id( id )
        if entity:
            for key, value in kwargs.items():
                if hasattr( entity, key ):
                    setattr( entity, key, value )
            self.session.flush()
        return entity

    def delete( self, id: Any ) -> bool:
        """
        Delete entity by ID.

        Requires:
            - id: Primary key value

        Ensures:
            - Entity removed from session
            - Commit NOT called (caller must commit)
            - Returns False if entity not found

        Returns:
            True if deleted, False if not found

        Example:
            with get_db() as session:
                repo = BaseRepository( User, session )
                deleted = repo.delete( user_id )
                # session.commit() called automatically by get_db()
        """
        entity = self.get_by_id( id )
        if entity:
            self.session.delete( entity )
            return True
        return False

    def count( self ) -> int:
        """
        Count total number of entities.

        Ensures:
            - Returns total count (efficient COUNT query)
            - No entities loaded into memory

        Returns:
            Total entity count
        """
        return self.session.query( self.model ).count()

    def exists( self, id: Any ) -> bool:
        """
        Check if entity exists by ID.

        Requires:
            - id: Primary key value

        Ensures:
            - Efficient existence check (no entity loaded)
            - Returns boolean

        Returns:
            True if exists, False otherwise
        """
        return self.session.query(
            self.session.query( self.model ).filter( self.model.id == id ).exists()
        ).scalar()
