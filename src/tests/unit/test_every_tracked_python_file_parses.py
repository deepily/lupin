"""
Every tracked Python file parses — the receiving-side guard for a truncated write.

WHY THIS FILE EXISTS — row `cae4276c`. A tool call whose payload contains a literal matching
the harness's own parameter close-tag terminates early, and the value is written TRUNCATED with
no error anywhere. Two instances happened in one day, both while writing files.

The measurement that motivated this guard: such a literal can only ever be written INSIDE a
string or a comment, so the cut always lands inside one, so the string is always left
unterminated. Cutting 2,326 real repo files inside a string token produced a SyntaxError in
2,326 of them — 100%. The loss is invisible in prose and deterministic in code, and this guard
covers the half that is deterministic.

⚠️ IT WAS NOT ALREADY COVERED. The repo's other tree-wide AST sweeps read every .py, but
`test_job_state_transition_call_sites.py:41` does `except ( SyntaxError, ValueError, OSError ):
continue` — a truncated file is SKIPPED and its census silently shrinks. (By contrast
`test_step12_internal_callers_use_flow_submit.py:142` falls back to raw text and stays loud;
that one degrades safely.) The per-edit `py_compile` mandate covers the file you remember to
check. This covers the tree.

⚠️ DO NOT WRITE THE TRIGGERING LITERAL INTO THIS FILE. The samples below are ordinary
unterminated strings; none of them involves a tag. Assembling such a literal from pieces is the
authoring-side practice, and it is the ONLY remedy available for prose payloads.
"""

import ast
import os
import subprocess

import pytest


# Sub-repos are managed separately and are outside the Lupin gate (CLAUDE.md § Git Repository
# Management), so a parse failure in one of them is not this repo's to report.
EXCLUDED_PREFIXES = ( "src/lupin-mobile/", "src/lupin-plugin-firefox/" )


def repo_root():
    """The worktree this test file lives in — never an ambient LUPIN_ROOT pointing elsewhere."""

    here = os.path.dirname( os.path.abspath( __file__ ) )

    return os.path.abspath( os.path.join( here, "..", "..", ".." ) )


def tracked_python_files( root ):
    """Every tracked .py path, sub-repos removed. Tracked, so untracked scratch cannot redden it."""

    out = subprocess.run( [ "git", "-C", root, "ls-files", "*.py" ],
                          capture_output=True, text=True, check=True ).stdout.split()

    return [ p for p in out if not p.startswith( EXCLUDED_PREFIXES ) ]


def first_syntax_error( source_bytes ):
    """
    None when the source parses; a one-line description when it does not.

    Reads BYTES so each file's own PEP 263 encoding declaration is honored rather than utf-8
    being assumed — the same reason the existing call-site census reads bytes.
    """

    try:
        ast.parse( source_bytes )
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"

    return None


def broken_files( root, rel_paths ):
    """
    The subset of rel_paths that does not parse, each as "path | problem".

    Split out from the guard so its FAILURE path can be exercised against a fixture tree. A
    guard whose red branch has never run once is a guard nobody has seen work.
    """

    broken = [ ]
    for rel in rel_paths:
        with open( os.path.join( root, rel ), "rb" ) as fh:
            problem = first_syntax_error( fh.read() )
        if problem is not None:
            broken.append( f"{rel} | {problem}" )

    return broken


# ── the guard ─────────────────────────────────────────────────────────────────────────────

def test_every_tracked_python_file_parses():
    """
    Reddens on any tracked .py that does not parse — a truncated write among them.

    A file that does not parse is not merely untested: every AST census in the repo that
    swallows SyntaxError skips it silently, so the failure hides twice.
    """

    root   = repo_root()
    broken = broken_files( root, tracked_python_files( root ) )

    assert broken == [ ], (
        "tracked Python files do not parse — a truncated tool-call write looks exactly like "
        "this (an unterminated string where a close-tag literal was being typed):\n  "
        + "\n  ".join( broken ) )


def test_the_sweep_actually_reaches_the_tree():
    """
    Reddens if the file list comes back empty or tiny — an empty collection is the failure mode
    that makes a guard pass while checking nothing.
    """

    assert len( tracked_python_files( repo_root() ) ) > 500


# ── the detector itself, both directions ──────────────────────────────────────────────────

def test_first_syntax_error_is_silent_on_valid_source():
    """Reddens if the detector accuses a healthy file."""

    assert first_syntax_error( b"x = 1\n" ) is None


@pytest.mark.parametrize( "truncated", [
    b'x = "abc',                       # cut inside a single-quoted string
    b'DOC = """a docstring that stops', # cut inside a triple-quoted string
    b"def f(\n",                        # cut inside a call signature
] )
def test_first_syntax_error_catches_a_truncated_source( truncated ):
    """
    The shape a close-tag truncation leaves behind. Reddens if the detector stops catching an
    unterminated construct — none of these samples contains a tag.
    """

    assert first_syntax_error( truncated ) is not None


def test_an_encoding_mismatch_is_reported_not_raised():
    """
    Reading bytes means a file whose declared encoding its content does not honor reaches the
    sweep. Measured on this interpreter, ast.parse answers SyntaxError for all three byte-level
    faults — a bad coding declaration, a null byte, and invalid utf-8 — so there is no separate
    ValueError arm to catch. Reddens if the sweep starts raising instead of reporting.
    """

    assert first_syntax_error( b"# -*- coding: ascii -*-\nx = '\xff'\n" ) is not None
    assert first_syntax_error( b"x = 1\x00\n" )                          is not None


def test_broken_files_names_the_offender_and_spares_the_healthy( tmp_path ):
    """
    The guard's RED path, driven over a fixture tree. Reddens if the sweep stops reporting the
    offending path, or starts accusing a healthy file. Neither sample contains a tag.
    """

    ( tmp_path / "healthy.py"   ).write_bytes( b"x = 1\n" )
    ( tmp_path / "truncated.py" ).write_bytes( b'DOC = """a write that stopped' )

    result = broken_files( str( tmp_path ), [ "healthy.py", "truncated.py" ] )

    assert len( result ) == 1
    assert result[ 0 ].startswith( "truncated.py | " )


def test_sub_repos_are_excluded():
    """Reddens if the exclusion stops applying and a separately-managed repo enters the gate."""

    assert all( not p.startswith( EXCLUDED_PREFIXES )
                for p in tracked_python_files( repo_root() ) )
