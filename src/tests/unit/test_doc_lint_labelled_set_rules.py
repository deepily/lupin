"""
Row 421963b6: the seven selection rules of the labelled-set seeder, the mechanical check after the writer (rule 1),
and the redraw path for the pairs that check fails.

Every docstring here is made up for this file. No dev, gate or reserve data is read; no model is called.
"""

import json
import random

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import labelled_set_rules as rules
from cosa.repo.doc_lint import labelled_set_seeder as s

SL = s.load_stoplist( s.DEFAULT_STOPLIST )


# ---- rule 7: a leading bullet or list marker is not a word ---------------------------------------

@pytest.mark.parametrize( "text, words", [ ( "- keep the lock", 3 ), ( "* keep the lock", 3 ), ( "• keep the lock", 3 ), ( "1. keep the lock", 3 ), ( "2) keep the lock", 3 ),
                                           ( "keep the lock", 3 ), ( "-", 0 ), ( "", 0 ), ( "keep - the lock", 4 ) ] )
def test_r7_a_leading_bullet_or_list_marker_is_not_a_word( text, words ):
    assert rules.words_of( text ) == words


def test_r7_a_three_word_bullet_span_is_short_and_a_four_word_one_is_not():
    assert s.is_short( s.words_of( "- keep the lock" ) ) is True
    assert s.is_short( s.words_of( "- keep the lock now" ) ) is False


def test_r7_the_plan_record_counts_the_words_without_the_marker():
    d = { "pool_id": "x", "file": "a/b.py", "symbol": "f", "old": "o", "stratum": "S" }
    rec = s.make_pair( "p000", "delete", d, { "span_text": "- keep the lock", "cut": "c" }, __import__( "random" ).Random( 1 ), {}, [] )
    assert ( rec[ "span_words" ], rec[ "short" ] ) == ( 3, True )


# ---- rule 2: a number or quantifier swap must not leave the claim standing elsewhere -----------------

def classes_of( old ):
    return sorted( { c[ "class" ] for c in s.weaken_candidates( old, SL ) } )


def test_r2_a_number_stated_once_is_a_candidate_and_stated_twice_is_not():
    once = "Return the count of workers. Callers must hold the lock for at least three seconds, which keeps the figure stable."
    twice = once + " The lock is held for three seconds."
    assert "number" in classes_of( once )
    assert "number" not in classes_of( twice )


def test_r2_the_same_value_as_digits_and_as_a_word_counts_as_a_restatement():
    old = "Return the count of workers. Callers hold the lock for three seconds, so wait 3 seconds before a retry."
    assert "number" not in classes_of( old )


def test_r2_a_quantifier_that_occurs_again_is_not_a_candidate_and_a_single_one_is():
    single = "Return the count of workers. The figure is exact and every worker is counted once."
    again  = single + " Every pool reports the same figure."
    assert "quantifier" in classes_of( single )
    assert "quantifier" not in classes_of( again )


def test_r2_other_classes_are_not_asked():
    assert rules.restated_swap( "It must hold. It must not fail.", "modal", "must", 3 ) is False


# ---- rule 3: a qualifier deletion needs the exclusion to be stated once, outside literals ----------------

def qualifier_spans( old ):
    return sorted( c[ "span_text" ] for c in s.weaken_candidates( old, SL ) if c[ "class" ] == "qualifier" )


def test_r3_a_qualifier_in_plain_prose_is_a_candidate():
    assert qualifier_spans( "Return the count of workers. The call returns only the idle workers of the open pool." )


LITERAL = "Return the count of workers. Pass the flag {o}return only idle workers of the open pool{c} to the call."


@pytest.mark.parametrize( "o, c", [ ( "`", "`" ), ( "\"", "\"" ), ( "“", "”" ) ] )
def test_r3_a_qualifier_inside_backticks_or_double_quotes_is_not_a_candidate_and_the_same_words_in_prose_are( o, c ):
    assert qualifier_spans( LITERAL.format( o="", c="" ) )                      # the control: without the literal the qualifier is a candidate
    assert qualifier_spans( LITERAL.format( o=o, c=c ) ) == []


@pytest.mark.parametrize( "old", [
    "Return the count of workers.\n\n```\nreturn only idle workers\n```\nThe open pool call is plain.",
    "Return the count of workers.\n\nExample:\n    count only idle workers of the open pool\n\nThe open pool call is plain.",
    "Return the count of workers.\n\n>>> count only idle workers of the open pool\n3\n\nThe open pool call is plain.",
] )
def test_r3_a_qualifier_inside_a_literal_an_example_or_a_fence_is_not_a_candidate( old ):
    assert qualifier_spans( old ) == []


def test_r3_a_qualifier_whose_exclusion_is_stated_in_another_sentence_is_not_a_candidate():
    stated = "Return the count of workers. The call returns only idle workers of the open pool. Busy workers of the open pool are never returned."
    again  = "Return the count of workers. The call returns only idle workers of the open pool. The open pool returns only idle workers on request."
    clear  = "Return the count of workers. The call returns only idle workers of the open pool. A second line mentions logging."
    assert qualifier_spans( stated ) == [] and qualifier_spans( again ) == []
    assert qualifier_spans( clear )


def test_r3_a_qualifier_with_no_sentence_around_it_is_judged_on_its_literal_status_alone():
    assert rules.qualifier_rejected( "only", 0, 4, "only" ) is False


# ---- rule 4: a delete may not leave broken text -------------------------------------------------------------

def reject( old, span_text ):
    """The reason the planner would refuse this delete for, in the planner's own order: bad_cut first, then the selection rules."""
    start = old.index( span_text )
    span  = ( start, start + len( span_text ) )
    cut   = s.cut_text( old, span )
    return s.bad_cut( old, cut ) or rules.delete_rejection( old, span, cut )


def test_r4_the_first_sentence_is_never_a_delete_candidate():
    old = "Return the count of idle workers in the open pool. Callers hold the lock here, which keeps the figure stable."
    assert reject( old, "in the open pool" ) == "SUMMARY"
    assert reject( old, "which keeps the figure stable" ) is None


def test_r4_a_cut_that_starts_a_sentence_on_a_lowercase_word_is_refused():
    old = "Return the count of workers. Callers retry, then stop waiting for the whole call here."
    assert reject( old, "Callers retry" ) == "LOWERCASE"


def test_r4_a_lowercase_word_after_a_cut_mid_sentence_is_fine_and_so_is_one_after_a_blank_line_cut():
    old = "Return the count of workers. Callers hold the lock for a while, which keeps the figure stable."
    assert reject( old, "for a while" ) is None
    para = "Return the count of workers.\n\nCallers retry, then stop waiting for the whole call here."
    assert reject( para, "Callers retry" ) == "LOWERCASE"


def test_r4_a_cut_that_leaves_a_sentence_under_four_words_is_refused():
    old = "Return the count of workers. Callers wait for the lock here, which is stable. Callers retry on failure."
    assert reject( old, "for the lock here, which is stable" ) == "SHORT_SENTENCE"
    assert reject( old, "which is stable" ) is None


def test_r4_a_cut_that_empties_a_field_is_refused():
    old = "Return the count of workers.\n\nRequires: an open pool\nEnsures: the count is exact, and it is never negative\n"
    assert reject( old, "an open pool" ) == "EMPTY_FIELD"
    assert reject( old, "and it is never negative" ) is None


def test_r4_a_cut_that_empties_a_heading_is_refused():
    old = "Return the count of workers.\n\nRaises:\n    ValueError when the pool is closed\n\nEnsures:\n    the count is exact\n    and never negative\n"
    assert reject( old, "ValueError when the pool is closed" ) == "EMPTY_HEADING"
    assert reject( old, "and never negative" ) is None


def test_r4_a_cut_that_leaves_a_paragraph_opening_on_a_pronoun_is_refused():
    old = "Return the count of workers.\n\nThe worker count, it is exact whenever the pool is open."
    assert reject( old, "The worker count" ) == "PRONOUN"


def test_r4_a_paragraph_that_already_opened_on_a_pronoun_is_not_blamed_on_the_cut():
    old = "Return the count of workers.\n\nIt is locked while counting. Callers wait for the lock here, which is slow."
    assert reject( old, "which is slow" ) is None


def test_r4_delete_candidates_count_the_new_refusals_by_reason_and_keep_none_of_them():
    old = "Return the count of idle workers. Callers hold the lock for a while, which keeps the figure stable. Callers retry on failure."
    cands, refused = s.delete_candidates( old, SL )
    assert set( refused ) - { "EMPTY", "DANGLING", "NO_VERB", "ORPHAN" }                    # at least one refusal comes from the new rules, counted by code
    assert cands and all( c[ "span" ][ 0 ] >= rules.first_sentence_end( old ) for c in cands )


def test_r4_a_sentence_start_is_found_at_the_start_of_the_text_after_a_full_stop_and_after_a_blank_line_only():
    assert rules.sentence_start_before( "Callers wait.", 0 ) is True
    assert rules.sentence_start_before( "  Callers wait.", 2 ) is True
    assert rules.sentence_start_before( "Stop. Callers wait.", 6 ) is True
    assert rules.sentence_start_before( "Stop\n\nCallers wait.", 6 ) is True
    assert rules.sentence_start_before( "Stop and\nCallers wait.", 9 ) is False


# ---- rule 5: a delete is refused when another sentence restates the span ---------------------------------------

def test_r5_a_span_restated_by_content_words_in_another_sentence_is_refused():
    old = "Return the count of workers. Callers hold the pool lock while counting idle workers. The pool lock is held while idle workers are counted."
    assert reject( old, "while counting idle workers" ) == "RESTATED"


def test_r5_a_span_no_other_sentence_restates_is_kept_and_a_span_with_no_content_is_never_restated():
    old = "Return the count of workers. Callers hold the pool lock while counting idle workers. A log line records the start time."
    assert reject( old, "while counting idle workers" ) is None
    assert rules.restated_elsewhere( "Return the count. Do it now and so on.", ( 18, 36 ) ) is False


# ---- rule 6: the writer prompt carries no hint about weakening --------------------------------------------------

