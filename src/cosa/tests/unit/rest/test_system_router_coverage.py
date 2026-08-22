#!/usr/bin/env python3
"""
Supplemental unit tests — `cosa.rest.routers.system` coverage closure.

Complements `test_system_router.py` (health / init-success+error / session-id /
auth-test / websocket-sessions). This file closes the remaining gap:

    - `get_todo_queue` dependency (G1 dual-key lupin_app.main),
    - `get_server_info` (masked DB url, password present + None),
    - `init` with config_block_id (block-swap path) + PredictionEngine
      eager-rebuild exception arm,
    - `reset_prediction_engine` (drop / no-drop / drop-error / drop_table=False /
      outer-exception),
    - `get_websocket_sessions` falsy-user_id loop arm,
    - `cleanup_stale_sessions`,
    - `get_websocket_state` (incl. orphaned-user + unmapped-session diagnostics),
    - `get_client_config` (TEST + DEVELOPMENT env labels),
    - `get_similarity_confirmation` / `set_similarity_confirmation`,
    - `code_identity` (the last uncovered line in the module).

Boundary-mock discipline: `lupin_app.main` is patched DUAL-KEY (G1);
ConfigurationManager / PredictionEngine / lancedb / db engine / get_config_manager
/ invalidate_all are all patched so NO real DB, LanceDB index, config file, or
PredictionEngine cold-start runs. ZERO GPU, ZERO network, ZERO spend.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure \
     src/cosa/.venv/bin/python -m pytest \
     src/cosa/tests/unit/rest/test_system_router_coverage.py -v
"""

import sys
import unittest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

from cosa.rest.routers.system import (
    get_todo_queue,
    get_server_info,
    init,
    reset_prediction_engine,
    get_websocket_sessions,
    cleanup_stale_sessions,
    get_websocket_state,
    get_client_config,
    get_similarity_confirmation,
    set_similarity_confirmation,
    code_identity,
    SimilarityConfirmationRequest,
)

_TS = "2026-01-01T12:00:00"


def _patch_fastapi_main( mock_main ):
    """G1 DUAL-KEY patch (see test_system_router._patch_fastapi_main)."""
    pkg      = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


class TestGetTodoQueue( unittest.TestCase ):
    """
    Exercises the `get_todo_queue` dependency.

    Ensures:
        - returns main_module.jobs_todo_queue when lupin_app.main is importable
    """

    def test_returns_main_module_queue( self ):
        main = Mock()
        main.jobs_todo_queue = "THE_QUEUE"
        with _patch_fastapi_main( main ):
            self.assertEqual( get_todo_queue(), "THE_QUEUE" )


class _FakeURL:
    """Stand-in for a SQLAlchemy URL — str() yields a DSN, .password set per-test."""
    def __init__( self, password ):
        self.password = password
    def __str__( self ):
        return "postgresql://user:secret@host:5432/lupin"


