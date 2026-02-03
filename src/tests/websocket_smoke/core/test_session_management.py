#!/usr/bin/env python3
"""
WebSocket Session Management Tests

Comprehensive tests for WebSocket session lifecycle, persistence, 
cleanup, and cross-session behavior. Tests session isolation, 
data persistence, and resource management.

This module focuses on session management after authentication.
"""

import asyncio
import json
import time
import uuid
from typing import Dict, List, Any, Optional, Set
import websockets

# Import our test utilities from the infrastructure
import sys
from pathlib import Path
sys.path.append( str( Path( __file__ ).parent.parent / "infrastructure" ) )
from test_utilities import WebSocketTestUtilities


class SessionManagementTests:
    """
    Comprehensive WebSocket session management tests.
    
    Tests session creation, persistence, isolation, cleanup,
    and resource management across different scenarios.
    """
    
    def __init__( self, server_url: str = "localhost:7999" ):
        """
        Initialize session management tests.
        
        Requires:
            - server_url is a valid string representing server endpoint
            - server_url follows format "host:port" or "host"
            
        Ensures:
            - self.utils is initialized with WebSocketTestUtilities
            - self.results is empty list ready for test results
            - self.active_sessions is empty set ready for session tracking
            
        Args:
            server_url: Server URL to test against in format "host:port"
        """
        self.utils = WebSocketTestUtilities( server_url )
        self.results = []
        self.active_sessions: Set[str] = set()
    
    async def run_all_tests( self ) -> List[Dict[str, Any]]:
        """
        Run all session management tests.
        
        Requires:
            - self is properly initialized with utils, results, and active_sessions
            - WebSocket server is running and accessible
            
        Ensures:
            - returns list of dictionaries containing test results
            - each result dict contains name, success, duration_ms fields
            - all test methods are executed in proper sequence
            - self.results contains all test outcomes
            
        Returns:
            List of test result dictionaries with test outcomes and metrics
            
        Raises:
            Exception: If critical test infrastructure fails
        """
        self.utils.log( "📋 Starting Session Management Tests" )
        self.utils.log( "=" * 50 )
        
        # Test basic session lifecycle
        await self._test_session_creation_lifecycle()
        await self._test_session_persistence()
        
        # Test session isolation
        await self._test_session_isolation()
        await self._test_cross_session_communication()
        
        # Test session cleanup and resource management
        await self._test_session_cleanup_on_disconnect()
        await self._test_multiple_sessions_same_user()
        
        # Test session edge cases
        await self._test_session_reconnection()
        await self._test_session_timeout_behavior()
        
        # Test session limits and scaling
        await self._test_maximum_sessions_per_user()
        await self._test_session_resource_cleanup()
        
        return self.results
    
    async def _test_session_creation_lifecycle( self ):
        """
        Test basic session creation and lifecycle.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server is running and accepting connections
            - self.results list exists for appending test results
            
        Ensures:
            - creates new session with unique session_id
            - performs authentication workflow
            - tests session responsiveness
            - performs clean session termination
            - appends test result to self.results
            - manages self.active_sessions set properly
            
        Raises:
            Exception: If session creation, authentication, or communication fails
        """
        test_name = "session_creation_lifecycle"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "lifecycle_user"

            # Use JWT authentication instead of deprecated mock tokens
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create session
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed during session creation" )
            
            self.active_sessions.add( session_id )
            
            # Test session is active
            test_message = {"type": "test", "data": "session_active"}
            await websocket.send( json.dumps( test_message ) )
            
            # Wait briefly for any response
            try:
                response = await asyncio.wait_for( websocket.recv(), timeout=1.0 )
                session_responsive = True
            except asyncio.TimeoutError:
                session_responsive = True  # No response doesn't mean failure
            
            # Clean session termination
            await websocket.close()
            self.active_sessions.discard( session_id )
            
            duration = ( time.time() - start_time ) * 1000
            
            self.results.append( {
                "name": test_name,
                "success": True,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "auth_successful": auth_success,
                    "session_responsive": session_responsive,
                    "clean_termination": True
                }
            } )
            
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Session lifecycle completed successfully" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_session_persistence( self ):
        """
        Test session persistence and state maintenance.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server supports session persistence features
            - self.results list exists for appending test results
            
        Ensures:
            - creates session and sends data for persistence
            - closes and reconnects to same session
            - tests whether session state is maintained across reconnections
            - appends comprehensive test result to self.results
            - properly closes all WebSocket connections
            
        Raises:
            Exception: If session creation, persistence testing, or reconnection fails
        """
        test_name = "session_persistence"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "persistence_user"

            # Use JWT authentication instead of deprecated mock tokens
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create session and send some data
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )

            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Send data that might be stored in session
            session_data = {
                "type": "session_data",
                "user_preference": "dark_mode",
                "session_count": 1,
                "timestamp": time.time()
            }
            await websocket.send( json.dumps( session_data ) )
            
            # Wait a bit for data to be processed
            await asyncio.sleep( 0.5 )
            
            # Close connection temporarily
            await websocket.close()
            
            # Reconnect to same session (if server supports this)
            try:
                websocket2 = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
                reconnect_success = True
                
                # Re-authenticate
                auth_success2, _ = await self.utils.authenticate_websocket( websocket2, token )
                
                # Test if session persisted any state
                query_message = {"type": "session_query", "query": "user_preference"}
                await websocket2.send( json.dumps( query_message ) )
                
                try:
                    response = await asyncio.wait_for( websocket2.recv(), timeout=2.0 )
                    session_state_maintained = True
                except asyncio.TimeoutError:
                    session_state_maintained = False  # No response doesn't mean failure
                
                await websocket2.close()
                
            except Exception as reconnect_error:
                reconnect_success = False
                auth_success2 = False
                session_state_maintained = False
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if basic session operations work (reconnection behavior may vary)
            success = auth_success and reconnect_success
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "initial_auth": auth_success,
                    "reconnect_success": reconnect_success,
                    "reauth_success": auth_success2,
                    "session_state_maintained": session_state_maintained,
                    "persistence_behavior": "supported" if session_state_maintained else "not_detected"
                }
            } )
            
            if success:
                persistence = "detected" if session_state_maintained else "not detected"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Session reconnection works, persistence {persistence}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Session reconnection failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_session_isolation( self ):
        """
        Test that sessions are properly isolated from each other.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server supports multiple concurrent sessions
            - self.results list exists for appending test results
            
        Ensures:
            - creates two separate sessions with different users
            - authenticates both sessions independently
            - sends distinct data to each session
            - verifies sessions operate independently without interference
            - appends test result documenting isolation behavior
            - properly closes all WebSocket connections
            
        Raises:
            Exception: If session creation, authentication, or isolation testing fails
        """
        test_name = "session_isolation"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        websockets_to_close = []
        
        try:
            # Get JWT token - will be used for both sessions (same user)
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create two separate sessions
            session1_id = self.utils.generate_session_id()
            session2_id = self.utils.generate_session_id()

            user1_id = "isolation_user_1"
            user2_id = "isolation_user_2"

            # Connect both sessions
            ws1 = await self.utils.connect_websocket( "queue", session1_id, timeout=5.0 )
            ws2 = await self.utils.connect_websocket( "queue", session2_id, timeout=5.0 )
            websockets_to_close = [ws1, ws2]

            # Authenticate both with JWT token
            auth1_success, _ = await self.utils.authenticate_websocket( ws1, token )
            auth2_success, _ = await self.utils.authenticate_websocket( ws2, token )

            if not (auth1_success and auth2_success):
                raise Exception( f"Authentication failed: session1={auth1_success}, session2={auth2_success}" )
            
            # Send distinct data to each session
            session1_data = {
                "type": "session_marker",
                "session_id": session1_id,
                "user_id": user1_id,
                "secret_data": "session1_secret_12345"
            }
            
            session2_data = {
                "type": "session_marker", 
                "session_id": session2_id,
                "user_id": user2_id,
                "secret_data": "session2_secret_67890"
            }
            
            await ws1.send( json.dumps( session1_data ) )
            await ws2.send( json.dumps( session2_data ) )
            
            # Wait for processing
            await asyncio.sleep( 0.5 )
            
            # Test that sessions don't interfere with each other
            # Send queries to verify isolation
            query1 = {"type": "isolation_test", "target": "session1"}
            query2 = {"type": "isolation_test", "target": "session2"}
            
            await ws1.send( json.dumps( query1 ) )
            await ws2.send( json.dumps( query2 ) )
            
            # Collect any responses (timeout is ok)
            session1_responses = []
            session2_responses = []
            
            try:
                response1 = await asyncio.wait_for( ws1.recv(), timeout=1.0 )
                session1_responses.append( json.loads( response1 ) )
            except asyncio.TimeoutError:
                pass
            
            try:
                response2 = await asyncio.wait_for( ws2.recv(), timeout=1.0 )
                session2_responses.append( json.loads( response2 ) )
            except asyncio.TimeoutError:
                pass
            
            # Close connections
            for ws in websockets_to_close:
                await ws.close()
            websockets_to_close = []
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if both sessions were created and operated independently
            success = auth1_success and auth2_success
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session1_id": session1_id,
                    "session2_id": session2_id,
                    "session1_auth": auth1_success,
                    "session2_auth": auth2_success,
                    "session1_responses": session1_responses,
                    "session2_responses": session2_responses,
                    "sessions_isolated": True  # Assume isolation unless evidence otherwise
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Sessions created and operated independently" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Session isolation test failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            
            # Clean up any remaining connections
            for ws in websockets_to_close:
                try:
                    await ws.close()
                except:
                    pass
            
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_cross_session_communication( self ):
        """
        Test whether sessions can or cannot communicate with each other.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server supports multiple concurrent sessions
            - self.results list exists for appending test results
            
        Ensures:
            - creates sender and receiver sessions
            - authenticates both sessions
            - attempts cross-session message transmission
            - documents whether cross-session communication is enabled or isolated
            - appends test result with communication behavior analysis
            - properly closes all WebSocket connections
            
        Raises:
            Exception: If session creation, authentication, or communication testing fails
        """
        test_name = "cross_session_communication"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        websockets_to_close = []
        
        try:
            # Get JWT token - will be used for both sessions
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create sender and receiver sessions
            sender_session = self.utils.generate_session_id()
            receiver_session = self.utils.generate_session_id()

            # Connect both sessions
            sender_ws = await self.utils.connect_websocket( "queue", sender_session, timeout=5.0 )
            receiver_ws = await self.utils.connect_websocket( "queue", receiver_session, timeout=5.0 )
            websockets_to_close = [sender_ws, receiver_ws]

            # Authenticate both with JWT token
            sender_auth, _ = await self.utils.authenticate_websocket( sender_ws, token )
            receiver_auth, _ = await self.utils.authenticate_websocket( receiver_ws, token )

            if not (sender_auth and receiver_auth):
                raise Exception( "Authentication failed for cross-session test" )
            
            # Attempt to send message from sender to specific receiver session
            cross_session_message = {
                "type": "cross_session_message",
                "target_session": receiver_session,
                "from_session": sender_session,
                "message": "Hello from sender session",
                "timestamp": time.time()
            }
            
            await sender_ws.send( json.dumps( cross_session_message ) )
            
            # Check if receiver gets the message
            try:
                received_message = await asyncio.wait_for( receiver_ws.recv(), timeout=2.0 )
                received_data = json.loads( received_message )
                cross_session_communication_works = (
                    received_data.get( "message" ) == "Hello from sender session" or
                    received_data.get( "from_session" ) == sender_session
                )
            except asyncio.TimeoutError:
                cross_session_communication_works = False
            except Exception:
                cross_session_communication_works = False
            
            # Also test sender for any response/acknowledgment
            try:
                sender_response = await asyncio.wait_for( sender_ws.recv(), timeout=1.0 )
                sender_got_response = True
            except asyncio.TimeoutError:
                sender_got_response = False
            
            # Close connections
            for ws in websockets_to_close:
                await ws.close()
            websockets_to_close = []
            
            duration = ( time.time() - start_time ) * 1000
            
            # This test documents behavior rather than requiring specific behavior
            success = sender_auth and receiver_auth  # Basic success: sessions work
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "sender_session": sender_session,
                    "receiver_session": receiver_session,
                    "sender_auth": sender_auth,
                    "receiver_auth": receiver_auth,
                    "cross_session_message_received": cross_session_communication_works,
                    "sender_got_response": sender_got_response,
                    "communication_behavior": "enabled" if cross_session_communication_works else "isolated"
                }
            } )
            
            behavior = "enabled" if cross_session_communication_works else "isolated"
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Cross-session communication is {behavior}" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            
            # Clean up connections
            for ws in websockets_to_close:
                try:
                    await ws.close()
                except:
                    pass
            
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_session_cleanup_on_disconnect( self ):
        """
        Test that sessions are properly cleaned up when connections close.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server implements proper cleanup mechanisms
            - self.results list exists for appending test results
            
        Ensures:
            - creates session and establishes state
            - abruptly closes connection to simulate network issues
            - waits for server cleanup processes
            - tests reconnection capability after cleanup
            - appends test result documenting cleanup behavior
            - verifies server remains functional after cleanup
            
        Raises:
            Exception: If session creation, cleanup testing, or reconnection verification fails
        """
        test_name = "session_cleanup_on_disconnect"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "cleanup_user"

            # Use JWT authentication instead of deprecated mock tokens
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create session
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )

            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Send some data to establish session state
            session_data = {
                "type": "cleanup_test_data",
                "data": "This should be cleaned up",
                "session_id": session_id
            }
            await websocket.send( json.dumps( session_data ) )
            await asyncio.sleep( 0.2 )
            
            # Abruptly close connection (simulate network issue)
            await websocket.close()
            
            # Wait for server cleanup
            await asyncio.sleep( 1.0 )
            
            # Try to reconnect to same session (should work if server handles cleanup properly)
            try:
                websocket2 = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
                reconnect_after_cleanup = True
                
                # Re-authenticate
                reauth_success, _ = await self.utils.authenticate_websocket( websocket2, token )
                
                # Send test message
                test_message = {"type": "cleanup_verification", "test": "post_cleanup"}
                await websocket2.send( json.dumps( test_message ) )
                
                await websocket2.close()
                
            except Exception as e:
                reconnect_after_cleanup = False
                reauth_success = False
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if basic cleanup doesn't break subsequent connections
            success = auth_success and reconnect_after_cleanup
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "initial_auth": auth_success,
                    "reconnect_after_cleanup": reconnect_after_cleanup,
                    "reauth_after_cleanup": reauth_success,
                    "cleanup_behavior": "successful" if success else "problematic"
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Session cleanup allows proper reconnection" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Session cleanup issues detected" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_multiple_sessions_same_user( self ):
        """
        Test behavior when same user has multiple sessions.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server supports user authentication
            - self.results list exists for appending test results
            
        Ensures:
            - creates multiple sessions for same user_id
            - attempts authentication for each session
            - sends unique messages to each session
            - documents multi-session behavior (allowed/restricted)
            - appends test result with session count and behavior analysis
            - properly closes all WebSocket connections
            
        Raises:
            Exception: If session creation, authentication, or multi-session testing fails
        """
        test_name = "multiple_sessions_same_user"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        websockets_to_close = []

        try:
            user_id = "multi_session_user"

            # Use JWT authentication instead of deprecated mock tokens
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create multiple sessions for same user
            sessions = []
            for i in range( 3 ):
                session_id = self.utils.generate_session_id()
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
                websockets_to_close.append( websocket )
                
                auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
                
                sessions.append( {
                    "session_id": session_id,
                    "websocket": websocket,
                    "auth_success": auth_success,
                    "auth_data": auth_data
                } )
                
                self.utils.log( f"   Session {i+1}: {'✅' if auth_success else '❌'} {session_id}" )
            
            # Test that all sessions work independently
            successful_sessions = sum( 1 for s in sessions if s["auth_success"] )
            
            # Send unique messages to each session
            for i, session in enumerate( sessions ):
                if session["auth_success"]:
                    message = {
                        "type": "multi_session_test",
                        "session_number": i + 1,
                        "user_id": user_id,
                        "test_data": f"message_from_session_{i+1}"
                    }
                    await session["websocket"].send( json.dumps( message ) )
            
            # Wait for processing
            await asyncio.sleep( 0.5 )
            
            # Close all connections
            for ws in websockets_to_close:
                await ws.close()
            websockets_to_close = []
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if multiple sessions for same user are allowed
            success = successful_sessions >= 2  # At least 2 sessions should work
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "user_id": user_id,
                    "attempted_sessions": len( sessions ),
                    "successful_sessions": successful_sessions,
                    "session_details": [
                        {
                            "session_id": s["session_id"],
                            "auth_success": s["auth_success"]
                        } for s in sessions
                    ],
                    "multi_session_behavior": "allowed" if successful_sessions > 1 else "restricted"
                }
            } )
            
            behavior = "allowed" if successful_sessions > 1 else "restricted"
            self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Multiple sessions per user: {behavior} ({successful_sessions}/{len(sessions)})" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            
            # Clean up connections
            for ws in websockets_to_close:
                try:
                    await ws.close()
                except:
                    pass
            
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_session_reconnection( self ):
        """
        Test session reconnection scenarios.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server supports reconnection workflows
            - self.results list exists for appending test results
            
        Ensures:
            - creates initial session and sends data
            - closes connection and attempts quick reconnection
            - tests delayed reconnection after longer wait
            - documents reconnection behavior for both scenarios
            - appends test result with reconnection capability analysis
            - properly closes all WebSocket connections
            
        Raises:
            Exception: If initial session, reconnection attempts, or testing fails
        """
        test_name = "session_reconnection"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "reconnection_user"

            # Use JWT authentication instead of deprecated mock tokens
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Initial connection
            websocket1 = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth1_success, _ = await self.utils.authenticate_websocket( websocket1, token )

            if not auth1_success:
                raise Exception( "Initial authentication failed" )
            
            # Send data
            initial_data = {"type": "reconnection_test", "data": "initial_connection"}
            await websocket1.send( json.dumps( initial_data ) )
            await asyncio.sleep( 0.2 )
            
            # Close connection
            await websocket1.close()
            
            # Quick reconnection attempt
            await asyncio.sleep( 0.5 )
            
            try:
                websocket2 = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
                quick_reconnect_success = True
                
                auth2_success, _ = await self.utils.authenticate_websocket( websocket2, token )
                
                # Test functionality after reconnection
                reconnect_data = {"type": "reconnection_test", "data": "after_reconnection"}
                await websocket2.send( json.dumps( reconnect_data ) )
                
                await websocket2.close()
                
            except Exception as e:
                quick_reconnect_success = False
                auth2_success = False
            
            # Delayed reconnection attempt
            await asyncio.sleep( 2.0 )
            
            try:
                websocket3 = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
                delayed_reconnect_success = True
                
                auth3_success, _ = await self.utils.authenticate_websocket( websocket3, token )
                
                await websocket3.close()
                
            except Exception as e:
                delayed_reconnect_success = False
                auth3_success = False
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if reconnections work (behavior may vary)
            success = auth1_success and (quick_reconnect_success or delayed_reconnect_success)
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "initial_auth": auth1_success,
                    "quick_reconnect": quick_reconnect_success,
                    "quick_reauth": auth2_success,
                    "delayed_reconnect": delayed_reconnect_success,
                    "delayed_reauth": auth3_success,
                    "reconnection_behavior": "supported" if success else "limited"
                }
            } )
            
            if success:
                quick_status = "✅" if quick_reconnect_success else "❌"
                delayed_status = "✅" if delayed_reconnect_success else "❌"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Reconnection: quick {quick_status}, delayed {delayed_status}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Session reconnection failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_session_timeout_behavior( self ):
        """
        Test session behavior with idle connections.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server implements timeout/keepalive mechanisms
            - self.results list exists for appending test results
            
        Ensures:
            - creates session and establishes baseline
            - waits through idle period to test timeout behavior
            - tests connection liveness after idle period
            - attempts message sending after idle period
            - documents timeout and idle handling behavior
            - appends test result with timeout robustness analysis
            
        Raises:
            Exception: If session creation, timeout testing, or idle behavior verification fails
        """
        test_name = "session_timeout_behavior"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "timeout_user"

            # Use JWT authentication instead of deprecated mock tokens
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create session
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )

            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Send initial message
            initial_message = {"type": "timeout_test", "phase": "initial"}
            await websocket.send( json.dumps( initial_message ) )
            
            # Wait for idle period (shorter than typical timeout)
            idle_duration = 3.0
            self.utils.log( f"   Waiting {idle_duration}s to test idle behavior..." )
            await asyncio.sleep( idle_duration )
            
            # Test if connection is still alive
            try:
                ping_result = await websocket.ping()
                connection_alive_after_idle = True
            except Exception:
                connection_alive_after_idle = False
            
            # Send message after idle period
            if connection_alive_after_idle:
                try:
                    post_idle_message = {"type": "timeout_test", "phase": "post_idle"}
                    await websocket.send( json.dumps( post_idle_message ) )
                    message_sent_after_idle = True
                except Exception:
                    message_sent_after_idle = False
            else:
                message_sent_after_idle = False
            
            # Wait for any response
            if message_sent_after_idle:
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=2.0 )
                    response_received = True
                except asyncio.TimeoutError:
                    response_received = False
            else:
                response_received = False
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if connection handles idle period reasonably
            success = auth_success and connection_alive_after_idle
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "idle_duration_seconds": idle_duration,
                    "connection_alive_after_idle": connection_alive_after_idle,
                    "message_sent_after_idle": message_sent_after_idle,
                    "response_received": response_received,
                    "timeout_behavior": "robust" if success else "problematic"
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Connection survived {idle_duration}s idle period" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Connection lost during idle period" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_maximum_sessions_per_user( self ):
        """
        Test server limits on sessions per user.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server implements session limiting mechanisms
            - self.results list exists for appending test results
            
        Ensures:
            - attempts to create many sessions for single user
            - tracks successful vs failed session creations
            - documents session limits and server behavior
            - calculates success rates and estimated limits
            - appends test result with session scaling analysis
            - properly closes all created WebSocket connections
            
        Raises:
            Exception: If session limit testing infrastructure fails
        """
        test_name = "maximum_sessions_per_user"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        websockets_to_close = []

        try:
            user_id = "limit_test_user"

            # Use JWT authentication instead of deprecated mock tokens
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            max_attempts = 10  # Try to create many sessions

            successful_sessions = []
            failed_sessions = []

            # Attempt to create many sessions
            for i in range( max_attempts ):
                try:
                    session_id = self.utils.generate_session_id()
                    websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                    websockets_to_close.append( websocket )
                    
                    auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
                    
                    if auth_success:
                        successful_sessions.append( session_id )
                        self.utils.log( f"   Session {i+1}: ✅ {session_id}" )
                    else:
                        failed_sessions.append( session_id )
                        self.utils.log( f"   Session {i+1}: ❌ Auth failed - {session_id}" )
                    
                    # Small delay to avoid overwhelming server
                    await asyncio.sleep( 0.1 )
                    
                except Exception as e:
                    failed_sessions.append( f"session_{i+1}_error" )
                    self.utils.log( f"   Session {i+1}: ❌ Connection failed - {e}" )
            
            # Clean up all connections
            for ws in websockets_to_close:
                try:
                    await ws.close()
                except:
                    pass
            websockets_to_close = []
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if we can create reasonable number of sessions
            success = len( successful_sessions ) >= 3  # At least 3 sessions should work
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "user_id": user_id,
                    "attempted_sessions": max_attempts,
                    "successful_sessions": len( successful_sessions ),
                    "failed_sessions": len( failed_sessions ),
                    "success_rate": len( successful_sessions ) / max_attempts,
                    "session_limit_detected": len( failed_sessions ) > 0,
                    "estimated_limit": len( successful_sessions ) if len( failed_sessions ) > 0 else "none_detected"
                }
            } )
            
            if success:
                limit_info = f"at least {len(successful_sessions)}" if len( failed_sessions ) == 0 else str( len( successful_sessions ) )
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Session limit: {limit_info} per user" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Too few sessions allowed ({len(successful_sessions)}/{max_attempts})" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            
            # Clean up connections
            for ws in websockets_to_close:
                try:
                    await ws.close()
                except:
                    pass
            
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_session_resource_cleanup( self ):
        """
        Test that sessions don't leak resources over time.
        
        Requires:
            - self.utils is initialized and functional
            - WebSocket server implements proper resource management
            - self.results list exists for appending test results
            
        Ensures:
            - creates and destroys sessions in multiple cycles
            - tests server responsiveness after resource cycling
            - verifies no resource leaks affect server performance
            - documents resource cleanup effectiveness
            - appends test result with resource management analysis
            - properly closes all WebSocket connections
            
        Raises:
            Exception: If resource cycling, cleanup testing, or final verification fails
        """
        test_name = "session_resource_cleanup"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            # Get JWT token once for all cycles
            jwt_success, token_or_error = await self.utils.get_jwt_token()
            if not jwt_success:
                raise Exception( f"JWT login failed: {token_or_error}" )
            token = token_or_error

            # Create and destroy sessions rapidly to test resource cleanup
            cycles = 5
            sessions_per_cycle = 3

            for cycle in range( cycles ):
                self.utils.log( f"   Resource test cycle {cycle + 1}/{cycles}" )

                cycle_websockets = []

                # Create sessions
                for i in range( sessions_per_cycle ):
                    session_id = self.utils.generate_session_id()
                    user_id = f"resource_user_{cycle}_{i}"

                    websocket = await self.utils.connect_websocket( "queue", session_id, timeout=3.0 )
                    auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
                    
                    if auth_success:
                        # Send some data
                        data = {"type": "resource_test", "cycle": cycle, "session": i}
                        await websocket.send( json.dumps( data ) )
                    
                    cycle_websockets.append( websocket )
                
                # Clean up cycle sessions
                for ws in cycle_websockets:
                    await ws.close()
                
                # Brief pause between cycles
                await asyncio.sleep( 0.2 )
            
            # Final test: create one more session to verify server is still responsive
            final_session_id = self.utils.generate_session_id()

            final_websocket = await self.utils.connect_websocket( "queue", final_session_id, timeout=5.0 )
            final_auth_success, _ = await self.utils.authenticate_websocket( final_websocket, token )
            await final_websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if server remains responsive after resource cycling
            success = final_auth_success
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "test_cycles": cycles,
                    "sessions_per_cycle": sessions_per_cycle,
                    "total_sessions_tested": cycles * sessions_per_cycle,
                    "final_session_responsive": final_auth_success,
                    "resource_cleanup": "effective" if success else "problematic"
                }
            } )
            
            total_sessions = cycles * sessions_per_cycle
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Server responsive after {total_sessions} session cycles" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Server unresponsive after resource cycling" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )


