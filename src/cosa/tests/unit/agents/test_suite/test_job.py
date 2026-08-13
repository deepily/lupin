"""
Unit tests for cosa/agents/test_suite/job.py (TestSuiteJob + module helpers).

Coverage target: 100% line + branch + function on job.py's production code
(lines 19-1133; the `quick_smoke_test`/`__main__` block is excluded via the
repo `[tool.coverage.report] exclude_also` regex).

Isolation contract:
    - NO subprocess is ever spawned — `subprocess.Popen` is replaced by an
      in-process `_FakeProcess` whose stdout/poll/wait/terminate/kill are
      scripted per test.
    - NO notification leaves the process — `voice_io.notify` and friends are
      boundary-mocked at the `cosa.agents.test_suite.voice_io` module.
    - NO real project files are touched — `cu.get_project_root()` is redirected
      to a pytest `tmp_path`, and `_write_stdout_log`'s canonical /tmp symlinks
      are redirected to `tmp_path` (or the method is stubbed) so the real
      `/tmp/<suite>-latest.log` symlinks are never mutated.
    - ZERO API spend, ZERO server contact.

This file harvests every assertion from the module's legacy `quick_smoke_test()`
(__init__ / id-format / last_question_asked / monopolize / is_cacheable /
attributes / class-constants / `_parse_junit_xml`) into real pytest, plus the
branches the smoke block never reached. The legacy `quick_smoke_test()` +
`if __name__ == "__main__":` block is therefore MARKED FOR DELETION (manager
gates the delete post-commit per campaign runbook §9).
"""
import os
import asyncio
import subprocess

import pytest

import cosa.agents.test_suite.job as job_mod
# Aliased to a non-"Test*" name so pytest doesn't try to collect the imported
# production class as a test case (PytestCollectionWarning).
from cosa.agents.test_suite.job import TestSuiteJob as TSJob, _expand_all, ALL_SUITE_COMPONENTS
from cosa.rest.job_state import JobState


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _FakeStdout:
    """Scripted stand-in for a subprocess stdout pipe.

    Requires:
        - lines is a list of strings (each a readline() result, "" = EOF)
    Ensures:
        - readline() pops the next scripted line, "" once exhausted
        - read() returns the configured `remaining` tail
        - readline_raises, when set, makes readline() raise that exception
    """
    def __init__( self, lines, remaining="", read_raises=None, readline_raises=None ):
        self._lines          = list( lines )
        self._remaining      = remaining
        self._read_raises    = read_raises
        self._readline_raises = readline_raises

    def readline( self ):
        if self._readline_raises is not None:
            raise self._readline_raises
        if self._lines:
            return self._lines.pop( 0 )
        return ""

    def read( self ):
        if self._read_raises is not None:
            raise self._read_raises
        return self._remaining


class _FakeProcess:
    """Scripted stand-in for subprocess.Popen's return value.

    Ensures:
        - poll() returns the configured returncode (never None → loop can break)
        - wait() raises TimeoutExpired when wait_timeout=True, else returns 0
        - terminate()/kill() record that they were called
    """
    def __init__( self, lines, returncode=0, remaining="", wait_timeout=False,
                  read_raises=None, readline_raises=None ):
        self.stdout           = _FakeStdout( lines, remaining, read_raises, readline_raises )
        self.returncode       = returncode
        self._wait_timeout    = wait_timeout
        self.terminate_called = False
        self.kill_called      = False

    def poll( self ):
        return self.returncode

    def terminate( self ):
        self.terminate_called = True

    def kill( self ):
        self.kill_called = True

    def wait( self, timeout=None ):
        if self._wait_timeout:
            raise subprocess.TimeoutExpired( cmd="bash", timeout=timeout )
        return 0


class _FakeConfigMgr:
    """ConfigurationManager double returning a scripted extra-args string."""
    def __init__( self, extra="" ):
        self._extra = extra

    def get( self, key, default="", return_type="string" ):
        return self._extra


@pytest.fixture
def patched_voice( monkeypatch ):
    """Boundary-mock the voice_io + cosa_interface seam so no notification leaves.

    Ensures:
        - voice_io.notify is an AsyncMock (awaitable, records calls)
        - reconfigure/set_job_id/clear_job_id are no-op Mocks
        - cosa_interface._get_sender_id returns a deterministic string
    """
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


@pytest.fixture( autouse=True )
def _isolate_artifact_root( tmp_path, monkeypatch ):
    """
    Every test in this module writes tier artifacts under a tmp root. AUTOUSE, and
    that is the load-bearing word.

    THE TWIN THAT WAS MISSED — row 5bf28e07's thesis, live
    ------------------------------------------------------
    Krishna landed exactly this fixture on `src/tests/unit/test_test_suite_job.py`
    (row fd0cd863) and ran the full unit tier green. THIS module is the same job's
    other test file, and it went red on the same change — 17 failures — because
    `src/cosa/tests/**` is referenced by NO GATE, so the tier he ran could not see
    it. Two test files for one unit, one gated and one not: the gated one reported
    health for both.

    That is `5bf28e07` demonstrated rather than argued, and it is the second reason
    this fixture is autouse rather than per-test: an opt-in fixture in an UNGATED
    module is a default nobody will ever be told they missed.

    `_ARTIFACT_DIR` is the single knob — the log file, the symlink and the junit XML
    all derive from it, so there is nothing left to redirect separately. Patching it
    also satisfies `attestation.artifact_root()`'s fail-closed refusal, which is what
    turned this red loudly instead of letting the tests keep writing the live path.
    """
    monkeypatch.setattr( TSJob, "_ARTIFACT_DIR", str( tmp_path ) )


def _make_job( **overrides ):
    """Build a TestSuiteJob with sensible test defaults; overrides win."""
    kwargs = dict(
        test_types = [ "integration", "e2e" ],
        user_id    = "user123",
        user_email = "test@test.com",
        session_id = "session456",
    )
    kwargs.update( overrides )
    return TSJob( **kwargs )


