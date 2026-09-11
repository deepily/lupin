#!/usr/bin/env python3
"""
Rick's tick-box topic confirm for a deep-research run over a local document.
Row b6cfbf8d; silence-means-cancel is option A, pending his decision row f8fddc8b.

THE SEAMS, each driven by its real collaborator (slice 1 died at an unguarded one):

    factory  ->  DeepResearchJob  ->  run_research  ->  voice_io.select_*  ->  research loop

    · the REAL factory turns the switch on for a document run and off otherwise
    · the REAL job hands the switch and the document name to run_research
    · the REAL run_research asks with tick-boxes and only ticked topics reach research
    · the REAL voice_io resolves "no answer" and "answered, ticked nothing" to cancel

Only the edges are faked: the LLM client, the dispatcher behind present_choices, the
search cache, and outbound notifications.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_COMMAND = "agent router go to deep research"

_FOUR_TOPICS = [
    { "topic": "Alpha history",  "objective": "a" },
    { "topic": "Beta economics", "objective": "b" },
    { "topic": "Gamma policy",   "objective": "c" },
    { "topic": "Delta outlook",  "objective": "d" },
]


# =============================================================================
# Seam 1 — the factory
# =============================================================================

def _factory_job( args_dict ):
    from cosa.rest.agentic_job_factory import create_agentic_job
    return create_agentic_job(
        command    = _COMMAND,
        args_dict  = dict( query="what changed", **args_dict ),
        user_id    = "uid-1",
        user_email = "test@lupin",
        session_id = "sess-1",
    )


def test_the_REAL_factory_turns_topic_confirm_ON_for_a_document_run():
    job = _factory_job( { "source_document": [ "/tmp/notes.md" ] } )
    assert job.confirm_topics is True
    assert job.source_document == [ "/tmp/notes.md" ], "the document must still reach the job"
    assert job.no_confirm is True, "confirm_topics must not be done by turning clarification back on"


@pytest.mark.parametrize( "args_dict", [ {}, { "source_document": [] }, { "source_document": None } ] )
def test_the_REAL_factory_leaves_topic_confirm_OFF_without_a_document( args_dict ):
    assert _factory_job( args_dict ).confirm_topics is False


# =============================================================================
# Seam 2 — the job hands the switch to run_research
# =============================================================================

@pytest.mark.asyncio
async def test_the_REAL_job_passes_confirm_topics_and_the_document_name_to_run_research( tmp_path ):
    from cosa.agents.deep_research.job import DeepResearchJob

    ( tmp_path / "quarterly-notes.md" ).write_text( "notes" )
    ( tmp_path / "memo.txt" ).write_text( "memo" )
    job = DeepResearchJob(
        query           = "what changed",
        user_id         = "uid-1",
        user_email      = "test@lupin",
        session_id      = "sess-1",
        source_document = [ str( tmp_path / "quarterly-notes.md" ), str( tmp_path / "memo.txt" ) ],
        confirm_topics  = True,
    )
    fake_run = AsyncMock( return_value=None )
    gister   = MagicMock()
    gister.return_value.get_gist.return_value = "quarterly notes"

    with patch( "cosa.agents.deep_research.cli.run_research", fake_run ), \
         patch( "cosa.memory.gister.Gister", gister ), \
         patch( "cosa.agents.deep_research.voice_io.notify", AsyncMock() ):
        await job._execute()

    kwargs = fake_run.call_args.kwargs
    assert kwargs[ "confirm_topics" ] is True
    assert kwargs[ "topic_source" ] == "quarterly-notes.md, memo.txt"


# =============================================================================
# Seams 3 + 4 — run_research asks, voice_io resolves, research sees the result
# =============================================================================

class _FakeAPIClient:
    """The LLM edge. Plans N topics, clusters them into themes, stops at synthesis."""

    def __init__( self, topics, themes ):
        self.topics    = topics
        self.themes    = themes
        self.call_types = []

    async def call_with_json_output( self, system_prompt, user_message, call_type ):
        self.call_types.append( call_type )
        if call_type == "clarification":    return { "needs_clarification": True, "question": "Which era?", "options": [ "old", "new" ] }
        if call_type == "planning":         return { "complexity": "moderate", "subqueries": self.topics }
        if call_type == "theme_clustering": return { "themes": self.themes }
        raise _StopAfterResearch()

    async def call_subagent( self, **kwargs ):
        raise AssertionError( "a cached topic must not reach the paid subagent call" )

    def get_rate_limiter( self ):
        return MagicMock( **{ "estimate_total_time.return_value": 0 } )

    async def close( self ):
        pass

    def __getattr__( self, name ):
        # Anything else is past the research loop (synthesis): stop there.
        raise _StopAfterResearch()


class _StopAfterResearch( Exception ):
    """Raised past the research loop — the test has what it needs by then."""


@pytest.fixture
def harness():
    """
    Put the REAL core voice_io into voice mode with a stub dispatcher, fake the LLM
    and the search cache, and record which topics reach the research loop.
    """
    from cosa.agents.utils import voice_io as core
    from cosa.agents.deep_research import cli

    saved = ( core._cosa_interface, core._voice_available, core._force_cli_mode, core._job_id )

    class H:
        researched = []
        notices    = []
        asks       = []

        @classmethod
        def dispatcher( cls, **kw ):
            iface = type( "I", (), {} )()
            async def present_choices( questions, timeout, job_id=None ):
                cls.asks.append( { "questions": questions, "timeout": timeout, "job_id": job_id } )
                if "raises" in kw: raise kw[ "raises" ]
                return kw[ "returns" ]( questions )
            iface.present_choices  = present_choices
            core._cosa_interface   = iface
            core._voice_available  = True
            core._force_cli_mode   = False
            core._job_id           = "dr-test1234"

        @classmethod
        async def run( cls, topics, themes=None, **run_kw ):
            api = _FakeAPIClient( topics, themes or [] )

            def cached( user_email, topic ):
                cls.researched.append( topic )
                return { "results": { "content": "x", "tokens": 1 } }

            async def notify( message, **kw ):
                cls.notices.append( message )

            with patch.object( cli, "ResearchAPIClient", lambda **kw: api ), \
                 patch.object( cli.search_cache, "load_cached_result", cached ), \
                 patch.object( cli.voice_io, "notify", notify ):
                try:
                    result = await cli.run_research(
                        query="q", config=MagicMock( audience=None, audience_context=None ),
                        cost_tracker=MagicMock(), **run_kw
                    )
                except _StopAfterResearch:
                    result = "reached-synthesis"
            return result, api

    H.researched, H.notices, H.asks = [], [], []
    try:
        yield H
    finally:
        core._cosa_interface, core._voice_available, core._force_cli_mode, core._job_id = saved


def _tick( header, labels ):
    return lambda questions: { "answers": { header: labels } }


@pytest.mark.asyncio
async def test_POSITIVE_ARM_only_the_ticked_topics_reach_research( harness ):
    """Two themes, tick one; its two topics are what the research loop sees."""
    themes = [
        { "name": "Past",   "description": "p", "subquery_indices": [ 0, 1 ] },
        { "name": "Future", "description": "f", "subquery_indices": [ 2, 3 ] },
    ]
    harness.dispatcher( returns=_tick( "Themes", [ "Future" ] ) )
    result, api = await harness.run(
        _FOUR_TOPICS, themes, no_confirm=True, confirm_topics=True, topic_source="notes.md"
    )
    assert harness.researched == [ "Gamma policy", "Delta outlook" ]
    assert result == "reached-synthesis"


@pytest.mark.asyncio
async def test_the_ask_names_the_document_waits_ten_minutes_and_routes_to_the_job_card( harness ):
    themes = [
        { "name": "Past",   "description": "p", "subquery_indices": [ 0, 1 ] },
        { "name": "Future", "description": "f", "subquery_indices": [ 2, 3 ] },
    ]
    harness.dispatcher( returns=_tick( "Themes", [ "Past" ] ) )
    await harness.run( _FOUR_TOPICS, themes, no_confirm=True, confirm_topics=True, topic_source="notes.md" )
    ask = harness.asks[ 0 ]
    assert ask[ "questions" ][ 0 ][ "question" ].startswith( "Themes drawn from notes.md." )
    assert ask[ "questions" ][ 0 ][ "multiSelect" ] is True
    assert ask[ "timeout" ] == 600
    assert ask[ "job_id" ] == "dr-test1234", "the tick-box card must land on the job's card, like every other ask"


@pytest.mark.asyncio
async def test_a_two_topic_document_plan_gets_TICK_BOXES_not_the_plan_yes_no( harness ):
    harness.dispatcher( returns=_tick( "Topics", [ "Beta economics" ] ) )
    with patch( "cosa.agents.utils.voice_io.ask_yes_no", AsyncMock( side_effect=AssertionError( "yes/no asked" ) ) ):
        await harness.run( _FOUR_TOPICS[ :2 ], no_confirm=True, confirm_topics=True, topic_source="notes.md" )
    assert harness.asks[ 0 ][ "questions" ][ 0 ][ "header" ] == "Topics"
    assert harness.researched == [ "Beta economics" ]


@pytest.mark.asyncio
async def test_NO_ANSWER_before_the_timeout_cancels_with_no_research_spend( harness ):
    """Mr. Radio's path 1: the dispatcher's timeout resolves to the declared default []."""
    from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
    harness.dispatcher( raises=VoiceGateTimeoutError( phase="choices", message="timed out", delivered=True ) )
    result, api = await harness.run( _FOUR_TOPICS[ :2 ], no_confirm=True, confirm_topics=True )
    assert result is None
    assert harness.researched == []
    assert "No topics were ticked, so the research is cancelled and nothing was spent." in harness.notices
    assert not any( "selection failed" in n.lower() for n in harness.notices ), "silence is not a failure"


@pytest.mark.asyncio
async def test_ANSWERED_BUT_TICKED_NOTHING_cancels_with_no_research_spend( harness ):
    """Mr. Radio's path 2: a reply with no Topics header resolves via _DEFAULT_SOURCE_NO_SELECTION."""
    harness.dispatcher( returns=lambda questions: { "answers": {} } )
    result, api = await harness.run( _FOUR_TOPICS[ :2 ], no_confirm=True, confirm_topics=True )
    assert result is None
    assert harness.researched == []
    assert "No topics were ticked, so the research is cancelled and nothing was spent." in harness.notices


