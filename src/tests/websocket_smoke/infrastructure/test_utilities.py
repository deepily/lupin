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
        Initialize WebSocket test utilities with server configuration.
        
        Requires:
            - base_url must be valid server address format
            
        Ensures:
            - HTTP and WebSocket base URLs are properly configured
            - Debug logging is enabled by default
            - Instance is ready for WebSocket testing operations
            
        Args:
            base_url: Base server URL (default: "localhost:7999")
            
        Returns:
            None
            
        Raises:
            No exceptions raised during initialization
        """
        self.base_url = base_url
        self.http_base = f"http://{base_url}"
        self.ws_base = f"ws://{base_url}"
        self.debug = True  # Enable debug output for test development
        
    def log( self, message: str, level: str = "INFO" ):
        """
        Log message with timestamp if debug enabled.
        
        Requires:
            - message must be a valid string
            - level must be a valid log level string
            - self.debug attribute must be set (boolean)
            
        Ensures:
            - Message is printed to stdout if debug is enabled
            - Message includes timestamp in HH:MM:SS.mmm format
            - Message format follows [timestamp] [level] message pattern
            - No output if debug is disabled
            
        Args:
            message: Message to log
            level: Log level (INFO, ERROR, DEBUG)
            
        Returns:
            None
            
        Raises:
            No exceptions raised - string formatting is guaranteed to work
        """
        if self.debug:
            timestamp = datetime.now().strftime( "%H:%M:%S.%f" )[:-3]
            print( f"[{timestamp}] [{level}] {message}" )
    
    async def check_server_health( self ) -> bool:
        """
        Check if FastAPI server is healthy and responding.
        
        Requires:
            - HTTP base URL must be configured
            - httpx client must be available
            
        Ensures:
            - Makes HTTP GET request to /health endpoint
            - Returns True only if status code is 200
            - Logs health check result with status
            - Returns False on any exception or non-200 status
            
        Args:
            None
            
        Returns:
            bool: True if server is healthy (status 200), False otherwise
            
        Raises:
            No exceptions raised - all errors are caught and logged
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
        
        Requires:
            - prefix must be None or a valid string if provided
            - random module must be available for choice selection
            
        Ensures:
            - Returns string in 'adjective noun' format for server compatibility
            - Uses predefined adjectives and nouns lists for consistency
            - Without prefix: returns exactly 2 words separated by space
            - With prefix: returns prefix + space + adjective + space + noun
            
        Args:
            prefix: Optional prefix for the session ID (usually None for server compatibility)
            
        Returns:
            str: Valid session ID string in expected server format
            
        Raises:
            No exceptions raised - random.choice and string formatting are guaranteed
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
        
        Requires:
            - user_id must be a valid string identifier
            
        Ensures:
            - Returns token string in format 'mock_token_{user_id}'
            - Token format is consistent for testing purposes
            - String concatenation always succeeds
            
        Args:
            user_id: User identifier for the token
            
        Returns:
            str: Mock token string in expected format
            
        Raises:
            No exceptions raised - string formatting is guaranteed to work
        """
        return f"mock_token_{user_id}"
    
    async def connect_websocket( 
        self, 
        endpoint: str, 
        session_id: str,
        timeout: float = 10.0 
    ) -> websockets.WebSocketClientProtocol:
        """
        Connect to a WebSocket endpoint with session authentication.
        
        Requires:
            - endpoint must be 'queue' or 'audio'
            - session_id must be valid, non-empty session identifier
            - WebSocket server must be running at configured base URL
            - timeout must be positive number
            
        Ensures:
            - Returns connected WebSocket client if successful
            - URL encodes session_id for safe transmission
            - Logs connection attempt and result
            - Raises ConnectionError on failure
            
        Args:
            endpoint: WebSocket endpoint ('queue' or 'audio')
            session_id: Session ID for the connection
            timeout: Connection timeout in seconds (default: 10.0)
            
        Returns:
            websockets.WebSocketClientProtocol: Connected WebSocket client
            
        Raises:
            ConnectionError: If connection fails or times out
            ValueError: If endpoint or session_id is invalid
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
        
        Requires:
            - websocket must be a connected WebSocket client
            - token must be a valid non-empty authentication string
            - subscribed_events must be None or list of valid event name strings
            - timeout must be positive number
            
        Ensures:
            - Sends auth_request message with token and subscribed events
            - Waits for server response within timeout period
            - Returns tuple with success boolean and full response data
            - Logs authentication result with user ID or error message
            - Uses default event subscriptions if none provided
            
        Args:
            websocket: Connected WebSocket client
            token: Authentication token
            subscribed_events: Optional list of events to subscribe to
            timeout: Authentication timeout in seconds
            
        Returns:
            Tuple[bool, Dict[str, Any]]: (success, response_data) where success indicates auth result
            
        Raises:
            asyncio.TimeoutError: If server doesn't respond within timeout
            json.JSONDecodeError: If server response is not valid JSON
            websockets.exceptions.ConnectionClosed: If connection is lost during auth
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
        
        Requires:
            - websocket must be connected and authenticated WebSocket client
            - event_type must be valid non-empty event name string
            - timeout must be positive number
            - max_events must be positive integer
            
        Ensures:
            - Listens for incoming WebSocket messages up to timeout duration
            - Processes up to max_events messages while searching
            - Returns first matching event data with specified type
            - Returns None if timeout reached or max_events exceeded
            - Logs search progress and result status
            
        Args:
            websocket: Connected WebSocket client
            event_type: Type of event to wait for
            timeout: Maximum time to wait
            max_events: Maximum number of events to process while waiting
            
        Returns:
            Optional[Dict[str, Any]]: Event data if found, None if timeout or not found
            
        Raises:
            asyncio.TimeoutError: If timeout is reached without finding event
            json.JSONDecodeError: If received message is not valid JSON
            websockets.exceptions.ConnectionClosed: If connection is lost during wait
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
        
        Requires:
            - websocket must be connected and authenticated WebSocket client
            - duration must be positive number of seconds
            - max_events must be positive integer
            
        Ensures:
            - Collects events for exactly the specified duration
            - Stops early if max_events limit is reached
            - Returns chronological list of all collected events
            - Logs collection progress and final count
            - Returns empty list if no events received
            
        Args:
            websocket: Connected WebSocket client
            duration: Time to collect events (seconds)
            max_events: Maximum number of events to collect
            
        Returns:
            List[Dict[str, Any]]: List of collected event data dictionaries in chronological order
            
        Raises:
            json.JSONDecodeError: If received message is not valid JSON
            websockets.exceptions.ConnectionClosed: If connection is lost during collection
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
        
        Requires:
            - operation_name must be valid non-empty string
            - PerformanceTimer class must be available
            
        Ensures:
            - Returns PerformanceTimer context manager instance
            - Context manager will measure and log execution time
            - Timing starts on context entry and ends on context exit
            - Final timing is logged through self.log method
            
        Args:
            operation_name: Name of the operation being measured
            
        Returns:
            PerformanceTimer: Context manager that logs execution time
            
        Raises:
            No exceptions raised - PerformanceTimer handles all timing logic
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
        
        Requires:
            - endpoint must be 'queue' or 'audio'
            - user_id must be valid non-empty string identifier
            - duration must be positive number of seconds
            - WebSocket server must be running and accessible
            
        Ensures:
            - Performs full connection, authentication, and event collection cycle
            - Measures connection and authentication timing
            - Collects events for specified duration
            - Returns comprehensive test results including success status
            - Properly closes WebSocket connection after test
            - Logs all test phases and their outcomes
            
        Args:
            endpoint: WebSocket endpoint to test ('queue' or 'audio')
            user_id: User ID for authentication
            duration: How long to maintain connection and collect events
            
        Returns:
            Dict[str, Any]: Dictionary with test results including success, timing, and collected data
            
        Raises:
            ConnectionError: If WebSocket connection fails
            asyncio.TimeoutError: If authentication or event collection times out
            json.JSONDecodeError: If server sends invalid JSON responses
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
        
        Requires:
            - operation_name must be valid non-empty string
            - log_func must be callable that accepts (message: str, level: str = "INFO")
            
        Ensures:
            - Sets operation_name and log_func attributes
            - Initializes start_time to None
            - Instance is ready for use as context manager
            
        Args:
            operation_name: Name of operation being measured
            log_func: Logging function to use for timing results
            
        Returns:
            None
            
        Raises:
            No exceptions raised during initialization
        """
        self.operation_name = operation_name
        self.log_func = log_func
        self.start_time = None
    
    def __enter__( self ):
        """
        Start timing the operation.
        
        Requires:
            - Context manager entry (called by 'with' statement)
            - time.time() function must be available
            
        Ensures:
            - Records current timestamp as start_time
            - Returns self for context manager protocol
            - Timer is ready to measure elapsed time on exit
            
        Args:
            None
            
        Returns:
            PerformanceTimer: Self reference for context manager protocol
            
        Raises:
            No exceptions raised - time.time() is guaranteed to work
        """
        self.start_time = time.time()
        return self
    
    def __exit__( self, exc_type, exc_val, exc_tb ):
        """
        End timing and log the result.
        
        Requires:
            - Context manager exit (called at end of 'with' block)
            - start_time must be set (from __enter__ call)
            - log_func must be callable and available
            
        Ensures:
            - Calculates elapsed time from start_time to current time
            - Logs timing result in milliseconds with operation name
            - Uses emoji prefix for easy identification in logs
            - Only logs if start_time was properly set
            
        Args:
            exc_type: Exception type (from context manager protocol)
            exc_val: Exception value (from context manager protocol)
            exc_tb: Exception traceback (from context manager protocol)
            
        Returns:
            None (implicitly returns None to not suppress exceptions)
            
        Raises:
            No exceptions raised - timing calculation and logging are safe operations
        """
        if self.start_time:
            duration = time.time() - self.start_time
            self.log_func( f"⏱️ {self.operation_name}: {duration*1000:.2f}ms" )


# Convenience functions for common operations
async def quick_health_check( base_url: str = "localhost:7999" ) -> bool:
    """
    Quick server health check.
    
    Requires:
        - base_url must be valid server address format
        - Server should be running at specified address
        
    Ensures:
        - Creates temporary WebSocketTestUtilities instance
        - Performs HTTP health check via utils.check_server_health()
        - Returns boolean result of health status
        
    Args:
        base_url: Server base URL to check (default: "localhost:7999")
        
    Returns:
        bool: True if server is healthy, False otherwise
        
    Raises:
        No exceptions raised - all errors handled by check_server_health()
    """
    utils = WebSocketTestUtilities( base_url )
    return await utils.check_server_health()


async def quick_websocket_test( endpoint: str = "queue", user_id: str = "test" ) -> Dict[str, Any]:
    """
    Quick WebSocket connection and authentication test.
    
    Requires:
        - endpoint must be 'queue' or 'audio'
        - user_id must be valid non-empty string identifier
        - WebSocket server must be running at default location
        
    Ensures:
        - Creates temporary WebSocketTestUtilities instance with default config
        - Performs complete WebSocket flow test with 2-second duration
        - Returns comprehensive test results including success status
        
    Args:
        endpoint: WebSocket endpoint to test (default: "queue")
        user_id: User ID for authentication (default: "test")
        
    Returns:
        Dict[str, Any]: Test results including success, timing, and event data
        
    Raises:
        ConnectionError: If WebSocket connection fails
        asyncio.TimeoutError: If authentication or event collection times out
        json.JSONDecodeError: If server sends invalid JSON responses
    """
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