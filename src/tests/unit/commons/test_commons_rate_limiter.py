"""
Unit tests for commons_rate_limiter (Phase 2 step 2).

Per AC3 + F6 (Pass 1) of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md.

Coverage target: 100% lines + branches + functions (AC12 hard gate).
"""

import threading
import time

import pytest

from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter


# ---------- Construction + validation ----------


def test_init_rejects_zero_window():
    """Constructor raises on non-positive window_seconds."""
    with pytest.raises( ValueError, match="window_seconds must be positive" ):
        CommonsBroadcastRateLimiter( window_seconds=0 )


def test_init_rejects_negative_window():
    """Constructor raises on negative window_seconds."""
    with pytest.raises( ValueError, match="window_seconds must be positive" ):
        CommonsBroadcastRateLimiter( window_seconds=-1.0 )


def test_init_accepts_float_window():
    """Constructor stores window_seconds as float."""
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    assert rl.window_seconds == 30.0
    assert isinstance( rl.window_seconds, float )


# ---------- Core sliding-window behavior (AC3) ----------


def test_first_call_allowed():
    """First check_and_record for a fresh user returns (True, None)."""
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    allowed, retry = rl.check_and_record( "userA" )
    assert allowed is True
    assert retry is None


def test_second_call_within_window_blocked():
    """Second call within window returns (False, retry_seconds_remaining)."""
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    rl.check_and_record( "userA" )
    allowed, retry = rl.check_and_record( "userA" )
    assert allowed is False
    assert retry is not None
    assert 0 < retry <= 30


def test_third_call_after_window_allowed( monkeypatch ):
    """Third call after window expiry succeeds (clock monkeypatched)."""
    fake_now = [ 1000.0 ]
    monkeypatch.setattr( "cosa.rest.commons_rate_limiter.time.monotonic", lambda: fake_now[ 0 ] )

    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    allowed1, _ = rl.check_and_record( "userA" )
    fake_now[ 0 ] += 15  # mid-window
    allowed2, _ = rl.check_and_record( "userA" )
    fake_now[ 0 ] += 20  # past the 30s window (15 + 20 = 35 > 30)
    allowed3, _ = rl.check_and_record( "userA" )

    assert allowed1 is True
    assert allowed2 is False
    assert allowed3 is True


def test_per_user_isolation():
    """Two users' state is independent."""
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    rl.check_and_record( "userA" )
    # userB's first call should be allowed even though userA just posted
    allowed, retry = rl.check_and_record( "userB" )
    assert allowed is True
    assert retry is None


# ---------- reset() test hook (F6) ----------


def test_reset_clears_specific_user():
    """reset(user_id) clears that user only; other users untouched."""
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    rl.check_and_record( "userA" )
    rl.check_and_record( "userB" )
    assert rl._peek( "userA" ) is not None
    assert rl._peek( "userB" ) is not None

    rl.reset( "userA" )
    assert rl._peek( "userA" ) is None
    assert rl._peek( "userB" ) is not None

    # userA can now post freely again
    allowed, _ = rl.check_and_record( "userA" )
    assert allowed is True


def test_reset_all_clears_everything():
    """reset() with no user_id clears all state."""
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    rl.check_and_record( "userA" )
    rl.check_and_record( "userB" )
    rl.reset()
    assert rl._peek( "userA" ) is None
    assert rl._peek( "userB" ) is None


def test_reset_missing_user_silent():
    """reset(<unknown>) does not raise."""
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    rl.reset( "never-seen-this-user" )  # should not raise


# ---------- Retry-After value correctness ----------


def test_retry_after_decreases_over_time( monkeypatch ):
    """retry_after gets smaller as we approach the window boundary."""
    fake_now = [ 1000.0 ]
    monkeypatch.setattr( "cosa.rest.commons_rate_limiter.time.monotonic", lambda: fake_now[ 0 ] )

    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    rl.check_and_record( "userA" )

    fake_now[ 0 ] += 5
    _, retry1 = rl.check_and_record( "userA" )
    fake_now[ 0 ] += 10  # now 15s in
    _, retry2 = rl.check_and_record( "userA" )

    assert retry1 > retry2  # 25 > 15
    assert abs( retry1 - 25.0 ) < 0.01
    assert abs( retry2 - 15.0 ) < 0.01


# ---------- Thread-safety smoke ----------


def test_concurrent_check_and_record_one_wins():
    """
    Under high contention from N threads racing for the same user,
    exactly ONE thread sees allowed=True and the rest see allowed=False.
    """
    rl = CommonsBroadcastRateLimiter( window_seconds=30 )
    results = [ ]
    barrier = threading.Barrier( 10 )

    def worker():
        barrier.wait()  # synchronize start
        allowed, _ = rl.check_and_record( "userA" )
        results.append( allowed )

    threads = [ threading.Thread( target=worker ) for _ in range( 10 ) ]
    for t in threads: t.start()
    for t in threads: t.join( timeout=5 )

    allowed_count = sum( 1 for r in results if r is True )
    assert allowed_count == 1, f"expected exactly 1 winner, got {allowed_count}"
    assert len( results ) == 10
