"""
Unit tests for cosa.rest.db.repositories.user_repository.

SQLAlchemy session mocked ( chainable query ); inherited BaseRepository.create /
update mocked. No real DB. Covers email lookup, creation ( roles default ), the
update-delegating mutators, listing/role/count queries, and email_exists.
"""

import unittest
import uuid
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.user_repository import UserRepository


def _repo():
    """
    Ensures:
        - Returns ( repo, session, query ) with a chainable query mock
    """
    session = MagicMock()
    q = session.query.return_value
    for attr in ( "filter", "order_by", "limit", "offset" ):
        getattr( q, attr ).return_value = q
    return UserRepository( session ), session, q


class TestUserRepository( unittest.TestCase ):
    """
    Tests for UserRepository.

    Ensures:
        - Lookup, creation, update-delegation, listing, and existence checks
    """

    def test_get_by_email_lowercases( self ):
        """
        Ensures:
            - get_by_email returns the first match ( email lookup )
        """
        repo, _, q = _repo()
        q.first.return_value = "user"
        self.assertEqual( repo.get_by_email( "USER@X.com" ), "user" )

    def test_create_user_defaults_roles( self ):
        """
        Ensures:
            - roles=None defaults to ["user"]; email lowercased; flags set
        """
        repo, _, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            self.assertEqual( repo.create_user( "USER@X.com", "$h" ), "created" )
            _, kwargs = mock_create.call_args
            self.assertEqual( kwargs[ "email" ], "user@x.com" )
            self.assertEqual( kwargs[ "roles" ], [ "user" ] )
            self.assertTrue( kwargs[ "is_active" ] )
            self.assertFalse( kwargs[ "email_verified" ] )

    def test_create_user_explicit_roles( self ):
        """
        Ensures:
            - Explicit roles are passed through
        """
        repo, _, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            repo.create_user( "u@x.com", "$h", roles=[ "user", "admin" ] )
            self.assertEqual( mock_create.call_args.kwargs[ "roles" ], [ "user", "admin" ] )

    def test_update_password_delegates( self ):
        """
        Ensures:
            - update_password delegates to base.update with password_hash
        """
        repo, _, _ = _repo()
        uid = uuid.uuid4()
        with patch.object( repo, "update", return_value="updated" ) as mock_update:
            self.assertEqual( repo.update_password( uid, "$new" ), "updated" )
            mock_update.assert_called_once_with( uid, password_hash="$new" )

    def test_update_last_login_delegates( self ):
        """
        Ensures:
            - update_last_login delegates to base.update with a last_login_at timestamp
        """
        repo, _, _ = _repo()
        uid = uuid.uuid4()
        with patch.object( repo, "update", return_value="updated" ) as mock_update:
            self.assertEqual( repo.update_last_login( uid ), "updated" )
            self.assertIn( "last_login_at", mock_update.call_args.kwargs )

    def test_update_roles_delegates( self ):
        """
        Ensures:
            - update_roles delegates to base.update replacing the roles list
        """
        repo, _, _ = _repo()
        uid = uuid.uuid4()
        with patch.object( repo, "update", return_value="updated" ) as mock_update:
            repo.update_roles( uid, [ "admin" ] )
            mock_update.assert_called_once_with( uid, roles=[ "admin" ] )

    def test_deactivate_delegates( self ):
        """
        Ensures:
            - deactivate delegates to base.update with is_active=False
        """
        repo, _, _ = _repo()
        uid = uuid.uuid4()
        with patch.object( repo, "update", return_value="updated" ) as mock_update:
            repo.deactivate( uid )
            mock_update.assert_called_once_with( uid, is_active=False )

    def test_activate_delegates( self ):
        """
        Ensures:
            - activate delegates to base.update with is_active=True
        """
        repo, _, _ = _repo()
        uid = uuid.uuid4()
        with patch.object( repo, "update", return_value="updated" ) as mock_update:
            repo.activate( uid )
            mock_update.assert_called_once_with( uid, is_active=True )

    def test_mark_email_verified_delegates( self ):
        """
        Ensures:
            - mark_email_verified delegates to base.update with email_verified=True
        """
        repo, _, _ = _repo()
        uid = uuid.uuid4()
        with patch.object( repo, "update", return_value="updated" ) as mock_update:
            repo.mark_email_verified( uid )
            mock_update.assert_called_once_with( uid, email_verified=True )

    def test_get_active_users( self ):
        """
        Ensures:
            - Returns paginated active users
        """
        repo, _, q = _repo()
        q.all.return_value = [ "u1" ]
        self.assertEqual( repo.get_active_users( limit=10, offset=0 ), [ "u1" ] )

    def test_get_by_role( self ):
        """
        Ensures:
            - Returns users matching the role
        """
        repo, _, q = _repo()
        q.all.return_value = [ "admin1" ]
        self.assertEqual( repo.get_by_role( "admin" ), [ "admin1" ] )

    def test_count_active_users( self ):
        """
        Ensures:
            - Returns the active-user count
        """
        repo, _, q = _repo()
        q.count.return_value = 42
        self.assertEqual( repo.count_active_users(), 42 )

    def test_email_exists_true( self ):
        """
        Ensures:
            - email_exists returns the scalar existence result ( True )
        """
        repo, _, q = _repo()
        q.scalar.return_value = True
        self.assertTrue( repo.email_exists( "u@x.com" ) )

    def test_email_exists_false( self ):
        """
        Ensures:
            - email_exists returns False when not present
        """
        repo, _, q = _repo()
        q.scalar.return_value = False
        self.assertFalse( repo.email_exists( "u@x.com" ) )


if __name__ == "__main__":
    unittest.main()
