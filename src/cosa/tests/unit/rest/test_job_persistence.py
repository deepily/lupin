"""
Unit tests for the CJ Flow persistence service (cosa.rest.job_persistence).

Covers every public + private function to genuine 100% line + branch + function:
is_agentic_job_type, _is_persistence_enabled (true/false/except), _get_history_days
(value/except), record_server_available (disabled/insert/update/except),
get_last_available (none/naive-tz/aware/except), _is_within_downtime (no-last/in/
out/parse-error), _build_metadata_json (empty/extract), the four persist_* writers
(disabled-skip / write / except + completed/stalled/failed merge-and-duration arcs),
mark_interrupted_jobs (running + pending future/catchup/before-window/no-schedule +
except), _is_future_scheduled (future/past/parse-error/naive-now), get_restorable_jobs
(with/without scheduled_at / except), get_active_job_ids_by_user (group/except),
_count_notifications_for_jobs (empty/rows/except), _unpack_metadata_json,
_build_history_row (timestamps present/None), query_job_history (all-filters/no-
filters/except), get_job_by_id_hash (found/not-found/except), delete_job_history
(deleted/not/except), delete_job_history_bulk (filters/no-filters/except),
get_checkpoint_for_job (artifacts/top-level/not-stalled/except), and
get_original_args_for_job (found/not-found/except).

get_db is boundary-mocked; ConfigurationManager is patched. ZERO real DB.
"""

import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from cosa.rest import job_persistence as jp
from cosa.rest.job_state import JobState


def _mock_get_db( session ):
    """Return a MagicMock standing in for get_db whose context yields `session`."""
    mg = MagicMock( name="get_db" )
    mg.return_value.__enter__.return_value = session
    mg.return_value.__exit__.return_value = False
    return mg


class TestIsAgenticJobType( unittest.TestCase ):
    def test_agentic( self ):
        self.assertTrue( jp.is_agentic_job_type( "deep_research" ) )

    def test_non_agentic( self ):
        self.assertFalse( jp.is_agentic_job_type( "math" ) )

    def test_falsy( self ):
        self.assertFalse( jp.is_agentic_job_type( None ) )
        self.assertFalse( jp.is_agentic_job_type( "" ) )


class TestConfigHelpers( unittest.TestCase ):
    def test_persistence_enabled_true( self ):
        cfg = Mock(); cfg.get.return_value = "true"
        with patch.object( jp, "ConfigurationManager", return_value=cfg ):
            self.assertTrue( jp._is_persistence_enabled() )

    def test_persistence_enabled_false( self ):
        cfg = Mock(); cfg.get.return_value = "false"
        with patch.object( jp, "ConfigurationManager", return_value=cfg ):
            self.assertFalse( jp._is_persistence_enabled() )

    def test_persistence_enabled_except_defaults_true( self ):
        with patch.object( jp, "ConfigurationManager", side_effect=RuntimeError( "boom" ) ):
            self.assertTrue( jp._is_persistence_enabled() )

    def test_history_days_value( self ):
        cfg = Mock(); cfg.get.return_value = "45"
        with patch.object( jp, "ConfigurationManager", return_value=cfg ):
            self.assertEqual( jp._get_history_days(), 45 )

    def test_history_days_except_defaults_30( self ):
        with patch.object( jp, "ConfigurationManager", side_effect=RuntimeError( "boom" ) ):
            self.assertEqual( jp._get_history_days(), 30 )


class TestRecordServerAvailable( unittest.TestCase ):
    def test_disabled_noop( self ):
        with patch.object( jp, "_is_persistence_enabled", return_value=False ), \
             patch.object( jp, "get_db" ) as mg:
            jp.record_server_available()
        mg.assert_not_called()

    def test_insert_when_no_row( self ):
        session = MagicMock(); session.get.return_value = None
        with patch.object( jp, "_is_persistence_enabled", return_value=True ), \
             patch.object( jp, "get_db", _mock_get_db( session ) ):
            jp.record_server_available()
        session.add.assert_called_once()

    def test_update_when_row_exists( self ):
        row = SimpleNamespace( last_available_at=None )
        session = MagicMock(); session.get.return_value = row
        ts = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        with patch.object( jp, "_is_persistence_enabled", return_value=True ), \
             patch.object( jp, "get_db", _mock_get_db( session ) ):
            jp.record_server_available( ts=ts )
        self.assertEqual( row.last_available_at, ts )

    def test_exception_logged( self ):
        with patch.object( jp, "_is_persistence_enabled", return_value=True ), \
             patch.object( jp, "get_db", side_effect=RuntimeError( "db boom" ) ), \
             patch( "builtins.print" ) as mp:
            jp.record_server_available()
        self.assertTrue( any( "record_server_available failed" in str( c ) for c in mp.call_args_list ) )


