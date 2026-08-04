"""
Generate the immutable, git-tracked DM-verbosity two-arm pilot schedule.

Writes `src/conf/dm-experiment-schedule.json` from a RECORDED seed (20260804,
Maria's ruling 2026-08-03) so the file reproduces BYTE-IDENTICALLY on a re-run.

Design: `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md`
(item 2). Two arms — `blind` vs `rejecting` — across 28 hourly slots (14 per
day, Tue 2026-08-04 + Wed 2026-08-05, 09:00-23:00 America/New_York). Seven of
each arm per day; Wednesday mirrors Tuesday at every clock hour; no run of the
same arm longer than two hours. The server's `assignment_at()` consumes the
UTC intervals recorded here.

Bootstrap standalone (runs before cosa is guaranteed importable): sets
`sys.path` from LUPIN_ROOT first; the pure schedule logic below imports no
cosa, so the unit tests can exercise it in isolation.

Run:  python src/scripts/dm-experiment/generate_schedule.py [--check]
"""

import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:                                                     # pragma: no cover
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )                # pragma: no cover

import json
import random
import argparse
import collections
import datetime
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Recorded constants — changing any of these breaks byte-identity by design.
# ---------------------------------------------------------------------------
SEED                 = 20260804                    # Maria's ruling, 2026-08-03
SCHEDULE_ID          = "dm-verbosity-two-arm-v1"
EXPERIMENT           = "two-arm-v1"                 # classifier key (item 4)
TIMEZONE             = "America/New_York"
WINDOW_START_HOUR    = 9                            # first block starts 09:00 local
WINDOW_END_HOUR      = 23                           # exclusive — last block starts 22:00
MAX_RUN              = 2                            # no arm run longer than 2 hours
MAX_SHUFFLE_ATTEMPTS = 100000                       # rejection-sampling budget
TUESDAY_DATE         = datetime.date( 2026, 8, 4 )
WEDNESDAY_DATE       = datetime.date( 2026, 8, 5 )
BLIND                = "blind"
REJECTING            = "rejecting"
SLOTS_PER_ARM_PER_DAY = 7


def _max_run_length( seq ):
    """
    Longest run of consecutive identical elements.

    Requires:
        - seq is a list

    Ensures:
        - returns 0 for an empty seq
        - returns the length of the longest run of equal adjacent elements
    """
    if not seq: return 0
    longest = 1
    current = 1
    for i in range( 1, len( seq ) ):
        if seq[ i ] == seq[ i - 1 ]:
            current += 1
            if current > longest: longest = current
        else:
            current = 1
    return longest


def randomize_with_max_run( arms, max_run, rng ):
    """
    Permute `arms` so no run of identical labels exceeds `max_run`.

    Requires:
        - arms is a non-empty list of labels
        - max_run is a positive integer
        - rng is a seeded random.Random instance

    Ensures:
        - returns a permutation of arms whose longest run is <= max_run
        - deterministic for a given rng seed and call sequence

    Raises:
        - ValueError if no valid arrangement is found within the attempt budget
    """
    candidate = list( arms )
    for _ in range( MAX_SHUFFLE_ATTEMPTS ):
        rng.shuffle( candidate )
        if _max_run_length( candidate ) <= max_run:
            return list( candidate )
    raise ValueError( f"no arrangement with max_run<={max_run} found in {MAX_SHUFFLE_ATTEMPTS} attempts" )


def mirror_arm( arm ):
    """
    Return the opposite arm — Wednesday mirrors Tuesday.

    Requires:
        - arm is one of "blind" or "rejecting"

    Ensures:
        - "blind" -> "rejecting" and "rejecting" -> "blind"

    Raises:
        - ValueError for any other value
    """
    if arm == BLIND:     return REJECTING
    if arm == REJECTING: return BLIND
    raise ValueError( f"unknown arm: {arm!r}" )


def _build_day_slots( date, arms, tz ):
    """
    Build the per-hour slot dicts for one day.

    Requires:
        - date is a datetime.date
        - arms is a list of arm labels, one per hour in the window
        - tz is a zoneinfo.ZoneInfo for America/New_York

    Ensures:
        - returns one slot dict per window hour, each carrying slot_id, date,
          local_hour, local_start, start_utc, end_utc, arm
        - UTC instants are derived from the local wall time via zoneinfo (DST-safe)
    """
    slots = []
    hours = list( range( WINDOW_START_HOUR, WINDOW_END_HOUR ) )
    for hour, arm in zip( hours, arms ):
        local_start = datetime.datetime( date.year, date.month, date.day, hour, 0, 0, tzinfo=tz )
        start_utc   = local_start.astimezone( datetime.timezone.utc )
        end_utc     = start_utc + datetime.timedelta( hours=1 )
        slots.append( {
            "slot_id"     : f"{date.isoformat()}T{hour:02d}",
            "date"        : date.isoformat(),
            "local_hour"  : hour,
            "local_start" : local_start.isoformat(),
            "start_utc"   : start_utc.isoformat(),
            "end_utc"     : end_utc.isoformat(),
            "arm"         : arm,
        } )
    return slots


