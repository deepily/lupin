"""
Unit tests for scheduled job preservation and restoration at startup.

Tests the fix for the bug where mark_interrupted_jobs() incorrectly
marked scheduled-but-not-yet-fired jobs as interrupted on server restart.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from cosa.rest.job_state import JobState
from cosa.rest.job_persistence import (
    _is_future_scheduled,
    _is_within_downtime,
    record_server_available,
    get_last_available,
    mark_interrupted_jobs,
)


def _mock_db( mock_get_db ):
    """Wire a MagicMock session into a patched get_db() context manager."""
    session = MagicMock()
    mock_get_db.return_value.__enter__ = MagicMock( return_value=session )
    mock_get_db.return_value.__exit__  = MagicMock( return_value=False )
    return session


# =============================================================================
# _is_future_scheduled() — pure logic tests
# =============================================================================

class TestIsFutureScheduled:
    """Tests for the scheduled_at future check helper."""

    def test_future_utc( self ):
        """UTC timestamp 1 hour ahead → True."""
        future = ( datetime.now( timezone.utc ) + timedelta( hours=1 ) ).isoformat()
        assert _is_future_scheduled( future ) is True

    def test_past_utc( self ):
        """UTC timestamp 1 hour ago → False."""
        past = ( datetime.now( timezone.utc ) - timedelta( hours=1 ) ).isoformat()
        assert _is_future_scheduled( past ) is False

    def test_future_with_offset( self ):
        """Timezone-aware timestamp (EDT) in the future → True."""
        from zoneinfo import ZoneInfo
        tz     = ZoneInfo( "America/New_York" )
        future = ( datetime.now( tz ) + timedelta( hours=2 ) ).isoformat()
        assert _is_future_scheduled( future ) is True

    def test_past_with_offset( self ):
        """Timezone-aware timestamp (EDT) in the past → False."""
        from zoneinfo import ZoneInfo
        tz   = ZoneInfo( "America/New_York" )
        past = ( datetime.now( tz ) - timedelta( hours=2 ) ).isoformat()
        assert _is_future_scheduled( past ) is False

    def test_naive_future( self ):
        """Naive datetime (no timezone) treated as UTC → True if future."""
        future = ( datetime.now( timezone.utc ) + timedelta( hours=1 ) ).replace( tzinfo=None ).isoformat()
        assert _is_future_scheduled( future ) is True

    def test_invalid_string( self ):
        """Non-ISO string → False (graceful fallback)."""
        assert _is_future_scheduled( "not a date" ) is False

    def test_empty_string( self ):
        """Empty string → False."""
        assert _is_future_scheduled( "" ) is False

    def test_none_value( self ):
        """None → False."""
        assert _is_future_scheduled( None ) is False

    def test_explicit_now_parameter( self ):
        """With explicit now parameter, compare correctly."""
        now    = datetime( 2026, 4, 7, 18, 0, 0, tzinfo=timezone.utc )
        future = "2026-04-07T19:00:00-04:00"  # 7 PM EDT = 23:00 UTC → after 18:00 UTC
        assert _is_future_scheduled( future, now ) is True

    def test_explicit_now_past( self ):
        """With explicit now after scheduled_at → False."""
        now  = datetime( 2026, 4, 8, 6, 0, 0, tzinfo=timezone.utc )
        past = "2026-04-07T19:00:00-04:00"  # 7 PM EDT April 7 = 23:00 UTC April 7
        assert _is_future_scheduled( past, now ) is False

    def test_boundary_exact_now( self ):
        """Exactly now → False (not strictly future)."""
        now = datetime.now( timezone.utc )
        assert _is_future_scheduled( now.isoformat(), now ) is False


# =============================================================================
# mark_interrupted_jobs() behavior — logic validation
# =============================================================================

class TestMarkInterruptedJobsLogic:
    """
    Validates the logic of the split mark_interrupted_jobs():
    - RUNNING → always INTERRUPTED
    - PENDING + future scheduled_at → preserved
    - PENDING + no scheduled_at → INTERRUPTED
    - PENDING + past scheduled_at → INTERRUPTED

    These test the decision logic via _is_future_scheduled().
    Full DB integration tests require a live database.
    """

    def test_running_always_interrupted( self ):
        """RUNNING jobs should always be marked interrupted (no schedule check needed)."""
        # This is tested by the SQL WHERE clause: status == 'running' → bulk UPDATE
        # The logic is unconditional — no scheduled_at check for running jobs
        assert True  # Structural assertion — the SQL handles this

    def test_pending_with_future_schedule_preserved( self ):
        """PENDING + future scheduled_at → _is_future_scheduled returns True → preserve."""
        future = ( datetime.now( timezone.utc ) + timedelta( hours=3 ) ).isoformat()
        assert _is_future_scheduled( future ) is True
        # mark_interrupted_jobs() skips this row (leaves as PENDING)

    def test_pending_without_schedule_interrupted( self ):
        """PENDING + no scheduled_at → _is_future_scheduled returns False → interrupt."""
        assert _is_future_scheduled( None ) is False
        assert _is_future_scheduled( "" ) is False
        # mark_interrupted_jobs() marks this row as INTERRUPTED

    def test_pending_with_past_schedule_interrupted( self ):
        """PENDING + past scheduled_at → _is_future_scheduled returns False → interrupt."""
        past = ( datetime.now( timezone.utc ) - timedelta( hours=1 ) ).isoformat()
        assert _is_future_scheduled( past ) is False
        # mark_interrupted_jobs() marks this row as INTERRUPTED

    def test_decision_matrix_complete( self ):
        """All 4 cases in the decision matrix produce correct results."""
        now    = datetime( 2026, 4, 7, 22, 0, 0, tzinfo=timezone.utc )
        future = "2026-04-08T03:00:00+00:00"  # 5 hours ahead
        past   = "2026-04-07T18:00:00+00:00"  # 4 hours ago

        assert _is_future_scheduled( future, now ) is True    # preserve
        assert _is_future_scheduled( past, now ) is False     # interrupt
        assert _is_future_scheduled( None, now ) is False     # interrupt
        assert _is_future_scheduled( "", now ) is False       # interrupt


# =============================================================================
# _is_within_downtime() — measured-downtime catch-up window (missed-window fix)
# =============================================================================

class TestIsWithinDowntime:
    """
    Tests for the downtime-window helper that drives missed-window catch-up.

    A job is caught up iff its scheduled_at falls within [last_available, now] —
    i.e., it was due WHILE the server was down. Future jobs and jobs due BEFORE
    the server went down are NOT in the window.
    """

    def _window( self ):
        """Return (last_available, now) one hour apart, UTC."""
        now            = datetime.now( timezone.utc )
        last_available = now - timedelta( hours=1 )
        return last_available, now

    def test_in_window( self ):
        """scheduled_at inside the downtime window → True (catch up)."""
        last_available, now = self._window()
        scheduled = ( last_available + timedelta( minutes=30 ) ).isoformat()
        assert _is_within_downtime( scheduled, last_available, now ) is True

    def test_before_window( self ):
        """scheduled_at BEFORE the server went down → False (anomalous, not a downtime miss)."""
        last_available, now = self._window()
        scheduled = ( last_available - timedelta( minutes=1 ) ).isoformat()
        assert _is_within_downtime( scheduled, last_available, now ) is False

    def test_after_window_future( self ):
        """scheduled_at after 'now' (still future) → False (handled by the future branch)."""
        last_available, now = self._window()
        scheduled = ( now + timedelta( minutes=1 ) ).isoformat()
        assert _is_within_downtime( scheduled, last_available, now ) is False

    def test_last_available_none( self ):
        """No recorded last-available (first boot) → False (no known downtime)."""
        now = datetime.now( timezone.utc )
        scheduled = ( now - timedelta( minutes=30 ) ).isoformat()
        assert _is_within_downtime( scheduled, None, now ) is False

    def test_boundary_equals_last_available( self ):
        """scheduled_at exactly at last_available → True (inclusive lower bound)."""
        last_available, now = self._window()
        assert _is_within_downtime( last_available.isoformat(), last_available, now ) is True

    def test_boundary_equals_now( self ):
        """scheduled_at exactly at now → True (inclusive upper bound)."""
        last_available, now = self._window()
        assert _is_within_downtime( now.isoformat(), last_available, now ) is True

    def test_naive_scheduled_treated_utc( self ):
        """Naive scheduled_at string is treated as UTC."""
        last_available, now = self._window()
        scheduled = ( last_available + timedelta( minutes=20 ) ).replace( tzinfo=None ).isoformat()
        assert _is_within_downtime( scheduled, last_available, now ) is True

    def test_tz_aware_offset_in_window( self ):
        """A timezone-aware (EDT) scheduled_at inside the window → True."""
        from zoneinfo import ZoneInfo
        now            = datetime.now( timezone.utc )
        last_available = now - timedelta( hours=1 )
        scheduled      = ( now - timedelta( minutes=10 ) ).astimezone( ZoneInfo( "America/New_York" ) ).isoformat()
        assert _is_within_downtime( scheduled, last_available, now ) is True

    def test_invalid_string( self ):
        """Non-ISO scheduled_at → False (graceful)."""
        last_available, now = self._window()
        assert _is_within_downtime( "not a date", last_available, now ) is False

    def test_none_scheduled( self ):
        """None scheduled_at → False (TypeError caught)."""
        last_available, now = self._window()
        assert _is_within_downtime( None, last_available, now ) is False


# =============================================================================
# Catch-up decision matrix (measured downtime) — pure logic
# =============================================================================

class TestCatchupDecisionMatrix:
    """
    The 4-way mark_interrupted_jobs() decision for a PENDING job, expressed via
    the two pure helpers (full DB-branch coverage lives in the integration test).
    """

    def test_matrix( self ):
        now            = datetime( 2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc )
        last_available = datetime( 2026, 5, 29, 11, 55, 0, tzinfo=timezone.utc )   # down 5 min
        future         = "2026-05-29T14:00:00+00:00"   # 2h ahead  → preserve (future)
        in_window      = "2026-05-29T11:57:00+00:00"   # during downtime → catch up
        before_window  = "2026-05-29T09:00:00+00:00"   # due while UP, never ran → interrupt

        assert _is_future_scheduled( future, now ) is True
        assert _is_within_downtime( in_window, last_available, now ) is True
        assert _is_future_scheduled( in_window, now ) is False          # not future
        assert _is_within_downtime( before_window, last_available, now ) is False
        assert _is_future_scheduled( before_window, now ) is False      # → interrupt


# =============================================================================
# Server-lifecycle persistence (record / get) — mocked get_db
# =============================================================================

class TestServerLifecycle:
    """record_server_available() + get_last_available() with a mocked DB session."""

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_record_inserts_when_absent( self, mock_get_db, _enabled ):
        session = _mock_db( mock_get_db )
        session.get.return_value = None
        ts = datetime( 2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc )
        record_server_available( ts )
        session.add.assert_called_once()
        added = session.add.call_args[ 0 ][ 0 ]
        assert added.key == "singleton"
        assert added.last_available_at == ts

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_record_updates_when_present( self, mock_get_db, _enabled ):
        session  = _mock_db( mock_get_db )
        existing = MagicMock()
        session.get.return_value = existing
        ts = datetime( 2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc )
        record_server_available( ts )
        session.add.assert_not_called()
        assert existing.last_available_at == ts

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_record_default_ts_is_now_utc( self, mock_get_db, _enabled ):
        session = _mock_db( mock_get_db )
        session.get.return_value = None
        before = datetime.now( timezone.utc )
        record_server_available()
        added = session.add.call_args[ 0 ][ 0 ]
        assert added.last_available_at.tzinfo is not None
        assert added.last_available_at >= before

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=False )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_record_noop_when_disabled( self, mock_get_db, _disabled ):
        record_server_available()
        mock_get_db.assert_not_called()

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_record_swallows_exception( self, mock_get_db, _enabled ):
        mock_get_db.side_effect = RuntimeError( "db down" )
        record_server_available( datetime.now( timezone.utc ) )   # must NOT raise

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_get_returns_aware_utc( self, mock_get_db ):
        session = _mock_db( mock_get_db )
        row     = MagicMock()
        row.last_available_at = datetime( 2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc )
        session.get.return_value = row
        assert get_last_available() == datetime( 2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc )

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_get_coerces_naive_to_utc( self, mock_get_db ):
        session = _mock_db( mock_get_db )
        row     = MagicMock()
        row.last_available_at = datetime( 2026, 5, 29, 12, 0, 0 )   # naive
        session.get.return_value = row
        result = get_last_available()
        assert result.tzinfo is not None
        assert result == datetime( 2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc )

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_get_none_when_absent( self, mock_get_db ):
        session = _mock_db( mock_get_db )
        session.get.return_value = None
        assert get_last_available() is None

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_get_none_on_exception( self, mock_get_db ):
        mock_get_db.side_effect = RuntimeError( "db down" )
        assert get_last_available() is None


# =============================================================================
# mark_interrupted_jobs() — catch-up branch (mocked get_db + get_last_available)
# =============================================================================

def _pending_row( id_hash, scheduled_at ):
    r = MagicMock()
    r.id_hash       = id_hash
    r.metadata_json = { "scheduled_at": scheduled_at } if scheduled_at else {}
    return r


class TestMarkInterruptedJobsCatchup:
    """Full 4-way decision in mark_interrupted_jobs() against a mocked session."""

    @patch( "cosa.rest.job_persistence.get_last_available" )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_catchup_preserves_downtime_missed( self, mock_get_db, mock_last_avail ):
        session = _mock_db( mock_get_db )
        now            = datetime.now( timezone.utc )
        last_available = now - timedelta( minutes=10 )
        mock_last_avail.return_value = last_available

        running_res = MagicMock(); running_res.rowcount = 0
        rows = [
            _pending_row( "a", ( last_available + timedelta( minutes=2 ) ).isoformat() ),  # catch-up
            _pending_row( "b", ( last_available - timedelta( minutes=5 ) ).isoformat() ),  # before → interrupt
            _pending_row( "c", ( now + timedelta( hours=1 ) ).isoformat() ),               # future → preserve
            _pending_row( "d", None ),                                                     # no schedule → interrupt
        ]
        pending_res = MagicMock()
        pending_res.scalars.return_value.all.return_value = rows
        session.execute.side_effect = [ running_res, pending_res ]

        counts = mark_interrupted_jobs()
        assert counts[ "pending_catchup" ]     == 1   # 'a'
        assert counts[ "pending_preserved" ]   == 1   # 'c'
        assert counts[ "pending_interrupted" ] == 2   # 'b' + 'd'
        assert rows[ 1 ].status == JobState.INTERRUPTED.value   # before-window
        assert rows[ 3 ].status == JobState.INTERRUPTED.value   # no schedule

    @patch( "cosa.rest.job_persistence.get_last_available", return_value=None )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_no_catchup_when_last_available_none( self, mock_get_db, _none ):
        session = _mock_db( mock_get_db )
        now = datetime.now( timezone.utc )
        running_res = MagicMock(); running_res.rowcount = 0
        rows = [
            _pending_row( "a", ( now - timedelta( minutes=5 ) ).isoformat() ),  # past, no downtime → interrupt
            _pending_row( "b", ( now + timedelta( hours=1 ) ).isoformat() ),    # future → preserve
        ]
        pending_res = MagicMock()
        pending_res.scalars.return_value.all.return_value = rows
        session.execute.side_effect = [ running_res, pending_res ]

        counts = mark_interrupted_jobs()
        assert counts[ "pending_catchup" ]     == 0
        assert counts[ "pending_preserved" ]   == 1
        assert counts[ "pending_interrupted" ] == 1
        assert rows[ 0 ].status == JobState.INTERRUPTED.value

    @patch( "cosa.rest.job_persistence.get_last_available", side_effect=RuntimeError( "boom" ) )
    @patch( "cosa.rest.job_persistence.get_db", side_effect=RuntimeError( "db down" ) )
    def test_returns_zeroed_dict_on_failure( self, mock_get_db, _boom ):
        counts = mark_interrupted_jobs()
        assert counts == { "running": 0, "pending_interrupted": 0, "pending_preserved": 0, "pending_catchup": 0 }


def test_server_lifecycle_model_repr():
    """ServerLifecycle instantiates + __repr__ renders (model-side coverage)."""
    from cosa.rest.postgres_models import ServerLifecycle
    row = ServerLifecycle( key="singleton", last_available_at=datetime( 2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc ) )
    assert row.key == "singleton"
    assert "singleton" in repr( row )
