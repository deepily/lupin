#!/usr/bin/env python3
"""
Read a paired-replay results file and print what it can honestly say.

WHY A SEPARATE READER. The replay writes records and stops; turning them into a table
is a different job that must be re-runnable against a finished run without paying for
inference again. It is also where the two open rulings bite, so the refusals live here
in one place rather than being re-argued per reader.

WHAT IT REFUSES TO DO:
  - no fabrication RATE unless --denominator is passed. The denominator is Rick's
    ruling (narrow vs wide); a reader that picks one silently is publishing his
    decision under his name.
  - no p-value unless --floor is passed AND the discordant count clears it. The
    operational floor is Rick's too, pre-stated before arm 1. The arithmetic minimum
    is 6: with b+c=5 the best achievable p is 0.0625, which cannot clear 0.05.
  - no verdict of any kind about which model is more honest. Blocking on the guard is
    DETECTABILITY; honesty needs the hand-labelled sample (handoff §7 item 5).

Usage:
    PYTHONPATH=$LUPIN_ROOT/src python src/scripts/phi4_flash_lite_report.py \
        --results <run>/results.jsonl [--denominator narrow] [--floor 6]
"""
import argparse
import collections
import json
import sys

from cosa.research.phi4_flash_lite_study import replay_harness as rh
from cosa.research.phi4_flash_lite_study import statistics as study_statistics


# ⚠️ DO NOT `import statistics` IN THIS PACKAGE. It sat here as
# `import statistics as py_statistics` and worked in every test, then crashed the FIRST
# real 400-row run: this package contains its own `statistics.py`, and running the file
# directly (`python …/report.py`) puts its directory first on sys.path, so the name
# resolves to the sibling module instead of the standard library. The data was already
# safely on disk, but a reader that dies after a 42-minute paid run is a reader that
# failed when it mattered. `median` and `fmean` are three lines each — owning them costs
# less than the shadow.
def _median( values ):
    """
    Median of a list, without importing a name this package shadows.

    Requires:
        - values is a non-empty list of numbers

    Ensures:
        - returns the middle value, averaging the middle pair on an even count
        - does not assume the input is sorted

    Raises:
        - IndexError on an empty list — callers here guard for empty first
    """
    ordered = sorted( values )
    n       = len( ordered )
    mid     = n // 2
    return ordered[ mid ] if n % 2 else ( ordered[ mid - 1 ] + ordered[ mid ] ) / 2


def _mean( values ):
    """
    Arithmetic mean, same reasoning as _median.

    Requires:
        - values is a non-empty list of numbers

    Ensures:
        - returns sum / count

    Raises:
        - ZeroDivisionError on an empty list — callers here guard for empty first
    """
    return sum( values ) / len( values )


def load_run( path ):
    """
    Split a results file into its header and its per-row records.

    Requires:
        - path names a jsonl file written by the paired replay

    Ensures:
        - returns ( header_or_None, records ); a file with no run header yields None
          rather than guessing what selection produced it

    Raises:
        - nothing beyond the underlying IO/JSON errors
    """
    header  = None
    records = []
    for line in open( path, encoding="utf-8" ):
        row = json.loads( line )
        if row.get( "record_kind" ) == "run_header":
            header = row
        else:
            records.append( row )
    return header, records


