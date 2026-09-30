"""
🔴 WHAT THIS PINS, AND WHY IT IS NOT CEREMONY (row b254172a, 2026-09-05).

`run-coverage-gate.sh` used to render the FULL per-file coverage table and then throw
away everything but three lines:

    "$PYBIN" -m coverage report --precision=2 | tail -3

The verdict survived. The MEASUREMENT did not. Measured cost: a correct, isolated,
fully-provenanced run of this gate could not answer the very next question its own row
asked — WHICH FILES ARE SHORT — because the breakdown had never been written anywhere,
and a 21-minute tier was re-run to recover a table rendered correctly two hours earlier.
It also hid a closed lever: pyproject's comment still names files "at 0%" that read
100.00%, because no run ever kept the evidence.

⚠️ A GATE THAT SILENTLY STOPS WRITING THE REPORT IS THAT DEFECT RETURNING, AND IT WOULD
STILL PASS. That is the whole reason this file exists: "the gate still exits 0" cannot
see it. These tests fail if the report is absent, unnamed, or incomplete.

⚠️ IT DRIVES THE REAL SCRIPT, NOT A HELPER. The incident entered at the gate, so the test
enters at the gate. The frame check runs first and is EXPECTED to fail here (a synthetic
data file does not satisfy the real frame) — that is fine and deliberate: FRAME_EXIT is
CAPTURED at run-coverage-gate.sh:169 rather than exited on, so the floor section still
runs. We assert on the report, never on the verdict.
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


def _run_gate_over_a_real_measurement( tmp_path ):
    """
    Produce a genuine coverage data file, then drive the real gate over it.

    Requires:
        - tmp_path is a writable directory unique to this test

    Ensures:
        - returns ( completed_process, report_path )
        - the data file holds a real measurement, so the gate does not take its
          NO COVERAGE DATA TO GATE ON early exit

    Raises:
        - pytest.fail if the measurement step produced no data
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
    driver = tmp_path / "driver.py"
    driver.write_text( "import subject\nsubject.taken( 1 )\n" )

    data_file  = tmp_path / ".coverage-guard"
    report_txt = tmp_path / "per-file-report.txt"
    env        = { **os.environ,
                   "COVERAGE_FILE"       : str( data_file ),
                   "COVERAGE_REPORT_TXT" : str( report_txt ) }

    measured = subprocess.run(
        [ sys.executable, "-m", "coverage", "run", "--branch", "driver.py" ],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120 )
    if not data_file.exists():
        pytest.fail( f"the measurement step wrote no data file: {measured.stderr[ :400 ]}" )

    done = subprocess.run( [ "bash", GATE ], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=300 )
    return done, report_txt


def test_the_gate_writes_a_per_file_report_to_disk( tmp_path ):
    """The report must EXIST. Its absence is the defect this row was opened for."""
    done, report_txt = _run_gate_over_a_real_measurement( tmp_path )
    assert report_txt.exists(), (
        "the gate produced no per-file report — the measurement died in the pipe again.\n"
        f"gate stdout:\n{done.stdout[ -1500: ]}" )


def test_the_report_is_not_empty_and_carries_a_total( tmp_path ):
    """
    POSITIVE CONTROL for the file above. An empty file EXISTS and satisfies every
    per-item assertion in a loop over nothing — so existence alone proves too little.
    """
    _, report_txt = _run_gate_over_a_real_measurement( tmp_path )
    body = report_txt.read_text()
    assert body.strip(), "the per-file report is empty"
    assert "TOTAL" in body, f"no TOTAL line in the report:\n{body[ :800 ]}"
    rows = [ l for l in body.splitlines()
             if l.strip() and not l.startswith( ( "Name", "-", "TOTAL" ) )
             and len( l.split() ) >= 4 ]
    assert rows, f"the report lists no files at all:\n{body[ :800 ]}"


def test_the_gate_names_the_report_path_in_its_own_output( tmp_path ):
    """
    A report nobody can find is as lost as one that was never written — which is
    precisely how the frame JSON's existence went unnoticed. The gate must SAY where it is.
    """
    done, report_txt = _run_gate_over_a_real_measurement( tmp_path )
    assert str( report_txt ) in done.stdout, (
        "the gate does not name the report path in its output.\n"
        f"gate stdout:\n{done.stdout[ -1500: ]}" )


def test_the_reports_miss_column_sums_to_its_own_total( tmp_path ):
    """
    🔴 COMPLETENESS, DEMONSTRATED RATHER THAN ASSERTED. A truncated report cannot sum to
    the total it claims to decompose. This is the same arithmetic check that proved the
    80-file list on row cd94cfb5 was complete rather than silently cut to fit.
    """
    _, report_txt = _run_gate_over_a_real_measurement( tmp_path )
    per_file, total = 0, None
    for line in report_txt.read_text().splitlines():
        parts = line.split()
        if len( parts ) < 4 or parts[ 0 ].startswith( "-" ) or parts[ 0 ] == "Name":
            continue
        try:
            miss = int( parts[ 2 ] )
        except ValueError:
            continue
        if parts[ 0 ] == "TOTAL": total     = miss
        else:                    per_file += miss
    assert total is not None, "no parseable TOTAL row in the report"
    assert per_file == total, (
        f"the report's file rows miss {per_file} but its TOTAL says {total} — "
        "the report does not decompose its own total, so it is truncated or misparsed" )
