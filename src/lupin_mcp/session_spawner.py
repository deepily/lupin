"""
Host-side orchestration for manager-spawned headless reviewer sessions.

A "manager" Claude Code persona (e.g. Tiberius) calls the cosa-voice MCP tools
`spawn_sessions` / `dismiss_sessions` / `list_spawned_sessions`; those thin
@mcp.tool wrappers delegate to the pure-ish functions here. This module is the
testable brain: it renders the task brief, builds the headless spawn invocation,
enforces the spawn cap, records lineage to a per-manager manifest, and reaps.

Design notes:
    - The cosa-voice MCP server runs HOST-side (stdio subprocess of `claude`),
      so it — and this module — can run `tmux`/scripts. A container REST
      endpoint could not. See src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md.
    - Lineage is tracked in a manifest file keyed by the manager's session_id
      (`<SESSION_DIR>/spawned-<manager>.json`), written by the spawner at spawn
      time. This sidesteps the race where a freshly-spawned child's bridge file
      does not yet exist when spawn returns. `dismiss_sessions` reconciles the
      manifest against live tmux (kill-session is idempotent).
    - All side effects (subprocess, clock) are injected so the logic is unit
      testable to 100% without launching real tmux sessions or `claude`.

See: src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md
"""

import json
import os
import subprocess
from pathlib import Path
from typing  import Any, Callable, Dict, List, Optional


# Default ceiling on concurrent reviewers a single manager may spawn. Overridden
# at the call site by the INI key `cc session spawn max reviewers`.
DEFAULT_SPAWN_CAP = 8

# Directory holding session bridge + manifest files (mirrors session_bridge.py).
SESSION_DIR = Path.home() / ".claude" / "sessions"


# ── Subprocess runner (injectable) ───────────────────────────────────────────

def default_runner( argv: List[ str ], env: Optional[ Dict[ str, str ] ] = None ) -> "subprocess.CompletedProcess":
    """
    Real subprocess runner: run argv, capture output, never raise on non-zero.

    Requires:
        - argv is a non-empty list of strings
        - env is a dict of env overrides or None (None → inherit os.environ)

    Ensures:
        - Returns the CompletedProcess (returncode/stdout/stderr captured as text)
        - Never raises on a non-zero exit (check returncode at the call site)
        - A 30s timeout guards against a hung spawn

    Args:
        argv: command + args
        env:  full environment for the child (None → inherit)

    Returns:
        subprocess.CompletedProcess
    """
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=30,
        env=( { **os.environ, **env } if env else None )
    )


# ── Prompt rendering ──────────────────────────────────────────────────────────

def render_task_prompt(
    template     : str,
    tokens       : Optional[ Dict[ str, Any ] ] = None,
    seed_memento : Optional[ str ]              = None
) -> str:
    """
    Substitute {token} placeholders in a task template, optionally prepending a
    seed memento for author narrative continuity.

    Requires:
        - template is a string (may contain {role} {section} {scope_sentence}
          {cascade_name} {parent_topic} {manager_session_id} placeholders)
        - tokens is a dict of name→value or None
        - seed_memento is a string (prior-context blob) or None

    Ensures:
        - Each "{name}" occurrence whose name is in tokens is replaced by str(value)
        - Unknown placeholders are left intact (no KeyError — uses plain replace,
          not str.format, so stray braces in the template never raise)
        - When seed_memento is non-empty, it is APPENDED after the task as a
          trailing "Prior context (memento)" reference appendix — the task leads
          as the immediate actionable directive so a large memento never buries
          the instruction (Rick's directive 2026-05-28: append, not prepend)
        - Returns the rendered string; never raises

    Args:
        template: the task template
        tokens: placeholder substitutions
        seed_memento: optional prior-context blob to append as a reference

    Returns:
        str: the rendered task prompt
    """
    rendered = template
    for name, value in ( tokens or {} ).items():
        rendered = rendered.replace( "{" + name + "}", str( value ) )

    if seed_memento and seed_memento.strip():
        rendered = (
            f"{rendered}\n\n"
            "# Prior context (memento — your earlier work on this, for reference)\n"
            f"{seed_memento.strip()}"
        )
    return rendered


# ── Spawn invocation construction ─────────────────────────────────────────────

