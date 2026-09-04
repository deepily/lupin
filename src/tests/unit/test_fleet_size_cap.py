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


# ── THE CEILING IS CONFIGURED, NOT DERIVED (superseded 2026-09-03) ──────────────
#
# 🔨 THESE TESTS WERE REWRITTEN, NOT DELETED. They used to assert the ceiling was
# COUNTED from the persona pool, with a message calling any other source "the second
# source of truth the ruling forbids". That was a correct reading of Rick's earlier
# ruling. He ruled again the same day, by voice: the maximum must be CONFIGURABLE in
# the configuration manager so he can tweak it over time.
#
# ⚠️ THE OLD TESTS' CONCERN SURVIVES AS `pool_shortfall`, and is asserted below. The
# pool is still what decides how many seats can be FILLED; the key is only how wide the
# dial goes. Nothing here clamps one to the other, deliberately.

def test_the_ceiling_is_READ_FROM_CONFIG_not_counted_from_the_pool():
    """
    The dial's width comes from the key, and a pool of a different size does not move
    it. Both halves matter: reading the key, and NOT being dragged by the pool.
    """
    cfg = _Config( { fsc.FLEET_CEILING_KEY: 18, fsc.PERSONA_POOL_KEY: "alpha, beta, gamma" } )
    assert fsc.resolve_fleet_ceiling( cfg ) == 18, (
        "the ceiling was not read from the key — a pool of 3 dragged it down, which is "
        "the silent clamp Rick's ruling forbids"
    )

    wider_pool = _Config( { fsc.FLEET_CEILING_KEY: 18,
                            fsc.PERSONA_POOL_KEY: ",".join( f"p{i}" for i in range( 40 ) ) } )
    assert fsc.resolve_fleet_ceiling( wider_pool ) == 18, (
        "a pool larger than the key moved the ceiling — the key is the authority"
    )


def test_an_unreadable_ceiling_falls_back_rather_than_raising_on_the_spawn_path():
    assert fsc.resolve_fleet_ceiling( None ) == fsc.DEFAULT_FLEET_CEILING
    assert fsc.resolve_fleet_ceiling( _Config( raises=True ) ) == fsc.DEFAULT_FLEET_CEILING
    assert fsc.resolve_fleet_ceiling( _Config( {} ) ) == fsc.DEFAULT_FLEET_CEILING
    # Below 1 clamps to 1 — a zero-width dial would refuse every spawn on a typo.
    assert fsc.resolve_fleet_ceiling( _Config( { fsc.FLEET_CEILING_KEY: 0 } ) ) == 1
    assert fsc.resolve_fleet_ceiling( _Config( { fsc.FLEET_CEILING_KEY: -5 } ) ) == 1


# ── A NAME IS NOT A SEAT ─────────────────────────────────────────────────────────

def test_pool_size_counts_VOICE_IDS_not_names():
    """
    🔴 THE TRAP THIS EXISTS FOR. `load_persona_pool_from_config` silently skips a pool
    entry whose `voice id` is missing or empty — correct for allocation, and a trap for
    counting. So a pool grown by NAME alone advertises seats that cannot be filled.

    Found 2026-09-03 BEFORE any persona was added, which is the only reason it is a
    guard rather than an incident.
    """
    voiced = { fsc.PERSONA_POOL_KEY: "a,b,c",
               "cc session voice persona a voice id": "v1",
               "cc session voice persona b voice id": "v2",
               "cc session voice persona c voice id": "v3" }
    assert fsc.pool_size( _Config( voiced ) ) == 3

    # One name added with no voice id: the NAME count is 4, the SEAT count is still 3.
    plus_a_nameless = dict( voiced ); plus_a_nameless[ fsc.PERSONA_POOL_KEY ] = "a,b,c,d"
    assert fsc.pool_size( _Config( plus_a_nameless ) ) == 3, (
        "a name with no voice id was counted as a seat — the loader skips it, so this "
        "would advertise a seat nobody can occupy"
    )

    # An empty/whitespace voice id is the same case as a missing one.
    blank = dict( plus_a_nameless ); blank[ "cc session voice persona d voice id" ] = "   "
    assert fsc.pool_size( _Config( blank ) ) == 3

    assert fsc.pool_size( None ) == 0
    assert fsc.pool_size( _Config( raises=True ) ) == 0


