"""
Unit tests for notification management router endpoints with comprehensive mocking.

Tests the notification management router endpoints including:
- Notification sending with authentication and WebSocket delivery
- User notification retrieval with filtering and limits
- Next unplayed notification fetching
- Notification lifecycle management (mark played, delete)
- Timezone handling and local timestamp generation
- Dependency injection and error handling
- FastAPI response formats and status codes

Zero external dependencies - all FastAPI operations, notification management,
WebSocket operations, and external service calls are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call, AsyncMock
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import asyncio

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.rest.routers.notifications import router, notify_user, get_user_notifications, get_next_notification, mark_notification_played, delete_notification
from cosa.rest.routers.notifications import get_notification_queue, get_websocket_manager, get_local_timestamp


def _patch_fastapi_main( mock_main ):
    """
    Robustly patch `fastapi_app.main` for direct-call unit tests.

    `import fastapi_app.main as m` binds m via getattr(sys.modules['fastapi_app'],
    'main'), NOT sys.modules['fastapi_app.main']. Once the REAL fastapi_app
    package is cached by an earlier test in the suite, patching only the
    submodule entry is silently ignored — the test passes in isolation but fails
    under full-suite ordering. Overriding BOTH the package object and the
    submodule entry makes the import resolve to mock_main regardless of prior
    import state. Returns a patch.dict context manager (restores on exit).
    """
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )


class TestNotificationsRouter( unittest.TestCase ):
    """
    Comprehensive unit tests for notification management router endpoints.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All notification management endpoints tested in isolation
        - FastAPI dependencies properly mocked
        - WebSocket operations and authentication validated
        - Error handling scenarios covered
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
        
        # Common test data
        self.test_user_email = "ricardo.felipe.ruiz@gmail.com"
        self.test_user_system_id = "ricardo_felipe_ruiz_gmail_com"
        self.test_message = "Test notification message"
        self.test_type = "progress"
        self.test_priority = "medium"
        self.test_api_key = "claude_code_simple_key"
        self.test_timestamp = "2025-08-05T12:00:00.000000-05:00"
        self.test_notification_id = "notif_123"
        
        # Mock notification data
        self.test_notification = {
            "id": self.test_notification_id,
            "message": self.test_message,
            "type": self.test_type,
            "priority": self.test_priority,
            "timestamp": self.test_timestamp,
            "source": "claude_code",
            "user_id": self.test_user_system_id,
            "played": False
        }
        
        self.test_notification_list = [
            self.test_notification,
            {
                "id": "notif_124",
                "message": "Another notification",
                "type": "task",
                "priority": "high",
                "timestamp": "2025-08-05T11:00:00.000000-05:00",
                "source": "claude_code",
                "user_id": self.test_user_system_id,
                "played": True
            }
        ]
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mock_notification_queue( self ):
        """
        Helper to create mock notification queue with standard methods.
        
        Returns:
            Mock notification queue object
        """
        mock_queue = Mock()
        mock_queue.push_notification.return_value = self.test_notification
        mock_queue.get_user_notifications.return_value = self.test_notification_list
        mock_queue.get_next_unplayed.return_value = self.test_notification
        mock_queue.mark_played.return_value = True
        mock_queue.delete_by_id_hash.return_value = True
        
        return mock_queue
    
    def _create_mock_websocket_manager( self, is_connected=True, connection_count=1, message_sent=True ):
        """
        Helper to create mock WebSocket manager with configurable responses.
        
        Args:
            is_connected: Whether user is connected
            connection_count: Number of user connections
            message_sent: Whether message sending succeeds
            
        Returns:
            Mock WebSocket manager object
        """
        mock_ws_manager = Mock()
        mock_ws_manager.is_user_connected = Mock(return_value=is_connected)
        mock_ws_manager.get_user_connection_count = Mock(return_value=connection_count)

        # emit_to_user is async, so create an AsyncMock for it
        mock_ws_manager.emit_to_user = AsyncMock(return_value=message_sent)

        # Live notify_user reads these as real dicts (connected diagnostics +
        # offline diagnostics iterate them); Mock auto-attrs would break iteration.
        mock_ws_manager.user_sessions      = {}
        mock_ws_manager.active_connections = {}
        mock_ws_manager.user_to_email      = {}

        # Cross-user CC-listener fallback helper (offline + job_id path).
        mock_ws_manager.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": message_sent } )

        return mock_ws_manager

    async def _call_notify_user( self, notification_queue, ws_manager, **overrides ):
        """
        Invoke the live notify_user with a complete, safe kwarg set.

        Why every param is passed explicitly: notify_user is a FastAPI endpoint
        whose parameters default to Query(...)/FieldInfo objects. Calling it
        DIRECTLY (unit test, no FastAPI resolution) leaves those defaults as
        FieldInfo instances — which are truthy and would corrupt branches like
        `if response_requested:`, `if response_options:` (json.loads on a
        FieldInfo), and the idempotency block. Passing concrete values models
        what FastAPI would inject.

        Auth note: authenticated_user_id is supplied directly here (the live
        require_api_key_or_jwt dependency would inject it in production).
        """
        kwargs = dict(
            authenticated_user_id    = "svc-account",
            message                  = self.test_message,
            type                     = self.test_type,
            priority                 = self.test_priority,
            target_user              = self.test_user_email,
            response_requested       = False,
            response_type            = None,
            timeout_seconds          = 120,
            response_default         = None,
            title                    = None,
            sender_id                = None,
            response_options         = None,
            abstract                 = None,
            job_id                   = None,
            queue_name               = None,
            suppress_ding            = False,
            progress_group_id        = None,
            prediction_hint_override = None,
            display_qualifier_widget = False,
            session_name             = None,
            idempotency_key          = None,
            notification_queue       = notification_queue,
            ws_manager               = ws_manager,
        )
        kwargs.update( overrides )
        return await notify_user( **kwargs )
    
    def test_notify_user_connected_queued( self ):
        """
        Test fire-and-forget notification when the target user is connected.

        Live contract (re-architected): auth is the require_api_key_or_jwt
        dependency (no api_key param); the email→system-id step is
        get_user_by_email (NOT the retired email_to_system_id); delivery is via
        the FIFO notification queue (push_notification), NOT a synchronous
        emit_to_user. A connected user yields status "queued" (the old
        "delivered" status is retired). PostgreSQL persistence is best-effort
        (wrapped in try/except) — get_db is patched to fail so the unit test
        stays DB-free; the non-fatal except keeps the path on the FIFO branch.

        Ensures:
            - get_user_by_email resolves the target email → system id
            - push_notification is invoked with the live source/user_id contract
            - Connection state is checked via the ws_manager
            - Returns status "queued" with target + connection metadata
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            mock_ws_manager = self._create_mock_websocket_manager(
                is_connected=True, connection_count=2, message_sent=True
            )

            with patch( 'cosa.rest.user_service.get_user_by_email', return_value={ "id": self.test_user_system_id } ) as mock_get_user, \
                 patch( 'cosa.rest.routers.notifications.get_db', side_effect=Exception( "no db in unit test" ) ), \
                 _patch_fastapi_main( Mock( app_debug=False, app_verbose=False ) ), \
                 patch( 'builtins.print' ):

                result = await self._call_notify_user( mock_notification_queue, mock_ws_manager )

                # Email → system id resolution (live helper)
                mock_get_user.assert_called_once_with( self.test_user_email )

                # Notification pushed to the FIFO queue with the live contract
                mock_notification_queue.push_notification.assert_called_once()
                push_kwargs = mock_notification_queue.push_notification.call_args.kwargs
                self.assertEqual( push_kwargs["message"], self.test_message )
                self.assertEqual( push_kwargs["type"], self.test_type )
                self.assertEqual( push_kwargs["priority"], self.test_priority )
                self.assertEqual( push_kwargs["source"], "claude_code" )
                self.assertEqual( push_kwargs["user_id"], self.test_user_system_id )

                # Connection state checked
                mock_ws_manager.is_user_connected.assert_called_once_with( self.test_user_system_id )
                mock_ws_manager.get_user_connection_count.assert_called_once_with( self.test_user_system_id )

                # Live response shape
                self.assertEqual( result["status"], "queued" )
                self.assertEqual( result["target_user"], self.test_user_email )
                self.assertEqual( result["target_system_id"], self.test_user_system_id )
                self.assertEqual( result["connection_count"], 2 )

        asyncio.run( run_test() )
    
    def test_notify_user_user_not_available( self ):
        """
        Test notification sending when user is not connected.
        
        Ensures:
            - Checks user connection status
            - Does not attempt WebSocket delivery  
            - Returns user_not_available status
            - Logs appropriate message
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            mock_ws_manager = self._create_mock_websocket_manager(
                is_connected=False, connection_count=0
            )

            with patch( 'cosa.rest.user_service.get_user_by_email', return_value={ "id": self.test_user_system_id } ), \
                 patch( 'cosa.rest.routers.notifications.get_db', side_effect=Exception( "no db in unit test" ) ), \
                 _patch_fastapi_main( Mock( app_debug=False, app_verbose=False ) ), \
                 patch( 'builtins.print' ):

                # Offline + NO job_id → no cc-listener fallback → user_not_available
                result = await self._call_notify_user( mock_notification_queue, mock_ws_manager, job_id=None )

                mock_ws_manager.is_user_connected.assert_called_once_with( self.test_user_system_id )
                mock_ws_manager.get_user_connection_count.assert_called_once_with( self.test_user_system_id )

                # Offline returns before pushing to the FIFO queue
                mock_notification_queue.push_notification.assert_not_called()

                self.assertEqual( result["status"], "user_not_available" )
                self.assertEqual( result["connection_count"], 0 )
                self.assertIn( "not connected to queue UI", result["message"] )

        asyncio.run( run_test() )
    
    def test_notify_user_offline_listener_fallback( self ):
        """
        Test the offline cross-user CC-listener fallback path.

        REPURPOSED (was test_notify_user_delivery_failed): the old synchronous
        "delivery_failed" status no longer exists — fire-and-forget delivery is
        now async via the FIFO queue, so a connected user always yields "queued"
        (no sync emit success/fail). The genuinely-interesting live branch worth
        covering is the OFFLINE + job_id path: when the target user is offline
        but a job_id is supplied, notify_user delegates to
        emit_to_user_or_listener_sync; if that delivers to a cc-listener-{job_id}
        session, the status is "delivered_via_listener".

        Ensures:
            - Offline user + job_id → emit_to_user_or_listener_sync consulted
            - listener_delivered=True → status "delivered_via_listener"
            - Response carries the cc-listener delivery path + session
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            # Offline, but the listener helper reports a successful delivery.
            mock_ws_manager = self._create_mock_websocket_manager(
                is_connected=False, connection_count=0, message_sent=True
            )

            with patch( 'cosa.rest.user_service.get_user_by_email', return_value={ "id": self.test_user_system_id } ), \
                 patch( 'cosa.rest.routers.notifications.get_db', side_effect=Exception( "no db in unit test" ) ), \
                 _patch_fastapi_main( Mock( app_debug=False, app_verbose=False ) ), \
                 patch( 'builtins.print' ):

                result = await self._call_notify_user(
                    mock_notification_queue, mock_ws_manager, job_id="dr-a1b2c3d4"
                )

                # Listener fallback consulted; FIFO push skipped (offline)
                mock_ws_manager.emit_to_user_or_listener_sync.assert_called_once()
                mock_notification_queue.push_notification.assert_not_called()

                self.assertEqual( result["status"], "delivered_via_listener" )
                self.assertEqual( result["delivery_path"], "cc-listener" )
                self.assertEqual( result["listener_session"], "cc-listener-dr-a1b2c3d4" )

        asyncio.run( run_test() )
    
    def test_notify_user_auth_delegated_to_dependency( self ):
        """
        Test that notify_user's auth contract moved to a FastAPI dependency.

        REPURPOSED (was test_notify_user_invalid_api_key): the in-function
        "Invalid API key → 401" check is RETIRED. Authentication is now enforced
        by the require_api_key_or_jwt FastAPI dependency, surfaced as the FIRST
        parameter `authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)]`.
        There is no longer an `api_key` parameter to validate in-function — so a
        bad-key 401 cannot originate here. This signature-contract test pins the
        migration and acts as a resurrection guard against re-adding in-function
        auth.

        Ensures:
            - notify_user exposes `authenticated_user_id` (the dependency seam)
            - notify_user no longer exposes an `api_key` parameter
            - The dependency is wired to require_api_key_or_jwt
        """
        import inspect
        from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

        sig = inspect.signature( notify_user )
        params = sig.parameters

        self.assertIn( "authenticated_user_id", params )
        self.assertNotIn( "api_key", params )

        # The first parameter carries the auth dependency (Annotated metadata
        # includes a Depends(require_api_key_or_jwt) marker).
        auth_param = params["authenticated_user_id"]
        annotated_meta = getattr( auth_param.annotation, "__metadata__", () )
        depends_markers = [ m for m in annotated_meta if getattr( m, "dependency", None ) is require_api_key_or_jwt ]
        self.assertEqual( len( depends_markers ), 1 )

    def test_notify_user_invalid_type( self ):
        """
        Test notification sending with invalid type.
        
        Ensures:
            - Raises HTTPException with 400 status
            - Includes valid types in error message
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_notification_queue = self._create_mock_notification_queue()
            mock_ws_manager = self._create_mock_websocket_manager()
            
            with self.assertRaises( HTTPException ) as context:
                await self._call_notify_user(
                    mock_notification_queue, mock_ws_manager, type="invalid_type"
                )

            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 400 )
            self.assertIn( "Invalid notification type", str( context.exception.detail ) )
            self.assertIn( "task, progress, alert, custom", str( context.exception.detail ) )
        
        asyncio.run( run_test() )
    
    def test_notify_user_invalid_priority( self ):
        """
        Test notification sending with invalid priority.
        
        Ensures:
            - Raises HTTPException with 400 status
            - Includes valid priorities in error message
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_notification_queue = self._create_mock_notification_queue()
            mock_ws_manager = self._create_mock_websocket_manager()
            
            with self.assertRaises( HTTPException ) as context:
                await self._call_notify_user(
                    mock_notification_queue, mock_ws_manager, priority="invalid_priority"
                )

            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 400 )
            self.assertIn( "Invalid priority", str( context.exception.detail ) )
            self.assertIn( "low, medium, high, urgent", str( context.exception.detail ) )
        
        asyncio.run( run_test() )
    
    def test_notify_user_empty_message( self ):
        """
        Test notification sending with empty message.
        
        Ensures:
            - Raises HTTPException with 400 status
            - Validates both empty and whitespace-only messages
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_notification_queue = self._create_mock_notification_queue()
            mock_ws_manager = self._create_mock_websocket_manager()
            
            # Live validation message changed: "Please provide a message to send"
            # (was "Message cannot be empty").
            # Test empty message
            with self.assertRaises( HTTPException ) as context:
                await self._call_notify_user(
                    mock_notification_queue, mock_ws_manager, message=""
                )

            self.assertEqual( context.exception.status_code, 400 )
            self.assertEqual( str( context.exception.detail ), "Please provide a message to send" )

            # Test whitespace-only message
            with self.assertRaises( HTTPException ) as context:
                await self._call_notify_user(
                    mock_notification_queue, mock_ws_manager, message="   "
                )

            self.assertEqual( context.exception.status_code, 400 )
            self.assertEqual( str( context.exception.detail ), "Please provide a message to send" )
        
        asyncio.run( run_test() )
    
    def test_get_user_notifications_success( self ):
        """
        Test user notifications retrieval success case.
        
        Ensures:
            - Retrieves notifications for user
            - Applies include_played filter
            - Limits results as requested
            - Returns proper response format
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            
            with patch( 'cosa.rest.routers.notifications.get_local_timestamp', return_value=self.test_timestamp ):
                result = await get_user_notifications(
                    user_id=self.test_user_system_id,
                    include_played=True,
                    limit=50,
                    notification_queue=mock_notification_queue
                )
                
                # Verify queue method called
                mock_notification_queue.get_user_notifications.assert_called_once_with(
                    user_id=self.test_user_system_id,
                    include_played=True
                )
                
                # Verify response format
                self.assertEqual( result["status"], "success" )
                self.assertEqual( result["user_id"], self.test_user_system_id )
                self.assertEqual( result["notification_count"], len( self.test_notification_list ) )
                self.assertEqual( result["include_played"], True )
                self.assertEqual( result["limit"], 50 )
                self.assertEqual( result["notifications"], self.test_notification_list )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_get_user_notifications_with_limit( self ):
        """
        Test user notifications retrieval with limit smaller than result set.
        
        Ensures:
            - Applies limit correctly when smaller than total results
            - Returns truncated notification list
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            
            with patch( 'cosa.rest.routers.notifications.get_local_timestamp', return_value=self.test_timestamp ):
                result = await get_user_notifications(
                    user_id=self.test_user_system_id,
                    include_played=False,
                    limit=1,  # Smaller than test data length
                    notification_queue=mock_notification_queue
                )
                
                # Verify response with limited results
                self.assertEqual( result["notification_count"], 1 )
                self.assertEqual( len( result["notifications"] ), 1 )
                self.assertEqual( result["limit"], 1 )
        
        asyncio.run( run_test() )
    
    def test_get_user_notifications_error( self ):
        """
        Test user notifications retrieval error handling.
        
        Ensures:
            - Catches exceptions from queue operations
            - Returns HTTPException with 500 status
            - Logs error details
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_notification_queue = Mock()
            mock_notification_queue.get_user_notifications.side_effect = Exception( "Database error" )
            
            with patch( 'builtins.print' ) as mock_print:
                with self.assertRaises( HTTPException ) as context:
                    await get_user_notifications(
                        user_id=self.test_user_system_id,
                        include_played=True,
                        limit=50,
                        notification_queue=mock_notification_queue
                    )
                
                # Verify HTTPException details
                self.assertEqual( context.exception.status_code, 500 )
                self.assertIn( "Failed to get notifications", str( context.exception.detail ) )
        
        asyncio.run( run_test() )
    
    def test_get_next_notification_found( self ):
        """
        Test next notification retrieval when notification exists.
        
        Ensures:
            - Retrieves next unplayed notification
            - Returns found status with notification data
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            
            with patch( 'cosa.rest.routers.notifications.get_local_timestamp', return_value=self.test_timestamp ):
                result = await get_next_notification(
                    user_id=self.test_user_system_id,
                    notification_queue=mock_notification_queue
                )
                
                # Verify queue method called
                mock_notification_queue.get_next_unplayed.assert_called_once_with( self.test_user_system_id )
                
                # Verify response format
                self.assertEqual( result["status"], "found" )
                self.assertEqual( result["user_id"], self.test_user_system_id )
                self.assertEqual( result["notification"], self.test_notification )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_get_next_notification_none_available( self ):
        """
        Test next notification retrieval when no notification exists.
        
        Ensures:
            - Returns none_available status
            - Includes null notification in response
        """
        async def run_test():
            mock_notification_queue = Mock()
            mock_notification_queue.get_next_unplayed.return_value = None
            
            with patch( 'cosa.rest.routers.notifications.get_local_timestamp', return_value=self.test_timestamp ):
                result = await get_next_notification(
                    user_id=self.test_user_system_id,
                    notification_queue=mock_notification_queue
                )
                
                # Verify response format
                self.assertEqual( result["status"], "none_available" )
                self.assertEqual( result["user_id"], self.test_user_system_id )
                self.assertIsNone( result["notification"] )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_mark_notification_played_success( self ):
        """
        Test marking notification as played success case.
        
        Ensures:
            - Calls queue mark_played method
            - Returns success status with details
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            
            with patch( 'cosa.rest.routers.notifications.get_local_timestamp', return_value=self.test_timestamp ):
                result = await mark_notification_played(
                    notification_id=self.test_notification_id,
                    notification_queue=mock_notification_queue
                )
                
                # Verify queue method called
                mock_notification_queue.mark_played.assert_called_once_with( self.test_notification_id )
                
                # Verify response format
                self.assertEqual( result["status"], "success" )
                self.assertIn( "marked as played", result["message"] )
                self.assertEqual( result["notification_id"], self.test_notification_id )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_mark_notification_played_not_found( self ):
        """
        Test marking notification as played when notification not found.
        
        Ensures:
            - Returns HTTPException with 404 status
            - Includes notification ID in error message
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_notification_queue = Mock()
            mock_notification_queue.mark_played.return_value = False
            
            with self.assertRaises( HTTPException ) as context:
                await mark_notification_played(
                    notification_id=self.test_notification_id,
                    notification_queue=mock_notification_queue
                )
            
            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 404 )
            self.assertIn( self.test_notification_id, str( context.exception.detail ) )
            self.assertIn( "not found", str( context.exception.detail ) )
        
        asyncio.run( run_test() )
    
    def test_delete_notification_success( self ):
        """
        Test notification deletion success case.
        
        Ensures:
            - Calls queue delete_by_id_hash method
            - Returns success status with details
        """
        async def run_test():
            mock_notification_queue = self._create_mock_notification_queue()
            
            with patch( 'cosa.rest.routers.notifications.get_local_timestamp', return_value=self.test_timestamp ):
                result = await delete_notification(
                    notification_id=self.test_notification_id,
                    notification_queue=mock_notification_queue
                )
                
                # Verify queue method called
                mock_notification_queue.delete_by_id_hash.assert_called_once_with( self.test_notification_id )
                
                # Verify response format
                self.assertEqual( result["status"], "success" )
                self.assertIn( "deleted", result["message"] )
                self.assertEqual( result["notification_id"], self.test_notification_id )
                self.assertEqual( result["timestamp"], self.test_timestamp )
        
        asyncio.run( run_test() )
    
    def test_delete_notification_not_found( self ):
        """
        Test notification deletion when notification not found.
        
        Ensures:
            - Returns HTTPException with 404 status
            - Includes notification ID in error message
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_notification_queue = Mock()
            mock_notification_queue.delete_by_id_hash.return_value = False
            
            with self.assertRaises( HTTPException ) as context:
                await delete_notification(
                    notification_id=self.test_notification_id,
                    notification_queue=mock_notification_queue
                )
            
            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 404 )
            self.assertIn( self.test_notification_id, str( context.exception.detail ) )
            self.assertIn( "not found", str( context.exception.detail ) )
        
        asyncio.run( run_test() )
    
    def test_dependency_functions( self ):
        """
        Test notification router dependency functions.
        
        Ensures:
            - All dependency functions can import fastapi_app.main
            - Dependencies return correct attributes
        """
        # Test get_notification_queue dependency
        mock_main = Mock()
        mock_main.jobs_notification_queue = "mock_notification_queue"
        with _patch_fastapi_main( mock_main ):
            result = get_notification_queue()
            self.assertEqual( result, "mock_notification_queue" )

        # Test get_websocket_manager dependency
        mock_main = Mock()
        mock_main.websocket_manager = "mock_websocket_manager"
        with _patch_fastapi_main( mock_main ):
            result = get_websocket_manager()
            self.assertEqual( result, "mock_websocket_manager" )
    
    def test_get_local_timestamp_success( self ):
        """
        Test local timestamp generation success case.
        
        Ensures:
            - Uses configured timezone from config manager
            - Returns timezone-aware ISO timestamp
            - Includes debug output when enabled
        """
        mock_config_mgr = Mock()
        mock_config_mgr.get.return_value = "America/New_York"
        
        mock_main_module = Mock()
        mock_main_module.config_mgr = mock_config_mgr
        mock_main_module.app_debug = False
        
        with _patch_fastapi_main( mock_main_module ), \
             patch( 'cosa.rest.routers.notifications.datetime' ) as mock_datetime, \
             patch( 'cosa.rest.routers.notifications.zoneinfo' ) as mock_zoneinfo:

            mock_timezone = Mock()
            mock_zoneinfo.ZoneInfo.return_value = mock_timezone
            
            mock_tz_aware_datetime = Mock()
            mock_tz_aware_datetime.isoformat.return_value = self.test_timestamp
            mock_datetime.now.return_value = mock_tz_aware_datetime
            
            result = get_local_timestamp()
            
            # Verify config lookup
            mock_config_mgr.get.assert_called_once_with( "app timezone", default="America/New_York" )
            
            # Verify timezone creation
            mock_zoneinfo.ZoneInfo.assert_called_once_with( "America/New_York" )
            
            # Verify datetime creation
            mock_datetime.now.assert_called_once_with( mock_timezone )
            
            self.assertEqual( result, self.test_timestamp )
    
    def test_get_local_timestamp_fallback_to_utc( self ):
        """
        Test local timestamp generation with timezone fallback.
        
        Ensures:
            - Falls back to UTC when timezone is invalid
            - Logs warning message
            - Returns valid timestamp
        """
        mock_config_mgr = Mock()
        mock_config_mgr.get.return_value = "Invalid/Timezone"
        
        mock_main_module = Mock()
        mock_main_module.config_mgr = mock_config_mgr
        mock_main_module.app_debug = True
        
        with _patch_fastapi_main( mock_main_module ), \
             patch( 'cosa.rest.routers.notifications.datetime' ) as mock_datetime, \
             patch( 'cosa.rest.routers.notifications.zoneinfo' ) as mock_zoneinfo, \
             patch( 'builtins.print' ) as mock_print:

            # Make zoneinfo raise exception
            mock_zoneinfo.ZoneInfo.side_effect = Exception( "Unknown timezone" )
            
            mock_utc_datetime = Mock()
            mock_utc_datetime.isoformat.return_value = "2025-08-05T17:00:00.000000"
            mock_datetime.now.return_value = mock_utc_datetime
            
            result = get_local_timestamp()
            
            # Verify fallback timestamp returned
            self.assertEqual( result, "2025-08-05T17:00:00.000000" )
            
            # Verify warning logged
            mock_print.assert_called()
            print_args = [call[0][0] for call in mock_print.call_args_list]
            warning_logged = any( "falling back to UTC" in arg for arg in print_args )
            self.assertTrue( warning_logged )
    
    def test_router_configuration( self ):
        """
        Test router configuration and metadata.
        
        Ensures:
            - Router has correct prefix and tags
            - Router is properly configured for FastAPI
        """
        # Verify router is configured
        self.assertIsNotNone( router )
        
        # Verify router has correct prefix and tags
        self.assertEqual( router.prefix, "/api" )
        self.assertIn( "notifications", router.tags )
        
        # Verify router is an APIRouter instance
        from fastapi import APIRouter
        self.assertIsInstance( router, APIRouter )


def isolated_unit_test():
    """
    Run comprehensive unit tests for notification management router in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real FastAPI or notification operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "Notification Management Router Unit Tests - REST API Phase 4", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_notify_user_connected_queued',
            'test_notify_user_user_not_available',
            'test_notify_user_offline_listener_fallback',
            'test_notify_user_auth_delegated_to_dependency',
            'test_notify_user_invalid_type',
            'test_notify_user_invalid_priority',
            'test_notify_user_empty_message',
            'test_get_user_notifications_success',
            'test_get_user_notifications_with_limit',
            'test_get_user_notifications_error',
            'test_get_next_notification_found',
            'test_get_next_notification_none_available',
            'test_mark_notification_played_success',
            'test_mark_notification_played_not_found',
            'test_delete_notification_success',
            'test_delete_notification_not_found',
            'test_dependency_functions',
            'test_get_local_timestamp_success',
            'test_get_local_timestamp_fallback_to_utc',
            'test_router_configuration'
        ]
        
        for method in test_methods:
            suite.addTest( TestNotificationsRouter( method ) )
        
        # Run tests with detailed output
        runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
        result = runner.run( suite )
        
        duration = time.time() - start_time
        
        # Calculate results
        tests_run = result.testsRun
        failures = len( result.failures )
        errors = len( result.errors )
        success_count = tests_run - failures - errors
        
        print( f"\n{'='*60}" )
        print( f"NOTIFICATION MANAGEMENT ROUTER UNIT TEST RESULTS" )
        print( f"{'='*60}" )
        print( f"Tests Run     : {tests_run}" )
        print( f"Passed        : {success_count}" )
        print( f"Failed        : {failures}" )
        print( f"Errors        : {errors}" )
        print( f"Success Rate  : {(success_count/tests_run)*100:.1f}%" )
        print( f"Duration      : {duration:.3f} seconds" )
        print( f"{'='*60}" )
        
        if failures > 0:
            print( "\nFAILURE DETAILS:" )
            for test, traceback in result.failures:
                print( f"❌ {test}: {traceback.split(chr(10))[-2]}" )
                
        if errors > 0:
            print( "\nERROR DETAILS:" )
            for test, traceback in result.errors:
                print( f"💥 {test}: {traceback.split(chr(10))[-2]}" )
        
        success = failures == 0 and errors == 0
        
        if success:
            du.print_banner( "✅ ALL NOTIFICATION MANAGEMENT ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME NOTIFICATION MANAGEMENT ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 NOTIFICATION MANAGEMENT ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Notification management router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )