"""
Unit tests for TestSuiteJob.

Tests job creation, configuration, pytest output parsing, state transitions,
dry run mode, and voice_io integration.
"""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from cosa.agents.test_suite.job import (
    TestSuiteJob,
    ALL_SUITE_COMPONENTS,
    SUITES_SUPPORTING_JUNIT_XML,
    _expand_all,
)
from cosa.rest.job_state import JobState


# ═══════════════════════════════════════════════════════════════════════════════
# Shared stubs
# ═══════════════════════════════════════════════════════════════════════════════

# Bug d8a23fca. Patching `job.cu.get_project_root` does NOT scope to job.py — `cu`
# is the shared `cosa.utils.util` module object, so the patch rewrites project-root
# resolution for every consumer in the process. do_all() then reaches
# _preflight_assert_exclusive_test_db, which lazily imports lupin_app.main, whose
# module-level ConfigurationManager resolves lupin-app.ini under the mocked tmpdir
# and dies with "That file doesn't exist".
#
# It only bites where the engine IS lupin_db_test: off the test DB the preflight
# returns before the import, so on the dev host these tests pass having never
# executed the branch at all. Their green there was vacuous, not sound — and inside
# the container four of the six were ALSO green, masked by an earlier test importing
# lupin_app.main under the real root. Run alone, all six fail.
#
# The preflight has its own six tests (TestPreflightExclusivity), so a do_all() test
# that only needs the io_base pin stubs it — the idiom
# test_preflight_fires_before_first_suite already uses. `new` is given explicitly, so
# no extra mock argument is injected and signatures stay put.
_stub_preflight = patch.object(
    TestSuiteJob, "_preflight_assert_exclusive_test_db", lambda self: None
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture( autouse=True )
def _isolate_artifact_root( tmp_path, monkeypatch ):
    """
    Every test in this module writes tier artifacts under a tmp root. AUTOUSE, and
    that is the load-bearing word.

    ROW fd0cd863. This module exercises the real `_run_suite` / `_write_stdout_log`
    paths, and those wrote into the LIVE artifact directory. Measured in the running
    test container 2026-07-27:

        /tmp/integration-latest.log  ->  line-1 line-2 line-3 line-4 line-5 line-6
        /tmp/unit-20260727-185252.log -> "first run"

    Fixture strings, sitting in the path a human triaging a scheduled run opens, with
    a plausible timestamped filename and a correctly-rotated symlink. Not absent —
    present and WRONG, which is the worse polarity: absence prompts a question, a
    convincing wrong answer ends one.

    ⛔ AUTOUSE RATHER THAN PER-TEST, DELIBERATELY. One test here already redirected
    `_LOG_SYMLINKS` by hand and was still writing the real log file, because the
    symlink and the file were separately configurable. An opt-in fixture has the same
    shape as that partial fix and as the `_PG_ISOLATION_MODULES` allowlist deleted on
    2026-07-27: every test added later is un-isolated by default and nothing says so.
    Autouse inverts the default, so a new test cannot reach the live path by omission.
    """
    monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )


@pytest.fixture
def job():
    """Create a default TestSuiteJob for testing."""
    return TestSuiteJob(
        test_types = [ "integration", "e2e" ],
        user_id    = "user-123",
        user_email = "test@test.com",
        session_id = "wise-penguin",
    )


@pytest.fixture
def single_suite_job():
    """Create a single-suite TestSuiteJob."""
    return TestSuiteJob(
        test_types = [ "integration" ],
        user_id    = "user-123",
        user_email = "test@test.com",
        session_id = "wise-penguin",
    )


@pytest.fixture
def dry_run_job():
    """Create a dry-run TestSuiteJob."""
    return TestSuiteJob(
        test_types = [ "integration", "e2e" ],
        user_id    = "user-123",
        user_email = "test@test.com",
        session_id = "wise-penguin",
        dry_run    = True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Job Creation Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobCreation:
    """Tests for TestSuiteJob instantiation and defaults."""

    def test_default_creation( self, job ):
        """Job with both suites should have correct defaults."""
        assert job.test_types == [ "integration", "e2e" ]
        assert job.monopolize == True
        assert job.dry_run == False
        assert job.pytest_args == []
        assert job.state == JobState.PENDING
        assert job.suite_results == {}
        # Per-run TFE override defaults to None (use INI default).
        assert job.auto_fix_on_failure is None

    def test_auto_fix_on_failure_explicit_true( self ):
        """Per-run override True is stored verbatim for the watchdog to read."""
        job = TestSuiteJob(
            test_types          = [ "integration" ],
            user_id             = "u1",
            user_email          = "e@e.com",
            session_id          = "s1",
            auto_fix_on_failure = True,
        )
        assert job.auto_fix_on_failure is True

    def test_auto_fix_on_failure_explicit_false( self ):
        """Per-run override False is stored verbatim for the watchdog to read."""
        job = TestSuiteJob(
            test_types          = [ "integration" ],
            user_id             = "u1",
            user_email          = "e@e.com",
            session_id          = "s1",
            auto_fix_on_failure = False,
        )
        assert job.auto_fix_on_failure is False

    def test_single_suite( self, single_suite_job ):
        """Job with single suite should store it correctly."""
        assert single_suite_job.test_types == [ "integration" ]

    def test_id_prefix( self, job ):
        """Job ID should start with 'ts-' prefix."""
        assert job.id_hash.startswith( "ts-" )
        assert len( job.id_hash ) == 11  # "ts-" + 8 hex chars

    def test_job_type_constants( self ):
        """Class constants should be correct."""
        assert TestSuiteJob.JOB_TYPE == "test_suite"
        assert TestSuiteJob.JOB_PREFIX == "ts"

    def test_monopolize_always_true( self ):
        """Monopolize should always be True regardless of constructor args."""
        job = TestSuiteJob(
            test_types = [ "e2e" ],
            user_id    = "u1",
            user_email = "e@e.com",
            session_id = "s1",
        )
        assert job.monopolize == True

    def test_not_cacheable( self, job ):
        """Agentic jobs should never be cacheable."""
        assert job.is_cacheable == False

    def test_pytest_args_stored( self ):
        """Extra pytest args should be stored."""
        job = TestSuiteJob(
            test_types  = [ "integration" ],
            user_id     = "u1",
            user_email  = "e@e.com",
            session_id  = "s1",
            pytest_args = [ "-v", "-k", "test_auth" ],
        )
        assert job.pytest_args == [ "-v", "-k", "test_auth" ]

    def test_user_attributes( self, job ):
        """User attributes should be stored correctly."""
        assert job.user_id == "user-123"
        assert job.user_email == "test@test.com"
        assert job.session_id == "wise-penguin"


# ═══════════════════════════════════════════════════════════════════════════════
# Display Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDisplay:
    """Tests for last_question_asked property."""

    def test_both_suites( self, job ):
        """Should show both suite names."""
        assert job.last_question_asked == "[Tests] integration, e2e"

    def test_single_suite( self, single_suite_job ):
        """Should show single suite name."""
        assert single_suite_job.last_question_asked == "[Tests] integration"

    def test_e2e_only( self ):
        """Should show e2e only."""
        job = TestSuiteJob(
            test_types = [ "e2e" ],
            user_id    = "u1",
            user_email = "e@e.com",
            session_id = "s1",
        )
        assert job.last_question_asked == "[Tests] e2e"


# ═══════════════════════════════════════════════════════════════════════════════
# JUnit XML Parsing Tests
# ═══════════════════════════════════════════════════════════════════════════════

def _write_junit_xml( tmp_path, tests=0, failures=0, errors=0, skipped=0 ):
    """Helper: write a minimal junit-xml file and return its path."""
    xml_path = tmp_path / "results.xml"
    xml_path.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}" time="10.0">\n'
        f'</testsuite>\n'
    )
    return str( xml_path )


