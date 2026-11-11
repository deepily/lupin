#!/usr/bin/env python3
"""
Unit tests for the Spanish translation check.

Two captured scripts drive it. Both were saved by real runs and are read back through the real
PodcastScript reader. One is a genuine es-MX script. The other is the English text that shipped
labelled es-MX on 4 Aug 2026. The model's answer is built from their segments and goes through
the real parse_script_response.
"""

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.podcast_generator import orchestrator as orch_mod
from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
from cosa.agents.podcast_generator.state import PodcastScript, ScriptSegment
from cosa.agents.podcast_generator.translation_check import spanish_stopword_ratio

FIXTURES  = Path( __file__ ).resolve().parent / "fixtures" / "podcast"
REAL_ES   = FIXTURES / "captured-real-es-mx-script-2026.01.23.md"
UNCHANGED = FIXTURES / "captured-english-unchanged-es-mx-script-2026.08.04.md"
INI       = Path( __file__ ).resolve().parents[ 2 ] / "conf" / "lupin-app.ini"


def _captured( path ):
    return PodcastScript.from_markdown( path.read_text() )


def _text( script ):
    return " ".join( seg.text for seg in script.segments )


def _english():
    return PodcastScript(
        title = "EN", research_source = "/io/r.md", host_a_name = "Maria", host_b_name = "Mr. Radio",
        segments = [ ScriptSegment( speaker="Maria", role="curious", text="So what changes everything here today", prosody=[] ) ],
        estimated_duration_minutes = 5.0, key_topics = [ "t" ],
    )


def _translate( answer_script, language="es-MX" ):
    """Run the real translation step with a model that answers with the given captured script."""
    agent = PodcastOrchestratorAgent( research_doc_path="/io/r.md", user_id="u@test.com", config=PodcastConfig() )
    answer = json.dumps( {
        "title"    : answer_script.title,
        "segments" : [ { "speaker": s.speaker, "role": s.role, "text": s.text, "prosody": [] } for s in answer_script.segments ],
    } )
    client = MagicMock()
    client.call_for_script = AsyncMock( return_value=MagicMock( content=answer ) )
    client.cost_estimate   = MagicMock()
    agent._api_client = client
    english = _english()
    with patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ) as notify, \
         patch.object( orch_mod, "validate_prosody_preservation", return_value=( True, {} ) ):
        translated = asyncio.run( agent._generate_translated_script_async( english, language ) )
    return english, translated, notify


def test_the_ratio_of_no_words_is_zero():
    assert spanish_stopword_ratio( "" ) == 0.0
    assert spanish_stopword_ratio( "123 !!!" ) == 0.0


def test_the_two_captured_scripts_sit_far_apart_around_the_threshold():
    threshold = PodcastConfig().min_spanish_stopword_ratio
    real      = spanish_stopword_ratio( _text( _captured( REAL_ES ) ) )
    english   = spanish_stopword_ratio( _text( _captured( UNCHANGED ) ) )
    assert len( _captured( REAL_ES ).segments ) > 20 and len( _captured( UNCHANGED ).segments ) > 20
    assert real > threshold > english
    assert real - english > 0.3


def test_the_ini_key_holds_the_threshold_between_the_two_measured_ratios():
    line  = re.search( r"^podcast translation min spanish stopword ratio\s*=\s*([0-9.]+)", INI.read_text(), re.M )
    value = float( line.group( 1 ) )
    assert spanish_stopword_ratio( _text( _captured( UNCHANGED ) ) ) < value < spanish_stopword_ratio( _text( _captured( REAL_ES ) ) )
    assert value == PodcastConfig().min_spanish_stopword_ratio


def test_a_real_spanish_translation_ships_as_es_mx():
    real                        = _captured( REAL_ES )
    english, translated, notify = _translate( real )
    assert "Translation Failed" not in translated.title
    assert translated.segments[ 0 ].text == real.segments[ 0 ].text
    notify.assert_not_awaited()


def test_english_returned_unchanged_is_marked_translation_failed_and_not_shipped_as_es_mx():
    unchanged                   = _captured( UNCHANGED )
    english, translated, notify = _translate( unchanged )
    assert "Translation Failed" in translated.title
    assert translated.segments == english.segments
    said = notify.await_args.args[ 0 ]
    assert "translation failed" in said and "untranslated" in said


def test_a_language_that_is_not_spanish_is_not_judged_by_spanish_words():
    english, translated, notify = _translate( _captured( UNCHANGED ), language="fr" )
    assert "Translation Failed" not in translated.title
    notify.assert_not_awaited()


