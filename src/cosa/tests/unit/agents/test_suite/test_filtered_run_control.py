"""
Reviewer control for row f3beb6d5 — a FILTERED test-suite run must never render
as a full-suite pass.

WHO OWNS THIS FILE: Krishna 🦚 (reviewer). It is deliberately SEPARATE from
test_job.py so it does not share adjacent new lines with Rio's in-flight edits
(two crews adding contiguous lines make one unsplittable hunk — see
feedback_git_cannot_split_two_crews_contiguous_new_lines). It is self-contained:
it replicates the minimal test doubles rather than importing test_job.py's, so
there is zero coupling to Rio's file.

WHAT IT PROVES: these assertions go RED with the fix removed and GREEN with it
present — that is the whole point of a control. The three biting tests
(parse / cost_summary+filtered / failure-dominance) fail on today's tree
(no fix yet); the unfiltered guard stays green either way and proves the fix
does NOT red a deliberately-scoped TFE landing/confirm run.

Contract under test (ratified in
src/rnd/v0.2.0/2026.08.15-filtered-run-reports-as-full-suite-pass.md):
    1. `_run_suite` parses `deselected` from pytest stdout into the result dict.
    2. `deselected` is a SEPARATE cost_summary field; it NEVER reaches
       `_classify_outcome` (routing it into not_executed would red every
       filtered run — the trap this fix exists to avoid).
    3. cost_summary gains `total_deselected` (int) and `filtered` (bool);
       `all_passed` keeps its meaning for what actually ran.
    4. The report header names the scope when filtered ("FILTERED — 5 of 692").
"""
import asyncio
import subprocess

import pytest

import cosa.agents.test_suite.job as job_mod
from cosa.agents.test_suite.job import TestSuiteJob as TSJob


# =========================================================================== #
# Minimal, self-contained test doubles (replicated, NOT imported from test_job)
# =========================================================================== #
class _FakeStdout:
    """Scripted stand-in for a subprocess stdout pipe."""
    def __init__( self, lines ):
        self._lines = list( lines )

    def readline( self ):
        return self._lines.pop( 0 ) if self._lines else ""

    def read( self ):
        return ""


class _FakeProcess:
    """Scripted stand-in for subprocess.Popen's return value."""
    def __init__( self, lines, returncode=0 ):
        self.stdout           = _FakeStdout( lines )
        self.returncode       = returncode
        self.terminate_called = False
        self.kill_called      = False

    def poll( self ):
        return self.returncode

    def terminate( self ):
        self.terminate_called = True

    def kill( self ):
        self.kill_called = True

    def wait( self, timeout=None ):
        return 0


class _FakeConfigMgr:
    """ConfigurationManager double returning an empty extra-args string."""
    def get( self, key, default="", return_type="string" ):
        return ""


@pytest.fixture( autouse=True )
def _isolate_artifact_root( tmp_path, monkeypatch ):
    """Pin the artifact dir under tmp so no test writes the live ledger/log/junit."""
    monkeypatch.setattr( TSJob, "_ARTIFACT_DIR", str( tmp_path ) )


@pytest.fixture
def patched_voice( monkeypatch ):
    """Boundary-mock the voice_io + cosa_interface seam so no notification leaves."""
    from unittest.mock import AsyncMock, Mock
    import cosa.agents.test_suite.voice_io as vio
    import cosa.agents.test_suite.cosa_interface as ci

    notify = AsyncMock()
    monkeypatch.setattr( vio, "notify",       notify )
    monkeypatch.setattr( vio, "reconfigure",  Mock() )
    monkeypatch.setattr( vio, "set_job_id",   Mock() )
    monkeypatch.setattr( vio, "clear_job_id", Mock() )
    monkeypatch.setattr( ci,  "_get_sender_id", lambda suffix=None: f"test.suite@x#{suffix}" )
    return notify


@pytest.fixture
def no_real_log( monkeypatch ):
    """Stub _write_stdout_log so _run_suite never touches /tmp symlinks."""
    monkeypatch.setattr(
        job_mod.TestSuiteJob, "_write_stdout_log",
        classmethod( lambda cls, suite, text: "/tmp/fake-test.log" ),
    )


def _patch_config_mgr( monkeypatch ):
    import cosa.config.configuration_manager as cfg
    monkeypatch.setattr( cfg, "ConfigurationManager", lambda *a, **k: _FakeConfigMgr() )


def _make_job( **overrides ):
    kwargs = dict(
        test_types = [ "e2e" ],
        user_id    = "user123",
        user_email = "test@test.com",
        session_id = "session456",
    )
    kwargs.update( overrides )
    return TSJob( **kwargs )


# The exact pytest stdout the real defect produced (row f3beb6d5): a -k slice of
# one e2e file — 692 collected, 687 deselected, 5 selected/passed. Both pytest
# forms are present: the collection line AND the trailer.
_FILTERED_STDOUT = [
    "============================= test session starts ==============================\n",
    "collected 692 items / 687 deselected / 5 selected\n",
    "\n",
    "src/tests/e2e/test_action_required_self_content_pane.py .....             [100%]\n",
    "\n",
    "====================== 5 passed, 687 deselected in 23.08s ======================\n",
]


