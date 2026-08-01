"""
Live good-vs-bad discrimination probe for the DM Quality Judge (row ad560979).

WHY THIS AND NOT THE UNIT TIER. The 2026-07-31 BUG-1 regression was invisible to a green
unit suite and only showed up against the real model: the unit tests feed hand-written
clean XML, so they measure the PARSER, not whether the prompt still makes the model
discriminate. Any prompt edit has to be re-measured here or it is unverified.

THE MEASUREMENT. A 2x2 of fixed DM bodies — {verdict leads, verdict buried} x {plain
prose, jargon} — graded N times each. Each dimension is scored ONLY against the pair that
varies it while HOLDING the other property constant, so a failure is attributable to the
dimension being tested.

🔴 THIS SAMPLE HAS BEEN WRONG TWICE, and each time the sample was the defect rather than
   the judge. Both are recorded because the second one was invisible until the first was
   fixed.

   v1 — TWO bodies (good, bad). Reported SEPARATED on a configuration where BAD scored
   (0,0) while MID scored (0,-1): the WORST body grading BETTER on tone than a middling
   one. A two-point check cannot see ORDERING at all. Maria 🌸 caught it and the rename is
   the point — "cannot reach the bottom" is a RANGE defect, "ranks the bottom above the
   middle" is an ORDERING defect, and they need different fixes.

   v2 — THREE bodies (good, middling, bad), monotonicity asserted. Better, and still
   broken: all three were written in plain, ordinary English and differed only in whether
   the verdict was buried. So the TONE axis was never exercised, and the probe demanded a
   strict tone ordering across bodies whose tone barely differs — marking a model WRONG
   for correctly giving two plainly-written messages the same tone grade.

   ⇒ A sample that varies two properties TOGETHER cannot attribute a result to either one.
     That is why this is a 2x2 and not a ranked list, and why DIRECT_PLAIN is never
     compared against BURIED_JARGON: those cells differ on both properties, so a
     difference between them says nothing about either dimension.

Every body is kept UNDER the qualitative word limit on purpose; past it the judge
short-circuits to 🤷/0 without calling the model at all, which would make this probe
pass while measuring nothing.

Usage:  python judge_discrimination_probe.py [runs]
"""
import os
import sys

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )

from cosa.agents.dm_quality_judge.judge import DmQualityJudge, QUALITATIVE_WORD_LIMIT

# ── the 2x2, and why it is a 2x2 ──────────────────────────────────────────────
#
# 🔴 THE THIRD VERSION OF THIS SAMPLE, and the second time the sample itself was the
#    defect. Version one had two bodies (good, bad) and reported SEPARATED while the
#    middle of the scale was inverted — it could not see ORDERING at all. Version two
#    added a middle body and caught that. Both versions still varied the two dimensions
#    TOGETHER: good-on-both, middling, bad-on-both.
#
#    So the tone axis was never actually exercised. All three bodies were written in
#    plain, ordinary English; they differed in whether the verdict was buried. The probe
#    then demanded a strict TONE ordering across bodies whose tone barely differs — and
#    marked a model WRONG for correctly giving two plainly-written messages the same tone
#    grade.
#
#    ⇒ A sample that varies two properties together cannot attribute a result to either
#      one. Each dimension needs bodies that move along IT while the other is held.
#
# The four cells. Directness is graded on whether the verdict leads; tone on whether the
# prose is plain. Read down for the tone contrast, across for the directness contrast.
#
#                     PLAIN prose              JARGON + aphorism
#   verdict LEADS     DIRECT_PLAIN             DIRECT_JARGON
#   verdict BURIED    BURIED_PLAIN             BURIED_JARGON

DIRECT_PLAIN = (
    "Phase 1 is done and green. 89 unit tests pass, 100% lines and branches on the "
    "changed file. Not committed — I am holding your gate. One risk: the retry path "
    "is still untested against a real timeout, so I would not merge before Thursday."
)

# Same shape as above — verdict first, then evidence and a decision — but written badly.
DIRECT_JARGON = (
    "Rollback is done. The listener refactor tripped a re-entrancy invariant under the "
    "new dispatch aperture, so I reverted it and the owed oracle is provenance-idempotent "
    "again. I need your ruling on whether we re-land tonight. That trade is the "
    "load-bearing half of the whole incident, and worth naming."
)

# Plain, ordinary English — but the reader must hunt for the point.
BURIED_PLAIN = (
    "So I spent this morning going through the retry logic, and I read back through the "
    "ticket history, and I talked to the person who originally wrote it. There were a "
    "couple of dead ends along the way. It took longer than I expected. Anyway, the "
    "timeout is set to thirty seconds and it should be five."
)

# Buried AND badly written — the only body that should be low on both.
BURIED_JARGON = (
    "So I wanted to circle back on the thing we were discussing earlier, and I have to "
    "say it has been quite a journey getting here. After some digging around in the "
    "queue layer I started to form a picture. The owed oracle's count-only path has no "
    "aperture disclosure, which admits re-park by induction and is therefore "
    "provenance-idempotent. Anyway I think it is probably fine now. That is the "
    "sharpest part of the whole exercise, and worth naming."
)


