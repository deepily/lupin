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
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

    # ------------------------------------------------------------------ #
    # __new__ double-checked-locking race + __init__ pipeline branches.   #
    # These reset the singleton and restore the REAL instance in finally  #
    # so the shared spaCy-backed singleton survives for sibling tests.    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tok( text, pos="X", is_punct=False, lemma=None ):
        """Build a lightweight spaCy-token stand-in for branch-level tests."""
        return SimpleNamespace(
            text     = text,
            lemma_   = lemma if lemma is not None else text,
            pos_     = pos,
            is_punct = is_punct,
        )

    def test_new_double_checked_lock_returns_existing_on_race( self ):
        """
        Test __new__ returns the existing instance when it appears during locking.

        Simulates the double-checked-locking race: the outer None-check passes, then
        a competing creation populates _instance while the lock is being acquired, so
        the inner None-check is False and the existing instance is returned.

        Ensures:
            - The inner-check False arm is exercised (no second construction)
            - The pre-populated instance is returned unchanged
        """
        saved_inst = Normalizer._instance
        saved_lock = Normalizer._lock

        sentinel = Mock()
        sentinel._initialized = True   # __init__ early-returns on this latch

        class _RacingLock:
            def __enter__( self_inner ):
                Normalizer._instance = sentinel   # competitor "wins" mid-acquire
                return self_inner
            def __exit__( self_inner, *exc ):
                return False

        Normalizer._instance = None
        Normalizer._lock     = _RacingLock()
        try:
            result = Normalizer()
            self.assertIs( result, sentinel )
        finally:
            Normalizer._instance = saved_inst
            Normalizer._lock     = saved_lock

    def _build_with_pipe_names( self, pipe_names ):
        """
        Construct a fresh Normalizer with spaCy + config mocked and a given pipeline.

        Resets the singleton, patches spacy.load to return a fake nlp whose
        pipe_names is the supplied list, then restores the real singleton.

        Returns:
            The constructed (fake-nlp) Normalizer instance.
        """
        saved_inst = Normalizer._instance
        Normalizer._instance = None

        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "app debug"        : False,
            "app verbose"      : False,
            "spacy model name" : "en_core_web_sm",
        }.get( key, default )

        fake_nlp = Mock()
        fake_nlp.pipe_names = pipe_names

        try:
            with patch( "cosa.memory.normalizer.ConfigurationManager", return_value=cfg ), \
                 patch( "cosa.memory.normalizer.spacy" ) as mock_spacy:
                mock_spacy.load.return_value = fake_nlp
                inst = Normalizer()
            return inst, fake_nlp
        finally:
            Normalizer._instance = saved_inst

    def test_init_disables_textcat_when_present( self ):
        """
        Test __init__ adds 'textcat' (but not 'ner') to the disable list when present.

        Ensures:
            - The no-'ner' branch is taken
            - 'textcat' is appended and disable_pipes invoked with it
        """
        inst, fake_nlp = self._build_with_pipe_names( [ "tok2vec", "textcat" ] )

        fake_nlp.disable_pipes.assert_called_once_with( [ "textcat" ] )

    def test_init_skips_disable_when_no_target_components( self ):
        """
        Test __init__ skips disable_pipes when neither 'ner' nor 'textcat' is present.

        Ensures:
            - The empty-disable-list branch is taken (disable_pipes NOT called)
            - _initialized latch is still set
        """
        inst, fake_nlp = self._build_with_pipe_names( [ "tok2vec", "lemmatizer" ] )

        fake_nlp.disable_pipes.assert_not_called()
        self.assertTrue( inst._initialized )

    def test_init_missing_model_raises_runtime_error( self ):
        """
        Test __init__ converts a spaCy OSError into a helpful RuntimeError.

        Ensures:
            - An OSError from spacy.load is re-raised as RuntimeError with install hint
        """
        saved_inst = Normalizer._instance
        Normalizer._instance = None

        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "app debug"        : False,
            "app verbose"      : False,
            "spacy model name" : "en_core_web_sm",
        }.get( key, default )

        try:
            with patch( "cosa.memory.normalizer.ConfigurationManager", return_value=cfg ), \
                 patch( "cosa.memory.normalizer.spacy" ) as mock_spacy:
                mock_spacy.load.side_effect = OSError( "model not found" )
                with self.assertRaises( RuntimeError ):
                    Normalizer()
        finally:
            Normalizer._instance = saved_inst

    # ------------------------------------------------------------------ #
    # remove_filler_words debug trace + normalize / normalize_batch       #
    # token-iteration branches, driven by a swapped fake nlp (restored).  #
    # ------------------------------------------------------------------ #

    def test_remove_filler_words_debug_trace( self ):
        """
        Test remove_filler_words logs removed fillers under debug+verbose.

        Ensures:
            - With debug+verbose the filler-removal print branch is exercised
            - Filler tokens are dropped; content tokens are kept
        """
        saved_debug   = self.normalizer.debug
        saved_verbose = self.normalizer.verbose
        self.normalizer.debug   = True
        self.normalizer.verbose = True
        try:
            doc    = [ self._tok( "um" ), self._tok( "hello" ) ]
            kept   = self.normalizer.remove_filler_words( doc )
            texts  = [ t.text for t in kept ]
            self.assertEqual( texts, [ "hello" ] )
        finally:
            self.normalizer.debug   = saved_debug
            self.normalizer.verbose = saved_verbose

    def test_normalize_skips_empty_sentence( self ):
        """
        Test normalize drops a sentence that yields no surviving tokens.

        Drives a fake doc whose only sentence is a lone (non-math) punctuation token,
        so should_keep is False for every token and the sentence is not appended.

        Ensures:
            - An all-filtered sentence contributes nothing → empty result
        """
        fake_doc = SimpleNamespace( sents=[ [ self._tok( ".", is_punct=True ) ] ] )

        saved_nlp = self.normalizer.nlp
        self.normalizer.nlp = Mock( return_value=fake_doc )
        try:
            self.assertEqual( self.normalizer.normalize( "anything here" ), "" )
        finally:
            self.normalizer.nlp = saved_nlp

    def test_normalize_batch_punctuation_and_empty_sentence( self ):
        """
        Test normalize_batch appends sentence-final punctuation and skips empty sentences.

        Drives a fake piped doc with three sentences:
          - an empty sentence (lone comma → neither kept nor a '.!?' terminator)
          - a content sentence ending in '.' (terminator appended to the last token)
          - a sentence STARTING with '.' (terminator seen while sent_tokens is empty →
            the no-tokens-yet arm is taken and the terminator is dropped)

        Ensures:
            - The empty sentence is skipped (no contribution)
            - A trailing terminator is glued onto the final content token
            - A leading terminator with no preceding token is dropped, not glued
        """
        empty_sent     = [ self._tok( ",", is_punct=True ) ]
        content_sent   = [ self._tok( "hello", pos="NOUN", lemma="hello" ),
                           self._tok( ".", is_punct=True ) ]
        leading_punct  = [ self._tok( ".", is_punct=True ),
                           self._tok( "world", pos="NOUN", lemma="world" ) ]
        fake_doc       = SimpleNamespace( sents=[ empty_sent, content_sent, leading_punct ] )

        saved_nlp = self.normalizer.nlp
        self.normalizer.nlp = Mock()
        self.normalizer.nlp.pipe.return_value = [ fake_doc ]
        try:
            results = self.normalizer.normalize_batch( [ "ignored input" ] )
            self.assertEqual( results, [ "hello. world" ] )
        finally:
            self.normalizer.nlp = saved_nlp


if __name__ == "__main__":
    unittest.main()
