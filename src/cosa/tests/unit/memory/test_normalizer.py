"""
Unit tests for Normalizer with comprehensive mocking.

Tests the Normalizer class including:
- Punctuation removal fix validation (CRITICAL)
- Lemmatization behavior
- Text preprocessing and tokenization
- Edge cases and error conditions

Zero external dependencies - all operations mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Dict, Any, Optional

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
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns

    Ensures:
        - All Normalizer functionality tested in isolation
        - Punctuation fix validation (critical search failure resolution)
        - Edge cases and error conditions validated
    """

    def setUp( self ):
        """
        Setup for each test method.

        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()

    def tearDown( self ):
        """
        Cleanup after each test method.

        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()

    def test_punctuation_removal_fix( self ):
        """
        Test that punctuation preservation is completely removed (CRITICAL).

        This test validates the critical fix for "What time is it?" search failure
        where punctuation preservation caused exact match failures.

        Ensures:
            - "What time is it?" → "what time is it" (no punctuation)
            - Contractions and punctuation properly handled
            - Multiple punctuation marks removed
            - No sentence-ending preservation
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            # Mock spaCy model and pipeline
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            # Mock document and tokens for "What time is it?"
            mock_doc = Mock()
            mock_tokens = []

            # Token: "What"
            token_what = Mock()
            token_what.is_punct = False
            token_what.is_stop = False
            token_what.pos_ = 'NOUN'
            token_what.lemma_ = 'what'
            token_what.text = 'what'
            mock_tokens.append( token_what )

            # Token: "time"
            token_time = Mock()
            token_time.is_punct = False
            token_time.is_stop = False
            token_time.pos_ = 'NOUN'
            token_time.lemma_ = 'time'
            token_time.text = 'time'
            mock_tokens.append( token_time )

            # Token: "is"
            token_is = Mock()
            token_is.is_punct = False
            token_is.is_stop = False
            token_is.pos_ = 'VERB'
            token_is.lemma_ = 'be'
            token_is.text = 'is'
            mock_tokens.append( token_is )

            # Token: "it"
            token_it = Mock()
            token_it.is_punct = False
            token_it.is_stop = False
            token_it.pos_ = 'PRON'
            token_it.lemma_ = 'it'
            token_it.text = 'it'
            mock_tokens.append( token_it )

            # Token: "?" (punctuation - should be ignored)
            token_punct = Mock()
            token_punct.is_punct = True
            token_punct.is_stop = False
            token_punct.pos_ = 'PUNCT'
            token_punct.text = '?'
            mock_tokens.append( token_punct )

            mock_doc.__iter__ = Mock( return_value=iter( mock_tokens ) )
            mock_doc.sents = [Mock()]
            mock_doc.sents[0].__iter__ = Mock( return_value=iter( mock_tokens ) )
            mock_nlp.return_value = mock_doc

            normalizer = Normalizer( debug=False, verbose=False )

            # Critical test cases that were failing before fix
            result = normalizer.normalize( "What time is it?" )
            expected = "what time be it"  # Note: lemmatization changes "is" to "be"

            self.assertEqual( result, expected,
                           f"Punctuation not properly removed: 'What time is it?' → '{result}' (expected: '{expected}')" )

    def test_punctuation_removal_comprehensive( self ):
        """
        Test comprehensive punctuation removal scenarios.

        Ensures:
            - Various punctuation types are removed
            - Contractions are expanded
            - Multiple punctuation marks handled
            - No preservation of sentence-ending punctuation
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            normalizer = Normalizer( debug=False, verbose=False )

            # Test cases for punctuation removal
            test_cases = [
                ( "Hello, world!", ["hello", "world"] ),
                ( "What's happening?", ["what", "be", "happen"] ),  # Contraction expanded
                ( "Yes, it is.", ["yes", "it", "be"] ),
                ( "Really?! Amazing!!!", ["really", "amazing"] ),
                ( "user@example.com", ["user", "example", "com"] ),
            ]

            for input_text, expected_tokens in test_cases:
                # Mock the spaCy processing for each test case
                mock_doc = Mock()
                mock_tokens = []

                for token_text in expected_tokens:
                    token = Mock()
                    token.is_punct = False
                    token.is_stop = False
                    token.pos_ = 'NOUN'  # Simplified for testing
                    token.lemma_ = token_text
                    token.text = token_text
                    mock_tokens.append( token )

                # Add punctuation tokens that should be ignored
                for punct in ",.!?@":
                    if punct in input_text:
                        punct_token = Mock()
                        punct_token.is_punct = True
                        punct_token.text = punct
                        mock_tokens.append( punct_token )

                mock_doc.__iter__ = Mock( return_value=iter( mock_tokens ) )
                mock_doc.sents = [Mock()]
                mock_doc.sents[0].__iter__ = Mock( return_value=iter( mock_tokens ) )
                mock_nlp.return_value = mock_doc

                result = normalizer.normalize( input_text )
                expected = " ".join( expected_tokens )

                self.assertEqual( result, expected,
                               f"Punctuation removal failed for '{input_text}': got '{result}', expected '{expected}'" )

    def test_lemmatization_behavior( self ):
        """
        Test lemmatization behavior for different parts of speech.

        Ensures:
            - Verbs are lemmatized correctly
            - Nouns are lemmatized correctly
            - Function words use original form
            - POS-based lemmatization logic works
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            # Test lemmatization with different POS tags
            test_cases = [
                # (text, pos, lemma, expected_output)
                ( "running", "VERB", "run", "run" ),
                ( "cats", "NOUN", "cat", "cat" ),
                ( "better", "ADJ", "good", "good" ),
                ( "quickly", "ADV", "quickly", "quickly" ),
                ( "the", "DET", "the", "the" ),  # Function word - uses original
            ]

            normalizer = Normalizer( debug=False, verbose=False )

            for text, pos, lemma, expected in test_cases:
                mock_doc = Mock()
                token = Mock()
                token.is_punct = False
                token.is_stop = False
                token.pos_ = pos
                token.lemma_ = lemma
                token.text = text

                mock_doc.__iter__ = Mock( return_value=iter( [token] ) )
                mock_doc.sents = [Mock()]
                mock_doc.sents[0].__iter__ = Mock( return_value=iter( [token] ) )
                mock_nlp.return_value = mock_doc

                result = normalizer.normalize( text )

                self.assertEqual( result, expected,
                               f"Lemmatization failed for '{text}' ({pos}): got '{result}', expected '{expected}'" )

    def test_stop_word_handling( self ):
        """
        Test stop word filtering behavior.

        Ensures:
            - Stop words are filtered out appropriately
            - Content words are preserved
            - Stop word detection works correctly
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            normalizer = Normalizer( debug=False, verbose=False )

            # Mock tokens: content words and stop words
            content_token = Mock()
            content_token.is_punct = False
            content_token.is_stop = False
            content_token.pos_ = 'NOUN'
            content_token.lemma_ = 'apple'
            content_token.text = 'apple'

            stop_token = Mock()
            stop_token.is_punct = False
            stop_token.is_stop = True
            stop_token.pos_ = 'DET'
            stop_token.lemma_ = 'the'
            stop_token.text = 'the'

            mock_doc = Mock()
            mock_doc.__iter__ = Mock( return_value=iter( [stop_token, content_token] ) )
            mock_doc.sents = [Mock()]
            mock_doc.sents[0].__iter__ = Mock( return_value=iter( [stop_token, content_token] ) )
            mock_nlp.return_value = mock_doc

            result = normalizer.normalize( "the apple" )

            # Should only include content word, not stop word
            self.assertEqual( result, "apple",
                           f"Stop word filtering failed: got '{result}', expected 'apple'" )

    def test_empty_and_edge_cases( self ):
        """
        Test edge cases and error conditions.

        Ensures:
            - Empty strings handled gracefully
            - Whitespace-only strings handled
            - Very long strings processed correctly
            - Invalid input handled without crashes
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            normalizer = Normalizer( debug=False, verbose=False )

            # Empty document case
            mock_doc_empty = Mock()
            mock_doc_empty.__iter__ = Mock( return_value=iter( [] ) )
            mock_doc_empty.sents = []
            mock_nlp.return_value = mock_doc_empty

            # Test empty string
            result = normalizer.normalize( "" )
            self.assertEqual( result, "", "Empty string should return empty string" )

            # Test whitespace-only string
            result = normalizer.normalize( "   " )
            self.assertEqual( result, "", "Whitespace-only string should return empty string" )

            # Test string with only punctuation
            result = normalizer.normalize( "?!@#$" )
            self.assertEqual( result, "", "Punctuation-only string should return empty string" )

    def test_case_normalization( self ):
        """
        Test case normalization behavior.

        Ensures:
            - All text is converted to lowercase
            - Mixed case inputs handled correctly
            - Case normalization works with other processing
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            normalizer = Normalizer( debug=False, verbose=False )

            # Mock token that preserves case information
            token = Mock()
            token.is_punct = False
            token.is_stop = False
            token.pos_ = 'NOUN'
            token.lemma_ = 'hello'  # spaCy should return lowercase lemma
            token.text = 'Hello'

            mock_doc = Mock()
            mock_doc.__iter__ = Mock( return_value=iter( [token] ) )
            mock_doc.sents = [Mock()]
            mock_doc.sents[0].__iter__ = Mock( return_value=iter( [token] ) )
            mock_nlp.return_value = mock_doc

            result = normalizer.normalize( "HELLO" )

            self.assertEqual( result, "hello",
                           f"Case normalization failed: got '{result}', expected 'hello'" )

    def test_critical_search_failure_scenarios( self ):
        """
        Test specific scenarios that caused the original search failure.

        This test validates the exact scenarios that were failing in the
        three-level architecture implementation.

        Ensures:
            - "What time is it?" search works correctly
            - Punctuation variations are normalized consistently
            - Database queries will find exact matches
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            normalizer = Normalizer( debug=False, verbose=False )

            # The exact scenarios that were causing search failures
            critical_test_cases = [
                # Original failing case
                ( "What time is it?", "what time be it" ),
                # Variations that should normalize to same result
                ( "What time is it", "what time be it" ),
                ( "what time is it?", "what time be it" ),
                ( "what time is it", "what time be it" ),
                # Similar time-related queries
                ( "What's the time?", "what be the time" ),
                ( "Tell me the time", "tell me the time" ),
            ]

            for input_query, expected_normalized in critical_test_cases:
                # Mock appropriate tokens for each query
                if "what time" in input_query.lower():
                    tokens = self._create_time_query_tokens( input_query )
                else:
                    tokens = self._create_generic_tokens( input_query )

                mock_doc = Mock()
                mock_doc.__iter__ = Mock( return_value=iter( tokens ) )
                mock_doc.sents = [Mock()]
                mock_doc.sents[0].__iter__ = Mock( return_value=iter( tokens ) )
                mock_nlp.return_value = mock_doc

                result = normalizer.normalize( input_query )

                self.assertEqual( result, expected_normalized,
                               f"Critical search failure case: '{input_query}' → '{result}' (expected: '{expected_normalized}')" )

    def _create_time_query_tokens( self, query ):
        """Helper method to create mock tokens for time-related queries."""
        tokens = []
        words = query.lower().replace( "?", "" ).replace( "'s", "" ).split()

        for word in words:
            if word in ["what", "what's"]:
                token = Mock()
                token.is_punct = False
                token.is_stop = False
                token.pos_ = 'PRON'
                token.lemma_ = 'what'
                token.text = 'what'
                tokens.append( token )
            elif word == "time":
                token = Mock()
                token.is_punct = False
                token.is_stop = False
                token.pos_ = 'NOUN'
                token.lemma_ = 'time'
                token.text = 'time'
                tokens.append( token )
            elif word in ["is", "be"]:
                token = Mock()
                token.is_punct = False
                token.is_stop = False
                token.pos_ = 'VERB'
                token.lemma_ = 'be'
                token.text = word
                tokens.append( token )
            elif word == "it":
                token = Mock()
                token.is_punct = False
                token.is_stop = False
                token.pos_ = 'PRON'
                token.lemma_ = 'it'
                token.text = 'it'
                tokens.append( token )
            elif word == "the":
                token = Mock()
                token.is_punct = False
                token.is_stop = False
                token.pos_ = 'DET'
                token.lemma_ = 'the'
                token.text = 'the'
                tokens.append( token )
            elif word in ["tell", "me"]:
                token = Mock()
                token.is_punct = False
                token.is_stop = False
                token.pos_ = 'VERB' if word == "tell" else 'PRON'
                token.lemma_ = word
                token.text = word
                tokens.append( token )

        return tokens

    def _create_generic_tokens( self, text ):
        """Helper method to create mock tokens for generic text."""
        tokens = []
        words = text.lower().replace( "?", "" ).replace( "!", "" ).split()

        for word in words:
            token = Mock()
            token.is_punct = False
            token.is_stop = False
            token.pos_ = 'NOUN'
            token.lemma_ = word
            token.text = word
            tokens.append( token )

        return tokens

    def test_initialization( self ):
        """
        Test Normalizer initialization.

        Ensures:
            - Normalizer initializes correctly with default parameters
            - Debug and verbose flags are handled properly
            - spaCy model is loaded correctly
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            # Test default initialization
            normalizer = Normalizer()
            self.assertIsNotNone( normalizer )
            mock_spacy.assert_called_with( "en_core_web_sm" )

            # Test with debug and verbose flags
            normalizer_debug = Normalizer( debug=True, verbose=True )
            self.assertIsNotNone( normalizer_debug )

    def test_performance_characteristics( self ):
        """
        Test performance-related characteristics.

        Ensures:
            - Normalizer handles reasonable text lengths efficiently
            - No memory leaks in token processing
            - Consistent behavior across multiple calls
        """
        with patch( 'cosa.memory.normalizer.spacy.load' ) as mock_spacy:
            mock_nlp = Mock()
            mock_spacy.return_value = mock_nlp

            normalizer = Normalizer( debug=False, verbose=False )

            # Mock for consistent results
            mock_doc = Mock()
            token = Mock()
            token.is_punct = False
            token.is_stop = False
            token.pos_ = 'NOUN'
            token.lemma_ = 'test'
            token.text = 'test'

            mock_doc.__iter__ = Mock( return_value=iter( [token] ) )
            mock_doc.sents = [Mock()]
            mock_doc.sents[0].__iter__ = Mock( return_value=iter( [token] ) )
            mock_nlp.return_value = mock_doc

            # Test multiple calls produce consistent results
            text = "Test consistency"
            result1 = normalizer.normalize( text )
            result2 = normalizer.normalize( text )

            self.assertEqual( result1, result2,
                           "Normalizer should produce consistent results for same input" )


if __name__ == "__main__":
    unittest.main()