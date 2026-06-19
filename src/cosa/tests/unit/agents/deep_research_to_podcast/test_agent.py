#!/usr/bin/env python3
"""
Unit tests for cosa.agents.deep_research_to_podcast.agent

Target: DeepResearchToPodcastAgent — the wrapper that chains Deep Research ->
Podcast Generation. Every external boundary (deep_research package,
podcast_generator package, ConfigurationManager, Gister, cost tracker, CLI
run_research/abstract/save helpers, filesystem) is mocked at the import
boundary so NO real LLM / SDK / network / filesystem work occurs.

Strategy:
    - __init__ / get_state / _finalize_result: exercised directly (no boundaries)
    - _set_modality / _notify: sys.modules-injected fake voice_io modules
    - run_async: underlying _run_* / _notify / _set_modality patched on the
      instance, then every branch (happy / dr-cancel / no-report / pg-cancel /
      exception) is driven and asserted
    - _run_deep_research / _run_podcast_generator: full fake module graphs
      injected into sys.modules; every documented branch exercised

The quick_smoke_test() function and the __main__ guard are excluded from
coverage by the repo's [tool.coverage.report] config, so they are not tested.
"""

import sys
import types
import asyncio
import builtins
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
from cosa.agents.deep_research_to_podcast.state import PipelineState, ChainedResult


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _make_module( name, **attrs ):
    """Build a throwaway module object with the given attributes set."""
    mod = types.ModuleType( name )
    for key, value in attrs.items():
        setattr( mod, key, value )
    return mod


def _run( coro ):
    """Drive a coroutine to completion on a fresh event loop."""
    return asyncio.run( coro )


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
class TestInit:
    """
    Construction contract for DeepResearchToPodcastAgent.__init__.

    Ensures:
        - all passed args are stored verbatim
        - target_languages defaults to ["en"] when None, else passthrough
        - result starts as a fresh INITIALIZED ChainedResult, _start_time None
        - debug=True prints an init banner (captured), debug=False stays silent
    """

    def test_stores_args_and_defaults( self ):
        agent = DeepResearchToPodcastAgent(
            query      = "quantum computing",
            user_email = "u@test.com",
            budget     = 3.0,
            lead_model = "claude-opus",
            no_confirm = True,
            audience   = "expert",
            audience_context = "PhD physicists",
            max_segments = 5,
            cli_mode   = True,
            verbose    = True,
        )
        assert agent.query            == "quantum computing"
        assert agent.user_email       == "u@test.com"
        assert agent.budget           == 3.0
        assert agent.lead_model       == "claude-opus"
        assert agent.no_confirm       is True
        assert agent.audience         == "expert"
        assert agent.audience_context == "PhD physicists"
        assert agent.max_segments     == 5
        assert agent.cli_mode         is True
        assert agent.verbose          is True
        assert agent.target_languages == [ "en" ]          # default applied
        assert isinstance( agent.result, ChainedResult )
        assert agent.result.state     == PipelineState.INITIALIZED
        assert agent._start_time      is None

    def test_target_languages_passthrough( self ):
        agent = DeepResearchToPodcastAgent(
            query="q", user_email="u@test.com", target_languages=[ "es", "fr" ]
        )
        assert agent.target_languages == [ "es", "fr" ]

    def test_debug_true_prints_banner( self, capsys ):
        DeepResearchToPodcastAgent( query="q" * 60, user_email="u@test.com", debug=True, cli_mode=False )
        out = capsys.readouterr().out
        assert "[DeepResearchToPodcastAgent] Initialized" in out
        assert "Voice-driven" in out                       # cli_mode False label

    def test_debug_false_is_silent( self, capsys ):
        DeepResearchToPodcastAgent( query="q", user_email="u@test.com", debug=False )
        assert capsys.readouterr().out == ""


