"""
Lever E (notify backpressure) unit tests — messaging-coordination plane.

Covers the per-session sliding-window limiter + the config-driven gate, all with
injected time (deterministic) and stubbed config (no INI dependency where it
matters). Venue: :7999-eligible (pure unit).
"""

import pytest

import cosa.rest.notify_rate_limiter as nrl
from cosa.rest.notify_rate_limiter import NotifyRateLimiter


class TestSlidingWindow:

    def test_allows_under_cap( self ):
        rl = NotifyRateLimiter()
        for i in range( 3 ):
            allowed, ra = rl.check_and_record( "s", 3, 10, now=100.0 + i )
            assert allowed and ra is None

    def test_denies_at_cap_with_retry_after( self ):
        rl = NotifyRateLimiter()
        for _ in range( 3 ):
            rl.check_and_record( "s", 3, 10, now=100.0 )        # 3 hits at t=100
        allowed, ra = rl.check_and_record( "s", 3, 10, now=105.0 )  # 4th within window
        assert not allowed
        assert ra == pytest.approx( 5.0 )                       # 100 + 10 - 105

    def test_window_slides_prunes_old( self ):
        rl = NotifyRateLimiter()
        rl.check_and_record( "s", 1, 10, now=100.0 )
        allowed, ra = rl.check_and_record( "s", 1, 10, now=111.0 )  # old hit pruned
        assert allowed and ra is None

    def test_per_source_isolation( self ):
        rl = NotifyRateLimiter()
        rl.check_and_record( "a", 1, 10, now=100.0 )
        allowed, _ = rl.check_and_record( "b", 1, 10, now=100.0 )   # different source
        assert allowed

    def test_now_defaults_to_wall_clock( self ):
        rl = NotifyRateLimiter()
        allowed, ra = rl.check_and_record( "s", 5, 10 )            # now=None → time.time()
        assert allowed and ra is None

    def test_reset_one_source_and_all( self ):
        rl = NotifyRateLimiter()
        rl.check_and_record( "s", 1, 10, now=100.0 )
        rl.reset( "s" )
        assert rl.check_and_record( "s", 1, 10, now=100.5 )[ 0 ] is True
        rl.check_and_record( "x", 1, 10, now=100.0 )
        rl.reset()                                                # clear all
        assert rl.check_and_record( "x", 1, 10, now=100.5 )[ 0 ] is True


class TestCheckNotifyAllowed:

    def test_disabled_always_allows( self, monkeypatch ):
        monkeypatch.setattr( nrl, "_backpressure_config",
                             lambda: { "enabled": False, "max": 1, "window": 10, "retry_after": 5 } )
        assert nrl.check_notify_allowed( "s" ) == ( True, None )

    def test_allowed_then_denied( self, monkeypatch ):
        monkeypatch.setattr( nrl, "_backpressure_config",
                             lambda: { "enabled": True, "max": 1, "window": 10, "retry_after": 5 } )
        nrl._limiter.reset()
        a1, r1 = nrl.check_notify_allowed( "sess-e" )
        assert a1 is True and r1 is None
        a2, r2 = nrl.check_notify_allowed( "sess-e" )
        assert a2 is False and r2 is not None and r2 > 0
        nrl._limiter.reset()

    def test_denied_retry_none_falls_back_to_config_floor( self, monkeypatch ):
        monkeypatch.setattr( nrl, "_backpressure_config",
                             lambda: { "enabled": True, "max": 1, "window": 10, "retry_after": 7 } )
        monkeypatch.setattr( nrl._limiter, "check_and_record", lambda *a, **k: ( False, None ) )
        allowed, ra = nrl.check_notify_allowed( "s" )
        assert allowed is False and ra == 7.0


class TestBackpressureConfig:

    def test_reads_ini_values( self ):
        cfg = nrl._backpressure_config()
        assert cfg[ "enabled" ] is True
        assert cfg[ "max" ] == 60
        assert cfg[ "window" ] == 10.0
        assert cfg[ "retry_after" ] == 5

    def test_cached_on_unchanged_mtime( self ):
        # Second call with an unchanged INI mtime returns the cache without re-reading
        # (exercises the mtime-gate skip branch).
        a = nrl._backpressure_config()
        b = nrl._backpressure_config()
        assert a == b

    def test_fails_safe_on_error( self, monkeypatch ):
        import cosa.utils.util as cu
        def boom():
            raise RuntimeError( "no root" )
        monkeypatch.setattr( cu, "get_project_root", boom )
        cfg = nrl._backpressure_config()                          # must not raise
        assert isinstance( cfg, dict ) and "enabled" in cfg
