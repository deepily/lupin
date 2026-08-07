"""
Unit tests for the DM-verbosity pilot schedule generator
(`src/scripts/dm-experiment/generate_schedule.py`, plan item 2).

Loads the dashed-directory script straight from its on-disk path via importlib
(the same pattern the migration-script tests use) — the script's schedule logic
imports no cosa, so these run in isolation.

The acceptance bar from the plan's § Verification: 28 slots, 14 per arm, 7 per
arm per day, mirrored at every clock hour, no within-day run > 2, and the same
seed reproduces the file BYTE-IDENTICALLY.

Venue: :7999-eligible (pure unit — no server, no DB, no state mutation).
"""

import os
import json
import random
import datetime
import importlib.util

import pytest


def _load_generator():
    """Load generate_schedule.py as a module from its on-disk path."""
    lupin_root = os.environ[ "LUPIN_ROOT" ]
    path       = os.path.join( lupin_root, "src", "scripts", "dm-experiment", "generate_schedule.py" )
    spec       = importlib.util.spec_from_file_location( "dm_generate_schedule", path )
    module     = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


GEN = _load_generator()


# The Tue/Wed assignment as it stood when the Thu/Fri/Sat extension was authorized
# (Rick, 2026-08-06). Recorded here as a LITERAL, not read back from the generator,
# so this test can catch the generator re-randomizing the original block: the
# 08-04/08-05 corpus rows were written against these arms, and pooling them with a
# different assignment would silently re-label already-collected data.
_ORIGINAL_BLOCK_AT_RULING_TIME = [
    { "slot_id": "2026-08-04T09", "arm": "rejecting" },
    { "slot_id": "2026-08-04T10", "arm": "blind"     },
    { "slot_id": "2026-08-04T11", "arm": "rejecting" },
    { "slot_id": "2026-08-04T12", "arm": "rejecting" },
    { "slot_id": "2026-08-04T13", "arm": "blind"     },
    { "slot_id": "2026-08-04T14", "arm": "rejecting" },
    { "slot_id": "2026-08-04T15", "arm": "blind"     },
    { "slot_id": "2026-08-04T16", "arm": "blind"     },
    { "slot_id": "2026-08-04T17", "arm": "rejecting" },
    { "slot_id": "2026-08-04T18", "arm": "rejecting" },
    { "slot_id": "2026-08-04T19", "arm": "blind"     },
    { "slot_id": "2026-08-04T20", "arm": "blind"     },
    { "slot_id": "2026-08-04T21", "arm": "rejecting" },
    { "slot_id": "2026-08-04T22", "arm": "blind"     },
    { "slot_id": "2026-08-05T09", "arm": "blind"     },
    { "slot_id": "2026-08-05T10", "arm": "rejecting" },
    { "slot_id": "2026-08-05T11", "arm": "blind"     },
    { "slot_id": "2026-08-05T12", "arm": "blind"     },
    { "slot_id": "2026-08-05T13", "arm": "rejecting" },
    { "slot_id": "2026-08-05T14", "arm": "blind"     },
    { "slot_id": "2026-08-05T15", "arm": "rejecting" },
    { "slot_id": "2026-08-05T16", "arm": "rejecting" },
    { "slot_id": "2026-08-05T17", "arm": "blind"     },
    { "slot_id": "2026-08-05T18", "arm": "blind"     },
    { "slot_id": "2026-08-05T19", "arm": "rejecting" },
    { "slot_id": "2026-08-05T20", "arm": "rejecting" },
    { "slot_id": "2026-08-05T21", "arm": "blind"     },
    { "slot_id": "2026-08-05T22", "arm": "rejecting" },
]


# --------------------------------------------------------------------------- #
# _max_run_length                                                             #
# --------------------------------------------------------------------------- #
def test_max_run_length_empty_is_zero():
    assert GEN._max_run_length( [] ) == 0


def test_max_run_length_singletons():
    assert GEN._max_run_length( [ "a", "b", "a", "b" ] ) == 1


def test_max_run_length_counts_longest():
    assert GEN._max_run_length( [ "a", "a", "b", "a", "a", "a" ] ) == 3


# --------------------------------------------------------------------------- #
# mirror_arm                                                                  #
# --------------------------------------------------------------------------- #
def test_mirror_arm_swaps():
    assert GEN.mirror_arm( "blind" )     == "rejecting"
    assert GEN.mirror_arm( "rejecting" ) == "blind"


def test_mirror_arm_rejects_unknown():
    with pytest.raises( ValueError ):
        GEN.mirror_arm( "graded" )


