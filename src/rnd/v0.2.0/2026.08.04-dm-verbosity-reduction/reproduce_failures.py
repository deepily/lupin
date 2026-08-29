"""
Phase 0 — reproduce the KNOWN failures, on the same rows, and capture what broke.

Supersedes the stride-sampled `diagnose_envelope.py`, which was fishing: it drew
its own sample from the 250+ band and got 8 pairs deep with zero failures. At a
30% base rate that is unremarkable, but it is also unnecessary — we know exactly
which 22 messages failed, keyed by `body_sha`. Reproducing those directly is
both faster and the acceptance bar María set: *measured on the same rows*.

WHY THIS CAN WORK AT ALL: sampling is `temperature 0.0`, so the same prompt must
produce the same output. That makes the reproduction rate itself a finding,
before anything is read:

    all 22 reproduce   → deterministic, tied to specific inputs, diagnosable
    none reproduce     → nondeterministic; a server or sampling story, and no
                         amount of input analysis will ever explain it
    some reproduce     → both, and the split is the thing to look at

TWO HYPOTHESES ON THE TABLE, and the captured text separates them cleanly:

1. **Degenerate repetition into the `max_tokens` ceiling** (María). A response
   cut mid-stream looks exactly like an unterminated envelope. But note the
   arithmetic: the 250+ band's median input is 456 tokens, so reaching 4096
   means emitting ~9× the input on a task that says "make this shorter". That
   is the model failing to STOP, not a cap that is too small — and the fix
   would be a stopping condition, not a bigger cap.
2. **Ordinary malformation** — a mangled tag, an unbalanced CDATA wrapper.

**Captured length tells them apart**: truncation lands near the ceiling and
reads repetitive; malformation is short and mangled.

🔴 UNTRACKED OUTPUT. Raw responses are rewrites of real DM bodies — the same
disclosure reason the corpus is out of git. Bodies go to `src/tmp/`; only the
classification counts are committable.

Usage:  python reproduce_failures.py
"""

import hashlib
import json
import pathlib
import re
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_compression.freeze import freeze
from cosa.agents.dm_compression.compressor import DmCompressionAgent
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
from cosa.agents.llm_client_factory import LlmClientFactory

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
ROWS     = "src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/live-runs/unfrozen-control-50per-band.jsonl"
OUT_DIR  = pathlib.Path( "src/tmp/arm4/failure-reproduction" )
MAX_TOK  = 4096                        # the ceiling under test

try:
    import tiktoken
    _ENC = tiktoken.get_encoding( "o200k_base" )
    def ntok( s ): return len( _ENC.encode( s ) )
except Exception:
    def ntok( s ): return max( 1, round( len( s ) / 4 ) )


def classify( raw ):
    """
    Name the shape of a malformed response.

    Requires:
        - raw is the text the parser rejected, or None when none was captured

    Ensures:
        - returns a short kebab-case tag
        - "unknown-shape" rather than a guess when nothing matches

    Raises:
        - nothing
    """
    if raw is None:     return "no-raw-captured"
    if not raw.strip(): return "empty-response"

    has_open  = "<response>"  in raw
    has_close = "</response>" in raw

    if not has_open and not has_close:               return "no-envelope-at-all"
    if has_open and not has_close:                   return "unterminated-envelope"
    if raw.count( "<![CDATA[" ) != raw.count( "]]>" ): return "unbalanced-cdata"
    if not re.search( r"<compressed>", raw ):        return "missing-compressed-tag"
    if raw.count( "<compressed>" ) > 1:              return "duplicate-compressed-tag"
    return "unknown-shape"


def repetition_score( raw ):
    """
    Fraction of the text made of lines that already appeared. Rough on purpose.

    Requires:
        - raw is a string

    Ensures:
        - returns 0.0 when nothing repeats, approaching 1.0 when nearly all does
        - a degenerate loop scores high; ordinary prose scores near zero

    Raises:
        - nothing
    """
    lines = [ ln.strip() for ln in raw.splitlines() if ln.strip() ]
    if len( lines ) < 2: return 0.0
    return 1.0 - ( len( set( lines ) ) / len( lines ) )


