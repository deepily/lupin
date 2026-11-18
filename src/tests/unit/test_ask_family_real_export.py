"""
The real-data check for classify_asks (the `local_data` tier).

It reads Rick's 285 real asks from the main checkout's gitignored
`io/write-ups/online-preference-learning/`. In a worktree the folder is absent and the test skips
by name. The real run is made in the main checkout with `--require-local-data`.
"""

import collections
import json

import pytest

from cosa.agents.prediction_engine.ask_family import classify_asks, normalise_text
from cosa.utils.local_data_tier import require_local_file

EXPORT_FILE_NAME = "2026.11.17-recent-predictions-285.json"

pytestmark = pytest.mark.local_data


def _asks():
    """The export's asks, mapped to the fields classify_asks reads."""
    predictions = json.load( open( require_local_file( EXPORT_FILE_NAME ) ) )[ "predictions" ]
    return [ { "response_type": p[ "response_type" ], "category": p[ "category" ], "title": p[ "title" ], "message": p[ "question" ],
               "sender_id": p[ "asked_by" ][ "sender_id" ], "asked_at": p[ "asked_at" ] } for p in predictions ]


def test_the_285_real_asks_fall_into_263_families_and_281_retry_groups():
    got = classify_asks( _asks() )
    assert len( got ) == 285
    assert len( { g[ "family" ] for g in got } ) == 263
    assert sum( g[ "is_retry_copy" ] for g in got ) == 4
    assert len( { g[ "retry_group" ] for g in got } ) == 281


def test_every_real_ask_has_a_known_project_and_the_counts_are_these():
    got = classify_asks( _asks() )
    assert collections.Counter( g[ "project" ] for g in got ) == { "lupin": 205, "plan": 54, "lupin-mobile": 26 }


def test_no_real_ask_is_left_with_an_empty_family_title():
    assert [ g for g in classify_asks( _asks() ) if g[ "family" ][ 2 ] == "" ] == []


def test_the_fifty_character_title_cut_merges_no_distinct_messages_into_one_family():
    """148 of 285 titles are cut at 50 characters; no cut family holds two messages."""
    asks = _asks()
    got  = classify_asks( asks )
    messages = collections.defaultdict( set )
    for ask, keys in zip( asks, got ):
        messages[ keys[ "family" ] ].add( normalise_text( ask[ "message" ] ) )
    assert sum( len( a[ "title" ] ) == 50 for a in asks ) == 148
    cut_families = { keys[ "family" ] for ask, keys in zip( asks, got ) if len( ask[ "title" ] ) == 50 }
    assert [ f for f in cut_families if len( messages[ f ] ) > 1 ] == []


def test_three_families_hold_seven_different_messages_for_reasons_other_than_the_cut():
    asks = _asks()
    got  = classify_asks( asks )
    messages = collections.defaultdict( set )
    for ask, keys in zip( asks, got ):
        messages[ keys[ "family" ] ].add( normalise_text( ask[ "message" ] ) )
    merged = [ m for m in messages.values() if len( m ) > 1 ]
    assert ( len( merged ), sum( len( m ) for m in merged ) ) == ( 3, 7 )
