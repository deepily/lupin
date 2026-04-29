"""
Smoke test for the voice persona allocation HTTP endpoints.

Verifies the contract that the SessionStart hook depends on:
    POST /api/cosa-voice/voice-persona/{session_id}/allocate
    POST /api/cosa-voice/voice-persona/{session_id}/release
    GET  /api/cosa-voice/voice-persona/pool

This test creates a synthetic bridge file in the real ~/.claude/sessions/
directory (the same one the live server reads), POSTs /allocate, verifies
the bridge gained a voice_persona field, then cleans up.

Venue: :7999 (AI-discretionary). Test is non-destructive (the bridge file
created/torn down is named with a unique UUID and the PID is the test PID,
which is alive for the test run). Runtime is sub-second.

Requires:
    - Server running at LUPIN_APP_SERVER_URL (default http://localhost:7999)
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD env vars set

See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md
"""

import json
import os
import uuid
from pathlib import Path

import pytest
import requests


BASE_URL    = os.environ.get( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
SESSION_DIR = Path.home() / ".claude" / "sessions"


# ── Auth fixture ─────────────────────────────────────────────────────────────

@pytest.fixture( scope="module" )
def auth_token():
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip(
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD must be set"
        )

    try:
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json    = { "email": email, "password": password },
            timeout = 5
        )
    except requests.exceptions.ConnectionError:
        pytest.skip( f"Server not reachable at {BASE_URL}" )

    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    return resp.json()[ "tokens" ][ "access_token" ]


# ── Bridge fixture: create a synthetic bridge in the real SESSION_DIR ────────

@pytest.fixture
def synthetic_bridge():
    """
    Create a synthetic bridge file with a unique session_id under the real
    ~/.claude/sessions/ directory. The PID is the test process's PID so the
    server's dead-PID filter does NOT skip this bridge during the test.

    Yields ( session_id, bridge_path ). Tears down at end (deletes both the
    bridge file and any voice_persona it accumulated).
    """
    SESSION_DIR.mkdir( parents=True, exist_ok=True )

    # Unique session_id so we never collide with a real CC session
    session_id  = str( uuid.uuid4() )
    test_pid    = os.getpid()
    # Use a high offset so we don't collide with the real test PID's CC bridge
    pid_alias   = test_pid + 90000
    bridge_path = SESSION_DIR / f"cc-{pid_alias}.json"

    # If this PID happens to have a bridge (very unlikely), skip
    if bridge_path.exists():
        pytest.skip( f"Bridge collision at {bridge_path} — pick a different pid offset" )

    bridge_data = {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "session_ids"       : [ session_id ],
        "transcript_path"   : "/tmp/synthetic-transcript.jsonl",
        "cwd"               : "/tmp",
        "ppid"              : test_pid,        # alive for liveness check
        "hook_ppid"         : 1,
        "tmux_session"      : None
    }
    with open( bridge_path, "w" ) as f:
        json.dump( bridge_data, f )

    yield session_id, bridge_path

    # Cleanup
    try:
        bridge_path.unlink()
    except FileNotFoundError:
        pass


# ── Tests ────────────────────────────────────────────────────────────────────

class TestVoicePersonaPool:

    def test_get_pool_returns_6_voices( self, auth_token ):
        """GET /pool should return the 6 configured allocatable voices."""
        resp = requests.get(
            f"{BASE_URL}/api/cosa-voice/voice-persona/pool",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        )
        assert resp.status_code == 200, f"GET /pool failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "pool" in body
        assert "occupied_names" in body
        assert "free_names" in body
        # Pool must contain exactly the 6 expected voices (Sam not in pool)
        pool_names = [ p[ "name" ] for p in body[ "pool" ] ]
        assert len( pool_names ) == 6, f"Expected 6-voice pool, got {pool_names}"
        assert "Sam" not in pool_names, "Sam must NOT be in the allocatable pool"
        assert set( pool_names ) == { "Nora", "Quentin", "Rachel", "Adam", "Domi", "Arnold" }


