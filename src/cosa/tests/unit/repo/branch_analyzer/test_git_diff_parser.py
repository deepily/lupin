"""
Unit tests for cosa.repo.branch_analyzer.git_diff_parser.

Tests the DiffLine dataclass and GitDiffParser, which shells out to git via
subprocess. Every subprocess.run call is mocked so the suite runs fully
offline (no real git repo / no real process); the tests assert on the COMMANDS
built (including the repo_path → cwd wiring, which previously harboured a
cross-repo path bug elsewhere in this toolkit), the structured DiffLine parse,
operation classification, branch-name resolution, and every error path
(timeout / missing-git / generic failure / non-zero return code).

Part of the CoSA 100% coverage campaign (repo module group).
"""
import subprocess
from unittest import mock

import pytest

from cosa.repo.branch_analyzer.git_diff_parser import GitDiffParser, DiffLine
from cosa.repo.branch_analyzer.exceptions import GitCommandError


def _completed( stdout="", stderr="", returncode=0 ):
    """Build a fake subprocess.CompletedProcess-like result."""
    return subprocess.CompletedProcess( args=[], returncode=returncode, stdout=stdout, stderr=stderr )


@pytest.fixture
def run_mock():
    """
    Patch subprocess.run inside the git_diff_parser module.

    Ensures:
        - the constructor's _check_git_available() succeeds by default
          (first call returns a 0-exit `git --version`)
    Yields the MagicMock so tests can set .return_value / .side_effect.
    """
    with mock.patch( "cosa.repo.branch_analyzer.git_diff_parser.subprocess.run" ) as m:
        m.return_value = _completed( stdout="git version 2.40.0" )
        yield m


@pytest.fixture
def parser( run_mock ):
    """A GitDiffParser over repo_path='/repo' with git available."""
    return GitDiffParser( {}, repo_path="/repo" )


class TestDiffLine:
    """The DiffLine dataclass carries content/operation/file/line."""

    def test_fields_stored( self ):
        """Ensures: all four dataclass fields round-trip."""
        dl = DiffLine( content="+x", operation="add", file_path="a.py", line_number=3 )
        assert dl.content == "+x"
        assert dl.operation == "add"
        assert dl.file_path == "a.py"
        assert dl.line_number == 3


class TestInit:
    """Construction reads config knobs and verifies git availability."""

    def test_defaults_from_empty_config( self, parser ):
        """
        Ensures:
            - algorithm defaults to 'histogram', extra_opts to [], timeout to 60
            - repo_path is stored
        """
        assert parser.algorithm == "histogram"
        assert parser.extra_opts == []
        assert parser.timeout == 60
        assert parser.repo_path == "/repo"

    def test_config_overrides( self, run_mock ):
        """
        Ensures:
            - git.diff_algorithm / git.extra_diff_options / performance.git_timeout
              are read from config
        """
        cfg = {
            "git": { "diff_algorithm": "myers", "extra_diff_options": [ "--stat" ] },
            "performance": { "git_timeout": 5 },
        }
        p = GitDiffParser( cfg, repo_path="." )
        assert p.algorithm == "myers"
        assert p.extra_opts == [ "--stat" ]
        assert p.timeout == 5

    def test_check_git_available_runs_version_in_repo_path( self, run_mock ):
        """
        Ensures:
            - _check_git_available shells `git --version` with cwd=repo_path
              (cross-repo wiring: the parser must operate in the TARGET repo,
              not the cwd of the caller)
        """
        GitDiffParser( {}, repo_path="/some/other/repo" )
        first_call = run_mock.call_args_list[ 0 ]
        assert first_call.args[ 0 ] == [ "git", "--version" ]
        assert first_call.kwargs[ "cwd" ] == "/some/other/repo"

    def test_git_not_found_raises( self, run_mock ):
        """Ensures: FileNotFoundError on `git --version` raises GitCommandError."""
        run_mock.side_effect = FileNotFoundError()
        with pytest.raises( GitCommandError ):
            GitDiffParser( {}, repo_path="." )

    def test_git_version_nonzero_raises( self, run_mock ):
        """Ensures: a non-zero `git --version` exit raises GitCommandError."""
        run_mock.return_value = _completed( returncode=1 )
        with pytest.raises( GitCommandError ):
            GitDiffParser( {}, repo_path="." )

    def test_git_version_generic_error_raises( self, run_mock ):
        """Ensures: an unexpected error verifying git raises GitCommandError."""
        run_mock.side_effect = RuntimeError( "boom" )
        with pytest.raises( GitCommandError ):
            GitDiffParser( {}, repo_path="." )

    def test_debug_init_logs( self, run_mock, capsys ):
        """Ensures: debug=True logs algorithm/timeout + repository lines."""
        GitDiffParser( {}, repo_path="/repo", debug=True )
        out = capsys.readouterr().out
        assert "Algorithm" in out
        assert "Repository" in out


