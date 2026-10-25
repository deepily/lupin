"""Unit tests for semdup.score_run: worked scores, each unscorable cause and the command."""
import asyncio
import json
import re

import pytest

from cosa.repo.doc_lint import harness_runner as hr
from cosa.repo.semdup import blind as bl
from cosa.repo.semdup import config as cf
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex
from cosa.repo.semdup import judge as jd
from cosa.repo.semdup import pipeline as pl
from cosa.repo.semdup import score_run as sr

SCRUB  = bl.scrub_tokens( [ "ARM-WITH" ] )
MARKS  = [ "MARKA", "MARKB", "MARKC", "MARKD", "MARKE", "MARKF", "MARKG", "MARKH", "MARKI" ]
BLOCK  = re.compile( r"<(definition|candidate_c\d+)_([0-9a-f]{8})>\n(.*?)\n</\1_\2>", re.DOTALL )
JSCPD  = { "version": "5.3.3", "min_tokens": 50, "min_lines": 5, "chosen_in": "test" }


class FakeClient:
    """Embed a text as the counts of the marker words in it."""

    def __init__( self ):
        self.texts = []

    def embed( self, texts, content_type, role ):
        self.texts.extend( texts )
        return [ [ float( t.count( m ) ) for m in MARKS ] + [ float( len( t ) % 7 ) ] for t in texts ]

    def info( self ):
        return { "engines": { "code": { "revision": "r1" } } }


class FakeBackend:
    """Rule duplicate on a candidate that shares a marker word with the definition, else related."""

    name               = "max-plan"
    server_label       = "max-plan"
    temperature_record = "unsettable:bounded-cc"

    def __init__( self, garbage=False, pause=0.0 ):
        self.garbage = garbage
        self.pause   = pause
        self.calls   = 0
        self.now     = 0
        self.peak    = 0

    async def complete( self, model, system_prompt, user_prompt ):
        self.calls += 1
        self.now   += 1
        self.peak   = max( self.peak, self.now )
        try:
            if self.pause: await asyncio.sleep( self.pause )
            return self.answer( user_prompt )
        finally:
            self.now -= 1

    def answer( self, user_prompt ):
        if self.garbage: return "not json"
        blocks = { tag: body for tag, _, body in BLOCK.findall( user_prompt ) }
        mine   = set( re.findall( r"MARK[A-Z]", blocks[ "definition" ] ) )
        out    = []
        for tag, body in blocks.items():
            if tag == "definition": continue
            shared = mine & set( re.findall( r"MARK[A-Z]", body ) )
            verdict, reason = ( "duplicate", f"both carry {sorted( shared )[ 0 ]}" ) if shared else ( "related", "no marker shared" )
            out.append( { "candidate": tag.replace( "candidate_", "" ), "verdict": verdict, "reason": reason } )
        return json.dumps( { "verdicts": out } )


def _write( path, text ):
    """Write text to path and return the path."""
    path.write_text( text, encoding="utf-8" )
    return path


def function( name, marks, n ):
    """Return the source of a function that carries the marker words and a number only it has."""
    tags = ", ".join( f'"{m}"' for m in marks )
    return f"def {name}( items ):\n    tags = [ {tags} ]\n    out = []\n    for item in items:\n        out.append( item * {n} )\n    return out\n"


