"""
Unit tests for cosa.agents.llm_exceptions.

ISOLATED dedicated test file — imports llm_exceptions directly with NO test-
infrastructure dependency, deliberately sidestepping the pre-existing harness
bug in test_data_types_and_exceptions.py (bare `from unit_test_utilities import`
+ `sys.exit(1)` on ImportError, which crashes collection under --cov).

Covers the full LLM exception hierarchy: base LlmError (message / error_code /
metadata-default), the bare-pass subclasses (inheritance), and the custom-__init__
subclasses LlmAPIError (status_code / response_body / kwargs pass-through) and
LlmRateLimitError (retry_after).

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, agents Tier-2, LLM-support lane).
"""

import unittest

from cosa.agents.llm_exceptions import (
    LlmError,
    LlmConfigError,
    LlmAPIError,
    LlmTimeoutError,
    LlmAuthenticationError,
    LlmRateLimitError,
    LlmModelError,
    LlmStreamingError,
    LlmValidationError,
)


class TestLlmError( unittest.TestCase ):
    def test_message_only_defaults( self ):
        """message stored; error_code None; metadata defaults to {}."""
        err = LlmError( "boom" )
        self.assertEqual( str( err ), "boom" )
        self.assertIsNone( err.error_code )
        self.assertEqual( err.metadata, {} )

    def test_with_error_code_and_metadata( self ):
        """Provided error_code + metadata are stored verbatim (metadata-truthy arm)."""
        err = LlmError( "boom", error_code="E42", metadata={ "k": "v" } )
        self.assertEqual( err.error_code, "E42" )
        self.assertEqual( err.metadata, { "k": "v" } )

    def test_is_exception( self ):
        with self.assertRaises( LlmError ):
            raise LlmError( "x" )


class TestPassSubclasses( unittest.TestCase ):
    """The bare-pass subclasses inherit LlmError behavior + identity."""

    def test_inheritance( self ):
        for cls in ( LlmConfigError, LlmTimeoutError, LlmModelError,
                     LlmStreamingError, LlmValidationError ):
            err = cls( "msg", error_code="C1" )
            self.assertIsInstance( err, LlmError )
            self.assertEqual( err.error_code, "C1" )
            self.assertEqual( str( err ), "msg" )


class TestLlmAPIError( unittest.TestCase ):
    def test_defaults( self ):
        err = LlmAPIError( "api down" )
        self.assertIsInstance( err, LlmError )
        self.assertIsNone( err.status_code )
        self.assertIsNone( err.response_body )

    def test_with_http_context_and_kwargs( self ):
        """status_code + response_body stored; error_code/metadata pass through to super via kwargs."""
        err = LlmAPIError(
            "api down", status_code=503, response_body="unavailable",
            error_code="E_API", metadata={ "url": "/x" }
        )
        self.assertEqual( err.status_code, 503 )
        self.assertEqual( err.response_body, "unavailable" )
        self.assertEqual( err.error_code, "E_API" )           # forwarded to LlmError.__init__
        self.assertEqual( err.metadata, { "url": "/x" } )


class TestLlmAuthenticationError( unittest.TestCase ):
    def test_inherits_api_error( self ):
        err = LlmAuthenticationError( "bad key", status_code=401 )
        self.assertIsInstance( err, LlmAPIError )
        self.assertIsInstance( err, LlmError )
        self.assertEqual( err.status_code, 401 )


class TestLlmRateLimitError( unittest.TestCase ):
    def test_retry_after_and_inheritance( self ):
        err = LlmRateLimitError( "slow down", retry_after=30, status_code=429 )
        self.assertIsInstance( err, LlmAPIError )
        self.assertEqual( err.retry_after, 30 )
        self.assertEqual( err.status_code, 429 )              # forwarded through kwargs

    def test_retry_after_default_none( self ):
        err = LlmRateLimitError( "slow down" )
        self.assertIsNone( err.retry_after )


class TestHarvestedFromLegacy( unittest.TestCase ):
    """
    Assertions harvested from the now-deleted test_data_types_and_exceptions.py
    (the superseded combined legacy test) that exercised module contract beyond
    the dedicated tests above. The legacy file's serialization / validation /
    propagation / performance suites tested usage PATTERNS with locally-defined
    helpers (not module code) and depended on broken test infrastructure — those
    carried no module coverage and were not harvested.
    """

    def test_specific_type_caught_before_base( self ):
        """A subclass is catchable as its specific type AND as the LlmError base."""
        try:
            raise LlmConfigError( "config" )
        except LlmConfigError as e:
            self.assertIsInstance( e, LlmConfigError )
            self.assertIsInstance( e, LlmError )
        # Derived error is catchable purely as the base type too
        try:
            raise LlmModelError( "model" )
        except LlmError as e:
            self.assertIsInstance( e, LlmModelError )

    def test_provided_metadata_stored_by_reference( self ):
        """`metadata or {}` stores the SAME dict when provided → caller-visible mutation."""
        meta = { "component": "x" }
        err = LlmError( "msg", metadata=meta )
        err.metadata[ "added" ] = "value"
        self.assertIn( "added", meta )                        # same object, not a copy
        self.assertIn( "component", err.metadata )


if __name__ == "__main__":
    unittest.main()