class TestVoicePersonaAllocateAndRelease:

    def test_allocate_returns_persona_not_sam( self, auth_token, synthetic_bridge ):
        """POST /allocate should return a persona from the pool (never Sam)."""
        session_id, bridge_path = synthetic_bridge

        resp = requests.post(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{session_id}/allocate",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        )
        assert resp.status_code == 200, f"/allocate failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body[ "newly_allocated" ] is True
        persona = body[ "voice_persona" ]
        assert persona is not None
        assert persona[ "voice_id" ]
        assert persona[ "name" ] in { "Nora", "Quentin", "Rachel", "Adam", "Domi", "Arnold" }
        assert persona[ "voice_id" ] != "G7ILShrCNLfmS0A37SXS", "Sam's voice ID must NOT be allocated"
        assert "assigned_at" in persona

        # Verify the bridge file was actually written
        with open( bridge_path ) as f:
            data = json.load( f )
        assert data.get( "voice_persona" ) is not None
        assert data[ "voice_persona" ][ "voice_id" ] == persona[ "voice_id" ]

    def test_allocate_is_idempotent( self, auth_token, synthetic_bridge ):
        """Second /allocate for the same session should return the same persona, newly_allocated=False."""
        session_id, _ = synthetic_bridge

        # First allocate
        first  = requests.post(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{session_id}/allocate",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        ).json()
        # Second allocate
        second = requests.post(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{session_id}/allocate",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        ).json()

        assert first[ "newly_allocated" ] is True
        assert second[ "newly_allocated" ] is False
        assert first[ "voice_persona" ][ "voice_id" ] == second[ "voice_persona" ][ "voice_id" ]
        assert first[ "voice_persona" ][ "name" ]     == second[ "voice_persona" ][ "name" ]

    def test_release_clears_persona( self, auth_token, synthetic_bridge ):
        """POST /release should clear the bridge field; subsequent GET returns null."""
        session_id, bridge_path = synthetic_bridge

        # Allocate first
        requests.post(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{session_id}/allocate",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        )

        # Release
        resp = requests.post(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{session_id}/release",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        )
        assert resp.status_code == 200, f"/release failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body[ "released" ] is True

        # GET should now return null
        resp = requests.get(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{session_id}",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        )
        assert resp.status_code == 200
        assert resp.json()[ "voice_persona" ] is None

        # Bridge file's voice_persona is null
        with open( bridge_path ) as f:
            data = json.load( f )
        assert data.get( "voice_persona" ) is None

    def test_release_idempotent_on_unallocated( self, auth_token, synthetic_bridge ):
        """Releasing a session with no persona returns released=False, no error."""
        session_id, _ = synthetic_bridge

        resp = requests.post(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{session_id}/release",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        )
        assert resp.status_code == 200
        assert resp.json()[ "released" ] is False

    def test_allocate_for_unknown_session_returns_404( self, auth_token ):
        """Allocating for a session_id that has no bridge file returns 404."""
        ghost_sid = "ghostsid-aaaa-bbbb-cccc-dddddddddddd"
        resp = requests.post(
            f"{BASE_URL}/api/cosa-voice/voice-persona/{ghost_sid}/allocate",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 5
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


class TestVoicePersonaUniqueness:

    def test_two_concurrent_sessions_get_distinct_voices( self, auth_token ):
        """
        Allocate personas for TWO synthetic bridges. They must be distinct.
        This is the core anti-collision guarantee.
        """
        SESSION_DIR.mkdir( parents=True, exist_ok=True )
        test_pid = os.getpid()

        sids        = [ str( uuid.uuid4() ) for _ in range( 2 ) ]
        bridges     = [ SESSION_DIR / f"cc-{test_pid + 91000 + i}.json" for i in range( 2 ) ]
        try:
            for sid, path in zip( sids, bridges ):
                with open( path, "w" ) as f:
                    json.dump(
                        {
                            "session_id"        : sid,
                            "stable_session_id" : sid,
                            "session_ids"       : [ sid ],
                            "cwd"               : "/tmp",
                            "ppid"              : test_pid,  # alive
                            "hook_ppid"         : 1
                        },
                        f
                    )

            allocated_voice_ids = []
            for sid in sids:
                resp = requests.post(
                    f"{BASE_URL}/api/cosa-voice/voice-persona/{sid}/allocate",
                    headers = { "Authorization": f"Bearer {auth_token}" },
                    timeout = 5
                )
                assert resp.status_code == 200
                allocated_voice_ids.append( resp.json()[ "voice_persona" ][ "voice_id" ] )

            assert allocated_voice_ids[ 0 ] != allocated_voice_ids[ 1 ], (
                f"Two sessions got the same voice: {allocated_voice_ids}"
            )

        finally:
            # Best-effort: release + delete bridges
            for sid, path in zip( sids, bridges ):
                try:
                    requests.post(
                        f"{BASE_URL}/api/cosa-voice/voice-persona/{sid}/release",
                        headers = { "Authorization": f"Bearer {auth_token}" },
                        timeout = 2
                    )
                except Exception:
                    pass
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