# --------------------------------------------------------------------------- #
# randomize_with_max_run                                                      #
# --------------------------------------------------------------------------- #
def test_randomize_respects_max_run():
    rng    = random.Random( GEN.SEED )
    arms   = [ "blind" ] * 7 + [ "rejecting" ] * 7
    result = GEN.randomize_with_max_run( arms, 2, rng )
    assert sorted( result ) == sorted( arms )       # a permutation
    assert GEN._max_run_length( result ) <= 2


def test_randomize_is_deterministic_for_a_seed():
    a = GEN.randomize_with_max_run( [ "blind" ] * 7 + [ "rejecting" ] * 7, 2, random.Random( GEN.SEED ) )
    b = GEN.randomize_with_max_run( [ "blind" ] * 7 + [ "rejecting" ] * 7, 2, random.Random( GEN.SEED ) )
    assert a == b


def test_randomize_raises_when_impossible():
    # Three identical labels can never satisfy max_run == 1 — exercises the budget-exhausted raise.
    with pytest.raises( ValueError ):
        GEN.randomize_with_max_run( [ "x", "x", "x" ], 1, random.Random( 0 ) )


# --------------------------------------------------------------------------- #
# build_schedule — the design invariants                                      #
# --------------------------------------------------------------------------- #
@pytest.fixture( scope="module" )
def schedule():
    return GEN.build_schedule()


@pytest.fixture( scope="module" )
def original_slots( schedule ):
    """The Tue/Wed block only — the 28 slots these invariants were written for."""
    return [ s for s in schedule[ "slots" ] if s[ "block" ] == GEN.SCHEDULE_ID ]


@pytest.fixture( scope="module" )
def ext_slots( schedule ):
    """The Thu/Fri/Sat extension block (Rick's ruling 2026-08-06)."""
    return [ s for s in schedule[ "slots" ] if s[ "block" ] == GEN.EXT_BLOCK_ID ]


def test_twenty_eight_slots( original_slots ):
    assert len( original_slots ) == 28


def test_fifty_six_slots_total_after_the_extension( schedule ):
    assert len( schedule[ "slots" ] ) == 56


def test_fourteen_per_arm_total( original_slots ):
    arms = [ s[ "arm" ] for s in original_slots ]
    assert arms.count( "blind" )     == 14
    assert arms.count( "rejecting" ) == 14


def test_seven_per_arm_per_day( schedule ):
    for date in ( "2026-08-04", "2026-08-05" ):
        day = [ s[ "arm" ] for s in schedule[ "slots" ] if s[ "date" ] == date ]
        assert day.count( "blind" )     == 7
        assert day.count( "rejecting" ) == 7


def test_mirrored_at_every_clock_hour( schedule ):
    tue = { s[ "local_hour" ]: s[ "arm" ] for s in schedule[ "slots" ] if s[ "date" ] == "2026-08-04" }
    wed = { s[ "local_hour" ]: s[ "arm" ] for s in schedule[ "slots" ] if s[ "date" ] == "2026-08-05" }
    assert set( tue ) == set( wed ) == set( range( 9, 23 ) )
    for hour in tue:
        assert wed[ hour ] == GEN.mirror_arm( tue[ hour ] )


def test_no_within_day_run_longer_than_two( schedule ):
    for date in ( "2026-08-04", "2026-08-05" ):
        ordered = [ s[ "arm" ] for s in sorted(
            ( s for s in schedule[ "slots" ] if s[ "date" ] == date ),
            key=lambda s: s[ "local_hour" ] ) ]
        assert GEN._max_run_length( ordered ) <= 2


# --------------------------------------------------------------------------- #
# The extension block — Thu 19-22 / Fri 09-22 / Sat 09-18 (Rick, 2026-08-06)   #
# --------------------------------------------------------------------------- #
def test_extension_has_twenty_eight_slots( ext_slots ):
    assert len( ext_slots ) == 28


def test_extension_is_balanced_fourteen_per_arm( ext_slots ):
    arms = [ s[ "arm" ] for s in ext_slots ]
    assert arms.count( "blind" )     == 14
    assert arms.count( "rejecting" ) == 14


def test_extension_covers_the_declared_hours_per_day( ext_slots ):
    expected = {
        "2026-08-06" : set( range( 19, 23 ) ),          # ruling landed 18:10 — 19:00 is the first armable slot
        "2026-08-07" : set( range(  9, 23 ) ),
        "2026-08-08" : set( range(  9, 19 ) ),
    }
    for date, hours in expected.items():
        assert { s[ "local_hour" ] for s in ext_slots if s[ "date" ] == date } == hours


