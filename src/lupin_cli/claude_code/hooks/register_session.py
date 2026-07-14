#!/usr/bin/env python3
"""
SessionStart hook: registers Claude Code session with the session bridge.

Phase 0 test hook — validates SessionStart payload, writes session bridge file,
and sends hello-world TTS notification.

Actions:
    1. Extract session_id, transcript_path, cwd from stdin
    2. Write ~/.claude/sessions/cc-{PPID}.json (for MCP server polling)
    3. Write CLAUDE_SESSION_ID to CLAUDE_ENV_FILE (for Bash access)
    4. Purge stale session files (>24h old)
    5. Send TTS notification with per-session sender_id
    6. Log full payload
    7. Emit additionalContext with session ID

Install in .claude/settings.local.json:
    "hooks": {
        "SessionStart": [{
            "type": "command",
            "command": "python3 src/lupin_cli/claude_code/hooks/test_register_session.py"
        }]
    }
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:   # pragma: no cover - bootstrap import-guard; src is always on sys.path under pytest
    sys.path.insert( 0, _src_path )

import urllib.request
import urllib.error
import urllib.parse

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts
)
from lupin_cli.claude_code.hooks.lib.session_bridge import build_sender_id_for_cc
from lupin_cli.claude_code.hooks.lib.listener_processes import find_live_listener_pids, listener_spawn_lock
from cosa.agents.utils.sender_id import detect_project
from cosa.utils.notification_utils import is_known_project
from cosa.rest.voice_persona_helpers import resolve_session_start_persona_chain, pick_declared_managers_from_env


def _find_tmux_session( cc_pid ):
    """
    Find the tmux session containing the given PID.

    Calls `tmux list-panes -a -F "#{session_name} #{pane_pid}"` and matches
    cc_pid against pane PIDs. Falls back to grandparent PID check for shell
    wrappers (e.g., start-cc-with-tmux.sh spawns bash -> claude).

    Requires:
        - cc_pid is a positive integer

    Ensures:
        - Returns tmux session name if cc_pid (or its parent) is found in a pane
        - Returns None if tmux is not installed or no match is found
        - Never raises exceptions (graceful when tmux unavailable)

    Args:
        cc_pid: PID of the Claude Code process

    Returns:
        str or None: tmux session name, or None
    """
    try:
        result = subprocess.run(
            [ "tmux", "list-panes", "-a", "-F", "#{session_name} #{pane_pid}" ],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return None

        # Build pid -> session_name mapping
        pid_to_session = {}
        for line in result.stdout.strip().splitlines():
            parts = line.strip().split( " ", 1 )
            if len( parts ) == 2:
                session_name, pane_pid_str = parts
                try:
                    pid_to_session[ int( pane_pid_str ) ] = session_name
                except ValueError:
                    continue

        # Direct match: CC process is the pane process
        if cc_pid in pid_to_session:
            return pid_to_session[ cc_pid ]

        # Grandparent check: pane runs shell -> shell runs claude
        # Check if cc_pid's parent is a pane PID
        try:
            with open( f"/proc/{cc_pid}/stat" ) as f:
                stat_line = f.read()
            comm_end = stat_line.rindex( ")" )
            fields   = stat_line[comm_end + 2:].split()
            parent_pid = int( fields[1] )
            if parent_pid in pid_to_session:
                return pid_to_session[ parent_pid ]
        except ( FileNotFoundError, IndexError, ValueError, PermissionError, OSError ):
            pass

        return None

    except ( FileNotFoundError, subprocess.TimeoutExpired, OSError ):
        return None


def _resolve_cc_pid( hook_ppid ):
    """
    Walk up from the hook's parent (bash wrapper) to find Claude Code's PID.

    The hook process tree is always: claude → bash -c "..." → python hook.py
    So hook's PPID is bash, and bash's PPID is Claude Code.

    Requires:
        - hook_ppid is a valid PID (the bash wrapper's PID)

    Ensures:
        - Returns the grandparent PID (Claude Code) on success
        - Returns hook_ppid unchanged on any error (safe fallback)

    Args:
        hook_ppid: PID of the hook's immediate parent (bash wrapper)

    Returns:
        int: Claude Code PID (grandparent), or hook_ppid on failure
    """
    try:
        with open( f"/proc/{hook_ppid}/stat" ) as f:
            stat_line = f.read()
        # Safe parsing: comm field is in parens and may contain spaces/parens
        # Format: pid (comm) state ppid ...
        # Find the LAST ")" to skip past comm field safely
        comm_end = stat_line.rindex( ")" )
        fields_after_comm = stat_line[comm_end + 2:].split()
        # fields_after_comm[0] = state, fields_after_comm[1] = ppid
        cc_pid = int( fields_after_comm[1] )
        return cc_pid
    except ( FileNotFoundError, IndexError, ValueError, PermissionError, OSError ):
        return hook_ppid


def _record_listener_pid( session_data, session_file, listener_pid ):
    """
    Record the listener PID in the session bridge file for SessionEnd cleanup.

    Requires:
        - listener_pid is a positive int

    Ensures:
        - Writes listener_pid into session_data and persists to session_file
        - No-op when session_data is None or session_file is falsy
        - Never raises exceptions (best-effort)

    Args:
        session_data: Session bridge data dict (updated in-place), or None
        session_file: Path to session bridge JSON file, or None
        listener_pid: PID to record
    """
    if session_data is not None and session_file:
        session_data[ "listener_pid" ] = listener_pid
        try:
            with open( session_file, "w" ) as f:
                json.dump( session_data, f, indent=2 )
        except OSError:
            pass  # Best-effort


def _resolve_owner_pid( session_data, session_file ):
    """
    Resolve the owning Claude Code PID to hand the listener for self-reaping.

    _spawn_listener is called with `session_data if session_id else None`, so on the
    session_id-less path the in-memory dict is absent — but the bridge file on disk
    still carries cc_pid. Reading it back closes that hole; without the fallback that
    path would spawn a listener with NO watchdog, silently preserving the strand bug
    on exactly the branch nobody looks at.

    Requires:
        - session_data is a dict carrying "cc_pid", or None
        - session_file is a path to the bridge JSON, or None

    Ensures:
        - Returns the cc_pid as an int when resolvable from either source
        - Returns None when neither source yields one (watchdog disabled, and the
          listener logs that loudly at startup)

    Args:
        session_data: In-memory bridge dict, or None
        session_file: Path to the on-disk bridge JSON

    Returns:
        int or None: PID of the owning Claude Code process
    """
    cc_pid = ( session_data or {} ).get( "cc_pid" )

    if not cc_pid and session_file:
        try:
            with open( session_file ) as fh:
                cc_pid = json.load( fh ).get( "cc_pid" )
        except ( OSError, ValueError ):
            return None

    return int( cc_pid ) if cc_pid else None


def _spawn_listener( session_id, session_data, session_file, accepted_ids=None ):
    """
    Spawn the CC Notification Listener as a background subprocess.

    The listener connects via WebSocket and buffers user_initiated_message
    notifications targeted at this CC session.

    Singleton guard (F1, 2026-06-11): the documented `--continue` double-fire
    runs two concurrent SessionStart hooks; without a guard BOTH spawned a
    listener, the bridge remembered only the last PID, and the orphaned
    duplicate raced tmux injections — the broadcast-miss root cause. The
    check-then-spawn section is serialized under a per-session-hash flock so
    the second hook sees the first hook's live listener and reuses it.
    See: src/rnd/v0.1.8/2026.06.10-broadcast-miss-duplicate-listener-root-cause.md §4

    Requires:
        - session_id is a non-empty string
        - LUPIN_ROOT environment variable is set (for PYTHONPATH)

    Ensures:
        - At most ONE live listener exists per session hash (flock-serialized
          pgrep guard; an existing live listener is recorded + returned
          instead of spawning a duplicate)
        - Spawns listener subprocess in background (detached from hook lifecycle)
        - Records listener PID in session bridge file for SessionEnd cleanup
        - Always writes log file to ~/.claude/sessions/cc-listener-{hash}.log
        - Respects LUPIN_CC_HOOK_LISTENER_DEBUG/VERBOSE env vars
        - Returns listener PID on success, None on failure
        - Never raises exceptions (spawn failure is non-fatal)

    Args:
        session_id: Full CC session ID (stable_session_id after Phase 2)
        session_data: Session bridge data dict (updated in-place with listener_pid)
        session_file: Path to session bridge JSON file
        accepted_ids: Comma-separated 8-char hashes for listener filtering (e.g., "stable,transient")

    Returns:
        int or None: Listener subprocess PID, or None on failure
    """
    if not session_id:
        return None

    # Check if listener spawning is disabled
    if os.environ.get( "LUPIN_CC_HOOK_LISTENER_ENABLED", "true" ).strip().lower() == "false":
        return None

    short_id = session_id[:8]

    with listener_spawn_lock( short_id ):
        existing = find_live_listener_pids( short_id )
        if existing:
            # A live listener already serves this session hash (the other
            # double-fire hook won the race, or a resume found the prior
            # listener still running). Record it so SessionEnd can reap it.
            _record_listener_pid( session_data, session_file, existing[ 0 ] )
            return existing[ 0 ]

        return _spawn_listener_locked( session_id, session_data, session_file, accepted_ids )


def _spawn_listener_locked( session_id, session_data, session_file, accepted_ids ):
    """
    Spawn the listener subprocess — F1 critical section, caller holds the
    per-session-hash spawn lock.

    Requires:
        - session_id is a non-empty string
        - caller holds listener_spawn_lock( session_id[:8] )

    Ensures:
        - Same spawn/record/liveness contract as _spawn_listener
        - Returns listener PID on success, None on failure
        - Never raises exceptions

    Args:
        session_id: Full CC session ID (stable_session_id after Phase 2)
        session_data: Session bridge data dict (updated in-place with listener_pid)
        session_file: Path to session bridge JSON file
        accepted_ids: Comma-separated 8-char hashes for listener filtering

    Returns:
        int or None: Listener subprocess PID, or None on failure
    """
    short_id = session_id[:8]

    cmd = [
        sys.executable, "-m",
        "lupin_cli.claude_code.hooks.lib.cc_notification_listener",
        "--session-id", short_id,
    ]

    # Hand the listener its owner's PID so it can self-reap. The listener is spawned
    # detached (start_new_session=True, below), so tmux's SIGHUP never reaches it and
    # session_end.py — the only other reaper — cannot run on an abrupt death. Without
    # this the listener outlives its session forever, still wired to the notifications
    # UI. See cc_notification_listener._watch_owner().
    owner_pid = _resolve_owner_pid( session_data, session_file )
    if owner_pid:
        cmd.extend( [ "--owner-pid", str( owner_pid ) ] )

    # Pass accepted IDs for multi-hash filtering
    # On first start, stable_session_id == session_id, so this deduplicates to one entry.
    # On subsequent lifecycle events (compact, clear), they diverge and both are needed.
    if accepted_ids:
        cmd.extend( [ "--accepted-ids", accepted_ids ] )

    # Pass debug/verbose/log flags from env vars
    if os.environ.get( "LUPIN_CC_HOOK_LISTENER_DEBUG", "" ).strip().lower() == "true":
        cmd.append( "--debug" )

    if os.environ.get( "LUPIN_CC_HOOK_LISTENER_VERBOSE", "" ).strip().lower() == "true":
        cmd.append( "--verbose" )

    # Opt-in memory sampler — set LUPIN_CC_LISTENER_MEMTRACE=true to arm tracemalloc
    # on spawned listeners (for catching the 684 MB leak, 2026-07-14). Off by default.
    if os.environ.get( "LUPIN_CC_LISTENER_MEMTRACE", "" ).strip().lower() == "true":
        cmd.append( "--memory-trace" )

    # Always write per-session log files (backward compat) + centralized log
    log_dir          = os.path.expanduser( "~/.claude/sessions" )
    log_path         = os.path.join( log_dir, f"cc-listener-{short_id}.log" )
    centralized_path = os.path.join( log_dir, "cc-listeners.log" )
    cmd.extend( [ "--log-file", log_path ] )
    cmd.extend( [ "--centralized-log", centralized_path ] )

    # Ensure PYTHONPATH includes src/
    env = os.environ.copy()
    lupin_root = env.get( "LUPIN_ROOT", "" )
    src_path   = os.path.join( lupin_root, "src" ) if lupin_root else ""
    if src_path and src_path not in env.get( "PYTHONPATH", "" ):
        env[ "PYTHONPATH" ] = src_path + ":" + env.get( "PYTHONPATH", "" )

    # Force line-buffered stdout
    env[ "PYTHONUNBUFFERED" ] = "1"

    try:
        # Always capture stderr for startup crash diagnostics
        session_dir = os.path.expanduser( "~/.claude/sessions" )
        stderr_path = os.path.join( session_dir, f"cc-listener-{short_id}.stderr" )
        stderr_file = open( stderr_path, "w" )

        # Redirect stdout to centralized log — captures base class print() calls
        stdout_file = open( centralized_path, "a" )

        # Spawn detached — listener outlives the hook subprocess
        proc = subprocess.Popen(
            cmd,
            stdout = stdout_file,
            stderr = stderr_file,
            env    = env,
            start_new_session = True,
        )

        listener_pid = proc.pid

        # Brief liveness check — detect immediate crashes (e.g., missing credentials)
        time.sleep( 0.3 )
        try:
            os.kill( listener_pid, 0 )
        except ProcessLookupError:
            # Listener died immediately — read stderr for diagnostics
            stderr_file.close()
            try:
                with open( stderr_path, "r" ) as f:
                    stderr_contents = f.read().strip()
                if stderr_contents:
                    print( f"[SessionStart] WARNING: Listener died immediately. stderr:\n{stderr_contents}", file=sys.stderr )
                else:
                    print( f"[SessionStart] WARNING: Listener (PID {listener_pid}) died immediately with no stderr output", file=sys.stderr )
            except OSError:
                print( f"[SessionStart] WARNING: Listener (PID {listener_pid}) died immediately, could not read stderr", file=sys.stderr )
            return None

        # Record listener PID in session bridge file for SessionEnd cleanup
        _record_listener_pid( session_data, session_file, listener_pid )

        return listener_pid

    except Exception:
        return None  # Spawn failure is non-fatal


def _is_live_cc_process( pid_str ):
    """
    Check if a PID corresponds to a live process.

    Requires:
        - pid_str is a string representation of a PID

    Ensures:
        - Returns True if the process exists and is signalable
        - Returns True if the process exists but we lack permission (don't purge)
        - Returns False if the process does not exist or pid_str is invalid

    Args:
        pid_str: String PID to check

    Returns:
        bool: True if process is alive, False otherwise
    """
    try:
        os.kill( int( pid_str ), 0 )  # signal 0 = existence check, no signal sent
        return True
    except ( ProcessLookupError, ValueError ):
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it — don't purge


def _log_session_transition( old_hash, new_hash, stable_hash ):
    """
    Append a session transition marker to the centralized listener log.

    Requires:
        - old_hash and new_hash are non-empty strings

    Ensures:
        - Writes a single line to ~/.claude/sessions/cc-listeners.log
        - Uses [--------] pseudo-hash since this comes from the hook, not a listener
        - Never raises exceptions (best-effort)

    Args:
        old_hash: 8-char hash of the old session
        new_hash: 8-char hash of the new session
        stable_hash: 8-char hash of the stable (original) session
    """
    try:
        log_path  = os.path.expanduser( "~/.claude/sessions/cc-listeners.log" )
        now       = datetime.now( timezone.utc )
        timestamp = now.strftime( "%Y.%m.%d @ %H:%M %S" ) + f",{now.microsecond // 1000:03d}ms"
        line      = f"{timestamp} [--------] === SESSION TRANSITION: {old_hash} -> {new_hash} (stable: {stable_hash}) ===\n"
        with open( log_path, "a" ) as f:
            f.write( line )
            f.flush()
    except Exception:
        pass  # Best-effort


def _cleanup_old_listener( old_session_data, new_session_id ):
    """
    Kill old listener and forward buffer messages on context clear.

    When CC performs a context clear, the same PID gets a new session ID.
    The old listener is still running and filtering for the old session hash.
    This function:
        1. Sends SIGTERM to the old listener (3s timeout, then SIGKILL)
        2. Forwards any remaining messages from old buffer to new buffer
        3. Deletes the old buffer file

    Requires:
        - old_session_data is a dict with listener_pid and session_id keys
        - new_session_id is a non-empty string

    Ensures:
        - Old listener process is terminated
        - Buffer messages are forwarded (best-effort)
        - Old buffer file is deleted
        - Never raises exceptions (all errors are logged but non-fatal)

    Args:
        old_session_data: Session bridge data from previous session
        new_session_id: New session ID after context clear
    """
    old_listener_pid = old_session_data.get( "listener_pid" )
    old_session_id   = old_session_data.get( "session_id", "" )
    old_hash         = old_session_id[:8] if old_session_id else ""
    new_hash         = new_session_id[:8] if new_session_id else ""

    session_dir = os.path.expanduser( "~/.claude/sessions" )

    # Step 1: Kill old listener
    if old_listener_pid:
        try:
            os.kill( old_listener_pid, 0 )  # Check if alive
            os.kill( old_listener_pid, signal.SIGTERM )

            # Wait up to 3 seconds for graceful shutdown
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    os.kill( old_listener_pid, 0 )
                    time.sleep( 0.2 )
                except ProcessLookupError:
                    break
            else:
                # Still alive after 3s — force kill
                try:
                    os.kill( old_listener_pid, signal.SIGKILL )
                except ProcessLookupError:
                    pass

        except ProcessLookupError:
            pass  # Already dead
        except ( PermissionError, OSError ):
            pass  # Can't signal it

    # Step 1.5: Log session transition to centralized log
    stable_hash = old_session_data.get( "stable_session_id", old_session_id )[:8] if old_session_data.get( "stable_session_id", old_session_id ) else old_hash
    if old_hash and new_hash:
        _log_session_transition( old_hash, new_hash, stable_hash )

    # Step 2: Forward buffer messages from old hash to new hash
    if old_hash and new_hash and old_hash != new_hash:
        old_buffer = os.path.join( session_dir, f"cc-buffer-{old_hash}.jsonl" )
        new_buffer = os.path.join( session_dir, f"cc-buffer-{new_hash}.jsonl" )

        if os.path.exists( old_buffer ):
            try:
                with open( old_buffer, "r" ) as f_old:
                    lines = f_old.readlines()

                if lines:
                    with open( new_buffer, "a" ) as f_new:
                        for line in lines:
                            try:
                                entry = json.loads( line.strip() )
                                entry[ "job_id" ]       = new_hash
                                entry[ "forwarded_from" ] = old_hash
                                f_new.write( json.dumps( entry ) + "\n" )
                            except ( json.JSONDecodeError, KeyError ):
                                f_new.write( line )

                os.remove( old_buffer )

            except OSError:
                pass  # Best-effort


def _check_cosa_voice_status():
    """
    Quick non-blocking checks for cosa-voice prerequisites.

    Requires:
        - Called from within a SessionStart hook context

    Ensures:
        - Returns a formatted status block string (never raises)
        - Each check has 1s timeout max to avoid blocking session start
    """
    checks = []
    sep    = "=" * 42

    # ── Check 1: MCP registration ────────────────────────────────────
    mcp_status = "not found"
    try:
        settings_path = os.path.expanduser( "~/.claude/settings.json" )
        if os.path.exists( settings_path ):
            with open( settings_path ) as f:
                settings = json.load( f )
            mcp_servers = settings.get( "mcpServers", {} )
            if "cosa-voice" in mcp_servers:
                mcp_status = "registered (user scope)"
        # Also check local .mcp.json in cwd
        local_mcp = os.path.join( os.getcwd(), ".mcp.json" )
        if os.path.exists( local_mcp ):
            with open( local_mcp ) as f:
                local_cfg = json.load( f )
            if "cosa-voice" in local_cfg.get( "mcpServers", {} ):
                mcp_status = "registered (local scope — consider migrating to global)"
    except Exception:
        mcp_status = "check failed"

    # ── Check 2: Project detection ───────────────────────────────────
    try:
        project      = detect_project()
        known        = is_known_project( project )
        proj_source  = "known" if known else "basename"
        proj_status  = f"{project} ({proj_source})"
    except Exception:
        proj_status  = "detection failed"

    # ── Check 3: Hook count ──────────────────────────────────────────
    hook_count = 0
    try:
        settings_path = os.path.expanduser( "~/.claude/settings.json" )
        if os.path.exists( settings_path ):
            with open( settings_path ) as f:
                settings = json.load( f )
            hooks = settings.get( "hooks", {} )
            for hook_name, hook_list in hooks.items():
                if isinstance( hook_list, list ) and len( hook_list ) > 0:
                    hook_count += 1
    except Exception:
        pass
    hook_status = f"{hook_count}/8 active"

    # ── Check 4: Server reachable ────────────────────────────────────
    server_url = os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
    try:
        req  = urllib.request.Request( f"{server_url}/docs", method="HEAD" )
        resp = urllib.request.urlopen( req, timeout=1 )
        server_status = f"reachable ({server_url})"
    except Exception:
        server_status = f"unreachable ({server_url})"

    # ── Check 5: Config file ─────────────────────────────────────────
    config_path   = os.path.expanduser( "~/.lupin/config" )
    config_status = "found" if os.path.exists( config_path ) else "MISSING"

    # ── Build status block ───────────────────────────────────────────
    lines = [
        sep,
        "  cosa-voice — Session Start",
        sep,
        f"  MCP     : {mcp_status}",
        f"  Project : {proj_status}",
        f"  Hooks   : {hook_status}",
        f"  Server  : {server_status}",
        f"  Config  : ~/.lupin/config {config_status}",
        sep,
    ]
    return "\n".join( lines )


def _allocate_voice_persona_via_http(
    server_url, project, stable_session_id,
    previous_persona_name = None,
    persona_chain         = None,
    declared_managers     = None
):
    """
    Allocate a voice persona for the given session by calling the cosa-voice
    HTTP endpoint at /api/cosa-voice/voice-persona/{sid}/allocate.

    The server endpoint atomically picks an unallocated persona from the pool
    (under asyncio.Lock), writes it to the bridge file, and broadcasts a
    voice_persona_assigned WebSocket event.

    Fail-soft: any failure (server unreachable, auth failure, pool empty)
    logs a warning to stderr and returns None. The session continues
    without a persona; the speech router will fall back to Sam (the global
    default voice) on TTS dispatch.

    Requires:
        - server_url is a non-empty string (e.g. http://localhost:7999)
        - project is a non-empty string used to look up hook credentials
        - stable_session_id is a non-empty string

    Ensures:
        - Returns the persona dict on success
        - Returns None on any failure (logged to stderr)
        - Never raises exceptions
        - Uses 2-second timeouts for both /auth/login and /allocate
        - When previous_persona_name is non-empty, threads it as a
          query-string param so the server pushes a "Voice re-assigned"
          announcement after the assigned broadcast
        - When persona_chain is non-empty, threads it as a query-string
          param so the server walks the chain strictly (first FREE element
          wins, `*` = "then take anything free", exhaustion without `*` =
          409 + conflict notify — the fail-soft except path below turns
          that 409 into a None return, leaving the session persona-less).
          Mutually exclusive with the strict requested_persona_name swap
          endpoint.
        - When declared_managers is a non-empty list, threads it as a CSV
          `declared_managers` query-string param on EVERY allocate call —
          with AND without a chain — so the server reserves those names out
          of the random and chain-`*` draws (reserve-from-random, Rick
          2026-06-11). Named chain elements and strict requests still claim
          them.

    Args:
        server_url: Lupin server URL
        project: Project key (for credential lookup)
        stable_session_id: Stable session ID to allocate for
        previous_persona_name: Optional display_name of the outgoing persona
            (when /clear preservation failed); causes the server to push a
            "Voice re-assigned: X → Y" notification on successful allocation
        persona_chain: Optional ordered persona-chain expression — from the
            spawn-injected `COSA_VOICE_PERSONA_CHAIN` env var or the user's
            per-repo `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` shell default
        declared_managers: Optional list of declared-manager persona names
            (the `COSA_VOICE_MANAGERS__<PROJECT>` roster) reserved out of
            the server's random + chain-`*` draws

    Returns:
        dict or None: The persona dict, or None on failure
    """
    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        email, password = get_hook_credentials( project )

        # Step 1: login to get JWT
        login_body = json.dumps( { "email": email, "password": password } ).encode()
        login_req  = urllib.request.Request(
            f"{server_url}/auth/login",
            data    = login_body,
            method  = "POST",
            headers = { "Content-Type": "application/json" }
        )
        with urllib.request.urlopen( login_req, timeout=2 ) as resp:
            login_data = json.loads( resp.read().decode() )
        access_token = login_data.get( "tokens", {} ).get( "access_token" )
        if not access_token:
            print( f"[register_session] WARNING: voice persona allocate — login response missing access_token",
                   file=sys.stderr )
            return None

        # Step 2: POST /allocate (optionally with previous_persona_name +
        # persona_chain as query params)
        alloc_url    = f"{server_url}/api/cosa-voice/voice-persona/{stable_session_id}/allocate"
        query_params = []
        if previous_persona_name:
            query_params.append( f"previous_persona_name={urllib.parse.quote( previous_persona_name )}" )
        if persona_chain:
            query_params.append( f"persona_chain={urllib.parse.quote( persona_chain )}" )
        if declared_managers:
            query_params.append( f"declared_managers={urllib.parse.quote( ','.join( declared_managers ) )}" )
        if query_params:
            alloc_url = f"{alloc_url}?{'&'.join( query_params )}"

        alloc_req = urllib.request.Request(
            alloc_url,
            data    = b"",  # empty body (endpoint takes session_id from path)
            method  = "POST",
            headers = {
                "Content-Type"  : "application/json",
                "Authorization" : f"Bearer {access_token}"
            }
        )
        with urllib.request.urlopen( alloc_req, timeout=2 ) as resp:
            alloc_data = json.loads( resp.read().decode() )
        return alloc_data.get( "voice_persona" )

    except ( urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
             KeyError, FileNotFoundError, OSError, ValueError ) as e:
        print( f"[register_session] WARNING: voice persona allocate failed ({type( e ).__name__}: {e})",
               file=sys.stderr )
        return None


def _release_voice_persona_via_http( server_url, project, stable_session_id ):
    """
    Release the currently-allocated voice persona for the given session by
    calling the cosa-voice HTTP endpoint at
    /api/cosa-voice/voice-persona/{sid}/release.

    The server endpoint clears the voice_persona field on the bridge file and
    broadcasts a voice_persona_released WebSocket event. The frontend uses the
    event to drop the stale persona from senderPersonaMap so subsequent
    notifications re-hydrate from the freshly-stamped envelope.

    Fail-soft: any failure (server unreachable, auth failure, no persona to
    release) logs a warning to stderr and returns False. The hook continues
    with its bridge write either way.

    Requires:
        - server_url is a non-empty string (e.g. http://localhost:7999)
        - project is a non-empty string used to look up hook credentials
        - stable_session_id is a non-empty string

    Ensures:
        - Returns True on successful POST /release (HTTP 2xx)
        - Returns False on any failure (logged to stderr)
        - Never raises exceptions
        - Uses 2-second timeouts for both /auth/login and /release

    Args:
        server_url: Lupin server URL
        project: Project key (for credential lookup)
        stable_session_id: Stable session ID to release

    Returns:
        bool: True on success, False on failure
    """
    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        email, password = get_hook_credentials( project )

        # Step 1: login to get JWT
        login_body = json.dumps( { "email": email, "password": password } ).encode()
        login_req  = urllib.request.Request(
            f"{server_url}/auth/login",
            data    = login_body,
            method  = "POST",
            headers = { "Content-Type": "application/json" }
        )
        with urllib.request.urlopen( login_req, timeout=2 ) as resp:
            login_data = json.loads( resp.read().decode() )
        access_token = login_data.get( "tokens", {} ).get( "access_token" )
        if not access_token:
            print( f"[register_session] WARNING: voice persona release — login response missing access_token",
                   file=sys.stderr )
            return False

        # Step 2: POST /release
        rel_req = urllib.request.Request(
            f"{server_url}/api/cosa-voice/voice-persona/{stable_session_id}/release",
            data    = b"",
            method  = "POST",
            headers = {
                "Content-Type"  : "application/json",
                "Authorization" : f"Bearer {access_token}"
            }
        )
        with urllib.request.urlopen( rel_req, timeout=2 ) as resp:
            resp.read()  # drain
        return True

    except ( urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
             KeyError, FileNotFoundError, OSError, ValueError ) as e:
        print( f"[register_session] WARNING: voice persona release failed ({type( e ).__name__}: {e})",
               file=sys.stderr )
        return False


def _resolve_window_tokens():
    """
    Context-window size (in tokens) to PIN into the bridge at spawn.

    The out-of-band context-pressure assessor needs each worker's true window as
    the denominator and MUST NOT infer it from observed occupancy (a 1M worker at
    138k and a 200k worker at 138k look identical from the transcript — and the
    200k one is on fire). So we pin it here, as a property of the worker, read
    from LUPIN_CC_WINDOW_TOKENS (set per-worker by the spawn path for [1m]-beta
    workers) and falling back to the 1M fleet default.

    See: src/rnd/v0.1.8/2026.06.07-managing-context-memory/2026.06.08-context-pressure-revised-plan.md §4

    Ensures:
        - returns a positive int (never raises — defensive: this runs inside the
          live SessionStart hook on every registration)
        - bad/absent env value → 1_000_000
    """
    try:
        val = int( os.environ.get( "LUPIN_CC_WINDOW_TOKENS", "" ) )
        return val if val > 0 else 1_000_000
    except ( ValueError, TypeError ):
        return 1_000_000


def main():

    # ── Phase 1: Read hook input ──────────────────────────────────────────
    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    session_id      = payload.get( "session_id", "" )
    transcript_path = payload.get( "transcript_path", "" )
    cwd             = payload.get( "cwd", "" )

    # ── Phase 2: Write session bridge file ────────────────────────────────
    session_dir  = os.path.expanduser( "~/.claude/sessions" )
    session_file = None
    old_data     = None
    is_context_clear      = False
    previous_persona_name = None  # Set when /clear preservation fails AND old bridge had a persona; threaded into Phase 4.5 alloc

    if session_id:
        os.makedirs( session_dir, exist_ok=True )

        hook_ppid    = os.getppid()
        cc_pid       = _resolve_cc_pid( hook_ppid )
        session_file = os.path.join( session_dir, f"cc-{cc_pid}.json" )

        # ── Context clear detection ──────────────────────────────────
        # Write-once lockfile is the source of truth for stable ID.
        # Uses open('x') (O_CREAT|O_EXCL) for atomic creation — safe against
        # the documented double-fire on `--continue` (two concurrent SessionStart hooks).
        stable_lockfile   = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
        stable_session_id = session_id  # Default: first session start
        try:
            # Attempt atomic create — succeeds only for the first SessionStart of this PID
            with open( stable_lockfile, "x" ) as f:
                stable_session_id = session_id
                f.write( stable_session_id )
        except FileExistsError:
            # Lockfile already exists — this is a subsequent lifecycle event (clear, compact, resume)
            # or the second concurrent hook on --continue. Read the winner's stable ID.
            try:
                with open( stable_lockfile ) as f:
                    stable_session_id = f.read().strip()
            except OSError as e:
                # Lockfile exists but unreadable (corruption, permission denied).
                # Log to stderr (hooks emit to stderr without polluting Claude's context),
                # then establish a new stable anchor rather than silently diverging.
                print( f"[register_session] WARNING: failed to read lockfile {stable_lockfile}: {e}",
                       file=sys.stderr )
                stable_session_id = session_id
                try:
                    with open( stable_lockfile, "w" ) as f:
                        f.write( stable_session_id )
                except OSError:
                    pass  # Best-effort recovery

            # Detect context clear by comparing transient IDs in the bridge file
            if os.path.exists( session_file ):
                try:
                    with open( session_file ) as f:
                        old_data = json.load( f )
                    old_session_id = old_data.get( "session_id", "" )
                    if old_session_id and old_session_id != session_id:
                        is_context_clear = True
                        _cleanup_old_listener( old_data, session_id )  # session_id = new transient UUID, keep its listener alive
                except ( json.JSONDecodeError, OSError ):
                    pass
        except OSError as e:
            # Cannot create lockfile at all (permissions, disk full).
            # Fall back to transient session_id — stability guarantee lost for this session.
            print( f"[register_session] WARNING: failed to create lockfile {stable_lockfile}: {e}",
                   file=sys.stderr )
            stable_session_id = session_id

        tmux_session = _find_tmux_session( cc_pid )

        # Build session_ids list — accumulate across context clears
        # old_data was already read at line 471-480 for context-clear detection
        existing_ids = old_data.get( "session_ids", [] ) if old_data else []
        if stable_session_id not in existing_ids:
            existing_ids.append( stable_session_id )
        if session_id not in existing_ids:
            existing_ids.append( session_id )

        session_data = {
            "session_id"        : session_id,
            "stable_session_id" : stable_session_id,
            "session_ids"       : existing_ids,
            "transcript_path"   : transcript_path,
            "cwd"               : cwd,
            "cc_pid"            : cc_pid,
            "hook_ppid"         : hook_ppid,
            "tmux_session"      : tmux_session,
            "window_size"       : _resolve_window_tokens(),
        }

        # Manager-spawned headless reviewer tagging (2026-05-28). When this
        # session was launched by the cosa-voice spawn_sessions MCP tool, the
        # spawn script forwards COSA_VOICE_SPAWNED_BY / COSA_VOICE_HEADLESS /
        # COSA_VOICE_ROLE into the tmux env. Record lineage + mark headless, and
        # start the session speakerphone-OFF so its (rare, stray) notify() isn't
        # spoken — reviewers normally communicate via commons text, and un-muting
        # one is just enable_speakerphone on its session_id. Fully env-gated:
        # zero effect on normal interactive sessions (the block only runs when
        # COSA_VOICE_SPAWNED_BY is present).
        # See: src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md
        _spawned_by = os.environ.get( "COSA_VOICE_SPAWNED_BY" )
        if _spawned_by:
            session_data[ "spawned_by" ]      = _spawned_by
            session_data[ "headless" ]        = os.environ.get( "COSA_VOICE_HEADLESS", "" ) == "1"
            session_data[ "role" ]            = os.environ.get( "COSA_VOICE_ROLE", "reviewer" )
            session_data[ "speakerphone_on" ] = False
            # Owner-lineage drift fix (2026-06-22): freeze the manager's persona-at-
            # spawn onto this worker's bridge so the arbiter resolves the TRUE
            # spawning manager for a finished/dead worker WITHOUT re-deriving the
            # manager session's CURRENT (drift-prone) persona. Worker-keyed, durable.
            # Omitted when the spawner couldn't resolve a manager persona (legacy
            # behavior: resolver falls back to re-derivation).
            _spawned_by_persona = os.environ.get( "COSA_VOICE_SPAWNED_BY_PERSONA" )
            if _spawned_by_persona:
                session_data[ "spawned_by_persona" ] = _spawned_by_persona

        # Carry voice_persona forward across ANY context reset (/clear,
        # /compact, resume, --continue double-fire) so the user keeps the same
        # allocated voice. Without this, the SessionStart that follows the reset
        # would lose the persona (session_data is rebuilt from scratch above)
        # and Phase 4.5 would re-roll a new voice — confusing the user
        # mid-session (e.g. Mr. Radio → Krishna after a compaction).
        #
        # The gate is deliberately NOT keyed on is_context_clear: that flag is
        # True only when the transient session UUID changed, which a compaction
        # need not do. A session keeps its persona for life, and old_data is
        # non-None only on a subsequent lifecycle event — never on a genuinely
        # fresh start (the lockfile is created fresh there, leaving old_data
        # None). So whenever a prior bridge carries a valid voice_persona dict,
        # preserve it regardless of whether the transient id rotated.
        # See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md §5
        #      src/rnd/v0.1.7/2026.05.22-voice-persona-request-tool-and-compaction-carry-forward.md
        if old_data and isinstance( old_data.get( "voice_persona" ), dict ):
            session_data[ "voice_persona" ] = old_data[ "voice_persona" ]

        # Defense-in-depth: if the carry-forward above did NOT preserve the
        # persona but the old bridge had one, explicitly release it via HTTP
        # before the bridge write below. This emits a voice_persona_released
        # WS event, prompting the frontend to drop the stale persona from
        # senderPersonaMap so the about-to-arrive new persona doesn't render
        # under the old badge. Also captures the outgoing display_name so
        # Phase 4.5's alloc can request a "Voice re-assigned" announcement.
        # Fail-soft.
        if not session_data.get( "voice_persona" ) and old_data and isinstance( old_data.get( "voice_persona" ), dict ):
            old_persona_dict = old_data[ "voice_persona" ]
            if isinstance( old_persona_dict.get( "display_name" ), str ):
                previous_persona_name = old_persona_dict[ "display_name" ]
            try:
                _release_project = detect_project()
            except Exception:
                _release_project = "lupin"
            _release_server_url = os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
            _release_voice_persona_via_http( _release_server_url, _release_project, stable_session_id )

        # Initialize idle_detection block — tracks per-session state for the
        # deferred "Anything else?" prompt with exponential backoff.
        # See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
        import datetime as _dt
        idle_block = {
            "last_interaction_at" : _dt.datetime.now().astimezone().isoformat( timespec="seconds" ),
            "backoff_index"       : 0,
            "waiter_pid"          : None,
        }
        # Carry forward backoff_index across /clear (the user shouldn't lose
        # backoff progression just because they cleared context). Reset
        # last_interaction_at to now (the clear itself is activity) and
        # waiter_pid to None (any old waiter is now orphaned and will exit
        # on its next wake when it sees the new bridge state).
        if is_context_clear and old_data and isinstance( old_data.get( "idle_detection" ), dict ):
            old_idle = old_data[ "idle_detection" ]
            if isinstance( old_idle.get( "backoff_index" ), int ):
                idle_block[ "backoff_index" ] = old_idle[ "backoff_index" ]
        session_data[ "idle_detection" ] = idle_block

        # Carry-forward read-modify-write — preserves any bridge fields not in
        # session_data (e.g., user_id, owner_user_id stamped by the listener
        # post-SessionStart). Without this merge, a /clear would clobber every
        # listener-stamped field because session_data is rebuilt from scratch
        # above and only voice_persona + idle_detection.backoff_index appear in
        # the explicit carry-forward list. session_data wins for keys it
        # provides; existing fills in everything else.
        # See: src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md §D4 Fix B
        try:
            existing = { }
            if os.path.exists( session_file ):
                try:
                    with open( session_file ) as f:
                        existing = json.load( f )
                    if not isinstance( existing, dict ):
                        existing = { }
                except ( json.JSONDecodeError, OSError ):
                    existing = { }
            merged = { **existing, **session_data }
            with open( session_file, "w" ) as f:
                json.dump( merged, f, indent=2 )
        except OSError:
            pass  # Best-effort

    # ── Phase 3: Write to CLAUDE_ENV_FILE (for Bash commands) ─────────────
    # Use stable_session_id so all hooks produce consistent sender_ids
    # after context clears (avoids duplicate notification session cards)
    if session_id:
        env_file = os.getenv( "CLAUDE_ENV_FILE" )
        if env_file:
            try:
                with open( env_file, "a" ) as f:
                    f.write( f"export CLAUDE_SESSION_ID='{stable_session_id}'\n" )
                    f.write( f"export CLAUDE_TRANSCRIPT_PATH='{transcript_path}'\n" )
                    f.write( f"export CLAUDE_TMUX_SESSION='{tmux_session or ''}'\n" )
            except OSError:
                pass  # Best-effort

    # ── Phase 4: Purge stale session files (>24h old) ─────────────────────
    try:
        now = time.time()
        for entry in os.listdir( session_dir ) if os.path.isdir( session_dir ) else []:
            if entry.startswith( "cc-" ) and ( entry.endswith( ".json" ) or entry.endswith( ".id" ) ):
                fpath = os.path.join( session_dir, entry )
                if fpath == session_file or fpath == stable_lockfile:
                    continue  # Never purge our own files
                if ( now - os.path.getmtime( fpath ) ) > 86400:
                    # For lockfiles, check PID liveness before purging
                    if entry.endswith( ".id" ):
                        match = re.match( r"cc-stable-(\d+)\.id", entry )
                        if match and _is_live_cc_process( match.group( 1 ) ):
                            continue  # PID still alive — don't purge
                    os.remove( fpath )
    except Exception:
        pass  # Best-effort cleanup

    # ── Phase 4.4: Prune stale persona allocations (host-side only) ──────
    # Strike dead-PID bridges' voice_persona fields BEFORE allocation runs
    # so the in-container occupancy scan (which intentionally bypasses the
    # dead-PID filter — see find_active_voice_persona_sessions) sees a clean
    # pool. Without this prune, leftovers from prior days accumulate as
    # "occupied", exhausting the pool at day-start and forcing every new
    # session into the borrow/overflow path.
    #
    # Host-side only: prune_dead_persona_bridges() short-circuits to no-op
    # when called from inside a container (host PIDs invisible there).
    #
    # See: src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import prune_dead_persona_bridges
        pruned_count = prune_dead_persona_bridges()
        if pruned_count > 0:
            print( f"[register_session] Pruned voice_persona on {pruned_count} dead-PID bridge(s)", file=sys.stderr )
    except Exception as e:
        print( f"[register_session] WARNING: prune phase failed ({type( e ).__name__}: {e})", file=sys.stderr )

    # ── Phase 4.5: Allocate voice persona (synchronous, fail-soft) ───────
    # New CC session → assign a uniformly random voice from the 6-voice pool
    # so the user can audibly distinguish parallel sessions in the
    # notifications UI accordion. Sam is reserved as the system default for
    # any TTS request lacking a voice_id (and thus is NOT in the pool).
    #
    # If voice_persona was carried forward (set in Phase 2 from a prior bridge),
    # skip allocation — the user keeps the same voice across any context reset
    # (/clear, /compact, resume), not just /clear.
    # If allocation fails (server unreachable, auth issue, pool empty), the
    # bridge stays without a persona; the speech router falls back to Sam,
    # exactly today's behavior. No SessionStart blocking.
    #
    # Design: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md
    if session_id and "voice_persona" not in session_data:
        try:
            project = detect_project()
        except Exception:
            project = "lupin"
        # Persona-chain precedence (strict ordered-fallback, Rick 2026-06-11):
        # spawn-injected COSA_VOICE_PERSONA_CHAIN > headless-no-default >
        # per-repo COSA_VOICE_PREFERRED_PERSONA__<PROJECT> > None (random).
        # Full precedence contract lives in the pure helper.
        # See: src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md
        chain = resolve_session_start_persona_chain( project, os.environ )
        # Reserve-from-random (Rick, 2026-06-11): thread the project's
        # declared-manager roster (COSA_VOICE_MANAGERS__<PROJECT>, sourced
        # from fleet-roster.env and tmux-forwarded by start-cc-with-tmux.sh)
        # to the allocate endpoint on EVERY call — chain or plain random —
        # so neither draw can squat a declared manager's name.
        # See: src/rnd/v0.1.8/2026.06.11-fleet-roster-env-file-and-reserve-from-random.md
        declared_managers = pick_declared_managers_from_env( project, os.environ )
        # ── TEMPORARY DEBUG (2026-05-19, Tiberius session 4e724860) ─────────
        # Investigating why LookML hook never successfully allocates a persona
        # despite the backend chain working when called manually via curl.
        # Remove once root cause identified.
        _env_key   = f"COSA_VOICE_PREFERRED_PERSONA__{project.upper().replace( '-', '_' )}"
        _env_raw   = os.environ.get( _env_key, "<UNSET>" )
        print( f"[LOOKML-DEBUG] phase4.5 entry — project={project!r} env_key={_env_key!r} env_raw={_env_raw!r} spawned_chain_env={os.environ.get( 'COSA_VOICE_PERSONA_CHAIN', '<UNSET>' )!r} chain={chain!r}",
               file=sys.stderr )
        try:
            voice_persona_server_url = os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
            print( f"[LOOKML-DEBUG] calling _allocate_voice_persona_via_http — server={voice_persona_server_url!r} sid={stable_session_id!r} chain={chain!r}",
                   file=sys.stderr )
            allocated = _allocate_voice_persona_via_http(
                voice_persona_server_url, project, stable_session_id,
                previous_persona_name = previous_persona_name,
                persona_chain         = chain,
                declared_managers     = declared_managers
            )
            print( f"[LOOKML-DEBUG] _allocate_voice_persona_via_http returned — allocated={allocated!r}",
                   file=sys.stderr )
            if allocated is not None:
                # The /allocate endpoint already wrote the persona to the
                # bridge file; no further write needed here.
                session_data[ "voice_persona" ] = allocated
        except Exception as e:
            print( f"[register_session] WARNING: voice persona phase failed ({type( e ).__name__}: {e})",
                   file=sys.stderr )
            print( f"[LOOKML-DEBUG] exception in phase4.5 — type={type( e ).__name__} msg={e}",
                   file=sys.stderr )

    # ── Phase 5: Send TTS notification (with explicit sender_id) ────────
    short_id = session_id[:8] if session_id else "unknown"
    # Use stable_session_id for sender_id — stays consistent across context clears
    stable_id = session_data.get( "stable_session_id", session_id ) if session_id else session_id
    hook_sender_id = build_sender_id_for_cc( session_id=stable_id ) if session_id else None
    if is_context_clear:
        stable_short = stable_id[:8] if stable_id else "unknown"
        send_tts( f"Hook fired: SessionStart (context clear) — stable session {stable_short}", sender_id=hook_sender_id )
    else:
        send_tts( f"Hook fired: SessionStart — session {short_id}", sender_id=hook_sender_id )

    # ── Phase 5.5: Spawn CC Notification Listener ──────────────────────
    listener_pid = _spawn_listener( stable_session_id, session_data if session_id else None, session_file, accepted_ids=f"{stable_session_id[:8]},{session_id[:8]}" )

    # ── Phase 6: Log full payload ─────────────────────────────────────────
    log_payload( "session_start", payload )

    # ── Phase 7: Emit response with cosa-voice status ─────────────────────
    if session_id:
        try:
            status_block = _check_cosa_voice_status()
        except Exception:
            status_block = ""
        emit_json( {
            "additionalContext": f"Session ID: {session_id}\n\n{status_block}"
        } )
    else:
        emit_json( {} )


if __name__ == "__main__":
    main()
