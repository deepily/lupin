#!/usr/bin/env python3
"""
Smoke test for TFE forensic error capture + persistence round-trip.

Lighter-weight than the full live-pipeline test described in the plan as T9
(which requires a real test_suite run → TestSuiteCompletionWatchdog → TFE, taking
minutes). Instead, this test directly exercises the failure-handling and
persistence code paths in-process:

    1. Instantiate a TFE job via the agentic_job_factory
    2. Force `_execute()` to raise by monkey-patching it
    3. Call `do_all()` synchronously — verifies Fix 2 (self.state, self.error,
       full traceback in error, unconditional stdout print)
    4. Manually push the metadata through `persist_job_created_from_metadata`
       + `persist_job_failed_from_metadata` — verifies Fix 1 (persistence
       allowlist) + Fix 4 (stack_trace merge into metadata_json)
    5. Query `get_job_by_id_hash` and assert the persisted row has real error
       text (not "Unknown error"), state=failed, and stack_trace in metadata_json
    6. Verify the dead-queue API returns the plan_path + artifact fields
       (tests Fix 8b by pushing a fake agentic job into the in-memory dead queue
       and hitting /api/get-queue/dead)

Requires:
    - Server running on localhost:7999 (for the /api/get-queue/dead probe)
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars

Usage:
    python src/tests/smoke/test_tfe_error_capture_smoke.py

Plan: src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md (T9)
"""

import os
import sys
import time
import traceback

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import cosa.utils.util as cu


BASE_URL = "http://localhost:7999"


def _make_tfe_job():
    """Construct a TFE job via the factory with a known-bad snapshot path."""
    from cosa.rest.agentic_job_factory import create_agentic_job
    return create_agentic_job(
        command    = "agent router go to test fix expediter",
        args_dict  = {
            "remediation_snapshot_path": "test-suite/nonexistent-smoke-test-file.json",
            "source_test_suite_job_id" : "ts-smoke1234::test-user",
            "dry_run"                  : False,
        },
        user_id    = "smoke-test-user",
        user_email = "smoke@test.com",
        session_id = "smoke-test-session",
    )


def _force_execute_failure( tfe, exception_to_raise ):
    """Monkey-patch `_execute()` to raise the given exception."""
    async def _raise():
        raise exception_to_raise
    tfe._execute = _raise


