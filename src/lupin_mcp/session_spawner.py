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
import time
from pathlib import Path
from typing  import Any, Callable, Dict, List, Optional, Tuple

from lupin_mcp.persona_normalization import persona_slug


# Default ceiling on concurrent reviewers a single manager may spawn. Overridden
# at the call site by the INI key `cc session spawn max reviewers`.
DEFAULT_SPAWN_CAP = 8

# Directory holding session bridge + manifest files (mirrors session_bridge.py).
SESSION_DIR = Path.home() / ".claude" / "sessions"

# ── Persona-state vocabulary for the spawn roster (row 6f8fd858) ──────────────
#
# The roster's liveness axis (`alive`/`status`) answers "is this tmux session
# up?". It does NOT answer "who is sitting in it?" — the persona is written by
# the CHILD's SessionStart into the child's own bridge file, long after the
# PARENT wrote the manifest row. These four values are the identity axis, and
# they exist so that a caller can never read a green liveness row as an answer
# to the identity question.
#
# The critical distinction is between the last two: a child that BOOTED and got
# no persona is a different animal from a child whose bridge is simply not on
# disk yet (or never will be). Collapsing them into one reassuring word is the
# defect this vocabulary exists to prevent.
PERSONA_STATE_ALLOCATED = "allocated"           # bridge found, voice_persona names a persona
PERSONA_STATE_NONE      = "none"                # bridge found, voice_persona explicitly null — booting, or booted and got nothing
PERSONA_STATE_UNKNOWN   = "unknown_no_bridge"   # no bridge matches — mid-spawn RACE *or* dead SessionStart, AMBIGUOUS
PERSONA_STATE_UNREADABLE= "unreadable"          # bridge found, voice_persona present but malformed — instrument failure, not absence

