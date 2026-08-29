#!/usr/bin/env python3
"""
Regenerate the tutor's OUTPUT side, and persist it where the nightly sweep cannot reach.

    export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin
    cd $LUPIN_ROOT
    python src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/sentence_band_outputs.py

    --n-per-band N   messages per WORD band (default 50 — last night's 200)
    --limit N        stop after N messages, for a smoke run

WHY THIS FILE EXISTS AT ALL. Last night's 400-call run answered "how many words came
back" per word band and nothing else, because `dm_txt_run.py` writes its document to
/tmp and keeps no per-message record. /tmp is swept nightly. **The measurement was
gone before the question about it was asked.** Rick's fourth question — average
sentences and words of the OUTPUT, per band — cannot be answered from what survives,
so it is re-measured here, and the rows land under live-runs/ in the repo.

WHAT IS DIFFERENT FROM LAST NIGHT, said plainly so nothing is compared that shouldn't be:
  - ONE arm, sentinel ON. The 200-run priced the sentinel at 3 messages against a
    noise floor of 4 and could not call a winner, so a second arm buys nothing here.
  - No injected paths. They add a line to two messages; the pointer slot is not what
    this run is measuring.
  - Every delivered body is kept, so the output can be re-cut later without re-running.

The sample is the SAME 200 messages, selected the same way (stride over the corpus-
ordered pool of each word band), so the input side of this run and the input side of
last night's are the same set of messages.
"""

import json
import pathlib
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_tutor.agent     import DmTutorAgent
from cosa.agents.dm_tutor.sentences import count_sentences

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
OUT_DIR  = pathlib.Path( "src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/live-runs" )
OUT_PATH = OUT_DIR / "sentence-band-outputs-2026.08.12.jsonl"

WORD_BANDS = [ "<80", "80-150", "150-250", "250+" ]

SENTENCE_BANDS = [
    ( "1-2",   1,  2 ),
    ( "3-4",   3,  4 ),
    ( "5-8",   5,  8 ),
    ( "9-15",  9, 15 ),
    ( "16+",  16, 10 ** 9 ),
]


def _arg( flag, default ):
    """
    Read `--flag value` from argv.

    Requires:
        - flag is the full flag string including its leading dashes

    Ensures:
        - returns the following argv entry when the flag is present, else default

    Raises:
        - nothing
    """
    return sys.argv[ sys.argv.index( flag ) + 1 ] if flag in sys.argv else default


N_PER_BAND = int( _arg( "--n-per-band", 50 ) )
LIMIT      = int( _arg( "--limit", 0 ) )


def word_band_of( words ):
    """
    The arm-4 word band for a message.

    Requires:
        - words is a non-negative integer

    Ensures:
        - returns one of WORD_BANDS

    Raises:
        - nothing
    """
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    return "250+"


def sentence_band_of( sentences ):
    """
    The sentence band for a message.

    Requires:
        - sentences is a non-negative integer

    Ensures:
        - returns the label of the containing band, or "0" for a claimless body

    Raises:
        - nothing
    """
    for label, low, high in SENTENCE_BANDS:
        if low <= sentences <= high: return label
    return "0"


def load_sample():
    """
    The same 200 messages `dm_txt_run.select()` picks, without the path injection.

    Requires:
        - SNAPSHOT is a readable JSONL file whose rows carry a "body"

    Ensures:
        - returns a list of bodies, at most N_PER_BAND per word band, WORD_BANDS order

    Raises:
        - FileNotFoundError when the snapshot is missing
    """
    pools = {}

    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        body = record.get( "body" )
        if body: pools.setdefault( word_band_of( len( body.split() ) ), [] ).append( body )

    sample = []
    for band in WORD_BANDS:
        pool = pools.get( band, [] )
        if not pool: continue
        stride = max( 1, len( pool ) // N_PER_BAND )
        sample += pool[ ::stride ][ :N_PER_BAND ]

    return sample


def run_one( body ):
    """
    One message through the tutor, fail-closed.

    Requires:
        - body is a non-empty message

    Ensures:
        - returns a dict carrying the delivered text, latency and error
        - never raises — one bad message must not end a 200-message run

    Raises:
        - nothing
    """
    started = time.time()

    try:
        agent     = DmTutorAgent( dm_body=body, include_stop_sentinel=True )
        delivered = agent.rewrite()
        error     = agent.error
    except Exception as e:
        delivered, error = None, f"{type( e ).__name__}: {e}"

    return { "delivered" : delivered, "error" : error, "latency" : time.time() - started }


def main():
    sample = load_sample()
    if LIMIT: sample = sample[ :LIMIT ]

    OUT_DIR.mkdir( parents=True, exist_ok=True )

    print( "=" * 88 )
    print( f"tutor output re-measure · {len( sample )} messages · sentinel ON · one arm" )
    print( f"rows → {OUT_PATH}" )
    print( "=" * 88, flush=True )

    started = time.time()

    # Append-as-you-go, not write-at-the-end. A run that dies at message 180 should
    # still leave 179 measurements behind — the failure mode this file was written
    # to stop repeating.
    with open( OUT_PATH, "w" ) as handle:
        for index, body in enumerate( sample ):
            in_words     = len( body.split() )
            in_sentences = count_sentences( body )
            result       = run_one( body )
            delivered    = result[ "delivered" ]

            row = {
                "index"          : index,
                "in_words"       : in_words,
                "in_sentences"   : in_sentences,
                "word_band"      : word_band_of( in_words ),
                "sentence_band"  : sentence_band_of( in_sentences ),
                "ok"             : delivered is not None,
                "out_words"      : len( delivered.split() )     if delivered else 0,
                "out_sentences"  : count_sentences( delivered ) if delivered else 0,
                "latency"        : round( result[ "latency" ], 2 ),
                "error"          : result[ "error" ],
                "in_body"        : body,
                "out_body"       : delivered,
            }

            handle.write( json.dumps( row ) + "\n" )
            handle.flush()

            print( f"  {index + 1:>3}/{len( sample )} {row['word_band']:<9}"
                   f"{row['sentence_band']:<7}"
                   f"{in_words:>4}w/{in_sentences:>2}s → "
                   f"{row['out_words']:>4}w/{row['out_sentences']:>2}s "
                   f"{result['latency']:>5.1f}s  {'✓' if delivered else '🔴'}",
                   flush=True )

    print( f"\ndone in {( time.time() - started ) / 60:.1f} min → {OUT_PATH}" )


if __name__ == "__main__":
    main()
