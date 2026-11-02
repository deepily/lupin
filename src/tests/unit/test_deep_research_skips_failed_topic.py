#!/usr/bin/env python3
"""
A research topic whose call fails is a gap in the report, not the end of the run.

Job rp-82d10201 lost seven finished topics when topic 8 hit error_max_turns. The real run_research
and the real raise_error_result run here. Only the LLM client, the search cache and notifications
are faked.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.deep_research import cli
from cosa.agents.deep_research.config import ResearchConfig
from cosa.agents.deep_research.cost_tracker import BudgetExceededError
from cosa.agents.shared.sdk_error_result import LOGIN_HINT, raise_error_result


_TOPICS = [ { "topic": f"Topic {n}", "objective": "o" } for n in range( 1, 5 ) ]

_MAX_TURNS = SimpleNamespace(
    subtype="error_max_turns", result=None, errors=[ "Reached maximum number of turns (20)" ] )
_LOGIN     = SimpleNamespace( subtype="error_during_execution", result="API Error: 401 bad token", errors=[] )


def _error_result( message ):
    """Build the exception the SDK path raises, using the shipped helper."""
    try:
        raise_error_result( message, "ResearchAPIClient research", MagicMock() )
    except RuntimeError as e:
        return e


class _Client:
    """Fake client: plans _TOPICS, and answers each topic from `outcomes`."""

    def __init__( self, outcomes ):
        self.outcomes = outcomes
        self.researched = []
        self.closed = False

    async def call_with_json_output( self, system_prompt, user_message, call_type ):
        if call_type == "clarification": return { "needs_clarification": False }
        if call_type == "planning": return { "complexity": "moderate", "subqueries": _TOPICS }
        raise AssertionError( f"unexpected {call_type}" )

    async def call_subagent( self, **kw ):
        i = kw[ "subquery_index" ]
        self.researched.append( i )
        outcome = self.outcomes[ i ]
        if isinstance( outcome, BaseException ): raise outcome
        return SimpleNamespace( content=outcome, input_tokens=5 )

    async def call_lead_agent( self, **kw ):
        return SimpleNamespace( content="# Report\n\nBody." )

    def get_rate_limiter( self ):
        return MagicMock( **{ "estimate_total_time.return_value": 0, "get_estimated_wait_for_next_call.return_value": 0 } )

    async def close( self ):
        self.closed = True


async def _run( outcomes, **kw ):
    client  = _Client( outcomes )
    notices = []

    async def notify( message, **k ):
        notices.append( ( message, k.get( "priority" ) ) )

    with patch.object( cli, "ResearchAPIClient", lambda **k: client ), \
         patch.object( cli.search_cache, "load_cached_result", lambda *a: None ), \
         patch.object( cli.search_cache, "save_to_cache", lambda *a: None ), \
         patch.object( cli.voice_io, "notify", notify ):
        try:
            result = await cli.run_research( query="q", config=ResearchConfig(), cost_tracker=MagicMock(), no_confirm=True, **kw )
        except BaseException as e:
            return e, client, notices
    return result, client, notices


@pytest.mark.asyncio
async def test_topic_that_hits_max_turns_is_skipped_and_the_rest_are_researched_and_named():
    gap = _error_result( _MAX_TURNS )
    skipped = []
    report, client, notices = await _run( [ "a", "b", "c", gap ], skipped_topics=skipped )
    assert client.researched == [ 0, 1, 2, 3 ], "the failing topic is the last; the first three were researched"
    assert [ g[ "topic" ] for g in skipped ] == [ "Topic 4" ]
    assert "error_max_turns" in skipped[ 0 ][ "reason" ]
    assert report.startswith( "# Report" ) and "## Skipped topics" in report and "- **Topic 4**: " in report
    assert ( "1 of 4 topics were skipped: Topic 4", "high" ) in notices
    assert client.closed


@pytest.mark.asyncio
async def test_a_failure_in_the_MIDDLE_does_not_stop_the_topics_after_it():
    skipped = []
    report, client, _ = await _run( [ "a", _error_result( _MAX_TURNS ), "c", "d" ], skipped_topics=skipped )
    assert client.researched == [ 0, 1, 2, 3 ]
    assert [ g[ "topic" ] for g in skipped ] == [ "Topic 2" ]
    assert report.count( "- **Topic" ) == 1


@pytest.mark.asyncio
async def test_without_a_caller_list_the_gap_still_reaches_the_report():
    report, _, _ = await _run( [ "a", "b", "c", _error_result( _MAX_TURNS ) ] )
    assert "## Skipped topics" in report and "Topic 4" in report


@pytest.mark.asyncio
async def test_no_failure_means_no_skipped_section_and_an_empty_caller_list():
    skipped = []
    report, _, notices = await _run( [ "a", "b", "c", "d" ], skipped_topics=skipped )
    assert skipped == [] and "Skipped topics" not in report
    assert not any( "skipped" in m for m, _ in notices )


@pytest.mark.asyncio
async def test_ALL_topics_failing_fails_the_job():
    skipped = []
    result, client, _ = await _run( [ _error_result( _MAX_TURNS ) ] * 4, skipped_topics=skipped )
    assert isinstance( result, RuntimeError ) and "failed for all 4 topics" in str( result ) and "error_max_turns" in str( result )
    assert len( skipped ) == 4 and client.closed


@pytest.mark.asyncio
async def test_a_login_expiry_aborts_instead_of_becoming_a_gap():
    result, client, _ = await _run( [ "a", _error_result( _LOGIN ), "c", "d" ] )
    assert isinstance( result, RuntimeError ) and LOGIN_HINT in str( result )
    assert client.researched == [ 0, 1 ], "no further topic is tried once the login is dead"


@pytest.mark.asyncio
async def test_a_budget_stop_is_not_a_gap():
    result, client, _ = await _run( [ "a", BudgetExceededError( "over", 2.0, 1.0 ), "c", "d" ] )
    assert isinstance( result, BudgetExceededError )
    assert client.researched == [ 0, 1 ]


def test_the_section_lists_every_topic_with_its_reason():
    text = cli.skipped_topics_section( [ { "topic": "A", "reason": "r1" }, { "topic": "B", "reason": "r2" } ] )
    assert "## Skipped topics" in text and "- **A**: r1\n- **B**: r2\n" in text


# =============================================================================
# Wiring — the gaps reach the artifacts and the cards of both callers
# =============================================================================

_GAPS = [ { "topic": "Alpha", "reason": "error_max_turns" }, { "topic": "Beta", "reason": "error_max_turns" } ]


async def _fake_run_research( **kw ):
    """Fill the caller's list the way the shipped function does."""
    kw[ "skipped_topics" ].extend( _GAPS )
    return "# Report"