def build_spawn_argv(
    script_path  : str,
    session_name : str,
    task_prompt  : str,
    dry_run      : bool = False,
    claude_args  : Optional[ List[ str ] ] = None
) -> List[ str ]:
    """
    Build the argv for one headless spawn of start-cc-with-tmux.sh.

    Requires:
        - script_path is the path to start-cc-with-tmux.sh
        - session_name is a non-empty unique tmux session name
        - task_prompt is the rendered brief
        - claude_args is a list of pass-through claude args or None

    Ensures:
        - Returns ["bash", script_path, "--headless", (--dry-run?), session_name,
          *claude_args, "--prompt", task_prompt]
        - --dry-run is included iff dry_run is True
        - Never raises

    Args:
        script_path: path to the spawn script
        session_name: tmux session name
        task_prompt: rendered brief
        dry_run: include --dry-run
        claude_args: extra args forwarded to claude

    Returns:
        list[str]: argv
    """
    argv = [ "bash", script_path, "--headless" ]
    if dry_run:
        argv.append( "--dry-run" )
    argv.append( session_name )
    if claude_args:
        argv.extend( claude_args )
    argv.extend( [ "--prompt", task_prompt ] )
    return argv


# ── Manifest (lineage) persistence ────────────────────────────────────────────

def _manifest_path( manager_session_id: str, session_dir: Path = SESSION_DIR ) -> Path:
    """Path to the spawn manifest for a given manager session_id."""
    safe = "".join( c if c.isalnum() or c in "-_" else "_" for c in manager_session_id )
    return session_dir / f"spawned-{safe}.json"


def _read_manifest( path: Path ) -> List[ Dict[ str, Any ] ]:
    """
    Read a spawn manifest; return [] when absent or unreadable.

    Ensures:
        - Returns the list of spawn records, or [] on missing/corrupt file
        - Never raises
    """
    try:
        with open( path ) as f:
            data = json.load( f )
        return data if isinstance( data, list ) else []
    except ( FileNotFoundError, json.JSONDecodeError, OSError ):
        return []


def _write_manifest( path: Path, records: List[ Dict[ str, Any ] ] ) -> bool:
    """
    Write a spawn manifest atomically-ish; return success.

    Ensures:
        - Parent dir is created if missing
        - Returns True on success, False on OSError (never raises)
    """
    try:
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "w" ) as f:
            json.dump( records, f, indent=2 )
        return True
    except OSError:
        return False


# ── Orchestration ─────────────────────────────────────────────────────────────

