"""
Unit tests for the shutdown steps in `lupin_app/lifespan_steps.py`.

Each step takes its collaborators as arguments, so every branch runs here with a double and
no server. Every assertion reads the line the step prints, because the printed line is the
only record an operator has of how a shutdown went.
"""

import asyncio
import threading
import types

import pytest

from lupin_app import lifespan_steps as steps


# ── record_clean_shutdown ────────────────────────────────────────────────────

def test_record_clean_shutdown_reports_success( capsys ):
    """A recorder that returns is called once and confirmed."""
    calls = []
    assert steps.record_clean_shutdown( lambda: calls.append( 1 ) ) is True
    assert calls == [ 1 ]
    assert capsys.readouterr().out == "[CJ-PERSIST] Recorded clean-shutdown last-available marker\n"


def test_record_clean_shutdown_swallows_a_failure( capsys ):
    """A recorder that raises is reported as a warning and does not stop teardown."""
    def boom(): raise OSError( "disk gone" )
    assert steps.record_clean_shutdown( boom ) is False
    out = capsys.readouterr().out
    assert out == "[WARN] shutdown last-available marker failed: disk gone\n"
    assert "Recorded" not in out


# ── cancel_background_task ───────────────────────────────────────────────────

_TEXT = ( "CLOCK", "background clock task", "Background clock task", "clock task" )


def test_cancel_background_task_ignores_a_task_that_never_started( capsys ):
    """None means the INI switch was off, so there is nothing to print."""
    asyncio.run( steps.cancel_background_task( None, *_TEXT ) )
    assert capsys.readouterr().out == ""


def test_cancel_background_task_reports_cancellation( capsys ):
    """A task cancelled before its first step is reported as cancelled."""
    async def scenario():
        async def forever():
            await asyncio.sleep( 3600 )
        task = asyncio.create_task( forever() )
        await steps.cancel_background_task( task, *_TEXT )
        return task
    task = asyncio.run( scenario() )
    assert task.cancelled()
    assert capsys.readouterr().out == (
        "[CLOCK] Cancelling background clock task...\n"
        "[CLOCK] Background clock task cancelled successfully\n"
    )


def test_cancel_background_task_is_quiet_when_the_task_swallows_the_cancel( capsys ):
    """A task that swallows the cancel, as the real loops do, prints only the first line."""
    async def scenario():
        started = asyncio.Event()
        async def loop_that_breaks():
            started.set()
            try:
                await asyncio.sleep( 3600 )
            except asyncio.CancelledError:
                return
        task = asyncio.create_task( loop_that_breaks() )
        await started.wait()
        await steps.cancel_background_task( task, *_TEXT )
    asyncio.run( scenario() )
    assert capsys.readouterr().out == "[CLOCK] Cancelling background clock task...\n"


def test_cancel_background_task_reports_a_task_that_fails_on_cancel( capsys ):
    """A task that raises while being cancelled is reported and does not propagate."""
    async def scenario():
        started = asyncio.Event()
        async def loop_that_explodes():
            started.set()
            try:
                await asyncio.sleep( 3600 )
            except asyncio.CancelledError:
                raise RuntimeError( "cleanup blew up" )
        task = asyncio.create_task( loop_that_explodes() )
        await started.wait()
        await steps.cancel_background_task( task, *_TEXT )
    asyncio.run( scenario() )
    assert capsys.readouterr().out == (
        "[CLOCK] Cancelling background clock task...\n"
        "[CLOCK] Error during clock task shutdown: cleanup blew up\n"
    )


# ── shutdown_fcm_wake ────────────────────────────────────────────────────────

def test_shutdown_fcm_wake_without_a_service_prints_nothing( capsys ):
    """No Firebase credentials means no service object."""
    steps.shutdown_fcm_wake( None )
    assert capsys.readouterr().out == ""


def test_shutdown_fcm_wake_stops_the_service( capsys ):
    """The service is shut down once and confirmed."""
    service = types.SimpleNamespace( calls=0 )
    service.shutdown = lambda: setattr( service, "calls", service.calls + 1 )
    steps.shutdown_fcm_wake( service )
    assert service.calls == 1
    assert capsys.readouterr().out == "[FCM-WAKE] Pending trailing wakes cancelled\n"


def test_shutdown_fcm_wake_continues_after_a_failure( capsys ):
    """A failing shutdown is reported and the caller carries on."""
    def boom(): raise RuntimeError( "timer stuck" )
    steps.shutdown_fcm_wake( types.SimpleNamespace( shutdown=boom ) )
    assert capsys.readouterr().out == "[FCM-WAKE] Error during wake-service shutdown (continuing): timer stuck\n"


# ── drain_agentic_pool ───────────────────────────────────────────────────────

def test_drain_agentic_pool_skips_a_queue_without_a_pool( capsys ):
    """A queue with no shutdown_pool method, and a missing queue, are both left alone."""
    steps.drain_agentic_pool( None )
    steps.drain_agentic_pool( object() )
    assert capsys.readouterr().out == ""


def test_drain_agentic_pool_waits_for_in_flight_workers( capsys ):
    """The pool is drained with wait=True and the 30 second default budget."""
    seen = {}
    queue = types.SimpleNamespace( shutdown_pool=lambda **kw: seen.update( kw ) )
    steps.drain_agentic_pool( queue )
    assert seen == { "wait": True, "timeout": 30.0 }
    assert capsys.readouterr().out == "[AGENTIC-POOL] Draining agentic pool before consumer stop...\n"


