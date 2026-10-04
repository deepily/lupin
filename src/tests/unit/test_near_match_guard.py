"""
Unit tests for the near-match quantity guard (row 1b3ec88f): `cosa.rest.v2.near_match_guard`.

Pure functions, no flow, no network. Each parametrized case names what it stands for.
"""

import pytest

from cosa.rest.v2.near_match_guard import has_number, quantities_differ, quantity_tokens


@pytest.mark.parametrize( "text, expected", [
    ( "Convert 10 miles to kilometers",              [ "convert", "10", "mile", "to", "kilometer" ] ),
    ( "How many miles is 10 kilometers?",            [ "how", "many", "mile", "10", "kilometer" ] ),
    ( "Convert 100 degrees fahrenheit to celsius",   [ "convert", "100", "degree", "fahrenheit", "to", "celsius" ] ),
    ( "Uh... what\u2019s 253 plus, uh, 147?",           [ "what", "253", "plus", "147" ] ),
    ( "what is 2 + 2",                               [ "what", "2", "plus", "2" ] ),
    ( "5-3",                                         [ "5", "minus", "3" ] ),
    ( "5 - 3",                                       [ "5", "minus", "3" ] ),
    ( "a 45-degree angle",                           [ "a", "45", "degree", "angle" ] ),
    ( "couch-to-5K plan",                            [ "couch", "to", "5", "k", "plan" ] ),
    ( "dash - alone and trailing -",                 [ "dash", "alone", "and", "trailing" ] ),
    ( "what is -5 plus 3",                           [ "what", "-5", "plus", "3" ] ),
    ( "what is \u22125 plus 3",                      [ "what", "-5", "plus", "3" ] ),
    ( "add .5 cups of flour",                        [ "add", "0.5", "cup", "flour" ] ),
    ( "pay 1,000 dollars or 3.50 dollars",           [ "pay", "1000", "dollar", "or", "3.5", "dollar" ] ),
    ( "interest at 7% on $5,000",                    [ "interest", "at", "7", "percent", "on", "dollar", "5000" ] ),
    ( "3 \u00d7 4 \u00f7 2 * 1 / 1 = 6",             [ "3", "times", "4", "divided", "2", "times", "1", "divided", "1", "equal", "6" ] ),
    ( "a 3,5 thing",                                 [ "a", "3", "5", "thing" ] ),
    ( "-0 and 0.0",                                  [ "0", "and", "0" ] ),
    ( "eat berries, glasses, boxes, lunches, dishes, plus, this, bus", [ "eat", "berry", "glass", "box", "lunch", "dish", "plus", "this", "bus" ] ),
    ( "it\u2019s you\u2019re we'll I'd they've I'm don't",     [ "it", "you", "we", "will", "i", "would", "they", "have", "i", "am", "not" ] ),
    ( "hmmm ummm uhhh errr ahh ehh ohh",             [] ),
    ( "can't won't isn't cannot o'clock John's", [ "can", "not", "will", "not", "not", "can", "not", "oclock", "john" ] ),
    ( "no numbers here",                             [ "no", "number", "here" ] ),
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


@pytest.mark.parametrize( "asked, stored, why", [
    ( "what is 10 more than 5",              "what is 10 less than 5",              "more/less are spaCy stop words but decide the answer" ),
    ( "what is 10 before 5 pm",              "what is 10 after 5 pm",               "before/after flip the meaning" ),
    ( "is 10 above 5",                       "is 10 below 5",                       "above/below flip the meaning" ),
    ( "is 10 over 5",                        "is 10 under 5",                       "over/under flip the meaning" ),
    ( "10 is not 5",                         "10 is 5",                             "negation is a stop word and flips the meaning" ),
    ( "convert 10 miles from kilometers",    "convert 10 miles to kilometers",      "from/to name the direction" ),
    ( "the first 10 of 50",                  "the last 10 of 50",                   "first/last differ" ),
    ( "what is ten plus 5",                  "what is five plus 5",                 "spelled numbers are stop words and must still be compared" ),
    ( "10 miles per hour",                   "10 miles an hour over 3",             "per is kept as a word" ),
    ( "at least 10 apples",                  "at most 10 apples",                   "least/most differ" ),
] )
def test_direction_negation_and_spelled_number_words_are_not_dropped_as_stop_words( asked, stored, why ):
    assert quantities_differ( asked, stored ) is True, why


@pytest.mark.parametrize( "asked, stored, why", [
    ( "5 and 3",                      "5 or 3",                        "and/or" ),
    ( "sum of 2 and 3",               "sum of 2 or 3",                 "and/or inside a sum" ),
    ( "can I drive 50 miles",         "can't I drive 50 miles",        "can't must not become can" ),
    ( "can I use 5",                  "can't I use 5",                 "can't must not become can" ),
    ( "can I use 5",                  "cannot I use 5",                "cannot is not can" ),
    ( "without 5",                    "with 5",                        "without/with" ),
    ( "if 5 is even",                 "unless 5 is even",              "if/unless" ),
    ( "all but 5",                    "all 5",                         "but" ),
    ( "5 plus 3 then 2",              "5 plus 3 also 2",               "then/also" ),
    ( "5 must work",                  "5 may work",                    "modals" ),
    ( "5 will work",                  "5 would work",                  "modals" ),
    ( "I'll use 5",                   "I'd use 5",                     "'ll and 'd are will and would" ),
    ( "anyone with 5",                "someone with 5",                "quantifier pronouns" ),
    ( "5 someone",                    "5 nobody",                      "quantifier pronouns" ),
    ( "5 always",                     "5 sometimes",                   "frequency" ),
    ( "5 now",                        "5 then",                        "time" ),
    ( "5 here",                       "5 there",                       "place" ),
    ( "who has 5",                    "whom has 5",                    "who/whom" ),
    ( "up 5",                         "down 5",                        "up/down, unpinned before" ),
    ( "top 5",                        "bottom 5",                      "top/bottom, unpinned before" ),
    ( "never 5",                      "none 5",                        "never/none, unpinned before" ),
    ( "5 until noon",                 "5 since noon",                  "until/since, unpinned before" ),
    ( "5 per day",                    "5 a day",                       "per vs a" ),
    ( "a word nobody has listed 5",   "a word nobody has invented 5",  "an unknown word fails closed" ),
] )
def test_every_word_outside_the_filler_list_is_compared( asked, stored, why ):
    assert quantities_differ( asked, stored ) is True, why


@pytest.mark.parametrize( "asked, stored", [
    ( "convert 10 miles to km",       "Convert 10 miles to km please" ),
    ( "what's 5 plus 3",              "what is 5 plus 3" ),
    ( "what is 2 + 2",                "what is 2 plus 2" ),
    ( "Uh, what is 5 plus 3?",        "what is 5 plus 3" ),
    ( "isn't 5 big",                  "is not 5 big" ),
    ( "can't use 5",                  "can not use 5" ),
    ( "John's 5 apples",              "John 5 apples" ),
] )
def test_filler_and_spelling_variants_of_the_same_question_still_replay( asked, stored ):
    assert quantities_differ( asked, stored ) is False


from cosa.rest.v2.near_match_guard import _NOISE_WORDS

_KEPT_WORDS = (
    "more less fewer most least few many much than enough before after above below over under up down out off into from to "
    "per between within through across around behind beyond against until during since first last next top bottom front back "
    "again once twice no not nor never none cannot nothing neither either both all each every only just same other another half "
    "whole a was were did been am one two three ten hundred and or but without with unless if then also now here there always sometimes never someone "
    "anyone nobody everyone who whom whose what which when where why how can could may might must shall should will would have has had "
    "i you he she it we they me us them my your his her its our their this that these those some any such own very too also"
).split()


_PINNED_NOISE = [ "an", "the", "of", "please", "is", "are", "be", "do", "does" ]


def test_the_noise_list_is_exactly_what_the_tests_below_pin():
    assert sorted( _NOISE_WORDS ) == sorted( _PINNED_NOISE )


@pytest.mark.parametrize( "word", _PINNED_NOISE )
def test_each_noise_word_added_to_a_question_still_replays( word ):
    assert quantities_differ( f"show 5 apples {word} 3", "show 5 apples 3" ) is False, f"{word!r} is noise"


@pytest.mark.parametrize( "word", _KEPT_WORDS )
def test_each_kept_word_added_to_a_question_refuses( word ):
    assert word not in _NOISE_WORDS
    assert quantities_differ( f"show 5 apples {word} 3", "show 5 apples 3" ) is True, f"{word!r} is compared"


@pytest.mark.parametrize( "asked, stored, why", [
    ( "solve 5a = 10",              "solve 5 = 10",            "a variable next to a number" ),
    ( "what is a plus 5",           "what is plus 5",          "a variable beside an operator" ),
    ( "5 a day",                    "5 day",                   "a is a word" ),
    ( "meet at 5 am",               "meet at 5",               "am is a word" ),
    ( "is 5 even",                  "was 5 even",              "tense" ),
    ( "is 5 even",                  "were 5 even",             "tense" ),
    ( "does 5 work",                "did 5 work",              "tense" ),
    ( "has 5 been done",            "has 5 done",              "perfect tense" ),
    ( "isn't 5 big",                "wasn't 5 big",            "n't keeps the tense word" ),
    ( "I'm 5",                      "I 5",                     "'m is am" ),
] )
def test_tense_variables_and_am_are_compared( asked, stored, why ):
    assert quantities_differ( asked, stored ) is True, why


@pytest.mark.parametrize( "text, expected", [
    ( "I shan't use 5",             [ "i", "shall", "not", "use", "5" ] ),
    ( "it ain't 5",                 [ "it", "not", "5" ] ),
    ( "I'm 5",                      [ "i", "am", "5" ] ),
    ( "they're 5",                  [ "they", "5" ] ),
    ( "please show 5",              [ "show", "5" ] ),
] )
def test_irregular_clitics_and_please_are_pinned( text, expected ):
    assert quantity_tokens( text ) == expected


@pytest.mark.parametrize( "text, expected", [
    ( "show 5 n't",     [ "show", "5", "not" ] ),
    ( "n't 5",          [ "not", "5" ] ),
] )
def test_a_bare_nt_is_not_and_never_an_empty_token( text, expected ):
    tokens = quantity_tokens( text )
    assert "" not in tokens, f"empty token in {tokens}"
    assert tokens == expected