# Measured on a live spawn, 2026-07-21 (row 6f8fd858 verification). A HEALTHY
# child walks all three of the first states in about a second:
#     t+0.00s  unknown_no_bridge   parent wrote the seat; child has written nothing
#     t+0.77s  none                bridge on disk, voice_persona still null
#     t+1.02s  allocated           persona named (Tiberius)
# So NEITHER "unknown_no_bridge" NOR "none" is a failure verdict on its own —
# both are normal for a child that is one second old, and both are damning for a
# child that is forty minutes old. This is exactly why `age_seconds` is reported
# next to the state and why the state itself never editorializes: the STATE says
# what is on disk, the AGE is the evidence, and the caller draws the conclusion.
# An instrument that guessed here would be repeating the row's original sin in a
# new place — asserting a verdict it cannot actually establish.
#
# ⚠️ SCOPE OF THIS REPAIR — stated so it is not mistaken for more than it is.
# A persona-less session is inconsistently visible across the identity-bearing
# surfaces, and they disagree with each other. Measured 2026-07-21 on ONE live
# session (cc-author-mr-radio-3), simultaneously:
#     list_spawned_sessions   said alive:true / status:"live"      → healthy
#     dm_send                 said recipient_unresolved/inactive,
#                             listing 7 live peers and omitting it → gone
#     the bridge-scan path    found no bridge for it               → nothing
# Three surfaces, three different answers, one session, no shared source of
# truth. THIS CHANGE REPAIRS ONLY THE FIRST. The DM resolver's blindness is a
# separate defect on a separate path and is NOT fixed here; do not read a
# now-honest roster as evidence that the other surfaces agree with it.


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
    session_dir        : Path = SESSION_DIR,
    now_fn             : Callable = time.time
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
        - Stamps `spawned_ts` (epoch seconds, from now_fn) on EVERY spawn record,
          persisted to the manifest. The roster reads it back as `age_seconds` to
          distinguish a child mid-boot from a child whose SessionStart died — both
          present on disk as "no bridge yet" (row 6f8fd858). Pre-existing manifest
          records lack the key and surface age_seconds=None (honest absence).
        - Returns { spawned: [ {session_name, requested_role, status, model,
                    spawned_ts, ...} ], manager_session_id, collection_topic,
                    dry_run, requested, persona_preference, model }
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
        now_fn: injected clock (epoch seconds) stamped onto each spawn record

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
            "model"          : model,
            # Spawn-time stamp (row 6f8fd858). The roster's identity axis has a
            # genuinely ambiguous state — "no bridge on disk" is both a child
            # mid-boot and a child whose SessionStart died. Age does not resolve
            # the ambiguity (nothing on disk can), but it is the evidence that
            # lets a caller tell a 3-second race from a 40-minute corpse.
            "spawned_ts"     : now_fn()
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
        # 🔴 DELIBERATELY LEFT SHORT — excluded from the ~30s reload-window bump
        # (row 204911ca, 2026-07-20). Every other out-of-process `:7999` client
        # was raised to _SERVER_TRANSPORT_TIMEOUT_SECONDS (30) so it can outlast
        # a `uvicorn --reload` window. Not this one:
        #
        # The whole call is a best-effort notify inside `except: pass`, and it
        # sits ON the reap path. A 30s budget would delay EVERY reap by 30s
        # during a reload — the cost lands on the reap, which is real work, to
        # rescue a "<name> reaped" announcement, which is not. The exposure is
        # genuine; it is simply cheaper to lose the notification than to pay for
        # it. Do not raise this to match the cohort.
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
    reconcile_items_fn : Optional[ Callable ] = None,
    respin_personas    : Optional[ List[ str ] ] = None
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
                    reason, write_memento, remaining, reconciliation,
                    retained_owner_personas, retained_unmatched }
        - RE-SPIN RETENTION (4dfb2f3b): a persona named in `respin_personas` is
          reaped normally (tmux kill, bridge unlink, tombstone, hold-clear) but
          its store rows are NOT reconciled — the reconciler is not called for it
          at all, so ownership survives into the re-spun session. Surfaced, never
          silent: `retained_owner_personas` lists the slugs actually skipped and
          `retained_unmatched` lists requested slugs that matched no reaped
          persona (a stale/typo'd name protects nothing — the row reconciles as
          before, which is fail-safe, but the miss is NAMED rather than inferred
          from an absence).
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
        respin_personas: persona names coming straight back in a re-spin — their
            rows keep their owner (slug-tolerant matching); None/[] = every reaped
            session is a true reap and reconciles as before

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

    # RE-SPIN RETENTION (4dfb2f3b): the reconciliation above exists to stop a reaped
    # worker's rows orphaning on a persona with no live session (d647b531) — real,
    # and untouched. A RE-SPIN is the one case where that premise is FALSE: the same
    # persona is coming straight back, so reassigning its rows to the manager makes a
    # worked lane read as un-owned, and does it SELF-CONCEALINGLY (the rows land on
    # the manager who ordered the reap, so his board only looks fuller). The caller
    # has always known which it is; this is the parameter that lets it say so.
    #   • retention is PER-PERSONA, not per-batch — a real reap mixes both.
    #   • a retained persona STAYS in `dead_owner_slugs`. That set answers a DIFFERENT
    #     question — may ANOTHER worker's row be reassigned TO this persona now? —
    #     and the reason not to widen it is TRUST SCOPE, not timing (Rio ⚡, review
    #     of 4e922b20; my original timing argument is struck, because "he'll be
    #     sitting before anyone reads the row" defeats it in about four seconds).
    #     `respin_personas` is an UNVERIFIED CALLER CLAIM. Price a FALSE one:
    #     narrow, it strands the claimant's OWN rows on a dead persona — the
    #     d647b531 orphan, confined to the lane that made the claim. Widened, that
    #     same false claim ALSO drags a THIRD PARTY's rows onto the dead persona.
    #     ⇒ widening multiplies the blast radius of an unverified claim from the
    #     claimant's lane into other workers' lanes, and that holds whether or not
    #     the seat is sitting. The "loss" is not one: escalating to the reaping
    #     manager parks the row on a live, addressable, accountable owner who can
    #     hand it over in one call the moment the seat is genuinely occupied.
    #   ⚠️ NAME-KEYED, AND THE KEY IS NOT SOUND TODAY. Retention matches on persona
    #     SLUG, but a persona name can be held by more than one live session (2026-
    #     07-21: `arnold` on two, one with an unresolvable bridge) and freed names
    #     are re-granted after a reap. A claim naming a re-granted name can retain
    #     the WRONG seat's rows. Not fixed here — the sound key is a session id, and
    #     that is a change to the whole spawn/reap surface, not to this parameter.
    #   • both outcomes are SURFACED below — a retention you cannot see is the same
    #     class of defect as the reassignment it replaces.
    respin_slugs     = { persona_slug( p ) for p in ( respin_personas or [] ) if p and persona_slug( p ) }
    retained_slugs   = []
    for name in reaped_names:
        name_persona = _identity_persona_name( identities.get( name ) )
        if name_persona and persona_slug( name_persona ) in respin_slugs:
            retained_slugs.append( persona_slug( name_persona ) )
    retained_unmatched = sorted( respin_slugs - set( retained_slugs ) )

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
        if reconcile_items_fn is not None and persona_slug( _identity_persona_name( ident ) or "" ) not in respin_slugs:
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
        "reconciliation"     : reconciliation,
        "retained_owner_personas" : sorted( set( retained_slugs ) ),
        "retained_unmatched"      : retained_unmatched
    }


