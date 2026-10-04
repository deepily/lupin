"""
Unit tests for the near-match quantity guard (row 1b3ec88f): `cosa.rest.v2.near_match_guard`.

Pure functions, no flow, no network. Each parametrized case names what it stands for.
"""

import pytest

from cosa.rest.v2.near_match_guard import quantities_differ, quantity_signature


@pytest.mark.parametrize( "text, expected", [
    ( "Convert 10 miles to kilometers",     [ ( "10", "mile" ) ] ),
    ( "How many miles is 10 kilometers?",   [ ( "10", "kilometer" ) ] ),
    ( "what is 2 + 2",                      [ ( "2", None ), ( "2", None ) ] ),
    ( "what is 2 plus 2",                   [ ( "2", "plus" ), ( "2", None ) ] ),
    ( "run 10km",                           [ ( "10", "km" ) ] ),
    ( "pay 1,000 dollars or 3.50 dollars",  [ ( "1000", "dollar" ), ( "3.5", "dollar" ) ] ),
    ( "10 .",                               [ ( "10", None ) ] ),
    ( "ends with a number 7",               [ ( "7", None ) ] ),
    ( "eat 3 berries and 2 glasses and 4 bus and 5 boxes and 6 lunches and 7 dishes and 8 plus 9 this", [ ( "3", "berry" ), ( "2", "glass" ), ( "4", "bus" ), ( "5", "box" ), ( "6", "lunch" ), ( "7", "dish" ), ( "8", "plus" ), ( "9", "this" ) ] ),
    ( "no numbers here",                    [] ),
    ( "",                                   [] ),
    ( "a 3,5 thing",                        [ ( "3,5", "thing" ) ] ),
] )
def test_quantity_signature( text, expected ):
    assert quantity_signature( text ) == expected


@pytest.mark.parametrize( "asked, stored, differ, why", [
    ( "Convert 10 miles to kilometers", "How many miles is 10 kilometers?", True,  "THE INCIDENT: same number, the 10 belongs to a different unit" ),
    ( "Convert 10 miles to kilometers", "What is 10 miles in kilometers?",  False, "same quantity, different wording" ),
    ( "Convert 10 miles to kilometers", "Convert 10 mile to kilometers",    False, "plural folded" ),
    ( "Convert 10 miles to kilometers", "Convert 15 miles to kilometers",   True,  "different number" ),
    ( "what is 2 + 2",                  "what is 2 plus 2",                 False, "an absent unit is compatible with any" ),
    ( "What is 10 plus 10",             "What is 10 plus 20",               True,  "second number differs" ),
    ( "go 10 then 20",                  "go 20 then 10",                    True,  "ORDER matters, not just the set" ),
    ( "10 miles",                       "10.0 miles",                       False, "one spelling per numeric value" ),
    ( "1,000 miles",                    "1000 miles",                       False, "grouping commas are not part of the value" ),
    ( "3,5 miles",                      "35 miles",                         True,  "a non-grouping comma is NOT silently merged" ),
    ( "5 dollars",                      "5 bucks",                          True,  "fails closed: a synonym unit is refused, costing one cache hit" ),
    ( "what is the capital of France",  "capital city of France",           False, "no numbers on either side" ),
    ( "what is 10 plus 10",             "what is the capital of France",    True,  "numbers on one side only" ),
] )
def test_quantities_differ( asked, stored, differ, why ):
    assert quantities_differ( asked, stored ) is differ, why
