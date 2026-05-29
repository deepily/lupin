"""
Remediation snapshot loader for the TestFixExpediter.

Parses the JSON remediation snapshot produced by a failed TestSuiteJob and
hydrates a `TestRemediationContext` for downstream phases. Validates the
schema version, checks for non-empty failures, and strips PII from tracebacks.

See:
  - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/06-phase3-fix-delegation-plan.md
  - src/cosa/agents/test_suite/job.py (produces the snapshot)
"""

import json
import os
import re
from typing import Optional

import cosa.utils.util as cu

from cosa.agents.test_fix_expediter.state import TestRemediationContext


class SnapshotLoadError( Exception ):
    """Raised when a remediation snapshot fails schema or structural validation."""
    pass


REQUIRED_SCHEMA_VERSION = "1.0"


def load_from_path(
    snapshot_path: str,
    source_test_suite_job_id: str,
    user_id: str,
    user_email: str,
    session_id: str,
    original_test_types: Optional[ list ] = None,
    original_pytest_args: Optional[ list ] = None,
) -> TestRemediationContext:
    """
    Load a remediation snapshot from a file path.

    Requires:
        - snapshot_path is a relative path (under io/) or absolute path
        - source_test_suite_job_id, user_id, user_email, session_id are non-empty
        - The file exists and contains valid JSON with schema_version "1.0"

    Ensures:
        - Returns TestRemediationContext populated from the snapshot
        - Raises SnapshotLoadError on any validation failure

    Args:
        snapshot_path: Path to the remediation JSON (relative to io/ or absolute)
        source_test_suite_job_id: ID of the TestSuiteJob that produced this snapshot
        user_id: User ID for downstream plan doc + WS routing
        user_email: User email for PlanWriter partitioning
        session_id: WebSocket session ID
        original_test_types: Suites the original job ran (for Phase 6 rerun)
        original_pytest_args: Original pytest args (for Phase 6 rerun)

    Returns:
        TestRemediationContext: Validated context for downstream phases
    """
    # Resolve path
    if os.path.isabs( snapshot_path ):
        abs_path = snapshot_path
    else:
        project_root = cu.get_project_root()
        # Accept both "io/test-suite/..." and "test-suite/..." relative forms
        if snapshot_path.startswith( "io/" ):
            abs_path = os.path.join( project_root, snapshot_path )
        else:
            abs_path = os.path.join( project_root, "io", snapshot_path )

    if not os.path.exists( abs_path ):
        raise SnapshotLoadError( f"Remediation snapshot not found: {abs_path}" )

    try:
        with open( abs_path, "r" ) as f:
            snapshot = json.load( f )
    except json.JSONDecodeError as e:
        raise SnapshotLoadError( f"Invalid JSON in snapshot {abs_path}: {e}" )

    return _validate_and_build(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        source_test_suite_job_id=source_test_suite_job_id,
        user_id=user_id,
        user_email=user_email,
        session_id=session_id,
        original_test_types=original_test_types,
        original_pytest_args=original_pytest_args,
    )


def load_from_artifacts(
    artifacts: dict,
    source_test_suite_job_id: str,
    user_id: str,
    user_email: str,
    session_id: str,
    original_test_types: Optional[ list ] = None,
    original_pytest_args: Optional[ list ] = None,
) -> TestRemediationContext:
    """
    Load a remediation snapshot directly from a TestSuiteJob's artifacts dict.

    The watchdog path uses this — artifacts["remediation_snapshot"] is the
    in-memory parsed JSON (no file read needed).

    Requires:
        - artifacts has "remediation_snapshot" (dict) and "remediation_snapshot_path"

    Ensures:
        - Same as load_from_path
    """
    snapshot = artifacts.get( "remediation_snapshot" )
    if not isinstance( snapshot, dict ):
        raise SnapshotLoadError(
            f"artifacts['remediation_snapshot'] is not a dict (got {type( snapshot ).__name__})"
        )

    snapshot_path = artifacts.get( "remediation_snapshot_path", "unknown" )

    return _validate_and_build(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        source_test_suite_job_id=source_test_suite_job_id,
        user_id=user_id,
        user_email=user_email,
        session_id=session_id,
        original_test_types=original_test_types,
        original_pytest_args=original_pytest_args,
    )


def _validate_and_build(
    snapshot: dict,
    snapshot_path: str,
    source_test_suite_job_id: str,
    user_id: str,
    user_email: str,
    session_id: str,
    original_test_types: Optional[ list ],
    original_pytest_args: Optional[ list ],
) -> TestRemediationContext:
    """Internal: validate snapshot shape and build TestRemediationContext."""

    # Schema version gate
    version = snapshot.get( "schema_version" )
    if version != REQUIRED_SCHEMA_VERSION:
        raise SnapshotLoadError(
            f"Unsupported schema_version '{version}' (expected '{REQUIRED_SCHEMA_VERSION}')"
        )

    # Summary must exist and indicate failure
    summary = snapshot.get( "summary" )
    if not isinstance( summary, dict ):
        raise SnapshotLoadError( "snapshot missing or malformed 'summary' field" )

    if summary.get( "all_passed", True ):
        raise SnapshotLoadError(
            "snapshot.summary.all_passed is True — nothing to remediate"
        )

    # Failures list must be non-empty
    failures = snapshot.get( "failures" )
    if not isinstance( failures, list ):
        raise SnapshotLoadError( "snapshot missing or malformed 'failures' field" )
    if len( failures ) == 0:
        raise SnapshotLoadError( "snapshot.failures is empty — nothing to remediate" )

    # Suites run
    suites_run = snapshot.get( "suites_run", [] )
    if not isinstance( suites_run, list ):
        suites_run = []

    # Determine original_test_types: prefer explicit arg, else fall back to suites_run
    effective_test_types = original_test_types if original_test_types else suites_run

    # Redact PII from tracebacks (absolute paths outside the project root)
    sanitized_failures = [ _redact_failure( f ) for f in failures ]

    return TestRemediationContext(
        source_test_suite_job_id = source_test_suite_job_id,
        snapshot_path            = snapshot_path,
        snapshot                 = snapshot,
        suites_run               = suites_run,
        summary                  = summary,
        failures                 = sanitized_failures,
        original_test_types      = effective_test_types,
        original_pytest_args     = original_pytest_args or [],
        user_id                  = user_id,
        user_email               = user_email,
        session_id               = session_id,
    )