def list_spawned_sessions(
    manager_session_id : str,
    *,
    runner             : Callable = default_runner,
    session_dir        : Path = SESSION_DIR,
    now_fn             : Callable = time.time
) -> Dict[ str, Any ]:
    """
    List the sessions this manager spawned, on TWO independent axes: liveness
    (is the tmux session up?) and identity (who is sitting in it?).

    Row 6f8fd858 — this roster used to answer only the first axis while reading
    like a general health check. A manager asking "who took this seat?" got a
    green row and learned nothing, then briefed the wrong session by name. The
    liveness fields below keep their exact prior meaning; the identity fields
    are added alongside, and the roster now states out loud when identity could
    not be established rather than letting success stand in for verification.

    Requires:
        - manager_session_id is a non-empty string
        - runner is a callable(argv, env=None) -> CompletedProcess-like
        - now_fn is a callable() -> epoch seconds

    Ensures:
        - LIVENESS (unchanged): probes `tmux has-session -t <name>` per manifest
          entry; returncode 0 → alive=True/status="live", else dead
        - IDENTITY: each row carries `persona` (the name, or None) and
          `persona_state`, one of allocated / none / unknown_no_bridge /
          unreadable — a null persona is NEVER emitted without a state saying why,
          so a missing identity and an absent bridge can never read the same
        - `identity_verified` per row is True iff persona_state is "allocated"
        - `age_seconds` is seconds since the manifest recorded the spawn, or None
          for legacy records predating spawn-time capture (honest absence, never
          a guess) — it is the EVIDENCE that separates a live spawn race from a
          SessionStart that ran and failed, both of which present as "no bridge"
        - Top-level `identity_complete` is True iff EVERY row is "allocated"
          AND the bridge scan read every file it found (R-1, Rio 2026-07-21: a
          blind scan is not a complete one — an unreadable bridge cannot be
          ruled out as belonging to a seat listed here). `identity_warning` is
          None in that case and otherwise NAMES each unverified seat and/or the
          blindness, so a caller cannot read this dict as identity-verified
          unless the dict says so
        - `unattributable_bridges` reports bridge files the scan could not read —
          the instrument declaring its own blind spot
        - Returns { sessions, manager_session_id, count, identity_complete,
                    identity_warning, unattributable_bridges }
        - model surfaces the persisted manifest model id (None when a pre-fix
          record predates model capture — honest absence, never a guess)
        - Never raises (a missing manifest yields an empty list)
        - identity_complete is `warning is None`, and _build_identity_warning returns a
          warning whenever unattributable_bridges > 0 — REGARDLESS OF ROW COUNT. So an
          EMPTY roster with a corrupt bridge is identity_complete=FALSE, not True.
          🔴 This bullet used to promise the opposite ("an empty roster is
          identity_complete=True with no warning — nothing was claimed"), and it was
          FALSE from the moment the R-1 fix landed at 6ef13065 — stale inside its own fix
          commit, which is what row e788fce2 was filed for. Measured there: 0 records +
          1 corrupt bridge -> identity_complete=False. The code and its test agreed; the
          contract was the one lying, and a contract is the half a reader trusts.

    Args:
        manager_session_id: lineage key
        runner: injected subprocess runner
        session_dir: injected session/manifest directory
        now_fn: injected clock (epoch seconds) for age computation

    Returns:
        dict: roster with liveness AND identity, plus an explicit statement of
              which identity questions it could not answer
    """
    path    = _manifest_path( manager_session_id, session_dir )
    records = _read_manifest( path )
    out     = []

    # One scan for the whole roster — N rows must not mean N directory globs.
    persona_index, unattributable, corrupt_bridges = _scan_persona_by_tmux_session( session_dir )
    now = now_fn()

    for r in records:
        name   = r[ "session_name" ]
        result = runner( [ "tmux", "has-session", "-t", name ] )
        alive  = getattr( result, "returncode", 1 ) == 0

        # A seat absent from the index has NO bridge on disk. That is genuinely
        # ambiguous — mid-spawn race or dead SessionStart — and is reported as
        # ambiguous rather than smoothed into "this child has no persona".
        identity   = persona_index.get( name, { "persona": None, "persona_state": PERSONA_STATE_UNKNOWN } )
        spawned_ts = r.get( "spawned_ts" )
        age        = ( now - spawned_ts ) if isinstance( spawned_ts, ( int, float ) ) else None

        out.append( {
            "session_name"      : name,
            "requested_role"    : r.get( "requested_role", "reviewer" ),
            "status"            : "live" if alive else "dead",
            "alive"             : alive,
            "model"             : r.get( "model" ),
            "persona"           : identity[ "persona" ],
            "persona_state"     : identity[ "persona_state" ],
            "identity_verified" : identity[ "persona_state" ] == PERSONA_STATE_ALLOCATED,
            "age_seconds"       : age
        } )

    warning = _build_identity_warning( out, unattributable, corrupt_bridges )

    return {
        "sessions"              : out,
        "manager_session_id"    : manager_session_id,
        "count"                 : len( out ),
        "identity_complete"     : warning is None,
        "identity_warning"      : warning,
        "unattributable_bridges": unattributable,
        "corrupt_bridges"       : corrupt_bridges
    }


