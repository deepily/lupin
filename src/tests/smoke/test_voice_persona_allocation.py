"""
Smoke test for the voice persona allocation HTTP endpoints.

Verifies the contract that the SessionStart hook depends on:
    POST /api/cosa-voice/voice-persona/{session_id}/allocate
    POST /api/cosa-voice/voice-persona/{session_id}/release
    GET  /api/cosa-voice/voice-persona/pool

This test creates a synthetic bridge file in the session-bridge directory the
live server reads, POSTs /allocate, verifies the bridge gained a voice_persona
field, then cleans up. That directory is resolved by _resolve_session_dir()
below and then CHECKED against the server by the `server_sees_session_dir`
fixture — the tests that write bridges skip, with the mismatch named, rather
than fail when this process and the server do not share one directory.

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


def _resolve_session_dir() -> Path:
    """
    The directory this test must write its synthetic bridges into: the one the
    RUNNING SERVER reads, not the one this pytest process's home happens to be.

    Fixed 2026-08-26. This was `Path.home() / ".claude" / "sessions"`, which made
    the result depend on which account invoked pytest. Measured on the dev box:
    as the account whose home the server mounts, 8 passed; with HOME pointed
    somewhere else, 6 of the same 8 failed with 404, because the bridges landed
    where the server never looks. A test whose result tracks the caller's home
    directory is not testing the endpoints.

    Resolution order, most specific first:
      1. LUPIN_HOST_SESSIONS_DIR — the HOST side of the docker-compose bind mount
         that gives the container its ~/.claude/sessions (docker-compose.yml, the
         `source:` of the lupin-rest-dev sessions bind). This is the only value
         that is correct when the caller's home and the server's differ.
      2. sessions_dir() — the same single resolution point every server-side
         reader uses, so we honour LUPIN_HOOK_SESSIONS_DIR and fall back to
         ~/.claude/sessions exactly the way the server does.

    Neither is a guarantee, which is why `server_sees_session_dir` below checks
    contact with the server instead of trusting this function.

    Ensures:
        - returns a Path; never raises
    """
    host_side = os.environ.get( "LUPIN_HOST_SESSIONS_DIR" )
    if host_side:
        return Path( host_side )
    from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir
    return sessions_dir()


SESSION_DIR = _resolve_session_dir()


# ── configured-pool readers (added 2026-08-26) ──────────────────────────────
# The pool roster used to be hardcoded in three places in this file. It has
# changed at least twice (6 names -> 14, and the overflow persona moved from
# sam to arnold on 2026-05-19), and each change reddened these tests without
# anything being wrong. Read the same INI keys the server reads instead.

def _configured_pool_names() -> list[ str ]:
    """
    Ensures:
        - returns the persona names from `cc session voice persona pool`,
          stripped, in config order
    """
    from cosa.config.configuration_manager import ConfigurationManager
    raw = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get( "cc session voice persona pool" )
    return [ n.strip() for n in raw.split( "," ) if n.strip() ]


def _configured_overflow_name() -> str:
    """
    Ensures:
        - returns `cc session voice persona overflow name`, lowercased
          (the persona reserved for pool exhaustion — never an allocatable member)
    """
    from cosa.config.configuration_manager import ConfigurationManager
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get(
        "cc session voice persona overflow name" ).strip().lower()


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


# ── Contact check: does the server actually read the directory we write? ────

@pytest.fixture( scope="module" )
def server_sees_session_dir( auth_token ):
    """
    Prove, once per module, that a bridge written to SESSION_DIR is visible to
    the server — and skip with a usable message when it is not.

    Added 2026-08-26. _resolve_session_dir() is a better guess than Path.home()
    was, but it is still a guess: it cannot see a container that mounts a
    different host directory, a server running as another account, or a bind
    mount that is not what the compose file says. So this asks the server
    instead of assuming. It writes a throwaway bridge and reads it back through
    GET /voice-persona/{session_id}, which 404s when the server cannot find the
    bridge and allocates nothing, so the probe costs no persona and mutates no
    shared state.

    A skip here means "this box cannot run these tests", which is an honest
    result. A pass means the two sides genuinely share a directory, not that
    they happened to match.

    Ensures:
        - returns SESSION_DIR when the server can see a bridge written there
        - pytest.skip() naming both the directory and the remedy otherwise
        - removes its probe bridge either way
    """
    SESSION_DIR.mkdir( parents=True, exist_ok=True )
    probe_sid  = str( uuid.uuid4() )
    probe_path = SESSION_DIR / f"cc-{os.getpid() + 96000}.json"
    try:
        with open( probe_path, "w" ) as f:
            json.dump(
                {
                    "session_id"        : probe_sid,
                    "stable_session_id" : probe_sid,
                    "session_ids"       : [ probe_sid ],
                    "cwd"               : "/tmp",
                    "cc_pid"            : os.getpid(),
                    "hook_ppid"         : 1
                },
                f
            )
        try:
            resp = requests.get(
                f"{BASE_URL}/api/cosa-voice/voice-persona/{probe_sid}",
                headers = { "Authorization": f"Bearer {auth_token}" },
                timeout = 5
            )
        except requests.exceptions.ConnectionError:
            pytest.skip( f"Server not reachable at {BASE_URL}" )

        if resp.status_code == 404:
            pytest.skip(
                "SKIPPED — this test process and the server are reading different "
                "session-bridge directories, so these tests cannot say anything about "
                "the endpoints here.\n"
                f"  WHAT HAPPENED : wrote a bridge to {probe_path}, then asked the server "
                f"for that session and got 404.\n"
                f"  WHY           : this process resolved the directory to {SESSION_DIR} "
                f"(HOME={os.path.expanduser( '~' )}). The server reads the host side of the "
                "docker-compose bind mount that supplies its ~/.claude/sessions, which "
                "defaults to /home/rruiz/.claude/sessions.\n"
                "  HOW TO FIX IT : point both at one directory, then re-run — either run "
                "pytest as the account whose home the server mounts, or export "
                "LUPIN_HOST_SESSIONS_DIR=<the host path in the `source:` of the "
                "lupin-rest-dev sessions bind in docker-compose.yml>. "
                "LUPIN_HOST_SESSIONS_DIR is read first by _resolve_session_dir() precisely "
                "so the two sides can be reconciled without editing either one."
            )
        assert resp.status_code == 200, (
            f"session-dir contact probe got an unexpected {resp.status_code}: {resp.text}"
        )
        return SESSION_DIR
    finally:
        try:
            probe_path.unlink()
        except FileNotFoundError:
            pass


# ── Bridge fixture: create a synthetic bridge in the real SESSION_DIR ────────

@pytest.fixture
def synthetic_bridge( server_sees_session_dir ):
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
        "cc_pid"            : test_pid,        # alive for liveness check
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

    def test_get_pool_returns_the_configured_pool( self, auth_token ):
        """
        GET /pool returns exactly the personas named by the INI pool key.

        Refreshed 2026-08-26. This asserted a hardcoded 6-name pool
        {maria, mr radio, Rachel, Tiberius, Rio, Arnold}. On 2026-05-19 (merged
        in 26898e1e) Sam was promoted out of the reserved overflow slot into the
        regular pool, Arnold took over the overflow slot, and the pool grew to
        14 names. Hardcoding the roster meant every later addition reddened this
        test, so it now reads the same config key the server reads
        (`cc session voice persona pool`) and asserts the API agrees with it —
        which is the actual contract. The overflow persona
        (`cc session voice persona overflow name`, currently arnold) must NOT
        appear in the allocatable pool.
        """
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
        # The API's pool must equal the configured pool, name for name.
        pool_names    = [ p[ "name" ] for p in body[ "pool" ] ]
        expected      = _configured_pool_names()
        assert set( pool_names ) == set( expected ), (
            f"pool disagrees with `cc session voice persona pool`:\n"
            f"  api    = {sorted( pool_names )}\n"
            f"  config = {sorted( expected )}"
        )
        # The overflow persona is reserved — it is never an allocatable member.
        overflow = _configured_overflow_name()
        assert overflow not in { n.lower() for n in pool_names }, (
            f"overflow persona {overflow!r} must NOT be in the allocatable pool; got {pool_names}"
        )


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
        # Refreshed 2026-08-26: was a hardcoded 6-name set, and a Sam-voice-id
        # exclusion. Sam joined the regular pool on 2026-05-19 (26898e1e), so his
        # voice IS allocatable now; the reserved persona is whatever
        # `cc session voice persona overflow name` points at (currently arnold).
        assert persona[ "name" ] in set( _configured_pool_names() ), (
            f"allocated {persona[ 'name' ]!r}, which is not in the configured pool "
            f"{sorted( _configured_pool_names() )}"
        )
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

    def test_pool_exhaustion_returns_the_overflow_persona( self, auth_token, server_sees_session_dir ):
        """
        Saturate the pool with synthetic bridges; the spill must land on the
        configured overflow persona, not on a hash-borrowed pool member.

        Refreshed 2026-08-26. This asserted the spill lands on SAM and that
        every Sam allocation carries `overflow: True`. Both statements were
        true when written and are false now: on 2026-05-19 (merged in 26898e1e)
        Sam was promoted into the regular pool and ARNOLD took the overflow
        slot, which is why the old version died on `KeyError: 'overflow'` — it
        was reading that key off an ordinary pool allocation. The overflow
        persona is now a config pointer
        (`cc session voice persona overflow name`), so this reads it rather
        than naming anyone.

        The bridge count is also derived now: the pool grew 6 -> 14, so a fixed
        8 bridges no longer exhausts it. We allocate len(pool) + 2.

        See: src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md
        """
        SESSION_DIR.mkdir( parents=True, exist_ok=True )
        test_pid = os.getpid()

        # len(pool) + 2 synthetic bridges — exhausts the CONFIGURED pool with two
        # to spare even if a couple of personas are already held by live sessions.
        overflow_name = _configured_overflow_name()
        n_bridges     = len( _configured_pool_names() ) + 2
        sids    = [ str( uuid.uuid4() ) for _ in range( n_bridges ) ]
        bridges = [ SESSION_DIR / f"cc-{test_pid + 93000 + i}.json" for i in range( n_bridges ) ]
        try:
            for sid, path in zip( sids, bridges ):
                with open( path, "w" ) as f:
                    json.dump(
                        {
                            "session_id"        : sid,
                            "stable_session_id" : sid,
                            "session_ids"       : [ sid ],
                            "cwd"               : "/tmp",
                            "cc_pid"            : test_pid,  # alive
                            "hook_ppid"         : 1
                        },
                        f
                    )

            personas = []
            for sid in sids:
                resp = requests.post(
                    f"{BASE_URL}/api/cosa-voice/voice-persona/{sid}/allocate",
                    headers = { "Authorization": f"Bearer {auth_token}" },
                    timeout = 5
                )
                assert resp.status_code == 200, f"/allocate failed: {resp.status_code} {resp.text}"
                personas.append( resp.json()[ "voice_persona" ] )

            # Spilling past the pool must land on the configured overflow persona.
            overflow_allocations = [ p for p in personas
                                     if ( p.get( "name" ) or "" ).lower() == overflow_name ]
            assert overflow_allocations, (
                f"Expected at least one {overflow_name!r} overflow allocation when saturating "
                f"the {len( _configured_pool_names() )}-voice pool with {n_bridges} synthetic "
                f"bridges; got: {[ p.get( 'name' ) for p in personas ]}"
            )
            # Overflow supplants hash-borrowing — an overflow allocation is never borrowed.
            assert all( p.get( "borrowed", False ) is False for p in overflow_allocations ), (
                f"overflow allocations should have borrowed=False; got: {overflow_allocations}"
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

    def test_two_concurrent_sessions_get_distinct_voices( self, auth_token, server_sees_session_dir ):
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
                            "cc_pid"            : test_pid,  # alive
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
