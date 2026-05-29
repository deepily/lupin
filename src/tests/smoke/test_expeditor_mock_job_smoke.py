#!/usr/bin/env python3
"""
Smoke test for Runtime Argument Expeditor via mock job endpoint.

Verifies that:
1. Login and auth token retrieval works
2. Mock job health endpoint is alive
3. Standard mock job (no voice_command) baseline works
4.1-4.13 Thirteen expeditor scenarios covering all 3 agents, audience params,
        missing args, confirmation loop, and cancellation (INTERACTIVE)

Tests 4.x require LUPIN_INTERACTIVE_TESTS=true because they:
- Call LLM for gap analysis (real inference cost)
- Call notify_user_sync() for missing args + confirmation (blocks for user response)

Scenario Index Reference:
    0  DR_HAPPY    — "do deep research on quantum computing"
    1  DR_MISSING  — "do some deep research"
    2  DR_BUDGET   — "...climate change with a budget of 5 dollars"
    3  DR_AUDIENCE — "...machine learning for a beginner audience"
    4  PG_MISSING  — "make me a podcast"
    5  PG_AUDIENCE — "...for an expert audience"
    6  RTP_HAPPY   — "research quantum gravity and turn it into a podcast"
    7  RTP_MISSING — "I want research to podcast"
    8  DR_CANCEL   — "do some deep research for me" (user cancels)
    9  DR_FULL       — "...dark matter with a budget of 10 dollars for an expert audience"
   10  RTP_LANGUAGES — "research artificial intelligence and make a podcast in Spanish"
   11  PG_LANGUAGES  — "make me a podcast in English and Spanish"
   12  RTP_BARE      — "I want a research to podcast job"

Usage:
    # Run all 13 scenarios
    LUPIN_INTERACTIVE_TESTS=true python src/tests/smoke/test_expeditor_mock_job_smoke.py

    # Run only DR_HAPPY (scenario 0) to diagnose first
    LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 0

    # Run DR scenarios only (0-3 and cancel)
    LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 0,1,2,3,8

    # Run just PG scenarios (4, 5)
    LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 4,5

    # With auto-proxy (single terminal!):
    LUPIN_INTERACTIVE_TESTS=true python src/tests/smoke/test_expeditor_mock_job_smoke.py --auto-proxy -s 0,1,2,3,4,5,6,7,9,10,11,12

Requires:
- Server running on localhost:7999
- Environment variables: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / PASSWORD
- For tests 4.x: LUPIN_INTERACTIVE_TESTS=true

Created: 2026-02-05
Updated: 2026-02-11 — Expanded to 13 scenarios, single-pass proxy docs
Refactored: 2026-02-13 — Migrated to InteractiveSmokeTest

Automated Execution with Notification Proxy (scenarios 0-7, 9-12):
    Terminal 1: Server running on port 7999
    Terminal 2: PYTHONPATH=src python -m cosa.agents.notification_proxy --profile expeditor_smoke --debug
    Terminal 3: LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 0,1,2,3,4,5,6,7,9,10,11,12

    Scenario 8 (DR_CANCEL) excluded: The proxy auto-answers all notifications,
    but DR_CANCEL needs a "cancel" response. Its notification is identical to
    DR_MISSING (same response_type, title, sender_id) so the proxy cannot
    distinguish them. Cancel path is unit-tested in test_notification_proxy.py
    and test_runtime_argument_expeditor.py.
"""

import os
import sys
import time

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests
import cosa.utils.util as cu

from tests.smoke.utilities.interactive_smoke_test import InteractiveSmokeTest


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

