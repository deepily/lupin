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

# ---------------------------------------------------------------------------
# Extension block (Rick's ruling 2026-08-06, ~18:10 EDT).
#
# The original 28 slots ran out at Wed 22:00 EDT and every DM since has been
# written untagged — the fail-safe behaving as specified, not a defect. This
# block adds 28 MORE slots so the pilot keeps accruing.
#
# ⚠️ The extension is declared with a FIXED end time BEFORE it runs. It is not
# "run until it turns significant" — the pre-declared co-primaries and the
# +/-46-word null band are unchanged. It carries its own block id so Tue/Wed can
# still be reported standalone as well as pooled; the interim result was already
# seen when this was authorized, and that is recorded in the R&D doc.
#
# Shape — every clock hour gets BOTH arms inside the extension:
#   Thu 19-22 (4)  mirrored by  Fri 19-22 (4)
#   Fri 09-18 (10) mirrored by  Sat 09-18 (10)
# 28 slots, 14 per arm. Thursday starts at 19:00 because the ruling landed at
# 18:10 and an already-elapsed slot cannot be armed.
# ---------------------------------------------------------------------------
EXT_SEED             = 20260806                    # Rick's ruling date, recorded
EXT_BLOCK_ID         = "dm-verbosity-two-arm-v1-ext"
THURSDAY_DATE        = datetime.date( 2026, 8, 6 )
FRIDAY_DATE          = datetime.date( 2026, 8, 7 )
SATURDAY_DATE        = datetime.date( 2026, 8, 8 )
EXT_LATE_HOURS       = list( range( 19, 23 ) )     # 19,20,21,22 — Thu, mirrored Fri
EXT_EARLY_HOURS      = list( range(  9, 19 ) )     # 09..18      — Fri, mirrored Sat

# ---------------------------------------------------------------------------
# Week-2 block (Rick's instruction 2026-08-11, ~14:36 EDT): "start running it now
# and across the rest of this week while we make a decision on what the third arm
# is supposed to look like."
#
# The Sat 2026-08-08 18:00 slot was the last declared one, so every DM since has
# been written with `arm: null` — the fail-safe behaving as specified, the same
# shape as the 08-06 gap. This block resumes collection today and declares its
# own end.
#
# ⚠️ THIS IS THE SECOND EXTENSION AUTHORIZED AFTER RESULTS WERE SEEN, and the
# cost compounds rather than repeating. The pilot plan's protection is that the
# end is fixed BEFORE the window runs; that still holds here (Sat 2026-08-15
# 14:00 EDT, written down before the first slot opens). What does NOT hold is
# the stronger claim that the stopping rule was never data-dependent — it was
# extended twice, both times by someone who had seen the interim numbers. Report
# the blocks separately as well as pooled, and say so wherever a p-value appears.
#
# ⚠️ STILL TWO ARMS. The third arm is undecided by design — this block does not
# reserve slots for it. Adding it later means a NEW block with its own id, not a
# re-labelling of these slots, because a slot's arm is what its rows were
# collected under.
#
# Shape — every clock hour carries BOTH arms inside the block:
#   Tue 15-22 (8)  mirrored by  Wed 15-22 (8)
#   Wed 09-14 (6)  mirrored by  Thu 09-14 (6)
#   Thu 15-22 (8)  mirrored by  Fri 15-22 (8)
#   Fri 09-14 (6)  mirrored by  Sat 09-14 (6)
# 56 slots, 28 per arm. Tuesday starts at 15:00 because the instruction landed at
# 14:36 and an already-elapsed slot cannot be armed. Saturday ends at 14:00 so
# every sequence has a mirror — a tail with no partner would break the pairing
# the analyzer needs, which is a worse trade than four fewer hours.
# ---------------------------------------------------------------------------
WK2_SEED             = 20260811                    # the instruction's date, recorded
WK2_BLOCK_ID         = "dm-verbosity-two-arm-v1-week2"
WK2_TUESDAY_DATE     = datetime.date( 2026, 8, 11 )
WK2_WEDNESDAY_DATE   = datetime.date( 2026, 8, 12 )
WK2_THURSDAY_DATE    = datetime.date( 2026, 8, 13 )
WK2_FRIDAY_DATE      = datetime.date( 2026, 8, 14 )
WK2_SATURDAY_DATE    = datetime.date( 2026, 8, 15 )
WK2_LATE_HOURS       = list( range( 15, 23 ) )     # 15..22 — 8 hours
WK2_EARLY_HOURS      = list( range(  9, 15 ) )     # 09..14 — 6 hours


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


