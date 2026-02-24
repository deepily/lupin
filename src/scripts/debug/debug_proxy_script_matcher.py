#!/usr/bin/env python3
"""
Standalone diagnostic: reproduce the exact Phi-4 script-matching call
the notification proxy makes for CRUD delete confirmation.

The existing debug_crud_llm_call.py tests CRUD agent *intent extraction*.
This script tests the proxy's *script matching* path — a completely
different prompt and model interaction.

5 diagnostic steps:
  1. Load crud.json Q&A script
  2. Create LlmScriptMatcherStrategy, check availability
  3. Simulate the exact notification the CRUD agent sends
  4. Test can_handle() — verify sender matching
  5. Call respond() — capture prompt, raw response, parsed result

Usage:
    export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
    export LUPIN_ROOT="/mnt/DATA01/include/www.deepily.ai/projects/lupin"
    python src/scripts/debug/debug_proxy_script_matcher.py
"""

import json
import sys
import os
import traceback

# Bootstrap
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu

from cosa.agents.notification_proxy.strategies.llm_script_matcher import (
    LlmScriptMatcherStrategy,
    resolve_script_path,
)
from cosa.agents.notification_proxy.xml_models import ScriptMatcherResponse


# ============================================================================
# Helpers
# ============================================================================

def banner( step_num, title ):
    """Print a numbered step banner."""
    print()
    print( "=" * 80 )
    print( f"  STEP {step_num}: {title}" )
    print( "=" * 80 )


def pass_fail( label, passed ):
    """Print pass/fail indicator."""
    icon = "PASS" if passed else "FAIL"
    print( f"  [{icon}] {label}" )
    return passed


# ============================================================================
# STEP 1: Load crud.json
# ============================================================================

banner( 1, "Load crud.json Q&A script" )

script_path = resolve_script_path( "crud" )
print( f"  Script path: {script_path}" )
print( f"  File exists: {os.path.exists( script_path )}" )

try:
    with open( script_path, "r" ) as f:
        script_data = json.load( f )

    entries = script_data.get( "entries", [] )
    print( f"  Profile name: {script_data.get( 'profile_name', '?' )}" )
    print( f"  Sender IDs: {script_data.get( 'sender_ids', [] )}" )
    print( f"  Entry count: {len( entries )}" )
    print()
    for i, entry in enumerate( entries ):
        print( f"    [{i}] pattern : \"{entry.get( 'question_pattern', '' )}\"" )
        print( f"        answer  : \"{entry.get( 'answer', '' )}\"" )
        print( f"        arg     : {entry.get( 'arg_name', '' )}" )
        print( f"        types   : {entry.get( 'response_types', [] )}" )
    step1_ok = pass_fail( "crud.json loaded successfully", len( entries ) >= 2 )
except Exception as e:
    print( f"  ERROR loading crud.json: {e}" )
    traceback.print_exc()
    step1_ok = False
    pass_fail( "crud.json loaded", False )

# ============================================================================
# STEP 2: Create LlmScriptMatcherStrategy
# ============================================================================

banner( 2, "Create LlmScriptMatcherStrategy" )

strategy = None
try:
    strategy = LlmScriptMatcherStrategy(
        script_path = script_path,
        debug       = True,
        verbose     = True,
    )
    print( f"  LLM available   : {strategy.available}" )
    print( f"  LLM spec key    : {strategy.llm_spec_key}" )
    print( f"  Accepted senders: {strategy.accepted_senders}" )
    print( f"  Entry count     : {len( strategy._entries )}" )
    print( f"  Client type     : {type( strategy._client ).__name__ if strategy._client else 'None'}" )

    step2_ok = pass_fail( "Strategy created", True )

    if not strategy.available:
        print()
        print( "  WARNING: LLM client is NOT available." )
        print( "  Phi-4 vLLM server may not be running." )
        print( "  Steps 4-5 will fail gracefully." )
        pass_fail( "LLM client available", False )
    else:
        pass_fail( "LLM client available", True )

except Exception as e:
    print( f"  ERROR creating strategy: {e}" )
    traceback.print_exc()
    step2_ok = False
    pass_fail( "Strategy created", False )

# ============================================================================
# STEP 3: Simulate the exact CRUD delete notification
# ============================================================================

banner( 3, "Simulate CRUD delete notification" )

notification = {
    "message"            : "Are you sure you want to delete from grocery list?",
    "title"              : "",
    "sender_id"          : "crud.agent@lupin.deepily.ai",
    "response_type"      : "yes_no",
    "response_requested" : True,
}

print( "  Notification fields:" )
for k, v in notification.items():
    print( f"    {k:22s} : {repr( v )}" )

step3_ok = pass_fail( "Notification dict constructed", True )

# ============================================================================
# STEP 4: Test can_handle()
# ============================================================================

banner( 4, "Test can_handle()" )

