"""
Thin the cases a retrieval returned, before they vote.

Two rules, each asked for separately. A burst of retry copies counts once. No single question template
may take more than a set number of places. The retry rule is ask_family.classify_asks, not a copy of it.
"""

from cosa.agents.prediction_engine.ask_family import classify_asks, normalise_text
from cosa.utils.iso_timestamp import parse_iso

# Ratification states that carry a thumbs vote, which a dropped retry copy must not take with it.
VOTED_STATES = ( "approved", "rejected" )


def thin_candidates( similar_cases, limit, dedupe=False, template_cap=None ):
    """
    Drop retry copies and over-represented templates, then cut to the neighbour limit.

    Requires:
        - similar_cases is a list of ( similarity_pct, record ) pairs, strongest first, as find_similar returns
        - limit is a positive int; template_cap is None or a positive int
        - a record may carry question, category, response_type, owner_user_id, created_at and ratification_state

    Ensures:
        - returns at most limit pairs, in the order given
        - with dedupe, each retry group of classify_asks keeps one pair: the earliest voted one, else the earliest;
          the sender is the case's owner, and a case with no readable created_at never joins a group
        - with template_cap, at most that many pairs share one normalise_text( question ), the strongest first;
          a question that normalises to nothing is never capped

    Raises:
        - ValueError if limit or template_cap is below 1
    """
    if limit < 1 or ( template_cap is not None and template_cap < 1 ):
        raise ValueError( f"limit and template_cap must be at least 1, got {limit!r} and {template_cap!r}" )
    kept = _without_retry_copies( similar_cases ) if dedupe else list( similar_cases )
    if template_cap is not None:
        counts, capped = {}, []
        for pair in kept:
            template = normalise_text( pair[ 1 ].get( "question" ) )
            counts[ template ] = counts.get( template, 0 ) + 1
            if not template or counts[ template ] <= template_cap: capped.append( pair )
        kept = capped
    return kept[ :limit ]


def rank_with_category( same_category, any_category, category, boost, limit ):
    """
    Order two retrievals as one, a case of the asked category ranked as if it were nearer.

    Requires:
        - same_category and any_category are find_similar results, the first filtered to category and the second not
        - boost is a fraction of similarity; limit is a positive int

    Ensures:
        - returns at most limit pairs, one per record id, ordered by similarity plus the boost for the asked category
        - every similarity returned is the one find_similar gave: the boost orders and is never reported
        - a tie keeps the same-category retrieval first
        - the result is the top limit of all matching cases, because each retrieval was itself cut to the same limit
    """
    merged = {}
    for pair in list( same_category ) + list( any_category ):
        merged.setdefault( pair[ 1 ][ "id" ], pair )
    ordered = sorted( merged.values(), key=lambda pair: -( pair[ 0 ] + ( boost * 100.0 if pair[ 1 ].get( "category" ) == category else 0.0 ) ) )
    return ordered[ :limit ]


def _without_retry_copies( similar_cases ):
    """
    Keep one pair of each retry group.

    Requires:
        - similar_cases is as for thin_candidates

    Ensures:
        - returns the kept pairs in the order given, one per retry group plus every pair with no readable created_at
    """
    timed = [ ( position, parse_iso( record.get( "created_at" ) ) ) for position, ( _, record ) in enumerate( similar_cases ) ]
    timed = [ ( position, moment ) for position, moment in timed if moment is not None ]
    asks  = []
    for position, moment in timed:
        record = similar_cases[ position ][ 1 ]
        asks.append( { "response_type": record.get( "response_type" ), "category": record.get( "category" ), "title": "",
                       "message": record.get( "question" ) or "", "sender_id": record.get( "owner_user_id" ), "asked_at": moment } )
    groups = {}
    for ( position, moment ), info in zip( timed, classify_asks( asks ) ):
        unvoted = similar_cases[ position ][ 1 ].get( "ratification_state" ) not in VOTED_STATES
        groups.setdefault( info[ "retry_group" ], [] ).append( ( unvoted, moment, position ) )
    dropped = { position for members in groups.values() for _, _, position in sorted( members )[ 1: ] }
    return [ pair for position, pair in enumerate( similar_cases ) if position not in dropped ]
