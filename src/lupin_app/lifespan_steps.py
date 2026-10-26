#!/usr/bin/env python3
"""
Startup and shutdown steps that `lupin_app.main` runs from its lifespan.

Each step used to sit inline in the lifespan, where only a booted server could reach it.
A step here takes its collaborators as arguments, so a unit test can drive every branch
with doubles and no GPU, database or running app.

Imports are limited to the standard library. Heavy modules are imported inside the step
that needs them, so importing this file stays cheap.
"""
import asyncio
import sys


def print_migration_banner( migrate_result, stream=None ):
    """
    Announce on stderr that boot applied a database migration, and stay silent otherwise.

    Requires:
        - migrate_result has keys "applied", "before" and "after"
        - stream is a writable file object, or None to use sys.stderr at call time

    Ensures:
        - prints one banner naming the before and after revisions when "applied" is true
        - prints "(unstamped)" when the database had no revision before the migration
        - prints nothing and returns False when nothing was applied
        - returns True when it printed
    """
    if not migrate_result[ "applied" ]:
        return False
    print(
        f"⚠️  MIGRATION APPLIED — the database moved {migrate_result[ 'before' ] or '(unstamped)'}"
        f" -> {migrate_result[ 'after' ]}.\n"
        f"    On :7999 a file-save restarts the server and runs this migrate, so this may be a\n"
        f"    schema deploy nobody decided. If you did not intend it, that is the thing to look at.",
        file=stream if stream is not None else sys.stderr,
    )
    return True


def build_snapshot_manager_config( manager_type, config_mgr, debug=False ):
    """
    Return the factory config for the configured solution snapshot manager.

    Requires:
        - manager_type is a string
        - config_mgr has a get( key, default= ) method

    Ensures:
        - returns { "table_name": <INI value or "solution_snapshots"> } for "postgres", in any letter case
        - prints one line when debug is true

    Raises:
        - ValueError when manager_type is anything but "postgres"
    """
    if manager_type.lower() == "postgres":
        config = {
            "table_name" : config_mgr.get( "solution snapshots postgres table", default="solution_snapshots" )
        }
        if debug: print( "Using Postgres+pgvector solution snapshot manager" )
        return config
    else:
        raise ValueError(
            f"Unsupported 'solution snapshots manager type' = {manager_type!r}; "
            "the only supported value is 'postgres'"
        )


def recover_interrupted_jobs( mark_fn ):
    """
    Run the startup recovery pass over persisted jobs and report what it found.

    Requires:
        - mark_fn takes no arguments and returns a dict of counts

    Ensures:
        - prints a summary line when any job was interrupted, preserved or caught up
        - prints a "nothing found" line otherwise
        - catches any exception from mark_fn, prints a warning and returns None
        - returns the counts dict on success
    """
    try:
        counts = mark_fn()
        total_interrupted = counts.get( "running", 0 ) + counts.get( "pending_interrupted", 0 )
        preserved = counts.get( "pending_preserved", 0 )
        catchup = counts.get( "pending_catchup", 0 )
        if total_interrupted > 0 or preserved > 0 or catchup > 0:
            print( f"[CJ-PERSIST] Startup recovery: {total_interrupted} interrupted, "
                   f"{preserved} future-scheduled preserved, {catchup} downtime-missed caught up" )
        else:
            print( "[CJ-PERSIST] No interrupted or scheduled jobs found" )
        return counts
    except Exception as e:
        print( f"[WARN] CJ Flow startup recovery failed: {e}" )
        return None


def restore_jobs_at_boot( restore_fn ):
    """
    Run the boot-time job restore and keep a failure from stopping startup.

    Requires:
        - restore_fn takes no arguments

    Ensures:
        - returns True when restore_fn returns normally
        - prints a warning and returns False when restore_fn raises
    """
    try:
        restore_fn()
        return True
    except Exception as e:
        print( f"[WARN] Job restoration failed: {e}" )
        return False


def start_websocket_maintenance_tasks( config_mgr, heartbeat_loop_fn, cleanup_loop_fn, create_task_fn=asyncio.create_task ):
    """
    Start the heartbeat and cleanup loops that the INI switches on.

    Requires:
        - config_mgr has get( key, default=, return_type= )
        - heartbeat_loop_fn and cleanup_loop_fn are coroutine functions
        - create_task_fn schedules a coroutine on the running loop

    Ensures:
        - returns ( heartbeat_task, cleanup_task ) with None for each loop whose INI switch is off
        - both switches default to on
    """
    heartbeat_task = None
    cleanup_task   = None
    if config_mgr.get( "websocket heartbeat enabled", default=True, return_type="boolean" ):
        print( "[WS-HEARTBEAT] Starting heartbeat task..." )
        heartbeat_task = create_task_fn( heartbeat_loop_fn() )
        print( "[WS-HEARTBEAT] Heartbeat task started" )

    if config_mgr.get( "websocket cleanup enabled", default=True, return_type="boolean" ):
        print( "[WS-CLEANUP] Starting cleanup task..." )
        cleanup_task = create_task_fn( cleanup_loop_fn() )
        print( "[WS-CLEANUP] Cleanup task started" )
    return heartbeat_task, cleanup_task


