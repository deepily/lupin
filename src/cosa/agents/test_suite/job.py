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
import queue
import re
import signal
import subprocess
import threading
import time
import traceback as tb_mod
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, List, Dict
from zoneinfo import ZoneInfo

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState
from cosa.rest.pytest_args_policy import validate_pytest_args, validate_timeout_against_suite_budget
import cosa.utils.util as cu


# Valid suite types and their script paths (relative to project root)
SUITE_SCRIPTS = {
    "unit"         : "src/tests/run-unit-tests.sh",
    "typescript"   : "src/tests/run-typescript-tests.sh",   # TS suite under c8 at an enforced 100% threshold (row 36e479ed)
    "smoke"        : "src/tests/run-smoke-tests.sh",
    "smoke_direct" : "src/tests/run-smoke-direct.sh",
    "pytest_direct": "src/tests/run-pytest-direct.sh",    # Arbitrary pytest file (doc 16 follow-up)
    "websocket"    : "src/scripts/run-websocket-smoke-tests.sh",
    "integration"  : "src/tests/run-integration-tests.sh",
    "e2e"          : "src/scripts/run-e2e-ui-tests.sh",
    "all"            : "src/tests/run-all-tests.sh",
    "presentation"   : "src/tests/run-presentation-regression.sh",
    "cosa"           : "src/tests/run-cosa-tests.sh",   # in-tree CoSA test tree (row c9d3ddcb); joined the merge pyramid 2026-08-13 (row d83d025b)
    "v2_eval"        : "src/tests/run-v2-eval.sh",     # CJ Flow v2 paired eval (row 7e2125a7 D6). NOT in ALL_SUITE_COMPONENTS — ~105 min on the metered LLM path; see the runner's header
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
    "integration", "e2e", "all", "cosa",
} )
# NOTE (row 7e2125a7 D6): "v2_eval" is deliberately NOT here either. run-v2-eval.sh
# wraps a plain python script, not pytest — an injected --junit-xml would reach
# v2_eval.py's argparse as an unknown flag and kill the run at second one. It reports
# through _parse_non_pytest_stdout, the same treatment as websocket and presentation.
# NOTE (bug 89bfcc8f): "presentation" is deliberately NOT here. Its backing
# script (run-presentation-regression.sh) is a MULTI-TIER orchestrator, not a
# single pytest run — it ignores an injected --junit-xml, so the file is never
# produced and _parse_junit_xml raised FileNotFoundError, mis-reporting a run as
# 0/0/0/0. Presentation is parsed from its stdout tier summary instead (see
# _parse_non_pytest_stdout), the same treatment as the websocket runner.

# Per-suite max execution timeout (seconds). Process is killed if exceeded.
# Values based on observed worst-case runtimes + 2x buffer. Tunable.
SUITE_TIMEOUTS_SECONDS = {
    "typescript"   : 1500,   # 25 min. ⚠️ CORRECTED 2026-08-24: this used to read "8m19s ... WITHOUT c8;
                             # c8 adds overhead, so ~2.5x margin over the uninstrumented run". That run WAS under
                             # c8 — run-typescript-tests.sh:62 reports its coverage percentages, which only a c8
                             # run produces. The two files described the same 07-21 run in contradictory terms and
                             # the margin arithmetic here rested on the wrong half.
                             # MEASURED 2026-08-24 (row 92e94cb7): c8 costs ~60% wall clock — 117 files ran 18s
                             # bare vs 29s under c8. The budget still holds comfortably, but note WHY it is not
                             # 29s for the suite: ONE file, audio_transport.test.ts, PASSES in 452s and owns
                             # essentially the entire wall clock. Fix that file and this budget could drop by an
                             # order of magnitude. Provenance: src/rnd/v0.2.0/2026.08.24-typescript-suite-memory-measured.md
    "unit"         : 300,    #  5 min (bumped from 180s on 2026-06-12: observed ~185s on ts-b51e63c9 — suite grew to ~6745 tests and the 180s budget killed it mid-run; ~1.6x margin over observed)
    "smoke"        : 3600,   # 60 min (bumped from 1800s on 2026-04-21: observed 2456s on ts-f55d172d — 160 tests + container_preflight adds overhead; ~1.46x margin over observed)
    "smoke_direct" : 1200,   # 20 min (longest: Phase D live ~10 min)
    "pytest_direct": 1200,   # 20 min (arbitrary pytest file — match smoke_direct budget)
    "websocket"    : 300,    #  5 min (~50 tests, server + WS)
    "integration"  : 30000,  # TEMP 2026-08-17 (row d8d019f6): 2000→30000 (~8.3h) for the full n=60 v2 paired CLOSING run — measured n=60 ≈ 4.8h (v1 ~6.7s/push + v2 ~22s/call), margin for the poweroff window. REVERT to 2000 at close. Prior: 33 min (bumped from 1200s on 2026-04-21: observed 1392s SWE-team dry-run — ~1.44x margin)
    "e2e"          : 3000,   # 50 min (bumped from 2400s on 2026-06-12: observed 2020.6s on ts-b51e63c9 — suite grew to ~593 tests, 2400s was only 1.19x margin; ~1.48x over observed)
    "all"            : 3600,   # 60 min (sequential pyramid, ~25-35 min observed)
    "presentation"   : 1800,   # 30 min (render-only + Sonnet; +Opus/R2P with flags)
    "cosa"           : 900,    # 15 min (~8,800 tests; both-roots hand run was ~11 min for 21,721 on 2026-08-06 — ~1.5x margin)
    "v2_eval"        : 9000,   # 150 min. MEASURED from io/v2-flow/eval-2026-08-21-11-37-48: cold ~93 min + warm ~11 min = ~105 min serial,
                               # and that warm figure is the INLINE one — under `v2 executor = queued` with terminal waits the warm pass gets LONGER,
                               # not shorter, because it waits for work the inline run did synchronously. ~1.4x margin over the measured inline total,
                               # deliberately generous on that account. Provenance: src/rnd/v0.2.0/2026.08.26-v2-warm-replay-relabels-the-route.md §7.4
}
SUITE_TIMEOUT_DEFAULT_SECONDS = 600  # 10 min fallback for unknown types

# How long the poll loop may wait on stdout before re-checking its own timeout
# and cancellation flags (bug 8b93bcf5 defect 2). This is the UPPER BOUND on how
# late a kill can be, and it replaces an unbounded one: the loop used to block in
# readline() for as long as the child stayed quiet, which on the 2026-07-26 smoke
# tier was ~9 minutes past a 3600s budget. Half a second is far below any budget
# here and costs nothing — the wait is idle, not a spin.
STDOUT_POLL_INTERVAL_SECONDS = 0.5

# Upper bound on draining already-queued stdout after a kill. Bounded on purpose:
# the drain used to be process.stdout.read(), which blocks until every descriptor
# holding the pipe's write end closes — including a grandchild the kill never
# reached. Measured: a suite whose script ran `sleep 30` returned 30.0s after a
# 1s budget. The kill was punctual; the return was not.
STDOUT_DRAIN_BUDGET_SECONDS = 5.0

# When the caller asks for "all", expand into these component suites and run
# each as its own entry in self.suite_results. This preserves partial results
# when one suite times out or crashes (pre-fix behavior was a single
# monolithic "all" subprocess whose timeout vaporized every other suite's output).
# Order matches src/tests/run-all-tests.sh's sequential pyramid.
# "typescript" joined the pyramid 2026-07-21 (row 36e479ed) once Rick ratified
# the denominator exclusions on gate 07a5460d. Before that the TS suite was
# reachable by NOTHING — no runner, no test-type, no hook, no CI — so the
# 100%-lines/branches/functions TypeScript mandate in CLAUDE.md was enforced
# only by a human remembering to type a command. The exclusions (boot.ts /
# types.ts / index.ts, each with a dated reason) live in
# src/tests/run-typescript-tests.sh; that file is where the denominator is
# defined and audited, not here.
# "cosa" joined the pyramid 2026-08-13 (row d83d025b) once its 4 stale-twin reds
# were fixed. Before that the whole src/cosa/tests/** tree (~8,800 tests) had a
# runner (row c9d3ddcb) but no gate RAN it — a green merge did not exercise it,
# so its rot emitted nothing (the exact gap the gate-reachability census exists
# to catch). Placed right after "unit": both are fast, server-free pytest, so
# they fail early together. Keep this list identical (order included) to
# run-all-tests.sh's SUITES array — test_typescript_suite_gate.py asserts it.
# 🔴 "v2_eval" is registered in SUITE_SCRIPTS but is deliberately ABSENT from this list
# (row 7e2125a7 D6). It is individually submittable, never part of "all": it runs ~105
# minutes and spends real money on the metered firewalled LLM path, so putting it in the
# merge pyramid would attach an hour and a half of billed work to every merge. Same
# treatment as "presentation". Registration and gate-membership are separate decisions,
# and conflating them is how a suite ends up either unreachable or unaffordable.
ALL_SUITE_COMPONENTS = [ "unit", "cosa", "typescript", "smoke", "websocket", "integration", "e2e" ]


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

