#!/usr/bin/env python3
"""
WebSocket Notification Diagnostic Script.

This script diagnoses why WebSocket notifications return 'user_not_available'
even when the user is logged into the Queue interface.

Usage:
    python src/scripts/test_websocket_notification.py \
        --email "$LUPIN_TEST_EMAIL" \
        --password "$LUPIN_TEST_PASSWORD" \
        --server http://localhost:7999
"""

import os
import sys
import argparse
import requests
import time
import json
from pathlib import Path

# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/scripts/test_websocket_notification.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable
import cosa.utils.util as du
from cosa.rest.user_service import get_user_by_email
from cosa.utils.config_loader import load_api_key


def login_user( email, password, server_url ):
    """
    Login via API and return JWT token + user_id.

    Requires:
        - email is valid user email
        - password is correct password
        - server_url is running FastAPI server

    Ensures:
        - Returns (access_token, user_id) on success
        - Raises exception on failure

    Args:
        email: User email address
        password: User password
        server_url: Base URL of Lupin server

    Returns:
        tuple: (access_token, user_id)

    Raises:
        Exception: If login fails
    """
    print( f"Logging in as {email}..." )

    try:
        response = requests.post(
            f"{server_url}/auth/login",
            json = {
                "email"    : email,
                "password" : password
            },
            timeout = 10
        )

        if response.status_code != 200:
            raise Exception( f"Login failed: HTTP {response.status_code} - {response.text}" )

        data = response.json()

        # Handle nested token structure (tokens.access_token)
        if "tokens" in data and "access_token" in data["tokens"]:
            access_token = data["tokens"]["access_token"]
            user_id = data.get( "user", {} ).get( "id" )
        elif "access_token" in data:
            access_token = data["access_token"]
            user_id = data.get( "user_id" )
        else:
            raise Exception( f"Login response missing access_token: {data}" )

        print( f"✓ Login successful" )
        print( f"  User ID: {user_id}" )
        print( f"  Token: {access_token[:50]}..." )
        print()

        return access_token, user_id

    except Exception as e:
        print( f"❌ Login failed: {e}" )
        raise


def check_websocket_state_via_admin_api( server_url, user_id ):
    """
    Query WebSocket state via admin API.

    Requires:
        - server_url is running FastAPI server
        - user_id is valid UUID string

    Ensures:
        - Returns dict with connection state from admin API
        - Never raises exception

    Args:
        server_url: Base URL of Lupin server
        user_id: User UUID string

    Returns:
        dict: Connection state or error info
    """
    try:
        response = requests.get(
            f"{server_url}/admin/websocket/status",
            timeout = 5
        )

        if response.status_code == 200:
            data = response.json()
            # Look for this user in the connections
            user_connections = 0
            for session in data.get( "active_connections", [] ):
                if session.get( "user_id" ) == user_id:
                    user_connections += 1

            return {
                "is_connected"     : user_connections > 0,
                "connection_count" : user_connections,
                "total_connections": len( data.get( "active_connections", [] ) ),
                "via_api"          : True
            }
        else:
            return {
                "is_connected"     : None,
                "connection_count" : 0,
                "error"            : f"Admin API returned {response.status_code}",
                "via_api"          : False
            }

    except Exception as e:
        # Admin API might not be available, that's okay
        return {
            "is_connected"     : None,
            "connection_count" : 0,
            "error"            : str( e ),
            "via_api"          : False
        }


def send_notification( email, server_url, api_key ):
    """
    Send notification via API and return response.

    Requires:
        - email is target user email
        - server_url is running FastAPI server
        - api_key is valid API key

    Ensures:
        - Returns response dict
        - Never raises exception (returns error in dict)

    Args:
        email: Target user email
        server_url: Base URL of Lupin server
        api_key: Claude Code API key

    Returns:
        dict: API response
    """
    try:
        response = requests.post(
            f"{server_url}/api/notify",
            params = {
                "message"     : "[DIAGNOSTIC] Test notification from diagnostic script",
                "type"        : "custom",
                "priority"    : "low",
                "target_user" : email
            },
            headers = {
                "X-API-Key" : api_key
            },
            timeout = 10
        )

        if response.status_code != 200:
            return {
                "success" : False,
                "status"  : "http_error",
                "code"    : response.status_code,
                "message" : response.text
            }

        return response.json()

    except Exception as e:
        return {
            "success" : False,
            "status"  : "exception",
            "message" : str( e )
        }


