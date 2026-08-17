"""
The bounded wait that stops a not-yet-ready database from killing boot.

Found 2026-08-17 on lupin-host-test: `lupin-rest-cloud-gpu` died at startup with
`connection to server on socket "/cloudsql/..." failed: Connection refused` and
`Application startup failed. Exiting.` The migration path connected exactly once,
so any transient unavailability was fatal.

On the cloud topologies the database is reached through a Cloud SQL Auth Proxy
sidecar. The compose file gates the app on `condition: service_healthy`, but
Docker's RESTART POLICY ignores depends_on — on a reboot or resume both
containers come back independently and the app can win the race.

Every test here injects sleep and clock, so the suite stays instant.
"""

import pytest

from cosa.rest.db.auto_migrate import (
    next_backoff,
    wait_for_database,
    DB_WAIT_INITIAL_BACKOFF,
    DB_WAIT_MAX_BACKOFF,
    DB_WAIT_TIMEOUT_SECONDS,
)


class FakeClock:
    """A monotonic clock that only moves when something sleeps on it."""

    def __init__( self ):
        self.t      = 0.0
        self.sleeps = []

    def now( self ):
        return self.t

    def sleep( self, seconds ):
        self.sleeps.append( seconds )
        self.t += seconds


class TestNextBackoff:

    def test_doubles( self ):
        assert next_backoff( 1.0, maximum=100 ) == 2.0

    def test_caps_at_the_maximum( self ):
        assert next_backoff( 64.0, maximum=8.0 ) == 8.0

    def test_never_exceeds_the_cap_however_large_the_input( self ):
        # The cap is what stops a long budget becoming one enormous sleep.
        for value in ( 8.0, 100.0, 1_000_000.0 ):
            assert next_backoff( value, maximum=8.0 ) <= 8.0

    def test_the_shipped_default_cap_is_reachable_from_the_shipped_start( self ):
        delay, steps = DB_WAIT_INITIAL_BACKOFF, 0
        while delay < DB_WAIT_MAX_BACKOFF and steps < 50:
            delay = next_backoff( delay )
            steps += 1
        assert delay == DB_WAIT_MAX_BACKOFF


class TestWaitForDatabase:

    def test_a_reachable_database_costs_nothing( self ):
        # The common case must not pay for this guard: no sleeps at all.
        clock = FakeClock()
        result = wait_for_database( lambda: "connected", sleep=clock.sleep, now=clock.now )
        assert result == "connected"
        assert clock.sleeps == []

    def test_returns_the_probe_result_so_callers_can_use_it( self ):
        # run_migrations_to_head unpacks this into (has_version_table, has_app_tables).
        clock = FakeClock()
        assert wait_for_database( lambda: ( True, False ),
                                  sleep=clock.sleep, now=clock.now ) == ( True, False )

    def test_retries_then_succeeds( self ):
        clock   = FakeClock()
        outcome = iter( [ OSError( "Connection refused" ),
                          OSError( "Connection refused" ),
                          "connected" ] )

        def probe():
            value = next( outcome )
            if isinstance( value, Exception ): raise value
            return value

        assert wait_for_database( probe, sleep=clock.sleep, now=clock.now ) == "connected"
        assert len( clock.sleeps ) == 2

    def test_backoff_grows_between_attempts( self ):
        clock = FakeClock()
        with pytest.raises( OSError ):
            wait_for_database( _always_refused, timeout=30.0, initial_backoff=1.0,
                               sleep=clock.sleep, now=clock.now )
        # Strictly increasing until the cap — that is what "backoff" means.
        assert clock.sleeps[ 0 ] < clock.sleeps[ 1 ] < clock.sleeps[ 2 ]

    def test_reraises_the_last_error_unchanged_when_the_budget_is_spent( self ):
        # Fail-loud survives: the operator sees the driver's own error, not a wrapper.
        clock = FakeClock()
        with pytest.raises( OSError, match="Connection refused" ):
            wait_for_database( _always_refused, timeout=5.0,
                               sleep=clock.sleep, now=clock.now )

    def test_never_sleeps_past_the_deadline( self ):
        clock = FakeClock()
        with pytest.raises( OSError ):
            wait_for_database( _always_refused, timeout=10.0, initial_backoff=4.0,
                               sleep=clock.sleep, now=clock.now )
        assert sum( clock.sleeps ) <= 10.0

    def test_a_zero_timeout_tries_once_and_raises( self ):
        # Degenerate but meaningful: no budget means no retry, and no hang.
        clock = FakeClock()
        with pytest.raises( OSError ):
            wait_for_database( _always_refused, timeout=0.0,
                               sleep=clock.sleep, now=clock.now )
        assert clock.sleeps == []

    def test_on_retry_reports_each_attempt( self ):
        clock, seen = FakeClock(), []
        outcome = iter( [ OSError( "boom" ), "connected" ] )

        def probe():
            value = next( outcome )
            if isinstance( value, Exception ): raise value
            return value

        wait_for_database( probe, sleep=clock.sleep, now=clock.now,
                           on_retry=lambda attempt, error, delay: seen.append( ( attempt, delay ) ) )
        assert seen == [ ( 1, DB_WAIT_INITIAL_BACKOFF ) ]

    def test_the_shipped_timeout_is_long_enough_to_outlast_a_sidecar_start( self ):
        # The proxy's own healthcheck allows a 20s start_period plus retries; a
        # budget shorter than that would re-introduce the very race this fixes.
        assert DB_WAIT_TIMEOUT_SECONDS >= 20.0


def _always_refused():
    raise OSError( "Connection refused" )
