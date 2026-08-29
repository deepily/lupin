"""
Phase 1 sample harness — what do the tutor's rewrites actually LOOK like?

    python tutor_sample_run.py [N_PER_BAND]      # default 20 (→ ~40 messages)

Rick's instruction, and the reason this runs before anything else is built:

    "In our first phase we want to see how well and what the output looks like
     when we take long examples and chop them down to 3 most important
     sentences. We will then, AFTER we approve of the outputs, double back and
     update the workflow."

So the deliverable is a DOCUMENT A HUMAN READS, not a metric. Every number this
prints is secondary to the side-by-side text.

WHERE THE OUTPUT GOES — outside the repo, on Rick's ruling: "No point in keeping
it for posterity's sake, it's just an intermediary step." It also carries real DM
bodies, which is the same disclosure reason the corpus is not in git. Default
destination is /tmp; only counts and the verdict are ever committed.

FOUR RULES THIS HARNESS FOLLOWS, each one a way a sample document can lie:

1. **The sample is picked by stride, never by hand.** A set chosen for good
   examples measures the chooser, not the tutor.
2. **Every rewrite in the chosen set appears** — including the bad ones, the
   failures, and the ones that came back unchanged. If a rewrite is
   embarrassing, that is the finding.
3. **Failures are shown as failures**, in place, not skipped over. A document
   that silently drops the messages the model could not handle is exactly the
   biased sample §6 of the plan warns about.
4. **The observers report, they do not gate.** Nothing here decides whether a
   rewrite is good — that judgement is Rick's, and the harness exists to put the
   evidence in front of him.

WHAT IT MEASURES BESIDE THE TEXT — the checks a reader cannot do by eye across 40
messages: whether the output really is ≤3 claims, which literals survived, which
were dropped, and whether any literal in the output was never in the input (the
closest automatable proxy for an ALTERED value — a real alteration and an
invention look identical from here).

⚠️ NOT MEASURED, and it is the failure that matters most: relocation, and
negation/ownership/status drift. `not reproducible` → `reproducible` passes every
check in this file. That is why the document exists and why a human reads it.
"""

import hashlib
import json
import pathlib
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_tutor.sentences import count_sentences, over_limit
from cosa.agents.dm_compression.freeze import extract_spans, resolve_spans

SNAPSHOT     = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
CORPUS_SHA16 = "94b1c192bf777e03"
N_PER_BAND   = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 20
OUT_PATH     = pathlib.Path( f"/tmp/dm-tutor-samples-{time.strftime('%Y.%m.%d-%H%M')}.md" )

# Long bands only. This is where the tutor earns or loses its case: 42% of 250+
# messages carry a table, and the two long bands hold most of the token mass.
BANDS = [ "150-250", "250+" ]


def band_of( words ):
    """
    Classify by word count — the same boundaries every prior arm-4 run used.

    Requires:
        - words is a non-negative integer

    Ensures:
        - returns one of "<80", "80-150", "150-250", "250+"

    Raises:
        - nothing
    """
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    return "250+"


def verify_corpus():
    """
    Refuse to run against a corpus that is not the pinned one.

    Requires:
        - SNAPSHOT names a readable JSONL file

    Ensures:
        - returns the file's sha256 when its first 16 hex chars match CORPUS_SHA16

    Raises:
        - SystemExit naming both digests on a mismatch, or the path when missing
    """
    path = pathlib.Path( SNAPSHOT )
    if not path.exists():
        sys.exit( f"corpus missing: {SNAPSHOT} — see CORPUS-MANIFEST.md (deliberately not in git)" )

    digest = hashlib.sha256()
    with open( path, "rb" ) as handle:
        for chunk in iter( lambda: handle.read( 1 << 20 ), b"" ): digest.update( chunk )

    actual = digest.hexdigest()
    if actual[ :16 ] != CORPUS_SHA16:
        sys.exit( f"corpus sha256 MISMATCH\n  expected {CORPUS_SHA16}…\n  actual   {actual[:16]}…\n"
                  f"The corpus has drifted. Numbers from a drifted corpus cannot be compared "
                  f"across runs — see CORPUS-MANIFEST.md." )
    return actual


# The tutor's own appended invitation. It is boilerplate this harness adds to
# every delivered rewrite, so anything it contributes is an artefact of the
# instrument, not of the model — see _strip_ps.
_CANNED_PS = "P.S. Need more detail? Ask me *one* question only!"


def _strip_ps( text ):
    """
    Remove the tutor's canned P.S. before any literal is counted.

    Requires:
        - text is a string

    Ensures:
        - returns text with a trailing canned P.S. removed, else text unchanged

    Notes:
        Without this, `P.S` is extracted as a literal from every rewrite and
        never from any original, so the "not in original" column reads 100%
        contaminated on all delivered rows — the instrument reporting its own
        boilerplate as damage. Mr Radio caught it in the first full run.

    Raises:
        - nothing
    """
    index = text.rfind( _CANNED_PS )
    return text[ :index ].rstrip() if index != -1 else text


