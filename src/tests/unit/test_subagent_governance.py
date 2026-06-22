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

from lupin_cli.claude_code.hooks.lib.subagent_governance import (
    subagent_deny_reason,
    build_subagent_deny_response,
    _is_crew_manager,
    _governance_enabled,
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
_MGR_ENV = { "LUPIN_MANAGER_PERSONAS": "Tiberius,Mr. Radio,María" }


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
    reason = subagent_deny_reason(
        "Task", "sid-x", enabled=True, session_dir=tmp_path, env={ "LUPIN_MANAGER_PERSONAS": "" },
        persona_fn=lambda sid: { "name": "María" }, canon_fn=_CANON,
    )
    assert reason is None

def test_unreadable_persona_is_not_a_manager( tmp_path ):
    reason = subagent_deny_reason(
        "Task", "sid-x", enabled=True, session_dir=tmp_path, env=_MGR_ENV,
        persona_fn=lambda sid: None, canon_fn=_CANON,
    )
    assert reason is None


# ── deny envelope ────────────────────────────────────────────────────────────────

def test_build_subagent_deny_response_shape():
    env = build_subagent_deny_response( "because" )
    out = env[ "hookSpecificOutput" ]
    assert out[ "hookEventName" ] == "PreToolUse"
    assert out[ "permissionDecision" ] == "deny"
    assert out[ "permissionDecisionReason" ] == "because"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
