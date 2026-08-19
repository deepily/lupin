"""
Subagent governance (manager-autonomy §2.2 — the worker-creation channel rule).

Denies a CREW-MANAGER session's Agent/Task (in-process subagent) tool calls and
redirects to spawn_sessions. An in-process subagent runs under the spawning
session with NO persona and NO bridge → it never registers in the fleet roster
or focus bar → invisible + ungovernable. The Agent/Task tool is reserved for a
WORKER parallelizing its OWN assigned task; a manager staffs a crew via
spawn_sessions. See planning-is-prompting → workflow/manager-autonomy.md §2.2.

ROLE SIGNAL (no new marker needed): a session is a crew-manager iff it has a
non-empty spawn manifest at ~/.claude/sessions/spawned-<safe-id>.json — written
by session_spawner.spawn_sessions when it spawns workers. A session that has not
spawned anyone (e.g. a solo builder using read-only Explore) has no manifest and
is NOT blocked — which also resolves the scope question (block crew-managers,
not all Agent-tool use everywhere).

SAFETY — this runs inside the hot-path PreToolUse hook (every tool call, every
session), so two non-negotiables:
  • DEFAULT-OFF: gated behind the LUPIN_SUBAGENT_GOVERNANCE env flag (unset →
    inert → byte-identical to today). Activation = set the flag in the session
    launch env; no global-config edit.
  • FAIL-OPEN: ANY error → allow (return None). A governance check must never
    break a tool call.
"""
import json
import os
from pathlib import Path
from typing import Optional

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir


# The Claude Code subagent tool's hook `tool_name`.
SUBAGENT_TOOL_NAMES = ( "Task", )

_ENV_FLAG = "LUPIN_SUBAGENT_GOVERNANCE"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# Standing manager-figure personas are DERIVED from the single fleet roster
# (no separate hand-set list — the retired LUPIN_MANAGER_PERSONAS). Two env-var
# families, both forwarded into every session by start-cc-with-tmux.sh:
#   • COSA_VOICE_MANAGERS__<PROJECT>          — the declared-manager roster
#     (~/.claude/fleet-roster.env), comma-separated names; UNION across all repos.
#   • COSA_VOICE_PREFERRED_PERSONA__<PROJECT> — the per-repo preferred-persona
#     CHAIN; every NAMED element (the "*" wildcard excluded) is a standing
#     manager for that repo.
# Design: src/rnd/2026.06.22-fleet-roster-to-user-level-migration-spec.md §5.
#
# ⚠️ CHAIN-TAIL SEMANTICS CHANGED 2026-08-18 (row a1a84682). This module used to
# take the chain HEAD only, while manager_figure.resolve_implicit_manager_figure
# — the predicate that gates task-store WRITES — takes EVERY named element. Two
# consumers, the same string, two different answers about who is a manager. The
# launcher now derives the chain from the roster (`<roster>,*`), so the two agree
# by construction there; taking every named element here makes them agree off the
# launcher path too, instead of only where the roster happens to name the tail.
_ROSTER_PREFIX    = "COSA_VOICE_MANAGERS__"
_PREFERRED_PREFIX = "COSA_VOICE_PREFERRED_PERSONA__"
_CHAIN_WILDCARD   = "*"

DENY_REASON = (
    "Crew managers create workers via spawn_sessions, NOT the Agent/Task tool. "
    "In-process subagents have no persona/bridge — they never register in the "
    "fleet roster or focus bar, so they are invisible and ungovernable. The "
    "Agent/Task tool is reserved for a WORKER parallelizing its OWN assigned "
    "task. Staff your crew with spawn_sessions instead. (manager-autonomy.md §2.2)"
)


def _governance_enabled( env=None ) -> bool:
    """True iff the LUPIN_SUBAGENT_GOVERNANCE flag is set truthy (default-off)."""
    env = env if env is not None else os.environ
    return str( env.get( _ENV_FLAG, "" ) ).strip().lower() in _TRUE_VALUES


def _session_dir() -> Path:
    """The spawn-manifest directory (matches session_spawner.SESSION_DIR)."""
    return sessions_dir()   # row 8ccc20ab: the one seam


def _is_crew_manager( session_id, session_dir: Optional[ Path ] = None ) -> bool:
    """
    True iff this session has a non-empty spawn manifest (it has spawned workers).

    Mirrors session_spawner._manifest_path sanitization + _read_manifest exactly
    so the role signal is read from the same file the spawner writes.

    Ensures:
        - returns False for an empty session_id, a missing/corrupt manifest, or
          an empty manifest list; never raises
    """
    if not session_id:
        return False
    session_dir = session_dir if session_dir is not None else _session_dir()
    safe = "".join( c if c.isalnum() or c in "-_" else "_" for c in str( session_id ) )
    path = session_dir / f"spawned-{safe}.json"
    try:
        with open( path ) as f:
            data = json.load( f )
        return isinstance( data, list ) and len( data ) > 0
    except ( FileNotFoundError, json.JSONDecodeError, OSError, ValueError ):
        return False