def build( tmp_path, new=(), server=(), extra=None, passing=4, backend=None, min_nodes=10, **over ):
    """Write a client tree and return ( run, wiring ); new and server list ( name, markers )."""
    root = tmp_path / "tree"
    ( root / "client" ).mkdir( parents=True )
    ( root / "server" ).mkdir()
    files = []
    for i, ( name, marks ) in enumerate( new ):
        path = root / "client" / f"{name}.py"
        path.write_text( function( name, marks, i + 2 ), encoding="utf-8" )
        files.append( path )
    for name, text in ( extra or {} ).items():
        path = root / "client" / name
        path.write_text( text, encoding="utf-8" )
        files.append( path )
    server_paths = []
    for i, ( name, marks ) in enumerate( server ):
        path = root / "server" / f"{name}.py"
        path.write_text( function( name, marks, i + 50 ), encoding="utf-8" )
        server_paths.append( path )
    cfg = cf.build_config( "max-plan", "unsettable:bounded-cc", "stub", *jd.prompt_parts(), SCRUB, 4000, JSCPD, min_nodes=min_nodes )
    frozen = tmp_path / "frozen.json"
    cf.freeze( cfg, str( frozen ) )
    backend = backend or FakeBackend()
    wiring = { "frozen_path": str( frozen ), "live": cfg, "root": root, "files": files,
               "server_defs": ex.extract_tree( root, server_paths, "server" )[ "definitions" ] if server_paths else [],
               "client": FakeClient(), "cache_dir": tmp_path / "vectors", "scrub": SCRUB, "structural_pairs": lambda defs: [], "backend": backend,
               "ledger": hr.Ledger( str( tmp_path / "ledger.jsonl" ), jd.ledger_binding( "cli 1", backend ) ), "slot": 0, "parallel": 1, **over }
    return { "run": "r1", "passing_tests": passing, "pass_rate": 0.9 }, wiring


# ---- worked scores ------------------------------------------------------------------------------------------------

def test_three_new_definitions_that_share_a_marker_are_one_cluster_with_surplus_two_and_a_score(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKA" ] ), ( "a3", [ "MARKA" ] ) ], passing=4 )
    report = sr.score_run( run, w )
    assert report[ "status" ] == "scored" and report[ "surplus" ] == 2 and report[ "clusters" ] == { "3": 1 }
    assert report[ "score_per_100" ] == 50.0 and report[ "pass_rate" ] == 0.9 and report[ "server" ] == "max-plan"
    assert report[ "definitions" ] == { "new": 3, "server": 0, "judged": 3 } and report[ "below_min" ] == 0 and report[ "unjudged" ] == []
    assert report[ "config_sha" ] == cf.verify_frozen( w[ "frozen_path" ], w[ "live" ] )[ "config_sha" ]


def test_two_new_and_one_server_that_share_a_marker_are_one_cluster_with_surplus_two(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKA" ] ) ], server=[ ( "s1", [ "MARKA" ] ) ] )
    report = sr.score_run( run, w )
    assert report[ "surplus" ] == 2 and report[ "clusters" ] == { "3": 1 } and report[ "definitions" ][ "server" ] == 1


def test_one_new_and_one_server_that_share_a_marker_give_surplus_one(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ], server=[ ( "s1", [ "MARKA" ] ), ( "s2", [ "MARKB" ] ) ] )
    report = sr.score_run( run, w )
    assert report[ "surplus" ] == 1 and report[ "clusters" ] == { "2": 1 } and report[ "score_per_100" ] == 25.0


def test_one_new_definition_that_matches_two_server_definitions_gives_surplus_one(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ], server=[ ( "s1", [ "MARKA" ] ), ( "s2", [ "MARKA" ] ) ] )
    report = sr.score_run( run, w )
    assert report[ "clusters" ] == { "3": 1 } and report[ "surplus" ] == 1


