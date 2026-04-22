"""
Unit tests for BFE per-invocation model overrides.

Session 85b05d1d (2026-04-12): E2E --cheap flag plumbs
lead_model_override / worker_model_override through
agentic_job_factory → BugFixExpediterJob.__init__ → _execute() where
it overrides config.lead_model / config.worker_model after from_config
loads INI defaults.

Covers the constructor accepting the overrides and the attributes being
stored for later application. The actual config.lead_model = override
assignment in _execute() is exercised indirectly via the orchestrator
invocation (any config field read after that line uses the overridden
value).
"""

import pytest


def _make_bfe_job( lead_override=None, worker_override=None, thinking_effort=None ):
    """Construct a BFE job instance with minimal required args + optional overrides."""
    from cosa.agents.bug_fix_expediter.job import BugFixExpediterJob
    return BugFixExpediterJob(
        dead_job_id           = "dr-abc12345::user1",
        user_id               = "user1",
        user_email            = "bfe-model-override@test.com",
        session_id            = "test-session",
        lead_model_override   = lead_override,
        worker_model_override = worker_override,
        thinking_effort       = thinking_effort,
        debug                 = False,
    )


class TestBfeThinkingEffort:
    """Constructor accepts and stores thinking_effort. Factory + config plumb it through."""

    def test_default_is_none( self ):
        bfe = _make_bfe_job()
        assert bfe.thinking_effort is None

    def test_thinking_effort_stored( self ):
        bfe = _make_bfe_job( thinking_effort="high" )
        assert bfe.thinking_effort == "high"

    def test_factory_wires_thinking_effort( self ):
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to bug fix expediter",
            args_dict  = {
                "dead_job_id"     : "dr-abc12345::user1",
                "thinking_effort" : "xhigh",
            },
            user_id    = "user1",
            user_email = "factory-test@test.com",
            session_id = "test-session",
        )
        assert job is not None
        assert job.thinking_effort == "xhigh"

    def test_config_exposes_thinking_effort( self ):
        from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig
        c = BugFixExpediterConfig()
        assert hasattr( c, "thinking_effort" )
        assert c.thinking_effort is None
        c.thinking_effort = "high"
        assert c.thinking_effort == "high"


class TestBfeModelOverride:
    """Constructor accepts and stores lead_model_override / worker_model_override."""

    def test_defaults_to_none_when_not_provided( self ):
        """Omitted override kwargs default to None → use INI config."""
        bfe = _make_bfe_job()
        assert bfe.lead_model_override   is None
        assert bfe.worker_model_override is None

    def test_lead_override_stored( self ):
        """Passing lead_model_override stores the string on the instance."""
        bfe = _make_bfe_job( lead_override="claude-sonnet-4-6" )
        assert bfe.lead_model_override   == "claude-sonnet-4-6"
        assert bfe.worker_model_override is None

    def test_worker_override_stored( self ):
        """Passing worker_model_override stores the string on the instance."""
        bfe = _make_bfe_job( worker_override="claude-haiku-4-5" )
        assert bfe.lead_model_override   is None
        assert bfe.worker_model_override == "claude-haiku-4-5"

    def test_both_overrides_stored( self ):
        """Passing both overrides stores both on the instance."""
        bfe = _make_bfe_job(
            lead_override   = "claude-sonnet-4-6",
            worker_override = "claude-sonnet-4-6",
        )
        assert bfe.lead_model_override   == "claude-sonnet-4-6"
        assert bfe.worker_model_override == "claude-sonnet-4-6"

    def test_factory_wires_through_override_args( self ):
        """agentic_job_factory should pass override args from args_dict to constructor."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to bug fix expediter",
            args_dict  = {
                "dead_job_id"           : "dr-fake::user1",
                "lead_model_override"   : "claude-sonnet-4-6",
                "worker_model_override" : "claude-sonnet-4-6",
            },
            user_id    = "user1",
            user_email = "factory-test@test.com",
            session_id = "test-session",
        )

        assert job is not None
        assert job.lead_model_override   == "claude-sonnet-4-6"
        assert job.worker_model_override == "claude-sonnet-4-6"

    def test_factory_leaves_overrides_none_when_absent( self ):
        """args_dict without override keys → overrides are None on the job."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to bug fix expediter",
            args_dict  = { "dead_job_id": "dr-fake::user1" },
            user_id    = "user1",
            user_email = "factory-test@test.com",
            session_id = "test-session",
        )

        assert job is not None
        assert job.lead_model_override   is None
        assert job.worker_model_override is None
