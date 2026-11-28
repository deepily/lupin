"""
Tests that the rerun script's stamp and window split come from the shared helpers.

The old rerun tests do not fail when the commit stamp turns short or the split drifts from the freeze.
Each test here names one such change.
"""

import subprocess
import sys
import types

import pytest

import cosa.utils.util as cu
from cosa.research.preference_replay.retune import TUNE_FRACTION, split_windows

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import rerun_phases_7_to_11 as rrm   # noqa: E402
from scripts import check_bundle_freshness as cbf   # noqa: E402


def test_the_code_stamp_is_the_full_forty_character_commit_of_this_tree():
    stamp = rrm.code_sha( cu.get_project_root() )
    assert len( stamp ) == 40 and set( stamp ) <= set( "0123456789abcdef" )
    assert stamp.startswith( cbf.current_sha( cu.get_project_root() ) ), "the short sha is the start of the full one"


@pytest.mark.parametrize( "short, expected", [ ( True, [ "git", "rev-parse", "--short", "HEAD" ] ), ( False, [ "git", "rev-parse", "HEAD" ] ) ] )
def test_current_sha_asks_git_for_the_short_or_the_full_commit_and_reads_unknown_when_git_fails( monkeypatch, short, expected ):
    seen = []
    monkeypatch.setattr( subprocess, "run", lambda argv, **kw: seen.append( argv ) or types.SimpleNamespace( returncode=0, stdout="abc\n" ) )
    assert cbf.current_sha( "/x", short=short ) == "abc" and seen == [ expected ]
    monkeypatch.setattr( subprocess, "run", lambda argv, **kw: types.SimpleNamespace( returncode=128, stdout="" ) )
    assert cbf.current_sha( "/x", short=short ) == "unknown"


@pytest.mark.parametrize( "count", [ 0, 1, 2, 9, 10, 391, 1302 ] )
def test_split_by_time_cuts_where_the_freeze_cuts( count ):
    ids         = [ f"id{n}" for n in range( count ) ]
    tune, final = rrm.split_by_time( ids )
    assert ( len( tune ), len( final ) ) == split_windows( count, TUNE_FRACTION ) and tune + final == ids


def test_write_json_writes_exactly_this_text_one_space_per_level_sorted_and_no_trailing_newline( tmp_path ):
    path = tmp_path / "doc.json"
    sha  = rrm.write_json( str( path ), { "b": 1, "a": [ 2, { "d": 4, "c": 3 } ] } )
    assert path.read_text() == '{\n "a": [\n  2,\n  {\n   "c": 3,\n   "d": 4\n  }\n ],\n "b": 1\n}'
    assert sha == rrm.sha256_of( str( path ) )


def record( response_type, correct ):
    return { "meta": { "response_type": response_type, "correct": correct } }


def test_window_counts_reads_each_types_own_asks_and_correct_counts_from_the_final_window_only():
    tune, final = split_windows( 20 )
    head        = [ record( "yes_no", True ) for _ in range( tune ) ]
    tail        = [ record( "yes_no", True ), record( "yes_no", True ), record( "yes_no", False ) ] + \
                  [ record( "multiple_choice", n == 0 ) for n in range( final - 3 ) ]
    assert rrm.window_counts( head + tail ) == {
        "tune": tune, "final": final, "final_all": 2 + 1,
        "final_yes_no_asks": 3, "final_yes_no": 2, "final_mc_asks": final - 3, "final_mc": 1, "final_mc_scorable": None, "final_mc_scorable_correct": None }


def test_split_by_time_uses_the_fraction_it_is_given():
    ids = [ f"id{n}" for n in range( 10 ) ]
    assert rrm.split_by_time( ids, 0.5 ) == ( ids[ :5 ], ids[ 5: ] )
    assert rrm.split_by_time( ids, 0.2 ) == ( ids[ :2 ], ids[ 2: ] )
    assert TUNE_FRACTION not in ( 0.5, 0.2 ), "the default is a different fraction, so a dropped argument shows"