def test_a_chain_a_b_c_through_two_different_markers_is_one_cluster_of_three(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKA", "MARKB" ] ), ( "a3", [ "MARKB" ] ) ] )
    report = sr.score_run( run, w )
    assert report[ "clusters" ] == { "3": 1 } and report[ "surplus" ] == 2


def test_clusters_of_two_three_and_four_are_counted_by_their_distinct_sizes(tmp_path):
    new = [ ( f"p{i}", [ "MARKA" ] ) for i in range( 2 ) ] + [ ( f"q{i}", [ "MARKB" ] ) for i in range( 3 ) ] + [ ( f"r{i}", [ "MARKC" ] ) for i in range( 4 ) ]
    run, w = build( tmp_path, new=new, passing=6 )
    report = sr.score_run( run, w )
    assert report[ "clusters" ] == { "2": 1, "3": 1, "4": 1 } and report[ "surplus" ] == 1 + 2 + 3 and report[ "score_per_100" ] == 100.0


def test_related_rulings_join_nothing(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKB" ] ), ( "a3", [ "MARKC" ] ) ] )
    report = sr.score_run( run, w )
    assert report[ "status" ] == "scored" and report[ "clusters" ] == {} and report[ "surplus" ] == 0 and report[ "score_per_100" ] == 0.0


def test_a_definition_under_min_nodes_is_counted_and_not_judged(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ], extra={ "tiny.py": "def tiny():\n    return 1\n" } )
    report = sr.score_run( run, w )
    assert report[ "definitions" ] == { "new": 2, "server": 0, "judged": 1 } and report[ "below_min" ] == 1


def test_a_definition_with_exactly_min_nodes_is_judged_and_one_node_fewer_is_not(tmp_path):
    ( tmp_path / "at" ).mkdir()
    ( tmp_path / "under" ).mkdir()
    probe     = ex.extract_python( tmp_path, _write( tmp_path / "probe.py", function( "a1", [ "MARKA" ], 2 ) ), "new" )[ 0 ][ "nodes" ]
    run, w    = build( tmp_path / "at", new=[ ( "a1", [ "MARKA" ] ) ], min_nodes=probe )
    run2, w2  = build( tmp_path / "under", new=[ ( "a1", [ "MARKA" ] ) ], min_nodes=probe + 1 )
    assert sr.score_run( run, w )[ "definitions" ][ "judged" ] == 1
    assert sr.score_run( run2, w2 )[ "definitions" ][ "judged" ] == 0 and sr.score_run( run2, w2 )[ "below_min" ] == 1


def test_a_python_file_that_does_not_parse_is_listed_and_the_run_still_scores(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ], extra={ "broken.py": "def (:\n" } )
    report = sr.score_run( run, w )
    assert report[ "status" ] == "scored" and report[ "skipped_python" ] == [ "client/broken.py" ]


def test_the_client_builds_flag_is_copied_when_the_result_has_it_and_absent_when_not(tmp_path):
    ( tmp_path / "first" ).mkdir()
    ( tmp_path / "second" ).mkdir()
    run, w   = build( tmp_path / "first", new=[ ( "a1", [ "MARKA" ] ) ] )
    run2, w2 = build( tmp_path / "second", new=[ ( "a1", [ "MARKA" ] ) ] )
    assert "client_builds" not in sr.score_run( run, w )
    assert sr.score_run( { **run2, "client_builds": False }, w2 )[ "client_builds" ] is False


# ---- the shared pipeline ------------------------------------------------------------------------------------------

def test_judge_all_embeds_the_definition_text_cut_at_the_frozen_length_and_runs_the_calls_in_parallel(tmp_path):
    backend = FakeBackend( pause=0.05 )
    run, w  = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKB" ] ), ( "a3", [ "MARKC" ] ) ], backend=backend, parallel=3 )
    cfg     = cf.verify_frozen( w[ "frozen_path" ], w[ "live" ] )
    defs    = ex.extract_tree( w[ "root" ], w[ "files" ], "new" )[ "definitions" ]
    pl.judge_all( defs, defs, cfg, w, 0 )
    assert backend.peak == 3 and sorted( w[ "client" ].texts ) == sorted( d[ "text" ] for d in defs )
    short = { **cfg, "body_chars": 5 }
    pl.judge_all( defs, defs, short, { **w, "cache_dir": tmp_path / "other" }, 1 )
    assert {t for t in w[ "client" ].texts if len( t ) == 5} != set()


def test_judge_all_rules_each_definition_once_per_slot_and_reads_a_finished_slot_from_the_ledger(tmp_path):
    run, w  = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKA" ] ) ], server=[ ( "s1", [ "MARKB" ] ) ] )
    cfg     = cf.verify_frozen( w[ "frozen_path" ], w[ "live" ] )
    defs    = ex.extract_tree( w[ "root" ], w[ "files" ], "new" )[ "definitions" ]
    seen    = []
    w       = { **w, "structural_pairs": lambda given: seen.append( sorted( d[ "id" ] for d in given ) ) or [] }
    zero    = pl.judge_all( defs, defs + w[ "server_defs" ], cfg, w, 0 )
    assert w[ "backend" ].calls == 2 and {( v[ "id" ], v[ "slot" ] ) for v in zero[ "verdicts" ]} == { ( d[ "id" ], 0 ) for d in defs }
    pl.judge_all( defs, defs + w[ "server_defs" ], cfg, w, 0 )
    assert w[ "backend" ].calls == 2
    one = pl.judge_all( defs, defs + w[ "server_defs" ], cfg, w, 1 )
    assert w[ "backend" ].calls == 4 and {v[ "slot" ] for v in one[ "verdicts" ]} == { 1 }
    assert seen[ 0 ] == sorted( d[ "id" ] for d in defs + w[ "server_defs" ] )


