"""
Unit tests for cosa.repo.git_loc_delta (AC12).

Three required-v1 tests covering:
- Parser correctly skips binary file rows
- Aggregator buckets by (date, file_type)
- CSV writer produces stable tidy-long schema regardless of file-type cardinality

Author: María 🌸 (session 3c9fce51, 2026-05-16)
Plan:   src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md
"""

import os
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

import cosa.utils.util as cu
from cosa.repo.git_loc_delta.csv_writer       import CSV_COLUMNS, write_csv
from cosa.repo.git_loc_delta.daily_aggregator import DailyAggregator
from cosa.repo.git_loc_delta.git_log_parser   import GitLogParser


# --- Fixtures ---------------------------------------------------------------

_FAKE_GIT_LOG_OUTPUT = (
    "COMMIT|abc1234|2026-05-15|alice@example.com\n"
    "10\t2\tsrc/cosa/foo.py\n"
    "5\t1\tREADME.md\n"
    "-\t-\timg/logo.png\n"                  # binary — must be skipped
    "\n"                                     # blank — must be skipped
    "COMMIT|def5678|2026-05-15|bob@example.com\n"
    "20\t4\tsrc/cosa/foo.py\n"
    "COMMIT|ghi9abc|2026-05-16|alice@example.com\n"
    "7\t3\tsrc/lib/bar.js\n"
    "1\t0\tCHANGELOG.md\n"
)


class _FakeCompletedProcess:
    """Minimal subprocess.CompletedProcess look-alike for monkey-patching."""

    def __init__( self, stdout: str, returncode: int = 0, stderr: str = "" ):
        self.stdout     = stdout
        self.returncode = returncode
        self.stderr     = stderr


# --- Test 1: parser binary-row skip -----------------------------------------

def test_parser_handles_binary_files():
    """
    GitLogParser.iter_changes must skip rows that report `-\t-\tpath` (binary).

    Verifies AC6.
    """
    parser = GitLogParser( repo_path=".", since="2026-05-15", until="2026-05-17" )

    with patch( "subprocess.run", return_value=_FakeCompletedProcess( _FAKE_GIT_LOG_OUTPUT ) ):
        changes = list( parser.iter_changes() )

    paths = [ c["path"] for c in changes ]

    # The 4 non-binary file rows should be yielded
    assert len( changes ) == 5, f"Expected 5 non-binary changes, got {len(changes)}: {paths}"

    # The binary row must NOT appear
    assert "img/logo.png" not in paths, "Binary file row leaked through the parser"

    # Spot-check counts and metadata propagation
    first = changes[0]
    assert first["sha"]    == "abc1234"
    assert first["date"]   == "2026-05-15"
    assert first["author"] == "alice@example.com"
    assert first["path"]   == "src/cosa/foo.py"
    assert first["added"]   == 10
    assert first["deleted"] == 2


# --- Test 2: aggregator (date, file_type) bucketing -------------------------

