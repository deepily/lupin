"""
Event-loop starvation regression tests (lever B, surgical pass 2 — 2026-06-12).

Reproduces the :7999 HTTP-starvation disease at unit scale: a hot handler whose
blocking work runs ON the event loop starves every concurrent request (the
FM-7/11/15/18 black-hole; /health 10s-timeouts during the 2026-06-11 wedges).

Each probe injects an artificially slow blocking dependency into a hot handler,
runs that request while a 10ms-cadence monitor measures event-loop lag, and
asserts the loop never stalled. On the pre-fix code (blocking call inline in
the async handler) the loop freezes for the dependency's full duration and the
monitor records a ~BLOCK_SECONDS lag spike; with the asyncio.to_thread offload
the loop keeps ticking at millisecond lag.
"""

import asyncio
import time
import uuid as uuid_module

import pytest
import httpx
from unittest.mock import Mock, MagicMock, patch
from fastapi import FastAPI

# Bootstrap imports
import sys
import os

lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root:
    src_path = os.path.join( lupin_root, 'src' )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

from cosa.rest.routers.notifications import (
    router,
    get_notification_queue,
    get_websocket_manager
)
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest import user_service

# How long the injected blocking dependency sleeps, and the worst single
# event-loop stall we tolerate while it runs. A handler that blocks the loop
# stalls it for ~BLOCK_SECONDS in one tick; a properly offloaded handler
# leaves the loop ticking at millisecond lag. (Measured discrimination on
# this probe: pre-fix 0.791s max lag, post-fix 0.003s.)
BLOCK_SECONDS   = 0.8
LAG_MAX_SECONDS = 0.4

USER_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _warm_main_module_import():
    """
    Pre-import lupin_app.main so the probe measures the handler, not the import.

    notify_user does `import lupin_app.main` inline (DIAG block) and the
    cross-tree eviction fixture in src/conftest.py removes lupin_app.main from
    sys.modules after EVERY test — so without this warm-up, the first request
    in each test re-imports the whole app (~2.5s) ON the loop and that
    test-env artifact dominates the lag signal. A live server always has the
    module imported; the production stall being regression-tested is the
    blocking DB/embedding work, not module import cost.

    Ensures:
        - lupin_app.main is present in sys.modules before the probe window
    """
    import lupin_app.main   # noqa: F401


def _build_app( ws_manager, notification_queue ):
    """
    Build a minimal FastAPI app: notifications router + a trivial /ping.

    Requires:
        - ws_manager and notification_queue are mock instances

    Ensures:
        - returns an app with auth/queue/ws dependencies overridden
        - /ping does no I/O — used as a post-run sanity check that the app
          still answers
    """
    app = FastAPI()
    app.include_router( router )

    @app.get( "/ping" )
    async def ping():
        return { "status": "ok" }

    app.dependency_overrides[ require_api_key_or_jwt ]  = lambda: "service_account_123"
    app.dependency_overrides[ get_websocket_manager ]   = lambda: ws_manager
    app.dependency_overrides[ get_notification_queue ]  = lambda: notification_queue
    return app


def _online_ws_manager():
    """
    Mock WebSocketManager presenting one connected browser session.

    Ensures:
        - is_user_connected → True so notify takes the online fast path
    """
    ws = Mock()
    ws.is_user_connected.return_value          = True
    ws.get_user_connection_count.return_value  = 1
    ws.user_sessions                           = { USER_UUID: [ "session-1" ] }
    ws.active_connections                      = { "session-1": Mock() }
    ws.user_to_email                           = { USER_UUID: "test@example.com" }
    return ws


def _mock_db_patches():
    """
    Patch get_db + NotificationRepository inside the notifications router module.

    Ensures:
        - returns ( get_db_patch, repo_patch ) context managers; the repo's
          create_notification returns a row with a stable UUID
    """
    class MockDbContextManager:
        def __enter__( self ):
            return MagicMock()
        def __exit__( self, *args ):
            pass

    mock_notification    = MagicMock()
    mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

    get_db_patch = patch( 'cosa.rest.routers.notifications.get_db', return_value=MockDbContextManager() )
    repo_patch   = patch( 'cosa.rest.routers.notifications.NotificationRepository' )
    return get_db_patch, repo_patch, mock_notification


