#!/usr/bin/env python3
"""
Every agent that can be shown the document choice card has an answer for it (row 9046ef58).

THE FAILURE THIS PREVENTS, observed rather than imagined: on 2026-08-21 a live
presentation job on :7999 reached the card and the run CANCELLED at it —
`[Expeditor] User cancelled at arg 'source'` — because the decision proxy's answer
file had no entry matching the question. Nothing was broken; the proxy simply had
nothing to say, and a cancel looks exactly like a user declining.

WHY A TEST AND NOT A NOTE. The answer files match on `question_pattern`, a plain
string. Nothing in the code refers to those files, so the wording and the key can
drift apart silently and the only symptom is an automated run that cancels for no
visible reason. This test is the link: it derives the question from the CODE and
demands the FILE carry it.

RED ON REVERT, per arm:
  · remove either entry            -> "podcast.json has no entry for the document choice card"
  · change the wording in the code -> the derived question stops matching the file's key
  · change the key in the file     -> same failure from the other side

⚠️ Podcast's entry is NEW too. It has had the card since row bd0ce120 and never had an
answer for it; nobody hit it because a run must land on 2-to-cap matches to see the
card. This row's live cancel was presentation's, but the hole was already there.
"""

import json
import os
import unittest

import cosa.utils.util as cu
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor


SCRIPT_DIR = "/src/conf/notification-proxy-scripts"

# profile file -> the command whose card it must answer
CARD_CONSUMERS = {
    "podcast.json"      : "agent router go to podcast generator",
    "presentation.json" : "agent router go to presentation generator",
}


def _load( filename ):
    with open( cu.get_project_root() + SCRIPT_DIR + "/" + filename, encoding="utf-8" ) as handle:
        return json.load( handle )


def _choice_card_entries( script ):
    return [ e for e in script[ "entries" ]
             if "multiple_choice" in e.get( "response_types", [] )
             and e[ "question_pattern" ].startswith( "Which document should I use" ) ]


class TestEveryCardConsumerHasAnAnswer( unittest.TestCase ):

    def test_each_profile_carries_exactly_one_choice_card_entry( self ):
        for filename in CARD_CONSUMERS:
            with self.subTest( profile=filename ):
                entries = _choice_card_entries( _load( filename ) )
                self.assertEqual(
                    len( entries ), 1,
                    f"{filename} has {len( entries )} entries for the document choice card; "
                    f"expected exactly 1 — with none the proxy cancels at the card, "
                    f"with two the matcher is given contradictory guidance"
                )

    def test_the_key_equals_what_the_code_actually_asks( self ):
        # THE LINK. The question is derived from the code, not retyped here, so a
        # wording change in either place fails this rather than silently unanswering
        # a card.
        for filename, command in CARD_CONSUMERS.items():
            with self.subTest( profile=filename ):
                display  = JOB_ARG_CONTRACTS[ command ][ "display_name" ]
                expected = RuntimeArgumentExpeditor._document_choice_question( display )
                entry    = _choice_card_entries( _load( filename ) )[ 0 ]
                self.assertEqual( entry[ "question_pattern" ], expected )

    def test_the_entry_names_the_agents_own_argument( self ):
        for filename, command in CARD_CONSUMERS.items():
            with self.subTest( profile=filename ):
                handlers = JOB_ARG_CONTRACTS[ command ][ "special_handlers" ]
                fuzzy    = [ arg for arg, h in handlers.items() if h == "fuzzy_file_match" ]
                entry    = _choice_card_entries( _load( filename ) )[ 0 ]
                self.assertEqual( entry[ "arg_name" ], fuzzy[ 0 ] )

    def test_the_answer_is_a_directive_not_a_filename( self ):
        # The option labels are candidate basenames discovered at run time, so a fixed
        # filename could never match one. If someone "fixes" this entry by putting a
        # path in it, the matcher returns a label the card cannot produce and the
        # expeditor rejects it as malformed — a cancel again, by a different route.
        for filename in CARD_CONSUMERS:
            with self.subTest( profile=filename ):
                answer = _choice_card_entries( _load( filename ) )[ 0 ][ "answer" ]
                self.assertNotIn( ".md", answer )
                self.assertNotIn( "/", answer )
                self.assertIn( "option", answer.lower() )

    def test_presentation_is_not_asked_about_the_podcast( self ):
        # The wording defect and the answer-file gap were one piece of work: an entry
        # keyed to the old hardcoded question would have been a test of the bug.
        entry = _choice_card_entries( _load( "presentation.json" ) )[ 0 ]
        self.assertNotIn( "podcast", entry[ "question_pattern" ].lower() )

    def test_every_profile_file_still_parses( self ):
        # Cheap whole-directory guard: these are hand-edited JSON, and a trailing
        # comma here is a proxy that dies at startup rather than at the card.
        directory = cu.get_project_root() + SCRIPT_DIR
        for filename in sorted( os.listdir( directory ) ):
            if not filename.endswith( ".json" ):
                continue
            with self.subTest( profile=filename ):
                self.assertIsInstance( _load( filename ), dict )


if __name__ == "__main__":
    unittest.main()
