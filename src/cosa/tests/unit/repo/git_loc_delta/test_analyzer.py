"""
Unit tests for cosa.repo.git_loc_delta.analyzer.GitLogLocDeltaAnalyzer.

Real public surface (verified via live introspection, not a rendered Read):
    GitLogLocDeltaAnalyzer.__init__(...), ._resolve_range(), .analyze() -> dict
    (quick_smoke_test / __main__ are config-excluded from the denominator.)

The orchestrator wires GitLogParser → DailyAggregator. GitLogParser is mocked
(its own unit tests cover it; Cheech's git_log_parser batch); the real
DailyAggregator runs so aggregation is exercised end-to-end. subprocess.run is
mocked for the branch-mode current-branch resolution.

CROSS-REPO: analyze() forwards a repo_path OUTSIDE the project tree to the
parser verbatim (the resolution-bug class).

Authored by Sam 🎙️ for the CoSA 100% coverage campaign (git_loc_delta group).
Reviewed by Mr. Radio (no self-audit).
"""
import subprocess
from datetime import date as _date
from unittest.mock import patch, MagicMock

import pytest

from cosa.repo.git_loc_delta.analyzer import GitLogLocDeltaAnalyzer
from cosa.repo.git_loc_delta.exceptions import DateRangeError, GitCommandError

_EXTERNAL = "/tmp/__sam_external_repo__"


def _change( date, sha, path, added, deleted ):
    return { "date": date, "sha": sha, "author": "rick@x", "path": path,
             "added": added, "deleted": deleted }


class TestInit:
    """__init__ mode validation + attribute capture."""

    def test_invalid_mode_raises( self ):
        with pytest.raises( ValueError ):
            GitLogLocDeltaAnalyzer( mode="weekly" )

    def test_valid_construction_captures_flags( self ):
        a = GitLogLocDeltaAnalyzer(
            repo_path=_EXTERNAL, mode="branch", branch="wip", base="develop",
            repo_name="cosa", debug=True,
        )
        assert a.repo_path == _EXTERNAL
        assert a.mode == "branch"
        assert a.base == "develop"
        assert a.repo_name == "cosa"


class TestResolveRangeExplicit:
    """_resolve_range — explicit mode."""

    def test_returns_since_until_no_revrange( self ):
        a = GitLogLocDeltaAnalyzer( mode="explicit", since="2026-05-01", until="2026-05-31" )
        assert a._resolve_range() == ( "2026-05-01", "2026-05-31", None, None )

    def test_since_after_until_raises( self ):
        a = GitLogLocDeltaAnalyzer( mode="explicit", since="2026-05-31", until="2026-05-01" )
        with pytest.raises( DateRangeError ):
            a._resolve_range()

    def test_since_only_does_not_raise( self ):
        a = GitLogLocDeltaAnalyzer( mode="explicit", since="2026-05-01" )
        assert a._resolve_range() == ( "2026-05-01", None, None, None )


class TestResolveRangeToday:
    """_resolve_range — today mode."""

    def test_today_resolves_to_today_since( self ):
        a = GitLogLocDeltaAnalyzer( mode="today" )
        since, until, rev_range, branch = a._resolve_range()
        assert since == _date.today().isoformat()
        assert until is None and rev_range is None and branch is None


class TestResolveRangeBranch:
    """_resolve_range — branch mode incl. git current-branch resolution."""

    def test_explicit_branch_builds_rev_range( self ):
        a = GitLogLocDeltaAnalyzer( mode="branch", branch="wip-x", base="main" )
        assert a._resolve_range() == ( None, None, "main..wip-x", "wip-x" )

    def test_branch_equal_base_raises_empty_range( self ):
        a = GitLogLocDeltaAnalyzer( mode="branch", branch="main", base="main" )
        with pytest.raises( DateRangeError ):
            a._resolve_range()

    def test_current_branch_resolved_via_git( self ):
        a = GitLogLocDeltaAnalyzer( mode="branch", branch=None, base="main", repo_path=_EXTERNAL )
        fake = MagicMock( returncode=0, stdout="feature-y\n", stderr="" )
        with patch( "cosa.repo.git_loc_delta.analyzer.subprocess.run", return_value=fake ) as run:
            result = a._resolve_range()
        assert result == ( None, None, "main..feature-y", "feature-y" )
        assert run.call_args.kwargs[ "cwd" ] == _EXTERNAL   # cross-repo wiring

    def test_git_nonzero_returncode_raises( self ):
        a = GitLogLocDeltaAnalyzer( mode="branch", branch=None )
        fake = MagicMock( returncode=128, stdout="", stderr="fatal" )
        with patch( "cosa.repo.git_loc_delta.analyzer.subprocess.run", return_value=fake ):
            with pytest.raises( GitCommandError ):
                a._resolve_range()

    def test_git_timeout_raises( self ):
        a = GitLogLocDeltaAnalyzer( mode="branch", branch=None )
        with patch(
            "cosa.repo.git_loc_delta.analyzer.subprocess.run",
            side_effect=subprocess.TimeoutExpired( cmd="git", timeout=10 ),
        ):
            with pytest.raises( GitCommandError ):
                a._resolve_range()


class TestAnalyze:
    """analyze() — parse→aggregate→result dict, with real DailyAggregator."""

    def _patch_parser( self, changes ):
        """Patch GitLogParser to an instance whose iter_changes yields `changes`."""
        parser = MagicMock()
        parser.iter_changes.return_value = iter( changes )
        return patch( "cosa.repo.git_loc_delta.analyzer.GitLogParser", return_value=parser ), parser

    def test_result_dict_shape_and_aggregation( self ):
        changes = [
            _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ),
            _change( "2026-05-16", "sha2", "docs/r.md", 5, 1 ),
        ]
        a = GitLogLocDeltaAnalyzer(
            repo_path=_EXTERNAL, mode="explicit", since="2026-05-16", repo_name="cosa",
        )
        ctx, _ = self._patch_parser( changes )
        with ctx:
            result = a.analyze()
        assert set( result.keys() ) == {
            "since", "until", "branch", "rev_range", "repo_path", "repo_name",
            "summary", "daily", "by_type",
        }
        assert result[ "since" ] == "2026-05-16"
        assert result[ "repo_path" ] == _EXTERNAL
        assert result[ "repo_name" ] == "cosa"
        # Real aggregation: 2 distinct files, 2 commits, 15 added / 3 deleted.
        assert result[ "summary" ][ "total_added" ] == 15
        assert result[ "summary" ][ "total_deleted" ] == 3
        assert result[ "summary" ][ "total_commits" ] == 2
        assert "2026-05-16" in result[ "daily" ]

    def test_cross_repo_path_forwarded_to_parser( self ):
        a = GitLogLocDeltaAnalyzer( repo_path=_EXTERNAL, mode="explicit", since="2026-05-16" )
        ctx, _ = self._patch_parser( [] )
        with ctx as mock_parser_cls:
            a.analyze()
        # CROSS-REPO: the OUTSIDE-tree repo_path is handed verbatim to GitLogParser.
        assert mock_parser_cls.call_args.kwargs[ "repo_path" ] == _EXTERNAL

    def test_debug_prints_resolution( self, capsys ):
        a = GitLogLocDeltaAnalyzer( mode="explicit", since="2026-05-16", debug=True )
        ctx, _ = self._patch_parser( [] )
        with ctx:
            a.analyze()
        assert "GitLogLocDeltaAnalyzer" in capsys.readouterr().out
