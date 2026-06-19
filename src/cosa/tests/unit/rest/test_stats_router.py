"""
Unit tests for the statistics router (`cosa.rest.routers.stats`).

Covers:
- `get_snapshot_mgr` — pulls snapshot_mgr off `lupin_app.main` (dual-key patched).
- `_format_duration` — all four magnitude bands (ms / s / minutes / hours).
- `get_time_saved_stats` — per-user aggregate: created-by-me counting, time saved
  for others, time saved for me within/outside the period, and the timestamp-parse
  fallback arm.
- `get_global_time_saved_stats` — global leaderboard: replay aggregation, unique
  users, the `replays > 0` gate, and the question-truncation ternary.

Zero external dependencies — the snapshot manager is boundary-mocked (no disk, no
GPU), the auth dependency is bypassed by passing `current_user` explicitly, and
`lupin_app.main` is patched via the dual-key helper (Gotcha 1).
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from types import SimpleNamespace
from datetime import datetime
import asyncio
import sys
import time

from cosa.rest.routers.stats import (
    router,
    get_snapshot_mgr,
    _format_duration,
    get_time_saved_stats,
    get_global_time_saved_stats,
)


def _patch_fastapi_main( mock_main ):
    """
    Robustly patch `lupin_app.main` for direct-call unit tests (Gotcha 1).

    `import lupin_app.main as m` binds via getattr(sys.modules['lupin_app'],
    'main'), NOT sys.modules['lupin_app.main'], so patching only the submodule
    entry is silently ignored once the real package is cached. Override BOTH keys.
    """
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


class TestGetSnapshotMgr( unittest.TestCase ):
    """
    Unit test for the snapshot-manager dependency.

    Ensures:
        - get_snapshot_mgr returns main_module.snapshot_mgr
    """

    def test_returns_main_module_snapshot_mgr( self ):
        """Ensures: the dependency reads snapshot_mgr off lupin_app.main."""
        mock_main = MagicMock()
        mock_main.snapshot_mgr = "THE_MGR"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_snapshot_mgr(), "THE_MGR" )


class TestFormatDuration( unittest.TestCase ):
    """
    Unit tests for `_format_duration` across all magnitude bands.

    Ensures:
        - <1s → ms, <1min → s, <1hr → minutes, else → hours
    """

    def test_milliseconds_band( self ):
        """Ensures: sub-second values render as integer milliseconds."""
        self.assertEqual( _format_duration( 500 ), "500ms" )

    def test_seconds_band( self ):
        """Ensures: sub-minute values render as fractional seconds."""
        self.assertEqual( _format_duration( 5000 ), "5.0s" )

    def test_minutes_band( self ):
        """Ensures: sub-hour values render as fractional minutes."""
        self.assertEqual( _format_duration( 120000 ), "2.0 minutes" )

    def test_hours_band( self ):
        """Ensures: hour-and-up values render as fractional hours."""
        self.assertEqual( _format_duration( 3600000 ), "1.0 hours" )


class TestGetTimeSavedStats( unittest.TestCase ):
    """
    Unit tests for the per-user time-saved endpoint.

    Requires:
        - get_snapshot_mgr boundary-mocked to return crafted snapshots

    Ensures:
        - solutions created by the user are counted
        - replays by others credit time_saved_for_others
        - replays the user benefited from are counted within the period
        - stale (pre-cutoff) replays are excluded; unparsable timestamps still count
        - falsy replay_stats/replay_history take the `or {}` / `or []` arms
    """

    def test_aggregates_user_stats_across_branches( self ):
        """
        Ensures:
            - All per-user aggregation branches are exercised in one realistic pass
        """
        today = datetime.now().strftime( "%Y-%m-%d" )

        # S1: created by "me"; one replay by other (credits others), one recent by me
        s1 = SimpleNamespace(
            user_id        = "me",
            replay_stats   = { "ignored": True },
            replay_history = [
                { "user_id": "other", "time_saved_ms": 100 },
                { "user_id": "me",    "time_saved_ms": 50, "timestamp": f"{today} @ 12:00:00 EST" },
            ],
        )
        # S2: created by other; one stale (T-format, pre-cutoff) + one unparsable, both by me
        s2 = SimpleNamespace(
            user_id        = "other",
            replay_history = [
                { "user_id": "me",      "time_saved_ms": 70, "timestamp": "2020-01-01T00:00:00" },
                { "user_id": "me",      "time_saved_ms": 30, "timestamp": "bad-date" },
                { "user_id": "someone", "time_saved_ms": 999 },
            ],
        )
        # S3: falsy replay_stats + replay_history → exercises the `or {}` / `or []` arms
        s3 = SimpleNamespace( user_id="nobody", replay_stats=None, replay_history=None )

        mgr = MagicMock()
        mgr.get_all_snapshots.return_value = [ s1, s2, s3 ]

        with patch( "cosa.rest.routers.stats.get_snapshot_mgr", return_value=mgr ):
            result = asyncio.run( get_time_saved_stats(
                current_user = { "uid": "me" },
                days         = 30,
            ) )

        self.assertEqual( result[ "user_id" ], "me" )
        self.assertEqual( result[ "period_days" ], 30 )
        self.assertEqual( result[ "solutions_created" ], 1 )                 # only S1
        self.assertEqual( result[ "solutions_replayed_by_others" ], 1 )      # the "other" entry in S1
        self.assertEqual( result[ "time_saved_for_others_ms" ], 100 )
        # me-benefited: S1 recent (+50) + S2 unparsable (+30); S2 stale (70) excluded
        self.assertEqual( result[ "total_time_saved_ms" ], 80 )
        self.assertEqual( result[ "total_replays_benefited" ], 2 )
        self.assertEqual( result[ "total_time_saved_formatted" ], "80ms" )
        self.assertEqual( result[ "time_saved_for_others_formatted" ], "100ms" )


class TestGetGlobalTimeSavedStats( unittest.TestCase ):
    """
    Unit tests for the global leaderboard endpoint.

    Ensures:
        - replay + time aggregation across all snapshots
        - unique users de-duplicated to a count
        - only replays>0 snapshots become leaderboard entries
        - long questions are truncated; None/empty questions take the `or ''` arm
    """

    def test_global_aggregation_and_leaderboard( self ):
        """
        Ensures:
            - The global stats aggregate correctly and the top-solutions list
              reflects the replays>0 gate + question-truncation ternary
        """
        long_q = "Q" * 60
        g1 = SimpleNamespace(
            replay_stats = { "total_replays": 5, "total_time_saved_ms": 2000, "unique_users": [ "a", "b" ] },
            question     = long_q,
        )
        g2 = SimpleNamespace(
            replay_stats = { "total_replays": 0, "total_time_saved_ms": 0, "unique_users": [] },
        )
        g3 = SimpleNamespace( replay_stats=None )                            # `or {}` arm; replays 0 → skipped
        g4 = SimpleNamespace(
            replay_stats = { "total_replays": 3, "total_time_saved_ms": 500, "unique_users": [ "a" ] },
            question     = None,                                             # `or ''` arm; len 0 → not truncated
        )

        mgr = MagicMock()
        mgr.get_all_snapshots.return_value = [ g1, g2, g3, g4 ]

        with patch( "cosa.rest.routers.stats.get_snapshot_mgr", return_value=mgr ):
            result = asyncio.run( get_global_time_saved_stats( current_user={ "uid": "me" } ) )

        self.assertEqual( result[ "total_solutions" ], 4 )
        self.assertEqual( result[ "total_replays" ], 8 )          # 5 + 0 + 3
        self.assertEqual( result[ "total_time_saved_ms" ], 2500 )
        self.assertEqual( result[ "unique_users" ], 2 )           # {a, b}
        self.assertEqual( result[ "total_time_saved_formatted" ], "2.5s" )

        # Only g1 (5 replays) and g4 (3 replays) make the leaderboard, sorted desc
        top = result[ "top_solutions" ]
        self.assertEqual( len( top ), 2 )
        self.assertEqual( top[ 0 ][ "replays" ], 5 )
        self.assertEqual( top[ 0 ][ "question" ], "Q" * 50 + "..." )   # truncated
        self.assertEqual( top[ 1 ][ "replays" ], 3 )
        self.assertEqual( top[ 1 ][ "question" ], "" )                # None → '' → untruncated


class TestStatsRouterRegistration( unittest.TestCase ):
    """
    Ensures:
        - The router prefix + both stats routes are registered
    """

    def test_router_prefix_and_routes( self ):
        """Ensures: /api/stats prefix with time-saved + global routes."""
        self.assertEqual( router.prefix, "/api/stats" )
        paths = { route.path for route in router.routes }
        self.assertIn( "/api/stats/time-saved", paths )
        self.assertIn( "/api/stats/time-saved/global", paths )


def isolated_unit_test():
    """
    Run the stats router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestGetSnapshotMgr, TestFormatDuration, TestGetTimeSavedStats,
            TestGetGlobalTimeSavedStats, TestStatsRouterRegistration,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL STATS ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME STATS ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 STATS ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Stats router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
