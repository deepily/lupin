"""
The three podcast-only fences are gone: presentation gets the same file resolution.

Row 5bc22180, Approach A from
`src/rnd/v0.2.0/2026.08.05-expeditor-podcast-fences-generalization-proposal.md`
(Clayton, reviewed PASS by Rachel), governed by
`src/rnd/v0.2.0/2026.08.05-qa-card-presentation-path-podcast-only-fences.md`.

WHAT THE FENCES WERE. Three features in `expeditor.py` were gated on
`command == "agent router go to podcast generator"`, so the presentation
generator's `source` arg — the only other `fuzzy_file_match` consumer — never got
them: auto-resolve from the utterance, the first-turn choice card, and the
present-but-unresolvable rescue. The third is not cosmetic: a pre-filled topic
phrase like "KISS" is present-not-missing, so nothing resolved it and the job died
with `FileNotFoundError: Source document not found: KISS` (Rachel ran it).

WHICH TESTS HERE MUST HAVE BEEN RED BEFORE THE FIX, AND WHICH MUST NOT.
  · The four presentation behaviours below were each captured RED on the pre-fix
    tree and green after. A green with no red before is indistinguishable from a
    test that asserts nothing.
  · The podcast and TFE guards are UNCHANGED-BOTH-SIDES BY DESIGN and pass green on
    the pre-fix tree too. They must never be held to red-on-HEAD (Rachel section
    6.2) — their whole job is to stay green while the shared handler is edited
    underneath them.

WHY TFE IS EXEMPT BY CONSTRUCTION, not by a fence: `resume_from` routes through
`tfe_checkpoint_match`, a different handler on a separate `elif`. It never enters
the `fuzzy_file_match` branch at all, so no gate needs to protect it.
"""

import unittest
from unittest.mock import patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from cosa.tests.unit.agents.runtime_argument_expeditor.test_expeditor_flow import (
    PG,
    PR,
    TFE,
    _expeditor_resp,
    _FlowFixture,
    _mk_expeditor,
)


PRESENTATION_QUESTION = JOB_ARG_CONTRACTS[ PR ][ "fallback_questions" ][ "source" ]
PODCAST_QUESTION      = JOB_ARG_CONTRACTS[ PG ][ "fallback_questions" ][ "research" ]


