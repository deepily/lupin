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

    def test_every_runnable_suite_can_write_a_stdout_log( self ):
        """
        🔴 A SUITE MISSING FROM _LOG_BASENAMES THROWS ITS STDOUT AWAY, SILENTLY.

        `_write_stdout_log` no-ops on a falsy basename, so a suite registered in
        SUITE_SCRIPTS but absent from _LOG_BASENAMES runs, fails, and leaves NO record
        of why. Measured 2026-08-28: a v2_eval run failed in 2.5s; the report said
        "0 passed, 1 failed" with no reason, the remediation snapshot carried
        `failures: []`, and no log existed anywhere. v2_eval, cosa and presentation
        were all missing.

        It is worst for the NON-pytest suites — they have no junit-xml fallback, so
        stdout is the only account of the run they produce.

        This asserts the two tables agree, so registering the NEXT suite trips a test
        rather than an operator staring at an unexplained failure.
        """
        from cosa.agents.test_suite.job import TestSuiteJob, SUITE_SCRIPTS
        missing = ( set( SUITE_SCRIPTS )
                    - set( TestSuiteJob._LOG_BASENAMES )
                    - TestSuiteJob._SUITES_EXEMPT_FROM_STDOUT_LOG )
        assert missing == set(), (
            f"these suites can be run but cannot write a stdout log, so a failure in one "
            f"leaves no explanation on disk: {sorted( missing )}. Add a basename to "
            f"_LOG_BASENAMES, or name it in _SUITES_EXEMPT_FROM_STDOUT_LOG with a reason."
        )

    def test_the_three_suites_added_on_2026_08_28_actually_write( self, tmp_path, monkeypatch ):
        """
        The table-agreement test above passes if someone types a key with an empty-ish
        value that is still truthy. This drives the real writer for the three suites the
        08-28 finding named, so the fix is exercised rather than asserted.
        """
        import pathlib
        from cosa.agents.test_suite.job import TestSuiteJob
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
        for suite in ( "v2_eval", "cosa", "presentation" ):
            path = TestSuiteJob._write_stdout_log( suite, f"{suite} said something\n" )
            assert path is not None, f"{suite} still discards its stdout"
            assert pathlib.Path( path ).read_text() == f"{suite} said something\n"


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
        """Canonical pyramid order: unit → cosa → typescript → smoke → websocket → integration → e2e."""
        # "typescript" joined the pyramid 2026-07-21 (row 36e479ed, Rick's ruling on
        # gate 07a5460d). Before that, `all` ran every Python tier and silently
        # skipped the entire TypeScript suite.
        # "cosa" joined 2026-08-13 (row d83d025b), right after "unit" — both are fast
        # server-free pytest, so they fail early together.
        assert ALL_SUITE_COMPONENTS == [ "unit", "cosa", "coverage", "typescript", "smoke", "websocket", "integration", "e2e" ]

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

    # not_executed joined the zero-counts dict at c37443f5 (89bfcc8f D2, 2026-08-13);
    # deselected joined at f3beb6d5 (2026-08-15) — the junit XML carries no deselect
    # info, so the key is always 0 here and the slice count is parsed from stdout.
    def test_parse_junit_xml_handles_none_path( self ):
        """_parse_junit_xml(None) returns zero-counts dict without raising."""
        result = TestSuiteJob._parse_junit_xml( None )
        assert result == { "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 0, "deselected": 0 }

    def test_parse_junit_xml_handles_empty_string( self ):
        """Empty-string path treated same as None (non-pytest suites)."""
        result = TestSuiteJob._parse_junit_xml( "" )
        assert result == { "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 0, "deselected": 0 }


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


# ═══════════════════════════════════════════════════════════════════════════════
# The completion card (row 24a85385)
#
# The junit XML always carried the failure message; the card a human reads did not.
# On 2026-08-21 an eval run died on an integrity guard and the card said "1 failed",
# so the reader had to open the XML to learn it was not a broken assertion.
# ═══════════════════════════════════════════════════════════════════════════════
def _line( **result ):
    """Build one suite line without constructing a whole job."""
    base = { "passed": 0, "failed": 0, "errors": 0, "skipped": 0 }
    base.update( result )
    return TestSuiteJob._suite_abstract_line( TestSuiteJob, "integration", base )


def test_the_card_carries_the_failure_message_not_just_the_count():
    """
    RED ON REVERT: drop the failure_details block and this fails — the line is back
    to counts alone, which is exactly the state that cost an afternoon.
    """
    line = _line( failed=1, failure_details=[ {
        "type": "FAILED", "name": "test_v2_eval_two_pass_live",
        "message": "v2_eval.EvalIntegrityError: run integrity failed — http-all-ok: 1 of 300",
    } ] )
    assert "1 failed" in line
    assert "EvalIntegrityError" in line
    assert "http-all-ok" in line
    assert "test_v2_eval_two_pass_live" in line


def test_a_clean_suite_line_gains_nothing():
    """The control: no failures, no appended detail — the card must not grow noise."""
    line = _line( passed=12 )
    assert "12 passed" in line
    assert "FAILED" not in line
    assert "…and" not in line


def test_only_the_first_failure_is_shown_and_the_rest_are_counted():
    """
    The card is spoken aloud and rendered in a box. A full list buries the one line
    that says what happened, so the rest become a count.
    """
    details = [ { "type": "FAILED", "name": f"test_{i}", "message": f"boom {i}" }
                for i in range( 4 ) ]
    line = _line( failed=4, failure_details=details )
    assert "boom 0" in line
    assert "boom 1" not in line
    assert "…and 3 more" in line


def test_a_multi_line_message_is_reduced_to_its_first_line():
    """A pytest message can carry a whole assertion dump; the card takes the headline."""
    line = _line( failed=1, failure_details=[ {
        "type": "FAILED", "name": "test_x",
        "message": "AssertionError: the headline\n  plus a second line\n  and a third",
    } ] )
    assert "the headline" in line
    assert "second line" not in line


def test_a_very_long_message_is_truncated():
    line = _line( failed=1, failure_details=[ {
        "type": "FAILED", "name": "test_x", "message": "x" * 900,
    } ] )
    assert len( line ) < 600


def test_a_failure_with_no_message_says_so_rather_than_showing_an_empty_box():
    """
    Silence in the card must not look like a missing failure. If the XML gave us no
    message, the card says that plainly instead of rendering an empty code span.
    """
    line = _line( failed=1, failure_details=[ { "type": "ERROR", "name": "test_x" } ] )
    assert "no message on the failure element" in line


def test_a_malformed_failure_detail_does_not_break_the_card():
    """
    A card that cannot be built is worse than a card missing one detail — the reader
    would get nothing at all about a run that did happen.
    """
    line = _line( failed=1, failure_details=[ "not-a-dict" ] )
    assert "1 failed" in line


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal state reflects whether anything actually RAN (row a9d19d18)
# ═══════════════════════════════════════════════════════════════════════════════

def _run_do_all( job, execute_return, cost_summary, suite_results, overall_status ):
    """
    Drive do_all() with _execute() stubbed to leave the state a real run would leave.

    do_all bridges to the async _execute via asyncio.run, so the seam under test is
    "what do_all does with what _execute left on self", not the subprocess itself.
    """
    async def fake_execute():
        job.cost_summary    = cost_summary
        job.suite_results   = suite_results
        job.overall_status  = overall_status
        return execute_return

    with patch.object( TestSuiteJob, "_execute", side_effect=fake_execute ):
        return job.do_all()


def _counts( passed=0, failed=0, errors=0, skipped=0 ):
    return {
        "total_passed"  : passed,
        "total_failed"  : failed,
        "total_errors"  : errors,
        "total_skipped" : skipped,
        "all_passed"    : ( failed + errors ) == 0 and passed > 0,
    }


def test_a_suite_that_executed_nothing_is_FAILED_not_completed( job ):
    """
    THE DEFECT THIS ROW EXISTS FOR (row a9d19d18), measured on job ts-76be90f0.

    The capped JS-test lane refused to start (exit 70, no container memory ceiling),
    so ZERO tests ran — and the job still landed in the `done` queue reading
    "completed". `_classify_outcome` had already called it NOT EXECUTED; do_all
    never asked. A run that never executed has not passed.
    """
    _run_do_all(
        job,
        execute_return = "Test suite run complete. NOT EXECUTED.",
        cost_summary   = _counts(),
        suite_results  = { "typescript": { "passed": 0, "failed": 0, "errors": 0, "skipped": 0 } },
        overall_status = "NOT EXECUTED",
    )
    assert job.state == JobState.FAILED
    assert "ZERO tests" in job.error
    assert "NOT EXECUTED" in job.error


def test_a_collection_error_that_ran_nothing_is_also_FAILED( job ):
    """A suite that could not even collect ran nothing — same verdict, different cause."""
    _run_do_all(
        job,
        execute_return = "COLLECTION ERROR — THE SUITE DID NOT RUN",
        cost_summary   = _counts(),
        suite_results  = { "unit": { "passed": 0, "failed": 0, "errors": 0, "skipped": 0 } },
        overall_status = "COLLECTION ERROR",
    )
    assert job.state == JobState.FAILED


def test_a_green_run_is_COMPLETED( job ):
    """The ordinary case must not regress — 2421 passed is a completed job."""
    _run_do_all(
        job,
        execute_return = "Test suite run complete. ALL PASSED.",
        cost_summary   = _counts( passed=2421 ),
        suite_results  = { "typescript": { "passed": 2421, "failed": 0, "errors": 0, "skipped": 0 } },
        overall_status = "PASSED",
    )
    assert job.state == JobState.COMPLETED
    assert job.error is None or job.error == ""


def test_a_genuine_RED_stays_COMPLETED_because_the_job_did_its_work( job ):
    """
    DELIBERATE, and the reason is load-bearing: a suite that ran and went red is a
    job that DID its work and is reporting a red. The TestSuiteCompletionWatchdog
    reads the DONE queue and gates on all_passed — routing reds to the dead queue
    would hide them from the very thing that remediates them.
    """
    _run_do_all(
        job,
        execute_return = "Test suite run complete. FAILURES DETECTED.",
        cost_summary   = _counts( passed=10, failed=3 ),
        suite_results  = { "unit": { "passed": 10, "failed": 3, "errors": 0, "skipped": 0 } },
        overall_status = "FAILED",
    )
    assert job.state == JobState.COMPLETED


def test_a_PARTIAL_run_stays_COMPLETED( job ):
    """
    Scope guard. A partial run (one tier ran, another did not) ALSO classifies as
    NOT EXECUTED, and deliberately keeps COMPLETED: its counts and all_passed already
    tell the truth, and routing partials to the dead queue is a behaviour change well
    outside this defect. If this test is ever changed, change it with a reason.
    """
    _run_do_all(
        job,
        execute_return = "Test suite run complete. NOT EXECUTED.",
        cost_summary   = _counts( passed=50 ),
        suite_results  = {
            "unit"       : { "passed": 50, "failed": 0, "errors": 0, "skipped": 0 },
            "typescript" : { "passed":  0, "failed": 0, "errors": 0, "skipped": 0 },
        },
        overall_status = "NOT EXECUTED",
    )
    assert job.state == JobState.COMPLETED


def test_a_DRY_RUN_stays_COMPLETED_even_though_its_counts_are_all_zero( dry_run_job ):
    """
    THE TRAP THIS GUARDS, and it nearly shipped: the dry-run path builds suite_results
    with all-zero counts too. A predicate keyed on the counts alone marks every dry run
    FAILED. `overall_status` is published by the REAL path only, which is what tells
    "a real run executed nothing" apart from "no real run happened".
    """
    _run_do_all(
        dry_run_job,
        execute_return = "Dry run complete.",
        cost_summary   = { "mode": "dry_run", "suites": [ "integration" ], "suites_run": 1 },
        suite_results  = { "integration": { "passed": 0, "failed": 0, "errors": 0, "skipped": 0 } },
        overall_status = None,
    )
    assert dry_run_job.state == JobState.COMPLETED


# ═════════════════════════════════════════════════════════════════════════════
# Helpers that had NO test in either tier (row e2099400 coverage sweep).
#
# Measured 2026-08-25: `_parse_pytest_progress_stdout`, `_parse_node_tap_summary`,
# `_terminate_process_group` and `_attestation_project_root` / the unpinned
# `_artifact_dir` arm were named ZERO times in src/tests/unit/ AND in
# src/cosa/tests/unit/agents/test_suite/. Three of them are recovery paths — the
# code that runs only when a tier has already gone wrong — which is exactly the
# code that must not be first exercised in production.
# ═════════════════════════════════════════════════════════════════════════════

class TestClassifyOutcomeCollectionError:
    """
    A collection error is not "zero tests passed" — it is "the suite never got to
    run". The distinction is the whole point of the verdict: 0/0/0/0 with a green
    label is the indistinguishable-zeros failure this classifier exists to end.
    """

    def test_collection_error_outranks_every_count( self ):
        assert TestSuiteJob._classify_outcome( 0, 0, 0, 0, 0, collection_error=True ) == "COLLECTION ERROR"

    def test_collection_error_wins_even_when_tests_passed( self ):
        # A partially-collected run can report passes AND a collection error. The
        # error must still be the verdict — some tests never got the chance to run.
        assert TestSuiteJob._classify_outcome( 12, 0, 0, 0, 0, collection_error=True ) == "COLLECTION ERROR"

    def test_without_a_collection_error_the_counts_decide( self ):
        assert TestSuiteJob._classify_outcome( 0, 0, 0, 0, 0, collection_error=False ) == "NOT EXECUTED"
        assert TestSuiteJob._classify_outcome( 5, 1, 0, 0, 0, collection_error=False ) == "FAILED"
        assert TestSuiteJob._classify_outcome( 5, 0, 0, 0, 0, collection_error=False ) == "PASSED"


class TestNodeTapSummaryParser:
    """
    Row 36e479ed — the typescript suite has no junit-xml, so its TAP trailer is the
    only evidence a green run produced. Without a parse it lands as 0/0/0/0 and is
    classified a failure.
    """

    TRAILER = "# tests 2245\n# pass 2240\n# fail 3\n# skipped 2\n"

    def test_reads_the_trailer_counts( self ):
        got = TestSuiteJob._parse_node_tap_summary( self.TRAILER )
        assert got == { "passed": 2240, "failed": 3, "skipped": 2, "errors": 0 }

    def test_absent_trailer_returns_none_not_zeros( self ):
        # None lets the caller keep its own default; a zero dict would assert
        # "the run produced nothing", which is a different and false claim.
        assert TestSuiteJob._parse_node_tap_summary( "no trailer here" ) is None
        assert TestSuiteJob._parse_node_tap_summary( "" ) is None

    def test_a_pass_line_alone_is_enough_and_the_rest_default_to_zero( self ):
        assert TestSuiteJob._parse_node_tap_summary( "# pass 7\n" ) == {
            "passed": 7, "failed": 0, "skipped": 0, "errors": 0 }

    def test_the_last_trailer_wins_so_nested_output_cannot_shadow_the_total( self ):
        # A test whose own output contains "# pass 1" must not become the run total.
        nested = "# pass 1\n# fail 0\nsome test output\n# pass 900\n# fail 4\n"
        assert TestSuiteJob._parse_node_tap_summary( nested )[ "passed" ] == 900
        assert TestSuiteJob._parse_node_tap_summary( nested )[ "failed" ] == 4

    def test_an_indented_pass_line_is_not_a_trailer( self ):
        # The trailer is anchored to line start; indented output is test content.
        assert TestSuiteJob._parse_node_tap_summary( "    # pass 5\n" ) is None


class TestNonPytestStdoutRoutesTypescriptToTap:
    def test_typescript_routes_to_the_tap_parser( self ):
        got = TestSuiteJob._parse_non_pytest_stdout( "typescript", "# pass 11\n# fail 0\n" )
        assert got == { "passed": 11, "failed": 0, "skipped": 0, "errors": 0 }

    def test_an_unknown_suite_type_is_not_parsed( self ):
        assert TestSuiteJob._parse_non_pytest_stdout( "unit", "# pass 11\n" ) is None

    def test_empty_stdout_is_not_parsed( self ):
        assert TestSuiteJob._parse_non_pytest_stdout( "typescript", "" ) is None


class TestPytestProgressRecovery:
    """
    Bug 8b93bcf5's mitigation: a KILLED tier never writes junit-xml and never
    reaches the summary block, so the compact progress stream is the only surviving
    evidence. Recovering it is what stops a killed run reporting 0/0/0/1 —
    indistinguishable from a tier that never started while sitting on real results.

    ⚠️ FILE-level only, by construction. Compact pytest output carries no test
    node-id, so these tests assert counts and filenames and deliberately do NOT
    assert per-test names — there are none to recover.
    """

    def test_counts_a_single_progress_line_and_names_the_file( self ):
        got = TestSuiteJob._parse_pytest_progress_stdout(
            "src/tests/smoke/test_alembic.py FFF.F                    [  1%]\n" )
        assert ( got[ "passed" ], got[ "failed" ] ) == ( 1, 4 )
        assert got[ "partial_files" ] == [ ( "src/tests/smoke/test_alembic.py", "FFF.F" ) ]

    def test_sums_across_files_and_counts_every_progress_char( self ):
        stdout = (
            "src/tests/unit/test_a.py ..s.E                            [ 10%]\n"
            "src/tests/unit/test_b.py .F..                             [ 20%]\n"
        )
        got = TestSuiteJob._parse_pytest_progress_stdout( stdout )
        assert got[ "passed" ]  == 6      # 3 dots in "..s.E", 3 in ".F.."
        assert got[ "failed" ]  == 1
        assert got[ "errors" ]  == 1
        assert got[ "skipped" ] == 1
        assert len( got[ "partial_files" ] ) == 2

    def test_a_wrapped_continuation_line_is_attributed_to_the_current_file( self ):
        # pytest wraps long progress runs onto a following line with no filename.
        stdout = (
            "src/tests/unit/test_long.py ....................          [ 30%]\n"
            "....                                                      [ 31%]\n"
        )
        got = TestSuiteJob._parse_pytest_progress_stdout( stdout )
        assert got[ "passed" ] == 24
        assert [ f for f, _ in got[ "partial_files" ] ] == [ "src/tests/unit/test_long.py" ] * 2

    def test_a_continuation_before_any_filename_is_ignored( self ):
        # Nothing to attribute it to — guessing a file would be worse than dropping it.
        assert TestSuiteJob._parse_pytest_progress_stdout( "....\n" ) is None

    def test_xfail_and_xpass_count_as_neither_pass_nor_failure( self ):
        got = TestSuiteJob._parse_pytest_progress_stdout( "t.py .xX.\n" )
        assert ( got[ "passed" ], got[ "failed" ], got[ "errors" ] ) == ( 2, 0, 0 )

    def test_tracebacks_and_banners_are_skipped_rather_than_miscounted( self ):
        # A traceback line contains dots. Counting them as passes would invent
        # results, which is worse than recovering none.
        stdout = (
            "======================= FAILURES =======================\n"
            "E   AssertionError: expected 1 got 2\n"
            "src/tests/unit/test_a.py ..                               [  5%]\n"
        )
        got = TestSuiteJob._parse_pytest_progress_stdout( stdout )
        assert got[ "passed" ] == 2
        assert len( got[ "partial_files" ] ) == 1

    def test_no_recognizable_progress_returns_none_not_a_zero_dict( self ):
        # The load-bearing distinction: None means "could not recover", a zero dict
        # would mean "recovered, and it was nothing".
        assert TestSuiteJob._parse_pytest_progress_stdout( "collecting ...\nERROR\n" ) is None
        assert TestSuiteJob._parse_pytest_progress_stdout( "" ) is None

    def test_spaces_inside_a_progress_run_are_ignored( self ):
        got = TestSuiteJob._parse_pytest_progress_stdout( "t.py .. ..                [ 9%]\n" )
        assert got[ "passed" ] == 4


class TestTerminateProcessGroup:
    """
    Bug 8b93bcf5, third defect: the runner is `bash <script>`, so terminate() hits
    bash alone and a grandchild keeps the inherited stdout pipe alive past the kill.
    The group signal is the fix; the fallbacks exist because this helper runs inside
    the caller's error path and must never raise a second failure into it.
    """

    def test_signals_the_whole_group_then_reaps( self, monkeypatch ):
        sent = []
        monkeypatch.setattr( os, "getpgid", lambda pid: 4242 )
        monkeypatch.setattr( os, "killpg", lambda pgid, sig: sent.append( ( pgid, sig ) ) )

        proc = MagicMock()
        proc.pid = 99
        proc.wait.return_value = 0

        TestSuiteJob._terminate_process_group( proc )

        import signal as _signal
        assert sent == [ ( 4242, _signal.SIGTERM ) ]        # reaped, so no SIGKILL
        proc.wait.assert_called_once()

    def test_escalates_to_sigkill_when_the_group_will_not_die( self, monkeypatch ):
        import signal as _signal
        import subprocess as _sp
        sent = []
        monkeypatch.setattr( os, "getpgid", lambda pid: 4242 )
        monkeypatch.setattr( os, "killpg", lambda pgid, sig: sent.append( sig ) )

        proc = MagicMock()
        proc.pid = 99
        proc.wait.side_effect = [ _sp.TimeoutExpired( "cmd", 10 ), 0 ]

        TestSuiteJob._terminate_process_group( proc )
        assert sent == [ _signal.SIGTERM, _signal.SIGKILL ]

    def test_falls_back_to_the_direct_child_when_the_group_is_gone( self, monkeypatch ):
        # No group left (ProcessLookupError) — the kill must still reach the child,
        # just without its descendants.
        def no_group( pid ):
            raise ProcessLookupError( "gone" )
        monkeypatch.setattr( os, "getpgid", no_group )

        proc = MagicMock()
        proc.pid = 99
        proc.wait.return_value = 0

        TestSuiteJob._terminate_process_group( proc )
        proc.terminate.assert_called_once()                 # SIGTERM arm

    def test_a_child_that_is_already_gone_does_not_raise( self, monkeypatch ):
        """
        Both the group AND the direct child are gone. The helper is called while the
        caller is already handling a failure, so it must swallow this and return —
        raising here would replace a measured timeout verdict with an exception.
        """
        def no_group( pid ):
            raise ProcessLookupError( "gone" )
        monkeypatch.setattr( os, "getpgid", no_group )

        proc = MagicMock()
        proc.pid = 99
        proc.terminate.side_effect = ProcessLookupError( "already reaped" )
        proc.kill.side_effect      = ProcessLookupError( "already reaped" )
        proc.wait.return_value     = 0

        TestSuiteJob._terminate_process_group( proc )       # must not raise

    def test_a_platform_without_killpg_still_kills_the_child( self, monkeypatch ):
        def no_killpg( pid ):
            raise AttributeError( "no killpg on this platform" )
        monkeypatch.setattr( os, "getpgid", no_killpg )

        proc = MagicMock()
        proc.pid = 99
        proc.wait.return_value = 0

        TestSuiteJob._terminate_process_group( proc )
        proc.terminate.assert_called_once()


class TestArtifactRootResolution:
    """
    `_isolate_artifact_root` pins `_ARTIFACT_DIR` for every test in this module, so
    the UNPINNED arm — the one production actually takes — was never executed here.
    These unpin it deliberately.
    """

    def test_unpinned_artifact_dir_resolves_through_attestation( self, tmp_path, monkeypatch ):
        import cosa.agents.test_suite.attestation as att
        target = tmp_path / "resolved" / "artifacts"
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", None )
        monkeypatch.setattr( att, "artifact_root", lambda: str( target ) )

        got = TestSuiteJob._artifact_dir()

        assert got == str( target )
        assert target.is_dir()                             # created here, not assumed

    def test_a_pinned_artifact_dir_is_created_and_returned( self, tmp_path, monkeypatch ):
        pinned = tmp_path / "pinned" / "deep"
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( pinned ) )
        assert TestSuiteJob._artifact_dir() == str( pinned )
        assert pinned.is_dir()

    def test_attestation_project_root_is_none_in_production( self, job, monkeypatch ):
        # None lets `attestation` resolve the real root. Any other value would send
        # a production attestation somewhere else.
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", None )
        assert job._attestation_project_root() is None

    def test_attestation_project_root_follows_a_pinned_dir( self, job, tmp_path, monkeypatch ):
        # Fail-closed: with a pinned dir, a test's attestation must never land in
        # the live ledger.
        monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
        assert job._attestation_project_root() == str( tmp_path )


# ═════════════════════════════════════════════════════════════════════════════
# The KILLED-TIER path inside _run_suite (bug 8b93bcf5).
#
# Everything below only executes when a tier has already gone wrong: the budget
# blew, or the stdout reader thread died. It was the last uncovered region of the
# file, which is the worst place to have one — the recovery code for a failure is
# the code most likely to be first exercised in production.
#
# The harness fakes Popen and runs the reader thread SYNCHRONOUSLY, so the queue
# contents are fully determined before the poll loop starts. Wall-clock is driven
# by a fake monotonic clock rather than real sleeps, so a timeout fires on a
# chosen iteration instead of after a real budget.
# ═════════════════════════════════════════════════════════════════════════════

import queue as _queue_mod
import subprocess as _subprocess_mod

import cosa.agents.test_suite.job as job_mod


class _FakePipe:
    """A stdout pipe that yields `lines` then EOF, and can die partway."""

    def __init__( self, lines, raise_after=None ):
        self._lines      = list( lines )
        self._raise_after = raise_after
        self._served      = 0

    def readline( self ):
        if self._raise_after is not None and self._served == self._raise_after:
            raise OSError( "pipe went away" )
        if not self._lines:
            return ""                                      # EOF
        self._served += 1
        return self._lines.pop( 0 )


class _SyncThread:
    """
    Stand-in for threading.Thread whose start() runs the target INLINE.

    The real reader thread races the poll loop, so what is in the queue when the
    timeout fires would be nondeterministic. Running it inline makes the queue a
    known quantity and the test a statement about the drain logic rather than
    about scheduling.
    """

    def __init__( self, target=None, args=(), daemon=None ):
        self._target = target
        self._args   = args
        self.daemon  = daemon

    def start( self ):
        self._target( *self._args )

    def join( self, timeout=None ):
        pass


class _FakeClock:
    """
    monotonic() returns 0.0 for the first `zero_calls` calls, then `after`.

    The jump is what makes a chosen poll iteration exceed the budget; before it,
    every elapsed check reads 0 and the loop just drains its queue.
    """

    def __init__( self, zero_calls, after=10_000.0, step=0.0 ):
        self.zero_calls = zero_calls
        self.after      = after
        self.step       = step                             # per-call advance AFTER the jump
        self.calls      = 0
        self.post       = 0

    def __call__( self ):
        self.calls += 1
        if self.calls <= self.zero_calls:
            return 0.0
        value = self.after + self.step * self.post
        self.post += 1
        return value


def _install_harness( monkeypatch, tmp_path, *, lines, poll_returns=None,
                      zero_calls=99, raise_after=None, returncode=0, clock_step=0.0 ):
    """
    Wire a fake `bash <script>` run. Returns ( project_root, fake_process ).

    `poll_returns` is what process.poll() answers; None keeps the child 'running'
    so the loop cannot exit normally and the timeout branch is reachable.
    """
    root   = tmp_path / "proj"
    script = root / "src/tests/run-unit-tests.sh"
    script.parent.mkdir( parents=True, exist_ok=True )
    script.write_text( "#!/bin/bash\ntrue\n" )

    proc            = MagicMock()
    proc.pid        = 4242
    proc.stdout     = _FakePipe( lines, raise_after=raise_after )
    proc.poll.return_value = poll_returns
    proc.returncode = returncode

    monkeypatch.setattr( job_mod.subprocess, "Popen", lambda *a, **k: proc )
    monkeypatch.setattr( job_mod.threading, "Thread", _SyncThread )
    monkeypatch.setattr( job_mod.time, "monotonic", _FakeClock( zero_calls, step=clock_step ) )
    monkeypatch.setattr( TestSuiteJob, "_terminate_process_group", staticmethod( lambda p: None ) )
    monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path / "artifacts" ) )
    return str( root ), proc


