"""
The claim extractor's clause check and the prompt rules that go with it (design note v2).

The fixture src/tests/fixtures/claim_clause/dev-nine-pairs.json holds claim lists written by the real
extractor (Sonnet, extractor-bb5fabc9a0). They cover the four dev pairs the judge missed and the five
it falsely alarmed on. It was copied out of the dev ledger, so the wording is the producer's.
No test here calls a model.
"""

import json
import os

import cosa.utils.util as cu
from cosa.repo.doc_lint import claim_extractor as ce

FIXTURE = os.path.join( cu.get_project_root(), "src", "tests", "fixtures", "claim_clause", "dev-nine-pairs.json" )

MISSES        = ( "p012", "p030", "p063", "p068" )
FALSE_ALARMS  = { "p027": [ 3 ], "p062": [ 8 ], "p070": [ 2 ], "p075": [ 2 ], "p078": [ 4 ] }


def claims_of( pair_id ):
    with open( FIXTURE, encoding="utf-8" ) as f:
        rows = json.load( f )[ pair_id ]
    return [ ce.Claim( r[ "text" ], r[ "quote" ], 0, 0 ) for r in rows ]


def test_fixture_covers_the_nine_pairs_and_every_claim_has_text_and_quote():
    with open( FIXTURE, encoding="utf-8" ) as f:
        data = json.load( f )
    assert sorted( data ) == sorted( list( MISSES ) + list( FALSE_ALARMS ) )
    assert sum( len( rows ) for rows in data.values() ) == 69
    assert all( r[ "text" ] and r[ "quote" ] for rows in data.values() for r in rows )


def test_each_false_alarm_claim_is_flagged():
    for pair_id, wanted in FALSE_ALARMS.items():
        flagged = ce.unsupported_claim_indexes( claims_of( pair_id ) )
        assert all( i in flagged for i in wanted ), ( pair_id, flagged )


def test_no_claim_of_a_missed_pair_is_flagged_since_the_check_is_not_what_failed_there():
    for pair_id in MISSES:
        assert ce.unsupported_claim_indexes( claims_of( pair_id ) ) == [], pair_id


def test_the_flags_on_the_nine_pairs_are_exactly_these_eight_claims():
    flagged = { p: ce.unsupported_claim_indexes( claims_of( p ) ) for p in list( MISSES ) + list( FALSE_ALARMS ) }
    assert { p: i for p, i in flagged.items() if i } == { "p027": [ 3 ], "p062": [ 8 ], "p070": [ 1, 2 ], "p075": [ 2, 5 ], "p078": [ 4 ] }


# ---- the splitter ----------------------------------------------------------------------------

def test_tail_is_the_text_after_the_last_cut():
    assert ce.claim_tail( "The header spanned the pane, which contrasted with the bubbles." ) == "contrasted with the bubbles."
    assert ce.claim_tail( "It is cached; a restart clears it, because memory is volatile." ) == "memory is volatile."


def test_tail_is_the_whole_claim_when_nothing_cuts_it():
    assert ce.claim_tail( "The stream emits on every transition." ) == "The stream emits on every transition."


def test_each_connective_word_cuts_but_only_as_a_whole_word_between_spaces():
    for word in ( "which", "so", "because", "since", "this is", "therefore", "hence", "thus", "while", "whereas" ):
        assert ce.claim_tail( f"Head clause {word} tail words here" ) == "tail words here", word
    assert ce.claim_tail( "Head sofa and whichever stay" ) == "Head sofa and whichever stay"


def test_cutting_ignores_case():
    assert ce.claim_tail( "Head Because Tail words" ) == "Tail words"


# ---- the token rule --------------------------------------------------------------------------

def test_stems_drop_stop_words_short_tokens_and_cut_to_five_characters():
    assert ce.clause_stems( "The callers do add it to a Bearer token" ) == { "calle", "add", "beare", "token" }
    assert ce.clause_stems( "the of it is" ) == set()
    assert ce.clause_stems( "id ok go" ) == set()


