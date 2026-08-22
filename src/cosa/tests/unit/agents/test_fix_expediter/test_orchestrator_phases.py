#!/usr/bin/env python3
"""
Unit tests for cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator —
the ASYNC PHASE surface (paired with test_orchestrator_helpers.py).

Covers the phase state-machine + SDK-delegation + voice-gate + worktree +
git + validation methods:
  run_phase0_cluster / run_phase1_diagnose / _diagnose_cluster /
  _delegate_to_lead_diagnosis / run_phase2_propose / _propose_for_cluster /
  _delegate_to_lead_proposal / _write_multi_cluster_plan_doc /
  _proposal_voice_gate / _aggregate_voice_gate / _per_cluster_voice_gate /
  run_phase3_fix / _notify_for_executor / _delegate_to_coder / _verify_fix /
  worktree_scope / _warn_on_uncommitted_changes_if_any / run_phase5_git /
  run_phase6_validation

ALL boundaries mocked — sdk_query is replaced with an async-generator stub
(real TextBlock/ToolUseBlock/AssistantMessage blocks; spec'd ResultMessage/
RateLimitEvent), and every collaborator (FixExecutor, GitStrategist, GitOps,
WorktreeContext, PlanWriter, create_agentic_job, lupin_app.main, run_pytest,
the safety hooks, cosa_interface voice gates) is patched. NO real SDK / LLM /
git / subprocess / network. Zero spend.

quick_smoke_test + __main__ are coverage-excluded by repo config.

Created 2026-05-31 by Rachel 🕊️ (CoSA coverage campaign, TFE lane).
"""

import sys
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.test_fix_expediter.orchestrator as orch_mod
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.state import (
    TFEPhase, FailureCluster, TestDiagnosisResult, TFEProposedFix,
    VoiceGateTimeoutError, StalledException, TFE_PHASE_ORDINALS,
)
from cosa.agents.bug_fix_expediter.state import FixResult
from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock, ResultMessage, RateLimitEvent


# ----------------------------------------------------------------------------
# Builders + SDK stubs
# ----------------------------------------------------------------------------
def _ctx( **over ):
    base = dict(
        source_test_suite_job_id="ts-abc", snapshot_path="p",
        snapshot={ "schema_version": "1.0" }, suites_run=[ "unit" ],
        summary={ "all_passed": False, "total_failed": 2, "total_errors": 0 },
        failures=[ { "classname": "src.tests.test_a.TestA", "name": "t1",
                     "traceback": 'File "src/a.py", line 1, in f', "message": "boom" } ],
        original_test_types=[ "unit" ], original_pytest_args=[],
        user_id="u1", user_email="t@t.com", session_id="s1",
    )
    base.update( over )
    from cosa.agents.test_fix_expediter.state import TestRemediationContext
    return TestRemediationContext( **base )


def _orch( config=None, ctx=None, silence_notify=True, **over ):
    base = dict(
        remediation_context = ctx if ctx is not None else _ctx(),
        config              = config if config is not None else TestFixExpediterConfig(),
        user_id="u1", user_email="t@t.com", session_id="s1",
        job_id="tfe-test1", dry_run=False, debug=False, verbose=False,
    )
    base.update( over )
    o = TFEOrchestrator( **base )
    if silence_notify:
        o._notify = AsyncMock()
    return o


def _prop( cid="C1", title="T", fix_type="code_patch", conf=0.8, changes=None ):
    return TFEProposedFix( cluster_id=cid, title=title, fix_type=fix_type, confidence=conf,
                           description="d", changes=changes if changes is not None else [] )


def _diag( cid="C1", conf=0.8, cat="code_bug" ):
    return TestDiagnosisResult( cluster_id=cid, root_cause="rc", error_category=cat,
                                confidence=conf, evidence=[ "e" ], affected_components=[ "f.py" ] )


def _cluster( cid="C1" ):
    return FailureCluster( cluster_id=cid, failure_indices=[ 0 ], shared_error_signature="sig",
                           affected_files_guess=[ "src/a.py" ] )


def _sdk_stub( messages ):
    """Return a stub matching sdk_query(prompt=, options=) → async iterator."""
    async def _gen( prompt=None, options=None ):
        for m in messages:
            yield m
    return _gen


def _assistant( *blocks ):
    return AssistantMessage( content=list( blocks ), model="claude-x" )


def run( coro ):
    return asyncio.run( coro )


# ============================================================================
# run_phase0_cluster
# ============================================================================
class TestPhase0:
    def test_resume_short_circuit( self ):
        o = _orch( debug=True )
        o.clusters = [ _cluster() ]
        o.set_resume_phase( TFE_PHASE_ORDINALS[ TFEPhase.CLUSTERING ] )
        out = run( o.run_phase0_cluster() )
        assert out == o.clusters
        assert o.current_phase == TFEPhase.CLUSTERING

    def test_normal_clustering( self ):
        o = _orch()
        out = run( o.run_phase0_cluster() )
        assert len( out ) == 1            # one failure -> one heuristic cluster
        assert o.current_phase == TFEPhase.CLUSTERING


