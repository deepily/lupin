#!/usr/bin/env python3
"""
Unit tests for the cosa-voice conversation mode router.

Tests the GET / POST endpoints at /api/cosa-voice/speakerphone/{session_id}:
    - GET reads speakerphone_on from the session bridge
    - POST writes the flag AND queues a speakerphone_changed notification
    - 404 when bridge file is missing
    - 500 when bridge found but write fails

The router was migrated 2026-04-29 from ad-hoc `ws_manager.emit_to_user(...)`
calls to the canonical notification subsystem via `notification_queue.push_notification(
type="speakerphone_changed", payload={...})`. Tests verify the migrated
contract: a single push_notification call carrying the payload dict, instead
of a top-level WS event with positional args. See:
    src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md

Uses a tmp SESSION_DIR via patch + a mock NotificationFifoQueue so tests don't
mutate real bridge files or require a live server.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_session_file( sessions_dir, pid, session_id ):
    path = sessions_dir / f"cc-{pid}.json"
    data = {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : "/tmp",
        "ppid"              : os.getpid(),
    }
    with open( path, "w" ) as f:
        json.dump( data, f )
    return path


def _push_kwargs( mock_nq, call_index=0 ):
    """Extract kwargs from the Nth push_notification call on a mock queue."""
    return mock_nq.push_notification.call_args_list[ call_index ].kwargs


# ── Mode mock — file-wide default ────────────────────────────────────────────
# Existing tests inherited from the conversation-mode era assume monopoly /
# displacement semantics, which the speakerphone refactor preserves only in
# SOLO mode. Default the mode to "solo" for every test in this file so legacy
# behavior is exercised; chorus-specific behavior is tested separately at the
# bottom of this file via per-test mode override.

@pytest.fixture( autouse=True )
def _default_solo_mode():
    with patch( "cosa.utils.util.get_tts_interaction_mode", return_value="solo" ):
        yield


# ── Tests: GET endpoint ──────────────────────────────────────────────────────

class TestGetSpeakerphoneEndpoint:

    @pytest.mark.asyncio
    async def test_returns_default_false_when_flag_missing( self ):
        """GET reads False when bridge has no speakerphone_on field."""
        from cosa.rest.routers.speakerphone import get_speakerphone_endpoint

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "endpoint-1111-2222-3333-444455556666"
            _write_session_file( sessions_dir, os.getpid(), sid )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await get_speakerphone_endpoint( sid, authenticated_user_id="user@test.com" )

            body = json.loads( resp.body.decode() )
            assert body == { "session_id": sid, "on": False }

    @pytest.mark.asyncio
    async def test_returns_true_when_flag_set( self ):
        """GET reads True when bridge has speakerphone_on=True."""
        from cosa.rest.routers.speakerphone import get_speakerphone_endpoint

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "endpoint-2222-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )
            # Pre-set the flag
            with open( path ) as f:
                data = json.load( f )
            data[ "speakerphone_on" ] = True
            with open( path, "w" ) as f:
                json.dump( data, f )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await get_speakerphone_endpoint( sid, authenticated_user_id="user@test.com" )

            body = json.loads( resp.body.decode() )
            assert body == { "session_id": sid, "on": True }

    @pytest.mark.asyncio
    async def test_returns_404_when_bridge_missing( self ):
        """GET raises 404 when session_id does not match any bridge file."""
        from cosa.rest.routers.speakerphone import get_speakerphone_endpoint

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                with pytest.raises( HTTPException ) as exc_info:
                    await get_speakerphone_endpoint( "nonexistent", authenticated_user_id="user@test.com" )

            assert exc_info.value.status_code == 404


# ── Tests: POST endpoint ─────────────────────────────────────────────────────

class TestSetSpeakerphoneEndpoint:

    @pytest.mark.asyncio
    async def test_post_writes_bridge_and_pushes_notification( self ):
        """POST writes flag to bridge and pushes speakerphone_changed notification."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post1111-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Bridge mutated
            with open( path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is True

            # Single push_notification call carrying the migrated shape
            mock_nq.push_notification.assert_called_once()
            kw = _push_kwargs( mock_nq )
            assert kw[ "type"     ] == "speakerphone_changed"
            assert kw[ "user_id"  ] == "user@test.com"
            assert kw[ "payload"  ] == { "session_id": sid, "on": True }
            assert kw[ "suppress_ding" ]      is True
            assert kw[ "response_requested" ] is False

            # Response shape
            body = json.loads( resp.body.decode() )
            assert body[ "session_id" ] == sid
            assert body[ "on" ] is True
            assert body[ "broadcast_delivered" ] is True

    @pytest.mark.asyncio
    async def test_post_with_active_false_round_trip( self ):
        """POST on=False clears the flag and pushes a notification."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post2222-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )
            with open( path ) as f:
                data = json.load( f )
            data[ "speakerphone_on" ] = True
            with open( path, "w" ) as f:
                json.dump( data, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid,
                    body=SpeakerphoneBody( on=False ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            with open( path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is False

            body = json.loads( resp.body.decode() )
            assert body[ "on" ] is False

    @pytest.mark.asyncio
    async def test_post_returns_404_when_bridge_missing( self ):
        """POST returns 404 when no bridge matches session_id."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                with pytest.raises( HTTPException ) as exc_info:
                    await set_speakerphone_endpoint(
                        session_id="nonexistent",
                        body=SpeakerphoneBody( on=True ),
                        authenticated_user_id="user@test.com",
                        notification_queue=mock_nq
                    )

            assert exc_info.value.status_code == 404
            mock_nq.push_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_succeeds_even_if_push_fails( self ):
        """POST is canonical write; notification-push failure is logged but does not fail the request."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post3333-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )

            mock_nq = MagicMock()
            mock_nq.push_notification.side_effect = RuntimeError( "queue dispatch broken" )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Bridge write still happened
            with open( path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is True

            body = json.loads( resp.body.decode() )
            assert body[ "on" ] is True
            assert body[ "broadcast_delivered" ] is False


# ── Tests: auto-displace (mutual exclusion across sessions) ──────────────────


class TestAutoDisplaceOnActivate:
    """
    The mutex contract: when session B activates, ANY other bridge with
    speakerphone_on=true must be flipped off, with a separate
    speakerphone_changed notification carrying displaced=True and
    displaced_by=<B's session_id> in the payload. The activate-then-displace
    sequence is serialized by an asyncio.Lock at module scope.
    """

    @pytest.mark.asyncio
    async def test_activate_displaces_existing_active_session( self ):
        """A is active; activate B → A flipped off + displaced notification + B activated."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "displa-a1-1111-2222-3333-444455556666"
            sid_b = "displa-b2-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, 70001, sid_a )
            path_b = _write_session_file( sessions_dir, 70002, sid_b )

            # Pre-set A active
            with open( path_a ) as f:
                data_a = json.load( f )
            data_a[ "speakerphone_on" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data_a, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid_b,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # A's bridge flipped off
            with open( path_a ) as f:
                data_a = json.load( f )
            assert data_a[ "speakerphone_on" ] is False

            # B's bridge flipped on
            with open( path_b ) as f:
                data_b = json.load( f )
            assert data_b[ "speakerphone_on" ] is True

            # Three push_notification calls per displacement:
            #   1) speakerphone_changed (displaced=True) — UI sync for A
            #   2) user_initiated_message (action:disable_speakerphone) — listener
            #      injects deactivation reminder into A's tmux pane so the
            #      model's in-context state catches up to the bridge flip
            #   3) activate for B
            assert mock_nq.push_notification.call_count == 3

            # First call: displaced notification for A
            kw_first = _push_kwargs( mock_nq, 0 )
            assert kw_first[ "type"    ] == "speakerphone_changed"
            assert kw_first[ "user_id" ] == "user@test.com"
            assert kw_first[ "payload" ] == {
                "session_id"   : sid_a,
                "on"       : False,
                "displaced"    : True,
                "displaced_by" : sid_b
            }

            # Second call: action push for A's listener
            kw_action = _push_kwargs( mock_nq, 1 )
            assert kw_action[ "type"   ] == "user_initiated_message"
            assert kw_action[ "title"  ] == "action:disable_speakerphone"
            assert kw_action[ "job_id" ] == sid_a[:8]

            # Third call: B's activate notification (no displaced flag)
            kw_third = _push_kwargs( mock_nq, 2 )
            assert kw_third[ "type"    ] == "speakerphone_changed"
            assert kw_third[ "payload" ] == { "session_id": sid_b, "on": True }

            # Response payload includes the displaced session id
            body = json.loads( resp.body.decode() )
            assert body[ "session_id" ] == sid_b
            assert body[ "on" ] is True
            assert body[ "displaced_sessions" ] == [ sid_a ]

    @pytest.mark.asyncio
    async def test_activate_with_no_other_active_pushes_only_activate( self ):
        """No other bridges active → only B's activate notification pushed; displaced_sessions is empty."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_b = "soloact-1-1111-2222-3333-444455556666"
            _write_session_file( sessions_dir, os.getpid(), sid_b )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid_b,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Exactly one push — the activate
            assert mock_nq.push_notification.call_count == 1
            kw = _push_kwargs( mock_nq )
            assert kw[ "payload" ] == { "session_id": sid_b, "on": True }

            body = json.loads( resp.body.decode() )
            assert body[ "displaced_sessions" ] == []

    @pytest.mark.asyncio
    async def test_activate_displaces_multiple_active_sessions( self ):
        """Three pre-active sessions → all three displaced, four total pushes (3 displaced + 1 activate)."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sids = [
                "multi-a1-1111-2222-3333-444455556666",
                "multi-a2-1111-2222-3333-444455556666",
                "multi-a3-1111-2222-3333-444455556666",
            ]
            sid_b = "multi-b9-1111-2222-3333-444455556666"
            paths = []
            for i, sid in enumerate( sids ):
                p = _write_session_file( sessions_dir, 80001 + i, sid )
                with open( p ) as f:
                    data = json.load( f )
                data[ "speakerphone_on" ] = True
                with open( p, "w" ) as f:
                    json.dump( data, f )
                paths.append( p )
            _write_session_file( sessions_dir, 80100, sid_b )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid_b,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # All three pre-active bridges flipped off
            for p in paths:
                with open( p ) as f:
                    data = json.load( f )
                assert data[ "speakerphone_on" ] is False

            # Per-displaced-session push pair (displaced WS event + action push) ×3
            # plus the final activate push for B = 7 total.
            assert mock_nq.push_notification.call_count == 7

            # Last call is the activate event for B
            last_kw = _push_kwargs( mock_nq, -1 )
            assert last_kw[ "payload" ] == { "session_id": sid_b, "on": True }

            # Action pushes interleaved with displaced pushes — each displaced
            # session got an action:disable_speakerphone targeted at its hash
            action_calls = [
                _push_kwargs( mock_nq, i ) for i in range( 6 )
                if _push_kwargs( mock_nq, i ).get( "title" ) == "action:disable_speakerphone"
            ]
            assert len( action_calls ) == 3
            action_job_ids = sorted( c[ "job_id" ] for c in action_calls )
            assert action_job_ids == sorted( s[:8] for s in sids )

            body = json.loads( resp.body.decode() )
            assert sorted( body[ "displaced_sessions" ] ) == sorted( sids )

    @pytest.mark.asyncio
    async def test_deactivate_pushes_ui_sync_and_self_action( self ):
        """active=false bypasses the lock + scan; pushes UI sync + self-targeted action.

        Two pushes per self-exit:
          1) speakerphone_changed (active=false) — UI sync to all of B's tabs
          2) user_initiated_message (action:disable_speakerphone) — listener
             injects deactivation reminder into B's own tmux pane so the model's
             in-context state catches up to the bridge flip. Mirror of the
             displace branch's per-displaced action push, applied to the
             deactivating session itself.
        """
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "deact1-1-1111-2222-3333-444455556666"
            sid_b = "deact1-2-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, 90001, sid_a )
            _write_session_file( sessions_dir, 90002, sid_b )
            # A is active; we are deactivating B (which is not active) — A must NOT be touched
            with open( path_a ) as f:
                data_a = json.load( f )
            data_a[ "speakerphone_on" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data_a, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid_b,
                    body=SpeakerphoneBody( on=False ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # A is untouched — deactivate path skips the scan
            with open( path_a ) as f:
                data_a = json.load( f )
            assert data_a[ "speakerphone_on" ] is True

            # Two pushes — UI sync, then self-targeted action
            assert mock_nq.push_notification.call_count == 2

            # First call: UI-sync speakerphone_changed for B
            kw_ui = _push_kwargs( mock_nq, 0 )
            assert kw_ui[ "type"    ] == "speakerphone_changed"
            assert kw_ui[ "payload" ] == { "session_id": sid_b, "on": False }

            # Second call: self-targeted action push for B's own listener
            kw_action = _push_kwargs( mock_nq, 1 )
            assert kw_action[ "type"    ] == "user_initiated_message"
            assert kw_action[ "title"   ] == "action:disable_speakerphone"
            assert kw_action[ "job_id"  ] == sid_b[:8]
            assert kw_action[ "payload" ] == { "session_id": sid_b, "reason": "self" }

            body = json.loads( resp.body.decode() )
            assert body[ "on" ] is False
            assert body[ "displaced_sessions" ] == []

    @pytest.mark.asyncio
    async def test_displace_push_failure_does_not_block_activate( self ):
        """If displaced-event push raises, the bridge writes still happen and B still activates."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "wsfail-a-1111-2222-3333-444455556666"
            sid_b = "wsfail-b-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, 70001, sid_a )
            path_b = _write_session_file( sessions_dir, 70002, sid_b )
            with open( path_a ) as f:
                data_a = json.load( f )
            data_a[ "speakerphone_on" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data_a, f )

            # First push (displaced for A) raises; second (action for A) and
            # third (activate for B) succeed. Both displaced-event and action
            # pushes are best-effort — failure of one does not block the other
            # or the activate write.
            mock_nq = MagicMock()
            mock_nq.push_notification.side_effect = [ RuntimeError( "queue ded" ), None, None ]

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid_b,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Both bridge writes succeeded despite push failure
            with open( path_a ) as f:
                assert json.load( f )[ "speakerphone_on" ] is False
            with open( path_b ) as f:
                assert json.load( f )[ "speakerphone_on" ] is True

            body = json.loads( resp.body.decode() )
            assert body[ "on" ] is True
            assert body[ "displaced_sessions" ] == [ sid_a ]

    @pytest.mark.asyncio
    async def test_self_activation_does_not_displace_self( self ):
        """Activating an already-active session is a no-op displacement (exclude_session_id filters it)."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "selfact1-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, os.getpid(), sid_a )
            with open( path_a ) as f:
                data = json.load( f )
            data[ "speakerphone_on" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid_a,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Only one push — self's activate event. No spurious displaced event.
            assert mock_nq.push_notification.call_count == 1

            body = json.loads( resp.body.decode() )
            assert body[ "displaced_sessions" ] == []


# ── Tests: Chorus-mode activation (NEW Phase 3 branch) ──────────────────────

class TestChorusActivation:
    """
    Chorus-mode activate path: NO Lock, NO scan, NO displacement.
    Self is activated, broadcast goes out, response shape preserved
    (displaced_sessions: [] for stability so UI doesn't special-case modes).
    """

    @pytest.mark.asyncio
    async def test_chorus_no_displacement_of_others( self ):
        """In chorus mode, activating session B does NOT touch session A's flag."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody,
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "chorus-a-1111-2222-3333-444455556666"
            sid_b = "chorus-b-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, 90001, sid_a )
            _write_session_file( sessions_dir, 90002, sid_b )

            # Pre-set A active.
            with open( path_a ) as f:
                data_a = json.load( f )
            data_a[ "speakerphone_on" ] = True
            data_a[ "format_version" ] = 2
            with open( path_a, "w" ) as f:
                json.dump( data_a, f )

            mock_nq = MagicMock()
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ), \
                 patch( "cosa.utils.util.get_tts_interaction_mode", return_value="chorus" ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid_b,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            body = json.loads( resp.body.decode() )
            # Self is on.
            assert body[ "on" ] is True
            # Critically: nobody was displaced.
            assert body[ "displaced_sessions" ] == []
            # And A's flag is UNTOUCHED on disk.
            with open( path_a ) as f:
                data_a_after = json.load( f )
            assert data_a_after[ "speakerphone_on" ] is True

    @pytest.mark.asyncio
    async def test_chorus_response_includes_empty_displaced_sessions( self ):
        """Schema stability: response always has displaced_sessions, even when empty."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody,
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "chorus-solo-1111-2222-3333-444455556666"
            _write_session_file( sessions_dir, os.getpid(), sid )

            mock_nq = MagicMock()
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "cosa.utils.util.get_tts_interaction_mode", return_value="chorus" ):
                resp = await set_speakerphone_endpoint(
                    session_id=sid,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            body = json.loads( resp.body.decode() )
            assert "displaced_sessions" in body
            assert body[ "displaced_sessions" ] == []

    @pytest.mark.asyncio
    async def test_chorus_pushes_self_activate_notification( self ):
        """Chorus path still emits speakerphone_changed for self."""
        from cosa.rest.routers.speakerphone import (
            set_speakerphone_endpoint, SpeakerphoneBody,
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "chorus-notif-1-2222-3333-444455556666"
            _write_session_file( sessions_dir, os.getpid(), sid )

            mock_nq = MagicMock()
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "cosa.utils.util.get_tts_interaction_mode", return_value="chorus" ):
                await set_speakerphone_endpoint(
                    session_id=sid,
                    body=SpeakerphoneBody( on=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Exactly one push: self-activate. No displace pushes, no displace-action pushes.
            assert mock_nq.push_notification.call_count == 1
            kw = mock_nq.push_notification.call_args_list[ 0 ].kwargs
            assert kw[ "type" ] == "speakerphone_changed"
            assert kw[ "payload" ] == { "session_id": sid, "on": True }


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
