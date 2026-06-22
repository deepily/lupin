"""
Tests for lib.subagent_governance — the manager-autonomy §2.2 worker-creation
channel rule enforced at the PreToolUse hook.

Covers: default-off, tool-name gate, crew-manager role signal (spawn manifest),
fail-open on error, and the deny-envelope shape. Uses an injected session_dir
(tmp_path) so no real ~/.claude/sessions is touched.

Run: pytest src/tests/unit/test_subagent_governance.py -v
"""

import json

import pytest

from pathlib import Path

from lupin_cli.claude_code.hooks.lib.subagent_governance import (
    subagent_deny_reason,
    build_subagent_deny_response,
    _is_crew_manager,
    _is_manager_persona,
    _session_dir,
    _governance_enabled,
    _manager_personas,
    DENY_REASON,
)


def _write_manifest( session_dir, session_id, records ):
    safe = "".join( c if c.isalnum() or c in "-_" else "_" for c in session_id )
    ( session_dir / f"spawned-{safe}.json" ).write_text( json.dumps( records ) )


# ── enable flag ────────────────────────────────────────────────────────────────

def test_governance_disabled_by_default():
    assert _governance_enabled( env={} ) is False

@pytest.mark.parametrize( "val", [ "1", "true", "TRUE", "on", "yes" ] )
def test_governance_enabled_truthy_values( val ):
    assert _governance_enabled( env={ "LUPIN_SUBAGENT_GOVERNANCE": val } ) is True

@pytest.mark.parametrize( "val", [ "", "0", "false", "off", "no", "garbage" ] )
def test_governance_disabled_other_values( val ):
    assert _governance_enabled( env={ "LUPIN_SUBAGENT_GOVERNANCE": val } ) is False


# ── decision logic (enabled forced True via kwarg) ───────────────────────────────

def test_disabled_allows_even_a_manager( tmp_path ):
    _write_manifest( tmp_path, "mgr-1", [ { "session_id": "w1" } ] )
    # enabled defaults to the (unset) env → False → allow
    assert subagent_deny_reason( "Task", "mgr-1", session_dir=tmp_path ) is None

def test_non_subagent_tool_is_allowed( tmp_path ):
    _write_manifest( tmp_path, "mgr-1", [ { "session_id": "w1" } ] )
    assert subagent_deny_reason( "Bash", "mgr-1", enabled=True, session_dir=tmp_path ) is None
    assert subagent_deny_reason( "Edit", "mgr-1", enabled=True, session_dir=tmp_path ) is None

def test_non_manager_may_use_task( tmp_path ):
    # no manifest → solo session (e.g. Explore) → allowed
    assert subagent_deny_reason( "Task", "solo-1", enabled=True, session_dir=tmp_path ) is None

def test_empty_manifest_is_not_a_manager( tmp_path ):
    _write_manifest( tmp_path, "mgr-empty", [ ] )   # spawned nothing → not a crew
    assert subagent_deny_reason( "Task", "mgr-empty", enabled=True, session_dir=tmp_path ) is None

def test_crew_manager_task_is_denied( tmp_path ):
    _write_manifest( tmp_path, "mgr-1", [ { "session_id": "w1" }, { "session_id": "w2" } ] )
    reason = subagent_deny_reason( "Task", "mgr-1", enabled=True, session_dir=tmp_path )
    assert reason == DENY_REASON
    assert "spawn_sessions" in reason

def test_empty_session_id_is_not_a_manager( tmp_path ):
    assert subagent_deny_reason( "Task", "", enabled=True, session_dir=tmp_path ) is None


# ── role signal (manifest sanitization matches session_spawner) ──────────────────

def test_is_crew_manager_reads_sanitized_manifest( tmp_path ):
    # a session id with a non-alnum char → sanitized to '_'
    _write_manifest( tmp_path, "abc/def", [ { "session_id": "w1" } ] )
    assert _is_crew_manager( "abc/def", session_dir=tmp_path ) is True
    assert _is_crew_manager( "no-manifest", session_dir=tmp_path ) is False

def test_is_crew_manager_corrupt_manifest_is_false( tmp_path ):
    safe = "mgr-corrupt"
    ( tmp_path / f"spawned-{safe}.json" ).write_text( "{ not json" )
    assert _is_crew_manager( safe, session_dir=tmp_path ) is False


# ── fail-open ────────────────────────────────────────────────────────────────────

def test_fail_open_on_unexpected_error():
    class Boom:
        # a session_dir whose / operator raises → exercises the except → allow
        def __truediv__( self, other ): raise RuntimeError( "boom" )
    assert subagent_deny_reason( "Task", "mgr-1", enabled=True, session_dir=Boom() ) is None


# ── persona signal (standing manager-figures; catches the founding case) ─────────

# deterministic canon for tests: lowercase, alnum-only ("Mr. Radio" → "mrradio")
_CANON = lambda s: "".join( c for c in str( s ).lower() if c.isalnum() )
# Managers are DERIVED from the fleet roster (no hand-set LUPIN_MANAGER_PERSONAS):
# the roster var supplies Mr. Radio + Tiberius; the preferred-persona chain HEAD
# supplies María. → manager set = {Mr. Radio, Tiberius, María}.
_MGR_ENV = {
    "COSA_VOICE_MANAGERS__LUPIN"          : "Mr. Radio, Tiberius",
    "COSA_VOICE_PREFERRED_PERSONA__PLAN"  : "María,*",
}


