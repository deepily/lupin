"""
The check_exists decision table as a pure function (see README-reuse-decision-table.md).

No file, network or model access happens here. The caller supplies the answers received and the
state of the pipeline. It gets back the verdict, the cause, every cause that holds, the shortlist
and the nearest entries. A malformed answer is reported under its own cause and never
contributes to a verdict.
"""
import math

STRONG_MATCH = 0.9      # the best entry's overlap and confidence must both reach this for a strong match to win

POLICY = { "threshold": 0.5, "confidence": 0.9, "floor": 0.3, "shortlist": 10, "sum_tolerance": 0.02, "strong": STRONG_MATCH }

CAUSES  = ( "NOT_LUPIN_TREE", "DEPENDENCY_MISSING", "INDEX_STALE", "KEY_UNREADABLE", "CALL_FAILED", "MALFORMED_ANSWER", "LOW_CONFIDENCE" )
ANSWERS = ( "reuse", "extend", "unrelated" )


def malformed_reason( probabilities, policy=POLICY ):
    """
    Check one answer's probabilities.

    Ensures:
        - returns None when they are valid: the keys reuse, extend and unrelated and no others, each a
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
    Return the overlap, confidence and choice of one valid answer.

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


def _is_strong( row, policy ):
    """Ensures: returns True when the row's overlap and confidence both reach policy["strong"]."""
    return row[ "p_overlap" ] >= policy[ "strong" ] and row[ "confidence" ] >= policy[ "strong" ]


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
        - flags is a set drawn from `CAUSES` naming the pipeline problems already known
          (NOT_LUPIN_TREE, DEPENDENCY_MISSING, INDEX_STALE, KEY_UNREADABLE)
    Ensures:
        - returns { verdict, cause, causes, shortlist, shortlist_total, nearest, doubtful, malformed, missing }
        - verdict is `REUSE`, `EXTEND`, `NEW` or `UNCERTAIN_READ_SOURCE`; cause is None unless `UNCERTAIN_READ_SOURCE`
        - causes lists every cause that holds, in the order of `CAUSES`
        - coverage is set equality: CALL_FAILED holds when any call failed or any expected id is
          neither answered nor failed nor malformed; `missing` is the sorted list of those ids
        - MALFORMED_ANSWER holds when an answer has an invalid probability mapping, an id that is
          not expected, or an id answered twice (every copy is dropped); `malformed` lists
          { id, reason }, and such an answer never reaches a verdict
        - a call is relevant when p_overlap >= threshold and doubtful when p_overlap >= floor
          and confidence < the confidence bar, so unrelated entries never cause uncertainty
        - a strong match wins: when policy["strong"] is set and some entry has both p_overlap and
          confidence at or above it, doubtful entries no longer cause LOW_CONFIDENCE and are listed in
          `doubtful` instead; every other cause still holds, and the reuse-or-extend choice is decided from the strong entries only. A policy without "strong" (a receipt stored
          before the rule) never has a strong match, so it replays as it was stored
        - doubtful lists the doubtful entries best first, cut to policy["shortlist"], whether or not they cause uncertainty
        - shortlist holds the relevant entries and `nearest` the best entries by p_overlap whatever
          their value, each cut to policy["shortlist"], so a `NEW` verdict still names what to read
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
    ordered  = _order( rows )
    doubtful = [ r for r in ordered if r[ "p_overlap" ] >= policy[ "floor" ] and r[ "confidence" ] < policy[ "confidence" ] ]
    strong   = "strong" in policy and any( _is_strong( r, policy ) for r in rows )
    if doubtful and not strong: holds.add( "LOW_CONFIDENCE" )
    relevant = [ r for r in ordered if r[ "p_overlap" ] >= policy[ "threshold" ] ]
    deciding = [ r for r in relevant if _is_strong( r, policy ) ] if strong else relevant
    causes   = [ c for c in CAUSES if c in holds ]
    if causes:          verdict = "UNCERTAIN_READ_SOURCE"
    elif not relevant:  verdict = "NEW"
    elif any( r[ "choice" ] == "reuse" for r in deciding ): verdict = "REUSE"
    else:               verdict = "EXTEND"
    return { "verdict"         : verdict,
             "cause"           : causes[ 0 ] if causes else None,
             "causes"          : causes,
             "shortlist"       : relevant[ :policy[ "shortlist" ] ],
             "shortlist_total" : len( relevant ),
             "nearest"         : ordered[ :policy[ "shortlist" ] ],
             "doubtful"        : doubtful[ :policy[ "shortlist" ] ],
             "malformed"       : malformed,
             "missing"         : missing }