def test_stems_keep_digits_and_underscores_and_match_by_prefix():
    assert ce.clause_stems( "speak_anyway handles 404s" ) == { "speak", "handl", "404s" }
    assert ce.clause_stems( "replays replayed" ) == { "repla" }


def test_the_stop_list_has_eighty_nine_words_and_is_not_the_uncovered_run_list():
    assert len( ce.CLAUSE_STOP_WORDS ) == 89
    assert ce.CLAUSE_STOP_WORDS != ce.STOP_WORDS


# ---- the trigger -----------------------------------------------------------------------------

def make( text, quote ):
    return ce.Claim( text, quote, 0, 0 )


def test_a_tail_that_shares_no_stem_with_the_quote_triggers():
    assert ce.says_more_than_quote( make( "The header spanned the full width, which contrasted with the narrower bubbles.", "The header spanned all of it" ) ) is True


def test_one_shared_stem_is_enough_to_keep_the_claim():
    assert ce.says_more_than_quote( make( "A restart clears the pause, so callers re-read the state.", "a restart clears it, so callers re-read" ) ) is False


def test_a_tail_with_fewer_than_two_content_stems_never_triggers():
    assert ce.says_more_than_quote( make( "The value is stored, nowhere.", "stored here" ) ) is False
    assert ce.says_more_than_quote( make( "It is on, the end.", "something unrelated entirely" ) ) is False


def test_exactly_two_content_stems_none_shared_triggers_and_one_shared_does_not():
    assert ce.says_more_than_quote( make( "Head, alpha bravo.", "gamma delta" ) ) is True
    assert ce.says_more_than_quote( make( "Head, alpha bravo.", "gamma alpha" ) ) is False


def test_the_check_reads_the_tail_only_so_a_head_word_missing_from_the_quote_does_not_trigger():
    assert ce.says_more_than_quote( make( "Mysterious extra words appear, shared stem here.", "shared stem" ) ) is False


def test_indexes_come_back_in_order_and_empty_for_no_claims():
    claims = [ make( "ok words, shared stem", "shared stem" ), make( "x, alpha bravo", "gamma delta" ), make( "y, alpha bravo", "alpha" ), make( "z, alpha bravo", "other" ) ]
    assert ce.unsupported_claim_indexes( claims ) == [ 1, 3 ]
    assert ce.unsupported_claim_indexes( [] ) == []


# ---- the prompt ------------------------------------------------------------------------------

QUALIFIER_WORDS = ( "only", "never", "always", "until", "unless", "rather than", "at most", "at least", "no longer", "without" )


def test_prompt_states_the_clause_rule_and_keeps_the_reply_contract_without_the_extra_claims_rule():
    prompt = ce.SYSTEM_PROMPT
    assert "A claim may not add a clause" in prompt
    clause = prompt.split( "A claim may not add a clause" )[ 1 ].split( "Reply with one JSON object" )[ 0 ]
    for word in ( "so", "which", "because", "this is the reason" ):
        assert word in clause
    assert "whose content words are absent from its quote" in prompt
    for gone in ( "If a sentence limits", "state the limit as one extra claim", "at least three words, and never the whole sentence",
                  "Make one extra claim per limiting word", "any adjective or any item of a list", "never give two claims the same quote" ):
        assert gone not in prompt
    assert "A qualifier is its own claim" not in prompt and "restricts a noun" not in prompt
    assert "Copy each quote character for character" in prompt
    assert prompt.index( "A claim may not add a clause" ) < prompt.index( "Reply with one JSON object" )


def test_the_prompt_version_changed_with_the_prompt_and_still_names_the_extractor():
    assert ce.PROMPT_VERSION.startswith( "extractor-" )
    assert ce.PROMPT_VERSION not in ( "extractor-bb5fabc9a0", "extractor-945e42d978" )
