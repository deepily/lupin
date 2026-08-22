"""
Unit tests for FIRST-TURN document disambiguation via the standard choice card
(plan 2026.08.04-first-turn-document-disambiguation).

Units under test in expeditor.py:
  1. _ask_choice_for_arg          — the ONE new ask surface: a MULTIPLE_CHOICE
     request built like the routing confirm; JSON answer parsing; cancel / describe
     / failure returns.
  2. _describe_candidate          — folder + yyyy.mm.dd hint (cosmetic).
  3. _choose_document_from_matches — options assembly (candidates + Describe + Cancel),
     label→abs mapping, no-silent-guess.
  4. _handle_fuzzy_file_match wiring — card shown for 2..cap on the FIRST turn (opt-in
     via use_choice_card); >cap falls to the open ask; TERMINATION (card→describe→open
     ask→second ambiguity → exact-path ask, never a second card); presentation opt-out.

All boundaries mocked — no LLM, no network, no filesystem.

Created 2026-08-04 by Rachel 🕊️ (row: first-turn document disambiguation).
"""

import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    MAX_CHOICE_OPTIONS,
    DOC_CHOICE_DESCRIBE_LABEL,
    DOC_CHOICE_CANCEL_LABEL,
    DOC_CHOICE_DESCRIBE_SENTINEL,
    BATCH_DECLINED,
    BATCH_MALFORMED,
    DOCUMENT_CHOICE_CARD_ID,
    DOCUMENT_DESCRIBE_ASK_ID,
)


def _mk_expeditor( debug=False ):
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    with patch.object( ex_mod, "LlmClientFactory", MagicMock() ):
        o = RuntimeArgumentExpeditor( cfg, debug=debug )
    o.SENDER_ID      = "arg.expeditor@lupin.deepily.ai"
    o._bearer_token  = None
    o._job_id        = "pg-a1b2c3d4"
    return o


class _Resp:
    """Minimal stand-in for the notify_user_sync response object."""
    def __init__( self, success=True, response_value=None, status="responded", is_timeout=False, is_error=False, exit_code=0 ):
        self.success        = success
        self.response_value = response_value
        self.status         = status
        self.is_timeout     = is_timeout
        self.is_error       = is_error
        self.exit_code      = exit_code


