"""
Dead Queue Watchdog — Automated BFE trigger for failed agentic jobs.

Monitors the dead queue for newly failed jobs, evaluates eligibility
for automated repair, classifies failures, and triggers the Bug Fix
Expediter on behalf of the original user.

Phase 6A of the Bug Fix Expediter pipeline.
"""

import re
import threading
import time
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

class FailureCategory:
    """Classification result for a failed job's error."""
    CODE_BUG            = "code_bug"
    INFRA_TIMEOUT       = "infra_timeout"
    INFRA_OOM           = "infra_oom"
    INFRA_RATE_LIMIT    = "infra_rate_limit"
    INFRA_ENVIRONMENT   = "infra_environment"
    USER_INPUT          = "user_input"
    UNKNOWN             = "unknown"


# Regex patterns for infrastructure failures
_INFRA_PATTERNS = {
    FailureCategory.INFRA_TIMEOUT    : re.compile(
        r"TimeoutError|asyncio\.TimeoutError|timed?\s*out|deadline\s*exceeded",
        re.IGNORECASE
    ),
    FailureCategory.INFRA_OOM        : re.compile(
        r"MemoryError|OOMKilled|OutOfMemory|CUDA\s*out\s*of\s*memory",
        re.IGNORECASE
    ),
    FailureCategory.INFRA_RATE_LIMIT : re.compile(
        # Require explicit rate-limit keywords. Bare "429" was matching line numbers
        # in tracebacks (e.g. 'File "x.py", line 429') and misclassifying code bugs.
        r"RateLimitError|rate.limit|Too\s*Many\s*Requests|overloaded|"
        r"\b(?:HTTP|status|code|error)\s*(?:code\s*)?429\b",
        re.IGNORECASE
    ),
    FailureCategory.INFRA_ENVIRONMENT: re.compile(
        r"ECONNREFUSED|Connection\s*refused|Docker|credential|"
        r"No\s*such\s*file|FileNotFoundError|PermissionError",
        re.IGNORECASE
    ),
}

# Regex patterns for USER-INPUT failures — the user supplied something that
# resolved to nothing (e.g. a podcast doc description matching no file). These
# are NOT code bugs and NOT infrastructure; sending them to the Bug Fix
# Expediter burns cycles trying to code-fix a missing input AND saturates the
# agentic pool (bug f16c7ce1). The remedy is to ask the user to re-specify, so
# these are classified distinctly and made BFE-ineligible.
_USER_INPUT_PATTERNS = re.compile(
    r"Research document not found|no\s+matching\s+document|"
    r"document\s+not\s+found",
    re.IGNORECASE
)

# Regex patterns for code bugs (stronger signal → BFE eligible)
_CODE_BUG_PATTERNS = re.compile(
    r"ImportError|ModuleNotFoundError|KeyError|AttributeError|TypeError|"
    r"NameError|IndexError|ValueError|ValidationError|pydantic|"
    r"SyntaxError|IndentationError|UnboundLocalError",
    re.IGNORECASE
)


def classify_failure( error: str, stack_trace: str = "" ) -> str:
    """
    Classify a job failure as code bug vs infrastructure issue.

    Requires:
        - error is a string (may be empty)

    Ensures:
        - Returns one of FailureCategory constants
        - Infrastructure patterns checked first (higher priority)
        - Code bug patterns checked second
        - Falls back to UNKNOWN (which triggers BFE — conservative approach)

    Args:
        error: Error message from the failed job
        stack_trace: Optional full stack trace for deeper analysis

    Returns:
        str: FailureCategory constant
    """
    combined = f"{error or ''}\n{stack_trace or ''}"

    if not combined.strip():
        return FailureCategory.UNKNOWN

    # Check user-input failures FIRST — the most specific, correct label. A
    # "Research document not found" message carries neither "FileNotFoundError"
    # nor "No such file" tokens, so without this it fell through to UNKNOWN and
    # was sent to the BFE (bug f16c7ce1).
    if _USER_INPUT_PATTERNS.search( combined ):
        return FailureCategory.USER_INPUT

    # Check infrastructure patterns first (higher priority)
    for category, pattern in _INFRA_PATTERNS.items():
        if pattern.search( combined ):
            return category

    # Check code bug patterns
    if _CODE_BUG_PATTERNS.search( combined ):
        return FailureCategory.CODE_BUG

    # Default: unknown → BFE will attempt repair (conservative)
    return FailureCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Eligibility evaluation