class TestParseJunitXml:
    """Tests for _parse_junit_xml static method."""

    def test_all_passed( self, tmp_path ):
        """Parse XML with only passed tests."""
        path   = _write_junit_xml( tmp_path, tests=195 )
        result = TestSuiteJob._parse_junit_xml( path )
        assert result[ "passed" ] == 195
        assert result[ "failed" ] == 0
        assert result[ "skipped" ] == 0
        assert result[ "errors" ] == 0

    def test_mixed_results( self, tmp_path ):
        """Parse XML with passed, failed, and skipped."""
        path   = _write_junit_xml( tmp_path, tests=230, failures=3, skipped=32 )
        result = TestSuiteJob._parse_junit_xml( path )
        assert result[ "passed" ] == 195
        assert result[ "failed" ] == 3
        assert result[ "skipped" ] == 32

    def test_with_errors( self, tmp_path ):
        """Parse XML with errors."""
        path   = _write_junit_xml( tmp_path, tests=9, failures=3, errors=1 )
        result = TestSuiteJob._parse_junit_xml( path )
        assert result[ "passed" ] == 5
        assert result[ "failed" ] == 3
        assert result[ "errors" ] == 1

    def test_missing_file( self ):
        """Missing file should return zeros (startup crash scenario)."""
        result = TestSuiteJob._parse_junit_xml( "/tmp/nonexistent-junit.xml" )
        assert result[ "passed" ] == 0
        assert result[ "failed" ] == 0
        assert result[ "skipped" ] == 0
        assert result[ "errors" ] == 0

    def test_malformed_xml( self, tmp_path ):
        """Malformed XML should return zeros."""
        xml_path = tmp_path / "bad.xml"
        xml_path.write_text( "this is not xml" )
        result = TestSuiteJob._parse_junit_xml( str( xml_path ) )
        assert result[ "passed" ] == 0

    def test_failed_only( self, tmp_path ):
        """Parse XML where all tests failed."""
        path   = _write_junit_xml( tmp_path, tests=10, failures=10 )
        result = TestSuiteJob._parse_junit_xml( path )
        assert result[ "passed" ] == 0
        assert result[ "failed" ] == 10

    def test_testsuites_wrapper( self, tmp_path ):
        """Parse XML with <testsuites> root wrapping <testsuite>."""
        xml_path = tmp_path / "results.xml"
        xml_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<testsuites>\n'
            '<testsuite name="pytest" tests="50" failures="2" errors="0" skipped="5" time="30.0">\n'
            '</testsuite>\n'
            '</testsuites>\n'
        )
        result = TestSuiteJob._parse_junit_xml( str( xml_path ) )
        assert result[ "passed" ] == 43
        assert result[ "failed" ] == 2
        assert result[ "skipped" ] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# from_config Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFromConfig:
    """Tests for from_config classmethod."""

    def test_from_config_defaults( self ):
        """from_config should use config values."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "test suite default types"       : "integration,e2e",
            "test suite default pytest args"  : "",
        }.get( key, default )

        job = TestSuiteJob.from_config(
            config_mgr = mock_config,
            user_id    = "u1",
            user_email = "e@e.com",
            session_id = "s1",
        )
        assert job.test_types == [ "integration", "e2e" ]
        assert job.pytest_args == []

    def test_from_config_custom_types( self ):
        """from_config should parse custom suite types."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "test suite default types"       : "e2e",
            "test suite default pytest args"  : "-v -s",
        }.get( key, default )

        job = TestSuiteJob.from_config(
            config_mgr = mock_config,
            user_id    = "u1",
            user_email = "e@e.com",
            session_id = "s1",
        )
        assert job.test_types == [ "e2e" ]
        assert job.pytest_args == [ "-v", "-s" ]


