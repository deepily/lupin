#!/usr/bin/env python3
"""
Rule-based response strategy for known Runtime Argument Expediter patterns.

Matches notification messages against known question patterns from the
agent_registry and provides deterministic answers from the active test profile.

References:
    - src/cosa/agents/runtime_argument_expeditor/agent_registry.py (AGENTIC_AGENTS)
    - src/cosa/agents/runtime_argument_expeditor/expeditor.py (question flow)
"""

import json
import re
from typing import Optional

from cosa.agents.notification_proxy.config import TEST_PROFILES, DEFAULT_ACCEPTED_SENDERS


# ============================================================================
# Keyword → Argument Name Mapping
# ============================================================================

# Maps keywords found in notification messages/titles to profile arg names.
# Order matters: first match wins.
KEYWORD_TO_ARG = [
    ( [ "topic", "query" ],                                              "query" ),
    ( [ "budget", "limit", "dollar" ],                                   "budget" ),
    ( [ "audience context", "additional context" ],                       "audience_context" ),
    ( [ "audience", "target" ],                                          "audience" ),
    ( [ "language", "iso code" ],                                        "languages" ),
    ( [ "document", "filename", "which research", "podcast", "research" ], "research" ),
]


class ExpediterRuleStrategy:
    """
    Rule-based auto-responder for Runtime Argument Expediter notifications.

    Matches notifications by sender_id and keyword patterns in the message,
    then returns answers from the active test profile.

    Requires:
        - profile_name is a key in TEST_PROFILES

    Ensures:
        - can_handle() returns True for accepted sender notifications that need a response
        - respond() returns a string answer or dict for batch questions
        - Returns None if no matching rule is found
    """

    def __init__( self, profile_name="deep_research", accepted_senders=None, debug=False, verbose=False ):
        """
        Initialize with a test profile.

        Requires:
            - profile_name is a key in TEST_PROFILES

        Ensures:
            - Loads the profile answers
            - Sets accepted_senders from parameter or falls back to DEFAULT_ACCEPTED_SENDERS
            - Raises KeyError if profile not found

        Args:
            profile_name: Key in TEST_PROFILES
            accepted_senders: List of sender ID prefixes to accept (default: DEFAULT_ACCEPTED_SENDERS)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        if profile_name not in TEST_PROFILES:
            raise KeyError( f"Unknown profile '{profile_name}'. Available: {list( TEST_PROFILES.keys() )}" )

        self.profile_name     = profile_name
        self.profile          = TEST_PROFILES[ profile_name ]
        self.accepted_senders = accepted_senders if accepted_senders is not None else DEFAULT_ACCEPTED_SENDERS
        self.debug            = debug
        self.verbose          = verbose

    def can_handle( self, notification ):
        """
        Check if this strategy can handle the notification.

        Requires:
            - notification is a dict with at least 'sender_id' and 'response_requested'

        Ensures:
            - Returns True if sender matches any accepted sender prefix and response is requested
            - Returns False otherwise

        Args:
            notification: Notification event data dict

        Returns:
            bool: True if this strategy should handle this notification
        """
        sender_id          = notification.get( "sender_id", "" )
        response_requested = notification.get( "response_requested", False )

        if not response_requested:
            return False

        # Check sender against accepted list (prefix match, ignoring #suffix)
        sender_base = sender_id.split( "#" )[ 0 ]
        is_accepted = any( sender_base == prefix for prefix in self.accepted_senders )

        return is_accepted

    def respond( self, notification ):
        """
        Generate a response for the notification using rules.

        Requires:
            - notification is a dict with 'message', 'response_type', etc.
            - can_handle( notification ) returned True

        Ensures:
            - Returns string answer for OPEN_ENDED / YES_NO notifications
            - Returns dict answer for OPEN_ENDED_BATCH notifications
            - Returns None if no matching rule found

        Args:
            notification: Notification event data dict

        Returns:
            str or dict or None: The auto-answer, or None if no rule matches
        """
        response_type = notification.get( "response_type", "" )
        message       = notification.get( "message", "" ).lower()
        title         = notification.get( "title", "" ).lower()
        search_text   = f"{title} {message}"

        if self.debug:
            print( f"[ExpediterRules] response_type={response_type}, title={title!r}, message={message[ :80 ]!r}" )

        # YES_NO: always confirm
        if response_type == "yes_no":
            if self.debug: print( "[ExpediterRules] YES_NO → answering 'yes'" )
            return "yes"

        # OPEN_ENDED_BATCH: return a dict mapping headers to profile values
        if response_type == "open_ended_batch":
            return self._handle_batch( notification )

        # OPEN_ENDED: match by keyword
        if response_type == "open_ended":
            return self._match_keyword( search_text )

        # MULTIPLE_CHOICE: pick first option
        if response_type == "multiple_choice":
            options = notification.get( "response_options", {} )
            questions = options.get( "questions", [] )
            if questions and questions[ 0 ].get( "options" ):
                first_label = questions[ 0 ][ "options" ][ 0 ].get( "label", "" )
                if self.debug: print( f"[ExpediterRules] MULTIPLE_CHOICE → picking first: {first_label}" )
                return first_label
            return None

        if self.debug: print( f"[ExpediterRules] Unknown response_type: {response_type}" )
        return None

    def _match_keyword( self, search_text ):
        """
        Match search text against keyword patterns and return profile value.

        Requires:
            - search_text is a lowercase string

        Ensures:
            - Returns profile value for first matching keyword group
            - Returns None if no keywords match

        Args:
            search_text: Lowercase concatenation of title + message

        Returns:
            str or None: Profile answer for the matched argument
        """
        for keywords, arg_name in KEYWORD_TO_ARG:
            for keyword in keywords:
                if keyword in search_text:
                    value = self.profile.get( arg_name )
                    if value:
                        if self.debug: print( f"[ExpediterRules] Keyword '{keyword}' → {arg_name}={value}" )
                        return value

        if self.debug: print( f"[ExpediterRules] No keyword match in: {search_text[ :100 ]}" )
        return None

    def _handle_batch( self, notification ):
        """
        Handle OPEN_ENDED_BATCH notifications by mapping headers to profile values.

        Requires:
            - notification has 'response_options' with 'questions' list
            - Each question has a 'header' field

        Ensures:
            - Returns dict mapping headers to profile values
            - Falls back to keyword matching for unknown headers
            - Returns None if no answers can be generated

        Args:
            notification: Notification event data dict

        Returns:
            dict or None: Answers dict or None
        """
        options   = notification.get( "response_options", {} )
        questions = options.get( "questions", [] )

        if not questions:
            if self.debug: print( "[ExpediterRules] BATCH: no questions found" )
            return None

        answers = {}
        for q in questions:
            header = q.get( "header", "" )

            # Direct profile match by header name
            value = self.profile.get( header )
            if value:
                answers[ header ] = value
                continue

            # Keyword fallback using question text
            question_text = q.get( "question", "" ).lower()
            search_text   = f"{header.lower()} {question_text}"
            value = self._match_keyword( search_text )
            if value:
                answers[ header ] = value
                continue

            # Use default_value from question if available
            default = q.get( "default_value" )
            if default:
                answers[ header ] = default
                continue

            if self.debug: print( f"[ExpediterRules] BATCH: no answer for header '{header}'" )

        if not answers:
            return None

        if self.debug: print( f"[ExpediterRules] BATCH answers: {answers}" )

        # Format as JSON string matching the expected response format
        return json.dumps( { "answers": answers } )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for expediter rule strategy."""
    print( "\n" + "=" * 60 )
    print( "Expediter Rule Strategy Smoke Test" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Construction with valid profile
    print( "\n1. Testing construction..." )
    try:
        strategy = ExpediterRuleStrategy( "deep_research", debug=True )
        assert strategy.profile_name == "deep_research"
        print( "   ✓ Constructed with deep_research profile" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: can_handle
    print( "\n2. Testing can_handle..." )
    try:
        strategy = ExpediterRuleStrategy( "deep_research" )

        # Should handle expediter notifications
        assert strategy.can_handle( {
            "sender_id"          : DEFAULT_ACCEPTED_SENDERS[ 0 ],
            "response_requested" : True
        } )
        print( "   ✓ Handles expediter notifications" )

        # Should NOT handle non-expediter
        assert not strategy.can_handle( {
            "sender_id"          : "claude.code@lupin.deepily.ai",
            "response_requested" : True
        } )
        print( "   ✓ Rejects non-expediter notifications" )

        # Should NOT handle non-response-requested
        assert not strategy.can_handle( {
            "sender_id"          : DEFAULT_ACCEPTED_SENDERS[ 0 ],
            "response_requested" : False
        } )
        print( "   ✓ Rejects non-response-requested notifications" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: YES_NO always returns "yes"
    print( "\n3. Testing YES_NO auto-confirm..." )
    try:
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type" : "yes_no",
            "message"       : "Does this look right?",
            "title"         : "Confirm"
        } )
        assert answer == "yes"
        print( "   ✓ YES_NO returns 'yes'" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 4: OPEN_ENDED keyword matching
    print( "\n4. Testing OPEN_ENDED keyword matching..." )
    try:
        strategy = ExpediterRuleStrategy( "deep_research" )

        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What topic would you like me to research?",
            "title"         : "Missing: query"
        } )
        assert answer == "quantum computing breakthroughs 2026"
        print( f"   ✓ Query: {answer}" )

        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "Would you like to set a budget limit?",
            "title"         : "Missing: budget"
        } )
        assert answer == "no limit"
        print( f"   ✓ Budget: {answer}" )

        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "Who is the target audience?",
            "title"         : "Missing: audience"
        } )
        assert answer == "academic"
        print( f"   ✓ Audience: {answer}" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 5: Invalid profile
    print( "\n5. Testing invalid profile..." )
    try:
        ExpediterRuleStrategy( "nonexistent" )
        print( "   ✗ Should have raised KeyError" )
        tests_failed += 1
    except KeyError:
        print( "   ✓ Raises KeyError for unknown profile" )
        tests_passed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"Expediter Rules Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
