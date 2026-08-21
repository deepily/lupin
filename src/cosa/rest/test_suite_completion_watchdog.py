"""
TestSuiteCompletionWatchdog — auto-dispatches TestFixExpediter when a
TestSuiteJob completes with failures.

Parallel to `DeadQueueWatchdog`, but fires on the DONE-queue push path
rather than the DEAD-queue push path because TestSuiteJobs complete
SUCCESSFULLY (from a queue perspective) even when the tests they ran
failed — they return a result object, not a crash.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/09-watchdog-routing-plan.md

Eligibility gates (all must pass for dispatch):
    1. self.enabled (INI `test fix expediter auto fix enabled`, default False)
    2. completed_job.JOB_TYPE == "test_suite"
    3. Remediation snapshot present, schema v1.0, all_passed==False, failures non-empty
    4. Recursion guard: metadata["triggered_by_tfe"] is None
    5. Failure count cap (INI `test fix expediter max cluster seed failures`)
    6. RepairAttemptTracker allows (cost/iteration/wall-clock limits)
"""

import logging
from typing import Optional

logger = logging.getLogger( __name__ )


class TestSuiteCompletionWatchdog:
    """
    Watchdog that auto-dispatches TestFixExpediter when a TestSuiteJob
    completes with failures.

    Requires:
        - config_mgr is a ConfigurationManager instance
        - todo_queue is the active TodoFifoQueue (or None for no-op mode)
        - repair_tracker is a RepairAttemptTracker (or None to disable rate limits)

    Ensures:
        - evaluate() never raises — all errors swallowed + logged
        - Returns the dispatched TFE job_id on success, None otherwise
    """

    def __init__(
        self,
        config_mgr,
        todo_queue=None,
        repair_tracker=None,
        debug: bool = False,
        verbose: bool = False,
        ask_flow=None,
    ):
        # ask_flow: the v2 AskFlow the TFE dispatch submits through (step 12). Injected
        # like todo_queue and repair_tracker, because every test of this class supplies
        # fakes for those and needs the same seam here. Defaults to None so those tests
        # keep working; the dispatch path raises by name if it is reached without one.
        self.config_mgr      = config_mgr
        self.todo_queue      = todo_queue
        self.repair_tracker  = repair_tracker
        self.ask_flow        = ask_flow
        self.debug           = debug
        self.verbose         = verbose

        # Cache config at init
        self.enabled = config_mgr.get(
            "test fix expediter auto fix enabled",
            default=False,
            return_type="boolean",
        )
        self.max_failures = config_mgr.get(
            "test fix expediter max cluster seed failures",
            default=50,
            return_type="int",
        )

        if self.debug:
            print(
                f"[TestSuiteCompletionWatchdog] initialized "
                f"(enabled={self.enabled}, max_failures={self.max_failures})"
            )

    def evaluate( self, completed_job ) -> Optional[ str ]:
        """
        Evaluate a completed job and optionally dispatch TFE.

        Requires:
            - completed_job is any job that completed successfully
              (status "completed") and has been pushed to the done queue

        Ensures:
            - Returns dispatched TFE job_id on success, None on skip
            - Never raises — logs and returns None on error

        Args:
            completed_job: The job that just completed (done-queue push)

        Returns:
            Optional[str]: The TFE job_id if dispatched, None otherwise
        """
        try:
            return self._evaluate_inner( completed_job )
        except Exception as e:
            logger.error(
                f"[TestSuiteCompletionWatchdog] evaluate() raised: {e}"
            )
            if self.debug:
                import traceback
                traceback.print_exc()
            return None

    def _evaluate_inner( self, completed_job ) -> Optional[ str ]:
        """Actual evaluation logic. May raise — caller catches in evaluate()."""

        # Gate 1: master switch with per-run override
        #
        # Tri-state precedence:
        #   override == False  → explicit per-run opt-out (skip regardless of INI)
        #   override == True   → explicit per-run opt-in (proceed regardless of INI)
        #   override is None   → no override; honor self.enabled (the INI default)
        override = getattr( completed_job, "auto_fix_on_failure", None )
        if override is False:
            if self.debug:
                print( "[TestSuiteCompletionWatchdog] skip: per-run override disabled auto-fix" )
            return None
        if override is None and not self.enabled:
            if self.debug:
                print( "[TestSuiteCompletionWatchdog] skip: disabled (INI default, no override)" )
            return None

        # Gate 2: must be a TestSuiteJob
        job_type = getattr( completed_job, "JOB_TYPE", None )
        if job_type != "test_suite":
            return None

        # Gate 3: must have a valid remediation snapshot
        artifacts = getattr( completed_job, "artifacts", None ) or {}
        snapshot = artifacts.get( "remediation_snapshot" )
        if not isinstance( snapshot, dict ):
            if self.debug:
                print( "[TestSuiteCompletionWatchdog] skip: no remediation_snapshot" )
            return None

        if snapshot.get( "schema_version" ) != "1.0":
            if self.debug:
                print(
                    f"[TestSuiteCompletionWatchdog] skip: unsupported schema_version "
                    f"{snapshot.get( 'schema_version' )}"
                )
            return None

        summary = snapshot.get( "summary", {} )
        if not isinstance( summary, dict ) or summary.get( "all_passed", True ):
            if self.debug:
                print( "[TestSuiteCompletionWatchdog] skip: all_passed or no summary" )
            return None

        failures = snapshot.get( "failures", [] )
        if not isinstance( failures, list ) or len( failures ) == 0:
            if self.debug:
                print( "[TestSuiteCompletionWatchdog] skip: no failures in snapshot" )
            return None

        # Gate 4: recursion guard — don't re-trigger on TFE-dispatched reruns
        metadata = getattr( completed_job, "metadata", None ) or {}
        if metadata.get( "triggered_by_tfe" ):
            if self.debug:
                print(
                    f"[TestSuiteCompletionWatchdog] skip: TFE recursion guard "
                    f"(triggered_by_tfe={metadata['triggered_by_tfe']})"
                )
            return None

        # Gate 5: failure count cap
        if len( failures ) > self.max_failures:
            logger.warning(
                f"[TestSuiteCompletionWatchdog] skip: {len( failures )} failures "
                f"exceeds cap {self.max_failures} — deferring to human"
            )
            return None

        # Gate 6: repair attempt tracker (cost/iteration/wall-clock)
        if self.repair_tracker is not None:
            repair_key = self._compute_repair_key( completed_job, snapshot )
            if not self._repair_tracker_allows( repair_key ):
                if self.debug:
                    print(
                        f"[TestSuiteCompletionWatchdog] skip: repair tracker "
                        f"blocked {repair_key}"
                    )
                return None

        # All gates passed — dispatch TFE
        return self._dispatch_tfe( completed_job, snapshot )

    def _repair_tracker_allows( self, repair_key ) -> bool:
        """
        Check RepairAttemptTracker. Handles both `allow()` and
        `is_allowed()`/`check()` method names defensively.
        """
        if self.repair_tracker is None:
            return True

        # Try common method names (BFE's tracker uses different names; be flexible)
        for method_name in ( "allow", "is_allowed", "check", "can_attempt" ):
            method = getattr( self.repair_tracker, method_name, None )
            if callable( method ):
                try:
                    return bool( method( repair_key ) )
                except Exception as e:
                    logger.warning(
                        f"[TestSuiteCompletionWatchdog] repair_tracker.{method_name} "
                        f"raised: {e} — allowing by default"
                    )
                    return True

        # No known method — allow by default
        return True

    @staticmethod
    def _compute_repair_key( completed_job, snapshot ) -> tuple:
        """
        Key for the repair tracker: (test_suite_job_id, sorted_suites_tuple).
        """
        job_id = getattr( completed_job, "id_hash", "unknown" )
        suites = snapshot.get( "suites_run", [] )
        return ( job_id, tuple( sorted( suites ) ) )

    def _dispatch_tfe( self, completed_job, snapshot ) -> Optional[ str ]:
        """
        Construct and enqueue a TestFixExpediterJob for this failed run.

        Returns the TFE job_id on success, None on failure.
        """
        if self.todo_queue is None:
            logger.error(
                "[TestSuiteCompletionWatchdog] cannot dispatch: no todo_queue"
            )
            return None

        snapshot_path = completed_job.artifacts.get(
            "remediation_snapshot_path", ""
        )
        if not snapshot_path:
            logger.error(
                "[TestSuiteCompletionWatchdog] snapshot path missing from artifacts"
            )
            return None

        user_id    = getattr( completed_job, "user_id", "" )
        user_email = getattr( completed_job, "user_email", "" )
        session_id = getattr( completed_job, "session_id", "" )

        # Route through create_agentic_job() so routing_command + original_args are set
        # on the constructed job for Resume capability (Bug 14 fix). The factory is the
        # single source of truth for TFE construction; matches the voice-expediter path.
        try:
            from cosa.rest.agentic_job_factory import create_agentic_job

            args_dict = {
                "remediation_snapshot_path" : snapshot_path,
                "source_test_suite_job_id"  : getattr( completed_job, "id_hash", "unknown" ),
                "original_test_types"       : snapshot.get( "suites_run", [] ),
                "dry_run"                   : False,
            }

            tfe_job = create_agentic_job(
                command    = "agent router go to test fix expediter",
                args_dict  = args_dict,
                user_id    = user_id,
                user_email = user_email,
                session_id = session_id,
                debug      = self.debug,
                verbose    = self.verbose,
            )

            if tfe_job is None:
                logger.error(
                    "[TestSuiteCompletionWatchdog] create_agentic_job returned None for TFE dispatch "
                    f"(source job {getattr( completed_job, 'id_hash', 'unknown' )})"
                )
                return None

        except Exception as e:
            logger.error(
                f"[TestSuiteCompletionWatchdog] TFE construction via factory failed: {e}"
            )
            return None

        # A PREBUILT JOB goes through `flow.submit()` — step 12. The command was decided
        # by the factory call above, so there is nothing to route; the flow scopes the id
        # and hands it to the todo queue through its queued executor, which is what the
        # direct push did.
        if self.ask_flow is None:
            logger.error(
                "[TestSuiteCompletionWatchdog] no ask_flow — cannot dispatch TFE. It is "
                "built in lupin_app.main's lifespan and passed through init_watchdogs()."
            )
            return None
        try:
            self.ask_flow.submit(
                job          = tfe_job,
                user_id      = user_id,
                user_email   = user_email,
                session_id   = session_id,
                websocket_id = session_id,
            )
        except Exception as e:
            logger.error(
                f"[TestSuiteCompletionWatchdog] submit to the ask flow failed: {e}"
            )
            return None

        # Record attempt in repair tracker
        if self.repair_tracker is not None:
            repair_key = self._compute_repair_key( completed_job, snapshot )
            self._repair_tracker_record( repair_key )

        logger.info(
            f"[TestSuiteCompletionWatchdog] auto-dispatched TFE {tfe_job.id_hash} "
            f"from TestSuiteJob {getattr( completed_job, 'id_hash', 'unknown' )} "
            f"(failures={len( snapshot.get( 'failures', [] ) )})"
        )
        return tfe_job.id_hash

    def _repair_tracker_record( self, repair_key ) -> None:
        """
        Record a repair attempt. Handles both `record_attempt()` and
        `record()` method names defensively.
        """
        if self.repair_tracker is None:
            return

        for method_name in ( "record_attempt", "record", "track" ):
            method = getattr( self.repair_tracker, method_name, None )
            if callable( method ):
                try:
                    method( repair_key )
                    return
                except Exception as e:
                    logger.warning(
                        f"[TestSuiteCompletionWatchdog] repair_tracker.{method_name} "
                        f"raised: {e}"
                    )
                    return


# ─────────────────────────────────────────────────────────────────────────
# Singleton init helper (mirrors BFE's init_watchdog pattern)
# ─────────────────────────────────────────────────────────────────────────

_watchdog_instance: Optional[ TestSuiteCompletionWatchdog ] = None


def init_watchdog(
    config_mgr,
    todo_queue=None,
    repair_tracker=None,
    debug: bool = False,
    verbose: bool = False,
    ask_flow=None,
) -> TestSuiteCompletionWatchdog:
    """
    Initialize the singleton TestSuiteCompletionWatchdog instance.

    Called once at app startup from lupin_app.main.
    """
    global _watchdog_instance
    _watchdog_instance = TestSuiteCompletionWatchdog(
        config_mgr=config_mgr,
        todo_queue=todo_queue,
        repair_tracker=repair_tracker,
        debug=debug,
        verbose=verbose,
        ask_flow=ask_flow,
    )
    return _watchdog_instance


def get_watchdog() -> Optional[ TestSuiteCompletionWatchdog ]:
    """Return the singleton instance, or None if not initialized."""
    return _watchdog_instance


def reset_watchdog() -> None:
    """Clear the singleton — used by tests to avoid cross-test contamination."""
    global _watchdog_instance
    _watchdog_instance = None