def test_drain_agentic_pool_continues_after_a_failure( capsys ):
    """A drain that raises is reported and shutdown goes on."""
    def boom( **kw ): raise TimeoutError( "pool stuck" )
    steps.drain_agentic_pool( types.SimpleNamespace( shutdown_pool=boom ) )
    out = capsys.readouterr().out
    assert out.endswith( "[AGENTIC-POOL] Error during pool drain (continuing): pool stuck\n" )


# ── stop_consumer_thread ─────────────────────────────────────────────────────

def _todo_queue():
    """A queue double with a real condition, so the `with` block and notify() are exercised."""
    return types.SimpleNamespace( condition=threading.Condition(), consumer_running=True )


def test_stop_consumer_thread_without_a_thread_prints_nothing( capsys ):
    """A server that never started a consumer has nothing to stop."""
    queue = _todo_queue()
    steps.stop_consumer_thread( None, queue )
    assert queue.consumer_running is True
    assert capsys.readouterr().out == ""


def test_stop_consumer_thread_stops_a_thread_that_exits( capsys ):
    """The flag is cleared, the thread is woken and joined, and success is reported."""
    queue  = _todo_queue()
    joined = {}
    thread = types.SimpleNamespace( join=lambda timeout: joined.update( timeout=timeout ), is_alive=lambda: False )
    steps.stop_consumer_thread( thread, queue )
    assert queue.consumer_running is False
    assert joined == { "timeout": 5.0 }
    assert capsys.readouterr().out == (
        "[CONSUMER] Stopping todo-producer-run-consumer thread...\n"
        "[CONSUMER] Todo-producer-run-consumer thread stopped successfully\n"
    )


def test_stop_consumer_thread_wakes_the_consumer_while_holding_the_condition():
    """The consumer is woken once, under the lock, after the flag is cleared."""
    queue  = _todo_queue()
    seen   = []
    real   = queue.condition.notify
    def spy_notify():
        seen.append( ( queue.consumer_running, queue.condition._is_owned() ) )
        real()
    queue.condition.notify = spy_notify
    thread = types.SimpleNamespace( join=lambda timeout: None, is_alive=lambda: False )
    steps.stop_consumer_thread( thread, queue )
    assert seen == [ ( False, True ) ]


def test_stop_consumer_thread_warns_about_a_thread_that_will_not_exit( capsys ):
    """A thread still alive after the join gets a warning and no success line."""
    queue  = _todo_queue()
    thread = types.SimpleNamespace( join=lambda timeout: None, is_alive=lambda: True )
    steps.stop_consumer_thread( thread, queue )
    out = capsys.readouterr().out
    assert "[CONSUMER] Warning: Consumer thread did not exit cleanly\n" in out
    assert "stopped successfully" not in out


# ── cancel_peer_watchers ─────────────────────────────────────────────────────

def test_cancel_peer_watchers_brackets_the_call( capsys ):
    """The cancel function is awaited between the two lines."""
    order = []
    async def cancel(): order.append( "cancel" )
    asyncio.run( steps.cancel_peer_watchers( cancel ) )
    assert order == [ "cancel" ]
    assert capsys.readouterr().out == (
        "[PEER-WATCH] Cancelling active peer-queue watchers...\n"
        "[PEER-WATCH] Peer-queue watchers cancelled\n"
    )


def test_cancel_peer_watchers_continues_after_a_failure( capsys ):
    """A failing cancel is reported and the closing line is not printed."""
    async def cancel(): raise RuntimeError( "no watchers" )
    asyncio.run( steps.cancel_peer_watchers( cancel ) )
    out = capsys.readouterr().out
    assert out.endswith( "[PEER-WATCH] Error cancelling watchers: no watchers\n" )
    assert "watchers cancelled" not in out


# ── stop_commons_watcher ─────────────────────────────────────────────────────

def test_stop_commons_watcher_without_a_watcher_prints_nothing( capsys ):
    """Commons disabled, or the traffic switch off, leaves the watcher None."""
    steps.stop_commons_watcher( None, "CommonsAckWatcher", "Error stopping watcher" )
    assert capsys.readouterr().out == ""


def test_stop_commons_watcher_stops_with_the_join_budget( capsys ):
    """The watcher is stopped with a 3 second join and named in both lines."""
    seen    = {}
    watcher = types.SimpleNamespace( stop=lambda join_timeout: seen.update( join_timeout=join_timeout ) )
    steps.stop_commons_watcher( watcher, "CommonsAckWatcher", "Error stopping watcher" )
    assert seen == { "join_timeout": 3.0 }
    assert capsys.readouterr().out == (
        "[COMMONS] Stopping CommonsAckWatcher daemon...\n"
        "[COMMONS] CommonsAckWatcher stopped\n"
    )


def test_stop_commons_watcher_reports_a_failure_with_the_caller_text( capsys ):
    """The failure line carries the caller's own wording for each watcher."""
    def boom( join_timeout ): raise RuntimeError( "thread wedged" )
    steps.stop_commons_watcher( types.SimpleNamespace( stop=boom ), "CommonsActivityWatcher", "WARN — CommonsActivityWatcher shutdown failed" )
    out = capsys.readouterr().out
    assert out.endswith( "[COMMONS] WARN — CommonsActivityWatcher shutdown failed: thread wedged\n" )
    assert "CommonsActivityWatcher stopped" not in out
