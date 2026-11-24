"""
Census guard: every labelling item type has a validator that accepts a sample of it.

A new type added to items.TYPES must come with a sample here, or this file reddens.
"""
import pytest

from cosa.repo.labelling import items as it

SAMPLES = {
    "need_key"            : { "need": "A function that adds.", "key_sources": [ "def f(): pass" ] },
    "semdup_pair"         : { "a": "def a(): pass", "b": "def b(): pass" },
    "answer_meaning_card" : { "card_text": "Merge now?", "options": [], "recommendation": None, "answer": "yes", "stance_class": "yes" },
}


def test_every_item_type_has_a_sample_and_every_sample_a_type():
    assert set( SAMPLES ) == set( it.TYPES ) and len( it.TYPES ) == 3


@pytest.mark.parametrize( "kind", it.TYPES )
def test_every_item_type_has_a_validator_that_accepts_its_sample_and_refuses_an_empty_payload( kind ):
    assert it.make_item( kind, "x-1", SAMPLES[ kind ] )[ "type" ] == kind
    with pytest.raises( Exception ) as e: it.make_item( kind, "x-2", {} )
    assert e.value.code == "BAD_ITEM"