def test_extension_gives_every_clock_hour_both_arms( ext_slots ):
    """The property the analyzer's clock-hour pairing needs — a one-armed hour is unusable."""
    by_hour = {}
    for s in ext_slots:
        by_hour.setdefault( s[ "local_hour" ], set() ).add( s[ "arm" ] )
    for hour in range( 9, 23 ):
        assert by_hour[ hour ] == { "blind", "rejecting" }, f"hour {hour} is one-armed"


def test_extension_no_within_day_run_longer_than_two( ext_slots ):
    for date in ( "2026-08-06", "2026-08-07", "2026-08-08" ):
        ordered = [ s[ "arm" ] for s in sorted(
            ( s for s in ext_slots if s[ "date" ] == date ),
            key=lambda s: s[ "local_hour" ] ) ]
        assert GEN._max_run_length( ordered ) <= 2


def test_extension_friday_mirrors_thursday_at_the_late_hours( ext_slots ):
    thu = { s[ "local_hour" ]: s[ "arm" ] for s in ext_slots if s[ "date" ] == "2026-08-06" }
    fri = { s[ "local_hour" ]: s[ "arm" ] for s in ext_slots if s[ "date" ] == "2026-08-07" }
    for hour in range( 19, 23 ):
        assert fri[ hour ] == GEN.mirror_arm( thu[ hour ] )


def test_extension_saturday_mirrors_friday_at_the_early_hours( ext_slots ):
    fri = { s[ "local_hour" ]: s[ "arm" ] for s in ext_slots if s[ "date" ] == "2026-08-07" }
    sat = { s[ "local_hour" ]: s[ "arm" ] for s in ext_slots if s[ "date" ] == "2026-08-08" }
    for hour in range( 9, 19 ):
        assert sat[ hour ] == GEN.mirror_arm( fri[ hour ] )


def test_extension_is_deterministic_for_its_seed():
    assert GEN.build_extension_slots() == GEN.build_extension_slots()


def test_extension_seed_changes_the_arms():
    """A different seed must actually redraw — else the seed is decorative."""
    a = [ s[ "arm" ] for s in GEN.build_extension_slots( GEN.EXT_SEED ) ]
    b = [ s[ "arm" ] for s in GEN.build_extension_slots( GEN.EXT_SEED + 1 ) ]
    assert a != b


def test_extension_starts_after_the_original_block_ends( schedule ):
    """No overlap: the extension's first instant is at or after the original's last end."""
    orig_end = max( s[ "end_utc" ]   for s in schedule[ "slots" ] if s[ "block" ] == GEN.SCHEDULE_ID )
    ext_start = min( s[ "start_utc" ] for s in schedule[ "slots" ] if s[ "block" ] == GEN.EXT_BLOCK_ID )
    assert ext_start >= orig_end


def test_original_block_arms_unchanged_by_the_extension():
    """
    The extension must not perturb the already-collected Tue/Wed assignment — the
    corpus rows from 08-04/08-05 were written against those arms and pooling them
    with a re-randomized schedule would silently re-label collected data.
    """
    slots = sorted( ( s for s in GEN.build_schedule()[ "slots" ] if s[ "block" ] == GEN.SCHEDULE_ID ),
                    key=lambda s: s[ "start_utc" ] )
    assert [ ( s[ "slot_id" ], s[ "arm" ] ) for s in slots ] == [
        ( s[ "slot_id" ], s[ "arm" ] ) for s in _ORIGINAL_BLOCK_AT_RULING_TIME
    ]


def test_assert_extension_invariants_rejects_a_one_armed_hour():
    slots = GEN.build_extension_slots()
    broken = [ dict( s ) for s in slots ]
    for s in broken:
        if s[ "local_hour" ] == 9: s[ "arm" ] = "blind"       # flatten hour 9 to a single arm
    with pytest.raises( AssertionError ):
        GEN._assert_extension_invariants( broken )


def test_assert_extension_invariants_rejects_a_short_block():
    with pytest.raises( AssertionError ):
        GEN._assert_extension_invariants( GEN.build_extension_slots()[ :-1 ] )


def test_extension_day_arms_raises_when_impossible( monkeypatch ):
    monkeypatch.setattr( GEN, "MAX_RUN", 0 )                  # no arrangement can satisfy this
    monkeypatch.setattr( GEN, "MAX_SHUFFLE_ATTEMPTS", 50 )
    with pytest.raises( ValueError ):
        GEN._extension_day_arms( random.Random( 1 ) )


def test_utc_intervals_are_one_hour_edt( schedule ):
    slot = schedule[ "slots" ][ 0 ]                 # Tue 09:00 EDT
    start = datetime.datetime.fromisoformat( slot[ "start_utc" ] )
    end   = datetime.datetime.fromisoformat( slot[ "end_utc" ] )
    assert start == datetime.datetime( 2026, 8, 4, 13, 0, tzinfo=datetime.timezone.utc )   # 09:00 EDT -> 13:00 UTC
    assert ( end - start ) == datetime.timedelta( hours=1 )


