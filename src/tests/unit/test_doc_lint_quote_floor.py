"""
Row ed2f9b4e: the claim harness threw away a claim whose verbatim quote was a short removed span.

The extractor listed the claim; locate_quote refused a quote under 3 words or 15 characters; no judge
was asked. These tests pin the fix: floors of 2 words and 10 characters for a quote that occurs once,
one discard code per cause, a stretch that no kept quote covers re-extracted once and then flagged,
the scoring of a flag, and a pre-flight that every seeded span can itself be quoted.
The fake model reads the text it is given, as in test_doc_lint_claim_extractor.
"""

import asyncio
import json
import os
import re

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

import cosa.utils.util as cu
from cosa.repo.doc_lint import claim_extractor as ce
from cosa.repo.doc_lint import harness_cli, harness_report as hr, harness_runner as hn

@pytest.fixture( autouse=True )
def short_runs( monkeypatch ):
    """The tests use short sentences, so they run the flag rule at 2 words; the default is pinned in its own test below."""
    monkeypatch.setattr( ce, "MIN_RUN_WORDS", 2 )


OLD = "The chase window is ten minutes. A parked row stays parked if idle. Raises ValueError when blank."


def scripted_query( replies, seen=None ):
    """A stand-in for sdk_query that answers each call with the next reply, and records the old text it was shown."""
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


# ---- the floors (T2, T6) ---------------------------------------------------------------------

def test_a_unique_two_word_quote_of_ten_characters_is_kept_with_its_span():
    code, span = ce.classify_quote( "ten minutes", OLD )
    assert code is None and OLD[ span[ 0 ]:span[ 1 ] ] == "ten minutes"
    assert ce.locate_quote( "ten minutes", OLD ) == span


@pytest.mark.parametrize( "quote, code", [
    ( "ValueError", ce.TOO_FEW_WORDS ),         # one word of 10 characters: the word floor alone
    ( "if idle", ce.TOO_FEW_CHARS ),            # two words of 7 characters: the character floor alone
] )
def test_each_floor_refuses_on_its_own( quote, code ):
    assert ce.classify_quote( quote, OLD )[ 0 ] == code


def test_a_two_word_quote_of_exactly_nine_characters_is_refused_and_ten_is_kept():
    assert ce.classify_quote( "ab cdefgh", "Say ab cdefgh now. Then stop." )[ 0 ] == ce.TOO_FEW_CHARS
    assert ce.classify_quote( "ab cdefghi", "Say ab cdefghi now. Then stop." )[ 0 ] is None


def test_the_destination_search_keeps_the_old_floors():
    assert ce.locate_quote( "ten minutes", "wait ten minutes here", bounded=False ) is None
    assert ce.locate_quote( "wait ten minutes", "wait ten minutes here", bounded=False ) is not None


# ---- uniqueness (T3) -------------------------------------------------------------------------

def test_a_short_quote_that_occurs_twice_is_ambiguous_and_names_the_first_occurrence():
    text = "Wait ten minutes. Then wait ten minutes more."
    code, span = ce.classify_quote( "ten minutes", text )
    assert code == ce.AMBIGUOUS and text[ span[ 0 ]:span[ 1 ] ] == "ten minutes" and span[ 0 ] == 5
    assert ce.locate_quote( "ten minutes", text ) is None


def test_a_quote_over_the_old_floors_that_occurs_twice_still_takes_the_first_occurrence():
    text = "It returns nothing here. And then it returns nothing here."
    assert ce.locate_quote( "returns nothing here", text ) == ( 3, 23 )


# ---- one code per cause, and no quote text in a row (T4) -------------------------------------

LONG_TEXT = ( "First sentence of a long text. " + "x" * 5 + " " ) + " ".join( [ "word" ] * 80 ) + ". Another sentence here."


@pytest.mark.parametrize( "quote, text, code", [
    ( "nothing like this exists",            OLD,        ce.NOT_FOUND ),
    ( "",                                    OLD,        ce.TOO_FEW_WORDS ),
    ( "Raises",                              OLD,        ce.TOO_FEW_WORDS ),
    ( "if idl",                              OLD,        ce.TOO_FEW_CHARS ),
    ( "ten minutes",                         "ten minutes and ten minutes", ce.AMBIGUOUS ),
    ( " ".join( [ "word" ] * 70 ),           LONG_TEXT,  ce.TOO_LONG ),
    ( "A parked row stays parked if idle. Raises ValueError when blank.", OLD, ce.SHARE_CAP ),
] )
def test_each_discard_code_comes_from_its_own_input( quote, text, code ):
    assert ce.classify_quote( quote, text )[ 0 ] == code


