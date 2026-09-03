#!/usr/bin/env python3
"""
THE FLEET SIZE CAP — one number, enforced at spawn, reaping nobody.

Row `0ab1a095`. Rick set a cap of four by voice, counted six workers, and had to read two
managers the riot act to get it back. These arms hold the three rulings and the one
consequence he did not ask about.

⚠️ WHAT THIS FILE DELIBERATELY DOES NOT TEST: that anything is REAPED. Ruling 2 is that
over-cap refuses new spawns and leaves running seats alone, so "nothing was terminated" is
the specified behaviour rather than a gap. `test_lowering_the_cap_below_the_live_count_...`
is the arm that pins it.

VENUE: :7999-eligible — pure functions with injected seams, no bridge, no fleet, no server.
"""
import pytest

from lupin_mcp import fleet_size_cap as fsc


class _Config:
    """A ConfigurationManager double with the same .get shape the spawner uses."""
    def __init__( self, values=None, raises=False ):
        self._values = values or { }
        self._raises = raises
    def get( self, key, default=None, return_type=None, silent=False ):
        if self._raises: raise RuntimeError( "config exploded" )
        return self._values.get( key, default )


def _sessions( n, prefix="s" ):
    """n live sessions in find_active_voice_persona_sessions()'s (path, id, persona) shape."""
    return [ ( f"/bridges/cc-{i}.json", f"{prefix}{i}", { "name": f"p{i}" } ) for i in range( n ) ]


def _managers( *ids ):
    wanted = set( ids )
    return lambda session_id: session_id in wanted


# ── THE CEILING IS DERIVED, NOT TYPED ────────────────────────────────────────────

def test_the_ceiling_is_COUNTED_from_the_persona_pool_not_hardcoded():
    """
    Rick said 18 and said the maximum must track the REAL ceiling rather than repeat a
    number. This asserts the derivation, so the arm keeps holding when the pool changes
    — which a `== 14` assertion would not.
    """
    cfg = _Config( { fsc.PERSONA_POOL_KEY: "alpha, beta, gamma" } )
    assert fsc.resolve_fleet_ceiling( cfg ) == 3

    grown = _Config( { fsc.PERSONA_POOL_KEY: "alpha, beta, gamma, delta" } )
    assert fsc.resolve_fleet_ceiling( grown ) == 4, (
        "the ceiling did not move when the pool grew — it is being read from somewhere "
        "other than the pool, which is the second source of truth the ruling forbids"
    )


def test_an_unreadable_pool_falls_back_rather_than_raising_on_the_spawn_path():
    assert fsc.resolve_fleet_ceiling( None ) == fsc.FALLBACK_FLEET_CEILING
    assert fsc.resolve_fleet_ceiling( _Config( raises=True ) ) == fsc.FALLBACK_FLEET_CEILING
    assert fsc.resolve_fleet_ceiling( _Config( { fsc.PERSONA_POOL_KEY: "  ,  , " } ) ) == fsc.FALLBACK_FLEET_CEILING


# ── THE CAP ──────────────────────────────────────────────────────────────────────

def test_the_cap_is_read_from_the_ini():
    cfg = _Config( { fsc.FLEET_CAP_KEY: 5, fsc.PERSONA_POOL_KEY: "a,b,c,d,e,f,g,h" } )
    assert fsc.resolve_fleet_cap( cfg ) == 5


def test_a_malformed_cap_CLAMPS_and_never_takes_spawning_down():
    """A bad INI value must land somewhere sane. This is read on the spawn path: raising
    here would stop the whole fleet spawning over a typo."""
    pool = { fsc.PERSONA_POOL_KEY: "a,b,c,d,e,f,g,h" }        # ceiling 8
    assert fsc.resolve_fleet_cap( _Config( { **pool, fsc.FLEET_CAP_KEY: 0 } ) ) == 1
    assert fsc.resolve_fleet_cap( _Config( { **pool, fsc.FLEET_CAP_KEY: -3 } ) ) == 1
    assert fsc.resolve_fleet_cap( _Config( { **pool, fsc.FLEET_CAP_KEY: 999 } ) ) == 8, (
        "a cap above the ceiling was not clamped — the slider could promise seats the "
        "persona pool cannot supply"
    )
    assert fsc.resolve_fleet_cap( _Config( raises=True ) ) == min( fsc.DEFAULT_FLEET_CAP,
                                                                   fsc.FALLBACK_FLEET_CEILING )


