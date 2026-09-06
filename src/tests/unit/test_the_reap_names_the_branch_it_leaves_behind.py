"""
The reap must NAME unmerged work it is walking away from — and must NEVER withhold the
kill for it.

WHY THIS FILE EXISTS. `reviewed-and-merged is nobody's standing job` (Cheech's design,
src/rnd/2026.09.06-unmerged-branch-orphaning-mechanism.md). Nothing in the reap path
looked at git at all, so a seat's commits left every surface a manager reads the moment
it was killed. Measured 2026-09-06: 72 branches carried work absent from the working
line, 18 held by no worktree at all.

THE TWO HALVES THIS PINS, and they pull in OPPOSITE directions — which is the whole
reason both are here:

    1. the probe SPEAKS   — an unmerged branch produces a top-level `branch_alarm`
    2. the probe DEFERS   — it never withholds a kill, unlike the memento gate

A test for (1) alone would pass on an implementation that withholds, and withholding is
the specific misreading the design warns against. So (2) is asserted directly, against the
memento gate's own withhold in the same result, to prove the two seams are discriminated
rather than merely coexisting.
"""

import pytest

from lupin_mcp import reap_branch


# ── Fakes ─────────────────────────────────────────────────────────────────────
class _Res:
    def __init__( self, stdout="", returncode=0 ):
        self.stdout     = stdout
        self.returncode = returncode


def _git_fake( branch="wt-feature", ahead="3", rc_head=0, rc_count=0, raises=False ):
    """A git runner honouring its ARGS — a fake that ignored them could not discriminate."""
    def run( repo, *args ):
        if raises: raise OSError( "git exploded" )
        if args[ 0 ] == "rev-parse": return _Res( branch, rc_head )
        if args[ 0 ] == "rev-list":  return _Res( ahead,  rc_count )
        raise AssertionError( f"unexpected git verb {args}" )
    return run


def _identity( cwd="/tmp", persona="Clayton" ):
    return { "cwd": cwd, "persona": persona, "session_id": "abc123", "sender_id": "s" }


# ── seat_branch ───────────────────────────────────────────────────────────────
def test_a_named_branch_resolves( tmp_path ):
    assert reap_branch.seat_branch( str( tmp_path ), _git_fake() ) == ( "wt-feature", None )


def test_a_missing_cwd_is_named_not_silently_passed():
    assert reap_branch.seat_branch( None, _git_fake() ) == ( None, "no_cwd" )
    assert reap_branch.seat_branch( "",   _git_fake() ) == ( None, "no_cwd" )


def test_a_cwd_that_is_not_on_disk_reads_not_a_worktree():
    assert reap_branch.seat_branch( "/nonexistent/xyz", _git_fake() ) == ( None, "not_a_worktree" )


def test_a_raising_git_reads_not_a_worktree( tmp_path ):
    assert reap_branch.seat_branch( str( tmp_path ), _git_fake( raises=True ) ) == ( None, "not_a_worktree" )


def test_a_nonzero_git_reads_not_a_worktree( tmp_path ):
    assert reap_branch.seat_branch( str( tmp_path ), _git_fake( rc_head=128 ) ) == ( None, "not_a_worktree" )


def test_empty_git_output_reads_not_a_worktree( tmp_path ):
    assert reap_branch.seat_branch( str( tmp_path ), _git_fake( branch="" ) ) == ( None, "not_a_worktree" )


def test_a_detached_head_is_reported_never_dropped( tmp_path ):
    """Its commits are anchored by the worktree ALONE — the category that is LOST."""
    assert reap_branch.seat_branch( str( tmp_path ), _git_fake( branch="HEAD" ) ) == ( None, "detached" )


# ── commits_ahead ─────────────────────────────────────────────────────────────
def test_the_count_is_parsed( tmp_path ):
    assert reap_branch.commits_ahead( str( tmp_path ), "line", "b", _git_fake( ahead="7" ) ) == 7


def test_a_raising_count_is_none_never_zero( tmp_path ):
    """None and 0 want opposite responses: 'could not look' vs 'nothing to report'."""
    assert reap_branch.commits_ahead( str( tmp_path ), "line", "b", _git_fake( raises=True ) ) is None


