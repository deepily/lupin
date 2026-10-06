#!/usr/bin/env python3
"""
Read a paired-replay results file and print only what the data can support.

This is a separate reader because the replay writes records and stops. Turning them into
a table is a different job, and it must be re-runnable on a finished run without paying
for inference again. The refusals live here in one place, so no other reader has to
re-argue them.

What it refuses to do:
  - no fabrication rate unless --denominator is passed. The denominator (narrow or wide)
    is the owner's ruling, and a reader that picks one silently publishes that decision
    under his name.
  - no p-value unless --floor is passed and the discordant count clears it. The
    operational floor is also the owner's, stated before arm 1. The arithmetic minimum
    is 6: with b+c=5 the best achievable p is 0.0625, which cannot clear 0.05.
  - no verdict of any kind about which model is more honest. Blocking on the guard shows
    detectability only; honesty needs the hand-labelled sample.

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
    Restore snapshot and frozen-index provenance on records that predate per-row fields.

    This is recovery, not invention. `pair_records` refuses records from different
    freezes. The earlier driver kept the provenance in the run header, so both fields
    are derivable, not guessed. With no header, nothing is backfilled and pairing fails loudly.

    Requires:
        - header is the run header dict, or None
        - records are the per-row records from the same file

    Ensures:
        - fills `snapshot_sha256` from the header and `frozen_index` from the header's
          drawn indices, only where the field is missing
        - says out loud what it backfilled, since a silently repaired file cannot be
          audited later
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
    Percentile of a sorted list, delegated to the shared harness and rounded.

    Two implementations gave different p90 values on identical data. Delegating keeps
    the method in one place, `replay_harness.PERCENTILE_METHOD`.

    Requires:
        - sorted_values is a non-empty ascending list
        - fraction is in (0, 1]

    Ensures:
        - returns the shared percentile, rounded to 3 dp for the printed report
        - preserves this module's prior behaviour while PERCENTILE_METHOD is
          "nearest_rank": the value returned is one that was actually measured
        - on a small sample a high percentile collapses onto the maximum: with n=8
          the p99 is the max, and saying so beats implying a tail resolution the
          sample does not have

    Raises:
        - nothing
    """
    from cosa.research.phi4_flash_lite_study.replay_harness import _percentile as shared
    return round( shared( sorted_values, fraction ), 3 )


def latency_block( records ):
    """
    Per-arm wall-clock latency over fired rows only, plus the between-arm ratio.

    This compares deployments, not model speed: a LAN vLLM against a hosted Vertex
    endpoint. An unfired row costs microseconds, so only fired rows count.
    The arms ran sequentially on one host.

    Requires:
        - records carry `arm`, `meta` and `elapsed_seconds`

    Ensures:
        - returns { arm: {...} } with n / median / mean / p90 / min / max / total, and
          a "ratio" entry giving flash_lite ÷ phi_4 on the median and on the total when
          both arms are present
        - reports the ratio, never a verdict about it

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
        - returns { arm: {...} } with no rate, since rates need a denominator nobody has
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
        - prints the counts unconditionally; prints rates only with --denominator and
          a p-value only with --floor, saying out loud when it is withholding and why
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
            # Print the rate's OWN denominator, not the row count. It read
            # "130/400 rows | rate 0.3316" — two numbers that do not divide to the third,
            # because 400 is how many rows ran while the narrow rate divides by
            # blocked + rewritten (392 here). A reader doing the arithmetic gets a
            # different answer than the printed rate, which is how a real number starts
            # looking wrong. Mr. Radio caught it by quoting 130/392 back at me.
            attempts = summary[ 'fabrication_blocked' ] + summary[ 'rewritten' ]
            printer( f"  {arm:12} {summary[ 'fabrication_blocked' ]}/{attempts} "
                     f"(blocked+rewritten; {summary[ 'rows' ]} rows ran) | "
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
