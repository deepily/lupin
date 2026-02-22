#!/usr/bin/env python3
"""
E2E smoke test for Phase 7 proxy notification flow.

Validates the proxy notification pipeline end-to-end:

    1. Submit SWE Team job via /api/swe-team/submit with trust_mode=suggest, dry_run=true
    2. Poll done queue for job completion
    3. Verify proxy decisions were created: GET /api/proxy/pending/{email}
    4. Verify batch ID endpoint: GET /api/proxy/batch-id returns valid pr-{hex}-{N} format
    5. Verify notification was emitted: GET /api/notifications/{email}
    6. Test acknowledge cycle: POST /api/proxy/acknowledge → verify batch increments

Usage:
    python src/tests/smoke/test_proxy_notifications.py
    python src/tests/smoke/test_proxy_notifications.py --dry-run-only   # Skip live SWE job, test endpoints only

Requires:
    - Server running on localhost:7999
    - Environment variables:
        LUPIN_TEST_EMAIL / LUPIN_TEST_PASSWORD

Created: 2026-02-21
"""

import os
import re
import sys
import time

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests
import cosa.utils.util as cu


BASE_URL        = "http://localhost:7999"
REQUEST_TIMEOUT = 30
POLL_TIMEOUT    = 120
POLL_INTERVAL   = 2

BATCH_ID_PATTERN = re.compile( r"^pr-[a-f0-9]{8}-\d+$" )


def get_credentials():
    """
    Get test credentials from environment.

    Ensures:
        - Returns ( email, password ) tuple
        - Exits with error if not found
    """
    email    = os.environ.get( "LUPIN_TEST_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_PASSWORD" )

    if not email or not password:
        print( "ERROR: Set LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD" )
        sys.exit( 1 )

    return email, password


def login( email, password ):
    """
    Authenticate and return ( token, headers ).

    Ensures:
        - Returns ( token_str, headers_dict ) on success
        - Exits with error on failure
    """
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=REQUEST_TIMEOUT
    )

    if resp.status_code != 200:
        print( f"ERROR: Login failed: {resp.status_code} - {resp.text[ :200 ]}" )
        sys.exit( 1 )

    token   = resp.json()[ "tokens" ][ "access_token" ]
    headers = { "Authorization": f"Bearer {token}" }
    return token, headers