def test_a_discard_row_carries_the_code_the_word_count_and_the_stretch_and_never_the_quote():
    pairs = [ ( "c1", "if idle" ), ( "c2", "nothing like this exists" ), ( "c3", "ten minutes" ) ]
    claims, discarded = ce.verify_claims( pairs, OLD )
    rows = ce.discard_rows( discarded, OLD )
    start = OLD.index( "if idle" )
    assert [ c.quote for c in claims ] == [ "ten minutes" ]
    assert rows == [ { "code": ce.TOO_FEW_CHARS, "words": 2, "start": start, "end": start + 7 },
                     { "code": ce.NOT_FOUND, "words": 4, "start": None, "end": None } ]
    assert "if idle" not in json.dumps( rows ) and "nothing like" not in json.dumps( rows )


def test_every_code_is_listed_once():
    assert sorted( ce.DISCARD_CODES ) == sorted( { ce.NOT_FOUND, ce.TOO_FEW_WORDS, ce.TOO_FEW_CHARS, ce.AMBIGUOUS, ce.TOO_LONG, ce.SHARE_CAP } )


# ---- uncovered runs and the enclosing sentence -----------------------------------------------

def test_an_uncovered_run_needs_two_words_and_one_content_word():
    text   = "Alpha beta gamma. of the. delta. epsilon zeta"
    spans  = [ ( 0, 5 ) ]                       # covers "Alpha"
    runs   = ce.uncovered_runs( text, spans )
    assert [ text[ a:b ] for a, b in runs ] == [ "beta gamma. of the. delta. epsilon zeta" ]
    assert ce.uncovered_runs( "of the", [] ) == []          # stop words only
    assert ce.uncovered_runs( "alone", [] ) == []           # one word
    assert ce.uncovered_runs( OLD, [ ( 0, len( OLD ) ) ] ) == []


def test_a_span_that_ends_a_run_splits_it():
    text = "one two THREE four five"
    runs = ce.uncovered_runs( text, [ ( 8, 13 ) ] )
    assert [ text[ a:b ] for a, b in runs ] == [ "one two", "four five" ]


def test_the_enclosing_sentences_are_each_returned_once_in_order():
    runs = [ ( OLD.index( "ten" ), OLD.index( "ten" ) + 3 ), ( OLD.index( "parked row" ), OLD.index( "parked row" ) + 4 ),
             ( OLD.index( "parked row" ) + 5, OLD.index( "parked row" ) + 9 ) ]
    assert ce.enclosing_sentences( OLD, runs ).split( "\n" ) == [ "The chase window is ten minutes.", "A parked row stays parked if idle." ]
    assert ce.enclosing_sentences( OLD, [] ) == ""


# ---- extraction: a stretch is re-extracted once and then flagged (T7) -------------------------

COVER_ALL = [ "The chase window is ten minutes.", "A parked row stays parked if idle.", "Raises ValueError when blank." ]


def test_a_text_every_sentence_of_which_is_quoted_makes_one_call_and_flags_nothing():
    result = extract( [ reply( *COVER_ALL ) ] )
    assert result.reextract_calls == 0 and result.flags == [] and result.discards == []


def test_a_short_quote_on_a_stretch_nothing_else_covers_is_kept_and_asks_nothing_more():
    # The extractor lists the 2-word removed span "ten minutes" and the two other sentences: all three verify.
    seen   = []
    result = extract( [ reply( "ten minutes", COVER_ALL[ 1 ], COVER_ALL[ 2 ] ), reply( "ten minutes" ) ], seen=seen )
    assert [ c.quote for c in result.claims ][ 0 ] == "ten minutes"
    assert result.discards == [] and len( seen ) == 2          # "The chase window is" is still under no quote
    assert seen[ 1 ] == "The chase window is ten minutes."
    start = OLD.index( "The chase" )
    assert result.reextract_calls == 1 and [ tuple( f ) for f in result.flags ] == [ ( start, start + len( "The chase window is" ) ) ]


