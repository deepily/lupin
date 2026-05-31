#!/usr/bin/env python3
"""
Unit tests for cosa.agents.test_fix_expediter.job.TestFixExpediterJob

Targets:
  - __init__ / last_question_asked
  - do_all       (COMPLETED / STALLED / CANCELLED / FAILED arcs)
  - _execute     (happy-path TTS branches, snapshot-load failure, resume,
                  StalledException, generic-error, notify-failure arcs)
  - _write_final_report (status variants, optional artifacts, exception arc)

ALL boundaries mocked — the orchestrator (TFEOrchestrator), snapshot_loader,
voice_io.notify, ConfigurationManager, TestFixExpediterConfig, the BFE
cosa_interface, and ReportWriter are patched. NO real SDK / LLM / DB / git /
disk / network. Zero spend.

quick_smoke_test + __main__ are coverage-excluded by repo config.

Created 2026-05-31 by Rachel 🕊️ (CoSA coverage campaign, TFE lane).
"""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.test_fix_expediter.job as job_mod
from cosa.agents.test_fix_expediter.job import TestFixExpediterJob
from cosa.agents.test_fix_expediter.snapshot_loader import SnapshotLoadError
from cosa.agents.test_fix_expediter.state import StalledException
from cosa.rest.job_state import JobState


# ----------------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------------
def _fix_result( success=True, last_stderr="", attempts=1 ):
    return SimpleNamespace( success=success, last_stderr=last_stderr, attempts=attempts )


def _diag( root_cause="rc", category="code_bug", confidence=0.8, has_conf=True ):
    if has_conf:
        return SimpleNamespace( root_cause=root_cause, error_category=category, confidence=confidence )
    # object WITHOUT a confidence attr -> exercises the hasattr-False arc
    d = SimpleNamespace( root_cause=root_cause, error_category=category )
    return d


class _FakeOrch:
    """Fake TFEOrchestrator driving job._execute through its phase calls."""
    def __init__( self, **kw ):
        self.last_plan_path      = kw.get( "last_plan_path", "io/plan.md" )
        self.clusters            = kw.get( "clusters", [] )
        self.diagnoses           = kw.get( "diagnoses", {} )
        self.proposed_fixes      = kw.get( "proposed_fixes", [] )
        self.selected_fixes      = kw.get( "selected_fixes", [] )
        self.fix_results         = kw.get( "fix_results", [] )
        self.remediation_context = SimpleNamespace( failures=kw.get( "failures", [] ) )
        self._validation         = kw.get( "validation", "ts-rerun-1" )
        self._wt_lines           = kw.get( "wt_lines", [] )
        self.loaded_checkpoint   = None
        self.resume_phase        = None

    async def run_phase0_cluster( self ):  return self.clusters
    async def run_phase1_diagnose( self ): return self.diagnoses
    async def run_phase2_propose( self ):  return None
    async def run_phase3_fix( self ):      return self.fix_results
    async def run_phase5_git( self ):      return None
    async def run_phase6_validation( self ): return self._validation

    def render_worktree_artifacts_abstract( self, id_hash ): return list( self._wt_lines )

    @asynccontextmanager
    async def worktree_scope( self ):
        yield

    def load_checkpoint( self, c ):     self.loaded_checkpoint = c
    def set_resume_phase( self, o ):    self.resume_phase = o


def _make_job( **over ):
    base = dict(
        remediation_snapshot_path = "test-suite/fake.json",
        source_test_suite_job_id  = "ts-abc12345",
        user_id="u1", user_email="t@t.com", session_id="s1",
        debug=False, verbose=False,
    )
    base.update( over )
    return TestFixExpediterJob( **base )


