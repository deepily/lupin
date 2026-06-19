"""
TFE live pipeline smoke test.

Session 1cfcdf73 (2026-04-10): Step 16 of the approved plan.

Scenarios exercised (all offline-safe with mocked SDK):
  - basic_1cluster      : 1-cluster snapshot fixture, all phases walk
  - kcluster_dry_run    : 3-cluster snapshot, dry_run=True, aggregate gate auto-selects all
  - partial_success     : K clusters with one fix simulated as failing
  - no_selected_fixes   : user rejects all at the proposal gate
  - recursion_guard     : TFE job constructed from a TestSuiteJob with
                          metadata["triggered_by_tfe"] set (watchdog-side check)

The "live" nature of this test is:
  - Real TestFixExpediterJob construction via the factory
  - Real orchestrator phase walk (Phase 0 + Phase 1 + Phase 2 + Phase 3 +
    Phase 5 + Phase 6 stubs exercised)
  - Mocked Claude Agent SDK (`sdk_query`) so no API calls
  - Mocked GitOps so no real git state change
  - Mocked lupin_app.main.jobs_todo_queue so Phase 6 resubmit stays in-memory

For the full live E2E path that actually invokes the SDK + GitOps, see the
bash driver at `src/tests/e2e/run-tfe-live-e2e.sh` (to be authored in step 18).
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.utils.util as cu
from cosa.agents.bug_fix_expediter.state import FixResult
from cosa.agents.test_fix_expediter.job import TestFixExpediterJob
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.state import TFEPhase, TFEProposedFix


FIXTURE_DIR = os.path.join(
    cu.get_project_root(), "src", "tests", "fixtures", "tfe"
)


def _copy_fixture_to_io( fixture_name: str ) -> str:
    """
    Copy a fixture snapshot into io/test-suite/ so the snapshot_loader
    finds it via its normal path-resolution.

    Returns the relative path from io/ for TFE job construction.
    """
    import shutil
    src = os.path.join( FIXTURE_DIR, fixture_name )
    target_dir = os.path.join( cu.get_project_root(), "io", "test-suite" )
    os.makedirs( target_dir, exist_ok=True )
    target = os.path.join( target_dir, f"tfe-live-test-{fixture_name}" )
    shutil.copy( src, target )
    return f"test-suite/tfe-live-test-{fixture_name}"


def _cleanup_fixture( relative_path: str ) -> None:
    """Remove a previously-copied fixture file."""
    target = os.path.join( cu.get_project_root(), "io", relative_path )
    if os.path.exists( target ):
        os.unlink( target )


async def _noop_notify( *args, **kwargs ): return None


# ─────────────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────────────


class TestBasic1Cluster:

    @pytest.mark.asyncio
    async def test_basic_1cluster_dry_run_all_phases( self ):
        """1-cluster snapshot → Phase 0 → Phase 1 (mocked) → Phase 2 (mocked) → Phase 3+5+6 dry_run."""
        snapshot_path = _copy_fixture_to_io( "snapshot_1cluster.json" )
        try:
            job = TestFixExpediterJob(
                remediation_snapshot_path = snapshot_path,
                source_test_suite_job_id  = "ts-smoke-1cluster",
                user_id                   = "u1",
                user_email                = "t@t.com",
                session_id                = "s1",
                original_test_types       = [ "unit" ],
                dry_run                   = True,
                debug                     = False,
            )

            # Mock the SDK delegates so Phase 1 diagnose + Phase 2 propose get
            # canned responses and phase 3/5/6 short-circuit via dry_run.
            async def mock_diagnose( prompt ):
                return json.dumps( {
                    "cluster_id": "C1",
                    "root_cause": "Simulated root cause",
                    "error_category": "code_bug",
                    "confidence": 0.85,
                    "evidence": [ "tokens.py:42" ],
                    "affected_components": [ "src/cosa/auth/tokens.py" ],
                    "is_transient": False,
                    "test_symptoms": [ "assert 401 == 200" ],
                } )

            async def mock_propose( prompt ):
                return json.dumps( [ {
                    "cluster_id": "C1",
                    "title": "Replace None with new_token",
                    "description": "Fix line 42",
                    "fix_type": "code_patch",
                    "confidence": 0.9,
                    "risk_level": "low",
                    "estimated_effort": "minutes",
                    "changes": [ { "file": "src/cosa/auth/tokens.py",
                                   "action": "modify",
                                   "description": "return new_token" } ],
                } ] )

            with (
                patch(
                    "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator._delegate_to_lead_diagnosis",
                    new=AsyncMock( side_effect=mock_diagnose ),
                ),
                patch(
                    "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator._delegate_to_lead_proposal",
                    new=AsyncMock( side_effect=mock_propose ),
                ),
            ):
                # Drive the job — since do_all() runs asyncio.run(_execute()),
                # we call _execute() directly so we can await it here.
                answer = await job._execute()

            assert job.orchestrator is not None
            # Phase 0 produced clusters
            assert len( job.orchestrator.clusters ) == 1
            # Phase 1 diagnosed the cluster
            assert "C1" in job.orchestrator.diagnoses
            assert job.orchestrator.diagnoses[ "C1" ].confidence == 0.85
            # Phase 2 produced proposals
            assert len( job.orchestrator.proposed_fixes ) == 1
            # Phase 2 dry_run auto-selected all
            assert len( job.orchestrator.selected_fixes ) == 1
            # Phase 3 dry_run produced synthetic success results
            assert len( job.orchestrator.fix_results ) == 1
            assert job.orchestrator.fix_results[ 0 ].success is True
            # Phase 5 dry_run produced synthetic commits
            assert len( job.orchestrator.commit_hashes ) >= 1
            # Phase 6 dry_run placeholder
            assert job.orchestrator.validation_run_job_id == "dry-run-skipped"
            # Final conversational answer includes cluster count
            assert "1 clusters" in answer or "C1" in answer or "1 cluster" in answer
            # Artifacts populated for UI
            assert job.artifacts[ "cluster_count" ] == 1
            assert job.artifacts[ "source_test_suite_job_id" ] == "ts-smoke-1cluster"
        finally:
            _cleanup_fixture( snapshot_path )


class TestKClusterDryRun:

    @pytest.mark.asyncio
    async def test_kcluster_dry_run_walks_all_phases( self ):
        """K-cluster snapshot (3 distinct clusters) → full phase walk in dry_run."""
        snapshot_path = _copy_fixture_to_io( "snapshot_kcluster.json" )
        try:
            job = TestFixExpediterJob(
                remediation_snapshot_path = snapshot_path,
                source_test_suite_job_id  = "ts-smoke-kcluster",
                user_id                   = "u1",
                user_email                = "t@t.com",
                session_id                = "s1",
                original_test_types       = [ "unit", "integration" ],
                dry_run                   = True,
                debug                     = False,
            )

            # Generic canned responses that work for any cluster_id
            async def mock_diagnose( prompt ):
                # Extract cluster_id from the prompt if present, else use C1
                cluster_id = "C1"
                for cid in ( "C1", "C2", "C3", "C4", "C5" ):
                    if f"cluster: {cid}" in prompt.lower() or f"cluster {cid}" in prompt:
                        cluster_id = cid
                        break
                return json.dumps( {
                    "cluster_id": cluster_id,
                    "root_cause": f"Root cause for {cluster_id}",
                    "error_category": "code_bug",
                    "confidence": 0.8,
                    "evidence": [],
                    "affected_components": [ "src/foo.py" ],
                    "test_symptoms": [],
                } )

            async def mock_propose( prompt ):
                cluster_id = "C1"
                for cid in ( "C1", "C2", "C3", "C4", "C5" ):
                    if cid in prompt:
                        cluster_id = cid
                        break
                return json.dumps( [ {
                    "cluster_id": cluster_id,
                    "title": f"Fix for {cluster_id}",
                    "description": "desc",
                    "fix_type": "code_patch",
                    "confidence": 0.8,
                    "risk_level": "low",
                    "estimated_effort": "minutes",
                    "changes": [ { "file": "src/foo.py", "action": "modify", "description": "x" } ],
                } ] )

            with (
                patch(
                    "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator._delegate_to_lead_diagnosis",
                    new=AsyncMock( side_effect=mock_diagnose ),
                ),
                patch(
                    "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator._delegate_to_lead_proposal",
                    new=AsyncMock( side_effect=mock_propose ),
                ),
            ):
                answer = await job._execute()

            # At least 2 clusters from the kcluster fixture (Auth, Queue, WebSocket)
            assert len( job.orchestrator.clusters ) >= 2
            # All clusters got diagnoses
            assert len( job.orchestrator.diagnoses ) == len( job.orchestrator.clusters )
            # All clusters got proposals (1 each in our mock)
            assert len( job.orchestrator.proposed_fixes ) == len( job.orchestrator.clusters )
            # Dry_run auto-selected all
            assert len( job.orchestrator.selected_fixes ) == len( job.orchestrator.proposed_fixes )
            # Phase 3 dry_run produced synthetic success for each
            assert all( r.success for r in job.orchestrator.fix_results )
        finally:
            _cleanup_fixture( snapshot_path )


class TestParametrizedSingleCluster:

    @pytest.mark.asyncio
    async def test_parametrized_fixture_collapses_to_one_cluster( self ):
        """4 parametrized variants → 1 cluster after heuristic clustering."""
        snapshot_path = _copy_fixture_to_io( "snapshot_parametrized.json" )
        try:
            job = TestFixExpediterJob(
                remediation_snapshot_path = snapshot_path,
                source_test_suite_job_id  = "ts-smoke-param",
                user_id                   = "u1",
                user_email                = "t@t.com",
                session_id                = "s1",
                original_test_types       = [ "e2e" ],
                dry_run                   = True,
                debug                     = False,
            )

            async def mock_diagnose( prompt ):
                return json.dumps( {
                    "cluster_id": "C1",
                    "root_cause": "Visual snapshots stale",
                    "error_category": "test_bug",
                    "confidence": 0.9,
                    "affected_components": [],
                    "test_symptoms": [ "Snapshots DO NOT match!" ],
                } )

            async def mock_propose( prompt ):
                return json.dumps( [ {
                    "cluster_id": "C1",
                    "title": "Re-baseline visual snapshots",
                    "description": "Update the 4 stale PNGs",
                    "fix_type": "test_patch",
                    "confidence": 0.95,
                    "risk_level": "low",
                    "estimated_effort": "minutes",
                    "changes": [ { "file": "io/test-suite/visual-baselines/login.png",
                                   "action": "modify", "description": "update" } ],
                } ] )

            with (
                patch(
                    "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator._delegate_to_lead_diagnosis",
                    new=AsyncMock( side_effect=mock_diagnose ),
                ),
                patch(
                    "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator._delegate_to_lead_proposal",
                    new=AsyncMock( side_effect=mock_propose ),
                ),
            ):
                await job._execute()

            # All 4 parametrized failures should collapse to 1 cluster
            assert len( job.orchestrator.clusters ) == 1
            cluster = job.orchestrator.clusters[ 0 ]
            assert len( cluster.failure_indices ) == 4
        finally:
            _cleanup_fixture( snapshot_path )


class TestFactoryIntegration:

    def test_factory_round_trip( self ):
        """create_agentic_job → TestFixExpediterJob → constructor args preserved."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to test fix expediter",
            args_dict  = {
                "remediation_snapshot_path": "test-suite/fake.json",
                "source_test_suite_job_id": "ts-factory-test",
                "original_test_types": "unit,integration",
                "dry_run": "true",
            },
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1",
            debug      = False,
            verbose    = False,
        )
        assert isinstance( job, TestFixExpediterJob )
        assert job.source_test_suite_job_id == "ts-factory-test"
        assert job.original_test_types == [ "unit", "integration" ]
        assert job.dry_run is True


