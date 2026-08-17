"""
Unit tests for cosa.memory.gister.Gister with comprehensive boundary mocking.

Exercises the Gister class against its CURRENT production contract:

- __init__               — config-driven cache enable/disable, GistCacheTable wiring,
                           debug status print
- get_gist               — single-word shortcut, default-vs-custom prompt routing,
                           cache HIT / MISS / store, debug+verbose tracing
- _generate_gist_via_llm — template load + process + format, LLM call, Pydantic
                           SimpleResponse parsing, None-content guard, XMLParsingError
                           and generic-exception fallbacks

Zero external dependencies — ConfigurationManager, LlmClientFactory, Normalizer,
GistCacheTable, PromptTemplateProcessor, SimpleResponse, and the du.* helpers are
all mocked at the boundary. No network / model / storage I/O.

Created 2026-05-31 (CoSA coverage campaign, memory group — Tiffany 💍). New file;
the module previously had no dedicated unit-test coverage.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.memory.gister import Gister
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError


class TestGister( unittest.TestCase ):
    """
    Comprehensive unit tests for the Gister class.

    Ensures:
        - Initialization honors the cache-enabled config flag
        - get_gist routes default vs custom prompts and cache hit/miss correctly
        - _generate_gist_via_llm parses, guards, and degrades gracefully
    """

    def _build_gister( self, cache_enabled=True, debug=False, verbose=False ):
        """
        Construct a Gister with its full __init__ dependency chain mocked.

        Patches (module-bound): ConfigurationManager, LlmClientFactory, Normalizer,
        GistCacheTable, and du.get_project_root.

        Args:
            cache_enabled : value returned for the "gister cache enabled" config key
            debug         : forwarded to the constructor
            verbose       : forwarded to the constructor

        Returns:
            Tuple of (gister_instance, mocks_dict)
        """
        mapping = {
            "gister cache enabled"            : cache_enabled,
            "solution snapshots lancedb path" : "/db/lancedb",
            "gister cache table name"         : "gist_cache",
            "prompt template for gist generation" : "/prompts/gist.txt",
            "llm spec key for gist generation"     : "llm_spec_key",
        }

        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None, return_type=None: mapping.get( key, default )

        mock_client  = Mock()
        mock_factory = Mock()
        mock_factory.get_client.return_value = mock_client

        mock_normalizer = Mock()
        mock_normalizer.normalize.side_effect = lambda u: u.lower()

        mock_cache = Mock()

        with patch( "cosa.memory.gister.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.memory.gister.LlmClientFactory", return_value=mock_factory ), \
             patch( "cosa.memory.gister.Normalizer", return_value=mock_normalizer ), \
             patch( "cosa.memory.gister.GistCacheTable", return_value=mock_cache ), \
             patch( "cosa.memory.gister.du.get_project_root", return_value="/root" ):

            gister = Gister( debug=debug, verbose=verbose )

        mocks = {
            "config"     : mock_config,
            "factory"    : mock_factory,
            "client"     : mock_client,
            "normalizer" : mock_normalizer,
            "cache"      : mock_cache,
        }
        return gister, mocks

    # ------------------------------------------------------------------ #
    # __init__                                                            #
    # ------------------------------------------------------------------ #

    def test_init_cache_enabled_constructs_cache_table( self ):
        """
        Test initialization with caching enabled wires up the GistCacheTable.

        Ensures:
            - cache_enabled flag is True
            - _gist_cache is the constructed cache table
            - config consulted for the table name (no location — Postgres store)
        """
        gister, mocks = self._build_gister( cache_enabled=True )

        self.assertTrue( gister.cache_enabled )
        self.assertIs( gister._gist_cache, mocks["cache"] )
        consulted = [ c.args[0] for c in mocks["config"].get.call_args_list ]
        self.assertIn( "gister cache table name", consulted )
        self.assertNotIn( "solution snapshots lancedb path", consulted )

    def test_init_cache_disabled_skips_cache_table( self ):
        """
        Test initialization with caching disabled leaves _gist_cache unset.

        Ensures:
            - cache_enabled flag is False
            - _gist_cache stays None (table never constructed)
            - the cache table-name key is NOT consulted
        """
        gister, mocks = self._build_gister( cache_enabled=False )

        self.assertFalse( gister.cache_enabled )
        self.assertIsNone( gister._gist_cache )
        consulted = [ c.args[0] for c in mocks["config"].get.call_args_list ]
        self.assertNotIn( "gister cache table name", consulted )

    def test_init_debug_status_print_both_states( self ):
        """
        Test the debug status-print branch for both cache states.

        Ensures:
            - debug=True exercises the "cache enabled/disabled" status line
            - Both enabled and disabled status strings are reached
        """
        for cache_enabled in ( True, False ):
            with self.subTest( cache_enabled=cache_enabled ):
                gister, _ = self._build_gister( cache_enabled=cache_enabled, debug=True )
                self.assertEqual( gister.cache_enabled, cache_enabled )

    # ------------------------------------------------------------------ #
    # get_gist — shortcut + prompt routing + cache                       #
    # ------------------------------------------------------------------ #

    def test_get_gist_single_word_shortcut( self ):
        """
        Test the single-word shortcut returns the (stripped) token without an LLM call.

        Ensures:
            - An utterance with no internal space is returned stripped
            - No cache lookup and no LLM generation occur
        """
        gister, mocks = self._build_gister( cache_enabled=True, debug=True )

        result = gister.get_gist( "  hello  " )

        self.assertEqual( result, "hello" )
        mocks["cache"].get_cached_gist.assert_not_called()
        mocks["client"].run.assert_not_called()

    def test_get_gist_default_prompt_cache_hit( self ):
        """
        Test a cache HIT on the default prompt returns the cached gist directly.

        Ensures:
            - get_cached_gist consulted with the raw utterance
            - The cached value is returned (no LLM generation)
        """
        gister, mocks = self._build_gister( cache_enabled=True, debug=True, verbose=True )
        mocks["cache"].get_cached_gist.return_value = "cached gist"

        result = gister.get_gist( "what is the date" )

        self.assertEqual( result, "cached gist" )
        mocks["cache"].get_cached_gist.assert_called_once_with( "what is the date" )
        mocks["cache"].cache_gist.assert_not_called()

    def test_get_gist_cache_miss_generates_and_stores( self ):
        """
        Test a cache MISS generates via LLM and stores the result.

        Ensures:
            - On a None cache lookup, _generate_gist_via_llm is invoked
            - The generated gist is cached with the normalized form
            - The generated gist is returned
        """
        gister, mocks = self._build_gister( cache_enabled=True, debug=True, verbose=True )
        mocks["cache"].get_cached_gist.return_value = None

        with patch.object( gister, "_generate_gist_via_llm", return_value="the gist" ) as gen:
            result = gister.get_gist( "what is the date" )

        self.assertEqual( result, "the gist" )
        gen.assert_called_once_with( "what is the date", gister.DEFAULT_PROMPT_KEY )
        mocks["cache"].cache_gist.assert_called_once_with(
            "what is the date", "the gist", normalized="what is the date"   # normalizer.lower()
        )

    def test_get_gist_cache_miss_empty_gist_not_stored( self ):
        """
        Test a cache MISS that yields an empty gist is NOT stored.

        Ensures:
            - An empty generated gist skips the cache_gist write (the `and gist` guard)
            - Empty string returned
        """
        gister, mocks = self._build_gister( cache_enabled=True )
        mocks["cache"].get_cached_gist.return_value = None

        with patch.object( gister, "_generate_gist_via_llm", return_value="" ):
            result = gister.get_gist( "what is the date" )

        self.assertEqual( result, "" )
        mocks["cache"].cache_gist.assert_not_called()

    def test_get_gist_custom_prompt_bypasses_cache( self ):
        """
        Test a custom (non-default) prompt key bypasses the cache entirely.

        Ensures:
            - use_cache is False → no cache lookup or store
            - _generate_gist_via_llm invoked with the custom prompt key
        """
        gister, mocks = self._build_gister( cache_enabled=True, debug=True, verbose=True )

        with patch.object( gister, "_generate_gist_via_llm", return_value="custom gist" ) as gen:
            result = gister.get_gist( "summarize this session", prompt_key="session title prompt" )

        self.assertEqual( result, "custom gist" )
        mocks["cache"].get_cached_gist.assert_not_called()
        mocks["cache"].cache_gist.assert_not_called()
        gen.assert_called_once_with( "summarize this session", "session title prompt" )

    def test_get_gist_cache_disabled_generates_without_cache( self ):
        """
        Test the default prompt with caching disabled goes straight to generation.

        Ensures:
            - With cache_enabled=False, use_cache is False
            - No cache table exists; _generate invoked and its result returned
        """
        gister, mocks = self._build_gister( cache_enabled=False )

        with patch.object( gister, "_generate_gist_via_llm", return_value="gen gist" ) as gen:
            result = gister.get_gist( "what is the date" )

        self.assertEqual( result, "gen gist" )
        gen.assert_called_once_with( "what is the date", gister.DEFAULT_PROMPT_KEY )

    # ------------------------------------------------------------------ #
    # _generate_gist_via_llm                                             #
    # ------------------------------------------------------------------ #

    def test_generate_success_strips_content( self ):
        """
        Test _generate_gist_via_llm returns the stripped Pydantic-parsed content.

        Ensures:
            - Template loaded, processed, formatted with the utterance
            - SimpleResponse.from_xml(...).get_content() result is stripped + returned
        """
        gister, mocks = self._build_gister( cache_enabled=False, debug=True, verbose=True )
        mocks["client"].run.return_value = "<response>raw</response>"

        with patch( "cosa.memory.gister.du.get_file_as_string", return_value="PROMPT {utterance}" ), \
             patch( "cosa.memory.gister.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.gister.PromptTemplateProcessor" ) as mock_proc, \
             patch( "cosa.memory.gister.SimpleResponse" ) as mock_sr:

            mock_proc.return_value.process_template.return_value = "PROMPT {utterance}"
            mock_sr.from_xml.return_value.get_content.return_value = "  My Gist  "

            result = gister._generate_gist_via_llm( "what is it", gister.DEFAULT_PROMPT_KEY )

        self.assertEqual( result, "My Gist" )
        mocks["client"].run.assert_called_once()

    def test_generate_none_content_returns_empty( self ):
        """
        Test the None-content guard yields an empty gist.

        Ensures:
            - get_content() returning None is coerced to "" (and stripped to "")
        """
        gister, mocks = self._build_gister( cache_enabled=False, debug=True )
        mocks["client"].run.return_value = "<response></response>"

        with patch( "cosa.memory.gister.du.get_file_as_string", return_value="PROMPT {utterance}" ), \
             patch( "cosa.memory.gister.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.gister.PromptTemplateProcessor" ) as mock_proc, \
             patch( "cosa.memory.gister.SimpleResponse" ) as mock_sr:

            mock_proc.return_value.process_template.return_value = "PROMPT {utterance}"
            mock_sr.from_xml.return_value.get_content.return_value = None

            result = gister._generate_gist_via_llm( "what is it", gister.DEFAULT_PROMPT_KEY )

        self.assertEqual( result, "" )

    def test_generate_xml_parsing_error_returns_empty( self ):
        """
        Test an XMLParsingError during parsing degrades to an empty gist.

        Ensures:
            - The XMLParsingError branch is caught; "" returned (debug trace exercised)
        """
        gister, mocks = self._build_gister( cache_enabled=False, debug=True )
        mocks["client"].run.return_value = "not valid xml"

        with patch( "cosa.memory.gister.du.get_file_as_string", return_value="PROMPT {utterance}" ), \
             patch( "cosa.memory.gister.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.gister.PromptTemplateProcessor" ) as mock_proc, \
             patch( "cosa.memory.gister.SimpleResponse" ) as mock_sr:

            mock_proc.return_value.process_template.return_value = "PROMPT {utterance}"
            mock_sr.from_xml.side_effect = XMLParsingError( "bad xml" )

            result = gister._generate_gist_via_llm( "what is it", gister.DEFAULT_PROMPT_KEY )

        self.assertEqual( result, "" )

    def test_generate_generic_exception_returns_empty( self ):
        """
        Test an unexpected exception during parsing degrades to an empty gist.

        Ensures:
            - The generic-Exception branch is caught; "" returned (debug trace exercised)
        """
        gister, mocks = self._build_gister( cache_enabled=False, debug=True )
        mocks["client"].run.return_value = "<response>x</response>"

        with patch( "cosa.memory.gister.du.get_file_as_string", return_value="PROMPT {utterance}" ), \
             patch( "cosa.memory.gister.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.gister.PromptTemplateProcessor" ) as mock_proc, \
             patch( "cosa.memory.gister.SimpleResponse" ) as mock_sr:

            mock_proc.return_value.process_template.return_value = "PROMPT {utterance}"
            mock_sr.from_xml.side_effect = ValueError( "boom" )

            result = gister._generate_gist_via_llm( "what is it", gister.DEFAULT_PROMPT_KEY )

        self.assertEqual( result, "" )


if __name__ == "__main__":
    unittest.main()