def _build_day_slots( date, arms, tz, hours=None ):
    """
    Build the per-hour slot dicts for one day.

    Requires:
        - date is a datetime.date
        - arms is a list of arm labels, one per hour covered
        - tz is a zoneinfo.ZoneInfo for America/New_York
        - hours is a list of local hours, or None for the full 09-22 window

    Ensures:
        - returns one slot dict per covered hour, each carrying slot_id, date,
          local_hour, local_start, start_utc, end_utc, arm
        - UTC instants are derived from the local wall time via zoneinfo (DST-safe)
        - a partial `hours` list (the extension's Thu 19-22) is honoured verbatim,
          so a block that cannot start at 09:00 is not silently back-filled
    """
    slots = []
    if hours is None: hours = list( range( WINDOW_START_HOUR, WINDOW_END_HOUR ) )
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


def _extension_day_arms( rng ):
    """
    Draw the two randomized arm sequences the extension block is built from.

    The late sequence covers EXT_LATE_HOURS on Thursday; the early sequence covers
    EXT_EARLY_HOURS on Friday. Their mirrors supply Friday-late and Saturday-early,
    so every clock hour in 09-22 carries both arms inside the extension.

    Rejection-samples the pair together, because Friday is assembled from the EARLY
    sequence plus the MIRROR of the late one — its run length spans the join and
    cannot be checked from either sequence alone.

    Requires:
        - rng is a seeded random.Random instance

    Ensures:
        - returns ( late_arms, early_arms ), balanced 2/2 and 5/5 respectively
        - every assembled day (Thu, Fri, Sat) has max run <= MAX_RUN

    Raises:
        - ValueError if no arrangement is found within the attempt budget
    """
    late_pool  = [ BLIND ] * 2 + [ REJECTING ] * 2
    early_pool = [ BLIND ] * 5 + [ REJECTING ] * 5
    for _ in range( MAX_SHUFFLE_ATTEMPTS ):
        late  = list( late_pool  ); rng.shuffle( late )
        early = list( early_pool ); rng.shuffle( early )
        thursday = late
        friday   = early + [ mirror_arm( a ) for a in late ]          # 09..18 then 19..22
        saturday = [ mirror_arm( a ) for a in early ]
        if max( _max_run_length( thursday ), _max_run_length( friday ),
                _max_run_length( saturday ) ) <= MAX_RUN:
            return late, early
    raise ValueError( f"no extension arrangement with max_run<={MAX_RUN} found in {MAX_SHUFFLE_ATTEMPTS} attempts" )


def build_extension_slots( seed=EXT_SEED ):
    """
    Build the 28 extension slots (Thu 19-22, Fri 09-22, Sat 09-18).

    Requires:
        - seed is an integer

    Ensures:
        - returns 28 slot dicts, 14 per arm, in chronological day order
        - each carries block == EXT_BLOCK_ID so the extension can be reported
          standalone as well as pooled with the original Tue/Wed block
        - the same seed yields the same arms (deterministic)
    """
    rng          = random.Random( seed )
    late, early  = _extension_day_arms( rng )
    tz           = ZoneInfo( TIMEZONE )

    slots  = _build_day_slots( THURSDAY_DATE, late, tz, hours=EXT_LATE_HOURS )
    slots += _build_day_slots( FRIDAY_DATE,   early + [ mirror_arm( a ) for a in late ], tz,
                               hours=EXT_EARLY_HOURS + EXT_LATE_HOURS )
    slots += _build_day_slots( SATURDAY_DATE, [ mirror_arm( a ) for a in early ], tz,
                               hours=EXT_EARLY_HOURS )
    for slot in slots:
        slot[ "block" ] = EXT_BLOCK_ID
    return slots


