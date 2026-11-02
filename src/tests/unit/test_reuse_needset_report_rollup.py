"""Unit tests for the overnight roll-up report, on hand-built or copied plan-only inputs."""

import json

import pytest

from lupin_mcp import reuse_e2e
from lupin_mcp.reuse_needset import report_rollup as rr

FORCED_PLAN    = { "live": False, "plan": { "by_label": { "not_same": 4, "same_job": 8 }, "pairs": 12, "requests_needed": 48, "stage_budget": 100, "undrafted": [] } }
EXPANSION_PLAN = { "live": False, "plan": { "by_group": { "attribution": 37, "control": 17, "yield": 70 }, "calls_needed": 124, "embeddings_needed": 620, "rows": 124,
                                            "saved_replies": 0, "stage_budget": 140, "undrafted": [ "d-1", "d-2", "d-3" ], "unsaved": [] } }
NO_NEED        = { "disputed": 0, "disputed_ids": [], "draft_failed": 29, "no_partner": 0, "not_pooled": 1, "skipped": [], "unreadable_reply": 0, "unstrippable_seed": 0 }
YIELD_PLAN     = { "live": False, "plan": { "seeds": 100, "needs": 70, "unsaved": [], "no_final_need": NO_NEED, "by_lang": { "py": 36, "ts": 34 }, "lists_sha": "abc" } }
YIELD_RUN      = { "live": True, "plan": YIELD_PLAN[ "plan" ], "closed_run": None, "close_error": None,
                   "report": { "used": 200, "limit": 669, "by_stage": {}, "status": "done",
                               "report": { "traced": True, "members": 10, "found": 6, "by_lost_at": { "found": 6, "retrieval": 4 },
                                           "found_by_lang": { "ts": { "found": 2, "members": 4, "interval": [ 0.1, 0.9 ] }, "py": { "found": 4, "members": 6, "interval": [ 0.3, 0.9 ] } } } } }


def forced_result( rid, label, lang, was_in=False, answered=True, accepted=False ):
    """Ensures: returns one forced_judge result row."""
    return { "id": rid, "label": label, "lang": lang, "was_in_shortlist": was_in, "answered": None if was_in else answered, "accepted": None if was_in else accepted }


FORCED_RUN = { "used": 8, "limit": 100, "by_stage": {}, "status": "done", "detail": None, "summary": {},
               "results": [ forced_result( "r1", "same_job", "python", accepted=True ), forced_result( "r2", "same_job", "python" ),
                            forced_result( "r3", "same_job", "typescript", was_in=True ), forced_result( "r4", "not_same", "python", answered=False ) ] }


def expansion_run( summary ):
    """Ensures: returns a finished expansion report holding summary."""
    return { "used": 124, "limit": 669, "by_stage": {}, "status": "done", "detail": None, "summary": summary, "results": [] }


def test_share_formats_count_percent_and_interval():
    assert rr.wilson is reuse_e2e.wilson
    assert rr.share( 8, 10 ) == "8/10 (80.0%, 49.0-94.3%)"
    assert rr.share( 0, 0 ) == "0/0 (n/a)"
    assert rr.share( 0, 5 ).startswith( "0/5 (0.0%, 0.0-" ) and rr.share( 5, 5 ).endswith( "-100.0%)" )


def test_table_has_header_rule_and_rows():
    assert rr.table( [ "a", "b" ], [ [ 1, "x" ] ] ).split( "\n" ) == [ "| a | b |", "| --- | --- |", "| 1 | x |" ]


def test_split_distinguishes_result_from_report_file():
    assert rr.split( FORCED_PLAN ) == ( FORCED_PLAN[ "plan" ], None )
    assert rr.split( FORCED_RUN ) == ( None, FORCED_RUN )
    assert rr.split( YIELD_RUN )[ 1 ] is YIELD_RUN[ "report" ]


def test_load_reads_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text( json.dumps( FORCED_PLAN ), encoding="utf-8" )
    assert rr.load( str( p ) ) == FORCED_PLAN


def test_yield_plan_only_marks_figures_not_run():
    text = rr.yield_section( YIELD_PLAN )
    assert "Plan only" in text and "| py | 36 |" in text and "Found share: not run" in text
    assert "| draft_failed | 29 |" in text and "disputed_ids" not in text and "Seeds 100, needs 70" in text


def test_yield_plan_names_each_skipped_seed_with_code_and_cut_detail():
    skipped = [ { "seed": "s-1", "code": "STRIP_FAILED", "detail": "line one\nhas | a bar " + "x" * 200 }, { "seed": "s-2", "code": "BAD_REPLY", "detail": "short" } ]
    plan    = { "live": False, "plan": { **YIELD_PLAN[ "plan" ], "no_final_need": { **NO_NEED, "skipped": skipped } } }
    text    = rr.yield_section( plan )
    assert "| skipped seed | code | detail |" in text and "| s-2 | BAD_REPLY | short |" in text
    row = next( l for l in text.split( "\n" ) if l.startswith( "| s-1 " ) )
    assert "line one has a bar xxx" in row and "\n" not in row and row.count( "|" ) == 4 and len( row.split( "| " )[ 3 ] ) <= 103


def test_yield_plan_without_skipped_seeds_says_none():
    assert "Skipped seeds: none." in rr.yield_section( YIELD_PLAN )


def test_yield_run_gives_wilson_overall_and_per_language():
    text = rr.yield_section( YIELD_RUN )
    assert "| all | 6/10 (60.0%, 31.3-83.2%) |" in text
    assert text.index( "| py |" ) < text.index( "| ts |" ) and "| py | 4/6 (66.7%," in text
    assert "| retrieval | 4 |" in text and "Run status done, 200 of 669" in text