# ── 1. _ask_choice_for_arg ──────────────────────────────────────────────────
class TestAskChoiceForArg( unittest.TestCase ):

    OPTIONS = [
        { "label": "a.md", "description": "folder · 2026-01-01" },
        { "label": "b.md", "description": "folder · 2026-02-02" },
        { "label": DOC_CHOICE_DESCRIBE_LABEL, "description": "None of these" },
        { "label": DOC_CHOICE_CANCEL_LABEL,   "description": "Cancel" },
    ]

    def _ask( self, resp ):
        o   = _mk_expeditor()
        ctx = ex_mod.ExpediteContext()
        captured = {}
        def _fake_notify( request=None, debug=False, bearer_token=None ):
            captured[ "request" ] = request
            return resp
        with patch.object( ex_mod, "notify_user_sync", side_effect=_fake_notify ):
            out = o._ask_choice_for_arg( "research", "Which document?", self.OPTIONS, "u@e.com", context=ctx )
        return out, captured.get( "request" ), ctx

    def _ask_with_card_id( self, card_id ):
        o = _mk_expeditor()
        captured = {}
        def _fake_notify( request=None, debug=False, bearer_token=None ):
            captured[ "request" ] = request
            return _Resp( response_value="a.md" )
        with patch.object( ex_mod, "notify_user_sync", side_effect=_fake_notify ):
            o._ask_choice_for_arg( "research", "Which document?", self.OPTIONS, "u@e.com",
                                   card_id=card_id )
        return captured[ "request" ]

    def test_a_named_card_stamps_its_id_beside_the_questions( self ):
        # Row a1420538. The id names the CARD, so it rides beside `questions` rather
        # than inside one — a question-level key would read as a property of that
        # question and would have to be repeated if the card ever grew a second.
        request = self._ask_with_card_id( DOCUMENT_CHOICE_CARD_ID )
        self.assertEqual( request.response_options[ "card_id" ], DOCUMENT_CHOICE_CARD_ID )
        self.assertIn( "questions", request.response_options )

    def test_an_unnamed_card_carries_no_id_at_all( self ):
        # The routing-confirm card and every other user of this ask must send exactly
        # what they sent before. An id of None would still be a new key on the wire,
        # which is a different envelope even if nothing reads it.
        # RED ON REVERT (stamping unconditionally): "card_id" unexpectedly found.
        _out, request, _o = self._ask( _Resp( response_value="a.md" ) )
        self.assertNotIn( "card_id", request.response_options )

    def test_a_named_card_stamps_the_argument_beside_the_id( self ):
        # MARÍA'S POINT, and it was a real gap: the matcher narrows an id match by
        # arg_name, and for one commit NOTHING sent arg_name — the filter was reachable
        # only from tests. Both ask surfaces stamp it now, and each has a falsifier.
        # RED ON REVERT (the arg_name line dropped from _ask_choice_for_arg):
        # KeyError: 'arg_name'.
        request = self._ask_with_card_id( DOCUMENT_CHOICE_CARD_ID )
        self.assertEqual( request.response_options[ "arg_name" ], "research" )

    def test_builds_multiple_choice_request_shape( self ):
        _out, request, _o = self._ask( _Resp( response_value="a.md" ) )
        self.assertEqual( request.response_type, ex_mod.ResponseType.MULTIPLE_CHOICE )
        q = request.response_options[ "questions" ][ 0 ]
        self.assertEqual( q[ "header" ], "research" )
        self.assertFalse( q[ "multi_select" ] )
        self.assertEqual( q[ "options" ], self.OPTIONS )

    def test_returns_raw_label( self ):
        out, _r, _o = self._ask( _Resp( response_value="a.md" ) )
        self.assertEqual( out, "a.md" )

    def test_parses_json_answer_by_header( self ):
        out, _r, _o = self._ask( _Resp( response_value='{"answers": {"research": "b.md"}}' ) )
        self.assertEqual( out, "b.md" )

    def test_parses_json_answer_by_index_key( self ):
        out, _r, _o = self._ask( _Resp( response_value='{"answers": {"0": "b.md"}}' ) )
        self.assertEqual( out, "b.md" )

    def test_malformed_json_falls_through_to_raw( self ):
        # starts with '{' but is not valid JSON → treated as the raw value
        out, _r, _o = self._ask( _Resp( response_value="{not json" ) )
        self.assertEqual( out, "{not json" )

    def test_cancel_returns_none_and_declined( self ):
        out, _r, o = self._ask( _Resp( response_value=DOC_CHOICE_CANCEL_LABEL ) )
        self.assertIsNone( out )
        self.assertEqual( o.reason, BATCH_DECLINED )

    def test_describe_returns_sentinel( self ):
        out, _r, _o = self._ask( _Resp( response_value=DOC_CHOICE_DESCRIBE_LABEL ) )
        self.assertEqual( out, DOC_CHOICE_DESCRIBE_SENTINEL )

    def test_failure_returns_none_not_declined( self ):
        out, _r, o = self._ask( _Resp( success=False, response_value=None, status="error", is_error=True ) )
        self.assertIsNone( out )
        self.assertNotEqual( o.reason, BATCH_DECLINED )


# ── 2. _describe_candidate ──────────────────────────────────────────────────
class TestDescribeCandidate( unittest.TestCase ):

    def test_folder_and_date( self ):
        o = _mk_expeditor()
        self.assertEqual(
            o._describe_candidate( "io/deep-research/u/2026.08.04-kiss.md" ),
            "io/deep-research/u · 2026-08-04",
        )

    def test_folder_only_when_no_date( self ):
        o = _mk_expeditor()
        self.assertEqual( o._describe_candidate( "src/rnd/notes.md" ), "src/rnd" )

    def test_bare_basename_folder_is_dot( self ):
        o = _mk_expeditor()
        self.assertEqual( o._describe_candidate( "notes.md" ), "." )