def spawn_sessions(
    count              : int,
    task_prompt        : str,
    manager_session_id : str,
    *,
    script_path        : str,
    manager_persona    : Optional[ str ] = None,
    role               : str = "reviewer",
    project            : str = "lupin",
    persona_preference : Optional[ Any ] = None,
    seed_memento       : Optional[ str ] = None,
    tokens             : Optional[ Dict[ str, Any ] ] = None,
    spawn_cap          : int = DEFAULT_SPAWN_CAP,
    dry_run            : bool = False,
    runner             : Callable = default_runner,
    session_dir        : Path = SESSION_DIR
) -> Dict[ str, Any ]:
    """
    Spawn `count` headless reviewer sessions; record lineage to the manager's
    manifest; return the spawned roster.

    Requires:
        - count is an int (validated: 1..spawn_cap)
        - task_prompt is a non-empty template string
        - manager_session_id is a non-empty string
        - script_path points to start-cc-with-tmux.sh
        - runner is a callable(argv, env=None) -> CompletedProcess-like

    Ensures:
        - Raises ValueError when count < 1 or count > spawn_cap (predictable cap,
          no silent truncation)
        - Renders the task prompt once per child with per-child tokens merged in
          ({role}, {manager_session_id}, {index} always provided)
        - Spawns each child via runner(build_spawn_argv(...)); a child whose
          runner returns non-zero is recorded with status "failed" (others still
          proceed — partial success is reported, not raised)
        - On a NON-dry-run, appends successful spawns to the manager's manifest
        - Returns { spawned: [ {session_name, requested_role, status, ...} ],
                    manager_session_id, collection_topic, dry_run, requested,
                    persona_preference }
        - Never raises except the cap ValueError

    Args:
        count: number of reviewers
        task_prompt: brief template
        manager_session_id: the spawning manager's session id (lineage key)
        script_path: spawn script path
        role: requested role label (templated into the prompt)
        project: project for the child (sets cwd / CLAUDE.md)
        persona_preference: echoed into the result (allocation honored host-side
            by the child's SessionStart; predictable-fail is enforced there)
        seed_memento: optional prior-context blob for author continuity
        tokens: extra template tokens
        spawn_cap: max children
        dry_run: pass --dry-run; do not persist the manifest
        name_prefix: tmux session name prefix
        runner: injected subprocess runner
        session_dir: injected session/manifest directory

    Returns:
        dict: spawn result roster
    """
    if count < 1:
        raise ValueError( f"count must be ≥ 1 (got {count})" )
    if count > spawn_cap:
        raise ValueError( f"count {count} exceeds spawn cap {spawn_cap}" )

    # Collection + naming key on the manager PERSONA (dm-{persona}), matching the
    # existing commons DM convention + cascade_heartbeat_scheduler.dm_topic_for().
    # The manifest itself stays keyed on session_id (globally unique lineage).
    topic_key        = _slug( manager_persona ) if manager_persona else _slug( manager_session_id )
    collection_topic = f"dm-{topic_key}"
    base             = f"cc-{_slug( role )}-{topic_key}"

    # Names key on ROLE + manager + a lowest-free index computed across the live
    # manifest. This avoids collisions across (a) roles — reviewers vs an author
    # for the same manager — and (b) batches — a second reviewer batch continues
    # past the first. Without it, every call restarted at index 1 and an author
    # would clash with reviewer #1's tmux session (the script would silently skip
    # it). (Caught by the 3-reviewer+author dry-run 2026-05-28.)
    used    = { r[ "session_name" ] for r in _read_manifest( _manifest_path( manager_session_id, session_dir ) ) }
    spawned = []
    n       = 0

    for _k in range( count ):
        n += 1
        while f"{base}-{n}" in used:
            n += 1
        session_name = f"{base}-{n}"
        used.add( session_name )
        merged       = { "role": role, "manager_session_id": manager_session_id, "index": n }
        merged.update( tokens or {} )
        rendered     = render_task_prompt( task_prompt, merged, seed_memento )

        argv = build_spawn_argv( script_path, session_name, rendered, dry_run=dry_run )
        env  = {
            "COSA_VOICE_SPAWNED_BY" : manager_session_id,
            "COSA_VOICE_HEADLESS"   : "1",
            "COSA_VOICE_ROLE"       : role
        }
        result = runner( argv, env=env )
        ok     = getattr( result, "returncode", 1 ) == 0

        spawned.append( {
            "session_name"   : session_name,
            "requested_role" : role,
            "project"        : project,
            "status"         : "spawned" if ok else "failed",
            "dry_run"        : dry_run
        } )

    if not dry_run:
        successful = [ s for s in spawned if s[ "status" ] == "spawned" ]
        if successful:
            path    = _manifest_path( manager_session_id, session_dir )
            records = _read_manifest( path )
            records.extend( successful )
            _write_manifest( path, records )

    return {
        "spawned"            : spawned,
        "manager_session_id" : manager_session_id,
        "manager_persona"    : manager_persona,
        "collection_topic"   : collection_topic,
        "persona_preference" : persona_preference,
        "requested"          : count,
        "dry_run"            : dry_run
    }


def dismiss_sessions(
    manager_session_id : str,
    *,
    session_names      : Optional[ List[ str ] ] = None,
    reason             : str = "",
    write_memento      : bool = True,
    runner             : Callable = default_runner,
    session_dir        : Path = SESSION_DIR
) -> Dict[ str, Any ]:
    """
    Reap reviewer sessions this manager spawned: kill their tmux sessions and
    drop them from the manifest.

    Requires:
        - manager_session_id is a non-empty string
        - session_names is a list of tmux session names to reap, or None for ALL
          sessions in this manager's manifest
        - runner is a callable(argv, env=None) -> CompletedProcess-like

    Ensures:
        - For each target, runs `tmux kill-session -t <name>` via runner
          (idempotent: already-dead sessions are fine — reported "already_gone")
        - Removes reaped names from the manifest; rewrites it (or deletes it when
          empty)
        - `reason` and `write_memento` are echoed in the result (write_memento
          coordination — surfacing a final memento prompt to the child before
          kill — is handled by the MCP wrapper's pre-kill DM; this function does
          the teardown)
        - Returns { dismissed: [ {session_name, status} ], manager_session_id,
                    reason, write_memento, remaining }
        - Never raises

    Args:
        manager_session_id: lineage key
        session_names: explicit targets, or None = all mine
        reason: recorded teardown reason
        write_memento: echoed; the wrapper gives the child a chance to write one
        runner: injected subprocess runner
        session_dir: injected session/manifest directory

    Returns:
        dict: dismissal result
    """
    path    = _manifest_path( manager_session_id, session_dir )
    records = _read_manifest( path )
    known   = [ r[ "session_name" ] for r in records ]

    targets   = session_names if session_names is not None else list( known )
    dismissed = []

    for name in targets:
        result = runner( [ "tmux", "kill-session", "-t", name ] )
        ok     = getattr( result, "returncode", 1 ) == 0
        dismissed.append( {
            "session_name" : name,
            "status"       : "killed" if ok else "already_gone"
        } )

    reaped_names = { d[ "session_name" ] for d in dismissed }
    remaining    = [ r for r in records if r[ "session_name" ] not in reaped_names ]

    if remaining:
        _write_manifest( path, remaining )
    else:
        try:
            path.unlink()
        except ( FileNotFoundError, OSError ):
            pass

    return {
        "dismissed"          : dismissed,
        "manager_session_id" : manager_session_id,
        "reason"             : reason,
        "write_memento"      : write_memento,
        "remaining"          : [ r[ "session_name" ] for r in remaining ]
    }


