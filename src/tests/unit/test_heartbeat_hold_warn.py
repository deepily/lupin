#!/usr/bin/env python3
"""
Unit tests for the scoped loud-at-read warning.

Target: 100% line + branch + function coverage of
    src/lupin_cli/claude_code/hooks/lib/heartbeat_hold_warn.py

Venue: :7999-eligible (pure logic; every test injects base_dir=tmp_path so the
real /tmp is never touched).

What this guards: absent/unusable ttl → is_fresh False → is_honored False → the
session is poked despite holding. Twenty-two sessions lived that for four weeks in
total silence. The warning must fire ONCE — loud enough to be seen, never often
enough to become wallpaper.
"""
import pytest

from lupin_cli.claude_code.hooks.lib import heartbeat_hold_warn as hw
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import HOLD_MTIME_ANNOTATION


def _broken( mtime=1000.0 ):
    """A hold that CANNOT defend its session: no usable ttl_seconds."""
    return { "session_id": "s", "reason": "holding", HOLD_MTIME_ANNOTATION: mtime }


# ── _warn_state_path ──────────────────────────────────────────────────────────

def test_warn_state_path_uses_session_prefix( tmp_path ):
    p = hw._warn_state_path( "abc12345-6789-dead-beef", base_dir=tmp_path )
    assert p == tmp_path / "claude-hook-heartbeat-hold-ttl-warned-abc12345"


def test_warn_state_path_empty_session_collapses_to_zeros( tmp_path ):
    p = hw._warn_state_path( "", base_dir=tmp_path )
    assert p == tmp_path / "claude-hook-heartbeat-hold-ttl-warned-00000000"


def test_warn_state_path_defaults_to_tmp():
    assert hw._warn_state_path( "abc12345" ).parent == hw.WARN_STATE_DIR


def test_warn_state_file_never_collides_with_the_poke_cap_counter( tmp_path ):
    """María, 2026-06-04: separate budgets must never share a file. Same rule here —
    this marker has its OWN filename namespace."""
    from lupin_cli.claude_code.hooks.lib import heartbeat_poke_cap as pc
    assert hw._warn_state_path( "abc12345", base_dir=tmp_path ) \
        != pc._poke_count_path( "abc12345", base_dir=tmp_path )


# ── _hold_version_key ─────────────────────────────────────────────────────────

def test_hold_version_key_uses_mtime_annotation():
    assert hw._hold_version_key( _broken( mtime=1234.5 ) ) == repr( 1234.5 )


def test_hold_version_key_sentinel_when_mtime_absent_or_bool():
    assert hw._hold_version_key( { } )                                  == hw.NO_MTIME_SENTINEL
    assert hw._hold_version_key( { HOLD_MTIME_ANNOTATION: True } )      == hw.NO_MTIME_SENTINEL
    assert hw._hold_version_key( { HOLD_MTIME_ANNOTATION: "nope" } )    == hw.NO_MTIME_SENTINEL


# ── should_warn_unusable_ttl ──────────────────────────────────────────────────

def test_no_hold_never_warns( tmp_path ):
    """A session that never declared a hold is pokeable BY DESIGN — nothing is
    silently betraying it, so there is nothing to say."""
    assert hw.should_warn_unusable_ttl( "sid", None, base_dir=tmp_path ) is False
    assert hw.should_warn_unusable_ttl( "sid", { },  base_dir=tmp_path ) is False


def test_usable_ttl_never_warns( tmp_path ):
    """The healthy path stays silent — and costs nothing."""
    healthy = { "session_id": "s", "reason": "r", "ttl_seconds": 900 }
    assert hw.should_warn_unusable_ttl( "sid", healthy, base_dir=tmp_path ) is False
    assert not list( tmp_path.iterdir() )          # no state file written at all


def test_broken_ttl_warns_exactly_once_then_stays_silent( tmp_path ):
    """n=1. This is the property that makes a loud reader safe: it cannot become
    wallpaper, so it never earns the eye-roll that silences real alarms."""
    assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is True
    for _ in range( 5 ):
        assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is False


def test_rewritten_but_still_broken_hold_warns_once_more( tmp_path ):
    """Rate-limited per hold-MTIME, not per session-forever: an agent that rewrites
    its hold and STILL gets it wrong deserves exactly one more warning."""
    assert hw.should_warn_unusable_ttl( "sid", _broken( mtime=1000.0 ), base_dir=tmp_path ) is True
    assert hw.should_warn_unusable_ttl( "sid", _broken( mtime=1000.0 ), base_dir=tmp_path ) is False
    assert hw.should_warn_unusable_ttl( "sid", _broken( mtime=2000.0 ), base_dir=tmp_path ) is True
    assert hw.should_warn_unusable_ttl( "sid", _broken( mtime=2000.0 ), base_dir=tmp_path ) is False


def test_warning_is_scoped_per_session_not_global( tmp_path ):
    """The hook reads ONE hold — its own. Two sessions with broken holds each get
    their own single warning; neither silences the other."""
    assert hw.should_warn_unusable_ttl( "aaaaaaaa", _broken(), base_dir=tmp_path ) is True
    assert hw.should_warn_unusable_ttl( "bbbbbbbb", _broken(), base_dir=tmp_path ) is True
    assert hw.should_warn_unusable_ttl( "aaaaaaaa", _broken(), base_dir=tmp_path ) is False


def test_hold_with_no_mtime_annotation_warns_once( tmp_path ):
    no_mtime = { "session_id": "s", "reason": "r" }             # sentinel path
    assert hw.should_warn_unusable_ttl( "sid", no_mtime, base_dir=tmp_path ) is True
    assert hw.should_warn_unusable_ttl( "sid", no_mtime, base_dir=tmp_path ) is False


def test_unreadable_state_marker_is_treated_as_not_yet_warned( tmp_path, monkeypatch ):
    import pathlib
    hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path )       # marker now exists
    def _boom( self, *a, **k ): raise OSError( "read denied" )
    monkeypatch.setattr( pathlib.Path, "read_text", _boom )
    # Fails LOUD, not silent: a marker we cannot read must not suppress the warning.
    assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is True


def test_unwritable_state_still_warns( tmp_path, monkeypatch ):
    """Deliberate tradeoff: an unwritable /tmp is pathological, and the alternative
    to a repeated log line is restoring the four-week silence this exists to close."""
    import pathlib
    def _boom( self, *a, **k ): raise OSError( "write denied" )
    monkeypatch.setattr( pathlib.Path, "write_text", _boom )
    assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is True
    assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is True


# ── clear_warn_state ──────────────────────────────────────────────────────────

def test_clear_warn_state_allows_a_fresh_warning( tmp_path ):
    assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is True
    assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is False
    hw.clear_warn_state( "sid", base_dir=tmp_path )
    assert hw.should_warn_unusable_ttl( "sid", _broken(), base_dir=tmp_path ) is True


def test_clear_warn_state_is_idempotent_and_swallows_oserror( tmp_path ):
    hw.clear_warn_state( "never-warned", base_dir=tmp_path )       # absent → no-op
    ( tmp_path / "claude-hook-heartbeat-hold-ttl-warned-dirsid00" ).mkdir()
    hw.clear_warn_state( "dirsid00", base_dir=tmp_path )           # unlink raises → swallowed


# ── smoke ─────────────────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert hw.quick_smoke_test() is True
