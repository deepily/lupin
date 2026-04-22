"""
Unit tests for POST /api/test-fix-expediter/resume-from smart resume endpoint.

Session 9056c113 continued (2026-04-12). Tests the endpoint's dispatch to
resolve_resume_target() + resume_job() with mocked dependencies.
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class TestTFEResumeFromRequestModel:
    """Request body model accepts a single resume_from string."""

    def test_valid_request_parses( self ):
        from cosa.rest.routers.queues import TFEResumeFromRequest
        req = TFEResumeFromRequest( resume_from="tfe-abc::u1" )
        assert req.resume_from == "tfe-abc::u1"

    def test_missing_resume_from_raises( self ):
        from cosa.rest.routers.queues import TFEResumeFromRequest
        with pytest.raises( Exception ):
            TFEResumeFromRequest()


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------

def _make_mock_resume_target( **kwargs ):
    """Build a ResumeTarget mock with specified fields."""
    from cosa.agents.test_fix_expediter.resume_resolver import ResumeTarget
    return ResumeTarget( **kwargs )


def _make_mock_job( id_hash="tfe-resumed-001::u1", phase_ordinal=3, phase_name="proposing" ):
    """Build a reconstructed job mock with _resume_checkpoint attached."""
    job = MagicMock()
    job.id_hash = id_hash
    job._resume_checkpoint = {
        "phase_ordinal": phase_ordinal,
        "phase_name"   : phase_name,
        "resume_count" : 1,
    }
    return job


class TestResumeEndpointDispatch:
    """resume_tfe_smart endpoint dispatches to resolver + resume_job."""

    @pytest.mark.asyncio
    async def test_resume_by_job_id_returns_resumed_status( self ):
        """Successful resume with source_type=job_id."""
        from cosa.rest.routers.queues import resume_tfe_smart, TFEResumeFromRequest

        current_user = { "email": "u1@test.com" }
        mock_queue = MagicMock()

        target = _make_mock_resume_target(
            job_id="tfe-abc::u1@test.com",
            source_type="job_id",
            confidence=1.0,
        )
        job = _make_mock_job()

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
            return_value=target
        ), patch(
            "cosa.rest.agentic_job_factory.resume_job",
            return_value=job
        ):
            result = await resume_tfe_smart(
                TFEResumeFromRequest( resume_from="tfe-abc::u1@test.com" ),
                current_user=current_user,
                todo_queue=mock_queue,
            )

        assert result[ "status" ] == "resumed"
        assert result[ "source_type" ] == "job_id"
        assert result[ "resumed_job_id" ] == "tfe-resumed-001::u1"
        assert result[ "phase_name" ] == "proposing"
        mock_queue.push.assert_called_once_with( job )

    @pytest.mark.asyncio
    async def test_resume_by_plan_path( self ):
        """Plan path resolution → resume flow."""
        from cosa.rest.routers.queues import resume_tfe_smart, TFEResumeFromRequest

        current_user = { "email": "u1@test.com" }
        target = _make_mock_resume_target(
            job_id       = "tfe-from-plan::u1@test.com",
            source_type  = "plan_path",
            matched_path = "io/swe-team/plans/foo-c1-plan.md",
            confidence   = 1.0,
        )
        job = _make_mock_job( id_hash="tfe-from-plan::u1@test.com" )

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
            return_value=target
        ), patch(
            "cosa.rest.agentic_job_factory.resume_job",
            return_value=job
        ):
            result = await resume_tfe_smart(
                TFEResumeFromRequest( resume_from="io/swe-team/plans/foo-c1-plan.md" ),
                current_user=current_user,
                todo_queue=MagicMock(),
            )

        assert result[ "status" ] == "resumed"
        assert result[ "source_type" ] == "plan_path"
        assert result[ "matched_path" ] == "io/swe-team/plans/foo-c1-plan.md"

    @pytest.mark.asyncio
    async def test_resume_not_found_raises_404( self ):
        """source_type=not_found raises HTTPException 404."""
        from fastapi import HTTPException
        from cosa.rest.routers.queues import resume_tfe_smart, TFEResumeFromRequest

        target = _make_mock_resume_target(
            source_type = "not_found",
            diagnostic  = "Job xyz not found or not stalled",
        )

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
            return_value=target
        ):
            with pytest.raises( HTTPException ) as exc_info:
                await resume_tfe_smart(
                    TFEResumeFromRequest( resume_from="tfe-nonexistent" ),
                    current_user={ "email": "u1@test.com" },
                    todo_queue=MagicMock(),
                )

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_resume_ambiguous_returns_candidates_not_resumed( self ):
        """Fuzzy match with multiple candidates returns status=ambiguous."""
        from cosa.rest.routers.queues import resume_tfe_smart, TFEResumeFromRequest

        target = _make_mock_resume_target(
            source_type = "fuzzy",
            candidates  = [
                { "job_id": "tfe-a::u1", "status": "stalled", "summary": "visual" },
                { "job_id": "tfe-b::u1", "status": "stalled", "summary": "auth" },
            ],
            confidence  = 0.6,
            diagnostic  = "Multiple matches found",
        )

        mock_queue = MagicMock()

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
            return_value=target
        ):
            result = await resume_tfe_smart(
                TFEResumeFromRequest( resume_from="something vague" ),
                current_user={ "email": "u1@test.com" },
                todo_queue=mock_queue,
            )

        assert result[ "status" ] == "ambiguous"
        assert len( result[ "candidates" ] ) == 2
        # Nothing pushed to queue
        mock_queue.push.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_user_email_raises_400( self ):
        """Authenticated user without email should 400 rather than crash."""
        from fastapi import HTTPException
        from cosa.rest.routers.queues import resume_tfe_smart, TFEResumeFromRequest

        with pytest.raises( HTTPException ) as exc_info:
            await resume_tfe_smart(
                TFEResumeFromRequest( resume_from="tfe-abc" ),
                current_user={},  # no email
                todo_queue=MagicMock(),
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_resume_resolved_but_factory_returns_none_raises_404( self ):
        """Resolver found the job but resume_job() fails to reconstruct → 404."""
        from fastapi import HTTPException
        from cosa.rest.routers.queues import resume_tfe_smart, TFEResumeFromRequest

        target = _make_mock_resume_target(
            job_id      = "tfe-abc::u1@test.com",
            source_type = "job_id",
            confidence  = 1.0,
        )

        with patch(
            "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
            return_value=target
        ), patch(
            "cosa.rest.agentic_job_factory.resume_job",
            return_value=None  # factory can't reconstruct
        ):
            with pytest.raises( HTTPException ) as exc_info:
                await resume_tfe_smart(
                    TFEResumeFromRequest( resume_from="tfe-abc" ),
                    current_user={ "email": "u1@test.com" },
                    todo_queue=MagicMock(),
                )

        assert exc_info.value.status_code == 404
        assert "cannot be resumed" in exc_info.value.detail
