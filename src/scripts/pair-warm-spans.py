#!/usr/bin/env python3
"""
Pair v1-WARM against v2-WARM per utterance, by category and pooled (row d8d019f6).

WHY THIS EXISTS SEPARATELY FROM paired_eval: paired_eval consumes two finished arm
artifacts. This reads the spans that are ALREADY ON DISK mid-run — v1's artifact plus the
v2 attempt trail — so a delta can be re-derived without spending another ~70 minutes of
live traffic (Mr Radio, 2026-08-20). It is a RE-DERIVATION TOOL, not a second gate.

🔴 THE THREE THINGS IT REFUSES TO HIDE, each because hiding it produced a wrong answer
   earlier tonight:

   1. WARM vs WARM ONLY. v1's artifact carries its warm pass; v2's trail carries both
      passes in order. Pairing v1-warm against v2-COLD gave a −11.2 s delta that meant
      nothing, because the two arms were at different points in their own warm-up. The
      pass split is computed here, not assumed.

      🔴 AND IT SPLITS ON THE ARM'S OWN `seq`, NOT ON LIST POSITION. The first version of
      this file sliced the OK records positionally, which is wrong the moment a pass
      contains a failure: failures are filtered out before the slice, so every ok record
      after the first failure shifts one place earlier and some WARM records get labelled
      COLD. v2 happened to have zero failures tonight, which is exactly the kind of luck
      that hides a defect until the run that matters. `seq` is emitted by the arm, runs
      1..2N monotonically across both passes, and does not move when records are dropped.

   2. BY CATEGORY AND POOLED. A pooled median hides a category that behaves completely
      differently — on 2026-08-20 the pooled figure was −11.2 s while `todo` alone was
      −59.9 s. The pooled number is the headline; the per-category table is what makes it
      readable.

   3. THE SURVIVING COUNT, STATED. The two arms do not score `ok` at the same bar
      (v2_eval.py:837 is status==200; v1_eval_arm.py:314 requires an observed completion),
      so the utterances that survive into a pairing are a SELECTED set, not the sample.
      Printing how many survive out of how many were sampled is the only honest way to
      quote the delta at all.

    python3 src/scripts/pair-warm-spans.py [--since <epoch>] [--n-per-command 20]
"""

import argparse, collections, json, os, statistics, sys


def v2_spans_by_pass( trail_path, since, n_per_pass ):
    """
    Split v2's attempt trail into its cold and warm passes, in file order.

    Requires:
        - trail_path is the ask-attempts jsonl; since bounds it to one run
        - n_per_pass is the utterance count of ONE pass (n_per_command * commands)

    Ensures:
        - returns (cold, warm) dicts of utterance -> client_span_ms over ok records only
        - the split is on the arm's own `seq` (1..2N, monotonic across both passes), so a
          filtered-out failure cannot shift a warm record into the cold bucket
        - a record with no usable `seq` is DROPPED, not guessed into a bucket
        - a run that has not reached its warm pass returns an empty warm dict rather than
          silently borrowing cold records
    """
    cold, warm = {}, {}
    if not os.path.exists( trail_path ): return cold, warm
    with open( trail_path ) as fh:
        for line in fh:
            try: d = json.loads( line )
            except Exception: continue
            if d.get( "phase" ) != "end": continue
            try:
                if float( d.get( "wall_ts", 0 ) ) < since: continue
            except Exception: continue
            if str( d.get( "ok" ) ).lower() not in ( "true", "1" ): continue
            if d.get( "client_span_ms" ) is None: continue
            try:
                seq = int( d[ "seq" ] )
            except ( KeyError, TypeError, ValueError ):
                # No seq ⇒ the position this record belongs to is UNKNOWABLE. Guessing is
                # what the positional version did; dropping it is honest and the count of
                # survivors (which the report prints) goes down visibly.
                continue
            target = cold if seq <= n_per_pass else warm
            target[ d[ "utterance" ] ] = float( d[ "client_span_ms" ] )
    return cold, warm


def pair( v1_spans, v2_spans ):
    """Utterances present in BOTH arms, sorted for stable output."""
    return sorted( set( v1_spans ) & set( v2_spans ) )


def summarise( v1_spans, v2_spans, keys ):
    """
    Ensures:
        - returns None for an empty pairing rather than a median over nothing
        - the delta is the median of PER-UTTERANCE differences, never a difference of
          medians: the two are not the same and only the first is a paired statistic
    """
    if not keys: return None
    deltas = [ v1_spans[ k ] - v2_spans[ k ] for k in keys ]
    return {
        "n"        : len( keys ),
        "v1_median": statistics.median( [ v1_spans[ k ] for k in keys ] ),
        "v2_median": statistics.median( [ v2_spans[ k ] for k in keys ] ),
        "delta"    : statistics.median( deltas ),
    }