class TestGetLastAvailable( unittest.TestCase ):
    def test_none_when_no_row( self ):
        session = MagicMock(); session.get.return_value = None
        with patch.object( jp, "get_db", _mock_get_db( session ) ):
            self.assertIsNone( jp.get_last_available() )

    def test_naive_timestamp_made_aware( self ):
        row = SimpleNamespace( last_available_at=datetime( 2026, 1, 1 ) )   # naive
        session = MagicMock(); session.get.return_value = row
        with patch.object( jp, "get_db", _mock_get_db( session ) ):
            out = jp.get_last_available()
        self.assertEqual( out.tzinfo, timezone.utc )

    def test_aware_timestamp_returned( self ):
        row = SimpleNamespace( last_available_at=datetime( 2026, 1, 1, tzinfo=timezone.utc ) )
        session = MagicMock(); session.get.return_value = row
        with patch.object( jp, "get_db", _mock_get_db( session ) ):
            self.assertIsNotNone( jp.get_last_available() )

    def test_exception_returns_none( self ):
        with patch.object( jp, "get_db", side_effect=RuntimeError( "boom" ) ), \
             patch( "builtins.print" ):
            self.assertIsNone( jp.get_last_available() )


class TestIsWithinDowntime( unittest.TestCase ):
    def test_no_last_available_false( self ):
        self.assertFalse( jp._is_within_downtime( "2026-01-01T00:00:00+00:00", None,
                                                  datetime.now( timezone.utc ) ) )

    def test_within_window( self ):
        last = datetime( 2020, 1, 1, tzinfo=timezone.utc )
        now  = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        self.assertTrue( jp._is_within_downtime( "2021-01-01T00:00:00+00:00", last, now ) )

    def test_outside_window( self ):
        last = datetime( 2025, 1, 1, tzinfo=timezone.utc )
        now  = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        self.assertFalse( jp._is_within_downtime( "2019-01-01T00:00:00+00:00", last, now ) )

    def test_naive_scheduled_made_aware( self ):
        last = datetime( 2020, 1, 1, tzinfo=timezone.utc )
        now  = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        self.assertTrue( jp._is_within_downtime( "2021-01-01T00:00:00", last, now ) )   # naive

    def test_parse_error_false( self ):
        last = datetime( 2020, 1, 1, tzinfo=timezone.utc )
        self.assertFalse( jp._is_within_downtime( "not-a-date", last, datetime.now( timezone.utc ) ) )


class TestBuildMetadataJson( unittest.TestCase ):
    def test_empty( self ):
        self.assertEqual( jp._build_metadata_json( None ), {} )

    def test_extracts_present_rich_fields( self ):
        md = { "response_text": "r", "abstract": None, "irrelevant": "x", "cost_summary": { "t": 1 } }
        out = jp._build_metadata_json( md )
        self.assertEqual( out, { "response_text": "r", "cost_summary": { "t": 1 } } )   # None + irrelevant dropped


class _PersistBase( unittest.TestCase ):
    def setUp( self ):
        self.session = MagicMock( name="session" )
        self._p_enabled = patch.object( jp, "_is_persistence_enabled", return_value=True )
        self._p_enabled.start()
        self._p_db = patch.object( jp, "get_db", _mock_get_db( self.session ) )
        self._p_db.start()

    def tearDown( self ):
        self._p_db.stop()
        self._p_enabled.stop()