def start_notification_sweep_task( config_mgr, sweep_loop_fn, create_task_fn=asyncio.create_task ):
    """
    Start the orphan notification sweep loop when the INI switch is on.

    Requires:
        - config_mgr has get( key, default=, return_type= )
        - sweep_loop_fn is a coroutine function

    Ensures:
        - returns the task when "notification expiry sweep enabled" is true
        - returns None when the key is false or absent, so a missing key never arms the sweeper
    """
    if config_mgr.get( "notification expiry sweep enabled", default=False, return_type="boolean" ):
        print( "[NOTIFY-SWEEP] Starting orphan sweep task..." )
        task = create_task_fn( sweep_loop_fn() )
        print( "[NOTIFY-SWEEP] Orphan sweep task started" )
        return task
    return None


def schedule_all_clear( config_mgr, commons_store, label_fn, root_fn, run_fn, startup_began, now_fn,
                        create_task_fn=asyncio.create_task ):
    """
    Schedule the post-boot all-clear broadcast, and keep any failure from stopping boot.

    Requires:
        - run_fn( boot_id=, boot_started=, startup_began= ) returns a coroutine
        - label_fn() returns the server label and root_fn() the project root that holds the per-server boot counter
        - now_fn() returns a datetime and create_task_fn schedules a coroutine

    Ensures:
        - schedules nothing when commons is disabled or commons_store is None, and returns False
        - otherwise numbers this boot from the per-server counter, creates the task and returns True
        - prints a warning to stderr and returns False when resolving the label or root, numbering or scheduling raises
    """
    if config_mgr.get( "commons enabled", default=True, return_type="boolean" ) and commons_store is not None:
        try:
            from cosa.rest.managed_bounce_broadcast import next_boot_id, boot_counter_path
            boot_id = next_boot_id( boot_counter_path( root_fn(), label_fn() ) )
            create_task_fn(
                run_fn(
                    boot_id       = boot_id,
                    boot_started  = now_fn().isoformat( timespec="seconds" ),
                    startup_began = startup_began,
                )
            )
            return True
        except Exception as e:
            print( f"[managed-bounce] WARN: could not schedule all-clear: {e}", file=sys.stderr )
    return False


def print_all_clear_receipt( gate, boot_id, recipients, curve, stream=None ):
    """
    Print the fire-time receipt for the all-clear broadcast, naming anyone who missed it.

    Requires:
        - gate has "reason", "elapsed", "missing", "roster_size"
        - curve is the reconnect curve already joined into a string

    Ensures:
        - prints one line to stream, or stderr when stream is None
        - the line names the sessions that had not rejoined, when there are any
        - the line says the roster was empty when it was, and that the gate cannot tell why
        - the wording differs for a deadline fire and a roster-covered fire
    """
    missed = gate[ "missing" ]
    loss   = (
        f" {len( missed )} session(s) had NOT rejoined and got NO all-clear "
        f"(accepted loss, no re-fire): {missed}."
        if missed
        else (
            f" all {gate[ 'roster_size' ]} session(s) on the roster had a live socket."
            if gate[ "roster_size" ]
            else (
                " ⚠️ the roster was EMPTY — either nobody was expected back, or the bridge "
                "directory could not be read. This fire reached nobody and the gate cannot "
                "tell those two apart."
            )
        )
    )
    out = stream if stream is not None else sys.stderr
    if gate[ "reason" ] == "deadline":
        print(
            f"[managed-bounce] ⚠️ all-clear FIRED on DEADLINE EXPIRY (boot #{boot_id}): reached "
            f"{recipients} recipient(s) after {gate[ 'elapsed' ]:.1f}s; reconnect curve {curve}."
            f"{loss}",
            file=out,
        )
    else:
        print(
            f"[managed-bounce] all-clear FIRED (boot #{boot_id}): roster COVERED after "
            f"{gate[ 'elapsed' ]:.1f}s; reconnect curve {curve}; reached {recipients} recipient(s)."
            f"{loss}",
            file=out,
        )


