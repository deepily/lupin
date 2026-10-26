"""
Unit tests for every outcome of the seat worktree provisioner.

A fake `subprocess.run` drives each outcome, so no git or script runs.

Requires:
    - cosa.utils.seat_worktree is importable

Ensures:
    - each status the provisioner can report is reached by a test that names it
"""

import logging
import subprocess
from types import SimpleNamespace

import pytest

from cosa.utils import seat_worktree as sw


@pytest.fixture
def main_root( tmp_path, monkeypatch ):
    """A directory that holds the provisioning script, with the refuse-root guard unset."""
    monkeypatch.delenv( sw.REFUSE_ROOT_ENV, raising=False )
    script = tmp_path / "src" / "scripts" / "provision-seat-worktree.sh"
    script.parent.mkdir( parents=True )
    script.write_text( "#!/bin/bash\n" )
    return str( tmp_path )


def _fake_run( monkeypatch, returncode=0, stdout="", stderr="", raises=None ):
    """Replace subprocess.run in the module; record the argv it was called with."""
    calls = []
    def run( argv, **kwargs ):
        calls.append( argv )
        if raises is not None: raise raises
        return SimpleNamespace( returncode=returncode, stdout=stdout, stderr=stderr )
    monkeypatch.setattr( sw.subprocess, "run", run )
    return calls


@pytest.mark.parametrize( "failure", [ OSError( "no git" ), subprocess.TimeoutExpired( "git", 10 ) ] )
def test_main_checkout_falls_back_to_realpath_when_git_cannot_run( monkeypatch, tmp_path, failure ):
    """A git that cannot run leaves the path's own realpath as the answer."""
    _fake_run( monkeypatch, raises=failure )
    assert sw._main_checkout_of( tmp_path ) == str( tmp_path.resolve() )


def test_main_checkout_falls_back_to_realpath_on_nonzero_git_exit( monkeypatch, tmp_path ):
    """A non-zero `git rev-parse` is not trusted even if it printed something."""
    _fake_run( monkeypatch, returncode=128, stdout="/elsewhere/.git\n" )
    assert sw._main_checkout_of( tmp_path ) == str( tmp_path.resolve() )


def test_main_checkout_is_the_parent_of_the_common_git_dir( monkeypatch, tmp_path ):
    """The owner of a linked worktree is the parent of git's common dir."""
    _fake_run( monkeypatch, stdout=f"{tmp_path}/main/.git/\n" )
    assert sw._main_checkout_of( "/anywhere" ) == str( ( tmp_path / "main" ).resolve() )


def test_parse_keys_keeps_only_upper_case_names_and_survives_none():
    """Prose with an '=' and a lower-case name is dropped; None is an empty parse."""
    assert sw._parse_keys( "STATUS=created\nnote=ignored\nsee a=b prose\nWORKTREE = /x \n" ) == \
        { "STATUS": "created", "WORKTREE": "/x" }
    assert sw._parse_keys( None ) == {}


@pytest.mark.parametrize( "root,seat", [ ( "", "s" ), ( None, "s" ), ( "/r", "" ), ( "/r", None ) ] )
def test_a_missing_target_is_a_no_op( root, seat ):
    """Either argument falsy: no_target, nothing run, no work_dir."""
    got = sw.provision_seat_worktree( root, seat )
    assert got[ "status" ] == "no_target" and got[ "provisioned" ] is False and got[ "work_dir" ] is None


def test_the_refused_root_is_not_provisioned_into( monkeypatch, main_root ):
    """The env guard names the main checkout: refused_root, and the script never runs."""
    calls = _fake_run( monkeypatch, stdout="WORKTREE=/w\nSTATUS=created\n" )
    monkeypatch.setenv( sw.REFUSE_ROOT_ENV, main_root )
    monkeypatch.setattr( sw, "_main_checkout_of", lambda p: sw.os.path.realpath( p ) )
    got = sw.provision_seat_worktree( main_root, "seat-a" )
    assert got[ "status" ] == "refused_root" and calls == []


def test_a_missing_script_is_reported_not_raised( tmp_path, monkeypatch ):
    """No script under main_root: script_absent."""
    monkeypatch.delenv( sw.REFUSE_ROOT_ENV, raising=False )
    assert sw.provision_seat_worktree( str( tmp_path ), "seat-a" )[ "status" ] == "script_absent"


@pytest.mark.parametrize( "failure", [ OSError( "boom" ), subprocess.TimeoutExpired( "bash", 60 ) ] )
def test_a_script_that_cannot_run_is_a_logged_failure( monkeypatch, main_root, caplog, failure ):
    """OS and timeout errors both become status failed with a warning and no exit code."""
    _fake_run( monkeypatch, raises=failure )
    with caplog.at_level( logging.WARNING, logger=sw.logger.name ):
        got = sw.provision_seat_worktree( main_root, "seat-a" )
    assert got[ "status" ] == "failed" and got[ "exit_code"] is None and got[ "work_dir" ] is None
    assert "could not run" in caplog.text


