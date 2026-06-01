"""
Unit tests for WebSocket admin router endpoints with comprehensive mocking.

Tests the WebSocket admin router endpoints including:
- WebSocket session listing and management
- WebSocket connection statistics and metrics
- Session cleanup operations and validation
- Individual session information retrieval
- WebSocket session disconnection capabilities
- Single-session policy configuration
- Available WebSocket events introspection
- Dependency injection and error handling
- FastAPI response formats and authentication

Zero external dependencies - all FastAPI operations, WebSocket management,
authentication, and WebSocket manager operations are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call, AsyncMock
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import asyncio

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.rest.routers.websocket_admin import router, get_websocket_sessions, get_websocket_stats, cleanup_websocket_sessions
from cosa.rest.routers.websocket_admin import get_websocket_session, disconnect_websocket_session, update_single_session_policy, get_available_events
from cosa.rest.routers.websocket_admin import get_websocket_manager


def _patch_fastapi_main( mock_main ):
    """
    Robustly patch `fastapi_app.main` for direct-call unit tests.

    `import fastapi_app.main as m` binds m via getattr(sys.modules['fastapi_app'],
    'main'), NOT sys.modules['fastapi_app.main']. Once the REAL fastapi_app
    package is cached by an earlier test, patching only the submodule entry is
    silently ignored (passes in isolation, fails under full-suite ordering).
    Overriding BOTH the package object and the submodule entry makes the import
    resolve to mock_main regardless of prior import state.
    """
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )


class TestWebSocketAdminRouter( unittest.TestCase ):
    """
    Comprehensive unit tests for WebSocket admin router endpoints.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All WebSocket admin endpoints tested in isolation
        - WebSocket manager operations properly mocked
        - Authentication and session management validated
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
            "uid": "test_user_123",
            "email": "test@example.com",
            "name": "Test User"
        }
        self.test_session_id = "happy-elephant"
        self.test_timestamp = "2025-08-05T12:00:00.000000"
        
        # Mock session data
        self.test_sessions = [
            {
                "session_id": "session1",
                "user_id": "user1",
                "status": "connected",
                "connection_time": "2025-08-05T11:00:00"
            },
            {
                "session_id": "session2", 
                "user_id": "user2",
                "status": "connected",
                "connection_time": "2025-08-05T11:30:00"
            }
        ]
        
        self.test_subscription_stats = {
            "queue_update": 2,
            "notification": 1,
            "audio_streaming": 1
        }
        
        self.test_available_events = ["queue_update", "notification", "audio_streaming", "sys_ping"]
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mock_websocket_manager( self ):
        """
        Helper to create mock WebSocket manager with standard methods.
        
        Returns:
            Mock WebSocket manager object
        """
        mock_manager = Mock()
        mock_manager.get_all_sessions_info.return_value = self.test_sessions
        mock_manager.user_sessions = {"user1": ["session1"], "user2": ["session2"]}
        mock_manager.get_subscription_stats.return_value = self.test_subscription_stats
        mock_manager.get_connection_count.return_value = len( self.test_sessions )
        mock_manager.cleanup_stale_sessions.return_value = 1
        mock_manager.get_session_info.return_value = self.test_sessions[0]
        mock_manager.is_connected.return_value = True
        mock_manager.disconnect = Mock()
        mock_manager.set_single_session_policy = Mock()
        mock_manager.available_events = set( self.test_available_events )
        
        return mock_manager
    
    def test_get_websocket_sessions_success( self ):
        """
        Test WebSocket sessions listing endpoint success case.
        
        Ensures:
            - Retrieves all active WebSocket sessions
            - Calculates session and user counts correctly
            - Returns proper response format with timestamp
        """
        async def run_test():
            mock_websocket_manager = self._create_mock_websocket_manager()
            
            # Live contract: timestamps come from du.get_current_datetime_iso() (cosa.utils.util).
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):

                result = await get_websocket_sessions(
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
                
                # Verify WebSocket manager called
                mock_websocket_manager.get_all_sessions_info.assert_called_once()
                
                # Verify response structure
                self.assertEqual( result["total_sessions"], len( self.test_sessions ) )
                self.assertEqual( result["total_users"], len( mock_websocket_manager.user_sessions ) )
                self.assertEqual( result["sessions"], self.test_sessions )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_get_websocket_stats_success( self ):
        """
        Test WebSocket statistics endpoint success case.
        
        Ensures:
            - Retrieves connection and subscription statistics
            - Returns comprehensive metrics with proper format
            - Includes timestamp for monitoring
        """
        async def run_test():
            mock_websocket_manager = self._create_mock_websocket_manager()
            
            # Live contract: timestamps come from du.get_current_datetime_iso() (cosa.utils.util).
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):

                result = await get_websocket_stats(
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
                
                # Verify WebSocket manager methods called
                mock_websocket_manager.get_subscription_stats.assert_called_once()
                mock_websocket_manager.get_connection_count.assert_called_once()
                
                # Verify response structure
                self.assertEqual( result["connection_count"], len( self.test_sessions ) )
                self.assertEqual( result["user_count"], len( mock_websocket_manager.user_sessions ) )
                self.assertEqual( result["subscription_stats"], self.test_subscription_stats )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_cleanup_websocket_sessions_success( self ):
        """
        Test WebSocket session cleanup endpoint success case.
        
        Ensures:
            - Validates max_age_hours parameter
            - Calls cleanup with correct age limit
            - Returns cleanup results with confirmation
        """
        async def run_test():
            mock_websocket_manager = self._create_mock_websocket_manager()
            max_age_hours = 48
            
            # Live contract: timestamps come from du.get_current_datetime_iso() (cosa.utils.util).
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):

                result = await cleanup_websocket_sessions(
                    max_age_hours=max_age_hours,
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
                
                # Verify cleanup called with correct parameter
                mock_websocket_manager.cleanup_stale_sessions.assert_called_once_with( max_age_hours )
                
                # Verify response structure
                self.assertEqual( result["sessions_cleaned"], 1 )
                self.assertEqual( result["max_age_hours"], max_age_hours )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_cleanup_websocket_sessions_invalid_age( self ):
        """
        Test WebSocket session cleanup with invalid age parameter.
        
        Ensures:
            - Rejects negative max_age_hours values
            - Raises HTTPException with 400 status
            - Includes descriptive error message
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_websocket_manager = self._create_mock_websocket_manager()
            
            with self.assertRaises( HTTPException ) as context:
                await cleanup_websocket_sessions(
                    max_age_hours=-1,  # Invalid negative value
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
            
            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 400 )
            self.assertIn( "max_age_hours must be positive", str( context.exception.detail ) )
            
            # Verify cleanup was not called
            mock_websocket_manager.cleanup_stale_sessions.assert_not_called()
        
        asyncio.run( run_test() )
    
    def test_get_websocket_session_success( self ):
        """
        Test individual WebSocket session retrieval success case.
        
        Ensures:
            - Looks up session by session_id
            - Returns detailed session information
            - Handles existing sessions correctly
        """
        async def run_test():
            mock_websocket_manager = self._create_mock_websocket_manager()
            
            result = await get_websocket_session(
                session_id=self.test_session_id,
                current_user=self.test_user,
                websocket_manager=mock_websocket_manager
            )
            
            # Verify session lookup called
            mock_websocket_manager.get_session_info.assert_called_once_with( self.test_session_id )
            
            # Verify response is session info
            self.assertEqual( result, self.test_sessions[0] )
        
        asyncio.run( run_test() )
    
    def test_get_websocket_session_not_found( self ):
        """
        Test individual WebSocket session retrieval when session not found.
        
        Ensures:
            - Raises HTTPException with 404 status for missing session
            - Includes descriptive error message
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_websocket_manager = self._create_mock_websocket_manager()
            mock_websocket_manager.get_session_info.return_value = None  # Session not found
            
            with self.assertRaises( HTTPException ) as context:
                await get_websocket_session(
                    session_id="nonexistent_session",
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
            
            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 404 )
            self.assertEqual( str( context.exception.detail ), "Session not found" )
        
        asyncio.run( run_test() )
    
    def test_disconnect_websocket_session_success( self ):
        """
        Test WebSocket session disconnection success case.
        
        Ensures:
            - Verifies session is connected before disconnect
            - Calls disconnect on WebSocket manager
            - Returns confirmation with session details
        """
        async def run_test():
            mock_websocket_manager = self._create_mock_websocket_manager()
            mock_websocket_manager.is_connected.return_value = True
            
            # Live contract: timestamps come from du.get_current_datetime_iso() (cosa.utils.util).
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):

                result = await disconnect_websocket_session(
                    session_id=self.test_session_id,
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
                
                # Verify connection check and disconnect
                mock_websocket_manager.is_connected.assert_called_once_with( self.test_session_id )
                mock_websocket_manager.disconnect.assert_called_once_with( self.test_session_id )
                
                # Verify response structure
                self.assertEqual( result["session_id"], self.test_session_id )
                self.assertEqual( result["status"], "disconnected" )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_disconnect_websocket_session_not_found( self ):
        """
        Test WebSocket session disconnection when session not connected.
        
        Ensures:
            - Raises HTTPException with 404 status for disconnected session
            - Does not attempt disconnection
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_websocket_manager = self._create_mock_websocket_manager()
            mock_websocket_manager.is_connected.return_value = False
            
            with self.assertRaises( HTTPException ) as context:
                await disconnect_websocket_session(
                    session_id=self.test_session_id,
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
            
            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 404 )
            self.assertIn( "Session not found or already disconnected", str( context.exception.detail ) )
            
            # Verify disconnect was not called
            mock_websocket_manager.disconnect.assert_not_called()
        
        asyncio.run( run_test() )
    
    def test_update_single_session_policy_success( self ):
        """
        Test single-session policy update success case.
        
        Ensures:
            - Updates WebSocket manager policy setting
            - Returns confirmation with new policy state
            - Includes timestamp for change tracking
        """
        async def run_test():
            mock_websocket_manager = self._create_mock_websocket_manager()
            policy_enabled = True
            
            # Live contract: timestamps come from du.get_current_datetime_iso() (cosa.utils.util).
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):

                result = await update_single_session_policy(
                    enabled=policy_enabled,
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
                
                # Verify policy update called
                mock_websocket_manager.set_single_session_policy.assert_called_once_with( policy_enabled )
                
                # Verify response structure
                self.assertEqual( result["single_session_policy"], policy_enabled )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_get_available_events_success( self ):
        """
        Test available WebSocket events retrieval success case.
        
        Ensures:
            - Retrieves all available event types
            - Returns events in sorted order
            - Includes total count and timestamp
        """
        async def run_test():
            mock_websocket_manager = self._create_mock_websocket_manager()
            
            # Live contract: timestamps come from du.get_current_datetime_iso() (cosa.utils.util).
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):

                result = await get_available_events(
                    current_user=self.test_user,
                    websocket_manager=mock_websocket_manager
                )
                
                # Verify response structure
                self.assertEqual( result["available_events"], sorted( self.test_available_events ) )
                self.assertEqual( result["total_events"], len( self.test_available_events ) )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_dependency_functions( self ):
        """
        Test WebSocket admin router dependency functions.
        
        Ensures:
            - get_websocket_manager dependency works correctly
            - Returns proper attributes from main module
        """
        # Test get_websocket_manager dependency
        mock_main = Mock()
        mock_main.websocket_manager = "mock_websocket_manager"
        with _patch_fastapi_main( mock_main ):
            result = get_websocket_manager()
            self.assertEqual( result, "mock_websocket_manager" )
    
    def test_router_configuration( self ):
        """
        Test router configuration and metadata.
        
        Ensures:
            - Router has correct prefix and tags
            - Router is properly configured for FastAPI
            - Router object is accessible for app integration
        """
        # Verify router is configured
        self.assertIsNotNone( router )
        
        # Verify router has correct prefix and tags
        self.assertEqual( router.prefix, "/api" )
        self.assertIn( "websocket-admin", router.tags )
        
        # Verify router is an APIRouter instance
        from fastapi import APIRouter
        self.assertIsInstance( router, APIRouter )


def isolated_unit_test():
    """
    Run comprehensive unit tests for WebSocket admin router in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real WebSocket or authentication operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "WebSocket Admin Router Unit Tests - REST API Phase 4", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_get_websocket_sessions_success',
            'test_get_websocket_stats_success',
            'test_cleanup_websocket_sessions_success',
            'test_cleanup_websocket_sessions_invalid_age',
            'test_get_websocket_session_success',
            'test_get_websocket_session_not_found',
            'test_disconnect_websocket_session_success',
            'test_disconnect_websocket_session_not_found',
            'test_update_single_session_policy_success',
            'test_get_available_events_success',
            'test_dependency_functions',
            'test_router_configuration'
        ]
        
        for method in test_methods:
            suite.addTest( TestWebSocketAdminRouter( method ) )
        
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
        print( f"WEBSOCKET ADMIN ROUTER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL WEBSOCKET ADMIN ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME WEBSOCKET ADMIN ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 WEBSOCKET ADMIN ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} WebSocket admin router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )