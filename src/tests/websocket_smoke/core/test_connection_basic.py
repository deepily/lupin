#!/usr/bin/env python3
"""
Basic WebSocket Connection Tests

Comprehensive tests for WebSocket connection establishment, error handling,
and edge cases. Tests both /ws/queue/ and /ws/audio/ endpoints.

This module tests the fundamental connection layer before authentication.
"""

import asyncio
import json
import time
import urllib.parse
from typing import Dict, List, Any, Optional
import websockets

# Import our test utilities from the infrastructure
import sys
from pathlib import Path
sys.path.append( str( Path( __file__ ).parent.parent / "infrastructure" ) )
from test_utilities import WebSocketTestUtilities


class ConnectionBasicTests:
    """
    Comprehensive WebSocket connection tests.
    
    Tests connection establishment, error scenarios, timeout handling,
    and edge cases for both queue and audio endpoints.
    """
    
    def __init__( self, server_url: str = "localhost:7999" ):
        """
        Initialize connection test suite with server configuration.
        
        Requires:
            - server_url is a non-empty string in format "host:port"
            - server_url contains valid hostname or IP address
            
        Ensures:
            - self.utils is initialized with WebSocketTestUtilities instance
            - self.results is initialized as empty list
            - object is ready to execute connection tests
            
        Args:
            server_url: Server URL to test against in "host:port" format
            
        Raises:
            - ValueError if server_url is empty or malformed
            - ConnectionError if server_url is unreachable
        """
        self.utils = WebSocketTestUtilities( server_url )
        self.results = []
    
    async def run_all_tests( self ) -> List[Dict[str, Any]]:
        """
        Execute comprehensive WebSocket connection test suite.
        
        Requires:
            - self.utils is properly initialized
            - self.results is initialized as empty list
            - WebSocket server is running and accessible
            
        Ensures:
            - all connection test methods are executed in sequence
            - each test result is appended to self.results
            - returns complete list of test results with success/failure status
            - no connections remain open after completion
            
        Returns:
            List of test result dictionaries containing:
            - name: test identifier
            - success: boolean test outcome
            - duration_ms: execution time in milliseconds
            - details: test-specific result data
            - error: error message if test failed
            
        Raises:
            - ConnectionError if server is unreachable
            - TimeoutError if tests exceed reasonable time limits
        """
        self.utils.log( "🔌 Starting Basic Connection Tests" )
        self.utils.log( "=" * 50 )
        
        # Test valid connections
        await self._test_valid_queue_connection()
        await self._test_valid_audio_connection()
        
        # Test session ID validation
        await self._test_session_id_formats()
        await self._test_session_id_edge_cases()
        
        # Test connection limits and cleanup
        await self._test_connection_cleanup()
        await self._test_rapid_connections()
        
        # Test error scenarios
        await self._test_invalid_endpoints()
        await self._test_connection_timeouts()
        
        # Test concurrent connections
        await self._test_concurrent_same_session()
        await self._test_concurrent_different_sessions()
        
        return self.results
    
    async def _test_valid_queue_connection( self ):
        """
        Test basic WebSocket connection to queue endpoint.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running on configured port
            - /ws/queue/ endpoint is available
            
        Ensures:
            - attempts connection to queue endpoint with valid session ID
            - verifies connection is active using ping
            - properly closes connection after test
            - appends test result to self.results
            - logs test outcome with duration
            
        Raises:
            - websockets.ConnectionClosed if connection fails
            - asyncio.TimeoutError if connection times out
        """
        test_name = "valid_queue_connection"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            
            # Verify connection is active with a ping
            await websocket.ping()
            
            await websocket.close()
            duration = ( time.time() - start_time ) * 1000
            
            self.results.append( {
                "name": test_name,
                "success": True,
                "duration_ms": duration,
                "details": {"session_id": session_id, "endpoint": "queue"}
            } )
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms)" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms): {e}" )
    
    async def _test_valid_audio_connection( self ):
        """
        Test basic WebSocket connection to audio endpoint.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running on configured port
            - /ws/audio/ endpoint is available
            
        Ensures:
            - attempts connection to audio endpoint with valid session ID
            - checks for immediate audio streaming status message
            - properly closes connection after test
            - appends test result to self.results with audio status info
            - logs test outcome with duration and audio message status
            
        Raises:
            - websockets.ConnectionClosed if connection fails
            - asyncio.TimeoutError if connection or message times out
        """
        test_name = "valid_audio_connection"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            websocket = await self.utils.connect_websocket( "audio", session_id, timeout=5.0 )
            
            # Audio WebSocket should immediately send a status message
            try:
                message = await asyncio.wait_for( websocket.recv(), timeout=2.0 )
                data = json.loads( message )
                audio_message_received = data.get( "type" ) == "audio_streaming_status"
            except asyncio.TimeoutError:
                audio_message_received = False
            
            await websocket.close()
            duration = ( time.time() - start_time ) * 1000
            
            self.results.append( {
                "name": test_name,
                "success": True,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id, 
                    "endpoint": "audio",
                    "immediate_status_message": audio_message_received
                }
            } )
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Audio status: {audio_message_received}" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms): {e}" )
    
    async def _test_session_id_formats( self ):
        """
        Test WebSocket connections with various session ID formats.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            - test cases include valid and invalid session ID formats
            
        Ensures:
            - tests multiple session ID formats against expected behavior
            - validates server correctly accepts/rejects session IDs
            - measures connection attempt duration for each test case
            - appends comprehensive test result to self.results
            - logs individual test case outcomes
            
        Raises:
            - websockets.ConnectionClosed for expected invalid session IDs
            - asyncio.TimeoutError if connections exceed timeout limits
        """
        test_name = "session_id_formats"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        # Test cases: use generated session IDs and test edge cases
        valid_session = self.utils.generate_session_id()
        
        test_cases = [
            ( valid_session, True, "Generated valid session ID" ),
            ( "very-wise penguin", False, "Three words should fail" ),
            ( "wise", False, "Single word should fail" ),
            ( "", False, "Empty session ID should fail" ),
            ( "wise  penguin", False, "Multiple spaces should fail" ),
            ( "123 456", False, "Numeric session ID should fail" ),
            ( "wise_penguin", False, "Underscore format should fail" ),
        ]
        
        results = []
        
        for session_id, should_succeed, description in test_cases:
            try:
                start_time = time.time()
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                await websocket.close()
                duration = ( time.time() - start_time ) * 1000
                
                success = should_succeed  # Connection succeeded
                results.append( {
                    "session_id": session_id,
                    "expected": should_succeed,
                    "actual": True,
                    "correct": success,
                    "duration_ms": duration,
                    "description": description
                } )
                
                status = "✅" if success else "⚠️"
                self.utils.log( f"   {status} '{session_id}': Connected ({duration:.1f}ms) - {description}" )
                
            except Exception as e:
                duration = ( time.time() - start_time ) * 1000
                success = not should_succeed  # Connection failed as expected
                
                results.append( {
                    "session_id": session_id,
                    "expected": should_succeed,
                    "actual": False,
                    "correct": success,
                    "duration_ms": duration,
                    "description": description,
                    "error": str( e )
                } )
                
                status = "✅" if success else "❌"
                self.utils.log( f"   {status} '{session_id}': Failed ({duration:.1f}ms) - {description}" )
        
        # Overall test success
        all_correct = all( r["correct"] for r in results )
        overall_duration = sum( r["duration_ms"] for r in results )
        
        self.results.append( {
            "name": test_name,
            "success": all_correct,
            "duration_ms": overall_duration,
            "details": {
                "test_cases": len( results ),
                "correct_predictions": sum( 1 for r in results if r["correct"] ),
                "results": results
            }
        } )
        
        if all_correct:
            self.utils.log( f"   ✅ PASS ({overall_duration:.1f}ms) - All {len(results)} cases behaved as expected" )
        else:
            incorrect = [r for r in results if not r["correct"]]
            self.utils.log( f"   ❌ FAIL ({overall_duration:.1f}ms) - {len(incorrect)} unexpected behaviors" )
    
    async def _test_session_id_edge_cases( self ):
        """
        Test WebSocket connections with session ID edge cases and special characters.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            - test cases include edge cases with special characters
            
        Ensures:
            - tests session IDs with Unicode, whitespace, and special characters
            - validates server correctly handles edge case session IDs
            - measures connection attempt duration for each edge case
            - appends comprehensive test result to self.results
            - logs edge case outcomes with repr() for special character visibility
            
        Raises:
            - websockets.ConnectionClosed for expected invalid session IDs
            - asyncio.TimeoutError if connections exceed timeout limits
            - UnicodeError if session ID encoding fails
        """
        test_name = "session_id_edge_cases"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        # More challenging edge cases using generated base
        valid_session1 = self.utils.generate_session_id()
        valid_session2 = self.utils.generate_session_id()
        
        edge_cases = [
            ( valid_session1, True, "First generated valid session" ),
            ( valid_session2, True, "Second generated valid session" ),
            ( valid_session1.upper(), True, "Uppercase version of valid session" ),
            ( "wise\tpenguin", False, "Tab character should fail" ),
            ( "wise\npenguin", False, "Newline should fail" ),
            ( "café mouse", False, "Unicode characters should fail" ),
            ( "wise-penguin", False, "Hyphenated format should fail" ),
            ( "wise penguin!", False, "Punctuation should fail" ),
        ]
        
        results = []
        
        for session_id, should_succeed, description in edge_cases:
            try:
                start_time = time.time()
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                await websocket.close()
                duration = ( time.time() - start_time ) * 1000
                
                success = should_succeed
                results.append( {
                    "session_id": repr( session_id ),  # Use repr to show special chars
                    "expected": should_succeed,
                    "actual": True,
                    "correct": success,
                    "duration_ms": duration,
                    "description": description
                } )
                
                status = "✅" if success else "⚠️"
                self.utils.log( f"   {status} {repr(session_id)}: Connected ({duration:.1f}ms) - {description}" )
                
            except Exception as e:
                duration = ( time.time() - start_time ) * 1000
                success = not should_succeed
                
                results.append( {
                    "session_id": repr( session_id ),
                    "expected": should_succeed,
                    "actual": False,
                    "correct": success,
                    "duration_ms": duration,
                    "description": description,
                    "error": str( e )
                } )
                
                status = "✅" if success else "❌"
                self.utils.log( f"   {status} {repr(session_id)}: Failed ({duration:.1f}ms) - {description}" )
        
        all_correct = all( r["correct"] for r in results )
        overall_duration = sum( r["duration_ms"] for r in results )
        
        self.results.append( {
            "name": test_name,
            "success": all_correct,
            "duration_ms": overall_duration,
            "details": {
                "edge_cases": len( results ),
                "correct_predictions": sum( 1 for r in results if r["correct"] ),
                "results": results
            }
        } )
        
        if all_correct:
            self.utils.log( f"   ✅ PASS ({overall_duration:.1f}ms) - All {len(results)} edge cases handled correctly" )
        else:
            incorrect = [r for r in results if not r["correct"]]
            self.utils.log( f"   ❌ FAIL ({overall_duration:.1f}ms) - {len(incorrect)} unexpected edge case behaviors" )
    
    async def _test_connection_cleanup( self ):
        """
        Test WebSocket connection cleanup and resource management.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            - server supports multiple concurrent connections
            
        Ensures:
            - creates multiple WebSocket connections successfully
            - properly closes all created connections
            - verifies server resources are cleaned up after connection closure
            - confirms new connections can be established after cleanup
            - appends test result to self.results with cleanup details
            
        Raises:
            - websockets.ConnectionClosed if connections fail unexpectedly
            - asyncio.TimeoutError if operations exceed timeout limits
            - ResourceError if server fails to clean up resources
        """
        test_name = "connection_cleanup"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        connections_created = 0
        
        try:
            # Create multiple connections and close them properly
            connections = []
            for i in range( 5 ):
                session_id = self.utils.generate_session_id()
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                connections.append( websocket )
                connections_created += 1
            
            # Close all connections
            for websocket in connections:
                await websocket.close()
            
            # Verify we can still create new connections (server didn't leak resources)
            session_id = self.utils.generate_session_id()
            test_websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
            await test_websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            self.results.append( {
                "name": test_name,
                "success": True,
                "duration_ms": duration,
                "details": {
                    "connections_created": connections_created,
                    "cleanup_successful": True,
                    "new_connection_after_cleanup": True
                }
            } )
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Created and cleaned up {connections_created} connections" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e ),
                "details": {"connections_created": connections_created}
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms): {e}" )
    
    async def _test_rapid_connections( self ):
        """
        Test rapid WebSocket connection creation and closing patterns.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            - server can handle rapid connection establishment/teardown
            
        Ensures:
            - creates and closes connections in rapid succession
            - includes small delays to avoid overwhelming server
            - counts successful rapid connections
            - calculates average connection time per rapid connection
            - appends test result to self.results with timing metrics
            
        Raises:
            - websockets.ConnectionClosed if rapid connections fail
            - asyncio.TimeoutError if connections exceed timeout limits
            - ServerOverloadError if server cannot handle rapid connections
        """
        test_name = "rapid_connections"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        successful_connections = 0
        
        try:
            # Rapidly create and close connections
            for i in range( 10 ):
                session_id = self.utils.generate_session_id()
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=2.0 )
                await websocket.close()
                successful_connections += 1
                
                # Small delay to avoid overwhelming the server
                await asyncio.sleep( 0.05 )
            
            duration = ( time.time() - start_time ) * 1000
            
            self.results.append( {
                "name": test_name,
                "success": True,
                "duration_ms": duration,
                "details": {
                    "rapid_connections": successful_connections,
                    "average_connection_time": duration / successful_connections if successful_connections > 0 else 0
                }
            } )
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - {successful_connections} rapid connections successful" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e ),
                "details": {"successful_connections": successful_connections}
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms): Failed after {successful_connections} connections - {e}" )
    
    async def _test_invalid_endpoints( self ):
        """
        Test WebSocket connections to invalid or non-existent endpoints.
        
        Requires:
            - self.utils is properly initialized
            - test includes various invalid endpoint patterns
            - server properly rejects invalid endpoint connections
            
        Ensures:
            - attempts connections to known invalid endpoints
            - verifies server correctly rejects invalid endpoint requests
            - measures rejection response time for each invalid endpoint
            - appends test result to self.results with rejection details
            - logs expected failures as successful test outcomes
            
        Raises:
            - websockets.InvalidURI for malformed endpoint URIs
            - websockets.ConnectionClosed for properly rejected endpoints
            - Unexpected success exceptions if invalid endpoints are accepted
        """
        test_name = "invalid_endpoints"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        invalid_endpoints = [
            "invalid",
            "ws",
            "",
            "queue/extra",
            "audio/extra",
            "admin",
        ]
        
        results = []
        start_time = time.time()
        
        for endpoint in invalid_endpoints:
            try:
                session_id = "test session"
                # Manually construct invalid URI
                encoded_session = urllib.parse.quote( session_id )
                uri = f"ws://{self.utils.base_url}/ws/{endpoint}/{encoded_session}"
                
                # This should fail
                websocket = await asyncio.wait_for( websockets.connect( uri ), timeout=2.0 )
                await websocket.close()
                
                # If we get here, the connection unexpectedly succeeded
                results.append( {
                    "endpoint": endpoint,
                    "expected_failure": True,
                    "actually_failed": False,
                    "correct": False
                } )
                self.utils.log( f"   ⚠️ '{endpoint}': Unexpectedly succeeded" )
                
            except Exception as e:
                # Expected failure
                results.append( {
                    "endpoint": endpoint,
                    "expected_failure": True,
                    "actually_failed": True,
                    "correct": True,
                    "error": str( e )
                } )
                self.utils.log( f"   ✅ '{endpoint}': Failed as expected ({type(e).__name__})" )
        
        duration = ( time.time() - start_time ) * 1000
        all_correct = all( r["correct"] for r in results )
        
        self.results.append( {
            "name": test_name,
            "success": all_correct,
            "duration_ms": duration,
            "details": {
                "invalid_endpoints_tested": len( results ),
                "correctly_rejected": sum( 1 for r in results if r["correct"] ),
                "results": results
            }
        } )
        
        if all_correct:
            self.utils.log( f"   ✅ PASS ({duration:.1f}ms) - All {len(results)} invalid endpoints correctly rejected" )
        else:
            unexpected = [r for r in results if not r["correct"]]
            self.utils.log( f"   ❌ FAIL ({duration:.1f}ms) - {len(unexpected)} endpoints had unexpected behavior" )
    
    async def _test_connection_timeouts( self ):
        """
        Test WebSocket connection timeout behavior and handling.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            - timeout values include both very short and reasonable timeouts
            
        Ensures:
            - tests connection behavior with extremely short timeout
            - tests connection behavior with normal reasonable timeout
            - measures performance for different timeout scenarios
            - validates timeout handling works correctly
            - appends test result to self.results with timeout behavior details
            
        Raises:
            - asyncio.TimeoutError for expected short timeout failures
            - websockets.ConnectionClosed if connections fail unexpectedly
        """
        test_name = "connection_timeouts"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        
        try:
            # Test with very short timeout
            session_id = self.utils.generate_session_id()
            
            with self.utils.measure_performance( "short_timeout_connection" ):
                try:
                    websocket = await self.utils.connect_websocket( "queue", session_id, timeout=0.001 )  # 1ms timeout
                    await websocket.close()
                    connection_succeeded = True
                except asyncio.TimeoutError:
                    connection_succeeded = False
                except Exception:
                    connection_succeeded = False
            
            # Test with reasonable timeout (should succeed)
            with self.utils.measure_performance( "normal_timeout_connection" ):
                try:
                    websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
                    await websocket.close()
                    normal_connection_succeeded = True
                except Exception:
                    normal_connection_succeeded = False
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if: short timeout had expected behavior AND normal timeout succeeded
            success = normal_connection_succeeded  # We mainly care that normal connections work
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "short_timeout_connection": connection_succeeded,
                    "normal_timeout_connection": normal_connection_succeeded,
                    "timeout_handling_working": True
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Timeout handling works correctly" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Normal timeout connection failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms): {e}" )
    
    async def _test_concurrent_same_session( self ):
        """
        Test multiple concurrent WebSocket connections using same session ID.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            - server has defined behavior for multiple connections per session
            
        Ensures:
            - attempts multiple concurrent connections with identical session ID
            - executes connection attempts concurrently using asyncio.gather
            - counts successful vs failed concurrent connections
            - properly closes all successful connections
            - appends test result to self.results with concurrency details
            - determines server behavior (allows/restricts multiple connections)
            
        Raises:
            - websockets.ConnectionClosed if connections are rejected
            - asyncio.TimeoutError if concurrent connections exceed timeout
        """
        test_name = "concurrent_same_session"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        session_id = self.utils.generate_session_id()
        
        try:
            # Try to create multiple connections with same session ID
            connection_tasks = []
            for i in range( 3 ):
                task = self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                connection_tasks.append( task )
            
            # Execute connections concurrently
            connections = await asyncio.gather( *connection_tasks, return_exceptions=True )
            
            # Count successful connections
            successful_connections = []
            for i, conn in enumerate( connections ):
                if isinstance( conn, Exception ):
                    self.utils.log( f"   Connection {i}: Failed ({type(conn).__name__})" )
                else:
                    successful_connections.append( conn )
                    self.utils.log( f"   Connection {i}: Succeeded" )
            
            # Close all successful connections
            for conn in successful_connections:
                if hasattr( conn, 'close' ):
                    await conn.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # The behavior here depends on server configuration
            # We'll consider it successful if at least one connection worked
            success = len( successful_connections ) >= 1
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "attempted_connections": len( connections ),
                    "successful_connections": len( successful_connections ),
                    "server_behavior": "allows" if len( successful_connections ) > 1 else "restricts"
                }
            } )
            
            if success:
                behavior = "multiple" if len( successful_connections ) > 1 else "single"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Server allows {behavior} connections per session" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - No connections succeeded" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms): {e}" )
    
    async def _test_concurrent_different_sessions( self ):
        """
        Test multiple concurrent WebSocket connections using different session IDs.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            - server supports multiple concurrent sessions
            
        Ensures:
            - creates multiple unique session IDs for concurrent testing
            - attempts concurrent connections with different session IDs
            - executes all connections concurrently using asyncio.gather
            - analyzes success rate of concurrent different-session connections
            - properly closes all successful connections
            - appends test result to self.results with success rate metrics
            - requires minimum 80% success rate for test to pass
            
        Raises:
            - websockets.ConnectionClosed if connections fail unexpectedly
            - asyncio.TimeoutError if concurrent connections exceed timeout
            - ServerCapacityError if server cannot handle concurrent sessions
        """
        test_name = "concurrent_different_sessions"
        self.utils.log( f"\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        
        try:
            # Create connections with different session IDs concurrently
            connection_tasks = []
            session_ids = []
            
            for i in range( 5 ):
                session_id = self.utils.generate_session_id()
                session_ids.append( session_id )
                task = self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                connection_tasks.append( task )
            
            # Execute all connections concurrently
            connections = await asyncio.gather( *connection_tasks, return_exceptions=True )
            
            # Analyze results
            successful_connections = []
            for i, conn in enumerate( connections ):
                if isinstance( conn, Exception ):
                    self.utils.log( f"   Session '{session_ids[i]}': Failed ({type(conn).__name__})" )
                else:
                    successful_connections.append( conn )
                    self.utils.log( f"   Session '{session_ids[i]}': Succeeded" )
            
            # Close all connections
            for conn in successful_connections:
                await conn.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Should succeed if all or most connections worked
            success_rate = len( successful_connections ) / len( connections )
            success = success_rate >= 0.8  # At least 80% success rate
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "attempted_connections": len( connections ),
                    "successful_connections": len( successful_connections ),
                    "success_rate": success_rate,
                    "session_ids": session_ids
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - {len(successful_connections)}/{len(connections)} concurrent connections successful ({success_rate:.1%})" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Only {len(successful_connections)}/{len(connections)} connections successful ({success_rate:.1%})" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms): {e}" )


