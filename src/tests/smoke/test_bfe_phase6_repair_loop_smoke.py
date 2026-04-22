#!/usr/bin/env python3
"""
Smoke test for BFE Phase 6 automated repair loop (dry-run, $0 cost).

Verifies the full Phase 6 loop end-to-end using existing dry-run infrastructure
plus the new `force_failure_mode` failure-injection hook:

    submit dry-run DR with force_failure_mode=code_bug
        ↓
    dry-run job runs breadcrumbs, raises KeyError at end
        ↓
    running_fifo_queue pushes failed job to dead queue
        ↓
    dead_queue_watchdog.evaluate() fires — classifies as CODE_BUG,
    propagates dry_run=True to spawned BFE, pushes BFE to todo queue
        ↓
    BFE dry-run runs breadcrumbs, packages real DeadJobContext,
    strips force_failure_mode from original_args (simulates the "fix"),
    calls _resubmit_original_job() → pushes clean DR back to todo
        ↓
    resubmitted DR runs dry-run cleanly (no force_failure_mode)
        ↓
    done queue ends up with: original failed DR (in dead), BFE (done),
    resubmitted DR (done)

Scenarios:
    DR_LOOP_HAPPY  — requires `auto fix enabled = true`
    PG_LOOP_HAPPY  — requires `auto fix enabled = true`
    WATCHDOG_DISABLED — requires `auto fix enabled = false`

The test reads the current `auto fix enabled` config at startup and runs
the scenarios that match. It is NOT interactive — no proxy, no gap analysis,
no user input required. All failures are deliberately injected via the
`force_failure_mode` REST parameter.

Requires:
    - Server running on localhost:7999
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD environment variables
    - LUPIN_ROOT environment variable (bootstrap)

Usage:
    # Happy-path scenarios (requires auto fix enabled = true in lupin-app.ini)
    python src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py

    # Watchdog-disabled scenario (requires auto fix enabled = false)
    python src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py

Created: 2026-04-10
Plan: src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/09-phase6-dry-run-smoke-test-plan.md
"""

import os
import sys
import time
import traceback

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests
import cosa.utils.util as cu


BASE_URL         = "http://localhost:7999"
MAX_POLL_SECONDS = 120
POLL_INTERVAL    = 2


