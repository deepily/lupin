#!/usr/bin/env python3
"""
LLM Fallback Strategy for unknown notification questions.

Uses the Anthropic SDK directly (AsyncAnthropic) to generate answers
for notifications that don't match any rule-based strategy.

References:
    - src/cosa/agents/deep_research/api_client.py (Anthropic SDK pattern)
"""

import asyncio
from typing import Optional

from cosa.agents.notification_proxy.config import (
    LLM_FALLBACK_MODEL,
    LLM_FALLBACK_MAX_TOKENS,
    get_anthropic_api_key,
)


class LLMFallbackStrategy:
    """
    Uses Anthropic SDK to generate answers for unknown notifications.

    Requires:
        - Anthropic API key available (env var or local file)

    Ensures:
        - can_handle() returns True for any response-requested notification
        - respond() returns an LLM-generated answer string
        - Returns None if API call fails or no key available
    """

    def __init__( self, debug=False, verbose=False ):
        """
        Initialize the LLM fallback strategy.

        Requires:
            - Anthropic SDK is installed

        Ensures:
            - Creates AsyncAnthropic client if API key is available
            - Sets self._available to False if no key found

        Args:
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.debug     = debug
        self.verbose   = verbose
        self._client   = None
        self._available = False

        api_key = get_anthropic_api_key()
        if api_key:
            try:
                from anthropic import AsyncAnthropic
                self._client    = AsyncAnthropic( api_key=api_key )
                self._available = True
                if self.debug: print( "[LLMFallback] Client initialized successfully" )
            except Exception as e:
                print( f"[LLMFallback] Failed to initialize Anthropic client: {e}" )
        else:
            if self.debug: print( "[LLMFallback] No API key found — fallback unavailable" )

    @property
    def available( self ):
        """Whether the LLM fallback is available (has API key and client)."""
        return self._available

    def can_handle( self, notification ):
        """
        Check if this strategy can handle the notification.

        Requires:
            - notification is a dict with 'response_requested' key

        Ensures:
            - Returns True if API client is available and response is requested
            - Returns False otherwise

        Args:
            notification: Notification event data dict

        Returns:
            bool: True if this strategy can attempt to answer
        """
        return self._available and notification.get( "response_requested", False )

    async def respond( self, notification ):
        """
        Generate an LLM response for the notification.

        Requires:
            - self._available is True
            - notification has 'message' field

        Ensures:
            - Returns a concise answer string
            - Returns None on API error or empty response

        Args:
            notification: Notification event data dict

        Returns:
            str or None: LLM-generated answer
        """
        if not self._available:
            return None

        message       = notification.get( "message", "" )
        abstract      = notification.get( "abstract", "" )
        response_type = notification.get( "response_type", "open_ended" )
        title         = notification.get( "title", "" )

        # Build prompt
        prompt = self._build_prompt( message, abstract, response_type, title )

        try:
            if self.debug: print( f"[LLMFallback] Calling {LLM_FALLBACK_MODEL} ({len( prompt )} chars)..." )

            response = await self._client.messages.create(
                model      = LLM_FALLBACK_MODEL,
                max_tokens = LLM_FALLBACK_MAX_TOKENS,
                messages   = [ {
                    "role"    : "user",
                    "content" : prompt
                } ]
            )

            # Extract text content
            answer = ""
            for block in response.content:
                if hasattr( block, "text" ):
                    answer += block.text

            answer = answer.strip()

            if self.debug:
                print( f"[LLMFallback] Response ({response.usage.input_tokens}+{response.usage.output_tokens} tokens): {answer[ :100 ]}" )

            return answer if answer else None

        except Exception as e:
            print( f"[LLMFallback] API call failed: {e}" )
            return None

    def _build_prompt( self, message, abstract, response_type, title ):
        """
        Build the LLM prompt for answering a notification question.

        Requires:
            - message is a string (the question)
            - abstract is a string (additional context, may be empty)
            - response_type is a string (yes_no, open_ended, etc.)

        Ensures:
            - Returns a focused prompt string
            - Includes response format guidance

        Args:
            message: The notification question
            abstract: Additional context
            response_type: Expected response format
            title: Notification title

        Returns:
            str: The prompt to send to the LLM
        """
        parts = [
            "You are an automated test agent responding to a notification question.",
            "Answer concisely and helpfully. Respond with ONLY the answer, no explanation.",
            "",
        ]

        if title:
            parts.append( f"Title: {title}" )
        parts.append( f"Question: {message}" )

        if abstract:
            parts.append( f"\nContext:\n{abstract}" )

        if response_type == "yes_no":
            parts.append( "\nRespond with exactly 'yes' or 'no'." )
        elif response_type == "open_ended":
            parts.append( "\nProvide a brief, direct answer (1-2 sentences max)." )
        elif response_type == "multiple_choice":
            parts.append( "\nRespond with exactly one of the option labels." )

        return "\n".join( parts )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for LLM fallback strategy."""
    print( "\n" + "=" * 60 )
    print( "LLM Fallback Strategy Smoke Test" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Construction
    print( "\n1. Testing construction..." )
    try:
        strategy = LLMFallbackStrategy( debug=True )
        if strategy.available:
            print( "   ✓ Client available (API key found)" )
        else:
            print( "   ⚠ Client unavailable (no API key — not a failure)" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: can_handle
    print( "\n2. Testing can_handle..." )
    try:
        strategy = LLMFallbackStrategy()

        result = strategy.can_handle( { "response_requested": True } )
        expected = strategy.available
        assert result == expected, f"Expected {expected}, got {result}"
        print( f"   ✓ can_handle returns {result} (available={strategy.available})" )

        assert not strategy.can_handle( { "response_requested": False } )
        print( "   ✓ Rejects non-response-requested" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: Prompt building
    print( "\n3. Testing prompt building..." )
    try:
        strategy = LLMFallbackStrategy()
        prompt = strategy._build_prompt(
            message       = "What topic would you like?",
            abstract      = "Agent: Deep Research",
            response_type = "open_ended",
            title         = "Missing: query"
        )
        assert "automated test agent" in prompt
        assert "What topic" in prompt
        assert "Deep Research" in prompt
        print( f"   ✓ Prompt built ({len( prompt )} chars)" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"LLM Fallback Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