# ═══════════════════════════════════════════════════════════════════════════════
# State Transition Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateTransitions:
    """Tests for job state management during execution."""

    def test_initial_state_pending( self, job ):
        """New job should be PENDING."""
        assert job.state == JobState.PENDING

    @_stub_preflight
    @patch( "cosa.agents.test_suite.job.cu.get_project_root" )
    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_successful_completion( self, mock_voice_io, mock_run_suite, mock_root, job, tmp_path ):
        """Successful execution should transition to COMPLETED."""
        mock_root.return_value = str( tmp_path )
        mock_run_suite.return_value = {
            "passed"    : 10,
            "failed"    : 0,
            "skipped"   : 0,
            "errors"    : 0,
            "exit_code" : 0,
            "log_path"  : None,
            "duration"  : 5.0,
        }
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        job.do_all()

        assert job.state == JobState.COMPLETED
        assert job.started_at is not None
        assert job.completed_at is not None
        assert job.answer_conversational is not None
        assert job.error is None

    @_stub_preflight
    @patch( "cosa.agents.test_suite.job.cu.get_project_root" )
    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_failed_suite( self, mock_voice_io, mock_run_suite, mock_root, job, tmp_path ):
        """Suite failure should still complete (both always run)."""
        mock_root.return_value = str( tmp_path )
        mock_run_suite.return_value = {
            "passed"    : 5,
            "failed"    : 3,
            "skipped"   : 0,
            "errors"    : 0,
            "exit_code" : 1,
            "log_path"  : None,
            "duration"  : 5.0,
        }
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        result = job.do_all()

        assert job.state == JobState.COMPLETED
        assert "FAILURES DETECTED" in result

    @patch( "cosa.agents.test_suite.voice_io" )
    def test_exception_sets_failed( self, mock_voice_io, job ):
        """Exception during execution should set FAILED state."""
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock( side_effect=RuntimeError( "boom" ) )

        # Backlog item 5 (2026-04-29): do_all() re-raises (canonical Future
        # contract). State + error are still set on the job object.
        with pytest.raises( RuntimeError ):
            job.do_all()

        assert job.state == JobState.FAILED
        assert job.error is not None
        assert "boom" in job.error


# ═══════════════════════════════════════════════════════════════════════════════
# Dry Run Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDryRun:
    """Tests for dry-run mode execution."""

    @patch( "cosa.agents.test_suite.voice_io" )
    def test_dry_run_completes( self, mock_voice_io, dry_run_job ):
        """Dry run should complete without running subprocesses."""
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        result = dry_run_job.do_all()

        assert dry_run_job.state == JobState.COMPLETED
        assert "Dry run complete" in result
        assert dry_run_job.artifacts.get( "cost_summary" ) is not None
        assert dry_run_job.artifacts[ "cost_summary" ][ "mode" ] == "dry_run"

    @patch( "cosa.agents.test_suite.voice_io" )
    def test_dry_run_calls_voice_io( self, mock_voice_io, dry_run_job ):
        """Dry run should call voice_io set_job_id and clear_job_id."""
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        dry_run_job.do_all()

        mock_voice_io.set_job_id.assert_called_once_with( dry_run_job.id_hash )
        mock_voice_io.clear_job_id.assert_called_once()

    @patch( "cosa.agents.test_suite.voice_io" )
    def test_dry_run_notify_includes_queue_name( self, mock_voice_io, dry_run_job ):
        """All dry run notify() calls should include queue_name='run'."""
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        dry_run_job.do_all()

        for call in mock_voice_io.notify.call_args_list:
            _, kwargs = call
            assert kwargs.get( "queue_name" ) == "run", f"notify() call missing queue_name='run': {kwargs}"


# ═══════════════════════════════════════════════════════════════════════════════
# Voice I/O Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoiceIOIntegration:
    """Tests for voice_io lifecycle compliance."""

    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_set_job_id_called( self, mock_voice_io, mock_run_suite, job ):
        """voice_io.set_job_id should be called at execution start."""
        mock_run_suite.return_value = {
            "passed" : 1, "failed" : 0, "skipped" : 0, "errors" : 0,
            "exit_code" : 0, "log_path" : None, "duration" : 1.0,
        }
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        job.do_all()

        mock_voice_io.set_job_id.assert_called_once_with( job.id_hash )

    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_clear_job_id_called( self, mock_voice_io, mock_run_suite, job ):
        """voice_io.clear_job_id should be called in finally block."""
        mock_run_suite.return_value = {
            "passed" : 1, "failed" : 0, "skipped" : 0, "errors" : 0,
            "exit_code" : 0, "log_path" : None, "duration" : 1.0,
        }
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        job.do_all()

        mock_voice_io.clear_job_id.assert_called_once()

    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_all_notify_calls_have_queue_name( self, mock_voice_io, mock_run_suite, job ):
        """Every notify() call should include queue_name='run'."""
        mock_run_suite.return_value = {
            "passed" : 10, "failed" : 0, "skipped" : 0, "errors" : 0,
            "exit_code" : 0, "log_path" : None, "duration" : 5.0,
        }
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        job.do_all()

        assert mock_voice_io.notify.call_count > 0
        for call in mock_voice_io.notify.call_args_list:
            _, kwargs = call
            assert kwargs.get( "queue_name" ) == "run", f"notify() call missing queue_name='run': {kwargs}"


