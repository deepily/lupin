"""
Argument-surface tests for `src/scripts/migrate-pyc-to-checked-hash.sh` (row a4e36bcb).

WHY THESE EXIST. The script used to test `$1` only for the literal `--verify` and assign
`TARGETS=( "$LUPIN_ROOT/src" )` unconditionally, so a path on the command line was neither
used nor rejected — it was silently discarded. `--verify <tmpdir>` on a directory holding
exactly ONE unchecked-hash pyc reported `2416 (checked-hash=2416)` and exited 0: a clean bill
of health for a scope the operator never named.

That is worse than a wrong answer. The output is internally consistent and simply about
something else, so the reader has no thread to pull — the same shape CLAUDE.md records for
the two-database trap in §TESTING VENUES. The redirect test below is the one that would have
caught it; the rest hold the argument surface closed around it.
"""
import os
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path( __file__ ).resolve().parents[ 3 ] / "src" / "scripts" / "migrate-pyc-to-checked-hash.sh"


def _run( *args ):
    """
    Requires:
        - SCRIPT exists and is executable

    Ensures:
        - returns the CompletedProcess with stdout/stderr captured as text
        - PYTHON is pinned to the interpreter running the tests, so the census's
          "THIS interpreter" bucket is the one that planted the probe pyc
    """
    env = dict( os.environ, PYTHON=sys.executable )
    return subprocess.run( [ str( SCRIPT ), *args ], capture_output=True, text=True, env=env )


def _plant( directory, mode ):
    """
    Requires:
        - directory is an existing directory
        - mode is a py_compile.PycInvalidationMode

    Ensures:
        - writes one module under directory/pkg and compiles its pyc in the given mode
        - returns the path to the written pyc
    """
    pkg = Path( directory ) / "pkg"
    pkg.mkdir( parents=True, exist_ok=True )
    src = pkg / "mod.py"
    src.write_text( "X = 1\n" )
    py_compile.compile( str( src ), doraise=True, invalidation_mode=mode )
    ( pyc, ) = list( ( pkg / "__pycache__" ).glob( "*.pyc" ) )
    return pyc


def test_verify_on_a_named_directory_reports_on_that_directory_not_on_src( tmp_path ):
    """The redirect case. A clean `src/` must not launder a dirty directory the operator named."""
    _plant( tmp_path, py_compile.PycInvalidationMode.UNCHECKED_HASH )

    result = _run( "--verify", str( tmp_path ) )
    out    = result.stdout + result.stderr

    assert result.returncode == 1, out
    # It answered about the directory it was GIVEN...
    assert str( tmp_path.resolve() ) in out
    assert "unchecked-hash=1" in out
    # ...and not about the tree it used to silently substitute. The main tree holds thousands
    # of pycs, so any count above the single planted one is the redirect defect returning.
    assert "1 pyc(s) for THIS interpreter are not checked-hash" in out


def test_convert_honours_a_named_directory( tmp_path ):
    """Honoured on the WRITE path too — a scope the converter ignores is a scope it lies about."""
    pyc = _plant( tmp_path, py_compile.PycInvalidationMode.UNCHECKED_HASH )

    result = _run( str( tmp_path ) )
    out    = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert str( tmp_path.resolve() ) in out
    flags = int.from_bytes( pyc.read_bytes()[ 4:8 ], "little" )
    assert flags & 0b11 == 0b11, f"pyc flags {flags:#b} — not checked-hash after conversion"


def test_census_names_the_roots_it_scanned_by_default():
    """No arguments = the default root, and the census still SAYS which root that was."""
    out = _run( "--verify" ).stdout
    assert "scanned roots:" in out
    assert str( ( SCRIPT.parents[ 2 ] / "src" ).resolve() ) in out


def test_failure_verdict_does_not_assert_a_mode_the_census_contradicts( tmp_path ):
    """
    The verdict used to read "still timestamp-based" one line under a census reading
    `unchecked-hash=1`. Unchecked-hash is the more dangerous mode — timestamp at least
    invalidates on mtime+size — so naming the wrong one understates the finding.
    """
    _plant( tmp_path, py_compile.PycInvalidationMode.UNCHECKED_HASH )

    out = _run( "--verify", str( tmp_path ) ).stdout

    assert "NOT checked-hash" in out
    assert "timestamp-based" not in out


@pytest.mark.parametrize( "args", [ ( "--bogus", ), ( "--verify", "--nope" ), ( "-x", ) ] )
def test_unknown_option_is_refused_not_ignored( args ):
    """A tool that refuses what it cannot do never lies about what it did."""
    result = _run( *args )
    assert result.returncode == 2
    assert "unknown option" in result.stderr
    assert "Usage:" in result.stderr


def test_a_path_that_is_not_a_directory_is_refused( tmp_path ):
    """A file or a typo would scan no `__pycache__` at all and report a clean bill."""
    target = tmp_path / "mod.py"
    target.write_text( "X = 1\n" )

    result = _run( "--verify", str( target ) )
    assert result.returncode == 2
    assert "not a directory" in result.stderr


def test_missing_path_is_refused( tmp_path ):
    result = _run( "--verify", str( tmp_path / "does-not-exist" ) )
    assert result.returncode == 2
    assert "not a directory" in result.stderr


def test_verify_flag_is_positional_independent( tmp_path ):
    """`DIR --verify` must not convert; the flag is parsed wherever it appears."""
    pyc    = _plant( tmp_path, py_compile.PycInvalidationMode.UNCHECKED_HASH )
    before = pyc.read_bytes()

    result = _run( str( tmp_path ), "--verify" )

    assert result.returncode == 1, result.stdout + result.stderr
    assert pyc.read_bytes() == before, "--verify after the path still converted the tree"


def test_help_exits_zero_and_documents_the_path_argument():
    result = _run( "--help" )
    assert result.returncode == 0
    assert "DIR..." in result.stdout
    assert "never silently discarded" in result.stdout
