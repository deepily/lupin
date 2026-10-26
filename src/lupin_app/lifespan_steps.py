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
