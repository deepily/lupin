"""
Test Suite background job for queue-based execution.

Runs integration and/or E2E test suites as scheduled AgenticJobs within
the CJ Flow queue system. Delegates to existing shell scripts via
subprocess.Popen for cancellation support.

Example:
    job = TestSuiteJob(
        test_types = [ "integration", "e2e" ],
        user_id    = "user123",
        user_email = "user@example.com",
        session_id = "wise-penguin",
        dry_run    = True
    )
    result = job.do_all()  # Runs test suites and returns summary
"""

import asyncio
import json
import os
import subprocess
import time
import traceback as tb_mod
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, List, Dict
from zoneinfo import ZoneInfo

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState
import cosa.utils.util as cu


# Valid suite types and their script paths (relative to project root)
SUITE_SCRIPTS = {
    "unit"         : "src/tests/run-unit-tests.sh",
    "smoke"        : "src/tests/run-smoke-tests.sh",
    "smoke_direct" : "src/tests/run-smoke-direct.sh",
    "pytest_direct": "src/tests/run-pytest-direct.sh",    # Arbitrary pytest file (doc 16 follow-up)
    "websocket"    : "src/scripts/run-websocket-smoke-tests.sh",
    "integration"  : "src/tests/run-integration-tests.sh",
    "e2e"          : "src/scripts/run-e2e-ui-tests.sh",
    "all"            : "src/tests/run-all-tests.sh",
    "presentation"   : "src/tests/run-presentation-regression.sh",
}

# Test types that accept a file path as the first positional pytest arg
# (the shell script delegates to "$@" rather than running a fixed suite).
# Frontend mirrors this in notifications.js FILE_DRIVEN_TEST_TYPES.
FILE_DRIVEN_TEST_TYPES = frozenset( { "smoke_direct", "pytest_direct" } )

# Suites whose runner is pytest (or pytest-compatible) and therefore accepts
# --junit-xml. The websocket suite's backing script is a custom async
# orchestrator (smoke_test_runner.py), NOT pytest, and will error at arg-parse
# if --junit-xml is appended — so we must skip the injection for it. Other
# non-pytest suites can be added here as the project grows.
SUITES_SUPPORTING_JUNIT_XML = frozenset( {
    "unit", "smoke", "smoke_direct", "pytest_direct",
    "integration", "e2e", "all", "presentation",
} )

# Per-suite max execution timeout (seconds). Process is killed if exceeded.
# Values based on observed worst-case runtimes + 2x buffer. Tunable.
SUITE_TIMEOUTS_SECONDS = {
    "unit"         : 180,    #  3 min (fast, ~915 tests, no server)
    "smoke"        : 3600,   # 60 min (bumped from 1800s on 2026-04-21: observed 2456s on ts-f55d172d — 160 tests + container_preflight adds overhead; ~1.46x margin over observed)
    "smoke_direct" : 1200,   # 20 min (longest: Phase D live ~10 min)
    "pytest_direct": 1200,   # 20 min (arbitrary pytest file — match smoke_direct budget)
    "websocket"    : 300,    #  5 min (~50 tests, server + WS)
    "integration"  : 2000,   # 33 min (bumped from 1200s on 2026-04-21: observed 1392s when SWE-team dry-run tests ran — ~1.44x margin)
    "e2e"          : 2400,   # 40 min (~297 tests, ~17 min observed)
    "all"            : 3600,   # 60 min (sequential pyramid, ~25-35 min observed)
    "presentation"   : 1800,   # 30 min (render-only + Sonnet; +Opus/R2P with flags)
}
SUITE_TIMEOUT_DEFAULT_SECONDS = 600  # 10 min fallback for unknown types

# When the caller asks for "all", expand into these component suites and run
# each as its own entry in self.suite_results. This preserves partial results
# when one suite times out or crashes (pre-fix behavior was a single
# monolithic "all" subprocess whose timeout vaporized every other suite's output).
# Order matches src/tests/run-all-tests.sh's sequential pyramid.
ALL_SUITE_COMPONENTS = [ "unit", "smoke", "websocket", "integration", "e2e" ]


def _expand_all( test_types: List[ str ] ) -> List[ str ]:
    """
    Expand any "all" entry in `test_types` into ALL_SUITE_COMPONENTS, preserving
    order and deduping. Non-"all" entries pass through unchanged.

    Requires:
        - test_types is a list of strings (possibly empty)

    Ensures:
        - returns a new list; never mutates the input
        - "all" is replaced in place by ALL_SUITE_COMPONENTS
        - duplicates (e.g. test_types=["all","unit"]) are removed, first wins
    """
    expanded = []
    seen     = set()
    for t in test_types:
        candidates = ALL_SUITE_COMPONENTS if t == "all" else [ t ]
        for c in candidates:
            if c not in seen:
                seen.add( c )
                expanded.append( c )
    return expanded