class TestRunSuiteTimeoutRecovery:

    def test_a_killed_tier_recovers_partial_counts_from_progress_output( self, job, tmp_path, monkeypatch ):
        """
        Bug 8b93bcf5's whole point: a killed tier used to report 0/0/0/1 —
        indistinguishable from a tier that never started — while sitting on
        results it had already produced. The progress stream is the only evidence
        that survives a kill, so it must be mined before the verdict is written.
        """
        lines = [
            "src/tests/unit/test_a.py ....F                            [ 10%]\n",
            "src/tests/unit/test_b.py ...s                             [ 20%]\n",
        ]
        # 1 start_time + 2 line iterations + 1 EOF iteration = 4 zero reads, then
        # the 5th elapsed check jumps past the budget.
        root, _ = _install_harness( monkeypatch, tmp_path, lines=lines, zero_calls=4 )

        result = job._run_suite( "unit", root )

        assert result[ "exit_code" ] == -2                 # the timeout verdict
        assert result[ "passed" ]  == 7                    # 4 + 3 recovered
        assert result[ "failed" ]  == 1
        assert result[ "skipped" ] == 1
        # +1 for the timeout itself — a killed tier can never report a clean bill.
        assert result[ "errors" ]  == 1
        assert "PARTIAL results recovered" in result[ "error" ]
        assert "FILE-level only" in result[ "error" ]

    def test_a_killed_tier_with_no_progress_output_says_so_plainly( self, job, tmp_path, monkeypatch ):
        # Nothing recoverable. The note must say that rather than let zero counts
        # imply the run produced nothing.
        lines   = [ "collecting ...\n" ]
        root, _ = _install_harness( monkeypatch, tmp_path, lines=lines, zero_calls=3 )

        result = job._run_suite( "unit", root )

        assert result[ "exit_code" ] == -2
        assert ( result[ "passed" ], result[ "failed" ], result[ "skipped" ] ) == ( 0, 0, 0 )
        assert result[ "errors" ] == 1
        assert "NO partial results could be recovered" in result[ "error" ]

    def test_the_drain_stops_on_an_empty_queue_rather_than_waiting_out_its_budget( self, job, tmp_path, monkeypatch ):
        """
        The drain replaced a BLOCKING `process.stdout.read()` that waited on any
        surviving grandchild holding the pipe — measured at 30.0s against a 1s
        budget. With the poll loop having already consumed everything, the drain
        must find the queue empty and return immediately, not sit on its deadline.
        """
        lines   = [ "src/tests/unit/test_a.py ..                       [  5%]\n" ]
        # 1 start + 1 line + 1 EOF + 1 empty-get iteration = 4, then timeout.
        root, _ = _install_harness( monkeypatch, tmp_path, lines=lines, zero_calls=4 )

        result = job._run_suite( "unit", root )

        assert result[ "exit_code" ] == -2
        assert result[ "passed" ] == 2                     # the consumed line still counted

    def test_a_reader_crash_found_during_the_drain_is_recorded_not_raised( self, job, tmp_path, monkeypatch ):
        """
        On the MAIN poll path a reader crash is re-raised, because silence there
        would report a crashed tier as green. In the DRAIN it must NOT raise: this
        path is already returning a measured timeout verdict, and converting that
        into an exception would lose the counts it just recovered. The marker is
        recorded in the log instead — and it is not a log line either, so a bare
        append would put a repr into the saved stdout.
        """
        lines = [ "src/tests/unit/test_a.py ...                        [  5%]\n" ]
        # readline raises after serving 1 line -> reader posts a crash marker, then
        # its finally posts EOF. Timeout fires after the first line is consumed, so
        # the marker is still queued when the drain runs.
        root, _ = _install_harness( monkeypatch, tmp_path, lines=lines,
                                    raise_after=1, zero_calls=2 )

        result = job._run_suite( "unit", root )

        assert result[ "exit_code" ] == -2                 # timeout verdict survives
        assert result[ "errors" ] == 1                     # not turned into a crash
        log_text = open( result[ "log_path" ] ).read()
        assert "stdout reader thread died" in log_text
        assert "OSError" in log_text