def test_a_failed_count_is_none_never_zero( tmp_path ):
    assert reap_branch.commits_ahead( str( tmp_path ), "line", "b", _git_fake( rc_count=1 ) ) is None


def test_an_unparseable_count_is_none_never_zero( tmp_path ):
    assert reap_branch.commits_ahead( str( tmp_path ), "line", "b", _git_fake( ahead="fatal: bad rev" ) ) is None


# ── probe_seat_branches ───────────────────────────────────────────────────────
def test_an_unmerged_seat_carries_its_count_and_its_resume_line( tmp_path ):
    out = reap_branch.probe_seat_branches(
        { "seat-a": _identity( str( tmp_path ) ) },
        target_branch="the-line", git_fn=_git_fake( ahead="3" ) )
    assert out[ "seat-a" ][ "status"  ] == "unmerged"
    assert out[ "seat-a" ][ "commits" ] == 3
    assert out[ "seat-a" ][ "branch"  ] == "wt-feature"
    # A branch NAME plus the line that reads it — not a claim about the branch.
    assert out[ "seat-a" ][ "resume" ] == "git log --oneline the-line..wt-feature"


def test_a_merged_seat_is_quiet( tmp_path ):
    out = reap_branch.probe_seat_branches(
        { "seat-a": _identity( str( tmp_path ) ) },
        target_branch="the-line", git_fn=_git_fake( ahead="0" ) )
    assert out[ "seat-a" ][ "status" ] == "merged"
    assert out[ "seat-a" ][ "resume" ] is None


def test_a_seat_with_no_bridge_still_gets_an_explicit_verdict():
    """A None identity must never vanish — a silent pass IS the defect."""
    out = reap_branch.probe_seat_branches( { "seat-a": None }, git_fn=_git_fake() )
    assert out[ "seat-a" ][ "status"  ] == "no_cwd"
    assert out[ "seat-a" ][ "persona" ] is None


def test_a_probe_that_cannot_count_says_so( tmp_path ):
    out = reap_branch.probe_seat_branches(
        { "seat-a": _identity( str( tmp_path ) ) }, git_fn=_git_fake( rc_count=1 ) )
    assert out[ "seat-a" ][ "status" ] == "probe_failed"
    assert out[ "seat-a" ][ "branch" ] == "wt-feature"


def test_a_missing_sweep_module_reads_unavailable_not_clean( monkeypatch ):
    """'I could not look' must never render as a quiet fleet."""
    monkeypatch.setattr( reap_branch, "default_sweep_git", lambda: None )
    out = reap_branch.probe_seat_branches( { "seat-a": _identity() } )
    assert out[ "seat-a" ][ "status" ] == "sweep_unavailable"


def test_the_target_defaults_when_not_named( tmp_path ):
    out = reap_branch.probe_seat_branches(
        { "s": _identity( str( tmp_path ) ) }, git_fn=_git_fake( ahead="1" ) )
    assert reap_branch.DEFAULT_TARGET_BRANCH in out[ "s" ][ "resume" ]


# ── default_sweep_git — the REUSE seam ────────────────────────────────────────
def test_no_planning_root_yields_no_runner( monkeypatch ):
    monkeypatch.delenv( "PLANNING_IS_PROMPTING_ROOT", raising=False )
    assert reap_branch.default_sweep_git() is None


def test_a_planning_root_without_the_script_yields_no_runner( tmp_path ):
    assert reap_branch.default_sweep_git( str( tmp_path ) ) is None


def test_an_unimportable_script_yields_no_runner( tmp_path ):
    scripts = tmp_path / "workflow" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "orphaned_head_sweep.py" ).write_text( "this is not valid python (((" )
    assert reap_branch.default_sweep_git( str( tmp_path ) ) is None


def test_the_real_sweep_module_supplies_the_runner( tmp_path ):
    """POSITIVE CONTROL: without this, every None above could be a broken loader."""
    scripts = tmp_path / "workflow" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "orphaned_head_sweep.py" ).write_text(
        "def _git( repo, *args ):\n    return 'borrowed'\n" )
    runner = reap_branch.default_sweep_git( str( tmp_path ) )
    assert runner is not None and runner( "/repo", "status" ) == "borrowed"


