"""
The range gate replays each commit of a range through the commit gate.

Every test builds a small real git repository in a temporary directory. The gate itself is a
stand-in that reports what the worktree holds, so the tests read the staging and the verdicts.
"""

import io
import os
import signal
import subprocess
import sys

import pytest

from cosa.repo.doc_lint import range_gate


def _git( root, *args ):
    env = dict( os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t" )
    res = subprocess.run( [ "git", "-C", str( root ) ] + list( args ), capture_output=True, text=True, env=env )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _write( root, rel, text ):
    path = os.path.join( str( root ), rel )
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    with open( path, "w", encoding="utf-8" ) as handle: handle.write( text )


def _commit( root, message ):
    _git( root, "add", "-A" )
    _git( root, "commit", "-q", "-m", message )
    return _git( root, "rev-parse", "HEAD" )


@pytest.fixture
def repo( tmp_path ):
    root = tmp_path / "repo"
    root.mkdir()
    _git( root, "init", "-q", "-b", "main" )
    _write( root, "keep.py", "keep = 1\n" * 10 )
    _write( root, "old.py", "old = 1\n" * 10 )
    _write( root, "gone.py", "gone = 1\n" )
    base = _commit( root, "base" )
    _write( root, "added.py", "added = 1\n" )
    _write( root, "keep.py", "keep = 2\n" * 10 )
    one = _commit( root, "adds and modifies" )
    os.remove( os.path.join( str( root ), "gone.py" ) )
    os.rename( os.path.join( str( root ), "old.py" ), os.path.join( str( root ), "renamed.py" ) )
    two = _commit( root, "deletes and renames" )
    return { "root": str( root ), "base": base, "one": one, "two": two }


def _worktree( repo, tmp_path ):
    work = str( tmp_path / "work" )
    _git( repo[ "root" ], "worktree", "add", "-q", "--detach", work, repo[ "two" ] )
    return work


def test_the_commits_of_a_range_come_oldest_first( repo ):
    assert range_gate.list_commits( repo[ "root" ], repo[ "base" ], repo[ "two" ] ) == [ repo[ "one" ], repo[ "two" ] ]


def test_changes_name_additions_modifications_deletions_and_renames( repo ):
    assert sorted( range_gate.changes( repo[ "root" ], repo[ "one" ] ) ) == [ ( "A", "added.py", None ), ( "M", "keep.py", None ) ]
    assert sorted( range_gate.changes( repo[ "root" ], repo[ "two" ] ) ) == [ ( "D", "gone.py", None ), ( "R", "renamed.py", "old.py" ) ]


def test_a_root_commit_has_no_parent_to_compare_with( repo ):
    with pytest.raises( RuntimeError, match="failed" ): range_gate.changes( repo[ "root" ], repo[ "base" ] )


def test_staging_a_commit_in_its_parent_gives_the_tree_of_that_commit( repo, tmp_path ):
    work = _worktree( repo, tmp_path )
    for sha in ( repo[ "one" ], repo[ "two" ] ):
        found = range_gate.changes( repo[ "root" ], sha )
        _git( work, "checkout", "-q", "-f", "--detach", f"{sha}^1" )
        range_gate.stage( work, sha, found )
        assert _git( work, "write-tree" ) == _git( repo[ "root" ], "rev-parse", f"{sha}^{{tree}}" )


def _runner_for( verdicts ):
    seen = []
    def runner( worktree ):
        seen.append( _git( worktree, "diff", "--cached", "--name-status" ) )
        return verdicts.pop( 0 )
    runner.seen = seen
    return runner


def test_exit_three_is_a_refusal_that_carries_the_refusal_lines( repo, tmp_path ):
    runner = _runner_for( [ ( 3, "[doc-lint] REFUSED a.py: 1 findings\n[doc-lint] noise\n[doc-lint] 1 refusals, commit REFUSED\n" ) ] )
    result = range_gate.check_commit( repo[ "root" ], _worktree( repo, tmp_path ), repo[ "one" ], runner )
    assert ( result.verdict, result.gate_rc, result.subject ) == ( "refused", 3, "adds and modifies" )
    assert result.lines == [ "[doc-lint] REFUSED a.py: 1 findings", "[doc-lint] 1 refusals, commit REFUSED" ]
    assert "A\tadded.py" in runner.seen[ 0 ] and "M\tkeep.py" in runner.seen[ 0 ]


def test_exit_zero_passes_with_no_lines( repo, tmp_path ):
    result = range_gate.check_commit( repo[ "root" ], _worktree( repo, tmp_path ), repo[ "one" ], _runner_for( [ ( 0, "ok\n" ) ] ) )
    assert ( result.verdict, result.gate_rc, result.lines ) == ( "passed", 0, [] )


def test_any_other_exit_is_unchecked_and_keeps_the_last_output_lines( repo, tmp_path ):
    out    = "a\nb\nc\nd\n"
    result = range_gate.check_commit( repo[ "root" ], _worktree( repo, tmp_path ), repo[ "one" ], _runner_for( [ ( 1, out ) ] ) )
    assert ( result.verdict, result.gate_rc, result.lines ) == ( "unchecked", 1, [ "b", "c", "d" ] )


def test_a_git_failure_is_unchecked_and_names_the_failure( repo, tmp_path ):
    result = range_gate.check_commit( repo[ "root" ], _worktree( repo, tmp_path ), repo[ "base" ], _runner_for( [] ) )
    assert result.verdict == "unchecked" and result.gate_rc is None and "failed" in result.lines[ 0 ]


def test_the_worktree_is_reset_between_commits( repo, tmp_path ):
    work = _worktree( repo, tmp_path )
    _write( work, "stray.txt", "left over\n" )
    runner = _runner_for( [ ( 0, "" ), ( 0, "" ) ] )
    range_gate.check_range( repo[ "root" ], repo[ "base" ], repo[ "two" ], work, runner )
    assert "stray.txt" not in runner.seen[ 0 ] and not os.path.exists( os.path.join( work, "stray.txt" ) )
    assert "D\tgone.py" in runner.seen[ 1 ] and "R100\told.py\trenamed.py" in runner.seen[ 1 ]


def test_a_commit_that_cannot_be_judged_does_not_stop_the_ones_after_it( repo, tmp_path ):
    work    = _worktree( repo, tmp_path )
    results = range_gate.check_range( repo[ "root" ], repo[ "base" ], repo[ "two" ], work, _runner_for( [ ( 1, "x" ), ( 3, "refused" ) ] ) )
    assert [ r.verdict for r in results ] == [ "unchecked", "refused" ]


def test_a_merge_commit_is_judged_against_its_first_parent( repo, tmp_path ):
    root = repo[ "root" ]
    _git( root, "checkout", "-q", "-b", "side", repo[ "base" ] )
    _write( root, "side.py", "side = 1\n" )
    _commit( root, "side work" )
    _git( root, "checkout", "-q", "main" )
    _git( root, "merge", "-q", "--no-ff", "-m", "merge side", "side" )
    merge = _git( root, "rev-parse", "HEAD" )
    assert range_gate.changes( root, merge ) == [ ( "A", "side.py", None ) ]


@pytest.mark.parametrize( "verdicts,expected", [
    ( [], 0 ), ( [ "passed" ], 0 ), ( [ "passed", "refused" ], 1 ), ( [ "refused", "unchecked" ], 2 ), ( [ "unchecked" ], 2 ),
] )
def test_exit_code_ranks_unchecked_over_refused_over_passed( verdicts, expected ):
    assert range_gate.exit_code( [ range_gate.Result( "s", "t", v, None, [] ) for v in verdicts ] ) == expected


def test_the_report_has_a_line_per_commit_the_refusal_lines_and_a_summary():
    text = range_gate.report( "b", "h", [
        range_gate.Result( "a" * 40, "one", "passed", 0, [] ),
        range_gate.Result( "b" * 40, "two", "refused", 3, [ "why" ] ),
    ] )
    assert text.splitlines() == [
        "passed    aaaaaaaaa gate=0 one",
        "refused   bbbbbbbbb gate=3 two",
        "    why",
        "range b..h: 2 commits, 1 passed, 1 refused, 0 unchecked",
    ]


def test_run_gate_runs_the_gate_of_the_worktree_with_its_root_pinned( tmp_path ):
    pkg = tmp_path / "wt" / "src" / "cosa" / "repo" / "doc_lint"
    pkg.mkdir( parents=True )
    for folder in ( pkg.parent.parent, pkg.parent, pkg ): ( folder / "__init__.py" ).write_text( "" )
    ( pkg / "gate.py" ).write_text(
        "import os, sys\nprint( 'root', os.environ[ 'LUPIN_ROOT' ], sys.argv[ 1: ] )\nprint( 'REFUSED x', file=sys.stderr )\nsys.exit( 3 )\n" )
    code, output = range_gate.run_gate( str( tmp_path / "wt" ) )
    assert code == 3
    assert f"root {tmp_path / 'wt'}" in output and "--repo-root" in output and "REFUSED x" in output


def test_run_gate_takes_an_interpreter_override( tmp_path ):
    ( tmp_path / "src" ).mkdir()
    code, output = range_gate.run_gate( str( tmp_path ), python=sys.executable )
    assert code != 0 and "gate" in output


def test_main_reports_a_range_writes_the_file_and_removes_its_worktree( repo, tmp_path ):
    os.makedirs( os.path.join( repo[ "root" ], ".claude", "worktrees" ) )
    out_file = str( tmp_path / "report.txt" )
    stream   = io.StringIO()
    code     = range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "two" ], "--out", out_file, "--repo-root", repo[ "root" ] ], out=stream, runner=_runner_for( [ ( 0, "" ), ( 3, "refused" ) ] ) )
    assert code == 1
    with open( out_file, encoding="utf-8" ) as handle: assert handle.read() == stream.getvalue()
    assert "range " in stream.getvalue() and "1 refused" in stream.getvalue()
    assert os.listdir( os.path.join( repo[ "root" ], ".claude", "worktrees" ) ) == []
    assert "range-gate" not in _git( repo[ "root" ], "worktree", "list" )


