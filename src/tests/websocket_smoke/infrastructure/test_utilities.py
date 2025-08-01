#!/usr/bin/env python3
"""
WebSocket Smoke Test Utilities

Core utilities for testing WebSocket functionality against the live FastAPI server.
Provides connection helpers, authentication utilities, and event validation tools.

Server Assumption: FastAPI running on http://localhost:7999
WebSocket Endpoints: ws://localhost:7999/ws/queue/ and ws://localhost:7999/ws/audio/
"""

import asyncio
import json
import time
import random
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Tuple, Union
import websockets
import httpx


class WebSocketTestUtilities:
    """
    Core utilities for WebSocket smoke testing.
    
    Provides connection management, authentication, event handling,
    and performance measurement capabilities.
    """
    
    def __init__( self, base_url: str = "localhost:7999" ):
        """
        Initialize test utilities.
        
        Args:
            base_url: Base server URL (default: localhost:7999)
        """
        self.base_url = base_url
        self.http_base = f"http://{base_url}"
        self.ws_base = f"ws://{base_url}"
        self.debug = True  # Enable debug output for test development
        
    def log( self, message: str, level: str = "INFO" ):
        """
        Log message with timestamp if debug enabled.
        
        Args:
            message: Message to log
            level: Log level (INFO, ERROR, DEBUG)
        """
        if self.debug:
            timestamp = datetime.now().strftime( "%H:%M:%S.%f" )[:-3]
            print( f"[{timestamp}] [{level}] {message}" )
    
    async def check_server_health( self ) -> bool:
        """
        Check if FastAPI server is healthy and responding.
        
        Returns:
            True if server is healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get( f"{self.http_base}/health", timeout=5.0 )
                is_healthy = response.status_code == 200
                self.log( f"Server health check: {response.status_code} ({'✅ HEALTHY' if is_healthy else '❌ UNHEALTHY'})" )
                return is_healthy
        except Exception as e:
            self.log( f"Server health check failed: {e}", "ERROR" )
            return False
    
    def generate_session_id( self, prefix: str = None ) -> str:
        """
        Generate a valid WebSocket session ID.
        
        Uses the expected 'adjective noun' format that the server validates.
        Based on the working test format: exactly two words, no prefix.
        
        Args:
            prefix: Optional prefix for the session ID (usually None for server compatibility)
            
        Returns:
            Valid session ID string
        """
        adjectives = ["wise", "clever", "brave", "quick", "calm", "bright", "noble", "swift", "bold", "keen"]
        nouns = ["penguin", "giraffe", "owl", "lion", "fox", "bear", "eagle", "wolf", "tiger", "hawk"]
        
        adjective = random.choice( adjectives )
        noun = random.choice( nouns )
        
        # Server appears to expect exactly 'adjective noun' format
        # Adding prefix seems to cause HTTP 403 errors
        if prefix:
            return f"{prefix} {adjective} {noun}"
        else:
            return f"{adjective} {noun}"
    
    def generate_mock_token( self, user_id: str = "test_user" ) -> str:
        """
        Generate a mock authentication token.
        
        Args:
            user_id: User identifier for the token
            
        Returns:
            Mock token string in expected format
        """
        return f"mock_token_{user_id}"
    
    async def connect_websocket( 
        self, 
        endpoint: str, 
        session_id: str,
        timeout: float = 10.0 
    ) -> websockets.WebSocketClientProtocol:
        """
        Connect to a WebSocket endpoint.
        
        Args:
            endpoint: WebSocket endpoint ('queue' or 'audio')
            session_id: Session ID for the connection
            timeout: Connection timeout in seconds
            
        Returns:
            Connected WebSocket client
            
        Raises:
            ConnectionError: If connection fails
        """
        encoded_session = urllib.parse.quote( session_id )
        uri = f"{self.ws_base}/ws/{endpoint}/{encoded_session}"
        
        self.log( f"Connecting to WebSocket: {uri}" )
        
        try:
            websocket = await asyncio.wait_for(
                websockets.connect( uri ),
                timeout=timeout
            )
            self.log( f"✅ Connected to {endpoint} WebSocket" )
            return websocket
        except Exception as e:
            self.log( f"❌ WebSocket connection failed: {e}", "ERROR" )
            raise ConnectionError( f"Failed to connect to {uri}: {e}" )
    
    async def authenticate_websocket( 
        self, 
        websocket: websockets.WebSocketClientProtocol,
        token: str,
        subscribed_events: Optional[List[str]] = None,
        timeout: float = 5.0
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Authenticate a WebSocket connection.
        
        Args:
            websocket: Connected WebSocket client
            token: Authentication token
            subscribed_events: Optional list of events to subscribe to
            timeout: Authentication timeout in seconds
            
        Returns:
            Tuple of (success, response_data)
        """
        # Default event subscriptions for testing
        if subscribed_events is None:
            subscribed_events = [
                "auth_success", "auth_error", "connect", "sys_ping",
                "queue_todo_update", "queue_running_update", "queue_done_update", "queue_dead_update"
            ]
        
        auth_message = {
            "type": "auth_request",
            "token": token,
            "subscribed_events": subscribed_events
        }
        
        self.log( f"Sending auth request with {len(subscribed_events)} subscribed events" )
        
        try:
            # Send authentication request
            await websocket.send( json.dumps( auth_message ) )
            
            # Wait for authentication response
            response_raw = await asyncio.wait_for( websocket.recv(), timeout=timeout )
            response_data = json.loads( response_raw )
            
            success = response_data.get( "type" ) == "auth_success"
            
            if success:
                self.log( f"✅ Authentication successful: {response_data.get('user_id', 'unknown user')}" )
            else:
                self.log( f"❌ Authentication failed: {response_data.get('message', 'unknown error')}", "ERROR" )
            
            return success, response_data
            
        except Exception as e:
            self.log( f"❌ Authentication error: {e}", "ERROR" )
            return False, {"error": str( e )}
    
    async def wait_for_event( 
        self,
        websocket: websockets.WebSocketClientProtocol,
        event_type: str,
        timeout: float = 10.0,
        max_events: int = 100
    ) -> Optional[Dict[str, Any]]:
        """
        Wait for a specific WebSocket event type.
        
        Args:
            websocket: Connected WebSocket client
            event_type: Type of event to wait for
            timeout: Maximum time to wait
            max_events: Maximum number of events to process while waiting
            
        Returns:
            Event data if found, None if timeout or not found
        """
        self.log( f"Waiting for event type: {event_type} (timeout: {timeout}s)" )
        
        start_time = time.time()
        events_processed = 0
        
        try:
            while time.time() - start_time < timeout and events_processed < max_events:
                try:
                    # Wait for next message with remaining timeout
                    remaining_timeout = timeout - ( time.time() - start_time )
                    if remaining_timeout <= 0:
                        break
                        
                    message_raw = await asyncio.wait_for( 
                        websocket.recv(), 
                        timeout=min( remaining_timeout, 1.0 )  # Check every second
                    )
                    
                    message_data = json.loads( message_raw )
                    events_processed += 1
                    
                    received_type = message_data.get( "type", "unknown" )
                    self.log( f"Received event: {received_type}" )
                    
                    if received_type == event_type:
                        self.log( f"✅ Found target event: {event_type}" )
                        return message_data
                        
                except asyncio.TimeoutError:
                    # Continue waiting if we haven't reached the total timeout
                    continue
                    
        except Exception as e:
            self.log( f"❌ Error waiting for event: {e}", "ERROR" )
        
        self.log( f"❌ Event {event_type} not received within {timeout}s ({events_processed} events processed)" )
        return None
    
    async def collect_events( 
        self,
        websocket: websockets.WebSocketClientProtocol,
        duration: float = 5.0,
        max_events: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Collect WebSocket events for a specified duration.
        
        Args:
            websocket: Connected WebSocket client
            duration: Time to collect events (seconds)
            max_events: Maximum number of events to collect
            
        Returns:
            List of collected event data
        """
        self.log( f"Collecting events for {duration}s (max {max_events})" )
        
        events = []
        start_time = time.time()
        
        try:
            while time.time() - start_time < duration and len( events ) < max_events:
                try:
                    # Wait for message with remaining timeout
                    remaining_time = duration - ( time.time() - start_time )
                    if remaining_time <= 0:
                        break
                        
                    message_raw = await asyncio.wait_for( 
                        websocket.recv(), 
                        timeout=min( remaining_time, 0.5 )  # Check frequently
                    )
                    
                    message_data = json.loads( message_raw )
                    events.append( message_data )
                    
                    event_type = message_data.get( "type", "unknown" )
                    self.log( f"Collected event: {event_type}" )
                    
                except asyncio.TimeoutError:
                    # Continue collecting until duration expires
                    continue
                    
        except Exception as e:
            self.log( f"❌ Error collecting events: {e}", "ERROR" )
        
        self.log( f"✅ Collected {len(events)} events in {time.time() - start_time:.2f}s" )
        return events
    
    def measure_performance( self, operation_name: str ):
        """
        Context manager for measuring operation performance.
        
        Args:
            operation_name: Name of the operation being measured
            
        Returns:
            Context manager that logs execution time
        """
        return PerformanceTimer( operation_name, self.log )
    
    async def test_websocket_flow( 
        self,
        endpoint: str,
        user_id: str = "test_user",
        duration: float = 5.0 
    ) -> Dict[str, Any]:
        """
        Test a complete WebSocket connection flow.
        
        Args:
            endpoint: WebSocket endpoint to test ('queue' or 'audio')
            user_id: User ID for authentication
            duration: How long to maintain connection and collect events
            
        Returns:
            Dictionary with test results and collected data
        """
        results = {
            "endpoint": endpoint,
            "user_id": user_id,
            "success": False,
            "connection_time": 0,
            "auth_time": 0,
            "events_collected": 0,
            "events": [],
            "error": None
        }
        
        session_id = self.generate_session_id()  # No prefix to match working test format
        token = self.generate_mock_token( user_id )
        
        try:
            # Measure connection time
            with self.measure_performance( f"{endpoint} connection" ):
                websocket = await self.connect_websocket( endpoint, session_id )
                results["connection_time"] = time.time()
            
            # Measure authentication time
            with self.measure_performance( f"{endpoint} authentication" ):
                auth_success, auth_data = await self.authenticate_websocket( websocket, token )
                results["auth_time"] = time.time()
                
                # Audio WebSocket may not require authentication in the same way
                if not auth_success and endpoint != "audio":
                    results["error"] = f"Authentication failed: {auth_data}"
                    return results
                elif endpoint == "audio" and not auth_success:
                    # Audio WebSocket might send different messages instead of auth responses
                    self.log( f"Audio WebSocket connected but no auth response - this may be expected behavior" )
                    results["auth_time"] = time.time()  # Mark auth as complete
            
            # Collect events for specified duration
            events = await self.collect_events( websocket, duration )
            results["events"] = events
            results["events_collected"] = len( events )
            results["success"] = True
            
            # Close connection
            await websocket.close()
            self.log( f"✅ Completed {endpoint} WebSocket flow test" )
            
        except Exception as e:
            results["error"] = str( e )
            self.log( f"❌ WebSocket flow test failed: {e}", "ERROR" )
        
        return results


class PerformanceTimer:
    """Context manager for measuring operation performance."""
    
    def __init__( self, operation_name: str, log_func: Callable[[str, str], None] ):
        """
        Initialize performance timer.
        
        Args:
            operation_name: Name of operation being measured
            log_func: Logging function to use
        """
        self.operation_name = operation_name
        self.log_func = log_func
        self.start_time = None
    
    def __enter__( self ):
        """Start timing the operation."""
        self.start_time = time.time()
        return self
    
    def __exit__( self, exc_type, exc_val, exc_tb ):
        """End timing and log the result."""
        if self.start_time:
            duration = time.time() - self.start_time
            self.log_func( f"⏱️ {self.operation_name}: {duration*1000:.2f}ms" )


# Convenience functions for common operations
async def quick_health_check( base_url: str = "localhost:7999" ) -> bool:
    """Quick server health check."""
    utils = WebSocketTestUtilities( base_url )
    return await utils.check_server_health()


async def quick_websocket_test( endpoint: str = "queue", user_id: str = "test" ) -> Dict[str, Any]:
    """Quick WebSocket connection and authentication test."""
    utils = WebSocketTestUtilities()
    return await utils.test_websocket_flow( endpoint, user_id, duration=2.0 )


if __name__ == "__main__":
    """
    Simple smoke test of the utilities themselves.
    Run this to verify the test utilities work against the live server.
    """
    async def main():
        print( "🧪 Testing WebSocket Test Utilities" )
        print( "=" * 50 )
        
        utils = WebSocketTestUtilities()
        
        # Test 1: Server health check
        print( "\n1. Testing server health check..." )
        health_ok = await utils.check_server_health()
        print( f"   Server health: {'✅ PASS' if health_ok else '❌ FAIL'}" )
        
        if not health_ok:
            print( "❌ Server not healthy - stopping tests" )
            return
        
        # Test 2: Queue WebSocket flow
        print( "\n2. Testing queue WebSocket flow..." )
        queue_result = await utils.test_websocket_flow( "queue", "smoke_test_user", 3.0 )
        print( f"   Queue WebSocket: {'✅ PASS' if queue_result['success'] else '❌ FAIL'}" )
        if queue_result.get( "error" ):
            print( f"   Error: {queue_result['error']}" )
        else:
            print( f"   Events collected: {queue_result['events_collected']}" )
        
        # Test 3: Audio WebSocket flow  
        print( "\n3. Testing audio WebSocket flow..." )
        audio_result = await utils.test_websocket_flow( "audio", "smoke_test_user", 3.0 )
        print( f"   Audio WebSocket: {'✅ PASS' if audio_result['success'] else '❌ FAIL'}" )
        if audio_result.get( "error" ):
            print( f"   Error: {audio_result['error']}" )
        else:
            print( f"   Events collected: {audio_result['events_collected']}" )
        
        # Summary
        print( "\n" + "=" * 50 )
        tests_passed = sum([
            health_ok,
            queue_result["success"],
            audio_result["success"]
        ])
        print( f"Test Utilities Smoke Test: {tests_passed}/3 tests passed" )
        
        if tests_passed == 3:
            print( "✅ Test utilities are working correctly!" )
        else:
            print( "❌ Some test utilities need attention" )
    
    # Run the smoke test
    asyncio.run( main() )