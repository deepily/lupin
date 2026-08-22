#!/usr/bin/env python3
"""
Claude Code dry-run endpoint smoke test — Surface 2 Layer B.

Validates the full HTTP submit-and-poll lifecycle against a running
server on port 7999. Tests the actual queue flow (todo -> running -> done)
for Claude Code dry-run jobs in both BOUNDED and INTERACTIVE modes,
plus error handling for invalid payloads.

6 scenarios:

    #  ID                          task_type    Description
    0  CC_BOUNDED_DRY_RUN          BOUNDED      Submit dry-run -> verify "Mock Bounded execution completed"
    1  CC_INTERACTIVE_DRY_RUN      INTERACTIVE  Submit dry-run -> verify "Mock Interactive session completed", "conversation turns"
    2  CC_AGENT_TYPE               BOUNDED      Submit dry-run -> verify agent_type == "claude_code", status == "completed"
    3  CC_COST_SUMMARY             BOUNDED      Submit dry-run -> verify cost_summary.total_cost_usd == 0.0
    4  CC_TIMESTAMPS               INTERACTIVE  Submit dry-run -> verify started_at and completed_at are set
    5  CC_MISSING_PROMPT           N/A          Submit empty payload -> expect HTTP 422

Usage:
    python src/tests/smoke/test_claude_code_dry_run_smoke.py
    python src/tests/smoke/test_claude_code_dry_run_smoke.py --debug

Requires:
    - Server running on localhost:7999
    - Environment variables: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-02-25
"""

import os
import sys

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests

from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