# ============================================================================
# run_phase1_diagnose + _diagnose_cluster
# ============================================================================
class TestPhase1:
    def test_resume_short_circuit( self ):
        o = _orch( debug=True )
        o.diagnoses = { "C1": _diag() }
        o.set_resume_phase( TFE_PHASE_ORDINALS[ TFEPhase.DIAGNOSING ] )
        out = run( o.run_phase1_diagnose() )
        assert out == o.diagnoses

    def test_no_clusters_returns_empty( self ):
        o = _orch()
        o.clusters = []
        assert run( o.run_phase1_diagnose() ) == {}

    def test_sdk_unavailable_fallback( self ):
        o = _orch()
        o.clusters = [ _cluster( "C1" ), _cluster( "C2" ) ]
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            out = run( o.run_phase1_diagnose() )
        assert set( out.keys() ) == { "C1", "C2" }
        assert all( d.confidence == 0.1 for d in out.values() )

    def test_normal_loop_with_debug( self ):
        o = _orch( debug=True )
        o.clusters = [ _cluster( "C1" ), _cluster( "C2" ) ]   # 2 clusters -> loop back-edge (397->384)
        with patch.object( o, "_diagnose_cluster",
                           AsyncMock( side_effect=[ _diag( "C1", 0.9 ), _diag( "C2", 0.7 ) ] ) ):
            out = run( o.run_phase1_diagnose() )
        assert out[ "C1" ].confidence == 0.9 and out[ "C2" ].confidence == 0.7

    def test_normal_loop_debug_off( self ):
        # debug=False -> the `if self.debug` print is skipped, loop continues (397->384 arc)
        o = _orch( debug=False )
        o.clusters = [ _cluster( "C1" ), _cluster( "C2" ) ]
        with patch.object( o, "_diagnose_cluster",
                           AsyncMock( side_effect=[ _diag( "C1", 0.9 ), _diag( "C2", 0.7 ) ] ) ):
            out = run( o.run_phase1_diagnose() )
        assert set( out.keys() ) == { "C1", "C2" }

    def test_cancel_breaks_loop( self ):
        o = _orch()
        o.clusters = [ _cluster( "C1" ) ]
        o.request_stop()
        with patch.object( o, "_diagnose_cluster", AsyncMock( return_value=_diag() ) ) as dc:
            out = run( o.run_phase1_diagnose() )
        dc.assert_not_called()            # cancelled before diagnosing
        assert out == {}

    def test_diagnose_cluster_threshold_break( self ):
        o = _orch( debug=True, config=TestFixExpediterConfig( max_diagnosis_iterations=3,
                                                              min_diagnosis_confidence=0.65 ) )
        raw = '{"cluster_id":"C1","root_cause":"rc","error_category":"code_bug","confidence":0.9}'
        with patch.object( o, "_delegate_to_lead_diagnosis", AsyncMock( return_value=raw ) ) as d:
            out = run( o._diagnose_cluster( _cluster( "C1" ) ) )
        assert out.confidence == 0.9
        assert d.await_count == 1         # high confidence -> stop after first iteration

    def test_diagnose_cluster_none_then_high_then_lower( self ):
        # None (continue) -> 0.6 (sets best) -> 0.3 (does NOT beat best: 459->462 arc).
        o = _orch( config=TestFixExpediterConfig( max_diagnosis_iterations=3,
                                                  min_diagnosis_confidence=0.99 ) )
        hi  = '{"cluster_id":"C1","root_cause":"a","error_category":"code_bug","confidence":0.6}'
        lo  = '{"cluster_id":"C1","root_cause":"b","error_category":"code_bug","confidence":0.3}'
        with patch.object( o, "_delegate_to_lead_diagnosis",
                           AsyncMock( side_effect=[ None, hi, lo ] ) ):
            out = run( o._diagnose_cluster( _cluster( "C1" ) ) )
        assert out.confidence == 0.6      # best retained; lower attempt did not replace it

    def test_diagnose_cluster_all_none_fallback( self ):
        o = _orch( config=TestFixExpediterConfig( max_diagnosis_iterations=2 ) )
        with patch.object( o, "_delegate_to_lead_diagnosis", AsyncMock( return_value=None ) ):
            out = run( o._diagnose_cluster( _cluster( "C1" ) ) )
        assert out.confidence == 0.1 and out.error_category == "unknown"

    def test_diagnose_cluster_cancel_breaks( self ):
        o = _orch( config=TestFixExpediterConfig( max_diagnosis_iterations=3 ) )
        o.request_stop()
        with patch.object( o, "_delegate_to_lead_diagnosis", AsyncMock() ) as d:
            out = run( o._diagnose_cluster( _cluster( "C1" ) ) )
        d.assert_not_called()
        assert out.confidence == 0.1      # no attempts -> fallback


# ============================================================================
# _delegate_to_lead_diagnosis (SDK iteration)
# ============================================================================
class TestDelegateDiagnosis:
    def test_collects_text_and_handles_all_message_types( self ):
        o = _orch()
        # A content block that is neither Text nor ToolUse -> elif-false fall-through (499->496).
        # A message that is none of the 4 known types -> elif-false fall-through (508->491).
        msgs = [
            _assistant( ToolUseBlock( id="t1", name="Grep", input={} ), MagicMock(), TextBlock( text="hello " ) ),
            TextBlock( text="world" ),
            MagicMock( spec=RateLimitEvent ),
            MagicMock(),                       # unknown message type
            MagicMock( spec=ResultMessage ),
        ]
        with patch.object( orch_mod, "sdk_query", _sdk_stub( msgs ) ):
            out = run( o._delegate_to_lead_diagnosis( "prompt" ) )
        assert out == "hello world"

    def test_empty_response_returns_none( self ):
        o = _orch()
        with patch.object( orch_mod, "sdk_query", _sdk_stub( [ _assistant( TextBlock( text="   " ) ) ] ) ):
            assert run( o._delegate_to_lead_diagnosis( "p" ) ) is None

    def test_cancel_mid_iteration( self ):
        o = _orch()
        o.request_stop()
        with patch.object( orch_mod, "sdk_query", _sdk_stub( [ _assistant( TextBlock( text="x" ) ) ] ) ):
            assert run( o._delegate_to_lead_diagnosis( "p" ) ) is None

    def test_exception_returns_none_debug_on( self ):
        o = _orch( debug=True )      # debug -> traceback.print_exc arc (518->519)
        def _boom( prompt=None, options=None ):
            raise RuntimeError( "sdk error" )
        with patch.object( orch_mod, "sdk_query", _boom ):
            assert run( o._delegate_to_lead_diagnosis( "p" ) ) is None

    def test_exception_returns_none_debug_off( self ):
        o = _orch( debug=False )     # no-debug -> skips traceback print (518->521)
        def _boom( prompt=None, options=None ):
            raise RuntimeError( "sdk error" )
        with patch.object( orch_mod, "sdk_query", _boom ):
            assert run( o._delegate_to_lead_diagnosis( "p" ) ) is None


