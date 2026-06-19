"""
Unit tests for cosa.repo.branch_analyzer.analyzer.

Tests BranchChangeAnalyzer, the orchestrator that wires ConfigLoader,
FileTypeClassifier, LineClassifier, GitDiffParser, StatisticsCollector, and
ReportFormatter into the end-to-end analysis workflow. GitDiffParser is mocked
so the orchestrator runs fully offline (no real git repo / subprocess); all
other collaborators are the real classes, so this also integration-exercises
the diff-line → classify → aggregate pipeline with synthetic DiffLine inputs.

Harvested from analyzer.quick_smoke_test (the __main__ block) — its intent is
preserved here with REAL assertions. Note: the legacy smoke test asserted
'# Code Changes Analysis' for markdown, which is STALE — the formatter emits
'# Branch Comparison Analysis'; this suite asserts the correct header.

Part of the CoSA 100% coverage campaign (repo module group).
"""
from unittest import mock

import pytest

from cosa.repo.branch_analyzer.analyzer import BranchChangeAnalyzer
from cosa.repo.branch_analyzer.git_diff_parser import DiffLine
from cosa.repo.branch_analyzer.exceptions import BranchAnalyzerError


@pytest.fixture
def patched_git():
    """
    Patch the GitDiffParser used by the analyzer with a MagicMock.

    Ensures:
        - get_branch_name(ref) is an identity passthrough (resolves to itself)
        - get_diff() returns whatever the test assigns to .get_diff.return_value
        - no real git subprocess runs
    Yields the mock *instance* the analyzer will hold as self.git_parser.
    """
    with mock.patch( "cosa.repo.branch_analyzer.analyzer.GitDiffParser" ) as ParserCls:
        instance = ParserCls.return_value
        instance.get_branch_name.side_effect = lambda ref: ref
        instance.get_diff.return_value = []
        yield instance


def _diff( content, operation, file_path, line_number=1 ):
    """Build a DiffLine for synthetic diff input."""
    return DiffLine( content=content, operation=operation, file_path=file_path, line_number=line_number )


class TestInit:
    """Construction loads config, wires components, resolves branch names."""

    def test_defaults_load_config_and_resolve_branches( self, patched_git ):
        """
        Ensures:
            - repo_path defaults to '.'
            - config is loaded with the git section present
            - base/head default to the config's branch values
            - resolved branch names come from the (mocked) git parser
        """
        analyzer = BranchChangeAnalyzer()
        assert analyzer.repo_path == "."
        assert "git" in analyzer.config
        assert analyzer.base_branch == analyzer.config[ "git" ][ "default_base_branch" ]
        assert analyzer.head_branch == analyzer.config[ "git" ][ "default_head_branch" ]
        # identity passthrough from the mocked resolver
        assert analyzer.base_branch_resolved == analyzer.base_branch
        assert analyzer.head_branch_resolved == analyzer.head_branch

    def test_branch_and_repo_overrides_applied( self, patched_git ):
        """
        Ensures:
            - explicit base_branch/head_branch override the config defaults
            - explicit repo_path is stored
        """
        analyzer = BranchChangeAnalyzer(
            base_branch="develop", head_branch="feature", repo_path="/some/repo"
        )
        assert analyzer.base_branch == "develop"
        assert analyzer.head_branch == "feature"
        assert analyzer.repo_path == "/some/repo"
        assert analyzer.config[ "git" ][ "default_base_branch" ] == "develop"
        assert analyzer.config[ "git" ][ "default_head_branch" ] == "feature"

    def test_debug_init_logs( self, patched_git, capsys ):
        """Ensures: debug=True emits the init/resolved banner lines."""
        BranchChangeAnalyzer( debug=True )
        out = capsys.readouterr().out
        assert "Initialized" in out
        assert "Resolved" in out

    def test_config_load_failure_wrapped_in_branch_analyzer_error( self, patched_git ):
        """
        Ensures:
            - a ConfigLoader failure is wrapped as BranchAnalyzerError
              (the __init__ try/except branch)
        """
        with mock.patch(
            "cosa.repo.branch_analyzer.analyzer.ConfigLoader",
            side_effect=RuntimeError( "cfg boom" ),
        ):
            with pytest.raises( BranchAnalyzerError ) as exc:
                BranchChangeAnalyzer()
        assert "Failed to load configuration" in str( exc.value )


