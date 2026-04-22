"""
Unit tests for TestFixExpediterJob.

Session 1cfcdf73 (2026-04-10): Phase 2 scaffolding tests.
"""

import pytest

from cosa.agents.test_fix_expediter.job import TestFixExpediterJob


class TestJobConstants:

    def test_job_type( self ):
        assert TestFixExpediterJob.JOB_TYPE == "test_fix_expediter"

    def test_job_prefix( self ):
        assert TestFixExpediterJob.JOB_PREFIX == "tfe"


class TestJobConstruction:

    def _make_job( self, **overrides ):
        kwargs = dict(
            remediation_snapshot_path = "test-suite/fake.json",
            source_test_suite_job_id  = "ts-abc12345",
            user_id                   = "u1",
            user_email                = "t@t.com",
            session_id                = "s1",
            dry_run                   = True,
        )
        kwargs.update( overrides )
        return TestFixExpediterJob( **kwargs )

    def test_minimal_construction( self ):
        job = self._make_job()
        assert job.remediation_snapshot_path == "test-suite/fake.json"
        assert job.source_test_suite_job_id == "ts-abc12345"
        assert job.dry_run is True
        assert job.remediation_context is None
        assert job.orchestrator is None
        assert job.original_test_types == []
        assert job.original_pytest_args == []

    def test_id_hash_has_tfe_prefix( self ):
        job = self._make_job()
        assert job.id_hash.startswith( "tfe-" ), f"Expected tfe- prefix, got {job.id_hash}"

    def test_original_test_types_passthrough( self ):
        job = self._make_job( original_test_types=[ "e2e", "integration" ] )
        assert job.original_test_types == [ "e2e", "integration" ]

    def test_last_question_asked_includes_source_job( self ):
        job = self._make_job()
        q = job.last_question_asked
        assert "ts-abc12345" in q
        assert isinstance( q, str )


class TestFactoryRouting:

    def test_create_agentic_job_routes_to_tfe( self ):
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command="agent router go to test fix expediter",
            args_dict={
                "remediation_snapshot_path": "test-suite/fake.json",
                "source_test_suite_job_id": "ts-xyz99999",
                "dry_run": "true",
            },
            user_id="u1", user_email="t@t.com", session_id="s1",
            debug=False, verbose=False,
        )

        assert job is not None, "Factory returned None for TFE command"
        assert isinstance( job, TestFixExpediterJob )
        assert job.remediation_snapshot_path == "test-suite/fake.json"
        assert job.source_test_suite_job_id == "ts-xyz99999"
        assert job.dry_run is True

    def test_factory_parses_comma_separated_test_types( self ):
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command="agent router go to test fix expediter",
            args_dict={
                "remediation_snapshot_path": "p.json",
                "source_test_suite_job_id": "ts-x",
                "original_test_types": "e2e,integration,unit",
                "dry_run": "true",
            },
            user_id="u1", user_email="t@t.com", session_id="s1",
            debug=False, verbose=False,
        )
        assert job.original_test_types == [ "e2e", "integration", "unit" ]

    def test_factory_accepts_list_test_types( self ):
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command="agent router go to test fix expediter",
            args_dict={
                "remediation_snapshot_path": "p.json",
                "source_test_suite_job_id": "ts-x",
                "original_test_types": [ "e2e" ],   # already list, passes through
            },
            user_id="u1", user_email="t@t.com", session_id="s1",
            debug=False, verbose=False,
        )
        assert job.original_test_types == [ "e2e" ]