@contextmanager
def _exec_patches( orch, from_config_raises=False ):
    """Patch every call-time collaborator inside job._execute."""
    fake_cfg         = SimpleNamespace( lead_model="opus", worker_model="worker", thinking_effort=None )
    fake_cfg_default = SimpleNamespace( lead_model="opus", worker_model="worker", thinking_effort=None )

    cfg_cls = MagicMock()
    if from_config_raises:
        cfg_cls.from_config.side_effect = RuntimeError( "ini missing" )
    else:
        cfg_cls.from_config.return_value = fake_cfg
    cfg_cls.return_value = fake_cfg_default

    notify = AsyncMock()
    bfe_ci = SimpleNamespace( TARGET_USER=None, SENDER_ID=None,
                              _get_sender_id=MagicMock( return_value="tfe@lupin#1" ) )

    with patch( "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator", return_value=orch ), \
         patch( "cosa.agents.test_fix_expediter.config.TestFixExpediterConfig", cfg_cls ), \
         patch( "cosa.agents.test_fix_expediter.voice_io.notify", notify ), \
         patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "cosa.agents.bug_fix_expediter.cosa_interface.TARGET_USER", None, create=True ), \
         patch( "cosa.agents.bug_fix_expediter.cosa_interface.SENDER_ID", None, create=True ), \
         patch( "cosa.agents.bug_fix_expediter.cosa_interface._get_sender_id",
                MagicMock( return_value="tfe@lupin#1" ) ):
        yield SimpleNamespace( cfg_cls=cfg_cls, notify=notify )


# ============================================================================
# __init__ / last_question_asked
# ============================================================================
class TestInitAndProps:
    def test_constructs_with_defaults( self ):
        job = _make_job( original_test_types=None, original_pytest_args=None )
        assert job.original_test_types == []          # None -> []
        assert job.original_pytest_args == []
        assert job.remediation_context is None
        assert job.orchestrator is None
        assert job.id_hash.startswith( "tfe-" )

    def test_stores_explicit_lists_and_overrides( self ):
        job = _make_job(
            original_test_types=[ "e2e" ], original_pytest_args=[ "-k", "x" ],
            dry_run=True, lead_model_override="sonnet", worker_model_override="haiku",
            thinking_effort="high",
        )
        assert job.original_test_types == [ "e2e" ]
        assert job.dry_run is True
        assert job.lead_model_override == "sonnet"
        assert job.thinking_effort == "high"

    def test_last_question_asked( self ):
        assert "ts-abc12345" in _make_job().last_question_asked


# ============================================================================
# do_all
# ============================================================================
class TestDoAll:
    def test_completed_path( self ):
        job = _make_job( debug=True )
        with patch.object( job, "_execute", AsyncMock( return_value="done report" ) ):
            out = job.do_all()
        assert out == "done report"
        assert job.state == JobState.COMPLETED
        assert job.answer_conversational == "done report"
        assert job.result == "done report"

    def test_completed_path_debug_off( self ):
        # debug=False -> the `if self.debug` duration-print arc (188->192) is skipped
        job = _make_job( debug=False )
        with patch.object( job, "_execute", AsyncMock( return_value="done" ) ):
            out = job.do_all()
        assert out == "done"
        assert job.state == JobState.COMPLETED

    def test_stalled_path( self ):
        job = _make_job( debug=True )
        job.orchestrator = _FakeOrch( proposed_fixes=[ 1, 2 ] )
        with patch.object( job, "_execute", AsyncMock( return_value="__STALLED__" ) ):
            out = job.do_all()
        assert job.state == JobState.STALLED
        assert "2 proposals await your review" in out

    def test_cancelled_path( self ):
        job = _make_job()
        job._cancel_requested = True
        with patch.object( job, "_execute", AsyncMock( return_value="partial" ) ):
            out = job.do_all()
        assert job.state == JobState.CANCELLED
        assert out == "partial"
        assert job.error == "Cancelled by user request"

    def test_cancelled_path_empty_result_uses_default_msg( self ):
        job = _make_job()
        job._cancel_requested = True
        with patch.object( job, "_execute", AsyncMock( return_value="" ) ):
            out = job.do_all()
        assert out == "TFE was cancelled by the user."

    def test_failed_path_reraises_and_writes_report( self ):
        job = _make_job( debug=True )
        with patch.object( job, "_execute", AsyncMock( side_effect=ValueError( "kaboom" ) ) ), \
             patch.object( job, "_write_final_report" ) as wfr:
            with pytest.raises( ValueError, match="kaboom" ):
                job.do_all()
        assert job.state == JobState.FAILED
        assert "kaboom" in job.error
        assert job.artifacts[ "failure_message" ] == "kaboom"
        assert "failure_traceback" in job.artifacts
        wfr.assert_called_once()