HINTS = ( "weak", "strong", "negat", "modal", "quantif", "qualif", "restore", "on purpose", "deliberate", "changed", "altered", "meaning" )


def test_r6_the_writer_prompts_carry_no_hint_about_weakening():
    for text in ( s.WRITER_SYSTEM_PROMPT, *s.INSTRUCTIONS.values() ):
        low = text.lower()
        assert not [ h for h in HINTS if h in low and not ( h == "meaning" and text == s.REWORD_INSTRUCTION ) ], text


# ---- the harness-shaped helpers behind rule 1 --------------------------------------------------------------------

def test_weak_cues_name_what_a_weakened_token_looks_like():
    assert s.weak_cues( "negation", "is" ) == s.NEGATION_CUES
    assert s.weak_cues( "quantifier", "always" ) == frozenset( [ "usually" ] )
    assert s.weak_cues( "modal", "Must" ) == frozenset( [ "may" ] )
    assert s.weak_cues( "number", "3" ) == frozenset( [ "4", "four" ] )
    assert s.weak_cues( "number", "9" ) == frozenset( [ "10" ] )
    assert s.weak_cues( "negation", "never" ) == frozenset( [ "sometimes" ] )
    assert s.weak_cues( "number", "three" ) == frozenset( [ "4", "four" ] )
    assert s.weak_cues( "qualifier", "only" ) == frozenset()
    assert s.weak_cues( "modal", "unknown" ) == frozenset()


def test_token_counts_and_word_regex_match_whole_words_and_the_contraction():
    assert s.token_count( "Only the only one. Lonely.", "only" ) == 2
    assert s.word_regex( "n't" ).search( "it isn't so" ) and s.word_regex( "n't" ).search( "it isn’t so" )
    assert not s.word_regex( "not" ).search( "nothing" )


# ---- rule 1: the mechanical check of one pair ---------------------------------------------------------------------

def pair_of( kind, span, cls=None, token=None ):
    return { "id": "p000", "kind": kind, "x_span_in_old": span, "weaken_class": cls, "changed_token": token }


def test_r1_a_delete_whose_span_is_still_in_the_new_text_fails():
    pair = pair_of( "delete", "when the pool is closed" )
    assert s.check_pair( pair, "task", "It raises when the pool is closed." ) == [ "SPAN_VERBATIM" ]
    assert s.check_pair( pair, "task", "It raises if the pool is shut." ) == []


def test_r1_the_span_comparison_is_normalised():
    pair = pair_of( "delete", "when the pool is closed" )
    assert s.check_pair( pair, "task", "It raises  WHEN the\npool is closed." ) in ( [ "SPAN_VERBATIM" ], [] )
    assert s.check_pair( pair, "task", "It raises when the pool is clo­sed." ) in ( [ "SPAN_VERBATIM" ], [] )


def test_r1_a_weaken_whose_strong_word_came_back_fails_both_ways():
    pair = pair_of( "weaken", "is always safe", "quantifier", "always" )
    task = "The call is usually safe."
    assert s.check_pair( pair, task, "The call is always safe." ) == [ "SPAN_VERBATIM", "WEAK_TOKEN_MISSING", "STRONG_RESTORED" ]
    assert s.check_pair( pair, task, "The call is usually safe, always." ) == [ "STRONG_RESTORED" ]
    assert s.check_pair( pair, task, "The call is usually safe." ) == []


def test_r1_a_weaken_whose_weak_word_is_missing_fails_even_without_the_strong_word():
    pair = pair_of( "weaken", "must hold the lock", "modal", "must" )
    assert s.check_pair( pair, "Callers may hold the lock.", "Callers hold the lock." ) == [ "WEAK_TOKEN_MISSING" ]


def test_r1_a_negation_is_judged_by_its_cue_and_never_by_the_span_or_the_strong_word_count():
    pair = pair_of( "weaken", "The figure is", "negation", "is" )
    task = "The figure is not exact."
    assert s.check_pair( pair, task, "The figure is not exact, and it is stable." ) == []
    assert s.check_pair( pair, task, "The figure isn't exact." ) == []
    assert s.check_pair( pair, task, "The figure is exact." ) == [ "WEAK_TOKEN_MISSING" ]


def test_r1_a_deleted_qualifier_has_no_weak_cue_and_fails_only_when_the_strong_word_returns():
    pair = pair_of( "weaken", "returns only idle workers", "qualifier", "only" )
    task = "It returns idle workers."
    assert s.check_pair( pair, task, "It gives back idle workers." ) == []
    assert s.check_pair( pair, task, "It gives back only idle workers." ) == [ "STRONG_RESTORED" ]


# ---- a written set to check and redraw, on made-up docstrings ------------------------------------------------------

SMALL = { "pairs": 15, "delete": 4, "weaken": 5, "short": 2, "class_floor": 1, "relocate": 2, "paraphrase": 4 }


def docstring( n, filler ):
    lines = [ f"Return the number of idle workers in pool p{n}, or zero when parked.", "",
              "    The count is exact when the pool is open, and it never raises",
              "    if the pool is closed (it returns zero instead). Callers must hold the lock (in practice)",
              f"    for at least three seconds, which keeps the figure of pool p{n} stable. The figure is only a hint and is always safe." ]
    lines += [ f"    Note {chr( 97 + i )} says something distinct about shape {chr( 97 + i )}." for i in range( filler ) ]
    return "\n".join( lines )


def make_pool( units=12, per_unit=6 ):
    return [ { "id": f"d{u:02d}-{k}", "file": f"pkg{u:02d}/mod{k}.py", "symbol": f"f{u * 100 + k + 7}", "old": docstring( u * 100 + k + 7, [ 0, 5, 12 ][ k % 3 ] ) }
             for u in range( units ) for k in range( per_unit ) ]


@pytest.fixture
def written( tmp_path, monkeypatch ):
    """A planned set with a writer output for every task (the task text, reworded by a prefix); returns ( tmp_path, pool path )."""
    root = tmp_path / "fake-repo"
    root.mkdir()
    monkeypatch.setattr( cu, "get_project_root", lambda: str( root ) )
    pool = tmp_path / "pool.jsonl"
    s.write_jsonl( str( pool ), make_pool() )
    args = [ "plan", "--pool", str( pool ), "--out", str( tmp_path / "out" ), "--gate-out", str( tmp_path / "gate-store" ), "--option", "A",
             "--seed", "1", "--gate-seed", "2", "--split-seed", "100", "--sizes-json", json.dumps( { "gate": SMALL, "dev": SMALL } ) ]
    assert s.main( args ) == 0
    for base, split in ( ( tmp_path / "out", "dev" ), ( tmp_path / "gate-store", "gate" ), ( tmp_path / "gate-store", "gate-reserve" ) ):
        plan = json.loads( ( base / split / "plan.json" ).read_text() )
        rows = s.read_jsonl( str( base / split / "writer_tasks.jsonl" ) )
        s.write_jsonl( str( base / split / "writer_outputs.jsonl" ), [ { "task_id": r[ "task_id" ], "text": "Reworded: " + r[ "text" ], "task_sha": plan[ "tasks" ][ r[ "task_id" ] ][ "sha256" ] } for r in rows ] )
        s.write_jsonl( str( base / split / "writer_ledger.jsonl" ), [ { "task_id": r[ "task_id" ], "model": "m", "prompt_hash": s.prompt_hash(), "task_sha": plan[ "tasks" ][ r[ "task_id" ] ][ "sha256" ] } for r in rows ] )
    return tmp_path, str( pool )


def load( base, split ):
    return json.loads( ( base / split / "plan.json" ).read_text() )


def new_task_of( plan, pair_id ):
    return next( t for t, m in plan[ "tasks" ].items() if m[ "pair_id" ] == pair_id and m[ "role" ] == "new" )


def break_outputs( base, split, n=2, skip=() ):
    """Make the first n seeded pairs fail rule 1 by putting the seeded span back in the output; returns their ids."""
    plan    = load( base, split )
    seeded  = [ p for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS and p[ "weaken_class" ] != "negation" and p[ "id" ] not in skip ][ :n ]      # a negation keeps its strong span by design
    path    = str( base / split / "writer_outputs.jsonl" )
    outputs = s.read_jsonl( path )
    for p in seeded:
        tid = new_task_of( plan, p[ "id" ] )
        for row in outputs:
            if row[ "task_id" ] == tid: row[ "text" ] += " " + p[ "x_span_in_old" ]
    s.write_jsonl( path, outputs )
    return sorted( p[ "id" ] for p in seeded )


def test_the_plan_under_the_new_rules_still_meets_every_floor( written ):
    tmp_path, _ = written
    plan = load( tmp_path / "out", "dev" )
    assert len( plan[ "pairs" ] ) == SMALL[ "pairs" ]
    seeded = [ p for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS ]
    assert sum( p[ "short" ] for p in seeded if p[ "kind" ] == "delete" ) >= 1
    assert { p[ "weaken_class" ] for p in plan[ "pairs" ] if p[ "kind" ] == "weaken" } == set( s.WEAKEN_CLASSES )


def test_r1_check_set_passes_a_set_whose_outputs_keep_the_cut_and_the_weak_word( written ):
    tmp_path, _ = written
    failures, checked = s.check_set( str( tmp_path / "out" ), "dev" )
    assert failures == {} and checked == SMALL[ "delete" ] + SMALL[ "weaken" ]


def test_r1_check_set_lists_each_broken_pair_with_its_reason( written ):
    tmp_path, _ = written
    ids = break_outputs( tmp_path / "out", "dev", 2 )
    failures, _ = s.check_set( str( tmp_path / "out" ), "dev" )
    assert sorted( failures ) == ids and all( reasons for reasons in failures.values() )


