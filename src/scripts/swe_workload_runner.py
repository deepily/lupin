#!/usr/bin/env python3
"""
SWE Team workload runner — submits catalog tasks and captures proxy decisions.

Authenticates against the running server, submits tasks from the workload
catalog sequentially via POST /api/v2/submit with dry_run=true, polls
the done queue for completion, then queries PostgreSQL for all proxy decisions
created by each job. Writes a JSONL manifest to io/decision-proxies/ for
downstream analysis and integration test fixture generation.

Usage:
    python src/scripts/swe_workload_runner.py                    # All catalog tasks
    python src/scripts/swe_workload_runner.py --category testing # Single category
    python src/scripts/swe_workload_runner.py --limit 3          # First 3 tasks
    python src/scripts/swe_workload_runner.py --live             # Live mode (not dry-run)
    python src/scripts/swe_workload_runner.py --trust-mode shadow  # Set trust mode

Output:
    io/decision-proxies/workload-manifest-swe-team-catalog-{category|all}-{dry-run|live}-{timestamp}.jsonl

Requires:
    - LUPIN_ROOT environment variable set
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD environment variables set
    - FastAPI server running on port 7999

Ensures:
    - Each catalog task is submitted and completed before the next
    - All proxy decisions for each job are captured into a JSONL manifest
    - Manifest path is printed at completion

Session 268: Work Item 2, Step 2.3.
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Bootstrap: LUPIN_ROOT → sys.path
# ---------------------------------------------------------------------------
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/scripts/swe_workload_runner.py"
    )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from scripts.swe_workload_catalog import WORKLOAD_CATALOG, get_tasks_by_category

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL        = os.environ.get( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
# The dedicated door /api/swe-team/submit is retired (410); one front door now.
SUBMIT_ENDPOINT = "/api/v2/submit"
ROUTING_COMMAND = "agent router go to swe team"
DONE_ENDPOINT   = "/api/get-queue/done"
POLL_INTERVAL   = 2
DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login():
    """
    Login via /auth/login and return ( token, headers ).

    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD env vars set
        - Server running at BASE_URL

    Ensures:
        - Returns ( token_str, headers_dict ) on success

    Raises:
        - ValueError if env vars missing
        - requests.HTTPError if login fails
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise ValueError(
            "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables"
        )

    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=30
    )
    resp.raise_for_status()
    token   = resp.json()[ "tokens" ][ "access_token" ]
    headers = { "Authorization": f"Bearer {token}" }
    return token, headers


