"""
Unit tests for runtime_argument_expeditor/expeditor.py — RuntimeArgumentExpeditor
self-contained helper methods (the expedite() top-level flow + the two fuzzy/tfe
special handlers live in test_expeditor_flow.py):

  __init__, _resolve_display_name, _parse_lora_args, _resolve_default,
  _inject_system_args, _extract_comment, _build_request_context, _ask_for_arg,
  _ask_for_confirmation, _parse_modification, _batch_collect_args, _confirm_and_iterate.

ALL boundaries mocked: config_mgr, LlmClientFactory, notify_user_sync,
PromptTemplateProcessor, cu file/path helpers. NO LLM/network/fs.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, runtime_argument_expeditor lane).
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    ArgSpec,
    BATCH_ANSWERED,
    BATCH_DECLINED,
    BATCH_UNREACHABLE,
    BATCH_TIMEOUT,
    BATCH_MALFORMED,
    BATCH_INCOMPLETE,
)
from cosa.agents.runtime_argument_expeditor.xml_models import ArgConfirmationResponse


def _spec( **kw ):
    """Build an ArgSpec for helper tests; absent fields default to empty/None
    (mirrors the former partial agent_entry dicts these tests passed)."""
    base = dict(
        arg_mapping        = {},
        system_provided    = [],
        required_user_args = [],
        fallback_questions = {},
        fallback_defaults  = {},
        special_handlers   = {},
        display_name       = None,
        cli_module         = None,
    )
    base.update( kw )
    return ArgSpec( **base )


def _mk_expeditor( debug=False ):
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    with patch.object( ex_mod, "LlmClientFactory", MagicMock() ):
        o = RuntimeArgumentExpeditor( cfg, debug=debug )
    o._job_id       = None   # NotificationRequest.job_id is Optional + pattern-validated
    o._bearer_token = None
    # config_mgr.get returns None for these keys by default; set valid path strings so
    # the `get_project_root() + path` concatenations don't TypeError.
    o.prompt_template_path     = "/templates/rae.txt"
    o.confirmation_prompt_path = "/templates/confirm.txt"
    o.llm_spec_key             = "rae-llm-spec"
    return o


def _resp( success=True, value="answer", status="ok" ):
    r = MagicMock()
    r.success         = success
    r.response_value  = value
    r.status          = status
    r.exit_code       = 0
    r.is_timeout      = False
    return r


# ============================================================================
# __init__ / _resolve_display_name / _parse_lora_args / _resolve_default
# ============================================================================

class TestInitAndPureHelpers( unittest.TestCase ):

    def test_init_reads_config_keys( self ):
        o = _mk_expeditor()
        self.assertEqual( o.SENDER_ID, "arg.expeditor@lupin.deepily.ai" )
        self.assertIsNone( o._last_notification_status )

    def test_resolve_display_name_explicit( self ):
        self.assertEqual( RuntimeArgumentExpeditor._resolve_display_name( _spec( display_name="Deep Research" ) ),
                          "Deep Research" )

    def test_resolve_display_name_derived_from_cli_module( self ):
        self.assertEqual(
            RuntimeArgumentExpeditor._resolve_display_name( _spec( cli_module="cosa.agents.podcast_generator.cli" ) ),
            "cli",
        )

    def test_resolve_display_name_derived_underscores( self ):
        self.assertEqual(
            RuntimeArgumentExpeditor._resolve_display_name( _spec( cli_module="cosa.agents.swe_team" ) ),
            "swe team",
        )

    def test_resolve_display_name_neither_returns_agent( self ):
        self.assertEqual( RuntimeArgumentExpeditor._resolve_display_name( _spec( cli_module=None ) ), "agent" )

    def test_parse_lora_args_empty( self ):
        o = _mk_expeditor()
        self.assertEqual( o._parse_lora_args( "" ), {} )
        self.assertEqual( o._parse_lora_args( None ), {} )
        self.assertEqual( o._parse_lora_args( "   " ), {} )

    def test_parse_lora_args_all_quote_styles( self ):
        o = _mk_expeditor()
        d = o._parse_lora_args( 'query="quantum computing" budget=10 audience=\'expert\'' )
        self.assertEqual( d[ "query" ], "quantum computing" )
        self.assertEqual( d[ "budget" ], "10" )
        self.assertEqual( d[ "audience" ], "expert" )

    def test_resolve_default_config_override_wins( self ):
        o = _mk_expeditor()
        o.config_mgr.get.side_effect = lambda key, default=None, **kw: "from-config" if "default value for" in key else default
        self.assertEqual( o._resolve_default( "agent router go to deep research", "budget", "registry-def" ),
                          "from-config" )

    def test_resolve_default_falls_back_to_registry( self ):
        o = _mk_expeditor()
        o.config_mgr.get.side_effect = lambda key, default=None, **kw: default   # no override
        self.assertEqual( o._resolve_default( "agent router go to deep research", "budget", "registry-def" ),
                          "registry-def" )

    def test_inject_system_args( self ):
        o = _mk_expeditor()
        spec = _spec( system_provided=[ "user_email", "session_id", "user_id", "no_confirm" ] )
        out = o._inject_system_args( { "query": "x", "user_email": "keep@me" }, spec, "u@x", "s1", "uid1" )
        self.assertEqual( out[ "user_email" ], "keep@me" )   # not overwritten
        self.assertEqual( out[ "session_id" ], "s1" )
        self.assertEqual( out[ "user_id" ], "uid1" )
        self.assertTrue( out[ "no_confirm" ] )

    def test_extract_comment_match_and_none( self ):
        self.assertEqual( RuntimeArgumentExpeditor._extract_comment( "yes [comment: change budget to 10]" ),
                          "change budget to 10" )
        self.assertIsNone( RuntimeArgumentExpeditor._extract_comment( "yes" ) )


# ============================================================================
# _build_request_context
# ============================================================================

class TestBuildRequestContext( unittest.TestCase ):

    def test_with_present_and_missing( self ):
        o = _mk_expeditor()
        spec = _spec( display_name="Deep Research", system_provided=[ "user_id" ] )
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query", "budget" ] ):
            out = o._build_request_context( spec, "cmd", "research AI", { "query": "AI", "user_id": "x" }, [ "budget" ] )
        self.assertIn( "research AI", out )
        self.assertIn( "Already extracted", out )
        self.assertIn( "query: AI", out )
        self.assertNotIn( "user_id", out )    # system arg filtered
        self.assertIn( "Still needed", out )

    def test_empty_present_and_missing( self ):
        o = _mk_expeditor()
        spec = _spec( display_name="X", system_provided=[] )
        with patch.object( ex_mod, "get_user_visible_args", return_value=None ):
            out = o._build_request_context( spec, "cmd", "q", {}, [] )
        self.assertNotIn( "Already extracted", out )
        self.assertNotIn( "Still needed", out )

    def test_uses_passed_command_not_registry_identity_lookup( self ):
        # New seam (row 5982e19b): a spec is not identity-matchable against the
        # registry, so _build_request_context resolves user-visible args via the
        # command passed in. A hand-built spec (NOT in AGENTIC_AGENTS) must still
        # forward the real command — the former reverse lookup would pass None.
        # Proven RED against the reverse-lookup code (receipt in the crew report).
        o    = _mk_expeditor()
        spec = _spec( display_name="X", system_provided=[] )
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ) as guv:
            o._build_request_context( spec, "agent router go to deep research", "q", { "query": "AI" }, [] )
        guv.assert_called_once_with( "agent router go to deep research" )


# ============================================================================
# _ask_for_arg / _ask_for_confirmation
# ============================================================================

class TestAskHelpers( unittest.TestCase ):

    def test_ask_for_arg_success( self ):
        o = _mk_expeditor( debug=True )
        with patch.object( ex_mod, "notify_user_sync", return_value=_resp( value="  biodiversity  " ) ):
            out = o._ask_for_arg( "query", "What topic?", "u@x", response_default="d", abstract="a" )
        self.assertEqual( out, "biodiversity" )

    def test_ask_for_arg_cancellation_keyword( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "notify_user_sync", return_value=_resp( value="cancel" ) ):
            self.assertIsNone( o._ask_for_arg( "query", "?", "u@x" ) )

    def test_ask_for_arg_failure_returns_none( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "notify_user_sync", return_value=_resp( success=False, value=None ) ):
            self.assertIsNone( o._ask_for_arg( "query", "?", "u@x" ) )

    def test_ask_for_confirmation_success( self ):
        o = _mk_expeditor( debug=True )
        with patch.object( ex_mod, "notify_user_sync", return_value=_resp( value=" yes " ) ):
            self.assertEqual( o._ask_for_confirmation( "ok?", "u@x", abstract="a" ), "yes" )

    def test_ask_for_confirmation_failure_returns_none( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "notify_user_sync", return_value=_resp( success=False, value="" ) ):
            self.assertIsNone( o._ask_for_confirmation( "ok?", "u@x" ) )


# ============================================================================
# _parse_modification
# ============================================================================

class TestParseModification( unittest.TestCase ):

    def test_success( self ):
        o = _mk_expeditor( debug=True )
        spec = _spec( system_provided=[ "user_id" ], fallback_questions={ "budget": "?" } )
        llm = MagicMock(); llm.run.return_value = "<response><action>modify</action><arg_name>budget</arg_name><new_value>50</new_value></response>"
        o.llm_factory.get_client = MagicMock( return_value=llm )
        with patch.object( ex_mod.cu, "get_file_as_string", return_value="tmpl {user_response} {current_args} {arg_names}" ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod, "PromptTemplateProcessor" ) as PTP:
            PTP.return_value.process_template.side_effect = lambda t, n: t
            out = o._parse_modification( "change budget to 50", { "budget": "10", "user_id": "x" }, spec )
        self.assertIsInstance( out, ArgConfirmationResponse )
        self.assertTrue( out.is_modify() )

    def test_success_no_fallback_keys_verbose( self ):
        # 463->467 (no fallback_questions → empty fallback_keys) + 477 (debug AND verbose print).
        o = _mk_expeditor( debug=True )
        o.verbose = True
        spec = _spec( system_provided=[] )   # fallback_questions defaults to {} → empty fallback_keys
        llm = MagicMock(); llm.run.return_value = "<response><action>approve</action><arg_name></arg_name><new_value></new_value></response>"
        o.llm_factory.get_client = MagicMock( return_value=llm )
        with patch.object( ex_mod.cu, "get_file_as_string", return_value="t {user_response} {current_args} {arg_names}" ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod, "PromptTemplateProcessor" ) as PTP:
            PTP.return_value.process_template.side_effect = lambda t, n: t
            out = o._parse_modification( "looks good", { "query": "AI" }, spec )
        self.assertTrue( out.is_approval() )

    def test_exception_returns_none( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod.cu, "get_file_as_string", side_effect=RuntimeError( "no file" ) ):
            self.assertIsNone( o._parse_modification( "x", {}, _spec( system_provided=[] ) ) )


# ============================================================================
# _batch_collect_args
# ============================================================================

class TestBatchCollectArgs( unittest.TestCase ):

    def _patch_tts( self ):
        return patch.multiple(
            ex_mod,
            format_open_ended_batch_for_tts=MagicMock( return_value="tts" ),
            convert_open_ended_batch_for_api=MagicMock( return_value={ "questions": [ { "question": "q", "header": "h" } ] } ),
        )

    # ⚠️ _batch_collect_args returns ( answers, reason ) — a 2-tuple on EVERY path
    # (bug 2aaab1bf). None alone cannot carry WHY a collection came back empty, and
    # collapsing every outcome into it is what let a transport failure be reported
    # as a user cancellation. These tests pin the reason, not just the None.

    def test_success_returns_answers( self ):
        o = _mk_expeditor( debug=True )
        resp = _resp( value=json.dumps( { "answers": { "budget": "10", "audience": "expert" } } ) )
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync", return_value=resp ):
            answers, reason = o._batch_collect_args( [ "budget", "audience" ], { "budget": "?", "audience": "?" },
                                                     "u@x", { "budget": "no limit" }, "agent router go to deep research" )
        self.assertEqual( answers, { "budget": "10", "audience": "expert" } )
        self.assertEqual( reason, BATCH_ANSWERED )

    def test_failure_returns_unreachable( self ):
        o = _mk_expeditor()
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync", return_value=_resp( success=False, value=None ) ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], {}, "u@x" )
        self.assertIsNone( answers )
        self.assertEqual( reason, BATCH_UNREACHABLE )

    def test_timeout_returns_timeout( self ):
        o = _mk_expeditor()
        resp = _resp( success=False, value=None )
        resp.is_timeout = True
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync", return_value=resp ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], {}, "u@x" )
        self.assertIsNone( answers )
        self.assertEqual( reason, BATCH_TIMEOUT )

    def test_malformed_json_returns_malformed( self ):
        o = _mk_expeditor( debug=True )
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync", return_value=_resp( value="not json" ) ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], {}, "u@x" )
        self.assertIsNone( answers )
        self.assertEqual( reason, BATCH_MALFORMED )

    def test_cancelled_flag_returns_declined( self ):
        o = _mk_expeditor()
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync",
                                              return_value=_resp( value=json.dumps( { "cancelled": True } ) ) ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], {}, "u@x" )
        self.assertIsNone( answers )
        self.assertEqual( reason, BATCH_DECLINED )

    def test_empty_answers_returns_malformed( self ):
        o = _mk_expeditor()
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync",
                                              return_value=_resp( value=json.dumps( { "answers": {} } ) ) ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], {}, "u@x" )
        self.assertIsNone( answers )
        self.assertEqual( reason, BATCH_MALFORMED )

    def test_cancellation_keyword_in_answer_returns_declined( self ):
        o = _mk_expeditor()
        resp = _resp( value=json.dumps( { "answers": { "a": "stop", "b": "x" } } ) )
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync", return_value=resp ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], {}, "u@x" )
        self.assertIsNone( answers )
        self.assertEqual( reason, BATCH_DECLINED )

    def test_missing_arg_in_answers_returns_incomplete( self ):
        o = _mk_expeditor( debug=True )
        resp = _resp( value=json.dumps( { "answers": { "a": "x" } } ) )   # missing "b"
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync", return_value=resp ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], {}, "u@x" )
        self.assertIsNone( answers )
        self.assertEqual( reason, BATCH_INCOMPLETE )

    def test_default_value_attached_without_command_key( self ):
        # command_key=None → resolved_default = fallback_defaults.get(arg) directly.
        o = _mk_expeditor()
        resp = _resp( value=json.dumps( { "answers": { "a": "1", "b": "2" } } ) )
        with self._patch_tts(), patch.object( ex_mod, "notify_user_sync", return_value=resp ):
            answers, reason = o._batch_collect_args( [ "a", "b" ], { "a": "qa" }, "u@x", { "a": "da" }, command_key=None )
        self.assertEqual( answers, { "a": "1", "b": "2" } )
        self.assertEqual( reason, BATCH_ANSWERED )


# ============================================================================
# _confirm_and_iterate
# ============================================================================

class TestConfirmAndIterate( unittest.TestCase ):

    def _entry( self ):
        return _spec( display_name="Deep Research", fallback_questions={ "query": "?", "budget": "?" } )

    def test_plain_yes_approves( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="yes" ):
            out = o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out, { "query": "AI" } )

    def test_plain_no_cancels( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=None ), \
             patch.object( o, "_ask_for_confirmation", return_value="no" ):
            self.assertIsNone( o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" ) )

    def test_confirmation_none_cancels( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value=None ):
            self.assertIsNone( o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" ) )

    def test_yes_with_comment_applies_modification_then_proceeds( self ):
        o = _mk_expeditor( debug=True )
        mod = ArgConfirmationResponse( action="modify", arg_name="budget", new_value="50" )
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query", "budget" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="yes [comment: set budget to 50]" ), \
             patch.object( o, "_parse_modification", return_value=mod ):
            out = o._confirm_and_iterate( { "query": "AI", "budget": "10" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out[ "budget" ], "50" )

    def test_no_with_comment_modifies_then_reconfirms_yes( self ):
        o = _mk_expeditor( debug=True )
        mod = ArgConfirmationResponse( action="modify", arg_name="budget", new_value="99" )
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query", "budget" ] ), \
             patch.object( o, "_ask_for_confirmation", side_effect=[ "no [comment: bump budget]", "yes" ] ), \
             patch.object( o, "_parse_modification", return_value=mod ):
            out = o._confirm_and_iterate( { "query": "AI", "budget": "10" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out[ "budget" ], "99" )   # modified, then re-confirmed

    def test_no_with_comment_no_modification_cancels( self ):
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="no [comment: nonsense]" ), \
             patch.object( o, "_parse_modification", return_value=None ):
            self.assertIsNone( o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" ) )

    def test_arg_not_in_user_visible_is_skipped_in_summary( self ):
        # 363->362: an arg not in the user_visible whitelist is skipped in the summary.
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="yes" ):
            out = o._confirm_and_iterate( { "query": "AI", "_hidden": "x" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out, { "query": "AI", "_hidden": "x" } )

    def test_yes_prefix_without_comment_proceeds( self ):
        # 396->402: "yes please" → startswith yes, no [comment:] → proceed unchanged.
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="yes please" ):
            out = o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out, { "query": "AI" } )

    def test_yes_with_comment_parse_fails_still_proceeds( self ):
        # 398->402: yes + comment but modification is None → no change, still proceed.
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="yes [comment: gibberish]" ), \
             patch.object( o, "_parse_modification", return_value=None ):
            out = o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out, { "query": "AI" } )

    def test_neither_yes_nor_no_reloops_then_yes( self ):
        # 404->359: a response that is neither yes nor no → loop continues to next iteration.
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", side_effect=[ "hmm not sure", "yes" ] ):
            out = o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out, { "query": "AI" } )

    def test_no_prefix_without_comment_cancels( self ):
        # 405->413: "no thanks" → startswith no, no [comment:] → return None.
        o = _mk_expeditor()
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "query" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="no thanks" ):
            self.assertIsNone( o._confirm_and_iterate( { "query": "AI" }, self._entry(), "cmd", "u@x" ) )

    def test_max_iterations_proceeds( self ):
        # Every iteration returns "no [comment]" with a successful modify → loop never
        # approves/cancels → after 5 iterations the safety valve returns args_dict.
        o = _mk_expeditor( debug=True )
        mod = ArgConfirmationResponse( action="modify", arg_name="budget", new_value="1" )
        with patch.object( ex_mod, "get_user_visible_args", return_value=[ "budget" ] ), \
             patch.object( o, "_ask_for_confirmation", return_value="no [comment: keep tweaking]" ), \
             patch.object( o, "_parse_modification", return_value=mod ):
            out = o._confirm_and_iterate( { "budget": "10" }, self._entry(), "cmd", "u@x" )
        self.assertEqual( out, { "budget": "1" } )   # safety-valve return after max iters


if __name__ == "__main__":
    unittest.main()
