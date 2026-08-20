#!/usr/bin/env python3
"""
Per-block failure-rate watcher for the CJ Flow v2 paired run (row d8d019f6).

WHY THIS EXISTS (María 🌸, row 2ebe4ccb, 2026-08-17): a paired run can degrade
CATEGORICALLY rather than randomly. On 08-17 the per-50 failure blocks ran
10%, 10%, 4%, 38%, 94% — and because the corpus is ORDERED BY CATEGORY, that
last block means the mode-switch/routing category was ~94% absent from the v2
arm while v1 kept it intact. Routing accuracy is computed over `ok` records
only, so the two arms then get scored on differently-composed corpora and the
arm that LOST its hardest category scores BETTER.

🔴 THE SAMPLE-SIZE FLOOR DOES NOT CATCH THIS. ~300 pairs still survive a 32%
failure rate, so the run reads as well-powered while measuring two different
things. A flat 30% is survivable; a rate that CLIMBS block over block is the
signature that a whole category is dropping out. Flatness is the test, not
magnitude.

    python3 src/scripts/watch-paired-block-failure-rate.py [--block 50] [--since <epoch>] [--follow]

Prints one line per COMPLETED block and flags escalation. It only reads and
reports — it never kills the run. Killing a live job needs Rick's word.
"""

import argparse, json, os, sys, time


def read_end_records( path, since ):
    """
    Return the run's completed attempts, in file order.

    Requires:
        - path names a jsonl file whose records carry phase/ok/seq/wall_ts

    Ensures:
        - returns a list of dicts for phase == "end" with wall_ts >= since
        - skips malformed lines rather than dying mid-run (this watches a LIVE
          file, so a half-written final line is expected, not exceptional)
    """
    out = []
    if not os.path.exists( path ): return out
    with open( path ) as fh:
        for line in fh:
            try:
                d = json.loads( line )
            except Exception:
                continue                                  # a partially-flushed tail line
            if d.get( "phase" ) != "end": continue
            try:
                if float( d.get( "wall_ts", 0 ) ) < since: continue
            except Exception:
                continue
            out.append( d )
    return out


def blocks( records, size ):
    """Yield (index, block) for each COMPLETE block of `size` records."""
    for i in range( 0, len( records ) - size + 1, size ):
        yield i // size, records[ i : i + size ]


def failure_rate( block ):
    """Fraction of a block whose `ok` is not truthy. Handles the string 'False'."""
    bad = sum( 1 for r in block if str( r.get( "ok" ) ).lower() not in ( "true", "1" ) )
    return bad / len( block )


def escalating( rates ):
    """
    True when the newest block is BOTH materially worse than the run so far and
    high in absolute terms — the 08-17 signature. A uniformly bad run is a
    different problem and this deliberately stays quiet about it.
    """
    if len( rates ) < 3: return False
    prior, latest = rates[ :-1 ], rates[ -1 ]
    base = sorted( prior )[ len( prior ) // 2 ]           # median of prior blocks
    return latest >= 0.25 and latest >= max( 2 * base, base + 0.20 )


def main( argv=None ):
    ap = argparse.ArgumentParser()
    ap.add_argument( "--path",  default="io/v2-flow/ask-attempts.jsonl" )
    ap.add_argument( "--block", type=int, default=50 )
    ap.add_argument( "--since", type=float, default=0.0, help="epoch seconds; ignore records older than this" )
    ap.add_argument( "--follow", action="store_true", help="keep watching, emitting one line per new completed block" )
    ap.add_argument( "--interval", type=int, default=60 )
    args = ap.parse_args( argv )

    seen = 0
    while True:
        recs  = read_end_records( args.path, args.since )
        rates = [ failure_rate( b ) for _, b in blocks( recs, args.block ) ]
        for i in range( seen, len( rates ) ):
            window = rates[ : i + 1 ]
            flag   = "🔴 ESCALATING" if escalating( window ) else "ok"
            print( f"block {i+1} (attempts {i*args.block+1}-{(i+1)*args.block}): "
                   f"failure {rates[i]*100:.0f}%  [{flag}]", flush=True )
        seen = len( rates )
        if not args.follow: break
        time.sleep( args.interval )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
