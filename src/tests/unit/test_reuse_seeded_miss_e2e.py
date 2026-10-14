"""
Unit tests for the seeded-miss end-to-end run, over its stand-in Jev and saved answers.

Venue: :7999-eligible. No HTTP and no key.
A live run is exercised through a stand-in transport and a scratch ledger.
The task store is an in-memory stand-in, and everything is written under tmp_path.
"""
import json
import pathlib

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from cosa.repo.symindex import repair_check
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_seeded_miss_e2e as sm
from lupin_mcp import reuse_tools as rt


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    """No test here may find a real key: a live call would be spend and a leak."""
    monkeypatch.delenv( jt.KEY_VARIABLE, raising=False )


def test_words_drop_short_and_stop_words_and_split_on_punctuation():
    assert sm.words( "Read the articles of an RSS feed_x" ) == { "read", "articles", "rss", "feed" }


def test_candidate_of_reads_the_quoted_text_whatever_follows_and_none_when_absent():
    text = "cosa.feeds.parse_feed(url) — Parse an RSS feed."
    assert sm.candidate_of( f"Judge only from the candidate {text!r}'s signature and docstring" ) == text
    assert sm.candidate_of( f"Judge only from the candidate {text!r}, the one-line description" ) == text
    quoted = "it's a \"quoted\" doc \\ with a slash"
    assert sm.candidate_of( f"from the candidate {quoted!r}, then more" ) == quoted
    assert sm.candidate_of( "no such phrase here" ) is None


def test_answer_for_is_relevant_at_half_the_need_and_unrelated_below():
    assert sm.answer_for( sm.NEED_PAGE, "read articles, feed" ) == sm.RELEVANT
    assert sm.answer_for( sm.NEED_PAGE, "serve the tools" ) == sm.UNRELATED
    assert sm.answer_for( "the of an", "anything" ) == sm.UNRELATED


def test_the_stand_in_answers_each_question_from_its_own_candidate_and_counts_bodies():
    jev  = sm.StandInJev()
    body = { "model": "m", "state": { "need": sm.NEED_PAGE },
             "questions": { "a": { "instructions": "from the candidate 'read articles of an RSS feed', x" },
                            "b": { "instructions": "from the candidate 'serve tools', x" } } }
    response, meta = jev.post_with_meta( body )
    assert response[ "answers" ][ "a" ][ "probabilities" ] == sm.RELEVANT and response[ "answers" ][ "b" ][ "probabilities" ] == sm.UNRELATED
    assert meta[ "status" ] == 200 and jev.calls == 1
    with pytest.raises( AssertionError ): jev.post_with_meta( { "model": "m", "state": { "need": "x" }, "questions": { "c": { "instructions": "none" } } } )


def test_the_no_call_transport_refuses_and_remembers_the_need():
    transport = sm.NoCallTransport()
    with pytest.raises( sm.SavedAnswerMissing, match = "read the articles" ): transport.post_with_meta( { "state": { "need": sm.NEED_PAGE } } )
    assert transport.refused == [ sm.NEED_PAGE ] and transport.calls == 0


def test_the_fake_store_creates_amends_and_moves_the_clock_on():
    store = sm.FakeStore()
    ok, status, row = store.create( { "title": "t", "body": "b" } )
    assert ( ok, status, row[ "id" ] ) == ( True, 201, "fake-1" )
    first = store.rows[ 0 ][ "updated_ts" ]
    assert store.amend( "fake-1", "note" ) == ( True, 200, {} )
    assert store.rows[ 0 ][ "body" ].endswith( "[amendment]\nnote" ) and store.rows[ 0 ][ "updated_ts" ] > first
    assert store.query( "k" )[ 2 ][ "tasks" ] == store.query_all( "k" )[ 2 ][ "tasks" ] and len( store.rows ) == 1


