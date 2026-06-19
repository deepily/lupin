"""
Unit tests for the peer-queue router (`cosa.rest.routers.peer`).

Covers:
- Host/queue validation helpers (_get_allowed_hosts, _is_host_allowed,
  _validate_host_and_queue).
- Peer auth (_login_to_peer: env-missing 500, success, non-200/missing-token/
  timeout/generic 502s), JWT cache (_get_peer_jwt cached vs fresh,
  _invalidate_peer_jwt), and _fetch_queue (200, 401-retry, non-200, timeout,
  generic).
- get_peer_queue proxy endpoint.
- _watcher_loop (drain, not-drained→drain, HTTP error arm, generic error arm,
  cancellation), _fire_notification (success + failure).
- start_watcher / stop_watcher / get_watcher_status / cancel_all_watchers_on_shutdown.

Zero external dependencies — aiohttp sessions, the env, time, asyncio.sleep,
asyncio.create_task, sync_notify, and the config manager are all boundary-mocked.
No real network, no real background tasks. Auth bypassed by passing admin_user.
"""

import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
import time as _time
import os

from fastapi import HTTPException

import cosa.rest.routers.peer as peer
from cosa.rest.routers.peer import (
    _get_allowed_hosts, _is_host_allowed, _validate_host_and_queue,
    _login_to_peer, _get_peer_jwt, _invalidate_peer_jwt, _fetch_queue,
    get_peer_queue, _watcher_loop, _fire_notification,
    start_watcher, stop_watcher, get_watcher_status,
    cancel_all_watchers_on_shutdown,
    WatchStartRequest,
)

P = "cosa.rest.routers.peer"


# ── Fakes ────────────────────────────────────────────────────────────────────

class _FakeResp:
    """Async-CM stand-in for an aiohttp response."""
    def __init__( self, status, json_data=None, text_data="" ):
        self.status = status
        self._json  = json_data
        self._text  = text_data
    async def __aenter__( self ): return self
    async def __aexit__( self, *a ): return False
    async def json( self ): return self._json
    async def text( self ): return self._text


class _FakeSessionCM:
    """Async-CM stand-in for aiohttp.ClientSession()."""
    def __init__( self, session ): self._s = session
    async def __aenter__( self ): return self._s
    async def __aexit__( self, *a ): return False


class _FakeTask:
    """Awaitable stand-in for an asyncio.Task."""
    def __init__( self, done=False ):
        self._done     = done
        self.cancelled = False
    def done( self ): return self._done
    def cancel( self ): self.cancelled = True
    def __await__( self ):
        if False: yield   # make it a generator → awaitable
        return None


class _RaisingTask( _FakeTask ):
    """Awaitable task whose await raises (exercises the except-pass arm)."""
    def __await__( self ):
        if False: yield
        raise RuntimeError( "task blew up on await" )


def _clear_globals():
    peer._peer_jwt_cache.clear()
    peer._active_watchers.clear()
    peer._watcher_state.clear()


# ── Validation helpers ─────────────────────────────────────────────────────────