def _assert_extension_invariants( slots ):
    """
    Fail loudly unless the extension block honours its design constraints.

    Requires:
        - slots is the extension slot list from build_extension_slots

    Ensures:
        - returns None when 28 slots, 14 per arm, the declared per-day hour
          coverage, both arms present at every clock hour 09-22, and no
          within-day run > MAX_RUN all hold

    Raises:
        - AssertionError naming the first violated constraint
    """
    assert len( slots ) == 28, f"expected 28 extension slots, got {len( slots )}"

    total = collections.Counter( s[ "arm" ] for s in slots )
    assert total[ BLIND ]     == 14, f"extension blind {total[ BLIND ]}, expected 14"
    assert total[ REJECTING ] == 14, f"extension rejecting {total[ REJECTING ]}, expected 14"

    expected_hours = {
        THURSDAY_DATE.isoformat() : set( EXT_LATE_HOURS ),
        FRIDAY_DATE.isoformat()   : set( EXT_EARLY_HOURS + EXT_LATE_HOURS ),
        SATURDAY_DATE.isoformat() : set( EXT_EARLY_HOURS ),
    }
    for date_str, hours in expected_hours.items():
        day = [ s for s in slots if s[ "date" ] == date_str ]
        assert { s[ "local_hour" ] for s in day } == hours, f"{date_str}: unexpected hour coverage"
        ordered = [ s[ "arm" ] for s in sorted( day, key=lambda s: s[ "local_hour" ] ) ]
        assert _max_run_length( ordered ) <= MAX_RUN, f"{date_str}: run longer than {MAX_RUN}"

    # Both arms at every clock hour — the property the analyzer's pairing needs.
    by_hour = collections.defaultdict( set )
    for s in slots:
        by_hour[ s[ "local_hour" ] ].add( s[ "arm" ] )
    for hour in range( WINDOW_START_HOUR, WINDOW_END_HOUR ):
        assert by_hour[ hour ] == { BLIND, REJECTING }, f"hour {hour} lacks both arms in the extension"


def _week2_day_arms( rng ):
    """
    Draw the four randomized arm sequences the week-2 block is built from.

    Each sequence supplies one half-day and its MIRROR supplies the matching clock
    hours on the following day, so every hour in 09-22 carries both arms:

        late_a  -> Tue 15-22, mirrored onto Wed 15-22
        early_b -> Wed 09-14, mirrored onto Thu 09-14
        late_c  -> Thu 15-22, mirrored onto Fri 15-22
        early_d -> Fri 09-14, mirrored onto Sat 09-14

    All four are rejection-sampled TOGETHER because three of the five days are
    assembled from two different sequences (an early half plus the mirror of a
    late one). A run can straddle that join, and no single sequence can see it.

    Requires:
        - rng is a seeded random.Random instance

    Ensures:
        - returns ( late_a, early_b, late_c, early_d ), balanced 4/4 and 3/3
        - every assembled day has max run <= MAX_RUN

    Raises:
        - ValueError if no arrangement is found within the attempt budget
    """
    late_pool  = [ BLIND ] * 4 + [ REJECTING ] * 4
    early_pool = [ BLIND ] * 3 + [ REJECTING ] * 3

    for _ in range( MAX_SHUFFLE_ATTEMPTS ):
        late_a  = list( late_pool  ); rng.shuffle( late_a  )
        early_b = list( early_pool ); rng.shuffle( early_b )
        late_c  = list( late_pool  ); rng.shuffle( late_c  )
        early_d = list( early_pool ); rng.shuffle( early_d )

        tuesday   = late_a
        wednesday = early_b + [ mirror_arm( a ) for a in late_a ]          # 09..14 then 15..22
        thursday  = [ mirror_arm( a ) for a in early_b ] + late_c
        friday    = early_d + [ mirror_arm( a ) for a in late_c ]
        saturday  = [ mirror_arm( a ) for a in early_d ]

        if max( _max_run_length( tuesday  ), _max_run_length( wednesday ),
                _max_run_length( thursday ), _max_run_length( friday    ),
                _max_run_length( saturday ) ) <= MAX_RUN:
            return late_a, early_b, late_c, early_d

    raise ValueError( f"no week-2 arrangement with max_run<={MAX_RUN} found in {MAX_SHUFFLE_ATTEMPTS} attempts" )


