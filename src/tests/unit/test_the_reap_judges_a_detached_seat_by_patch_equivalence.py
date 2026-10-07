#!/usr/bin/env python3
"""
A detached seat is judged by patch equivalence on a real scratch repository.

This branch takes seat work as cherry-picks, so a picked commit has a new sha and an
ancestry check still counts it. Every test here builds real commits and asks real git.
"""
import os
import subprocess
import sys

import pytest

_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src not in sys.path:
    sys.path.insert( 0, _src )

from lupin_mcp import reap_branch


def _git( cwd, *args ):
    return subprocess.run( [ "git", "-C", str( cwd ), *args ], capture_output=True, text=True )


def _must( cwd, *args ):
    result = _git( cwd, *args )
    assert result.returncode == 0, result.stderr
    return result


def _commit( cwd, name ):
    ( cwd / f"{name}.txt" ).write_text( f"{name}\n" )
    _must( cwd, "add", "-A" )
    _must( cwd, "commit", "-qm", name )


@pytest.fixture( autouse=True )
def _no_ambient_target( monkeypatch ):
    monkeypatch.delenv( reap_branch.TARGET_BRANCH_ENV, raising=False )


@pytest.fixture
def world( tmp_path ):
    """A main tree on `the-line`, and a detached seat worktree holding two commits of its own."""
    main = tmp_path / "main"
    main.mkdir()
    _must( main, "init", "-q", "-b", "the-line" )
    _must( main, "config", "user.email", "t@t" )
    _must( main, "config", "user.name", "t" )
    _commit( main, "base" )
    seat = tmp_path / "seat"
    _must( main, "worktree", "add", "-q", "--detach", str( seat ) )
    _commit( main, "line-moves-on" )          # so a pick gets a new parent, hence a new sha
    _must( seat, "config", "user.email", "t@t" )
    _must( seat, "config", "user.name", "t" )
    _commit( seat, "work-one" )
    _commit( seat, "work-two" )
    shas = _must( seat, "rev-list", "--reverse", "the-line..HEAD" ).stdout.split()
    return { "main": main, "seat": seat, "shas": shas }


def _probe( world, **kwargs ):
    identities = { "seat": { "cwd": str( world[ "seat" ] ), "persona": "Maya" } }
    return reap_branch.probe_seat_branches( identities, git_fn=lambda repo, *a: _git( repo, *a ), **kwargs )[ "seat" ]


def test_a_detached_seat_whose_commits_were_cherry_picked_raises_no_alarm( world ):
    """Kills the mutant that swaps `git cherry` back to `rev-list --count`."""
    for sha in world[ "shas" ]:
        _must( world[ "main" ], "cherry-pick", sha )
    assert _must( world[ "main" ], "rev-list", "--count", f"HEAD..{world[ 'shas' ][ -1 ]}" ).stdout.strip() == "2", \
        "premise: ancestry still calls the picked commits unmerged"
    outcome = _probe( world )
    assert outcome[ "status" ] == "merged" and outcome[ "commits" ] == 0
    assert reap_branch.branch_alarm( { "seat": outcome } ) is None


def test_a_detached_seat_with_one_commit_not_picked_alarms_and_names_it( world ):
    _must( world[ "main" ], "cherry-pick", world[ "shas" ][ 0 ] )
    outcome = _probe( world )
    assert outcome[ "status" ] == "detached" and outcome[ "commits" ] == 1
    assert outcome[ "shas" ] == [ world[ "shas" ][ 1 ][ :9 ] ]
    alarm = reap_branch.branch_alarm( { "seat": outcome } )
    assert "1 commit(s) not on the-line" in alarm and world[ "shas" ][ 1 ][ :9 ] in alarm


def test_the_resume_line_it_prints_runs_and_lists_the_unpicked_commit( world ):
    outcome = _probe( world )
    assert outcome[ "resume" ] == "git cherry -v the-line HEAD"
    listing = _git( world[ "seat" ], "cherry", "-v", "the-line", "HEAD" ).stdout
    assert [ l for l in listing.splitlines() if l.startswith( "+" ) ] and len( listing.splitlines() ) == 2


