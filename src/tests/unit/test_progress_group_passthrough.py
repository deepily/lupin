#!/usr/bin/env python3
"""
Unit tests for progress_group_id passthrough across all agentic iterative loops.

Verifies that progress_group_id is correctly wired from call site → voice_io / cosa_interface
for each of the 6 files modified in the progress_group_id integration:

    Phase 1 (Infrastructure):
        - Podcast Generator voice_io.notify() passthrough
        - SWE Team cosa_interface.notify_progress() passthrough
        - SWE Team orchestrator._notify() passthrough
        - SWE Team hooks.notification_hook() passthrough

    Phase 2 (Podcast Generator loops):
        - TTS audio progress callback uses _audio_progress_group_id
        - Per-language loop uses separate lang_audio_group_id

    Phase 3 (Deep Research loop):
        - Subquery research loop generates and passes research_group_id

    Phase 4 (SWE Team loops):
        - Task delegation loop uses delegation_group_id
        - Coder SDK stream uses coder_group_id
        - Tester SDK stream uses tester_group_id
        - Verification cycle uses verify_group_id
        - Re-delegation stream uses redelegate_group_id

All SDK / network calls mocked via unittest.mock. No server required.
"""

import asyncio
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# =============================================================================
# Helpers
# =============================================================================

PG_REGEX = re.compile( r"^pg-[a-f0-9]{8}$" )


def assert_valid_pg_id( value ):
    """Assert value matches pg-{8 hex chars} format."""
    assert value is not None, "progress_group_id should not be None"
    assert PG_REGEX.match( value ), f"Invalid pg ID format: {value!r}"


# =============================================================================
# Phase 1A: Podcast Generator voice_io.notify() passthrough
# =============================================================================

class TestPodcastGeneratorVoiceIoPassthrough:
    """Verify podcast_generator/voice_io.notify() forwards progress_group_id."""

    @pytest.mark.asyncio
    async def test_progress_group_id_passed_to_core( self ):
        """progress_group_id reaches the AsyncNotificationRequest via dispatcher."""
        with patch( "cosa.agents.utils.voice_io._voice_available", True ), \
             patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_async" ) as mock_send:

            from cosa.agents.podcast_generator import voice_io
            await voice_io.notify(
                "Test message",
                priority          = "low",
                progress_group_id = "pg-aabbccdd",
            )

            mock_send.assert_called_once()
            request = mock_send.call_args[ 0 ][ 0 ]
            assert request.progress_group_id == "pg-aabbccdd"

    @pytest.mark.asyncio
    async def test_progress_group_id_none_by_default( self ):
        """progress_group_id defaults to None when not provided."""
        with patch( "cosa.agents.utils.voice_io._voice_available", True ), \
             patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_async" ) as mock_send:

            from cosa.agents.podcast_generator import voice_io
            await voice_io.notify( "No group" )

            request = mock_send.call_args[ 0 ][ 0 ]
            assert request.progress_group_id is None


# =============================================================================
# Phase 1B: SWE Team cosa_interface.notify_progress() passthrough
# =============================================================================

class TestSweTeamCosaInterfacePassthrough:
    """Verify swe_team/cosa_interface.notify_progress() includes progress_group_id in AsyncNotificationRequest."""

    @pytest.mark.asyncio
    async def test_progress_group_id_in_request( self ):
        """progress_group_id is set on the AsyncNotificationRequest."""
        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_async" ) as mock_send, \
             patch( "cosa.agents.swe_team.cosa_interface.SESSION_ID", "test-session" ), \
             patch( "cosa.agents.swe_team.cosa_interface.SESSION_NAME", "test session" ):

            from cosa.agents.swe_team import cosa_interface
            await cosa_interface.notify_progress(
                message           = "Test",
                role              = "lead",
                progress_group_id = "pg-11223344",
            )

            mock_send.assert_called_once()
            request = mock_send.call_args[ 0 ][ 0 ]
            assert request.progress_group_id == "pg-11223344"

    @pytest.mark.asyncio
    async def test_progress_group_id_none_by_default( self ):
        """progress_group_id defaults to None when not passed."""
        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_async" ) as mock_send, \
             patch( "cosa.agents.swe_team.cosa_interface.SESSION_ID", "test-session" ), \
             patch( "cosa.agents.swe_team.cosa_interface.SESSION_NAME", "test session" ):

            from cosa.agents.swe_team import cosa_interface
            await cosa_interface.notify_progress( message="No group" )

            request = mock_send.call_args[ 0 ][ 0 ]
            assert request.progress_group_id is None