def literals_of( text ):
    """
    Every literal the freeze protocol recognises in a body, across ALL classes.

    Requires:
        - text is a string

    Ensures:
        - returns a set of the exact substrings, HARD and SOFT and VERIFY alike
        - the tutor's canned P.S. contributes nothing

    Notes:
        The tier split answers "is a placeholder cheaper than this literal?" —
        a substitution question a lossy tutor never asks. Checking in place costs
        nothing for any class, so nothing is excluded here. (An earlier draft of
        the plan restricted this to the VERIFY tier, which would have left shas,
        paths and file:line refs unprotected — the one thing Rick asked for, and
        the same hole the tutor's own gate turned out to have.)

    Raises:
        - nothing
    """
    text  = _strip_ps( text )
    spans = resolve_spans( extract_spans( text ) )
    return { text[ s.start : s.end ] for s in spans }


def observe( original, rewrite ):
    """
    Report what the rewrite did to the original's literals. Gates nothing.

    Requires:
        - original and rewrite are strings

    Ensures:
        - returns a dict with kept / dropped / unrecognized literal sets
        - "unrecognized" holds literals present in the rewrite but absent from
          the original — the closest automatable proxy for an ALTERED value,
          since an alteration and an invention are indistinguishable from here

    Raises:
        - nothing
    """
    before, after = literals_of( original ), literals_of( rewrite )
    return {
        "kept"         : sorted( lit for lit in before if lit in rewrite ),
        "dropped"      : sorted( lit for lit in before if lit not in rewrite ),
        "unrecognized" : sorted( after - before ),
    }


def load_rewriter():
    """
    Bind the tutor's rewrite function, or explain precisely what is missing.

    Requires:
        - nothing

    Ensures:
        - returns a callable taking a body and returning ( rewrite, error )

    Raises:
        - SystemExit with the module path when the tutor is not yet built
    """
    try:
        from cosa.agents.dm_tutor.tutor import rewrite_to_form
    except ImportError as e:
        sys.exit( f"tutor not available yet: {e}\n"
                  f"Expected `rewrite_to_form( body ) -> ( str|None, str|None, str|None )` in "
                  f"cosa/agents/dm_tutor/tutor.py. The harness is ready; the rewriter is not." )
    return rewrite_to_form


