"""
classify_asks gives each ask its family, its retry group and its project.

Each case names the rule it pins. The retry window is a fixed span from the first ask of a group,
so a chain of retries cannot grow it without limit.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.ask_family import RETRY_WINDOW, classify_asks, normalise_text

T0 = datetime( 2026, 11, 4, 1, 0, 0, tzinfo=timezone.utc )


def ask( minutes=0, message="Approve the fix row?", title="Approve the fix", sender="claude.code@lupin.deepily.ai#aaaa1111",
         response_type="yes_no", category="workflow", seconds=0 ):
    """One ask, built so a test names only what it varies."""
    return { "response_type": response_type, "category": category, "title": title, "message": message,
             "sender_id": sender, "asked_at": T0 + timedelta( minutes=minutes, seconds=seconds ) }


@pytest.mark.parametrize( "text, expected", [
    ( "Approve fix row 4e8b56e0 in /src/cosa/x.py \"quoted\" 12 times", "approve fix row in times" ),
    ( "  Just  one:\n WILL you click ",                                 "just one: will you click" ),
    ( "Row a8b6f06b31411b9d done",                                      "row done" ),
    ( "id 00000000-0000-4000-8000-000000001001 gone",                    "id gone" ),
    ( "keep ‘curly’ and 'single' and `ticks`",                          "keep ‘curly’ and and" ),
    ( "say “hello there” now",                                          "say now" ),
    ( "feature face decade",                                            "feature face decade" ),
    ( "see ~/notes/a.md and ./b/c",                                     "see and" ),
    ( "",                                                               "" ),
    ( None,                                                             "" ),
    ( "42 /tmp/x \"y\"",                                                "" ),
] )
def test_normalise_text_keeps_the_words_and_drops_the_specifics( text, expected ):
    assert normalise_text( text ) == expected


def test_the_family_is_response_type_category_and_the_normalised_title():
    got = classify_asks( [ ask( title="Approve fix row 77 \"x\"" ) ] )[ 0 ]
    assert got[ "family" ] == ( "yes_no", "workflow", "approve fix row" )


def test_two_asks_that_differ_only_in_specifics_share_a_family():
    a, b = classify_asks( [ ask( title="Approve row 12" ), ask( minutes=60, title="Approve row 99", message="other" ) ] )
    assert a[ "family" ] == b[ "family" ]


def test_a_different_category_or_response_type_is_a_different_family():
    base, cat, rtype = classify_asks( [ ask(), ask( category="other" ), ask( response_type="multiple_choice" ) ] )
    assert len( { base[ "family" ], cat[ "family" ], rtype[ "family" ] } ) == 3


def test_an_empty_title_falls_back_to_the_first_line_of_the_message():
    got = classify_asks( [ ask( title="", message="Pick a venue 7\nsecond line" ) ] )[ 0 ]
    assert got[ "family" ][ 2 ] == "pick a venue"


def test_a_missing_title_and_message_gives_an_empty_family_title():
    got = classify_asks( [ ask( title=None, message=None ) ] )[ 0 ]
    assert got[ "family" ][ 2 ] == ""


@pytest.mark.parametrize( "sender, project", [
    ( "claude.code@lupin.deepily.ai#8f3a2b1c", "lupin" ),
    ( "claude.code@lupin.deepily.ai",          "lupin" ),
    ( "claude.code@lupin-mobile.deepily.ai#b", "lupin-mobile" ),
    ( None,                                    "unknown" ),
    ( "",                                      "unknown" ),
    ( "no-domain-here",                        "unknown" ),
] )
def test_the_project_is_the_first_label_of_the_senders_domain( sender, project ):
    assert classify_asks( [ ask( sender=sender ) ] )[ 0 ][ "project" ] == project


def test_a_retry_inside_ten_minutes_is_a_copy_of_the_first_ask():
    first, copy = classify_asks( [ ask(), ask( minutes=3 ) ] )
    assert ( first[ "is_retry_copy" ], copy[ "is_retry_copy" ], copy[ "retry_group" ] ) == ( False, True, 0 )


def test_the_window_edge_is_inclusive_and_a_second_past_it_starts_a_new_group():
    _, edge, past = classify_asks( [ ask(), ask( minutes=10 ), ask( minutes=10, seconds=1, message="Approve the fix row?" ) ] )
    assert ( edge[ "is_retry_copy" ], past[ "is_retry_copy" ], past[ "retry_group" ] ) == ( True, False, 2 )


def test_the_window_runs_from_the_first_ask_so_a_chain_of_retries_cannot_stretch_it():
    a, b, c = classify_asks( [ ask(), ask( minutes=8 ), ask( minutes=16 ) ] )
    assert [ a[ "is_retry_copy" ], b[ "is_retry_copy" ], c[ "is_retry_copy" ] ] == [ False, True, False ]
    assert c[ "retry_group" ] == 2


def test_another_sender_or_another_message_is_not_a_copy():
    base, other_sender, other_message = classify_asks( [ ask(), ask( minutes=1, sender="claude.code@lupin.deepily.ai#bbbb2222" ), ask( minutes=1, message="Something else entirely" ) ] )
    assert [ other_sender[ "is_retry_copy" ], other_message[ "is_retry_copy" ] ] == [ False, False ]


def test_messages_that_differ_only_in_specifics_are_copies():
    _, copy = classify_asks( [ ask( message="Approve fix row 12?" ), ask( minutes=1, message="Approve fix row 13?" ) ] )
    assert copy[ "is_retry_copy" ] is True


def test_asks_with_no_sender_group_together_and_stay_apart_from_a_known_sender():
    a, b, c = classify_asks( [ ask( sender=None ), ask( minutes=1, sender=None ), ask( minutes=2 ) ] )
    assert ( b[ "is_retry_copy" ], c[ "is_retry_copy" ] ) == ( True, False )


def test_a_message_that_normalises_to_nothing_never_joins_a_group():
    a, b = classify_asks( [ ask( message="42" ), ask( minutes=1, message="42" ) ] )
    assert ( a[ "is_retry_copy" ], b[ "is_retry_copy" ] ) == ( False, False )


def test_the_result_is_in_input_order_whatever_the_time_order():
    later, earlier = classify_asks( [ ask( minutes=5 ), ask() ] )
    assert ( earlier[ "is_retry_copy" ], later[ "is_retry_copy" ], later[ "retry_group" ] ) == ( False, True, 1 )


def test_equal_times_are_taken_in_input_order():
    first, second = classify_asks( [ ask(), ask() ] )
    assert ( first[ "is_retry_copy" ], second[ "retry_group" ] ) == ( False, 0 )


def test_asked_at_may_be_an_iso_string_with_z_or_a_naive_datetime_read_as_utc():
    rows = [ ask(), ask( minutes=1 ), ask( minutes=2 ) ]
    rows[ 1 ][ "asked_at" ] = ( T0 + timedelta( minutes=1 ) ).isoformat().replace( "+00:00", "Z" )
    rows[ 2 ][ "asked_at" ] = ( T0 + timedelta( minutes=2 ) ).replace( tzinfo=None )
    assert [ r[ "is_retry_copy" ] for r in classify_asks( rows ) ] == [ False, True, True ]


@pytest.mark.parametrize( "bad", [ None, 5, [ "2026-11-04" ], "not a time", "" ] )
def test_an_asked_at_that_is_not_a_time_is_refused_by_name( bad ):
    row = ask()
    row[ "asked_at" ] = bad
    with pytest.raises( ValueError, match="asked_at" ):
        classify_asks( [ row ] )


def test_no_asks_give_no_result():
    assert classify_asks( [] ) == []


def test_the_retry_window_is_ten_minutes():
    assert RETRY_WINDOW == timedelta( minutes=10 )
