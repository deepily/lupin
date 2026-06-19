"""
Unit tests for the multimodal transcription munger (cosa.rest.multimodal_munger).

Drives MultiModalMunger to genuine 100% line + branch + function coverage. Every
external seam is boundary-mocked — NO GPU, NO DB, NO network, NO real LLM, NO real
OpenAI calls, NO ANTHROPIC_API_KEY access:

  - du file loaders (get_file_as_dictionary / _string / _list / get_project_root /
    get_api_key / print_banner) are replaced with a MagicMock returning controlled,
    deterministic dictionaries so every transform asserts against known values.
  - ConfigurationManager is injected (config_mgr=...) so __init__ never reads the
    real INI; one test exercises the config_mgr=None construction path with a
    patched ConfigurationManager.
  - openai.completions.create is a Mock (extract_args).
  - LlmClientFactory + CommandResponse are patched (_get_ai_command).

The controlled lookup dictionaries (CHEECH-test fixtures) are intentionally small
and unambiguous so each munge_* result is hand-traceable from the algorithm.
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from cosa.rest import multimodal_munger as mmm
from cosa.rest.multimodal_munger import (
    MultiModalMunger,
    trans_mode_vox_cmd_browser,
    trans_mode_vox_cmd_agent,
    trans_mode_text_raw,
    trans_mode_text_email,
    trans_mode_text_punctuation,
    trans_mode_text_broadcast,
    trans_mode_text_proofread,
    trans_mode_server_search,
    trans_mode_run_prompt,
)
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError


# ── Controlled fixture dictionaries (deterministic, hand-traceable) ──────────
PUNCT = {
    "dot"              : ".",
    "comma"            : ",",
    "underscore"       : "_",
    "colon"            : ":",
    "semicolon"        : ";",
    "hash"             : "#",
    "bang"             : "!",
    "period"           : ".",
    "at sign"          : "@",
    "question mark"    : "?",
    "exclamation point": "!",
}
DOMAINS = { "dot com": ".com", "dotcom": ".com" }
NUMBERS = { "one": "1", "two": "2", "three": "3", "five": "5" }
CONTACT = {
    "name"     : "rick ruiz",
    "address"  : "1 main st",
    "city"     : "anytown",
    "state"    : "ny",
    "zip"      : "10001",
    "email"    : "rick@example.com",
    "telephone": "555-1212",
}
PROMPTDICT = { "generic": "/src/conf/generic-prompt.txt" }
CONSTANTS_LINES = [
    "// this is a comment with no equals",          # split(' = ') len 1 -> skip
    'const NEW_TAB = "go to new tab";',             # valid -> "go to new tab"
    'const SEARCH  = "search";',                    # valid -> "search"
    'const URL     = "http://example.com";',        # startswith '"http' -> skip
    "const COUNT   = 42;",                          # not quoted -> skip
]


class _MungerBase( unittest.TestCase ):
    """
    Shared boundary-mock harness for MultiModalMunger tests.

    Requires:
        - cosa.rest.multimodal_munger imports cleanly

    Ensures:
        - setUp patches mmm.du with a controlled MagicMock and provides a
          config_mgr mock; make() constructs a fully boundary-mocked munger
        - tearDown stops the du patch

    Raises:
        - None
    """

    def setUp( self ):
        self.du = MagicMock( name="du" )
        self.du.get_project_root.return_value = "/root"
        self.du.get_api_key.return_value = "test-key"

        def _dict_side_effect( path, *a, **kw ):
            if "translation-dictionary" in path: return dict( PUNCT )
            if "domain-names"           in path: return dict( DOMAINS )
            if "numbers"                in path: return dict( NUMBERS )
            if "contact-information"    in path: return dict( CONTACT )
            if "prompt-dictionary"      in path: return dict( PROMPTDICT )
            return {}

        self.du.get_file_as_dictionary.side_effect = _dict_side_effect
        self.du.get_file_as_string.return_value     = "TEMPLATE {voice_command}"
        self.du.get_file_as_list.return_value        = list( CONSTANTS_LINES )

        self._du_patch = patch.object( mmm, "du", self.du )
        self._du_patch.start()

        self.cfg = MagicMock( name="config_mgr" )

        def _cfg_get( key, return_type=None, default=None ):
            return {
                "vox command prompt path wo root"      : "/src/conf/vox-template.txt",
                "router and vox command model"         : "test-model",
                "router and vox command is completion" : False,
            }.get( key, default )

        self.cfg.get.side_effect = _cfg_get

    def tearDown( self ):
        self._du_patch.stop()

    def make( self, raw="multimodal text raw hello", prefix="", last_response=None,
              debug=False, verbose=False, use_string_matching=True, use_ai_matching=True ):
        return MultiModalMunger(
            raw, prefix=prefix, last_response=last_response,
            use_string_matching=use_string_matching, use_ai_matching=use_ai_matching,
            debug=debug, verbose=verbose, config_mgr=self.cfg,
        )


class TestConstructionAndDunder( _MungerBase ):
    """Construction, __str__, get_jsons, reverse-map, class/command dictionaries."""

    def test_default_construction_dispatches_text_raw( self ):
        mm = self.make( "multimodal text raw hello world" )
        self.assertEqual( mm.transcription, "hello world" )
        self.assertEqual( mm.mode, trans_mode_text_raw )
        self.assertEqual( mm.results, "" )

    def test_str_contains_all_fields( self ):
        mm = self.make( "multimodal text raw hello" )
        s = str( mm )
        self.assertIn( "Mode:", s )
        self.assertIn( trans_mode_text_raw, s )
        self.assertIn( "Raw transcription:", s )

    def test_get_jsons_round_trips( self ):
        mm = self.make( "multimodal text raw hello" )
        parsed = json.loads( mm.get_jsons() )
        self.assertEqual( set( parsed.keys() ),
                          { "mode", "prefix", "raw_transcription", "transcription", "results" } )
        self.assertEqual( parsed[ "mode" ], trans_mode_text_raw )

    def test_methods_to_modes_is_inverse( self ):
        mm = self.make()
        self.assertEqual( mm.methods_to_modes_dict[ "munge_text_raw" ], trans_mode_text_raw )
        self.assertEqual( mm.methods_to_modes_dict[ "munge_vox_cmd_agent" ], trans_mode_vox_cmd_agent )

    def test_class_dictionary_known_and_default( self ):
        mm = self.make()
        self.assertEqual( mm.class_dictionary[ "0" ], "go to current tab" )
        self.assertEqual( mm.class_dictionary[ "999" ], "unknown command" )  # defaultdict miss

    def test_command_strings_filtered_and_sorted( self ):
        mm = self.make()
        # comment, http, and non-quoted lines dropped; sorted longest-first
        self.assertEqual( mm.command_strings, [ "go to new tab", "search" ] )

    def test_debug_verbose_construction_runs_all_print_branches( self ):
        # Exercises the debug+verbose print arcs in __init__ and _get_command_strings
        mm = self.make( "multimodal text raw hello", debug=True, verbose=True )
        self.assertEqual( mm.mode, trans_mode_text_raw )

    def test_construction_with_none_config_mgr_instantiates_manager( self ):
        with patch.object( mmm, "ConfigurationManager", return_value=self.cfg ) as cm:
            mm = MultiModalMunger( "multimodal text raw hi", config_mgr=None )
            cm.assert_called_once()
            self.assertEqual( mm.mode, trans_mode_text_raw )


class TestTextHelpers( _MungerBase ):
    """Pure leaf string helpers."""

    def setUp( self ):
        super().setUp()
        self.mm = self.make()

    def test_tokenize_reconstructs_exactly( self ):
        toks = self.mm._tokenize( "What's five?" )
        self.assertEqual( toks, [ "What's", " ", "five", "?" ] )
        self.assertEqual( "".join( toks ), "What's five?" )

    def test_remove_protocols_http_and_https( self ):
        self.assertEqual( self.mm._remove_protocols( "http://x.com" ), "x.com" )
        self.assertEqual( self.mm._remove_protocols( "https://y.com" ), "y.com" )
        self.assertEqual( self.mm._remove_protocols( "no protocol here" ), "no protocol here" )

    def test_remove_spaces_around_punctuation_variants( self ):
        self.assertEqual( self.mm._remove_spaces_around_punctuation( "hi ." ), "hi." )
        self.assertEqual( self.mm._remove_spaces_around_punctuation( "hi ?" ), "hi?" )
        self.assertEqual( self.mm._remove_spaces_around_punctuation( "a ?? b" ), "a? b" )
        self.assertEqual( self.mm._remove_spaces_around_punctuation( "x [ y ]" ), "x [y]" )

    def test_remove_dashes_from_single_letters( self ):
        self.assertEqual( self.mm._remove_dashes_from_single_letters_within_word( "t-h-i-s" ), "this" )
        # compound word with multi-char segments is preserved
        self.assertEqual( self.mm._remove_dashes_from_single_letters_within_word( "well-being" ), "well-being" )

    def test_remove_dashed_spellings_across_sentence( self ):
        self.assertEqual( self.mm._remove_dashed_spellings( "spell c-a-t please" ), "spell cat please" )

    def test_collapse_spaces_around_punctuation_code( self ):
        out = self.mm._collapse_spaces_around_punctuation( "self . foo ( )" )
        self.assertEqual( out, "self.foo()" )
        self.assertEqual( self.mm._collapse_spaces_around_punctuation( "a _ b" ), "a_b" )
        self.assertEqual( self.mm._collapse_spaces_around_punctuation( "[ { } ]" ), "[{}]" )


class TestMungeTransforms( _MungerBase ):
    """The mode-specific munge_* transforms (called directly with controlled dicts)."""

    def setUp( self ):
        super().setUp()
        self.mm = self.make()

    def test_munge_text_raw_strips_dashes( self ):
        out, mode = self.mm.munge_text_raw( "say h-i there", trans_mode_text_raw )
        self.assertEqual( out, "say hi there" )
        self.assertEqual( mode, trans_mode_text_raw )

    def test_munge_text_email_basic( self ):
        out, _ = self.mm.munge_text_email( "rick at example dot com", trans_mode_text_email )
        self.assertEqual( out, "rickatexample.com" )

    def test_munge_text_email_numbers_and_digit_space( self ):
        out, _ = self.mm.munge_text_email( "one two", trans_mode_text_email )
        self.assertEqual( out, "12" )

    def test_munge_text_email_dash_between_letters( self ):
        out, _ = self.mm.munge_text_email( "x-y", trans_mode_text_email )
        self.assertEqual( out, "xy" )

    def test_munge_vox_cmd_browser_strips_punct( self ):
        out, mode = self.mm.munge_vox_cmd_browser( "Go to NPR, now!", trans_mode_vox_cmd_browser )
        self.assertEqual( out, "go to npr now" )
        self.assertEqual( mode, trans_mode_vox_cmd_browser )

    def test_munge_vox_cmd_browser_removes_protocol_and_domain( self ):
        out, _ = self.mm.munge_vox_cmd_browser( "https://example dotcom", trans_mode_vox_cmd_browser )
        self.assertEqual( out, "example.com" )

    def test_munge_vox_cmd_agent_underscore_replacement( self ):
        out, mode = self.mm.munge_vox_cmd_agent( "set field underscore name", trans_mode_vox_cmd_agent )
        self.assertEqual( out, "set field_name" )
        self.assertEqual( mode, trans_mode_vox_cmd_agent )

    def test_munge_text_punctuation_preserves_case_and_numbers( self ):
        out, _ = self.mm.munge_text_punctuation( "What's five plus five", trans_mode_text_punctuation )
        # "five" -> "5", commas/periods stripped, case preserved
        self.assertEqual( out, "What's 5 plus 5" )

    def test_munge_text_punctuation_strips_protocol( self ):
        out, _ = self.mm.munge_text_punctuation( "go to http://site", trans_mode_text_punctuation )
        self.assertEqual( out, "go to site" )

    def test_munge_text_punctuation_domain_token_branch( self ):
        # single-token domain "dotcom" -> ".com" (then [,.] strip removes the dot)
        out, _ = self.mm.munge_text_punctuation( "visit dotcom", trans_mode_text_punctuation )
        self.assertEqual( out, "visit com" )

    def test_munge_text_punctuation_punct_token_branch( self ):
        # single-token punct "colon" -> ":" (survives the [,.] strip)
        out, _ = self.mm.munge_text_punctuation( "title colon text", trans_mode_text_punctuation )
        self.assertEqual( out, "title: text" )

    def test_munge_text_proofread_delegates_to_punctuation( self ):
        out, mode = self.mm.munge_text_proofread( "hello five", trans_mode_text_proofread )
        self.assertEqual( out, "hello 5" )
        self.assertEqual( mode, trans_mode_text_proofread )

    # ── munge_text_broadcast: every while-loop arc ───────────────────────────
    def test_broadcast_at_sign_mention( self ):
        out, _ = self.mm.munge_text_broadcast( "at sign you", trans_mode_text_broadcast )
        self.assertEqual( out, "@you" )

    def test_broadcast_bare_at_preserved( self ):
        out, _ = self.mm.munge_text_broadcast( "meet at noon", trans_mode_text_broadcast )
        self.assertEqual( out, "meet at noon" )

    def test_broadcast_question_and_exclamation_phrases( self ):
        self.assertEqual( self.mm.munge_text_broadcast( "how are you question mark", trans_mode_text_broadcast )[ 0 ], "how are you?" )
        self.assertEqual( self.mm.munge_text_broadcast( "wow exclamation point", trans_mode_text_broadcast )[ 0 ], "wow!" )

    def test_broadcast_domain_join_pops_trailing_space( self ):
        out, _ = self.mm.munge_text_broadcast( "example dotcom", trans_mode_text_broadcast )
        self.assertEqual( out, "example.com" )

    def test_broadcast_domain_no_preceding_space( self ):
        out, _ = self.mm.munge_text_broadcast( "dotcom", trans_mode_text_broadcast )
        self.assertEqual( out, ".com" )

    def test_broadcast_joining_underscore_consumes_next_space( self ):
        out, _ = self.mm.munge_text_broadcast( "file underscore name", trans_mode_text_broadcast )
        self.assertEqual( out, "file_name" )

    def test_broadcast_joining_underscore_trailing_no_next_space( self ):
        out, _ = self.mm.munge_text_broadcast( "file underscore", trans_mode_text_broadcast )
        self.assertEqual( out, "file_" )

    def test_broadcast_joining_leading_no_preceding_space( self ):
        out, _ = self.mm.munge_text_broadcast( "underscore x", trans_mode_text_broadcast )
        self.assertEqual( out, "_x" )

    def test_broadcast_non_joining_punct_colon( self ):
        out, _ = self.mm.munge_text_broadcast( "Title colon text", trans_mode_text_broadcast )
        self.assertEqual( out, "Title: text" )

    def test_broadcast_number_lookup( self ):
        out, _ = self.mm.munge_text_broadcast( "five apples", trans_mode_text_broadcast )
        self.assertEqual( out, "5 apples" )

    def test_broadcast_comma_run_collapses_and_bang_cleanup( self ):
        self.assertEqual( self.mm.munge_text_broadcast( "so,,, excited", trans_mode_text_broadcast )[ 0 ], "so, excited" )
        self.assertEqual( self.mm.munge_text_broadcast( "wow,!", trans_mode_text_broadcast )[ 0 ], "wow!" )
        self.assertEqual( self.mm.munge_text_broadcast( "wow!.", trans_mode_text_broadcast )[ 0 ], "wow!" )

    # ── munge_text_contact: every branch ─────────────────────────────────────
    def test_contact_full_block( self ):
        out, _ = self.mm.munge_text_contact( "full", trans_mode_text_email )
        self.assertEqual( out, "full" )
        self.assertIn( "Rick Ruiz", self.mm.results )
        self.assertIn( "Anytown NY, 10001", self.mm.results )
        self.assertIn( "rick@example.com", self.mm.results )

    def test_contact_city_state_zip( self ):
        self.mm.munge_text_contact( "city state zip", trans_mode_text_email )
        self.assertEqual( self.mm.results, "Anytown NY, 10001" )

    def test_contact_state_upper( self ):
        self.mm.munge_text_contact( "state", trans_mode_text_email )
        self.assertEqual( self.mm.results, "NY" )

    def test_contact_email_verbatim( self ):
        self.mm.munge_text_contact( "email", trans_mode_text_email )
        self.assertEqual( self.mm.results, "rick@example.com" )

    def test_contact_name_titlecased( self ):
        self.mm.munge_text_contact( "name", trans_mode_text_email )
        self.assertEqual( self.mm.results, "Rick Ruiz" )

    def test_contact_unknown_key_na_titlecased( self ):
        self.mm.munge_text_contact( "boss", trans_mode_text_email )
        self.assertEqual( self.mm.results, "N/A" )

    def test_munge_python_punctuation( self ):
        out, _ = self.mm.munge_python_punctuation( "print one two", mmm.trans_mode_python_punctuation )
        self.assertEqual( out, "print 12" )

    def test_munge_sql_punctuation( self ):
        out, _ = self.mm.munge_sql_punctuation( "select five", mmm.trans_mode_sql_punctuation )
        self.assertEqual( out, "select 5" )


class TestBacktickExtraction( _MungerBase ):
    """_extract_string_from_backticked_llm_output try + except arcs."""

    def setUp( self ):
        super().setUp()
        self.mm = self.make()

    def test_extract_success( self ):
        raw = "prose\n```python\nprint(1)\n```\nmore"
        self.assertEqual( self.mm._extract_string_from_backticked_llm_output( raw ), "print(1)" )

    def test_extract_failure_returns_raw( self ):
        raw = "no backticks here"
        self.assertEqual( self.mm._extract_string_from_backticked_llm_output( raw ), raw )


class TestModePredicates( _MungerBase ):
    """is_text_proofread / is_ddg_search / is_run_prompt / is_agent."""

    def test_is_text_proofread( self ):
        mm = self.make()
        mm.mode = trans_mode_text_proofread
        self.assertTrue( mm.is_text_proofread() )
        mm.mode = trans_mode_text_raw
        self.assertFalse( mm.is_text_proofread() )

    def test_is_ddg_search( self ):
        mm = self.make()
        mm.mode = trans_mode_server_search
        self.assertTrue( mm.is_ddg_search() )
        mm.mode = trans_mode_text_raw
        self.assertFalse( mm.is_ddg_search() )

    def test_is_run_prompt( self ):
        mm = self.make()
        mm.mode = trans_mode_run_prompt
        self.assertTrue( mm.is_run_prompt() )
        mm.mode = trans_mode_text_raw
        self.assertFalse( mm.is_run_prompt() )

    def test_is_agent( self ):
        mm = self.make()
        mm.mode = trans_mode_vox_cmd_agent
        self.assertTrue( mm.is_agent() )
        mm.mode = trans_mode_text_raw
        self.assertFalse( mm.is_agent() )


class TestCommandMatching( _MungerBase ):
    """_is_match (exact / startswith / none) and _get_command_dict."""

    def setUp( self ):
        super().setUp()
        self.mm = self.make()

    def test_get_command_dict_defaults( self ):
        d = self.mm._get_command_dict()
        self.assertEqual( d, { "match_type": "none", "command": "none", "confidence": 0.0, "args": [ "" ] } )

    def test_is_match_exact( self ):
        is_match, d = self.mm._is_match( "go to new tab" )
        self.assertTrue( is_match )
        self.assertEqual( d[ "command" ], "go to new tab" )
        self.assertEqual( d[ "match_type" ], "string_matching_exact" )

    def test_is_match_startswith( self ):
        is_match, d = self.mm._is_match( "search kittens" )
        self.assertTrue( is_match )
        self.assertEqual( d[ "command" ], "search" )
        self.assertEqual( d[ "match_type" ], "string_matching_startswith" )
        self.assertEqual( d[ "args" ], [ "kittens" ] )

    def test_is_match_none( self ):
        is_match, d = self.mm._is_match( "fly to the moon" )
        self.assertFalse( is_match )
        self.assertEqual( d[ "command" ], "none" )


class TestGetCommandStringsBranches( _MungerBase ):
    """_get_command_strings debug/verbose arc with a richer constants list."""

    def test_debug_verbose_lists_and_skips( self ):
        # The debug+verbose construction prints both kept and skipped commands.
        mm = self.make( debug=True, verbose=True )
        self.assertEqual( mm.command_strings, [ "go to new tab", "search" ] )


class TestAiCommand( _MungerBase ):
    """_get_ai_command success / XMLParsingError / generic-exception arcs."""

    def test_ai_command_success( self ):
        mm = self.make()
        factory = MagicMock( name="factory" )
        client  = MagicMock( name="client" )
        client.run.return_value = "<response>...</response>"
        factory.get_client.return_value = client
        parsed = SimpleNamespace( command="search google", args="kittens" )
        with patch.object( mmm, "LlmClientFactory", return_value=factory ), \
             patch.object( mmm, "CommandResponse" ) as cr:
            cr.from_xml.return_value = parsed
            d = mm._get_ai_command( "search google for kittens" )
        self.assertEqual( d[ "command" ], "search google" )
        self.assertEqual( d[ "args" ], [ "kittens" ] )
        self.assertEqual( d[ "match_type" ], "ai_matching" )

    def test_ai_command_success_debug_and_none_args( self ):
        mm = self.make( debug=True )
        factory = MagicMock(); client = MagicMock()
        client.run.return_value = "<response/>"
        factory.get_client.return_value = client
        parsed = SimpleNamespace( command="go", args=None )   # args None -> "" branch
        with patch.object( mmm, "LlmClientFactory", return_value=factory ), \
             patch.object( mmm, "CommandResponse" ) as cr:
            cr.from_xml.return_value = parsed
            d = mm._get_ai_command( "go" )
        self.assertEqual( d[ "args" ], [ "" ] )

    def test_ai_command_xml_parsing_error( self ):
        mm = self.make( debug=True )
        factory = MagicMock(); client = MagicMock()
        client.run.return_value = "garbage"
        factory.get_client.return_value = client
        with patch.object( mmm, "LlmClientFactory", return_value=factory ), \
             patch.object( mmm, "CommandResponse" ) as cr:
            cr.from_xml.side_effect = XMLParsingError( "bad xml" )
            d = mm._get_ai_command( "anything" )
        self.assertEqual( d[ "command" ], "unknown" )
        self.assertEqual( d[ "args" ], [ "" ] )

    def test_ai_command_generic_exception( self ):
        mm = self.make( debug=True )
        factory = MagicMock(); client = MagicMock()
        client.run.return_value = "garbage"
        factory.get_client.return_value = client
        with patch.object( mmm, "LlmClientFactory", return_value=factory ), \
             patch.object( mmm, "CommandResponse" ) as cr:
            cr.from_xml.side_effect = ValueError( "boom" )
            d = mm._get_ai_command( "anything" )
        self.assertEqual( d[ "command" ], "unknown" )


class TestExtractArgs( _MungerBase ):
    """extract_args OpenAI completion seam (debug on + off)."""

    def _fake_openai_response( self, text ):
        choice = SimpleNamespace( text=text )
        return SimpleNamespace( choices=[ choice ] )

    def test_extract_args_returns_stripped( self ):
        mm = self.make()
        with patch.object( mmm, "openai" ) as oa:
            oa.completions.create.return_value = self._fake_openai_response( "  answer  " )
            out = mm.extract_args( "raw text", model="test-model" )
        self.assertEqual( out, [ "answer" ] )
        self.assertEqual( self.du.get_api_key.call_args[ 0 ][ 0 ], "openai" )

    def test_extract_args_debug_branch( self ):
        mm = self.make( debug=True )
        with patch.object( mmm, "openai" ) as oa:
            oa.completions.create.return_value = self._fake_openai_response( "x" )
            out = mm.extract_args( "raw", model="m" )
        self.assertEqual( out, [ "x" ] )


class TestHandleVoxCommandParsing( _MungerBase ):
    """_handle_vox_command_parsing: string-match hit vs AI-match fallback."""

    def test_string_match_hit_short_circuits( self ):
        mm = self.make()
        # "search ..." -> munge then _is_match startswith "search"
        trans, mode = mm._handle_vox_command_parsing( "search kittens" )
        self.assertEqual( mode, trans_mode_vox_cmd_browser )
        self.assertEqual( mm.results[ "command" ], "search" )

    def test_ai_match_fallback_when_no_string_match( self ):
        mm = self.make( use_string_matching=False, use_ai_matching=True )
        with patch.object( mm, "_get_ai_command", return_value={ "command": "ai" } ) as ai:
            trans, mode = mm._handle_vox_command_parsing( "do something weird" )
            ai.assert_called_once()
        self.assertEqual( mm.results, { "command": "ai" } )

    def test_no_matching_enabled_returns_plain( self ):
        mm = self.make( use_string_matching=False, use_ai_matching=False )
        trans, mode = mm._handle_vox_command_parsing( "whatever" )
        self.assertEqual( mode, trans_mode_vox_cmd_browser )

    def test_string_match_miss_then_ai( self ):
        mm = self.make( use_string_matching=True, use_ai_matching=True )
        with patch.object( mm, "_get_ai_command", return_value={ "command": "ai2" } ):
            mm._handle_vox_command_parsing( "no command match at all" )
        self.assertEqual( mm.results, { "command": "ai2" } )


class TestParseBranches( _MungerBase ):
    """parse() dispatch branches via construction (parse runs in __init__)."""

    def test_browser_prefix_repeat_with_last_response( self ):
        last = {
            "prefix"           : "p",
            "results"          : "r",
            "raw_transcription": "rt",
            "transcription"    : "prior trans",
            "mode"             : "prior mode",
        }
        mm = self.make( "repeat", prefix=trans_mode_vox_cmd_browser, last_response=last )
        self.assertEqual( mm.transcription, "prior trans" )
        self.assertEqual( mm.mode, "prior mode" )
        self.assertEqual( mm.prefix, "p" )

    def test_browser_prefix_repeat_without_last_response( self ):
        # last_response None -> "No previous response" arc; then handle_vox parsing
        mm = self.make( "repeat", prefix=trans_mode_vox_cmd_browser, last_response=None,
                        use_string_matching=False, use_ai_matching=False )
        self.assertEqual( mm.mode, trans_mode_vox_cmd_browser )

    def test_browser_via_startswith_strips_prefix( self ):
        mm = self.make( "multimodal browser search new tab", prefix="",
                        use_string_matching=True, use_ai_matching=False )
        self.assertEqual( mm.prefix, trans_mode_vox_cmd_browser )
        self.assertEqual( mm.mode, trans_mode_vox_cmd_browser )

    def test_short_input_default_mode( self ):
        mm = self.make( "hi there", prefix="" )
        self.assertEqual( mm.mode, trans_mode_text_punctuation )

    def test_long_input_first_words_in_modes( self ):
        mm = self.make( "multimodal text email rick at example dot com" )
        self.assertEqual( mm.mode, trans_mode_text_email )

    def test_first_words_not_in_modes_prefix_in_modes( self ):
        mm = self.make( "hello world foo", prefix=trans_mode_text_email )
        self.assertEqual( mm.mode, trans_mode_text_email )

    def test_first_words_not_in_modes_prefix_not_in_modes( self ):
        mm = self.make( "hello world foo", prefix="zzz unknown prefix" )
        # falls back to default method (text_punctuation)
        self.assertEqual( mm.mode, trans_mode_text_punctuation )

    def test_parse_debug_branch( self ):
        mm = self.make( "multimodal text raw hello world", debug=True )
        self.assertEqual( mm.mode, trans_mode_text_raw )

    def test_adhoc_prefix_cleanup_fixes_multimodal_and_toggle( self ):
        mm = self.make()
        self.assertEqual( mm._adhoc_prefix_cleanup( "multi-model toggle" ), "multimodal toggle" )
        self.assertEqual( mm._adhoc_prefix_cleanup( "multimodal taggle on" ), "multimodal toggle on" )


def isolated_unit_test():
    """
    Run the multimodal_munger unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness

    Raises:
        - None
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} multimodal_munger tests in {secs:.3f}s — {msg}" )
