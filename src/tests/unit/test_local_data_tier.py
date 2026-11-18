"""
Unit tests for `cosa.utils.local_data_tier` and its wiring in `src/conftest.py`.

The wiring tests run a real child pytest over `test_local_data_real_export.py`.
`LUPIN_LOCAL_DATA_DIR` points it at a folder the test chooses.
So they give the same verdict in a worktree and in the main checkout.
"""

import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import cosa.utils.util as cu
from cosa.utils import local_data_tier as ldt

REAL_TEST_FILE = "src/tests/unit/test_local_data_real_export.py"
SYNTHETIC_PATH = "/src/tests/fixtures/preference_learning/synthetic-export.json"


def _report( node_id="t::a", when="call", skipped=False, passed_marker=True, longrepr=None ):
    """A stand-in for pytest's TestReport carrying only what the ledger reads."""
    keywords = { ldt.MARKER_NAME: 1 } if passed_marker else { }
    return SimpleNamespace( nodeid=node_id, when=when, skipped=skipped, keywords=keywords, longrepr=longrepr )


def _run_child( data_dir, *extra ):
    """Run the real-data test file in a child pytest and return ( exit code, stdout )."""
    env = dict( os.environ, **{ ldt.OVERRIDE_ENV_VAR: str( data_dir ) } )
    done = subprocess.run( [ sys.executable, "-m", "pytest", REAL_TEST_FILE, "-q", "-p", "no:cacheprovider", *extra ],
                           cwd=cu.get_project_root(), env=env, capture_output=True, text=True, timeout=300 )
    return done.returncode, done.stdout


def test_local_data_dir_defaults_to_the_project_root_path( monkeypatch ):
    monkeypatch.delenv( ldt.OVERRIDE_ENV_VAR, raising=False )
    assert ldt.local_data_dir() == cu.get_project_root() + "/io/write-ups/online-preference-learning"


def test_local_data_dir_honours_the_override( monkeypatch, tmp_path ):
    monkeypatch.setenv( ldt.OVERRIDE_ENV_VAR, str( tmp_path ) )
    assert ldt.local_data_dir() == str( tmp_path )


def test_require_local_file_returns_the_path_when_present( monkeypatch, tmp_path ):
    ( tmp_path / "present.json" ).write_text( "{}" )
    monkeypatch.setenv( ldt.OVERRIDE_ENV_VAR, str( tmp_path ) )
    assert ldt.require_local_file( "present.json" ) == str( tmp_path ) + "/present.json"


def test_require_local_file_skips_by_name_when_absent( monkeypatch, tmp_path ):
    monkeypatch.setenv( ldt.OVERRIDE_ENV_VAR, str( tmp_path ) )
    with pytest.raises( pytest.skip.Exception ) as skipped:
        ldt.require_local_file( "absent.json" )
    assert str( tmp_path ) + "/absent.json" in str( skipped.value )


def test_skip_reason_strips_the_prefix_from_a_tuple_and_a_string():
    assert ldt.skip_reason( _report( longrepr=( "f.py", 3, "Skipped: gone" ) ) ) == "gone"
    assert ldt.skip_reason( _report( longrepr="Skipped: also gone" ) ) == "also gone"


def test_ledger_counts_ran_and_skipped_and_ignores_other_reports():
    ledger = ldt.LocalDataLedger()
    ledger.on_report( _report( "t::ran" ) )
    ledger.on_report( _report( "t::setup", when="setup" ) )
    ledger.on_report( _report( "t::skip", when="setup", skipped=True, longrepr=( "f", 1, "Skipped: why" ) ) )
    ledger.on_report( _report( "t::other", passed_marker=False ) )
    assert ledger.ran == 1
    assert ledger.skipped == [ ( "t::skip", "why" ) ]


def test_summary_lines_name_each_skip_and_print_the_zero_case():
    empty = ldt.LocalDataLedger()
    assert empty.summary_lines() == [ "[local_data] ran=0 skipped=0" ]
    ledger = ldt.LocalDataLedger()
    ledger.skipped.append( ( "t::skip", "why" ) )
    assert ledger.summary_lines() == [ "[local_data] ran=0 skipped=1", "[local_data] SKIPPED t::skip: why" ]