class TestPersistCreated( _PersistBase ):
    def test_disabled_skips( self ):
        with patch.object( jp, "_is_persistence_enabled", return_value=False ):
            jp.persist_job_created_from_metadata( "j1", "u1", { "agent_type": "deep_research" } )
        self.session.add.assert_not_called()

    def test_inserts_row( self ):
        self.session.get.return_value = None   # row absent → idempotent create INSERTs (row 2817b0f5)
        jp.persist_job_created_from_metadata( "j1", "u1", { "agent_type": "deep_research", "user_email": "e" } )
        self.session.add.assert_called_once()

    def test_exception_logged( self ):
        self.session.get.return_value = None   # reach the INSERT so add() raises
        self.session.add.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ) as mp:
            jp.persist_job_created_from_metadata( "j1", "u1", {} )
        self.assertTrue( any( "persist_job_created" in str( c ) for c in mp.call_args_list ) )


class TestPersistStarted( _PersistBase ):
    def test_disabled_skips( self ):
        with patch.object( jp, "_is_persistence_enabled", return_value=False ):
            jp.persist_job_started_from_metadata( "j1", {} )
        self.session.execute.assert_not_called()

    def test_updates( self ):
        jp.persist_job_started_from_metadata( "j1", {} )
        self.session.execute.assert_called_once()

    def test_exception_logged( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ) as mp:
            jp.persist_job_started_from_metadata( "j1", {} )
        self.assertTrue( any( "persist_job_started" in str( c ) for c in mp.call_args_list ) )


class _MergeWriterMixin:
    """Shared assertions for completed/stalled/failed merge-and-duration writers."""
    FN     = None
    PREFIX = None

    def _run_with_row( self, row ):
        result = MagicMock(); result.one_or_none.return_value = row
        # first execute → select(one_or_none); second execute → update
        self.session.execute.side_effect = [ result, MagicMock() ]
        getattr( jp, self.FN )( "j1", { "response_text": "r" } )

    def test_disabled_skips( self ):
        with patch.object( jp, "_is_persistence_enabled", return_value=False ):
            getattr( jp, self.FN )( "j1", {} )
        self.session.execute.assert_not_called()

    def test_with_row_and_started_at_computes_duration( self ):
        row = SimpleNamespace( started_at=datetime.now( timezone.utc ) - timedelta( seconds=5 ),
                               metadata_json={ "original_args": { "x": 1 } } )
        self._run_with_row( row )
        self.assertEqual( self.session.execute.call_count, 2 )

    def test_no_row_no_duration( self ):
        self._run_with_row( None )    # row None → existing metadata {} , no duration
        self.assertEqual( self.session.execute.call_count, 2 )

    def test_row_without_started_at( self ):
        self._run_with_row( SimpleNamespace( started_at=None, metadata_json=None ) )
        self.assertEqual( self.session.execute.call_count, 2 )

    def test_exception_logged( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ) as mp:
            getattr( jp, self.FN )( "j1", {} )
        self.assertTrue( any( self.PREFIX in str( c ) for c in mp.call_args_list ) )


class TestPersistCompleted( _MergeWriterMixin, _PersistBase ):
    FN     = "persist_job_completed_from_metadata"
    PREFIX = "persist_job_completed"


class TestPersistStalled( _MergeWriterMixin, _PersistBase ):
    FN     = "persist_job_stalled_from_metadata"
    PREFIX = "persist_job_stalled"


class TestPersistFailed( _MergeWriterMixin, _PersistBase ):
    FN     = "persist_job_failed_from_metadata"
    PREFIX = "persist_job_failed"

    def test_error_text_default_when_no_metadata( self ):
        row = SimpleNamespace( started_at=None, metadata_json={} )
        result = MagicMock(); result.one_or_none.return_value = row
        self.session.execute.side_effect = [ result, MagicMock() ]
        jp.persist_job_failed_from_metadata( "j1", None )   # metadata None → "Unknown error"
        self.assertEqual( self.session.execute.call_count, 2 )


