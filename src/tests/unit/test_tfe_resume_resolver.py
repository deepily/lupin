"""
Unit tests for TFE resume resolver — file-path-based resume dispatcher.

Session 9056c113 continued (2026-04-12): Phase 1 of the file-path resume plan.
Tests exact-match paths (job ID + plan doc path). Fuzzy natural-language
matching is Phase 2 (deferred).

See: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/15-file-path-resume-and-voice-parsing.md
"""

import os
import re

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# ResumeTarget model + resolver dispatch
# ---------------------------------------------------------------------------

class TestResumeTargetModel:
    """ResumeTarget Pydantic model basics."""

    def test_default_source_type_is_not_found( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import ResumeTarget
        t = ResumeTarget()
        assert t.source_type == "not_found"
        assert t.job_id is None
        assert t.confidence == 1.0
        assert t.candidates == []

    def test_confidence_bounds_enforced( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import ResumeTarget
        with pytest.raises( Exception ):
            ResumeTarget( confidence=1.5 )
        with pytest.raises( Exception ):
            ResumeTarget( confidence=-0.1 )


class TestDispatchLogic:
    """resolve_resume_target() dispatches to the right resolver by input shape."""

    def test_empty_input_returns_not_found( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target
        t = resolve_resume_target( "", "user@test.com" )
        assert t.source_type == "not_found"
        assert "empty" in t.diagnostic.lower()

    def test_whitespace_input_returns_not_found( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target
        t = resolve_resume_target( "   \n\t  ", "user@test.com" )
        assert t.source_type == "not_found"

    def test_natural_language_routes_to_fuzzy_match( self ):
        """Natural language goes through fuzzy match (which needs candidates)."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        # With no candidates, returns not_found (but via fuzzy path, not Phase 1 short-circuit)
        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=[]
        ):
            t = resolve_resume_target( "the stalled tfe job from today", "user@test.com" )
        assert t.source_type == "not_found"
        assert "No stalled" in t.diagnostic

    def test_checkpoint_json_returns_not_found_with_deferred_hint( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target
        t = resolve_resume_target( "io/checkpoint.json", "user@test.com" )
        assert t.source_type == "not_found"
        assert "not yet implemented" in t.diagnostic


# ---------------------------------------------------------------------------
# Type 1: Job ID resolution
# ---------------------------------------------------------------------------

class TestJobIdResolution:
    """Job IDs (tfe-*) dispatch to _resolve_by_job_id."""

    def test_fully_qualified_job_id_found_stalled( self ):
        """tfe-abc::user1 → checkpoint exists → returns ResumeTarget with job_id set."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        fake_checkpoint = {
            "phase_ordinal": 3, "phase_name": "proposing", "state_snapshot": {}
        }
        with patch(
            "cosa.rest.job_persistence.get_checkpoint_for_job",
            return_value=fake_checkpoint
        ):
            t = resolve_resume_target( "tfe-abc12345::user@test.com", "user@test.com" )

        assert t.source_type == "job_id"
        assert t.job_id == "tfe-abc12345::user@test.com"
        assert t.confidence == 1.0

    def test_bare_job_id_gets_scoped_to_user_email( self ):
        """Bare tfe-abc → tfe-abc::user@test.com lookup."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        fake_checkpoint = { "phase_ordinal": 3, "phase_name": "proposing", "state_snapshot": {} }
        with patch(
            "cosa.rest.job_persistence.get_checkpoint_for_job",
            return_value=fake_checkpoint
        ) as mock_get:
            t = resolve_resume_target( "tfe-abc12345", "user@test.com" )

        # Should have tried the user-scoped form
        mock_get.assert_called_once_with( "tfe-abc12345::user@test.com" )
        assert t.source_type == "job_id"
        assert t.job_id == "tfe-abc12345::user@test.com"

    def test_job_id_not_stalled_returns_not_found( self ):
        """Job exists but not stalled → get_checkpoint_for_job returns None → not_found."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        with patch(
            "cosa.rest.job_persistence.get_checkpoint_for_job",
            return_value=None
        ):
            t = resolve_resume_target( "tfe-abc12345::user@test.com", "user@test.com" )

        assert t.source_type == "not_found"
        assert "not found" in t.diagnostic.lower() or "not stalled" in t.diagnostic.lower()


# ---------------------------------------------------------------------------
# Type 2: Plan path resolution
# ---------------------------------------------------------------------------

class TestPlanPathResolution:
    """Plan doc paths dispatch to _resolve_by_plan_path."""

    def test_plan_filename_pattern_parses_source_id( self ):
        """Regex extracts source_id (packed, no dashes) from plan filename."""
        from cosa.agents.test_fix_expediter.resume_resolver import _PLAN_FILENAME_PATTERN

        filename = "2026.04.12-1-clusters-from-ts86c172f70cf47e2dd5a14cd4addf79810fd32b15-c1-plan.md"
        match = _PLAN_FILENAME_PATTERN.match( filename )
        assert match is not None
        assert match.group( "source_id" ) == "ts86c172f70cf47e2dd5a14cd4addf79810fd32b15"

    def test_plan_filename_with_multiple_clusters( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import _PLAN_FILENAME_PATTERN
        filename = "2026.04.11-3-clusters-from-tsabcdef123-c2-plan.md"
        match = _PLAN_FILENAME_PATTERN.match( filename )
        assert match is not None
        assert match.group( "source_id" ) == "tsabcdef123"

    def test_non_plan_filename_rejected( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import _PLAN_FILENAME_PATTERN
        for bad in [
            "random-file.md",
            "2026.04.12-notes.md",
            "2026.04.12-1-clusters-wrong.md",
            "c1-plan.md",
        ]:
            assert _PLAN_FILENAME_PATTERN.match( bad ) is None, f"Expected rejection of: {bad}"

    def test_plan_path_missing_file_returns_not_found( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        t = resolve_resume_target(
            "io/swe-team/plans/user@test.com/nonexistent-c1-plan.md",
            "user@test.com"
        )
        assert t.source_type == "not_found"
        assert "not found" in t.diagnostic.lower()
        assert t.matched_path == "io/swe-team/plans/user@test.com/nonexistent-c1-plan.md"

    def test_plan_path_with_unparseable_filename( self, tmp_path ):
        """File exists but filename doesn't match the expected pattern."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        bad_plan = tmp_path / "random-plan.md"
        bad_plan.write_text( "dummy" )

        t = resolve_resume_target( str( bad_plan ), "user@test.com" )
        assert t.source_type == "not_found"
        assert "does not match" in t.diagnostic or "pattern" in t.diagnostic

    def test_plan_path_found_but_no_stalled_job( self, tmp_path ):
        """File exists, filename parses, but no stalled TFE job references it."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        plan_file = tmp_path / "2026.04.12-1-clusters-from-tsabc123-c1-plan.md"
        plan_file.write_text( "dummy plan content" )

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver._find_stalled_tfe_by_plan_path",
            return_value=None
        ):
            t = resolve_resume_target( str( plan_file ), "user@test.com" )

        assert t.source_type == "not_found"
        assert "no stalled TFE job" in t.diagnostic

    def test_plan_path_resolves_to_stalled_job( self, tmp_path ):
        """Happy path: plan file exists + parseable + stalled job found."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        plan_file = tmp_path / "2026.04.12-1-clusters-from-tsabc123-c1-plan.md"
        plan_file.write_text( "dummy plan content" )

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver._find_stalled_tfe_by_plan_path",
            return_value="tfe-def456::user@test.com"
        ):
            t = resolve_resume_target( str( plan_file ), "user@test.com" )

        assert t.source_type == "plan_path"
        assert t.job_id == "tfe-def456::user@test.com"
        assert t.confidence == 1.0
        assert t.matched_path == str( plan_file )


# ---------------------------------------------------------------------------
# DB query helper
# ---------------------------------------------------------------------------

class TestFindStalledTfeByPlanPath:
    """_find_stalled_tfe_by_plan_path queries job_history for a match."""

    def test_matches_exact_stored_path( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import _find_stalled_tfe_by_plan_path

        mock_row = MagicMock()
        mock_row.id_hash = "tfe-match1::user@test.com"
        mock_row.metadata_json = {
            "artifacts": { "plan_path": "io/swe-team/plans/user@test.com/2026.04.12-1-clusters-from-tsabc-c1-plan.md" }
        }

        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [ mock_row ]

        with patch( "cosa.rest.db.database.get_db" ) as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_session
            result = _find_stalled_tfe_by_plan_path(
                "io/swe-team/plans/user@test.com/2026.04.12-1-clusters-from-tsabc-c1-plan.md",
                "user@test.com"
            )

        assert result == "tfe-match1::user@test.com"

    def test_matches_by_basename_when_paths_differ( self ):
        """Absolute path input vs relative stored path — basename fallback."""
        from cosa.agents.test_fix_expediter.resume_resolver import _find_stalled_tfe_by_plan_path

        mock_row = MagicMock()
        mock_row.id_hash = "tfe-match2::user@test.com"
        mock_row.metadata_json = {
            "artifacts": { "plan_path": "io/swe-team/plans/user@test.com/2026.04.12-1-clusters-from-tsabc-c1-plan.md" }
        }

        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [ mock_row ]

        with patch( "cosa.rest.db.database.get_db" ) as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_session
            result = _find_stalled_tfe_by_plan_path(
                "/var/lupin/io/swe-team/plans/user@test.com/2026.04.12-1-clusters-from-tsabc-c1-plan.md",
                "user@test.com"
            )

        assert result == "tfe-match2::user@test.com"

    def test_returns_none_on_no_match( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import _find_stalled_tfe_by_plan_path

        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch( "cosa.rest.db.database.get_db" ) as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_session
            result = _find_stalled_tfe_by_plan_path( "io/nonexistent-plan.md", "user@test.com" )

        assert result is None

    def test_swallows_db_errors_returns_none( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import _find_stalled_tfe_by_plan_path

        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "db down" ) ):
            result = _find_stalled_tfe_by_plan_path( "io/foo.md", "user@test.com" )

        assert result is None


# ---------------------------------------------------------------------------
# Type 4: Fuzzy natural-language resolution
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    """Natural-language descriptions route to the LLM fuzzy matcher."""

    def test_no_candidates_returns_not_found( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=[]
        ):
            t = resolve_resume_target( "the stalled one from yesterday", "user@test.com" )

        assert t.source_type == "not_found"
        assert "No stalled" in t.diagnostic

    def test_high_confidence_match_auto_selects( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        candidates = [
            { "job_id": "tfe-abc::u1", "status": "stalled", "summary": "visual regression" }
        ]
        ranked = [
            { "job_id": "tfe-abc::u1", "status": "stalled", "summary": "visual regression",
              "confidence": 0.95, "reason": "top match" }
        ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ), patch(
            "cosa.agents.test_fix_expediter.resume_resolver.fuzzy_match_candidates",
            return_value=ranked
        ):
            t = resolve_resume_target( "the visual regression one", "user@test.com" )

        assert t.source_type == "fuzzy"
        assert t.job_id == "tfe-abc::u1"
        assert t.confidence >= 0.9

    def test_low_confidence_returns_candidates_for_disambiguation( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        candidates = [ { "job_id": "tfe-abc::u1", "status": "stalled" } ]
        ranked = [
            { "job_id": "tfe-abc::u1", "status": "stalled", "confidence": 0.6, "reason": "low" }
        ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ), patch(
            "cosa.agents.test_fix_expediter.resume_resolver.fuzzy_match_candidates",
            return_value=ranked
        ):
            t = resolve_resume_target( "something vague", "user@test.com" )

        assert t.source_type == "fuzzy"
        assert t.job_id is None
        assert len( t.candidates ) == 1
        assert "disambiguation required" in t.diagnostic

    def test_non_stalled_top_match_does_not_auto_resume( self ):
        """High-confidence match on a COMPLETED (not stalled) job should not auto-select."""
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target

        candidates = [ { "job_id": "tfe-abc::u1", "status": "completed" } ]
        ranked = [
            { "job_id": "tfe-abc::u1", "status": "completed", "confidence": 0.95, "reason": "..." }
        ]

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates",
            return_value=candidates
        ), patch(
            "cosa.agents.test_fix_expediter.resume_resolver.fuzzy_match_candidates",
            return_value=ranked
        ):
            t = resolve_resume_target( "the recent one", "user@test.com" )

        assert t.job_id is None
        assert t.source_type == "fuzzy"
        assert len( t.candidates ) == 1


class TestListResumeCandidates:
    """list_resume_candidates() queries + normalizes rows."""

    def test_returns_empty_on_db_error( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import list_resume_candidates

        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "down" ) ):
            result = list_resume_candidates( "user@test.com" )

        assert result == []

    def test_normalizes_row_to_candidate_dict( self ):
        from cosa.agents.test_fix_expediter.resume_resolver import _row_to_candidate_dict

        row = MagicMock()
        row.id_hash = "tfe-abc::user@test.com"
        row.status = "stalled"
        row.updated_at = None
        row.completed_at = None
        row.question_text = None
        row.metadata_json = {
            "artifacts": {
                "plan_path": "io/swe-team/plans/foo-c1-plan.md",
                "checkpoint": {
                    "stalled_at": "2026-04-12T03:14:00",
                    "state_snapshot": {
                        "clusters": [ {"cluster_id": "C1"} ],
                        "proposed_fixes": [ {"title": "fix A"}, {"title": "fix B"} ],
                    }
                }
            },
            "original_args": { "source_test_suite_job_id": "ts-src::user@test.com" }
        }

        c = _row_to_candidate_dict( row )
        assert c[ "job_id" ] == "tfe-abc::user@test.com"
        assert c[ "status" ] == "stalled"
        assert c[ "plan_path" ] == "io/swe-team/plans/foo-c1-plan.md"
        assert "1 cluster" in c[ "summary" ]
        assert "2 proposed" in c[ "summary" ]
        assert c[ "source_ts" ] == "ts-src::user@test.com"
        assert c[ "stalled_at" ] == "2026-04-12T03:14:00"
