#!/usr/bin/env python3
"""
Behaviour of do_all on the four agentic jobs that bridge to an async _execute.

The same checks run on each class, so they hold across the move of the shared
body into the base class. The strings are the ones the jobs printed and stored
before the move.
"""

import re
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.claude_code.job import ClaudeCodeJob
from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob
from cosa.agents.swe_team.job import SweTeamJob
from cosa.rest.job_state import JobState

COMMON = dict( user_id="u1", user_email="e@x.com", session_id="s1" )

# class, constructor arguments, class name in the logs, text before the error in the stored answer
CASES = [
    ( ClaudeCodeJob, dict( prompt="Run the tests", project="lupin" ), "ClaudeCodeJob", "Claude Code task failed" ),
    ( DeepResearchToPodcastJob, dict( query="Run the tests" ), "DeepResearchToPodcastJob", "Research→Podcast pipeline failed" ),
    ( DeepResearchToPresentationJob, dict( query="Run the tests" ), "DeepResearchToPresentationJob", "Research→Presentation pipeline failed" ),
    ( SweTeamJob, dict( task="Run the tests" ), "SweTeamJob", "SWE Team task failed" ),
]
IDS = [ c[ 2 ] for c in CASES ]


def _job( cls, kwargs, debug ):
    """Build a job of one of the four classes."""
    return cls( **kwargs, **COMMON, debug=debug )


@pytest.mark.parametrize( "cls, kwargs, label, failure", CASES, ids=IDS )
def test_success_debug_prints_and_stores_the_result( cls, kwargs, label, failure, capsys ):
    """A good run ends completed, stores the answer in both fields, and logs start and duration."""
    job = _job( cls, kwargs, True )
    with patch.object( job, "_execute", AsyncMock( return_value="ANSWER" ) ):
        out = job.do_all()
    assert out == "ANSWER"
    assert ( job.state, job.result, job.answer_conversational ) == ( JobState.COMPLETED, "ANSWER", "ANSWER" )
    assert job.started_at is not None and job.completed_at is not None
    lines = [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[" )  ]
    assert lines[ 0 ] == f"[{label}] Starting do_all() for: Run the tests..."
    assert re.fullmatch( rf"\[{label}\] Completed in \d+\.\ds", lines[ 1 ] )
    assert len( lines ) == 2


@pytest.mark.parametrize( "cls, kwargs, label, failure", CASES, ids=IDS )
def test_success_without_debug_is_quiet( cls, kwargs, label, failure, capsys ):
    """With debug off a good run prints nothing."""
    job = _job( cls, kwargs, False )
    with patch.object( job, "_execute", AsyncMock( return_value="A" ) ):
        job.do_all()
    assert [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[" ) ] == []


@pytest.mark.parametrize( "cls, kwargs, label, failure", CASES, ids=IDS )
def test_failure_marks_failed_and_reraises( cls, kwargs, label, failure, capsys ):
    """A failed run records the error, sets the stored answer, logs a traceback and re-raises."""
    job = _job( cls, kwargs, True )
    with patch.object( job, "_execute", AsyncMock( side_effect=RuntimeError( "kaboom" ) ) ):
        with pytest.raises( RuntimeError, match="kaboom" ):
            job.do_all()
    assert job.state == JobState.FAILED
    assert job.error == "kaboom"
    assert job.answer_conversational == f"{failure}: kaboom"
    assert job.completed_at is not None
    assert job.result is None
    captured = capsys.readouterr()
    assert f"[{label}] Failed: kaboom" in captured.out.splitlines()
    assert "RuntimeError: kaboom" in captured.err


@pytest.mark.parametrize( "cls, kwargs, label, failure", CASES, ids=IDS )
def test_failure_without_debug_is_quiet( cls, kwargs, label, failure, capsys ):
    """With debug off a failed run still sets state and re-raises, and prints nothing."""
    job = _job( cls, kwargs, False )
    with patch.object( job, "_execute", AsyncMock( side_effect=ValueError( "x" ) ) ):
        with pytest.raises( ValueError ):
            job.do_all()
    assert job.state == JobState.FAILED
    assert [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[" ) ] == []


@pytest.mark.parametrize( "cls, kwargs, label, failure", CASES, ids=IDS )
def test_state_is_running_while_execute_runs( cls, kwargs, label, failure ):
    """The job reports the running state, with a start time, from inside _execute."""
    job  = _job( cls, kwargs, False )
    seen = []

    async def probe():
        seen.append( ( job.state, job.started_at, job.completed_at ) )
        return "R"

    with patch.object( job, "_execute", probe ):
        job.do_all()
    assert seen[ 0 ][ 0 ] == JobState.RUNNING
    assert seen[ 0 ][ 1 ] is not None and seen[ 0 ][ 2 ] is None
