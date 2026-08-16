"""
Unit tests for the TFE RESUME factory branch (design §4/§5.5 phase 3).

`create_agentic_job("agent router go to test fix expediter resume", …)` mirrors
POST /api/test-fix-expediter/resume-from (queues.py:1857): resolve the
expeditor-matched `resume_from` to a single stalled job, then rebuild via
`resume_job()`. No single match (not-found / still-ambiguous) → return None, so the
voice flow routes to the receptionist to speak the failure.

Tier: :7999-eligible unit (resolver + resume_job mocked; no server, no DB).
"""

from types import SimpleNamespace
from unittest.mock import patch

from cosa.rest.agentic_job_factory import create_agentic_job

_RESUME = "agent router go to test fix expediter resume"


def _call( resume_from="tfe-123", extra=None ):
    args = { "resume_from": resume_from }
    if extra:
        args.update( extra )
    return create_agentic_job(
        command    = _RESUME,
        args_dict  = args,
        user_id    = "uid-1",
        user_email = "test@lupin",
        session_id = "sess-1",
    )


class TestTfeResumeFactoryBranch:
    """The voice resume dispatch — single-match resumes, no-match returns None."""

    def test_single_match_returns_the_resumed_job( self ):
        sentinel = object()
        with patch( "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
                    return_value=SimpleNamespace( job_id="tfe-123" ) ) as m_resolve, \
             patch( "cosa.rest.agentic_job_factory.resume_job",
                    return_value=sentinel ) as m_resume:
            out = _call( extra={ "thinking_effort": "high" } )   # non-empty overrides path
        assert out is sentinel
        m_resolve.assert_called_once()
        assert m_resume.call_args.kwargs[ "args_overrides" ] == { "thinking_effort": "high" }

    def test_no_single_match_returns_none_without_resuming( self ):
        with patch( "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
                    return_value=SimpleNamespace( job_id=None ) ), \
             patch( "cosa.rest.agentic_job_factory.resume_job" ) as m_resume:
            out = _call()
        assert out is None
        m_resume.assert_not_called()