def test_aggregator_buckets_by_date_and_type():
    """
    DailyAggregator.record + .by_type + .daily must group rows correctly.

    Verifies AC1 / AC2 aggregation semantics + AC18 file-uniqueness counting.
    """
    # We rely on the real branch_analyzer config for file-type classification.
    # python → "python", markdown → "markdown", javascript → "javascript".
    agg = DailyAggregator( debug=False )

    rows = [
        # 2026-05-15 python: two commits, two distinct file paths
        { "date": "2026-05-15", "sha": "a", "author": "x", "path": "src/foo.py", "added": 10, "deleted": 2 },
        { "date": "2026-05-15", "sha": "a", "author": "x", "path": "src/foo.py", "added":  5, "deleted": 1 },
        { "date": "2026-05-15", "sha": "b", "author": "y", "path": "src/bar.py", "added": 20, "deleted": 4 },
        # 2026-05-15 markdown: one commit, one file
        { "date": "2026-05-15", "sha": "a", "author": "x", "path": "README.md",  "added":  3, "deleted": 0 },
        # 2026-05-16 javascript: one commit, one file
        { "date": "2026-05-16", "sha": "c", "author": "z", "path": "lib/baz.js", "added":  7, "deleted": 3 },
    ]
    for r in rows:
        agg.record( r )

    by_type = agg.by_type()

    # (2026-05-15, python) bucket
    py_key = ( "2026-05-15", "python" )
    assert py_key in by_type
    assert by_type[py_key]["added"]         == 10 + 5 + 20
    assert by_type[py_key]["deleted"]       == 2 + 1 + 4
    assert by_type[py_key]["files_touched"] == 2          # foo.py + bar.py
    assert by_type[py_key]["commits"]       == 2          # SHAs a and b

    # (2026-05-15, markdown) bucket
    md_key = ( "2026-05-15", "markdown" )
    assert md_key in by_type
    assert by_type[md_key]["added"]         == 3
    assert by_type[md_key]["files_touched"] == 1

    # (2026-05-16, javascript) bucket
    js_key = ( "2026-05-16", "javascript" )
    assert js_key in by_type
    assert by_type[js_key]["added"]   == 7
    assert by_type[js_key]["deleted"] == 3

    # Daily totals
    daily = agg.daily()
    assert "2026-05-15" in daily and "2026-05-16" in daily
    assert daily["2026-05-15"]["added"]   == 38         # 35 python + 3 markdown
    assert daily["2026-05-15"]["deleted"] == 7          # 7 python + 0 markdown
    assert daily["2026-05-15"]["commits"] == 2          # unique SHAs across all types
    # by_file_type sorted by added desc
    types_15 = [ row["file_type"] for row in daily["2026-05-15"]["by_file_type"] ]
    assert types_15[0] == "python", f"Expected python first (highest added), got {types_15}"

    # Summary
    summary = agg.summary()
    assert summary["total_added"]   == 45
    assert summary["total_deleted"] == 10
    assert summary["total_days"]    == 2
    assert summary["total_commits"] == 3          # a, b, c
    assert summary["net"]           == 35


# --- Test 3: CSV schema stability -------------------------------------------

def test_csv_long_shape_is_stable_across_file_types():
    """
    write_csv must emit the same 6-column header regardless of which file types
    appear in the input. New file types add ROWS, not COLUMNS — that's the
    tidy-long invariant.

    Verifies AC4.
    """
    # Two by-type dicts with disjoint file-type sets
    by_type_a = {
        ( "2026-05-15", "python" ):   { "added": 100, "deleted":  20, "files_touched": 5, "commits": 2 },
        ( "2026-05-15", "markdown" ): { "added":  50, "deleted":  10, "files_touched": 2, "commits": 2 },
    }
    by_type_b = {
        ( "2026-05-16", "javascript" ): { "added": 30, "deleted": 5, "files_touched": 1, "commits": 1 },
        ( "2026-05-16", "typescript" ): { "added": 80, "deleted": 9, "files_touched": 3, "commits": 1 },
        ( "2026-05-16", "rust" ):       { "added": 12, "deleted": 0, "files_touched": 1, "commits": 1 },
    }

    with tempfile.TemporaryDirectory() as td:
        path_a = os.path.join( td, "a.csv" )
        path_b = os.path.join( td, "b.csv" )

        rows_a = write_csv( by_type_a, path=path_a, repo="repo-a" )
        rows_b = write_csv( by_type_b, path=path_b, repo="repo-b" )

        assert rows_a == 2
        assert rows_b == 3

        df_a = pd.read_csv( path_a )
        df_b = pd.read_csv( path_b )

        # Schema invariant: same columns in same order regardless of input
        assert list( df_a.columns ) == CSV_COLUMNS, f"a.csv columns drifted: {list(df_a.columns)}"
        assert list( df_b.columns ) == CSV_COLUMNS, f"b.csv columns drifted: {list(df_b.columns)}"

        # Row-count invariant: rows match the number of (date, file_type) keys
        assert len( df_a ) == 2
        assert len( df_b ) == 3

        # Sort invariant: within a date, rows are ordered by `added` desc
        # In df_b all rows share date 2026-05-16; verify ordering: typescript(80) > javascript(30) > rust(12)
        types_b = df_b["file_type"].tolist()
        assert types_b == [ "typescript", "javascript", "rust" ], f"Sort drift: {types_b}"


# --- Empty-input CSV (edge: AC17) -------------------------------------------

def test_csv_empty_input_produces_header_only():
    """
    Empty by_type dict must still produce a CSV with the header row (AC17 edge).
    """
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join( td, "empty.csv" )
        rows = write_csv( {}, path=path, repo="test-repo" )

        assert rows == 0
        df = pd.read_csv( path )
        assert list( df.columns ) == CSV_COLUMNS
        assert len( df ) == 0


