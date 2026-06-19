"""
Supplemental coverage tests for cosa.rest.routers.notifications.

Companion to test_notifications_router.py (left untouched). Closes the coverage
gap on: the voice-persona helper + import fallbacks, time/date display helpers,
resolve_sender_id, the full notify_user matrix (validation, idempotency,
persist, listener fallback, offline/online response-required SSE), the
submit_notification_response endpoint, and the entire sender/conversation/
history/gist endpoint family.

Boundary-isolated: get_db / NotificationRepository / get_user_by_email /
ConfigurationManager / prediction engine / Gister / user_job_tracker /
websocket_manager are all mocked. Zero GPU/DB/net/LLM. Run BOTH files together:

    PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python \
      -m pytest src/cosa/tests/unit/rest/test_notifications_router.py \
                src/cosa/tests/unit/rest/test_notifications_router_coverage.py \
      --cov=cosa.rest.routers.notifications --cov-branch --cov-report=term-missing \
      -p no:cacheprovider -q
"""

import sys
import os
import time
import uuid
import threading
import asyncio
import importlib
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

import cosa.rest.routers.notifications as N
from cosa.rest.routers.notifications import (
    _voice_persona_for_sender_id, get_formatted_time_display, get_formatted_date_display,
    resolve_sender_id, notify_user, submit_notification_response,
    get_next_notification, mark_notification_played, delete_notification,
    bulk_delete_notifications, get_senders_with_activity, get_sender_conversation,
    delete_sender_conversation, get_sender_conversation_by_date, soft_delete_by_date,
    get_sender_date_summaries, get_visible_senders, get_active_conversation,
    get_project_sessions, generate_session_gist, get_undelivered_notifications,
)


UID_STR  = "12345678-1234-5678-1234-567812345678"
UID_UUID = uuid.UUID( UID_STR )