# ----------------------------------------------------------------------------
# get_state + _finalize_result
# ----------------------------------------------------------------------------
class TestGetStateAndFinalize:
    """
    get_state() reflects result.state; _finalize_result stamps timing + cost.

    Ensures:
        - get_state returns the live result.state
        - _finalize_result sets completed_at, sums total_cost
        - duration_seconds is computed only when _start_time is set
    """

    def test_get_state_reflects_result( self ):
        agent = DeepResearchToPodcastAgent( query="q", user_email="u@test.com" )
        assert agent.get_state() == PipelineState.INITIALIZED
        agent.result.state = PipelineState.RUNNING_PODCAST_GEN
        assert agent.get_state() == PipelineState.RUNNING_PODCAST_GEN

    def test_finalize_with_start_time_sets_duration( self ):
        agent = DeepResearchToPodcastAgent( query="q", user_email="u@test.com" )
        agent.result.dr_cost = 1.0
        agent.result.pg_cost = 0.5
        # NOTE: `if self._start_time:` treats 0.0 as falsy, so a truthy
        # (non-zero) start time is required to exercise the compute branch.
        agent._start_time    = 1.0
        out = agent._finalize_result()
        assert out is agent.result
        assert out.completed_at is not None
        assert out.total_cost == 1.5
        assert out.duration_seconds > 0

    def test_finalize_without_start_time_leaves_duration_zero( self ):
        agent = DeepResearchToPodcastAgent( query="q", user_email="u@test.com" )
        agent.result.dr_cost = 2.0
        agent.result.pg_cost = 3.0
        agent._start_time    = None
        out = agent._finalize_result()
        assert out.total_cost       == 5.0
        assert out.duration_seconds == 0.0                  # untouched (no start time)


# ----------------------------------------------------------------------------
# _set_modality
# ----------------------------------------------------------------------------
class TestSetModality:
    """
    _set_modality must push cli_mode onto BOTH voice_io modules and reconfigure DR.

    Ensures:
        - dr/pg voice_io.set_cli_mode called with self.cli_mode
        - dr voice_io.reconfigure called (re-establishes default binding)
        - debug=True prints the resolved mode label
    """

    def _patched_modules( self, dr_vio, pg_vio ):
        dr_pkg = _make_module( "cosa.agents.deep_research", voice_io=dr_vio )
        pg_pkg = _make_module( "cosa.agents.podcast_generator", voice_io=pg_vio )
        return patch.dict( sys.modules, {
            "cosa.agents.deep_research"   : dr_pkg,
            "cosa.agents.podcast_generator": pg_pkg,
        } )

    def test_sets_cli_mode_on_both_and_reconfigures( self ):
        dr_vio = MagicMock()
        pg_vio = MagicMock()
        agent  = DeepResearchToPodcastAgent( query="q", user_email="u@test.com", cli_mode=True )
        with self._patched_modules( dr_vio, pg_vio ):
            agent._set_modality()
        dr_vio.set_cli_mode.assert_called_once_with( True )
        pg_vio.set_cli_mode.assert_called_once_with( True )
        dr_vio.reconfigure.assert_called_once_with()

    def test_debug_prints_mode_label( self, capsys ):
        dr_vio = MagicMock()
        pg_vio = MagicMock()
        agent  = DeepResearchToPodcastAgent( query="q", user_email="u@test.com", cli_mode=False, debug=True )
        with self._patched_modules( dr_vio, pg_vio ):
            agent._set_modality()
        assert "Set modality to: Voice-driven" in capsys.readouterr().out


# ----------------------------------------------------------------------------
# _notify
# ----------------------------------------------------------------------------
class TestNotify:
    """
    _notify routes to deep_research.voice_io.notify (async) with priority + kwargs.

    Ensures:
        - awaits voice_io.notify with message, priority, and passthrough kwargs
    """

    def test_awaits_voice_io_notify( self ):
        dr_vio = MagicMock()
        dr_vio.notify = AsyncMock()
        dr_pkg = _make_module( "cosa.agents.deep_research", voice_io=dr_vio )
        agent  = DeepResearchToPodcastAgent( query="q", user_email="u@test.com" )
        with patch.dict( sys.modules, { "cosa.agents.deep_research": dr_pkg } ):
            _run( agent._notify( "hello", priority="urgent", abstract="A" ) )
        dr_vio.notify.assert_awaited_once_with( "hello", priority="urgent", abstract="A" )