def test_the_sandbox_has_the_wrong_page_matching_and_the_right_page_terse( tmp_path ):
    root  = sm.build_sandbox( tmp_path )
    index = ( root / "src" / "docs" / "wiki" / "INDEX.md" ).read_text()
    assert sm.TERSE_LINE in index and sm.WRONG_LINE in index and ( root / "src" / "lupin_mcp" ).is_dir()
    assert len( sm.words( sm.NEED_PAGE ) & sm.words( f"{sm.RIGHT_PAGE} {sm.TERSE_LINE}" ) ) == 0
    sm.write_index( root, sm.REPAIRED_LINE )
    assert sm.REPAIRED_LINE in ( root / "src" / "docs" / "wiki" / "INDEX.md" ).read_text()


def test_a_dry_run_on_the_stand_in_repairs_the_page_miss_and_the_full_sweep_miss( tmp_path ):
    code, report = sm.run( tmp_path / "w", "dry", log=lambda line: None )
    assert code == 0 and report[ "ok"] and report[ "mode" ] == "dry-stand-in" and report[ "calls" ] > 0
    page, full = report[ "page" ], report[ "full" ]
    assert page[ "route" ] == "pages" and page[ "shortlist_before" ] == [ "cosa.newsx.read_articles" ]
    assert page[ "repair" ] == { "verdict": "REPAIRED", "before": 0, "after": 5, "runs": 5, "replay_routes": [ "pages" ] }
    assert full[ "route" ] == "full" and full[ "shortlist_before" ] == []
    assert full[ "repair" ][ "no_change" ][ "verdict" ] == "NO_INPUT_CHANGE" and full[ "repair" ][ "docstring" ] == { "verdict": "REPAIRED", "before": 0, "after": 5, "runs": 5 }
    assert report[ "exported" ] == { sm.SYMBOL_PAGE: True, sm.SYMBOL_FULL: True }
    assert sm.NEW_DOC in ( tmp_path / "w" / "sandbox" / "src" / "cosa" / "feeds.py" ).read_text()
    lines = ( tmp_path / "w" / "misses.jsonl" ).read_text().splitlines()
    assert len( lines ) == 2 and json.loads( ( tmp_path / "w" / "report.json" ).read_text() )[ "ok" ] is True
    assert sm.REPAIRED_LINE in ( tmp_path / "w" / "sandbox" / "src" / "docs" / "wiki" / "INDEX.md" ).read_text()


def test_a_dry_run_on_saved_answers_makes_no_call_and_a_run_missing_answers_stops_loudly( tmp_path ):
    sm.run( tmp_path / "first", "dry", log=lambda line: None )
    code, report = sm.run( tmp_path / "second", "dry", answers=tmp_path / "first" / "data" / "jev-cache", log=lambda line: None )
    assert code == 0 and report[ "mode" ] == "dry-saved" and report[ "calls" ] == 0
    ( tmp_path / "empty" ).mkdir()
    with pytest.raises( sm.SavedAnswerMissing, match = "not in the saved answers" ): sm.run( tmp_path / "third", "dry", answers=tmp_path / "empty", log=lambda line: None )
    with pytest.raises( sm.RunRefused, match = "not a folder" ): sm.run( tmp_path / "fourth", "dry", answers=tmp_path / "nowhere" )


def test_an_answers_folder_over_the_size_limit_is_refused_before_it_is_copied( tmp_path, monkeypatch ):
    big = tmp_path / "big" / "ab"
    big.mkdir( parents=True )
    ( big / "x.json" ).write_bytes( b"x" * 2048 )
    monkeypatch.setattr( sm, "MAX_ANSWERS_BYTES", 1024 )
    with pytest.raises( sm.RunRefused, match = "holds more than 1024 bytes; copy only" ): sm.run( tmp_path / "w", "dry", answers=tmp_path / "big" )
    assert not ( tmp_path / "w" / "data" ).exists()


