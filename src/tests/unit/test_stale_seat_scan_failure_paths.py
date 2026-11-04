"""
Failure-path guards for `src/scripts/stale-seat-scan.py`.

The sibling file drives the happy paths and the process boundary.
These cases run in-process, so coverage sees them, and each makes one git call fail.
A scan that treats a failed git call as "nothing there" would report a clean fleet.
"""

import importlib.util
import subprocess

import pytest

import cosa.utils.util as cu

SCAN_PATH = cu.get_project_root() + "/src/scripts/stale-seat-scan.py"


def _load_scan():
    """Import the scan module despite its dashed filename."""
    spec   = importlib.util.spec_from_file_location( "stale_seat_scan_failures", SCAN_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def scan_mod():
    return _load_scan()


def _git( repo, *args ):
    done = subprocess.run( [ "git", "-C", str( repo ), *args ], capture_output=True, text=True )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def repo( tmp_path ):
    """One repo on branch `target` holding a committed file, a dirty file and an untracked file."""
    root = tmp_path / "repo"
    root.mkdir()
    _git( root, "init", "-q", "-b", "target" )
    _git( root, "config", "user.email", "guard@example.com" )
    _git( root, "config", "user.name", "guard" )
    ( root / "tracked.py" ).write_text( "a = 1\n" )
    _git( root, "add", "-A" )
    _git( root, "commit", "-q", "-m", "base" )
    return root


def test_current_branch_names_the_checked_out_branch( scan_mod, repo ):
    assert scan_mod.current_branch( repo ) == "target"


def test_current_branch_refuses_a_detached_head( scan_mod, repo ):
    _git( repo, "checkout", "-q", "--detach" )
    with pytest.raises( LookupError, match = "detached" ):
        scan_mod.current_branch( repo )


def test_current_branch_refuses_when_git_cannot_answer( scan_mod, tmp_path ):
    with pytest.raises( LookupError, match = "detached" ):
        scan_mod.current_branch( tmp_path / "not-a-repo" )


def test_worktree_roots_is_empty_when_git_cannot_enumerate( scan_mod, tmp_path ):
    assert scan_mod.worktree_roots( tmp_path / "not-a-repo" ) == []


def test_files_touched_by_is_empty_when_git_show_fails( scan_mod, tmp_path ):
    assert scan_mod.files_touched_by( tmp_path / "not-a-repo", [ "deadbeef" ] ) == set()


def test_files_touched_by_discards_output_from_a_failed_show( scan_mod, monkeypatch ):
    """A failing git may still print something; a failure answer is empty, never partial."""
    monkeypatch.setattr( scan_mod, "_git", lambda *a: ( 128, "partial.py\n" ) )
    assert scan_mod.files_touched_by( "wt", [ "deadbeef" ] ) == set()


def test_files_touched_by_with_no_shas_runs_no_git( scan_mod, monkeypatch ):
    monkeypatch.setattr( scan_mod, "_git", lambda *a: pytest.fail( "git must not run for no shas" ) )
    assert scan_mod.files_touched_by( "anywhere", [ ] ) == set()


@pytest.mark.parametrize( "failing, expected", [
    ( "diff",     { "untracked.py", "ahead.py" } ),
    ( "ls-files", { "dirty.py", "ahead.py" } ),
    ( "rev-list", { "dirty.py", "untracked.py" } ),
] )
def test_one_failed_git_call_drops_only_its_own_files( scan_mod, monkeypatch, failing, expected ):
    """Each of the three sources is independent: losing one must not lose the other two."""
    answers = {
        "diff"     : "dirty.py\n",
        "ls-files" : "untracked.py\n",
        "rev-list" : "abc123\n",
    }

    def fake_git( worktree, *args ):
        verb = args[ 0 ]
        if verb == "show": return 0, "\x00\nahead.py\n"
        return ( 1, "" ) if verb == failing else ( 0, answers[ verb ] )

    monkeypatch.setattr( scan_mod, "_git", fake_git )
    assert scan_mod.files_this_seat_touched( "wt", "target" ) == expected


def test_main_exits_two_and_says_nothing_was_scanned_when_scan_refuses( scan_mod, monkeypatch, capsys ):
    def refuse( target ): raise LookupError( "zero worktrees" )
    monkeypatch.setattr( scan_mod, "scan", refuse )
    assert scan_mod.main( [ "--target", "target" ] ) == 2
    err = capsys.readouterr().err
    assert "REFUSED: zero worktrees" in err
    assert "Do not read this as a clean run" in err


def test_main_defaults_the_target_from_the_current_branch( scan_mod, monkeypatch, capsys ):
    seen = {}
    monkeypatch.setattr( scan_mod, "current_branch", lambda: "the-branch" )
    def fake_scan( target ):
        seen[ "target" ] = target
        return {}, { "worktrees": 1, "occupied": 1, "behind": 0, "unresolved": 0, "overlapping": 0 }
    monkeypatch.setattr( scan_mod, "scan", fake_scan )
    assert scan_mod.main( [ ] ) == 0
    assert seen[ "target" ] == "the-branch"


def test_mine_that_is_not_a_hit_exits_two_when_another_tree_was_not_judged( scan_mod, monkeypatch, tmp_path, capsys ):
    """A hit elsewhere plus an unjudged tree: the caller's own tree is unknown, not clean."""
    stale = { "/some/other/tree": { "pids": [ "1" ], "behind": 1, "moved": 1, "touched": 1, "overlap": [ "x.py" ] } }
    stats = { "worktrees": 3, "occupied": 2, "behind": 1, "unresolved": 1, "overlapping": 1 }
    monkeypatch.setattr( scan_mod, "scan", lambda target: ( stale, stats ) )
    rc = scan_mod.main( [ "--target", "target", "--mine", str( tmp_path ) ] )
    assert rc == 2
    assert "NOT judged" in capsys.readouterr().err
