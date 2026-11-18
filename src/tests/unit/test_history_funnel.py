"""
One family imports first: the inventory is reproduced, hashes agree, the funnel shrinks.

The rows are shaped like stored notifications; the real-data check is in the `local_data` file.
"""

import pytest

from cosa.agents.prediction_engine.history_funnel import OUTSIDE_WINDOW, format_funnel, prove_import, reproduce_inventory, yield_funnel

RECIPIENT = "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"

INVENTORY = """ notification_rows | response_required_rows | recipient_asks
--------------------+------------------------+----------------
                100 |                     20 |              4
(1 row)

 response_type | state     | asks | logged_asks
---------------+-----------+------+-------------
 yes_no        | responded |    3 |           0
 yes_no        | expired   |    1 |           0
(2 rows)

 month_utc  | response_type | asks
------------+---------------+------
 2026-11-01 | yes_no        |    4
(1 row)
"""


def raw( id, message, value=None, state="responded", created_at="2026-11-10T10:00:00Z", response_type="yes_no", title="Alpha" ):
    """One stored notification, built so a test names only what it varies."""
    return { "id": id, "recipient_id": RECIPIENT, "sender_id": "claude.code@lupin.deepily.ai#aaaa1111", "title": title, "message": message,
             "response_type": response_type, "state": state, "created_at": created_at, "thread_id": None, "job_id": None, "reply_to": None,
             "response_options": None, "response_value": value }


def answered( text, source="ui", user=RECIPIENT ):
    """A stored response_value in the common envelope."""
    return { "value": text, "source": source, "answered_by": { "method": "jwt", "user_id": user } if user else None }


ROWS = [
    raw( "a", "Q one?",   answered( "yes" ) ),
    raw( "b", "Q two?",   answered( "no" ), title="Bravo" ),
    raw( "c", "Q three?", answered( "yes" ), title="Charlie", created_at="2026-11-18T00:00:00Z" ),
    raw( "d", "Q four?",  None, state="expired", title="Delta", created_at="2026-11-18T01:00:00Z" ),
]


def test_the_asks_of_a_family_created_by_the_run_time_reproduce_the_inventory_by_state():
    got = reproduce_inventory( ROWS, INVENTORY, "2026-11-18T01:30:00Z", "yes_no" )
    assert got[ "matches" ] is True
    assert ( got[ "reproduced" ], got[ "inventory" ] ) == ( { "responded": 3, "expired": 1 }, { "responded": 3, "expired": 1 } )


def test_a_state_that_differs_is_named_with_both_counts():
    got = reproduce_inventory( ROWS, INVENTORY, "2026-11-18T23:00:00Z", "yes_no" )
    assert got[ "matches" ] is True
    short = reproduce_inventory( ROWS[ :3 ], INVENTORY, "2026-11-18T23:00:00Z", "yes_no" )
    assert ( short[ "matches" ], short[ "differences" ] ) == ( False, [ ( "expired", 0, 1 ) ] )


def test_rows_made_after_the_run_time_and_rows_of_another_family_are_not_counted():
    rows = ROWS + [ raw( "late", "Q late?", None, state="expired", created_at="2026-11-19T00:00:00Z" ), raw( "mc", "Pick", None, response_type="multiple_choice" ) ]
    assert reproduce_inventory( rows, INVENTORY, "2026-11-18T23:00:00Z", "yes_no" )[ "matches" ] is True


def test_a_family_the_inventory_does_not_hold_is_refused_by_name():
    with pytest.raises( ValueError, match="family 'open_ended'" ):
        reproduce_inventory( ROWS, INVENTORY, "2026-11-18T23:00:00Z", "open_ended" )


def test_the_funnel_drops_each_row_for_a_named_reason_and_never_grows():
    rows = ROWS + [ raw( "e", "Q one?", answered( "yes" ), created_at="2026-11-10T10:05:00Z" ),
                    raw( "f", "Q six?", answered( "yes", source="timeout_default" ), title="Foxtrot" ),
                    raw( "g", "Q seven?", answered( "perhaps" ), title="Golf" ),
                    raw( "h", "Q eight?", answered( "yes", user=None ), title="Hotel" ),
                    raw( "i", "Q nine?", answered( "yes" ), title="India" ),
                    raw( "j", "Q nine?", answered( "yes" ), title="India", created_at="2026-11-18T08:00:00Z" ) ]
    states = { "a": "reconstructed", "b": "ambiguous_only", "i": "reconstructed", "j": "reconstructed" }
    got    = { s[ "stage" ]: s for s in yield_funnel( rows, states, "yes_no" ) }
    assert [ s[ "count" ] for s in yield_funnel( rows, states, "yes_no" ) ] == [ 10, 9, 6, 5, 3, 2 ]
    assert got[ "distinct eligible asks" ][ "dropped" ] == { "retry copy of an earlier ask": 1 }
    assert got[ "usable answers" ][ "dropped" ] == { "unanswered": 1, "timeout default, no human label": 1, "answer could not be read": 1 }
    assert got[ "unambiguous typed labels" ][ "dropped" ] == { "actor not established: unknown_actor": 1 }
    assert got[ "reconstructable context" ][ "dropped" ] == { "before the context window": 1, "context ambiguous_only": 1 }
    assert got[ "independent families" ][ "dropped" ] == { "family already counted": 1 }


def test_the_funnel_counts_never_rise_and_each_drop_sums_to_the_difference():
    stages = yield_funnel( ROWS, { "a": "reconstructed" }, "yes_no" )
    for before, after in zip( stages, stages[ 1: ] ): assert after[ "count" ] == before[ "count" ] - sum( after[ "dropped" ].values() )


def test_an_ask_with_no_context_state_is_read_as_outside_the_window():
    assert OUTSIDE_WINDOW == "outside_window"
    stage = yield_funnel( [ raw( "a", "Q?", answered( "yes" ) ) ], {}, "yes_no" )[ 4 ]
    assert stage[ "dropped" ] == { "before the context window": 1 }


def test_a_family_is_proved_by_a_reproduced_inventory_and_equal_hashes_from_two_runs( tmp_path ):
    got = prove_import( ROWS, INVENTORY, "2026-11-18T23:00:00Z", "yes_no", { "a": "reconstructed" }, str( tmp_path ) )
    assert got[ "inventory" ][ "matches" ] is True and got[ "hashes_agree" ] is True
    assert got[ "funnel" ][ 0 ] == { "stage": "asks", "count": 4, "dropped": {} }
    assert ( tmp_path / "run-1" / "derived.jsonl" ).exists() and ( tmp_path / "run-2" / "originals.jsonl" ).exists()


def test_a_family_with_no_rows_cannot_be_proved( tmp_path ):
    with pytest.raises( ValueError, match="no original rows" ):
        prove_import( ROWS, INVENTORY, "2026-11-18T23:00:00Z", "open_ended", {}, str( tmp_path ) )


def test_the_printout_names_every_stage_and_reason():
    out = format_funnel( yield_funnel( ROWS, {}, "yes_no" ) )
    for needle in ( "asks", "usable answers", "independent families", "dropped", "before the context window" ): assert needle in out
