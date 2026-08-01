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

🔴 A NON-ANSWER IS NOT A MEASUREMENT (row ca7a2cbf, 2026-08-01). When the judge cannot
   parse the model's XML it falls back to weight 0 with detail "judge unavailable"; a body
   over the word limit returns weight 0 with a "too long" detail; the feature-off state
   returns weight None. A REAL `meh` grade is ALSO weight 0. Earlier versions of this probe
   compared WEIGHTS ONLY, so every fallback wore the costume of a real neutral grade and
   could silently satisfy an ordering test. This probe now classifies each dimension result
   by its `detail` string (imported from judge.py, never re-typed) and DROPS non-answers
   from the ordering entirely — a non-answer is never treated as a 0.

   The guard is PER CELL, not global: any cell that produced zero real grades on a
   dimension fails the run outright. A global "some data exists" check would let three
   good cells and one all-fallback cell satisfy an ordering by quietly comparing fewer
   cells — the same defect this probe fixes, one level out. And a run that measured
   nothing anywhere fails hardest of all (exit 2); it can never be mistaken for "I
   measured, and it was fine."

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

Usage:  python dm_judge_discrimination_probe.py [runs]
"""
import os
import sys

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )

from cosa.agents.dm_quality_judge.judge import (
    DmQualityJudge,
    QUALITATIVE_WORD_LIMIT,
    _JUDGE_UNAVAILABLE_DETAIL,
    _QUALITATIVE_OFF_DETAIL,
    _TOO_LONG_DETAIL,
)

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

# The non-answer kinds, in the order we report them. Keeping this list here (rather than
# re-deriving it in three places) means a table column, a per-cell counter, and a test
# fixture all agree on the same vocabulary.
NONANSWER_KINDS = ( "unavailable", "too_long", "withheld" )


def nonanswer_kind( dim ):
    """
    Name why a dimension result is NOT a real grade, or return None if it is one.

    A non-answer describes ITSELF — the judge's own state ("judge unavailable", "too
    long", "off"). A real grade describes something in the graded TEXT ("Leans on an
    aphorism instead of plain phrasing"). The two are distinguishable only by weight and
    detail together, NEVER by weight alone — a fallback and a real `meh` are both weight
    0. This is the whole defect the probe exists to close (row ca7a2cbf, §6.1).

    Requires:
        - dim is a dimension result dict carrying "weight" and "detail" keys, exactly as
          DmQualityJudge.judge() emits them

    Ensures:
        - returns one of NONANSWER_KINDS when the result is a non-answer, matched against
          the SAME constants judge.py emits (imported, never re-typed, so a drift in the
          judge cannot silently desynchronize this classifier)
        - returns None when the result is a real, comparable grade
    """
    if dim[ "weight" ] is None:                 return "withheld"
    detail = dim.get( "detail", "" )
    if detail == _JUDGE_UNAVAILABLE_DETAIL:     return "unavailable"
    if detail == _QUALITATIVE_OFF_DETAIL:       return "withheld"
    if detail.startswith( _TOO_LONG_DETAIL ):   return "too_long"
    return None


def is_measurement( dim ):
    """
    True iff this dimension result is a real grade, not a judge non-answer.

    Ensures:
        - returns True only when nonanswer_kind( dim ) is None
    """
    return nonanswer_kind( dim ) is None


def _measured_weights( runs, index ):
    """
    The real-grade weights on ONE dimension across a cell's runs — non-answers DROPPED.

    Requires:
        - runs is a list of ( directness_dict, tone_dict ) tuples
        - index is 0 (directness) or 1 (tone)

    Ensures:
        - returns a list of int weights, containing ONLY runs that were real grades; a
          non-answer is omitted, never coerced to 0
    """
    return [ r[ index ][ "weight" ] for r in runs if is_measurement( r[ index ] ) ]


def _cell_counts( runs, index ):
    """
    Count real grades and each kind of non-answer for ONE cell on ONE dimension.

    Ensures:
        - returns {"real": n, "unavailable": n, "too_long": n, "withheld": n}
        - the four counts sum to len( runs )
    """
    counts = { "real": 0, "unavailable": 0, "too_long": 0, "withheld": 0 }
    for r in runs:
        kind = nonanswer_kind( r[ index ] )
        counts[ "real" if kind is None else kind ] += 1
    return counts


def _ordered( results, index, pairs, dim_name ):
    """
    Do the held-constant pairs come out in the right order on ONE dimension?

    Scores ONLY pairs where both sides have at least one real grade — a dead cell (zero
    real grades) is caught separately and globally by evaluate(), so it is skipped here
    rather than double-reported. This function's job is ordering, not coverage.

    Ensures:
        - compares only REAL measurements — a non-answer is dropped, NEVER treated as a 0
        - compares the WORST run of the better body against the BEST run of the worse one
          — a margin, so a single overlapping run fails instead of averaging away
        - returns a list of failure strings; a failure names the pair AND the two numbers
        - makes NO claim across cells that differ on BOTH properties (DIRECT_PLAIN vs
          BURIED_JARGON is deliberately never compared)
    """
    failures = [ ]
    for better, worse in pairs:
        wb = _measured_weights( results[ better ], index )
        ww = _measured_weights( results[ worse  ], index )
        if not wb or not ww:
            continue                                # dead cell — reported by evaluate()
        worst_better = min( wb )
        best_worse   = max( ww )
        if worst_better <= best_worse:
            failures.append(
                f"{dim_name}: {better} ({worst_better}) is NOT above {worse} ({best_worse})" )
    return failures


def evaluate( results, contrasts ):
    """
    Turn per-cell run results into a verdict that CANNOT confuse a non-answer with a grade.

    Requires:
        - results maps body-name -> list of ( directness_dict, tone_dict ) runs, each dict
          carrying "weight" and "detail" exactly as DmQualityJudge.judge() emits
        - contrasts is the CONTRASTS map ( dim_name -> ( index, pairs ) )

    Ensures:
        - counts real grades and each kind of non-answer PER CELL PER DIMENSION (cell_stats)
        - dead_cells lists every ( body, dimension ) that produced ZERO real grades — the
          per-cell guard, so one all-fallback cell fails the run even when the other three
          cells are fully graded
        - status is exactly one of:
            "NO_MEASUREMENTS" — zero real grades ANYWHERE; the probe measured nothing
            "INSUFFICIENT"    — at least one dead cell; an ordering rests on missing grades
            "NOT_MONOTONIC"   — every needed cell measured, at least one ordering wrong
            "MONOTONIC"       — every needed cell measured and every ordering correct
        - exit_code is 0 ONLY for MONOTONIC; 1 for NOT_MONOTONIC and INSUFFICIENT; 2 for
          NO_MEASUREMENTS — a probe that measured nothing is a HARD failure, never a pass
        - returns a report dict:
            {"status", "exit_code", "cell_stats", "dead_cells", "total_real",
             "failures", "verdicts"}
    """
    cell_stats = { }
    dead_cells = [ ]
    total_real = 0
    for name in results:
        cell_stats[ name ] = { }
        for dim_name, ( index, _pairs ) in contrasts.items():
            counts = _cell_counts( results[ name ], index )
            cell_stats[ name ][ dim_name ] = counts
            total_real += counts[ "real" ]
            if counts[ "real" ] == 0:
                dead_cells.append( ( name, dim_name ) )

    failures, verdicts = [ ], { }
    for dim_name, ( index, pairs ) in contrasts.items():
        fails = _ordered( results, index, pairs, dim_name )
        # A dimension is "ok" only if it had no ordering failures AND no dead cell.
        dim_dead = any( d == dim_name for _n, d in dead_cells )
        verdicts[ dim_name ] = ( not fails ) and ( not dim_dead )
        failures.extend( fails )

    if total_real == 0:
        status, exit_code = "NO_MEASUREMENTS", 2
    elif dead_cells:
        status, exit_code = "INSUFFICIENT", 1
    elif failures:
        status, exit_code = "NOT_MONOTONIC", 1
    else:
        status, exit_code = "MONOTONIC", 0

    return {
        "status"     : status,
        "exit_code"  : exit_code,
        "cell_stats" : cell_stats,
        "dead_cells" : dead_cells,
        "total_real" : total_real,
        "failures"   : failures,
        "verdicts"   : verdicts,
    }


def _nonanswer_summary( counts ):
    """Compact "u=1 t=0 w=2" tail for the non-answer columns; empty string if all zero."""
    parts = [ ]
    if counts[ "unavailable" ]: parts.append( f"u={counts[ 'unavailable' ]}" )
    if counts[ "too_long"    ]: parts.append( f"t={counts[ 'too_long'    ]}" )
    if counts[ "withheld"    ]: parts.append( f"w={counts[ 'withheld'    ]}" )
    return " ".join( parts )


def main():
    runs = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 3

    for name, body in BODIES:
        wc = len( body.split() )
        assert wc <= QUALITATIVE_WORD_LIMIT, (
            f"{name} body is {wc} words, over the {QUALITATIVE_WORD_LIMIT} limit — the judge "
            f"would skip the model entirely and this probe would measure nothing" )

    # Force qualitative grading ON regardless of the ambient INI. The feature ships OFF
    # (row ca7a2cbf), but this probe exists to measure the qualitative half itself, so it
    # injects the seam rather than depending on an operator's toggle. Say so LOUDLY — a
    # reader who assumes this verdict describes live behavior would be wrong.
    print( "── DM Quality Judge discrimination probe ─────────────────────────────" )
    print( "⚠ qualitative judging FORCED ON for this probe (injection seam)." )
    print( "  Production ships qualitative OFF (row ca7a2cbf); this measures the" )
    print( "  qualitative half in isolation, NOT live DM-grading behavior." )

    judge = DmQualityJudge( debug=False, verbose=False, qualitative_enabled=True )
    if not judge.available:
        print( "✗ judge LLM unavailable — probe cannot run" )
        return 2

    rows    = [ ]
    results = { name: [ ] for name, _ in BODIES }
    for i in range( runs ):
        for name, body in BODIES:
            g = judge.judge( body )
            d, t = g[ "directness" ], g[ "tone" ]
            results[ name ].append( ( d, t ) )
            rows.append( ( i + 1, name, d[ "emoji" ], d[ "weight" ], t[ "emoji" ],
                           t[ "weight" ], g[ "overall" ][ "emoji" ] ) )

    print( f"\n{'run':<5}{'body':<15}{'direct':<10}{'w':<6}{'tone':<10}{'w':<6}{'overall'}" )
    print( "-" * 56 )
    for r in rows:
        wd = "—" if r[ 3 ] is None else r[ 3 ]
        wt = "—" if r[ 5 ] is None else r[ 5 ]
        print( f"{r[0]:<5}{r[1]:<15}{r[2]:<10}{str( wd ):<6}{r[4]:<10}{str( wt ):<6}{r[6]}" )

    report = evaluate( results, CONTRASTS )

    # The 2x2, with the real-grade weights AND the non-answer count stated PER CELL — a
    # cell that never produced a real grade is the headline, not a footnote.
    print( "\n2x2 real-grade weights (non-answers are NOT shown as 0):" )
    for name, _ in BODIES:
        line = f"  {name:<14}"
        for dim_name in ( "Directness", "Tone" ):
            index  = CONTRASTS[ dim_name ][ 0 ]
            counts = report[ "cell_stats" ][ name ][ dim_name ]
            ws     = sorted( { w for w in _measured_weights( results[ name ], index ) } )
            tail   = _nonanswer_summary( counts )
            tail   = f"  [non-answers {tail}]" if tail else ""
            label  = "direct" if dim_name == "Directness" else "tone"
            shown  = ws if counts[ "real" ] else "NONE MEASURED"
            line  += f"  {label}={shown}{tail}"
        print( line )

    # Loud, un-missable non-answer accounting. If ANY cell produced a non-answer, say so
    # here — a reader must never have to infer it from a suspiciously clean table.
    total_nonanswers = sum(
        report[ "cell_stats" ][ name ][ dim ][ k ]
        for name, _ in BODIES for dim in ( "Directness", "Tone" ) for k in NONANSWER_KINDS
    )
    if total_nonanswers:
        print( f"\n🔴 NON-ANSWERS PRESENT: {total_nonanswers} dimension-result(s) were NOT real grades." )
        print( "   (u=judge unavailable/parse-fail, t=too long, w=withheld/feature-off)" )
        for name, _ in BODIES:
            for dim_name in ( "Directness", "Tone" ):
                counts = report[ "cell_stats" ][ name ][ dim_name ]
                tail   = _nonanswer_summary( counts )
                if tail:
                    print( f"   {name:<14} {dim_name:<11} real={counts[ 'real' ]}  {tail}" )

    for name, dim_name in report[ "dead_cells" ]:
        print( f"  ⚠ DEAD CELL: {name} produced 0 real grades on {dim_name} — cannot be ordered" )
    for line in report[ "failures" ]:
        print( f"  ✗ {line}" )

    status = report[ "status" ]
    banner = {
        "NO_MEASUREMENTS" : "✗ MEASURED NOTHING — every dimension was a non-answer; this is NOT a pass",
        "INSUFFICIENT"    : "✗ INSUFFICIENT — a dead cell means an ordering rests on grades that do not exist",
        "NOT_MONOTONIC"   : "✗ NOT MONOTONIC",
        "MONOTONIC"       : "✓ MONOTONIC on both dimensions",
    }[ status ]
    print( f"\n{banner}" )
    return report[ "exit_code" ]


if __name__ == "__main__":
    raise SystemExit( main() )