def _summary():
    return SimpleNamespace( total_cost_usd=0.5, total_input_tokens=10, total_output_tokens=5, duration_seconds=2.0 )


@pytest.mark.asyncio
async def test_the_chained_agents_research_leg_returns_the_gaps_in_its_artifacts():
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    agent = DeepResearchToPodcastAgent( query="q", user_email="u@x.com", no_confirm=True )
    gister = MagicMock()
    gister.return_value.get_gist.return_value = "a name"
    cost = MagicMock()
    cost.return_value.get_summary.return_value = _summary()
    from unittest.mock import AsyncMock
    with patch( "cosa.agents.deep_research.cli.run_research", _fake_run_research ), \
         patch( "cosa.agents.deep_research.cli.generate_abstract_for_cli", AsyncMock( return_value="abs" ) ), \
         patch( "cosa.agents.deep_research.cli.save_report_with_frontmatter", return_value="/io/r.md" ), \
         patch( "cosa.agents.deep_research.cost_tracker.CostTracker", cost ), \
         patch( "cosa.memory.gister.Gister", gister ):
        out = await agent._run_deep_research()
    assert out[ "report_path" ] == "/io/r.md" and out[ "artifacts" ][ "skipped_topics" ] == _GAPS


@pytest.mark.asyncio
async def test_the_chained_agents_checkpoint_names_the_skipped_topics_and_counts_them():
    from unittest.mock import AsyncMock
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    agent = DeepResearchToPodcastAgent( query="q", user_email="u@x.com", no_confirm=True )
    agent._notify = AsyncMock()
    agent._run_deep_research = AsyncMock( return_value={
        "report_path": "/io/r.md", "abstract": "abs", "cost": 0.5,
        "artifacts": { "skipped_topics": _GAPS, "tokens_used": 15, "duration_seconds": 2 } } )
    agent._run_podcast_generator = AsyncMock( return_value={ "audio_path": "a.mp3", "script_path": "s.md", "cost": 0.1 } )
    with patch.object( agent, "_set_modality" ):
        result = await agent.run_async()
    first = next( c for c in agent._notify.call_args_list if c.args[ 0 ].startswith( "Deep Research complete" ) )
    assert "(2 topics skipped)" in first.args[ 0 ]
    assert "**Skipped topics (2)**: Alpha; Beta" in first.kwargs[ "abstract" ]
    assert result.dr_artifacts[ "skipped_topics" ] == _GAPS and result.state.value == "completed"