def select( bodies ):
    """
    Stride-sample the long bands.

    Requires:
        - bodies is a list of message body strings

    Ensures:
        - returns a list of ( band, body ), at most N_PER_BAND per long band
        - selection is deterministic and independent of content, so the set
          cannot have been chosen to flatter the result

    Raises:
        - nothing
    """
    by_band = {}
    for body in bodies: by_band.setdefault( band_of( len( body.split() ) ), [] ).append( body )

    sample = []
    for band in BANDS:
        pool   = by_band.get( band, [] )
        stride = max( 1, len( pool ) // N_PER_BAND )
        sample += [ ( band, body ) for body in pool[ ::stride ][ :N_PER_BAND ] ]
    return sample


def _variant_stamp():
    """Name the ask-placement variant these samples were produced with."""
    from cosa.agents.dm_tutor import tutor
    import inspect
    return inspect.signature( tutor.rewrite_to_form ).parameters[ "ask_outside" ].default


def _prompt_stamp():
    """sha256[:12] of the assembled prompt, so wording drift is visible too."""
    import hashlib
    from cosa.agents.dm_tutor.tutor import build_prompt
    return hashlib.sha256( build_prompt( "STAMP PROBE — asks nothing." ).encode() ).hexdigest()[ :12 ]


def render( results, corpus_sha, elapsed ):
    """
    Write the side-by-side document Rick reads.

    Requires:
        - results is the list of per-message dicts built by main()

    Ensures:
        - every sampled message appears, including failures and no-ops
        - the summary sits at the TOP, the evidence below it

    Raises:
        - nothing
    """
    ok      = [ r for r in results if r[ "rewrite" ] ]
    failed  = [ r for r in results if not r[ "rewrite" ] ]
    overrun = [ r for r in ok if r[ "out_sentences" ] > 3 ]
    damaged = [ r for r in ok if r[ "observed" ][ "unrecognized" ] ]

    lines = [
        "# DM formatting tutor — phase 1 samples",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M')} · **wall clock** {elapsed/60:.1f} min",
        # 🔴 STAMP THE CONFIG. Without it, a reader a month from now cannot tell
        # whether these pairs came from the recommended variant or from the
        # contradictory-prompt run that preceded it — the same defect as every
        # other capture failure today, aimed at the future reader instead of at
        # us. (María, 2026-08-11.)
        f"**Variant**: `{_variant_stamp()}` · **prompt sha256**: `{_prompt_stamp()}`",
        f"**Corpus**: pinned, sha256 `{corpus_sha[:16]}…` · **sampled**: {len(results)} long messages "
        f"({N_PER_BAND}/band, stride-picked)",
        "",
        "> **This document lives outside the repo on purpose.** It carries real DM bodies, and it is",
        "> an intermediate artefact, not a record. Only the counts below and Rick's verdict are committed.",
        "",
        "## What to judge",
        "",
        "The numbers are secondary. Reading the pairs, ask:",
        "",
        "1. Is the **headline the verdict**, or just a topic label?",
        "2. Did the two supporting sentences keep what **mattered**, or what came **first**?",
        "3. Is anything lost that the recipient **could not recover with one question**?",
        "4. Did **negation, ownership, status and conditionality** survive? *(`not reproducible` →",
        "   `reproducible` is the failure that matters most — **no check in this harness can see it**.)*",
        "5. Does it read like a **human colleague** wrote it?",
        "",
        "## Summary",
        "",
        "| | |",
        "|---|---|",
        f"| rewritten | **{len(ok)}/{len(results)}** |",
        f"| failed outright | **{len(failed)}** |",
        f"| still over 3 sentences | **{len(overrun)}** |",
        f"| carrying a literal not in the original | **{len(damaged)}** |",
        "",
        "⚠️ **Relocation and meaning drift are NOT in that table** — nothing automated here can see",
        "them. That is what the reading is for.",
        "",
        "---",
        "",
    ]

    for i, r in enumerate( results, 1 ):
        lines += [ f"## {i}. {r['band']} · {r['in_sentences']} claims → "
                   f"{r['out_sentences'] if r['rewrite'] else '—'} · `{r['body_sha']}`", "" ]

        if not r[ "rewrite" ]:
            lines += [ f"🔴 **NO REWRITE** — {r['error']}", "",
                       "**Original**", "", "```", r[ "original" ], "```", "", "---", "" ]
            continue

        obs = r[ "observed" ]
        lines += [
            "**Original**", "", "```", r[ "original" ], "```", "",
            "**Rewrite**", "", "```", r[ "rewrite" ], "```", "",
            f"*literals — kept {len(obs['kept'])} · dropped {len(obs['dropped'])}"
            + ( f" · ⚠️ NOT IN ORIGINAL: {', '.join('`'+l+'`' for l in obs['unrecognized'])}"
                if obs[ "unrecognized" ] else "" ) + "*",
            "",
        ]
        if obs[ "dropped" ]:
            lines += [ f"*dropped: {', '.join( '`'+l+'`' for l in obs['dropped'][:12] )}"
                       + ( " …" if len( obs[ "dropped" ] ) > 12 else "" ) + "*", "" ]
        lines += [ "---", "" ]

    OUT_PATH.write_text( "\n".join( lines ) )
    return ok, failed, overrun, damaged


def main():
    corpus_sha = verify_corpus()
    print( f"corpus sha256 verified: {corpus_sha[:16]}…", flush=True )

    rewrite_to_form = load_rewriter()

    bodies = []
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        if record.get( "body" ): bodies.append( record[ "body" ] )

    sample = select( bodies )
    print( f"corpus {len(bodies)} bodies · sampling {N_PER_BAND}/band over {BANDS} · "
           f"{len(sample)} messages\n", flush=True )

    results, started = [], time.time()

    for i, ( band, body ) in enumerate( sample, 1 ):
        # 3-tuple: the third value is the model's text even when the gate
        # rejects it — phase 1 is Rick judging what rewrites LOOK like, so a
        # rejection that shows him nothing defeats the phase.
        rewrite, error, attempted = rewrite_to_form( body )

        row = {
            "band"          : band,
            "body_sha"      : hashlib.sha256( body.encode( "utf-8" ) ).hexdigest()[ :16 ],
            "original"      : body,
            "rewrite"       : rewrite,
            "attempted"     : attempted,
            "error"         : error,
            "in_sentences"  : count_sentences( body ),
            "out_sentences" : count_sentences( rewrite ) if rewrite else 0,
            "observed"      : observe( body, rewrite ) if rewrite else None,
        }
        results.append( row )

        mark = "✓" if rewrite else "🔴"
        print( f"  [{i:>3}/{len(sample)}] {mark} {band:<8} "
               f"{row['in_sentences']:>3} → {row['out_sentences'] if rewrite else '—':>3} claims"
               f"{'' if rewrite else '  ' + str(error)[:50]}", flush=True )

    elapsed = time.time() - started
    ok, failed, overrun, damaged = render( results, corpus_sha, elapsed )

    print()
    print( "=" * 78 )
    print( f"document → {OUT_PATH}" )
    print( f"rewritten {len(ok)}/{len(results)} · failed {len(failed)} · "
           f"over 3 sentences {len(overrun)} · literal not in original {len(damaged)}" )
    print()
    print( "The numbers are secondary. The document is the deliverable — read the pairs." )


if __name__ == "__main__":
    main()