def test_main_prints_without_a_file_when_none_is_named( repo ):
    os.makedirs( os.path.join( repo[ "root" ], ".claude", "worktrees" ) )
    stream = io.StringIO()
    code   = range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "one" ], "--repo-root", repo[ "root" ] ], out=stream, runner=_runner_for( [ ( 0, "" ) ] ) )
    assert code == 0 and "1 passed" in stream.getvalue()


def test_main_makes_its_worktree_folder_when_it_is_missing_and_works_from_a_linked_worktree( repo, tmp_path ):
    linked = _worktree( repo, tmp_path )
    stream = io.StringIO()
    code   = range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "one" ], "--repo-root", linked ], out=stream, runner=_runner_for( [ ( 0, "" ) ] ) )
    assert code == 0 and "1 passed" in stream.getvalue()
    assert os.listdir( os.path.join( repo[ "root" ], ".claude", "worktrees" ) ) == []


def _merge_range( repo ):
    root = repo[ "root" ]
    _git( root, "checkout", "-q", "-b", "side2", repo[ "base" ] )
    _write( root, "side2.py", "side = 1\n" )
    _commit( root, "side work 2" )
    _git( root, "checkout", "-q", "main" )
    _git( root, "merge", "-q", "--no-ff", "-m", "merge side2", "side2" )
    return _git( root, "rev-parse", "HEAD" )


