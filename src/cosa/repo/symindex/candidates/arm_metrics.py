"""
The measures of the offline comparison: recall, twin rank and replayed verdicts.

Every function here is pure. The shortlists, rankings and cached answers come from the caller.
A unit test feeds hand-built cases and the run feeds the real ones.
"""
import statistics

from cosa.repo.symindex import verdict as vd

TOP_CUTS = ( 10, 50, 128 )


def recall_at_k( shortlist, reference ):
    """
    Measure how much of the reference a shortlist holds.

    Requires:
        - shortlist and reference are collections of ids
        - reference is not empty

    Ensures:
        - returns the share of reference ids found in the shortlist, from 0.0 to 1.0
    """
    if not reference: raise ValueError( "the reference shortlist is empty, so recall is undefined" )
    held = set( shortlist )
    return sum( 1 for doc_id in set( reference ) if doc_id in held ) / len( set( reference ) )


def t1_table( shortlists, references ):
    """
    Measure recall of the full-sweep shortlist for every arm and K.

    Requires:
        - shortlists maps arm to K to need id to the ids shortlisted
        - references maps need id to the full sweep's shortlist, and holds every need that appears

    Ensures:
        - returns { arm: { K: { "mean": float, "per_need": { need id: recall } } } }
        - a need with an empty reference is left out of the mean and the per-need map
    """
    table = {}
    for arm, by_k in shortlists.items():
        table[ arm ] = {}
        for k, by_need in by_k.items():
            per = { n: recall_at_k( ids, references[ n ] ) for n, ids in by_need.items() if references[ n ] }
            table[ arm ][ k ] = { "mean": statistics.fmean( per.values() ) if per else None, "per_need": per }
    return table


def reference_ids( decision ):
    """
    Read the full sweep's shortlist out of a decision.

    Requires:
        - decision is the result of verdict.decide

    Ensures:
        - returns the ids of the relevant entries, sorted
    """
    return sorted( row[ "id" ] for row in decision[ "shortlist" ] )


def twin_rank( ranking, twin_id ):
    """
    Find where a known twin lands in a ranking.

    Ensures:
        - returns the 1-based position, or None when the twin is not in the ranking
    """
    return ranking.index( twin_id ) + 1 if twin_id in ranking else None


def t3_summary( ranks_by_language ):
    """
    Summarise twin ranks by language.

    Requires:
        - ranks_by_language maps a language to a list of ranks, None for a twin that was not ranked

    Ensures:
        - returns, per language, the member count, the number not ranked, the median rank of the ranked ones,
          and the count at or inside each of TOP_CUTS
        - a language with no ranked twin has a median of None
    """
    out = {}
    for language, ranks in ranks_by_language.items():
        ranked = sorted( r for r in ranks if r is not None )
        out[ language ] = { "members"  : len( ranks ),
                            "unranked" : len( ranks ) - len( ranked ),
                            "median"   : statistics.median( ranked ) if ranked else None,
                            "within"   : { cut: sum( 1 for r in ranked if r <= cut ) for cut in TOP_CUTS } }
    return out


def decide_with_ids( rows, ids ):
    """
    Apply the verdict table to cached answers for a set of entries.

    Requires:
        - rows is a list of { id, probabilities } for entries that have a cached answer
        - ids is every entry the sweep is taken to cover

    Ensures:
        - returns the verdict string of verdict.decide, with no failed calls and no flags
    """
    return vd.decide( rows, ids, [], set() )[ "verdict" ]


def t2_replay( shortlists, answers, decide_fn=decide_with_ids ):
    """
    Replay cached judge answers over each arm's shortlists.

    Requires:
        - shortlists maps need id to the shortlisted ids
        - answers maps ( need id, repeat ) to { entry id: probabilities } for every entry the full sweep judged
        - decide_fn takes the rows and the id set, and returns a verdict string

    Ensures:
        - each repeat's verdict uses only shortlisted entries that have a cached answer
        - the reference verdict for a ( need, repeat ) uses every answered entry, so it is the full sweep's
        - returns { flip_rate, agreement, uncached, needs, verdicts: { need id: [ verdict per repeat ] } }
        - flip_rate is the share of needs whose repeats disagree
        - agreement is the share of ( need, repeat ) pairs where the arm's verdict equals the reference
        - uncached counts shortlisted entries that had no cached answer, over all repeats
    """
    verdicts, flips, agree, pairs, uncached = {}, 0, 0, 0, 0
    for need_id, ids in sorted( shortlists.items() ):
        repeats = sorted( r for n, r in answers if n == need_id )
        seen    = []
        for repeat in repeats:
            cached  = answers[ ( need_id, repeat ) ]
            rows    = [ { "id": i, "probabilities": cached[ i ] } for i in sorted( ids ) if i in cached ]
            uncached += len( ids ) - len( rows )
            verdict = decide_fn( rows, [ r[ "id" ] for r in rows ] )
            whole   = decide_fn( [ { "id": i, "probabilities": p } for i, p in sorted( cached.items() ) ], sorted( cached ) )
            seen.append( verdict )
            pairs += 1
            agree += 1 if verdict == whole else 0
        verdicts[ need_id ] = seen
        flips += 1 if len( set( seen ) ) > 1 else 0
    needs = len( verdicts )
    return { "flip_rate" : flips / needs if needs else None,
             "agreement" : agree / pairs if pairs else None,
             "uncached"  : uncached,
             "needs"     : needs,
             "verdicts"  : verdicts }


def choose_vectors( b1, b2 ):
    """
    Apply the rule that keeps two vectors only when they earn it.

    Requires:
        - b1 and b2 each hold "recall_128" and "median_rank", with None for a figure that was not measured

    Ensures:
        - returns the two-vector arm only when it beats the one-vector arm on recall at 128 or on the median twin rank
        - a higher recall and a lower rank are better, and a tie or a missing figure never beats
        - otherwise returns the one-vector arm
    """
    higher = b1[ "recall_128" ] is not None and b2[ "recall_128" ] is not None and b2[ "recall_128" ] > b1[ "recall_128" ]
    lower  = b1[ "median_rank" ] is not None and b2[ "median_rank" ] is not None and b2[ "median_rank" ] < b1[ "median_rank" ]
    return "B2" if higher or lower else "B1"
