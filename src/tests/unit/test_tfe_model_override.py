"""
Unit tests for TFE per-invocation model overrides.

Session 85b05d1d (2026-04-12): E2E --cheap flag plumbs
lead_model_override / worker_model_override through
agentic_job_factory → TestFixExpediterJob.__init__ → _execute() where
it overrides config.lead_model / config.worker_model after from_config
loads INI defaults.

Covers the constructor accepting the overrides and the attributes being
stored for later application. Mirrors test_bfe_model_override.py.
"""

import pytest


def _make_tfe_job( lead_override=None, worker_override=None ):
    """Construct a TFE job instance with minimal required args + optional overrides."""
    from cosa.agents.test_fix_expediter.job import TestFixExpediterJob
    return TestFixExpediterJob(
        remediation_snapshot_path = "io/test-suite/fake-snapshot.json",
        source_test_suite_job_id  = "ts-fake-12345",
        user_id                   = "user1",
        user_email                = "tfe-model-override@test.com",
        session_id                = "test-session",
        lead_model_override       = lead_override,
        worker_model_override     = worker_override,
        debug                     = False,
    )


class TestTfeModelOverride:
    """Constructor accepts and stores lead_model_override / worker_model_override."""

    def test_defaults_to_none_when_not_provided( self ):
        """Omitted override kwargs default to None → use INI config."""
        tfe = _make_tfe_job()
        assert tfe.lead_model_override   is None
        assert tfe.worker_model_override is None

    def test_lead_override_stored( self ):
        """Passing lead_model_override stores the string on the instance."""
        tfe = _make_tfe_job( lead_override="claude-sonnet-4-6" )
        assert tfe.lead_model_override   == "claude-sonnet-4-6"
        assert tfe.worker_model_override is None

    def test_worker_override_stored( self ):
        """Passing worker_model_override stores the string on the instance."""
        tfe = _make_tfe_job( worker_override="claude-haiku-4-5" )
        assert tfe.lead_model_override   is None
        assert tfe.worker_model_override == "claude-haiku-4-5"

    def test_both_overrides_stored( self ):
        """Passing both overrides stores both on the instance."""
        tfe = _make_tfe_job(
            lead_override   = "claude-sonnet-4-6",
            worker_override = "claude-sonnet-4-6",
        )
        assert tfe.lead_model_override   == "claude-sonnet-4-6"
        assert tfe.worker_model_override == "claude-sonnet-4-6"

    def test_factory_wires_through_override_args( self ):
        """agentic_job_factory should pass override args from args_dict to constructor."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to test fix expediter",
            args_dict  = {
                "remediation_snapshot_path" : "io/test-suite/fake.json",
                "source_test_suite_job_id"  : "ts-fake",
                "lead_model_override"       : "claude-sonnet-4-6",
                "worker_model_override"     : "claude-sonnet-4-6",
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
            command    = "agent router go to test fix expediter",
            args_dict  = {
                "remediation_snapshot_path" : "io/test-suite/fake.json",
                "source_test_suite_job_id"  : "ts-fake",
            },
            user_id    = "user1",
            user_email = "factory-test@test.com",
            session_id = "test-session",
        )

        assert job is not None
        assert job.lead_model_override   is None
        assert job.worker_model_override is None