# =============================================================================
# Phase 1C: SWE Team orchestrator._notify() passthrough
# =============================================================================

class TestSweTeamOrchestratorNotifyPassthrough:
    """Verify orchestrator._notify() passes progress_group_id to team_io.notify_progress()."""

    @pytest.fixture
    def orchestrator( self ):
        from cosa.agents.swe_team.config import SweTeamConfig
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        return SweTeamOrchestrator(
            task_description = "test task",
            config           = SweTeamConfig( dry_run=True ),
            session_id       = "test-session",
        )

    @pytest.fixture
    def mock_team_io( self ):
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()
        return team_io

    @pytest.mark.asyncio
    async def test_progress_group_id_forwarded( self, orchestrator, mock_team_io ):
        """progress_group_id is passed through to team_io.notify_progress()."""
        await orchestrator._notify(
            mock_team_io, "Test message",
            progress_group_id = "pg-deadbeef",
        )

        mock_team_io.notify_progress.assert_awaited_once()
        kwargs = mock_team_io.notify_progress.call_args.kwargs
        assert kwargs[ "progress_group_id" ] == "pg-deadbeef"

    @pytest.mark.asyncio
    async def test_progress_group_id_none_by_default( self, orchestrator, mock_team_io ):
        """progress_group_id defaults to None when not provided."""
        await orchestrator._notify( mock_team_io, "No group" )

        kwargs = mock_team_io.notify_progress.call_args.kwargs
        assert kwargs[ "progress_group_id" ] is None


# =============================================================================
# Phase 1D: SWE Team hooks.notification_hook() passthrough
# =============================================================================

class TestSweTeamHooksPassthrough:
    """Verify hooks.notification_hook() passes progress_group_id to team_io.notify_progress()."""

    @pytest.mark.asyncio
    async def test_progress_group_id_forwarded( self ):
        """progress_group_id is passed through notification_hook → team_io.notify_progress()."""
        from cosa.agents.swe_team.hooks import notification_hook

        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        await notification_hook(
            { "message": "SDK event" },
            team_io,
            role              = "coder",
            progress_group_id = "pg-12345678",
        )

        team_io.notify_progress.assert_awaited_once()
        kwargs = team_io.notify_progress.call_args.kwargs
        assert kwargs[ "progress_group_id" ] == "pg-12345678"

    @pytest.mark.asyncio
    async def test_progress_group_id_none_by_default( self ):
        """progress_group_id defaults to None when not provided."""
        from cosa.agents.swe_team.hooks import notification_hook

        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        await notification_hook( { "message": "No group" }, team_io )

        kwargs = team_io.notify_progress.call_args.kwargs
        assert kwargs[ "progress_group_id" ] is None

    @pytest.mark.asyncio
    async def test_empty_message_skips_notification( self ):
        """Empty message should not trigger notify_progress at all."""
        from cosa.agents.swe_team.hooks import notification_hook

        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        await notification_hook( { "message": "" }, team_io, progress_group_id="pg-aaaabbbb" )

        team_io.notify_progress.assert_not_awaited()


# =============================================================================
# Phase 2: Podcast Generator — group ID generation
# =============================================================================

