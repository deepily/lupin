#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.job

PresentationGeneratorJob — queue-executable wrapper around the presentation
orchestrator. voice_io / cosa_interface / orchestrator / config /
ConfigurationManager / filesystem / asyncio.sleep are all faked so NO real
LLM / SDK / network / disk / sleep occurs.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import sys
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator.job import PresentationGeneratorJob
from cosa.rest.job_state import JobState


def _make_module( name, **attrs ):
    mod = types.ModuleType( name )
    for k, v in attrs.items():
        setattr( mod, k, v )
    return mod


def _run( coro ):
    return asyncio.run( coro )


def _job( **kw ):
    defaults = dict(
        source_path="/io/dr/report.md", user_id="u1",
        user_email="u@test.com", session_id="s1",
    )
    defaults.update( kw )
    return PresentationGeneratorJob( **defaults )


# ===========================================================================
# __init__ / last_question_asked
# ===========================================================================
class TestInit:
    def test_class_constants( self ):
        assert PresentationGeneratorJob.JOB_TYPE   == "presentation"
        assert PresentationGeneratorJob.JOB_PREFIX == "pr"

    def test_stores_params( self ):
        job = _job( target_duration_minutes=20, audience="expert", theme="dark",
                    content_model="claude-x", render_only=True, dry_run=True,
                    force_failure_mode="code_bug", verbose=True )
        assert job.id_hash.startswith( "pr-" )
        assert job.source_path == "/io/dr/report.md"
        assert job.target_duration_minutes == 20
        assert job.audience == "expert"
        assert job.theme == "dark"
        assert job.content_model == "claude-x"
        assert job.render_only is True
        assert job.dry_run is True
        assert job.force_failure_mode == "code_bug"
        assert job.yaml_path is None and job.marp_path is None and job.cost_summary is None
        assert job.state == JobState.PENDING

    def test_lqa_presentation_prefix( self ):
        assert _job( source_path="/io/dr/topic.md" ).last_question_asked == "[Presentation] topic.md"

    def test_lqa_render_prefix( self ):
        assert _job( source_path="/io/x/deck.yaml", render_only=True ).last_question_asked == "[Render] deck.yaml"


# ===========================================================================
# do_all (sync bridge)
# ===========================================================================
class TestDoAll:
    def test_success_debug( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( return_value="ANSWER" ) ):
            out = job.do_all()
        assert out == "ANSWER"
        assert job.state == JobState.COMPLETED
        assert job.answer_conversational == "ANSWER"
        printed = capsys.readouterr().out
        assert "Starting do_all()" in printed
        assert "Completed in" in printed

    def test_success_quiet( self, capsys ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( return_value="A" ) ):
            job.do_all()
        assert capsys.readouterr().out == ""

    def test_cancel_with_result( self, capsys ):
        job = _job( debug=True )
        job._cancel_requested = True
        with patch.object( job, "_execute", AsyncMock( return_value="partial" ) ):
            out = job.do_all()
        assert job.state == JobState.CANCELLED
        assert job.error == "Cancelled by user request"
        assert out == "partial"
        assert "Cancelled by user request" in capsys.readouterr().out

    def test_cancel_without_result_fallback( self ):
        job = _job()
        job._cancel_requested = True
        with patch.object( job, "_execute", AsyncMock( return_value=None ) ):
            out = job.do_all()
        assert job.state == JobState.CANCELLED
        assert out == "Presentation generation was cancelled by the user."

    def test_failure_reraises_debug( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( side_effect=RuntimeError( "kaboom" ) ) ):
            with pytest.raises( RuntimeError, match="kaboom" ):
                job.do_all()
        assert job.state == JobState.FAILED
        assert job.error == "kaboom"
        assert job.answer_conversational == "Presentation generation failed: kaboom"
        assert "Failed: kaboom" in capsys.readouterr().out

    def test_failure_quiet( self ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( side_effect=ValueError( "x" ) ) ):
            with pytest.raises( ValueError ):
                job.do_all()
        assert job.state == JobState.FAILED


