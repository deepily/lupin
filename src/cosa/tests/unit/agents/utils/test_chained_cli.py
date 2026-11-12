#!/usr/bin/env python3
"""
Tests for the shared command-line pieces of the chained pipelines.

Each test builds a fresh parser, so nothing leaks between cases.
"""

import argparse
import json
import sys

import pytest

from cosa.agents.utils import chained_cli



def test_deep_research_arguments_order_and_defaults():
    """The seven options come in order, with the recorded defaults."""
    parser = argparse.ArgumentParser()
    chained_cli.add_deep_research_arguments( parser )
    assert [ a.dest for a in parser._actions if a.dest != "help" ] == [
        "query", "user_email", "budget", "lead_model", "no_confirm", "audience", "audience_context" ]
    ns = parser.parse_args( [ "-q", "x", "-u", "y" ] )
    assert vars( ns ) == { "query": "x", "user_email": "y", "budget": None, "lead_model": None,
                           "no_confirm": False, "audience": None, "audience_context": None }


def test_deep_research_arguments_required_and_choices():
    """Query and user email are required, and audience takes four levels."""
    parser = argparse.ArgumentParser()
    chained_cli.add_deep_research_arguments( parser )
    with pytest.raises( SystemExit ): parser.parse_args( [ "-u", "y" ] )
    with pytest.raises( SystemExit ): parser.parse_args( [ "-q", "x" ] )
    with pytest.raises( SystemExit ): parser.parse_args( [ "-q", "x", "-u", "y", "--audience", "kid" ] )
    for level in ( "beginner", "general", "expert", "academic" ):
        assert parser.parse_args( [ "-q", "x", "-u", "y", "--audience", level ] ).audience == level


def test_deep_research_arguments_parse_values():
    """Budget is a float and the short flags map to the same fields."""
    parser = argparse.ArgumentParser()
    chained_cli.add_deep_research_arguments( parser )
    ns = parser.parse_args( [ "-q", "x", "-u", "y", "-b", "1.5", "--lead-model", "m",
                              "--no-confirm", "--audience-context", "c" ] )
    assert ( ns.budget, ns.lead_model, ns.no_confirm, ns.audience_context ) == ( 1.5, "m", True, "c" )


def test_mode_arguments_order_and_defaults():
    """The five mode options come in order and all default to off."""
    parser = argparse.ArgumentParser()
    chained_cli.add_mode_arguments( parser )
    assert [ a.dest for a in parser._actions if a.dest != "help" ] == [
        "cli_mode", "dry_run", "debug", "verbose", "user_visible_args" ]
    assert vars( parser.parse_args( [] ) ) == {
        "cli_mode": False, "dry_run": False, "debug": False, "verbose": False, "user_visible_args": False }


def test_mode_arguments_short_flags():
    """Debug and verbose also answer to the short flags."""
    parser = argparse.ArgumentParser()
    chained_cli.add_mode_arguments( parser )
    ns = parser.parse_args( [ "-d", "-v", "--cli-mode", "--dry-run", "--user-visible-args" ] )
    assert all( vars( ns ).values() )


class _Recorder:
    """Callables that note how they were used."""

    def __init__( self, code=0 ):
        self.code    = code
        self.parsed  = 0
        self.shown   = []
        self.ran     = []

    def parse_args( self ):
        self.parsed += 1
        return argparse.Namespace( dry_run=self.dry_run )

    def show_dry_run( self, args ):
        self.shown.append( args )

    async def run_pipeline( self, args ):
        self.ran.append( args )
        return self.code


def _drive( monkeypatch, argv, dry_run=False, code=0 ):
    """Call run_chained_cli with recorder callables, returning the recorder and exit code."""
    rec         = _Recorder( code )
    rec.dry_run = dry_run
    monkeypatch.setattr( sys, "argv", argv )
    with pytest.raises( SystemExit ) as exc:
        chained_cli.run_chained_cli( rec.parse_args, rec.show_dry_run, rec.run_pipeline, [ "a", "b" ] )
    return rec, exc.value.code


