#!/usr/bin/env python3
"""
Behaviour of the two chained pipeline command-line entry points.

The podcast and presentation packages each have a module that runs as a
script. These tests drive both through their public functions, so they
hold across the move of the shared code into one helper module.
"""

import argparse
import hashlib
import json
import sys

import pytest

import cosa.agents.deep_research_to_podcast.__main__ as podcast_cli
import cosa.agents.deep_research_to_presentation.__main__ as presentation_cli

MODULES = [ podcast_cli, presentation_cli ]
IDS     = [ "podcast", "presentation" ]

BASE_ARGV = [ "prog", "--query", "q", "--user-email", "u@example.com" ]

# What a bare invocation parses to, for the options both modules share
SHARED_DEFAULTS = {
    "query"            : "q",
    "user_email"       : "u@example.com",
    "budget"           : None,
    "lead_model"       : None,
    "no_confirm"       : False,
    "audience"         : None,
    "audience_context" : None,
    "cli_mode"         : False,
    "dry_run"          : False,
    "debug"            : False,
    "verbose"          : False,
    "user_visible_args": False,
}

PODCAST_ONLY_DEFAULTS      = { "languages": None, "max_segments": None }
PRESENTATION_ONLY_DEFAULTS = { "target_duration_minutes": None, "target_slide_count": None, "theme": None }

# Hashes of the full help text, taken from the code before the shared helper existed
HELP_SHA256 = {
    "podcast"      : "e4f72399b3fee447c1d7c84593b5be8140c0e573f75c0e9b26019a3681d25bc5",
    "presentation" : "645dfb05761f12173620876ca4dd3ddeb739365ab1e31c02a52ae7ade9c4747f",
}


def _parse( module, monkeypatch, argv ):
    """Run parse_args of a module against an argument list."""
    monkeypatch.setattr( sys, "argv", argv )
    return module.parse_args()


@pytest.mark.parametrize( "module, name", list( zip( MODULES, IDS ) ), ids=IDS )
def test_help_text_is_unchanged( module, name, monkeypatch, capsys ):
    """The full help text, options in order, matches the recorded hash."""
    monkeypatch.setattr( sys, "argv", [ "prog", "--help" ] )
    monkeypatch.setenv( "COLUMNS", "100" )
    with pytest.raises( SystemExit ) as exc:
        module.parse_args()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert hashlib.sha256( out.encode() ).hexdigest() == HELP_SHA256[ name ]


def test_podcast_defaults( monkeypatch ):
    """A bare podcast invocation parses to the recorded defaults."""
    ns = _parse( podcast_cli, monkeypatch, BASE_ARGV )
    assert vars( ns ) == { **SHARED_DEFAULTS, **PODCAST_ONLY_DEFAULTS }


def test_presentation_defaults( monkeypatch ):
    """A bare presentation invocation parses to the recorded defaults."""
    ns = _parse( presentation_cli, monkeypatch, BASE_ARGV )
    assert vars( ns ) == { **SHARED_DEFAULTS, **PRESENTATION_ONLY_DEFAULTS }


def test_podcast_every_flag( monkeypatch ):
    """Every podcast flag, in long and short form, lands on its own field."""
    argv = [ "prog", "-q", "topic", "-u", "a@b.c", "-b", "2.5", "--lead-model", "m1",
             "--no-confirm", "--audience", "expert", "--audience-context", "ctx",
             "-l", "en,es-MX", "-m", "7", "--cli-mode", "--dry-run", "-d", "-v",
             "--user-visible-args" ]
    ns = _parse( podcast_cli, monkeypatch, argv )
    assert vars( ns ) == {
        "query": "topic", "user_email": "a@b.c", "budget": 2.5, "lead_model": "m1",
        "no_confirm": True, "audience": "expert", "audience_context": "ctx",
        "languages": "en,es-MX", "max_segments": 7, "cli_mode": True, "dry_run": True,
        "debug": True, "verbose": True, "user_visible_args": True,
    }