class TestSuiteJob( AgenticJobBase ):
    """
    Background job for running test suites in CJ Flow.

    Wraps existing shell scripts (run-integration-tests.sh, run-e2e-ui-tests.sh)
    for execution within the COSA queue system. Supports scheduling, monopolize
    mode, cancellation, and voice notifications.

    Always runs with monopolize=True since test scripts hot-swap the database
    config, which is an exclusive operation.

    Attributes:
        test_types: List of suite types to run (e.g., ["integration", "e2e"])
        pytest_args: Optional extra pytest arguments
        dry_run: Simulate execution without running tests
        suite_results: Dict of per-suite results (populated after execution)
    """

    JOB_TYPE   = "test_suite"
    JOB_PREFIX = "ts"

    def __init__(
        self,
        test_types: List[ str ],
        user_id: str,
        user_email: str,
        session_id: str,
        pytest_args: Optional[ List[ str ] ] = None,
        dry_run: bool = False,
        auto_fix_on_failure: Optional[ bool ] = None,
        env_vars: Optional[ Dict[ str, str ] ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Test Suite job.

        Requires:
            - test_types is a non-empty list of valid suite names ("integration", "e2e")
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "ts-" prefix
            - monopolize=True (DB hot-swap is exclusive)
            - All parameters stored for execution

        Args:
            test_types: List of test suite types to run
            user_id: System ID of the job owner
            user_email: Email address of the user
            session_id: WebSocket session for notifications
            pytest_args: Optional extra pytest arguments (e.g., ["-v", "-k", "test_auth"])
            dry_run: Simulate execution without running tests
            auto_fix_on_failure: Per-run override for the TestSuiteCompletionWatchdog.
                None  → use INI default ("test fix expediter auto fix enabled")
                True  → force-enable TFE auto-dispatch for this run only
                False → force-disable TFE auto-dispatch for this run only
                The override is read by TestSuiteCompletionWatchdog Gate 1 and
                does NOT mutate the INI file.
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id,
            monopolize = True,
            debug      = debug,
            verbose    = verbose
        )

        # Test parameters
        self.test_types          = test_types or [ "integration", "e2e" ]
        self.pytest_args         = pytest_args or []
        self.dry_run             = dry_run
        self.auto_fix_on_failure = auto_fix_on_failure
        self.env_vars            = self._filter_env_vars( env_vars or {} )

        # Results (populated after execution)
        self.suite_results = {}
        self.cost_summary  = None  # Required by queues.py for unified job interface

    # Env vars exposed to the pytest subprocess are prefix-filtered so arbitrary
    # client-supplied vars can't leak into the runner. Extend the allowlist here
    # when adding new test-scoped env contracts.
    _ENV_VAR_ALLOWED_PREFIXES = ( "TFE_", "BFE_", "LUPIN_TEST_" )

    @classmethod
    def _filter_env_vars( cls, raw: Dict[ str, str ] ) -> Dict[ str, str ]:
        """Drop keys that don't match the allowlist; coerce values to str."""
        if not raw:
            return {}
        filtered = {}
        dropped  = []
        for k, v in raw.items():
            if not isinstance( k, str ):
                dropped.append( repr( k ) )
                continue
            if any( k.startswith( p ) for p in cls._ENV_VAR_ALLOWED_PREFIXES ):
                filtered[ k ] = str( v )
            else:
                dropped.append( k )
        if dropped:
            print( f"[TestSuiteJob] WARNING: dropped env_vars outside allowlist {cls._ENV_VAR_ALLOWED_PREFIXES}: {dropped}" )
        return filtered

    @classmethod
    def from_config( cls, config_mgr, user_id, user_email, session_id, debug=False ):
        """
        Create TestSuiteJob with defaults from configuration.

        Requires:
            - config_mgr is a valid ConfigurationManager instance
            - user_id, user_email, session_id are non-empty strings

        Ensures:
            - Returns TestSuiteJob with config-derived defaults

        Args:
            config_mgr: ConfigurationManager instance
            user_id: System ID of the job owner
            user_email: Email address of the user
            session_id: WebSocket session for notifications
            debug: Enable debug output

        Returns:
            TestSuiteJob: Configured job instance
        """
        default_types = config_mgr.get( "test suite default types", default="integration,e2e" )
        test_types    = [ t.strip() for t in default_types.split( "," ) ]

        default_args  = config_mgr.get( "test suite default pytest args", default="" )
        pytest_args   = [ a.strip() for a in default_args.split() if a.strip() ] if default_args else []

        return cls(
            test_types  = test_types,
            user_id     = user_id,
            user_email  = user_email,
            session_id  = session_id,
            pytest_args = pytest_args,
            debug       = debug
        )

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns:
            str: Human-readable job description (e.g., "[Tests] integration, e2e")
        """
        suites = ", ".join( self.test_types )
        return f"[Tests] {suites}"

    def do_all( self ) -> str:
        """
        Execute test suites and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing test results
        """
        if self.debug: print( f"[TestSuiteJob] Starting do_all() for: {self.test_types}" )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            # Check if cancellation was requested during execution
            if self._cancel_requested:
                self.state                 = JobState.CANCELLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.error                 = "Cancelled by user request"
                self.answer_conversational = result or "Test suite run was cancelled by the user."
                if self.debug: print( "[TestSuiteJob] Cancelled by user request" )
                return self.answer_conversational

            self.state        = JobState.COMPLETED
            self.completed_at = cu.get_current_datetime_iso()
            self.result       = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[TestSuiteJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()

            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = f"{type( e ).__name__}: {e}\n\n{tb_str}"
            self.answer_conversational = (
                f"Test suite run failed: **{type( e ).__name__}**: {e}\n\n"
                f"```\n{tb_str}\n```"
            )

            print( f"[TestSuiteJob] Failed: {e}" )
            print( tb_str )

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    async def _execute( self ) -> str:
        """
        Internal async test suite execution.

        Runs each suite sequentially, always completing all suites regardless
        of individual failures. Reports progress via voice_io notifications.

        Returns:
            str: Conversational summary of all suite results
        """
        from cosa.agents.test_suite import voice_io, cosa_interface

        # Re-establish core voice_io binding (import-order race)
        voice_io.reconfigure()

        # Handle dry-run mode
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Set sender_id and target_user for notifications
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all notify() calls
        voice_io.set_job_id( self.id_hash )

        project_root = cu.get_project_root()

        if self.debug:
            print( f"[TestSuiteJob] Suites: {self.test_types}" )
            print( f"[TestSuiteJob] Pytest args: {self.pytest_args}" )
            print( f"[TestSuiteJob] Project root: {project_root}" )

        try:
            await voice_io.notify(
                f"Starting test suite run: {', '.join( self.test_types )}",
                priority="medium",
                queue_name="run"
            )

            # Expand "all" into component suites so each runs with its own
            # timeout and its own suite_results entry. self.test_types stays
            # unchanged so the report filename ("all-results.md") and the
            # user-visible label in notifications/snapshots remain meaningful.
            suites_to_run = _expand_all( self.test_types )
            if self.debug and suites_to_run != list( self.test_types ):
                print( f"[TestSuiteJob] Expanded {self.test_types} -> {suites_to_run}" )

            for suite_type in suites_to_run:
                if self._cancel_requested:
                    await voice_io.notify(
                        "Test suite run cancelled by user.",
                        priority="medium",
                        queue_name="run"
                    )
                    break

                await voice_io.notify(
                    f"Starting {suite_type} tests...",
                    priority="low",
                    queue_name="run"
                )

                result = self._run_suite( suite_type, project_root )
                self.suite_results[ suite_type ] = result

                # Report per-suite results
                suite_found  = result[ "passed" ] + result[ "failed" ] + result[ "skipped" ] + result[ "errors" ]
                status       = "PASSED" if suite_found > 0 and ( result[ "failed" ] + result[ "errors" ] ) == 0 else "FAILED"
                await voice_io.notify(
                    f"{suite_type}: {status} — {result[ 'passed' ]} passed, "
                    f"{result[ 'failed' ]} failed, {result[ 'errors' ]} errors, "
                    f"{result[ 'skipped' ]} skipped",
                    priority="low",
                    queue_name="run"
                )

            # Build summary
            total_passed  = sum( r[ "passed" ] for r in self.suite_results.values() )
            total_failed  = sum( r[ "failed" ] for r in self.suite_results.values() )
            total_skipped = sum( r[ "skipped" ] for r in self.suite_results.values() )
            total_errors  = sum( r[ "errors" ] for r in self.suite_results.values() )
            total_found   = total_passed + total_failed + total_skipped + total_errors
            # Determine pass/fail from parsed results, not exit code — exit code can be
            # non-zero for warnings or cleanup even when all tests pass (335/0/0 false positive)
            all_passed    = total_found > 0 and ( total_failed + total_errors ) == 0

            # Store artifacts + cost_summary (required by queues.py unified interface)
            self.cost_summary = {
                "suites_run"    : len( self.suite_results ),
                "total_passed"  : total_passed,
                "total_failed"  : total_failed,
                "total_errors"  : total_errors,
                "total_skipped" : total_skipped,
                "all_passed"    : all_passed,
            }
            self.artifacts[ "suite_results" ] = self.suite_results
            self.artifacts[ "cost_summary" ]  = self.cost_summary
            for suite_type, result in self.suite_results.items():
                if result.get( "log_path" ):
                    self.artifacts[ f"{suite_type}_log" ] = result[ "log_path" ]

            overall = "ALL PASSED" if all_passed else "FAILURES DETECTED"

            # ─── Write full report to io/ for the document viewer ───
            import urllib.parse
            import pathlib

            io_base    = project_root + "/io"
            report_dir = io_base + "/test-suite"
            pathlib.Path( report_dir ).mkdir( parents=True, exist_ok=True )

            # Timestamp in project-local timezone (America/New_York) with DST-aware
            # -EST/-EDT suffix, per project filename convention. The container's system
            # clock is UTC, so we explicitly convert rather than relying on datetime.now().
            now_local  = datetime.now( ZoneInfo( "America/New_York" ) )
            timestamp  = now_local.strftime( "%Y.%m.%d-at-%H:%M-%Z" )
            suites_str = "-".join( self.test_types )
            report_rel = f"test-suite/{timestamp}-{suites_str}-results.md"
            report_abs = f"{io_base}/{report_rel}"

            # Build markdown report with full stdout for each suite
            report_lines = [
                f"# Test Suite Report — {overall}",
                f"",
                f"**Date**: {now_local.strftime( '%Y-%m-%d %H:%M:%S %Z' )}  ",
                f"**Suites**: {', '.join( self.test_types )}  ",
                f"**Total**: {total_passed} passed, {total_failed} failed, {total_errors} errors, {total_skipped} skipped",
                f"",
                f"---",
                f"",
            ]

            for suite_type, result in self.suite_results.items():
                sf   = result[ "passed" ] + result[ "failed" ] + result[ "skipped" ] + result[ "errors" ]
                icon = "PASS" if sf > 0 and ( result[ "failed" ] + result[ "errors" ] ) == 0 else "FAIL"
                report_lines.append( f"## {suite_type} — {icon}" )
                report_lines.append( f"" )
                report_lines.append( f"| Metric | Count |" )
                report_lines.append( f"|--------|-------|" )
                report_lines.append( f"| Passed | {result[ 'passed' ]} |" )
                report_lines.append( f"| Failed | {result[ 'failed' ]} |" )
                report_lines.append( f"| Skipped | {result[ 'skipped' ]} |" )
                report_lines.append( f"| Errors | {result[ 'errors' ]} |" )
                report_lines.append( f"| Duration | {result[ 'duration' ]:.1f}s |" )
                report_lines.append( f"" )

                # Include full stdout from log file
                log_path = result.get( "log_path" )
                if log_path:
                    try:
                        full_output = pathlib.Path( log_path ).read_text()
                        report_lines.append( f"<details><summary>Full output ({len( full_output.splitlines() )} lines)</summary>" )
                        report_lines.append( f"" )
                        report_lines.append( f"```" )
                        report_lines.append( full_output )
                        report_lines.append( f"```" )
                        report_lines.append( f"</details>" )
                    except ( FileNotFoundError, OSError ):
                        report_lines.append( f"*(log file not available)*" )
                else:
                    crash_output = result.get( "startup_crash_output" )
                    if crash_output:
                        report_lines.append( f"**STARTUP CRASH** (exit={result[ 'exit_code' ]}):" )
                        report_lines.append( f"```" )
                        report_lines.append( crash_output )
                        report_lines.append( f"```" )

                report_lines.append( f"" )
                report_lines.append( f"---" )
                report_lines.append( f"" )

            pathlib.Path( report_abs ).write_text( "\n".join( report_lines ) )
            self.artifacts[ "report_path" ] = report_rel
            self.report_path                = report_abs

            # ─── Write remediation snapshot JSON if any failures/errors ───
            if total_failed + total_errors > 0:
                snapshot = {
                    "schema_version" : "1.0",
                    "timestamp"      : timestamp,
                    "suites_run"     : list( self.test_types ),
                    "summary"        : {
                        "total_passed"  : total_passed,
                        "total_failed"  : total_failed,
                        "total_skipped" : total_skipped,
                        "total_errors"  : total_errors,
                        "all_passed"    : False,
                    },
                    "failures"       : [],
                }
                for suite_type, result in self.suite_results.items():
                    for fd in result.get( "failure_details", [] ):
                        fd_copy            = dict( fd )
                        fd_copy[ "suite" ] = suite_type
                        snapshot[ "failures" ].append( fd_copy )

                snapshot_rel = f"test-suite/{timestamp}-{suites_str}-remediation.json"
                snapshot_abs = f"{io_base}/{snapshot_rel}"
                pathlib.Path( snapshot_abs ).write_text(
                    json.dumps( snapshot, indent=2 )
                )
                self.artifacts[ "remediation_snapshot_path" ] = snapshot_rel
                self.artifacts[ "remediation_snapshot" ]      = snapshot

            # ─── Build abstract with summary ───
            suite_lines = []
            for suite_type, result in self.suite_results.items():
                sf   = result[ "passed" ] + result[ "failed" ] + result[ "skipped" ] + result[ "errors" ]
                icon = "PASS" if sf > 0 and ( result[ "failed" ] + result[ "errors" ] ) == 0 else "FAIL"
                line = ( f"- **{suite_type}**: {icon} — "
                         f"{result[ 'passed' ]} passed, {result[ 'failed' ]} failed, "
                         f"{result[ 'errors' ]} errors, {result[ 'skipped' ]} skipped" )
                crash_output = result.get( "startup_crash_output" )
                if crash_output:
                    line += f"\n  **STARTUP CRASH** (exit={result[ 'exit_code' ]}): `{crash_output[ :500 ]}`"
                suite_lines.append( line )

            abstract = ( f"**Test Suite Results: {overall}**\n\n"
                         + "\n".join( suite_lines )
                         + f"\n\n**Total**: {total_passed} passed, {total_failed} failed, {total_errors} errors, {total_skipped} skipped" )
            self.artifacts[ "abstract" ] = abstract

            await voice_io.notify(
                f"Test suite complete: {overall}",
                priority="medium",
                abstract=abstract,
                queue_name="run"
            )

            # Conversational answer
            summary = ( f"Test suite run complete. {overall}.\n\n"
                        + "\n".join( f"  {st}: {r[ 'passed' ]} passed, {r[ 'failed' ]} failed, {r[ 'errors' ]} errors, {r[ 'skipped' ]} skipped"
                                    for st, r in self.suite_results.items() )
                        + f"\n\n  Total: {total_passed} passed, {total_failed} failed, {total_errors} errors, {total_skipped} skipped" )

            return summary

        finally:
            voice_io.clear_job_id()

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """
        Execute dry-run mode with breadcrumb notifications.

        Simulates the test suite workflow without actually running tests.

        Requires:
            - voice_io is a configured voice I/O module
            - cosa_interface is a configured COSA interface module

        Ensures:
            - Breadcrumb notifications sent for each suite
            - Mock artifacts populated
            - Returns mock conversational summary

        Args:
            voice_io: Voice I/O module for notifications
            cosa_interface: COSA interface module for sender ID

        Returns:
            str: Mock conversational summary
        """
        # Set sender_id and target_user
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        voice_io.set_job_id( self.id_hash )

        if self.debug: print( f"[TestSuiteJob] DRY RUN MODE for: {self.test_types}" )

        try:
            await voice_io.notify(
                f"Dry run: Starting test suite simulation for {', '.join( self.test_types )}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( 0.5 )

            for suite_type in self.test_types:
                await voice_io.notify(
                    f"[DRY RUN] Would run {suite_type} tests",
                    priority="low",
                    job_id=self.id_hash,
                    queue_name="run"
                )
                await asyncio.sleep( 0.5 )

            # Mock results
            self.suite_results = {
                suite_type: {
                    "passed"    : 0,
                    "failed"    : 0,
                    "skipped"   : 0,
                    "errors"    : 0,
                    "exit_code" : 0,
                    "log_path"  : None,
                    "duration"  : 0.0,
                }
                for suite_type in self.test_types
            }

            self.cost_summary = {
                "mode"       : "dry_run",
                "suites"     : self.test_types,
                "suites_run" : len( self.test_types ),
            }
            self.artifacts[ "suite_results" ] = self.suite_results
            self.artifacts[ "cost_summary" ]  = self.cost_summary

            abstract = (
                f"**Dry Run Complete**\n\n"
                f"- Suites: {', '.join( self.test_types )}\n"
                f"- Pytest args: {self.pytest_args or '(none)'}\n"
                f"- monopolize: True"
            )

            await voice_io.notify(
                "Dry run complete! Test suite simulation finished.",
                priority="medium",
                abstract=abstract,
                job_id=self.id_hash,
                queue_name="run"
            )

            return f"Dry run complete. Would have run: {', '.join( self.test_types )}"

        finally:
            voice_io.clear_job_id()

    def _run_suite( self, suite_type: str, project_root: str ) -> Dict:
        """
        Run a single test suite via subprocess.

        Uses subprocess.Popen with a poll loop to support cancellation.
        Does NOT use --bg flag (the AgenticJob IS the background runner).

        Requires:
            - suite_type is "integration" or "e2e"
            - project_root is a valid directory path

        Ensures:
            - Returns dict with passed/failed/skipped/errors/exit_code/log_path/duration
            - Subprocess is terminated if cancellation requested

        Args:
            suite_type: Type of test suite ("integration" or "e2e")
            project_root: Absolute path to project root

        Returns:
            dict: Test results with keys: passed, failed, skipped, errors, exit_code, log_path, duration
        """
        script_rel = SUITE_SCRIPTS.get( suite_type )
        if not script_rel:
            return {
                "passed"    : 0,
                "failed"    : 0,
                "skipped"   : 0,
                "errors"    : 0,
                "exit_code" : 1,
                "log_path"  : None,
                "duration"  : 0.0,
                "error"     : f"Unknown suite type: {suite_type}",
            }

        script_path = os.path.join( project_root, script_rel )

        if not os.path.exists( script_path ):
            return {
                "passed"    : 0,
                "failed"    : 0,
                "skipped"   : 0,
                "errors"    : 0,
                "exit_code" : 1,
                "log_path"  : None,
                "duration"  : 0.0,
                "error"     : f"Script not found: {script_path}",
            }

        # Build command — pass through extra pytest args, never use --bg
        # Strip --bg: harmful when running as a subprocess (detaches, breaks tracking)
        sanitized_args = [ arg for arg in self.pytest_args if arg != "--bg" ]
        if len( sanitized_args ) < len( self.pytest_args ):
            print( f"[TestSuiteJob] WARNING: Stripped --bg flag from pytest_args (harmful for subprocess-tracked runs)" )

        # Append per-suite extra pytest args from INI (Phase 6 / Cluster B fix
        # for 2026-04-30 post-mortem). The smoke suite needs --auto-proxy +
        # --cost-cap-usd to satisfy the pre_run_hook of the two live_smoke
        # tests (test_presentation_live_smoke, test_research_to_presentation_
        # live_smoke); other suites are empty by default. The INI key shape is
        # "test suite {suite_type} extra pytest args" — empty / missing is OK.
        # `src/tests/smoke/conftest.py` registers --auto-proxy / --cost-cap-usd
        # / --no-confirm / --group / --scenario-id so pytest accepts the flags
        # without erroring; the actual flag values are consumed by each test's
        # own argparse (see live_pipeline_base.py:619).
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            extra_args_cfg = ConfigurationManager(
                env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS"
            )
            extra_args_raw = extra_args_cfg.get(
                f"test suite {suite_type} extra pytest args",
                default="",
                return_type="string"
            )
            if extra_args_raw:
                extra_args = [ a for a in extra_args_raw.split() if a.strip() ]
                if extra_args:
                    sanitized_args = sanitized_args + extra_args
                    if self.debug:
                        print( f"[TestSuiteJob] Appended per-suite extra args for "
                               f"'{suite_type}': {extra_args}" )
        except Exception as e:
            # ConfigurationManager unavailable — log and continue with the
            # caller-supplied args only. This is a best-effort augmentation;
            # failure to read the INI must not block the suite.
            print( f"[TestSuiteJob] WARNING: Could not load extra pytest args "
                   f"for '{suite_type}' suite from INI: {e}" )

        # Inject --junit-xml for structured result parsing (no brittle regex).
        # Gated by SUITES_SUPPORTING_JUNIT_XML — non-pytest runners (e.g. the
        # websocket async orchestrator) will error at arg-parse if this flag
        # is appended, killing the subprocess before any tests run.
        if suite_type in SUITES_SUPPORTING_JUNIT_XML:
            junit_xml_path = f"/tmp/{suite_type}-junit-{datetime.now().strftime( '%Y%m%d-%H%M%S' )}.xml"
            sanitized_args += [ f"--junit-xml={junit_xml_path}" ]
        else:
            junit_xml_path = None  # _parse_junit_xml(None) returns zero-counts without raising

        cmd = [ "bash", script_path ] + sanitized_args

        if self.debug: print( f"[TestSuiteJob] Running: {' '.join( cmd )}" )

        start_time = time.monotonic()

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=project_root,
                text=True,
                env={
                    **os.environ,
                    "LUPIN_ROOT"          : project_root,
                    "LUPIN_TEST_PORT"     : os.environ.get( "PORT", "7999" ),
                    # When the runner executes inside lupin-rest-test, the server
                    # lives on internal port 7999 (host :8000 mapping is inaccessible
                    # from within the container). Honor any caller-set value first.
                    "LUPIN_TEST_BASE_URL" : os.environ.get( "LUPIN_TEST_BASE_URL", f"http://localhost:{os.environ.get( 'PORT', '7999' )}" ),
                    # Caller-supplied env (allowlist-filtered in __init__) overrides defaults.
                    **self.env_vars,
                }
            )

            # Per-suite timeout (seconds)
            timeout_secs = SUITE_TIMEOUTS_SECONDS.get( suite_type, SUITE_TIMEOUT_DEFAULT_SECONDS )
            if self.debug: print( f"[TestSuiteJob] {suite_type} timeout: {timeout_secs}s" )

            # Poll loop for cancellation support + timeout enforcement
            stdout_lines = []
            while True:
                # Check for cancellation
                if self._cancel_requested:
                    process.terminate()
                    try:
                        process.wait( timeout=10 )
                    except subprocess.TimeoutExpired:
                        process.kill()
                    duration = time.monotonic() - start_time
                    return {
                        "passed"    : 0,
                        "failed"    : 0,
                        "skipped"   : 0,
                        "errors"    : 0,
                        "exit_code" : -1,
                        "log_path"  : None,
                        "duration"  : duration,
                        "error"     : "Cancelled by user",
                    }

                # Check for timeout
                elapsed = time.monotonic() - start_time
                if elapsed > timeout_secs:
                    print( f"[TestSuiteJob] TIMEOUT: {suite_type} exceeded {timeout_secs}s, killing process" )
                    process.terminate()
                    try:
                        process.wait( timeout=10 )
                    except subprocess.TimeoutExpired:
                        process.kill()

                    # Drain anything still buffered after terminate so the tail
                    # captured in the synthetic failure reflects reality.
                    try:
                        remaining = process.stdout.read()
                        if remaining:
                            stdout_lines.append( remaining )
                    except ( OSError, ValueError ):
                        pass

                    stdout_text = "".join( stdout_lines )
                    log_path    = self._write_stdout_log( suite_type, stdout_text )
                    tail_text   = "".join( stdout_lines[ -40: ] ).strip()

                    return {
                        "passed"          : 0,
                        "failed"          : 0,
                        "skipped"         : 0,
                        "errors"          : 1,
                        "exit_code"       : -2,
                        "log_path"        : log_path,
                        "duration"        : elapsed,
                        "error"           : f"Timeout: {suite_type} exceeded {timeout_secs}s",
                        "failure_details" : [ self._synth_failure_detail(
                            suite_type     = suite_type,
                            name           = "timeout",
                            elapsed        = elapsed,
                            message        = f"Subprocess killed after {timeout_secs}s budget (actual {elapsed:.1f}s)",
                            traceback_text = tail_text,
                        ) ],
                    }

                # Read available output
                line = process.stdout.readline()
                if line:
                    stdout_lines.append( line )
                    if self.verbose: print( line, end="" )

                # Check if process has finished
                if line == "" and process.poll() is not None:
                    break

            duration  = time.monotonic() - start_time
            exit_code = process.returncode
            stdout    = "".join( stdout_lines )

            # Write captured stdout to a log file (always, regardless of --bg mode)
            # This ensures crash output is always available for post-mortem diagnosis
            log_path = self._write_stdout_log( suite_type, stdout )

            # Parse structured junit-xml report (falls back to zeros if file missing)
            parsed = self._parse_junit_xml( junit_xml_path )
            # TODO: Re-enable after debugging empty failures array
            # try:
            #     os.unlink( junit_xml_path )
            # except OSError:
            #     pass

            # WG-7 (2026-04-28): For non-pytest suites (websocket today), the
            # junit-xml path is None, so _parse_junit_xml returned zero counts.
            # Fall back to parsing the runner's stdout summary so we don't
            # mis-classify a 50/50 PASS as FAIL with metrics 0/0/0/0.
            if junit_xml_path is None and parsed[ "passed" ] == 0 and parsed[ "failed" ] == 0:
                fallback = self._parse_non_pytest_stdout( suite_type, stdout )
                if fallback is not None:
                    parsed.update( fallback )

            parsed[ "exit_code" ] = exit_code
            parsed[ "log_path" ]  = log_path
            parsed[ "duration" ]  = duration

            # Capture stdout tail when subprocess crashed with no test output
            total_found = parsed[ "passed" ] + parsed[ "failed" ] + parsed[ "skipped" ] + parsed[ "errors" ]
            if exit_code != 0 and total_found == 0:
                tail_lines  = stdout_lines[ -20: ] if stdout_lines else [ "(no output captured)" ]
                parsed[ "startup_crash_output" ] = "".join( tail_lines ).strip()

            if self.debug:
                print( f"[TestSuiteJob] {suite_type} finished: exit={exit_code}, "
                       f"passed={parsed[ 'passed' ]}, failed={parsed[ 'failed' ]}, "
                       f"duration={duration:.1f}s" )

            return parsed

        except Exception as e:
            duration = time.monotonic() - start_time
            tb_text  = tb_mod.format_exc()

            # Best-effort: persist whatever stdout we managed to capture before
            # the exception so post-mortem is possible. stdout_lines may be
            # undefined if Popen itself failed — guard accordingly.
            try:
                stdout_so_far = "".join( stdout_lines )
            except NameError:
                stdout_so_far = ""
            log_path = self._write_stdout_log( suite_type, stdout_so_far )

            return {
                "passed"          : 0,
                "failed"          : 0,
                "skipped"         : 0,
                "errors"          : 1,
                "exit_code"       : 1,
                "log_path"        : log_path,
                "duration"        : duration,
                "error"           : str( e ),
                "failure_details" : [ self._synth_failure_detail(
                    suite_type     = suite_type,
                    name           = "exception",
                    elapsed        = duration,
                    message        = f"{type( e ).__name__}: {e}",
                    traceback_text = tb_text,
                ) ],
            }

    # Map suite_type to canonical /tmp/<name>-latest.log symlink used across scripts
    _LOG_SYMLINKS = {
        "unit"         : "/tmp/unit-latest.log",
        "smoke"        : "/tmp/smoke-latest.log",
        "smoke_direct" : "/tmp/smoke-direct-latest.log",
        "pytest_direct": "/tmp/pytest-direct-latest.log",
        "websocket"    : "/tmp/websocket-latest.log",
        "integration"  : "/tmp/integration-latest.log",
        "e2e"          : "/tmp/e2e-ui-latest.log",
        "all"          : "/tmp/all-tests-latest.log",
    }

    @classmethod
    def _write_stdout_log( cls, suite_type: str, stdout_text: str ) -> Optional[ str ]:
        """
        Persist captured subprocess stdout to a timestamped file and refresh the
        canonical /tmp/<suite>-latest.log symlink.

        Requires:
            - suite_type is a known SUITE_SCRIPTS key (unknown keys are a no-op)
            - stdout_text is a (possibly empty) string

        Ensures:
            - returns the absolute path of the written log, or None if nothing
              was written (unknown suite or empty text)
            - updates /tmp/<suite>-latest.log symlink atomically (unlink+symlink)
        """
        symlink_path = cls._LOG_SYMLINKS.get( suite_type )
        if not ( symlink_path and stdout_text ):
            return None
        import pathlib
        actual_log = f"/tmp/{suite_type}-{datetime.now().strftime( '%Y%m%d-%H%M%S' )}.log"
        pathlib.Path( actual_log ).write_text( stdout_text )
        pathlib.Path( symlink_path ).unlink( missing_ok=True )
        pathlib.Path( symlink_path ).symlink_to( actual_log )
        return actual_log

    @staticmethod
    def _synth_failure_detail( suite_type: str, name: str, elapsed: float, message: str, traceback_text: str ) -> Dict:
        """
        Build a single failure_details entry for synthesized ERRORs (timeout,
        caught exception, etc.) so the remediation snapshot's `failures` array
        is never empty when `errors > 0`. Matches the shape produced by
        _parse_junit_xml for real testcase <failure>/<error> elements.
        """
        return {
            "classname" : f"TestSuiteJob.{suite_type}",
            "name"      : name,
            "time"      : f"{elapsed:.1f}",
            "type"      : "ERROR",
            "message"   : message,
            "traceback" : traceback_text or "(no output captured)",
        }

    @staticmethod
    def _parse_junit_xml( xml_path: str ) -> Dict:
        """
        Parse pytest junit-xml report for pass/fail/skip/error counts.

        Uses pytest's built-in --junit-xml output for structured, order-independent
        result extraction. No brittle regex parsing of text output.

        Requires:
            - xml_path is a file path (may not exist if pytest crashed before writing)

        Ensures:
            - Returns dict with passed, failed, skipped, errors keys (all int)
            - Returns zeros if file not found or unparseable

        Args:
            xml_path: Path to the junit-xml report file

        Returns:
            dict: Parsed counts with keys: passed, failed, skipped, errors
        """
        result = {
            "passed"  : 0,
            "failed"  : 0,
            "skipped" : 0,
            "errors"  : 0,
        }

        # None path = suite is not pytest-backed (e.g. websocket). Skip parse,
        # return zero-counts. Caller already captured stdout via _write_stdout_log.
        if not xml_path:
            return result

        try:
            # Debug: check raw file content before parsing
            with open( xml_path, "r" ) as f:
                raw = f.read()
            print( f"[DEBUG _parse_junit_xml] file={xml_path}, size={len( raw )}, has_failure={'<failure' in raw}, has_error={'<error' in raw}" )

            # Use ET.fromstring() instead of ET.parse() — confirmed that ET.parse()
            # strips <failure> children in the live server process (CPython C accelerator issue)
            root      = ET.fromstring( raw )
            testsuite = root if root.tag == "testsuite" else root.find( "testsuite" )

            print( f"[DEBUG _parse_junit_xml] root.tag={root.tag}, testsuite={'found' if testsuite is not None else 'None'}" )

            if testsuite is not None:
                tests    = int( testsuite.get( "tests", 0 ) )
                failures = int( testsuite.get( "failures", 0 ) )
                errors   = int( testsuite.get( "errors", 0 ) )
                skipped  = int( testsuite.get( "skipped", 0 ) )

                result[ "passed" ]  = tests - failures - errors - skipped
                result[ "failed" ]  = failures
                result[ "skipped" ] = skipped
                result[ "errors" ]  = errors

                # Extract per-failure details for remediation snapshots
                # Use root (not testsuite) to find testcases across ALL <testsuite> children
                failure_details = []
                loop_count      = 0
                children_count  = 0
                for testcase in root.iter( "testcase" ):
                    loop_count += 1
                    failure_el = testcase.find( "failure" )
                    error_el   = testcase.find( "error" )
                    el         = failure_el if failure_el is not None else error_el
                    if el is not None:
                        children_count += 1
                    if loop_count <= 3 or el is not None:
                        print( f"[DEBUG] tc={testcase.get( 'name', '?' )[:40]}, children={[c.tag for c in testcase]}, failure_el={failure_el}, error_el={error_el}" )
                    if el is None:
                        continue
                    failure_details.append( {
                        "classname" : testcase.get( "classname", "" ),
                        "name"      : testcase.get( "name", "" ),
                        "time"      : testcase.get( "time", "" ),
                        "type"      : "FAILED" if failure_el is not None else "ERROR",
                        "message"   : el.get( "message", "" ),
                        "traceback" : ( el.text or "" ).strip(),
                    } )
                result[ "failure_details" ] = failure_details
                print( f"[DEBUG _parse_junit_xml] loop_count={loop_count}, children_found={children_count}, failure_details={len( failure_details )}" )
        except ( FileNotFoundError, ET.ParseError, ValueError ) as e:
            print( f"[DEBUG _parse_junit_xml] EXCEPTION caught: {type( e ).__name__}: {e}" )

        return result

    @staticmethod
    def _parse_non_pytest_stdout( suite_type: str, stdout: str ) -> Optional[ Dict ]:
        """
        Parse the stdout of a non-pytest suite runner (e.g. the websocket smoke
        runner) into pytest-compatible counts.

        WG-7 (2026-04-28): the websocket suite's bash-driven runner emits its
        own log format. _parse_junit_xml returns zero counts because there's
        no junit-xml file. Without this fallback, the test_suite parser
        classifies 50/50 PASS as a FAIL with metrics 0/0/0/0.

        Recognized signals (websocket runner today):
            - "ALL SMOKE TESTS PASSED!" → green
            - "ALL SMOKE TESTS FAILED" / "tests failed" → red
            - "Total Tests: N" / "Passed: X" / "Failed: Y" → counts

        Requires:
            - suite_type is a known suite name
            - stdout is the captured stdout string (may be empty)

        Ensures:
            - Returns a dict with keys passed, failed, skipped, errors when the
              format is recognized.
            - Returns None when the format isn't recognized — caller keeps the
              zero-count default and downstream classification stays unchanged.

        Args:
            suite_type: Suite name (e.g., "websocket")
            stdout: Captured stdout from the runner

        Returns:
            dict | None: Parsed counts or None if format unrecognized.
        """
        if suite_type != "websocket":
            return None
        if not stdout:
            return None

        import re

        total_match  = re.search( r"Total Tests:\s*(\d+)", stdout )
        passed_match = re.search( r"\bPassed:\s*(\d+)",   stdout )
        failed_match = re.search( r"\bFailed:\s*(\d+)",   stdout )

        if not ( total_match or passed_match or failed_match ):
            return None

        total  = int( total_match.group( 1 ) )  if total_match  else 0
        passed = int( passed_match.group( 1 ) ) if passed_match else 0
        failed = int( failed_match.group( 1 ) ) if failed_match else 0

        # Sanity: prefer Passed/Failed over Total subtraction; reconcile if both available.
        if passed_match and failed_match and not total_match:
            total = passed + failed
        elif total_match and not ( passed_match or failed_match ):
            # Only "Total Tests: N" — assume all-passed iff success marker present.
            if "ALL SMOKE TESTS PASSED" in stdout:
                passed = total
                failed = 0
            else:
                # Couldn't disambiguate — fall back to None to preserve zero-counts.
                return None

        return {
            "passed"  : passed,
            "failed"  : failed,
            "skipped" : 0,
            "errors"  : 0,
        }


def quick_smoke_test():
    """
    Quick smoke test for TestSuiteJob.
    """
    cu.print_banner( "TestSuiteJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.test_suite.job import TestSuiteJob
        print( "  Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = TestSuiteJob(
            test_types = [ "integration", "e2e" ],
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
            debug      = True
        )
        print( f"  Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "ts-" ), "ID should start with ts-"
        print( f"  ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Tests]" in lqa
        print( f"  last_question_asked: {lqa}" )

        # Test 5: monopolize
        print( "Testing monopolize flag..." )
        assert job.monopolize == True
        print( "  monopolize correctly set to True" )

        # Test 6: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "  is_cacheable correctly returns False" )

        # Test 7: Attributes
        print( "Testing job attributes..." )
        assert job.test_types == [ "integration", "e2e" ]
        assert job.user_email == "test@test.com"
        assert job.state == JobState.PENDING
        assert job.dry_run == False
        print( "  All attributes set correctly" )

        # Test 8: Class constants
        print( "Testing class constants..." )
        assert TestSuiteJob.JOB_TYPE == "test_suite"
        assert TestSuiteJob.JOB_PREFIX == "ts"
        print( "  Class constants correct" )

        # Test 9: Parse junit-xml output
        print( "Testing _parse_junit_xml..." )
        import tempfile
        with tempfile.NamedTemporaryFile( mode="w", suffix=".xml", delete=False ) as f:
            f.write( '<?xml version="1.0" encoding="utf-8"?>\n'
                     '<testsuite name="pytest" errors="1" failures="3" skipped="32" tests="231" time="350.12">\n'
                     '</testsuite>\n' )
            xml_path = f.name
        parsed = TestSuiteJob._parse_junit_xml( xml_path )
        os.unlink( xml_path )
        assert parsed[ "passed" ] == 195, f"Expected 195 passed, got {parsed[ 'passed' ]}"
        assert parsed[ "failed" ] == 3
        assert parsed[ "skipped" ] == 32
        assert parsed[ "errors" ] == 1
        print( f"  Parsed: {parsed}" )

        # Test 10: Missing XML file returns zeros (startup crash scenario)
        print( "Testing _parse_junit_xml with missing file..." )
        parsed = TestSuiteJob._parse_junit_xml( "/tmp/nonexistent-junit.xml" )
        assert parsed[ "passed" ] == 0
        assert parsed[ "failed" ] == 0
        print( f"  Missing file returns zeros: {parsed}" )

        print( "\n  Smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