def _folder( repo ):
    path = os.path.join( repo[ "root" ], ".claude", "worktrees" )
    os.makedirs( path, exist_ok=True )
    return path


def test_a_range_holding_a_merge_is_refused_whole_and_the_merge_is_named( repo, tmp_path ):
    merge = _merge_range( repo )
    with pytest.raises( range_gate.RangeRefused, match=merge ): range_gate.check_range( repo[ "root" ], repo[ "base" ], merge, _worktree( repo, tmp_path ), _runner_for( [] ) )


def test_main_exits_two_for_a_merge_and_runs_no_check_and_leaves_no_folder( repo ):
    merge  = _merge_range( repo )
    folder = _folder( repo )
    stream = io.StringIO()
    runner = _runner_for( [] )
    code   = range_gate.main( [ "--base", repo[ "base" ], "--head", merge, "--repo-root", repo[ "root" ] ], out=stream, runner=runner )
    assert code == 2 and merge in stream.getvalue() and runner.seen == [] and os.listdir( folder ) == []


def test_an_empty_range_exits_two_and_says_nothing_was_checked( repo ):
    folder = _folder( repo )
    stream = io.StringIO()
    code   = range_gate.main( [ "--base", repo[ "one" ], "--head", repo[ "one" ], "--repo-root", repo[ "root" ] ], out=stream, runner=_runner_for( [] ) )
    assert code == 2 and "holds 0 commits, nothing was checked" in stream.getvalue() and os.listdir( folder ) == []