@pytest.mark.parametrize( "key,reason", [ ( "reason", "why" ), ( "budget_detail", "why" ), ( "detail", "why" ), ( None, "no reason given" ) ] )
def test_yield_unfinished_run_gives_no_figures( key, reason ):
    inner = { "traced": False, **( { key: "why" } if key else { } ) }
    text  = rr.yield_section( { "live": True, "plan": YIELD_PLAN[ "plan" ], "report": { "used": 1, "limit": 2, "status": "stopped", "report": inner } } )
    assert f"({reason})" in text and "Wilson" not in text


def test_forced_plan_only_copies_real_output():
    text = rr.forced_section( FORCED_PLAN )
    assert "Missed pairs 12, requests needed 48 of a stage budget of 100, undrafted 0" in text
    assert "| same_job | 8 |" in text and "Judge recall: not run" in text


def test_judge_rows_count_by_label_with_already_in_excluded_from_answered():
    rows = rr.judge_rows( FORCED_RUN[ "results" ], "label" )
    assert rows == [ [ "not_same", 1, 0, 0, "0/0 (n/a)" ], [ "same_job", 3, 1, 2, "1/2 (50.0%, 9.5-90.5%)" ] ]


def test_forced_run_has_label_and_language_tables():
    text = rr.forced_section( FORCED_RUN )
    assert "| resolved label |" in text and "| language |" in text
    assert "| typescript | 1 | 1 | 0 | 0/0 (n/a) |" in text and "false accept" in text


def test_expansion_plan_only_copies_real_output():
    text = rr.expansion_section( EXPANSION_PLAN )
    assert "Rows 124, calls needed 124 of a stage budget of 140, replies already saved 0, undrafted 3" in text
    assert "| yield | 70 |" in text and "Entry into the 128: not run" in text


def test_expansion_run_reads_shares_over_readable_needs():
    g    = { "needs": 10, "unreadable": 2, "enter_before": 2, "enter_after": 6, "lifted": 5, "lowered": 1 }
    text = rr.expansion_section( expansion_run( { "yield": g } ) )
    assert "| yield | 10 | 2 | 2/8 (25.0%," in text and "| 6/8 (75.0%," in text and "| 5 | 1 |" in text
    assert "optimistic" in text and "no language" in text


def pair( oi, pi, rid="p" ):
    """Ensures: returns a control pair row."""
    return { "id": rid, "original_in": oi, "plant_in": pi }


def test_discordant_counts_the_pre_registered_example():
    pairs = [ pair( 1, 0 ) ] * 6 + [ pair( 0, 1 ) ] * 2 + [ pair( 1, 1 ) ] * 3 + [ pair( 0, 0 ) ] * 2
    assert rr.discordant( pairs ) == { "a": 6, "b": 2, "both": 3, "neither": 2, "passes": False }


@pytest.mark.parametrize( "a,b,passes", [ ( 2, 0, True ), ( 3, 0, False ), ( 3, 1, True ), ( 0, 5, True ) ] )
def test_the_mark_is_a_minus_b_at_most_two( a, b, passes ):
    pairs = [ pair( 1, 0 ) ] * a + [ pair( 0, 1 ) ] * b
    assert rr.discordant( pairs )[ "passes" ] is passes


def test_control_section_states_verdict_wording_and_one_sample_note():
    text = rr.control_section( [ pair( 1, 0 ) ] * 3 + [ pair( 1, 1 ) ] )
    assert "| a - b | 3 |" in text and "not met" in text and "not worse than the originals by more than two pairs" in text
    assert "one sample" in text and "equivalent" not in text
    assert "met." in rr.control_section( [ pair( 1, 1 ) ] )


def test_control_section_without_pairs_is_a_placeholder():
    assert "Not read yet" in rr.control_section() and "not run" in rr.control_section()


def test_control_report_reader_is_a_stub_until_johns_merge():
    with pytest.raises( NotImplementedError, match="not merged yet" ): rr.control_pairs_from_report( { } )


def test_render_orders_sections_and_flags_missing_inputs():
    text = rr.render( YIELD_PLAN, FORCED_PLAN, None )
    assert text.index( "Positive control" ) < text.index( "C1 forced" ) < text.index( "C2 yield" ) < text.index( "C5 need expansion" )
    assert "## C5 need expansion\n\nNo input given." in text and text.endswith( "\n" )


def test_render_with_every_input_and_control_rows():
    text = rr.render( YIELD_RUN, FORCED_RUN, EXPANSION_PLAN, [ pair( 1, 1 ) ] )
    assert "No input given" not in text and "| a - b | 0 |" in text


def test_main_prints_or_writes_and_reads_only_named_files(tmp_path):
    f, y, e, o = tmp_path / "f.json", tmp_path / "y.json", tmp_path / "e.json", tmp_path / "out.md"
    f.write_text( json.dumps( FORCED_PLAN ), encoding="utf-8" )
    y.write_text( json.dumps( YIELD_PLAN ), encoding="utf-8" )
    e.write_text( json.dumps( EXPANSION_PLAN ), encoding="utf-8" )
    got = [ ]
    assert rr.main( [ "--forced-judge", str( f ), "--yield-trace", str( y ), "--expansion", str( e ) ], out=got.append ) == 0
    assert len( got ) == 1 and "Plan only" in got[ 0 ] and "No input given" not in got[ 0 ]
    assert rr.main( [ "--forced-judge", str( f ), "--out", str( o ) ], out=got.append ) == 0
    assert len( got ) == 1 and "C1 forced" in o.read_text( encoding="utf-8" )
