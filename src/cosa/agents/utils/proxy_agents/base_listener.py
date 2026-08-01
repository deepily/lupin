#!/usr/bin/env python3
"""
Base WebSocket Listener for proxy agents.

Connects to the Lupin FastAPI WebSocket endpoint, authenticates via JWT,
subscribes to specified events, and dispatches received events to a
callback handler. Includes exponential backoff reconnection.

Subclasses (notification proxy, decision proxy) pass their own
subscribed_events list and on_event callback.

Dependency Rule:
    This module NEVER imports from notification_proxy, decision_proxy, or swe_team.

References:
    - src/scripts/debug/debug_websocket_auth_validation.py (client pattern)
    - src/cosa/rest/websocket_manager.py (server-side subscription logic)
"""

import asyncio
import json
import time
from urllib.parse import quote
from typing import Callable, List, Optional

import requests
import websockets

from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_BACKOFF_FACTOR,
)


class BaseWebSocketListener:
    """
    Async WebSocket client that connects, authenticates, subscribes
    to events, and dispatches them to a callback.

    Requires:
        - email is a valid user email
        - session_id is a non-empty string
        - on_event is an async callable accepting (event_type, event_data)
        - subscribed_events is a non-empty list of event type strings

    Ensures:
        - Maintains persistent connection with keep-alive ping/pong
        - Reconnects with exponential backoff on disconnection
        - Calls on_event for every received WebSocket message
    """

    # Subclass override point: log prefix for all messages
    LOG_PREFIX = "[Listener]"

    def __init__(
        self,
        email,
        password,
        session_id,
        on_event,
        subscribed_events,
        host    = DEFAULT_SERVER_HOST,
        port    = DEFAULT_SERVER_PORT,
        debug   = False,
        verbose = False
    ):
        """
        Initialize the WebSocket listener.

        Requires:
            - email is a non-empty string
            - password is a non-empty string
            - session_id is a non-empty string
            - on_event is an async callable( event_type: str, event_data: dict )
            - subscribed_events is a non-empty list of event type strings

        Ensures:
            - Stores connection parameters
            - Does NOT connect (call run() to start)

        Args:
            email: User email for JWT authentication
            password: User password for JWT authentication
            session_id: WebSocket session identifier
            on_event: Async callback for received events
            subscribed_events: List of WebSocket event types to subscribe to
            host: Server hostname (default: localhost)
            port: Server port (default: 7999)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.email             = email
        self.password          = password
        self.session_id        = session_id
        self.on_event          = on_event
        self.subscribed_events = subscribed_events
        self.host              = host
        self.port              = port
        self.debug             = debug
        self.verbose           = verbose

        self._ws        = None
        self._running   = False
        self._connected = False
        self._attempt   = 0
        self._user_id   = None
        self._token     = None

    @property
    def is_connected( self ):
        """Whether the WebSocket is currently connected and authenticated."""
        return self._connected

    async def _on_connected( self ):
        """
        Connect hook — fired once per successful connect, after auth_success and
        before the receive loop. Default no-op; subclasses override to run
        catch-up on connect (e.g. the CC listener pulls answers owed to its
        persona that landed while it was disconnected — §4.4).

        Ensures:
            - default implementation does nothing (pure live subscribers)
        """
        pass

    async def run( self ):
        """
        Start the listener with automatic reconnection.

        Requires:
            - Server is running at host:port

        Ensures:
            - Connects, authenticates, and enters receive loop
            - Reconnects with exponential backoff on disconnection
            - Stops after RECONNECT_MAX_ATTEMPTS consecutive failures
            - Returns cleanly when stop() is called
        """
        self._running = True
        self._attempt = 0

        while self._running and self._attempt < RECONNECT_MAX_ATTEMPTS:
            try:
                await self._connect_and_listen()
                # Clean exit means stop() was called
                if not self._running:
                    break
                # Connection dropped — reset for reconnect
                self._connected = False
                self._attempt += 1
                delay = min(
                    RECONNECT_INITIAL_DELAY * ( RECONNECT_BACKOFF_FACTOR ** self._attempt ),
                    RECONNECT_MAX_DELAY
                )
                print( f"{self.LOG_PREFIX} Connection lost. Reconnecting in {delay:.1f}s (attempt {self._attempt}/{RECONNECT_MAX_ATTEMPTS})..." )
                await asyncio.sleep( delay )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._attempt += 1
                delay = min(
                    RECONNECT_INITIAL_DELAY * ( RECONNECT_BACKOFF_FACTOR ** self._attempt ),
                    RECONNECT_MAX_DELAY
                )
                print( f"{self.LOG_PREFIX} Error: {e}. Reconnecting in {delay:.1f}s (attempt {self._attempt}/{RECONNECT_MAX_ATTEMPTS})..." )
                await asyncio.sleep( delay )

        if self._attempt >= RECONNECT_MAX_ATTEMPTS:
            print( f"{self.LOG_PREFIX} Max reconnection attempts ({RECONNECT_MAX_ATTEMPTS}) reached. Giving up." )

    async def stop( self ):
        """
        Gracefully stop the listener.

        Ensures:
            - Sets running flag to False
            - Closes WebSocket connection if open
        """
        self._running   = False
        self._connected = False
        if self._ws:
            await self._ws.close()

    def _login( self ):
        """
        Authenticate via REST API and return JWT access token.

        Requires:
            - self.email and self.password are non-empty
            - Server is running at self.host:self.port

        Ensures:
            - Returns JWT token string on success
            - Returns None on failure (with error printed)
        """
        url = f"http://{self.host}:{self.port}/auth/login"

        try:
            resp = requests.post(
                url,
                json    = { "email": self.email, "password": self.password },
                timeout = 30
            )
        except requests.ConnectionError:
            print( f"{self.LOG_PREFIX} Cannot connect to {url} -- is the server running?" )
            return None
        except requests.Timeout:
            print( f"{self.LOG_PREFIX} Login request timed out ({url})" )
            return None

        if resp.status_code == 200:
            token = resp.json()[ "tokens" ][ "access_token" ]
            if self.debug: print( f"{self.LOG_PREFIX} JWT obtained for {self.email}" )
            return token

        print( f"{self.LOG_PREFIX} Login failed: {resp.status_code}" )
        print( f"{self.LOG_PREFIX} Response: {resp.text[ :200 ]}" )
        print()
        print( "  Possible fixes:" )
        print( "  1. Account may not exist. Register it:" )
        print( f'     curl -X POST "http://{self.host}:{self.port}/auth/register" \\' )
        print( f'       -H "Content-Type: application/json" \\' )
        print( f'       -d \'{{"email": "{self.email}", "password": "<your-password>"}}\'' )
        print( "  2. Password may be wrong. Check your env vars:" )
        print( "     LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
        return None

    async def _connect_and_listen( self ):
        """
        Single connection lifecycle: connect, auth, subscribe, receive loop.

        Requires:
            - self._running is True

        Ensures:
            - Logs in via REST to obtain JWT
            - Authenticates WebSocket with Bearer token
            - Subscribes to configured events
            - Dispatches events to on_event callback
            - Responds to sys_ping with sys_pong (keep-alive)
            - Returns on disconnection or stop()
        """
        # Obtain a fresh JWT (handles token expiry on reconnects)
        jwt_token = self._login()
        if jwt_token is None:
            print( f"{self.LOG_PREFIX} Authentication failed -- cannot obtain JWT" )
            return

        encoded_session = quote( self.session_id )
        uri = f"ws://{self.host}:{self.port}/ws/queue/{encoded_session}"

        if self.debug: print( f"{self.LOG_PREFIX} Connecting to {uri}..." )

        async with websockets.connect( uri ) as ws:
            self._ws = ws

            # Send auth message with real JWT
            self._token = f"Bearer {jwt_token}"
            auth_msg = {
                "type"              : "auth_request",
                "token"             : self._token,
                "session_id"        : self.session_id,
                "subscribed_events" : self.subscribed_events
            }
            await ws.send( json.dumps( auth_msg ) )

            # Wait for auth response
            auth_response = await asyncio.wait_for( ws.recv(), timeout=10.0 )
            auth_data     = json.loads( auth_response )

            if auth_data.get( "type" ) == "auth_success":
                self._connected = True
                self._attempt   = 0  # Reset backoff on successful connect
                self._user_id   = auth_data.get( "user_id", "unknown" )

                print( "" )
                print( "  " + "-" * 54 )
                print( "  Authenticated" )
                print( "  " + "-" * 54 )
                print( f"  Email      : {self.email}" )
                print( f"  User ID    : {self._user_id}" )
                print( f"  Session ID : {self.session_id}" )
                print( f"  Token      : {self._token}" )
                print( "  " + "-" * 54 )
                print( "" )

                if self.debug and self.verbose:
                    print( f"{self.LOG_PREFIX} Auth response: {json.dumps( auth_data, indent=2 )}" )
            elif auth_data.get( "type" ) == "auth_error":
                print( f"{self.LOG_PREFIX} Authentication failed: {auth_data.get( 'message', 'unknown error' )}" )
                return
            else:
                print( f"{self.LOG_PREFIX} Unexpected auth response: {auth_data}" )
                return

            # Connect hook (default no-op; the CC listener overrides it to catch
            # up on answers owed to this persona that landed while it was
            # disconnected — §4.4). Fires on EVERY connect edge: a listener
            # respawn after a bounce IS a first connect, so unlike the browser
            # rehydrator (reconnect edge only) we fire here on both.
            await self._on_connected()

            # Receive loop
            async for message in ws:
                if not self._running:
                    break

                try:
                    data       = json.loads( message )
                    event_type = data.get( "type", "unknown" )

                    # Handle ping/pong keep-alive
                    if event_type == "sys_ping":
                        pong = { "type": "sys_pong" }
                        await ws.send( json.dumps( pong ) )
                        if self.verbose: print( f"{self.LOG_PREFIX} Pong sent" )
                        continue

                    # Dispatch to callback
                    await self.on_event( event_type, data )

                except json.JSONDecodeError as e:
                    print( f"{self.LOG_PREFIX} Invalid JSON received: {e}" )
                except Exception as e:
                    log_msg = f"{self.LOG_PREFIX} Error handling message: {e}"
                    if hasattr( self, '_log' ):
                        self._log( log_msg )
                    else:
                        print( log_msg )
