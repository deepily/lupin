#!/usr/bin/env python3
"""
Unit tests for cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator —
the SYNCHRONOUS + light-async HELPER surface (paired with
test_orchestrator_phases.py which drives the async phase methods).

Covers: __init__, _is_cancelled/request_stop, _notify, save/load_checkpoint,
set_resume_phase, the JSON parsers (_parse_diagnosis_result /
_extract_last_json_object / _fallback_diagnosis / _parse_proposal_result /
_parse_proposal_json / _extract_last_json_array), the ClaudeAgentOptions
builders, _apply_voice_gate_timeout_policy / _delegate_to_predictor, the
render helpers (_render_proposal_abstract / _render_single_proposal /
_render_git_summary / _render_validation_abstract / render_worktree_artifacts_abstract),
_summarize_tool_use, _derive_budget_tier, _suite_abbrev,
_build_tfe_commit_message / _build_tfe_pr_body, _resolve_tfe_trust_level,
_resolve_rerun_test_types.

ALL boundaries mocked — no SDK calls, no LLM, no git, no network. The SDK
ClaudeAgentOptions ctor is real (cheap dataclass); build_can_use_tool is
patched on the orchestrator module. Zero spend.

quick_smoke_test + __main__ are coverage-excluded by repo config.

Created 2026-05-31 by Rachel 🕊️ (CoSA coverage campaign, TFE lane).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.test_fix_expediter.orchestrator as orch_mod
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.state import (
    TFEPhase, FailureCluster, TestDiagnosisResult, TFEProposedFix,
    VoiceGateTimeoutError,
)
from cosa.agents.bug_fix_expediter.state import FixResult


# ----------------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------------
def _ctx( **over ):
    base = dict(
        source_test_suite_job_id="ts-abc", snapshot_path="p",
        snapshot={ "schema_version": "1.0" }, suites_run=[ "unit" ],
        summary={ "all_passed": False, "total_failed": 2, "total_errors": 0 },
        failures=[ { "classname": "A", "name": "t", "traceback": "" } ],
        original_test_types=[ "unit" ], original_pytest_args=[],
        user_id="u1", user_email="t@t.com", session_id="s1",
    )
    base.update( over )
    from cosa.agents.test_fix_expediter.state import TestRemediationContext
    return TestRemediationContext( **base )


def _orch( config=None, ctx=None, **over ):
    base = dict(
        remediation_context = ctx if ctx is not None else _ctx(),
        config              = config if config is not None else TestFixExpediterConfig(),
        user_id="u1", user_email="t@t.com", session_id="s1",
        job_id="tfe-test1", dry_run=False, debug=False, verbose=False,
    )
    base.update( over )
    return TFEOrchestrator( **base )


def _prop( cid="C1", title="T", fix_type="code_patch", conf=0.8, risk="low",
           effort="minutes", desc="d", changes=None ):
    return TFEProposedFix(
        cluster_id=cid, title=title, fix_type=fix_type, confidence=conf,
        risk_level=risk, estimated_effort=effort, description=desc,
        changes=changes if changes is not None else [],
    )


def _diag( cid="C1", conf=0.8, cat="code_bug" ):
    return TestDiagnosisResult( cluster_id=cid, root_cause="rc", error_category=cat,
                                confidence=conf, evidence=[ "e" ], affected_components=[ "f.py" ] )


# ============================================================================
# __init__ / cancellation
# ============================================================================
class TestInitAndCancel:
    def test_init_defaults( self ):
        o = _orch()
        assert o.clusters == [] and o.diagnoses == {} and o.proposed_fixes == []
        assert o.current_phase == TFEPhase.LOADING
        assert o._resume_from_ordinal is None
        assert o._worktree_cwd is None
        assert o._current_budget_tier == "medium"
        assert o._stop_requested is False

    def test_request_stop_and_is_cancelled( self ):
        o = _orch()
        assert o._is_cancelled() is False
        o.request_stop()
        assert o._is_cancelled() is True


# ============================================================================
# _notify
# ============================================================================
class TestNotify:
    def test_delegates_to_cosa_interface( self ):
        o = _orch()
        ci = SimpleNamespace( notify_progress=AsyncMock() )
        vio = SimpleNamespace()
        with patch.dict( "sys.modules" ), \
             patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ), \
             patch( "cosa.agents.test_fix_expediter.voice_io", vio, create=True ):
            asyncio.run( o._notify( "hi", priority="medium", abstract="abs" ) )
        ci.notify_progress.assert_awaited_once_with( "hi", priority="medium", abstract="abs", job_id="tfe-test1" )

    def test_dry_run_debug_breadcrumb( self, capsys ):
        o = _orch( dry_run=True, debug=True )
        o.current_phase = TFEPhase.CLUSTERING
        ci = SimpleNamespace( notify_progress=AsyncMock() )
        with patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ), \
             patch( "cosa.agents.test_fix_expediter.voice_io", SimpleNamespace(), create=True ):
            asyncio.run( o._notify( "breadcrumb" ) )
        assert "breadcrumb" in capsys.readouterr().out

    def test_exception_swallowed_with_debug_print( self, capsys ):
        o = _orch( debug=True )
        ci = SimpleNamespace( notify_progress=AsyncMock( side_effect=RuntimeError( "ws down" ) ) )
        with patch( "cosa.agents.test_fix_expediter.cosa_interface", ci, create=True ), \
             patch( "cosa.agents.test_fix_expediter.voice_io", SimpleNamespace(), create=True ):
            asyncio.run( o._notify( "x" ) )   # must not raise
        assert "notify error" in capsys.readouterr().out


# ============================================================================
# save_checkpoint / load_checkpoint / set_resume_phase
# ============================================================================
class TestCheckpoint:
    def test_save_checkpoint_serializes_state( self ):
        o = _orch()
        o.current_phase = TFEPhase.PROPOSING
        o.clusters       = [ FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="s" ) ]
        o.diagnoses      = { "C1": _diag() }
        o.proposed_fixes = [ _prop() ]
        o.selected_fixes = [ _prop() ]
        # fix_results: one model_dump-able + one plain dict (covers both arcs)
        o.fix_results    = [ FixResult( applied=True, success=True, details="ok" ), { "raw": 1 } ]
        o.last_plan_path = "io/plan.md"
        ckpt = o.save_checkpoint()
        assert ckpt[ "phase_name" ] == "proposing"
        assert ckpt[ "phase_ordinal" ] == 3
        assert ckpt[ "stall_reason" ] == "voice_gate_timeout"
        assert ckpt[ "artifacts" ][ "plan_path" ] == "io/plan.md"
        assert len( ckpt[ "state_snapshot" ][ "clusters" ] ) == 1
        assert ckpt[ "state_snapshot" ][ "fix_results" ][ 1 ] == { "raw": 1 }

    def test_save_checkpoint_phase_not_in_ordinals_is_minus_one( self ):
        o = _orch()
        o.current_phase = TFEPhase.WAITING_CONFIRMATION   # not in TFE_PHASE_ORDINALS
        ckpt = o.save_checkpoint()
        assert ckpt[ "phase_ordinal" ] == -1
        assert "plan_path" not in ckpt[ "artifacts" ]     # last_plan_path None

    def test_load_checkpoint_round_trip( self ):
        o = _orch()
        o.current_phase = TFEPhase.PROPOSING
        o.clusters       = [ FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="s" ) ]
        o.diagnoses      = { "C1": _diag() }
        o.proposed_fixes = [ _prop() ]
        o.selected_fixes = [ _prop( cid="C1", title="sel" ) ]
        o.last_plan_path = "io/plan.md"
        o.branch_name    = "fix/x"
        o.commit_hashes  = [ "abc123" ]
        ckpt = o.save_checkpoint()

        o2 = _orch()
        o2.load_checkpoint( ckpt )
        assert len( o2.clusters ) == 1 and o2.clusters[ 0 ].cluster_id == "C1"
        assert o2.diagnoses[ "C1" ].error_category == "code_bug"
        assert o2.proposed_fixes[ 0 ].title == "T"
        assert o2.selected_fixes[ 0 ].title == "sel"
        assert o2.last_plan_path == "io/plan.md"
        assert o2.branch_name == "fix/x"
        assert o2.current_phase == TFEPhase.PROPOSING

    def test_set_resume_phase( self ):
        o = _orch()
        o.set_resume_phase( 3 )
        assert o._resume_from_ordinal == 3


# ============================================================================
# JSON parsers — diagnosis
# ============================================================================
class TestParseDiagnosis:
    def test_clean_json( self ):
        o = _orch()
        d = o._parse_diagnosis_result(
            '{"cluster_id":"C1","root_cause":"rc","error_category":"code_bug","confidence":0.8}', "C1" )
        assert d.error_category == "code_bug" and d.confidence == 0.8

    def test_markdown_fenced_in_prose( self ):
        o = _orch()
        raw = 'analysis:\n```json\n{"root_cause":"rc","error_category":"test_bug","confidence":0.7}\n```\ndone'
        d = o._parse_diagnosis_result( raw, "C9" )
        assert d.cluster_id == "C9"          # filled when omitted
        assert d.error_category == "test_bug"

    def test_no_json_falls_back( self ):
        o = _orch()
        d = o._parse_diagnosis_result( "no json at all", "C2" )
        assert d.confidence == 0.1 and d.error_category == "unknown"

    def test_invalid_json_falls_back( self ):
        o = _orch()
        d = o._parse_diagnosis_result( '{"confidence": not-valid}', "C3" )
        assert d.confidence == 0.1

    def test_blank_cluster_id_in_payload_filled( self ):
        o = _orch()
        d = o._parse_diagnosis_result(
            '{"cluster_id":"","root_cause":"rc","error_category":"code_bug","confidence":0.5}', "C7" )
        assert d.cluster_id == "C7"

    def test_extract_last_json_object_no_brace( self ):
        assert TFEOrchestrator._extract_last_json_object( "no braces" ) is None

    def test_extract_last_json_object_unbalanced( self ):
        # a lone close brace with no matching open -> depth never returns to 0 -> None
        assert TFEOrchestrator._extract_last_json_object( "text } more" ) is None

    def test_extract_last_json_object_balanced( self ):
        out = TFEOrchestrator._extract_last_json_object( 'pre {"a": 1} post' )
        assert out == '{"a": 1}'

    def test_extract_last_json_object_nested( self ):
        # nested braces -> inner depth doesn't return to 0 (594->589 continue arc)
        out = TFEOrchestrator._extract_last_json_object( 'pre {"a": {"b": 1}} post' )
        assert out == '{"a": {"b": 1}}'

    def test_fallback_diagnosis_shape( self ):
        d = TFEOrchestrator._fallback_diagnosis( "C5", "the reason" )
        assert d.cluster_id == "C5" and d.root_cause == "the reason"
        assert d.confidence == 0.1 and d.error_category == "unknown"


# ============================================================================
# JSON parsers — proposal
# ============================================================================
class TestParseProposal:
    def test_array_parsed( self ):
        o = _orch()
        raw = '[{"cluster_id":"C1","title":"t","description":"d","fix_type":"code_patch","confidence":0.8}]'
        out = o._parse_proposal_result( raw, "C1" )
        assert len( out ) == 1 and out[ 0 ].title == "t"

    def test_dict_wrapped_into_list( self ):
        o = _orch()
        raw = '{"title":"t","description":"d","fix_type":"retry","confidence":0.5}'   # no cluster_id -> filled
        out = o._parse_proposal_result( raw, "C2" )
        assert len( out ) == 1 and out[ 0 ].cluster_id == "C2"

    def test_markdown_fenced_array( self ):
        o = _orch()
        raw = '```json\n[{"cluster_id":"C1","title":"t","description":"d","fix_type":"code_patch","confidence":0.9}]\n```'
        out = o._parse_proposal_result( raw, "C1" )
        assert out[ 0 ].confidence == 0.9

    def test_unparseable_returns_empty( self ):
        o = _orch()
        assert o._parse_proposal_result( "garbage no json", "C1" ) == []

    def test_non_list_non_dict_payload_returns_empty( self ):
        o = _orch()
        # json.loads("5") -> int -> not dict, not list -> warning + []
        assert o._parse_proposal_result( "5", "C1" ) == []

    def test_non_dict_items_skipped( self ):
        o = _orch()
        raw = '[42, {"cluster_id":"C1","title":"ok","description":"d","fix_type":"code_patch","confidence":0.8}]'
        out = o._parse_proposal_result( raw, "C1" )
        assert [ p.title for p in out ] == [ "ok" ]   # int item skipped

    def test_invalid_proposal_dropped( self ):
        o = _orch()
        # missing required title -> Pydantic ValueError -> dropped
        raw = '[{"cluster_id":"C1","fix_type":"code_patch","confidence":0.8}]'
        out = o._parse_proposal_result( raw, "C1" )
        assert out == []

    def test_parse_proposal_json_empty( self ):
        assert TFEOrchestrator._parse_proposal_json( "" ) is None

    def test_parse_proposal_json_whole_text( self ):
        assert TFEOrchestrator._parse_proposal_json( '[1, 2]' ) == [ 1, 2 ]

    def test_parse_proposal_json_array_walkback( self ):
        out = TFEOrchestrator._parse_proposal_json( 'noise [1, 2] tail-noise }' )
        assert out == [ 1, 2 ]

    def test_parse_proposal_json_object_walkback( self ):
        out = TFEOrchestrator._parse_proposal_json( 'prose {"a": 1} end' )
        assert out == { "a": 1 }

    def test_parse_proposal_json_array_candidate_broken_breaks( self ):
        # last ']' has a matching '[' but the slice is invalid JSON -> break -> falls through to None
        assert TFEOrchestrator._parse_proposal_json( "[not json]" ) is None

    def test_parse_proposal_json_nothing_parses( self ):
        assert TFEOrchestrator._parse_proposal_json( "plain text" ) is None

    def test_extract_last_json_array_removed( self ):
        # The orphaned _extract_last_json_array helper was deleted (dead code,
        # zero callers). Guard against accidental resurrection.
        assert not hasattr( TFEOrchestrator, "_extract_last_json_array" )

    def test_parse_proposal_json_array_nested_walkback( self ):
        # nested arrays exercise the depth!=0 continue arc in the array walk
        assert TFEOrchestrator._parse_proposal_json( "x [[1],[2]] y" ) == [ [ 1 ], [ 2 ] ]

    def test_parse_proposal_json_unbalanced_array_falls_to_object( self ):
        # ']' with no matching '[' -> array loop exhausts (903->916) -> object attempt parses {a:1}
        assert TFEOrchestrator._parse_proposal_json( 'x ] y {"a": 1}' ) == { "a": 1 }

    def test_parse_proposal_json_object_nested_walkback( self ):
        # nested braces in the object walk exercise the depth!=0 continue arc
        assert TFEOrchestrator._parse_proposal_json( 'pre {"a": {"b": 1}} post' ) == { "a": { "b": 1 } }

    def test_parse_proposal_json_object_unbalanced_returns_none( self ):
        # '}' with no matching '{' -> object loop exhausts -> None
        assert TFEOrchestrator._parse_proposal_json( "junk } only" ) is None

    def test_parse_proposal_json_object_candidate_broken_breaks( self ):
        # matched {...} but invalid JSON inside -> except break -> None
        assert TFEOrchestrator._parse_proposal_json( "x {bad json} y" ) is None


# ============================================================================
# ClaudeAgentOptions builders
# ============================================================================
class TestOptionBuilders:
    def test_lead_diagnosis_options( self ):
        o = _orch()
        opts = o._build_lead_diagnosis_options()
        assert opts.model == o.config.lead_model
        assert opts.permission_mode == "plan"

    def test_lead_proposal_options( self ):
        o = _orch()
        opts = o._build_lead_proposal_options()
        assert opts.model == o.config.lead_model
        assert opts.max_turns == 20

    def test_coder_options_tier_lookup_and_default( self ):
        o = _orch()
        with patch.object( orch_mod, "build_can_use_tool", MagicMock( return_value=lambda *a, **k: None ) ):
            o._current_budget_tier = "large"
            opts = o._build_tfe_coder_options( MagicMock(), MagicMock() )
            assert opts.max_turns == o.config.coder_budget_large_turns
            # unknown tier -> medium default
            o._current_budget_tier = "bogus"
            opts2 = o._build_tfe_coder_options( MagicMock(), MagicMock() )
            assert opts2.max_turns == o.config.coder_budget_medium_turns

    def test_coder_options_routes_to_worktree_cwd( self ):
        o = _orch()
        o._worktree_cwd = "/tmp/wt"
        with patch.object( orch_mod, "build_can_use_tool", MagicMock( return_value=lambda *a, **k: None ) ):
            opts = o._build_tfe_coder_options( MagicMock(), MagicMock() )
        assert opts.cwd == "/tmp/wt"

    def test_tester_options( self ):
        o = _orch()
        with patch.object( orch_mod, "build_can_use_tool", MagicMock( return_value=lambda *a, **k: None ) ):
            opts = o._build_tfe_tester_options( MagicMock(), MagicMock() )
        assert opts.max_turns == 10
        assert opts.model == o.config.worker_model


# ============================================================================
# _apply_voice_gate_timeout_policy / _delegate_to_predictor
# ============================================================================
class TestVoiceGateTimeoutPolicy:
    def test_stall_raises( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="stall" ) )
        with pytest.raises( VoiceGateTimeoutError ):
            o._apply_voice_gate_timeout_policy( [ _prop() ] )

    def test_none_returns_empty( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="none" ) )
        assert o._apply_voice_gate_timeout_policy( [ _prop() ] ) == []

    def test_top_1_returns_highest_confidence( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="top_1" ) )
        props = [ _prop( cid="C1", conf=0.4 ), _prop( cid="C2", conf=0.9 ) ]
        out = o._apply_voice_gate_timeout_policy( props )
        assert len( out ) == 1 and out[ 0 ].cluster_id == "C2"

    def test_top_n_uses_config_count( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="top_n",
                                                  voice_gate_auto_ratify_top_n=2 ) )
        props = [ _prop( cid="C1", conf=0.4 ), _prop( cid="C2", conf=0.9 ), _prop( cid="C3", conf=0.6 ) ]
        out = o._apply_voice_gate_timeout_policy( props )
        assert [ p.cluster_id for p in out ] == [ "C2", "C3" ]

    def test_unknown_policy_raises( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="weird" ) )
        with pytest.raises( VoiceGateTimeoutError, match="unknown policy" ):
            o._apply_voice_gate_timeout_policy( [ _prop() ] )

    def test_none_policy_value_defaults_to_stall( self ):
        # config value None -> ( None or "stall" ).lower() == "stall"
        cfg = TestFixExpediterConfig()
        cfg.voice_gate_timeout_policy = None
        o = _orch( config=cfg )
        with pytest.raises( VoiceGateTimeoutError ):
            o._apply_voice_gate_timeout_policy( [ _prop() ] )

    def test_delegate_policy_raises_not_implemented( self ):
        o = _orch( config=TestFixExpediterConfig( voice_gate_timeout_policy="delegate" ) )
        with pytest.raises( NotImplementedError ):
            o._apply_voice_gate_timeout_policy( [ _prop() ] )

    def test_delegate_to_predictor_direct( self ):
        o = _orch()
        with pytest.raises( NotImplementedError ):
            o._delegate_to_predictor( [ _prop() ] )


# ============================================================================
# Render helpers
# ============================================================================
class TestRenderHelpers:
    def test_render_proposal_abstract_with_and_without_description( self ):
        out = TFEOrchestrator._render_proposal_abstract(
            [ _prop( cid="C1", desc="has desc" ), _prop( cid="C2", desc="" ) ] )
        assert "**C1**" in out and "has desc" in out
        assert "**C2**" in out

    def test_render_single_proposal( self ):
        out = TFEOrchestrator._render_single_proposal( _prop( cid="C1", title="X", desc="why" ) )
        assert "**C1: X**" in out and "why" in out

    def test_render_git_summary_full( self ):
        out = TFEOrchestrator._render_git_summary( {
            "git_strategy": "L1", "branch_name": "fix/x",
            "commit_hashes": [ "abcdef123", "999" ], "pr_url": "http://pr", "error": "oops",
        } )
        assert "**Strategy**: L1" in out
        assert "`abcdef12`" in out          # truncated to 8
        assert "**PR**: http://pr" in out
        assert "**Error**: oops" in out

    def test_render_git_summary_minimal( self ):
        out = TFEOrchestrator._render_git_summary( {} )
        assert "(none)" in out              # strategy fallback

    def test_render_validation_abstract( self ):
        o = _orch()
        vj = SimpleNamespace( id_hash="ts-rerun" )
        out = o._render_validation_abstract( vj, [ "unit" ], 3 )
        assert "ts-rerun" in out and "Successful fixes applied: 3" in out


# ============================================================================
# render_worktree_artifacts_abstract
# ============================================================================
class TestWorktreeAbstract:
    def test_no_selected_returns_empty( self ):
        o = _orch()
        assert o.render_worktree_artifacts_abstract( "tfe-1" ) == []

    def test_with_fixes_files_and_git_outputs( self ):
        o = _orch()
        o.selected_fixes = [ _prop( cid="C1", title="ok" ), _prop( cid="C2", title="bad" ) ]
        o.fix_results    = [ SimpleNamespace( success=True ), SimpleNamespace( success=False ) ]
        o.files_changed_by_cluster = { "C1": [ "a.py", "b.py" ] }   # C2 -> no files (suffix skipped)
        o.branch_name    = "fix/x"
        o.commit_hashes  = [ "abcdef123456", "789" ]
        o.pr_url         = "http://pr"
        out = o.render_worktree_artifacts_abstract( "tfe-1" )
        body = "\n".join( out )
        assert "**C1** ✓ ok · files=2" in body
        assert "**C2** ✗ bad" in body and "C2** ✗ bad ·" not in body   # no files suffix
        assert "**Branch**: `fix/x`" in body
        assert "`abcdef12`" in body
        assert "**PR**: http://pr" in body

    def test_with_fixes_only_branch_set( self ):
        # block entered via branch; hashes/pr_url false (1707->1711, 1711->1714 arcs)
        o = _orch()
        o.selected_fixes = [ _prop( cid="C1", title="ok" ) ]
        o.fix_results    = [ SimpleNamespace( success=True ) ]
        o.files_changed_by_cluster = {}
        o.branch_name    = "fix/x"; o.commit_hashes = []; o.pr_url = None
        body = "\n".join( o.render_worktree_artifacts_abstract( "tfe-1" ) )
        assert "**Branch**: `fix/x`" in body
        assert "**Commits**" not in body and "**PR**" not in body

    def test_with_fixes_only_pr_set( self ):
        # block entered via pr_url; branch false (1705->1707 arc)
        o = _orch()
        o.selected_fixes = [ _prop( cid="C1", title="ok" ) ]
        o.fix_results    = [ SimpleNamespace( success=True ) ]
        o.files_changed_by_cluster = {}
        o.branch_name    = None; o.commit_hashes = []; o.pr_url = "http://pr"
        body = "\n".join( o.render_worktree_artifacts_abstract( "tfe-1" ) )
        assert "**Branch**" not in body
        assert "**PR**: http://pr" in body

    def test_with_fixes_no_git_outputs( self ):
        o = _orch()
        o.selected_fixes = [ _prop( cid="C1", title="ok" ) ]
        o.fix_results    = [ SimpleNamespace( success=True ) ]
        o.files_changed_by_cluster = {}
        # branch/hashes/pr all empty -> git block skipped
        out = o.render_worktree_artifacts_abstract( "tfe-1" )
        body = "\n".join( out )
        assert "**Branch**" not in body
        assert "**Inspect**:" in body


# ============================================================================
# _summarize_tool_use
# ============================================================================
class TestSummarizeToolUse:
    def _block( self, name, **inp ):
        return SimpleNamespace( name=name, input=inp )

    def test_bash_with_command( self ):
        out = TFEOrchestrator._summarize_tool_use( self._block( "Bash", command="ls -la\nsecond line" ) )
        assert out == "Bash: ls -la"

    def test_bash_empty_command( self ):
        assert TFEOrchestrator._summarize_tool_use( self._block( "Bash", command="" ) ) == "Bash"

    def test_read_with_path( self ):
        out = TFEOrchestrator._summarize_tool_use( self._block( "Read", file_path="/a/b/c.py" ) )
        assert out.startswith( "Read: " ) and "c.py" in out

    def test_edit_empty_path( self ):
        assert TFEOrchestrator._summarize_tool_use( self._block( "Edit", file_path="" ) ) == "Edit"

    def test_grep_with_pattern( self ):
        out = TFEOrchestrator._summarize_tool_use( self._block( "Grep", pattern="foo.*bar" ) )
        assert out == "Grep: foo.*bar"

    def test_glob_empty_pattern( self ):
        assert TFEOrchestrator._summarize_tool_use( self._block( "Glob", pattern="" ) ) == "Glob"

    def test_other_tool_name( self ):
        assert TFEOrchestrator._summarize_tool_use( self._block( "WebFetch", url="http://x" ) ) == "WebFetch"

    def test_none_input_defaults_empty( self ):
        out = TFEOrchestrator._summarize_tool_use( SimpleNamespace( name="Bash", input=None ) )
        assert out == "Bash"


# ============================================================================
# _derive_budget_tier
# ============================================================================
class TestDeriveBudgetTier:
    def test_small_single_file_test_patch( self ):
        p = _prop( fix_type="test_patch", changes=[ { "file": "a.py" } ] )
        assert TFEOrchestrator._derive_budget_tier( p ) == "small"

    def test_small_single_file_config_change( self ):
        p = _prop( fix_type="config_change", changes=[ { "file": "x.ini" } ] )
        assert TFEOrchestrator._derive_budget_tier( p ) == "small"

    def test_large_four_plus_files( self ):
        p = _prop( fix_type="code_patch", changes=[ { "file": f"f{i}.py" } for i in range( 4 ) ] )
        assert TFEOrchestrator._derive_budget_tier( p ) == "large"

    def test_medium_default( self ):
        p = _prop( fix_type="code_patch", changes=[ { "file": "a.py" }, { "file": "b.py" } ] )
        assert TFEOrchestrator._derive_budget_tier( p ) == "medium"

    def test_empty_changes_falls_back_to_cluster_guess( self ):
        p = _prop( fix_type="code_patch", changes=[] )
        cluster = SimpleNamespace( affected_files_guess=[ "a", "b", "c", "d", "e" ] )
        assert TFEOrchestrator._derive_budget_tier( p, cluster=cluster ) == "large"

    def test_empty_changes_no_cluster_is_medium( self ):
        p = _prop( fix_type="code_patch", changes=[] )
        assert TFEOrchestrator._derive_budget_tier( p ) == "medium"


# ============================================================================
# _suite_abbrev / _build_tfe_commit_message / _build_tfe_pr_body
# ============================================================================
class TestGitTextHelpers:
    def test_suite_abbrev_empty( self ):
        assert TFEOrchestrator._suite_abbrev( [] ) == "none"

    def test_suite_abbrev_single( self ):
        assert TFEOrchestrator._suite_abbrev( [ "e2e" ] ) == "e2e"

    def test_suite_abbrev_multiple( self ):
        assert TFEOrchestrator._suite_abbrev( [ "unit", "e2e" ] ) == "mixed"

    def test_commit_message_with_description( self ):
        out = TFEOrchestrator._build_tfe_commit_message( _prop( cid="C1", title="fix thing", desc="why" ) )
        assert "fix(tfe): C1 fix thing" in out and "why" in out

    def test_commit_message_without_description( self ):
        out = TFEOrchestrator._build_tfe_commit_message( _prop( cid="C1", title="t", desc="" ) )
        assert "Confidence:" in out and "why" not in out

    def test_build_pr_body( self ):
        o = _orch()
        pairs = [ ( _prop( cid="C1", title="t" ), SimpleNamespace( success=True ), [ "a.py" ] ) ]
        out = o._build_tfe_pr_body( pairs, "unit" )
        assert "## Summary" in out and "Clusters fixed (1)" in out
        assert "| C1 |" in out


# ============================================================================
# _resolve_tfe_trust_level / _resolve_rerun_test_types
# ============================================================================
class TestResolvers:
    @pytest.mark.parametrize( "mode,expected", [
        ( "fixed_l3", 3 ), ( "fixed_l1", 1 ), ( "shadow", 1 ), ( "inherit", 1 ), ( "bogus", 1 ),
    ] )
    def test_trust_level( self, mode, expected ):
        o = _orch( config=TestFixExpediterConfig( trust_mode=mode ) )
        assert o._resolve_tfe_trust_level() == expected

    def test_rerun_test_types_full( self ):
        o = _orch( config=TestFixExpediterConfig( rerun_scope="full" ) )
        assert o._resolve_rerun_test_types() == [ "all" ]

    def test_rerun_test_types_affected( self ):
        o = _orch( config=TestFixExpediterConfig( rerun_scope="affected" ),
                   ctx=_ctx( original_test_types=[ "unit", "e2e" ] ) )
        assert o._resolve_rerun_test_types() == [ "unit", "e2e" ]