# =========================================================================== #
# _expand_all  (module helper)
# =========================================================================== #
def test_expand_all_passthrough_non_all():
    """Non-'all' entries pass through unchanged and in order."""
    assert _expand_all( [ "unit", "smoke" ] ) == [ "unit", "smoke" ]


def test_expand_all_expands_all_token():
    """'all' is replaced in place by ALL_SUITE_COMPONENTS."""
    assert _expand_all( [ "all" ] ) == ALL_SUITE_COMPONENTS


def test_expand_all_dedups_first_wins():
    """Duplicates (e.g. all + unit) are removed, first occurrence wins."""
    out = _expand_all( [ "all", "unit" ] )
    assert out == ALL_SUITE_COMPONENTS                       # unit already inside expansion
    assert out.count( "unit" ) == 1


def test_expand_all_does_not_mutate_input():
    """Input list is never mutated."""
    src = [ "all" ]
    _expand_all( src )
    assert src == [ "all" ]


# =========================================================================== #
# __init__  /  _filter_env_vars
# =========================================================================== #
def test_init_id_format_and_defaults():
    """ID is ts-prefixed, monopolize forced True, core attrs stored (harvest)."""
    job = _make_job( test_types=[ "integration", "e2e" ] )
    assert job.id_hash.startswith( "ts-" )
    assert job.monopolize is True
    assert job.is_cacheable is False
    assert job.test_types == [ "integration", "e2e" ]
    assert job.user_email == "test@test.com"
    assert job.state == JobState.PENDING
    assert job.dry_run is False
    assert job.pytest_args == []
    assert job.suite_results == {}
    assert job.cost_summary is None


def test_init_empty_test_types_falls_back_to_default():
    """An empty test_types list falls back to [integration, e2e]."""
    job = _make_job( test_types=[] )
    assert job.test_types == [ "integration", "e2e" ]


def test_init_pytest_args_none_becomes_empty_list():
    """pytest_args=None normalizes to []."""
    job = _make_job( pytest_args=None )
    assert job.pytest_args == []


def test_class_constants():
    """JOB_TYPE / JOB_PREFIX class constants (harvest)."""
    assert TSJob.JOB_TYPE   == "test_suite"
    assert TSJob.JOB_PREFIX == "ts"


def test_filter_env_vars_empty_returns_empty():
    """No env vars → empty dict, fast path."""
    assert TSJob._filter_env_vars( {} ) == {}


def test_filter_env_vars_allowlist_keeps_and_coerces( capsys ):
    """Allowlisted prefixes are kept and values coerced to str; others dropped."""
    out = TSJob._filter_env_vars( {
        "TFE_FOO"   : 1,
        "BFE_BAR"   : "x",
        "LUPIN_TEST_Z" : True,
        "EVIL"      : "nope",
    } )
    assert out == { "TFE_FOO": "1", "BFE_BAR": "x", "LUPIN_TEST_Z": "True" }
    assert "dropped env_vars" in capsys.readouterr().out      # warning printed for EVIL


def test_filter_env_vars_non_string_key_dropped( capsys ):
    """A non-string key is dropped (and reported)."""
    out = TSJob._filter_env_vars( { 42: "x", "TFE_OK": "y" } )
    assert out == { "TFE_OK": "y" }
    assert "dropped env_vars" in capsys.readouterr().out


def test_init_env_vars_filtered():
    """__init__ runs env_vars through the allowlist filter."""
    job = _make_job( env_vars={ "TFE_A": "1", "BAD": "2" } )
    assert job.env_vars == { "TFE_A": "1" }


def test_filter_env_vars_all_allowed_no_warning( capsys ):
    """When nothing is dropped, the warning print is skipped (no `dropped` branch)."""
    out = TSJob._filter_env_vars( { "TFE_A": "1", "BFE_B": "2" } )
    assert out == { "TFE_A": "1", "BFE_B": "2" }
    assert "dropped env_vars" not in capsys.readouterr().out


# =========================================================================== #
# from_config
# =========================================================================== #
def test_from_config_parses_types_and_args():
    """from_config splits comma types and whitespace pytest args."""
    class _Cfg:
        def get( self, key, default=None ):
            return { "test suite default types"       : "unit, smoke",
                     "test suite default pytest args" : "-v -k auth" }[ key ]
    job = TSJob.from_config( _Cfg(), "u", "e@e.com", "sess" )
    assert job.test_types  == [ "unit", "smoke" ]
    assert job.pytest_args == [ "-v", "-k", "auth" ]


def test_from_config_empty_args_yields_empty_list():
    """Empty default pytest-args string yields []."""
    class _Cfg:
        def get( self, key, default=None ):
            return "integration,e2e" if "types" in key else ""
    job = TSJob.from_config( _Cfg(), "u", "e@e.com", "sess" )
    assert job.pytest_args == []


# =========================================================================== #
# last_question_asked
# =========================================================================== #
def test_last_question_asked():
    """Display string joins suite names under a [Tests] label (harvest)."""
    job = _make_job( test_types=[ "integration", "e2e" ] )
    assert job.last_question_asked == "[Tests] integration, e2e"


# =========================================================================== #
# do_all  (success / cancelled / exception)
# =========================================================================== #
def test_do_all_success_sets_completed( monkeypatch ):
    """do_all bridges to _execute, stores result, transitions to COMPLETED."""
    job = _make_job( debug=True )

    async def _fake_exec():
        return "the summary"
    monkeypatch.setattr( job, "_execute", _fake_exec )

    out = job.do_all()
    assert out == "the summary"
    assert job.state == JobState.COMPLETED
    assert job.result == "the summary"
    assert job.answer_conversational == "the summary"
    assert job.started_at and job.completed_at


def test_do_all_success_no_debug_skips_duration_print( monkeypatch ):
    """Success with debug=False skips the duration print (branch 297->301)."""
    job = _make_job( debug=False )

    async def _fake_exec():
        return "ok"
    monkeypatch.setattr( job, "_execute", _fake_exec )
    assert job.do_all() == "ok"
    assert job.state == JobState.COMPLETED