class TestGetDiff:
    """get_diff builds the diff command, parses output, handles failures."""

    def test_builds_command_with_algorithm_range_and_extra_opts( self, run_mock ):
        """
        Ensures:
            - the git diff command embeds the algorithm flag, the base...head
              range, and any extra options, and runs with cwd=repo_path
        """
        cfg = { "git": { "diff_algorithm": "myers", "extra_diff_options": [ "--stat" ] } }
        p = GitDiffParser( cfg, repo_path="/repo" )
        run_mock.return_value = _completed( stdout="" )
        p.get_diff( "main", "HEAD" )

        call = run_mock.call_args_list[ -1 ]
        cmd = call.args[ 0 ]
        assert cmd[ :2 ] == [ "git", "diff" ]
        assert "--diff-algorithm=myers" in cmd
        assert "main...HEAD" in cmd
        assert cmd[ -1 ] == "--stat"
        assert call.kwargs[ "cwd" ] == "/repo"

    def test_parses_structured_diff_lines( self, parser, run_mock ):
        """
        Ensures:
            - output is parsed into DiffLine objects
            - the current file is tracked from the 'diff --git' header
            - operations are classified (add/remove/meta/context)
        """
        diff = (
            "diff --git a/a.py b/a.py\n"
            "index 111..222 100644\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1 +1 @@\n"
            "+added line\n"
            "-removed line\n"
            " context line\n"
        )
        run_mock.return_value = _completed( stdout=diff )
        lines = parser.get_diff( "main", "HEAD" )

        ops = { dl.operation for dl in lines }
        assert { "add", "remove", "meta", "context" } <= ops
        add_line = next( dl for dl in lines if dl.operation == "add" )
        assert add_line.file_path == "a.py"
        assert add_line.content == "+added line"

    def test_timeout_raises( self, parser, run_mock ):
        """Ensures: a subprocess timeout raises GitCommandError."""
        run_mock.side_effect = subprocess.TimeoutExpired( cmd="git diff", timeout=60 )
        with pytest.raises( GitCommandError ):
            parser.get_diff( "main", "HEAD" )

    def test_git_missing_raises( self, parser, run_mock ):
        """Ensures: FileNotFoundError during diff raises GitCommandError."""
        run_mock.side_effect = FileNotFoundError()
        with pytest.raises( GitCommandError ):
            parser.get_diff( "main", "HEAD" )

    def test_generic_error_raises( self, parser, run_mock ):
        """Ensures: an unexpected error during diff raises GitCommandError."""
        run_mock.side_effect = RuntimeError( "boom" )
        with pytest.raises( GitCommandError ):
            parser.get_diff( "main", "HEAD" )

    def test_nonzero_returncode_raises( self, parser, run_mock ):
        """Ensures: a non-zero git diff exit raises GitCommandError with detail."""
        run_mock.return_value = _completed( returncode=128, stderr="fatal: bad rev" )
        with pytest.raises( GitCommandError ):
            parser.get_diff( "main", "HEAD" )

    def test_debug_logs_command_and_count( self, run_mock, capsys ):
        """Ensures: debug=True logs the running command and parsed-line count."""
        p = GitDiffParser( {}, repo_path="/repo", debug=True )
        run_mock.return_value = _completed( stdout="+x\n" )
        p.get_diff( "main", "HEAD" )
        out = capsys.readouterr().out
        assert "Running" in out
        assert "Parsed" in out


