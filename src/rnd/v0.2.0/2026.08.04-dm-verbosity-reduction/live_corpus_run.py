"""
Live corpus run — freeze → Phi-4 on :3001 → validate → restore.

Reports what the plan's §Verification asks for: placeholder fidelity, verify-tier
survival, fail-closed rate, achieved compression per size band, and latency.

Zero cost — the model is local.

⚠️ PERSISTS ITS ROWS. An earlier version of this harness lived in a scratchpad
and printed a summary, so its numbers existed only in a DM and nobody could
re-read them. Every run now writes a JSONL row per message to
`io/arm4/` so the claim and the evidence travel together.

🔑 READ THE BANDS, NOT THE BLENDED MEAN. The plan's compression target is
SIZE-SCALED — 15% at <80 words rising to 65% at 400+ — so a single blended
percentage compared against "15-65%" is comparing to a number that does not
exist. A sample that skews short will look like a failure against a target it
was never measured against. (María, 2026-08-07.)
"""

import json
import statistics
import pathlib
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_compression.freeze import freeze, validate, compress_or_original
from cosa.agents.dm_compression.compressor import DmCompressionAgent

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
SAMPLE_N = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 25

# The plan's size-scaled targets, so every band prints against its OWN number.
BAND_TARGET = { "<80": 0.15, "80-150": 0.30, "150-250": 0.45, "250-400": 0.55, "400+": 0.65 }


def band( words ):
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    if words < 400: return "250-400"
    return "400+"


def main():
    bodies = []
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        if record.get( "body" ): bodies.append( record[ "body" ] )

    # Deterministic stride sample — same set every run, no RNG.
    stride  = max( 1, len( bodies ) // SAMPLE_N )
    sample  = bodies[ ::stride ][ :SAMPLE_N ]

    results = []
    for i, body in enumerate( sample, 1 ):
        fm = freeze( body )
        if fm.should_bypass:
            results.append( { "outcome": "bypassed", "reason": fm.bypass_reason, "words": len( body.split() ) } )
            print( f"  [{i}/{len(sample)}] bypassed" )
            continue

        started = time.time()
        try:
            agent    = DmCompressionAgent( frozen_text=fm.frozen_text )
            response = agent.run_prompt()
            latency  = time.time() - started
        except Exception as e:
            results.append( { "outcome": "model_error", "reason": f"{type(e).__name__}: {e}",
                              "words": len( body.split() ), "latency": time.time() - started } )
            print( f"  [{i}/{len(sample)}] MODEL ERROR {type(e).__name__}: {str(e)[:70]}" )
            continue

        rewritten = response.get( "compressed" ) if isinstance( response, dict ) else None
        if not rewritten:
            results.append( { "outcome": "empty", "words": len( body.split() ), "latency": latency } )
            print( f"  [{i}/{len(sample)}] empty response" )
            continue

        verdict      = validate( rewritten, fm )
        delivered, r = compress_or_original( rewritten, fm )

        row = {
            "outcome"  : "compressed" if r is None else "fell_back",
            "reason"   : r,
            "words"    : len( body.split() ),
            "band"     : band( len( body.split() ) ),
            "latency"  : latency,
            "in_chars" : len( body ),
            "out_chars": len( delivered ),
            "ratio"    : 1 - ( len( delivered ) / len( body ) ) if r is None else 0.0,
            "warnings" : [ n for n, _ in verdict.warnings ],
        }
        results.append( row )
        mark = "✓" if r is None else "✗"
        print( f"  [{i}/{len(sample)}] {mark} {row['band']:<8} {latency:5.1f}s  "
               f"ratio {row['ratio']:5.1%}  {('' if r is None else r[:60])}" )

    # ── Report ────────────────────────────────────────────────────────────────
    print()
    print( "=" * 70 )
    counts = {}
    for r in results: counts[ r[ "outcome" ] ] = counts.get( r[ "outcome" ], 0 ) + 1
    print( "outcomes:", counts )

    compressed = [ r for r in results if r[ "outcome" ] == "compressed" ]
    attempted  = [ r for r in results if r[ "outcome" ] not in ( "bypassed", ) ]

    if attempted:
        print( f"fail-closed rate: {1 - len(compressed)/len(attempted):.1%} "
               f"({len(attempted)-len(compressed)}/{len(attempted)} attempted)" )

    if compressed:
        lat = sorted( r[ "latency" ] for r in compressed )
        print( f"latency  p50 {statistics.median(lat):.1f}s  "
               f"p99 {lat[min(int(len(lat)*0.99), len(lat)-1)]:.1f}s  max {lat[-1]:.1f}s" )
        print( f"compression mean {statistics.mean(r['ratio'] for r in compressed):.1%}" )

        by_band = {}
        for r in compressed: by_band.setdefault( r[ "band" ], [] ).append( r[ "ratio" ] )
        print( "  by band:" )
        for b in [ "<80", "80-150", "150-250", "250-400", "400+" ]:
            if b in by_band:
                got    = statistics.mean( by_band[ b ] )
                target = BAND_TARGET[ b ]
                verdict = "MEETS" if got >= target else f"short by {target - got:.1%}"
                print( f"    {b:<8} n={len(by_band[b]):<3} mean {got:6.1%}  target {target:.0%}  {verdict}" )

        warned = [ r for r in compressed if r[ "warnings" ] ]
        print( f"  relocation warnings: {len(warned)}/{len(compressed)}" )

    # ── Persist ───────────────────────────────────────────────────────────────
    out_dir = pathlib.Path( "io/arm4" )
    out_dir.mkdir( parents=True, exist_ok=True )
    out_path = out_dir / f"live-run-n{len(sample)}.jsonl"
    with open( out_path, "w" ) as handle:
        for r in results: handle.write( json.dumps( r ) + "\n" )
    print( f"rows written: {out_path}" )

    fell = [ r for r in results if r[ "outcome" ] == "fell_back" ]
    if fell:
        print( "fallback reasons:" )
        for r in fell[ :8 ]: print( f"    {r['reason'][:100]}" )


if __name__ == "__main__":
    main()