class TestMarkInterruptedJobs( _PersistBase ):
    def test_classifies_pending_rows( self ):
        update_result = MagicMock(); update_result.rowcount = 2
        future = SimpleNamespace( id_hash="f", metadata_json={ "scheduled_at": "2099-01-01T00:00:00+00:00" } )
        catch  = SimpleNamespace( id_hash="c", metadata_json={ "scheduled_at": "2021-01-01T00:00:00+00:00" } )
        before = SimpleNamespace( id_hash="b", metadata_json={ "scheduled_at": "2019-01-01T00:00:00+00:00" },
                                  status=None, completed_at=None, updated_at=None )
        none_s = SimpleNamespace( id_hash="n", metadata_json={}, status=None, completed_at=None, updated_at=None )
        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [ future, catch, before, none_s ]
        self.session.execute.side_effect = [ update_result, select_result ]
        with patch.object( jp, "get_last_available",
                           return_value=datetime( 2020, 1, 1, tzinfo=timezone.utc ) ), \
             patch( "builtins.print" ):
            counts = jp.mark_interrupted_jobs()
        self.assertEqual( counts[ "running" ], 2 )
        self.assertEqual( counts[ "pending_preserved" ], 2 )     # future + no-schedule (row 9f06c28a: no-schedule now PRESERVED)
        self.assertEqual( counts[ "pending_catchup" ], 1 )
        self.assertEqual( counts[ "pending_interrupted" ], 1 )   # before-window only

    def test_all_zero_counts_skip_summary_prints( self ):
        # nothing running, no pending rows → total/preserved/catchup all 0 → all
        # three `if ... > 0:` summary prints take their FALSE arc.
        update_result = MagicMock(); update_result.rowcount = 0
        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = []
        self.session.execute.side_effect = [ update_result, select_result ]
        with patch.object( jp, "get_last_available", return_value=None ), \
             patch( "builtins.print" ) as mp:
            counts = jp.mark_interrupted_jobs()
        self.assertEqual( counts, { "running": 0, "pending_interrupted": 0,
                                    "pending_preserved": 0, "pending_catchup": 0 } )
        mp.assert_not_called()

    def test_exception_returns_zeroed( self ):
        with patch.object( jp, "get_db", side_effect=RuntimeError( "boom" ) ), \
             patch.object( jp, "get_last_available", return_value=None ), \
             patch( "builtins.print" ):
            counts = jp.mark_interrupted_jobs()
        self.assertEqual( counts, { "running": 0, "pending_interrupted": 0,
                                    "pending_preserved": 0, "pending_catchup": 0 } )


class TestIsFutureScheduled( unittest.TestCase ):
    def test_future( self ):
        self.assertTrue( jp._is_future_scheduled( "2099-01-01T00:00:00+00:00" ) )

    def test_past( self ):
        self.assertFalse( jp._is_future_scheduled( "2000-01-01T00:00:00+00:00" ) )

    def test_naive_now_path( self ):
        # pass an explicit naive `now` to exercise the now.tzinfo-None normalization
        self.assertTrue( jp._is_future_scheduled( "2099-01-01T00:00:00", now=datetime( 2026, 1, 1 ) ) )

    def test_parse_error_false( self ):
        self.assertFalse( jp._is_future_scheduled( "not-a-date" ) )


