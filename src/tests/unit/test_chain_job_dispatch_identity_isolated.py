#!/usr/bin/env python3
"""
The research-to-presentation chain addresses its notifications to its own user.

The chain job and the chain agent each set the notification target when they start.
They must also set the per-task context variables the dispatcher reads first.
Without them, a job that started later can overwrite the module globals and redirect the asks.
Each test starts with a stale user in the context variable and checks the code under test replaces it.
Only the network send and the heavy pipeline stages are replaced.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cosa.agents.deep_research import cosa_interface, voice_io
from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent
from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob
from cosa.agents.deep_research_to_presentation.state import PipelineState
from cosa.agents.utils.agent_notification_dispatcher import ctx_target_user

REAL_SLEEP = asyncio.sleep
TESTER     = "interactive.job.tester@test.com"
OTHER      = "other.user@example.com"


class _Stop( Exception ):
    """Raised by the replacement for the first call made after the context is set."""


def _job( email, dry_run=False ):
    return DeepResearchToPresentationJob(
        query      = "what is a context variable",
        user_id    = f"uid-{email}",
        user_email = email,
        session_id = f"session-{email}",
        dry_run    = dry_run,
    )


@pytest.mark.asyncio
async def test_concurrent_dry_run_chains_address_their_own_user():
    seen = []

    async def record( message, **kwargs ):
        seen.append( cosa_interface._dispatcher._resolve_target_user() )

    async def notify_via_interface( message, **kwargs ):
        await cosa_interface.notify_progress( message )

    async def quick_sleep( seconds, *a, **kw ):
        await REAL_SLEEP( 0.01 )

    job_tester = _job( TESTER, dry_run=True )
    job_other  = _job( OTHER,  dry_run=True )

    with patch.object( cosa_interface._dispatcher, "notify_progress", side_effect=record ), \
         patch.object( voice_io, "notify", side_effect=notify_via_interface ), \
         patch( "asyncio.sleep", quick_sleep ):
        t1 = asyncio.create_task( job_tester._run_chained_dry_run( voice_io, cosa_interface ) )
        await REAL_SLEEP( 0.005 )
        t2 = asyncio.create_task( job_other._run_chained_dry_run( voice_io, cosa_interface ) )
        await asyncio.gather( t1, t2 )

    assert len( seen ) > 4, "the loop must have found notifications to check"
    assert set( seen ) == { TESTER, OTHER }
    assert seen.count( TESTER ) == seen.count( OTHER )


@pytest.mark.asyncio
async def test_live_chain_job_sets_the_context_before_running_the_agent():
    seen = []

    class FakeAgent:
        async def run_async( self ):
            seen.append( ctx_target_user.get() )
            return SimpleNamespace( state=PipelineState.CANCELLED )

    job = _job( TESTER )
    ctx_target_user.set( "stale@example.com" )
    with patch.object( job, "_make_agent", return_value=FakeAgent() ), \
         patch.object( voice_io, "notify", side_effect=lambda *a, **k: asyncio.sleep( 0 ) ):
        await job._execute()

    assert seen == [ TESTER ]


@pytest.mark.asyncio
async def test_research_phase_sets_the_context_before_its_first_stage():
    seen = []

    def stop_here( *args, **kwargs ):
        seen.append( ctx_target_user.get() )
        raise _Stop()

    agent = DeepResearchToPresentationAgent( query="q", user_email=TESTER )
    ctx_target_user.set( "stale@example.com" )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=stop_here ):
        with pytest.raises( _Stop ):
            await agent._run_deep_research()

    assert seen == [ TESTER ]


@pytest.mark.asyncio
async def test_presentation_phase_sets_the_context_before_its_first_stage( tmp_path ):
    seen = []

    def stop_here( *args, **kwargs ):
        seen.append( ctx_target_user.get() )
        raise _Stop()

    report = tmp_path / "report.md"
    report.write_text( "# report\n" )
    agent = DeepResearchToPresentationAgent( query="q", user_email=TESTER )
    ctx_target_user.set( "stale@example.com" )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=stop_here ):
        with pytest.raises( _Stop ):
            await agent._run_presentation_generator( str( report ) )

    assert seen == [ TESTER ]
