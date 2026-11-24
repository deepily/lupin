"""
The voice-card bridge: batches of 20 out, spoken answers back.
"""
import itertools
import json

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import voice_batches as vb

START = "2026-12-01T09:00:00-05:00"


def card( n, **over ):
    """Return an answer_meaning_card item."""
    payload = { "card_text": f"Question {n}?", "options": [ "A", "B" ], "recommendation": "A", "answer": "yes", "stance_class": "yes", **over }
    return it.make_item( "answer_meaning_card", f"card-{n:03d}", payload )


def packet( blind=0, disputes=0 ):
    """Return a packet of that many blind cards and dispute cards, with distinct ids."""
    return { "name": "gold-1", "blind": [ card( n ) for n in range( blind ) ], "disputes": [ card( 1000 + n ) for n in range( disputes ) ] }


def code_of( fn, *args, **kw ):
    """Return the code of the LabellingError that fn raises."""
    with pytest.raises( er.LabellingError ) as e: fn( *args, **kw )
    return e.value.code


def test_61_cards_give_four_batches_of_20_20_20_1_and_no_card_twice():
    batches = vb.voice_batches( packet( blind=61 ), "s1", START )
    assert [ len( b[ "item_ids" ] ) for b in batches ] == [ 20, 20, 20, 1 ]
    flat = list( itertools.chain.from_iterable( b[ "item_ids" ] for b in batches ) )
    assert len( flat ) == 61 and len( set( flat ) ) == 61 and set( flat ) == { f"card-{n:03d}" for n in range( 61 ) }


def test_blind_and_dispute_cards_never_share_a_batch_and_blind_come_first():
    batches = vb.voice_batches( packet( blind=25, disputes=21 ), "s1", START )
    assert [ ( b[ "kind" ], len( b[ "item_ids" ] ) ) for b in batches ] == [ ( "blind", 20 ), ( "blind", 5 ), ( "dispute", 20 ), ( "dispute", 1 ) ]
    for b in batches: assert all( ( i.startswith( "card-1" ) and int( i[ 5: ] ) >= 1000 ) == ( b[ "kind" ] == "dispute" ) for i in b[ "item_ids" ] )


def test_the_same_packet_and_seed_give_the_same_batches_whatever_the_input_order_and_a_new_seed_changes_them():
    p = packet( blind=45, disputes=3 )
    shuffled = { "name": p[ "name" ], "blind": list( reversed( p[ "blind" ] ) ), "disputes": list( reversed( p[ "disputes" ] ) ) }
    a = vb.voice_batches( p, "s1", START )
    assert a == vb.voice_batches( shuffled, "s1", START )
    assert [ b[ "item_ids" ] for b in a ] != [ b[ "item_ids" ] for b in vb.voice_batches( p, "s2", START ) ]
    assert [ b[ "batch_id" ] for b in a ] == [ vb.batch_id( "gold-1", "s1", k ) for k in range( len( a ) ) ] and len( a[ 0 ][ "batch_id" ] ) == 12
    assert len( { b[ "batch_id" ] for b in a } ) == len( a )


def test_the_row_spec_names_the_epic_the_batch_and_a_chase_a_day_apart():
    batches = vb.voice_batches( packet( blind=41 ), "s1", START )
    specs = [ b[ "row_spec" ] for b in batches ]
    assert [ s[ "next_chase_ts" ] for s in specs ] == [ "2026-12-01T09:00:00-05:00", "2026-12-02T09:00:00-05:00", "2026-12-03T09:00:00-05:00" ]
    assert all( s[ "correlation_key" ] == "epic:answer-signal-pipeline" and s[ "batch_id" ] == b[ "batch_id" ] and b[ "batch_id" ] in s[ "title" ] for s, b in zip( specs, batches ) )
    assert "batch 2 of 3" in specs[ 1 ][ "title" ] and "(blind, 1 cards)" in specs[ 2 ][ "title" ]
    assert vb.voice_batches( packet( blind=21 ), "s1", "2026-12-01T09:00:00", chase_days=3 )[ 1 ][ "row_spec" ][ "next_chase_ts" ] == "2026-12-04T09:00:00+00:00"


