"""
Unit tests for the DM read methods added to NotificationRepository:
get_dm_thread / get_dm_inbox — to 100% line + branch + function.

All DB access is boundary-mocked via a self-returning fluent query mock (ZERO DB),
matching the pattern in test_notification_repository.py.
"""

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.postgres_models import Notification


def _fq( rows=None ):
    """A self-returning query mock for filter/order_by/limit chains."""
    q = MagicMock( name="query" )
    for m in ( "filter", "order_by", "limit" ):
        getattr( q, m ).return_value = q
    q.all.return_value = rows if rows is not None else []
    return q


_RID  = uuid.UUID( "11111111-1111-1111-1111-111111111111" )
_SINCE = datetime( 2026, 6, 17, 0, 0, 0, tzinfo=timezone.utc )


class _Base( unittest.TestCase ):
    def setUp( self ):
        self.session = MagicMock( name="session" )
        self.repo    = NotificationRepository( self.session )


class TestGetDmThread( _Base ):

    def test_no_since_skips_since_filter( self ):
        q = _fq( rows=[ "n1", "n2" ] )
        self.session.query.return_value = q
        out = self.repo.get_dm_thread( "th-1", _RID )
        self.assertEqual( out, [ "n1", "n2" ] )
        # base filter (recipient+thread+direction+is_hidden) called once; no since filter
        self.assertEqual( q.filter.call_count, 1 )
        q.limit.assert_called_once_with( 200 )
        q.order_by.assert_called_once()  # ascending

    def test_since_adds_filter_and_honors_limit( self ):
        q = _fq( rows=[ "n1" ] )
        self.session.query.return_value = q
        out = self.repo.get_dm_thread( "th-1", _RID, since=_SINCE, limit=10 )
        self.assertEqual( out, [ "n1" ] )
        self.assertEqual( q.filter.call_count, 2 )   # base + since
        q.limit.assert_called_once_with( 10 )


class TestGetDmInbox( _Base ):

    def test_no_since_skips_since_filter( self ):
        q = _fq( rows=[ "i1" ] )
        self.session.query.return_value = q
        out = self.repo.get_dm_inbox( _RID )
        self.assertEqual( out, [ "i1" ] )
        self.assertEqual( q.filter.call_count, 1 )
        q.limit.assert_called_once_with( 50 )

    def test_since_adds_filter_and_honors_limit( self ):
        q = _fq( rows=[] )
        self.session.query.return_value = q
        out = self.repo.get_dm_inbox( _RID, since=_SINCE, limit=5 )
        self.assertEqual( out, [] )
        self.assertEqual( q.filter.call_count, 2 )
        q.limit.assert_called_once_with( 5 )


# ─────────────────────────────────────────────────────────────────────────────
# recipient_session — the addressee predicate (row 2565956b)
#
# `recipient_id` scopes to a SERVICE ACCOUNT, not a session, so without this
# predicate both reads return every session's DMs on the account. These pin
# that the filter is applied when asked for and NOT applied when it isn't —
# the second half matters because the pre-existing client-side-filtering hook
# calls without it and must keep its account-wide behavior.
# ─────────────────────────────────────────────────────────────────────────────

class TestRecipientSessionPredicate( _Base ):

    def test_inbox_adds_the_addressee_filter( self ):
        q = _fq( rows=[ "mine" ] )
        self.session.query.return_value = q
        out = self.repo.get_dm_inbox( _RID, recipient_session="d43421a6" )
        self.assertEqual( out, [ "mine" ] )
        self.assertEqual( q.filter.call_count, 2 )        # base + addressee

    def test_inbox_without_it_is_unchanged( self ):
        q = _fq( rows=[ "all" ] )
        self.session.query.return_value = q
        self.repo.get_dm_inbox( _RID )
        self.assertEqual( q.filter.call_count, 1 )        # base only — legacy behavior

    def test_thread_adds_the_addressee_filter( self ):
        q = _fq( rows=[ "mine" ] )
        self.session.query.return_value = q
        self.repo.get_dm_thread( "th-1", _RID, recipient_session="d43421a6" )
        self.assertEqual( q.filter.call_count, 2 )

    def test_thread_without_it_is_unchanged( self ):
        q = _fq( rows=[ "all" ] )
        self.session.query.return_value = q
        self.repo.get_dm_thread( "th-1", _RID )
        self.assertEqual( q.filter.call_count, 1 )

    def test_addressee_and_since_stack( self ):
        q = _fq( rows=[] )
        self.session.query.return_value = q
        self.repo.get_dm_inbox( _RID, since=_SINCE, recipient_session="d43421a6" )
        self.assertEqual( q.filter.call_count, 3 )        # base + addressee + since

    def test_empty_string_session_is_still_a_filter_not_a_bypass( self ):
        # Guarding the boundary: only None means "do not narrow". An empty
        # string is a caller error that must NOT silently widen the read —
        # the router's resolve_dm_list_scope is what maps blank -> None.
        q = _fq( rows=[] )
        self.session.query.return_value = q
        self.repo.get_dm_inbox( _RID, recipient_session="" )
        self.assertEqual( q.filter.call_count, 2 )


if __name__ == "__main__":
    unittest.main()
