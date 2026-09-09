#!/usr/bin/env python3
"""
🔴 PROPOSED, NOT RATIFIED — the pyramid is Rick's gate; awaiting his word, 10:30 chase 2026-09-09.

The two /api/notify tests that WRITE ROWS — routed :8000-scheduled.

🔴 WHY THIS FILE EXISTS: THESE TWO WERE RUNNING ON THE MERGE GATE'S :7999 LEG.
They lived in `src/tests/smoke/test_notifications_sse_smoke.py`, which
`src/tests/run-smoke-tests.sh:47` sweeps wholesale — `pytest src/tests/smoke/`,
excluding only `test_proxy_integration.py`. That is the "smoke (:7999)" leg of
CLAUDE.md's PR merge requirements. Both tests below reach
`_persist_notification_sync` at `routers/notifications.py:1063` on a 200 and
each CREATES A NOTIFICATION ROW that nothing cleans up. By the § TESTING VENUES
rubric that is persistent-state mutation, which is :8000. The other seven tests
in that file write nothing and correctly stay where they are — moving the whole
file would have pulled seven fast, safe tests out of the gate that runs them,
which is a change that reduces coverage while looking like compliance.

🔴 AND THE ORDER OF REPAIRS IS LOAD-BEARING — READ BEFORE FIXING THE AUTH DEFECT.
`test_offline_with_default` creates the ORPHAN SPECIES that row bf4f65c3 is
about: `response_requested=True` with a `response_default`, a row that is never
marked expired and stays `delivered` forever. It has never actually made one,
because it has been failing at the credential defect (row c46ba7c0) and never
reaching the handler. MEASURED 2026-09-08 ~20:25 EDT, read-only, both databases
named:

    "Smoke test offline with default"  in lupin_db_dev   ->  0 rows
    "Smoke test fire-and-forget..."    in lupin_db_dev   ->  0 rows
    both, in lupin_db_test                               ->  0 rows
    positive controls: 490,996 rows in dev, 567 in test — the query reaches
    retention: dev holds 2026-02-10 .. 2026-09-09, nothing purges — so the
               zero is a real absence, not a sweep

⇒ THE VENUE VIOLATION IS A LOADED GUN THAT HAS NOT GONE OFF, and the credential
defect is the only thing holding the hammer. Fix auth while these two still sit
on the :7999 sweep and the merge pyramid starts minting a response-required
orphan on every fire. That is why this move lands FIRST and the auth fix second.

⚠️ THESE TWO ARE RED TODAY, AND NOT BECAUSE OF THIS MOVE. Both fail 401
"Missing auth. Provide X-API-Key or Authorization: Bearer <jwt>" — they send the
credential as a query param and `api_key_auth.py:208` reads a Header. That is
row c46ba7c0's staircase, deliberately NOT repaired here: read all three of its
faults before touching the first, or you will fix one, see the next fire, and
revert a correct repair.
"""

import sys
import os
import requests
import json

# Bootstrap: this file runs before `cosa` is importable, so sys.path is set
# manually here and every later path comes from cu.get_project_root().
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    print( "ERROR: LUPIN_ROOT environment variable not set" )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu


BASE_URL  = "http://localhost:8000"
API_KEY   = "claude_code_simple_key"
TEST_USER = os.environ.get( "LUPIN_DEV_EMAIL", "test@example.com" )


def print_test_header( test_name ):
    """Print formatted test header."""
    print( f"\n{'=' * 60}" )
    print( f"  {test_name}" )
    print( f"{'=' * 60}" )


def test_fire_and_forget_mode():
    """
    Fire-and-forget mode — notifications without response_requested.

    WRITES: one Notification row via `repo.create_notification`, marked
    'delivered' when the target user is connected. Nothing cleans it up.

    Requires:
        - a live server at BASE_URL

    Ensures:
        - status is 200
        - the response carries a 'status' field of 'queued' or 'user_not_available'
    """
    print_test_header( "Fire-and-Forget Mode" )

    response = requests.post(
        f"{BASE_URL}/api/notify",
        params={
            "message"     : "Smoke test fire-and-forget notification",
            "type"        : "task",
            "priority"    : "low",
            "target_user" : TEST_USER,
            "api_key"     : API_KEY
        },
        timeout=5
    )

    print( f"Status Code: {response.status_code}" )
    data = response.json()
    print( f"Response: {json.dumps(data, indent=2)}" )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert "status" in data, "Response missing 'status' field"
    assert data["status"] in ["queued", "user_not_available"], f"Unexpected status: {data['status']}"


def test_offline_with_default():
    """
    Offline detection with a default response.

    🔴 WRITES THE ORPHAN SPECIES: response_requested=True with a response_default
    is exactly the row shape row bf4f65c3 tracks — never marked expired, stays
    'delivered' forever. One row per run, never cleaned up.

    Requires:
        - a live server at BASE_URL

    Ensures:
        - status is 200
        - on the OFFLINE path (application/json) the default is returned immediately
        - on the ONLINE path (text/event-stream) an SSE stream is created
        - any other content-type or status fails, naming what it saw
    """
    print_test_header( "Offline Detection with Default" )

    response = requests.post(
        f"{BASE_URL}/api/notify",
        params={
            "message"           : "Smoke test offline with default",
            "type"              : "task",
            "priority"          : "high",
            "target_user"       : TEST_USER,
            "api_key"           : API_KEY,
            "response_requested": True,
            "response_type"     : "yes_no",
            "response_default"  : "no"
        },
        timeout=5
    )

    print( f"Status Code: {response.status_code}" )

    if response.status_code == 200:
        content_type = response.headers.get( "content-type", "" )

        if "application/json" in content_type:
            data = response.json()
            print( f"Response (offline): {json.dumps(data, indent=2)}" )
            assert data["status"] == "offline", f"Expected 'offline', got '{data['status']}'"
            assert data["response"] == "no", f"Expected response 'no', got '{data.get('response', 'MISSING')}'"
            assert data["default_used"] == "no", (
                f"Expected default_used 'no' (value, not boolean for the offline path), "
                f"got '{data['default_used']}'"
            )

        elif "text/event-stream" in content_type:
            print( "Response: SSE stream created (user is online) — expected behaviour" )

        else:
            raise AssertionError(
                f"200 with an unexpected content-type: {content_type!r}. This door "
                f"returns application/json on the offline path and text/event-stream "
                f"on the online one; anything else is neither."
            )

    else:
        raise AssertionError(
            f"expected 200, got {response.status_code}. Body: {response.text[:200]}"
        )
