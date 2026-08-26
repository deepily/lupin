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


def provenance_block( v1, v2 ):
    """
    The provenance header — WHICH v1, WHICH v2, and under what sampling.

    🔴 WHY THIS EXISTS (row 224fbb68, Krishna 2026-08-25). This report carried NO
    provenance at all. Counted across the full rendered output, each of these
    appeared exactly ZERO times: the v1 sha, the v2 sha, `git_sha`, `written_by`,
    `seed`, `n_per_command`. The stamp lives in the JSON and was dropped at exactly
    the point a human reads it.

    That is not cosmetic. Mr Radio's 08-21 ruling on row 647f3733 requires, verbatim:
    "REPORT MUST SAY: referent sha 15536409, contains bf77852b, pre-drift alternative
    b0735467 remains available by pinning; whether the referent choice moves any
    headline number is UNMEASURED." The renderer could not satisfy that ruling — it
    printed none of it. And the 08-14 ruling's whole premise is that drift is a
    LABELLING problem: "a measurement stamped with the sha it was taken against is
    comparable forever." An unstamped report throws that away.

    Requires:
        - v1, v2 are arm artifacts or None

    Ensures:
        - returns a list of markdown lines, always non-empty
        - names each arm's git_sha, or says plainly that the arm wrote none
        - flags a v1 sha that is not the pinned referent, rather than printing it flat
        - flags `written_by == "unknown-caller"`, which is the backstop that row
          224fbb68 found had never once fired
        - flags differing sample_signatures — two arms sampled differently are not a
          paired measurement, whatever the delta says
    """
    from v1_eval_arm import V1_PIN_SHA, V1_PIN_RATIONALE

    def _p( art, key, default="—" ):
        if art is None: return default
        return art.get( "provenance", {} ).get( key, default )

    out = [ "## Provenance", "" ,
            "| field | v1 arm | v2 arm |", "|---|---|---|" ]
    for label, key in ( ( "git_sha", "git_sha" ), ( "corpus", "corpus" ), ( "seed", "seed" ),
                        ( "n_per_command", "n_per_command" ), ( "sampled_n", "sampled_n" ),
                        ( "sample_signature", "sample_signature" ) ):
        a = _p( v1, key ); b = _p( v2, key )
        if key == "sample_signature":
            a = str( a )[ :12 ] if a != "—" else a
            b = str( b )[ :12 ] if b != "—" else b
        out.append( f"| {label} | {a} | {b} |" )
    for label, key in ( ( "written_at", "written_at" ), ( "written_by", "written_by" ) ):
        a = ( v1 or {} ).get( key, "—" ); b = ( v2 or {} ).get( key, "—" )
        out.append( f"| {label} | {a} | {b} |" )
    out.append( "" )

    # The referent, named and judged — the ruling's requirement, derived from the
    # constant rather than hard-coded so it cannot drift away from the arm itself.
    v1_sha = _p( v1, "git_sha" )
    if v1_sha == "—":
        out.append( "🔴 **The v1 arm wrote no git_sha** — this report cannot say which v1 it measured." )
    elif str( v1_sha ).startswith( V1_PIN_SHA ) or str( V1_PIN_SHA ).startswith( str( v1_sha ) ):
        out.append( f"**Referent**: v1 pinned at `{V1_PIN_SHA}` — {V1_PIN_RATIONALE}." )
        out.append( "" )
        out.append( "The pre-drift alternative `b0735467` remains available by pinning; it is "
                    "unrefactored but LEAKY (predates `bf77852b`, the 8aa89f42 cross-user "
                    "fallback_defaults fix). **Whether the referent choice moves any headline "
                    "number here is UNMEASURED.**" )
    else:
        out.append( f"🔴 **REFERENT MISMATCH — this run measured v1 at `{v1_sha}`, but the pin is "
                    f"`{V1_PIN_SHA}`.** Do not compare these numbers to a run taken against the pin." )
        # The pre-drift sha is called out BY NAME only when it is actually the one, so the
        # generic branch does not emit "if b0735467 is b0735467" at a reader.
        if str( v1_sha ).startswith( "b0735467" ):
            out.append( "" )
            out.append( "That sha is the PRE-DRIFT alternative, and it is **LEAKY**: it predates "
                        "`bf77852b`, the 8aa89f42 cross-user `fallback_defaults` fix — a "
                        "SEQUENTIAL-REPLAY CONTAMINANT that corrupts the measurement itself, not "
                        "merely the code under test. Rejected as the referent on row 647f3733." )
    out.append( "" )

    # `unknown-caller` was built as the tell that nothing identified itself as a real
    # run. Row 224fbb68 measured that nothing ever SET the variable it reads, so the
    # tell could never fire. Surfacing it here is what gives it back its meaning.
    for name, art in ( ( "v1", v1 ), ( "v2", v2 ) ):
        if art is not None and art.get( "written_by" ) == "unknown-caller":
            out.append( f"⚠️ **{name} arm `written_by` is `unknown-caller`** — nothing identified "
                        f"itself as a real run. This is either a scaffold/unit-test artifact or a "
                        f"runner that did not inject `LUPIN_TEST_SUITE_JOB_ID`. Do not cite these "
                        f"numbers as a run result until you know which." )
    if any( art is not None and art.get( "written_by" ) == "unknown-caller" for art in ( v1, v2 ) ):
        out.append( "" )

    sig1, sig2 = _p( v1, "sample_signature" ), _p( v2, "sample_signature" )
    if sig1 != "—" and sig2 != "—" and sig1 != sig2:
        out.append( "🔴 **SAMPLE SIGNATURES DIFFER** — the two arms did not draw the same sample, "
                    "so this is not a paired measurement however the delta reads." )
        out.append( "" )

    return out


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

    # --- provenance header -------------------------------------------------------
    out += provenance_block( v1, v2 )

    # --- the median-Δ verdict, from the real gate --------------------------------
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
        out.append( "✅ No category diverged between the arms — neither arm lost ground the other kept." )

    # 🔴 AGREEING IS NOT THE SAME AS BEING SOUND. Two arms can lose the SAME half of the
    # corpus and diverge not at all — the rehearsal that found this rendered a green tick over
    # a pair that kept 53 of 100 with one category gone entirely. Divergence asks "were they
    # scored on the same corpus"; attrition asks "was there enough corpus left to mean
    # anything". A report that answers only the first hands a clean bill to a gutted run.
    worst = 0.0
    for art in ( v1, v2 ):
        rate = ( art or {} ).get( "metrics", {} ).get( "failure_rate" )
        if rate is not None: worst = max( worst, float( rate ) )
    if worst >= 0.20:
        out.append( "" )
        out.append( f"🔴 **HIGH ATTRITION — {worst * 100:.0f}% of attempts produced no usable record.** "
                    f"Whatever the delta says, it was measured over what survived, and what survived "
                    f"is a selected subsample rather than the corpus that was sampled. Say why the "
                    f"attrition happened before quoting the number." )

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
