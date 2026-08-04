#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.orchestrator

Target: PodcastOrchestratorAgent — the top-level, single-job, multi-phase async
state machine that drives podcast generation (load research → analyze → generate
script → review/revise loop → translate → audio → stitch).

Isolation contract (zero spend, zero I/O):
  - voice_io.{notify,present_choices,ask_yes_no,get_input} → AsyncMock
  - the lazy client properties (_api_client / _tts_client / _audio_stitcher) →
    MagicMock with AsyncMock methods; never the real LLM / ElevenLabs / pydub.
  - .prompts get_*/parse_* helpers → patched to deterministic stubs.
  - asyncio.to_thread + open / os.path.exists / os.makedirs / os.remove → patched
    so NO real filesystem access occurs.
  - pydub is injected as a fake module when the mp3-duration branch is exercised.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import os
import sys
import types
import asyncio
import builtins
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.podcast_generator import orchestrator as orch_mod
from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent, PodcastGenerationError
from cosa.agents.podcast_generator.state import (
    OrchestratorState,
    PodcastScript,
    ScriptSegment,
    ContentAnalysis,
)
from cosa.agents.podcast_generator.config import PodcastConfig


# ===========================================================================
# Helpers / fixtures
# ===========================================================================
def _run( coro ):
    return asyncio.run( coro )


def _segment( speaker="Nora", role="curious", text="Hello world here", prosody=None ):
    return ScriptSegment(
        speaker = speaker,
        role    = role,
        text    = text,
        prosody = prosody or [],
    )


def _script( title="Test Topic", segments=None, prosody_markers=None, **kw ):
    if segments is None:
        segments = [
            _segment( "Nora", "curious", "So what changes everything here today", prosody=prosody_markers or [] ),
            _segment( "Quentin", "expert", "Exactly the market is growing fast now" ),
        ]
    defaults = dict(
        title                      = title,
        research_source            = "/io/dr/report.md",
        host_a_name                = "Nora",
        host_b_name                = "Quentin",
        segments                   = segments,
        estimated_duration_minutes = 5.0,
        key_topics                 = [ "topic1", "topic2" ],
    )
    defaults.update( kw )
    return PodcastScript( **defaults )


def _agent( research_doc_path="/io/dr/report.md", user_id="u@test.com",
            target_languages=None, max_segments=None, debug=False, verbose=False,
            config=None ):
    return PodcastOrchestratorAgent(
        research_doc_path = research_doc_path,
        user_id           = user_id,
        config            = config or PodcastConfig(),
        max_segments      = max_segments,
        target_languages  = target_languages,
        debug             = debug,
        verbose           = verbose,
    )


class _TTSResult:
    """Lightweight stand-in for TTSSegmentResult."""
    def __init__( self, success=True, error_message=None, pcm_audio=b"\x00\x00",
                  character_count=10 ):
        self.success         = success
        self.error_message   = error_message
        self.pcm_audio       = pcm_audio if success else b""
        self.character_count = character_count


class _StitchResult:
    def __init__( self, success=True, output_path="/io/out/podcast.mp3",
                  error_message=None, total_duration_seconds=12.3, file_size_bytes=2048 ):
        self.success                = success
        self.output_path            = output_path
        self.error_message          = error_message
        self.total_duration_seconds = total_duration_seconds
        self.file_size_bytes        = file_size_bytes


def _mock_api_client():
    client = MagicMock()
    response = MagicMock()
    response.content = "RAW"
    client.call_for_analysis = AsyncMock( return_value=response )
    client.call_for_script   = AsyncMock( return_value=response )
    client.call_for_revision = AsyncMock( return_value=response )
    client.cost_estimate.total_api_calls     = 3
    client.cost_estimate.total_input_tokens  = 100
    client.cost_estimate.total_output_tokens = 200
    client.cost_estimate.estimated_cost_usd  = 0.05
    return client


@pytest.fixture( autouse=True )
def _silence_voice_io():
    """Mock all voice_io coroutines so no real notifications/prompts fire."""
    with patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ) as notify, \
         patch.object( orch_mod.voice_io, "present_choices", new=AsyncMock() ) as choices, \
         patch.object( orch_mod.voice_io, "ask_yes_no", new=AsyncMock( return_value=True ) ) as yesno, \
         patch.object( orch_mod.voice_io, "get_input", new=AsyncMock( return_value="" ) ) as getinput:
        yield {
            "notify"  : notify,
            "choices" : choices,
            "yesno"   : yesno,
            "input"   : getinput,
        }


# ===========================================================================
# __init__ / lazy props / from_saved_script  (EASY WINS)
# ===========================================================================
class TestInit:
    def test_defaults( self ):
        agent = _agent()
        assert agent.state == OrchestratorState.LOADING_RESEARCH
        assert agent.podcast_id.startswith( "podcast-" )
        assert agent.target_languages == [ "en" ]
        assert agent._api_client is None
        assert agent._tts_client is None
        assert agent._audio_stitcher is None
        assert agent._original_script_path is None
        assert agent.metrics[ "start_time" ] is None

    def test_target_languages_from_cli_arg( self ):
        assert _agent( target_languages=[ "es", "fr" ] ).target_languages == [ "es", "fr" ]

    def test_target_languages_from_config( self ):
        cfg = PodcastConfig()
        cfg.target_languages = [ "de" ]
        assert _agent( config=cfg ).target_languages == [ "de" ]

    def test_target_languages_default_when_config_empty( self ):
        cfg = PodcastConfig()
        cfg.target_languages = []
        assert _agent( config=cfg ).target_languages == [ "en" ]

    def test_debug_branch_prints( self, capsys ):
        _agent( debug=True )
        out = capsys.readouterr().out
        assert "Initialized for" in out
        assert "Podcast ID" in out


class TestLazyProps:
    def test_api_client_lazy_init( self ):
        agent = _agent()
        with patch.object( orch_mod, "PodcastAPIClient" ) as PAC:
            client = agent.api_client
            assert client is PAC.return_value
            # second access returns cached instance (no second construction)
            assert agent.api_client is client
            PAC.assert_called_once()

    def test_tts_client_lazy_init( self ):
        agent = _agent()
        with patch.object( orch_mod, "PodcastTTSClient" ) as PTC:
            client = agent.tts_client
            assert client is PTC.return_value
            assert agent.tts_client is client
            PTC.assert_called_once()

    def test_audio_stitcher_lazy_init( self ):
        agent = _agent()
        with patch.object( orch_mod, "PodcastAudioStitcher" ) as PAS:
            stitcher = agent.audio_stitcher
            assert stitcher is PAS.return_value
            assert agent.audio_stitcher is stitcher
            PAS.assert_called_once()