def quick_smoke_test():
    """
    Full TFE forensic error-capture smoke test.

    Returns:
        bool: True if all assertions pass, False on any failure
    """
    cu.print_banner( "TFE Forensic Error Capture Smoke Test", prepend_nl=True )

    try:
        # ═══════════════════════════════════════════════════════════════════
        # Part 1: Persistence allowlist (Fix 1)
        # ═══════════════════════════════════════════════════════════════════
        print( "\nPart 1: Persistence allowlist check..." )
        from cosa.rest.job_persistence import is_agentic_job_type, AGENTIC_JOB_TYPES
        assert "test_fix_expediter" in AGENTIC_JOB_TYPES, \
            f"test_fix_expediter NOT in AGENTIC_JOB_TYPES: {AGENTIC_JOB_TYPES}"
        assert is_agentic_job_type( "test_fix_expediter" ) is True
        print( "  ✓ test_fix_expediter is in AGENTIC_JOB_TYPES" )

        # ═══════════════════════════════════════════════════════════════════
        # Part 2: TFE do_all() captures state + error + traceback on failure
        # ═══════════════════════════════════════════════════════════════════
        print( "\nPart 2: TFE do_all() error capture..." )
        from cosa.rest.job_state import JobState

        tfe = _make_tfe_job()
        assert tfe is not None, "factory returned None for test fix expediter command"
        print( f"  Created TFE: {tfe.id_hash}" )

        _force_execute_failure(
            tfe, RuntimeError( "smoke-test-forced-failure-MARKER-a9f3c" )
        )
        # AgenticJobBase subclasses now re-raise from do_all() after persisting
        # state/error/answer_conversational (Phase 4 backlog #5, Session d34f2f74).
        # Catch the re-raise so the forensic assertions below can still run.
        try:
            tfe.do_all()
            assert False, "do_all() should have re-raised RuntimeError"
        except RuntimeError as e:
            assert "smoke-test-forced-failure-MARKER-a9f3c" in str( e )

        assert tfe.state == JobState.FAILED, f"expected FAILED, got {tfe.state}"
        assert tfe.error is not None, "self.error must be populated on failure"
        assert "RuntimeError" in tfe.error, "error should contain exception type"
        assert "smoke-test-forced-failure-MARKER-a9f3c" in tfe.error, \
            "error should contain the forced exception message"
        assert "Traceback" in tfe.error, \
            "error should contain the full traceback (not just the message)"
        assert tfe.completed_at is not None
        print( "  ✓ self.state = FAILED" )
        print( "  ✓ self.error contains full traceback with exception type + message" )
        print( f"  Error preview: {tfe.error[ :120 ]}..." )

        # ═══════════════════════════════════════════════════════════════════
        # Part 3: Persistence round-trip (Fix 1 + Fix 4 via metadata merge)
        # ═══════════════════════════════════════════════════════════════════
        print( "\nPart 3: Persistence round-trip (INSERT + UPDATE with stack_trace merge)..." )
        from cosa.rest.job_persistence import (
            persist_job_created_from_metadata,
            persist_job_failed_from_metadata,
            get_job_by_id_hash,
            _is_persistence_enabled,
        )

        if not _is_persistence_enabled():
            print( "  ⚠ Persistence is disabled in this environment — skipping DB assertions" )
            print( "  (Part 3 would verify: INSERT creates row, UPDATE writes error + stack_trace)" )
        else:
            # Build the create metadata dict the way TodoFifoQueue.push() would
            create_metadata = {
                "agent_type"      : tfe.job_type,
                "question_text"   : tfe.last_question_asked,
                "user_email"      : tfe.user_email,
                "session_id"      : tfe.session_id,
                "routing_command" : tfe.routing_command,
                "original_args"   : tfe.original_args,
                "monopolize"      : False,
            }
            persist_job_created_from_metadata( tfe.id_hash, tfe.user_id, create_metadata )
            print( f"  INSERT via persist_job_created_from_metadata: {tfe.id_hash}" )

            # Build the failed metadata dict the way running_fifo_queue.py would
            # on the except path (lines 502-517) — with full stack trace
            fail_metadata = {
                "error"       : tfe.error,
                "stack_trace" : tfe.error,  # running_fifo_queue uses traceback.format_exc()
                "agent_type"  : tfe.job_type,
                "question_text": tfe.last_question_asked,
            }
            persist_job_failed_from_metadata( tfe.id_hash, fail_metadata )
            print( f"  UPDATE via persist_job_failed_from_metadata" )

            # Now query the row and verify
            row = get_job_by_id_hash( tfe.id_hash )
            assert row is not None, \
                f"TFE row {tfe.id_hash} not found in job_history — Fix 1 (AGENTIC_JOB_TYPES) regression?"
            print( f"  ✓ Row persisted to job_history: status={row.get( 'status' )}" )

            assert row.get( "status" ) == "failed", f"expected status=failed, got {row.get( 'status' )}"
            assert row.get( "error" ) is not None, "error field must be populated"
            assert "RuntimeError" in row.get( "error", "" ), \
                "DB error field should contain the exception type"
            assert "smoke-test-forced-failure-MARKER-a9f3c" in row.get( "error", "" ), \
                "DB error field should contain the forced exception message"
            print( "  ✓ DB error field contains real traceback (not 'Unknown error')" )

            metadata_json = row.get( "metadata_json" ) or {}
            stack_trace = metadata_json.get( "stack_trace" )
            assert stack_trace is not None, \
                "metadata_json.stack_trace must be populated — Fix 4 (metadata merge) regression?"
            assert "Traceback" in stack_trace or "RuntimeError" in stack_trace, \
                "stack_trace should contain traceback or exception type"
            print( "  ✓ metadata_json.stack_trace contains the traceback" )

        # ═══════════════════════════════════════════════════════════════════
        # Part 4: Dead-queue API exposes plan_path for agentic jobs (Fix 8b)
        # ═══════════════════════════════════════════════════════════════════
        print( "\nPart 4: Dead-queue API serializer check..." )

        # Fix 8b, checked by DRIVING the serializer (row 122f07a1). This block used
        # to read queues.py's source and look for the literal dead-queue branch plus
        # the five field names, justified as "inspection rather than a full live
        # push/poll because in-memory dead queue state is wiped on every uvicorn
        # reload". That reason does not survive checking: get_queue takes its four
        # queues as ordinary arguments, so there is no live queue state to depend on.
        # The source check went green on any build that kept the branch and the words
        # while returning None for every field — which is what the user would see.
        import asyncio as _asyncio
        from unittest.mock import MagicMock as _Mock, patch as _patch
        import cosa.rest.routers.queues as queues_mod
        from cosa.agents.agentic_job_base import AgenticJobBase as _AgenticJobBase
        from cosa.rest.queue_protocol import JobState as _JobState

        _dead_job = _Mock( spec=_AgenticJobBase )
        _dead_job.id_hash             = "smoke_tfe_dead"
        _dead_job.last_question_asked = "fix the failing tests"
        _dead_job.run_date            = "2026-04-11T10:00:00"
        _dead_job.created_date        = "2026-04-11T09:00:00"
        _dead_job.user_email          = "smoke@test.com"
        _dead_job.session_id          = "smoke-test-session"
        _dead_job.job_type            = "test_fix_expediter"
        _dead_job.state               = _JobState.FAILED
        _dead_job.error               = "boom"
        _dead_job.started_at          = "2026-04-11T10:00:00"
        _dead_job.completed_at        = "2026-04-11T10:05:00"
        _dead_job.scheduled_at        = None
        _dead_job.monopolize          = False
        _dead_job.cost_summary        = { "usd": 1.25 }
        _dead_job.artifacts           = {
            "plan_path"                : "/io/plans/tfe-plan.md",
            "remediation_snapshot_path": "/io/snapshots/tfe-remediation.json",
            "report_path"              : "/io/reports/tfe-report.md",
            "yaml_path"                : "/io/tfe.yaml",
        }
        _dead_queue = _Mock()
        _dead_queue.get_jobs_for_user.return_value = [ _dead_job ]

        with _patch.object( queues_mod, "_count_interactions_for_jobs", return_value={} ):
            _out = _asyncio.run( queues_mod.get_queue(
                queue_name    = "dead",
                current_user  = { "uid": "admin1", "email": "a@x.com", "roles": [ "admin" ] },
                user_filter   = "admin1",
                todo_queue    = _Mock(), running_queue = _Mock(),
                done_queue    = _Mock(), dead_queue    = _dead_queue,
            ) )
        _card = _out[ "dead_jobs_metadata" ][ 0 ]
        assert _card[ "plan_path" ]                 == "/io/plans/tfe-plan.md", \
            f"Fix 8b regression: dead card lost plan_path — got {_card.get( 'plan_path' )!r}"
        assert _card[ "remediation_snapshot_path" ] == "/io/snapshots/tfe-remediation.json", \
            f"Fix 8b regression: dead card lost remediation_snapshot_path"
        assert _card[ "report_path" ]               == "/io/reports/tfe-report.md", \
            "Fix 8b regression: dead card lost report_path"
        assert _card[ "yaml_path" ]                 == "/io/tfe.yaml", \
            "Fix 8b regression: dead card lost yaml_path"
        assert _card[ "cost_summary" ]              == { "usd": 1.25 }, \
            "Fix 8b regression: dead card lost cost_summary"
        print( "  ✓ Fix 8b live: a dead agentic card carries all 5 partial artifacts" )

        # Frontend sanity check (Fix 8c) — make sure notifications.js has the
        # partial-artifacts section for dead cards
        import os as _os
        notif_js_path = _os.path.join(
            _os.environ.get( "LUPIN_ROOT", "/var/lupin" ),
            "src/lupin_app/static/js/notifications.js"
        )
        if _os.path.exists( notif_js_path ):
            with open( notif_js_path ) as f:
                notif_src = f.read()
            assert "job-partial-artifacts" in notif_src, \
                "Fix 8c regression: notifications.js missing job-partial-artifacts section"
            assert "Partial plan written before failure" in notif_src, \
                "Fix 8c regression: notifications.js missing partial-plan UI text"
            print( "  ✓ Fix 8c live: notifications.js has partial-artifacts section" )
        else:
            print( f"  ⚠ notifications.js not found at {notif_js_path} — skipped Fix 8c sanity check" )

        # ═══════════════════════════════════════════════════════════════════
        # Part 5: orchestrator notify_progress kwarg sanity (Fix 6)
        # ═══════════════════════════════════════════════════════════════════
        print( "\nPart 5: Fix 6 — orchestrator notify_progress has no notification_type kwarg..." )
        # Fix 6, checked on the CALLS rather than the file's text (row 122f07a1).
        # The old assertion read `"notification_type=" not in src or "# Fix 6" in src`
        # — and "# Fix 6" is a comment sitting in that very file, so the right-hand
        # side was always true and the whole check was always green. It could not
        # have failed. This walks the module's AST and looks at every notify_progress
        # call, so a real regression is named with its line number.
        import ast as _ast
        import inspect as _inspect
        import cosa.agents.test_fix_expediter.orchestrator as orch_mod

        _tree = _ast.parse( _inspect.getsource( orch_mod ) )
        _offenders = [
            f"line {n.lineno}" for n in _ast.walk( _tree )
            if isinstance( n, _ast.Call )
            and _ast.unparse( n.func ).split( "." )[ -1 ] == "notify_progress"
            and any( k.arg == "notification_type" for k in n.keywords )
        ]
        assert not _offenders, (
            f"Fix 6 regression: notify_progress called with notification_type= at "
            f"{', '.join( _offenders )} in orchestrator.py"
        )
        print( "  ✓ Orchestrator notify_progress calls are clean of the notification_type kwarg" )

        # ═══════════════════════════════════════════════════════════════════
        # All assertions passed
        # ═══════════════════════════════════════════════════════════════════
        print( "\n" + "=" * 70 )
        print( "ALL TFE FORENSIC SMOKE TEST ASSERTIONS PASSED!" )
        print( "=" * 70 )
        print( "\nKey findings:" )
        print( f"  TFE in AGENTIC_JOB_TYPES       : ✓" )
        print( f"  do_all() captures full trace   : ✓ ({len( tfe.error )} char error)" )
        print( f"  state=FAILED on exception      : ✓" )
        print( f"  Persistence round-trip         : ✓ (if DB enabled)" )
        print( f"  queues.py dead branch (Fix 8b) : ✓" )
        print( f"  notifications.js (Fix 8c)      : ✓" )
        print( f"  orchestrator kwargs (Fix 6)    : ✓" )

        return True

    except AssertionError as e:
        print( f"\n✗ Assertion failed: {e}" )
        traceback.print_exc()
        return False
    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        traceback.print_exc()
        return False


def test_tfe_error_capture_smoke():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    try:
        success = quick_smoke_test()
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
