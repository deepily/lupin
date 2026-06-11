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
    monkeypatch.setattr( session_end, "_find_all_listener_pids", MagicMock( return_value=[ ] ) )
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


# ═════════════════════════════════════════════════════════════════════════════
# F2 reap-all-matching listeners (2026-06-11)
#
# Pre-fix, Phase 2 killed only the single bridge-recorded listener_pid; the
# `--continue` double-fire's duplicate listener survived as a permanent orphan
# (the broadcast-miss root cause). _find_all_listener_pids returns the union
# of bridge PID + cmdline-matched live listeners across ALL the session's
# hashes.
#
# Per src/rnd/v0.1.8/2026.06.10-broadcast-miss-duplicate-listener-root-cause.md §4
# ═════════════════════════════════════════════════════════════════════════════

import json
import os
import subprocess
import time
import uuid

import lupin_cli.claude_code.hooks.lib.listener_processes as listener_processes


def _write_bridge( session_dir, name, data ):
    """Write a bridge JSON file into the test session dir."""
    path = session_dir / name
    with open( path, "w" ) as f:
        json.dump( data, f )
    return path


class TestFindAllListenerPids:

    def test_union_of_bridge_pid_and_cmdline_matches( self, tmp_path, monkeypatch ):
        """Bridge PID ∪ pgrep hits across session_id/stable/session_ids hashes."""
        _write_bridge( tmp_path, "cc-111.json", {
            "session_id"        : TEST_SESSION_ID,
            "stable_session_id" : "stable99-aaaa-bbbb-cccc-ddddeeeeffff",
            "session_ids"       : [ "stable99-aaaa-bbbb-cccc-ddddeeeeffff", TEST_SESSION_ID ],
            "listener_pid"      : 100,
        } )
        per_hash = {
            TEST_SESSION_ID[ :8 ] : [ 200 ],
            "stable99"            : [ 100, 300 ],   # bridge PID rediscovered + an orphan
        }
        monkeypatch.setattr( listener_processes, "find_live_listener_pids",
                             lambda h: per_hash.get( h, [ ] ) )

        result = session_end._find_all_listener_pids( TEST_SESSION_ID, session_dir=str( tmp_path ) )

        assert result == [ 100, 200, 300 ]  # deduped union, sorted

    def test_no_bridge_falls_back_to_session_hash_scan( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( listener_processes, "find_live_listener_pids",
                             lambda h: [ 555 ] if h == TEST_SESSION_ID[ :8 ] else [ ] )
        result = session_end._find_all_listener_pids( TEST_SESSION_ID, session_dir=str( tmp_path ) )
        assert result == [ 555 ]

    def test_missing_session_dir_falls_back_to_hash_scan( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( listener_processes, "find_live_listener_pids",
                             lambda h: [ 777 ] )
        result = session_end._find_all_listener_pids(
            TEST_SESSION_ID, session_dir=str( tmp_path / "does-not-exist" )
        )
        assert result == [ 777 ]

    def test_unparseable_and_foreign_bridges_skipped( self, tmp_path, monkeypatch ):
        ( tmp_path / "cc-bad.json" ).write_text( "{not json" )
        _write_bridge( tmp_path, "cc-other.json", {
            "session_id"   : "some-other-session",
            "listener_pid" : 666,
        } )
        monkeypatch.setattr( listener_processes, "find_live_listener_pids", lambda h: [ ] )
        result = session_end._find_all_listener_pids( TEST_SESSION_ID, session_dir=str( tmp_path ) )
        assert result == [ ]

    def test_default_session_dir_resolved_via_expanduser( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( session_end.os.path, "expanduser", lambda p: str( tmp_path ) )
        monkeypatch.setattr( listener_processes, "find_live_listener_pids",
                             lambda h: [ 888 ] )
        result = session_end._find_all_listener_pids( TEST_SESSION_ID )  # no session_dir arg
        assert result == [ 888 ]

    def test_non_bridge_entries_skipped( self, tmp_path, monkeypatch ):
        ( tmp_path / "README.txt" ).write_text( "not a bridge" )
        ( tmp_path / "cc-listener-abc.log" ).write_text( "not json suffix" )
        monkeypatch.setattr( listener_processes, "find_live_listener_pids", lambda h: [ ] )
        result = session_end._find_all_listener_pids( TEST_SESSION_ID, session_dir=str( tmp_path ) )
        assert result == [ ]

    def test_non_int_listener_pid_ignored( self, tmp_path, monkeypatch ):
        _write_bridge( tmp_path, "cc-111.json", {
            "session_id"   : TEST_SESSION_ID,
            "listener_pid" : "not-a-pid",
        } )
        monkeypatch.setattr( listener_processes, "find_live_listener_pids", lambda h: [ ] )
        result = session_end._find_all_listener_pids( TEST_SESSION_ID, session_dir=str( tmp_path ) )
        assert result == [ ]


class TestMainReapsAllListeners:

    def test_phase2_stops_every_returned_pid( self, monkeypatch ):
        payload = { "session_id": TEST_SESSION_ID, "reason": "logout" }
        _patch_main_dependencies( monkeypatch, payload )
        monkeypatch.setattr( session_end, "_find_all_listener_pids",
                             MagicMock( return_value=[ 100, 200, 300 ] ) )
        stop_mock = MagicMock()
        monkeypatch.setattr( session_end, "_stop_listener", stop_mock )

        session_end.main()

        assert [ c.args[ 0 ] for c in stop_mock.call_args_list ] == [ 100, 200, 300 ]


class TestDuplicateListenerReapRegression:
    """
    REGRESSION (live processes): the 06-06 anomaly — TWO live listeners for
    one session, the bridge remembering only ONE PID. Pre-fix SessionEnd
    killed the bridge PID and orphaned the other. Post-fix the reap-all
    sweep kills BOTH.

    SAFETY: children are throwaway `sleep` processes carrying the listener
    marker + a uuid-unique FAKE hash in argv — never a real session hash.
    """

    def test_both_duplicates_reaped_when_bridge_knows_only_one( self, tmp_path ):
        import sys as _sys
        fake_stable = uuid.uuid4().hex
        fake_hash   = fake_stable[ :8 ]

        def spawn_fake():
            return subprocess.Popen(
                [ _sys.executable, "-c", "import time; time.sleep( 30 )",
                  "cc_notification_listener", "--session-id", fake_hash ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        proc_a, proc_b = spawn_fake(), spawn_fake()
        try:
            time.sleep( 0.2 )  # let /proc entries settle
            # Bridge records ONLY proc_a (the PID-shadowing condition)
            _write_bridge( tmp_path, "cc-42.json", {
                "session_id"        : fake_stable,
                "stable_session_id" : fake_stable,
                "listener_pid"      : proc_a.pid,
            } )

            pids = session_end._find_all_listener_pids( fake_stable, session_dir=str( tmp_path ) )
            assert sorted( [ proc_a.pid, proc_b.pid ] ) == pids

            # Reap zombies concurrently — in production the detached listener is
            # reparented to init; here WE are the parent, and an unreaped zombie
            # still answers os.kill(pid, 0), which would stall _stop_listener's
            # 5s liveness loop.
            import threading as _threading
            reapers = [ _threading.Thread( target=p.wait ) for p in ( proc_a, proc_b ) ]
            for r in reapers: r.start()

            for pid in pids:
                session_end._stop_listener( pid )

            for r in reapers: r.join( timeout=10 )
            assert proc_a.returncode is not None
            assert proc_b.returncode is not None
        finally:
            for p in ( proc_a, proc_b ):
                try:
                    p.kill()
                    p.wait( timeout=5 )
                except OSError:
                    pass


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
