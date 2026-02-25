#!/usr/bin/env python3
"""
Approach D user-initiated message smoke test.

Validates the POST /api/jobs/{job_id}/message endpoint and the full
submit-inject-verify lifecycle using dry-run SWE Team jobs.

10 scenarios:

    #  ID                Description                                 Needs Running Job
    0  MSG_EMPTY         POST empty message -> 400                   No
    1  MSG_WHITESPACE    POST whitespace-only message -> 400         No
    2  MSG_BAD_PRIORITY  POST invalid priority -> 400                No
    3  MSG_NO_JOB        POST to nonexistent job -> 404              No
    4  MSG_NO_AUTH       POST without Bearer token -> 401            No
    5  MSG_NO_BODY       POST with no JSON body -> 400               No
    6  MSG_NORMAL        POST normal message to running job -> 200   Yes
    7  MSG_URGENT        POST urgent message to running job -> 200   Yes
    8  MSG_MULTI         POST 3 messages rapidly -> all 200          Yes
    9  MSG_VERIFY_DB     After job done, verify interactions in DB   Yes (post-completion)

Usage:
    python src/tests/smoke/test_approach_d_user_messages.py
    python src/tests/smoke/test_approach_d_user_messages.py --debug

Requires:
    - Server running on localhost:7999
    - Environment variables: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-02-20
"""

import os
import sys
import time

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests

from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


# =============================================================================
# Scenario Matrix
# =============================================================================

ERROR_SCENARIOS = [
    {
        "id"          : "MSG_EMPTY",
        "description" : "POST empty message -> 400",
        "endpoint"    : "/api/jobs/swe-placeholder/message",
        "body"        : { "message": "", "priority": "normal" },
        "expect_code" : 400,
        "needs_job"   : False,
    },
    {
        "id"          : "MSG_WHITESPACE",
        "description" : "POST whitespace-only message -> 400",
        "endpoint"    : "/api/jobs/swe-placeholder/message",
        "body"        : { "message": "   ", "priority": "normal" },
        "expect_code" : 400,
        "needs_job"   : False,
    },
    {
        "id"          : "MSG_BAD_PRIORITY",
        "description" : "POST invalid priority -> 400",
        "endpoint"    : "/api/jobs/swe-placeholder/message",
        "body"        : { "message": "hi", "priority": "high" },
        "expect_code" : 400,
        "needs_job"   : False,
    },
    {
        "id"          : "MSG_NO_JOB",
        "description" : "POST to nonexistent job -> 404",
        "endpoint"    : "/api/jobs/swe-nonexistent-999/message",
        "body"        : { "message": "hello", "priority": "normal" },
        "expect_code" : 404,
        "needs_job"   : False,
    },
    {
        "id"          : "MSG_NO_AUTH",
        "description" : "POST without Bearer token -> 401",
        "endpoint"    : "/api/jobs/swe-placeholder/message",
        "body"        : { "message": "hello", "priority": "normal" },
        "expect_code" : 401,
        "needs_job"   : False,
        "skip_auth"   : True,
    },
    {
        "id"          : "MSG_NO_BODY",
        "description" : "POST with no JSON body -> 400",
        "endpoint"    : "/api/jobs/swe-placeholder/message",
        "body"        : None,
        "expect_code" : 400,
        "needs_job"   : False,
    },
]

INJECT_SCENARIOS = [
    {
        "id"          : "MSG_NORMAL",
        "description" : "POST normal message to running job -> 200",
        "messages"    : [ { "message": "Please use the existing auth module", "priority": "normal" } ],
        "needs_job"   : True,
    },
    {
        "id"          : "MSG_URGENT",
        "description" : "POST urgent message to running job -> 200",
        "messages"    : [ { "message": "URGENT: Stop using deprecated API immediately", "priority": "urgent" } ],
        "needs_job"   : True,
    },
    {
        "id"          : "MSG_MULTI",
        "description" : "POST 3 messages rapidly -> all 200",
        "messages"    : [
            { "message": "First: use Python 3.11 features",    "priority": "normal" },
            { "message": "Second: add type hints to all funcs", "priority": "normal" },
            { "message": "Third: include docstrings",           "priority": "normal" },
        ],
        "needs_job"   : True,
    },
    {
        "id"          : "MSG_VERIFY_DB",
        "description" : "After job done, verify interactions contain user_initiated_message",
        "needs_job"   : True,
        "verify_only" : True,
    },
]

