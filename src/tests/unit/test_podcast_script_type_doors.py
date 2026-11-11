#!/usr/bin/env python3
"""
Unit tests for how script_type, review and languages cross each podcast door.

Doors covered here: both factory builders, both jobs, the chained agent, the CLI and
saved-script loading. A request with none of the three produces a research-critical,
English-only, ask-for-review job.
"""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.podcast_generator import __main__ as cli
from cosa.agents.podcast_generator import orchestrator as orch_mod
from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
from cosa.agents.podcast_generator.state import PodcastScript, ScriptSegment
from cosa.rest.v2.refusal import SubmitRefused
from cosa.rest.agentic_job_factory import _podcast_languages, create_agentic_job
from tests.helpers.podcast_prompt_capture import RecordingClient

PG = "agent router go to podcast generator"
RP = "agent router go to research to podcast"


def _job( command, **extra ):
    args = { "research": "io/r.md" } if command == PG else { "query": "q" }
    args.update( extra )
    return create_agentic_job( command, args, "u", "u@t.com", "s" )


# --- factory: the languages alias and the new args ----------------------------------------------

@pytest.mark.parametrize( "command", [ PG, RP ] )
def test_no_type_no_languages_means_research_critical_english_ask( command ):
    job = _job( command )
    assert ( job.script_type, job.review, job.target_languages ) == ( None, None, [ "en" ] )


@pytest.mark.parametrize( "command", [ PG, RP ] )
def test_the_factory_drives_both_language_key_names( command ):
    assert _job( command, languages="en,es-MX" ).target_languages == [ "en", "es-MX" ]
    assert _job( command, target_languages=[ "en", "es-MX" ] ).target_languages == [ "en", "es-MX" ]
    assert _job( command, target_languages="es-MX" ).target_languages == [ "es-MX" ]
    assert _job( command, languages="en", target_languages=[ "en", "es-MX" ] ).target_languages == [ "en" ]


@pytest.mark.parametrize( "command", [ PG, RP ] )
def test_the_factory_carries_script_type_and_review( command ):
    job = _job( command, script_type="status_report", review="ask" )
    assert ( job.script_type, job.review ) == ( "status_report", "ask" )


@pytest.mark.parametrize( "command", [ PG, RP ] )
def test_the_factory_refuses_an_unknown_type_or_review( command ):
    with pytest.raises( SubmitRefused, match="Unknown script_type" ):
        _job( command, script_type="nope" )
    with pytest.raises( SubmitRefused, match="Unknown review" ):
        _job( command, review="maybe" )


def test_podcast_languages_helper_shapes():
    assert _podcast_languages( {} ) is None
    assert _podcast_languages( { "languages": "" } ) is None
    assert _podcast_languages( { "languages": " en , es-MX ," } ) == [ "en", "es-MX" ]
    assert _podcast_languages( { "target_languages": [ "es" ] } ) == [ "es" ]


# --- jobs reach the config ------------------------------------------------------------------------

def _run_job_execute( job ):
    seen = {}

    class _Agent:
        podcast_id = "pg-x"

        def __init__( self, **kw ):
            seen.update( kw )
            self._podcast_state = {}

        async def do_all_async( self ):
            return None

    with patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", _Agent ), \
         patch( "cosa.agents.podcast_generator.voice_io.notify", new=AsyncMock() ), \
         patch( "os.path.exists", return_value=True ):
        asyncio.run( job._execute() )
    return seen


def test_podcast_job_resolves_its_config_from_the_request():
    job  = _job( PG, script_type="status_report", audience="expert", audience_context="an SRE" )
    seen = _run_job_execute( job )
    config = seen[ "config" ]
    assert ( config.script_type, config.review, config.audience, config.audience_context ) == ( "status_report", "one_shot", "expert", "an SRE" )
    assert config.target_duration_minutes == 5


def test_podcast_job_with_no_type_keeps_todays_defaults():
    config = _run_job_execute( _job( PG ) )[ "config" ]
    assert ( config.script_type, config.review ) == ( "research_critical", "ask" )


