#!/usr/bin/env python3
"""
Unit tests for `DmTutorAgent` — the object the DM send path calls.

Two things are under test and they are not the same thing:

1. **Construction.** The prompt that leaves the constructor must be fully
   processed. Every failure here is SILENT in production — `AgentBase` swallows
   the template processor's exception in a bare `except` (`agent_base.py:161`)
   and ships the template as-is, so a missing registration produces a literal
   `{{PYDANTIC_XML_EXAMPLE}}` in the prompt and no `</stop>` sentinel, with
   nothing raised anywhere.

2. **The fail-closed contract.** `rewrite()` and `rewrite_dm()` return None on
   every failure and raise on none of them. None means "deliver the original".
   A tutor that raises into a sender's call stack, or that returns a partial
   rewrite, is worse than no tutor: the recipient cannot tell which kind of
   message they are holding.

No model is called. The live path is exercised by `dm_txt_run.py`.
"""

import pytest

from cosa.agents.dm_tutor.agent      import DmTutorAgent, rewrite_dm
from cosa.agents.dm_tutor.xml_models import DmTutorResponse


BODY = (
    "I spent the morning tracing the leak and I am fairly confident it sits at "
    "src/cosa/rest/queue.py:412, which is the line that shipped in f4e0370 last "
    "Tuesday. Have a look when you get a moment."
)


def _fields( **overrides ):
    """A well-formed run_prompt() return value, overridable per test."""
    fields = {
        "thoughts"                : "reasoning",
        "declaration_or_question" : "The leak is at src/cosa/rest/queue.py:412",
        "supporting_1st"          : "It shipped in f4e0370 last Tuesday",
        "supporting_2nd"          : "Take a look when you get a moment",
        "file_path_or_url"        : "",
    }
    fields.update( overrides )
    return fields


class TestConstruction:
    """Every check here guards a failure that is silent without it."""

    def test_the_body_is_substituted( self ):
        assert "queue.py:412" in DmTutorAgent( dm_body=BODY ).prompt

    def test_no_unresolved_body_marker( self ):
        assert "{dm}" not in DmTutorAgent( dm_body=BODY ).prompt

    def test_the_xml_example_was_injected( self ):
        """A literal marker here means the routing command is not in MODEL_MAPPING."""
        assert "{{PYDANTIC_XML_EXAMPLE}}" not in DmTutorAgent( dm_body=BODY ).prompt

    def test_the_stop_sentinel_is_present_by_default( self ):
        assert "</stop>" in DmTutorAgent( dm_body=BODY ).prompt

    def test_the_prompt_teaches_cdata( self ):
        """Without this instruction a literal angle bracket in prose kills the parse."""
        assert "CDATA" in DmTutorAgent( dm_body=BODY ).prompt

    def test_the_prompt_teaches_the_path_slot( self ):
        assert "file-path-or-url-if-present" in DmTutorAgent( dm_body=BODY ).prompt

    def test_tag_names_match_the_response_model( self ):
        agent = DmTutorAgent( dm_body=BODY )
        assert agent.xml_response_tag_names == list( DmTutorResponse.TAG_FOR_FIELD.values() )

    @pytest.mark.parametrize( "empty", [ "", "   ", "\n\t ", None ] )
    def test_an_empty_body_is_refused( self, empty ):
        with pytest.raises( ValueError ):
            DmTutorAgent( dm_body=empty )

    def test_an_explicit_question_is_left_alone( self ):
        """
        `AgentBase` refuses to construct without a question, so the body stands
        in for one. A caller who supplies a real question must keep it — the
        stand-in is a fallback, not an override.
        """
        agent = DmTutorAgent( dm_body=BODY, question="why is the queue leaking?" )
        assert agent.question == "why is the queue leaking?"
        assert "queue.py:412" in agent.prompt

    def test_a_last_question_asked_also_suppresses_the_stand_in( self ):
        agent = DmTutorAgent( dm_body=BODY, last_question_asked="what shipped Tuesday?" )
        assert agent.question != BODY

    def test_a_body_full_of_braces_does_not_raise( self ):
        """
        `.replace()` not `.format()`. DM bodies carry code fences, dict literals
        and f-strings; str.format reads every brace as a field and raises on the
        first one it cannot resolve.
        """
        body   = 'run f"{x}" then {"a": 1} and {{literal}} plus [[L00]]'
        prompt = DmTutorAgent( dm_body=body ).prompt
        assert '{"a": 1}' in prompt
        assert "{{literal}}" in prompt