def test_r1_a_pair_with_no_output_and_one_with_a_stale_output_both_fail( written ):
    tmp_path, _ = written
    base, plan = tmp_path / "out", load( tmp_path / "out", "dev" )
    seeded = [ p for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS ]
    gone, stale = new_task_of( plan, seeded[ 0 ][ "id" ] ), new_task_of( plan, seeded[ 1 ][ "id" ] )
    path = str( base / "dev" / "writer_outputs.jsonl" )
    rows = [ r for r in s.read_jsonl( path ) if r[ "task_id" ] != gone ]
    for r in rows:
        if r[ "task_id" ] == stale: r[ "task_sha" ] = "0" * 64
    s.write_jsonl( path, rows )
    failures, _ = s.check_set( str( base ), "dev" )
    assert failures == { seeded[ 0 ][ "id" ]: [ "NO_OUTPUT" ], seeded[ 1 ][ "id" ]: [ "STALE_OUTPUT" ] }


def test_r1_check_set_with_no_output_file_at_all_fails_every_seeded_pair( written ):
    tmp_path, _ = written
    ( tmp_path / "out" / "dev" / "writer_outputs.jsonl" ).unlink()
    failures, checked = s.check_set( str( tmp_path / "out" ), "dev" )
    assert len( failures ) == checked and {r[ 0 ] for r in failures.values()} == { "NO_OUTPUT" }


def test_r1_check_set_refuses_an_edited_plan_and_a_task_file_that_lacks_a_task( written ):
    tmp_path, _ = written
    base = tmp_path / "out"
    rows = s.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) )
    plan = load( base, "dev" )
    seeded_tid = new_task_of( plan, next( p[ "id" ] for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS ) )
    s.write_jsonl( str( base / "dev" / "writer_tasks.jsonl" ), [ r for r in rows if r[ "task_id" ] != seeded_tid ] )
    with pytest.raises( ValueError, match="lacks task" ): s.check_set( str( base ), "dev" )
    plan[ "units" ] = plan[ "units" ] + [ "edit" ]
    ( base / "dev" / "plan.json" ).write_text( json.dumps( plan ) )
    with pytest.raises( ValueError, match="does not match the hash" ): s.check_set( str( base ), "dev" )


