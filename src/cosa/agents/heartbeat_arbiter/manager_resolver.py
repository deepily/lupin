#!/usr/bin/env python3
"""
Heartbeat-Arbiter manager resolution (v2.2 closed-loop, lane B6 / decision D5).

Resolve a stuck worker's MANAGER for the manager-tap DM (B2) from spawn-lineage,
so — with multiple groups — each stuck worker routes to ITS OWN manager
automatically. **Never hardcode a persona name** (D5).

The join is multi-hop because the spawn-lineage manifest is keyed by tmux
session_NAME, not the child's CC session_id, and stores neither the manager's
session_id nor the child's:

    worker session_id
      → bridge.tmux_session            (find_session_by_id)
      → manifest record session_name match across ~/.claude/sessions/spawned-*.json
      → manager_session_id             (parsed from the manifest FILENAME)
      → manager persona                (get_voice_persona)

The manager id is parsed from `spawned-<id>.json`. That filename is produced by
`session_spawner._manifest_path`, whose inline slugify maps non-[alnum-_] chars
to "_" (it does NOT truncate — confirmed; no length cap → no truncation
collision surface). Real CC session_ids are UUIDs (hex + hyphens) for which the
slugify is the identity, so the round-trip is exact.

Two collision/robustness guards (María's B6 review anchors) keep "never a
wrong-manager DM" airtight:
  • **Round-trip guard** — trust a parsed id ONLY if `_manifest_path(id).name`
    reproduces the actual filename EXACTLY (re-applying the *same* transform that
    produced it, not a different slug). A lossy/non-round-tripping filename →
    skip → unresolved.
  • **Multi-match guard** — if the worker's tmux_session resolves to MORE THAN
    ONE manager-id (collision / cross-manifest ambiguity), return None →
    unresolved. Exactly-one-else-escalate.

**Layered degradation (D5 + Tiberius's escalate-don't-guess):**
  lineage (a single manager_session_id AND a DM-able persona both resolve)
    → declared manager-on-duty fallback (config)
      → UNRESOLVED → caller escalates to Rick.
**Prefer UNRESOLVED over a wrong-manager DM** on any brittle/ambiguous hop.
Never raises.
"""
from pathlib import Path
from typing import Callable, Optional

from lupin_mcp.session_spawner import SESSION_DIR, _read_manifest, _manifest_path


SOURCE_LINEAGE    = "lineage"
SOURCE_DECLARED   = "declared"
SOURCE_UNRESOLVED = "unresolved"

_MANIFEST_PREFIX = "spawned-"
_MANIFEST_SUFFIX = ".json"


