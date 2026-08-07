"""
Measure the freeze protocol against the pinned corpus snapshot. Zero API spend.

Answers three open questions:
  1. spans per DM with the widened taxonomy (Maria measured 3.9 with a narrower one)
  2. placeholder token overhead under [[L00]] versus the literals replaced
  3. whether bare ALL-CAPS should join CONST (the 305-vs-8,330 disagreement)
"""

import json
import re
import sys
import collections

sys.path.insert( 0, "src" )

from cosa.agents.dm_compression.freeze import (
    freeze, extract_spans, resolve_spans, restore, validate, OPEN_DELIM, CLOSE_DELIM
)

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"

try:
    import tiktoken
    ENC = tiktoken.get_encoding( "o200k_base" )
    def ntok( s ): return len( ENC.encode( s ) )
    TOKENIZER = "o200k_base (tiktoken)"
except Exception:
    # Deliberately crude, and labelled as such wherever it is reported. A
    # character heuristic cannot settle a tokenizer question; it can only show
    # whether the direction of the effect is the one Maria measured.
    def ntok( s ): return max( 1, round( len( s ) / 4 ) )
    TOKENIZER = "chars/4 HEURISTIC — tiktoken unavailable, treat as direction only"


def main():
    bodies = []
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: r = json.loads( line )
        except Exception: continue
        b = r.get( "body" )
        if b: bodies.append( b )

    total_spans   = 0
    kind_counts   = collections.Counter()
    lit_tokens    = 0
    ph_tokens     = 0
    ph_tokens_alt = 0
    ratios        = []
    bypassed      = 0
    roundtrip_ok  = 0
    roundtrip_bad = []

    for body in bodies:
        fm = freeze( body )
        total_spans += len( fm.placeholders )
        ratios.append( fm.frozen_char_ratio )
        if fm.should_bypass: bypassed += 1

        for p in fm.placeholders:
            kind_counts[ p.kind ] += 1
            lit_tokens    += ntok( p.literal )
            ph_tokens     += ntok( p.token )
            ph_tokens_alt += ntok( "⟦" + p.token[ 2:-2 ] + "⟧" )

        # The extractor/restorer identity property, on every single record.
        if restore( fm.frozen_text, fm ) == body: roundtrip_ok += 1
        else: roundtrip_bad.append( body[ :80 ] )

    n = len( bodies )
    ratios.sort()

    def pct( p ): return ratios[ min( int( len( ratios ) * p ), len( ratios ) - 1 ) ] * 100

    print( f"corpus            : {n} bodies" )
    print( f"tokenizer         : {TOKENIZER}" )
    print()
    print( f"resolved spans    : {total_spans}  ({total_spans / n:.2f} per DM)" )
    print( f"identity roundtrip: {roundtrip_ok}/{n} exact" )
    if roundtrip_bad:
        print( f"  FAILURES: {roundtrip_bad[ :3 ]}" )
    print()
    print( f"frozen char ratio : mean {sum( ratios ) / n * 100:.1f}%  p50 {pct( .50 ):.1f}%  "
           f"p90 {pct( .90 ):.1f}%  p99 {pct( .99 ):.1f}%  max {ratios[ -1 ] * 100:.1f}%" )
    print( f"bypassed          : {bypassed} ({bypassed / n * 100:.1f}%)" )
    print()
    print( f"literal tokens    : {lit_tokens:,}" )
    print( f"[[L00]] tokens    : {ph_tokens:,}   delta {ph_tokens - lit_tokens:+,}" )
    print( f"vs plan's  ⟦L00⟧  : {ph_tokens_alt:,}   delta {ph_tokens_alt - lit_tokens:+,}" )
    print()
    print( "top span kinds:" )
    for kind, count in kind_counts.most_common( 14 ):
        print( f"  {kind:<10} {count:>6}" )

    # The CONST disagreement: what would a bare ALL-CAPS rule actually catch?
    bare_caps = collections.Counter()
    for body in bodies:
        for m in re.finditer( r"\b[A-Z]{2,}\b", body ):
            if "_" not in m.group( 0 ): bare_caps[ m.group( 0 ) ] += 1
    print()
    print( f"bare ALL-CAPS (no underscore): {sum( bare_caps.values() )} hits, "
           f"{len( bare_caps )} distinct" )
    print( f"  most common: {bare_caps.most_common( 15 )}" )


if __name__ == "__main__":
    main()
