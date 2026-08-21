#!/usr/bin/env python3
"""
Every file-typed argument in the registry can reach the choice card, and something
can answer it (row a1420538, piece 4).

WHY THIS IS DERIVED AND NOT WRITTEN DOWN. The three defects this row cleans up were
all the same shape: a behaviour proven on the podcast, then reached by a second agent
that nobody re-checked. Row ea184d06 fixed hardcoded podcast wording on two prompts
and missed the third. Row 63ca8976 fixed it on the first-turn card and missed the
post-describe one — expeditor.py's second `_choose_document_from_matches` call site,
which passed neither the caller's argument name nor its display name, so a
presentation user who described their document and stayed ambiguous got a card titled
"Missing: research" asking about the podcast. A hand-written test would have listed
the call site that was already fixed.

So this test asks the REGISTRY which arguments are file-typed, and drives the real
resolver down BOTH card paths for each one. A new agent that declares a file argument
is covered the day it is declared; a third call site that forgets to pass the caller's
identity fails here whether or not anyone remembered to add a case.

WHAT IS PINNED, per file-typed argument:
  1. it is declared kind="file" with somewhere to look
  2. the FIRST-TURN card is shown, and speaks as the calling agent
  3. the POST-DESCRIBE card is shown, and speaks as the calling agent
  4. the profile that answers for that agent carries the generic card entry

RED ON REVERT, observed: restoring the bare `self._choose_document_from_matches(
matches, docs_map, user_email )` at the post-describe call site fails (3) —
"AssertionError: None != 'research' : the card is titled with the argument it is
filling". None rather than a wrong name because the call site passed NOTHING, leaving
the helper on its podcast defaults for every agent alike.
"""

import json
import unittest
from unittest.mock import patch

import cosa.utils.util as cu
import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    ArgSpec,
    DOCUMENT_CHOICE_CARD_ID,
)
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from unittest.mock import MagicMock


EMAIL = "u@example.com"

# command -> the proxy profile that answers for it. The profile file is chosen by the
# operator at launch, so it cannot be derived; what IS derived is the set of commands
# that must appear here at all — test_every_file_arg_has_a_profile_that_answers_it
# fails when a newly-declared file argument has no profile named.
PROFILE_FOR_COMMAND = {
    "agent router go to podcast generator"      : "podcast.json",
    "agent router go to presentation generator" : "presentation.json",
}


def _file_args():
    """Every ( command, arg_name, declaration ) the registry declares as a file."""
    found = []
    for command, entry in JOB_ARG_CONTRACTS.items():
        for arg_name, declaration in ( entry.get( "file_args" ) or {} ).items():
            found.append( ( command, arg_name, declaration ) )
    return found


def _mk_expeditor():
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    with patch.object( ex_mod, "LlmClientFactory", MagicMock() ):
        return RuntimeArgumentExpeditor( cfg, debug=False )


class TestEveryFileArgReachesTheCard( unittest.TestCase ):

    def test_the_registry_declares_at_least_one_file_arg( self ):
        # Guard against the whole suite passing vacuously: every test below iterates
        # this set, so an empty one would be green and prove nothing.
        self.assertTrue( _file_args(), "no file-typed arguments found in JOB_ARG_CONTRACTS" )

    def test_each_declaration_says_what_it_is_and_where_to_look( self ):
        for command, arg_name, declaration in _file_args():
            with self.subTest( command=command, arg=arg_name ):
                self.assertEqual( declaration[ "kind" ], "file" )
                roots = declaration[ "search_roots" ]
                self.assertTrue( roots, f"{command}/{arg_name} declares nowhere to look" )
                for root in roots:
                    self.assertIn( "path", root )

    def test_the_handler_and_the_declaration_agree( self ):
        # Two spellings of "this argument is a file" must not drift apart: the handler
        # tag drives dispatch, the declaration drives the search. An argument tagged
        # fuzzy_file_match with no declaration silently falls back to the shared
        # defaults and the PODCAST's config key, which is the derivation this row
        # removed.
        for command, entry in JOB_ARG_CONTRACTS.items():
            handlers = entry.get( "special_handlers" ) or {}
            declared = entry.get( "file_args" ) or {}
            for arg_name, handler in handlers.items():
                if handler != "fuzzy_file_match":
                    continue
                with self.subTest( command=command, arg=arg_name ):
                    self.assertIn(
                        arg_name, declared,
                        f"{command} routes '{arg_name}' through fuzzy_file_match but "
                        f"declares no file_args entry for it" )

    # ── the two card paths, driven for real ──────────────────────────────────
    def _drive( self, command, arg_name, match_results ):
        """
        Run the real _handle_fuzzy_file_match for one registered file argument and
        report every choice card it showed.

        match_results: one (status, matches) per _match_description_to_files call —
        the first is the auto-resolve attempt from the original utterance, the second
        the attempt on whatever the user typed.
        """
        entry = JOB_ARG_CONTRACTS[ command ]
        spec  = ArgSpec.from_entry( entry )
        o     = _mk_expeditor()

        cards = []
        def _fake_choose( matches, docs, email, **kwargs ):
            cards.append( kwargs )
            return "/abs/a.md"
        o._choose_document_from_matches = _fake_choose
        o._ask_for_arg = lambda arg, question, email, **k: "a description of my document"

        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as CM, \
             patch.object( ex_mod.cu, "get_project_root", return_value="/root" ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "a.md", "b.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_match_description_to_files", side_effect=list( match_results ) ):
            CM.return_value.get.side_effect = lambda key, default=None, **kw: default
            o._handle_fuzzy_file_match(
                EMAIL, spec.display_name,
                original_question="please use my document",
                use_choice_card=True,
                arg_name=arg_name,
                ask_question=spec.fallback_questions.get( arg_name ),
                file_arg=spec.file_args.get( arg_name ),
            )
        return cards, spec.display_name

    def _two_matches( self ):
        return ( "fuzzy", [ f"io/deep-research/{EMAIL}/a.md", f"io/deep-research/{EMAIL}/b.md" ] )

    def _assert_card_speaks_for( self, card, arg_name, display_name ):
        self.assertEqual( card.get( "arg_name" ), arg_name,
                          "the card is titled with the argument it is filling" )
        self.assertEqual( card.get( "agent_display_name" ), display_name,
                          "the card asks in the calling agent's terms" )
        # The end result the two above exist to produce, asserted directly so a future
        # refactor that renames the kwargs cannot keep this test green while the user
        # is asked about the wrong thing.
        question = RuntimeArgumentExpeditor._document_choice_question( card.get( "agent_display_name" ) )
        self.assertIn( display_name.lower().replace( " generator", "" ), question.lower() )

    def test_the_first_turn_card_speaks_as_the_calling_agent( self ):
        for command, arg_name, _declaration in _file_args():
            with self.subTest( command=command, arg=arg_name ):
                cards, display = self._drive( command, arg_name, [ self._two_matches() ] )
                self.assertEqual( len( cards ), 1, "the first-turn card must be shown" )
                self._assert_card_speaks_for( cards[ 0 ], arg_name, display )

    def test_the_post_describe_card_speaks_as_the_calling_agent( self ):
        # THE CALL SITE ROW 63ca8976 DID NOT REACH. The user's utterance names nothing
        # resolvable, they type a description, and it is still ambiguous — the second
        # card. It passed no identity at all, so it fell back to the podcast's.
        # RED ON REVERT: "None != 'research'" — the call site passed no identity at
        # all, so the helper used its podcast defaults whoever was asking.
        for command, arg_name, _declaration in _file_args():
            with self.subTest( command=command, arg=arg_name ):
                cards, display = self._drive(
                    command, arg_name,
                    [ ( "fuzzy", [] ), self._two_matches() ] )
                self.assertEqual( len( cards ), 1, "the post-describe card must be shown" )
                self._assert_card_speaks_for( cards[ 0 ], arg_name, display )

    # ── something can answer it ──────────────────────────────────────────────
    def test_every_file_arg_has_a_profile_that_answers_it( self ):
        for command, arg_name, _declaration in _file_args():
            with self.subTest( command=command, arg=arg_name ):
                self.assertIn(
                    command, PROFILE_FOR_COMMAND,
                    f"{command} declares a file argument but no proxy profile is named "
                    f"for it here — an automated run would reach the card and cancel" )

                path = ( cu.get_project_root() + "/src/conf/notification-proxy-scripts/"
                         + PROFILE_FOR_COMMAND[ command ] )
                with open( path, encoding="utf-8" ) as handle:
                    entries = json.load( handle )[ "entries" ]
                claims = [ e for e in entries if e.get( "card_id" ) == DOCUMENT_CHOICE_CARD_ID ]
                self.assertEqual(
                    len( claims ), 1,
                    f"{PROFILE_FOR_COMMAND[ command ]} has {len( claims )} entries claiming "
                    f"{DOCUMENT_CHOICE_CARD_ID!r}; expected exactly 1" )


if __name__ == "__main__":
    unittest.main()