def _recover_tmux_session( raw: str ) -> Optional[ str ]:
    """
    Best-effort: recover the `tmux_session` from a bridge whose JSON will not
    load, so a corrupt bridge can NAME ITS SEAT instead of being an anonymous
    count.

    🔴 WHY THIS EXISTS (Rio ⚡ 2026-07-21, correcting his own ratified claim, and
    mine by inheritance). The scan reported corrupt bridges as an unattributable
    COUNT on the reasoning that "attribution requires reading the file." That is
    false for the failure mode this fleet actually produces. A SPLICE — two
    writers racing on one path — is A VALID DOCUMENT WITH GARBAGE AFTER IT, and
    `raw_decode` stops at the end of the first object and hands it back whole.
    Measured on the preserved specimen: `json.load` raised "Extra data", while
    `raw_decode` returned tmux_session `cc-author-mr-radio-3` intact. That seat's
    identity was in readable bytes the entire time the fleet called it
    unattributable — including in the roster this function backs.

    THE BOUNDARY, because a correction without one is just sloppiness in the
    other direction: recoverable IFF THE FIRST OBJECT IS COMPLETE.
        splice / short-write-over-long  → first object intact  → NAMEABLE
        first object itself truncated   → crashed write, full disk → genuinely
                                          nothing to name, and this returns None
    Verified against real files on both sides of that line.

    ⚠️ WHAT THIS DELIBERATELY DOES NOT DO: it does not return the persona, and
    the caller does not put the recovered document into the index. A corrupt
    bridge may be STALE — that is the whole basis of R-1 — so handing back a
    persona name from it would trade an anonymous blind spot for a confidently
    wrong one. This names the SEAT so a human can go repair the FILE; it does
    not supply a value anyone should trust.

    Requires:
        - raw is the file's text (may be malformed)

    Ensures:
        - Returns the `tmux_session` string when the leading JSON object decodes
          and carries a non-empty one
        - Returns None when the first object is incomplete, is not a dict, or
          has no usable tmux_session
        - Never raises

    Args:
        raw: unparseable bridge file contents

    Returns:
        str|None: the named seat, or None when genuinely unattributable
    """
    try:
        obj, _end = json.JSONDecoder().raw_decode( raw )
    except ( json.JSONDecodeError, ValueError ):
        return None
    if not isinstance( obj, dict ): return None
    named = obj.get( "tmux_session" )
    return named.strip() if isinstance( named, str ) and named.strip() else None