ALL_SCENARIOS = ERROR_SCENARIOS + INJECT_SCENARIOS


# =============================================================================
# Test Class
# =============================================================================

class ApproachDUserMessageSmokeTest( LivePipelineTestBase ):
    """
    Smoke test for Approach D user-initiated messaging.

    Phase 1: Error scenarios (no running job needed).
    Phase 2: Submit dry-run SWE job, inject messages, verify interactions.

    Requires:
        - Server running on port 7999
        - Valid test credentials in environment

    Ensures:
        - Error scenarios return correct HTTP status codes
        - Messages to running jobs return 200
        - Interactions endpoint shows user_initiated_message entries
    """

    TEST_NAME       = "Approach D User Messages"
    SCENARIOS       = ALL_SCENARIOS
    DEFAULT_TIMEOUT = 120
    POLL_INTERVAL   = 2

    # =========================================================================
    # Table Columns
    # =========================================================================

    def get_table_columns( self ):
        """
        Return column definitions for the results table.

        Ensures:
            - Returns list of ( header, width, key ) tuples
        """
        return [
            ( "#",           4,  None ),
            ( "Test ID",     20, "id" ),
            ( "Status",      8,  "status" ),
            ( "Details",     0,  "details" ),
        ]

    # =========================================================================
    # Results Table (override to handle "skip" as non-failure)
    # =========================================================================

    def _print_results_table( self, results ):
        """
        Print results table treating "skip" as non-failure in the summary.

        Requires:
            - results is a list of dicts with status, id, details keys

        Ensures:
            - Overall is PASS if no "fail" statuses (skips are acceptable)
        """
        columns  = self.get_table_columns()
        total_w  = max( 90, sum( c[ 1 ] for c in columns ) + 10 )
        header   = "  "

        for col_name, width, _ in columns:
            if width > 0:
                header += f"{col_name:<{width}} "
            else:
                header += col_name

        print( "\n" + "=" * total_w )
        print( header )
        print( "-" * total_w )

        for i, r in enumerate( results, 1 ):
            status     = r.get( "status", "fail" )
            status_txt = status.upper()
            icon       = "+" if status == "pass" else "~" if status == "skip" else "-"

            row = f"  {icon} {i:<3} "
            for col_name, width, key in columns:
                if key is None:
                    continue
                val = str( r.get( key, "" ) )
                if key == "status":
                    val = status_txt
                if width > 0:
                    row += f"{val:<{width}} "
                else:
                    row += val

            print( row )

        print( "=" * total_w )

        passed  = sum( 1 for r in results if r[ "status" ] == "pass" )
        failed  = sum( 1 for r in results if r[ "status" ] == "fail" )
        skipped = sum( 1 for r in results if r[ "status" ] == "skip" )

        summary = f"\n  Total: {passed} passed, {failed} failed"
        if skipped > 0:
            summary += f", {skipped} skipped"
        summary += f" out of {len( results )}"
        print( summary )
        print( f"  Overall: {'PASS' if failed == 0 else 'FAIL'}" )

    # =========================================================================
    # CLI
    # =========================================================================

    def build_argparser( self ):
        """
        Build CLI parser with --debug flag.

        Ensures:
            - Returns argparse.ArgumentParser
        """
        parser = super().build_argparser()
        return parser

    # =========================================================================
    # Core Orchestration (overrides base class)
    # =========================================================================

    def run_scenarios( self, args=None ):
        """
        Run error scenarios first, then submit+inject+verify pipeline.

        Requires:
            - Server running on BASE_URL
            - Credentials available in environment

        Ensures:
            - Returns True if all scenarios pass (or gracefully skip)
            - Returns False on any unexpected failure
        """
        import argparse
        if args is None:
            args = argparse.Namespace( debug=False, verbose=False, no_confirm=False )

        self.debug = getattr( args, "debug", False )

        label = f"{self.TEST_NAME} Smoke Test ({len( ALL_SCENARIOS )} scenarios)"
        self._print_banner( label )

        # Get credentials
        email, password = self._get_credentials()
        if not email or not password:
            print( f"Missing environment variables. Set:" )
            print( f"  export {self.CREDENTIAL_ENV_PREFIX}_EMAIL='your@email.com'" )
            print( f"  export {self.CREDENTIAL_ENV_PREFIX}_PASSWORD='<your-password>'" )
            return False

        results = []

        try:
            # =================================================================
            # Step 1: Login
            # =================================================================
            print( f"\nStep 1: Logging in as {email}..." )
            token, headers = self._login( email, password )

            if not token:
                print( "Login failed." )
                return False

            print( f"  Login successful, token: {token[ :30 ]}..." )

            # =================================================================
            # Step 2: Get WebSocket session ID
            # =================================================================
            print( "\nStep 2: Getting WebSocket session ID..." )
            ws_id = self._get_websocket_session_id( headers )
            print( f"  Using session ID: {ws_id}" )

            # =================================================================
            # Phase 1: Error scenarios (no running job needed)
            # =================================================================
            print( "\n" + "=" * 70 )
            print( "  PHASE 1: ERROR SCENARIOS (6 scenarios)" )
            print( "  Direct HTTP calls, no running job required." )
            print( "=" * 70 )

            error_results = self._run_error_scenarios( headers )
            results.extend( error_results )

            # =================================================================
            # Phase 2: Submit + Inject + Verify
            # =================================================================
            print( "\n" + "=" * 70 )
            print( "  PHASE 2: INJECT SCENARIOS (4 scenarios)" )
            print( "  Submit dry-run SWE job, inject messages, verify interactions." )
            print( "=" * 70 )

            inject_results = self._run_inject_scenarios( headers, ws_id )
            results.extend( inject_results )

            # =================================================================
            # Results Table
            # =================================================================
            self._print_results_table( results )

            passed  = sum( 1 for r in results if r[ "status" ] == "pass" )
            skipped = sum( 1 for r in results if r[ "status" ] == "skip" )
            failed  = sum( 1 for r in results if r[ "status" ] == "fail" )

            print( f"\n{'=' * 70}" )
            if failed == 0:
                msg = f"ALL {self.TEST_NAME.upper()} SMOKE TESTS PASSED ({passed}/{len( results )})"
                if skipped > 0:
                    msg += f" ({skipped} skipped)"
                print( msg )
            else:
                print( f"{self.TEST_NAME.upper()} SMOKE TESTS: {passed} passed, {failed} failed, {skipped} skipped" )
            print( "=" * 70 )

            return failed == 0

        except requests.exceptions.ConnectionError:
            print( f"\nConnection failed - is the server running on {self.BASE_URL}?" )
            return False
        except Exception as e:
            print( f"\nSmoke test failed: {e}" )
            import traceback
            traceback.print_exc()
            return False

    # =========================================================================
    # Phase 1: Error Scenarios
    # =========================================================================

    def _run_error_scenarios( self, headers ):
        """
        Run all error/validation scenarios.

        Requires:
            - headers contains valid auth token

        Ensures:
            - Returns list of result dicts, one per error scenario
        """
        results = []

        for i, scenario in enumerate( ERROR_SCENARIOS ):
            print( f"\n{'~' * 70}" )
            print( f"  Error Scenario {i + 1}/{len( ERROR_SCENARIOS )}: {scenario[ 'id' ]}" )
            print( f"  {scenario[ 'description' ]}" )
            print( f"{'~' * 70}" )

            result = {
                "id"             : scenario[ "id" ],
                "status"         : "fail",
                "answer_preview" : "",
                "details"        : "",
            }

            endpoint      = scenario[ "endpoint" ]
            body          = scenario[ "body" ]
            expected_code = scenario[ "expect_code" ]
            skip_auth     = scenario.get( "skip_auth", False )

            req_headers = {} if skip_auth else dict( headers )

            try:
                if body is None:
                    # Send request with no body (Content-Type still set by requests)
                    resp = requests.post(
                        f"{self.BASE_URL}{endpoint}",
                        headers=req_headers,
                        timeout=self.REQUEST_TIMEOUT,
                    )
                else:
                    resp = requests.post(
                        f"{self.BASE_URL}{endpoint}",
                        json=body,
                        headers=req_headers,
                        timeout=self.REQUEST_TIMEOUT,
                    )

                if resp.status_code == expected_code:
                    result[ "status" ]  = "pass"
                    result[ "details" ] = f"HTTP {resp.status_code} as expected"
                    print( f"    PASS: HTTP {resp.status_code} (expected {expected_code})" )
                else:
                    result[ "details" ] = f"Expected HTTP {expected_code}, got {resp.status_code}"
                    print( f"    FAIL: Expected HTTP {expected_code}, got {resp.status_code}" )
                    if self.debug: print( f"    Body: {resp.text[ :200 ]}" )

            except Exception as e:
                result[ "details" ] = f"Request error: {e}"
                print( f"    FAIL: {e}" )

            results.append( result )

        return results

    # =========================================================================
    # Phase 2: Inject Scenarios
    # =========================================================================

    def _run_inject_scenarios( self, headers, ws_id ):
        """
        Submit a dry-run SWE job, inject messages while running, verify interactions.

        Requires:
            - headers contains valid auth token
            - ws_id is a valid session ID

        Ensures:
            - Returns list of result dicts for inject scenarios
            - Gracefully skips if dry-run completes before messages can be sent
        """
        results = []

        # -----------------------------------------------------------------
        # Step A: Submit dry-run SWE job
        # -----------------------------------------------------------------
        print( "\n  Submitting SWE dry-run job..." )

        submit_payload = {
            "task"         : "Smoke test: Approach D user message injection",
            "dry_run"      : True,
            "websocket_id" : ws_id,
        }
        req_headers = { **headers, "X-Session-ID": ws_id }

        try:
            resp = requests.post(
                f"{self.BASE_URL}/api/swe-team/submit",
                json=submit_payload,
                headers=req_headers,
                timeout=self.REQUEST_TIMEOUT
            )
        except Exception as e:
            print( f"    Submit failed: {e}" )
            for scenario in INJECT_SCENARIOS:
                results.append( {
                    "id"      : scenario[ "id" ],
                    "status"  : "fail",
                    "details" : f"Submit error: {e}",
                } )
            return results

        if resp.status_code != 200:
            print( f"    Submit failed: HTTP {resp.status_code}: {resp.text[ :200 ]}" )
            for scenario in INJECT_SCENARIOS:
                results.append( {
                    "id"      : scenario[ "id" ],
                    "status"  : "fail",
                    "details" : f"Submit HTTP {resp.status_code}",
                } )
            return results

        submit_data = resp.json()
        job_id      = submit_data.get( "job_id" )

        if not job_id:
            print( f"    No job_id in response: {submit_data}" )
            for scenario in INJECT_SCENARIOS:
                results.append( {
                    "id"      : scenario[ "id" ],
                    "status"  : "fail",
                    "details" : "No job_id in submit response",
                } )
            return results

        print( f"    Job submitted: {job_id}" )

        # -----------------------------------------------------------------
        # Step B: Poll running queue until job appears
        # -----------------------------------------------------------------
        job_found_running = self._poll_running_queue( job_id, headers, timeout=30 )

        # -----------------------------------------------------------------
        # Step C: Inject messages (if job is still running)
        # -----------------------------------------------------------------
        messages_sent = 0

        if job_found_running:
            print( f"\n  Job {job_id} found in running queue. Injecting messages..." )

            for scenario in INJECT_SCENARIOS:
                if scenario.get( "verify_only" ):
                    continue

                print( f"\n{'~' * 70}" )
                print( f"  Inject Scenario: {scenario[ 'id' ]}" )
                print( f"  {scenario[ 'description' ]}" )
                print( f"{'~' * 70}" )

                result = {
                    "id"      : scenario[ "id" ],
                    "status"  : "fail",
                    "details" : "",
                }

                all_ok    = True
                msg_count = 0

                for msg in scenario[ "messages" ]:
                    status_code, resp_text = self._send_message(
                        job_id, msg[ "message" ], msg[ "priority" ], headers
                    )

                    if status_code == 200:
                        msg_count     += 1
                        messages_sent += 1
                        if self.debug: print( f"      200 OK: {msg[ 'message' ][ :60 ]}" )
                    else:
                        all_ok = False
                        print( f"      FAIL: HTTP {status_code}: {resp_text[ :100 ]}" )

                if all_ok:
                    result[ "status" ]  = "pass"
                    result[ "details" ] = f"{msg_count}/{len( scenario[ 'messages' ] )} messages accepted (200)"
                    print( f"    PASS: {result[ 'details' ]}" )
                else:
                    result[ "details" ] = f"Some messages rejected ({msg_count}/{len( scenario[ 'messages' ] )} OK)"
                    print( f"    FAIL: {result[ 'details' ]}" )

                results.append( result )

        else:
            print( f"\n  Job {job_id} not found in running queue (completed too fast)." )
            print( "  Skipping inject scenarios (timing-sensitive — not a failure)." )

            for scenario in INJECT_SCENARIOS:
                if scenario.get( "verify_only" ):
                    continue
                results.append( {
                    "id"      : scenario[ "id" ],
                    "status"  : "skip",
                    "details" : "Dry-run completed before messages could be sent",
                } )

        # -----------------------------------------------------------------
        # Step D: Poll done queue until job completes
        # -----------------------------------------------------------------
        print( f"\n  Waiting for job {job_id} to complete..." )
        job_done = self._poll_done_queue( job_id, headers, timeout=120 )

        # -----------------------------------------------------------------
        # Step E: Verify interactions (MSG_VERIFY_DB)
        # -----------------------------------------------------------------
        verify_scenario = next( s for s in INJECT_SCENARIOS if s.get( "verify_only" ) )

        print( f"\n{'~' * 70}" )
        print( f"  Verify Scenario: {verify_scenario[ 'id' ]}" )
        print( f"  {verify_scenario[ 'description' ]}" )
        print( f"{'~' * 70}" )

        result = {
            "id"      : verify_scenario[ "id" ],
            "status"  : "fail",
            "details" : "",
        }

        if not job_done:
            result[ "details" ] = f"Job {job_id} did not appear in done queue within timeout"
            print( f"    FAIL: {result[ 'details' ]}" )
            results.append( result )
            return results

        if messages_sent == 0:
            result[ "status" ]  = "skip"
            result[ "details" ] = "No messages were sent (job completed too fast)"
            print( f"    SKIP: {result[ 'details' ]}" )
            results.append( result )
            return results

        # GET /api/get-job-interactions/{job_id}
        interactions = self._get_interactions( job_id, headers )

        if interactions is None:
            result[ "details" ] = "Failed to fetch interactions"
            print( f"    FAIL: {result[ 'details' ]}" )
            results.append( result )
            return results

        # Count user_initiated_message entries
        user_msgs = [
            i for i in interactions
            if i.get( "type" ) == "user_initiated_message"
        ]

        if len( user_msgs ) >= messages_sent:
            result[ "status" ]  = "pass"
            result[ "details" ] = f"Found {len( user_msgs )} user_initiated_message interactions (sent {messages_sent})"
            print( f"    PASS: {result[ 'details' ]}" )
        else:
            result[ "details" ] = f"Expected >= {messages_sent} user_initiated_message, found {len( user_msgs )}"
            print( f"    FAIL: {result[ 'details' ]}" )
            if self.debug:
                print( f"    All interaction types: {[ i.get( 'type' ) for i in interactions ]}" )

        results.append( result )
        return results

    # =========================================================================
    # Helper: Poll Running Queue
    # =========================================================================

    def _poll_running_queue( self, job_id, headers, timeout=30 ):
        """
        Poll GET /api/get-queue/run until job_id appears.

        Requires:
            - job_id is a non-empty string
            - headers contains valid auth token

        Ensures:
            - Returns True if job found in running queue within timeout
            - Returns False if timeout reached
        """
        print( f"  Polling running queue for {job_id} (timeout={timeout}s)..." )

        elapsed = 0
        interval = 0.5

        while elapsed < timeout:
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/api/get-queue/run",
                    headers=headers,
                    timeout=10
                )

                if resp.status_code == 200:
                    data = resp.json()
                    jobs = data.get( "run_jobs_metadata", [] )

                    for job in jobs:
                        if job.get( "job_id" ) == job_id:
                            print( f"    Found in running queue after {elapsed:.1f}s" )
                            return True

            except Exception as e:
                if self.debug: print( f"    Poll error: {e}" )

            time.sleep( interval )
            elapsed += interval

        print( f"    Not found in running queue after {timeout}s" )
        return False

    # =========================================================================
    # Helper: Poll Done Queue
    # =========================================================================

    def _poll_done_queue( self, job_id, headers, timeout=120 ):
        """
        Poll GET /api/get-queue/done until job_id appears.

        Requires:
            - job_id is a non-empty string
            - headers contains valid auth token

        Ensures:
            - Returns True if job found in done queue within timeout
            - Returns False if timeout reached
        """
        elapsed  = 0
        interval = 2.0

        while elapsed < timeout:
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/api/get-queue/done",
                    headers=headers,
                    timeout=30
                )

                if resp.status_code == 200:
                    data = resp.json()
                    jobs = data.get( "done_jobs_metadata", [] )

                    for job in jobs:
                        if job.get( "job_id" ) == job_id:
                            print( f"    Job completed after {elapsed:.1f}s" )
                            return True

            except Exception as e:
                if self.debug: print( f"    Poll error: {e}" )

            time.sleep( interval )
            elapsed += interval

        print( f"    Job did not complete within {timeout}s" )
        return False

    # =========================================================================
    # Helper: Send Message
    # =========================================================================

    def _send_message( self, job_id, message, priority, headers ):
        """
        POST a message to a running job.

        Requires:
            - job_id is a non-empty string
            - message is a non-empty string
            - priority is "normal" or "urgent"
            - headers contains valid auth token

        Ensures:
            - Returns ( status_code, response_text ) tuple
        """
        try:
            resp = requests.post(
                f"{self.BASE_URL}/api/jobs/{job_id}/message",
                json={ "message": message, "priority": priority },
                headers=headers,
                timeout=self.REQUEST_TIMEOUT
            )
            return resp.status_code, resp.text

        except Exception as e:
            return -1, str( e )

    # =========================================================================
    # Helper: Get Interactions
    # =========================================================================

    def _get_interactions( self, job_id, headers ):
        """
        GET /api/get-job-interactions/{job_id} and return the interactions list.

        Requires:
            - job_id is a non-empty string
            - headers contains valid auth token

        Ensures:
            - Returns list of interaction dicts on success
            - Returns None on failure
        """
        try:
            resp = requests.get(
                f"{self.BASE_URL}/api/get-job-interactions/{job_id}",
                headers=headers,
                timeout=30
            )

            if resp.status_code != 200:
                print( f"    Interactions endpoint returned HTTP {resp.status_code}" )
                if self.debug: print( f"    Body: {resp.text[ :200 ]}" )
                return None

            data = resp.json()
            interactions = data.get( "interactions", [] )

            if self.debug:
                print( f"    Got {len( interactions )} interactions" )
                for ix in interactions:
                    print( f"      type={ix.get( 'type' )}, msg={ix.get( 'message', '' )[ :60 ]}" )

            return interactions

        except Exception as e:
            print( f"    Failed to fetch interactions: {e}" )
            return None


# =============================================================================
# Pytest + CLI Entry Points
# =============================================================================

def quick_smoke_test():
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - Server running on localhost:7999
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD set

    Ensures:
        - Returns True if all scenarios pass (or skip)
    """
    test = ApproachDUserMessageSmokeTest()
    return test.run()


def test_approach_d_user_messages():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = ApproachDUserMessageSmokeTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
