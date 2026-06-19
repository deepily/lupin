"""
Unit tests for cosa.repo.git_loc_delta.git_log_parser.

Tests GitLogParser, which shells out to `git log --numstat` and yields one
dict per non-binary file row. subprocess.run is fully mocked so the suite
runs offline (no real git repo); tests assert on the COMMAND built (flags +
cwd=repo_path, including a cross-repo path OUTSIDE the project tree), the
line-stream parse (commit headers → file rows), every skip/guard arc
(binary rows, malformed headers/rows, non-integer counts, orphan rows,
blank lines), and every error path (timeout / missing-git / generic /
non-zero return code).

Part of the CoSA 100% coverage campaign (repo module group).
"""
import subprocess
from unittest import mock

import pytest

from cosa.repo.git_loc_delta.git_log_parser import GitLogParser
from cosa.repo.git_loc_delta.exceptions import GitCommandError


def _completed( stdout="", stderr="", returncode=0 ):
    """Build a fake subprocess.CompletedProcess-like result."""
    return subprocess.CompletedProcess( args=[], returncode=returncode, stdout=stdout, stderr=stderr )


@pytest.fixture
def run_mock():
    """
    Patch subprocess.run inside the git_log_parser module.

    Yields the MagicMock so tests set .return_value / .side_effect; defaults
    to an empty successful run.
    """
    with mock.patch( "cosa.repo.git_loc_delta.git_log_parser.subprocess.run" ) as m:
        m.return_value = _completed( stdout="" )
        yield m


# A two-commit log: commit A has a python + a binary row; commit B has a
# markdown row. Schema: COMMIT|<sha>|<date>|<author>, then <added>\t<deleted>\t<path>.
_SAMPLE_LOG = (
    "COMMIT|sha_a|2026-05-16|rick@example.com\n"
    "10\t2\tsrc/a.py\n"
    "-\t-\tassets/logo.png\n"        # binary → skipped
    "COMMIT|sha_b|2026-05-17|maria@example.com\n"
    "5\t1\tdocs/readme.md\n"
)


class TestBuildCommand:
    """_build_command assembles the git log invocation from the options."""

    def test_base_command_has_numstat_and_pretty( self ):
        """Ensures: the core flags (--numstat, --date=short, --pretty, --no-merges) are present by default."""
        cmd = GitLogParser()._build_command()
        assert cmd[ :2 ] == [ "git", "log" ]
        assert "--numstat" in cmd
        assert "--date=short" in cmd
        assert "--pretty=format:COMMIT|%H|%ad|%aE" in cmd
        assert "--no-merges" in cmd          # include_merges defaults False

    def test_include_merges_drops_no_merges( self ):
        """Ensures: include_merges=True omits the --no-merges flag."""
        cmd = GitLogParser( include_merges=True )._build_command()
        assert "--no-merges" not in cmd

    def test_since_until_author_and_rev_range_appended( self ):
        """Ensures: since/until/author/rev_range each contribute their token when set."""
        cmd = GitLogParser(
            since="2026-05-01", until="2026-05-31",
            author="rick@example.com", rev_range="main..HEAD",
        )._build_command()
        assert "--since=2026-05-01" in cmd
        assert "--until=2026-05-31" in cmd
        assert "--author=rick@example.com" in cmd
        assert cmd[ -1 ] == "main..HEAD"

    def test_optional_flags_absent_when_unset( self ):
        """Ensures: with no date/author/rev options, none of those tokens appear."""
        cmd = GitLogParser()._build_command()
        assert not any( c.startswith( "--since=" ) for c in cmd )
        assert not any( c.startswith( "--until=" ) for c in cmd )
        assert not any( c.startswith( "--author=" ) for c in cmd )


class TestRun:
    """_run executes git log with cwd=repo_path and translates failures."""

    def test_runs_in_repo_path_and_returns_stdout( self, run_mock ):
        """
        Ensures:
            - subprocess.run is invoked with cwd=repo_path (cross-repo wiring)
            - stdout is returned verbatim on success
        """
        run_mock.return_value = _completed( stdout="hello" )
        parser = GitLogParser( repo_path="/some/other/repo" )
        assert parser._run() == "hello"
        assert run_mock.call_args.kwargs[ "cwd" ] == "/some/other/repo"

    def test_cross_repo_path_outside_project( self, run_mock ):
        """
        Ensures (cross-target invocation per mandate):
            - a repo_path OUTSIDE the project tree is passed through as cwd
        """
        run_mock.return_value = _completed( stdout="" )
        GitLogParser( repo_path="/tmp/some-unrelated-repo" )._run()
        assert run_mock.call_args.kwargs[ "cwd" ] == "/tmp/some-unrelated-repo"

    def test_timeout_raises( self, run_mock ):
        """Ensures: a subprocess timeout raises GitCommandError."""
        run_mock.side_effect = subprocess.TimeoutExpired( cmd="git log", timeout=60 )
        with pytest.raises( GitCommandError ):
            GitLogParser()._run()

    def test_git_missing_raises( self, run_mock ):
        """Ensures: FileNotFoundError (git absent) raises GitCommandError."""
        run_mock.side_effect = FileNotFoundError()
        with pytest.raises( GitCommandError ):
            GitLogParser()._run()

    def test_generic_error_raises( self, run_mock ):
        """Ensures: an unexpected error raises GitCommandError."""
        run_mock.side_effect = RuntimeError( "boom" )
        with pytest.raises( GitCommandError ):
            GitLogParser()._run()

    def test_nonzero_returncode_raises( self, run_mock ):
        """Ensures: a non-zero git exit raises GitCommandError with detail."""
        run_mock.return_value = _completed( returncode=128, stderr="fatal: bad revision" )
        with pytest.raises( GitCommandError ):
            GitLogParser()._run()

    def test_debug_logs_command( self, run_mock, capsys ):
        """Ensures: debug=True logs the running command."""
        run_mock.return_value = _completed( stdout="" )
        GitLogParser( debug=True )._run()
        assert "Running" in capsys.readouterr().out


