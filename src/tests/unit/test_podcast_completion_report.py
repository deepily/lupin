"""
Unit tests for Podcast Generator completion voice report.

Session 9056c113 Phase E.3: Podcast success path gets the same outcome-aware
TTS + rich markdown abstract pattern as TFE/BFE. Mirrors
test_bfe_completion_report.py structure.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_podcast_job():
    """Construct a Podcast job instance with minimal required args."""
    from cosa.agents.podcast_generator.job import PodcastGeneratorJob
    return PodcastGeneratorJob(
        research_path    = "io/deep-research/user1@test.com/research.md",
        user_id          = "user1",
        user_email       = "podcast-completion@test.com",
        session_id       = "test-session",
        target_languages = [ "en" ],
        debug            = False,
    )


class TestPodcastCompletionReport:
    """Podcast success path sends voice_io.notify with outcome-aware TTS + abstract."""

    @pytest.mark.asyncio
    async def test_completion_notify_called_on_full_success( self ):
        """Audio rendered → 'N segments rendered in K languages' TTS."""
        podcast = _make_podcast_job()

        # Mock script with 5 segments, 3.5 min duration
        mock_script = MagicMock()
        mock_script.get_segment_count.return_value = 5
        mock_script.estimated_duration_minutes = 3.5

        # Mock orchestrator agent
        mock_agent = MagicMock()
        mock_agent.do_all_async = AsyncMock( return_value=mock_script )
        mock_agent.podcast_id = "pod-abc123"
        mock_agent._podcast_state = {
            "final_audio_path"  : "io/podcasts/user1/final.mp3",
            "final_script_path" : "io/podcasts/user1/script.md",
        }
        mock_agent._api_client = None  # keeps cost calc simple

        with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
             patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
             patch( "cosa.agents.podcast_generator.cosa_interface" ), \
             patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", return_value=mock_agent ), \
             patch( "os.path.exists", return_value=True ):
            await podcast._execute()

        # Find the completion notify (the one with "Podcast Activity Report" abstract)
        completion_call = next(
            c for c in mock_notify.call_args_list
            if c.kwargs.get( "abstract" ) and "Podcast Activity Report" in c.kwargs[ "abstract" ]
        )

        tts_msg = completion_call.args[ 0 ]
        assert "complete" in tts_msg.lower()
        assert "5 segment" in tts_msg.lower()
        assert "1 language" in tts_msg.lower()

        abstract = completion_call.kwargs[ "abstract" ]
        assert "**Segments**: 5" in abstract
        assert "io/podcasts/user1/final.mp3" in abstract
        assert "io/podcasts/user1/script.md" in abstract
        assert "~3.5 min" in abstract

    @pytest.mark.asyncio
    async def test_completion_notify_called_on_script_only( self ):
        """Script done but audio path None → 'Audio rendering pending' TTS."""
        podcast = _make_podcast_job()

        mock_script = MagicMock()
        mock_script.get_segment_count.return_value = 3
        mock_script.estimated_duration_minutes = 2.0

        mock_agent = MagicMock()
        mock_agent.do_all_async = AsyncMock( return_value=mock_script )
        mock_agent.podcast_id = "pod-xyz"
        mock_agent._podcast_state = {
            "final_audio_path"  : None,   # no audio
            "final_script_path" : "io/podcasts/user1/script.md",
        }
        mock_agent._api_client = None

        with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
             patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
             patch( "cosa.agents.podcast_generator.cosa_interface" ), \
             patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", return_value=mock_agent ), \
             patch( "os.path.exists", return_value=True ):
            await podcast._execute()

        completion_call = next(
            c for c in mock_notify.call_args_list
            if c.kwargs.get( "abstract" ) and "Podcast Activity Report" in c.kwargs[ "abstract" ]
        )
        tts_msg = completion_call.args[ 0 ]
        assert "script complete" in tts_msg.lower()
        assert "audio rendering pending" in tts_msg.lower()

    @pytest.mark.asyncio
    async def test_completion_notify_not_called_on_cancellation( self ):
        """Cancelled workflow (do_all_async returns None) should NOT send completion notify."""
        podcast = _make_podcast_job()

        mock_agent = MagicMock()
        mock_agent.do_all_async = AsyncMock( return_value=None )  # cancelled

        with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
             patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
             patch( "cosa.agents.podcast_generator.cosa_interface" ), \
             patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", return_value=mock_agent ), \
             patch( "os.path.exists", return_value=True ):
            result = await podcast._execute()

        assert "cancelled" in result.lower()
        # No completion notify should have happened (only the cancellation one)
        completion_calls = [
            c for c in mock_notify.call_args_list
            if c.kwargs.get( "abstract" ) and "Podcast Activity Report" in c.kwargs[ "abstract" ]
        ]
        assert completion_calls == []