# ============================================================================
# _execute — happy paths + branches
# ============================================================================
class TestExecuteHappyPaths:
    def _run( self, job, orch, **kw ):
        import asyncio
        with _exec_patches( orch, **kw ) as h, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path",
                    return_value=orch.remediation_context ), \
             patch.object( job, "_write_final_report" ):
            return asyncio.run( job._execute() ), h

    def test_fixes_applied_branch_with_diagnoses_and_failed_pairs( self ):
        job = _make_job( debug=True, lead_model_override="sonnet",
                         worker_model_override="haiku", thinking_effort="high" )
        orch = _FakeOrch(
            clusters=[ SimpleNamespace( cluster_id="C1", failure_indices=[ 0 ],
                                        shared_error_signature="sig" ) ],
            diagnoses={ "C1": _diag() },
            proposed_fixes=[ SimpleNamespace( title="P1", description="d" ) ],
            selected_fixes=[ SimpleNamespace( title="P1" ) ],
            fix_results=[ _fix_result( success=True ),
                          _fix_result( success=False, last_stderr="trace-A" ) ],
            failures=[ {}, {} ],
            wt_lines=[ "**Worktree**: /tmp/wt" ],
        )
        # selected_fixes shorter than fix_results -> zip stops at shortest; ensure a failed pair:
        orch.selected_fixes = [ SimpleNamespace( title="P-fail" ), SimpleNamespace( title="P-ok" ) ]
        orch.fix_results    = [ _fix_result( success=False, last_stderr="trace-A", attempts=2 ),
                                _fix_result( success=True ) ]
        out, h = self._run( job, orch )
        assert "TFE complete" in out
        assert job.artifacts[ "cluster_count" ] == 1
        assert job.artifacts[ "validation_run_job_id" ] == "ts-rerun-1"
        # n_fixed == 1 -> "fixes applied" TTS branch; failed diagnostics rendered
        h.notify.assert_awaited()
        msg = h.notify.await_args.args[ 0 ]
        assert "fix" in msg and "applied" in msg

    def test_no_selected_branch_config_default_and_resume( self ):
        job = _make_job( debug=True )
        job._resume_checkpoint = { "phase_ordinal": 3 }
        orch = _FakeOrch(
            clusters=[ SimpleNamespace( cluster_id="C1", failure_indices=[ 0 ],
                                        shared_error_signature="" ) ],
            diagnoses={}, proposed_fixes=[], selected_fixes=[], fix_results=[],
            failures=[ {} ], last_plan_path=None, validation=None,
        )
        out, h = self._run( job, orch, from_config_raises=True )   # exercises defaults path
        assert "TFE complete" in out
        assert orch.loaded_checkpoint == { "phase_ordinal": 3 }   # resume wired
        assert orch.resume_phase == 3
        assert "plan_path" not in job.artifacts                   # last_plan_path None -> skipped
        msg = h.notify.await_args.args[ 0 ]
        assert "no fixes selected" in msg

    def test_attempted_failed_branch_and_failed_pairs_truncation( self ):
        job = _make_job()
        # n_selected>0, n_fixed==0 -> else TTS branch; 6 failed pairs -> >5 truncation
        sel  = [ SimpleNamespace( title=f"P{i}" ) for i in range( 6 ) ]
        fres = [ _fix_result( success=False, last_stderr=f"err{i}", attempts=1 ) for i in range( 6 ) ]
        orch = _FakeOrch(
            clusters=[ SimpleNamespace( cluster_id="C1", failure_indices=[ 0 ],
                                        shared_error_signature="s" ) ],
            diagnoses={ "C1": _diag( has_conf=False ) },   # hasattr-False confidence arc
            proposed_fixes=[ SimpleNamespace( title="P", description="d" ) ],
            selected_fixes=sel, fix_results=fres, failures=[ {} ],
        )
        out, h = self._run( job, orch )
        msg = h.notify.await_args.args[ 0 ]
        assert "attempted" in msg and "failed" in msg
        abstract = h.notify.await_args.kwargs[ "abstract" ]
        assert "+1 more failed" in abstract                       # 6 - 5 = 1

    def test_completion_notify_failure_is_swallowed( self ):
        import asyncio
        job  = _make_job()
        orch = _FakeOrch(
            clusters=[], diagnoses={}, proposed_fixes=[], selected_fixes=[],
            fix_results=[], failures=[],
        )
        with _exec_patches( orch ) as h, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path",
                    return_value=orch.remediation_context ), \
             patch.object( job, "_write_final_report" ):
            h.notify.side_effect = RuntimeError( "ws down" )
            out = asyncio.run( job._execute() )   # must NOT raise
        assert "TFE complete" in out


