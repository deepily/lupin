#!/usr/bin/env python3
"""
Research to Presentation dry-run endpoint smoke test.

Validates the full HTTP submit-and-poll lifecycle against a running
server on port 7999. Tests the actual queue flow (todo -> running -> done)
for Research-to-Presentation chained dry-run jobs, plus error handling
for invalid payloads.

6 scenarios:

    #  ID                          Description
    0  RX_DRY_RUN_BASIC            Submit dry-run with query -> verify completion keywords
    1  RX_AGENT_TYPE               Submit dry-run -> verify agent_type == "research_to_presentation"
    2  RX_COST_SUMMARY             Submit dry-run -> verify cost_summary.total_cost_usd == 0.0
    3  RX_TIMESTAMPS               Submit dry-run -> verify started_at and completed_at are set
    4  RX_JOB_ID_PREFIX            Submit dry-run -> verify job_id starts with "rx-"
    5  RX_MISSING_QUERY            Submit empty payload -> expect HTTP 422

Usage:
    python src/tests/smoke/test_research_to_presentation_dry_run_smoke.py
    python src/tests/smoke/test_research_to_presentation_dry_run_smoke.py --debug

Requires:
    - Server running on localhost:7999
    - Environment variables: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-03-30
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

RESEARCH_TO_PRESENTATION_DRY_RUN_SCENARIOS = [
    {
        "id"                : "RX_DRY_RUN_BASIC",
        "query"             : "quantum computing breakthroughs 2026",
        "dry_run"           : True,
        "expected_keywords" : [ "complete", "simulation", "dry run" ],
    },
    {
        "id"      : "RX_AGENT_TYPE",
        "query"   : "quantum computing breakthroughs 2026",
        "dry_run" : True,
        "check"   : "agent_type",
    },
    {
        "id"      : "RX_COST_SUMMARY",
        "query"   : "quantum computing breakthroughs 2026",
        "dry_run" : True,
        "check"   : "cost_summary",
    },
    {
        "id"      : "RX_TIMESTAMPS",
        "query"   : "quantum computing breakthroughs 2026",
        "dry_run" : True,
        "check"   : "timestamps",
    },
    {
        "id"      : "RX_JOB_ID_PREFIX",
        "query"   : "quantum computing breakthroughs 2026",
        "dry_run" : True,
        "check"   : "job_id_prefix",
    },
    {
        "id"                : "RX_MISSING_QUERY",
        "payload"           : {},
        "expect_http_error" : 422,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class ResearchToPresentationDryRunSmokeTest( LivePipelineTestBase ):
    """
    Live endpoint smoke test for Research-to-Presentation chained dry-run lifecycle.

    Tests the full queue pipeline (todo -> running -> done) for chained
    research-to-presentation dry-run jobs, validating metadata, timestamps,
    cost tracking, and job ID format.

    Requires:
        - Server running on port 7999
        - Valid test credentials in environment

    Ensures:
        - Dry-run jobs complete through queue pipeline (todo -> running -> done)
        - Done queue metadata contains correct agent_type, cost_summary, timestamps
        - Job IDs use the "rx-" prefix
        - Invalid payloads return HTTP 422
    """

    TEST_NAME       = "Research to Presentation Dry Run"
    SUBMIT_ENDPOINT = "/api/deep-research-to-presentation/submit"
    DEFAULT_TIMEOUT = 240   # Chained workflow needs more time even in dry-run
    POLL_INTERVAL   = 3
    SCENARIOS       = RESEARCH_TO_PRESENTATION_DRY_RUN_SCENARIOS

    # ═══════════════════════════════════════════════════════════════════════
    # Payload Construction
    # ═══════════════════════════════════════════════════════════════════════

    def get_submit_payload( self, scenario, ws_id ):
        """
        Build the JSON payload for a Research-to-Presentation submission.

        Requires:
            - scenario is a dict from RESEARCH_TO_PRESENTATION_DRY_RUN_SCENARIOS
            - ws_id is a valid session ID

        Ensures:
            - Returns raw payload dict for error scenarios
            - Returns structured chained payload for normal scenarios
        """
        # Error scenarios use raw payload directly
        if "payload" in scenario:
            return scenario[ "payload" ]

        payload = {
            "query"                   : scenario[ "query" ],
            "budget"                  : 0.01,
            "target_duration_minutes" : 15,
            "dry_run"                 : scenario.get( "dry_run", True ),
        }
        # Lineage tag (row 7451bebe / bug 5ed4f187): a child pytest inside a monopolizing
        # test-suite job must thread LUPIN_TEST_MONOPOLIZE_PARENT_ID or the consumer's Gate B
        # defers it as a foreign writer and it starves 900s.
        parent_id = os.environ.get( "LUPIN_TEST_MONOPOLIZE_PARENT_ID" )
        if parent_id:
            payload[ "parent_id_hash" ] = parent_id
        return payload

    # ═══════════════════════════════════════════════════════════════════════
    # Mode Management
    # ═══════════════════════════════════════════════════════════════════════

    def get_mode_for_scenario( self, scenario ):
        """
        Research-to-Presentation uses dedicated REST endpoint, not mode switching.

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
            - scenario is a dict from RESEARCH_TO_PRESENTATION_DRY_RUN_SCENARIOS
        """
        if "query" in scenario:
            print( f"  Query: {scenario[ 'query' ]}" )
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
            - scenario is a dict from RESEARCH_TO_PRESENTATION_DRY_RUN_SCENARIOS
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
            - scenario is a dict from RESEARCH_TO_PRESENTATION_DRY_RUN_SCENARIOS
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

        if check == "job_id_prefix":
            return self._validate_job_id_prefix( job_data )

        # Default: keyword matching via base class
        return super().validate_result( scenario, job_data )

    def _validate_agent_type( self, job_data ):
        """
        Verify agent_type == "research_to_presentation" in done queue metadata.

        Requires:
            - job_data is a dict from the done queue

        Ensures:
            - Returns PASS if agent_type is "research_to_presentation"
        """
        agent_type = job_data.get( "agent_type", "" )
        answer     = job_data.get( "response_text", "" ) or ""

        if agent_type == "research_to_presentation":
            return {
                "status"         : "pass",
                "answer_preview" : answer[ :80 ],
                "details"        : f"agent_type={agent_type}",
            }

        return {
            "status"         : "fail",
            "answer_preview" : answer[ :80 ],
            "details"        : f"Expected agent_type=research_to_presentation, got {agent_type}",
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

    def _validate_job_id_prefix( self, job_data ):
        """
        Verify job_id starts with "rx-" prefix.

        Requires:
            - job_data is a dict from the done queue

        Ensures:
            - Returns PASS if job_id starts with "rx-"
        """
        job_id = job_data.get( "job_id", "" )
        answer = job_data.get( "response_text", "" ) or ""

        if job_id.startswith( "rx-" ):
            return {
                "status"         : "pass",
                "answer_preview" : answer[ :80 ],
                "details"        : f"job_id={job_id}",
            }

        return {
            "status"         : "fail",
            "answer_preview" : answer[ :80 ],
            "details"        : f"Expected job_id prefix 'rx-', got '{job_id[ :10 ]}'",
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
    test = ResearchToPresentationDryRunSmokeTest()
    return test.run( argv=[] )


def test_research_to_presentation_dry_run_endpoint():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = ResearchToPresentationDryRunSmokeTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
