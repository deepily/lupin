#!/usr/bin/env python3
"""
Run the paired replay over a SEEDED RANDOM SUBSET of the official frozen snapshot.

WHY THIS EXISTS. The harness CLI offers `--limit N`, which takes the FIRST N rows of
the frozen set. The frozen set is in corpus order, so `--limit` is a time-window
sample: it is whatever the fleet happened to be saying that afternoon, not a sample of
the study's population. Mr. Radio 🦉 called this out mid-run — the first 400 of 4,942
is a convenience sample, and a convenience sample is a caveat you have to carry
through every number that comes off it.

WHAT IT DOES INSTEAD. Loads the official snapshot through the harness's own
`load_frozen_rows` (so the live-path guard and the manifest checksum still apply),
draws a subset with `random.Random( seed ).sample`, and replays BOTH arms over the
SAME drawn rows. The seed and the drawn row indices are written into the run header,
so the exact subset is reproducible without re-freezing anything — the official
snapshot stays the one frozen set.

WHAT IT DELIBERATELY DOES NOT DO. No statistics. Rick has not set the operational
discordant floor or the fabrication denominator, and the harness raises rather than
defaulting on both. This script banks the paired `meta` and stops there.

Usage:
    PYTHONPATH=$LUPIN_ROOT/src python src/scripts/phi4_flash_lite_seeded_replay.py \
        --snapshot-dir <…>/frozen-2026.08.17 --out <…>/results.jsonl \
        --sample-size 400 --seed 20260817 --max-model-failed-rate 0.10
"""
import argparse
import datetime
import json
import random
import sys

from cosa.research.phi4_flash_lite_study import replay_harness as rh


def main( argv=None, printer=print ):
    """
    Draw a seeded subset of the frozen set and replay both arms over it.

    Requires:
        - snapshot_dir holds the official frozen snapshot and its manifest
        - max_model_failed_rate is PRE-STATED by the caller (the harness has no default)

    Ensures:
        - both arms replay the SAME drawn rows, in the same order, so pairing holds
        - writes one JSON record per row per arm, plus a run header naming the seed,
          the sample size, the drawn row indices and the snapshot checksum
        - returns 0 on a completed replay

    Raises:
        - whatever load_frozen_rows / replay_arm raise: a live path, a drifted
          snapshot, an unmeasurable row and a dead arm are all hard stops
    """
    parser = argparse.ArgumentParser( description="Seeded-subset paired replay" )
    parser.add_argument( "--snapshot-dir",          required=True )
    parser.add_argument( "--out",                   required=True )
    parser.add_argument( "--sample-size",           required=True, type=int )
    parser.add_argument( "--seed",                  required=True, type=int )
    parser.add_argument( "--max-model-failed-rate", required=True, type=float )
    parser.add_argument( "--preflight",             type=int, default=25 )
    args = parser.parse_args( argv )

    rows, manifest = rh.load_frozen_rows( args.snapshot_dir )
    if args.sample_size > len( rows ):
        raise ValueError( f"sample-size {args.sample_size} exceeds the frozen set's {len( rows )} rows" )

    indices = sorted( random.Random( args.seed ).sample( range( len( rows ) ), args.sample_size ) )
    drawn   = [ rows[ i ] for i in indices ]
    printer( f"drew {len( drawn )} of {len( rows )} rows with seed {args.seed}" )

    records = []
    for arm in ( rh.ARM_PHI4, rh.ARM_FLASH_LITE ):
        printer( f"replaying arm {arm} …" )
        arm_records = rh.replay_arm(
            drawn, arm,
            rewrite_fn            = rh.make_arm_rewrite_fn( arm ),
            max_model_failed_rate = args.max_model_failed_rate,
            preflight             = args.preflight,
        )
        records.extend( arm_records )
        printer( f"  {arm}: {len( arm_records )} rows recorded" )

    header = {
        "record_kind"           : "run_header",
        "study"                 : "phi4-vs-flash-lite",
        "selection"             : "seeded_random_subset",
        "seed"                  : args.seed,
        "sample_size"           : args.sample_size,
        "frozen_set_rows"       : len( rows ),
        "drawn_row_indices"     : indices,
        "snapshot_sha256"       : manifest.get( "snapshot_sha256" ),
        "max_model_failed_rate" : args.max_model_failed_rate,
        "denominator"           : None,
        "denominator_note"      : "unset — Rick's ruling; rates are deliberately NOT computed here",
        "ran_at_utc"            : datetime.datetime.now( datetime.timezone.utc ).isoformat(),
    }

    with open( args.out, "w", encoding="utf-8" ) as handle:
        handle.write( json.dumps( header ) + "\n" )
        for record in records:
            handle.write( json.dumps( record, default=str ) + "\n" )

    printer( f"wrote {len( records )} records to {args.out}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