def test_a_failed_translation_keeps_the_script_type_of_the_english_script():
    english = _english()
    english.script_type = "status_report"
    agent = PodcastOrchestratorAgent( research_doc_path="/io/r.md", user_id="u@test.com", config=PodcastConfig() )
    answer = json.dumps( { "title": "T", "segments": [ { "speaker": "Maria", "role": "curious", "text": "So what changes everything" } ] } )
    agent._api_client = MagicMock( call_for_script=AsyncMock( return_value=MagicMock( content=answer ) ), cost_estimate=MagicMock() )
    with patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ):
        translated = asyncio.run( agent._generate_translated_script_async( english, "es-MX" ) )
    assert "Translation Failed" in translated.title
    assert translated.script_type == "status_report"


def test_the_ratio_is_pinned_to_exact_values():
    assert spanish_stopword_ratio( "de la casa que no" ) == 0.8
    assert spanish_stopword_ratio( "De casa" ) == 0.5
    assert spanish_stopword_ratio( _text( _captured( UNCHANGED ) ) ) == pytest.approx( 0.050637, abs=1e-6 )
    assert spanish_stopword_ratio( _text( _captured( REAL_ES ) ) ) == pytest.approx( 0.395773, abs=1e-6 )


def _run_whole_job( model_answer ):
    """
    Run the whole job for English plus es-MX, with the real translation step.

    Everything around the translation is replaced by a recorder, so the test can say which
    languages were saved, voiced and listed. Returns the recorded calls and the final card text.
    """
    agent = PodcastOrchestratorAgent(
        research_doc_path="/io/r.md", user_id="u@test.com", target_languages=[ "en", "es-MX" ],
        config=PodcastConfig( review="one_shot" ) )
    english  = _english()
    answer   = json.dumps( {
        "title"    : model_answer.title,
        "segments" : [ { "speaker": s.speaker, "role": s.role, "text": s.text, "prosody": [] } for s in model_answer.segments ],
    } )
    saved, voiced, stitched = [], [], []

    async def save( script, is_revision=False, language="en" ):
        saved.append( language )
        return f"/io/script-{language}.md"

    async def voice( script, language="en" ):
        voiced.append( language )
        result = MagicMock( success=True, character_count=10 )
        return [ result ], []

    async def stitch( results, script, language="en" ):
        stitched.append( language )
        return f"/io/audio-{language}.mp3"

    agent._api_client = MagicMock( call_for_script=AsyncMock( return_value=MagicMock( content=answer ) ),
                                   cost_estimate=MagicMock( total_api_calls=1, total_input_tokens=1,
                                                            total_output_tokens=1, estimated_cost_usd=0.0 ) )
    agent._load_research_async              = AsyncMock( return_value="research text" )
    agent._analyze_content_async            = AsyncMock( return_value=MagicMock( main_topic="T" ) )
    agent._generate_script_async            = AsyncMock( return_value=english )
    agent._save_script_async                = save
    agent._generate_audio_async             = voice
    agent._stitch_audio_async               = stitch
    cards = AsyncMock()
    with patch.object( orch_mod.voice_io, "notify", new=cards ), \
         patch.object( orch_mod, "validate_prosody_preservation", return_value=( True, {} ) ), \
         patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
        asyncio.run( agent.do_all_async() )
    final = [ call.kwargs.get( "abstract" ) for call in cards.await_args_list if call.kwargs.get( "abstract" ) ][ -1 ]
    return agent, saved, voiced, stitched, final


def test_a_failed_translation_is_not_saved_voiced_or_listed_as_es_mx():
    agent, saved, voiced, stitched, card = _run_whole_job( _captured( UNCHANGED ) )
    assert saved == [ "en" ], "no script may be saved under the es-MX path"
    assert voiced == [ "en" ] and stitched == [ "en" ], "no es-MX audio may be made"
    assert set( agent._podcast_state[ "audio_paths_by_language" ] ) == { "en" }, "nothing es-MX reaches the upload"
    assert "**Mexican Spanish**: translation failed (not produced)" in card
    assert "Mexican Spanish Script" not in card and "Mexican Spanish MP3" not in card


def test_a_real_translation_is_saved_voiced_and_listed_as_es_mx():
    agent, saved, voiced, stitched, card = _run_whole_job( _captured( REAL_ES ) )
    assert saved == [ "en", "es-MX" ] and voiced == [ "en", "es-MX" ]
    assert "translation failed" not in card
    assert "Mexican Spanish" in card


