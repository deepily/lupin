#!/usr/bin/env python3
"""
Coverage-closure unit tests for expeditor.py (review-manager task, store row e010d5e2).

Test-only — NO production behavior changed. Targets the previously-uncovered
regions reported by `--cov-report=term-missing --cov-branch` on the expeditor dir:

  123-137     user_message_for_expedite_reason (reason → spoken/log map + default)
  209, 211    _classify_ask_failure (timeout / malformed / unreachable)
  534->533,
  536->533    collect() podcast special-handler skip branches
  1031-1075   _ask_choice_for_arg (all response branches)
  1090-1092   _describe_candidate (date prefix / none / bare basename)
  1121-1146   _choose_document_from_matches (pick / cancel / describe / off-set / collision)
  1466-1470   _handle_fuzzy_file_match first-turn choice card
  1519-1523   _handle_fuzzy_file_match post-describe choice card
  1639->1635  _match_description_to_files inner basename no-match loop

ALL boundaries mocked: notify_user_sync, ConfigurationManager, os.*, cu, the LLM
factory, and the fuzzy matcher. No LLM / network / filesystem.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python \
     -m pytest src/cosa/tests/unit/agents/runtime_argument_expeditor/test_expeditor_coverage_closure.py -v
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    ExtractionResult,
    ArgSpec,
    user_message_for_expedite_reason,
    BATCH_DECLINED,
    BATCH_UNREACHABLE,
    BATCH_TIMEOUT,
    BATCH_MALFORMED,
    BATCH_INCOMPLETE,
    BATCH_INTERNAL,
    DOC_CHOICE_CANCEL_LABEL,
    DOC_CHOICE_DESCRIBE_LABEL,
    DOC_CHOICE_DESCRIBE_SENTINEL,
)
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

from cosa.tests.unit.agents.runtime_argument_expeditor.test_expeditor_auto_resolve import (
    _mk_expeditor,
    DOCS,
)

PG = "agent router go to podcast generator"


def _resp( success=True, response_value="", status="ok", is_timeout=False ):
    """Minimal notify_user_sync response stand-in."""
    return SimpleNamespace(
        success        = success,
        response_value = response_value,
        status         = status,
        is_timeout     = is_timeout,
    )


# ─────────────────────────── 123-137 ───────────────────────────
class TestUserMessageForExpediteReason( unittest.TestCase ):

    def test_every_reason_maps_to_nonempty_pair( self ):
        for reason in ( BATCH_DECLINED, BATCH_UNREACHABLE, BATCH_TIMEOUT,
                        BATCH_MALFORMED, BATCH_INCOMPLETE, BATCH_INTERNAL ):
            spoken, log = user_message_for_expedite_reason( reason )
            self.assertTrue( spoken and log )

    def test_only_declined_attributes_to_user( self ):
        spoken, log = user_message_for_expedite_reason( BATCH_DECLINED )
        self.assertIn( "cancelled that job", spoken )
        self.assertIn( "the user declined", log )

    def test_none_and_unknown_fall_to_machine_failure_default( self ):
        for reason in ( None, "some-unrecognized-reason" ):
            spoken, log = user_message_for_expedite_reason( reason )
            self.assertIn( "unrecognized expedite failure reason", log )


# ─────────────────────────── 209, 211 ───────────────────────────
class TestClassifyAskFailure( unittest.TestCase ):

    def test_timeout( self ):
        r = _resp( success=False, is_timeout=True )
        self.assertEqual( RuntimeArgumentExpeditor._classify_ask_failure( r ), BATCH_TIMEOUT )

    def test_malformed_when_delivered_but_empty( self ):
        r = _resp( success=True, is_timeout=False )
        self.assertEqual( RuntimeArgumentExpeditor._classify_ask_failure( r ), BATCH_MALFORMED )

    def test_unreachable_otherwise( self ):
        r = _resp( success=False, is_timeout=False )
        self.assertEqual( RuntimeArgumentExpeditor._classify_ask_failure( r ), BATCH_UNREACHABLE )


# ─────────────────────────── 1031-1075 ───────────────────────────
class TestAskChoiceForArg( unittest.TestCase ):

    def _ask( self, response ):
        o = _mk_expeditor()
        o._job_id       = None
        o._bearer_token = None
        opts = [ { "label": "Alpha", "description": "a" }, { "label": "Beta", "description": "b" } ]
        with patch.object( ex_mod, "notify_user_sync", return_value=response ):
            return o, o._ask_choice_for_arg( "research", "Which?", opts, "u@x" )

    def test_delivery_failure_returns_none_and_classifies( self ):
        o, out = self._ask( _resp( success=False, is_timeout=True ) )
        self.assertIsNone( out )
        self.assertEqual( o._last_expedite_reason, BATCH_TIMEOUT )

    def test_plain_label_returned( self ):
        _o, out = self._ask( _resp( response_value="Alpha" ) )
        self.assertEqual( out, "Alpha" )

    def test_json_answers_shape_extracts_label( self ):
        _o, out = self._ask( _resp( response_value='{"answers": {"research": "Beta"}}' ) )
        self.assertEqual( out, "Beta" )

    def test_malformed_json_falls_through_to_raw( self ):
        _o, out = self._ask( _resp( response_value='{not valid json' ) )
        self.assertEqual( out, "{not valid json" )

    def test_cancel_label_declined( self ):
        o, out = self._ask( _resp( response_value=DOC_CHOICE_CANCEL_LABEL ) )
        self.assertIsNone( out )
        self.assertEqual( o._last_expedite_reason, BATCH_DECLINED )

    def test_describe_label_returns_sentinel( self ):
        _o, out = self._ask( _resp( response_value=DOC_CHOICE_DESCRIBE_LABEL ) )
        self.assertEqual( out, DOC_CHOICE_DESCRIBE_SENTINEL )


# ─────────────────────────── 1090-1092 ───────────────────────────
class TestDescribeCandidate( unittest.TestCase ):

    def test_with_date_prefix( self ):
        o = _mk_expeditor()
        self.assertEqual( o._describe_candidate( "io/dr/2026.08.14-kiss.md" ), "io/dr · 2026-08-14" )

    def test_without_date_prefix( self ):
        o = _mk_expeditor()
        self.assertEqual( o._describe_candidate( "io/dr/kiss.md" ), "io/dr" )

    def test_bare_basename_folder_is_dot( self ):
        o = _mk_expeditor()
        self.assertEqual( o._describe_candidate( "kiss.md" ), "." )


# ─────────────────────────── 1121-1146 ───────────────────────────
class TestChooseDocumentFromMatches( unittest.TestCase ):

    DMAP = {
        "io/dr/kiss.md"    : "/abs/io/dr/kiss.md",
        "io/dr/quantum.md" : "/abs/io/dr/quantum.md",
    }

    def test_pick_returns_absolute_path( self ):
        o = _mk_expeditor()
        with patch.object( o, "_ask_choice_for_arg", return_value="kiss.md" ):
            out = o._choose_document_from_matches( list( self.DMAP.keys() ), self.DMAP, "u@x" )
        self.assertEqual( out, "/abs/io/dr/kiss.md" )

    def test_cancel_returns_none( self ):
        o = _mk_expeditor()
        with patch.object( o, "_ask_choice_for_arg", return_value=None ):
            out = o._choose_document_from_matches( list( self.DMAP.keys() ), self.DMAP, "u@x" )
        self.assertIsNone( out )

    def test_describe_sentinel_passes_through( self ):
        o = _mk_expeditor()
        with patch.object( o, "_ask_choice_for_arg", return_value=DOC_CHOICE_DESCRIBE_SENTINEL ):
            out = o._choose_document_from_matches( list( self.DMAP.keys() ), self.DMAP, "u@x" )
        self.assertEqual( out, DOC_CHOICE_DESCRIBE_SENTINEL )

    def test_label_outside_option_set_is_malformed_none( self ):
        o = _mk_expeditor()
        with patch.object( o, "_ask_choice_for_arg", return_value="not-an-option" ):
            out = o._choose_document_from_matches( list( self.DMAP.keys() ), self.DMAP, "u@x" )
        self.assertIsNone( out )
        self.assertEqual( o._last_expedite_reason, BATCH_MALFORMED )

    def test_basename_collision_uses_full_rel_path_label( self ):
        o = _mk_expeditor()
        collide = { "a/x.md": "/abs/a/x.md", "b/x.md": "/abs/b/x.md" }
        # first "x.md" → label "x.md"; second collides → label is the full rel "b/x.md"
        with patch.object( o, "_ask_choice_for_arg", return_value="b/x.md" ):
            out = o._choose_document_from_matches( list( collide.keys() ), collide, "u@x" )
        self.assertEqual( out, "/abs/b/x.md" )


# ─────────────────────────── 534->533, 536->533 ───────────────────────────
class TestCollectPodcastSpecialHandlerSkips( unittest.TestCase ):

    def test_non_fuzzy_and_present_absent_args_are_skipped( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ PG ]
        # missing=[] → the interactive block is skipped; the podcast post-loop runs.
        # "other" handler → 534->533 continue; "research" fuzzy but NOT in final_args
        #   and NOT in missing → 536->533 continue. Neither invokes a matcher.
        extraction = ExtractionResult(
            final_args         = { "query": "AI" },
            missing            = [],
            fallback_questions = entry[ "fallback_questions" ],
            fallback_defaults  = {},
            special_handlers   = { "foo": "other", "research": "fuzzy_file_match" },
        )
        with patch.object( o, "_handle_fuzzy_file_match" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", return_value={ "query": "AI" } ), \
             patch.object( o, "_inject_system_args", return_value={ "query": "AI", "user_email": "u@x" } ):
            out = o.collect( extraction, PG, "make a podcast", ArgSpec.from_entry( entry ), "u@x", "s", "uid" )
        self.assertEqual( out[ "query" ], "AI" )
        fuzzy.assert_not_called()   # both branches were skips, no resolve fired


# ─────────────────────────── 1466-1470, 1519-1523 ───────────────────────────
class TestHandleFuzzyChoiceCard( unittest.TestCase ):
    """Drives _handle_fuzzy_file_match with a non-empty docs_map (mocked) to reach
    the podcast choice-card branches."""

    EMAIL = "u@example.com"

    def _run( self, *, original_question, match_result, chosen, use_choice_card=True ):
        o = _mk_expeditor()
        o._ask_for_arg = lambda *a, **k: "EXACT-PATH-ASKED"
        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as CM, \
             patch.object( ex_mod.cu, "get_project_root", return_value="/root" ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "kiss.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_match_description_to_files", return_value=match_result ), \
             patch.object( o, "_choose_document_from_matches", return_value=chosen ) as card:
            CM.return_value.get.side_effect = lambda key, default=None, **kw: default
            out = o._handle_fuzzy_file_match(
                self.EMAIL, agent_display_name="podcast generator",
                original_question=original_question, use_choice_card=use_choice_card,
            )
        return out, card

    def test_first_turn_card_pick_returns_chosen( self ):
        # original_question → auto pre-step; 2 matches + use_choice_card → first-turn card.
        out, card = self._run(
            original_question = "make a podcast from a kiss doc",
            match_result      = ( "fuzzy", [ "io/dr/kiss.md", "io/dr/quantum.md" ] ),
            chosen            = "/abs/io/dr/kiss.md",
        )
        card.assert_called_once()
        self.assertEqual( out, "/abs/io/dr/kiss.md" )

    def test_first_turn_card_describe_falls_through_to_ask( self ):
        out, _card = self._run(
            original_question = "make a podcast from a kiss doc",
            match_result      = ( "fuzzy", [ "io/dr/kiss.md", "io/dr/quantum.md" ] ),
            chosen            = DOC_CHOICE_DESCRIBE_SENTINEL,
        )
        self.assertEqual( out, "EXACT-PATH-ASKED" )

    def test_post_describe_card_pick_returns_chosen( self ):
        # No original_question → auto pre-step skipped, card_shown stays False; the
        # describe ask runs, then 2 matches + use_choice_card → post-describe card.
        out, card = self._run(
            original_question = None,
            match_result      = ( "fuzzy", [ "io/dr/kiss.md", "io/dr/quantum.md" ] ),
            chosen            = "/abs/io/dr/quantum.md",
        )
        card.assert_called_once()
        self.assertEqual( out, "/abs/io/dr/quantum.md" )

    def test_post_describe_card_describe_falls_through_to_exact_ask( self ):
        # No original_question → card_shown False; post-describe card returns the
        # describe-sentinel → does NOT return, falls to the exact-path ask (closes
        # the 1521->1523 partial branch).
        out, card = self._run(
            original_question = None,
            match_result      = ( "fuzzy", [ "io/dr/kiss.md", "io/dr/quantum.md" ] ),
            chosen            = DOC_CHOICE_DESCRIBE_SENTINEL,
        )
        card.assert_called_once()
        self.assertEqual( out, "EXACT-PATH-ASKED" )


# ─────────────────────────── 1639->1635 ───────────────────────────
class TestMatchInnerBasenameNoMatchLoop( unittest.TestCase ):

    def test_raw_match_matching_nothing_is_dropped( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "prefilter_docs_map_by_keywords",
                           side_effect=lambda m, d, debug=False: ( dict( m ), False ) ), \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="{description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor", MagicMock() ) as proc, \
             patch( "cosa.agents.io_models.xml_models.FuzzyFileMatchResponse.from_xml" ) as from_xml:
            proc.return_value.process_template.return_value = "{description} {file_list}"
            # a raw match neither a key NOR any candidate's basename → inner loop
            # exhausts with no break (1639->1635), match is dropped.
            from_xml.return_value.get_matches_list.return_value = [ "nonexistent-xyz.md" ]
            o.llm_factory = MagicMock()
            status, matches = o._match_description_to_files( "alpha bravo charlie", DOCS, MagicMock(), "/root" )
        self.assertEqual( status, "fuzzy" )
        self.assertEqual( matches, [] )


if __name__ == "__main__":
    unittest.main()
