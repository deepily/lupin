"""
CJ Flow Persistence — End-to-End Smoke Test

Automated verification of the full persistence → API → auth pipeline.
Exercises: DB insert → status progression → API query → detail lookup → cleanup.

Usage:
    python src/tests/smoke/test_job_persistence_e2e.py

Requires:
    - FastAPI server running on port 7999
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars set
    - PostgreSQL running with job_history table
"""

import os
import sys
import time
import uuid
import requests

# Bootstrap PYTHONPATH
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    # Derive from script location: src/tests/smoke/ → project root
    lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as du

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL             = "http://localhost:7999"
CREDENTIAL_ENV_PREFIX = "LUPIN_TEST_INTERACTIVE_MOCK_JOBS"
TEST_JOB_PREFIX       = "smoke-persist-test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_credentials():
    """Get test credentials from environment."""
    email    = os.environ.get( f"{CREDENTIAL_ENV_PREFIX}_EMAIL" )
    password = os.environ.get( f"{CREDENTIAL_ENV_PREFIX}_PASSWORD" )
    if not email or not password:
        print( f"  ERROR: Set {CREDENTIAL_ENV_PREFIX}_EMAIL and {CREDENTIAL_ENV_PREFIX}_PASSWORD" )
        return None, None
    return email, password


def _login( email, password ):
    """Authenticate and return ( token, headers, user_id ) or ( None, None, None )."""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=30
    )
    if resp.status_code != 200:
        print( f"  Login failed: {resp.status_code} — {resp.text[ :200 ]}" )
        return None, None, None

    data    = resp.json()
    token   = data[ "tokens" ][ "access_token" ]
    user_id = data[ "user" ][ "id" ]
    headers = { "Authorization": f"Bearer {token}" }
    return token, headers, user_id


def _cleanup_test_row( job_id ):
    """Delete test row from job_history table."""
    try:
        from cosa.rest.db.database import get_db
        from cosa.rest.postgres_models import JobHistory

        with get_db() as session:
            session.query( JobHistory ).filter( JobHistory.id_hash == job_id ).delete()
        return True
    except Exception as e:
        print( f"  Cleanup warning: {e}" )
        return False


# ---------------------------------------------------------------------------
# Test Steps
# ---------------------------------------------------------------------------

def step_authenticate():
    """Step 1: Authenticate with test credentials."""
    email, password = _get_credentials()
    if not email:
        return None, None, None, "FAIL"

    token, headers, user_id = _login( email, password )
    if not token:
        return None, None, None, "FAIL"

    return token, headers, user_id, "PASS"


def step_insert_job( job_id, user_id ):
    """Step 2: Insert a test job via persist_job_created_from_metadata."""
    from cosa.rest.job_persistence import persist_job_created_from_metadata

    metadata = {
        "agent_type"    : "deep_research",
        "question_text" : "Smoke test: CJ Flow persistence E2E verification",
        "user_email"    : "smoke-test@example.com",
        "session_id"    : "smoke-test-session"
    }

    try:
        persist_job_created_from_metadata( job_id, user_id, metadata )
        return "PASS"
    except Exception as e:
        print( f"  Insert failed: {e}" )
        return "FAIL"


def step_advance_to_running( job_id ):
    """Step 3: Advance job to running status."""
    from cosa.rest.job_persistence import persist_job_started_from_metadata

    try:
        persist_job_started_from_metadata( job_id, {} )
        return "PASS"
    except Exception as e:
        print( f"  Start failed: {e}" )
        return "FAIL"


def step_advance_to_completed( job_id ):
    """Step 4: Advance job to completed status."""
    from cosa.rest.job_persistence import persist_job_completed_from_metadata

    metadata = {
        "response_text" : "Smoke test completed successfully",
        "abstract"      : "E2E persistence verification",
        "agent_type"    : "deep_research",
        "cost_summary"  : { "total_cost_usd": 0.0, "note": "smoke test" }
    }

    try:
        persist_job_completed_from_metadata( job_id, metadata )
        return "PASS"
    except Exception as e:
        print( f"  Complete failed: {e}" )
        return "FAIL"


def step_query_job_history( headers, job_id ):
    """Step 5: Query GET /api/job-history and verify the test job appears."""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/job-history?status=completed&job_type=deep_research&limit=50",
            headers=headers,
            timeout=30
        )

        if resp.status_code != 200:
            print( f"  API returned {resp.status_code}: {resp.text[ :200 ]}" )
            return "FAIL"

        data = resp.json()
        jobs = data.get( "jobs", [] )

        # Find our test job
        for job in jobs:
            if job.get( "id_hash" ) == job_id:
                status = job.get( "status" )
                if status == "completed":
                    return "PASS"
                else:
                    print( f"  Found job but status={status}, expected 'completed'" )
                    return "FAIL"

        print( f"  Job {job_id} not found in {len( jobs )} results (total: {data.get( 'total', '?' )})" )
        return "FAIL"

    except Exception as e:
        print( f"  Query failed: {e}" )
        return "FAIL"


