#!/usr/bin/env python3
"""
Render the full paired-run report from the two arm artifacts (row d8d019f6).

WHY THIS EXISTS: `paired_eval.render_paired_verdict` emits the median-Δ and the medians,
and that is NOT a readable result on its own. Mr Radio's requirement, from María's 08-17
finding (row 2ebe4ccb): a delta ships with the PER-ARM FAILURE RATE and EACH ARM'S
SURVIVING CATEGORY COMPOSITION beside it, or the number cannot be judged.

🔴 THE FAILURE THOSE TWO NUMBERS CATCH, and it is invisible in the delta itself: routing
accuracy and latency are computed over `ok` records only. If one arm loses a whole category
— on 08-17 the mode-switch/routing block went ~94% absent from v2 while v1 kept it — the two
arms are scored on DIFFERENTLY COMPOSED corpora, and the arm that lost its hardest category
scores BETTER. The sample-size floor does not see this: ~300 pairs survive a 32% failure
rate, so the run reads as well-powered while measuring two different things.

⇒ The composition table below is the control. A category where the arms' surviving counts
diverge is flagged, so the delta is either trustworthy on its face or visibly is not.

    python3 src/scripts/render-paired-run-report.py [--dir io/v2-flow/paired-run-latest]
"""

import argparse, json, os, sys

sys.path.insert( 0, os.path.join( os.path.dirname( os.path.abspath( __file__ ) ) ) )


def load_artifacts( art_dir ):
    """
    Load both arm artifacts.

    Ensures:
        - returns (v1, v2); either is None when its file is absent, because the EARLY
          v1-only dump means a v2-arm death leaves v1 alone on disk and that partial
          result is exactly what this tool must still be able to read.
    """
    def _load( name ):
        path = os.path.join( art_dir, f"{name}-arm-artifact.json" )
        if not os.path.exists( path ): return None
        with open( path ) as fh: return json.load( fh )
    return _load( "v1" ), _load( "v2" )


def surviving_by_category( artifact, utterance_to_command ):
    """
    Count an arm's SURVIVING (ok) utterances per corpus command.

    Requires:
        - artifact is an arm artifact carrying metrics.spans_by_utterance
        - utterance_to_command maps an utterance string to its corpus command

    Ensures:
        - returns {command: count} over the utterances that produced a usable span
        - an utterance absent from the corpus map is counted under "(unmapped)" rather
          than dropped, so a mapping gap shows up instead of silently shrinking a category
    """
    spans  = ( artifact or {} ).get( "metrics", {} ).get( "spans_by_utterance", {} ) or {}
    counts = {}
    for utterance in spans:
        command = utterance_to_command.get( utterance, "(unmapped)" )
        counts[ command ] = counts.get( command, 0 ) + 1
    return counts


def composition_table( v1_counts, v2_counts, expected_per_command=None ):
    """
    Render the side-by-side surviving-category table, flagging divergence.

    Ensures:
        - one row per command seen in either arm, sorted for stable output
        - flags a row when the arms' counts differ by more than 20% of the larger,
          which is the shape of "one arm lost this category" rather than ordinary jitter
        - returns (lines, any_flagged) so the caller can headline a compromised run
    """
    commands = sorted( set( v1_counts ) | set( v2_counts ) )
    lines    = [ "| command | v1 survived | v2 survived | note |",
                 "|---|---:|---:|---|" ]
    flagged  = False
    for command in commands:
        a, b  = v1_counts.get( command, 0 ), v2_counts.get( command, 0 )
        larger = max( a, b )
        note   = ""
        if larger and abs( a - b ) > 0.20 * larger:
            note    = f"🔴 DIVERGENT — {'v2' if b < a else 'v1'} lost {abs( a - b )} of {larger}"
            flagged = True
        if expected_per_command and larger < expected_per_command:
            note = ( note + " · " if note else "" ) + f"both below the {expected_per_command} sampled"
        lines.append( f"| {command} | {a} | {b} | {note} |" )
    return lines, flagged


