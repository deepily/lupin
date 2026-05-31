"""
Unit tests for cosa.agents.bug_fix_expediter.state.

state.py defines the BFE pipeline's data layer:
  - BFEPhase             — 11-member phase enum
  - DeadJobContext       — Pydantic forensic-context model (7 required + optionals)
  - DiagnosisResult      — root-cause model with confidence ge/le validation
  - ProposedFix          — fix-proposal model with defaults
  - FixResult            — fix-outcome model with Phase-5 git / Phase-6 resubmit fields
  - BFEState             — TypedDict (compile-time only; constructed via create_initial_state)
  - create_initial_state — factory seeding phase=PACKAGING + all-None fields
  - BFE_PHASE_ORDINALS   — phase → ordinal map
  - __getattr__          — PEP-562 lazy re-export of TFE exception types (breaks import cycle)

Tests are pure-Python (Pydantic only) — no I/O, no mocking needed except the
lazy-import boundary. quick_smoke_test + __main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import unittest

from cosa.agents.bug_fix_expediter.state import (
    BFEPhase,
    DeadJobContext,
    DiagnosisResult,
    ProposedFix,
    FixResult,
    create_initial_state,
    BFE_PHASE_ORDINALS,
)
import cosa.agents.bug_fix_expediter.state as state_mod

from pydantic import ValidationError


class TestBFEPhase( unittest.TestCase ):
    """BFEPhase enum membership + values."""

    def test_enum_has_eleven_members_with_expected_values( self ):
        # Discriminating: exact count + representative values across the 3 groups
        self.assertEqual( len( BFEPhase ), 11 )
        self.assertEqual( BFEPhase.PACKAGING.value,            "packaging" )
        self.assertEqual( BFEPhase.DIAGNOSING.value,           "diagnosing" )
        self.assertEqual( BFEPhase.PROPOSING.value,            "proposing" )
        self.assertEqual( BFEPhase.FIXING.value,               "fixing" )
        self.assertEqual( BFEPhase.COMMITTING.value,           "committing" )
        self.assertEqual( BFEPhase.RESUBMITTING.value,         "resubmitting" )
        self.assertEqual( BFEPhase.RETRYING.value,             "retrying" )
        self.assertEqual( BFEPhase.WAITING_CONFIRMATION.value, "waiting_confirmation" )
        self.assertEqual( BFEPhase.COMPLETED.value,            "completed" )
        self.assertEqual( BFEPhase.FAILED.value,               "failed" )
        self.assertEqual( BFEPhase.SKIPPED.value,              "skipped" )


class TestDeadJobContext( unittest.TestCase ):
    """DeadJobContext required fields + optional defaults."""

    def test_minimal_construction_defaults_optionals( self ):
        ctx = DeadJobContext(
            id_hash="dr-test::u1", job_type="deep_research",
            user_id="u1", user_email="t@t.com", session_id="s1",
            status="failed", question_text="q",
        )
        self.assertEqual( ctx.status, "failed" )
        self.assertIsNone( ctx.error )
        self.assertIsNone( ctx.stack_trace )
        self.assertIsNone( ctx.routing_command )
        self.assertIsNone( ctx.duration_seconds )
        self.assertEqual( ctx.metadata_json, {} )        # default_factory=dict
        self.assertIsNone( ctx.created_at )

    def test_missing_required_field_raises( self ):
        # question_text omitted → Pydantic ValidationError (required field)
        with self.assertRaises( ValidationError ):
            DeadJobContext(
                id_hash="x", job_type="t", user_id="u",
                user_email="e", session_id="s", status="failed",
            )


class TestDiagnosisResult( unittest.TestCase ):
    """DiagnosisResult confidence bounds + defaults."""

    def test_defaults_and_valid_confidence( self ):
        diag = DiagnosisResult( root_cause="rc", error_category="config", confidence=0.5 )
        self.assertEqual( diag.evidence, [] )
        self.assertEqual( diag.affected_components, [] )
        self.assertFalse( diag.is_transient )

    def test_confidence_above_one_rejected( self ):
        with self.assertRaises( ValidationError ):
            DiagnosisResult( root_cause="rc", error_category="config", confidence=1.5 )

    def test_confidence_below_zero_rejected( self ):
        with self.assertRaises( ValidationError ):
            DiagnosisResult( root_cause="rc", error_category="config", confidence=-0.1 )


class TestProposedFix( unittest.TestCase ):
    """ProposedFix defaults for risk/effort/changes."""

    def test_defaults( self ):
        fix = ProposedFix(
            title="t", description="d", fix_type="config_change", confidence=0.9,
        )
        self.assertEqual( fix.risk_level, "low" )
        self.assertEqual( fix.estimated_effort, "minimal" )
        self.assertEqual( fix.changes, [] )

    def test_confidence_bounds_enforced( self ):
        with self.assertRaises( ValidationError ):
            ProposedFix( title="t", description="d", fix_type="x", confidence=2.0 )


class TestFixResult( unittest.TestCase ):
    """FixResult default + Phase-5/6 optional fields."""

    def test_minimal_defaults( self ):
        r = FixResult( applied=True, success=False )
        self.assertEqual( r.details, "" )
        self.assertFalse( r.retry_eligible )
        self.assertEqual( r.attempts, 0 )
        self.assertIsNone( r.last_stderr )
        self.assertIsNone( r.git_strategy )
        self.assertIsNone( r.commit_hash )
        self.assertIsNone( r.branch_name )
        self.assertIsNone( r.pr_url )
        self.assertIsNone( r.resubmitted_job_id )

    def test_phase5_git_fields_accept_values( self ):
        r = FixResult(
            applied=True, success=True, git_strategy="branch_and_pr",
            commit_hash="abc1234", branch_name="fix/x", pr_url="http://pr",
            resubmitted_job_id="dr-redo::u1", attempts=2, last_stderr="boom",
        )
        self.assertEqual( r.git_strategy, "branch_and_pr" )
        self.assertEqual( r.commit_hash, "abc1234" )
        self.assertEqual( r.branch_name, "fix/x" )
        self.assertEqual( r.pr_url, "http://pr" )
        self.assertEqual( r.resubmitted_job_id, "dr-redo::u1" )
        self.assertEqual( r.attempts, 2 )
        self.assertEqual( r.last_stderr, "boom" )


class TestCreateInitialState( unittest.TestCase ):
    """create_initial_state factory output."""

    def test_seeds_packaging_phase_and_null_fields( self ):
        st = create_initial_state( "dr-test::u1", "extra info" )
        self.assertEqual( st[ "dead_job_id" ],   "dr-test::u1" )
        self.assertEqual( st[ "extra_context" ], "extra info" )
        self.assertIsNone( st[ "dead_job_context" ] )
        self.assertIsNone( st[ "diagnosis" ] )
        self.assertEqual( st[ "proposed_fixes" ], [] )
        self.assertIsNone( st[ "selected_fix" ] )
        self.assertFalse( st[ "user_approved" ] )
        self.assertIsNone( st[ "fix_result" ] )
        self.assertIsNone( st[ "retry_job_id" ] )
        self.assertIsNone( st[ "retry_status" ] )
        self.assertEqual( st[ "phase" ], BFEPhase.PACKAGING.value )
        self.assertIsNone( st[ "error" ] )

    def test_extra_context_defaults_empty( self ):
        st = create_initial_state( "bfe-min::u1" )
        self.assertEqual( st[ "extra_context" ], "" )


class TestPhaseOrdinals( unittest.TestCase ):
    """BFE_PHASE_ORDINALS map ordering."""

    def test_ordinals_monotonic_for_active_phases( self ):
        self.assertEqual( BFE_PHASE_ORDINALS[ BFEPhase.PACKAGING ],    0 )
        self.assertEqual( BFE_PHASE_ORDINALS[ BFEPhase.DIAGNOSING ],   1 )
        self.assertEqual( BFE_PHASE_ORDINALS[ BFEPhase.PROPOSING ],    2 )
        self.assertEqual( BFE_PHASE_ORDINALS[ BFEPhase.FIXING ],       3 )
        self.assertEqual( BFE_PHASE_ORDINALS[ BFEPhase.COMMITTING ],   4 )
        self.assertEqual( BFE_PHASE_ORDINALS[ BFEPhase.RESUBMITTING ], 5 )
        self.assertEqual( BFE_PHASE_ORDINALS[ BFEPhase.RETRYING ],     6 )


class TestLazyGetattr( unittest.TestCase ):
    """PEP-562 module __getattr__ lazy re-export of TFE exception types."""

    def test_reexports_tfe_exception_types( self ):
        # Valid names trigger the lazy import branch (line 212 True → 213-218).
        from cosa.agents.test_fix_expediter.state import (
            VoiceGateTimeoutError, StalledException, CheckpointData,
        )
        self.assertIs( state_mod.VoiceGateTimeoutError, VoiceGateTimeoutError )
        self.assertIs( state_mod.StalledException,      StalledException )
        self.assertIs( state_mod.CheckpointData,        CheckpointData )

    def test_unknown_attribute_raises_attributeerror( self ):
        # Unknown name → line 212 False → line 219 raise.
        with self.assertRaises( AttributeError ) as cm:
            _ = state_mod.does_not_exist
        self.assertIn( "does_not_exist", str( cm.exception ) )


if __name__ == "__main__":
    unittest.main()
