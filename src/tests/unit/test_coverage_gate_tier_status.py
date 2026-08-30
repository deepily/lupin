"""
Row `e2099400` — the coverage gate must not publish a partial measurement as a whole one.

🔴 WHAT THIS PINS, MEASURED 2026-08-30. `run-coverage-gate.sh --run-tiers` invoked its two
tiers with a bare `bash …` and captured NEITHER exit status (line 25 sets `-o pipefail` but
not `-e`). A peer suite arrived between the tiers, the contention guard correctly refused the
cosa tier with exit 6, and the gate rendered the data file anyway:

    TOTAL 70,842 statements / 20,045 missing = 70.68%   ->   "COVERAGE GATE FAILED"

against 95.14% from the identical tree an hour earlier. Nothing regressed — 8,769 cosa tests
never ran — and the verdict named a percentage and a floor while saying nothing about a
refused tier.

⚠️ THE HARD HALF IS NOT DETECTING FAILURE, IT IS NOT OVER-DETECTING IT. A tier that RAN and
had FAILING TESTS (pytest exit 1) measured perfectly well; the verified 95.14% baseline was
earned by a run carrying 14 pre-existing failures. A fix that treated "non-zero" as "did not
measure" would have discarded the correct answer and blocked every merge. That case —
test_a_tier_with_failing_tests_still_measured — is the one that keeps this honest, and it is
the reason the classifier is a whitelist of {0, 1} rather than a check for zero.

⚠️ AND IT FAILED RED ONLY BY LUCK. Which way a partial run lands depends on which tier goes
missing. A red gets investigated; a green does not.

Venue: :7999-eligible. Sources one shell library and runs a stubbed gate against a fake
repo; no server, no network, no state outside tmp_path, well under a second.
"""

import os
import subprocess

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
TIER_LIB     = f"{PROJECT_ROOT}/src/scripts/lib/tier-measured.sh"
GATE         = f"{PROJECT_ROOT}/src/tests/run-coverage-gate.sh"

# The statuses a tier can exit with, and whether its coverage data may be rendered.
# pytest: 0 ok · 1 tests failed · 2 interrupted · 3 internal · 4 usage · 5 nothing collected.
# guard-contended-coverage.sh: 6 contended · 7 could-not-tell.
_MEASURED     = [ 0, 1 ]
_NOT_MEASURED = [ 2, 3, 4, 5, 6, 7, 127 ]


def _classify( status ):
    """Source the library and ask it about one status. Returns (measured, reason)."""
    script = ( f'source "{TIER_LIB}"\n'
               f'if tier_measured {status}; then echo MEASURED; else echo NOT; fi\n'
               f'tier_not_measured_reason {status}\n' )
    done = subprocess.run( [ "bash", "-c", script ], capture_output=True, text=True, timeout=30 )
    assert done.returncode == 0, done.stderr
    lines = done.stdout.strip().splitlines()
    return lines[ 0 ] == "MEASURED", lines[ 1 ]


# ── the classifier ───────────────────────────────────────────────────────────

@pytest.mark.parametrize( "status", _MEASURED )
def test_a_tier_that_ran_counts_as_measured( status ):
    measured, _ = _classify( status )
    assert measured is True


def test_a_tier_with_failing_tests_still_measured():
    """
    🔴 THE CASE THE FIX EXISTS TO NOT BREAK. pytest exit 1 means the tests RAN. The
    coverage data is complete and the number is real — the verified 95.14% baseline was
    earned by a run with 14 failures in it. Treat this as "did not measure" and the gate
    becomes inconclusive on every branch that has a single red test, which is worse than
    the defect being fixed.
    """
    measured, _ = _classify( 1 )
    assert measured is True, "a tier with failing tests was wrongly called unmeasured"


@pytest.mark.parametrize( "status", _NOT_MEASURED )
def test_a_tier_that_never_ran_is_not_measured( status ):
    measured, reason = _classify( status )
    assert measured is False
    assert reason.strip(), "an unmeasured tier must say WHY, or the verdict is unactionable"


@pytest.mark.parametrize( "status,fragment", [ ( 6, "REFUSED" ), ( 7, "REFUSED" ),
                                               ( 5, "collected no tests" ),
                                               ( 4, "usage error" ) ] )
def test_the_reason_names_the_actual_cause( status, fragment ):
    _, reason = _classify( status )
    assert fragment in reason


def test_an_unrecognised_status_still_gets_a_reason():
    """A classifier that goes silent on the case nobody anticipated is the defect again."""
    _, reason = _classify( 99 )
    assert "99" in reason and reason.strip()


