#!/usr/bin/env python3
"""
Job Queue Workflow Smoke Tests

Comprehensive smoke tests for the Lupin job queue system including:
- Job submission via /api/v2/ask (prose) and /api/v2/submit (decided command)
- Queue state transitions (TODO → RUNNING → DONE → DEAD)
- Job completion notifications via tts_job_request
- Queue count updates via WebSocket events
- Job lifecycle validation
"""

import sys
import os

# Bootstrap using LUPIN_ROOT for standalone script execution
# (conftest.py handles this for pytest)
if __name__ == "__main__":
    lupin_root = os.environ.get( 'LUPIN_ROOT' )
    if lupin_root is None:
        raise RuntimeError(
            "LUPIN_ROOT environment variable not set.\n"
            "Set it before running:\n"
            "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
            "  python src/tests/lupin_smoke/test_queue_workflow.py"
        )
    src_path = os.path.join( lupin_root, 'src' )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

import asyncio
import json
import time

from tests.lupin_smoke.utilities import (
    LupinTestClient, TestValidator,
    print_test_banner, run_test_with_error_handling
)


class QueueWorkflowHelper:
    """Helper utilities specifically for queue workflow testing."""
    
    def __init__(self, client: LupinTestClient):
        self.client = client
    
    async def push_job(self, message: str, job_type: str = "test") -> dict:
        """
        Submit a bare question through the v2 front door.

        Migrated off /api/push, which is now a 410 tombstone: "Every question now
        enters through /api/v2/ask." Rick's 2026-08-21 entry-point ruling collapsed
        eighteen doors into two, because eighteen doors meant eighteen places a
        guard would have to be installed.

        `interactive=False` because NOBODY IS WATCHING. On the interactive path a
        command missing an argument PARKS and asks the user for it, and a parked
        question in an unattended smoke run is a job that never returns and a suite
        that hangs until its timeout. With it false the same case comes straight
        back as status='needs_input', which a test can actually assert on.

        `speak=False` for the same reason: the answer would otherwise be dispatched
        as a TTS notification, so every smoke run would talk to whoever happens to
        be at the machine.

        Args:
            message: the question text
            job_type: accepted for call-compatibility; the v2 door does not use it

        Returns:
            API response
        """
        data = {
            "question"     : message,
            "websocket_id" : self.client.session_id,
            "speak"        : False,
            "interactive"  : False,
        }
        
        response = await self.client.http_request("POST", "/api/v2/ask", json=data)
        return response
    
    async def submit_job(self, command: str, args: dict = None) -> dict:
        """
        Submit work whose command is already decided, through the OTHER v2 door.

        /api/v2/ask and /api/v2/submit are not interchangeable. `ask` is handed
        prose and has to work out what it means; `submit` is handed the answer to
        that question up front. The two retired doors point at them separately —
        /api/push names ask, /api/push-agentic names submit — so which one a caller
        wants is a real choice, not a formatting detail.

        This exists for the queue-observation tests. An agentic command comes back
        status='waiting' once the job is QUEUED rather than running it to
        completion, which is what leaves a todo/running window for a WebSocket
        listener to actually see. A conversational question through `ask` holds the
        caller for the agent's whole span and the transitions are over before it
        returns.

        Args:
            command: a routing command, e.g. "agent router go to claude code"
            args: every argument that command requires — no extraction is performed

        Returns:
            API response
        """
        data = {
            "command"      : command,
            "args"         : args or {},
            "websocket_id" : self.client.session_id,
            "speak"        : False,
        }
        
        response = await self.client.http_request("POST", "/api/v2/submit", json=data)
        return response
    
    async def get_queue_status(self, queue_type: str) -> dict:
        """
        Get queue status/count.
        
        Args:
            queue_type: "todo", "run", "done", or "dead"
            
        Returns:
            Queue status response
        """
        response = await self.client.http_request("GET", f"/api/get-queue/{queue_type}")
        return response
    
    async def get_queue_contents(self, queue_type: str) -> dict:
        """
        Get queue contents.
        
        Args:
            queue_type: "todo", "run", "done", or "dead"
            
        Returns:
            Queue contents response
        """
        response = await self.client.http_request("GET", f"/api/queue/{queue_type}")
        return response