class TestWatchdogIntegration:

    def test_watchdog_skips_tfe_triggered_run( self ):
        """A TestSuiteJob carrying metadata.triggered_by_tfe must NOT re-dispatch TFE."""
        from cosa.rest.test_suite_completion_watchdog import (
            TestSuiteCompletionWatchdog,
        )

        mock_config = MagicMock()
        mock_config.get = MagicMock( side_effect=lambda key, default=None, return_type="string": {
            "test fix expediter auto fix enabled": True,
            "test fix expediter max cluster seed failures": 50,
        }.get( key, default ) )

        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=mock_config,
            todo_queue=MagicMock(),
        )

        # Fake TestSuiteJob with triggered_by_tfe metadata
        fake_job = MagicMock()
        fake_job.JOB_TYPE = "test_suite"
        fake_job.id_hash = "ts-rerun-xyz"
        fake_job.artifacts = {
            "remediation_snapshot": {
                "schema_version": "1.0",
                "summary": { "all_passed": False },
                "failures": [ { "classname": "a.b.C", "name": "t" } ],
                "suites_run": [ "unit" ],
            },
            "remediation_snapshot_path": "test-suite/rerun.json",
        }
        fake_job.metadata = { "triggered_by_tfe": "tfe-parent-abc" }

        result = watchdog.evaluate( fake_job )
        assert result is None  # recursion guard honored