class TestRunSuiteCollectionDiagnosis:
    def test_a_diagnosis_that_raises_cannot_change_the_suite_outcome( self, job, tmp_path, monkeypatch ):
        """
        The diagnosis is a diagnostic, and a diagnostic must never be able to fail
        a run by raising. It fails soft to None and the suite result stands.
        """
        import cosa.utils.pytest_collection_diagnosis as diag_mod
        def boom( exit_code, stdout ):
            raise RuntimeError( "diagnosis blew up" )
        monkeypatch.setattr( diag_mod, "diagnose", boom )

        lines   = [ "src/tests/unit/test_a.py ..                       [100%]\n" ]
        # poll() returns 0 -> the child has exited, so the loop leaves normally.
        root, _ = _install_harness( monkeypatch, tmp_path, lines=lines,
                                    poll_returns=0, returncode=0 )

        result = job._run_suite( "unit", root )

        assert result[ "exit_code" ] == 0                  # outcome unchanged
        assert result[ "collection_diagnosis" ] is None    # failed soft

    def test_a_working_diagnosis_is_carried_on_the_result( self, job, tmp_path, monkeypatch ):
        import cosa.utils.pytest_collection_diagnosis as diag_mod
        monkeypatch.setattr( diag_mod, "diagnose", lambda exit_code, stdout: "looks fine" )

        lines   = [ "src/tests/unit/test_a.py ..                       [100%]\n" ]
        root, _ = _install_harness( monkeypatch, tmp_path, lines=lines,
                                    poll_returns=0, returncode=0 )

        assert job._run_suite( "unit", root )[ "collection_diagnosis" ] == "looks fine"