def test_run_chained_cli_user_visible_args_exits_before_parsing( monkeypatch, capsys ):
    """The flag prints the list as JSON and never calls the parser."""
    rec, code = _drive( monkeypatch, [ "prog", "--user-visible-args" ] )
    assert code == 0
    assert json.loads( capsys.readouterr().out ) == [ "a", "b" ]
    assert ( rec.parsed, rec.shown, rec.ran ) == ( 0, [], [] )


def test_run_chained_cli_dry_run_shows_plan_only( monkeypatch ):
    """A dry run calls the plan printer and never the pipeline."""
    rec, code = _drive( monkeypatch, [ "prog" ], dry_run=True )
    assert code == 0
    assert ( rec.parsed, len( rec.shown ), rec.ran ) == ( 1, 1, [] )


@pytest.mark.parametrize( "pipeline_code", [ 0, 1, 3 ] )
def test_run_chained_cli_exits_with_pipeline_code( monkeypatch, pipeline_code ):
    """The exit code is the one the pipeline returned, and the pipeline got the parsed namespace."""
    rec, code = _drive( monkeypatch, [ "prog" ], code=pipeline_code )
    assert code == pipeline_code
    assert rec.shown == []
    assert len( rec.ran ) == 1 and isinstance( rec.ran[ 0 ], argparse.Namespace )


class _Result:
    """Just enough of a ChainedResult for the report."""

    def __init__( self, success=False, partial=False ):
        self.success, self.partial = success, partial
        self.research_path, self.research_abstract = "/io/r.md", "A" * 150
        self.dr_cost, self.error, self.duration_seconds = 1.25, "boom", 12.34
        self.state = type( "S", ( ), { "value": "failed" } )()

    def is_success( self ): return self.success
    def is_partial( self ): return self.partial


class _Agent:
    """An agent whose run_async returns a result, or raises what it was given."""

    def __init__( self, outcome ): self.outcome = outcome

    async def run_async( self ):
        if isinstance( self.outcome, BaseException ): raise self.outcome
        return self.outcome


def _report( agent, debug=False ):
    import asyncio
    shown = [ ]
    code  = asyncio.run( chained_cli.run_agent_and_report(
        argparse.Namespace( debug=debug ), agent, "Podcast Generation", shown.append, "retry --research {research_path}" ) )
    return code, shown


def test_a_complete_run_prints_the_report_then_the_stage_lines_then_the_duration( capsys ):
    result = _Result( success=True )
    code, shown = _report( _Agent( result ) )
    out = capsys.readouterr().out
    assert code == 0 and shown == [ result ]
    assert "Research Report: /io/r.md" in out and f"Abstract: {'A' * 100}..." in out and "A" * 101 not in out
    assert "Duration: 12.3 seconds" in out


def test_a_complete_run_without_an_abstract_prints_no_abstract_line( capsys ):
    result = _Result( success=True )
    result.research_abstract = None
    code, _shown = _report( _Agent( result ) )
    assert code == 0 and "Abstract:" not in capsys.readouterr().out


def test_a_partial_run_names_the_stage_and_the_formatted_retry_command( capsys ):
    code, shown = _report( _Agent( _Result( partial=True ) ) )
    out = capsys.readouterr().out
    assert code == 1 and shown == [ ]
    assert "Podcast Generation failed:" in out and "  Error: boom" in out
    assert "retry podcast generation separately with:" in out
    assert "  retry --research /io/r.md" in out and "Cost: $1.2500" in out


def test_any_other_result_prints_its_state_and_error( capsys ):
    code, shown = _report( _Agent( _Result() ) )
    out = capsys.readouterr().out
    assert code == 1 and shown == [ ]
    assert "State: failed" in out and "Error: boom" in out


