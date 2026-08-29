#!/usr/bin/env python3
"""
Re-run the subject-loss measurement for row cf1587cd from the live DM traffic corpus.

The labelled sets next to this file store corpus KEYS (ts / from / to), not message
bodies — the bodies stay in the corpus where they were written, so this directory does
not become a second copy of the fleet's mail.

    PYTHONPATH=src python3 src/rnd/v0.2.0/2026.08.26-dm-subject-loss/rerun_measurement.py

Requires:
    - spacy with en_core_web_sm installed
    - the DM traffic corpus readable at $LUPIN_DM_CORPUS_DIR or the fleet data root

Ensures:
    - prints agreement, precision and recall on each labelled set
    - prints the full-corpus flag rate
    - exits 1 if the corpus cannot be found, rather than reporting an empty run as a
      clean one
"""

import json
import os
import sys

HERE = os.path.dirname( os.path.abspath( __file__ ) )
sys.path.insert( 0, HERE )

from subject_loss_detector import classify   # noqa: E402


def corpus_path():
    """
    Locate dm_traffic.jsonl the same way the send path does.

    Ensures:
        - returns $LUPIN_DM_CORPUS_DIR/dm_traffic.jsonl when the env var is set
        - otherwise derives <projects-parent>/projects-data/<repo>/dm-corpus/…

    Raises:
        - nothing
    """
    override = os.environ.get( "LUPIN_DM_CORPUS_DIR" )
    if override: return os.path.join( override, "dm_traffic.jsonl" )
    root = os.path.abspath( os.environ.get( "LUPIN_ROOT", "/var/lupin" ) )
    return os.path.join(
        os.path.dirname( os.path.dirname( root ) ), "projects-data",
        os.path.basename( root ), "dm-corpus", "dm_traffic.jsonl"
    )


def load_pairs( path ):
    """
    Every ( submitted, delivered ) pair the tutor actually rewrote, keyed for lookup.

    Requires:
        - path names the JSONL traffic corpus

    Ensures:
        - returns a dict keyed ( ts, from, to ) holding the body and delivered body
        - skips malformed lines rather than raising on them

    Raises:
        - nothing
    """
    out = {}
    with open( path, encoding="utf-8" ) as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            try:
                row = json.loads( line )
            except Exception:
                continue
            if row.get( "tutor_outcome" ) != "rewritten": continue
            if row.get( "origin" ) != "live": continue
            out[ ( row[ "ts" ], row.get( "from" ), row.get( "to" ) ) ] = row
    return out


def score_set( name, pairs, labelled ):
    """Print agreement, precision and recall for one labelled set."""
    tp = fp = fn = tn = 0
    missing = 0
    for item in labelled:
        row = pairs.get( ( item[ "ts" ], item[ "from" ], item[ "to" ] ) )
        if row is None:
            missing += 1
            continue
        auto = classify( row[ "body" ], row[ "delivered_body" ] )[ "subject_lost" ]
        hand = bool( item[ "subject_lost" ] )
        if   hand and auto:         tp += 1
        elif hand:                  fn += 1
        elif auto:                  fp += 1
        else:                       tn += 1
    n = tp + fp + fn + tn
    print( f"{name}: {n} scored, {missing} not found in corpus" )
    if not n: return
    print( f"   agreement {tp + tn}/{n} = {( tp + tn ) / n:.0%}"
           f"   TP {tp} FP {fp} FN {fn} TN {tn}" )
    if tp + fp: print( f"   precision {tp / ( tp + fp ):.2f}" )
    if tp + fn: print( f"   recall    {tp / ( tp + fn ):.2f}" )


def main():
    path = corpus_path()
    if not os.path.exists( path ):
        print( f"corpus not found at {path}" )
        return 1
    pairs = load_pairs( path )
    print( f"corpus: {len( pairs )} rewritten live pairs at {path}\n" )

    for fname, label in ( ( "calibration-50.json", "calibration (tuned on)" ),
                          ( "holdout-25.json",     "held out (the honest number)" ) ):
        with open( os.path.join( HERE, fname ), encoding="utf-8" ) as fh:
            score_set( label, pairs, json.load( fh ) )
        print()

    flagged = sum( classify( r[ "body" ], r[ "delivered_body" ] )[ "subject_lost" ]
                   for r in pairs.values() )
    print( f"full corpus: {flagged}/{len( pairs )} flagged = {flagged / len( pairs ):.1%}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
