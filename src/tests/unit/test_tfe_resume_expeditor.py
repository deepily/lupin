"""
Unit tests for TFE resume voice expeditor integration.

Session 9056c113 doc 16 Phase 2. Tests:
- agent_registry entry present + correct
- Expeditor._handle_tfe_checkpoint_match auto-selects high-confidence matches
- Falls back to _ask_for_arg when no candidates
- Fast-path for literal job IDs / plan paths (skips LLM)
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Agent registry entry
# ---------------------------------------------------------------------------

class TestAgentRegistryEntry:
    """agent_registry.py has the TFE resume entry with expected shape."""

    def test_tfe_resume_entry_exists( self ):
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS as AGENT_REGISTRY
        assert "agent router go to test fix expediter resume" in AGENT_REGISTRY

    def test_tfe_resume_entry_has_required_fields( self ):
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS as AGENT_REGISTRY
        entry = AGENT_REGISTRY[ "agent router go to test fix expediter resume" ]

        assert entry[ "display_name" ] == "TFE Resume"
        assert "resume_from" in entry[ "required_user_args" ]
        assert entry[ "special_handlers" ][ "resume_from" ] == "tfe_checkpoint_match"

    def test_tfe_resume_arg_mapping_covers_common_synonyms( self ):
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS as AGENT_REGISTRY
        entry = AGENT_REGISTRY[ "agent router go to test fix expediter resume" ]
        mapping = entry[ "arg_mapping" ]

        # Users may say "job_id", "plan_path", "checkpoint", "description"
        assert mapping[ "job_id" ]      == "resume_from"
        assert mapping[ "plan_path" ]   == "resume_from"
        assert mapping[ "checkpoint" ]  == "resume_from"
        assert mapping[ "description" ] == "resume_from"


# ---------------------------------------------------------------------------
# _handle_tfe_checkpoint_match fast-path (literal job ID or plan path)
# ---------------------------------------------------------------------------

def _make_expeditor():
    """Build a minimal Expeditor instance bypassing real config."""
    from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
    config_mgr = MagicMock()
    exp = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
    exp.config_mgr = config_mgr
    exp.debug      = False
    exp.verbose    = False
    return exp


class TestHandleTfeCheckpointMatchFastPath:
    """Literal job IDs and plan paths short-circuit the LLM call."""

    def test_job_id_fast_path_returns_directly( self ):
        exp = _make_expeditor()
        candidates = [ { "job_id": "tfe-xyz::u1", "status": "stalled", "summary": "test" } ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ):
            result = exp._handle_tfe_checkpoint_match(
                user_email="u@test.com",
                user_description="tfe-xyz::u1"
            )

        assert result == "tfe-xyz::u1"

    def test_plan_path_fast_path_returns_directly( self ):
        exp = _make_expeditor()
        candidates = [ { "job_id": "tfe-x::u1", "status": "stalled" } ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ):
            result = exp._handle_tfe_checkpoint_match(
                user_email="u@test.com",
                user_description="io/swe-team/plans/user@test.com/2026.04.12-1-clusters-from-tsabc-c1-plan.md"
            )

        assert result.endswith( "c1-plan.md" )


# ---------------------------------------------------------------------------
# _handle_tfe_checkpoint_match LLM fuzzy match paths
# ---------------------------------------------------------------------------

class TestHandleTfeCheckpointMatchFuzzy:

    def test_high_confidence_stalled_match_auto_selected( self ):
        exp = _make_expeditor()
        candidates = [ { "job_id": "tfe-a::u1", "status": "stalled" } ]
        matches    = [ { "job_id": "tfe-a::u1", "status": "stalled", "confidence": 0.95, "reason": "exact" } ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ), patch(
            "cosa.agents.test_fix_expediter.resume_resolver.fuzzy_match_candidates",
            return_value=matches
        ):
            result = exp._handle_tfe_checkpoint_match(
                user_email="u@test.com",
                user_description="the visual regression one"
            )

        assert result == "tfe-a::u1"

    def test_high_confidence_but_non_stalled_falls_through_to_disambiguation( self ):
        """Confidence is high but job status is 'completed' — should NOT auto-select.

        The user must disambiguate via _ask_for_arg."""
        exp = _make_expeditor()
        candidates = [ { "job_id": "tfe-done::u1", "status": "completed" } ]
        matches    = [ { "job_id": "tfe-done::u1", "status": "completed", "confidence": 0.95, "reason": "exact" } ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ), patch(
            "cosa.agents.test_fix_expediter.resume_resolver.fuzzy_match_candidates",
            return_value=matches
        ), patch.object( exp, "_ask_for_arg", return_value="1" ) as mock_ask:
            result = exp._handle_tfe_checkpoint_match(
                user_email="u@test.com",
                user_description="the completed one"
            )

        # Should have asked user to confirm even though confidence was high
        mock_ask.assert_called_once()
        assert result == "tfe-done::u1"   # user picked #1

    def test_no_candidates_prompts_manual_entry( self ):
        exp = _make_expeditor()

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=[]
        ), patch.object( exp, "_ask_for_arg", return_value="tfe-manual::u1" ) as mock_ask:
            result = exp._handle_tfe_checkpoint_match(
                user_email="u@test.com",
                user_description="anything"
            )

        # Should have prompted manual entry fallback
        mock_ask.assert_called_once()
        assert "No stalled TFE jobs" in mock_ask.call_args[ 0 ][ 1 ]
        assert result == "tfe-manual::u1"

    def test_user_cancels_returns_none( self ):
        exp = _make_expeditor()
        candidates = [ { "job_id": "tfe-a::u1", "status": "stalled" } ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ), patch.object( exp, "_ask_for_arg", return_value=None ):
            result = exp._handle_tfe_checkpoint_match( user_email="u@test.com" )

        assert result is None

    def test_numeric_disambiguation_pick( self ):
        """User types '2' → picks second candidate."""
        exp = _make_expeditor()
        candidates = [
            { "job_id": "tfe-a::u1", "status": "stalled" },
            { "job_id": "tfe-b::u1", "status": "stalled" },
            { "job_id": "tfe-c::u1", "status": "stalled" },
        ]
        matches = [
            { "job_id": "tfe-a::u1", "status": "stalled", "confidence": 0.7, "summary": "s1" },
            { "job_id": "tfe-b::u1", "status": "stalled", "confidence": 0.6, "summary": "s2" },
            { "job_id": "tfe-c::u1", "status": "stalled", "confidence": 0.5, "summary": "s3" },
        ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ), patch(
            "cosa.agents.test_fix_expediter.resume_resolver.fuzzy_match_candidates",
            return_value=matches
        ), patch.object( exp, "_ask_for_arg", return_value="2" ):
            result = exp._handle_tfe_checkpoint_match(
                user_email="u@test.com",
                user_description="vague"
            )

        assert result == "tfe-b::u1"