def test_do_all_cancelled_uses_result_or_fallback( monkeypatch ):
    """When cancel is requested during execution, falls back to cancel message."""
    job = _make_job()

    async def _fake_exec():
        job._cancel_requested = True
        return ""                                            # empty → fallback branch
    monkeypatch.setattr( job, "_execute", _fake_exec )

    out = job.do_all()
    assert job.state == JobState.CANCELLED
    assert "cancelled" in out.lower()


def test_do_all_cancelled_keeps_partial_result( monkeypatch ):
    """A non-empty partial result is preserved on cancellation."""
    job = _make_job()

    async def _fake_exec():
        job._cancel_requested = True
        return "partial work"
    monkeypatch.setattr( job, "_execute", _fake_exec )

    assert job.do_all() == "partial work"
    assert job.state == JobState.CANCELLED


def test_do_all_exception_sets_failed_and_reraises( monkeypatch ):
    """An exception inside _execute → FAILED, error captured, re-raised."""
    job = _make_job()

    async def _boom():
        raise ValueError( "kaboom" )
    monkeypatch.setattr( job, "_execute", _boom )

    with pytest.raises( ValueError, match="kaboom" ):
        job.do_all()
    assert job.state == JobState.FAILED
    assert "ValueError" in job.error
    assert "kaboom" in job.answer_conversational


# =========================================================================== #
# _execute  (the orchestration path)
# =========================================================================== #
def _passing_result( log_path=None ):
    return {
        "passed": 5, "failed": 0, "skipped": 1, "errors": 0,
        "exit_code": 0, "log_path": log_path, "duration": 1.5,
    }


def test_execute_all_passed_writes_report_no_snapshot( monkeypatch, tmp_path, patched_voice ):
    """All-green run: report written (log read inline), no remediation snapshot."""
    log_file = tmp_path / "unit.log"
    log_file.write_text( "captured stdout\nline2\n" )

    job = _make_job( test_types=[ "unit" ], debug=True )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( job, "_run_suite", lambda st, pr: _passing_result( str( log_file ) ) )

    summary = asyncio.run( job._execute() )
    assert "ALL PASSED" in summary
    assert job.cost_summary[ "all_passed" ] is True
    # report file written under tmp io/test-suite (artifacts path is io-relative;
    # job.report_path is the absolute path)
    import pathlib
    report_abs = pathlib.Path( job.report_path )
    assert report_abs.exists()
    assert job.artifacts[ "report_path" ].startswith( "test-suite/" )
    assert "captured stdout" in report_abs.read_text()
    # no snapshot for an all-green run
    assert "remediation_snapshot_path" not in job.artifacts
    assert "unit_log" in job.artifacts                       # log_path present → artifact registered


def test_execute_failures_write_snapshot_and_crash_branches( monkeypatch, tmp_path, patched_voice ):
    """Failure run exercises: missing-log, crash-output, and clean-no-crash report branches."""
    job = _make_job( test_types=[ "integration", "e2e", "smoke" ] )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )

    results = {
        # s1: failed, log_path points at a NONEXISTENT file → read_text raises (FileNotFoundError branch)
        "integration": {
            "passed": 1, "failed": 2, "skipped": 0, "errors": 0,
            "exit_code": 1, "log_path": str( tmp_path / "missing.log" ), "duration": 3.0,
            "failure_details": [ { "name": "t_a", "type": "FAILED" } ],
        },
        # s2: failed, no log_path but a startup crash tail (crash-present branch in report + abstract)
        "e2e": {
            "passed": 0, "failed": 0, "skipped": 0, "errors": 1,
            "exit_code": 2, "log_path": None, "duration": 0.2,
            "startup_crash_output": "Traceback: boom",
            "failure_details": [ { "name": "t_b", "type": "ERROR" } ],
        },
        # s3: passed, no log_path, no crash (crash-absent / log-absent branch)
        "smoke": {
            "passed": 3, "failed": 0, "skipped": 0, "errors": 0,
            "exit_code": 0, "log_path": None, "duration": 0.5,
        },
    }
    monkeypatch.setattr( job, "_run_suite", lambda st, pr: results[ st ] )

    summary = asyncio.run( job._execute() )
    assert "FAILURES DETECTED" in summary
    # remediation snapshot written, with both failure_details merged in
    snap = job.artifacts[ "remediation_snapshot" ]
    assert snap[ "summary" ][ "all_passed" ] is False
    assert len( snap[ "failures" ] ) == 2
    assert { f[ "suite" ] for f in snap[ "failures" ] } == { "integration", "e2e" }
    # abstract carries the crash tail for s2
    assert "STARTUP CRASH" in job.artifacts[ "abstract" ]
    # report records the missing-log fallback line for s1
    import pathlib
    assert "log file not available" in pathlib.Path( job.report_path ).read_text()


# =========================================================================== #
# _classify_outcome  (bug 89bfcc8f — non-execution is NOT a failure)
# =========================================================================== #
@pytest.mark.parametrize( "counts, expected", [
    ( ( 0, 0, 0, 0 ), "NOT EXECUTED" ),                       # nothing collected → non-execution
    ( ( 0, 0, 0, 3 ), "PASSED" ),                             # all skipped, but tests were collected
    ( ( 5, 0, 0, 1 ), "PASSED" ),                             # ran clean
    ( ( 4, 1, 0, 0 ), "FAILED" ),                             # a real failure
    ( ( 0, 0, 1, 0 ), "FAILED" ),                             # a real error (e.g. subprocess crash)
    # not_executed (5th arg) — a tier that never ran (bug 89bfcc8f):
    ( ( 0, 0, 0, 0, 0 ), "NOT EXECUTED" ),                    # explicit 5-arg all-zero
    ( ( 3, 0, 0, 0, 0 ), "PASSED" ),                          # every tier ran, clean
    ( ( 0, 0, 0, 0, 2 ), "NOT EXECUTED" ),                    # only not-executed tiers
    ( ( 2, 0, 0, 0, 1 ), "NOT EXECUTED" ),                    # some passed but a tier didn't run → not green
    ( ( 2, 1, 0, 0, 1 ), "FAILED" ),                          # a genuine failure dominates a not-run tier
    ( ( 0, 0, 1, 0, 1 ), "FAILED" ),                          # a genuine error dominates a not-run tier
] )
def test_classify_outcome( counts, expected ):
    """Zero-count is NOT EXECUTED; skipped-only counts as collected; failed/errors →
    FAILED; a not-executed tier blocks a clean pass without inflating failures."""
    assert TSJob._classify_outcome( *counts ) == expected


