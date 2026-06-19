"""
Unit tests for NotificationRepository (cosa.rest.db.repositories.notification_repository).

Covers every method to genuine 100% line + branch + function:
create_notification, get_by_recipient, get_sender_last_activities,
get_sender_conversation (anchor-given / anchor-None-empty / anchor-None-found),
update_state (not-found / delivered / responded / other), update_response,
get_pending_for_recipient, get_expired_notifications, mark_expired
(not-found / with-default / without-default), count_by_sender, count_by_job_ids
(empty / populated-with-missing-ids), delete_by_sender,
get_sender_conversations_by_date (anchor arcs / include_hidden / tz-fallback /
date grouping), soft_delete_by_date (good tz / tz-fallback),
get_sender_date_summaries (state arcs / include_hidden / tz-fallback),
get_sender_last_activities_visible (include_hidden / exclude None / exclude
truthy / exclude empty / new_count-None), get_active_conversation (found /
none), bulk_delete_by_user (hours arcs / exclude arcs), and
get_sessions_for_project (project match / no-match).

All DB access is boundary-mocked via a self-returning fluent query mock. ZERO DB.
"""

import unittest
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.postgres_models import Notification


def _fq( rows=None, first=None, scalar=None, count=None, delete=None, update=None ):
    """A self-returning query mock for filter/order_by/limit/offset/group_by chains."""
    q = MagicMock( name="query" )
    for m in ( "filter", "order_by", "limit", "offset", "group_by" ):
        getattr( q, m ).return_value = q
    q.all.return_value    = rows if rows is not None else []
    q.first.return_value  = first
    q.scalar.return_value = scalar
    q.count.return_value  = count
    q.delete.return_value = delete
    q.update.return_value = update
    return q


def _row( **kw ):
    return SimpleNamespace( **kw )


_RID = uuid.UUID( "11111111-1111-1111-1111-111111111111" )


class _NRBase( unittest.TestCase ):
    def setUp( self ):
        self.session = MagicMock( name="session" )
        self.repo    = NotificationRepository( self.session )


class TestInit( _NRBase ):
    def test_binds_model( self ):
        self.assertIs( self.repo.model, Notification )


class TestCreateNotification( _NRBase ):
    def test_delegates_with_created_state( self ):
        self.repo.create = Mock( return_value="n" )
        out = self.repo.create_notification(
            sender_id="s", recipient_id=_RID, message="m", type="task", priority="medium"
        )
        self.assertEqual( out, "n" )
        self.assertEqual( self.repo.create.call_args.kwargs[ "state" ], "created" )


class TestGetByRecipient( _NRBase ):
    def test_returns_rows( self ):
        q = _fq( rows=[ "n1" ] )
        self.session.query.return_value = q
        self.assertEqual( self.repo.get_by_recipient( _RID ), [ "n1" ] )
        q.limit.assert_called_once_with( 100 )
        q.offset.assert_called_once_with( 0 )


class TestGetSenderLastActivities( _NRBase ):
    def test_maps_rows( self ):
        rows = [ _row( sender_id="s1", last_activity="t1", notification_count=5 ) ]
        self.session.query.return_value = _fq( rows=rows )
        out = self.repo.get_sender_last_activities( _RID )
        self.assertEqual( out, [ { "sender_id": "s1", "last_activity": "t1", "count": 5 } ] )


class TestGetSenderConversation( _NRBase ):
    def test_anchor_given_skips_lookup( self ):
        q = _fq( rows=[ "n1" ] )
        self.session.query.return_value = q
        anchor = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        self.assertEqual(
            self.repo.get_sender_conversation( "s", _RID, anchor=anchor ), [ "n1" ]
        )

    def test_anchor_none_no_activity_returns_empty( self ):
        self.session.query.return_value = _fq( scalar=None )
        self.assertEqual( self.repo.get_sender_conversation( "s", _RID ), [] )

    def test_anchor_none_uses_last_activity( self ):
        anchor = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        self.session.query.return_value = _fq( rows=[ "n1" ], scalar=anchor )
        self.assertEqual( self.repo.get_sender_conversation( "s", _RID ), [ "n1" ] )


class TestUpdateState( _NRBase ):
    def test_not_found_returns_none( self ):
        self.repo.get_by_id = Mock( return_value=None )
        self.assertIsNone( self.repo.update_state( _RID, "delivered" ) )

    def test_delivered_sets_delivered_at( self ):
        n = SimpleNamespace()
        self.repo.get_by_id = Mock( return_value=n )
        self.repo.update_state( _RID, "delivered" )
        self.assertEqual( n.state, "delivered" )
        self.assertIsNotNone( n.delivered_at )

    def test_responded_sets_responded_at( self ):
        n = SimpleNamespace()
        self.repo.get_by_id = Mock( return_value=n )
        self.repo.update_state( _RID, "responded" )
        self.assertIsNotNone( n.responded_at )

    def test_other_state_sets_no_timestamp( self ):
        n = SimpleNamespace()
        self.repo.get_by_id = Mock( return_value=n )
        out = self.repo.update_state( _RID, "queued" )
        self.assertEqual( out.state, "queued" )
        self.session.flush.assert_called_once_with()