# ═══════════════════════════════════════════════════════════════════════════════
# Artifacts Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestArtifacts:
    """Tests for artifact population after execution."""

    @_stub_preflight
    @patch( "cosa.agents.test_suite.job.cu.get_project_root" )
    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_artifacts_populated( self, mock_voice_io, mock_run_suite, mock_root, job, tmp_path ):
        """Artifacts should contain suite_results and cost_summary."""
        # Pin io_base to tmp_path so do_all() writes results.md + remediation.json
        # under pytest's temp dir instead of polluting real io/test-suite/. Without
        # this, every unit-test run leaves a stray *-integration-e2e-remediation.json
        # in the project filesystem (OOS-4 Finding D, fixed 2026-04-29).
        mock_root.return_value = str( tmp_path )
        # Include failure_details in the mock so the writer's iteration at
        # job.py:511-515 produces a consistent snapshot (failed count matches
        # the failures[] array length). Previously omitted, which produced the
        # inconsistent "failed=4, failures=[]" file shape.
        mock_run_suite.return_value = {
            "passed"          : 10,
            "failed"          : 2,
            "skipped"         : 1,
            "errors"          : 0,
            "exit_code"       : 1,
            "log_path"        : "/tmp/test.log",
            "duration"        : 5.0,
            "failure_details" : [
                { "classname": "test.module.TestClass", "name": "test_one",
                  "type": "FAILED", "message": "mock failure 1", "traceback": "" },
                { "classname": "test.module.TestClass", "name": "test_two",
                  "type": "FAILED", "message": "mock failure 2", "traceback": "" },
            ],
        }
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        job.do_all()

        assert "suite_results" in job.artifacts
        assert "cost_summary" in job.artifacts
        cost = job.artifacts[ "cost_summary" ]
        assert cost[ "suites_run" ] == 2
        assert cost[ "total_passed" ] == 20  # 10 per suite * 2 suites
        assert cost[ "total_failed" ] == 4   # 2 per suite * 2 suites

    @_stub_preflight
    @patch( "cosa.agents.test_suite.job.cu.get_project_root" )
    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_log_paths_in_artifacts( self, mock_voice_io, mock_run_suite, mock_root, job, tmp_path ):
        """Log paths should be stored in artifacts."""
        # Pin io_base to tmp_path (OOS-4 Finding D) — see test_artifacts_populated above.
        mock_root.return_value = str( tmp_path )
        mock_run_suite.return_value = {
            "passed" : 10, "failed" : 0, "skipped" : 0, "errors" : 0,
            "exit_code" : 0, "log_path" : "/tmp/test.log", "duration" : 5.0,
        }
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify = AsyncMock()

        job.do_all()

        assert job.artifacts.get( "integration_log" ) == "/tmp/test.log"
        assert job.artifacts.get( "e2e_log" ) == "/tmp/test.log"


# ═══════════════════════════════════════════════════════════════════════════════
# Run Suite Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunSuite:
    """Tests for _run_suite method."""

    def test_unknown_suite_type( self, job ):
        """Unknown suite type should return error result."""
        result = job._run_suite( "unknown", "/tmp" )
        assert result[ "exit_code" ] == 1
        assert "Unknown suite type" in result.get( "error", "" )

    def test_missing_script( self, job ):
        """Missing script should return error result."""
        result = job._run_suite( "integration", "/nonexistent/path" )
        assert result[ "exit_code" ] == 1
        assert "Script not found" in result.get( "error", "" )


# ═══════════════════════════════════════════════════════════════════════════════
# Synthetic Failure Records (Bug 1A — timeout/exception paths)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyntheticFailureRecords:
    """
    Regression tests for the 2026-04-14 `all`-suite aggregation bug:
    the timeout and generic-exception paths must return `errors:1` plus a
    single `failure_details` entry so TestSuiteCompletionWatchdog Gate 3
    (`len(failures) > 0`) can dispatch TFE instead of silently dropping
    an 80-minute run on the floor.
    """

    def test_timeout_populates_failure_details( self, single_suite_job, tmp_path, monkeypatch ):
        """Timeout branch must return errors=1 + one synthetic failure_details entry + log_path."""
        script = tmp_path / "src" / "tests" / "run-integration-tests.sh"
        script.parent.mkdir( parents=True )
        # Long-running shell that exceeds the patched 1s budget
        script.write_text( "#!/usr/bin/env bash\nfor i in $(seq 1 20); do echo line-$i; sleep 0.2; done\n" )
        script.chmod( 0o755 )

        from cosa.agents.test_suite import job as job_mod
        monkeypatch.setitem( job_mod.SUITE_TIMEOUTS_SECONDS, "integration", 1 )

        result = single_suite_job._run_suite( "integration", str( tmp_path ) )

        assert result[ "errors" ] == 1
        assert result[ "passed" ] == 0
        assert result[ "failed" ] == 0
        assert result[ "exit_code" ] == -2
        assert "Timeout" in result[ "error" ]
        # Core regression guard: non-empty failure_details so watchdog Gate 3 fires
        fd = result.get( "failure_details" )
        assert isinstance( fd, list ) and len( fd ) == 1
        assert fd[ 0 ][ "type" ] == "ERROR"
        assert fd[ 0 ][ "name" ] == "timeout"
        assert fd[ 0 ][ "classname" ] == "TestSuiteJob.integration"
        assert "Subprocess killed after 1s" in fd[ 0 ][ "message" ]
        # Captured stdout tail survives the terminate()
        assert "line-" in fd[ 0 ][ "traceback" ]
        # Log file was actually written
        # Asserted against the ISOLATED root, not "/tmp/". The old form pinned the
        # literal live directory — so it passed only while this test was polluting it,
        # and it went red the moment the pollution stopped. An assertion that requires
        # the defect in order to pass is not a guard; it is the defect's alibi.
        assert result[ "log_path" ]
        assert result[ "log_path" ].startswith( os.path.join( str( tmp_path ), "integration-" ) )

    def test_exception_populates_failure_details( self, single_suite_job, tmp_path, monkeypatch ):
        """Exception branch must return errors=1 (not 0) + one synthetic failure_details entry."""
        script = tmp_path / "src" / "tests" / "run-integration-tests.sh"
        script.parent.mkdir( parents=True )
        script.write_text( "#!/usr/bin/env bash\necho hi\n" )
        script.chmod( 0o755 )

        from cosa.agents.test_suite import job as job_mod
        def boom( *a, **kw ):
            raise RuntimeError( "simulated popen failure" )
        monkeypatch.setattr( job_mod.subprocess, "Popen", boom )

        result = single_suite_job._run_suite( "integration", str( tmp_path ) )

        # Was errors=0 before the fix — watchdog silently ignored crashed subprocesses
        assert result[ "errors" ] == 1
        assert "simulated popen failure" in result[ "error" ]
        fd = result.get( "failure_details" )
        assert isinstance( fd, list ) and len( fd ) == 1
        assert fd[ 0 ][ "type" ] == "ERROR"
        assert fd[ 0 ][ "name" ] == "exception"
        assert "RuntimeError" in fd[ 0 ][ "message" ]
        # format_exc() output lands in traceback (best-effort; at minimum non-empty fallback)
        assert fd[ 0 ][ "traceback" ]

    def test_write_stdout_log_refreshes_symlink( self, tmp_path, monkeypatch ):
        """_write_stdout_log returns actual log path and points the canonical symlink at it."""
        import pathlib
        from cosa.agents.test_suite.job import TestSuiteJob

        # Redirect the ARTIFACT ROOT, not just the symlink map.
        #
        # This test used to monkeypatch _LOG_SYMLINKS alone, which moved the symlink and
        # left `actual_log` hardcoded at /tmp/ — so every run wrote a real
        # /tmp/unit-<timestamp>.log containing "first run" into the live artifact
        # directory the scheduled tier and its human triager both read. Found 2026-07-27
        # (row fd0cd863) with "first run" sitting in the container's /tmp.
        #
        # Patching _ARTIFACT_DIR moves the log file, the symlink and the junit XML
        # together, because they all derive from it now. There is nothing left to forget.
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
        link = tmp_path / "unit-latest.log"

        path1 = TestSuiteJob._write_stdout_log( "unit", "first run\n" )
        assert path1 is not None
        assert pathlib.Path( path1 ).read_text() == "first run\n"
        assert pathlib.Path( link ).resolve() == pathlib.Path( path1 ).resolve()

        # Unknown suite → no-op
        assert TestSuiteJob._write_stdout_log( "bogus", "ignored" ) is None
        # Empty text → no-op even for known suite
        assert TestSuiteJob._write_stdout_log( "unit", "" ) is None