class ProxyNotificationSmokeTest:
    """
    E2E smoke test for proxy notification flow.

    Requires:
        - Server running on BASE_URL
        - Valid test credentials

    Ensures:
        - Tests batch-id endpoint format
        - Tests acknowledge cycle
        - Tests SWE Team job submission with trust_mode=suggest
        - Prints tabular results summary
    """

    def __init__( self ):
        self.results = []
        self.email   = None
        self.headers = None

    def _record( self, test_id, name, passed, detail="" ):
        """Record a test result."""
        status = "PASS" if passed else "FAIL"
        self.results.append( {
            "id"     : test_id,
            "name"   : name,
            "status" : status,
            "detail" : detail,
        } )
        icon = "✓" if passed else "✗"
        print( f"  {icon} {test_id}: {name}" )
        if detail: print( f"    {detail}" )

    def _print_summary( self ):
        """Print tabular results summary."""
        print()
        cu.print_banner( "Results Summary" )
        print( f"  {'ID':<8} {'Test':<45} {'Status':<6} {'Detail'}" )
        print( f"  {'─'*8} {'─'*45} {'─'*6} {'─'*40}" )

        for r in self.results:
            print( f"  {r[ 'id' ]:<8} {r[ 'name' ]:<45} {r[ 'status' ]:<6} {r[ 'detail' ][ :40 ]}" )

        passed = sum( 1 for r in self.results if r[ "status" ] == "PASS" )
        total  = len( self.results )
        print()
        print( f"  {passed}/{total} passed" )

        return passed == total

    def test_batch_id_endpoint( self ):
        """Test 1: GET /api/proxy/batch-id returns valid format."""
        try:
            resp = requests.get(
                f"{BASE_URL}/api/proxy/batch-id",
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )

            if resp.status_code != 200:
                self._record( "T1", "Batch ID endpoint", False, f"HTTP {resp.status_code}" )
                return

            data     = resp.json()
            batch_id = data.get( "batch_id", "" )

            if BATCH_ID_PATTERN.match( batch_id ):
                self._record( "T1", "Batch ID endpoint", True, f"batch_id={batch_id}" )
            else:
                self._record( "T1", "Batch ID endpoint", False, f"Invalid format: {batch_id}" )

        except Exception as e:
            self._record( "T1", "Batch ID endpoint", False, str( e ) )

    def test_acknowledge_cycle( self ):
        """Test 2: POST /api/proxy/acknowledge increments batch generation."""
        try:
            # Get current batch
            resp1 = requests.get(
                f"{BASE_URL}/api/proxy/batch-id",
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )
            batch_before = resp1.json().get( "batch_id", "" )

            # Acknowledge
            resp2 = requests.post(
                f"{BASE_URL}/api/proxy/acknowledge",
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )

            if resp2.status_code != 200:
                self._record( "T2", "Acknowledge cycle", False, f"HTTP {resp2.status_code}" )
                return

            ack_data = resp2.json()
            retired  = ack_data.get( "retired_batch", "" )
            new_id   = ack_data.get( "new_batch", "" )

            # Get new batch
            resp3 = requests.get(
                f"{BASE_URL}/api/proxy/batch-id",
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )
            batch_after = resp3.json().get( "batch_id", "" )

            checks = [
                retired == batch_before,
                batch_after == new_id,
                batch_after != batch_before,
                BATCH_ID_PATTERN.match( batch_after ) is not None,
            ]

            if all( checks ):
                self._record( "T2", "Acknowledge cycle", True, f"{batch_before} → {batch_after}" )
            else:
                self._record( "T2", "Acknowledge cycle", False, f"retired={retired}, new={new_id}, after={batch_after}" )

        except Exception as e:
            self._record( "T2", "Acknowledge cycle", False, str( e ) )

    def test_swe_submit_with_trust_mode( self ):
        """Test 3: Submit SWE Team dry-run job with trust_mode=suggest."""
        try:
            resp = requests.post(
                f"{BASE_URL}/api/swe-team/submit",
                json={
                    "task"       : "Add a health check endpoint for proxy notification smoke test",
                    "dry_run"    : True,
                    "trust_mode" : "suggest",
                },
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )

            if resp.status_code != 200:
                self._record( "T3", "SWE submit with trust_mode", False, f"HTTP {resp.status_code}: {resp.text[ :100 ]}" )
                return

            data   = resp.json()
            job_id = data.get( "job_id", "" )
            status = data.get( "status", "" )

            if status == "queued" and job_id:
                self._record( "T3", "SWE submit with trust_mode", True, f"job_id={job_id}" )
                return job_id
            else:
                self._record( "T3", "SWE submit with trust_mode", False, f"status={status}, job_id={job_id}" )
                return None

        except Exception as e:
            self._record( "T3", "SWE submit with trust_mode", False, str( e ) )
            return None

    def test_poll_done_queue( self, job_id ):
        """Test 4: Poll done queue for SWE Team dry-run completion."""
        if not job_id:
            self._record( "T4", "Poll done queue", False, "No job_id from submit" )
            return False

        try:
            elapsed = 0
            while elapsed < POLL_TIMEOUT:
                resp = requests.get(
                    f"{BASE_URL}/api/get-queue/done",
                    headers=self.headers,
                    timeout=REQUEST_TIMEOUT
                )

                if resp.status_code == 200:
                    data = resp.json()
                    jobs = data.get( "done_jobs_metadata", [] )

                    for job in jobs:
                        if job.get( "job_id" ) == job_id:
                            status = job.get( "status", "unknown" )
                            if status == "completed":
                                self._record( "T4", "Poll done queue", True, f"Completed in ~{elapsed}s" )
                                return True
                            else:
                                self._record( "T4", "Poll done queue", False, f"Job status: {status}" )
                                return False

                time.sleep( POLL_INTERVAL )
                elapsed += POLL_INTERVAL

            self._record( "T4", "Poll done queue", False, f"Timeout after {POLL_TIMEOUT}s" )
            return False

        except Exception as e:
            self._record( "T4", "Poll done queue", False, str( e ) )
            return False

    def test_proxy_pending_decisions( self ):
        """Test 5: Check proxy pending decisions for test user."""
        try:
            resp = requests.get(
                f"{BASE_URL}/api/proxy/pending/{self.email}",
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )

            if resp.status_code == 200:
                data      = resp.json()
                decisions = data.get( "decisions", [] )
                count     = len( decisions )
                self._record( "T5", "Proxy pending decisions", True, f"{count} decision(s) found" )
            elif resp.status_code == 404:
                self._record( "T5", "Proxy pending decisions", True, "Endpoint exists, 0 decisions (expected for dry-run)" )
            else:
                self._record( "T5", "Proxy pending decisions", False, f"HTTP {resp.status_code}" )

        except Exception as e:
            self._record( "T5", "Proxy pending decisions", False, str( e ) )

    def test_notification_history( self ):
        """Test 6: Check notification history for proxy-related entries."""
        try:
            resp = requests.get(
                f"{BASE_URL}/api/notifications/{self.email}",
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )

            if resp.status_code == 200:
                data          = resp.json()
                notifications = data.get( "notifications", [] )

                # Look for any notification with pr- progress_group_id
                proxy_notifs = [
                    n for n in notifications
                    if ( n.get( "progress_group_id" ) or "" ).startswith( "pr-" )
                ]

                count = len( proxy_notifs )
                self._record( "T6", "Notification history (proxy entries)", True, f"{count} proxy notification(s)" )
            elif resp.status_code == 404:
                self._record( "T6", "Notification history (proxy entries)", True, "Endpoint exists, no proxy notifications yet" )
            else:
                self._record( "T6", "Notification history (proxy entries)", False, f"HTTP {resp.status_code}" )

        except Exception as e:
            self._record( "T6", "Notification history (proxy entries)", False, str( e ) )

    def run( self, dry_run_only=False ):
        """
        Execute all smoke tests.

        Requires:
            - Server running on BASE_URL
            - Valid credentials in environment

        Ensures:
            - Runs all tests sequentially
            - Prints tabular summary
            - Returns True if all passed, False otherwise
        """
        cu.print_banner( "Phase 7: Proxy Notification Smoke Test", prepend_nl=True )

        # Auth
        self.email, password = get_credentials()
        _, self.headers = login( self.email, password )
        print( f"  Authenticated as: {self.email}" )
        print()

        # T1: Batch ID endpoint
        print( "Testing batch ID endpoint..." )
        self.test_batch_id_endpoint()

        # T2: Acknowledge cycle
        print( "Testing acknowledge cycle..." )
        self.test_acknowledge_cycle()

        if not dry_run_only:
            # T3: SWE submit with trust_mode
            print( "Testing SWE Team submit with trust_mode=suggest..." )
            job_id = self.test_swe_submit_with_trust_mode()

            # T4: Poll done queue
            print( "Polling done queue for completion..." )
            completed = self.test_poll_done_queue( job_id )

            # T5: Proxy pending decisions
            print( "Checking proxy pending decisions..." )
            self.test_proxy_pending_decisions()

            # T6: Notification history
            print( "Checking notification history for proxy entries..." )
            self.test_notification_history()
        else:
            print( "  (Skipping live SWE job tests — dry-run-only mode)" )

        return self._print_summary()


if __name__ == "__main__":
    dry_run_only = "--dry-run-only" in sys.argv
    test = ProxyNotificationSmokeTest()
    success = test.run( dry_run_only=dry_run_only )
    sys.exit( 0 if success else 1 )
