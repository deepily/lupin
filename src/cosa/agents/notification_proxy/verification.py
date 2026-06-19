#!/usr/bin/env python3
"""
LLM-based answer verification for semantic equivalence scoring.

Uses Phi-4 to compare expected vs actual answers during automated testing,
replacing brittle exact string comparison with semantic understanding.

References:
    - src/cosa/agents/notification_proxy/xml_models.py (VerificationResponse)
    - src/conf/prompts/notification-proxy-answer-verifier.txt (prompt template)
"""

import time

import cosa.utils.util as cu
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.notification_proxy.xml_models import VerificationResponse
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor


class LlmAnswerVerifier:
    """
    Verify semantic equivalence between expected and actual answers using Phi-4.

    Optimization: exact string matches (case-insensitive, stripped) skip the
    LLM call entirely and return a perfect-confidence match.

    Requires:
        - vLLM server running with Phi-4 model loaded

    Ensures:
        - verify() returns a VerificationResponse
        - Exact matches bypass LLM for speed
        - Graceful failure returns a "false" VerificationResponse on errors
    """

    def __init__(
        self,
        llm_spec_key         = "kaitchup/phi_4_14b",
        prompt_template_path = "/src/conf/prompts/notification-proxy-answer-verifier.txt",
        debug                = False,
        verbose              = False
    ):
        """
        Initialize the verifier with LLM configuration.

        Requires:
            - llm_spec_key is a valid model key in LlmClientFactory

        Ensures:
            - Creates LLM client and prompt template processor
            - Sets available=True if LLM client can be created

        Args:
            llm_spec_key: Model identifier for LlmClientFactory
            prompt_template_path: Path (relative to project root) for verifier template
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.debug               = debug
        self.verbose             = verbose
        self.llm_spec_key        = llm_spec_key
        self.prompt_template_path = prompt_template_path
        self._available          = False
        self._client             = None

        # Create LLM client
        try:
            factory = LlmClientFactory( debug=debug, verbose=verbose )
            self._client = factory.get_client( llm_spec_key, debug=debug, verbose=verbose )
            self._available = True
            if self.debug: print( f"[AnswerVerifier] LLM client ready ({llm_spec_key})" )
        except Exception as e:
            print( f"[AnswerVerifier] LLM client unavailable: {e}" )
            self._available = False

        # Prompt template processor
        self._processor = PromptTemplateProcessor( debug=debug, verbose=verbose )

    @property
    def available( self ):
        """Whether the LLM client is available for verification."""
        return self._available

    def verify( self, expected, actual, context="" ):
        """
        Compare expected vs actual answers for semantic equivalence.

        Requires:
            - expected and actual are strings
            - context is an optional question description

        Ensures:
            - Returns VerificationResponse with match/confidence/reasoning
            - Exact string matches (case-insensitive) bypass LLM
            - Returns false match on LLM errors

        Args:
            expected: The expected answer string
            actual: The actual answer string
            context: Optional question context for the LLM

        Returns:
            VerificationResponse: Verification result
        """
        # Optimization: exact match bypasses LLM
        if expected.strip().lower() == actual.strip().lower():
            if self.debug: print( f"[AnswerVerifier] Exact match — skipping LLM" )
            return VerificationResponse(
                match      = "true",
                confidence = "1.0",
                reasoning  = "Exact string match (case-insensitive)"
            )

        if not self._available:
            if self.debug: print( "[AnswerVerifier] LLM unavailable — returning false" )
            return VerificationResponse(
                match      = "false",
                confidence = "0.0",
                reasoning  = "LLM unavailable for semantic comparison"
            )

        # Load and process prompt template
        template_raw = cu.get_file_as_string(
            cu.get_project_root() + self.prompt_template_path
        )
        template_processed = self._processor.process_template(
            template_raw, "notification proxy answer verifier"
        )

        # Fill runtime placeholders
        prompt = template_processed.format(
            question_context = context,
            expected         = expected,
            actual           = actual
        )

        if self.debug and self.verbose:
            print( f"[AnswerVerifier] Prompt length: {len( prompt )} chars" )

        # Send to LLM. Up to 2 retries on transient empty/malformed-XML failures —
        # vLLM occasionally returns whitespace or truncated XML under load.
        # 3 attempts with gentle backoff (0.5s, 1.0s) absorb transient hiccups
        # without inflating cost. System-boundary retry policy, not defensive cargo.
        # Bumped from 2-attempt to 3-attempt 2026-04-30 (Session b195a160) after
        # FUZZY_BUDGET_2 failed both attempts on 2026-04-29 17:39 EDT all-test run.
        last_error = None
        max_attempts = 3
        for attempt in range( 1, max_attempts + 1 ):
            try:
                response_text = self._client.run( prompt )
                if self.debug: print( f"[AnswerVerifier] Raw response (attempt {attempt}): {response_text[ :200 ]}" )

                parsed = VerificationResponse.from_xml( response_text )

                if self.debug:
                    print( f"[AnswerVerifier] match={parsed.match}, confidence={parsed.confidence}, "
                           f"reasoning={parsed.reasoning[ :80 ]}" )

                return parsed

            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    backoff = 0.5 * attempt   # 0.5s, 1.0s — gentle, bounded
                    print( f"[AnswerVerifier] LLM transient on attempt {attempt}, retrying in {backoff}s: {e}" )
                    time.sleep( backoff )
                    continue
                print( f"[AnswerVerifier] LLM error after {max_attempts} attempts: {e}" )

        return VerificationResponse(
            match      = "false",
            confidence = "0.0",
            reasoning  = f"LLM error after {max_attempts} attempts: {last_error}"
        )

    def verify_batch( self, pairs, context="" ):
        """
        Verify multiple expected/actual pairs.

        Requires:
            - pairs is a list of (expected, actual) tuples
            - context is optional question description

        Ensures:
            - Returns list of VerificationResponse objects, one per pair
            - Each pair is verified independently

        Args:
            pairs: List of (expected, actual) string tuples
            context: Optional shared question context

        Returns:
            list: List of VerificationResponse objects
        """
        results = []
        for expected, actual in pairs:
            result = self.verify( expected, actual, context )
            results.append( result )
        return results


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for LLM answer verifier."""
    print( "\n" + "=" * 60 )
    print( "LLM Answer Verifier Smoke Test" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Construction
    print( "\n1. Testing construction..." )
    try:
        verifier = LlmAnswerVerifier( debug=True )
        print( f"   ✓ Constructed (LLM available: {verifier.available})" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: Exact match bypass
    print( "\n2. Testing exact match bypass..." )
    try:
        verifier = LlmAnswerVerifier( debug=True )
        result = verifier.verify( "academic", "Academic" )
        assert result.is_match()
        assert result.get_confidence_float() == 1.0
        print( "   ✓ Case-insensitive exact match returns true with 1.0 confidence" )

        result = verifier.verify( "  no limit  ", "no limit" )
        assert result.is_match()
        print( "   ✓ Whitespace-stripped exact match returns true" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: Batch verification
    print( "\n3. Testing batch verification..." )
    try:
        verifier = LlmAnswerVerifier( debug=True )
        pairs = [
            ( "academic", "Academic" ),
            ( "no limit", "no limit" ),
        ]
        results = verifier.verify_batch( pairs )
        assert len( results ) == 2
        assert all( r.is_match() for r in results )
        print( f"   ✓ Batch verified {len( results )} pairs" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"Answer Verifier Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