# ── 3. _choose_document_from_matches ────────────────────────────────────────
class TestChooseDocumentFromMatches( unittest.TestCase ):

    DOCS = {
        "io/deep-research/u/2026.07.25-kiss.md" : "/abs/kiss-a.md",
        "io/deep-research/u/2026.08.04-kiss.md" : "/abs/kiss-b.md",
    }

    def _choose( self, choice_return ):
        o   = _mk_expeditor()
        ctx = ex_mod.ExpediteContext()
        captured = {}
        def _fake_choice( arg_name, question, options, user_email, abstract=None, card_id=None, context=None ):
            captured[ "options" ] = options
            captured[ "card_id" ] = card_id
            captured[ "context" ] = context
            return choice_return
        o._ask_choice_for_arg = _fake_choice
        out = o._choose_document_from_matches( list( self.DOCS.keys() ), self.DOCS, "u@e.com", context=ctx )
        # the caller's context is what the ask receives — not a fresh one
        assert captured[ "context" ] is ctx
        return out, captured.get( "options" ), ctx, captured.get( "card_id" )

    def test_the_caller_names_the_card_it_is_showing( self ):
        # Row a1420538. The stub's signature broke when card_id was added; widening it
        # silently would have left nothing checking that the doc-choice caller actually
        # passes the id — and without the id the proxy's generic entry never claims the
        # card, which is a run that hangs at a prompt nothing can answer.
        # RED ON REVERT (card_id dropped at the call site): None != 'document_choice'.
        _out, _options, _o, card_id = self._choose( "2026.07.25-kiss.md" )
        self.assertEqual( card_id, DOCUMENT_CHOICE_CARD_ID )

    def test_options_carry_candidates_plus_two_escapes_last( self ):
        _out, options, _o, _card_id = self._choose( "2026.07.25-kiss.md" )
        labels = [ opt[ "label" ] for opt in options ]
        # two candidates then Describe then Cancel, in that order
        self.assertEqual( labels[ -2: ], [ DOC_CHOICE_DESCRIBE_LABEL, DOC_CHOICE_CANCEL_LABEL ] )
        self.assertIn( "2026.07.25-kiss.md", labels )
        self.assertIn( "2026.08.04-kiss.md", labels )

    def test_pick_maps_label_to_abs_path( self ):
        out, _opts, _o, _card_id = self._choose( "2026.08.04-kiss.md" )
        self.assertEqual( out, "/abs/kiss-b.md" )

    def test_cancel_returns_none( self ):
        out, _opts, _o, _card_id = self._choose( None )
        self.assertIsNone( out )

    def test_describe_returns_sentinel( self ):
        out, _opts, _o, _card_id = self._choose( DOC_CHOICE_DESCRIBE_SENTINEL )
        self.assertEqual( out, DOC_CHOICE_DESCRIBE_SENTINEL )

    def test_label_outside_option_set_never_guesses( self ):
        out, _opts, o, _card_id = self._choose( "not-a-candidate.md" )
        self.assertIsNone( out )
        self.assertEqual( o.reason, BATCH_MALFORMED )

    def test_basename_collision_falls_back_to_rel_label( self ):
        o = _mk_expeditor()
        docs = {
            "io/deep-research/u/a/report.md" : "/abs/a/report.md",
            "io/deep-research/u/b/report.md" : "/abs/b/report.md",
        }
        captured = {}
        def _fake_choice( arg_name, question, options, user_email, abstract=None, card_id=None, context=None ):
            captured[ "options" ] = options
            return "io/deep-research/u/b/report.md"
        o._ask_choice_for_arg = _fake_choice
        out = o._choose_document_from_matches( list( docs.keys() ), docs, "u@e.com" )
        labels = [ opt[ "label" ] for opt in captured[ "options" ] ]
        # first "report.md" keeps the basename; the collider uses its full rel path
        self.assertIn( "report.md", labels )
        self.assertIn( "io/deep-research/u/b/report.md", labels )
        self.assertEqual( out, "/abs/b/report.md" )