LEVELS = ( "0", "1", "2", "3" )

POLICY_PROVIDES = { "threshold": 0.5, "reuse": 0.7, "floor": 0.3, "coverage": 0.5, "shortlist": 10, "sum_tolerance": 0.02 }


def _number_reason( values, low=0.0, high=1.0 ):
    """
    Check that every value is a finite real number inside [low, high].

    Ensures:
        - returns None when all are; otherwise the first reason: not_a_number (a bool is not a number),
          not_finite or out_of_range
    """
    if any( isinstance( v, bool ) or not isinstance( v, ( int, float ) ) for v in values ): return "not_a_number"
    try:
        finite = all( math.isfinite( v ) for v in values )
    except OverflowError:                                              # an int too large for a float
        finite = False
    if not finite: return "not_finite"
    if any( v < low or v > high for v in values ): return "out_of_range"
    return None


def malformed_reason_provides( provides, coverage, policy=POLICY_PROVIDES ):
    """
    Check one answer's Noul number and Score probabilities.

    Ensures:
        - returns None when both are valid: provides a finite real number in [0, 1], coverage a
          mapping with the keys 0, 1, 2 and 3, each a finite real in [0, 1], summing to 1
          within sum_tolerance
        - otherwise returns the first reason, provides first: not_a_number, not_finite, out_of_range,
          not_a_mapping, missing_or_extra_keys or sum_not_one
    """
    reason = _number_reason( [ provides ] )
    if reason is not None: return reason
    if not isinstance( coverage, dict ): return "not_a_mapping"
    if set( coverage ) != set( LEVELS ): return "missing_or_extra_keys"
    values = [ coverage[ k ] for k in LEVELS ]
    reason = _number_reason( values )
    if reason is not None: return reason
    if abs( sum( values ) - 1.0 ) > policy[ "sum_tolerance" ] + 1e-9: return "sum_not_one"      # slack for float addition
    return None


def _provides_row( answer ):
    """
    Build one row from a valid answer.

    Ensures:
        - returns { id, provides, coverage, score } for one valid answer, each rounded to 6 places
        - coverage is the probability at level 2 or 3, and score is recomputed from the levels
    """
    cov = answer[ "coverage" ]
    return { "id"       : answer[ "id" ],
             "provides" : round( answer[ "provides" ], 6 ),
             "coverage" : round( cov[ "2" ] + cov[ "3" ], 6 ),
             "score"    : round( sum( int( k ) * cov[ k ] for k in LEVELS ), 6 ) }


def _provides_order( rows ):
    """Ensures: returns the rows sorted by provides descending, then id."""
    return sorted( rows, key=lambda r: ( -r[ "provides" ], r[ "id" ] ) )


def _cut_shortlist( causal, pool, cap ):
    """
    Cut the shortlist pool to the cap, keeping the causal rows first.

    Requires:
        - causal is a subset of pool, both ranked by provides then id
    Ensures:
        - returns at most cap rows ranked by provides then id
        - when causal holds cap rows or more, only the best cap causal rows stay; otherwise every causal
          row stays and the best non-causal rows fill the rest
    """
    if len( causal ) >= cap: return _provides_order( causal[ :cap ] )
    causal_ids = { r[ "id" ] for r in causal }
    others     = [ r for r in pool if r[ "id" ] not in causal_ids ]
    return _provides_order( causal + others[ :cap - len( causal ) ] )


