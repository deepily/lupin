#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.orchestrator — STATE MACHINES.

Covers the two top-level coordinators:
  - do_all_async         (orchestrator.py:188-289) — the 8-phase + 4-gate pipeline
  - render_from_yaml_async (orchestrator.py:291-359) — render-only mode (phases 6-8)

Playbook (proven on podcast's orchestrator): mock every private _*_async helper +
each _gate_N on the agent instance, then drive the state machine through:
  - the full happy path,
  - each _check_stop()-True checkpoint (helper side-effect flips _stop_requested),
  - each gate-rejected branch,
  - the top-level except → FAILED + re-raise.

Isolation: voice_io.* → AsyncMock (autouse); zero API/fs/subprocess. The helper
methods themselves are unit-tested in test_orchestrator_helpers.py — here we only
exercise the GLUE that sequences them.
"""

import builtins
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator import orchestrator as orch_mod
from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
from cosa.agents.presentation_generator.state import (
    OrchestratorState,
    ArcPosition,
    NarrativeSection,
    SlideOutline,
    SlideModel,
    PresenterNotes,
    PresentationModel,
)
from cosa.agents.presentation_generator.config import PresentationConfig


def _run( coro ):
    return asyncio.run( coro )


def _agent( source_path="/io/src/doc.md", user_id="u@test.com", offline_mode=False, debug=False ):
    return PresentationOrchestratorAgent(
        source_path  = source_path,
        user_id      = user_id,
        config       = PresentationConfig(),
        offline_mode = offline_mode,
        debug        = debug,
    )


def _presentation():
    slide = SlideModel(
        number=1, arc_position="opening", type="title", title="T",
        presenter_notes=PresenterNotes( talking_points=[ "tp" ], timing_seconds=60 ),
    )
    return PresentationModel( title="My Talk", total_slides=1, slides=[ slide ] )


@pytest.fixture( autouse=True )
def _silence_voice_io():
    with patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ) as notify:
        yield { "notify": notify }


# ===========================================================================
# do_all_async
# ===========================================================================
def _wire_doall( agent, presentation=None ):
    """Mock every private helper + gate so do_all_async runs end-to-end."""
    pres = presentation or _presentation()
    agent._ingest_async   = AsyncMock( return_value="source content" )
    agent._analyze_async  = AsyncMock( return_value=[ NarrativeSection(
        heading="H", content="c", arc_position=ArcPosition.SETUP, proposed_slides=1 ) ] )
    agent._gate_1_narrative_review = AsyncMock( return_value=True )
    agent._outline_async  = AsyncMock( return_value=[ SlideOutline(
        number=1, arc_position="opening", type="title", title="T" ) ] )
    agent._gate_2_outline_review = AsyncMock( return_value=True )
    agent._elaborate_async = AsyncMock( return_value=pres.slides )
    agent._gate_3_content_review = AsyncMock( return_value=True )
    agent._serialize_async = AsyncMock( return_value=pres )
    agent._render_text_async    = AsyncMock()
    agent._render_visuals_async = AsyncMock()
    agent._gate_4_render_review = AsyncMock( return_value=True )
    agent._deliver_async   = AsyncMock()
    agent._export_pptx_async = AsyncMock()
    return pres


class TestDoAllAsyncHappy:
    def test_full_happy_path( self, _silence_voice_io ):
        agent = _agent()
        pres  = _wire_doall( agent )
        result = _run( agent.do_all_async() )
        assert result is pres
        assert agent.state == OrchestratorState.COMPLETED
        assert agent.metrics[ "start_time" ] is not None
        assert agent.metrics[ "end_time" ] is not None
        agent._deliver_async.assert_awaited_once()
        agent._export_pptx_async.assert_awaited_once()
        # state stored
        assert agent._presentation_state[ "source_content" ] == "source content"
        assert agent._presentation_state[ "presentation_model" ] is pres


class TestDoAllAsyncStopCheckpoints:
    """Each _check_stop()-True arm → _handle_stop (CANCELLED) → return None."""
    def _stop_after( self, agent, attr, retval ):
        async def _side( *a, **k ):
            agent._stop_requested = True
            return retval
        setattr( agent, attr, AsyncMock( side_effect=_side ) )

    def test_stop_after_ingest( self ):
        agent = _agent(); _wire_doall( agent )
        self._stop_after( agent, "_ingest_async", "content" )
        assert _run( agent.do_all_async() ) is None
        assert agent.state == OrchestratorState.CANCELLED

    def test_stop_after_analyze( self ):
        agent = _agent(); _wire_doall( agent )
        self._stop_after( agent, "_analyze_async", [] )
        assert _run( agent.do_all_async() ) is None
        assert agent.state == OrchestratorState.CANCELLED

    def test_stop_after_outline( self ):
        agent = _agent(); _wire_doall( agent )
        self._stop_after( agent, "_outline_async", [] )
        assert _run( agent.do_all_async() ) is None

    def test_stop_after_elaborate( self ):
        agent = _agent(); _wire_doall( agent )
        self._stop_after( agent, "_elaborate_async", [] )
        assert _run( agent.do_all_async() ) is None

    def test_stop_after_serialize( self ):
        agent = _agent(); pres = _wire_doall( agent )
        self._stop_after( agent, "_serialize_async", pres )
        assert _run( agent.do_all_async() ) is None

    def test_stop_after_render_text( self ):
        agent = _agent(); _wire_doall( agent )
        self._stop_after( agent, "_render_text_async", None )
        assert _run( agent.do_all_async() ) is None

    def test_stop_after_render_visuals( self ):
        agent = _agent(); _wire_doall( agent )
        self._stop_after( agent, "_render_visuals_async", None )
        assert _run( agent.do_all_async() ) is None


class TestDoAllAsyncGatesReject:
    """Each gate returning False → _handle_stop → return None."""
    def test_gate1_reject( self ):
        agent = _agent(); _wire_doall( agent )
        agent._gate_1_narrative_review = AsyncMock( return_value=False )
        assert _run( agent.do_all_async() ) is None
        assert agent.state == OrchestratorState.CANCELLED

    def test_gate2_reject( self ):
        agent = _agent(); _wire_doall( agent )
        agent._gate_2_outline_review = AsyncMock( return_value=False )
        assert _run( agent.do_all_async() ) is None

    def test_gate3_reject( self ):
        agent = _agent(); _wire_doall( agent )
        agent._gate_3_content_review = AsyncMock( return_value=False )
        assert _run( agent.do_all_async() ) is None

    def test_gate4_reject( self ):
        agent = _agent(); _wire_doall( agent )
        agent._gate_4_render_review = AsyncMock( return_value=False )
        assert _run( agent.do_all_async() ) is None


class TestDoAllAsyncException:
    def test_exception_sets_failed_and_reraises( self, _silence_voice_io ):
        agent = _agent()
        _wire_doall( agent )
        agent._ingest_async = AsyncMock( side_effect=RuntimeError( "ingest boom" ) )
        with pytest.raises( RuntimeError, match="ingest boom" ):
            _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.FAILED
        assert agent.metrics[ "end_time" ] is not None
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )


class TestDoAllAsyncEmptyResultGuards:
    """D6-STRICT: a non-stopped empty phase result FAILS the job loudly (not a
    silent empty deck). Guards are ordered AFTER the per-phase stop-check, so a
    user-requested stop (covered in TestDoAllAsyncStopCheckpoints) still cancels
    cleanly even when the phase returns []."""

    def test_empty_narrative_fails_loud( self, _silence_voice_io ):
        agent = _agent(); _wire_doall( agent )
        agent._analyze_async = AsyncMock( return_value=[] )
        with pytest.raises( ValueError, match="Phase 2" ):
            _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.FAILED

    def test_empty_outline_fails_loud( self, _silence_voice_io ):
        agent = _agent(); _wire_doall( agent )
        agent._outline_async = AsyncMock( return_value=[] )
        with pytest.raises( ValueError, match="Phase 3" ):
            _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.FAILED

    def test_empty_elaboration_fails_loud( self, _silence_voice_io ):
        agent = _agent(); _wire_doall( agent )
        agent._elaborate_async = AsyncMock( return_value=[] )
        with pytest.raises( ValueError, match="Phase 4" ):
            _run( agent.do_all_async() )
        assert agent.state == OrchestratorState.FAILED


# ===========================================================================
# render_from_yaml_async
# ===========================================================================
def _wire_render_only( agent ):
    agent._render_text_async    = AsyncMock()
    agent._render_visuals_async = AsyncMock()
    agent._gate_4_render_review = AsyncMock( return_value=True )
    agent._deliver_async        = AsyncMock()
    agent._export_pptx_async    = AsyncMock()


def _fake_open_yaml( payload="yaml: content" ):
    fh = MagicMock()
    fh.read.return_value = payload
    fo = MagicMock()
    fo.return_value.__enter__.return_value = fh
    return fo


class TestRenderFromYamlAsync:
    def test_happy_path_debug( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        _wire_render_only( agent )
        pres = _presentation()
        with patch.object( builtins, "open", _fake_open_yaml() ), \
             patch.object( orch_mod.PresentationModel, "from_yaml", return_value=pres ):
            result = _run( agent.render_from_yaml_async( "/io/out/pres.yaml" ) )
        assert result is pres
        assert agent.state == OrchestratorState.COMPLETED
        assert agent._presentation_state[ "yaml_path" ] == "/io/out/pres.yaml"
        assert agent._presentation_state[ "presentation_model" ] is pres
        agent._deliver_async.assert_awaited_once()
        assert "Render-only: Loaded" in capsys.readouterr().out

    def test_stop_after_render_text( self, _silence_voice_io ):
        agent = _agent()
        _wire_render_only( agent )
        async def _rt_stop( *a, **k ):
            agent._stop_requested = True
        agent._render_text_async = AsyncMock( side_effect=_rt_stop )
        with patch.object( builtins, "open", _fake_open_yaml() ), \
             patch.object( orch_mod.PresentationModel, "from_yaml", return_value=_presentation() ):
            assert _run( agent.render_from_yaml_async( "/io/out/pres.yaml" ) ) is None
        assert agent.state == OrchestratorState.CANCELLED

    def test_stop_after_render_visuals( self, _silence_voice_io ):
        agent = _agent()
        _wire_render_only( agent )
        async def _rv_stop( *a, **k ):
            agent._stop_requested = True
        agent._render_visuals_async = AsyncMock( side_effect=_rv_stop )
        with patch.object( builtins, "open", _fake_open_yaml() ), \
             patch.object( orch_mod.PresentationModel, "from_yaml", return_value=_presentation() ):
            assert _run( agent.render_from_yaml_async( "/io/out/pres.yaml" ) ) is None

    def test_gate4_reject( self, _silence_voice_io ):
        agent = _agent()
        _wire_render_only( agent )
        agent._gate_4_render_review = AsyncMock( return_value=False )
        with patch.object( builtins, "open", _fake_open_yaml() ), \
             patch.object( orch_mod.PresentationModel, "from_yaml", return_value=_presentation() ):
            assert _run( agent.render_from_yaml_async( "/io/out/pres.yaml" ) ) is None
        assert agent.state == OrchestratorState.CANCELLED

    def test_exception_sets_failed_and_reraises( self, _silence_voice_io ):
        agent = _agent()
        _wire_render_only( agent )
        with patch.object( builtins, "open", side_effect=OSError( "no yaml" ) ):
            with pytest.raises( OSError, match="no yaml" ):
                _run( agent.render_from_yaml_async( "/io/out/missing.yaml" ) )
        assert agent.state == OrchestratorState.FAILED
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )
