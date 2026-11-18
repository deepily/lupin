"""
The fifth history step: recover each answered ask by its response family.

A yes, no or neither answer is read from its raw string, because a stored vote has already lost its
qualifier. A multiple-choice answer is checked against the options that were offered. A batch answer
is paired field by field with the prompt of each field. An open-ended answer is paired with its prompt
and its context state, and waits for review. Old scores are not touched: they keep their metric version.
"""

from cosa.agents.prediction_engine.history_derive import asks_of
from cosa.agents.prediction_engine.ask_family import classify_asks

STATUS_RECOVERED = "recovered"
STATUS_NO_OFFER  = "no_offer"
STATUS_PARTIAL   = "partial"
STATUS_UNREAD    = "unread"
STATUS_NO_ANSWER = "no_answer"

STATUSES = ( STATUS_RECOVERED, STATUS_PARTIAL, STATUS_NO_OFFER, STATUS_UNREAD, STATUS_NO_ANSWER )


def offered_fields( raw ):
    """
    Read the fields an ask offered, keyed by header.

    Requires:
        - raw is a notification row as a dict; response_options may be None

    Ensures:
        - Returns { header: { "question", "options", "multi_select" } } in the order offered
        - options is the list of option labels
        - Returns {} when the row has no offered questions
    """
    questions = ( raw.get( "response_options" ) or {} ).get( "questions" ) or []
    return { q.get( "header" ): { "question": q.get( "question" ), "multi_select": bool( q.get( "multi_select" ) ),
                                  "options": [ o.get( "label" ) for o in q.get( "options" ) or [] ] } for q in questions }


def recover_example( raw, example, context_state ):
    """
    Recover one answered ask in the shape of its response family.

    Requires:
        - raw is the notification row and example is its derived example
        - context_state is "reconstructed", "ambiguous_only" or "no_context"

    Ensures:
        - Returns { "notification_id", "response_type", "status", "recovered" }
        - status is one of the five status names and recovered holds what the family yields
        - yes_no yields { "stance", "qualified", "qualifier" }
        - multiple_choice and open_ended_batch yield { "fields": { header: { "prompt", "offered", "selected", "in_offer" } } }
          where in_offer is True when every pick is one of the offered options and False for a write-in
        - open_ended yields { "prompt", "response", "context_state", "reviewed": False }
        - A row with no stored answer is no_answer; an answer that could not be read is unread; a field answer
          with no offered schema is no_offer, and one that names a header nobody offered is partial
    """
    answer   = example[ "answer" ]
    response = example[ "response_type" ]
    out      = { "notification_id": example[ "notification_id" ], "response_type": response, "status": STATUS_NO_ANSWER, "recovered": None }
    if answer[ "kind" ] == "none":   return out
    if answer[ "kind" ] == "unread": return { **out, "status": STATUS_UNREAD, "recovered": { "text": answer[ "text" ] } }
    if answer[ "kind" ] == "stance":
        qualifier = answer[ "qualifier" ]
        return { **out, "status": STATUS_RECOVERED, "recovered": { "stance": answer[ "stance" ], "qualified": qualifier is not None, "qualifier": qualifier } }
    if answer[ "kind" ] == "text":
        return { **out, "status": STATUS_RECOVERED, "recovered": { "prompt": raw[ "message" ], "response": answer[ "text" ], "context_state": context_state, "reviewed": False } }
    offered = offered_fields( raw )
    if not offered: return { **out, "status": STATUS_NO_OFFER, "recovered": { "fields": { h: { "prompt": None, "offered": None, "selected": f[ "selected" ], "in_offer": None } for h, f in answer[ "fields" ].items() } } }
    fields = {}
    for header, picked in answer[ "fields" ].items():
        known           = offered.get( header )
        fields[ header ] = { "prompt"  : known[ "question" ] if known else None,
                             "offered" : known[ "options" ] if known else None,
                             "selected": picked[ "selected" ],
                             "in_offer": all( s in known[ "options" ] for s in picked[ "selected" ] ) if known else None }
    status = STATUS_RECOVERED if all( f[ "offered" ] is not None for f in fields.values() ) else STATUS_PARTIAL
    return { **out, "status": status, "recovered": { "fields": fields } }


def recover_by_family( raws, derived, context_states ):
    """
    Recover every example, grouped by response type and then by family.

    Requires:
        - raws and derived are parallel lists, derived being derive_dataset's output for raws
        - context_states maps each notification id to its context state

    Ensures:
        - Returns ( recovered, counts ), recovered in the order of raws
        - counts is { response_type: { "rows", "statuses": { status: n }, "families": { family: { "rows", "statuses" } } } }
        - Every status name is a key of each statuses dict, 0 when none
        - Every row is counted once, so each response type's statuses sum to its rows

    Raises:
        - ValueError when raws and derived differ in length
        - KeyError naming the notification id when an example has no context state
    """
    if len( raws ) != len( derived ): raise ValueError( f"raws has {len( raws )} rows but derived has {len( derived )}" )
    families  = classify_asks( asks_of( raws ) )
    recovered = []
    counts    = {}
    for raw, example, group in zip( raws, derived, families ):
        row = recover_example( raw, example, context_states[ example[ "notification_id" ] ] )
        recovered.append( row )
        kind = counts.setdefault( row[ "response_type" ], { "rows": 0, "statuses": { s: 0 for s in STATUSES }, "families": {} } )
        fam  = kind[ "families" ].setdefault( group[ "family" ][ 2 ], { "rows": 0, "statuses": { s: 0 for s in STATUSES } } )
        for bucket in ( kind, fam ):
            bucket[ "rows" ] += 1
            bucket[ "statuses" ][ row[ "status" ] ] += 1
    return recovered, counts