def test_a_below_floor_quote_that_stays_below_floor_leaves_its_stretch_flagged_on_exactly_that_stretch():
    first  = reply( "if idle", COVER_ALL[ 0 ], COVER_ALL[ 2 ] )
    second = reply( "if idle" )
    seen   = []
    result = extract( [ first, second ], seen=seen )
    start  = OLD.index( "A parked row" )
    assert [ d[ "code" ] for d in result.discards ] == [ ce.TOO_FEW_CHARS ]
    assert seen[ 1 ] == "A parked row stays parked if idle."
    assert result.reextract_calls == 1 and [ tuple( f ) for f in result.flags ] == [ ( start, start + len( "A parked row stays parked if idle." ) ) ]


def test_the_second_call_can_cover_the_stretch_and_then_nothing_is_flagged():
    first  = reply( COVER_ALL[ 0 ], COVER_ALL[ 2 ] )
    result = extract( [ first, reply( COVER_ALL[ 1 ] ) ] )
    assert result.reextract_calls == 1 and result.flags == [] and len( result.claims ) == 3


def test_an_unreadable_second_reply_flags_the_stretch_and_a_failed_first_reply_still_raises():
    result = extract( [ reply( COVER_ALL[ 0 ], COVER_ALL[ 2 ] ), "not json" ] )
    assert result.reextract_calls == 1 and len( result.flags ) == 1 and len( result.claims ) == 2
    with pytest.raises( ce.ExtractionParseError ):
        extract( [ "not json" ] )


def test_an_invented_quote_is_counted_under_its_code_and_flags_nothing_when_the_text_is_covered():
    result = extract( [ reply( *COVER_ALL, "no such text anywhere" ) ] )
    assert [ ( d[ "code" ], d[ "start" ] ) for d in result.discards ] == [ ( ce.NOT_FOUND, None ) ]
    assert result.flags == [] and result.reextract_calls == 0


def test_a_claim_the_second_call_repeats_is_not_added_twice():
    first  = reply( COVER_ALL[ 0 ], COVER_ALL[ 2 ], "A parked row stays" )
    result = extract( [ first, reply( "A parked row stays" ) ] )
    assert [ c.quote for c in result.claims ].count( "A parked row stays" ) == 1


# ---- scoring (T5, B4) ------------------------------------------------------------------------

CONFIG = hn.HarnessConfig( "e", "j", "x", "w", 1, 1 )


def lst( claims=(), flags=(), discards=(), verdict="present" ):
    return { "claims": [ { "start": a, "end": b, "quote": "q" } for a, b in claims ], "discarded": len( discards ),
             "discards": [ { "code": "TOO_FEW_CHARS", "words": 2, "start": a, "end": b } for a, b in discards ],
             "flags": [ list( f ) for f in flags ], "flag_words": [ 12 for _ in flags ], "reextract_calls": 0, "uncovered": 0.0, "longest_quote": 0.0,
             "runs": [ [ { "verdict": verdict, "escalated": False, "noul": None } for _ in claims ] ] }


def report( *results ):
    return hr.build_report( [ { "id": i, "seed_span": s, "lists": [ lst_ ] } for i, ( s, lst_ ) in enumerate( results ) ], CONFIG )


def test_a_flag_on_the_seeded_span_is_a_catch_and_a_flag_elsewhere_is_not():
    on_span  = report( ( ( 10, 20 ), lst( flags=[ ( 12, 14 ) ] ) ) )
    off_span = report( ( ( 10, 20 ), lst( flags=[ ( 30, 40 ) ] ) ) )
    assert on_span[ "lists" ][ 0 ][ "misses" ] == 0 and on_span[ "lists" ][ 0 ][ "caught_by_flag_only" ] == 1
    assert off_span[ "lists" ][ 0 ][ "misses" ] == 1 and off_span[ "lists" ][ 0 ][ "caught_by_flag_only" ] == 0