# ═══════════════════════════════════════════════════════════════════════════════
# "all" Expansion (Bug 1B — per-component suite_results)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAllExpansion:
    """
    Regression tests for the 2026-04-14 `all`-suite aggregation bug:
    passing test_types=["all"] must fan out into per-component runs so a
    timeout in one suite doesn't nuke every other suite's results.
    """

    def test_all_components_order( self ):
        """Canonical pyramid order: unit → smoke → websocket → integration → e2e."""
        # "typescript" joined the pyramid 2026-07-21 (row 36e479ed, Rick's ruling on
        # gate 07a5460d). Before that, `all` ran every Python tier and silently
        # skipped the entire TypeScript suite.
        assert ALL_SUITE_COMPONENTS == [ "unit", "typescript", "smoke", "websocket", "integration", "e2e" ]

    def test_expand_all_fans_out( self ):
        assert _expand_all( [ "all" ] ) == ALL_SUITE_COMPONENTS

    def test_expand_passthrough_for_non_all( self ):
        assert _expand_all( [ "integration" ] )         == [ "integration" ]
        assert _expand_all( [ "unit", "e2e" ] )         == [ "unit", "e2e" ]
        assert _expand_all( [] )                        == []

    def test_expand_dedupes_first_wins( self ):
        # "all" + redundant component → expansion deduped, order preserved
        assert _expand_all( [ "all", "unit" ] )         == ALL_SUITE_COMPONENTS
        assert _expand_all( [ "unit", "all" ] )         == ALL_SUITE_COMPONENTS
        # Caller-supplied duplicates also deduped
        assert _expand_all( [ "unit", "unit" ] )        == [ "unit" ]

    def test_expand_does_not_mutate_input( self ):
        original = [ "all" ]
        _expand_all( original )
        assert original == [ "all" ]

    def test_run_task_runs_each_component( self, monkeypatch ):
        """
        When test_types=["all"], run_task must invoke _run_suite once per
        component and store each result under its own key in suite_results.
        Pre-fix this was a single "all" entry — a timeout anywhere lost everything.
        """
        import asyncio
        job = TestSuiteJob(
            test_types = [ "all" ],
            user_id    = "user-123",
            user_email = "test@test.com",
            session_id = "wise-penguin",
        )

        called_with = []
        def fake_run_suite( self_ref, suite_type, project_root ):
            called_with.append( suite_type )
            return {
                "passed"    : 1,
                "failed"    : 0,
                "skipped"   : 0,
                "errors"    : 0,
                "exit_code" : 0,
                "log_path"  : None,
                "duration"  : 0.1,
            }
        monkeypatch.setattr( TestSuiteJob, "_run_suite", fake_run_suite )

        # Patch voice_io to keep the coroutine inert in unit context
        import cosa.agents.test_suite.voice_io as voice_io
        monkeypatch.setattr( voice_io, "reconfigure", lambda: None )
        monkeypatch.setattr( voice_io, "set_job_id", lambda _id: None )
        monkeypatch.setattr( voice_io, "clear_job_id", lambda: None )
        async def fake_notify( *a, **kw ): return None
        monkeypatch.setattr( voice_io, "notify", fake_notify )

        asyncio.run( job._execute() )

        assert called_with == ALL_SUITE_COMPONENTS
        assert set( job.suite_results.keys() ) == set( ALL_SUITE_COMPONENTS )
        # test_types unchanged — user-visible label and report filename stay "all"
        assert job.test_types == [ "all" ]


# ═══════════════════════════════════════════════════════════════════════════════
# --junit-xml Flag Gating (2026-04-14 regression — WebSocket runner is custom async,
# not pytest; flag was killing the subprocess before any tests ran)
# ═══════════════════════════════════════════════════════════════════════════════

