#!/usr/bin/env python3
"""
The document CHOICE CARD asks in the calling agent's terms (row 9046ef58).

THE THIRD SURFACE. Row ea184d06 fixed the podcast wording on the two `_ask_for_arg`
document prompts and never reached `_choose_document_from_matches`, which hardcoded
the arg name "research" and the question "Which document should I use for the
podcast?". That was invisible while podcast was the only consumer of the card. Row
5bc22180 gave presentation the card, and the hardcoding immediately produced a
presentation user being asked about the podcast under a card titled
"Missing: research".

WHAT EACH TEST BELOW WOULD SAY IF THE FIX WERE REVERTED is written into its comment,
because a wording assertion that has never been watched fail is decoration.

⚠️ THESE STRINGS ARE ALSO KEYS. The decision proxy's answer files match on
question_pattern, so the wording asserted here must equal the wording in
src/conf/notification-proxy-scripts/{podcast,presentation}.json. The pairing is
asserted in test_proxy_scripts_answer_the_choice_card.py — change one and that test
goes red, which is the point.
"""

import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor


PG = "agent router go to podcast generator"
PR = "agent router go to presentation generator"

PODCAST_NAME      = JOB_ARG_CONTRACTS[ PG ][ "display_name" ]
PRESENTATION_NAME = JOB_ARG_CONTRACTS[ PR ][ "display_name" ]


def _mk_expeditor():
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    with patch.object( ex_mod, "LlmClientFactory", MagicMock() ):
        return RuntimeArgumentExpeditor( cfg, debug=False )


class TestTheQuestionNamesTheCallingAgent( unittest.TestCase ):

    def test_presentation_is_never_asked_about_the_podcast( self ):
        # THE DEFECT, stated as an assertion.
        # RED ON REVERT: 'Which document should I use for the podcast?' contains
        # "podcast", so both assertions below fail.
        question = RuntimeArgumentExpeditor._document_choice_question( PRESENTATION_NAME )
        self.assertNotIn( "podcast", question.lower() )
        self.assertEqual( question, "Which document should I use for the presentation?" )

    def test_podcasts_own_wording_is_unchanged_to_the_byte( self ):
        # THE ONE SURFACE THAT MUST NOT MOVE. A podcast user has always been asked
        # this exact sentence, and it is also a key in podcast.json — a moved key is
        # an unanswerable card. Passing the display name through unchanged would
        # produce "for the podcast generator", which is why the trailing word is
        # dropped rather than lower-cased and left alone.
        self.assertEqual(
            RuntimeArgumentExpeditor._document_choice_question( PODCAST_NAME ),
            "Which document should I use for the podcast?",
        )
        self.assertEqual(
            RuntimeArgumentExpeditor._document_choice_question( PODCAST_NAME ),
            RuntimeArgumentExpeditor._document_choice_question( None ),
        )

    def test_a_name_without_the_trailing_word_is_used_whole( self ):
        # The strip is a courtesy, not a parser. An agent whose display name does not
        # end in "Generator" — say a future "Deep Research" consumer of the same card
        # — keeps its name intact rather than losing a word to a rule written for two
        # other agents.
        self.assertEqual(
            RuntimeArgumentExpeditor._document_choice_question( "Deep Research" ),
            "Which document should I use for the deep research?",
        )

    def test_a_missing_display_name_falls_back_to_the_historic_wording( self ):
        # The default exists so an older caller that passes no name behaves exactly
        # as it always did rather than producing a question with a hole in it.
        self.assertEqual(
            RuntimeArgumentExpeditor._document_choice_question( None ),
            "Which document should I use for the podcast?",
        )
        self.assertEqual(
            RuntimeArgumentExpeditor._document_choice_question( "" ),
            "Which document should I use for the podcast?",
        )


class TestTheCardCarriesTheCallersFieldName( unittest.TestCase ):

    DOCS = {
        "io/deep-research/u@e.com/a.md" : "/abs/a.md",
        "io/deep-research/u@e.com/b.md" : "/abs/b.md",
    }

    def _card_args( self, **kwargs ):
        """Drive the card and capture the (arg_name, question) it presented."""
        o        = _mk_expeditor()
        captured = {}

        def _fake_choice( arg_name, question, options, user_email, **_kw ):
            captured[ "arg_name" ] = arg_name
            captured[ "question" ] = question
            return None

        o._ask_choice_for_arg = _fake_choice
        o._choose_document_from_matches( list( self.DOCS.keys() ), self.DOCS, "u@e.com", **kwargs )
        return captured

    def test_presentation_card_is_titled_with_source_not_research( self ):
        # RED ON REVERT: AssertionError: 'research' != 'source' — the card title the
        # user reads is "Missing: <arg_name>", so this is the "Missing: research"
        # half of the pr-a10a55aa defect.
        captured = self._card_args( arg_name="source", agent_display_name=PRESENTATION_NAME )
        self.assertEqual( captured[ "arg_name" ], "source" )
        self.assertNotIn( "podcast", captured[ "question" ].lower() )

    def test_podcast_card_is_unchanged( self ):
        captured = self._card_args( arg_name="research", agent_display_name=PODCAST_NAME )
        self.assertEqual( captured[ "arg_name" ], "research" )
        self.assertEqual( captured[ "question" ], "Which document should I use for the podcast?" )

    def test_defaults_reproduce_the_pre_row_behaviour_exactly( self ):
        # Called with neither kwarg — the shape every pre-existing caller had.
        captured = self._card_args()
        self.assertEqual( captured[ "arg_name" ], "research" )
        self.assertEqual( captured[ "question" ], "Which document should I use for the podcast?" )


if __name__ == "__main__":
    unittest.main()
