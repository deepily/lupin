#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.circuit_breaker.

CircuitBreaker monitors per-category decision health — error-rate spike and
confidence collapse — and auto-demotes trust via an injected trust_tracker.
The trust_tracker collaborator is mocked and the cooldown clock is driven by
controlled time.time() offsets stored directly in _tripped; no real I/O.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker


def _tracker( categories=None ):
    """
    Build a mock trust_tracker exposing a `categories` dict and a
    `demote_category` spy.
    """
    tt = MagicMock()
    tt.categories = categories if categories is not None else {}
    return tt


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
def test_init_stores_params_and_state():
    tt = _tracker()
    cb = CircuitBreaker(
        tt,
        error_rate_threshold=0.2,
        confidence_collapse_threshold=0.4,
        auto_demotion_levels=3,
        recovery_cooldown_seconds=60,
    )
    assert cb.trust_tracker is tt
    assert cb.error_rate_threshold == 0.2
    assert cb.confidence_collapse_threshold == 0.4
    assert cb.auto_demotion_levels == 3
    assert cb.recovery_cooldown_seconds == 60
    assert cb._tripped == {}
    assert cb._confidence_window == {}
    assert cb._confidence_window_size == 20


# ----------------------------------------------------------------------------
# is_tripped
# ----------------------------------------------------------------------------
def test_is_tripped_false_when_never_tripped():
    cb = CircuitBreaker( _tracker() )
    assert cb.is_tripped( "deploy" ) is False


def test_is_tripped_true_within_cooldown():
    cb = CircuitBreaker( _tracker(), recovery_cooldown_seconds=3600 )
    cb._tripped[ "deploy" ] = time.time()
    assert cb.is_tripped( "deploy" ) is True


def test_is_tripped_auto_recovers_after_cooldown():
    cb = CircuitBreaker( _tracker(), recovery_cooldown_seconds=60 )
    cb._tripped[ "deploy" ] = time.time() - 120
    assert cb.is_tripped( "deploy" ) is False
    assert "deploy" not in cb._tripped


def test_is_tripped_recovery_debug_prints( capsys ):
    cb = CircuitBreaker( _tracker(), recovery_cooldown_seconds=60, debug=True )
    cb._tripped[ "deploy" ] = time.time() - 120
    assert cb.is_tripped( "deploy" ) is False
    assert "recovered after cooldown" in capsys.readouterr().out


# ----------------------------------------------------------------------------
# record_confidence
# ----------------------------------------------------------------------------
def test_record_confidence_creates_window():
    cb = CircuitBreaker( _tracker() )
    cb.record_confidence( "deploy", 0.8 )
    assert cb._confidence_window[ "deploy" ] == [ 0.8 ]


def test_record_confidence_trims_to_window_size():
    cb = CircuitBreaker( _tracker() )
    for i in range( 25 ):
        cb.record_confidence( "deploy", i / 100.0 )
    window = cb._confidence_window[ "deploy" ]
    assert len( window ) == 20
    assert window[ -1 ] == 0.24      # most recent retained
    assert window[ 0 ] == 0.05       # oldest 5 trimmed


# ----------------------------------------------------------------------------
# get_average_confidence
# ----------------------------------------------------------------------------
def test_get_average_confidence_default_when_empty():
    cb = CircuitBreaker( _tracker() )
    assert cb.get_average_confidence( "deploy" ) == 1.0


def test_get_average_confidence_mean():
    cb = CircuitBreaker( _tracker() )
    cb.record_confidence( "deploy", 0.4 )
    cb.record_confidence( "deploy", 0.6 )
    assert cb.get_average_confidence( "deploy" ) == 0.5


# ----------------------------------------------------------------------------
# check
# ----------------------------------------------------------------------------
def test_check_returns_false_when_already_tripped():
    cb = CircuitBreaker( _tracker(), recovery_cooldown_seconds=3600 )
    cb._tripped[ "deploy" ] = time.time()
    assert cb.check( "deploy" ) is False


def test_check_unknown_category_is_healthy():
    cb = CircuitBreaker( _tracker( {} ) )
    assert cb.check( "unknown" ) is True


def test_check_trips_on_error_rate_spike():
    cat = SimpleNamespace( total_decisions=10, error_rate=0.5 )
    tt = _tracker( { "deploy": cat } )
    cb = CircuitBreaker( tt, error_rate_threshold=0.15 )
    assert cb.check( "deploy" ) is False
    assert cb.is_tripped( "deploy" ) is True
    tt.demote_category.assert_called_once_with( "deploy", cb.auto_demotion_levels )


