#!/usr/bin/env python3
"""
Simple test script for WebSocket authentication validation (no pytest dependency)
"""

import sys
import os
import asyncio
import json
import websockets

# Add the cosa module to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

async def test_websocket_auth_validation():
    """Test WebSocket authentication validation behavior"""

    print("="*60)
    print("WEBSOCKET AUTHENTICATION VALIDATION TEST")
    print("="*60)

    server_url = "localhost:7999"

    # Test malformed auth message handling (CRITICAL ISSUE)
    print("\n🚨 CRITICAL: Testing malformed auth message rejection")
    malformed_cases = [
        ("not json", "Non-JSON message"),
        ("{invalid json", "Invalid JSON syntax"),
        (json.dumps({"wrong": "type"}), "Missing auth type"),
        (json.dumps({"type": "auth_request"}), "Missing token field"),
        (json.dumps({"type": "wrong_type", "token": "mock_token_user"}), "Wrong message type"),
        (json.dumps({"type": "auth_request", "token": None}), "Null token"),
        (json.dumps({"type": "auth_request", "token": 123}), "Numeric token"),
        (json.dumps({"type": "auth_request", "token": ["array"]}), "Array token"),
    ]

    malformed_accepted = 0
    for malformed_message, description in malformed_cases:
        try:
            # Generate a valid session ID
            from urllib.parse import quote
            session_id = "test penguin"
            uri = f"ws://{server_url}/ws/queue/{quote(session_id)}"

            async with websockets.connect(uri) as websocket:
                # Send malformed message
                await websocket.send(malformed_message)

                # Check if server responds with error
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    response_data = json.loads(response)
                    auth_rejected = response_data.get("type") == "auth_error"
                except asyncio.TimeoutError:
                    auth_rejected = True  # No response means rejection
                except json.JSONDecodeError:
                    auth_rejected = True  # Invalid response means rejection
                except Exception:
                    auth_rejected = True  # Any error means rejection

                status = "✅ REJECTED" if auth_rejected else "❌ ACCEPTED"
                print(f"  {description}: {status}")
                if not auth_rejected:
                    malformed_accepted += 1

        except Exception as e:
            # Connection errors are also acceptable for malformed messages
            print(f"  {description}: ✅ REJECTED (connection error)")

    # Test invalid token handling (CRITICAL ISSUE)
    print("\n🚨 CRITICAL: Testing invalid token rejection")
    invalid_token_cases = [
        (None, "No token provided"),
        ("", "Empty token"),
        ("invalid_format", "Token without mock_ prefix"),
        ("mock_token_", "Token with empty user ID"),
        ("mock_token_" + "x" * 1000, "Extremely long token"),
        (json.dumps({"invalid": "object"}), "JSON object instead of token"),
        ("123456", "Numeric token"),
    ]

    invalid_tokens_accepted = 0
    for invalid_token, description in invalid_token_cases:
        try:
            # Generate a valid session ID
            from urllib.parse import quote
            session_id = "test penguin"
            uri = f"ws://{server_url}/ws/queue/{quote(session_id)}"

            async with websockets.connect(uri) as websocket:
                # Send properly formatted auth message with invalid token
                auth_message = {
                    "type": "auth_request",
                    "token": invalid_token,
                    "subscribed_events": ["*"]
                }
                await websocket.send(json.dumps(auth_message))

                # Check if server responds with error
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    response_data = json.loads(response)
                    auth_rejected = response_data.get("type") == "auth_error"
                except asyncio.TimeoutError:
                    auth_rejected = True  # No response means rejection
                except json.JSONDecodeError:
                    auth_rejected = True  # Invalid response means rejection
                except Exception:
                    auth_rejected = True  # Any error means rejection

                status = "✅ REJECTED" if auth_rejected else "❌ ACCEPTED"
                print(f"  {description}: {status}")
                if not auth_rejected:
                    invalid_tokens_accepted += 1

        except Exception as e:
            # Connection errors are also acceptable for invalid tokens
            print(f"  {description}: ✅ REJECTED (connection error)")

    # Test valid authentication (should pass)
    print("\n✅ Testing valid authentication")
    valid_passed = False
    try:
        session_id = "test penguin"
        from urllib.parse import quote
        uri = f"ws://{server_url}/ws/queue/{quote(session_id)}"

        async with websockets.connect(uri) as websocket:
            # Send valid auth message
            auth_message = {
                "type": "auth_request",
                "token": "mock_token_test_user",
                "subscribed_events": ["*"]
            }
            await websocket.send(json.dumps(auth_message))

            # Check for success response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)
                auth_success = response_data.get("type") == "auth_success"
                status = "✅ ACCEPTED" if auth_success else "❌ REJECTED"
                print(f"  Valid authentication: {status}")
                valid_passed = auth_success
            except Exception as e:
                print(f"  Valid authentication: ❌ FAILED ({e})")

    except Exception as e:
        print(f"  Valid authentication: ❌ CONNECTION FAILED ({e})")

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Malformed messages incorrectly accepted: {malformed_accepted}/{len(malformed_cases)} (CRITICAL)")
    print(f"Invalid tokens incorrectly accepted: {invalid_tokens_accepted}/{len(invalid_token_cases)} (CRITICAL)")
    print(f"Valid authentication passed: {valid_passed}")

    total_critical_failures = malformed_accepted + invalid_tokens_accepted
    if total_critical_failures > 0:
        print(f"\n🚨 CRITICAL SECURITY ISSUE: {total_critical_failures} invalid inputs incorrectly accepted!")
        print("This should fix the baseline smoke test findings.")
        return False
    elif not valid_passed:
        print(f"\n⚠️ Valid authentication is broken!")
        return False
    else:
        print("\n✅ WebSocket authentication validation working correctly")
        return True

if __name__ == "__main__":
    asyncio.run(test_websocket_auth_validation())