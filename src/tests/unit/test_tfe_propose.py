"""
Unit tests for TFE Phase 2 propose.

Session 1cfcdf73 (2026-04-10): Step 9 implementation tests. Mocks the
SDK delegate + cosa_interface voice gate for offline-safe runs.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.state import (
    FailureCluster,
    TFEPhase,
    TFEProposedFix,
    TestDiagnosisResult,
    TestRemediationContext,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


def _make_ctx():
    return TestRemediationContext(
        source_test_suite_job_id = "ts-test",
        snapshot_path            = "p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [ "unit" ],
        summary                  = { "all_passed": False, "total_failed": 2 },
        failures                 = [
            {
                "classname": "src.tests.unit.test_auth.TestLogin",
                "name": "test_ok", "type": "FAILED",
                "message": "assert 401 == 200",
                "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh',
            },
            {
                "classname": "src.tests.unit.test_queue.TestQueue",
                "name": "test_push", "type": "FAILED",
                "message": "assert 0 == 1",
                "traceback": 'File "src/cosa/rest/queue.py", line 87, in push',
            },
        ],
        original_test_types      = [ "unit" ],
        user_id                  = "u1",
        user_email               = "t@t.com",
        session_id               = "s1",
    )


def _make_orchestrator( dry_run: bool = True, **config_overrides ):
    ctx = _make_ctx()
    config = TestFixExpediterConfig( **config_overrides )
    return TFEOrchestrator(
        remediation_context = ctx,
        config              = config,
        user_id             = "u1",
        user_email          = "t@t.com",
        session_id          = "s1",
        job_id              = "tfe-smoke",
        dry_run             = dry_run,
        debug               = False,
    )


async def _setup_clusters_and_diagnoses( orch ):
    """Run Phase 0 and inject canned diagnoses so Phase 2 has inputs."""
    await orch.run_phase0_cluster()
    orch.diagnoses = {
        c.cluster_id: TestDiagnosisResult(
            cluster_id=c.cluster_id,
            root_cause=f"root cause for {c.cluster_id}",
            error_category="code_bug",
            confidence=0.8,
            evidence=[ "file.py:42" ],
            affected_components=[ "src/foo.py" ],
            test_symptoms=[ "assert 401 == 200" ],
        )
        for c in orch.clusters
    }


def _proposal_response( cluster_id: str, n: int = 1 ) -> str:
    """Build a valid JSON array response for N proposals."""
    proposals = []
    for i in range( n ):
        proposals.append( {
            "cluster_id"       : cluster_id,
            "title"            : f"Fix {cluster_id}.{i}",
            "description"      : f"Description for {cluster_id}.{i}",
            "fix_type"         : "code_patch",
            "confidence"       : 0.85 - i * 0.1,
            "risk_level"       : "low",
            "estimated_effort" : "minutes",
            "changes"          : [ { "file": "src/foo.py", "action": "modify", "description": "fix" } ],
        } )
    return f"```json\n{json.dumps( proposals )}\n```"


# ─────────────────────────────────────────────────────────────────────────
# JSON parser tests
# ─────────────────────────────────────────────────────────────────────────


class TestParseProposalResult:

    def test_valid_array( self ):
        orch = _make_orchestrator()
        raw = _proposal_response( "C1", n=2 )
        result = orch._parse_proposal_result( raw, "C1" )
        assert len( result ) == 2
        assert all( isinstance( p, TFEProposedFix ) for p in result )
        assert result[ 0 ].cluster_id == "C1"

    def test_single_object_wrapped_in_array( self ):
        """If LLM returns a single JSON object instead of an array, wrap it."""
        orch = _make_orchestrator()
        payload = {
            "cluster_id"       : "C1",
            "title"            : "One fix",
            "description"      : "Only proposal",
            "fix_type"         : "code_patch",
            "confidence"       : 0.9,
            "risk_level"       : "low",
            "estimated_effort" : "minutes",
            "changes"          : [ { "file": "src/x.py", "action": "modify", "description": "x" } ],
        }
        raw = json.dumps( payload )
        result = orch._parse_proposal_result( raw, "C1" )
        assert len( result ) == 1

    def test_missing_cluster_id_populated( self ):
        orch = _make_orchestrator()
        payload = [ {
            "title": "x", "description": "y", "fix_type": "code_patch",
            "confidence": 0.8, "risk_level": "low", "estimated_effort": "minutes",
            "changes": [],
        } ]
        raw = json.dumps( payload )
        result = orch._parse_proposal_result( raw, "C3" )
        assert len( result ) == 1
        assert result[ 0 ].cluster_id == "C3"

    def test_invalid_json_empty_list( self ):
        orch = _make_orchestrator()
        assert orch._parse_proposal_result( "no json", "C1" ) == []

    def test_object_at_root_not_array( self ):
        """If the object can't be a valid TFEProposedFix either, return empty."""
        orch = _make_orchestrator()
        raw = '{"unrelated": "field"}'
        result = orch._parse_proposal_result( raw, "C1" )
        # The parser wraps the object in an array, but validation drops it
        assert result == []

    def test_dropped_invalid_items( self ):
        """Invalid items are dropped but valid ones are kept."""
        orch = _make_orchestrator()
        payload = [
            {
                "cluster_id": "C1", "title": "good", "description": "ok",
                "fix_type": "code_patch", "confidence": 0.8,
                "risk_level": "low", "estimated_effort": "minutes", "changes": [],
            },
            { "incomplete": "data" },
        ]
        raw = json.dumps( payload )
        result = orch._parse_proposal_result( raw, "C1" )
        assert len( result ) == 1
        assert result[ 0 ].title == "good"

    # NOTE (2026-06-03): the standalone `_extract_last_json_array` helper was removed
    # when proposal parsing moved to `_parse_proposal_json` (handles clean JSON, fenced,
    # prose-embedded arrays AND single objects). Its two unit tests were deleted as stale
    # — the array-extraction path is now covered by the `TestParseProposalResult` cases
    # above (`_parse_proposal_result` → `_parse_proposal_json`).