def test_a_failure_after_the_worktree_exists_leaves_no_folder_and_no_registered_tree( repo ):
    folder = _folder( repo )
    def failing( worktree ): raise ValueError( "boom" )
    with pytest.raises( ValueError, match="boom" ): range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "two" ], "--repo-root", repo[ "root" ] ], out=io.StringIO(), runner=failing )
    assert os.listdir( folder ) == [] and "range-gate" not in _git( repo[ "root" ], "worktree", "list" )


def test_a_termination_signal_runs_the_cleanup_and_restores_the_handler( repo ):
    folder = _folder( repo )
    def guard( signum, frame ): raise AssertionError( "main installed no SIGTERM handler" )
    original = signal.signal( signal.SIGTERM, guard )
    try:
        def killer( worktree ): os.kill( os.getpid(), signal.SIGTERM )
        with pytest.raises( SystemExit ) as raised: range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "two" ], "--repo-root", repo[ "root" ] ], out=io.StringIO(), runner=killer )
        assert raised.value.code == 128 + signal.SIGTERM
        assert os.listdir( folder ) == [] and signal.getsignal( signal.SIGTERM ) == guard
    finally:
        signal.signal( signal.SIGTERM, original )


def test_a_report_with_an_unchecked_commit_shows_it():
    text = range_gate.report( "b", "h", [ range_gate.Result( "c" * 40, "x", "unchecked", 1, [ "line" ] ), range_gate.Result( "d" * 40, "y", "passed", 0, [] ) ] )
    assert text.splitlines()[ -1 ] == "range b..h: 2 commits, 1 passed, 0 refused, 1 unchecked"


def _stale_holder( repo, name, pid=None ):
    holder = os.path.join( _folder( repo ), name )
    os.makedirs( holder )
    _git( repo[ "root" ], "worktree", "add", "-q", "--detach", os.path.join( holder, "tree" ), repo[ "two" ] )
    if pid is not None:
        with open( os.path.join( holder, "pid" ), "w", encoding="utf-8" ) as handle: handle.write( str( pid ) )
    return holder


def _dead_pid():
    child = subprocess.Popen( [ sys.executable, "-c", "pass" ] )
    child.wait()
    return child.pid


def test_a_stale_holder_from_a_killed_run_is_swept_when_the_next_run_starts( repo ):
    no_pid = _stale_holder( repo, "range-gate-nopid" )
    dead   = _stale_holder( repo, "range-gate-dead", pid=_dead_pid() )
    live   = _stale_holder( repo, "range-gate-live", pid=os.getpid() )
    other  = os.path.join( _folder( repo ), "someone-elses" )
    os.makedirs( other )
    code   = range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "one" ], "--repo-root", repo[ "root" ] ], out=io.StringIO(), runner=_runner_for( [ ( 0, "" ) ] ) )
    assert code == 0
    assert not os.path.exists( no_pid ) and not os.path.exists( dead )
    assert os.path.exists( live ) and os.path.exists( other )
    listing = _git( repo[ "root" ], "worktree", "list" )
    assert "range-gate-nopid" not in listing and "range-gate-dead" not in listing and "range-gate-live" in listing
