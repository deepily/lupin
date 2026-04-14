"""
Unit tests for TestSuiteJob.

Tests job creation, configuration, pytest output parsing, state transitions,
dry run mode, and voice_io integration.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from cosa.agents.test_suite.job import TestSuiteJob, ALL_SUITE_COMPONENTS, _expand_all
from cosa.rest.job_state import JobState


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

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

        result = job.do_all()

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

    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_artifacts_populated( self, mock_voice_io, mock_run_suite, job ):
        """Artifacts should contain suite_results and cost_summary."""
        mock_run_suite.return_value = {
            "passed" : 10, "failed" : 2, "skipped" : 1, "errors" : 0,
            "exit_code" : 1, "log_path" : "/tmp/test.log", "duration" : 5.0,
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

    @patch( "cosa.agents.test_suite.job.TestSuiteJob._run_suite" )
    @patch( "cosa.agents.test_suite.voice_io" )
    def test_log_paths_in_artifacts( self, mock_voice_io, mock_run_suite, job ):
        """Log paths should be stored in artifacts."""
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
        assert result[ "log_path" ] and result[ "log_path" ].startswith( "/tmp/integration-" )

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

        # Redirect _LOG_SYMLINKS to a tmp location so the test doesn't stomp /tmp/unit-latest.log
        link = tmp_path / "unit-latest.log"
        monkeypatch.setattr( TestSuiteJob, "_LOG_SYMLINKS", { "unit": str( link ) } )

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
        assert ALL_SUITE_COMPONENTS == [ "unit", "smoke", "websocket", "integration", "e2e" ]

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
