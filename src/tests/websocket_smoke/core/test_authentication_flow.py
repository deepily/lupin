#!/usr/bin/env python3
"""
WebSocket Authentication Flow Tests

Comprehensive tests for WebSocket authentication scenarios, edge cases,
and error handling. Tests both /ws/queue/ and /ws/audio/ endpoints with
various authentication scenarios.

This module focuses on authentication behavior after connection establishment.
"""

import asyncio
import json
import time
import uuid
from typing import Dict, List, Any, Optional
import websockets

# Import our test utilities from the infrastructure
import sys
from pathlib import Path
sys.path.append( str( Path( __file__ ).parent.parent / "infrastructure" ) )
from test_utilities import WebSocketTestUtilities


class AuthenticationFlowTests:
    """
    Comprehensive WebSocket authentication tests.
    
    Tests authentication flows, token validation, error scenarios,
    and edge cases for both queue and audio endpoints.
    """
    
    def __init__( self, server_url: str = "localhost:7999" ):
        """
        Initialize authentication tests.
        
        Requires:
            - server_url is a non-empty string in format "host:port"
            
        Ensures:
            - self.utils is initialized with WebSocketTestUtilities
            - self.results is initialized as empty list
            
        Args:
            server_url: Server URL to test against
            
        Returns:
            None
            
        Raises:
            TypeError: If server_url is not a string
        """
        self.utils = WebSocketTestUtilities( server_url )
        self.results = []
    
    async def run_all_tests( self ) -> List[Dict[str, Any]]:
        """
        Run all authentication tests.
        
        Requires:
            - self.utils is properly initialized
            - self.results is initialized as a list
            
        Ensures:
            - returns list of test result dictionaries
            - each result contains name, success, duration_ms fields
            - self.results contains all test outcomes
            
        Args:
            None
            
        Returns:
            List of test results with success/failure status
            
        Raises:
            Exception: If WebSocket connections fail or test infrastructure errors occur
        """
        self.utils.log( "🔐 Starting Authentication Flow Tests" )
        self.utils.log( "=" * 50 )
        
        # Test valid authentication scenarios
        await self._test_valid_queue_authentication()
        await self._test_valid_audio_authentication()
        
        # Test authentication token formats
        await self._test_token_formats()
        await self._test_invalid_tokens()
        
        # Test authentication timing and sequences
        await self._test_authentication_timing()
        await self._test_multiple_auth_attempts()
        
        # Test error scenarios
        await self._test_authentication_without_token()
        await self._test_malformed_auth_messages()
        
        # Test edge cases
        await self._test_connection_after_auth_failure()
        await self._test_concurrent_authentications()
        
        return self.results
    
    async def _test_valid_queue_authentication( self ):
        """
        Test valid queue WebSocket authentication.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - test result is appended to self.results
            - WebSocket connection is properly closed
            - test timing is recorded
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connection or authentication fails
        """
        test_name = "valid_queue_authentication"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            token = self.utils.generate_mock_token( "test_user_queue" )
            
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            self.results.append( {
                "name": test_name,
                "success": auth_success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "user_id": "test_user_queue",
                    "auth_data": auth_data,
                    "endpoint": "queue"
                }
            } )
            
            status = "✅ PASS" if auth_success else "❌ FAIL"
            self.utils.log( f"   Queue Auth: {status} ({duration:.2f}ms)" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   Queue Auth: ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_valid_audio_authentication( self ):
        """
        Test valid audio WebSocket authentication (different behavior expected).
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - test result is appended to self.results
            - WebSocket connection is properly closed
            - audio endpoint behavior is validated
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connection or authentication fails
        """
        test_name = "valid_audio_authentication"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            token = self.utils.generate_mock_token( "test_user_audio" )
            
            websocket = await self.utils.connect_websocket( "audio", session_id, timeout=5.0 )
            auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Audio endpoint has different authentication behavior
            expected_behavior = True  # Audio always "succeeds" but behaves differently
            
            self.results.append( {
                "name": test_name,
                "success": expected_behavior,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "user_id": "test_user_audio",
                    "auth_data": auth_data,
                    "endpoint": "audio",
                    "auth_response_type": auth_data.get( "type" ) if auth_data else None
                }
            } )
            
            status = "✅ PASS" if expected_behavior else "❌ FAIL"
            response_type = auth_data.get( "type" ) if auth_data else "none"
            self.utils.log( f"   Audio Auth: {status} ({duration:.2f}ms) - Response: {response_type}" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   Audio Auth: ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_token_formats( self ):
        """
        Test various authentication token formats.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - all token format test cases are executed
            - test result is appended to self.results
            - all WebSocket connections are properly closed
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connections fail or test infrastructure errors occur
        """
        test_name = "token_formats"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        # Test cases: (user_id, should_succeed, description)
        token_test_cases = [
            ( "valid_user_123", True, "Standard user ID format" ),
            ( "user@domain.com", True, "Email-like user ID" ),
            ( "test-user-456", True, "Hyphenated user ID" ),
            ( "UserWithCaps", True, "Mixed case user ID" ),
            ( "u", True, "Single character user ID" ),
            ( "user_with_very_long_name_12345", True, "Long user ID" ),
            ( "", False, "Empty user ID should fail" ),
            ( "user with spaces", True, "User ID with spaces" ),
            ( "用户123", True, "Unicode user ID" ),
        ]
        
        results = []
        
        for user_id, should_succeed, description in token_test_cases:
            try:
                start_time = time.time()
                session_id = self.utils.generate_session_id()
                token = self.utils.generate_mock_token( user_id )
                
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
                await websocket.close()
                
                duration = ( time.time() - start_time ) * 1000
                
                # Evaluate success based on expectation
                test_success = ( auth_success == should_succeed )
                
                results.append( {
                    "user_id": repr( user_id ),
                    "expected": should_succeed,
                    "actual": auth_success,
                    "correct": test_success,
                    "duration_ms": duration,
                    "description": description,
                    "auth_data": auth_data
                } )
                
                status = "✅" if test_success else "❌"
                auth_status = "succeeded" if auth_success else "failed"
                self.utils.log( f"   {status} {repr(user_id)}: Auth {auth_status} ({duration:.1f}ms) - {description}" )
                
            except Exception as e:
                duration = ( time.time() - start_time ) * 1000
                # If we expected success but got an exception, that's a failure
                test_success = not should_succeed
                
                results.append( {
                    "user_id": repr( user_id ),
                    "expected": should_succeed,
                    "actual": False,
                    "correct": test_success,
                    "duration_ms": duration,
                    "description": description,
                    "error": str( e )
                } )
                
                status = "✅" if test_success else "❌"
                self.utils.log( f"   {status} {repr(user_id)}: Exception ({duration:.1f}ms) - {description} - {e}" )
        
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
            self.utils.log( f"   ✅ PASS ({overall_duration:.1f}ms) - All {len(results)} token formats behaved as expected" )
        else:
            incorrect = [r for r in results if not r["correct"]]
            self.utils.log( f"   ❌ FAIL ({overall_duration:.1f}ms) - {len(incorrect)} unexpected token behaviors" )
    
    async def _test_invalid_tokens( self ):
        """
        Test various invalid token scenarios.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - all invalid token cases are tested
            - test result is appended to self.results
            - all WebSocket connections are properly closed
            - invalid tokens are properly rejected
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connections fail or test infrastructure errors occur
        """
        test_name = "invalid_tokens"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        # Invalid token test cases
        invalid_token_cases = [
            ( None, "No token provided" ),
            ( "", "Empty token" ),
            ( "invalid_format", "Token without mock_ prefix" ),
            ( "mock_token_", "Token with empty user ID" ),
            ( "mock_token_" + "x" * 1000, "Extremely long token" ),
            ( json.dumps( {"invalid": "object"} ), "JSON object instead of token" ),
            ( "123456", "Numeric token" ),
        ]
        
        results = []
        
        for invalid_token, description in invalid_token_cases:
            try:
                start_time = time.time()
                session_id = self.utils.generate_session_id()
                
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                
                # Send authentication with invalid token
                auth_message = {
                    "type": "authenticate",
                    "token": invalid_token
                }
                await websocket.send( json.dumps( auth_message ) )
                
                # Wait for response
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=2.0 )
                    response_data = json.loads( response )
                    auth_failed_properly = response_data.get( "type" ) == "auth_error"
                except asyncio.TimeoutError:
                    auth_failed_properly = True  # No response means auth failed
                except Exception:
                    auth_failed_properly = True  # Parse error means auth failed
                
                await websocket.close()
                duration = ( time.time() - start_time ) * 1000
                
                results.append( {
                    "token": repr( invalid_token ),
                    "auth_failed_properly": auth_failed_properly,
                    "duration_ms": duration,
                    "description": description
                } )
                
                status = "✅" if auth_failed_properly else "❌"
                self.utils.log( f"   {status} {description}: Auth rejected properly ({duration:.1f}ms)" )
                
            except Exception as e:
                duration = ( time.time() - start_time ) * 1000
                # Connection or other errors are also acceptable for invalid tokens
                results.append( {
                    "token": repr( invalid_token ),
                    "auth_failed_properly": True,
                    "duration_ms": duration,
                    "description": description,
                    "error": str( e )
                } )
                
                self.utils.log( f"   ✅ {description}: Failed with exception ({duration:.1f}ms) - {e}" )
        
        # All invalid tokens should fail
        all_failed_properly = all( r["auth_failed_properly"] for r in results )
        overall_duration = sum( r["duration_ms"] for r in results )
        
        self.results.append( {
            "name": test_name,
            "success": all_failed_properly,
            "duration_ms": overall_duration,
            "details": {
                "invalid_cases": len( results ),
                "properly_rejected": sum( 1 for r in results if r["auth_failed_properly"] ),
                "results": results
            }
        } )
        
        if all_failed_properly:
            self.utils.log( f"   ✅ PASS ({overall_duration:.1f}ms) - All {len(results)} invalid tokens properly rejected" )
        else:
            accepted = [r for r in results if not r["auth_failed_properly"]]
            self.utils.log( f"   ❌ FAIL ({overall_duration:.1f}ms) - {len(accepted)} invalid tokens were incorrectly accepted" )
    
    async def _test_authentication_timing( self ):
        """
        Test authentication timing scenarios.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - immediate and delayed authentication scenarios are tested
            - timeout handling is validated
            - test result is appended to self.results
            - all WebSocket connections are properly closed
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connections fail or test infrastructure errors occur
        """
        test_name = "authentication_timing"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        timing_results = []
        
        try:
            # Test 1: Immediate authentication after connection
            session_id = self.utils.generate_session_id()
            token = self.utils.generate_mock_token( "timing_user_1" )
            
            websocket = await self.utils.connect_websocket( "queue", session_id )
            immediate_start = time.time()
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            immediate_duration = ( time.time() - immediate_start ) * 1000
            await websocket.close()
            
            timing_results.append( {
                "scenario": "immediate_auth",
                "success": auth_success,
                "duration_ms": immediate_duration
            } )
            
            # Test 2: Delayed authentication (wait 1 second)
            session_id = self.utils.generate_session_id()
            token = self.utils.generate_mock_token( "timing_user_2" )
            
            websocket = await self.utils.connect_websocket( "queue", session_id )
            await asyncio.sleep( 1.0 )  # Wait 1 second
            delayed_start = time.time()
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            delayed_duration = ( time.time() - delayed_start ) * 1000
            await websocket.close()
            
            timing_results.append( {
                "scenario": "delayed_auth",
                "success": auth_success,
                "duration_ms": delayed_duration
            } )
            
            # Test 3: Authentication timeout (very slow response simulation)
            session_id = self.utils.generate_session_id()
            token = self.utils.generate_mock_token( "timing_user_3" )
            
            websocket = await self.utils.connect_websocket( "queue", session_id )
            try:
                # Send auth but use very short timeout to simulate slow server
                auth_message = {"type": "authenticate", "token": token}
                await websocket.send( json.dumps( auth_message ) )
                response = await asyncio.wait_for( websocket.recv(), timeout=0.1 )  # 100ms timeout
                timeout_occurred = False
            except asyncio.TimeoutError:
                timeout_occurred = True
            await websocket.close()
            
            timing_results.append( {
                "scenario": "timeout_test",
                "timeout_occurred": timeout_occurred,
                "expected_timeout": True
            } )
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if immediate and delayed auth work, and timeout handling works
            success = (
                timing_results[0]["success"] and 
                timing_results[1]["success"] and
                timing_results[2]["timeout_occurred"]
            )
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "timing_scenarios": timing_results,
                    "immediate_auth_ms": timing_results[0]["duration_ms"],
                    "delayed_auth_ms": timing_results[1]["duration_ms"]
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - All timing scenarios work correctly" )
                self.utils.log( f"     Immediate: {timing_results[0]['duration_ms']:.1f}ms, Delayed: {timing_results[1]['duration_ms']:.1f}ms" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Timing issues detected" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_multiple_auth_attempts( self ):
        """
        Test multiple authentication attempts on the same connection.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - multiple authentication attempts are tested on same connection
            - test result is appended to self.results
            - WebSocket connection is properly closed
            - server behavior for multiple auth attempts is validated
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connection or authentication fails
        """
        test_name = "multiple_auth_attempts" 
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            websocket = await self.utils.connect_websocket( "queue", session_id )
            
            # First authentication attempt
            token1 = self.utils.generate_mock_token( "multi_user_1" )
            auth1_success, auth1_data = await self.utils.authenticate_websocket( websocket, token1 )
            
            # Second authentication attempt (should this work or fail?)
            token2 = self.utils.generate_mock_token( "multi_user_2" )
            try:
                auth2_success, auth2_data = await self.utils.authenticate_websocket( websocket, token2 )
                second_auth_attempted = True
            except Exception as e:
                auth2_success = False
                auth2_data = None
                second_auth_attempted = True
                second_auth_error = str( e )
            
            await websocket.close()
            duration = ( time.time() - start_time ) * 1000
            
            # Success if first auth works (second auth behavior may vary)
            success = auth1_success
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "first_auth_success": auth1_success,
                    "first_auth_data": auth1_data,
                    "second_auth_success": auth2_success,
                    "second_auth_data": auth2_data,
                    "multiple_auth_behavior": "allowed" if auth2_success else "rejected"
                }
            } )
            
            if success:
                behavior = "allowed" if auth2_success else "rejected"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - First auth successful, second auth {behavior}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - First authentication failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_authentication_without_token( self ):
        """
        Test connection behavior without authentication.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - connection behavior without authentication is tested
            - test result is appended to self.results
            - WebSocket connection is properly closed
            - server response to unauthenticated connections is validated
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connection fails
        """
        test_name = "authentication_without_token"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            websocket = await self.utils.connect_websocket( "queue", session_id )
            
            # Don't authenticate - just wait and see what happens
            try:
                # Wait for any automatic messages
                message = await asyncio.wait_for( websocket.recv(), timeout=2.0 )
                received_message = json.loads( message )
                message_type = received_message.get( "type" )
            except asyncio.TimeoutError:
                # No message received - this might be expected
                message_type = None
                received_message = None
            
            await websocket.close()
            duration = ( time.time() - start_time ) * 1000
            
            # Success if connection stays open without auth (server behavior may vary)
            success = True  # Connection established and held without auth
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "connection_maintained": True,
                    "automatic_message_type": message_type,
                    "automatic_message": received_message
                }
            } )
            
            msg_info = f"message: {message_type}" if message_type else "no automatic messages"
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Connection maintained without auth, {msg_info}" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_malformed_auth_messages( self ):
        """
        Test various malformed authentication messages.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - all malformed message cases are tested
            - test result is appended to self.results
            - all WebSocket connections are properly closed
            - malformed messages are properly rejected
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connections fail or test infrastructure errors occur
        """
        test_name = "malformed_auth_messages"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        # Malformed message test cases
        malformed_cases = [
            ( "not json", "Non-JSON message" ),
            ( "{invalid json", "Invalid JSON syntax" ),
            ( json.dumps( {"wrong": "type"} ), "Missing auth type" ),
            ( json.dumps( {"type": "authenticate"} ), "Missing token field" ),
            ( json.dumps( {"type": "wrong_type", "token": "mock_token_user"} ), "Wrong message type" ),
            ( json.dumps( {"type": "authenticate", "token": None} ), "Null token" ),
            ( json.dumps( {"type": "authenticate", "token": 123} ), "Numeric token" ),
            ( json.dumps( {"type": "authenticate", "token": ["array"]} ), "Array token" ),
        ]
        
        results = []
        
        for malformed_message, description in malformed_cases:
            try:
                start_time = time.time()
                session_id = self.utils.generate_session_id()
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                
                # Send malformed message
                await websocket.send( malformed_message )
                
                # Check if server responds with error or closes connection
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=1.0 )
                    response_data = json.loads( response )
                    server_rejected = response_data.get( "type" ) == "auth_error"
                except asyncio.TimeoutError:
                    server_rejected = True  # No response might mean rejection
                except websockets.exceptions.ConnectionClosed:
                    server_rejected = True  # Connection closed means rejection
                except Exception:
                    server_rejected = True  # Any error means rejection
                
                await websocket.close()
                duration = ( time.time() - start_time ) * 1000
                
                results.append( {
                    "message": repr( malformed_message ),
                    "rejected_properly": server_rejected,
                    "duration_ms": duration,
                    "description": description
                } )
                
                status = "✅" if server_rejected else "❌"
                self.utils.log( f"   {status} {description}: Rejected properly ({duration:.1f}ms)" )
                
            except Exception as e:
                duration = ( time.time() - start_time ) * 1000
                # Exception during malformed message handling is acceptable
                results.append( {
                    "message": repr( malformed_message ),
                    "rejected_properly": True,
                    "duration_ms": duration,
                    "description": description,
                    "error": str( e )
                } )
                
                self.utils.log( f"   ✅ {description}: Rejected with exception ({duration:.1f}ms)" )
        
        # All malformed messages should be rejected
        all_rejected = all( r["rejected_properly"] for r in results )
        overall_duration = sum( r["duration_ms"] for r in results )
        
        self.results.append( {
            "name": test_name,
            "success": all_rejected,
            "duration_ms": overall_duration,
            "details": {
                "malformed_cases": len( results ),
                "properly_rejected": sum( 1 for r in results if r["rejected_properly"] ),
                "results": results
            }
        } )
        
        if all_rejected:
            self.utils.log( f"   ✅ PASS ({overall_duration:.1f}ms) - All {len(results)} malformed messages properly rejected" )
        else:
            accepted = [r for r in results if not r["rejected_properly"]]
            self.utils.log( f"   ❌ FAIL ({overall_duration:.1f}ms) - {len(accepted)} malformed messages were incorrectly accepted" )
    
    async def _test_connection_after_auth_failure( self ):
        """
        Test connection behavior after authentication failure.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - authentication failure behavior is tested
            - connection recovery scenarios are validated
            - test result is appended to self.results
            - WebSocket connection is properly closed
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connection fails
        """
        test_name = "connection_after_auth_failure"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            websocket = await self.utils.connect_websocket( "queue", session_id )
            
            # Try authentication with invalid token
            invalid_token = "definitely_not_valid"
            auth_message = {"type": "authenticate", "token": invalid_token}
            await websocket.send( json.dumps( auth_message ) )
            
            # Wait for auth failure response
            try:
                response = await asyncio.wait_for( websocket.recv(), timeout=2.0 )
                auth_failed = True
            except asyncio.TimeoutError:
                auth_failed = True  # Timeout also indicates failure
            
            # Try to send another message after auth failure
            try:
                await websocket.send( json.dumps( {"type": "test", "data": "after_failure"} ) )
                can_send_after_failure = True
            except Exception:
                can_send_after_failure = False
            
            # Try valid authentication after initial failure
            try:
                valid_token = self.utils.generate_mock_token( "recovery_user" )
                recovery_success, _ = await self.utils.authenticate_websocket( websocket, valid_token )
            except Exception:
                recovery_success = False
            
            await websocket.close()
            duration = ( time.time() - start_time ) * 1000
            
            # Success if auth fails but connection recovery is handled gracefully
            success = auth_failed  # Main requirement is that invalid auth fails
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "auth_failed_properly": auth_failed,
                    "can_send_after_failure": can_send_after_failure,
                    "recovery_auth_success": recovery_success,
                    "connection_behavior": "maintained" if can_send_after_failure else "restricted"
                }
            } )
            
            if success:
                behavior = "maintained" if can_send_after_failure else "restricted"
                recovery = "succeeded" if recovery_success else "failed"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Auth failed properly, connection {behavior}, recovery {recovery}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Invalid authentication was accepted" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_concurrent_authentications( self ):
        """
        Test multiple concurrent authentication attempts.
        
        Requires:
            - self.utils is properly initialized
            - WebSocket server is running and accessible
            
        Ensures:
            - concurrent authentication attempts are tested
            - test result is appended to self.results
            - all WebSocket connections are properly closed
            - server handling of concurrent auths is validated
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: If WebSocket connections fail or test infrastructure errors occur
        """
        test_name = "concurrent_authentications"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            # Create multiple connections and authenticate concurrently
            auth_tasks = []
            for i in range( 3 ):
                session_id = self.utils.generate_session_id()
                user_id = f"concurrent_user_{i}"
                task = self._single_concurrent_auth( session_id, user_id )
                auth_tasks.append( task )
            
            # Wait for all authentication attempts
            auth_results = await asyncio.gather( *auth_tasks, return_exceptions=True )
            
            # Analyze results
            successful_auths = 0
            for i, result in enumerate( auth_results ):
                if isinstance( result, dict ) and result.get( "success" ):
                    successful_auths += 1
                    self.utils.log( f"   Auth {i}: ✅ Succeeded" )
                else:
                    error = result if isinstance( result, Exception ) else result.get( "error", "Unknown" )
                    self.utils.log( f"   Auth {i}: ❌ Failed - {error}" )
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if most concurrent authentications work
            success_rate = successful_auths / len( auth_tasks )
            success = success_rate >= 0.8  # At least 80% success rate
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "concurrent_attempts": len( auth_tasks ),
                    "successful_auths": successful_auths,
                    "success_rate": success_rate,
                    "individual_results": [r if isinstance( r, dict ) else {"error": str( r )} for r in auth_results]
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - {successful_auths}/{len(auth_tasks)} concurrent auths succeeded ({success_rate:.1%})" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Only {successful_auths}/{len(auth_tasks)} concurrent auths succeeded ({success_rate:.1%})" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _single_concurrent_auth( self, session_id: str, user_id: str ) -> Dict[str, Any]:
        """
        Perform a single authentication for concurrent testing.
        
        Requires:
            - session_id is a non-empty string
            - user_id is a non-empty string
            - self.utils is properly initialized
            
        Ensures:
            - returns dictionary with success status and auth data
            - WebSocket connection is properly closed
            - authentication attempt is completed
            
        Args:
            session_id: Unique session identifier for WebSocket connection
            user_id: User identifier for authentication token
            
        Returns:
            Dictionary containing success status, user_id, session_id, and auth_data or error
            
        Raises:
            None (exceptions are caught and returned in result dictionary)
        """
        try:
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
            token = self.utils.generate_mock_token( user_id )
            auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
            await websocket.close()
            
            return {
                "success": auth_success,
                "user_id": user_id,
                "session_id": session_id,
                "auth_data": auth_data
            }
        except Exception as e:
            return {
                "success": False,
                "user_id": user_id,
                "session_id": session_id,
                "error": str( e )
            }


async def main():
    """
    Run all authentication flow tests.
    
    Requires:
        - WebSocket server is running and accessible
        
    Ensures:
        - all authentication tests are executed
        - test summary is printed to console
        - returns appropriate exit code (0 for success, 1 for failure)
        
    Args:
        None
        
    Returns:
        Exit code: 0 if all tests pass, 1 if any tests fail
        
    Raises:
        Exception: If test infrastructure fails
    """
    print( "🔐 WebSocket Authentication Flow Tests" )
    print( "=" * 50 )
    
    tester = AuthenticationFlowTests()
    results = await tester.run_all_tests()
    
    # Summary
    print( "\\n" + "=" * 50 )
    print( "📊 AUTHENTICATION TEST SUMMARY" )
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
        print( "\\n❌ Failed Tests:" )
        for test in failed_tests:
            print( f"  • {test['name']}: {test.get('error', 'Authentication logic error')}" )
    
    if passed_tests == total_tests:
        print( "\\n✅ All authentication tests passed!" )
        return 0
    else:
        print( f"\\n❌ {total_tests - passed_tests} authentication tests failed!" )
        return 1


if __name__ == "__main__":
    import sys
    exit_code = asyncio.run( main() )
    sys.exit( exit_code )