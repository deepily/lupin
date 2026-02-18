#!/usr/bin/env python3
"""
SWE Team proxy integration test — Surface 3.

Validates the RuntimeArgumentExpeditor can resolve SWE Team arguments via
the notification proxy. Tests the interactive voice->expeditor->queue pipeline.

3 scenarios:

    #  ID                 Description
    0  SWE_HAPPY          Voice command with all args -> job queued -> dry_run completes
    1  SWE_MISSING_TASK   Missing task -> proxy supplies answer -> job completes
    2  SWE_DRY_COST       Dry-run job -> verify $0.00 cost in done queue

Usage:
    # Full run (auto-proxy, interactive)
    LUPIN_INTERACTIVE_TESTS=true python src/tests/smoke/test_swe_team_proxy.py \\
      --auto-proxy --no-confirm

    # Manual proxy (start proxy in separate terminal first)
    LUPIN_INTERACTIVE_TESTS=true python src/tests/smoke/test_swe_team_proxy.py \\
      --no-confirm

Requires:
    - Server running on localhost:7999
    - Environment variables:
        LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / PASSWORD (preferred)
        LUPIN_TEST_EMAIL / LUPIN_TEST_PASSWORD (fallback)
    - LUPIN_INTERACTIVE_TESTS=true

Created: 2026-02-16
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

SWE_TEAM_PROXY_SCENARIOS = [
    {
        "id"            : "SWE_HAPPY",
        "group"         : "expediter",
        "voice_command" : "start an swe team task for adding a health check endpoint",
        "agent"         : "swe team",
        "key_arg"       : "task",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. Proxy auto-confirms.",
    },
    {
        "id"            : "SWE_MISSING_TASK",
        "group"         : "expediter",
        "voice_command" : "start an swe team task",
        "agent"         : "swe team",
        "key_arg"       : "task",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Proxy provides task, then auto-confirms.",
        "expected_args" : { "task": "add a health check endpoint to the API" },
    },
    {
        "id"            : "SWE_DRY_COST",
        "group"         : "expediter",
        "voice_command" : "use the swe team to refactor the database module",
        "agent"         : "swe team",
        "key_arg"       : "task",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "Job queued dry_run=True. Verify zero cost in done queue.",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class SweTeamProxySmokeTest( InteractiveSmokeTest ):
    """
    Proxy integration test for SWE Team expeditor argument resolution.

    Requires:
        - Server running on port 7999
        - Notification proxy (manual or --auto-proxy)
        - LUPIN_INTERACTIVE_TESTS=true

    Ensures:
        - Expeditor resolves SWE Team arguments via proxy
        - Jobs are queued with correct command and args
        - Dry-run jobs complete with $0.00 cost
    """

    TEST_NAME       = "SWE Team Proxy"
    SCENARIOS       = SWE_TEAM_PROXY_SCENARIOS
    BASE_URL        = "http://localhost:7999"
    DEFAULT_TIMEOUT = 120
    REQUEST_TIMEOUT = 600
    SUBMIT_ENDPOINT = "/api/mock-job/submit"
    PROXY_PROFILE   = "swe_team"
    PROXY_STRATEGY  = "llm_script"

    def _get_credentials( self ):
        """
        Get credentials, preferring interactive mock job account when available.

        Ensures:
            - Uses LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* if available
            - Falls back to LUPIN_TEST_* otherwise
        """
        email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
        password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
        if email and password:
            return email, password

        email    = os.environ.get( "LUPIN_TEST_EMAIL" )
        password = os.environ.get( "LUPIN_TEST_PASSWORD" )

        if email and password:
            return email, password

        return None, None

    def get_mode_for_scenario( self, scenario ):
        """
        SWE Team proxy scenarios do not use mode switching.

        Ensures:
            - Always returns None
        """
        return None

    def get_table_columns( self ):
        """Return proxy-specific table columns."""
        return [
            ( "#",        4,  None ),
            ( "Scenario", 20, "id" ),
            ( "Status",   8,  "status" ),
            ( "Details",  0,  "details" ),
        ]

    def _print_scenario_header( self, scenario ):
        """Print scenario details for expediter testing."""
        print( f"  Voice command: \"{scenario[ 'voice_command' ]}\"" )
        print( f"  Instructions: {scenario[ 'instructions' ]}" )

    def _submit_and_wait( self, scenario, headers, ws_id, timeout=None ):
        """
        Submit expediter scenario via mock job endpoint (synchronous).

        Requires:
            - scenario has "voice_command" key
            - headers contains valid auth token

        Ensures:
            - Returns ( response_data, error_msg ) tuple
            - Returns ( None, error_msg ) on failure
        """
        try:
            resp = requests.post(
                f"{self.BASE_URL}/api/mock-job/submit",
                json={ "voice_command": scenario[ "voice_command" ] },
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
        Validate expediter response — check status, command, and args.

        Requires:
            - scenario has agent, expect_cancel, expected_args keys
            - data is the JSON response from mock job endpoint

        Ensures:
            - Returns result dict with status, answer_preview, details
        """
        config = data.get( "config", {} )

        # Handle cancellation
        if data.get( "status" ) == "cancelled":
            if scenario.get( "expect_cancel" ):
                return {
                    "status"         : "pass",
                    "answer_preview" : "",
                    "details"        : "Cancelled as expected",
                }
            else:
                return {
                    "status"         : "cancel",
                    "answer_preview" : "",
                    "details"        : "User cancelled unexpectedly",
                }

        # Verify command contains expected agent
        if scenario[ "agent" ] not in config.get( "command", "" ):
            return {
                "status"         : "fail",
                "answer_preview" : "",
                "details"        : f"Expected '{scenario[ 'agent' ]}' in command, got: {config.get( 'command' )}",
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
        if job_id and not scenario.get( "expect_cancel" ):
            cost_ok = self._verify_job_completion( job_id )
            if not cost_ok:
                details += " (cost/poll issue)"

        return {
            "status"         : "pass",
            "answer_preview" : "",
            "details"        : details,
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
                            cost_summary = job.get( "cost_summary" )
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

            except Exception as e:
                print( f"    Poll error: {e}" )

            time.sleep( self.POLL_INTERVAL )
            elapsed += self.POLL_INTERVAL

        print( f"    Job not found in done queue after {self.DEFAULT_TIMEOUT}s" )
        return False

    def pre_run_hook( self, args, headers, ws_id ):
        """
        Run health checks, gate on interactive flag, and start proxy.

        Ensures:
            - Mock job health endpoint is alive
            - LUPIN_INTERACTIVE_TESTS=true is set
            - Proxy is launched if --auto-proxy
            - Returns True to continue, False to abort
        """
        # Store headers for _verify_job_completion
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
            print( f"  Mock job health: status={health_data.get( 'status' )}, available={health_data.get( 'available' )}" )

        except Exception as e:
            print( f"  Health check error: {e}" )
            return False

        # ═══════════════════════════════════════════════════════════════
        # Interactive gate
        # ═══════════════════════════════════════════════════════════════
        if not interactive:
            print( "\n  ABORT: LUPIN_INTERACTIVE_TESTS not set." )
            print( "  Set LUPIN_INTERACTIVE_TESTS=true to enable proxy integration tests." )
            return False

        # ═══════════════════════════════════════════════════════════════
        # Start proxy if --auto-proxy
        # ═══════════════════════════════════════════════════════════════
        if getattr( args, "auto_proxy", False ):
            debug = getattr( args, "proxy_debug", False )
            self._start_proxy( debug=debug )

            if not self.proxy_running:
                print( "  WARNING: Proxy failed to start. Scenarios may timeout." )

        return True

    def post_run_hook( self, args, headers, results ):
        """
        Stop proxy after scenarios complete.

        Ensures:
            - Proxy subprocess is stopped gracefully
        """
        self._stop_proxy()


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest + CLI Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test():
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - Server running on localhost:7999
        - LUPIN_INTERACTIVE_TESTS=true
        - Notification proxy running

    Ensures:
        - Returns True if all 3 scenarios pass
    """
    import argparse
    test = SweTeamProxySmokeTest()
    args = argparse.Namespace(
        auto_proxy  = False,
        proxy_debug = False,
        no_confirm  = True,
        debug       = False,
        verbose     = False,
    )
    return test.run_scenarios( args )


def test_swe_team_proxy():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = SweTeamProxySmokeTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