def _manager_personas( env=None ) -> list:
    """
    Derive the standing manager-figure persona names from the fleet roster.

    Sources (both env-var families are forwarded into every session by
    start-cc-with-tmux.sh; the hook reads whichever the launch env carries):
      • every COSA_VOICE_MANAGERS__<PROJECT> var — comma-separated roster, taken
        as a UNION across all repos (a manager-figure in ANY repo is standing);
      • every COSA_VOICE_PREFERRED_PERSONA__<PROJECT> var — every NAMED chain
        element is that repo's standing manager, matching what
        manager_figure.resolve_implicit_manager_figure reads; the "*" wildcard
        is not a name and is never a manager.

    Ensures:
        - returns the de-duplicated names in first-seen order (roster vars first,
          then preferred heads), empty when neither family is present
    """
    env  = env if env is not None else os.environ
    seen = set()
    out  = []

    def _add( name ):
        name = name.strip()
        if name and name != _CHAIN_WILDCARD and name not in seen:
            seen.add( name )
            out.append( name )

    for key, val in env.items():
        if key.startswith( _ROSTER_PREFIX ):
            for n in str( val ).split( "," ):
                _add( n )
    for key, val in env.items():
        if key.startswith( _PREFERRED_PREFIX ):
            for n in str( val ).split( "," ):
                _add( n )                          # every named element; _add drops "*"
    return out


def _is_manager_persona( session_id, env=None, persona_fn=None, canon_fn=None ) -> bool:
    """
    True iff this session's voice-persona is a standing manager-figure derived
    from the fleet roster (see _manager_personas).

    This is the second role signal (besides the spawn manifest): it catches an
    AD-HOC manager-figure who only ever uses subagents and never spawns (the
    founding 2026-06-22 case) — the manifest signal can't see that session.
    Persona names are matched via canonical_persona_key (accent/case-insensitive)
    on BOTH sides, so "Mr. Radio" / "mr radio" / "María" all resolve correctly.

    Ensures:
        - False when the manager list is empty, the persona is unreadable, or no
          match; never raises (fail-open helper)
    """
    personas = _manager_personas( env )
    if not personas:
        return False
    try:
        if persona_fn is None or canon_fn is None:
            from lupin_cli.claude_code.hooks.lib.session_bridge import (
                get_voice_persona, canonical_persona_key,
            )
            persona_fn = persona_fn or get_voice_persona
            canon_fn   = canon_fn   or canonical_persona_key
        pdict = persona_fn( session_id )
        name  = pdict.get( "name" ) if isinstance( pdict, dict ) else None
        if not name:
            return False
        mine = canon_fn( name )
        return any( canon_fn( m ) == mine for m in personas )
    except Exception:
        return False


def subagent_deny_reason(
    tool_name,
    session_id,
    *,
    enabled     : Optional[ bool ] = None,
    session_dir : Optional[ Path ] = None,
    env         = None,
    persona_fn  = None,
    canon_fn    = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a CREW-MANAGER session is invoking the
    Agent/Task subagent tool while governance is enabled; else None (allow).

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - session_id is the resolved (stable) session id
        - enabled / session_dir are None (resolved from env / home) or injected
          for testing

    Ensures:
        - None unless ALL hold: governance enabled, tool_name is a subagent tool,
          and the session is a crew-manager (non-empty spawn manifest)
        - FAIL-OPEN: any unexpected error → None (a hot-path hook never breaks a
          tool call over a governance check)
    """
    try:
        if enabled is None:
            enabled = _governance_enabled( env )
        if not enabled:
            return None
        if tool_name not in SUBAGENT_TOOL_NAMES:
            return None
        # Two role signals (EITHER → crew-manager): (1) a non-empty spawn manifest
        # (has spawned workers); (2) the session's persona is a standing manager-
        # figure DERIVED from the fleet roster (COSA_VOICE_MANAGERS__* union +
        # COSA_VOICE_PREFERRED_PERSONA__* heads) — catches the ad-hoc manager who
        # only subagents and never spawns (the founding case the manifest can't see).
        is_manager = (
            _is_crew_manager( session_id, session_dir=session_dir )
            or _is_manager_persona( session_id, env=env, persona_fn=persona_fn, canon_fn=canon_fn )
        )
        if is_manager:
            return DENY_REASON
        return None
    except Exception:
        return None


def build_subagent_deny_response( reason: str ) -> dict:
    """
    Build the PreToolUse deny envelope (mirrors hook_common.build_voice_deny_response).

    Ensures:
        - returns { hookSpecificOutput: { hookEventName: "PreToolUse",
          permissionDecision: "deny", permissionDecisionReason: <reason> } }
    """
    return {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : reason,
        }
    }