async def _measure_loop_lag_during( app, slow_request_coro ):
    """
    Run the slow request while a 10ms-cadence monitor measures event-loop lag
    (sleep overshoot); return the WORST single lag observed.

    Loop lag is the honest starvation signal. Request-latency probes false-pass
    here in two distinct ways (both observed while developing this test against
    the pre-fix code): a one-shot concurrent ping races the slow handler and
    completes before its blocking section starts, and a ping HAMMER absorbs the
    block inside its own `await asyncio.sleep()` rather than inside a timed
    request. The lag monitor is phase-independent: ANY tick of the loop delayed
    by a blocking handler shows up as overshoot on the sleep that spans it
    (measured: pre-fix 0.791s, post-fix 0.003s on this exact probe).

    Requires:
        - slow_request_coro is a coroutine factory taking the shared AsyncClient

    Ensures:
        - the monitor runs from before the slow request starts until after it
          completes; a final /ping sanity-checks the app still answers
        - returns ( max_lag_seconds, slow_response )
    """
    transport = httpx.ASGITransport( app=app )
    async with httpx.AsyncClient( transport=transport, base_url="http://testserver" ) as client:
        stop_event = asyncio.Event()
        lags       = []

        async def _lag_monitor():
            last = time.monotonic()
            while not stop_event.is_set():
                await asyncio.sleep( 0.01 )
                now = time.monotonic()
                lags.append( now - last - 0.01 )
                last = now

        monitor_task = asyncio.create_task( _lag_monitor() )
        await asyncio.sleep( 0.03 )   # warm-up: the monitor is ticking before the slow request begins

        slow_response = await slow_request_coro( client )

        stop_event.set()
        await monitor_task

        ping_response = await client.get( "/ping" )
        assert ping_response.status_code == 200
        assert lags, "lag monitor recorded no samples — probe harness broken"
        print( f"\n[PROBE] samples={len( lags )} max_lag={max( lags ):.3f}s" )
        return max( lags ), slow_response


class TestNotifyPathDoesNotStarveLoop:
    """POST /api/notify with a slow DB user-lookup must not stall the event loop."""

    @pytest.mark.asyncio
    async def test_slow_user_lookup_does_not_stall_loop( self ):
        """A 0.8s-blocking get_user_by_email leaves the loop ticking (B1 offload)."""
        _warm_main_module_import()
        ws_manager         = _online_ws_manager()
        notification_queue = Mock()
        notification_queue.push_notification.return_value = MagicMock()

        app = _build_app( ws_manager, notification_queue )

        def slow_get_user_by_email( email ):
            time.sleep( BLOCK_SECONDS )
            return { "id": USER_UUID, "email": email }

        get_db_patch, repo_patch, mock_notification = _mock_db_patches()

        original = user_service.get_user_by_email
        user_service.get_user_by_email = slow_get_user_by_email
        try:
            with get_db_patch, repo_patch as MockRepo:
                MockRepo.return_value.create_notification.return_value = mock_notification

                async def fire_notify( client ):
                    return await client.post(
                        "/api/notify",
                        params  = {
                            "message"     : "starvation probe",
                            "type"        : "task",
                            "priority"    : "medium",
                            "target_user" : "test@example.com"
                        },
                        headers = { "X-API-Key": "probe_key" }
                    )

                max_lag_seconds, notify_response = await _measure_loop_lag_during( app, fire_notify )

                assert notify_response.status_code == 200
                assert notify_response.json()[ "status" ] == "queued"
                assert max_lag_seconds < LAG_MAX_SECONDS, (
                    f"event loop stalled {max_lag_seconds:.3f}s while notify's DB lookup was in flight — "
                    f"blocking I/O is back ON the loop (FM-7 starvation regression)"
                )
        finally:
            user_service.get_user_by_email = original


class TestMarkPlayedPathDoesNotStarveLoop:
    """POST /api/notifications/{id}/played with slow embeddings+store writes must not stall the loop."""

    @pytest.mark.asyncio
    async def test_slow_mark_played_does_not_stall_loop( self ):
        """A 0.8s-blocking mark_played (2 embeddings + a store write — the
        2026-06-11 wedge smoking gun) leaves the loop ticking (T4 offload)."""
        _warm_main_module_import()
        ws_manager         = _online_ws_manager()
        notification_queue = Mock()

        def slow_mark_played( notification_id ):
            time.sleep( BLOCK_SECONDS )
            return True

        notification_queue.mark_played = slow_mark_played

        app = _build_app( ws_manager, notification_queue )

        async def fire_mark_played( client ):
            return await client.post( "/api/notifications/notif-123/played" )

        # get_local_timestamp reads lupin_app.main.config_mgr (None in the bare
        # unit env) — pin it so the response can serialize.
        with patch( 'cosa.rest.routers.notifications.get_local_timestamp', return_value="2026-06-12T00:00:00-04:00" ):
            max_lag_seconds, played_response = await _measure_loop_lag_during( app, fire_mark_played )

        assert played_response.status_code == 200
        assert played_response.json()[ "status" ] == "success"
        assert max_lag_seconds < LAG_MAX_SECONDS, (
            f"event loop stalled {max_lag_seconds:.3f}s while mark_played's embedding+store work "
            f"was in flight — blocking I/O is back ON the loop (the 2026-06-11 wedge mechanism)"
        )