def _scan_persona_by_tmux_session( session_dir: Path ) -> Tuple[ Dict[ str, Dict[ str, Any ] ], int, List[ Dict[ str, str ] ] ]:
    """
    Scan the session-bridge directory once and index persona identity by the
    child's `tmux_session` name.

    This is the READ side of the identity axis. The parent never learns a
    child's persona at spawn time — the child's SessionStart writes it into its
    own bridge file afterwards — so the only honest way for a roster to answer
    "who is in this seat?" is to go look at the bridges.

    A bridge whose JSON will not parse cannot be attributed to any seat (bridge
    filenames key on pid, not on tmux session), so it is COUNTED rather than
    silently skipped: a scan that was partially blind must say so, otherwise a
    resulting "no bridge" verdict overstates what the scan actually established.

    Requires:
        - session_dir is a Path (need not exist)

    Ensures:
        - Returns ( index, unattributable_bridge_count, corrupt_bridges ) where
          index maps tmux_session -> { "persona": str|None, "persona_state": str }
        - corrupt_bridges lists { tmux_session, path } for every unparseable
          bridge whose SEAT could still be recovered (see _recover_tmux_session).
          The count KEEPS ITS EXACT PRIOR MEANING — every unreadable file still
          increments it, named or not — so identity_complete is unaffected by
          the naming and a recovered name never reads as a repaired file
        - a recovered document is NEVER merged into the index: a corrupt bridge
          may be stale, so its persona is not trusted, only its seat is named
        - persona_state is PERSONA_STATE_ALLOCATED when voice_persona is a dict
          carrying a non-empty string name (persona is that name)
        - persona_state is PERSONA_STATE_NONE when voice_persona is absent or
          explicitly null — the child wrote a bridge but has no persona in it
          (normal mid-boot; a failure only once aged — see the state vocabulary)
        - persona_state is PERSONA_STATE_UNREADABLE when voice_persona is
          present but malformed (not a dict, or a dict with no usable name);
          the record was found but the identity cannot be read from it
        - persona is None for every state except ALLOCATED — a name is only
          ever emitted when it was actually read
        - Bridges with no `tmux_session` field are ignored (not attributable)
        - Bridges whose JSON is unreadable/corrupt increment the returned count
        - Buffer/listener sidecar files are skipped (they are not bridges)
        - Never raises (an absent or unlistable session_dir yields ( {}, 0, [] ))

    Args:
        session_dir: directory holding cc-*.json bridge files

    Returns:
        tuple: ( { tmux_session: { persona, persona_state } }, unattributable_count,
                 [ { tmux_session, path } ] )
    """
    index         : Dict[ str, Dict[ str, Any ] ] = { }
    unattributable = 0
    corrupt        : List[ Dict[ str, str ] ] = [ ]

    try:
        candidates = sorted( session_dir.glob( "cc-*.json" ) )
    except OSError:
        return index, unattributable, corrupt

    for path in candidates:
        if "buffer" in path.name or "listener" in path.name: continue
        try:
            raw = path.read_text()
        except OSError:
            unattributable += 1
            continue
        try:
            data = json.loads( raw )
        except ( json.JSONDecodeError, ValueError ):
            unattributable += 1
            named = _recover_tmux_session( raw )
            if named: corrupt.append( { "tmux_session": named, "path": str( path ) } )
            continue
        if not isinstance( data, dict ):
            unattributable += 1
            continue

        tmux_session = data.get( "tmux_session" )
        if not tmux_session or not isinstance( tmux_session, str ): continue

        raw = data.get( "voice_persona" )
        if raw is None:
            entry = { "persona": None, "persona_state": PERSONA_STATE_NONE }
        elif isinstance( raw, dict ):
            name  = raw.get( "name" )
            if isinstance( name, str ) and name.strip():
                entry = { "persona": name.strip(), "persona_state": PERSONA_STATE_ALLOCATED }
            else:
                entry = { "persona": None, "persona_state": PERSONA_STATE_UNREADABLE }
        else:
            entry = { "persona": None, "persona_state": PERSONA_STATE_UNREADABLE }

        index[ tmux_session ] = entry

    return index, unattributable, corrupt