def record_clean_shutdown( record_fn ):
    """
    Stamp the last-available marker at shutdown, and keep a failure from stopping teardown.

    Requires:
        - record_fn takes no arguments

    Ensures:
        - prints a confirmation and returns True when record_fn returns
        - prints a warning and returns False when it raises
    """
    try:
        record_fn()
        print( "[CJ-PERSIST] Recorded clean-shutdown last-available marker" )
        return True
    except Exception as e:
        print( f"[WARN] shutdown last-available marker failed: {e}" )
        return False


async def cancel_background_task( task, tag, cancelling, cancelled, failed ):
    """
    Cancel a background task and wait for it, reporting how it ended.

    Requires:
        - task is an asyncio task, or None when the task was never started
        - tag, cancelling, cancelled and failed are the text of the log lines

    Ensures:
        - does nothing when task is None
        - prints "[tag] Cancelling <cancelling>...", cancels, then awaits the task
        - prints the cancelled line when the task ends by cancellation
        - prints nothing further when the task returns normally
        - prints the failed line with the exception when the task ends with any other error
        - never raises
    """
    if not task:
        return
    print( f"[{tag}] Cancelling {cancelling}..." )
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print( f"[{tag}] {cancelled} cancelled successfully" )
    except Exception as e:
        print( f"[{tag}] Error during {failed} shutdown: {e}" )


def shutdown_fcm_wake( service ):
    """
    Cancel the pending trailing wakes of the FCM wake service, when there is one.

    Requires:
        - service is None or an object with shutdown()

    Ensures:
        - does nothing when service is None
        - prints a confirmation after shutdown() returns
        - prints an error and continues when shutdown() raises
    """
    if service is None:
        return
    try:
        service.shutdown()
        print( "[FCM-WAKE] Pending trailing wakes cancelled" )
    except Exception as e:
        print( f"[FCM-WAKE] Error during wake-service shutdown (continuing): {e}" )


def drain_agentic_pool( run_queue, timeout=30.0 ):
    """
    Drain the agentic worker pool before the consumer thread stops.

    Requires:
        - run_queue is None or any object

    Ensures:
        - does nothing when run_queue is None or has no shutdown_pool method
        - otherwise waits up to timeout seconds for in-flight workers
        - prints an error and continues when the drain raises
    """
    if run_queue is not None and hasattr( run_queue, "shutdown_pool" ):
        try:
            print( "[AGENTIC-POOL] Draining agentic pool before consumer stop..." )
            run_queue.shutdown_pool( wait=True, timeout=timeout )
        except Exception as e:
            print( f"[AGENTIC-POOL] Error during pool drain (continuing): {e}" )


def stop_consumer_thread( thread, todo_queue, join_timeout=5.0 ):
    """
    Tell the todo-producer-run-consumer thread to stop and wait for it.

    Requires:
        - thread is None or a started thread
        - todo_queue has a condition and a consumer_running flag

    Ensures:
        - does nothing when thread is None
        - clears consumer_running and wakes the thread under the condition
        - prints a warning when the thread is still alive after join_timeout
        - prints a success line otherwise
    """
    if not thread:
        return
    print( "[CONSUMER] Stopping todo-producer-run-consumer thread..." )
    with todo_queue.condition:
        todo_queue.consumer_running = False
        todo_queue.condition.notify()
    thread.join( timeout=join_timeout )
    if thread.is_alive():
        print( "[CONSUMER] Warning: Consumer thread did not exit cleanly" )
    else:
        print( "[CONSUMER] Todo-producer-run-consumer thread stopped successfully" )


async def cancel_peer_watchers( cancel_fn ):
    """
    Cancel the active peer-queue watchers at shutdown.

    Requires:
        - cancel_fn is an async function that takes no arguments

    Ensures:
        - prints before and after lines around the call
        - prints an error and continues when cancel_fn raises
    """
    try:
        print( "[PEER-WATCH] Cancelling active peer-queue watchers..." )
        await cancel_fn()
        print( "[PEER-WATCH] Peer-queue watchers cancelled" )
    except Exception as e:
        print( f"[PEER-WATCH] Error cancelling watchers: {e}" )


def stop_commons_watcher( watcher, name, failure_text, join_timeout=3.0 ):
    """
    Stop one commons watcher daemon, when there is one.

    Requires:
        - watcher is None or an object with stop( join_timeout= )
        - name is the class name used in the log lines
        - failure_text is the text printed before the exception on failure

    Ensures:
        - does nothing when watcher is None
        - prints a stopping line, calls stop, then prints a stopped line
        - prints "[COMMONS] <failure_text>: <error>" and continues when stop raises
    """
    if watcher is None:
        return
    try:
        print( f"[COMMONS] Stopping {name} daemon..." )
        watcher.stop( join_timeout=join_timeout )
        print( f"[COMMONS] {name} stopped" )
    except Exception as e:
        print( f"[COMMONS] {failure_text}: {e}" )