# ============================================================================
# run_phase2_propose
# ============================================================================
class TestPhase2:
    def test_resume_short_circuit_voice_gate_success( self ):
        o = _orch( debug=True )
        o.proposed_fixes = [ _prop() ]
        o.set_resume_phase( TFE_PHASE_ORDINALS[ TFEPhase.PROPOSING ] )
        with patch.object( o, "_proposal_voice_gate", AsyncMock( return_value=[ _prop() ] ) ):
            proposed, selected, plan = run( o.run_phase2_propose() )
        assert len( selected ) == 1

    def test_resume_short_circuit_voice_gate_timeout_stalls( self ):
        o = _orch()
        o.proposed_fixes = [ _prop() ]
        o.set_resume_phase( TFE_PHASE_ORDINALS[ TFEPhase.PROPOSING ] )
        with patch.object( o, "_proposal_voice_gate", AsyncMock( side_effect=VoiceGateTimeoutError( "t" ) ) ), \
             patch.object( o, "save_checkpoint", return_value={ "stall_reason": "x" } ):
            with pytest.raises( StalledException ):
                run( o.run_phase2_propose() )

    def test_resume_short_circuit_cancelled_skips_gate( self ):
        o = _orch()
        o.proposed_fixes = [ _prop() ]
        o.set_resume_phase( TFE_PHASE_ORDINALS[ TFEPhase.PROPOSING ] )
        o.request_stop()
        with patch.object( o, "_proposal_voice_gate", AsyncMock() ) as gate:
            proposed, selected, plan = run( o.run_phase2_propose() )
        gate.assert_not_called()

    def test_no_clusters_or_diagnoses_skips( self ):
        o = _orch()
        o.clusters = []; o.diagnoses = {}
        proposed, selected, plan = run( o.run_phase2_propose() )
        assert proposed == [] and selected == [] and plan is None

    def test_sdk_unavailable_skips( self ):
        o = _orch()
        o.clusters = [ _cluster() ]; o.diagnoses = { "C1": _diag() }
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            proposed, selected, plan = run( o.run_phase2_propose() )
        assert proposed == [] and plan is None

    def test_normal_with_plandoc_and_gate( self ):
        o = _orch()
        o.clusters  = [ _cluster( "C1" ), _cluster( "C2" ) ]
        o.diagnoses = { "C1": _diag( "C1" ) }   # C2 has NO diagnosis -> skipped
        with patch.object( o, "_propose_for_cluster", AsyncMock( return_value=[ _prop( "C1" ) ] ) ), \
             patch.object( o, "_write_multi_cluster_plan_doc", return_value="io/plan.md" ), \
             patch.object( o, "_proposal_voice_gate", AsyncMock( return_value=[ _prop( "C1" ) ] ) ):
            proposed, selected, plan = run( o.run_phase2_propose() )
        assert len( proposed ) == 1 and plan == "io/plan.md"
        assert len( selected ) == 1

    def test_plandoc_write_failure_swallowed( self ):
        o = _orch()
        o.clusters  = [ _cluster( "C1" ) ]
        o.diagnoses = { "C1": _diag( "C1" ) }
        with patch.object( o, "_propose_for_cluster", AsyncMock( return_value=[ _prop( "C1" ) ] ) ), \
             patch.object( o, "_write_multi_cluster_plan_doc", side_effect=RuntimeError( "disk" ) ), \
             patch.object( o, "_proposal_voice_gate", AsyncMock( return_value=[] ) ):
            proposed, selected, plan = run( o.run_phase2_propose() )
        assert plan is None              # write failed -> stays None

    def test_voice_gate_timeout_stalls( self ):
        o = _orch()
        o.clusters  = [ _cluster( "C1" ) ]
        o.diagnoses = { "C1": _diag( "C1" ) }
        with patch.object( o, "_propose_for_cluster", AsyncMock( return_value=[ _prop( "C1" ) ] ) ), \
             patch.object( o, "_write_multi_cluster_plan_doc", return_value="io/p.md" ), \
             patch.object( o, "_proposal_voice_gate", AsyncMock( side_effect=VoiceGateTimeoutError( "t" ) ) ), \
             patch.object( o, "save_checkpoint", return_value={ "stall_reason": "voice_gate_timeout" } ):
            with pytest.raises( StalledException ):
                run( o.run_phase2_propose() )

    def test_cancel_during_proposal_loop( self ):
        o = _orch()
        o.clusters  = [ _cluster( "C1" ) ]
        o.diagnoses = { "C1": _diag( "C1" ) }
        o.request_stop()
        with patch.object( o, "_propose_for_cluster", AsyncMock() ) as pc:
            proposed, selected, plan = run( o.run_phase2_propose() )
        pc.assert_not_called()
        assert proposed == [] and selected == []

    def test_no_proposals_selected_empty( self ):
        # proposals empty -> the `if all_proposals` gate is False -> selected_fixes = []
        o = _orch()
        o.clusters  = [ _cluster( "C1" ) ]
        o.diagnoses = { "C1": _diag( "C1" ) }
        with patch.object( o, "_propose_for_cluster", AsyncMock( return_value=[] ) ):
            proposed, selected, plan = run( o.run_phase2_propose() )
        assert proposed == [] and selected == [] and plan is None


