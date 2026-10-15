"""
Rank fusion over ranked id lists.

Only the position in a list counts, never a score, so lists from unlike sources combine
without any scale. Ties break on id, and the top few ids of every list are never dropped.
"""

FUSION_K     = 60
FUSION_DEPTH = 512
FUSION_HEAD  = 5
SCORE_DIGITS = 6


def fuse( lists, k=FUSION_K, depth=FUSION_DEPTH, head=FUSION_HEAD, limit=None ):
    """
    Fuse ranked lists into one order.

    Requires:
        - lists is a list of lists of ids, each best first, without repeats
        - k and depth are positive integers, head is no larger than depth, limit is not negative

    Ensures:
        - an id at 1-based position r in a list inside depth adds 1 / ( k + r )
        - the fused score is rounded to SCORE_DIGITS places before the sort
        - returns ids ordered by ( -fused score, id )
        - with a limit, returns the first limit ids plus any id that is in the top head of some list
          and fell outside them, still in fused order
        - never reads a score from a list, so the result depends on order only
    """
    fused = {}
    for ranked in lists:
        for position, doc_id in enumerate( ranked[ :depth ], start=1 ): fused[ doc_id ] = fused.get( doc_id, 0.0 ) + 1.0 / ( k + position )
    order = sorted( fused, key=lambda d: ( -round( fused[ d ], SCORE_DIGITS ), d ) )
    if limit is None: return order
    kept = set( order[ :limit ] )
    for ranked in lists: kept.update( ranked[ :head ] )
    return [ d for d in order if d in kept ]