def list_spawned_sessions(
    manager_session_id : str,
    *,
    runner             : Callable = default_runner,
    session_dir        : Path = SESSION_DIR
) -> Dict[ str, Any ]:
    """
    List the sessions this manager spawned, with live/dead status from tmux.

    Requires:
        - manager_session_id is a non-empty string
        - runner is a callable(argv, env=None) -> CompletedProcess-like

    Ensures:
        - For each manifest entry, probes `tmux has-session -t <name>` via runner;
          returncode 0 → "live", else "dead"
        - Returns { sessions: [ {session_name, requested_role, status, alive} ],
                    manager_session_id, count }
        - Never raises (a missing manifest yields an empty list)

    Args:
        manager_session_id: lineage key
        runner: injected subprocess runner
        session_dir: injected session/manifest directory

    Returns:
        dict: roster with liveness
    """
    path    = _manifest_path( manager_session_id, session_dir )
    records = _read_manifest( path )
    out     = []

    for r in records:
        name   = r[ "session_name" ]
        result = runner( [ "tmux", "has-session", "-t", name ] )
        alive  = getattr( result, "returncode", 1 ) == 0
        out.append( {
            "session_name"   : name,
            "requested_role" : r.get( "requested_role", "reviewer" ),
            "status"         : "live" if alive else "dead",
            "alive"          : alive
        } )

    return {
        "sessions"           : out,
        "manager_session_id" : manager_session_id,
        "count"              : len( out )
    }


def reap_stale_spawned(
    manager_session_id : str,
    *,
    is_stale           : Callable,
    reason             : str = "idle-ttl auto-reap",
    runner             : Callable = default_runner,
    session_dir        : Path = SESSION_DIR
) -> Dict[ str, Any ]:
    """
    Idle-TTL auto-reap backstop (decision #3): reap spawned sessions the
    `is_stale` predicate flags, so a crashed/forgotten manager never strands
    reviewers burning OAuth.

    The staleness PREDICATE is injected — the host-side caller supplies one that
    checks the child's bridge mtime against the configured idle TTL (and/or tmux
    liveness); this keeps the reap LOGIC unit-testable without real bridges/tmux.

    Requires:
        - manager_session_id is a non-empty string
        - is_stale is a callable(session_name) -> bool
        - runner is a callable(argv, env=None) -> CompletedProcess-like

    Ensures:
        - Scans this manager's manifest; reaps (via dismiss_sessions) exactly the
          session_names for which is_stale(name) is True
        - When none are stale, returns { reaped: [], remaining: [all names] }
          without touching tmux or the manifest
        - When some are stale, delegates to dismiss_sessions (idempotent kill +
          manifest update) and returns its result augmented with reaped=stale
        - Never raises

    Args:
        manager_session_id: lineage key
        is_stale: predicate flagging a session_name as idle/dead
        reason: teardown reason recorded on the reap
        runner: injected subprocess runner
        session_dir: injected session/manifest directory

    Returns:
        dict: reap result
    """
    path    = _manifest_path( manager_session_id, session_dir )
    records = _read_manifest( path )
    stale   = [ r[ "session_name" ] for r in records if is_stale( r[ "session_name" ] ) ]

    if not stale:
        return { "reaped": [], "remaining": [ r[ "session_name" ] for r in records ] }

    result = dismiss_sessions(
        manager_session_id, session_names=stale, reason=reason,
        write_memento=False, runner=runner, session_dir=session_dir
    )
    result[ "reaped" ] = stale
    return result