def test_a_flag_on_an_unseeded_pair_is_not_a_judge_false_alarm_and_has_its_own_rate_and_ceiling():
    out = report( ( None, lst( flags=[ ( 0, 5 ) ] ) ), ( None, lst() ), ( ( 10, 20 ), lst( flags=[ ( 12, 14 ) ] ) ), ( ( 10, 20 ), lst( claims=[ ( 10, 20 ) ], verdict="absent" ) ) )
    row = out[ "lists" ][ 0 ]
    assert ( row[ "false_alarms" ], row[ "unseeded" ] ) == ( 0, 2 ), "a flagged run is not a judge false alarm"
    assert ( row[ "flagged_pairs" ], row[ "flagged_rate" ] ) == ( 1, 0.5 ) and out[ "flagged_rate" ] == 0.5
    assert row[ "mean_flag_words" ] == 12 and out[ "mean_flag_words" ] == 12
    assert out[ "flagged_ok" ] is False and out[ "false_alarm_ok" ] is True
    assert row[ "caught_by_flag_only" ] == 1, "the pair caught by a dropped claim is not counted as caught by a flag alone"


def test_the_flag_ceiling_is_fifteen_percent_inclusive_per_list_and_the_judge_ceiling_stays_ten():
    def rate( flagged, judged, n=100 ):
        pairs = [ ( None, lst( flags=[ ( 0, 5 ) ] if i < flagged else (), claims=[ ( 0, 3 ) ], verdict="absent" if flagged <= i < flagged + judged else "present" ) ) for i in range( n ) ]
        return report( *pairs )
    ok, over = rate( 15, 0 ), rate( 16, 0 )
    assert ok[ "lists" ][ 0 ][ "flagged_rate" ] == 0.15 and ok[ "flagged_ok" ] is True
    assert over[ "flagged_ok" ] is False
    assert rate( 0, 10 )[ "false_alarm_ok" ] is True and rate( 0, 10 )[ "flagged_ok" ] is True and rate( 0, 11 )[ "false_alarm_ok" ] is False


def test_the_review_rate_is_the_union_of_flagged_and_judged_pairs_and_has_no_ceiling():
    out = report( ( None, lst( flags=[ ( 0, 5 ) ] ) ), ( None, lst( claims=[ ( 0, 3 ) ], verdict="absent" ) ),
                  ( None, lst( flags=[ ( 0, 5 ) ], claims=[ ( 0, 3 ) ], verdict="absent" ) ), ( None, lst() ) )
    row = out[ "lists" ][ 0 ]
    assert ( row[ "flagged_pairs" ], row[ "false_alarms" ], row[ "review_pairs" ], row[ "review_rate" ] ) == ( 2, 2, 3, 0.75 )
    assert out[ "review_rate" ] == 0.75


def test_a_flag_that_fails_its_own_ceiling_blocks_the_default_gate_though_the_judge_is_clean():
    pairs = [ ( ( 0, 3 ), lst( claims=[ ( 0, 3 ) ], verdict="absent" ) ) for _ in range( 60 ) ] + [ ( None, lst( flags=[ ( 0, 5 ) ] ) ) for _ in range( 10 ) ]
    out   = report( *pairs )
    assert out[ "miss_criterion_met" ] is True and out[ "false_alarm_ok" ] is True and out[ "flagged_ok" ] is False and out[ "default_gate_pass" ] is False


def test_seeded_span_discarded_counts_a_discarded_quote_on_the_span_and_ignores_one_off_it():
    out = report( ( ( 10, 20 ), lst( discards=[ ( 12, 14 ) ] ) ), ( ( 10, 20 ), lst( discards=[ ( 30, 40 ) ] ) ),
                  ( ( 10, 20 ), lst() ), ( None, lst( discards=[ ( 12, 14 ) ] ) ) )
    assert out[ "lists" ][ 0 ][ "seeded_span_discarded" ] == 1 and out[ "seeded_span_discarded" ] == 1
    assert out[ "lists" ][ 0 ][ "misses" ] == 3, "a discard is a diagnosis, not a catch"


def test_a_discard_with_no_stretch_never_counts_as_on_the_span():
    row = lst()
    row[ "discards" ] = [ { "code": "NOT_FOUND", "words": 3, "start": None, "end": None } ]
    assert hr.discarded_on( row, ( 0, 100 ) ) is False


def test_the_report_counts_discards_per_code_and_the_extra_calls():
    one = lst( discards=[ ( 1, 3 ) ] )
    one[ "reextract_calls" ] = 1
    out = report( ( ( 10, 20 ), one ), ( None, lst() ) )
    assert out[ "discard_codes" ] == { **{ c: 0 for c in ce.DISCARD_CODES }, "TOO_FEW_CHARS": 1 } and out[ "reextract_calls" ] == 1


