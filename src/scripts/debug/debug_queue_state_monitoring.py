#!/usr/bin/env python3
"""
Debug the specific queue state monitoring test failure
"""

import asyncio
import aiohttp
import json

async def test_queue_state_monitoring_debug():
    """Replicate the exact queue state monitoring test to debug the 500 error"""

    print("=" * 60)
    print("QUEUE STATE MONITORING DEBUG")
    print("=" * 60)

    server_url = "http://localhost:7999"
    auth_token = "Bearer mock_token_email_test@example.com"
    session_id = "wise penguin"

    headers = {
        "Authorization": auth_token,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:

        # Step 1: Get initial state of all queues (exactly like smoke test)
        print("\n1. Getting initial queue states...")
        initial_states = {}
        queue_types = ["todo", "run", "done", "dead"]

        for queue_type in queue_types:
            endpoint = f"/api/get-queue/{queue_type}"
            url = f"{server_url}{endpoint}"
            print(f"   Checking {queue_type} queue...")

            try:
                async with session.get(url, headers=headers) as response:
                    status = response.status
                    if status == 200:
                        data = await response.json()
                        initial_states[queue_type] = data
                        print(f"   ✅ {queue_type}: {list(data.keys())}")
                    else:
                        error_text = await response.text()
                        print(f"   ❌ {queue_type} ERROR ({status}): {error_text[:100]}...")
                        return False
            except Exception as e:
                print(f"   ❌ {queue_type} EXCEPTION: {e}")
                return False

        print(f"\n   Initial states captured for {len(initial_states)} queues")

        # Step 2: Submit multiple jobs (exactly like smoke test)
        print("\n2. Submitting multiple jobs...")
        for i in range(3):
            job_message = f"State monitoring test job {i+1}"
            job_data = {
                "question": job_message,
                "websocket_id": session_id
            }

            url = f"{server_url}/api/push"
            print(f"   Submitting job {i+1}: {job_message}")

            try:
                async with session.post(url, headers=headers, json=job_data) as response:
                    if response.status == 200:
                        print(f"   ✅ Job {i+1} submitted successfully")
                    else:
                        error_text = await response.text()
                        print(f"   ❌ Job {i+1} FAILED ({response.status}): {error_text[:100]}...")
            except Exception as e:
                print(f"   ❌ Job {i+1} EXCEPTION: {e}")

        # Step 3: Wait for processing (exactly like smoke test)
        print("\n3. Waiting for processing...")
        await asyncio.sleep(2)

        # Step 4: Check final state (where 500 error occurs)
        print("\n4. Checking final queue states...")
        final_states = {}

        for queue_type in queue_types:
            endpoint = f"/api/get-queue/{queue_type}"
            url = f"{server_url}{endpoint}"
            print(f"   Checking {queue_type} queue...")

            try:
                async with session.get(url, headers=headers) as response:
                    status = response.status
                    if status == 200:
                        data = await response.json()
                        final_states[queue_type] = data
                        print(f"   ✅ {queue_type}: {list(data.keys())}")
                    else:
                        error_text = await response.text()
                        print(f"   ❌ {queue_type} ERROR ({status}): {error_text[:200]}...")
                        print(f"      This is likely the 500 error source!")

                        # Try to get more detail
                        try:
                            error_data = await response.json()
                            print(f"      Error details: {error_data}")
                        except:
                            pass

                        return False
            except Exception as e:
                print(f"   ❌ {queue_type} EXCEPTION: {e}")
                return False

        print(f"\n   Final states captured for {len(final_states)} queues")

        # Step 5: Compare states (basic validation)
        print("\n5. Comparing states...")
        for queue_type in queue_types:
            initial = initial_states[queue_type]
            final = final_states[queue_type]

            # Just check that we got valid responses
            if isinstance(initial, dict) and isinstance(final, dict):
                print(f"   ✅ {queue_type}: State comparison possible")
            else:
                print(f"   ⚠️  {queue_type}: Unexpected state format")

    print("\n✅ Queue state monitoring debug completed successfully!")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_queue_state_monitoring_debug())
    if success:
        print("\n✅ No 500 error detected in queue state monitoring!")
    else:
        print("\n❌ 500 error reproduced in queue state monitoring!")