def resolve_manager_identity(
    cc_meta             : Optional[ Dict[ str, Any ] ],
    fallback_session_id : Optional[ str ] = None
) -> "tuple":
    """
    Extract (manager_session_id, manager_persona) from a session-bridge metadata
    dict (as returned by session_bridge.get_session_metadata).

    Requires:
        - cc_meta is the bridge metadata dict or None
        - fallback_session_id is used when the bridge has no session id

    Ensures:
        - manager_session_id prefers stable_session_id, then session_id, then the
          fallback (lineage must be stable across /clear → prefer the stable id)
        - manager_persona is voice_persona.name, falling back to display_name,
          else None (the spawner then slugs the session_id for the topic)
        - Never raises (treats None/missing fields gracefully)

    Args:
        cc_meta: session bridge metadata
        fallback_session_id: last-resort session id

    Returns:
        (manager_session_id, manager_persona)
    """
    meta    = cc_meta or {}
    vp      = meta.get( "voice_persona" ) or {}
    persona = vp.get( "name" ) or vp.get( "display_name" )
    sid     = meta.get( "stable_session_id" ) or meta.get( "session_id" ) or fallback_session_id
    return sid, persona


def resolve_spawn_config( config_mgr: Any ) -> Dict[ str, Any ]:
    """
    Resolve spawn-related INI keys via a ConfigurationManager, with defaults.

    Requires:
        - config_mgr is a ConfigurationManager (or test double exposing
          .get(key, default=, return_type=, silent=)) or None

    Ensures:
        - Returns { spawn_cap, ack_timeout_seconds, write_memento_default } with
          documented defaults (8, 120, True) when config_mgr is None or a key is
          absent
        - Never raises

    Args:
        config_mgr: configuration source or None

    Returns:
        dict of resolved spawn config
    """
    cap = DEFAULT_SPAWN_CAP
    ack = 120
    wm  = True
    if config_mgr is not None:
        cap = config_mgr.get( "cc session spawn max reviewers",
                              default=DEFAULT_SPAWN_CAP, return_type="int", silent=True )
        ack = config_mgr.get( "cc session spawn reviewer ack timeout seconds",
                              default=120, return_type="int", silent=True )
        wm  = config_mgr.get( "cc session spawn write memento default",
                              default=True, return_type="boolean", silent=True )
    return { "spawn_cap": cap, "ack_timeout_seconds": ack, "write_memento_default": wm }


def _slug( text: str ) -> str:
    """
    Lowercase, keep alnum/-/_, collapse other runs to a single '-'. For session
    names + DM topics — matches the dm-{persona} convention (e.g. "Mr. Radio" →
    "mr-radio") used by cascade_heartbeat_scheduler.dm_topic_for / PG-6 slug.
    """
    out = "".join( c if c.isalnum() or c in "-_" else "-" for c in text.strip().lower() )
    while "--" in out:
        out = out.replace( "--", "-" )
    return out.strip( "-" ) or "anon"


# ── Quick smoke test ──────────────────────────────────────────────────────────

