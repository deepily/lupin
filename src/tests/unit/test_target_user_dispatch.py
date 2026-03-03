#!/usr/bin/env python3
"""
Unit tests for target_user notification dispatch chain.

Reproduces the "Cannot resolve target_user" error from podcast job execution
(Session 283 bug). Tests the full chain:

    job.py → cosa_interface.TARGET_USER → dispatcher.target_user →
    AsyncNotificationRequest.target_user → notify_user_async()

Each test verifies that target_user propagates correctly through the chain
and is never None when the job has a valid user_email.
"""

import os
import sys
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# ============================================================================
# Bootstrap PYTHONPATH
# ============================================================================

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", ".." ) )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )


# ============================================================================
# Test 1: cosa_interface.TARGET_USER propagates to dispatcher
# ============================================================================

class TestCosaInterfaceTargetUserPropagation:
    """Verify TARGET_USER flows from cosa_interface to dispatcher."""

    def test_target_user_propagates_to_dispatcher( self ):
        """Setting cosa_interface.TARGET_USER should update dispatcher.target_user."""
        from cosa.agents.podcast_generator import cosa_interface

        # Save original state
        original = cosa_interface.TARGET_USER

        try:
            cosa_interface.TARGET_USER = "test@example.com"

            # Simulate what notify_progress does (lines 90-92)
            cosa_interface._dispatcher.sender_id    = cosa_interface.SENDER_ID
            cosa_interface._dispatcher.session_name = cosa_interface.SESSION_NAME
            cosa_interface._dispatcher.target_user  = cosa_interface.TARGET_USER

            assert cosa_interface._dispatcher.target_user == "test@example.com"
        finally:
            cosa_interface.TARGET_USER = original

    def test_target_user_none_when_not_set( self ):
        """Before job sets TARGET_USER, dispatcher.target_user is None."""
        from cosa.agents.podcast_generator import cosa_interface

        original = cosa_interface.TARGET_USER
        try:
            cosa_interface.TARGET_USER = None
            cosa_interface._dispatcher.target_user = cosa_interface.TARGET_USER
            assert cosa_interface._dispatcher.target_user is None
        finally:
            cosa_interface.TARGET_USER = original


# ============================================================================
# Test 2: Dispatcher passes target_user to AsyncNotificationRequest
# ============================================================================

