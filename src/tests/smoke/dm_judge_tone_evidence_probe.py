"""
Live probe: does the Tone grade's EVIDENCE quote a phrase, or echo the whole DM back?

THE QUESTION. `dm-quality-judge-v2-tone.txt` asks the model to "quote the specific words
or phrases from the DM that your grade rests on". The Tone result carries that answer
verbatim in its `detail` field, with NOTHING checked against the source text. Observed
2026-08-01 across five real sends (mine and Maria's): four of five came back with the
ENTIRE body quoted instead of a phrase.

WHY IT MATTERS, stated no larger than it is. Evidence that reproduces the whole input
does not corroborate the grade — it is compatible with every grade the model could have
given, so a reader cannot use it to check the score. That makes Tone's detail decorative
rather than load-bearing. It does NOT make the WEIGHT wrong, and this probe does not
claim it does: weight and evidence are measured separately below, precisely so the two
claims stay separable.

CONTRAST WITH DIRECTNESS, which is why this is a Tone-only probe. Directness extracts a
sentence and RECONCILES it against the source, and a reconciliation failure gets its own
non-answer string (`_EXTRACTION_FAILED_DETAIL`). Tone has no equivalent check, so a Tone
evidence field can be anything — including the whole body — and still count as a real
grade everywhere downstream.

TWO HYPOTHESES ALREADY DEAD, recorded so nobody re-runs them:
  - "It differs by SESSION / config." Maria got BOTH behaviours one message apart in one
    seat. Rules out session and config.
  - "It is LENGTH." Her 149-word body echoed whole and her 73-word body quoted fragments,
    but my 70-, 69- and 60-word bodies ALL echoed whole. Three points that close together
    cannot be ordered by length.
This probe therefore measures the RATE and whether it tracks the GRADE, and proposes no
mechanism it has not measured.

🔴 THE HARNESS IS AUDITED BEFORE THE MODEL IS. `_self_test()` runs first and feeds the
   classifier hand-built pairs whose answer is known — a whole echo, a real fragment, a
   near-miss that is 99% of the body, and evidence that is NOT from the body at all. If
   the classifier cannot separate those, the run ABORTS (exit 2) without calling the
   model. A probe that cannot fail on purpose cannot be trusted when it passes.

🔴 A NON-ANSWER IS NOT A MEASUREMENT. Reuses `nonanswer_kind` from the discrimination
   probe rather than re-typing the detail strings, so a fallback ("judge unavailable"),
   an over-length withhold, and the feature-off state can never be counted as evidence
   of anything. A cell that produced zero real Tone grades is reported as measuring
   NOTHING, never as a 0% echo rate.

Usage:  python dm_judge_tone_evidence_probe.py [runs]     (default 3)
Exit:   0 = ran and measured   ·   1 = echo rate at or above the alarm line
        2 = measured nothing, or the harness self-test failed
"""
import os
import re
import sys

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )

from cosa.agents.dm_quality_judge import get_dm_quality_judge

# The four vetted bodies and the non-answer classifier come from the discrimination
# probe — imported, never re-typed. Those bodies are already known to sit under the
# qualitative word limit (past it the judge short-circuits without calling the model)
# and to vary tone and directness independently.
#
# Resolved by THIS FILE's directory, not by cwd. A bare `from dm_judge_discrimination_probe
# import ...` works only when the probe is launched from inside src/tests/smoke/, so it
# ran fine by hand and broke the moment pytest imported this module from the repo root.
# src/tests/smoke/ is not a package, so the path has to be put on sys.path explicitly.
sys.path.insert( 0, os.path.dirname( os.path.abspath( __file__ ) ) )

from dm_judge_discrimination_probe import (
    BODIES,
    nonanswer_kind,
    is_measurement,
)

# At or above this share of real grades echoing the whole body, the run exits 1. Set at
# half deliberately: the point is not perfection, it is that evidence should USUALLY be
# usable. A single stray echo is noise; a coin flip is a broken contract.
ECHO_ALARM_RATE = 0.5