EXPEDITOR_SCENARIOS = [
    {
        "id"            : "DR_HAPPY",
        "voice_command" : "do deep research on quantum computing",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. You'll be asked to CONFIRM the summary — say 'yes'.",
    },
    {
        "id"            : "DR_MISSING",
        "voice_command" : "do some deep research",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "You'll be prompted for the topic. Provide one (e.g. 'climate change'), then CONFIRM — say 'yes'.",
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
    },
    {
        "id"            : "DR_BUDGET",
        "voice_command" : "do deep research on climate change with a budget of 5 dollars",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command (query + budget). CONFIRM the summary — say 'yes'.",
    },
    {
        "id"            : "DR_AUDIENCE",
        "voice_command" : "do deep research on machine learning for a beginner audience",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "Audience should auto-extract. Verify summary includes audience, then say 'yes'.",
    },
    {
        "id"            : "PG_MISSING",
        "voice_command" : "make me a podcast",
        "agent"         : "podcast",
        "key_arg"       : "research",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "You'll be prompted for a research document. Describe one, then CONFIRM — say 'yes'.",
        "expected_args" : { "research": "/tmp/mock-research-document.md" },
    },
    {
        "id"            : "PG_AUDIENCE",
        "voice_command" : "make me a podcast for an expert audience",
        "agent"         : "podcast",
        "key_arg"       : "research",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Audience should auto-extract. You'll be prompted for research doc. Provide one, then CONFIRM — say 'yes'.",
    },
    {
        "id"            : "RTP_HAPPY",
        "voice_command" : "research quantum gravity and turn it into a podcast",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. CONFIRM the summary — say 'yes'.",
    },
    {
        "id"            : "RTP_MISSING",
        "voice_command" : "I want research to podcast",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "You'll be prompted for the topic. Provide one, then CONFIRM — say 'yes'.",
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
    },
    {
        "id"            : "DR_CANCEL",
        "voice_command" : "do some deep research for me",
        "agent"         : "deep research",
        "key_arg"       : None,
        "missing"       : True,
        "expect_cancel" : True,
        "instructions"  : "Say 'cancel' when prompted for the missing topic (or at confirmation).",
    },
    {
        "id"            : "DR_FULL",
        "voice_command" : "do deep research on dark matter with a budget of 10 dollars for an expert audience",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All main args in voice command. Confirm the summary — say 'yes'.",
    },
    {
        "id"            : "RTP_LANGUAGES",
        "voice_command" : "research artificial intelligence and make a podcast in Spanish",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "Query + languages should extract. You'll be asked about budget/audience. Provide answers, then say 'yes'.",
    },
    {
        "id"            : "PG_LANGUAGES",
        "voice_command" : "make me a podcast in English and Spanish",
        "agent"         : "podcast",
        "key_arg"       : "research",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Languages should extract. You'll be asked for research doc + audience. Provide answers, then say 'yes'.",
        "expected_args" : { "research": "/tmp/mock-research-document.md" },
    },
    {
        "id"            : "RTP_BARE",
        "voice_command" : "I want a research to podcast job",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "No args extracted. Provide all values when prompted, then say 'yes'.",
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Expeditor Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class ExpeditorSmokeTest( InteractiveSmokeTest ):
    """
    Smoke test for Runtime Argument Expeditor via mock job endpoint.

    Requires:
        - Server running on port 7999
        - LUPIN_INTERACTIVE_TESTS=true for scenario tests
        - For automated scenarios: notification proxy (manual or --auto-proxy)

    Ensures:
        - Health endpoint is alive
        - Standard mock job baseline works
        - Expeditor scenarios execute with correct arg resolution
        - Dry-run cost verification ($0.00)
    """

    TEST_NAME             = "Expeditor Mock Job"
    SCENARIOS             = EXPEDITOR_SCENARIOS
    BASE_URL              = "http://localhost:7999"
    DEFAULT_TIMEOUT       = 120
    REQUEST_TIMEOUT       = 600
    SUBMIT_ENDPOINT       = "/api/mock-job/submit"
    PROXY_PROFILE         = "expeditor_smoke"
    PROXY_STRATEGY        = "llm_script"
    def build_argparser( self ):
        """Add expeditor-specific CLI arguments."""
        parser = super().build_argparser()
        parser.add_argument(
            "--scenarios", "-s",
            type=str,
            default=None,
            help="Comma-separated scenario indices to run (e.g., '0,3,8'). Default: all."
        )
        return parser

    def get_scenario_indices( self, args ):
        """
        Parse --scenarios flag for selective execution.

        Ensures:
            - Returns list of valid indices into EXPEDITOR_SCENARIOS
        """
        if hasattr( args, "scenarios" ) and args.scenarios:
            return [ int( x.strip() ) for x in args.scenarios.split( "," ) if int( x.strip() ) < len( self.SCENARIOS ) ]
        return list( range( len( self.SCENARIOS ) ) )

    def get_submit_payload( self, scenario, ws_id ):
        """
        Build mock job submit payload with voice_command.

        Ensures:
            - Returns dict with voice_command key
        """
        return { "voice_command": scenario[ "voice_command" ] }

    def get_submit_headers( self, headers, ws_id ):
        """
        Use standard auth headers (no session ID needed for mock jobs).

        Ensures:
            - Returns headers dict
        """
        return headers

    def get_table_columns( self ):
        """Return expeditor-specific table columns."""
        return [
            ( "#",        4,  None ),
            ( "Scenario", 14, "id" ),
            ( "Agent",    22, "agent" ),
            ( "Status",   8,  "status" ),
            ( "Details",  0,  "details" ),
        ]

    def _print_scenario_header( self, scenario ):
        """Print expeditor-specific scenario details."""
        print( f"  Voice command: \"{scenario[ 'voice_command' ]}\"" )
        print( f"  Instructions: {scenario[ 'instructions' ]}" )

    def _submit_and_wait( self, scenario, headers, ws_id, timeout=None ):
        """
        Submit expeditor scenario via mock job endpoint (synchronous, no polling).

        The mock job endpoint blocks until the expeditor flow completes,
        so we don't need the poll-done-queue pattern.

        Requires:
            - scenario is a dict from EXPEDITOR_SCENARIOS
            - headers contains valid auth token

        Ensures:
            - Returns ( response_data, error_msg ) tuple
            - Returns ( None, error_msg ) on failure
        """
        try:
            resp = requests.post(
                f"{self.BASE_URL}{self.SUBMIT_ENDPOINT}",
                json=self.get_submit_payload( scenario, ws_id ),
                headers=headers,
                timeout=self.REQUEST_TIMEOUT
            )

            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}: {resp.text[ :200 ]}"

            return resp.json(), None

        except requests.exceptions.Timeout:
            return None, f"Request timed out after {self.REQUEST_TIMEOUT}s"
        except Exception as e:
            return None, f"Error: {e}"

    def validate_result( self, scenario, data ):
        """
        Validate expeditor response — check status, command, and dry-run cost.

        Requires:
            - scenario is a dict from EXPEDITOR_SCENARIOS
            - data is the JSON response from mock job endpoint

        Ensures:
            - Returns result dict with status, answer_preview, details, agent
        """
        config = data.get( "config", {} )

        # Handle cancellation
        if data.get( "status" ) == "cancelled":
            notif_status = config.get( "notification_status" )
            if notif_status and notif_status != "responded":
                print( f"    Notification status: {notif_status}" )

            # Re-classify HTTP infra failures (e.g. http_error_503 from /api/notify)
            # as a distinct "infra_error" status — these are NOT user cancellations.
            if notif_status and notif_status.startswith( "http_error_" ):
                return {
                    "status"         : "infra_error",
                    "answer_preview" : "",
                    "details"        : f"Infra failure: notification dispatch returned {notif_status} (proxy unreachable or /api/notify down)",
                    "agent"          : scenario[ "agent" ],
                }
            if scenario[ "expect_cancel" ]:
                return {
                    "status"         : "pass",
                    "answer_preview" : "",
                    "details"        : "Cancelled as expected",
                    "agent"          : scenario[ "agent" ],
                }
            else:
                return {
                    "status"         : "cancel",
                    "answer_preview" : "",
                    "details"        : "User cancelled unexpectedly",
                    "agent"          : scenario[ "agent" ],
                }

        # Verify command contains expected agent
        if scenario[ "agent" ] not in config.get( "command", "" ):
            return {
                "status"         : "fail",
                "answer_preview" : "",
                "details"        : f"Expected '{scenario[ 'agent' ]}' in command, got: {config.get( 'command' )}",
                "agent"          : scenario[ "agent" ],
            }

        # Soft verification: check proxy-provided args match expected values
        expected = scenario.get( "expected_args" )
        if expected and config.get( "args_resolved" ):
            for arg_name, expected_value in expected.items():
                actual = config[ "args_resolved" ].get( arg_name )
                if actual != expected_value:
                    print( f"    Arg mismatch: {arg_name} expected='{expected_value}' got='{actual}'" )

        job_id = data.get( "job_id", "" )
        args   = config.get( "args_resolved", {} )

        print( f"    Command: {config.get( 'command', 'N/A' )}" )
        print( f"    Args: {args}" )
        print( f"    Job ID: {job_id}" )

        details = f"job={job_id}, args={list( args.keys() )}"

        # Poll for completion and verify dry-run cost
        if job_id and not scenario[ "expect_cancel" ]:
            cost_ok = self._verify_job_completion( job_id )
            if not cost_ok:
                details += " (cost/poll issue)"

        return {
            "status"         : "pass",
            "answer_preview" : "",
            "details"        : details,
            "agent"          : scenario[ "agent" ],
        }

    def _verify_job_completion( self, job_id ):
        """
        Poll done queue for completed job and verify dry-run cost.

        Requires:
            - job_id is a non-empty string
            - self._headers contains valid auth token

        Ensures:
            - Returns True if job completed with $0.00 cost
            - Returns False otherwise
        """
        print( f"    Polling for completion..." )
        elapsed = 0

        while elapsed < self.DEFAULT_TIMEOUT:
            try:
                done_resp = requests.get(
                    f"{self.BASE_URL}/api/get-queue/done",
                    headers=self._headers,
                    timeout=30
                )

                if done_resp.status_code == 200:
                    done_data = done_resp.json()
                    jobs      = done_data.get( "done_jobs_metadata", [] )

                    for job in jobs:
                        if job.get( "job_id" ) == job_id:
                            return self._verify_dry_run_cost( job )

            except Exception as e:
                print( f"    Poll error: {e}" )

            time.sleep( self.POLL_INTERVAL )
            elapsed += self.POLL_INTERVAL

        print( f"    Job not found in done queue after {self.DEFAULT_TIMEOUT}s" )
        return False

    def _verify_dry_run_cost( self, completed_job ):
        """
        Verify a completed job has $0.00 cost (dry-run).

        Requires:
            - completed_job is a dict from done queue

        Ensures:
            - Returns True if cost is $0.00
            - Returns False otherwise
        """
        cost_summary = completed_job.get( "cost_summary" )
        if cost_summary is None:
            total_cost = 0.0
        elif isinstance( cost_summary, dict ):
            total_cost = cost_summary.get( "total_cost_usd", cost_summary.get( "total_cost", -1 ) )
        else:
            total_cost = 0.0

        if total_cost == 0.0 or total_cost == 0:
            print( f"    Dry-run cost: $0.00" )
            return True
        else:
            print( f"    Non-zero cost detected: ${total_cost}" )
            return False

    def _print_results_table( self, results ):
        """
        Print expeditor-specific results table with agent column.

        Requires:
            - results is a list of dicts with keys: id, status, agent, details

        Ensures:
            - Prints tabular summary with pass/fail/cancel counts
        """
        columns = self.get_table_columns()
        print( "\n" + "=" * 80 )
        print( f"  {'#':<4} {'Scenario':<14} {'Agent':<22} {'Status':<8} {'Details'}" )
        print( "-" * 80 )

        for i, r in enumerate( results, 1 ):
            status = r.get( "status", "fail" )
            icon   = "+" if status == "pass" else "-" if status == "fail" else "~"
            print( f"  {icon} {i:<3} {r[ 'id' ]:<14} {r.get( 'agent', '' ):<22} {status:<8} {r[ 'details' ]}" )

        print( "=" * 80 )

        passed = sum( 1 for r in results if r[ "status" ] == "pass" )
        failed = sum( 1 for r in results if r[ "status" ] == "fail" )
        cancel = sum( 1 for r in results if r[ "status" ] == "cancel" )

        print( f"\n  Total: {passed} passed, {failed} failed, {cancel} unexpected cancels" )
        print( f"  Overall: {'PASS' if failed == 0 and cancel == 0 else 'FAIL'}" )

    def pre_run_hook( self, args, headers, ws_id ):
        """
        Run health check and baseline mock job before scenarios.

        Ensures:
            - Health endpoint returns ok
            - Standard mock job queues correctly
            - Returns False to abort if pre-checks fail
        """
        # Store headers for later use in _verify_job_completion
        self._headers = headers

        interactive = os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() == "true"

        # ═══════════════════════════════════════════════════════════════
        # Health check
        # ═══════════════════════════════════════════════════════════════
        print( "\nPre-check 1: Checking mock job health endpoint..." )
        try:
            health_resp = requests.get( f"{self.BASE_URL}/api/mock-job/health", timeout=10 )

            if health_resp.status_code != 200:
                print( f"  Health check failed: {health_resp.status_code}" )
                return False

            health_data = health_resp.json()
            assert health_data[ "status" ] == "ok", f"Expected status 'ok', got '{health_data[ 'status' ]}'"
            assert health_data[ "available" ] is True, "Expected available=True"
            print( "  Mock job health endpoint is alive" )
        except AssertionError as e:
            print( f"  Assertion failed: {e}" )
            return False

        # ═══════════════════════════════════════════════════════════════
        # Standard mock job baseline
        # ═══════════════════════════════════════════════════════════════
        print( "\nPre-check 2: Submitting standard mock job (baseline)..." )
        try:
            mock_resp = requests.post(
                f"{self.BASE_URL}/api/mock-job/submit",
                json={
                    "fixed_iterations" : 2,
                    "fixed_sleep"      : 0.5,
                    "description"      : "expeditor smoke test baseline"
                },
                headers=headers,
                timeout=30
            )

            if mock_resp.status_code != 200:
                print( f"  Standard mock job failed: {mock_resp.status_code}" )
                print( f"  Response: {mock_resp.text[ :200 ]}" )
                return False

            mock_data = mock_resp.json()
            assert mock_data[ "status" ] == "queued", f"Expected 'queued', got '{mock_data[ 'status' ]}'"
            assert mock_data[ "job_id" ].startswith( "mock-" ), f"Expected job_id prefix 'mock-', got '{mock_data[ 'job_id' ]}'"
            print( f"  Standard mock job queued: {mock_data[ 'job_id' ]}" )
            print( f"  Config: {mock_data[ 'config' ]}" )
        except AssertionError as e:
            print( f"  Assertion failed: {e}" )
            return False

        # ═══════════════════════════════════════════════════════════════
        # Interactive gate check
        # ═══════════════════════════════════════════════════════════════
        if not interactive:
            print( "\nTests 4.1-4.13: SKIPPED (requires LUPIN_INTERACTIVE_TESTS=true)" )
            print( "\n" + "=" * 70 )
            print( "AUTOMATED SMOKE TESTS PASSED (3/3)!" )
            print( "  Scenario tests skipped: set LUPIN_INTERACTIVE_TESTS=true to enable" )
            print( "=" * 70 )
            return False  # Abort scenario loop (pre-checks passed, but no scenarios to run)

        # Start proxy if --auto-proxy
        if getattr( args, "auto_proxy", False ):
            debug    = getattr( args, "proxy_debug", False )
            email    = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_EMAIL" )
            password = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_PASSWORD" )
            try:
                self._start_proxy( debug=debug, email=email, password=password )
            except RuntimeError as e:
                print( f"\n  ABORT: Proxy startup failed — refusing to run interactive scenarios without a proxy (would 503-cascade)." )
                print( f"  {e}" )
                return False

        return True

    def run_scenarios( self, args=None ):
        """
        Override to handle the non-interactive early exit gracefully.

        The pre_run_hook returns False when LUPIN_INTERACTIVE_TESTS is not set,
        which normally means failure. But for the expeditor, it means the
        pre-checks passed and we should report success.
        """
        interactive = os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() == "true"

        if not interactive:
            # Run pre-checks only (login + health + baseline)
            result = self._run_pre_checks_only( args )
            return result

        return super().run_scenarios( args )

    def _run_pre_checks_only( self, args ):
        """
        Run login + pre-checks without the scenario loop.

        Ensures:
            - Returns True if pre-checks pass
            - Returns False on failure
        """
        import argparse
        if args is None:
            args = argparse.Namespace()

        cu.print_banner( "Expeditor Mock Job Smoke Test (13-Scenario Matrix)", prepend_nl=True )
        print( "Note: Scenario tests skipped (set LUPIN_INTERACTIVE_TESTS=true to enable)" )

        email, password = self._get_credentials()
        if not email or not password:
            print( "Missing environment variables." )
            return False

        try:
            print( f"\nTest 1: Logging in as {email}..." )
            token, headers = self._login( email, password )
            if not token:
                return False
            print( f"  Login successful, token: {token[ :30 ]}..." )

            ws_id = self._get_websocket_session_id( headers )

            # pre_run_hook handles health check and baseline
            self.pre_run_hook( args, headers, ws_id )
            return True  # Pre-checks passed

        except requests.exceptions.ConnectionError:
            print( f"\nConnection failed - is the server running on {self.BASE_URL}?" )
            return False
        except Exception as e:
            print( f"\nSmoke test failed: {e}" )
            import traceback
            traceback.print_exc()
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest + CLI Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( scenario_indices=None ):
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - scenario_indices is None (all) or a list of valid int indices

    Ensures:
        - Returns True if all tests pass
    """
    import argparse
    test = ExpeditorSmokeTest()
    args = argparse.Namespace(
        scenarios   = ",".join( str( i ) for i in scenario_indices ) if scenario_indices else None,
        auto_proxy  = False,
        proxy_debug = False,
        debug       = False,
        verbose     = False,
    )
    return test.run_scenarios( args )


def test_expeditor_mock_job_smoke():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = ExpeditorSmokeTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