# ── RULING 3: EVERY SESSION COUNTS, MANAGERS INCLUDED ────────────────────────────

def test_the_census_counts_MANAGERS_TOO_and_the_split_always_reconciles():
    counts = fsc.census( _sessions( 5 ), _managers( "s0", "s1" ) )
    assert counts == { "total": 5, "managers": 2, "workers": 3 }
    assert counts[ "managers" ] + counts[ "workers" ] == counts[ "total" ]


def test_a_session_whose_classification_RAISES_is_still_counted():
    """
    It occupies a seat whatever we can say about it. Dropping it from the total would let
    the fleet exceed its own cap through a classifier bug — the cap would be silently
    wrong in the direction that lets more sessions run.
    """
    def explode( session_id ):
        if session_id == "s2": raise RuntimeError( "bridge unreadable" )
        return session_id == "s0"
    counts = fsc.census( _sessions( 4 ), explode )
    assert counts[ "total" ] == 4, "an unclassifiable session vanished from the count"
    assert counts == { "total": 4, "managers": 1, "workers": 3 }


# ── ENFORCEMENT ──────────────────────────────────────────────────────────────────

def test_a_spawn_that_FITS_is_not_refused():
    """The negative control for the whole file. Without it every assertion below is
    satisfied by a cap that refuses everything."""
    assert fsc.refusal_for_spawn( 2, { "total": 3, "managers": 1, "workers": 2 }, cap=8 ) is None
    assert fsc.refusal_for_spawn( 1, { "total": 7, "managers": 1, "workers": 6 }, cap=8 ) is None


def test_a_spawn_that_would_EXCEED_the_cap_is_refused_and_says_every_number():
    """
    🔴 The refusal is what a manager reads at 2am. Rick: "it would simply fail and tell you
    why, that you are already at limit."
    """
    msg = fsc.refusal_for_spawn( 3, { "total": 6, "managers": 2, "workers": 4 }, cap=8 )
    assert msg is not None, "a spawn of 3 onto a fleet of 6 against a cap of 8 was allowed"
    for needed in ( "8", "6", "2 manager", "4 worker", "3", "2 seat" ):
        assert needed in msg, f"the refusal never names {needed!r}: {msg}"


def test_the_refusal_NAMES_the_case_where_managers_alone_fill_the_cap():
    """
    🔴 THE CONSEQUENCE OF RULING 3, and the reason this arm exists at all. Managers occupy
    the cap, so a cap at or below the live manager count leaves zero room for workers and
    a manager is refused by a cap it is itself consuming. Unlabelled, that is
    indistinguishable from a broken spawner.
    """
    msg = fsc.refusal_for_spawn( 1, { "total": 3, "managers": 3, "workers": 0 }, cap=3 )
    assert msg is not None
    assert "MANAGER(S) ALONE" in msg, (
        f"the refusal does not say that managers alone fill the cap, so a manager hits a "
        f"wall it cannot diagnose: {msg}"
    )
    assert "Raise the cap" in msg, "the refusal names the problem but not a way out"

    # and it must NOT cry manager-starvation on an ordinary over-cap refusal
    ordinary = fsc.refusal_for_spawn( 5, { "total": 6, "managers": 1, "workers": 5 }, cap=8 )
    assert "MANAGER(S) ALONE" not in ordinary, (
        "the zero-headroom warning fires on an ordinary refusal too — a warning that "
        "appears every time carries no information"
    )


def test_lowering_the_cap_below_the_live_count_REFUSES_but_never_reaps():
    """
    RULING 2, pinned. The fleet is over cap; the answer is a refusal and an explicit
    statement that nothing was terminated. There is no reap path in this module to test,
    and that absence is the ruling.
    """
    msg = fsc.refusal_for_spawn( 1, { "total": 9, "managers": 2, "workers": 7 }, cap=4 )
    assert msg is not None
    assert "Nothing was terminated" in msg
    assert not hasattr( fsc, "reap" ) and not hasattr( fsc, "dismiss" ), (
        "this module grew a reap path — a slider that destroys work when dragged is "
        "explicitly not to be built"
    )
