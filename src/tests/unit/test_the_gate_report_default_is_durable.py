"""
🔴 WHAT THIS PINS, AND WHY THE FOUR TESTS BESIDE IT CANNOT (row b254172a, 2026-09-05).

`test_the_gate_keeps_its_own_per_file_report.py` proves the gate WRITES a per-file report.
Every one of its four cases hands the gate an explicit `COVERAGE_REPORT_TXT`, so all four
exercise the OVERRIDE and are structurally blind to a broken DEFAULT: revert the default to
a scratchpad path and all four still pass, because none of them ever asks where the report
goes when nobody says.

That blindness is not hypothetical — it is the remaining half of this row's own defect. The
original artifact was unrecoverable because it lived beside `$COVERAGE_FILE`, which is a
session scratchpad for every seat that has run this gate. A fix that only adds an override
leaves the DEFAULT exactly as lossy as it was, and the override is used by nobody who has
not already been bitten.

⚠️ IT DRIVES THE REAL GATE, at the layer the incident entered at. The only thing relocated
is the fleet data root itself, via the `DEEPILY_DATA_DIR` env var that `fleet_data_root()`
already reads — so the gate's own resolution code runs unmodified and a real report lands on
a real disk. The frame check is EXPECTED to fail over a synthetic data file; FRAME_EXIT is
captured rather than exited on, so the floor section still runs. We assert on the report and
its announcement, never on the verdict.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
GATE         = f"{PROJECT_ROOT}/src/tests/run-coverage-gate.sh"


def _drive_the_real_gate( tmp_path, data_dir_value, lupin_root=None ):
    """
    Run the real coverage gate over a real measurement with COVERAGE_REPORT_TXT UNSET.

    Requires:
        - tmp_path is a writable directory unique to this test
        - data_dir_value is the DEEPILY_DATA_DIR the gate should resolve its durable
          root from; it may deliberately name an unusable location

    Ensures:
        - COVERAGE_REPORT_TXT is absent from the child's environment, so the gate must
          take its DEFAULT path — the thing under test
        - when lupin_root is given, the child's LUPIN_ROOT names THAT tree, so a
          resolver reading the environment answers about a different repo than the
          gate is measuring
        - returns ( completed_process, coverage_file_dir )

    Raises:
        - pytest.fail if the measurement step produced no coverage data
    """
    module = tmp_path / "subject.py"
    module.write_text( textwrap.dedent( """
        def taken( n ):
            if n > 0:
                return "positive"
            return "other"

        def never_taken():
            return "unreached"
    """ ) )
    ( tmp_path / "driver.py" ).write_text( "import subject\nsubject.taken( 1 )\n" )

    data_file = tmp_path / ".coverage-default-guard"
    env       = { **os.environ,
                  "COVERAGE_FILE"    : str( data_file ),
                  "DEEPILY_DATA_DIR" : str( data_dir_value ) }
    # The whole point of this file. Inheriting it would silently retarget the gate and
    # this guard would pass while measuring the override, which is the blind axis.
    env.pop( "COVERAGE_REPORT_TXT", None )
    if lupin_root is not None: env[ "LUPIN_ROOT" ] = str( lupin_root )

    measured = subprocess.run(
        [ sys.executable, "-m", "coverage", "run", "--branch", "driver.py" ],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120 )
    if not data_file.exists():
        pytest.fail( f"the measurement step wrote no data file: {measured.stderr[ :400 ]}" )

    done = subprocess.run( [ "bash", GATE ], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=300 )
    return done, tmp_path


def test_the_default_report_lands_under_the_fleet_data_root( tmp_path ):
    """
    THE ROW'S ACCEPTANCE CRITERION 1. With nothing overridden, the report must land
    somewhere that outlives the seat — the fleet data root, not the caller's scratchpad.
    """
    data_dir  = tmp_path / "fleet-data"
    done, _   = _drive_the_real_gate( tmp_path, data_dir )
    expected  = data_dir / "lupin" / "coverage" / "per-file-report.txt"

    assert expected.exists(), (
        "the gate's DEFAULT did not put the report under the fleet data root.\n"
        f"expected: {expected}\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )
    body = expected.read_text()
    assert "TOTAL" in body, f"the durable report carries no TOTAL line:\n{body[ :600 ]}"


def test_the_default_report_is_not_written_beside_the_coverage_data_file( tmp_path ):
    """
    🔴 THE DISCRIMINATING HALF. The test above passes if the gate writes the report to
    BOTH places; only this one fails when the default silently reverts to the scratchpad,
    which is the exact regression this row exists to prevent.
    """
    data_dir   = tmp_path / "fleet-data"
    done, _    = _drive_the_real_gate( tmp_path, data_dir )
    scratchpad = tmp_path / "coverage-per-file-report.txt"

    assert not scratchpad.exists(), (
        "the gate wrote its default report beside COVERAGE_FILE — a session scratchpad, "
        "which is how this row's original artifact became unrecoverable.\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )


def test_the_gate_names_the_durable_default_in_its_own_output( tmp_path ):
    """A report nobody can find is as lost as one that was never written."""
    data_dir = tmp_path / "fleet-data"
    done, _  = _drive_the_real_gate( tmp_path, data_dir )
    expected = data_dir / "lupin" / "coverage" / "per-file-report.txt"

    assert str( expected ) in done.stdout, (
        "the gate does not name its default report path.\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )


def test_an_unusable_fleet_root_degrades_loudly_instead_of_silently( tmp_path ):
    """
    🔴 THE FAIL-SAFE, AND IT MUST BE AUDIBLE. A report path may never fail the gate, so
    the fallback is correct — but a SILENT fallback to a scratchpad is this row's defect
    returning wearing the cure's clothes. The downgrade must announce itself.
    """
    # A regular FILE where a directory must be created: mkdir cannot succeed against it,
    # so the resolver fails for a real reason rather than a mocked one.
    blocker = tmp_path / "not-a-directory"
    blocker.write_text( "" )

    done, _    = _drive_the_real_gate( tmp_path, blocker )
    scratchpad = tmp_path / "coverage-per-file-report.txt"

    assert scratchpad.exists(), (
        "the gate wrote no report at all when the durable root was unusable — the "
        "fallback must still produce a measurement.\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )
    assert "DEGRADED TO A NON-DURABLE PATH" in done.stdout, (
        "the gate fell back to a scratchpad WITHOUT saying so. A silent downgrade is "
        "indistinguishable from the durable path working.\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )


def test_the_degradation_notice_is_absent_on_the_healthy_path( tmp_path ):
    """
    🔴 POSITIVE CONTROL FOR THE CASE ABOVE. An alarm that fired on every run would satisfy
    it and tell a reader nothing. This is the arm that shows it discriminates.
    """
    done, _ = _drive_the_real_gate( tmp_path, tmp_path / "fleet-data" )
    assert "DEGRADED TO A NON-DURABLE PATH" not in done.stdout, (
        "the gate announced a degraded report path on a perfectly healthy run.\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )


def test_the_default_describes_the_gates_own_tree_not_the_callers( tmp_path ):
    """
    🔴 THE PROPERTY: THE REPORT DESCRIBES THE GATE'S OWN TREE, NOT THE CALLER'S SHELL.

    Two independent mechanisms deliver it — `export LUPIN_ROOT="$PROJECT_ROOT"` at
    run-coverage-gate.sh:32, and the explicit `repo_root` handed to `fleet_data_root()`.
    Both derive from the same BASH_SOURCE-derived root. This test pins the PROPERTY, and
    deliberately does not pretend to isolate either mechanism.

    ⚠️ MEASURED 2026-09-06, four arms, one variable at a time — and the middle two are why
    this docstring does not claim more than it can:
        export + explicit   -> 10 passed   baseline
        export, NO explicit -> 10 passed   EQUIVALENT MUTANT — the export carries it
        NO export, explicit -> 10 passed   the argument carries it alone
        NEITHER             ->  1 FAILED   this test, by name

    ⇒ Removing EITHER mechanism is invisible here, because either one suffices. That is a
    real limit and not a defect in the guard: a test that reddened on a redundant mechanism
    being dropped would be asserting an implementation, not a behaviour.

    ⚠️ AND THE FIXTURE HAD TO BE FIXED BEFORE IT COULD SEE ANYTHING AT ALL. The first
    version merely UNSET LUPIN_ROOT and the both-removed arm still passed: with
    DEEPILY_DATA_DIR set, only the repo NAME comes from the root, and an unset LUPIN_ROOT
    falls back to "/var/lupin" whose name is ALSO "lupin" — the right and the wrong
    implementation agreed on the observable. Pointing LUPIN_ROOT at a DIFFERENT repo is
    what separates them.

    ⚠️ AND THE UNSET CASE IS STILL REAL AND STILL UNGUARDED HERE, said out loud rather than
    dissolved: with LUPIN_ROOT unset AND DEEPILY_DATA_DIR unset, `fleet_data_root()` returns
    "/projects-data/lupin" — the root of the filesystem (measured 2026-09-05 23:52 EDT).
    Reaching it requires unsetting DEEPILY_DATA_DIR, which would point this test at the
    fleet's REAL report and clobber it.
    """
    decoy = "/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting"
    if not Path( decoy ).is_dir():
        pytest.skip( f"no sibling repo to stand in as a decoy tree: {decoy}" )

    data_dir  = tmp_path / "fleet-data"
    done, _   = _drive_the_real_gate( tmp_path, data_dir, lupin_root=decoy )
    expected  = data_dir / "lupin" / "coverage" / "per-file-report.txt"
    wrong     = data_dir / Path( decoy ).name / "coverage" / "per-file-report.txt"

    assert not wrong.exists(), (
        "the gate filed its report under the CALLER's tree rather than its own — it is "
        f"reading LUPIN_ROOT instead of its BASH_SOURCE-derived root.\nwrong: {wrong}\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )
    assert expected.exists(), (
        "the gate did not file its report under its own tree's data root.\n"
        f"expected: {expected}\ngate stdout:\n{done.stdout[ -1800: ]}" )
