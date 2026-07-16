"""
Orphan-session-bridge reaper (bug ee59d5ed, Change 2).

The lineage-independent half of the orphaned-session focus-bar fix. `dismiss_sessions`
can only reach sessions in a live manager's own spawn manifest, so when a spawner/manager
dies, its children's bridges are unreachable by any persona's dismiss — they linger, and
the operator's focus bar keeps rendering the dead sessions as ALIVE.

This module sweeps `~/.claude/sessions/cc-*.json` bridges directly (no manifest), and for
any bridge that is CONFIRMED dead — host PID confirmed-dead AND its tmux session gone AND
dead across `debounce_threshold` consecutive polls — emits the SAME reap signals a normal
`dismiss_sessions` emits (reusing `session_spawner`'s emitters): the persisted
`session_reaped` marker (which Change 1 turns into a durable, history-safe roster
eviction), the `kind="reaped"` tombstone (arbiter-snapshot eviction), a bridge unlink, and
a heartbeat-hold clear. It is designed to run once per heartbeat-arbiter poll (host-side,
where host PIDs are trustworthy).

Design: src/rnd/v0.1.9/2026.07.15-orphan-session-bridge-reap-survival.md

Every IO / decision / emit seam is injected with a real production default, so the sweep
runs with zero setup in production AND unit-tests to 100% with pure in-memory fakes — the
same pattern as `worktree_reaper.reconcile_worktrees`.
"""
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# Debounce sentinel: a session already reaped this run keeps this value in the
# cross-poll state so a lingering bridge (a failed unlink) is NEVER re-emitted.
# Stale keys (bridge gone) are pruned at end-of-sweep, so the dict stays bounded.
_REAPED_SENTINEL = -1

# Bridge filenames that are NOT sessions (never reap these).
_NON_SESSION_BRIDGE_TOKENS = ( "buffer", "listener" )


def _default_list_bridges( session_dir ):
    """List cc-*.json bridge files (excluding buffer/listener sidecars)."""
    if not session_dir.exists():
        return []
    return [
        p for p in session_dir.glob( "cc-*.json" )
        if not any( tok in p.name for tok in _NON_SESSION_BRIDGE_TOKENS )
    ]


def _default_read_bridge( path ):
    """Read + parse one bridge file (json)."""
    import json
    with open( path, "r", encoding="utf-8" ) as handle:
        return json.load( handle )


def _default_tmux_alive( tmux_session, runner=None ):
    """
    True iff `tmux has-session -t <name>` reports the session exists.

    Mirrors session_spawner.list_spawned_sessions' liveness probe. Bias-to-ALIVE:
    any probe failure (tmux missing, error) → treated as ALIVE, so a flaky probe
    can NEVER cause a reap. Reaping requires a POSITIVE "gone" (returncode != 0
    with a working tmux).
    """
    if not tmux_session:
        return False  # no tmux field → cannot be a live tmux-backed session
    import subprocess
    run = runner if runner is not None else (
        lambda argv: subprocess.run( argv, capture_output=True, text=True, timeout=5 )
    )
    try:
        result = run( [ "tmux", "has-session", "-t", tmux_session ] )
        return result.returncode == 0
    except Exception:
        return True  # probe broke → assume ALIVE (never reap on an unreliable probe)


def _bridge_pids( path, data, extract_pid_fn ):
    """All host PIDs a bridge carries: filename PID + listener_pid + cc_pid."""
    pids = []
    fname_pid = extract_pid_fn( path.name )
    if fname_pid is not None:
        pids.append( fname_pid )
    for key in ( "listener_pid", "cc_pid" ):
        val = data.get( key )
        if isinstance( val, int ):
            pids.append( val )
    return pids


