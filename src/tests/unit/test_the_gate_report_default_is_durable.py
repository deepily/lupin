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


def _drive_the_real_gate( tmp_path, data_dir_value, lupin_root=None, drop_lupin_root=False ):
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
    if lupin_root is not None:  env[ "LUPIN_ROOT" ] = str( lupin_root )
    if drop_lupin_root:         env.pop( "LUPIN_ROOT", None )

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

    `fleet_data_root()` reads LUPIN_ROOT through `cu.get_project_root()`, so on its own it
    would answer about whatever tree the CALLER's shell names. What makes it answer about the
    gate's tree is `export LUPIN_ROOT="$PROJECT_ROOT"` at run-coverage-gate.sh:32, from the
    script's own BASH_SOURCE-derived root — and THAT is what this test guards. Delete line 32
    and this case plus its sibling below go red by name, rather than the report quietly
    following whoever ran the gate.

    ⚠️ AND THE FIXTURE HAD TO BE FIXED BEFORE IT COULD DISCRIMINATE AT ALL. An earlier version
    merely UNSET LUPIN_ROOT, and removing the export left it GREEN: with DEEPILY_DATA_DIR set,
    only the repo NAME comes from the root, and the unset fallback "/var/lupin" is ALSO named
    "lupin" — the right and the wrong resolution agreeing on the observable. Pointing
    LUPIN_ROOT at a DIFFERENT repo is what separates them. The unset case is kept as its own
    test below, for the different property it does pin.
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


def test_the_report_survives_an_absent_caller_lupin_root( tmp_path ):
    """
    🔴 THE CASE AN EARLIER DRAFT CALLED "UNGUARDED", NOW SHOWN TO BE UNREACHABLE.

    `fleet_data_root()` with LUPIN_ROOT unset falls through `cu.get_project_root()` to
    "/var/lupin" and yields "/projects-data/lupin" — the root of the filesystem, which does
    not exist and cannot be created (measured 2026-09-05 23:52 EDT). That was reported as a
    live exposure for this gate. It is not one: line 32 exports LUPIN_ROOT before anything
    resolves, so a caller who has none cannot produce that state here.

    ⇒ So this is the receipt for "unreachable", not a guard on the bad path. It drives the
    real gate with LUPIN_ROOT ABSENT from the caller's environment and asserts the report
    still lands under the gate's own tree AND that the fail-safe never fired — a degradation
    here would mean the resolver had escaped line 32 and reached the unwritable path.

    ⚠️ WHAT IS STILL NOT REACHED, said out loud rather than dissolved: DEEPILY_DATA_DIR is set
    here. With BOTH it and LUPIN_ROOT unset the resolver really would return
    "/projects-data/lupin" — but unsetting DEEPILY_DATA_DIR points this test at the fleet's
    REAL report and clobbers it, and line 32 makes that combination unreachable from the gate
    regardless. The measurement stands; its relevance to THIS caller does not.
    """
    data_dir = tmp_path / "fleet-data"
    done, _  = _drive_the_real_gate( tmp_path, data_dir, drop_lupin_root=True )
    expected = data_dir / "lupin" / "coverage" / "per-file-report.txt"

    assert expected.exists(), (
        "with no LUPIN_ROOT in the caller's environment the gate did not resolve its own "
        "tree — line 32's export is not governing the resolver.\n"
        f"expected: {expected}\ngate stdout:\n{done.stdout[ -1800: ]}" )
    assert "DEGRADED TO A NON-DURABLE PATH" not in done.stdout, (
        "the gate fell back to a scratchpad merely because the CALLER had no LUPIN_ROOT — "
        "the resolver reached the unwritable /projects-data path.\n"
        f"gate stdout:\n{done.stdout[ -1800: ]}" )


def test_a_directory_that_exists_but_cannot_be_written_still_degrades( tmp_path ):
    """
    🔴 THE WRITE PROBE, AND IT WAS UNGUARDED UNTIL THIS ARM WAS RUN.

    `mkdir( parents=True, exist_ok=True )` SUCCEEDS against a directory that already exists
    and that nothing may write to — it has nothing to create. So a resolver that stops at
    mkdir reports a healthy durable path, and the failure surfaces later, at the moment the
    report is written, when the measurement is already gone. That is this row's own defect
    arriving one step further downstream.

    ⚠️ MEASURED 2026-09-06: deleting the probe from the gate left every other case in this
    file GREEN — 11 passed. The probe's other sibling case reaches an unusable root by
    putting a FILE where a directory must be created, which mkdir catches on its own, so
    nothing there needed the probe. This is the case that does.

    ⇒ Pre-create the durable directory read-only, so mkdir has nothing to do and succeeds,
    and only an actual write can tell the difference.
    """
    durable = tmp_path / "fleet-data" / "lupin" / "coverage"
    durable.mkdir( parents=True )
    durable.chmod( 0o555 )
    try:
        done, _ = _drive_the_real_gate( tmp_path, tmp_path / "fleet-data" )
        assert "DEGRADED TO A NON-DURABLE PATH" in done.stdout, (
            "the gate accepted an unwritable durable directory because mkdir succeeded "
            "against it — the write probe is gone, and the failure moves to report time.\n"
            f"gate stdout:\n{done.stdout[ -1800: ]}" )
        assert ( tmp_path / "coverage-per-file-report.txt" ).exists(), (
            "the gate announced a degradation but wrote no fallback report.\n"
            f"gate stdout:\n{done.stdout[ -1800: ]}" )
    finally:
        # pytest cannot clean a read-only directory; restore the mode whatever happened.
        durable.chmod( 0o755 )