# ── the gate itself, driven against stub tiers ───────────────────────────────

def _fake_repo( tmp_path, unit_exit, cosa_exit ):
    """
    A repo-shaped tree whose two tier scripts exit with the statuses we choose. The gate
    resolves PROJECT_ROOT from its own location, so a copy placed here runs against here.
    """
    ( tmp_path / "src/tests" ).mkdir( parents=True )
    ( tmp_path / "src/scripts/lib" ).mkdir( parents=True )
    for name, code in ( ( "run-unit-tests.sh", unit_exit ), ( "run-cosa-tests.sh", cosa_exit ) ):
        target = tmp_path / "src/tests" / name
        target.write_text( f'#!/bin/bash\necho "stub {name} exiting {code}"\nexit {code}\n' )
        target.chmod( 0o755 )
    for lib in ( "tier-measured.sh", "resolve-venv-pytest.sh" ):
        source = f"{PROJECT_ROOT}/src/scripts/lib/{lib}"
        if os.path.exists( source ):
            ( tmp_path / "src/scripts/lib" / lib ).write_text( open( source ).read() )
    # The gate resolves an EXPLICIT venv pytest before anything else and exits 3 without one
    # (row c98bce3f — never a silent `python3 -m pytest` fallback). Link the real one in, or
    # every case below dies at that guard instead of reaching the tier logic under test.
    ( tmp_path / ".venv" ).symlink_to( f"{PROJECT_ROOT}/.venv" )
    gate = tmp_path / "src/tests/run-coverage-gate.sh"
    gate.write_text( open( GATE ).read() )
    gate.chmod( 0o755 )
    return gate


def _run_gate( tmp_path, unit_exit, cosa_exit ):
    gate = _fake_repo( tmp_path, unit_exit, cosa_exit )
    env  = dict( os.environ )
    env[ "COVERAGE_FILE" ] = str( tmp_path / ".coverage-stub" )
    env.pop( "LUPIN_COVERAGE", None )
    return subprocess.run( [ "bash", str( gate ), "--run-tiers" ],
                           capture_output=True, text=True, env=env, timeout=120 )


@pytest.mark.parametrize( "unit_exit,cosa_exit,who", [ ( 6, 0, "unit" ), ( 0, 6, "cosa" ),
                                                       ( 6, 6, "unit" ) ] )
def test_a_refused_tier_makes_the_gate_inconclusive_not_a_floor_breach( tmp_path, unit_exit,
                                                                        cosa_exit, who ):
    """
    THE REGRESSION PIN. Exit 2 (inconclusive), never 1 (below the floor), and no percentage
    anywhere — a number printed beside a fail_under is read as a verdict on the CODE, and
    this one would be a verdict on the BOX.
    """
    done = _run_gate( tmp_path, unit_exit, cosa_exit )
    assert done.returncode == 2, f"expected inconclusive, got {done.returncode}: {done.stdout}"
    assert "INCONCLUSIVE" in done.stdout
    assert f"the {who} tier exited 6" in done.stdout, "the verdict does not name the tier"
    assert "REFUSED" in done.stdout,                  "the verdict does not name the cause"
    assert "coverage gate: floor" not in done.stdout, "it rendered a floor verdict anyway"


def test_both_refused_tiers_are_both_named( tmp_path ):
    """One re-run per problem is how a two-problem run costs two re-runs."""
    done = _run_gate( tmp_path, 6, 7 )
    assert "the unit tier exited 6" in done.stdout
    assert "the cosa tier exited 7" in done.stdout


def test_tiers_that_ran_let_the_gate_proceed_to_its_real_work( tmp_path ):
    """
    The other direction, and it must not be forgotten: statuses 0 and 1 are NOT inconclusive.
    The stub repo holds no coverage data, so the gate goes on to its own no-data branch —
    which is the point. It got PAST the tier check and reached the measurement.
    """
    done = _run_gate( tmp_path, 0, 1 )
    assert "INCONCLUSIVE — a tier did not run" not in done.stdout
    assert "NO COVERAGE DATA TO GATE ON" in done.stdout, \
        "the gate did not reach the data check, so the tier gate over-fired"


def test_an_empty_data_file_is_inconclusive_rather_than_a_floor_breach( tmp_path ):
    """
    'No data' was exit 1 — the same code as a floor breach — so a build log could not tell
    'you are under the line' from 'nothing was measured'. It is exit 2 with the rest now.
    """
    done = _run_gate( tmp_path, 0, 0 )
    assert done.returncode == 2
    assert "INCONCLUSIVE" in done.stdout
