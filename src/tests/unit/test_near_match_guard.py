"""
Unit tests for the near-match quantity guard (row 1b3ec88f): `cosa.rest.v2.near_match_guard`.

Pure functions, no flow, no network. Each parametrized case names what it stands for.
"""

import pytest

from cosa.rest.v2.near_match_guard import has_number, quantities_differ, quantity_tokens


@pytest.mark.parametrize( "text, expected", [
    ( "Convert 10 miles to kilometers",              [ "convert", "10", "mile", "kilometer" ] ),
    ( "How many miles is 10 kilometers?",            [ "mile", "10", "kilometer" ] ),
    ( "Convert 100 degrees fahrenheit to celsius",   [ "convert", "100", "degree", "fahrenheit", "celsius" ] ),
    ( "Uh... what\u2019s 253 plus, uh, 147?",           [ "253", "plus", "147" ] ),
    ( "what is 2 + 2",                               [ "2", "plus", "2" ] ),
    ( "5-3",                                         [ "5", "minus", "3" ] ),
    ( "5 - 3",                                       [ "5", "minus", "3" ] ),
    ( "a 45-degree angle",                           [ "45", "degree", "angle" ] ),
    ( "couch-to-5K plan",                            [ "couch", "5", "k", "plan" ] ),
    ( "dash - alone and trailing -",                 [ "dash", "trailing" ] ),
    ( "what is -5 plus 3",                           [ "-5", "plus", "3" ] ),
    ( "what is \u22125 plus 3",                      [ "-5", "plus", "3" ] ),
    ( "add .5 cups of flour",                        [ "add", "0.5", "cup", "flour" ] ),
    ( "pay 1,000 dollars or 3.50 dollars",           [ "pay", "1000", "dollar", "3.5", "dollar" ] ),
    ( "interest at 7% on $5,000",                    [ "interest", "7", "percent", "dollar", "5000" ] ),
    ( "3 \u00d7 4 \u00f7 2 * 1 / 1 = 6",             [ "3", "times", "4", "divided", "2", "times", "1", "divided", "1", "equal", "6" ] ),
    ( "a 3,5 thing",                                 [ "3", "5", "thing" ] ),
    ( "-0 and 0.0",                                  [ "0", "0" ] ),
    ( "eat berries, glasses, boxes, lunches, dishes, plus, this, bus", [ "eat", "berry", "glass", "box", "lunch", "dish", "plus", "bus" ] ),
    ( "it\u2019s you\u2019re we'll I'd they've I'm don't",     [ "don" ] ),
    ( "hmmm ummm uhhh errr ahh ehh ohh",             [] ),
    ( "no numbers here",                             [ "number" ] ),
    ( "",                                            [] ),
] )
def test_quantity_tokens( text, expected ):
    assert quantity_tokens( text ) == expected


@pytest.mark.parametrize( "text, expected", [
    ( "10 miles", True ), ( "-5", True ), ( ".5", True ), ( "1,000", True ), ( "no digits", False ), ( "", False ),
] )
def test_has_number( text, expected ):
    assert has_number( text ) is expected


@pytest.mark.parametrize( "asked, stored, differ, why", [
    ( "Convert 10 miles to kilometers",    "How many miles is 10 kilometers?",   True,  "THE INCIDENT: same number, the 10 belongs to a different unit" ),
    ( "Convert 10 miles to kilometers",    "Convert 10 mile to kilometers",      False, "plural folded" ),
    ( "Convert 10 miles to kilometers",    "Convert 15 miles to kilometers",     True,  "different number" ),
    ( "what is 2 + 2",                     "what is 2 plus 2",                   False, "a symbol and its word are the same" ),
    ( "what is 5 - 3",                     "what is 5 + 3",                      True,  "different operator" ),
    ( "What is 10 plus 10",                "What is 10 plus 20",                 True,  "second number differs" ),
    ( "go 10 then 20",                     "go 20 then 10",                      True,  "ORDER matters, not just the set" ),
    ( "10 miles",                          "10.0 miles",                         False, "one spelling per numeric value" ),
    ( "1,000 miles",                       "1000 miles",                         False, "grouping commas are not part of the value" ),
    ( "3,5 miles",                         "35 miles",                           True,  "a non-grouping comma is NOT silently merged" ),
    ( "5 dollars",                         "5 bucks",                            True,  "fails closed: a synonym is refused, costing one cache hit" ),
    ( "what is the capital of France",     "capital city of France",             False, "no numbers on either side: the guard is silent" ),
    ( "what is 10 plus 10",                "what is the capital of France",      True,  "numbers on one side only" ),
    ( "What is 253 plus 147?",             "Uh... what\u2019s 253 plus, uh, 147?", False, "filler and function words do not make a different question" ),
    ( "angle of a 45 degree slope",        "angle of a 45-degree slope",         False, "a hyphen joining a number to a word is not subtraction" ),
    ( "How many miles is 5 kilometers?",   "What's 5 kilometers in miles?",      True,  "THE PRICE: a true paraphrase whose number moved is refused (fails closed)" ),
    ( "Convert 10 miles to kilometers",    "Calculate 10 miles in kilometers",   True,  "THE PRICE: a different leading verb is refused" ),
] )
def test_quantities_differ( asked, stored, differ, why ):
    assert quantities_differ( asked, stored ) is differ, why


# ── ROW 1b3ec88f, Rio's review of 7840b20ab: cases the first predicate let through ───────────────
# Written red against 7840b20ab (6 failed), then made green by the ordered-token comparison.
@pytest.mark.parametrize( "asked, stored, why", [
    ( "Convert 10 miles to kilometers",            "Convert 10 miles to feet",                    "target unit differs: only the word after the number was compared" ),
    ( "Convert 100 degrees fahrenheit to celsius", "Convert 100 degrees celsius to fahrenheit",   "same words, opposite direction" ),
    ( "what is -5 plus 3",                         "what is 5 plus 3",                            "a minus sign is part of the number" ),
    ( "add .5 cups of flour",                      "add 5 cups of flour",                         "a leading-dot decimal is 0.5, not 5" ),
    ( "what is the temperature in 2 hours",        "what is the temperature in 2 days",           "a differing unit after the number (the old rule's case, kept as a control)" ),
    ( "How many miles is 10 kilometers?",          "What's 10 miles in kilometers?",              "the number moved relative to the units: opposite conversions with the same word set" ),
] )
def test_rios_cases_are_refused( asked, stored, why ):
    assert quantities_differ( asked, stored ) is True, why


def test_a_candidate_whose_question_is_none_is_refused_not_raised():
    assert quantities_differ( "Convert 10 miles to kilometers", None ) is True


def test_a_missing_asked_question_is_refused_not_raised():
    assert quantities_differ( None, "Convert 10 miles to kilometers" ) is True
