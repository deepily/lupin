"""
Unit tests for cosa.agents.utils.feedback_analysis.

Pure signal-based feedback classification — no mocking.

Covers: is_approval (signal / exact-match / negative / empty), is_rejection
(signal / negative / empty), extract_feedback_intent (all three feedback_type arms).

Created 2026-05-31 (CoSA coverage campaign, utils package — Tiffany 💍). New file.
"""

import unittest

from cosa.agents.utils import feedback_analysis as fa


class TestFeedbackAnalysis( unittest.TestCase ):
    """Comprehensive unit tests for the feedback-analysis helpers."""

    def test_is_approval_signal_substring( self ):
        """Test an approval signal substring yields True."""
        self.assertTrue( fa.is_approval( "Yes, proceed please" ) )
        self.assertTrue( fa.is_approval( "sounds good" ) )

    def test_is_approval_exact_short_match( self ):
        """Test a short exact-match token (e.g. 'yep') yields True."""
        self.assertTrue( fa.is_approval( "yep" ) )

    def test_is_approval_negative_and_empty( self ):
        """Test non-approval and empty/None inputs yield False."""
        self.assertFalse( fa.is_approval( "zzz" ) )
        self.assertFalse( fa.is_approval( "" ) )
        self.assertFalse( fa.is_approval( None ) )

    def test_is_rejection_signal_and_empty( self ):
        """Test rejection signals yield True; empty/None yields False."""
        self.assertTrue( fa.is_rejection( "wait, stop" ) )
        self.assertTrue( fa.is_rejection( "change it" ) )
        self.assertFalse( fa.is_rejection( "" ) )
        self.assertFalse( fa.is_rejection( None ) )

    def test_is_rejection_negative( self ):
        """Test a neutral phrase is not a rejection."""
        self.assertFalse( fa.is_rejection( "the weather today" ) )

    def test_extract_intent_approval( self ):
        """Test extract_feedback_intent classifies approval."""
        intent = fa.extract_feedback_intent( "yes, go ahead" )
        self.assertTrue( intent[ "is_approval" ] )
        self.assertEqual( intent[ "feedback_type" ], "approval" )

    def test_extract_intent_change_request( self ):
        """Test extract_feedback_intent classifies a change request."""
        intent = fa.extract_feedback_intent( "no, change it" )
        self.assertTrue( intent[ "is_rejection" ] )
        self.assertEqual( intent[ "feedback_type" ], "change_request" )

    def test_extract_intent_additional_context( self ):
        """Test extract_feedback_intent classifies neutral context."""
        intent = fa.extract_feedback_intent( "focus on performance" )
        self.assertFalse( intent[ "is_approval" ] )
        self.assertFalse( intent[ "is_rejection" ] )
        self.assertEqual( intent[ "feedback_type" ], "additional_context" )


if __name__ == "__main__":
    unittest.main()
