#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.strategies.llm_script_matcher.

LlmScriptMatcherStrategy loads a Q&A script from disk and fuzzy-matches via
an LLM. The filesystem (open / os.path.exists), the LLM client
(LlmClientFactory + client.run), the prompt-template processor, and the
cosa.utils.util helpers are ALL boundary-mocked → no disk, no vLLM, zero
API spend. Real ScriptMatcherResponse / BatchScriptMatcherResponse parsing
stays in the loop.
"""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

import cosa.agents.notification_proxy.strategies.llm_script_matcher as sm
from cosa.agents.notification_proxy.strategies.llm_script_matcher import (
    LlmScriptMatcherStrategy, resolve_script_path
)
from cosa.agents.notification_proxy.config import DEFAULT_ACCEPTED_SENDERS

EXPEDITER = DEFAULT_ACCEPTED_SENDERS[ 0 ]

SINGLE_MATCH_XML = (
    "<response><matched_entry>1</matched_entry><answer>academic</answer>"
    "<confidence>0.9</confidence><reasoning>r</reasoning></response>"
)
SINGLE_NOMATCH_XML = (
    # matched_entry='none' → is_match() False (answer is non-empty so parsing
    # succeeds and we reach the explicit no-match branch, not the except arm)
    "<response><matched_entry>none</matched_entry><answer>n/a</answer>"
    "<confidence>0.0</confidence><reasoning>nope</reasoning></response>"
)
BATCH_MATCH_XML = (
    "<response><entries>"
    "<entry><header>Budget</header><matched_index>1</matched_index><answer>no limit</answer></entry>"
    "</entries><confidence>0.9</confidence><reasoning>ok</reasoning></response>"
)
BATCH_NOMATCH_XML = (
    # <entries> with no <entry> children → entries normalises to [] →
    # is_match() False cleanly (empty any()), exercising the no-match else branch
    "<response><entries><placeholder/></entries>"
    "<confidence>0.0</confidence><reasoning>no</reasoning></response>"
)


def _make_matcher(
    script           = None,
    factory_raises   = False,
    accepted_senders = None,
    debug            = False,
    verbose          = False,
    exists           = True,
):
    """Build a strategy with filesystem + LLM factory + processor mocked."""
    if script is None:
        script = { "entries": [ { "question_pattern": "q", "answer": "a", "arg_name": "x" } ],
                   "sender_ids": [ EXPEDITER ], "profile_name": "deep_research" }

    fake_client = MagicMock()
    factory     = MagicMock()
    if factory_raises:
        factory.get_client.side_effect = RuntimeError( "no vLLM" )
    else:
        factory.get_client.return_value = fake_client

    m = mock_open( read_data=json.dumps( script ) )
    with patch( "builtins.open", m ), \
         patch.object( sm.os.path, "exists", return_value=exists ), \
         patch.object( sm, "LlmClientFactory", return_value=factory ), \
         patch.object( sm, "PromptTemplateProcessor", return_value=MagicMock() ):
        strat = LlmScriptMatcherStrategy(
            script_path      = "/fake/script.json",
            accepted_senders = accepted_senders,
            debug            = debug,
            verbose          = verbose,
        )
    return strat, fake_client


def _patch_cu():
    cu_mock = MagicMock()
    cu_mock.get_project_root.return_value   = "/root"
    cu_mock.get_file_as_string.return_value = "TEMPLATE"
    return cu_mock


class TestInit:

    def test_file_not_found_raises( self ):
        with pytest.raises( FileNotFoundError ):
            _make_matcher( exists=False )

    def test_available_when_client_builds( self ):
        s, _ = _make_matcher( debug=True )
        assert s.available is True

    def test_unavailable_when_factory_raises( self ):
        s, _ = _make_matcher( factory_raises=True, debug=True )
        assert s.available is False

    def test_accepted_senders_from_param( self ):
        s, _ = _make_matcher( accepted_senders=[ "p@q.r" ] )
        assert s.accepted_senders == [ "p@q.r" ]

    def test_accepted_senders_from_script( self ):
        s, _ = _make_matcher( script={ "entries": [], "sender_ids": [ "script@x.y" ] } )
        assert s.accepted_senders == [ "script@x.y" ]

    def test_accepted_senders_default_when_absent( self ):
        s, _ = _make_matcher( script={ "entries": [] } )
        assert s.accepted_senders == DEFAULT_ACCEPTED_SENDERS


class TestCanHandle:

    def test_rejects_when_unavailable( self ):
        s, _ = _make_matcher( factory_raises=True )
        assert not s.can_handle( { "sender_id": EXPEDITER, "response_requested": True } )

    def test_accepts_expediter( self ):
        s, _ = _make_matcher()
        assert s.can_handle( { "sender_id": EXPEDITER, "response_requested": True } )

    def test_rejects_no_response_requested( self ):
        s, _ = _make_matcher()
        assert not s.can_handle( { "sender_id": EXPEDITER, "response_requested": False } )

    def test_rejects_unknown_sender( self ):
        s, _ = _make_matcher()
        assert not s.can_handle( { "sender_id": "x@y.z", "response_requested": True } )


class TestRespondDispatch:

    def test_unavailable_returns_none( self ):
        s, _ = _make_matcher( factory_raises=True )
        assert s.respond( { "response_type": "open_ended" } ) is None

    def test_dispatches_to_batch( self ):
        s, client = _make_matcher()
        client.run.return_value = BATCH_MATCH_XML
        s._processor.process_template.return_value = "{batch_questions}{script_entries}"
        notif = { "response_type": "open_ended_batch",
                  "response_options": { "questions": [ { "header": "Budget", "question": "?" } ] } }
        with patch.object( sm, "cu", _patch_cu() ):
            out = json.loads( s.respond( notif ) )
        assert out[ "answers" ][ "Budget" ] == "no limit"


class TestHandleSingle:

    def test_open_ended_match_returns_answer( self ):
        s, client = _make_matcher( debug=True, verbose=True )
        client.run.return_value = SINGLE_MATCH_XML
        s._processor.process_template.return_value = "{response_type}{title}{incoming_question}{options_section}{script_entries}"
        with patch.object( sm, "cu", _patch_cu() ):
            out = s.respond( { "response_type": "open_ended", "message": "audience?", "title": "T" } )
        assert out == "academic"

    def test_open_ended_no_match_returns_none( self ):
        s, client = _make_matcher( debug=True )
        client.run.return_value = SINGLE_NOMATCH_XML
        s._processor.process_template.return_value = "{response_type}{title}{incoming_question}{options_section}{script_entries}"
        with patch.object( sm, "cu", _patch_cu() ):
            out = s.respond( { "response_type": "open_ended", "message": "q", "title": "" } )
        assert out is None

    def test_multiple_choice_builds_options_section( self ):
        s, client = _make_matcher()
        client.run.return_value = SINGLE_MATCH_XML
        s._processor.process_template.return_value = "{response_type}{title}{incoming_question}{options_section}{script_entries}"
        notif = {
            "response_type"    : "multiple_choice",
            "message"          : "pick",
            "title"            : "",
            "response_options" : { "questions": [ { "options": [
                { "label": "Alpha", "description": "first" },
                { "label": "Beta" },
            ] } ] },
        }
        with patch.object( sm, "cu", _patch_cu() ):
            out = s.respond( notif )
        assert out == "academic"

    def test_llm_exception_returns_none( self ):
        s, client = _make_matcher( debug=True )
        client.run.side_effect = RuntimeError( "llm boom" )
        s._processor.process_template.return_value = "{response_type}{title}{incoming_question}{options_section}{script_entries}"
        with patch.object( sm, "cu", _patch_cu() ):
            out = s.respond( { "response_type": "open_ended", "message": "q", "title": "" } )
        assert out is None


class TestHandleBatch:

    def _process( self, s ):
        s._processor.process_template.return_value = "{batch_questions}{script_entries}"

    def test_batch_no_questions_returns_none( self ):
        s, _ = _make_matcher( debug=True )
        out = s.respond( { "response_type": "open_ended_batch", "response_options": { "questions": [] } } )
        assert out is None

    def test_batch_match_returns_json( self ):
        s, client = _make_matcher( debug=True, verbose=True )
        client.run.return_value = BATCH_MATCH_XML
        self._process( s )
        notif = { "response_type": "open_ended_batch",
                  "response_options": { "questions": [ { "header": "Budget", "question": "?", "default_value": "d" } ] } }
        with patch.object( sm, "cu", _patch_cu() ):
            out = json.loads( s.respond( notif ) )
        assert out[ "answers" ][ "Budget" ] == "no limit"

    def test_batch_no_match_returns_none( self ):
        s, client = _make_matcher( debug=True )
        client.run.return_value = BATCH_NOMATCH_XML
        self._process( s )
        notif = { "response_type": "open_ended_batch",
                  "response_options": { "questions": [ { "header": "Budget", "question": "?" } ] } }
        with patch.object( sm, "cu", _patch_cu() ):
            out = s.respond( notif )
        assert out is None

    def test_batch_matched_but_empty_answers_returns_none( self ):
        """is_match True but get_answers_dict empty (headerless entry) → None."""
        s, client = _make_matcher( debug=True )
        client.run.return_value = (
            "<response><entries>"
            "<entry><header></header><matched_index>1</matched_index><answer>x</answer></entry>"
            "</entries><confidence>0.9</confidence><reasoning>r</reasoning></response>"
        )
        self._process( s )
        notif = { "response_type": "open_ended_batch",
                  "response_options": { "questions": [ { "header": "Budget", "question": "?" } ] } }
        with patch.object( sm, "cu", _patch_cu() ):
            out = s.respond( notif )
        assert out is None

    def test_batch_llm_exception_returns_none( self ):
        s, client = _make_matcher( debug=True )
        client.run.side_effect = RuntimeError( "batch boom" )
        self._process( s )
        notif = { "response_type": "open_ended_batch",
                  "response_options": { "questions": [ { "header": "Budget", "question": "?" } ] } }
        with patch.object( sm, "cu", _patch_cu() ):
            out = s.respond( notif )
        assert out is None


class TestFilterEntriesByAgent:

    AGENTED = {
        "entries": [
            { "question_pattern": "q1", "answer": "a1", "arg_name": "x" },          # universal (no agents tag)
            { "question_pattern": "q2", "answer": "a2", "agents": [ "deep_research" ] },   # matches
            { "question_pattern": "q3", "answer": "a3", "agents": [ "other_agent" ] },     # filtered out
        ],
        "sender_ids": [ EXPEDITER ],
    }

    def test_no_abstract_returns_all_entries( self ):
        s, _ = _make_matcher( script=self.AGENTED )
        out = s._filter_entries_by_agent( { "abstract": "" } )
        assert len( out ) == 3

    def test_abstract_without_agent_line_returns_all( self ):
        s, _ = _make_matcher( script=self.AGENTED )
        out = s._filter_entries_by_agent( { "abstract": "Some context\nJob: 123" } )
        assert len( out ) == 3

    def test_agent_line_filters_universal_plus_matching( self ):
        s, _ = _make_matcher( script=self.AGENTED, debug=True )
        out = s._filter_entries_by_agent( { "abstract": "**Agent**: Deep Research\nJob: x" } )
        assert len( out ) == 2          # universal + deep_research-tagged, other_agent dropped

    def test_agent_line_plain_prefix( self ):
        s, _ = _make_matcher( script=self.AGENTED )
        out = s._filter_entries_by_agent( { "abstract": "agent: deep research" } )
        assert len( out ) == 2


class TestFormatOptions:

    def test_no_questions_returns_empty( self ):
        s, _ = _make_matcher()
        assert s._format_options( { "response_options": { "questions": [] } } ) == ""

    def test_options_with_and_without_description( self ):
        s, _ = _make_matcher()
        notif = { "response_options": { "questions": [ { "options": [
            { "label": "A", "description": "desc-a" },
            { "label": "B" },
        ] } ] } }
        out = s._format_options( notif )
        assert "desc-a" in out
        assert '"B"' in out


class TestResolveScriptPath:

    def test_explicit_scripts_dir( self ):
        path = resolve_script_path( "deep_research", scripts_dir="/custom" )
        assert path == "/custom/deep-research.json"

    def test_default_scripts_dir_uses_project_root( self ):
        with patch.object( sm, "cu", _patch_cu() ):
            path = resolve_script_path( "all_agents" )
        assert path.endswith( "all-agents.json" )
        assert path.startswith( "/root" )