def test_chained_job_hands_type_and_review_to_its_agent():
    job   = _job( RP, script_type="status_report", review="ask", languages="en,es-MX" )
    agent = job._make_agent()
    assert ( agent.script_type, agent.review, agent.target_languages ) == ( "status_report", "ask", [ "en", "es-MX" ] )


def test_chained_agent_reads_the_ini_and_applies_the_type():
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    agent = DeepResearchToPodcastAgent( query="q", user_email="u@t.com", script_type="status_report", audience="expert" )
    seen  = {}

    class _Orch:
        podcast_id = "pg-x"
        _api_client = None

        def __init__( self, **kw ):
            seen.update( kw )
            self._podcast_state = {}

        async def do_all_async( self ):
            return None

    with patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", _Orch ), \
         patch( "os.path.exists", return_value=True ), \
         patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ):
        out = asyncio.run( agent._run_podcast_generator( "/io/r.md" ) )
    assert out == { "cancelled": True }
    config = seen[ "config" ]
    assert ( config.script_type, config.review, config.audience, config.min_exchanges ) == ( "status_report", "one_shot", "expert", 6 )


def test_chained_agent_with_no_type_is_research_critical_with_the_ini_numbers():
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    agent = DeepResearchToPodcastAgent( query="q", user_email="u@t.com" )
    seen  = {}

    class _Orch:
        podcast_id = "pg-x"

        def __init__( self, **kw ):
            seen.update( kw )
            self._podcast_state = {}

        async def do_all_async( self ):
            return None

    with patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", _Orch ), \
         patch( "os.path.exists", return_value=True ), \
         patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ):
        asyncio.run( agent._run_podcast_generator( "/io/r.md" ) )
    assert ( seen[ "config" ].script_type, seen[ "config" ].review ) == ( "research_critical", "ask" )
    assert seen[ "target_languages" ] == [ "en" ]


# --- CLI -----------------------------------------------------------------------------------------

def _cli_args( **over ):
    base = dict( cli_mode=False, languages=None, research="/proj/r.md", user_id="u@t.com", dry_run=False,
                 audience=None, audience_context=None, script_type=None, review=None, debug=False, verbose=False )
    base.update( over )
    return MagicMock( **base )


def _run_cli_generation( **over ):
    seen = {}

    class _Orch:
        podcast_id = "pg-x"

        def __init__( self, **kw ):
            seen.update( kw )

        async def do_all_async( self ):
            return None

    with patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", _Orch ), \
         patch( "os.path.exists", return_value=True ):
        rc = asyncio.run( cli.run_podcast_generation( _cli_args( **over ) ) )
    return rc, seen[ "config" ]


def test_cli_passes_type_and_review_into_the_config():
    rc, config = _run_cli_generation( script_type="status_report", review="ask" )
    assert rc == 1 and ( config.script_type, config.review ) == ( "status_report", "ask" )


def test_cli_with_no_flags_is_research_critical_ask():
    rc, config = _run_cli_generation()
    assert ( config.script_type, config.review ) == ( "research_critical", "ask" )


def test_cli_flags_are_parsed_and_unknown_values_are_refused( monkeypatch, capsys ):
    seen = {}

    async def _fake( args ):
        seen[ "args" ] = args
        return 0

    monkeypatch.setattr( cli, "run_podcast_generation", _fake )
    monkeypatch.setattr( sys, "argv", [ "pg", "--research", "r.md", "--script-type", "status_report", "--review", "one_shot" ] )
    with pytest.raises( SystemExit ) as ex:
        cli.main()
    assert ex.value.code == 0 and ( seen[ "args" ].script_type, seen[ "args" ].review ) == ( "status_report", "one_shot" )
    monkeypatch.setattr( sys, "argv", [ "pg", "--research", "r.md", "--script-type", "nope" ] )
    with pytest.raises( SystemExit ) as ex:
        cli.main()
    assert ex.value.code == 2


