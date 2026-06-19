#!/usr/bin/env python3
"""
Unit tests for cosa.agents.test_fix_expediter.snapshot_loader

Targets: load_from_path, load_from_artifacts, _validate_and_build, _redact_failure.
The filesystem boundary (open / os.path.exists / cu.get_project_root) is mocked
— no real file is read. The built TestRemediationContext is the real Pydantic
model (pure in-package data). NO network / disk writes.

quick_smoke_test + __main__ are coverage-excluded by repo config.

Created 2026-05-31 by Clayton 😎 (CoSA coverage campaign, agents Tier-2, TFE lane).
"""

import json
from unittest.mock import patch, mock_open

import pytest

import cosa.agents.test_fix_expediter.snapshot_loader as sl
from cosa.agents.test_fix_expediter.snapshot_loader import (
    load_from_path,
    load_from_artifacts,
    SnapshotLoadError,
    REQUIRED_SCHEMA_VERSION,
)


def _valid_snapshot():
    return {
        "schema_version": "1.0",
        "suites_run"    : [ "e2e" ],
        "summary"       : { "total_failed": 2, "all_passed": False },
        "failures": [
            { "name": "test_bar", "traceback": "Traceback from /home/rruiz/code/file.py\nassert 200 == 401" },
            { "name": "test_baz", "traceback": "contact admin@test.com for help" },
        ],
    }


def _args( **over ):
    base = dict(
        source_test_suite_job_id="ts-abc12345", user_id="u1",
        user_email="user@test.com", session_id="s1",
    )
    base.update( over )
    return base


# ----------------------------------------------------------------------------
# load_from_artifacts
# ----------------------------------------------------------------------------
class TestLoadFromArtifacts:
    """
    load_from_artifacts pulls the in-memory snapshot from a job's artifacts dict.

    Ensures non-dict snapshot raises, the snapshot_path default ("unknown") is
    used when absent, and a valid snapshot builds a full context.
    """

    def test_non_dict_snapshot_raises( self ):
        with pytest.raises( SnapshotLoadError, match="not a dict" ):
            load_from_artifacts( artifacts={ "remediation_snapshot": [ "oops" ] }, **_args() )

    def test_valid_builds_context_and_redacts( self ):
        ctx = load_from_artifacts(
            artifacts={ "remediation_snapshot": _valid_snapshot(),
                        "remediation_snapshot_path": "test-suite/x.json" },
            **_args(),
        )
        assert ctx.source_test_suite_job_id == "ts-abc12345"
        assert len( ctx.failures ) == 2
        assert ctx.suites_run == [ "e2e" ]
        assert ctx.original_test_types == [ "e2e" ]          # fell back to suites_run
        # PII redaction applied
        assert "~" in ctx.failures[ 0 ][ "traceback" ]
        assert "<email>" in ctx.failures[ 1 ][ "traceback" ]

    def test_missing_path_defaults_to_unknown( self ):
        ctx = load_from_artifacts( artifacts={ "remediation_snapshot": _valid_snapshot() }, **_args() )
        assert ctx.snapshot_path == "unknown"


# ----------------------------------------------------------------------------
# _validate_and_build branches (exercised via load_from_artifacts)
# ----------------------------------------------------------------------------
class TestValidateAndBuild:
    """
    _validate_and_build schema/summary/failures gates + suites_run/test_types logic.

    Ensures: wrong schema_version; missing/malformed summary; all_passed True;
    malformed/empty failures; non-list suites_run coerced to []; and explicit
    original_test_types overriding the suites_run fallback.
    """

    def _load( self, snapshot, **over ):
        return load_from_artifacts(
            artifacts={ "remediation_snapshot": snapshot, "remediation_snapshot_path": "p" },
            **_args( **over ),
        )

    def test_wrong_schema_version( self ):
        snap = _valid_snapshot(); snap[ "schema_version" ] = "2.0"
        with pytest.raises( SnapshotLoadError, match="Unsupported schema_version" ):
            self._load( snap )

    def test_missing_summary( self ):
        snap = _valid_snapshot(); snap[ "summary" ] = "not-a-dict"
        with pytest.raises( SnapshotLoadError, match="missing or malformed 'summary'" ):
            self._load( snap )

    def test_all_passed_true_rejected( self ):
        snap = _valid_snapshot(); snap[ "summary" ] = { "all_passed": True }
        with pytest.raises( SnapshotLoadError, match="all_passed is True" ):
            self._load( snap )

    def test_all_passed_defaults_true_when_absent( self ):
        # summary.get("all_passed", True) -> default True -> rejected
        snap = _valid_snapshot(); snap[ "summary" ] = { "total_failed": 1 }
        with pytest.raises( SnapshotLoadError, match="all_passed is True" ):
            self._load( snap )

    def test_malformed_failures_field( self ):
        snap = _valid_snapshot(); snap[ "failures" ] = "not-a-list"
        with pytest.raises( SnapshotLoadError, match="missing or malformed 'failures'" ):
            self._load( snap )

    def test_empty_failures_rejected( self ):
        snap = _valid_snapshot(); snap[ "failures" ] = []
        with pytest.raises( SnapshotLoadError, match="empty" ):
            self._load( snap )

    def test_non_list_suites_run_coerced_to_empty( self ):
        snap = _valid_snapshot(); snap[ "suites_run" ] = "e2e"   # not a list
        # original_test_types absent -> falls back to (now empty) suites_run
        ctx = self._load( snap )
        assert ctx.suites_run == []
        assert ctx.original_test_types == []

    def test_explicit_test_types_override_suites_run( self ):
        ctx = self._load( _valid_snapshot(), original_test_types=[ "e2e", "integration" ] )
        assert ctx.original_test_types == [ "e2e", "integration" ]

    def test_missing_suites_run_key_defaults_empty_list( self ):
        snap = _valid_snapshot(); del snap[ "suites_run" ]
        ctx = self._load( snap )
        assert ctx.suites_run == []


