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
                           return_value={ "budget": "no limit", "audience": "expert", "audience_context": "none" } ), \
             patch.object( o, "_confirm_and_iterate", side_effect=lambda a, *r: a ):
            out = o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )
        self.assertEqual( out[ "audience" ], "expert" )
        self.assertNotIn( "budget", out )    # "no limit" skipped

    def test_batch_collect_cancel_returns_none( self ):
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "query", "budget", "audience" ],
                           parsed=_expeditor_resp( present="query=AI" ) ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_batch_collect_args", return_value=None ):
            self.assertIsNone( o.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" ) )

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
        with patch.object( ex_mod, "AGENTIC_AGENTS", custom ), \
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


if __name__ == "__main__":
    unittest.main()
