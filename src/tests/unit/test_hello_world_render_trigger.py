#!/usr/bin/env python3
"""
Acceptance tests for bug ef10c5b6 — the SessionStart hello-world render TRIGGER
fires under environment loss (fix (b), defense-in-depth file fallback).

WHY THIS IS THE RIGHT ACCEPTANCE (not "seed is live"):
The focus-bar roster (get_visible_senders, notifications.py) lists any sender
with >=1 visible notification row. The row that paints a fresh session onto the
bar is created by the hello-world send_tts() dispatch. The bug was NEVER in the
server-side row->roster render (interactively-launched sessions rendered fine
all along) — it was that send_tts() returned SILENTLY when get_target_email()
resolved to None after the tmux-server restart wiped LUPIN_DEV_EMAIL. So the
defect is precisely: "the render trigger does not fire." These tests assert the
trigger DOES fire now — that send_tts() dispatches a notification carrying the
file-resolved recipient — with LUPIN_DEV_EMAIL FORCED UNSET, so the live
`tmux set-environment -g` seed (mitigation c) is irrelevant to the result. A
green here means env-loss no longer silences registration, independent of the
seed.

The outermost HTTP transport (notify_user_async) is the only thing mocked; every
layer the bug lives in — is_tts_enabled, get_target_email, the ~/.lupin/config
INI fallback, and send_tts's dispatch decision — runs for real. No server, no DB
row, no live-feed pollution → :7999 venue (fast, isolated, no persistent state).

A full live-spawn E2E (launch a real tmux session -> observe the focus bar) is
the domain of manual operator observation / the :8000 scheduled suite, and the
SECOND delivery-path bug (spawned-seat MCP-notify not rendering, root-cause doc
"Live addendum") is a SEPARATE cause explicitly out of this fix's scope.
"""
import configparser

import pytest

from lupin_cli.claude_code.hooks.lib import hook_common as hc


TRANSPORT = "lupin_cli.notifications.notify_user_async.notify_user_async"


def _write_config( path, env_name, recipient ):
    parser = configparser.ConfigParser()
    parser[ "environments" ] = { "default": env_name }
    parser[ env_name ] = { "global_notification_recipient": recipient }
    with open( path, "w", encoding="utf-8" ) as handle:
        parser.write( handle )
    return path


@pytest.fixture
def captured_dispatch( monkeypatch ):
    """Capture the AsyncNotificationRequest send_tts would transmit, without any
    network I/O. notify_user_async is imported inside send_tts, so we patch it at
    its source module (the call-time import binds to the patched attribute)."""
    captured = {}

    def _fake_notify( request=None, **_kwargs ):
        captured[ "request" ] = request
        return None

    monkeypatch.setattr( TRANSPORT, _fake_notify )
    return captured


class TestHelloWorldRenderTrigger:

    def test_env_loss_still_fires_dispatch_via_file_fallback( self, tmp_path, monkeypatch, captured_dispatch ):
        # THE crux: LUPIN_DEV_EMAIL forced UNSET (seed irrelevant) → the file
        # fallback resolves the recipient → send_tts DISPATCHES the hello-world.
        cfg = _write_config( tmp_path / "config", "local", "operator@example.com" )
        monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
        monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
        monkeypatch.delenv( "HOOK_TTS_ENABLED", raising=False )

        hc.send_tts( "hello-world", sender_id="claude.code@lupin.deepily.ai#probe" )

        assert "request" in captured_dispatch, "send_tts must dispatch, not silently no-op"
        request = captured_dispatch[ "request" ]
        assert request.target_user == "operator@example.com"   # file-resolved recipient
        assert request.sender_id   == "claude.code@lupin.deepily.ai#probe"
        assert request.message     == "hello-world"

    def test_env_wins_over_file_in_dispatch( self, tmp_path, monkeypatch, captured_dispatch ):
        # Precedence carried all the way to the wire: env present → env recipient.
        cfg = _write_config( tmp_path / "config", "local", "file@example.com" )
        monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
        monkeypatch.setenv( "LUPIN_DEV_EMAIL", "env@example.com" )
        monkeypatch.delenv( "HOOK_TTS_ENABLED", raising=False )

        hc.send_tts( "hello-world", sender_id="claude.code@lupin.deepily.ai#probe" )

        assert captured_dispatch[ "request" ].target_user == "env@example.com"

    def test_no_dispatch_when_neither_source_resolves( self, tmp_path, monkeypatch, captured_dispatch ):
        # The documented silent no-op is now reached ONLY when BOTH sources are
        # empty — a genuinely unresolvable target, not an environment accident.
        monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( tmp_path / "absent" ) )
        monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
        monkeypatch.delenv( "HOOK_TTS_ENABLED", raising=False )

        hc.send_tts( "hello-world", sender_id="claude.code@lupin.deepily.ai#probe" )

        assert "request" not in captured_dispatch, "no target → no dispatch (correct silent no-op)"

    def test_tts_disabled_suppresses_dispatch_even_with_resolvable_target( self, tmp_path, monkeypatch, captured_dispatch ):
        # A deliberate HOOK_TTS_ENABLED=false still wins — the fix does not
        # override an explicit per-session disable.
        cfg = _write_config( tmp_path / "config", "local", "operator@example.com" )
        monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
        monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
        monkeypatch.setenv( "HOOK_TTS_ENABLED", "false" )

        hc.send_tts( "hello-world", sender_id="claude.code@lupin.deepily.ai#probe" )

        assert "request" not in captured_dispatch


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