class TestAnalyze:
    """analyze() pulls the diff, processes lines, returns a summary."""

    # Shared synthetic diff: 2 python adds (code+comment), 1 python remove,
    # a meta + context line (skipped), an orphan add with no file_path
    # (skipped), and 1 markdown add. Total real adds = 3 (2 py + 1 md).
    _MIXED_DIFF = [
        ( "+x = 42", "add", "a.py" ),          # python code
        ( "+# note", "add", "a.py" ),          # python comment
        ( "-old", "remove", "a.py" ),          # python removal
        ( "diff --git ...", "meta", "a.py" ),  # skipped (meta)
        ( " ctx", "context", "a.py" ),         # skipped (context)
        ( "+orphan", "add", None ),            # skipped (no file_path)
        ( "+doc text", "add", "README.md" ),   # markdown add (no lang breakdown)
    ]

    def test_processes_mixed_diff_lines( self, patched_git ):
        """
        Ensures:
            - per-file-type 'add' counts are correct (python 2, markdown 1)
            - 'remove' lines count as removals
            - meta and context lines are skipped
            - lines with no file_path are skipped
            - files_changed tracks both touched files
            - python is language-broken-down; markdown is not
        """
        patched_git.get_diff.return_value = [ _diff( *t ) for t in self._MIXED_DIFF ]
        stats = BranchChangeAnalyzer().analyze()

        # Per-file-type breakdown is correct (this is the trustworthy total).
        by_type = { row[ "file_type" ]: row for row in stats[ "by_file_type" ] }
        assert by_type[ "python" ][ "added" ] == 2
        assert by_type[ "markdown" ][ "added" ] == 1
        assert by_type[ "python" ][ "removed" ] == 1

        assert stats[ "overall" ][ "total_removed" ] == 1
        assert set( stats[ "files_changed_set" ] ) == { "a.py", "README.md" }

        py = stats[ "language_details" ][ "python" ]
        assert py[ "code" ] == 1
        assert py[ "comment" ] == 1
        assert py[ "removed" ] == 1
        assert "markdown" not in stats[ "language_details" ]

    def test_overall_total_added_counts_all_file_types( self, patched_git ):
        """
        PROD BUG FIXED (2026-05-31): the per-language loop in
        statistics_collector.get_summary used to reassign a bare `total_added`,
        clobbering the overall sum-across-all-file-types. Renamed the loop-local
        to `lang_total_added`; overall.total_added is now correct.

        Ensures:
            - overall.total_added equals the sum of adds across ALL file types
              (2 python + 1 markdown == 3)
        """
        patched_git.get_diff.return_value = [ _diff( *t ) for t in self._MIXED_DIFF ]
        stats = BranchChangeAnalyzer().analyze()
        assert stats[ "overall" ][ "total_added" ] == 3

    def test_add_without_plus_prefix_is_classified_verbatim( self, patched_git ):
        """
        Ensures:
            - an 'add' line whose content does NOT start with '+' is classified
              using the content as-is (the prefix-strip false branch)
        """
        patched_git.get_diff.return_value = [ _diff( "y = 1", "add", "a.py" ) ]
        stats = BranchChangeAnalyzer().analyze()
        assert stats[ "language_details" ][ "python" ][ "code" ] == 1

    def test_verbose_logs_during_analyze( self, patched_git, capsys ):
        """Ensures: verbose=True emits processing/state-tracking lines."""
        patched_git.get_diff.return_value = [ _diff( "+x = 1", "add", "a.py" ) ]
        BranchChangeAnalyzer( verbose=True ).analyze()
        assert "Processing" in capsys.readouterr().out

    def test_debug_logs_completion( self, patched_git, capsys ):
        """Ensures: debug=True emits the 'Analysis complete' line."""
        BranchChangeAnalyzer( debug=True ).analyze()
        assert "Analysis complete" in capsys.readouterr().out

    def test_get_diff_failure_wrapped_in_branch_analyzer_error( self, patched_git ):
        """
        Ensures:
            - an exception from get_diff is wrapped as BranchAnalyzerError
              (the analyze() try/except branch)
        """
        patched_git.get_diff.side_effect = RuntimeError( "git boom" )
        with pytest.raises( BranchAnalyzerError ) as exc:
            BranchChangeAnalyzer().analyze()
        assert "Analysis failed" in str( exc.value )


class TestFormatResults:
    """format_results() dispatches to the right formatter by name."""

    @pytest.fixture
    def analyzer_with_stats( self, patched_git ):
        """An analyzer whose analyze() has produced a small real summary."""
        patched_git.get_diff.return_value = [
            _diff( "+x = 42", "add", "a.py" ),
            _diff( "-old", "remove", "a.py" ),
        ]
        analyzer = BranchChangeAnalyzer()
        analyzer._stats = analyzer.analyze()
        return analyzer

    def test_console_format( self, analyzer_with_stats ):
        """Ensures: console format returns the OVERALL SUMMARY banner text."""
        out = analyzer_with_stats.format_results( analyzer_with_stats._stats, format="console" )
        assert "OVERALL SUMMARY" in out

    def test_json_format( self, analyzer_with_stats ):
        """Ensures: json format returns a string containing base_branch."""
        out = analyzer_with_stats.format_results( analyzer_with_stats._stats, format="json" )
        assert "base_branch" in out

    def test_markdown_format_uses_correct_header( self, analyzer_with_stats ):
        """
        Ensures:
            - markdown format returns the REAL header 'Branch Comparison
              Analysis' (the legacy smoke test's '# Code Changes Analysis'
              assertion was stale — pinned correctly here)
        """
        out = analyzer_with_stats.format_results( analyzer_with_stats._stats, format="markdown" )
        assert "Branch Comparison Analysis" in out

    def test_invalid_format_raises_value_error( self, analyzer_with_stats ):
        """Ensures: an unsupported format name raises ValueError."""
        with pytest.raises( ValueError ):
            analyzer_with_stats.format_results( analyzer_with_stats._stats, format="pdf" )
