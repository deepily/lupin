#!/usr/bin/env python3
"""
Every agent that can be shown the document choice card has an answer for it
(row 9046ef58, re-keyed on the card's own id by row a1420538).

THE FAILURE THIS PREVENTS, observed rather than imagined: on 2026-08-21 a live
presentation job on :7999 reached the card and the run CANCELLED at it —
`[Expeditor] User cancelled at arg 'source'` — because the decision proxy's answer
file had no entry matching the question. Nothing was broken; the proxy simply had
nothing to say, and a cancel looks exactly like a user declining.

WHAT CHANGED, AND WHY THE TEST CHANGED WITH IT. The entries used to be keyed on
`question_pattern` — the question the expeditor DERIVES per calling agent, "for the
podcast" or "for the presentation". That made prose the join key between code and
config, so this test's job was to derive the question from the code and demand the
file carry it byte for byte. It worked, and it was the wrong shape: every new agent
needed its own copy of an otherwise identical entry, and the pairing had to be
re-pinned each time.

The card now names itself. `card_id` rides in `response_options`, the matcher claims
the entry on an exact id match before the model is asked anything, and ONE generic
entry answers the card for every agent. So what is pinned here is no longer a string
pair — it is that each profile carries the generic entry, that it says nothing about
any particular agent, and that its answer is a sentinel rather than a filename.

RED ON REVERT, per arm:
  · remove either entry        -> "podcast.json has 0 entries for the document choice card"
  · re-key one on prose        -> the id lookup finds nothing; same failure
  · put a path in the answer   -> "must be one of ('__first_option__', '__last_option__')"
  · name an agent in the entry -> "the generic entry must not mention 'podcast'"
"""

import json
import os
import unittest

import cosa.utils.util as cu
from cosa.agents.notification_proxy import option_sentinels
from cosa.agents.runtime_argument_expeditor.expeditor import DOCUMENT_CHOICE_CARD_ID


SCRIPT_DIR = "/src/conf/notification-proxy-scripts"

# The profile files whose agent can reach the card. Row a1420538 piece 4 replaces this
# literal with an iteration over every file-typed argument in the registry.
CARD_CONSUMERS = ( "podcast.json", "presentation.json" )

# Words that would mean the entry had drifted back to being agent-specific.
AGENT_WORDS = ( "podcast", "presentation" )


def _load( filename ):
    with open( cu.get_project_root() + SCRIPT_DIR + "/" + filename, encoding="utf-8" ) as handle:
        return json.load( handle )


def _choice_card_entries( script ):
    return [ e for e in script[ "entries" ] if e.get( "card_id" ) == DOCUMENT_CHOICE_CARD_ID ]


class TestEveryCardConsumerHasAnAnswer( unittest.TestCase ):

    def test_each_profile_carries_exactly_one_choice_card_entry( self ):
        for filename in CARD_CONSUMERS:
            with self.subTest( profile=filename ):
                entries = _choice_card_entries( _load( filename ) )
                self.assertEqual(
                    len( entries ), 1,
                    f"{filename} has {len( entries )} entries for the document choice card; "
                    f"expected exactly 1 — with none the proxy cancels at the card, "
                    f"with two the matcher claims whichever comes first"
                )

    def test_the_id_is_the_one_the_code_actually_sends( self ):
        # THE LINK, in its new form. The id is imported from the expeditor rather than
        # retyped, so renaming it there fails this instead of silently unanswering the
        # card in every profile at once.
        for filename in CARD_CONSUMERS:
            with self.subTest( profile=filename ):
                entry = _choice_card_entries( _load( filename ) )[ 0 ]
                self.assertEqual( entry[ "card_id" ], DOCUMENT_CHOICE_CARD_ID )

    def test_the_entry_is_generic( self ):
        # The whole point of the id. An entry that names an agent — in its key, its
        # arg_name, or its comment — is one that has to be copied for the next agent,
        # which is the duplication this row removed.
        for filename in CARD_CONSUMERS:
            with self.subTest( profile=filename ):
                entry = _choice_card_entries( _load( filename ) )[ 0 ]
                self.assertNotIn( "question_pattern", entry,
                                  "the card is claimed by id; a prose key would take precedence "
                                  "in the reader's mind and drift from the code again" )
                self.assertNotIn( "arg_name", entry,
                                  "the arg differs per agent — naming one makes the entry "
                                  "agent-specific again" )
                for word in AGENT_WORDS:
                    self.assertNotIn(
                        word, entry.get( "_comment", "" ).lower().replace( "podcasts", "" )
                              .replace( "presentations", "" ),
                        f"the generic entry must not mention {word!r}" )

    def test_the_answer_is_a_positional_sentinel_not_a_filename( self ):
        # The option labels are candidate basenames discovered at run time, so a fixed
        # filename could never match one. If someone "fixes" this entry by putting a
        # path in it, the answer reaches the card as a label it never offered — which
        # the responder now refuses outright (row a1420538 piece 3), so the run takes a
        # visible skip instead of a mystery cancel. Still wrong; just no longer silent.
        #
        # It must be a SENTINEL and not merely prose. Prose was the first attempt: the
        # entry read "Pick the first document option in the list", and on a live run
        # the matcher returned that sentence verbatim as the answer.
        for filename in CARD_CONSUMERS:
            with self.subTest( profile=filename ):
                answer = _choice_card_entries( _load( filename ) )[ 0 ][ "answer" ]
                self.assertTrue(
                    option_sentinels.is_sentinel( answer ),
                    f"{filename}'s choice-card answer must be one of "
                    f"{option_sentinels.SENTINELS}, not {answer!r} — anything else is "
                    f"submitted verbatim and rejected as an unknown label"
                )

    def test_the_entry_is_scoped_to_multiple_choice( self ):
        # The card is a multiple-choice ask. Leaving the type off would let this entry
        # claim the OPEN-ENDED "describe the document" ask as well, whose legitimate
        # answer is a file path — and a sentinel submitted there resolves against a
        # card with no options at all.
        for filename in CARD_CONSUMERS:
            with self.subTest( profile=filename ):
                entry = _choice_card_entries( _load( filename ) )[ 0 ]
                self.assertEqual( entry[ "response_types" ], [ "multiple_choice" ] )

    def test_no_profile_still_keys_a_document_choice_card_on_prose( self ):
        # The straggler guard. A prose-keyed multiple-choice entry for this card is the
        # shape that had to be duplicated per agent; if one reappears anywhere in the
        # directory, it fails here rather than hanging a smoke run.
        #
        # SCOPED TO multiple_choice DELIBERATELY. Six OPEN-ENDED entries across the
        # directory legitimately ask "Which research document should I use…" and answer
        # with a file path — that is the describe-it ask, a different surface. Widening
        # this check to every response type would false-accuse all six.
        directory = cu.get_project_root() + SCRIPT_DIR
        offenders = []
        for filename in sorted( os.listdir( directory ) ):
            if not filename.endswith( ".json" ):
                continue
            for entry in _load( filename ).get( "entries", [] ):
                if "multiple_choice" not in entry.get( "response_types", [] ):
                    continue
                question = entry.get( "question_pattern", "" )
                if question.lower().startswith( "which document should i use" ):
                    offenders.append( f"{filename}: {question!r}" )
        self.assertEqual( offenders, [],
                          "these entries key the document choice card on its wording; "
                          "key them on card_id instead" )

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
