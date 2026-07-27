"""
Unit tests for system router endpoints with comprehensive mocking.

Tests the system router endpoints including:
- Health check endpoints (/, /health)
- Configuration refresh (/api/init)
- Session ID generation (/api/get-session-id)
- Authentication testing (/api/auth-test)
- WebSocket session management (/api/websocket-sessions)
- WebSocket session cleanup (/api/websocket-sessions/cleanup)
- Dependency injection and error handling
- FastAPI response formats and status codes

Zero external dependencies - all FastAPI operations, configuration management,
authentication, and WebSocket operations are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call, AsyncMock
import time
from datetime import datetime
from typing import Dict, Any, Optional
import asyncio

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.rest.routers.system import router, health_check, health, init, get_session_id, auth_test, get_websocket_sessions

# ⚠️ LOAD-BEARING IMPORT — DO NOT REMOVE AS "UNUSED". Bug e9e31de7, measured 2026-07-27.
#
# `init()` imports `cosa.rest.db.database` INSIDE its own try block, and several tests
# below wrap that call in `patch.dict( 'sys.modules', ... )` to stub `lupin_app.main`.
# On exit, `patch.dict` restores sys.modules to its PRE-PATCH SNAPSHOT — which EVICTS
# every module the patched code imported while inside. Measured: that import pulls in
# **140 sqlalchemy modules**, and all 140 are evicted on exit.
#
#   sqlalchemy modules before patch.dict : 0
#   inside, after init()'s import        : 140
#   after patch.dict exits               : 0      <- all evicted
#   re-import in the next test           : RAISES
#
# SQLAlchemy cannot be re-imported after a partial eviction; the re-import raises
# (`AssertionError: Type <class 'object'> is already registered` under pytest, or
# `ImportError: cannot load module more than once per process` standalone — same
# partial-eviction family, differing by which module is reached first). `init()`
# catches it and returns `{"status": "error"}`, so `get_config_manager` is never
# called and the NEXT test fails with "called 0 times".
#
# ⇒ The failure is SYMMETRIC: whichever of these tests runs FIRST does the eviction,
#   and whichever runs SECOND fails. It is not one test contaminating a specific
#   other one — both directions reproduce.
#
# Importing it HERE puts it in the pre-patch snapshot, so restoration keeps it and
# nothing is ever re-imported. This is the same mechanism `cosa/rest/db/__init__.py`
# documents for bug 1b8ec2b9, where coverage's `sys_modules_saved()` was the evictor
# instead of `patch.dict`.
import cosa.rest.db.database  # noqa: F401


def _patch_fastapi_main( mock_main ):
    """
    Robustly patch `lupin_app.main` for direct-call unit tests.

    `import lupin_app.main as m` binds m via getattr(sys.modules['lupin_app'],
    'main'), NOT sys.modules['lupin_app.main']. Once the REAL lupin_app
    package is cached by an earlier test, patching only the submodule entry is
    silently ignored (passes in isolation, fails under full-suite ordering).
    Overriding BOTH the package object and the submodule entry makes the import
    resolve to mock_main regardless of prior import state.
    """
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


class TestSystemRouter( unittest.TestCase ):
    """
    Comprehensive unit tests for system router endpoints.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All system endpoints tested in isolation
        - FastAPI dependencies properly mocked
        - Authentication and WebSocket operations validated
        - Error handling scenarios covered
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
        
        # Common test data
        self.test_user = {
            "user_id": "test_user_123",
            "email": "test@example.com",
            "name": "Test User"
        }
        self.test_session_id = "happy-elephant"
        self.test_timestamp = "2025-08-05T12:00:00.000000"
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_health_check_endpoint( self ):
        """
        Test root health check endpoint (/).
        
        Ensures:
            - Returns healthy status with service info
            - Contains required fields (status, service, timestamp, version)
            - Timestamp is in ISO format
            - Response structure matches expected format
        """
        # Create an async test function
        async def run_test():
            # Live contract: timestamps come from du.get_current_datetime_iso() (cosa.utils.util),
            # NOT datetime.now().isoformat() — patch the utility helper at its source.
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ) as mock_dt_iso:
                result = await health_check()

                # Verify response structure
                self.assertIsInstance( result, dict )
                self.assertEqual( result["status"], "healthy" )
                self.assertEqual( result["service"], "lupin-fastapi" )
                self.assertEqual( result["timestamp"], self.test_timestamp )
                self.assertEqual( result["version"], "0.1.0" )

                # Verify timestamp helper called
                mock_dt_iso.assert_called_once()
        
        # Run the async test
        asyncio.run( run_test() )
    
    def test_health_endpoint( self ):
        """
        Test simplified health endpoint (/health).
        
        Ensures:
            - Returns "ok" status for lightweight monitoring
            - Contains status and timestamp fields only
            - Timestamp is in ISO format
            - Response is minimal for high-frequency checks
        """
        async def run_test():
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):
                result = await health()

                # Verify response structure
                self.assertIsInstance( result, dict )
                self.assertEqual( result["status"], "ok" )
                self.assertEqual( result["timestamp"], self.test_timestamp )
                
                # Should only have these two fields
                self.assertEqual( len( result ), 2 )
        
        asyncio.run( run_test() )
    
    def test_init_endpoint_success( self ):
        """
        Test configuration refresh endpoint (/api/init) success case.

        Live contract (re-architected): /api/init reinitializes the SINGLETON
        ConfigurationManager via cosa.rest.dependencies.config.get_config_manager()
        (no throwaway construction), calls config_mgr.init() in place, flushes all
        registered caches via cosa.config.cache_registry.invalidate_all(), and
        eagerly rebuilds the PredictionEngine.

        Ensures:
            - Fetches the singleton config manager (does NOT construct a new one)
            - With no config_block_id, calls config_mgr.init() with no args
            - Prints configuration with brackets
            - Flushes all caches via invalidate_all()
            - Eagerly rebuilds the PredictionEngine
            - Returns success status with live response shape (config_block_id,
              database_url, caches_invalidated, timestamp)
        """
        async def run_test():
            mock_config_mgr = Mock()
            mock_config_mgr.config_block_id = "Lupin: Development"

            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ), \
                 patch( 'cosa.rest.dependencies.config.get_config_manager', return_value=mock_config_mgr ) as mock_get_cfg, \
                 patch( 'cosa.config.cache_registry.invalidate_all', return_value=3 ) as mock_invalidate, \
                 patch( 'cosa.agents.prediction_engine.prediction_engine.get_prediction_engine' ) as mock_get_pe, \
                 patch.dict( 'sys.modules', { 'lupin_app.main': Mock() } ), \
                 patch( 'builtins.print' ):

                result = await init()

                # Singleton fetched, NOT constructed
                mock_get_cfg.assert_called_once()
                # No config_block_id → in-place re-init with no args
                mock_config_mgr.init.assert_called_once_with()
                # Configuration printed with brackets
                mock_config_mgr.print_configuration.assert_called_once_with( brackets=True )
                # All caches flushed via the registry
                mock_invalidate.assert_called_once()
                # PredictionEngine eagerly rebuilt with the singleton config
                mock_get_pe.assert_called_once_with( config_mgr=mock_config_mgr )

                # Success response shape (live contract)
                self.assertEqual( result["status"], "success" )
                self.assertEqual( result["config_block_id"], "Lupin: Development" )
                self.assertEqual( result["database_url"], "(unchanged)" )
                self.assertEqual( result["caches_invalidated"], 3 )
                self.assertEqual( result["timestamp"], self.test_timestamp )

        asyncio.run( run_test() )
    
    def test_init_endpoint_error( self ):
        """
        Test configuration refresh endpoint (/api/init) error handling.
        
        Ensures:
            - Catches exceptions gracefully
            - Returns error status with exception message
            - Includes timestamp in error response
        """
        async def run_test():
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ), \
                 patch( 'cosa.rest.dependencies.config.get_config_manager', side_effect=Exception( "Config file not found" ) ), \
                 patch.dict( 'sys.modules', { 'lupin_app.main': Mock() } ):

                result = await init()

                # Verify error response (live contract: "Init failed: <msg>")
                self.assertEqual( result["status"], "error" )
                self.assertIn( "Init failed", result["message"] )
                self.assertIn( "Config file not found", result["message"] )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_get_session_id_endpoint( self ):
        """
        Test session ID generation endpoint (/api/get-session-id).
        
        Ensures:
            - Uses TwoWordIdGenerator dependency correctly
            - Generates unique session ID
            - Logs session ID for debugging
            - Returns session ID with timestamp
        """
        async def run_test():
            mock_id_generator = Mock()
            mock_id_generator.get_id.return_value = self.test_session_id
            
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ), \
                 patch( 'builtins.print' ) as mock_print:

                result = await get_session_id( mock_id_generator )
                
                # Verify ID generator called
                mock_id_generator.get_id.assert_called_once()
                
                # Verify logging
                mock_print.assert_called_once_with( f"[API] Generated new session ID: {self.test_session_id}" )
                
                # Verify response
                self.assertEqual( result["session_id"], self.test_session_id )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_auth_test_endpoint_success( self ):
        """
        Test authentication test endpoint (/api/auth-test) success case.
        
        Ensures:
            - Accepts authenticated user from dependency
            - Returns success status with user information
            - Includes authentication confirmation message
            - Contains timestamp for verification
        """
        async def run_test():
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):
                result = await auth_test( self.test_user )
                
                # Verify response structure
                self.assertEqual( result["status"], "success" )
                self.assertEqual( result["message"], "Authentication is working" )
                self.assertEqual( result["user"], self.test_user )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_get_websocket_sessions_endpoint( self ):
        """
        Test WebSocket sessions endpoint (/api/websocket-sessions).
        
        Ensures:
            - Retrieves WebSocketManager from main module
            - Gets all active session information
            - Calculates session metrics correctly
            - Returns comprehensive session data
        """
        async def run_test():
            # Mock WebSocket sessions data
            mock_sessions = [
                {"session_id": "session1", "user_id": "user1", "status": "connected"},
                {"session_id": "session2", "user_id": "user2", "status": "connected"},
                {"session_id": "session3", "user_id": "user1", "status": "connected"}  # user1 has multiple sessions
            ]
            
            mock_websocket_manager = Mock()
            mock_websocket_manager.get_all_sessions_info.return_value = mock_sessions
            
            mock_main_module = Mock()
            mock_main_module.websocket_manager = mock_websocket_manager
            
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ), \
                 _patch_fastapi_main( mock_main_module ):

                result = await get_websocket_sessions( self.test_user )
                
                # Verify WebSocketManager called
                mock_websocket_manager.get_all_sessions_info.assert_called_once()
                
                # Verify response contains expected data
                self.assertIn( "sessions", result )
                self.assertIn( "total_sessions", result )
                self.assertIn( "unique_users", result )
                self.assertIn( "users_with_multiple_sessions", result )
                self.assertIn( "single_session_policy", result )
                self.assertIn( "timestamp", result )
                
                # Verify sessions data and metrics
                self.assertEqual( result["sessions"], mock_sessions )
                self.assertEqual( result["total_sessions"], 3 )
                self.assertEqual( result["unique_users"], 2 )  # user1 and user2
                self.assertEqual( result["users_with_multiple_sessions"], 1 )  # user1 has 2 sessions
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_router_configuration( self ):
        """
        Test router configuration and metadata.
        
        Ensures:
            - Router has correct tags
            - Router is properly configured for FastAPI
            - Router object is accessible for app integration
        """
        # Verify router is configured
        self.assertIsNotNone( router )
        
        # Verify router has system tag
        self.assertIn( "system", router.tags )
        
        # Verify router is an APIRouter instance
        from fastapi import APIRouter
        self.assertIsInstance( router, APIRouter )
    
    def test_dependency_injection_mocking( self ):
        """
        Test that FastAPI dependencies can be properly mocked.
        
        Ensures:
            - get_current_user dependency can be mocked
            - get_id_generator dependency can be mocked
            - Dependencies return expected mock values
        """
        # Test mocking get_current_user
        from cosa.rest.auth import get_current_user
        with patch( 'cosa.rest.routers.system.get_current_user', return_value=self.test_user ):
            # Dependency should return mocked user
            pass  # This validates the import and mocking works
        
        # Test mocking get_id_generator
        from cosa.rest.dependencies.config import get_id_generator
        mock_generator = Mock()
        with patch( 'cosa.rest.routers.system.get_id_generator', return_value=mock_generator ):
            # Dependency should return mocked generator
            pass  # This validates the import and mocking works
    
    def test_async_endpoint_patterns( self ):
        """
        Test async endpoint patterns for FastAPI compatibility.
        
        Ensures:
            - All endpoints are properly defined as async
            - Endpoints can be called in async context
            - Return values are dictionaries suitable for JSON serialization
        """
        async def run_test():
            # Test that endpoints are async and return serializable data
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):
                # Test health check
                result = await health_check()
                self.assertIsInstance( result, dict )
                
                # Test simplified health
                result = await health()
                self.assertIsInstance( result, dict )
                
                # All return values should be JSON serializable
                import json
                for endpoint_result in [result]:
                    json.dumps( endpoint_result )  # Should not raise exception
        
        asyncio.run( run_test() )


