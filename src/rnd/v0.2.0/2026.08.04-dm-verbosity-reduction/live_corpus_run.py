"""
Live corpus run — the ACTUAL shipping path, measured end to end.

    freeze → Phi-4 on :3001 → validate → restore → minimum-gain gate

Zero cost; the model is local. The only budget is wall-clock.

Three things this harness gets right, each because an earlier version got it
wrong:

1. **It calls `compress_dm()`, the real pipeline.** An earlier version
   reimplemented the steps and applied the minimum-gain gate afterwards in
   analysis, which measures a reconstruction rather than the thing that ships.
   If the gate is in the product, it belongs in the run.

2. **It persists a row per message, into a TRACKED directory.** The first
   version printed a summary from a scratchpad, so its numbers existed only in
   a DM. The second version "fixed" that by writing to `io/`, which is
   gitignored (`.gitignore:90`, `io/**`) — the rows existed on one box and
   nobody else could read them either. Same defect, one directory over, and it
   looked solved because a file was undeniably being written. Rows now land
   beside this script in `src/rnd/`, which git actually keeps.

3. **It reports per band against that band's OWN target.** The plan's target is
   size-scaled — 15% at <80 words rising to 65% at 400+ — so a single blended
   percentage is compared against a number that does not exist.

Both CHARACTER and TOKEN ratios are recorded. Characters are what the earlier
runs reported; tokens are what the economics actually turn on, and they are not
interchangeable.

Usage:  python live_corpus_run.py [PER_BAND]      # default 10 per band
"""

import json
import pathlib
import statistics
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_compression.freeze import freeze
from cosa.agents.dm_compression.pipeline import compress_dm, MIN_USEFUL_GAIN
from cosa.agents.dm_compression.compressor import DmCompressionAgent

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
PER_BAND = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 10

# Arm B: inject each message's own band target into the prompt. Arm A (default)
# is the control — the template as written, which states a target RANGE but never
# tells the model which band THIS message is in. Until both are run, "the model
# cannot compress long messages" and "the prompt cannot get the model to" are
# indistinguishable, and only one of those is a reason to abandon the arm.
ARM_B = "--band-target" in sys.argv

BANDS       = [ "<80", "80-150", "150-250", "250+" ]
BAND_TARGET = { "<80": 0.15, "80-150": 0.30, "150-250": 0.45, "250+": 0.60 }

try:
    import tiktoken
    _ENC = tiktoken.get_encoding( "o200k_base" )
    def ntok( s ): return len( _ENC.encode( s ) )
    TOKENIZER = "o200k_base"
except Exception:
    def ntok( s ): return max( 1, round( len( s ) / 4 ) )
    TOKENIZER = "chars/4 HEURISTIC"


def band_of( words ):
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    return "250+"