# --- F5 (2026-05-16): cross-target invocation regression -------------------


def test_default_csv_path_branch_mode_resolves_under_target_repo_not_lupin():
    """
    Regression for the 2026-05-16 cross-repo bug filed by Tiberius 🌑.

    When --repo-path points OUTSIDE the Lupin tree, the default CSV save path
    must land inside the TARGET repo's `io/git-loc-delta/` tree — not in
    Lupin's tree. The original implementation used `cu.get_project_root()`
    (always LUPIN_ROOT), causing cross-repo runs to cross-contaminate Lupin.

    Per `feedback_tests_must_cover_cross_target_invocations` — when a CLI
    takes a path parameter to operate on something OTHER than the current
    project, the test pyramid MUST include an invocation pointing OUTSIDE
    the project tree.
    """
    from cosa.repo.run_git_loc_delta import _default_csv_path, _resolve_target_root, _resolve_repo_name

    with tempfile.TemporaryDirectory() as td:
        sibling = os.path.join( td, "fake-sibling-repo" )
        os.makedirs( sibling )

        target_root = _resolve_target_root( sibling )
        repo_name   = _resolve_repo_name( None, target_root )
        path = _default_csv_path(
            mode        = "branch",
            target_root = target_root,
            repo_name   = repo_name,
            branch      = "wip-feature-x",
        )

        # Must land INSIDE the target repo's tree
        assert path.startswith( sibling + os.sep ), (
            f"Path leaked outside target repo: {path}"
        )
        # Must use the target repo's basename in the filename
        assert "fake-sibling-repo" in path, f"Filename missing target repo name: {path}"
        # Must end with the canonical pattern
        assert path.endswith( "fake-sibling-repo-wip-feature-x-loc-delta.csv" ), (
            f"Filename pattern drift: {path}"
        )
        # MUST NOT contain LUPIN_ROOT (this is the regression-locker)
        lupin_root = cu.get_project_root()
        assert lupin_root not in path, (
            f"Cross-contamination — path leaked into Lupin tree: {path} (lupin_root={lupin_root})"
        )


def test_default_csv_path_today_mode_also_target_aware():
    """
    --today mode must ALSO resolve relative to --repo-path, not LUPIN_ROOT.
    Same cross-target principle as the branch-mode test; this locks the
    archival-snapshot path against the same regression.
    """
    from cosa.repo.run_git_loc_delta import _default_csv_path, _resolve_target_root, _resolve_repo_name

    with tempfile.TemporaryDirectory() as td:
        sibling = os.path.join( td, "another-sibling" )
        os.makedirs( sibling )

        target_root = _resolve_target_root( sibling )
        repo_name   = _resolve_repo_name( None, target_root )
        path = _default_csv_path(
            mode        = "today",
            target_root = target_root,
            repo_name   = repo_name,
            branch      = None,
        )

        assert path.startswith( sibling + os.sep ), (
            f"Today-mode path leaked outside target repo: {path}"
        )
        # Today-mode filename uses a date stamp, not the repo name
        assert path.endswith( "-loc-delta.csv" )
        # Lock the date format implicitly via length (YYYY-MM-DD = 10 chars)
        basename = os.path.basename( path )
        assert len( basename ) == len( "YYYY-MM-DD-loc-delta.csv" ), (
            f"Today-mode filename pattern drift: {basename}"
        )


def test_default_csv_path_same_tree_still_lands_under_lupin():
    """
    Confirm the cross-target fix does NOT break the in-tree case. Calling
    with `repo_path="."` from within the Lupin tree should still land at
    `{LUPIN_ROOT}/io/git-loc-delta/...` — same as before the fix.
    """
    from cosa.repo.run_git_loc_delta import _default_csv_path, _resolve_target_root, _resolve_repo_name

    target_root = _resolve_target_root( "." )
    repo_name   = _resolve_repo_name( None, target_root )
    path = _default_csv_path(
        mode        = "branch",
        target_root = target_root,
        repo_name   = repo_name,
        branch      = "wip-test",
    )

    # In-tree resolution: "." resolves to the Lupin repo root, so the default
    # path must land under that target_root (same as before the cross-target fix).
    assert os.path.isabs( path )
    assert path.startswith( target_root + os.sep )
    assert path.endswith( "-wip-test-loc-delta.csv" )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