class TestPodcastGeneratorGroupIdGeneration:
    """Verify Podcast Generator generates valid progress group IDs."""

    def test_audio_progress_group_id_attribute_exists( self ):
        """PodcastOrchestratorAgent defines _audio_progress_group_id attribute."""
        import inspect
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        source = inspect.getsource( PodcastOrchestratorAgent.__init__ )
        assert "_audio_progress_group_id" in source, "Missing _audio_progress_group_id in __init__"

    def test_pg_id_format_inline_generation( self ):
        """Inline f"pg-{uuid.uuid4().hex[:8]}" generates valid format."""
        # This is the exact pattern used in all orchestrator loops
        pg_id = f"pg-{uuid.uuid4().hex[ :8 ]}"
        assert_valid_pg_id( pg_id )

    def test_pg_ids_are_unique( self ):
        """Multiple inline generations produce unique IDs."""
        ids = { f"pg-{uuid.uuid4().hex[ :8 ]}" for _ in range( 50 ) }
        assert len( ids ) == 50


# =============================================================================
# Phase 4A: SWE Team — delegation loop group ID
# =============================================================================

class TestSweTeamDelegationGroupId:
    """Verify task delegation loop generates delegation_group_id via source inspection."""

    def test_execute_live_generates_delegation_group_id( self ):
        """_execute_live() generates a delegation_group_id before the task loop."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._execute_live )
        assert "delegation_group_id" in source
        assert 'progress_group_id = delegation_group_id' in source

    def test_execute_live_delegation_group_id_format( self ):
        """delegation_group_id uses the uuid inline pattern."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._execute_live )
        assert 'delegation_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"' in source

    def test_execute_live_verify_group_id_present( self ):
        """_execute_live() also generates verify_group_id for the verification loop."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._execute_live )
        assert "verify_group_id" in source
        assert 'progress_group_id = verify_group_id' in source


# =============================================================================
# Phase 4B: SWE Team — coder SDK stream group ID
# =============================================================================

class TestSweTeamCoderStreamGroupId:
    """Verify _delegate_task() generates coder_group_id via source inspection."""

    def test_delegate_task_generates_coder_group_id( self ):
        """_delegate_task() generates a coder_group_id."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._delegate_task )
        assert "coder_group_id" in source
        assert 'coder_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"' in source

    def test_delegate_task_passes_coder_group_id_to_hook( self ):
        """notification_hook() call in _delegate_task() receives coder_group_id."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._delegate_task )
        assert "progress_group_id=coder_group_id" in source


# =============================================================================
# Phase 4C: SWE Team — tester SDK stream group ID
# =============================================================================

class TestSweTeamTesterStreamGroupId:
    """Verify _verify_result() generates tester_group_id via source inspection."""

    def test_verify_result_generates_tester_group_id( self ):
        """_verify_result() generates a tester_group_id."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._verify_result )
        assert "tester_group_id" in source
        assert 'tester_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"' in source

    def test_verify_result_passes_tester_group_id_to_hook( self ):
        """notification_hook() call in _verify_result() receives tester_group_id."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._verify_result )
        assert "progress_group_id=tester_group_id" in source


class TestSweTeamRedelegateGroupId:
    """Verify _redelegate_with_feedback() generates redelegate_group_id."""

    def test_redelegate_generates_group_id( self ):
        """_redelegate_with_feedback() generates a redelegate_group_id."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._redelegate_with_feedback )
        assert "redelegate_group_id" in source
        assert 'redelegate_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"' in source

    def test_redelegate_passes_group_id_to_hook( self ):
        """notification_hook() call in _redelegate_with_feedback() receives redelegate_group_id."""
        import inspect
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        source = inspect.getsource( SweTeamOrchestrator._redelegate_with_feedback )
        assert "progress_group_id=redelegate_group_id" in source


class TestDeepResearchGroupId:
    """Verify Deep Research cli.py generates research_group_id."""

    def test_run_research_generates_group_id( self ):
        """run_research() generates a research_group_id."""
        import inspect
        from cosa.agents.deep_research.cli import run_research
        source = inspect.getsource( run_research )
        assert "research_group_id" in source
        assert 'research_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"' in source

    def test_run_research_passes_group_id_to_notify( self ):
        """voice_io.notify() calls in run_research() receive research_group_id."""
        import inspect
        from cosa.agents.deep_research.cli import run_research
        source = inspect.getsource( run_research )
        assert "progress_group_id=research_group_id" in source