# ----------------------------------------------------------------------------
# run_async — branch matrix (underlying steps patched on the instance)
# ----------------------------------------------------------------------------
class TestRunAsync:
    """
    run_async orchestration branches with _set_modality / _run_* / _notify patched.

    Ensures, per branch:
        - happy path -> COMPLETED, both artifacts stored, costs summed
        - dr cancelled -> CANCELLED with DR-cancel error
        - dr returns no report_path -> FAILED
        - pg cancelled -> CANCELLED with PG-cancel error
        - underlying exception -> FAILED, error captured, urgent notify
    """

    def _agent( self, **kw ):
        agent = DeepResearchToPodcastAgent( query="q", user_email="u@test.com", **kw )
        agent._set_modality = MagicMock()
        agent._notify       = AsyncMock()
        return agent

    def test_happy_path_completes( self ):
        agent = self._agent()
        agent._run_deep_research = AsyncMock( return_value={
            "cancelled"   : False,
            "report_path" : "/io/dr/report.md",
            "abstract"    : "An abstract about quantum things",
            "cost"        : 1.5,
            "artifacts"   : { "tokens_used": 12345, "duration_seconds": 60 },
        } )
        agent._run_podcast_generator = AsyncMock( return_value={
            "cancelled"   : False,
            "audio_path"  : "/io/pod/ep.mp3",
            "script_path" : "/io/pod/ep.md",
            "cost"        : 0.75,
            "artifacts"   : { "podcast_id": "pg-1" },
        } )
        result = _run( agent.run_async() )

        assert result.state           == PipelineState.COMPLETED
        assert result.research_path    == "/io/dr/report.md"
        assert result.audio_path       == "/io/pod/ep.mp3"
        assert result.script_path      == "/io/pod/ep.md"
        assert result.dr_cost          == 1.5
        assert result.pg_cost          == 0.75
        assert result.total_cost       == 2.25
        agent._set_modality.assert_called_once()
        agent._run_podcast_generator.assert_awaited_once_with( "/io/dr/report.md" )

    def test_dr_cancelled_sets_cancelled( self ):
        agent = self._agent()
        agent._run_deep_research     = AsyncMock( return_value={ "cancelled": True } )
        agent._run_podcast_generator = AsyncMock()
        result = _run( agent.run_async() )
        assert result.state == PipelineState.CANCELLED
        assert result.error == "Deep Research was cancelled by user"
        agent._run_podcast_generator.assert_not_called()    # short-circuited

    def test_dr_no_report_path_sets_failed( self ):
        agent = self._agent()
        agent._run_deep_research     = AsyncMock( return_value={ "cancelled": False, "report_path": None } )
        agent._run_podcast_generator = AsyncMock()
        result = _run( agent.run_async() )
        assert result.state == PipelineState.FAILED
        assert result.error == "Deep Research completed but no report_path returned"
        agent._run_podcast_generator.assert_not_called()

    def test_pg_cancelled_with_none_abstract_sets_cancelled( self ):
        # abstract=None exercises the 'N/A' branch of the checkpoint abstract.
        agent = self._agent()
        agent._run_deep_research = AsyncMock( return_value={
            "cancelled"   : False,
            "report_path" : "/io/dr/report.md",
            "abstract"    : None,
            "cost"        : 1.0,
            "artifacts"   : { "tokens_used": 999, "duration_seconds": 30 },
        } )
        agent._run_podcast_generator = AsyncMock( return_value={ "cancelled": True } )
        result = _run( agent.run_async() )
        assert result.state == PipelineState.CANCELLED
        assert result.error == "Podcast Generation was cancelled by user"
        # DR results were still recorded before the PG cancel
        assert result.research_path == "/io/dr/report.md"
        assert result.dr_cost       == 1.0

    def test_exception_with_debug_sets_failed_and_urgent_notify( self, capsys ):
        agent = self._agent( debug=True )
        agent._run_deep_research = AsyncMock( side_effect=RuntimeError( "boom-detail" ) )
        result = _run( agent.run_async() )
        assert result.state == PipelineState.FAILED
        assert result.error == "boom-detail"
        # urgent notify fired with truncated message
        urgent_calls = [ c for c in agent._notify.await_args_list if c.kwargs.get( "priority" ) == "urgent" ]
        assert len( urgent_calls ) == 1
        assert "Pipeline failed: boom-detail" in urgent_calls[ 0 ].args[ 0 ]
        # debug=True printed a traceback
        assert "RuntimeError" in capsys.readouterr().err or "Traceback" in capsys.readouterr().out

    def test_exception_without_debug_no_traceback( self ):
        agent = self._agent( debug=False )
        agent._run_deep_research = AsyncMock( side_effect=ValueError( "nope" ) )
        result = _run( agent.run_async() )
        assert result.state == PipelineState.FAILED
        assert result.error == "nope"