class TestHostHelpers( unittest.TestCase ):
    """
    Unit tests for host/queue validation helpers.

    Ensures:
        - allowed-hosts parsing (empty + comma list w/ stripping)
        - _is_host_allowed default vs explicit whitelist
        - _validate_host_and_queue raises on bad queue / bad host, passes otherwise
    """

    def test_get_allowed_hosts_empty( self ):
        """Ensures: empty config yields an empty list."""
        mgr = MagicMock(); mgr.get.return_value = ""
        with patch.object( peer, "_config_mgr", mgr ):
            self.assertEqual( _get_allowed_hosts(), [] )

    def test_get_allowed_hosts_parsed_and_stripped( self ):
        """Ensures: comma list is split, stripped, and empties dropped."""
        mgr = MagicMock(); mgr.get.return_value = "a:7999, b:7999 ,,  "
        with patch.object( peer, "_config_mgr", mgr ):
            self.assertEqual( _get_allowed_hosts(), [ "a:7999", "b:7999" ] )

    def test_is_host_allowed_explicit_whitelist( self ):
        """Ensures: explicit whitelist is honored without config lookup."""
        self.assertTrue( _is_host_allowed( "x:7999", [ "x:7999" ] ) )
        self.assertFalse( _is_host_allowed( "y:7999", [ "x:7999" ] ) )

    def test_is_host_allowed_default_whitelist( self ):
        """Ensures: a None whitelist falls back to _get_allowed_hosts()."""
        with patch( f"{P}._get_allowed_hosts", return_value=[ "x:7999" ] ):
            self.assertTrue( _is_host_allowed( "x:7999" ) )

    def test_validate_bad_queue_400( self ):
        """Ensures: an unknown queue name raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            _validate_host_and_queue( "x:7999", "bogus" )
        self.assertEqual( ctx.exception.status_code, 400 )

    def test_validate_bad_host_400( self ):
        """Ensures: a non-whitelisted host raises 400."""
        with patch( f"{P}._is_host_allowed", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                _validate_host_and_queue( "x:7999", "todo" )
        self.assertEqual( ctx.exception.status_code, 400 )

    def test_validate_ok( self ):
        """Ensures: valid queue + whitelisted host passes (returns None)."""
        with patch( f"{P}._is_host_allowed", return_value=True ):
            self.assertIsNone( _validate_host_and_queue( "x:7999", "todo" ) )


# ── Peer auth ───────────────────────────────────────────────────────────────────

class TestLoginToPeer( unittest.IsolatedAsyncioTestCase ):
    """
    Unit tests for `_login_to_peer`.

    Ensures:
        - missing env → 500; success returns token+expiry; non-200/missing-token/
          timeout/generic failures all raise 502
    """

    async def test_missing_env_500( self ):
        """Ensures: absent service-account creds raise 500."""
        with patch.dict( os.environ, {}, clear=True ):
            with self.assertRaises( HTTPException ) as ctx:
                await _login_to_peer( MagicMock(), "h:7999" )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_returns_token( self ):
        """Ensures: a 200 login returns the access token + a future expiry."""
        session = MagicMock()
        session.post = MagicMock( return_value=_FakeResp( 200, json_data={ "tokens": { "access_token": "TK" } } ) )
        with patch.dict( os.environ, { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e",
                                        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" } ), \
             patch( f"{P}.time.time", return_value=1000.0 ):
            result = await _login_to_peer( session, "h:7999" )
        self.assertEqual( result[ "token" ], "TK" )
        self.assertEqual( result[ "expires_at" ], 1000.0 + 25 * 60 )

    async def test_non_200_502( self ):
        """Ensures: a non-200 login response raises 502."""
        session = MagicMock()
        session.post = MagicMock( return_value=_FakeResp( 403, text_data="forbidden" ) )
        with patch.dict( os.environ, { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e",
                                        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" } ):
            with self.assertRaises( HTTPException ) as ctx:
                await _login_to_peer( session, "h:7999" )
        self.assertEqual( ctx.exception.status_code, 502 )

    async def test_missing_token_502( self ):
        """Ensures: a 200 with no access_token raises 502."""
        session = MagicMock()
        session.post = MagicMock( return_value=_FakeResp( 200, json_data={ "tokens": {} } ) )
        with patch.dict( os.environ, { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e",
                                        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" } ):
            with self.assertRaises( HTTPException ) as ctx:
                await _login_to_peer( session, "h:7999" )
        self.assertEqual( ctx.exception.status_code, 502 )

    async def test_timeout_502( self ):
        """Ensures: a timeout during login raises 502."""
        session = MagicMock()
        session.post = MagicMock( side_effect=asyncio.TimeoutError )
        with patch.dict( os.environ, { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e",
                                        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" } ):
            with self.assertRaises( HTTPException ) as ctx:
                await _login_to_peer( session, "h:7999" )
        self.assertEqual( ctx.exception.status_code, 502 )

    async def test_generic_exception_502( self ):
        """Ensures: an unexpected error during login raises 502."""
        session = MagicMock()
        session.post = MagicMock( side_effect=ValueError( "boom" ) )
        with patch.dict( os.environ, { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e",
                                        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" } ):
            with self.assertRaises( HTTPException ) as ctx:
                await _login_to_peer( session, "h:7999" )
        self.assertEqual( ctx.exception.status_code, 502 )


class TestPeerJwtCache( unittest.IsolatedAsyncioTestCase ):
    """
    Unit tests for the per-host JWT cache.

    Ensures:
        - a valid cached token is reused; an expired/absent one re-logs in
        - _invalidate_peer_jwt drops the entry
    """

    def setUp( self ): _clear_globals()
    def tearDown( self ): _clear_globals()

    async def test_returns_cached_token_when_valid( self ):
        """Ensures: a non-expired cached token is returned without re-login."""
        peer._peer_jwt_cache[ "h" ] = { "token": "CACHED", "expires_at": 9999.0 }
        with patch( f"{P}.time.time", return_value=1.0 ), \
             patch( f"{P}._login_to_peer", new=AsyncMock() ) as m_login:
            tok = await _get_peer_jwt( MagicMock(), "h" )
        self.assertEqual( tok, "CACHED" )
        m_login.assert_not_called()

    async def test_relogs_when_expired( self ):
        """Ensures: an expired cache entry triggers a fresh login + re-cache."""
        peer._peer_jwt_cache[ "h" ] = { "token": "OLD", "expires_at": 1.0 }
        with patch( f"{P}.time.time", return_value=5000.0 ), \
             patch( f"{P}._login_to_peer",
                    new=AsyncMock( return_value={ "token": "NEW", "expires_at": 9999.0 } ) ):
            tok = await _get_peer_jwt( MagicMock(), "h" )
        self.assertEqual( tok, "NEW" )
        self.assertEqual( peer._peer_jwt_cache[ "h" ][ "token" ], "NEW" )

    def test_invalidate_drops_entry( self ):
        """Ensures: invalidation removes the host's cache entry (idempotent)."""
        peer._peer_jwt_cache[ "h" ] = { "token": "X", "expires_at": 1.0 }
        _invalidate_peer_jwt( "h" )
        self.assertNotIn( "h", peer._peer_jwt_cache )
        _invalidate_peer_jwt( "h" )   # no-op on missing