def test_slots_carry_the_required_keys( schedule ):
    required = { "slot_id", "date", "local_hour", "local_start", "start_utc", "end_utc", "arm" }
    for slot in schedule[ "slots" ]:
        assert required <= set( slot )


def test_metadata_records_the_seed( schedule ):
    assert schedule[ "seed" ]        == GEN.SEED == 20260804
    assert schedule[ "experiment" ]  == "two-arm-v1"
    assert schedule[ "timezone" ]    == "America/New_York"


# --------------------------------------------------------------------------- #
# serialize — byte-identity                                                   #
# --------------------------------------------------------------------------- #
def test_serialize_is_byte_identical_across_builds():
    assert GEN.serialize( GEN.build_schedule() ) == GEN.serialize( GEN.build_schedule() )


def test_serialize_has_sorted_keys_and_trailing_newline():
    text = GEN.serialize( GEN.build_schedule() )
    assert text.endswith( "\n" )
    parsed = json.loads( text )                     # round-trips
    assert parsed[ "seed" ] == GEN.SEED


def test_committed_file_matches_a_fresh_build():
    """The git-tracked file must equal a fresh build from the recorded seed."""
    lupin_root = os.environ[ "LUPIN_ROOT" ]
    path       = os.path.join( lupin_root, "src", "conf", "dm-experiment-schedule.json" )
    with open( path, "r", encoding="utf-8" ) as fh:
        on_disk = fh.read()
    assert on_disk == GEN.serialize( GEN.build_schedule() )


# --------------------------------------------------------------------------- #
# _assert_invariants — the guard itself rejects a tampered schedule           #
# --------------------------------------------------------------------------- #
def test_assert_invariants_rejects_a_broken_schedule():
    broken = GEN.build_schedule()
    broken[ "slots" ][ 0 ][ "arm" ] = "rejecting" if broken[ "slots" ][ 0 ][ "arm" ] == "blind" else "blind"
    with pytest.raises( AssertionError ):
        GEN._assert_invariants( broken )


# --------------------------------------------------------------------------- #
# write_schedule_file + main --check                                          #
# --------------------------------------------------------------------------- #
def test_write_schedule_file_to_explicit_path( tmp_path ):
    target        = tmp_path / "sched.json"
    path, payload = GEN.write_schedule_file( path=str( target ) )
    assert path == str( target )
    assert target.read_text( encoding="utf-8" ) == payload
    assert payload == GEN.serialize( GEN.build_schedule() )


def test_write_schedule_file_defaults_to_conf_path( tmp_path, monkeypatch ):
    """path=None resolves default_output_path — redirected to tmp so the committed file is untouched."""
    target = tmp_path / "default-sched.json"
    monkeypatch.setattr( GEN, "default_output_path", lambda: str( target ) )
    path, payload = GEN.write_schedule_file( path=None )
    assert path == str( target )
    assert target.read_text( encoding="utf-8" ) == GEN.serialize( GEN.build_schedule() )


# --------------------------------------------------------------------------- #
# default_output_path + main CLI                                              #
# --------------------------------------------------------------------------- #
def test_default_output_path_points_at_conf():
    assert GEN.default_output_path().endswith( "/src/conf/dm-experiment-schedule.json" )


def test_main_check_ok_when_file_matches( capsys ):
    """--check returns 0 when the committed file equals a fresh build."""
    assert GEN.main( [ "--check" ] ) == 0
    assert "OK" in capsys.readouterr().out


def test_main_check_reports_drift( tmp_path, monkeypatch, capsys ):
    """--check returns 1 when the on-disk file differs from a fresh build."""
    stale = tmp_path / "stale.json"
    stale.write_text( "{}\n", encoding="utf-8" )
    monkeypatch.setattr( GEN, "default_output_path", lambda: str( stale ) )
    assert GEN.main( [ "--check" ] ) == 1
    assert "DRIFT" in capsys.readouterr().out


def test_main_write_produces_the_file( tmp_path, monkeypatch, capsys ):
    """Default (no --check) writes the canonical file and returns 0."""
    target = tmp_path / "written.json"
    monkeypatch.setattr( GEN, "default_output_path", lambda: str( target ) )
    assert GEN.main( [] ) == 0
    assert target.read_text( encoding="utf-8" ) == GEN.serialize( GEN.build_schedule() )
    assert "wrote" in capsys.readouterr().out
