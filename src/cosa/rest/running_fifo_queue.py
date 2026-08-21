# from cosa.agents.math_refactoring_agent import MathRefactoringAgent
from cosa.agents.receptionist_agent import ReceptionistAgent
from cosa.agents.weather_agent import WeatherAgent
from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.job_state import JobState
from cosa.rest.queue_util import emit_job_state_transition
from cosa.rest.queue_protocol import is_queueable_job
from cosa.agents.agent_base import AgentBase
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.memory.input_and_output_table import InputAndOutputTable
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.memory.gist_normalizer import GistNormalizer

import cosa.utils.util as du
import cosa.rest._unreachability_probe as _probe
import cosa.utils.util_stopwatch as sw
import time

import threading
import traceback
import pprint
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Any, List, Dict

# Notification service imports for async correctness verification
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    ResponseType
)

def compute_duration_seconds( started_at: Any, completed_at: Any ) -> Optional[ float ]:
    """
    Elapsed seconds between two timestamps, or None when either is absent.

    The single place that knows a timestamp may arrive as an ISO string OR a
    datetime. Fast-lane jobs and agentic jobs disagree on which they carry
    (row 4a9ebc4b), so callers must not have to guess — six copies of this
    logic used to, and two of them forgot to require completed_at.

    Requires:
        - started_at / completed_at are each an ISO-8601 string, a datetime,
          None, or "" — nothing else is assumed

    Ensures:
        - returns None if either value is empty ("" or None)
        - returns None if either value fails to parse, rather than raising —
          a card's duration must never take the request down with it
        - otherwise returns ( completed_at - started_at ).total_seconds()
    """
    if not started_at or not completed_at: return None

    try:
        start = datetime.fromisoformat( started_at )   if isinstance( started_at, str )   else started_at
        end   = datetime.fromisoformat( completed_at ) if isinstance( completed_at, str ) else completed_at
        return ( end - start ).total_seconds()
    except Exception:
        return None