# ============================================================================
# _execute — failure / stall / error arcs
# ============================================================================
class TestExecuteErrorArcs:
    def test_snapshot_load_error_becomes_runtime_error( self ):
        import asyncio
        job  = _make_job()
        orch = _FakeOrch()
        with _exec_patches( orch ), \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path",
                    side_effect=SnapshotLoadError( "bad json" ) ), \
             patch( "cosa.agents.test_fix_expediter.voice_io.notify", AsyncMock() ), \
             patch.object( job, "_write_final_report" ):
            with pytest.raises( RuntimeError, match="Failed to load remediation snapshot" ):
                asyncio.run( job._execute() )

    def test_stalled_exception_returns_sentinel( self ):
        import asyncio
        job  = _make_job( debug=True )
        orch = _FakeOrch( clusters=[ 1, 2 ], proposed_fixes=[ 1 ] )
        checkpoint = { "stall_reason": "voice_gate_timeout",
                       "artifacts": { "plan_path": "io/p.md" } }

        async def _stall():
            raise StalledException( checkpoint=checkpoint, phase="proposing" )
        orch.run_phase0_cluster = _stall   # stall at first phase

        with _exec_patches( orch ) as h, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path",
                    return_value=orch.remediation_context ), \
             patch.object( job, "_write_final_report" ):
            out = asyncio.run( job._execute() )
        assert out == "__STALLED__"
        assert job.artifacts[ "checkpoint" ] == checkpoint
        assert job.artifacts[ "plan_path" ] == "io/p.md"          # lifted from checkpoint
        h.notify.assert_awaited()

    def test_stalled_exception_no_plan_path_and_notify_fails( self ):
        import asyncio
        job  = _make_job()
        orch = _FakeOrch( clusters=[], proposed_fixes=[] )
        checkpoint = { "stall_reason": "user_pause", "artifacts": {} }   # no plan_path

        async def _stall():
            raise StalledException( checkpoint=checkpoint, phase="diagnosing" )
        orch.run_phase0_cluster = _stall

        with _exec_patches( orch ) as h, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path",
                    return_value=orch.remediation_context ), \
             patch.object( job, "_write_final_report" ):
            h.notify.side_effect = RuntimeError( "ws gone" )
            out = asyncio.run( job._execute() )
        assert out == "__STALLED__"
        assert "plan_path" not in job.artifacts

    def test_generic_error_notifies_urgent_and_reraises( self ):
        import asyncio
        job  = _make_job()
        orch = _FakeOrch()

        async def _boom():
            raise ValueError( "phase blew up" )
        orch.run_phase0_cluster = _boom

        with _exec_patches( orch ) as h, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path",
                    return_value=orch.remediation_context ), \
             patch.object( job, "_write_final_report" ):
            with pytest.raises( ValueError, match="phase blew up" ):
                asyncio.run( job._execute() )
        # urgent notify fired with the traceback in abstract
        assert h.notify.await_args.kwargs[ "priority" ] == "urgent"

    def test_generic_error_notify_failure_does_not_mask( self ):
        import asyncio
        job  = _make_job()
        orch = _FakeOrch()

        async def _boom():
            raise ValueError( "original error" )
        orch.run_phase0_cluster = _boom

        with _exec_patches( orch ) as h, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path",
                    return_value=orch.remediation_context ), \
             patch.object( job, "_write_final_report" ):
            h.notify.side_effect = RuntimeError( "notify down" )
            with pytest.raises( ValueError, match="original error" ):   # original, not notify error
                asyncio.run( job._execute() )


