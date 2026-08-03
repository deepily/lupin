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
    4. /clear with corrupted bridge → no preservation (gate-2 except swallowed)
    5. (REMOVED 2026-05-05) Legacy session_ids[] match — was pinned to the
       gate-3 hypothesis disproved by Phase 1.2 diagnostics. The real bug is
       in session_end.py releasing the persona on /clear; see
       test_session_end.py::TestSessionEndPersonaReleaseGuard for the fix's
       coverage.

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
        # ( persona, failure ) since candidate A (2026-07-19): the give-up is
        # structured so Phase 7 can route it into the session's boot context.
        # Modelled as a REAL failure shape, not ( None, None ) — that tuple
        # cannot occur in production and a fixture should not teach otherwise.
        "_allocate_voice_persona_via_http" : MagicMock( return_value=(
            None,
            { "stage": "transport", "exception": "TimeoutError", "message": "timed out",
              "attempts": 3, "server_url": "http://srv" }
        ) ),
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

    def test_clear_corrupted_bridge_no_preservation( self, isolated_session_dir, patched_main ):
        """/clear with corrupted bridge JSON → gate-2 except swallows error, no preservation."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _bridge_path( isolated_session_dir ).write_text( "{not valid json" )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None  # Hook still wrote a fresh bridge over the bad one
        assert "voice_persona" not in bridge

    # Removed 2026-05-05 (Session d5e3cf21): the legacy session_ids[] match xfail
    # was pinned to the gate-3 hypothesis disproved by Phase 1.2 diagnostics. Real
    # root cause is in session_end.py (releases persona on /clear), not in
    # register_session.py gate-3. See:
    #   - src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md §0
    #   - src/tests/unit/test_session_end.py::TestSessionEndPersonaReleaseGuard
    #     (covers the actual fix at session_end.py:224-226)


# ═════════════════════════════════════════════════════════════════════════════
# TestPhase1Diagnostics — REMOVED 2026-05-05 (Phase 1F)
# ═════════════════════════════════════════════════════════════════════════════
# The Phase 1.1 stderr prints (gate-result, gate-2-fail, preserve-check) were
# diagnostic instrumentation added to capture which gate failed on /clear.
# They served their purpose in Phase 1.2 (proved gate-3 fired correctly,
# pointed to upstream session_end.py:224 release-on-clear bug). With the §0.4
# reason-guard fix landed in session_end.py and live-verified, the diagnostic
# prints + their tests were removed in Phase 1F.
# See: src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md §0.5


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


# ═════════════════════════════════════════════════════════════════════════════
# TestDeclaredManagersTransport — reserve-from-random (Rick 2026-06-11)
# ═════════════════════════════════════════════════════════════════════════════
# The COSA_VOICE_MANAGERS__<PROJECT> roster must reach the allocate endpoint on
# EVERY Phase 4.5 call — chain or plain random — or the reserve only protects
# chained boots (Tiberius's build-time check).
# Design: src/rnd/v0.1.8/2026.06.11-fleet-roster-env-file-and-reserve-from-random.md
#         src/rnd/2026.06.22-fleet-roster-to-user-level-migration-spec.md (PIP, María):
#         the roster moved to the user-level ~/.claude/fleet-roster.env; the
#         COSA_VOICE_MANAGERS__* VAR contract asserted here is UNCHANGED by that move.

class TestDeclaredManagersTransport:
    """Call-site threading of declared_managers into _allocate_voice_persona_via_http."""

    def _clear_chain_env( self, monkeypatch ):
        for var in ( "COSA_VOICE_PERSONA_CHAIN", "COSA_VOICE_PREFERRED_PERSONA__LUPIN",
                     "COSA_VOICE_HEADLESS" ):
            monkeypatch.delenv( var, raising=False )

    def test_roster_threads_on_plain_random_call( self, isolated_session_dir, patched_main, monkeypatch ):
        """THE no-chain receipt: with NO chain resolvable, the roster still
        rides the allocate call — plain-random boots are protected too."""
        self._clear_chain_env( monkeypatch )
        monkeypatch.setenv( "COSA_VOICE_MANAGERS__LUPIN", "Mr. Radio, Tiberius" )
        register_session.main()
        kwargs = patched_main[ "_allocate_voice_persona_via_http" ].call_args.kwargs
        assert kwargs.get( "persona_chain" ) is None
        assert kwargs.get( "declared_managers" ) == [ "Mr. Radio", "Tiberius" ]

    def test_roster_threads_alongside_chain( self, isolated_session_dir, patched_main, monkeypatch ):
        self._clear_chain_env( monkeypatch )
        monkeypatch.setenv( "COSA_VOICE_PERSONA_CHAIN", "Rio,*" )
        monkeypatch.setenv( "COSA_VOICE_MANAGERS__LUPIN", "Mr. Radio, Tiberius" )
        register_session.main()
        kwargs = patched_main[ "_allocate_voice_persona_via_http" ].call_args.kwargs
        assert kwargs.get( "persona_chain" ) == "Rio,*"
        assert kwargs.get( "declared_managers" ) == [ "Mr. Radio", "Tiberius" ]

    def test_no_roster_env_threads_empty_list( self, isolated_session_dir, patched_main, monkeypatch ):
        self._clear_chain_env( monkeypatch )
        monkeypatch.delenv( "COSA_VOICE_MANAGERS__LUPIN", raising=False )
        register_session.main()
        kwargs = patched_main[ "_allocate_voice_persona_via_http" ].call_args.kwargs
        assert kwargs.get( "declared_managers" ) == [ ]


class TestAllocateHttpDeclaredManagersParam:
    """Query-param emission inside _allocate_voice_persona_via_http itself."""

    _LOGIN_BODY = { "tokens": { "access_token": "tok" } }
    _ALLOC_BODY = { "voice_persona": { "name": "nora" } }

    def _patch_transport( self, monkeypatch, captured_urls ):
        import urllib.request

        def fake_urlopen( req, timeout=None ):
            captured_urls.append( req.full_url )
            body = self._LOGIN_BODY if "/auth/login" in req.full_url else self._ALLOC_BODY
            cm = MagicMock()
            cm.__enter__.return_value.read.return_value = json.dumps( body ).encode()
            cm.__exit__.return_value = False
            return cm

        monkeypatch.setattr( urllib.request, "urlopen", fake_urlopen )
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
            lambda project: ( "e@x.com", "pw" )
        )

    def _alloc_url( self, captured_urls ):
        urls = [ u for u in captured_urls if "/allocate" in u ]
        assert len( urls ) == 1, captured_urls
        return urls[ 0 ]

    def test_declared_managers_emitted_as_csv_param( self, monkeypatch ):
        import urllib.parse
        captured = [ ]
        self._patch_transport( monkeypatch, captured )
        persona, failure = register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1",
            declared_managers=[ "Mr. Radio", "Tiberius" ]
        )
        assert persona == { "name": "nora" }
        assert failure is None
        query = urllib.parse.parse_qs( urllib.parse.urlsplit( self._alloc_url( captured ) ).query )
        assert query[ "declared_managers" ] == [ "Mr. Radio,Tiberius" ]
        assert "persona_chain" not in query

    def test_declared_managers_alongside_chain_param( self, monkeypatch ):
        import urllib.parse
        captured = [ ]
        self._patch_transport( monkeypatch, captured )
        register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1",
            persona_chain="Rio,*", declared_managers=[ "Mr. Radio" ]
        )
        query = urllib.parse.parse_qs( urllib.parse.urlsplit( self._alloc_url( captured ) ).query )
        assert query[ "persona_chain" ]     == [ "Rio,*" ]
        assert query[ "declared_managers" ] == [ "Mr. Radio" ]

    def test_no_declared_managers_omits_param( self, monkeypatch ):
        captured = [ ]
        self._patch_transport( monkeypatch, captured )
        register_session._allocate_voice_persona_via_http( "http://srv", "lupin", "sid-1" )
        assert "declared_managers" not in self._alloc_url( captured )


# ═════════════════════════════════════════════════════════════════════════════
# TestCarryForwardReadModifyWrite — Fix B for the 2026-05-17 §6 mystery
# ═════════════════════════════════════════════════════════════════════════════
# Per src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md
# §D4 Fix B: the bridge write at register_session.main() is now read-modify-
# write so listener-stamped fields (user_id, owner_user_id) survive /clear.
# Without this fix, every /clear would clobber both fields and re-introduce
# the broadcast-UI "only 1 of N personas visible" bug class.

class TestCarryForwardReadModifyWrite:
    """Phase 2 (Fix B) — listener-stamped fields survive /clear via merge."""

    def test_user_id_carries_forward_across_clear( self, isolated_session_dir, patched_main ):
        """Old bridge has user_id (listener-stamped) → /clear → user_id preserved on merged bridge."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_OLD_SESSION_ID,
            "stable_session_id" : TEST_OLD_SESSION_ID,
            "session_ids"       : [ TEST_OLD_SESSION_ID ],
            "user_id"           : "service-account-uuid-aaa111",
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        # Fresh session_data wins for keys it provides
        assert bridge[ "session_id" ] == TEST_NEW_SESSION_ID
        # Listener-stamped user_id MUST survive (Fix B carry-forward)
        assert bridge[ "user_id" ] == "service-account-uuid-aaa111"

    def test_owner_user_id_carries_forward_across_clear( self, isolated_session_dir, patched_main ):
        """Old bridge has owner_user_id (writer-side stamped) → /clear → preserved."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_OLD_SESSION_ID,
            "stable_session_id" : TEST_OLD_SESSION_ID,
            "session_ids"       : [ TEST_OLD_SESSION_ID ],
            "user_id"           : "service-account-uuid-aaa111",
            "owner_user_id"     : "human-owner-uuid-0cf47e2d",
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        assert bridge[ "session_id" ]     == TEST_NEW_SESSION_ID
        assert bridge[ "user_id" ]        == "service-account-uuid-aaa111"
        # owner_user_id is the field this whole change set is designed to preserve
        assert bridge[ "owner_user_id" ] == "human-owner-uuid-0cf47e2d"

    def test_unknown_future_fields_carry_forward( self, isolated_session_dir, patched_main ):
        """Unknown future fields on old bridge → preserved (structural fix is future-proof)."""
        _write_lockfile( isolated_session_dir, TEST_OLD_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"            : TEST_OLD_SESSION_ID,
            "stable_session_id"     : TEST_OLD_SESSION_ID,
            "session_ids"           : [ TEST_OLD_SESSION_ID ],
            "future_field_xyz"      : "some_value",
            "another_future_field"  : { "nested" : True },
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        # Fix B is structural: ANY field on old bridge that isn't overwritten by
        # session_data survives. Future bridge fields don't need to be added to
        # an explicit carry-forward list — they're preserved by default.
        assert bridge[ "future_field_xyz" ]     == "some_value"
        assert bridge[ "another_future_field" ] == { "nested" : True }
        # Fresh session_data still wins for its own keys
        assert bridge[ "session_id" ] == TEST_NEW_SESSION_ID


# ═════════════════════════════════════════════════════════════════════════════
# TestCompactionAndResumeCarryForward — 2026-05-22 carry-forward gate broadening
# ═════════════════════════════════════════════════════════════════════════════
# The carry-forward gate at register_session.py:789 was keyed on
# is_context_clear, which is True only when the transient session UUID changes.
# A context COMPACTION (and a plain resume / --continue double-fire) can keep
# the same transient id, leaving is_context_clear False — so the persona was
# NOT preserved and Phase 4.5 re-rolled a random voice (Mr. Radio → Krishna).
#
# The fix drops is_context_clear from the gate: whenever a prior bridge carries
# a valid voice_persona dict, preserve it regardless of UUID rotation. These
# tests pin that behavior — the lockfile + bridge carry the SAME id that
# read_hook_input returns, so is_context_clear stays False.
#
# Design: src/rnd/v0.1.7/2026.05.22-voice-persona-request-tool-and-compaction-carry-forward.md

class TestCompactionAndResumeCarryForward:
    """Carry-forward fires on a same-transient-id lifecycle event (compaction / resume)."""

    def test_compaction_same_id_with_persona_preserves( self, isolated_session_dir, patched_main ):
        """Same-id event (is_context_clear=False) with persona → persona still carried forward."""
        # Lockfile + bridge both carry TEST_NEW_SESSION_ID — the id read_hook_input
        # returns — so old_session_id == session_id → is_context_clear stays False.
        _write_lockfile( isolated_session_dir, TEST_NEW_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_NEW_SESSION_ID,
            "stable_session_id" : TEST_NEW_SESSION_ID,
            "session_ids"       : [ TEST_NEW_SESSION_ID ],
            "voice_persona"     : TEST_PERSONA
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        # Persona preserved despite is_context_clear=False — the regression this fixes
        assert bridge[ "voice_persona" ] == TEST_PERSONA
        # Preservation succeeded → release MUST NOT fire, allocation MUST be skipped
        patched_main[ "_release_voice_persona_via_http" ].assert_not_called()
        patched_main[ "_allocate_voice_persona_via_http" ].assert_not_called()

    def test_compaction_same_id_without_persona_allocates( self, isolated_session_dir, patched_main ):
        """Same-id event with NO persona on old bridge → no carry-forward → allocation fires."""
        _write_lockfile( isolated_session_dir, TEST_NEW_SESSION_ID )
        _write_bridge( isolated_session_dir, {
            "session_id"        : TEST_NEW_SESSION_ID,
            "stable_session_id" : TEST_NEW_SESSION_ID,
            "session_ids"       : [ TEST_NEW_SESSION_ID ]
        } )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge is not None
        assert "voice_persona" not in bridge
        # No persona to carry → Phase 4.5 allocation runs; release still skipped
        assert patched_main[ "_allocate_voice_persona_via_http" ].call_count == 1
        patched_main[ "_release_voice_persona_via_http" ].assert_not_called()


# ---------------------------------------------------------------------------
# window_size pin for context-pressure assessment (2026-06-08)
# See: src/rnd/v0.1.8/2026.06.07-managing-context-memory/2026.06.08-context-pressure-revised-plan.md §4
# ---------------------------------------------------------------------------
class TestResolveWindowTokens:
    """_resolve_window_tokens() is defensive — it runs inside the live SessionStart hook."""

    def test_absent_env_falls_back_to_default( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_CC_WINDOW_TOKENS", raising=False )
        assert register_session._resolve_window_tokens() == 1_000_000

    def test_valid_env_is_honored( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_CC_WINDOW_TOKENS", "200000" )
        assert register_session._resolve_window_tokens() == 200_000

    def test_garbage_env_falls_back( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_CC_WINDOW_TOKENS", "not-a-number" )
        assert register_session._resolve_window_tokens() == 1_000_000

    def test_nonpositive_env_falls_back( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_CC_WINDOW_TOKENS", "-5" )
        assert register_session._resolve_window_tokens() == 1_000_000


# ═════════════════════════════════════════════════════════════════════════════
# TestSpawnLineageStamp — owner-lineage drift fix (2026-06-22)
# A manager-spawned worker stamps spawned_by + the persona-at-spawn SNAPSHOT
# (spawned_by_persona) onto its bridge so the arbiter resolves the TRUE spawning
# manager for a finished/dead worker WITHOUT re-deriving the manager session's
# drift-prone CURRENT persona.
# ═════════════════════════════════════════════════════════════════════════════

class TestSpawnLineageStamp:
    def test_persona_snapshot_stamped_on_bridge( self, isolated_session_dir, patched_main, monkeypatch ):
        """COSA_VOICE_SPAWNED_BY_PERSONA present → frozen onto the bridge."""
        monkeypatch.setenv( "COSA_VOICE_SPAWNED_BY",         "mgr-session-uuid" )
        monkeypatch.setenv( "COSA_VOICE_SPAWNED_BY_PERSONA", "Mr. Radio" )
        monkeypatch.setenv( "COSA_VOICE_ROLE",               "author" )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge[ "spawned_by" ]         == "mgr-session-uuid"
        assert bridge[ "spawned_by_persona" ] == "Mr. Radio"      # the frozen snapshot
        assert bridge[ "role" ]               == "author"
        assert bridge[ "speakerphone_on" ]    is False

    def test_no_persona_env_omits_snapshot( self, isolated_session_dir, patched_main, monkeypatch ):
        """spawned_by present but NO persona env → snapshot omitted (legacy path:
        resolver falls back to re-derivation). The False branch of the stamp gate."""
        monkeypatch.setenv(  "COSA_VOICE_SPAWNED_BY", "mgr-session-uuid" )
        monkeypatch.delenv( "COSA_VOICE_SPAWNED_BY_PERSONA", raising=False )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert bridge[ "spawned_by" ] == "mgr-session-uuid"
        assert "spawned_by_persona" not in bridge

    def test_no_spawned_by_env_no_lineage_stamp( self, isolated_session_dir, patched_main, monkeypatch ):
        """No COSA_VOICE_SPAWNED_BY (an ordinary interactive session) → the whole
        lineage block is skipped; no spawned_by / spawned_by_persona on the bridge.
        (Explicit delenv because a SPAWNED test-runner inherits the var.)"""
        monkeypatch.delenv( "COSA_VOICE_SPAWNED_BY",         raising=False )
        monkeypatch.delenv( "COSA_VOICE_SPAWNED_BY_PERSONA", raising=False )

        register_session.main()

        bridge = _read_bridge( isolated_session_dir )
        assert "spawned_by" not in bridge
        assert "spawned_by_persona" not in bridge
