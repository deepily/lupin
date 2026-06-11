"""
Unit tests for CCNotificationListener._handle_broadcast_received — roster wiring
for the roster-aware directive discrimination hardening (2026-06-11).

The listener supplies `persona_roster` to `broadcast_handler.handle_broadcast`:
name + display_name of every live persona session from
`session_bridge.find_active_voice_persona_sessions()`, deduplicated, with an
EMPTY scan passed as None (no roster signal → roster-blind legacy parse).

All collaborators are patched at their SOURCE modules because the listener
imports them lazily inside the method body.
"""

import pytest
from unittest.mock import MagicMock, patch

from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def listener():
    """A CCNotificationListener instance suitable for broadcast unit tests."""
    return CCNotificationListener(
        email           = "service@lupin.deepily.ai",
        password        = "service-pass",
        session_id_hash = "abc12345",
        host            = "localhost",
        port            = 7999,
        debug           = False,
        verbose         = False,
    )


@pytest.fixture
def notification():
    return { "payload": { "broadcast_id": "bid-1", "body": "hello fleet" } }


_META = { "voice_persona": { "name": "maria" }, "stable_session_id": "sess-1" }


def _bridge_scan( personas ):
    """Build a find_active_voice_persona_sessions return value from persona dicts."""
    return [ ( MagicMock(), f"sid-{i}", p ) for i, p in enumerate( personas ) ]


def _invoke( listener, notification, scan_result, meta=_META ):
    """Run _handle_broadcast_received with all collaborators patched; return the handle_broadcast mock."""
    with patch(
        "lupin_mcp.broadcast_handler.handle_broadcast"
    ) as mock_handle, patch(
        "lupin_mcp.commons_store.CommonsStore", return_value=MagicMock()
    ), patch(
        "lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata",
        return_value=meta,
    ), patch(
        "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
        return_value=scan_result,
    ), patch.object( listener, "_log" ):
        listener._handle_broadcast_received( notification )
    return mock_handle


# ═════════════════════════════════════════════════════════════════════════════
# Test cases
# ═════════════════════════════════════════════════════════════════════════════

class TestBroadcastRosterWiring:
    """Roster construction + pass-through to handle_broadcast."""

    def test_roster_collects_name_and_display_name( self, listener, notification, monkeypatch ):
        """Each live session contributes name AND display_name, order-preserving."""
        monkeypatch.setenv( "LUPIN_ROOT", "/tmp/lupin-test-root" )
        scan = _bridge_scan( [
            { "name": "maria",    "display_name": "Maria"     },
            { "name": "mr_radio", "display_name": "Mr. Radio" },
        ] )
        mock_handle = _invoke( listener, notification, scan )

        kwargs = mock_handle.call_args.kwargs
        assert kwargs[ "persona_roster" ] == [ "maria", "Maria", "mr_radio", "Mr. Radio" ]
        assert kwargs[ "local_persona" ]  == _META[ "voice_persona" ]
        assert kwargs[ "sender_session_id" ] == "sess-1"

    def test_roster_deduplicates_repeated_names( self, listener, notification, monkeypatch ):
        """A name seen twice (same persona on two bridges, or name == display_name) appears once."""
        monkeypatch.setenv( "LUPIN_ROOT", "/tmp/lupin-test-root" )
        scan = _bridge_scan( [
            { "name": "sam", "display_name": "Sam" },
            { "name": "sam", "display_name": "Sam" },
        ] )
        mock_handle = _invoke( listener, notification, scan )
        assert mock_handle.call_args.kwargs[ "persona_roster" ] == [ "sam", "Sam" ]

    def test_roster_skips_non_string_and_empty_values( self, listener, notification, monkeypatch ):
        """None / empty / non-string name fields are skipped, not collected."""
        monkeypatch.setenv( "LUPIN_ROOT", "/tmp/lupin-test-root" )
        scan = _bridge_scan( [
            { "name": None, "display_name": ""      },
            { "name": 42                            },
            { "name": "tiberius"                    },
        ] )
        mock_handle = _invoke( listener, notification, scan )
        assert mock_handle.call_args.kwargs[ "persona_roster" ] == [ "tiberius" ]

    def test_empty_scan_passes_none_not_empty_list( self, listener, notification, monkeypatch ):
        """An empty bridge scan carries no roster signal → persona_roster=None
        (an empty LIST would flag every directive as prose — wrong)."""
        monkeypatch.setenv( "LUPIN_ROOT", "/tmp/lupin-test-root" )
        mock_handle = _invoke( listener, notification, [ ] )
        assert mock_handle.call_args.kwargs[ "persona_roster" ] is None


class TestBroadcastReceivedGuards:
    """Pre-roster guard branches of _handle_broadcast_received."""

    def test_missing_lupin_root_returns_without_handling( self, listener, notification, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        with patch(
            "lupin_mcp.broadcast_handler.handle_broadcast"
        ) as mock_handle, patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata",
            return_value=_META,
        ), patch.object( listener, "_log" ) as mock_log:
            listener._handle_broadcast_received( notification )
        mock_handle.assert_not_called()
        assert any( "LUPIN_ROOT unset" in str( c ) for c in mock_log.call_args_list )

    def test_commons_store_init_failure_returns_without_handling( self, listener, notification, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", "/tmp/lupin-test-root" )
        with patch(
            "lupin_mcp.broadcast_handler.handle_broadcast"
        ) as mock_handle, patch(
            "lupin_mcp.commons_store.CommonsStore", side_effect=OSError( "disk gone" )
        ), patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata",
            return_value=_META,
        ), patch.object( listener, "_log" ) as mock_log:
            listener._handle_broadcast_received( notification )
        mock_handle.assert_not_called()
        assert any( "CommonsStore init failed" in str( c ) for c in mock_log.call_args_list )

    def test_import_failure_logged_and_returns( self, listener, notification, monkeypatch ):
        """None in sys.modules makes the lazy import raise ImportError → logged, no crash."""
        monkeypatch.setenv( "LUPIN_ROOT", "/tmp/lupin-test-root" )
        with patch.dict( "sys.modules", { "lupin_mcp.broadcast_handler": None } ), \
             patch.object( listener, "_log" ) as mock_log:
            listener._handle_broadcast_received( notification )
        assert any( "broadcast_handler import failed" in str( c ) for c in mock_log.call_args_list )

    def test_session_id_falls_back_to_unknown( self, listener, notification, monkeypatch ):
        """No stable_session_id / session_id in metadata → sender '<unknown>'."""
        monkeypatch.setenv( "LUPIN_ROOT", "/tmp/lupin-test-root" )
        mock_handle = _invoke( listener, notification, [ ], meta={ "voice_persona": None } )
        assert mock_handle.call_args.kwargs[ "sender_session_id" ] == "<unknown>"
