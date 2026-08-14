"""
Unit tests for the auto-resolve of Rick's document (row bd0ce120, Option C→D).

Two units under test in expeditor.py:
  1. _match_description_to_files — the shared PURE matcher (no prompts): exact /
     basename / too_broad / fuzzy / error branches. LLM + prefilter boundaries mocked.
  2. _handle_fuzzy_file_match auto pre-step — the DECISION: with original_question
     that resolves to exactly one file, skip the "which document?" prompt; 0 or 2+
     falls through to the interactive ask, exactly as before. The chosen file is
     named to the user by the _confirm_and_iterate summary (Step 8), the veto surface.

ALL boundaries mocked: config_mgr, LlmClientFactory, prefilter, FuzzyFileMatchResponse,
cu file/path helpers, os.path.exists/os.listdir/os.walk, ConfigurationManager. No LLM,
no network, no filesystem — and NO seeded files (the near-miss lives in a dict, never
on disk).

The podcast-vs-presentation SCOPE FENCE (only the podcast command forwards
original_question) is tested at the caller level in test_expeditor_flow.py.

Created 2026-08-04 by Clayton 😎 (SWE crew lane B).
"""

import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor


def _mk_expeditor( debug=False ):
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    with patch.object( ex_mod, "LlmClientFactory", MagicMock() ):
        o = RuntimeArgumentExpeditor( cfg, debug=debug )
    o.prompt_template_path = "/t.txt"
    o.llm_spec_key         = "spec"
    return o


DOCS = {
    "io/deep-research/u/kiss-protocol.md" : "/abs/kiss-protocol.md",
    "io/deep-research/u/quantum.md"       : "/abs/quantum.md",
}