def test_check_trips_on_confidence_collapse():
    cat = SimpleNamespace( total_decisions=10, error_rate=0.0 )
    tt = _tracker( { "deploy": cat } )
    cb = CircuitBreaker( tt, error_rate_threshold=0.15, confidence_collapse_threshold=0.3 )
    for _ in range( 5 ):
        cb.record_confidence( "deploy", 0.1 )
    assert cb.check( "deploy" ) is False
    assert cb.is_tripped( "deploy" ) is True


def test_check_healthy_passes():
    cat = SimpleNamespace( total_decisions=10, error_rate=0.0 )
    tt = _tracker( { "deploy": cat } )
    cb = CircuitBreaker( tt, error_rate_threshold=0.15, confidence_collapse_threshold=0.3 )
    for _ in range( 5 ):
        cb.record_confidence( "deploy", 0.9 )
    assert cb.check( "deploy" ) is True
    assert cb.is_tripped( "deploy" ) is False


def test_check_skips_thresholds_with_insufficient_samples():
    # total_decisions < 10 → error check skipped; <5 confidences → confidence check skipped
    cat = SimpleNamespace( total_decisions=5, error_rate=0.9 )
    tt = _tracker( { "deploy": cat } )
    cb = CircuitBreaker( tt )
    for _ in range( 4 ):
        cb.record_confidence( "deploy", 0.0 )
    assert cb.check( "deploy" ) is True


def test_check_error_below_threshold_and_confidence_ok():
    # Exercises the FALSE arms of both inner threshold ifs (no trip).
    cat = SimpleNamespace( total_decisions=10, error_rate=0.1 )
    tt = _tracker( { "deploy": cat } )
    cb = CircuitBreaker( tt, error_rate_threshold=0.15, confidence_collapse_threshold=0.3 )
    for _ in range( 5 ):
        cb.record_confidence( "deploy", 0.95 )
    assert cb.check( "deploy" ) is True
    assert cb.is_tripped( "deploy" ) is False


# ----------------------------------------------------------------------------
# trip
# ----------------------------------------------------------------------------
def test_trip_records_demotes_and_invokes_callback():
    callback = MagicMock()
    tt = _tracker()
    cb = CircuitBreaker( tt, auto_demotion_levels=2, on_trip_callback=callback )
    cb.trip( "deploy", reason="boom" )
    assert "deploy" in cb._tripped
    tt.demote_category.assert_called_once_with( "deploy", 2 )
    callback.assert_called_once_with( "deploy", "boom" )


def test_trip_debug_prints_and_no_callback( capsys ):
    tt = _tracker()
    cb = CircuitBreaker( tt, debug=True )   # on_trip_callback is None
    cb.trip( "deploy", reason="reason-x" )
    out = capsys.readouterr().out
    assert "TRIPPED" in out
    assert "Demoted" in out


# ----------------------------------------------------------------------------
# reset
# ----------------------------------------------------------------------------
def test_reset_clears_trip_and_window():
    cb = CircuitBreaker( _tracker() )
    cb._tripped[ "deploy" ] = time.time()
    cb._confidence_window[ "deploy" ] = [ 0.5 ]
    cb.reset( "deploy" )
    assert "deploy" not in cb._tripped
    assert "deploy" not in cb._confidence_window


def test_reset_missing_category_is_safe():
    cb = CircuitBreaker( _tracker() )
    cb.reset( "never-seen" )
    assert cb._tripped == {}
    assert cb._confidence_window == {}


# ----------------------------------------------------------------------------
# get_status
# ----------------------------------------------------------------------------
def test_get_status_reports_tripped_and_clear_categories():
    cat_a = SimpleNamespace( total_decisions=0, error_rate=0.0 )
    cat_b = SimpleNamespace( total_decisions=0, error_rate=0.0 )
    tt = _tracker( { "a": cat_a, "b": cat_b } )
    cb = CircuitBreaker( tt, recovery_cooldown_seconds=3600 )
    cb._tripped[ "a" ] = time.time()       # a: tripped + within cooldown
    cb.record_confidence( "a", 0.5 )

    status = cb.get_status()

    assert status[ "a" ][ "tripped" ] is True
    assert status[ "a" ][ "cooldown_remaining" ] > 0
    assert status[ "a" ][ "avg_confidence" ] == 0.5
    assert status[ "b" ][ "tripped" ] is False
    assert status[ "b" ][ "cooldown_remaining" ] == 0
    assert status[ "b" ][ "avg_confidence" ] == 1.0