def _build_identity_warning(
    rows                  : List[ Dict[ str, Any ] ],
    unattributable_bridges: int,
    corrupt_bridges       : Optional[ List[ Dict[ str, str ] ] ] = None
) -> Optional[ str ]:
    """
    Compose the caller-facing sentence that REFUSES to let an all-green liveness
    roster be read as identity-verified.

    Returns None ONLY when every seat's identity was established AND the scan
    read every bridge it found — the roster warns about exactly what it could
    not answer, so the warning never becomes background noise a caller skips.

    🔴 A BLIND SCAN IS NOT A COMPLETE ONE, EVEN WHEN EVERY ROW LOOKS ALLOCATED.
    Found by Rio 2026-07-21 (R-1) against the first version of this function,
    which returned early on "no unverified rows" and dropped the blindness count
    on the floor — reporting identity_complete=True with unreadable bridges
    sitting on disk. That was this commit's own thesis inverted: the roster
    existed because an instrument sounded authoritative while silent on what it
    could not answer.

    WHY the blind case genuinely is incomplete, not merely surprising — the
    reason is load-bearing, so do not "simplify" it back: a bridge is attributed
    to a seat by the `tmux_session` field INSIDE it. When a bridge cannot be
    read, its tmux_session is unknown, so it CANNOT BE RULED OUT as belonging to
    a seat listed here — and a later-sorting bridge overwrites an earlier one in
    the index. An unreadable file may therefore be the CURRENT bridge for a seat
    this roster just reported as `allocated` under a stale name. Every row
    looking answered does not establish that every row was answered CORRECTLY.

    Requires:
        - rows is the assembled roster list (each row has session_name,
          persona_state, age_seconds)
        - unattributable_bridges is a non-negative count from the bridge scan

    Ensures:
        - Returns None IFF every row is PERSONA_STATE_ALLOCATED **AND**
          unattributable_bridges is 0 — both conditions, one source for the flag
        - Names EVERY unverified seat with its state, plus its age in whole
          seconds when the manifest recorded a spawn time (age is the evidence
          separating a live race from a dead SessionStart)
        - Reports scan blindness WHETHER OR NOT any row was unverified, and says
          which of the two situations the reader is in
        - Never raises

    Args:
        rows: assembled roster rows
        unattributable_bridges: bridges the scan could not parse or attribute

    Returns:
        str|None: the warning, or None when identity is fully established
    """
    unverified = [ r for r in rows if r[ "persona_state" ] != PERSONA_STATE_ALLOCATED ]
    if not unverified and not unattributable_bridges: return None

    if unverified:
        parts = []
        for r in unverified:
            age = r.get( "age_seconds" )
            if age is None:
                parts.append( f"{r[ 'session_name' ]} ({r[ 'persona_state' ]}, age unknown)" )
            else:
                parts.append( f"{r[ 'session_name' ]} ({r[ 'persona_state' ]}, {int( age )}s old)" )
        warning = (
            f"{len( unverified )} of {len( rows )} seat(s) could NOT be identity-verified: "
            + ", ".join( parts )
            + ". This roster answers LIVENESS; a live row is not proof of who is in it. "
              "Do not address these seats by persona name — confirm identity out of band."
        )
    else:
        warning = (
            f"Every one of {len( rows )} seat(s) resolved to a persona, but identity is NOT complete: "
            "the bridge scan was partially blind."
        )

    if unattributable_bridges:
        warning += (
            f" NOTE: the bridge scan skipped {unattributable_bridges} unreadable bridge file(s). "
        )
        named = [ c for c in ( corrupt_bridges or [ ] ) if c.get( "tmux_session" ) ]
        if named:
            # The seat IS recoverable from a spliced bridge, so say WHOSE it is
            # rather than leaving a nameable seat anonymous — that anonymity is
            # what let a live seat sit unaddressable while the fleet counted it
            # as one faceless bad file.
            warning += (
                "Of those, " + str( len( named ) ) + " could still be attributed: "
                + ", ".join( f"{c[ 'tmux_session' ]} ({c[ 'path' ]})" for c in named )
                + " — the file is corrupt but the seat is known; repair it rather than guessing. "
                  "The persona inside a corrupt bridge is NOT reported, because it may be stale. "
            )
        warning += (
            "An unreadable bridge's tmux_session cannot always be read, so it cannot be ruled out as "
            "belonging to a seat listed here"
        )
        warning += (
            " — an 'unknown_no_bridge' verdict above may be scan blindness rather than a missing bridge."
            if unverified else
            " — a seat reported as allocated may be named from a stale bridge the unreadable one supersedes."
        )
    return warning


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