class TestPodcastGeneratorOrchestratorGroupIds:
    """Verify Podcast Generator orchestrator generates per-language and audio group IDs."""

    def test_do_all_async_generates_audio_group_id( self ):
        """do_all_async() generates _audio_progress_group_id per language."""
        import inspect
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        source = inspect.getsource( PodcastOrchestratorAgent.do_all_async )
        assert '_audio_progress_group_id' in source
        assert 'self._audio_progress_group_id     = f"pg-{uuid.uuid4().hex[ :8 ]}"' in source

    def test_do_all_async_generates_lang_group_id( self ):
        """do_all_async() generates a separate lang_audio_group_id per language."""
        import inspect
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        source = inspect.getsource( PodcastOrchestratorAgent.do_all_async )
        assert "lang_audio_group_id" in source
        assert 'progress_group_id = lang_audio_group_id' in source

    def test_audio_progress_callback_uses_group_id( self ):
        """_audio_progress_callback() passes self._audio_progress_group_id to notify."""
        import inspect
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        source = inspect.getsource( PodcastOrchestratorAgent._audio_progress_callback )
        assert "progress_group_id = self._audio_progress_group_id" in source

    def test_do_audio_only_async_generates_group_id( self ):
        """do_audio_only_async() also generates its own _audio_progress_group_id."""
        import inspect
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        source = inspect.getsource( PodcastOrchestratorAgent.do_audio_only_async )
        assert '_audio_progress_group_id' in source


# =============================================================================
# Cross-cutting: progress_group_id format validation
# =============================================================================

class TestProgressGroupIdFormat:
    """Validate the pg-{8hex} format contract used across all agents."""

    @pytest.mark.parametrize( "pg_id", [
        "pg-a1b2c3d4",
        "pg-00000000",
        "pg-ffffffff",
        "pg-abcdef01",
        "pg-12345678",
    ] )
    def test_valid_ids_match_regex( self, pg_id ):
        """Known-good IDs pass the regex."""
        assert PG_REGEX.match( pg_id )

    @pytest.mark.parametrize( "pg_id", [
        "pg-ABCDEF01",      # Uppercase
        "pg-a1b2c3d",       # 7 hex chars
        "pg-a1b2c3d4e",     # 9 hex chars
        "a1b2c3d4",          # Missing prefix
        "PG-a1b2c3d4",      # Uppercase prefix
        "pg_a1b2c3d4",      # Underscore
        "",                   # Empty
        "pg-",               # Prefix only
    ] )
    def test_invalid_ids_rejected( self, pg_id ):
        """Known-bad IDs fail the regex."""
        assert not PG_REGEX.match( pg_id )

    def test_uuid_based_generation_always_valid( self ):
        """The inline uuid pattern always produces valid IDs."""
        for _ in range( 100 ):
            pg_id = f"pg-{uuid.uuid4().hex[ :8 ]}"
            assert_valid_pg_id( pg_id )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for progress_group_id passthrough tests."""
    import cosa.utils.util as cu

    cu.print_banner( "Progress Group ID Passthrough Smoke Test", prepend_nl=True )

    try:
        print( "Testing pg ID format validation..." )
        assert PG_REGEX.match( "pg-a1b2c3d4" )
        assert not PG_REGEX.match( "pg-INVALID" )
        print( "✓ Format regex works" )

        print( "Testing uuid-based generation..." )
        ids = set()
        for _ in range( 20 ):
            pg_id = f"pg-{uuid.uuid4().hex[ :8 ]}"
            assert_valid_pg_id( pg_id )
            ids.add( pg_id )
        assert len( ids ) == 20
        print( "✓ UUID generation produces 20 unique valid IDs" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