# =========================================================================== #
# BITE 1 — the parse seam: _run_suite must lift `deselected` out of stdout.
# =========================================================================== #
def test_run_suite_parses_deselected_from_stdout( monkeypatch, no_real_log ):
    """A filtered pytest run's stdout carries "687 deselected"; _run_suite must
    surface it as result["deselected"]. RED without the fix (key absent → 0)."""
    _patch_config_mgr( monkeypatch )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    monkeypatch.setattr( job_mod.subprocess, "Popen",
                         lambda *a, **k: _FakeProcess( lines=_FILTERED_STDOUT, returncode=0 ) )

    job = _make_job()
    res = job._run_suite( "e2e", "/proj" )

    assert res.get( "deselected", 0 ) == 687, (
        "result must carry the deselected count parsed from stdout; "
        f"got {res.get( 'deselected', 'MISSING' )}"
    )
    # And it must NOT have been laundered into not_executed (the trap): a
    # deselect is intentional scoping, not a tier that never ran.
    assert res.get( "not_executed", 0 ) == 0, (
        "deselected must NOT flow into not_executed — that would red every "
        "filtered run at _classify_outcome"
    )


# =========================================================================== #
# BITE 2 — the surface seam: cost_summary + report header on a green slice.
# =========================================================================== #
def _filtered_green_result( deselected=687, log_path=None ):
    """5 real passes, 687 deselected — the exact false-green shape."""
    return {
        "passed": 5, "failed": 0, "skipped": 0, "errors": 0,
        "not_executed": 0, "deselected": deselected,
        "exit_code": 0, "log_path": log_path, "duration": 23.08,
    }


def test_execute_filtered_green_flags_scope_not_full_pass( monkeypatch, tmp_path, patched_voice ):
    """A green filtered slice: all_passed stays True for what ran, but cost_summary
    must carry total_deselected + filtered=True and the report header must name the
    scope — so no dashboard/watchdog reads a 5-of-692 slice as a full-suite gate.
    RED without the fix (no total_deselected/filtered keys, header says only ALL PASSED)."""
    job = _make_job( test_types=[ "e2e" ] )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( job, "_run_suite", lambda st, pr: _filtered_green_result() )

    summary = asyncio.run( job._execute() )

    # The 5 that ran are a real pass — all_passed keeps its meaning.
    assert job.cost_summary[ "all_passed" ] is True
    # ...but the scope must be disclosed on the surfaced result.
    assert job.cost_summary.get( "total_deselected", 0 ) == 687
    assert job.cost_summary.get( "filtered", False ) is True

    # Report header names the scope. 692 = 5 executed + 687 deselected.
    import pathlib
    report_text = pathlib.Path( job.report_path ).read_text()
    assert "FILTERED" in report_text, "report header must name the filter"
    assert "692" in report_text, "report must state the full collected count"


# =========================================================================== #
# BITE 3 — a filtered run carrying a REAL failure: FAILED must still dominate.
# =========================================================================== #
def _filtered_failing_result( log_path=None ):
    """3 passed, 1 failed, 687 deselected — a red inside a slice."""
    return {
        "passed": 3, "failed": 1, "skipped": 0, "errors": 0,
        "not_executed": 0, "deselected": 687,
        "exit_code": 1, "log_path": log_path, "duration": 24.0,
        "failure_details": [ { "name": "t_x", "type": "FAILED" } ],
    }


def test_execute_filtered_with_failure_stays_red_and_flagged( monkeypatch, tmp_path, patched_voice ):
    """The filtered flag must never mask a genuine failure: a red slice reports
    FAILURES DETECTED with all_passed=False AND filtered=True. Guards both sides —
    the flag fires, and it does not launder a real red into a pass. RED without
    the fix (filtered key absent)."""
    job = _make_job( test_types=[ "e2e" ] )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( job, "_run_suite", lambda st, pr: _filtered_failing_result() )

    summary = asyncio.run( job._execute() )

    assert "FAILURES DETECTED" in summary
    assert job.cost_summary[ "all_passed" ] is False
    assert job.cost_summary.get( "filtered", False ) is True
    assert job.cost_summary.get( "total_deselected", 0 ) == 687


# =========================================================================== #
# GUARD (green either way) — an UNFILTERED full run must stay unflagged.
# This is the manager's core worry from the other side: the fix must NOT red or
# mislabel a run that selected everything. Not a bite; a regression guard.
# =========================================================================== #
def _unfiltered_result( log_path=None ):
    return {
        "passed": 692, "failed": 0, "skipped": 0, "errors": 0,
        "not_executed": 0, "deselected": 0,
        "exit_code": 0, "log_path": log_path, "duration": 600.0,
    }


def test_execute_unfiltered_run_not_flagged( monkeypatch, tmp_path, patched_voice ):
    """A full run (0 deselected) stays all_passed=True, filtered=False, and its
    header must NOT say FILTERED."""
    job = _make_job( test_types=[ "e2e" ] )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( job, "_run_suite", lambda st, pr: _unfiltered_result() )

    summary = asyncio.run( job._execute() )

    assert job.cost_summary[ "all_passed" ] is True
    assert job.cost_summary.get( "filtered", False ) is False
    assert job.cost_summary.get( "total_deselected", 0 ) == 0
    import pathlib
    assert "FILTERED" not in pathlib.Path( job.report_path ).read_text()