def build_week2_slots( seed=WK2_SEED ):
    """
    Build the 56 week-2 slots (Tue 15-22, Wed/Thu/Fri 09-22, Sat 09-14).

    Requires:
        - seed is an integer

    Ensures:
        - returns 56 slot dicts, 28 per arm, in chronological day order
        - each carries block == WK2_BLOCK_ID so this window can be reported
          standalone as well as pooled with the two earlier blocks
        - the same seed yields the same arms (deterministic)
    """
    rng = random.Random( seed )
    late_a, early_b, late_c, early_d = _week2_day_arms( rng )
    tz  = ZoneInfo( TIMEZONE )

    slots  = _build_day_slots( WK2_TUESDAY_DATE, late_a, tz, hours=WK2_LATE_HOURS )
    slots += _build_day_slots( WK2_WEDNESDAY_DATE,
                               early_b + [ mirror_arm( a ) for a in late_a ], tz,
                               hours=WK2_EARLY_HOURS + WK2_LATE_HOURS )
    slots += _build_day_slots( WK2_THURSDAY_DATE,
                               [ mirror_arm( a ) for a in early_b ] + late_c, tz,
                               hours=WK2_EARLY_HOURS + WK2_LATE_HOURS )
    slots += _build_day_slots( WK2_FRIDAY_DATE,
                               early_d + [ mirror_arm( a ) for a in late_c ], tz,
                               hours=WK2_EARLY_HOURS + WK2_LATE_HOURS )
    slots += _build_day_slots( WK2_SATURDAY_DATE,
                               [ mirror_arm( a ) for a in early_d ], tz,
                               hours=WK2_EARLY_HOURS )
    for slot in slots:
        slot[ "block" ] = WK2_BLOCK_ID
    return slots


def _assert_week2_invariants( slots ):
    """
    Fail loudly unless the week-2 block honours its design constraints.

    Requires:
        - slots is the slot list from build_week2_slots

    Ensures:
        - returns None when 56 slots, 28 per arm, the declared per-day hour
          coverage, both arms present at every clock hour 09-22, and no
          within-day run > MAX_RUN all hold

    Raises:
        - AssertionError naming the first violated constraint
    """
    assert len( slots ) == 56, f"expected 56 week-2 slots, got {len( slots )}"

    total = collections.Counter( s[ "arm" ] for s in slots )
    assert total[ BLIND ]     == 28, f"week-2 blind {total[ BLIND ]}, expected 28"
    assert total[ REJECTING ] == 28, f"week-2 rejecting {total[ REJECTING ]}, expected 28"

    full_day       = set( WK2_EARLY_HOURS + WK2_LATE_HOURS )
    expected_hours = {
        WK2_TUESDAY_DATE.isoformat()   : set( WK2_LATE_HOURS ),
        WK2_WEDNESDAY_DATE.isoformat() : full_day,
        WK2_THURSDAY_DATE.isoformat()  : full_day,
        WK2_FRIDAY_DATE.isoformat()    : full_day,
        WK2_SATURDAY_DATE.isoformat()  : set( WK2_EARLY_HOURS ),
    }
    for date_str, hours in expected_hours.items():
        day = [ s for s in slots if s[ "date" ] == date_str ]
        assert { s[ "local_hour" ] for s in day } == hours, f"{date_str}: unexpected hour coverage"
        ordered = [ s[ "arm" ] for s in sorted( day, key=lambda s: s[ "local_hour" ] ) ]
        assert _max_run_length( ordered ) <= MAX_RUN, f"{date_str}: run longer than {MAX_RUN}"

    # Both arms at every clock hour — the property the analyzer's pairing needs.
    by_hour = collections.defaultdict( set )
    for s in slots:
        by_hour[ s[ "local_hour" ] ].add( s[ "arm" ] )
    for hour in range( WINDOW_START_HOUR, WINDOW_END_HOUR ):
        assert by_hour[ hour ] == { BLIND, REJECTING }, f"hour {hour} lacks both arms in week 2"

    # No slot may open in the past relative to the declared start. This is the
    # check that would have caught an already-elapsed Tuesday hour being armed.
    earliest = min( s[ "start_utc" ] for s in slots )
    assert earliest.startswith( "2026-08-11T19:00" ), f"week 2 opens at {earliest}, expected Tue 15:00 EDT"