class TestSentinelControlArm:
    """The control must differ in the sentinel and in nothing else."""

    def test_the_control_arm_has_no_sentinel( self ):
        assert "</stop>" not in DmTutorAgent( dm_body=BODY, include_stop_sentinel=False ).prompt

    def test_the_arms_differ_by_exactly_the_sentinel( self ):
        """
        A control that differs in more than the one variable measures something
        other than the variable.
        """
        with_it    = DmTutorAgent( dm_body=BODY, include_stop_sentinel=True ).prompt
        without_it = DmTutorAgent( dm_body=BODY, include_stop_sentinel=False ).prompt

        assert len( with_it ) - len( without_it ) == len( "</stop>" )
        assert with_it.replace( "</stop>", "" ) == without_it

    def test_the_control_arm_is_otherwise_complete( self ):
        control = DmTutorAgent( dm_body=BODY, include_stop_sentinel=False ).prompt
        assert "{{PYDANTIC_XML_EXAMPLE}}" not in control
        assert "queue.py:412" in control
        assert "CDATA" in control


class TestRewriteSucceeds:
    """The happy path, with the model stubbed."""

    def test_it_returns_the_delivered_lines( self, monkeypatch ):
        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt", lambda **kw: _fields() )

        assert agent.rewrite().splitlines() == [
            "The leak is at src/cosa/rest/queue.py:412",
            "It shipped in f4e0370 last Tuesday",
            "Take a look when you get a moment",
        ]

    def test_a_pointer_becomes_a_fourth_line( self, monkeypatch ):
        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt",
                             lambda **kw: _fields( file_path_or_url="src/cosa/rest/queue.py:412" ) )

        lines = agent.rewrite().splitlines()
        assert len( lines ) == 4
        assert lines[ -1 ] == "src/cosa/rest/queue.py:412"

    def test_a_null_word_pointer_is_dropped( self, monkeypatch ):
        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt", lambda **kw: _fields( file_path_or_url="N/A" ) )

        assert len( agent.rewrite().splitlines() ) == 3

    def test_a_bare_id_pointer_is_dropped_AND_announced( self, monkeypatch, capsys ):
        """
        Row 56a3c48d. Dropping the id is the delivery fix; SAYING SO is the second half
        — a suppression nobody can see is one nobody can audit, and the reader asking
        "why did this DM carry no path" would otherwise find nothing to read.
        """
        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt", lambda **kw: _fields( file_path_or_url="fb9faba7" ) )

        assert len( agent.rewrite().splitlines() ) == 3
        assert "[dm-tutor] pointer_slot_cleared=fb9faba7" in capsys.readouterr().out

    def test_an_ordinary_send_says_nothing_about_the_slot( self, monkeypatch, capsys ):
        """
        CONTROL. The line must fire on the refusal ONLY. A notice printed on every send
        is noise, and noise is how the real one gets missed — so a real path and a
        null-word both stay quiet.
        """
        for value in ( "src/cosa/rest/queue.py:412", "N/A" ):
            agent = DmTutorAgent( dm_body=BODY )
            monkeypatch.setattr( agent, "run_prompt", lambda **kw: _fields( file_path_or_url=value ) )
            agent.rewrite()
            assert "pointer_slot_cleared" not in capsys.readouterr().out

    def test_the_parsed_response_is_kept_for_inspection( self, monkeypatch ):
        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt", lambda **kw: _fields() )
        agent.rewrite()

        assert isinstance( agent.response, DmTutorResponse )
        assert agent.error is None


