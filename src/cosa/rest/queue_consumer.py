"""
CJ Flow background consumer thread for producer-consumer queue pattern.

This module implements the consumer side of the TodoFifoQueue -> RunningFifoQueue
producer-consumer pattern, replacing the old polling-based approach with
event-driven processing using threading.Condition.
"""

import threading
import time
from typing import Any
from datetime import datetime
import cosa.utils.util as du
from cosa.rest.job_state import JobState
from cosa.rest.queue_util import emit_job_state_transition


def start_todo_producer_run_consumer_thread( todo_queue: Any, running_queue: Any ) -> threading.Thread:
    """
    Start the background consumer thread for producer-consumer pattern.
    
    Requires:
        - todo_queue is a TodoFifoQueue with condition variable support
        - running_queue is a RunningFifoQueue with _process_job method
        
    Ensures:
        - Consumer thread runs as daemon (dies with main process)
        - Uses condition.wait() instead of polling for efficiency
        - Gracefully handles shutdown via consumer_running flag
        
    Args:
        todo_queue: TodoFifoQueue instance (producer)
        running_queue: RunningFifoQueue instance (consumer processor)
        
    Returns:
        threading.Thread: The started consumer thread
        
    Raises:
        None (exceptions handled within thread)
    """
    
    def consumer_worker():
        """Main consumer worker function that processes jobs with timed execution support."""
        print( "[CONSUMER] Starting queue consumer thread..." )
        todo_queue.consumer_running = True

        # Idle-wake interval: bound otherwise-indefinite condition.wait()
        # calls so the heartbeat refreshes even when the queue is empty.
        # Backlog item 2 (2026-04-29): without this, the consumer thread
        # blocks in wait() indefinitely after a test_suite job completes,
        # heartbeat goes stale, and /api/queue/pool-status flags
        # consumer_stalled=true even though the consumer is healthy-but-idle.
        # Derived from the running_queue's stall threshold so it's self-
        # consistent with stall detection (4 ticks per stall window).
        try:
            stall_threshold_secs = int( getattr(
                running_queue, "_consumer_stall_threshold_seconds", 120
            ) )
        except ( TypeError, ValueError ):
            # Mock running_queue in unit tests, or a non-numeric override.
            stall_threshold_secs = 120
        idle_wake_interval_secs = max( 5, stall_threshold_secs // 4 )

        # Option (a) true-monopoly (bug 30398595): poll interval for the Gate-A
        # pool-drain wait AND the Gate-B intake-hold wait. Short enough to resume
        # intake promptly when a monopolize job clears; the per-iteration
        # heartbeat keeps stall detection healthy either way.
        monopolize_poll_secs = 1.0

        def _tick_heartbeat() -> None:
            """Refresh the consumer heartbeat. Tolerates Mock running_queue."""
            try:
                running_queue.last_consumer_heartbeat_at = datetime.now()
            except AttributeError:
                # running_queue may be a Mock in unit tests, or an older
                # implementation without the attribute — never fatal.
                pass

        while todo_queue.consumer_running:
            # WG-8 (2026-04-28): heartbeat at top of loop. /api/queue/pool-status
            # reports seconds_since_heartbeat so stall detection can flag a
            # frozen consumer (suspenders to the ghost-job sweeper's belt).
            _tick_heartbeat()

            try:
                # Wait for eligible jobs using condition variable + dynamic timeout
                with todo_queue.condition:
                    job = None
                    while todo_queue.consumer_running:
                        # Per-iteration heartbeat: even while waiting for a
                        # job, every wait() return ticks this. Ensures a
                        # bounded idle wait keeps the heartbeat fresh.
                        _tick_heartbeat()

                        # Option (a) true-monopoly (bug 30398595 + 3a14292b) — Gate B:
                        # while a monopolize job holds the pool, defer FOREIGN intake
                        # but ADMIT the monopolizer's OWN lineage children — they are
                        # part of its exclusive window, not contaminants (without this
                        # the sweep's pytest-spawned children starve for the whole run:
                        # 1916 "deferring all intake" receipts on ts-ad4670ec). Foreign
                        # jobs stay FIFO-intact so the deferred head dispatches first
                        # once the hold clears. Bounded wait keeps the heartbeat fresh
                        # (no busy-loop). The hold check short-circuits first (cheap)
                        # then re-reads the master kill-switch fresh so an INI flip lifts
                        # the hold live.
                        if running_queue._monopolize_active is not None and running_queue._is_monopolize_enabled():
                            parent = running_queue._monopolize_active
                            def _is_admissible_child( j ):
                                # A child is admissible iff it was spawned BY the active
                                # monopolizer (explicit lineage, NEVER job_type sniffing)
                                # AND does not itself monopolize (a nested monopolizer
                                # needs its own exclusive window → defer it like a foreign
                                # job). getattr with None/False defaults: the todo queue is
                                # heterogeneous (AgentBase / SolutionSnapshot never carry
                                # the AgenticJobBase lineage field) — this is the legitimate
                                # "attribute absent on this class" guard, not defensive
                                # fishing for an attribute that ought to exist.
                                return ( getattr( j, "spawned_by_id_hash", None ) == parent
                                         and not getattr( j, "monopolize", False ) )
                            job = todo_queue.pop_next_eligible( predicate=_is_admissible_child )
                            if job is not None:
                                break  # admitted a lineage child — dispatch it normally
                            if todo_queue.debug: print( "[CONSUMER] Monopoly hold active — deferring FOREIGN intake (lineage children pass)" )
                            todo_queue.condition.wait( timeout=monopolize_poll_secs )
                            continue

                        now = datetime.now()
                        job = todo_queue.pop_next_eligible( now )

                        if job is not None:
                            break  # Got an eligible job

                        if todo_queue.is_empty():
                            # Queue empty — wait, but with a bounded timeout so
                            # the heartbeat refreshes periodically. Without the
                            # bound, indefinite wait() blocks the heartbeat
                            # update path and stall detection mis-flags a
                            # healthy idle consumer.
                            if todo_queue.debug: print( f"[CONSUMER] Queue empty, waiting up to {idle_wake_interval_secs}s for jobs..." )
                            todo_queue.condition.wait( timeout=idle_wake_interval_secs )
                        else:
                            # Queue has items but none are eligible yet (all paused or future-scheduled)
                            earliest = todo_queue.earliest_scheduled_at()
                            if earliest is not None:
                                # Cap at idle_wake_interval so the heartbeat
                                # ticks at least every wake-interval seconds
                                # even if the next scheduled job is far away.
                                until_scheduled = max( 0.1, ( earliest - datetime.now() ).total_seconds() )
                                timeout         = min( until_scheduled, idle_wake_interval_secs )
                                if todo_queue.debug: print( f"[CONSUMER] Sleeping {timeout:.1f}s (next scheduled in {until_scheduled:.1f}s)" )
                                todo_queue.condition.wait( timeout=timeout )
                            else:
                                # All jobs are paused (no scheduled times) —
                                # wait for a resume/push notify, but bounded
                                # so the heartbeat keeps ticking.
                                if todo_queue.debug: print( f"[CONSUMER] All jobs paused, waiting up to {idle_wake_interval_secs}s for resume..." )
                                todo_queue.condition.wait( timeout=idle_wake_interval_secs )

                    if not todo_queue.consumer_running:
                        break

                if job:  # pragma: no branch - reached only after the inner while breaks WITH a job in hand: either the normal eligible-job break or the Gate-B lineage-child admit break (bug 3a14292b) — BOTH assign job a non-None value. The only other inner-loop exit is consumer_running going False, caught by the `if not ...: break` immediately above. So job is always truthy here; the falsy arc back to the outer loop is unreachable.
                    # Option (a) true-monopoly (bug 30398595) — Gate A: before a
                    # monopolize job takes the pool, drain it of foreign (non-test)
                    # inflight writers so the sweep gets exclusive use of the shared
                    # test DB (bug 30398595 wired the formerly-inert monopolize flag
                    # into this enforced two-gate monopoly — it is no longer a no-op).
                    # On timeout the sweep is dead-lettered — a contaminated gate must
                    # NEVER run. Non-monopolize jobs skip the gate. The drain classifier
                    # exempts the sweep's own lineage children (bug 3a14292b).
                    monopolize_drain_offenders = None
                    drain_timeout              = None
                    if getattr( job, 'monopolize', False ) and running_queue._is_monopolize_enabled():
                        drain_timeout = running_queue._monopolize_drain_timeout_seconds
                        monopolize_drain_offenders = running_queue.await_monopolize_pool_drain(
                            job,
                            timeout_seconds = drain_timeout,
                            poll_seconds    = monopolize_poll_secs,
                            heartbeat_fn    = _tick_heartbeat,
                        )

                    if todo_queue.debug:
                        print( f"[CONSUMER] Processing job: {job.last_question_asked}" )

                    # Emit job state transition (todo -> run) before moving to running queue
                    # Phase 2: Direct attribute access - Protocol guarantees these exist
                    job_id = job.id_hash
                    if hasattr( running_queue, 'websocket_mgr' ):
                        user_id = job.user_id
                        # Phase 6.1: Include card-rendering metadata for client-side card creation
                        metadata = {
                            'question_text' : job.last_question_asked,
                            'agent_type'    : job.job_type,
                            'timestamp'     : job.created_date,
                            'user_email'    : job.user_email,
                            'started_at'    : du.get_current_datetime_iso()
                        }
                        emit_job_state_transition( running_queue.websocket_mgr, job_id, JobState.QUEUED, JobState.RUNNING, user_id, metadata )

                    # Move to running queue
                    running_queue.push( job )  # Auto-emits 'run_update'

                    if monopolize_drain_offenders:
                        # Gate A timeout: fail loud. Dead-letter the sweep with a
                        # reason that NAMES the offenders (classifier output verbatim)
                        # — do not run onto a contaminated DB (option (c) is the belt).
                        detail = ", ".join( f"{o[ 'id_hash' ]}({o[ 'job_type' ]})" for o in monopolize_drain_offenders )
                        cause  = ( f"Monopolize drain TIMEOUT after {drain_timeout}s (bug 30398595): foreign "
                                   f"agentic writer(s) still inflight on the shared test DB — contaminated gate "
                                   f"refused, sweep dead-lettered. Offenders: {detail}." )
                        print( f"[CONSUMER] {cause}" )
                        running_queue._transition_to_dead( job, cause )
                    # Process the job (new method we'll add to RunningFifoQueue)
                    elif hasattr( running_queue, '_process_job' ):
                        running_queue._process_job( job )
                    else:
                        print( "[CONSUMER] Warning: RunningFifoQueue missing _process_job method" )
                        # Fallback: just leave it in running queue for now
                        time.sleep( 0.1 )
                    
            except Exception as e:
                print( f"[CONSUMER] Error in consumer thread: {e}" )
                if todo_queue.debug:
                    import traceback
                    traceback.print_exc()
                # Continue running even after errors
                time.sleep( 1.0 )
        
        print( "[CONSUMER] Consumer thread shutting down..." )
    
    # Start as daemon thread (dies when main process exits)
    consumer_thread = threading.Thread( target=consumer_worker, daemon=True, name="TodoConsumerThread" )
    consumer_thread.start()
    
    print( f"[CONSUMER] Consumer thread started: {consumer_thread.name}" )
    return consumer_thread


def quick_smoke_test():
    """Quick smoke test for consumer thread functionality"""
    from unittest.mock import Mock
    import time
    
    du.print_banner( "Queue Consumer Thread Smoke Test" )
    
    try:
        # Create mock queues
        mock_todo_queue = Mock()
        mock_todo_queue.debug = True
        mock_todo_queue.consumer_running = True  # Start as True
        mock_todo_queue.condition = threading.Condition()
        mock_todo_queue.is_empty.return_value = True
        mock_todo_queue.pop_next_eligible.return_value = None
        mock_todo_queue.earliest_scheduled_at.return_value = None
        
        mock_running_queue = Mock()
        
        print( "✓ Testing consumer thread startup..." )
        
        # Start thread
        thread = start_todo_producer_run_consumer_thread( mock_todo_queue, mock_running_queue )
        
        # Give thread time to start
        time.sleep( 0.1 )
        assert thread.is_alive() == True, "Thread should be running"
        
        # Now stop it
        with mock_todo_queue.condition:
            mock_todo_queue.consumer_running = False
            mock_todo_queue.condition.notify()
        
        # Give thread time to exit
        thread.join( timeout=1.0 )
        assert thread.is_alive() == False, "Thread should have exited after consumer_running=False"
        print( "✓ Consumer thread lifecycle working!" )
        
        print( "✓ Consumer thread smoke test passed!" )
        
    except Exception as e:
        print( f"✗ Consumer thread smoke test failed: {e}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()