def test_a_detached_seat_with_no_commits_of_its_own_is_quiet( tmp_path ):
    main = tmp_path / "main"
    main.mkdir()
    _must( main, "init", "-q", "-b", "the-line" )
    _must( main, "config", "user.email", "t@t" )
    _must( main, "config", "user.name", "t" )
    _commit( main, "base" )
    seat = tmp_path / "seat"
    _must( main, "worktree", "add", "-q", "--detach", str( seat ) )
    outcome = _probe( { "main": main, "seat": seat } )
    assert outcome[ "status" ] == "merged"


def test_a_stale_branch_of_the_old_name_does_not_make_a_merged_seat_alarm( world ):
    """A local branch of the old hard-coded name lags the real line and is not consulted."""
    _must( world[ "main" ], "branch", "wip-v0.2.1-2026.08.29-cjflow-v2-followup", "the-line~0" )
    for sha in world[ "shas" ]:
        _must( world[ "main" ], "cherry-pick", sha )
    assert _probe( world )[ "status" ] == "merged"


def test_the_main_tree_detached_with_no_override_reads_probe_failed( world ):
    _must( world[ "main" ], "checkout", "-q", "--detach" )
    outcome = _probe( world )
    assert outcome[ "status" ] == "probe_failed"
    assert reap_branch.branch_alarm( { "seat": outcome } ) is not None


def test_the_env_override_beats_the_main_trees_branch( world, monkeypatch ):
    _must( world[ "main" ], "branch", "other-line", world[ "shas" ][ 1 ] )
    monkeypatch.setenv( reap_branch.TARGET_BRANCH_ENV, "other-line" )
    outcome = _probe( world )
    assert outcome[ "status" ] == "merged", "judged against other-line, which already holds both commits"
    monkeypatch.setenv( reap_branch.TARGET_BRANCH_ENV, "no-such-line" )
    assert _probe( world )[ "status" ] == "probe_failed"


def test_an_explicit_target_beats_the_env_override( world, monkeypatch ):
    monkeypatch.setenv( reap_branch.TARGET_BRANCH_ENV, "no-such-line" )
    assert _probe( world, target_branch="the-line" )[ "status" ] == "detached"


def test_git_failing_in_the_seat_reads_probe_failed( world ):
    def broken( repo, *args ):
        if args[ 0 ] == "cherry":
            return subprocess.CompletedProcess( args, 128, "", "fatal" )
        return _git( repo, *args )
    identities = { "seat": { "cwd": str( world[ "seat" ] ), "persona": "Maya" } }
    assert reap_branch.probe_seat_branches( identities, git_fn=broken )[ "seat" ][ "status" ] == "probe_failed"


def test_main_tree_branch_survives_a_git_that_raises_or_lists_nothing( world ):
    def raises( repo, *args ): raise OSError( "boom" )
    def empty( repo, *args ): return subprocess.CompletedProcess( args, 0, "", "" )
    def fails( repo, *args ): return subprocess.CompletedProcess( args, 1, "", "" )
    for runner in ( raises, empty, fails ):
        assert reap_branch.main_tree_branch( str( world[ "seat" ] ), runner ) is None
    def list_ok_then_raise( repo, *args ):
        if args[ 0 ] == "worktree": return subprocess.CompletedProcess( args, 0, "worktree /x\n", "" )
        raise OSError( "boom" )
    assert reap_branch.main_tree_branch( str( world[ "seat" ] ), list_ok_then_raise ) is None
    assert reap_branch.unpicked_commits( str( world[ "seat" ] ), "the-line", raises ) is None


def test_main_tree_branch_skips_listing_lines_that_do_not_name_a_worktree( world ):
    def junk_first( repo, *args ):
        if args[ 0 ] == "worktree":
            return subprocess.CompletedProcess( args, 0, f"HEAD abc\nworktree {world[ 'main' ]}\n", "" )
        return _git( repo, *args )
    assert reap_branch.main_tree_branch( str( world[ "seat" ] ), junk_first ) == "the-line"