class TestMatchDescriptionToFiles( unittest.TestCase ):
    """The shared pure matcher — every branch, boundaries mocked."""

    def test_exact_relative_path_hit( self ):
        o = _mk_expeditor()
        status, matches = o._match_description_to_files(
            "io/deep-research/u/kiss-protocol.md", DOCS, MagicMock(), "/root"
        )
        self.assertEqual( status, "exact" )
        self.assertEqual( matches, [ "io/deep-research/u/kiss-protocol.md" ] )

    def test_basename_hit( self ):
        o = _mk_expeditor()
        status, matches = o._match_description_to_files( "quantum.md", DOCS, MagicMock(), "/root" )
        self.assertEqual( status, "exact" )
        self.assertEqual( matches, [ "io/deep-research/u/quantum.md" ] )

    def test_too_broad_when_prefilter_arbitrary( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "prefilter_docs_map_by_keywords", return_value=( {}, True ) ):
            status, matches = o._match_description_to_files( "vague words", DOCS, MagicMock(), "/root" )
        self.assertEqual( status, "too_broad" )
        self.assertEqual( matches, [] )

    def test_does_not_mutate_callers_docs_map( self ):
        """The prefilter runs on a COPY — the caller's docs_map must be untouched."""
        o = _mk_expeditor()
        original = dict( DOCS )
        # "alpha bravo charlie" shares NO keyword with either DOCS path, so the
        # deterministic dominant-match check declines and the LLM path runs.
        with patch.object( ex_mod, "prefilter_docs_map_by_keywords",
                           side_effect=lambda m, d, debug=False: ( { k: m[ k ] for k in list( m )[ :1 ] }, False ) ) as pf, \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="{description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor", MagicMock() ) as proc, \
             patch( "cosa.agents.io_models.xml_models.FuzzyFileMatchResponse.from_xml" ) as from_xml:
            proc.return_value.process_template.return_value = "{description} {file_list}"
            from_xml.return_value.get_matches_list.return_value = []
            o.llm_factory = MagicMock()
            o._match_description_to_files( "alpha bravo charlie", DOCS, MagicMock(), "/root" )
        passed = pf.call_args[ 0 ][ 0 ]
        self.assertIsNot( passed, DOCS )
        self.assertEqual( DOCS, original )

    def _fuzzy( self, o, raw_matches ):
        with patch.object( ex_mod, "prefilter_docs_map_by_keywords",
                           side_effect=lambda m, d, debug=False: ( dict( m ), False ) ), \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="{description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor", MagicMock() ) as proc, \
             patch( "cosa.agents.io_models.xml_models.FuzzyFileMatchResponse.from_xml" ) as from_xml:
            proc.return_value.process_template.return_value = "{description} {file_list}"
            from_xml.return_value.get_matches_list.return_value = raw_matches
            o.llm_factory = MagicMock()
            # No-overlap description so the deterministic dominant-match check
            # declines and the LLM (mocked) path under test actually runs.
            return o._match_description_to_files( "alpha bravo charlie", DOCS, MagicMock(), "/root" )

    def test_fuzzy_single_match( self ):
        o = _mk_expeditor()
        status, matches = self._fuzzy( o, [ "io/deep-research/u/kiss-protocol.md" ] )
        self.assertEqual( status, "fuzzy" )
        self.assertEqual( matches, [ "io/deep-research/u/kiss-protocol.md" ] )

    def test_fuzzy_two_matches_via_basename( self ):
        """A raw match given as a bare filename resolves to its relative path."""
        o = _mk_expeditor()
        status, matches = self._fuzzy( o, [ "kiss-protocol.md", "quantum.md" ] )
        self.assertEqual( status, "fuzzy" )
        self.assertEqual( set( matches ), { "io/deep-research/u/kiss-protocol.md", "io/deep-research/u/quantum.md" } )

    def test_fuzzy_no_matches( self ):
        o = _mk_expeditor()
        status, matches = self._fuzzy( o, [] )
        self.assertEqual( status, "fuzzy" )
        self.assertEqual( matches, [] )

    def test_error_when_llm_raises( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "prefilter_docs_map_by_keywords",
                           side_effect=lambda m, d, debug=False: ( dict( m ), False ) ), \
             patch.object( ex_mod.cu, "get_file_as_string", side_effect=RuntimeError( "boom" ) ):
            status, matches = o._match_description_to_files( "alpha bravo charlie", DOCS, MagicMock(), "/root" )
        self.assertEqual( status, "error" )
        self.assertEqual( matches, [] )

    def test_dominant_keyword_match_resolves_deterministically( self ):
        """One candidate dominates keyword overlap → 'exact', LLM never consulted."""
        o = _mk_expeditor()
        # "kiss protocol" overlaps kiss-protocol.md (2) and quantum.md (0) → unique top.
        # Patch the LLM boundary to explode: if it is reached, the test fails loudly.
        with patch.object( ex_mod, "prefilter_docs_map_by_keywords",
                           side_effect=AssertionError( "LLM path must not run on a dominant match" ) ):
            status, matches = o._match_description_to_files( "kiss protocol", DOCS, MagicMock(), "/root" )
        self.assertEqual( status, "exact" )
        self.assertEqual( matches, [ "io/deep-research/u/kiss-protocol.md" ] )

    def test_top_score_tie_falls_through_to_llm( self ):
        """A keyword shared equally by two candidates is a tie → LLM decides (unchanged)."""
        o = _mk_expeditor()
        # "deep research" scores 2 on BOTH DOCS paths (io/DEEP-RESEARCH/...) → tie.
        status, matches = self._fuzzy_desc( o, "deep research", [ "io/deep-research/u/quantum.md" ] )
        self.assertEqual( status, "fuzzy" )
        self.assertEqual( matches, [ "io/deep-research/u/quantum.md" ] )

    def _fuzzy_desc( self, o, description, raw_matches ):
        """Like _fuzzy but with a caller-supplied description (to exercise a tie)."""
        with patch.object( ex_mod, "prefilter_docs_map_by_keywords",
                           side_effect=lambda m, d, debug=False: ( dict( m ), False ) ), \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="{description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor", MagicMock() ) as proc, \
             patch( "cosa.agents.io_models.xml_models.FuzzyFileMatchResponse.from_xml" ) as from_xml:
            proc.return_value.process_template.return_value = "{description} {file_list}"
            from_xml.return_value.get_matches_list.return_value = raw_matches
            o.llm_factory = MagicMock()
            return o._match_description_to_files( description, DOCS, MagicMock(), "/root" )