def _patch_fastapi_main( mock_main ):
    """G1 dual-key patch of lupin_app.main (see test_notifications_router.py)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _ctx_db( mock_db ):
    """get_db replacement whose context-manager yields mock_db."""
    gd = MagicMock()
    gd.return_value.__enter__.return_value = mock_db
    return gd


def _seed_idempotency_cache( n ):
    """Fill the module idempotency cache past its cap so the trim/popitem path runs."""
    N._idempotency_cache.clear()
    now = time.time()
    for i in range( n ):
        N._idempotency_cache[ f"seed-{i}" ] = ( { "status": "seed" }, now )


def _wait_for_stub( result=None, exc=None ):
    """
    Drop-in for asyncio.wait_for in SSE tests. Closes the inbound coroutine
    (response_event.wait()) so it isn't left un-awaited (no ResourceWarning),
    then returns `result` or raises `exc` to drive the generator's branch.
    """
    async def _f( coro, *a, **k ):
        coro.close()
        if exc is not None:
            raise exc
        return result
    return _f


def _ws_manager( is_connected=True, connection_count=1, listener_delivered=True ):
    ws = Mock()
    ws.is_user_connected            = Mock( return_value=is_connected )
    ws.get_user_connection_count    = Mock( return_value=connection_count )
    ws.user_sessions                = {}
    ws.active_connections           = {}
    ws.user_to_email                = {}
    ws.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": listener_delivered } )
    ws.emit_to_user_sync            = Mock()
    return ws


# ===========================================================================
# Module-level helper functions
# ===========================================================================
class TestVoicePersonaHelper( unittest.TestCase ):
    """Coverage for _voice_persona_for_sender_id and its import fallbacks."""

    def test_bridge_none_returns_none( self ):
        with patch.object( N, "_bridge_get_voice_persona", None ):
            self.assertIsNone( _voice_persona_for_sender_id( "x#abc" ) )

    def test_no_hash_returns_none( self ):
        with patch.object( N, "_bridge_get_voice_persona", Mock() ):
            self.assertIsNone( _voice_persona_for_sender_id( "no-hash-here" ) )

    def test_empty_suffix_returns_none( self ):
        with patch.object( N, "_bridge_get_voice_persona", Mock() ):
            self.assertIsNone( _voice_persona_for_sender_id( "claude.code@x#   " ) )

    def test_bridge_raises_returns_none( self ):
        with patch.object( N, "_bridge_get_voice_persona", Mock( side_effect=Exception( "boom" ) ) ):
            self.assertIsNone( _voice_persona_for_sender_id( "x#abcd1234" ) )

    def test_persona_without_display_name_stamped( self ):
        bridge = Mock( return_value={ "name": "tiberius" } )
        with patch.object( N, "_bridge_get_voice_persona", bridge ), \
             patch.object( N, "_display_name_for", Mock( return_value="Tiberius" ) ):
            out = _voice_persona_for_sender_id( "x#abcd1234" )
        self.assertEqual( out[ "display_name" ], "Tiberius" )

    def test_persona_with_display_name_passthrough( self ):
        bridge = Mock( return_value={ "name": "rio", "display_name": "Rio" } )
        with patch.object( N, "_bridge_get_voice_persona", bridge ):
            out = _voice_persona_for_sender_id( "x#abcd1234" )
        self.assertEqual( out[ "display_name" ], "Rio" )

    def test_import_fallbacks_set_globals_none( self ):
        """
        Force both optional imports to fail and reload the module so the
        `except ImportError:` fallback arms (_bridge_get_voice_persona /
        _display_name_for → None) execute, then reload clean to restore state.
        """
        blockers = {
            "lupin_cli.claude_code.hooks.lib.session_bridge": None,
            "cosa.rest.voice_persona_helpers": None,
        }
        try:
            with patch.dict( sys.modules, blockers ):
                reloaded = importlib.reload( N )
                self.assertIsNone( reloaded._bridge_get_voice_persona )
                self.assertIsNone( reloaded._display_name_for )
        finally:
            importlib.reload( N )   # restore real imports for the rest of the suite


class TestTimeDateDisplay( unittest.TestCase ):
    """Coverage for get_formatted_time_display / get_formatted_date_display."""

    def _main( self, tz_name ):
        cfg = Mock(); cfg.get.return_value = tz_name
        m = Mock(); m.config_mgr = cfg
        return m

    def test_time_display_success( self ):
        with _patch_fastapi_main( self._main( "America/New_York" ) ):
            out = get_formatted_time_display()
        self.assertRegex( out, r"^\d{2}:\d{2}" )

    def test_time_display_fallback( self ):
        with _patch_fastapi_main( self._main( "Bogus/Zone" ) ):
            out = get_formatted_time_display()
        self.assertRegex( out, r"^\d{2}:\d{2}$" )

    def test_date_display_success( self ):
        with _patch_fastapi_main( self._main( "America/New_York" ) ):
            out = get_formatted_date_display()
        self.assertRegex( out, r"^\d{4}-\d{2}-\d{2}$" )

    def test_date_display_fallback( self ):
        with _patch_fastapi_main( self._main( "Bogus/Zone" ) ):
            out = get_formatted_date_display()
        self.assertRegex( out, r"^\d{4}-\d{2}-\d{2}$" )


class TestResolveSenderId( unittest.TestCase ):
    """Coverage for resolve_sender_id precedence."""

    def test_explicit_wins( self ):
        self.assertEqual( resolve_sender_id( "explicit@x", "[LUPIN] hi" ), "explicit@x" )

    def test_extract_from_prefix( self ):
        self.assertEqual( resolve_sender_id( None, "[LUPIN] hi" ), "claude.code@lupin.deepily.ai" )

    def test_default_fallback( self ):
        self.assertEqual( resolve_sender_id( None, "no prefix" ), "claude.code@unknown.deepily.ai" )


# ===========================================================================
# notify_user — the monster endpoint
# ===========================================================================
class TestNotifyUser( unittest.IsolatedAsyncioTestCase ):

    EMAIL = "ricardo.felipe.ruiz@gmail.com"

    async def _call( self, nq, ws, **overrides ):
        kwargs = dict(
            authenticated_user_id    = "svc",
            message                  = "Hello world",
            type                     = "progress",
            direction                = "ai_to_human",
            priority                 = "medium",
            target_user              = self.EMAIL,
            response_requested       = False,
            response_type            = None,
            timeout_seconds          = 120,
            response_default         = None,
            title                    = None,
            sender_id                = None,
            response_options         = None,
            abstract                 = None,
            job_id                   = None,
            queue_name               = None,
            suppress_ding            = False,
            progress_group_id        = None,
            prediction_hint_override = None,
            display_qualifier_widget = False,
            session_name             = None,
            idempotency_key          = None,
            notification_queue       = nq,
            ws_manager               = ws,
        )
        kwargs.update( overrides )
        return await notify_user( **kwargs )

    def _user_main( self, app_debug=False, app_verbose=False ):
        m = Mock(); m.app_debug = app_debug; m.app_verbose = app_verbose
        return m

    # ---- validation ----
    async def test_response_required_missing_type_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( Mock(), _ws_manager(), response_requested=True, response_type=None )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_response_required_invalid_type_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( Mock(), _ws_manager(), response_requested=True, response_type="bogus" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_multiple_choice_without_options_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( Mock(), _ws_manager(), response_requested=True,
                              response_type="multiple_choice", response_options=None )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_timeout_nonpositive_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( Mock(), _ws_manager(), response_requested=True,
                              response_type="yes_no", timeout_seconds=0 )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_bad_response_options_json_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( Mock(), _ws_manager(), response_options="{not json" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "response_options", ctx.exception.detail )

    async def test_bad_prediction_hint_json_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( Mock(), _ws_manager(), prediction_hint_override="{bad" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "prediction_hint_override", ctx.exception.detail )

    async def test_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._call( Mock(), _ws_manager() )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_outer_exception_500( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", side_effect=RuntimeError( "kaboom" ) ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._call( Mock(), _ws_manager() )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_backpressure_over_cap_429( self ):
        """
        Ensures a sender over the per-session notify cap is rejected with HTTP 429.

        Ensures:
            - check_notify_allowed returning ( False, retry ) raises HTTPException 429
            - the Retry-After header is int( retry ) + 1 (lever-E backpressure contract)
        """
        with patch( "cosa.rest.notify_rate_limiter.check_notify_allowed", return_value=( False, 4.2 ) ), \
             patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._call( Mock(), _ws_manager() )
        self.assertEqual( ctx.exception.status_code, 429 )
        self.assertEqual( ctx.exception.headers[ "Retry-After" ], "5" )

    # ---- fire-and-forget connected ----
    async def test_connected_queued_with_diag_and_persist_and_idempotency( self ):
        nq = Mock(); nq.push_notification.return_value = Mock()
        ws = _ws_manager( is_connected=True, connection_count=2 )
        # Populate session maps so the app_debug+verbose diag loop body executes,
        # and seed the idempotency cache past _IDEMPOTENCY_MAX so the queued-path
        # trim (popitem) runs.
        ws.user_sessions      = { UID_STR: [ "s1", "cc-listener-x" ] }
        ws.active_connections = { "s1": Mock(), "cc-listener-x": Mock() }
        _seed_idempotency_cache( 1100 )
        mock_db = Mock()
        repo = Mock(); repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( mock_db ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main( app_debug=True, app_verbose=True ) ), \
             patch( "builtins.print" ):
            out = await self._call( nq, ws, idempotency_key="key-1" )
        self.assertEqual( out[ "status" ], "queued" )
        repo.update_state.assert_called_once()        # is_connected → delivered
        self.assertIn( "key-1", N._idempotency_cache )
        self.assertLessEqual( len( N._idempotency_cache ), N._IDEMPOTENCY_MAX )

    async def test_idempotency_hit_returns_cached_and_evicts_expired( self ):
        # Seed an expired entry (evicted) + a fresh entry for our key (hit).
        N._idempotency_cache.clear()
        N._idempotency_cache[ "stale" ] = ( { "status": "old" }, time.time() - 999 )
        cached = { "status": "from-cache" }
        N._idempotency_cache[ "key-hit" ] = ( cached, time.time() )
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( Mock(), ws, idempotency_key="key-hit" )
        self.assertEqual( out[ "status" ], "from-cache" )
        self.assertNotIn( "stale", N._idempotency_cache )   # evicted

    async def test_idempotency_all_expired_evicted_to_empty( self ):
        # Seed ONLY expired entries so the eviction while-loop pops every one and
        # exits on the empty-cache condition (516->523 false arm) before the miss.
        N._idempotency_cache.clear()
        old = time.time() - 999
        for i in range( 3 ):
            N._idempotency_cache[ f"old-{i}" ] = ( { "status": "old" }, old )
        nq = Mock(); nq.push_notification.return_value = Mock()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", side_effect=Exception( "skip persist" ) ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, idempotency_key="fresh-key" )
        self.assertEqual( out[ "status" ], "queued" )
        self.assertNotIn( "old-0", N._idempotency_cache )   # all expired entries evicted

    async def test_persist_failure_nonfatal_then_queued( self ):
        nq = Mock(); nq.push_notification.return_value = Mock()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", side_effect=Exception( "db down" ) ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws )
        self.assertEqual( out[ "status" ], "queued" )

    # ---- offline + job_id listener fallback ----
    async def test_offline_listener_delivered_with_state_update( self ):
        ws = _ws_manager( is_connected=False, connection_count=0, listener_delivered=True )
        _seed_idempotency_cache( 1100 )   # exercise listener-path cache trim (popitem)
        mock_db = Mock(); repo = Mock()
        repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( mock_db ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( Mock(), ws, job_id="dr-a1b2c3d4", idempotency_key="lk" )
        self.assertEqual( out[ "status" ], "delivered_via_listener" )
        self.assertIn( "lk", N._idempotency_cache )

    async def test_offline_listener_state_update_failure_nonfatal( self ):
        ws = _ws_manager( is_connected=False, connection_count=0, listener_delivered=True )
        # First get_db (persist) ok; second get_db (state update) raises.
        good_db = Mock(); repo = Mock(); repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        gd = MagicMock()
        gd.return_value.__enter__.side_effect = [ good_db, Exception( "state db down" ) ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", gd ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( Mock(), ws, job_id="dr-a1b2c3d4" )
        self.assertEqual( out[ "status" ], "delivered_via_listener" )

    async def test_offline_listener_not_delivered_falls_through( self ):
        ws = _ws_manager( is_connected=False, connection_count=0, listener_delivered=False )
        _seed_idempotency_cache( 1100 )   # exercise user_not_available-path cache trim
        mock_db = Mock(); repo = Mock(); repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( mock_db ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( Mock(), ws, job_id="dr-a1b2c3d4", idempotency_key="uk" )
        self.assertEqual( out[ "status" ], "user_not_available" )
        self.assertIn( "uk", N._idempotency_cache )

    async def test_offline_no_job_id_user_not_available( self ):
        ws = _ws_manager( is_connected=False, connection_count=0 )
        # Populate session maps so the (ungated) OFFLINE-diag loop body executes.
        ws.user_sessions      = { UID_STR: [ "s1" ] }
        ws.active_connections = { "s1": Mock() }
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", side_effect=Exception( "skip persist" ) ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( Mock(), ws, job_id=None )
        self.assertEqual( out[ "status" ], "user_not_available" )

    # ---- response-required offline ----
    async def test_response_required_offline_with_default( self ):
        ws = _ws_manager( is_connected=False, connection_count=0 )
        mock_db = Mock(); repo = Mock(); repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( mock_db ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( Mock(), ws, response_requested=True, response_type="yes_no",
                                    response_default="no" )
        self.assertIsInstance( out, JSONResponse )

    async def test_response_required_offline_no_default_503( self ):
        ws = _ws_manager( is_connected=False, connection_count=0 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await self._call( Mock(), ws, response_requested=True, response_type="yes_no",
                                  response_default=None )
        self.assertEqual( ctx.exception.status_code, 503 )

    # ---- response-required online (prediction + SSE) ----
    def _online_repo( self ):
        repo = Mock()
        repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        return repo

    def _online_item( self ):
        item = Mock(); item.response_default = "x"; item.to_dict.return_value = {}
        return item

    async def test_online_prediction_override_returns_sse( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, response_requested=True, response_type="yes_no",
                                    response_default="no", prediction_hint_override='{"hint": 1}' )
        self.assertIsInstance( out, StreamingResponse )

    async def test_online_prediction_engine_enabled( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        pred = Mock(); pred.metadata = {}; pred.confidence = 0.9; pred.category = "yes"
        pred.to_hint_dict.return_value = { "h": 1 }
        engine = Mock(); engine.enabled = True; engine.confidence_threshold = 0.5
        engine.predict.return_value = pred
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=engine ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        self.assertIsInstance( out, StreamingResponse )
        engine.predict.assert_called_once()

    async def test_predict_runs_off_event_loop_thread( self ):
        # FM-7 regression guard: predict() must run on a WORKER thread (via
        # asyncio.to_thread), never the event-loop thread — otherwise a slow
        # GPU embedding / LanceDB search freezes the loop and /health times out.
        # Reverting to a bare `prediction_engine.predict(...)` call makes predict
        # run on the loop thread → this assertion fails. Deterministic, no sleep.
        loop_thread_id = threading.get_ident()
        captured       = {}
        def _capture_predict( payload ):
            captured[ "thread_id" ] = threading.get_ident()
            pred = Mock(); pred.metadata = {}; pred.confidence = 0.9; pred.category = "yes"
            pred.to_hint_dict.return_value = { "h": 1 }
            return pred
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        engine = Mock(); engine.enabled = True; engine.confidence_threshold = 0.5
        engine.predict.side_effect = _capture_predict
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=engine ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        self.assertIsInstance( out, StreamingResponse )
        engine.predict.assert_called_once()
        self.assertIn( "thread_id", captured )
        self.assertNotEqual( captured[ "thread_id" ], loop_thread_id,
                             "predict() ran on the event-loop thread — FM-7 offload regressed (must use asyncio.to_thread)" )

    async def test_online_prediction_engine_raises_nonfatal( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine", side_effect=Exception( "pred down" ) ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        self.assertIsInstance( out, StreamingResponse )

    async def test_online_prediction_engine_disabled( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        engine = Mock(); engine.enabled = False
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=engine ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        self.assertIsInstance( out, StreamingResponse )
        engine.predict.assert_not_called()   # disabled → 784->807 false arm

    async def test_online_prediction_metadata_none_low_confidence( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        pred = Mock(); pred.metadata = None; pred.confidence = 0.1; pred.category = "no"
        engine = Mock(); engine.enabled = True; engine.confidence_threshold = 0.5
        engine.predict.return_value = pred
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=engine ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        self.assertIsInstance( out, StreamingResponse )   # metadata None + conf<threshold false arms

    # ---- vote-gate stamp (Stage 3 — threshold carried IN the hint payload) ----
    def _vote_engine( self, voting_enabled=True, threshold=0.5 ):
        pred = Mock(); pred.metadata = {}; pred.confidence = 0.9; pred.category = "yes"
        pred.to_hint_dict.return_value = { "predicted_value": "yes" }
        engine = Mock(); engine.enabled = True; engine.confidence_threshold = 0.5
        engine.hint_voting_enabled                = voting_enabled
        engine.hint_vote_min_confidence_threshold = threshold
        engine.predict.return_value = pred
        return engine

    async def test_vote_gate_stamped_when_voting_enabled( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=self._vote_engine() ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        pushed_hint = nq.push_notification.call_args.kwargs[ "prediction_hint" ]
        self.assertEqual( pushed_hint[ "vote_min_confidence_threshold" ], 0.5 )

    async def test_vote_gate_not_stamped_when_voting_disabled( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine",
                    return_value=self._vote_engine( voting_enabled=False ) ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        pushed_hint = nq.push_notification.call_args.kwargs[ "prediction_hint" ]
        self.assertNotIn( "vote_min_confidence_threshold", pushed_hint )

    async def test_vote_gate_respects_override_preset( self ):
        # An override hint that pre-sets the gate keeps its value — the stamp block
        # must not second-guess it (and must not even need the engine).
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine",
                    side_effect=Exception( "engine must not be consulted" ) ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no",
                              prediction_hint_override='{"predicted_value": "yes", "vote_min_confidence_threshold": 0.25}' )
        pushed_hint = nq.push_notification.call_args.kwargs[ "prediction_hint" ]
        self.assertEqual( pushed_hint[ "vote_min_confidence_threshold" ], 0.25 )

    async def test_vote_gate_stamp_error_nonfatal( self ):
        # predict succeeds (first get_prediction_engine call), the stamp's second
        # call blows up → notification still goes out, hint just lacks the gate.
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=self._online_repo() ), \
             patch( "cosa.agents.prediction_engine.get_prediction_engine",
                    side_effect=[ self._vote_engine(), Exception( "gate down" ) ] ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            out = await self._call( nq, ws, response_requested=True, response_type="yes_no", response_default="no" )
        self.assertIsInstance( out, StreamingResponse )
        pushed_hint = nq.push_notification.call_args.kwargs[ "prediction_hint" ]
        self.assertNotIn( "vote_min_confidence_threshold", pushed_hint )

    async def _drain( self, response ):
        chunks = []
        async for c in response.body_iterator:
            chunks.append( c )
        return "".join( chunks )

    async def _make_sse( self, nq, ws ):
        return await self._call( nq, ws, response_requested=True, response_type="yes_no",
                                 response_default="no", prediction_hint_override='{"hint": 1}' )

    async def test_sse_response_received_path( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        fixed_id = uuid.uuid4()
        repo = Mock(); repo.create_notification.return_value = Mock( id=fixed_id )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            resp = await self._make_sse( nq, ws )
            nid = str( fixed_id )
            # Simulate a response arriving before the stream is drained.
            N.pending_responses[ nid ][ "response_data" ] = "yes"
            with patch.object( N.asyncio, "wait_for", _wait_for_stub() ):
                body = await self._drain( resp )
        self.assertIn( "responded", body )
        self.assertNotIn( nid, N.pending_responses )   # finally cleanup

    async def test_sse_timeout_path( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        fixed_id = uuid.uuid4()
        repo = Mock(); repo.create_notification.return_value = Mock( id=fixed_id )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            resp = await self._make_sse( nq, ws )
            with patch.object( N.asyncio, "wait_for", _wait_for_stub( exc=asyncio.TimeoutError() ) ):
                body = await self._drain( resp )
        self.assertIn( "expired", body )

    async def test_sse_timeout_path_ws_emit_failure( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        ws.emit_to_user_or_listener_sync.side_effect = Exception( "ws gone" )
        fixed_id = uuid.uuid4()
        repo = Mock(); repo.create_notification.return_value = Mock( id=fixed_id )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            resp = await self._make_sse( nq, ws )
            with patch.object( N.asyncio, "wait_for", _wait_for_stub( exc=asyncio.TimeoutError() ) ):
                body = await self._drain( resp )
        self.assertIn( "expired", body )

    async def test_sse_finally_entry_already_removed( self ):
        # Delete the pending_responses entry before draining: reading
        # response_data at 849 raises KeyError → generic except → finally's
        # `if notification_id in pending_responses` takes the false (exit) arm.
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        fixed_id = uuid.uuid4()
        repo = Mock(); repo.create_notification.return_value = Mock( id=fixed_id )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            resp = await self._make_sse( nq, ws )
            N.pending_responses.pop( str( fixed_id ), None )
            with patch.object( N.asyncio, "wait_for", _wait_for_stub() ):
                body = await self._drain( resp )
        self.assertIn( "error", body )

    async def test_sse_generic_error_path( self ):
        nq = Mock(); nq.push_notification.return_value = self._online_item()
        ws = _ws_manager( is_connected=True, connection_count=1 )
        fixed_id = uuid.uuid4()
        repo = Mock(); repo.create_notification.return_value = Mock( id=fixed_id )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._user_main() ), patch( "builtins.print" ):
            resp = await self._make_sse( nq, ws )
            with patch.object( N.asyncio, "wait_for", _wait_for_stub( exc=ValueError( "weird" ) ) ):
                body = await self._drain( resp )
        self.assertIn( "error", body )


# ===========================================================================
# submit_notification_response
# ===========================================================================
class TestSubmitResponse( unittest.IsolatedAsyncioTestCase ):

    def _main_cfg( self, grace=300 ):
        cfg = Mock(); cfg.get.return_value = grace
        m = Mock(); m.config_mgr = cfg
        return m

    async def test_missing_notification_id_422( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await submit_notification_response( request_body={ "response_value": "yes" }, ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 422 )

    async def test_missing_response_value_422( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await submit_notification_response( request_body={ "notification_id": UID_STR }, ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 422 )

    async def test_empty_string_response_400( self ):
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "  <b></b> " },
                    ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_notification_not_found_404( self ):
        repo = Mock(); repo.get_by_id.return_value = None
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" },
                    ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_already_responded_400( self ):
        notif = Mock(); notif.state = "responded"
        repo = Mock(); repo.get_by_id.return_value = notif
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" },
                    ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_expired_beyond_grace_400( self ):
        notif = Mock(); notif.state = "expired"
        notif.expires_at = datetime.now( timezone.utc ) - timedelta( seconds=10000 )
        repo = Mock(); repo.get_by_id.return_value = notif
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._main_cfg( grace=300 ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" },
                    ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_expired_within_grace_accepted( self ):
        notif = Mock(); notif.state = "expired"
        notif.expires_at = datetime.now( timezone.utc ) - timedelta( seconds=5 )
        notif.recipient_id = UID_STR; notif.job_id = "dr-a1b2c3d4"
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
             patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
             _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
            out = await submit_notification_response(
                request_body={ "notification_id": UID_STR, "response_value": "yes" },
                ws_manager=_ws_manager() )
        self.assertEqual( out[ "status" ], "success" )

    async def test_update_response_false_500( self ):
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR; notif.job_id = None
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = False
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" },
                    ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_dict_value_with_prediction_and_sse_signal( self ):
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR; notif.job_id = "dr-a1b2c3d4"
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        # Seed an SSE waiter + prediction result for this notification id.
        N.pending_responses[ UID_STR ] = { "event": asyncio.Event(), "response_data": None }
        pred_res = Mock(); pred_res.response_type = "yes_no"
        N.pending_responses[ UID_STR ][ "prediction_result" ] = pred_res
        engine = Mock()
        ws = _ws_manager()
        try:
            with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
                 patch.object( N, "NotificationRepository", return_value=repo ), \
                 patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=engine ), \
                 patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
                 patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
                 _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
                out = await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": { "value": "blue" } },
                    ws_manager=ws )
            self.assertEqual( out[ "status" ], "success" )
            engine.record_outcome.assert_called_once()
            self.assertTrue( N.pending_responses[ UID_STR ][ "event" ].is_set() )
        finally:
            N.pending_responses.pop( UID_STR, None )

    async def test_record_outcome_runs_off_event_loop_thread( self ):
        # FM-7 regression guard (symmetric to predict): record_outcome() does
        # 3-5 GPU embeddings + a LanceDB write; it must run on a WORKER thread,
        # never the event-loop thread, or the response path freezes /health.
        # Reverting to a bare call makes this assertion fail. Deterministic.
        loop_thread_id = threading.get_ident()
        captured       = {}
        def _capture_record( **kwargs ):
            captured[ "thread_id" ] = threading.get_ident()
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR; notif.job_id = None
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        N.pending_responses[ UID_STR ] = { "event": asyncio.Event(), "response_data": None,
                                           "prediction_result": Mock( response_type="yes_no" ) }
        engine = Mock(); engine.record_outcome.side_effect = _capture_record
        try:
            with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
                 patch.object( N, "NotificationRepository", return_value=repo ), \
                 patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=engine ), \
                 patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
                 patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
                 _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
                out = await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" },
                    ws_manager=_ws_manager() )
            self.assertEqual( out[ "status" ], "success" )
            engine.record_outcome.assert_called_once()
            self.assertIn( "thread_id", captured )
            self.assertNotEqual( captured[ "thread_id" ], loop_thread_id,
                                 "record_outcome() ran on the event-loop thread — FM-7 offload regressed" )
        finally:
            N.pending_responses.pop( UID_STR, None )

    async def test_prediction_outcome_recording_error_nonfatal( self ):
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR; notif.job_id = None
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        N.pending_responses[ UID_STR ] = { "event": asyncio.Event(), "response_data": None,
                                           "prediction_result": Mock( response_type="yes_no" ) }
        engine = Mock(); engine.record_outcome.side_effect = Exception( "record down" )
        try:
            with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
                 patch.object( N, "NotificationRepository", return_value=repo ), \
                 patch( "cosa.agents.prediction_engine.get_prediction_engine", return_value=engine ), \
                 patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
                 patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
                 _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
                out = await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" }, ws_manager=_ws_manager() )
            self.assertEqual( out[ "status" ], "success" )   # outcome-recording error swallowed
        finally:
            N.pending_responses.pop( UID_STR, None )

    async def test_success_ws_broadcast_failure_nonfatal( self ):
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR; notif.job_id = None
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        ws = _ws_manager(); ws.emit_to_user_or_listener_sync.side_effect = Exception( "ws down" )
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
             patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
             _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
            out = await submit_notification_response(
                request_body={ "notification_id": UID_STR, "response_value": "yes" }, ws_manager=ws )
        self.assertEqual( out[ "status" ], "success" )

    async def test_outer_exception_500( self ):
        # Malformed (non-UUID) notification_id → uuid.UUID raises inside try → 500
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=Mock() ), \
             _patch_fastapi_main( self._main_cfg() ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await submit_notification_response(
                    request_body={ "notification_id": "not-a-uuid", "response_value": "yes" },
                    ws_manager=_ws_manager() )
        self.assertEqual( ctx.exception.status_code, 500 )


# ===========================================================================
# Simple endpoint error paths (exception → 500)
# ===========================================================================
class TestSimpleEndpointErrors( unittest.IsolatedAsyncioTestCase ):

    async def test_get_next_notification_error_500( self ):
        nq = Mock(); nq.get_next_unplayed.side_effect = Exception( "x" )
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_next_notification( user_id="u1", notification_queue=nq )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_mark_played_error_500( self ):
        nq = Mock(); nq.mark_played.side_effect = Exception( "x" )
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await mark_notification_played( notification_id="n1", notification_queue=nq )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_delete_notification_error_500( self ):
        nq = Mock(); nq.delete_by_id_hash.side_effect = Exception( "x" )
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_notification( notification_id="n1", notification_queue=nq )
        self.assertEqual( ctx.exception.status_code, 500 )


# ===========================================================================
# Sender / conversation / history endpoint family
# ===========================================================================
class TestSenderHistoryEndpoints( unittest.IsolatedAsyncioTestCase ):

    EMAIL = "ricardo.felipe.ruiz@gmail.com"

    def _cfg_main( self, tz="America/New_York" ):
        cfg = Mock(); cfg.get.return_value = tz
        m = Mock(); m.config_mgr = cfg
        return m

    def _patch_cfgmgr( self, tz="America/New_York" ):
        cfg = Mock(); cfg.get.return_value = tz
        return patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg )

    # ---- bulk_delete_notifications ----
    async def test_bulk_delete_hours_invalid_400( self ):
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await bulk_delete_notifications( user_email=self.EMAIL, hours=0, exclude_own_jobs=False )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_bulk_delete_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await bulk_delete_notifications( user_email=self.EMAIL, hours=None, exclude_own_jobs=False )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_bulk_delete_success_with_exclude_own_jobs( self ):
        repo = Mock(); repo.bulk_delete_by_user.return_value = 3
        tracker = Mock(); tracker.get_jobs_for_user.return_value = [ "j1" ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR, "uid": "u1" } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch( "cosa.rest.queue_extensions.user_job_tracker", tracker ), patch( "builtins.print" ):
            out = await bulk_delete_notifications( user_email=self.EMAIL, hours=24, exclude_own_jobs=True )
        self.assertEqual( out[ "deleted_count" ], 3 )

    async def test_bulk_delete_uuid_id_arm_and_error_500( self ):
        # id already a UUID (covers the non-str ternary arm) + repo raises → 500
        repo = Mock(); repo.bulk_delete_by_user.side_effect = Exception( "boom" )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_UUID, "uid": "u1" } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await bulk_delete_notifications( user_email=self.EMAIL, hours=None, exclude_own_jobs=False )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- get_senders_with_activity ----
    async def test_senders_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_senders_with_activity( user_email=self.EMAIL, hours=None )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_senders_success_with_hours_filter( self ):
        recent = datetime.now( timezone.utc )
        repo = Mock(); repo.get_sender_last_activities.return_value = [ { "sender_id": "s", "last_activity": recent } ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_senders_with_activity( user_email=self.EMAIL, hours=24 )
        self.assertEqual( len( out ), 1 )
        self.assertIsInstance( out[ 0 ][ "last_activity" ], str )

    async def test_senders_error_500( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_senders_with_activity( user_email=self.EMAIL, hours=None )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- get_sender_conversation ----
    def _notif( self ):
        n = Mock()
        n.id = uuid.uuid4(); n.sender_id = "s"; n.message = "m"; n.title = "t"; n.type = "progress"
        n.priority = "low"; n.state = "delivered"; n.is_hidden = False; n.abstract = ""
        n.created_at = datetime.now( timezone.utc ); n.delivered_at = None; n.responded_at = None
        n.response_requested = False; n.response_type = None; n.response_value = None
        n.job_id = None; n.progress_group_id = None
        return n

    async def test_conversation_user_not_found_404( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_conversation( sender_id="s", user_email=self.EMAIL, hours=24, anchor=None )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_conversation_bad_anchor_400( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_conversation( sender_id="s", user_email=self.EMAIL, hours=24, anchor="bad-stamp" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_conversation_success_with_anchor( self ):
        repo = Mock(); repo.get_sender_conversation.return_value = [ self._notif() ]
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_sender_conversation( sender_id="s", user_email=self.EMAIL, hours=24,
                                                 anchor="2026-06-01T00:00:00Z" )
        self.assertEqual( len( out ), 1 )

    async def test_conversation_error_500( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_conversation( sender_id="s", user_email=self.EMAIL, hours=24, anchor=None )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- delete_sender_conversation ----
    async def test_delete_conversation_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_sender_conversation( sender_id="s", user_email=self.EMAIL )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_delete_conversation_success( self ):
        repo = Mock(); repo.delete_by_sender.return_value = 2
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await delete_sender_conversation( sender_id="s", user_email=self.EMAIL )
        self.assertEqual( out[ "deleted_count" ], 2 )

    async def test_delete_conversation_error_500( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_sender_conversation( sender_id="s", user_email=self.EMAIL )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- get_sender_conversation_by_date ----
    async def test_by_date_user_not_found_404( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_conversation_by_date( sender_id="s", user_email=self.EMAIL,
                                                       hours=168, anchor=None, include_hidden=False )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_by_date_bad_anchor_400( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_conversation_by_date( sender_id="s", user_email=self.EMAIL,
                                                       hours=168, anchor="nope", include_hidden=False )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_by_date_success( self ):
        repo = Mock(); repo.get_sender_conversations_by_date.return_value = { "2026-06-01": [ self._notif() ] }
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_sender_conversation_by_date( sender_id="s", user_email=self.EMAIL,
                                                         hours=168, anchor="2026-06-01T00:00:00Z", include_hidden=True )
        self.assertIn( "2026-06-01", out )

    async def test_by_date_error_500( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_conversation_by_date( sender_id="s", user_email=self.EMAIL,
                                                       hours=168, anchor=None, include_hidden=False )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- soft_delete_by_date ----
    async def test_soft_delete_bad_date_400( self ):
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await soft_delete_by_date( sender_id="s", user_email=self.EMAIL, date_string="2026/06/01" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_soft_delete_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await soft_delete_by_date( sender_id="s", user_email=self.EMAIL, date_string="2026-06-01" )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_soft_delete_success( self ):
        repo = Mock(); repo.soft_delete_by_date.return_value = 5
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await soft_delete_by_date( sender_id="s", user_email=self.EMAIL, date_string="2026-06-01" )
        self.assertEqual( out[ "hidden_count" ], 5 )

    async def test_soft_delete_error_500( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await soft_delete_by_date( sender_id="s", user_email=self.EMAIL, date_string="2026-06-01" )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- get_sender_date_summaries ----
    async def test_date_summaries_user_not_found_404( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_date_summaries( sender_id="s", user_email=self.EMAIL, include_hidden=False )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_date_summaries_success( self ):
        repo = Mock(); repo.get_sender_date_summaries.return_value = [ { "date": "2026-06-01", "count": 3 } ]
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_sender_date_summaries( sender_id="s", user_email=self.EMAIL, include_hidden=True )
        self.assertEqual( len( out ), 1 )

    async def test_date_summaries_error_500( self ):
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_sender_date_summaries( sender_id="s", user_email=self.EMAIL, include_hidden=False )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- get_visible_senders ----
    async def test_visible_senders_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_visible_senders( user_email=self.EMAIL, hours=None, include_hidden=False, exclude_own_jobs=False )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_visible_senders_success_with_exclude_and_hours( self ):
        recent = datetime.now( timezone.utc )
        repo = Mock()
        repo.get_sender_last_activities_visible.return_value = [ { "sender_id": "s#abcd1234", "last_activity": recent } ]
        tracker = Mock(); tracker.get_jobs_for_user.return_value = [ "j1" ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR, "uid": "u1" } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch( "cosa.rest.queue_extensions.user_job_tracker", tracker ), \
             patch.object( N, "_voice_persona_for_sender_id", return_value=None ), patch( "builtins.print" ):
            out = await get_visible_senders( user_email=self.EMAIL, hours=24, include_hidden=False, exclude_own_jobs=True )
        self.assertEqual( len( out ), 1 )
        self.assertIsInstance( out[ 0 ][ "last_activity" ], str )

    async def test_visible_senders_error_500( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_visible_senders( user_email=self.EMAIL, hours=None, include_hidden=False, exclude_own_jobs=False )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- get_active_conversation ----
    async def test_active_conversation_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_active_conversation( user_email=self.EMAIL )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_active_conversation_success_uuid_id_arm( self ):
        repo = Mock(); repo.get_active_conversation.return_value = "s#abcd1234"
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_UUID } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_active_conversation( user_email=self.EMAIL )
        self.assertEqual( out[ "active_sender_id" ], "s#abcd1234" )

    async def test_active_conversation_error_500( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_active_conversation( user_email=self.EMAIL )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- get_project_sessions ----
    async def test_project_sessions_user_not_found_404( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", return_value=None ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_project_sessions( project="lupin", user_email=self.EMAIL )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_project_sessions_success( self ):
        recent = datetime.now( timezone.utc )
        repo = Mock(); repo.get_sessions_for_project.return_value = [ { "session_id": "x", "last_activity": recent } ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_project_sessions( project="Lupin", user_email=self.EMAIL )
        self.assertEqual( len( out ), 1 )
        self.assertIsInstance( out[ 0 ][ "last_activity" ], str )

    async def test_project_sessions_error_500( self ):
        with patch( "cosa.rest.user_service.get_user_by_email", side_effect=Exception( "x" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_project_sessions( project="lupin", user_email=self.EMAIL )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- branch-arm fills: hours=None / null last_activity / anchor=None / null created_at ----
    async def test_senders_no_hours_with_null_activity( self ):
        repo = Mock()
        repo.get_sender_last_activities.return_value = [
            { "sender_id": "s1", "last_activity": None },                      # falsy → if-false arm
            { "sender_id": "s2", "last_activity": datetime.now( timezone.utc ) },
        ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_senders_with_activity( user_email=self.EMAIL, hours=None )   # hours None → 1497->1505
        self.assertEqual( len( out ), 2 )
        self.assertIsNone( out[ 0 ][ "last_activity" ] )

    async def test_conversation_no_anchor_null_created( self ):
        n = self._notif(); n.created_at = None        # format_time_display(None) → 1604
        repo = Mock(); repo.get_sender_conversation.return_value = [ n ]
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_sender_conversation( sender_id="s", user_email=self.EMAIL, hours=24, anchor=None )
        self.assertIsNone( out[ 0 ][ "time_display" ] )

    async def test_by_date_no_anchor_null_created( self ):
        n = self._notif(); n.created_at = None
        repo = Mock(); repo.get_sender_conversations_by_date.return_value = { "2026-06-01": [ n ] }
        with self._patch_cfgmgr(), \
             patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_sender_conversation_by_date( sender_id="s", user_email=self.EMAIL,
                                                         hours=168, anchor=None, include_hidden=False )
        self.assertIsNone( out[ "2026-06-01" ][ 0 ][ "time_display" ] )

    async def test_visible_senders_no_exclude_no_hours_null_activity( self ):
        repo = Mock()
        repo.get_sender_last_activities_visible.return_value = [ { "sender_id": "s", "last_activity": None } ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR, "uid": "u1" } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch.object( N, "_voice_persona_for_sender_id", return_value=None ), patch( "builtins.print" ):
            out = await get_visible_senders( user_email=self.EMAIL, hours=None,
                                             include_hidden=False, exclude_own_jobs=False )
        self.assertIsNone( out[ 0 ][ "last_activity" ] )

    async def test_project_sessions_null_activity( self ):
        repo = Mock(); repo.get_sessions_for_project.return_value = [ { "session_id": "x", "last_activity": None } ]
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), patch( "builtins.print" ):
            out = await get_project_sessions( project="lupin", user_email=self.EMAIL )
        self.assertIsNone( out[ 0 ][ "last_activity" ] )


# ===========================================================================
# generate_session_gist
# ===========================================================================
class TestGenerateGist( unittest.IsolatedAsyncioTestCase ):

    async def test_empty_inputs_returns_empty_session( self ):
        out = await generate_session_gist( request_body={ "messages": [], "abstracts": [] } )
        self.assertEqual( out[ "gist" ], "Empty session" )

    async def test_whitespace_only_returns_empty_session( self ):
        out = await generate_session_gist( request_body={ "messages": [ "   " ], "abstracts": [] } )
        self.assertEqual( out[ "gist" ], "Empty session" )

    async def test_success( self ):
        gister = Mock(); gister.get_gist.return_value = "Three Word Gist"
        with patch( "cosa.memory.gister.Gister", return_value=gister ), patch( "builtins.print" ):
            out = await generate_session_gist( request_body={ "messages": [ "fix the bug" ], "abstracts": [ "abc" ] } )
        self.assertEqual( out[ "gist" ], "Three Word Gist" )

    async def test_error_500( self ):
        with patch( "cosa.memory.gister.Gister", side_effect=Exception( "llm down" ) ), patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await generate_session_gist( request_body={ "messages": [ "x" ], "abstracts": [] } )
        self.assertEqual( ctx.exception.status_code, 500 )


# ===========================================================================
# get_undelivered_notifications — HTTPException passthrough (lever-D inbox)
# ===========================================================================
class TestGetUndeliveredNotifications( unittest.IsolatedAsyncioTestCase ):
    """Coverage for the get_undelivered_notifications HTTPException re-raise arm."""

    async def test_http_exception_is_reraised_not_wrapped( self ):
        """
        Ensures an HTTPException raised inside the query block is re-raised verbatim.

        The handler's `except HTTPException: raise` arm must propagate the original
        status code (here 503) rather than masking it as a generic 500 via the
        broad `except Exception` arm below it.
        """
        with patch.object( N, "_undelivered_max_age_hours",
                           side_effect=HTTPException( status_code=503, detail="db unavailable" ) ), \
             patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_undelivered_notifications( authenticated_user_id=UID_STR )
        self.assertEqual( ctx.exception.status_code, 503 )       # re-raised verbatim, NOT wrapped to 500


def isolated_unit_test():
    """
    Run the supplemental notifications-router coverage suite in isolation.

    Ensures:
        - All external collaborators mocked (zero DB/net/LLM/GPU)
        - Deterministic, fast execution

    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    du.print_banner( "Notifications Router — Supplemental Coverage Tests", prepend_nl=True )

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in (
        TestVoicePersonaHelper, TestTimeDateDisplay, TestResolveSenderId,
        TestNotifyUser, TestSubmitResponse, TestSimpleEndpointErrors,
        TestSenderHistoryEndpoints, TestGenerateGist,
    ):
        suite.addTests( loader.loadTestsFromTestCase( cls ) )

    runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
    result = runner.run( suite )
    duration = time.time() - start_time

    success = result.wasSuccessful()
    msg = ( f"All {result.testsRun} tests passed in {duration:.3f}s" if success
            else f"{len( result.failures )} failures, {len( result.errors )} errors of {result.testsRun}" )
    du.print_banner( ( "✅ " if success else "❌ " ) + msg, prepend_nl=True )
    return success, duration, msg


if __name__ == "__main__":
    ok, dur, message = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} notifications coverage suite in {dur:.3f}s: {message}" )
