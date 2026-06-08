"""
Unit tests for the voice-persona router (`cosa.rest.routers.voice_persona`).

Covers:
- get_notification_queue / get_config_manager dependencies.
- get_voice_persona_pool — occupancy + free + active-session shaping (incl.
  non-dict / nameless persona filtering).
- get_voice_persona_endpoint — 404 + read.
- allocate_voice_persona_endpoint — every mode: 404, mutual-exclusive 422,
  outer idempotency, requested same-name idempotency, requested
  none/not_in_pool/occupied/success/write-fail, no-request raced idempotency,
  no-request random success/empty-pool, preferred ok/none/occupied-fallback/
  not_in_pool-fallback (avail + empty), preferred fallback empty-pool, broadcast
  failure, conflict-notify failure, re-assign announce (via previous + via swap)
  and its push failure.
- release_voice_persona_endpoint — 404, already-empty, write-fail, success, broadcast fail.
- voice_persona_sample — missing fields 400, not-in-pool 400 (+ overflow accept),
  missing api key 503, httpx error 503, upstream non-200 503, success.

Zero external dependencies — bridge helpers, persona-pool helpers, httpx,
du.get_api_key, and the notification queue are boundary-mocked. No real bridge,
no ElevenLabs call, no API spend. Auth bypassed by passing the user id.
"""

import unittest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import sys
import time

from fastapi import HTTPException

from cosa.rest.routers.voice_persona import (
    get_notification_queue, get_config_manager,
    get_voice_persona_pool, get_voice_persona_endpoint,
    allocate_voice_persona_endpoint, release_voice_persona_endpoint,
    voice_persona_sample, VoicePersonaSampleRequest,
)

VP = "cosa.rest.routers.voice_persona"


def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _json( response ):
    import json
    return json.loads( bytes( response.body ).decode() )


def _persona( name="María", vid="v_maria" ):
    return { "name": name, "display_name": name, "voice_id": vid }


def _queue( raise_on_type=None ):
    q = MagicMock()
    if raise_on_type:
        def push( **kw ):
            if kw.get( "type" ) == raise_on_type:
                raise RuntimeError( "ws down" )
            return None
        q.push_notification.side_effect = push
    return q


class TestDependencies( unittest.TestCase ):
    """Ensures: the two DI helpers resolve correctly."""

    def test_get_notification_queue( self ):
        """Ensures: notification queue read off lupin_app.main."""
        m = MagicMock(); m.jobs_notification_queue = "NQ"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_notification_queue(), "NQ" )

    def test_get_config_manager( self ):
        """Ensures: config manager is constructed with the standard env var."""
        with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value="CM" ) as MC:
            self.assertEqual( get_config_manager(), "CM" )
        MC.assert_called_once()


class TestPool( unittest.IsolatedAsyncioTestCase ):
    """Ensures: pool snapshot computes occupancy/free + filters bad entries."""

    async def test_pool_snapshot( self ):
        """Ensures: occupied/free derived; non-dict + nameless personas filtered."""
        cfg = MagicMock(); cfg.get.return_value = 43200
        pool = [ _persona( "María" ), _persona( "Edmund" ) ]
        active = [
            ( "/p/a", "s1", { "name": "María", "borrowed": False } ),  # occupies María
            ( "/p/b", "s2", { "borrowed": True } ),                    # dict, no name → ignored for occupancy
            ( "/p/c", "s3", "not-a-dict" ),                            # non-dict → filtered everywhere
        ]
        with patch( f"{VP}.load_persona_pool_from_config", return_value=pool ), \
             patch( f"{VP}.find_active_voice_persona_sessions", return_value=active ):
            resp = await get_voice_persona_pool( authenticated_user_id="u", config_mgr=cfg )
        body = _json( resp )
        self.assertEqual( body[ "occupied_names" ], [ "María" ] )
        self.assertEqual( body[ "free_names" ], [ "Edmund" ] )
        # only the two dict entries appear in active_sessions
        self.assertEqual( len( body[ "active_sessions" ] ), 2 )