def test_r1_the_check_command_exits_0_when_clean_1_when_a_pair_fails_and_2_when_refused( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    assert s.main( [ "check", "--base", str( base ), "--split", "dev" ] ) == 0
    assert f"{SMALL[ 'delete' ] + SMALL[ 'weaken' ]} seeded pairs, 0 fail" in capsys.readouterr().out
    ids = break_outputs( base, "dev", 2 )
    assert s.main( [ "check", "--base", str( base ), "--split", "dev" ] ) == 1
    out = capsys.readouterr().out
    assert "2 fail" in out and all( i in out for i in ids )
    assert s.main( [ "check", "--base", str( base ), "--split", "nowhere" ] ) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_r1_verify_refuses_while_the_check_fails_and_writes_nothing( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    ids = break_outputs( base, "dev", 1 )
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev" ] ) == 2
    assert ids[ 0 ] in capsys.readouterr().err and not ( base / "dev" / "verify-input.jsonl" ).exists()


def test_r1_verify_goes_on_when_the_check_passes( written ):
    tmp_path, _ = written
    assert s.main( [ "verify", "--base", str( tmp_path / "out" ), "--split", "dev" ] ) == 0


# ---- redraw: replace the failed pairs, keep every floor, count the calls before any call ---------------------------------

def redraw_args( tmp_path, pool, split="gate", base="gate-store", **over ):
    args = [ "redraw", "--base", str( tmp_path / base ), "--split", split, "--pool", pool, "--out", str( tmp_path / "redrawn" ), "--seed", "7" ]
    for k, v in over.items(): args += [ f"--{k.replace( '_', '-' )}", v ]
    return args


def floors_of( plan ):
    seeded = [ p for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS ]
    return ( sorted( ( p[ "kind" ], p[ "weaken_class" ], p[ "short" ], p[ "stratum" ] ) for p in plan[ "pairs" ] ), len( seeded ) )


def test_redraw_replaces_the_failed_pairs_keeps_floors_and_states_the_call_count_first( written, capsys ):
    tmp_path, pool = written
    gate = tmp_path / "gate-store"
    before_plan = load( gate, "gate" )
    ids = break_outputs( gate, "gate", 2 )
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    out = capsys.readouterr().out
    assert f"2 failed pair(s) {' '.join( ids )} are replaced; 2 new writer call(s) needed, up to 4 with one retry each; no model call made" in out
    new_plan = load( tmp_path / "redrawn", "gate" )
    s.check_plan_hash( new_plan )
    assert floors_of( new_plan ) == floors_of( before_plan )
    assert [ p[ "id" ] for p in new_plan[ "pairs" ] ] == [ p[ "id" ] for p in before_plan[ "pairs" ] ]
    changed = [ p[ "id" ] for p, q in zip( before_plan[ "pairs" ], new_plan[ "pairs" ] ) if p != q ]
    assert changed == ids and new_plan[ "redrawn" ] == { "pairs": ids, "from_plan_sha256": before_plan[ "plan_sha256" ] }
    kept_pool_ids = [ p[ "pool_id" ] for p in new_plan[ "pairs" ] ]
    assert len( set( kept_pool_ids ) ) == len( kept_pool_ids )                         # no docstring used twice in the split
    for old_p, new_p in zip( before_plan[ "pairs" ], new_plan[ "pairs" ] ):
        if old_p[ "id" ] in ids: assert new_p[ "x_span_in_old" ] != old_p[ "x_span_in_old" ] or new_p[ "pool_id" ] != old_p[ "pool_id" ]


def test_redraw_leaves_the_source_alone_and_the_new_folder_needs_only_the_new_calls( written, capsys ):
    tmp_path, pool = written
    gate = tmp_path / "gate-store"
    ids = break_outputs( gate, "gate", 2 )
    snapshot = { name: ( gate / "gate" / name ).read_bytes() for name in ( "plan.json", "writer_tasks.jsonl", "writer_outputs.jsonl", "writer_ledger.jsonl" ) }
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    assert snapshot == { name: ( gate / "gate" / name ).read_bytes() for name in snapshot }
    target = tmp_path / "redrawn" / "gate"
    plan   = load( tmp_path / "redrawn", "gate" )
    tasks  = s.read_jsonl( str( target / "writer_tasks.jsonl" ) )
    assert {r[ "task_id" ] for r in tasks} == set( plan[ "tasks" ] )
    done = {r[ "task_id" ] for r in s.read_jsonl( str( target / "writer_ledger.jsonl" ) )}
    assert {r[ "task_id" ] for r in s.read_jsonl( str( target / "writer_outputs.jsonl" ) )} == done
    pending = [ t for t in plan[ "tasks" ] if t not in done ]
    assert sorted( plan[ "tasks" ][ t ][ "pair_id" ] for t in pending ) == ids                  # exactly the replaced pairs still need a call
    failures, _ = s.check_set( str( tmp_path / "redrawn" ), "gate" )
    assert sorted( failures ) == ids and {r[ 0 ] for r in failures.values()} == { "NO_OUTPUT" }


def test_redraw_of_a_reserve_split_carries_the_new_hash_in_plan_hashes( written ):
    tmp_path, pool = written
    gate = tmp_path / "gate-store"
    break_outputs( gate, "gate-reserve", 1 )
    assert s.main( redraw_args( tmp_path, pool, split="gate-reserve" ) ) == 0
    hashes = json.loads( ( tmp_path / "redrawn" / "plan-hashes.json" ).read_text() )
    old    = json.loads( ( gate / "plan-hashes.json" ).read_text() )
    assert hashes[ "reserve_plan_sha256" ] == load( tmp_path / "redrawn", "gate-reserve" )[ "plan_sha256" ] != old[ "reserve_plan_sha256" ]
    assert hashes[ "gate_plan_sha256" ] == old[ "gate_plan_sha256" ]
    break_outputs( gate, "gate", 1 )
    (tmp_path / "redrawn").rename( tmp_path / "redrawn-reserve" )
    assert s.main( redraw_args( tmp_path, pool, split="gate" ) ) == 0
    assert json.loads( ( tmp_path / "redrawn" / "plan-hashes.json" ).read_text() )[ "gate_plan_sha256" ] == load( tmp_path / "redrawn", "gate" )[ "plan_sha256" ]


def test_redraw_of_dev_takes_its_scope_from_a_given_split_seed_or_from_the_plans_own_units( written, capsys ):
    tmp_path, pool = written
    break_outputs( tmp_path / "out", "dev", 1 )
    assert s.main( redraw_args( tmp_path, pool, split="dev", base="out", split_seed="100" ) ) == 0
    assert "1 failed pair(s)" in capsys.readouterr().out
    (tmp_path / "redrawn").rename( tmp_path / "again" )
    assert s.main( redraw_args( tmp_path, pool, split="dev", base="out" ) ) in ( 0, 2 )     # plan units only: a replacement may not exist


def test_redraw_with_nothing_failing_writes_nothing( written, capsys ):
    tmp_path, pool = written
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    assert "nothing to redraw" in capsys.readouterr().out and not ( tmp_path / "redrawn" ).exists()


def test_redraw_refuses_a_changed_pool_an_existing_target_and_a_gate_target_inside_the_repo( written, capsys ):
    tmp_path, pool = written
    break_outputs( tmp_path / "gate-store", "gate", 1 )
    other = tmp_path / "other-pool.jsonl"
    s.write_jsonl( str( other ), make_pool( units=13 ) )
    assert s.main( redraw_args( tmp_path, str( other ) ) ) == 2
    assert "not the one this plan was drawn from" in capsys.readouterr().err
    ( tmp_path / "redrawn" / "gate" ).mkdir( parents=True )
    assert s.main( redraw_args( tmp_path, pool ) ) == 2
    assert "already exists" in capsys.readouterr().err
    inside = cu.get_project_root()
    assert s.main( [ "redraw", "--base", str( tmp_path / "gate-store" ), "--split", "gate", "--pool", pool, "--out", inside + "/x", "--seed", "7" ] ) == 2
    assert "inside the repo" in capsys.readouterr().err


def test_redraw_refuses_when_no_replacement_keeps_a_floor_and_writes_nothing( written, capsys, monkeypatch ):
    tmp_path, pool = written
    break_outputs( tmp_path / "gate-store", "gate", 1 )
    monkeypatch.setattr( s, "build_docs", lambda pool_rows, stoplist, exclude=frozenset(): ( { kind: [] for kind in s.KINDS }, [] ) )
    assert s.main( redraw_args( tmp_path, pool ) ) == 2
    assert "nothing in scope replaces" in capsys.readouterr().err and not ( tmp_path / "redrawn" ).exists()


def test_redraw_honours_an_exclude_file( written ):
    tmp_path, pool = written
    break_outputs( tmp_path / "gate-store", "gate", 1 )
    plan = load( tmp_path / "gate-store", "gate" )
    ex   = tmp_path / "ex.json"
    ex.write_text( json.dumps( [ "d00-0" ] ) )
    assert s.main( redraw_args( tmp_path, pool, exclude=str( ex ) ) ) == 0
    assert "d00-0" not in {p[ "pool_id" ] for p in load( tmp_path / "redrawn", "gate" )[ "pairs" ] if p not in plan[ "pairs" ]}


def test_redraw_is_deterministic_for_one_seed( written ):
    tmp_path, pool = written
    break_outputs( tmp_path / "gate-store", "gate", 2 )
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    first = ( tmp_path / "redrawn" / "gate" / "plan.json" ).read_bytes()
    (tmp_path / "redrawn").rename( tmp_path / "again" )
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    assert ( tmp_path / "redrawn" / "gate" / "plan.json" ).read_bytes() == first


# ---- redraw: a task id minted by one round must not take another pair's id (row e86e07b1) ------------------------------

class ForcedTaskId( random.Random ):
    """A Random whose first 64-bit draw is a chosen value.

    Every other draw is the seeded one, so a task id collision can be forced.
    """
    forced = []

    def getrandbits( self, k ):
        if k == 64 and ForcedTaskId.forced: return ForcedTaskId.forced.pop( 0 )
        return super().getrandbits( k )


def test_make_pair_draws_again_when_its_task_id_is_already_taken():
    d      = { "pool_id": "x", "file": "a/b.py", "symbol": "f", "old": "o", "stratum": "S" }
    taken  = "t%016x" % random.Random( 1 ).getrandbits( 64 )
    tasks  = { taken: { "pair_id": "p001", "role": "new", "sha256": "kept" } }
    rows   = []
    s.make_pair( "p000", "delete", d, { "span_text": "- keep the lock", "cut": "c" }, random.Random( 1 ), tasks, rows )
    assert tasks[ taken ] == { "pair_id": "p001", "role": "new", "sha256": "kept" }
    assert len( tasks ) == 2 and rows[ 0 ][ "task_id" ] != taken and rows[ 0 ][ "task_id" ] in tasks


def test_redraw_with_a_task_id_that_collides_with_a_kept_pair_keeps_every_pairs_new_task( written, monkeypatch ):
    tmp_path, pool = written
    gate   = tmp_path / "gate-store"
    before = load( gate, "gate" )
    ids    = break_outputs( gate, "gate", 1 )
    kept   = next( t for t, m in before[ "tasks" ].items() if m[ "pair_id" ] not in ids and m[ "role" ] == "new" )
    ForcedTaskId.forced = [ int( kept[ 1: ], 16 ) ]
    monkeypatch.setattr( s.random, "Random", ForcedTaskId )
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    new_plan = load( tmp_path / "redrawn", "gate" )
    assert len( new_plan[ "tasks" ] ) == len( before[ "tasks" ] )
    assert new_plan[ "tasks" ][ kept ] == before[ "tasks" ][ kept ]
    assert all( any( m[ "pair_id" ] == p[ "id" ] and m[ "role" ] == "new" for m in new_plan[ "tasks" ].values() ) for p in new_plan[ "pairs" ] )
    s.check_set( str( tmp_path / "redrawn" ), "gate" )                                   # the StopIteration of the row


def test_two_redraw_rounds_with_one_seed_leave_every_pair_its_own_task( written, capsys ):
    tmp_path, pool = written
    gate   = tmp_path / "gate-store"
    first  = break_outputs( gate, "gate", 1 )
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    round1 = tmp_path / "redrawn"
    plan1  = load( round1, "gate" )
    path   = str( round1 / "gate" / "writer_outputs.jsonl" )
    done   = { r[ "task_id" ] for r in s.read_jsonl( path ) }
    s.write_jsonl( path, s.read_jsonl( path ) + [ { "task_id": t, "text": "Reworded: " + r[ "text" ], "task_sha": plan1[ "tasks" ][ t ][ "sha256" ] }
                                                  for r in s.read_jsonl( str( round1 / "gate" / "writer_tasks.jsonl" ) ) for t in [ r[ "task_id" ] ] if t not in done ] )
    second = break_outputs( round1, "gate", 1, skip=first )
    assert second != first
    args = [ "redraw", "--base", str( round1 ), "--split", "gate", "--pool", pool, "--out", str( tmp_path / "round2" ), "--seed", "7" ]
    assert s.main( args ) == 0
    plan2 = load( tmp_path / "round2", "gate" )
    assert len( plan2[ "tasks" ] ) == len( plan1[ "tasks" ] )
    assert all( any( m[ "pair_id" ] == p[ "id" ] and m[ "role" ] == "new" for m in plan2[ "tasks" ].values() ) for p in plan2[ "pairs" ] )


def test_redraw_refuses_and_writes_nothing_when_a_pair_is_left_without_a_new_task( written, capsys, monkeypatch ):
    tmp_path, pool = written
    break_outputs( tmp_path / "gate-store", "gate", 1 )
    real = s.make_pair
    def lossy( pair_id, kind, d, c, rng, tasks, task_rows ):
        rec = real( pair_id, kind, d, c, rng, tasks, task_rows )
        for t in [ t for t, m in tasks.items() if m[ "pair_id" ] == pair_id ]: del tasks[ t ]
        return rec
    monkeypatch.setattr( s, "make_pair", lossy )
    assert s.main( redraw_args( tmp_path, pool ) ) == 2
    assert "no new writer task" in capsys.readouterr().err and not ( tmp_path / "redrawn" ).exists()


def test_redraw_never_redraws_the_span_that_failed():
    plan = { "pairs": [ { "id": "p000", "kind": "delete", "weaken_class": None, "short": False, "stratum": "S", "pool_id": "d1", "x_span_in_old": "when the pool is closed" } ] }
    doc  = lambda *spans: { "pool_id": "d1", "unit": "u", "stratum": "S", "cands": [ { "span_text": sp } for sp in spans ] }
    with pytest.raises( s.Shortfall, match="nothing in scope replaces p000" ):
        s.redraw_pairs( plan, {"p000"}, { "delete": [ doc( "when the pool is closed" ) ] }, {"u"}, __import__( "random" ).Random( 1 ) )
    got = s.redraw_pairs( plan, {"p000"}, { "delete": [ doc( "when the pool is closed", "if the pool is open" ) ] }, {"u"}, __import__( "random" ).Random( 1 ) )
    assert got[ "p000" ][ 2 ][ "span_text" ] == "if the pool is open"


# ---- redraw --failed: replace the pairs a second reader failed, whatever rule 1 says ------------------------------

def test_redraw_failed_replaces_a_pair_rule_1_passes_of_every_kind_keeps_its_id_and_every_floor( written, capsys ):
    tmp_path, pool = written
    gate   = tmp_path / "gate-store"
    before = load( gate, "gate" )
    assert s.check_set( str( gate ), "gate" )[ 0 ] == {}
    for kind in s.KINDS:
        target = tmp_path / ( "redrawn" if kind == s.KINDS[ 0 ] else "redrawn-" + kind )
        pair   = next( p for p in before[ "pairs" ] if p[ "kind" ] == kind )
        args   = redraw_args( tmp_path, pool, failed=write_accept( tmp_path, [ pair[ "id" ] ], f"failed-{kind}.json" ) )
        args[ args.index( "--out" ) + 1 ] = str( target )
        assert s.main( args ) == 0, kind
        after  = json.loads( ( target / "gate" / "plan.json" ).read_text() )
        s.check_plan_hash( after )
        assert floors_of( after ) == floors_of( before ), kind
        assert [ p[ "id" ] for p in after[ "pairs" ] ] == [ p[ "id" ] for p in before[ "pairs" ] ]
        assert [ p[ "id" ] for p, q in zip( before[ "pairs" ], after[ "pairs" ] ) if p != q ] == [ pair[ "id" ] ], kind
        new = next( p for p in after[ "pairs" ] if p[ "id" ] == pair[ "id" ] )
        assert new[ "kind" ] == kind and ( new[ "pool_id" ], new[ "x_span_in_old" ] ) != ( pair[ "pool_id" ], pair[ "x_span_in_old" ] ), kind
        pool_ids = [ p[ "pool_id" ] for p in after[ "pairs" ] ]
        assert len( set( pool_ids ) ) == len( pool_ids ), kind
        tasks = 2 if kind == "relocate" else 1
        assert f"1 failed pair(s) {pair[ 'id' ]} are replaced; {tasks} new writer call(s) needed, up to {2 * tasks} with one retry each" in capsys.readouterr().out, kind
        done = { r[ "task_id" ] for r in s.read_jsonl( str( target / "gate" / "writer_ledger.jsonl" ) ) }
        assert len( [ t for t in after[ "tasks" ] if t not in done ] ) == tasks, kind


def test_redraw_failed_adds_to_the_rule_1_failures_and_a_pair_named_twice_is_replaced_once( written, capsys ):
    tmp_path, pool = written
    gate   = tmp_path / "gate-store"
    broken = break_outputs( gate, "gate", 1 )
    other  = next( p[ "id" ] for p in load( gate, "gate" )[ "pairs" ] if p[ "kind" ] == "paraphrase" )
    failed = write_accept( tmp_path, [ other, broken[ 0 ], other ] )
    assert s.main( redraw_args( tmp_path, pool, failed=failed ) ) == 0
    ids = sorted( [ other, broken[ 0 ] ] )
    assert f"2 failed pair(s) {' '.join( ids )} are replaced; 2 new writer call(s) needed" in capsys.readouterr().out
    assert load( tmp_path / "redrawn", "gate" )[ "redrawn" ][ "pairs" ] == ids


@pytest.mark.parametrize( "content, message", [
    ( "{\"p000\": 1}", "must hold a JSON list of pair ids" ), ( "[1, 2]", "must hold a JSON list of pair ids" ),
    ( "[\"p000\", \"p999\", \"p998\"]", "names pairs that are not in the plan: p998 p999" ), ( "[", "Expecting value" ) ] )
def test_redraw_failed_refuses_a_file_that_is_not_a_list_of_strings_or_names_an_unknown_pair_and_writes_nothing( written, capsys, content, message ):
    tmp_path, pool = written
    path = tmp_path / "failed.json"
    path.write_text( content )
    assert s.main( redraw_args( tmp_path, pool, failed=str( path ) ) ) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and message in err and not ( tmp_path / "redrawn" ).exists()


def test_redraw_failed_refuses_a_file_that_is_not_there_and_writes_nothing( written, capsys ):
    tmp_path, pool = written
    assert s.main( redraw_args( tmp_path, pool, failed=str( tmp_path / "nowhere.json" ) ) ) == 2
    assert "REFUSED" in capsys.readouterr().err and not ( tmp_path / "redrawn" ).exists()


def test_redraw_failed_with_an_empty_list_and_no_rule_1_failure_changes_nothing( written, capsys ):
    tmp_path, pool = written
    assert s.main( redraw_args( tmp_path, pool, failed=write_accept( tmp_path, [] ) ) ) == 0
    assert "nothing to redraw" in capsys.readouterr().out and not ( tmp_path / "redrawn" ).exists()


def test_redraw_never_redraws_the_relocate_sentence_or_the_paraphrase_docstring_that_failed():
    doc   = lambda pool_id, cands: { "pool_id": pool_id, "unit": "u", "stratum": "S", "cands": cands }
    pair  = lambda kind, span: { "pairs": [ { "id": "p000", "kind": kind, "weaken_class": None, "short": False, "stratum": "S", "pool_id": "d1", "x_span_in_old": span } ] }
    wait  = { "sentence": "Callers wait here.", "cut": "x" }
    retry = { "sentence": "Callers retry here.", "cut": "y" }
    with pytest.raises( s.Shortfall, match="nothing in scope replaces p000" ):
        s.redraw_pairs( pair( "relocate", "Callers wait here." ), { "p000" }, { "relocate": [ doc( "d1", [ wait ] ) ] }, { "u" }, random.Random( 1 ) )
    got = s.redraw_pairs( pair( "relocate", "Callers wait here." ), { "p000" }, { "relocate": [ doc( "d1", [ wait, retry ] ) ] }, { "u" }, random.Random( 1 ) )
    assert got[ "p000" ][ 2 ] is retry
    with pytest.raises( s.Shortfall, match="nothing in scope replaces p000" ):
        s.redraw_pairs( pair( "paraphrase", "" ), { "p000" }, { "paraphrase": [ doc( "d1", [ { "text": "t" } ] ) ] }, { "u" }, random.Random( 1 ) )
    got = s.redraw_pairs( pair( "paraphrase", "" ), { "p000" }, { "paraphrase": [ doc( "d1", [ { "text": "t" } ] ), doc( "d2", [ { "text": "u" } ] ) ] }, { "u" }, random.Random( 1 ) )
    assert got[ "p000" ][ 1 ][ "pool_id" ] == "d2"


def capture_scope( monkeypatch ):
    seen = {}
    real = s.redraw_pairs
    def spy( plan, failing, docs_by_kind, scope, rng ):
        seen[ "scope" ] = set( scope )
        return real( plan, failing, docs_by_kind, scope, rng )
    monkeypatch.setattr( s, "redraw_pairs", spy )
    return seen


def pool_units( pool ):
    return sorted( { s.unit_of( r[ "file" ] ) for r in s.read_jsonl( pool ) } )


def test_redraw_draws_a_gate_replacement_from_the_units_the_plans_split_seed_gives_that_split( written, monkeypatch ):
    tmp_path, pool = written
    break_outputs( tmp_path / "gate-store", "gate", 1 )
    seen = capture_scope( monkeypatch )
    assert s.main( redraw_args( tmp_path, pool ) ) == 0
    assert seen[ "scope" ] == set( s.partition_units( pool_units( pool ), 100 )[ "gate" ] )


def test_redraw_takes_a_given_split_seed_over_the_plans_and_falls_back_to_the_plans_own_units( written, monkeypatch ):
    tmp_path, pool = written
    break_outputs( tmp_path / "out", "dev", 1 )
    seen = capture_scope( monkeypatch )
    s.main( redraw_args( tmp_path, pool, split="dev", base="out", split_seed="101" ) )
    assert seen[ "scope" ] == set( s.partition_units( pool_units( pool ), 101 )[ "dev" ] )
    if ( tmp_path / "redrawn" ).exists(): (tmp_path / "redrawn").rename( tmp_path / "again" )
    s.main( redraw_args( tmp_path, pool, split="dev", base="out" ) )
    assert seen[ "scope" ] == set( load( tmp_path / "out", "dev" )[ "units" ] )


# ---- review of a754c102f: the four boundaries the mutation run found untested ------------------------------

def test_r4_a_sentence_of_exactly_three_words_is_refused_and_one_of_four_is_not():
    old3 = "Return the count of workers. Callers wait here, which is stable. Callers retry on failure."
    assert reject( old3, "which is stable" ) == "SHORT_SENTENCE"                                                      # leaves "Callers wait here." : 3 words
    old4 = "Return the count of workers. Callers wait here now, which is stable. Callers retry on failure."
    assert reject( old4, "which is stable" ) is None                                                                  # leaves 4 words


def test_r3_a_sentence_sharing_exactly_two_content_words_with_an_exclusion_cue_blocks_the_deletion_and_one_word_does_not():
    head  = "Return the count of workers. The call returns only idle workers of the open pool."
    two   = head + " Busy workers are never returned."                         # shares workers + ... see content words below
    assert len( rules.content_words( "The call returns only idle workers of the open pool." ) & rules.content_words( "Busy workers are never returned." ) ) == 1
    assert qualifier_spans( two )                                                # one shared word: not blocked
    shared2 = head + " Idle workers are never returned."
    assert len( rules.content_words( "The call returns only idle workers of the open pool." ) & rules.content_words( "Idle workers are never returned." ) ) == 2
    assert qualifier_spans( shared2 ) == []                                      # two shared words: blocked


def test_r4_a_span_that_starts_in_the_summary_and_ends_after_it_is_refused():
    old  = "Return the count of workers. Callers hold the lock here."
    span = ( old.index( "workers" ), old.index( "Callers" ) + len( "Callers" ) )
    assert span[ 0 ] < rules.first_sentence_end( old ) < span[ 1 ]
    assert rules.delete_rejection( old, span, s.cut_text( old, span ) ) == "SUMMARY"


def test_r4_a_heading_that_was_already_empty_is_not_blamed_on_the_cut():
    old = "Return the count of workers.\n\nRaises:\n\nEnsures:\n    the count is exact, and it is never negative\n"
    assert rules.structure_emptied( old, old ) is None
    assert reject( old, "and it is never negative" ) is None


# ---- accepting the pairs a reader judged fine (rule 1 false alarms on a synonym) ---------------------------

def synonym_pair( base, split ):
    """Reword the weak word of one weaken pair to a word the cue set lacks; returns that pair's id."""
    plan    = load( base, split )
    path    = str( base / split / "writer_outputs.jsonl" )
    outputs = s.read_jsonl( path )
    for pair in plan[ "pairs" ]:
        cues = s.weak_cues( pair[ "weaken_class" ], pair[ "changed_token" ] ) if pair[ "kind" ] == "weaken" else frozenset()
        if not cues or pair[ "weaken_class" ] == "negation": continue
        tid = new_task_of( plan, pair[ "id" ] )
        for row in outputs:
            if row[ "task_id" ] == tid:
                for cue in cues: row[ "text" ] = s.word_regex( cue ).sub( "perchance", row[ "text" ] )
        s.write_jsonl( path, outputs )
        return pair[ "id" ]
    raise AssertionError( "no weaken pair with a cue" )


def write_accept( tmp_path, ids, name="accept.json" ):
    path = tmp_path / name
    path.write_text( json.dumps( ids ) )
    return str( path )


def test_accept_verify_refuses_a_synonym_false_alarm_and_goes_on_when_a_reader_accepts_it( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    pid  = synonym_pair( base, "dev" )
    assert s.check_set( str( base ), "dev" )[ 0 ] == { pid: [ "WEAK_TOKEN_MISSING" ] }
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev" ] ) == 2
    capsys.readouterr()
    accept = write_accept( tmp_path, [ pid ] )
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev", "--accept", accept ] ) == 0
    assert "rule 1: accepted 1 pair(s)" in capsys.readouterr().out
    record = json.loads( ( base / "dev" / "rule1-accepted.json" ).read_text() )
    assert record == { "accepted": { pid: [ "WEAK_TOKEN_MISSING" ] }, "accept_file_sha256": s.sha256_file( accept ) }
    assert ( base / "dev" / "verify-input.jsonl" ).exists()


def test_accept_a_pair_that_passes_anyway_is_ignored_and_the_count_says_zero( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    plan = load( base, "dev" )
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev", "--accept", write_accept( tmp_path, [ plan[ "pairs" ][ 0 ][ "id" ] ] ) ] ) == 0
    assert "accepted 0 pair(s)" in capsys.readouterr().out


def test_accept_cannot_waive_a_pair_that_fails_for_another_reason( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    bad  = break_outputs( base, "dev", 1 )[ 0 ]
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev", "--accept", write_accept( tmp_path, [ bad ] ) ] ) == 2
    err = capsys.readouterr().err
    assert f"cannot accept {bad}" in err and "WEAK_TOKEN_MISSING can be accepted" in err
    assert not ( base / "dev" / "verify-input.jsonl" ).exists()


def damage_one( base, split, kind, mutate, want ):
    """Apply mutate( pair, text ) to the writer's new text of one pair of this kind until rule 1 fails it for exactly the reasons in want; returns its id."""
    plan     = load( base, split )
    path     = str( base / split / "writer_outputs.jsonl" )
    original = s.read_jsonl( path )
    for pair in plan[ "pairs" ]:
        if pair[ "kind" ] != kind or pair[ "weaken_class" ] == "negation": continue
        if kind == "weaken" and not s.weak_cues( pair[ "weaken_class" ], pair[ "changed_token" ] ): continue
        tid  = new_task_of( plan, pair[ "id" ] )
        rows = [ dict( r, text=mutate( pair, r[ "text" ] ) if r[ "task_id" ] == tid else r[ "text" ] ) for r in original ]
        s.write_jsonl( path, rows )
        if s.check_set( str( base ), split )[ 0 ].get( pair[ "id" ] ) == want: return pair[ "id" ]
    s.write_jsonl( path, original )
    raise AssertionError( f"no {kind} pair can be made to fail for exactly {want}" )


def reword( pair, text ):
    for cue in s.weak_cues( pair[ "weaken_class" ], pair[ "changed_token" ] ): text = s.word_regex( cue ).sub( "perchance", text )
    return text


def refused_accept( tmp_path, base, pid, capsys, reasons ):
    """An --accept naming pid is refused, names the pid and its reasons, and verify goes no further."""
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev", "--accept", write_accept( tmp_path, [ pid ] ) ] ) == 2
    err = capsys.readouterr().err
    assert f"cannot accept {pid} ({reasons})" in err and "only WEAK_TOKEN_MISSING can be accepted" in err
    assert not ( base / "dev" / "verify-input.jsonl" ).exists() and not ( base / "dev" / "rule1-accepted.json" ).exists()


def test_accept_refuses_a_pair_whose_only_failure_is_a_restored_strong_word( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    pid  = damage_one( base, "dev", "weaken", lambda p, text: text + " " + p[ "changed_token" ], [ "STRONG_RESTORED" ] )
    refused_accept( tmp_path, base, pid, capsys, "STRONG_RESTORED" )


def test_accept_refuses_a_pair_whose_only_failure_is_the_seeded_span_coming_back( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    pid  = damage_one( base, "dev", "delete", lambda p, text: text + " " + p[ "x_span_in_old" ], [ "SPAN_VERBATIM" ] )
    refused_accept( tmp_path, base, pid, capsys, "SPAN_VERBATIM" )


def test_accept_refuses_a_pair_that_misses_the_weak_word_and_also_fails_another_rule( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    pid  = damage_one( base, "dev", "weaken", lambda p, text: reword( p, text ) + " " + p[ "changed_token" ], [ "WEAK_TOKEN_MISSING", "STRONG_RESTORED" ] )
    refused_accept( tmp_path, base, pid, capsys, "WEAK_TOKEN_MISSING STRONG_RESTORED" )


def test_accept_refuses_a_file_that_is_not_a_list_of_ids_names_an_unknown_pair_or_is_missing( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    for payload, words in ( ( { "p000": 1 }, "must hold a JSON list" ), ( [ 1 ], "must hold a JSON list" ), ( [ "p999" ], "not in the plan: p999" ) ):
        assert s.main( [ "verify", "--base", str( base ), "--split", "dev", "--accept", write_accept( tmp_path, payload ) ] ) == 2
        assert words in capsys.readouterr().err
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev", "--accept", str( tmp_path / "no-such.json" ) ] ) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_accept_check_counts_the_accepted_pair_and_exits_0( written, capsys ):
    tmp_path, _ = written
    base = tmp_path / "out"
    pid  = synonym_pair( base, "dev" )
    assert s.main( [ "check", "--base", str( base ), "--split", "dev" ] ) == 1
    capsys.readouterr()
    assert s.main( [ "check", "--base", str( base ), "--split", "dev", "--accept", write_accept( tmp_path, [ pid ] ) ] ) == 0
    assert "0 fail, 1 accepted by a reader" in capsys.readouterr().out


def test_accept_redraw_leaves_an_accepted_pair_alone_and_replaces_only_the_rest( written, capsys ):
    tmp_path, pool = written
    gate = tmp_path / "gate-store"
    kept = synonym_pair( gate, "gate" )
    broken = break_outputs( gate, "gate", 3, skip=( kept, ) )
    assert broken
    accept = write_accept( tmp_path, [ kept ] )
    assert s.main( redraw_args( tmp_path, pool, accept=accept ) ) == 0
    named = capsys.readouterr().out.split( "failed pair(s) " )[ 1 ].split( " are replaced" )[ 0 ].split()
    assert named == sorted( broken ) and kept not in named


# ---- rule 8 (row 9d3f4562): a span is never drawn inside inline code, a [reference] link, or the opening of a list item ----
# Every text below is made up, in the shape of a Dart doc comment with its /// markers removed.

SUMMARY = "Return the cached session for the signed-in user. "


def delete_spans( old ):
    return sorted( c[ "span_text" ] for c in s.delete_candidates( old, SL )[ 0 ] )


def refusals( old ):
    return s.delete_candidates( old, SL )[ 1 ]


def span_of( old, text ):
    start = old.index( text )
    return ( start, start + len( text ) )


def test_r8_a_delete_that_cuts_into_backticks_is_refused_and_the_same_words_in_prose_are_candidates():
    marked = SUMMARY + "Callers pass `retry: true, backoff: slow` to the reader when the lock is busy."
    plain  = marked.replace( "`", "" )
    assert "true, backoff" in delete_spans( plain )                                          # the control: without the backticks the phrase is a candidate
    assert delete_spans( marked ) == [ "when the lock is busy" ]
    assert refusals( marked )[ "CODE" ] == 4 and "CODE" not in refusals( plain )


def test_r8_a_delete_that_cuts_into_a_code_fence_is_refused():
    old = SUMMARY + "The reader waits for the lock.\n\n```\nopen( retry, backoff ) when the lock is busy\n```\n\nThe handle is closed after the read."
    assert rules.markup_rejection( old, span_of( old, "when the lock is busy" ) ) == "CODE"
    assert rules.markup_rejection( old, span_of( old, "The handle is closed after the read" ) ) is None


def test_r8_a_delete_that_cuts_into_a_reference_link_is_refused_and_one_that_holds_the_whole_link_is_kept():
    old = SUMMARY + "The handle stays open while [SessionStore.open, SessionStore.close] keep the count above zero."
    assert delete_spans( old ) == [ "while [SessionStore.open, SessionStore.close] keep the count above zero" ]
    assert refusals( old )[ "LINK" ] == 3


def test_r8_a_delete_of_a_markdown_link_target_or_of_its_text_alone_is_refused():
    old = SUMMARY + "Callers read [the session guide](docs/session.md) before they change how the handle is kept."
    assert delete_spans( old ) == [ "before they change how the handle is kept" ]
    assert rules.markup_rejection( old, span_of( old, "(docs/session.md)" ) ) == "LINK"
    assert rules.markup_rejection( old, span_of( old, "Callers read [the session guide]" ) ) == "LINK"
    labelled = "See [the session guide][guide] first."
    assert rules.markup_rejection( labelled, span_of( labelled, "[guide] first" ) ) == "LINK"


def test_r8_a_delete_that_holds_a_whole_code_span_is_kept():
    old = SUMMARY + "The reader waits for the lock, which `SessionStore` releases on close, before it reads the handle."
    assert "which `SessionStore` releases on close" in delete_spans( old )
    assert "CODE" not in refusals( old )


LISTED = SUMMARY.strip() + "\n\n- keeps the handle open for the reader, which avoids a second login\n- drops the handle when the app is paused, unless a write is running"


def test_r8_a_delete_that_removes_the_opening_of_a_list_item_is_refused_and_a_trailing_clause_is_kept():
    assert rules.markup_rejection( LISTED, span_of( LISTED, "drops the handle when the app is paused" ) ) == "LIST_ITEM"
    assert rules.markup_rejection( LISTED, span_of( LISTED, "keeps the handle open for the reader, which avoids a second login" ) ) == "LIST_ITEM"
    assert rules.markup_rejection( LISTED, span_of( LISTED, "unless a write is running" ) ) is None
    assert "unless a write is running" in delete_spans( LISTED )


def test_r8_a_delete_that_runs_from_one_line_into_the_next_list_item_is_refused():
    assert rules.markup_rejection( LISTED, span_of( LISTED, "which avoids a second login\n- drops the handle" ) ) == "LIST_ITEM"
    assert all( "\n" not in span for span in delete_spans( LISTED ) )
    assert refusals( LISTED )[ "LIST_ITEM" ] == 2


@pytest.mark.parametrize( "marker", [ "-", "*", "+", "•", "1.", "2)" ] )
def test_r8_every_list_marker_the_word_count_knows_starts_a_list_item( marker ):
    old = "Return the session.\n\n" + marker + " drops the handle when the app is paused"
    assert rules.markup_rejection( old, span_of( old, "drops the handle" ) ) == "LIST_ITEM"
    assert rules.markup_rejection( old.replace( marker + " ", "" ), span_of( old.replace( marker + " ", "" ), "drops the handle" ) ) is None


def modal_spans( old ):
    return sorted( c[ "span_text" ] for c in s.weaken_candidates( old, SL ) if c[ "class" ] == "modal" )


@pytest.mark.parametrize( "o, c, code", [ ( "`", "`", "CODE" ), ( "[", "]", "LINK" ) ] )
def test_r8_a_weaken_whose_changed_word_is_inside_backticks_or_a_link_is_refused_and_the_same_words_in_prose_are_candidates( o, c, code ):
    text   = SUMMARY + "The reader sends {o}handle must stay open{c} to the store when the lock is busy."
    marked = text.format( o=o, c=c )
    assert modal_spans( text.format( o="", c="" ) )                                           # the control: in plain prose the modal is a candidate
    assert modal_spans( marked ) == []
    token = span_of( marked, "must" )
    assert rules.markup_rejection( marked, span_of( marked, o + "handle must stay open" + c ), token=token ) == code


def test_r8_a_weaken_span_that_cuts_into_backticks_is_refused_and_one_that_stays_outside_is_kept():
    old = SUMMARY + "The reader must `wait here` for the lock before it reads the handle."
    assert rules.markup_rejection( old, span_of( old, "must `wait" ), token=span_of( old, "must" ) ) == "CODE"
    assert rules.markup_rejection( old, span_of( old, "reader must" ), token=span_of( old, "must" ) ) is None
    assert "reader must" in modal_spans( old ) and "must `wait" not in modal_spans( old )


def test_r8_a_weaken_in_a_list_item_is_not_refused_for_the_list():
    old = "Return the session.\n\n- must keep the handle open for the reader"
    assert rules.markup_rejection( old, span_of( old, "must keep the handle" ) ) == "LIST_ITEM"
    assert rules.markup_rejection( old, span_of( old, "must keep the handle" ), token=span_of( old, "must" ) ) is None


def test_r8_the_first_reason_to_fire_is_code_then_link_then_list_item():
    old = "Return the session.\n\n- `open now` and [close later] run in turn"
    assert rules.markup_rejection( old, span_of( old, "`open" ) ) == "CODE"
    assert rules.markup_rejection( old, span_of( old, "now` and [close" ) ) == "CODE"
    assert rules.markup_rejection( old, span_of( old, "and [close" ) ) == "LINK"
    assert rules.markup_rejection( old, span_of( old, "`open now` and [close later] run" ) ) == "LIST_ITEM"
    assert rules.markup_rejection( old, span_of( old, "run in turn" ) ) is None


def test_r8_text_with_no_markup_has_no_regions_and_refuses_nothing():
    old = SUMMARY + "The reader waits for the lock before it reads the handle."
    assert rules.code_regions( old ) == [] and rules.link_regions( old ) == [] and rules.list_item_starts( old ) == []
    assert rules.markup_rejection( old, span_of( old, "before it reads the handle" ) ) is None
    assert rules.cuts_into( [ ( 5, 9 ) ], 0, 5 ) is False and rules.cuts_into( [ ( 5, 9 ) ], 9, 12 ) is False     # touching an edge is not cutting in


# ---- rule 9: a delete never leaves a clause's lead-in hanging (row 4cc9cd81) ---------------------------------------
# Made-up docstrings only. Each shape slipped past bad_cut, delete_rejection and markup_rejection: the cut sentence has a verb, does
# not start or end on a dangler, has four words or more, and the span is not inside markup.

SHAPE_1 = "Return the cached value for a key. If the cache is empty, the default is used. Throws on failure."
SHAPE_2 = "Count the items of a list. It returns zero when the list is empty: nothing can be counted, and a negative size would break the sort."
SHAPE_3 = "Complete the dialog. It completes with the saved value when the form closed itself, and with zero when the user cancelled."


def span_in( old, text ):
    assert old.count( text ) == 1
    a = old.index( text )
    return ( a, a + len( text ) )


def lead_in( old, text ):
    return rules.lead_in_rejection( old, span_in( old, text ) )


@pytest.mark.parametrize( "old, text, code", [
    ( SHAPE_1, "the default is used", "HANGING_CONDITION" ),
    ( SHAPE_2, "when the list is empty: nothing can be counted", "DROPPED_CONDITION" ),
    ( SHAPE_3, "and with zero", "JOINED_CONDITIONS" ) ] )
def test_r9_each_of_the_three_shapes_slips_past_every_older_check_and_is_refused_by_its_own_code( old, text, code ):
    span = span_in( old, text )
    cut  = s.cut_text( old, span )
    assert span in s.phrase_units( old ) and s.span_ok( old, span, SL )
    assert s.bad_cut( old, cut ) is None and rules.delete_rejection( old, span, cut ) is None and rules.markup_rejection( old, span ) is None
    assert rules.lead_in_rejection( old, span ) == code


def test_r9_a_condition_with_its_main_clause_still_standing_is_not_a_hanging_lead_in():
    assert lead_in( "Return the value. If the cache is empty, the default is used, and a warning is logged.", "and a warning is logged" ) is None
    assert lead_in( "Return the value. If the cache is empty, the default is used. Throws on failure.", "Throws on failure" ) is None
    assert lead_in( "Return the value. The default is used, and a warning is logged.", "and a warning is logged" ) is None
    assert lead_in( "Return the value. If the cache is empty, the default is used by callers.", "the default" ) is None       # text still follows the span


def test_r9_a_bullet_in_front_of_the_condition_does_not_hide_it():
    old = "Return the value.\n\n- If the cache is empty, the default is used.\n- Throws on failure."
    assert lead_in( old, "the default is used" ) == "HANGING_CONDITION"


def test_r9_a_clause_deleted_before_a_conjunction_is_refused_only_when_it_opens_with_a_subordinator():
    assert lead_in( SHAPE_2, "when the list is empty: nothing can be counted" ) == "DROPPED_CONDITION"
    assert lead_in( "Count the items. It returns zero when the list is empty. A negative size would break the sort.", "when the list is empty" ) is None
    assert lead_in( "Count the items. It returns zero for an empty list, and a negative size would break the sort.", "for an empty list" ) is None     # a miss, stated in the docstring
    assert lead_in( "Count the items. It returns zero when the list is empty, which is a case callers meet.", "when the list is empty" ) is None


def test_r9_two_conditions_run_together_are_refused_only_when_the_text_before_the_cut_already_holds_one():
    assert lead_in( SHAPE_3, "and with zero" ) == "JOINED_CONDITIONS"
    assert lead_in( "Complete the dialog. It completes with the saved value, and with zero when the user cancelled.", "and with zero" ) is None
    assert lead_in( "Complete the dialog. It completes with the saved value when the form closed itself and with zero when the user cancelled.", "and with zero" ) is None


def test_r9_a_span_in_a_sentence_of_its_own_is_judged_on_that_sentence_alone():
    old = "Return the value. It is cached. If the cache is empty, the default is used."
    assert lead_in( old, "the default is used" ) == "HANGING_CONDITION"
    assert lead_in( old, "It is cached" ) is None


def test_r9_delete_candidates_leave_out_each_shape_and_count_it_by_code():
    for old, text, code in ( ( SHAPE_1, "the default is used", "HANGING_CONDITION" ), ( SHAPE_2, "when the list is empty: nothing can be counted", "DROPPED_CONDITION" ),
                             ( SHAPE_3, "and with zero", "JOINED_CONDITIONS" ) ):
        cands, refused = s.delete_candidates( old, SL )
        assert text not in [ c[ "span_text" ] for c in cands ], code
        assert refused.get( code, 0 ) >= 1, code
        assert all( rules.lead_in_rejection( old, c[ "span" ] ) is None for c in cands ), code


# ---- rule 10: a delete never leaves stray punctuation, and rule 9 reads a condition left in front of a conjunction (row 6737b017) ----
# Made-up docstrings only. Each case below passes bad_cut, delete_rejection, markup_rejection and lead_in_rejection today.

SEMI_OLD  = "Show the card list. It shows the latest card and a count chip; tapping expands the burst in place. Throws on failure."
COLON_OLD = "Count the items. It has two modes: strict mode rejects an empty list. Throws on failure."
BLANK_OLD = "Return the card. It never throws, for any input\n\nCallers hold the lock while they read it."
SO_OLD    = "Look up the key. When no key is enrolled, it returns unavailable, so callers can fall back to the default."


@pytest.mark.parametrize( "old, text, artifact", [
    ( SEMI_OLD, "tapping expands the burst in place", ";." ),
    ( COLON_OLD, "strict mode rejects an empty list", ":." ),
    ( BLANK_OLD, "for any input", ",\n\n" ) ] )
def test_r10_a_cut_that_leaves_stray_punctuation_is_refused_and_counted_by_its_code( old, text, artifact ):
    span = span_in( old, text )
    cut  = s.cut_text( old, span )
    assert artifact in cut and artifact not in old
    assert span in s.phrase_units( old ) and s.span_ok( old, span, SL )
    assert s.bad_cut( old, cut ) is None and rules.delete_rejection( old, span, cut ) is None
    assert rules.markup_rejection( old, span ) is None and rules.lead_in_rejection( old, span ) is None
    assert rules.stray_punctuation_rejection( old, cut ) == "STRAY_PUNCTUATION"
    cands, refused = s.delete_candidates( old, SL )
    assert text not in [ c[ "span_text" ] for c in cands ] and refused.get( "STRAY_PUNCTUATION", 0 ) >= 1


@pytest.mark.parametrize( "cut", [ "Show the list;. Done.", "It has two modes:. Done.", "Shows the card.. Done.", "Callers wait,\n\nDone.", "- never throws,", "Hold the lock!;?" ] )
def test_r10_each_artifact_is_seen_wherever_it_stands_in_the_text( cut ):
    assert rules.stray_punctuation_rejection( "Show the list. Done.", cut ) == "STRAY_PUNCTUATION"


def test_r10_an_artifact_the_original_already_had_is_not_the_cuts_fault():
    old = "Show the list;. It also holds, as a note,\n\nthe lock.. Done."
    assert rules.stray_punctuation_rejection( old, old.replace( "Done.", "Finished." ) ) is None


def test_r10_an_ellipsis_a_clean_cut_and_a_comma_kept_inside_a_line_are_not_stray():
    old = "Show the list. Wait... then read it, and move on. Done."
    assert rules.stray_punctuation_rejection( old, old ) is None
    assert rules.stray_punctuation_rejection( old, "Show the list. Wait... then read it. Done." ) is None
    assert rules.stray_punctuation_rejection( old, "Show the list. Wait, then read it, and move on.\nDone." ) is None


def test_r9_a_condition_left_in_front_of_a_conjunction_is_refused_when_its_main_clause_was_cut():
    span = span_in( SO_OLD, "it returns unavailable" )
    assert span in s.phrase_units( SO_OLD ) and s.span_ok( SO_OLD, span, SL )
    cut = s.cut_text( SO_OLD, span )
    assert s.bad_cut( SO_OLD, cut ) is None and rules.delete_rejection( SO_OLD, span, cut ) is None and rules.markup_rejection( SO_OLD, span ) is None
    assert rules.lead_in_rejection( SO_OLD, span ) == "UNANSWERED_CONDITION"
    assert rules.lead_in_codes( SO_OLD, span ) == [ "UNANSWERED_CONDITION" ]
    cands, refused = s.delete_candidates( SO_OLD, SL )
    assert "it returns unavailable" not in [ c[ "span_text" ] for c in cands ] and refused.get( "UNANSWERED_CONDITION", 0 ) >= 1


@pytest.mark.parametrize( "conjunction", [ "and", "or", "but", "nor", "yet", "so" ] )
def test_r9_every_coordinator_after_the_cut_clause_leaves_the_condition_unanswered( conjunction ):
    old = f"Look up the key. When no key is enrolled, it returns unavailable, {conjunction} callers can fall back to the default."
    assert lead_in( old, "it returns unavailable" ) == "UNANSWERED_CONDITION"


def test_r9_an_unanswered_condition_needs_the_condition_to_open_the_sentence_and_nothing_else_to_answer_it():
    assert lead_in( "Look up the key. It returns unavailable, so callers can fall back to the default.", "It returns unavailable" ) is None
    assert lead_in( "Look up the key. When no key is enrolled, it returns unavailable, so callers can fall back.", "so callers can fall back" ) is None
    assert lead_in( "Look up the key. When no key is enrolled, or the pool is closed, it returns unavailable, so callers can fall back.", "it returns unavailable" ) is None    # a miss, stated in the docstring
    assert lead_in( "Look up the key. When no key is enrolled, if it is closed, it returns unavailable, so callers can fall back.", "if it is closed, it returns unavailable" ) == "DROPPED_CONDITION"


# ---- review of e2d510af1 (Rio): two redraw --failed cases the first tests did not pin ------------------------------

def test_redraw_failed_replaces_all_three_pairs_named_on_a_set_rule_1_passes( written, capsys ):
    tmp_path, pool = written
    gate   = tmp_path / "gate-store"
    before = load( gate, "gate" )
    assert s.check_set( str( gate ), "gate" )[ 0 ] == {}
    ids    = sorted( next( p[ "id" ] for p in before[ "pairs" ] if p[ "kind" ] == kind ) for kind in ( "delete", "weaken", "paraphrase" ) )
    assert len( ids ) == 3
    assert s.main( redraw_args( tmp_path, pool, failed=write_accept( tmp_path, ids ) ) ) == 0
    assert f"3 failed pair(s) {' '.join( ids )} are replaced; 3 new writer call(s) needed" in capsys.readouterr().out
    after = load( tmp_path / "redrawn", "gate" )
    assert after[ "redrawn" ][ "pairs" ] == ids
    assert sorted( p[ "id" ] for p, q in zip( before[ "pairs" ], after[ "pairs" ] ) if p != q ) == ids
    assert floors_of( after ) == floors_of( before )


def test_redraw_failed_wins_over_accept_for_a_pair_named_in_both( written, capsys ):
    tmp_path, pool = written
    gate = tmp_path / "gate-store"
    pid  = synonym_pair( gate, "gate" )
    accept = write_accept( tmp_path, [ pid ], "accept.json" )
    failures, accepted, _ = s.rule1_status( str( gate ), "gate", accept )
    assert failures == {} and list( accepted ) == [ pid ]                                  # --accept alone leaves nothing to redraw
    assert s.main( redraw_args( tmp_path, pool, accept=accept ) ) == 0
    assert "nothing to redraw" in capsys.readouterr().out and not ( tmp_path / "redrawn" ).exists()
    assert s.main( redraw_args( tmp_path, pool, accept=accept, failed=write_accept( tmp_path, [ pid ], "failed.json" ) ) ) == 0
    assert f"1 failed pair(s) {pid} are replaced" in capsys.readouterr().out
    assert load( tmp_path / "redrawn", "gate" )[ "redrawn" ][ "pairs" ] == [ pid ]


# ---- review of fd85e299d (Rio): every subordinator and every coordinator is read by a test --------------------------
# The word lists below are literals on purpose: a test that read rules.SUBORDINATORS would pass whatever the set held.

SUBORDINATOR_WORDS = "if when unless while although though because once until whenever whereas since after before where wherever whether provided".split()
COORDINATOR_WORDS  = "and or but nor yet so".split()


def test_r9_the_word_lists_are_exactly_these_and_leave_out_as_and_even():
    assert set( rules.SUBORDINATORS ) == set( SUBORDINATOR_WORDS ) and "as" not in rules.SUBORDINATORS and "even" not in rules.SUBORDINATORS
    assert rules.CONJUNCTION_RE.pattern.count( "|" ) == len( COORDINATOR_WORDS ) - 1
    assert all( rules.CONJUNCTION_RE.match( f", {w} x" ) for w in COORDINATOR_WORDS )


@pytest.mark.parametrize( "word", SUBORDINATOR_WORDS )
def test_r9_every_subordinator_opens_a_hanging_condition( word ):
    assert lead_in( f"Return the value. {word.capitalize()} the cache is empty, the default is used.", "the default is used" ) == "HANGING_CONDITION"


@pytest.mark.parametrize( "word", SUBORDINATOR_WORDS )
def test_r9_every_subordinator_opens_a_dropped_condition_before_a_conjunction( word ):
    old = f"Count the items. It returns zero {word} the list is empty, and a negative size would break the sort."
    assert lead_in( old, f"{word} the list is empty" ) == "DROPPED_CONDITION"


@pytest.mark.parametrize( "word", SUBORDINATOR_WORDS )
def test_r9_every_subordinator_counts_as_the_earlier_and_as_the_following_condition_of_two_run_together( word ):
    earlier   = f"Complete the dialog. It completes {word} the form closed itself, and with zero when the user cancelled."
    following = f"Complete the dialog. It completes when the form closed itself, and with zero {word} the user cancelled."
    assert lead_in( earlier, "and with zero" ) == "JOINED_CONDITIONS" and lead_in( following, "and with zero" ) == "JOINED_CONDITIONS"


@pytest.mark.parametrize( "word", COORDINATOR_WORDS )
def test_r9_every_coordinator_after_the_comma_makes_the_dropped_condition( word ):
    assert lead_in( f"Count the items. It returns zero when the list is empty, {word} a negative size would break the sort.", "when the list is empty" ) == "DROPPED_CONDITION"


def test_r9_a_word_that_only_starts_like_a_coordinator_is_not_one():
    for word in ( "order", "android", "sooner", "yetis", "nori", "button" ):
        assert lead_in( f"Count the items. It returns zero when the list is empty, {word} a negative size would break the sort.", "when the list is empty" ) is None, word


def test_r9_a_lead_in_opened_by_as_or_even_is_a_documented_miss_and_is_not_refused():
    assert lead_in( "Return the value. As the cache is empty, the default is used.", "the default is used" ) is None
    assert lead_in( "Return the value. Even if the cache is empty, the default is used.", "the default is used" ) is None


# ---- review of fd85e299d (Rio), findings 4 to 6: the comma miss, the order of the checks, the weaken scope ----------

def test_r9_a_lead_in_with_a_comma_of_its_own_is_a_documented_miss_and_is_not_refused():
    assert lead_in( "Return the value. If a, b or c is missing, the call fails.", "the call fails" ) is None
    assert lead_in( "Return the value. If the cache is empty, and the pool is closed, the call fails.", "the call fails" ) is None
    assert lead_in( "Return the value. If the cache is empty, the call fails.", "the call fails" ) == "HANGING_CONDITION"      # the same lead-in without the comma is seen


def test_r9_no_two_checks_fire_on_one_span_so_the_order_of_the_checks_changes_nothing():
    openers = ( "If the cache is empty", "It returns zero", "It completes when the form closed itself", "Where the pool is open" )
    joiners = ( ", ", " ", ", and ", ", when ", ", but if " )
    tails   = ( "the default is used", "when the list is empty", "and with zero when the user cancelled", "a negative size would break the sort", "and a warning is logged" )
    seen, spans = set(), 0
    for o in openers:
        for j in joiners:
            for t in tails:
                for j2, t2 in ( ( "", "" ), ( ", ", "when it is done" ), ( ", and ", "it logs" ), ( " ", "after that" ) ):
                    old    = f"Return the value. {o}{j}{t}{j2}{t2}."
                    tokens = list( __import__( "re" ).finditer( r"\S+", old ) )[ 3: ]                    # the words of the second sentence
                    for i in range( len( tokens ) ):
                        for k in range( i, len( tokens ) ):
                            word = tokens[ k ].group( 0 )
                            for end in { tokens[ k ].end(), tokens[ k ].end() - ( len( word ) - len( word.rstrip( ",.;:" ) ) ) }:       # with and without the comma or full stop
                                if end <= tokens[ i ].start(): continue
                                codes = rules.lead_in_codes( old, ( tokens[ i ].start(), end ) )
                                assert len( codes ) <= 1, ( old, old[ tokens[ i ].start():end ], codes )
                                seen.update( codes )
                                spans += 1
    assert seen == { "HANGING_CONDITION", "DROPPED_CONDITION", "JOINED_CONDITIONS" } and spans > 20000        # the grid finds every code, so a clean result means something


def test_r9_a_span_both_rule_8_and_rule_9_refuse_is_counted_under_rule_8s_code_only():
    old  = "Return the value. When the cache is empty it is reset to `alpha, beta gamma`."
    span = ( old.index( "beta gamma`" ), len( old ) - 1 )
    assert rules.markup_rejection( old, span ) == "CODE" and rules.lead_in_rejection( old, span ) == "HANGING_CONDITION"
    cands, refused = s.delete_candidates( old, SL )
    assert span not in [ c[ "span" ] for c in cands ]
    assert refused.get( "CODE" ) == 1 and "HANGING_CONDITION" not in refused


def test_r9_a_weaken_whose_span_would_trip_rule_9_as_a_delete_is_still_offered():
    old   = "Return the value. If the cache is empty, the default must be used."
    span  = ( old.index( "the default must be used" ), len( old ) - 1 )
    found = [ c for c in s.weaken_candidates( old, SL ) if c[ "span" ] == span ]
    assert rules.lead_in_rejection( old, span ) == "HANGING_CONDITION"                        # as a delete this span is refused
    assert len( found ) == 1 and found[ 0 ][ "class" ] == "modal"                            # as a weaken it is offered