CLAUDE_CODE_DRY_RUN_SCENARIOS = [
    {
        "id"                : "CC_BOUNDED_DRY_RUN",
        "prompt"            : "Run the tests and fix any failures",
        "task_type"         : "BOUNDED",
        "dry_run"           : True,
        "expected_keywords" : [ "Mock Bounded execution completed" ],
    },
    {
        "id"                : "CC_INTERACTIVE_DRY_RUN",
        "prompt"            : "Let's refactor the authentication module together",
        "task_type"         : "INTERACTIVE",
        "dry_run"           : True,
        "expected_keywords" : [ "Mock Interactive session completed", "conversation turns" ],
    },
    {
        "id"        : "CC_AGENT_TYPE",
        "prompt"    : "Add input validation to the registration endpoint",
        "task_type" : "BOUNDED",
        "dry_run"   : True,
        "check"     : "agent_type",
    },
    {
        "id"        : "CC_COST_SUMMARY",
        "prompt"    : "Refactor the database connection module",
        "task_type" : "BOUNDED",
        "dry_run"   : True,
        "check"     : "cost_summary",
    },
    {
        "id"        : "CC_TIMESTAMPS",
        "prompt"    : "Walk me through optimizing the query layer",
        "task_type" : "INTERACTIVE",
        "dry_run"   : True,
        "check"     : "timestamps",
    },
    {
        "id"                : "CC_MISSING_PROMPT",
        "payload"           : {},
        "expect_http_error" : 422,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class ClaudeCodeDryRunSmokeTest( LivePipelineTestBase ):
    """
    Live endpoint smoke test for Claude Code dry-run submit-and-poll lifecycle.

    Tests both BOUNDED and INTERACTIVE dry-run modes through the queue pipeline,
    validating that INTERACTIVE mode exercises MessageHistory and multi-turn
    conversation simulation.

    Requires:
        - Server running on port 7999
        - Valid test credentials in environment

    Ensures:
        - BOUNDED dry-run jobs complete through queue pipeline (todo -> running -> done)
        - INTERACTIVE dry-run jobs exercise MessageHistory and report conversation stats
        - Done queue metadata contains correct agent_type, cost_summary, timestamps
        - Invalid payloads return HTTP 422
    """

    TEST_NAME       = "Claude Code Dry Run"
    # The two dedicated doors (/api/claude-code/submit and its /queue/submit alias) are
    # retired (410) per Rick's 2026-08-21 ruling; one front door now.
    SUBMIT_ENDPOINT = "/api/v2/submit"
    ROUTING_COMMAND = "agent router go to claude code"
    DEFAULT_TIMEOUT = 120
    POLL_INTERVAL   = 2
    SCENARIOS       = CLAUDE_CODE_DRY_RUN_SCENARIOS

    # ═══════════════════════════════════════════════════════════════════════
    # Payload Construction
    # ═══════════════════════════════════════════════════════════════════════

    def get_submit_payload( self, scenario, ws_id ):
        """
        Build the JSON payload for a Claude Code queue submission.

        Requires:
            - scenario is a dict from CLAUDE_CODE_DRY_RUN_SCENARIOS
            - ws_id is a valid session ID

        Ensures:
            - Returns raw payload dict for error scenarios
            - Returns structured Claude Code payload for normal scenarios
        """
        # Error scenarios use raw payload directly
        if "payload" in scenario:
            return scenario[ "payload" ]

        # ONE DOOR NOW. The dedicated endpoints this used to post to are retired and answer
        # 410 naming /api/v2/submit, which takes the routing command as a string and the
        # job's own arguments in `args`. `websocket_id` stays TOP-LEVEL because it is a
        # queue/routing directive rather than an argument to the agent, and `args` is
        # checked against the command's own argument contract.
        body = {
            "command"      : self.ROUTING_COMMAND,
            "args"         : {
                "prompt"    : scenario[ "prompt" ],
                "task_type" : scenario.get( "task_type", "BOUNDED" ),
                "dry_run"   : scenario.get( "dry_run", True ),
            },
            "question"     : scenario[ "prompt" ],
            "websocket_id" : ws_id,
        }
        # Lineage tag (bug 5ed4f187): when this smoke runs as a child pytest inside a
        # monopolizing test-suite job, the runner exports LUPIN_TEST_MONOPOLIZE_PARENT_ID
        # (test_suite/job.py). Threading it as parent_id_hash lets the consumer's Gate B
        # admit this child through the monopoly hold instead of starving it 900s. It is a
        # queue directive, so it stays top-level rather than going inside `args`.
        parent_id = os.environ.get( "LUPIN_TEST_MONOPOLIZE_PARENT_ID" )
        if parent_id:
            body[ "parent_id_hash" ] = parent_id
        return body

    # ═══════════════════════════════════════════════════════════════════════
    # Mode Management
    # ═══════════════════════════════════════════════════════════════════════

    def get_mode_for_scenario( self, scenario ):
        """
        Claude Code does not use mode switching.

        Ensures:
            - Always returns None
        """
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Scenario Execution
    # ═══════════════════════════════════════════════════════════════════════

    def _print_scenario_header( self, scenario ):
        """
        Print scenario details before execution.

        Requires:
            - scenario is a dict from CLAUDE_CODE_DRY_RUN_SCENARIOS
        """
        if "prompt" in scenario:
            print( f"  Prompt: \"{scenario[ 'prompt' ]}\"" )
            task_type = scenario.get( "task_type", "BOUNDED" )
            print( f"  Task type: {task_type}" )
            if scenario.get( "dry_run" ):
                print( f"  Mode: dry_run" )
            if "check" in scenario:
                print( f"  Validation: {scenario[ 'check' ]}" )
            if "expected_keywords" in scenario:
                print( f"  Expected keywords: {scenario[ 'expected_keywords' ]}" )
        elif "payload" in scenario:
            print( f"  Payload: {scenario[ 'payload' ]}" )
            print( f"  Expected HTTP error: {scenario[ 'expect_http_error' ]}" )

    def _run_single_scenario( self, scenario, headers, ws_id ):
        """
        Execute a single scenario, routing error scenarios to direct HTTP check.

        Requires:
            - scenario is a dict from CLAUDE_CODE_DRY_RUN_SCENARIOS
            - headers contains valid auth token
            - ws_id is session ID

        Ensures:
            - Returns dict with keys: id, status, answer_preview, details
        """
        # Error scenarios: direct HTTP post, check status code
        if "expect_http_error" in scenario:
            return self._run_error_scenario( scenario, headers, ws_id )

        # Normal scenarios: delegate to base class submit-and-poll
        return super()._run_single_scenario( scenario, headers, ws_id )

    def _run_error_scenario( self, scenario, headers, ws_id ):
        """
        Submit an invalid payload and verify the expected HTTP error code.

        Requires:
            - scenario has "expect_http_error" and "payload" keys
            - headers contains valid auth token

        Ensures:
            - Returns PASS if HTTP status matches expected error code
            - Returns FAIL otherwise
        """
        result = {
            "id"             : scenario[ "id" ],
            "status"         : "fail",
            "answer_preview" : "",
            "details"        : "",
        }

        expected_code = scenario[ "expect_http_error" ]
        payload       = scenario.get( "payload", {} )
        req_headers   = self.get_submit_headers( headers, ws_id )

        try:
            resp = requests.post(
                f"{self.BASE_URL}{self.SUBMIT_ENDPOINT}",
                json=payload,
                headers=req_headers,
                timeout=self.REQUEST_TIMEOUT
            )

            if resp.status_code == expected_code:
                result[ "status" ]         = "pass"
                result[ "details" ]        = f"HTTP {resp.status_code} as expected"
                result[ "answer_preview" ] = resp.text[ :80 ]
                print( f"    PASS: HTTP {resp.status_code} (expected {expected_code})" )
            else:
                result[ "details" ]        = f"Expected HTTP {expected_code}, got {resp.status_code}"
                result[ "answer_preview" ] = resp.text[ :80 ]
                print( f"    FAIL: Expected HTTP {expected_code}, got {resp.status_code}" )
                print( f"    Body: {resp.text[ :200 ]}" )

        except Exception as e:
            result[ "details" ] = f"Request error: {e}"
            print( f"    FAIL: {e}" )

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # Validation
    # ═══════════════════════════════════════════════════════════════════════

    def validate_result( self, scenario, job_data ):
        """
        Validate a completed job against scenario expectations.

        Requires:
            - scenario is a dict from CLAUDE_CODE_DRY_RUN_SCENARIOS
            - job_data is a dict from the done queue

        Ensures:
            - Dispatches to check-specific validation for custom checks
            - Falls back to base class keyword matching for expected_keywords
        """
        check = scenario.get( "check" )

        if check == "agent_type":
            return self._validate_agent_type( job_data )

        if check == "cost_summary":
            return self._validate_cost_summary( job_data )

        if check == "timestamps":
            return self._validate_timestamps( job_data )

        # Default: keyword matching via base class
        return super().validate_result( scenario, job_data )

    def _validate_agent_type( self, job_data ):
        """
        Verify agent_type == "claude_code" and status == "completed" in done queue.

        Requires:
            - job_data is a dict from the done queue

        Ensures:
            - Returns PASS if agent_type is "claude_code" and status is "completed"
        """
        agent_type = job_data.get( "agent_type", "" )
        status     = job_data.get( "status", "" )
        answer     = job_data.get( "response_text", "" ) or ""

        if agent_type == "claude_code" and status == "completed":
            return {
                "status"         : "pass",
                "answer_preview" : answer[ :80 ],
                "details"        : f"agent_type={agent_type}, status={status}",
            }

        return {
            "status"         : "fail",
            "answer_preview" : answer[ :80 ],
            "details"        : f"Expected agent_type=claude_code/status=completed, got {agent_type}/{status}",
        }

    def _validate_cost_summary( self, job_data ):
        """
        Verify cost_summary has zero cost for dry-run jobs.

        Requires:
            - job_data is a dict from the done queue

        Ensures:
            - Returns PASS if cost_summary is a dict with total_cost_usd == 0.0
        """
        cost_summary = job_data.get( "cost_summary" )
        answer       = job_data.get( "response_text", "" ) or ""

        if not isinstance( cost_summary, dict ):
            return {
                "status"         : "fail",
                "answer_preview" : answer[ :80 ],
                "details"        : f"cost_summary is not a dict: {type( cost_summary ).__name__}",
            }

        total_cost = cost_summary.get( "total_cost_usd", -1 )

        if total_cost == 0.0 or total_cost == 0:
            return {
                "status"         : "pass",
                "answer_preview" : answer[ :80 ],
                "details"        : f"cost_summary.total_cost_usd={total_cost}",
            }

        return {
            "status"         : "fail",
            "answer_preview" : answer[ :80 ],
            "details"        : f"Expected total_cost_usd=0.0, got {total_cost}",
        }

    def _validate_timestamps( self, job_data ):
        """
        Verify started_at and completed_at are set in done queue metadata.

        Requires:
            - job_data is a dict from the done queue

        Ensures:
            - Returns PASS if both started_at and completed_at are non-None
        """
        started_at   = job_data.get( "started_at" )
        completed_at = job_data.get( "completed_at" )
        answer       = job_data.get( "response_text", "" ) or ""

        if started_at and completed_at:
            return {
                "status"         : "pass",
                "answer_preview" : answer[ :80 ],
                "details"        : f"started_at={started_at}, completed_at={completed_at}",
            }

        missing = []
        if not started_at:
            missing.append( "started_at" )
        if not completed_at:
            missing.append( "completed_at" )

        return {
            "status"         : "fail",
            "answer_preview" : answer[ :80 ],
            "details"        : f"Missing timestamps: {', '.join( missing )}",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest + CLI Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test():
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - Server running on localhost:7999
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD set

    Ensures:
        - Returns True if all 6 scenarios pass
    """
    test = ClaudeCodeDryRunSmokeTest()
    return test.run( argv=[] )


def test_claude_code_dry_run_endpoint():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = ClaudeCodeDryRunSmokeTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
