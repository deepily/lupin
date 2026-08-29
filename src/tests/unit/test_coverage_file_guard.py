"""
The guard that refuses an unattributable coverage figure (row aa41fa66).

Every session working in lupin wrote the same repo-root `.coverage`, which
pytest-cov erases at startup, so a long run and a short one shared one mutable
file and the short one won — silently. A tier run reported 96.59% while ~28,000
statements had quietly left the denominator, and because the vanished files were
the worse-than-average ones the number went UP while nothing improved.

The path itself cannot be fixed from inside the repo: pytest-cov reads
COVERAGE_FILE before the rootdir conftest is imported, so by the time any code
here runs the destination is already chosen. What CAN be done is refuse to
produce the figure, which is what these tests pin.

Each case runs pytest in a SUBPROCESS: the guard is a `pytest_configure` hook, so
it can only be exercised by starting a real session with a real environment.
"""
import os
import subprocess
import sys

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
TARGET     = "src/tests/unit/scripts"          # small, fast, and has no coverage needs of its own
NEEDLE     = "COVERAGE_FILE is not set"


def _run( target=TARGET, cov=True, coverage_file=None, allow_shared=False ):
    """
    Start a real pytest session and return (returncode, combined output).

    Requires:
        - target is a pytest target relative to the repo root

    Ensures:
        - COVERAGE_FILE is ABSENT from the child env unless coverage_file is given,
          so the unset case is genuinely unset rather than inherited from the
          parent run that is executing this test
    """
    env = dict( os.environ )
    env.pop( "COVERAGE_FILE", None )
    env.pop( "LUPIN_ALLOW_SHARED_COVERAGE", None )
    if coverage_file:  env[ "COVERAGE_FILE" ]              = coverage_file
    if allow_shared:   env[ "LUPIN_ALLOW_SHARED_COVERAGE" ] = "1"

    cmd = [ sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider" ]
    if cov: cmd += [ "--cov=lupin_cli", "--cov-report=", "--cov-fail-under=0" ]

    proc = subprocess.run( cmd, cwd=LUPIN_ROOT, env=env, capture_output=True, text=True, timeout=300 )
    return proc.returncode, proc.stdout + proc.stderr


class TestTheGuardRefusesAnUnattributableFigure:

    def test_cov_without_coverage_file_fails_loudly( self ):
        """The case the row exists for: refuse BEFORE any measurement is written."""
        rc, out = _run( cov=True )

        assert rc != 0, "a --cov run with no COVERAGE_FILE must not succeed"
        assert NEEDLE in out, f"the refusal must name COVERAGE_FILE; output was:\n{out[ -2000: ]}"
        assert "export COVERAGE_FILE=" in out, "the refusal must carry the remedy, not just the complaint"

    def test_cov_with_an_exported_coverage_file_passes_silently( self, tmp_path ):
        """
        The other half of the contract. A guard that fires on the correct case too
        would just be a broken build, and everyone would learn to pass the hatch.
        """
        rc, out = _run( cov=True, coverage_file=str( tmp_path / "cov.data" ) )

        assert rc == 0, f"an exported COVERAGE_FILE must run clean; output was:\n{out[ -2000: ]}"
        assert NEEDLE not in out, "the guard fired on a correctly-configured run"

    def test_a_run_without_cov_is_never_touched( self ):
        """
        NEGATIVE CONTROL. Most runs in this repo pass no --cov at all; if the guard
        fired on those it would be a blanket outage rather than a control.
        """
        rc, out = _run( cov=False )

        assert rc == 0, f"a plain run must be unaffected; output was:\n{out[ -2000: ]}"
        assert NEEDLE not in out

    def test_the_escape_hatch_is_honored( self ):
        """A deliberate shared-file run stays possible, and has to be asked for by name."""
        rc, out = _run( cov=True, allow_shared=True )

        assert rc == 0, f"LUPIN_ALLOW_SHARED_COVERAGE must permit the run; output was:\n{out[ -2000: ]}"
        assert NEEDLE not in out
