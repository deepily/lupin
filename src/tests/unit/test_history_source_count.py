"""
The source count reads the baseline inventory tables and refuses totals that miss.

The fixture text is shaped like psql's aligned output. The real-output check is in the
`local_data` file beside this one.
"""

import pytest

from cosa.agents.prediction_engine.history_source_count import count_source_population, format_source_count, parse_psql_tables

TOTALS = """ notification_rows | response_required_rows | recipient_asks
--------------------+------------------------+----------------
                100 |                     20 |             10
(1 row)
"""

BY_STATE = """ response_type | state     | asks | logged_asks
---------------+-----------+------+-------------
 yes_no        | responded |    6 |           5
 yes_no        | expired   |    4 |           0
(2 rows)
"""

BY_MONTH = """ month_utc  | response_type | asks
------------+---------------+------
 2026-05-01 | yes_no        |    7
 2026-06-01 | yes_no        |    3
(2 rows)
"""

TEXT = "BEGIN\n" + TOTALS + "\n" + BY_STATE + "\n" + BY_MONTH + "\nROLLBACK\n"


def test_parse_psql_tables_returns_every_table_in_order_and_ignores_the_rest():
    tables = parse_psql_tables( TEXT )
    assert [ len( t ) for t in tables ] == [ 1, 2, 2 ]
    assert tables[ 1 ][ 0 ] == { "response_type": "yes_no", "state": "responded", "asks": "6", "logged_asks": "5" }


def test_text_with_no_table_gives_no_tables():
    assert parse_psql_tables( "BEGIN\nROLLBACK\n" ) == []


def test_the_counts_name_each_stage_and_each_cell():
    got = count_source_population( TEXT )
    assert [ ( stage, count ) for stage, count, _ in got[ "funnel" ] ] == [ ( "notification_rows", 100 ), ( "response_required_rows", 20 ), ( "recipient_asks", 10 ) ]
    assert got[ "by_type_state" ] == { ( "yes_no", "responded" ): 6, ( "yes_no", "expired" ): 4 }
    assert got[ "by_era" ] == { ( "2026-05-01", "yes_no" ): 7, ( "2026-06-01", "yes_no" ): 3 }


def test_every_stage_carries_a_named_reason():
    assert all( reason for _, _, reason in count_source_population( TEXT )[ "funnel" ] )


@pytest.mark.parametrize( "text, named", [
    ( "BEGIN\n" + BY_STATE + BY_MONTH,                          "totals table" ),
    ( TOTALS + BY_MONTH,                                        "type-by-state table" ),
    ( TOTALS + BY_STATE,                                        "month table" ),
    ( TEXT.replace( "|             10", "|            200" ),    "larger than" ),
    ( TEXT.replace( "|    6 |", "|    7 |" ),                   "type-by-state asks sum to 11" ),
    ( TEXT.replace( "|    7\n", "|    8\n" ),                   "month asks sum to 11" ),
] )
def test_a_missing_table_or_a_total_that_does_not_add_up_is_refused_by_name( text, named ):
    with pytest.raises( ValueError, match=named ):
        count_source_population( text )


def test_the_printout_carries_every_count():
    out = format_source_count( count_source_population( TEXT ) )
    for needle in ( "notification_rows", "100", "yes_no", "responded", "2026-05-01", "7" ):
        assert needle in out