def test_the_spoken_text_is_short_and_the_card_texts_and_options_are_in_the_abstract_only():
    b = vb.voice_batches( packet( blind=20 ), "s1", START )[ 0 ]
    assert b[ "spoken" ] == "I have 20 questions for you." and len( b[ "spoken" ] ) < 400
    assert len( b[ "questions" ] ) == 20 and all( set( q ) == { "header", "question" } for q in b[ "questions" ] )
    assert all( "Question" not in q[ "question" ] and "options" not in q[ "question" ] for q in b[ "questions" ] )
    assert all( any( f"Question {n}?" in line for line in b[ "abstract" ].splitlines() ) for n in range( 20 ) )
    assert "options: A; B" in b[ "abstract" ] and "recommended: A" in b[ "abstract" ] and "answer: yes" in b[ "abstract" ] and "expands_recommendation" in b[ "abstract" ]


def test_a_card_with_no_options_and_no_recommendation_says_so_in_the_abstract():
    b = vb.voice_batches( { "name": "g", "blind": [ card( 1, options=[], recommendation=None, stance_class="none" ) ], "disputes": [] }, "s", START )[ 0 ]
    assert "options:" not in b[ "abstract" ] and "recommended: none" in b[ "abstract" ] and "(none)" in b[ "abstract" ]


def test_a_forecast_a_reader_label_or_a_labeller_label_is_refused_and_never_reaches_the_abstract():
    for extra in ( "forecast", "reader_label", "labeller_label" ):
        bad = card( 1 )
        bad[ "payload" ][ extra ] = "leaked-value"
        assert code_of( vb.voice_batches, { "name": "g", "blind": [ bad ], "disputes": [] }, "s", START ) == "PACKET_LEAK"
    top = card( 1 )
    top[ "forecast" ] = "leaked-value"
    assert code_of( vb.voice_batches, { "name": "g", "blind": [], "disputes": [ top ] }, "s", START ) == "PACKET_LEAK"
    clean = vb.voice_batches( packet( blind=3 ), "s", START )[ 0 ]
    assert "leaked-value" not in json.dumps( clean )


def test_other_item_types_repeated_ids_and_bad_arguments_are_refused():
    pair = it.make_item( "semdup_pair", "p-1", { "a": "def a(): pass", "b": "def b(): pass" } )
    assert code_of( vb.voice_batches, { "name": "g", "blind": [ pair ], "disputes": [] }, "s", START ) == "BAD_ITEM"
    assert code_of( vb.voice_batches, { "name": "g", "blind": [ card( 1 ) ], "disputes": [ card( 1 ) ] }, "s", START ) == "BAD_ITEM"
    for size in ( 0, -1, 2.5, True, "20" ): assert code_of( vb.voice_batches, packet( blind=3 ), "s", START, size=size ) == "BAD_ITEM"
    assert code_of( vb.voice_batches, packet( blind=3 ), "s", "next tuesday" ) == "BAD_ITEM"


def test_an_empty_packet_gives_no_batches():
    assert vb.voice_batches( packet(), "s", START ) == []


def test_a_long_spoken_text_is_refused( monkeypatch ):
    monkeypatch.setattr( vb, "format_open_ended_batch_for_tts", lambda questions: "x" * 400 )
    assert code_of( vb.voice_batches, packet( blind=2 ), "s", START ) == "BAD_ITEM"
    monkeypatch.setattr( vb, "format_open_ended_batch_for_tts", lambda questions: "x" * 399 )
    assert len( vb.voice_batches( packet( blind=2 ), "s", START )[ 0 ][ "spoken" ] ) == 399