def render( v1_spans, v2_warm, mapping, n_per_command, sampled_commands, v2_cold=None ):
    """Render the pooled + per-category table with the surviving counts stated.

    Ensures:
        - a refusal SAYS WHY IT IS ZERO. "0 shared" on its own reads as a broken tool,
          while 49 shared from the WRONG pairing reads as a healthy sample — the numbers
          give the opposite impression to the truth, so the refusal must distinguish
          "the run has not got there yet" from "something is broken".
    """
    lines = [ "# v1-WARM vs v2-WARM paired spans", "" ]
    keys  = pair( v1_spans, v2_warm )
    if not keys:
        lines.append( "**NO WARM-WARM PAIRING AVAILABLE — no latency statement is possible.**" )
        lines.append( "" )
        n_cold = len( v2_cold ) if v2_cold is not None else None
        if n_cold and not v2_warm:
            per_pass = n_per_command * len( sampled_commands ) if sampled_commands else "?"
            lines.append( f"**This is the run not being ready, NOT a broken tool.** The v2 arm has "
                          f"{n_cold} COLD spans and 0 WARM: it is still inside its first pass of "
                          f"{per_pass}. v1 has {len( v1_spans )} warm spans waiting for it." )
        elif not v1_spans:
            lines.append( "The v1 arm has no spans at all — check that its artifact is the one you meant." )
        else:
            lines.append( f"v1 has {len( v1_spans )} warm spans and v2 has {len( v2_warm )}, but they "
                          f"share no utterance. That is NOT a not-ready run — the two arms measured "
                          f"different utterances, which is a provenance problem, not a timing one." )
        lines.append( "" )
        lines.append( "⚠️ Do not reach for the cold pass to fill the gap. A cold-warm pairing yields a "
                      "plausible-looking sample and a meaningless number: on 2026-08-20 it gave 49 "
                      "shared utterances and a −11.2 s \"delta\" that compared two arms at different "
                      "points in their own warm-up." )
        return "\n".join( lines ), False

    sampled = n_per_command * len( sampled_commands ) if sampled_commands else None
    lines.append( f"**Surviving into the warm-warm pairing: {len( keys )}"
                  + ( f" of {sampled} sampled**" if sampled else "**" ) )
    lines.append( "" )
    lines.append( "⚠️ Survivors are a SELECTED set, not the sample: the arms do not score `ok` at "
                  "the same bar (v2 = HTTP 200; v1 = observed terminal completion), so an utterance "
                  "can drop out of one arm for reasons unrelated to how fast it was." )
    lines.append( "" )
    lines.append( "| scope | n | v1 median | v2 median | paired median Δ (v1−v2) | faster |" )
    lines.append( "|---|---:|---:|---:|---:|---|" )

    def row( label, ks ):
        s = summarise( v1_spans, v2_warm, ks )
        if s is None:
            lines.append( f"| {label} | 0 | — | — | — | — |" ); return
        faster = "v2" if s[ "delta" ] > 0 else ( "v1" if s[ "delta" ] < 0 else "tie" )
        lines.append( f"| {label} | {s['n']} | {s['v1_median']:.0f} ms | {s['v2_median']:.0f} ms | "
                      f"{s['delta']:+.0f} ms | **{faster}** |" )

    row( "**POOLED**", keys )
    by = collections.defaultdict( list )
    for k in keys: by[ mapping.get( k, "(unmapped)" ) ].append( k )
    for cmd in sorted( by ): row( cmd, by[ cmd ] )

    lines.append( "" )
    lines.append( "A pooled median hides a category that behaves differently — report both." )
    return "\n".join( lines ), True


def main( argv=None ):
    ap = argparse.ArgumentParser()
    ap.add_argument( "--v1-artifact",   default="io/v2-flow/paired-run-latest/v1-arm-artifact.json" )
    ap.add_argument( "--trail",         default="io/v2-flow/ask-attempts.jsonl" )
    ap.add_argument( "--since",         type=float, default=0.0 )
    ap.add_argument( "--n-per-command", type=int,   default=int( os.environ.get( "LUPIN_PAIRED_N", "20" ) ) )
    ap.add_argument( "--corpus",        default="simple" )
    args = ap.parse_args( argv )

    if not os.path.exists( args.v1_artifact ):
        print( f"**NO v1 ARTIFACT** at {args.v1_artifact} — nothing to pair." ); return 1

    import v2_eval
    pairs    = v2_eval.load_corpus( args.corpus )
    mapping  = { utterance: command for utterance, command in pairs }
    commands = sorted( set( mapping.values() ) )

    v1_spans = json.load( open( args.v1_artifact ) )[ "metrics" ][ "spans_by_utterance" ]
    _cold, warm = v2_spans_by_pass( args.trail, args.since, args.n_per_command * len( commands ) )

    text, ok = render( v1_spans, warm, mapping, args.n_per_command, commands, v2_cold=_cold )
    print( text )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit( main() )