def step_query_job_detail( headers, job_id ):
    """Step 6: Query GET /api/job-history/{job_id} and verify detail fields."""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/job-history/{job_id}",
            headers=headers,
            timeout=30
        )

        if resp.status_code != 200:
            print( f"  Detail API returned {resp.status_code}: {resp.text[ :200 ]}" )
            return "FAIL"

        job = resp.json()
        errors = []

        if job.get( "status" ) != "completed":
            errors.append( f"status={job.get( 'status' )}, expected 'completed'" )
        if job.get( "job_type" ) != "deep_research":
            errors.append( f"job_type={job.get( 'job_type' )}, expected 'deep_research'" )
        if job.get( "duration_seconds" ) is None:
            errors.append( "duration_seconds is None (expected a value)" )
        if not job.get( "metadata_json" ):
            errors.append( "metadata_json is empty" )

        if errors:
            for err in errors:
                print( f"  Detail check: {err}" )
            return "FAIL"

        return "PASS"

    except Exception as e:
        print( f"  Detail query failed: {e}" )
        return "FAIL"


def step_cleanup( job_id ):
    """Step 7: Delete the test row from job_history."""
    return "PASS" if _cleanup_test_row( job_id ) else "FAIL"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_smoke_test():
    """Run the full E2E persistence smoke test."""
    du.print_banner( "CJ Flow Persistence — E2E Smoke Test", prepend_nl=True )

    results = []

    # Step 1: Authenticate
    print( "\n1. Authenticating..." )
    token, headers, auth_user_id, status = step_authenticate()
    results.append( ( "Authenticate", status ) )
    if status == "FAIL":
        _print_summary( results )
        return False

    # Generate unique test job ID using the authenticated user's uid
    short_uuid = str( uuid.uuid4() )[ :8 ]
    user_id    = auth_user_id
    job_id     = f"{TEST_JOB_PREFIX}-{short_uuid}::{user_id}"
    print( f"   User ID: {user_id}" )
    print( f"   Job ID:  {job_id}" )

    # Step 2: Insert test job (pending)
    print( "2. Inserting test job (status=pending)..." )
    status = step_insert_job( job_id, user_id )
    results.append( ( "Insert (pending)", status ) )
    if status == "FAIL":
        _print_summary( results )
        return False

    # Brief pause for DB commit
    time.sleep( 0.5 )

    # Step 3: Advance to running
    print( "3. Advancing to running..." )
    status = step_advance_to_running( job_id )
    results.append( ( "Update (running)", status ) )

    time.sleep( 0.5 )

    # Step 4: Advance to completed
    print( "4. Advancing to completed..." )
    status = step_advance_to_completed( job_id )
    results.append( ( "Update (completed)", status ) )

    time.sleep( 0.5 )

    # Step 5: Query job history API
    print( "5. Querying GET /api/job-history..." )
    status = step_query_job_history( headers, job_id )
    results.append( ( "API: job-history", status ) )

    # Step 6: Query job detail API
    print( "6. Querying GET /api/job-history/{job_id}..." )
    status = step_query_job_detail( headers, job_id )
    results.append( ( "API: job detail", status ) )

    # Step 7: Cleanup
    print( "7. Cleaning up test row..." )
    status = step_cleanup( job_id )
    results.append( ( "Cleanup", status ) )

    # Summary
    _print_summary( results )

    passed = all( s == "PASS" for _, s in results )
    return passed


def _print_summary( results ):
    """Print tabular summary of test results."""
    print( "\n" + "=" * 50 )
    print( f"  {'Step':<25} {'Result':<10}" )
    print( "  " + "-" * 35 )
    for step_name, status in results:
        marker = "✓" if status == "PASS" else "✗"
        print( f"  {step_name:<25} {marker} {status}" )

    passed = sum( 1 for _, s in results if s == "PASS" )
    total  = len( results )
    print( "  " + "-" * 35 )
    print( f"  {'TOTAL':<25} {passed}/{total}" )
    print( "=" * 50 )

    if passed == total:
        print( "\n  ✓ CJ Flow Persistence E2E: ALL PASS\n" )
    else:
        print( f"\n  ✗ CJ Flow Persistence E2E: {total - passed} FAILURE(S)\n" )


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit( 0 if success else 1 )
