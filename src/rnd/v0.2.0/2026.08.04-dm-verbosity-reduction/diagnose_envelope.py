"""
Phase 0 diagnostic — WHY does the response envelope fail on long messages?

The unfrozen control failed 15 of 50 calls in the 250+ band, every one an
`XMLParsingError`. The acceptance bar for phase 0 is bringing that rate down on
the same rows, and nothing can be fixed before the mechanism is known.

RULED OUT ALREADY, by arithmetic rather than by running anything: context-window
truncation. The prompt template is 742 tokens and the largest 250+ prompt is
2,078; with `max_tokens` 4096 against `max_model_len` 8192, zero of the 111
long bodies can overflow. So these responses are malformed, not cut short.

WHAT THIS DOES. Re-runs the long band, and on every parse failure captures the
model's RAW response off `XMLParsingError.xml_content`. That field exists and
carries the text the parser choked on, which is the one artefact the earlier run
did not keep and therefore could not diagnose.

🔴 OUTPUT IS UNTRACKED, DELIBERATELY. Raw responses are rewrites of real DM
bodies — the same disclosure reason the corpus itself is out of git (real
traffic, a live email address, named colleagues). Bodies land in `src/tmp/`;
only the classification counts are safe to commit.

Usage:  python diagnose_envelope.py [N]        # default 20 long messages
"""

import json
import pathlib
import re
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_compression.freeze import freeze
from cosa.agents.dm_compression.compressor import DmCompressionAgent
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
OUT_DIR  = pathlib.Path( "src/tmp/arm4/envelope-diagnosis" )
N        = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 20


def classify( raw ):
    """
    Name the shape of a malformed response.

    Requires:
        - raw is the text the parser rejected, or None when it was not captured

    Ensures:
        - returns a short kebab-case tag naming the failure shape
        - "unknown" rather than a guess when nothing matches

    Raises:
        - nothing
    """
    if raw is None:            return "no-raw-captured"
    if not raw.strip():        return "empty-response"

    has_open  = "<response>"  in raw
    has_close = "</response>" in raw

    if not has_open and not has_close:      return "no-envelope-at-all"
    if has_open and not has_close:          return "unterminated-envelope"
    if raw.count( "<![CDATA[" ) != raw.count( "]]>" ):
                                            return "unbalanced-cdata"
    if "]]>" in raw and raw.index( "]]>" ) < raw.index( "<![CDATA[" ):
                                            return "cdata-close-before-open"
    if not re.search( r"<compressed>", raw ): return "missing-compressed-tag"
    if raw.count( "<compressed>" ) > 1:      return "duplicate-compressed-tag"
    return "unknown"


def main():
    bodies = []
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        if record.get( "body" ): bodies.append( record[ "body" ] )

    long_bodies = [ b for b in bodies if len( b.split() ) >= 250 ]
    stride      = max( 1, len( long_bodies ) // N )
    sample      = long_bodies[ ::stride ][ :N ]

    print( f"{len(long_bodies)} bodies in the 250+ band · probing {len(sample)}", flush=True )
    print( f"raw failures → {OUT_DIR} (untracked)", flush=True )
    print( flush=True )

    OUT_DIR.mkdir( parents=True, exist_ok=True )

    counts  = {}
    results = []

    for i, body in enumerate( sample, 1 ):
        frozen = freeze( body )

        # Both arms, because the failure was 15/50 unfrozen against 2/50 frozen.
        # A fix aimed at the wrong arm would look like it worked.
        for arm, text in [ ( "frozen", frozen.frozen_text ), ( "unfrozen", body ) ]:
            started = time.time()
            tag, raw = "ok", None
            try:
                agent    = DmCompressionAgent( frozen_text=text )
                response = agent.run_prompt()
                if not ( isinstance( response, dict ) and response.get( "compressed" ) ):
                    tag = "parsed-but-empty"
            except XMLParsingError as e:
                raw = getattr( e, "xml_content", None )
                tag = classify( raw )
            except Exception as e:
                tag = f"other:{type( e ).__name__}"

            counts[ ( arm, tag ) ] = counts.get( ( arm, tag ), 0 ) + 1
            results.append( { "i": i, "arm": arm, "tag": tag,
                              "in_words": len( body.split() ),
                              "latency": round( time.time() - started, 2 ) } )

            if raw is not None:
                ( OUT_DIR / f"{i:03d}-{arm}-{tag}.txt" ).write_text( raw )

            print( f"  [{i:>3}/{len(sample)}] {arm:<9} {tag}", flush=True )

    print()
    print( "=" * 70 )
    for arm in [ "frozen", "unfrozen" ]:
        rows = [ r for r in results if r[ "arm" ] == arm ]
        bad  = [ r for r in rows if r[ "tag" ] != "ok" ]
        print( f"{arm:<9} {len(bad)}/{len(rows)} failed" )
        for ( a, tag ), n in sorted( counts.items(), key=lambda kv: -kv[1] ):
            if a == arm and tag != "ok": print( f"    {tag:<28} {n}" )

    ( OUT_DIR / "summary.json" ).write_text( json.dumps( results, indent=2 ) )
    print()
    print( f"raw bodies + summary → {OUT_DIR}" )


if __name__ == "__main__":
    main()
