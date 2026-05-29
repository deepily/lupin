"""
Smoke tests for CoSA Voice MCP Server.

Quick validation tests for MCP server configuration, imports, and basic functionality.
These tests verify the MCP server can start and create notification requests.

Note: These tests do NOT require the Lupin server to be running.
They test the MCP server module in isolation.

Created: 2026-01-01
"""

import os
import sys

# Add src to path for imports
sys.path.insert( 0, os.path.join( os.path.dirname( __file__ ), '..', '..' ) )

import cosa.utils.util as cu


def quick_smoke_test():
    """
    Quick smoke test for CoSA Voice MCP Server - validates basic functionality.
    """
    cu.print_banner( "CoSA Voice MCP Server Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import lupin_cli.notifications notification models
        print( "Test 1: Importing lupin_cli.notifications notification models..." )
        from lupin_cli.notifications.notification_models import (
            NotificationRequest,
            AsyncNotificationRequest,
            NotificationResponse,
            AsyncNotificationResponse,
            NotificationType,
            NotificationPriority,
            ResponseType
        )
        print( "✓ All notification models imported successfully" )

        # Test 2: Import lupin_cli.notifications notification functions
        print( "\nTest 2: Importing lupin_cli.notifications notification functions..." )
        from lupin_cli.notifications.notify_user_sync import notify_user_sync
        from lupin_cli.notifications.notify_user_async import notify_user_async
        print( "✓ notify_user_sync imported" )
        print( "✓ notify_user_async imported" )

        # Test 3: Import FastMCP
        print( "\nTest 3: Importing FastMCP..." )
        from fastmcp import FastMCP
        print( "✓ FastMCP imported successfully" )

        # Test 4: Test sender_id generation format
        print( "\nTest 4: Testing sender_id generation..." )

        def _get_sender_id( project: str ) -> str:
            return f"claude.code@{project}.deepily.ai"

        sender_id = _get_sender_id( "lupin" )
        assert sender_id == "claude.code@lupin.deepily.ai"
        print( f"✓ sender_id generated: {sender_id}" )

        sender_id_test = _get_sender_id( "TEST" )
        assert sender_id_test == "claude.code@TEST.deepily.ai"
        print( f"✓ sender_id preserves case: {sender_id_test}" )

        # Test 5: Create NotificationRequest (blocking)
        print( "\nTest 5: Creating NotificationRequest (blocking)..." )
        request = NotificationRequest(
            message="Test message for smoke test",
            response_type=ResponseType.YES_NO,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority.MEDIUM,
            timeout_seconds=60,
            response_default="no",
            sender_id="claude.code@test.deepily.ai"
        )
        assert request.message == "Test message for smoke test"
        assert request.response_type == ResponseType.YES_NO
        assert request.sender_id == "claude.code@test.deepily.ai"
        print( f"✓ NotificationRequest created successfully" )
        print( f"  - message: {request.message[:30]}..." )
        print( f"  - response_type: {request.response_type}" )
        print( f"  - sender_id: {request.sender_id}" )

        # Test 6: Create AsyncNotificationRequest (fire-and-forget)
        print( "\nTest 6: Creating AsyncNotificationRequest (fire-and-forget)..." )
        async_request = AsyncNotificationRequest(
            message="Async test notification",
            notification_type=NotificationType.PROGRESS,
            priority=NotificationPriority.LOW,
            sender_id="claude.code@test.deepily.ai"
        )
        assert async_request.message == "Async test notification"
        assert async_request.notification_type == NotificationType.PROGRESS
        assert async_request.priority == NotificationPriority.LOW
        print( f"✓ AsyncNotificationRequest created successfully" )
        print( f"  - notification_type: {async_request.notification_type}" )
        print( f"  - priority: {async_request.priority}" )

        # Test 7: Verify enum values
        print( "\nTest 7: Verifying enum values..." )

        notification_types = [e.value for e in NotificationType]
        assert "task" in notification_types
        assert "progress" in notification_types
        assert "alert" in notification_types
        assert "custom" in notification_types
        print( f"✓ NotificationType values: {notification_types}" )

        priorities = [e.value for e in NotificationPriority]
        assert "low" in priorities
        assert "medium" in priorities
        assert "high" in priorities
        assert "urgent" in priorities
        print( f"✓ NotificationPriority values: {priorities}" )

        response_types = [e.value for e in ResponseType]
        assert "yes_no" in response_types
        assert "open_ended" in response_types
        print( f"✓ ResponseType values: {response_types}" )

        # Test 8: Create FastMCP instance
        print( "\nTest 8: Creating FastMCP server instance..." )
        mcp = FastMCP(
            name="Test MCP Server",
            instructions="Test instructions for smoke test"
        )
        assert mcp is not None
        print( f"✓ FastMCP instance created successfully" )
        print( f"  - name: Test MCP Server" )

        # Test 9: Verify MCP tool decorator works
        print( "\nTest 9: Testing MCP tool decorator..." )

        @mcp.tool
        def test_tool( message: str ) -> str:
            """Test tool for smoke test."""
            return f"Echo: {message}"

        # Verify tool was registered (decorator returns FunctionTool object)
        assert test_tool is not None
        assert "FunctionTool" in str( type( test_tool ) )
        print( f"✓ MCP tool decorator works (returns {type( test_tool ).__name__})" )

        # Test 10: Test server URL default
        print( "\nTest 10: Testing server URL configuration..." )

        def _get_server_url() -> str:
            return os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )

        # Without env var, should return default
        original_value = os.environ.pop( "LUPIN_APP_SERVER_URL", None )
        try:
            url = _get_server_url()
            assert url == "http://localhost:7999"
            print( f"✓ Default server URL: {url}" )

            # With env var, should return custom value
            os.environ["LUPIN_APP_SERVER_URL"] = "http://custom:8080"
            url = _get_server_url()
            assert url == "http://custom:8080"
            print( f"✓ Custom server URL: {url}" )
        finally:
            # Restore original value
            if original_value:
                os.environ["LUPIN_APP_SERVER_URL"] = original_value
            elif "LUPIN_APP_SERVER_URL" in os.environ:
                del os.environ["LUPIN_APP_SERVER_URL"]

        # Test 11: Verify request_persona tool is registered on the real server module
        print( "\nTest 11: Verifying request_persona tool registration..." )
        from lupin_mcp import cosa_voice_mcp
        assert hasattr( cosa_voice_mcp, "request_persona" ), "request_persona tool missing"
        assert "FunctionTool" in str( type( cosa_voice_mcp.request_persona ) ), \
            "request_persona is not a registered @mcp.tool"
        assert callable( cosa_voice_mcp._request_persona ), "_request_persona helper missing"
        assert callable( cosa_voice_mcp._persona_error_detail ), "_persona_error_detail helper missing"
        print( "✓ request_persona registered as FunctionTool; helpers present" )

        print( "\n" + "=" * 70 )
        print( "✅ ALL SMOKE TESTS PASSED!" )
        print( "=" * 70 )
        print( "\nCoSA Voice MCP Server components are operational!" )
        print( "\nNote: To test actual notification delivery, ensure:" )
        print( "  1. Lupin server is running (./src/scripts/run-fastapi-lupin.sh)" )
        print( "  2. MCP server is installed (./src/scripts/install-mcp-server.sh)" )

    except AssertionError as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print( f"\n✗ Error during smoke test: {e}" )
        import traceback
        traceback.print_exc()
        return False

    return True


def test_mcp_smoke():
    """Pytest wrapper for MCP smoke test."""
    assert quick_smoke_test() is True


if __name__ == "__main__":
    success = quick_smoke_test()
    sys.exit( 0 if success else 1 )
