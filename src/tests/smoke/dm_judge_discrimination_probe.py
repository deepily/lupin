"""
Live good-vs-bad discrimination probe for the DM Quality Judge (row ad560979).

WHY THIS AND NOT THE UNIT TIER. The 2026-07-31 BUG-1 regression was invisible to a green
unit suite and only showed up against the real model: the unit tests feed hand-written
clean XML, so they measure the PARSER, not whether the prompt still makes the model
discriminate. Any prompt edit has to be re-measured here or it is unverified.

THE MEASUREMENT. THREE fixed DM bodies — good, middling, bad — graded N times each. The
probe passes only if the grades are MONOTONIC (good > mid > bad) on each dimension
independently, using a margin rather than an average, so one overlapping run fails
instead of being averaged away.

🔴 WHY MONOTONICITY AND NOT JUST GOOD-vs-BAD (Maria 🌸, 2026-08-01). The first version of
   this probe checked only that every GOOD grade outranked every BAD grade, and it
   reported SEPARATED on a configuration where BAD scored (0,0) while MID scored (0,-1) —
   the WORST body grading BETTER on tone than a middling one. The gate was green on an
   inverted scale.

   Her correction is a rename, and the rename is the point: "cannot reach the bottom" is a
   RANGE defect, "ranks the bottom above the middle" is an ORDERING defect, and they need
   different fixes. A truncated scale is imprecise; an inverted one is actively
   misleading, because a reader ranks the two messages backwards. A two-point check
   cannot see ordering at all — it needs a third body in the middle, which is why one is
   now here.

Both bodies are kept UNDER the qualitative word limit on purpose; past it the judge
short-circuits to 🤷/0 without calling the model at all, which would make this probe
pass while measuring nothing.

Usage:  python judge_discrimination_probe.py [runs]
"""
import os
import sys

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )

from cosa.agents.dm_quality_judge.judge import DmQualityJudge, QUALITATIVE_WORD_LIMIT

# Leads with the verdict; every sentence after it is evidence or a required action.
GOOD_DM = (
    "Phase 1 is done and green. 89 unit tests pass, 100% lines and branches on the "
    "changed file. Not committed — I am holding your gate. One risk: the retry path "
    "is still untested against a real timeout, so I would not merge before Thursday."
)

# The MIDDLE body, and the reason it exists: without it the probe cannot tell a
# compressed scale from an INVERTED one. Mildly buried result, plain language — it
# should land between the other two on both dimensions and never below BAD.
MID_DM = (
    "I looked into the queue thing you mentioned. After some digging I think the fix "
    "is in running_fifo_queue, around the pop path."
)

# Buries the verdict under narration, and does it in coined vocabulary.
BAD_DM = (
    "So I wanted to circle back on the thing we were discussing earlier, and I have to "
    "say it has been quite a journey getting here. After some digging around in the "
    "queue layer I started to form a picture. The owed oracle's count-only path has no "
    "aperture disclosure, which admits re-park by induction and is therefore "
    "provenance-idempotent. Anyway I think it is probably fine now. That is the "
    "sharpest part of the whole exercise, and worth naming."
)

RANK = { "terrible": 0, "needs_improvement": 1, "meh": 2, "good": 3, "exemplary": 4 }


BODIES = ( ( "GOOD", GOOD_DM ), ( "MID", MID_DM ), ( "BAD", BAD_DM ) )

# The ordering the grades must respect, best first. Stated as data so the pairs the
# probe checks are visible rather than buried in an expression.
EXPECTED_ORDER = ( "GOOD", "MID", "BAD" )


def _ordered( results, index, dim_name ):
    """
    Is every adjacent pair strictly ordered on ONE dimension?

    Ensures:
        - compares the WORST run of the better body against the BEST run of the worse
          one — a margin, so a single overlapping run fails instead of averaging away
        - returns ( ok, list_of_failure_strings ); the failures name the pair AND the
          two numbers, because "not monotonic" alone does not say where it broke
    """
    failures = [ ]
    for better, worse in zip( EXPECTED_ORDER, EXPECTED_ORDER[ 1: ] ):
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

    print( f"\n{'run':<5}{'body':<7}{'direct':<10}{'w':<4}{'tone':<10}{'w':<4}{'overall'}" )
    print( "-" * 52 )
    for r in rows:
        print( f"{r[0]:<5}{r[1]:<7}{r[2]:<10}{r[3]:<4}{r[4]:<10}{r[5]:<4}{r[6]}" )

    ok_d, fail_d = _ordered( results, 0, "Directness" )
    ok_t, fail_t = _ordered( results, 1, "Tone" )

    print( "" )
    for name in EXPECTED_ORDER:
        ds = sorted( { r[ 0 ] for r in results[ name ] } )
        ts = sorted( { r[ 1 ] for r in results[ name ] } )
        print( f"{name:<5} directness={ds}  tone={ts}" )

    for line in fail_d + fail_t:
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