# ── 4. _handle_fuzzy_file_match wiring ──────────────────────────────────────
class TestTheDescribeAskNamesItself( unittest.TestCase ):
    """
    Row 0c280989. The open-ended "which document? describe it" ask had six proxy
    entries keyed on its prose, in three different wordings. It carries an id now, the
    same way the card does.
    """

    def _ask( self, **kwargs ):
        o = _mk_expeditor()
        captured = {}
        def _fake_notify( request=None, debug=False, bearer_token=None ):
            captured[ "request" ] = request
            return _Resp( response_value="my document" )
        with patch.object( ex_mod, "notify_user_sync", side_effect=_fake_notify ):
            o._ask_for_arg( "source", "Which document?", "u@e.com", **kwargs )
        return captured[ "request" ]

    def test_a_named_ask_carries_its_id_and_its_argument( self ):
        # RED ON REVERT (the arg_name line dropped from _ask_for_arg): KeyError.
        request = self._ask( card_id=DOCUMENT_DESCRIBE_ASK_ID )
        self.assertEqual( request.response_options[ "card_id" ],  DOCUMENT_DESCRIBE_ASK_ID )
        self.assertEqual( request.response_options[ "arg_name" ], "source" )

    def test_an_unnamed_ask_sends_no_response_options_at_all( self ):
        # _ask_for_arg has a dozen other callers and an OPEN_ENDED ask carries no
        # options. They must send the envelope they always sent — an empty dict would
        # still be a new key on the wire.
        # RED ON REVERT (stamping unconditionally): {} is not None.
        self.assertIsNone( self._ask().response_options )

    def test_the_describe_ask_in_the_fuzzy_handler_names_itself( self ):
        # The wiring, not just the helper: this is the ask the six migrated proxy
        # entries answer, so if the call site stops naming the id they all stop
        # matching and an automated run hangs at a prompt nothing can answer.
        # RED ON REVERT (card_id dropped at the call site): None != 'document_describe'.
        o = _mk_expeditor()
        seen = {}
        def _fake_ask( arg, question, email, **kwargs ):
            seen.setdefault( "card_ids", [] ).append( kwargs.get( "card_id" ) )
            return None
        o._ask_for_arg = _fake_ask
        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as CM, \
             patch.object( ex_mod.cu, "get_project_root", return_value="/root" ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "a.md", "b.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_match_description_to_files", return_value=( "fuzzy", [] ) ):
            CM.return_value.get.side_effect = lambda key, default=None, **kw: default
            o._handle_fuzzy_file_match( "u@e.com", "presentation generator",
                                        original_question="anything", use_choice_card=False,
                                        arg_name="source" )
        self.assertIn( DOCUMENT_DESCRIBE_ASK_ID, seen[ "card_ids" ] )


