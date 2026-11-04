#!/usr/bin/env python3
"""
Tests for the shared run-and-record body that agentic jobs call from do_all.

A small job class stands in for a real one, so only the base class is measured.
"""

import re

import pytest

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class _Job( AgenticJobBase ):
    """Minimal job whose _execute is set per test."""

    JOB_TYPE   = "probe"
    JOB_PREFIX = "pr"

    def __init__( self, outcome, debug=False ):
        super().__init__( user_id="u1", user_email="e@x.com", session_id="s1", debug=debug )
        self.outcome = outcome
        self.during  = None

    @property
    def last_question_asked( self ):
        return "probe"

    def do_all( self ) -> str:
        return self._run_execute( "ProbeJob", "the subject", "Probe failed" )

    async def _execute( self ) -> str:
        self.during = ( self.state, self.started_at, self.completed_at )
        if isinstance( self.outcome, Exception ): raise self.outcome
        return self.outcome


def test_success_records_state_result_and_both_answer_fields():
    """A good run ends in the completed state and the text is returned and stored twice."""
    job = _Job( "fine" )
    assert job.do_all() == "fine"
    assert ( job.state, job.result, job.answer_conversational ) == ( JobState.COMPLETED, "fine", "fine" )
    assert job.started_at is not None and job.completed_at is not None
    assert job.error is None


def test_state_is_running_with_a_start_time_inside_execute():
    """From inside _execute the job is running, started and not completed."""
    job = _Job( "fine" )
    job.do_all()
    assert job.during[ 0 ] == JobState.RUNNING
    assert job.during[ 1 ] is not None and job.during[ 2 ] is None


def test_success_debug_prints_start_then_duration( capsys ):
    """With debug on, exactly a start line and a duration line are printed."""
    _Job( "fine", debug=True ).do_all()
    lines = [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[" ) ]
    assert lines[ 0 ] == "[ProbeJob] Starting do_all() for: the subject..."
    assert re.fullmatch( r"\[ProbeJob\] Completed in \d+\.\ds", lines[ 1 ] ) and len( lines ) == 2


def test_failure_records_error_and_reraises_the_same_exception():
    """A failed run ends in the failed state, stores the error text, and raises the original."""
    boom = RuntimeError( "kaboom" )
    job  = _Job( boom )
    with pytest.raises( RuntimeError ) as exc:
        job.do_all()
    assert exc.value is boom
    assert ( job.state, job.error, job.answer_conversational ) == ( JobState.FAILED, "kaboom", "Probe failed: kaboom" )
    assert job.completed_at is not None and job.result is None


def test_failure_debug_prints_the_failure_and_a_traceback( capsys ):
    """With debug on, a failure prints a line to stdout and the traceback to stderr."""
    job = _Job( ValueError( "bad" ), debug=True )
    with pytest.raises( ValueError ):
        job.do_all()
    captured = capsys.readouterr()
    assert "[ProbeJob] Failed: bad" in captured.out.splitlines()
    assert "ValueError: bad" in captured.err


def test_debug_off_prints_nothing_on_either_path( capsys ):
    """Without debug neither a good nor a failed run prints a job line."""
    _Job( "fine" ).do_all()
    with pytest.raises( ValueError ):
        _Job( ValueError( "bad" ) ).do_all()
    captured = capsys.readouterr()
    assert [ l for l in captured.out.splitlines() if l.startswith( "[" ) ] == []
    assert captured.err == ""