def render( art_dir, corpus_name="simple" ):
    """Build the full report string. Returns (text, ok) — ok is False when a run is unreadable."""
    v1, v2 = load_artifacts( art_dir )
    out    = [ "# Paired run report", "" ]

    if v1 is None and v2 is None:
        return "\n".join( out + [ f"**NO ARTIFACTS** under {art_dir} — nothing was measured." ] ), False
    for name, art in ( ( "v1", v1 ), ( "v2", v2 ) ):
        if art is None:
            out.append( f"⚠️ **The {name} arm wrote no artifact** — the run did not reach it, "
                        f"or it died. No paired number is possible; what follows is one-armed." )
            out.append( "" )

    # --- provenance + the median-Δ verdict, from the real gate --------------------
    if v1 is not None and v2 is not None:
        import paired_eval
        verdict = paired_eval.build_paired_verdict( v1, v2 )
        out.append( paired_eval.render_paired_verdict( verdict ) )
        out.append( "" )

    # --- per-arm failure rate (requirement 2 of 3) --------------------------------
    out.append( "## Per-arm failure rate" )
    out.append( "" )
    out.append( "| arm | attempted | usable | failure rate |" )
    out.append( "|---|---:|---:|---:|" )
    for name, art, ok_key in ( ( "v1", v1, "ok_n" ), ( "v2", v2, "n_ok" ) ):
        if art is None:
            out.append( f"| {name} | — | — | no artifact |" ); continue
        m    = art.get( "metrics", {} )
        rate = m.get( "failure_rate" )
        out.append( f"| {name} | {m.get( 'n', '?' )} | {m.get( ok_key, '?' )} | "
                    f"{'?' if rate is None else f'{rate * 100:.1f}%'} |" )
    out.append( "" )

    # --- surviving category composition (requirement 3 of 3) ----------------------
    out.append( "## Surviving category composition" )
    out.append( "" )
    out.append( "Routing accuracy and latency are computed over usable records only. If one arm "
                "loses a category the other keeps, the arms are scored on differently composed "
                "corpora and the arm that lost its hardest category scores BETTER." )
    out.append( "" )
    try:
        import v2_eval
        pairs   = v2_eval.load_corpus( corpus_name )
        mapping = { utterance: command for utterance, command in pairs }
    except Exception as error:
        out.append( f"⚠️ could not load corpus '{corpus_name}' to map utterances: {error}" )
        return "\n".join( out ), False

    v1_counts = surviving_by_category( v1, mapping )
    v2_counts = surviving_by_category( v2, mapping )
    n_per     = int( os.environ.get( "LUPIN_PAIRED_N", "0" ) ) or None
    table, flagged = composition_table( v1_counts, v2_counts, expected_per_command=n_per )
    out.extend( table )
    out.append( "" )

    # ONE-ARMED RUNS DO NOT GET A DIVERGENCE VERDICT. With an arm absent every row reads
    # "the other arm lost everything", which is true and useless — it describes a missing
    # file, not a lost category. A control that fires on a state it cannot speak to is
    # noise, and noise is how a real flag gets ignored later.
    if v1 is None or v2 is None:
        out.append( "⚠️ **Divergence not assessed** — only one arm reported, so the zero column "
                    "above is an absent artifact rather than a lost category." )
    elif flagged:
        out.append( "🔴 **A DIVERGENT row above means the delta is not readable as a like-for-like "
                    "comparison** — say which category was lost, from which arm, beside the number." )
    else:
        out.append( "✅ No category diverged between the arms — the delta compares like with like." )

    # A category the corpus HAS but neither arm produced is invisible in a table built from
    # what survived. It is also the most complete form of the loss this report looks for.
    missing = sorted( set( mapping.values() ) - set( v1_counts ) - set( v2_counts ) )
    if missing:
        out.append( "" )
        out.append( f"🔴 **Absent from BOTH arms entirely**: {', '.join( missing )} — these "
                    f"categories are in the corpus and produced no usable record on either side." )
    return "\n".join( out ), True


def main( argv=None ):
    ap = argparse.ArgumentParser()
    ap.add_argument( "--dir",    default="io/v2-flow/paired-run-latest" )
    ap.add_argument( "--corpus", default="simple" )
    args = ap.parse_args( argv )
    text, ok = render( args.dir, args.corpus )
    print( text )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit( main() )