def test_short_ids_are_unique_within_a_batch_and_a_forced_collision_lengthens_them():
    seen = {}
    for n in itertools.count():
        name = f"clash-{n}"
        key  = vb.short_ids( [ name ] )[ name ]
        if key in seen: break
        seen[ key ] = name
    pair = [ seen[ key ], name ]
    ids  = vb.short_ids( pair )
    assert len( ids[ pair[ 0 ] ] ) == len( ids[ pair[ 1 ] ] ) > vb.MIN_ID_LENGTH and ids[ pair[ 0 ] ] != ids[ pair[ 1 ] ]
    assert all( len( v ) == vb.MIN_ID_LENGTH for v in vb.short_ids( [ "a", "b" ] ).values() )
    batch = vb.voice_batches( { "name": "g", "blind": [ card( 1 ), card( 2 ) ], "disputes": [] }, "s", START )[ 0 ]
    assert len( set( batch[ "headers" ] ) ) == 2 and set( batch[ "headers" ].values() ) == { "card-001", "card-002" }
    assert [ q[ "header" ] for q in batch[ "questions" ] ] == list( batch[ "headers" ] )


def test_every_relation_and_spoken_form_maps_to_its_value():
    batch = vb.voice_batches( packet( blind=len( pk.ANSWER_LABELS ) ), "s", START )[ 0 ]
    headers = list( batch[ "headers" ] )
    reply = { h: label for h, label in zip( headers, pk.ANSWER_LABELS ) }
    got = vb.read_answers( batch, reply )
    assert [ x[ "relation" ] for x in got[ "labels" ] ] == list( pk.ANSWER_LABELS ) and got[ "unlabelled" ] == [] and got[ "unmatched" ] == []
    assert [ x[ "item_id" ] for x in got[ "labels" ] ] == [ batch[ "headers" ][ h ] for h in headers ]
    for spoken, value in ( ( "Expands on the recommendation.", "expands_recommendation" ), ( "expands on the other option", "expands_other_option" ),
                           ( "  Re-frame ", "re_frame" ), ( "reframe", "re_frame" ), ( "AGREES!", "agrees" ), ( "declines", "declines_or_defers" ), ( "No comment", "no_comment" ) ):
        one = vb.voice_batches( packet( blind=1 ), "s", START )[ 0 ]
        assert vb.read_answers( one, { next( iter( one[ "headers" ] ) ): spoken } )[ "labels" ][ 0 ][ "relation" ] == value
    assert set( vb.SPOKEN.values() ) == set( pk.ANSWER_LABELS )


def test_a_garbled_missing_blank_or_non_text_answer_stays_unlabelled_and_is_listed():
    batch = vb.voice_batches( packet( blind=5 ), "s", START )[ 0 ]
    h = list( batch[ "headers" ] )
    got = vb.read_answers( batch, { h[ 0 ]: "agrees", h[ 1 ]: "uhh maybe sort of", h[ 2 ]: "   ", h[ 3 ]: None } )
    assert [ x[ "header" ] for x in got[ "labels" ] ] == [ h[ 0 ] ]
    assert [ ( x[ "header" ], x[ "text" ] ) for x in got[ "unlabelled" ] ] == [ ( h[ 1 ], "uhh maybe sort of" ), ( h[ 2 ], "   " ), ( h[ 3 ], None ), ( h[ 4 ], None ) ]
    assert len( got[ "labels" ] ) + len( got[ "unlabelled" ] ) == 5


def test_a_reply_cut_short_labels_only_what_it_answered_and_an_unknown_header_is_listed_not_dropped():
    batch = vb.voice_batches( packet( blind=3 ), "s", START )[ 0 ]
    h = list( batch[ "headers" ] )
    got = vb.read_answers( batch, { h[ 0 ]: "support", "zzzz": "agrees", "aaaa": "agrees" } )
    assert [ x[ "relation" ] for x in got[ "labels" ] ] == [ "support" ] and len( got[ "unlabelled" ] ) == 2
    assert got[ "unmatched" ] == [ "aaaa", "zzzz" ]
    assert vb.read_answers( batch, {} ) == { "labels": [], "unlabelled": [ { "item_id": batch[ "headers" ][ x ], "header": x, "text": None } for x in h ], "unmatched": [] }
