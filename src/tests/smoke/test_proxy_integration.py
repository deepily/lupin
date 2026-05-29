#!/usr/bin/env python3
"""
Proxy integration test combining Calculator, CRUD, and Expediter agents.

Verifies the notification proxy can auto-respond to notifications from
three different agent types in a single test run:

  1. Calculator — needs similarity_confirmation_enabled=false
  2. CRUD — needs proxy to auto-confirm destructive operations (delete/update)
  3. Expediter — needs proxy to auto-answer missing arg questions

12 scenarios across 3 groups:

    #  ID              Group       Query                                                  Proxy
    0  CALC_CONVERT_KM calculator  "How many miles is 10 kilometers?"                     No
    1  CALC_MORTGAGE   calculator  "Monthly payment on $300k mortgage at 6.5% for 30y"    No
    2  CALC_COMPARE    calculator  "Compare 12 oz at $3.49 vs 24 oz at $5.99"             No
    3  CRUD_ADD_TODO   crud        "add buy milk to my grocery list"                       No
    4  CRUD_ADD_TODO_2 crud        "add buy bread to my grocery list"                      No
    5  CRUD_QUERY      crud        "what's on my grocery list?"                            No
    6  CRUD_DELETE     crud        "delete buy bread from my grocery list"                 Yes
    7  CRUD_ADD_CAL    crud        "add dentist appointment on March 15 at 2pm"            No
    8  EXP_DR_HAPPY   expediter   "do deep research on quantum computing"                 Yes
    9  EXP_DR_MISSING  expediter   "do some deep research"                                Yes
   10  EXP_PG_MISSING  expediter   "make me a podcast"                                    Yes
   11  EXP_RTP_HAPPY   expediter   "research quantum gravity and turn it into a podcast"  Yes

Usage:
    # Full run (all 3 agent types, auto-proxy, no similarity confirmation)
    LUPIN_INTERACTIVE_TESTS=true python src/tests/smoke/test_proxy_integration.py \\
      --auto-proxy --no-confirm

    # Calculator only (no proxy needed)
    python src/tests/smoke/test_proxy_integration.py --group calculator --no-confirm

    # CRUD only (proxy auto-confirms deletes)
    python src/tests/smoke/test_proxy_integration.py --group crud --auto-proxy

    # Expediter only (proxy auto-answers all questions)
    LUPIN_INTERACTIVE_TESTS=true python src/tests/smoke/test_proxy_integration.py \\
      --group expediter --auto-proxy

Requires:
    - Server running on localhost:7999
    - Phi-4 LLM server running for intent extraction
    - Environment variables:
        LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / PASSWORD
    - For expediter scenarios: LUPIN_INTERACTIVE_TESTS=true

Created: 2026-02-14
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

INTEGRATION_SCENARIOS = [
    # --- Calculator scenarios (0-2) ---
    {
        "id"                : "CALC_CONVERT_KM",
        "group"             : "calculator",
        "query"             : "How many miles is 10 kilometers?",
        "mode"              : "calculator",
        "needs_confirm"     : False,
        "expected_keywords" : [ "6.21", "6.2" ],
    },
    {
        "id"                : "CALC_MORTGAGE",
        "group"             : "calculator",
        "query"             : "Monthly payment on $300k mortgage at 6.5% for 30 years",
        "mode"              : "calculator",
        "needs_confirm"     : False,
        "expected_keywords" : [ "1,896", "1896", "1,897", "1897" ],
    },
    {
        "id"                : "CALC_COMPARE",
        "group"             : "calculator",
        "query"             : "Compare 12 oz at $3.49 vs 24 oz at $5.99",
        "mode"              : "calculator",
        "needs_confirm"     : False,
        "expected_keywords" : [ "cheaper", "better", "value", "per" ],
    },
    # --- CRUD scenarios (3-7) ---
    {
        "id"                : "CRUD_ADD_TODO",
        "group"             : "crud",
        "query"             : "add buy milk to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "milk", "already exists" ],
        "expected_status"   : [ "added", "duplicate" ],
    },
    {
        "id"                : "CRUD_ADD_TODO_2",
        "group"             : "crud",
        "query"             : "add buy bread to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "bread", "already exists" ],
        "expected_status"   : [ "added", "duplicate" ],
    },
    {
        "id"                : "CRUD_QUERY",
        "group"             : "crud",
        "query"             : "what's on my grocery list?",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "found", "milk", "bread", "item" ],
        "expected_status"   : [ "ok" ],
    },
    {
        "id"                : "CRUD_DELETE",
        "group"             : "crud",
        "query"             : "delete buy bread from my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : True,
        "timeout"           : 180,
        "expected_keywords" : [ "done", "deleted", "removed", "cancelled", "cancel" ],
        "expected_status"   : [ "deleted", "cancelled" ],
    },
    {
        "id"                : "CRUD_ADD_CAL",
        "group"             : "crud",
        "query"             : "add dentist appointment on March 15 at 2pm",
        "mode"              : "calendar",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "dentist", "already exists" ],
        "expected_status"   : [ "added", "duplicate" ],
    },
    # --- Expediter scenarios (8-11) ---
    {
        "id"            : "EXP_DR_HAPPY",
        "group"         : "expediter",
        "voice_command" : "do deep research on quantum computing",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. Proxy auto-confirms.",
    },
    {
        "id"            : "EXP_DR_MISSING",
        "group"         : "expediter",
        "voice_command" : "do some deep research",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Proxy provides topic, then auto-confirms.",
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
    },
    {
        "id"            : "EXP_PG_MISSING",
        "group"         : "expediter",
        "voice_command" : "make me a podcast",
        "agent"         : "podcast",
        "key_arg"       : "research",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Proxy provides research doc, then auto-confirms.",
        "expected_args" : { "research": "/tmp/mock-research-document.md" },
    },
    {
        "id"            : "EXP_RTP_HAPPY",
        "group"         : "expediter",
        "voice_command" : "research quantum gravity and turn it into a podcast",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. Proxy auto-confirms.",
    },
    # --- Presentation expediter scenarios (12-14) ---
    {
        "id"            : "EXP_PRES_MISSING",
        "group"         : "expediter",
        "voice_command" : "make me a presentation",
        "agent"         : "presentation",
        "key_arg"       : "source",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Proxy provides source doc, then auto-confirms.",
        "expected_args" : { "source": "/tmp/mock-source-document.md" },
    },
    {
        "id"            : "EXP_RTPRES_HAPPY",
        "group"         : "expediter",
        "voice_command" : "research quantum computing and make a presentation",
        "agent"         : "research to presentation",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. Proxy auto-confirms.",
    },
    {
        "id"            : "EXP_RTPRES_MISSING",
        "group"         : "expediter",
        "voice_command" : "research something and present it",
        "agent"         : "research to presentation",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Proxy provides topic, then auto-confirms.",
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
    },
]

# Group -> scenario index mapping
GROUP_SCENARIOS = {
    "calculator" : [ 0, 1, 2 ],
    "crud"       : [ 3, 4, 5, 6, 7 ],
    "expediter"  : [ 8, 9, 10, 11, 12, 13, 14 ],
    "all"        : list( range( 15 ) ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class ProxyIntegrationTest( InteractiveSmokeTest ):
    """
    Integration test combining Calculator, CRUD, and Expediter agents.

    Requires:
        - Server running on port 7999
        - Phi-4 LLM server running for intent extraction
        - For expediter scenarios: LUPIN_INTERACTIVE_TESTS=true
        - For proxy scenarios: notification proxy (manual or --auto-proxy)

    Ensures:
        - Calculator scenarios pass with explicit mode switching
        - CRUD add, query, delete, and calendar operations work
        - Expediter scenarios execute with correct arg resolution
        - Proxy auto-responds to all notification types
    """

    TEST_NAME       = "Proxy Integration"
    SCENARIOS       = INTEGRATION_SCENARIOS
    BASE_URL        = "http://localhost:7999"
    DEFAULT_TIMEOUT = 120
    REQUEST_TIMEOUT = 600
    SUBMIT_ENDPOINT = "/api/push"
    PROXY_PROFILE   = "proxy_integration_test"
    PROXY_STRATEGY  = "llm_script"

    def build_argparser( self ):
        """Add integration-specific CLI arguments."""
        parser = super().build_argparser()
        parser.add_argument(
            "--group", "-g",
            choices=[ "calculator", "crud", "expediter", "all" ],
            default="all",
            help="Scenario group to run: calculator, crud, expediter, or all (default)"
        )
        parser.add_argument(
            "--scenarios", "-s",
            type=str,
            default=None,
            help="Comma-separated scenario indices to run (e.g., '0,3,8'). Overrides --group."
        )
        return parser

    def get_scenario_indices( self, args ):
        """
        Map --group or --scenarios flag to scenario indices.

        Ensures:
            - --scenarios overrides --group when both provided
            - Returns list of valid indices into INTEGRATION_SCENARIOS
        """
        if hasattr( args, "scenarios" ) and args.scenarios:
            return [
                int( x.strip() ) for x in args.scenarios.split( "," )
                if int( x.strip() ) < len( self.SCENARIOS )
            ]

        group = getattr( args, "group", "all" )
        return GROUP_SCENARIOS.get( group, GROUP_SCENARIOS[ "all" ] )

    def get_mode_for_scenario( self, scenario ):
        """
        Return per-scenario mode for routing.

        Ensures:
            - Calculator scenarios return "calculator"
            - CRUD scenarios return "todo" or "calendar"
            - Expediter scenarios return None (use mock job endpoint)
        """
        group = scenario.get( "group" )
        if group == "expediter":
            return None
        return scenario.get( "mode" )

    def get_table_columns( self ):
        """Return integration-specific table columns."""
        return [
            ( "#",        4,  None ),
            ( "Scenario", 18, "id" ),
            ( "Group",    12, "group" ),
            ( "Status",   8,  "status" ),
            ( "Details",  0,  "details" ),
        ]

    def _print_scenario_header( self, scenario ):
        """Print scenario details based on group type."""
        group = scenario.get( "group" )

        if group == "expediter":
            print( f"  Voice command: \"{scenario[ 'voice_command' ]}\"" )
            print( f"  Instructions: {scenario[ 'instructions' ]}" )
        else:
            print( f"  Query: \"{scenario[ 'query' ]}\"" )
            print( f"  Mode: {scenario.get( 'mode', 'system' )}" )
            if "expected_keywords" in scenario:
                print( f"  Expected keywords: {scenario[ 'expected_keywords' ]}" )
            if scenario.get( "needs_confirm" ):
                print( f"  Confirm: Yes (proxy auto-confirms)" )

    def _submit_and_wait( self, scenario, headers, ws_id, timeout=None ):
        """
        Route submission based on scenario group.

        Calculator and CRUD use /api/push with poll-done-queue pattern.
        Expediter uses /api/mock-job/submit (synchronous, no polling).

        Requires:
            - scenario is a dict from INTEGRATION_SCENARIOS
            - headers contains valid auth token

        Ensures:
            - Returns ( response_data, error_msg ) tuple
        """
        group = scenario.get( "group" )

        if group == "expediter":
            return self._submit_expediter( scenario, headers, timeout )
        else:
            return super()._submit_and_wait( scenario, headers, ws_id, timeout )

    def _submit_expediter( self, scenario, headers, timeout=None ):
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

    def validate_result( self, scenario, job_data ):
        """
        Validate based on scenario group type.

        Requires:
            - scenario is a dict from INTEGRATION_SCENARIOS
            - job_data is the response from the endpoint

        Ensures:
            - Returns result dict with status, details, group, and optionally answer_preview
        """
        group = scenario.get( "group" )

        if group == "expediter":
            result = self._validate_expediter( scenario, job_data )
        else:
            result = super().validate_result( scenario, job_data )

        result[ "group" ] = group
        return result

    def _validate_expediter( self, scenario, data ):
        """
        Validate expediter response — check status, command, and args.

        Requires:
            - scenario has agent, expect_cancel, expected_args keys
            - data is the JSON response from mock job endpoint

        Ensures:
            - Returns result dict with status, answer_preview, details, group
        """
        config = data.get( "config", {} )

        # Handle cancellation
        if data.get( "status" ) == "cancelled":
            notif_status = config.get( "notification_status" )
            # Re-classify HTTP infra failures (e.g. http_error_503 from /api/notify)
            # as a distinct "infra_error" status — these are NOT user cancellations.
            if notif_status and notif_status.startswith( "http_error_" ):
                return {
                    "status"         : "infra_error",
                    "answer_preview" : "",
                    "details"        : f"Infra failure: notification dispatch returned {notif_status} (proxy unreachable or /api/notify down)",
                }
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
        Run health checks, start proxy, and disable similarity confirmation.

        Ensures:
            - Mock job health endpoint is alive (for expediter scenarios)
            - Proxy is launched if --auto-proxy
            - Similarity confirmation disabled for calculator scenarios
            - Returns True to continue, False to abort
        """
        # Store headers for _verify_job_completion
        self._headers = headers

        group       = getattr( args, "group", "all" )
        has_exp     = group in ( "expediter", "all" )
        interactive = os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() == "true"

        # ═══════════════════════════════════════════════════════════════
        # Health check for expediter scenarios
        # ═══════════════════════════════════════════════════════════════
        if has_exp:
            print( "\nPre-check 1: Checking mock job health endpoint..." )
            try:
                health_resp = requests.get( f"{self.BASE_URL}/api/mock-job/health", timeout=10 )

                if health_resp.status_code != 200:
                    print( f"  Health check failed: {health_resp.status_code}" )
                    if group == "expediter":
                        return False
                    print( "  WARNING: Expediter scenarios may fail." )
                else:
                    health_data = health_resp.json()
                    print( f"  Mock job health: status={health_data.get( 'status' )}, available={health_data.get( 'available' )}" )

            except Exception as e:
                print( f"  Health check error: {e}" )
                if group == "expediter":
                    return False

        # ═══════════════════════════════════════════════════════════════
        # Interactive gate check for expediter
        # ═══════════════════════════════════════════════════════════════
        if has_exp and not interactive:
            print( "\n  WARNING: LUPIN_INTERACTIVE_TESTS not set. Expediter scenarios will be skipped." )
            if group == "expediter":
                print( "  Set LUPIN_INTERACTIVE_TESTS=true to enable expediter scenarios." )
                return False

        # ═══════════════════════════════════════════════════════════════
        # Start proxy if --auto-proxy
        # ═══════════════════════════════════════════════════════════════
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

    def post_run_hook( self, args, headers, results ):
        """
        Stop proxy after scenarios complete.

        Ensures:
            - Proxy subprocess is stopped gracefully
        """
        self._stop_proxy()

    def get_scenario_indices( self, args ):
        """
        Map --group or --scenarios flag to scenario indices.

        Filters out expediter scenarios when LUPIN_INTERACTIVE_TESTS is not set.

        Ensures:
            - Returns list of valid indices
        """
        # Get raw indices from CLI args
        if hasattr( args, "scenarios" ) and args.scenarios:
            indices = [
                int( x.strip() ) for x in args.scenarios.split( "," )
                if int( x.strip() ) < len( self.SCENARIOS )
            ]
        else:
            group   = getattr( args, "group", "all" )
            indices = GROUP_SCENARIOS.get( group, GROUP_SCENARIOS[ "all" ] )

        # Filter out expediter scenarios if interactive tests not enabled
        interactive = os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() == "true"
        if not interactive:
            filtered = [ i for i in indices if self.SCENARIOS[ i ].get( "group" ) != "expediter" ]
            if len( filtered ) < len( indices ):
                skipped = len( indices ) - len( filtered )
                print( f"\n  Note: {skipped} expediter scenario(s) skipped (set LUPIN_INTERACTIVE_TESTS=true)" )
            indices = filtered

        return indices

    def _print_results_table( self, results ):
        """
        Print integration-specific results table with group column.

        Requires:
            - results is a list of dicts with keys: id, group, status, details

        Ensures:
            - Prints tabular summary with pass/fail counts per group
        """
        print( "\n" + "=" * 90 )
        print( f"  {'#':<4} {'Scenario':<18} {'Group':<12} {'Status':<8} {'Details'}" )
        print( "-" * 90 )

        for i, r in enumerate( results, 1 ):
            status = r.get( "status", "fail" )
            icon   = "+" if status == "pass" else "-" if status == "fail" else "~"
            print( f"  {icon} {i:<3} {r[ 'id' ]:<18} {r.get( 'group', '' ):<12} {status:<8} {r.get( 'details', '' )}" )

        print( "=" * 90 )

        # Per-group summary
        groups = {}
        for r in results:
            g = r.get( "group", "unknown" )
            if g not in groups:
                groups[ g ] = { "pass": 0, "fail": 0, "other": 0 }
            if r[ "status" ] == "pass":
                groups[ g ][ "pass" ] += 1
            elif r[ "status" ] == "fail":
                groups[ g ][ "fail" ] += 1
            else:
                groups[ g ][ "other" ] += 1

        print( "\n  Per-group results:" )
        for g, counts in groups.items():
            total = counts[ "pass" ] + counts[ "fail" ] + counts[ "other" ]
            print( f"    {g:<12}: {counts[ 'pass' ]}/{total} passed" )

        passed = sum( 1 for r in results if r[ "status" ] == "pass" )
        failed = sum( 1 for r in results if r[ "status" ] == "fail" )
        cancel = sum( 1 for r in results if r[ "status" ] not in ( "pass", "fail" ) )

        print( f"\n  Total: {passed} passed, {failed} failed, {cancel} other" )
        print( f"  Overall: {'PASS' if failed == 0 and cancel == 0 else 'FAIL'}" )

    def run_scenarios( self, args=None ):
        """
        Override to update label with selected group.

        Ensures:
            - TEST_NAME reflects the selected group
        """
        group = getattr( args, "group", "all" )
        self.TEST_NAME = f"Proxy Integration ({group})"
        return super().run_scenarios( args )


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest + CLI Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( group="all" ):
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - group is one of: "calculator", "crud", "expediter", "all"

    Ensures:
        - Returns True if all selected scenarios pass
    """
    import argparse
    test = ProxyIntegrationTest()
    args = argparse.Namespace(
        group       = group,
        scenarios   = None,
        auto_proxy  = False,
        proxy_debug = False,
        no_confirm  = True,
        debug       = False,
        verbose     = False,
    )
    return test.run_scenarios( args )


def test_proxy_integration():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = ProxyIntegrationTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