# Below this share of the body's words, evidence is a genuine excerpt. Between this and
# whole-echo is the grey band, reported separately rather than rounded into either — a
# threshold that silently absorbs its own near-misses cannot be contradicted.
FRAGMENT_MAX_RATIO = 0.60


def _normalize( text ):
    """
    Collapse text to comparable form: lowercase, punctuation-stripped, single-spaced.

    Requires:
        - text is a string

    Ensures:
        - returns a lowercase string whose only separator is a single space
        - strips characters the model routinely re-punctuates (quotes, dashes,
          ellipses), so a re-quoted sentence is not counted as a DIFFERENT sentence
          merely because a straight quote became a curly one
    """
    lowered = text.lower()
    stripped = re.sub( r"[^a-z0-9 ]+", " ", lowered )
    return re.sub( r"\s+", " ", stripped ).strip()


def _quoted_spans( evidence ):
    """
    The separately-quoted runs of text in the evidence, in order.

    Ensures:
        - returns the contents of every "..." pair, straight or curly quotes alike
        - returns [] when the model quoted nothing (it answered in bare prose)
    """
    return re.findall( r'["“]([^"”]+)["”]', evidence )


def classify_evidence( evidence, body ):
    """
    Name what the Tone evidence actually is, relative to the body it claims to quote.

    🔴 SPAN COUNT FIRST, RATIO SECOND — and the order is the whole correction (2026-08-01).
    This function originally decided on the word-count ratio alone, and that ratio CANNOT
    separate the two cases that matter. Measured on BURIED_JARGON: the model returned
    NINE discrete quoted phrases — "circle back on the thing we were discussing", "quite
    a journey getting here", "provenance-idempotent" — which together came to 63% of the
    body and were therefore filed as a near-whole "partial" dump. It was the single BEST
    piece of evidence in the run: every span named a specific offending phrase. A
    contiguous dump and a list of targeted quotes can have identical ratios and opposite
    meanings, so the ratio was measuring length where the question is aim.

    Requires:
        - evidence and body are strings

    Ensures:
        - returns "targeted" when the evidence is TWO OR MORE separately quoted spans,
          whatever they total — a list of named phrases is aimed evidence by construction
        - returns "echo" when the body is reproduced whole inside a single span
        - returns "partial"/"fragment" for a single span, by share of the body
        - returns "foreign" when most evidence words are absent from the body (the model
          narrating rather than quoting) — checked BEFORE ratio, since an invented string
          and a real quote of the same length are indistinguishable by ratio
        - returns "empty" for no evidence at all
    """
    norm_evidence = _normalize( evidence )
    norm_body     = _normalize( body )
    if not norm_evidence: return "empty"

    body_words     = norm_body.split()
    evidence_words = norm_evidence.split()

    # Foreign first: the model narrating instead of quoting is a different defect from
    # over-quoting, and it must not be scored on either the span or the ratio path.
    in_body = sum( 1 for w in evidence_words if w in set( body_words ) )
    if evidence_words and ( in_body / len( evidence_words ) ) < 0.7: return "foreign"

    # Two or more quoted spans = the model picked phrases out. That is aimed evidence
    # regardless of how much of the body it adds up to.
    if len( _quoted_spans( evidence ) ) >= 2: return "targeted"

    # Whole-echo: the entire body appears contiguously inside the evidence. Checked as a
    # substring rather than by ratio, so a body quoted whole PLUS a sentence of the
    # model's own commentary still reads as an echo — which it is.
    if norm_body in norm_evidence: return "echo"

    ratio = len( evidence_words ) / len( body_words ) if body_words else 0.0
    return "fragment" if ratio <= FRAGMENT_MAX_RATIO else "partial"


