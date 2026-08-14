#!/usr/bin/env python3
"""
Unit tests for the extract() / collect() split of RuntimeArgumentExpeditor.expedite()
(v1 behavior-preserving refactor, store row e010d5e2).

- extract(): non-interactive half — resolves known args, computes what is missing,
  returns an ExtractionResult. Takes agent_entry as a parameter (the AGENTIC_AGENTS
  lookup stays in the expedite() shim).
- collect(): interactive half — prompts for missing args, confirms, injects system args.
- expedite(): thin shim = extract() then collect(). One test proves its output is
  IDENTICAL to calling the two halves by hand (María's explicit bar).

Reuses the shared seam fixtures from test_expeditor_flow. NO LLM / network / fs.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python \
     -m pytest src/cosa/tests/unit/agents/runtime_argument_expeditor/test_expeditor_extract_collect.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import ExtractionResult, ArgSpec
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS


def _spec( entry ):
    """ArgSpec the expedite() shim would build from a registry entry."""
    return ArgSpec.from_entry( entry )

from cosa.tests.unit.agents.runtime_argument_expeditor.test_expeditor_flow import (
    _mk_expeditor,
    _FlowFixture,
    _expeditor_resp,
    DR,
)


def _extraction( final_args, missing, entry, fallback_defaults=None ):
    """Build an ExtractionResult from a registry entry, for collect() tests."""
    return ExtractionResult(
        final_args         = final_args,
        missing            = missing,
        fallback_questions = entry[ "fallback_questions" ],
        fallback_defaults  = fallback_defaults if fallback_defaults is not None else {},
        special_handlers   = entry.get( "special_handlers", {} ),
    )


class TestArgSpecFromEntry( unittest.TestCase ):

    def test_carries_required_fields_by_reference( self ):
        entry = AGENTIC_AGENTS[ DR ]
        spec  = ArgSpec.from_entry( entry )
        self.assertIs( spec.arg_mapping,        entry[ "arg_mapping" ] )
        self.assertIs( spec.fallback_questions, entry[ "fallback_questions" ] )
        self.assertEqual( spec.required_user_args, entry[ "required_user_args" ] )

    def test_absent_optional_fields_default_to_fresh_empty_dicts( self ):
        # An entry without fallback_defaults / special_handlers → fresh {} each,
        # matching the former entry.get( key, {} ) semantics inside extract().
        entry = { "arg_mapping": {}, "system_provided": [], "required_user_args": [],
                  "fallback_questions": {} }
        spec  = ArgSpec.from_entry( entry )
        self.assertEqual( spec.fallback_defaults, {} )
        self.assertEqual( spec.special_handlers, {} )

    def test_present_optional_fields_kept_by_reference( self ):
        fd    = { "query": "seed" }
        sh    = { "research": "fuzzy_file_match" }
        entry = { "arg_mapping": {}, "system_provided": [], "required_user_args": [],
                  "fallback_questions": {}, "fallback_defaults": fd, "special_handlers": sh }
        spec  = ArgSpec.from_entry( entry )
        self.assertIs( spec.fallback_defaults, fd )
        self.assertIs( spec.special_handlers, sh )


class TestExtract( unittest.TestCase ):

    def test_returns_extraction_result_with_missing( self ):
        o     = _mk_expeditor( debug=True )
        entry = AGENTIC_AGENTS[ DR ]
        with _FlowFixture( o, user_visible=[ "query" ], parsed=_expeditor_resp() ):
            result = o.extract( DR, "", "research AI", _spec( entry ) )
        self.assertIsInstance( result, ExtractionResult )
        self.assertEqual( result.missing, [ "query" ] )
        self.assertEqual( result.final_args, {} )
        # required arg with no default → seeded with the original question
        self.assertEqual( result.fallback_defaults[ "query" ], "research AI" )

    def test_all_present_no_missing( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        with _FlowFixture( o, user_visible=[ "query" ], parsed=_expeditor_resp( present="query=AI" ) ):
            result = o.extract( DR, 'query="AI"', "research AI", _spec( entry ) )
        self.assertEqual( result.missing, [] )
        self.assertEqual( result.final_args[ "query" ], "AI" )

    def test_help_none_uses_placeholder_and_still_extracts( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        with _FlowFixture( o, help_text=None, user_visible=[ "query" ],
                           parsed=_expeditor_resp( present="query=AI" ) ):
            result = o.extract( DR, 'query="AI"', "research AI", _spec( entry ) )
        self.assertEqual( result.final_args[ "query" ], "AI" )

    def test_parse_exception_falls_back_to_all_missing( self ):
        o     = _mk_expeditor( debug=True )
        entry = AGENTIC_AGENTS[ DR ]
        with _FlowFixture( o, user_visible=[ "query" ], parse_raises=True ):
            result = o.extract( DR, "", "research AI", _spec( entry ) )
        self.assertIn( "query", result.missing )

    def test_user_visible_none_falls_back_to_fallback_question_keys( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        with _FlowFixture( o, user_visible=None, parsed=_expeditor_resp( present="query=AI" ) ):
            result = o.extract( DR, 'query="AI"', "research AI", _spec( entry ) )
        # user_visible None → keys of fallback_questions; query already present so
        # the remaining fallback keys land in missing.
        self.assertNotIn( "query", result.missing )
        self.assertIn( "budget", result.missing )

    def test_extract_does_not_consult_agentic_agents_registry( self ):
        # Mr. Radio's bar: extract() resolves off the agent_entry PARAMETER, never
        # a registry lookup. With AGENTIC_AGENTS emptied, a self-lookup would
        # KeyError/None; passing the spec in must still work. This guard is
        # PROVEN to fail if the lookup is reinstated (red receipt in the report).
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        with patch.object( ex_mod, "AGENTIC_AGENTS", {} ), \
             _FlowFixture( o, user_visible=[ "query" ], parsed=_expeditor_resp( present="query=AI" ) ):
            result = o.extract( DR, 'query="AI"', "research AI", _spec( entry ) )
        self.assertEqual( result.final_args[ "query" ], "AI" )


class TestCollect( unittest.TestCase ):

    def test_no_missing_confirms_and_injects( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        extraction = _extraction( { "query": "AI" }, [], entry )
        with patch.object( o, "_confirm_and_iterate", return_value={ "query": "AI" } ):
            out = o.collect( extraction, DR, "research AI", entry, "u@x", "s", "uid" )
        self.assertEqual( out[ "query" ], "AI" )
        self.assertEqual( out[ "user_email" ], "u@x" )   # system args injected

    def test_single_missing_asks_and_injects( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        extraction = _extraction( {}, [ "query" ], entry, fallback_defaults={ "query": "research AI" } )
        with patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_resolve_default",       return_value="research AI" ), \
             patch.object( o, "_ask_for_arg",           return_value="AI topic" ), \
             patch.object( o, "_confirm_and_iterate",   return_value={ "query": "AI topic" } ):
            out = o.collect( extraction, DR, "research AI", entry, "u@x", "s", "uid" )
        self.assertEqual( out[ "query" ], "AI topic" )

    def test_single_missing_user_cancels_returns_none( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        extraction = _extraction( {}, [ "query" ], entry, fallback_defaults={ "query": "research AI" } )
        with patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_resolve_default",       return_value="research AI" ), \
             patch.object( o, "_ask_for_arg",           return_value=None ):
            out = o.collect( extraction, DR, "research AI", entry, "u@x", "s", "uid" )
        self.assertIsNone( out )

    def test_confirmation_cancel_returns_none( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        extraction = _extraction( { "query": "AI" }, [], entry )
        with patch.object( o, "_confirm_and_iterate", return_value=None ):
            out = o.collect( extraction, DR, "research AI", entry, "u@x", "s", "uid" )
        self.assertIsNone( out )


class TestExpediteShimUnchanged( unittest.TestCase ):

    def test_expedite_delegates_extract_then_collect( self ):
        o     = _mk_expeditor()
        entry = AGENTIC_AGENTS[ DR ]
        sentinel = MagicMock( name="extraction" )
        with patch.object( o, "extract", return_value=sentinel ) as mx, \
             patch.object( o, "collect", return_value={ "ok": 1 } ) as mc:
            out = o.expedite( DR, "raw", "u@x", "s", "uid", "q", job_id="j", bearer_token="b" )
        self.assertEqual( out, { "ok": 1 } )
        # extract() now receives an ArgSpec the shim built from the entry; collect()
        # still receives the raw entry.
        mx.assert_called_once_with( DR, "raw", "q", ArgSpec.from_entry( entry ) )
        mc.assert_called_once_with( sentinel, DR, "q", entry, "u@x", "s", "uid" )
        self.assertEqual( o._job_id, "j" )
        self.assertEqual( o._bearer_token, "b" )

    def test_unknown_command_short_circuits_in_shim( self ):
        o = _mk_expeditor( debug=True )
        with patch.object( o, "extract" ) as mx, patch.object( o, "collect" ) as mc:
            out = o.expedite( "no such command", "", "u@x", "s", "uid", "do it" )
        self.assertIsNone( out )
        mx.assert_not_called()
        mc.assert_not_called()

    def test_expedite_output_equals_manual_extract_then_collect( self ):
        # María's bar: expedite() must produce EXACTLY what the two halves produce
        # when composed by hand under identical seams.
        entry  = AGENTIC_AGENTS[ DR ]
        parsed = _expeditor_resp( present="query=AI" )

        o1 = _mk_expeditor()
        with _FlowFixture( o1, user_visible=[ "query" ], parsed=parsed ), \
             patch.object( o1, "_confirm_and_iterate", return_value={ "query": "AI" } ):
            via_expedite = o1.expedite( DR, 'query="AI"', "u@x", "s", "uid", "research AI" )

        o2 = _mk_expeditor()
        with _FlowFixture( o2, user_visible=[ "query" ], parsed=parsed ), \
             patch.object( o2, "_confirm_and_iterate", return_value={ "query": "AI" } ):
            extraction = o2.extract( DR, 'query="AI"', "research AI", _spec( entry ) )
            via_manual = o2.collect( extraction, DR, "research AI", entry, "u@x", "s", "uid" )

        self.assertEqual( via_expedite, via_manual )
        self.assertIsNotNone( via_expedite )


if __name__ == "__main__":
    unittest.main()