class TestFromSavedScript:
    def _markdown( self ):
        return (
            "# Podcast: Saved Topic\n"
            "## Generated: 2026-01-19T10:30:00\n"
            "## Hosts: Nora, Quentin\n"
            "## Estimated Duration: 5.0 minutes\n"
            "## Revision: 2\n\n---\n\n"
            "**[Nora - Curious]**: Hello there everyone today\n\n"
            "**[Quentin - Expert]**: Indeed it is quite so\n"
        )

    def test_from_saved_script_absolute_path( self ):
        m = MagicMock()
        m.read.return_value = self._markdown()
        fake_open = MagicMock()
        fake_open.return_value.__enter__.return_value = m
        with patch.object( builtins, "open", fake_open ):
            agent = _run( PodcastOrchestratorAgent.from_saved_script(
                script_path = "/io/dr/saved.md",
                user_id     = "u@test.com",
            ) )
        assert agent.state == OrchestratorState.WAITING_SCRIPT_REVIEW
        assert agent._original_script_path == "/io/dr/saved.md"
        assert agent._podcast_state[ "draft_script_path" ] == "/io/dr/saved.md"
        assert agent._podcast_state[ "revision_count" ] == 2
        assert agent._podcast_state[ "draft_script" ].title == "Saved Topic"

    def test_from_saved_script_relative_path_and_debug( self, capsys ):
        m = MagicMock()
        m.read.return_value = self._markdown()
        fake_open = MagicMock()
        fake_open.return_value.__enter__.return_value = m
        with patch.object( builtins, "open", fake_open ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            agent = _run( PodcastOrchestratorAgent.from_saved_script(
                script_path = "io/dr/saved.md",
                user_id     = "u@test.com",
                debug       = True,
            ) )
        # relative path resolved against project root
        assert agent._original_script_path == "/proj/io/dr/saved.md"
        out = capsys.readouterr().out
        assert "Loaded script from" in out
        assert "Title" in out


# ===========================================================================
# get_state / _calculate_progress / control methods  (EASY WINS)
# ===========================================================================
class TestStateQueries:
    def test_get_state_shape( self ):
        agent = _agent()
        state = agent.get_state()
        assert state[ "state" ] == "loading_research"
        assert state[ "progress_pct" ] == 10
        assert state[ "podcast_id" ] == agent.podcast_id
        assert state[ "research_doc" ] == agent.research_doc_path
        assert state[ "revision_count" ] == 0
        assert state[ "script_approved" ] is False
        assert "metrics" in state

    @pytest.mark.parametrize( "st,pct", [
        ( OrchestratorState.LOADING_RESEARCH, 10 ),
        ( OrchestratorState.ANALYZING_CONTENT, 30 ),
        ( OrchestratorState.GENERATING_SCRIPT, 60 ),
        ( OrchestratorState.WAITING_SCRIPT_REVIEW, 80 ),
        ( OrchestratorState.GENERATING_AUDIO, 85 ),
        ( OrchestratorState.STITCHING_AUDIO, 95 ),
        ( OrchestratorState.COMPLETED, 100 ),
        ( OrchestratorState.FAILED, 0 ),
        ( OrchestratorState.PAUSED, 0 ),
        ( OrchestratorState.STOPPED, 0 ),
    ] )
    def test_calculate_progress_all_states( self, st, pct ):
        agent = _agent()
        agent.state = st
        assert agent._calculate_progress() == pct


class TestControlMethods:
    def test_pause( self ):
        agent = _agent()
        assert _run( agent.pause() ) is True
        assert agent._pause_requested is True

    def test_resume_when_paused( self ):
        agent = _agent()
        agent.state = OrchestratorState.PAUSED
        agent._pause_requested = True
        assert _run( agent.resume() ) is True
        assert agent._pause_requested is False

    def test_resume_when_not_paused( self ):
        agent = _agent()
        assert _run( agent.resume() ) is False

    def test_stop_returns_partial( self ):
        agent = _agent()
        agent._podcast_state[ "draft_script" ]     = _script()
        agent._podcast_state[ "content_analysis" ] = ContentAnalysis( main_topic="X" )
        result = _run( agent.stop() )
        assert agent._stop_requested is True
        assert agent.state == OrchestratorState.STOPPED
        assert result[ "stopped_at" ] == "stopped"
        assert result[ "partial_script" ] is not None
        assert result[ "analysis" ] is not None

    def test_check_stop( self ):
        agent = _agent()
        assert agent._check_stop() is False
        agent._stop_requested = True
        assert agent._check_stop() is True

    def test_handle_stop( self, _silence_voice_io ):
        agent = _agent()
        result = _run( agent._handle_stop() )
        assert result is None
        assert agent.state == OrchestratorState.STOPPED
        _silence_voice_io[ "notify" ].assert_awaited()


# ===========================================================================
# _get_script_preview  (EASY WIN)
# ===========================================================================
class TestScriptPreview:
    def test_preview_three_or_more_segments( self ):
        agent = _agent()
        script = _script( segments=[
            _segment( "Nora", "curious", "one two three" ),
            _segment( "Quentin", "expert", "four five six" ),
            _segment( "Nora", "curious", "seven eight nine" ),
            _segment( "Quentin", "expert", "ten eleven twelve" ),
        ] )
        preview = agent._get_script_preview( script )
        assert "Script Preview: Test Topic" in preview
        assert "**Segments**: 4" in preview
        assert "Nora" in preview and "Quentin" in preview

    def test_preview_fewer_than_three_segments( self ):
        agent = _agent()
        script = _script( segments=[ _segment( "Nora", "curious", "only one segment here" ) ] )
        preview = agent._get_script_preview( script )
        assert "**Segments**: 1" in preview


# ===========================================================================
# _audio_progress_callback / _audio_retry_callback  (EASY WINS)
# ===========================================================================
class TestAudioCallbacks:
    def test_progress_callback_new_milestone_with_eta( self, _silence_voice_io ):
        agent = _agent()
        agent._reported_milestones = set()
        agent._audio_progress_group_id = "pg-abc"
        _run( agent._audio_progress_callback( current=5, total=10, speaker="Nora", eta_seconds=42.0 ) )
        assert 50 in agent._reported_milestones
        _silence_voice_io[ "notify" ].assert_awaited()
        # the eta string is included
        kwargs = _silence_voice_io[ "notify" ].await_args.args
        assert "50%" in kwargs[ 0 ]
        assert "remaining" in kwargs[ 0 ]

    def test_progress_callback_no_eta( self, _silence_voice_io ):
        agent = _agent()
        agent._reported_milestones = set()
        agent._audio_progress_group_id = "pg-abc"
        _run( agent._audio_progress_callback( current=3, total=10, speaker="Nora", eta_seconds=0.0 ) )
        msg = _silence_voice_io[ "notify" ].await_args.args[ 0 ]
        assert "30%" in msg
        assert "remaining" not in msg

    def test_progress_callback_already_reported_milestone( self, _silence_voice_io ):
        agent = _agent()
        agent._reported_milestones = { 50 }
        agent._audio_progress_group_id = "pg-abc"
        _run( agent._audio_progress_callback( current=5, total=10, speaker="Nora" ) )
        _silence_voice_io[ "notify" ].assert_not_awaited()

    def test_progress_callback_zero_milestone_skipped( self, _silence_voice_io ):
        agent = _agent()
        agent._reported_milestones = set()
        agent._audio_progress_group_id = "pg-abc"
        # current=0 → pct 0 → milestone 0 → skipped (milestone > 0 guard)
        _run( agent._audio_progress_callback( current=0, total=10, speaker="Nora" ) )
        _silence_voice_io[ "notify" ].assert_not_awaited()

    def test_retry_callback( self, _silence_voice_io ):
        agent = _agent()
        _run( agent._audio_retry_callback( segment_index=2, attempt=2, max_attempts=3, speaker="Quentin" ) )
        msg = _silence_voice_io[ "notify" ].await_args.args[ 0 ]
        assert "Segment 3" in msg
        assert "Quentin" in msg


# ===========================================================================
# _load_research_async  (MID)
# ===========================================================================
class TestLoadResearch:
    def test_load_absolute_path_success_debug( self, capsys ):
        agent = _agent( research_doc_path="/io/dr/report.md", debug=True )
        fh = MagicMock()
        fh.read.return_value = "RESEARCH CONTENT"
        fake_open = MagicMock()
        fake_open.return_value.__enter__.return_value = fh
        with patch( "os.path.exists", return_value=True ), \
             patch.object( builtins, "open", fake_open ):
            content = _run( agent._load_research_async() )
        assert content == "RESEARCH CONTENT"
        assert "Loaded research doc" in capsys.readouterr().out

    def test_load_relative_path_uses_project_root( self ):
        agent = _agent( research_doc_path="io/dr/report.md" )
        fh = MagicMock()
        fh.read.return_value = "CONTENT"
        fake_open = MagicMock()
        fake_open.return_value.__enter__.return_value = fh
        captured = {}
        real_exists = os.path.exists
        def fake_exists( p ):
            captured[ "path" ] = p
            return True
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", side_effect=fake_exists ), \
             patch.object( builtins, "open", fake_open ):
            content = _run( agent._load_research_async() )
        assert content == "CONTENT"
        assert captured[ "path" ] == "/proj/io/dr/report.md"

    def test_load_file_not_found_returns_none( self ):
        agent = _agent( research_doc_path="/io/dr/missing.md" )
        with patch( "os.path.exists", return_value=False ):
            assert _run( agent._load_research_async() ) is None

    def test_load_exception_returns_none( self ):
        agent = _agent( research_doc_path="/io/dr/report.md" )
        with patch( "os.path.exists", return_value=True ), \
             patch.object( builtins, "open", side_effect=OSError( "boom" ) ):
            assert _run( agent._load_research_async() ) is None


# ===========================================================================
# _analyze_content_async  (MID)
# ===========================================================================
class TestAnalyzeContent:
    def test_analyze_happy_path( self ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        result_dict = {
            "main_topic"                 : "Quantum",
            "key_subtopics"              : [ "qubits" ],
            "interesting_facts"          : [ "fast" ],
            "discussion_questions"       : [ "why?" ],
            "analogies_suggested"        : [ "like coins" ],
            "target_audience"            : "experts",
            "complexity_level"           : "advanced",
            "estimated_coverage_minutes" : 12.0,
        }
        with patch.object( orch_mod, "get_content_analysis_prompt", return_value="P" ), \
             patch.object( orch_mod, "parse_analysis_response", return_value=result_dict ):
            analysis = _run( agent._analyze_content_async( "research text" ) )
        assert analysis.main_topic == "Quantum"
        assert analysis.inferred_audience == "experts"
        assert analysis.complexity_level == "advanced"
        assert agent.metrics[ "api_calls" ] == 1

    def test_analyze_refuses_rather_than_forging_an_analysis( self, capsys ):
        """
        A failed analysis must RAISE, not return a plausible-looking stand-in.

        Replaces test_analyze_exception_returns_minimal, which asserted the old
        behaviour: an exception yielded a minimal ContentAnalysis whose shape was
        indistinguishable from a real one, so a caller could not tell an invented
        result from a genuine one. That forgery was deliberately removed — see
        src/rnd/v0.1.9/2026.08.01-a-fallback-that-forges-an-answer.md. Restoring it
        to make this file green would silently undo the campaign (row a0ceb502).
        """
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_analysis = AsyncMock( side_effect=RuntimeError( "api down" ) )

        with patch.object( orch_mod, "get_content_analysis_prompt", return_value="P" ):
            with pytest.raises( PodcastGenerationError ) as excinfo:
                _run( agent._analyze_content_async( "research text" ) )

        # The original cause is chained, so the real error is not swallowed.
        assert isinstance( excinfo.value.__cause__, RuntimeError )
        assert "analyzing the research document" in str( excinfo.value )
        assert "Analysis error" in capsys.readouterr().out


# ===========================================================================
# _generate_script_async  (MID)
# ===========================================================================
class TestGenerateScript:
    def test_generate_happy_path( self ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        analysis = ContentAnalysis( main_topic="Quantum", key_subtopics=[ "a" ] )
        parsed = {
            "title"    : "My Podcast",
            "segments" : [
                { "speaker": "Nora", "role": "curious", "text": "hi", "prosody": [ "pause" ] },
                { "speaker": "Quentin", "role": "expert", "text": "yo" },
            ],
            "estimated_duration_minutes" : 9.0,
            "key_topics" : [ "x" ],
        }
        with patch.object( orch_mod, "get_dynamic_duo_description", return_value="DUO" ), \
             patch.object( orch_mod, "get_script_generation_prompt", return_value="P" ), \
             patch.object( orch_mod, "parse_script_response", return_value=parsed ):
            script = _run( agent._generate_script_async( "research", analysis ) )
        assert script.title == "My Podcast"
        assert script.get_segment_count() == 2
        assert agent.metrics[ "api_calls" ] == 1

    def test_generate_refuses_rather_than_forging_a_script( self, capsys ):
        """
        A failed script generation must RAISE, not return an empty stand-in.

        Replaces test_generate_exception_returns_minimal. The old behaviour handed
        back a 0-segment PodcastScript that reached the review gate looking like a
        normal — if empty — review-ready result. Raising is the fix; see the
        orchestrator's own comment at the raise site.
        """
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_script = AsyncMock( side_effect=RuntimeError( "boom" ) )
        analysis = ContentAnalysis( main_topic="Quantum" )

        with patch.object( orch_mod, "get_dynamic_duo_description", return_value="DUO" ), \
             patch.object( orch_mod, "get_script_generation_prompt", return_value="P" ):
            with pytest.raises( PodcastGenerationError ) as excinfo:
                _run( agent._generate_script_async( "research", analysis ) )

        assert isinstance( excinfo.value.__cause__, RuntimeError )
        assert "writing the podcast script" in str( excinfo.value )
        assert "Script generation error" in capsys.readouterr().out


# ===========================================================================
# _revise_script_async  (MID)
# ===========================================================================
class TestReviseScript:
    def test_revise_happy_path( self ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        current = _script( title="Original" )
        parsed = {
            "title"    : "Revised",
            "segments" : [ { "speaker": "Nora", "role": "curious", "text": "new line" } ],
            "estimated_duration_minutes" : 7.0,
            "key_topics" : [ "y" ],
        }
        with patch.object( orch_mod, "get_script_revision_prompt", return_value="P" ), \
             patch.object( orch_mod, "parse_script_response", return_value=parsed ):
            revised = _run( agent._revise_script_async( current, "make it punchy" ) )
        assert revised.title == "Revised"
        assert revised.revision_count == current.revision_count + 1
        assert revised.segments[ 0 ].text == "new line"

    def test_revise_empty_segments_fails_loud( self, _silence_voice_io ):
        """
        A revision that parses to zero segments must FAIL LOUD, not silently
        hand back the previous script as if it had been revised.

        Regression 0913bb90: the old `segments if segments else current_script.segments`
        substitution let an empty parse masquerade as a successful revision. Now the
        empty case raises into the except branch, which notifies the user and returns
        the current script UNCHANGED (same object, revision_count not incremented).
        """
        agent = _agent()
        agent._api_client = _mock_api_client()
        current = _script( title="Original" )
        parsed = { "segments": [] }  # zero segments → must NOT masquerade as a revision
        with patch.object( orch_mod, "get_script_revision_prompt", return_value="P" ), \
             patch.object( orch_mod, "parse_script_response", return_value=parsed ):
            revised = _run( agent._revise_script_async( current, "fb" ) )
        assert revised is current
        _silence_voice_io[ "notify" ].assert_awaited()

    def test_revise_exception_returns_original( self ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_revision = AsyncMock( side_effect=RuntimeError( "x" ) )
        current = _script( title="Original" )
        with patch.object( orch_mod, "get_script_revision_prompt", return_value="P" ):
            revised = _run( agent._revise_script_async( current, "fb" ) )
        assert revised is current


# ===========================================================================
# _save_script_async  (MID) — 4 path branches + exception
# ===========================================================================
class TestSaveScript:
    def _patch_fs( self ):
        return patch.multiple( "os", makedirs=MagicMock(), path=os.path ), \
               patch.object( builtins, "open", MagicMock() )

    def test_save_first_time_generates_path_and_stores( self ):
        agent = _agent()
        script = _script( title="Podcast: Cool Topic" )
        with patch( "os.makedirs" ), patch.object( builtins, "open", MagicMock() ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            path = _run( agent._save_script_async( script ) )
        assert path.endswith( ".md" )
        # English first save stores _original_script_path
        assert agent._original_script_path == path

    def test_save_revision_versioned_path( self ):
        agent = _agent()
        agent._original_script_path = "/proj/io/name-script.md"
        agent._podcast_state[ "revision_count" ] = 3
        script = _script()
        with patch( "os.makedirs" ), patch.object( builtins, "open", MagicMock() ):
            path = _run( agent._save_script_async( script, is_revision=True ) )
        assert path == "/proj/io/name-script-v3.md"

    def test_save_approval_uses_original_path( self ):
        agent = _agent()
        agent._original_script_path = "/proj/io/name-script.md"
        script = _script()
        with patch( "os.makedirs" ), patch.object( builtins, "open", MagicMock() ):
            path = _run( agent._save_script_async( script, is_revision=False ) )
        assert path == "/proj/io/name-script.md"

    def test_save_non_english_language_path( self ):
        agent = _agent()
        script = _script( title="Podcast: Cool Topic (Spanish)" )
        with patch( "os.makedirs" ), patch.object( builtins, "open", MagicMock() ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            path = _run( agent._save_script_async( script, language="es-MX" ) )
        assert "-es-MX.md" in path
        # non-english save does NOT set _original_script_path
        assert agent._original_script_path is None

    def test_save_debug_print( self, capsys ):
        agent = _agent( debug=True )
        script = _script( title="Podcast: T" )
        with patch( "os.makedirs" ), patch.object( builtins, "open", MagicMock() ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( agent._save_script_async( script ) )
        assert "Script saved to" in capsys.readouterr().out

    def test_save_exception_raises( self ):
        agent = _agent()
        script = _script( title="Podcast: T" )
        with patch( "os.makedirs", side_effect=OSError( "disk full" ) ), \
             patch.object( builtins, "open", MagicMock() ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( OSError ):
                _run( agent._save_script_async( script ) )


# ===========================================================================
# _delete_draft_script  (MID)
# ===========================================================================
class TestDeleteDraft:
    def test_delete_existing_file_debug( self, capsys ):
        agent = _agent( debug=True )
        with patch( "os.path.exists", return_value=True ), patch( "os.remove" ) as rm:
            _run( agent._delete_draft_script( "/io/draft.md" ) )
        rm.assert_called_once_with( "/io/draft.md" )
        assert "Draft script deleted" in capsys.readouterr().out

    def test_delete_missing_file_noop( self ):
        agent = _agent( debug=True )
        with patch( "os.path.exists", return_value=False ), patch( "os.remove" ) as rm:
            _run( agent._delete_draft_script( "/io/draft.md" ) )
        rm.assert_not_called()

    def test_delete_exception_is_swallowed( self ):
        agent = _agent()
        with patch( "os.path.exists", side_effect=OSError( "x" ) ):
            # should not raise
            _run( agent._delete_draft_script( "/io/draft.md" ) )


# ===========================================================================
# _generate_translated_script_async  (MID)
# ===========================================================================
class TestGenerateTranslated:
    def test_translated_happy_prosody_preserved( self, capsys ):
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        english = _script( title="EN", prosody_markers=[ "pause" ] )
        parsed = {
            "title"    : "ES",
            "segments" : [ { "speaker": "Nora", "role": "curious", "text": "hola", "prosody": [ "pause" ] } ],
            "key_topics" : [ "z" ],
            "estimated_duration_minutes" : 6.0,
        }
        with patch.object( orch_mod, "parse_script_response", return_value=parsed ), \
             patch.object( orch_mod, "validate_prosody_preservation",
                           return_value=( True, { "english_count": 1, "translated_count": 1, "missing": [], "extra": [] } ) ):
            translated = _run( agent._generate_translated_script_async( english, "es-MX" ) )
        assert translated.title == "ES"
        assert translated.revision_count == 0
        assert "Generating Mexican Spanish" in capsys.readouterr().out

    def test_translated_prosody_not_preserved_warns( self, _silence_voice_io ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        english = _script( title="EN", prosody_markers=[ "pause" ] )
        parsed = {
            "title"    : "ES",
            "segments" : [ { "speaker": "Nora", "role": "curious", "text": "hola" } ],
        }
        with patch.object( orch_mod, "parse_script_response", return_value=parsed ), \
             patch.object( orch_mod, "validate_prosody_preservation",
                           return_value=( False, { "english_count": 1, "translated_count": 0, "missing": [ "pause" ], "extra": [] } ) ):
            translated = _run( agent._generate_translated_script_async( english, "es-MX" ) )
        assert translated.title == "ES"
        _silence_voice_io[ "notify" ].assert_awaited()

    def test_translated_empty_segments_fails_loud( self, _silence_voice_io ):
        """
        A translation that parses to zero segments must FAIL LOUD, not silently
        ship the English text under a normal-looking title.

        Regression 0913bb90 (Rick's live find): the old
        `segments if segments else english_script.segments` substitution produced an
        English-body file titled "Untitled Podcast" that reached the approval gate
        looking like a Spanish script. Now the empty case raises into the except
        branch, which notifies the user and marks the title "Translation Failed".
        """
        agent = _agent()
        agent._api_client = _mock_api_client()
        english = _script( title="EN" )
        parsed = { "segments": [] }  # zero segments → must NOT silently pass through as English
        with patch.object( orch_mod, "parse_script_response", return_value=parsed ):
            translated = _run( agent._generate_translated_script_async( english, "es-MX" ) )
        assert "Translation Failed" in translated.title
        assert translated.segments == english.segments
        _silence_voice_io[ "notify" ].assert_awaited()

    def test_translated_exception_returns_fallback( self, capsys ):
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_script = AsyncMock( side_effect=RuntimeError( "boom" ) )
        english = _script( title="EN" )
        translated = _run( agent._generate_translated_script_async( english, "es-MX" ) )
        assert "Translation Failed" in translated.title
        assert translated.segments == english.segments
        assert "Translation error" in capsys.readouterr().out


# ===========================================================================
# _generate_audio_async  (MID)
# ===========================================================================
class TestGenerateAudio:
    def test_audio_happy_no_failures( self ):
        agent = _agent()
        results = [ _TTSResult( success=True ), _TTSResult( success=True ) ]
        agent._tts_client = MagicMock()
        agent._tts_client.generate_all_segments = AsyncMock( return_value=( results, [] ) )
        script = _script()
        out_results, failed = _run( agent._generate_audio_async( script, language="en" ) )
        assert out_results == results
        assert failed == []
        assert agent._podcast_state[ "tts_results_en" ] == results

    def test_audio_with_failures_prints( self, capsys ):
        agent = _agent( debug=True )
        results = [ _TTSResult( success=True ), _TTSResult( success=False, error_message="429 rate limit" ) ]
        agent._tts_client = MagicMock()
        agent._tts_client.generate_all_segments = AsyncMock( return_value=( results, [ 1 ] ) )
        script = _script()
        out_results, failed = _run( agent._generate_audio_async( script ) )
        assert failed == [ 1 ]
        out = capsys.readouterr().out
        assert "Audio failures" in out
        assert "429 rate limit" in out

    def test_audio_max_segments_limit_debug( self, capsys ):
        agent = _agent( max_segments=1, debug=True )
        results = [ _TTSResult( success=True ) ]
        agent._tts_client = MagicMock()
        agent._tts_client.generate_all_segments = AsyncMock( return_value=( results, [] ) )
        script = _script( segments=[
            _segment( "Nora", "curious", "a b c" ),
            _segment( "Quentin", "expert", "d e f" ),
            _segment( "Nora", "curious", "g h i" ),
        ] )
        _run( agent._generate_audio_async( script ) )
        out = capsys.readouterr().out
        assert "Limiting segments" in out
        # tts client was called with a 1-segment script
        called_script = agent._tts_client.generate_all_segments.await_args.kwargs[ "script" ]
        assert called_script.get_segment_count() == 1


# ===========================================================================
# _stitch_audio_async  (MID)
# ===========================================================================
class TestStitchAudio:
    def test_stitch_success_debug( self, capsys ):
        agent = _agent( debug=True )
        agent._audio_stitcher = MagicMock()
        agent._audio_stitcher.stitch_segments = MagicMock(
            return_value=_StitchResult( success=True, output_path="/io/out/p.mp3" )
        )
        results = [ _TTSResult( success=True ) ]
        script = _script( title="Podcast: Cool" )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            path = _run( agent._stitch_audio_async( results, script, language="en" ) )
        assert path == "/io/out/p.mp3"
        out = capsys.readouterr().out
        assert "Stitching" in out
        assert "Audio stitched" in out

    def test_stitch_failure_raises( self ):
        agent = _agent()
        agent._audio_stitcher = MagicMock()
        agent._audio_stitcher.stitch_segments = MagicMock(
            return_value=_StitchResult( success=False, error_message="ffmpeg missing" )
        )
        results = [ _TTSResult( success=True ) ]
        script = _script( title="Podcast: Cool" )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( RuntimeError, match="ffmpeg missing" ):
                _run( agent._stitch_audio_async( results, script ) )

    def test_stitch_non_english_language_path( self ):
        agent = _agent()
        captured = {}
        def fake_stitch( tts, out ):
            captured[ "out" ] = out
            return _StitchResult( success=True, output_path=out )
        agent._audio_stitcher = MagicMock()
        agent._audio_stitcher.stitch_segments = MagicMock( side_effect=fake_stitch )
        results = [ _TTSResult( success=True ) ]
        script = _script( title="Podcast: Cool (Spanish)" )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( agent._stitch_audio_async( results, script, language="es-MX" ) )
        assert "-es-MX.mp3" in captured[ "out" ]


# ===========================================================================
# THORNY sub-batch 1 — do_all_async
# ===========================================================================
class _FakeAudio:
    def __init__( self, ms ): self._ms = ms
    def __len__( self ): return self._ms


def _wire_pipeline( agent, *, analysis=None, script=None, translated=None,
                    save_path="/proj/io/script.md", audio_results=None, failed=None,
                    audio_path="/proj/io/audio.mp3" ):
    """Mock every private async helper so do_*_async runs without real work."""
    agent._api_client = _mock_api_client()
    agent._load_research_async = AsyncMock( return_value="research text" )
    agent._analyze_content_async = AsyncMock(
        return_value=analysis or ContentAnalysis( main_topic="Topic", key_subtopics=[ "s" ] ) )
    base_script = script or _script( title="Cool" )
    agent._generate_script_async = AsyncMock( return_value=base_script )
    agent._revise_script_async   = AsyncMock( return_value=base_script )
    agent._generate_translated_script_async = AsyncMock( return_value=translated or _script( title="Cool ES" ) )

    if callable( save_path ):
        agent._save_script_async = AsyncMock( side_effect=save_path )
    else:
        agent._save_script_async = AsyncMock( return_value=save_path )

    results = audio_results if audio_results is not None else [ _TTSResult( success=True, character_count=100 ) ]
    fails   = failed if failed is not None else []
    async def _gen_audio( scr, language="en" ):
        agent._podcast_state[ f"tts_results_{language}" ] = results
        return results, fails
    agent._generate_audio_async = AsyncMock( side_effect=_gen_audio )

    if callable( audio_path ):
        agent._stitch_audio_async = AsyncMock( side_effect=audio_path )
    else:
        agent._stitch_audio_async = AsyncMock( return_value=audio_path )
    return base_script


class TestDoAllAsync:
    def test_full_happy_multilang_pydub_success( self, _silence_voice_io, capsys ):
        agent = _agent( target_languages=[ "en", "es-MX" ],
                        research_doc_path="/proj/io/dr/report.md", debug=True )
        async def save( s, is_revision=False, language="en" ):
            return f"/proj/io/script-{language}.md"
        async def stitch( tts, scr, language="en" ):
            return f"/proj/io/audio-{language}.mp3"
        base = _wire_pipeline( agent, save_path=save, audio_path=stitch )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Approve script" } },
        ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=True ), \
             patch( "pydub.AudioSegment.from_mp3", return_value=_FakeAudio( 60000 ) ):
            result = _run( agent.do_all_async() )
        assert result is base
        assert agent.state == OrchestratorState.COMPLETED
        assert agent._podcast_state[ "script_approved" ] is True
        out = capsys.readouterr().out
        assert "Analysis complete" in out
        assert "Script generated" in out

    def test_cancel_at_first_review( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Cancel" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent.do_all_async() )
        assert result is None
        assert agent.state == OrchestratorState.STOPPED

    def test_zero_segment_script_floored_before_review_gate( self, _silence_voice_io ):
        # P0 4317efd1 floor: a parsed-but-empty (0-segment) script must be rejected
        # BEFORE the human approval gate. Proving the raise alone is not enough —
        # the whole point is that the approval surface is NEVER invoked, so we also
        # assert present_choices was never awaited.
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent, script=_script( title="Untitled Podcast", segments=[] ) )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( PodcastGenerationError, match="zero segments" ):
                _run( agent.do_all_async() )
        _silence_voice_io[ "choices" ].assert_not_called()   # never reached the gate
        assert agent.state == OrchestratorState.FAILED

    def test_revise_empty_then_custom_then_approve( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        # 1) Revise w/ empty feedback (loops), 2) "Other" custom text feedback, 3) Approve
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Revise script" } },
            { "answers": { "Script Review": "Make it shorter" } },   # custom "Other"
            { "answers": { "Script Review": "Approve script" } },
        ]
        _silence_voice_io[ "input" ].return_value = ""   # empty feedback first revise
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            result = _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.COMPLETED
        assert agent._podcast_state[ "revision_count" ] == 1   # only the custom-text revise counted

    def test_revise_with_feedback_then_approve( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Revise script" } },
            { "answers": { "Script Review": "Approve script" } },
        ]
        _silence_voice_io[ "input" ].return_value = "punch it up"
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            _run( agent.do_all_async() )
        assert agent._podcast_state[ "revision_count" ] == 1
        agent._revise_script_async.assert_awaited()

    def test_stop_requested_after_load( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        async def load_and_stop():
            agent._stop_requested = True
            return "research"
        agent._load_research_async = AsyncMock( side_effect=load_and_stop )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent.do_all_async() )
        assert result is None
        assert agent.state == OrchestratorState.STOPPED

    def test_load_returns_empty_raises( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        agent._load_research_async = AsyncMock( return_value="" )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( ValueError, match="Could not load research" ):
                _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.FAILED
        # urgent failure notification fired
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )

    def test_translation_skip_language( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en", "es-MX" ] )
        async def save( s, is_revision=False, language="en" ):
            return f"/proj/io/script-{language}.md"
        _wire_pipeline( agent, save_path=save )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Skip language" } },
        ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            _run( agent.do_all_async() )
        # es-MX skipped → only en audio produced
        assert "es-MX" not in agent._podcast_state[ "audio_paths_by_language" ]
        assert agent.state == OrchestratorState.COMPLETED

    def test_translation_revise_then_approve( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en", "es-MX" ] )
        async def save( s, is_revision=False, language="en" ):
            return f"/proj/io/script-{language}.md"
        _wire_pipeline( agent, save_path=save )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Revise script" } },
            { "answers": { "Mexican Spanish Review": "Approve script" } },
        ]
        _silence_voice_io[ "input" ].return_value = "tweak the intro"
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.COMPLETED

    def test_non_english_only_target( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "es-MX" ] )
        async def save( s, is_revision=False, language="en" ):
            return f"/proj/io/script-{language}.md"
        async def stitch( tts, scr, language="en" ):
            return f"/proj/io/audio-{language}.mp3"
        _wire_pipeline( agent, save_path=save, audio_path=stitch )
        # no en review — first review presented is for the en *source* script (always shown),
        # then es review. (en script is generated/approved even when only es requested.)
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Approve script" } },
        ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.COMPLETED
        # en not requested → only es audio
        assert set( agent._podcast_state[ "audio_paths_by_language" ].keys() ) == { "es-MX" }

    def test_audio_partial_failure_continue_skips_one_language( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en", "es-MX" ] )
        async def save( s, is_revision=False, language="en" ):
            return f"/proj/io/script-{language}.md"
        async def stitch( tts, scr, language="en" ):
            return f"/proj/io/audio-{language}.mp3"
        _wire_pipeline( agent, save_path=save, audio_path=stitch )
        # en: a failure present; user declines to continue → skip en
        # es: clean success
        en_results = [ _TTSResult( success=True, character_count=50 ),
                       _TTSResult( success=False, error_message="429" ) ]
        es_results = [ _TTSResult( success=True, character_count=50 ) ]
        async def gen_audio( scr, language="en" ):
            res = en_results if language == "en" else es_results
            agent._podcast_state[ f"tts_results_{language}" ] = res
            return res, ( [ 1 ] if language == "en" else [] )
        agent._generate_audio_async = AsyncMock( side_effect=gen_audio )
        _silence_voice_io[ "yesno" ].return_value = False   # do NOT continue with partial
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Approve script" } },
        ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            _run( agent.do_all_async() )
        assert set( agent._podcast_state[ "audio_paths_by_language" ].keys() ) == { "es-MX" }

    def test_audio_all_segments_failed_then_no_audio_raises( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        all_failed = [ _TTSResult( success=False, error_message="500" ) ]
        async def gen_audio( scr, language="en" ):
            agent._podcast_state[ f"tts_results_{language}" ] = all_failed
            return all_failed, []   # no failed_indices, but zero successful
        agent._generate_audio_async = AsyncMock( side_effect=gen_audio )
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( RuntimeError, match="All TTS audio generation failed" ):
                _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.FAILED

    def test_audio_partial_failure_continue_yes_pydub_exception( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        results = [ _TTSResult( success=True, character_count=80 ),
                    _TTSResult( success=False, error_message="timeout" ) ]
        async def gen_audio( scr, language="en" ):
            agent._podcast_state[ f"tts_results_{language}" ] = results
            return results, [ 1 ]
        agent._generate_audio_async = AsyncMock( side_effect=gen_audio )
        _silence_voice_io[ "yesno" ].return_value = True   # continue with partial
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=True ), \
             patch( "pydub.AudioSegment.from_mp3", side_effect=Exception( "bad mp3" ) ):
            result = _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.COMPLETED
        assert result is not None

    def test_non_io_paths_link_else_branches( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ], research_doc_path="/tmp/research.md" )
        _wire_pipeline( agent, save_path="/tmp/script.md", audio_path="/tmp/audio.mp3" )
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            result = _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.COMPLETED
        assert result is not None

    # --- stop-checkpoint coverage (each _check_stop() True arm) -------------
    def _approve_all( self, vio ):
        vio[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Approve script" } },
        ]

    def test_stop_after_analyze( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        base = _wire_pipeline( agent )
        async def analyze( content ):
            agent._stop_requested = True
            return ContentAnalysis( main_topic="T" )
        agent._analyze_content_async = AsyncMock( side_effect=analyze )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_all_async() ) is None
        assert agent.state == OrchestratorState.STOPPED

    def test_stop_after_generate( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        async def gen( content, analysis ):
            agent._stop_requested = True
            return _script( title="Cool" )
        agent._generate_script_async = AsyncMock( side_effect=gen )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_all_async() ) is None

    def test_stop_after_review_approve( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        async def save( s, is_revision=False, language="en" ):
            agent._stop_requested = True
            return "/proj/io/s.md"
        agent._save_script_async = AsyncMock( side_effect=save )
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_all_async() ) is None
        assert agent.state == OrchestratorState.STOPPED

    def test_stop_after_translation_save( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en", "es-MX" ] )
        _wire_pipeline( agent )
        async def save( s, is_revision=False, language="en" ):
            if language != "en":
                agent._stop_requested = True
            return f"/proj/io/s-{language}.md"
        agent._save_script_async = AsyncMock( side_effect=save )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
        ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_all_async() ) is None

    def test_stop_after_translation_review( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en", "es-MX" ] )
        _wire_pipeline( agent )
        calls = { "es": 0 }
        async def save( s, is_revision=False, language="en" ):
            if language != "en":
                calls[ "es" ] += 1
                if calls[ "es" ] >= 2:           # the revise-save (2nd es save) sets stop
                    agent._stop_requested = True
            return f"/proj/io/s-{language}.md"
        agent._save_script_async = AsyncMock( side_effect=save )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Revise script" } },
            { "answers": { "Mexican Spanish Review": "Approve script" } },
        ]
        _silence_voice_io[ "input" ].return_value = "fix it"
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_all_async() ) is None

    def test_stop_after_audio_gen( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        async def gen_audio( scr, language="en" ):
            agent._stop_requested = True
            res = [ _TTSResult( success=True ) ]
            agent._podcast_state[ f"tts_results_{language}" ] = res
            return res, []
        agent._generate_audio_async = AsyncMock( side_effect=gen_audio )
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_all_async() ) is None

    def test_stop_after_stitch( self, _silence_voice_io ):
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        async def stitch( tts, scr, language="en" ):
            agent._stop_requested = True
            return "/proj/io/a.mp3"
        agent._stitch_audio_async = AsyncMock( side_effect=stitch )
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_all_async() ) is None

    def test_original_script_path_reused_in_review_draft( self, _silence_voice_io ):
        # 353: `if self._original_script_path:` True arm in the draft-save block
        agent = _agent( target_languages=[ "en" ] )
        _wire_pipeline( agent )
        agent._original_script_path = "/proj/io/orig.md"
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            assert _run( agent.do_all_async() ) is not None

    def test_translation_custom_feedback_and_empty_and_nonio_link( self, _silence_voice_io ):
        # covers translated "Other" custom feedback (542), empty-feedback loop (544->496),
        # and the non-io translated link else branch (492)
        agent = _agent( target_languages=[ "en", "es-MX" ] )
        _wire_pipeline( agent )
        async def save( s, is_revision=False, language="en" ):
            return f"/tmp/s-{language}.md"   # non-io path → translated link else branch
        agent._save_script_async = AsyncMock( side_effect=save )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Approve script" } },
            { "answers": { "Mexican Spanish Review": "Revise script" } },     # empty feedback → loops
            { "answers": { "Mexican Spanish Review": "Make it warmer" } },    # custom "Other"
            { "answers": { "Mexican Spanish Review": "Approve script" } },
        ]
        _silence_voice_io[ "input" ].return_value = ""   # empty for the first revise
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            assert _run( agent.do_all_async() ) is not None


# ===========================================================================
# Helper debug=False branch fillers
# ===========================================================================
class TestHelperDebugFalseBranches:
    def test_analyze_refuses_with_debug_off( self, capsys ):
        """
        Debug-off covers the false arm of `if self.debug:` — and the raise still fires.

        The old test asserted a forged minimal analysis came back. Silence on stdout
        is the only thing debug=False should change; whether the failure is REPORTED
        must not depend on a debug flag.
        """
        agent = _agent( debug=False )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_analysis = AsyncMock( side_effect=RuntimeError( "x" ) )

        with patch.object( orch_mod, "get_content_analysis_prompt", return_value="P" ):
            with pytest.raises( PodcastGenerationError ):
                _run( agent._analyze_content_async( "r" ) )

        assert "Analysis error" not in capsys.readouterr().out

    def test_generate_refuses_with_debug_off( self, capsys ):
        """Same false-arm coverage for script generation; the raise is unconditional."""
        agent = _agent( debug=False )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_script = AsyncMock( side_effect=RuntimeError( "x" ) )

        with patch.object( orch_mod, "get_dynamic_duo_description", return_value="D" ), \
             patch.object( orch_mod, "get_script_generation_prompt", return_value="P" ):
            with pytest.raises( PodcastGenerationError ):
                _run( agent._generate_script_async( "r", ContentAnalysis( main_topic="Q" ) ) )

        assert "Script generation error" not in capsys.readouterr().out

    def test_translated_exception_no_debug( self ):
        agent = _agent( debug=False )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_script = AsyncMock( side_effect=RuntimeError( "x" ) )
        translated = _run( agent._generate_translated_script_async( _script( title="EN" ), "es-MX" ) )
        assert "Translation Failed" in translated.title

    def test_generate_audio_max_segments_no_debug( self ):
        agent = _agent( max_segments=1, debug=False )
        results = [ _TTSResult( success=True ) ]
        agent._tts_client = MagicMock()
        agent._tts_client.generate_all_segments = AsyncMock( return_value=( results, [] ) )
        script = _script( segments=[
            _segment( "Nora", "curious", "a b c" ),
            _segment( "Quentin", "expert", "d e f" ),
        ] )
        _run( agent._generate_audio_async( script ) )
        called = agent._tts_client.generate_all_segments.await_args.kwargs[ "script" ]
        assert called.get_segment_count() == 1


# ===========================================================================
# THORNY sub-batch 2 — do_review_only_async
# ===========================================================================
def _review_agent( original_path="/proj/io/s.md", draft_path="/proj/io/s.md" ):
    agent = _agent()
    agent._podcast_state[ "draft_script" ]      = _script( title="Loaded" )
    agent._podcast_state[ "draft_script_path" ] = draft_path
    agent._original_script_path                 = original_path
    agent._save_script_async   = AsyncMock( side_effect=lambda s, is_revision=False, language="en": original_path )
    agent._revise_script_async = AsyncMock( return_value=_script( title="Revised" ) )
    return agent


class TestDoReviewOnlyAsync:
    def test_no_script_raises( self, _silence_voice_io ):
        agent = _agent()
        agent._podcast_state[ "draft_script" ] = None
        with pytest.raises( ValueError, match="No script loaded" ):
            _run( agent.do_review_only_async() )
        assert agent.state == OrchestratorState.FAILED

    def test_approve_immediately_io_link( self, _silence_voice_io ):
        agent = _review_agent()
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent.do_review_only_async() )
        assert result is not None
        assert agent.state == OrchestratorState.COMPLETED
        assert agent._podcast_state[ "script_approved" ] is True

    def test_cancel( self, _silence_voice_io ):
        agent = _review_agent()
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Cancel" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_review_only_async() ) is None
        assert agent.state == OrchestratorState.STOPPED

    def test_revise_feedback_then_approve_revision_label( self, _silence_voice_io ):
        agent = _review_agent()
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Revise script" } },
            { "answers": { "Script Review": "Approve script" } },
        ]
        _silence_voice_io[ "input" ].return_value = "more energy"
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( agent.do_review_only_async() )
        assert agent._podcast_state[ "revision_count" ] == 1
        agent._revise_script_async.assert_awaited()

    def test_revise_empty_then_custom_then_approve_nonio_link( self, _silence_voice_io ):
        agent = _review_agent( original_path="/tmp/s.md", draft_path="/tmp/s.md" )
        agent._save_script_async = AsyncMock( side_effect=lambda s, is_revision=False, language="en": "/tmp/s.md" )
        _silence_voice_io[ "choices" ].side_effect = [
            { "answers": { "Script Review": "Revise script" } },   # empty feedback → loops
            { "answers": { "Script Review": "Trim the middle" } }, # custom "Other"
            { "answers": { "Script Review": "Approve script" } },
        ]
        _silence_voice_io[ "input" ].return_value = ""
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_review_only_async() ) is not None
        assert agent._podcast_state[ "revision_count" ] == 1

    def test_exception_propagates_failed( self, _silence_voice_io ):
        agent = _review_agent()
        _silence_voice_io[ "choices" ].return_value = { "answers": { "Script Review": "Approve script" } }
        agent._save_script_async = AsyncMock( side_effect=RuntimeError( "disk" ) )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( RuntimeError, match="disk" ):
                _run( agent.do_review_only_async() )
        assert agent.state == OrchestratorState.FAILED


# ===========================================================================
# THORNY sub-batch 3 — do_audio_only_async
# ===========================================================================
def _audio_agent( research_doc_path="/proj/io/dr/report.md", draft_path="/proj/io/s.md" ):
    agent = _agent( research_doc_path=research_doc_path )
    agent._podcast_state[ "draft_script" ]      = _script( title="Loaded" )
    agent._podcast_state[ "draft_script_path" ] = draft_path
    return agent


def _wire_audio_only( agent, results=None, failed=None, audio_path="/proj/io/audio.mp3" ):
    results = results if results is not None else [ _TTSResult( success=True, character_count=100 ) ]
    fails   = failed if failed is not None else []
    async def gen_audio( scr, language="en" ):
        agent._podcast_state[ "tts_results_en" ] = results
        return results, fails
    agent._generate_audio_async = AsyncMock( side_effect=gen_audio )
    if callable( audio_path ):
        agent._stitch_audio_async = AsyncMock( side_effect=audio_path )
    else:
        agent._stitch_audio_async = AsyncMock( return_value=audio_path )


class TestDoAudioOnlyAsync:
    def test_no_script_raises( self, _silence_voice_io ):
        agent = _agent()
        agent._podcast_state[ "draft_script" ] = None
        with pytest.raises( ValueError, match="No script loaded" ):
            _run( agent.do_audio_only_async() )
        assert agent.state == OrchestratorState.FAILED

    def test_happy_with_research_link_pydub_success( self, _silence_voice_io ):
        agent = _audio_agent()
        _wire_audio_only( agent )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=True ), \
             patch( "pydub.AudioSegment.from_mp3", return_value=_FakeAudio( 120000 ) ):
            result = _run( agent.do_audio_only_async() )
        assert result is not None
        assert agent.state == OrchestratorState.COMPLETED
        assert agent._podcast_state[ "final_audio_path" ] == "/proj/io/audio.mp3"

    def test_partial_failure_decline_continue( self, _silence_voice_io ):
        agent = _audio_agent()
        results = [ _TTSResult( success=True ), _TTSResult( success=False, error_message="429" ) ]
        _wire_audio_only( agent, results=results, failed=[ 1 ] )
        _silence_voice_io[ "yesno" ].return_value = False
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_audio_only_async() ) is None
        assert agent.state == OrchestratorState.STOPPED

    def test_partial_failure_accept_continue( self, _silence_voice_io ):
        agent = _audio_agent()
        results = [ _TTSResult( success=True, character_count=70 ),
                    _TTSResult( success=False, error_message="429" ) ]
        _wire_audio_only( agent, results=results, failed=[ 1 ] )
        _silence_voice_io[ "yesno" ].return_value = True
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            assert _run( agent.do_audio_only_async() ) is not None
        assert agent.state == OrchestratorState.COMPLETED

    def test_all_failed_raises( self, _silence_voice_io ):
        agent = _audio_agent()
        all_failed = [ _TTSResult( success=False, error_message="500" ) ]
        _wire_audio_only( agent, results=all_failed, failed=[] )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( RuntimeError, match="no segments produced audio" ):
                _run( agent.do_audio_only_async() )
        assert agent.state == OrchestratorState.FAILED

    def test_stop_after_audio_gen( self, _silence_voice_io ):
        agent = _audio_agent()
        async def gen_audio( scr, language="en" ):
            agent._stop_requested = True
            res = [ _TTSResult( success=True ) ]
            agent._podcast_state[ "tts_results_en" ] = res
            return res, []
        agent._generate_audio_async = AsyncMock( side_effect=gen_audio )
        agent._stitch_audio_async = AsyncMock( return_value="/proj/io/a.mp3" )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_audio_only_async() ) is None

    def test_stop_after_stitch( self, _silence_voice_io ):
        agent = _audio_agent()
        _wire_audio_only( agent )
        async def stitch( tts, scr, language="en" ):
            agent._stop_requested = True
            return "/proj/io/a.mp3"
        agent._stitch_audio_async = AsyncMock( side_effect=stitch )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent.do_audio_only_async() ) is None

    def test_nonio_paths_editmode_research_pydub_exception( self, _silence_voice_io ):
        # non-io script/audio links (else branches), research == "edit-mode" → research_link None,
        # os.path.exists True but pydub raises → except pass
        agent = _audio_agent( research_doc_path="edit-mode", draft_path="/tmp/s.md" )
        _wire_audio_only( agent, audio_path="/tmp/a.mp3" )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=True ), \
             patch( "pydub.AudioSegment.from_mp3", side_effect=Exception( "bad" ) ):
            assert _run( agent.do_audio_only_async() ) is not None
        assert agent.state == OrchestratorState.COMPLETED

    def test_research_doc_nonio_path_no_link( self, _silence_voice_io ):
        # research_doc_path is a real-but-non-io path → not "edit-mode" but fails startswith(io_base)
        agent = _audio_agent( research_doc_path="/tmp/research.md", draft_path="/proj/io/s.md" )
        _wire_audio_only( agent )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            assert _run( agent.do_audio_only_async() ) is not None


# ===========================================================================
# Approval gate speaks at HIGH priority (Rick's direct ask 2026-08-03)
# ===========================================================================
class TestPresentScriptReviewPriority:
    """The blocking script-review gate MUST pass priority='high' so the TTS
    alert fires for Rick driving by voice from across the room. The default was
    'medium' (the dispatcher's default_priority), which may not alert at all —
    and standing doctrine is that every blocking ask is high. This asserts the
    gate passes it, so nobody silently drops it back to the default."""

    def test_gate_passes_priority_high( self, _silence_voice_io ):
        agent = _agent()
        agent.config.script_review_timeout_seconds = 600
        asyncio.run( agent._present_script_review(
            questions = [ {
                "header"  : "Review",
                "question": "Approve this script?",
                "options" : [ { "label": "Approve script" }, { "label": "Revise" } ],
            } ],
            header = "Review",
        ) )
        choices = _silence_voice_io[ "choices" ]
        choices.assert_awaited_once()
        _args, kwargs = choices.await_args
        assert kwargs.get( "priority" ) == "high", (
            f"the script-review gate must alert at high so the TTS reaches a "
            f"remote user; got {kwargs.get( 'priority' )!r}"
        )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
