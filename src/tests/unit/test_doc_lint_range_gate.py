"""
The range gate replays each commit of a range through the commit gate.

Every test builds a small real git repository in a temporary directory. The gate itself is a
stand-in that reports what the worktree holds, so the tests read the staging and the verdicts.
"""

import io
import os
import re
import shutil
import signal
import subprocess
import sys

import pytest

import cosa.utils.util as cu
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
    seen  = []
    modes = []
    def runner( worktree, blocking=False ):
        seen.append( _git( worktree, "diff", "--cached", "--name-status" ) )
        modes.append( blocking )
        return verdicts.pop( 0 )
    runner.seen  = seen
    runner.modes = modes
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
    assert ( result.verdict, result.gate_rc, result.lines[ :3 ] ) == ( "unchecked", 1, [ "b", "c", "d" ] )


def test_a_git_failure_is_unchecked_and_names_the_failure( repo, tmp_path ):
    result = range_gate.check_commit( repo[ "root" ], _worktree( repo, tmp_path ), repo[ "base" ], _runner_for( [] ) )
    assert result.verdict == "unchecked" and result.gate_rc is None and "failed" in result.lines[ 0 ]


def test_an_unchecked_commit_names_its_worktree_and_the_time( repo, tmp_path, monkeypatch ):
    monkeypatch.setattr( range_gate, "now", lambda: "2026-10-10T01:02:03-04:00" )
    work   = _worktree( repo, tmp_path )
    result = range_gate.check_commit( repo[ "root" ], work, repo[ "one" ], _runner_for( [ ( 1, "a\nb\n" ) ] ) )
    assert result.verdict == "unchecked"
    assert f"worktree {work}" in result.lines and "at 2026-10-10T01:02:03-04:00" in result.lines


def test_a_git_failure_keeps_every_line_of_the_git_error( repo, tmp_path, monkeypatch ):
    monkeypatch.setattr( range_gate, "now", lambda: "t" )
    def failing( root, *args ): raise RuntimeError( "git checkout x failed: error: first\nhint: second\nhint: third" )
    monkeypatch.setattr( range_gate, "git", failing )
    work   = str( tmp_path / "w" )
    result = range_gate.check_commit( "r", work, "abc", _runner_for( [] ) )
    assert result.lines == [ "git checkout x failed: error: first", "hint: second", "hint: third", f"worktree {work}", "at t" ]


def test_a_passed_or_refused_commit_carries_no_worktree_line( repo, tmp_path ):
    work = _worktree( repo, tmp_path )
    for code in ( 0, 3 ):
        result = range_gate.check_commit( repo[ "root" ], work, repo[ "one" ], _runner_for( [ ( code, "REFUSED x\n" ) ] ) )
        assert not any( line.startswith( "worktree " ) for line in result.lines )


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


def _incoming_runner():
    """Give a stand-in gate that records what MERGE_HEAD holds in the worktree while it runs."""
    seen = []
    def runner( worktree, blocking=False ):
        marker = _git( worktree, "rev-parse", "--path-format=absolute", "--git-path", "MERGE_HEAD" )
        if os.path.exists( marker ):
            with open( marker, encoding="utf-8" ) as handle: seen.append( handle.read() )
        else: seen.append( None )
        return 0, ""
    runner.seen = seen
    return runner


def test_a_merge_in_a_range_is_replayed_with_its_other_parent_as_the_incoming_commit( repo, tmp_path ):
    merge   = _merge_range( repo )
    root    = repo[ "root" ]
    side    = _git( root, "rev-parse", "side2" )
    work    = _worktree( repo, tmp_path )
    runner  = _incoming_runner()
    commits = range_gate.list_commits( root, repo[ "base" ], merge )
    results = range_gate.check_range( root, repo[ "base" ], merge, work, runner )
    assert len( commits ) == 4 and [ r.verdict for r in results ] == [ "passed" ] * 4 and range_gate.other_parents( root, merge ) == [ side ]
    assert runner.seen == [ f"{side}\n" if sha == merge else None for sha in commits ]             # only the merge has an incoming commit
    assert results[ commits.index( merge ) ].lines == [ f"merge commit: judged with {side[ :9 ]} as the incoming commit, so a line that came in unchanged with it was not enforced" ]
    assert [ r.lines for r in results if r.sha != merge ] == [ [] ] * 3
    assert not os.path.exists( range_gate.incoming_path( work ) )                                  # nothing is left for the next replay


def test_the_incoming_commit_file_is_removed_when_the_gate_cannot_be_run( repo, tmp_path ):
    merge = _merge_range( repo )
    work  = _worktree( repo, tmp_path )
    def broken( worktree, blocking=False ): raise RuntimeError( "the gate could not start" )
    result = range_gate.check_commit( repo[ "root" ], work, merge, broken )
    assert result.verdict == "unchecked" and result.lines[ 0 ] == "the gate could not start" and not os.path.exists( range_gate.incoming_path( work ) )