def backfill_provenance( header, records, printer=print ):
    """
    Restore `snapshot_sha256` and `frozen_index` on records written before the harness
    carried them per row.

    WHY THIS IS RECOVERY AND NOT INVENTION. `pair_records` refuses to pair records that
    do not agree on which freeze they came from — correctly, since matching indices
    across two different snapshots is not a pairing. Records written by the earlier
    driver carry that provenance in the RUN HEADER instead of on each row: the header
    names the snapshot checksum and the exact drawn row indices, so both fields are
    derivable, not guessed. If the header is absent, nothing is backfilled and the
    pairing is allowed to fail loudly.

    Requires:
        - header is the run header dict, or None
        - records are the per-row records from the same file

    Ensures:
        - fills `snapshot_sha256` from the header and `frozen_index` from the header's
          drawn indices, ONLY where the field is missing
        - says out loud what it backfilled — a silently repaired file is one nobody can
          audit later
        - returns the number of records touched

    Raises:
        - nothing
    """
    if header is None:
        return 0

    sha   = header.get( "snapshot_sha256" )
    drawn = header.get( "drawn_row_indices" ) or []
    fixed = 0
    for record in records:
        touched = False
        if "snapshot_sha256" not in record and sha:
            record[ "snapshot_sha256" ] = sha
            touched = True
        if "frozen_index" not in record and drawn:
            index = record.get( "row_index" )
            if isinstance( index, int ) and 0 <= index < len( drawn ):
                record[ "frozen_index" ] = drawn[ index ]
                touched = True
        fixed += 1 if touched else 0

    if fixed:
        printer( f"backfilled provenance on {fixed} record(s) from the run header "
                 f"(snapshot {str( sha )[ :16 ]}) — written before the harness carried it per row" )
    return fixed


def _percentile( sorted_values, fraction ):
    """
    The package's ONE percentile, rounded for display.

    ⚠️ THIS USED TO BE A SECOND IMPLEMENTATION. Sam wrote nearest-rank here while
    Clayton wrote linear interpolation in `replay_harness`, and on the same 8 rows
    that gave flash_lite a p90 of 24.524 from this module and 14.225 from the other —
    two readers disagreeing about identical data. Now it delegates, so the method
    lives in exactly one place (`replay_harness.PERCENTILE_METHOD`, currently
    nearest-rank, which is this module's original behaviour).

    Requires:
        - sorted_values is a non-empty ascending list
        - fraction is in (0, 1]

    Ensures:
        - returns the shared percentile, rounded to 3 dp for the printed report
        - preserves this module's prior behaviour while PERCENTILE_METHOD is
          "nearest_rank": the value returned is one that was actually MEASURED
        - on a small sample a high percentile collapses onto the maximum — with n=8
          the p99 IS the max, and saying so beats implying a tail resolution the
          sample does not have

    Raises:
        - nothing
    """
    from cosa.research.phi4_flash_lite_study.replay_harness import _percentile as shared
    return round( shared( sorted_values, fraction ), 3 )