def _zero_result( log_path=None ):
    """A suite that collected nothing (no JUnit XML produced) — the false-red case."""
    return {
        "passed": 0, "failed": 0, "skipped": 0, "errors": 0,
        "exit_code": 1, "log_path": log_path, "duration": 0.3,
    }


def test_execute_non_execution_reports_not_run_not_failed( monkeypatch, tmp_path, patched_voice ):
    """A 0/0/0/0 suite is announced + summarized as NOT EXECUTED, never FAILED, and writes no snapshot."""
    job = _make_job( test_types=[ "presentation" ] )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( job, "_run_suite", lambda st, pr: _zero_result() )

    summary = asyncio.run( job._execute() )

    # Overall banner: NOT EXECUTED, not the false-red FAILURES DETECTED
    assert "NOT EXECUTED" in summary
    assert "FAILURES DETECTED" not in summary

    # Per-suite spoken line says NOT EXECUTED, never FAILED
    spoken = [ c.args[ 0 ] for c in patched_voice.call_args_list if c.args ]
    per_suite = [ m for m in spoken if m.startswith( "presentation:" ) ]
    assert per_suite and "NOT EXECUTED" in per_suite[ 0 ]
    assert "FAILED" not in per_suite[ 0 ]

    # Report table + abstract render "NOT RUN", not "FAIL"; no remediation snapshot
    import pathlib
    assert "presentation — NOT RUN" in pathlib.Path( job.report_path ).read_text()
    assert "NOT RUN" in job.artifacts[ "abstract" ]
    assert "remediation_snapshot_path" not in job.artifacts
    assert job.cost_summary[ "all_passed" ] is False


def _not_executed_tier_result( log_path=None ):
    """A multi-tier run where a tier PASSED but another NEVER RAN (bug 89bfcc8f):
    one passed, zero failed/errored, one not-executed. Not green, not a failure."""
    return {
        "passed": 1, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 1,
        "exit_code": 1, "log_path": log_path, "duration": 0.5,
    }


def test_execute_not_executed_tier_reports_not_run_not_failed( monkeypatch, tmp_path, patched_voice ):
    """A tier that never ran (with another that passed) reports NOT EXECUTED overall
    — never the false-red FAILURES DETECTED, and never a clean pass (bug 89bfcc8f)."""
    job = _make_job( test_types=[ "presentation" ] )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( job, "_run_suite", lambda st, pr: _not_executed_tier_result() )

    summary = asyncio.run( job._execute() )

    # Overall: NOT EXECUTED — not FAILURES DETECTED, not ALL PASSED
    assert "NOT EXECUTED" in summary
    assert "FAILURES DETECTED" not in summary
    assert "ALL PASSED" not in summary

    # Per-suite spoken line names the not-executed count and reads NOT EXECUTED
    spoken = [ c.args[ 0 ] for c in patched_voice.call_args_list if c.args ]
    per_suite = [ m for m in spoken if m.startswith( "presentation:" ) ]
    assert per_suite and "NOT EXECUTED" in per_suite[ 0 ]
    assert "1 not executed" in per_suite[ 0 ]

    # Report table carries the Not-executed row + NOT RUN icon; not green
    import pathlib
    report = pathlib.Path( job.report_path ).read_text()
    assert "presentation — NOT RUN" in report
    assert "| Not executed | 1 |" in report
    assert job.cost_summary[ "all_passed" ] is False
    assert job.cost_summary[ "total_not_executed" ] == 1


def test_execute_expands_all_with_debug( monkeypatch, tmp_path, patched_voice, capsys ):
    """test_types=['all'] + debug logs the expansion and runs each component."""
    job = _make_job( test_types=[ "all" ], debug=True )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    seen = []
    def _fake( st, pr ):
        seen.append( st )
        return _passing_result()
    monkeypatch.setattr( job, "_run_suite", _fake )

    asyncio.run( job._execute() )
    assert seen == ALL_SUITE_COMPONENTS
    assert "Expanded" in capsys.readouterr().out


def test_execute_cancel_mid_loop_breaks( monkeypatch, tmp_path, patched_voice ):
    """A cancel raised during the suite loop stops further suites."""
    job = _make_job( test_types=[ "unit", "smoke" ] )
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    calls = []
    def _fake( st, pr ):
        calls.append( st )
        job._cancel_requested = True                         # cancel after first suite
        return _passing_result()
    monkeypatch.setattr( job, "_run_suite", _fake )

    asyncio.run( job._execute() )
    assert calls == [ "unit" ]                               # second suite never ran


def test_execute_dry_run_delegates( monkeypatch, tmp_path, patched_voice ):
    """dry_run=True routes through the dry-run branch and returns its summary."""
    job = _make_job( test_types=[ "unit", "smoke" ], dry_run=True )
    summary = asyncio.run( job._execute() )
    assert "Dry run complete" in summary
    assert job.cost_summary[ "mode" ] == "dry_run"
    assert set( job.suite_results.keys() ) == { "unit", "smoke" }