def test_refusals_come_before_anything_is_created( tmp_path, monkeypatch ):
    ( tmp_path / "busy" ).mkdir()
    ( tmp_path / "busy" / "x" ).write_text( "x" )
    with pytest.raises( sm.RunRefused, match = "not empty" ): sm.run( tmp_path / "busy", "dry" )
    with pytest.raises( sm.RunRefused, match = "is refused" ): sm.run( tmp_path / "a", "dry", store_kind="other" )
    with pytest.raises( sm.RunRefused, match = "--ceiling and --ledger" ): sm.run( tmp_path / "b", "live" )
    with pytest.raises( sm.RunRefused, match = "is not set" ): sm.run( tmp_path / "c", "live", ceiling=1000, ledger_path=tmp_path / "l" )
    monkeypatch.setattr( jt, "has_key", lambda: True )
    with pytest.raises( sm.RunRefused, match = "--answers is for a dry run" ): sm.run( tmp_path / "d", "live", answers=tmp_path, ceiling=1000, ledger_path=tmp_path / "l" )
    for mode in ( "dry", "live" ):
        with pytest.raises( sm.RunRefused, match = "synthetic rows" ): sm.run( tmp_path / f"e-{mode}", mode, store_kind="live", ceiling=1000, ledger_path=tmp_path / "l" )
    assert not ( tmp_path / "a" ).exists() and not ( tmp_path / "b" ).exists() and not ( tmp_path / "c" ).exists()


class EverythingRelevant( sm.StandInJev ):
    """Answers every candidate as relevant, so neither seed can produce a miss."""

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        for answer in response[ "answers" ].values(): answer[ "probabilities" ] = sm.RELEVANT
        return response, meta


class NewsOnly( sm.StandInJev ):
    """Answers only the news page and its entry as relevant, so a rewrite changes nothing."""

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        for key, question in body[ "questions" ].items():
            relevant = "news" in sm.candidate_of( question[ "instructions" ] )
            response[ "answers" ][ key ][ "probabilities" ] = sm.RELEVANT if relevant else sm.UNRELATED
        return response, meta


def scenario_parts( tmp_path, transport ):
    root, data, out = sm.build_sandbox( tmp_path ), tmp_path / "data", tmp_path / "out"
    ctx   = sm.make_context( root, data, out, transport=transport )
    store = sm.FakeStore()
    from cosa.repo.symindex.librarian_queue import Librarian
    return ctx, root, Librarian( store, str( tmp_path / "pending.jsonl" ), lambda line: None ), store


def test_a_seed_that_finds_the_symbol_is_reported_and_no_row_is_written( tmp_path ):
    ctx, root, lib, store = scenario_parts( tmp_path, EverythingRelevant() )
    page = sm.page_scenario( ctx, root, lib, store, 5 )
    assert page[ "ok" ] is False and "did not produce a page-route miss" in page[ "reason" ]
    full = sm.full_scenario( ctx, root, lib, store, 5 )
    assert full[ "ok" ] is False and "did not produce a full-sweep miss" in full[ "reason" ] and store.rows == []


def test_a_rewrite_that_does_not_help_is_not_repaired_and_no_repaired_note_is_written( tmp_path ):
    ctx, root, lib, store = scenario_parts( tmp_path, NewsOnly() )
    page = sm.page_scenario( ctx, root, lib, store, 5 )
    assert page[ "ok" ] is False and page[ "repair" ][ "verdict" ] == repair_check.NOT_REPAIRED and "repaired_noted" not in page[ "row" ]


def test_a_failed_seed_ask_is_reported_for_both_scenarios( tmp_path, monkeypatch ):
    ctx, root, lib, store = scenario_parts( tmp_path, sm.StandInJev() )
    monkeypatch.setattr( rt, "page_route_need_impl", lambda need, exclude, c: { "status": "error", "error": "NO" } )
    monkeypatch.setattr( rt, "sweep_need_impl", lambda need, exclude, c: { "status": "error", "error": "NO" } )
    assert sm.page_scenario( ctx, root, lib, store, 5 )[ "reason" ] == "seed ask failed: NO"
    assert sm.full_scenario( ctx, root, lib, store, 5 )[ "reason" ] == "seed ask failed: NO"


class NothingRelevant( sm.StandInJev ):
    """Answers every candidate as unrelated, so no docstring rewrite can repair a miss."""

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        for answer in response[ "answers" ].values(): answer[ "probabilities" ] = sm.UNRELATED
        return response, meta


def test_a_docstring_rewrite_that_the_model_does_not_accept_leaves_the_full_sweep_miss_open( tmp_path ):
    ctx, root, lib, store = scenario_parts( tmp_path, NothingRelevant() )
    full = sm.full_scenario( ctx, root, lib, store, 5 )
    assert full[ "ok" ] is False and "checks gave NO_INPUT_CHANGE and NOT_REPAIRED" in full[ "reason" ] and "repaired_noted" not in full[ "row" ]


