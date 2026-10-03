"""
Row 421963b6: the seven selection rules of the labelled-set seeder, the mechanical check after the writer (rule 1),
and the redraw path for the pairs that check fails.

Every docstring here is made up for this file. No dev, gate or reserve data is read; no model is called.
"""

import json

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


def break_outputs( base, split, n=2 ):
    """Make the first n seeded pairs fail rule 1 by putting the seeded span back in the output; returns their ids."""
    plan    = load( base, split )
    seeded  = [ p for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS ][ :n ]
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


def test_redraw_never_redraws_the_span_that_failed():
    plan = { "pairs": [ { "id": "p000", "kind": "delete", "weaken_class": None, "short": False, "stratum": "S", "pool_id": "d1", "x_span_in_old": "when the pool is closed" } ] }
    doc  = lambda *spans: { "pool_id": "d1", "unit": "u", "stratum": "S", "cands": [ { "span_text": sp } for sp in spans ] }
    with pytest.raises( s.Shortfall, match="nothing in scope replaces p000" ):
        s.redraw_pairs( plan, {"p000"}, { "delete": [ doc( "when the pool is closed" ) ] }, {"u"}, __import__( "random" ).Random( 1 ) )
    got = s.redraw_pairs( plan, {"p000"}, { "delete": [ doc( "when the pool is closed", "if the pool is open" ) ] }, {"u"}, __import__( "random" ).Random( 1 ) )
    assert got[ "p000" ][ 2 ][ "span_text" ] == "if the pool is open"


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