def find_manager_session_id( tmux_session: str, session_dir: Path = SESSION_DIR ) -> Optional[ str ]:
    """
    Scan the spawn manifests for the manager that spawned `tmux_session`.

    Requires:
        - tmux_session is the child's tmux session name (manifest join key)

    Ensures:
        - returns the manager_session_id parsed from the matching manifest's
          filename iff EXACTLY ONE manager-id resolves, where a resolution
          requires (i) a manifest record with that session_name AND (ii) the
          parsed id round-trips `_manifest_path(id).name == filename` (the same
          transform that produced the filename — guards the lossy edge)
        - returns None on: no match · empty/missing tmux_session · a brittle
          (non-round-tripping) filename · MULTI-MATCH (>1 manager-id resolves —
          collision / cross-manifest ambiguity → escalate-don't-guess) · OSError
        - never raises
    """
    if not tmux_session:
        return None
    try:
        manifests = sorted( session_dir.glob( f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}" ) )
    except OSError:
        return None
    matches = [ ]
    for path in manifests:
        records = _read_manifest( path )
        if not any( isinstance( r, dict ) and r.get( "session_name" ) == tmux_session
                    for r in records ):
            continue
        manager_id = path.name[ len( _MANIFEST_PREFIX ) : -len( _MANIFEST_SUFFIX ) ]
        # Round-trip guard against the EXACT transform that produced the filename
        # (_manifest_path's slugify, NOT _slug). A non-round-tripping filename is
        # lossy → skip it (contributes no clean match → unresolved).
        if manager_id and _manifest_path( manager_id, session_dir ).name == path.name:
            matches.append( manager_id )
    # Multi-match guard (María): exactly-one-else-unresolved. Zero or >1 distinct
    # manager-ids resolving to this worker → ambiguous → escalate-don't-guess.
    unique = set( matches )
    if len( unique ) == 1:
        return matches[ 0 ]
    return None


def _default_bridge_lookup( session_id ):   # pragma: no cover - IO boundary
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
    return find_session_by_id( session_id )


def _default_persona_lookup( session_id ):   # pragma: no cover - IO boundary
    from lupin_cli.claude_code.hooks.lib.session_bridge import get_voice_persona
    return get_voice_persona( session_id )


def resolve_manager(
    worker_session_id,
    *,
    declared_manager : Optional[ str ]      = None,
    bridge_lookup    : Optional[ Callable ] = None,
    persona_lookup   : Optional[ Callable ] = None,
    manifest_scan    : Optional[ Callable ] = None,
    session_dir      : Path                 = SESSION_DIR,
) -> dict:
    """
    Resolve a worker's manager (D5), layered with escalate-don't-guess.

    Requires:
        - worker_session_id is a session id string

    Ensures:
        - returns { manager_session_id, manager_persona, source } where source ∈
          { "lineage", "declared", "unresolved" }
        - "lineage" requires BOTH a manager_session_id (via the spawn-lineage
          join) AND a DM-able manager persona; a hit without a usable persona
          degrades (never DM a None persona)
        - on a lineage miss → "declared" (the config manager-on-duty fallback) if
          provided, else "unresolved"
        - on ANY error/brittle hop → degrades the same way (declared else
          unresolved); NEVER mis-routes, NEVER raises
        - "unresolved" signals the caller to escalate to Rick
    """
    bridge_lookup  = bridge_lookup  or _default_bridge_lookup
    persona_lookup = persona_lookup or _default_persona_lookup
    manifest_scan  = manifest_scan  or find_manager_session_id

    def _fallback():
        if declared_manager:
            return { "manager_session_id": None, "manager_persona": declared_manager, "source": SOURCE_DECLARED }
        return { "manager_session_id": None, "manager_persona": None, "source": SOURCE_UNRESOLVED }

    try:
        bridge = bridge_lookup( worker_session_id )
        tmux   = bridge.get( "tmux_session" ) if isinstance( bridge, dict ) else None
        manager_id = manifest_scan( tmux, session_dir ) if tmux else None
        if not manager_id:
            return _fallback()
        persona = persona_lookup( manager_id )
        name    = persona.get( "name" ) if isinstance( persona, dict ) else None
        if not name:
            return _fallback()   # lineage id but no DM-able persona → don't guess
        return { "manager_session_id": manager_id, "manager_persona": name, "source": SOURCE_LINEAGE }
    except Exception:
        return _fallback()


def quick_smoke_test():
    """Self-contained smoke test with injected seams. Returns True or raises."""
    # lineage hit
    out = resolve_manager(
        "worker-1",
        bridge_lookup  = lambda sid: { "tmux_session": "cc-reviewer-tib-0" },
        manifest_scan  = lambda tmux, sd: "tib-uuid" if tmux == "cc-reviewer-tib-0" else None,
        persona_lookup = lambda mid: { "name": "Tiberius" },
    )
    assert out == { "manager_session_id": "tib-uuid", "manager_persona": "Tiberius", "source": "lineage" }, out

    # lineage miss → declared fallback
    out = resolve_manager( "w", declared_manager="manager-on-duty",
                           bridge_lookup=lambda sid: { "tmux_session": "x" },
                           manifest_scan=lambda tmux, sd: None )
    assert out[ "source" ] == "declared" and out[ "manager_persona" ] == "manager-on-duty"

    # no bridge + no declared → unresolved
    out = resolve_manager( "w", bridge_lookup=lambda sid: None )
    assert out[ "source" ] == "unresolved"

    # error → fallback (unresolved here)
    out = resolve_manager( "w", bridge_lookup=lambda sid: ( _ for _ in () ).throw( RuntimeError() ) )
    assert out[ "source" ] == "unresolved"
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"manager_resolver smoke: {'PASS' if ok else 'FAIL'}" )