class TestIterChanges:
    """iter_changes parses the line stream into per-file dicts."""

    def test_parses_commit_headers_and_file_rows( self, run_mock ):
        """
        Ensures:
            - each non-binary file row yields a dict carrying the CURRENT
              commit's date/sha/author plus path/added/deleted (ints)
            - the binary row is skipped (not yielded)
        """
        run_mock.return_value = _completed( stdout=_SAMPLE_LOG )
        rows = list( GitLogParser().iter_changes() )

        assert len( rows ) == 2
        assert rows[ 0 ] == {
            "date": "2026-05-16", "sha": "sha_a", "author": "rick@example.com",
            "path": "src/a.py", "added": 10, "deleted": 2,
        }
        assert rows[ 1 ][ "path" ] == "docs/readme.md"
        assert rows[ 1 ][ "sha" ] == "sha_b"
        assert rows[ 1 ][ "added" ] == 5

    def test_blank_lines_skipped( self, run_mock ):
        """Ensures: blank / whitespace-only lines are ignored."""
        run_mock.return_value = _completed(
            stdout="COMMIT|s|2026-05-16|a@b\n\n   \n3\t1\tx.py\n"
        )
        rows = list( GitLogParser().iter_changes() )
        assert len( rows ) == 1
        assert rows[ 0 ][ "path" ] == "x.py"

    def test_binary_rows_skipped_with_verbose_log( self, run_mock, capsys ):
        """Ensures: a `-\\t-\\t` binary row is skipped and (verbose) logged."""
        run_mock.return_value = _completed(
            stdout="COMMIT|s|2026-05-16|a@b\n-\t-\timg.png\n"
        )
        rows = list( GitLogParser( verbose=True ).iter_changes() )
        assert rows == []
        assert "Skipping binary file" in capsys.readouterr().out

    def test_malformed_commit_header_skipped( self, run_mock, capsys ):
        """
        Ensures:
            - a COMMIT| header without exactly 4 fields is skipped (debug log),
              and a following file row becomes an orphan (no current sha) → skipped
        """
        run_mock.return_value = _completed(
            stdout="COMMIT|only|two\n9\t9\tx.py\n"
        )
        rows = list( GitLogParser( debug=True ).iter_changes() )
        out = capsys.readouterr().out
        assert rows == []
        assert "malformed commit header" in out
        assert "Orphan file row" in out

    def test_malformed_file_row_skipped( self, run_mock, capsys ):
        """Ensures: a file row without 3 tab-fields is skipped (debug log)."""
        run_mock.return_value = _completed(
            stdout="COMMIT|s|2026-05-16|a@b\nonly_one_field\n"
        )
        rows = list( GitLogParser( debug=True ).iter_changes() )
        assert rows == []
        assert "malformed file row" in capsys.readouterr().out

    def test_non_integer_counts_skipped( self, run_mock, capsys ):
        """Ensures: a row whose added/deleted aren't ints is skipped (debug log)."""
        run_mock.return_value = _completed(
            stdout="COMMIT|s|2026-05-16|a@b\nxx\tyy\tx.py\n"
        )
        rows = list( GitLogParser( debug=True ).iter_changes() )
        assert rows == []
        assert "Non-integer counts" in capsys.readouterr().out

    def test_orphan_file_row_before_any_commit_skipped( self, run_mock, capsys ):
        """Ensures: a file row appearing before any COMMIT header is skipped (debug log)."""
        run_mock.return_value = _completed( stdout="3\t1\tx.py\n" )
        rows = list( GitLogParser( debug=True ).iter_changes() )
        assert rows == []
        assert "Orphan file row" in capsys.readouterr().out

    def test_verbose_yield_count_logged( self, run_mock, capsys ):
        """Ensures: verbose mode logs the total yielded-row count at the end."""
        run_mock.return_value = _completed( stdout=_SAMPLE_LOG )
        list( GitLogParser( verbose=True ).iter_changes() )
        assert "Yielded 2 file change rows" in capsys.readouterr().out

    def test_iter_changes_propagates_run_failure( self, run_mock ):
        """Ensures: a git failure during the underlying _run surfaces as GitCommandError."""
        run_mock.return_value = _completed( returncode=1, stderr="boom" )
        with pytest.raises( GitCommandError ):
            list( GitLogParser().iter_changes() )
