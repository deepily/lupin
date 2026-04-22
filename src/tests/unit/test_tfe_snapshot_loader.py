"""
Unit tests for TFE snapshot_loader.

Session 1cfcdf73 (2026-04-10): Phase 2 scaffolding tests.
"""

import json
import os
import tempfile

import pytest

from cosa.agents.test_fix_expediter.snapshot_loader import (
    load_from_artifacts,
    load_from_path,
    SnapshotLoadError,
    _redact_failure,
)


def _valid_snapshot() -> dict:
    return {
        "schema_version" : "1.0",
        "timestamp"      : "2026.04.10-at-14:53",
        "suites_run"     : [ "e2e" ],
        "summary"        : {
            "total_passed" : 335,
            "total_failed" : 2,
            "total_errors" : 0,
            "total_skipped": 0,
            "all_passed"   : False,
        },
        "failures": [
            {
                "classname": "src.tests.e2e_ui.test_foo.TestFoo",
                "name"     : "test_bar[chromium-login]",
                "type"     : "FAILED",
                "message"  : "assert 200 == 401",
                "traceback": "Traceback\nassert 200 == 401",
                "suite"    : "e2e",
            },
            {
                "classname": "src.tests.e2e_ui.test_foo.TestFoo",
                "name"     : "test_baz",
                "type"     : "ERROR",
                "message"  : "fixture error",
                "traceback": "error in /home/rruiz/code/file.py",
                "suite"    : "e2e",
            },
        ],
    }


class TestLoadFromArtifacts:

    def _artifacts( self, snapshot ):
        return {
            "remediation_snapshot"      : snapshot,
            "remediation_snapshot_path" : "test-suite/fake-remediation.json",
        }

    def test_valid_snapshot( self ):
        ctx = load_from_artifacts(
            artifacts=self._artifacts( _valid_snapshot() ),
            source_test_suite_job_id="ts-abc12345",
            user_id="u1", user_email="t@t.com", session_id="s1",
        )
        assert ctx.source_test_suite_job_id == "ts-abc12345"
        assert len( ctx.failures ) == 2
        assert ctx.suites_run == [ "e2e" ]
        assert ctx.original_test_types == [ "e2e" ]  # fell back to suites_run

    def test_explicit_test_types_override( self ):
        ctx = load_from_artifacts(
            artifacts=self._artifacts( _valid_snapshot() ),
            source_test_suite_job_id="ts-x", user_id="u", user_email="e@e.com", session_id="s",
            original_test_types=[ "integration", "unit" ],
        )
        assert ctx.original_test_types == [ "integration", "unit" ]

    def test_schema_version_gate_rejects_2_0( self ):
        snap = _valid_snapshot()
        snap[ "schema_version" ] = "2.0"
        with pytest.raises( SnapshotLoadError, match="Unsupported schema_version" ):
            load_from_artifacts(
                artifacts=self._artifacts( snap ),
                source_test_suite_job_id="ts-x", user_id="u", user_email="e@e.com", session_id="s",
            )

    def test_missing_schema_version_rejected( self ):
        snap = _valid_snapshot()
        del snap[ "schema_version" ]
        with pytest.raises( SnapshotLoadError ):
            load_from_artifacts(
                artifacts=self._artifacts( snap ),
                source_test_suite_job_id="ts-x", user_id="u", user_email="e@e.com", session_id="s",
            )

    def test_all_passed_true_rejected( self ):
        snap = _valid_snapshot()
        snap[ "summary" ][ "all_passed" ] = True
        with pytest.raises( SnapshotLoadError, match="all_passed" ):
            load_from_artifacts(
                artifacts=self._artifacts( snap ),
                source_test_suite_job_id="ts-x", user_id="u", user_email="e@e.com", session_id="s",
            )

    def test_empty_failures_rejected( self ):
        snap = _valid_snapshot()
        snap[ "failures" ] = []
        with pytest.raises( SnapshotLoadError, match="empty" ):
            load_from_artifacts(
                artifacts=self._artifacts( snap ),
                source_test_suite_job_id="ts-x", user_id="u", user_email="e@e.com", session_id="s",
            )

    def test_snapshot_not_dict_rejected( self ):
        with pytest.raises( SnapshotLoadError, match="not a dict" ):
            load_from_artifacts(
                artifacts={ "remediation_snapshot": "not a dict", "remediation_snapshot_path": "p" },
                source_test_suite_job_id="ts-x", user_id="u", user_email="e@e.com", session_id="s",
            )


class TestPIIRedaction:

    def test_home_dir_redacted( self ):
        failure = {
            "classname": "a.b.C", "name": "test_x", "type": "FAILED",
            "message": "x", "traceback": "at /home/rruiz/code/file.py line 5",
        }
        result = _redact_failure( failure )
        assert "/home/rruiz" not in result[ "traceback" ]
        assert "~" in result[ "traceback" ]

    def test_users_dir_redacted( self ):
        failure = {
            "classname": "a.b.C", "name": "test_x", "type": "FAILED",
            "message": "x", "traceback": "at /Users/alice/code/file.py line 5",
        }
        result = _redact_failure( failure )
        assert "/Users/alice" not in result[ "traceback" ]

    def test_email_redacted( self ):
        failure = {
            "classname": "a.b.C", "name": "test_x", "type": "FAILED",
            "message": "x", "traceback": "contact admin@example.com for help",
        }
        result = _redact_failure( failure )
        assert "admin@example.com" not in result[ "traceback" ]
        assert "<email>" in result[ "traceback" ]

    def test_redaction_preserves_other_fields( self ):
        failure = {
            "classname": "a.b.C", "name": "test_x", "type": "FAILED",
            "message": "msg", "traceback": "at /home/user/x",
        }
        result = _redact_failure( failure )
        assert result[ "classname" ] == "a.b.C"
        assert result[ "name" ] == "test_x"
        assert result[ "type" ] == "FAILED"
        assert result[ "message" ] == "msg"


class TestLoadFromPath:

    def test_load_from_absolute_path( self ):
        with tempfile.NamedTemporaryFile( mode="w", suffix=".json", delete=False ) as f:
            json.dump( _valid_snapshot(), f )
            tmp_path = f.name
        try:
            ctx = load_from_path(
                snapshot_path = tmp_path,
                source_test_suite_job_id="ts-abc", user_id="u", user_email="e@e.com", session_id="s",
            )
            assert len( ctx.failures ) == 2
        finally:
            os.unlink( tmp_path )

    def test_load_from_path_missing_file( self ):
        with pytest.raises( SnapshotLoadError, match="not found" ):
            load_from_path(
                snapshot_path = "/nonexistent/path/file.json",
                source_test_suite_job_id="ts", user_id="u", user_email="e@e.com", session_id="s",
            )

    def test_load_from_path_invalid_json( self ):
        with tempfile.NamedTemporaryFile( mode="w", suffix=".json", delete=False ) as f:
            f.write( "not valid json {" )
            tmp_path = f.name
        try:
            with pytest.raises( SnapshotLoadError, match="Invalid JSON" ):
                load_from_path(
                    snapshot_path = tmp_path,
                    source_test_suite_job_id="ts", user_id="u", user_email="e@e.com", session_id="s",
                )
        finally:
            os.unlink( tmp_path )
