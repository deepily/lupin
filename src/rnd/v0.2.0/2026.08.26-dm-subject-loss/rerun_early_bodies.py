#!/usr/bin/env python3
"""
Re-condense EARLY-period bodies with today's model and today's shipped prompt.

The one question this answers: did the CONDENSER drift, or did the BODIES change?
Same body, same prompt, two moments — anything that moves is the environment.
The first pass gave 20 worse / 9 better, p = 0.061: suggestive, not an answer. This
is the bigger n rather than reporting a near-miss as a finding.
"""
import json, os, random, sys, time
sys.path.insert( 0, os.path.dirname( os.path.abspath( __file__ ) ) )
from cosa.agents.dm_tutor.agent import DmTutorAgent
from detect_frozen import classify

HERE  = os.path.dirname( os.path.abspath( __file__ ) )
EARLY = { "2026-08-13","2026-08-14","2026-08-15","2026-08-16","2026-08-17","2026-08-18","2026-08-19" }


def rewrite( body ):
    """One body through the shipped prompt. Returns the rewrite or None."""
    try:
        return DmTutorAgent( dm_body=body ).rewrite()
    except Exception:
        return None


def main():
    n    = int( sys.argv[1] ) if len( sys.argv ) > 1 else 200
    seed = int( sys.argv[2] ) if len( sys.argv ) > 2 else 31337
    pool = json.load( open( os.path.join( HERE, "pool.json" ), encoding="utf-8" ) )
    early = [ p for p in pool if p[ "ts" ][ :10 ] in EARLY ]
    random.seed( seed )
    sample = random.sample( early, min( n, len( early ) ) )

    rows = []
    t0 = time.time()
    for k, p in enumerate( sample ):
        out = rewrite( p[ "body" ] )
        rows.append( {
            "ts": p[ "ts" ], "from": p[ "from" ], "to": p[ "to" ],
            "lost_then": classify( p[ "body" ], p[ "delivered" ] )[ "subject_lost" ],
            "lost_now" : classify( p[ "body" ], out )[ "subject_lost" ] if out else None,
        } )
        if k and k % 20 == 0: print( f"  {k}/{len( sample )}  {time.time()-t0:.0f}s", flush=True )

    json.dump( rows, open( os.path.join( HERE, f"early_rerun-{seed}.json" ), "w" ) )
    both = [ r for r in rows if r[ "lost_now" ] is not None ]
    worse = sum( 1 for r in both if r[ "lost_now" ] and not r[ "lost_then" ] )
    better= sum( 1 for r in both if r[ "lost_then" ] and not r[ "lost_now" ] )
    then  = sum( r[ "lost_then" ] for r in both )
    now   = sum( r[ "lost_now" ]  for r in both )
    print( f"\nEARLY bodies, n={len( both )}" )
    print( f"  lost WHEN SENT   {then}/{len( both )} = {then/len( both ):.1%}" )
    print( f"  lost TODAY       {now}/{len( both )} = {now/len( both ):.1%}" )
    print( f"  discordant: worse today {worse}, better today {better}" )


if __name__ == "__main__":
    main()
