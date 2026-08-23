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

    # voice_io.notify's dispatch gate is `_force_cli_mode or _cosa_interface is None`
    # — it does NOT read `_voice_available`. The core `_cosa_interface` global is
    # None by default and is only set to the podcast interface as a side-effect of
    # the FIRST import of podcast_generator.voice_io in the process. Once any earlier
    # test has imported that module, this test's own import is a no-op and the gate
    # sees whatever `_cosa_interface` was left at (None) — so notify prints and never
    # reaches the dispatcher. These tests therefore pin BOTH gate inputs explicitly
    # (context-managed, auto-restored) so the outcome does not depend on collection
    # order (bug 69fb89cd, polluter #2 — an order-dependent victim, not a dirty
    # teardown elsewhere).

    @pytest.mark.asyncio
    async def test_progress_group_id_passed_to_core( self ):
        """progress_group_id reaches the AsyncNotificationRequest via dispatcher."""
        from cosa.agents.podcast_generator import voice_io
        from cosa.agents.podcast_generator import cosa_interface as podcast_cosa_interface
        with patch( "cosa.agents.utils.voice_io._cosa_interface", podcast_cosa_interface ), \
             patch( "cosa.agents.utils.voice_io._force_cli_mode", False ), \
             patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_async" ) as mock_send:

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
        from cosa.agents.podcast_generator import voice_io
        from cosa.agents.podcast_generator import cosa_interface as podcast_cosa_interface
        with patch( "cosa.agents.utils.voice_io._cosa_interface", podcast_cosa_interface ), \
             patch( "cosa.agents.utils.voice_io._force_cli_mode", False ), \
             patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_async" ) as mock_send:

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

    def test_a_fresh_agent_has_no_audio_tag_yet( self ):
        """A tag belongs to a RUN, not to the object — a new agent holds none.

        Replaces a grep for the attribute name in __init__ (row 122f07a1). That
        check passed on any build that merely mentioned the word; this one fails
        if a stale tag is ever baked in at construction, which is what would make
        two runs share a UI line.
        """
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        from cosa.agents.podcast_generator.config import PodcastConfig

        agent = PodcastOrchestratorAgent(
            research_doc_path = "/io/dr/report.md",
            user_id           = "u@test.com",
            config            = PodcastConfig(),
        )
        assert agent._audio_progress_group_id is None, (
            f"a freshly built agent must not carry an audio tag; got "
            f"{agent._audio_progress_group_id!r}"
        )

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
# Phase 4: SWE Team — where each progress group ID starts and stops
# =============================================================================
#
# WHAT THESE USED TO BE, AND WHY THEY CHANGED (row 122f07a1). Every test below
# was an `assert "<literal>" in inspect.getsource( <method> )`. That shape is a
# grep: it goes green on a build that keeps the text and guts the behaviour, and
# red on a rename that breaks nothing. Worse, the rule that actually matters here
# is INVISIBLE to a grep. In orchestrator.py the delegation ID is created ONCE
# ABOVE the task loop, so every task's status line updates ONE slot in place;
# the verification ID is created INSIDE the loop, so each task gets its OWN slot.
# Move either line across its loop boundary and the source text is byte-identical
# — `delegation_group_id = f"pg-..."` still reads exactly the same — while the UI
# silently starts overwriting one task's result with another's. The tests below
# drive the real methods with the SDK stubbed and read the IDs that reach the
# notification seam, so that move is precisely what reddens them.


def _collect_hook_group_ids( mock_hook ):
    """Every progress_group_id that reached notification_hook, call order preserved."""
    return [ c.kwargs[ "progress_group_id" ] for c in mock_hook.await_args_list ]


def _collect_notify_group_ids( mock_notify, contains ):
    """
    progress_group_id values that reached orchestrator._notify, filtered by message.

    Filtering on the message text is how a caller asks for "the delegation ones"
    or "the verified ones" without depending on call ordering.
    """
    out = []
    for c in mock_notify.await_args_list:
        if contains not in c.kwargs.get( "message", "" ): continue
        out.append( c.kwargs.get( "progress_group_id" ) )
    return out


