#!/usr/bin/env python3
"""
Unit tests for cosa.agents.deep_research_to_podcast.job

Target: DeepResearchToPodcastJob — the queue-executable wrapper around the
chained DR -> Podcast pipeline. AgenticJobBase.__init__ is self-contained
(no network / config), so the job is instantiated directly; the pipeline
agent, the deep_research voice_io/cosa_interface modules, and asyncio.sleep
are all mocked at the boundary so NO real LLM / SDK / network / sleep occurs.

Strategy:
    - __init__ / last_question_asked: exercised directly
    - do_all: self._execute patched -> success + failure (re-raise) branches
    - _execute: fake deep_research module + fake agent module; real
      PipelineState enum drives COMPLETED / CANCELLED / FAILED branches;
      finally-clause job_id clearing verified
    - _execute_dry_run: fake voice_io/cosa_interface + patched asyncio.sleep;
      all breadcrumbs + mock artifacts asserted

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import sys
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
from cosa.agents.deep_research_to_podcast.state import PipelineState, ChainedResult
from cosa.rest.job_state import JobState


def _make_module( name, **attrs ):
    mod = types.ModuleType( name )
    for key, value in attrs.items():
        setattr( mod, key, value )
    return mod


def _run( coro ):
    return asyncio.run( coro )


def _job( **kw ):
    defaults = dict( query="quantum", user_id="u1", user_email="u@test.com", session_id="s1" )
    defaults.update( kw )
    return DeepResearchToPodcastJob( **defaults )


# ----------------------------------------------------------------------------
# __init__ + last_question_asked
# ----------------------------------------------------------------------------
class TestInitAndDisplay:
    """
    Construction + display-string contract.

    Ensures:
        - JOB_TYPE / JOB_PREFIX class constants are pinned
        - id_hash carries the rp- prefix (via AgenticJobBase)
        - pipeline params stored; target_languages defaults to ["en"]
        - result fields start as None; state PENDING
        - last_question_asked renders the [Research->Podcast] prefix
    """

    def test_class_constants( self ):
        assert DeepResearchToPodcastJob.JOB_TYPE   == "research_to_podcast"
        assert DeepResearchToPodcastJob.JOB_PREFIX == "rp"

    def test_stores_params_and_defaults( self ):
        job = _job( budget=2.0, max_segments=4, dry_run=True,
                    audience="expert", audience_context="phds", verbose=True )
        assert job.id_hash.startswith( "rp-" )
        assert job.query            == "quantum"
        assert job.budget           == 2.0
        assert job.target_languages == [ "en" ]          # default
        assert job.max_segments     == 4
        assert job.dry_run          is True
        assert job.audience         == "expert"
        assert job.audience_context == "phds"
        assert job.verbose          is True
        assert job.research_path is None
        assert job.audio_path    is None
        assert job.script_path   is None
        assert job.cost_summary  is None
        assert job.state == JobState.PENDING

    def test_explicit_target_languages_passthrough( self ):
        job = _job( target_languages=[ "es" ] )
        assert job.target_languages == [ "es" ]

    def test_last_question_asked( self ):
        job = _job( query="state of AI" )
        assert job.last_question_asked == "[Research→Podcast] state of AI"


# ----------------------------------------------------------------------------
# do_all (success / failure) with _execute patched
# ----------------------------------------------------------------------------
class TestDoAll:
    """
    do_all bridges to async _execute via asyncio.run and manages job state.

    Ensures:
        - success: state COMPLETED, result + answer_conversational set, returns answer
        - failure: state FAILED, error captured, conversational error set, re-raises
        - debug=True prints start/duration (success) and traceback (failure)
    """

    def test_success_sets_completed_state( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( return_value="ANSWER" ) ):
            out = job.do_all()
        assert out == "ANSWER"
        assert job.state == JobState.COMPLETED
        assert job.result == "ANSWER"
        assert job.answer_conversational == "ANSWER"
        assert job.started_at   is not None
        assert job.completed_at is not None
        printed = capsys.readouterr().out
        assert "Starting do_all()" in printed
        assert "Completed in"      in printed

    def test_success_debug_false_is_quiet( self, capsys ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( return_value="A" ) ):
            job.do_all()
        assert capsys.readouterr().out == ""

    def test_failure_sets_failed_and_reraises( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( side_effect=RuntimeError( "kaboom" ) ) ):
            with pytest.raises( RuntimeError, match="kaboom" ):
                job.do_all()
        assert job.state == JobState.FAILED
        assert job.error == "kaboom"
        assert job.answer_conversational == "Research→Podcast pipeline failed: kaboom"
        assert job.completed_at is not None
        assert "Failed: kaboom" in capsys.readouterr().out

    def test_failure_debug_false_no_traceback( self ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( side_effect=ValueError( "x" ) ) ):
            with pytest.raises( ValueError ):
                job.do_all()
        assert job.state == JobState.FAILED


# ----------------------------------------------------------------------------
# _execute (non-dry-run) — fake DR module + fake agent module, real enum
# ----------------------------------------------------------------------------
class _ExecGraph:
    """
    Installs fake deep_research + fake pipeline-agent modules for _execute.

    The agent's run_async returns a real ChainedResult so the job's
    PipelineState comparisons run against the genuine enum.
    """

    def __init__( self, result ):
        self.voice_io = MagicMock()
        self.voice_io.notify = AsyncMock()
        self.cosa_interface = MagicMock()
        self.cosa_interface._get_sender_id.return_value = "sender-id"

        agent_inst = MagicMock()
        agent_inst.run_async = AsyncMock( return_value=result )
        self.agent_ctor = MagicMock( return_value=agent_inst )

        self.modules = {
            "cosa.agents.deep_research": _make_module(
                "cosa.agents.deep_research",
                voice_io       = self.voice_io,
                cosa_interface = self.cosa_interface,
            ),
            "cosa.agents.deep_research_to_podcast.agent": _make_module(
                "cosa.agents.deep_research_to_podcast.agent",
                DeepResearchToPodcastAgent = self.agent_ctor,
            ),
        }

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestExecute:
    """
    _execute orchestration branches (non-dry-run).

    Ensures:
        - COMPLETED -> stores paths/artifacts/cost_summary, returns summary
        - CANCELLED -> cancel notify + cancellation string
        - FAILED    -> urgent notify + raised Exception(error)
        - job_id always cleared in finally (even on raise)
        - debug prints budget line (set vs unlimited)
    """

    def _completed_result( self ):
        return ChainedResult(
            research_path     = "/io/dr/r.md",
            research_abstract = "abs",
            audio_path        = "/io/pod/a.mp3",
            script_path       = "/io/pod/s.md",
            dr_cost           = 1.0,
            pg_cost           = 0.5,
            total_cost        = 1.5,
            state             = PipelineState.COMPLETED,
        )

    def test_completed_stores_results( self, capsys ):
        job   = _job( budget=2.0, debug=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher():
            out = _run( job._execute() )
        assert "Pipeline complete!" in out
        assert "$1.5000" in out
        assert job.research_path == "/io/dr/r.md"
        assert job.audio_path    == "/io/pod/a.mp3"
        assert job.script_path   == "/io/pod/s.md"
        assert job.artifacts[ "research_abstract" ] == "abs"
        assert job.cost_summary == {
            "dr_cost_usd"    : 1.0,
            "pg_cost_usd"    : 0.5,
            "total_cost_usd" : 1.5,
        }
        # boundary wiring
        assert job.cost_summary is job.artifacts[ "cost_summary" ]
        graph.voice_io.set_job_id.assert_called_once_with( job.id_hash )
        graph.voice_io.clear_job_id.assert_called_once_with()    # finally
        assert "Budget: $2.0" in capsys.readouterr().out

    def test_completed_unlimited_budget_debug_line( self, capsys ):
        job   = _job( budget=None, debug=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher():
            _run( job._execute() )
        assert "Budget: unlimited" in capsys.readouterr().out

    def test_cancelled_returns_cancel_message( self ):
        result = ChainedResult( state=PipelineState.CANCELLED )
        job    = _job()
        graph  = _ExecGraph( result )
        with graph.patcher():
            out = _run( job._execute() )
        assert out == "Research→Podcast pipeline was cancelled by the user."
        graph.voice_io.clear_job_id.assert_called_once_with()

    def test_failed_raises_with_error_message( self ):
        result = ChainedResult( state=PipelineState.FAILED, error="dr exploded" )
        job    = _job()
        graph  = _ExecGraph( result )
        with graph.patcher():
            with pytest.raises( Exception, match="dr exploded" ):
                _run( job._execute() )
        # urgent notify fired and job_id cleared despite the raise
        urgent = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "priority" ) == "urgent" ]
        assert len( urgent ) == 1
        graph.voice_io.clear_job_id.assert_called_once_with()

    def test_failed_with_none_error_uses_unknown( self ):
        result = ChainedResult( state=PipelineState.FAILED, error=None )
        job    = _job()
        graph  = _ExecGraph( result )
        with graph.patcher():
            with pytest.raises( Exception, match="Unknown error" ):
                _run( job._execute() )

    def test_dry_run_routes_to_dry_run_helper( self ):
        # dry_run=True must short-circuit to _execute_dry_run before any agent build.
        job   = _job( dry_run=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher(), patch.object(
            job, "_execute_dry_run", AsyncMock( return_value="DRY" )
        ) as dry:
            out = _run( job._execute() )
        assert out == "DRY"
        dry.assert_awaited_once()
        graph.agent_ctor.assert_not_called()                 # never built the real agent


# ----------------------------------------------------------------------------
# _execute_dry_run — patched asyncio.sleep, fake voice_io/cosa_interface
# ----------------------------------------------------------------------------
class TestExecuteDryRun:
    """
    _execute_dry_run simulates the pipeline with breadcrumb notifications.

    Ensures:
        - 10 breadcrumb notifies + 1 completion notify fire (11 total)
        - asyncio.sleep is awaited 10 times (mocked — no real delay)
        - mock artifact paths + zeroed cost summary are stored
        - job_id set then cleared; returns the dry-run summary string
        - debug=True prints the DRY RUN banner
    """

    def _voice_and_iface( self ):
        voice_io = MagicMock()
        voice_io.notify = AsyncMock()
        cosa_interface = MagicMock()
        cosa_interface._get_sender_id.return_value = "sid"
        return voice_io, cosa_interface

    def test_dry_run_full_flow( self, capsys ):
        job = _job( debug=True )
        voice_io, cosa_interface = self._voice_and_iface()
        with patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( job._execute_dry_run( voice_io, cosa_interface ) )

        assert out == "Dry run complete. Research and podcast simulation finished."
        assert voice_io.notify.await_count == 11             # 10 breadcrumbs + completion
        assert slp.await_count == 10
        # mock artifacts
        assert job.research_path.endswith( "/report.md" )
        assert job.audio_path.endswith( "/podcast.mp3" )
        assert job.script_path.endswith( "/script.md" )
        assert job.artifacts[ "research_abstract" ] == "Mock abstract from dry-run mode."
        assert job.cost_summary == {
            "dr_cost_usd"    : 0.0,
            "pg_cost_usd"    : 0.0,
            "total_cost_usd" : 0.0,
        }
        voice_io.set_job_id.assert_called_once_with( job.id_hash )
        voice_io.clear_job_id.assert_called_once_with()
        assert "DRY RUN MODE" in capsys.readouterr().out

    def test_dry_run_debug_false_no_banner( self, capsys ):
        job = _job( debug=False )
        voice_io, cosa_interface = self._voice_and_iface()
        with patch( "asyncio.sleep", AsyncMock() ):
            _run( job._execute_dry_run( voice_io, cosa_interface ) )
        assert "DRY RUN MODE" not in capsys.readouterr().out
