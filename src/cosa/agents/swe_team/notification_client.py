#!/usr/bin/env python3
"""
WebSocket notification client for SWE Team orchestrator.

Connects to the Lupin WebSocket endpoint and queues incoming user messages
for consumption by the orchestrator at check-in points. Adapted from
BaseWebSocketListener with key differences:

    - Proxy processes immediately → this client QUEUES for later drain
    - Auth: generates JWT in-process via JwtService (no REST login)
    - Filter: only queues messages where notification_type == "user_initiated_message"
              AND job_id matches the target job
              (renamed from "user_message" for semantic clarity)
    - Urgent: if priority == "urgent", sets a threading.Event for interrupt

Dependency Rule:
    This module imports from base_listener (parent class) and jwt_service.
    It does NOT import from orchestrator, job, or cosa_interface.
"""

import asyncio
import logging
import queue
import threading
from typing import Optional

from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener
from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
)

logger = logging.getLogger( __name__ )


class OrchestratorNotificationClient( BaseWebSocketListener ):
    """
    WebSocket client that filters and queues user-initiated messages for the orchestrator.

    Runs in a daemon thread with its own asyncio event loop. Messages matching
    the target job_id with notification_type="user_initiated_message" are placed onto a
    shared threading.Queue for the orchestrator to drain at check-in points.

    Requires:
        - user_email is a valid registered email
        - job_id is the target SWE Team job ID
        - message_queue is a threading.Queue shared with orchestrator
        - urgent_event is a threading.Event shared with orchestrator

    Ensures:
        - Only user_initiated_message notifications for this job_id are queued
        - Urgent priority messages set the urgent_event for immediate check-in
        - Runs as a daemon thread (dies with parent process)
        - Reconnects with exponential backoff on disconnection
    """

    LOG_PREFIX = "[SWE-NotifClient]"

    def __init__(
        self,
        user_email,
        job_id,
        message_queue,
        urgent_event,
        host    = DEFAULT_SERVER_HOST,
        port    = DEFAULT_SERVER_PORT,
        debug   = False,
        verbose = False,
    ):
        """
        Initialize the orchestrator notification client.

        Requires:
            - user_email is a non-empty string
            - job_id is a non-empty string
            - message_queue is a threading.Queue instance
            - urgent_event is a threading.Event instance

        Ensures:
            - Stores target job_id for message filtering
            - Stores shared queue and event references
            - Does NOT connect (call start() to begin)

        Args:
            user_email: Email for JWT authentication
            job_id: Target job ID to filter messages for
            message_queue: Shared queue for orchestrator consumption
            urgent_event: Shared event for urgent interrupt signaling
            host: Server hostname
            port: Server port
            debug: Enable debug output
            verbose: Enable verbose output
        """
        # Generate a unique session ID for this WS connection
        session_id = f"swe-notif-{job_id}"

        super().__init__(
            email             = user_email,
            password          = "__jwt_bypass__",  # Not used — _login() is overridden
            session_id        = session_id,
            on_event          = self._on_event,
            subscribed_events = [ "notification_queue_update", "sys_ping" ],
            host              = host,
            port              = port,
            debug             = debug,
            verbose           = verbose,
        )

        self._target_job_id = job_id
        self._message_queue = message_queue
        self._urgent_event  = urgent_event
        self._thread        = None

    def _login( self ):
        """
        Generate JWT in-process via JwtService — no REST login needed.

        The orchestrator runs in the same process as the FastAPI server,
        so we can generate a valid JWT directly using the jwt_service module.

        Requires:
            - self.email is a valid registered email
            - jwt_service module is importable

        Ensures:
            - Returns a valid JWT access token string
            - Returns None on failure

        Returns:
            str or None: JWT access token
        """
        try:
            from cosa.rest.jwt_service import create_access_token
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.user_repository import UserRepository

            # Look up user to get user_id and roles
            with get_db() as db:
                user_repo = UserRepository( db )
                user = user_repo.get_by_email( self.email )

                if not user:
                    print( f"{self.LOG_PREFIX} User not found: {self.email}" )
                    return None

                token = create_access_token(
                    user_id = str( user.id ),
                    email   = self.email,
                    roles   = user.roles or [ "user" ],
                )

                if self.debug: print( f"{self.LOG_PREFIX} JWT generated in-process for {self.email}" )
                return token

        except Exception as e:
            logger.error( f"In-process JWT generation failed: {e}" )
            print( f"{self.LOG_PREFIX} JWT generation failed: {e}" )
            return None

    async def _on_event( self, event_type, data ):
        """
        Filter incoming events and queue matching user messages.

        Only processes notification_queue_update events that contain a
        notification with type="user_initiated_message" and a matching job_id.

        Requires:
            - event_type is a string
            - data is a dict with optional "notification" key

        Ensures:
            - Matching messages are placed on self._message_queue
            - Urgent messages also set self._urgent_event
            - Non-matching events are silently ignored
        """
        if event_type != "notification_queue_update":
            return

        notification = data.get( "notification", {} )

        # Filter: must be a user_initiated_message for our job
        notif_type = notification.get( "type" ) or notification.get( "notification_type" )
        notif_job_id = notification.get( "job_id" )

        if notif_type != "user_initiated_message":
            return

        if notif_job_id != self._target_job_id:
            if self.debug:
                print( f"{self.LOG_PREFIX} Ignoring user_initiated_message for different job: {notif_job_id}" )
            return

        # Extract message content
        message_text = notification.get( "message", "" )
        priority     = notification.get( "priority", "normal" )

        queued_msg = {
            "message"   : message_text,
            "priority"  : priority,
            "timestamp" : notification.get( "timestamp", "" ),
            "sender_id" : notification.get( "sender_id", "" ),
        }

        self._message_queue.put( queued_msg )

        if self.debug:
            print( f"{self.LOG_PREFIX} Queued user message (priority={priority}): {message_text[ :80 ]}" )

        # Urgent messages trigger immediate check-in
        if priority == "urgent":
            self._urgent_event.set()
            if self.debug:
                print( f"{self.LOG_PREFIX} URGENT interrupt signaled" )

    def start( self ):
        """
        Start the notification client in a daemon thread.

        Spawns a daemon thread with its own asyncio event loop that runs
        the WebSocket listener. The thread dies automatically when the
        parent process exits.

        Ensures:
            - Thread is started and running
            - Thread is a daemon (won't prevent process exit)
        """
        def _run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop( loop )
            try:
                loop.run_until_complete( self.run() )
            except Exception as e:
                logger.error( f"Notification client loop error: {e}" )
            finally:
                loop.close()

        self._thread = threading.Thread(
            target = _run_loop,
            name   = f"swe-notif-{self._target_job_id}",
            daemon = True,
        )
        self._thread.start()

        if self.debug:
            print( f"{self.LOG_PREFIX} Started daemon thread for job {self._target_job_id}" )

    def stop_sync( self ):
        """
        Synchronously stop the notification client and join the thread.

        Ensures:
            - Sets running flag to False
            - Closes WebSocket connection
            - Joins thread with timeout
        """
        self._running   = False
        self._connected = False

        # Close WebSocket from outside the event loop
        if self._ws:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete( self._ws.close() )
                loop.close()
            except Exception:
                pass  # Best effort

        if self._thread and self._thread.is_alive():
            self._thread.join( timeout=5.0 )
            if self.debug:
                print( f"{self.LOG_PREFIX} Thread joined for job {self._target_job_id}" )


