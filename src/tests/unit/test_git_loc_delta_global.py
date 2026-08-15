"""
Unit tests for the two code-half fixes on cosa.repo.run_git_loc_delta_global
(row d5bfe470):

  1. EMIT the largest single commit alongside the total, ALWAYS — so a squash-merge
     that folds already-counted work into one dated commit is visible as
     concentration, with no threshold and no shape-detection (remedy c; remedy b
     was withdrawn for keying on commit SHAPE).
  2. TIME-NORMALIZE the aggregator's own --since/--until — git's approxidate
     resolves a bare YYYY-MM-DD to that date AT THE CURRENT WALL-CLOCK TIME, so
     --since=D --until=D is an empty interval by construction and a direct CLI
     caller (bypassing the slash wrapper) silently loses the day's work.

Each test is written to BITE: deleting the fix under test turns the assertion red.
The normalization tests bite deterministically; the single-day end-to-end test bites
for every realistic run hour (its commit sits one second before end-of-day, which a
bare --until=D — resolved to D at the current wall-clock time — excludes).

Author: Arnold 🪨 (session 71e314ac, 2026-08-15)
"""

import json
import os
import subprocess
import tempfile

import pytest

from cosa.repo.run_git_loc_delta_global import (
    _analyze_repos,
    _build_aggregated_daily,
    _build_summary,
    _commit_subject,
    _format_console,
    _largest_commit_for_repo,
    _normalize_window_bounds,
    main,
)


# --- Real-git-repo fixtures -------------------------------------------------

def _git( repo: str, *cmd: str, commit_date: str = None ) -> None:
    """Run a git subcommand in `repo`, optionally pinning author+committer date."""
    env = { **os.environ }
    if commit_date is not None:
        env[ "GIT_AUTHOR_DATE"    ] = commit_date
        env[ "GIT_COMMITTER_DATE" ] = commit_date
    subprocess.run( [ "git", *cmd ], cwd=repo, check=True, capture_output=True, env=env )


def _init_repo( workdir: str, name: str ) -> str:
    """Create a fresh git repo `name` under `workdir` with a stable identity."""
    repo = os.path.join( workdir, name )
    os.makedirs( repo )
    _git( repo, "init", "-q", "-b", "main" )
    _git( repo, "config", "user.email", "smoke@test.local" )
    _git( repo, "config", "user.name",  "Smoke Test" )
    return repo


def _commit( repo: str, files: dict, message: str, commit_date: str ) -> None:
    """Write `files` (rel path -> content) and commit them at `commit_date`."""
    for rel, content in files.items():
        full = os.path.join( repo, rel )
        os.makedirs( os.path.dirname( full ), exist_ok=True )
        with open( full, "w" ) as f:
            f.write( content )
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-q", "-m", message, commit_date=commit_date )


def _lines( n: int, tag: str ) -> str:
    """Deterministic n-line file body."""
    return "\n".join( f"{tag}{i}" for i in range( n ) ) + "\n"


@pytest.fixture
def workdir():
    """A tempdir cleaned up after the test."""
    d = tempfile.mkdtemp( prefix="git_loc_delta_global_ut_" )
    yield d
    import shutil
    shutil.rmtree( d, ignore_errors=True )


# ---------------------------------------------------------------------------
# Item 2 — time-normalization of the aggregator's own --since/--until
# ---------------------------------------------------------------------------

class TestNormalizeWindowBounds:
    """The deterministic bite for the bare-date / empty-single-day defect."""

    def test_bare_same_day_window_is_not_an_empty_instant( self ):
        # The heart of the defect: --since=D --until=D must span the WHOLE day,
        # not collapse to a single wall-clock instant. Deleting the fix (making
        # the helper a passthrough) returns ("D", "D") and turns this red.
        since, until = _normalize_window_bounds( "2026-08-03", "2026-08-03" )
        assert since == "2026-08-03 00:00:00"
        assert until == "2026-08-03 23:59:59"
        assert since < until, "a same-day window must be a real interval, not empty"

    def test_none_passes_through( self ):
        assert _normalize_window_bounds( None, None ) == ( None, None )

    def test_already_timed_value_is_untouched( self ):
        # A value that already carries a time is unambiguous — never second-guess it.
        since, until = _normalize_window_bounds( "2026-08-03 06:30:00", "2026-08-03 18:00:00" )
        assert since == "2026-08-03 06:30:00"
        assert until == "2026-08-03 18:00:00"

    def test_relative_expression_is_untouched( self ):
        since, until = _normalize_window_bounds( "1 day ago", "now" )
        assert since == "1 day ago"
        assert until == "now"

    def test_one_bound_bare_one_bound_none( self ):
        since, until = _normalize_window_bounds( "2026-08-03", None )
        assert since == "2026-08-03 00:00:00"
        assert until is None


class TestSingleDayWindowEndToEnd:
    """The realistic bite: a bare single-day window must still count the day's work."""

    def test_bare_single_day_window_counts_late_commit( self, workdir ):
        # Commit one second before end-of-day. A bare --until=D resolves to D at
        # the current wall-clock time, which excludes this commit for every run
        # hour but the last second of the day — so WITHOUT the end-of-day pin the
        # window reports ZERO. WITH it, the day's work appears.
        repo = _init_repo( workdir, "late_day" )
        _commit( repo, { "src/a.py": _lines( 12, "x" ) }, "late in the day",
                 commit_date="2026-07-10T23:59:58" )

        out_json  = os.path.join( workdir, "out.json" )
        exit_code = main( argv=[
            "--repos", repo,
            "--since", "2026-07-10", "--until", "2026-07-10",
            "--output", "json", "--save-output", out_json,
        ] )
        assert exit_code == 0

        with open( out_json ) as f:
            parsed = json.load( f )
        assert parsed[ "summary" ][ "total_commits" ] == 1, \
            "the single-day window dropped the day's commit — bare-date defect is back"
        assert parsed[ "summary" ][ "total_added" ] == 12


# ---------------------------------------------------------------------------
# Item 1 — emit the largest single commit, always
# ---------------------------------------------------------------------------

