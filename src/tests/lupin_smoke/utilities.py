#!/usr/bin/env python3
"""
Lupin Smoke Test Utilities

Shared utilities for testing Lupin functionality including HTTP requests,
WebSocket connections, and common test patterns.
"""

import asyncio
import json
import time
import httpx
import websockets
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import quote


class LupinTestClient:
    """
    Test client for Lupin HTTP and WebSocket functionality.
    
    Provides convenient methods for testing API endpoints and WebSocket connections
    with proper authentication and error handling.
    """
    
    def __init__(self, base_url: str = "http://localhost:7999", debug: bool = False):
        """
        Initialize test client.
        
        Args:
            base_url: Base URL for HTTP requests
            debug: Enable debug output
        """
        self.base_url = base_url
        self.debug = debug
        self.session_id = "test_session_" + str(int(time.time()))
        self.auth_token = "Bearer mock_token_email_test@example.com"
        
        if self.debug:
            print(f"[TEST CLIENT] Initialized with base_url={base_url}, session_id={self.session_id}")
    
    async def http_request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """
        Make HTTP request with automatic authentication.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for httpx
            
        Returns:
            httpx.Response object
        """
        url = f"{self.base_url}{endpoint}"
        
        # Add authentication header if not provided
        headers = kwargs.get('headers', {})
        if 'Authorization' not in headers:
            headers['Authorization'] = self.auth_token
        kwargs['headers'] = headers
        
        if self.debug:
            print(f"[HTTP] {method} {url}")
        
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, **kwargs)
            
        if self.debug:
            print(f"[HTTP] Response: {response.status_code}")
            
        return response
    
    async def get_session_id(self) -> str:
        """
        Get a valid session ID from the API.
        
        Returns:
            Session ID string in 'adjective noun' format
        """
        response = await self.http_request("GET", "/api/get-session-id")
        if response.status_code != 200:
            raise Exception(f"Failed to get session ID: {response.status_code}")
        
        data = response.json()
        session_id = data.get("session_id")
        if not session_id:
            raise Exception("Session ID not found in response")
        
        if self.debug:
            print(f"[SESSION] Generated session ID: {session_id}")
        
        return session_id
    
    async def websocket_connect(self, endpoint: str, subscribed_events: List[str] = None) -> websockets.WebSocketServerProtocol:
        """
        Connect to WebSocket endpoint with authentication.
        
        Args:
            endpoint: WebSocket endpoint path (e.g., '/ws/queue/{session_id}' or '/ws/audio/session_id')
                     If endpoint contains '{session_id}', it will be replaced with a valid session ID
            subscribed_events: List of events to subscribe to
            
        Returns:
            Connected WebSocket
        """
        if subscribed_events is None:
            subscribed_events = ["sys_ping", "auth_success", "auth_error"]
        
        # Handle session ID placeholder
        session_id_for_auth = self.session_id  # Default session ID for auth
        if "{session_id}" in endpoint:
            # Generate a valid session ID from the API
            real_session_id = await self.get_session_id()
            encoded_session_id = quote(real_session_id)  # URL encode for path
            endpoint = endpoint.replace("{session_id}", encoded_session_id)
            session_id_for_auth = real_session_id  # Use unencoded for auth message
            
            # Store the generated session ID for use by other methods
            self.last_generated_session_id = real_session_id
            
            if self.debug:
                print(f"[WS] Using session ID: {real_session_id} (encoded: {encoded_session_id})")
        
        ws_url = f"ws://localhost:7999{endpoint}"
        
        if self.debug:
            print(f"[WS] Connecting to {ws_url}")
        
        websocket = await websockets.connect(ws_url)
        
        # Send authentication with unencoded session ID
        auth_message = {
            "type": "auth_request",
            "token": self.auth_token.replace("Bearer ", ""),  # Strip Bearer prefix
            "session_id": session_id_for_auth,
            "subscribed_events": subscribed_events
        }
        
        await websocket.send(json.dumps(auth_message))
        
        if self.debug:
            print(f"[WS] Sent auth request with session: {session_id_for_auth}")
        
        # Wait for auth response
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            auth_data = json.loads(response)
            
            if self.debug:
                print(f"[WS] Received: {auth_data.get('type', 'unknown')}")
            
            if auth_data.get("type") == "auth_success":
                if self.debug:
                    print(f"[WS] Authentication successful")
                return websocket
            elif auth_data.get("type") == "auth_error":
                raise Exception(f"WebSocket authentication failed: {auth_data.get('message', 'Unknown error')}")
            elif auth_data.get("type") == "audio_streaming_status":
                # Audio WebSocket doesn't send auth_success, just confirms connection
                if auth_data.get("status") == "success":
                    if self.debug:
                        print(f"[WS] Audio WebSocket connected successfully")
                    return websocket
                else:
                    raise Exception(f"Audio WebSocket connection failed: {auth_data}")
            else:
                # Some other endpoints send connection confirmation first
                if auth_data.get("type") == "connect":
                    if self.debug:
                        print(f"[WS] Connection confirmed, waiting for auth...")
                    # Wait for auth response
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    auth_data = json.loads(response)
                    if auth_data.get("type") == "auth_success":
                        return websocket
                
                raise Exception(f"WebSocket authentication failed: {auth_data}")
                
        except asyncio.TimeoutError:
            raise Exception("WebSocket authentication timeout")
    
    async def wait_for_websocket_event(self, websocket: websockets.WebSocketServerProtocol, 
                                     event_type: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Wait for specific WebSocket event.
        
        Args:
            websocket: Connected WebSocket
            event_type: Event type to wait for
            timeout: Timeout in seconds
            
        Returns:
            Event data dictionary
        """
        if self.debug:
            print(f"[WS] Waiting for event: {event_type}")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                data = json.loads(message)
                
                if self.debug:
                    print(f"[WS] Received: {data.get('type', 'unknown')}")
                
                if data.get("type") == event_type:
                    return data
                    
            except asyncio.TimeoutError:
                continue
        
        raise TimeoutError(f"Timeout waiting for WebSocket event: {event_type}")
    
    async def close_websocket(self, websocket: websockets.WebSocketServerProtocol):
        """Close WebSocket connection gracefully."""
        if websocket:
            await websocket.close()
            if self.debug:
                print(f"[WS] Connection closed")


class TestValidator:
    """Validation utilities for test assertions."""
    
    @staticmethod
    def assert_response_ok(response: httpx.Response, expected_status: int = 200):
        """Assert HTTP response has expected status code."""
        assert response.status_code == expected_status, \
            f"Expected status {expected_status}, got {response.status_code}: {response.text}"
    
    @staticmethod
    def assert_json_contains(data: Dict[str, Any], required_keys: List[str]):
        """Assert JSON data contains required keys."""
        for key in required_keys:
            assert key in data, f"Required key '{key}' not found in response: {data}"
    
    @staticmethod
    def assert_websocket_event(event: Dict[str, Any], expected_type: str, required_keys: List[str] = None):
        """Assert WebSocket event has expected type and keys."""
        assert event.get("type") == expected_type, \
            f"Expected event type '{expected_type}', got '{event.get('type')}'"
        
        if required_keys:
            for key in required_keys:
                assert key in event, f"Required key '{key}' not found in event: {event}"


class NotificationTestHelper:
    """Helper utilities specifically for notification testing."""
    
    def __init__(self, client: LupinTestClient):
        self.client = client
    
    async def send_notification(self, message: str, priority: str = "medium", 
                              notification_type: str = "custom", 
                              target_user: str = "test@example.com") -> httpx.Response:
        """
        Send notification via API.
        
        Args:
            message: Notification message
            priority: Priority level (low, medium, high, urgent)
            notification_type: Notification type (task, progress, alert, custom)
            target_user: Target user email
            
        Returns:
            API response
        """
        params = {
            "message": message,
            "type": notification_type,
            "priority": priority,
            "target_user": target_user,
            "api_key": "claude_code_simple_key"
        }
        
        return await self.client.http_request("POST", "/api/notify", params=params)
    
    async def get_user_notifications(self, user_id: str, include_played: bool = True, 
                                   limit: int = 50) -> httpx.Response:
        """Get notifications for a user."""
        params = {
            "include_played": str(include_played).lower(),
            "limit": limit
        }
        
        return await self.client.http_request("GET", f"/api/notifications/{user_id}", params=params)
    
    async def mark_notification_played(self, notification_id: str) -> httpx.Response:
        """Mark notification as played."""
        return await self.client.http_request("POST", f"/api/notifications/{notification_id}/played")
    
    async def delete_notification(self, notification_id: str) -> httpx.Response:
        """Delete notification."""
        return await self.client.http_request("DELETE", f"/api/notifications/{notification_id}")


def print_test_banner(test_name: str):
    """Print formatted test banner."""
    print(f"\n{'='*60}")
    print(f"  {test_name}")
    print(f"{'='*60}")


def print_test_result(test_name: str, success: bool, error: str = None):
    """Print formatted test result."""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} {test_name}")
    if error:
        print(f"     Error: {error}")


async def run_test_with_error_handling(test_func, test_name: str) -> bool:
    """
    Run test function with error handling and reporting.
    
    Args:
        test_func: Async test function to run
        test_name: Name of the test for reporting
        
    Returns:
        True if test passed, False if failed
    """
    try:
        await test_func()
        print_test_result(test_name, True)
        return True
    except Exception as e:
        print_test_result(test_name, False, str(e))
        return False


def email_to_system_id(email: str) -> str:
    """
    Convert email to system user ID (matches server logic).
    
    Args:
        email: User email address
        
    Returns:
        System user ID
    """
    clean_email = email.replace("@", "_").replace(".", "_")
    return f"user_{clean_email}"