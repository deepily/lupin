"""
The last history step: prove one family imports before any other does.

For one response type it checks three things. The asks must reproduce the inventory's counts exactly.
The written dataset must pass its check twice with the same hashes.
The yield funnel must shrink stage by stage, with a named reason for every row it drops.
"""

from cosa.agents.prediction_engine.ask_family import classify_asks
from cosa.agents.prediction_engine.history_derive import asks_of, derive_dataset, write_dataset
from cosa.agents.prediction_engine.history_source_count import count_source_population
from cosa.agents.prediction_engine.history_uses import WEAK_ACTOR_TIERS
from cosa.utils.iso_timestamp import aware_moment

OUTSIDE_WINDOW = "outside_window"


def reproduce_inventory( raws, inventory_text, run_time, family ):
    """
    Check that one family's asks reproduce the inventory's counts by state.

    Requires:
        - raws is a list of notification rows as dicts with response_type, state and created_at
        - inventory_text is the inventory's psql output and run_time the moment it ran, as an ISO-8601 string
        - family is a response type

    Ensures:
        - Counts only the rows of that family created at or before run_time, by state
        - Returns { "matches", "reproduced", "inventory", "differences" }; matches is True only when every state agrees
        - differences lists ( state, reproduced, inventory ) for each state that does not

    Raises:
        - ValueError if the inventory holds no asks for the family
    """
    cut       = aware_moment( run_time )
    inventory = { state: n for ( kind, state ), n in count_source_population( inventory_text )[ "by_type_state" ].items() if kind == family }
    if not inventory: raise ValueError( f"the inventory holds no asks for family {family!r}" )
    reproduced = {}
    for raw in raws:
        if raw[ "response_type" ] == family and aware_moment( raw[ "created_at" ] ) <= cut: reproduced[ raw[ "state" ] ] = reproduced.get( raw[ "state" ], 0 ) + 1
    differences = [ ( state, reproduced.get( state, 0 ), inventory.get( state, 0 ) ) for state in sorted( set( reproduced ) | set( inventory ) )
                    if reproduced.get( state, 0 ) != inventory.get( state, 0 ) ]
    return { "matches": not differences, "reproduced": reproduced, "inventory": inventory, "differences": differences }


def yield_funnel( raws, context_states, family ):
    """
    Count one family's asks through each yield-funnel stage, naming every drop.

    Requires:
        - raws is a list of notification rows as dicts
        - context_states maps a notification id to its context state; an id it lacks is read as outside the context window
        - family is a response type

    Ensures:
        - Returns a list of { "stage", "count", "dropped" } in order, dropped mapping each reason to its row count
        - The stages are asks, distinct eligible asks, usable answers, unambiguous typed labels, reconstructable context and independent families
        - No stage holds more than the one before it, and the dropped counts sum to the difference
        - An ask enters a stage only by passing the stage before it
    """
    rows              = [ r for r in raws if r[ "response_type" ] == family ]
    derived, _        = derive_dataset( rows )
    keys              = classify_asks( asks_of( rows ) )
    stages            = [ { "stage": "asks", "count": len( rows ), "dropped": {} } ]
    alive             = list( zip( rows, derived, keys ) )

    def narrow( stage, reason_of ):
        nonlocal alive
        kept, dropped = [], {}
        for item in alive:
            reason = reason_of( item )
            if reason is None: kept.append( item )
            else: dropped[ reason ] = dropped.get( reason, 0 ) + 1
        alive = kept
        stages.append( { "stage": stage, "count": len( kept ), "dropped": dropped } )

    narrow( "distinct eligible asks", lambda i: "retry copy of an earlier ask" if i[ 1 ][ "is_retry_copy" ] else None )
    narrow( "usable answers", lambda i: _unusable( i[ 1 ] ) )
    narrow( "unambiguous typed labels", lambda i: f"actor not established: {i[ 1 ][ 'attribution_tier' ]}" if i[ 1 ][ "attribution_tier" ] in WEAK_ACTOR_TIERS else None )
    narrow( "reconstructable context", lambda i: _no_context( context_states.get( i[ 0 ][ "id" ], OUTSIDE_WINDOW ) ) )
    seen = set()
    def repeat_family( item ):
        key = item[ 2 ][ "family" ]
        if key in seen: return "family already counted"
        seen.add( key )
        return None
    narrow( "independent families", repeat_family )
    return stages


def _unusable( example ):
    """
    Name why a derived example is not a usable answer, or None when it is.

    Requires:
        - example is a derived example

    Ensures:
        - Returns "unanswered", "timeout default, no human label" or "answer could not be read" in that order of precedence, else None
    """
    if example[ "answer" ][ "kind" ] == "none": return "unanswered"
    if example[ "attribution_tier" ] == "timeout_default": return "timeout default, no human label"
    if example[ "answer" ][ "kind" ] == "unread": return "answer could not be read"
    return None


def _no_context( state ):
    """
    Name why a context state is not reconstructable, or None when it is.

    Requires:
        - state is a context state or OUTSIDE_WINDOW

    Ensures:
        - Returns None for "reconstructed", "before the context window" for OUTSIDE_WINDOW, else "context <state>"
    """
    if state == "reconstructed": return None
    return "before the context window" if state == OUTSIDE_WINDOW else f"context {state}"


def prove_import( raws, inventory_text, run_time, family, context_states, out_dir ):
    """
    Prove one family imports: inventory reproduced, dataset checked twice, funnel built.

    Requires:
        - raws, inventory_text, run_time, family and context_states as the functions above take them
        - out_dir is a directory path; the family is written to two folders beneath it

    Ensures:
        - Returns { "inventory", "hashes_agree", "funnel" }
        - The family's rows are written twice with write_dataset, each run passing verify_snapshot, and hashes_agree compares both hashes of both runs

    Raises:
        - ValueError if the family has no rows, or a written file fails its check
    """
    rows  = [ r for r in raws if r[ "response_type" ] == family ]
    first = write_dataset( rows, f"{out_dir}/run-1" )
    again = write_dataset( rows, f"{out_dir}/run-2" )
    return { "inventory"    : reproduce_inventory( raws, inventory_text, run_time, family ),
             "hashes_agree" : ( first[ "originals_sha256" ], first[ "derived_sha256" ] ) == ( again[ "originals_sha256" ], again[ "derived_sha256" ] ),
             "funnel"       : yield_funnel( raws, context_states, family ) }


def format_funnel( funnel ):
    """
    Print the funnel with each drop and its reason.

    Requires:
        - funnel is the list yield_funnel returns

    Ensures:
        - Returns one string, a line per stage and an indented line per reason
    """
    lines = []
    for stage in funnel:
        lines.append( f"{stage[ 'stage' ]:<28}{stage[ 'count' ]:>8,}" )
        for reason, n in sorted( stage[ "dropped" ].items() ): lines.append( f"    dropped {n:>6,}  {reason}" )
    return "\n".join( lines )
