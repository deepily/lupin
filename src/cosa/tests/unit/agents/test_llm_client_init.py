#!/usr/bin/env python3
"""
Unit tests for cosa.agents.llm_client_init and its four callers.

The judge, the v2 judge and the answer verifier each print their own tag.
So a caller test checks the printed line for that class.
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.llm_client_init import init_llm_client


class _Factory:
    """A factory double that records what it was asked and returns a marker client."""

    calls = []

    def __init__( self, debug=False, verbose=False ):
        self.ctor = ( debug, verbose )

    def get_client( self, key, debug=False, verbose=False ):
        _Factory.calls.append( ( self.ctor, key, debug, verbose ) )
        return f"client-for-{key}"


class _BrokenFactory:
    """A factory whose client build fails."""

    def __init__( self, debug=False, verbose=False ):
        pass

    def get_client( self, key, debug=False, verbose=False ):
        raise RuntimeError( "no such model" )


class TestInitLlmClient:
    """The shared build step."""

    def test_success_returns_the_client_and_passes_the_flags_through( self, capsys ):
        _Factory.calls = []
        assert init_llm_client( _Factory, "some/key", "Tag", True, False ) == ( "client-for-some/key", True )
        assert _Factory.calls == [ ( ( True, False ), "some/key", True, False ) ]
        assert capsys.readouterr().out == "[Tag] LLM client ready (some/key)\n"

    def test_success_is_silent_without_debug( self, capsys ):
        init_llm_client( _Factory, "k", "Tag" )
        assert capsys.readouterr().out == ""

    def test_a_failed_build_returns_no_client_and_says_why( self, capsys ):
        assert init_llm_client( _BrokenFactory, "k", "Tag" ) == ( None, False )
        assert capsys.readouterr().out == "[Tag] LLM client unavailable: no such model\n"

    def test_a_failing_factory_constructor_is_handled_the_same_way( self, capsys ):
        boom = MagicMock( side_effect=ValueError( "bad config" ) )
        assert init_llm_client( boom, "k", "Tag" ) == ( None, False )
        assert "[Tag] LLM client unavailable: bad config" in capsys.readouterr().out


CALLERS = [
    ( "cosa.agents.dm_quality_judge.judge",                          "DmQualityJudge",              "DmQualityJudge" ),
    ( "cosa.agents.dm_quality_judge.judge_v2",                       "DmQualityJudgeV2",            "DmQualityJudgeV2" ),
    ( "cosa.agents.notification_proxy.verification",                 "LlmAnswerVerifier",           "AnswerVerifier" ),
    ( "cosa.agents.notification_proxy.strategies.llm_script_matcher", "LlmScriptMatcherStrategy",   "LlmScriptMatcher" ),
]


def _build( module, cls, factory, tmp_path, debug=False ):
    """
    Build one caller class with its module's LlmClientFactory name replaced.

    Ensures:
        - the script matcher gets a real one-entry script file, since its constructor reads one
        - returns the built object
    """
    import importlib
    import json
    mod    = importlib.import_module( module )
    kwargs = { "debug": debug }
    if cls == "LlmScriptMatcherStrategy":
        script = tmp_path / "script.json"
        script.write_text( json.dumps( { "entries": [], "sender_ids": [ "x" ], "profile_name": "p" } ) )
        kwargs[ "script_path" ] = str( script )
    with patch.object( mod, "LlmClientFactory", factory ):
        return getattr( mod, cls )( **kwargs )


@pytest.mark.parametrize( "module, cls, tag", CALLERS )
class TestCallersUseIt:
    """Each class ends up available with a client, or unavailable with none, under its tag."""

    def test_available_when_the_factory_builds( self, module, cls, tag, tmp_path ):
        obj = _build( module, cls, _Factory, tmp_path )
        assert obj.available is True
        assert obj._client.startswith( "client-for-" )

    def test_unavailable_and_tagged_when_it_fails( self, module, cls, tag, tmp_path, capsys ):
        obj = _build( module, cls, _BrokenFactory, tmp_path )
        assert obj.available is False
        assert obj._client is None
        assert f"[{tag}] LLM client unavailable: no such model" in capsys.readouterr().out

    def test_debug_prints_the_ready_line_under_its_tag( self, module, cls, tag, tmp_path, capsys ):
        _build( module, cls, _Factory, tmp_path, debug=True )
        assert f"[{tag}] LLM client ready (" in capsys.readouterr().out

    def test_debug_flag_reaches_the_factory( self, module, cls, tag, tmp_path ):
        _Factory.calls = []
        _build( module, cls, _Factory, tmp_path, debug=True )
        assert _Factory.calls[ 0 ][ 0 ][ 0 ] is True