def test_an_octopus_merge_records_every_other_parent_in_order( repo, tmp_path ):
    root = repo[ "root" ]
    for name in ( "left", "right" ):
        _git( root, "checkout", "-q", "-b", name, repo[ "base" ] )
        _write( root, f"{name}.py", "side = 1\n" )
        _commit( root, f"{name} work" )
    _git( root, "checkout", "-q", "main" )
    _git( root, "merge", "-q", "--no-ff", "-m", "merge both", "left", "right" )
    merge  = _git( root, "rev-parse", "HEAD" )
    runner = _incoming_runner()
    assert range_gate.check_commit( root, _worktree( repo, tmp_path ), merge, runner ).verdict == "passed"
    assert runner.seen == [ f"{_git( root, 'rev-parse', 'left' )}\n{_git( root, 'rev-parse', 'right' )}\n" ]


def test_main_judges_a_range_that_holds_a_merge_and_leaves_no_folder( repo ):
    merge  = _merge_range( repo )
    folder = _folder( repo )
    stream = io.StringIO()
    runner = _incoming_runner()
    code   = range_gate.main( [ "--base", repo[ "base" ], "--head", merge, "--repo-root", repo[ "root" ] ], out=stream, runner=runner )
    assert code == 0 and len( runner.seen ) == 4 and os.listdir( folder ) == []
    assert stream.getvalue().splitlines()[ -1 ] == f"range {repo[ 'base' ]}..{merge}: 4 commits, 4 passed, 0 refused, 0 unchecked"


def test_a_commit_that_adds_a_file_whose_name_is_not_utf8_is_staged_and_judged( repo, tmp_path ):
    root = repo[ "root" ]
    name = "caf\udce9.py"                                                                        # the byte 0xE9, as Python reads a name from the file system
    with open( os.path.join( root, name ), "w", encoding="utf-8" ) as handle: handle.write( "x = 1\n" )
    odd = _commit( root, "adds a name that is not UTF-8" )
    os.rename( os.path.join( root, name ), os.path.join( root, "moved\udce9.py" ) )
    moved = _commit( root, "moves it" )
    assert range_gate.changes( root, odd ) == [ ( "A", name, None ) ] and range_gate.changes( root, moved ) == [ ( "R", "moved\udce9.py", name ) ]
    work = _worktree( repo, tmp_path )
    for sha in ( odd, moved ):
        assert range_gate.check_commit( root, work, sha, _runner_for( [ ( 0, "" ) ] ) ).verdict == "passed"
        assert _git( work, "write-tree" ) == _git( root, "rev-parse", f"{sha}^{{tree}}" )


def test_an_empty_range_exits_two_and_says_nothing_was_checked( repo ):
    folder = _folder( repo )
    stream = io.StringIO()
    code   = range_gate.main( [ "--base", repo[ "one" ], "--head", repo[ "one" ], "--repo-root", repo[ "root" ] ], out=stream, runner=_runner_for( [] ) )
    assert code == 2 and "holds 0 commits, nothing was checked" in stream.getvalue() and os.listdir( folder ) == []


def test_a_failure_after_the_worktree_exists_leaves_no_folder_and_no_registered_tree( repo ):
    folder = _folder( repo )
    def failing( worktree, blocking=False ): raise ValueError( "boom" )
    with pytest.raises( ValueError, match="boom" ): range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "two" ], "--repo-root", repo[ "root" ] ], out=io.StringIO(), runner=failing )
    assert os.listdir( folder ) == [] and "range-gate" not in _git( repo[ "root" ], "worktree", "list" )


def test_a_termination_signal_runs_the_cleanup_and_restores_the_handler( repo ):
    folder = _folder( repo )
    def guard( signum, frame ): raise AssertionError( "main installed no SIGTERM handler" )
    original = signal.signal( signal.SIGTERM, guard )
    try:
        def killer( worktree, blocking=False ): os.kill( os.getpid(), signal.SIGTERM )
        with pytest.raises( SystemExit ) as raised: range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "two" ], "--repo-root", repo[ "root" ] ], out=io.StringIO(), runner=killer )
        assert raised.value.code == 128 + signal.SIGTERM
        assert os.listdir( folder ) == [] and signal.getsignal( signal.SIGTERM ) == guard
    finally:
        signal.signal( signal.SIGTERM, original )


def test_a_report_with_an_unchecked_commit_shows_it():
    text = range_gate.report( "b", "h", [ range_gate.Result( "c" * 40, "x", "unchecked", 1, [ "line" ] ), range_gate.Result( "d" * 40, "y", "passed", 0, [] ) ] )
    assert text.splitlines()[ -1 ] == "range b..h: 2 commits, 1 passed, 0 refused, 1 unchecked"


def _stale_holder( repo, name, remove_tree=False ):
    holder = os.path.join( _folder( repo ), name )
    os.makedirs( holder )
    _git( repo[ "root" ], "worktree", "add", "-q", "--detach", os.path.join( holder, "tree" ), repo[ "two" ] )
    if remove_tree: shutil.rmtree( os.path.join( holder, "tree" ) )
    return holder


def _dead_pid():
    child = subprocess.Popen( [ sys.executable, "-c", "pass" ] )
    child.wait()
    return child.pid


