#!/usr/bin/env python3
"""
Smoke test for notification proxy script matching via live Phi-4 LLM.

Sends questions directly through LlmScriptMatcherStrategy to validate:
  - Phi-4 produces parseable ScriptMatcherResponse XML
  - Exact question_pattern text matches script entries (Tier 1: Exact)
  - Paraphrased questions semantically match via fuzzy matching (Tier 2: Fuzzy)
  - Batch, multiple-choice, and negative scenarios work end-to-end (Tier 3: Multi)

No server, WebSocket, or authentication required — only vLLM with Phi-4.

Usage:
    # Default: deep_research script, all tiers
    python src/tests/smoke/test_notification_proxy_script_matching.py

    # Expeditor smoke script (broader coverage, 3 agents)
    python src/tests/smoke/test_notification_proxy_script_matching.py -s expeditor_smoke

    # Both scripts (full coverage)
    python src/tests/smoke/test_notification_proxy_script_matching.py -s all

    # Only exact tier
    python src/tests/smoke/test_notification_proxy_script_matching.py -t exact

    # Specific scenarios by index
    python src/tests/smoke/test_notification_proxy_script_matching.py -n 0,8,20

    # Disable verifier for faster runs
    python src/tests/smoke/test_notification_proxy_script_matching.py --no-verify

    # Debug output
    python src/tests/smoke/test_notification_proxy_script_matching.py --debug --verbose

Scenario index reference (expeditor_smoke, all tiers):
     0-7:  EXACT   — Literal question_pattern from script entries
    8-19:  FUZZY   — Paraphrased questions for semantic matching
   20-23:  MULTI   — Multiple-choice, batch, and negative (no-match)

Requires:
    - vLLM server running with Phi-4 model loaded
    - LUPIN_ROOT environment variable set

Created: 2026-02-12 (Session 193)
"""

import argparse
import json
import os
import sys
import time
import traceback

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

try:
    import cosa.utils.util as cu
except ImportError:
    cu = None

from cosa.agents.notification_proxy.strategies.llm_script_matcher import (
    LlmScriptMatcherStrategy, resolve_script_path
)
from cosa.agents.notification_proxy.verification import LlmAnswerVerifier
from cosa.agents.notification_proxy.config import DEFAULT_ACCEPTED_SENDERS


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Context Mapping
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_DISPLAY_NAMES = {
    "deep_research"       : "Deep Research",
    "research_to_podcast" : "Research To Podcast",
    "podcast"             : "Podcast",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 2: Fuzzy/Paraphrased Scenarios (static definitions)
# ═══════════════════════════════════════════════════════════════════════════════

FUZZY_SCENARIOS = [
    {
        "id"            : "FUZZY_DR_QUERY_1",
        "question"      : "What subject should I investigate?",
        "arg_name"      : "query",
        "agent_context" : "deep_research",
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_DR_QUERY_2",
        "question"      : "Tell me the research topic you'd like",
        "arg_name"      : "query",
        "agent_context" : "deep_research",
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_BUDGET_1",
        "question"      : "Do you want to cap the spending?",
        "arg_name"      : "budget",
        "agent_context" : "deep_research",
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_BUDGET_2",
        "question"      : "Is there a maximum dollar amount?",
        "arg_name"      : "budget",
        "agent_context" : "research_to_podcast",
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_AUDIENCE_1",
        "question"      : "What kind of people will be reading this?",
        "arg_name"      : "audience",
        "agent_context" : None,
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_AUDIENCE_2",
        "question"      : "Who should I write this for?",
        "arg_name"      : "audience",
        "agent_context" : None,
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_CONFIRM_1",
        "question"      : "Ready to go with these options?",
        "arg_name"      : "confirmation",
        "agent_context" : None,
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_CONFIRM_2",
        "question"      : "Shall I start the job now?",
        "arg_name"      : "confirmation",
        "agent_context" : None,
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_RTP_QUERY_1",
        "question"      : "What's the research topic for the podcast?",
        "arg_name"      : "query",
        "agent_context" : "research_to_podcast",
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_PG_DOC_1",
        "question"      : "Which document should be used as source material?",
        "arg_name"      : "research",
        "agent_context" : "podcast",
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_LANGS_1",
        "question"      : "In what language should the podcast be produced?",
        "arg_name"      : "languages",
        "agent_context" : "podcast",
        "response_type" : "open_ended",
    },
    {
        "id"            : "FUZZY_AUDIENCE_CTX_1",
        "question"      : "Anything else I should know about who this is for?",
        "arg_name"      : "audience_context",
        "agent_context" : None,
        "response_type" : "open_ended",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 3: Multi-Response Type + Negative Scenarios
# ═══════════════════════════════════════════════════════════════════════════════

MULTI_SCENARIOS = [
    {
        "id"            : "MC_AUDIENCE",
        "question"      : "Who is the target audience?",
        "arg_name"      : "audience",
        "agent_context" : None,
        "response_type" : "multiple_choice",
        "expected"      : "academic",
        "options"       : [
            { "label" : "beginner", "description" : "No prior knowledge needed" },
            { "label" : "academic", "description" : "Research-level depth" },
            { "label" : "general",  "description" : "General public" },
            { "label" : "expert",   "description" : "Industry professionals" },
        ],
    },
    {
        "id"              : "BATCH_DR",
        "question"        : None,
        "arg_name"        : None,
        "agent_context"   : "deep_research",
        "response_type"   : "open_ended_batch",
        "expected"        : { "Budget" : "no limit", "Audience" : "academic", "Context" : "none" },
        "batch_questions" : [
            { "header" : "Budget",   "question" : "Would you like to set a budget limit?", "default_value" : "" },
            { "header" : "Audience", "question" : "Who is the target audience?",           "default_value" : "" },
            { "header" : "Context",  "question" : "Any additional context?",               "default_value" : "" },
        ],
    },
    {
        "id"              : "BATCH_MIXED",
        "question"        : None,
        "arg_name"        : None,
        "agent_context"   : "deep_research",
        "response_type"   : "open_ended_batch",
        "expected"        : { "Topic" : "quantum computing breakthroughs 2026", "Budget" : "no limit" },
        "batch_questions" : [
            { "header" : "Topic",  "question" : "What topic would you like me to research?", "default_value" : "" },
            { "header" : "Budget", "question" : "Would you like to set a budget limit?",     "default_value" : "" },
        ],
    },
    {
        "id"            : "NEGATIVE_NO_MATCH",
        "question"      : "What is the airspeed velocity of an unladen swallow?",
        "arg_name"      : None,
        "agent_context" : None,
        "response_type" : "open_ended",
        "expected"      : None,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

def _preflight_check( strategy, entries ):
    """
    Quick pre-flight LLM connectivity check using the first script entry.

    Requires:
        - strategy is a constructed LlmScriptMatcherStrategy with available=True
        - entries is a non-empty list of script entry dicts

    Ensures:
        - Returns True if a minimal LLM call succeeds (answer returned)
        - Returns False if the LLM is unreachable or returns no answer
    """
    entry       = entries[ 0 ]
    notification = _build_notification(
        question      = entry[ "question_pattern" ],
        response_type = "open_ended",
        agent_context = None,
    )
    try:
        answer = strategy.respond( notification )
        return answer is not None
    except Exception:
        return False


def _build_exact_scenarios( entries ):
    """
    Auto-generate exact-match scenarios from loaded script entries.

    Requires:
        - entries is a non-empty list of script entry dicts

    Ensures:
        - Returns list of scenario dicts, one per entry
        - Each scenario uses the literal question_pattern as the question
        - Agent context is derived from the entry's agents tag (first entry)
    """
    scenarios = []
    for i, entry in enumerate( entries ):
        # Determine agent context from entry's agents tag
        agents    = entry.get( "agents" )
        agent_ctx = agents[ 0 ] if agents and len( agents ) > 0 else None

        # Use first response_type from entry
        response_types = entry.get( "response_types", [ "open_ended" ] )
        response_type  = response_types[ 0 ]

        scenarios.append( {
            "id"            : f"EXACT_{entry[ 'arg_name' ].upper()}_{i}",
            "tier"          : "exact",
            "question"      : entry[ "question_pattern" ],
            "expected"      : entry[ "answer" ],
            "arg_name"      : entry[ "arg_name" ],
            "agent_context" : agent_ctx,
            "response_type" : response_type,
            "source_entry"  : i,
        } )

    return scenarios


def _build_notification( question, response_type, agent_context=None,
                         options=None, batch_questions=None ):
    """
    Construct a notification dict for LlmScriptMatcherStrategy.respond().

    Requires:
        - question is a string (or None for batch)
        - response_type is one of: open_ended, yes_no, multiple_choice, open_ended_batch

    Ensures:
        - Returns a dict with all fields needed by respond()
        - Agent context is formatted as "Agent: <Display Name>" in abstract
    """
    abstract = ""
    if agent_context and agent_context in AGENT_DISPLAY_NAMES:
        abstract = f"Agent: {AGENT_DISPLAY_NAMES[ agent_context ]}"

    notification = {
        "message"            : question or "",
        "title"              : "",
        "response_type"      : response_type,
        "abstract"           : abstract,
        "sender_id"          : DEFAULT_ACCEPTED_SENDERS[ 0 ],
        "response_requested" : True,
    }

    if response_type == "multiple_choice" and options:
        notification[ "response_options" ] = {
            "questions" : [ {
                "question" : question,
                "header"   : "Selection",
                "options"  : options,
            } ]
        }

    if response_type == "open_ended_batch" and batch_questions:
        notification[ "response_options" ] = {
            "questions" : batch_questions
        }

    return notification


def _check_answer( actual, expected, response_type="open_ended" ):
    """
    Compare actual answer to expected answer.

    Requires:
        - expected is a string, dict, or None
        - actual is a string or None

    Ensures:
        - Returns (passed_bool, details_str) tuple
        - For None expected: passes if actual is None
        - For string expected: case-insensitive stripped comparison
        - For dict expected: parses actual as JSON and compares values
    """
    # Negative scenario: expect no match
    if expected is None:
        if actual is None:
            return True, "correctly returned None (no match)"
        else:
            return False, f"expected None, got '{str( actual )[ :60 ]}'"

    # No answer returned
    if actual is None:
        return False, f"returned None, expected '{str( expected )[ :60 ]}'"

    # Batch scenario: compare dict values
    if isinstance( expected, dict ):
        try:
            parsed  = json.loads( actual )
            answers = parsed.get( "answers", parsed )

            mismatches = []
            for key, exp_val in expected.items():
                act_val = answers.get( key, "" )
                if act_val.strip().lower() != exp_val.strip().lower():
                    mismatches.append( f"{key}: '{act_val}' != '{exp_val}'" )

            if not mismatches:
                return True, f"all {len( expected )} batch values match"
            else:
                return False, "; ".join( mismatches )

        except ( json.JSONDecodeError, AttributeError ) as e:
            return False, f"JSON parse error: {e}"

    # Single answer: case-insensitive comparison
    if actual.strip().lower() == expected.strip().lower():
        return True, f"exact match: '{expected[ :40 ]}'"

    # Partial/substring match as fallback
    if expected.strip().lower() in actual.strip().lower():
        return True, f"substring match: '{expected[ :40 ]}'"

    return False, f"got '{actual[ :60 ]}', expected '{expected[ :40 ]}'"


def _lookup_expected_answer( arg_name, agent_context, entries ):
    """
    Look up expected answer from script entries by arg_name and agent context.

    Requires:
        - arg_name is a string
        - entries is a list of script entry dicts

    Ensures:
        - Returns the answer string for the best-matching entry
        - Returns None if no matching entry found
        - Prefers agent-scoped matches over universal entries
    """
    # First pass: match arg_name + agent context
    for entry in entries:
        if entry.get( "arg_name" ) != arg_name:
            continue
        entry_agents = entry.get( "agents" )
        if entry_agents and agent_context and agent_context not in entry_agents:
            continue
        return entry[ "answer" ]

    # Fallback: any entry with matching arg_name
    for entry in entries:
        if entry.get( "arg_name" ) == arg_name:
            return entry[ "answer" ]

    return None


def _print_results_table( results, script_name ):
    """
    Print formatted summary table of all scenario results.

    Requires:
        - results is a list of dicts with keys: idx, tier, id, status, conf,
          answer_preview, time_s

    Ensures:
        - Prints tabular summary to console with alignment
    """
    print( "\n" + "=" * 95 )
    print( f"  {'#':<4} {'Tier':<6} {'Scenario ID':<24} {'Status':<8} {'Conf':<6} "
           f"{'Answer Preview':<28} {'Time':>6}" )
    print( "-" * 95 )

    for r in results:
        if r[ "status" ] == "pass":
            status_str = "PASS"
            icon       = "+"
        elif r[ "status" ] == "skip":
            status_str = "SKIP"
            icon       = "~"
        else:
            status_str = "FAIL"
            icon       = "-"

        preview  = r.get( "answer_preview", "" )[ :26 ]
        conf_str = r.get( "conf", "---" )
        time_str = f"{r.get( 'time_s', 0 ):.1f}s"

        print( f"  {icon} {r[ 'idx' ]:<3} {r[ 'tier' ]:<6} {r[ 'id' ]:<24} "
               f"{status_str:<8} {conf_str:<6} {preview:<28} {time_str:>6}" )

    print( "=" * 95 )

    passed  = sum( 1 for r in results if r[ "status" ] == "pass" )
    failed  = sum( 1 for r in results if r[ "status" ] == "fail" )
    skipped = sum( 1 for r in results if r[ "status" ] == "skip" )

    total_time = sum( r.get( "time_s", 0 ) for r in results )
    parts      = [ f"{passed} passed" ]
    if failed > 0:  parts.append( f"{failed} failed" )
    if skipped > 0: parts.append( f"{skipped} skipped" )

    print( f"\n  Script: {script_name} | Total: {', '.join( parts )} | Time: {total_time:.1f}s" )
    print( f"  Overall: {'PASS' if failed == 0 else 'FAIL'}" )


# ═══════════════════════════════════════════════════════════════════════════════
# Single-Script Runner
# ═══════════════════════════════════════════════════════════════════════════════

def _run_single_script( script_name, tier, scenario_indices, verify,
                        min_confidence, debug, verbose ):
    """
    Run scenarios for a single Q&A script.

    Requires:
        - script_name is "deep_research" or "expeditor_smoke"
        - tier is "exact", "fuzzy", "multi", or "all"
        - scenario_indices is None (run all) or a list of ints

    Ensures:
        - Returns (results_list, all_passed_bool)
        - Returns ([], True) if vLLM unavailable (graceful skip, not a failure)
        - Constructs LlmScriptMatcherStrategy from the script file
        - Auto-generates exact scenarios from script entries
        - Filters fuzzy/multi scenarios by arg_name applicability
    """
    # Resolve script path and verify existence
    script_path = resolve_script_path( script_name )
    if not os.path.exists( script_path ):
        print( f"  Script not found: {script_path}" )
        return [], False

    print( f"\n  Loading script: {script_name} ({script_path})" )

    # Create strategy — this also checks vLLM availability
    strategy = LlmScriptMatcherStrategy(
        script_path = script_path,
        debug       = debug,
        verbose     = verbose
    )

    if not strategy.available:
        print( "\n  vLLM unavailable -- skipping smoke test (this is not a failure)" )
        print( "  Start vLLM with Phi-4 and re-run." )
        return [], True

    entries = strategy._entries
    print( f"  Loaded {len( entries )} entries, LLM client created: {strategy.available}" )

    # Pre-flight connectivity check — verify vLLM actually responds
    print( "  Running pre-flight LLM check..." )
    if not _preflight_check( strategy, entries ):
        print( "\n  vLLM not responding -- skipping smoke test (this is not a failure)" )
        print( "  The LLM client was created but the server is unreachable." )
        print( "  Start vLLM with Phi-4 and re-run." )
        return [], True
    print( "  Pre-flight OK -- vLLM is responding\n" )

    # Build set of arg_names present in this script
    script_arg_names = { entry.get( "arg_name" ) for entry in entries }

    # ───────────────────────────────────────────────────────────────────────
    # Build applicable scenario list by tier
    # ───────────────────────────────────────────────────────────────────────
    all_scenarios = []
    idx = 0

    # Tier 1: Exact — auto-generated from script entries
    if tier in ( "exact", "all" ):
        exact_scenarios = _build_exact_scenarios( entries )
        for s in exact_scenarios:
            s[ "idx" ] = idx
            idx += 1
        all_scenarios.extend( exact_scenarios )

    # Tier 2: Fuzzy — static paraphrases, filtered by arg_name applicability
    if tier in ( "fuzzy", "all" ):
        for s in FUZZY_SCENARIOS:
            if s[ "arg_name" ] not in script_arg_names:
                continue

            # Look up expected answer from script entries
            expected = _lookup_expected_answer(
                s[ "arg_name" ], s[ "agent_context" ], entries
            )
            if expected is None:
                continue

            scenario             = dict( s )
            scenario[ "tier" ]   = "fuzzy"
            scenario[ "expected" ] = expected
            scenario[ "idx" ]    = idx
            idx += 1
            all_scenarios.append( scenario )

    # Tier 3: Multi — special response types + negative
    if tier in ( "multi", "all" ):
        for s in MULTI_SCENARIOS:
            # Skip if arg_name not in script (except None-arg scenarios)
            if s[ "arg_name" ] is not None and s[ "arg_name" ] not in script_arg_names:
                continue

            scenario           = dict( s )
            scenario[ "tier" ] = "multi"
            scenario[ "idx" ]  = idx
            idx += 1
            all_scenarios.append( scenario )

    # Filter by explicit scenario indices if specified
    if scenario_indices is not None:
        all_scenarios = [ s for s in all_scenarios if s[ "idx" ] in scenario_indices ]

    if not all_scenarios:
        print( "  No applicable scenarios for this script/tier combination." )
        return [], True

    print( f"  Running {len( all_scenarios )} scenarios...\n" )

    # ───────────────────────────────────────────────────────────────────────
    # Optional verifier for fuzzy tier second-pass
    # ───────────────────────────────────────────────────────────────────────
    verifier = None
    if verify:
        try:
            verifier = LlmAnswerVerifier( debug=debug, verbose=verbose )
            if not verifier.available:
                print( "  Verifier LLM unavailable -- disabling verification" )
                verifier = None
            else:
                print( "  Answer verifier enabled (second-pass semantic check on fuzzy tier)\n" )
        except Exception as e:
            print( f"  Verifier init failed: {e}" )
            verifier = None

    # ───────────────────────────────────────────────────────────────────────
    # Run scenarios
    # ───────────────────────────────────────────────────────────────────────
    results = []

    for scenario in all_scenarios:
        s_id            = scenario[ "id" ]
        s_tier          = scenario[ "tier" ]
        s_question      = scenario.get( "question" )
        s_expected      = scenario.get( "expected" )
        s_response_type = scenario[ "response_type" ]
        s_agent_ctx     = scenario.get( "agent_context" )
        s_idx           = scenario[ "idx" ]

        print( f"  [{s_idx:>2}] {s_tier:<6} {s_id}" )
        if debug and s_question:
            print( f"       Q: \"{s_question[ :70 ]}\"" )

        result = {
            "idx"            : s_idx,
            "tier"           : s_tier,
            "id"             : s_id,
            "status"         : "fail",
            "conf"           : "---",
            "answer_preview" : "",
            "time_s"         : 0,
        }

        start_time = time.time()

        try:
            # Build notification dict
            notification = _build_notification(
                question        = s_question,
                response_type   = s_response_type,
                agent_context   = s_agent_ctx,
                options         = scenario.get( "options" ),
                batch_questions = scenario.get( "batch_questions" ),
            )

            # Call strategy
            answer  = strategy.respond( notification )
            elapsed = time.time() - start_time
            result[ "time_s" ] = elapsed

            if debug: print( f"       Answer: {repr( answer )[ :80 ]}" )

            # Check answer against expected
            passed, details = _check_answer( answer, s_expected, s_response_type )

            if passed:
                result[ "status" ]         = "pass"
                result[ "answer_preview" ] = str( answer )[ :60 ] if answer else "(none)"
                result[ "conf" ]           = "1.0"

                # Optional verifier second-pass on fuzzy tier
                if s_tier == "fuzzy" and verifier and s_expected and answer:
                    v_result = verifier.verify(
                        str( s_expected ), str( answer ), context=s_question
                    )
                    v_conf = v_result.get_confidence_float()
                    result[ "conf" ] = f"{v_conf:.2f}"

                    if v_conf < min_confidence:
                        result[ "status" ] = "fail"
                        details = f"verifier confidence {v_conf:.2f} < {min_confidence}"
                        print( f"       FAIL: {details}" )
                    else:
                        print( f"       PASS ({details}, verifier: {v_conf:.2f}) [{elapsed:.1f}s]" )
                else:
                    print( f"       PASS ({details}) [{elapsed:.1f}s]" )
            else:
                result[ "status" ]         = "fail"
                result[ "answer_preview" ] = str( answer )[ :60 ] if answer else "(none)"
                print( f"       FAIL: {details} [{elapsed:.1f}s]" )

        except Exception as e:
            elapsed            = time.time() - start_time
            result[ "time_s" ] = elapsed
            result[ "status" ] = "fail"
            print( f"       ERROR: {e} [{elapsed:.1f}s]" )
            if debug: traceback.print_exc()

        results.append( result )

    return results, all( r[ "status" ] != "fail" for r in results )


# ═══════════════════════════════════════════════════════════════════════════════
# Main Test
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( script_scope="deep_research", tier="all", scenario_indices=None,
                      verify=True, min_confidence=0.7, debug=False, verbose=False ):
    """
    Smoke test for notification proxy script matching via live Phi-4 LLM.

    Requires:
        - vLLM server running with Phi-4 model loaded
        - LUPIN_ROOT environment variable set
        - script_scope is "deep_research", "expeditor_smoke", or "all"
        - tier is "exact", "fuzzy", "multi", or "all"

    Ensures:
        - Returns True if all scenarios pass (or if vLLM unavailable)
        - Returns False if any scenario fails
        - Prints tabular summary to console

    Args:
        script_scope: Which Q&A script(s) to test against
        tier: Which scenario tier(s) to run
        scenario_indices: Optional list of scenario indices to run
        verify: Enable LlmAnswerVerifier second-pass on fuzzy scenarios
        min_confidence: Minimum confidence threshold for verifier
        debug: Enable debug output
        verbose: Enable verbose output (full prompts and responses)
    """
    banner = f"Notification Proxy Script Matching Smoke Test (script={script_scope}, tier={tier})"
    if cu:
        cu.print_banner( banner, prepend_nl=True )
    else:
        print( f"\n{'=' * 80}" )
        print( f"  {banner}" )
        print( f"{'=' * 80}" )

    if script_scope == "all":
        scripts = [ "deep_research", "expeditor_smoke" ]
    else:
        scripts = [ script_scope ]

    all_results = []
    all_passed  = True

    for script_name in scripts:
        if len( scripts ) > 1:
            print( f"\n{'─' * 80}" )
            print( f"  Script: {script_name}" )
            print( f"{'─' * 80}" )

        results, passed = _run_single_script(
            script_name      = script_name,
            tier             = tier,
            scenario_indices = scenario_indices,
            verify           = verify,
            min_confidence   = min_confidence,
            debug            = debug,
            verbose          = verbose,
        )

        if results:
            _print_results_table( results, script_name )
            all_results.extend( results )

        if not passed:
            all_passed = False

    # Combined summary for "all" scope
    if len( scripts ) > 1 and all_results:
        print( f"\n{'=' * 80}" )
        total_passed  = sum( 1 for r in all_results if r[ "status" ] == "pass" )
        total_failed  = sum( 1 for r in all_results if r[ "status" ] == "fail" )
        total_skipped = sum( 1 for r in all_results if r[ "status" ] == "skip" )
        total_time    = sum( r.get( "time_s", 0 ) for r in all_results )

        parts = [ f"{total_passed} passed" ]
        if total_failed > 0:  parts.append( f"{total_failed} failed" )
        if total_skipped > 0: parts.append( f"{total_skipped} skipped" )

        print( f"  Combined: {', '.join( parts )} | Time: {total_time:.1f}s" )
        print( f"  Overall: {'PASS' if total_failed == 0 else 'FAIL'}" )
        print( "=" * 80 )

    return all_passed


def test_notification_proxy_script_matching():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Notification proxy script matching smoke test (live Phi-4)"
    )
    parser.add_argument(
        "--script", "-s",
        type=str,
        default="deep_research",
        choices=[ "deep_research", "expeditor_smoke", "all" ],
        help="Script scope: deep_research (5 entries, fast), "
             "expeditor_smoke (8 entries), all (both). Default: deep_research"
    )
    parser.add_argument(
        "--tier", "-t",
        type=str,
        default="all",
        choices=[ "exact", "fuzzy", "multi", "all" ],
        help="Tier to run: exact, fuzzy, multi, or all. Default: all"
    )
    parser.add_argument(
        "--scenarios", "-n",
        type=str,
        default=None,
        help="Comma-separated scenario indices to run (e.g., '0,8,20'). Default: all."
    )
    parser.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        default=True,
        help="Disable LlmAnswerVerifier second-pass on fuzzy scenarios"
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.7,
        help="Minimum confidence threshold for verifier, 0.0-1.0 (default: 0.7)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug output from strategy and verifier"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output (prompts, full LLM responses)"
    )
    args = parser.parse_args()

    indices = None
    if args.scenarios:
        indices = [ int( x.strip() ) for x in args.scenarios.split( "," ) ]

    try:
        success = quick_smoke_test(
            script_scope     = args.script,
            tier             = args.tier,
            scenario_indices = indices,
            verify           = args.verify,
            min_confidence   = args.confidence,
            debug            = args.debug,
            verbose          = args.verbose,
        )
        sys.exit( 0 if success else 1 )
    except Exception as e:
        print( f"\nFatal error: {e}" )
        traceback.print_exc()
        sys.exit( 1 )