@pytest.mark.parametrize( "skipped, ran, required, expected", [
    ( 0, 2, True,  False ),
    ( 1, 2, True,  True  ),
    ( 0, 0, True,  True  ),
    ( 1, 0, False, False ),
    ( 0, 0, False, False ),
] )
def test_should_fail_only_when_required_and_skipped_or_never_ran( skipped, ran, required, expected ):
    ledger         = ldt.LocalDataLedger()
    ledger.ran     = ran
    ledger.skipped = [ ( "t::x", "r" ) ] * skipped
    assert ledger.should_fail( required ) is expected


def test_add_require_option_registers_a_boolean_flag_off_by_default():
    seen = { }
    parser = SimpleNamespace( addoption=lambda *a, **k: seen.update( args=a, kwargs=k ) )
    ldt.add_require_option( parser )
    assert seen[ "args" ] == ( "--require-local-data", )
    assert seen[ "kwargs" ][ "default" ] is False


def test_a_skipped_local_data_run_prints_the_skip_by_name_and_passes_without_the_flag( tmp_path ):
    code, out = _run_child( tmp_path )
    assert code == 0
    assert "[local_data] ran=0 skipped=3" in out
    assert "[local_data] SKIPPED " + REAL_TEST_FILE + "::test_the_real_export_still_matches_the_manifest_sha" in out


def test_a_skipped_local_data_run_fails_with_require_local_data( tmp_path ):
    code, out = _run_child( tmp_path, "--require-local-data" )
    assert code == 1
    assert "[local_data] SKIPPED " in out


def _planted_export():
    """An invented export shaped like the real one, with one free-text neighbour answer."""
    asks, neighbours = [ ], { }
    for index in range( 139 ):
        ref   = f"ask-{index}"
        cases = [ { "case_id": f"case-{index}-{k}", "answer": "yes" } for k in range( 3 if index < 33 else 2 ) ]
        asks.append( { "response_type": "yes_no", "neighbours_ref": ref, "actual": { "value": "yes" } } )
        neighbours[ ref ] = { "by_dot": cases }
    neighbours[ "ask-0" ][ "by_dot" ][ 0 ][ "answer" ] = "invented free text"
    asks += [ { "response_type": "multiple_choice" } ] * 146
    return { "predictions": asks }, { "neighbours": neighbours }


def test_planted_data_runs_the_tier_and_passes_with_require_local_data( tmp_path ):
    export, neighbours = _planted_export()
    export_bytes       = json.dumps( export ).encode()
    ( tmp_path / "2026.11.17-recent-predictions-285.json" ).write_bytes( export_bytes )
    ( tmp_path / "2026.11.17-recent-predictions-285-neighbours.json" ).write_text( json.dumps( neighbours ) )
    ( tmp_path / "manifest-before.txt" ).write_text(
        hashlib.sha256( export_bytes ).hexdigest() + "  2026.11.17-recent-predictions-285.json\n" )
    code, out = _run_child( tmp_path, "--require-local-data" )
    assert code == 0
    assert "[local_data] ran=3 skipped=0" in out


def test_the_committed_fixture_is_synthetic_and_carries_the_pilot_write_in_pattern():
    export      = json.load( open( cu.get_project_root() + SYNTHETIC_PATH ) )
    predictions = export[ "predictions" ]
    assert export[ "manifest" ][ "synthetic" ] is True
    cards, write_ins = 0, 0
    for p in predictions:
        if p[ "response_type" ] != "multiple_choice": continue
        found = 0
        for q in p[ "options" ][ "questions" ]:
            offered = [ o[ "label" ] for o in q[ "options" ] ]
            if not q[ "multi_select" ] and p[ "actual" ][ "answers" ][ q[ "header" ] ] not in offered: found += 1
        cards     += 1 if found else 0
        write_ins += found
    assert ( write_ins, cards ) == ( 9, 7 )
    assert all( p[ "ref" ][ "database" ] == "synthetic" for p in predictions )