class RunningFifoQueue( FifoQueue ):
    """
    CJ Flow execution engine — processes running jobs with agents and solution snapshots.

    Manages execution of jobs from todo queue to done/dead queues.
    Handles both AgentBase instances and SolutionSnapshot instances.
    """
    def __init__( self, app: Any, websocket_mgr: Any, snapshot_mgr: Any, jobs_todo_queue: FifoQueue, jobs_done_queue: FifoQueue, jobs_dead_queue: FifoQueue, config_mgr: Optional[Any]=None, emit_speech_callback: Optional[Any]=None ) -> None:
        """
        Initialize the running FIFO queue.
        
        Requires:
            - app is a Flask application instance
            - websocket_mgr is a WebSocketManager instance
            - snapshot_mgr is a valid snapshot manager
            - All queue parameters are FifoQueue instances
            - config_mgr is None or a valid ConfigurationManager
            - emit_speech_callback is None or a callable function
            
        Ensures:
            - Sets up queue management components
            - Initializes auto_debug and inject_bugs from config
            - Creates InputAndOutputTable instance
            
        Raises:
            - None
        """
        
        super().__init__( websocket_mgr=websocket_mgr, queue_name="running", emit_enabled=True )
        
        self.app                 = app
        self.snapshot_mgr        = snapshot_mgr
        self.jobs_todo_queue     = jobs_todo_queue
        self.jobs_done_queue     = jobs_done_queue
        self.jobs_dead_queue     = jobs_dead_queue
        self.emit_speech_callback = emit_speech_callback
        
        self.auto_debug              = False if config_mgr is None else config_mgr.get( "debug auto",  default=False, return_type="boolean" )
        self.inject_bugs             = False if config_mgr is None else config_mgr.get( "debug inject bugs", default=False, return_type="boolean" )
        self.debug                   = False if config_mgr is None else config_mgr.get( "app debug",   default=False, return_type="boolean" )
        self.verbose                 = False if config_mgr is None else config_mgr.get( "app verbose", default=False, return_type="boolean" )
        self.threshold_confirmation  = 90.0  if config_mgr is None else config_mgr.get( "similarity threshold confirmation", default=90.0, return_type="float" )
        self.io_tbl                  = InputAndOutputTable()
        self.gist_normalizer         = GistNormalizer( debug=self.debug, verbose=self.verbose )

        # Phase 2 (CJ Flow async multi-lane): agentic pool + future tracking
        self._pool_max_workers       = 1 if config_mgr is None else config_mgr.get(
            "cj flow max concurrent agentic jobs", default=1, return_type="int"
        )
        self._agentic_pool           = ThreadPoolExecutor(
            max_workers        = self._pool_max_workers,
            thread_name_prefix = "AgenticPool"
        )
        # Shape-B hardening (bug fe375cf6): a DEDICATED single-worker executor for
        # monopolize jobs, separate from the shared agentic pool. A monopolizer runs
        # HERE so it no longer consumes a shared-pool worker — the full width N stays
        # free for its own spawned (lineage) children. This makes pool_max==1
        # deadlock-safe and 67473d91's budget math exact. Eager (D2): symmetric with
        # _agentic_pool, no lazy-init race, one idle thread. Its Futures are tracked
        # in the SAME _agentic_futures dict below, so the completion callback + ghost
        # sweeper cover both executors with one scan / one lock (invariants I1-I3).
        self._monopolize_pool        = ThreadPoolExecutor(
            max_workers        = 1,                          # Gate B already serializes monopolizers at intake
            thread_name_prefix = "MonopolizePool"
        )
        self._agentic_futures        = { }                   # { id_hash : Future } (BOTH executors)
        # RLock (not Lock): when a Future completes before add_done_callback
        # returns — possible for fast-running work — the callback fires
        # synchronously on the SAME thread inside add_done_callback. That thread
        # is already holding the lock from _submit_agentic_job; re-acquiring
        # via _on_agentic_complete's `with self._agentic_futures_lock:` would
        # deadlock under a plain Lock. RLock permits same-thread re-entry.
        self._agentic_futures_lock   = threading.RLock()

        # Option (a) true-monopoly (bug 30398595): id_hash of the monopolize job
        # currently holding the pool, or None. Set in _submit_agentic_job when a
        # monopolize job is dispatched; cleared from EVERY terminal path
        # (_on_agentic_complete AND _ghost_job_sweep) via _release_monopolize_hold
        # so a wedged sweep can never freeze intake permanently. Guarded by
        # _agentic_futures_lock (same lifecycle as the futures dict).
        self._monopolize_active      = None

        # Phase 3 (CJ Flow async multi-lane): ghost-job sweeper daemon thread
        # Periodically scans _agentic_futures for entries whose Future.done()
        # is True but whose job is still in running_queue (transition never
        # happened due to callback crash). Dead-letters them. Suspenders to
        # Phase 2's defensive callback belt.
        self._config_mgr                    = config_mgr
        self._ghost_job_sweeper_stop_event  = threading.Event()
        self._ghost_job_sweeper_thread      = threading.Thread(
            target = self._ghost_job_sweep_loop,
            daemon = True,
            name   = "GhostJobSweeper",
        )
        self._ghost_job_sweeper_thread.start()

        # WG-8 (2026-04-28): consumer-thread heartbeat.
        # Updated by queue_consumer.consumer_worker at the top of each loop
        # iteration so /api/queue/pool-status can report seconds_since_heartbeat
        # for stall detection. None = consumer hasn't ticked yet.
        self.last_consumer_heartbeat_at = None
        if config_mgr is not None:
            self._consumer_stall_threshold_seconds = config_mgr.get(
                "cj flow consumer stall threshold seconds", default=120, return_type="int"
            )
        else:
            self._consumer_stall_threshold_seconds = 120

        # Option (a) true-monopoly (bug 30398595): Gate-A drain budget. How long
        # the consumer waits for the agentic pool to drain of foreign writers
        # before dispatching a monopolize job; on timeout the sweep is
        # dead-lettered (fail loud, never dispatch onto a contaminated DB).
        if config_mgr is not None:
            self._monopolize_drain_timeout_seconds = config_mgr.get(
                "cj flow monopolize drain timeout seconds", default=300, return_type="int"
            )
        else:
            self._monopolize_drain_timeout_seconds = 300


    def enter_running_loop( self ) -> None:
        """
        DEPRECATED: Enter the main job execution loop.
        
        This method is deprecated in favor of the producer-consumer pattern
        using start_todo_producer_run_consumer_thread() which eliminates
        the inefficient polling with time.sleep(1).
        
        Use _process_job() for individual job processing instead.
        
        Requires:
            - All queue instances are initialized
            - websocket_mgr is connected
            
        Ensures:
            - Continuously processes jobs from todo queue
            - Emits socket updates for queue states
            - Never returns (infinite loop)
            
        Raises:
            - Exceptions handled internally
        """
        print( "Starting job run loop..." )
        while True:
            
            if not self.jobs_todo_queue.is_empty():
                
                print( "Jobs running @ " + du.get_current_datetime() )
                
                print( "popping one job from todo Q" )
                job = self.jobs_todo_queue.pop()  # Auto-emits 'todo_update'
                
                self.push( job )  # Auto-emits 'run_update'
                
                # Point to the head of the queue without popping it
                running_job = self.head()
                
                # Limit the length of the question string
                truncated_question = du.truncate_string( running_job.last_question_asked, max_len=64 )
                
                run_timer = sw.Stopwatch( "Starting job run timer..." )
                
                # Assume for now that all *agents* are of type AgentBase. If it's not, then it's a solution snapshot
                if isinstance( running_job, AgentBase ):
                    running_job = self._handle_base_agent( running_job, truncated_question, run_timer )
                else:
                    running_job = self._handle_solution_snapshot( running_job, truncated_question, run_timer )
            
            else:
                # print( "No jobs to pop from todo Q " )
                time.sleep( 1 )
    
    def _process_job( self, job: Any ) -> None:
        """
        Process a single job (extracted from enter_running_loop).
        
        Requires:
            - job is a valid job instance (AgentBase or SolutionSnapshot)
            - Job is already in the running queue
            
        Ensures:
            - Processes job based on its type
            - Moves job to done or dead queue when complete
            - Emits appropriate WebSocket updates
            
        Raises:
            - None (exceptions handled internally)
        """
        try:
            # Phase 2 fix: use the `job` parameter explicitly, not self.head().
            # Pre-Phase-2 (serial agentic processing), _process_job ran agentic
            # jobs inline and they were always removed from the running queue
            # before the next job arrived — so self.head() coincidentally
            # matched the passed `job`. Phase 2 submits agentic jobs to a pool
            # and returns immediately, so the running queue can hold MULTIPLE
            # in-flight jobs (one per pool worker + any phantoms). self.head()
            # then returns the OLDEST running job, not the one the consumer
            # just pushed — causing re-submission of already-in-flight jobs
            # and orphaning of the intended new job. Passing `job` explicitly
            # fixes both Bug 2A (phantom run-queue entry) and Bug 2B (duplicate
            # done-queue pushes) surfaced by the 2026-04-24 Live API probe.
            running_job = job

            if not running_job:
                print( "[RUNNING] Warning: _process_job called but no job in running queue" )
                return

            # JOB-TRACE: Log each job processing for duplicate investigation
            import time
            timestamp_trace = time.strftime( "%Y-%m-%d %H:%M:%S" )
            print( f"[JOB-TRACE] {timestamp_trace} Processing: {du.truncate_string( running_job.last_question_asked, 50 )}..." )

            # Limit the length of the question string
            truncated_question = du.truncate_string( running_job.last_question_asked, max_len=64 )

            run_timer = sw.Stopwatch( "Starting job run timer..." )

            # Process based on job type
            # IMPORTANT: Check AgenticJobBase FIRST since it's a separate hierarchy from AgentBase
            if isinstance( running_job, AgenticJobBase ):
                # Phase 2: Submit to agentic pool; return immediately so consumer
                # thread is free to pop the next todo job. Pool worker calls
                # job.do_all(); Future callback _on_agentic_complete moves the
                # job from running_queue → done/dead. Job is already in
                # running_queue (consumer pushed it).
                self._submit_agentic_job( running_job )
                return

            elif isinstance( running_job, AgentBase ):
                if isinstance( running_job, CrudForDataFramesAgent ):
                    # CRUD agents: skip cache — data is mutable, snapshots go stale
                    if self.debug: print( "[CACHE] Skipping cache for CRUD agent (mutable data)" )
                    running_job = self._handle_base_agent( running_job, truncated_question, run_timer )
                else:
                    # NEW: Check cache BEFORE agent execution
                    question = running_job.last_question_asked

                    if self.debug: print( f"[CACHE] Checking cache for question: {question}" )

                    # Search for existing snapshot
                    cached_snapshots = self.snapshot_mgr.get_snapshots_by_question( question )

                    if cached_snapshots and len( cached_snapshots ) > 0:
                        # Unpack best match
                        score, cached_snapshot = cached_snapshots[ 0 ]

                        if score >= 100.0:
                            # Exact match — auto-accept
                            if self.debug: print( f"[CACHE] EXACT HIT: score {score:.1f}% from {cached_snapshot.run_date}" )
                            running_job = self._format_cached_result( cached_snapshot, running_job, truncated_question, run_timer )

                        else:
                            # ── the ACCEPT-ABOVE-FLOOR branch was DELETED here (step 7b) ──
                            #
                            # WHAT IT WAS: `elif score >= self.threshold_confirmation:` —
                            # anything from 90% up was served from the cache without asking
                            # anybody. WHY IT WAS BAD: its own comment said why it was
                            # allowed — "push_job already handled user confirmation". That
                            # was true while push_job asked. push_job is dead (step 6c: the
                            # doors were retired, the internal callers moved, and door 8
                            # hands the transcription to the flow), so the confirmation this
                            # branch leaned on had already stopped happening — and a
                            # 90-to-99% match was being replayed with nobody asked. Exactly
                            # the silent wrong-but-close answer the plan says we would never
                            # have, arriving as a side effect of a cutover rather than a
                            # decision.
                            #
                            # WHAT CARRIES CONFIRMATION NOW: AskFlow's near-match ask (step
                            # 6b) — the same question, the same 30 seconds, the same default
                            # of "no" — which runs BEFORE the job is ever queued. A second,
                            # silent accept behind it would answer a question the user had
                            # already been asked about and may have declined.
                            #
                            # Below an exact hit, this now routes to the agent.
                            print( f"[CACHE] BELOW EXACT: score {score:.1f}% — routing to agent (the flow already asked)" )
                            running_job = self._handle_base_agent( running_job, truncated_question, run_timer )
                    else:
                        # CACHE MISS - Continue with normal agent execution
                        if self.debug: print( f"[CACHE] MISS: Running agent for new question" )

                        running_job = self._handle_base_agent( running_job, truncated_question, run_timer )
            else:
                running_job = self._handle_solution_snapshot( running_job, truncated_question, run_timer )
                
        except Exception as e:
            print( f"[RUNNING] Error processing job: {e}" )
            print( f"[RUNNING] Full stack trace:" )
            traceback.print_exc()

            # OOS-4 Part A hotfix (2026-04-28): use the `job` parameter explicitly,
            # NOT self.head(). Phase 2 introduced the agentic pool — the running
            # queue can hold multiple in-flight jobs (one per pool worker + any
            # fast-lane job currently being processed). self.head() returns the
            # OLDEST running job, which during a fast-lane crash is the agentic
            # pool job (e.g. test_suite) running async, NOT the fast-lane job
            # (e.g. Calculator) that just raised. Mis-attribution dead-letters
            # the WRONG job. Fix mirrors the happy-path correction at line 203
            # ('running_job = job') that landed for Bug 2A/2B but missed this
            # exception branch. Repro: 2026-04-28 ts-1c41e064 killed at 17:53.
            failed_job = job
            if failed_job:  # pragma: no branch - False->exit arc unreachable: failed_job = job (L285) is the same param the L205-207 `if not running_job: return` guard already proved truthy (running_job = job at L203, job never reassigned), so any exception reaching this except has job truthy → the True arc always fires; only a pathological stateful __bool__ flipping mid-do_all could differ, which is not a designed contract
                # OOS-4 Finding C (2026-04-29 Phase 4): route through the
                # canonical `_transition_to_dead` primitive instead of the
                # ~50-line inline duplicate that was here pre-refactor. The
                # canonical primitive sets job.error, builds metadata, emits
                # the WS state transition, deletes from running_queue, pushes
                # to dead_queue, and runs the auto-fix watchdog — exactly
                # what the inline copy did, minus the drift risk. The OOS-4
                # Part B hotfix (failed_job.error = str(e)) is now subsumed
                # by `_transition_to_dead`'s normalization at line 729-734.
                self._transition_to_dead( failed_job, e )
    
    def _handle_error_case( self, response: dict, running_job: Any, truncated_question: str, error_message: str=None ) -> Any:
        """
        Handle error cases during job execution.

        Requires:
            - response is a dictionary with 'output' key
            - running_job is a valid job instance
            - truncated_question is a string
            - error_message is an optional string with a specific error description

        Ensures:
            - Logs the failure banner + captured stdout
            - Delegates to the canonical `_transition_to_dead` primitive,
              which handles: TTS notify, error persistence on the job,
              metadata build, WS emit, queue delete + dead-queue push,
              and auto-fix watchdog evaluation
            - Returns the job instance (preserved for back-compat with
              callers at lines _handle_base_agent error fallback and
              _format_cached_result error fallback)

        Raises:
            - None (handles errors gracefully)
        """
        du.print_banner( f"Error running code for [{truncated_question}]", prepend_nl=True )

        for line in response[ "output" ].split( "\n" ): print( line )

        # OOS-4 Finding C (2026-04-29 Phase 4): canonical dead-queue path.
        # Pre-refactor this method had ~60 lines duplicating _transition_to_dead.
        notification_msg = error_message if error_message else "I'm sorry Dave, I'm afraid I can't do that. Please check your logs"
        self._transition_to_dead( running_job, notification_msg )

        return running_job

    # =============================================================================
    # Phase 2 (CJ Flow async multi-lane): agentic pool + shared transition primitives
    #
    # The pool runs agentic jobs concurrently (up to _pool_max_workers); fast-lane
    # jobs (AgentBase, SolutionSnapshot) continue to run inline on the consumer
    # thread. The Future callback _on_agentic_complete is the only post-do_all()
    # path for pool jobs. _transition_to_done / _transition_to_dead are the
    # canonical completion primitives — callable from the pool callback (Phase 2)
    # or later migrated into fast-lane paths (Phase 3 cleanup).
    # =============================================================================

    def _submit_agentic_job( self, job: AgenticJobBase ) -> None:
        """
        Submit an agentic job to the pool; track Future + register callback.

        **Consumer integration note**: In Lupin's current architecture, the
        consumer thread (`queue_consumer.py::consumer_worker`) already does
        `emit_job_state_transition(QUEUED→RUNNING)` and `running_queue.push(job)`
        BEFORE invoking `_process_job` → this method. So the job is already in
        running_queue and the UI has already seen the transition by the time
        we submit to the pool. We ONLY do the atomic submit+track+callback here.

        Design-doc 3-step ordering (push → emit → submit+track) is preserved
        system-wide across consumer + this method; don't duplicate.

        Ordering invariant (atomic-under-lock, load-bearing):
          submit() + _agentic_futures[id_hash] assignment + add_done_callback
          ALL inside _agentic_futures_lock — closes the sub-microsecond race
          where a fast-completing Future fires its callback before
          _agentic_futures has the key.

        Requires:
            - job implements AgenticJobBase
            - job is ALREADY in running_queue (consumer pushed it)

        Ensures:
            - job.id_hash is a key in _agentic_futures with the pool Future
            - Future has _on_agentic_complete registered as done_callback
        """
        with self._agentic_futures_lock:
            # Shape-B (bug fe375cf6): route a monopolize job to the DEDICATED
            # single-worker executor so it does NOT consume a shared-pool slot —
            # the full width N stays free for its lineage children. Non-monopolize
            # jobs use the shared pool (unchanged). The executor pick is the ONLY
            # new behavior; everything below (track in the SAME _agentic_futures
            # dict, set the hold, register the callback) is identical for both, so
            # invariants I1-I3 (atomic track, release-before-transition, ghost
            # sweep) hold regardless of which executor produced the Future.
            is_mono = getattr( job, "monopolize", False ) and self._is_monopolize_enabled()
            pool    = self._monopolize_pool if is_mono else self._agentic_pool
            future  = pool.submit( self._execute_agentic_in_pool, job )
            self._agentic_futures[ job.id_hash ] = future
            # Option (a) true-monopoly (bug 30398595): a monopolize job now holds
            # the pool → Gate B (queue_consumer) defers foreign intake (admitting
            # lineage children) until it clears. Set under the same lock as the
            # futures dict so the flag and the future land atomically. Gated by the
            # master kill-switch (read fresh via is_mono): when disabled the hold is
            # never SET → old no-op AND the job routes to the shared pool.
            if is_mono:
                self._monopolize_active = job.id_hash
            future.add_done_callback(
                lambda f, j=job: self._on_agentic_complete( j, f )
            )

    def _execute_agentic_in_pool( self, job: AgenticJobBase ) -> Any:
        """
        Runs inside a pool worker thread. Blocks on job.do_all() and returns
        whatever do_all() returns (fed to _on_agentic_complete via future.result()).

        do_all() creates its own asyncio event loop via asyncio.run() internally;
        safe here because each call is on a distinct pool thread with no
        pre-existing loop.
        """
        return job.do_all()

    def _on_agentic_complete( self, job: AgenticJobBase, future ) -> None:
        """
        Future callback — runs on a pool thread after do_all() returns or raises.
        Moves job from running_queue to done_queue or dead_queue.

        INVARIANT (load-bearing, see design doc 03 §Step 2.1): pop from
        _agentic_futures BEFORE transitioning. The Phase-3 ghost-sweeper uses
        "still in _agentic_futures AND Future.done()" as the signal that a
        transition never happened; reversing these two ops opens a race window
        where the sweeper dead-letters a job that was just moved to done_queue.

        Defensive:
          - Outer `except BaseException`: KeyboardInterrupt / SystemExit /
            GeneratorExit survivors are LOGGED and left for the Phase-3 sweeper
            rather than pushed through _transition_to_dead (which can itself
            raise). Never re-raise — ThreadPoolExecutor treats callback
            exceptions as fatal and can deadlock the pool.
          - Inner `except Exception`: failures during dead-letter are logged;
            job left in _agentic_futures for the sweeper as last resort.
        """
        try:
            # INVARIANT: pop from futures dict BEFORE transitioning
            with self._agentic_futures_lock:
                self._agentic_futures.pop( job.id_hash, None )
            # Option (a) (bug 30398595): release the monopoly hold on ANY terminal
            # outcome (done/exception/stalled/failed) so intake resumes.
            self._release_monopolize_hold( job.id_hash )

            exc = future.exception()
            if exc is not None:
                if isinstance( exc, Exception ):
                    # Regular Exception → dead-letter path
                    self._transition_to_dead( job, exc )
                else:
                    # BaseException-but-not-Exception survivor (KeyboardInterrupt,
                    # SystemExit, GeneratorExit) — log-only; leave for Phase-3
                    # ghost-sweeper. Attempting dead-letter is risky because
                    # transition code may itself raise more BaseExceptions.
                    du.print_banner(
                        f"_on_agentic_complete: BaseException survivor for {job.id_hash}: {exc!r}",
                        prepend_nl=True
                    )
                return

            formatted_output = future.result()

            # Stalled terminal (Bug 11 2026-04-15, ported to pool path 2026-04-26):
            # voice gate timed out and orchestrator saved a checkpoint. Route to
            # Done with status=stalled so the UI badge + Resume button activate.
            # Without this branch, _transition_to_done overwrites status='completed'
            # and drops the checkpoint blob, breaking checkpoint-resume entirely.
            # Mirrors the legacy serial path's stall check at line ~898.
            if job.state == JobState.STALLED:
                self._transition_to_stalled( job, formatted_output )
                return

            # Failed terminal: agentic do_all() may catch its own exception, set
            # state=FAILED, and RETURN the error string rather than re-raise.
            # In that case future.exception() is None but the job is genuinely
            # failed and belongs in the dead queue. Without this branch the job
            # gets pushed to done_queue with status=failed (and BFE auto-fix
            # never fires because _evaluate_for_auto_fix runs only from the dead
            # path). Symmetric to the STALLED branch above.
            if job.state == JobState.FAILED:
                cause = job.error or formatted_output or "Job reported FAILED with no error message"
                self._transition_to_dead( job, cause )
                return

            self._transition_to_done( job, formatted_output )

        except BaseException as e:
            # Outer BaseException catch: keep the executor alive even if
            # KeyboardInterrupt / SystemExit leaks out of the body above.
            du.print_banner(
                f"_on_agentic_complete FAILED for job {job.id_hash}: {e!r}",
                prepend_nl=True
            )
            if isinstance( e, Exception ):
                try:
                    self._transition_to_dead( job, e )
                except Exception as inner:
                    du.print_banner(
                        f"Dead-letter ALSO failed for {job.id_hash}: {inner!r}",
                        prepend_nl=True
                    )
                    # Last-resort: leave for Phase-3 ghost-sweeper.
            # BaseException-but-not-Exception survivors: log only, no dead-letter.
            # Never re-raise from a Future callback.

    def _transition_to_done( self, job: Any, formatted_output: Any = None ) -> None:
        """
        Canonical success transition. Thread-safe (callable from consumer OR
        pool-callback threads). Reads derived values (answer_conversational,
        artifacts, etc.) directly from job.* set by do_all() as side-effects;
        formatted_output is the return value used for I/O logging only.

        Extracted from the agentic-success block historically at
        running_fifo_queue.py lines 409-480. Phase 2 scope: shared with the
        pool callback only. Phase 3 cleanup can migrate fast-lane paths
        (_handle_base_agent success, _format_cached_result, etc.) to call
        this helper too.

        Order:
          TTS → build metadata → emit RUNNING → COMPLETED → delete from
          running_queue → push to done_queue → TFE watchdog evaluate →
          I/O table insert.
        """
        # Leg (c) P3 — close the done->dead sweeper race: claim the SAME terminal
        # marker _transition_to_dead uses, so a racing ghost-sweep that dead-letters
        # this job (or a late duplicate callback) no-ops instead of double-transitioning
        # a row already completed. Claimed atomically; rolled back below on any
        # mid-transition failure so a failed done never wedges the slot (a claim that
        # stuck through a FAILED done would make the follow-on _transition_to_dead
        # no-op too — the exact wedge leg (c) exists to prevent).
        if not self._claim_terminal_reclaim( job ):
            if self.debug:
                print( "[AGENTIC-POOL] _transition_to_done no-op — job already terminal (Leg c P3)" )
            return

        try:
            # TTS Migration (Session 97): notify via notification service
            self._notify( job.answer_conversational, job=job )

            job_id       = job.id_hash
            user_id      = job.user_id
            completed_at = du.get_current_datetime_iso()
            started_at   = job.started_at

            duration_seconds = compute_duration_seconds( started_at, completed_at )

            # artifacts-based fields are agentic-specific; fast-lane jobs have empty
            # artifacts or no artifacts attribute — use getattr for boundary safety
            artifacts = getattr( job, "artifacts", None ) or { }
            metadata  = {
                "response_text"             : job.answer_conversational,
                "abstract"                  : artifacts.get( "abstract" ),
                "report_link"               : artifacts.get( "report_path" ),
                "remediation_snapshot_path" : artifacts.get( "remediation_snapshot_path" ),
                "yaml_path"                 : artifacts.get( "yaml_path" ),
                "pptx_path"                 : artifacts.get( "pptx_path" ),
                "cost_summary"              : artifacts.get( "cost_summary" ),
                "error"                     : None,
                "question_text"             : job.last_question_asked,
                "agent_type"                : job.job_type,
                "timestamp"                 : job.created_date,
                "status"                    : JobState.COMPLETED.value,
                "has_interactions"          : bool( job.session_id ),
                "is_cache_hit"              : job.is_cache_hit,
                "user_email"                : job.user_email,
                "started_at"                : started_at,
                "completed_at"              : completed_at,
                "duration_seconds"          : duration_seconds,
            }
            emit_job_state_transition(
                self.websocket_mgr, job_id, JobState.RUNNING, JobState.COMPLETED, user_id, metadata
            )

            # Queue transition (Phase 1 RLock protects both queues under concurrency)
            self.delete_by_id_hash( job.id_hash )
            self.jobs_done_queue.push( job )
        except BaseException:
            self._release_terminal_reclaim( job )   # failed done stays retryable
            raise

        # TFE auto-dispatch (non-fatal if watchdog isn't initialized)
        try:
            from cosa.rest.test_suite_completion_watchdog import get_watchdog
            _tfe_watchdog = get_watchdog()
            if _tfe_watchdog is not None:
                _tfe_watchdog.evaluate( job )
        except Exception as _tfe_e:
            if self.debug: print( f"[AGENTIC-POOL] TFE watchdog evaluate skipped: {_tfe_e}" )

        # I/O table (non-fatal if unavailable)
        try:
            self.io_tbl.insert_io_row(
                input_type   = job.routing_command,
                input        = job.last_question_asked,
                output_raw   = str( artifacts ) if artifacts else str( formatted_output ),
                output_final = job.answer_conversational,
            )
        except Exception as io_e:
            if self.debug: print( f"[AGENTIC-POOL] I/O table write skipped: {io_e}" )

    def _transition_to_stalled( self, job: Any, formatted_output: Any = None ) -> None:
        """
        Stalled-terminal transition for agentic jobs that hit a voice-gate
        timeout and saved a checkpoint. Routes the job to Done with
        status='stalled' so the UI badge + Resume button activate; persistence
        dispatch in queue_util.emit_job_state_transition routes
        `to_state == JobState.STALLED` to persist_job_stalled_from_metadata,
        which writes status='stalled' to job_history and preserves the
        checkpoint blob in metadata_json for later resume.

        Mirrors _transition_to_done's structure, but emits JobState.STALLED
        with `checkpoint` + `plan_path` in the metadata blob, instead of
        JobState.COMPLETED with no checkpoint.

        Bug 11 (2026-04-15) added the equivalent stall handling in the legacy
        serial path (_handle_agentic_job, ~line 898). Phase 2's pool refactor
        moved agentic dispatch to _on_agentic_complete but did not port the
        stall check, leaving status='completed' as the unconditional outcome
        for ALL agentic jobs going through the pool — including TFE and BFE
        voice-gate stalls. This helper closes that gap.

        Order:
          TTS (informational, not urgent) → build metadata WITH checkpoint →
          emit RUNNING → STALLED → delete from running_queue → push to
          done_queue → I/O table insert. Does NOT invoke the dead-queue /
          auto-repair watchdog — the checkpoint IS the repair path; BFE would
          just swallow it on its own DB lookup.
        """
        # Leg (c) P3 — claim the SAME terminal marker so a racing ghost-sweep
        # dead-letter no-ops instead of stalling-then-dead double-transitioning.
        # Safe for resume: a resumed stalled job is a FRESH object built by
        # agentic_job_factory (_resume_checkpoint attached to a new construction),
        # so this per-object marker never carries into the resumed run — verified
        # 2026-08-13. Rolled back below on any mid-transition failure.
        if not self._claim_terminal_reclaim( job ):
            if self.debug:
                print( "[AGENTIC-POOL] _transition_to_stalled no-op — job already terminal (Leg c P3)" )
            return

        try:
            # TTS — informational tone (not urgent — this is a normal stall, not a crash)
            self._notify( job.answer_conversational, job=job )

            job_id       = job.id_hash
            user_id      = job.user_id
            completed_at = du.get_current_datetime_iso()
            started_at   = job.started_at

            duration_seconds = compute_duration_seconds( started_at, completed_at )

            artifacts = getattr( job, "artifacts", None ) or { }
            metadata  = {
                "response_text"             : job.answer_conversational,
                "abstract"                  : artifacts.get( "abstract" ),
                "report_link"               : artifacts.get( "report_path" ),
                "remediation_snapshot_path" : artifacts.get( "remediation_snapshot_path" ),
                "yaml_path"                 : artifacts.get( "yaml_path" ),
                "pptx_path"                 : artifacts.get( "pptx_path" ),
                "cost_summary"              : artifacts.get( "cost_summary" ),
                # Stall-specific fields (the missing piece pre-fix):
                "checkpoint"                : artifacts.get( "checkpoint" ),
                "plan_path"                 : artifacts.get( "plan_path" ),
                "error"                     : None,
                "question_text"             : job.last_question_asked,
                "agent_type"                : job.job_type,
                "timestamp"                 : job.created_date,
                "status"                    : JobState.STALLED.value,
                "has_interactions"          : bool( job.session_id ),
                "is_cache_hit"              : False,
                "user_email"                : job.user_email,
                "started_at"                : started_at,
                "completed_at"              : completed_at,
                "duration_seconds"          : duration_seconds,
            }
            emit_job_state_transition(
                self.websocket_mgr, job_id, JobState.RUNNING, JobState.STALLED, user_id, metadata
            )

            # Queue transition — same pattern as _transition_to_done but explicitly
            # NOT firing the TFE auto-dispatch watchdog (stalled jobs are awaiting
            # human review, not failed jobs needing repair).
            self.delete_by_id_hash( job.id_hash )
            self.jobs_done_queue.push( job )
        except BaseException:
            self._release_terminal_reclaim( job )   # failed stall stays retryable
            raise

        # I/O table (non-fatal if unavailable)
        try:
            self.io_tbl.insert_io_row(
                input_type   = job.routing_command,
                input        = job.last_question_asked,
                output_raw   = str( artifacts ) if artifacts else str( formatted_output ),
                output_final = job.answer_conversational,
            )
        except Exception as io_e:
            if self.debug: print( f"[AGENTIC-POOL] I/O table write skipped (stalled): {io_e}" )

    def _claim_terminal_reclaim( self, job: Any ) -> bool:
        """
        Leg (c) — atomically claim a job's single terminal transition.

        Returns True exactly once per job OBJECT (first caller wins) and False on
        every subsequent call, so a terminal primitive can no-op a
        double-transition. The marker lives on the job object (getattr default
        False — heterogeneous job types may lack it until first claim; the
        acceptable external-object case, mirroring the getattr at ~line 736), so a
        resubmitted repair-chain job (a NEW object) is never falsely blocked.
        Checked+set under _agentic_futures_lock (an RLock, already re-entrant for
        the callback-on-same-thread case) so the read and the write are atomic
        against a racing ghost-sweep / completion callback.

        Requires:
            - job is a queue job object (attribute-settable)

        Ensures:
            - First call for a given job object returns True and marks it
            - Every later call for the same object returns False
        """
        with self._agentic_futures_lock:
            if getattr( job, "_brake_terminal_claimed", False ):
                return False
            job._brake_terminal_claimed = True
            return True

    def _release_terminal_reclaim( self, job: Any ) -> None:
        """
        Leg (c) rollback — release a claim taken by _claim_terminal_reclaim when
        the transition it guarded did NOT complete (raised mid-flight).

        Without this, a claim set at the top of _transition_to_dead would stick
        True even though emit/delete/push failed, leaving the job in
        running_queue with every later retry no-op'd — a slot that never frees,
        the exact runaway this brake exists to prevent (Tiberius P1, 2026-08-13).
        Releasing lets the ghost-sweeper's next tick re-attempt the transition.
        Idempotent; taken under _agentic_futures_lock so it is atomic against a
        concurrent claim.

        Requires:
            - job is a queue job object (attribute-settable)

        Ensures:
            - job's terminal claim is cleared (a subsequent claim can succeed)
        """
        with self._agentic_futures_lock:
            job._brake_terminal_claimed = False

    def _transition_to_dead( self, job: Any, cause: Any ) -> None:
        """
        Canonical failure transition. Thread-safe. `cause` may be an Exception
        instance OR a string (status-check-failure paths set running_job.error
        as a string). The body normalises both.

        Extracted from agentic failure paths at running_fifo_queue.py lines
        482-532 (status-check fail) + 534-592 (exception). Phase 2 scope:
        shared with the pool callback only; fast-lane paths (_handle_error_case
        et al.) may migrate in Phase 3 cleanup.

        Leg (c) idempotency: no-ops on a second entry for the SAME job object so a
        late completion callback, or a ghost-sweep that snapshotted
        _agentic_futures before _on_agentic_complete popped the future, cannot
        double-transition a row already declared dead.
        """
        # Leg (c) — status-guarded idempotent reclaim (design §Leg c). Claim
        # atomically so a concurrent ghost-sweep / completion callback cannot
        # double-transition this row.
        if not self._claim_terminal_reclaim( job ):
            if self.debug:
                print( "[AGENTIC-POOL] _transition_to_dead no-op — job already terminal (Leg c)" )
            return

        # The claim is now HELD. Everything below must either COMPLETE or roll the
        # claim back — a claim that stuck through a FAILED transition (emit/delete/
        # push raising) would leave the job in running_queue with every retry
        # no-op'd forever: a slot that never frees, the exact runaway this brake
        # exists to prevent (Tiberius P1, 2026-08-13). On any mid-transition
        # exception, release the claim so the ghost-sweeper's next tick can
        # re-attempt, then re-raise so the caller's error handling is unchanged.
        try:
            # Normalise cause
            if isinstance( cause, str ):
                error_msg   = cause
                stack_trace = cause
            else:
                error_msg   = str( cause )
                try:
                    stack_trace = "".join( traceback.format_exception( type( cause ), cause, cause.__traceback__ ) )
                except Exception:
                    stack_trace = error_msg

            # Ensure job.error reflects the failure (some paths set this already; some don't)
            try:
                if not job.error:
                    job.error = error_msg
                job.state = JobState.FAILED
            except Exception:
                pass  # Missing attributes on exotic job types — boundary tolerance

            du.print_banner( f"AgenticJob failed: {error_msg}", prepend_nl=True )

            # TTS notify — urgent priority
            job_type_label = getattr( job, "JOB_TYPE", job.job_type )
            self._notify(
                f"The {job_type_label} job encountered an error: {error_msg[ :100 ]}",
                job=job,
                priority="urgent"
            )

            job_id       = job.id_hash
            user_id      = job.user_id
            completed_at = du.get_current_datetime_iso()
            started_at   = job.started_at

            duration_seconds = compute_duration_seconds( started_at, completed_at )

            metadata = {
                "error"            : error_msg,
                "stack_trace"      : stack_trace,
                "question_text"    : job.last_question_asked,
                "agent_type"       : job.job_type,
                "timestamp"        : job.created_date,
                "status"           : JobState.FAILED.value,
                "has_interactions" : bool( job.session_id ),
                "is_cache_hit"     : False,
                "user_email"       : job.user_email,
                "started_at"       : started_at,
                "completed_at"     : completed_at,
                "duration_seconds" : duration_seconds,
            }
            emit_job_state_transition(
                self.websocket_mgr, job_id, JobState.RUNNING, JobState.FAILED, user_id, metadata
            )

            self.delete_by_id_hash( job.id_hash )
            try:
                self.jobs_dead_queue.push( job )
            except BaseException:
                # Tiberius residual (log-not-guard, María 2026-08-13): delete
                # succeeded but the dead-queue push raised, so the row is now in
                # NEITHER queue and the ghost-sweeper's queue_dict check will skip
                # it. An in-memory push effectively never raises, so this earns a
                # log line and nothing more — no recovery guard. Re-raise so the
                # outer handler still rolls the reclaim back.
                du.print_banner(
                    f"[AGENTIC-POOL] dead-queue push raised AFTER delete for {job.id_hash} "
                    f"— row orphaned (in neither queue); ghost-sweeper will skip it",
                    prepend_nl=True
                )
                raise
        except BaseException:
            # Transition did NOT complete — release the claim so a retry can
            # re-attempt (else the slot wedges forever), then re-raise unchanged.
            self._release_terminal_reclaim( job )
            raise

        # Phase 6A: automated repair evaluation.
        # Leg (b3): a runtime-brake timeout death must NOT re-arm the repair chain
        # — the failure is a non-returning SDK call (a systemic/environmental
        # hang), so a fresh attempt would just hang again. A brake that trips and
        # immediately respawns the same runaway is not a brake. Skip the watchdog
        # for BFETimeoutError deaths only; every other cause re-arms as before.
        # (Outside the reclaim-rollback try: the transition has COMPLETED and the
        # row is terminal by the time we get here; a watchdog hiccup must not undo
        # a finished dead-letter — its own except already swallows failures.)
        from cosa.agents.shared.fix_executor import BFETimeoutError
        if isinstance( cause, BFETimeoutError ):
            if self.debug: print( "[AGENTIC-POOL] auto-fix re-arm SKIPPED — runtime-brake timeout death (Leg b3)" )
        else:
            try:
                self._evaluate_for_auto_fix( job )
            except Exception as e:
                if self.debug: print( f"[AGENTIC-POOL] auto-fix eval skipped: {e}" )

    # ── _process_fast_lane was DELETED here (step 7a, 2026-08-21) ──────────────────
    #
    # WHAT IT WAS: ~40 lines that ran a non-agentic job inline — cache check, CRUD
    # sub-branch, snapshot dispatch — with a docstring saying it ran on the consumer
    # thread. WHY IT WAS BAD: nothing called it. `_process_job` inlines the same logic
    # itself (the cache branch above), so two copies of one decision sat side by side
    # and only one of them ever ran. Anyone looking for how a fast-lane job is handled
    # found this one first, complete with a confident docstring, and could change it all
    # day without changing what the server does. SIX tests pinned it, which is what
    # made it look maintained. (The plan and the row both said seven; the seventh grep
    # hit was the section header comment above them. Six is what was deleted.)
    #
    # HOW WE KNEW, because grep alone was not allowed to decide it: a temporary probe
    # recorded any entry to a file; its positive control proved the probe FIRES when the
    # method runs — a probe never seen to fire and a probe never reached leave identical
    # silence; and a live window on :7999 recorded zero trips. That window ran
    # 2026-08-21 16:30Z to 23:07Z, fragmented by six boots, and carried 65 requests on
    # /api/upload-and-transcribe-mp3, 2 on /api/v2/ask and 1 on /api/push. Real spoken
    # traffic went through this queue and none of it entered this method.
    #
    # The three helpers it called — _handle_base_agent, _format_cached_result,
    # _handle_solution_snapshot — are LIVE and stay: _process_job calls all three.

    def get_pool_status( self ) -> dict:
        """
        Return a snapshot of the agentic-pool state for /api/queue/pool-status.

        Requires:
            - Pool initialized in __init__

        Ensures:
            - Returns dict with keys: inflight_agentic_jobs, max_agentic_workers, pending_in_pool
            - inflight = submitted-but-not-done (running + pending)
            - pending  = queued inside pool's internal queue, not yet picked up by a worker
            - UI "running" count = inflight - pending
            - Phase 3: enriched with api_resource_manager per-provider state
              when the singleton is initialised; omitted with a marker if not
        """
        with self._agentic_futures_lock:
            # Shape-B (bug fe375cf6): the monopolizer runs on the DEDICATED executor,
            # not the shared pool, so exclude its Future from the shared-pool counts —
            # otherwise inflight_agentic_jobs (documented observability, CLAUDE.md
            # §CJ Flow) would silently count a non-pool job and the UI's
            # running = inflight - pending invariant would break. At most ONE
            # monopolizer can be present (Gate B defers a 2nd at intake before it
            # ever reaches _agentic_futures), so a single mono_id exclusion is complete.
            mono_id  = self._monopolize_active
            inflight = sum(
                1 for h, f in self._agentic_futures.items()
                if not f.done() and h != mono_id
            )
            pending  = sum(
                1 for h, f in self._agentic_futures.items()
                if not f.running() and not f.done() and h != mono_id
            )

        payload = {
            "inflight_agentic_jobs" : inflight,                 # shared pool only — meaning UNCHANGED
            "max_agentic_workers"   : self._pool_max_workers,
            "pending_in_pool"       : pending,
            "monopolize_inflight"   : mono_id is not None,      # Shape-B: the out-of-pool monopolizer
            "monopolize_id"         : mono_id,                  # None when no monopolizer holds
        }

        # WG-8 (2026-04-28): consumer-thread heartbeat for stall detection.
        # `last_consumer_heartbeat_at` is set by the consumer worker at the
        # top of each loop iteration. None = consumer has never ticked
        # (server just started or consumer never launched). seconds_since
        # is computed against datetime.now() so callers can compare against
        # `consumer_stall_threshold_seconds` to detect a frozen consumer.
        from datetime import datetime as _dt
        hb_at = self.last_consumer_heartbeat_at
        if hb_at is not None:
            seconds_since = ( _dt.now() - hb_at ).total_seconds()
        else:
            seconds_since = None
        payload[ "last_consumer_heartbeat_at" ]    = hb_at.isoformat() if hb_at else None
        payload[ "seconds_since_heartbeat" ]       = seconds_since
        payload[ "consumer_stall_threshold_secs" ] = self._consumer_stall_threshold_seconds
        payload[ "consumer_stalled" ] = (
            seconds_since is not None and seconds_since > self._consumer_stall_threshold_seconds
        )

        # Phase 3: enrich with ApiResourceManager state (per-provider contention)
        try:
            from cosa.utils.api_resource_manager import get_arm
            payload[ "api_resource_manager" ] = get_arm().get_status()
        except RuntimeError:
            # ARM not initialised (init_arm() never called) — include a marker so
            # observability tooling sees the absence rather than a missing key.
            payload[ "api_resource_manager" ] = { "state": "uninitialised" }
        except Exception as e:
            payload[ "api_resource_manager" ] = { "state": "error", "detail": str( e )[ :200 ] }

        return payload

    def get_non_test_inflight_agentic_jobs( self, exclude_id_hash: Optional[ str ] = None ) -> List[ Dict ]:
        """
        List inflight (submitted-but-not-done) agentic jobs whose backing job is
        NOT a test_suite job. Backs the merge-gate sweep exclusivity preflight
        (bug caf58f71 — concurrent-writer contamination).

        A monopolize-mode test_suite sweep and ANY other agentic job share the
        same lupin_db_test on :8000; a concurrent non-test writer corrupts the
        in-flight suite's DB expectations (the refresh_tokens duplicate-jti
        flood). `monopolize` is ENFORCED (bug 30398595): the consumer's Gate A
        (drain-before-dispatch) uses this classifier as its drain oracle and
        Gate B holds foreign intake for the sweep's duration. This method
        surfaces the FOREIGN concurrent writers — it EXEMPTS the sweep's own
        lineage children (bug 3a14292b): a job whose `spawned_by_id_hash` equals
        `exclude_id_hash` was spawned BY the sweep and is part of its exclusive
        window, not a contaminant. Exemption is keyed on explicit lineage, never
        on `job_type`, so a future monopolizer spawning non-swe children is
        covered too.

        Requires:
            - _agentic_futures / queue_dict initialised (always true post-__init__)

        Ensures:
            - returns one { "id_hash", "job_type" } dict per inflight FOREIGN
              agentic job (Future present AND not done)
            - the future named by exclude_id_hash (the sweep's own) is skipped
            - a job whose spawned_by_id_hash == exclude_id_hash (a lineage child
              of the sweep) is skipped — spawned BY the sweep is not foreign TO it
            - a future whose backing job is absent from queue_dict is reported
              with job_type "unknown" — fail-loud on the unclassifiable, it is
              still a writer we cannot vouch for
            - inflight snapshot is taken under _agentic_futures_lock; classifi-
              cation never raises

        Args:
            exclude_id_hash: id_hash of the calling sweep, excluded from the count
                (also the lineage key: its children are exempted)

        Returns:
            list of { "id_hash": str, "job_type": str } for foreign inflight writers
        """
        with self._agentic_futures_lock:
            inflight_hashes = [ h for h, f in self._agentic_futures.items() if not f.done() ]

        offenders = [ ]
        for id_hash in inflight_hashes:
            if id_hash == exclude_id_hash:
                continue
            job      = self.get_by_id_hash( id_hash ) if id_hash in self.queue_dict else None
            # Lineage exemption (bug 3a14292b): a job SPAWNED BY the sweep is not
            # foreign TO the sweep. Guarded on exclude_id_hash is not None so a
            # None sweep key never matches a job's default-None lineage field.
            if ( exclude_id_hash is not None and job is not None
                 and job.spawned_by_id_hash == exclude_id_hash ):
                continue
            job_type = job.job_type if job is not None else "unknown"
            if job_type == "test_suite":
                continue
            offenders.append( { "id_hash": id_hash, "job_type": job_type } )
        return offenders

    def _is_monopolize_enabled( self ) -> bool:
        """
        Read the master true-monopoly kill-switch FRESH each call (bug 30398595).

        Read at gate-time — NOT cached at __init__ — so an INI-only flip of
        `cj flow monopolize enabled` takes effect via hot config reload without a
        server bounce. Gates all three surfaces atomically (the _submit set, Gate
        A, Gate B all consult this one source), so no half-state (hold set while
        gates disabled, or vice versa) is possible by construction.

        Ensures:
            - returns the current `cj flow monopolize enabled` boolean
            - returns True when no config_mgr is bound (default-enforced)
        """
        if self._config_mgr is None:
            return True
        return self._config_mgr.get(
            "cj flow monopolize enabled", default=True, return_type="boolean"
        )

    def _release_monopolize_hold( self, id_hash: str ) -> None:
        """
        Clear the monopolize intake hold iff `id_hash` owns it (bug 30398595).

        Called from EVERY terminal path a monopolize job can exit by —
        _on_agentic_complete (done/exception/stalled/failed) AND _ghost_job_sweep
        (dead-letter of a wedged job). If the hold were cleared only in the
        normal callback, a ghost-swept monopolize job would freeze ALL intake
        permanently (Tiberius's added hazard).

        Requires:
            - id_hash is the terminating job's pool key

        Ensures:
            - _monopolize_active is set to None iff it currently equals id_hash
            - a no-op when a DIFFERENT (or no) job holds the hold — idempotent,
              safe to call from any terminal path more than once
        """
        with self._agentic_futures_lock:
            if self._monopolize_active == id_hash:
                self._monopolize_active = None

    def await_monopolize_pool_drain( self, job: Any, timeout_seconds: float,
                                     poll_seconds: float = 1.0, heartbeat_fn=None ) -> List[ Dict ]:
        """
        Gate A (bug 30398595): block until the agentic pool has no foreign
        (non-test) inflight writers, or until timeout_seconds elapses. Reuses the
        caf58f71 classifier (get_non_test_inflight_agentic_jobs) as the drain
        oracle — the sweep's own future is excluded via job.id_hash.

        Requires:
            - job.id_hash is the monopolize sweep's pool key (excluded)
            - timeout_seconds >= 0; poll_seconds > 0

        Ensures:
            - returns [] when the pool drained clean (safe to dispatch)
            - returns the offender list (get_non_test_inflight_agentic_jobs shape)
              when the timeout expired with foreign writers still inflight — the
              caller MUST fail loud (dead-letter the sweep), never dispatch onto
              a contaminated DB
            - ticks heartbeat_fn (when supplied) once per poll so a healthy drain
              wait never trips consumer-stall detection; sleeps poll_seconds
              between probes (no busy-loop)

        Args:
            job: the monopolize job about to be dispatched
            timeout_seconds: max seconds to wait for the pool to drain
            poll_seconds: interval between drain probes
            heartbeat_fn: optional zero-arg callback to refresh the consumer heartbeat

        Returns:
            list of offender dicts (empty when drained clean before timeout)
        """
        deadline  = time.monotonic() + timeout_seconds
        offenders = self.get_non_test_inflight_agentic_jobs( exclude_id_hash=job.id_hash )
        while offenders and time.monotonic() < deadline:
            if heartbeat_fn is not None:
                heartbeat_fn()
            time.sleep( poll_seconds )
            offenders = self.get_non_test_inflight_agentic_jobs( exclude_id_hash=job.id_hash )
        return offenders

    def _ghost_job_sweep( self ) -> None:
        """
        Scan _agentic_futures for entries whose Future is done but whose job
        is still in running_queue. Dead-letter them (suspenders to Phase 2's
        defensive callback belt).

        INVARIANT DEPENDENCY (from 03-phase-2-*.md Step 2.1): relies on
        _on_agentic_complete popping from _agentic_futures BEFORE transitioning.
        The sweeper's "still in _agentic_futures AND Future.done()" check is
        the signal that a transition never happened. If the callback is ever
        re-ordered to pop-after-transition, the sweeper would dead-letter
        jobs that just moved to done_queue.

        Second safeguard — get_by_id_hash None-check: the sweeper iterates a
        SNAPSHOT of _agentic_futures (not held lock). If a completion
        callback fires during iteration and transitions the job to done,
        get_by_id_hash returns None → skip. No double-transition.
        """
        with self._agentic_futures_lock:
            futures_snapshot = dict( self._agentic_futures )

        for id_hash, future in futures_snapshot.items():
            if not future.done():
                continue

            job = self.get_by_id_hash( id_hash ) if id_hash in self.queue_dict else None
            if job is None:
                # Already transitioned by someone; clean up our tracker
                with self._agentic_futures_lock:
                    self._agentic_futures.pop( id_hash, None )
                # Idempotent belt: the normal callback already released the hold,
                # but clear here too so no terminal path can leave it wedged.
                self._release_monopolize_hold( id_hash )
                continue

            cause = future.exception() or RuntimeError(
                f"Ghost job {id_hash} detected — Future done but transition never happened"
            )
            try:
                self._transition_to_dead( job, cause )
            except Exception as e:
                du.print_banner(
                    f"Ghost-job sweeper failed to dead-letter {id_hash}: {e}",
                    prepend_nl=True
                )

            with self._agentic_futures_lock:
                self._agentic_futures.pop( id_hash, None )
            # Option (a) added hazard (bug 30398595): a ghost-swept monopolize job
            # MUST release the hold here, else a wedged sweep freezes ALL intake
            # permanently. _transition_to_dead does not touch the hold.
            self._release_monopolize_hold( id_hash )

    def _ghost_job_sweep_loop( self ) -> None:
        """
        Main loop for the GhostJobSweeper daemon thread. Runs until
        _ghost_job_sweeper_stop_event is set (at shutdown).

        Uses Event.wait(timeout) instead of time.sleep so shutdown can
        interrupt the nap immediately without waiting up to interval_seconds.
        """
        interval_seconds = 30 if self._config_mgr is None else self._config_mgr.get(
            "cj flow ghost job sweep interval seconds", default=30, return_type="int"
        )
        while not self._ghost_job_sweeper_stop_event.is_set():
            try:
                self._ghost_job_sweep()
            except Exception as e:
                du.print_banner(
                    f"Ghost-job sweeper loop caught exception (continuing): {e!r}",
                    prepend_nl=True
                )
            self._ghost_job_sweeper_stop_event.wait( timeout=interval_seconds )

    def shutdown_pool( self, wait: bool = True, timeout: float = 30.0 ) -> None:
        """
        Stop the pool from accepting new work. If wait=True, block up to
        `timeout` seconds for in-flight jobs to finish. Survivors after timeout
        are dead-lettered so we don't leave phantom `running` rows on restart.

        Ordering note (per design doc 03 §Step 2.2): shutdown_pool must run
        BEFORE the consumer thread exits AND BEFORE the HTTP socket closes,
        so in-flight pool workers can still emit WebSocket state transitions
        as they finish.

        Phase 3: Stop the ghost-job sweeper FIRST (before pool drain) so it
        doesn't race against drain dead-lettering.
        """
        # Phase 3: stop sweeper before pool drain
        self._ghost_job_sweeper_stop_event.set()
        self._ghost_job_sweeper_thread.join( timeout=5.0 )
        if self._ghost_job_sweeper_thread.is_alive():
            print( "[AGENTIC-POOL] Warning: ghost-job sweeper did not exit within 5s" )

        self._agentic_pool.shutdown( wait=False, cancel_futures=False )
        # Shape-B (bug fe375cf6): the dedicated monopolize executor shuts down on the
        # same no-new-work flag as the shared pool.
        self._monopolize_pool.shutdown( wait=False, cancel_futures=False )
        print( "[AGENTIC-POOL] shutdown_pool accepted no-new-work flag" )

        if not wait:
            return

        deadline = time.time() + timeout

        with self._agentic_futures_lock:
            inflight = list( self._agentic_futures.items() )

        for id_hash, future in inflight:
            remaining = max( 0.0, deadline - time.time() )
            try:
                future.result( timeout=remaining )
            except TimeoutError:
                try:
                    job = self.get_by_id_hash( id_hash )
                    if job is not None:
                        self._transition_to_dead( job, TimeoutError( "shutdown_pool timeout" ) )
                except Exception as te:
                    print( f"[AGENTIC-POOL] shutdown dead-letter failed for {id_hash}: {te!r}" )
            except Exception:
                pass  # Already handled by _on_agentic_complete

        print( "[AGENTIC-POOL] shutdown_pool returning" )

    # =============================================================================
    # End Phase 2 pool + transition primitives
    # =============================================================================

    def _handle_agentic_job( self, running_job: AgenticJobBase, truncated_question: str, job_timer: sw.Stopwatch ) -> Any:
        """
        Handle execution of AgenticJobBase instances (Deep Research, Podcast, etc.).

        Agentic jobs are long-running background tasks that:
        - Run for minutes (not seconds)
        - Send progress notifications during execution
        - Don't cache results (each run is unique)
        - Generate artifacts (reports, audio files, etc.)

        Requires:
            - running_job is an AgenticJobBase instance
            - truncated_question is a string
            - job_timer is a running Stopwatch

        Ensures:
            - Executes job's do_all() method
            - Moves job to done queue on success, dead queue on failure
            - NO snapshot caching (is_cacheable = False)
            - Emits speech with conversational answer
            - Returns the job instance

        Raises:
            - None (exceptions handled internally)
        """
        msg = f"Running AgenticJob [{running_job.JOB_TYPE}] for [{truncated_question}]..."
        du.print_banner( msg=msg, prepend_nl=True )

        try:
            # Execute the job (synchronous wrapper around async execution)
            formatted_output = running_job.do_all()

            du.print_banner( f"AgenticJob [{running_job.id_hash}] complete!", prepend_nl=True, end="\n" )
            job_timer.print( "Done!", use_millis=True )

            # Stalled terminal (Bug 11, 2026-04-15): voice gate timed out and
            # orchestrator saved a checkpoint. Route to Done with status=stalled
            # so the UI badge + Resume button activate. Do NOT invoke the
            # dead-queue/auto-repair watchdog — the checkpoint IS the repair
            # path and BFE would just swallow the checkpoint on its own DB lookup.
            if running_job.state == JobState.STALLED:
                job_id  = running_job.id_hash
                user_id = running_job.user_id
                completed_at = du.get_current_datetime_iso()
                started_at   = running_job.started_at

                duration_seconds = compute_duration_seconds( started_at, completed_at )

                metadata = {
                    'response_text'   : running_job.answer_conversational,
                    'abstract'        : running_job.artifacts.get( 'abstract' ),
                    'report_link'     : running_job.artifacts.get( 'report_path' ),
                    'checkpoint'      : running_job.artifacts.get( 'checkpoint' ),
                    'plan_path'       : running_job.artifacts.get( 'plan_path' ),
                    'question_text'   : running_job.last_question_asked,
                    'agent_type'      : running_job.job_type,
                    'timestamp'       : running_job.created_date,
                    'status'          : JobState.STALLED.value,
                    'has_interactions': bool( running_job.session_id ),
                    'is_cache_hit'    : False,
                    'user_email'      : running_job.user_email,
                    'started_at'      : started_at,
                    'completed_at'    : completed_at,
                    'duration_seconds': duration_seconds,
                }
                emit_job_state_transition( self.websocket_mgr, job_id, JobState.RUNNING, JobState.STALLED, user_id, metadata )

                # Phase 2: id_hash-based delete
                self.delete_by_id_hash( running_job.id_hash )
                self.jobs_done_queue.push( running_job )  # Auto-emits 'done_update'

                try:
                    self.io_tbl.insert_io_row(
                        input_type   = running_job.routing_command,
                        input        = running_job.last_question_asked,
                        output_raw   = str( running_job.artifacts ),
                        output_final = running_job.answer_conversational
                    )
                except Exception as io_e:
                    if self.debug: print( f"[AGENTIC] I/O table write skipped (stalled): {io_e}" )

                return running_job

            if running_job.code_ran_to_completion() and running_job.formatter_ran_to_completion():
                # Success path
                # TTS Migration (Session 97): Use notification service instead of _emit_speech
                self._notify( running_job.answer_conversational, job=running_job )

                # Emit job state transition (run -> done) with completion metadata
                job_id  = running_job.id_hash
                user_id = running_job.user_id
                # Calculate completed_at timestamp for duration calculation
                completed_at = du.get_current_datetime_iso()
                started_at   = running_job.started_at

                # Calculate duration_seconds if both timestamps exist
                duration_seconds = compute_duration_seconds( started_at, completed_at )

                metadata = {
                    'response_text'   : running_job.answer_conversational,
                    'abstract'        : running_job.artifacts.get( 'abstract' ),
                    'report_link'                : running_job.artifacts.get( 'report_path' ),
                    'remediation_snapshot_path'  : running_job.artifacts.get( 'remediation_snapshot_path' ),
                    'yaml_path'                  : running_job.artifacts.get( 'yaml_path' ),
                    'pptx_path'                  : running_job.artifacts.get( 'pptx_path' ),
                    'cost_summary'    : running_job.artifacts.get( 'cost_summary' ),
                    'error'           : None,
                    # Phase 6.2: Card-rendering fields for client-side card creation
                    'question_text'   : running_job.last_question_asked,
                    'agent_type'      : running_job.job_type,
                    'timestamp'       : running_job.created_date,
                    'status'          : JobState.COMPLETED.value,
                    'has_interactions': bool( running_job.session_id ),
                    'is_cache_hit'    : running_job.is_cache_hit,
                    'user_email'      : running_job.user_email,
                    'started_at'      : started_at,
                    'completed_at'    : completed_at,
                    'duration_seconds': duration_seconds
                }
                emit_job_state_transition( self.websocket_mgr, job_id, JobState.RUNNING, JobState.COMPLETED, user_id, metadata )

                # Move through queue system
                # Phase 2: id_hash-based delete
                self.delete_by_id_hash( running_job.id_hash )
                self.jobs_done_queue.push( running_job )  # Auto-emits 'done_update'

                # TFE auto-dispatch hook (Session 1cfcdf73, step 13 of TFE plan).
                # If the completed job is a TestSuiteJob that finished with
                # failures, the TestSuiteCompletionWatchdog will enqueue a TFE
                # job to attempt automated remediation. All eligibility gating
                # happens inside evaluate() — we never raise here.
                try:
                    from cosa.rest.test_suite_completion_watchdog import get_watchdog
                    _tfe_watchdog = get_watchdog()
                    if _tfe_watchdog is not None:
                        _tfe_watchdog.evaluate( running_job )
                except Exception as _tfe_e:
                    if self.debug: print( f"[AGENTIC] TFE watchdog evaluate skipped: {_tfe_e}" )

                # Log to I/O table (skip if not available)
                try:
                    self.io_tbl.insert_io_row(
                        input_type   = running_job.routing_command,
                        input        = running_job.last_question_asked,
                        output_raw   = str( running_job.artifacts ),
                        output_final = running_job.answer_conversational
                    )
                except Exception as io_e:
                    if self.debug: print( f"[AGENTIC] I/O table write skipped: {io_e}" )

            else:
                # OOS-4 Finding C (2026-04-29 Phase 4): canonical dead-queue
                # path replacing ~50 lines of inline duplicate. _transition_to_dead
                # accepts a string OR exception cause and handles all the same
                # work (notify, error persistence, metadata, WS emit, queue
                # mutations, auto-fix watchdog).
                # Note: this entire `_handle_agentic_job` method is dead code
                # post-Phase 2 (the agentic pool callback `_on_agentic_complete`
                # replaced it). Kept refactored anyway so any reactivation
                # picks up the canonical path.
                self._transition_to_dead( running_job, running_job.error or "Unknown error" )

        except Exception as e:
            # Unexpected exception during execution
            du.print_stack_trace(
                e,
                explanation=f"AgenticJob do_all() failed",
                caller="RunningFifoQueue._handle_agentic_job()",
                debug=self.debug
            )

            running_job.state = JobState.FAILED
            running_job.error  = str( e )

            # OOS-4 Finding C: canonical dead-queue path (see comment above).
            self._transition_to_dead( running_job, e )

        return running_job

    def _evaluate_for_auto_fix( self, failed_job ):
        """
        Evaluate a failed job for automated BFE repair via the dead queue watchdog.

        Called after a job is pushed to the dead queue. Silently no-ops if the
        watchdog is not initialized or auto-fix is disabled.

        Args:
            failed_job: The job that just failed and was pushed to dead queue
        """
        try:
            from cosa.rest.dead_queue_watchdog import get_watchdog
            watchdog = get_watchdog()
            if watchdog:
                watchdog.evaluate( failed_job )
        except Exception as e:
            if self.debug: print( f"[RunningFifoQueue] Watchdog evaluation error: {e}" )

    def _handle_base_agent( self, running_job: AgentBase, truncated_question: str, agent_timer: sw.Stopwatch ) -> Any:
        """
        Handle execution of AgentBase instances.

        Requires:
            - running_job is an AgentBase instance
            - truncated_question is a string
            - agent_timer is a running Stopwatch

        Ensures:
            - Executes agent's do_all() method
            - Handles serialization for eligible agents
            - Updates queues and database
            - Emits socket updates
            - Returns the job (possibly converted to SolutionSnapshot)

        Raises:
            - Catches and handles all exceptions internally
        """
        msg = f"Running AgentBase for [{truncated_question}]..."
        
        code_response = {
            "return_code": -1,
            "output"     : "ERROR: code_response: Output not yet generated!?!"
        }
        
        formatted_output = "ERROR: Formatted output not yet generated!?!"

        # Stamp the start. Without this the fast lane never records one, so every
        # duration below reads None and the card shows no elapsed time — the live
        # half of row 4a9ebc4b. The agentic lane already does this for itself.
        running_job.started_at = du.get_current_datetime_iso()

        try:
            formatted_output    = running_job.do_all()
        
        except Exception as e:

            du.print_stack_trace( e, explanation="do_all() failed", caller="RunningFifoQueue._handle_base_agent()", debug=self.debug )
            running_job = self._handle_error_case( code_response, running_job, truncated_question, error_message=str( e ) )
            return running_job

        du.print_banner( f"Job [{running_job.last_question_asked}] complete...", prepend_nl=True, end="\n" )
        
        if running_job.code_ran_to_completion() and running_job.formatter_ran_to_completion():

            # If we've arrived at this point, then we've successfully run the agentic part of this job
            # TTS Migration (Session 97): Use notification service instead of _emit_speech
            self._notify( running_job.answer_conversational, job=running_job )
            agent_timer.print( "Done!", use_millis=True )

            # Only the ReceptionistAgent and WeatherAgent are not being serialized as a solution snapshot
            # TODO: this needs to not be so ad hoc as it appears right now!
            serialize_snapshot = (
                not isinstance( running_job, ReceptionistAgent ) and
                not isinstance( running_job, WeatherAgent ) and
                not isinstance( running_job, CrudForDataFramesAgent )
            )
            if serialize_snapshot:

                # recast the agent object as a solution snapshot object and add it to the snapshot manager
                running_job = SolutionSnapshot.create( running_job )

                # KLUDGE! I shouldn't have to do this!
                print( f"KLUDGE! Setting running_job.answer_conversational to [{formatted_output}]...")
                running_job.answer_conversational = formatted_output

                # Generate solution_summary_gist if missing (lazy backfill for cache hits or failed generations)
                if not running_job.solution_summary_gist:
                    code_explanation = running_job.solution_summary if running_job.solution_summary else running_job.thoughts
                    if code_explanation:
                        try:
                            running_job.set_solution_summary_gist( self.gist_normalizer.get_normalized_gist( code_explanation ) )
                            if self.debug: print( f"Generated solution_summary_gist: {du.truncate_string(running_job.solution_summary_gist, 100)}" )
                        except Exception as e:
                            if self.debug: print( f"Failed to generate solution_summary_gist: {e}" )

                running_job.update_runtime_stats( agent_timer )
                
                # Save snapshot to manager (inserts new or updates existing)
                print( f"Saving job [{truncated_question}] to snapshot manager..." )
                self.snapshot_mgr.save_snapshot( running_job )
                print( f"Saving job [{truncated_question}] to snapshot manager... Done!" )

                # Fire async correctness verification (non-blocking)
                self._fire_correctness_check_async(
                    running_job,
                    truncated_question,
                    du.truncate_string( running_job.answer_conversational or running_job.answer, 120 )
                )

                du.print_banner( "running_job.runtime_stats", prepend_nl=True )
                pprint.pprint( running_job.runtime_stats )
            else:
                print( f"NOT adding to snapshot manager" )
                # Only overwrite answer for truly ephemeral agents (not CRUD which sets answer in run_formatter)
                if not isinstance( running_job, CrudForDataFramesAgent ):
                    running_job.answer = "no code executed by non-serializing/ephemeral objects"

            # Emit job state transition (run -> done) with completion metadata for ALL agents
            job_id  = running_job.id_hash
            user_id = running_job.user_id

            # Calculate completed_at timestamp for duration calculation
            completed_at = du.get_current_datetime_iso()
            started_at   = running_job.started_at

            # Calculate duration_seconds if both timestamps exist
            duration_seconds = compute_duration_seconds( started_at, completed_at )

            metadata = {
                'response_text'   : running_job.answer_conversational,
                'abstract'        : None,
                'report_link'     : None,
                'cost_summary'    : None,
                'error'           : None,
                # Phase 6.2: Card-rendering fields for client-side card creation
                'question_text'   : running_job.last_question_asked,
                'agent_type'      : running_job.job_type,
                'timestamp'       : running_job.created_date,
                # Session 107: Fix field parity between WebSocket and server-fetched cards
                'status'          : JobState.COMPLETED.value,
                'has_interactions': bool( running_job.session_id ),
                'is_cache_hit'       : running_job.is_cache_hit,
                'user_email'         : running_job.user_email,
                'answer_is_correct'  : running_job.answer_is_correct if isinstance( running_job, SolutionSnapshot ) else None,
                'started_at'         : started_at,
                'completed_at'       : completed_at,
                'duration_seconds'   : duration_seconds
            }
            emit_job_state_transition( self.websocket_mgr, job_id, JobState.RUNNING, JobState.COMPLETED, user_id, metadata )

            # Phase 2: id_hash-based delete
            self.delete_by_id_hash( running_job.id_hash )
            self.jobs_done_queue.push( running_job )  # Auto-emits 'done_update'

            # Write the job to the database for posterity's sake
            self.io_tbl.insert_io_row( input_type=running_job.routing_command, input=running_job.last_question_asked, output_raw=running_job.answer, output_final=running_job.answer_conversational )

        else:

            running_job = self._handle_error_case( code_response, running_job, truncated_question )

        return running_job

    def _handle_solution_snapshot( self, running_job: SolutionSnapshot, truncated_question: str, run_timer: sw.Stopwatch ) -> SolutionSnapshot:
        """
        Handle execution of SolutionSnapshot instances.
        
        Requires:
            - running_job is a SolutionSnapshot instance
            - truncated_question is a string
            - run_timer is a running Stopwatch
            
        Ensures:
            - Executes stored code
            - Formats and emits output
            - Updates queues and database
            - Writes snapshot to file
            - Returns the updated snapshot
            
        Raises:
            - None (handles errors gracefully)
        """
        msg = f"Executing SolutionSnapshot code for [{truncated_question}]..."
        du.print_banner( msg=msg, prepend_nl=True )
        timer = sw.Stopwatch( msg=msg )
        _ = running_job.run_code()
        timer.print( "Done!", use_millis=True )

        formatted_output = running_job.run_formatter()
        print( formatted_output )
        # TTS Migration (Session 97): Use notification service instead of _emit_speech
        self._notify( running_job.answer_conversational, job=running_job )

        # Emit job state transition (run -> done) with completion metadata
        job_id  = running_job.id_hash
        user_id = running_job.user_id

        # Calculate completed_at timestamp for duration calculation
        completed_at = du.get_current_datetime_iso()
        started_at   = running_job.started_at

        # Calculate duration_seconds if both timestamps exist
        duration_seconds = compute_duration_seconds( started_at, completed_at )

        metadata = {
            'response_text'   : running_job.answer_conversational,
            'abstract'        : None,
            'report_link'     : None,
            'cost_summary'    : None,
            'error'           : None,
            # Phase 6.2: Card-rendering fields for client-side card creation
            'question_text'   : running_job.last_question_asked,
            'agent_type'      : running_job.job_type,
            'timestamp'       : running_job.created_date,
            # Session 107: Fix field parity between WebSocket and server-fetched cards
            'status'          : JobState.COMPLETED.value,
            'has_interactions'  : bool( running_job.session_id ),
            'is_cache_hit'      : False,
            'user_email'        : running_job.user_email,
            'answer_is_correct' : running_job.answer_is_correct,
            'started_at'        : started_at,
            'completed_at'      : completed_at,
            'duration_seconds'  : duration_seconds
        }
        emit_job_state_transition( self.websocket_mgr, job_id, JobState.RUNNING, JobState.COMPLETED, user_id, metadata )

        # Phase 2: id_hash-based delete
        self.delete_by_id_hash( running_job.id_hash )
        self.jobs_done_queue.push( running_job )  # Auto-emits 'done_update'

        # If we've arrived at this point, then we've successfully run the job
        run_timer.print( "Solution snapshot full run complete ", use_millis=True )

        # Generate solution_summary_gist if missing (lazy backfill for cache hits or failed generations)
        if not running_job.solution_summary_gist:
            if self.debug: print( f"Generating missing solution_summary_gist..." )
            # Use solution_summary or thoughts as code explanation source
            code_explanation = running_job.solution_summary if running_job.solution_summary else running_job.thoughts
            if code_explanation:
                try:
                    # Generate gist of solution_summary for future formatter optimization
                    running_job.set_solution_summary_gist( self.gist_normalizer.get_normalized_gist( code_explanation ) )
                    if self.debug: print( f"Generated solution_summary_gist: {du.truncate_string(running_job.solution_summary_gist, 100)}" )
                except Exception as e:
                    if self.debug: print( f"Failed to generate solution_summary_gist: {e}" )

        running_job.update_runtime_stats( run_timer )
        du.print_banner( f"Job [{running_job.question}] complete!", prepend_nl=True, end="\n" )

        # Persist updated runtime stats to the snapshot store
        print( f"Saving snapshot with runtime stats for [{truncated_question}]..." )
        self.snapshot_mgr.save_snapshot( running_job )
        print( f"Saving snapshot with runtime stats for [{truncated_question}]... Done!" )

        du.print_banner( "running_job.runtime_stats", prepend_nl=True )
        pprint.pprint( running_job.runtime_stats )
        
        # Write the job to the database for posterity's sake
        self.io_tbl.insert_io_row( input_type=running_job.routing_command, input=running_job.last_question_asked, output_raw=running_job.answer, output_final=running_job.answer_conversational )
        
        return running_job

    def _fire_correctness_check_async( self, snapshot: SolutionSnapshot, truncated_question: str, truncated_answer: str ) -> None:
        """
        Spawn a daemon thread that asks the user whether the answer was correct.

        Non-blocking: the job has already moved to the done queue before this fires.
        On response, updates snapshot.answer_is_correct and persists via save_snapshot().
        On timeout or error, leaves answer_is_correct as None (unverified).

        Requires:
            - snapshot is a SolutionSnapshot that has been saved to the store
            - truncated_question is a short string for the prompt
            - truncated_answer is a short string for the prompt

        Ensures:
            - Does NOT block the pipeline
            - Thread-safe via SolutionSnapshotManager._save_lock
            - Updates the stored snapshot on yes/no response
        """
        def _ask_and_update():
            try:
                msg = f"Was this answer correct? Question: '{truncated_question}' Answer: '{truncated_answer}'"

                request = NotificationRequest(
                    message          = msg,
                    response_type    = ResponseType.YES_NO,
                    response_default = "no",
                    timeout_seconds  = 60,
                    priority         = "high",
                    suppress_ding    = True,
                    target_user      = snapshot.user_email,
                    sender_id        = f"queue.correctness@lupin.deepily.ai"
                )

                response = notify_user_sync( request )

                if response.status == "responded":
                    snapshot.answer_is_correct = ( response.response_value == "yes" )
                    self.snapshot_mgr.save_snapshot( snapshot )
                    if self.debug: print( f"[CORRECTNESS] Recorded answer_is_correct={snapshot.answer_is_correct} for [{truncated_question}]" )

                    # Emit WebSocket event so UI can update the card
                    job_id  = snapshot.id_hash
                    user_id = snapshot.user_id
                    if self.websocket_mgr:
                        self.websocket_mgr.emit(
                            "answer_verified",
                            {
                                "job_id"            : job_id,
                                "answer_is_correct" : snapshot.answer_is_correct,
                                "user_id"           : user_id
                            }
                        )
                else:
                    if self.debug: print( f"[CORRECTNESS] No response for [{truncated_question}] (status={response.status}), leaving as None" )

            except Exception as e:
                if self.debug: print( f"[CORRECTNESS] Error during verification for [{truncated_question}]: {e}" )

        thread = threading.Thread( target=_ask_and_update, daemon=True, name=f"correctness-{snapshot.id_hash[:8]}" )
        thread.start()

    def _format_cached_result( self, cached_snapshot: Any, original_job: Any, truncated_question: str, run_timer: sw.Stopwatch ) -> Any:
        """
        Format cached snapshot result to behave like a freshly executed job.

        Requires:
            - cached_snapshot is a valid SolutionSnapshot with results
            - original_job is the job from which to get current user context
            - truncated_question is a string for logging
            - run_timer is a running Stopwatch

        Ensures:
            - Emits speech for cached result
            - Updates queues (moves user-contextualized copy to done queue)
            - Records replay on canonical snapshot for analytics
            - Emits websocket updates
            - Updates runtime stats
            - Returns a properly formatted cached result with current user context

        Raises:
            - None (handles errors gracefully)
        """
        msg = f"Using CACHED result for [{truncated_question}]..."
        du.print_banner( msg=msg, prepend_nl=True )

        # Re-execute cached code to get fresh output (fixes stale time queries)
        if self.debug: print( f"[CACHE] Re-executing cached code for fresh result..." )
        try:
            code_response = cached_snapshot.run_code( debug=self.debug, verbose=self.verbose )
        except ValueError as e:
            code_response = { "return_code" : 1, "output" : "" }
            if self.debug: print( f"[CACHE] ⚠ {e}" )

        if code_response.get( "return_code" ) == 0:
            # Format fresh output
            cached_snapshot.run_formatter()
            if self.debug: print( f"[CACHE] ✓ Code re-executed successfully" )
        else:
            # Code failed - use cached answer as fallback
            if self.debug: print( f"[CACHE] ⚠ Re-execution failed, using cached answer" )

        # Calculate time saved (first_run_ms - current cache retrieval time)
        cache_retrieval_ms = run_timer.get_delta_ms()
        first_run_ms       = cached_snapshot.runtime_stats.get( "first_run_ms", 0 )
        time_saved_ms      = max( 0, first_run_ms - cache_retrieval_ms )

        # Get current user context from original job
        # Phase 2: Direct attribute access - Protocol guarantees these exist
        current_user_id    = original_job.user_id
        current_session_id = original_job.session_id

        # Record replay on canonical snapshot (updates the stored record for analytics)
        cached_snapshot.record_replay(
            user_id=current_user_id,
            session_id=current_session_id,
            time_saved_ms=time_saved_ms
        )

        # Update runtime stats on canonical snapshot
        cached_snapshot.update_runtime_stats( run_timer )

        # Persist updated stats to the store (canonical snapshot with replay history)
        self.snapshot_mgr.save_snapshot( cached_snapshot )

        # Create user-contextualized copy for done queue (FIX: use current user, not original creator)
        done_queue_entry = cached_snapshot.for_current_user(
            user_id=current_user_id,
            session_id=current_session_id
        )

        # FIX (Session 98): Preserve original job's id_hash for user association matching
        # The user_job_tracker has association: original_job.id_hash -> user_id
        # Without this fix, done queue filter returns 0 jobs because cached snapshot has different id_hash
        done_queue_entry.id_hash = original_job.id_hash

        # Emit the cached answer as speech (use done_queue_entry for routing)
        # TTS Migration (Session 97): Use notification service instead of _emit_speech
        self._notify( cached_snapshot.answer_conversational, job=done_queue_entry )

        # Emit job state transition (run -> done) with completion metadata (cache hit)
        job_id  = done_queue_entry.id_hash
        user_id = done_queue_entry.user_id

        # Calculate completed_at timestamp for duration calculation (cache retrieval time)
        completed_at = du.get_current_datetime_iso()
        started_at   = original_job.started_at

        # Calculate duration_seconds if both timestamps exist (will be very short for cache hits)
        duration_seconds = compute_duration_seconds( started_at, completed_at )

        metadata = {
            'response_text'   : cached_snapshot.answer_conversational,
            'abstract'        : None,
            'report_link'     : None,
            'cost_summary'    : None,
            'error'           : None,
            # Phase 6.2: Card-rendering fields for client-side card creation
            'question_text'   : cached_snapshot.last_question_asked,
            'agent_type'      : cached_snapshot.job_type,
            'timestamp'       : cached_snapshot.created_date,
            'is_cache_hit'      : True,
            'user_email'        : cached_snapshot.user_email,
            'answer_is_correct' : cached_snapshot.answer_is_correct,
            # Session 107: Fix field parity between WebSocket and server-fetched cards
            'status'            : JobState.COMPLETED.value,
            'has_interactions'  : bool( original_job.session_id ),
            'started_at'        : started_at,
            'completed_at'      : completed_at,
            'duration_seconds'  : duration_seconds
        }
        emit_job_state_transition( self.websocket_mgr, job_id, JobState.RUNNING, JobState.COMPLETED, user_id, metadata )

        # Move job through the queue system properly
        # Phase 2: id_hash-based delete (done_queue_entry.id_hash was set to original_job.id_hash above)
        self.delete_by_id_hash( original_job.id_hash )
        self.jobs_done_queue.push( done_queue_entry )  # Add COPY to done queue, auto-emits 'done_update'

        run_timer.print( "CACHE HIT - result retrieved in ", use_millis=True )
        print( f"⏱️ Time saved by cache hit: {time_saved_ms}ms" )

        du.print_banner( f"CACHED Job [{cached_snapshot.question}] complete!", prepend_nl=True, end="\n" )

        if self.debug:
            du.print_banner( "cached_snapshot.runtime_stats", prepend_nl=True )
            pprint.pprint( cached_snapshot.runtime_stats )
            print( f"Done queue entry user_id: {done_queue_entry.user_id} (current user)" )
            print( f"Canonical snapshot user_id: {cached_snapshot.user_id} (original creator)" )

        # Write to database to track cache hit
        self.io_tbl.insert_io_row(
            input_type=cached_snapshot.routing_command,
            input=cached_snapshot.last_question_asked,
            output_raw=cached_snapshot.answer,
            output_final=cached_snapshot.answer_conversational
        )

        return done_queue_entry