def test_a_report_with_no_pairs_has_no_flagged_rate():
    out = hr.build_report( [], CONFIG )
    assert out[ "flagged_rate" ] is None and out[ "mean_flag_words" ] is None and out[ "review_rate" ] is None and out[ "flagged_ok" ] is False


# ---- a ledger entry from before the fix, and the runner end to end ---------------------------

def test_a_legacy_ledger_entry_reads_as_no_discards_no_flags_and_no_extra_calls( tmp_path ):
    ledger = hn.Ledger( str( tmp_path / "l.jsonl" ) )
    pair   = { "id": "p", "old": OLD, "new": OLD, "seed_span": None }
    key    = hn.ledger_key( "extract", pair, ce.PROMPT_VERSION, "e", 0 )
    async def no_model( prompt, options ): raise AssertionError( "a model was called" ); yield
    config = hn.HarnessConfig( "e", "j", "x", "w", 1, 1 )
    ledger.put( key, { "claims": [], "discarded": 0, "uncovered": 1.0, "longest_quote": 0.0 } )         # the shape before ed2f9b4e
    row = asyncio.run( hn.run_pair( pair, config, ledger, query_fn=no_model ) )[ "lists" ][ 0 ]
    assert ( row[ "discards" ], row[ "flags" ], row[ "reextract_calls" ] ) == ( [], [], 0 )
    ledger.put( key, { "claims": [], "discarded": 1, "discards": [ { "code": "TOO_FEW_CHARS", "words": 2, "start": 1, "end": 3 } ],
                       "flags": [ [ 4, 9 ] ], "reextract_calls": 1, "uncovered": 1.0, "longest_quote": 0.0 } )
    row = asyncio.run( hn.run_pair( pair, config, ledger, query_fn=no_model ) )[ "lists" ][ 0 ]
    assert row[ "flags" ] == [ [ 4, 9 ] ] and row[ "reextract_calls" ] == 1 and row[ "discards" ][ 0 ][ "code" ] == "TOO_FEW_CHARS"


