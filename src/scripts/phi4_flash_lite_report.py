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
import statistics as py_statistics
import sys

from cosa.research.phi4_flash_lite_study import replay_harness as rh
from cosa.research.phi4_flash_lite_study import statistics as study_statistics


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
            "median_words_out" : py_statistics.median( words ) if words else None,
            "median_seconds"   : py_statistics.median( secs )  if secs  else None,
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

    for arm, stats in per_arm_table( records ).items():
        printer( f"{arm:12} {stats[ 'rows' ]:>4} rows | {stats[ 'spec_key' ]:<22} | {stats[ 'outcomes' ]} | "
                 f"median words {stats[ 'median_words_out' ]} | median {stats[ 'median_seconds' ]}s | total {stats[ 'total_seconds' ]}s" )

    if len( arms ) != 2:
        printer( f"only {len( arms )} arm(s) present — nothing to pair" )
        return 0

    arm_a, arm_b = arms
    paired       = rh.pair_records( [ r for r in records if r[ "arm" ] == arm_a ],
                                    [ r for r in records if r[ "arm" ] == arm_b ] )
    b, c         = rh.discordant_counts( paired, arm_a, arm_b, outcome=args.outcome )
    printer( f"paired {len( paired )} rows | discordant on '{args.outcome}': "
             f"b={b} (only {arm_a}) c={c} (only {arm_b}) | b+c={b + c}" )

    if args.denominator is None:
        printer( "RATES WITHHELD — no denominator. Rick's ruling (narrow vs wide); a reader that "
                 "picks one silently publishes his decision under his name." )

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
