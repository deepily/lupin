#!/usr/bin/env python3
"""
The open-ended "describe the document" ask is keyed on its own id, everywhere
(row 0c280989).

THE DEFECT. The expeditor's first-turn ask — "Which document should I use…? Describe
it or say the filename." — was matched by proxy entries keyed on that PROSE. Six
copies across six profiles, and unlike the two card entries the previous row
collapsed, these had drifted into THREE different wordings: podcast and presentation
carry a trailing "Describe it…" sentence, the three smoke profiles do not, and minimal
asks a shorter question entirely. A change in _handle_fuzzy_file_match would have
silently unanswered some and not others, and an unanswered ask is a run that cancels
with nothing to say why.

WHAT IS AND IS NOT COLLAPSED. The entries are re-keyed on card_id "document_describe";
their ANSWERS are left exactly as they were. Three values across the six — "latest" x2,
a mock research path x3, a mock source path x1 — are fixture choices belonging to
standalone profiles, not divergence to unify (Mr Radio's ruling, 2026-08-21).
Collapsing them would change what three profiles feed the expeditor while claiming to
fix a keying bug.

THE `agents` TAG IS LOAD-BEARING HERE and is asserted, not merely preserved. Three of
the six are scoped agents=["podcast"]. Before the id lookup learned to honour that tag,
one id would have let the podcast entry answer every agent's describe ask in those
multi-agent profiles — feeding a mock RESEARCH path to the presentation agent's
`source` argument.

RED ON REVERT: strip card_id off any one entry and
test_every_describe_entry_is_keyed_on_the_id fails naming the file; put a
question_pattern back on one and the straggler guard fails.
"""

import json
import os
import unittest

import cosa.utils.util as cu
from cosa.agents.runtime_argument_expeditor.expeditor import DOCUMENT_DESCRIBE_ASK_ID


SCRIPT_DIR = "/src/conf/notification-proxy-scripts"

# Every profile that answers the describe ask, with the answer it is expected to KEEP.
# The answers are written down here precisely because they must not drift: this test is
# what fails if someone "tidies" the six into one value.
EXPECTED = {
    "podcast.json"                : "latest",
    "minimal.json"                : "latest",
    "all-agents.json"             : "/tmp/mock-research-document.md",
    "expeditor-smoke.json"        : "/tmp/mock-research-document.md",
    "proxy-integration-test.json" : "/tmp/mock-research-document.md",
    "presentation.json"           : "/tmp/mock-source-document.md",
}

# The three multi-agent profiles whose entry MUST stay scoped to the podcast.
SCOPED_TO_PODCAST = ( "all-agents.json", "expeditor-smoke.json", "proxy-integration-test.json" )


def _load( filename ):
    with open( cu.get_project_root() + SCRIPT_DIR + "/" + filename, encoding="utf-8" ) as handle:
        return json.load( handle )


def _describe_entries( script ):
    return [ e for e in script[ "entries" ] if e.get( "card_id" ) == DOCUMENT_DESCRIBE_ASK_ID ]


class TestEveryProfileAnswersTheDescribeAsk( unittest.TestCase ):

    def test_every_describe_entry_is_keyed_on_the_id( self ):
        for filename in EXPECTED:
            with self.subTest( profile=filename ):
                entries = _describe_entries( _load( filename ) )
                self.assertEqual(
                    len( entries ), 1,
                    f"{filename} has {len( entries )} entries for the describe ask; expected "
                    f"exactly 1 — with none the run reaches the ask with nothing to answer it" )

    def test_the_id_is_the_one_the_code_actually_sends( self ):
        # Imported from the expeditor rather than retyped, so renaming it there fails
        # here instead of silently unanswering the ask in all six profiles at once.
        for filename in EXPECTED:
            with self.subTest( profile=filename ):
                entry = _describe_entries( _load( filename ) )[ 0 ]
                self.assertEqual( entry[ "card_id" ], DOCUMENT_DESCRIBE_ASK_ID )

    def test_each_profile_keeps_its_own_answer( self ):
        # THE RULING, pinned. Three different values across six profiles are fixture
        # choices, not divergence. This is what fails if a later reader decides the six
        # "should" agree — which would change what three profiles feed the expeditor
        # while claiming to fix a keying bug.
        for filename, answer in EXPECTED.items():
            with self.subTest( profile=filename ):
                self.assertEqual( _describe_entries( _load( filename ) )[ 0 ][ "answer" ], answer )

    def test_the_agent_scoping_survived_the_migration( self ):
        # Load-bearing, not decorative: with one id per ask, the tag is the only thing
        # keeping the podcast's entry from answering the presentation agent's `source`
        # in these three multi-agent profiles.
        for filename in EXPECTED:
            with self.subTest( profile=filename ):
                entry = _describe_entries( _load( filename ) )[ 0 ]
                if filename in SCOPED_TO_PODCAST:
                    self.assertEqual( entry[ "agents" ], [ "podcast" ] )
                else:
                    self.assertNotIn( "agents", entry,
                                      "a single-agent profile must not acquire a scope it "
                                      "never had — that would narrow it to nothing" )

    def test_the_entry_names_the_argument_it_fills( self ):
        # The id names the ASK; two agents ask it for different arguments, and arg_name
        # is the second narrowing filter the matcher applies.
        for filename in EXPECTED:
            with self.subTest( profile=filename ):
                entry = _describe_entries( _load( filename ) )[ 0 ]
                expected_arg = "source" if filename == "presentation.json" else "research"
                self.assertEqual( entry[ "arg_name" ], expected_arg )

    def test_the_entry_is_scoped_to_the_open_ended_types( self ):
        # It answers a free-text ask. Letting it claim multiple_choice would put a file
        # path in front of the choice card, which offers basenames and never a path.
        for filename in EXPECTED:
            with self.subTest( profile=filename ):
                types = _describe_entries( _load( filename ) )[ 0 ][ "response_types" ]
                self.assertNotIn( "multiple_choice", types )
                self.assertIn( "open_ended", types )

    def test_no_profile_still_keys_a_describe_ask_on_prose( self ):
        # The straggler guard. SCOPED TO open_ended DELIBERATELY, and that scoping is
        # the lesson from the sibling row: the equivalent guard for the choice card had
        # to be scoped to multiple_choice or it false-accused these very entries. The
        # trap is here in mirror image — widening this check would flag the two
        # multiple_choice card entries, which are correctly keyed on their own id.
        directory = cu.get_project_root() + SCRIPT_DIR
        offenders = []
        for filename in sorted( os.listdir( directory ) ):
            if not filename.endswith( ".json" ):
                continue
            for entry in _load( filename ).get( "entries", [] ):
                types = entry.get( "response_types", [] )
                if "open_ended" not in types and "open_ended_batch" not in types:
                    continue
                question = entry.get( "question_pattern", "" ).lower()
                if question.startswith( "which research document should i use" ) \
                   or question.startswith( "which document should i" ):
                    offenders.append( f"{filename}: {entry.get( 'question_pattern' )!r}" )
        self.assertEqual( offenders, [],
                          "these entries key the describe ask on its wording; key them on "
                          f"card_id {DOCUMENT_DESCRIBE_ASK_ID!r} instead" )

    def test_every_profile_file_still_parses( self ):
        # These are hand-edited JSON; a stray comma is a proxy that dies at startup
        # rather than at the ask.
        directory = cu.get_project_root() + SCRIPT_DIR
        for filename in sorted( os.listdir( directory ) ):
            if not filename.endswith( ".json" ):
                continue
            with self.subTest( profile=filename ):
                self.assertIsInstance( _load( filename ), dict )


if __name__ == "__main__":
    unittest.main()