def _self_test():
    """
    Prove the classifier can separate cases whose answer is known, BEFORE trusting it.

    Ensures:
        - returns a list of failure strings; empty means the harness is sound
        - every case is one the classifier MUST get right for the run to mean anything,
          including two that must NOT be called "echo": a near-whole quote and an
          invented string
    """
    body = ( "The retry path is untested against a real timeout. I am holding your gate. "
             "I would not merge before Thursday." )
    cases = (
        ( "whole body echoed",       body,                                    "echo"     ),
        ( "echo plus commentary",    f'"{body}" — reads plainly.',            "echo"     ),
        ( "re-punctuated echo",      body.replace( ".", " ..." ),             "echo"     ),
        ( "true fragment",           "holding your gate",                     "fragment" ),
        ( "near-whole, not whole",   "The retry path is untested against a real timeout. "
                                     "I am holding your gate.",               "partial"  ),
        ( "invented evidence",       "reads like a competent professional summary",
                                                                              "foreign"  ),
        ( "empty evidence",          "",                                      "empty"    ),
        # 🔴 THE CASE THAT BROKE THE OLD CLASSIFIER, kept as a permanent control. These
        # four spans are ~70% of the body — over FRAGMENT_MAX_RATIO — so the ratio-only
        # version filed them as a near-whole dump. They are the opposite: four named
        # phrases. If this ever returns "partial" again, the ratio has taken the wheel
        # back and every echo number the probe reports is inflated.
        ( "many targeted spans",     '"The retry path is untested", "a real timeout", '
                                     '"holding your gate", "not merge before Thursday"',
                                                                              "targeted" ),
        # And its mirror: ONE span that happens to be short must NOT be called targeted
        # merely because it carries quote marks.
        ( "single quoted fragment",  '"holding your gate"',                   "fragment" ),
    )
    failures = []
    for name, evidence, expected in cases:
        got = classify_evidence( evidence, body )
        if got != expected:
            failures.append( f"{name}: expected {expected}, got {got}" )
    return failures


def run( runs ):
    """
    Grade every body `runs` times and tabulate what the Tone evidence turned out to be.

    Requires:
        - runs is a positive int
        - the judge is reachable and qualitative judging is ON (a run against the
          feature-off state measures nothing and is reported as such, not as 0% echo)

    Ensures:
        - returns ( rows, totals ) where rows is one dict per body and totals aggregates
          real grades only
        - non-answers are counted and EXCLUDED from the echo rate, never coerced
    """
    judge = get_dm_quality_judge()
    rows  = []
    totals = { "real": 0, "echo": 0, "partial": 0, "fragment": 0, "targeted": 0,
               "foreign": 0, "empty": 0, "nonanswer": 0 }

    for name, body in BODIES:
        row = { "name": name, "words": len( body.split() ), "real": 0, "echo": 0,
                "partial": 0, "fragment": 0, "targeted": 0, "foreign": 0,
                "empty": 0, "nonanswer": 0, "weights": [] }
        for _ in range( runs ):
            tone = judge.judge( body )[ "tone" ]
            if not is_measurement( tone ):
                row[ "nonanswer" ] += 1
                totals[ "nonanswer" ] += 1
                if os.environ.get( "PROBE_VERBOSE" ):
                    print( f"    {name}: NON-ANSWER ({nonanswer_kind( tone )})" )
                continue
            kind = classify_evidence( tone.get( "detail", "" ), body )
            row[ "real" ] += 1
            row[ kind ]   += 1
            row[ "weights" ].append( tone[ "weight" ] )
            totals[ "real" ] += 1
            totals[ kind ]   += 1
            if os.environ.get( "PROBE_VERBOSE" ):
                print( f"    {name}: weight={tone[ 'weight' ]:+d} evidence={kind}" )
        rows.append( row )

    return rows, totals


