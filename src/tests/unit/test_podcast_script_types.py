#!/usr/bin/env python3
"""
Unit tests for the podcast script types: profiles, precedence, golden prompts, digest.

The golden file was captured from main before any script-type code existed.
"""

import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

import cosa.utils.util as cu
from cosa.agents.podcast_generator import script_types as st
from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.podcast_generator.orchestrator import PodcastGenerationError, PodcastOrchestratorAgent
from cosa.agents.podcast_generator.state import DigestItem, PodcastScript, ScriptSegment, StatusDigest
from tests.helpers.podcast_prompt_capture import CALL_SITES, RecordingClient, SOURCE_TEXT, capture_prompts

GOLDEN_PATH = os.path.join( os.path.dirname( __file__ ), "fixtures", "podcast", "golden_prompts_main_778332bb9.json" )


class _Cfg:
    """Config manager double: answers from a dict, else the default the caller passed."""

    def __init__( self, values=None ):
        self.values = values or {}

    def exists( self, key ):
        return key in self.values

    def get( self, key, default=None, silent=False, return_type="string" ):
        raw = self.values.get( key, default )
        if return_type == "int":     return int( raw )
        if return_type == "float":   return float( raw )
        if return_type == "boolean": return str( raw ).lower() == "true"
        return raw


def _real_cfg():
    from cosa.config.configuration_manager import ConfigurationManager
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def _golden():
    with open( GOLDEN_PATH, encoding="utf-8" ) as f:
        return json.load( f )


# --- golden file: research_critical is unchanged -------------------------------------------

@pytest.mark.parametrize( "site", CALL_SITES )
def test_default_type_matches_golden_at_every_call_site( site ):
    assert capture_prompts()[ site ] == _golden()[ site ]


@pytest.mark.parametrize( "site", CALL_SITES )
def test_explicit_research_critical_matches_golden( site ):
    config = PodcastConfig( script_type="research_critical", review="ask" )
    assert capture_prompts( config=config )[ site ] == _golden()[ site ]


def test_golden_covers_all_four_sites_with_real_text():
    golden = _golden()
    assert sorted( golden ) == sorted( CALL_SITES )
    for site in CALL_SITES:
        assert len( golden[ site ][ "system" ] ) > 500 and len( golden[ site ][ "user" ] ) > 500


def test_status_report_changes_every_system_prompt_and_the_script_user_prompt():
    calls = capture_prompts( config=PodcastConfig( script_type="status_report" ), replies={ "analysis": _digest_json() } )
    golden = _golden()
    for site in CALL_SITES:
        assert calls[ site ][ "system" ] != golden[ site ][ "system" ]
    assert calls[ "script" ][ "user" ] != golden[ "script" ][ "user" ]
    assert "Use suggested analogies" not in calls[ "script" ][ "user" ]
    assert "Start with an engaging hook" not in calls[ "script" ][ "user" ]
    assert "Use suggested analogies" in golden[ "script" ][ "user" ]
    assert calls[ "revision" ][ "user" ] == golden[ "revision" ][ "user" ]


# --- profiles ------------------------------------------------------------------------------

def test_unknown_type_is_refused_everywhere():
    with pytest.raises( ValueError, match="Unknown script_type 'nope'" ):
        st.get_profile( "nope" )
    with pytest.raises( ValueError, match="research_critical" ):
        st.resolve_podcast_config( _Cfg(), script_type="nope" )
    with pytest.raises( ValueError ):
        PodcastOrchestratorAgent( research_doc_path="x", user_id="u", config=PodcastConfig( script_type="nope" ) )


def test_none_means_the_default_type():
    assert st.get_profile( None ).name == "research_critical"
    assert st.get_profile( None ).review_default == "ask"
    assert st.get_profile( "status_report" ).review_default == "one_shot"


def test_unknown_review_is_refused():
    with pytest.raises( ValueError, match="Unknown review 'maybe'" ):
        st.validate_review( "maybe" )
    assert st.validate_review( None ) is None
    assert st.validate_review( "ask" ) == "ask"
    with pytest.raises( ValueError ):
        st.resolve_podcast_config( _Cfg(), review="maybe" )


def test_effective_review_uses_config_then_profile():
    assert st.effective_review( PodcastConfig() ) == "ask"
    assert st.effective_review( PodcastConfig( script_type="status_report" ) ) == "one_shot"
    assert st.effective_review( PodcastConfig( script_type="status_report", review="ask" ) ) == "ask"
    assert st.effective_review( PodcastConfig( review="one_shot" ) ) == "one_shot"


# --- precedence: request beats profile beats INI --------------------------------------------

def test_ini_keys_exist_in_the_real_ini_with_the_documented_values():
    config = st.resolve_podcast_config( _real_cfg(), script_type="status_report" )
    assert ( config.target_duration_minutes, config.min_exchanges, config.max_exchanges, config.audience ) == ( 5, 6, 10, "general" )


