#!/usr/bin/env python3
"""
Configuration for the Notification Proxy Agent.

Defines test profiles with pre-configured answers for expediter questions,
agent defaults, and connection parameters.

Test profiles map argument names to auto-answers so the proxy can respond
deterministically to known expediter question patterns.

Shared connection and reconnection constants are imported from
cosa.agents.utils.proxy_agents.base_config and re-exported here for
backward compatibility.
"""

import os

# Re-export shared constants for backward compatibility
from cosa.agents.utils.proxy_agents.base_config import (   # noqa: F401
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_BACKOFF_FACTOR,
    get_credentials,
    get_anthropic_api_key,
)


# ============================================================================
# Notification-Proxy-Specific Defaults
# ============================================================================

DEFAULT_EMAIL      = "mock.tester@lupin.deepily.ai"
DEFAULT_SESSION_ID = "auto proxy"
DEFAULT_PROFILE    = "deep_research"

# WebSocket subscription events
SUBSCRIBED_EVENTS = [
    "notification_queue_update",
    "job_state_transition",
    "sys_ping"
]


# ============================================================================
# LLM Fallback Configuration
# ============================================================================

LLM_FALLBACK_MODEL      = "claude-sonnet-4-5-20250929"
LLM_FALLBACK_MAX_TOKENS = 500


# ============================================================================
# LLM Script Matcher Configuration
# ============================================================================

LLM_SCRIPT_MATCHER_SPEC_KEY        = "kaitchup/phi_4_14b"
LLM_SCRIPT_MATCHER_TEMPLATE        = "/src/conf/prompts/notification-proxy-script-matcher.txt"
LLM_SCRIPT_MATCHER_BATCH_TEMPLATE  = "/src/conf/prompts/notification-proxy-batch-matcher.txt"
LLM_ANSWER_VERIFIER_TEMPLATE       = "/src/conf/prompts/notification-proxy-answer-verifier.txt"
NOTIFICATION_PROXY_SCRIPTS_DIR     = "/src/conf/notification-proxy-scripts"

# Valid strategy choices for --strategy CLI flag
STRATEGY_CHOICES = [ "llm_script", "rules", "auto" ]
DEFAULT_STRATEGY = "llm_script"


# ============================================================================
# Test Profiles
# ============================================================================

