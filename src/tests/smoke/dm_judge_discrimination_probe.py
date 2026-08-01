"""
Live good-vs-bad discrimination probe for the DM Quality Judge (row ad560979).

WHY THIS AND NOT THE UNIT TIER. The 2026-07-31 BUG-1 regression was invisible to a green
unit suite and only showed up against the real model: the unit tests feed hand-written
clean XML, so they measure the PARSER, not whether the prompt still makes the model
discriminate. Any prompt edit has to be re-measured here or it is unverified.

THE MEASUREMENT. Two fixed DM bodies, one deliberately good and one deliberately bad on
BOTH qualitative dimensions, graded N times each. The probe passes only if every good
grade outranks every bad grade on both Directness and Tone — a margin, not an average,
so one bad-run overlap fails rather than being averaged away.

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


def main():
    runs = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 3

    for name, body in ( ( "GOOD", GOOD_DM ), ( "BAD", BAD_DM ) ):
        wc = len( body.split() )
        assert wc <= QUALITATIVE_WORD_LIMIT, (
            f"{name} body is {wc} words, over the {QUALITATIVE_WORD_LIMIT} limit — the judge "
            f"would skip the model entirely and this probe would measure nothing" )

    judge = DmQualityJudge( debug=False, verbose=False )
    if not judge.available:
        print( "✗ judge LLM unavailable — probe cannot run" )
        return 2

    rows, results = [ ], { "GOOD": [ ], "BAD": [ ] }
    for i in range( runs ):
        for name, body in ( ( "GOOD", GOOD_DM ), ( "BAD", BAD_DM ) ):
            g = judge.judge( body )
            d, t = g[ "directness" ], g[ "tone" ]
            results[ name ].append( ( d[ "weight" ], t[ "weight" ] ) )
            rows.append( ( i + 1, name, d[ "emoji" ], d[ "weight" ], t[ "emoji" ],
                           t[ "weight" ], g[ "overall" ][ "emoji" ] ) )

    print( f"\n{'run':<5}{'body':<7}{'direct':<10}{'w':<4}{'tone':<10}{'w':<4}{'overall'}" )
    print( "-" * 52 )
    for r in rows:
        print( f"{r[0]:<5}{r[1]:<7}{r[2]:<10}{r[3]:<4}{r[4]:<10}{r[5]:<4}{r[6]}" )

    worst_good_d = min( d for d, _ in results[ "GOOD" ] )
    best_bad_d   = max( d for d, _ in results[ "BAD"  ] )
    worst_good_t = min( t for _, t in results[ "GOOD" ] )
    best_bad_t   = max( t for _, t in results[ "BAD"  ] )

    ok_d = worst_good_d > best_bad_d
    ok_t = worst_good_t > best_bad_t

    print( f"\nDirectness: worst GOOD={worst_good_d}  best BAD={best_bad_d}  "
           f"-> {'SEPARATED' if ok_d else 'OVERLAP'}" )
    print( f"Tone:       worst GOOD={worst_good_t}  best BAD={best_bad_t}  "
           f"-> {'SEPARATED' if ok_t else 'OVERLAP'}" )

    # A 🤷/0 on every run would show as "separated" if both sides collapsed together;
    # guard it explicitly so a dead judge cannot read as a pass.
    if all( d == 0 and t == 0 for d, t in results[ "GOOD" ] ):
        print( "\n✗ every GOOD run returned the 0 fallback — the judge is not grading at all" )
        return 2

    print( f"\n{'✓ DISCRIMINATION HOLDS' if ok_d and ok_t else '✗ DISCRIMINATION LOST'}" )
    return 0 if ( ok_d and ok_t ) else 1


if __name__ == "__main__":
    raise SystemExit( main() )