class TestGetRestorableJobs( _PersistBase ):
    def test_returns_all_pending( self ):
        # row 9f06c28a: get_restorable_jobs now returns EVERY surviving PENDING row —
        # future-scheduled AND immediate (no scheduled_at) — because mark_interrupted_jobs
        # has already flipped the anomalous cases to INTERRUPTED.
        r1 = SimpleNamespace( id_hash="a", job_type="t", user_id="u", user_email=None,
                              session_id=None, routing_command=None, question_text=None,
                              metadata_json={ "scheduled_at": "2099-01-01T00:00:00+00:00", "monopolize": True } )
        r2 = SimpleNamespace( id_hash="b", job_type="t", user_id="u", user_email="e",
                              session_id="s", routing_command="c", question_text="q",
                              metadata_json={} )   # no scheduled_at → still restorable (immediate)
        self.session.execute.return_value.scalars.return_value.all.return_value = [ r1, r2 ]
        out = jp.get_restorable_jobs()
        self.assertEqual( len( out ), 2 )
        self.assertEqual( { j[ "id_hash" ] for j in out }, { "a", "b" } )

    def test_exception_returns_empty( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertEqual( jp.get_restorable_jobs(), [] )


class TestGetActiveJobIdsByUser( _PersistBase ):
    def test_groups_by_user( self ):
        self.session.execute.return_value.all.return_value = [ ( "u1", "a" ), ( "u1", "b" ), ( "u2", "c" ) ]
        out = jp.get_active_job_ids_by_user()
        self.assertEqual( out, { "u1": [ "a", "b" ], "u2": [ "c" ] } )

    def test_exception_returns_empty( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertEqual( jp.get_active_job_ids_by_user(), {} )


class TestCountNotificationsForJobs( unittest.TestCase ):
    def test_empty_input( self ):
        self.assertEqual( jp._count_notifications_for_jobs( MagicMock(), [] ), {} )

    def test_counts_with_missing_filled_zero( self ):
        session = MagicMock()
        rows = [ SimpleNamespace( job_id="a", count=3 ) ]
        session.query.return_value.filter.return_value.group_by.return_value.all.return_value = rows
        out = jp._count_notifications_for_jobs( session, [ "a", "b" ] )
        self.assertEqual( out, { "a": 3, "b": 0 } )

    def test_exception_returns_empty( self ):
        session = MagicMock()
        session.query.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertEqual( jp._count_notifications_for_jobs( session, [ "a" ] ), {} )


class TestUnpackAndBuildRow( unittest.TestCase ):
    def test_unpack_defaults( self ):
        out = jp._unpack_metadata_json( None )
        self.assertIsNone( out[ "response_text" ] )
        self.assertFalse( out[ "monopolize" ] )

    def test_unpack_aliases( self ):
        out = jp._unpack_metadata_json( { "answer_conversational": "ans", "report_link": "rl", "monopolize": True } )
        self.assertEqual( out[ "response_text" ], "ans" )
        self.assertEqual( out[ "report_path" ], "rl" )
        self.assertTrue( out[ "monopolize" ] )

    def test_build_row_all_timestamps( self ):
        now = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        row = SimpleNamespace( id_hash="j", job_type="t", user_id="u", user_email="e",
                               session_id="s", routing_command="c", status="completed",
                               question_text="q", error=None, is_cache_hit=False,
                               duration_seconds=1.0, created_at=now, started_at=now,
                               completed_at=now, updated_at=now, metadata_json={} )
        out = jp._build_history_row( row, has_interactions=True )
        self.assertEqual( out[ "job_id" ], "j" )
        self.assertTrue( out[ "has_interactions" ] )
        self.assertEqual( out[ "timestamp" ], now.isoformat() )

    def test_build_row_none_timestamps( self ):
        row = SimpleNamespace( id_hash="j", job_type="t", user_id="u", user_email=None,
                               session_id=None, routing_command=None, status="x",
                               question_text=None, error=None, is_cache_hit=False,
                               duration_seconds=None, created_at=None, started_at=None,
                               completed_at=None, updated_at=None, metadata_json=None )
        out = jp._build_history_row( row, has_interactions=False )
        self.assertIsNone( out[ "created_at" ] )
        self.assertIsNone( out[ "timestamp" ] )


class TestQueryJobHistory( _PersistBase ):
    def _row( self ):
        now = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        return SimpleNamespace( id_hash="j1", job_type="t", user_id="u", user_email="e",
                                session_id="s", routing_command="c", status="completed",
                                question_text="q", error=None, is_cache_hit=False,
                                duration_seconds=1.0, created_at=now, started_at=now,
                                completed_at=now, updated_at=now, metadata_json={} )

    def test_all_filters( self ):
        count_result = MagicMock(); count_result.scalar.return_value = 1
        rows_result  = MagicMock(); rows_result.scalars.return_value.all.return_value = [ self._row() ]
        self.session.execute.side_effect = [ count_result, rows_result ]
        with patch.object( jp, "_count_notifications_for_jobs", return_value={ "j1": 2 } ):
            out = jp.query_job_history( user_id="u", status="completed", job_type="t",
                                        days=7, exclude_ids=[ "x" ], limit=10, offset=0 )
        self.assertEqual( out[ "total" ], 1 )
        self.assertTrue( out[ "jobs" ][ 0 ][ "has_interactions" ] )

    def test_no_filters( self ):
        count_result = MagicMock(); count_result.scalar.return_value = 0
        rows_result  = MagicMock(); rows_result.scalars.return_value.all.return_value = []
        self.session.execute.side_effect = [ count_result, rows_result ]
        with patch.object( jp, "_count_notifications_for_jobs", return_value={} ):
            out = jp.query_job_history()
        self.assertEqual( out, { "jobs": [], "total": 0 } )

    def test_exception_returns_empty( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertEqual( jp.query_job_history(), { "jobs": [], "total": 0 } )


class TestGetJobByIdHash( _PersistBase ):
    def test_found( self ):
        now = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        row = SimpleNamespace( id_hash="j", job_type="t", user_id="u", user_email="e",
                               session_id="s", routing_command="c", status="completed",
                               question_text="q", error=None, is_cache_hit=False,
                               duration_seconds=1.0, metadata_json={}, created_at=now,
                               started_at=None, completed_at=None, updated_at=None )
        self.session.execute.return_value.scalar.return_value = row
        out = jp.get_job_by_id_hash( "j" )
        self.assertEqual( out[ "id_hash" ], "j" )
        self.assertIsNone( out[ "started_at" ] )

    def test_not_found( self ):
        self.session.execute.return_value.scalar.return_value = None
        self.assertIsNone( jp.get_job_by_id_hash( "ghost" ) )

    def test_exception( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertIsNone( jp.get_job_by_id_hash( "j" ) )


class TestDeleteJobHistory( _PersistBase ):
    def test_deleted( self ):
        result = MagicMock(); result.rowcount = 1
        self.session.execute.return_value = result
        self.assertTrue( jp.delete_job_history( "j" ) )

    def test_not_found( self ):
        result = MagicMock(); result.rowcount = 0
        self.session.execute.return_value = result
        self.assertFalse( jp.delete_job_history( "j" ) )

    def test_exception( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertFalse( jp.delete_job_history( "j" ) )


class TestDeleteJobHistoryBulk( _PersistBase ):
    def test_with_filters( self ):
        result = MagicMock(); result.rowcount = 4
        self.session.execute.return_value = result
        self.assertEqual( jp.delete_job_history_bulk( user_id="u", days=7 ), 4 )

    def test_no_filters( self ):
        result = MagicMock(); result.rowcount = 9
        self.session.execute.return_value = result
        self.assertEqual( jp.delete_job_history_bulk(), 9 )

    def test_exception( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertEqual( jp.delete_job_history_bulk(), 0 )


class TestGetCheckpointForJob( _PersistBase ):
    def test_artifacts_checkpoint( self ):
        row = SimpleNamespace( status=JobState.STALLED.value,
                               metadata_json={ "artifacts": { "checkpoint": { "step": 3 } } } )
        self.session.execute.return_value.scalar.return_value = row
        self.assertEqual( jp.get_checkpoint_for_job( "j" ), { "step": 3 } )

    def test_top_level_checkpoint_fallback( self ):
        row = SimpleNamespace( status=JobState.STALLED.value,
                               metadata_json={ "checkpoint": { "step": 9 } } )
        self.session.execute.return_value.scalar.return_value = row
        self.assertEqual( jp.get_checkpoint_for_job( "j" ), { "step": 9 } )

    def test_not_stalled_returns_none( self ):
        row = SimpleNamespace( status="completed", metadata_json={} )
        self.session.execute.return_value.scalar.return_value = row
        self.assertIsNone( jp.get_checkpoint_for_job( "j" ) )

    def test_exception( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertIsNone( jp.get_checkpoint_for_job( "j" ) )


class TestGetOriginalArgsForJob( _PersistBase ):
    def test_found( self ):
        row = SimpleNamespace( metadata_json={ "original_args": { "x": 1 } },
                               routing_command="c", user_id="u", user_email="e", session_id="s" )
        self.session.execute.return_value.scalar.return_value = row
        out = jp.get_original_args_for_job( "j" )
        self.assertEqual( out[ "original_args" ], { "x": 1 } )

    def test_not_found( self ):
        self.session.execute.return_value.scalar.return_value = None
        self.assertIsNone( jp.get_original_args_for_job( "ghost" ) )

    def test_exception( self ):
        self.session.execute.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ):
            self.assertIsNone( jp.get_original_args_for_job( "j" ) )


def isolated_unit_test():
    """
    Run the job_persistence unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} job_persistence tests in {secs:.3f}s — {msg}" )