def _assert_blocks_are_disjoint( slots ):
    """
    Fail loudly unless every block occupies its own stretch of wall clock.

    Corpus rows record the arm they were collected under but NOT the block id, so
    a row is attributed to a block by its timestamp. That attribution is sound
    only while the blocks do not overlap — the moment two blocks cover the same
    instant, every pooled figure silently mixes windows and no reader can
    separate them after the fact.

    Written while the windows ARE disjoint, on purpose: this assert cannot be
    added later without first deciding what the already-collected ambiguous rows
    belong to. (Mr Radio raised it, 2026-08-11; the analyzer needs the same
    guarantee and gets it from here.)

    Requires:
        - slots is the full slot list, each carrying start_utc, end_utc, block

    Ensures:
        - returns None when no two slots from DIFFERENT blocks overlap and no
          slot_id is reused

    Raises:
        - AssertionError naming the first overlapping pair or duplicated id
    """
    ids = [ s[ "slot_id" ] for s in slots ]
    assert len( ids ) == len( set( ids ) ), "duplicate slot_id — a row would match two slots"

    ordered = sorted( slots, key=lambda s: s[ "start_utc" ] )
    for earlier, later in zip( ordered, ordered[ 1: ] ):
        if earlier[ "block" ] == later[ "block" ]: continue
        assert earlier[ "end_utc" ] <= later[ "start_utc" ], (
            f"blocks overlap: {earlier['block']} {earlier['slot_id']} ends {earlier['end_utc']} "
            f"after {later['block']} {later['slot_id']} starts {later['start_utc']} — "
            f"rows in that stretch cannot be attributed to a block by timestamp" )


def build_schedule( seed=SEED, ext_seed=EXT_SEED, wk2_seed=WK2_SEED ):
    """
    Build the full schedule dict from a recorded seed.

    Requires:
        - seed and ext_seed are integers

    Ensures:
        - returns a dict with metadata plus 56 slots: the original 28 (Tue/Wed,
          unchanged and byte-identical for a given seed) followed by the 28
          extension slots (Thu/Fri/Sat)
        - the original block still passes _assert_invariants and the extension
          block passes _assert_extension_invariants
        - the same seeds yield the same slot arms (deterministic)

    Raises:
        - AssertionError if any design constraint is violated
    """
    rng            = random.Random( seed )
    tuesday_arms   = randomize_with_max_run( [ BLIND ] * SLOTS_PER_ARM_PER_DAY + [ REJECTING ] * SLOTS_PER_ARM_PER_DAY, MAX_RUN, rng )
    wednesday_arms = [ mirror_arm( arm ) for arm in tuesday_arms ]

    tz    = ZoneInfo( TIMEZONE )
    slots = _build_day_slots( TUESDAY_DATE, tuesday_arms, tz ) + _build_day_slots( WEDNESDAY_DATE, wednesday_arms, tz )
    for slot in slots:
        slot[ "block" ] = SCHEDULE_ID

    original = {
        "schedule_id" : SCHEDULE_ID,
        "experiment"  : EXPERIMENT,
        "seed"        : seed,
        "timezone"    : TIMEZONE,
        "window"      : { "start_hour": WINDOW_START_HOUR, "end_hour": WINDOW_END_HOUR },
        "max_run"     : MAX_RUN,
        "slots"       : slots,
    }
    _assert_invariants( original )

    ext_slots = build_extension_slots( ext_seed )
    _assert_extension_invariants( ext_slots )

    wk2_slots = build_week2_slots( wk2_seed )
    _assert_week2_invariants( wk2_slots )

    schedule = dict( original )
    schedule[ "ext_seed" ]   = ext_seed
    schedule[ "ext_block" ]  = EXT_BLOCK_ID
    schedule[ "wk2_seed" ]   = wk2_seed
    schedule[ "wk2_block" ]  = WK2_BLOCK_ID
    schedule[ "slots" ]      = slots + ext_slots + wk2_slots
    _assert_blocks_are_disjoint( schedule[ "slots" ] )
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