BODIES = (
    ( "DIRECT_PLAIN",  DIRECT_PLAIN  ),
    ( "DIRECT_JARGON", DIRECT_JARGON ),
    ( "BURIED_PLAIN",  BURIED_PLAIN  ),
    ( "BURIED_JARGON", BURIED_JARGON ),
)

# Each dimension is scored ONLY against the contrast its own bodies establish, with the
# OTHER property held constant across the pair. That is the whole point of the 2x2: a
# claim about tone is made between two bodies that differ in tone and in nothing else
# that matters, so a failure is attributable to the dimension being tested.
#
# index 0 = directness, index 1 = tone.
CONTRASTS = {
    "Directness": ( 0, ( ( "DIRECT_PLAIN",  "BURIED_PLAIN"  ),      # prose held plain
                         ( "DIRECT_JARGON", "BURIED_JARGON" ) ) ),  # prose held jargon
    "Tone":       ( 1, ( ( "DIRECT_PLAIN",  "DIRECT_JARGON" ),      # verdict held leading
                         ( "BURIED_PLAIN",  "BURIED_JARGON" ) ) ),  # verdict held buried
}


def _ordered( results, index, pairs, dim_name ):
    """
    Does each held-constant pair come out in the right order on ONE dimension?

    Ensures:
        - compares the WORST run of the better body against the BEST run of the worse
          one — a margin, so a single overlapping run fails instead of averaging away
        - returns ( ok, list_of_failure_strings ); a failure names the pair AND the two
          numbers, because "not monotonic" alone does not say where it broke
        - makes NO claim across cells that differ on BOTH properties. DIRECT_PLAIN vs
          BURIED_JARGON is deliberately never compared: a difference there cannot be
          attributed to either dimension, and comparing it is how the previous version
          of this probe ended up marking a correct answer wrong
    """
    failures = [ ]
    for better, worse in pairs:
        worst_better = min( r[ index ] for r in results[ better ] )
        best_worse   = max( r[ index ] for r in results[ worse  ] )
        if worst_better <= best_worse:
            failures.append(
                f"{dim_name}: {better} ({worst_better}) is NOT above {worse} ({best_worse})" )
    return ( not failures ), failures


def main():
    runs = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 3

    for name, body in BODIES:
        wc = len( body.split() )
        assert wc <= QUALITATIVE_WORD_LIMIT, (
            f"{name} body is {wc} words, over the {QUALITATIVE_WORD_LIMIT} limit — the judge "
            f"would skip the model entirely and this probe would measure nothing" )

    judge = DmQualityJudge( debug=False, verbose=False )
    if not judge.available:
        print( "✗ judge LLM unavailable — probe cannot run" )
        return 2

    rows    = [ ]
    results = { name: [ ] for name, _ in BODIES }
    for i in range( runs ):
        for name, body in BODIES:
            g = judge.judge( body )
            d, t = g[ "directness" ], g[ "tone" ]
            results[ name ].append( ( d[ "weight" ], t[ "weight" ] ) )
            rows.append( ( i + 1, name, d[ "emoji" ], d[ "weight" ], t[ "emoji" ],
                           t[ "weight" ], g[ "overall" ][ "emoji" ] ) )

    print( f"\n{'run':<5}{'body':<15}{'direct':<10}{'w':<4}{'tone':<10}{'w':<4}{'overall'}" )
    print( "-" * 52 )
    for r in rows:
        print( f"{r[0]:<5}{r[1]:<15}{r[2]:<10}{r[3]:<4}{r[4]:<10}{r[5]:<4}{r[6]}" )

    verdicts, failures = { }, [ ]
    for dim_name, ( index, pairs ) in CONTRASTS.items():
        ok, fails = _ordered( results, index, pairs, dim_name )
        verdicts[ dim_name ] = ok
        failures.extend( fails )
    ok_d, ok_t = verdicts[ "Directness" ], verdicts[ "Tone" ]

    print( "" )
    for name, _ in BODIES:
        ds = sorted( { r[ 0 ] for r in results[ name ] } )
        ts = sorted( { r[ 1 ] for r in results[ name ] } )
        print( f"{name:<14} directness={ds}  tone={ts}" )

    for line in failures:
        print( f"  ✗ {line}" )

    # A 🤷/0 everywhere would satisfy no ordering, but a judge that has died mid-run
    # deserves its own exit code rather than being reported as a grading failure.
    if all( d == 0 and t == 0 for v in results.values() for d, t in v ):
        print( "\n✗ every run returned the 0 fallback — the judge is not grading at all" )
        return 2

    print( f"\n{'✓ MONOTONIC on both dimensions' if ok_d and ok_t else '✗ NOT MONOTONIC'}" )
    return 0 if ( ok_d and ok_t ) else 1


if __name__ == "__main__":
    raise SystemExit( main() )