def reconcile_orphan_bridges(
    dead_polls_state         : Dict[ str, int ],
    debounce_threshold       : int = 2,
    session_dir              : Optional[ Path ]     = None,
    list_fn                  : Optional[ Callable ] = None,
    read_fn                  : Optional[ Callable ] = None,
    trust_host_pids_fn       : Optional[ Callable ] = None,
    pid_confirmed_dead_fn    : Optional[ Callable ] = None,
    extract_pid_fn           : Optional[ Callable ] = None,
    tmux_alive_fn            : Optional[ Callable ] = None,
    capture_identity_fn      : Optional[ Callable ] = None,
    emit_reap_fn             : Optional[ Callable ] = None,
    emit_tombstone_fn        : Optional[ Callable ] = None,
    clear_hold_fn            : Optional[ Callable ] = None,
    unlink_fn                : Optional[ Callable ] = None,
    reason                   : str = "orphan-bridge janitor sweep (ee59d5ed)",
    debug                    : bool = False,
) -> Dict[ str, List ]:
    """
    Sweep orphaned session bridges once and reap the CONFIRMED-dead ones.

    Requires:
        - dead_polls_state is a caller-owned dict that PERSISTS across polls
          (the debounce counter; the arbiter/factory keeps one instance alive)
        - debounce_threshold >= 1

    Ensures:
        - No-ops (returns empty result, state untouched) when host PIDs are not
          trustworthy (inside a container — _can_trust_host_pids False)
        - A bridge is reaped ONLY when ALL hold: every host PID it carries is
          CONFIRMED dead (bias-to-alive), its tmux session is gone, AND it has
          been dead across >= debounce_threshold consecutive polls
        - A bridge with any live/ambiguous PID or a live/unprobeable tmux resets
          its debounce counter (re-arm) and is never reaped
        - On reap: emit session_reaped + tombstone, unlink the bridge, clear the
          hold — each fail-safe (a raising seam never aborts the sweep)
        - Idempotent: an already-reaped session is marked and never re-emitted;
          stale counter keys (bridge gone) are pruned so the state stays bounded
        - Never raises (a bad bridge lands in `errors`, the sweep continues)

    Returns:
        { "reaped": [ {session_id, sender_id, tmux_session} ],
          "skipped": [ {session_id|path, reason} ],
          "errors": [ str ] }
    """
    # Lazy-bind production defaults (import here so the module loads with no cosa
    # runtime + so tests inject pure fakes without touching the real helpers).
    if session_dir is None:
        from lupin_cli.claude_code.hooks.lib.session_bridge import SESSION_DIR
        session_dir = SESSION_DIR
    if trust_host_pids_fn is None:
        from lupin_cli.claude_code.hooks.lib.session_bridge import _can_trust_host_pids
        trust_host_pids_fn = _can_trust_host_pids
    if pid_confirmed_dead_fn is None:
        from lupin_cli.claude_code.hooks.lib.session_bridge import _pid_confirmed_dead
        pid_confirmed_dead_fn = _pid_confirmed_dead
    if extract_pid_fn is None:
        from lupin_cli.claude_code.hooks.lib.session_bridge import _extract_pid_from_filename
        extract_pid_fn = _extract_pid_from_filename
    if capture_identity_fn is None:
        from lupin_mcp.session_spawner import _capture_reap_identity
        capture_identity_fn = _capture_reap_identity
    if emit_reap_fn is None:
        from lupin_mcp.session_spawner import _default_emit_reap
        emit_reap_fn = _default_emit_reap
    if emit_tombstone_fn is None:
        from lupin_mcp.session_spawner import _default_emit_reaped_tombstone
        emit_tombstone_fn = _default_emit_reaped_tombstone
    if clear_hold_fn is None:
        from lupin_mcp.session_spawner import _default_clear_hold
        clear_hold_fn = _default_clear_hold
    list_fn      = list_fn      if list_fn      is not None else ( lambda: _default_list_bridges( session_dir ) )
    read_fn      = read_fn      if read_fn      is not None else _default_read_bridge
    tmux_alive_fn = tmux_alive_fn if tmux_alive_fn is not None else _default_tmux_alive
    unlink_fn    = unlink_fn    if unlink_fn    is not None else ( lambda p: Path( p ).unlink() )

    out: Dict[ str, List ] = { "reaped": [], "skipped": [], "errors": [] }

    # Container gate: host PIDs invisible inside Docker → kill(-0) reads the whole
    # fleet as dead. NEVER sweep there. State is left untouched.
    if not trust_host_pids_fn():
        if debug: print( "[orphan-bridge-reaper] host PIDs untrustworthy (container) — sweep skipped" )
        return out

    seen_keys = set()

    for path in list_fn():
        try:
            data = read_fn( path )
        except Exception as error:                       # unreadable / corrupt bridge
            out[ "errors" ].append( f"{path}: {error}" )
            continue

        session_id = data.get( "stable_session_id" ) or data.get( "session_id" )
        if not session_id:                               # cannot identify → never reap
            out[ "skipped" ].append( { "path": str( path ), "reason": "no session_id" } )
            continue
        seen_keys.add( session_id )

        # Already reaped in a prior poll but its bridge lingers (unlink failed):
        # do NOT re-emit. It will be pruned once the bridge finally disappears.
        if dead_polls_state.get( session_id ) == _REAPED_SENTINEL:
            out[ "skipped" ].append( { "session_id": session_id, "reason": "already reaped" } )
            continue

        pids         = _bridge_pids( path, data, extract_pid_fn )
        tmux_session = data.get( "tmux_session" )
        # Dual-confirm death: EVERY carried PID confirmed-dead AND tmux gone.
        pid_dead  = bool( pids ) and all( pid_confirmed_dead_fn( p ) for p in pids )
        tmux_gone = ( tmux_session is not None ) and ( not tmux_alive_fn( tmux_session ) )

        if not ( pid_dead and tmux_gone ):
            dead_polls_state.pop( session_id, None )     # re-arm — alive or unconfirmed
            out[ "skipped" ].append( { "session_id": session_id, "reason": "alive or unconfirmed" } )
            continue

        # Confirmed dead this poll — advance the debounce counter.
        count = dead_polls_state.get( session_id, 0 ) + 1
        dead_polls_state[ session_id ] = count
        if count < debounce_threshold:
            out[ "skipped" ].append(
                { "session_id": session_id, "reason": f"dead {count}/{debounce_threshold} polls" }
            )
            continue

        # Debounce satisfied → reap. Capture identity BEFORE unlink (sender_id +
        # persona derive from the bridge). Each seam fail-safe (dismiss ordering).
        identity = None
        try:
            identity = capture_identity_fn( session_dir, tmux_session )
        except Exception as error:
            out[ "errors" ].append( f"{session_id}: capture failed: {error}" )
        if identity is None:                             # bridge vanished between list + capture
            dead_polls_state[ session_id ] = _REAPED_SENTINEL
            out[ "skipped" ].append( { "session_id": session_id, "reason": "identity gone at reap" } )
            continue

        for seam, label in (
            ( lambda: emit_reap_fn( identity, reason ), "emit_reap" ),
            ( lambda: emit_tombstone_fn( identity ),    "emit_tombstone" ),
            ( lambda: unlink_fn( identity[ "bridge_path" ] ), "unlink" ),
            ( lambda: clear_hold_fn( identity ),        "clear_hold" ),
        ):
            try:
                seam()
            except Exception as error:                   # producer NEVER breaks the sweep
                out[ "errors" ].append( f"{session_id}: {label} failed: {error}" )

        dead_polls_state[ session_id ] = _REAPED_SENTINEL   # idempotency guard
        out[ "reaped" ].append( {
            "session_id"   : session_id,
            "sender_id"    : identity.get( "sender_id" ),
            "tmux_session" : tmux_session,
        } )
        if debug: print( f"[orphan-bridge-reaper] reaped {session_id} (sender {identity.get( 'sender_id' )})" )

    # Prune stale counters: any key not seen this poll (bridge gone — reaped +
    # unlinked, or simply vanished) is dropped so the state never grows unbounded.
    for key in [ k for k in dead_polls_state if k not in seen_keys ]:
        del dead_polls_state[ key ]

    return out