def test_default_type_keeps_the_generic_ini_numbers():
    ini = PodcastConfig.from_config( _real_cfg() )
    config = st.resolve_podcast_config( _real_cfg() )
    assert config.script_type == "research_critical" and config.review == "ask"
    assert ( config.target_duration_minutes, config.min_exchanges, config.max_exchanges, config.audience ) == \
           ( ini.target_duration_minutes, ini.min_exchanges, ini.max_exchanges, ini.audience )


def test_profile_beats_the_generic_ini_keys():
    cfg    = _Cfg( { "podcast target duration minutes": "30", "podcast generator audience": "expert" } )
    config = st.resolve_podcast_config( cfg, script_type="status_report" )
    assert ( config.target_duration_minutes, config.audience ) == ( 5, "general" )


def test_status_ini_keys_beat_the_profile_fallbacks():
    cfg = _Cfg( { "podcast status report target duration minutes": "7", "podcast status report min exchanges": "3",
                  "podcast status report max exchanges": "4", "podcast status report audience": "beginner" } )
    config = st.resolve_podcast_config( cfg, script_type="status_report" )
    assert ( config.target_duration_minutes, config.min_exchanges, config.max_exchanges, config.audience ) == ( 7, 3, 4, "beginner" )


def test_request_beats_profile_for_audience_and_review():
    config = st.resolve_podcast_config( _Cfg(), script_type="status_report", review="ask",
                                        audience="expert", audience_context="an SRE" )
    assert ( config.audience, config.audience_context, config.review ) == ( "expert", "an SRE", "ask" )
    config = st.resolve_podcast_config( _Cfg(), review="one_shot" )
    assert ( config.script_type, config.review ) == ( "research_critical", "one_shot" )


# --- saved scripts remember their type -------------------------------------------------------

def _script( script_type=None ):
    return PodcastScript( title="T", research_source="s", generated_at="2026-01-01T00:00:00", host_a_name="A", host_b_name="B",
                          segments=[ ScriptSegment( speaker="A", role="curious", text="Hi there", prosody=[] ) ],
                          script_type=script_type )


def test_to_markdown_omits_the_type_unless_asked():
    assert "Script Type" not in _script( "status_report" ).to_markdown()
    assert "Script Type" not in _script( None ).to_markdown( include_script_type=True )
    assert "## Script Type: status_report" in _script( "status_report" ).to_markdown( include_script_type=True )


def test_type_round_trips_through_the_saved_markdown():
    saved = _script( "status_report" ).to_markdown( include_script_type=True )
    assert PodcastScript.from_markdown( saved ).script_type == "status_report"
    assert PodcastScript.from_markdown( _script().to_markdown() ).script_type is None


def test_generated_script_carries_the_profile_type_and_saves_it( tmp_path ):
    config = PodcastConfig( script_type="status_report" )
    agent  = PodcastOrchestratorAgent( research_doc_path="/io/x.md", user_id="u@t.com", config=config, target_languages=[ "en" ] )
    agent._api_client = RecordingClient( { "analysis": _digest_json(), "script": json.dumps( { "title": "T", "segments": [
        { "speaker": "Maria", "role": "curious", "text": "Hi" } ] } ) } )

    async def _go():
        analysis = await agent._analyze_content_async( SOURCE_TEXT )
        return await agent._generate_script_async( SOURCE_TEXT, analysis )

    with patch( "cosa.agents.podcast_generator.orchestrator.voice_io.notify", new=AsyncMock() ):
        script = asyncio.run( _go() )
    assert script.script_type == "status_report"
    out = tmp_path / "s.md"
    agent.config.output_dir_template = str( tmp_path )
    with patch.object( PodcastConfig, "get_output_path", return_value=str( out ) ), \
         patch( "cosa.agents.podcast_generator.orchestrator.voice_io.notify", new=AsyncMock() ):
        asyncio.run( agent._save_script_async( script ) )
    assert "## Script Type: status_report" in out.read_text( encoding="utf-8" )


def test_revision_and_translation_keep_the_type():
    config = PodcastConfig( script_type="status_report" )
    agent  = PodcastOrchestratorAgent( research_doc_path="/io/x.md", user_id="u@t.com", config=config, target_languages=[ "en" ] )
    reply  = json.dumps( { "title": "T", "segments": [ { "speaker": "Maria", "role": "curious", "text": "Hola" } ] } )
    agent._api_client = RecordingClient( { "revision": reply, "translation": reply } )
    agent._podcast_state[ "revision_count" ] = 1

    async def _go():
        return ( await agent._revise_script_async( _script( "status_report" ), "shorter" ),
                 await agent._generate_translated_script_async( _script( "status_report" ), "es-MX" ) )

    with patch( "cosa.agents.podcast_generator.orchestrator.voice_io.notify", new=AsyncMock() ):
        revised, translated = asyncio.run( _go() )
    assert revised.script_type == "status_report" and translated.script_type == "status_report"


