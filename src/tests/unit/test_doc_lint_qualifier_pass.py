"""
The extractor's mechanical qualifier pass (design note, revision 2).

A sentence that holds one of ten limiting words, with no short quote around it, goes to the model once more.
That happens in the same single extra call the uncovered-run pass already makes.
The fake model here answers from a script and records the text it was shown, as in test_doc_lint_quote_floor.
No test calls a model.
"""

import asyncio
import json
import re

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from cosa.repo.doc_lint import claim_extractor as ce

TIGHT = "The server wakes only for a new notification."
LONG  = "The tap never crashes the app on the launch path when the stored payload is malformed or empty or old."
FILLER = "A parked row stays parked if idle."
OLD    = TIGHT + " " + LONG + " " + FILLER


def scripted_query( replies, seen=None ):
    calls = iter( replies )
    async def query( prompt, options ):
        if seen is not None: seen.append( re.search( r"<old_text_(\w+)>\n(.*)\n</old_text_\1>", prompt, re.DOTALL ).group( 2 ) )
        yield ResultMessage( subtype="x", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s" )
        yield AssistantMessage( content=[ TextBlock( next( calls ) ) ], model="fake" )
    return query


def reply( *quotes ):
    return json.dumps( { "claims": [ { "claim": f"claim {n}", "quote": q } for n, q in enumerate( quotes ) ] } )


def extract( replies, old=OLD, seen=None ):
    return asyncio.run( ce.extract_claims( old, "m", query_fn=scripted_query( replies, seen ) ) )


def claims_over( old, *quotes ):
    return [ ce.Claim( "c", q, old.index( q ), old.index( q ) + len( q ) ) for q in quotes ]


# ---- loose_qualifiers --------------------------------------------------------------------------

def test_the_ten_words_are_the_ones_the_prompt_names():
    assert ce.QUALIFIER_PHRASES == ( "only", "never", "always", "until", "unless", "rather than", "at most", "at least", "no longer", "without" )
    for phrase in ce.QUALIFIER_PHRASES: assert phrase in ce.SYSTEM_PROMPT


def test_with_no_claims_every_occurrence_is_loose_in_text_order():
    text = "It must never leak, rather than stay quiet. Only then, at most once, at least twice, no longer and always, until or unless, without."
    assert [ text[ a:b ].lower() for a, b in ce.loose_qualifiers( text, [] ) ] == [
        "never", "rather than", "only", "at most", "at least", "no longer", "always", "until", "unless", "without" ]


def test_only_whole_words_count_in_any_case():
    text = "A lonely onlyx xonly neverland alwaysly. ONLY Never WITHOUT At Least"
    assert [ text[ a:b ] for a, b in ce.loose_qualifiers( text, [] ) ] == [ "ONLY", "Never", "WITHOUT", "At Least" ]


def test_a_tight_claim_around_the_word_covers_it_and_a_claim_beside_it_does_not():
    claims = claims_over( OLD, "The server wakes only for a new notification" )
    assert [ OLD[ a:b ] for a, b in ce.loose_qualifiers( OLD, claims ) ] == [ "never" ]
    beside = claims_over( OLD, "The server wakes" )
    assert [ OLD[ a:b ] for a, b in ce.loose_qualifiers( OLD, beside ) ] == [ "only", "never" ]


def test_ten_words_is_tight_and_eleven_is_loose():
    ten    = "one two three four five six never seven eight nine"
    eleven = "one two three four five six never seven eight nine ten"
    assert ce.TIGHT_QUOTE_WORDS == 10
    assert ce.loose_qualifiers( ten, claims_over( ten, ten ) ) == []
    assert [ eleven[ a:b ] for a, b in ce.loose_qualifiers( eleven, claims_over( eleven, eleven ) ) ] == [ "never" ]


def test_a_claim_that_stops_inside_the_word_does_not_cover_it():
    text = "short only here"
    claim = [ ce.Claim( "c", "short on", 0, 8 ) ]
    assert [ text[ a:b ] for a, b in ce.loose_qualifiers( text, claim ) ] == [ "only" ]


# ---- extract_claims ----------------------------------------------------------------------------

def test_a_sentence_with_a_loose_limiting_word_is_asked_again_alone_and_the_tight_claim_is_kept():
    seen   = []
    result = extract( [ reply( TIGHT[ :-1 ], LONG[ :-1 ], FILLER[ :-1 ] ), reply( "never crashes the app on the launch path" ) ], seen=seen )
    assert seen[ 1 ] == LONG
    assert result.reextract_calls == 1 and result.flags == []
    assert [ c.quote for c in result.claims ] == [ TIGHT[ :-1 ], LONG[ :-1 ], FILLER[ :-1 ], "never crashes the app on the launch path" ]


def test_nothing_is_asked_again_when_every_limiting_word_has_a_tight_quote():
    seen   = []
    result = extract( [ reply( TIGHT[ :-1 ], "never crashes the app on the launch path", LONG[ :-1 ], FILLER[ :-1 ] ) ], seen=seen )
    assert len( seen ) == 1 and result.reextract_calls == 0


def test_a_text_with_no_limiting_word_makes_no_extra_call():
    text   = "The chase window is ten minutes. A parked row stays parked if idle."
    result = extract( [ reply( "The chase window is ten minutes", "A parked row stays parked if idle" ) ], old=text )
    assert result.reextract_calls == 0


def test_a_loose_sentence_and_an_uncovered_run_share_one_call():
    run  = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda."
    old  = OLD + " " + run
    seen = []
    result = extract( [ reply( TIGHT[ :-1 ], LONG[ :-1 ], FILLER[ :-1 ] ), reply( "never crashes the app on the launch path", run[ :-1 ] ) ], old=old, seen=seen )
    assert seen[ 1 ] == LONG + "\n" + run
    assert result.reextract_calls == 1 and result.flags == []
    assert len( result.claims ) == 5


def test_an_unreadable_second_reply_keeps_the_first_claims_and_flags_nothing_for_a_loose_word():
    result = extract( [ reply( TIGHT[ :-1 ], LONG[ :-1 ], FILLER[ :-1 ] ), "not json" ] )
    assert result.reextract_calls == 1 and result.flags == [] and len( result.claims ) == 3


def test_a_quote_the_second_call_repeats_is_not_added_twice_and_the_word_stays_loose():
    result = extract( [ reply( TIGHT[ :-1 ], LONG[ :-1 ], FILLER[ :-1 ] ), reply( LONG[ :-1 ] ) ] )
    assert len( result.claims ) == 3 and result.reextract_calls == 1
    assert [ OLD[ a:b ] for a, b in ce.loose_qualifiers( OLD, result.claims ) ] == [ "never" ]


def test_the_extra_call_runs_under_the_same_prompt():
    prompts = []
    async def query( prompt, options ):
        prompts.append( options.system_prompt )
        yield ResultMessage( subtype="x", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s" )
        yield AssistantMessage( content=[ TextBlock( reply( TIGHT[ :-1 ], LONG[ :-1 ], FILLER[ :-1 ] ) if len( prompts ) == 1 else reply( "never crashes the app on the launch path" ) ) ], model="fake" )
    asyncio.run( ce.extract_claims( OLD, "m", query_fn=query ) )
    assert len( prompts ) == 2 and prompts[ 0 ] == prompts[ 1 ]
