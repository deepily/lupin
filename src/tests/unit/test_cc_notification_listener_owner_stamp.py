"""
Unit tests for CCNotificationListener._stamp_owner_user_id_on_bridge —
writer-side follow-up to the 2026-05-14 Option C design.

Per src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md

Covers four scenarios:
    1. Happy path: get_owner_credentials succeeds, /auth/login returns user.id,
       set_owner_user_id is called with that UUID.
    2. get_owner_credentials raises FileNotFoundError → silently returns,
       no /auth/login attempt, no set_owner_user_id call.
    3. get_owner_credentials raises ValueError → same as #2.
    4. /auth/login response has no user.id → silently returns,
       no set_owner_user_id call.
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def listener():
    """A CCNotificationListener instance suitable for stamp-method unit tests."""
    return CCNotificationListener(
        email           = "service@lupin.deepily.ai",
        password        = "service-pass",
        session_id_hash = "abc12345",
        host            = "localhost",
        port            = 7999,
        debug           = False,
        verbose         = False,
    )


def _build_login_response( user_id ):
    """Build a fake urlopen context-manager whose .read() returns the JSON body."""
    body = json.dumps( { "user": { "id": user_id } } ).encode( "utf-8" )
    resp = MagicMock()
    resp.read.return_value = body
    cm = MagicMock()
    cm.__enter__ = MagicMock( return_value=resp )
    cm.__exit__  = MagicMock( return_value=False )
    return cm


# ═════════════════════════════════════════════════════════════════════════════
# Test cases
# ═════════════════════════════════════════════════════════════════════════════

class TestStampOwnerUserIdOnBridge:
    """4 scenarios — happy path + 3 silent-fallback paths."""

    def test_happy_path_stamps_owner_user_id( self, listener ):
        """get_owner_credentials → /auth/login → set_owner_user_id stamped."""
        owner_uuid = "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"

        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials",
            return_value=( "owner@example.com", "owner-pass" )
        ), patch(
            "urllib.request.urlopen",
            return_value=_build_login_response( owner_uuid )
        ), patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.set_owner_user_id",
            return_value=True
        ) as mock_set, patch.object( listener, "_log" ):
            listener._stamp_owner_user_id_on_bridge()

        # set_owner_user_id called once with the listener's session hash + resolved UUID
        mock_set.assert_called_once_with( "abc12345", owner_uuid )

    def test_no_creds_file_returns_silently( self, listener ):
        """get_owner_credentials raises FileNotFoundError → no /auth/login, no stamp."""
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials",
            side_effect=FileNotFoundError( "~/.lupin/config not found" )
        ), patch( "urllib.request.urlopen" ) as mock_urlopen, patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.set_owner_user_id"
        ) as mock_set, patch.object( listener, "_log" ) as mock_log:
            listener._stamp_owner_user_id_on_bridge()

        # No /auth/login attempted, no stamp attempted
        mock_urlopen.assert_not_called()
        mock_set.assert_not_called()
        # Log message captures the skip reason
        assert any(
            "owner_user_id stamp skipped" in str( call ) and "no owner credentials" in str( call )
            for call in mock_log.call_args_list
        )

    def test_missing_owner_section_returns_silently( self, listener ):
        """get_owner_credentials raises ValueError → silent fallback, no stamp."""
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials",
            side_effect=ValueError( "No [owner] section found" )
        ), patch( "urllib.request.urlopen" ) as mock_urlopen, patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.set_owner_user_id"
        ) as mock_set, patch.object( listener, "_log" ) as mock_log:
            listener._stamp_owner_user_id_on_bridge()

        mock_urlopen.assert_not_called()
        mock_set.assert_not_called()
        assert any(
            "owner_user_id stamp skipped" in str( call ) and "no owner credentials" in str( call )
            for call in mock_log.call_args_list
        )

    def test_login_response_missing_user_id_returns_silently( self, listener ):
        """/auth/login returns a payload with no user.id → no stamp call."""
        # Build a response whose JSON has no 'user' key at all
        empty_body = json.dumps( {} ).encode( "utf-8" )
        empty_resp = MagicMock()
        empty_resp.read.return_value = empty_body
        empty_cm = MagicMock()
        empty_cm.__enter__ = MagicMock( return_value=empty_resp )
        empty_cm.__exit__  = MagicMock( return_value=False )

        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials",
            return_value=( "owner@example.com", "owner-pass" )
        ), patch(
            "urllib.request.urlopen",
            return_value=empty_cm
        ), patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.set_owner_user_id"
        ) as mock_set, patch.object( listener, "_log" ) as mock_log:
            listener._stamp_owner_user_id_on_bridge()

        # Login fired, but stamp did NOT (no user.id in response)
        mock_set.assert_not_called()
        assert any(
            "no user.id in /auth/login response" in str( call )
            for call in mock_log.call_args_list
        )