def test_a_nonzero_exit_is_a_failure_carrying_stderr( monkeypatch, main_root, caplog ):
    """Exit 3: failed, exit code kept, stderr is the message, warning logged."""
    _fake_run( monkeypatch, returncode=3, stdout="WORKTREE=/w\n", stderr=" refused: path exists \n" )
    with caplog.at_level( logging.WARNING, logger=sw.logger.name ):
        got = sw.provision_seat_worktree( main_root, "seat-a" )
    assert ( got[ "status" ], got[ "exit_code" ], got[ "work_dir" ], got[ "provisioned" ] ) == ( "failed", 3, None, False )
    assert got[ "message" ] == "refused: path exists"
    assert "exit 3" in caplog.text


def test_a_nonzero_exit_with_no_stderr_falls_back_to_stdout( monkeypatch, main_root ):
    """stderr empty or None: the message comes from stdout."""
    _fake_run( monkeypatch, returncode=1, stdout="why on stdout\n", stderr=None )
    assert sw.provision_seat_worktree( main_root, "seat-a" )[ "message" ] == "why on stdout"


def test_a_zero_exit_without_a_worktree_line_is_a_failure( monkeypatch, main_root, caplog ):
    """A clean exit that names no tree is not success."""
    _fake_run( monkeypatch, stdout="STATUS=created\nprose\n" )
    with caplog.at_level( logging.WARNING, logger=sw.logger.name ):
        got = sw.provision_seat_worktree( main_root, "seat-a" )
    assert got[ "status" ] == "failed" and got[ "exit_code" ] == 0 and got[ "work_dir" ] is None
    assert "named no worktree" in caplog.text


@pytest.mark.parametrize( "stdout,expected", [
    ( "STATUS=created\nWORKTREE=/w\nDRIFT_BEHIND=4\n", 4 ),
    ( "STATUS=reused\nWORKTREE=/w\nDRIFT_BEHIND=abc\n", None ),
    ( "STATUS=reused\nWORKTREE=/w\n", None ),
] )
def test_drift_is_an_int_or_unknown( monkeypatch, main_root, stdout, expected ):
    """A non-numeric or absent DRIFT_BEHIND is None, never an exception."""
    _fake_run( monkeypatch, stdout=stdout )
    got = sw.provision_seat_worktree( main_root, "seat-a" )
    assert got[ "drift_behind" ] == expected and got[ "work_dir" ] == "/w"


def test_a_missing_status_line_reads_unknown_and_is_not_provisioned( monkeypatch, main_root ):
    """WORKTREE present, status line absent: status unknown, provisioned False."""
    _fake_run( monkeypatch, stdout="WORKTREE=/w\n" )
    got = sw.provision_seat_worktree( main_root, "seat-a" )
    assert got[ "status" ] == "unknown" and got[ "provisioned" ] is False


@pytest.mark.parametrize( "status,provisioned", [ ( "created", True ), ( "reused", True ), ( "already_seat_tree", False ) ] )
def test_only_created_and_reused_count_as_provisioned( monkeypatch, main_root, status, provisioned ):
    """The provisioned flag follows the status word, and the argv names script, root and seat."""
    calls = _fake_run( monkeypatch, stdout=f"STATUS={status}\nWORKTREE=/w\n" )
    got = sw.provision_seat_worktree( main_root, "seat-a", debug=True )
    assert got[ "provisioned" ] is provisioned and got[ "work_dir" ] == "/w" and got[ "exit_code" ] == 0
    assert calls[ 0 ][ 0 ] == "bash" and calls[ 0 ][ 2: ] == [ main_root, "seat-a" ]


def test_an_occupied_tree_is_never_handed_back_as_work_dir( monkeypatch, main_root ):
    """occupied: work_dir None, the refused tree and reason are named separately."""
    _fake_run( monkeypatch, stdout="STATUS=occupied\nWORKTREE=/busy\nOCCUPIED_REASON=live process\n" )
    got = sw.provision_seat_worktree( main_root, "seat-a" )
    assert got[ "status" ] == "occupied" and got[ "work_dir" ] is None and got[ "provisioned" ] is False
    assert got[ "occupied_tree" ] == "/busy" and got[ "occupied_reason" ] == "live process"


@pytest.mark.parametrize( "prov", [ None, {}, { "drift_behind": None }, { "drift_behind": 0 },
                                    { "drift_behind": -2 }, { "drift_behind": "3" } ] )
def test_nothing_to_disclose_returns_none( prov ):
    """No provisioning, unknown, zero, negative or non-int drift: no line at all."""
    assert sw.drift_disclosure( prov ) is None


def test_drift_disclosure_names_the_count_and_the_tree():
    """A positive int renders one sentence with the count and the work_dir."""
    line = sw.drift_disclosure( { "drift_behind": 7, "work_dir": "/x/y" } )
    assert "7 commit(s) behind" in line and "/x/y" in line


def test_quick_smoke_test_runs_clean( capsys ):
    """The inline smoke prints a tick for every case and no cross."""
    sw.quick_smoke_test()
    out = capsys.readouterr().out
    assert "✓" in out and "✗" not in out