# ---------------------------------------------------------------------------

# Job types that must NEVER be auto-fixed (prevent recursive loops)
_EXCLUDED_JOB_TYPES = frozenset( { "bug_fix_expediter", "swe_team" } )


def is_eligible_for_auto_fix(
    job,
    eligible_types: list,
    max_attempts: int = 3,
    attempt_count: int = 0,
    debug: bool = False
) -> tuple:
    """
    Evaluate whether a failed job is eligible for automated BFE repair.

    Requires:
        - job has attributes: job_type, state (or error), id_hash
        - eligible_types is a list of job type strings
        - max_attempts >= 1
        - attempt_count >= 0

    Ensures:
        - Returns (eligible: bool, reason: str)
        - Checks: job type, exclusion list, attempt count, failure category

    Args:
        job: The failed job object (from dead queue)
        eligible_types: Configured list of auto-fix-eligible job types
        max_attempts: Maximum repair attempts per job
        attempt_count: Current attempt count for this job
        debug: Enable debug output

    Returns:
        tuple: (eligible: bool, reason: str)
    """
    job_type = getattr( job, "job_type", getattr( job, "JOB_TYPE", None ) )

    # Guard: must have a job_type
    if not job_type:
        return False, "No job_type attribute found"

    # Guard: excluded job types (prevent recursion)
    if job_type in _EXCLUDED_JOB_TYPES:
        return False, f"Job type '{job_type}' is excluded from auto-fix (recursion prevention)"

    # Guard: must be in the eligible list
    if job_type not in eligible_types:
        return False, f"Job type '{job_type}' not in eligible types: {eligible_types}"

    # Guard: max attempts
    if attempt_count >= max_attempts:
        return False, f"Max attempts ({max_attempts}) reached for this job"

    # Guard: must be a failure state
    from cosa.rest.job_state import JobState
    job_state = getattr( job, "state", None )
    if job_state and job_state != JobState.FAILED:
        return False, f"Job state is '{job_state}', not FAILED"

    # Classify the failure
    error       = getattr( job, "error", "" ) or ""
    stack_trace = ""
    artifacts   = getattr( job, "artifacts", {} ) or {}
    if isinstance( artifacts, dict ):
        stack_trace = artifacts.get( "stack_trace", "" ) or ""

    category = classify_failure( error, stack_trace )

    if category == FailureCategory.INFRA_OOM:
        return False, "Infrastructure failure (OOM) — requires manual intervention"

    if category == FailureCategory.INFRA_ENVIRONMENT:
        return False, "Infrastructure failure (environment/credentials) — requires manual intervention"

    if category == FailureCategory.USER_INPUT:
        return False, "User-input error (e.g. no matching research document) — ask the user to re-specify, not a code bug (bug f16c7ce1)"

    # Rate limit and timeout: could retry the original job without BFE,
    # but for MVP we let BFE diagnose — it will correctly identify as transient
    if debug:
        print( f"[Watchdog] Job {getattr( job, 'id_hash', '?' )} eligible: "
               f"type={job_type}, category={category}, attempt={attempt_count + 1}/{max_attempts}" )

    return True, f"Eligible: {category}"


# ---------------------------------------------------------------------------
# Dead Queue Watchdog
# ---------------------------------------------------------------------------