class TestGetServerInfo( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises `get_server_info`.

    Ensures:
        - returns config_block_id, masked database_url, and environment
        - password is masked when present; the `or ""` arm is taken when None
    """

    async def test_masks_password_present( self ):
        cfg = Mock()
        cfg.config_block_id = "Lupin: Development"
        engine = Mock()
        engine.url = _FakeURL( password="secret" )
        with patch( "cosa.rest.db.database.engine", engine ), \
             patch.dict( "os.environ", { "LUPIN_ENV": "Development" } ):
            result = await get_server_info( config_mgr=cfg )
        self.assertEqual( result[ "config_block_id" ], "Lupin: Development" )
        self.assertNotIn( "secret", result[ "database_url" ] )
        self.assertIn( "***", result[ "database_url" ] )
        self.assertEqual( result[ "environment" ], "development" )

    async def test_password_none_arm( self ):
        cfg = Mock()
        cfg.config_block_id = "Lupin: Production"
        engine = Mock()
        engine.url = _FakeURL( password=None )         # → `str( None or "" )`
        with patch( "cosa.rest.db.database.engine", engine ), \
             patch.dict( "os.environ", { "LUPIN_ENV": "production" } ):
            result = await get_server_info( config_mgr=cfg )
        self.assertEqual( result[ "environment" ], "production" )


class TestInitWithBlockId( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises `init` config_block_id swap path + PE eager-rebuild exception arm.

    Ensures:
        - a config_block_id triggers in-place re-init + swap_database
        - a PredictionEngine rebuild failure is caught and noted (init still ok)
    """

    async def test_block_id_swap( self ):
        cfg = Mock()
        cfg.config_block_id = "Lupin: Testing"
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "cosa.rest.dependencies.config.get_config_manager", return_value=cfg ), \
             patch( "cosa.rest.db.database.swap_database", return_value="postgresql://test" ) as mk_swap, \
             patch( "cosa.config.cache_registry.invalidate_all", return_value=2 ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.get_prediction_engine" ), \
             patch.dict( "sys.modules", { "lupin_app.main": Mock() } ), \
             patch( "builtins.print" ):
            result = await init( config_block_id="Lupin: Testing" )
        cfg.init.assert_called_once_with( config_block_id="Lupin: Testing" )
        mk_swap.assert_called_once_with( "testing" )
        self.assertEqual( result[ "status" ], "success" )
        self.assertEqual( result[ "database_url" ], "postgresql://test" )

    async def test_block_id_with_plus_encoding_and_pe_rebuild_failure( self ):
        cfg = Mock()
        cfg.config_block_id = "Lupin: Development"
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "cosa.rest.dependencies.config.get_config_manager", return_value=cfg ), \
             patch( "cosa.rest.db.database.swap_database", return_value="db" ), \
             patch( "cosa.config.cache_registry.invalidate_all", return_value=0 ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.get_prediction_engine",
                    side_effect=Exception( "PE boom" ) ), \
             patch.dict( "sys.modules", { "lupin_app.main": Mock() } ), \
             patch( "builtins.print" ) as mk_print:
            # "+" in the block id is decoded to a space before env lookup
            result = await init( config_block_id="Lupin:+Development" )
        cfg.init.assert_called_once_with( config_block_id="Lupin: Development" )
        self.assertEqual( result[ "status" ], "success" )   # PE failure swallowed
        self.assertTrue( any( "PredictionEngine eager-rebuild" in str( c )
                              for c in mk_print.call_args_list ) )


