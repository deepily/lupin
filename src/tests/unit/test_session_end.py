"""
Unit tests for src/lupin_cli/claude_code/hooks/session_end.py.

Specifically validates the Phase 1.5 voice-persona release reason-guard
introduced 2026-05-05 to fix the /clear voice-persona switch bug.

Bug: SessionEnd hook fires on /clear (with payload reason="clear"),
not only on actual session termination. Without the guard,
_release_voice_persona was called unconditionally, nulling the bridge's
voice_persona BEFORE the post-/clear SessionStart could carry it forward.
The next /allocate then rolled a fresh random persona, so the user
heard a different voice mid-session.

Fix: skip _release_voice_persona when payload["reason"] in {"clear", "compact"}.
Always release on actual termination ("logout", "prompt_input_exit",
"other", or missing reason for legacy compat).

Design: src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md §0
"""

import sys
from unittest.mock import MagicMock

import pytest

import lupin_cli.claude_code.hooks.session_end as session_end
import lupin_cli.claude_code.hooks.lib.session_bridge as session_bridge


TEST_SESSION_ID = "test-sid-12345678-90ab-cdef-1234-567890abcdef"


def _patch_main_dependencies( monkeypatch, payload, release_mock=None ):
    """
    Replace all side-effect helpers in session_end.main() with mocks.

    Returns the release mock so the caller can assert call count.
    """
    if release_mock is None:
        release_mock = MagicMock( return_value=True )

    # The hook input — the THING we're varying per test.
    monkeypatch.setattr( session_end, "read_hook_input", lambda: payload )

    # The persona release helper — the THING we're testing the guard around.
    monkeypatch.setattr( session_end, "_release_voice_persona", release_mock )

    # kill_idle_waiter is imported INSIDE main() at the function-local scope.
    # Patch it on the source module so the local `from ... import` picks up
    # the mock the next time the import runs.
    monkeypatch.setattr( session_bridge, "kill_idle_waiter", MagicMock() )

    # Listener helpers — avoid touching real bridge files.
    monkeypatch.setattr( session_end, "_find_listener_pid", MagicMock( return_value=None ) )
    monkeypatch.setattr( session_end, "_stop_listener", MagicMock() )

    # Buffer-file cleanup — return a fake path that "doesn't exist".
    fake_buffer = MagicMock()
    fake_buffer.exists = MagicMock( return_value=False )
    monkeypatch.setattr( session_end, "get_buffer_path", lambda sid: fake_buffer )

    # Payload logger and emit — no-op.
    monkeypatch.setattr( session_end, "log_payload", MagicMock() )
    monkeypatch.setattr( session_end, "emit_json", MagicMock() )

    return release_mock


class TestSessionEndPersonaReleaseGuard:
    """
    Validate the reason-aware guard around _release_voice_persona that
    landed 2026-05-05 to stop /clear from accidentally releasing personas.
    """

    def test_skips_release_on_clear( self, monkeypatch ):
        """SessionEnd with reason='clear' MUST NOT call _release_voice_persona."""
        payload = { "session_id": TEST_SESSION_ID, "reason": "clear" }
        release_mock = _patch_main_dependencies( monkeypatch, payload )

        session_end.main()

        assert release_mock.call_count == 0, (
            f"Expected no /release call on /clear, but got {release_mock.call_count}"
        )

    def test_skips_release_on_compact( self, monkeypatch ):
        """SessionEnd with reason='compact' MUST NOT call _release_voice_persona."""
        payload = { "session_id": TEST_SESSION_ID, "reason": "compact" }
        release_mock = _patch_main_dependencies( monkeypatch, payload )

        session_end.main()

        assert release_mock.call_count == 0

    def test_releases_on_logout( self, monkeypatch ):
        """SessionEnd with reason='logout' (actual termination) MUST call _release_voice_persona."""
        payload = { "session_id": TEST_SESSION_ID, "reason": "logout" }
        release_mock = _patch_main_dependencies( monkeypatch, payload )

        session_end.main()

        assert release_mock.call_count == 1
        assert release_mock.call_args[ 0 ][ 0 ] == TEST_SESSION_ID

    def test_releases_on_other( self, monkeypatch ):
        """SessionEnd with reason='other' (process exit catch-all) MUST call _release_voice_persona."""
        payload = { "session_id": TEST_SESSION_ID, "reason": "other" }
        release_mock = _patch_main_dependencies( monkeypatch, payload )

        session_end.main()

        assert release_mock.call_count == 1

    def test_releases_on_prompt_input_exit( self, monkeypatch ):
        """SessionEnd with reason='prompt_input_exit' (Ctrl+D) MUST call _release_voice_persona."""
        payload = { "session_id": TEST_SESSION_ID, "reason": "prompt_input_exit" }
        release_mock = _patch_main_dependencies( monkeypatch, payload )

        session_end.main()

        assert release_mock.call_count == 1

    def test_releases_when_reason_missing( self, monkeypatch ):
        """SessionEnd with no reason key (legacy hook payload) MUST call release (default to release)."""
        payload = { "session_id": TEST_SESSION_ID }  # no "reason" key
        release_mock = _patch_main_dependencies( monkeypatch, payload )

        session_end.main()

        assert release_mock.call_count == 1, (
            "Missing reason should default to release (legacy compat: pre-reason-field hooks)"
        )

    def test_skips_release_when_session_id_empty( self, monkeypatch ):
        """SessionEnd without session_id MUST NOT call release (no-op for empty id)."""
        payload = { "session_id": "", "reason": "other" }
        release_mock = _patch_main_dependencies( monkeypatch, payload )

        session_end.main()

        assert release_mock.call_count == 0

    def test_release_failure_is_swallowed( self, monkeypatch ):
        """If _release_voice_persona raises, SessionEnd MUST NOT crash (fail-soft)."""
        payload = { "session_id": TEST_SESSION_ID, "reason": "logout" }
        release_mock = MagicMock( side_effect=RuntimeError( "simulated network failure" ) )
        _patch_main_dependencies( monkeypatch, payload, release_mock=release_mock )

        # Must not raise
        session_end.main()

        assert release_mock.call_count == 1


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
