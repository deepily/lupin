"""
:8000 integration tests for two main.py paths the smoke suite never reaches.

The :8000 server runs with server coverage on, and its data left nine
lifespan lines uncovered that only a live request can reach:

- `_invalidate_snapshot_mgr` (main.py, registered with the cache registry) runs only when
  `GET /api/init` calls `invalidate_all()`. No integration test called `/api/init`.
- `_commons_activity_bridge_owner_resolver` (main.py) runs only when the CommonsActivityWatcher
  finds a new entry on a non-excluded topic, and it reaches its loop body only when a live
  voice-persona bridge exists. A clean `:8000` has none, so the broadcast test in
  test_commons_traffic_visibility_integration.py skips itself with `no-active-sessions`.

**Venue: :8000 (monopolize)**. Never run against :7999 dev. Submit via the v2 test-suite submit
with `"pytest_args": "-k test_main_lifespan_server_paths"`.

The bridge test writes a file into the session-bridge directory, so it runs only inside the
test container, whose `~/.claude/sessions` is the isolated `sessions-test` mount. On a host the
same call would plant a fake persona in the fleet's real directory, so it skips there.
"""

import json
import os
import time
import uuid
from pathlib import Path

import pytest
import requests

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir

BASE_URL  = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

# The watcher polls every `commons broadcast ack watch interval seconds` (default 1 s).
# Waiting three polls guarantees at least one full tick sees the new entry.
_WATCHER_TICKS_SECONDS = 3.5


def test_api_init_runs_the_snapshot_cache_invalidator( create_test_admin ):
    """
    GET /api/init flushes every registered cache, including the snapshot manager's.

    Requires:
        - the :8000 server is up with a snapshot manager built during lifespan
        - create_test_admin yields a user holding the admin role

    Ensures:
        - the response status is "success"
        - "snapshot_mgr" is in caches_invalidated, so the invalidator main.py registered ran and returned cleanly
    """
    resp = requests.get(
        f"{BASE_URL}/api/init",
        headers = { "Authorization": f"Bearer {create_test_admin[ 'access_token' ]}" },
        timeout = 60,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[ :300 ]}"

    body = resp.json()
    assert body[ "status" ] == "success", f"init failed: {body}"
    assert "snapshot_mgr" in body[ "caches_invalidated" ], \
        f"snapshot_mgr invalidator did not run: {body[ 'caches_invalidated' ]}"


@pytest.fixture
def planted_bridge():
    """
    Write one live voice-persona bridge into the session directory, then remove it.

    Requires:
        - the process runs inside the test container (/.dockerenv exists)

    Ensures:
        - yields the planted session id
        - the file is removed on teardown, pass or fail
        - skips on a host, where the directory is the fleet's real one
    """
    if not Path( "/.dockerenv" ).exists():
        pytest.skip( "bridge planting is container-only: on a host it would write into the fleet's real session directory" )

    session_id = f"itest-{uuid.uuid4().hex[ :12 ]}"
    directory  = sessions_dir()
    directory.mkdir( parents=True, exist_ok=True )
    path = directory / f"cc-{uuid.uuid4().int % 10**7}.json"
    path.write_text( json.dumps( {
        "session_id"    : session_id,
        "voice_persona" : { "name": "itest", "display_name": "Itest", "voice_id": "none" },
    } ) )
    try:
        yield session_id
    finally:
        path.unlink( missing_ok=True )


@pytest.mark.skipif( not ( _EMAIL and _PASSWORD ), reason="LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD not set" )
def test_activity_watcher_resolves_the_bridge_owner_map( planted_bridge ):
    """
    A broadcast to a live bridge makes the activity watcher call the owner resolver.

    Requires:
        - planted_bridge wrote a live voice-persona bridge the server can see
        - the interactive-mock-jobs login works

    Ensures:
        - the broadcast reaches the planted session (recipients >= 1), so the commons store holds a new entry
        - at least one watcher tick runs after the post, which calls the resolver in main.py and loops over the planted bridge
        - the entry is visible through GET /api/commons/broadcast-history
    """
    login = requests.post( f"{BASE_URL}/auth/login", json={ "email": _EMAIL, "password": _PASSWORD }, timeout=10 )
    assert login.status_code == 200, f"Login failed: {login.status_code} {login.text}"
    body    = login.json()
    token   = body.get( "tokens", body ).get( "access_token" )
    headers = { "Authorization": f"Bearer {token}" }

    marker = f"LIFESPAN-RESOLVER-MARKER-{uuid.uuid4().hex[ :12 ]}"
    submit = requests.post(
        f"{BASE_URL}/api/commons/broadcast-to-cc-sessions",
        json    = { "message": marker, "require_ack": False },
        headers = headers,
        timeout = 15,
    )
    assert submit.status_code == 200, f"Broadcast submit failed: {submit.status_code} {submit.text}"
    result = submit.json()
    assert result[ "status" ] != "no-active-sessions", f"planted bridge {planted_bridge} was not seen: {result}"
    assert result[ "recipients" ] >= 1, f"no recipient reached: {result}"

    time.sleep( _WATCHER_TICKS_SECONDS )

    history = requests.get(
        f"{BASE_URL}/api/commons/broadcast-history",
        headers = headers,
        params  = { "hours": 1, "limit": 200 },
        timeout = 10,
    )
    assert history.status_code == 200
    assert any( marker in ( e.get( "body" ) or "" ) for e in history.json()[ "entries" ] ), \
        f"marker {marker!r} missing from broadcast-history"