class TestJunitFlagGating:
    """
    Regression tests for the post-fan-out discovery that not every suite script
    is a pytest wrapper. `run-websocket-smoke-tests.sh` is a custom async
    orchestrator — appending --junit-xml triggers its `Unknown option` branch
    and exit 1, causing 0 tests to run.
    """

    @staticmethod
    def _capture_popen_args( tmp_path, suite_type, job, monkeypatch ):
        """Shared setup: stub the suite script, intercept Popen, return captured cmd args."""
        from cosa.agents.test_suite import job as job_mod

        script_rel = job_mod.SUITE_SCRIPTS[ suite_type ]
        script = tmp_path / script_rel
        script.parent.mkdir( parents=True, exist_ok=True )
        script.write_text( "#!/usr/bin/env bash\necho noop\n" )
        script.chmod( 0o755 )

        captured = {}
        class FakeProc:
            stdout     = None
            returncode = 0
            def __init__( self ): self.stdout = _NullStdout()
            def poll( self ): return 0
            def wait( self, timeout=None ): return 0
            def terminate( self ): pass
            def kill( self ): pass

        class _NullStdout:
            def readline( self ): return ""
            def read( self ): return ""

        def fake_popen( cmd, **kwargs ):
            captured[ "cmd" ] = cmd
            return FakeProc()

        monkeypatch.setattr( job_mod.subprocess, "Popen", fake_popen )
        job._run_suite( suite_type, str( tmp_path ) )
        return captured.get( "cmd", [] )

    def test_junit_xml_injected_for_pytest_suites( self, single_suite_job, tmp_path, monkeypatch ):
        """pytest-backed suites (unit) must receive --junit-xml=<path>."""
        cmd = self._capture_popen_args( tmp_path, "integration", single_suite_job, monkeypatch )
        assert any( arg.startswith( "--junit-xml=" ) for arg in cmd ), \
            f"Expected --junit-xml= in cmd for integration suite, got: {cmd}"

    def test_junit_xml_not_injected_for_websocket( self, tmp_path, monkeypatch ):
        """WebSocket's custom async runner must NOT receive --junit-xml."""
        job = TestSuiteJob(
            test_types = [ "websocket" ],
            user_id    = "user-123",
            user_email = "test@test.com",
            session_id = "wise-penguin",
        )
        cmd = self._capture_popen_args( tmp_path, "websocket", job, monkeypatch )
        assert not any( arg.startswith( "--junit-xml" ) for arg in cmd ), \
            f"websocket must not get --junit-xml; got: {cmd}"

    def test_websocket_excluded_from_junit_support_set( self ):
        """Guard against someone accidentally adding websocket to the allow-list."""
        assert "websocket" not in SUITES_SUPPORTING_JUNIT_XML
        # Sanity-check the expected members are present
        for s in ( "unit", "smoke", "integration", "e2e" ):
            assert s in SUITES_SUPPORTING_JUNIT_XML

    def test_parse_junit_xml_handles_none_path( self ):
        """_parse_junit_xml(None) returns zero-counts dict without raising."""
        result = TestSuiteJob._parse_junit_xml( None )
        assert result == { "passed": 0, "failed": 0, "skipped": 0, "errors": 0 }

    def test_parse_junit_xml_handles_empty_string( self ):
        """Empty-string path treated same as None (non-pytest suites)."""
        result = TestSuiteJob._parse_junit_xml( "" )
        assert result == { "passed": 0, "failed": 0, "skipped": 0, "errors": 0 }


# ═══════════════════════════════════════════════════════════════════════════════
# Between-suites DB-reset orchestration (bug 8bd20375)
#
# The merge-gate sweep runs suites back-to-back on ONE shared :8000 DB. Without
# a reset at the seam, the earlier suite's residue (refresh_tokens; e2e→integration
# "Token already exists" flood) poisons the later suite's auth fixtures. A literal
# container bounce is impossible from INSIDE the sweep job (self-kill), so the
# equivalent isolation is an in-job DB hard-reset invoked BETWEEN suites only.
# These tests pin condition 2 of Tiberius's ruling: the reset fires in every gap,
# NEVER before the first suite, NEVER after the last, NEVER for a single-suite run.
# ═══════════════════════════════════════════════════════════════════════════════

class TestBetweenSuiteResetBoundaries:
    """Pure semantics of the between-suites reset seam — proves not-after-last
    + single-suite-skip without a DB or container."""

    def test_empty_suite_list_has_no_reset( self ):
        assert TestSuiteJob._between_suite_pairs( [ ] ) == [ ]

    def test_single_suite_skips_reset( self ):
        # one suite = zero gaps = zero resets (single-suite-skip)
        assert TestSuiteJob._between_suite_pairs( [ "integration" ] ) == [ ]

    def test_pair_resets_once_between_the_two( self ):
        pairs = TestSuiteJob._between_suite_pairs( [ "e2e", "integration" ] )
        assert pairs == [ ( "e2e", "integration" ) ]

    def test_full_pyramid_resets_in_every_gap_never_after_last( self ):
        suites = list( ALL_SUITE_COMPONENTS )   # unit, smoke, websocket, integration, e2e
        pairs  = TestSuiteJob._between_suite_pairs( suites )
        # exactly one reset per gap → N-1 resets
        assert len( pairs ) == len( suites ) - 1
        # each pair is an adjacent (prev, next) in original order
        assert pairs == [ ( suites[ i - 1 ], suites[ i ] ) for i in range( 1, len( suites ) ) ]
        # NEVER a reset AFTER the last suite: the last suite never opens a gap
        assert all( prev != suites[ -1 ] for prev, _ in pairs )