def report( rows, totals, runs ):
    """
    Print the per-body table and the verdict.

    Ensures:
        - a body that produced zero real grades prints "measured nothing" rather than a
          rate computed over an empty set
        - prints whether the echo rate tracks the GRADE, since "the model only echoes
          when it likes the message" is the first mechanism a reader will propose
    """
    print( f"\n  {'body':<16} {'words':>5} {'real':>5} {'echo':>5} {'part':>5} "
           f"{'frag':>5} {'targ':>5} {'foreign':>7} {'n/a':>5}  weights" )
    print( "  " + "-" * 80 )
    for r in rows:
        weights = ",".join( f"{w:+d}" for w in r[ "weights" ] ) if r[ "weights" ] else "—"
        print( f"  {r[ 'name' ]:<16} {r[ 'words' ]:>5} {r[ 'real' ]:>5} {r[ 'echo' ]:>5} "
               f"{r[ 'partial' ]:>5} {r[ 'fragment' ]:>5} {r[ 'targeted' ]:>5} "
               f"{r[ 'foreign' ]:>7} {r[ 'nonanswer' ]:>5}  {weights}" )

    real = totals[ "real" ]
    print()
    if real == 0:
        print( "  MEASURED NOTHING — every run was a non-answer. This is not a 0% echo "
               "rate; it is an absence of data." )
        return 2

    rate = totals[ "echo" ] / real
    print( f"  Real Tone grades: {real} of {runs * len( rows )} attempted "
           f"({totals[ 'nonanswer' ]} non-answers)" )
    unusable = totals[ "echo" ] + totals[ "partial" ]
    print( f"  Whole-body echo:  {totals[ 'echo' ]}/{real} = {rate:.0%}   "
           f"(partial {totals[ 'partial' ]}, fragment {totals[ 'fragment' ]}, "
           f"targeted {totals[ 'targeted' ]}, foreign {totals[ 'foreign' ]}, "
           f"empty {totals[ 'empty' ]})" )
    # Reported next to the echo rate, NOT folded into it. `echo` is the strict claim
    # (the body reproduced whole); `echo+partial` is the useful one (evidence a reader
    # cannot aim at anything). Keeping both visible means the alarm threshold can be
    # argued without re-running the model.
    print( f"  Unusable (echo+partial): {unusable}/{real} = {unusable / real:.0%}" )

    # Does echoing track the grade? A reader's first guess is "it echoes when it has
    # nothing specific to complain about", so answer it with the data rather than a
    # hunch — and say plainly when there is not enough spread to tell.
    echoed_weights = [ w for r in rows for w in r[ "weights" ] ]
    if len( set( echoed_weights ) ) < 2:
        print( "  Grade spread too narrow to say whether echoing tracks the grade." )
    else:
        by_body = [ ( r[ "name" ], r[ "echo" ], r[ "real" ], r[ "weights" ] )
                    for r in rows if r[ "real" ] ]
        mixed = [ n for n, e, t, _ in by_body if 0 < e < t ]
        if mixed:
            print( f"  Echo is NOT a property of the body: {', '.join( mixed )} produced "
                   f"both behaviours on the SAME text." )

    if rate >= ECHO_ALARM_RATE:
        print( f"\n  VERDICT: echo rate {rate:.0%} is at or above the {ECHO_ALARM_RATE:.0%} "
               f"alarm line. Tone's evidence is not usable for checking its own grade." )
        return 1
    print( f"\n  VERDICT: echo rate {rate:.0%} is below the alarm line." )
    return 0


def main():
    runs = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 3

    print( "\n  Auditing the harness before the model..." )
    failures = _self_test()
    if failures:
        print( "  HARNESS SELF-TEST FAILED — not calling the model:" )
        for f in failures: print( f"    - {f}" )
        return 2
    print( "  Harness self-test passed (9 cases, including the span-count control the\n  ratio-only classifier failed)." )

    print( f"\n  Grading {len( BODIES )} bodies x {runs} runs on Tone..." )
    rows, totals = run( runs )
    return report( rows, totals, runs )


if __name__ == "__main__":
    sys.exit( main() )