def _login():
    """
    Authenticate against /auth/login and return Bearer headers.

    Ensures:
        - Returns ( headers_dict, email ) on success
        - Returns ( None, None ) on failure
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

    if not email or not password:
        print( "✗ Missing environment variables:" )
        print( "  export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD='yourpassword'" )
        return None, None

    print( f"Logging in as {email}..." )
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=30
    )
    if resp.status_code != 200:
        print( f"✗ Login failed: {resp.status_code} {resp.text[ :200 ]}" )
        return None, None

    token = resp.json()[ "tokens" ][ "access_token" ]
    print( f"✓ Login successful" )
    return { "Authorization": f"Bearer {token}" }, email


def _read_auto_fix_enabled():
    """
    Read the current `auto fix enabled` config value directly.

    The watchdog reloads config on every evaluate() call, so whatever we read
    here is what will be in force when the test runs.

    Ensures:
        - Returns True/False based on INI
        - Returns None if config cannot be loaded
    """
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return config_mgr.get( "auto fix enabled", default=False, return_type="boolean" )
    except Exception as e:
        print( f"⚠ Could not read auto fix enabled config: {e}" )
        return None


def _submit_dry_run_job( headers, endpoint, payload, label ):
    """
    Submit a dry-run job with force_failure_mode to a native REST endpoint.

    Args:
        headers: Auth headers dict
        endpoint: REST endpoint path (e.g. "/api/deep-research/submit")
        payload: Full JSON body dict (must include dry_run=True and force_failure_mode)
        label: Human-readable label for logging

    Returns:
        str or None: job_id on success, None on failure
    """
    print( f"\n>>> Submitting {label}..." )
    print( f"    Endpoint: {endpoint}" )
    print( f"    force_failure_mode: {payload.get( 'force_failure_mode' )}" )
    resp = requests.post( f"{BASE_URL}{endpoint}", json=payload, headers=headers, timeout=30 )
    if resp.status_code != 200:
        print( f"✗ Submit failed: {resp.status_code} {resp.text[ :300 ]}" )
        return None
    data = resp.json()
    job_id = data.get( "job_id" )
    print( f"✓ Submitted: job_id={job_id}, status={data.get( 'status' )}" )
    return job_id


def _poll_queue( headers, queue_name, predicate, label, max_seconds=MAX_POLL_SECONDS ):
    """
    Poll a queue until `predicate(jobs)` returns a truthy value, or timeout.

    Args:
        headers: Auth headers
        queue_name: "todo" | "run" | "done" | "dead"
        predicate: callable( jobs_metadata_list ) → matched_object or None
        label: Human-readable label for logging
        max_seconds: Poll timeout

    Returns:
        Whatever predicate returned (typically a job dict), or None on timeout.
    """
    metadata_key = f"{queue_name}_jobs_metadata"
    elapsed = 0
    print( f"    Polling {queue_name} queue for {label} (max {max_seconds}s)..." )

    while elapsed < max_seconds:
        try:
            resp = requests.get( f"{BASE_URL}/api/get-queue/{queue_name}", headers=headers, timeout=30 )
            if resp.status_code == 200:
                jobs = resp.json().get( metadata_key, [] )
                hit = predicate( jobs )
                if hit:
                    print( f"    ✓ Found after {elapsed}s" )
                    return hit
        except requests.exceptions.RequestException as e:
            print( f"    ⚠ poll error: {e}" )

        time.sleep( POLL_INTERVAL )
        elapsed += POLL_INTERVAL

    print( f"    ✗ Not found in {queue_name} queue after {max_seconds}s" )
    return None


def _verify_dry_run_cost( job ):
    """
    Verify a completed job has $0.00 cost (dry-run indicator).

    Returns True if cost is $0.00, False otherwise.
    """
    cost_summary = job.get( "cost_summary" )
    if cost_summary is None:
        return True  # No cost data → assume dry-run
    if isinstance( cost_summary, dict ):
        total = cost_summary.get( "total_cost_usd", cost_summary.get( "total_cost", 0.0 ) )
    else:
        total = 0.0
    return total == 0.0 or total == 0


def run_dr_loop_happy_scenario( headers, user_email ):
    """
    DR_LOOP_HAPPY: full repair loop with deep research dry-run as the target.

    Requires `auto fix enabled = true`.

    Ensures:
        - Returns True on full success (loop closed, resubmit completed)
        - Returns False on any assertion failure
    """
    cu.print_banner( "Scenario 1: DR_LOOP_HAPPY — Deep Research repair loop", prepend_nl=True )

    # Step 1: Submit the original failing DR dry-run. Include `audience` so the
    # persistence round-trip has a non-default, user-supplied arg to verify.
    submit_payload = {
        "query"              : "phase6 smoke test — deep research repair loop",
        "budget"             : 0.01,
        "audience"           : "expert",
        "websocket_id"       : "phase6-smoke-dr",
        "dry_run"            : True,
        "force_failure_mode" : "code_bug",
    }
    original_job_id = _submit_dry_run_job(
        headers,
        "/api/deep-research/submit",
        submit_payload,
        "original DR (force_failure_mode=code_bug, audience=expert)"
    )
    if not original_job_id:
        return False

    # Step 2: Poll dead queue — original DR must land here
    print( "\n>>> Step 2: Waiting for original DR to land in dead queue..." )
    dead_hit = _poll_queue(
        headers, "dead",
        lambda jobs: next( ( j for j in jobs if j.get( "job_id" ) == original_job_id ), None ),
        "original DR in dead queue"
    )
    if dead_hit is None:
        return False
    error = dead_hit.get( "error", "" ) or ""
    print( f"    Error message: {error[ :120 ]}" )
    if "KeyError" not in error and "source_path" not in error:
        print( f"⚠ Error doesn't look like injected code_bug: {error[ :200 ]}" )

    # Step 3: Poll todo queue for spawned BFE job (watchdog should have fired)
    print( "\n>>> Step 3: Waiting for watchdog to spawn BFE job..." )
    def _find_bfe( jobs ):
        for j in jobs:
            agent_type = ( j.get( "agent_type" ) or "" ).lower()
            job_id     = j.get( "job_id", "" )
            if "bug_fix" in agent_type or job_id.startswith( "bfx-" ):
                return j
        return None

    # BFE may appear briefly in todo or run queues, or may already be in done.
    # Check done queue instead, since dry-run BFE finishes in ~5s.
    bfe_done = _poll_queue(
        headers, "done",
        _find_bfe,
        "BFE job in done queue (post-watchdog)"
    )
    if bfe_done is None:
        print( "✗ Watchdog did not spawn BFE. Check server log for [Watchdog] lines." )
        print( "  Likely cause: auto fix enabled = false in lupin-app.ini" )
        return False

    bfe_job_id = bfe_done.get( "job_id" )
    print( f"    BFE job_id: {bfe_job_id}" )

    # Verify BFE ran in dry-run mode (cost=$0)
    if not _verify_dry_run_cost( bfe_done ):
        print( f"⚠ BFE cost_summary suggests non-dry-run: {bfe_done.get( 'cost_summary' )}" )

    # Step 4: Poll done queue for the resubmitted original DR
    print( "\n>>> Step 4: Waiting for resubmitted DR to complete..." )
    def _find_resubmitted_dr( jobs ):
        # The resubmitted job is a DR with SAME query but different job_id.
        # It should arrive AFTER the BFE job (timestamp-wise).
        for j in jobs:
            if j.get( "agent_type" ) == "deep_research" and j.get( "job_id" ) != original_job_id:
                question = ( j.get( "question_text" ) or "" ).lower()
                if "phase6 smoke" in question:
                    return j
        return None

    resubmitted = _poll_queue(
        headers, "done",
        _find_resubmitted_dr,
        "resubmitted DR in done queue"
    )
    if resubmitted is None:
        print( "✗ Resubmitted DR did not reach done queue." )
        print( "  Possible causes:" )
        print( "    - BFE _resubmit_original_job() returned None (check auto fix enabled)" )
        print( "    - Resubmitted DR re-failed (force_failure_mode not stripped)" )
        return False

    resubmit_job_id = resubmitted.get( "job_id" )
    print( f"    Resubmitted job_id: {resubmit_job_id}" )

    # Verify resubmitted DR succeeded (status=completed, cost=$0)
    status = resubmitted.get( "status" ) or ""
    if status not in ( "completed", "done" ):
        print( f"⚠ Resubmitted DR status is '{status}', expected 'completed'" )
    if not _verify_dry_run_cost( resubmitted ):
        print( f"⚠ Resubmitted DR cost_summary: {resubmitted.get( 'cost_summary' )}" )
        return False

    # Step 5: CJ Flow persistence round-trip assertions.
    # Read the ORIGINAL DR's job_history row directly and verify the three
    # persistence fields that motivated this fix are populated end-to-end.
    print( "\n>>> Step 5: Verifying CJ Flow persistence round-trip (session_id, routing_command, original_args)..." )
    from cosa.rest.job_persistence import get_job_by_id_hash
    row = get_job_by_id_hash( original_job_id )
    if row is None:
        print( f"✗ Original DR job_history row not found: {original_job_id}" )
        return False

    row_session_id      = row.get( "session_id" )
    row_routing_command = row.get( "routing_command" )
    row_metadata_json   = row.get( "metadata_json" ) or {}
    row_original_args   = row_metadata_json.get( "original_args" ) or {}

    print( f"    session_id      = {row_session_id}" )
    print( f"    routing_command = {row_routing_command}" )
    print( f"    original_args   = {row_original_args}" )

    failures = []
    if row_session_id != "phase6-smoke-dr":
        failures.append( f"session_id: expected 'phase6-smoke-dr', got {row_session_id!r}" )
    if row_routing_command != "agent router go to deep research":
        failures.append( f"routing_command: expected 'agent router go to deep research', got {row_routing_command!r}" )
    if row_original_args.get( "query" ) != submit_payload[ "query" ]:
        failures.append( f"original_args.query: expected {submit_payload[ 'query' ]!r}, got {row_original_args.get( 'query' )!r}" )
    # budget comes through as a string because the REST endpoint stringifies it (deep_research.py:144)
    if str( row_original_args.get( "budget" ) ) != str( submit_payload[ "budget" ] ):
        failures.append( f"original_args.budget: expected '0.01', got {row_original_args.get( 'budget' )!r}" )
    if row_original_args.get( "audience" ) != "expert":
        failures.append( f"original_args.audience: expected 'expert', got {row_original_args.get( 'audience' )!r}" )
    if row_original_args.get( "force_failure_mode" ) != "code_bug":
        failures.append( f"original_args.force_failure_mode: expected 'code_bug' (the original), got {row_original_args.get( 'force_failure_mode' )!r}" )

    if failures:
        print( "✗ Persistence round-trip FAILED:" )
        for f in failures: print( f"    - {f}" )
        return False
    print( "    ✓ All persistence fields round-tripped correctly" )

    # Step 6: Verify the RESUBMITTED DR has its own original_args with
    # force_failure_mode stripped and dry_run=True set (BFE's dry-run "fix").
    print( "\n>>> Step 6: Verifying resubmitted DR's original_args reflect BFE's simulated fix..." )
    resub_row = get_job_by_id_hash( resubmit_job_id )
    if resub_row is None:
        print( f"✗ Resubmitted DR job_history row not found: {resubmit_job_id}" )
        return False
    resub_args = ( resub_row.get( "metadata_json" ) or {} ).get( "original_args" ) or {}
    print( f"    resubmitted original_args = {resub_args}" )

    resub_failures = []
    if "force_failure_mode" in resub_args:
        resub_failures.append( f"force_failure_mode should have been stripped by BFE, but is {resub_args[ 'force_failure_mode' ]!r}" )
    if resub_args.get( "dry_run" ) is not True:
        resub_failures.append( f"dry_run should be True (set by BFE), but is {resub_args.get( 'dry_run' )!r}" )
    if resub_args.get( "audience" ) != "expert":
        resub_failures.append( f"audience should have been preserved ('expert'), but is {resub_args.get( 'audience' )!r}" )
    if resub_args.get( "query" ) != submit_payload[ "query" ]:
        resub_failures.append( f"query should have been preserved, but is {resub_args.get( 'query' )!r}" )

    if resub_failures:
        print( "✗ Resubmit args round-trip FAILED:" )
        for f in resub_failures: print( f"    - {f}" )
        return False
    print( "    ✓ Resubmit args correctly preserve query+audience, strip force_failure_mode, set dry_run=True" )

    print( "\n✓ DR_LOOP_HAPPY passed:" )
    print( f"    original   (dead) = {original_job_id}" )
    print( f"    BFE        (done) = {bfe_job_id}" )
    print( f"    resubmitted(done) = {resubmit_job_id}" )
    print( f"    persistence       = session_id + routing_command + original_args all verified" )
    return True


def run_watchdog_disabled_scenario( headers ):
    """
    WATCHDOG_DISABLED: verify that failed dry-run jobs stay dead when auto-fix is off.

    Requires `auto fix enabled = false`.
    """
    cu.print_banner( "Scenario: WATCHDOG_DISABLED — auto-fix off", prepend_nl=True )

    original_job_id = _submit_dry_run_job(
        headers,
        "/api/deep-research/submit",
        {
            "query"              : "phase6 smoke test — watchdog disabled",
            "budget"             : 0.01,
            "websocket_id"       : "phase6-smoke-dr-disabled",
            "dry_run"            : True,
            "force_failure_mode" : "code_bug",
        },
        "DR (watchdog disabled, expect no BFE)"
    )
    if not original_job_id:
        return False

    # Step 2: Wait for dead queue entry
    dead_hit = _poll_queue(
        headers, "dead",
        lambda jobs: next( ( j for j in jobs if j.get( "job_id" ) == original_job_id ), None ),
        "original DR in dead queue"
    )
    if dead_hit is None:
        return False

    # Step 3: Wait a reasonable window, then confirm NO BFE was spawned
    print( "\n>>> Step 3: Sleeping 15s to give the watchdog time to fire (should NOT)..." )
    time.sleep( 15 )

    resp = requests.get( f"{BASE_URL}/api/get-queue/done", headers=headers, timeout=30 )
    done_jobs = resp.json().get( "done_jobs_metadata", [] )
    bfe_jobs = [ j for j in done_jobs if ( j.get( "agent_type" ) or "" ).lower().startswith( "bug" ) ]
    recent_bfe = [ j for j in bfe_jobs if j.get( "completed_at", "" ) > dead_hit.get( "timestamp", "" ) ]

    if recent_bfe:
        print( f"✗ Found {len( recent_bfe )} BFE job(s) in done after dead-queue event — watchdog fired when it should not have:" )
        for j in recent_bfe:
            print( f"    {j.get( 'job_id' )} completed_at={j.get( 'completed_at' )}" )
        return False

    print( "✓ WATCHDOG_DISABLED passed: no BFE spawned" )
    return True


def quick_smoke_test():
    """
    Main smoke test entry point.

    Ensures:
        - Detects current `auto fix enabled` setting
        - Runs the matching scenario(s)
        - Returns True on overall success
    """
    cu.print_banner( "BFE Phase 6 Dry-Run Repair Loop Smoke Test", prepend_nl=True )

    try:
        headers, user_email = _login()
        if headers is None:
            return False

        # Detect current config mode
        auto_fix_enabled = _read_auto_fix_enabled()
        if auto_fix_enabled is None:
            print( "⚠ Could not determine auto fix enabled — assuming disabled" )
            auto_fix_enabled = False

        print( f"\nConfig: auto fix enabled = {auto_fix_enabled}" )
        print( "=" * 70 )

        if auto_fix_enabled:
            print( "Running happy-path scenarios (watchdog enabled)" )
            results = {
                "DR_LOOP_HAPPY": run_dr_loop_happy_scenario( headers, user_email ),
            }
        else:
            print( "Running watchdog-disabled scenario" )
            print( "To test the happy-path loop, set `auto fix enabled = true` in lupin-app.ini" )
            print( "and restart the server, then rerun this smoke test." )
            results = {
                "WATCHDOG_DISABLED": run_watchdog_disabled_scenario( headers ),
            }

        # Tabular summary
        print( "\n" + "=" * 70 )
        print( "  Scenario              Result" )
        print( "-" * 70 )
        for name, ok in results.items():
            icon = "✓" if ok else "✗"
            print( f"  {icon} {name:<22} {'PASS' if ok else 'FAIL'}" )
        print( "=" * 70 )

        passed = sum( 1 for ok in results.values() if ok )
        total  = len( results )
        print( f"\n  Total: {passed}/{total} passed" )
        print( f"  Overall: {'PASS' if passed == total else 'FAIL'}" )

        return passed == total

    except requests.exceptions.ConnectionError:
        print( f"\n✗ Connection failed - is the server running on {BASE_URL}?" )
        return False
    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        traceback.print_exc()
        return False


def test_bfe_phase6_repair_loop_smoke():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    try:
        success = quick_smoke_test()
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