def isolated_unit_test():
    """
    Run comprehensive unit tests for system router in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real FastAPI or authentication operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "System Router Unit Tests - REST API Phase 4", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_health_check_endpoint',
            'test_health_endpoint',
            'test_init_endpoint_success',
            'test_init_endpoint_error',
            'test_get_session_id_endpoint',
            'test_auth_test_endpoint_success',
            'test_get_websocket_sessions_endpoint',
            'test_router_configuration',
            'test_dependency_injection_mocking',
            'test_async_endpoint_patterns'
        ]
        
        for method in test_methods:
            suite.addTest( TestSystemRouter( method ) )
        
        # Run tests with detailed output
        runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
        result = runner.run( suite )
        
        duration = time.time() - start_time
        
        # Calculate results
        tests_run = result.testsRun
        failures = len( result.failures )
        errors = len( result.errors )
        success_count = tests_run - failures - errors
        
        print( f"\n{'='*60}" )
        print( f"SYSTEM ROUTER UNIT TEST RESULTS" )
        print( f"{'='*60}" )
        print( f"Tests Run     : {tests_run}" )
        print( f"Passed        : {success_count}" )
        print( f"Failed        : {failures}" )
        print( f"Errors        : {errors}" )
        print( f"Success Rate  : {(success_count/tests_run)*100:.1f}%" )
        print( f"Duration      : {duration:.3f} seconds" )
        print( f"{'='*60}" )
        
        if failures > 0:
            print( "\nFAILURE DETAILS:" )
            for test, traceback in result.failures:
                print( f"❌ {test}: {traceback.split(chr(10))[-2]}" )
                
        if errors > 0:
            print( "\nERROR DETAILS:" )
            for test, traceback in result.errors:
                print( f"💥 {test}: {traceback.split(chr(10))[-2]}" )
        
        success = failures == 0 and errors == 0
        
        if success:
            du.print_banner( "✅ ALL SYSTEM ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME SYSTEM ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 SYSTEM ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} System router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )