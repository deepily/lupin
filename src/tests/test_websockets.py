#!/usr/bin/env python3
"""
WebSocket testing for FastAPI refactoring
Tests WebSocket connections and real-time events
"""

import asyncio
import json
import websockets
from datetime import datetime
import sys
from typing import Dict, Optional

class WebSocketTester:
    def __init__(self, base_url: str = "ws://localhost:7999"):
        self.base_url = base_url
        self.test_session_id = "test-session-123"
        
    async def test_basic_connection(self) -> bool:
        """Test basic WebSocket connection"""
        print("🔌 Testing basic WebSocket connection...")
        
        try:
            uri = f"{self.base_url}/ws/{self.test_session_id}"
            async with websockets.connect(uri) as websocket:
                print(f"✅ Connected to {uri}")
                
                # Send auth message
                auth_msg = {
                    "type": "auth",
                    "token": "mock_token_test"
                }
                await websocket.send(json.dumps(auth_msg))
                print("📤 Sent auth message")
                
                # Wait for auth response
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(response)
                
                if data.get("type") == "auth_success":
                    print("✅ Authentication successful")
                    return True
                elif data.get("type") == "auth_error":
                    print(f"❌ Authentication failed: {data.get('message')}")
                    return False
                else:
                    print(f"❌ Unexpected response: {data}")
                    return False
                    
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    async def test_queue_events(self) -> bool:
        """Test queue-specific WebSocket events"""
        print("\n📊 Testing queue WebSocket events...")
        
        try:
            uri = f"{self.base_url}/ws/queue/{self.test_session_id}"
            async with websockets.connect(uri) as websocket:
                print(f"✅ Connected to queue WebSocket")
                
                # Collect events for 10 seconds
                events = []
                start_time = asyncio.get_event_loop().time()
                
                while asyncio.get_event_loop().time() - start_time < 10:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        events.append(data)
                        print(f"📥 Received: {data.get('type', 'unknown')} event")
                    except asyncio.TimeoutError:
                        continue
                
                # Check if we received expected events
                event_types = {event.get("type") for event in events}
                expected_events = {"time_update", "todo_update", "run_update", "done_update", "dead_update"}
                
                print(f"\n📋 Received event types: {event_types}")
                
                # time_update should definitely be there (every 5 seconds)
                if "time_update" in event_types:
                    print("✅ Received time_update events")
                    return True
                else:
                    print("❌ No time_update events received")
                    return False
                    
        except Exception as e:
            print(f"❌ Queue WebSocket test failed: {e}")
            return False
    
    async def test_concurrent_connections(self) -> bool:
        """Test multiple concurrent WebSocket connections"""
        print("\n👥 Testing concurrent WebSocket connections...")
        
        async def connect_client(client_id: str) -> bool:
            try:
                uri = f"{self.base_url}/ws/client-{client_id}"
                async with websockets.connect(uri) as websocket:
                    # Send auth
                    auth_msg = {"type": "auth", "token": f"mock_token_{client_id}"}
                    await websocket.send(json.dumps(auth_msg))
                    
                    # Wait for response
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(response)
                    
                    if data.get("type") == "auth_success":
                        print(f"✅ Client {client_id} connected")
                        
                        # Keep connection open for a bit
                        await asyncio.sleep(2)
                        return True
                    else:
                        print(f"❌ Client {client_id} auth failed")
                        return False
                        
            except Exception as e:
                print(f"❌ Client {client_id} failed: {e}")
                return False
        
        # Test 5 concurrent connections
        tasks = [connect_client(f"user{i}") for i in range(5)]
        results = await asyncio.gather(*tasks)
        
        success_count = sum(results)
        print(f"\n📊 Concurrent test results: {success_count}/5 successful")
        
        return success_count == 5
    
    async def test_notification_events(self) -> bool:
        """Test notification WebSocket events"""
        print("\n🔔 Testing notification events...")
        
        try:
            uri = f"{self.base_url}/ws/{self.test_session_id}"
            async with websockets.connect(uri) as websocket:
                # Authenticate
                auth_msg = {"type": "auth", "token": "mock_token_test"}
                await websocket.send(json.dumps(auth_msg))
                
                # Wait for auth success
                response = await websocket.recv()
                data = json.loads(response)
                
                if data.get("type") != "auth_success":
                    print("❌ Authentication failed")
                    return False
                
                print("✅ Authenticated, waiting for notification events...")
                
                # Listen for notification events
                notification_received = False
                start_time = asyncio.get_event_loop().time()
                
                while asyncio.get_event_loop().time() - start_time < 5:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        
                        if data.get("type") == "notification_update":
                            print(f"✅ Received notification: {data}")
                            notification_received = True
                            break
                            
                    except asyncio.TimeoutError:
                        continue
                
                if not notification_received:
                    print("ℹ️  No notification events received (this is OK if no notifications are being sent)")
                
                return True
                
        except Exception as e:
            print(f"❌ Notification test failed: {e}")
            return False

async def main():
    print("🧪 WebSocket Testing Suite")
    print("=" * 50)
    
    tester = WebSocketTester()
    
    # Run all tests
    tests = [
        ("Basic Connection", tester.test_basic_connection),
        ("Queue Events", tester.test_queue_events),
        ("Concurrent Connections", tester.test_concurrent_connections),
        ("Notification Events", tester.test_notification_events),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"Running: {test_name}")
        print('='*50)
        
        try:
            result = await test_func()
            results[test_name] = result
        except Exception as e:
            print(f"❌ Test crashed: {e}")
            results[test_name] = False
    
    # Summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    
    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    print("="*50)
    print(f"Total: {passed_tests}/{total_tests} passed")
    
    if passed_tests == total_tests:
        print("✅ All WebSocket tests passed!")
        sys.exit(0)
    else:
        print("❌ Some WebSocket tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    # Check if server is running first
    import httpx
    
    try:
        response = httpx.get("http://localhost:7999/health", timeout=2.0)
        if response.status_code != 200:
            print("❌ Server is not healthy")
            sys.exit(1)
    except Exception:
        print("❌ FastAPI server is not running!")
        print("Run: cd src && python -m uvicorn fastapi_app.main:app --port 7999")
        sys.exit(1)
    
    asyncio.run(main())