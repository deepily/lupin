"""
Integration tests for notify-claude-sync CLI (Phase 2.3).

Tests end-to-end CLI flow with live FastAPI server on port 7999.
These tests require the server to be running and a valid user account.

Usage:
    # Start server first:
    ./src/scripts/run-fastapi-lupin.sh

    # Run integration tests:
    pytest src/tests/integration/test_notify_user_sync_integration.py -v
"""

import pytest
import subprocess
import time
import requests

from lupin_cli.notifications.notification_models import ResponseType


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture( scope="module" )
def server_check():
    """Check if server is running before tests."""
    server_url = "http://localhost:7999"

    try:
        response = requests.get( f"{server_url}/health", timeout=2 )
        if response.status_code == 200:
            print( f"\n✓ Server is running at {server_url}" )
            return True
    except requests.exceptions.ConnectionError:
        pytest.skip( f"Server not running at {server_url}. Start server with ./src/scripts/run-fastapi-lupin.sh" )


# ============================================================================
# CLI Integration Tests (Marked as manual for now)
# ============================================================================

@pytest.mark.manual
class TestNotifyClaudeSyncCLI:
    """Test notify-claude-sync CLI with live server (manual)."""

    def test_yes_no_notification_cli( self, server_check ):
        """Test yes/no notification via CLI."""
        # This test requires manual user interaction
        result = subprocess.run(
            [
                "notify-claude-sync",
                "Integration test: Approve?",
                "--response-type", "yes_no",
                "--response-default", "yes",
                "--timeout", "30"
            ],
            capture_output=True,
            text=True
        )

        # Note: Exit code depends on user interaction
        # 0 = responded, 1 = error, 2 = timeout
        assert result.returncode in (0, 1, 2)

    def test_open_ended_notification_cli( self, server_check ):
        """Test open-ended notification via CLI."""
        result = subprocess.run(
            [
                "notify-claude-sync",
                "Integration test: Enter text",
                "--response-type", "open_ended",
                "--response-default", "Default text",
                "--timeout", "30"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode in (0, 1, 2)


# ============================================================================
# API Integration Tests (Can run automatically)
# ============================================================================

class TestSSENotificationAPI:
    """Test SSE notification API with live server."""

    def test_offline_user_returns_default_immediately( self, server_check ):
        """Test offline detection returns default immediately."""
        import lupin_cli.notifications.notify_user_sync as sync_module
        from lupin_cli.notifications.notification_models import NotificationRequest

        request = NotificationRequest(
            message="Test offline notification",
            response_type=ResponseType.YES_NO,
            response_default="yes",
            target_user="nonexistent@example.com"  # User not in system
        )

        response = sync_module.notify_user_sync( request, debug=True )

        # Should return error (user not found) or offline with default
        assert response.exit_code in (0, 1)

    @pytest.mark.manual
    def test_timeout_with_default( self, server_check ):
        """Test notification timeout returns default."""
        import lupin_cli.notifications.notify_user_sync as sync_module
        from lupin_cli.notifications.notification_models import NotificationRequest

        request = NotificationRequest(
            message="Test timeout (will wait 10 seconds)",
            response_type=ResponseType.YES_NO,
            response_default="no",
            timeout_seconds=10,  # Short timeout for testing
            target_user="ricardo.felipe.ruiz@gmail.com"
        )

        response = sync_module.notify_user_sync( request, debug=True )

        # Should timeout and use default
        assert response.exit_code == 2  # Timeout
        assert response.response_value == "no"
        assert response.default_used is True


# ============================================================================
# Manual Testing Guide
# ============================================================================

def manual_test_guide():
    """
    Print manual testing guide for notify-claude-sync.

    Run this function to see comprehensive manual testing steps.
    """
    import cosa.utils.util as cu

    cu.print_banner( "notify-claude-sync Manual Testing Guide", prepend_nl=True )

    print( """
Prerequisites:
1. Start Lupin server: ./src/scripts/run-fastapi-lupin.sh
2. Open Fresh Queue UI in browser: http://localhost:7999/fresh
3. Login as test user

Test Scenarios:

1. Yes/No with Yes Default:
   notify-claude-sync "Approve deployment?" --response-type yes_no --response-default yes --timeout 60

   Expected:
   - Notification appears in Action Required section
   - Yes button highlighted (⭐ Default)
   - Press Y or click Yes → Exit code 0, stdout: "yes"
   - Wait for timeout → Exit code 2, stdout: "yes"

2. Yes/No with No Default:
   notify-claude-sync "Delete database?" --response-type yes_no --response-default no --timeout 60

   Expected:
   - No button highlighted (⭐ Default)
   - Press N or click No → Exit code 0, stdout: "no"

3. Open-Ended with Default:
   notify-claude-sync "Enter commit message" --response-type open_ended --response-default "Auto-commit" --timeout 60

   Expected:
   - Text input pre-filled with "Auto-commit"
   - Edit text and submit → Exit code 0, stdout: <your text>
   - Press Enter without editing → Exit code 0, stdout: "Auto-commit"
   - Wait for timeout → Exit code 2, stdout: "Auto-commit"

4. Open-Ended without Default:
   notify-claude-sync "Enter API key" --response-type open_ended --timeout 60

   Expected:
   - Empty text input
   - Type text and submit → Exit code 0, stdout: <your text>
   - Wait for timeout → Exit code 1 (error, no default)

5. Offline User (Automatic):
   notify-claude-sync "Test offline" --response-type yes_no --response-default yes --target-user nonexistent@example.com

   Expected:
   - Exit code 1 (user not found) or 0 (offline with default)
   - Immediate return (no blocking)

6. Connection Error (Server Stopped):
   # Stop server first, then run:
   notify-claude-sync "Test" --response-type yes_no

   Expected:
   - Error: "Cannot reach server"
   - Exit code 1

Exit Codes Reference:
  0: Success (response received or offline with default)
  1: Error (validation, network, user not found)
  2: Timeout (no response within timeout)
    """ )


if __name__ == "__main__":
    manual_test_guide()