# =========================================================================== #
# _execute_dry_run  (direct)
# =========================================================================== #
def test_execute_dry_run_direct_populates_artifacts( monkeypatch, patched_voice ):
    """Dry run sets mock results, cost summary, and abstract; clears job_id."""
    job = _make_job( test_types=[ "integration" ], dry_run=True, debug=True )
    import cosa.agents.test_suite.voice_io as vio
    import cosa.agents.test_suite.cosa_interface as ci

    out = asyncio.run( job._execute_dry_run( vio, ci ) )
    assert "Dry run complete" in out
    assert job.suite_results[ "integration" ][ "exit_code" ] == 0
    assert job.artifacts[ "cost_summary" ][ "suites_run" ] == 1
    vio.clear_job_id.assert_called()                         # finally block ran


# =========================================================================== #
# _run_suite  (subprocess orchestration — fully mocked)
# =========================================================================== #
@pytest.fixture
def no_real_log( monkeypatch ):
    """Stub _write_stdout_log so _run_suite tests never touch /tmp symlinks."""
    monkeypatch.setattr(
        job_mod.TestSuiteJob, "_write_stdout_log",
        classmethod( lambda cls, suite, text: "/tmp/fake-test.log" ),
    )


def _patch_config_mgr( monkeypatch, extra="" ):
    import cosa.config.configuration_manager as cfg
    monkeypatch.setattr( cfg, "ConfigurationManager", lambda *a, **k: _FakeConfigMgr( extra ) )


def test_run_suite_unknown_type_returns_error():
    """An unknown suite type short-circuits to an error dict."""
    job = _make_job()
    res = job._run_suite( "bogus", "/proj" )
    assert res[ "exit_code" ] == 1
    assert "Unknown suite type" in res[ "error" ]


def test_run_suite_script_missing_returns_error( monkeypatch ):
    """A known type whose script file is absent returns a not-found error."""
    job = _make_job()
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: False )
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == 1
    assert "Script not found" in res[ "error" ]


def test_run_suite_normal_completion( monkeypatch, no_real_log ):
    """Happy path: --bg stripped, junit injected, poll loop drains, exit 0."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    fake = _FakeProcess( lines=[ "line1\n", "line2\n" ], returncode=0 )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job( pytest_args=[ "--bg", "-v" ], verbose=True, debug=True )
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == 0
    assert res[ "errors" ] == 0
    assert "startup_crash_output" not in res                 # exit 0 → no crash tail


def test_run_suite_appends_ini_extra_args( monkeypatch, no_real_log ):
    """Per-suite extra pytest args from INI are appended (debug logs them)."""
    _patch_config_mgr( monkeypatch, extra="--auto-proxy --cost-cap-usd 1" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    captured = {}
    def _popen( cmd, **k ):
        captured[ "cmd" ] = cmd
        return _FakeProcess( lines=[ "x\n" ], returncode=0 )
    monkeypatch.setattr( job_mod.subprocess, "Popen", _popen )

    job = _make_job( debug=True )
    job._run_suite( "smoke", "/proj" )
    assert "--auto-proxy" in captured[ "cmd" ]


def test_run_suite_ini_extra_args_appended_no_debug( monkeypatch, no_real_log ):
    """Extra args appended with debug=False skips the debug print (branch 732->746)."""
    _patch_config_mgr( monkeypatch, extra="--verbose" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    captured = {}
    def _popen( cmd, **k ):
        captured[ "cmd" ] = cmd
        return _FakeProcess( lines=[ "x\n" ], returncode=0 )
    monkeypatch.setattr( job_mod.subprocess, "Popen", _popen )

    job = _make_job( debug=False )
    job._run_suite( "smoke", "/proj" )
    assert "--verbose" in captured[ "cmd" ]


def test_run_suite_ini_extra_args_whitespace_only_not_appended( monkeypatch, no_real_log ):
    """A whitespace-only INI value yields no extra args (branch 730->746)."""
    _patch_config_mgr( monkeypatch, extra="   " )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    captured = {}
    def _popen( cmd, **k ):
        captured[ "cmd" ] = cmd
        return _FakeProcess( lines=[ "x\n" ], returncode=0 )
    monkeypatch.setattr( job_mod.subprocess, "Popen", _popen )

    job = _make_job()
    res = job._run_suite( "smoke", "/proj" )
    assert res[ "exit_code" ] == 0
    # only the junit-xml flag (smoke supports it) was appended, no INI extras
    assert all( not a.startswith( "--verbose" ) for a in captured[ "cmd" ] )


def test_run_suite_ini_read_failure_is_nonfatal( monkeypatch, no_real_log, capsys ):
    """A ConfigurationManager failure is logged and the suite still runs."""
    import cosa.config.configuration_manager as cfg
    def _boom( *a, **k ):
        raise RuntimeError( "ini unavailable" )
    monkeypatch.setattr( cfg, "ConfigurationManager", _boom )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    monkeypatch.setattr( job_mod.subprocess, "Popen",
                         lambda *a, **k: _FakeProcess( lines=[ "x\n" ], returncode=0 ) )

    job = _make_job()
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == 0
    assert "Could not load extra pytest args" in capsys.readouterr().out


def test_run_suite_websocket_uses_stdout_fallback( monkeypatch, no_real_log ):
    """Non-pytest websocket suite (no junit) falls back to stdout parsing."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    stdout_lines = [ "Total Tests: 50\n", "Passed: 50\n", "Failed: 0\n",
                     "ALL SMOKE TESTS PASSED!\n" ]
    monkeypatch.setattr( job_mod.subprocess, "Popen",
                         lambda *a, **k: _FakeProcess( lines=stdout_lines, returncode=0 ) )

    job = _make_job()
    res = job._run_suite( "websocket", "/proj" )
    assert res[ "passed" ] == 50
    assert res[ "failed" ] == 0


def test_run_suite_websocket_unrecognized_stdout_keeps_zeros( monkeypatch, no_real_log ):
    """Websocket suite whose stdout doesn't parse → fallback None, counts stay zero (877->880)."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    monkeypatch.setattr( job_mod.subprocess, "Popen",
                         lambda *a, **k: _FakeProcess( lines=[ "no markers here\n" ], returncode=0 ) )

    job = _make_job()
    res = job._run_suite( "websocket", "/proj" )
    assert res[ "passed" ] == 0 and res[ "failed" ] == 0


def test_run_suite_nonzero_exit_no_tests_captures_crash_tail( monkeypatch, no_real_log ):
    """Non-zero exit with zero parsed tests records a startup_crash_output tail."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    monkeypatch.setattr( job_mod.subprocess, "Popen",
                         lambda *a, **k: _FakeProcess( lines=[ "ImportError: boom\n" ], returncode=1 ) )

    job = _make_job( debug=True )
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == 1
    assert "ImportError" in res[ "startup_crash_output" ]