class _StdoutReaderCrash:
    """
    Queue marker meaning THE STDOUT READER THREAD DIED — not end of output.

    `None` on the stdout queue means clean EOF. Without a second, distinct
    marker a reader that crashed posts the same `None` (from its `finally`),
    and the poll loop reports the run as a clean success: the crashed tier's
    exit code becomes `process.returncode`, which for a child that already
    exited 0 is 0. That is a green for a run whose output was never read.

    Carries the traceback text because the exception is re-raised on the main
    thread, where the original thread's stack is otherwise unrecoverable.
    """

    def __init__( self, exc, tb ):
        self.exc = exc
        self.tb  = tb


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

        # THE AUTHORITATIVE ALLOWLIST GATE (row 60f04102). It sits HERE, in the
        # constructor, rather than only in the submit router, because EVERY path
        # into execution runs through this constructor — HTTP submits, jobs
        # rehydrated from persistence (job_persistence.py:765), and side channels
        # such as capture-bounce-resubmit.py. A router-only check would leave all
        # of those unguarded. The router calls the same function so a bad request
        # is refused at the door with a clear 400, but that is usability; this is
        # the control.
        #
        # WHY IT MATTERS: pytest_args reach subprocess.Popen at :1184 with only
        # "--bg" stripped. There is no shell=True, so shell metacharacters are
        # not the vector — pytest IMPORTS whatever path it is asked to collect,
        # so an unconfined path is arbitrary code execution as the server's user.
        #
        # PytestArgsRejected subclasses ValueError, so the submit router's
        # existing `except ValueError` already renders this as a 400.
        validate_pytest_args( pytest_args or [], cu.get_project_root() )

        # THE BUDGET-CONTRADICTION GATE (row 64677f38). Also here rather than only
        # in the router, and for the same reason as the allowlist above: every path
        # into execution runs through this constructor. Attempt 11 of the paired eval
        # died because a --timeout typed into a submit request capped a single test at
        # 90 minutes while the suite budget granted it 8.3 hours — a contradiction no
        # file-reading test could see, because one of the two numbers was never in a file.
        validate_timeout_against_suite_budget(
            pytest_args or [], self.test_types, SUITE_TIMEOUTS_SECONDS, SUITE_TIMEOUT_DEFAULT_SECONDS )

        self.pytest_args         = pytest_args or []
        self.dry_run             = dry_run
        self.auto_fix_on_failure = auto_fix_on_failure
        self.env_vars            = self._filter_env_vars( env_vars or {} )

        # Results (populated after execution)
        self.suite_results = {}
        self.cost_summary  = None  # Required by queues.py for unified job interface
        # The 4-way verdict from _classify_outcome, published by the REAL run path only
        # (row a9d19d18). Stays None on the dry-run path and on any early return, which
        # is exactly what do_all uses to tell "a real run executed nothing" apart from
        # "no real run happened" — a dry run also carries all-zero counts.
        self.overall_status = None

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

            # A run that executed ZERO tests did not complete its mandate — it is
            # FAILED, not COMPLETED (row a9d19d18). Measured on ts-76be90f0: the
            # subprocess exited 70 at startup, nothing ran, and the job still landed
            # in the `done` queue reading "completed". `_classify_outcome` had
            # already called it NOT EXECUTED; the state machine simply never asked.
            #
            # THE PREDICATE IS DELIBERATELY THE NARROW ONE — nothing executed at all,
            # which is exactly `_classify_outcome`'s own first branch. A PARTIAL run
            # (some tier ran, another did not) also classifies as NOT EXECUTED, and it
            # deliberately KEEPS JobState.COMPLETED here: its counts and `all_passed`
            # already tell the truth, and routing partials to the dead queue would be
            # a behaviour change well outside this defect. Widen this only with a
            # reason, not by tidying the condition.
            #
            # Genuine reds (tests ran, some failed) also stay COMPLETED: the JOB did
            # its work and is reporting a red. The TestSuiteCompletionWatchdog expects
            # exactly that — it reads the done queue and gates on all_passed.
            # ⚠️ `overall_status is not None` is what distinguishes a REAL run from a
            # DRY RUN, and it is load-bearing: the dry-run path also builds
            # suite_results with all-zero counts, so a predicate keyed on the counts
            # alone would mark every dry run FAILED. Only the real path publishes the
            # verdict.
            summary  = self.cost_summary or {}
            executed = (
                summary[ "total_passed" ] + summary[ "total_failed" ] +
                summary[ "total_errors" ] + summary[ "total_skipped" ]
            ) if self.overall_status is not None else -1

            if executed == 0:
                self.state        = JobState.FAILED
                self.completed_at = cu.get_current_datetime_iso()
                self.result       = result
                self.error        = (
                    f"Suite executed ZERO tests (verdict: {self.overall_status}). "
                    f"A run that never executed has not passed — see the report for the startup output."
                )
                self.answer_conversational = result
                if self.debug: print( f"[TestSuiteJob] NOTHING RAN — state=FAILED ({self.error})" )
                return result

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

    # Compact per-suite icons for the report table + abstract, keyed by the
    # 3-way outcome so a non-executed suite never renders as a red "FAIL".
    _OUTCOME_ICON = {
        "PASSED"           : "PASS",
        "FAILED"           : "FAIL",
        "NOT EXECUTED"     : "NOT RUN",
        "COLLECTION ERROR" : "COLLECT ERR",
    }

    @staticmethod
    def _classify_outcome( passed: int, failed: int, errors: int, skipped: int,
                           not_executed: int = 0, collection_error: bool = False ) -> str:
        """
        Classify a run outcome from its parsed counts.

        Requires:
            - passed, failed, errors, skipped, not_executed are non-negative ints
            - collection_error is True only when pytest failed during COLLECTION

        Ensures:
            - returns "COLLECTION ERROR" when collection_error is set, BEFORE any count
              is consulted (row bc83f2df). A collection error in a TEST module writes a
              junit carrying errors=1, which this method used to read as "FAILED" — a
              string byte-identical to a genuine red. It is not a red: nothing ran. The
              measured case held 3 tests across 2 files and the junit accounted for 1,
              so the report also understated its own blast radius while sounding precise.
              Counts cannot distinguish these cases, which is why the caller passes the
              exit-code-derived fact instead of it being re-derived here.
            - returns "NOT EXECUTED" when nothing was collected (all counts zero)
              — a zero-count run is NON-EXECUTION, not a failure (bug 89bfcc8f: a
              harness reporting "FAILED — 0/0/0/0" is trusted as a real red by the
              next reader; the JUnit XML was never produced or no tests were
              collected, which is an ERROR condition, not a test failure)
            - returns "FAILED"  when at least one test failed or errored (a genuine
              failure dominates — even if some tiers also did not run)
            - returns "NOT EXECUTED" when nothing failed but at least one tier did
              not run (multi-tier runner: a tier that never ran is not a pass and
              not a failure — it must not read as green)
            - returns "PASSED"  when tests ran, none failed or errored, and every
              tier ran
        """
        if collection_error:
            return "COLLECTION ERROR"
        if ( passed + failed + errors + skipped + not_executed ) == 0:
            return "NOT EXECUTED"
        if ( failed + errors ) > 0:
            return "FAILED"
        if not_executed > 0:
            return "NOT EXECUTED"
        return "PASSED"


    def _suite_abstract_line( self, suite_type: str, result: dict ) -> str:
        """
        One suite's line in the completion card the user actually reads.

        Extracted from do_all so it can be tested directly (row 24a85385): the card
        is the only place most readers ever learn what a run did, and nothing was
        covering what it says.

        Requires:
            - result carries passed / failed / errors / skipped counts.

        Ensures:
            - always opens with the outcome icon and the counts.
            - appends the startup-crash line when startup_crash_output is present.
            - appends the FIRST failure's message when failure_details is non-empty,
              plus an "and N more" tail — the message is the notice, the junit XML
              stays the receipt.
            - never raises on a missing or malformed failure_details entry; a card
              that cannot be built is worse than a card missing one detail.

        Raises:
            - nothing
        """
        icon = self._OUTCOME_ICON[ self._classify_outcome(
            result[ "passed" ], result[ "failed" ], result[ "errors" ], result[ "skipped" ],
            result.get( "not_executed", 0 ),
            collection_error = result.get( "collection_diagnosis" ) is not None
        ) ]
        ne  = result.get( "not_executed", 0 )
        des = result.get( "deselected", 0 )
        line = ( f"- **{suite_type}**: {icon} — "
                 f"{result[ 'passed' ]} passed, {result[ 'failed' ]} failed, "
                 f"{result[ 'errors' ]} errors, {result[ 'skipped' ]} skipped"
                 + ( f", {ne} not executed" if ne else "" )
                 + ( f", {des} deselected" if des else "" ) )

        crash_output = result.get( "startup_crash_output" )
        if crash_output:
            line += f"\n  **STARTUP CRASH** (exit={result[ 'exit_code' ]}): `{crash_output[ :500 ]}`"

        # WHY THE COUNTS ALONE ARE NOT ENOUGH (row 24a85385). The junit XML has carried
        # the failure message all along — _parse_junit_xml puts it in failure_details —
        # but THIS CARD is what a human reads, and it said only "1 failed". On
        # 2026-08-21 an eval run died on an integrity guard and the reader had to open
        # the XML to learn it was not a broken assertion. The XML is the receipt; this
        # is the notice.
        #
        # FIRST failure only, plus a count of the rest: this string is spoken aloud and
        # rendered on a card, so a full list would bury the one line that says what
        # happened. Same truncation discipline as the crash line above.
        details = result.get( "failure_details" ) or []
        if details:
            first    = details[ 0 ] if isinstance( details[ 0 ], dict ) else {}
            message  = ( first.get( "message" ) or "" ).strip()
            headline = message.splitlines()[ 0 ] if message else "(no message on the failure element)"
            line    += ( f"\n  **{first.get( 'type', 'FAILED' )}** "
                         f"{first.get( 'name', '?' )}: `{headline[ :300 ]}`" )
            if len( details ) > 1:
                line += f"\n  …and {len( details ) - 1} more"
        return line

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
            # Exclusivity preflight (bug caf58f71): fail loud BEFORE the first
            # suite if a non-test agentic job is inflight on the shared
            # lupin_db_test — a concurrent writer would contaminate this sweep.
            # NO-OP off the test DB / when the running queue is unreachable.
            self._preflight_assert_exclusive_test_db()

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

            # Between-suites reset seams (bug 8bd20375): _between_suite_pairs is
            # the SINGLE source of truth for WHERE the shared-DB reset fires —
            # one (prev, next) per gap. Map each non-first suite to its
            # predecessor so the loop CONSUMES that spec rather than re-deriving
            # it (suites_to_run is deduped by _expand_all, so each suite name is
            # a unique key). A suite present as a key opens a seam; the first
            # suite never is → no reset before it, none after the last, none at
            # all for a single-suite run.
            reset_predecessor = {
                nxt: prev for prev, nxt in self._between_suite_pairs( suites_to_run )
            }

            for suite_type in suites_to_run:
                if self._cancel_requested:
                    await voice_io.notify(
                        "Test suite run cancelled by user.",
                        priority="medium",
                        queue_name="run"
                    )
                    break

                # Reset shared test-DB state BETWEEN suites so the earlier
                # suite's residue (refresh_tokens → 'Token already exists'
                # flood) can't cross the e2e→integration seam on the shared
                # :8000 DB. Fires iff this suite opens a seam.
                seam_prev = reset_predecessor.get( suite_type )
                if seam_prev is not None:
                    self._reset_state_between_suites( seam_prev, suite_type )

                await voice_io.notify(
                    f"Starting {suite_type} tests...",
                    priority="low",
                    queue_name="run"
                )

                # Row 691d49db — attest that this tier RAN, durably.
                #
                # AT THE CALL SITE, IN A `finally`. Both halves are load-bearing:
                #
                # CALL SITE, because `_run_suite` has five terminal returns
                # (success, no-script, bad-type, timeout/kill, exception).
                # Attesting inside it means five edits and a sixth return added
                # later that nobody instruments.
                #
                # `finally`, because A CALL SITE IS NOT A BOUNDARY. The first
                # version of this was a bare call after `_run_suite` and it was
                # scope-correct and boundary-wrong: it covered all five RETURNS
                # and none of the ESCAPES. Proven on the very first real run
                # (ts-102267b8, 2026-07-27): `_write_stdout_log` raised on the
                # main path, the `except` handler re-invoked it and it raised
                # again, so the exception left `_run_suite` entirely — and the
                # one run most worth a receipt produced none.
                #
                # `result` is bound only on a normal return, so the crash arm
                # attests a synthesized record rather than nothing: an escape is
                # a tier outcome, and the ledger's whole purpose is runs that
                # went wrong.
                started_at = cu.get_current_datetime_iso()
                result     = None
                try:
                    result = self._run_suite( suite_type, project_root )
                    self.suite_results[ suite_type ] = result
                finally:
                    self._attest_tier_run( suite_type, result, started_at )

                # Report per-suite results. A zero-count outcome is NON-EXECUTION
                # (no JUnit XML / nothing collected), reported as "NOT EXECUTED"
                # rather than the false-red "FAILED" (bug 89bfcc8f).
                status       = self._classify_outcome(
                    result[ "passed" ], result[ "failed" ], result[ "errors" ], result[ "skipped" ],
                    result.get( "not_executed", 0 ),
                    collection_error = result.get( "collection_diagnosis" ) is not None
                )
                await voice_io.notify(
                    f"{suite_type}: {status} — {result[ 'passed' ]} passed, "
                    f"{result[ 'failed' ]} failed, {result[ 'errors' ]} errors, "
                    f"{result[ 'skipped' ]} skipped, "
                    f"{result.get( 'not_executed', 0 )} not executed",
                    priority="low",
                    queue_name="run"
                )

            # Build summary
            total_passed       = sum( r[ "passed" ]                     for r in self.suite_results.values() )
            total_failed       = sum( r[ "failed" ]                     for r in self.suite_results.values() )
            total_skipped      = sum( r[ "skipped" ]                    for r in self.suite_results.values() )
            total_errors       = sum( r[ "errors" ]                     for r in self.suite_results.values() )
            total_not_executed = sum( r.get( "not_executed", 0 )        for r in self.suite_results.values() )
            total_deselected   = sum( r.get( "deselected", 0 )          for r in self.suite_results.values() )
            # A filtered run (any deselected test) is a SLICE, not a full-suite
            # gate (row f3beb6d5). This does NOT touch _classify_outcome —
            # `all_passed` still reflects what actually ran; `filtered` tells the
            # dashboard + watchdog the run was scoped so a slice can't masquerade
            # as a full green.
            filtered = ( total_deselected > 0 )
            # Determine pass/fail from parsed results, not exit code — exit code can be
            # non-zero for warnings or cleanup even when all tests pass (335/0/0 false positive).
            # A not-executed tier is neither a pass nor a failure: it blocks "all passed"
            # without inflating the failure count (bug 89bfcc8f).
            # A genuine failure anywhere still dominates the overall verdict — a suite
            # that collected fine and went red is a red, and must not be softened into
            # "collection error" because a DIFFERENT tier failed to collect. The
            # collection state applies only when nothing actually failed.
            any_collection_error = any(
                r.get( "collection_diagnosis" ) is not None for r in self.suite_results.values()
            )
            overall_status = self._classify_outcome(
                total_passed, total_failed, total_errors, total_skipped, total_not_executed,
                collection_error = any_collection_error and ( total_failed + total_errors ) == 0
            )
            all_passed = ( overall_status == "PASSED" )

            # Hand the 4-way verdict up to do_all so the JOB STATE can reflect it
            # (row a9d19d18). do_all used to set JobState.COMPLETED for anything that
            # returned without raising, so a run whose subprocess crashed at startup
            # having executed ZERO tests landed in the `done` queue reading
            # "completed" — measured, ts-76be90f0. The correct verdict already exists
            # right here; it simply was not carried anywhere the state machine reads.
            #
            # ⚠️ NOT a false green today, and the scope is deliberately narrow because
            # of that: every machine consumer reads cost_summary["all_passed"], which
            # is already correct (test_suite_completion_watchdog.py:150,
            # test_fix_expediter/snapshot_loader.py:161). Grepped for a caller gating
            # on JobState.COMPLETED / status == "completed" — every hit is queue
            # plumbing, none is a pass/fail gate. This closes the gap before some
            # future caller reaches for the more obvious field.
            self.overall_status = overall_status

            # Store artifacts + cost_summary (required by queues.py unified interface)
            self.cost_summary = {
                "suites_run"         : len( self.suite_results ),
                "total_passed"       : total_passed,
                "total_failed"       : total_failed,
                "total_errors"       : total_errors,
                "total_skipped"      : total_skipped,
                "total_not_executed" : total_not_executed,
                "total_deselected"   : total_deselected,
                "filtered"           : filtered,
                "all_passed"         : all_passed,
            }
            self.artifacts[ "suite_results" ] = self.suite_results
            self.artifacts[ "cost_summary" ]  = self.cost_summary
            for suite_type, result in self.suite_results.items():
                if result.get( "log_path" ):
                    self.artifacts[ f"{suite_type}_log" ] = result[ "log_path" ]

            # Non-execution (nothing collected, or tiers that never ran with no
            # genuine failure) is reported as "NOT EXECUTED", never the false-red
            # "FAILURES DETECTED" (bug 89bfcc8f). overall_status already encodes the
            # 3-way rule (FAILED dominates; not-executed blocks a clean pass).
            overall = {
                "PASSED"           : "ALL PASSED",
                "FAILED"           : "FAILURES DETECTED",
                "NOT EXECUTED"     : "NOT EXECUTED",
                "COLLECTION ERROR" : "COLLECTION ERROR — THE SUITE DID NOT RUN",
            }[ overall_status ]

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

            # Name the scope in the header when the run was FILTERED (row f3beb6d5):
            # a -k/-m slice must never read as a full-suite gate. selected =
            # what actually ran; collected = selected + deselected.
            selected_total  = total_passed + total_failed + total_errors + total_skipped
            collected_total = selected_total + total_deselected
            header_scope    = f" — FILTERED — {selected_total} of {collected_total} selected" if filtered else ""

            # Build markdown report with full stdout for each suite
            report_lines = [
                f"# Test Suite Report — {overall}{header_scope}",
                f"",
                f"**Date**: {now_local.strftime( '%Y-%m-%d %H:%M:%S %Z' )}  ",
                f"**Suites**: {', '.join( self.test_types )}  ",
                f"**Total**: {total_passed} passed, {total_failed} failed, {total_errors} errors, {total_skipped} skipped"
                + ( f", {total_deselected} deselected" if filtered else "" ),
                f"",
                f"---",
                f"",
            ]

            for suite_type, result in self.suite_results.items():
                icon = self._OUTCOME_ICON[ self._classify_outcome(
                    result[ "passed" ], result[ "failed" ], result[ "errors" ], result[ "skipped" ],
                    result.get( "not_executed", 0 ),
                    collection_error = result.get( "collection_diagnosis" ) is not None
                ) ]
                report_lines.append( f"## {suite_type} — {icon}" )
                report_lines.append( f"" )
                report_lines.append( f"| Metric | Count |" )
                report_lines.append( f"|--------|-------|" )
                report_lines.append( f"| Passed | {result[ 'passed' ]} |" )
                report_lines.append( f"| Failed | {result[ 'failed' ]} |" )
                report_lines.append( f"| Skipped | {result[ 'skipped' ]} |" )
                report_lines.append( f"| Errors | {result[ 'errors' ]} |" )
                report_lines.append( f"| Not executed | {result.get( 'not_executed', 0 )} |" )
                report_lines.append( f"| Deselected | {result.get( 'deselected', 0 )} |" )
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
            suite_lines = [ self._suite_abstract_line( suite_type, result )
                            for suite_type, result in self.suite_results.items() ]

            abstract = ( f"**Test Suite Results: {overall}{header_scope}**\n\n"
                         + "\n".join( suite_lines )
                         + f"\n\n**Total**: {total_passed} passed, {total_failed} failed, {total_errors} errors, {total_skipped} skipped"
                         + ( f", {total_deselected} deselected" if filtered else "" ) )
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

    # Residue tables cleared at the between-suites seam (bug 8bd20375). Superset
    # of the per-test clean_test_db TRUNCATE list PLUS refresh_tokens — the
    # residue whose duplicate-jti survival across the e2e→integration seam
    # produced the "Token already exists" flood.
    _BETWEEN_SUITE_TRUNCATE_TABLES = (
        "auth_audit_log", "failed_login_attempts", "job_history",
        "proxy_decisions", "trust_states", "task_items", "task_events",
        "fcm_tokens", "refresh_tokens",
    )

    @staticmethod
    def _between_suite_pairs( suites: List[ str ] ) -> List[ tuple ]:
        """
        Ordered (prev, next) adjacency pairs marking the BETWEEN-suite reset
        seams (bug 8bd20375).

        Requires:
            - suites is an ordered list of suite-type strings (possibly empty)

        Ensures:
            - returns one (suites[i-1], suites[i]) pair per gap → len(suites)-1 pairs
            - empty for 0 or 1 suite (single-suite-skip)
            - NEVER a trailing pair after the last suite (no reset-after-last)
        """
        return [ ( suites[ i - 1 ], suites[ i ] ) for i in range( 1, len( suites ) ) ]

    def _preflight_assert_exclusive_test_db( self ) -> None:
        """
        Fail loud if a non-test agentic job is inflight on the shared test DB at
        the moment this merge-gate sweep starts (bug caf58f71 — concurrent-writer
        contamination).

        The sweep is monopolize-mode. `monopolize` IS enforced now (bug 30398595:
        the consumer's Gate A drains foreign writers before dispatch and Gate B
        holds foreign intake for the run; bug 3a14292b exempts the sweep's own
        lineage children from both). This preflight is the belt to that
        suspenders — a same-instant DETECTION guard that converts any foreign
        writer already inflight AT sweep start into an explicit, diagnosable
        startup failure. It catches writers inflight at start (the shape the
        evidence shows) but, being a one-shot preflight, cannot see jobs
        dispatched later in the window — that is Gate B's job.

        SAFETY (mirrors _reset_state_between_suites): gated to lupin_db_test. On
        any other engine (a sweep aimed at :7999 dev, where coexisting fleet jobs
        are legitimate) this is a logged NO-OP. If the running-queue singleton is
        unreachable or not yet initialised (unit context, alternate host) it is
        also a logged NO-OP — the ONLY raise is the loud-fail.

        Requires:
            - self.id_hash is this sweep's pool key (excluded from the count)

        Ensures:
            - on lupin_db_test with >=1 non-test inflight agentic job: raises
              RuntimeError naming the offenders — aborts the sweep before any suite
            - on lupin_db_test with none: logs the PASS and returns
            - off the test DB, or with no reachable running queue: logged NO-OP

        Raises:
            - RuntimeError when a foreign inflight writer shares lupin_db_test
        """
        from cosa.rest.db import database as db_module

        db_url = str( db_module.engine.url )
        if "lupin_db_test" not in db_url:
            print( "[TestSuiteJob] preflight exclusivity SKIPPED: engine is not lupin_db_test — "
                   "coexisting jobs are legitimate off the test DB" )
            return

        try:
            import lupin_app.main as main_module
            running_queue = main_module.jobs_run_queue
        except ( ImportError, AttributeError ) as e:
            print( f"[TestSuiteJob] preflight exclusivity SKIPPED: running queue unavailable "
                   f"({type( e ).__name__}: {e})" )
            return

        if running_queue is None:
            print( "[TestSuiteJob] preflight exclusivity SKIPPED: running queue not yet initialised" )
            return

        offenders = running_queue.get_non_test_inflight_agentic_jobs( exclude_id_hash=self.id_hash )
        if offenders:
            detail = ", ".join( f"{o[ 'id_hash' ]}({o[ 'job_type' ]})" for o in offenders )
            raise RuntimeError(
                f"Merge-gate sweep preflight FAILED (bug caf58f71): {len( offenders )} non-test "
                f"agentic job(s) inflight on shared lupin_db_test — concurrent writers will "
                f"contaminate this sweep. Offenders: {detail}. Quiesce the agentic pool so "
                f":8000 is idle before scheduling the sweep."
            )

        print( "[TestSuiteJob] ✓ preflight exclusivity PASSED: no non-test inflight agentic "
               "jobs on lupin_db_test" )

    def _reset_state_between_suites( self, prev_suite: str, next_suite: str ) -> None:
        """
        Hard-reset the shared test DB at the seam between two suites (bug 8bd20375).

        The merge-gate sweep runs suites back-to-back on ONE shared :8000 DB
        (lupin_db_test). Without a reset here, the earlier suite's residue —
        notably refresh_tokens, whose duplicate jti collides with the login
        "Token already exists" 500 — survives into the next suite's auth
        fixtures (the e2e→integration flood, RED ts-2230937c). A literal
        container bounce is impossible from inside this job (self-kill), so the
        equivalent isolation is an in-process residue truncate against the
        hot-swapped test engine.

        SAFETY: mirrors clean_test_db — refuses to touch anything but
        lupin_db_test. When the live engine is NOT the test DB (e.g. a
        multi-suite run submitted against the :7999 dev server), this is a
        logged NO-OP, never a destructive op on dev data.

        Requires:
            - prev_suite / next_suite name the adjacent suites (logging only)

        Ensures:
            - on lupin_db_test: non-protected users deleted + residue TRUNCATEd
              (incl. refresh_tokens); protected companion rows survive
            - on any other DB: no destructive op; logs the skip
            - never raises — a reset failure logs loudly but does NOT abort the
              sweep (per-test clean_test_db is the finer-grained backstop)
        """
        from cosa.rest.db import database as db_module
        from sqlalchemy import text

        try:
            engine = db_module.engine
            db_url = str( engine.url )
            if "lupin_db_test" not in db_url:
                print( f"[TestSuiteJob] between-suites reset SKIPPED ({prev_suite}->{next_suite}): "
                       f"engine is not lupin_db_test — no destructive op off the test DB" )
                return

            table_list = ", ".join( self._BETWEEN_SUITE_TRUNCATE_TABLES )
            with engine.begin() as conn:
                conn.execute( text( "DELETE FROM users WHERE NOT is_protected" ) )
                conn.execute( text( f"TRUNCATE TABLE {table_list}" ) )
            print( f"[TestSuiteJob] ✓ between-suites DB reset ({prev_suite}->{next_suite}): "
                   f"non-protected users + residue cleared on lupin_db_test ({table_list})" )

        except Exception as reset_err:
            # Non-fatal: the per-test clean_test_db remains the backstop. A reset
            # hiccup must never vaporize the rest of the sweep.
            print( f"[TestSuiteJob] ⚠️ between-suites reset FAILED ({prev_suite}->{next_suite}), "
                   f"non-fatal: {reset_err}" )

    def _attest_tier_run( self, suite_type: str, result: Dict, started_at: str ) -> None:
        """
        Append a durable, tamper-evident record that this tier ran (row 691d49db).

        Requires:
            - result is a `_run_suite` return dict, or None when `_run_suite`
              raised and the exception is escaping
            - started_at is an ISO timestamp taken BEFORE the run

        Ensures:
            - a None result is attested as an ESCAPED run rather than skipped —
              exit_code 1, errors 1, and an `error` naming the escape. A crashed
              tier that leaves no receipt is the exact hole this row exists to
              close, and it is the outcome most worth recording.
            - appends one chained record to the ledger under the `io/` bind mount
            - NEVER raises: a failure to record must not fail the tier it records.
              The whole point is a receipt for runs that go wrong, so an
              attestation that can abort the run would delete the evidence in
              exactly the case it exists for.
            - prints the failure rather than swallowing it — a silent recorder is
              indistinguishable from one that was never wired, which is the defect
              this row was filed about
        """
        try:
            from cosa.agents.test_suite import attestation

            if result is None:
                result = {
                    "passed" : 0, "failed" : 0, "skipped" : 0, "errors" : 1,
                    "exit_code" : 1,
                    "error"     : "_run_suite raised and the exception escaped — see the job's own error",
                }

            attestation.append_attestation(
                result       = result,
                suite        = suite_type,
                job_id       = self.id_hash,
                started_at   = started_at,
                finished_at  = cu.get_current_datetime_iso(),
                project_root = self._attestation_project_root(),
            )
        except Exception as e:
            print( f"[TestSuiteJob] WARNING: tier-run attestation FAILED for {suite_type}: "
                   f"{type( e ).__name__}: {e} — the run itself is unaffected, but this "
                   f"run has NO durable receipt (row 691d49db)" )

    def _attestation_project_root( self ):
        """
        The project root the ledger hangs off, honoring a pinned artifact dir.

        Ensures:
            - returns None in production, so `attestation` resolves the real root
            - returns the pinned dir's parent chain when a test has redirected
              `_ARTIFACT_DIR`, so an attestation never lands in the live ledger
              from a test — the same fail-closed contract `artifact_root()` has
        """
        if self._ARTIFACT_DIR is None: return None
        return self._ARTIFACT_DIR

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
            junit_xml_path = self._artifact_path(
                f"{suite_type}-junit-{datetime.now().strftime( '%Y%m%d-%H%M%S' )}.xml"
            )
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
                # Own process group (bug 8b93bcf5): terminate() reaches only the
                # direct child, so a grandchild survives the kill and keeps the
                # inherited stdout pipe open. One group = one signal, whole tree.
                start_new_session=True,
                env={
                    **os.environ,
                    "LUPIN_ROOT"          : project_root,
                    "LUPIN_TEST_PORT"     : os.environ.get( "PORT", "7999" ),
                    # When the runner executes inside lupin-rest-test, the server
                    # lives on internal port 7999 (host :8000 mapping is inaccessible
                    # from within the container). Honor any caller-set value first.
                    "LUPIN_TEST_BASE_URL" : os.environ.get( "LUPIN_TEST_BASE_URL", f"http://localhost:{os.environ.get( 'PORT', '7999' )}" ),
                    # Lineage token (bug 3a14292b): this sweep's own id_hash, exposed to
                    # the pytest subprocess so any child job it spawns (e.g. a swe_team
                    # dry-run via POST /api/v2/submit) can echo it back as
                    # parent_id_hash. The consumer's Gate B then admits those children
                    # THROUGH the monopoly intake hold instead of starving them. Always
                    # injected — harmless when this sweep is not monopolize (Gate B never
                    # fires, so nothing consults it). LUPIN_TEST_ prefix matches the
                    # subprocess env-allowlist convention.
                    "LUPIN_TEST_MONOPOLIZE_PARENT_ID" : self.id_hash,
                    # Caller-supplied env (allowlist-filtered in __init__) overrides defaults.
                    **self.env_vars,
                    # 🔴 PROVENANCE — DELIBERATELY AFTER **self.env_vars, so a caller cannot
                    # overwrite it (row 224fbb68). Everything above is a default a caller may
                    # override; this is a FACT about who ran the suite, and a run that can
                    # relabel itself provides no provenance at all.
                    #
                    # WHY IT EXISTS: test_v2_paired_live.py:359 reads
                    #     written_by = os.environ.get( "LUPIN_TEST_SUITE_JOB_ID" ) or "unknown-caller"
                    # and stamps it into the paired-run artifact. Krishna measured that NOTHING
                    # in the tree ever set that variable — no runner, no script, no compose file
                    # — so `written_by` had been "unknown-caller" on every artifact ever written.
                    # The dump function's own docstring calls that value the tell that nothing
                    # identified itself as a real run; the tell could never fire, and a previous
                    # session nearly read a scaffold artifact as a real result.
                    #
                    # The LUPIN_TEST_ prefix is already inside _ENV_VAR_ALLOWED_PREFIXES, so the
                    # plumbing to carry it existed and was simply unused.
                    "LUPIN_TEST_SUITE_JOB_ID" : self.id_hash,
                }
            )

            # Per-suite timeout (seconds)
            timeout_secs = SUITE_TIMEOUTS_SECONDS.get( suite_type, SUITE_TIMEOUT_DEFAULT_SECONDS )
            if self.debug: print( f"[TestSuiteJob] {suite_type} timeout: {timeout_secs}s" )

            # Bug 8b93bcf5 defect 2 — DRAIN STDOUT ON A SEPARATE THREAD.
            #
            # This loop used to call process.stdout.readline() inline. readline()
            # on a pipe BLOCKS until a newline or EOF, so both the timeout check
            # and the cancellation check below were reachable only BETWEEN lines.
            # A child that went quiet parked the loop inside readline() and
            # neither could fire until it spoke again. Measured live on
            # 2026-07-26: the smoke tier ran ~9 minutes past its 3600s budget,
            # because --auto-proxy smoke is dominated by real LLM round-trips and
            # its silences are long BY DESIGN. Cancellation inherited the same
            # deafness, in exactly the case where someone reaches for cancel.
            #
            # A reader thread + a queue with a short get() timeout puts the loop's
            # OWN clock in charge: both checks now run at least every
            # STDOUT_POLL_INTERVAL_SECONDS no matter how silent the child is.
            # subprocess.run(timeout=) is not a drop-in — this loop needs the
            # stdout incrementally for the log.
            stdout_queue = queue.Queue()

            def _drain_stdout( pipe, q ):
                try:
                    for drained in iter( pipe.readline, "" ):
                        q.put( drained )
                except BaseException as reader_exc:                          # noqa: BLE001 — see below
                    # A crash in HERE must not look like a clean EOF. Before the
                    # reader thread existed, readline() ran inline and any failure
                    # hit _run_suite's `except Exception`, returning errors=1 /
                    # exit_code=1. Moving it to a thread made the exception die
                    # unraisable and `finally` post the EOF sentinel, so the poll
                    # loop fell through to exit_code = process.returncode = 0 and
                    # reported a crashed tier as A SUCCESS (0 passed, 0 failed,
                    # 0 errors, exit 0) — strictly worse than the 0/0/0/1 that
                    # bug 8b93bcf5 was filed about, because it reads as green.
                    # BaseException, not Exception: a KeyboardInterrupt or
                    # SystemExit in the reader is still a lost stdout stream, and
                    # silently reporting success for one is the defect either way.
                    q.put( _StdoutReaderCrash( reader_exc, tb_mod.format_exc() ) )
                finally:
                    q.put( None )   # EOF sentinel — distinct from "nothing yet"

            reader_thread = threading.Thread(
                target = _drain_stdout, args=( process.stdout, stdout_queue ), daemon=True
            )
            reader_thread.start()

            # Poll loop for cancellation support + timeout enforcement
            stdout_lines  = []
            stdout_at_eof = False
            while True:
                # Check for cancellation
                if self._cancel_requested:
                    # Same group kill as the timeout path (bug 8b93bcf5). A cancel
                    # that leaves the grandchild running would report "Cancelled"
                    # while the work carries on holding the monopolize server —
                    # the worst of both outcomes, and silent.
                    self._terminate_process_group( process )
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
                    self._terminate_process_group( process )

                    # Drain what the reader thread has already queued, so the tail
                    # captured in the synthetic failure reflects reality.
                    #
                    # This used to be `process.stdout.read()` — a BLOCKING read to
                    # EOF, which returns only once EVERY descriptor holding the
                    # pipe's write end is closed. terminate() signals the direct
                    # child only, so any surviving grandchild keeps that pipe open
                    # and the drain waits for IT. Measured: a suite script running
                    # `sleep 30` returned 30.0s after a 1s budget — the kill was
                    # punctual, the RETURN was not. Bounded queue drain instead;
                    # the reader thread owns the pipe and nothing else reads it.
                    drain_deadline = time.monotonic() + STDOUT_DRAIN_BUDGET_SECONDS
                    while time.monotonic() < drain_deadline:
                        try:
                            leftover = stdout_queue.get_nowait()
                        except queue.Empty:
                            break
                        if leftover is None:
                            break
                        if isinstance( leftover, _StdoutReaderCrash ):
                            # This path is already returning a timeout/kill verdict
                            # (exit_code -2, errors +1), so it must NOT raise and
                            # convert a measured timeout into an exception. But the
                            # marker is not a log line either — appending it would
                            # put a repr into the saved stdout. Record and continue
                            # draining.
                            stdout_lines.append(
                                f"\n[TestSuiteJob] stdout reader thread died: "
                                f"{type( leftover.exc ).__name__}: {leftover.exc}\n"
                            )
                            continue
                        stdout_lines.append( leftover )

                    stdout_text = "".join( stdout_lines )
                    log_path    = self._write_stdout_log( suite_type, stdout_text )
                    tail_text   = "".join( stdout_lines[ -40: ] ).strip()

                    # Bug 8b93bcf5: a killed tier used to report 0/0/0/1, which is
                    # indistinguishable from a tier that never ran — while sitting
                    # on results it had already produced. Recover what the progress
                    # output still holds, and say plainly that it is partial.
                    recovered = self._parse_pytest_progress_stdout( "".join( stdout_lines ) )
                    if recovered is None:
                        partial_note = "no pytest progress output was recognized, so NO partial results could be recovered"
                        p_passed = p_failed = p_skipped = p_errors = 0
                    else:
                        p_passed  = recovered[ "passed"  ]
                        p_failed  = recovered[ "failed"  ]
                        p_skipped = recovered[ "skipped" ]
                        p_errors  = recovered[ "errors"  ]
                        partial_note = (
                            f"PARTIAL results recovered from progress output: "
                            f"{p_passed} passed, {p_failed} failed, {p_errors} errors, "
                            f"{p_skipped} skipped across {len( recovered[ 'partial_files' ] )} files. "
                            f"FILE-level only — compact pytest output carries no test node-id, "
                            f"and the run was killed before the summary block, so no per-test "
                            f"name or traceback exists to recover."
                        )
                    print( f"[TestSuiteJob] {suite_type}: {partial_note}" )

                    return {
                        "passed"          : p_passed,
                        "failed"          : p_failed,
                        "skipped"         : p_skipped,
                        # +1 for the timeout itself, so a tier that was killed can
                        # never report a clean bill regardless of what it recovered.
                        "errors"          : p_errors + 1,
                        "exit_code"       : -2,
                        "log_path"        : log_path,
                        "duration"        : elapsed,
                        "error"           : f"Timeout: {suite_type} exceeded {timeout_secs}s — {partial_note}",
                        "failure_details" : [ self._synth_failure_detail(
                            suite_type     = suite_type,
                            name           = "timeout",
                            elapsed        = elapsed,
                            message        = f"Subprocess killed after {timeout_secs}s budget (actual {elapsed:.1f}s). {partial_note}",
                            traceback_text = tail_text,
                        ) ],
                    }

                # Read whatever the drain thread has produced. The get() timeout is
                # what bounds how long this loop can be away from its own checks.
                try:
                    line = stdout_queue.get( timeout=STDOUT_POLL_INTERVAL_SECONDS )
                except queue.Empty:
                    line = ""
                else:
                    if line is None:
                        stdout_at_eof = True
                        line = ""
                    elif isinstance( line, _StdoutReaderCrash ):
                        # Raise on the MAIN path so _run_suite's `except Exception`
                        # sees it — that handler is what turns a crash into
                        # errors=1 / exit_code=1 / an error string. Swallowing it
                        # here would restore the exact silence this marker exists
                        # to break.
                        raise RuntimeError(
                            f"stdout reader thread died: {type( line.exc ).__name__}: {line.exc}\n\n{line.tb}"
                        ) from line.exc
                    else:
                        stdout_lines.append( line )
                        if self.verbose: print( line, end="" )

                # Finished only when stdout hit EOF AND the process has exited.
                # Requiring BOTH matters: EOF alone can precede exit, and exit
                # alone can leave buffered lines undrained — breaking on either
                # one by itself truncates the log this job exists to preserve.
                if stdout_at_eof and process.poll() is not None:
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

            # Deselect count is stdout-only (junit-xml counts selected tests
            # only), so a -k/-m slice would otherwise read as a full pass
            # (row f3beb6d5). Kept SEPARATE from not_executed — deselection is
            # intentional scoping, not a tier that failed to run.
            parsed[ "deselected" ] = self._parse_deselected( stdout )

            parsed[ "exit_code" ] = exit_code
            parsed[ "log_path" ]  = log_path
            parsed[ "duration" ]  = duration

            # A collection error is SILENCE, not a red (row bc83f2df). Detect it from
            # the exit code, which is the only signal that survives BOTH shapes: an error
            # in a test module writes a junit (and used to read as FAILED), while an error
            # in a conftest writes no junit and fires no pytest hook at all, so nothing
            # in-process can see it. Failing soft on purpose — a diagnostic must never be
            # able to change a suite's outcome by raising.
            try:
                from cosa.utils.pytest_collection_diagnosis import diagnose
                parsed[ "collection_diagnosis" ] = diagnose( exit_code, stdout )
            except Exception as e:
                parsed[ "collection_diagnosis" ] = None
                if self.debug: print( f"[TestSuiteJob] collection diagnosis unavailable: {e!r}" )

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

    # ── artifact root: ONE knob, so the three paths cannot be moved apart ──────
    #
    # Row fd0cd863. Before this, the symlink map held absolute paths while
    # `actual_log` and `junit_xml_path` hardcoded "/tmp/" independently. A test could
    # therefore redirect the SYMLINK and still write the real FILE into the live
    # artifact directory — and that is exactly what happened:
    #
    #     /tmp/integration-latest.log  ->  line-1 line-2 line-3 line-4 line-5 line-6
    #     /tmp/unit-20260727-185252.log -> "first run"
    #
    # Fixture strings, in the path a human triaging a scheduled run reads. Not absent
    # — present and WRONG, with a plausible timestamped name and a correctly-rotated
    # symlink. A partial isolation seam is worse than none, because it reads as done.
    #
    # ⇒ Everything derives from _ARTIFACT_DIR. Redirect it and the log file, the
    # symlink and the junit XML all move together; there is no way to move one and
    # forget another, which is the failure this replaces.
    # ⚠️ None means "resolve the durable root at call time", NOT "/tmp". Kept as a
    # sentinel rather than an eagerly-resolved string because `artifact_root()` FAILS
    # CLOSED under pytest (attestation.py, commit `c29beb07`): resolving it at class-
    # definition time would fire that refusal at IMPORT, taking down every test that
    # merely imports this module. A test redirects it by setting this attribute to a
    # tmp_path — which is what the autouse `_isolate_artifact_root` fixture does.
    _ARTIFACT_DIR = None

    _LOG_BASENAMES = {
        "unit"         : "unit-latest.log",
        "typescript"   : "typescript-latest.log",
        "smoke"        : "smoke-latest.log",
        "smoke_direct" : "smoke-direct-latest.log",
        "pytest_direct": "pytest-direct-latest.log",
        "websocket"    : "websocket-latest.log",
        "integration"  : "integration-latest.log",
        "e2e"          : "e2e-ui-latest.log",
        "all"          : "all-tests-latest.log",
        # ⚠️ ADDED 2026-08-28. These three are registered in SUITE_SCRIPTS and were
        # MISSING here, and a suite absent from this map has its stdout silently thrown
        # away: `_write_stdout_log` no-ops on a falsy basename, so the run's only
        # explanation of itself never reaches disk.
        #
        # Measured the same day: a v2_eval run failed in 2.5 seconds. The report said
        # "0 passed, 1 failed" with no reason, the remediation snapshot carried
        # `failures: []`, and the container log held only the notify traffic. There was
        # no artifact anywhere naming what went wrong — the run had an explanation and
        # this dict discarded it.
        #
        # It bites the NON-pytest suites hardest, which is the reverse of harmless: they
        # have no junit-xml to fall back on, so stdout is the ONLY record they produce.
        "presentation" : "presentation-latest.log",
        "cosa"         : "cosa-latest.log",
        "v2_eval"      : "v2_eval-latest.log",
    }

    # Every suite that can be RUN must be able to explain itself. Kept next to the map
    # so the next suite registration trips the test rather than the operator.
    _SUITES_EXEMPT_FROM_STDOUT_LOG = frozenset()

    @classmethod
    def _log_symlink_path( cls, suite_type: str ) -> Optional[ str ]:
        """
        Ensures:
            - returns the absolute canonical symlink path for a known suite
            - returns None for an unknown suite (callers treat that as a no-op)
        """
        basename = cls._LOG_BASENAMES.get( suite_type )
        return os.path.join( cls._artifact_dir(), basename ) if basename else None

    @classmethod
    def _artifact_dir( cls ) -> str:
        """
        The ONE resolution point for the artifact root.

        Ensures:
            - returns `cls._ARTIFACT_DIR` when a test (or an operator) has pinned it
            - otherwise resolves the durable root via attestation.artifact_root(), which
              RAISES under pytest when no root was pinned — so a test cannot reach the
              real directory through any call path, computed or literal

        ⚠️ Resolved lazily, per call. An eager module- or class-level resolution would
        trigger that refusal at import and take down every test that imports this file.
        """
        root = cls._ARTIFACT_DIR
        if root is None:
            from cosa.agents.test_suite.attestation import artifact_root
            root = artifact_root()
        # CREATE IT — and note WHERE this line is. Because every artifact path resolves
        # through here, one mkdir covers the log file, the symlink, the junit XML AND the
        # except handler's retry. Patching the call sites would have needed three.
        #
        # `/tmp` always existed, so no writer ever needed a mkdir. Moving the root to
        # io/test-suite/artifacts/ replaced a path that is always there with one that must
        # be created, and the first real tier run died on it (ts-102267b8, 311s):
        #     FileNotFoundError: /var/lupin/io/test-suite/artifacts/unit-20260727-201637.log
        # It then failed a SECOND time inside _run_suite's except handler, which calls
        # _write_stdout_log again — so the exception escaped instead of returning the error
        # dict. A handler that re-invokes what just failed turns one failure into an escape.
        #
        # ⚠️ NO UNIT TEST COULD HAVE CAUGHT THIS. The autouse isolation fixture pins
        # _ARTIFACT_DIR to pytest's `tmp_path`, WHICH ALWAYS EXISTS — a fixture that hands
        # you a working precondition cannot detect a missing one. That is a whole class,
        # not one case. The regression tests pin the root to a path that does NOT exist.
        os.makedirs( root, exist_ok=True )
        return root

    @classmethod
    def _artifact_path( cls, filename: str ) -> str:
        """Ensures: returns `filename` resolved under the current artifact root."""
        return os.path.join( cls._artifact_dir(), filename )

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
        symlink_path = cls._log_symlink_path( suite_type )
        if not ( symlink_path and stdout_text ):
            return None
        import pathlib
        actual_log = cls._artifact_path(
            f"{suite_type}-{datetime.now().strftime( '%Y%m%d-%H%M%S' )}.log"
        )
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
            dict: Parsed counts with keys: passed, failed, skipped, errors, not_executed
        """
        result = {
            "passed"       : 0,
            "failed"       : 0,
            "skipped"      : 0,
            "errors"       : 0,
            "not_executed" : 0,   # tiers that never ran (multi-tier runners); 0 for pytest suites
            "deselected"   : 0,   # -k/-m slice size (row f3beb6d5); parsed from stdout, NOT this XML
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
    def _parse_node_tap_summary( stdout: str ) -> Optional[ Dict ]:
        """
        Parse `node --test` TAP trailer counts emitted by the typescript suite.

        Row 36e479ed. Without this the typescript suite would land in exactly
        the state WG-7 found the websocket suite in: a green run classified as
        a failure with metrics 0/0/0/0, because no junit-xml exists to parse.

        The trailer looks like:
            # tests 2245
            # pass 2245
            # fail 0
            # skipped 0

        Requires:
            - stdout is the captured runner stdout (may be empty)

        Ensures:
            - returns passed/failed/skipped/errors when a `# pass` line is present
            - returns None when the trailer is absent, so the caller keeps its
              zero-count default and downstream classification is unchanged
            - counts the LAST trailer, so a nested `# pass` inside test output
              cannot shadow the run's real total
        """
        import re

        passed_matches = re.findall( r"^# pass (\d+)$",    stdout, re.MULTILINE )
        if not passed_matches:
            return None

        failed_matches  = re.findall( r"^# fail (\d+)$",    stdout, re.MULTILINE )
        skipped_matches = re.findall( r"^# skipped (\d+)$", stdout, re.MULTILINE )

        return {
            "passed"  : int( passed_matches[ -1 ] ),
            "failed"  : int( failed_matches[ -1 ] )  if failed_matches  else 0,
            "skipped" : int( skipped_matches[ -1 ] ) if skipped_matches else 0,
            "errors"  : 0,
        }

    @staticmethod
    def _terminate_process_group( process ) -> None:
        """
        Kill the subprocess AND everything it spawned.

        WHY (bug 8b93bcf5, third defect): the runner is `bash <script>`, and
        process.terminate() signals that bash alone. A script that does NOT exec
        into pytest leaves a grandchild holding the inherited stdout pipe, which
        outlives the kill — so the tier's own budget stops governing the machine.
        Popen is started with start_new_session=True, giving the child its own
        process group, so one signal reaches the whole tree.

        Requires:
            - process is a Popen started with start_new_session=True

        Ensures:
            - SIGTERM to the group, escalating to SIGKILL after a grace period
            - falls back to the plain process-level terminate/kill when the group
              is already gone (ProcessLookupError) or the platform has no killpg;
              a cleanup helper must never raise into the caller's error path,
              because the caller is already handling a failure
        """
        def _signal_group( sig ):
            try:
                os.killpg( os.getpgid( process.pid ), sig )
            except ( ProcessLookupError, PermissionError, AttributeError, OSError ):
                # Group unavailable — fall back to the direct child so the kill
                # still happens, just without the descendants.
                try:
                    process.kill() if sig == signal.SIGKILL else process.terminate()
                except ProcessLookupError:
                    pass

        _signal_group( signal.SIGTERM )
        try:
            process.wait( timeout=10 )
        except subprocess.TimeoutExpired:
            _signal_group( signal.SIGKILL )
            try:
                process.wait( timeout=10 )
            except subprocess.TimeoutExpired:
                pass

    @staticmethod
    def _parse_deselected( stdout: str ) -> int:
        """
        Parse pytest's deselect count from captured stdout (row f3beb6d5).

        The junit-xml carries NO deselect information — its `tests` attribute
        counts only what was selected — so a `-k`/`-m` slice is invisible to
        _parse_junit_xml, and a 5-of-692 run looks byte-identical to a full
        green. This recovers the slice size so cost_summary can flag the run
        as `filtered` and the report header can name the scope.

        ⚠️ Deselection is INTENTIONAL SCOPING, not non-execution (bug 89bfcc8f).
        The count returned here must NEVER be routed into `not_executed` — that
        would red every filtered run, including the TFE landing/confirm runs
        which are filtered BY DESIGN.

        Two pytest forms carry the count; either one suffices:
            collected 692 items / 687 deselected / 5 selected
            ============== 5 passed, 687 deselected in 23.08s ==============

        Requires:
            - stdout is the captured runner stdout (may be empty)

        Ensures:
            - returns the deselected count when either form is present
            - returns 0 when neither is present (an unfiltered run)
            - prefers the collection form (the authoritative "/ M deselected /")
              when both are present; the two forms agree in practice
        """
        collected = re.search( r"collected\s+\d+\s+items?\s*/\s*(\d+)\s+deselected", stdout )
        if collected:
            return int( collected.group( 1 ) )
        trailer = re.search( r"(\d+)\s+deselected", stdout )
        if trailer:
            return int( trailer.group( 1 ) )
        return 0

    @staticmethod
    def _parse_pytest_progress_stdout( stdout: str ) -> Optional[ Dict ]:
        """
        Recover per-file result counts from pytest's COMPACT progress output.

        WHY (bug 8b93bcf5): --junit-xml is written only at session end, so a tier
        killed by the timeout leaves NO junit file, _parse_junit_xml falls back to
        zeros, and the tier publishes "0 passed, 0 failed, 1 errors" — a string
        byte-identical to a tier that crashed at import, a tier whose script was
        missing, and a tier that collected nothing. On 2026-07-26 that erased
        ~17 failures and 1 error the smoke tier had ALREADY found.

        The progress line survives in captured stdout, so the counts are
        recoverable even though the junit file is not:

            src/tests/smoke/test_alembic_....py FFF.F                    [  1%]

        ⚠️ THIS IS A MITIGATION, NOT THE FIX. It recovers FILE-level resolution
        only. Compact mode never emits a test node-id, and a killed run never
        reaches the "short test summary info" block, so no per-test name and no
        traceback exist ANYWHERE to recover. A reader learns "4 tests in this
        file failed" and cannot learn which four or why. Full per-test detail
        needs incremental capture (pytest-reportlog is NOT installed in the test
        image), which is a separate change.

        Requires:
            - stdout is the captured (possibly truncated) subprocess output

        Ensures:
            - returns a dict with passed/failed/skipped/errors counts plus a
              `partial_files` list of ( filename, chars ) for the reader
            - returns None when NO progress line was recognized — an empty parse
              must not read as "zero of everything", which is the exact
              indistinguishable-zeros failure this method exists to end
        """
        # Progress chars pytest emits in compact mode. 'x'/'X' are xfail/xpass and
        # count as neither pass nor failure, matching the junit parser's treatment.
        counts = { "passed": 0, "failed": 0, "skipped": 0, "errors": 0 }
        partial_files = []
        current_file  = None
        recognized    = False

        for raw in stdout.split( "\n" ):
            line = re.sub( r"\[\s*\d+%\]\s*$", "", raw ).rstrip()
            if not line.strip():
                continue
            m = re.match( r"^(\S+\.py)\s+(.*)$", line )
            if m:
                current_file = m.group( 1 )
                chars        = m.group( 2 )
            else:
                # A wrapped continuation carries progress chars with no filename.
                chars = line.strip()
                if current_file is None:
                    continue
            chars = chars.replace( " ", "" )
            # Anything outside the progress alphabet means this is not a progress
            # line (a banner, a traceback, a summary). Skip rather than guess —
            # miscounting a traceback as results would be worse than no recovery.
            if not chars or re.search( r"[^.FEsxX]", chars ):
                continue
            recognized = True
            counts[ "passed"  ] += chars.count( "." )
            counts[ "failed"  ] += chars.count( "F" )
            counts[ "errors"  ] += chars.count( "E" )
            counts[ "skipped" ] += chars.count( "s" )
            partial_files.append( ( current_file, chars ) )

        if not recognized:
            return None
        counts[ "partial_files" ] = partial_files
        return counts

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
        if suite_type not in ( "websocket", "typescript", "presentation", "v2_eval" ):
            return None
        if not stdout:
            return None

        import re

        if suite_type == "typescript":
            return TestSuiteJob._parse_node_tap_summary( stdout )

        # presentation (run-presentation-regression.sh) prints a tier summary:
        #   Total:  N tiers
        #   Passed: N
        #   Failed: N
        # Its "Passed:/Failed:" lines are counts of TIERS, which we surface as
        # passed/failed the same way websocket's runner summary is parsed. The
        # shared Passed/Failed regexes below already match it (bug 89bfcc8f).

        total_match         = re.search( r"Total Tests:\s*(\d+)",   stdout )
        passed_match        = re.search( r"\bPassed:\s*(\d+)",      stdout )
        failed_match        = re.search( r"\bFailed:\s*(\d+)",      stdout )
        # "Not executed: N" — tiers that never ran (multi-tier runners like
        # run-presentation-regression.sh). Surfaced distinctly so a tier that
        # did not run reads NOT EXECUTED, not FAILED (bug 89bfcc8f).
        not_executed_match  = re.search( r"Not executed:\s*(\d+)",  stdout )

        if not ( total_match or passed_match or failed_match or not_executed_match ):
            return None

        total        = int( total_match.group( 1 ) )        if total_match        else 0
        passed       = int( passed_match.group( 1 ) )       if passed_match       else 0
        failed       = int( failed_match.group( 1 ) )       if failed_match       else 0
        not_executed = int( not_executed_match.group( 1 ) ) if not_executed_match else 0

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
            "passed"       : passed,
            "failed"       : failed,
            "skipped"      : 0,
            "errors"       : 0,
            "not_executed" : not_executed,
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
