#!/usr/bin/env python3
"""
Debug WebSocket connection issue
"""

import asyncio
import json
import websockets
from urllib.parse import quote

# Python path configured by src/tests/conftest.py

async def debug_websocket_connection():
    """Debug WebSocket connection step by step"""

    print("=" * 60)
    print("WEBSOCKET CONNECTION DEBUG")
    print("=" * 60)

    server_url = "localhost:7999"
    session_id = "test penguin"

    print(f"Original session ID: '{session_id}'")

    # URL encode the session ID
    encoded_session_id = quote(session_id)
    print(f"URL encoded session ID: '{encoded_session_id}'")

    uri = f"ws://{server_url}/ws/queue/{encoded_session_id}"
    print(f"WebSocket URI: {uri}")

    try:
        print("\nAttempting WebSocket connection...")
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connection established!")

            # Send valid auth message
            auth_message = {
                "type": "auth_request",
                "token": "mock_token_test_user",
                "subscribed_events": ["*"]
            }
            print(f"Sending auth message: {auth_message}")
            await websocket.send(json.dumps(auth_message))

            # Check for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)
                print(f"✅ Response received: {response_data}")

                if response_data.get("type") == "auth_success":
                    print("✅ Authentication successful!")
                    return True
                else:
                    print(f"❌ Authentication failed: {response_data}")

            except asyncio.TimeoutError:
                print("❌ No response received (timeout)")
            except Exception as e:
                print(f"❌ Response error: {e}")

    except websockets.exceptions.ConnectionClosedError as e:
        print(f"❌ WebSocket connection closed: {e}")
        print(f"   Close code: {e.code}")
        print(f"   Close reason: {e.reason}")
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ WebSocket invalid status code: {e}")
        print(f"   Status code: {e.status_code}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")

    return False

if __name__ == "__main__":
    success = asyncio.run(debug_websocket_connection())
    if success:
        print("\n✅ WebSocket connection debug passed!")
    else:
        print("\n❌ WebSocket connection debug failed!")