def quick_smoke_test():
    """Self-contained smoke test using a fake runner + temp manifest dir."""
    import tempfile

    print( "session_spawner smoke test" )
    print( "===========================" )

    class _FakeRunner:
        def __init__( self ): self.calls = []
        def __call__( self, argv, env=None ):
            self.calls.append( ( argv, env ) )
            class _R: returncode = 0; stdout = argv[ -1 ]; stderr = ""
            return _R()

    # render: token substitution + memento prepend
    r = render_task_prompt( "Review {section} as {role}", { "section": "A", "role": "reviewer" } )
    assert r == "Review A as reviewer", r
    r2 = render_task_prompt( "do {x}", { "x": "y" }, seed_memento="I wrote this plan." )
    assert "Prior context" in r2 and "do y" in r2
    # unknown placeholder left intact, no raise
    assert render_task_prompt( "keep {unknown}", {} ) == "keep {unknown}"
    print( "  ✓ render_task_prompt: tokens, memento, unknown-placeholder safe" )

    with tempfile.TemporaryDirectory() as tmp:
        sd     = Path( tmp )
        runner = _FakeRunner()

        # cap enforcement (flag pattern — no unreachable assert lines)
        over_capped = under_capped = False
        try:
            spawn_sessions( 99, "t", "mgr", script_path="x", spawn_cap=8, runner=runner, session_dir=sd )
        except ValueError:
            over_capped = True
        try:
            spawn_sessions( 0, "t", "mgr", script_path="x", runner=runner, session_dir=sd )
        except ValueError:
            under_capped = True
        assert over_capped and under_capped, "cap bounds must raise ValueError"

        # spawn 3 → manifest has 3; topic keys on PERSONA, manifest on session_id
        res = spawn_sessions( 3, "Review {section}", "mgr-abc", script_path="x",
                              manager_persona="Tiberius", role="reviewer",
                              runner=runner, session_dir=sd, tokens={ "section": "A" } )
        assert len( res[ "spawned" ] ) == 3
        assert res[ "collection_topic" ] == "dm-tiberius"
        assert res[ "manager_persona" ] == "Tiberius"
        assert res[ "spawned" ][ 0 ][ "session_name" ] == "cc-reviewer-tiberius-1"
        assert all( s[ "status" ] == "spawned" for s in res[ "spawned" ] )
        listed = list_spawned_sessions( "mgr-abc", runner=runner, session_dir=sd )
        assert listed[ "count" ] == 3 and all( s[ "alive" ] for s in listed[ "sessions" ] )
        print( "  ✓ spawn 3 → manifest + list (all live)" )

        # dismiss one → 2 remain
        one = res[ "spawned" ][ 0 ][ "session_name" ]
        d   = dismiss_sessions( "mgr-abc", session_names=[ one ], runner=runner, session_dir=sd )
        assert d[ "dismissed" ][ 0 ][ "status" ] == "killed"
        assert len( d[ "remaining" ] ) == 2
        # dismiss all (None) → manifest deleted
        d2 = dismiss_sessions( "mgr-abc", runner=runner, session_dir=sd )
        assert d2[ "remaining" ] == []
        assert not _manifest_path( "mgr-abc", sd ).exists()
        print( "  ✓ dismiss (explicit + all) reaps + clears manifest" )

        # dry-run does NOT persist
        dr = spawn_sessions( 2, "t", "mgr-dry", script_path="x", dry_run=True, runner=runner, session_dir=sd )
        assert dr[ "dry_run" ] and not _manifest_path( "mgr-dry", sd ).exists()
        print( "  ✓ dry-run leaves no manifest" )

        # idle-TTL auto-reap: predicate flags one of two as stale
        spawn_sessions( 2, "t", "mgr-reap", script_path="x", manager_persona="Rio",
                        runner=runner, session_dir=sd )
        none_stale = reap_stale_spawned( "mgr-reap", is_stale=lambda n: False, runner=runner, session_dir=sd )
        assert none_stale[ "reaped" ] == [] and len( none_stale[ "remaining" ] ) == 2
        one_stale  = reap_stale_spawned( "mgr-reap", is_stale=lambda n: n.endswith( "-1" ),
                                         runner=runner, session_dir=sd )
        assert one_stale[ "reaped" ] == [ "cc-reviewer-rio-1" ]
        assert one_stale[ "remaining" ] == [ "cc-reviewer-rio-2" ]
        print( "  ✓ reap_stale_spawned reaps only predicate-flagged sessions" )

        # role in the name + lowest-free index across roles AND batches
        author = spawn_sessions( 1, "t", "mgr-roles", script_path="x", manager_persona="Rio",
                                 role="author", runner=runner, session_dir=sd )
        assert author[ "spawned" ][ 0 ][ "session_name" ] == "cc-author-rio-1"
        spawn_sessions( 3, "t", "mgr-batch", script_path="x", manager_persona="Rio", runner=runner, session_dir=sd )
        batch2 = spawn_sessions( 2, "t", "mgr-batch", script_path="x", manager_persona="Rio", runner=runner, session_dir=sd )
        assert [ s[ "session_name" ] for s in batch2[ "spawned" ] ] == [ "cc-reviewer-rio-4", "cc-reviewer-rio-5" ]
        print( "  ✓ role-in-name + lowest-free index across roles/batches (no collision)" )

    print( "\nAll session_spawner smoke tests: ✓ passed" )


if __name__ == "__main__":  # pragma: no cover  # CLI entry point; body exercised by the unit suite
    quick_smoke_test()