def main():
    """
    Main diagnostic flow.

    Returns:
        int: Exit code (0 = success, 1 = error)
    """
    parser = argparse.ArgumentParser(
        description='Diagnose WebSocket notification delivery issue',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--email',
        required = True,
        help = 'User email to login with'
    )

    parser.add_argument(
        '--password',
        required = True,
        help = 'User password'
    )

    parser.add_argument(
        '--server',
        default = 'http://localhost:7999',
        help = 'Server URL (default: http://localhost:7999)'
    )

    parser.add_argument(
        '--wait',
        type = int,
        default = 3,
        help = 'Seconds to wait for WebSocket auth (default: 3)'
    )

    args = parser.parse_args()

    # Display header
    du.print_banner( "WebSocket Notification Diagnostic", prepend_nl=True )

    print( f"Target User: {args.email}" )
    print( f"Server: {args.server}" )
    print( f"Wait Time: {args.wait} seconds" )
    print()

    try:
        # Step 1: Login
        du.print_banner( "Step 1: Login via API" )
        access_token, user_id = login_user( args.email, args.password, args.server )

        if not user_id:
            print( "❌ Warning: Login didn't return user_id, looking up from database..." )
            user_data = get_user_by_email( args.email )
            if user_data:
                user_id = user_data["id"]
                print( f"✓ Found user_id from database: {user_id}" )
                print()
            else:
                print( f"❌ Error: Could not find user_id for {args.email}" )
                return 1

        # Step 2: Wait for WebSocket auth to complete
        du.print_banner( "Step 2: Wait for WebSocket Auth" )
        print( f"Waiting {args.wait} seconds for WebSocket authentication to complete..." )
        print( "(This allows time for the Queue interface to establish WebSocket connection)" )
        print()

        time.sleep( args.wait )

        # Step 3: Check WebSocket connection state (via admin API if available)
        du.print_banner( "Step 3: Check WebSocket State" )
        ws_state = check_websocket_state_via_admin_api( args.server, user_id )

        print( f"WebSocket Connection Status for user {user_id}:" )

        if ws_state.get( "via_api" ):
            print( f"  (Queried via Admin API)" )
            print( f"  User connections: {ws_state['connection_count']}" )
            print( f"  Total server connections: {ws_state['total_connections']}" )

            if ws_state['is_connected']:
                print( f"  Status: ✓ Connected" )
            else:
                print( f"  Status: ❌ Not connected" )
        else:
            print( f"  (Admin API not available: {ws_state.get('error', 'unknown')})" )
            print( f"  Note: Will rely on notification API response to determine connection status" )

        print()

        # Only show warning if we know for sure user is disconnected
        if ws_state.get( "via_api" ) and not ws_state["is_connected"]:
            print( "❌ WARNING: User is NOT connected via WebSocket!" )
            print( "   This will cause notifications to return 'user_not_available'" )
            print()
            print( "   Possible reasons:" )
            print( "   1. Queue interface not open or WebSocket not connected" )
            print( "   2. WebSocket authentication failed (check server logs)" )
            print( "   3. Not enough time for auth to complete (increase --wait)" )
            print()

        # Step 4: Load API key and send notification
        du.print_banner( "Step 4: Send Notification" )

        # Load API key from config
        api_key_file = Path( lupin_root ) / "src/conf/keys/notification-api-claude-code-dev"
        api_key = load_api_key( str( api_key_file ) )

        print( f"Sending notification to {args.email}..." )
        print()

        notify_response = send_notification( args.email, args.server, api_key )

        print( "Notification API Response:" )
        print( json.dumps( notify_response, indent=2 ) )
        print()

        # Step 5: Analysis
        du.print_banner( "Analysis" )

        if notify_response.get( "status" ) == "user_not_available":
            print( "❌ DIAGNOSIS: Notification failed with 'user_not_available'" )
            print()
            print( "Root Cause:" )
            if ws_state.get( "via_api" ):
                if not ws_state["is_connected"]:
                    print( "  - Confirmed: User is NOT connected via WebSocket (Admin API)" )
                    print( "  - WebSocket authentication did not complete" )
                else:
                    print( "  - User IS connected (Admin API shows connection)" )
                    print( "  - But notification API reports user_not_available" )
                    print( "  - Possible user_id mismatch or logic error" )
            else:
                print( "  - WebSocket state unknown (Admin API not available)" )
                print( "  - But notification API reports user_not_available" )
                print( "  - User likely not connected or authentication failed" )

            print()
            print( "Recommendations:" )
            print( "  1. Check server logs for [WS-QUEUE-AUTH] messages" )
            print( "  2. Verify Queue interface is open and connected" )
            print( "  3. Check browser console for WebSocket errors" )
            print( "  4. Verify JWT token format and validity" )
            print( "  5. Check if frontend is sending auth_request message" )

        elif notify_response.get( "status" ) in ["delivered", "queued"]:
            print( "✅ SUCCESS: Notification delivered!" )
            print()
            print( f"Status: {notify_response.get( 'status' )}" )
            print( f"Connection count: {notify_response.get( 'connection_count', 0 )}" )

        else:
            print( f"❌ DIAGNOSIS: Unexpected response status: {notify_response.get( 'status' )}" )

        print()
        return 0

    except Exception as e:
        print()
        print( "❌ DIAGNOSTIC FAILED" )
        print( f"Error: {e}" )
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit( main() )
