#!/usr/bin/env python3
"""
Simple test script for queue endpoint debugging (no pytest dependency)
"""

import asyncio
import aiohttp
import json

async def test_queue_endpoint():
    """Test queue endpoint to debug 500 error"""

    print("=" * 60)
    print("QUEUE ENDPOINT DEBUG TEST")
    print("=" * 60)

    server_url = "http://localhost:7999"

    # Test all queue types that are failing
    queue_types = ["todo", "run", "done", "dead"]

    async with aiohttp.ClientSession() as session:
        for queue_type in queue_types:
            endpoint = f"/api/get-queue/{queue_type}"
            url = f"{server_url}{endpoint}"

            print(f"\nTesting: {endpoint}")

            # Create headers with authentication
            headers = {
                "Authorization": "Bearer mock_token_test_user",
                "Content-Type": "application/json"
            }

            try:
                async with session.get(url, headers=headers) as response:
                    status = response.status

                    if status == 200:
                        data = await response.json()
                        print(f"  ✅ SUCCESS (200): {queue_type} queue returned data")
                        print(f"     Keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    else:
                        # Get error details
                        try:
                            error_data = await response.json()
                            print(f"  ❌ ERROR ({status}): {error_data}")
                        except:
                            error_text = await response.text()
                            print(f"  ❌ ERROR ({status}): {error_text[:200]}...")

            except Exception as e:
                print(f"  ❌ CONNECTION ERROR: {e}")

    print("\n" + "=" * 60)
    print("Queue endpoint testing complete")

if __name__ == "__main__":
    asyncio.run(test_queue_endpoint())