@pytest.mark.asyncio
async def test_a_document_run_does_NOT_ask_the_clarification_question( harness ):
    harness.dispatcher( returns=_tick( "Topics", [ "Alpha history" ] ) )
    with patch( "cosa.agents.utils.voice_io.choose", AsyncMock( side_effect=AssertionError( "clarification asked" ) ) ):
        await harness.run( _FOUR_TOPICS[ :2 ], no_confirm=True, confirm_topics=True )
    assert [ a[ "questions" ][ 0 ][ "header" ] for a in harness.asks ] == [ "Topics" ]


@pytest.mark.asyncio
async def test_REGRESSION_a_run_without_a_document_asks_nothing_and_researches_everything( harness ):
    harness.dispatcher( returns=lambda questions: pytest.fail( "a queued run without a document must not ask" ) )
    await harness.run( _FOUR_TOPICS, no_confirm=True, confirm_topics=False )
    assert harness.asks == []
    assert harness.researched == [ t[ "topic" ] for t in _FOUR_TOPICS ]


# =============================================================================
# The import hazard found while building this
# =============================================================================

def test_the_timeout_check_does_not_import_the_package_that_rebinds_voice_io():
    """
    Importing cosa.agents.test_fix_expediter runs its __init__, which pulls in swe_team
    and rebinds voice_io._cosa_interface to swe_team's module (no present_choices). The
    gates used to import it inside the call, so the first ask in a fresh process broke
    itself. _is_gate_timeout must answer without importing anything.
    """
    from cosa.agents.utils import voice_io as core
    saved = sys.modules.pop( "cosa.agents.test_fix_expediter.state", None )
    try:
        assert core._is_gate_timeout( RuntimeError( "x" ) ) is False
        assert "cosa.agents.test_fix_expediter.state" not in sys.modules
    finally:
        if saved is not None: sys.modules[ "cosa.agents.test_fix_expediter.state" ] = saved


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