def test_the_pool_is_NOT_a_ceiling_because_Extra_N_carries_past_it():
    """
    🔴 THIS TEST REPLACES ONE THAT GUARDED A GAP THAT CANNOT EXIST.

    The first cut asserted a `pool_shortfall()` warning fired when the dial was wider
    than the persona pool. Measured on the live config, that gap is imaginary:
    allocation falls through the named pool to the overflow persona and then to
    UNBOUNDED `Extra-N` identities. 18 requested filled 18 distinct seats — 14 named,
    `arnold`, then `extra 1/2/3` — and 200 requested filled 200.

    ⚠️ SO THE REPLACEMENT PINS THE THING THAT MAKES A CEILING OF 18 SAFE, which nothing
    asserted before: that the ceiling may exceed the named pool without stranding a
    seat. If the fall-through is ever removed, a cap above `pool_size()` starts
    stranding sessions and this test is what says so.

    ⚠️ AND IT IS DELIBERATELY NOT A MOCK OF THE ALLOCATOR — it drives the real
    `pick_unallocated_persona` with a real pool, which is the only way to observe a
    fall-through that lives inside it.
    """
    from cosa.rest import voice_persona_helpers as vph

    pool     = [ { "name": f"p{i}", "voice_id": f"v{i}", "icon": "x",
                   "color": "#000", "profile": "" } for i in range( 3 ) ]
    overflow = { "name": "arnold", "voice_id": "vA", "icon": "x", "color": "#000", "profile": "" }

    occupied, filled = set(), [ ]
    for i in range( 12 ):
        p = vph.pick_unallocated_persona( pool, occupied, f"s{i:04d}",
                                          overflow_persona=overflow, extra_colors=[ "#111", "#222" ] )
        assert p is not None, f"allocation returned None at seat {i+1} — the pool became a ceiling"
        occupied.add( p[ "name" ] )
        filled.append( p[ "name" ] )

    assert len( occupied ) == 12, f"12 requested, {len(occupied)} distinct seats: {filled}"
    assert any( "extra" in n.lower() for n in filled ), (
        f"nothing fell through to Extra-N — a 3-name pool filled 12 seats some other way: {filled}" )


# ── THE CAP ──────────────────────────────────────────────────────────────────────

def test_the_cap_is_read_from_the_ini():
    cfg = _Config( { fsc.FLEET_CAP_KEY: 5, fsc.PERSONA_POOL_KEY: "a,b,c,d,e,f,g,h" } )
    assert fsc.resolve_fleet_cap( cfg ) == 5


def test_a_malformed_cap_CLAMPS_and_never_takes_spawning_down():
    """A bad INI value must land somewhere sane. This is read on the spawn path: raising
    here would stop the whole fleet spawning over a typo."""
    # ⚠️ THE CEILING IS NAMED HERE RATHER THAN INFERRED FROM THE POOL. This test's
    # subject is the CLAMP, not where the ceiling comes from; it used to derive 8 from
    # an eight-name pool and broke the moment the ceiling moved to config, which is the
    # test telling you it was asserting two things at once.
    pool = { fsc.FLEET_CEILING_KEY: 8, fsc.PERSONA_POOL_KEY: "a,b,c,d,e,f,g,h" }
    assert fsc.resolve_fleet_cap( _Config( { **pool, fsc.FLEET_CAP_KEY: 0 } ) ) == 1
    assert fsc.resolve_fleet_cap( _Config( { **pool, fsc.FLEET_CAP_KEY: -3 } ) ) == 1
    assert fsc.resolve_fleet_cap( _Config( { **pool, fsc.FLEET_CAP_KEY: 999 } ) ) == 8, (
        "a cap above the ceiling was not clamped — the dial could promise more seats "
        "than the configured maximum allows"
    )
    assert fsc.resolve_fleet_cap( _Config( raises=True ) ) == min( fsc.DEFAULT_FLEET_CAP,
                                                                   fsc.DEFAULT_FLEET_CEILING )


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