class TestLargestCommit:

    def test_largest_commit_surfaces_concentration( self, workdir ):
        # One dominant commit (the squash-shaped case) among several tiny ones.
        repo = _init_repo( workdir, "concentrated" )
        _commit( repo, { "tiny/a.py": _lines( 2, "a" ) }, "small 1", "2026-07-10T09:00:00" )
        _commit( repo, { "tiny/b.py": _lines( 2, "b" ) }, "small 2", "2026-07-10T10:00:00" )
        _commit( repo, { "huge/big.py": _lines( 500, "z" ) }, "the squash", "2026-07-10T11:00:00" )

        df, commits, cov, empty, skipped, largest = _analyze_repos(
            [ repo ], "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        assert largest is not None
        assert largest[ "added" ] == 500
        assert largest[ "files_touched" ] == 1

        summary = _build_summary( df, commits )
        churn   = largest[ "added" ] + largest[ "deleted" ]
        win     = summary[ "total_added" ] + summary[ "total_deleted" ]
        assert churn / win > 0.9, "a 500-vs-4 line commit is >90% of window churn"

    def test_largest_commit_present_without_concentration( self, workdir ):
        # No dominant commit — three equal ones. The line must STILL appear
        # (remedy c is unconditional); its share is ~1/3, not ~100%.
        repo = _init_repo( workdir, "uniform" )
        for i in range( 3 ):
            _commit( repo, { f"src/f{i}.py": _lines( 10, f"u{i}" ) }, f"equal {i}",
                     commit_date=f"2026-07-10T0{i+1}:00:00" )

        df, commits, cov, empty, skipped, largest = _analyze_repos(
            [ repo ], "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        assert largest is not None, "largest-commit must be reported even with no concentration"
        assert largest[ "added" ] == 10

        summary = _build_summary( df, commits )
        churn   = largest[ "added" ] + largest[ "deleted" ]
        win     = summary[ "total_added" ] + summary[ "total_deleted" ]
        assert 0.30 <= churn / win <= 0.40, "one of three equal commits is ~1/3 of churn"

    def test_largest_commit_is_global_max_across_repos( self, workdir ):
        # The winner is chosen across ALL repos, not per-repo. Big is FIRST in the
        # roster so the later (smaller) repo exercises the "does not beat" path.
        big = _init_repo( workdir, "big_repo" )
        _commit( big, { "b.py": _lines( 300, "b" ) }, "big repo", "2026-07-10T09:00:00" )
        small = _init_repo( workdir, "small_repo" )
        _commit( small, { "s.py": _lines( 20, "s" ) }, "small repo", "2026-07-10T09:00:00" )

        _, _, _, _, _, largest = _analyze_repos(
            [ big, small ], "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        assert largest[ "repo" ] == "big_repo"
        assert largest[ "added" ] == 300

    def test_largest_commit_for_repo_sums_multi_file_commit( self, workdir ):
        # One commit touching two files: the per-SHA record is revisited, and its
        # added lines sum across both files.
        repo = _init_repo( workdir, "multifile" )
        _commit(
            repo,
            { "src/a.py": _lines( 30, "a" ), "docs/b.md": _lines( 12, "b" ) },
            "two files, one commit", "2026-07-10T09:00:00",
        )
        largest = _largest_commit_for_repo(
            repo, "multifile", "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, debug=False, verbose=False,
        )
        assert largest[ "added" ] == 42
        assert largest[ "files_touched" ] == 2

    def test_largest_commit_for_repo_returns_none_for_empty_window( self, workdir ):
        repo = _init_repo( workdir, "outofwindow" )
        _commit( repo, { "a.py": _lines( 5, "a" ) }, "old", "2026-07-10T09:00:00" )
        largest = _largest_commit_for_repo(
            repo, "outofwindow", "2099-01-01", "2099-01-02",
            all_branches=True, include_merges=False, debug=False, verbose=False,
        )
        assert largest is None

    def test_empty_window_yields_no_largest_commit( self, workdir ):
        repo = _init_repo( workdir, "quiet" )
        _commit( repo, { "q.py": _lines( 5, "q" ) }, "old work", "2026-07-10T09:00:00" )

        _, _, _, _, _, largest = _analyze_repos(
            [ repo ], "2099-01-01", "2099-01-02",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        assert largest is None

    def test_largest_commit_line_rendered_in_console( self, workdir ):
        repo = _init_repo( workdir, "rendered" )
        _commit( repo, { "big/x.py": _lines( 400, "z" ) }, "Wip squash (#20)", "2026-07-10T11:00:00" )
        _commit( repo, { "tiny/y.py": _lines( 3, "y" ) }, "small", "2026-07-10T12:00:00" )

        df, commits, cov, empty, skipped, largest = _analyze_repos(
            [ repo ], "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        summary = _build_summary( df, commits )
        summary[ "largest_commit" ] = { **largest, "subject": "Wip squash (#20)" }
        daily   = _build_aggregated_daily( df, commits )
        text    = _format_console( daily, summary, "2026-07-09", "2026-07-12" )

        assert "Largest single commit:" in text
        assert "Wip squash (#20)" in text
        assert "% of window churn" in text

    def test_end_to_end_json_carries_largest_commit_with_pct( self, workdir ):
        repo = _init_repo( workdir, "e2e" )
        _commit( repo, { "big/x.py": _lines( 500, "z" ) }, "the squash (#20)", "2026-07-10T11:00:00" )
        _commit( repo, { "tiny/y.py": _lines( 4, "y" ) }, "tiny", "2026-07-10T12:00:00" )

        out_json  = os.path.join( workdir, "out.json" )
        exit_code = main( argv=[
            "--repos", repo,
            "--since", "2026-07-09", "--until", "2026-07-12",
            "--output", "json", "--save-output", out_json,
        ] )
        assert exit_code == 0

        with open( out_json ) as f:
            parsed = json.load( f )
        lc = parsed[ "summary" ][ "largest_commit" ]
        assert lc[ "added" ] == 500
        assert lc[ "subject" ] == "the squash (#20)"
        assert lc[ "pct_of_window_churn" ] > 90.0
        assert "repo_path" not in lc, "internal plumbing must not reach the payload"


class TestCommitSubject:

    def test_subject_returned_for_real_commit( self, workdir ):
        repo = _init_repo( workdir, "subj" )
        _commit( repo, { "a.py": _lines( 3, "a" ) }, "a memorable subject", "2026-07-10T09:00:00" )
        sha = subprocess.run(
            [ "git", "rev-parse", "HEAD" ], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert _commit_subject( repo, sha ) == "a memorable subject"

    def test_subject_empty_on_bogus_sha( self, workdir ):
        repo = _init_repo( workdir, "subj2" )
        _commit( repo, { "a.py": _lines( 3, "a" ) }, "real", "2026-07-10T09:00:00" )
        assert _commit_subject( repo, "0000000000000000000000000000000000000000" ) == ""

    def test_subject_empty_when_git_cannot_run( self ):
        # A nonexistent cwd makes subprocess.run raise (FileNotFoundError) — the
        # best-effort path degrades to "" rather than crashing the report.
        assert _commit_subject( "/nonexistent/path/xyz-does-not-exist", "deadbeef" ) == ""


class TestRenderingEdgeCases:

    def test_console_without_largest_commit_omits_the_line( self, workdir ):
        # remedy (c) renders WHEN there is a largest commit; a summary without one
        # (e.g. built by a caller that never set it) renders cleanly without it.
        repo = _init_repo( workdir, "plain" )
        _commit( repo, { "a.py": _lines( 5, "a" ) }, "work", "2026-07-10T09:00:00" )
        df, commits, _, _, _, _ = _analyze_repos(
            [ repo ], "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        summary = _build_summary( df, commits )          # no largest_commit key
        daily   = _build_aggregated_daily( df, commits )
        text    = _format_console( daily, summary, "2026-07-09", "2026-07-12" )
        assert "Largest single commit:" not in text
        assert "Total:" in text

    def test_console_largest_commit_without_subject( self, workdir ):
        repo = _init_repo( workdir, "nosubj" )
        _commit( repo, { "a.py": _lines( 40, "a" ) }, "x", "2026-07-10T09:00:00" )
        df, commits, _, _, _, largest = _analyze_repos(
            [ repo ], "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        summary = _build_summary( df, commits )
        summary[ "largest_commit" ] = { **largest, "subject": "" }   # subject unavailable
        daily = _build_aggregated_daily( df, commits )
        text  = _format_console( daily, summary, "2026-07-09", "2026-07-12" )
        assert "Largest single commit:" in text
        assert '"' not in text.split( "Largest single commit:" )[ 1 ].split( "\n" )[ 0 ]

    def test_json_without_largest_commit( self, workdir ):
        from cosa.repo.run_git_loc_delta_global import _format_json
        repo = _init_repo( workdir, "jplain" )
        _commit( repo, { "a.py": _lines( 5, "a" ) }, "work", "2026-07-10T09:00:00" )
        df, commits, _, _, _, _ = _analyze_repos(
            [ repo ], "2026-07-09", "2026-07-12",
            all_branches=True, include_merges=False, verbose=False, debug=False,
        )
        summary = _build_summary( df, commits )          # no largest_commit key
        daily   = _build_aggregated_daily( df, commits )
        parsed  = json.loads( _format_json( daily, summary, "2026-07-09", "2026-07-12" ) )
        assert "largest_commit" not in parsed[ "summary" ]

    def test_main_empty_window_reports_no_commits( self, workdir ):
        repo = _init_repo( workdir, "quiet2" )
        _commit( repo, { "a.py": _lines( 5, "a" ) }, "old", "2026-07-10T09:00:00" )
        out_txt   = os.path.join( workdir, "out.txt" )
        exit_code = main( argv=[
            "--repos", repo,
            "--since", "2099-01-01", "--until", "2099-01-02",
            "--save-output", out_txt,
        ] )
        assert exit_code == 0
        with open( out_txt ) as f:
            text = f.read()
        assert "No commits in range" in text
        assert "Largest single commit:" not in text


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
