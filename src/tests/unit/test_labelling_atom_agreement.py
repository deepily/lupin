#!/usr/bin/env python3
"""
atom_agreement: precision and recall of two readers, against hand-counted answers.

Venue: :7999-eligible / local, pure.
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.repo.labelling import atom_agreement as aa
from cosa.repo.labelling import errors as er

# Reference names 4 atoms, other names 5. Only "on staging" under i1 and "only if green" under i2 are shared.
REFERENCE = { "i1": [ "before the merge", "on staging" ], "i2": [ "only if green" ], "i3": [], "i4": [ "after 5pm", "after 5pm" ] }
OTHER     = { "i1": [ "on staging", "never on production" ], "i2": [ "only if green", "on staging" ], "i3": [ "ask first" ], "i4": [] }


def test_the_planted_case_gives_the_hand_counted_answer():
    assert aa.atom_agreement( REFERENCE, OTHER ) == {
        "items": 4, "reference_atoms": 4, "other_atoms": 5, "shared_atoms": 2,
        "precision": 0.4, "precision_reason": None, "recall": 0.5, "recall_reason": None,
        "only_reference": [ ( "i1", "before the merge" ), ( "i4", "after 5pm" ) ],
        "only_other": [ ( "i1", "never on production" ), ( "i2", "on staging" ), ( "i3", "ask first" ) ],
    }


def test_swapping_the_readers_swaps_precision_and_recall():
    got = aa.atom_agreement( OTHER, REFERENCE )
    assert ( got[ "precision" ], got[ "recall" ] ) == ( 0.5, 0.4 )


def test_no_shared_atom_is_zero_and_not_undefined():
    got = aa.atom_agreement( { "i1": [ "before" ] }, { "i1": [ "after" ] } )
    assert ( got[ "precision" ], got[ "recall" ], got[ "precision_reason" ], got[ "recall_reason" ] ) == ( 0.0, 0.0, None, None )


def test_an_empty_denominator_is_none_with_whose_atoms_are_missing():
    silent_other = aa.atom_agreement( { "i1": [ "before" ] }, { "i1": [] } )
    assert ( silent_other[ "precision" ], silent_other[ "precision_reason" ], silent_other[ "recall" ] ) == ( None, aa.NO_OTHER_ATOMS, 0.0 )
    silent_reference = aa.atom_agreement( { "i1": [] }, { "i1": [ "before" ] } )
    assert ( silent_reference[ "recall" ], silent_reference[ "recall_reason" ], silent_reference[ "precision" ] ) == ( None, aa.NO_REFERENCE_ATOMS, 0.0 )
    both = aa.atom_agreement( { "i1": [] }, { "i1": () } )
    assert ( both[ "precision" ], both[ "recall" ], both[ "precision_reason" ], both[ "recall_reason" ] ) == ( None, None, aa.NO_OTHER_ATOMS, aa.NO_REFERENCE_ATOMS )


@pytest.mark.parametrize( "reference, other, reason", [
    ( { "i1": [] },         { "i2": [] },     "different items" ),
    ( {},                   {},               "no items" ),
    ( { "i1": "before" },   { "i1": [] },     "non-blank strings" ),
    ( { "i1": [ "  " ] },   { "i1": [] },     "non-blank strings" ),
    ( { "i1": [] },         { "i1": [ 3 ] },  "non-blank strings" ),
] )
def test_unusable_labels_are_refused_by_name( reference, other, reason ):
    with pytest.raises( er.LabellingError, match=reason ) as caught: aa.atom_agreement( reference, other )
    assert caught.value.code == er.BAD_LABEL