# ─────────────────────────────────────────────────────────────────────────
# run_phase2_propose tests
# ─────────────────────────────────────────────────────────────────────────


class TestPhase2Propose:

    @pytest.mark.asyncio
    async def test_happy_path_with_dry_run( self ):
        """In dry_run, all proposals are auto-selected and no plan doc is written."""
        orch = _make_orchestrator( dry_run=True )
        await _setup_clusters_and_diagnoses( orch )

        with patch.object(
            orch, "_delegate_to_lead_proposal", new=AsyncMock(
                side_effect=lambda prompt: _proposal_response(
                    # Extract cluster_id from prompt context
                    "C1" if "C1" in prompt else "C2", n=1
                )
            )
        ):
            proposed, selected, plan_path = await orch.run_phase2_propose()

        assert len( proposed ) == len( orch.clusters )
        assert len( selected ) == len( proposed )   # dry_run auto-selects all
        assert plan_path is None   # dry_run skips plan doc write
        assert orch.current_phase == TFEPhase.PROPOSING

    @pytest.mark.asyncio
    async def test_no_diagnoses_empty_result( self ):
        orch = _make_orchestrator( dry_run=True )
        # No Phase 0 or Phase 1 run — clusters and diagnoses both empty
        proposed, selected, plan_path = await orch.run_phase2_propose()
        assert proposed == []
        assert selected == []
        assert plan_path is None

    @pytest.mark.asyncio
    async def test_sdk_unavailable_empty_result( self ):
        orch = _make_orchestrator( dry_run=True )
        await _setup_clusters_and_diagnoses( orch )

        with patch(
            "cosa.agents.test_fix_expediter.orchestrator.SDK_AVAILABLE", False
        ):
            proposed, selected, plan_path = await orch.run_phase2_propose()

        assert proposed == []
        assert selected == []

    @pytest.mark.asyncio
    async def test_per_cluster_propose_skips_missing_diagnosis( self ):
        orch = _make_orchestrator( dry_run=True )
        await orch.run_phase0_cluster()
        # Only diagnose C1 (leave C2+ without diagnoses)
        first_id = orch.clusters[ 0 ].cluster_id
        orch.diagnoses = {
            first_id: TestDiagnosisResult(
                cluster_id=first_id, root_cause="x", error_category="code_bug",
                confidence=0.8,
            )
        }

        with patch.object(
            orch, "_delegate_to_lead_proposal", new=AsyncMock(
                return_value=_proposal_response( first_id, n=1 )
            )
        ) as mock_delegate:
            proposed, _selected, _plan = await orch.run_phase2_propose()

        # Only one delegate call (for the one diagnosed cluster)
        assert mock_delegate.call_count == 1
        assert len( proposed ) == 1

    @pytest.mark.asyncio
    async def test_empty_proposal_from_llm( self ):
        """When the LLM returns an empty array, we keep going with empty proposals."""
        orch = _make_orchestrator( dry_run=True )
        await _setup_clusters_and_diagnoses( orch )

        with patch.object(
            orch, "_delegate_to_lead_proposal", new=AsyncMock( return_value="[]" )
        ):
            proposed, selected, _plan = await orch.run_phase2_propose()

        assert proposed == []
        assert selected == []

    @pytest.mark.asyncio
    async def test_cancellation_halts_mid_run( self ):
        orch = _make_orchestrator( dry_run=True )
        orch.clusters = [
            FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="a" ),
            FailureCluster( cluster_id="C2", failure_indices=[ 1 ], shared_error_signature="b" ),
        ]
        orch.diagnoses = {
            "C1": TestDiagnosisResult( cluster_id="C1", root_cause="x", error_category="code_bug", confidence=0.8 ),
            "C2": TestDiagnosisResult( cluster_id="C2", root_cause="y", error_category="code_bug", confidence=0.8 ),
        }

        call_count = [ 0 ]
        async def mock_propose( cluster, diagnosis ):
            call_count[ 0 ] += 1
            if cluster.cluster_id == "C1":
                orch.request_stop()
                return [ TFEProposedFix(
                    cluster_id="C1", title="fix", description="d",
                    fix_type="code_patch", confidence=0.8,
                ) ]
            return []

        with patch.object( orch, "_propose_for_cluster", side_effect=mock_propose ):
            proposed, _selected, _plan = await orch.run_phase2_propose()

        # C1 processed, C2 halted
        assert call_count[ 0 ] == 1
        assert len( proposed ) == 1


