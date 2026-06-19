"""
Unit tests for the generic SQLAlchemy repository (cosa.rest.db.repositories.base).

Covers BaseRepository.__init__, get_by_id, get_all, create, update (found +
hasattr-true / hasattr-false / not-found), delete (found / not-found), count,
and exists — to genuine 100% line + branch + function.

All DB access is boundary-mocked: the SQLAlchemy Session is a MagicMock and the
model class is a MagicMock. ZERO real database access at test time.
"""

import unittest
from unittest.mock import MagicMock, Mock

from cosa.rest.db.repositories.base import BaseRepository


class _RepoTestBase( unittest.TestCase ):
    """
    Shared harness: a mock model class + a mock SQLAlchemy session.

    Ensures:
        - self.session is a MagicMock standing in for an active Session
        - self.model is a MagicMock standing in for a SQLAlchemy model class
        - self.repo is the BaseRepository under test
    """

    def setUp( self ):
        self.session = MagicMock( name="session" )
        self.model   = MagicMock( name="Model" )
        self.repo    = BaseRepository( self.model, self.session )


class TestInit( _RepoTestBase ):
    def test_stores_model_and_session( self ):
        self.assertIs( self.repo.model, self.model )
        self.assertIs( self.repo.session, self.session )


class TestGetById( _RepoTestBase ):
    def test_returns_first_result( self ):
        sentinel = object()
        self.session.query.return_value.filter.return_value.first.return_value = sentinel
        self.assertIs( self.repo.get_by_id( 42 ), sentinel )
        self.session.query.assert_called_once_with( self.model )


class TestGetAll( _RepoTestBase ):
    def test_default_pagination( self ):
        rows  = [ object(), object() ]
        chain = self.session.query.return_value.limit.return_value.offset.return_value
        chain.all.return_value = rows
        self.assertEqual( self.repo.get_all(), rows )
        self.session.query.return_value.limit.assert_called_once_with( 100 )
        self.session.query.return_value.limit.return_value.offset.assert_called_once_with( 0 )

    def test_custom_pagination( self ):
        chain = self.session.query.return_value.limit.return_value.offset.return_value
        chain.all.return_value = []
        self.assertEqual( self.repo.get_all( limit=5, offset=10 ), [] )
        self.session.query.return_value.limit.assert_called_once_with( 5 )
        self.session.query.return_value.limit.return_value.offset.assert_called_once_with( 10 )


class TestCreate( _RepoTestBase ):
    def test_adds_flushes_and_returns_entity( self ):
        entity = self.repo.create( email="a@b.com", roles=[ "user" ] )
        self.model.assert_called_once_with( email="a@b.com", roles=[ "user" ] )
        self.assertIs( entity, self.model.return_value )
        self.session.add.assert_called_once_with( entity )
        self.session.flush.assert_called_once_with()


class _Plain:
    """A real (non-Mock) entity exposing exactly one settable attribute."""
    def __init__( self ):
        self.existing = 1


class TestUpdate( _RepoTestBase ):
    def test_found_updates_present_attrs_and_skips_missing( self ):
        entity = _Plain()
        self.repo.get_by_id = Mock( return_value=entity )
        result = self.repo.update( 7, existing=99, missing="ignored" )
        self.assertIs( result, entity )
        self.assertEqual( entity.existing, 99 )            # hasattr True branch
        self.assertFalse( hasattr( entity, "missing" ) )   # hasattr False branch — skipped
        self.session.flush.assert_called_once_with()

    def test_not_found_returns_none_without_flush( self ):
        self.repo.get_by_id = Mock( return_value=None )
        self.assertIsNone( self.repo.update( 7, existing=1 ) )
        self.session.flush.assert_not_called()


class TestDelete( _RepoTestBase ):
    def test_found_deletes_and_returns_true( self ):
        entity = object()
        self.repo.get_by_id = Mock( return_value=entity )
        self.assertTrue( self.repo.delete( 7 ) )
        self.session.delete.assert_called_once_with( entity )

    def test_not_found_returns_false( self ):
        self.repo.get_by_id = Mock( return_value=None )
        self.assertFalse( self.repo.delete( 7 ) )
        self.session.delete.assert_not_called()


class TestCount( _RepoTestBase ):
    def test_returns_query_count( self ):
        self.session.query.return_value.count.return_value = 3
        self.assertEqual( self.repo.count(), 3 )
        self.session.query.assert_called_once_with( self.model )


class TestExists( _RepoTestBase ):
    def test_returns_scalar_boolean( self ):
        self.session.query.return_value.scalar.return_value = True
        self.assertTrue( self.repo.exists( 7 ) )

    def test_returns_false_when_scalar_false( self ):
        self.session.query.return_value.scalar.return_value = False
        self.assertFalse( self.repo.exists( 7 ) )


def isolated_unit_test():
    """
    Run the BaseRepository unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} BaseRepository tests in {secs:.3f}s — {msg}" )
