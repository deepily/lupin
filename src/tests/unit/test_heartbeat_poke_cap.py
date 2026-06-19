#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Hook poke-cap counter.

Target: 100% line + branch + function coverage of
    src/lupin_cli/claude_code/hooks/lib/heartbeat_poke_cap.py

All tests inject base_dir (tmp_path) so they never touch real /tmp state.
"""
from lupin_cli.claude_code.hooks.lib import heartbeat_poke_cap as c


# ── _poke_count_path ──────────────────────────────────────────────────────────

def test_path_with_base_dir_uses_session_prefix( tmp_path ):
    p = c._poke_count_path( "abcdefghijkl", base_dir=tmp_path )
    assert p == tmp_path / "claude-hook-heartbeat-poke-count-abcdefgh"   # first 8 chars


def test_path_empty_session_uses_zero_suffix( tmp_path ):
    p = c._poke_count_path( "", base_dir=tmp_path )
    assert p == tmp_path / "claude-hook-heartbeat-poke-count-00000000"


def test_path_default_base_dir_is_tmp():
    p = c._poke_count_path( "abcdefgh" )
    assert p == c.COUNTER_DIR / "claude-hook-heartbeat-poke-count-abcdefgh"


# ── get_poke_count ────────────────────────────────────────────────────────────

def test_get_count_absent_is_zero( tmp_path ):
    assert c.get_poke_count( "nope", base_dir=tmp_path ) == 0


def test_get_count_reads_value( tmp_path ):
    ( tmp_path / "claude-hook-heartbeat-poke-count-sid12345" ).write_text( "2" )
    assert c.get_poke_count( "sid12345", base_dir=tmp_path ) == 2


def test_get_count_non_integer_is_zero( tmp_path ):
    ( tmp_path / "claude-hook-heartbeat-poke-count-sid12345" ).write_text( "not-a-number" )
    assert c.get_poke_count( "sid12345", base_dir=tmp_path ) == 0


def test_get_count_oserror_is_zero( tmp_path ):
    # Path exists but is a directory → read_text raises OSError
    ( tmp_path / "claude-hook-heartbeat-poke-count-dirsid12" ).mkdir()
    assert c.get_poke_count( "dirsid12", base_dir=tmp_path ) == 0


# ── increment_poke_count ──────────────────────────────────────────────────────

def test_increment_from_zero( tmp_path ):
    assert c.increment_poke_count( "s1", base_dir=tmp_path ) == 1
    assert c.increment_poke_count( "s1", base_dir=tmp_path ) == 2


def test_increment_oserror_returns_zero( tmp_path ):
    # base_dir does not exist → write_text raises OSError → return 0
    assert c.increment_poke_count( "s2", base_dir=tmp_path / "missing" ) == 0


# ── reset_poke_count ──────────────────────────────────────────────────────────

def test_reset_removes_file( tmp_path ):
    c.increment_poke_count( "s3", base_dir=tmp_path )
    c.reset_poke_count( "s3", base_dir=tmp_path )
    assert c.get_poke_count( "s3", base_dir=tmp_path ) == 0


def test_reset_absent_is_noop( tmp_path ):
    c.reset_poke_count( "ghost", base_dir=tmp_path )   # must not raise


def test_reset_oserror_swallowed( tmp_path ):
    # Path is a directory → unlink raises OSError, must be swallowed
    ( tmp_path / "claude-hook-heartbeat-poke-count-cdirsid1" ).mkdir()
    c.reset_poke_count( "cdirsid1", base_dir=tmp_path )   # must not raise


# ── is_cap_reached ────────────────────────────────────────────────────────────

def test_is_cap_reached_under_and_at( tmp_path ):
    c.increment_poke_count( "s4", base_dir=tmp_path )   # 1
    c.increment_poke_count( "s4", base_dir=tmp_path )   # 2
    assert c.is_cap_reached( "s4", cap=3, base_dir=tmp_path ) is False
    c.increment_poke_count( "s4", base_dir=tmp_path )   # 3
    assert c.is_cap_reached( "s4", cap=3, base_dir=tmp_path ) is True


def test_is_cap_reached_default_cap( tmp_path ):
    for _ in range( c.DEFAULT_POKE_CAP ):
        c.increment_poke_count( "s5", base_dir=tmp_path )
    assert c.is_cap_reached( "s5", base_dir=tmp_path ) is True


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert c.quick_smoke_test() is True