@pytest.mark.asyncio
async def test_the_deep_research_job_card_names_the_skipped_topics():
    from unittest.mock import AsyncMock
    from cosa.agents.deep_research.job import DeepResearchJob
    job = DeepResearchJob( query="q", user_id="u", user_email="u@x.com", session_id="s", no_confirm=True )
    gister = MagicMock()
    gister.return_value.get_gist.return_value = "a name"
    cost = MagicMock()
    cost.return_value.get_summary.return_value = _summary()
    notify = AsyncMock()
    with patch( "cosa.agents.deep_research.cli.run_research", _fake_run_research ), \
         patch( "cosa.agents.deep_research.cli.generate_abstract_for_cli", AsyncMock( return_value="abs" ) ), \
         patch( "cosa.agents.deep_research.cli.save_report_with_frontmatter", return_value="/io/r.md" ), \
         patch( "cosa.agents.deep_research.cost_tracker.CostTracker", cost ), \
         patch( "cosa.memory.gister.Gister", gister ), \
         patch( "cosa.agents.deep_research.voice_io.notify", notify ), \
         patch( "dataclasses.asdict", return_value={} ):
        await job._execute()
    card = next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) )
    assert "**Skipped topics (2)**: Alpha; Beta" in card


@pytest.mark.asyncio
async def test_with_no_gaps_the_checkpoint_and_the_job_card_say_nothing_about_skips():
    from unittest.mock import AsyncMock
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    from cosa.agents.deep_research.job import DeepResearchJob

    agent = DeepResearchToPodcastAgent( query="q", user_email="u@x.com", no_confirm=True )
    agent._notify = AsyncMock()
    agent._run_deep_research = AsyncMock( return_value={
        "report_path": "/io/r.md", "abstract": "abs", "cost": 0.5,
        "artifacts": { "skipped_topics": [], "tokens_used": 15, "duration_seconds": 2 } } )
    agent._run_podcast_generator = AsyncMock( return_value={ "audio_path": "a.mp3", "script_path": "s.md", "cost": 0.1 } )
    with patch.object( agent, "_set_modality" ):
        await agent.run_async()
    first = next( c for c in agent._notify.call_args_list if c.args[ 0 ].startswith( "Deep Research complete" ) )
    assert "skipped" not in first.args[ 0 ] and "Skipped" not in first.kwargs[ "abstract" ]

    async def no_gaps( **kw ): return "# Report"
    job = DeepResearchJob( query="q", user_id="u", user_email="u@x.com", session_id="s", no_confirm=True )
    gister = MagicMock()
    gister.return_value.get_gist.return_value = "a name"
    cost = MagicMock()
    cost.return_value.get_summary.return_value = _summary()
    notify = AsyncMock()
    with patch( "cosa.agents.deep_research.cli.run_research", no_gaps ), \
         patch( "cosa.agents.deep_research.cli.generate_abstract_for_cli", AsyncMock( return_value="abs" ) ), \
         patch( "cosa.agents.deep_research.cli.save_report_with_frontmatter", return_value="/io/r.md" ), \
         patch( "cosa.agents.deep_research.cost_tracker.CostTracker", cost ), \
         patch( "cosa.memory.gister.Gister", gister ), \
         patch( "cosa.agents.deep_research.voice_io.notify", notify ), \
         patch( "dataclasses.asdict", return_value={} ):
        await job._execute()
    card = next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) )
    assert "Skipped" not in card