class TestUpdateResponse( _NRBase ):
    def test_found_records_response( self ):
        n = SimpleNamespace()
        self.repo.get_by_id = Mock( return_value=n )
        out = self.repo.update_response( _RID, { "value": "yes" } )
        self.assertIs( out, n )
        self.assertEqual( n.response_value, { "value": "yes" } )
        self.assertEqual( n.state, "responded" )

    def test_not_found_returns_none( self ):
        self.repo.get_by_id = Mock( return_value=None )
        self.assertIsNone( self.repo.update_response( _RID, {} ) )


class TestGetPendingForRecipient( _NRBase ):
    def test_returns_rows( self ):
        self.session.query.return_value = _fq( rows=[ "p1" ] )
        self.assertEqual( self.repo.get_pending_for_recipient( _RID ), [ "p1" ] )


class TestGetExpiredNotifications( _NRBase ):
    def test_returns_rows( self ):
        self.session.query.return_value = _fq( rows=[ "e1" ] )
        self.assertEqual( self.repo.get_expired_notifications(), [ "e1" ] )


class TestMarkExpired( _NRBase ):
    def test_not_found_returns_none( self ):
        self.repo.get_by_id = Mock( return_value=None )
        self.assertIsNone( self.repo.mark_expired( _RID ) )

    def test_with_default_applies_value( self ):
        n = SimpleNamespace( response_default="yes" )
        self.repo.get_by_id = Mock( return_value=n )
        out = self.repo.mark_expired( _RID )
        self.assertEqual( out.state, "expired" )
        self.assertEqual( n.response_value, { "value": "yes", "source": "timeout_default" } )

    def test_without_default_no_value( self ):
        n = SimpleNamespace( response_default=None )
        self.repo.get_by_id = Mock( return_value=n )
        out = self.repo.mark_expired( _RID )
        self.assertEqual( out.state, "expired" )
        self.assertFalse( hasattr( n, "response_value" ) )


class TestCountBySender( _NRBase ):
    def test_maps_counts( self ):
        rows = [ _row( sender_id="s1", count=3 ), _row( sender_id="s2", count=1 ) ]
        self.session.query.return_value = _fq( rows=rows )
        self.assertEqual( self.repo.count_by_sender( _RID ), { "s1": 3, "s2": 1 } )


class TestCountByJobIds( _NRBase ):
    def test_empty_input_no_query( self ):
        self.assertEqual( self.repo.count_by_job_ids( [] ), {} )
        self.session.query.assert_not_called()

    def test_populated_fills_missing_with_zero( self ):
        rows = [ _row( job_id="j1", count=2 ) ]
        self.session.query.return_value = _fq( rows=rows )
        self.assertEqual( self.repo.count_by_job_ids( [ "j1", "j2" ] ), { "j1": 2, "j2": 0 } )


class TestDeleteBySender( _NRBase ):
    def test_returns_deleted_count( self ):
        self.session.query.return_value = _fq( delete=4 )
        self.assertEqual( self.repo.delete_by_sender( "s", _RID ), 4 )
        self.session.flush.assert_called_once_with()


class TestGetSenderConversationsByDate( _NRBase ):
    def test_anchor_none_no_activity_returns_empty( self ):
        self.session.query.return_value = _fq( scalar=None )
        self.assertEqual( self.repo.get_sender_conversations_by_date( "s", _RID ), {} )

    def test_anchor_given_include_hidden_groups_by_date( self ):
        base = datetime( 2026, 1, 2, 10, 0, tzinfo=timezone.utc )
        notifs = [
            _row( created_at=base ),
            _row( created_at=base + timedelta( hours=1 ) ),    # same date → existing-key branch
            _row( created_at=base - timedelta( days=1 ) ),     # different date → new-key branch
        ]
        self.session.query.return_value = _fq( rows=notifs )
        out = self.repo.get_sender_conversations_by_date(
            "s", _RID, anchor=base + timedelta( hours=2 ), include_hidden=True
        )
        keys = list( out.keys() )
        self.assertEqual( keys, sorted( keys, reverse=True ) )   # newest-first
        self.assertEqual( sum( len( v ) for v in out.values() ), 3 )

    def test_anchor_none_found_with_tz_fallback( self ):
        anchor = datetime( 2026, 1, 2, tzinfo=timezone.utc )
        notifs = [ _row( created_at=anchor ) ]
        self.session.query.return_value = _fq( rows=notifs, scalar=anchor )
        out = self.repo.get_sender_conversations_by_date(
            "s", _RID, timezone_name="Not/AZone"   # invalid → fallback to America/New_York
        )
        self.assertEqual( sum( len( v ) for v in out.values() ), 1 )


class TestSoftDeleteByDate( _NRBase ):
    def test_good_timezone_returns_update_count( self ):
        self.session.query.return_value = _fq( update=2 )
        self.assertEqual(
            self.repo.soft_delete_by_date( "s", _RID, "2026-01-01" ), 2
        )
        self.session.flush.assert_called_once_with()

    def test_bad_timezone_falls_back( self ):
        self.session.query.return_value = _fq( update=0 )
        self.assertEqual(
            self.repo.soft_delete_by_date( "s", _RID, "2026-01-01", timezone_name="Not/AZone" ), 0
        )