def main():
    rows   = [ json.loads( l ) for l in open( ROWS ) if l.strip() ]
    wanted = { r[ "body_sha" ]: r for r in rows
               if not r[ "bypassed" ] and r.get( "unfrozen_err" ) }

    bodies = {}
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        body = record.get( "body" )
        if not body: continue
        sha = hashlib.sha256( body.encode( "utf-8" ) ).hexdigest()[ :16 ]
        if sha in wanted: bodies[ sha ] = body

    print( f"{len(wanted)} known unfrozen failures · {len(bodies)} bodies recovered from the corpus",
           flush=True )
    if len( bodies ) != len( wanted ):
        print( f"⚠️ {len(wanted) - len(bodies)} could not be recovered by hash — "
               f"do not read the reproduction rate as complete", flush=True )
    print( flush=True )

    OUT_DIR.mkdir( parents=True, exist_ok=True )
    results = []

    for i, ( sha, body ) in enumerate( sorted( bodies.items() ), 1 ):
        row = wanted[ sha ]
        started = time.time()
        tag, raw = "REPRODUCED-NOT", None

        # 🔴 CAPTURE AT THE CLIENT, NOT AT THE EXCEPTION.
        #
        # The first version of this script read the raw text off
        # `XMLParsingError.xml_content`. That field is `xml_content[:200] +
        # "..."` (util_xml_pydantic.py:69) — the exception truncates its own
        # copy. Every capture came back at exactly 203 characters, every
        # response therefore looked unterminated, and the classifier was
        # naming the cut this harness had made. Uniform length across every row
        # is what gave it away; malformed output does not arrive all one size.
        #
        # `AgentBase.run_prompt` does `llm.run( self.prompt )` and parses the
        # result (agent_base.py:306). Splitting those two steps here is the
        # same shipping path with the raw string kept — no truncation anywhere.
        try:
            agent  = DmCompressionAgent( frozen_text=body )
            client = LlmClientFactory().get_client( agent.model_name, debug=False, verbose=False )
            raw    = client.run( agent.prompt )
        except Exception as e:
            results.append( { "body_sha": sha, "band": row[ "band" ],
                              "in_tok": row[ "unfrozen_in_tok" ],
                              "tag": f"call-failed:{type( e ).__name__}",
                              "reproduced": True,
                              "latency": round( time.time() - started, 2 ) } )
            print( f"  [{i:>2}/{len(bodies)}] {row['band']:<8} call failed: {type( e ).__name__}",
                   flush=True )
            continue

        # Now parse exactly as the agent would, and see whether it still breaks.
        try:
            agent._update_response_dictionary( raw )
            tag = "parsed-fine-now"
        except XMLParsingError:
            tag = classify( raw )
        except Exception as e:
            tag = f"other:{type( e ).__name__}"

        entry = {
            "body_sha"  : sha,
            "band"      : row[ "band" ],
            "in_tok"    : row[ "unfrozen_in_tok" ],
            "tag"       : tag,
            # The failure reproduced iff parsing broke again on the same input.
            "reproduced": tag != "parsed-fine-now",
            "raw_tok"   : ntok( raw ),
            "raw_chars" : len( raw ),
            "at_ceiling": ntok( raw ) >= MAX_TOK * 0.95,
            "repetition": round( repetition_score( raw ), 3 ),
            "latency"   : round( time.time() - started, 2 ),
        }
        # Every raw response is kept, not only the broken ones — a passing
        # response is the control that says what a healthy one looks like.
        ( OUT_DIR / f"{sha}-{tag}.txt" ).write_text( raw )

        results.append( entry )
        print( f"  [{i:>2}/{len(bodies)}] {row['band']:<8} in {row['unfrozen_in_tok']:>4} tok  "
               f"{tag:<24}  raw {entry['raw_tok']:>5} tok  rep {entry['repetition']:.0%}",
               flush=True )

    ( OUT_DIR / "summary.json" ).write_text( json.dumps( results, indent=2 ) )

    print()
    print( "=" * 74 )
    repro = [ r for r in results if r[ "reproduced" ] ]
    print( f"reproduced {len(repro)}/{len(results)} at temperature 0" )
    if not repro:
        print( "  ⇒ NONDETERMINISTIC. No input analysis can explain these; it is a "
               "server or sampling story." )
    elif len( repro ) == len( results ):
        print( "  ⇒ DETERMINISTIC. Tied to specific inputs, and diagnosable." )
    else:
        print( "  ⇒ MIXED. Both mechanisms are present; the split is the finding." )
    print()

    tags = {}
    for r in results: tags[ r[ "tag" ] ] = tags.get( r[ "tag" ], 0 ) + 1
    for tag, n in sorted( tags.items(), key=lambda kv: -kv[ 1 ] ):
        print( f"  {tag:<26} {n}" )
    print()

    capped = [ r for r in results if r.get( "at_ceiling" ) ]
    print( f"at the {MAX_TOK}-token ceiling: {len(capped)}/{len(repro)} reproduced failures" )
    if capped:
        rep = sum( r[ "repetition" ] for r in capped ) / len( capped )
        print( f"  mean repeated-line fraction among them: {rep:.0%}" )
        print( f"  ⇒ truncation. The defect is the model not STOPPING; a bigger cap "
               f"buys a longer loop, not a parse." )
    elif repro:
        print( f"  ⇒ NOT truncation. These are malformed, not cut off — "
               f"María's ceiling hypothesis is falsified on these rows." )

    print()
    print( f"raw responses + summary → {OUT_DIR} (untracked)" )


if __name__ == "__main__":
    main()
