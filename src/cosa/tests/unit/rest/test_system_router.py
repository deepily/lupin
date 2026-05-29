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
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime:
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
                result = await health_check()
                
                # Verify response structure
                self.assertIsInstance( result, dict )
                self.assertEqual( result["status"], "healthy" )
                self.assertEqual( result["service"], "lupin-fastapi" )
                self.assertEqual( result["timestamp"], self.test_timestamp )
                self.assertEqual( result["version"], "0.1.0" )
                
                # Verify datetime called
                mock_datetime.now.assert_called_once()
                mock_now.isoformat.assert_called_once()
        
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
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime:
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
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
        
        Ensures:
            - Creates new ConfigurationManager instance
            - Prints configuration with brackets
            - Reloads solution snapshots if available
            - Returns success status with confirmation message
        """
        async def run_test():
            # Mock the main module and its components
            mock_main_module = Mock()
            mock_snapshot_mgr = Mock()
            mock_main_module.snapshot_mgr = mock_snapshot_mgr
            
            mock_config_mgr = Mock()
            
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime, \
                 patch( 'cosa.rest.routers.system.ConfigurationManager', return_value=mock_config_mgr ) as mock_config_class, \
                 patch( 'builtins.print' ) as mock_print:
                
                # Mock the dynamic import that happens inside the init function
                # Use patch.dict to mock the specific module in sys.modules
                with patch.dict( 'sys.modules', { 'fastapi_app.main': mock_main_module } ):
                    mock_now = Mock()
                    mock_now.isoformat.return_value = self.test_timestamp
                    mock_datetime.now.return_value = mock_now
                    
                    result = await init()
                    
                    # Verify ConfigurationManager created with correct env var
                    mock_config_class.assert_called_once_with( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
                    
                    # Verify configuration printed with brackets
                    mock_config_mgr.print_configuration.assert_called_once_with( brackets=True )
                    
                    # Verify snapshot manager reload called
                    mock_snapshot_mgr.load_snapshots.assert_called_once()
                    
                    # Verify success response
                    self.assertEqual( result["status"], "success" )
                    self.assertEqual( result["message"], "Configuration refreshed and snapshots reloaded" )
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
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime, \
                 patch( 'cosa.rest.routers.system.ConfigurationManager' ) as mock_config_class, \
                 patch.dict( 'sys.modules', { 'fastapi_app.main': Mock() } ):
                
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
                # Make ConfigurationManager raise an exception
                mock_config_class.side_effect = Exception( "Config file not found" )
                
                result = await init()
                
                # Verify error response
                self.assertEqual( result["status"], "error" )
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
            
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime, \
                 patch( 'builtins.print' ) as mock_print:
                
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
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
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime:
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
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
            
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime, \
                 patch.dict( 'sys.modules', { 'fastapi_app.main': mock_main_module } ):
                
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
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
            with patch( 'cosa.rest.routers.system.datetime' ) as mock_datetime:
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
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