class TestSearchRootsComeFromTheDeclaration( unittest.TestCase ):
    """
    Row a1420538. WHERE a file argument's candidates live used to be written into
    _handle_fuzzy_file_match — two per-user directories and four extensions, the same
    for everyone — and the extra config key was BUILT from the display name, falling
    back to the podcast's key when the agent had none of its own. So an agent with no
    key silently searched wherever the podcast happened to be configured to look. The
    roots and the key are declared beside the argument now.
    """

    EMAIL = "u@example.com"

    def _docs_map( self, file_arg, listing, exists=True ):
        """Run the scan and report what it found, without going near the LLM."""
        o = _mk_expeditor()
        seen_keys = []
        captured  = {}
        def _fake_ask( arg, question, email, **k ):
            captured[ "asked" ] = question
            return None
        o._ask_for_arg = _fake_ask

        listdir = listing if callable( listing ) else ( lambda path: list( listing ) )
        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as CM, \
             patch.object( ex_mod.cu, "get_project_root", return_value="/root" ), \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: exists( p ) if callable( exists ) else exists ), \
             patch.object( ex_mod.os, "listdir", side_effect=listdir ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_match_description_to_files", return_value=( "fuzzy", [] ) ) as matcher:
            def _record( key, default=None, **kw ):
                seen_keys.append( key )
                return default
            CM.return_value.get.side_effect = _record
            o._handle_fuzzy_file_match(
                self.EMAIL, "presentation generator",
                original_question="anything", use_choice_card=False,
                arg_name="source", file_arg=file_arg,
            )
        docs_map = matcher.call_args[ 0 ][ 1 ] if matcher.call_args else {}
        return docs_map, seen_keys

    def test_a_declared_root_is_the_one_searched( self ):
        declaration = { "kind": "file",
                        "search_roots": ( { "path": "io/somewhere-else/{user_email}" }, ) }
        docs_map, _keys = self._docs_map( declaration, [ "a.md" ] )
        self.assertIn( f"io/somewhere-else/{self.EMAIL}/a.md", docs_map )
        self.assertEqual( docs_map[ f"io/somewhere-else/{self.EMAIL}/a.md" ],
                          f"/root/io/somewhere-else/{self.EMAIL}/a.md" )

    def test_declaring_nothing_searches_what_it_always_searched( self ):
        # A not-yet-migrated caller must be unchanged. Both shared roots, same rules.
        docs_map, _keys = self._docs_map( None, [ "a.md", "b.yaml" ] )
        self.assertIn( f"io/deep-research/{self.EMAIL}/a.md", docs_map )
        self.assertIn( f"io/presentations/{self.EMAIL}/b.yaml", docs_map )
        # The presentations root takes YAML only: a .md in there is a rendered output,
        # not a source, and pulling it in would offer the user their own output back.
        self.assertNotIn( f"io/presentations/{self.EMAIL}/a.md", docs_map )

    def test_a_root_that_does_not_exist_is_skipped_not_fatal( self ):
        # A user with no presentations directory is the ordinary case, not an error.
        missing = f"/root/io/presentations/{self.EMAIL}"
        docs_map, _keys = self._docs_map(
            None, [ "a.md" ], exists=lambda path: path != missing )
        self.assertIn( f"io/deep-research/{self.EMAIL}/a.md", docs_map )
        self.assertNotIn( f"io/presentations/{self.EMAIL}/a.md", docs_map )

    def test_the_extra_paths_key_is_the_declared_one( self ):
        declaration = { "kind": "file",
                        "search_roots": ( { "path": "io/deep-research/{user_email}" }, ),
                        "search_paths_key": "presentation generator source search paths" }
        _docs_map, keys = self._docs_map( declaration, [ "a.md" ] )
        self.assertIn( "presentation generator source search paths", keys )
        self.assertNotIn( "podcast generator source search paths", keys )

    def test_an_undeclared_key_still_falls_back_to_the_podcast_one( self ):
        # Characterisation, not endorsement: this is what an argument declaring no key
        # gets today, and it is the behaviour the declared key exists to replace. Pinned
        # so that changing it is a decision somebody makes, not a silent drift.
        _docs_map, keys = self._docs_map( None, [ "a.md" ] )
        self.assertIn( "podcast generator source search paths", keys )


class TestHandleFuzzyChoiceCardWiring( unittest.TestCase ):

    EMAIL = "u@example.com"

    def _run( self, original_question, match_results, use_choice_card,
              choose_return=None, files=( "kiss.md", ) ):
        """
        Drive _handle_fuzzy_file_match with a controlled matcher + spied helpers.

        match_results: a list, one (status, matches) per _match_description_to_files call.
        Returns dict of observed calls + the return value.
        """
        o = _mk_expeditor()
        ask_calls    = []
        choose_calls = []
        o._ask_for_arg = lambda arg, q, email, **k: ask_calls.append( q ) or "typed description"
        # The stub records the KWARGS too: the card now speaks as the calling agent
        # (row 9046ef58), so "who did the caller say it was" is part of the wiring
        # this class exists to pin, not an incidental argument.
        def _fake_choose( matches, docs, email, **kwargs ):
            choose_calls.append( { "matches": list( matches ), **kwargs } )
            return choose_return
        o._choose_document_from_matches = _fake_choose

        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as CM, \
             patch.object( ex_mod.cu, "get_project_root", return_value="/root" ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( ex_mod.os, "listdir", return_value=list( files ) ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_match_description_to_files", side_effect=list( match_results ) ):
            CM.return_value.get.side_effect = lambda key, default=None, **kw: default
            result = o._handle_fuzzy_file_match(
                self.EMAIL, agent_display_name="podcast generator",
                original_question=original_question, use_choice_card=use_choice_card,
            )
        return { "result": result, "ask_qs": ask_calls, "choose_calls": choose_calls }

    def _rel( self, name ):
        return f"io/deep-research/{self.EMAIL}/{name}"

    def test_two_first_turn_matches_show_card_not_question( self ):
        two = ( "fuzzy", [ self._rel( "a.md" ), self._rel( "b.md" ) ] )
        obs = self._run(
            "make a podcast about the KISS protocol", [ two ],
            use_choice_card=True, choose_return="/abs/a.md",
        )
        self.assertEqual( len( obs[ "choose_calls" ] ), 1, "card must be shown on the first turn" )
        # The caller hands its own identity down, so the card can ask in its terms.
        self.assertEqual( obs[ "choose_calls" ][ 0 ][ "arg_name" ], "research" )
        self.assertEqual( obs[ "choose_calls" ][ 0 ][ "agent_display_name" ], "podcast generator" )
        self.assertEqual( obs[ "ask_qs" ], [], "no open question when the card resolves" )
        self.assertEqual( obs[ "result" ], "/abs/a.md" )

    def test_over_cap_matches_skip_card_and_ask( self ):
        many = ( "fuzzy", [ self._rel( f"d{i}.md" ) for i in range( MAX_CHOICE_OPTIONS + 1 ) ] )
        obs = self._run(
            "make a podcast about docs", [ many, many ],
            use_choice_card=True, choose_return="/abs/x.md",
            files=tuple( f"d{i}.md" for i in range( MAX_CHOICE_OPTIONS + 1 ) ),
        )
        self.assertEqual( obs[ "choose_calls" ], [], "more than the cap must NOT show a card" )
        self.assertGreaterEqual( len( obs[ "ask_qs" ] ), 1, "over-cap falls through to an open ask" )

    def test_cancel_on_card_returns_none( self ):
        two = ( "fuzzy", [ self._rel( "a.md" ), self._rel( "b.md" ) ] )
        obs = self._run( "podcast about KISS", [ two ], use_choice_card=True, choose_return=None )
        self.assertIsNone( obs[ "result" ] )
        self.assertEqual( obs[ "ask_qs" ], [], "cancel is terminal — no open ask after it" )

    def test_termination_describe_then_second_ambiguity_goes_to_exact_ask_not_card( self ):
        # First turn: 2 matches → card → user picks "describe instead" (sentinel).
        # Falls through to the open ask; the typed answer is ALSO ambiguous (2 matches).
        # That second ambiguity must go to the exact-path ask, NOT a second card.
        two_a = ( "fuzzy", [ self._rel( "a.md" ), self._rel( "b.md" ) ] )
        two_b = ( "fuzzy", [ self._rel( "a.md" ), self._rel( "b.md" ) ] )
        obs = self._run(
            "make a podcast about the KISS protocol", [ two_a, two_b ],
            use_choice_card=True, choose_return=DOC_CHOICE_DESCRIBE_SENTINEL,
        )
        self.assertEqual( len( obs[ "choose_calls" ] ), 1, "the card must appear at most once" )
        # open "which document?" ask (after describe) + exact-path ask = 2 asks, no re-card
        self.assertGreaterEqual( len( obs[ "ask_qs" ] ), 2 )

    def test_second_turn_card_when_no_first_turn_card( self ):
        # Bare line (no original_question) → no first-turn card → open ask → the
        # typed answer yields 2 matches → the card fires at the SECOND site, once.
        two = ( "fuzzy", [ self._rel( "a.md" ), self._rel( "b.md" ) ] )
        obs = self._run(
            None, [ two ], use_choice_card=True, choose_return="/abs/a.md",
            files=( "a.md", "b.md" ),
        )
        self.assertEqual( len( obs[ "choose_calls" ] ), 1, "typed 2-match must card once" )
        self.assertEqual( len( obs[ "ask_qs" ] ), 1, "only the open 'which document?' ask, then the card" )
        self.assertEqual( obs[ "result" ], "/abs/a.md" )

    def test_second_turn_card_describe_falls_to_exact_ask( self ):
        # Bare line → open ask → 2 matches → SECOND-site card → "describe instead"
        # again → the exact-path ask, not another card.
        two = ( "fuzzy", [ self._rel( "a.md" ), self._rel( "b.md" ) ] )
        obs = self._run(
            None, [ two ], use_choice_card=True, choose_return=DOC_CHOICE_DESCRIBE_SENTINEL,
            files=( "a.md", "b.md" ),
        )
        self.assertEqual( len( obs[ "choose_calls" ] ), 1, "card fires once at the second site" )
        self.assertGreaterEqual( len( obs[ "ask_qs" ] ), 2, "open ask + exact-path ask after describe" )

    def test_presentation_opt_out_uses_no_card( self ):
        # use_choice_card=False (presentation `source`): a 2-match typed result must
        # NOT show a card — the numbered prompt path runs, unchanged.
        two = ( "fuzzy", [ self._rel( "a.md" ), self._rel( "b.md" ) ] )
        obs = self._run(
            None, [ two ], use_choice_card=False, choose_return="/abs/a.md",
            files=( "a.md", "b.md" ),
        )
        self.assertEqual( obs[ "choose_calls" ], [], "presentation opt-out must never card" )
        self.assertGreaterEqual( len( obs[ "ask_qs" ] ), 1 )


if __name__ == "__main__":
    unittest.main()
