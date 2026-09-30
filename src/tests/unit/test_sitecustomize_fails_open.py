"""
The startup shim must never brick an interpreter — proven by running one.

WHY THIS FILE IS SEPARATE, and why it spawns subprocesses. `sitecustomize` is
imported by `site` before any test framework exists, so its behaviour cannot be
observed from inside a process that has already started. The only honest way to
assert "a failure here does not stop the interpreter" is to START AN INTERPRETER
whose shim fails, and see whether it runs.

Raised by Mr Radio 🦉 in review: "it must fail open and say so — and I want a
test that proves it, not a try/except I have to read." He was right, and the
`# pragma: no cover` this replaces claimed the case was unreachable from the
tier. It is reachable; it just needs a subprocess rather than a monkeypatch.

⚠️ THE BLAST RADIUS IS WHY THIS MATTERS. `src/` is on the path for every Python
process in this repo, so an unguarded exception in the shim would take down the
test tier, the dev server, the arbiter and the MCP server simultaneously — every
interpreter you would need in order to fix it.
"""
import os
import pathlib
import subprocess
import sys

import pytest

import cosa.utils.util as cu


REAL_SHIM = pathlib.Path( cu.get_project_root(), "src", "sitecustomize.py" )

# A stand-in for `cosa.utils.checked_hash_pyc` that blows up on import, which is
# the shape of every failure the shim's guard exists for: a bad CPython version,
# a partial checkout, an ImportError from a moved private API.
POISON = "raise {exc}( 'deliberate failure staged by test_sitecustomize_fails_open' )\n"

# ⚠️ BOTH BRANCHES OF THE EXCEPTION TREE, and the second one is the whole point.
# `Exception` covers the ordinary failures (bad CPython version, partial checkout).
# `KeyboardInterrupt` does NOT derive from it, and an escaping BaseException does
# not merely skip the patch — CPython reports "Fatal Python error: init_import_site"
# and the interpreter never starts. Measured 2026-08-31: staged KeyboardInterrupt
# and SystemExit both exited 1 with that fatal error against an `except Exception`
# shim, while a staged RuntimeError exited 0 and reached the caller. Raised in
# review by Rachel 🕊️.
STAGED_FAILURES = [ "RuntimeError", "KeyboardInterrupt" ]


def _stage( tmp_path, poisoned, exc="RuntimeError" ):
    """
    Build a directory holding the REAL shim and a `cosa.utils.checked_hash_pyc`.

    Requires:
        - tmp_path is an empty directory
        - poisoned selects whether that module raises on import
        - exc names the exception class the staged module raises

    Ensures:
        - returns a path suitable as the sole PYTHONPATH entry
        - the shim is a byte-for-byte copy of the shipped one, never a rewrite —
          a test of a re-typed copy measures the copy

    Raises:
        - None
    """
    root = tmp_path / ( f"poisoned-{exc}" if poisoned else "healthy" )
    ( root / "cosa" / "utils" ).mkdir( parents=True )

    ( root / "sitecustomize.py" ).write_bytes( REAL_SHIM.read_bytes() )
    ( root / "cosa" / "__init__.py" ).write_text( "" )
    ( root / "cosa" / "utils" / "__init__.py" ).write_text( "" )
    ( root / "cosa" / "utils" / "checked_hash_pyc.py" ).write_text(
        POISON.format( exc=exc ) if poisoned
        else "def install( loader_cls=None, trace=None ): return True\n"
    )

    return root


def _run( root, code ):
    """
    Start a fresh interpreter with `root` as its only PYTHONPATH entry.

    Requires:
        - root contains a sitecustomize.py

    Ensures:
        - returns the CompletedProcess, never raising on a non-zero exit

    Raises:
        - None
    """
    env = dict( os.environ )
    env[ "PYTHONPATH" ] = str( root )

    return subprocess.run(
        [ sys.executable, "-c", code ],
        capture_output = True,
        text           = True,
        env            = env,
        timeout        = 60
    )


@pytest.mark.parametrize( "exc", STAGED_FAILURES )
def test_a_shim_that_raises_does_not_stop_the_interpreter( tmp_path, exc ):
    """
    THE ASSERTION THAT MATTERS. The staged module raises on import; the
    interpreter must still start, run the caller's code, and exit 0.

    Parametrized across both branches of the exception tree because they fail
    DIFFERENTLY: an uncaught Exception skips the patch, while an uncaught
    BaseException aborts interpreter startup entirely.
    """
    result = _run( _stage( tmp_path, poisoned=True, exc=exc ), "print( 'ALIVE' )" )

    assert result.returncode == 0, (
        f"an interpreter whose shim raised exited {result.returncode} — the shim "
        f"is not failing open, and every Python process in this repo would be "
        f"affected.\nstderr:\n{result.stderr}"
    )
    assert "ALIVE" in result.stdout, (
        f"the interpreter did not reach the caller's code.\nstdout: {result.stdout!r}"
    )


@pytest.mark.parametrize( "exc", STAGED_FAILURES )
def test_the_staged_failure_really_fires( tmp_path, exc ):
    """
    POSITIVE CONTROL, and without it the test above is worthless: it would pass
    identically against a harness whose poisoned module was never imported at
    all. Importing it directly must raise the staged error.
    """
    root   = _stage( tmp_path, poisoned=True, exc=exc )
    result = _run(
        root,
        "import cosa.utils.checked_hash_pyc"
    )

    assert result.returncode != 0, "the poisoned module imported cleanly — nothing was staged"
    assert "deliberate failure staged by" in result.stderr, (
        f"the staged module raised something else, so the fail-open test above "
        f"is not exercising the case it claims.\nstderr:\n{result.stderr}"
    )


def test_the_healthy_shim_reaches_install_and_the_interpreter_still_runs( tmp_path ):
    """
    The other half of the control. If the shim never called `install()` at all,
    the fail-open test would also pass — because nothing would ever raise. This
    proves the staged shim genuinely executes its import-and-call path.
    """
    root   = _stage( tmp_path, poisoned=False )
    result = _run(
        root,
        "import sys; print( 'INSTALLED' if 'cosa.utils.checked_hash_pyc' in sys.modules else 'NEVER IMPORTED' )"
    )

    assert result.returncode == 0
    assert "INSTALLED" in result.stdout, (
        f"the shim did not import checked_hash_pyc at startup, so the fail-open "
        f"test is not covering a path that runs.\nstdout: {result.stdout!r}"
    )