async def _job_card( failed ):
    """Run the real job over a stub orchestrator; return the completion text and abstract."""
    from cosa.agents.podcast_generator.job import PodcastGeneratorJob
    job = PodcastGeneratorJob( research_path="io/deep-research/u/r.md", user_id="u", user_email="card@test.com",
                               session_id="s", target_languages=[ "en", "es-MX" ], debug=False )
    script = MagicMock( estimated_duration_minutes=3.5 )
    script.get_segment_count.return_value = 5
    agent = MagicMock( do_all_async=AsyncMock( return_value=script ), _api_client=None, _failed_translations=failed )
    agent._podcast_state = {
        "final_audio_path"          : "io/podcasts/u/en.mp3",
        "final_script_path"         : "io/podcasts/u/en.md",
        "audio_paths_by_language"   : { "en": "io/podcasts/u/en.mp3" },
        "script_paths_by_language"  : { "en": "io/podcasts/u/en.md" },
    }
    with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ) as notify, \
         patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
         patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
         patch( "cosa.agents.podcast_generator.cosa_interface" ), \
         patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", return_value=agent ), \
         patch( "os.path.exists", return_value=True ):
        await job._execute()
    call = next( c for c in notify.call_args_list if c.kwargs.get( "abstract" ) and "Podcast Activity Report" in c.kwargs[ "abstract" ] )
    return call.args[ 0 ], call.kwargs[ "abstract" ]


def test_the_job_card_names_a_language_whose_translation_failed():
    spoken, card = asyncio.run( _job_card( { "es-MX": "came back untranslated" } ) )
    assert "**Languages**: en\n" in card
    assert "**Translation failed (not produced)**: Mexican Spanish. came back untranslated" in card
    assert "en, es-MX" not in card
    assert "1 language" in spoken and "2 language" not in spoken


def test_the_job_card_lists_both_languages_when_nothing_failed():
    spoken, card = asyncio.run( _job_card( { } ) )
    assert "**Languages**: en, es-MX\n" in card
    assert "Translation failed" not in card
    assert "2 languages" in spoken


async def _research_card( failed ):
    """Run the research-to-podcast job over a stub pipeline; return its completion abstract."""
    from types import SimpleNamespace
    from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
    from cosa.agents.deep_research_to_podcast.state import PipelineState
    job = DeepResearchToPodcastJob( query="q", user_id="u", user_email="card@test.com", session_id="s",
                                    target_languages=[ "en", "es-MX" ] )
    io  = "/proj/io/podcasts/u/"
    result = SimpleNamespace(
        state=PipelineState.COMPLETED, error=None, research_path="io/deep-research/u/report.md", research_abstract="a",
        audio_path=io + "en.mp3", script_path=io + "en-script.md",
        pg_artifacts={ "audio_paths_by_language": { "en": io + "en.mp3" }, "script_paths_by_language": { "en": io + "en-script.md" },
                       "failed_translations": failed },
        dr_cost=1.0, pg_cost=1.0, total_cost=2.0, dr_artifacts={} )
    agent = MagicMock( run_async=AsyncMock( return_value=result ) )
    with patch( "cosa.agents.deep_research.voice_io.notify", new_callable=AsyncMock ) as notify, \
         patch( "cosa.agents.deep_research.voice_io.set_job_id" ), \
         patch( "cosa.agents.deep_research.voice_io.clear_job_id" ), \
         patch( "cosa.agents.deep_research.cosa_interface" ), \
         patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
         patch.object( type( job ), "_make_agent", return_value=agent ):
        await job._execute()
    return next( c.kwargs[ "abstract" ] for c in notify.call_args_list
                 if c.kwargs.get( "abstract" ) and "Research → Podcast Complete" in c.kwargs[ "abstract" ] )


def test_the_research_to_podcast_card_names_a_language_whose_translation_failed():
    card = asyncio.run( _research_card( { "es-MX": "came back untranslated" } ) )
    assert "**Translation failed (not produced)**: Mexican Spanish. came back untranslated" in card
    assert "**Mexican Spanish**:" not in card


def test_the_research_to_podcast_card_has_no_failure_line_when_nothing_failed():
    card = asyncio.run( _research_card( { } ) )
    assert "Translation failed" not in card


def test_the_chained_agent_carries_the_failed_translations_to_the_card():
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    agent = DeepResearchToPodcastAgent( query="q", user_email="u@t.com", target_languages=[ "en", "es-MX" ] )

    class _Orch:
        podcast_id = "pg-x"
        _api_client = None

        def __init__( self, **kw ):
            self._podcast_state     = { "final_audio_path": "a.mp3", "script_path": "s.md" }
            self._failed_translations = { "es-MX": "came back untranslated" }

        async def do_all_async( self ):
            return _english()

    with patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", _Orch ), \
         patch( "os.path.exists", return_value=True ), \
         patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ):
        out = asyncio.run( agent._run_podcast_generator( "/io/r.md" ) )
    assert out[ "artifacts" ][ "failed_translations" ] == { "es-MX": "came back untranslated" }