def test_a_live_run_goes_through_the_ledger_and_closes_its_run( tmp_path, monkeypatch ):
    ledger = tmp_path / "ledger.jsonl"
    rl.AccountLedger.create( ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
    stand  = sm.StandInJev()

    class Wrapped:
        def __init__( self, budget=None, transient=False ): self.budget = budget
        def post_with_meta( self, body ): return stand.post_with_meta( body )

    monkeypatch.setattr( jt, "has_key", lambda: True )
    monkeypatch.setattr( rt, "LiveJevTransport", Wrapped )
    code, report = sm.run( tmp_path / "live", "live", ceiling=5_000_000, ledger_path=ledger, log=lambda line: None )
    assert code == 0 and report[ "mode" ] == "live" and report[ "calls" ] is None and stand.calls > 0
    held = rl.AccountLedger( ledger ).held_by_prefix( "seeded-miss-live" )
    assert held == 0 and '"kind": "end"' in ledger.read_text()          # closed at its spend (the stand-in sends no tokens), not held at the 5,000,000 ceiling


def test_the_summary_names_both_scenarios_and_the_verdict( tmp_path ):
    _, report = sm.run( tmp_path / "w", "dry", log=lambda line: None )
    text = "\n".join( sm.summary_lines( report ) )
    assert "dry-stand-in" in text and "REPAIRED" in text and "NO_INPUT_CHANGE" in text and "PASS" in text
    report[ "ok" ] = False
    assert "FAIL" in sm.summary_lines( report )[ -1 ]


def test_main_prints_the_table_and_returns_the_exit_code( tmp_path, capsys ):
    assert sm.main( [ "--work", str( tmp_path / "w" ) ] ) == 0
    assert "overall PASS" in capsys.readouterr().out
    assert sm.main( [ "--work", str( tmp_path / "x" ), "--live" ] ) == 2
    assert "seeded-miss-e2e: a live run needs" in capsys.readouterr().err


def test_main_without_a_work_folder_uses_a_temporary_one( tmp_path, monkeypatch, capsys ):
    made = tmp_path / "auto"
    def fake_mkdtemp( prefix ):
        made.mkdir()
        return str( made )
    monkeypatch.setattr( sm.tempfile, "mkdtemp", fake_mkdtemp )
    assert sm.main( [] ) == 0
    assert ( made / "report.json" ).is_file() and "report:" in capsys.readouterr().out


def test_the_size_check_stops_reading_file_sizes_once_the_limit_is_passed( tmp_path, monkeypatch ):
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range( 50 ): ( folder / f"{i:02d}.json" ).write_bytes( b"x" * 100 )
    monkeypatch.setattr( sm, "MAX_ANSWERS_BYTES", 250 )
    real, reads = pathlib.Path.stat, []
    def counting( self, *a, **k ):
        reads.append( self.name )
        return real( self, *a, **k )
    monkeypatch.setattr( pathlib.Path, "stat", counting )
    with pytest.raises( sm.RunRefused, match = "holds more than 250 bytes; copy only" ): sm.seed_cache( folder, tmp_path / "data" )
    files = { n for n in reads if n.endswith( ".json" ) }
    assert len( files ) == 3 and len( reads ) <= 8                                    # 100, 200, 300: the third file passes 250; 50 files exist


def test_a_folder_exactly_at_the_limit_is_accepted_and_copied( tmp_path, monkeypatch ):
    folder = tmp_path / "exact"
    folder.mkdir()
    for i in range( 2 ): ( folder / f"{i}.json" ).write_bytes( b"x" * 100 )
    monkeypatch.setattr( sm, "MAX_ANSWERS_BYTES", 200 )
    ( tmp_path / "data" ).mkdir()
    sm.seed_cache( folder, tmp_path / "data" )
    assert sorted( p.name for p in ( tmp_path / "data" / "jev-cache" ).iterdir() ) == [ "0.json", "1.json" ]
