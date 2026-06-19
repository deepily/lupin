"""
WS-frame capture E2E for the 2026-04-29 ad-hoc-event cleanup migration.

Verifies that the four router callsites previously emitting top-level WS events
now route through the canonical notification subsystem with custom `type` values.

Specifically asserts:
    1. POST /voice-persona/{sid}/allocate produces a `notification_queue_update`
       envelope carrying `notification.type === "voice_persona_assigned"` and
       `notification.voice_persona` populated.
    2. POST /voice-persona/{sid}/release produces a `notification_queue_update`
       envelope carrying `notification.type === "voice_persona_released"`.
    3. POST /conversation-mode/{sid} produces a `notification_queue_update`
       envelope carrying `notification.type === "conversation_mode_changed"` and
       `notification.payload.active` matching the toggled state.
    4. NO top-level WS frame with `type ∈ { "voice_persona_assigned",
       "voice_persona_released", "conversation_mode_changed" }` arrives — the
       legacy ad-hoc channel must be silent.

Venue: :7999 (AI-discretionary). Test creates a synthetic bridge file inside
the real ~/.claude/sessions/ directory under a unique PID alias and tears down
at end. WS captures are non-destructive (read-only on the user's notification
channel).

See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
import requests
import websockets


BASE_URL    = os.environ.get( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
WS_BASE     = BASE_URL.replace( "http://", "ws://" ).replace( "https://", "wss://" )
SESSION_DIR = Path.home() / ".claude" / "sessions"

# Custom notification types introduced by the 2026-04-29 migration
MIGRATED_TYPES = {
    "voice_persona_assigned",
    "voice_persona_released",
    "conversation_mode_changed"
}


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


@pytest.fixture
def synthetic_bridge():
    """
    Create a synthetic CC bridge file with a unique session_id under the real
    ~/.claude/sessions/ directory. PID alias is the test-process PID + 92000
    so the dead-PID filter does not skip it.

    Yields ( cosa_session_id, bridge_path ). Tears down on exit.
    """
    SESSION_DIR.mkdir( parents=True, exist_ok=True )
    session_id  = str( uuid.uuid4() )
    test_pid    = os.getpid()
    pid_alias   = test_pid + 92000
    bridge_path = SESSION_DIR / f"cc-{pid_alias}.json"

    if bridge_path.exists():
        pytest.skip( f"Bridge collision at {bridge_path}" )

    bridge_data = {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "session_ids"       : [ session_id ],
        "transcript_path"   : "/tmp/synthetic-transcript.jsonl",
        "cwd"               : "/tmp",
        "cc_pid"            : test_pid,
        "hook_ppid"         : 1,
        "tmux_session"      : None
    }
    with open( bridge_path, "w" ) as f:
        json.dump( bridge_data, f )

    yield session_id, bridge_path

    try:
        bridge_path.unlink()
    except FileNotFoundError:
        pass


# ── WS helpers ───────────────────────────────────────────────────────────────

async def _ws_capture(
    auth_token,
    trigger_coro,
    capture_seconds = 2.0,
    ws_session_id   = None
):
    """
    Connect to /ws/queue/{ws_session_id}, authenticate as the test user with
    `notification_queue_update` subscribed, run trigger_coro (the action that
    should produce notifications), then drain frames for capture_seconds.

    Returns the list of received envelopes (parsed JSON dicts), in order.
    """
    if ws_session_id is None:
        ws_session_id = f"ws-test-{uuid.uuid4().hex[:8]}"
    encoded = quote( ws_session_id )
    uri     = f"{WS_BASE}/ws/queue/{encoded}"

    captured = []

    async with websockets.connect( uri ) as ws:
        await ws.send( json.dumps( {
            "type"              : "auth_request",
            "token"             : auth_token,
            "session_id"        : ws_session_id,
            "subscribed_events" : [
                "notification_queue_update",
                "auth_success",
                "auth_error",
                # Legacy event names — left here so we can assert they DON'T arrive.
                "voice_persona_assigned",
                "voice_persona_released",
                "conversation_mode_changed"
            ]
        } ) )

        # Drain auth_success
        try:
            auth_resp = await asyncio.wait_for( ws.recv(), timeout=3.0 )
            captured.append( json.loads( auth_resp ) )
        except asyncio.TimeoutError:
            pytest.fail( "WS auth response timed out" )

        # Fire the trigger and start capturing
        await trigger_coro()

        # Drain frames for capture_seconds
        deadline = asyncio.get_event_loop().time() + capture_seconds
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                frame = await asyncio.wait_for( ws.recv(), timeout=remaining )
                captured.append( json.loads( frame ) )
            except asyncio.TimeoutError:
                break
            except Exception:
                break

    return captured


def _http_post( path, auth_token, json_body=None ):
    return requests.post(
        f"{BASE_URL}{path}",
        headers = { "Authorization": f"Bearer {auth_token}" },
        json    = json_body,
        timeout = 5
    )


def _migrated_type_envelopes( captured ):
    """Filter captured envelopes to those carrying notification.type ∈ MIGRATED_TYPES."""
    out = []
    for env in captured:
        if env.get( "type" ) != "notification_queue_update":
            continue
        notif = env.get( "notification" ) or {}
        if notif.get( "type" ) in MIGRATED_TYPES:
            out.append( env )
    return out


def _illegal_top_level_frames( captured ):
    """Captured frames whose top-level type is one of the migrated names — should be empty."""
    return [ env for env in captured if env.get( "type" ) in MIGRATED_TYPES ]


# ── Tests ────────────────────────────────────────────────────────────────────

class TestVoicePersonaAssignedRoutedThroughNotificationSubsystem:

    @pytest.mark.asyncio
    async def test_allocate_emits_voice_persona_assigned_notification( self, auth_token, synthetic_bridge ):
        """POST /allocate produces a notification_queue_update with type=voice_persona_assigned."""
        session_id, _ = synthetic_bridge

        async def trigger():
            # requests is sync; run in executor to keep the event loop responsive
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _http_post( f"/api/cosa-voice/voice-persona/{session_id}/allocate", auth_token )
            )

        captured = await _ws_capture( auth_token, trigger, capture_seconds=3.0 )

        # Migrated event arrives via the canonical envelope
        migrated = _migrated_type_envelopes( captured )
        matching = [ env for env in migrated
                     if env[ "notification" ][ "type" ] == "voice_persona_assigned" ]
        assert len( matching ) >= 1, (
            f"Expected at least one notification_queue_update with "
            f"notification.type=voice_persona_assigned; captured types: "
            f"{[ e.get('type') for e in captured ]}"
        )

        # Persona payload populated
        notif = matching[ 0 ][ "notification" ]
        assert notif.get( "voice_persona" ) is not None
        assert notif[ "voice_persona" ].get( "voice_id" )

        # No legacy top-level frame
        assert _illegal_top_level_frames( captured ) == [], (
            "Legacy top-level WS event leaked through — migration incomplete"
        )

    @pytest.mark.asyncio
    async def test_release_emits_voice_persona_released_notification( self, auth_token, synthetic_bridge ):
        """POST /release produces a notification_queue_update with type=voice_persona_released."""
        session_id, _ = synthetic_bridge

        # Allocate first (sync, outside the WS capture)
        _http_post( f"/api/cosa-voice/voice-persona/{session_id}/allocate", auth_token )

        async def trigger():
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _http_post( f"/api/cosa-voice/voice-persona/{session_id}/release", auth_token )
            )

        captured = await _ws_capture( auth_token, trigger, capture_seconds=3.0 )

        migrated = _migrated_type_envelopes( captured )
        matching = [ env for env in migrated
                     if env[ "notification" ][ "type" ] == "voice_persona_released" ]
        assert len( matching ) >= 1, (
            f"Expected notification_queue_update with type=voice_persona_released; "
            f"got types: {[ e.get('type') for e in captured ]}"
        )

        assert _illegal_top_level_frames( captured ) == []


class TestConversationModeChangedRoutedThroughNotificationSubsystem:

    @pytest.mark.asyncio
    async def test_activate_emits_conversation_mode_changed_notification( self, auth_token, synthetic_bridge ):
        """POST /conversation-mode active=True produces a notification with payload.active=True for OUR session.

        Note: activation triggers mutex-displacement of any other active conversation-mode sessions.
        Those displace events also fire conversation_mode_changed notifications (with displaced=True,
        active=False). We assert specifically on OUR session's activation event by filtering
        notification.payload.session_id == our session_id.
        """
        session_id, _ = synthetic_bridge

        async def trigger():
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _http_post(
                    f"/api/cosa-voice/conversation-mode/{session_id}",
                    auth_token,
                    json_body={ "active": True }
                )
            )

        captured = await _ws_capture( auth_token, trigger, capture_seconds=5.0 )

        migrated = _migrated_type_envelopes( captured )
        # Filter to OUR session's notification (mutex displacement may have produced
        # additional conversation_mode_changed notifications for other sessions)
        ours = [ env for env in migrated
                 if env[ "notification" ][ "type" ] == "conversation_mode_changed"
                 and env[ "notification" ].get( "payload", {} ).get( "session_id" ) == session_id ]
        assert len( ours ) >= 1, (
            f"Expected notification_queue_update with type=conversation_mode_changed for "
            f"session_id={session_id}; captured: "
            f"{[ ( e.get('type'), e.get('notification', {}).get('type'), e.get('notification', {}).get('payload', {}).get('session_id') ) for e in captured ]}"
        )

        notif = ours[ 0 ][ "notification" ]
        assert notif.get( "payload" ) is not None
        assert notif[ "payload" ].get( "active" ) is True
        # Activation event for our session must NOT be a displacement event
        assert notif[ "payload" ].get( "displaced" ) is not True

        assert _illegal_top_level_frames( captured ) == []

        # Cleanup — flip back off so we don't leave the bridge active
        _http_post(
            f"/api/cosa-voice/conversation-mode/{session_id}",
            auth_token,
            json_body={ "active": False }
        )

    @pytest.mark.asyncio
    async def test_senders_visible_carries_voice_persona( self, auth_token ):
        """
        Layer B verification: GET /api/notifications/senders-visible/{email} now stamps
        `voice_persona` on every sender entry (resolved via _voice_persona_for_sender_id).
        Each sender dict must have a `voice_persona` key (value may be null when no
        bridge persona is set for the sender's session).

        See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md §10
        """
        email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
        resp  = requests.get(
            f"{BASE_URL}/api/notifications/senders-visible/{email}",
            headers = { "Authorization": f"Bearer {auth_token}" },
            timeout = 10
        )
        assert resp.status_code == 200, f"senders-visible failed: {resp.status_code} {resp.text}"
        senders = resp.json()
        assert isinstance( senders, list )

        # If user has any notification history, every entry must have the key
        for sender in senders:
            assert "voice_persona" in sender, (
                f"Layer B regression: sender entry missing voice_persona key: {sender}"
            )
            # voice_persona is either null (no bridge persona) or a dict with name + voice_id
            persona = sender[ "voice_persona" ]
            if persona is not None:
                assert "name" in persona
                assert "voice_id" in persona

    @pytest.mark.asyncio
    async def test_deactivate_emits_conversation_mode_changed_with_active_false( self, auth_token, synthetic_bridge ):
        """POST /conversation-mode active=False produces a notification with payload.active=False."""
        session_id, _ = synthetic_bridge

        # Pre-activate (sync)
        _http_post(
            f"/api/cosa-voice/conversation-mode/{session_id}",
            auth_token,
            json_body={ "active": True }
        )

        async def trigger():
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _http_post(
                    f"/api/cosa-voice/conversation-mode/{session_id}",
                    auth_token,
                    json_body={ "active": False }
                )
            )

        captured = await _ws_capture( auth_token, trigger, capture_seconds=3.0 )

        migrated = _migrated_type_envelopes( captured )
        matching = [ env for env in migrated
                     if env[ "notification" ][ "type" ] == "conversation_mode_changed"
                     and env[ "notification" ].get( "payload", {} ).get( "active" ) is False ]
        assert len( matching ) >= 1, (
            f"Expected conversation_mode_changed notification with payload.active=False; "
            f"got: {[ ( e.get('type'), e.get('notification', {}).get('type'), e.get('notification', {}).get('payload') ) for e in captured ]}"
        )

        assert _illegal_top_level_frames( captured ) == []
