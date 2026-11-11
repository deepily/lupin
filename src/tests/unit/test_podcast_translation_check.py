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