def test_run_suite_cancel_terminates_cleanly( monkeypatch, no_real_log ):
    """A pre-set cancel flag terminates the process and returns the cancel dict."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    fake = _FakeProcess( lines=[ "x\n" ], returncode=0 )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job()
    job._cancel_requested = True
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == -1
    assert res[ "error" ] == "Cancelled by user"
    assert fake.terminate_called and not fake.kill_called


def test_run_suite_cancel_kill_on_wait_timeout( monkeypatch, no_real_log ):
    """Cancel where wait() times out escalates terminate → kill."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    fake = _FakeProcess( lines=[ "x\n" ], returncode=0, wait_timeout=True )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job()
    job._cancel_requested = True
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == -1
    assert fake.terminate_called and fake.kill_called


def test_run_suite_timeout_drains_remaining( monkeypatch, no_real_log ):
    """Exceeding the per-suite budget kills the process and synthesizes an ERROR."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    # start_time = 0, then loop sees elapsed = 10000 > 180s unit budget
    monkeypatch.setattr( job_mod.time, "monotonic", _seq( [ 0, 10_000, 10_000 ] ) )
    fake = _FakeProcess( lines=[ "slow\n" ], returncode=0, remaining="tail bytes\n" )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job( debug=True )
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == -2
    assert res[ "errors" ] == 1
    assert "Timeout" in res[ "error" ]
    assert res[ "failure_details" ][ 0 ][ "type" ] == "ERROR"
    assert fake.terminate_called


def test_run_suite_timeout_empty_drain( monkeypatch, no_real_log ):
    """Timeout where the drained read() is empty skips the append (branch 818->823)."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    monkeypatch.setattr( job_mod.time, "monotonic", _seq( [ 0, 10_000, 10_000 ] ) )
    fake = _FakeProcess( lines=[ "slow\n" ], returncode=0, remaining="" )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job()
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == -2
    assert fake.terminate_called


