#!/usr/bin/env python3
"""
Unit tests for cosa.agents.deep_research_to_presentation.agent

Target: DeepResearchToPresentationAgent — the wrapper chaining Deep Research ->
Presentation Generation. Every external boundary (deep_research package,
presentation_generator package, ConfigurationManager, Gister, cost tracker,
CLI helpers, filesystem) is mocked at the import boundary; NO real LLM / SDK /
network / filesystem work occurs.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import sys
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent
from cosa.agents.deep_research_to_presentation.state import PipelineState, ChainedResult


def _make_module( name, **attrs ):
    mod = types.ModuleType( name )
    for key, value in attrs.items():
        setattr( mod, key, value )
    return mod


def _run( coro ):
    return asyncio.run( coro )


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
class TestInit:
    """
    Construction contract for DeepResearchToPresentationAgent.__init__.

    Ensures:
        - all passed args stored verbatim (incl. theme / target_duration_minutes)
        - result starts as a fresh INITIALIZED ChainedResult, _start_time None
        - debug=True prints an init banner; debug=False stays silent
    """

    def test_stores_args( self ):
        agent = DeepResearchToPresentationAgent(
            query      = "quantum",
            user_email = "u@test.com",
            budget     = 3.0,
            lead_model = "claude-opus",
            no_confirm = True,
            audience   = "expert",
            audience_context = "PhDs",
            target_duration_minutes = 15,
            theme      = "gaia",
            cli_mode   = True,
            verbose    = True,
        )
        assert agent.query                   == "quantum"
        assert agent.user_email              == "u@test.com"
        assert agent.budget                  == 3.0
        assert agent.lead_model              == "claude-opus"
        assert agent.no_confirm              is True
        assert agent.audience                == "expert"
        assert agent.audience_context        == "PhDs"
        assert agent.target_duration_minutes == 15
        assert agent.theme                   == "gaia"
        assert agent.cli_mode                is True
        assert agent.verbose                 is True
        assert isinstance( agent.result, ChainedResult )
        assert agent.result.state == PipelineState.INITIALIZED
        assert agent._start_time  is None

    def test_debug_true_prints_banner( self, capsys ):
        DeepResearchToPresentationAgent( query="q" * 60, user_email="u@test.com", debug=True, cli_mode=True )
        out = capsys.readouterr().out
        assert "[DeepResearchToPresentationAgent] Initialized" in out
        assert "CLI" in out                                # cli_mode True label

    def test_debug_false_is_silent( self, capsys ):
        DeepResearchToPresentationAgent( query="q", user_email="u@test.com", debug=False )
        assert capsys.readouterr().out == ""


# ----------------------------------------------------------------------------
# get_state + _finalize_result
# ----------------------------------------------------------------------------
class TestGetStateAndFinalize:
    """
    get_state reflects result.state; _finalize_result stamps timing + cost.

    Ensures duration computed only when _start_time is truthy (0.0 is falsy).
    """

    def test_get_state_reflects_result( self ):
        agent = DeepResearchToPresentationAgent( query="q", user_email="u@test.com" )
        assert agent.get_state() == PipelineState.INITIALIZED
        agent.result.state = PipelineState.RUNNING_PRESENTATION_GEN
        assert agent.get_state() == PipelineState.RUNNING_PRESENTATION_GEN

    def test_finalize_with_start_time_sets_duration( self ):
        agent = DeepResearchToPresentationAgent( query="q", user_email="u@test.com" )
        agent.result.dr_cost = 1.0
        agent.result.pg_cost = 0.5
        agent._start_time    = 1.0                         # truthy => compute branch
        out = agent._finalize_result()
        assert out is agent.result
        assert out.completed_at is not None
        assert out.total_cost == 1.5
        assert out.duration_seconds > 0

    def test_finalize_without_start_time_leaves_duration_zero( self ):
        agent = DeepResearchToPresentationAgent( query="q", user_email="u@test.com" )
        agent.result.dr_cost = 2.0
        agent.result.pg_cost = 3.0
        agent._start_time    = None
        out = agent._finalize_result()
        assert out.total_cost       == 5.0
        assert out.duration_seconds == 0.0


# ----------------------------------------------------------------------------
# _set_modality + _notify
# ----------------------------------------------------------------------------
class TestSetModalityAndNotify:
    """
    _set_modality pushes cli_mode onto both voice_io modules and reconfigures DR;
    _notify routes to deep_research.voice_io.notify (async).
    """

    def _patched_voice_modules( self, dr_vio, pg_vio ):
        return patch.dict( sys.modules, {
            "cosa.agents.deep_research"        : _make_module( "cosa.agents.deep_research", voice_io=dr_vio ),
            "cosa.agents.presentation_generator": _make_module( "cosa.agents.presentation_generator", voice_io=pg_vio ),
        } )

    def test_set_modality_sets_both_and_reconfigures( self ):
        dr_vio, pg_vio = MagicMock(), MagicMock()
        agent = DeepResearchToPresentationAgent( query="q", user_email="u@test.com", cli_mode=True )
        with self._patched_voice_modules( dr_vio, pg_vio ):
            agent._set_modality()
        dr_vio.set_cli_mode.assert_called_once_with( True )
        pg_vio.set_cli_mode.assert_called_once_with( True )
        dr_vio.reconfigure.assert_called_once_with()

    def test_set_modality_debug_prints_label( self, capsys ):
        dr_vio, pg_vio = MagicMock(), MagicMock()
        agent = DeepResearchToPresentationAgent( query="q", user_email="u@test.com", cli_mode=False, debug=True )
        with self._patched_voice_modules( dr_vio, pg_vio ):
            agent._set_modality()
        assert "Set modality to: Voice-driven" in capsys.readouterr().out

    def test_notify_awaits_voice_io( self ):
        dr_vio = MagicMock()
        dr_vio.notify = AsyncMock()
        dr_pkg = _make_module( "cosa.agents.deep_research", voice_io=dr_vio )
        agent  = DeepResearchToPresentationAgent( query="q", user_email="u@test.com" )
        with patch.dict( sys.modules, { "cosa.agents.deep_research": dr_pkg } ):
            _run( agent._notify( "hello", priority="urgent", abstract="A" ) )
        dr_vio.notify.assert_awaited_once_with( "hello", priority="urgent", abstract="A" )


# ----------------------------------------------------------------------------
# run_async — branch matrix
# ----------------------------------------------------------------------------
class TestRunAsync:
    """
    run_async orchestration branches with underlying steps patched on the instance.

    Ensures: happy -> COMPLETED with yaml/marp/slide_count; dr-cancel -> CANCELLED;
    no-report -> FAILED; pg-cancel -> CANCELLED; exception -> FAILED + urgent notify.
    """

    def _agent( self, **kw ):
        agent = DeepResearchToPresentationAgent( query="q", user_email="u@test.com", **kw )
        agent._set_modality = MagicMock()
        agent._notify       = AsyncMock()
        return agent

    def test_happy_path_completes_with_slide_count( self ):
        agent = self._agent()
        agent._run_deep_research = AsyncMock( return_value={
            "cancelled"   : False,
            "report_path" : "/io/dr/report.md",
            "abstract"    : "An abstract",
            "cost"        : 1.5,
            "artifacts"   : { "tokens_used": 12345, "duration_seconds": 60 },
        } )
        agent._run_presentation_generator = AsyncMock( return_value={
            "cancelled" : False,
            "yaml_path" : "/io/pres/deck.yaml",
            "marp_path" : "/io/pres/deck.md",
            "cost"      : 0.75,
            "artifacts" : { "presentation_id": "pp-1", "slide_count": 11 },
        } )
        result = _run( agent.run_async() )
        assert result.state        == PipelineState.COMPLETED
        assert result.research_path == "/io/dr/report.md"
        assert result.yaml_path     == "/io/pres/deck.yaml"
        assert result.marp_path     == "/io/pres/deck.md"
        assert result.slide_count   == 11
        assert result.total_cost    == 2.25
        agent._run_presentation_generator.assert_awaited_once_with( "/io/dr/report.md" )

    def test_dr_cancelled( self ):
        agent = self._agent()
        agent._run_deep_research          = AsyncMock( return_value={ "cancelled": True } )
        agent._run_presentation_generator = AsyncMock()
        result = _run( agent.run_async() )
        assert result.state == PipelineState.CANCELLED
        assert result.error == "Deep Research was cancelled by user"
        agent._run_presentation_generator.assert_not_called()

    def test_dr_no_report_path( self ):
        agent = self._agent()
        agent._run_deep_research          = AsyncMock( return_value={ "cancelled": False, "report_path": None } )
        agent._run_presentation_generator = AsyncMock()
        result = _run( agent.run_async() )
        assert result.state == PipelineState.FAILED
        assert result.error == "Deep Research completed but no report_path returned"
        agent._run_presentation_generator.assert_not_called()

    def test_pg_cancelled_with_none_abstract( self ):
        agent = self._agent()
        agent._run_deep_research = AsyncMock( return_value={
            "cancelled"   : False,
            "report_path" : "/io/dr/report.md",
            "abstract"    : None,                          # 'N/A' branch
            "cost"        : 1.0,
            "artifacts"   : { "tokens_used": 5, "duration_seconds": 9 },
        } )
        agent._run_presentation_generator = AsyncMock( return_value={ "cancelled": True } )
        result = _run( agent.run_async() )
        assert result.state == PipelineState.CANCELLED
        assert result.error == "Presentation Generation was cancelled by user"
        assert result.research_path == "/io/dr/report.md"

    def test_exception_with_debug( self, capsys ):
        agent = self._agent( debug=True )
        agent._run_deep_research = AsyncMock( side_effect=RuntimeError( "boom-detail" ) )
        result = _run( agent.run_async() )
        assert result.state == PipelineState.FAILED
        assert result.error == "boom-detail"
        urgent = [ c for c in agent._notify.await_args_list if c.kwargs.get( "priority" ) == "urgent" ]
        assert len( urgent ) == 1
        assert "Pipeline failed: boom-detail" in urgent[ 0 ].args[ 0 ]

    def test_exception_without_debug( self ):
        agent = self._agent( debug=False )
        agent._run_deep_research = AsyncMock( side_effect=ValueError( "nope" ) )
        result = _run( agent.run_async() )
        assert result.state == PipelineState.FAILED
        assert result.error == "nope"


# ----------------------------------------------------------------------------
# _run_deep_research — identical logic to the podcast bridge
# ----------------------------------------------------------------------------
class _FakeBudgetExceeded( Exception ):
    def __init__( self, current_cost, budget_limit ):
        super().__init__( "budget" )
        self.current_cost = current_cost
        self.budget_limit = budget_limit


def _summary( cost=1.25, in_tok=100, out_tok=50, dur=42.0 ):
    s = MagicMock()
    s.total_cost_usd      = cost
    s.total_input_tokens  = in_tok
    s.total_output_tokens = out_tok
    s.duration_seconds    = dur
    return s


class _DRGraph:
    """Installs a complete fake module graph for _run_deep_research."""

    def __init__( self, cfg_values=None, gist="Quantum Topic", report="REPORT-BODY", run_research_exc=None ):
        self.cfg_values        = cfg_values or {}
        self.run_research      = AsyncMock( return_value=report, side_effect=run_research_exc )
        self.generate_abstract = AsyncMock( return_value="ABSTRACT" )
        self.save_report       = MagicMock( return_value="/io/dr/saved.md" )
        self.cost_tracker_instance = MagicMock()
        self.cost_tracker_instance.get_summary.return_value = _summary()

        gister_instance = MagicMock()
        gister_instance.get_gist.return_value = gist
        self.dr_cosa_iface = MagicMock()

        self.modules = {
            "cosa.agents.deep_research": _make_module(
                "cosa.agents.deep_research",
                voice_io       = MagicMock(),
                cosa_interface = self.dr_cosa_iface,
            ),
            "cosa.agents.deep_research.config": _make_module(
                "cosa.agents.deep_research.config", ResearchConfig=MagicMock()
            ),
            "cosa.agents.deep_research.cost_tracker": _make_module(
                "cosa.agents.deep_research.cost_tracker",
                CostTracker=MagicMock( return_value=self.cost_tracker_instance ),
                BudgetExceededError=_FakeBudgetExceeded,
            ),
            "cosa.agents.deep_research.cli": _make_module(
                "cosa.agents.deep_research.cli",
                run_research=self.run_research,
                generate_abstract_for_cli=self.generate_abstract,
                save_report_with_frontmatter=self.save_report,
            ),
            "cosa.config.configuration_manager": _make_module(
                "cosa.config.configuration_manager",
                ConfigurationManager=MagicMock( return_value=self._cfg_mgr() ),
            ),
            "cosa.memory.gister": _make_module(
                "cosa.memory.gister", Gister=MagicMock( return_value=gister_instance )
            ),
        }

    def _cfg_mgr( self ):
        cm = MagicMock()
        cm.get.side_effect = lambda key, default=None: self.cfg_values.get( key, default )
        return cm

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestRunDeepResearch:
    """
    _run_deep_research branch coverage with all boundaries faked.

    Ensures output_dir resolution (relative / absolute-outside / absolute-inside),
    gister fallback, explicit-override config branches, report-None cancel,
    happy result dict, and BudgetExceededError -> formatted re-raise.
    """

    def _agent( self, **kw ):
        return DeepResearchToPresentationAgent( query="q", user_email="u@test.com", **kw )

    def test_relative_output_dir_prefixed( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "io/dr" } )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent._run_deep_research() )
        assert graph.save_report.call_args.kwargs[ "output_dir" ] == "/proj/io/dr"
        assert result[ "cancelled" ] is False
        assert agent.result.state == PipelineState.RUNNING_DEEP_RESEARCH
        assert graph.dr_cosa_iface.TARGET_USER == "u@test.com"

    def test_absolute_output_dir_outside_root_prefixed( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/io/dr" } )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( agent._run_deep_research() )
        assert graph.save_report.call_args.kwargs[ "output_dir" ] == "/proj/io/dr"

    def test_absolute_output_dir_inside_root_unchanged( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io/dr" } )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( agent._run_deep_research() )
        assert graph.save_report.call_args.kwargs[ "output_dir" ] == "/proj/io/dr"

    def test_gister_falsy_default_session_name( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" }, gist="" )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent._run_deep_research() )
        assert result[ "artifacts" ][ "session_name" ]   == "general research query"
        assert result[ "artifacts" ][ "semantic_topic" ] == "general-research-query"

    def test_explicit_overrides_and_debug( self, capsys ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" } )
        agent = self._agent( lead_model="my-model", audience="beginner", audience_context="kids", debug=True )
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            result = _run( agent._run_deep_research() )
        kwargs = graph.modules[ "cosa.agents.deep_research.config" ].ResearchConfig.call_args.kwargs
        assert kwargs[ "lead_model" ]       == "my-model"
        assert kwargs[ "audience" ]         == "beginner"
        assert kwargs[ "audience_context" ] == "kids"
        out = capsys.readouterr().out
        assert "[DR] Session name:" in out and "Storage backend:" in out
        assert result[ "cost" ] == 1.25
        assert result[ "artifacts" ][ "tokens_used" ] == 150

    def test_report_none_returns_cancelled( self ):
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" }, report=None )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent._run_deep_research() ) == { "cancelled": True }
        graph.save_report.assert_not_called()

    def test_budget_exceeded_reraised( self ):
        exc   = _FakeBudgetExceeded( current_cost=4.2, budget_limit=3.0 )
        graph = _DRGraph( cfg_values={ "deep research output directory": "/proj/io" }, run_research_exc=exc )
        agent = self._agent()
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( Exception ) as ei:
                _run( agent._run_deep_research() )
        msg = str( ei.value )
        assert "Deep Research budget exceeded" in msg
        assert "$4.20" in msg and "$3.00" in msg


# ----------------------------------------------------------------------------
# _run_presentation_generator — full fake module graph
# ----------------------------------------------------------------------------
class _PGGraph:
    """
    Installs a fake module graph for _run_presentation_generator.

    Tunables: do_all_async presentation result (or None), api_client presence,
    presentation state dict contents.
    """

    def __init__( self, presentation="DECK", has_api_client=True, state=None ):
        self.config_obj = MagicMock()
        self.presentation_config = MagicMock()
        self.presentation_config.from_config.return_value = self.config_obj

        self.orch_instance = MagicMock()
        self.orch_instance.presentation_id = "pp-xyz"
        self.orch_instance.do_all_async = AsyncMock( return_value=( self._deck() if presentation else None ) )
        self.orch_instance._presentation_state = state or {
            "yaml_path"        : "/io/pres/deck.yaml",
            "marp_path"        : "/io/pres/deck.md",
            "delivery_summary" : "9 slides, 12 min",
        }
        if has_api_client:
            self.orch_instance._api_client = MagicMock()
            self.orch_instance.api_client.cost_estimate.estimated_cost_usd = 0.42
        else:
            self.orch_instance._api_client = None

        self.orch_ctor = MagicMock( return_value=self.orch_instance )

        self.modules = {
            "cosa.agents.presentation_generator": _make_module(
                "cosa.agents.presentation_generator",
                voice_io=MagicMock(), cosa_interface=MagicMock(),
            ),
            "cosa.agents.presentation_generator.orchestrator": _make_module(
                "cosa.agents.presentation_generator.orchestrator",
                PresentationOrchestratorAgent=self.orch_ctor,
            ),
            "cosa.agents.presentation_generator.config": _make_module(
                "cosa.agents.presentation_generator.config",
                PresentationConfig=self.presentation_config,
            ),
            "cosa.config.configuration_manager": _make_module(
                "cosa.config.configuration_manager",
                ConfigurationManager=MagicMock(),
            ),
        }

    def _deck( self ):
        d = MagicMock()
        d.total_slides = 9
        d.theme        = "gaia"
        return d

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestRunPresentationGenerator:
    """
    _run_presentation_generator branch coverage with all boundaries faked.

    Ensures:
        - missing research file -> raises
        - all override branches (duration/audience/theme) both set and unset
        - debug diagnostics with and without duration/theme lines
        - presentation None -> cancelled; _api_client falsy -> cost 0.0
        - happy result dict (yaml/marp/cost/artifacts) populated
    """

    def _agent( self, **kw ):
        return DeepResearchToPresentationAgent( query="q", user_email="u@test.com", **kw )

    def test_missing_research_file_raises( self ):
        graph = _PGGraph()
        agent = self._agent()
        with graph.patcher(), patch( "os.path.exists", return_value=False ):
            with pytest.raises( Exception ) as ei:
                _run( agent._run_presentation_generator( "/io/dr/missing.md" ) )
        assert "Research document not found" in str( ei.value )
        assert agent.result.state == PipelineState.RUNNING_PRESENTATION_GEN

    def test_happy_with_all_overrides_and_debug( self, capsys ):
        graph = _PGGraph()
        agent = self._agent( debug=True, target_duration_minutes=20, audience="expert", theme="dark" )
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            result = _run( agent._run_presentation_generator( "/io/dr/report.md" ) )
        # overrides applied to the config object
        assert graph.config_obj.target_duration_minutes == 20
        assert graph.config_obj.audience                == "expert"
        assert graph.config_obj.default_theme           == "dark"
        # full result
        assert result[ "cancelled" ]  is False
        assert result[ "yaml_path" ]  == "/io/pres/deck.yaml"
        assert result[ "marp_path" ]  == "/io/pres/deck.md"
        assert result[ "cost" ]       == 0.42
        assert result[ "artifacts" ][ "presentation_id" ]  == "pp-xyz"
        assert result[ "artifacts" ][ "total_slides" ]     == 9
        assert result[ "artifacts" ][ "theme" ]            == "gaia"
        assert result[ "artifacts" ][ "delivery_summary" ] == "9 slides, 12 min"
        out = capsys.readouterr().out
        assert "[PG] Research document:" in out
        assert "[PG] Target duration: 20 min" in out
        assert "[PG] Theme: dark"        in out
        assert "[PG] Presentation ID: pp-xyz" in out

    def test_slide_count_override_applied_to_config( self ):
        # bug 880d2801: target_slide_count must plumb through the dr2p override
        # path onto the inner PresentationConfig, mirroring target_duration_minutes.
        # The direct-path tests do NOT cover this dr2p config-override site.
        graph = _PGGraph()
        agent = self._agent( target_slide_count=8 )
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            _run( agent._run_presentation_generator( "/io/dr/report.md" ) )
        assert graph.config_obj.target_slide_count == 8

    def test_no_overrides_debug_skips_optional_lines( self, capsys ):
        # debug=True but no duration/theme exercises the 417->422 and 419->422
        # skip arcs AND the override-false arcs (427/429/431 all False).
        graph = _PGGraph( has_api_client=False )
        agent = self._agent( debug=True, target_duration_minutes=None, audience=None, theme=None )
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            result = _run( agent._run_presentation_generator( "/io/dr/report.md" ) )
        out = capsys.readouterr().out
        assert "[PG] Research document:" in out
        assert "Target duration:" not in out
        assert "Theme:"           not in out
        assert result[ "cost" ] == 0.0                     # no api_client

    def test_presentation_none_returns_cancelled( self ):
        graph = _PGGraph( presentation=None )
        agent = self._agent()
        with graph.patcher(), patch( "os.path.exists", return_value=True ):
            assert _run( agent._run_presentation_generator( "/io/dr/report.md" ) ) == { "cancelled": True }