def test_manager_persona_denied_without_any_manifest( tmp_path ):
    # no manifest at all, but the session's persona is a standing manager-figure
    reason = subagent_deny_reason(
        "Task", "sid-x", enabled=True, session_dir=tmp_path, env=_MGR_ENV,
        persona_fn=lambda sid: { "name": "María" }, canon_fn=_CANON,
    )
    assert reason == DENY_REASON

def test_manager_persona_match_is_canonical( tmp_path ):
    # bridge says "mr radio"; list says "Mr. Radio" → canonical match → denied
    reason = subagent_deny_reason(
        "Task", "sid-x", enabled=True, session_dir=tmp_path, env=_MGR_ENV,
        persona_fn=lambda sid: { "name": "mr radio" }, canon_fn=_CANON,
    )
    assert reason == DENY_REASON

def test_non_manager_persona_allowed( tmp_path ):
    reason = subagent_deny_reason(
        "Task", "sid-x", enabled=True, session_dir=tmp_path, env=_MGR_ENV,
        persona_fn=lambda sid: { "name": "Rio" }, canon_fn=_CANON,
    )
    assert reason is None

def test_empty_manager_list_disables_persona_signal( tmp_path ):
    # No roster / preferred-persona vars at all → derived manager list empty →
    # persona signal off → a manager-named persona is NOT denied on this signal.
    reason = subagent_deny_reason(
        "Task", "sid-x", enabled=True, session_dir=tmp_path, env={},
        persona_fn=lambda sid: { "name": "María" }, canon_fn=_CANON,
    )
    assert reason is None

def test_unreadable_persona_is_not_a_manager( tmp_path ):
    reason = subagent_deny_reason(
        "Task", "sid-x", enabled=True, session_dir=tmp_path, env=_MGR_ENV,
        persona_fn=lambda sid: None, canon_fn=_CANON,
    )
    assert reason is None


# ── manager-persona derivation (roster union + preferred-persona heads) ──────────

def test_manager_personas_empty_env_is_empty():
    assert _manager_personas( env={} ) == [ ]

def test_manager_personas_defaults_to_os_environ():
    # env=None → reads os.environ; just prove it resolves to a list without raising.
    assert isinstance( _manager_personas(), list )

def test_manager_personas_roster_union_across_repos():
    env = {
        "COSA_VOICE_MANAGERS__LUPIN" : "Mr. Radio, Tiberius",
        "COSA_VOICE_MANAGERS__PLAN"  : "María",
    }
    assert _manager_personas( env ) == [ "Mr. Radio", "Tiberius", "María" ]

def test_manager_personas_preferred_head_only_skips_tail_and_wildcard():
    # The chain HEAD is a manager; the tail and the "*" wildcard are NOT.
    env = { "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "Mr. Radio, Tiberius, *" }
    assert _manager_personas( env ) == [ "Mr. Radio" ]

def test_manager_personas_lone_wildcard_head_is_skipped():
    env = { "COSA_VOICE_PREFERRED_PERSONA__X": "*" }
    assert _manager_personas( env ) == [ ]

def test_manager_personas_dedup_roster_and_preferred_overlap():
    # Mr. Radio appears in BOTH the roster and as a preferred head → once only.
    env = {
        "COSA_VOICE_MANAGERS__LUPIN"          : "Mr. Radio, Tiberius",
        "COSA_VOICE_PREFERRED_PERSONA__LUPIN" : "Mr. Radio, Tiberius, *",
        "COSA_VOICE_PREFERRED_PERSONA__PLAN"  : "María, *",
    }
    assert _manager_personas( env ) == [ "Mr. Radio", "Tiberius", "María" ]

def test_manager_personas_skips_blank_roster_entries():
    env = { "COSA_VOICE_MANAGERS__LUPIN": "Mr. Radio,, Tiberius," }
    assert _manager_personas( env ) == [ "Mr. Radio", "Tiberius" ]

def test_manager_personas_ignores_unrelated_env_keys():
    env = { "PATH": "/usr/bin", "HOME": "/home/x", "COSA_VOICE_ROLE": "worker" }
    assert _manager_personas( env ) == [ ]


def test_session_dir_is_home_claude_sessions():
    # Matches session_spawner.SESSION_DIR — the manifest directory the role
    # signal reads when no session_dir is injected.
    assert _session_dir() == Path.home() / ".claude" / "sessions"


def test_is_manager_persona_fails_open_when_persona_fn_raises():
    # FAIL-OPEN helper: a non-empty manager list but a persona lookup that blows
    # up → swallow the error → False (a governance check never breaks a tool call).
    def _boom( _sid ):
        raise RuntimeError( "bridge read exploded" )
    assert _is_manager_persona(
        "sid-x", env=_MGR_ENV, persona_fn=_boom, canon_fn=_CANON,
    ) is False


def test_is_manager_persona_lazy_imports_real_bridge_helpers():
    # persona_fn/canon_fn OMITTED + a non-empty derived manager list → the real
    # session_bridge helpers are lazily imported; an unknown session id has no
    # persona → not a manager. (Deterministic coverage of the import branch,
    # independent of the ambient os.environ roster.)
    assert _is_manager_persona( "no-such-session-xyz", env=_MGR_ENV ) is False


# ── deny envelope ────────────────────────────────────────────────────────────────

def test_build_subagent_deny_response_shape():
    env = build_subagent_deny_response( "because" )
    out = env[ "hookSpecificOutput" ]
    assert out[ "hookEventName" ] == "PreToolUse"
    assert out[ "permissionDecision" ] == "deny"
    assert out[ "permissionDecisionReason" ] == "because"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
