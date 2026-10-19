"""
Unit tests for the shared smoke-block helpers and the five callers they replaced.

Twin refactor slice smoke-block-helpers: the date-and-time and math agents share one smoke walk,
and the podcast and presentation __main__ modules share one import-and-run suite.
"""

import sys
import types

import pytest

from cosa.agents import date_and_time_agent, math_agent
from cosa.agents.podcast_generator import __main__ as podcast_main
from cosa.agents.presentation_generator import __main__ as presentation_main


class _FakeAgent:
    """Records the calls the smoke walk makes; run_prompt can be told to fail."""
    fail_in = None
    calls   = []

    def __init__( self, question, debug, verbose, auto_debug ):
        type( self ).calls = [ ( "init", question, debug, verbose, auto_debug ) ]
        self.answer_conversational = "the answer"

    def _step( self, name ):
        type( self ).calls.append( name )
        if type( self ).fail_in == name: raise RuntimeError( "boom" )

    def run_prompt( self ):    self._step( "run_prompt" )
    def run_code( self ):      self._step( "run_code" )
    def run_formatter( self ): self._step( "run_formatter" )


@pytest.fixture
def fake_agent():
    _FakeAgent.fail_in = None
    _FakeAgent.calls   = []
    return _FakeAgent


class TestAgentSmokeBlocks:

    @pytest.mark.parametrize( "module, cls_name, question, label, error_context", [
        ( date_and_time_agent, "DateAndTimeAgent", "What time is it in Washington DC?", "DateAndTimeAgent", "agent execution" ),
        ( math_agent,          "MathAgent",        "What's the square root of 144?",    "MathAgent",        "math agent execution" ),
    ] )
    def test_walk_and_messages( self, module, cls_name, question, label, error_context, fake_agent, monkeypatch, capsys ):
        monkeypatch.setattr( module, cls_name, fake_agent )
        module.quick_smoke_test()
        out = capsys.readouterr().out
        assert fake_agent.calls == [ ( "init", question, True, False, False ), "run_prompt", "run_code", "run_formatter" ]
        assert f"Testing question: '{question}'" in out
        for line in ( f"✓ {label} created successfully", "✓ Prompt execution completed", "✓ Code execution completed",
                      "✓ Formatter execution completed", "✓ Final response: the answer" ):
            assert line in out
        assert out.rstrip().endswith( f"✓ {label} smoke test completed" )

        fake_agent.fail_in = "run_code"
        module.quick_smoke_test()
        out = capsys.readouterr().out
        assert f"✗ Error during {error_context}: boom" in out
        assert "✓ Formatter execution completed" not in out
        assert out.rstrip().endswith( f"✓ {label} smoke test completed" )


def _fake_modules( monkeypatch, paths, failing = None, message = "x" * 100 ):
    """Put a stand-in with a quick_smoke_test into sys.modules for each path."""
    ran = []
    for path in paths:
        def _run( path = path ):
            ran.append( path )
            if path == failing: raise RuntimeError( message )
        monkeypatch.setitem( sys.modules, path, types.SimpleNamespace( quick_smoke_test = _run ) )
    return ran


class TestImportSmokeSuites:

    def test_podcast_suite_runs_each_module_and_cuts_errors_at_60( self, monkeypatch, capsys ):
        paths = [ f"cosa.agents.podcast_generator.{n}" for n in (
            "config", "state", "prompts.script_generation", "prompts.personality", "cosa_interface",
            "voice_io", "api_client", "tts_client", "audio_stitcher", "orchestrator" ) ]
        ran = _fake_modules( monkeypatch, paths, failing = paths[ 6 ] )
        assert podcast_main.run_all_smoke_tests() is False
        out = capsys.readouterr().out
        assert ran == paths[ :10 ]
        assert "Podcast Generator - Full Smoke Test Suite" in out
        assert "  ✗ api_client: FAILED" in out and "  ✓ config: PASSED" in out
        assert "      Error: " + "x" * 60 + "\n" in out
        assert "Total: 9 passed, 1 failed out of 10 modules" in out

    def test_presentation_suite_cuts_errors_at_80_and_passes_when_clean( self, monkeypatch, capsys ):
        paths = [ f"cosa.agents.presentation_generator.{n}" for n in (
            "config", "state", "cosa_interface", "voice_io", "orchestrator", "job" ) ]
        _fake_modules( monkeypatch, paths, failing = paths[ 5 ] )
        assert presentation_main.run_all_smoke_tests() is False
        out = capsys.readouterr().out
        assert "Presentation Generator - Full Smoke Test Suite" in out
        assert "      Error: " + "x" * 80 + "\n" in out
        assert "Total: 5 passed, 1 failed out of 6 modules" in out

        _fake_modules( monkeypatch, paths )
        assert presentation_main.run_all_smoke_tests() is True
        assert "Total: 6 passed, 0 failed out of 6 modules" in capsys.readouterr().out


class TestRunImportSmokeSuite:

    def test_default_cut_is_80_and_every_module_runs_after_a_failure( self, monkeypatch, capsys ):
        from cosa.agents.utils.smoke_suite import run_import_smoke_suite
        paths = [ "twin_smoke_fake.a", "twin_smoke_fake.b", "twin_smoke_fake.c" ]
        ran   = _fake_modules( monkeypatch, paths, failing = paths[ 0 ], message = "y" * 120 )
        assert run_import_smoke_suite( "Fake", [ ( "a", paths[ 0 ] ), ( "b", paths[ 1 ] ), ( "c", paths[ 2 ] ) ] ) is False
        out = capsys.readouterr().out
        assert ran == paths
        assert "Fake - Full Smoke Test Suite" in out
        assert "      Error: " + "y" * 80 + "\n" in out
        assert "y" * 81 not in out

    def test_an_empty_list_passes( self, capsys ):
        from cosa.agents.utils.smoke_suite import run_import_smoke_suite
        assert run_import_smoke_suite( "Fake", [] ) is True
        assert "Total: 0 passed, 0 failed out of 0 modules" in capsys.readouterr().out