# ============================================================================
# _propose_for_cluster + _delegate_to_lead_proposal
# ============================================================================
class TestProposeForCluster:
    def test_raw_none_returns_empty( self ):
        o = _orch()
        with patch.object( o, "_delegate_to_lead_proposal", AsyncMock( return_value=None ) ):
            out = run( o._propose_for_cluster( _cluster(), _diag() ) )
        assert out == []

    def test_normal_parses_proposals( self ):
        o = _orch()
        raw = '[{"cluster_id":"C1","title":"t","description":"d","fix_type":"code_patch","confidence":0.8}]'
        with patch.object( o, "_delegate_to_lead_proposal", AsyncMock( return_value=raw ) ):
            out = run( o._propose_for_cluster( _cluster( "C1" ), _diag( "C1" ) ) )
        assert len( out ) == 1 and out[ 0 ].title == "t"


class TestDelegateProposal:
    def test_collects_and_handles_types( self ):
        o = _orch()
        # neither-type content block -> 785->782; unknown message type -> 794->777
        msgs = [
            _assistant( ToolUseBlock( id="t", name="Read", input={} ), MagicMock(), TextBlock( text="[" ) ),
            TextBlock( text="]" ),
            MagicMock( spec=RateLimitEvent ),
            MagicMock(),                       # unknown message type
            MagicMock( spec=ResultMessage ),
        ]
        with patch.object( orch_mod, "sdk_query", _sdk_stub( msgs ) ):
            out = run( o._delegate_to_lead_proposal( "p" ) )
        assert out == "[]"

    def test_cancel_breaks( self ):
        o = _orch()
        o.request_stop()
        with patch.object( orch_mod, "sdk_query", _sdk_stub( [ _assistant( TextBlock( text="x" ) ) ] ) ):
            assert run( o._delegate_to_lead_proposal( "p" ) ) is None

    def test_exception_returns_none( self ):
        o = _orch()
        def _boom( prompt=None, options=None ):
            raise RuntimeError( "x" )
        with patch.object( orch_mod, "sdk_query", _boom ):
            assert run( o._delegate_to_lead_proposal( "p" ) ) is None


# ============================================================================
# _write_multi_cluster_plan_doc
# ============================================================================
class TestWritePlanDoc:
    def test_single_category_with_evidence( self ):
        o = _orch()
        o.clusters  = [ _cluster( "C1" ) ]
        o.diagnoses = { "C1": _diag( "C1", cat="code_bug" ) }
        writer = MagicMock()
        writer.write_plan.return_value = "io/plan.md"
        with patch( "cosa.agents.shared.plan_writer.PlanWriter", return_value=writer ):
            out = o._write_multi_cluster_plan_doc( [ _prop( "C1" ) ] )
        assert out == "io/plan.md"
        agg = writer.write_plan.call_args.kwargs[ "diagnosis" ]
        assert agg.error_category == "code_bug"      # single category (not "mixed")

    def test_mixed_categories( self ):
        o = _orch()
        o.clusters  = [ _cluster( "C1" ), _cluster( "C2" ) ]
        o.diagnoses = { "C1": _diag( "C1", cat="code_bug" ), "C2": _diag( "C2", cat="test_bug" ) }
        writer = MagicMock(); writer.write_plan.return_value = "io/p.md"
        with patch( "cosa.agents.shared.plan_writer.PlanWriter", return_value=writer ):
            o._write_multi_cluster_plan_doc( [ _prop( "C1" ), _prop( "C2" ) ] )
        agg = writer.write_plan.call_args.kwargs[ "diagnosis" ]
        assert agg.error_category == "mixed"