# ===========================================================================
# _execute (non-dry-run) graph
# ===========================================================================
class _ExecGraph:
    def __init__( self, presentation=True, has_api_client=True, state=None,
                  total_slides=12, render_only=False ):
        self.voice_io = MagicMock()
        self.voice_io.notify = AsyncMock()
        self.cosa_interface = MagicMock()
        self.cosa_interface._get_sender_id.return_value = "sender-id"

        self.orch = MagicMock()
        self.orch.presentation_id = "pr-abc"
        self.orch._presentation_state = state if state is not None else {
            "yaml_path" : "/proj/io/pres/deck.yaml",
            "marp_path" : "/proj/io/pres/deck.md",
            "pptx_path" : "/proj/io/pres/deck.pptx",
        }
        deck = MagicMock()
        deck.total_slides = total_slides
        ret = deck if presentation else None
        self.orch.do_all_async          = AsyncMock( return_value=ret )
        self.orch.render_from_yaml_async = AsyncMock( return_value=ret )
        if has_api_client:
            self.orch._api_client = MagicMock()
            self.orch.api_client.cost_estimate.estimated_cost_usd  = 0.5
            self.orch.api_client.cost_estimate.total_input_tokens  = 100
            self.orch.api_client.cost_estimate.total_output_tokens = 50
            self.orch.api_client.cost_estimate.total_api_calls     = 3
        else:
            self.orch._api_client = None

        self.orch_ctor = MagicMock( return_value=self.orch )
        self.config_obj = MagicMock()
        self.config_obj.target_duration_minutes = 15
        pres_config = MagicMock()
        pres_config.from_config.return_value = self.config_obj

        self.modules = {
            "cosa.agents.presentation_generator": _make_module(
                "cosa.agents.presentation_generator",
                voice_io=self.voice_io, cosa_interface=self.cosa_interface ),
            "cosa.agents.presentation_generator.orchestrator": _make_module(
                "cosa.agents.presentation_generator.orchestrator",
                PresentationOrchestratorAgent=self.orch_ctor ),
            "cosa.agents.presentation_generator.config": _make_module(
                "cosa.agents.presentation_generator.config",
                PresentationConfig=pres_config ),
            "cosa.config.configuration_manager": _make_module(
                "cosa.config.configuration_manager",
                ConfigurationManager=MagicMock() ),
        }

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestExecute:
    def test_happy_full_with_overrides_and_links( self, capsys ):
        job = _job( debug=True, target_duration_minutes=20, audience="expert",
                    theme="dark", content_model="claude-x" )
        g = _ExecGraph()
        with g.patcher(), patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            out = _run( job._execute() )
        assert "Presentation complete! Generated 12 slides" in out
        assert g.config_obj.target_duration_minutes == 20
        assert g.config_obj.audience == "expert"
        assert g.config_obj.default_theme == "dark"
        assert g.config_obj.content_model == "claude-x"
        # io_base relative paths stored
        assert job.artifacts[ "report_path" ] == "pres/deck.md"
        assert job.artifacts[ "yaml_path" ] == "pres/deck.yaml"
        assert job.artifacts[ "pptx_path" ] == "pres/deck.pptx"
        assert job.cost_summary[ "total_cost_usd" ] == 0.5
        g.voice_io.set_job_id.assert_called_once_with( job.id_hash )
        g.voice_io.clear_job_id.assert_called_once_with()
        assert "Source document:" in capsys.readouterr().out

    def test_dry_run_routes_to_helper( self ):
        job = _job( dry_run=True )
        g = _ExecGraph()
        with g.patcher(), patch.object( job, "_execute_dry_run", AsyncMock( return_value="DRY" ) ) as dry:
            out = _run( job._execute() )
        assert out == "DRY"
        dry.assert_awaited_once()
        g.orch_ctor.assert_not_called()
        g.voice_io.reconfigure.assert_called_once_with()

    def test_render_only_branch( self ):
        job = _job( render_only=True )
        g = _ExecGraph( render_only=True )
        with g.patcher(), patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        g.orch.render_from_yaml_async.assert_awaited_once()
        g.orch.do_all_async.assert_not_called()

    def test_relative_path_resolution( self ):
        job = _job( source_path="io/dr/report.md" )
        g = _ExecGraph()
        with g.patcher(), patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        assert g.orch_ctor.call_args.kwargs[ "source_path" ] == "/proj/io/dr/report.md"

    def test_missing_file_raises( self ):
        job = _job()
        g = _ExecGraph()
        with g.patcher(), patch( "os.path.exists", return_value=False ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( FileNotFoundError, match="Source document not found" ):
                _run( job._execute() )
        g.voice_io.clear_job_id.assert_called_once_with()

    def test_presentation_none_cancelled( self ):
        job = _job()
        g = _ExecGraph( presentation=False )
        with g.patcher(), patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            out = _run( job._execute() )
        assert out == "Presentation generation was cancelled by the user."

    def test_non_io_paths_and_no_pptx_and_no_api_client( self ):
        job = _job()
        g = _ExecGraph(
            has_api_client=False,
            state={ "yaml_path": "/tmp/d.yaml", "marp_path": "/tmp/d.md", "pptx_path": None },
        )
        with g.patcher(), patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            out = _run( job._execute() )
        assert "12 slides" in out
        # non-io paths kept as-is
        assert job.artifacts[ "report_path" ] == "/tmp/d.md"
        assert job.artifacts[ "pptx_path" ] is None
        assert job.cost_summary[ "total_cost_usd" ] == 0.0

    def test_debug_false_quiet( self, capsys ):
        job = _job( debug=False )
        g = _ExecGraph()
        with g.patcher(), patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        assert "Source document:" not in capsys.readouterr().out


# ===========================================================================
# _execute_dry_run
# ===========================================================================
class TestExecuteDryRun:
    def _vio_ci( self ):
        vio = MagicMock()
        vio.notify = AsyncMock()
        ci = MagicMock()
        ci._get_sender_id.return_value = "sid"
        return vio, ci

    def test_dry_run_happy_debug( self, capsys ):
        job = _job( debug=True )
        vio, ci = self._vio_ci()
        with patch( "cosa.agents.presentation_generator.job.asyncio.sleep", new=AsyncMock() ):
            out = _run( job._execute_dry_run( vio, ci ) )
        assert out == "Dry run complete. Presentation simulation finished."
        assert job.artifacts[ "slide_count" ] == 0
        assert job.cost_summary[ "total_cost_usd" ] == 0.0
        vio.set_job_id.assert_called_once_with( job.id_hash )
        vio.clear_job_id.assert_called_once_with()
        assert "DRY RUN MODE" in capsys.readouterr().out

    def test_dry_run_force_failure_raises( self ):
        job = _job( force_failure_mode="code_bug" )
        vio, ci = self._vio_ci()
        with patch( "cosa.agents.presentation_generator.job.asyncio.sleep", new=AsyncMock() ), \
             patch.object( job, "_raise_forced_failure", AsyncMock( side_effect=RuntimeError( "forced" ) ) ):
            with pytest.raises( RuntimeError, match="forced" ):
                _run( job._execute_dry_run( vio, ci ) )
        # job_id cleared even on failure
        vio.clear_job_id.assert_called_once_with()


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