def test_a_stale_holder_from_a_killed_run_is_swept_when_the_next_run_starts( repo ):
    unnamed = _stale_holder( repo, "range-gate-nopid" )
    dead    = _stale_holder( repo, f"range-gate-{_dead_pid()}-abc" )
    live    = _stale_holder( repo, f"range-gate-{os.getpid()}-abc" )
    other   = os.path.join( _folder( repo ), "someone-elses" )
    os.makedirs( other )
    code    = range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "one" ], "--repo-root", repo[ "root" ] ], out=io.StringIO(), runner=_runner_for( [ ( 0, "" ) ] ) )
    assert code == 0
    assert not os.path.exists( unnamed ) and not os.path.exists( dead )
    assert os.path.exists( live ) and os.path.exists( other )
    listing = _git( repo[ "root" ], "worktree", "list" )
    assert "range-gate-nopid" not in listing and "abc" in listing and f"range-gate-{os.getpid()}-abc" in listing


def test_the_holder_of_a_running_check_carries_the_pid_of_its_run_from_the_moment_it_exists( repo ):
    _folder( repo )
    names = []
    def runner( worktree, blocking=False ):
        names.append( os.path.basename( os.path.dirname( worktree ) ) )
        return 0, ""
    range_gate.main( [ "--base", repo[ "base" ], "--head", repo[ "one" ], "--repo-root", repo[ "root" ] ], out=io.StringIO(), runner=runner )
    assert names[ 0 ].startswith( f"range-gate-{os.getpid()}-" )


def test_the_sweep_prunes_the_registration_of_a_holder_whose_tree_is_already_gone( repo ):
    gone = _stale_holder( repo, f"range-gate-{_dead_pid()}-gone", remove_tree=True )
    assert "gone" in _git( repo[ "root" ], "worktree", "list" )
    assert range_gate.sweep_stale( repo[ "root" ], os.path.dirname( gone ) ) == [ os.path.basename( gone ) ]
    assert "range-gate" not in _git( repo[ "root" ], "worktree", "list" )


def test_a_commit_after_a_merge_is_judged_with_no_incoming_commit( repo, tmp_path ):
    merge = _merge_range( repo )
    _write( repo[ "root" ], "later.py", "later = 1\n" )
    head = _commit( repo[ "root" ], "after the merge" )
    assert head != merge and range_gate.other_parents( repo[ "root" ], head ) == []
    runner  = _incoming_runner()
    results = range_gate.check_range( repo[ "root" ], merge, head, _worktree( repo, tmp_path ), runner )
    assert [ ( r.sha, r.verdict, r.lines ) for r in results ] == [ ( head, "passed", [] ) ] and runner.seen == [ None ]


def test_the_sweep_prunes_a_registration_whose_whole_holder_folder_is_gone( repo ):
    holder = _stale_holder( repo, f"range-gate-{os.getpid()}-gone" )
    shutil.rmtree( holder )
    assert "range-gate" in _git( repo[ "root" ], "worktree", "list" )
    assert range_gate.sweep_stale( repo[ "root" ], os.path.dirname( holder ) ) == []
    assert "range-gate" not in _git( repo[ "root" ], "worktree", "list" )


def test_a_holder_name_without_a_decimal_pid_or_without_a_suffix_has_no_pid():
    assert range_gate.holder_pid( "range-gate-x-y" ) is None
    assert range_gate.holder_pid( "range-gate-123" ) is None
    assert range_gate.holder_pid( "range-gate-123-abc" ) == 123


def test_a_sweep_over_a_holder_named_with_a_non_numeric_pid_removes_it_and_does_not_raise( repo ):
    odd = os.path.join( _folder( repo ), "range-gate-x-y" )
    os.makedirs( odd )
    assert range_gate.sweep_stale( repo[ "root" ], os.path.dirname( odd ) ) == [ "range-gate-x-y" ]
    assert not os.path.exists( odd )


