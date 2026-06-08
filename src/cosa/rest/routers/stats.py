"""
Statistics and Analytics API endpoints.

Provides time-saved dashboard data and solution replay analytics
for tracking the value of cached solutions.

Generated on: 2026-01-16
"""

from fastapi import APIRouter, Depends
from typing import Optional
from datetime import datetime, timedelta

from cosa.rest.auth import get_current_user

router = APIRouter( prefix="/api/stats", tags=["statistics"] )


def get_snapshot_mgr():
    """
    Dependency to get snapshot manager from main module.

    Requires:
        - lupin_app.main module is available
        - main_module has snapshot_mgr attribute

    Ensures:
        - Returns the snapshot manager instance
        - Provides access to solution snapshot data

    Raises:
        - ImportError if main module not available
        - AttributeError if snapshot_mgr not found
    """
    import lupin_app.main as main_module
    return main_module.snapshot_mgr


def _format_duration( ms: int ) -> str:
    """
    Format milliseconds as human-readable duration.

    Requires:
        - ms is a non-negative integer

    Ensures:
        - Returns appropriate time unit based on magnitude
        - Provides human-readable format
    """
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms / 1000:.1f}s"
    elif ms < 3600000:
        return f"{ms / 60000:.1f} minutes"
    else:
        return f"{ms / 3600000:.1f} hours"


@router.get(
    "/time-saved",
    summary     = "Get user time-saved stats",
    description = "Return per-user aggregate stats on time saved by cached solution replays."
)
async def get_time_saved_stats(
    current_user: dict = Depends( get_current_user ),
    days: int = 30
):
    """
    Get time saved statistics for the current user.

    Returns aggregate stats on how much time cached solutions have saved.

    Requires:
        - User is authenticated
        - days is a positive integer

    Ensures:
        - Returns user-specific time saved statistics
        - Includes both time saved FOR user and BY user for others
    """
    snapshot_mgr = get_snapshot_mgr()
    user_id = current_user[ "uid" ]

    # Get all snapshots
    all_snapshots = snapshot_mgr.get_all_snapshots()

    user_stats = {
        "user_id"                  : user_id,
        "period_days"              : days,
        "total_time_saved_ms"      : 0,
        "total_replays_benefited"  : 0,
        "solutions_created"        : 0,
        "solutions_replayed_by_others" : 0,
        "time_saved_for_others_ms" : 0
    }

    cutoff = datetime.now() - timedelta( days=days )

    for snapshot in all_snapshots:
        replay_stats   = getattr( snapshot, 'replay_stats', {} ) or {}
        replay_history = getattr( snapshot, 'replay_history', [] ) or []

        # Count solutions this user created
        if getattr( snapshot, 'user_id', '' ) == user_id:
            user_stats[ "solutions_created" ] += 1

            # Time saved for others by this user's solutions
            for entry in replay_history:
                if entry.get( "user_id" ) != user_id:
                    user_stats[ "solutions_replayed_by_others" ] += 1
                    user_stats[ "time_saved_for_others_ms" ] += entry.get( "time_saved_ms", 0 )

        # Time saved FOR this user (replays they benefited from)
        for entry in replay_history:
            if entry.get( "user_id" ) == user_id:
                # Check if within time period
                try:
                    timestamp_str = entry.get( "timestamp", "" )
                    # Parse timestamp format: "YYYY-MM-DD @ HH:MM:SS TZ"
                    date_part = timestamp_str.split( " @ " )[ 0 ] if " @ " in timestamp_str else timestamp_str.split( "T" )[ 0 ]
                    entry_time = datetime.strptime( date_part, "%Y-%m-%d" )
                    if entry_time >= cutoff:
                        user_stats[ "total_time_saved_ms" ] += entry.get( "time_saved_ms", 0 )
                        user_stats[ "total_replays_benefited" ] += 1
                except ( ValueError, IndexError ):
                    # If timestamp parsing fails, still count it
                    user_stats[ "total_time_saved_ms" ] += entry.get( "time_saved_ms", 0 )
                    user_stats[ "total_replays_benefited" ] += 1

    # Convert to human-readable
    user_stats[ "total_time_saved_formatted" ]      = _format_duration( user_stats[ "total_time_saved_ms" ] )
    user_stats[ "time_saved_for_others_formatted" ] = _format_duration( user_stats[ "time_saved_for_others_ms" ] )

    return user_stats


@router.get(
    "/time-saved/global",
    summary     = "Get global time-saved stats",
    description = "Return global time-saved leaderboard across all users with top replayed solutions."
)
async def get_global_time_saved_stats(
    current_user: dict = Depends( get_current_user )
):
    """
    Get global time saved statistics (all users combined).

    Available to all authenticated users for gamification/leaderboard.

    Requires:
        - User is authenticated

    Ensures:
        - Returns aggregate statistics across all users
        - Includes top solutions by replay count
    """
    snapshot_mgr = get_snapshot_mgr()

    all_snapshots = snapshot_mgr.get_all_snapshots()

    global_stats = {
        "total_solutions"          : len( all_snapshots ),
        "total_replays"            : 0,
        "total_time_saved_ms"      : 0,
        "unique_users"             : set(),
        "top_solutions"            : []
    }

    solution_scores = []

    for snapshot in all_snapshots:
        replay_stats = getattr( snapshot, 'replay_stats', {} ) or {}

        replays    = replay_stats.get( "total_replays", 0 )
        time_saved = replay_stats.get( "total_time_saved_ms", 0 )

        global_stats[ "total_replays" ] += replays
        global_stats[ "total_time_saved_ms" ] += time_saved

        for uid in replay_stats.get( "unique_users", [] ):
            global_stats[ "unique_users" ].add( uid )

        if replays > 0:
            question = getattr( snapshot, 'question', '' ) or ''
            solution_scores.append( {
                "question"             : question[ :50 ] + "..." if len( question ) > 50 else question,
                "replays"              : replays,
                "time_saved_ms"        : time_saved,
                "time_saved_formatted" : _format_duration( time_saved )
            } )

    # Top 10 most replayed solutions
    global_stats[ "top_solutions" ]            = sorted( solution_scores, key=lambda x: x[ "replays" ], reverse=True )[ :10 ]
    global_stats[ "unique_users" ]             = len( global_stats[ "unique_users" ] )
    global_stats[ "total_time_saved_formatted" ] = _format_duration( global_stats[ "total_time_saved_ms" ] )

    return global_stats


def quick_smoke_test():
    """Quick smoke test for stats router module."""
    import cosa.utils.util as du

    du.print_banner( "Stats Router Smoke Test", prepend_nl=True )

    try:
        print( "Testing module imports..." )
        from fastapi import APIRouter, Depends
        print( "✓ FastAPI imports successful" )

        print( "Testing router creation..." )
        assert router is not None
        assert router.prefix == "/api/stats"
        print( f"✓ Router created with prefix: {router.prefix}" )

        print( "Testing helper function..." )
        assert _format_duration( 500 ) == "500ms"
        assert _format_duration( 5000 ) == "5.0s"
        assert _format_duration( 120000 ) == "2.0 minutes"
        assert _format_duration( 3600000 ) == "1.0 hours"
        print( "✓ Duration formatting works correctly" )

        print( "Testing route definitions..." )
        routes = [ route.path for route in router.routes ]
        assert "/api/stats/time-saved" in routes
        assert "/api/stats/time-saved/global" in routes
        print( f"✓ Routes defined: {routes}" )

        print( "\n✓ Stats router smoke test completed successfully" )

    except Exception as e:
        print( f"✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