# ---- one test per unscorable cause ----------------------------------------------------------------------------------

def assert_unscorable( report, cause ):
    """Check the shape every unscorable report shares."""
    assert report[ "status" ] == "unscorable" and report[ "cause" ] == cause and report[ "evidence" ][ "detail" ]
    assert "score_per_100" not in report and report[ "run" ] == "r1" and report[ "passing_tests" ] == 4 and report[ "pass_rate" ] == 0.9


def test_an_extraction_that_does_not_close_is_unscorable_with_the_files_named(tmp_path, monkeypatch):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ] )
    partial = { "definitions": [], "skipped_python": [], "skipped_script": [ "client/bad.ts" ],
                "script_accounts": [ { "file": "client/odd.ts", "reported": 1, "anonymous_walked": 1, "function_like_total": 3 },
                                     { "file": "client/ok.ts", "reported": 2, "anonymous_walked": 1, "function_like_total": 3 } ], "repeated_ids": [] }
    monkeypatch.setattr( sr.extract, "extract_tree", lambda root, files, origin: partial )
    report = sr.score_run( run, w )
    assert_unscorable( report, err.EXTRACT_INCOMPLETE )
    assert report[ "evidence" ][ "files" ] == [ "client/bad.ts", "client/odd.ts" ]


def test_zero_passing_tests_is_unscorable_and_the_raw_surplus_is_still_in_the_report(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKA" ] ), ( "a3", [ "MARKA" ] ) ], passing=0 )
    report = sr.score_run( run, w )
    assert report[ "status" ] == "unscorable" and report[ "cause" ] == err.NO_PASSING_TESTS and "score_per_100" not in report
    assert report[ "surplus" ] == 2 and report[ "clusters" ] == { "3": 1 } and "raw surplus 2" in report[ "evidence" ][ "detail" ]


def test_a_definition_carrying_a_scrub_token_is_unscorable_as_a_blindness_breach(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ], extra={ "leak.py": function( "leak", [ "MARKA" ], 9 ).replace( "MARKA", "check_exists" ) } )
    report = sr.score_run( run, w )
    assert_unscorable( report, err.BLINDNESS_BREACH )
    assert "check_exists" in report[ "evidence" ][ "detail" ]


def test_a_definition_the_judge_could_not_read_makes_the_run_unscorable_as_incomplete(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKA" ] ) ], backend=FakeBackend( garbage=True ) )
    report = sr.score_run( run, w )
    assert_unscorable( report, err.RUN_INCOMPLETE )
    assert [ u[ "code" ] for u in report[ "unjudged" ] ] == [ err.JUDGE_UNREADABLE, err.JUDGE_UNREADABLE ] and "2 definitions" in report[ "evidence" ][ "detail" ]


def test_another_error_from_the_judge_is_not_swallowed_into_a_report(tmp_path, monkeypatch):
    async def boom( *args, **kwargs ): raise err.SemdupError( err.JUDGE_UNREADABLE, "unexpected" )
    monkeypatch.setattr( pl.judge, "judge_run", boom )
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ] )
    with pytest.raises( err.SemdupError ) as caught: sr.score_run( run, w )
    assert caught.value.code == err.JUDGE_UNREADABLE


def test_a_live_configuration_that_differs_from_the_frozen_one_raises_and_is_not_a_report(tmp_path):
    run, w = build( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ] )
    with pytest.raises( err.SemdupError ) as caught: sr.score_run( run, { **w, "live": { **w[ "live" ], "body_chars": 1 } } )
    assert caught.value.code == err.CONFIG_DRIFT


# ---- the command ----------------------------------------------------------------------------------------------------