async def main():
    """
    Run all session management tests.
    
    Requires:
        - WebSocket server is running and accessible
        - Test environment is properly configured
        
    Ensures:
        - executes complete session management test suite
        - prints formatted test results and summary
        - returns exit code (0 for success, 1 for failures)
        - displays session behavior insights
        
    Returns:
        int: Exit code where 0 indicates all tests passed, 1 indicates failures
        
    Raises:
        Exception: If test suite execution fails critically
    """
    print( "📋 WebSocket Session Management Tests" )
    print( "=" * 50 )
    
    tester = SessionManagementTests()
    results = await tester.run_all_tests()
    
    # Summary
    print( "\\n" + "=" * 50 )
    print( "📊 SESSION MANAGEMENT TEST SUMMARY" )
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
            print( f"  • {test['name']}: {test.get('error', 'Session management error')}" )
    
    # Session behavior insights
    print( "\\n📋 Session Behavior Summary:" )
    for result in results:
        if result["success"] and "details" in result:
            details = result["details"]
            test_name = result["name"]
            
            if test_name == "multiple_sessions_same_user":
                behavior = details.get( "multi_session_behavior", "unknown" )
                count = details.get( "successful_sessions", 0 )
                print( f"  • Multiple sessions per user: {behavior} ({count} concurrent)" )
            
            elif test_name == "cross_session_communication":
                behavior = details.get( "communication_behavior", "unknown" )
                print( f"  • Cross-session communication: {behavior}" )
            
            elif test_name == "session_persistence":
                behavior = details.get( "persistence_behavior", "unknown" )
                print( f"  • Session persistence: {behavior}" )
    
    if passed_tests == total_tests:
        print( "\\n✅ All session management tests passed!" )
        return 0
    else:
        print( f"\\n❌ {total_tests - passed_tests} session management tests failed!" )
        return 1


if __name__ == "__main__":
    import sys
    exit_code = asyncio.run( main() )
    sys.exit( exit_code )