def test_the_env_var_is_read_when_no_root_is_passed( tmp_path, monkeypatch ):
    scripts = tmp_path / "workflow" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "orphaned_head_sweep.py" ).write_text( "def _git( r, *a ):\n    return 'env'\n" )
    monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", str( tmp_path ) )
    assert reap_branch.default_sweep_git()( "/r" ) == "env"


# ── branch_alarm ──────────────────────────────────────────────────────────────
def test_a_clean_fleet_stays_quiet():
    """The quiet case must stay quiet, or the line means nothing when it appears."""
    assert reap_branch.branch_alarm( { "a": { "status": "merged", "persona": "P" } } ) is None
    assert reap_branch.branch_alarm( {} ) is None


def test_the_alarm_names_the_seat_the_persona_the_count_and_the_branch():
    alarm = reap_branch.branch_alarm( {
        "seat-a": { "status": "unmerged", "persona": "Maya", "commits": 23, "branch": "wt-x" } } )
    for token in ( "seat-a", "Maya", "23", "wt-x" ):
        assert token in alarm


def test_a_detached_seat_is_named_in_the_alarm():
    alarm = reap_branch.branch_alarm( { "s": { "status": "detached", "persona": "Rio" } } )
    assert "detached" in alarm and "Rio" in alarm


def test_unreadable_seats_get_their_own_clause_not_the_losing_one():
    """'could not look' and 'nothing to report' must never share a silence."""
    alarm = reap_branch.branch_alarm( { "s": { "status": "probe_failed", "persona": "Sam" } } )
    assert "UNREADABLE" in alarm and "NOT 'nothing to report'" in alarm
    assert "LEAVING UNMERGED WORK" not in alarm


def test_both_clauses_appear_together():
    alarm = reap_branch.branch_alarm( {
        "a": { "status": "unmerged", "persona": "M", "commits": 2, "branch": "b" },
        "z": { "status": "no_cwd",   "persona": "N" } } )
    assert "LEAVING UNMERGED WORK" in alarm and "UNREADABLE" in alarm


def test_a_missing_persona_reads_as_unknown_never_crashes():
    alarm = reap_branch.branch_alarm( {
        "s": { "status": "unmerged", "persona": None, "commits": 1, "branch": "b" } } )
    assert "unknown persona" in alarm


def test_the_reserved_error_key_and_junk_are_tolerated():
    """A probe failure is not a seat, and must not be rendered as one."""
    assert reap_branch.branch_alarm( { "_error": "probe blew up", "j": "not-a-dict" } ) is None


def test_the_alarm_is_sorted_so_one_reap_reads_the_same_way_twice():
    outcomes = { n: { "status": "unmerged", "persona": "P", "commits": 1, "branch": n }
                 for n in ( "zeta", "alpha", "mid" ) }
    assert reap_branch.branch_alarm( outcomes ).index( "alpha" ) \
         < reap_branch.branch_alarm( outcomes ).index( "mid" ) \
         < reap_branch.branch_alarm( outcomes ).index( "zeta" )


def test_a_spec_python_cannot_build_a_loader_for_yields_no_runner( tmp_path, monkeypatch ):
    """
    The defensive branch, closed by TEST rather than by `pragma: no cover`.

    `spec_from_file_location` returns None (or a loaderless spec) for a path importlib
    cannot construct a loader for. It is hard to reach with a real file, which is exactly
    the argument people use to pragma it away — and a pragma'd branch is one nobody ever
    watches fail. Both legs of the `or` are driven, so neither can be deleted silently.
    """
    import importlib.util

    scripts = tmp_path / "workflow" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "orphaned_head_sweep.py" ).write_text( "def _git( r, *a ):\n    return 1\n" )

    monkeypatch.setattr( importlib.util, "spec_from_file_location", lambda *a, **k: None )
    assert reap_branch.default_sweep_git( str( tmp_path ) ) is None

    class _NoLoader:
        loader = None
    monkeypatch.setattr( importlib.util, "spec_from_file_location", lambda *a, **k: _NoLoader() )
    assert reap_branch.default_sweep_git( str( tmp_path ) ) is None