# ============================================================================
# voice gates
# ============================================================================
class TestVoiceGates:
    def test_dry_run_auto_selects_all( self ):
        o = _orch( dry_run=True, debug=True )
        props = [ _prop( "C1" ), _prop( "C2" ) ]
        out = run( o._proposal_voice_gate( props ) )
        assert out == props

    def test_per_cluster_mode_dispatch( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_mode="per_cluster" ) )
        with patch.object( o, "_per_cluster_voice_gate", AsyncMock( return_value=[ _prop() ] ) ) as g:
            run( o._proposal_voice_gate( [ _prop() ] ) )
        g.assert_awaited_once()

    def test_aggregate_mode_dispatch( self ):
        o = _orch()
        with patch.object( o, "_aggregate_voice_gate", AsyncMock( return_value=[] ) ) as g:
            run( o._proposal_voice_gate( [ _prop() ] ) )
        g.assert_awaited_once()

    def test_aggregate_selects_by_label( self ):
        o = _orch()
        ci = SimpleNamespace( present_choices=AsyncMock(
            return_value={ "answers": { "Fixes": [ "C1: T" ] } } ) )
        with patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ):
            out = run( o._aggregate_voice_gate( [ _prop( "C1", "T" ), _prop( "C2", "Other" ) ] ) )
        assert [ p.cluster_id for p in out ] == [ "C1" ]

    def test_aggregate_string_answer_coerced_to_list( self ):
        o = _orch()
        ci = SimpleNamespace( present_choices=AsyncMock(
            return_value={ "answers": { "Fixes": "C1: T" } } ) )   # single str, not list
        with patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ):
            out = run( o._aggregate_voice_gate( [ _prop( "C1", "T" ) ] ) )
        assert len( out ) == 1

    def test_aggregate_timeout_applies_policy( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="none" ) )
        ci = SimpleNamespace( present_choices=AsyncMock( side_effect=VoiceGateTimeoutError( "t" ) ) )
        with patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ):
            out = run( o._aggregate_voice_gate( [ _prop() ] ) )
        assert out == []         # policy=none -> empty

    def test_aggregate_generic_exception_applies_the_policy_not_everything( self ):
        """
        Was: fail-open, auto-select all — a failed voice gate applied EVERY
        proposed fix. The timeout branch already deferred to a configured
        policy; a non-timeout failure now does the same instead of bypassing
        it. Row 2b604cdb.
        """
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="none" ) )
        ci = SimpleNamespace( present_choices=AsyncMock( side_effect=RuntimeError( "ws" ) ) )
        with patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ):
            out = run( o._aggregate_voice_gate( [ _prop( "C1" ) ] ) )
        assert out == []         # policy=none -> nothing applied

    def test_per_cluster_yes_no_and_error( self ):
        o = _orch()
        # first yes -> selected; second no -> skipped; third raises -> NOT
        # selected. It used to be selected, under a comment reading "on error,
        # err on the side of applying" — a gate that could not reach a human
        # applied the code change it was asking about. Row 2b604cdb.
        ci = SimpleNamespace( ask_confirmation=AsyncMock(
            side_effect=[ "yes", "no", RuntimeError( "boom" ) ] ) )
        props = [ _prop( "C1" ), _prop( "C2" ), _prop( "C3" ) ]
        with patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ):
            out = run( o._per_cluster_voice_gate( props ) )
        assert [ p.cluster_id for p in out ] == [ "C1" ]


# ============================================================================
# run_phase3_fix
# ============================================================================
class TestPhase3:
    def test_no_selected_skips( self ):
        o = _orch()
        o.selected_fixes = []
        assert run( o.run_phase3_fix() ) == []

    def test_sdk_unavailable_skips( self ):
        o = _orch()
        o.selected_fixes = [ _prop() ]
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            assert run( o.run_phase3_fix() ) == []

    def test_dry_run_synthetic_results( self ):
        o = _orch( dry_run=True )
        # changes is typed list[dict]; one dict has a file, one does not (get("file") None -> skipped)
        o.selected_fixes = [ _prop( "C1", changes=[ { "file": "a.py" }, { "noFile": 1 } ] ) ]
        out = run( o.run_phase3_fix() )
        assert len( out ) == 1 and out[ 0 ].success is True
        assert o.files_changed_by_cluster[ "C1" ] == [ "a.py" ]   # only the dict-with-file

    def test_normal_executor_success( self ):
        o = _orch()
        o.selected_fixes = [ _prop( "C1" ) ]
        o.clusters       = [ _cluster( "C1" ) ]
        o.diagnoses      = { "C1": _diag( "C1" ) }
        fake_exec = MagicMock()
        fake_exec.execute_fix = AsyncMock( return_value=( FixResult( applied=True, success=True, details="ok" ),
                                                          [ "a.py" ] ) )
        with patch( "cosa.agents.shared.fix_executor.FixExecutor", return_value=fake_exec ), \
             patch( "cosa.agents.test_fix_expediter.cosa_interface", SimpleNamespace(), create=True ), \
             patch( "cosa.agents.test_fix_expediter.voice_io", SimpleNamespace(), create=True ):
            out = run( o.run_phase3_fix() )
        assert out[ 0 ].success and o.files_changed_by_cluster[ "C1" ] == [ "a.py" ]

    def test_missing_cluster_or_diagnosis_skipped( self ):
        o = _orch()
        o.selected_fixes = [ _prop( "CX" ) ]   # no matching cluster/diagnosis
        o.clusters       = [ _cluster( "C1" ) ]
        o.diagnoses      = { "C1": _diag( "C1" ) }
        out = run( o.run_phase3_fix() )
        assert out == []

    def test_executor_raises_becomes_failed_result( self ):
        o = _orch()
        o.selected_fixes = [ _prop( "C1" ) ]
        o.clusters       = [ _cluster( "C1" ) ]
        o.diagnoses      = { "C1": _diag( "C1" ) }
        fake_exec = MagicMock()
        fake_exec.execute_fix = AsyncMock( side_effect=RuntimeError( "executor blew up" ) )
        with patch( "cosa.agents.shared.fix_executor.FixExecutor", return_value=fake_exec ), \
             patch( "cosa.agents.test_fix_expediter.cosa_interface", SimpleNamespace(), create=True ), \
             patch( "cosa.agents.test_fix_expediter.voice_io", SimpleNamespace(), create=True ):
            out = run( o.run_phase3_fix() )
        assert out[ 0 ].success is False

    def test_abort_on_failure_when_continue_false( self ):
        o = _orch( config=TestFixExpediterConfig( continue_on_cluster_failure=False ) )
        o.selected_fixes = [ _prop( "C1" ), _prop( "C2" ) ]
        o.clusters       = [ _cluster( "C1" ), _cluster( "C2" ) ]
        o.diagnoses      = { "C1": _diag( "C1" ), "C2": _diag( "C2" ) }
        fake_exec = MagicMock()
        fake_exec.execute_fix = AsyncMock( return_value=( FixResult( applied=True, success=False, details="no" ), [] ) )
        with patch( "cosa.agents.shared.fix_executor.FixExecutor", return_value=fake_exec ), \
             patch( "cosa.agents.test_fix_expediter.cosa_interface", SimpleNamespace(), create=True ), \
             patch( "cosa.agents.test_fix_expediter.voice_io", SimpleNamespace(), create=True ):
            out = run( o.run_phase3_fix() )
        assert len( out ) == 1            # aborted after first failure

    def test_cancel_breaks_loop( self ):
        o = _orch()
        o.selected_fixes = [ _prop( "C1" ) ]
        o.clusters       = [ _cluster( "C1" ) ]
        o.diagnoses      = { "C1": _diag( "C1" ) }
        o.request_stop()
        out = run( o.run_phase3_fix() )
        assert out == []

    def test_notify_for_executor_bridges( self ):
        o = _orch()
        run( o._notify_for_executor( MagicMock(), "msg", priority="high", abstract="a" ) )
        o._notify.assert_awaited_once_with( "msg", priority="high", abstract="a" )


