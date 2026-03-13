#!/usr/bin/env python3
"""
Visual QA test for prediction hint rendering in notification cards.

Sends 7 response-required notifications with crafted prediction_hint_override
payloads covering all hint scenarios. Each notification stays on screen for
visual inspection in the browser.

Scenarios:

    #  response_type       Hint                         What it tests
    0  yes_no              (none)                       Cold-start ghost box
    1  yes_no              predicted_value + confidence  Warm yes/no
    2  yes_no              + predicted_qualifier         Qualified yes/no
    3  multiple_choice     answers (single-select)       MC single-select
    4  multiple_choice     answers (multi-select)        MC multi-select
    5  open_ended          predicted_value               Open-ended text
    6  open_ended_batch    answers dict                  Batch open-ended

Usage:
    python src/tests/smoke/test_prediction_hint_visual_qa.py
    python src/tests/smoke/test_prediction_hint_visual_qa.py --delay 12
    python src/tests/smoke/test_prediction_hint_visual_qa.py --scenario 2

Requires:
    - Server running on localhost:7999
    - Environment variables:
        LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL
        LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-03-03 (Session 303)
"""

import os
import sys
import json
import time
import argparse
import threading

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

BASE_URL    = "http://localhost:7999"
REQ_TIMEOUT = 10

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix — 7 hint scenarios
# ═══════════════════════════════════════════════════════════════════════════════

SCENARIOS = [
    # ── 0: Cold start — no prediction hint ──
    {
        "id"              : "COLD_START",
        "response_type"   : "yes_no",
        "message"         : "Should I proceed with the refactor?",
        "response_default": "no",
        "hint_override"   : None,
        "description"     : "Cold-start ghost box (no hint)",
    },
    # ── 1: Warm yes/no — predicted_value + confidence ──
    {
        "id"              : "WARM_YES_NO",
        "response_type"   : "yes_no",
        "message"         : "Should I run the full test suite?",
        "response_default": "no",
        "hint_override"   : {
            "predicted_value" : "yes",
            "confidence"      : 0.85,
            "strategy"        : "cbr_majority_vote",
        },
        "description"     : "Warm yes/no prediction",
    },
    # ── 2: Qualified yes/no — predicted_value + qualifier ──
    {
        "id"              : "QUALIFIED_YES_NO",
        "response_type"   : "yes_no",
        "message"         : "Should I run the tests before committing?",
        "response_default": "no",
        "hint_override"   : {
            "predicted_value"     : "yes",
            "predicted_qualifier" : "only the unit tests",
            "confidence"          : 0.78,
            "strategy"            : "cbr_majority_vote",
        },
        "description"     : "Qualified yes/no with qualifier text",
    },
    # ── 3: Multiple choice — single select ──
    {
        "id"              : "MC_SINGLE_SELECT",
        "response_type"   : "multiple_choice",
        "message"         : "Which database should we use?",
        "response_default": None,
        "response_options": {
            "questions": [ {
                "question"    : "Which database should we use?",
                "header"      : "Database",
                "multiSelect" : False,
                "options"     : [
                    { "label": "PostgreSQL", "description": "Relational database" },
                    { "label": "MongoDB",    "description": "Document database" },
                    { "label": "Redis",      "description": "In-memory key-value store" },
                ]
            } ]
        },
        "hint_override"   : {
            "answers"    : { "Database": "PostgreSQL" },
            "confidence" : 0.91,
            "strategy"   : "option_embedding_scoring",
        },
        "description"     : "MC single-select prediction",
    },
    # ── 4: Multiple choice — multi-select ──
    {
        "id"              : "MC_MULTI_SELECT",
        "response_type"   : "multiple_choice",
        "message"         : "Which features do you want to enable?",
        "response_default": None,
        "response_options": {
            "questions": [ {
                "question"    : "Which features do you want to enable?",
                "header"      : "Features",
                "multiSelect" : True,
                "options"     : [
                    { "label": "Dark mode",     "description": "Toggle dark theme" },
                    { "label": "Notifications", "description": "Push notifications" },
                    { "label": "Analytics",     "description": "Usage analytics" },
                    { "label": "Export",        "description": "CSV/PDF export" },
                ]
            } ]
        },
        "hint_override"   : {
            "answers"    : { "Features": [ "Dark mode", "Notifications" ] },
            "confidence" : 0.72,
            "strategy"   : "option_embedding_scoring",
        },
        "description"     : "MC multi-select prediction",
    },
    # ── 5: Open-ended — single predicted value ──
    {
        "id"              : "OPEN_ENDED",
        "response_type"   : "open_ended",
        "message"         : "What topic would you like to research?",
        "response_default": None,
        "hint_override"   : {
            "predicted_value" : "quantum computing",
            "confidence"      : 0.65,
            "strategy"        : "cbr_retrieval",
        },
        "description"     : "Open-ended text prediction",
    },
    # ── 6: Open-ended batch — multiple answers ──
    {
        "id"              : "OPEN_ENDED_BATCH",
        "response_type"   : "open_ended_batch",
        "message"         : "Please answer these research questions.",
        "response_default": None,
        "response_options": {
            "questions": [
                { "question": "What topic would you like to research?",    "header": "Topic" },
                { "question": "Would you like to set a budget limit?",     "header": "Budget" },
                { "question": "Who is the target audience?",               "header": "Audience" },
            ]
        },
        "hint_override"   : {
            "answers"    : {
                "Topic"    : "quantum computing",
                "Budget"   : "no limit",
                "Audience" : "graduate students",
            },
            "confidence" : 0.58,
            "strategy"   : "llm_synthesis",
        },
        "description"     : "Batch open-ended prediction",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Authentication helper
# ═══════════════════════════════════════════════════════════════════════════════

def login():
    """
    Authenticate using LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* env vars.

    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL is set
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD is set
        - Server running on BASE_URL

    Ensures:
        - Returns ( token, headers, email ) tuple on success
        - Exits with error message on failure

    Raises:
        - SystemExit if credentials missing or login fails
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

    if not email or not password:
        print( "ERROR: Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
        sys.exit( 1 )

    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=REQ_TIMEOUT
    )

    if resp.status_code != 200:
        print( f"ERROR: Login failed ({resp.status_code}): {resp.text}" )
        sys.exit( 1 )

    token   = resp.json()[ "tokens" ][ "access_token" ]
    headers = { "Authorization": f"Bearer {token}" }

    print( f"  Authenticated as {email}" )
    return token, headers, email


# ═══════════════════════════════════════════════════════════════════════════════
# SSE consumer (background thread to prevent blocking)
# ═══════════════════════════════════════════════════════════════════════════════

def consume_sse_background( url, headers, params, scenario_id ):
    """
    Consume SSE stream in a background thread so the main thread can continue.

    Requires:
        - url is a valid endpoint URL
        - headers contains valid Authorization
        - params contains valid /api/notify query parameters

    Ensures:
        - Sends POST request with stream=True
        - Reads SSE events until stream ends or timeout
        - Prints any received events to console
    """
    try:
        resp = requests.post( url, headers=headers, params=params, stream=True, timeout=130 )
        if resp.status_code != 200:
            print( f"  [{scenario_id}] SSE error: HTTP {resp.status_code}" )
            return

        for line in resp.iter_lines( decode_unicode=True ):
            if line and line.startswith( "data:" ):
                data = line[ 5: ].strip()
                try:
                    parsed = json.loads( data )
                    status = parsed.get( "status", "unknown" )
                    print( f"  [{scenario_id}] SSE response: {status}" )
                except json.JSONDecodeError:
                    pass
    except requests.exceptions.ReadTimeout:
        print( f"  [{scenario_id}] SSE stream timed out (expected for visual QA)" )
    except Exception as e:
        print( f"  [{scenario_id}] SSE error: {e}" )


# ═══════════════════════════════════════════════════════════════════════════════
# Send a single scenario
# ═══════════════════════════════════════════════════════════════════════════════

def send_scenario( scenario, headers, email, index ):
    """
    Send a single prediction hint scenario to /api/notify.

    Requires:
        - scenario is a valid entry from SCENARIOS list
        - headers contains valid Authorization
        - email is the target user email

    Ensures:
        - Sends notification with response_requested=True
        - If hint_override is set, passes it as prediction_hint_override JSON
        - Starts SSE consumer in background thread
        - Returns True on success, False on failure
    """
    scenario_id = scenario[ "id" ]
    print( f"\n{'─' * 60}" )
    print( f"  Scenario {index}: {scenario_id}" )
    print( f"  {scenario[ 'description' ]}" )
    print( f"  response_type: {scenario[ 'response_type' ]}" )
    print( f"  hint: {'(none)' if scenario[ 'hint_override' ] is None else json.dumps( scenario[ 'hint_override' ], indent=2 )}" )

    params = {
        "message"            : scenario[ "message" ],
        "type"               : "task",
        "priority"           : "high",
        "target_user"        : email,
        "response_requested" : True,
        "response_type"      : scenario[ "response_type" ],
        "timeout_seconds"    : 120,
    }

    if scenario.get( "response_default" ) is not None:
        params[ "response_default" ] = scenario[ "response_default" ]

    if scenario.get( "response_options" ) is not None:
        params[ "response_options" ] = json.dumps( scenario[ "response_options" ] )

    if scenario[ "hint_override" ] is not None:
        params[ "prediction_hint_override" ] = json.dumps( scenario[ "hint_override" ] )

    # Fire the request in a background thread (SSE stream blocks)
    url = f"{BASE_URL}/api/notify"
    thread = threading.Thread(
        target=consume_sse_background,
        args=( url, headers, params, scenario_id ),
        daemon=True
    )
    thread.start()

    # Give the server a moment to push via WebSocket
    time.sleep( 0.5 )

    print( f"  Sent. Notification should be visible in browser." )
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():

    parser = argparse.ArgumentParser( description="Visual QA for prediction hint rendering" )
    parser.add_argument( "--delay",    type=int, default=8, help="Seconds between scenarios (default: 8)" )
    parser.add_argument( "--scenario", type=int, default=None, help="Run a single scenario by index (0-6)" )
    args = parser.parse_args()

    print( "=" * 60 )
    print( "  Prediction Hint Visual QA" )
    print( "  7 scenarios covering all hint types" )
    print( "=" * 60 )

    # Authenticate
    token, headers, email = login()

    # Determine which scenarios to run
    if args.scenario is not None:
        if args.scenario < 0 or args.scenario >= len( SCENARIOS ):
            print( f"ERROR: --scenario must be 0-{len( SCENARIOS ) - 1}" )
            sys.exit( 1 )
        scenarios_to_run = [ ( args.scenario, SCENARIOS[ args.scenario ] ) ]
    else:
        scenarios_to_run = list( enumerate( SCENARIOS ) )

    # Send each scenario
    results = []
    for index, scenario in scenarios_to_run:
        success = send_scenario( scenario, headers, email, index )
        results.append( ( index, scenario[ "id" ], scenario[ "description" ], success ) )

        # Pause between scenarios for visual inspection (skip after last)
        if index != scenarios_to_run[ -1 ][ 0 ]:
            print( f"\n  Waiting {args.delay}s for visual inspection..." )
            time.sleep( args.delay )

    # Print summary table
    print( f"\n{'=' * 60}" )
    print( f"  Summary" )
    print( f"{'=' * 60}" )
    print( f"  {'#':<3} {'ID':<22} {'Result':<8} {'Description'}" )
    print( f"  {'─'*3} {'─'*22} {'─'*8} {'─'*30}" )
    for index, scenario_id, description, success in results:
        status = "SENT" if success else "FAIL"
        print( f"  {index:<3} {scenario_id:<22} {status:<8} {description}" )
    print( f"\n  Total: {len( results )} scenarios sent" )
    print( f"  Check browser for visual rendering of hint boxes." )
    print( f"  Scenario 0 should show ghost box; 1-6 should show purple hint box." )


if __name__ == "__main__":
    main()