class DeadQueueWatchdog:
    """
    Monitors dead queue pushes and triggers BFE for eligible failures.

    Requires:
        - config_mgr is an initialized ConfigurationManager
        - todo_queue is the active TodoFifoQueue instance

    Ensures:
        - evaluate() is thread-safe
        - BFE jobs are submitted as the original user
        - Attempt counts are tracked in-memory (MVP)
    """

    def __init__( self, config_mgr, todo_queue, debug=False, ask_flow=None ):
        """
        Initialize the watchdog.

        Args:
            config_mgr: ConfigurationManager for reading INI settings
            todo_queue: TodoFifoQueue — still read for queue inspection; work is no
                longer pushed onto it directly (step 12)
            debug: Enable debug output
            ask_flow: the v2 AskFlow this watchdog submits through. Injected rather
                than reached for, because every test of this class builds it with a
                fake queue and needs the same seam for the flow. Defaults to None so
                those tests keep working; the two submit paths raise by name if they
                are reached without one.
        """
        self.config_mgr = config_mgr
        self.todo_queue = todo_queue
        self.ask_flow   = ask_flow
        self.debug      = debug

        # In-memory attempt tracker: { original_job_id_hash: attempt_count }
        self._attempts      = {}
        # Cooldown tracker: { original_job_id_hash: last_attempt_timestamp }
        self._last_attempt  = {}
        self._attempts_lock = threading.Lock()

        # Load config
        self._reload_config()

    def _reload_config( self ):
        """Reload auto-fix configuration from INI."""
        self.enabled        = self.config_mgr.get( "auto fix enabled", default=False, return_type="boolean" )
        eligible_raw        = self.config_mgr.get( "auto fix eligible job types", default="presentation, deep_research, podcast, test_suite" )
        self.eligible_types = [ t.strip() for t in eligible_raw.split( "," ) if t.strip() ]
        self.max_attempts   = self.config_mgr.get( "auto fix max attempts per job", default=3, return_type="int" )
        self.max_cost_usd   = self.config_mgr.get( "auto fix max cost usd", default=10.0, return_type="float" )
        self.max_wall_clock = self.config_mgr.get( "auto fix max wall clock seconds", default=1800, return_type="int" )
        self.cooldown_secs  = self.config_mgr.get( "auto fix cooldown seconds", default=60, return_type="int" )

    def get_attempt_count( self, job_id: str ) -> int:
        """Get current attempt count for a job."""
        with self._attempts_lock:
            return self._attempts.get( job_id, 0 )

    def increment_attempt( self, job_id: str ) -> int:
        """Increment and return attempt count for a job."""
        with self._attempts_lock:
            count = self._attempts.get( job_id, 0 ) + 1
            self._attempts[ job_id ] = count
            return count

    def evaluate( self, failed_job ) -> Optional[ str ]:
        """
        Evaluate a failed job and trigger BFE if eligible.

        Called by RunningFifoQueue after pushing a job to the dead queue.
        Thread-safe via attempt_count lock.

        Requires:
            - failed_job is a job object that just transitioned to FAILED

        Ensures:
            - Returns BFE job_id if triggered, None if not eligible
            - BFE job is submitted as the original user (user_id, user_email)
            - Attempt count incremented on trigger
            - Notifications sent for eligible/ineligible decisions

        Args:
            failed_job: The job that just failed

        Returns:
            str: BFE job_id if triggered, None otherwise
        """
        # Reload config each time (allows hot-toggle without restart)
        self._reload_config()

        if not self.enabled:
            if self.debug: print( "[Watchdog] Auto-fix disabled" )
            return None

        job_id = getattr( failed_job, "id_hash", None )
        if not job_id:
            return None

        # Check circuit breakers via RepairAttemptTracker (if available)
        from cosa.rest.repair_attempt_tracker import get_tracker
        tracker = get_tracker()
        if tracker:
            can, breaker_reason = tracker.can_attempt( job_id )
            if not can:
                if self.debug: print( f"[Watchdog] Circuit breaker: {breaker_reason}" )
                self._notify_ineligible( failed_job, breaker_reason )
                return None

        # Check eligibility
        attempt_count    = self.get_attempt_count( job_id )
        eligible, reason = is_eligible_for_auto_fix(
            failed_job,
            self.eligible_types,
            self.max_attempts,
            attempt_count,
            self.debug
        )

        if not eligible:
            if self.debug: print( f"[Watchdog] Not eligible: {reason}" )
            self._notify_ineligible( failed_job, reason )
            return None

        # Check cooldown
        if not self._cooldown_elapsed( job_id ):
            if self.debug: print( f"[Watchdog] Cooldown not elapsed for {job_id}" )
            return None

        # Check for transient failures — direct-retry without BFE
        error       = getattr( failed_job, "error", "" ) or ""
        stack_trace = ""
        artifacts   = getattr( failed_job, "artifacts", {} ) or {}
        if isinstance( artifacts, dict ):
            stack_trace = artifacts.get( "stack_trace", "" ) or ""

        category = classify_failure( error, stack_trace )
        if category in ( FailureCategory.INFRA_TIMEOUT, FailureCategory.INFRA_RATE_LIMIT ):
            return self._direct_retry( failed_job, attempt_count, category )

        # Trigger BFE for code bugs and unknown failures
        return self._submit_bfe( failed_job, attempt_count )

    def _cooldown_elapsed( self, job_id: str ) -> bool:
        """Check if cooldown period has elapsed since last attempt for this job."""
        with self._attempts_lock:
            last = self._last_attempt.get( job_id )
            if last is None:
                return True
            elapsed = time.time() - last
            return elapsed >= self.cooldown_secs

    def _record_attempt_time( self, job_id: str ):
        """Record the timestamp of this attempt for cooldown tracking."""
        with self._attempts_lock:
            self._last_attempt[ job_id ] = time.time()

    def _direct_retry( self, failed_job, attempt_count: int, category: str ) -> Optional[ str ]:
        """
        Directly retry a job for transient failures (timeout, rate limit).

        No BFE needed — just requeue the original job after cooldown.

        Args:
            failed_job: The failed job to retry
            attempt_count: Current attempt number
            category: FailureCategory constant

        Returns:
            str: Requeued job_id if successful, None on error
        """
        job_id = failed_job.id_hash
        print( f"[Watchdog] Transient failure ({category}) — direct retry for {job_id}" )

        try:
            # Re-use the retry endpoint's logic: get original question and resubmit
            from cosa.rest.job_persistence import get_job_by_id_hash
            job_record = get_job_by_id_hash( job_id )

            if job_record is None:
                print( f"[Watchdog] Cannot direct-retry: job {job_id} not found in DB" )
                return None

            question   = job_record.get( "question_text", "" )
            user_id    = getattr( failed_job, "user_id", "" )
            user_email = getattr( failed_job, "user_email", "" )
            session_id = getattr( failed_job, "session_id", f"watchdog-{job_id[ :8 ]}" )

            # A BARE QUESTION goes to `ask`, not `submit` — step 12 routes by SHAPE.
            # Nothing has been decided about this retry: all we recovered from the DB
            # is the text the user originally said, so it still needs routing and
            # argument extraction, and that is what `ask` is. `submit` would skip both
            # and try to run a command nobody named. Getting this backwards is silent
            # — both still produce an answer — which is why it is stated here.
            # interactive=False: there is no human behind a watchdog retry to answer a
            # follow-up question, so an under-specified question must come back as
            # needs_input rather than park at this session id and expire unread.
            if self.ask_flow is None:
                raise RuntimeError(
                    "DeadQueueWatchdog has no ask_flow — direct retry cannot reach the "
                    "queue. It is built in lupin_app.main's lifespan and passed through "
                    "init_watchdogs(); a None here means the app has not finished booting."
                )
            result = self.ask_flow.ask(
                question     = question,
                user_id      = user_id,
                user_email   = user_email,
                session_id   = session_id,
                websocket_id = session_id,
                interactive  = False,
            )

            self.increment_attempt( job_id )
            self._record_attempt_time( job_id )

            new_job_id = result.get( "job_id" ) if isinstance( result, dict ) else None
            print( f"[Watchdog] Direct retry queued for {job_id}: "
                   f"new_job={new_job_id}, attempt={attempt_count + 1}/{self.max_attempts}" )

            return new_job_id

        except Exception as e:
            print( f"[Watchdog] Direct retry failed for {job_id}: {e}" )
            return None

    def _submit_bfe( self, failed_job, attempt_count: int ) -> Optional[ str ]:
        """
        Submit a BFE job to fix the failed job.

        The BFE job runs as the original user so notifications route
        to their UI.

        Args:
            failed_job: The failed job to fix
            attempt_count: Current attempt number (pre-increment)

        Returns:
            str: BFE job_id if submitted, None on error
        """
        from cosa.rest.agentic_job_factory import create_agentic_job

        job_id     = failed_job.id_hash
        user_id    = getattr( failed_job, "user_id", "" )
        user_email = getattr( failed_job, "user_email", "" )
        session_id = getattr( failed_job, "session_id", f"watchdog-{job_id[ :8 ]}" )

        attempt_num = attempt_count + 1
        extra_context = (
            f"Automated repair attempt {attempt_num}/{self.max_attempts}. "
            f"Triggered by dead queue watchdog. "
            f"repair_chain_id={job_id}"
        )

        # Phase 6 dry-run repair loop: if the failed job was itself a dry-run
        # mock, propagate dry_run=True to the spawned BFE so the whole repair
        # loop runs at $0 cost. Production failures (dry_run=False) always
        # spawn non-dry-run BFE jobs.
        bfe_args = {
            "dead_job_id"   : job_id,
            "extra_context" : extra_context,
        }
        if getattr( failed_job, "dry_run", False ):
            bfe_args[ "dry_run" ] = True
            if self.debug: print( f"[Watchdog] Propagating dry_run=True to spawned BFE for {job_id}" )

        # Propagate BFE model overrides from the failed job's original args.
        # Set by E2E scripts via --cheap (Sonnet-only) and any other future
        # cost-sensitive pathway. Keys are namespaced with "bfe_" to avoid
        # colliding with other agents' model params.
        original_args = getattr( failed_job, "original_args", {} ) or {}
        if original_args.get( "bfe_lead_model_override" ):
            bfe_args[ "lead_model_override" ] = original_args[ "bfe_lead_model_override" ]
            if self.debug: print( f"[Watchdog] Propagating lead_model_override={bfe_args[ 'lead_model_override' ]} to spawned BFE" )
        if original_args.get( "bfe_worker_model_override" ):
            bfe_args[ "worker_model_override" ] = original_args[ "bfe_worker_model_override" ]
            if self.debug: print( f"[Watchdog] Propagating worker_model_override={bfe_args[ 'worker_model_override' ]} to spawned BFE" )

        try:
            bfe_job = create_agentic_job(
                command    = "agent router go to bug fix expediter",
                args_dict  = bfe_args,
                user_id    = user_id,
                user_email = user_email,
                session_id = session_id,
            )

            if bfe_job is None:
                print( f"[Watchdog] Failed to create BFE job for {job_id}" )
                return None

            # A PREBUILT JOB goes to `submit` — its command was decided above, so
            # routing it again would pay an LLM to re-derive a fact we just stated.
            # The scoping that used to happen here is the executor's now: QueuedExecutor
            # scopes the id and pushes, which is exactly the two lines this replaces.
            # Doing it here as well would be harmless (the scoper strips an existing
            # scope before re-adding) but it would be two places owning one rule.
            if self.ask_flow is None:
                raise RuntimeError(
                    "DeadQueueWatchdog has no ask_flow — the BFE job cannot reach the "
                    "queue. It is built in lupin_app.main's lifespan and passed through "
                    "init_watchdogs(); a None here means the app has not finished booting."
                )
            result = self.ask_flow.submit(
                job          = bfe_job,
                user_id      = user_id,
                user_email   = user_email,
                session_id   = session_id,
                websocket_id = session_id,
            )
            # THE SCOPED ID IS THE FLOW'S ANSWER, not something read back off the object.
            # QueuedExecutor does set job.id_hash in place, so reading the attribute would
            # work today — but everything below (the tracker row, the notify, the return
            # value) would go quietly wrong the day an executor stops mutating the caller's
            # object. Take the id the flow reports.
            bfe_job.id_hash = result[ "job_id" ]

            # Increment attempt count and record time for cooldown
            self.increment_attempt( job_id )
            self._record_attempt_time( job_id )

            # Record attempt in RepairAttemptTracker (if available)
            from cosa.rest.repair_attempt_tracker import get_tracker
            tracker = get_tracker()
            if tracker:
                tracker.record_attempt( job_id, bfe_job.id_hash )

            self._notify_triggered( failed_job, bfe_job )

            print( f"[Watchdog] BFE triggered for {job_id}: bfe_job={bfe_job.id_hash}, "
                   f"attempt={attempt_count + 1}/{self.max_attempts}" )

            return bfe_job.id_hash

        except Exception as e:
            print( f"[Watchdog] Error submitting BFE for {job_id}: {e}" )
            return None

    def _notify_triggered( self, failed_job, bfe_job ):
        """Log that auto-fix was triggered. BFE job's voice_io handles user-facing notifications."""
        job_type = getattr( failed_job, "job_type", getattr( failed_job, "JOB_TYPE", "unknown" ) )
        user     = getattr( failed_job, "user_email", "unknown" )
        print( f"[Watchdog] Auto-fix triggered: {job_type} job for {user}, BFE={bfe_job.id_hash}" )

    def _notify_ineligible( self, failed_job, reason: str ):
        """Log when auto-fix is not eligible. Only logs for actionable reasons."""
        # Only log for max-attempts-exhausted (user needs to know)
        if "Max attempts" not in reason:
            return
        job_type = getattr( failed_job, "job_type", getattr( failed_job, "JOB_TYPE", "unknown" ) )
        user     = getattr( failed_job, "user_email", "unknown" )
        print( f"[Watchdog] ESCALATION: Auto-fix exhausted for {job_type} job ({user}) "
               f"after {self.max_attempts} attempts. Manual review needed." )


