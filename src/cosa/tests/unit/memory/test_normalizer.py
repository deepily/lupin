"""
Unit tests for Normalizer against its real (spaCy-backed) production contract.

Tests the Normalizer class including:
- Singleton behavior
- Contraction expansion (apostrophe + STT no-apostrophe variants, case-insensitive)
- Filler-word removal
- Math-operator preservation + spacing
- Lowercasing, punctuation removal, empty/whitespace handling
- Batch normalization

Rewritten 2026-05-30 (CoSA coverage campaign, memory group). The legacy file was
written against a fictional contract:
  - it called Normalizer( debug=..., verbose=... ) but the real __init__ takes NO
    params (it is a config-reading singleton)
  - it asserted stop-word filtering, which the real normalize() does NOT do (it
    filters fillers + punctuation only)
  - it asserted lemmatization outputs ("is" → "be") that the current model does not
    produce ("What time is it?" → "what time is it")
  - its mock-token assertions were hollow (they only verified the mock matched the
    test's own expectation, not real behavior)

This rewrite exercises the REAL Normalizer + real spaCy model, asserting on
deterministic, model-stable behaviors (verified live 2026-05-30 in the cosa venv).
"""

import unittest
from typing import List

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.normalizer import Normalizer


class TestNormalizer( unittest.TestCase ):
    """
    Comprehensive unit tests for Normalizer class.

    Requires:
        - spaCy + en_core_web_sm available in the cosa venv
        - ConfigurationManager available (LUPIN_CONFIG_MGR_CLI_ARGS)

    Ensures:
        - Real normalization behavior validated (no hollow mocks)
        - Contraction / filler / math / case handling covered
        - Singleton identity preserved
    """

    def setUp( self ):
        """
        Setup for each test method.

        Ensures:
            - A working (real) Normalizer singleton is available
        """
        self.mock_manager   = MockManager()
        self.test_utilities = UnitTestUtilities()
        self.normalizer     = Normalizer()

    def tearDown( self ):
        """
        Cleanup after each test method.

        Ensures:
            - Mocks reset (singleton intentionally preserved — it IS the contract)
        """
        self.mock_manager.reset_mocks()

    def test_singleton_identity( self ):
        """
        Test that Normalizer is a singleton.

        Ensures:
            - Two constructions return the same instance
        """
        self.assertIs( Normalizer(), Normalizer() )
        self.assertIs( self.normalizer, Normalizer() )

    def test_initialization_attributes( self ):
        """
        Test Normalizer initialization wired the spaCy pipeline + flags.

        Ensures:
            - nlp pipeline loaded
            - debug/verbose flags present
            - _initialized latch set
        """
        self.assertIsNotNone( self.normalizer.nlp )
        self.assertTrue( hasattr( self.normalizer, "debug" ) )
        self.assertTrue( hasattr( self.normalizer, "verbose" ) )
        self.assertTrue( self.normalizer._initialized )

    def test_normalize_empty_string( self ):
        """
        Test normalize on an empty string.

        Ensures:
            - Empty string returns empty string
        """
        self.assertEqual( self.normalizer.normalize( "" ), "" )

    def test_normalize_whitespace_only( self ):
        """
        Test normalize on a whitespace-only string.

        Ensures:
            - Whitespace-only input returns empty string
        """
        self.assertEqual( self.normalizer.normalize( "   " ), "" )

    def test_normalize_lowercases( self ):
        """
        Test normalize lowercases its output.

        Ensures:
            - No uppercase characters survive normalization
        """
        result = self.normalizer.normalize( "HELLO World" )
        self.assertEqual( result, result.lower() )
        self.assertNotEqual( result, "" )

    def test_normalize_removes_filler_words( self ):
        """
        Test normalize strips filler words.

        Ensures:
            - 'um' / 'uh' fillers do not survive
            - Content words remain
        """
        result = self.normalizer.normalize( "um uh I want pizza" )
        tokens = result.split()
        self.assertNotIn( "um", tokens )
        self.assertNotIn( "uh", tokens )
        self.assertIn( "want", tokens )
        self.assertIn( "pizza", tokens )

    def test_normalize_preserves_math_operators_with_spacing( self ):
        """
        Test normalize preserves math operators and spaces them.

        Ensures:
            - '2+2' becomes '2 + 2' (operators carry semantic meaning in queries)
        """
        result = self.normalizer.normalize( "what is 2+2" )
        self.assertIn( "2 + 2", result )

    def test_normalize_time_query_punctuation_removed( self ):
        """
        Test the canonical 'What time is it?' query normalizes deterministically.

        Ensures:
            - Trailing '?' removed
            - Result is the stable lowercased token sequence
        """
        result = self.normalizer.normalize( "What time is it?" )
        self.assertEqual( result, "what time is it" )

    def test_normalize_punctuation_stripped( self ):
        """
        Test normalize removes ordinary punctuation while keeping words.

        Ensures:
            - Commas / exclamation marks dropped
            - Content words preserved
        """
        result = self.normalizer.normalize( "Hello, world!" )
        self.assertNotIn( ",", result )
        self.assertNotIn( "!", result )
        self.assertIn( "hello", result )
        self.assertIn( "world", result )

    def test_normalize_consistency( self ):
        """
        Test normalize is deterministic for the same input.

        Ensures:
            - Two identical calls produce identical output
        """
        text = "Tell me the current weather"
        self.assertEqual( self.normalizer.normalize( text ), self.normalizer.normalize( text ) )

    def test_expand_contractions_apostrophe( self ):
        """
        Test contraction expansion for apostrophe forms.

        Ensures:
            - "don't" → "do not"; "can't" → "cannot"; "it's" → "it is"
        """
        self.assertEqual( self.normalizer.expand_contractions( "don't" ), "do not" )
        self.assertEqual( self.normalizer.expand_contractions( "can't" ), "cannot" )
        self.assertEqual( self.normalizer.expand_contractions( "it's" ), "it is" )

    def test_expand_contractions_stt_variants( self ):
        """
        Test contraction expansion for STT (no-apostrophe) variants.

        Ensures:
            - "dont" → "do not"; "whats" → "what is"; "youre" → "you are"
        """
        self.assertEqual( self.normalizer.expand_contractions( "dont" ), "do not" )
        self.assertEqual( self.normalizer.expand_contractions( "whats" ), "what is" )
        self.assertEqual( self.normalizer.expand_contractions( "youre" ), "you are" )

    def test_expand_contractions_case_insensitive( self ):
        """
        Test contraction expansion is case-insensitive.

        Ensures:
            - "Don't" and "WON'T" expand regardless of case
        """
        self.assertEqual( self.normalizer.expand_contractions( "Don't" ), "do not" )
        self.assertEqual( self.normalizer.expand_contractions( "WON'T" ), "will not" )

    def test_expand_contractions_within_sentence( self ):
        """
        Test contraction expansion within a larger sentence (word-boundary safe).

        Ensures:
            - Only whole-word contractions expanded, surrounding words preserved
        """
        result = self.normalizer.expand_contractions( "I won't go" )
        self.assertIn( "will not", result )
        self.assertIn( "go", result )

    def test_remove_filler_words_method( self ):
        """
        Test remove_filler_words on a real spaCy Doc.

        Ensures:
            - Filler tokens removed, content tokens preserved
            - Returns a list of tokens
        """
        doc    = self.normalizer.nlp( "um hello there" )
        tokens = self.normalizer.remove_filler_words( doc )
        texts  = [ t.text for t in tokens ]
        self.assertNotIn( "um", texts )
        self.assertIn( "hello", texts )

    def test_normalize_batch( self ):
        """
        Test normalize_batch processes multiple texts.

        Ensures:
            - Returns a list of the same length as the input
            - Each element is a string
            - Deterministic across calls
        """
        texts   = [ "Hello there", "what time is it", "tell me a joke" ]
        results = self.normalizer.normalize_batch( texts )

        self.assertIsInstance( results, list )
        self.assertEqual( len( results ), len( texts ) )
        for r in results:
            self.assertIsInstance( r, str )

        # Deterministic
        self.assertEqual( results, self.normalizer.normalize_batch( texts ) )


if __name__ == "__main__":
    unittest.main()
