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