class TestPresentationGetsTheGeneralisedBehaviour( unittest.TestCase ):
    """The four behaviours the fences withheld. Each was RED before the fix."""

    def test_presentation_auto_resolve_receives_the_utterance( self ):
        # FENCE 1. `fuzzy_original = original_question if is_podcast else None` meant
        # presentation always got None, so the auto pre-step could never fire.
        # RED BEFORE THE FIX: AssertionError: None != 'make a deck about KISS'
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/deck.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            o.expedite( PR, "", "u@x", "s", "uid", "make a deck about KISS" )
        self.assertEqual( fuzzy.call_args.kwargs[ "original_question" ], "make a deck about KISS" )

    def test_presentation_gets_the_first_turn_choice_card( self ):
        # FENCE 2. `use_choice_card=is_podcast` meant presentation never got the
        # two-to-cap pick list and fell through to the open "describe it" ask.
        # RED BEFORE THE FIX: AssertionError: False is not true
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/deck.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            o.expedite( PR, "", "u@x", "s", "uid", "make a deck about KISS" )
        self.assertTrue( fuzzy.call_args.kwargs[ "use_choice_card" ] )

    def test_presentation_present_but_unresolvable_source_is_rescued( self ):
        # FENCE 3, and the one with a job-killing consequence. `source="KISS"` is
        # present-not-missing, so the missing-args loop skips it; the rescue loop was
        # podcast-only, so nothing resolved it and the job raised FileNotFoundError.
        # RED BEFORE THE FIX: AssertionError: 'KISS' != '/io/x/kiss-deck.md'
        o = _mk_expeditor( debug=True )
        with _FlowFixture( o, user_visible=[ "source" ],
                           parsed=_expeditor_resp( present="source=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/kiss-deck.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            out = o.expedite( PR, "", "u@x", "s", "uid", "make a deck on KISS" )
        self.assertEqual( out[ "source" ], "/io/x/kiss-deck.md" )
        self.assertEqual( fuzzy.call_args.kwargs[ "original_question" ], "make a deck on KISS" )

    def test_the_rescue_ask_uses_presentations_own_wording_and_field_name( self ):
        # FENCE 3's WORDING HALF. The rescue call site passed neither `arg_name` nor
        # `ask_question`, so it fell back to the defaults — the arg name "research"
        # and the podcast's question. That is the leak Tiffany caught live on job
        # pr-a10a55aa: a presentation job asking "Which document should I use for the
        # podcast?" under a card titled "Missing: research".
        #
        # The MISSING-arg call site was already fixed separately (commit 7c2d0b0b,
        # row ea184d06) and is green on both sides — this asserts the RESCUE site,
        # which that fix did not reach.
        # RED BEFORE THE FIX: KeyError 'arg_name' — the rescue never ran for
        # presentation at all, so there were no kwargs to inspect.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ],
                           parsed=_expeditor_resp( present="source=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/kiss-deck.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            o.expedite( PR, "", "u@x", "s", "uid", "make a deck on KISS" )
        self.assertEqual( fuzzy.call_args.kwargs[ "arg_name" ], "source" )
        self.assertEqual( fuzzy.call_args.kwargs[ "ask_question" ], PRESENTATION_QUESTION )
        self.assertNotIn( "podcast", fuzzy.call_args.kwargs[ "ask_question" ].lower() )


class TestTheRescueStillBehavesOnThePresentationPath( unittest.TestCase ):
    """The rescue's own guards must hold for `source` exactly as they do for `research`."""

    def test_presentation_source_that_is_already_a_real_path_is_left_alone( self ):
        # IDEMPOTENCE. A `source` that already points at a file must not be
        # re-resolved — otherwise the rescue would overwrite a good answer.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ],
                           parsed=_expeditor_resp( present="source=io/deep-research/u/report.md" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/other.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            out = o.expedite( PR, "", "u@x", "s", "uid", "make a deck from io/deep-research/u/report.md" )
        self.assertEqual( out[ "source" ], "io/deep-research/u/report.md" )
        fuzzy.assert_not_called()

    def test_presentation_missing_source_is_not_resolved_twice( self ):
        # The missing-args loop owns the missing case; the rescue owns only the
        # present case. Dropping the `arg_name in missing` guard would ask the user
        # the same question twice.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ], parsed=_expeditor_resp() ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/resolved.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            out = o.expedite( PR, "", "u@x", "s", "uid", "make a deck on KISS" )
        fuzzy.assert_called_once()
        self.assertEqual( out[ "source" ], "/io/x/resolved.md" )

    def test_presentation_rescue_resolving_to_yaml_sets_render_only( self ):
        # A .yaml answer through the rescue sets render_only, matching what the
        # missing-arg branch already does.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ],
                           parsed=_expeditor_resp( present="source=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/deck.yaml" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            out = o.expedite( PR, "", "u@x", "s", "uid", "make a deck on KISS" )
        self.assertEqual( out[ "source" ], "/io/x/deck.yaml" )
        self.assertEqual( out[ "render_only" ], "true" )

    def test_presentation_rescue_cancelled_returns_none_not_the_bare_topic( self ):
        # No-crash contract: a cancelled prompt ends the flow cleanly rather than
        # letting "KISS" travel downstream where a file path is expected.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ],
                           parsed=_expeditor_resp( present="source=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value=None ):
            self.assertIsNone( o.expedite( PR, "", "u@x", "s", "uid", "make a deck on KISS" ) )


class TestNothingElseMoved( unittest.TestCase ):
    """
    GREEN ON BOTH SIDES BY DESIGN — do NOT demand a red-before from these.

    The fix edits the SHARED `_handle_fuzzy_file_match` call sites, so the podcast
    path needs pinning even though nothing about it is meant to change; and TFE needs
    pinning to show the edit did not leak into a handler it was never supposed to
    touch.
    """

    def test_podcast_still_auto_resolves_and_still_gets_the_choice_card( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/report.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            o.expedite( PG, "", "u@x", "s", "uid", "make a podcast about KISS" )
        self.assertEqual( fuzzy.call_args.kwargs[ "original_question" ], "make a podcast about KISS" )
        self.assertTrue( fuzzy.call_args.kwargs[ "use_choice_card" ] )

    def test_podcast_rescue_still_fires_and_keeps_its_own_wording( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ],
                           parsed=_expeditor_resp( present="research=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/kiss-protocol.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            out = o.expedite( PG, "", "u@x", "s", "uid", "make me a podcast on KISS" )
        self.assertEqual( out[ "research" ], "/io/x/kiss-protocol.md" )
        # EFFECTIVE wording, not the mechanism. Before the fix the rescue passed
        # neither kwarg and leaned on the handler's podcast-shaped DEFAULTS; after it,
        # both are passed explicitly. Asserting the kwarg itself would make this guard
        # RED on the pre-fix tree — which would be wrong, because the user-visible
        # wording never changed. `.get` with the default reads what the user hears.
        kwargs = fuzzy.call_args.kwargs
        self.assertEqual( kwargs.get( "arg_name", "research" ), "research" )
        self.assertEqual( kwargs.get( "ask_question" ) or PODCAST_QUESTION, PODCAST_QUESTION )

    def test_tfe_resume_never_enters_the_fuzzy_branch( self ):
        # EXEMPT BY CONSTRUCTION, not by a fence: `resume_from` routes through
        # `tfe_checkpoint_match` on its own elif, so removing the podcast gate on the
        # fuzzy branch cannot reach it. Its handler takes no `original_question`.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "resume_from" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_tfe_checkpoint_match", return_value="tfe-abcd1234" ) as tfe, \
             patch.object( o, "_handle_fuzzy_file_match" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            out = o.expedite( TFE, "", "u@x", "s", "uid", "resume the auth job" )
        self.assertEqual( out[ "resume_from" ], "tfe-abcd1234" )
        fuzzy.assert_not_called()
        self.assertNotIn( "original_question", tfe.call_args.kwargs )

    def test_tfe_present_but_unresolvable_value_is_not_rescued( self ):
        # The rescue loop skips any arg whose handler is not fuzzy_file_match. With
        # the command gate gone, THAT is the only thing keeping TFE out of it — so it
        # is asserted rather than assumed.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "resume_from" ],
                           parsed=_expeditor_resp( present="resume_from=the auth job" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r, **k: a ):
            out = o.expedite( TFE, "", "u@x", "s", "uid", "resume the auth job" )
        self.assertEqual( out[ "resume_from" ], "the auth job" )
        fuzzy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