def latency_block( records ):
    """
    Per-arm wall-clock latency, over FIRED rows only, plus the between-arm ratio.

    THIS IS A DEPLOYMENT COMPARISON, NOT A CLAIM ABOUT MODEL SPEED (Rick's ruling,
    2026-08-17). What is being timed is two whole paths as they are actually wired: a
    local vLLM on the LAN versus a hosted Vertex endpoint across the public internet.
    A different deployment of either model — the same weights on other hardware, a
    closer region, a warmed connection — moves these numbers without changing either
    model. Nothing here says one model is faster than the other; it says one PATH
    answered faster on this host, today.

    WHAT THE NUMBER CONTAINS, said before anyone quotes it: `elapsed_seconds` wraps the
    whole `_apply_dm_tutor` call — claim counting, the model call, the pointer restore
    and the guards. On a fired row the model dominates; on a row the tutor never fired
    it is microseconds of counting. Mixing those two populations would drag a median
    toward zero in whichever arm happened to fire less, so only FIRED rows are counted.

    It is wall clock from one host: the phi_4 arm reaches a LAN vLLM and the flash_lite
    arm crosses the public internet to Vertex, and the two arms ran SEQUENTIALLY, not
    under matched load.

    Requires:
        - records carry `arm`, `meta` and `elapsed_seconds`

    Ensures:
        - returns { arm: {...} } with n / median / mean / p90 / min / max / total, and
          a "ratio" entry giving flash_lite ÷ phi_4 on the median and on the total when
          both arms are present
        - reports the RATIO, never a verdict about it

    Raises:
        - nothing
    """
    # Mr. Radio's ask: SAY which definition produced these figures. A p90 whose method
    # is unstated is a number two readers can compute differently and both be right —
    # which is exactly what happened here before the definitions were merged.
    from cosa.research.phi4_flash_lite_study.replay_harness import PERCENTILE_METHOD

    block = { "percentile_definition": (
        f"{PERCENTILE_METHOD} — every figure is a value that was actually MEASURED; no "
        f"interpolation. On a small sample a high percentile collapses onto the maximum "
        f"(at n=8, p99 IS the max)."
    ) }
    for arm in sorted( { r[ "arm" ] for r in records } ):
        fired = [ r for r in records
                  if r[ "arm" ] == arm and r[ "meta" ].get( "tutor_fired" ) and r.get( "elapsed_seconds" ) is not None ]
        secs  = sorted( r[ "elapsed_seconds" ] for r in fired )
        if not secs:
            block[ arm ] = { "fired_rows": 0 }
            continue
        block[ arm ] = {
            "fired_rows" : len( secs ),
            "median_s"   : round( _median( secs ), 3 ),
            "mean_s"     : round( _mean( secs ), 3 ),
            "p90_s"      : _percentile( secs, 0.90 ),
            "p99_s"      : _percentile( secs, 0.99 ),
            "min_s"      : round( secs[ 0 ], 3 ),
            "max_s"      : round( secs[ -1 ], 3 ),
            "total_s"    : round( sum( secs ), 1 ),
        }

    if { "phi_4", "flash_lite" } <= set( block ) and block[ "phi_4" ].get( "median_s" ) and block[ "flash_lite" ].get( "median_s" ):
        block[ "ratio" ] = {
            "basis"    : "flash_lite ÷ phi_4, fired rows only",
            "median_x" : round( block[ "flash_lite" ][ "median_s" ] / block[ "phi_4" ][ "median_s" ], 2 ),
            "total_x"  : round( block[ "flash_lite" ][ "total_s" ]  / block[ "phi_4" ][ "total_s" ],  2 ),
        }
    return block


def per_arm_table( records ):
    """
    One row per arm: outcome counts, median words out, elapsed seconds.

    Requires:
        - records carry `arm`, `meta` and `elapsed_seconds`

    Ensures:
        - returns { arm: {...} } with NO rate — rates need a denominator nobody has
          chosen yet

    Raises:
        - nothing
    """
    table = {}
    for arm in sorted( { r[ "arm" ] for r in records } ):
        rows     = [ r for r in records if r[ "arm" ] == arm ]
        outcomes = collections.Counter( r[ "meta" ].get( "tutor_outcome" ) for r in rows )
        words    = [ r[ "meta" ][ "tutor_words_out" ] for r in rows if r[ "meta" ].get( "tutor_words_out" ) is not None ]
        secs     = [ r[ "elapsed_seconds" ] for r in rows if r.get( "elapsed_seconds" ) is not None ]
        table[ arm ] = {
            "rows"             : len( rows ),
            "spec_key"         : rows[ 0 ].get( "spec_key" ),
            "outcomes"         : dict( outcomes ),
            "median_words_out" : _median( words ) if words else None,
            "median_seconds"   : _median( secs )  if secs  else None,
            "total_seconds"    : round( sum( secs ), 1 )       if secs  else None,
        }
    return table