def decide_provides( answers, expected_ids, failed_ids, flags, policy=POLICY_PROVIDES ):
    """
    Apply the Noul-and-Score decision rule to one sweep.

    Requires:
        - answers is a list of dicts { "id": str, "provides": <anything>, "coverage": <anything> };
          provides is the Noul number and coverage the Score probabilities keyed 0 to 3
        - expected_ids, failed_ids and flags are as for decide
    Ensures:
        - returns the same keys as decide: verdict, cause, causes, shortlist, shortlist_total,
          nearest, doubtful, malformed, missing; rows are { id, provides, coverage, score }
        - a malformed answer (duplicate_id, unknown_id or a reason from malformed_reason_provides) is
          reported under `MALFORMED_ANSWER` and never half used
        - `CALL_FAILED` holds when a call failed, an expected id is unaccounted for, or nothing was
          answered at all, so an empty sweep is never `NEW`
        - `REUSE` when some entry has provides at or above policy["reuse"]; `EXTEND` when some entry has
          provides from policy["floor"] up to policy["reuse"] and coverage at or above policy["coverage"]
        - `LOW_CONFIDENCE` holds when neither applies and some entry sits in the provides band or has
          coverage at or above policy["coverage"]; it is listed even beside other causes
        - any cause other than the one derived from the rule gives `UNCERTAIN_READ_SOURCE`; `NEW` needs at
          least one answered row and no cause
        - shortlist holds the causal rows (`REUSE` or `EXTEND` only) and every row with provides at or
          above policy["threshold"], cut to policy["shortlist"] with causal rows kept first
    """
    expected  = set( expected_ids )
    failed    = set( failed_ids )
    seen, dup = set(), set()
    for a in answers:
        if a[ "id" ] in seen: dup.add( a[ "id" ] )
        seen.add( a[ "id" ] )
    rows, malformed = [], []
    for a in answers:
        reason = "duplicate_id" if a[ "id" ] in dup else "unknown_id" if a[ "id" ] not in expected else malformed_reason_provides( a[ "provides" ], a[ "coverage" ], policy )
        if reason is not None:
            malformed.append( { "id": a[ "id" ], "reason": reason } ); continue
        rows.append( _provides_row( a ) )
    accounted = { r[ "id" ] for r in rows } | { m[ "id" ] for m in malformed } | failed
    missing   = sorted( expected - accounted )
    holds     = set( flags )
    if failed or missing:   holds.add( "CALL_FAILED" )
    if malformed:           holds.add( "MALFORMED_ANSWER" )
    if not rows and not holds.intersection( CAUSES[ :6 ] ): holds.add( "CALL_FAILED" )      # only the four pipeline flags and the two gaps count
    ordered  = _provides_order( rows )
    reuse    = [ r for r in ordered if r[ "provides" ] >= policy[ "reuse" ] ]
    banded   = [ r for r in ordered if policy[ "floor" ] <= r[ "provides" ] < policy[ "reuse" ] ]
    extend   = [ r for r in banded if r[ "coverage" ] >= policy[ "coverage" ] ]
    low      = not reuse and not extend and ( bool( banded ) or any( r[ "coverage" ] >= policy[ "coverage" ] for r in ordered ) )
    if low: holds.add( "LOW_CONFIDENCE" )
    causes   = [ c for c in CAUSES if c in holds ]
    gaps     = [ c for c in causes if c != "LOW_CONFIDENCE" ]
    if gaps or low:     verdict, causal = "UNCERTAIN_READ_SOURCE", []
    elif reuse:         verdict, causal = "REUSE", reuse
    elif extend:        verdict, causal = "EXTEND", extend
    else:               verdict, causal = "NEW", []
    pool = [ r for r in ordered if r in causal or r[ "provides" ] >= policy[ "threshold" ] ]
    return { "verdict"         : verdict,
             "cause"           : causes[ 0 ] if causes else None,
             "causes"          : causes,
             "shortlist"       : _cut_shortlist( causal, pool, policy[ "shortlist" ] ),
             "shortlist_total" : len( pool ),
             "nearest"         : ordered[ :policy[ "shortlist" ] ],
             "doubtful"        : banded[ :policy[ "shortlist" ] ],
             "malformed"       : malformed,
             "missing"         : missing }
