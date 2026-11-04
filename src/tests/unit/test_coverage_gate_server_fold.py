"""
The coverage gate folds the :8000 server's coverage of main.py into its data.

`src/lupin_app/main.py` is always in the frame, so a run with no usable server data owes no
number for it. That reads as inconclusive (exit 2), never as a floor breach and never as a pass.
The message names the scheduled :8000 run that produces the data. Stale data, where main.py's
content hash differs, and unreadable data get the same verdict.

The tests drive the real gate over a real small measurement from `coverage run --branch`, as the
per-file report guard beside them does. They read the verdict line and the report. The fold is
shown to reach the floor report by main.py's path appearing in it.

Venue: :7999-eligible. One gate run per case, a few seconds each, nothing outside tmp_path.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

import cosa.utils.server_coverage as sc
import cosa.utils.util as cu
from tests.helpers.server_coverage_fixture import make_server_dir

PROJECT_ROOT = cu.get_project_root()
GATE         = f"{PROJECT_ROOT}/src/tests/run-coverage-gate.sh"
MAIN_PY      = os.path.join( PROJECT_ROOT, sc.MAIN_PY_REL )


def _run_gate( tmp_path, server_dir ):
    """Measure a tiny driver for real, then run the real gate over that data with `server_dir`."""
    ( tmp_path / "subject.py" ).write_text( textwrap.dedent( """
        def taken( x ):
            if x > 0:
                return "positive"
            return "other"
    """ ) )
    ( tmp_path / "driver.py" ).write_text( "import subject\nsubject.taken( 1 )\n" )
    data_file  = tmp_path / ".coverage-fold"
    report_txt = tmp_path / "per-file-report.txt"
    env        = { **os.environ, "COVERAGE_FILE": str( data_file ), "COVERAGE_REPORT_TXT": str( report_txt ),
                   sc.DIR_ENV: str( server_dir ) }
    subprocess.run( [ sys.executable, "-m", "coverage", "run", "--branch", "driver.py" ],
                    cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120 )
    assert data_file.exists(), "the measurement step wrote no data file"
    done = subprocess.run( [ "bash", GATE ], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300 )
    return done, report_txt


def _inconclusive( done, reason ):
    assert done.returncode == 2, f"expected exit 2, got {done.returncode}:\n{done.stdout[ -1500: ]}"
    assert f"[server-coverage] {reason}:" in done.stdout
    assert "/api/v2/submit" in done.stdout and "LUPIN_SERVER_COVERAGE=1" in done.stdout, \
        "the verdict does not name the scheduled :8000 run that produces the data"
    assert "COVERAGE GATE INCONCLUSIVE" in done.stdout
    assert "COVERAGE GATE PASSED" not in done.stdout and "COVERAGE GATE FAILED" not in done.stdout
    assert "coverage gate: floor" not in done.stdout, "a floor verdict was rendered anyway"


def test_absent_server_data_is_inconclusive_not_a_breach_or_a_pass( tmp_path ):
    done, _ = _run_gate( tmp_path, tmp_path / "no-such-dir" )
    _inconclusive( done, "no-data" )


def test_server_data_recorded_on_another_main_py_is_inconclusive( tmp_path ):
    directory = make_server_dir( tmp_path / "srv" )
    with open( os.path.join( directory, sc.BOOT_NAME ), "w" ) as handle:
        json.dump( { "main_py_hash": "0" * 40 }, handle )
    done, _ = _run_gate( tmp_path, directory )
    _inconclusive( done, "stale" )


def test_server_data_without_a_sidecar_is_inconclusive( tmp_path ):
    directory = make_server_dir( tmp_path / "srv" )
    os.remove( os.path.join( directory, sc.BOOT_NAME ) )
    done, _ = _run_gate( tmp_path, directory )
    _inconclusive( done, "no-boot" )


def test_usable_server_data_reaches_the_floor_and_puts_main_py_in_the_report( tmp_path ):
    """The positive control: without it every case above could be the gate refusing everything."""
    done, report_txt = _run_gate( tmp_path, make_server_dir( tmp_path / "srv" ) )
    assert "[server-coverage] ok:" in done.stdout
    assert "coverage gate: frame completeness" in done.stdout and "coverage gate: floor" in done.stdout
    assert "INCONCLUSIVE" not in done.stdout
    assert "src/lupin_app/main.py" in report_txt.read_text(), "the folded main.py never reached the report"