class TestFetchQueue( unittest.IsolatedAsyncioTestCase ):
    """
    Unit tests for `_fetch_queue`.

    Ensures:
        - 200 returns JSON; 401 invalidates + retries once; non-200/timeout/generic → 502
    """

    def setUp( self ): _clear_globals()
    def tearDown( self ): _clear_globals()

    async def test_success_returns_json( self ):
        """Ensures: a 200 returns the parsed upstream body."""
        session = MagicMock()
        session.get = MagicMock( return_value=_FakeResp( 200, json_data={ "total_jobs": 3 } ) )
        with patch( f"{P}._get_peer_jwt", new=AsyncMock( return_value="TK" ) ):
            result = await _fetch_queue( session, "h", "todo" )
        self.assertEqual( result, { "total_jobs": 3 } )

    async def test_401_invalidates_and_retries( self ):
        """Ensures: a 401 invalidates the token and retries once (then succeeds)."""
        session = MagicMock()
        session.get = MagicMock( side_effect=[ _FakeResp( 401 ), _FakeResp( 200, json_data={ "total_jobs": 0 } ) ] )
        with patch( f"{P}._get_peer_jwt", new=AsyncMock( return_value="TK" ) ), \
             patch( f"{P}._invalidate_peer_jwt" ) as m_inv:
            result = await _fetch_queue( session, "h", "run" )
        self.assertEqual( result, { "total_jobs": 0 } )
        m_inv.assert_called_once_with( "h" )

    async def test_non_200_502( self ):
        """Ensures: a non-200 (non-401) upstream raises 502."""
        session = MagicMock()
        session.get = MagicMock( return_value=_FakeResp( 500, text_data="err" ) )
        with patch( f"{P}._get_peer_jwt", new=AsyncMock( return_value="TK" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await _fetch_queue( session, "h", "run" )
        self.assertEqual( ctx.exception.status_code, 502 )

    async def test_timeout_502( self ):
        """Ensures: a timeout raises 502."""
        session = MagicMock()
        session.get = MagicMock( side_effect=asyncio.TimeoutError )
        with patch( f"{P}._get_peer_jwt", new=AsyncMock( return_value="TK" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await _fetch_queue( session, "h", "run" )
        self.assertEqual( ctx.exception.status_code, 502 )

    async def test_generic_502( self ):
        """Ensures: an unexpected error raises 502."""
        session = MagicMock()
        session.get = MagicMock( side_effect=ValueError( "boom" ) )
        with patch( f"{P}._get_peer_jwt", new=AsyncMock( return_value="TK" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await _fetch_queue( session, "h", "run" )
        self.assertEqual( ctx.exception.status_code, 502 )


# ── Proxy endpoint ────────────────────────────────────────────────────────────

class TestGetPeerQueue( unittest.IsolatedAsyncioTestCase ):
    """
    Ensures:
        - validates host/queue, fetches, and shapes a PeerQueueResponse
    """

    async def test_returns_peer_queue_response( self ):
        """Ensures: a successful proxy read returns total_jobs + raw upstream."""
        with patch( f"{P}._validate_host_and_queue" ), \
             patch( f"{P}.aiohttp.ClientSession", return_value=_FakeSessionCM( MagicMock() ) ), \
             patch( f"{P}._fetch_queue", new=AsyncMock( return_value={ "total_jobs": 7, "jobs": [] } ) ), \
             patch( f"{P}.du.get_current_datetime_iso", return_value="2026-06-01T00:00:00" ):
            resp = await get_peer_queue( queue_name="todo", host="h:7999", admin_user={ "uid": "a" } )
        self.assertEqual( resp.total_jobs, 7 )
        self.assertEqual( resp.peer_host, "h:7999" )
        self.assertEqual( resp.queue_name, "todo" )


# ── Watcher loop + notification ──────────────────────────────────────────────────

class TestWatcherLoop( unittest.IsolatedAsyncioTestCase ):
    """
    Unit tests for `_watcher_loop`.

    Ensures:
        - drain fires notification + exits; not-drained polls again then drains
        - HTTP and generic errors are caught per-iteration; cancellation propagates
    """

    UID = "admin_1"

    def setUp( self ):
        _clear_globals()
        peer._watcher_state[ self.UID ] = { "consecutive_zero": 0 }

    def tearDown( self ): _clear_globals()

    async def _run_loop( self, signal, fetch_side_effect, stable_for=1, sleep_side_effect=None ):
        sleep = AsyncMock( side_effect=sleep_side_effect ) if sleep_side_effect else AsyncMock()
        with patch( f"{P}.aiohttp.ClientSession", return_value=_FakeSessionCM( MagicMock() ) ), \
             patch( f"{P}._fetch_queue", new=AsyncMock( side_effect=fetch_side_effect ) ), \
             patch( f"{P}._fire_notification", new=AsyncMock() ) as m_fire, \
             patch( f"{P}.asyncio.sleep", new=sleep ), \
             patch( f"{P}.du.get_current_datetime_iso", return_value="2026-06-01T00:00:00" ):
            await _watcher_loop( self.UID, "h", signal, 60, stable_for, "high", "sender-1" )
        return m_fire

    async def test_immediate_drain_fires_and_exits( self ):
        """Ensures: run+todo both zero with stable_for=1 → fire + exit."""
        m_fire = await self._run_loop( "run+todo", [ { "total_jobs": 0 }, { "total_jobs": 0 } ], stable_for=1 )
        m_fire.assert_awaited_once()
        self.assertFalse( peer._watcher_state[ self.UID ][ "active" ] )
        self.assertEqual( peer._watcher_state[ self.UID ][ "drained_at" ], "2026-06-01T00:00:00" )

    async def test_not_drained_then_drained_run_signal( self ):
        """Ensures: a non-zero poll resets the counter; later zeros reach stable_for."""
        # signal="run" → todo not fetched. run: 5, 0, 0 with stable_for=2
        m_fire = await self._run_loop( "run", [ { "total_jobs": 5 }, { "total_jobs": 0 }, { "total_jobs": 0 } ], stable_for=2 )
        m_fire.assert_awaited_once()

    async def test_http_error_arm_then_drain( self ):
        """Ensures: an HTTPException in a poll is caught, then a later poll drains."""
        side = [ HTTPException( status_code=502, detail="x" ), { "total_jobs": 0 }, { "total_jobs": 0 } ]
        m_fire = await self._run_loop( "run+todo", side, stable_for=1 )
        m_fire.assert_awaited_once()

    async def test_generic_error_arm_then_drain( self ):
        """Ensures: a generic exception in a poll is caught, then a later poll drains."""
        side = [ ValueError( "boom" ), { "total_jobs": 0 }, { "total_jobs": 0 } ]
        with patch( f"{P}.traceback.print_exc" ):
            m_fire = await self._run_loop( "run+todo", side, stable_for=1 )
        m_fire.assert_awaited_once()

    async def test_cancellation_propagates( self ):
        """Ensures: a CancelledError during sleep flips active False + re-raises."""
        with self.assertRaises( asyncio.CancelledError ):
            await self._run_loop( "run", [ { "total_jobs": 5 } ], stable_for=2,
                                  sleep_side_effect=asyncio.CancelledError )
        self.assertFalse( peer._watcher_state[ self.UID ][ "active" ] )
        self.assertEqual( peer._watcher_state[ self.UID ][ "last_error" ], "cancelled" )


class TestFireNotification( unittest.IsolatedAsyncioTestCase ):
    """
    Ensures:
        - _fire_notification dispatches via sync_notify; failures are swallowed
    """

    async def test_dispatches_via_sync_notify( self ):
        """Ensures: the notification is dispatched through asyncio.to_thread."""
        with patch( f"{P}.asyncio.to_thread", new=AsyncMock() ) as m_thread, \
             patch( "cosa.agents.utils.sync_notify.notify" ):
            await _fire_notification( "msg", "sender-1", "high" )
        m_thread.assert_awaited_once()

    async def test_dispatch_failure_swallowed( self ):
        """Ensures: a dispatch failure is logged, not raised."""
        with patch( f"{P}.asyncio.to_thread", new=AsyncMock( side_effect=RuntimeError( "down" ) ) ), \
             patch( "cosa.agents.utils.sync_notify.notify" ), \
             patch( f"{P}.traceback.print_exc" ):
            await _fire_notification( "msg", "sender-1", "high" )   # must not raise


# ── Watcher lifecycle endpoints ──────────────────────────────────────────────────

class TestStartWatcher( unittest.IsolatedAsyncioTestCase ):
    """
    Unit tests for `start_watcher`.

    Ensures:
        - invalid signal → 400; valid start seeds state + task; existing watcher is
          cancelled-and-replaced (not-done) or left alone (done)
    """

    def setUp( self ): _clear_globals()
    def tearDown( self ): _clear_globals()

    def _req( self, signal="run" ):
        return WatchStartRequest( host="h:7999", signal=signal, interval_seconds=60, stable_for=2, priority="high" )

    async def test_invalid_signal_400( self ):
        """Ensures: an unsupported signal raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            await start_watcher( request=self._req( signal="bogus" ), admin_user={ "uid": "a" } )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_start_seeds_state_and_task( self ):
        """Ensures: a valid start registers state + an active task."""
        with patch( f"{P}._validate_host_and_queue" ), \
             patch( f"{P}._watcher_loop", new=MagicMock( return_value="CORO" ) ), \
             patch( f"{P}.asyncio.create_task", return_value=_FakeTask() ) as m_ct, \
             patch( f"{P}.du.get_current_datetime_iso", return_value="2026-06-01T00:00:00" ):
            resp = await start_watcher( request=self._req(), admin_user={ "uid": "a" } )
        self.assertEqual( resp.status, "started" )
        self.assertIn( "a", peer._active_watchers )
        self.assertTrue( peer._watcher_state[ "a" ][ "active" ] )
        m_ct.assert_called_once()

    async def test_replaces_prior_active_watcher( self ):
        """Ensures: an existing non-done watcher is cancelled before replacement."""
        prior = _FakeTask( done=False )
        peer._active_watchers[ "a" ] = prior
        with patch( f"{P}._validate_host_and_queue" ), \
             patch( f"{P}._watcher_loop", new=MagicMock( return_value="CORO" ) ), \
             patch( f"{P}.asyncio.create_task", return_value=_FakeTask() ), \
             patch( f"{P}.du.get_current_datetime_iso", return_value="t" ):
            await start_watcher( request=self._req(), admin_user={ "uid": "a" } )
        self.assertTrue( prior.cancelled )

    async def test_prior_done_not_cancelled( self ):
        """Ensures: an already-done prior watcher is not cancelled."""
        prior = _FakeTask( done=True )
        peer._active_watchers[ "a" ] = prior
        with patch( f"{P}._validate_host_and_queue" ), \
             patch( f"{P}._watcher_loop", new=MagicMock( return_value="CORO" ) ), \
             patch( f"{P}.asyncio.create_task", return_value=_FakeTask() ), \
             patch( f"{P}.du.get_current_datetime_iso", return_value="t" ):
            await start_watcher( request=self._req(), admin_user={ "uid": "a" } )
        self.assertFalse( prior.cancelled )

    async def test_replaces_prior_whose_await_raises( self ):
        """Ensures: an exception while awaiting the cancelled prior is swallowed."""
        prior = _RaisingTask( done=False )
        peer._active_watchers[ "a" ] = prior
        with patch( f"{P}._validate_host_and_queue" ), \
             patch( f"{P}._watcher_loop", new=MagicMock( return_value="CORO" ) ), \
             patch( f"{P}.asyncio.create_task", return_value=_FakeTask() ), \
             patch( f"{P}.du.get_current_datetime_iso", return_value="t" ):
            resp = await start_watcher( request=self._req(), admin_user={ "uid": "a" } )
        self.assertEqual( resp.status, "started" )   # prior await-raise swallowed
        self.assertTrue( prior.cancelled )


class TestStopWatcher( unittest.IsolatedAsyncioTestCase ):
    """
    Unit tests for `stop_watcher`.

    Ensures:
        - no/done task → not_active (with optional state flip); active task → stopped;
          await-raise is swallowed
    """

    def setUp( self ): _clear_globals()
    def tearDown( self ): _clear_globals()

    async def test_no_task_not_active( self ):
        """Ensures: no registered task → not_active, no state to flip."""
        resp = await stop_watcher( admin_user={ "uid": "a" } )
        self.assertEqual( resp.status, "not_active" )

    async def test_done_task_flips_state( self ):
        """Ensures: a done task → not_active and flips the state's active flag."""
        peer._active_watchers[ "a" ] = _FakeTask( done=True )
        peer._watcher_state[ "a" ]   = { "active": True }
        resp = await stop_watcher( admin_user={ "uid": "a" } )
        self.assertEqual( resp.status, "not_active" )
        self.assertFalse( peer._watcher_state[ "a" ][ "active" ] )

    async def test_active_task_cancelled( self ):
        """Ensures: an active task is cancelled + awaited → stopped."""
        task = _FakeTask( done=False )
        peer._active_watchers[ "a" ] = task
        peer._watcher_state[ "a" ]   = { "active": True }
        resp = await stop_watcher( admin_user={ "uid": "a" } )
        self.assertEqual( resp.status, "stopped" )
        self.assertTrue( task.cancelled )
        self.assertFalse( peer._watcher_state[ "a" ][ "active" ] )

    async def test_await_raise_swallowed( self ):
        """Ensures: an exception while awaiting the cancelled task is swallowed."""
        peer._active_watchers[ "a" ] = _RaisingTask( done=False )
        resp = await stop_watcher( admin_user={ "uid": "a" } )
        self.assertEqual( resp.status, "stopped" )


class TestGetWatcherStatus( unittest.IsolatedAsyncioTestCase ):
    """
    Ensures:
        - missing state → default inactive response; present state → populated response
    """

    def setUp( self ): _clear_globals()
    def tearDown( self ): _clear_globals()

    async def test_no_state_default_response( self ):
        """Ensures: no watcher state → an all-None inactive response."""
        resp = await get_watcher_status( admin_user={ "uid": "a" } )
        self.assertFalse( resp.active )
        self.assertIsNone( resp.host )

    async def test_present_state_populated( self ):
        """Ensures: an existing state dict is reflected verbatim."""
        peer._watcher_state[ "a" ] = {
            "active": True, "host": "h:7999", "signal": "run", "interval_seconds": 60,
            "stable_for": 2, "started_at": "t", "last_poll_at": None, "last_run": 1,
            "last_todo": None, "consecutive_zero": 0, "last_error": None, "drained_at": None,
        }
        resp = await get_watcher_status( admin_user={ "uid": "a" } )
        self.assertTrue( resp.active )
        self.assertEqual( resp.host, "h:7999" )
        self.assertEqual( resp.last_run, 1 )


class TestCancelAllWatchers( unittest.IsolatedAsyncioTestCase ):
    """
    Ensures:
        - all active watchers are cancelled + awaited; the registry is cleared
    """

    def setUp( self ): _clear_globals()
    def tearDown( self ): _clear_globals()

    async def test_cancels_and_clears( self ):
        """Ensures: not-done tasks are cancelled, done tasks left, registry cleared."""
        active = _FakeTask( done=False )
        done   = _FakeTask( done=True )
        raising = _RaisingTask( done=False )
        peer._active_watchers.update( { "a": active, "b": done, "c": raising } )
        await cancel_all_watchers_on_shutdown()
        self.assertTrue( active.cancelled )
        self.assertFalse( done.cancelled )
        self.assertEqual( peer._active_watchers, {} )


def isolated_unit_test():
    """
    Run the peer router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = _time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestHostHelpers, TestLoginToPeer, TestPeerJwtCache, TestFetchQueue,
            TestGetPeerQueue, TestWatcherLoop, TestFireNotification,
            TestStartWatcher, TestStopWatcher, TestGetWatcherStatus, TestCancelAllWatchers,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = _time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL PEER ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME PEER ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = _time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 PEER ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Peer router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