class TestGetVoicePersona( unittest.IsolatedAsyncioTestCase ):
    """Ensures: read endpoint 404s on missing bridge, returns persona otherwise."""

    async def test_not_found_404( self ):
        """Ensures: missing bridge → 404."""
        with patch( f"{VP}.find_session_path_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_voice_persona_endpoint( session_id="s1", authenticated_user_id="u" )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_returns_persona( self ):
        """Ensures: existing bridge returns the persona dict."""
        with patch( f"{VP}.find_session_path_by_id", return_value="/p/s1" ), \
             patch( f"{VP}.get_voice_persona", return_value=_persona() ):
            resp = await get_voice_persona_endpoint( session_id="s1", authenticated_user_id="u" )
        self.assertEqual( _json( resp )[ "voice_persona" ][ "name" ], "María" )


class TestAllocate( unittest.IsolatedAsyncioTestCase ):
    """Comprehensive branch coverage for the allocate endpoint."""

    def setUp( self ):
        p = patch( f"{VP}.find_session_path_by_id", return_value="/p/s1" )
        p.start(); self.addCleanup( p.stop )
        p = patch( f"{VP}.build_sender_id_for_cc", side_effect=lambda sid: f"snd-{sid}" )
        p.start(); self.addCleanup( p.stop )
        self.cfg = MagicMock()

    async def _alloc( self, **kw ):
        defaults = dict(
            session_id="s1", authenticated_user_id="u",
            previous_persona_name=None, requested_persona_name=None, preferred_persona_name=None,
            notification_queue=kw.pop( "queue", _queue() ), config_mgr=self.cfg,
        )
        defaults.update( kw )
        return await allocate_voice_persona_endpoint( **defaults )

    async def test_not_found_404( self ):
        """Ensures: missing bridge → 404."""
        with patch( f"{VP}.find_session_path_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc()
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_mutually_exclusive_422( self ):
        """Ensures: supplying both requested + preferred → 422."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._alloc( requested_persona_name="A", preferred_persona_name="B" )
        self.assertEqual( ctx.exception.status_code, 422 )

    async def test_outer_idempotent_return( self ):
        """Ensures: existing persona + no request → idempotent return (no lock)."""
        with patch( f"{VP}.get_voice_persona", return_value=_persona() ):
            resp = await self._alloc()
        body = _json( resp )
        self.assertFalse( body[ "newly_allocated" ] )
        self.assertFalse( body[ "swapped" ] )

    async def test_requested_same_name_idempotent( self ):
        """Ensures: requested name matching existing (case-insensitive) → idempotent."""
        with patch( f"{VP}.get_voice_persona", return_value=_persona( "María" ) ):
            resp = await self._alloc( requested_persona_name="maría" )
        self.assertFalse( _json( resp )[ "newly_allocated" ] )

    async def test_requested_result_none_500( self ):
        """Ensures: allocate-requested returning None → 500 (empty pool)."""
        with patch( f"{VP}.get_voice_persona", return_value=None ), \
             patch( f"{VP}.allocate_requested_persona_for_session", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc( requested_persona_name="X" )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_requested_not_in_pool_422( self ):
        """Ensures: requested name not in pool → 422 with available list."""
        with patch( f"{VP}.get_voice_persona", return_value=None ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "not_in_pool", "available": [ "A" ] } ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc( requested_persona_name="X" )
        self.assertEqual( ctx.exception.status_code, 422 )

    async def test_requested_occupied_409( self ):
        """Ensures: requested name held by another session → 409."""
        with patch( f"{VP}.get_voice_persona", return_value=None ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "occupied", "holding_session_id": "s2",
                                   "holding_persona_name": "X", "available": [ "A" ] } ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc( requested_persona_name="X" )
        self.assertEqual( ctx.exception.status_code, 409 )

    async def test_requested_success_with_swap( self ):
        """Ensures: requested success from an existing persona → swap + re-assign announce."""
        q = _queue()
        with patch( f"{VP}.get_voice_persona", return_value=_persona( "Old" ) ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "ok", "persona": _persona( "New" ) } ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( requested_persona_name="New", queue=q )
        body = _json( resp )
        self.assertTrue( body[ "newly_allocated" ] )
        self.assertTrue( body[ "swapped" ] )
        types = [ c.kwargs.get( "type" ) for c in q.push_notification.call_args_list ]
        self.assertIn( "task", types )   # the re-assign announcement

    async def test_requested_success_write_fail_500( self ):
        """Ensures: a bridge write failure on requested allocation → 500."""
        with patch( f"{VP}.get_voice_persona", return_value=None ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "ok", "persona": _persona() } ), \
             patch( f"{VP}.set_voice_persona", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc( requested_persona_name="X" )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_no_request_raced_idempotent( self ):
        """Ensures: existing appearing only under the lock → idempotent return."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, _persona( "Raced" ) ] ):
            resp = await self._alloc()
        self.assertFalse( _json( resp )[ "newly_allocated" ] )

    async def test_no_request_random_success( self ):
        """Ensures: no request + empty bridge → random allocation, no re-assign."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona() ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc()
        body = _json( resp )
        self.assertTrue( body[ "newly_allocated" ] )
        self.assertFalse( body[ "swapped" ] )

    async def test_no_request_empty_pool_500( self ):
        """Ensures: random allocation returning None → 500."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc()
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_no_request_write_fail_500( self ):
        """Ensures: bridge write failure on random allocation → 500."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona() ), \
             patch( f"{VP}.set_voice_persona", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc()
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_preferred_ok( self ):
        """Ensures: preferred persona available → allocated, no conflict."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "ok", "persona": _persona() } ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( preferred_persona_name="María" )
        self.assertIsNone( _json( resp )[ "preference_conflict" ] )

    async def test_preferred_result_none_500( self ):
        """Ensures: preferred allocate returning None → 500."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_requested_persona_for_session", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc( preferred_persona_name="María" )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_preferred_occupied_fallback_to_random( self ):
        """Ensures: preferred held elsewhere → random fallback + occupied conflict notify."""
        q = _queue()
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "occupied", "holding_session_id": "sother123",
                                   "holding_persona_name": "María", "available": [ "A" ] } ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona( "Edmund" ) ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( preferred_persona_name="María", queue=q )
        body = _json( resp )
        self.assertEqual( body[ "preference_conflict" ][ "kind" ], "occupied" )
        types = [ c.kwargs.get( "type" ) for c in q.push_notification.call_args_list ]
        self.assertIn( "voice_persona_conflict", types )

    async def test_preferred_not_in_pool_fallback_with_available( self ):
        """Ensures: preferred not in pool (avail names) → fallback + not_in_pool conflict."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "not_in_pool", "available": [ "A", "B" ] } ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona( "Edmund" ) ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( preferred_persona_name="Ghost" )
        self.assertEqual( _json( resp )[ "preference_conflict" ][ "kind" ], "not_in_pool" )

    async def test_preferred_not_in_pool_fallback_empty_available( self ):
        """Ensures: not_in_pool with no free names → conflict notify uses '(none free)'."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "not_in_pool", "available": [] } ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona( "Edmund" ) ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( preferred_persona_name="Ghost" )
        self.assertEqual( _json( resp )[ "preference_conflict" ][ "available" ], [] )

    async def test_preferred_fallback_empty_pool_500( self ):
        """Ensures: preferred conflict then empty random pool → 500."""
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "not_in_pool", "available": [] } ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._alloc( preferred_persona_name="Ghost" )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_broadcast_failure_sets_delivered_false( self ):
        """Ensures: a failed assigned-broadcast → broadcast_delivered False (not error)."""
        q = _queue( raise_on_type="voice_persona_assigned" )
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona() ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( queue=q )
        self.assertFalse( _json( resp )[ "broadcast_delivered" ] )

    async def test_conflict_notify_failure_swallowed( self ):
        """Ensures: a failed conflict notify does not fail the request."""
        q = _queue( raise_on_type="voice_persona_conflict" )
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_requested_persona_for_session",
                    return_value={ "status": "not_in_pool", "available": [ "A" ] } ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona( "Edmund" ) ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( preferred_persona_name="Ghost", queue=q )
        self.assertTrue( _json( resp )[ "newly_allocated" ] )

    async def test_reassign_via_previous_persona_name( self ):
        """Ensures: previous_persona_name drives the re-assign announcement."""
        q = _queue()
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona( "New" ) ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            await self._alloc( previous_persona_name="Old", queue=q )
        types = [ c.kwargs.get( "type" ) for c in q.push_notification.call_args_list ]
        self.assertIn( "task", types )

    async def test_reassign_announce_push_failure_swallowed( self ):
        """Ensures: a failed re-assign announcement does not fail the request."""
        q = _queue( raise_on_type="task" )
        with patch( f"{VP}.get_voice_persona", side_effect=[ None, None ] ), \
             patch( f"{VP}.allocate_persona_for_session", return_value=_persona( "New" ) ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._alloc( previous_persona_name="Old", queue=q )
        self.assertTrue( _json( resp )[ "newly_allocated" ] )


class TestRelease( unittest.IsolatedAsyncioTestCase ):
    """Ensures: release 404 / already-empty / write-fail / success / broadcast-fail."""

    def setUp( self ):
        p = patch( f"{VP}.build_sender_id_for_cc", side_effect=lambda sid: f"snd-{sid}" )
        p.start(); self.addCleanup( p.stop )

    async def _release( self, queue=None ):
        return await release_voice_persona_endpoint(
            session_id="s1", authenticated_user_id="u", notification_queue=queue or _queue()
        )

    async def test_not_found_404( self ):
        """Ensures: missing bridge → 404."""
        with patch( f"{VP}.find_session_path_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._release()
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_already_empty_returns_false( self ):
        """Ensures: releasing an empty slot returns released=False."""
        with patch( f"{VP}.find_session_path_by_id", return_value="/p" ), \
             patch( f"{VP}.get_voice_persona", return_value=None ):
            resp = await self._release()
        self.assertFalse( _json( resp )[ "released" ] )

    async def test_write_fail_500( self ):
        """Ensures: a clear-write failure → 500."""
        with patch( f"{VP}.find_session_path_by_id", return_value="/p" ), \
             patch( f"{VP}.get_voice_persona", return_value=_persona() ), \
             patch( f"{VP}.set_voice_persona", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._release()
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success( self ):
        """Ensures: a populated slot is cleared and broadcast."""
        with patch( f"{VP}.find_session_path_by_id", return_value="/p" ), \
             patch( f"{VP}.get_voice_persona", return_value=_persona() ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._release()
        body = _json( resp )
        self.assertTrue( body[ "released" ] )
        self.assertTrue( body[ "broadcast_delivered" ] )

    async def test_broadcast_fail( self ):
        """Ensures: a failed release broadcast → broadcast_delivered False."""
        q = _queue( raise_on_type="voice_persona_released" )
        with patch( f"{VP}.find_session_path_by_id", return_value="/p" ), \
             patch( f"{VP}.get_voice_persona", return_value=_persona() ), \
             patch( f"{VP}.set_voice_persona", return_value=True ):
            resp = await self._release( queue=q )
        self.assertFalse( _json( resp )[ "broadcast_delivered" ] )


class TestVoiceSample( unittest.IsolatedAsyncioTestCase ):
    """Ensures: the ElevenLabs sample endpoint validates + serves + errors correctly."""

    def setUp( self ):
        self.cfg = MagicMock()
        self.cfg.get.side_effect = lambda key, default=None, **kw: default

    async def _sample( self, voice_id="v_maria", text="hello" ):
        return await voice_persona_sample(
            authenticated_user_id="u",
            body=VoicePersonaSampleRequest( voice_id=voice_id, text=text ),
            config_mgr=self.cfg,
        )

    async def test_missing_fields_400( self ):
        """Ensures: empty voice_id/text → 400."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._sample( voice_id="", text="" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_voice_id_not_in_pool_400( self ):
        """Ensures: a voice_id outside the pool (and not overflow) → 400."""
        with patch( f"{VP}.load_persona_pool_from_config", return_value=[ _persona() ] ), \
             patch( f"{VP}.load_overflow_persona_from_config", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._sample( voice_id="v_unknown" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_overflow_voice_id_accepted_then_no_key_503( self ):
        """Ensures: the overflow (Sam) voice_id is accepted; missing api key → 503."""
        with patch( f"{VP}.load_persona_pool_from_config", return_value=[ _persona() ] ), \
             patch( f"{VP}.load_overflow_persona_from_config", return_value={ "voice_id": "v_sam" } ), \
             patch( f"{VP}.du.get_api_key", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._sample( voice_id="v_sam" )
        self.assertEqual( ctx.exception.status_code, 503 )

    async def test_httpx_error_503( self ):
        """Ensures: an httpx transport error → 503."""
        import httpx
        client_cm = MagicMock()
        client_cm.__aenter__ = AsyncMock( return_value=MagicMock( post=AsyncMock( side_effect=httpx.HTTPError( "boom" ) ) ) )
        client_cm.__aexit__  = AsyncMock( return_value=False )
        with patch( f"{VP}.load_persona_pool_from_config", return_value=[ _persona() ] ), \
             patch( f"{VP}.load_overflow_persona_from_config", return_value=None ), \
             patch( f"{VP}.du.get_api_key", return_value="key" ), \
             patch( f"{VP}.httpx.AsyncClient", return_value=client_cm ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._sample( voice_id="v_maria" )
        self.assertEqual( ctx.exception.status_code, 503 )

    async def test_upstream_non_200_503( self ):
        """Ensures: a non-200 ElevenLabs response → 503 with a redacted snippet."""
        resp_obj = MagicMock( status_code=429, text="quota exceeded" )
        client_cm = MagicMock()
        client_cm.__aenter__ = AsyncMock( return_value=MagicMock( post=AsyncMock( return_value=resp_obj ) ) )
        client_cm.__aexit__  = AsyncMock( return_value=False )
        with patch( f"{VP}.load_persona_pool_from_config", return_value=[ _persona() ] ), \
             patch( f"{VP}.load_overflow_persona_from_config", return_value=None ), \
             patch( f"{VP}.du.get_api_key", return_value="key" ), \
             patch( f"{VP}.httpx.AsyncClient", return_value=client_cm ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._sample( voice_id="v_maria" )
        self.assertEqual( ctx.exception.status_code, 503 )

    async def test_success_returns_audio( self ):
        """Ensures: a 200 ElevenLabs response → audio/mpeg Response bytes."""
        resp_obj = MagicMock( status_code=200, content=b"AUDIO" )
        client_cm = MagicMock()
        client_cm.__aenter__ = AsyncMock( return_value=MagicMock( post=AsyncMock( return_value=resp_obj ) ) )
        client_cm.__aexit__  = AsyncMock( return_value=False )
        with patch( f"{VP}.load_persona_pool_from_config", return_value=[ _persona() ] ), \
             patch( f"{VP}.load_overflow_persona_from_config", return_value=None ), \
             patch( f"{VP}.du.get_api_key", return_value="key" ), \
             patch( f"{VP}.httpx.AsyncClient", return_value=client_cm ):
            resp = await self._sample( voice_id="v_maria" )
        self.assertEqual( resp.media_type, "audio/mpeg" )
        self.assertEqual( resp.body, b"AUDIO" )


def isolated_unit_test():
    """Run the voice-persona router unit tests in isolation."""
    import cosa.utils.util as du
    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestDependencies, TestPool, TestGetVoicePersona, TestAllocate,
            TestRelease, TestVoiceSample,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )
        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )
        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL VOICE-PERSONA ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME VOICE-PERSONA ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        return success, duration, message
    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 VOICE-PERSONA ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Voice-persona router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