def test_run_suite_timeout_kill_and_drain_oserror( monkeypatch, no_real_log ):
    """Timeout path: wait() times out → kill; draining read() OSError is swallowed."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    monkeypatch.setattr( job_mod.time, "monotonic", _seq( [ 0, 10_000, 10_000 ] ) )
    fake = _FakeProcess( lines=[ "slow\n" ], returncode=0, wait_timeout=True,
                         read_raises=OSError( "pipe closed" ) )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job()
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == -2
    assert fake.terminate_called and fake.kill_called


def test_run_suite_popen_raises_nameerror_guard( monkeypatch, no_real_log ):
    """If Popen itself raises, stdout_lines is undefined → NameError guard → ''. """
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    def _boom( *a, **k ):
        raise OSError( "cannot spawn" )
    monkeypatch.setattr( job_mod.subprocess, "Popen", _boom )

    job = _make_job()
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == 1
    assert res[ "errors" ] == 1
    assert "cannot spawn" in res[ "error" ]
    assert res[ "failure_details" ][ 0 ][ "name" ] == "exception"


def test_run_suite_exception_after_stdout_defined( monkeypatch, no_real_log ):
    """An exception after stdout_lines is bound → join('') succeeds (no NameError)."""
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    fake = _FakeProcess( lines=[], returncode=0,
                         readline_raises=RuntimeError( "read blew up" ) )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job()
    res = job._run_suite( "unit", "/proj" )
    assert res[ "exit_code" ] == 1
    assert "read blew up" in res[ "error" ]


def _seq( values ):
    """Return a callable yielding `values` in order then repeating the last."""
    it = iter( values )
    last = { "v": values[ -1 ] }
    def _next():
        try:
            last[ "v" ] = next( it )
        except StopIteration:
            pass
        return last[ "v" ]
    return _next


# =========================================================================== #
# _write_stdout_log
# =========================================================================== #
def test_write_stdout_log_unknown_suite_returns_none():
    """Unknown suite key → no write, returns None."""
    assert TSJob._write_stdout_log( "bogus", "text" ) is None


def test_write_stdout_log_empty_text_returns_none():
    """Empty stdout → nothing written, returns None."""
    assert TSJob._write_stdout_log( "unit", "" ) is None


def test_write_stdout_log_writes_file_and_symlink( monkeypatch, tmp_path ):
    """
    Valid call writes a timestamped log and refreshes the canonical symlink.

    ⚠️ THIS TEST USED TO DOCUMENT `fd0cd863` IN ITS OWN DOCSTRING. Verbatim, before
    2026-07-27: *"the timestamped actual-log still lands in /tmp (hard-coded in the
    method) and is cleaned up here."* It patched `_LOG_SYMLINKS` alone, which moved
    the symlink and left the real file writing into the live artifact directory —
    the two-authorities defect, stated as a known limitation and then shipped.
    "Cleaned up here" was also conditional: a failure before the `finally` left the
    file behind, which is how `"first run"` came to be sitting in the container's
    live `/tmp` when Krishna looked.

    Now `_ARTIFACT_DIR` is the single knob and the autouse fixture redirects it, so
    the log, the symlink and the junit XML move together. The assertion below is
    against the ISOLATED root — the old `startswith( "/tmp/unit-" )` form required
    the pollution in order to pass.
    """
    import pathlib

    path = TSJob._write_stdout_log( "unit", "hello log\n" )
    symlink = pathlib.Path( TSJob._ARTIFACT_DIR ) / "unit-latest.log"

    assert path is not None
    assert path.startswith( os.path.join( str( tmp_path ), "unit-" ) )
    assert pathlib.Path( path ).read_text() == "hello log\n"
    assert symlink.is_symlink()
    assert pathlib.Path( symlink ).resolve() == pathlib.Path( path ).resolve()


# =========================================================================== #
# _synth_failure_detail
# =========================================================================== #
def test_synth_failure_detail_shape():
    """Synthesized failure detail matches the junit-parsed entry shape."""
    d = TSJob._synth_failure_detail( "unit", "timeout", 12.3, "msg", "tb here" )
    assert d[ "classname" ] == "TestSuiteJob.unit"
    assert d[ "name" ] == "timeout"
    assert d[ "type" ] == "ERROR"
    assert d[ "message" ] == "msg"
    assert d[ "traceback" ] == "tb here"


def test_synth_failure_detail_empty_traceback_defaults():
    """Empty traceback text defaults to a placeholder string."""
    d = TSJob._synth_failure_detail( "e2e", "exception", 1.0, "m", "" )
    assert d[ "traceback" ] == "(no output captured)"


# =========================================================================== #
# _parse_junit_xml
# =========================================================================== #
def test_parse_junit_xml_none_path_returns_zeros():
    """A None/empty path (non-pytest suite) returns zero counts."""
    assert TSJob._parse_junit_xml( None ) == {
        "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_parse_junit_xml_missing_file_returns_zeros():
    """A nonexistent file returns zeros (FileNotFoundError swallowed)."""
    parsed = TSJob._parse_junit_xml( "/tmp/does-not-exist-xyz.xml" )
    assert parsed[ "passed" ] == 0 and parsed[ "failed" ] == 0


def test_parse_junit_xml_root_is_testsuite( tmp_path ):
    """A bare <testsuite> root parses counts correctly (harvest)."""
    p = tmp_path / "j.xml"
    p.write_text(
        '<?xml version="1.0"?>'
        '<testsuite name="pytest" errors="1" failures="3" skipped="32" tests="231"></testsuite>'
    )
    parsed = TSJob._parse_junit_xml( str( p ) )
    assert parsed == { "passed": 195, "failed": 3, "skipped": 32, "errors": 1,
                       "not_executed": 0, "failure_details": [] }


def test_parse_junit_xml_nested_with_failure_details( tmp_path ):
    """<testsuites> wrapper + per-testcase failure/error/clean details extracted."""
    p = tmp_path / "j.xml"
    p.write_text(
        '<testsuites><testsuite tests="5" failures="1" errors="1" skipped="0">'
        '<testcase classname="C" name="t1"><failure message="boom">tb1</failure></testcase>'
        '<testcase classname="C" name="t2"><error message="err">tb2</error></testcase>'
        '<testcase classname="C" name="t3"></testcase>'
        '<testcase classname="C" name="t4"></testcase>'
        '<testcase classname="C" name="t5"></testcase>'
        '</testsuite></testsuites>'
    )
    parsed = TSJob._parse_junit_xml( str( p ) )
    assert parsed[ "passed" ] == 3
    fd = parsed[ "failure_details" ]
    assert len( fd ) == 2
    assert fd[ 0 ][ "type" ] == "FAILED" and fd[ 0 ][ "traceback" ] == "tb1"
    assert fd[ 1 ][ "type" ] == "ERROR"  and fd[ 1 ][ "message" ]  == "err"


def test_parse_junit_xml_no_testsuite_element( tmp_path ):
    """A root with no <testsuite> child leaves counts at zero."""
    p = tmp_path / "j.xml"
    p.write_text( "<other></other>" )
    parsed = TSJob._parse_junit_xml( str( p ) )
    assert parsed == { "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_parse_junit_xml_parse_error( tmp_path ):
    """Malformed XML is caught (ParseError) and returns zeros."""
    p = tmp_path / "j.xml"
    p.write_text( "<testsuite not-closed" )
    parsed = TSJob._parse_junit_xml( str( p ) )
    assert parsed[ "passed" ] == 0


# =========================================================================== #
# _parse_non_pytest_stdout
# =========================================================================== #
def test_parse_non_pytest_stdout_non_websocket_is_none():
    """Only non-pytest runners (websocket/typescript/presentation) are recognized;
    a pytest suite like 'unit' returns None (it uses the junit path, not stdout)."""
    assert TSJob._parse_non_pytest_stdout( "unit", "Total Tests: 5" ) is None


def test_parse_non_pytest_stdout_empty_is_none():
    """Empty stdout returns None."""
    assert TSJob._parse_non_pytest_stdout( "websocket", "" ) is None


def test_parse_non_pytest_stdout_no_markers_is_none():
    """Stdout without any recognized marker returns None."""
    assert TSJob._parse_non_pytest_stdout( "websocket", "nothing useful here" ) is None


def test_parse_non_pytest_stdout_full_counts():
    """Total/Passed/Failed all present → parsed directly."""
    out = TSJob._parse_non_pytest_stdout(
        "websocket", "Total Tests: 50\nPassed: 48\nFailed: 2\n" )
    assert out == { "passed": 48, "failed": 2, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_parse_non_pytest_stdout_passed_failed_no_total():
    """Passed+Failed present, no Total → total reconstructed (unused) but counts kept."""
    out = TSJob._parse_non_pytest_stdout(
        "websocket", "Passed: 7\nFailed: 3\n" )
    assert out == { "passed": 7, "failed": 3, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_parse_non_pytest_stdout_total_only_all_passed():
    """Only Total + the ALL-PASSED marker → infer all passed."""
    out = TSJob._parse_non_pytest_stdout(
        "websocket", "Total Tests: 12\nALL SMOKE TESTS PASSED\n" )
    assert out == { "passed": 12, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_parse_non_pytest_stdout_total_only_no_marker_is_none():
    """Only Total with no PASS marker is ambiguous → None (preserve zero-counts)."""
    out = TSJob._parse_non_pytest_stdout(
        "websocket", "Total Tests: 12\n" )
    assert out is None


# --- presentation: multi-tier orchestrator parsed from its stdout summary (bug 89bfcc8f) ---
def test_presentation_not_in_junit_supporting_suites():
    """presentation must NOT claim junit support — its runner ignores --junit-xml,
    so the file is never produced and _parse_junit_xml would raise FileNotFoundError
    (mis-reported as a 0/0/0/0 run). It is parsed from stdout instead."""
    from cosa.agents.test_suite.job import SUITES_SUPPORTING_JUNIT_XML
    assert "presentation" not in SUITES_SUPPORTING_JUNIT_XML


def test_parse_non_pytest_stdout_presentation_tier_summary():
    """The presentation tier summary (Total: N tiers / Passed: N / Failed: N) parses to tier counts."""
    stdout = (
        "  PRESENTATION REGRESSION RESULTS\n"
        "  Total:  3 tiers\n"
        "  Passed: 2\n"
        "  Failed: 1\n"
        "  Failed tiers: opus-full\n"
    )
    out = TSJob._parse_non_pytest_stdout( "presentation", stdout )
    assert out == { "passed": 2, "failed": 1, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_parse_non_pytest_stdout_presentation_all_tiers_pass():
    """A clean presentation run (Failed: 0) parses to passed-only."""
    out = TSJob._parse_non_pytest_stdout(
        "presentation", "  Total:  2 tiers\n  Passed: 2\n  Failed: 0\n" )
    assert out == { "passed": 2, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_parse_non_pytest_stdout_presentation_empty_is_none():
    """Empty presentation stdout returns None (preserve zero-counts → NOT EXECUTED)."""
    assert TSJob._parse_non_pytest_stdout( "presentation", "" ) is None


def test_parse_non_pytest_stdout_presentation_not_executed_tier():
    """A tier that never ran surfaces as not_executed, NOT folded into failed
    (bug 89bfcc8f — the mixed real-fail + not-run shape from the 2026-08-13 run)."""
    stdout = (
        "  PRESENTATION REGRESSION RESULTS\n"
        "  Total:  2 tiers\n"
        "  Passed: 0\n"
        "  Failed: 1\n"
        "  Not executed: 1\n"
        "  Failed tiers: render-only\n"
        "  Not executed tiers: sonnet-full\n"
    )
    out = TSJob._parse_non_pytest_stdout( "presentation", stdout )
    assert out == { "passed": 0, "failed": 1, "skipped": 0, "errors": 0, "not_executed": 1 }


def test_parse_non_pytest_stdout_presentation_only_not_executed():
    """A run where every tier failed to launch (Not executed only) parses with a
    zero failed count — so _classify_outcome reads NOT EXECUTED, never FAILED."""
    stdout = "  Total:  2 tiers\n  Passed: 0\n  Failed: 0\n  Not executed: 2\n"
    out = TSJob._parse_non_pytest_stdout( "presentation", stdout )
    assert out == { "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 2 }
    assert TSJob._classify_outcome( **out ) == "NOT EXECUTED"


def test_parse_non_pytest_stdout_presentation_no_markers_is_none():
    """Presentation stdout without the tier summary returns None."""
    assert TSJob._parse_non_pytest_stdout( "presentation", "nothing useful here" ) is None


# ---------------------------------------------------------------------------
# Bug 8b93bcf5 follow-up — a DEAD READER THREAD must not read as a clean run.
#
# `69295c25` moved readline() off the main path into a daemon reader thread to
# stop a silent child from parking the poll loop. The move was right; its error
# path was not. The thread's `finally` posted the EOF sentinel on ANY exit, so a
# crashed reader was indistinguishable from clean EOF: the loop fell through to
# `exit_code = process.returncode` and reported a tier whose output was never
# read as 0 passed / 0 failed / 0 errors / exit 0 — GREEN. Strictly worse than
# the 0/0/0/1 that 8b93bcf5 was filed about, because that at least said "error".
#
# These are the controls. Each fails if the crash sentinel is removed, and the
# predicted failure is stated so a red here is diagnosable rather than merely red.
# ---------------------------------------------------------------------------

def test_reader_thread_crash_is_not_reported_as_success( monkeypatch, no_real_log ):
    """
    A reader-thread crash must surface as errors=1 / exit_code=1.

    Remove the crash sentinel and this fails as `assert 0 == 1` on exit_code —
    the exact shape the regression wore for a day before anyone ran this tree.
    """
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    fake = _FakeProcess( lines=[], returncode=0,
                         readline_raises=RuntimeError( "reader blew up" ) )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job()
    res = job._run_suite( "unit", "/proj" )

    assert res[ "exit_code" ] == 1,  "a crashed reader must not report the child's exit code"
    assert res[ "errors"    ] == 1,  "a crashed reader must be counted as an error"
    assert "reader blew up" in res[ "error" ], "the original exception must survive to the caller"


def test_reader_crash_marker_is_distinct_from_the_eof_sentinel():
    """
    The marker must not BE the EOF sentinel — that identity was the whole bug.

    Without this, someone 'simplifying' the marker back to None would restore
    the silence and every other test here would stay green.
    """
    crash = job_mod._StdoutReaderCrash( ValueError( "x" ), "tb text" )
    assert crash is not None
    assert not isinstance( crash, str ), "a marker that is a str would be appended to the log as output"
    assert crash.exc.args == ( "x", )
    assert crash.tb == "tb text"


def test_clean_eof_still_reports_the_childs_own_exit_code( monkeypatch, no_real_log ):
    """
    CONTROL IN THE OTHER DIRECTION: a healthy run must be unaffected.

    A fix that raised on every EOF would pass the crash tests above while
    breaking every real run — this is the arm that catches it.
    """
    _patch_config_mgr( monkeypatch, extra="" )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    fake = _FakeProcess( lines=[ "ok\n" ], returncode=0 )
    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: fake )

    job = _make_job()
    res = job._run_suite( "unit", "/proj" )

    assert res[ "exit_code" ] == 0
    assert res.get( "error" ) in ( None, "" ) or "reader" not in str( res.get( "error" ) )