# --- step 2: the status digest ---------------------------------------------------------------

STATUS_DOC = """# Weekly status

- Cache layer rewritten and live
- Search index rebuilt
- Billing export shipped
- Migration script still to write
- Rollback test not yet run
- Waiting on vendor key for the sandbox
"""

DONE_LINES        = [ "- Cache layer rewritten and live", "- Search index rebuilt", "- Billing export shipped" ]
OUTSTANDING_LINES = [ "- Migration script still to write", "- Rollback test not yet run" ]


def _items( lines ):
    return [ { "text": line.lstrip( "- " ), "source_line": line } for line in lines ]


def _digest_json( **over ):
    body = { "main_topic": "Weekly status", "done": _items( DONE_LINES ), "outstanding": _items( OUTSTANDING_LINES ),
             "blocked": _items( [ "- Waiting on vendor key for the sandbox" ] ) }
    body.update( over )
    return json.dumps( body )


def _digest_agent( reply ):
    agent = PodcastOrchestratorAgent( research_doc_path="/io/x.md", user_id="u@t.com",
                                      config=PodcastConfig( script_type="status_report" ), target_languages=[ "en" ] )
    agent._api_client = RecordingClient( { "analysis": reply } )
    return agent


def test_digest_holds_every_known_item_and_each_source_line_is_in_the_document():
    agent = _digest_agent( _digest_json() )
    with patch( "cosa.agents.podcast_generator.orchestrator.voice_io.notify", new=AsyncMock() ):
        digest = asyncio.run( agent._analyze_content_async( STATUS_DOC ) )
    assert isinstance( digest, StatusDigest ) and digest.script_type == "status_report"
    assert len( digest.done ) == len( DONE_LINES ) and len( digest.outstanding ) == len( OUTSTANDING_LINES )
    assert len( digest.all_items() ) == 6
    assert [ i.source_line for i in digest.done ] == DONE_LINES
    assert all( item.source_line in STATUS_DOC for item in digest.all_items() )
    assert digest.unsupported_items( STATUS_DOC ) == []
    assert digest.key_subtopics == [ "Weekly status" ]
    sent = agent._api_client.calls[ "analysis" ]
    assert sent[ "system" ] == st.get_profile( "status_report" ).analysis_system_prompt
    assert STATUS_DOC in sent[ "user" ]


def test_unsupported_source_line_is_reported_and_logged( caplog ):
    reply = _digest_json( tricky=[ { "text": "made up", "source_line": "- never in the doc" } ] )
    agent = _digest_agent( reply )
    with patch( "cosa.agents.podcast_generator.orchestrator.voice_io.notify", new=AsyncMock() ), caplog.at_level( "WARNING" ):
        digest = asyncio.run( agent._analyze_content_async( STATUS_DOC ) )
    assert [ i.text for i in digest.unsupported_items( STATUS_DOC ) ] == [ "made up" ]
    assert "source line is not in the document" in caplog.text


@pytest.mark.parametrize( "reply", [ "no json here at all", json.dumps( { "main_topic": "x", "key_subtopics": [] } ),
                                     json.dumps( { "done": "not a list", "outstanding": [] } ) ] )
def test_a_failed_parse_raises( reply ):
    agent = _digest_agent( reply )
    with patch( "cosa.agents.podcast_generator.orchestrator.voice_io.notify", new=AsyncMock() ):
        with pytest.raises( PodcastGenerationError, match="analyzing the research document" ):
            asyncio.run( agent._analyze_content_async( STATUS_DOC ) )


def test_digest_requires_done_and_outstanding():
    with pytest.raises( ValidationError ):
        StatusDigest( main_topic="x" )
    digest = StatusDigest( done=[], outstanding=[ DigestItem( text="a", source_line="b" ) ] )
    assert digest.main_topic == "Status report" and len( digest.all_items() ) == 1


# --- status prompt builders: clipping and audience blocks ------------------------------------

def test_status_analysis_prompt_clips_and_adds_audience_blocks():
    from cosa.agents.podcast_generator.prompts.status_report import get_status_analysis_prompt
    text   = "x" * 50
    clip   = get_status_analysis_prompt( text, max_source_chars=10 )
    whole  = get_status_analysis_prompt( text, max_source_chars=100 )
    plain  = get_status_analysis_prompt( text )
    aud    = get_status_analysis_prompt( text, audience="expert", audience_context="an SRE on call" )
    assert "x" * 10 in clip and "x" * 11 not in clip
    assert "x" * 50 in whole and "x" * 50 in plain
    assert "**Additional Audience Context**: an SRE on call" in aud
    assert len( aud ) > len( plain )
    assert len( get_status_analysis_prompt( text, audience="not-a-level" ) ) == len( plain )