def test_ctrl_c_and_an_exception_each_return_one( capsys ):
    assert _report( _Agent( KeyboardInterrupt() ) )[ 0 ] == 1
    assert "Interrupted by user" in capsys.readouterr().out
    assert _report( _Agent( RuntimeError( "bad" ) ) )[ 0 ] == 1
    out = capsys.readouterr().out
    assert "Pipeline error: bad" in out and "Traceback" not in out


def test_an_exception_prints_a_traceback_only_under_debug( capsys ):
    assert _report( _Agent( RuntimeError( "bad" ) ), debug=True )[ 0 ] == 1
    captured = capsys.readouterr()
    assert "Pipeline error: bad" in captured.out and "RuntimeError: bad" in captured.err


def test_each_package_prints_its_own_artifact_lines_and_cost_summary( capsys ):
    from cosa.agents.deep_research_to_podcast import __main__ as podcast_main
    from cosa.agents.deep_research_to_presentation import __main__ as presentation_main
    capsys.readouterr()   # the imports above can log; start from an empty capture
    result = _Result( success=True )
    result.pg_cost, result.total_cost = 2.5, 3.75
    result.audio_path, result.script_path = "/io/a.mp3", "/io/s.md"
    podcast_main._show_success( result )
    assert capsys.readouterr().out == (
        "\nPodcast Audio: /io/a.mp3\nPodcast Script: /io/s.md\n\nCost Summary:\n"
        "  Deep Research:     $1.2500\n  Podcast Generator: $2.5000\n  Total:             $3.7500\n" )
    result.script_path = None
    podcast_main._show_success( result )
    assert "Podcast Script" not in capsys.readouterr().out
    result.yaml_path, result.marp_path = "/io/d.yaml", "/io/d.md"
    presentation_main._show_success( result )
    assert capsys.readouterr().out == (
        "\nPresentation YAML: /io/d.yaml\nPresentation Marp: /io/d.md\n\nCost Summary:\n"
        "  Deep Research:            $1.2500\n  Presentation Generator:   $2.5000\n  Total:                    $3.7500\n" )


def _pipeline_args():
    return argparse.Namespace(
        query="q", user_email="a@x.com", budget=None, lead_model=None, no_confirm=False, audience=None,
        audience_context=None, cli_mode=True, debug=False, verbose=False,
        languages=None, max_segments=None, target_duration_minutes=None, target_slide_count=None, theme=None )


@pytest.mark.parametrize( "package, agent_name, stage_label, retry_command", [
    ( "deep_research_to_podcast",      "DeepResearchToPodcastAgent",      "Podcast Generation",
      "python -m cosa.agents.podcast_generator --research {research_path}" ),
    ( "deep_research_to_presentation", "DeepResearchToPresentationAgent", "Presentation Generation",
      "python -m cosa.agents.presentation_generator --source {research_path}" ),
] )
def test_each_run_pipeline_hands_its_own_stage_label_and_retry_command_to_the_shared_runner(
        monkeypatch, package, agent_name, stage_label, retry_command ):
    import asyncio
    import importlib
    main_module = importlib.import_module( f"cosa.agents.{package}.__main__" )
    agent_pkg   = importlib.import_module( f"cosa.agents.{package}" )
    built       = [ ]
    calls       = [ ]

    class _FakeAgent:
        def __init__( self, **kwargs ): built.append( kwargs )

    async def _fake_runner( args, agent, label, show_success, retry ):
        calls.append( ( agent, label, show_success, retry ) )
        return 7

    monkeypatch.setattr( agent_pkg, agent_name, _FakeAgent )
    monkeypatch.setattr( main_module, "run_agent_and_report", _fake_runner )
    assert asyncio.run( main_module.run_pipeline( _pipeline_args() ) ) == 7
    assert len( built ) == 1 and len( calls ) == 1
    agent, label, show_success, retry = calls[ 0 ]
    assert isinstance( agent, _FakeAgent )
    assert ( label, retry ) == ( stage_label, retry_command )
    assert show_success is main_module._show_success