TEST_PROFILES = {
    "deep_research" : {
        "description" : "Auto-answer for deep research agent expediter questions",
        "query"            : "quantum computing breakthroughs 2026",
        "budget"           : "no limit",
        "audience"         : "academic",
        "audience_context" : "none",
    },
    "podcast" : {
        "description" : "Auto-answer for podcast generator expediter questions",
        "research"         : "latest",
        "audience"         : "general",
        "audience_context" : "none",
        "languages"        : "en",
    },
    "research_to_podcast" : {
        "description" : "Auto-answer for research-to-podcast chained workflow",
        "query"            : "artificial intelligence safety research 2026",
        "budget"           : "no limit",
        "audience"         : "academic",
        "audience_context" : "none",
        "languages"        : "en,es-MX",
    },
    "all_agents" : {
        "description"              : "Union profile for automated testing across all agents",
        "query"                    : "quantum computing breakthroughs 2026",
        "budget"                   : "no limit",
        "audience"                 : "academic",
        "audience_context"         : "none",
        "research"                 : "/tmp/mock-research-document.md",
        "languages"                : "en",
        "prompt"                   : "fix the authentication bug in the login endpoint",
        "project"                  : "lupin",
        "task"                     : "add a health check endpoint to the API",
        "timeout"                  : "default",
        "dry_run"                  : "yes",
        "source"                   : "/tmp/mock-source-document.md",
        "target_duration_minutes"  : "15",
        "target_slide_count"       : "default",
        "theme"                    : "default",
        "dead_job_id"              : "dr-mock1234::user1",
        "resume_from"              : "tfe-mock1234::user1",
        "extra_context"            : "none",
        "pytest_args"              : "none",
        "test_types"               : "integration,e2e",
        "suites"                   : "all",
    },
    "presentation" : {
        "description"             : "Auto-answer for presentation generator expediter questions",
        "source"                  : "/tmp/mock-source-document.md",
        "target_duration_minutes" : "default",
        "target_slide_count"      : "default",
        "audience"                : "general",
        "audience_context"        : "none",
        "theme"                   : "default",
    },
    "presentation_gates" : {
        "description"             : "Auto-approve presentation generator orchestrator gates 1-4 (Phase D live E2E)",
    },
    "research_to_presentation" : {
        "description"             : "Auto-answer for research-to-presentation chained workflow",
        "query"                   : "artificial intelligence safety 2026",
        "budget"                  : "no limit",
        "target_duration_minutes" : "default",
        "theme"                   : "default",
        "audience"                : "academic",
        "audience_context"        : "none",
    },
    "swe_team" : {
        "description"      : "Auto-answer for SWE Team agent expediter questions",
        "task"             : "add a health check endpoint to the API",
        "budget"           : "no limit",
        "timeout"          : "default",
        "dry_run"          : "yes",
    },
    "expeditor_smoke" : {
        "description"      : "Q&A answers for expeditor smoke test matrix",
        "query"            : "quantum computing breakthroughs 2026",
        "budget"           : "no limit",
        "audience"         : "academic",
        "audience_context" : "none",
        "research"         : "/tmp/mock-research-document.md",
        "languages"        : "en",
        "prompt"           : "fix the authentication bug in the login endpoint",
        "project"          : "lupin",
    },
    "minimal" : {
        "description" : "Bare minimum answers — required args only, skip optionals",
        "query"    : "test query for automated proxy",
        "research" : "latest",
    },
    "crud" : {
        "description"  : "Auto-confirm for CRUD agent delete/update operations",
        "confirmation" : "yes",
    },
    "test_suite" : {
        "description"  : "Auto-answer for test suite agent expediter questions",
        "test_types"   : "integration,e2e",
        "pytest_args"  : "none",
        "dry_run"      : "no",
    },
    "proxy_integration_test" : {
        "description"             : "Union profile for proxy integration tests (expediter + CRUD)",
        "query"                   : "quantum computing breakthroughs 2026",
        "budget"                  : "no limit",
        "audience"                : "academic",
        "audience_context"        : "none",
        "research"                : "/tmp/mock-research-document.md",
        "languages"               : "en",
        "confirmation"            : "yes",
        "source"                  : "/tmp/mock-source-document.md",
        "target_duration_minutes" : "default",
        "target_slide_count"      : "default",
        "theme"                   : "default",
    },
}


# ============================================================================
# Known Expediter Sender IDs
# ============================================================================

DEFAULT_ACCEPTED_SENDERS = [ "arg.expeditor@lupin.deepily.ai" ]

# Deprecated alias — kept for backward compatibility in smoke tests
EXPEDITER_SENDER_ID = DEFAULT_ACCEPTED_SENDERS[ 0 ]


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for config module."""
    print( "\n" + "=" * 60 )
    print( "Notification Proxy Config Smoke Test" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Profiles exist
    print( "\n1. Testing profile structure..." )
    try:
        assert len( TEST_PROFILES ) >= 3, f"Expected >= 3 profiles, got {len( TEST_PROFILES )}"
        for name, profile in TEST_PROFILES.items():
            assert "description" in profile, f"Profile '{name}' missing description"
            print( f"   ✓ Profile '{name}': {profile[ 'description' ]}" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: Connection defaults
    print( "\n2. Testing connection defaults..." )
    try:
        assert DEFAULT_SERVER_PORT == 7999
        assert DEFAULT_EMAIL == "mock.tester@lupin.deepily.ai"
        assert len( SUBSCRIBED_EVENTS ) >= 3
        print( f"   ✓ Server: {DEFAULT_SERVER_HOST}:{DEFAULT_SERVER_PORT}" )
        print( f"   ✓ Email: {DEFAULT_EMAIL}" )
        print( f"   ✓ Events: {SUBSCRIBED_EVENTS}" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: API key resolution
    print( "\n3. Testing API key resolution..." )
    try:
        key = get_anthropic_api_key()
        if key:
            print( f"   ✓ API key found ({len( key )} chars, source: env or file)" )
        else:
            print( "   ⚠ No API key found (LLM fallback will be unavailable)" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"Config Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