# ============================================================================
# _delegate_to_coder + _verify_fix
# ============================================================================
class TestCoderAndVerify:
    def test_coder_unavailable_returns_empty( self ):
        o = _orch()
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            assert run( o._delegate_to_coder( MagicMock(), "p", MagicMock(), MagicMock() ) ) == ( "", [] )

    def test_coder_tracks_files_and_handles_types( self ):
        o = _orch()
        guard = MagicMock()
        # Edit (not last block -> 1487->1484), dup Edit, Bash (non-edit), trailing TextBlock block.
        # RateLimitEvent before ResultMessage -> outer back-edge (1502->1477).
        msgs = [
            _assistant(
                ToolUseBlock( id="1", name="Edit", input={ "file_path": "a.py" } ),
                ToolUseBlock( id="2", name="Edit", input={ "file_path": "a.py" } ),   # dup -> not re-added
                ToolUseBlock( id="3", name="Bash", input={ "command": "ls" } ),       # non-edit tool
                MagicMock(),                                                           # neither-type block -> 1487->1484
                TextBlock( text="working " ),
            ),
            TextBlock( text="done" ),
            MagicMock( spec=RateLimitEvent ),
            MagicMock(),                                                               # unknown message -> 1502->1477
            MagicMock( spec=ResultMessage, text="result-text" ),
        ]
        with patch.object( orch_mod, "sdk_query", _sdk_stub( msgs ) ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ):
            text, files = run( o._delegate_to_coder( MagicMock(), "p", guard, MagicMock() ) )
        assert text == "working done" and files == [ "a.py" ]
        guard.check_iteration.assert_called_once()

    def test_coder_cancel_breaks( self ):
        o = _orch()
        o.request_stop()
        with patch.object( orch_mod, "sdk_query", _sdk_stub( [ _assistant( TextBlock( text="x" ) ) ] ) ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ):
            text, files = run( o._delegate_to_coder( MagicMock(), "p", MagicMock(), MagicMock() ) )
        assert text == "" and files == []

    def test_coder_safety_limit_reraises( self ):
        o = _orch()
        guard = MagicMock(); guard.check_timeout.side_effect = orch_mod.SafetyLimitError( "limit" )
        with patch.object( orch_mod, "sdk_query", _sdk_stub( [ _assistant( TextBlock( text="x" ) ) ] ) ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ):
            with pytest.raises( orch_mod.SafetyLimitError ):
                run( o._delegate_to_coder( MagicMock(), "p", guard, MagicMock() ) )

    def test_coder_generic_exception_returns_empty( self ):
        o = _orch()
        def _boom( prompt=None, options=None ):
            raise RuntimeError( "sdk" )
        with patch.object( orch_mod, "sdk_query", _boom ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ):
            assert run( o._delegate_to_coder( MagicMock(), "p", MagicMock(), MagicMock() ) ) == ( "", [] )

    def test_verify_unavailable( self ):
        o = _orch()
        with patch.object( orch_mod, "SAFETY_AVAILABLE", False ):
            passed, out = run( o._verify_fix( MagicMock(), _prop(), "co", [], MagicMock(), MagicMock() ) )
        assert passed is False

    def test_verify_passes_self_report( self ):
        o = _orch()
        msgs = [ _assistant( TextBlock( text="All tests pass" ) ) ]
        with patch.object( orch_mod, "sdk_query", _sdk_stub( msgs ) ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ):
            passed, out = run( o._verify_fix( MagicMock(), _prop(), "co", [], MagicMock(), MagicMock() ) )
        assert passed is True

    def test_verify_rich_blocks_and_pytest_passes( self ):
        # Exercises: non-Edit tool block (1566->1571), dup file_path skip (1568->1570),
        # ToolUseBlock not last in content (1565->1562), bare TextBlock msg (1575),
        # RateLimitEvent not last (1576->1558), a non-test file FIRST in test_files
        # (1592->1591 continue), and run_pytest PASSING (1594->1596).
        o = _orch( debug=True )
        msgs = [
            _assistant(
                ToolUseBlock( id="1", name="Edit", input={ "file_path": "src/a.py" } ),          # non-test file, first
                ToolUseBlock( id="2", name="Edit", input={ "file_path": "src/tests/test_x.py" } ),# test file
                ToolUseBlock( id="3", name="Edit", input={ "file_path": "src/tests/test_x.py" } ),# dup -> 1568->1570
                ToolUseBlock( id="4", name="Bash", input={ "command": "ls" } ),                   # non-edit -> 1566->1571
                MagicMock(),                                                                       # neither-type block -> 1565->1562
                TextBlock( text="pass" ),                                                          # trailing block
            ),
            TextBlock( text=" report" ),       # bare TextBlock message -> 1575
            MagicMock( spec=RateLimitEvent ),  # not last -> 1576->1558
            MagicMock( spec=ResultMessage ),
        ]
        run_res = SimpleNamespace( passed=True, passed_count=2, total_tests=2 )
        with patch.object( orch_mod, "sdk_query", _sdk_stub( msgs ) ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
             patch.object( orch_mod, "run_pytest", AsyncMock( return_value=run_res ) ):
            passed, out = run( o._verify_fix( MagicMock(), _prop(), "co", [], MagicMock(), MagicMock() ) )
        assert passed is True            # self-report pass + pytest pass

    def test_verify_independent_pytest_overrides_to_fail( self ):
        o = _orch( debug=True )
        # Tester edits a test file + self-reports pass, but independent pytest fails -> override
        msgs = [
            _assistant(
                TextBlock( text="pass" ),
                ToolUseBlock( id="1", name="Edit", input={ "file_path": "src/tests/test_x.py" } ),
            ),
            MagicMock( spec=RateLimitEvent ),
        ]
        run_res = SimpleNamespace( passed=False, passed_count=0, total_tests=2 )
        with patch.object( orch_mod, "sdk_query", _sdk_stub( msgs ) ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
             patch.object( orch_mod, "run_pytest", AsyncMock( return_value=run_res ) ):
            passed, out = run( o._verify_fix( MagicMock(), _prop(), "co", [], MagicMock(), MagicMock() ) )
        assert passed is False

    def test_verify_safety_limit_reraises( self ):
        o = _orch()
        guard = MagicMock(); guard.check_timeout.side_effect = orch_mod.SafetyLimitError( "limit" )
        with patch.object( orch_mod, "sdk_query", _sdk_stub( [ _assistant( TextBlock( text="x" ) ) ] ) ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ):
            with pytest.raises( orch_mod.SafetyLimitError ):
                run( o._verify_fix( MagicMock(), _prop(), "co", [], guard, MagicMock() ) )

    def test_verify_generic_exception( self ):
        o = _orch()
        def _boom( prompt=None, options=None ):
            raise RuntimeError( "sdk" )
        with patch.object( orch_mod, "sdk_query", _boom ), \
             patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p ):
            passed, out = run( o._verify_fix( MagicMock(), _prop(), "co", [], MagicMock(), MagicMock() ) )
        assert passed is False and "Verification error" in out


# ============================================================================
# worktree_scope + _warn_on_uncommitted_changes_if_any
# ============================================================================
class TestWorktreeScope:
    def _wt_ctx( self, enabled, path="/tmp/wt" ):
        wt = SimpleNamespace( enabled=enabled, path=path )
        @asynccontextmanager
        async def _cm( *a, **k ):
            yield wt
        return _cm

    def test_enabled_sets_and_clears_cwd( self ):
        o = _orch( debug=True )
        with patch( "cosa.agents.shared.worktree_context.WorktreeContext", self._wt_ctx( True ) ):
            async def _use():
                async with o.worktree_scope():
                    assert o._worktree_cwd == "/tmp/wt"
            run( _use() )
        assert o._worktree_cwd is None      # cleared in finally

    def test_disabled_warns_and_noops( self ):
        o = _orch()
        with patch( "cosa.agents.shared.worktree_context.WorktreeContext", self._wt_ctx( False ) ), \
             patch.object( o, "_warn_on_uncommitted_changes_if_any", AsyncMock() ) as warn:
            async def _use():
                async with o.worktree_scope():
                    assert o._worktree_cwd is None
            run( _use() )
        warn.assert_awaited_once()

    def test_warn_dirty_tree_logs( self ):
        o = _orch()
        proc = MagicMock()
        proc.communicate = AsyncMock( return_value=( b" M file.py\n", b"" ) )
        with patch( "asyncio.create_subprocess_exec", AsyncMock( return_value=proc ) ):
            run( o._warn_on_uncommitted_changes_if_any() )   # no raise

    def test_warn_clean_tree_no_log( self ):
        o = _orch()
        proc = MagicMock()
        proc.communicate = AsyncMock( return_value=( b"", b"" ) )
        with patch( "asyncio.create_subprocess_exec", AsyncMock( return_value=proc ) ):
            run( o._warn_on_uncommitted_changes_if_any() )

    def test_warn_exception_swallowed( self ):
        o = _orch( debug=True )
        with patch( "asyncio.create_subprocess_exec", AsyncMock( side_effect=OSError( "no git" ) ) ):
            run( o._warn_on_uncommitted_changes_if_any() )   # must not raise


# ============================================================================
# run_phase5_git
# ============================================================================
class TestPhase5:
    def _setup( self, o, success=True, files=None ):
        o.selected_fixes = [ _prop( "C1" ) ]
        o.fix_results    = [ FixResult( applied=True, success=success, details="x" ) ]
        o.files_changed_by_cluster = { "C1": files if files is not None else [ "a.py" ] }

    def test_no_successful_pairs_skips( self ):
        o = _orch()
        self._setup( o, success=False )
        out = run( o.run_phase5_git() )
        assert out[ "branch_name" ] is None and out[ "commit_hashes" ] == []

    def test_successful_but_no_files_skips( self ):
        o = _orch()
        self._setup( o, success=True, files=[] )   # no files -> filtered out
        out = run( o.run_phase5_git() )
        assert out[ "branch_name" ] is None

    def test_dry_run_synthetic( self ):
        o = _orch( dry_run=True )
        self._setup( o )
        out = run( o.run_phase5_git() )
        assert out[ "git_strategy" ] == "dry_run"
        assert o.branch_name == out[ "branch_name" ]

    def test_gitops_import_error( self ):
        o = _orch()
        self._setup( o )
        with patch.dict( sys.modules, { "cosa.agents.bug_fix_expediter.git_ops": None } ):
            out = run( o.run_phase5_git() )
        assert out[ "error" ] is not None and out[ "branch_name" ] is None

    def test_normal_success( self ):
        o = _orch()
        self._setup( o )
        # commit_and_pr_multi invokes the inline notify_fn closure (covers its body, line ~1926)
        async def _commit( **kw ):
            await kw[ "notify_fn" ]( "committing...", priority="low" )
            return { "git_strategy": "L1", "branch_name": "fix/x", "commit_hashes": [ "h1" ],
                     "pr_url": "http://pr", "error": None }
        strategist = MagicMock()
        strategist.commit_and_pr_multi = _commit
        with patch( "cosa.agents.bug_fix_expediter.git_ops.GitOps", MagicMock() ), \
             patch( "cosa.agents.shared.git_strategist.GitStrategist", return_value=strategist ):
            out = run( o.run_phase5_git() )
        assert out[ "branch_name" ] == "fix/x"
        assert o.commit_hashes == [ "h1" ]

    def test_normal_with_error_summary( self ):
        o = _orch()
        self._setup( o )
        strategist = MagicMock()
        strategist.commit_and_pr_multi = AsyncMock( return_value={
            "git_strategy": None, "branch_name": None, "commit_hashes": [],
            "pr_url": None, "error": "push rejected",
        } )
        with patch( "cosa.agents.bug_fix_expediter.git_ops.GitOps", MagicMock() ), \
             patch( "cosa.agents.shared.git_strategist.GitStrategist", return_value=strategist ):
            out = run( o.run_phase5_git() )
        assert out[ "error" ] == "push rejected"


# ============================================================================
# run_phase6_validation
# ============================================================================
class TestPhase6:
    def _setup( self, o, success=True ):
        o.fix_results = [ FixResult( applied=True, success=success, details="x" ) ]

    def test_no_successful_returns_none( self ):
        o = _orch()
        self._setup( o, success=False )
        assert run( o.run_phase6_validation() ) is None

    def test_dry_run( self ):
        o = _orch( dry_run=True )
        self._setup( o )
        assert run( o.run_phase6_validation() ) == "dry-run-skipped"

    def test_factory_import_error( self ):
        o = _orch()
        self._setup( o )
        with patch.dict( sys.modules, { "cosa.rest.agentic_job_factory": None } ):
            assert run( o.run_phase6_validation() ) is None

    def test_factory_raises( self ):
        o = _orch()
        self._setup( o )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", side_effect=RuntimeError( "x" ) ):
            assert run( o.run_phase6_validation() ) is None

    def test_factory_returns_none( self ):
        o = _orch()
        self._setup( o )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=None ):
            assert run( o.run_phase6_validation() ) is None

    def test_success_submits_job_with_pytest_args( self ):
        """Step 12: Phase 6 submits through lupin_app.main.ask_flow, not jobs_todo_queue.

        The validation job is PREBUILT — the factory above named the command — so it
        takes `submit`, and the queue on the app module must stay untouched.
        """
        o = _orch( ctx=_ctx( original_pytest_args=[ "-k", "auth" ] ) )
        self._setup( o )
        vjob = SimpleNamespace( id_hash="ts-rerun", metadata=None )   # metadata None -> guard inits it
        flow = MagicMock()
        todo = MagicMock()
        main_mod = SimpleNamespace( ask_flow=flow, jobs_todo_queue=todo )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=vjob ), \
             patch.dict( sys.modules, { "lupin_app.main": main_mod } ):
            out = run( o.run_phase6_validation() )
        assert out == "ts-rerun"
        assert vjob.metadata[ "triggered_by_tfe" ] == "tfe-test1"
        flow.submit.assert_called_once()
        assert flow.submit.call_args.kwargs[ "job" ] is vjob
        todo.push.assert_not_called()

    def test_flow_none_raises_caught( self ):
        o = _orch()
        self._setup( o )
        vjob = SimpleNamespace( id_hash="ts-rerun", metadata={} )
        todo = MagicMock()
        main_mod = SimpleNamespace( ask_flow=None, jobs_todo_queue=todo )   # None -> RuntimeError -> caught
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=vjob ), \
             patch.dict( sys.modules, { "lupin_app.main": main_mod } ):
            assert run( o.run_phase6_validation() ) is None
        todo.push.assert_not_called()   # no fallback route onto the queue

    def test_flow_submit_raises_caught( self ):
        o = _orch()
        self._setup( o )
        vjob = SimpleNamespace( id_hash="ts-rerun", metadata={} )
        flow = MagicMock(); flow.submit.side_effect = RuntimeError( "flow broken" )
        main_mod = SimpleNamespace( ask_flow=flow, jobs_todo_queue=MagicMock() )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=vjob ), \
             patch.dict( sys.modules, { "lupin_app.main": main_mod } ):
            assert run( o.run_phase6_validation() ) is None
