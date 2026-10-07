"""
The git_loc_delta include-merges flag counts a merge commit, checked on a real repository.

Store id 895261c6-4d98-4e61-a192-b51fb7b3b641. `git log --numstat` prints no rows for a merge
commit, so the flag dropped `--no-merges` and changed no count. A merge now counts what it
brought in over its first parent, and the README says so.

Every other test of this flag mocks subprocess.run, which is how a flag that changes nothing
stayed green. These tests build a real repository in a temp directory and run real git.
"""
import os
import subprocess

import pytest

from cosa.repo.git_loc_delta.analyzer import GitLogLocDeltaAnalyzer
from cosa.repo.git_loc_delta.git_log_parser import GitLogParser


def _git( repo, *args ):
    """
    Run one git command in the repo with a fixed identity and date.

    Requires:
        - repo is an existing directory

    Ensures:
        - returns the command's stdout
        - raises CalledProcessError when git exits non-zero
    """
    env = { **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_AUTHOR_DATE": "2026-05-20T12:00:00", "GIT_COMMITTER_DATE": "2026-05-20T12:00:00" }
    return subprocess.run( [ "git", *args ], cwd=repo, env=env, check=True, capture_output=True, text=True ).stdout


@pytest.fixture
def merged_repo( tmp_path ):
    """
    Build a repository with one real, non-fast-forward merge.

    Ensures:
        - base adds 3 lines to f.txt, main1 adds 1 line to f.txt, feat1 adds 5 lines to g.txt
        - the merge commit joins main and feat, so it brings g.txt in over its first parent
        - yields ( path, merge_sha )
    """
    _git( tmp_path, "init", "-q", "-b", "main" )
    ( tmp_path / "f.txt" ).write_text( "a\nb\nc\n" )
    _git( tmp_path, "add", "f.txt" ); _git( tmp_path, "commit", "-qm", "base" )
    _git( tmp_path, "checkout", "-q", "-b", "feat" )
    ( tmp_path / "g.txt" ).write_text( "a\nb\nc\nd\ne\n" )
    _git( tmp_path, "add", "g.txt" ); _git( tmp_path, "commit", "-qm", "feat1" )
    _git( tmp_path, "checkout", "-q", "main" )
    ( tmp_path / "f.txt" ).write_text( "a\nb\nc\nx\n" )
    _git( tmp_path, "commit", "-qam", "main1" )
    _git( tmp_path, "merge", "-q", "--no-ff", "feat", "-m", "merge" )
    return str( tmp_path ), _git( tmp_path, "rev-parse", "HEAD" ).strip()


def _rows( repo, **kw ):
    """Ensures: returns the parser's rows for the whole history as a list."""
    return list( GitLogParser( repo_path=repo, since="2026-01-01", until="2026-12-31", **kw ).iter_changes() )


def test_POSITIVE_CONTROL_the_fixture_has_a_real_merge_commit( merged_repo ):
    repo, merge_sha = merged_repo
    assert len( _git( repo, "rev-list", "--min-parents=2", "HEAD" ).split() ) == 1
    assert _git( repo, "rev-parse", "HEAD" ).strip() == merge_sha


def test_without_the_flag_a_merge_commit_adds_no_rows( merged_repo ):
    repo, merge_sha = merged_repo
    rows = _rows( repo )
    assert merge_sha not in { r[ "sha" ] for r in rows }
    assert sum( r[ "added" ] for r in rows ) == 3 + 1 + 5


def test_with_the_flag_a_merge_commit_counts_what_it_brought_in_over_its_first_parent( merged_repo ):
    repo, merge_sha = merged_repo
    merge_rows = [ r for r in _rows( repo, include_merges=True ) if r[ "sha" ] == merge_sha ]
    assert [ ( r[ "path" ], r[ "added" ], r[ "deleted" ] ) for r in merge_rows ] == [ ( "g.txt", 5, 0 ) ], "the flag must change a count"


def test_with_the_flag_the_other_commits_are_counted_once_each( merged_repo ):
    repo, merge_sha = merged_repo
    rows = _rows( repo, include_merges=True )
    assert sum( r[ "added" ] for r in rows if r[ "sha" ] != merge_sha ) == 3 + 1 + 5


def test_the_analyzer_totals_differ_with_and_without_the_flag( merged_repo ):
    repo, _ = merged_repo
    totals = {}
    for flag in ( False, True ):
        result = GitLogLocDeltaAnalyzer( repo_path=repo, mode="explicit", since="2026-01-01", until="2026-12-31", include_merges=flag ).analyze()
        totals[ flag ] = result[ "summary" ][ "total_added" ]
    assert totals[ True ] == totals[ False ] + 5