# ---------------------------------------------------------------------------
# Module-level singleton (initialized at server startup)
# ---------------------------------------------------------------------------

_watchdog_instance: Optional[ DeadQueueWatchdog ] = None


def init_watchdog( config_mgr, todo_queue, debug=False, ask_flow=None ) -> DeadQueueWatchdog:
    """
    Initialize the global watchdog singleton.

    Called once at server startup from main.py.

    Args:
        config_mgr: ConfigurationManager
        todo_queue: TodoFifoQueue
        debug: Enable debug output
        ask_flow: the v2 AskFlow both submit paths go through (step 12)

    Returns:
        DeadQueueWatchdog: The initialized instance
    """
    global _watchdog_instance
    _watchdog_instance = DeadQueueWatchdog( config_mgr, todo_queue, debug=debug, ask_flow=ask_flow )

    enabled_str = "ENABLED" if _watchdog_instance.enabled else "DISABLED"
    print( f"[Watchdog] Dead Queue Watchdog initialized ({enabled_str}), "
           f"eligible types: {_watchdog_instance.eligible_types}" )

    return _watchdog_instance


def get_watchdog() -> Optional[ DeadQueueWatchdog ]:
    """Get the global watchdog instance (None if not initialized)."""
    return _watchdog_instance


def quick_smoke_test():
    """Quick smoke test for dead_queue_watchdog."""
    cu.print_banner( "Dead Queue Watchdog Smoke Test", prepend_nl=True )

    try:
        # 1: FailureCategory constants
        assert FailureCategory.CODE_BUG == "code_bug"
        assert FailureCategory.INFRA_TIMEOUT == "infra_timeout"
        print( "✓ FailureCategory constants correct" )

        # 2: classify_failure — code bugs
        assert classify_failure( "KeyError: 'missing_key'" ) == FailureCategory.CODE_BUG
        assert classify_failure( "ImportError: No module named 'foo'" ) == FailureCategory.CODE_BUG
        assert classify_failure( "pydantic.ValidationError" ) == FailureCategory.CODE_BUG
        assert classify_failure( "AttributeError: 'NoneType' has no attribute 'bar'" ) == FailureCategory.CODE_BUG
        print( "✓ classify_failure: code bugs detected correctly" )

        # 3: classify_failure — infrastructure
        assert classify_failure( "TimeoutError: operation timed out" ) == FailureCategory.INFRA_TIMEOUT
        assert classify_failure( "MemoryError" ) == FailureCategory.INFRA_OOM
        assert classify_failure( "RateLimitError: 429" ) == FailureCategory.INFRA_RATE_LIMIT
        assert classify_failure( "Connection refused (ECONNREFUSED)" ) == FailureCategory.INFRA_ENVIRONMENT
        print( "✓ classify_failure: infra failures detected correctly" )

        # 3b: classify_failure — user-input (bug f16c7ce1: must NOT reach BFE)
        assert classify_failure( "Research document not found: my lighthouse write-up" ) == FailureCategory.USER_INPUT
        print( "✓ classify_failure: user-input (missing research doc) detected correctly" )

        # 4: classify_failure — unknown
        assert classify_failure( "Something went wrong" ) == FailureCategory.UNKNOWN
        assert classify_failure( "" ) == FailureCategory.UNKNOWN
        print( "✓ classify_failure: unknown fallback correct" )

        # 5: classify_failure — stack trace has signal
        assert classify_failure( "job failed", "Traceback...\\nImportError: no module" ) == FailureCategory.CODE_BUG
        print( "✓ classify_failure: stack_trace analysis works" )

        # 6: classify_failure — infra wins over code in mixed signals
        assert classify_failure( "TimeoutError", "ImportError: no module" ) == FailureCategory.INFRA_TIMEOUT
        print( "✓ classify_failure: infra priority over code in mixed signals" )

        # 7: is_eligible_for_auto_fix — basic checks
        class MockJob:
            def __init__( self, job_type, state=None, error="" ):
                self.job_type  = job_type
                self.JOB_TYPE  = job_type
                self.state     = state
                self.error     = error
                self.id_hash   = "test-123"
                self.artifacts = {}

        from cosa.rest.job_state import JobState

        # Eligible case
        job = MockJob( "presentation", JobState.FAILED, "KeyError: oops" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        assert ok, f"Should be eligible: {reason}"
        print( "✓ is_eligible_for_auto_fix: eligible case passes" )

        # Excluded type
        job = MockJob( "bug_fix_expediter", JobState.FAILED, "KeyError: oops" )
        ok, reason = is_eligible_for_auto_fix( job, [ "bug_fix_expediter" ] )
        assert not ok
        assert "excluded" in reason.lower()
        print( "✓ is_eligible_for_auto_fix: BFE recursion blocked" )

        # Not in eligible list
        job = MockJob( "presentation", JobState.FAILED, "KeyError: oops" )
        ok, reason = is_eligible_for_auto_fix( job, [ "deep_research" ] )
        assert not ok
        assert "not in eligible" in reason.lower()
        print( "✓ is_eligible_for_auto_fix: non-eligible type blocked" )

        # Max attempts
        job = MockJob( "presentation", JobState.FAILED, "KeyError: oops" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ], max_attempts=3, attempt_count=3 )
        assert not ok
        assert "max attempts" in reason.lower()
        print( "✓ is_eligible_for_auto_fix: max attempts enforced" )

        # OOM = ineligible
        job = MockJob( "presentation", JobState.FAILED, "MemoryError: out of memory" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        assert not ok
        assert "oom" in reason.lower()
        print( "✓ is_eligible_for_auto_fix: OOM blocked" )

        # Cooldown tracking
        class MockConfigMgr:
            def get( self, key, default=None, return_type=None ):
                defaults = {
                    "auto fix enabled"              : True,
                    "auto fix eligible job types"    : "presentation, deep_research",
                    "auto fix max attempts per job"  : 3,
                    "auto fix max cost usd"          : 10.0,
                    "auto fix max wall clock seconds": 1800,
                    "auto fix cooldown seconds"      : 60,
                }
                val = defaults.get( key, default )
                if return_type == "boolean": return bool( val )
                if return_type == "int":     return int( val )
                if return_type == "float":   return float( val )
                return val

        watchdog = DeadQueueWatchdog( MockConfigMgr(), None, debug=True )
        assert watchdog._cooldown_elapsed( "test-123" ) == True
        watchdog._record_attempt_time( "test-123" )
        assert watchdog._cooldown_elapsed( "test-123" ) == False  # just recorded
        print( "✓ Cooldown tracking: elapsed before first attempt, blocked after" )

        # Attempt counting
        assert watchdog.get_attempt_count( "new-job" ) == 0
        watchdog.increment_attempt( "new-job" )
        assert watchdog.get_attempt_count( "new-job" ) == 1
        watchdog.increment_attempt( "new-job" )
        assert watchdog.get_attempt_count( "new-job" ) == 2
        print( "✓ Attempt counting: increment and read correct" )

        print( "\n✓ Dead Queue Watchdog smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