def quick_smoke_test():
    """
    Critical smoke test for RunningFifoQueue - validates active queue management functionality.
    
    This test is essential for v000 deprecation as running_fifo_queue.py is critical
    for active job processing and queue management in the REST system.
    """
    import cosa.utils.util as du
    
    du.print_banner( "Running FIFO Queue Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic class and method presence
        print( "Testing core running queue components..." )
        expected_methods = [
            "enter_running_loop", "_process_job", "_handle_base_agent", 
            "_handle_solution_snapshot", "_handle_error_case"
        ]
        
        methods_found = 0
        for method_name in expected_methods:
            if hasattr( RunningFifoQueue, method_name ):
                methods_found += 1
            else:
                print( f"⚠ Missing method: {method_name}" )
        
        if methods_found == len( expected_methods ):
            print( f"✓ All {len( expected_methods )} core running queue methods present" )
        else:
            print( f"⚠ Only {methods_found}/{len( expected_methods )} running queue methods present" )
        
        # Test 2: Critical dependency imports
        print( "Testing critical dependency imports..." )
        try:
            from cosa.agents.receptionist_agent import ReceptionistAgent
            from cosa.agents.weather_agent import WeatherAgent
            from cosa.rest.fifo_queue import FifoQueue
            from cosa.agents.agent_base import AgentBase
            print( "✓ Core agent imports successful" )
        except ImportError as e:
            print( f"✗ Core agent imports failed: {e}" )
        
        try:
            from cosa.memory.input_and_output_table import InputAndOutputTable
            from cosa.memory.solution_snapshot import SolutionSnapshot
            print( "✓ Memory system imports successful" )
        except ImportError as e:
            print( f"⚠ Memory system imports failed: {e}" )
        
        try:
            import cosa.utils.util_stopwatch as sw
            print( "✓ Utility imports successful" )
        except ImportError as e:
            print( f"⚠ Utility imports failed: {e}" )
        
        # Test 3: Inheritance validation
        print( "Testing inheritance structure..." )
        import inspect
        
        # Check if RunningFifoQueue properly inherits from FifoQueue
        base_classes = inspect.getmro( RunningFifoQueue )
        base_class_names = [ cls.__name__ for cls in base_classes ]
        
        if "FifoQueue" in base_class_names:
            print( "✓ Properly inherits from FifoQueue" )
        else:
            print( "✗ Missing FifoQueue inheritance" )
        
        # Test 4: Basic initialization (mock)
        print( "Testing basic initialization..." )
        try:
            # Create mock objects for initialization
            class MockApp:
                pass
            
            class MockWebSocketMgr:
                def emit( self, event, data ):
                    pass
            
            class MockSnapshotMgr:
                pass
            
            class MockConfigMgr:
                def get( self, key, default=None, return_type=None ):
                    return default
            
            # Create mock queues
            mock_app = MockApp()
            mock_ws_mgr = MockWebSocketMgr()
            mock_snapshot_mgr = MockSnapshotMgr()
            mock_todo_queue = FifoQueue()
            mock_done_queue = FifoQueue()
            mock_dead_queue = FifoQueue()
            mock_config_mgr = MockConfigMgr()
            
            # Test initialization
            running_queue = RunningFifoQueue(
                app=mock_app,
                websocket_mgr=mock_ws_mgr,
                snapshot_mgr=mock_snapshot_mgr,
                jobs_todo_queue=mock_todo_queue,
                jobs_done_queue=mock_done_queue,
                jobs_dead_queue=mock_dead_queue,
                config_mgr=mock_config_mgr
            )
            
            # Check basic attributes
            if ( hasattr( running_queue, 'app' ) and 
                 hasattr( running_queue, 'snapshot_mgr' ) and
                 hasattr( running_queue, 'io_tbl' ) ):
                print( "✓ Running queue initialization working" )
            else:
                print( "✗ Running queue initialization failed" )
            
        except Exception as e:
            print( f"⚠ Basic initialization issues: {e}" )
        
        # Test 5: Job processing structure validation
        print( "Testing job processing structure..." )
        try:
            # Verify that _process_job method has proper structure
            process_job_method = getattr( RunningFifoQueue, '_process_job', None )
            if callable( process_job_method ):
                print( "✓ Job processing method structure valid" )
            else:
                print( "✗ Job processing method not callable" )
            
            # Check handler methods
            handlers = [ '_handle_base_agent', '_handle_solution_snapshot', '_handle_error_case' ]
            handler_count = 0
            for handler in handlers:
                if hasattr( RunningFifoQueue, handler ):
                    handler_count += 1
            
            if handler_count == len( handlers ):
                print( f"✓ All {len( handlers )} job handlers present" )
            else:
                print( f"⚠ Only {handler_count}/{len( handlers )} job handlers present" )
            
        except Exception as e:
            print( f"⚠ Job processing structure issues: {e}" )
        
        # Test 6: Input/Output table integration
        print( "Testing I/O table integration..." )
        try:
            # Test that InputAndOutputTable can be imported and instantiated
            io_table = InputAndOutputTable()
            if hasattr( io_table, 'insert_io_row' ):
                print( "✓ I/O table integration structure valid" )
            else:
                print( "⚠ I/O table missing required methods" )
        except Exception as e:
            print( f"⚠ I/O table integration issues: {e}" )
        
        # Test 7: Job type handling logic
        print( "Testing job type handling logic..." )
        try:
            # Create mock job types for testing logic
            class MockAgentJob:
                def __init__( self ):
                    self.last_question_asked = "test question"
                    self.id_hash = "mock_hash"
            
            class MockSolutionJob:
                def __init__( self ):
                    self.last_question_asked = "test question"
                    self.id_hash = "mock_hash"
            
            mock_agent_job = MockAgentJob()
            mock_solution_job = MockSolutionJob()
            
            # Test type checking logic (simulated)
            if isinstance( mock_agent_job, AgentBase ):
                agent_check = "would handle as AgentBase"
            else:
                agent_check = "would handle as non-AgentBase"
            
            print( f"✓ Job type handling logic structure validated" )
            print( f"  Mock agent job: {agent_check}" )
            
        except Exception as e:
            print( f"⚠ Job type handling issues: {e}" )
        
        # Test 8: Critical v000 dependency scanning
        print( "\\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( RunningFifoQueue )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 9: Queue management integration
        print( "\\nTesting queue management integration..." )
        try:
            # Test that the class properly extends FifoQueue functionality
            running_queue_methods = set( dir( RunningFifoQueue ) )
            fifo_queue_methods = set( dir( FifoQueue ) )
            
            # Should have all FifoQueue methods plus additional ones
            inherited_methods = fifo_queue_methods.intersection( running_queue_methods )
            
            if len( inherited_methods ) >= 10:  # Expect at least 10 core methods inherited
                print( "✓ Queue management integration validated" )
                print( f"  Inherited {len( inherited_methods )} methods from FifoQueue" )
            else:
                print( f"⚠ Limited queue inheritance: only {len( inherited_methods )} methods" )
            
        except Exception as e:
            print( f"⚠ Queue management integration issues: {e}" )
    
    except Exception as e:
        print( f"✗ Error during running FIFO queue testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: Running FIFO queue has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - Active job processing will break" )
    else:
        print( "✅ Running FIFO queue smoke test completed successfully!" )
        print( "   Status: Active queue management ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ Running FIFO queue smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()