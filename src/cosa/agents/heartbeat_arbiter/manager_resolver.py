#!/usr/bin/env python3
"""
Heartbeat-Arbiter manager resolution (v2.2 closed-loop, lane B6 / decision D5).

Resolve a stuck worker's MANAGER for the manager-tap DM (B2) from spawn-lineage,
so — with multiple groups — each stuck worker routes to ITS OWN manager
automatically. **Never hardcode a persona name** (D5).

The PRIMARY lineage source is the child bridge's `spawned_by` field — the
manager's real session id, globally unique, collision-proof:

    worker session_id
      → bridge.spawned_by              (find_session_by_id)
      → manager persona                (get_voice_persona)

For LEGACY bridges that predate `spawned_by`, the resolver falls back to the
original multi-hop manifest join. That join is keyed by tmux session_NAME,
which is persona-indexed and REUSED (`cc-<role>-<persona>-<N>` recurs across
every same-persona manager session and survives in stale manifests), so it is
structurally ambiguous — the multi-match guard below then refuses to guess:

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
import os
from pathlib import Path
from typing import Callable, Optional

from lupin_mcp.session_spawner import SESSION_DIR, _read_manifest, _manifest_path
# F-B (2026.06.11 lineage-persistence design): THE one persona-equivalence
# normalizer — the allocation/DM path's own ("Mr. Radio"/"mr radio" → "mrradio").
# Persona strings drift structurally across signal sources (bridge = display
# casing; event-sourced fallback = lowercase punct-stripped), so every declared-
# roster compare in this module is normalize-keyed; display casing untouched.
from lupin_mcp.persona_normalization import canonical_persona_key


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


def _id_matches( a, b ):
    """Prefix-tolerant session-id match (short 8-char event ids vs full uuids)."""
    if not a or not b:
        return False
    return a == b or a.startswith( b ) or b.startswith( a )


def list_manager_session_ids( session_dir: Path = SESSION_DIR ):
    """
    Enumerate every MANAGER session-id that owns a (round-trip-valid) spawn manifest.

    The inverse of `find_manager_session_id`: instead of resolving ONE worker's
    manager, list ALL managers — a session is a manager iff it spawned ≥1 child
    (a `spawned-<id>.json` manifest exists). The id is parsed from the filename
    and trusted ONLY if it round-trips `_manifest_path(id).name == filename` (same
    guard as find_manager_session_id — a lossy/non-round-tripping name is skipped).

    Requires:
        - session_dir is the spawn-manifest directory

    Ensures:
        - returns a set of manager session-ids (one per round-trip-valid manifest)
        - returns an empty set on OSError / missing dir (degrade-safe)
        - never raises
    """
    try:
        manifests = sorted( session_dir.glob( f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}" ) )
    except OSError:
        return set()
    ids = set()
    for path in manifests:
        manager_id = path.name[ len( _MANIFEST_PREFIX ) : -len( _MANIFEST_SUFFIX ) ]
        if manager_id and _manifest_path( manager_id, session_dir ).name == path.name:
            ids.add( manager_id )
    return ids


def resolve_active_managers(
    who_rows,
    bridge_sessions,
    *,
    list_managers     : Optional[ Callable ] = None,
    session_dir       : Path                 = SESSION_DIR,
    declared_managers : Optional[ list ]     = None,
):
    """
    Resolve the managers ON DUTY for the Part-6 fleet-crisis fanout (Rick + ALL
    active managers), phantom-guarded.

    A persona is an ACTIVE MANAGER iff it satisfies BOTH:
      (1) MANAGER-ROLE — its session owns a spawn-lineage manifest (it spawned
          ≥1 child; via `list_managers`) OR its persona is in the DECLARED
          manager roster (`declared_managers`, from COSA_VOICE_MANAGERS__<PROJECT>
          — a declared manager counts even before its first spawn; Rick 2026-06-11).
      (2) PROCESS-ALIVE — its session is present in `bridge_sessions` (the
          PID + mtime-filtered live-bridge discovery, `find_active_voice_persona_sessions`).
          This is the PHANTOM GUARD: a reaped manager whose commons `last_post_ts`
          LINGERS in `who_rows` is EXCLUDED, because its dead bridge is absent from
          bridge_sessions. (Raw commons_who is the phantom-prone signal — bridge
          presence is the authoritative process-liveness axis, per the Round-1
          union doctrine.) The guard applies to DECLARED managers identically —
          declaration grants role, never liveness.

    `who_rows` (commons_who) SEEDS the candidate set (a manager visible on commons
    OR discovered via its bridge); the bridge-presence check then GUARDS it. The
    persona name prefers the authoritative bridge value, falling back to the
    who-row persona.

    Requires:
        - who_rows is a list of commons_who rows (dicts) or None
        - bridge_sessions is { session_id: persona_name|None } (the arbiter's
          bridge discovery) or None
        - declared_managers is a list of persona names or None

    Ensures:
        - returns a SORTED list of DISTINCT active-manager personas
        - includes a declared persona iff a LIVE bridge carries it
          (punct/case-tolerant match via the shared persona normalizer — F-B;
          the bridge's casing is emitted — the bridge is the authoritative
          name surface)
        - excludes non-managers (no manifest AND not declared) AND phantoms
          (commons-recent but no live bridge) AND managers with no DM-able persona
        - never raises
    """
    list_managers   = list_managers   if list_managers   is not None else list_manager_session_ids
    who_rows        = who_rows        or [ ]
    bridge_sessions = bridge_sessions or { }
    # F-B: canonical-keyed declared set (the journal-confirmed "mr radio" vs
    # "Mr. Radio" miss also broke this fanout site). canonical_persona_key is
    # the one identity root; symmetric on both compare sides + store-key parity.
    declared_norm   = { canonical_persona_key( str( name ) ) for name in ( declared_managers or [ ] )
                        if canonical_persona_key( str( name ) ) }

    try:
        manager_ids = list_managers( session_dir )
    except Exception:
        manager_ids = set()
    if not manager_ids and not declared_norm:
        return [ ]

    def _is_manager( sid ):
        return any( _id_matches( sid, mid ) for mid in manager_ids )

    # candidate manager sessions: commons-active (who_rows) ∪ bridge-present, ∩ role
    candidates = { }                                   # session_id -> persona|None
    for row in who_rows:
        sid = row.get( "session_id" ) if isinstance( row, dict ) else None
        if sid and _is_manager( sid ):
            candidates[ sid ] = row.get( "persona_name" )
    for sid, persona in bridge_sessions.items():
        if not sid:
            continue
        # DECLARED roster: a live-bridge persona in the declared set is a
        # manager regardless of manifest ownership (role-by-declaration).
        if _is_manager( sid ) or ( persona and canonical_persona_key( persona ) in declared_norm ):
            candidates[ sid ] = persona or candidates.get( sid )

    # PHANTOM GUARD: keep only sessions with a LIVE bridge (PID-alive), with a persona
    alive = set()
    for sid, persona in candidates.items():
        if persona and any( _id_matches( sid, bsid ) for bsid in bridge_sessions ):
            alive.add( persona )
    return sorted( alive )


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
        - the manager_session_id comes from the child bridge's `spawned_by`
          (PRIMARY — authoritative, globally unique), falling back to the
          tmux_session → manifest-name scan ONLY when `spawned_by` is
          absent/empty (legacy bridges that predate the field)
        - PERSONA-AT-SPAWN SNAPSHOT (owner-lineage drift fix, 2026-06-22): when
          the bridge carries BOTH `spawned_by` AND a non-blank `spawned_by_persona`
          (the manager persona FROZEN at spawn), the manager persona is read from
          that snapshot — NEVER re-derived from the manager session's CURRENT
          persona. Re-derivation (`persona_lookup(spawned_by)`) DRIFTS as personas
          recycle across /clear/compaction, so a finished/dead worker would be
          mis-attributed to the manager's LATER persona (and carry_forward_lineage
          would cache that wrong value into death). The snapshot is worker-keyed
          and immune to that drift. Re-derivation remains ONLY for legacy bridges
          predating the snapshot (snapshot absent/blank/non-string).
        - "lineage" requires BOTH a manager_session_id (via either source) AND
          a DM-able manager persona; a hit without a usable persona degrades
          (never DM a None persona)
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
        bridge    = bridge_lookup( worker_session_id )
        is_bridge = isinstance( bridge, dict )
        # PRIMARY: spawned_by = the manager's real session id — unique, so the
        # persona-indexed-name collision (cc-<role>-<persona>-<N> reused across
        # sessions + stale manifests) cannot arise on this path.
        manager_id = bridge.get( "spawned_by" ) if is_bridge else None
        # PERSONA-AT-SPAWN SNAPSHOT: the manager persona FROZEN onto the worker
        # bridge at spawn. Normalize to a stripped str ("" when absent/blank/
        # non-string) so the short-circuit below is a clean truthiness test.
        snapshot   = bridge.get( "spawned_by_persona" ) if is_bridge else None
        snapshot   = snapshot.strip() if isinstance( snapshot, str ) else ""
        if manager_id and snapshot:
            # Frozen attribution — immune to the manager session's persona drift.
            return { "manager_session_id": manager_id, "manager_persona": snapshot, "source": SOURCE_LINEAGE }
        if not manager_id:
            # FALLBACK (legacy bridges without spawned_by): manifest-name scan,
            # multi-match-guarded — ambiguity still degrades, never guesses.
            tmux       = bridge.get( "tmux_session" ) if is_bridge else None
            manager_id = manifest_scan( tmux, session_dir ) if tmux else None
        if not manager_id:
            return _fallback()
        # Legacy path only (no snapshot): re-derive the manager's CURRENT persona.
        persona = persona_lookup( manager_id )
        name    = persona.get( "name" ) if isinstance( persona, dict ) else None
        if not name:
            return _fallback()   # lineage id but no DM-able persona → don't guess
        return { "manager_session_id": manager_id, "manager_persona": name, "source": SOURCE_LINEAGE }
    except Exception:
        return _fallback()


def quick_smoke_test():
    """Self-contained smoke test with injected seams. Returns True or raises."""
    # lineage hit via spawned_by (PRIMARY) — manifest scan must NOT be consulted
    scan_calls = [ ]
    out = resolve_manager(
        "worker-0",
        bridge_lookup  = lambda sid: { "tmux_session": "cc-reviewer-tib-1", "spawned_by": "tib-uuid-real" },
        manifest_scan  = lambda tmux, sd: scan_calls.append( tmux ),
        persona_lookup = lambda mid: { "name": "Tiberius" } if mid == "tib-uuid-real" else None,
    )
    assert out == { "manager_session_id": "tib-uuid-real", "manager_persona": "Tiberius", "source": "lineage" }, out
    assert scan_calls == [ ], scan_calls   # spawned_by short-circuits the manifest scan

    # persona-at-spawn SNAPSHOT wins over a DRIFTED re-derivation (owner-lineage
    # drift fix): the frozen "Mr. Radio" beats persona_lookup's current "Tiberius".
    lookup_calls = [ ]
    out = resolve_manager(
        "dead-worker",
        bridge_lookup  = lambda sid: { "spawned_by": "mgr-uuid", "spawned_by_persona": "Mr. Radio" },
        persona_lookup = lambda mid: lookup_calls.append( mid ) or { "name": "Tiberius" },
    )
    assert out == { "manager_session_id": "mgr-uuid", "manager_persona": "Mr. Radio", "source": "lineage" }, out
    assert lookup_calls == [ ], lookup_calls   # snapshot short-circuits the drift-prone re-derivation

    # spawned_by present but persona un-DM-able → degrade, never guess
    out = resolve_manager(
        "worker-0",
        bridge_lookup  = lambda sid: { "spawned_by": "dead-mgr-uuid" },
        persona_lookup = lambda mid: None,
    )
    assert out[ "source" ] == "unresolved", out

    # lineage hit via manifest-scan FALLBACK (legacy bridge, no spawned_by)
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

    # active-managers resolver: role ∩ live-bridge, phantom EXCLUDED
    managers = resolve_active_managers(
        who_rows = [ { "session_id": "mgr-A", "persona_name": "Tiberius" },
                     { "session_id": "phantom-mgr", "persona_name": "Ghost" } ],  # lingering last-post
        bridge_sessions = { "mgr-A": "Tiberius", "worker-W": "Rio" },             # phantom NOT here (PID-dead)
        list_managers = lambda sd: { "mgr-A", "phantom-mgr" },                    # both are managers by role
    )
    assert managers == [ "Tiberius" ], managers   # worker excluded (no role); phantom excluded (no live bridge)
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"manager_resolver smoke: {'PASS' if ok else 'FAIL'}" )
