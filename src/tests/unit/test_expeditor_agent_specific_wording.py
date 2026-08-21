#!/usr/bin/env python3
"""
Regression (row ea184d06): the expeditor's "which document?" prompt must carry
the CALLING agent's wording and field name, not the podcast's.

Before the fix, `_handle_fuzzy_file_match` hardcoded both:

    self._ask_for_arg(
        "research",
        "Which document should I use for the podcast? Describe it or say the filename.",
        user_email )

Every agent shares that helper, so a PRESENTATION job asked the user about
"the podcast" under a card titled "Missing: research" — while the correct
wording already sat unused in agent_registry.py under the presentation entry's
fallback_questions["source"].

Two things are asserted here, and each fails independently against the old code:
  1. the spoken question is the caller's, not the podcast's
  2. the card's title field is the caller's arg name ("source"), not "research"

Both remain asserted for the podcast path, which must be unchanged.

Scope note: these cover WORDING only, on the MISSING-arg path. The file-matching
behaviour (auto-resolve and the first-turn choice card) was podcast-fenced when this
file was written; row 5bc22180 removed that fence, and the presentation path is now
covered by test_expeditor_presentation_fences_generalized.py. The wording on the
present-but-unresolvable RESCUE path is covered there too — this fix never reached
that call site.
"""

import unittest
from unittest.mock import patch, MagicMock

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS

PODCAST_CMD      = "agent router go to podcast generator"
PRESENTATION_CMD = "agent router go to presentation generator"


def _mk_expeditor():
    return RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )


class TestAgentSpecificDocumentPrompt( unittest.TestCase ):

    EMAIL = "u@example.com"

    def _ask( self, arg_name, ask_question ):
        """
        Drive _handle_fuzzy_file_match to the open "which document?" ask and
        capture the (arg_name, question) it presents.

        Ensures:
            - returns the single (arg_name, question) pair passed to _ask_for_arg
        """
        o        = _mk_expeditor()
        o.debug  = False
        captured = []

        # One file exists, and the description matches nothing → falls straight
        # through to the open ask, which is the surface under test.
        o._ask_for_arg = lambda arg, q, email, **k: captured.append( ( arg, q ) ) or None

        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as CM, \
             patch.object( ex_mod.cu, "get_project_root", return_value="/root" ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "a.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_match_description_to_files", return_value=( "fuzzy", [] ) ):
            CM.return_value.get.side_effect = lambda key, default=None, **kw: default
            o._handle_fuzzy_file_match(
                self.EMAIL, agent_display_name="x",
                original_question=None, use_choice_card=False,
                arg_name=arg_name, ask_question=ask_question,
            )

        self.assertTrue( captured, "expected the open document ask to fire" )
        return captured[ 0 ]

    # ── the registry already holds the right words ───────────────────────────
    def test_registry_supplies_a_presentation_specific_question( self ):
        """The correct wording exists in the registry — the bug was never reading it."""
        q = JOB_ARG_CONTRACTS[ PRESENTATION_CMD ][ "fallback_questions" ][ "source" ]
        self.assertIn( "presentation", q.lower() )
        self.assertNotIn( "podcast", q.lower() )

    # ── 1. the question follows the caller ───────────────────────────────────
    def test_presentation_ask_does_not_mention_podcast( self ):
        """RED before the fix: the hardcoded string said 'the podcast'."""
        question = JOB_ARG_CONTRACTS[ PRESENTATION_CMD ][ "fallback_questions" ][ "source" ]
        _arg, asked = self._ask( "source", question )
        self.assertNotIn( "podcast", asked.lower(),
                          "a presentation job must not ask the user about 'the podcast'" )
        self.assertIn( "presentation", asked.lower() )

    def test_podcast_ask_still_mentions_podcast( self ):
        """The podcast path keeps its own wording — this fix must not flip it."""
        question = JOB_ARG_CONTRACTS[ PODCAST_CMD ][ "fallback_questions" ].get( "research" )
        _arg, asked = self._ask( "research", question )
        self.assertIn( "podcast", asked.lower() )

    def test_omitted_question_falls_back_to_podcast_phrasing( self ):
        """Callers that pass nothing keep the historical wording — no silent change."""
        _arg, asked = self._ask( "research", None )
        self.assertIn( "podcast", asked.lower() )

    # ── 2. the card title follows the caller ─────────────────────────────────
    def test_presentation_card_titled_source_not_research( self ):
        """RED before the fix: the card read 'Missing: research' on a presentation job."""
        arg, _asked = self._ask( "source", "Which document should I convert to a presentation?" )
        self.assertEqual( arg, "source" )

    def test_podcast_card_still_titled_research( self ):
        arg, _asked = self._ask( "research", None )
        self.assertEqual( arg, "research" )


class TestExpediteForwardsAgentIdentity( unittest.TestCase ):
    """
    The BEHAVIOURAL red. The tests above pin the helper's contract, but against
    the pre-fix code they fail with TypeError (the parameters did not exist) —
    that proves the signature changed, not that the wording was wrong.

    This one drives expedite() itself and asserts the DEFECT: that the caller
    forwards the calling agent's own field name and question down to the
    document prompt. Pre-fix the caller forwarded neither, so the presentation
    job inherited the podcast's words — which is exactly what Rick would have
    seen on stage.
    """

    def _expeditor( self ):
        o = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        o.debug                     = False
        o.verbose                   = False
        o.confirmation_prompt_path  = "/src/conf/prompts/runtime-argument-confirmation.txt"
        o.prompt_template_path      = "/src/conf/prompts/test.txt"
        o.llm_spec_key              = "test_key"
        o._job_id                   = None
        o._bearer_token             = None
        o._last_notification_status = None
        o.config_mgr                = MagicMock()
        o.config_mgr.get            = MagicMock( return_value=None )

        llm      = MagicMock()
        llm.run.return_value = (
            "<expeditor_response><all_required_met>false</all_required_met>"
            "<args_present></args_present><args_missing>source</args_missing>"
            "</expeditor_response>"
        )
        factory  = MagicMock()
        factory.get_client.return_value = llm
        o.llm_factory = factory
        return o

    def test_presentation_job_forwards_source_and_its_own_question( self ):
        seen = {}

        def _spy( self_, user_email, agent_display_name=None, **kwargs ):
            seen.update( kwargs )
            return "/io/deep-research/test@test.com/doc.md"

        o = self._expeditor()
        with patch( "cosa.utils.util.get_file_as_string", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ), \
             patch( "cosa.utils.util.get_project_root", return_value="/fake" ), \
             patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_cli_help", return_value="test help" ), \
             patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args", return_value=[ "source" ] ), \
             patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor.process_template", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ), \
             patch.object( RuntimeArgumentExpeditor, "_handle_fuzzy_file_match", _spy ), \
             patch.object( RuntimeArgumentExpeditor, "_batch_collect_args", return_value=( {}, "answered" ) ), \
             patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate", side_effect=lambda *a, **k: a[ 0 ] if a else {} ):
            o.expedite(
                command           = PRESENTATION_CMD,
                raw_args          = "",
                user_email        = "test@test.com",
                session_id        = "sess-1",
                user_id           = "uid-1",
                original_question = "turn my notes into a presentation",
            )

        self.assertEqual( seen.get( "arg_name" ), "source",
                          "the presentation job must title its prompt 'source', not 'research'" )
        asked = ( seen.get( "ask_question" ) or "" ).lower()
        self.assertIn( "presentation", asked )
        self.assertNotIn( "podcast", asked,
                          "a presentation job must not inherit the podcast's wording" )


if __name__ == "__main__":
    unittest.main()