def _assert_invariants( schedule ):
    """
    Fail loudly unless the schedule honours every design constraint.

    Requires:
        - schedule is a dict with a "slots" list

    Ensures:
        - returns None when 28 slots, 14 per arm, 7 per arm per day, mirrored at
          every clock hour, and no within-day run > MAX_RUN all hold

    Raises:
        - AssertionError naming the first violated constraint
    """
    slots = schedule[ "slots" ]
    assert len( slots ) == 28, f"expected 28 slots, got {len( slots )}"

    tuesday   = [ s for s in slots if s[ "date" ] == TUESDAY_DATE.isoformat() ]
    wednesday = [ s for s in slots if s[ "date" ] == WEDNESDAY_DATE.isoformat() ]
    assert len( tuesday )   == 14, f"expected 14 Tuesday slots, got {len( tuesday )}"
    assert len( wednesday ) == 14, f"expected 14 Wednesday slots, got {len( wednesday )}"

    # 7 per arm per day
    for label, day in ( ( "Tuesday", tuesday ), ( "Wednesday", wednesday ) ):
        counts = collections.Counter( s[ "arm" ] for s in day )
        assert counts[ BLIND ]     == SLOTS_PER_ARM_PER_DAY, f"{label}: {counts[ BLIND ]} blind, expected {SLOTS_PER_ARM_PER_DAY}"
        assert counts[ REJECTING ] == SLOTS_PER_ARM_PER_DAY, f"{label}: {counts[ REJECTING ]} rejecting, expected {SLOTS_PER_ARM_PER_DAY}"

    # 14 per arm total
    total = collections.Counter( s[ "arm" ] for s in slots )
    assert total[ BLIND ]     == 14, f"total blind {total[ BLIND ]}, expected 14"
    assert total[ REJECTING ] == 14, f"total rejecting {total[ REJECTING ]}, expected 14"

    # Mirrored at every clock hour
    tue_by_hour = { s[ "local_hour" ]: s[ "arm" ] for s in tuesday }
    wed_by_hour = { s[ "local_hour" ]: s[ "arm" ] for s in wednesday }
    assert set( tue_by_hour ) == set( wed_by_hour ), "Tuesday and Wednesday cover different hours"
    for hour, arm in tue_by_hour.items():
        assert wed_by_hour[ hour ] == mirror_arm( arm ), f"hour {hour} not mirrored"

    # No within-day run longer than MAX_RUN (ordered by clock hour)
    for label, day in ( ( "Tuesday", tuesday ), ( "Wednesday", wednesday ) ):
        ordered = [ s[ "arm" ] for s in sorted( day, key=lambda s: s[ "local_hour" ] ) ]
        assert _max_run_length( ordered ) <= MAX_RUN, f"{label}: run longer than {MAX_RUN}"


def build_schedule( seed=SEED ):
    """
    Build the full schedule dict from a recorded seed.

    Requires:
        - seed is an integer

    Ensures:
        - returns a dict with metadata plus 28 slots that pass _assert_invariants
        - the same seed yields the same slot arms (deterministic)

    Raises:
        - AssertionError if any design constraint is violated
    """
    rng            = random.Random( seed )
    tuesday_arms   = randomize_with_max_run( [ BLIND ] * SLOTS_PER_ARM_PER_DAY + [ REJECTING ] * SLOTS_PER_ARM_PER_DAY, MAX_RUN, rng )
    wednesday_arms = [ mirror_arm( arm ) for arm in tuesday_arms ]

    tz    = ZoneInfo( TIMEZONE )
    slots = _build_day_slots( TUESDAY_DATE, tuesday_arms, tz ) + _build_day_slots( WEDNESDAY_DATE, wednesday_arms, tz )

    schedule = {
        "schedule_id" : SCHEDULE_ID,
        "experiment"  : EXPERIMENT,
        "seed"        : seed,
        "timezone"    : TIMEZONE,
        "window"      : { "start_hour": WINDOW_START_HOUR, "end_hour": WINDOW_END_HOUR },
        "max_run"     : MAX_RUN,
        "slots"       : slots,
    }
    _assert_invariants( schedule )
    return schedule


def serialize( schedule ):
    """
    Canonical JSON text for byte-identical re-runs.

    Requires:
        - schedule is a JSON-serializable dict

    Ensures:
        - returns deterministic text (sorted keys, 2-space indent, trailing newline)
    """
    return json.dumps( schedule, indent=2, sort_keys=True ) + "\n"


def default_output_path():
    """
    Path to the git-tracked schedule file under src/conf.

    Ensures:
        - returns <project_root>/src/conf/dm-experiment-schedule.json
    """
    import cosa.utils.util as cu
    return cu.get_project_root() + "/src/conf/dm-experiment-schedule.json"


def write_schedule_file( path=None, seed=SEED ):
    """
    Build, verify, and write the schedule file.

    Requires:
        - path is a writable path or None (defaults to src/conf location)
        - seed is an integer

    Ensures:
        - writes the canonical JSON to `path` and returns (path, payload)
    """
    schedule = build_schedule( seed )
    payload  = serialize( schedule )
    if path is None:
        path = default_output_path()
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( payload )
    return path, payload


def main( argv=None ):
    """
    CLI entry: write the schedule, or --check that HEAD matches a fresh build.

    Ensures:
        - default: writes the file and prints its path
        - --check: exits 1 if the on-disk file differs from a fresh build
    """
    parser = argparse.ArgumentParser( description="Generate the DM-verbosity pilot schedule." )
    parser.add_argument( "--check", action="store_true", help="verify the on-disk file matches a fresh build, do not write" )
    args = parser.parse_args( argv )

    path    = default_output_path()
    payload = serialize( build_schedule() )

    if args.check:
        with open( path, "r", encoding="utf-8" ) as fh:
            on_disk = fh.read()
        if on_disk == payload:
            print( f"OK — {path} matches a fresh build from seed {SEED}" )
            return 0
        print( f"DRIFT — {path} differs from a fresh build from seed {SEED}" )
        return 1

    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( payload )
    print( f"wrote {path} ({len( payload )} bytes, {len( build_schedule()[ 'slots' ] )} slots, seed {SEED})" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