class TestResetPredictionEngine( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises `reset_prediction_engine` across its clear/skip/error matrix.

    Boundary-mock: ConfigurationManager, PredictionEngine, get_prediction_engine
    and the DB session are patched — nothing real is opened.

    Ensures:
        - drop_table=True clears the pgvector rows
        - a DB error is caught (clear note) without failing the reset
        - drop_table=False skips the clear block entirely
        - an outer exception returns the error response shape
    """

    def _common_patches( self, pe_side_effect=None ):
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, **kw: "prediction_decisions"
        engine = Mock()
        engine.lancedb_table = "prediction_decisions"
        pe_cls = Mock()
        get_pe = Mock( return_value=engine, side_effect=pe_side_effect )
        return cfg, pe_cls, get_pe

    async def test_drop_table_false_skips_block( self ):
        cfg, pe_cls, get_pe = self._common_patches()
        with patch( "cosa.rest.routers.system.ConfigurationManager", return_value=cfg ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.PredictionEngine", pe_cls ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.get_prediction_engine", get_pe ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ):
            result = await reset_prediction_engine( drop_table=False )
        self.assertEqual( result[ "status" ], "success" )
        self.assertFalse( result[ "table_dropped" ] )

    async def test_outer_exception_returns_error( self ):
        with patch( "cosa.rest.routers.system.ConfigurationManager", side_effect=Exception( "cfg boom" ) ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ):
            result = await reset_prediction_engine( drop_table=True )
        self.assertEqual( result[ "status" ], "error" )
        self.assertIn( "PredictionEngine reset failed", result[ "message" ] )


    async def test_postgres_backend_clears_rows( self ):
        import contextlib
        cfg, pe_cls, get_pe = self._common_patches()
        session   = Mock()
        repo_inst = Mock()

        @contextlib.contextmanager
        def fake_get_db():
            yield session

        with patch( "cosa.rest.routers.system.ConfigurationManager", return_value=cfg ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.PredictionEngine", pe_cls ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.get_prediction_engine", get_pe ), \
             patch( "cosa.rest.db.database.get_db", fake_get_db ), \
             patch( "cosa.rest.db.repositories.prediction_decision_repository.PredictionDecisionRepository",
                    return_value=repo_inst ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ):
            result = await reset_prediction_engine( drop_table=True )
        repo_inst.delete_all.assert_called_once()
        self.assertEqual( result[ "status" ], "success" )
        self.assertTrue( result[ "table_dropped" ] )

    async def test_postgres_backend_clear_error_swallowed( self ):
        cfg, pe_cls, get_pe = self._common_patches()

        def boom_get_db():
            raise RuntimeError( "pg down" )

        with patch( "cosa.rest.routers.system.ConfigurationManager", return_value=cfg ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.PredictionEngine", pe_cls ), \
             patch( "cosa.agents.prediction_engine.prediction_engine.get_prediction_engine", get_pe ), \
             patch( "cosa.rest.db.database.get_db", boom_get_db ), \
             patch( "builtins.print" ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ):
            result = await reset_prediction_engine( drop_table=True )
        self.assertEqual( result[ "status" ], "success" )      # non-fatal
        self.assertFalse( result[ "table_dropped" ] )


class TestWebsocketSessionsFalsyUser( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises `get_websocket_sessions` falsy-user_id loop arm.

    Ensures:
        - a session whose user_id is missing/None is excluded from user metrics
          (the `if user_id:` false branch is taken)
    """

    async def test_session_without_user_id( self ):
        sessions = [
            { "session_id": "s1", "user_id": "u1" },
            { "session_id": "s2" },                     # no user_id → falsy arm
            { "session_id": "s3", "user_id": None },    # None → falsy arm
        ]
        wsm = Mock()
        wsm.get_all_sessions_info.return_value = sessions
        wsm.single_session_per_user = True
        main = Mock()
        main.websocket_manager = wsm
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             _patch_fastapi_main( main ):
            result = await get_websocket_sessions( { "user_id": "admin" } )
        self.assertEqual( result[ "total_sessions" ], 3 )
        self.assertEqual( result[ "unique_users" ], 1 )    # only u1 counts


class TestCleanupStaleSessions( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises `cleanup_stale_sessions`.

    Ensures:
        - delegates to websocket_manager.cleanup_stale_sessions and echoes count + age
    """

    async def test_cleanup( self ):
        wsm = Mock()
        wsm.cleanup_stale_sessions.return_value = 4
        main = Mock()
        main.websocket_manager = wsm
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             _patch_fastapi_main( main ):
            result = await cleanup_stale_sessions( max_age_hours=12, current_user={ "user_id": "admin" } )
        wsm.cleanup_stale_sessions.assert_called_once_with( 12 )
        self.assertEqual( result[ "sessions_cleaned" ], 4 )
        self.assertEqual( result[ "max_age_hours" ], 12 )


class TestGetWebsocketState( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises `get_websocket_state` diagnostics.

    Ensures:
        - returns internal-state mappings and diagnostics
        - an unmapped (unauthenticated) session is reported
        - an orphaned user mapping (sessions all inactive) is detected
    """

    async def test_full_state_with_orphan_and_unmapped( self ):
        wsm = Mock()
        wsm.active_connections = { "wise penguin": object(), "faithful zebra": object() }
        wsm.session_to_user    = { "wise penguin": "user_a" }          # zebra unmapped
        wsm.user_sessions      = { "user_a": [ "wise penguin" ], "user_dead": [ "gone session" ] }
        wsm.session_subscriptions = { "wise penguin": [ "*" ] }
        wsm.session_timestamps = { "wise penguin": datetime( 2026, 1, 1, 9, 0, 0 ) }
        wsm.single_session_per_user = False
        main = Mock()
        main.websocket_manager = wsm
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             _patch_fastapi_main( main ):
            result = await get_websocket_state()
        diag = result[ "diagnostics" ]
        self.assertIn( "faithful zebra", diag[ "unmapped_sessions" ] )
        self.assertIn( "user_dead", diag[ "orphaned_user_mappings" ] )
        self.assertEqual( diag[ "authenticated_sessions" ], 1 )
        self.assertEqual( result[ "session_timestamps" ][ "wise penguin" ], "2026-01-01T09:00:00" )


class TestGetClientConfig( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises `get_client_config` for both env-label branches.

    Ensures:
        - config values are fetched + unit-converted
        - LUPIN_ENV in {test,testing} → env_label TEST; otherwise DEVELOPMENT
    """

    def _cfg( self ):
        cfg = Mock()
        # return the per-call default so int()/float() conversions get valid types
        cfg.get.side_effect = lambda key, default=None, return_type=None: default
        return cfg

    async def test_test_env_label( self ):
        with patch( "cosa.rest.routers.system.ConfigurationManager", return_value=self._cfg() ), \
             patch.dict( "os.environ", { "LUPIN_ENV": "testing" } ):
            result = await get_client_config( user_id="u1" )
        self.assertEqual( result[ "env_label" ], "TEST" )
        self.assertEqual( result[ "token_refresh_check_interval_ms" ], 10 * 60 * 1000 )
        self.assertEqual( result[ "token_expiry_threshold_secs" ], 5 * 60 )

    async def test_development_env_label( self ):
        with patch( "cosa.rest.routers.system.ConfigurationManager", return_value=self._cfg() ), \
             patch.dict( "os.environ", { "LUPIN_ENV": "" } ):
            result = await get_client_config( user_id="u1" )
        self.assertEqual( result[ "env_label" ], "DEVELOPMENT" )
        self.assertEqual( result[ "app timezone" ], "America/New_York" )


class TestSimilarityConfirmation( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises the similarity-confirmation toggle get/set endpoints.

    Ensures:
        - GET returns the queue config's current enabled state
        - POST writes the new value and returns new + previous
    """

    async def test_get( self ):
        tq = Mock()
        tq.config_mgr.get.return_value = True
        result = await get_similarity_confirmation( current_user={ "u": 1 }, todo_queue=tq )
        self.assertEqual( result, { "enabled": True } )

    async def test_set( self ):
        tq = Mock()
        tq.config_mgr.get.return_value = False   # previous
        body = SimilarityConfirmationRequest( enabled=True )
        result = await set_similarity_confirmation( body=body, current_user={ "u": 1 }, todo_queue=tq )
        tq.config_mgr.set_config.assert_called_once_with( "similarity confirmation enabled", "true" )
        self.assertEqual( result, { "enabled": True, "previous": False } )


class TestCodeIdentity( unittest.IsolatedAsyncioTestCase ):
    """
    Ensures:
        - `code_identity` hands back the record captured at MODULE IMPORT and does
          not re-read the repository per request.

    This was the module's last uncovered line. It is worth a real test rather than
    a pragma: the endpoint exists to answer "which code is this process running?",
    and a per-request re-read would reproduce exactly the lie it was built to
    remove. A test that only checked the response shape would pass either way, so
    this one pins the delegation instead.
    """

    async def test_it_returns_the_captured_record( self ):
        """
        Ensures:
            - the endpoint returns get_code_identity()'s value unchanged.

        RED ON REVERT: have the endpoint build its own dict, or re-read git, and
        the returned object stops being the one the module captured.
        """
        record = { "git_sha": "deadbeef", "git_branch": "wt-brain-lane-a",
                   "git_sha_source": "test", "imported_at": _TS, "pid": 1234 }
        with patch( "cosa.rest.routers.system.get_code_identity", return_value=record ) as spy:
            result = await code_identity()
        spy.assert_called_once_with()
        self.assertIs( result, record )

    async def test_it_does_not_re_read_per_request( self ):
        """
        Ensures:
            - two calls return the SAME object, so the endpoint cannot be quietly
              turned into a per-request repository read without this failing.
        """
        record = { "git_sha": "deadbeef", "imported_at": _TS, "pid": 1234 }
        with patch( "cosa.rest.routers.system.get_code_identity", return_value=record ):
            first  = await code_identity()
            second = await code_identity()
        self.assertIs( first, second )


def isolated_unit_test():
    """
    Run this module's tests in isolation.

    Ensures:
        - returns True when all tests pass, False otherwise
    """
    suite  = unittest.TestLoader().loadTestsFromModule( sys.modules[ __name__ ] )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    return result.wasSuccessful()


if __name__ == "__main__":
    isolated_unit_test()
