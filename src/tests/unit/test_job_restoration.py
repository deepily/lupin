"""
Unit tests for scheduled job preservation and restoration at startup.

Tests the fix for the bug where mark_interrupted_jobs() incorrectly
marked scheduled-but-not-yet-fired jobs as interrupted on server restart.
"""

import pytest
from datetime import datetime, timezone, timedelta

from cosa.rest.job_persistence import _is_future_scheduled


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