class TestAutoResolvePreStep( unittest.TestCase ):
    """
    _handle_fuzzy_file_match auto pre-step DECISION. docs_map building + config are
    mocked so only the skip-or-ask decision is exercised.
    """

    # The docs_map key the handler builds for user "u@example.com" + file
    # "kiss-protocol.md": f"io/deep-research/{email}/{f}". The single-match result
    # MUST be a real key so the handler's docs_map[ rel ] dereference succeeds.
    EMAIL   = "u@example.com"
    DOC_REL = "io/deep-research/u@example.com/kiss-protocol.md"

    def _run( self, original_question, match_result ):
        """Drive the handler with a non-empty docs_map and a controlled matcher.

        Returns ( resolved_value, ask_call_count, matcher_mock ).
        """
        o = _mk_expeditor()
        ask_calls = []
        o._ask_for_arg = lambda *a, **k: ask_calls.append( a ) or self.DOC_REL

        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as CM, \
             patch.object( ex_mod.cu, "get_project_root", return_value="/root" ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "kiss-protocol.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_match_description_to_files", return_value=match_result ) as m:
            # the internal ConfigurationManager.get must return the default so the
            # search-path logic resolves to a real string, not a MagicMock.
            CM.return_value.get.side_effect = lambda key, default=None, **kw: default
            resolved = o._handle_fuzzy_file_match(
                self.EMAIL, agent_display_name="podcast generator",
                original_question=original_question
            )
        return resolved, len( ask_calls ), m

    def test_auto_resolves_and_skips_prompt_on_single_match( self ):
        resolved, ask_count, matcher = self._run(
            "make a podcast from my KISS explainer",
            ( "fuzzy", [ self.DOC_REL ] ),
        )
        # matcher was called with the ORIGINAL question (auto pre-step)
        self.assertEqual( matcher.call_args[ 0 ][ 0 ], "make a podcast from my KISS explainer" )
        # resolved to the abs path from docs_map WITHOUT any prompt
        self.assertTrue( str( resolved ).endswith( "kiss-protocol.md" ) )
        self.assertEqual( ask_count, 0, "auto-resolve must NOT prompt on a single match" )

    def test_falls_through_and_asks_on_two_matches( self ):
        # Two matches from the auto pre-step → must NOT auto-resolve; asks as before.
        resolved, ask_count, _m = self._run(
            "make a podcast from a KISS doc",
            ( "fuzzy", [ self.DOC_REL, "io/deep-research/u@example.com/quantum.md" ] ),
        )
        self.assertGreaterEqual( ask_count, 1, "2+ matches must fall through to a prompt" )

    def test_falls_through_and_asks_on_zero_matches( self ):
        # Zero matches from the auto pre-step → must NOT auto-resolve; asks as before.
        resolved, ask_count, _m = self._run(
            "make a podcast from something unfindable",
            ( "fuzzy", [] ),
        )
        self.assertGreaterEqual( ask_count, 1, "0 matches must fall through to a prompt" )

    def test_asks_when_no_original_question( self ):
        # Control: with no original_question, the auto pre-step is skipped entirely.
        resolved, ask_count, _m = self._run(
            None,
            ( "fuzzy", [ self.DOC_REL ] ),
        )
        self.assertGreaterEqual( ask_count, 1, "no original_question ⇒ must ask, unchanged" )


if __name__ == "__main__":
    unittest.main()