# ----------------------------------------------------------------------------
# _run_deep_research — full fake module graph
# ----------------------------------------------------------------------------
class _FakeBudgetExceeded( Exception ):
    """Stand-in for deep_research.cost_tracker.BudgetExceededError."""
    def __init__( self, current_cost, budget_limit ):
        super().__init__( "budget" )
        self.current_cost = current_cost
        self.budget_limit = budget_limit


def _summary( cost=1.25, in_tok=100, out_tok=50, dur=42.0 ):
    s = MagicMock()
    s.total_cost_usd       = cost
    s.total_input_tokens   = in_tok
    s.total_output_tokens  = out_tok
    s.duration_seconds     = dur
    return s


class _DRGraph:
    """
    Builds and installs a complete fake module graph for _run_deep_research.

    Lets tests tune: config values returned, gister output, the run_research
    result (report or None), and whether run_research raises budget-exceeded.
    """

    def __init__( self, cfg_values=None, gist="Quantum Topic", report="REPORT-BODY",
                  run_research_exc=None ):
        self.cfg_values = cfg_values or {}
        self.run_research = AsyncMock(
            return_value = report,
            side_effect  = run_research_exc,
        )
        self.generate_abstract = AsyncMock( return_value="ABSTRACT" )
        self.save_report = MagicMock( return_value="/io/dr/saved.md" )
        self.cost_tracker_instance = MagicMock()
        self.cost_tracker_instance.get_summary.return_value = _summary()

        dr_voice_io      = MagicMock()
        dr_cosa_iface    = MagicMock()
        gister_instance  = MagicMock()
        gister_instance.get_gist.return_value = gist

        self.dr_cosa_iface = dr_cosa_iface

        self.modules = {
            "cosa.agents.deep_research": _make_module(
                "cosa.agents.deep_research",
                voice_io       = dr_voice_io,
                cosa_interface = dr_cosa_iface,
            ),
            "cosa.agents.deep_research.config": _make_module(
                "cosa.agents.deep_research.config",
                ResearchConfig = MagicMock(),
            ),
            "cosa.agents.deep_research.cost_tracker": _make_module(
                "cosa.agents.deep_research.cost_tracker",
                CostTracker         = MagicMock( return_value=self.cost_tracker_instance ),
                BudgetExceededError = _FakeBudgetExceeded,
            ),
            "cosa.agents.deep_research.cli": _make_module(
                "cosa.agents.deep_research.cli",
                run_research               = self.run_research,
                generate_abstract_for_cli  = self.generate_abstract,
                save_report_with_frontmatter = self.save_report,
            ),
            "cosa.config.configuration_manager": _make_module(
                "cosa.config.configuration_manager",
                ConfigurationManager = MagicMock(
                    return_value=self._make_config_mgr()
                ),
            ),
            "cosa.memory.gister": _make_module(
                "cosa.memory.gister",
                Gister = MagicMock( return_value=gister_instance ),
            ),
        }

    def _make_config_mgr( self ):
        cm = MagicMock()
        cm.get.side_effect = lambda key, default=None: self.cfg_values.get( key, default )
        return cm

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestRunDeepResearch:
    """
    _run_deep_research branch coverage with all boundaries faked.

    Ensures:
        - output_dir resolution: relative / absolute-outside-root / absolute-inside-root
        - session_name fallback when gister returns falsy
        - lead_model / audience / audience_context resolution branches
        - report None -> {cancelled: True}
        - happy path -> full result dict with summed token artifact
        - BudgetExceededError -> re-raised as a formatted Exception
        - debug prints session/topic/storage diagnostics
    """

    def _agent( self, **kw ):
        return DeepResearchToPodcastAgent( query="q", user_email="u@test.com", **kw )

    def test_relative_output_dir_is_prefixed_with_root( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "io/dr" } )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent._run_deep_research() )
        # output_dir passed to save_report should be /proj/io/dr
        assert graph.save_report.call_args.kwargs[ "output_dir" ] == "/proj/io/dr"
        assert result[ "cancelled" ] is False
        assert result[ "report_path" ] == "/io/dr/saved.md"
        assert agent.result.state == PipelineState.RUNNING_DEEP_RESEARCH
        # TARGET_USER propagated to DR cosa_interface
        assert graph.dr_cosa_iface.TARGET_USER == "u@test.com"

    def test_absolute_output_dir_outside_root_is_root_prefixed( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/io/dr" } )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( agent._run_deep_research() )
        assert graph.save_report.call_args.kwargs[ "output_dir" ] == "/proj/io/dr"

    def test_absolute_output_dir_inside_root_is_unchanged( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io/dr" } )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( agent._run_deep_research() )
        assert graph.save_report.call_args.kwargs[ "output_dir" ] == "/proj/io/dr"

    def test_gister_falsy_falls_back_to_default_session_name( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" }, gist="" )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent._run_deep_research() )
        assert result[ "artifacts" ][ "session_name" ]   == "general research query"
        assert result[ "artifacts" ][ "semantic_topic" ] == "general-research-query"

    def test_explicit_lead_model_audience_and_context_used( self, capsys ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" } )
        agent = self._agent( lead_model="my-model", audience="beginner",
                             audience_context="kids", debug=True )
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent._run_deep_research() )
        # ResearchConfig was constructed with explicit overrides
        rc = graph.modules[ "cosa.agents.deep_research.config" ].ResearchConfig
        kwargs = rc.call_args.kwargs
        assert kwargs[ "lead_model" ]       == "my-model"
        assert kwargs[ "audience" ]         == "beginner"
        assert kwargs[ "audience_context" ] == "kids"
        out = capsys.readouterr().out
        assert "[DR] Session name:" in out
        assert "Storage backend:"   in out
        assert result[ "cost" ]     == 1.25                 # from _summary default
        assert result[ "artifacts" ][ "tokens_used" ] == 150  # 100 + 50

    def test_report_none_returns_cancelled( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" }, report=None )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent._run_deep_research() )
        assert result == { "cancelled": True }
        graph.save_report.assert_not_called()

    def test_budget_exceeded_is_reraised_as_exception( self ):
        exc   = _FakeBudgetExceeded( current_cost=4.20, budget_limit=3.00 )
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" },
                          run_research_exc=exc )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( Exception ) as ei:
                _run( agent._run_deep_research() )
        msg = str( ei.value )
        assert "Deep Research budget exceeded" in msg
        assert "$4.20" in msg and "$3.00" in msg


# ----------------------------------------------------------------------------
# _run_podcast_generator — full fake module graph
# ----------------------------------------------------------------------------
class _PGGraph:
    """
    Builds and installs a fake module graph for _run_podcast_generator.

    Tunables: do_all_async script result (or None), api_client presence,
    podcast state dict contents.
    """

    def __init__( self, script="SCRIPT-OBJ", has_api_client=True, state=None ):
        self.orch_instance = MagicMock()
        self.orch_instance.podcast_id = "pg-xyz"
        self.orch_instance.do_all_async = AsyncMock( return_value=( self._script_obj() if script else None ) )
        self.orch_instance._podcast_state = state or {
            "final_audio_path": "/io/pod/final.mp3",
            "script_path"     : "/io/pod/script.md",
        }
        if has_api_client:
            self.orch_instance._api_client = MagicMock()
            self.orch_instance.api_client.cost_estimate.estimated_cost_usd = 0.42
        else:
            self.orch_instance._api_client = None

        self.modules = {
            "cosa.agents.podcast_generator": _make_module(
                "cosa.agents.podcast_generator",
                voice_io       = MagicMock(),
                cosa_interface = MagicMock(),
            ),
            "cosa.agents.podcast_generator.orchestrator": _make_module(
                "cosa.agents.podcast_generator.orchestrator",
                PodcastOrchestratorAgent = MagicMock( return_value=self.orch_instance ),
            ),
            "cosa.agents.podcast_generator.config": _make_module(
                "cosa.agents.podcast_generator.config",
                PodcastConfig = MagicMock(),
            ),
        }

    def _script_obj( self ):
        s = MagicMock()
        s.title = "My Episode"
        s.get_segment_count.return_value = 7
        s.estimated_duration_minutes     = 12
        return s

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestRunPodcastGenerator:
    """
    _run_podcast_generator branch coverage with all boundaries faked.

    Ensures:
        - missing research file -> raises Exception
        - happy path -> full result dict (audio/script/cost/artifacts)
        - script None (cancelled) -> {cancelled: True}
        - _api_client falsy -> cost falls back to 0.0
        - debug prints research/podcast diagnostics incl. max_segments line
    """

    def _agent( self, **kw ):
        return DeepResearchToPodcastAgent( query="q", user_email="u@test.com", **kw )

    def test_missing_research_file_raises( self ):
        graph = _PGGraph()
        agent = self._agent()
        with graph.patcher(), patch( "os.path.exists", return_value=False ):
            with pytest.raises( Exception ) as ei:
                _run( agent._run_podcast_generator( "/io/dr/missing.md" ) )
        assert "Research document not found" in str( ei.value )
        assert agent.result.state == PipelineState.RUNNING_PODCAST_GEN

    def test_happy_path_returns_full_result( self ):
        graph = _PGGraph()
        agent = self._agent()
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            result = _run( agent._run_podcast_generator( "/io/dr/report.md" ) )
        assert result[ "cancelled" ]   is False
        assert result[ "audio_path" ]  == "/io/pod/final.mp3"
        assert result[ "script_path" ] == "/io/pod/script.md"
        assert result[ "cost" ]        == 0.42
        assert result[ "artifacts" ][ "podcast_id" ]    == "pg-xyz"
        assert result[ "artifacts" ][ "title" ]         == "My Episode"
        assert result[ "artifacts" ][ "segment_count" ] == 7
        assert result[ "artifacts" ][ "duration_min" ]  == 12

    def test_script_none_returns_cancelled( self ):
        graph = _PGGraph( script=None )
        agent = self._agent()
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            result = _run( agent._run_podcast_generator( "/io/dr/report.md" ) )
        assert result == { "cancelled": True }

    def test_no_api_client_cost_zero( self ):
        graph = _PGGraph( has_api_client=False )
        agent = self._agent()
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            result = _run( agent._run_podcast_generator( "/io/dr/report.md" ) )
        assert result[ "cost" ] == 0.0

    def test_debug_prints_diagnostics_with_max_segments( self, capsys ):
        graph = _PGGraph()
        agent = self._agent( debug=True, max_segments=3 )
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            _run( agent._run_podcast_generator( "/io/dr/report.md" ) )
        out = capsys.readouterr().out
        assert "[PG] Research document:" in out
        assert "[PG] Max segments: 3"    in out
        assert "[PG] Podcast ID: pg-xyz" in out

    def test_debug_without_max_segments_skips_segment_line( self, capsys ):
        # debug=True but max_segments=None exercises the 412->416 skip branch.
        graph = _PGGraph()
        agent = self._agent( debug=True, max_segments=None )
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            _run( agent._run_podcast_generator( "/io/dr/report.md" ) )
        out = capsys.readouterr().out
        assert "[PG] Research document:" in out
        assert "Max segments:" not in out