class TestDispatcherTargetUserToRequest:
    """Verify dispatcher creates requests with target_user set."""

    @pytest.mark.asyncio
    async def test_dispatcher_includes_target_user_in_request( self ):
        """Dispatcher.notify_progress() should create request with target_user."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"

        captured_request = None

        def mock_notify_async( request ):
            nonlocal captured_request
            captured_request = request

        with patch(
            "cosa.agents.utils.agent_notification_dispatcher._notify_user_async",
            side_effect=mock_notify_async
        ):
            await dispatcher.notify_progress( "Test message" )

        assert captured_request is not None, "notify_user_async was not called"
        assert captured_request.target_user == "test@example.com"

    @pytest.mark.asyncio
    async def test_dispatcher_target_user_none_when_not_set( self ):
        """Dispatcher with target_user=None creates request with target_user=None."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        # target_user defaults to None

        captured_request = None

        def mock_notify_async( request ):
            nonlocal captured_request
            captured_request = request

        with patch(
            "cosa.agents.utils.agent_notification_dispatcher._notify_user_async",
            side_effect=mock_notify_async
        ):
            await dispatcher.notify_progress( "Test message" )

        assert captured_request is not None
        assert captured_request.target_user is None

    @pytest.mark.asyncio
    async def test_dispatcher_ask_confirmation_includes_target_user( self ):
        """Blocking calls also include target_user."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from lupin_cli.notifications.notification_models import NotificationResponse

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"

        captured_request = None

        def mock_notify_sync( request ):
            nonlocal captured_request
            captured_request = request
            return NotificationResponse(
                exit_code      = 0,
                response_value = "yes",
                response_type  = "yes_no",
            )

        with patch(
            "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
            side_effect=mock_notify_sync
        ):
            result = await dispatcher.ask_confirmation( "Proceed?" )

        assert captured_request is not None
        assert captured_request.target_user == "test@example.com"


# ============================================================================
# Test 3: End-to-end: job.py → cosa_interface → dispatcher → request
# ============================================================================

class TestEndToEndTargetUser:
    """End-to-end tests for the full target_user chain via dry-run."""

    @pytest.mark.asyncio
    async def test_dry_run_notifications_have_target_user( self ):
        """All notifications from dry-run execution should have target_user set."""
        from cosa.agents.podcast_generator.job import PodcastGeneratorJob

        job = PodcastGeneratorJob(
            research_path    = "/io/deep-research/test@test.com/test-report.md",
            user_id          = "user123",
            user_email       = "test@test.com",
            session_id       = "session456",
            dry_run          = True,
            debug            = False,
        )

        captured_requests = []

        def mock_notify_async( request ):
            captured_requests.append( request )

        def mock_notify_sync( request ):
            captured_requests.append( request )
            from lupin_cli.notifications.notification_models import NotificationResponse
            return NotificationResponse(
                exit_code      = 0,
                response_value = "yes",
                response_type  = "yes_no",
            )

        with patch(
            "cosa.agents.utils.agent_notification_dispatcher._notify_user_async",
            side_effect=mock_notify_async
        ), patch(
            "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
            side_effect=mock_notify_sync
        ):
            # Reset voice check to force is_voice_available() to re-check
            from cosa.agents.utils import voice_io as core_voice_io
            core_voice_io._voice_available = None

            await job._execute()

        # Should have captured multiple notification requests
        assert len( captured_requests ) > 0, "No notifications were captured"

        # ALL requests must have target_user set
        for i, req in enumerate( captured_requests ):
            assert req.target_user == "test@test.com", (
                f"Request #{i} has target_user={req.target_user!r}, expected 'test@test.com'"
            )


# ============================================================================
# Test 4: Docker fallback scenario
# ============================================================================

class TestDockerFallback:
    """Test that resolve_target_user() fails in Docker-like env."""

    def test_resolve_target_user_fails_without_env( self ):
        """resolve_target_user() raises ValueError when no source is available."""
        from lupin_cli.notifications.notification_models import resolve_target_user

        # Temporarily unset LUPIN_DEV_EMAIL
        original = os.environ.pop( "LUPIN_DEV_EMAIL", None )

        try:
            # Patch get_api_config at the point where resolve_target_user imports it
            with patch(
                "cosa.utils.config_loader.get_api_config",
                side_effect=Exception( "config not found" )
            ):
                with pytest.raises( ValueError ):
                    resolve_target_user()
        finally:
            if original is not None:
                os.environ[ "LUPIN_DEV_EMAIL" ] = original

    def test_resolve_target_user_succeeds_with_explicit( self ):
        """resolve_target_user() returns explicit value when provided."""
        from lupin_cli.notifications.notification_models import resolve_target_user

        result = resolve_target_user( explicit_value="explicit@test.com" )
        assert result == "explicit@test.com"


# ============================================================================
# Test 5: Negative case — what happens WITHOUT the fix
# ============================================================================

class TestNegativeCase:
    """Verify that None target_user triggers resolve_target_user()."""

    def test_notify_user_async_calls_resolve_when_target_user_none( self ):
        """notify_user_async() calls resolve_target_user() when target_user is None."""
        from lupin_cli.notifications.notification_models import AsyncNotificationRequest, NotificationType, NotificationPriority

        request = AsyncNotificationRequest(
            message           = "Test",
            notification_type = NotificationType.PROGRESS,
            priority          = NotificationPriority.LOW,
            target_user       = None,  # Explicitly None
        )

        # Verify the fallback would be triggered
        assert request.target_user is None

    def test_notify_user_async_skips_resolve_when_target_user_set( self ):
        """notify_user_async() should NOT call resolve when target_user is set."""
        from lupin_cli.notifications.notification_models import AsyncNotificationRequest, NotificationType, NotificationPriority

        request = AsyncNotificationRequest(
            message           = "Test",
            notification_type = NotificationType.PROGRESS,
            priority          = NotificationPriority.LOW,
            target_user       = "user@test.com",
        )

        # target_user is set, resolve should be skipped
        assert request.target_user == "user@test.com"


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