# ============================================================================
# _write_final_report
# ============================================================================
class TestWriteFinalReport:
    def _job_with_orch( self, orch=None, **artifacts ):
        job = _make_job()
        job.started_at = "2026-01-01T00:00:00"
        job.orchestrator = orch
        job.artifacts.update( artifacts )
        return job

    @contextmanager
    def _writer( self, raises=False ):
        inst = MagicMock()
        if raises:
            inst.write.side_effect = RuntimeError( "disk full" )
        else:
            inst.write.return_value = "io/reports/tfe-report.md"
        with patch( "cosa.agents.shared.report_writer.ReportWriter", return_value=inst ):
            yield inst

    def test_full_completed_report( self ):
        orch = _FakeOrch(
            clusters=[ SimpleNamespace( cluster_id="C1", failure_indices=[ 0, 1 ],
                                        shared_error_signature="sig" ),
                       SimpleNamespace( cluster_id="C2", failure_indices=[ 2 ],
                                        shared_error_signature="" ) ],   # empty sig -> skip line
            proposed_fixes=[ SimpleNamespace( title="P1", description="desc" ),
                             SimpleNamespace( title="P2", description="" ) ],  # empty desc -> skip
        )
        job = self._job_with_orch(
            orch, cluster_count=2, fix_count=1, validation_run_job_id="ts-r",
            plan_path="io/p.md", remediation_snapshot_path="test-suite/f.json",
        )
        with self._writer() as inst:
            path = job._write_final_report( status="completed", summary_line="all good" )
        assert path == "io/reports/tfe-report.md"
        assert job.artifacts[ "report_path" ] == path
        body = inst.write.call_args.kwargs[ "body_md" ]
        assert "**Status**: completed" in body
        assert "**Clusters**: 2" in body
        assert "C1 — 2 failure(s)" in body
        assert "P1" in body and "desc" in body
        assert "## Appendix" in body

    def test_stalled_with_checkpoint( self ):
        job = self._job_with_orch( orch=None, checkpoint={ "phase": "proposing", "stall_reason": "user_pause" } )
        with self._writer() as inst:
            job._write_final_report( status="stalled", summary_line="stalled" )
        body = inst.write.call_args.kwargs[ "body_md" ]
        assert "## Stall checkpoint" in body
        assert "proposing" in body
        # orchestrator None -> no Clusters/Proposed sections
        assert "## Clusters" not in body

    def test_failed_with_traceback_and_no_optionals( self ):
        job = self._job_with_orch(
            orch=None, failure_traceback="Traceback...\nValueError",
        )   # no cluster_count/fix_count/validation/plan_path/snapshot
        with self._writer() as inst:
            job._write_final_report( status="failed", summary_line="boom" )
        body = inst.write.call_args.kwargs[ "body_md" ]
        assert "## Failure" in body
        assert "Unhandled exception" not in body or "ValueError" in body
        assert "## Appendix" not in body          # no plan/snapshot artifacts

    def test_failure_message_default_when_absent( self ):
        job = self._job_with_orch( orch=None, failure_traceback="tb-only" )  # no failure_message
        with self._writer() as inst:
            job._write_final_report( status="failed", summary_line="x" )
        body = inst.write.call_args.kwargs[ "body_md" ]
        assert "Unhandled exception" in body      # failure_message absent -> default

    def test_writer_exception_returns_none( self, capsys ):
        job = self._job_with_orch( orch=None )
        with self._writer( raises=True ):
            out = job._write_final_report( status="completed", summary_line="x" )
        assert out is None
        assert "Failed to write final report" in capsys.readouterr().out