# ─────────────────────────────────────────────────────────────────────────
# Voice gate tests
# ─────────────────────────────────────────────────────────────────────────


class TestProposalVoiceGate:

    def _make_proposals( self, n: int = 3 ):
        return [
            TFEProposedFix(
                cluster_id=f"C{i+1}", title=f"Fix {i+1}",
                description=f"desc {i+1}", fix_type="code_patch",
                confidence=0.8, risk_level="low", estimated_effort="minutes",
                changes=[ { "file": f"src/f{i}.py", "action": "modify", "description": "x" } ],
            )
            for i in range( n )
        ]

    @pytest.mark.asyncio
    async def test_dry_run_auto_selects_all( self ):
        orch = _make_orchestrator( dry_run=True )
        proposals = self._make_proposals( 3 )
        selected = await orch._proposal_voice_gate( proposals )
        assert len( selected ) == 3

    @pytest.mark.asyncio
    async def test_aggregate_mode_user_selects_subset( self ):
        orch = _make_orchestrator( dry_run=False, voice_gate_mode="aggregate" )
        proposals = self._make_proposals( 3 )

        with patch(
            "cosa.agents.test_fix_expediter.cosa_interface.present_choices",
            new=AsyncMock( return_value={
                "answers": { "Fixes": [ "C1: Fix 1", "C3: Fix 3" ] },
            } )
        ):
            selected = await orch._proposal_voice_gate( proposals )

        assert len( selected ) == 2
        assert selected[ 0 ].cluster_id == "C1"
        assert selected[ 1 ].cluster_id == "C3"

    @pytest.mark.asyncio
    async def test_aggregate_mode_user_selects_none( self ):
        orch = _make_orchestrator( dry_run=False, voice_gate_mode="aggregate" )
        proposals = self._make_proposals( 2 )

        with patch(
            "cosa.agents.test_fix_expediter.cosa_interface.present_choices",
            new=AsyncMock( return_value={ "answers": { "Fixes": [] } } )
        ):
            selected = await orch._proposal_voice_gate( proposals )

        assert selected == []

    @pytest.mark.asyncio
    async def test_aggregate_mode_voice_gate_error_auto_selects( self ):
        """On voice gate exception, fall back to auto-selecting all proposals."""
        orch = _make_orchestrator( dry_run=False, voice_gate_mode="aggregate" )
        proposals = self._make_proposals( 2 )

        with patch(
            "cosa.agents.test_fix_expediter.cosa_interface.present_choices",
            new=AsyncMock( side_effect=RuntimeError( "voice unavailable" ) )
        ):
            selected = await orch._proposal_voice_gate( proposals )

        assert len( selected ) == 2

    @pytest.mark.asyncio
    async def test_per_cluster_mode( self ):
        orch = _make_orchestrator( dry_run=False, voice_gate_mode="per_cluster" )
        proposals = self._make_proposals( 3 )

        answers = [ "yes", "no", "yes" ]
        answer_iter = iter( answers )

        async def mock_ask( **kwargs ):
            return next( answer_iter )

        with patch(
            "cosa.agents.test_fix_expediter.cosa_interface.ask_confirmation",
            side_effect=mock_ask
        ):
            selected = await orch._proposal_voice_gate( proposals )

        assert len( selected ) == 2   # C1 and C3 accepted, C2 rejected
        assert selected[ 0 ].cluster_id == "C1"
        assert selected[ 1 ].cluster_id == "C3"

    def test_render_proposal_abstract( self ):
        proposals = [
            TFEProposedFix(
                cluster_id="C1", title="T1", description="D1",
                fix_type="code_patch", confidence=0.8,
            ),
            TFEProposedFix(
                cluster_id="C2", title="T2", description="D2",
                fix_type="test_patch", confidence=0.6,
            ),
        ]
        abstract = TFEOrchestrator._render_proposal_abstract( proposals )
        assert "2 proposed fixes" in abstract
        assert "C1" in abstract
        assert "T1" in abstract
        assert "C2" in abstract
        assert "T2" in abstract

    def test_render_single_proposal( self ):
        p = TFEProposedFix(
            cluster_id="C1", title="Fix X", description="Description text",
            fix_type="code_patch", confidence=0.85, risk_level="medium",
            estimated_effort="hours",
            changes=[ { "file": "a.py", "action": "modify", "description": "x" } ],
        )
        rendered = TFEOrchestrator._render_single_proposal( p )
        assert "C1: Fix X" in rendered
        assert "code_patch" in rendered
        assert "85%" in rendered
        assert "medium" in rendered
        assert "hours" in rendered
        assert "Description text" in rendered
