#!/usr/bin/env python3
"""
Unit tests for the podcast one-shot path: no person is ever asked anything.

present_choices, ask_yes_no and get_input all raise if called. A one-shot run,
including a forced partial-audio failure, must pass. An ask run must reach the gate.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.podcast_generator import orchestrator as orch_mod
from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent, one_shot_notice
from cosa.agents.podcast_generator.state import ContentAnalysis, OrchestratorState, PodcastScript, ScriptSegment


class AskedAPerson( Exception ):
    """Raised by any voice_io call that would stop for a person."""


def _script( title="Cool" ):
    return PodcastScript( title=title, research_source="/io/r.md", host_a_name="A", host_b_name="B",
                          segments=[ ScriptSegment( speaker="A", role="curious", text="Hi there friend" ) ] )


def _result( ok=True ):
    return SimpleNamespace( success=ok, pcm_audio=b"\x00\x00" if ok else b"", error_message=None if ok else "boom", character_count=10 )


@pytest.fixture
def voice():
    with patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ) as notify, \
         patch.object( orch_mod.voice_io, "present_choices", new=AsyncMock( side_effect=AskedAPerson( "present_choices" ) ) ) as choices, \
         patch.object( orch_mod.voice_io, "ask_yes_no", new=AsyncMock( side_effect=AskedAPerson( "ask_yes_no" ) ) ) as yesno, \
         patch.object( orch_mod.voice_io, "get_input", new=AsyncMock( side_effect=AskedAPerson( "get_input" ) ) ) as getinput:
        yield SimpleNamespace( notify=notify, choices=choices, yesno=yesno, getinput=getinput )


def _agent( review, languages=None, partial=False ):
    config = PodcastConfig( script_type="status_report", review=review )
    agent  = PodcastOrchestratorAgent( research_doc_path="/proj/io/r.md", user_id="u@t.com", config=config,
                                       target_languages=languages or [ "en" ] )
    results = [ _result( True ), _result( not partial ) ]
    agent._load_research_async              = AsyncMock( return_value="research text" )
    agent._analyze_content_async            = AsyncMock( return_value=ContentAnalysis( main_topic="T" ) )
    agent._generate_script_async            = AsyncMock( return_value=_script() )
    agent._generate_translated_script_async = AsyncMock( return_value=_script( "Cool ES" ) )
    agent._save_script_async                = AsyncMock( side_effect=lambda s, is_revision=False, language="en": f"/proj/io/s-{language}.md" )

    async def _audio( scr, language="en" ):
        agent._podcast_state[ f"tts_results_{language}" ] = results
        return results, ( [ 1 ] if partial else [] )

    agent._generate_audio_async = AsyncMock( side_effect=_audio )
    agent._stitch_audio_async   = AsyncMock( side_effect=lambda tts, scr, language="en": f"/proj/io/a-{language}.mp3" )
    return agent


def _run_all( agent ):
    class _Audio:
        def __len__( self ): return 60000
    with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
         patch( "os.path.exists", return_value=True ), \
         patch( "pydub.AudioSegment.from_mp3", return_value=_Audio() ):
        return asyncio.run( agent.do_all_async() )


def _final_card( voice ):
    cards = [ c for c in voice.notify.await_args_list if "complete" in str( c.args[ 0 ] ).lower() and c.kwargs.get( "abstract" ) ]
    return cards[ -1 ].kwargs[ "abstract" ]


def test_one_shot_full_run_asks_nobody_and_discloses_it( voice ):
    agent  = _agent( "one_shot" )
    result = _run_all( agent )
    assert result is not None and agent.state == OrchestratorState.COMPLETED
    assert voice.choices.await_count == voice.yesno.await_count == voice.getinput.await_count == 0
    assert agent._podcast_state[ "script_one_shot" ] is True
    assert "generated in one shot and not reviewed" in _final_card( voice )


def test_one_shot_partial_audio_takes_the_unattended_default_without_asking( voice ):
    agent  = _agent( "one_shot", partial=True )
    result = _run_all( agent )
    assert result is not None and agent.state == OrchestratorState.COMPLETED
    assert voice.yesno.await_count == 0
    agent._stitch_audio_async.assert_awaited()


def test_one_shot_skips_every_translation_review_too( voice ):
    agent = _agent( "one_shot", languages=[ "en", "es-MX" ], partial=True )
    _run_all( agent )
    assert agent._generate_translated_script_async.await_count == 1
    assert voice.choices.await_count == voice.yesno.await_count == voice.getinput.await_count == 0
    assert agent._stitch_audio_async.await_count == 2


def test_ask_run_reaches_the_review_gate_and_the_trap_fires( voice ):
    agent = _agent( "ask" )
    with pytest.raises( Exception, match="present_choices" ):
        _run_all( agent )
    assert voice.choices.await_count == 1
    assert "script_one_shot" not in agent._podcast_state


def test_ask_run_asks_about_partial_audio_when_the_review_is_approved( voice ):
    voice.choices.side_effect = None
    voice.choices.return_value = { "answers": { "Script Review": "Approve script" } }
    agent = _agent( "ask", partial=True )
    with pytest.raises( Exception, match="ask_yes_no" ):
        _run_all( agent )
    assert voice.yesno.await_count == 1


def test_audio_only_one_shot_does_not_ask_about_partial_audio( voice ):
    agent = _agent( "one_shot", partial=True )
    agent._podcast_state[ "draft_script" ] = _script()
    agent._podcast_state[ "draft_script_path" ] = "/proj/io/s.md"
    agent._original_script_path = "/proj/io/s.md"
    with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), patch( "os.path.exists", return_value=True ):
        result = asyncio.run( agent.do_audio_only_async() )
    assert result is not None and voice.yesno.await_count == 0


def test_audio_only_ask_asks_about_partial_audio( voice ):
    agent = _agent( "ask", partial=True )
    agent._podcast_state[ "draft_script" ] = _script()
    agent._podcast_state[ "draft_script_path" ] = "/proj/io/s.md"
    agent._original_script_path = "/proj/io/s.md"
    with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), patch( "os.path.exists", return_value=True ):
        with pytest.raises( Exception, match="ask_yes_no" ):
            asyncio.run( agent.do_audio_only_async() )


def test_one_shot_with_review_only_is_refused( voice ):
    agent = _agent( "one_shot" )
    agent._podcast_state[ "draft_script" ] = _script()
    with pytest.raises( ValueError, match="review-only mode" ):
        asyncio.run( agent.do_review_only_async() )
    assert voice.choices.await_count == 0


def test_one_shot_notice_text():
    assert "not reviewed" in one_shot_notice( True )
    assert one_shot_notice( False ) == ""
