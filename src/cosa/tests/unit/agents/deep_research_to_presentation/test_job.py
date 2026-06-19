#!/usr/bin/env python3
"""
Unit tests for cosa.agents.deep_research_to_presentation.job

Target: DeepResearchToPresentationJob — queue-executable wrapper around the
chained DR -> Presentation pipeline. AgenticJobBase.__init__ is self-contained,
so the job is instantiated directly; the pipeline agent, the deep_research
voice_io/cosa_interface modules, and asyncio.sleep are mocked at the boundary
so NO real LLM / SDK / network / sleep occurs.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import sys
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob
from cosa.agents.deep_research_to_presentation.state import PipelineState, ChainedResult
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
    return DeepResearchToPresentationJob( **defaults )


# ----------------------------------------------------------------------------
# __init__ + last_question_asked
# ----------------------------------------------------------------------------
class TestInitAndDisplay:
    """
    Construction + display-string contract.

    Ensures JOB_TYPE/JOB_PREFIX pinned, rx- id prefix, params stored, result
    fields None, state PENDING, and the [Research->Presentation] display prefix.
    """

    def test_class_constants( self ):
        assert DeepResearchToPresentationJob.JOB_TYPE   == "research_to_presentation"
        assert DeepResearchToPresentationJob.JOB_PREFIX == "rx"

    def test_stores_params( self ):
        job = _job( budget=2.0, target_duration_minutes=15, theme="dark",
                    lead_model="m", dry_run=True, audience="expert",
                    audience_context="phds", verbose=True )
        assert job.id_hash.startswith( "rx-" )
        assert job.query                   == "quantum"
        assert job.budget                  == 2.0
        assert job.target_duration_minutes == 15
        assert job.theme                   == "dark"
        assert job.lead_model              == "m"
        assert job.dry_run                 is True
        assert job.audience                == "expert"
        assert job.audience_context        == "phds"
        assert job.verbose                 is True
        assert job.research_path is None
        assert job.yaml_path     is None
        assert job.marp_path     is None
        assert job.cost_summary  is None
        assert job.state == JobState.PENDING

    def test_last_question_asked( self ):
        assert _job( query="state of AI" ).last_question_asked == "[Research→Presentation] state of AI"


# ----------------------------------------------------------------------------
# do_all
# ----------------------------------------------------------------------------
class TestDoAll:
    """
    do_all bridges to async _execute and manages job state.

    Ensures success -> COMPLETED + answer; failure -> FAILED + re-raise; debug
    prints start/duration (success) and the failure line.
    """

    def test_success_sets_completed( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( return_value="ANSWER" ) ):
            out = job.do_all()
        assert out == "ANSWER"
        assert job.state == JobState.COMPLETED
        assert job.result == "ANSWER"
        assert job.answer_conversational == "ANSWER"
        assert job.started_at and job.completed_at
        printed = capsys.readouterr().out
        assert "Starting do_all()" in printed
        assert "Completed in"      in printed

    def test_success_debug_false_quiet( self, capsys ):
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
        assert job.answer_conversational == "Research→Presentation pipeline failed: kaboom"
        assert "Failed: kaboom" in capsys.readouterr().out

    def test_failure_debug_false_no_traceback( self ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( side_effect=ValueError( "x" ) ) ):
            with pytest.raises( ValueError ):
                job.do_all()
        assert job.state == JobState.FAILED


# ----------------------------------------------------------------------------
# _execute (non-dry-run)
# ----------------------------------------------------------------------------
class _ExecGraph:
    """Installs fake deep_research + fake pipeline-agent modules for _execute."""

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
            "cosa.agents.deep_research_to_presentation.agent": _make_module(
                "cosa.agents.deep_research_to_presentation.agent",
                DeepResearchToPresentationAgent = self.agent_ctor,
            ),
        }

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestExecute:
    """
    _execute orchestration branches (non-dry-run).

    Ensures COMPLETED stores yaml/marp/slide_count + cost_summary; CANCELLED and
    FAILED branches; job_id cleared in finally even on raise; budget debug line
    (set vs unlimited); dry_run short-circuit.
    """

    def _completed_result( self ):
        return ChainedResult(
            research_path     = "/io/dr/r.md",
            research_abstract = "abs",
            yaml_path         = "/io/pres/d.yaml",
            marp_path         = "/io/pres/d.md",
            slide_count       = 9,
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
        assert job.yaml_path     == "/io/pres/d.yaml"
        assert job.marp_path     == "/io/pres/d.md"
        assert job.artifacts[ "research_abstract" ] == "abs"
        assert job.artifacts[ "slide_count" ]       == 9
        assert job.cost_summary == {
            "dr_cost_usd"    : 1.0,
            "pg_cost_usd"    : 0.5,
            "total_cost_usd" : 1.5,
        }
        assert job.cost_summary is job.artifacts[ "cost_summary" ]
        graph.voice_io.set_job_id.assert_called_once_with( job.id_hash )
        graph.voice_io.clear_job_id.assert_called_once_with()
        assert "Budget: $2.0" in capsys.readouterr().out

    def test_completed_unlimited_budget_debug_line( self, capsys ):
        job   = _job( budget=None, debug=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher():
            _run( job._execute() )
        assert "Budget: unlimited" in capsys.readouterr().out

    def test_cancelled_returns_message( self ):
        job   = _job()
        graph = _ExecGraph( ChainedResult( state=PipelineState.CANCELLED ) )
        with graph.patcher():
            out = _run( job._execute() )
        assert out == "Research→Presentation pipeline was cancelled by the user."
        graph.voice_io.clear_job_id.assert_called_once_with()

    def test_failed_raises_with_error( self ):
        job   = _job()
        graph = _ExecGraph( ChainedResult( state=PipelineState.FAILED, error="pg exploded" ) )
        with graph.patcher():
            with pytest.raises( Exception, match="pg exploded" ):
                _run( job._execute() )
        urgent = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "priority" ) == "urgent" ]
        assert len( urgent ) == 1
        graph.voice_io.clear_job_id.assert_called_once_with()

    def test_failed_none_error_uses_unknown( self ):
        job   = _job()
        graph = _ExecGraph( ChainedResult( state=PipelineState.FAILED, error=None ) )
        with graph.patcher():
            with pytest.raises( Exception, match="Unknown error" ):
                _run( job._execute() )

    def test_dry_run_short_circuits( self ):
        job   = _job( dry_run=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher(), patch.object(
            job, "_execute_dry_run", AsyncMock( return_value="DRY" )
        ) as dry:
            out = _run( job._execute() )
        assert out == "DRY"
        dry.assert_awaited_once()
        graph.agent_ctor.assert_not_called()


# ----------------------------------------------------------------------------
# _execute_dry_run
# ----------------------------------------------------------------------------
class TestExecuteDryRun:
    """
    _execute_dry_run simulates the pipeline with breadcrumb notifications.

    Ensures 12 breadcrumbs + 1 completion (13 notifies), 12 mocked sleeps,
    mock artifact paths + zeroed cost summary + slide_count 0, job_id set/cleared,
    and the dry-run summary string; debug=True prints the DRY RUN banner.
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
        assert out == "Dry run complete. Research and presentation simulation finished."
        assert voice_io.notify.await_count == 13            # 12 breadcrumbs + completion
        assert slp.await_count == 12
        assert job.research_path.endswith( "/report.md" )
        assert job.yaml_path.endswith( "/presentation.yaml" )
        assert job.marp_path.endswith( "/presentation.md" )
        assert job.artifacts[ "research_abstract" ] == "Mock abstract from dry-run mode."
        assert job.artifacts[ "slide_count" ] == 0
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
