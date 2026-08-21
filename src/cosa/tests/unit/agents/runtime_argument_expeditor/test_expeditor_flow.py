"""
Unit tests for runtime_argument_expeditor/expeditor.py — the expedite() top-level
orchestration flow (LORA parse → LLM gap analysis → arg collection → confirm → inject).

All seams mocked: get_cli_help, get_user_visible_args, ExpeditorResponse.from_xml,
LlmClientFactory, PromptTemplateProcessor, cu helpers, and the collection/confirm
sub-methods (_batch_collect_args, _ask_for_arg, _handle_fuzzy_file_match,
_handle_tfe_checkpoint_match, _confirm_and_iterate). NO LLM/network/fs.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, runtime_argument_expeditor lane).
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


def _expeditor_resp( complete="false", present="", missing="" ):
    r = MagicMock()
    r.is_complete.return_value = ( complete == "true" )
    r.get_present_dict.return_value = dict(
        ( p.split( "=", 1 )[ 0 ].strip(), p.split( "=", 1 )[ 1 ].strip() )
        for p in present.split( "," ) if "=" in p
    )
    return r


class _FlowFixture:
    """Patches the shared expedite() seams; per-test override via attributes."""

    def __init__( self, o, *, help_text="help", user_visible=None, parsed=None,
                  parse_raises=False ):
        self.o = o
        self._patches = [
            patch.object( ex_mod, "get_cli_help", return_value=help_text ),
            patch.object( ex_mod, "get_user_visible_args", return_value=user_visible ),
            patch.object( ex_mod.cu, "get_file_as_string", return_value="tmpl {system_args}{help_text}{voice_command}{extracted_args}{required_args}" ),
            patch.object( ex_mod.cu, "get_project_root", return_value="/p" ),
            patch.object( ex_mod, "PromptTemplateProcessor" ),
        ]
        self._parsed = parsed
        self._parse_raises = parse_raises

    def __enter__( self ):
        for p in self._patches: p.start()
        ex_mod.PromptTemplateProcessor.return_value.process_template.side_effect = lambda t, n: t
        self.o.llm_factory.get_client = MagicMock( return_value=MagicMock( run=MagicMock( return_value="<xml/>" ) ) )
        if self._parse_raises:
            self._fx = patch.object( ex_mod.ExpeditorResponse, "from_xml", side_effect=RuntimeError( "bad xml" ) )
        else:
            self._fx = patch.object( ex_mod.ExpeditorResponse, "from_xml", return_value=self._parsed or _expeditor_resp() )
        self._fx.start()
        return self.o

    def __exit__( self, *exc ):
        self._fx.stop()
        for p in self._patches: p.stop()
        return False


DR = "agent router go to deep research"          # required ["query"], no special handlers
PG = "agent router go to podcast generator"      # special: research → fuzzy_file_match
TFE = "agent router go to test fix expediter resume"   # special: resume_from → tfe_checkpoint_match
PR = "agent router go to presentation generator"       # special: source → fuzzy_file_match


class TestExpediteFlow( unittest.TestCase ):

    def test_unknown_command_returns_none( self ):
        o = _mk_expeditor( debug=True )
        self.assertIsNone( o.expedite( "no such command", "", "u@x", "s", "uid", "do it" ) )

    def test_all_present_no_missing_confirms_and_injects( self ):
        o = _mk_expeditor( debug=True )
        parsed = _expeditor_resp( complete="true", present="query=AI" )
        with _FlowFixture( o, help_text="help", user_visible=[ "query" ], parsed=parsed ), \
             patch.object( o, "_confirm_and_iterate", return_value={ "query": "AI" } ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertEqual( out[ "query" ], "AI" )
        self.assertEqual( out[ "user_email" ], "u@x" )   # system args injected

    def test_help_none_uses_placeholder( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, help_text=None, user_visible=[ "query" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_confirm_and_iterate", return_value={ "query": "AI" } ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertIsNotNone( out )

    def test_llm_parse_exception_falls_back_to_all_missing( self ):
        o = _mk_expeditor( debug=True )
        with _FlowFixture( o, user_visible=[ "query" ], parse_raises=True ), \
             patch.object( o, "_ask_for_arg", return_value="AI topic" ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_confirm_and_iterate", return_value={ "query": "AI topic" } ):
            out = o.expedite( DR, "", "u@x", "s", "uid", "research AI" )
        self.assertIsNotNone( out )

    def test_user_visible_none_uses_fallback_question_keys( self ):
        o = _mk_expeditor()
        # user_visible None → falls back to fallback_questions keys (query/budget/audience/audience_context)
        with _FlowFixture( o, user_visible=None, parsed=_expeditor_resp( present="query=AI, budget=10, audience=expert, audience_context=none" ) ), \
             patch.object( o, "_confirm_and_iterate", return_value={ "query": "AI" } ):
            out = o.expedite( DR, "", "u@x", "s", "uid", "research AI" )
        self.assertIsNotNone( out )

    def test_batch_collect_multiple_missing_skips_no_limit( self ):
        o = _mk_expeditor( debug=True )
        # only query present → budget/audience/audience_context missing → batchable > 1
        with _FlowFixture( o, user_visible=[ "query", "budget", "audience", "audience_context" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_batch_collect_args",
                           return_value=( { "budget": "no limit", "audience": "expert", "audience_context": "none" },
                                          ex_mod.BATCH_ANSWERED ) ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertEqual( out[ "audience" ], "expert" )
        self.assertNotIn( "budget", out )    # "no limit" skipped

    def test_batch_collect_cancel_returns_none( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "query", "budget", "audience" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_batch_collect_args", return_value=( None, ex_mod.BATCH_DECLINED ) ):
            self.assertIsNone( o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" ) )
        # a real "no" is recorded as the user's decision
        self.assertEqual( o._last_expedite_reason, ex_mod.BATCH_DECLINED )

    def test_batch_collect_undeliverable_records_machine_reason( self ):
        # The non-declined batch branch: the reason must survive to the caller, NOT
        # be reported as a user cancellation (bugs 2aaab1bf, 68198c9f).
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "query", "budget", "audience" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_batch_collect_args", return_value=( None, ex_mod.BATCH_UNREACHABLE ) ):
            self.assertIsNone( o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" ) )
        self.assertEqual( o._last_expedite_reason, ex_mod.BATCH_UNREACHABLE )

    def test_single_missing_arg_from_fallback_question( self ):
        o = _mk_expeditor( debug=True )
        # everything present except budget → batchable == 1
        with _FlowFixture( o, user_visible=[ "query", "budget" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_ask_for_arg", return_value="50" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertEqual( out[ "budget" ], "50" )

    def test_single_missing_arg_cancel_returns_none( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "query", "budget" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_ask_for_arg", return_value=None ):
            self.assertIsNone( o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" ) )

    def test_single_missing_arg_optional_value_skipped( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "query", "budget" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_ask_for_arg", return_value="no limit" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertNotIn( "budget", out )    # "no limit" → optional skipped

    def test_single_missing_arg_not_in_fallback_questions_generic( self ):
        o = _mk_expeditor()
        # user_visible has an arg with no fallback question → generic "Please provide" prompt
        with _FlowFixture( o, user_visible=[ "query", "weird_arg" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_ask_for_arg", return_value="val" ) as ask, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertEqual( out[ "weird_arg" ], "val" )
        self.assertIn( "Please provide", ask.call_args.args[ 1 ] )

    def test_special_fuzzy_file_match_yaml_sets_render_only( self ):
        o = _mk_expeditor( debug=True )
        # presentation generator: source → fuzzy_file_match; a .yaml selection sets render_only.
        with _FlowFixture( o, user_visible=[ "source" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/deck.yaml" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( PR, "", "u@x", "s", "uid", "make a deck" )
        self.assertEqual( out[ "source" ], "/io/x/deck.yaml" )
        self.assertEqual( out[ "render_only" ], "true" )

    def test_special_fuzzy_file_match_non_yaml( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/report.md" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( PG, "", "u@x", "s", "uid", "make a podcast" )
        self.assertEqual( out[ "research" ], "/io/x/report.md" )
        self.assertNotIn( "render_only", out )

    def test_auto_resolve_scoped_to_podcast_forwards_question( self ):
        # SCOPE FENCE (row bd0ce120): the podcast command MUST forward
        # original_question into the fuzzy handler so its auto pre-step can fire.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/report.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            o.expedite( PG, "", "u@x", "s", "uid", "make a podcast about KISS" )
        self.assertEqual( fuzzy.call_args.kwargs[ "original_question" ], "make a podcast about KISS" )

    def test_auto_resolve_reaches_presentation_too( self ):
        # WAS test_auto_resolve_fence_presentation_gets_none, and it asserted the
        # OPPOSITE: that presentation received original_question=None. That fence was
        # deliberate and temporary — row bd0ce120 held presentation out while the
        # behaviour was proven on podcast, and row 5bc22180 (Rick's go, Approach A)
        # removed it. Keeping the old assertion would have pinned the fence as if it
        # were the requirement, so it is INVERTED here rather than deleted: the same
        # call site, the opposite expectation.
        # Full presentation coverage lives in
        # test_expeditor_presentation_fences_generalized.py.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/deck.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            o.expedite( PR, "", "u@x", "s", "uid", "make a deck about KISS" )
        self.assertEqual( fuzzy.call_args.kwargs[ "original_question" ], "make a deck about KISS" )

    def test_special_tfe_checkpoint_match( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "resume_from" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_tfe_checkpoint_match", return_value="tfe-abcd1234" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( TFE, "", "u@x", "s", "uid", "resume the auth job" )
        self.assertEqual( out[ "resume_from" ], "tfe-abcd1234" )

    def test_special_handler_cancel_returns_none( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value=None ):
            self.assertIsNone( o.expedite( PR, "", "u@x", "s", "uid", "make a deck" ) )

    def test_verbose_prompt_print( self ):
        # line 164: `if self.debug and self.verbose:` prompt-preview print.
        o = _mk_expeditor( debug=True )
        o.verbose = True
        with _FlowFixture( o, user_visible=[ "query" ], parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_confirm_and_iterate", return_value={ "query": "AI" } ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertIsNotNone( out )

    def test_unknown_special_handler_falls_to_ask( self ):
        # line 277: special_handlers value that is neither fuzzy_file_match nor
        # tfe_checkpoint_match → the else arm prompts via _ask_for_arg.
        o = _mk_expeditor()
        custom = {
            "custom command" : {
                "job_prefix"         : "cu",
                "cli_module"         : None,
                "display_name"       : "Custom",
                "required_user_args" : [ "thing" ],
                "system_provided"    : [ "user_id" ],
                "arg_mapping"        : { "thing": "thing" },
                "fallback_questions" : { "thing": "What thing?" },
                "fallback_defaults"  : {},
                "special_handlers"   : { "thing": "unrecognized_handler" },
            }
        }
        with patch.object( ex_mod, "JOB_ARG_CONTRACTS", custom ), \
             _FlowFixture( o, user_visible=[ "thing" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_ask_for_arg", return_value="a thing" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( "custom command", "", "u@x", "s", "uid", "do the thing" )
        self.assertEqual( out[ "thing" ], "a thing" )

    def test_confirm_cancel_returns_none( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "query" ], parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_confirm_and_iterate", return_value=None ):
            self.assertIsNone( o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" ) )


class TestPresentButUnresolvedFixB( unittest.TestCase ):
    """
    Fix B (row bd0ce120): when a fuzzy_file_match arg is PRESENT but its value is
    not an existing path (a bare topic word "KISS" from a natural utterance), the
    expeditor must run the SAME fuzzy matcher rather than hand the topic downstream
    where the podcast job treats it as a file path and dies with FileNotFoundError
    (job.py:216-223). Originally SCOPED to the podcast command; row 5bc22180 removed
    that scope, so presentation's `source` gets the same rescue — its own failure was
    the same bug one step earlier, in the job's path pre-validation.

    Each behaviour test is control-proven: the docstring predicts the exact failure
    text if the guarded code is mutated away, so a green here is a proof, not a claim.

    Added 2026-08-04 by Clayton 😎 (SWE crew lane B, Fix B — Rick-ruled A+B parallel).
    """

    def test_helper_value_is_existing_path( self ):
        # The trigger predicate mirrors job.py:216-223. Bare topic → False (fires
        # the resolve); a real path → True (leaves it); None/"" → False.
        o = _mk_expeditor()
        with patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: p == "/p/io/real.md" ):
            self.assertFalse( o._value_is_existing_path( "KISS" ) )          # bare topic → not a path
            self.assertTrue(  o._value_is_existing_path( "io/real.md" ) )    # relative → resolved under root
            self.assertFalse( o._value_is_existing_path( None ) )
            self.assertFalse( o._value_is_existing_path( "" ) )
        with patch.object( ex_mod.os.path, "exists", return_value=True ):
            self.assertTrue( o._value_is_existing_path( "/abs/existing.md" ) )  # absolute → tested as-is

    def test_present_unresolvable_research_runs_fuzzy_resolve( self ):
        # CORE. research present="KISS" (not missing) + not an existing path →
        # my new block runs the fuzzy matcher, seeded with original_question, and
        # OVERWRITES research with the resolved path.
        # CONTROL — remove the Fix-B block: research stays "KISS" and this fails
        #   AssertionError: 'KISS' != '/io/x/kiss-protocol.md'
        o = _mk_expeditor( debug=True )
        with _FlowFixture( o, user_visible=[ "research" ],
                           parsed=_expeditor_resp( present="research=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/kiss-protocol.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( PG, "", "u@x", "s", "uid", "make me a podcast on KISS" )
        self.assertEqual( out[ "research" ], "/io/x/kiss-protocol.md" )   # resolved, NOT the bare topic
        self.assertEqual( fuzzy.call_args.kwargs[ "original_question" ], "make me a podcast on KISS" )

    def test_present_existing_path_research_left_untouched( self ):
        # CONTROL (idempotence). research present AND already a real path → my block
        # must SKIP it; no re-resolve, value unchanged.
        # If the block fired anyway it would overwrite with the mock — so a mutation
        # dropping the os.path.exists guard fails: '/io/x/other.md' != 'io/deep-research/u/report.md'
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ],
                           parsed=_expeditor_resp( present="research=io/deep-research/u/report.md" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=True ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/other.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( PG, "", "u@x", "s", "uid", "make a podcast from io/deep-research/u/report.md" )
        self.assertEqual( out[ "research" ], "io/deep-research/u/report.md" )
        fuzzy.assert_not_called()

    def test_present_unresolvable_source_is_rescued_for_presentation_too( self ):
        # WAS test_present_unresolvable_scoped_to_podcast_presentation_untouched, and
        # it asserted the OPPOSITE: that `source="KISS"` stayed the bare topic. That
        # was the fence, not the goal — the bare topic then reached
        # presentation_generator/job.py, which raised
        # FileNotFoundError("Source document not found: KISS") and ended the job
        # FAILED. Row 5bc22180 removed the fence, so the assertion is INVERTED rather
        # than deleted: the topic now resolves.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "source" ],
                           parsed=_expeditor_resp( present="source=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/deck.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( PR, "", "u@x", "s", "uid", "make a deck on KISS" )
        self.assertEqual( out[ "source" ], "/io/x/deck.md" )   # resolved, not the bare topic
        fuzzy.assert_called_once()

    def test_present_unresolvable_cancel_returns_none( self ):
        # No-crash contract: when the fuzzy resolve's fall-through prompt is
        # cancelled (handler returns None), expedite returns None cleanly — never a
        # crash, never the bare topic passed downstream.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ],
                           parsed=_expeditor_resp( present="research=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value=None ):
            self.assertIsNone( o.expedite( PG, "", "u@x", "s", "uid", "make me a podcast on KISS" ) )

    def test_missing_research_resolved_by_loop_is_not_double_resolved( self ):
        # GUARD (regression caught by both-roots): when research was MISSING, the
        # missing-args loop's special handler already resolves it. Fix B must NOT
        # re-run the matcher on that just-resolved value — even when the resolved
        # value isn't a real path on disk (a mock here, or a not-yet-written file).
        # The missing-loop owns the missing case; Fix B owns only the present case.
        # CONTROL — drop the `if arg_name in missing` guard: fuzzy is called TWICE
        #   and this fails: "Expected '_handle_fuzzy_file_match' to be called once. Called 2 times."
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ], parsed=_expeditor_resp() ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/resolved.md" ) as fuzzy, \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( PG, "", "u@x", "s", "uid", "make me a podcast on KISS" )
        fuzzy.assert_called_once()   # missing-loop resolves it once; Fix B must NOT re-fire
        self.assertEqual( out[ "research" ], "/io/x/resolved.md" )

    def test_present_unresolvable_yaml_sets_render_only( self ):
        # A .yaml resolve through the present-but-unresolvable branch sets render_only,
        # matching the missing-arg branch's YAML handling.
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "research" ],
                           parsed=_expeditor_resp( present="research=KISS" ) ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_handle_fuzzy_file_match", return_value="/io/x/deck.yaml" ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( PG, "", "u@x", "s", "uid", "make me a podcast on KISS" )
        self.assertEqual( out[ "research" ], "/io/x/deck.yaml" )
        self.assertEqual( out[ "render_only" ], "true" )


if __name__ == "__main__":
    unittest.main()