def quick_smoke_test():
    """Quick smoke test for OrchestratorNotificationClient."""
    import cosa.utils.util as cu

    cu.print_banner( "OrchestratorNotificationClient Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.swe_team.notification_client import OrchestratorNotificationClient
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing instantiation..." )
        msg_queue = queue.Queue()
        urgent_evt = threading.Event()

        client = OrchestratorNotificationClient(
            user_email    = "test@test.com",
            job_id        = "swe-test123",
            message_queue = msg_queue,
            urgent_event  = urgent_evt,
            debug         = True,
        )
        assert client._target_job_id == "swe-test123"
        assert client._message_queue is msg_queue
        assert client._urgent_event is urgent_evt
        assert client.session_id == "swe-notif-swe-test123"
        print( f"✓ Client created: session={client.session_id}" )

        # Test 3: Event filtering — matching message
        print( "Testing event filtering (matching)..." )
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-test123",
                "message"  : "Use the existing auth module",
                "priority" : "normal",
            }
        } ) )
        assert not msg_queue.empty()
        msg = msg_queue.get_nowait()
        assert msg[ "message" ] == "Use the existing auth module"
        assert msg[ "priority" ] == "normal"
        print( "✓ Matching message queued correctly" )

        # Test 4: Event filtering — wrong job_id
        print( "Testing event filtering (wrong job_id)..." )
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-other456",
                "message"  : "This should be ignored",
                "priority" : "normal",
            }
        } ) )
        assert msg_queue.empty()
        print( "✓ Wrong job_id correctly ignored" )

        # Test 5: Event filtering — wrong notification type
        print( "Testing event filtering (wrong type)..." )
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "progress",
                "job_id"   : "swe-test123",
                "message"  : "This should be ignored too",
                "priority" : "medium",
            }
        } ) )
        assert msg_queue.empty()
        print( "✓ Wrong notification type correctly ignored" )

        # Test 6: Urgent priority sets event
        print( "Testing urgent interrupt..." )
        assert not urgent_evt.is_set()
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-test123",
                "message"  : "URGENT: Stop using deprecated API",
                "priority" : "urgent",
            }
        } ) )
        assert urgent_evt.is_set()
        assert not msg_queue.empty()
        msg = msg_queue.get_nowait()
        assert msg[ "priority" ] == "urgent"
        print( "✓ Urgent message sets interrupt event" )

        # Test 7: Non-matching event type
        print( "Testing non-notification event..." )
        urgent_evt.clear()
        asyncio.run( client._on_event( "job_state_transition", {
            "job_id": "swe-test123",
        } ) )
        assert msg_queue.empty()
        assert not urgent_evt.is_set()
        print( "✓ Non-notification events correctly ignored" )

        print( "\n✓ OrchestratorNotificationClient smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