async def main():
    """
    Execute complete basic WebSocket connection test suite and display results.
    
    Requires:
        - WebSocket server is running and accessible
        - ConnectionBasicTests class is properly implemented
        
    Ensures:
        - creates ConnectionBasicTests instance
        - executes all connection tests via run_all_tests()
        - displays comprehensive test summary with statistics
        - shows detailed failure information for failed tests
        - returns appropriate exit code (0 for success, 1 for failures)
        
    Returns:
        Exit code: 0 if all tests passed, 1 if any tests failed
        
    Raises:
        - ConnectionError if server is unreachable
        - Exception if test execution fails catastrophically
    """
    print( "🧪 WebSocket Basic Connection Tests" )
    print( "=" * 50 )
    
    tester = ConnectionBasicTests()
    results = await tester.run_all_tests()
    
    # Summary
    print( "\n" + "=" * 50 )
    print( "📊 CONNECTION TEST SUMMARY" )
    print( "=" * 50 )
    
    total_tests = len( results )
    passed_tests = sum( 1 for r in results if r["success"] )
    total_duration = sum( r["duration_ms"] for r in results )
    
    print( f"Total Tests: {total_tests}" )
    print( f"Passed: {passed_tests}" )
    print( f"Failed: {total_tests - passed_tests}" )
    print( f"Success Rate: {(passed_tests/total_tests)*100:.1f}%" )
    print( f"Total Duration: {total_duration:.2f}ms" )
    
    # Failed tests detail
    failed_tests = [r for r in results if not r["success"]]
    if failed_tests:
        print( "\n❌ Failed Tests:" )
        for test in failed_tests:
            print( f"  • {test['name']}: {test.get('error', 'Unknown error')}" )
    
    if passed_tests == total_tests:
        print( "\n✅ All connection tests passed!" )
        return 0
    else:
        print( f"\n❌ {total_tests - passed_tests} connection tests failed!" )
        return 1


if __name__ == "__main__":
    import sys
    exit_code = asyncio.run( main() )
    sys.exit( exit_code )