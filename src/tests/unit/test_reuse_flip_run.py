"""
The flip-rate driver: canary, approval, run and report, on the stand-in transport.

Thirty needs are asked five times each by the old question, every repeat keyed apart and stored nowhere.
The stand-in can be made to answer one need differently from its third request on, so a flip exists to find.
Nothing here reaches Jev, and the ledger is a scratch file.
"""
import collections
import json

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from tests.unit.test_reuse_e2e_cli import put
from tests.unit.test_reuse_e2e_run import IDS, make_wide_repo


def rows_of( n=30 ):
    return [ { "id": f"n{i:02d}", "need": f"A helper number {i} that does a distinct job for a caller.", "kind": "duplicate" if i % 2 == 0 else "distinct",
               "exclude": IDS[ i ] if i % 2 == 0 else None } for i in range( n ) ]


class Flippy( rr.StandIn ):
    """Answers a listed need as a strong match from its third request for each candidate on."""

    flip_needs, counts = (), collections.Counter()

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        need = body[ "state" ][ "need" ]
        if need in Flippy.flip_needs:
            for key, question in body[ "questions" ].items():
                Flippy.counts[ ( need, question[ "instructions" ] ) ] += 1
                if Flippy.counts[ ( need, question[ "instructions" ] ) ] >= 3: response[ "answers" ][ key ] = { "probabilities": { "reuse": 0.95, "extend": 0.03, "unrelated": 0.02 } }
        return response, meta


class Setup:
    """A scratch tree, ledger and needs file, and the argument lists that point at them."""

    def __init__( self, tmp_path, n=30 ):
        self.root, self.data, self.ledger = make_wide_repo( tmp_path ), tmp_path / "data", tmp_path / "ledger.jsonl"
        rl.AccountLedger.create( self.ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
        self.rows  = rows_of( n )
        self.needs = tmp_path / "flip-needs.json"
        self.sha   = put( self.needs, { "format": frun.NEEDS_FORMAT, "needs": self.rows } )

    def args( self, *command, extra=() ):
        base = [ "--root", str( self.root ), "--data", str( self.data ), "--ledger", str( self.ledger ) ]
        return base + list( extra ) + [ command[ 0 ], "--needs", str( self.needs ), "--needs-sha", self.sha ] + list( command[ 1: ] )

    def full( self, capsys, extra=() ):
        for step in ( ( "canary", "--ceiling", "100000000" ), ( "approve", "--by", "cheech", "--why", "read it" ), ( "run", "--ceiling", "300000000" ) ):
            assert frun.cli( self.args( *step, extra=extra ) ) == 0
        capsys.readouterr()
        assert frun.cli( self.args( "report", extra=extra ) ) == 0
        return capsys.readouterr().out


@pytest.fixture
def setup( tmp_path, monkeypatch ):
    Flippy.flip_needs, Flippy.counts = (), collections.Counter()
    monkeypatch.setattr( rr, "StandIn", Flippy )
    return Setup( tmp_path )


def test_the_needs_file_is_read_only_under_its_hash_and_must_hold_thirty_distinct_needs( tmp_path ):
    s = Setup( tmp_path )
    items = frun.load_flip_needs( s.needs, s.sha )
    assert len( items ) == 30 and items[ 0 ] == { "member": "n00", "need": s.rows[ 0 ][ "need" ], "exclude": IDS[ 0 ], "kind": "duplicate" }
    assert items[ 1 ][ "exclude" ] is None
    with pytest.raises( e2e.FrozenInputRefused, match="sha256" ): frun.load_flip_needs( s.needs, "0" * 64 )


@pytest.mark.parametrize( "damage, match", [
    ( lambda r: r[ :29 ], "at least 30" ),
    ( lambda r: r + [ { **r[ 0 ] } ], "repeated" ),
    ( lambda r: [ { **r[ 0 ], "need": r[ 1 ][ "need" ] } ] + r[ 1: ], "same need" ),
    ( lambda r: [ { **r[ 0 ], "need": "  " } ] + r[ 1: ], "empty need" ),
    ( lambda r: [ { **r[ 0 ], "kind": "similar" } ] + r[ 1: ], "kind" ),
    ( lambda r: [ { **r[ 0 ], "exclude": 7 } ] + r[ 1: ], "exclude" ) ] )
def test_a_needs_file_that_breaks_a_rule_is_refused( tmp_path, damage, match ):
    path = tmp_path / "bad.json"
    sha  = put( path, { "format": frun.NEEDS_FORMAT, "needs": damage( rows_of() ) } )
    with pytest.raises( e2e.FrozenInputRefused, match=match ): frun.load_flip_needs( path, sha )


def test_a_needs_file_in_another_format_is_refused( tmp_path ):
    path = tmp_path / "bad.json"
    sha  = put( path, { "format": "something-else", "needs": rows_of() } )
    with pytest.raises( e2e.FrozenInputRefused, match="format" ): frun.load_flip_needs( path, sha )


def test_a_canary_asks_the_first_five_needs_five_times_each_and_reports_the_numbers_first( setup, capsys ):
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000" ) ) == 0
    out = capsys.readouterr().out
    assert "canary fl-canary" in out and "searches 25" in out and "projection" in out and "ledger total before the first send: 0" in out
    record = json.loads( ( setup.data / "e2e-results" / "fl-canary.json" ).read_text( encoding="utf-8" ) )
    assert record[ "members" ] == [ "n00", "n01", "n02", "n03", "n04" ] and record[ "questions" ] == [ "r1", "r2", "r3", "r4", "r5" ]
    assert all( s[ "status" ] == "complete" for s in record[ "searches" ] ) and len( record[ "searches" ] ) == 25


def test_each_search_keeps_the_verdict_and_shortlist_of_its_repeat_for_the_report( setup ):
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000" ) ) == 0
    record = json.loads( ( setup.data / "e2e-results" / "fl-canary.json" ).read_text( encoding="utf-8" ) )
    row    = record[ "searches" ][ 2 ][ "rows" ][ 0 ]
    assert record[ "searches" ][ 2 ][ "question" ] == "r3" and row[ "repeat" ] == 3 and row[ "route" ] == "full"
    assert isinstance( row[ "verdict" ], str ) and row[ "shortlist" ] == sorted( row[ "shortlist" ] )


def test_the_run_waits_for_the_approval_then_asks_the_other_twenty_five_needs( setup, capsys ):
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000" ) ) == 0
    assert frun.cli( setup.args( "run", "--ceiling", "300000000" ) ) == 2                       # not approved yet
    assert "has not been approved" in capsys.readouterr().err
    assert frun.cli( setup.args( "approve", "--by", "cheech", "--why", "read it" ) ) == 0
    assert frun.cli( setup.args( "run", "--ceiling", "300000000" ) ) == 0
    record = json.loads( ( setup.data / "e2e-results" / "fl-run.json" ).read_text( encoding="utf-8" ) )
    assert len( record[ "members" ] ) == 25 and len( record[ "searches" ] ) == 125 and record[ "canary_run" ] == "fl-canary" and record[ "state" ] == "complete"


def test_steady_answers_report_no_flips_and_a_pass( setup, capsys ):
    out = setup.full( capsys )
    assert "0 of 30 needs flipped" in out and "state pass" in out and "route full" in out
    assert "duplicate 0 of 15" in out and "distinct 0 of 15" in out and "upper bound" in out


def test_one_need_that_changes_its_answer_is_found_and_named( setup, capsys ):
    Flippy.flip_needs = ( setup.rows[ 4 ][ "need" ], )
    out = setup.full( capsys )
    assert "1 of 30 needs flipped" in out and "flipped: n04" in out and "state pass" in out and "duplicate 1 of 15" in out


def test_two_changing_needs_is_over_five_percent_and_fails( setup, capsys ):
    Flippy.flip_needs = ( setup.rows[ 4 ][ "need" ], setup.rows[ 7 ][ "need" ] )
    out = setup.full( capsys )
    assert "2 of 30 needs flipped" in out and "flipped: n04, n07" in out and "state fail" in out and "distinct 1 of 15" in out


def test_four_repeats_is_inconclusive_whatever_they_show( setup, capsys ):
    out = setup.full( capsys, extra=[ "--repeats", "4" ] )
    assert "state inconclusive" in out and "repeats per need: 4" in out


def test_the_route_option_reaches_every_repeat_and_is_named_in_the_report( setup, monkeypatch, capsys ):
    seen = []
    real = rf.ask_repeat
    monkeypatch.setattr( rf, "ask_repeat", lambda ctx, need, member, run_index, **kw: seen.append( ( run_index, kw[ "route" ] ) ) or real( ctx, need, member, run_index, **kw ) )
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000", extra=[ "--route", "pages" ] ) ) == 0
    assert sorted( set( seen ) ) == [ ( i, "pages" ) for i in range( 1, 6 ) ]
    capsys.readouterr()
    assert frun.cli( setup.args( "report", extra=[ "--route", "pages" ] ) ) == 0
    assert "route pages" in capsys.readouterr().out


def test_a_route_that_is_neither_full_nor_pages_is_refused_by_the_parser( setup ):
    with pytest.raises( SystemExit ): frun.cli( setup.args( "canary", "--ceiling", "1", extra=[ "--route", "both" ] ) )


def test_the_estimate_sets_the_allowance_the_prefix_names_the_files_and_both_are_checked_first( setup, capsys ):
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000", extra=[ "--prefix", "flp", "--estimate-tokens", "2000000" ] ) ) == 0
    report = json.loads( ( setup.data / "e2e-results" / "flp-canary.canary.json" ).read_text( encoding="utf-8" ) )
    assert report[ "allowance_tokens" ] == 3_000_000 and ( setup.data / "e2e-results" / "flp-canary.json" ).exists()
    capsys.readouterr()
    for extra in ( [ "--prefix", "s2" ], [ "--prefix", "a,b" ], [ "--estimate-tokens", "0" ], [ "--repeats", "1" ] ):
        assert frun.cli( setup.args( "canary", "--ceiling", "1", extra=extra ) ) == 2 and capsys.readouterr().err


def test_the_default_estimate_is_the_arithmetic_of_this_run():
    assert frun.ESTIMATE_TOKENS == 319_000_000                                                  # 150 searches at 2,125,705 tokens each, rounded up, from the end-to-end run of 2026-10-09


def search( member, i, verdict="NEW", ids=(), status="complete", route="full" ):
    rows = [ { "repeat": i, "route": route, "verdict": verdict, "shortlist": list( ids ) } ] if status == "complete" else None
    return { "member": member, "question": f"r{i}", "status": status, "causes": [] if status == "complete" else [ "CALL_FAILED" ], "rows": rows }


def steady( items, repeats=5 ): return [ search( it[ "member" ], i ) for it in items for i in range( 1, repeats + 1 ) ]


def test_the_report_leaves_out_a_need_with_an_incomplete_repeat_and_says_so( tmp_path ):
    items = frun.load_flip_needs( *( lambda s: ( s.needs, s.sha ) )( Setup( tmp_path ) ) )
    runs  = steady( items )
    runs[ 7 ] = search( "n01", 3, status="incomplete" )
    runs[ 20 ] = search( "n04", 1, status="not_run" )
    lines = frun.report_lines( runs, items, 5 )
    text  = "\n".join( lines )
    assert "0 of 28 needs flipped" in text and "left out as incomplete: n01, n04" in text and "state inconclusive" in text


def test_the_report_with_no_searches_says_none_ran( tmp_path ):
    items = frun.load_flip_needs( *( lambda s: ( s.needs, s.sha ) )( Setup( tmp_path ) ) )
    assert frun.report_lines( [], items, 5 ) == [ "no searches have run yet" ]


def test_the_report_counts_a_changed_shortlist_and_notes_that_the_bound_is_above_the_line_even_when_clean( tmp_path ):
    items = frun.load_flip_needs( *( lambda s: ( s.needs, s.sha ) )( Setup( tmp_path ) ) )
    runs  = steady( items )
    runs[ 11 ] = search( "n02", 2, verdict="NEW", ids=[ "cosa.wide.f001" ] )
    text  = "\n".join( frun.report_lines( runs, items, 5 ) )
    assert "1 of 30 needs flipped" in text and "flipped: n02" in text
    clean = "\n".join( frun.report_lines( steady( items ), items, 5 ) )
    assert "above 5%" in clean and "the pass rule is on the rate" in clean


def test_an_ask_that_does_not_come_back_ok_is_passed_on_as_it_is_with_no_row( monkeypatch ):
    failed = { "status": "failed", "error": "no" }
    monkeypatch.setattr( rf, "ask_repeat", lambda ctx, need, member, run_index, **kw: failed )
    asks = frun.repeat_asks( 2, "full" )
    assert sorted( asks ) == [ "r1", "r2" ] and asks[ "r1" ]( None, { "need": "x", "exclude": None } ) is failed


def test_a_report_where_no_need_has_all_its_repeats_names_the_ones_left_out( tmp_path ):
    items = frun.load_flip_needs( *( lambda s: ( s.needs, s.sha ) )( Setup( tmp_path ) ) )
    runs  = [ search( "n01", i, status="incomplete" ) for i in range( 1, 6 ) ]
    assert frun.report_lines( runs, items, 5 ) == [ "no need has all its repeats complete yet", "left out as incomplete: n01" ]


def test_a_clean_report_over_enough_needs_has_an_upper_bound_under_the_line_and_no_note( ):
    items = [ { "member": f"n{i:03d}", "need": "x", "exclude": None, "kind": "duplicate" if i % 2 == 0 else "distinct" } for i in range( 200 ) ]
    text  = "\n".join( frun.report_lines( steady( items ), items, 5 ) )
    assert "0 of 200 needs flipped" in text and "state pass" in text and "above 5%" not in text


def test_a_command_with_no_root_given_and_none_in_the_environment_is_refused( setup, monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( rr.RunnerRefused, match = "LUPIN_ROOT" ): frun.main( [ "--data", str( setup.data ), "--ledger", str( setup.ledger ), "report", "--needs", str( setup.needs ), "--needs-sha", setup.sha ] )


def test_every_ask_sends_the_excluded_symbol_of_its_need_to_the_route( monkeypatch ):
    seen = []
    monkeypatch.setattr( rf, "ask_repeat", lambda ctx, need, member, run_index, **kw: seen.append( ( need, member, run_index ) ) or { "status": "failed" } )
    asks = frun.repeat_asks( 2, "full" )
    for name, ask in asks.items(): ask( None, { "need": "a need", "exclude": "cosa.wide.f001" } )
    assert seen == [ ( "a need", "cosa.wide.f001", 1 ), ( "a need", "cosa.wide.f001", 2 ) ]


def test_the_report_leaves_out_a_need_with_fewer_complete_records_than_repeats( tmp_path ):
    items = frun.load_flip_needs( *( lambda s: ( s.needs, s.sha ) )( Setup( tmp_path ) ) )
    runs  = [ r for r in steady( items ) if not ( r[ "member" ] == "n03" and r[ "question" ] in ( "r4", "r5" ) ) ]
    text  = "\n".join( frun.report_lines( runs, items, 5 ) )
    assert "left out as incomplete: n03" in text and "0 of 29 needs flipped" in text


def test_a_report_with_other_repeats_than_the_records_carry_is_refused_not_listed_as_incomplete( setup, capsys ):
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000" ) ) == 0
    capsys.readouterr()
    for given in ( "3", "7" ):
        assert frun.cli( setup.args( "report", extra=[ "--repeats", given ] ) ) == 2
        err = capsys.readouterr().err
        assert "5 repeats" in err and f"--repeats {given}" in err


def test_the_repeat_check_reads_the_questions_the_run_was_given_not_the_ones_that_finished():
    stopped = { "questions": [ "r1", "r2", "r3", "r4", "r5" ], "searches": [ search( "n01", i ) for i in range( 1, 4 ) ] }       # stopped after r3
    frun.check_repeats( [ stopped ], 5 )
    with pytest.raises( s1.DriverRefused, match="5 repeats per need.*--repeats 3" ): frun.check_repeats( [ stopped ], 3 )
    with pytest.raises( s1.DriverRefused, match="5 repeats per need.*--repeats 7" ): frun.check_repeats( [ stopped ], 7 )
    frun.check_repeats( [], 9 )


def test_a_canary_stopped_early_is_reported_with_its_own_repeats_not_refused( setup, capsys ):
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000" ) ) == 0
    path = setup.data / "e2e-results" / "fl-canary.json"
    record = json.loads( path.read_text( encoding="utf-8" ) )
    record[ "searches" ] = [ r for r in record[ "searches" ] if r[ "question" ] in ( "r1", "r2", "r3" ) ]
    path.write_text( json.dumps( record ), encoding="utf-8" )
    capsys.readouterr()
    assert frun.cli( setup.args( "report" ) ) == 0
    assert "left out as incomplete" in capsys.readouterr().out


@pytest.mark.parametrize( "short", [ "fl-run", "fl-canary" ] )
def test_the_repeat_check_reads_both_files_so_a_short_one_in_either_place_is_refused( setup, capsys, short ):
    assert frun.cli( setup.args( "canary", "--ceiling", "100000000" ) ) == 0
    results = setup.data / "e2e-results"
    canary  = json.loads( ( results / "fl-canary.json" ).read_text( encoding="utf-8" ) )
    for name in ( "fl-canary", "fl-run" ):
        record = dict( canary, run_name=name, questions=canary[ "questions" ][ :3 ] if name == short else canary[ "questions" ] )
        ( results / f"{name}.json" ).write_text( json.dumps( record ), encoding="utf-8" )
    capsys.readouterr()
    assert frun.cli( setup.args( "report", extra=[ "--repeats", "5" ] ) ) == 2
    assert "3 repeats per need" in capsys.readouterr().err