def test_a_fresh_run_pair_stores_the_new_fields_in_the_ledger( tmp_path ):
    ledger = hn.Ledger( str( tmp_path / "l.jsonl" ) )
    pair   = { "id": "p", "old": OLD, "new": OLD, "seed_span": None }
    replies = iter( [ reply( COVER_ALL[ 0 ], COVER_ALL[ 2 ], "if idle" ), reply( "if idle" ) ] )
    async def query( prompt, options ):
        yield ResultMessage( subtype="x", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s" )
        yield AssistantMessage( content=[ TextBlock( next( replies, json.dumps( { "verdicts": [ { "id": n, "verdict": "present" } for n in range( 3 ) ] } ) ) ) ], model=options.model )
    out = asyncio.run( hn.run_pair( pair, hn.HarnessConfig( "e", "j", "x", "w", 1, 1 ), ledger, query_fn=query ) )
    row = out[ "lists" ][ 0 ]
    assert row[ "reextract_calls" ] == 1 and len( row[ "flags" ] ) == 1 and [ d[ "code" ] for d in row[ "discards" ] ] == [ "TOO_FEW_CHARS" ]
    stored = next( v for k, v in ledger.entries.items() if k.startswith( "extract|" ) )
    assert stored[ "flags" ] == row[ "flags" ] and "if idle" not in json.dumps( stored )


# ---- representability: every seeded span can itself be quoted (T1) ---------------------------

def pair_with( old, span_text, pid="p" ):
    start = old.index( span_text )
    return { "id": pid, "old": old, "new": old.replace( span_text, "" ), "seed_span": ( start, start + len( span_text ) ) }


def test_a_two_word_twelve_character_span_is_quotable_now_and_was_not_before():
    # The shape of the three burned pairs: a 2-word span of 12 characters inside a longer sentence. Red on 9ce6f5f6e.
    pair = pair_with( OLD, "chase window", "a" )                                              # 2 words, 12 characters
    assert hn.unquotable_seeds( [ pair ] ) == []


def test_a_one_word_span_an_ambiguous_span_and_a_whole_text_span_are_listed_by_id_only():
    ambiguous = { "id": "amb", "old": "Wait ten minutes. Then wait ten minutes more.", "new": "x", "seed_span": ( 5, 16 ) }
    whole     = { "id": "whole", "old": OLD, "new": "x", "seed_span": ( 0, len( OLD ) ) }
    one_word  = pair_with( OLD, "ValueError", "one" )
    fine      = pair_with( OLD, "chase window", "fine" )
    unseeded  = { "id": "u", "old": OLD, "new": OLD, "seed_span": None }
    assert hn.unquotable_seeds( [ ambiguous, whole, one_word, fine, unseeded ] ) == [ "amb", "whole", "one" ]


def test_every_seeded_span_of_the_committed_judge_comparison_fixture_is_quotable():
    path  = os.path.join( cu.get_project_root(), "src", "tests", "fixtures", "judge_comparison", "pairs.json" )
    pairs = json.load( open( path ) )
    seeded = [ p for p in pairs if p.get( "seed_span" ) ]
    assert len( seeded ) > 0, "a loop over nothing passes"
    assert hn.unquotable_seeds( seeded ) == []


def test_the_command_line_refuses_an_unquotable_seeded_span_with_exit_4_before_any_model_call( tmp_path, capsys ):
    pairs = tmp_path / "pairs.json"
    pairs.write_text( json.dumps( [ pair_with( OLD, "ValueError", "one-word" ) ] ) )
    def no_model( prompt, options ): raise AssertionError( "a model was called" )
    argv = [ "--pairs", str( pairs ), "--ledger", str( tmp_path / "l.jsonl" ), "--out", str( tmp_path / "r.json" ),
             "--extractor-model", "e", "--judge-model", "j", "--escalation-model", "x", "--writer-model", "w" ]
    assert harness_cli.main( argv, query_fn=no_model ) == 4
    err = capsys.readouterr().err
    assert "one-word" in err and "ValueError" not in err and not ( tmp_path / "l.jsonl" ).exists()


# ---- review follow-ups (Tiberius, row ed2f9b4e): the or in the ambiguity test, and the prose judge's floors ----

def test_a_two_word_quote_of_fifteen_or_more_characters_that_occurs_twice_is_ambiguous():
    # 2 words, 18 characters: under the old word floor but not the old character floor, so only an OR catches it.
    text = "Set the parked_status flag first. Then clear the parked_status flag."
    assert ce.classify_quote( "parked_status flag", text )[ 0 ] == ce.AMBIGUOUS
    assert ce.classify_quote( "parked_status flag", "Set the parked_status flag first. Then stop." )[ 0 ] is None


def test_the_prose_judge_still_refuses_a_two_word_sentence_whatever_its_length():
    from cosa.repo.doc_lint import prose_judge as pj
    item = { "text": "Raises Error here. ValueError raised now. Longer sentence of five words.", "first_line": 5 }
    assert pj.locate_line( "Raises Error", item ) is None          # 2 words, 12 characters: over the new floors, under the old
    assert pj.locate_line( "ValueError raised", item ) is None      # 2 words, 17 characters
    assert pj.locate_line( "Longer sentence of five words.", item ) == 5


def test_the_default_minimum_run_is_ten_words_provisionally( monkeypatch ):
    monkeypatch.undo()
    assert ce.MIN_RUN_WORDS == 10
    nine, ten = " ".join( f"word{n}" for n in range( 9 ) ), " ".join( f"word{n}" for n in range( 10 ) )
    assert ce.uncovered_runs( nine, [] ) == [] and ce.uncovered_runs( ten, [] ) == [ ( 0, len( ten ) ) ]


def test_the_prose_judge_refuses_a_three_word_sentence_of_ten_to_fourteen_characters():
    # Only the character floor refuses this one: 3 words meet either word floor, 12 characters meet the new
    # character floor of 10 and miss the old one of 15, which the prose judge keeps (Tiberius, row ed2f9b4e).
    from cosa.repo.doc_lint import prose_judge as pj
    item = { "text": "Do not run. A longer sentence of six words here.", "first_line": 3 }
    assert pj.locate_line( "Do not run.", item ) is None
    assert pj.locate_line( "A longer sentence of six words here.", item ) == 3


def test_the_flag_words_are_counted_per_run_in_an_extraction():
    first = reply( COVER_ALL[ 0 ], COVER_ALL[ 2 ] )
    out   = extract( [ first, "not json" ] )
    assert list( out.flag_words ) == [ len( COVER_ALL[ 1 ].split() ) ]
