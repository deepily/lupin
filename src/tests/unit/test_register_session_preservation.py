"""
Unit tests for register_session.py /clear voice_persona preservation.

Covers the carry-forward block at register_session.main():

    if is_context_clear and old_data and isinstance(
        old_data.get( "voice_persona" ), dict
    ):
        session_data[ "voice_persona" ] = old_data[ "voice_persona" ]

…plus the defense-in-depth release call that fires when carry-forward
declined to preserve but the old bridge had a persona.

Five scenarios per design doc §3 Step 1.5:
    1. Fresh start (no lockfile, no bridge) → preservation N/A
    2. /clear with persona → persona preserved (release does NOT fire)
    3. /clear without persona → no preservation (release does NOT fire)
    4. /clear with corrupted bridge → no preservation, gate-2 logged
    5. Legacy session_ids[] match (xfail until Phase 1.3 mitigation lands)

Plus one additional case verifying Fix 2 + Fix 3 wiring:
    6. /clear with persona BUT preservation fails (simulated via session_ids
       legacy match): release helper fires AND alloc receives the previous
       display_name. Wired as part of case 5's xpass path; covered separately
       to lock in the contract.

Design: src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md
"""

import json

import pytest
from unittest.mock import MagicMock

import lupin_cli.claude_code.hooks.register_session as register_session


TEST_CC_PID         = 99999
TEST_OLD_SESSION_ID = "old-uuid-1111-2222-3333-444444444444"
TEST_NEW_SESSION_ID = "new-uuid-aaaa-bbbb-cccc-dddddddddddd"

TEST_PERSONA = {
    "name"         : "tiberius",
    "display_name" : "Tiberius",
    "voice_id"     : "abc123",
    "color"        : "#7B1FA2",
    "icon"         : "🎙",
    "profile"      : "deep authoritative"
}


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def isolated_session_dir( tmp_path, monkeypatch ):
    """
    Redirect HOME so register_session.main() writes to a tempdir.

    Returns the Path object for <tmp_path>/.claude/sessions.
    """
    monkeypatch.setenv( "HOME", str( tmp_path ) )
    session_dir = tmp_path / ".claude" / "sessions"
    session_dir.mkdir( parents=True, exist_ok=True )
    return session_dir


@pytest.fixture
def patched_main( monkeypatch ):
    """
    Patch all side-effect helpers used by main() so the bridge-write logic
    runs in isolation. Returns the mocks dict for assertions.
    """
    mocks = {
        "read_hook_input"                  : MagicMock(),
        "_resolve_cc_pid"                  : MagicMock( return_value=TEST_CC_PID ),
        "_find_tmux_session"               : MagicMock( return_value=None ),
        "_cleanup_old_listener"            : MagicMock(),
        "_allocate_voice_persona_via_http" : MagicMock( return_value=None ),
        "_release_voice_persona_via_http"  : MagicMock( return_value=False ),
        "send_tts"                         : MagicMock(),
        "_spawn_listener"                  : MagicMock( return_value=None ),
        "log_payload"                      : MagicMock(),
        "emit_json"                        : MagicMock(),
        "_check_cosa_voice_status"         : MagicMock( return_value="" ),
        "detect_project"                   : MagicMock( return_value="lupin" )
    }
    for name, mock in mocks.items():
        monkeypatch.setattr( register_session, name, mock )

    mocks[ "read_hook_input" ].return_value = {
        "session_id"      : TEST_NEW_SESSION_ID,
        "transcript_path" : "/tmp/transcript.jsonl",
        "cwd"             : "/mnt/DATA01/test"
    }
    return mocks


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _bridge_path( session_dir ):
    return session_dir / f"cc-{TEST_CC_PID}.json"


def _lockfile_path( session_dir ):
    return session_dir / f"cc-stable-{TEST_CC_PID}.id"


def _read_bridge( session_dir ):
    p = _bridge_path( session_dir )
    if not p.exists(): return None
    return json.loads( p.read_text() )


def _write_bridge( session_dir, data ):
    _bridge_path( session_dir ).write_text( json.dumps( data ) )


def _write_lockfile( session_dir, session_id ):
    _lockfile_path( session_dir ).write_text( session_id )


# ═════════════════════════════════════════════════════════════════════════════
# TestPreservationCases — five scenarios from design doc §3 Step 1.5
# ═════════════════════════════════════════════════════════════════════════════

