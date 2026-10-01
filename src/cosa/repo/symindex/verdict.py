"""
The check_exists decision table as a pure function (see README-reuse-decision-table.md).

No file, network or model access happens here: the caller supplies the answers received and the
state of the pipeline, and gets back the verdict, the cause, every cause that holds, the shortlist
and the nearest entries. An answer that is malformed is reported under its own cause and never
contributes to a verdict.
"""
import math

POLICY = { "threshold": 0.5, "confidence": 0.9, "floor": 0.3, "shortlist": 10, "sum_tolerance": 0.02 }

CAUSES  = ( "NOT_LUPIN_TREE", "DEPENDENCY_MISSING", "INDEX_STALE", "KEY_UNREADABLE", "CALL_FAILED", "MALFORMED_ANSWER", "LOW_CONFIDENCE" )
ANSWERS = ( "reuse", "extend", "unrelated" )


def malformed_reason( probabilities, policy=POLICY ):
    """
    Check one answer's probabilities.

    Ensures:
        - returns None when they are valid: exactly the keys reuse, extend and unrelated, each a
          finite real number in [0, 1] (a bool is not a number), summing to 1 within sum_tolerance
        - otherwise returns the first reason: not_a_mapping, missing_or_extra_keys, not_a_number,
          not_finite, out_of_range or sum_not_one
    """
    if not isinstance( probabilities, dict ): return "not_a_mapping"
    if set( probabilities ) != set( ANSWERS ): return "missing_or_extra_keys"
    values = [ probabilities[ k ] for k in ANSWERS ]
    if any( isinstance( v, bool ) or not isinstance( v, ( int, float ) ) for v in values ): return "not_a_number"
    try:
        finite = all( math.isfinite( v ) for v in values )
    except OverflowError:                                              # an int too large for a float
        finite = False
    if not finite: return "not_finite"
    if any( v < 0.0 or v > 1.0 for v in values ): return "out_of_range"
    if abs( sum( values ) - 1.0 ) > policy[ "sum_tolerance" ] + 1e-9: return "sum_not_one"      # slack for float addition
    return None


def call_facts( probabilities ):
    """
    Requires:
        - probabilities is valid (malformed_reason returned None)
    Ensures:
        - returns ( p_overlap, confidence, choice ) for one answered call
        - choice is the key with the largest probability; a tie goes to reuse, then extend
    """
    p_overlap  = probabilities[ "reuse" ] + probabilities[ "extend" ]
    confidence = max( probabilities.values() )
    choice     = next( k for k in ANSWERS if probabilities[ k ] == confidence )
    return p_overlap, confidence, choice


def _order( rows ):
    """Ensures: returns the rows sorted by p_overlap descending, then id."""
    return sorted( rows, key=lambda r: ( -r[ "p_overlap" ], r[ "id" ] ) )


def decide( answers, expected_ids, failed_ids, flags, policy=POLICY ):
    """
    Apply the decision table to one sweep.

    Requires:
        - answers is a list of dicts { "id": str, "probabilities": <anything> }; the caller (the sweep)
          guarantees the dict shape and the id, and puts None in `probabilities` when the model's
          response lacked them. The probabilities themselves are validated here
        - expected_ids is the collection of every index entry id the sweep should have covered
        - failed_ids is the collection of ids whose call failed after retries
        - flags is a set drawn from CAUSES naming the pipeline problems already known
          (NOT_LUPIN_TREE, DEPENDENCY_MISSING, INDEX_STALE, KEY_UNREADABLE)
    Ensures:
        - returns { verdict, cause, causes, shortlist, shortlist_total, nearest, malformed, missing }
        - verdict is REUSE, EXTEND, NEW or UNCERTAIN_READ_SOURCE; cause is None unless UNCERTAIN
        - causes lists every cause that holds, in the order of CAUSES
        - coverage is set equality: CALL_FAILED holds when any call failed or any expected id is
          neither answered nor failed nor malformed; `missing` is the sorted list of those ids
        - MALFORMED_ANSWER holds when an answer has an invalid probability mapping, an id that is
          not expected, or an id answered twice (every copy is dropped); `malformed` lists
          { id, reason }, and such an answer never reaches a verdict
        - a call is relevant when p_overlap >= threshold and doubtful when p_overlap >= floor
          and confidence < the confidence bar, so unrelated entries never cause uncertainty
        - shortlist holds the relevant entries and `nearest` the best entries by p_overlap whatever
          their value, each cut to policy["shortlist"], so a NEW verdict still names what to read
    """
    expected  = set( expected_ids )
    failed    = set( failed_ids )
    seen, dup = set(), set()
    for a in answers:
        if a[ "id" ] in seen: dup.add( a[ "id" ] )
        seen.add( a[ "id" ] )
    rows, malformed = [], []
    for a in answers:
        reason = "duplicate_id" if a[ "id" ] in dup else "unknown_id" if a[ "id" ] not in expected else malformed_reason( a[ "probabilities" ], policy )
        if reason is not None:
            malformed.append( { "id": a[ "id" ], "reason": reason } ); continue
        p, conf, choice = call_facts( a[ "probabilities" ] )
        rows.append( { "id": a[ "id" ], "p_overlap": round( p, 6 ), "confidence": round( conf, 6 ), "choice": choice } )
    accounted = { r[ "id" ] for r in rows } | { m[ "id" ] for m in malformed } | failed
    missing   = sorted( expected - accounted )
    holds     = set( flags )
    if failed or missing:   holds.add( "CALL_FAILED" )
    if malformed:           holds.add( "MALFORMED_ANSWER" )
    if any( r[ "p_overlap" ] >= policy[ "floor" ] and r[ "confidence" ] < policy[ "confidence" ] for r in rows ): holds.add( "LOW_CONFIDENCE" )
    ordered  = _order( rows )
    relevant = [ r for r in ordered if r[ "p_overlap" ] >= policy[ "threshold" ] ]
    causes   = [ c for c in CAUSES if c in holds ]
    if causes:          verdict = "UNCERTAIN_READ_SOURCE"
    elif not relevant:  verdict = "NEW"
    elif any( r[ "choice" ] == "reuse" for r in relevant ): verdict = "REUSE"
    else:               verdict = "EXTEND"
    return { "verdict"         : verdict,
             "cause"           : causes[ 0 ] if causes else None,
             "causes"          : causes,
             "shortlist"       : relevant[ :policy[ "shortlist" ] ],
             "shortlist_total" : len( relevant ),
             "nearest"         : ordered[ :policy[ "shortlist" ] ],
             "malformed"       : malformed,
             "missing"         : missing }