# ----------------------------------------------------------------------------
# _redact_failure
# ----------------------------------------------------------------------------
class TestRedactFailure:
    """
    _redact_failure strips home dirs + emails; leaves missing/empty tracebacks alone.
    """

    def test_redacts_home_users_and_email( self ):
        f = {
            "name": "t",
            "traceback": "at /home/rruiz/x.py and /Users/bob/y.py, mail jane@corp.io",
        }
        out = sl._redact_failure( f )
        assert "/home/rruiz" not in out[ "traceback" ]
        assert "/Users/bob" not in out[ "traceback" ]
        assert "~" in out[ "traceback" ]
        assert "<email>" in out[ "traceback" ]
        assert f[ "traceback" ].startswith( "at /home/rruiz" )   # original untouched (copy)

    def test_no_traceback_key_is_passthrough( self ):
        out = sl._redact_failure( { "name": "t" } )
        assert out == { "name": "t" }

    def test_empty_traceback_unchanged( self ):
        out = sl._redact_failure( { "name": "t", "traceback": "" } )
        assert out[ "traceback" ] == ""


# ----------------------------------------------------------------------------
# load_from_path (filesystem-mocked)
# ----------------------------------------------------------------------------
class TestLoadFromPath:
    """
    load_from_path path resolution + file IO with the filesystem mocked.

    Ensures: absolute path used as-is; relative "io/"-prefixed vs bare-relative
    resolution against project root; missing file raises; invalid JSON raises;
    a valid file builds a context.
    """

    def _open_with( self, snapshot ):
        return mock_open( read_data=json.dumps( snapshot ) )

    def test_absolute_path_used_directly( self ):
        with patch( "os.path.exists", return_value=True ), \
             patch( "builtins.open", self._open_with( _valid_snapshot() ) ):
            ctx = load_from_path( snapshot_path="/abs/snap.json", **_args() )
        assert ctx.snapshot_path == "/abs/snap.json"

    def test_relative_io_prefixed_resolves_under_root( self ):
        captured = {}
        m = self._open_with( _valid_snapshot() )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", side_effect=lambda p: captured.setdefault( "p", p ) or True ), \
             patch( "builtins.open", m ):
            load_from_path( snapshot_path="io/test-suite/x.json", **_args() )
        assert captured[ "p" ] == "/proj/io/test-suite/x.json"

    def test_relative_bare_resolves_under_io( self ):
        captured = {}
        m = self._open_with( _valid_snapshot() )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", side_effect=lambda p: captured.setdefault( "p", p ) or True ), \
             patch( "builtins.open", m ):
            load_from_path( snapshot_path="test-suite/x.json", **_args() )
        assert captured[ "p" ] == "/proj/io/test-suite/x.json"

    def test_missing_file_raises( self ):
        with patch( "os.path.exists", return_value=False ):
            with pytest.raises( SnapshotLoadError, match="snapshot not found" ):
                load_from_path( snapshot_path="/abs/missing.json", **_args() )

    def test_invalid_json_raises( self ):
        with patch( "os.path.exists", return_value=True ), \
             patch( "builtins.open", mock_open( read_data="{not valid json" ) ):
            with pytest.raises( SnapshotLoadError, match="Invalid JSON" ):
                load_from_path( snapshot_path="/abs/bad.json", **_args() )

    def test_valid_file_builds_context( self ):
        with patch( "os.path.exists", return_value=True ), \
             patch( "builtins.open", self._open_with( _valid_snapshot() ) ):
            ctx = load_from_path( snapshot_path="/abs/snap.json", original_pytest_args=[ "-k", "auth" ], **_args() )
        assert len( ctx.failures ) == 2
        assert ctx.original_pytest_args == [ "-k", "auth" ]


def test_required_schema_version_constant():
    """The module pins the supported schema version at 1.0."""
    assert REQUIRED_SCHEMA_VERSION == "1.0"