class QueueWorkflowSmokeTests:
    """Smoke tests for job queue workflow functionality."""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.client = LupinTestClient(debug=debug)
        self.queue_helper = QueueWorkflowHelper(self.client)
        self.validator = TestValidator()
        self.test_results = []
    
    async def test_queue_status_endpoints(self):
        """Test basic queue status endpoints."""
        queue_types = ["todo", "run", "done", "dead"]
        
        for queue_type in queue_types:
            response = await self.queue_helper.get_queue_status(queue_type)
            self.validator.assert_response_ok(response, 200)
            
            data = response.json()
            # Should return queue count information
            assert isinstance(data, (int, dict)), \
                f"Queue status should return count or status object for {queue_type}"
            
            if isinstance(data, dict):
                # If it's a dict, it might have count, items, etc.
                if "count" in data:
                    assert isinstance(data["count"], int), \
                        f"Queue count should be integer for {queue_type}"
    
    async def test_job_submission(self):
        """Test job submission via the v2 front door."""
        test_message = "What is 5 + 5?"
        
        # Get initial TODO count
        initial_response = await self.queue_helper.get_queue_status("todo")
        self.validator.assert_response_ok(initial_response, 200)
        
        # Submit a job
        push_response = await self.queue_helper.push_job(test_message)
        
        # Should accept job submission
        self.validator.assert_response_ok(push_response, 200)
        
        push_data = push_response.json()
        
        # Response should indicate success.
        #
        # The old assertion accepted "success" / "queued" / "accepted". The v2 door
        # declares its status vocabulary as done | waiting | parked | needs_input |
        # expired | failed, so that set named NONE of the six and could not have
        # passed here whatever the server did. It was carried over from /api/push.
        #
        # Two of the six are acceptance: `done` (ran and answered inline) and
        # `waiting` (queued for an executor — flow.py calls this "a SUCCESS, not a
        # degrade"). Which one comes back depends on where the router sends the
        # question, not on whether submission worked, so both are allowed here.
        # `parked` cannot occur because push_job sends interactive=False.
        self.validator.assert_json_contains(push_data, ["status", "trace_id"])
        assert push_data["status"] in ("done", "waiting"), \
            f"Job submission should be accepted (done|waiting), got {push_data['status']!r}"
        
        # Allowing two statuses would let this pass on a string match alone, so the
        # success has to be a real one: a degraded stage fills in `error`.
        assert push_data["error"] is None, \
            f"Submission reported {push_data['status']!r} but carried an error: {push_data['error']!r}"
        
        # TODO count should have increased (wait a moment for processing)
        await asyncio.sleep(1)
        
        new_response = await self.queue_helper.get_queue_status("todo")
        self.validator.assert_response_ok(new_response, 200)
        
        # Queue count might have changed
        if self.debug:
            print(f"[DEBUG] Job submitted: {test_message}")
    
    async def test_job_submission_validation(self):
        """Test job submission input validation."""
        # Both checks below used to sit in a try whose `except Exception: pass`
        # caught the assertion itself, so neither could fail. A push that raised,
        # or answered 500, read as a pass.
        
        # An empty question is REFUSED, and now it is refused for a stated reason:
        # AskRequest declares question with min_length=1, so the v2 door rejects it
        # at validation with 422 before any routing happens. The old assertion here
        # accepted `in [200, 400]` — both answers to the question it was asking —
        # which is why it could not have caught this change either way.
        response = await self.queue_helper.push_job("")
        assert response.status_code == 422, \
            f"An empty question should be refused with 422, got {response.status_code}"
        
        # A long-but-legal question is ACCEPTED. 1000 chars sits well inside the
        # door's declared 4000-char ceiling, so this is the accepted side of the
        # same boundary the empty case tests from below.
        long_message = "x" * 1000
        response = await self.queue_helper.push_job(long_message)
        assert response.status_code == 200, \
            f"A 1000-char question is within the 4000 limit and should be accepted, got {response.status_code}"
        
        # Test job with special characters
        # TODO: Re-enable when Kagi API is stable — submits to live queue which routes to Kagi FastGPT
        # special_message = "Test job with special chars: !@#$%^&*(){}[]|\\:;\"'<>,.?/~`"
        # response = await self.queue_helper.push_job( special_message )
        # self.validator.assert_response_ok( response, 200 )
    
    async def test_queue_websocket_events(self):
        """Test queue-related WebSocket events."""
        # Connect to queue WebSocket
        websocket = await self.client.websocket_connect(
            "/ws/queue/{session_id}",
            subscribed_events=["queue_todo_update", "queue_running_update",
                             "queue_done_update", "tts_job_request",
                             "auth_success", "sys_ping"]
        )
        
        try:
            # Submit through the SUBMIT door, not `ask`, and the reason is the whole
            # point of this test. An agentic command is QUEUED and comes straight
            # back status='waiting', which leaves the todo/running transitions on
            # the wire for the listener above to see. A conversational question
            # through `ask` holds the caller for the agent's entire span, so by the
            # time it returns every event this test exists to observe has already
            # been and gone.
            #
            # `claude code` is the command chosen deliberately: it is user-initiable,
            # it takes one ordinary argument, and it rides the bounded Claude Code
            # path that the Max subscription already covers rather than metered API
            # spend. `test suite` also needs no arguments and is the tempting pick —
            # it is the wrong one, because a test-suite job submitted from inside a
            # test is a nested monopolizer that Gate B defers by design.
            push_response = await self.queue_helper.submit_job(
                "agent router go to claude code",
                { "prompt": "Reply with the single word: ack. Do not read or write any files." },
            )
            self.validator.assert_response_ok(push_response, 200)
            
            # A 200 is NOT enough here, and checking only that was a real defect in
            # the first draft of this test: an unknown command also answers 200,
            # because the flow degrades it to the receptionist rather than failing.
            # The test would then sit watching for queue events from a job that was
            # never built, and pass anyway because "no events" is tolerated below.
            # What this test needs is proof the submit actually QUEUED something.
            # `path` is the discriminator, and it took two wrong drafts to find that.
            # Checking only the 200 passed with a nonsense command. Checking status
            # and job_id ALSO passed, because a command the flow cannot build
            # degrades to the receptionist — which queues a conversational job and
            # so reports status 'waiting' WITH a job_id, identical on both fields.
            # Only `path` separates a real agentic build ('agent') from that
            # fallback ('receptionist'), measured on the live door rather than read.
            push_data = push_response.json()
            assert push_data["path"] == "agent", \
                f"The submit degraded to {push_data['path']!r} instead of building an agentic job — " \
                f"status {push_data['status']!r} looks the same either way, so it proves nothing alone"
            assert push_data["status"] == "waiting", \
                f"An agentic submit should queue and report 'waiting', got {push_data['status']!r}"
            assert push_data["job_id"], \
                "A queued agentic submit must carry the executor job_id"
            
            # Try to catch queue update events
            events_received = []
            timeout_start = time.time()
            
            while time.time() - timeout_start < 15.0:  # 15 second timeout
                try:
                    event = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    event_data = json.loads(event)
                    event_type = event_data.get("type")
                    
                    if event_type in ["queue_todo_update", "queue_running_update", 
                                    "queue_done_update", "tts_job_request"]:
                        events_received.append(event_type)
                        
                        if self.debug:
                            print(f"[QUEUE EVENT] {event_type}: {event_data}")
                        
                        # Validate event structure
                        if event_type.startswith("queue_"):
                            self.validator.assert_json_contains(event_data, ["value"])
                            assert isinstance(event_data["value"], int), \
                                "Queue update should have integer value"
                        elif event_type == "tts_job_request":
                            self.validator.assert_json_contains(event_data, ["text"])
                        
                        # If we get a completion event, we can stop
                        if event_type == "tts_job_request":
                            break
                            
                except asyncio.TimeoutError:
                    continue
            
            if self.debug:
                print(f"[DEBUG] Queue events received: {events_received}")
            
            # We might not receive events immediately in test environment.
            # That's OK — the important thing is the WebSocket connection works,
            # and the inner `except asyncio.TimeoutError: continue` above already
            # covers a quiet socket. There used to be an outer `except Exception:
            # pass` here too, which additionally swallowed the assert_response_ok
            # on the job push, the assert_json_contains on each event, and the
            # integer-value assertion — so a rejected push or a malformed queue
            # event could not fail this test.
            
        finally:
            await self.client.close_websocket(websocket)
    
    async def test_queue_state_monitoring(self):
        """Test monitoring queue states over time."""
        # Get initial state of all queues
        initial_states = {}
        queue_types = ["todo", "run", "done", "dead"]
        
        for queue_type in queue_types:
            response = await self.queue_helper.get_queue_status(queue_type)
            self.validator.assert_response_ok(response, 200)
            initial_states[queue_type] = response.json()
        
        if self.debug:
            print(f"[DEBUG] Initial queue states: {initial_states}")
        
        # TODO: Re-enable when Kagi API is stable — submits to live queue which routes to Kagi FastGPT
        # test_questions = [
        #     "What is 2 + 2?",
        #     "What time is it?",
        #     "What day is today?"
        # ]
        #
        # for question in test_questions:
        #     response = await self.queue_helper.push_job( question )
        #     self.validator.assert_response_ok( response, 200 )
        #
        # await asyncio.sleep( 2 )

        # Check final state
        final_states = {}
        for queue_type in queue_types:
            response = await self.queue_helper.get_queue_status(queue_type)
            self.validator.assert_response_ok(response, 200)
            final_states[queue_type] = response.json()
        
        if self.debug:
            print(f"[DEBUG] Final queue states: {final_states}")
        
        # Validate that states are consistent (numbers should be reasonable)
        for queue_type in queue_types:
            initial = initial_states[queue_type]
            final = final_states[queue_type]
            
            # Extract count values for comparison
            initial_count = initial if isinstance(initial, int) else initial.get("count", 0)
            final_count = final if isinstance(final, int) else final.get("count", 0)
            
            assert isinstance(initial_count, int), f"Initial count should be integer for {queue_type}"
            assert isinstance(final_count, int), f"Final count should be integer for {queue_type}"
            assert final_count >= 0, f"Queue count should not be negative for {queue_type}"
    
    async def test_queue_contents_access(self):
        """Test accessing queue contents if available."""
        queue_types = ["todo", "run", "done", "dead"]
        
        # The "queue contents might not be accessible" case this loop used to
        # tolerate with `except Exception: pass` is already handled explicitly by
        # the 404 branch below. The handler only added blindness: it swallowed the
        # assert_response_ok and both structural assertions, so a 500 response or a
        # malformed queue item could not fail this test.
        for queue_type in queue_types:
            response = await self.queue_helper.get_queue_contents(queue_type)
            
            # Queue contents endpoint might not exist
            if response.status_code == 404:
                if self.debug:
                    print(f"[DEBUG] Queue contents endpoint not found for {queue_type}")
                continue
            
            self.validator.assert_response_ok(response, 200)
            
            data = response.json()
            
            # Should return list or dict with queue items
            if isinstance(data, list):
                # List of queue items
                for item in data:
                    if isinstance(item, dict):
                        # Each item should have some basic structure
                        assert "id" in item or "message" in item or "text" in item, \
                            f"Queue item should have basic fields: {item}"
            elif isinstance(data, dict):
                # Dict with queue info
                if "items" in data:
                    assert isinstance(data["items"], list), \
                        "Queue items should be a list"
    
    async def test_job_completion_flow(self):
        """Test complete job lifecycle if possible."""
        # This test might not work in all environments since it depends on
        # actual job processing, but we can test the basic flow
        
        test_message = "What is 3 + 3?"
        
        # Submit job
        push_response = await self.queue_helper.push_job(test_message)
        self.validator.assert_response_ok(push_response, 200)
        
        # Monitor queue states over time to see if job moves through states
        states_over_time = []
        
        for check in range(5):  # Check 5 times over 10 seconds
            await asyncio.sleep(2)
            
            state_snapshot = {}
            for queue_type in ["todo", "run", "done"]:
                response = await self.queue_helper.get_queue_status(queue_type)
                if response.status_code == 200:
                    data = response.json()
                    count = data if isinstance(data, int) else data.get("count", 0)
                    state_snapshot[queue_type] = count
            
            states_over_time.append(state_snapshot)
            
            if self.debug:
                print(f"[DEBUG] Queue state check {check+1}: {state_snapshot}")
        
        # Validate that the states are reasonable
        for state in states_over_time:
            for queue_type, count in state.items():
                assert isinstance(count, int), f"Queue count should be integer: {queue_type}={count}"
                assert count >= 0, f"Queue count should not be negative: {queue_type}={count}"
        
        if self.debug:
            print(f"[DEBUG] Job completion flow monitoring completed")
    
    async def test_queue_authentication(self):
        """Test queue endpoint authentication requirements."""
        # Both blocks below had two faults at once. The `except Exception: pass`
        # swallowed the assertion, and `headers = {}` never produced an
        # unauthenticated request — LupinTestClient.http_request re-attaches the
        # bearer token whenever the caller supplies no Authorization key, and an
        # empty dict has none. So these sent fully authenticated requests, got
        # 200, and passed on the wrong branch of an assertion that accepted both
        # answers to the question it claimed to ask. They now genuinely send no
        # token and require the refusal.
        
        # Test without authentication
        response = await self.client.http_request(
            "GET",
            "/api/get-queue/todo",
            authenticate=False
        )
        assert response.status_code == 401, \
            f"Unauthenticated /api/get-queue/todo should be rejected with 401, got {response.status_code}"
        
        # Test job submission without auth
        response = await self.client.http_request(
            "POST",
            "/api/v2/ask",
            json={"question": "Test message", "websocket_id": self.client.session_id},
            authenticate=False
        )
        assert response.status_code == 401, \
            f"Unauthenticated /api/v2/ask should be rejected with 401, got {response.status_code}"
        
        # Test with authentication (normal case)
        response = await self.queue_helper.get_queue_status("todo")
        self.validator.assert_response_ok(response, 200)
    
    async def run_all_tests(self) -> bool:
        """Run all queue workflow smoke tests."""
        print_test_banner("Job Queue Workflow Smoke Tests")
        
        tests = [
            (self.test_queue_status_endpoints, "Queue status endpoints"),
            (self.test_job_submission, "Job submission"),
            (self.test_job_submission_validation, "Job submission validation"),
            (self.test_queue_websocket_events, "Queue WebSocket events"),
            (self.test_queue_state_monitoring, "Queue state monitoring"),
            (self.test_queue_contents_access, "Queue contents access"),
            (self.test_job_completion_flow, "Job completion flow"),
            (self.test_queue_authentication, "Queue authentication")
        ]
        
        passed = 0
        total = len(tests)
        
        for test_func, test_name in tests:
            if await run_test_with_error_handling(test_func, test_name):
                passed += 1
        
        print(f"\n{'='*60}")
        print(f"Queue Workflow Tests Summary: {passed}/{total} passed")
        print(f"{'='*60}")
        
        return passed == total


async def main():
    """Main test execution function."""
    # Check if we should run in debug mode
    debug = "--debug" in sys.argv
    
    print("⚙️ Job Queue Workflow Smoke Tests")
    print("=" * 50)
    print("Testing comprehensive job queue functionality...")
    print("")
    
    # Create test instance and run
    tests = QueueWorkflowSmokeTests(debug=debug)
    
    try:
        success = await tests.run_all_tests()
        
        if success:
            print("✅ All queue workflow tests passed!")
            return True
        else:
            print("❌ Some queue workflow tests failed!")
            return False
            
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)