if strategy is not None:
    can_handle = strategy.can_handle( notification )
    print( f"  can_handle() returned: {can_handle}" )

    if not can_handle:
        print()
        print( "  DIAGNOSIS: can_handle() returned False. Checking why..." )
        print( f"    available          : {strategy.available}" )
        print( f"    response_requested : {notification.get( 'response_requested' )}" )
        sender_id   = notification.get( "sender_id", "" )
        sender_base = sender_id.split( "#" )[ 0 ]
        print( f"    sender_id          : {sender_id}" )
        print( f"    sender_base        : {sender_base}" )
        print( f"    accepted_senders   : {strategy.accepted_senders}" )
        is_accepted = any( sender_base == prefix for prefix in strategy.accepted_senders )
        print( f"    sender accepted?   : {is_accepted}" )
        if not is_accepted:
            print()
            print( "  ROOT CAUSE: Sender ID mismatch!" )
            print( f"    Expected one of: {strategy.accepted_senders}" )
            print( f"    Got: {sender_base}" )

    step4_ok = pass_fail( "can_handle() returns True", can_handle )
else:
    print( "  SKIPPED: Strategy not created (see Step 2)" )
    step4_ok = False
    pass_fail( "can_handle()", False )

# ============================================================================
# STEP 5: Call respond() — the main diagnostic
# ============================================================================

banner( 5, "Call respond() with debug + verbose" )

if strategy is not None and strategy.available:

    # Monkey-patch _client.run() to capture the prompt and raw response
    original_run = strategy._client.run
    captured      = { "prompt": None, "raw": None }

    def instrumented_run( prompt, **kwargs ):
        captured[ "prompt" ] = prompt
        print( "  --- FULL EXPANDED PROMPT ---" )
        print( prompt )
        print( "  --- END PROMPT ---" )
        print( f"  Prompt length: {len( prompt )} chars" )
        print()

        result = original_run( prompt, **kwargs )
        captured[ "raw" ] = result
        return result

    strategy._client.run = instrumented_run

    # Call respond()
    print( "  Calling strategy.respond()..." )
    print()
    try:
        answer = strategy.respond( notification )

        print()
        print( "  --- RAW LLM RESPONSE ---" )
        if captured[ "raw" ] is not None:
            print( f"  Length: {len( captured[ 'raw' ] )} chars" )
            print( captured[ "raw" ] )
        else:
            print( "  (No raw response captured — run() may not have been called)" )
        print( "  --- END RAW RESPONSE ---" )
        print()

        # Try to parse separately to see XML parsing details
        if captured[ "raw" ] is not None:
            print( "  --- XML PARSING DIAGNOSTIC ---" )
            try:
                parsed = ScriptMatcherResponse.from_xml( captured[ "raw" ] )
                print( f"  matched_entry : {repr( parsed.matched_entry )}" )
                print( f"  answer        : {repr( parsed.answer )}" )
                print( f"  confidence    : {repr( parsed.confidence )} ({parsed.get_confidence_float():.2f})" )
                print( f"  reasoning     : {repr( parsed.reasoning[ :200 ] )}" )
                print( f"  is_match()    : {parsed.is_match()}" )
            except Exception as parse_err:
                print( f"  XML PARSE ERROR: {parse_err}" )
                print( f"  This means Phi-4 returned malformed XML." )
                traceback.print_exc()
            print( "  --- END XML PARSING ---" )

        print()
        print( f"  Final answer from respond(): {repr( answer )}" )

        if answer is not None:
            step5_ok = pass_fail( "respond() returned an answer", True )
            pass_fail( f"Answer is '{answer}'", answer.strip().lower() == "yes" )
        else:
            step5_ok = False
            pass_fail( "respond() returned an answer", False )
            print()
            print( "  DIAGNOSIS: respond() returned None. Possible causes:" )
            print( "    1. Phi-4 returned matched_entry='none'" )
            print( "    2. Phi-4 returned empty answer" )
            print( "    3. XML parsing failed (malformed response)" )
            print( "    4. LLM call raised an exception" )

    except Exception as e:
        print( f"  EXCEPTION during respond(): {e}" )
        traceback.print_exc()
        step5_ok = False
        pass_fail( "respond() completed", False )

    # Restore original
    strategy._client.run = original_run

elif strategy is not None and not strategy.available:
    print( "  SKIPPED: LLM client not available (Phi-4 server may be down)" )
    step5_ok = False
    pass_fail( "respond()", False )
else:
    print( "  SKIPPED: Strategy not created (see Step 2)" )
    step5_ok = False
    pass_fail( "respond()", False )

# ============================================================================
# Summary
# ============================================================================

print()
print( "=" * 80 )
print( "  DIAGNOSTIC SUMMARY" )
print( "=" * 80 )

results = [
    ( "Load crud.json",           step1_ok ),
    ( "Create strategy",          step2_ok ),
    ( "Build notification",       step3_ok ),
    ( "can_handle()",             step4_ok ),
    ( "respond() → answer",       step5_ok ),
]

all_passed = True
for label, ok in results:
    icon = "PASS" if ok else "FAIL"
    print( f"  [{icon}] Step {results.index( ( label, ok ) ) + 1}: {label}" )
    if not ok:
        all_passed = False

print()
if all_passed:
    print( "  All 5 steps passed. Phi-4 script matching is working correctly." )
else:
    print( "  One or more steps failed. Review output above for root cause." )
print( "=" * 80 )
