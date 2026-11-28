"""
The principle code on a captured slice of a real store, against the old code's answers.

The slice is cut from replay run 2's store. It holds the principles nearest to 12 cards.
Their evidence rows and each card's cosine order among them come with it.
Ids, session names and conditions are renamed, and no statement text is held.
The expected values are what the code of commit 1b3cd8da9 said at capture time.
That was before status derivation was made linear and on-demand.
The whole store is compared by src/scripts/check_principle_store_speed.py.
"""

import json

import pytest

import cosa.utils.util as cu
from cosa.agents.prediction_engine import principle_retrieval, principle_status
from tests.helpers.principle_store_slice import observe, slice_session

SLICE = cu.get_project_root() + "/src/tests/fixtures/principle_store_speed/run2-slice.json"


@pytest.fixture( scope="module" )
def captured():
    """Give the slice and what today's code says about each of its cards."""
    with open( SLICE, encoding="utf-8" ) as handle: data = json.load( handle )
    with slice_session( data ) as session: seen = observe( data, session, principle_retrieval, principle_status )
    return data, seen


def test_the_slice_can_tell_the_standings_apart( captured ):
    """The slice holds 12 cards, three standings and cards that keep five principles."""
    data, _  = captured
    standing = { s[ 0 ] for card in data[ "cards" ] for s in card[ "expected" ][ "standings" ].values() }
    assert len( data[ "cards" ] ) == 12
    assert standing == { "hypothesis", "established", "contested" }
    assert sum( len( card[ "expected" ][ "kept" ] ) == 5 for card in data[ "cards" ] ) >= 10


def test_every_card_keeps_what_the_old_code_kept( captured ):
    """The same principles, in the same order, with the same similarity, status and conditions."""
    data, seen = captured
    for card, got in zip( data[ "cards" ], seen, strict=True ):
        for name in ( "kept", "available", "short" ):
            assert got[ name ] == card[ "expected" ][ name ], f"{name} at {card[ 'asked_at' ]}"


def test_every_card_gives_every_principle_the_old_standing( captured ):
    """Every principle's standing at every card's moment is the old one."""
    data, seen = captured
    for card, got in zip( data[ "cards" ], seen, strict=True ):
        assert got[ "standings" ] == card[ "expected" ][ "standings" ], f"standings at {card[ 'asked_at' ]}"