class TestPreservationCases:
    """Carry-forward gate behavior across the five canonical scenarios."""

    def test_fresh_start_no_lockfile_no_bridge( self, isolated_session_dir, patched_main ):
        """Fresh start: no lockfile + no bridge → is_context_clear=False, no carry-forward."""
        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        assert bridge[ "session_id" ]        == TEST_NEW_SESSION_ID
        assert bridge[ "stable_session_id" ] == TEST_NEW_SESSION_ID  # First SessionStart anchors stable id
        assert "voice_persona" not in bridge
        # No old bridge → release helper should not fire
        patched_main[ "_release_voice_persona_via_http" ].assert_not_called()

    def test_clear_with_persona_preserves( self, isolated_session_dir, patched_main ):
        """/clear with persona on bridge → is_context_clear=True → persona carried forward."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_OLD_SESSION_ID,
            "stable_session_id" : TEST_OLD_SESSION_ID,
            "session_ids"       : [ TEST_OLD_SESSION_ID ],
            "voice_persona"     : TEST_PERSONA
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        assert bridge[ "voice_persona" ] == TEST_PERSONA
        # Preservation succeeded → release MUST NOT fire
        patched_main[ "_release_voice_persona_via_http" ].assert_not_called()
        # Phase 4.5 short-circuits when voice_persona already in session_data
        patched_main[ "_allocate_voice_persona_via_http" ].assert_not_called()

    def test_clear_without_persona_no_preservation( self, isolated_session_dir, patched_main ):
        """/clear with no persona on old bridge → no carry-forward, no release."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_OLD_SESSION_ID,
            "stable_session_id" : TEST_OLD_SESSION_ID,
            "session_ids"       : [ TEST_OLD_SESSION_ID ]
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        assert "voice_persona" not in bridge
        patched_main[ "_release_voice_persona_via_http" ].assert_not_called()

    def test_clear_corrupted_bridge_no_preservation( self, isolated_session_dir, patched_main, capsys ):
        """/clear with corrupted bridge JSON → gate-2 swallows error, gate-2-fail diagnostic logged."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _bridge_path( isolated_session_dir ).write_text( "{not valid json" )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None  # Hook still wrote a fresh bridge over the bad one
        assert "voice_persona" not in bridge

        captured = capsys.readouterr()
        assert "[register_session] gate-2-fail:" in captured.err
        # Phase 1.1 diagnostic should also fire the preserve-check
        assert "[register_session] preserve-check:" in captured.err

    @pytest.mark.xfail(
        reason="Phase 1.3 gate-3 broadening (session_ids[] membership) pending; "
               "fires after user repro identifies the failed gate"
    )
    def test_legacy_session_ids_match_preserves( self, isolated_session_dir, patched_main ):
        """
        Legacy bridge: stable_session_id present in old_data["session_ids"][] but
        old_data["session_id"] equals the NEW transient (e.g., a documented
        hook double-fire on /clear). Once Phase 1.3 broadens gate-3 to accept
        session_ids[] membership, preservation should fire.
        """
        legacy_stable_id = "legacy-uuid-9999-8888-7777-666666666666"
        _write_lockfile( isolated_session_dir, legacy_stable_id )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_NEW_SESSION_ID,  # ← gate-3 sees equality, fails today
            "stable_session_id" : legacy_stable_id,
            "session_ids"       : [ legacy_stable_id, TEST_NEW_SESSION_ID ],
            "voice_persona"     : TEST_PERSONA
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        assert bridge.get( "voice_persona" ) == TEST_PERSONA  # Will XPASS once Phase 1.3 lands


# ═════════════════════════════════════════════════════════════════════════════
# TestPhase1Diagnostics — verify Phase 1.1 instrumentation fires correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestPhase1Diagnostics:
    """Phase 1.1 stderr prints — ensure they fire on the relevant code paths."""

    def test_gate_result_logs_after_clear_detected( self, isolated_session_dir, patched_main, capsys ):
        """gate-result print fires inside the FileExistsError path with old + new ids."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_OLD_SESSION_ID,
            "stable_session_id" : TEST_OLD_SESSION_ID,
            "session_ids"       : [ TEST_OLD_SESSION_ID ]
        } )

        register_session.main()

        captured = capsys.readouterr()
        assert "[register_session] gate-result:" in captured.err
        assert "is_context_clear=True"           in captured.err
        assert TEST_OLD_SESSION_ID               in captured.err
        assert TEST_NEW_SESSION_ID               in captured.err

    def test_preserve_check_logs_with_state( self, isolated_session_dir, patched_main, capsys ):
        """preserve-check print fires unconditionally inside the session_id branch."""
        register_session.main()

        captured = capsys.readouterr()
        assert "[register_session] preserve-check:" in captured.err
        assert "is_context_clear=False"             in captured.err  # Fresh start
        assert "old_data_present=False"             in captured.err
        assert "vp_is_dict=False"                   in captured.err


# ═════════════════════════════════════════════════════════════════════════════
# TestReleaseAndReAssignWiring — Fix 2 + Fix 3 plumbing
# ═════════════════════════════════════════════════════════════════════════════

class TestReleaseAndReAssignWiring:
    """Defense-in-depth: when carry-forward declines but old bridge had a persona."""

    def test_no_persona_on_old_bridge_skips_release( self, isolated_session_dir, patched_main ):
        """Old bridge without voice_persona → release MUST NOT be called."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_OLD_SESSION_ID,
            "stable_session_id" : TEST_OLD_SESSION_ID,
            "session_ids"       : [ TEST_OLD_SESSION_ID ]
        } )

        register_session.main()

        patched_main[ "_release_voice_persona_via_http" ].assert_not_called()

    def test_alloc_receives_no_previous_name_when_no_old_persona( self, isolated_session_dir, patched_main ):
        """Phase 4.5 alloc gets previous_persona_name=None when no handoff."""
        register_session.main()

        # Single alloc call expected; previous_persona_name kwarg should be None
        alloc_mock = patched_main[ "_allocate_voice_persona_via_http" ]
        assert alloc_mock.call_count == 1
        kwargs = alloc_mock.call_args.kwargs
        assert kwargs.get( "previous_persona_name" ) is None
