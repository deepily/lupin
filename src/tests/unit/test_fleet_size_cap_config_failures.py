"""
Unit tests for the fail-soft config reads in fleet_size_cap.

A config manager that raises, or answers None, must degrade to the documented default rather than stop a spawn.

Requires:
    - lupin_mcp.fleet_size_cap is importable

Ensures:
    - each except / None arm of the three config readers is reached and returns its default
"""

import pytest

from lupin_mcp import fleet_size_cap as fsc


class _Cfg:
    """A config stub: `answers` maps key to value, and an Exception value is raised."""

    def __init__( self, answers ):
        self.answers = answers

    def get( self, key, default=None, return_type=None, silent=False ):
        answer = self.answers.get( key, default )
        if isinstance( answer, Exception ): raise answer
        return answer


def test_a_voice_id_lookup_that_raises_counts_that_persona_as_voiceless():
    """Three names, one voice id lookup raises and one is blank: only the good one is fillable."""
    cfg = _Cfg( {
        fsc.PERSONA_POOL_KEY                          : "sam, tiffany, maria",
        "cc session voice persona sam voice id"       : "vid-1",
        "cc session voice persona tiffany voice id"   : RuntimeError( "boom" ),
        "cc session voice persona maria voice id"     : "   ",
    } )
    assert fsc.pool_size( cfg ) == 1


def test_a_ceiling_lookup_that_raises_falls_back_to_the_default_ceiling():
    """The ceiling key raising is the default ceiling, not an exception."""
    assert fsc.resolve_fleet_ceiling( _Cfg( { fsc.FLEET_CEILING_KEY: RuntimeError( "x" ) } ) ) == fsc.DEFAULT_FLEET_CEILING


def test_a_ceiling_of_none_falls_back_to_the_default_ceiling_and_zero_is_floored_to_one():
    """None means unset (default); a configured 0 is clamped to the floor of 1."""
    assert fsc.resolve_fleet_ceiling( _Cfg( { fsc.FLEET_CEILING_KEY: None } ) ) == fsc.DEFAULT_FLEET_CEILING
    assert fsc.resolve_fleet_ceiling( _Cfg( { fsc.FLEET_CEILING_KEY: 0 } ) ) == 1


def test_a_disk_reader_that_raises_is_ignored_and_the_config_value_is_used():
    """disk_fn raising is treated as 'no fresher answer'; the config manager's cap stands."""
    def boom(): raise OSError( "disk gone" )
    cfg = _Cfg( { fsc.FLEET_CAP_KEY: 5 } )
    assert fsc.resolve_fleet_cap( cfg, disk_fn=boom ) == 5


def test_a_fresh_disk_value_beats_the_config_value_but_not_the_ceiling():
    """The disk answer wins over the stale config; it is still clamped to the ceiling."""
    cfg = _Cfg( { fsc.FLEET_CAP_KEY: 5, fsc.FLEET_CEILING_KEY: 10 } )
    assert fsc.resolve_fleet_cap( cfg, disk_fn=lambda: 7 ) == 7
    assert fsc.resolve_fleet_cap( cfg, disk_fn=lambda: 99 ) == 10


def test_a_cap_lookup_that_raises_or_is_none_falls_back_to_the_default_cap():
    """Raising and None both give the default cap (8, under the default ceiling of 18)."""
    assert fsc.resolve_fleet_cap( _Cfg( { fsc.FLEET_CAP_KEY: RuntimeError( "x" ) } ) ) == fsc.DEFAULT_FLEET_CAP
    assert fsc.resolve_fleet_cap( _Cfg( { fsc.FLEET_CAP_KEY: None } ) ) == fsc.DEFAULT_FLEET_CAP


def test_the_disk_cap_reader_answers_none_when_the_ini_reader_fails( monkeypatch ):
    """Any failure inside the fresh read becomes None, so the caller keeps the config value."""
    from lupin_mcp import fleet_cap_ini_io
    def boom( path, key ): raise RuntimeError( "unreadable" )
    monkeypatch.setattr( fleet_cap_ini_io, "read_int_from_disk", boom )
    assert fsc.default_disk_cap_reader() is None