class TestFailClosed:
    """Every failure returns None, and none of them raise."""

    @pytest.mark.parametrize( "boom", [
        ConnectionError( "vLLM unreachable" ),
        TimeoutError( "read timed out" ),
        ValueError( "Pydantic model not yet implemented for agent: dm tutor rewrite" ),
        RuntimeError( "something nobody predicted" ),
    ] )
    def test_a_model_failure_returns_none( self, monkeypatch, boom ):
        def _raise( **kw ): raise boom

        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt", _raise )

        assert agent.rewrite() is None
        assert agent.response is None

    def test_a_dropped_required_slot_returns_none( self, monkeypatch ):
        """A two-line delivery must never travel as though it were a three-line one."""
        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt", lambda **kw: _fields( supporting_2nd="" ) )

        assert agent.rewrite() is None

    def test_a_missing_required_slot_returns_none( self, monkeypatch ):
        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt",
                             lambda **kw: { "thoughts" : "t", "declaration_or_question" : "d" } )

        assert agent.rewrite() is None

    def test_the_failure_reason_is_kept( self, monkeypatch ):
        """
        A discarded reason is an unanswerable question — three of the 2026-08-11
        setup failures were exactly this.
        """
        def _raise( **kw ): raise ConnectionError( "vLLM unreachable" )

        agent = DmTutorAgent( dm_body=BODY )
        monkeypatch.setattr( agent, "run_prompt", _raise )
        agent.rewrite()

        assert "ConnectionError" in agent.error
        assert "vLLM unreachable" in agent.error


class TestRewriteDmEntryPoint:
    """The free function the DM send path calls. It must never raise."""

    def test_it_delivers_on_the_happy_path( self, monkeypatch ):
        monkeypatch.setattr( DmTutorAgent, "run_prompt", lambda self, **kw: _fields() )
        assert rewrite_dm( BODY ).startswith( "The leak is at" )

    @pytest.mark.parametrize( "empty", [ "", "   ", None ] )
    def test_an_empty_body_returns_none_rather_than_raising( self, empty ):
        """
        The constructor raises ValueError on an empty body. Callers in the send
        path must not have to know that.
        """
        assert rewrite_dm( empty ) is None

    def test_a_construction_failure_returns_none( self, monkeypatch ):
        """
        A missing INI key or an unregistered routing command must deliver the
        original message, not raise into the sender's call stack.
        """
        def _raise( self, *a, **kw ): raise KeyError( "prompt template for dm tutor rewrite" )

        monkeypatch.setattr( DmTutorAgent, "__init__", _raise )
        assert rewrite_dm( BODY ) is None

    def test_a_model_failure_returns_none( self, monkeypatch ):
        def _raise( self, **kw ): raise ConnectionError( "vLLM unreachable" )

        monkeypatch.setattr( DmTutorAgent, "run_prompt", _raise )
        assert rewrite_dm( BODY ) is None

    def test_it_passes_the_sentinel_flag_through( self, monkeypatch ):
        seen = {}

        original = DmTutorAgent.__init__
        def _spy( self, *a, **kw ):
            seen[ "sentinel" ] = kw.get( "include_stop_sentinel" )
            original( self, *a, **kw )

        monkeypatch.setattr( DmTutorAgent, "__init__", _spy )
        monkeypatch.setattr( DmTutorAgent, "run_prompt", lambda self, **kw: _fields() )

        rewrite_dm( BODY, include_stop_sentinel=False )
        assert seen[ "sentinel" ] is False


class TestNotImplemented:
    """The one method this agent deliberately does not have."""

    def test_restore_from_serialized_state_raises( self ):
        with pytest.raises( NotImplementedError ):
            DmTutorAgent( dm_body=BODY ).restore_from_serialized_state( "/tmp/nope.json" )
