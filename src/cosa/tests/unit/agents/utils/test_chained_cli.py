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