def test_presentation_every_flag( monkeypatch ):
    """Every presentation flag, in long and short form, lands on its own field."""
    argv = [ "prog", "-q", "topic", "-u", "a@b.c", "-b", "2.5", "--lead-model", "m1",
             "--no-confirm", "--audience", "beginner", "--audience-context", "ctx",
             "--duration", "20", "--slide-count", "12", "--theme", "dark",
             "--cli-mode", "--dry-run", "-d", "-v", "--user-visible-args" ]
    ns = _parse( presentation_cli, monkeypatch, argv )
    assert vars( ns ) == {
        "query": "topic", "user_email": "a@b.c", "budget": 2.5, "lead_model": "m1",
        "no_confirm": True, "audience": "beginner", "audience_context": "ctx",
        "target_duration_minutes": 20, "target_slide_count": 12, "theme": "dark",
        "cli_mode": True, "dry_run": True, "debug": True, "verbose": True,
        "user_visible_args": True,
    }


@pytest.mark.parametrize( "module", MODULES, ids=IDS )
@pytest.mark.parametrize( "missing", [ "--query", "--user-email" ] )
def test_required_options_are_enforced( module, missing, monkeypatch ):
    """Leaving out the query or the user email is a usage error."""
    argv = list( BASE_ARGV )
    i    = argv.index( missing )
    del argv[ i : i + 2 ]
    monkeypatch.setattr( sys, "argv", argv )
    with pytest.raises( SystemExit ) as exc:
        module.parse_args()
    assert exc.value.code == 2


@pytest.mark.parametrize( "module", MODULES, ids=IDS )
def test_audience_choices_are_enforced( module, monkeypatch ):
    """An audience outside the four levels is a usage error."""
    monkeypatch.setattr( sys, "argv", BASE_ARGV + [ "--audience", "toddler" ] )
    with pytest.raises( SystemExit ) as exc:
        module.parse_args()
    assert exc.value.code == 2


def test_user_visible_args_constants():
    """Each module lists its own end-user options."""
    assert podcast_cli.USER_VISIBLE_ARGS == [ "query", "budget", "languages", "audience", "audience_context" ]
    assert presentation_cli.USER_VISIBLE_ARGS == [
        "query", "budget", "target_duration_minutes", "target_slide_count", "theme",
        "audience", "audience_context" ]


@pytest.mark.parametrize( "module", MODULES, ids=IDS )
def test_main_prints_user_visible_args_before_parsing( module, monkeypatch, capsys ):
    """The flag exits before the required options are checked."""
    monkeypatch.setattr( sys, "argv", [ "prog", "--user-visible-args" ] )
    with pytest.raises( SystemExit ) as exc:
        module.main()
    assert exc.value.code == 0
    assert json.loads( capsys.readouterr().out ) == module.USER_VISIBLE_ARGS


@pytest.mark.parametrize( "module", MODULES, ids=IDS )
def test_main_dry_run_prints_plan_and_exits_zero( module, monkeypatch, capsys ):
    """A dry run shows the plan and never starts the pipeline."""
    monkeypatch.setattr( sys, "argv", BASE_ARGV + [ "--dry-run" ] )

    async def boom( args ):
        raise AssertionError( "pipeline must not run on a dry run" )

    monkeypatch.setattr( module, "run_pipeline", boom )
    with pytest.raises( SystemExit ) as exc:
        module.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "[DRY RUN MODE - No API calls will be made]" in out
    assert "Query: q" in out


@pytest.mark.parametrize( "module", MODULES, ids=IDS )
@pytest.mark.parametrize( "code", [ 0, 1 ] )
def test_main_exits_with_the_pipeline_code( module, code, monkeypatch ):
    """The process exit code is whatever run_pipeline returned."""
    seen = []

    async def fake_pipeline( args ):
        seen.append( args )
        return code

    monkeypatch.setattr( sys, "argv", BASE_ARGV )
    monkeypatch.setattr( module, "run_pipeline", fake_pipeline )
    with pytest.raises( SystemExit ) as exc:
        module.main()
    assert exc.value.code == code
    assert len( seen ) == 1
    assert isinstance( seen[ 0 ], argparse.Namespace )
    assert seen[ 0 ].query == "q"
