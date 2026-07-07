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

from lupin_mcp.persona_normalization import persona_slug


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


# ── Persona-chain transport ───────────────────────────────────────────────────

def persona_chain_csv( persona_preference ) -> Optional[ str ]:
    """
    Normalize a spawn persona_preference (str | list | None) into the CSV
    form carried by the COSA_VOICE_PERSONA_CHAIN child env var.

    Requires:
        - persona_preference is a str, a list, or None

    Ensures:
        - Returns the stripped string when persona_preference is a non-empty
          string (already CSV or a single name — passed through verbatim)
        - Returns a comma-joined string of stripped non-empty string items
          when persona_preference is a list (non-string items skipped)
        - Returns None for None, empty/whitespace input, an empty list, or
          any other type — callers omit the env var entirely in that case
        - Never raises

    Examples:
        "Rio"                      → "Rio"
        "Rio, Krishna ,*"          → "Rio, Krishna ,*"   (server-side parser strips)
        [ "Rio", "Krishna", "*" ]  → "Rio,Krishna,*"
        [] / None / "   " / 42     → None
    """
    if isinstance( persona_preference, str ):
        stripped = persona_preference.strip()
        return stripped if stripped else None
    if isinstance( persona_preference, list ):
        items = [ item.strip() for item in persona_preference if isinstance( item, str ) and item.strip() ]
        return ",".join( items ) if items else None
    return None


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
    model              : Optional[ str ] = None,
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
        - When persona_preference is non-empty, injects it into EVERY child's
          environment as COSA_VOICE_PERSONA_CHAIN (CSV) — the child's
          SessionStart walks the chain strictly (first FREE element wins,
          `*` = "then take anything free", exhaustion without `*` = loud
          fail, never a silent random re-allocation). Each child walks the
          SAME chain and takes the first unclaimed element; sibling boots
          serialize via the server's atomic allocate-or-409.
        - When `model` is a non-empty string, forwards `--model <model>` to every
          child via the build_spawn_argv claude_args seam, so the child boots on
          that model instead of the user default (Fable-5-managers / Opus-4.8-
          workers cost split, 2026-07-02). When `model` is None/empty, NO --model
          flag is passed and the child inherits the user default (today's fail-open
          behavior). The resolved model is echoed on EVERY roster entry and at the
          top level (spawn-ack verification → verify-allocated-MODEL).
        - Returns { spawned: [ {session_name, requested_role, status, model, ...} ],
                    manager_session_id, collection_topic, dry_run, requested,
                    persona_preference, model }
        - Never raises except the cap ValueError

    Args:
        count: number of reviewers
        task_prompt: brief template
        manager_session_id: the spawning manager's session id (lineage key)
        script_path: spawn script path
        role: requested role label (templated into the prompt)
        project: project for the child (sets cwd / CLAUDE.md)
        persona_preference: str | list — ordered persona chain transported to
            the children via COSA_VOICE_PERSONA_CHAIN (see
            src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md)
        seed_memento: optional prior-context blob for author continuity
        tokens: extra template tokens
        spawn_cap: max children
        dry_run: pass --dry-run; do not persist the manifest
        model: resolved model id to pin via `--model` (None → inherit user default)
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

    # The DM/collection topic and the tmux SESSION name BOTH key on the manager
    # PERSONA, but with DIFFERENT separators — and they MUST stay separate
    # (Rick one-name mandate 2026-06-22). Coupling them through a single key is
    # precisely the divergence bug this fix closes:
    #
    #   • collection_topic → persona_slug( sep="_" ) → "dm-mr_radio" — THE canonical
    #     DM-topic form shared by _derive_dm_topic / _dm_topic_for / every
    #     *_gateway.dm_topic_for. The
    #     old sep="-" emitted "dm-mr-radio", a DIVERGENT topic string for
    #     MULTI-WORD personas (single-word personas have no internal space, so
    #     "dm-tiberius"/"dm-maria" are identical under either separator).
    #   • base session name → persona_slug( sep="-" ) → "cc-<role>-mr-radio-<n>" —
    #     the established tmux `cc-<role>-<persona>-<n>` convention that the sweep's
    #     scan_tmux_mismatches validates with sep="-". The field delimiter is '-';
    #     keeping the persona segment on sep="-" leaves the tmux parser + sweep
    #     UNTOUCHED (a deliberately-separate non-topic use). See the session-name
    #     caution in the persona-norm follow-on brief.
    #
    # Phase 3 accent-proofing is preserved on BOTH: persona_slug agrees with the
    # canonical store key, so "María" → "maria" (not the accent-leaky "maría" the
    # old `_slug` produced). `or "anon"` preserves `_slug`'s never-empty contract.
    # The fallback key is a SESSION ID (not a persona) → stays on `_slug` for BOTH
    # (hyphens survive, session-id path UNCHANGED); `role` is general text → also
    # stays on `_slug` (surgical: persona path only).
    dm_persona_key   = ( persona_slug( manager_persona, sep="_" ) or "anon" ) if manager_persona else _slug( manager_session_id )
    name_persona_key = ( persona_slug( manager_persona, sep="-" ) or "anon" ) if manager_persona else _slug( manager_session_id )
    collection_topic = f"dm-{dm_persona_key}"
    base             = f"cc-{_slug( role )}-{name_persona_key}"

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

        # Model-directive (2026-07-02): pin the child's model via the existing
        # claude_args pass-through seam. None/empty model → no flag → inherit the
        # user default (fail-open). The resolved model is chosen upstream (the MCP
        # wrapper's explicit-param → INI role key → INI default resolution).
        claude_args = [ "--model", model ] if model else None
        argv = build_spawn_argv( script_path, session_name, rendered, dry_run=dry_run, claude_args=claude_args )
        env  = {
            "COSA_VOICE_SPAWNED_BY" : manager_session_id,
            "COSA_VOICE_HEADLESS"   : "1",
            "COSA_VOICE_ROLE"       : role
        }
        # Owner-lineage drift fix (2026-06-22): freeze the manager's persona AS IT
        # IS NOW (spawn time) so the child can stamp it onto its bridge. The
        # arbiter then resolves a finished/dead worker's manager from this frozen
        # SNAPSHOT, never re-deriving the manager session's CURRENT persona (which
        # drifts as personas recycle). Only set when known (managers may spawn
        # without a resolved persona — then the child has no snapshot and the
        # resolver falls back to re-derivation, the legacy behavior).
        if manager_persona:
            env[ "COSA_VOICE_SPAWNED_BY_PERSONA" ] = manager_persona
        # Transport the persona chain to the child — THE missing link that
        # made spawn_sessions(persona_preference=...) a silent no-op for a
        # month (Rio→Krishna repros, root-caused 2026-06-11). The child's
        # SessionStart reads COSA_VOICE_PERSONA_CHAIN ahead of the per-repo
        # COSA_VOICE_PREFERRED_PERSONA__<PROJECT> default.
        chain_csv = persona_chain_csv( persona_preference )
        if chain_csv:
            env[ "COSA_VOICE_PERSONA_CHAIN" ] = chain_csv
        result = runner( argv, env=env )
        ok     = getattr( result, "returncode", 1 ) == 0

        spawned.append( {
            "session_name"   : session_name,
            "requested_role" : role,
            "project"        : project,
            "status"         : "spawned" if ok else "failed",
            "dry_run"        : dry_run,
            "model"          : model
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
        "dry_run"            : dry_run,
        "model"              : model
    }


def _capture_reap_identity( session_dir: Path, tmux_session: str ) -> Optional[ Dict[ str, Any ] ]:
    """
    Capture { bridge_path, persona, sender_id, session_id } for a soon-to-be-
    reaped tmux session by scanning `session_dir` for the bridge whose
    `tmux_session` field matches. MUST run BEFORE the bridge is unlinked
    (sender_id + persona both derive from the bridge). Returns None when no
    bridge matches or is unreadable. Never raises.
    """
    try:
        candidates = list( session_dir.glob( "cc-*.json" ) )
    except OSError:
        return None
    for path in candidates:
        if "buffer" in path.name or "listener" in path.name:
            continue
        try:
            data = json.loads( path.read_text() )
        except ( json.JSONDecodeError, OSError ):
            continue
        if data.get( "tmux_session" ) != tmux_session:
            continue
        session_id = data.get( "stable_session_id" ) or data.get( "session_id" )
        sender_id  = None
        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import build_sender_id_for_cc
            sender_id = build_sender_id_for_cc( session_id ) if session_id else None
        except Exception:
            pass
        return {
            "bridge_path" : path,
            "persona"     : data.get( "voice_persona" ),
            "sender_id"   : sender_id,
            "session_id"  : session_id,
        }
    return None


def _default_emit_reap( identity: Dict[ str, Any ], reason: str = "" ) -> None:
    """
    Default reap-event emitter (producer of Sam's reap-UI wiring, 2026-06-05):
    fire-and-forget POST of a `session_reaped` state-update onto the Lupin
    notification rail, envelope `sender_id` = the REAPED worker's sender_id
    (→ SenderStore drops its badge; the broadcast card refreshes). Best-effort:
    a down server / missing sender_id NEVER breaks a reap. Override via
    `dismiss_sessions(emit_reap_fn=...)` — tests inject a capture instead.

    Contract (locked with Sam): type="session_reaped", sender_id=reaped worker.
    """
    sender_id = identity.get( "sender_id" )
    if not sender_id:
        return
    try:
        import requests
        from cosa.utils.config_loader import get_api_config, load_api_key
        env     = os.getenv( "LUPIN_ENV", "local" )
        cfg     = get_api_config( env )
        api_key = load_api_key( cfg[ "api_key_file" ] )
        # /api/notify REQUIRES target_user — the reap event must route to the human
        # OWNER's UI (focus bar + broadcast card), not the worker. Resolve from the
        # dev/owner email (LUPIN_DEV_EMAIL), falling back to the configured recipient.
        target  = os.getenv( "LUPIN_DEV_EMAIL" ) or cfg.get( "global_notification_recipient" )
        if not target:
            return                          # can't route → skip (best-effort)
        persona = identity.get( "persona" ) if isinstance( identity.get( "persona" ), dict ) else { }
        name    = ( persona or { } ).get( "name" ) or "A worker"
        requests.post(
            f"{cfg[ 'api_url' ].rstrip( '/' )}/api/notify",
            params  = {
                "message"     : f"{name} reaped",
                "type"        : "session_reaped",
                "priority"    : "low",
                "sender_id"   : sender_id,
                "target_user" : target,
            },
            headers = { "X-API-Key": api_key },
            timeout = 3,
        )
    except Exception:
        pass  # producer must NEVER break the reap


def _default_emit_reaped_tombstone( identity: Dict[ str, Any ] ) -> None:
    """
    Default reap-TOMBSTONE emitter (reap-tombstone roster-eviction fix,
    2026-06-15): append ONE authoritative `kind="reaped"` record onto the fleet
    heartbeat-event rail the arbiter polls, so the reaped session's roster row is
    force-offlined in ~1 poll instead of lingering "stale" for ~60 min. The reap
    deletes the bridge FIRST (destroying the PID the fast kill-0 death path
    needs), so this marker is the only fast death signal a reaped session can
    carry. Reads the `session_id` captured pre-unlink by `_capture_reap_identity`
    and passes the worker's persona NAME for nicer audit lines. Best-effort: a
    missing session_id, a bad write, or any error NEVER breaks the reap. Override
    via `dismiss_sessions(emit_reaped_fn=...)` — tests inject a capture instead.
    """
    session_id = identity.get( "session_id" )
    if not session_id:
        return                              # no id → fall back to the ~60-min age-out
    persona = identity.get( "persona" )
    name    = persona.get( "name" ) if isinstance( persona, dict ) else persona
    try:
        from lupin_cli.claude_code.hooks.lib.heartbeat_events import emit_reaped
        emit_reaped( session_id, persona=name )
    except Exception:
        pass  # producer must NEVER break the reap


def _default_clear_hold( identity: Dict[ str, Any ] ) -> bool:
    """
    Default hold-clearer (ping-storm durable Fix 1, 2026-06-24): delete the
    reaped session's `.heartbeat-hold-<sid>.json` so the arbiter stops
    re-deriving phantom "X is blocking Y" edges from an ORPHANED hold every poll.

    The reap already deletes the BRIDGE; the hold is a SEPARATE dotfile the
    arbiter's `read_hold` polls, and it lingered until TTL+6h (the janitor's
    grace) — long enough to seed phantom blocker pings every backoff window. The
    hold lives in the project root `read_hold` resolves (base_dir default =
    cu.get_project_root), so clearing by the captured session_id targets EXACTLY
    the artifact the arbiter sees. Best-effort: a missing session_id or any error
    NEVER breaks the reap. Override via `dismiss_sessions(clear_hold_fn=...)` —
    tests inject a capture instead.

    Ensures:
        - returns True iff a session_id was present AND clear_hold was invoked
        - returns False for a missing session_id (nothing to clear) or a
          swallowed error
        - never raises
    """
    session_id = identity.get( "session_id" )
    if not session_id:
        return False
    try:
        from lupin_cli.claude_code.hooks.lib.heartbeat_hold import clear_hold
        clear_hold( session_id )
        return True
    except Exception:
        return False


def _identity_persona_name( identity ):
    """
    Extract the persona NAME from a captured reap identity. `voice_persona` may be
    a dict ({name, ...}) or a bare string; returns the name string, or None when
    absent. Mirrors the dict-or-string handling in `_default_emit_reaped_tombstone`.
    """
    persona = identity.get( "persona" ) if identity else None
    if isinstance( persona, dict ):
        return persona.get( "name" )
    return persona


def _resolve_session_persona_name( session_dir, session_id ):
    """
    Resolve the voice_persona NAME for a `session_id` by scanning `session_dir`
    bridges — the SAME identity surface as `_capture_reap_identity`, but matched on
    stable_session_id/session_id instead of tmux_session. Used to learn the REAPING
    MANAGER's persona for the reap-reconcile orphan guard, since the MCP wrapper
    threads only `manager_session_id` (not the persona).

    Best-effort: returns None on a missing id, no match, an unreadable/non-JSON
    bridge, or a glob error. Never raises.
    """
    if not session_id:
        return None
    try:
        candidates = list( session_dir.glob( "cc-*.json" ) )
    except OSError:
        return None
    for path in candidates:
        if "buffer" in path.name or "listener" in path.name:
            continue
        try:
            data = json.loads( path.read_text() )
        except ( json.JSONDecodeError, OSError ):
            continue
        if data.get( "stable_session_id" ) == session_id or data.get( "session_id" ) == session_id:
            persona = data.get( "voice_persona" )
            return persona.get( "name" ) if isinstance( persona, dict ) else persona
    return None


def _is_store_error( resp ):
    """
    True if a `task_store_tools` response is a transport/HTTP error envelope (the
    `{ "status": "error", ... }` shape `task_store_request` returns on a non-2xx)
    OR not a dict at all. A successful 200 body ({item, event} / {tasks, count})
    carries no "status":"error", so this distinguishes a real mutation from a 422.
    """
    return ( not isinstance( resp, dict ) ) or resp.get( "status" ) == "error"


def _latest_event_receipt( tst, api_url, api_key, item_id ):
    """
    Return the receipt_refs carried by an item's LATEST audit event (GET
    /api/tasks/{id}/events, ordered ascending), or None.

    Fail-safe-toward-reassign: a missing/empty trail, a store-error read, a
    non-dict body, or a raising read ALL yield None — treated as "no receipt", so
    the caller reassigns rather than auto-closing. Auto-close fires ONLY on a
    POSITIVE receipt, so a read failure can NEVER cause a wrong close.
    """
    try:
        resp = tst.task_store_request( "GET", f"/api/tasks/{item_id}/events", api_url, api_key )
    except Exception:
        return None
    events = ( resp.get( "events" ) if isinstance( resp, dict ) else None ) or []
    if not events:
        return None
    refs = events[ -1 ].get( "receipt_refs" )
    return refs if refs else None


def _default_reconcile_store_items( identity, dead_owner_slugs, reaping_manager, reason="" ):
    """
    Default reap-RECONCILE producer (d647b531): on reap, reconcile the reaped
    worker's NON-TERMINAL store items so an orphaned "outstanding" task never
    survives the reap for the user to catch. Three arms:

      (a) AUTO-CLOSE — ONLY when the item's LATEST audit event already carries
          receipt_refs (a `->done` that produced a receipt but never persisted the
          status flip). Machine-checkable, zero inference. No receipt → never close.
      (b) REASSIGN — every other non-terminal item, with the orphan-guard
          precedence: accountable_manager IF ALIVE (its slug NOT in
          `dead_owner_slugs` — the set of every persona reaped in THIS batch,
          which INCLUDES the reaped owner itself) → else the REAPING MANAGER
          (`reaping_manager`) → else unclassifiable. This kills the self-owned-stub
          re-orphan (harness TaskCreate hardcodes owner==accountable_manager==self)
          AND the same-batch case.
      (c) SURFACE — ALWAYS returns { closed, reassigned, unclassifiable } (lists of
          item ids); any per-item store error lands the item in unclassifiable.

    Reaches the store via the SAME `task_store_tools` client cosa_voice_mcp uses
    for its task verbs, with api_url/api_key resolved exactly as the sibling
    `_default_emit_reap` producer does. Best-effort throughout: a missing owner,
    unreachable config, or a raising query yields an empty summary and NEVER raises
    (dismiss_sessions also swallows, but this stays self-contained). Override via
    `dismiss_sessions(reconcile_items_fn=...)` — tests inject a fake.

    Requires:
        - identity is a captured reap identity ({persona, session_id, ...}) or None
        - dead_owner_slugs is a set of persona slugs reaped in this batch
        - reaping_manager is the reaping manager's persona NAME, or None

    Ensures:
        - returns { "closed": [...], "reassigned": [...], "unclassifiable": [...] }
        - auto-closes ONLY on a positive latest-event receipt; otherwise reassigns
          per the alive→reaping-manager→unclassifiable precedence
        - never raises
    """
    summary    = { "closed": [], "reassigned": [], "unclassifiable": [] }
    owner_name = _identity_persona_name( identity )
    if not owner_name:
        return summary                          # no owner key → nothing to query
    owner_key  = persona_slug( owner_name )
    try:
        from lupin_mcp import task_store_tools as tst
        from cosa.utils.config_loader import get_api_config, load_api_key
        env     = os.getenv( "LUPIN_ENV", "local" )
        cfg     = get_api_config( env )
        api_url = cfg[ "api_url" ]
        api_key = load_api_key( cfg[ "api_key_file" ] )
    except Exception:
        return summary                          # can't reach store config → best-effort no-op
    actor = f"reap-reconcile {owner_name}"
    try:
        resp = tst.task_query_impl( api_url, api_key, owner_persona=owner_key )
    except Exception:
        return summary                          # query transport blew up → best-effort no-op
    items = ( resp.get( "tasks" ) if isinstance( resp, dict ) else None ) or []
    for item in items:
        item_id = item.get( "id" )
        if item.get( "status" ) in ( "done", "dropped" ):
            continue                            # terminal — nothing to reconcile
        try:
            receipt = _latest_event_receipt( tst, api_url, api_key, item_id )
            if receipt:
                resp_t = tst.task_transition_impl( api_url, api_key, actor, item_id, "done", receipt_refs=receipt )
                ( summary[ "unclassifiable" ] if _is_store_error( resp_t ) else summary[ "closed" ] ).append( item_id )
                continue
            target      = item.get( "accountable_manager" )
            target_slug = persona_slug( target ) if target else None
            if target_slug and target_slug not in dead_owner_slugs:
                reassign_to = target                # accountable_manager is alive
            elif reaping_manager:
                reassign_to = reaping_manager       # dead/empty target → escalate to the reaping manager
            else:
                summary[ "unclassifiable" ].append( item_id )   # no live target → never re-orphan
                continue
            resp_r = tst.task_reassign_impl(
                api_url, api_key, actor, item_id, reassign_to,
                f"owner {owner_name} reaped; auto-reassigned to {reassign_to} ({reason or 'reap'})" )
            ( summary[ "unclassifiable" ] if _is_store_error( resp_r ) else summary[ "reassigned" ] ).append( item_id )
        except Exception:
            summary[ "unclassifiable" ].append( item_id )   # any per-item error → surface, never break
    return summary


def dismiss_sessions(
    manager_session_id : str,
    *,
    session_names      : Optional[ List[ str ] ] = None,
    reason             : str = "",
    write_memento      : bool = True,
    runner             : Callable = default_runner,
    session_dir        : Path = SESSION_DIR,
    emit_reap_fn       : Optional[ Callable ] = None,
    emit_reaped_fn     : Optional[ Callable ] = None,
    clear_hold_fn      : Optional[ Callable ] = None,
    reconcile_items_fn : Optional[ Callable ] = None
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
                    reason, write_memento, remaining, reconciliation }
        - reap-RECONCILE (d647b531): when `reconcile_items_fn` is provided, each
          reaped session's NON-TERMINAL store items are reconciled (close-if-
          receipt / reassign-to-live-manager / surface) and the per-session
          summaries are aggregated into the result's `reconciliation` block. The
          reconciler is FAIL-SAFE — a raising reconciler NEVER breaks the reap.
          DEFAULT is None (skip) so unit reaps pointed at a live :7999 stay
          hermetic; the real `_default_reconcile_store_items` is wired by the MCP
          wrapper (the live reap entrypoint). See the seam comment below.
        - Never raises

    Args:
        manager_session_id: lineage key
        session_names: explicit targets, or None = all mine
        reason: recorded teardown reason
        write_memento: echoed; the wrapper gives the child a chance to write one
        runner: injected subprocess runner
        session_dir: injected session/manifest directory
        reconcile_items_fn: per-reaped-session store reconciler
            (identity, dead_owner_slugs, reaping_manager, reason) -> summary dict;
            None = skip reconcile (hermetic default)

    Returns:
        dict: dismissal result
    """
    path    = _manifest_path( manager_session_id, session_dir )
    records = _read_manifest( path )
    known   = [ r[ "session_name" ] for r in records ]

    targets   = session_names if session_names is not None else list( known )
    dismissed = []

    # Capture each target's bridge identity (persona + sender_id) BEFORE teardown —
    # the bridge is unlinked below, and sender_id/persona both derive from it.
    identities = { name: _capture_reap_identity( session_dir, name ) for name in targets }

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

    # Bridge-delete + reap-event emit (2026-06-05, Rick): per reaped session, delete
    # its bridge file so the mtime-filtered active-sessions list drops it IMMEDIATELY
    # (broadcast send-to list + focus bar), then emit the `session_reaped` event.
    # Ordering: kill + manifest-rewrite (above) → unlink bridge → emit. Producer is
    # fail-safe — a bad unlink/emit NEVER breaks the reap.
    emit             = emit_reap_fn    if emit_reap_fn    is not None else _default_emit_reap
    emit_tombstone   = emit_reaped_fn  if emit_reaped_fn  is not None else _default_emit_reaped_tombstone
    do_clear_hold    = clear_hold_fn   if clear_hold_fn   is not None else _default_clear_hold
    bridges_deleted  = 0
    holds_cleared    = 0

    # reap-RECONCILE seam (d647b531): when a reconciler is wired, reconcile each
    # reaped worker's NON-TERMINAL store items so an orphaned "outstanding" task
    # never survives the reap. INVARIANT — TWO reap paths exist:
    #   • the MCP wrapper (cosa_voice_mcp.dismiss_sessions) → LIVE-reconcile: it
    #     passes the real `_default_reconcile_store_items`.
    #   • `reap_stale_spawned` (idle-TTL backstop) → forwards reconcile_items_fn
    #     (None until that path is wired live).
    # ANY NEW reap path MUST thread `reconcile_items_fn` — adding a third path that
    # calls dismiss_sessions WITHOUT it silently re-introduces the orphan this seam
    # exists to kill. The default is None (skip) so unit reaps stay hermetic against
    # a live :7999; the reconciler resolves the reaping-manager persona + the
    # dead-owner slug set (every persona reaped in THIS batch, incl. the reaped
    # owner) so a self-owned stub is escalated to the manager, never re-orphaned.
    reconciliation   = { "closed": [], "reassigned": [], "unclassifiable": [] }
    reaping_manager  = _resolve_session_persona_name( session_dir, manager_session_id ) if reconcile_items_fn is not None else None
    dead_owner_slugs = set()
    if reconcile_items_fn is not None:
        for name in reaped_names:
            name_persona = _identity_persona_name( identities.get( name ) )
            if name_persona:
                dead_owner_slugs.add( persona_slug( name_persona ) )

    for name in reaped_names:
        ident = identities.get( name )
        if not ident:
            continue
        bridge_path = ident.get( "bridge_path" )
        if bridge_path is not None:
            try:
                bridge_path.unlink()
                bridges_deleted += 1
            except ( FileNotFoundError, OSError ):
                pass
        try:
            emit( ident, reason )
        except Exception:
            pass  # producer must NEVER break the reap
        # Reap tombstone on the heartbeat-event rail (reap-tombstone fix): lets
        # the arbiter evict the roster row in ~1 poll. Fail-safe — a raising
        # emitter NEVER breaks the reap (same posture as the bridge unlink).
        try:
            emit_tombstone( ident )
        except Exception:
            pass  # producer must NEVER break the reap
        # Hold-clear on reap (ping-storm durable Fix 1, 2026-06-24): delete the
        # reaped session's `.heartbeat-hold-<sid>.json` so the arbiter stops
        # re-deriving phantom blocker edges from an orphaned hold every poll. The
        # bridge unlink above drops the session from liveness; the hold is a
        # SEPARATE artifact that lingered until TTL+6h. Fail-safe — a raising
        # clearer NEVER breaks the reap (same posture as the bridge unlink).
        try:
            if do_clear_hold( ident ):
                holds_cleared += 1
        except Exception:
            pass  # producer must NEVER break the reap
        # Reap-reconcile (d647b531): reconcile this worker's non-terminal store
        # items, aggregating the summary. Fail-safe — a raising reconciler NEVER
        # breaks the reap (same posture as the bridge unlink / emit / hold-clear).
        if reconcile_items_fn is not None:
            try:
                summary = reconcile_items_fn( ident, dead_owner_slugs, reaping_manager, reason )
                if isinstance( summary, dict ):
                    for category in ( "closed", "reassigned", "unclassifiable" ):
                        reconciliation[ category ].extend( summary.get( category ) or [] )
            except Exception:
                pass  # producer must NEVER break the reap

    return {
        "dismissed"          : dismissed,
        "manager_session_id" : manager_session_id,
        "reason"             : reason,
        "write_memento"      : write_memento,
        "remaining"          : [ r[ "session_name" ] for r in remaining ],
        "bridges_deleted"    : bridges_deleted,
        "holds_cleared"      : holds_cleared,
        "reconciliation"     : reconciliation
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
        - Returns { sessions: [ {session_name, requested_role, status, alive, model} ],
                    manager_session_id, count }
        - model surfaces the persisted manifest model id (None when a pre-fix
          record predates model capture — honest absence, never a guess)
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
            "alive"          : alive,
            "model"          : r.get( "model" )
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
    session_dir        : Path = SESSION_DIR,
    reconcile_items_fn : Optional[ Callable ] = None
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
        reconcile_items_fn: forwarded to dismiss_sessions' reap-RECONCILE seam.
            None by default (this path has NO live caller yet — dormant). When a
            LIVE caller is wired, it MUST pass `_default_reconcile_store_items`
            here (as the MCP wrapper does), else a stale-reaped worker's store
            items silently orphan — the exact failure d647b531 closes, one level up.

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
        write_memento=False, runner=runner, session_dir=session_dir,
        reconcile_items_fn=reconcile_items_fn   # forward — a LIVE wiring MUST pass _default_reconcile_store_items
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
        - Returns { spawn_cap, ack_timeout_seconds, write_memento_default,
          spawn_models } with documented defaults (8, 120, True, all-None model
          map) when config_mgr is None or a key is absent
        - spawn_models maps each spawn role (reviewer / author / observer /
          default) to its configured model id, or None when the key is absent
          (absent → no --model flag → child inherits the user default, fail-open).
          The MCP wrapper resolves a child's model as explicit-param → role key →
          the "default" key (covers unknown/new roles) → None.
        - Never raises

    Args:
        config_mgr: configuration source or None

    Returns:
        dict of resolved spawn config
    """
    cap    = DEFAULT_SPAWN_CAP
    ack    = 120
    wm     = True
    models = { "reviewer": None, "author": None, "observer": None, "default": None }
    if config_mgr is not None:
        cap = config_mgr.get( "cc session spawn max reviewers",
                              default=DEFAULT_SPAWN_CAP, return_type="int", silent=True )
        ack = config_mgr.get( "cc session spawn reviewer ack timeout seconds",
                              default=120, return_type="int", silent=True )
        wm  = config_mgr.get( "cc session spawn write memento default",
                              default=True, return_type="boolean", silent=True )
        for spawn_role in models:
            models[ spawn_role ] = config_mgr.get( f"cc session spawn model {spawn_role}",
                                                   default=None, return_type="string", silent=True )
    return { "spawn_cap": cap, "ack_timeout_seconds": ack, "write_memento_default": wm,
             "spawn_models": models }


def _slug( text: str ) -> str:
    """
    Lowercase, keep alnum/-/_, collapse other runs to a single '-'. For session
    names + DM topics — matches the dm-{persona} convention (e.g. "Mr. Radio" →
    "mr-radio") used by the PG-6 slug.
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
        # MULTI-WORD persona: DM topic on sep="_" (canonical, "dm-mr_radio") but
        # tmux session name on sep="-" ("cc-author-mr-radio-1") — the two MUST NOT
        # share a separator (one-name mandate 2026-06-22).
        mw = spawn_sessions( 1, "t", "mgr-mw", script_path="x", manager_persona="Mr. Radio",
                             role="author", runner=runner, session_dir=sd )
        assert mw[ "collection_topic" ] == "dm-mr_radio", mw[ "collection_topic" ]
        assert mw[ "spawned" ][ 0 ][ "session_name" ] == "cc-author-mr-radio-1"
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