def run_dir_for( tmp_path, **kwargs ):
    """Write a run directory with a result file and return it with its wiring callable."""
    run, w = build( tmp_path, **kwargs )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ( run_dir / sr.RESULT_FILE ).write_text( json.dumps( run ), encoding="utf-8" )
    return run_dir, ( lambda directory, result: w )


def test_main_writes_the_report_once_and_exits_zero_for_a_scored_run(tmp_path, capsys):
    run_dir, wiring = run_dir_for( tmp_path, new=[ ( "a1", [ "MARKA" ] ), ( "a2", [ "MARKA" ] ) ] )
    assert sr.main( [ "--run-dir", str( run_dir ) ], wiring ) == 0
    written = json.loads( ( run_dir / sr.REPORT_FILE ).read_text( encoding="utf-8" ) )
    assert written[ "status" ] == "scored" and written[ "surplus" ] == 1 and "r1: scored" in capsys.readouterr().out
    with pytest.raises( FileExistsError ): sr.main( [ "--run-dir", str( run_dir ) ], wiring )


def test_main_exits_two_for_an_unscorable_run_and_still_writes_its_report(tmp_path):
    run_dir, wiring = run_dir_for( tmp_path, new=[ ( "a1", [ "MARKA" ] ) ], passing=0 )
    assert sr.main( [ "--run-dir", str( run_dir ) ], wiring ) == 2
    written = json.loads( ( run_dir / sr.REPORT_FILE ).read_text( encoding="utf-8" ) )
    assert written[ "status" ] == "unscorable" and written[ "cause" ] == err.NO_PASSING_TESTS


def test_main_without_a_run_dir_stops_in_the_argument_parser(tmp_path):
    with pytest.raises( SystemExit ) as caught: sr.main( [], lambda d, r: None )
    assert caught.value.code == 2


# ---- aggregate_runs, moved here from config ---------------------------------------------------------------------------

def policy_cfg( policy ):
    """Return a configuration holding only the policy field aggregate_runs reads."""
    return { "unscorable_policy": policy }


def test_aggregate_runs_refuses_an_unscorable_run_when_no_policy_is_named():
    reports = [ { "run": "r1", "score_per_100": 2.0 }, { "run": "r2", "status": "unscorable", "cause": "NO_PASSING_TESTS" } ]
    for empty in ( None, "", " " ):
        with pytest.raises( err.SemdupError, match="r2" ) as caught: sr.aggregate_runs( reports, policy_cfg( empty ), { "stub": print } )
        assert caught.value.code == err.POLICY_UNDECIDED


def test_aggregate_runs_over_only_scorable_reports_needs_no_policy_and_calls_none():
    reports = [ { "run": "r1" }, { "run": "r2", "status": "scored" } ]
    called  = []
    assert sr.aggregate_runs( reports, policy_cfg( None ), { "stub": called.append } ) == { "reports": reports, "unscorable": [], "policy": None, "applied": None }
    assert called == []


def test_aggregate_runs_hands_the_reports_to_the_named_policy_and_returns_its_answer_unchanged():
    reports  = [ { "run": "r3", "status": "unscorable" }, { "run": "r1" }, { "run": "r2", "status": "unscorable" } ]
    received = []
    def stub( given ):
        received.append( given )
        return { "verdict": "stub says continue" }
    out = sr.aggregate_runs( reports, policy_cfg( "stub" ), { "stub": stub, "other": lambda given: "wrong" } )
    assert received == [ reports ] and received[ 0 ] is not None
    assert out == { "reports": reports, "unscorable": [ "r3", "r2" ], "policy": "stub", "applied": { "verdict": "stub says continue" } }
    assert out[ "reports" ] is not reports


def test_aggregate_runs_names_a_policy_the_registry_does_not_hold():
    reports = [ { "run": "r1", "status": "unscorable" } ]
    with pytest.raises( err.SemdupError ) as caught: sr.aggregate_runs( reports, policy_cfg( "worst-rank" ), { "stub": print } )
    assert caught.value.code == err.POLICY_UNKNOWN and "worst-rank" in caught.value.detail and "stub" in caught.value.detail