def _redact_failure( failure: dict ) -> dict:
    """
    Return a copy of the failure record with traceback PII stripped.

    Redaction rules:
        - Absolute paths to the user's home directory → "~"
        - Paths containing "/Users/{name}" or "/home/{name}" → "~"
        - Email addresses → "<email>"
    """
    out = dict( failure )
    traceback = out.get( "traceback", "" )
    if traceback:
        # Strip home dirs
        traceback = re.sub( r"/home/[^/\s]+", "~", traceback )
        traceback = re.sub( r"/Users/[^/\s]+", "~", traceback )
        # Strip emails
        traceback = re.sub(
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            "<email>",
            traceback,
        )
        out[ "traceback" ] = traceback
    return out


def quick_smoke_test():
    """Quick smoke test for snapshot_loader."""
    import tempfile

    cu.print_banner( "TFE Snapshot Loader Smoke Test", prepend_nl=True )

    try:
        # 1: Build a valid snapshot dict and load it
        valid_snapshot = {
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
                    "traceback": "Traceback from /home/rruiz/code/file.py\nassert 200 == 401",
                    "suite"    : "e2e",
                },
                {
                    "classname": "src.tests.e2e_ui.test_foo.TestFoo",
                    "name"     : "test_baz[chromium-register]",
                    "type"     : "FAILED",
                    "message"  : "assert 200 == 401",
                    "traceback": "contact admin@test.com for help",
                    "suite"    : "e2e",
                },
            ],
        }

        ctx = load_from_artifacts(
            artifacts = {
                "remediation_snapshot"      : valid_snapshot,
                "remediation_snapshot_path" : "test-suite/2026.04.10-at-14:53-e2e-remediation.json",
            },
            source_test_suite_job_id = "ts-abc12345",
            user_id                  = "u1",
            user_email               = "user@test.com",
            session_id               = "s1",
        )

        assert ctx.source_test_suite_job_id == "ts-abc12345"
        assert len( ctx.failures ) == 2
        assert ctx.summary[ "all_passed" ] == False
        assert ctx.suites_run == [ "e2e" ]
        assert ctx.original_test_types == [ "e2e" ]  # fell back to suites_run
        print( "✓ load_from_artifacts with valid snapshot" )

        # 2: PII redaction
        assert "~" in ctx.failures[ 0 ][ "traceback" ], "home dir should be redacted"
        assert "<email>" in ctx.failures[ 1 ][ "traceback" ], "email should be redacted"
        print( "✓ PII redaction works (home dirs + emails)" )

        # 3: Schema version gate
        bad_schema = dict( valid_snapshot )
        bad_schema[ "schema_version" ] = "2.0"
        try:
            load_from_artifacts(
                artifacts = { "remediation_snapshot": bad_schema, "remediation_snapshot_path": "p" },
                source_test_suite_job_id="ts-test", user_id="u", user_email="e@e.com", session_id="s",
            )
            assert False, "Should have raised SnapshotLoadError"
        except SnapshotLoadError as e:
            assert "Unsupported schema_version" in str( e )
        print( "✓ Schema version gate rejects 2.0" )

        # 4: all_passed=True is rejected
        passed_snapshot = dict( valid_snapshot )
        passed_snapshot[ "summary" ] = { "all_passed": True }
        try:
            load_from_artifacts(
                artifacts = { "remediation_snapshot": passed_snapshot, "remediation_snapshot_path": "p" },
                source_test_suite_job_id="ts-test", user_id="u", user_email="e@e.com", session_id="s",
            )
            assert False, "Should have raised"
        except SnapshotLoadError as e:
            assert "all_passed" in str( e )
        print( "✓ all_passed=True rejected" )

        # 5: Empty failures list rejected
        empty_snapshot = dict( valid_snapshot )
        empty_snapshot[ "failures" ] = []
        try:
            load_from_artifacts(
                artifacts = { "remediation_snapshot": empty_snapshot, "remediation_snapshot_path": "p" },
                source_test_suite_job_id="ts-test", user_id="u", user_email="e@e.com", session_id="s",
            )
            assert False, "Should have raised"
        except SnapshotLoadError as e:
            assert "empty" in str( e )
        print( "✓ Empty failures list rejected" )

        # 6: load_from_path (write then read)
        with tempfile.NamedTemporaryFile( mode="w", suffix=".json", delete=False ) as tmpf:
            json.dump( valid_snapshot, tmpf )
            tmp_path = tmpf.name
        try:
            ctx2 = load_from_path(
                snapshot_path = tmp_path,
                source_test_suite_job_id="ts-xyz", user_id="u", user_email="e@e.com", session_id="s",
                original_test_types=[ "e2e", "integration" ],
            )
            assert ctx2.original_test_types == [ "e2e", "integration" ]  # explicit override
            print( "✓ load_from_path with explicit original_test_types override" )
        finally:
            os.unlink( tmp_path )

        print( "\n✓ TFE Snapshot Loader smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback as tb
        tb.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