def test_the_user_visible_args_name_the_new_options():
    assert { "script_type", "review" } <= set( cli.USER_VISIBLE_ARGS )


def test_cli_edit_script_carries_type_and_review( tmp_path ):
    path = tmp_path / "s.md"
    path.write_text( _saved( "status_report" ), encoding="utf-8" )
    seen = {}

    class _Agent:
        podcast_id = "pg-x"
        _podcast_state = { "draft_script": MagicMock( title="T", get_segment_count=lambda: 1 ), "revision_count": 0 }

        async def do_review_only_async( self ):
            return None

    async def _fake_load( cls, **kw ):
        seen.update( kw )
        return _Agent()

    args = MagicMock( cli_mode=False, edit_script=str( path ), user_id="u", script_type="status_report", review="ask", debug=False, verbose=False )
    with patch.object( PodcastOrchestratorAgent, "from_saved_script", classmethod( _fake_load ) ):
        rc = asyncio.run( cli.run_script_editing( args ) )
    assert rc == 1 and seen[ "script_type" ] == "status_report" and seen[ "config" ].review == "ask"


# --- saved scripts: from_saved_script and review-only ---------------------------------------------

def _saved( script_type ):
    script = PodcastScript( title="T", research_source="/io/r.md", generated_at="2026-01-01T00:00:00", host_a_name="A", host_b_name="B",
                            segments=[ ScriptSegment( speaker="A", role="curious", text="Hi there", prosody=[] ) ], script_type=script_type )
    return script.to_markdown( include_script_type=True )


def _load( tmp_path, script_type=None, saved_type=None, config=None ):
    path = tmp_path / "s.md"
    path.write_text( _saved( saved_type ), encoding="utf-8" )
    return asyncio.run( PodcastOrchestratorAgent.from_saved_script( script_path=str( path ), user_id="u@t.com", config=config, script_type=script_type ) )


def test_a_typed_script_runs_as_its_own_type( tmp_path ):
    agent = _load( tmp_path, saved_type="status_report" )
    assert agent.config.script_type == "status_report" and agent.profile.name == "status_report"
    assert agent._script_type_unknown is False


def test_an_explicit_type_beats_the_one_the_file_records( tmp_path ):
    agent = _load( tmp_path, script_type="research_critical", saved_type="status_report", config=PodcastConfig( review="ask" ) )
    assert agent.config.script_type == "research_critical" and agent.config.review == "ask"


def test_the_callers_config_object_is_not_mutated( tmp_path ):
    config = PodcastConfig()
    _load( tmp_path, saved_type="status_report", config=config )
    assert config.script_type == "research_critical"


def test_an_unknown_explicit_type_is_refused( tmp_path ):
    with pytest.raises( ValueError, match="Unknown script_type" ):
        _load( tmp_path, script_type="nope" )


def test_review_only_refuses_an_untyped_script_but_accepts_one_given_a_type( tmp_path ):
    agent = _load( tmp_path )
    assert agent._script_type_unknown is True
    with pytest.raises( ValueError, match="records no script type" ):
        asyncio.run( agent.do_review_only_async() )
    assert _load( tmp_path, script_type="status_report" )._script_type_unknown is False


def test_review_only_on_a_status_script_revises_with_the_status_prompt( tmp_path ):
    agent = _load( tmp_path, saved_type="status_report" )
    reply = json.dumps( { "title": "T", "segments": [ { "speaker": "A", "role": "curious", "text": "Shorter" } ] } )
    agent._api_client = RecordingClient( { "revision": reply } )
    agent._podcast_state[ "revision_count" ] = 1
    with patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ):
        revised = asyncio.run( agent._revise_script_async( agent._podcast_state[ "draft_script" ], "shorter" ) )
    from cosa.agents.podcast_generator.script_types import get_profile
    assert agent._api_client.calls[ "revision" ][ "system" ] == get_profile( "status_report" ).system_prompt
    assert revised.script_type == "status_report"