def test_now_gives_local_time_to_the_second_with_its_offset():
    assert re.fullmatch( r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", range_gate.now() )


# ---- the blocking epoch ----------------------------------------------------------------------

DOC_LINT  = os.path.join( cu.get_project_root(), "src", "cosa", "repo", "doc_lint" )
OLD_GATE  = os.path.join( cu.get_project_root(), "src", "tests", "unit", "fixtures", "doc-lint-gate-at-59c155252.py.txt" )
SEEDED    = "# Page\n\nThis is NOT fine.\n"
EPOCH_SHA = "0123456789abcdef0123456789abcdef01234567"
FROM_WORK = " (read from the working copy: the head of the range has no epoch file)"


def test_the_committed_epoch_file_is_readable_and_holds_at_most_one_full_sha():
    with open( os.path.join( cu.get_project_root(), range_gate.EPOCH_PATH ), encoding="utf-8" ) as handle: text = handle.read()
    assert range_gate.EPOCH_PATH == "src/conf/doc-gate-blocking-epoch.txt" and text.startswith( "#" )
    value = range_gate.parse_blocking_epoch( text )
    assert value is None or re.fullmatch( r"[0-9a-f]{40}", value )


@pytest.mark.parametrize( "text", [ "", "\n\n", "# a comment\n", "# a comment\n\n   # another\n" ] )
def test_an_epoch_file_without_a_value_holds_no_commit_to_blocking( text ):
    assert range_gate.parse_blocking_epoch( text ) is None


def test_an_epoch_file_with_one_full_sha_gives_that_sha():
    assert range_gate.parse_blocking_epoch( f"# why\n{EPOCH_SHA}\n" ) == EPOCH_SHA
    assert range_gate.parse_blocking_epoch( f"  {EPOCH_SHA}  " ) == EPOCH_SHA


@pytest.mark.parametrize( "text", [ "0123456\n", f"{EPOCH_SHA}\n{EPOCH_SHA}\n", "not a sha\n", EPOCH_SHA.upper() + "\n", f"{EPOCH_SHA} trailing\n", EPOCH_SHA + "0\n" ] )
def test_a_malformed_epoch_value_is_refused_and_never_read_as_absent( text ):
    with pytest.raises( range_gate.RangeRefused, match="malformed" ): range_gate.parse_blocking_epoch( text )


def test_reading_the_epoch_of_a_tree_gives_none_a_commit_or_a_refusal( repo ):
    root = repo[ "root" ]
    assert range_gate.read_blocking_epoch( root ) is None                                   # no file
    _write( root, range_gate.EPOCH_PATH, "# nothing recorded\n" )
    assert range_gate.read_blocking_epoch( root ) is None
    _write( root, range_gate.EPOCH_PATH, repo[ "one" ] + "\n" )
    assert range_gate.read_blocking_epoch( root ) == repo[ "one" ]
    _write( root, range_gate.EPOCH_PATH, EPOCH_SHA + "\n" )
    with pytest.raises( range_gate.RangeRefused, match="names no commit" ): range_gate.read_blocking_epoch( root )


def test_a_commit_is_held_to_blocking_only_when_its_parent_descends_from_the_epoch( repo ):
    root = repo[ "root" ]
    assert range_gate.is_held( root, None, repo[ "two" ] ) is False
    assert range_gate.is_held( root, repo[ "one" ], repo[ "two" ] ) is True                 # the parent is the epoch itself
    assert range_gate.is_held( root, repo[ "base" ], repo[ "two" ] ) is True
    assert range_gate.is_held( root, repo[ "one" ], repo[ "one" ] ) is False                # the epoch commit: its parent predates it
    assert range_gate.is_held( root, repo[ "two" ], repo[ "one" ] ) is False
    with pytest.raises( RuntimeError, match="merge-base" ): range_gate.is_held( root, EPOCH_SHA, repo[ "two" ] )


def test_check_commit_runs_blocking_for_a_held_commit_and_warn_mode_with_the_predating_words_for_an_older_one( repo, tmp_path ):
    work   = _worktree( repo, tmp_path )
    runner = _runner_for( [ ( 0, "" ), ( 0, "" ), ( 3, "[doc-lint] REFUSED x\n" ), ( 0, "" ) ] )
    older  = range_gate.check_commit( repo[ "root" ], work, repo[ "one" ], runner, repo[ "one" ] )
    newer  = range_gate.check_commit( repo[ "root" ], work, repo[ "two" ], runner, repo[ "one" ] )
    old_no = range_gate.check_commit( repo[ "root" ], work, repo[ "one" ], runner, repo[ "one" ] )
    plain  = range_gate.check_commit( repo[ "root" ], work, repo[ "one" ], runner )
    note   = f"predates the blocking epoch {repo[ 'one' ][ :9 ]}: judged in warn mode, findings on its staged lines were not enforced"
    assert runner.modes == [ False, True, False, False ]
    assert ( older.verdict, older.blocking, older.lines ) == ( "passed", False, [ note ] )
    assert ( newer.verdict, newer.blocking, newer.lines ) == ( "passed", True, [] )
    assert ( old_no.verdict, old_no.blocking, old_no.lines ) == ( "refused", False, [ "[doc-lint] REFUSED x", note ] )
    assert ( plain.verdict, plain.blocking, plain.lines ) == ( "passed", False, [] )


def test_exit_one_under_blocking_is_unchecked_and_says_an_older_gate_may_be_the_cause( repo, tmp_path, monkeypatch ):
    monkeypatch.setattr( range_gate, "now", lambda: "t" )
    work   = _worktree( repo, tmp_path )
    runner = _runner_for( [ ( 1, "a\nb\n" ), ( 1, "a\nb\n" ), ( 2, "a\nb\n" ) ] )
    held   = range_gate.check_commit( repo[ "root" ], work, repo[ "two" ], runner, repo[ "one" ] )
    older  = range_gate.check_commit( repo[ "root" ], work, repo[ "one" ], runner, repo[ "one" ] )
    other  = range_gate.check_commit( repo[ "root" ], work, repo[ "two" ], runner, repo[ "one" ] )
    assert ( held.verdict, held.gate_rc ) == ( "unchecked", 1 ) and held.lines == [ "a", "b", range_gate.OLD_GATE_HINT, f"worktree {work}", "at t" ]
    assert older.verdict == "unchecked" and range_gate.OLD_GATE_HINT not in older.lines
    assert other.verdict == "unchecked" and range_gate.OLD_GATE_HINT not in other.lines
    assert "predates blocking" in range_gate.OLD_GATE_HINT and "epoch" in range_gate.OLD_GATE_HINT


def test_a_merge_base_failure_is_unchecked_and_runs_no_gate( repo, tmp_path ):
    runner = _runner_for( [] )
    result = range_gate.check_commit( repo[ "root" ], _worktree( repo, tmp_path ), repo[ "two" ], runner, EPOCH_SHA )
    assert result.verdict == "unchecked" and "merge-base" in result.lines[ 0 ] and runner.seen == []


def test_run_gate_passes_the_blocking_flag_only_when_asked( tmp_path ):
    pkg = tmp_path / "wt" / "src" / "cosa" / "repo" / "doc_lint"
    pkg.mkdir( parents=True )
    for folder in ( pkg.parent.parent, pkg.parent, pkg ): ( folder / "__init__.py" ).write_text( "" )
    ( pkg / "gate.py" ).write_text( "import sys\nprint( 'ARGV', sys.argv[ 1: ] )\n" )
    wt = str( tmp_path / "wt" )
    assert range_gate.run_gate( wt, True )[ 1 ].strip() == f"ARGV ['--blocking', '--repo-root', '{wt}']"
    assert range_gate.run_gate( wt, False )[ 1 ].strip() == f"ARGV ['--repo-root', '{wt}']"
    assert range_gate.run_gate( wt )[ 1 ].strip() == f"ARGV ['--repo-root', '{wt}']"


def test_the_report_names_the_epoch_and_counts_the_commits_held_to_it():
    results = [ range_gate.Result( "a" * 40, "one", "passed", 0, [ "note" ] ), range_gate.Result( "b" * 40, "two", "refused", 3, [ "why" ], True ) ]
    assert range_gate.epoch_line( None, results ) == "blocking epoch: none recorded in src/conf/doc-gate-blocking-epoch.txt, every commit was judged in warn mode"
    assert range_gate.epoch_line( None, results, False ) == range_gate.epoch_line( None, results ) + FROM_WORK
    assert range_gate.epoch_line( "e" * 40, results, False ) == range_gate.epoch_line( "e" * 40, results ) + FROM_WORK
    line = range_gate.epoch_line( "e" * 40, results )
    assert line == "blocking epoch eeeeeeeee: 1 commits held to blocking, 1 judged in warn mode"
    assert range_gate.report( "b", "h", results, line ).splitlines() == [
        "passed    aaaaaaaaa gate=0 one",
        "    note",
        "refused   bbbbbbbbb gate=3 two",
        "    why",
        line,
        "range b..h: 2 commits, 1 passed, 1 refused, 0 unchecked",
    ]


def _tool_stubs( folder, monkeypatch ):
    folder.mkdir()
    for name, var in ( ( "ruff", "LUPIN_RUFF" ), ( "markdownlint-cli2", "LUPIN_MARKDOWNLINT" ) ):
        ( folder / name ).write_text( "#!/bin/sh\nexit 0\n", encoding="utf-8" )
        os.chmod( folder / name, 0o755 )
        monkeypatch.setenv( var, str( folder / name ) )


@pytest.fixture
def gated( tmp_path, monkeypatch ):
    """Build a repository that tracks the real doc_lint package and holds two seeded commits."""
    _tool_stubs( tmp_path / "tools", monkeypatch )
    root = tmp_path / "gated"
    root.mkdir()
    _git( root, "init", "-q", "-b", "main" )
    shutil.copytree( DOC_LINT, root / "src" / "cosa" / "repo" / "doc_lint", ignore=shutil.ignore_patterns( "__pycache__" ) )
    for folder in ( root / "src" / "cosa", root / "src" / "cosa" / "repo" ): ( folder / "__init__.py" ).write_text( "" )
    _write( root, "src/conf/dm-tutor-lowercase-words.txt", "not\nnever\nthe\n" )
    _write( root, ".gitignore", "__pycache__/\n.claude/\n" )
    base = _commit( root, "base" )
    _write( root, "docs/older.md", SEEDED )
    older = _commit( root, "a finding made before the epoch" )
    _write( root, "docs/clean.md", "# Page\n\nThis is fine.\n" )
    epoch = _commit( root, "the commit that made the gate block" )
    _write( root, "docs/newer.md", SEEDED )
    newer = _commit( root, "a finding made after the epoch" )
    return { "root": str( root ), "base": base, "older": older, "epoch": epoch, "newer": newer }


def _range( gated, base="base" ):
    stream = io.StringIO()
    code   = range_gate.main( [ "--base", gated[ base ], "--head", gated[ "newer" ], "--repo-root", gated[ "root" ] ], out=stream )
    return code, stream.getvalue().splitlines()


def test_the_real_gate_refuses_the_seeded_commit_after_the_epoch_and_passes_the_one_before_it( gated ):
    _write( gated[ "root" ], range_gate.EPOCH_PATH, f"# recorded at landing\n{gated[ 'epoch' ]}\n" )
    code, lines = _range( gated )
    note = f"    predates the blocking epoch {gated[ 'epoch' ][ :9 ]}: judged in warn mode, findings on its staged lines were not enforced"
    assert code == 1
    assert lines[ 0 : 2 ] == [ f"passed    {gated[ 'older' ][ :9 ]} gate=0 a finding made before the epoch", note ]
    assert lines[ 2 : 4 ] == [ f"passed    {gated[ 'epoch' ][ :9 ]} gate=0 the commit that made the gate block", note ]
    assert lines[ 4 ] == f"refused   {gated[ 'newer' ][ :9 ]} gate=3 a finding made after the epoch"
    assert "    [doc-lint] REFUSED docs/newer.md:3: caps: ALL-CAPS word NOT" in lines
    assert lines[ -2 : ] == [ f"blocking epoch {gated[ 'epoch' ][ :9 ]}: 1 commits held to blocking, 2 judged in warn mode{FROM_WORK}", f"range {gated[ 'base' ]}..{gated[ 'newer' ]}: 3 commits, 2 passed, 1 refused, 0 unchecked" ]


@pytest.mark.parametrize( "text", [ None, "", "# the lander records the sha here\n" ] )
def test_an_absent_or_empty_epoch_holds_no_commit_to_blocking( gated, text ):
    if text is not None: _write( gated[ "root" ], range_gate.EPOCH_PATH, text )
    code, lines = _range( gated )
    assert code == 0
    assert lines[ -2 : ] == [ f"blocking epoch: none recorded in src/conf/doc-gate-blocking-epoch.txt, every commit was judged in warn mode{FROM_WORK}", f"range {gated[ 'base' ]}..{gated[ 'newer' ]}: 3 commits, 3 passed, 0 refused, 0 unchecked" ]
    assert not [ ln for ln in lines if "REFUSED" in ln or "predates" in ln ]


@pytest.mark.parametrize( "text,words", [ ( "0123456\n", "malformed" ), ( EPOCH_SHA + "\n", "names no commit" ) ] )
def test_a_malformed_epoch_is_an_error_exit_that_judges_no_commit( gated, text, words ):
    _write( gated[ "root" ], range_gate.EPOCH_PATH, text )
    code, lines = _range( gated )
    assert code == range_gate.EXIT_UNCHECKED == 2
    assert len( lines ) == 1 and words in lines[ 0 ] and "src/conf/doc-gate-blocking-epoch.txt" in lines[ 0 ] and "no commit was judged" in lines[ 0 ]
    assert os.listdir( os.path.join( gated[ "root" ], ".claude", "worktrees" ) ) == []


def test_a_tree_whose_gate_predates_blocking_is_unchecked_when_the_epoch_is_too_early_and_passes_in_warn_mode_otherwise( gated ):
    root = gated[ "root" ]
    shutil.copy( OLD_GATE, os.path.join( root, "src", "cosa", "repo", "doc_lint", "gate.py" ) )
    old_gate = _commit( root, "the gate as it was before blocking" )
    _write( root, "docs/last.md", SEEDED )
    last   = _commit( root, "a finding judged by the older gate" )
    stream = io.StringIO()
    args   = [ "--base", old_gate, "--head", last, "--repo-root", root ]
    assert range_gate.main( args, out=stream ) == 0 and "1 passed" in stream.getvalue()                   # no epoch: warn mode, the older gate exits 0
    _write( root, range_gate.EPOCH_PATH, gated[ "epoch" ] + "\n" )
    stream = io.StringIO()
    assert range_gate.main( args, out=stream ) == 2
    lines = stream.getvalue().splitlines()
    assert lines[ 0 ] == f"unchecked {last[ :9 ]} gate=1 a finding judged by the older gate" and f"    {range_gate.OLD_GATE_HINT}" in lines


# ---- the epoch of the range's head, and what an epoch may name ----------------------------------

def _record( gated, value ):
    """Commit the epoch file on top of the gated repository, so the head of the range tracks it."""
    _write( gated[ "root" ], range_gate.EPOCH_PATH, f"# recorded at landing\n{value}\n" if value else "# nothing recorded\n" )
    gated[ "record" ] = _commit( gated[ "root" ], "records the blocking epoch" )
    _write( gated[ "root" ], "docs/last.md", SEEDED )
    gated[ "newer" ] = _commit( gated[ "root" ], "a finding made after the record" )


def test_a_head_and_a_working_copy_that_record_the_same_epoch_judge_the_range_under_it( gated ):
    _record( gated, gated[ "epoch" ] )
    code, lines = _range( gated, base="epoch" )
    assert code == 1
    assert lines[ -2 ] == f"blocking epoch {gated[ 'epoch' ][ :9 ]}: 3 commits held to blocking, 0 judged in warn mode" and FROM_WORK not in lines[ -2 ]
    assert [ ln.split()[ 0 ] for ln in lines if ln[ :1 ] != " " ][ :3 ] == [ "refused", "passed", "refused" ]


@pytest.mark.parametrize( "working,shown", [ ( "# emptied\n", "no value" ), ( None, "no file" ), ( "OTHER", "OTHER" ) ] )
def test_a_working_copy_that_disagrees_with_the_head_of_the_range_judges_nothing( gated, working, shown ):
    _record( gated, gated[ "epoch" ] )
    path = os.path.join( gated[ "root" ], range_gate.EPOCH_PATH )
    if working is None: os.remove( path )
    else: _write( gated[ "root" ], range_gate.EPOCH_PATH, working.replace( "OTHER", gated[ "older" ] ) )
    code, lines = _range( gated, base="epoch" )
    assert code == range_gate.EXIT_UNCHECKED
    assert lines == [ f"the blocking epoch differs: the head of the range records {gated[ 'epoch' ]}, the working copy of src/conf/doc-gate-blocking-epoch.txt records {shown.replace( 'OTHER', gated[ 'older' ] )}; no commit was judged" ]


def test_a_head_that_records_no_value_disagrees_with_a_working_copy_that_records_one( gated ):
    _record( gated, None )
    _write( gated[ "root" ], range_gate.EPOCH_PATH, gated[ "epoch" ] + "\n" )
    code, lines = _range( gated, base="epoch" )
    assert code == range_gate.EXIT_UNCHECKED and len( lines ) == 1 and f"the head of the range records no value, the working copy of src/conf/doc-gate-blocking-epoch.txt records {gated[ 'epoch' ]}" in lines[ 0 ]


def test_a_malformed_epoch_at_the_head_of_the_range_judges_nothing( gated ):
    _record( gated, "0123456" )
    code, lines = _range( gated, base="epoch" )
    assert code == range_gate.EXIT_UNCHECKED and len( lines ) == 1 and "malformed" in lines[ 0 ]


def _object( root, kind ):
    if kind == "tree": return _git( root, "rev-parse", "HEAD^{tree}" )
    if kind == "blob": return _git( root, "rev-parse", "HEAD:docs/clean.md" )
    _git( root, "tag", "-a", "-m", "an annotated tag", "v1", "HEAD" )
    return _git( root, "rev-parse", "v1" )


@pytest.mark.parametrize( "kind", [ "tree", "blob", "tag" ] )
def test_an_epoch_that_names_an_object_which_is_not_a_commit_is_refused( gated, kind ):
    sha = _object( gated[ "root" ], kind )
    assert re.fullmatch( r"[0-9a-f]{40}", sha ) and _git( gated[ "root" ], "cat-file", "-t", sha ) == kind
    _write( gated[ "root" ], range_gate.EPOCH_PATH, sha + "\n" )
    with pytest.raises( range_gate.RangeRefused, match=f"names no commit in this repository.*it is a {kind}" ): range_gate.read_blocking_epoch( gated[ "root" ] )
    code, lines = _range( gated )
    assert code == range_gate.EXIT_UNCHECKED and len( lines ) == 1 and "names no commit" in lines[ 0 ]


def test_an_epoch_on_a_branch_the_range_never_took_holds_nobody_and_says_it_is_not_an_ancestor( gated ):
    root = gated[ "root" ]
    _git( root, "checkout", "-q", "-b", "apart", gated[ "base" ] )
    _write( root, "docs/apart.md", "# Page\n\nThis is fine.\n" )
    apart = _commit( root, "a commit on a branch the range never took" )
    _git( root, "checkout", "-q", "main" )
    _write( root, range_gate.EPOCH_PATH, apart + "\n" )
    assert range_gate.descends( root, gated[ "base" ], apart ) and not range_gate.descends( root, apart, gated[ "newer" ] )
    code, lines = _range( gated )
    note = f"    the blocking epoch {apart[ :9 ]} is not an ancestor of the head of this range: judged in warn mode, findings on its staged lines were not enforced"
    assert code == 0 and lines.count( note ) == 3 and not [ ln for ln in lines if "predates" in ln ]
    assert lines[ -2 ] == f"blocking epoch {apart[ :9 ]}: 0 commits held to blocking, 3 judged in warn mode{FROM_WORK}"


# ---- a merge, and a cherry-pick, replayed by the real gate ----------------------------------------

def _side_with_a_finding( gated ):
    """Commit a page with a finding on a branch that forks before the epoch; return to main."""
    root = gated[ "root" ]
    _git( root, "checkout", "-q", "-b", "side", gated[ "base" ] )
    _write( root, "docs/legacy.md", SEEDED )
    gated[ "side" ] = _commit( root, "a finding made on a branch that forked before the epoch" )
    _git( root, "checkout", "-q", "main" )


def _judge( gated, base, head ):
    _write( gated[ "root" ], range_gate.EPOCH_PATH, f"# recorded at landing\n{gated[ 'epoch' ]}\n" )
    stream = io.StringIO()
    code   = range_gate.main( [ "--base", base, "--head", head, "--repo-root", gated[ "root" ] ], out=stream )
    return code, stream.getvalue().splitlines()


def test_the_real_gate_passes_a_merge_whose_finding_came_in_unchanged_with_the_merged_commit( gated ):
    _side_with_a_finding( gated )
    root = gated[ "root" ]
    _git( root, "merge", "-q", "--no-ff", "-m", "merge side", "side" )
    merge = _git( root, "rev-parse", "HEAD" )
    code, lines = _judge( gated, gated[ "newer" ], merge )
    note = f"    merge commit: judged with {gated[ 'side' ][ :9 ]} as the incoming commit, so a line that came in unchanged with it was not enforced"
    assert code == 0 and lines[ -4 : -2 ] == [ f"passed    {merge[ :9 ]} gate=0 merge side", note ]
    assert lines[ -2 ] == f"blocking epoch {gated[ 'epoch' ][ :9 ]}: 1 commits held to blocking, 1 judged in warn mode{FROM_WORK}"
    assert lines[ -1 ].endswith( ": 2 commits, 2 passed, 0 refused, 0 unchecked" ) and not [ ln for ln in lines if "REFUSED" in ln ]


def test_the_real_gate_refuses_a_merge_for_a_finding_the_merge_itself_adds( gated ):
    _side_with_a_finding( gated )
    root = gated[ "root" ]
    _git( root, "merge", "-q", "--no-ff", "--no-commit", "side" )
    _write( root, "docs/own.md", SEEDED )
    merge = _commit( root, "merge side and add a page" )
    assert range_gate.other_parents( root, merge ) == [ gated[ "side" ] ]
    code, lines = _judge( gated, gated[ "newer" ], merge )
    assert code == 1 and [ ln.strip() for ln in lines if "REFUSED docs" in ln ] == [ "[doc-lint] REFUSED docs/own.md:3: caps: ALL-CAPS word NOT" ]
    assert f"refused   {merge[ :9 ]} gate=3 merge side and add a page" in lines


def test_a_concluded_cherry_pick_leaves_no_record_so_its_finding_is_refused_on_replay( gated ):
    _side_with_a_finding( gated )
    root = gated[ "root" ]
    _git( root, "cherry-pick", gated[ "side" ] )
    pick = _git( root, "rev-parse", "HEAD" )
    assert range_gate.other_parents( root, pick ) == [] and pick != gated[ "side" ]
    code, lines = _judge( gated, gated[ "newer" ], pick )
    assert code == 1 and [ ln.strip() for ln in lines if "REFUSED docs" in ln ] == [ "[doc-lint] REFUSED docs/legacy.md:3: caps: ALL-CAPS word NOT" ]
    assert not [ ln for ln in lines if "incoming commit" in ln ]


# ---- a range may not change the epoch it is judged under ------------------------------------------

def _change_the_epoch_file( gated, how ):
    """Commit a change to the epoch file above a base that records the epoch."""
    root = gated[ "root" ]
    path = os.path.join( root, range_gate.EPOCH_PATH )
    if how == "moved": _git( root, "mv", range_gate.EPOCH_PATH, "src/conf/elsewhere.txt" )
    elif how == "deleted": os.remove( path )
    elif how == "emptied": _write( root, range_gate.EPOCH_PATH, "# nothing recorded\n" )
    else: _write( root, range_gate.EPOCH_PATH, gated[ "older" ] + "\n" )
    return _commit( root, f"the epoch file is {how}" )


@pytest.mark.parametrize( "how,shown", [ ( "moved", "no file" ), ( "deleted", "no file" ), ( "emptied", "no value" ), ( "rewritten", "OLDER" ) ] )
def test_a_range_whose_head_changes_the_epoch_its_base_records_judges_nothing( gated, how, shown ):
    _record( gated, gated[ "epoch" ] )
    head   = _change_the_epoch_file( gated, how )
    stream = io.StringIO()
    code   = range_gate.main( [ "--base", gated[ "record" ], "--head", head, "--repo-root", gated[ "root" ] ], out=stream )
    assert code == range_gate.EXIT_UNCHECKED
    assert stream.getvalue().splitlines() == [
        f"the blocking epoch differs: the base of the range records {gated[ 'epoch' ]} in src/conf/doc-gate-blocking-epoch.txt, the head of the range records {shown.replace( 'OLDER', gated[ 'older' ] )}; "
        "a range is judged under the value its base records and cannot change it; no commit was judged"
    ]
    assert os.listdir( os.path.join( gated[ "root" ], ".claude", "worktrees" ) ) == []


def test_a_range_whose_base_and_head_record_the_same_epoch_is_judged_under_it( gated ):
    _record( gated, gated[ "epoch" ] )
    code, lines = _range( gated, base="record" )
    assert code == 1 and lines[ 0 ] == f"refused   {gated[ 'newer' ][ :9 ]} gate=3 a finding made after the record"
    assert lines[ -2 ] == f"blocking epoch {gated[ 'epoch' ][ :9 ]}: 1 commits held to blocking, 0 judged in warn mode"
    assert range_gate.resolve_blocking_epoch( gated[ "root" ], gated[ "record" ], gated[ "newer" ] ) == ( gated[ "epoch" ], True )


def test_the_range_that_lands_the_epoch_is_judged_under_the_value_its_head_records( gated ):
    _record( gated, gated[ "epoch" ] )
    root = gated[ "root" ]
    assert range_gate.committed_epoch_text( root, gated[ "epoch" ] ) is None and gated[ "epoch" ] in range_gate.committed_epoch_text( root, gated[ "record" ] )
    assert range_gate.resolve_blocking_epoch( root, gated[ "epoch" ], gated[ "newer" ] ) == ( gated[ "epoch" ], True )
    assert range_gate.resolve_blocking_epoch( root, gated[ "base" ], gated[ "epoch" ] ) == ( gated[ "epoch" ], False )      # neither end records it: the working copy does
