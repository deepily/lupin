"""
Unit tests for cosa.rest.db.repositories.token_base and BaseRepository._set_flag.

Pins the shared token behaviour on a bare subclass, so a change to one token repository's flag or
default lifetime cannot hide behind the others. Session mocked; no real DB.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.repositories.token_base import TokenRepositoryBase
from cosa.rest.postgres_models import EmailVerificationToken, RefreshToken


class _Tokens( TokenRepositoryBase ):
    """A bare token repository with a 12 hour default."""
    default_expires_hours = 12


def _repo( model=EmailVerificationToken ):
    session = MagicMock()
    return _Tokens( model, session ), session


class TestCreateToken( unittest.TestCase ):

    def test_none_means_the_class_default_lifetime( self ):
        repo, _ = _repo()
        uid = uuid.uuid4()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            before = datetime.now( timezone.utc )
            self.assertEqual( repo.create_token( "tok", uid ), "created" )
            after = datetime.now( timezone.utc )
        kwargs = mock_create.call_args[ 1 ]
        self.assertEqual( ( kwargs[ "token" ], kwargs[ "user_id" ], kwargs[ "used" ] ), ( "tok", uid, False ) )
        self.assertTrue( before + timedelta( hours=12 ) <= kwargs[ "expires_at" ] <= after + timedelta( hours=12 ) )

    def test_an_explicit_lifetime_wins_over_the_class_default( self ):
        repo, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            repo.create_token( "tok", uuid.uuid4(), expires_hours=2 )
        remaining = mock_create.call_args[ 1 ][ "expires_at" ] - datetime.now( timezone.utc )
        self.assertTrue( timedelta( hours=1, minutes=59 ) < remaining <= timedelta( hours=2 ) )

    def test_zero_hours_is_honoured_not_replaced_by_the_default( self ):
        repo, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            repo.create_token( "tok", uuid.uuid4(), expires_hours=0 )
        remaining = mock_create.call_args[ 1 ][ "expires_at" ] - datetime.now( timezone.utc )
        self.assertTrue( remaining <= timedelta( seconds=1 ) )


class TestIsLive( unittest.TestCase ):

    def _row( self, flag_name, flag, hours ):
        row = MagicMock()
        setattr( row, flag_name, flag )
        row.expires_at = datetime.now( timezone.utc ) + timedelta( hours=hours )
        return row

    def test_a_row_with_the_flag_clear_and_a_future_expiry_is_live( self ):
        repo, _ = _repo()
        self.assertTrue( repo._is_live( self._row( "used", False, 1 ), "used" ) )

    def test_no_row_is_not_live( self ):
        repo, _ = _repo()
        self.assertFalse( repo._is_live( None, "used" ) )

    def test_the_named_flag_set_is_not_live_and_other_flags_do_not_matter( self ):
        repo, _ = _repo()
        row = self._row( "used", True, 1 )
        row.revoked = False
        self.assertFalse( repo._is_live( row, "used" ) )
        row = self._row( "used", False, 1 )
        row.revoked = True
        self.assertTrue( repo._is_live( row, "used" ) )
        self.assertFalse( repo._is_live( row, "revoked" ) )

    def test_an_expired_row_is_not_live( self ):
        repo, _ = _repo()
        self.assertFalse( repo._is_live( self._row( "used", False, -1 ), "used" ) )


class TestDeleteExpiredOr( unittest.TestCase ):

    def test_filters_on_the_models_expiry_or_the_given_flag_and_returns_the_count( self ):
        repo, session = _repo( RefreshToken )
        query = session.query.return_value
        query.filter.return_value.delete.return_value = 7

        self.assertEqual( repo._delete_expired_or( RefreshToken.revoked ), 7 )

        session.query.assert_called_once_with( RefreshToken )
        criterion = str( query.filter.call_args[ 0 ][ 0 ] )
        self.assertIn( "refresh_tokens.expires_at <", criterion )
        self.assertIn( " OR ", criterion )
        self.assertIn( "refresh_tokens.revoked = true", criterion )
        query.filter.return_value.delete.assert_called_once_with( synchronize_session=False )
        session.flush.assert_called_once()


class TestSetFlag( unittest.TestCase ):

    def _base( self ):
        session = MagicMock()
        return BaseRepository( EmailVerificationToken, session ), session

    def test_sets_the_attribute_flushes_and_returns_true( self ):
        repo, session = self._base()
        entity = MagicMock( used=False )
        self.assertTrue( repo._set_flag( entity, "used", True ) )
        self.assertIs( entity.used, True )
        session.flush.assert_called_once()

    def test_can_set_false_too( self ):
        repo, _ = self._base()
        entity = MagicMock( is_active=True )
        self.assertTrue( repo._set_flag( entity, "is_active", False ) )
        self.assertIs( entity.is_active, False )

    def test_no_entity_returns_false_and_does_not_flush( self ):
        repo, session = self._base()
        self.assertFalse( repo._set_flag( None, "used", True ) )
        session.flush.assert_not_called()


if __name__ == "__main__":
    unittest.main()