def main( argv=None, printer=print ):
    """
    Print the per-arm table, the discordant cells, and — only if licensed — statistics.

    Requires:
        - --results names a finished paired run

    Ensures:
        - prints the counts unconditionally; prints rates ONLY with --denominator and
          a p-value ONLY with --floor, saying out loud when it is withholding and why
        - returns 0

    Raises:
        - nothing it does not print first
    """
    parser = argparse.ArgumentParser( description="Report on a paired replay run" )
    parser.add_argument( "--results",     required=True )
    parser.add_argument( "--denominator", default=None, help="Rick's ruling; omit and rates are withheld" )
    parser.add_argument( "--floor",       default=None, type=int, help="Rick's PRE-STATED operational floor" )
    parser.add_argument( "--outcome",     default="fabrication_blocked" )
    args = parser.parse_args( argv )

    header, records = load_run( args.results )
    arms            = sorted( { r[ "arm" ] for r in records } )

    if header is None:
        printer( "run header ABSENT — the selection that produced this file is unknown; treat counts as unattributed" )
    else:
        printer( f"selection: {header.get( 'selection' )} | seed {header.get( 'seed' )} | "
                 f"{header.get( 'sample_size' )} of {header.get( 'frozen_set_rows' )} rows | "
                 f"snapshot {str( header.get( 'snapshot_sha256' ) )[ :16 ]}" )

    backfill_provenance( header, records, printer=printer )

    for arm, stats in per_arm_table( records ).items():
        printer( f"{arm:12} {stats[ 'rows' ]:>4} rows | {stats[ 'spec_key' ]:<22} | {stats[ 'outcomes' ]} | "
                 f"median words {stats[ 'median_words_out' ]} | median {stats[ 'median_seconds' ]}s | total {stats[ 'total_seconds' ]}s" )

    printer( "" )
    printer( "latency — a DEPLOYMENT comparison, NOT a claim about model speed (Rick, 2026-08-17)." )
    printer( "FIRED rows only; wall clock around the whole _apply_dm_tutor call; one host, arms run" )
    printer( "sequentially; phi_4 to a LAN vLLM, flash_lite across the public internet to Vertex." )
    printer( "Percentiles are nearest-rank, so on a small sample p99 collapses onto the maximum:" )
    for name, stats in latency_block( records ).items():
        printer( f"  {name:12} {stats}" )

    if len( arms ) != 2:
        printer( f"only {len( arms )} arm(s) present — nothing to pair" )
        return 0

    arm_a, arm_b = arms
    paired       = rh.pair_records( [ r for r in records if r[ "arm" ] == arm_a ],
                                    [ r for r in records if r[ "arm" ] == arm_b ] )
    # discordant_counts returns a NAMED dict (Clayton, 500e2a1b), not a bare (b, c) —
    # deliberately, because the two of us had labelled the cells in opposite orders and
    # a tuple lets the next reader quote the direction backwards. Read the arm-named
    # keys, never positions.
    cells        = rh.discordant_counts( paired, arm_a, arm_b, outcome=args.outcome )
    b, c         = cells[ f"only_{arm_a}" ], cells[ f"only_{arm_b}" ]
    printer( f"paired {len( paired )} rows | discordant on '{args.outcome}': "
             f"only_{arm_a}={b}, only_{arm_b}={c} | n_discordant={cells[ 'n_discordant' ]} | "
             f"{cells[ 'direction' ]}" )

    if args.denominator is None:
        printer( "RATES WITHHELD — no denominator. Rick's ruling (narrow vs wide); a reader that "
                 "picks one silently publishes his decision under his name." )
    else:
        printer( "" )
        printer( f"fabrication rate, denominator '{args.denominator}' (Rick's ruling — the reader never picks one):" )
        for arm in arms:
            metas = [ r[ "meta" ] for r in records if r[ "arm" ] == arm ]
            summary = rh.summarize_arm( metas, denominator=args.denominator )
            printer( f"  {arm:12} {summary[ 'fabrication_blocked' ]}/{summary[ 'rows' ]} rows | "
                     f"rate {summary[ 'fabrication_rate' ]:.4f} | model_failed {summary[ 'model_failed' ]}" )

    if args.floor is None:
        printer( f"STATISTICS WITHHELD — no pre-stated operational floor. The arithmetic minimum is "
                 f"{study_statistics.ARITHMETIC_DISCORDANT_FLOOR}; the operational number is Rick's, "
                 f"and it has to be stated BEFORE the run, not chosen after seeing b and c." )
        return 0

    try:
        printer( json.dumps( study_statistics.compare_arms( b, c, operational_floor=args.floor,
                                                            arm_a=arm_a, arm_b=arm_b ), indent=2, default=str ) )
    except Exception as e:
        printer( f"statistics REFUSED: {type( e ).__name__}: {e}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