class TestGetChangedFiles:
    """get_changed_files runs --name-only and returns a clean file list."""

    def test_returns_stripped_nonempty_files( self, parser, run_mock ):
        """
        Ensures:
            - the --name-only command is built with the base...head range
            - blank lines are dropped and entries stripped
        """
        run_mock.return_value = _completed( stdout="a.py\n\nb.js\n" )
        files = parser.get_changed_files( "main", "HEAD" )
        assert files == [ "a.py", "b.js" ]
        cmd = run_mock.call_args_list[ -1 ].args[ 0 ]
        assert cmd == [ "git", "diff", "--name-only", "main...HEAD" ]

    def test_timeout_raises( self, parser, run_mock ):
        """Ensures: a timeout raises GitCommandError."""
        run_mock.side_effect = subprocess.TimeoutExpired( cmd="git", timeout=60 )
        with pytest.raises( GitCommandError ):
            parser.get_changed_files( "main", "HEAD" )

    def test_generic_error_raises( self, parser, run_mock ):
        """Ensures: an unexpected error raises GitCommandError."""
        run_mock.side_effect = RuntimeError( "boom" )
        with pytest.raises( GitCommandError ):
            parser.get_changed_files( "main", "HEAD" )

    def test_nonzero_returncode_raises( self, parser, run_mock ):
        """Ensures: a non-zero exit raises GitCommandError."""
        run_mock.return_value = _completed( returncode=1, stderr="boom" )
        with pytest.raises( GitCommandError ):
            parser.get_changed_files( "main", "HEAD" )

    def test_debug_logs_command( self, run_mock, capsys ):
        """Ensures: debug=True logs the running command."""
        p = GitDiffParser( {}, repo_path="/repo", debug=True )
        run_mock.return_value = _completed( stdout="a.py\n" )
        p.get_changed_files( "main", "HEAD" )
        assert "Running" in capsys.readouterr().out


class TestGetBranchName:
    """get_branch_name resolves a ref via rev-parse, falling back to the ref."""

    def test_resolves_symbolic_ref( self, parser, run_mock ):
        """Ensures: HEAD resolves to the concrete branch name on success."""
        run_mock.return_value = _completed( stdout="feature-x\n" )
        assert parser.get_branch_name( "HEAD" ) == "feature-x"

    def test_returns_ref_when_resolution_yields_head( self, parser, run_mock ):
        """
        Ensures:
            - if rev-parse returns the literal 'HEAD' (detached), the original
              ref is returned instead (the branch_name=='HEAD' guard)
        """
        run_mock.return_value = _completed( stdout="HEAD\n" )
        assert parser.get_branch_name( "HEAD" ) == "HEAD"

    def test_returns_ref_when_resolution_empty( self, parser, run_mock ):
        """Ensures: an empty rev-parse stdout falls back to the original ref."""
        run_mock.return_value = _completed( stdout="\n" )
        assert parser.get_branch_name( "main" ) == "main"

    def test_returns_ref_on_nonzero_returncode( self, parser, run_mock ):
        """Ensures: a non-zero rev-parse exit falls back to the original ref."""
        run_mock.return_value = _completed( returncode=1 )
        assert parser.get_branch_name( "weird-ref" ) == "weird-ref"

    def test_returns_ref_on_exception( self, parser, run_mock ):
        """Ensures: any exception during resolution falls back to the ref (never raises)."""
        run_mock.side_effect = RuntimeError( "boom" )
        assert parser.get_branch_name( "main" ) == "main"


class TestClassifyDiffLine:
    """_classify_diff_line maps a raw diff line to its operation."""

    def test_empty_line_is_context( self, parser ):
        """Ensures: an empty string classifies as context."""
        assert parser._classify_diff_line( "" ) == "context"

    def test_addition( self, parser ):
        """Ensures: a '+' line (not '+++') is an add."""
        assert parser._classify_diff_line( "+new" ) == "add"

    def test_plus_header_is_meta_not_add( self, parser ):
        """Ensures: the '+++ ' file header is meta, not an addition."""
        assert parser._classify_diff_line( "+++ b/a.py" ) == "meta"

    def test_removal( self, parser ):
        """Ensures: a '-' line (not '---') is a remove."""
        assert parser._classify_diff_line( "-gone" ) == "remove"

    def test_minus_header_is_meta_not_remove( self, parser ):
        """Ensures: the '--- ' file header is meta, not a removal."""
        assert parser._classify_diff_line( "--- a/a.py" ) == "meta"

    @pytest.mark.parametrize( "line", [
        "diff --git a/x b/x",
        "index 111..222",
        "@@ -1 +1 @@",
        "Binary files differ",
    ] )
    def test_meta_markers( self, parser, line ):
        """Ensures: diff/index/@@/Binary headers classify as meta."""
        assert parser._classify_diff_line( line ) == "meta"

    def test_plain_context_line( self, parser ):
        """Ensures: an unprefixed content line classifies as context."""
        assert parser._classify_diff_line( " unchanged" ) == "context"

    def test_parse_diff_header_without_enough_parts_keeps_file_none( self, parser, run_mock ):
        """
        Ensures:
            - a malformed 'diff --git' header (<4 tokens) does NOT set a file
              path (the len(parts)>=4 false branch); the line still parses
        """
        run_mock.return_value = _completed( stdout="diff --git\n+x\n" )
        lines = parser.get_diff( "main", "HEAD" )
        add_line = next( dl for dl in lines if dl.operation == "add" )
        assert add_line.file_path is None