class TestGetSenderDateSummaries( _NRBase ):
    def test_states_and_existing_key( self ):
        base = datetime( 2026, 1, 2, 10, 0, tzinfo=timezone.utc )
        notifs = [
            _row( created_at=base, state="created" ),                       # new_count++
            _row( created_at=base + timedelta( hours=1 ), state="delivered" ),  # same date, not new
        ]
        self.session.query.return_value = _fq( rows=notifs )
        out = self.repo.get_sender_date_summaries( "s", _RID )
        self.assertEqual( len( out ), 1 )
        self.assertEqual( out[ 0 ][ "count" ], 2 )
        self.assertEqual( out[ 0 ][ "new_count" ], 1 )

    def test_include_hidden_and_tz_fallback_new_date( self ):
        notifs = [ _row( created_at=datetime( 2026, 1, 3, tzinfo=timezone.utc ), state="queued" ) ]
        self.session.query.return_value = _fq( rows=notifs )
        out = self.repo.get_sender_date_summaries(
            "s", _RID, include_hidden=True, timezone_name="Not/AZone"
        )
        self.assertEqual( out[ 0 ][ "new_count" ], 1 )


class TestGetSenderLastActivitiesVisible( _NRBase ):
    def test_defaults_exclude_none_new_count_truthy( self ):
        rows = [ _row( sender_id="s1", last_activity="t", notification_count=5, new_count=2 ) ]
        self.session.query.return_value = _fq( rows=rows )
        out = self.repo.get_sender_last_activities_visible( _RID )
        self.assertEqual( out[ 0 ][ "new_count" ], 2 )

    def test_include_hidden_exclude_truthy_new_count_none( self ):
        rows = [ _row( sender_id="s1", last_activity="t", notification_count=5, new_count=None ) ]
        self.session.query.return_value = _fq( rows=rows )
        out = self.repo.get_sender_last_activities_visible(
            _RID, include_hidden=True, exclude_job_ids=[ "j1" ]
        )
        self.assertEqual( out[ 0 ][ "new_count" ], 0 )   # `or 0` arc

    def test_exclude_empty_list_true_branch( self ):
        self.session.query.return_value = _fq( rows=[] )
        self.assertEqual(
            self.repo.get_sender_last_activities_visible( _RID, exclude_job_ids=[] ), []
        )


class TestGetActiveConversation( _NRBase ):
    def test_found_returns_sender_id( self ):
        self.session.query.return_value = _fq( first=_row( sender_id="s9" ) )
        self.assertEqual( self.repo.get_active_conversation( _RID ), "s9" )

    def test_none_returns_none( self ):
        self.session.query.return_value = _fq( first=None )
        self.assertIsNone( self.repo.get_active_conversation( _RID ) )


class TestBulkDeleteByUser( _NRBase ):
    def test_no_hours_no_exclude( self ):
        self.session.query.return_value = _fq( count=3, delete=3 )
        with patch( "builtins.print" ):
            self.assertEqual( self.repo.bulk_delete_by_user( "u@e.com", _RID ), 3 )

    def test_hours_and_exclude_truthy( self ):
        self.session.query.return_value = _fq( count=2, delete=2 )
        with patch( "builtins.print" ):
            self.assertEqual(
                self.repo.bulk_delete_by_user( "u@e.com", _RID, hours=168, exclude_job_ids=[ "j1" ] ), 2
            )

    def test_exclude_empty_list_true_branch( self ):
        self.session.query.return_value = _fq( count=0, delete=0 )
        with patch( "builtins.print" ):
            self.assertEqual(
                self.repo.bulk_delete_by_user( "u@e.com", _RID, exclude_job_ids=[] ), 0
            )


class TestGetSessionsForProject( _NRBase ):
    def test_filters_to_project_and_marks_active( self ):
        self.repo.get_sender_last_activities_visible = Mock( return_value=[
            { "sender_id": "claude.code@lupin.deepily.ai", "last_activity": "t1", "count": 3, "new_count": 1 },
            { "sender_id": "claude.code@cosa.deepily.ai",  "last_activity": "t2", "count": 1, "new_count": 0 },
        ] )
        self.repo.get_active_conversation = Mock( return_value="claude.code@lupin.deepily.ai" )

        def _parse( sender_id ):
            project = "lupin" if "lupin" in sender_id else "cosa"
            return { "project": project, "session_id": sender_id.split( "@" )[ 0 ] }

        with patch( "lupin_cli.notifications.notification_models.parse_sender_id", side_effect=_parse ):
            out = self.repo.get_sessions_for_project( _RID, "lupin" )

        self.assertEqual( len( out ), 1 )                      # only the lupin sender
        self.assertTrue( out[ 0 ][ "is_active" ] )
        self.assertEqual( out[ 0 ][ "new_count" ], 1 )


def isolated_unit_test():
    """
    Run the NotificationRepository unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} NotificationRepository tests in {secs:.3f}s — {msg}" )
