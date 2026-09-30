"""
The check_exists decision table as a pure function (see README-reuse-decision-table.md).

No file, network or model access happens here: the caller supplies the answered calls and the
state of the pipeline, and gets back the verdict, the cause, every cause that holds, and the
shortlist. That keeps the rule testable row by row.
"""
POLICY = { "threshold": 0.5, "confidence": 0.9, "floor": 0.3, "shortlist": 10 }

CAUSES = ( "NOT_LUPIN_TREE", "DEPENDENCY_MISSING", "INDEX_STALE", "KEY_UNREADABLE", "CALL_FAILED", "LOW_CONFIDENCE" )


def call_facts( probabilities ):
    """
    Requires:
        - probabilities has the keys reuse, extend and unrelated
    Ensures:
        - returns ( p_overlap, confidence, choice ) for one answered call
        - choice is the key with the largest probability; a tie goes to reuse, then extend
    """
    p_overlap  = probabilities[ "reuse" ] + probabilities[ "extend" ]
    confidence = max( probabilities.values() )
    choice     = next( k for k in ( "reuse", "extend", "unrelated" ) if probabilities[ k ] == confidence )
    return p_overlap, confidence, choice


def decide( answers, total_entries, failed_calls, flags, policy=POLICY ):
    """
    Apply the decision table to one sweep.

    Requires:
        - answers is a list of { "id": str, "probabilities": { reuse, extend, unrelated } }
        - total_entries is the number of index entries the sweep should have covered
        - failed_calls is the number of calls that failed after retries
        - flags is a set drawn from CAUSES naming the pipeline problems already known
          (NOT_LUPIN_TREE, DEPENDENCY_MISSING, INDEX_STALE, KEY_UNREADABLE)
    Ensures:
        - returns { "verdict", "cause", "causes", "shortlist", "shortlist_total" }
        - verdict is REUSE, EXTEND, NEW or UNCERTAIN_READ_SOURCE; cause is None unless UNCERTAIN
        - causes lists every cause that holds, in the order of CAUSES
        - a call is relevant when p_overlap >= threshold and doubtful when p_overlap >= floor
          and confidence < the confidence bar, so unrelated entries never cause uncertainty
        - the shortlist is sorted by p_overlap descending then id, and cut to policy["shortlist"]
    """
    holds   = set( flags )
    rows    = []
    for a in answers:
        p, conf, choice = call_facts( a[ "probabilities" ] )
        rows.append( { "id": a[ "id" ], "p_overlap": round( p, 6 ), "confidence": round( conf, 6 ), "choice": choice } )
    if failed_calls > 0 or len( answers ) < total_entries: holds.add( "CALL_FAILED" )
    if any( r[ "p_overlap" ] >= policy[ "floor" ] and r[ "confidence" ] < policy[ "confidence" ] for r in rows ): holds.add( "LOW_CONFIDENCE" )
    relevant = sorted( ( r for r in rows if r[ "p_overlap" ] >= policy[ "threshold" ] ), key=lambda r: ( -r[ "p_overlap" ], r[ "id" ] ) )
    causes   = [ c for c in CAUSES if c in holds ]
    if causes:          verdict = "UNCERTAIN_READ_SOURCE"
    elif not relevant:  verdict = "NEW"
    elif any( r[ "choice" ] == "reuse" for r in relevant ): verdict = "REUSE"
    else:               verdict = "EXTEND"
    return { "verdict"         : verdict,
             "cause"           : causes[ 0 ] if causes else None,
             "causes"          : causes,
             "shortlist"       : relevant[ :policy[ "shortlist" ] ],
             "shortlist_total" : len( relevant ) }