class TestProgressParserSkipsVerboseLines:
    def test_a_verbose_node_id_line_is_not_counted_as_progress( self ):
        # `-v` output carries a filename-shaped token but is not a progress run.
        # Counting its letters would invent results.
        stdout = (
            "src/tests/unit/test_a.py ..                               [  5%]\n"
            "src/tests/unit/test_a.py::test_x PASSED\n"
        )
        got = TestSuiteJob._parse_pytest_progress_stdout( stdout )
        assert got[ "passed" ] == 2
        assert len( got[ "partial_files" ] ) == 1


    def test_the_drain_gives_up_at_its_budget_instead_of_waiting_forever( self, job, tmp_path, monkeypatch ):
        """
        The drain is BOUNDED on purpose. A surviving grandchild can keep producing
        output past the kill, and the old blocking read waited for it — measured at
        30.0s against a 1s budget. Here the queue still holds lines when
        STDOUT_DRAIN_BUDGET_SECONDS expires, and the loop must exit on its deadline
        rather than keep draining.

        The clock advances 3s per check after the timeout fires, so the 5s drain
        budget lapses partway through a queue that still has work in it.
        """
        lines = [ f"src/tests/unit/test_{i}.py ..                      [ {i}%]\n"
                  for i in range( 8 ) ]
        # Timeout fires on the FIRST poll iteration, so nothing has been consumed
        # and all 8 lines plus the EOF sentinel are still queued.
        root, _ = _install_harness( monkeypatch, tmp_path, lines=lines,
                                    zero_calls=1, clock_step=3.0 )

        result = job._run_suite( "unit", root )

        assert result[ "exit_code" ] == -2
        # It drained SOME but not all — the budget cut it short, which is the point.
        assert 0 < result[ "passed" ] < 16                  # 8 files x 2 dots = 16 if fully drained
