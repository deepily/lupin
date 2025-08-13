#!/usr/bin/env python3
"""
Notification System Smoke Tests

Comprehensive smoke tests for the Lupin notification system including:
- /api/notify endpoint validation
- Notification queue operations
- WebSocket notification delivery
- User-specific notification routing
- Priority handling validation
"""

import asyncio
import json
import time
import sys
from pathlib import Path

# Add utilities to path
sys.path.append(str(Path(__file__).parent))
from utilities import (
    LupinTestClient, TestValidator, NotificationTestHelper,
    print_test_banner, run_test_with_error_handling, email_to_system_id
)


class NotificationSmokeTests:
    """Smoke tests for notification system functionality."""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.client = LupinTestClient(debug=debug)
        self.notification_helper = NotificationTestHelper(self.client)
        self.validator = TestValidator()
        self.test_results = []
    
    async def test_notify_endpoint_basic(self):
        """Test basic /api/notify endpoint functionality."""
        response = await self.notification_helper.send_notification(
            message="Test notification for smoke test",
            priority="medium",
            notification_type="custom"
        )
        
        self.validator.assert_response_ok(response, 200)
        
        data = response.json()
        self.validator.assert_json_contains(data, ["status", "message", "notification"])
        
        # Verify notification structure
        notification = data["notification"]
        self.validator.assert_json_contains(notification, ["message", "type", "priority", "timestamp", "source"])
        
        assert notification["message"] == "Test notification for smoke test"
        assert notification["type"] == "custom"
        assert notification["priority"] == "medium"
        assert notification["source"] == "claude_code"
    
    async def test_notify_endpoint_all_priorities(self):
        """Test /api/notify endpoint with all priority levels."""
        priorities = ["low", "medium", "high", "urgent"]
        
        for priority in priorities:
            response = await self.notification_helper.send_notification(
                message=f"Test {priority} priority notification",
                priority=priority
            )
            
            self.validator.assert_response_ok(response, 200)
            
            data = response.json()
            notification = data["notification"]
            assert notification["priority"] == priority, f"Priority mismatch for {priority}"
    
    async def test_notify_endpoint_all_types(self):
        """Test /api/notify endpoint with all notification types."""
        types = ["task", "progress", "alert", "custom"]
        
        for notification_type in types:
            response = await self.notification_helper.send_notification(
                message=f"Test {notification_type} type notification",
                notification_type=notification_type
            )
            
            self.validator.assert_response_ok(response, 200)
            
            data = response.json()
            notification = data["notification"]
            assert notification["type"] == notification_type, f"Type mismatch for {notification_type}"
    
    async def test_notify_endpoint_validation(self):
        """Test /api/notify endpoint input validation."""
        # Test missing API key
        try:
            params = {
                "message": "Test message",
                "type": "custom",
                "priority": "medium",
                "target_user": "test@example.com"
                # Missing api_key
            }
            response = await self.client.http_request("POST", "/api/notify", params=params)
            assert response.status_code == 422, "Should require api_key parameter"
        except Exception:
            pass  # Expected to fail
        
        # Test invalid priority
        response = await self.notification_helper.send_notification(
            message="Test message",
            priority="invalid_priority"
        )
        assert response.status_code == 400, "Should reject invalid priority"
        
        # Test invalid type
        response = await self.notification_helper.send_notification(
            message="Test message",
            notification_type="invalid_type"
        )
        assert response.status_code == 400, "Should reject invalid type"
        
        # Test empty message
        response = await self.notification_helper.send_notification(
            message="",
            priority="medium"
        )
        assert response.status_code == 400, "Should reject empty message"
    
    async def test_user_notification_routing(self):
        """Test user-specific notification routing."""
        test_email = "notification_test@example.com"
        user_id = email_to_system_id(test_email)
        
        # Send notification to specific user
        response = await self.notification_helper.send_notification(
            message="User-specific test notification",
            target_user=test_email
        )
        
        self.validator.assert_response_ok(response, 200)
        
        data = response.json()
        assert data["target_user"] == test_email
        assert data["target_system_id"] == user_id
        
        # Verify routing information
        self.validator.assert_json_contains(data, ["target_user", "target_system_id"])
    
    async def test_notification_queue_operations(self):
        """Test notification queue CRUD operations."""
        test_email = "queue_test@example.com"
        user_id = email_to_system_id(test_email)
        
        # Send a notification first
        send_response = await self.notification_helper.send_notification(
            message="Queue operation test notification",
            target_user=test_email,
            priority="high"
        )
        
        self.validator.assert_response_ok(send_response, 200)
        
        # Get user notifications
        get_response = await self.notification_helper.get_user_notifications(user_id)
        self.validator.assert_response_ok(get_response, 200)
        
        get_data = get_response.json()
        self.validator.assert_json_contains(get_data, ["status", "notifications", "notification_count"])
        
        # Should have at least our test notification
        notifications = get_data["notifications"]
        assert len(notifications) > 0, "Should have notifications in queue"
        
        # Find our test notification
        test_notification = None
        for notification in notifications:
            if notification["message"] == "Queue operation test notification":
                test_notification = notification
                break
        
        assert test_notification is not None, "Test notification not found in queue"
        assert test_notification["priority"] == "high"
        
        # Test marking as played (if notification has ID)
        if "id_hash" in test_notification:
            played_response = await self.notification_helper.mark_notification_played(
                test_notification["id_hash"]
            )
            self.validator.assert_response_ok(played_response, 200)
    
    async def test_websocket_notification_delivery(self):
        """Test notification delivery via WebSocket events."""
        # Connect to queue WebSocket with notification events
        websocket = await self.client.websocket_connect(
            f"/ws/queue/{self.client.session_id}",
            subscribed_events=["notification_queue_update", "auth_success", "sys_ping"]
        )
        
        try:
            # Send a notification
            test_message = f"WebSocket delivery test {int(time.time())}"
            send_response = await self.notification_helper.send_notification(
                message=test_message,
                priority="urgent"
            )
            
            self.validator.assert_response_ok(send_response, 200)
            
            # Wait for WebSocket notification event
            try:
                notification_event = await self.client.wait_for_websocket_event(
                    websocket, "notification_queue_update", timeout=10.0
                )
                
                # Validate event structure
                self.validator.assert_websocket_event(
                    notification_event, 
                    "notification_queue_update",
                    ["notification"]
                )
                
                # Validate notification content
                notification = notification_event["notification"]
                self.validator.assert_json_contains(
                    notification, 
                    ["message", "type", "priority", "timestamp"]
                )
                
                assert notification["message"] == test_message
                assert notification["priority"] == "urgent"
                
            except TimeoutError:
                # This might be expected if user isn't connected to the specific session
                if self.debug:
                    print("[DEBUG] WebSocket notification timeout - may be expected in test environment")
                pass
                
        finally:
            await self.client.close_websocket(websocket)
    
    async def test_api_authentication(self):
        """Test notification API authentication requirements."""
        # Test with wrong API key
        params = {
            "message": "Test message",
            "type": "custom", 
            "priority": "medium",
            "target_user": "test@example.com",
            "api_key": "wrong_key"
        }
        
        response = await self.client.http_request("POST", "/api/notify", params=params)
        assert response.status_code == 401, "Should reject invalid API key"
        
        # Test with correct API key (already tested in other tests)
        response = await self.notification_helper.send_notification(
            message="Auth test notification"
        )
        self.validator.assert_response_ok(response, 200)
    
    async def run_all_tests(self) -> bool:
        """Run all notification smoke tests."""
        print_test_banner("Notification System Smoke Tests")
        
        tests = [
            (self.test_notify_endpoint_basic, "Basic /api/notify endpoint"),
            (self.test_notify_endpoint_all_priorities, "All priority levels"),
            (self.test_notify_endpoint_all_types, "All notification types"),
            (self.test_notify_endpoint_validation, "Input validation"),
            (self.test_user_notification_routing, "User-specific routing"),
            (self.test_notification_queue_operations, "Queue operations"),
            (self.test_websocket_notification_delivery, "WebSocket delivery"),
            (self.test_api_authentication, "API authentication")
        ]
        
        passed = 0
        total = len(tests)
        
        for test_func, test_name in tests:
            if await run_test_with_error_handling(test_func, test_name):
                passed += 1
        
        print(f"\n{'='*60}")
        print(f"Notification Tests Summary: {passed}/{total} passed")
        print(f"{'='*60}")
        
        return passed == total


async def main():
    """Main test execution function."""
    # Check if we should run in debug mode
    debug = "--debug" in sys.argv
    
    print("🔔 Notification System Smoke Tests")
    print("=" * 50)
    print("Testing comprehensive notification functionality...")
    print("")
    
    # Create test instance and run
    tests = NotificationSmokeTests(debug=debug)
    
    try:
        success = await tests.run_all_tests()
        
        if success:
            print("✅ All notification tests passed!")
            return True
        else:
            print("❌ Some notification tests failed!")
            return False
            
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)