class TestSweepResetsBetweenSuites:
    """The sweep loop invokes _reset_state_between_suites in each between-suite
    gap — proven by call ORDER (interleaved), not merely count."""

    _CANNED = {
        "passed"    : 1,
        "failed"    : 0,
        "skipped"   : 0,
        "errors"    : 0,
        "exit_code" : 0,
        "log_path"  : None,
        "duration"  : 0.1,
    }

    @_stub_preflight
    @patch( "cosa.agents.test_suite.job.cu.get_project_root" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_reset_fires_between_suites_in_order( self, mock_voice_io, mock_root, job, tmp_path ):
        """job fixture = ["integration","e2e"] → exactly ONE reset, and it lands
        AFTER integration's run and BEFORE e2e's run (interleaved at the gap)."""
        mock_root.return_value    = str( tmp_path )
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id  = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify      = AsyncMock()

        order = [ ]
        def _run( suite_type, project_root ):
            order.append( f"run:{suite_type}" )
            return dict( self._CANNED )
        def _reset( prev, nxt ):
            order.append( f"reset:{prev}->{nxt}" )

        with patch.object( TestSuiteJob, "_run_suite", side_effect=_run ), \
             patch.object( TestSuiteJob, "_reset_state_between_suites", side_effect=_reset, create=True ):
            job.do_all()

        assert order == [ "run:integration", "reset:integration->e2e", "run:e2e" ]

    @_stub_preflight
    @patch( "cosa.agents.test_suite.job.cu.get_project_root" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_single_suite_never_resets( self, mock_voice_io, mock_root, single_suite_job, tmp_path ):
        """A single-suite run has no gap → the reset must never fire."""
        mock_root.return_value    = str( tmp_path )
        mock_voice_io.reconfigure = MagicMock()
        mock_voice_io.set_job_id  = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify      = AsyncMock()

        with patch.object( TestSuiteJob, "_run_suite", return_value=dict( self._CANNED ) ), \
             patch.object( TestSuiteJob, "_reset_state_between_suites", create=True ) as spy_reset:
            single_suite_job.do_all()

        spy_reset.assert_not_called()


class TestResetStateBetweenSuitesBody:
    """The reset body (bug 8bd20375): truncates residue ONLY on lupin_db_test,
    NO-OPs off the test DB (dev-data safety), and never raises."""

    @staticmethod
    def _mock_engine( url ):
        conn = MagicMock()
        executed = [ ]
        conn.execute.side_effect = lambda stmt: executed.append( str( stmt ) )
        cm = MagicMock()
        cm.__enter__.return_value = conn
        cm.__exit__.return_value  = False
        engine = MagicMock()
        engine.url            = url
        engine.begin.return_value = cm
        return engine, executed

    def test_truncates_and_deletes_on_test_db( self, job ):
        """On lupin_db_test: non-protected users DELETEd + residue TRUNCATEd,
        and refresh_tokens is in the truncate — the flood-killing residue."""
        engine, executed = self._mock_engine( "postgresql://u@h/lupin_db_test" )
        with patch( "cosa.rest.db.database.engine", engine ):
            job._reset_state_between_suites( "e2e", "integration" )
        joined = " ".join( executed )
        assert "DELETE FROM users WHERE NOT is_protected" in joined
        assert "TRUNCATE TABLE" in joined
        assert "refresh_tokens" in joined
        engine.begin.assert_called_once()

    def test_skips_off_test_db_no_destructive_op( self, job ):
        """Against a NON-test DB (e.g. dev), the reset must NOT open a
        transaction or execute anything — dev-data safety."""
        engine, executed = self._mock_engine( "postgresql://u@h/lupin_db_dev" )
        with patch( "cosa.rest.db.database.engine", engine ):
            job._reset_state_between_suites( "e2e", "integration" )
        engine.begin.assert_not_called()
        assert executed == [ ]

    def test_reset_failure_is_non_fatal( self, job ):
        """A DB error during the reset is swallowed (logged) — it must never
        abort the surrounding sweep; the per-test clean_test_db is the backstop."""
        engine = MagicMock()
        engine.url = "postgresql://u@h/lupin_db_test"
        engine.begin.side_effect = RuntimeError( "connection refused" )
        with patch( "cosa.rest.db.database.engine", engine ):
            # Must not raise
            job._reset_state_between_suites( "e2e", "integration" )


class TestPreflightAssertExclusiveTestDb:
    """The sweep-start exclusivity preflight (bug caf58f71 — concurrent-writer
    contamination). Fails LOUD if a non-test agentic job is inflight on the shared
    lupin_db_test; NO-OPs off the test DB or when the running queue is unreachable."""

    @staticmethod
    def _test_engine():
        engine     = MagicMock()
        engine.url = "postgresql://u@h/lupin_db_test"
        return engine

    @staticmethod
    def _install_main( jobs_run_queue="__unset__" ):
        """Return a patch.dict context injecting fake lupin_app / lupin_app.main
        into sys.modules. jobs_run_queue: '__unset__' → attr absent (AttributeError
        path); None → attribute present but None; None-module → ImportError path;
        any object → that queue."""
        import sys, types
        fake_pkg  = types.ModuleType( "lupin_app" )
        if jobs_run_queue == "__import_error__":
            fake_pkg.main = None
            return patch.dict( sys.modules, { "lupin_app": fake_pkg, "lupin_app.main": None } )
        fake_main = types.ModuleType( "lupin_app.main" )
        if jobs_run_queue != "__unset__":
            fake_main.jobs_run_queue = jobs_run_queue
        fake_pkg.main = fake_main
        return patch.dict( sys.modules, { "lupin_app": fake_pkg, "lupin_app.main": fake_main } )

    def test_off_test_db_is_noop( self, job ):
        """Off lupin_db_test (e.g. a sweep aimed at :7999 dev) the preflight must
        NOT raise and must never consult the running queue."""
        engine     = MagicMock()
        engine.url = "postgresql://u@h/lupin_db_dev"
        with patch( "cosa.rest.db.database.engine", engine ):
            job._preflight_assert_exclusive_test_db()   # must not raise

    def test_import_error_is_noop( self, job ):
        """On the test DB but the running-queue module import fails → logged
        NO-OP, never a raise."""
        with patch( "cosa.rest.db.database.engine", self._test_engine() ), \
             self._install_main( jobs_run_queue="__import_error__" ):
            job._preflight_assert_exclusive_test_db()   # must not raise

    def test_missing_attribute_is_noop( self, job ):
        """Module present but jobs_run_queue attribute absent → AttributeError
        path → logged NO-OP."""
        with patch( "cosa.rest.db.database.engine", self._test_engine() ), \
             self._install_main():   # attr unset
            job._preflight_assert_exclusive_test_db()   # must not raise

    def test_none_queue_is_noop( self, job ):
        """jobs_run_queue present but None (server not yet initialised) → NO-OP."""
        with patch( "cosa.rest.db.database.engine", self._test_engine() ), \
             self._install_main( jobs_run_queue=None ):
            job._preflight_assert_exclusive_test_db()   # must not raise

    def test_no_offenders_passes( self, job ):
        """A clean pool (no non-test inflight jobs) → preflight passes, no raise,
        and the sweep's own id_hash is excluded from the query."""
        fake_queue = MagicMock()
        fake_queue.get_non_test_inflight_agentic_jobs.return_value = [ ]
        with patch( "cosa.rest.db.database.engine", self._test_engine() ), \
             self._install_main( jobs_run_queue=fake_queue ):
            job._preflight_assert_exclusive_test_db()   # must not raise
        fake_queue.get_non_test_inflight_agentic_jobs.assert_called_once_with(
            exclude_id_hash=job.id_hash
        )

    def test_offenders_raise_loud( self, job ):
        """A non-test inflight writer → RuntimeError naming the offender(s) and
        the bug id, aborting the sweep before any suite runs."""
        fake_queue = MagicMock()
        fake_queue.get_non_test_inflight_agentic_jobs.return_value = [
            { "id_hash": "dr-abc123", "job_type": "deep_research" }
        ]
        with patch( "cosa.rest.db.database.engine", self._test_engine() ), \
             self._install_main( jobs_run_queue=fake_queue ):
            with pytest.raises( RuntimeError ) as exc:
                job._preflight_assert_exclusive_test_db()
        msg = str( exc.value )
        assert "caf58f71" in msg
        assert "dr-abc123" in msg
        assert "deep_research" in msg

    @patch( "cosa.agents.test_suite.job.cu.get_project_root" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_preflight_fires_before_first_suite( self, mock_voice_io, mock_root, single_suite_job, tmp_path ):
        """The preflight is called at sweep start — BEFORE any suite runs. A
        loud-fail must abort the run (job FAILED) with no _run_suite call."""
        mock_root.return_value     = str( tmp_path )
        mock_voice_io.reconfigure  = MagicMock()
        mock_voice_io.set_job_id   = MagicMock()
        mock_voice_io.clear_job_id = MagicMock()
        mock_voice_io.notify       = AsyncMock()

        order = [ ]
        def _preflight( self ):
            order.append( "preflight" )
            raise RuntimeError( "Merge-gate sweep preflight FAILED (bug caf58f71): offenders" )
        def _run( self, suite_type, project_root ):
            order.append( f"run:{suite_type}" )
            return { "passed": 1, "failed": 0, "skipped": 0, "errors": 0,
                     "exit_code": 0, "log_path": None, "duration": 0.1 }

        with patch.object( TestSuiteJob, "_preflight_assert_exclusive_test_db", _preflight, create=True ), \
             patch.object( TestSuiteJob, "_run_suite", _run ):
            with pytest.raises( RuntimeError ):
                single_suite_job.do_all()

        assert order == [ "preflight" ]   # aborted before the first suite
        assert single_suite_job.state == JobState.FAILED


# ═══════════════════════════════════════════════════════════════════════════════
# Artifact-root creation (regression from 11ba6a1b — ts-102267b8 died on it)
# ═══════════════════════════════════════════════════════════════════════════════

class TestArtifactRootIsCreated:
    """
    🔴 THE CASE THE ISOLATION FIXTURE STRUCTURALLY CANNOT PRODUCE.

    `_isolate_artifact_root` pins `_ARTIFACT_DIR` to pytest's `tmp_path` — **which
    already exists**. So every test in this module wrote into a live directory, and the
    whole suite stayed green while production died on the first real run:

        FileNotFoundError: /var/lupin/io/test-suite/artifacts/unit-20260727-201637.log
        job.py:1182  _write_stdout_log        (ts-102267b8, dead at 311s)

    `/tmp` always existed, so no writer ever needed a mkdir. Moving the root to
    `io/test-suite/artifacts/` replaced a path that is always there with one that must
    be created — **the change that passes every unit test.**

    ⇒ These tests point the root at a path that does NOT exist. That is the only way
    the harness stops supplying what production doesn't.
    """

    def test_write_stdout_log_CREATES_a_missing_artifact_root( self, tmp_path, monkeypatch ):
        import pathlib
        missing = tmp_path / "does" / "not" / "exist"
        assert not missing.exists(), "precondition: the root must be ABSENT, or this proves nothing"
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( missing ) )

        path = TestSuiteJob._write_stdout_log( "unit", "hello\n" )

        assert path is not None
        assert pathlib.Path( path ).read_text() == "hello\n"
        assert pathlib.Path( missing / "unit-latest.log" ).resolve() == pathlib.Path( path ).resolve()

    def test_run_suite_RETURNS_its_error_dict_when_the_root_is_missing( self, single_suite_job, tmp_path, monkeypatch ):
        """
        The second half: `_write_stdout_log` raised on the main path AND again inside
        `_run_suite`'s except handler, so the exception ESCAPED rather than returning the
        error dict. A handler that re-invokes what just failed turns one failure into an
        escape — and an escaped exception loses the whole result, the `8b93bcf5` family.
        """
        script = tmp_path / "src" / "tests" / "run-integration-tests.sh"
        script.parent.mkdir( parents=True )
        script.write_text( "#!/usr/bin/env bash\necho hi\n" )
        script.chmod( 0o755 )
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path / "absent" / "root" ) )

        result = single_suite_job._run_suite( "integration", str( tmp_path ) )   # must NOT raise

        assert isinstance( result, dict )
        assert "log_path" in result