class TestSweTeamDelegationLoopGroupIds:
    """
    The delegation loop shares one group ID; each verification cycle gets its own.

    Drives _execute_live over three tasks with every collaborator stubbed, then
    reads what reached _notify. A grep cannot tell the two rules apart — both
    generator lines look identical — but the emitted notifications can.
    """

    def _drive( self, task_count ):
        """Run _execute_live end to end with stubs; return the _notify mock."""
        import cosa.agents.swe_team.orchestrator as orch_mod
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        from cosa.agents.swe_team.config import SweTeamConfig
        from cosa.agents.swe_team.state import TaskSpec, DelegationResult, VerificationResult

        specs = [ TaskSpec( title=f"task-{i}", objective="o", output_format="f" )
                  for i in range( task_count ) ]
        coder = [ DelegationResult( task_index=i, task_title=f"task-{i}", status="success",
                                    output="done", files_changed=[ "a.py" ] )
                  for i in range( task_count ) ]
        verds = [ VerificationResult( task_index=i, task_title=f"task-{i}", passed=True,
                                      tester_output="ok", status="passed" )
                  for i in range( task_count ) ]

        orch = SweTeamOrchestrator(
            task_description = "Build X",
            config           = SweTeamConfig( trust_mode="disabled", enable_checkins=False ),
            job_id           = "swe-pg",
        )
        notify = AsyncMock()
        with patch.object( orch, "_notify", notify ), \
             patch.object( orch, "_emit_state", AsyncMock() ), \
             patch.object( orch_mod, "ProgressLog", MagicMock() ), \
             patch.object( orch_mod, "FeatureList", MagicMock() ), \
             patch.object( orch_mod.cu, "get_project_root", MagicMock( return_value="/tmp" ) ), \
             patch.object( orch, "_decompose_task", AsyncMock( return_value=specs ) ), \
             patch.object( orch, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( orch, "_delegate_task", AsyncMock( side_effect=coder ) ), \
             patch.object( orch, "_verify_result", AsyncMock( side_effect=verds ) ), \
             patch.object( orch, "_check_in_with_user", AsyncMock( return_value=None ) ):
            asyncio.run( orch._execute_live( MagicMock() ) )
        return notify

    def test_one_delegation_group_id_covers_every_task( self ):
        """All three "Delegating task N/3" notifications share ONE valid group ID.

        RED ON REVERT: move the delegation_group_id assignment inside the task
        loop and each task gets its own ID — three distinct values here.
        """
        group_ids = _collect_notify_group_ids( self._drive( 3 ), "Delegating task" )

        assert len( group_ids ) == 3, f"expected one delegation notify per task, got {group_ids}"
        assert len( set( group_ids ) ) == 1, (
            "the delegation loop must reuse ONE group ID so the three status "
            f"notifications update one line in place; got {group_ids}"
        )
        assert_valid_pg_id( group_ids[ 0 ] )

    def test_each_task_gets_its_own_verification_group_id( self ):
        """Per-task verification notifications carry DISTINCT group IDs.

        RED ON REVERT: hoist the verify_group_id assignment above the task loop
        and all three collapse to one — task 3's verdict would overwrite task 1's.
        """
        verify_ids = _collect_notify_group_ids( self._drive( 3 ), "verified" )

        assert len( verify_ids ) == 3, f"expected one verified notify per task, got {verify_ids}"
        assert len( set( verify_ids ) ) == 3, (
            "each task's verification cycle must open its OWN group so one task's "
            f"result does not overwrite another's; got {verify_ids}"
        )
        for pg in verify_ids: assert_valid_pg_id( pg )

    def test_verification_ids_never_collide_with_the_delegation_id( self ):
        """A verification group is never the delegation group."""
        notify        = self._drive( 2 )
        delegation_id = set( _collect_notify_group_ids( notify, "Delegating task" ) )
        verify_ids    = set( _collect_notify_group_ids( notify, "verified" ) )

        assert delegation_id and verify_ids
        assert delegation_id.isdisjoint( verify_ids ), (
            "a verification notification landing in the delegation group would "
            f"overwrite the running delegation status line; shared={delegation_id & verify_ids}"
        )


# =============================================================================
# Phase 4B/4C/4D: SWE Team — one group ID per SDK stream
# =============================================================================


def _run_stream( method_name, call_args, result_message_count=3 ):
    """
    Drive one orchestrator SDK-stream method with sdk_query stubbed.

    _delegate_task / _verify_result / _redelegate_with_feedback each open a stream
    and forward every ResultMessage in it through notification_hook. The rule is
    the same for all three: every message in ONE stream shares ONE group ID, and a
    second stream gets a different one. Returns the IDs that reached the hook.
    """
    import cosa.agents.swe_team.orchestrator as orch_mod
    from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
    from cosa.agents.swe_team.config import SweTeamConfig

    messages = [ MagicMock( spec=orch_mod.ResultMessage ) for _ in range( result_message_count ) ]

    async def _stream( *a, **kw ):
        for m in messages: yield m

    orch = SweTeamOrchestrator(
        task_description = "Build X",
        config           = SweTeamConfig( trust_mode="disabled" ),
        job_id           = "swe-pg",
    )
    hook = AsyncMock()
    with patch.object( orch_mod, "sdk_query", _stream ), \
         patch.object( orch, "_build_agent_options", return_value=MagicMock() ), \
         patch.object( orch, "_emit_state", AsyncMock() ), \
         patch.object( orch, "_notify", AsyncMock() ), \
         patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
         patch.object( orch_mod, "notification_hook", hook ):
        asyncio.run( getattr( orch, method_name )( *call_args ) )
    return _collect_hook_group_ids( hook )


def _spec():
    from cosa.agents.swe_team.state import TaskSpec
    return TaskSpec( title="impl", objective="o", output_format="f" )


def _coder_result( status="success" ):
    from cosa.agents.swe_team.state import DelegationResult
    return DelegationResult( task_index=0, task_title="impl", status=status,
                             output="prev", files_changed=[ "a.py" ] )


def _assert_one_group_per_stream( ids, method_name ):
    assert len( ids ) == 3, f"{method_name}: expected 3 forwarded messages, got {ids}"
    assert len( set( ids ) ) == 1, (
        f"{method_name}: every message in one stream must share one group ID so the "
        f"UI updates one line in place instead of appending three; got {ids}"
    )
    assert_valid_pg_id( ids[ 0 ] )


class TestSweTeamCoderStreamGroupId:
    """_delegate_task groups its whole coder stream under one ID."""

    def test_every_coder_message_shares_one_group_id( self ):
        """RED ON REVERT: generate the ID inside the message loop, or pass None."""
        _assert_one_group_per_stream(
            _run_stream( "_delegate_task", ( _spec(), 0, MagicMock() ) ), "_delegate_task"
        )

    def test_two_delegations_do_not_share_a_group_id( self ):
        """A second task opens its OWN group — not the first task's.

        RED ON REVERT: hoist coder_group_id to a module constant.
        """
        first  = _run_stream( "_delegate_task", ( _spec(), 0, MagicMock() ), result_message_count=1 )
        second = _run_stream( "_delegate_task", ( _spec(), 1, MagicMock() ), result_message_count=1 )
        assert first[ 0 ] != second[ 0 ], (
            "two coder streams sharing a group ID would make the second task's output "
            f"overwrite the first's; both were {first[ 0 ]}"
        )


class TestSweTeamTesterStreamGroupId:
    """_verify_result groups its whole tester stream under one ID."""

    def test_every_tester_message_shares_one_group_id( self ):
        _assert_one_group_per_stream(
            _run_stream( "_verify_result", ( _spec(), _coder_result(), 0, MagicMock() ) ),
            "_verify_result",
        )

    def test_tester_group_is_not_the_coder_group( self ):
        """The tester stream never reuses a coder stream's group."""
        coder  = _run_stream( "_delegate_task", ( _spec(), 0, MagicMock() ), result_message_count=1 )
        tester = _run_stream( "_verify_result", ( _spec(), _coder_result(), 0, MagicMock() ),
                              result_message_count=1 )
        assert coder[ 0 ] != tester[ 0 ], (
            "the tester's output would overwrite the coder's in the same DOM slot; "
            f"both were {coder[ 0 ]}"
        )


class TestSweTeamRedelegateGroupId:
    """_redelegate_with_feedback groups its retry stream under one ID."""

    def test_every_redelegate_message_shares_one_group_id( self ):
        _assert_one_group_per_stream(
            _run_stream( "_redelegate_with_feedback",
                         ( _spec(), 0, _coder_result( "failure" ), "feedback", 2, MagicMock() ) ),
            "_redelegate_with_feedback",
        )

    def test_each_retry_opens_a_fresh_group( self ):
        """Two retries of the same task do not share a group ID."""
        one = _run_stream( "_redelegate_with_feedback",
                           ( _spec(), 0, _coder_result( "failure" ), "fb", 2, MagicMock() ),
                           result_message_count=1 )
        two = _run_stream( "_redelegate_with_feedback",
                           ( _spec(), 0, _coder_result( "failure" ), "fb", 3, MagicMock() ),
                           result_message_count=1 )
        assert one[ 0 ] != two[ 0 ], (
            "retry 3 landing in retry 2's group would overwrite the earlier attempt's "
            f"output; both were {one[ 0 ]}"
        )


# =============================================================================
# Deep Research and Podcast tags — MOVED OUT (row 122f07a1)
# =============================================================================
#
# The twelve source-text assertions that lived here (TestDeepResearchGroupId and
# TestPodcastGeneratorOrchestratorGroupIds) are gone, replaced by tests that DRIVE
# those pipelines and read the tags that actually reach the notification seam.
# They now live beside the harnesses that can run them, because this file has no
# way to reach either pipeline:
#
#   Deep Research  -> src/cosa/tests/unit/agents/deep_research/test_cli.py
#                     ::TestSubqueryLoopProgressGroup   (rr_env is the harness)
#   Podcast        -> src/tests/unit/test_podcast_orchestrator.py
#                     ::TestAudioProgressGroupTags      (_wire_pipeline is the harness)
#
# The podcast set also covers the `_audio_progress_group_id` attribute that a grep
# here used to look for in __init__: a run that never opens a tag now fails by
# name rather than by the word being absent from a constructor.


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