def main():
    bodies = []
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        if record.get( "body" ): bodies.append( record[ "body" ] )

    # Stratified, deterministic: take an even stride WITHIN each band so the
    # sample is reproducible and every band is equally represented.
    by_band = { b: [] for b in BANDS }
    for body in bodies: by_band[ band_of( len( body.split() ) ) ].append( body )

    sample = []
    for b in BANDS:
        pool   = by_band[ b ]
        stride = max( 1, len( pool ) // PER_BAND )
        sample += [ ( b, body ) for body in pool[ ::stride ][ :PER_BAND ] ]

    print( f"corpus {len(bodies)} bodies · sampling {PER_BAND}/band · {len(sample)} total · "
           f"tokenizer {TOKENIZER} · arm {'B (band target in prompt)' if ARM_B else 'A (control)'}", flush=True )
    for b in BANDS: print( f"  {b:<8} pool {len(by_band[b]):>4}", flush=True )
    print( flush=True )

    results = []
    started_all = time.time()

    for i, ( b, body ) in enumerate( sample, 1 ):
        started = time.time()
        try:
            delivered, reason = compress_dm( body, band_target=BAND_TARGET[ b ] if ARM_B else None )
        except Exception as e:
            delivered, reason = body, f"HARNESS ERROR {type(e).__name__}: {e}"
        latency = time.time() - started

        in_tok, out_tok = ntok( body ), ntok( delivered )

        row = {
            "band"        : b,
            "words"       : len( body.split() ),
            "delivered"   : reason is None,
            "reason"      : reason,
            "latency"     : round( latency, 2 ),
            "in_chars"    : len( body ),
            "out_chars"   : len( delivered ),
            "in_tokens"   : in_tok,
            "out_tokens"  : out_tok,
            "char_ratio"  : round( 1 - len( delivered ) / len( body ), 4 ) if body else 0.0,
            "token_ratio" : round( 1 - out_tok / in_tok, 4 ) if in_tok else 0.0,
        }
        results.append( row )

        mark = "✓" if reason is None else "·"
        print( f"  [{i:>3}/{len(sample)}] {mark} {b:<8} {latency:5.1f}s  "
               f"chars {row['char_ratio']:6.1%}  tokens {row['token_ratio']:6.1%}  "
               f"{'' if reason is None else reason[:55]}", flush=True )

    elapsed = time.time() - started_all

    # ── Persist ───────────────────────────────────────────────────────────────
    # Beside this script, in src/rnd/ — a TRACKED path. See the module docstring:
    # io/ is gitignored, so persisting there is indistinguishable from not
    # persisting at all to anyone who is not on this machine.
    out_dir = pathlib.Path( __file__ ).parent / "live-runs"
    out_dir.mkdir( parents=True, exist_ok=True )
    out_path = out_dir / f"live-run-{PER_BAND}per-band{'-armB' if ARM_B else ''}.jsonl"
    with open( out_path, "w" ) as handle:
        for r in results: handle.write( json.dumps( r ) + "\n" )

    # ── Report ────────────────────────────────────────────────────────────────
    print()
    print( "=" * 78 )
    print( f"wall clock {elapsed/60:.1f} min · rows → {out_path}" )
    print()

    delivered = [ r for r in results if r[ "delivered" ] ]
    print( f"delivery rate: {len(delivered)}/{len(results)} = {len(delivered)/len(results):.1%}"
           f"   (fail-closed {1 - len(delivered)/len(results):.1%})" )

    lat = sorted( r[ "latency" ] for r in results )
    print( f"latency  p50 {statistics.median(lat):.1f}s  "
           f"p90 {lat[int(len(lat)*0.90)]:.1f}s  max {lat[-1]:.1f}s" )
    print()

    print( f"{'band':<9}{'n':>4}{'delivrd':>9}{'char%':>9}{'token%':>9}{'target':>8}   verdict" )
    for b in BANDS:
        rows = [ r for r in results if r[ "band" ] == b ]
        if not rows: continue
        won  = [ r for r in rows if r[ "delivered" ] ]
        # Mean over ALL sampled messages, not just the winners: a band where
        # most messages fall back has not compressed, whatever the winners did.
        char_mean  = statistics.mean( r[ "char_ratio" ]  if r[ "delivered" ] else 0.0 for r in rows )
        token_mean = statistics.mean( r[ "token_ratio" ] if r[ "delivered" ] else 0.0 for r in rows )
        target     = BAND_TARGET[ b ]
        verdict    = "MEETS" if token_mean >= target else f"short {target - token_mean:.0%}"
        print( f"{b:<9}{len(rows):>4}{len(won)/len(rows):>8.0%}{char_mean:>9.1%}"
               f"{token_mean:>9.1%}{target:>8.0%}   {verdict}" )

    print()
    saved = sum( r[ "in_tokens" ] - r[ "out_tokens" ] for r in results if r[ "delivered" ] )
    total = sum( r[ "in_tokens" ] for r in results )
    print( f"tokens on the sample: {total:,} in, {saved:,} saved = {saved/total:.1%}" )

    reasons = {}
    for r in results:
        if r[ "reason" ]:
            key = r[ "reason" ].split( ":" )[ 0 ]
            reasons[ key ] = reasons.get( key, 0 ) + 1
    print( "fallback reasons:", dict( sorted( reasons.items(), key=lambda kv: -kv[1] ) ) )
    print( f"minimum-gain gate: {MIN_USEFUL_GAIN:.0%} (applied IN the run, not in analysis)" )


if __name__ == "__main__":
    main()
