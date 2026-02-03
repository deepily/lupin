#!/usr/bin/env python3
"""
Simple test to debug WebSocket connection issues
"""

import asyncio
import json
import websockets

async def test_basic_connection():
    """Test basic WebSocket connection"""

    print("="*60)
    print("BASIC WEBSOCKET CONNECTION TEST")
    print("="*60)

    server_url = "localhost:7999"

    # Test with different session ID formats
    test_cases = [
        "wise penguin",
        "test_penguin",
        "clever fox",
        "brave tiger"
    ]

    for session_id in test_cases:
        try:
            print(f"\nTesting session ID: '{session_id}'")

            # URL encode the session ID
            from urllib.parse import quote
            encoded_session_id = quote(session_id)
            uri = f"ws://{server_url}/ws/queue/{encoded_session_id}"
            print(f"URI: {uri}")

            async with websockets.connect(uri) as websocket:
                print(f"  ✅ Connected successfully")

                # Send valid auth message
                auth_message = {
                    "type": "auth_request",
                    "token": "mock_token_test_user",
                    "subscribed_events": ["*"]
                }
                await websocket.send(json.dumps(auth_message))
                print(f"  ✅ Auth message sent")

                # Check for response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    response_data = json.loads(response)
                    print(f"  ✅ Response received: {response_data.get('type', 'unknown')}")

                    if response_data.get("type") == "auth_success":
                        print(f"  ✅ Authentication successful!")
                        return True
                    else:
                        print(f"  ❌ Authentication failed: {response_data}")

                except asyncio.TimeoutError:
                    print(f"  ❌ No response received (timeout)")
                except Exception as e:
                    print(f"  ❌ Response error: {e}")

        except Exception as e:
            print(f"  ❌ Connection failed: {e}")

    return False

if __name__ == "__main__":
    success = asyncio.run(test_basic_connection())
    if success:
        print("\n✅ WebSocket connection test passed!")
    else:
        print("\n❌ WebSocket connection test failed!")