def get_websocket_session_id( headers ):
    """
    Get a WebSocket session ID for notifications.

    Requires:
        - headers contains valid auth token

    Returns:
        str: WebSocket session ID, or "workload-runner" as fallback
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/api/ws/session",
            headers=headers,
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get( "session_id", "workload-runner" )
    except Exception:
        pass
    return "workload-runner"


# ---------------------------------------------------------------------------
# Submit + Poll
# ---------------------------------------------------------------------------

def submit_task( task, headers, ws_id, dry_run=True, trust_mode=None ):
    """
    Submit a single SWE team task.

    Requires:
        - task is a catalog task dict with "task" key
        - headers contains valid auth token

    Ensures:
        - Returns ( job_id, None ) on success
        - Returns ( None, error_msg ) on failure
    """
    args = {
        "task"    : task[ "task" ],
        "dry_run" : dry_run,
    }
    if trust_mode:
        args[ "trust_mode" ] = trust_mode

    # ONE DOOR NOW. The dedicated endpoint this used to post to is retired and answers
    # 410 naming /api/v2/submit, which takes the routing command as a string and the
    # agent's own arguments in `args`. `websocket_id` and `parent_id_hash` stay TOP-LEVEL:
    # they are instructions about the request and the queue, not arguments to the agent,
    # and `args` is checked against the command's own argument contract, which neither is in.
    payload = {
        "command"      : ROUTING_COMMAND,
        "args"         : args,
        "question"     : task[ "task" ],
        "websocket_id" : ws_id,
    }

    try:
        resp = requests.post(
            f"{BASE_URL}{SUBMIT_ENDPOINT}",
            json=payload,
            headers=headers,
            timeout=60
        )
    except requests.exceptions.Timeout:
        return None, "Submit timed out"
    except Exception as e:
        return None, f"Submit error: {e}"

    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[ :200 ]}"

    data   = resp.json()
    job_id = data.get( "job_id" )

    if not job_id:
        return None, f"No job_id in response: {data}"

    return job_id, None


def poll_done_queue( job_id, headers, timeout=DEFAULT_TIMEOUT ):
    """
    Poll the done queue until job_id appears or timeout.

    Requires:
        - job_id is a non-empty string
        - headers contains valid auth token

    Ensures:
        - Returns ( job_metadata_dict, None ) on success
        - Returns ( None, error_msg ) on timeout/failure
    """
    elapsed = 0
    while elapsed < timeout:
        try:
            resp = requests.get(
                f"{BASE_URL}{DONE_ENDPOINT}",
                headers=headers,
                timeout=30
            )
            if resp.status_code == 200:
                done_data = resp.json()
                jobs = done_data.get( "done_jobs_metadata", [] )
                for job in jobs:
                    if job.get( "job_id" ) == job_id:
                        return job, None
        except Exception as e:
            print( f"    Poll error: {e}" )

        time.sleep( POLL_INTERVAL )
        elapsed += POLL_INTERVAL

    return None, f"Timeout after {timeout}s"


# ---------------------------------------------------------------------------
# Decision Capture
# ---------------------------------------------------------------------------

def capture_decisions_for_job( job_id ):
    """
    Query PostgreSQL for all proxy decisions created by a specific job.

    Requires:
        - job_id is a non-empty string
        - Database accessible via cosa.rest.db.database

    Ensures:
        - Returns list of decision dicts
        - Returns empty list on failure
    """
    try:
        from cosa.rest.db.database import get_db
        from sqlalchemy import text

        with get_db() as session:
            result = session.execute(
                text( """
                    SELECT id, notification_id, domain, category, question,
                           action, decision_value, confidence, trust_level,
                           reason, ratification_state, data_origin,
                           metadata_json, created_at
                    FROM proxy_decisions
                    WHERE metadata_json->>'job_id' = :job_id
                    ORDER BY created_at ASC
                """ ),
                { "job_id": job_id }
            )

            decisions = []
            for row in result:
                decisions.append( {
                    "id"                 : str( row.id ),
                    "notification_id"    : row.notification_id,
                    "domain"             : row.domain,
                    "category"           : row.category,
                    "question"           : row.question,
                    "action"             : row.action,
                    "decision_value"     : row.decision_value,
                    "confidence"         : row.confidence,
                    "trust_level"        : row.trust_level,
                    "reason"             : row.reason,
                    "ratification_state" : row.ratification_state,
                    "data_origin"        : row.data_origin,
                    "metadata_json"      : row.metadata_json,
                    "created_at"         : row.created_at.isoformat() if row.created_at else None,
                } )

            return decisions

    except Exception as e:
        print( f"  Warning: Failed to capture decisions: {e}" )
        return []


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def run_workload( tasks, dry_run=True, trust_mode=None, manifest_path=None, category=None ):
    """
    Run the full workload: authenticate, submit tasks, capture decisions.

    Requires:
        - tasks is a non-empty list of catalog task dicts
        - Server running on BASE_URL

    Ensures:
        - Returns ( results_list, manifest_path ) tuple
        - Each result contains: task_id, job_id, status, decisions, job_data
        - JSONL manifest written to manifest_path
    """
    print( f"\n{'='*70}" )
    print( f"SWE Workload Runner" )
    print( f"{'='*70}" )
    print( f"Tasks: {len( tasks )}, dry_run={dry_run}, trust_mode={trust_mode or 'default'}" )
    print()

    # Authenticate
    print( "Authenticating..." )
    token, headers = login()
    ws_id = get_websocket_session_id( headers )
    print( f"  Logged in, ws_id={ws_id}" )

    # Generate manifest path
    if manifest_path is None:
        timestamp     = datetime.now().strftime( "%Y%m%d-%H%M%S" )
        mode_label    = "dry-run" if dry_run else "live"
        source_name   = f"swe-team-catalog-{category or 'all'}"
        manifest_dir  = os.path.join( lupin_root, "io", "decision-proxies" )
        os.makedirs( manifest_dir, exist_ok=True )
        manifest_path = os.path.join(
            manifest_dir,
            f"workload-manifest-{source_name}-{mode_label}-{timestamp}.jsonl"
        )

    results     = []
    total_decs  = 0

    for i, task in enumerate( tasks ):
        task_id = task[ "id" ]
        print( f"\n[{i + 1}/{len( tasks )}] {task_id}: {task[ 'task' ][ :60 ]}..." )

        # Submit
        job_id, error = submit_task( task, headers, ws_id, dry_run=dry_run, trust_mode=trust_mode )
        if error:
            print( f"  FAILED: {error}" )
            results.append( {
                "task_id"   : task_id,
                "job_id"    : None,
                "status"    : "submit_failed",
                "error"     : error,
                "decisions" : [],
                "job_data"  : None,
            } )
            continue

        print( f"  Submitted: job_id={job_id}" )

        # Poll
        job_data, error = poll_done_queue( job_id, headers )
        if error:
            print( f"  TIMEOUT: {error}" )
            results.append( {
                "task_id"   : task_id,
                "job_id"    : job_id,
                "status"    : "timeout",
                "error"     : error,
                "decisions" : [],
                "job_data"  : None,
            } )
            continue

        print( f"  Completed: status={job_data.get( 'status', 'unknown' )}" )

        # Capture proxy decisions from PG
        decisions = capture_decisions_for_job( job_id )
        total_decs += len( decisions )
        print( f"  Captured {len( decisions )} proxy decisions" )

        for dec in decisions:
            print( f"    [{dec[ 'category' ]:<15}] conf={dec[ 'confidence' ]:.2f}  val={dec[ 'decision_value' ]}" )

        results.append( {
            "task_id"           : task_id,
            "job_id"            : job_id,
            "status"            : "completed",
            "expected_category" : task[ "category" ],
            "decisions"         : decisions,
            "job_data"          : job_data,
            "error"             : None,
        } )

    # Write JSONL manifest
    with open( manifest_path, "w" ) as f:
        for result in results:
            f.write( json.dumps( result, default=str ) + "\n" )

    # Summary table
    print( f"\n{'='*70}" )
    print( f"RESULTS SUMMARY" )
    print( f"{'='*70}" )
    print( f"{'Task ID':<20} {'Status':<15} {'Job ID':<15} {'Decisions':<10} {'Categories'}" )
    print( "-" * 80 )

    passed = 0
    for r in results:
        cats = ", ".join( set( d[ "category" ] for d in r[ "decisions" ] ) ) if r[ "decisions" ] else "—"
        dec_count = len( r[ "decisions" ] )
        status_display = r[ "status" ]
        job_display = r[ "job_id" ][ :12 ] if r[ "job_id" ] else "—"
        print( f"{r[ 'task_id' ]:<20} {status_display:<15} {job_display:<15} {dec_count:<10} {cats}" )
        if r[ "status" ] == "completed":
            passed += 1

    print( f"\nTotal: {passed}/{len( tasks )} completed, {total_decs} proxy decisions captured" )
    print( f"Manifest: {manifest_path}" )

    return results, manifest_path


def main():
    """Parse CLI args and run the workload."""
    parser = argparse.ArgumentParser( description="SWE Team Workload Runner" )
    parser.add_argument( "--category", type=str, default=None, help="Filter catalog by category" )
    parser.add_argument( "--limit", type=int, default=None, help="Limit number of tasks" )
    parser.add_argument( "--live", action="store_true", help="Run in live mode (not dry-run)" )
    parser.add_argument( "--trust-mode", type=str, default=None, help="Trust mode: shadow, suggest, active" )
    parser.add_argument( "--manifest", type=str, default=None, help="Output manifest path" )
    args = parser.parse_args()

    # Select tasks
    tasks = get_tasks_by_category( args.category )
    if args.limit:
        tasks = tasks[ :args.limit ]

    if not tasks:
        print( "No tasks selected. Check --category filter." )
        sys.exit( 1 )

    dry_run = not args.live

    results, manifest_path = run_workload(
        tasks,
        dry_run=dry_run,
        trust_mode=args.trust_mode,
        manifest_path=args.manifest,
        category=args.category,
    )

    # Exit code: 0 if all completed, 1 if any failed
    all_ok = all( r[ "status" ] == "completed" for r in results )
    sys.exit( 0 if all_ok else 1 )


if __name__ == "__main__":
    main()
