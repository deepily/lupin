"""
Rank fusion over ranked id lists.

Only the position in a list counts, never a score, so lists from unlike sources combine
without any scale. Ties break on id, and the top few ids of every list are never dropped.
"""
from cosa.repo.symindex.candidates.errors import CandidateError

FUSION_K           = 60
FUSION_DEPTH       = 512
FUSION_HEAD        = 5
SCORE_DIGITS       = 6
HEAD_EXCEEDS_LIMIT = "HEAD_EXCEEDS_LIMIT"


def fuse( lists, k=FUSION_K, depth=FUSION_DEPTH, head=FUSION_HEAD, limit=None ):
    """
    Fuse ranked lists into one order.

    Requires:
        - lists is a list of lists of ids, each best first
        - k and depth are positive integers, head is no larger than depth, limit is not negative

    Ensures:
        - a repeated id in one list counts once, at its first position
        - an id at 1-based position r in a list inside depth adds 1 / ( k + r )
        - the fused score is rounded to SCORE_DIGITS places before the sort
        - returns ids ordered by ( -fused score, id )
        - with a limit, returns at most limit ids: every id in the top head of some list, then the
          best of the rest, still in fused order
        - never reads a score from a list, so the result depends on order only

    Raises:
        - CandidateError HEAD_EXCEEDS_LIMIT when the top-head ids of all lists are more than limit
    """
    unique = [ list( dict.fromkeys( ranked ) ) for ranked in lists ]
    fused  = {}
    for ranked in unique:
        for position, doc_id in enumerate( ranked[ :depth ], start=1 ): fused[ doc_id ] = fused.get( doc_id, 0.0 ) + 1.0 / ( k + position )
    order = sorted( fused, key=lambda d: ( -round( fused[ d ], SCORE_DIGITS ), d ) )
    if limit is None: return order
    kept = set()
    for ranked in unique: kept.update( ranked[ :head ] )
    if len( kept ) > limit: raise CandidateError( HEAD_EXCEEDS_LIMIT, f"{len( kept )} head ids do not fit in {limit}" )
    for doc_id in order:
        if len( kept ) >= limit: break
        kept.add( doc_id )
    return [ d for d in order if d in kept ]
