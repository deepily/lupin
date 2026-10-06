#!/usr/bin/env python3
"""
SessionStart hook: registers Claude Code session with the session bridge.

Validates the SessionStart payload, writes the session bridge file,
and sends a hello-world TTS notification.

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
import unicodedata
from datetime import datetime, timezone

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:   # pragma: no cover - bootstrap import-guard; src is always on sys.path under pytest
    sys.path.insert( 0, _src_path )

import urllib.request
import urllib.error
import urllib.parse

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, log_to_stream, emit_json, send_tts
)
from lupin_cli.claude_code.hooks.lib.session_bridge import atomic_write_json, build_sender_id_for_cc
from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir
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
        # Atomic (row 49b2c80b): this write races the Phase-2 bridge write and
        # the MCP-side updaters on the same cc-{pid}.json path.
        atomic_write_json( session_file, session_data )  # best-effort, never raises


def _resolve_owner_pid( session_data, session_file ):
    """
    Resolve the owning Claude Code PID to hand the listener for self-reaping.

    Without a session_id the in-memory dict is absent, but the bridge file still
    carries cc_pid. Reading it back is required: otherwise the listener has no watchdog.

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
    Spawn the CC Notification Listener as a background subprocess, once per session hash.

    The listener buffers user_initiated_message notifications for this session. A
    `--continue` runs two concurrent hooks; unguarded, both spawn and the orphan races
    tmux injections. A per-session-hash flock makes the second hook reuse the first.

    Requires:
        - session_id is a non-empty string
        - LUPIN_ROOT environment variable is set (for PYTHONPATH)

    Ensures:
        - At most one live listener exists per session hash (flock-serialized
          pgrep guard; an existing live listener is recorded and returned
          instead of spawning a duplicate)
        - Spawns listener subprocess in background (detached from hook lifecycle)
        - Records listener PID in session bridge file for SessionEnd cleanup
        - Always writes log file to ~/.claude/sessions/cc-listener-{hash}.log
        - Respects the LUPIN_CC_HOOK_LISTENER_DEBUG and LUPIN_CC_HOOK_LISTENER_VERBOSE env vars
        - Returns listener PID on success, None on failure
        - Never raises exceptions (spawn failure is non-fatal)

    Args:
        session_id: Full CC session ID (the stable session ID once the bridge is written)
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
    Spawn the listener subprocess inside the critical section; caller holds the spawn lock.

    Requires:
        - session_id is a non-empty string
        - caller holds listener_spawn_lock( session_id[:8] )

    Ensures:
        - Same spawn/record/liveness contract as _spawn_listener
        - Returns listener PID on success, None on failure
        - Never raises exceptions

    Args:
        session_id: Full CC session ID (the stable session ID once the bridge is written)
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
    log_dir          = str( sessions_dir() )
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
        session_dir = str( sessions_dir() )
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

        # Brief liveness check — detect immediate crashes (e.g., missing credentials).
        #
        # 🔴 proc.poll(), NOT os.kill( listener_pid, 0 ). This hook never wait()s the
        # child, so a listener that has ALREADY EXITED is a ZOMBIE — still in the
        # process table, and `os.kill( pid, 0 )` SUCCEEDS on it. Measured 2026-09-04:
        # Popen( [ "/bin/true" ], start_new_session=True ), sleep 0.3, then
        # os.kill( pid, 0 ) returns cleanly while poll() reports returncode 0.
        #
        # What the blind check cost: on 2026-09-04 a worktree seat's listener exited 1
        # during credential resolution ~0.1s in; the check said ALIVE, the dead PID was
        # written to the bridge, and the seat ran DEAF for two minutes while the roster
        # reported it healthy. The centralized log carried 32 such deaths. A monitor
        # that cannot fail is worse than no monitor: it converts a loud death into a
        # silent one. See src/tests/unit/test_listener_spawn_liveness_sees_a_zombie.py.
        time.sleep( 0.3 )
        exit_code = proc.poll()
        if exit_code is not None:
            # Listener died immediately — read stderr for diagnostics
            stderr_file.close()
            try:
                with open( stderr_path, "r" ) as f:
                    stderr_contents = f.read().strip()
                if stderr_contents:
                    print( f"[SessionStart] WARNING: Listener died immediately (exit {exit_code}). stderr:\n{stderr_contents}", file=sys.stderr )
                else:
                    print( f"[SessionStart] WARNING: Listener (PID {listener_pid}) died immediately (exit {exit_code}) with no stderr output — "
                           f"check the centralized log {centralized_path} for an unprefixed startup failure", file=sys.stderr )
            except OSError:
                print( f"[SessionStart] WARNING: Listener (PID {listener_pid}) died immediately (exit {exit_code}), could not read stderr", file=sys.stderr )
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
        log_path  = str( sessions_dir() / "cc-listeners.log" )
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
    Kill the old listener and forward its buffered messages on context clear.

    A context clear gives the same PID a new session ID; the old listener still
    filters the old hash. Sends SIGTERM (SIGKILL after 3s), forwards old-buffer
    messages to the new buffer, then deletes the old buffer file.

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

    session_dir = str( sessions_dir() )

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


# Budget for the SessionStart banner's `/docs` reachability probe. Deliberately
# SHORT — it runs on the boot path and its job is to LABEL the server's state,
# not to outlast a reload. See _classify_server_probe_error for why the label,
# not the number, is the fix at this site.
#
# 🔴 The two constants in this module are NOT interchangeable, and the split is
# the point: this one buys a fast, correctly-worded LABEL; the one below buys
# COMPLETION of a call whose result we cannot afford to lose. Sizing the probe
# like a transaction would stall every session boot by ~30s whenever the server
# is genuinely down.
_BANNER_PROBE_TIMEOUT_SECONDS = 3

# Transport budget for out-of-process calls to `:7999` whose RESULT is
# load-bearing — here, voice-persona release (row 204911ca). ~30s = 1.60x the
# observed maximum reload window of 18.76s: a multiplier with explicit headroom,
# NOT a coverage guarantee. `:7999` runs `uvicorn --reload` and the reloader
# parent holds the listening socket across a restart, so the kernel ACCEPTS a
# request nothing is there to answer and the caller hangs rather than getting a
# fast ConnectionRefused. The prior 2s failed every reload window it landed in
# (measured n=143: min 6.59s, median 6.91s).
#
# Full derivation: src/rnd/v0.1.9/2026.07.19-dev-server-reload-availability.md §9(a).
#
# 🔴 DRIFT CONTROL — TWO SEARCHES, AND IT TOOK BOTH.
# `grep -rn _SERVER_TRANSPORT_TIMEOUT_SECONDS` returns every DIRECT call site.
# It does NOT return members whose budget is carried in a Pydantic FIELD rather
# than passed at the call — `AsyncNotificationRequest( timeout=… )`, consumed at
# inside `notify_user_async()`'s retry loop as a bare `requests.post( timeout=request.timeout )`.
# (Cited by SYMBOL, not by line: this used to read `notify_user_async.py:197-201` and a
#  seven-line fix above it silently repointed every copy at an unrelated comment block.)
# Two such members were missed on the first pass for exactly this reason.
# The second search is: `grep -rn "AsyncNotificationRequest(" -A14 | grep timeout`.
# Run BOTH, or the set you get back is the set the first grep can see.
#
# TRADE: a genuinely hung server now stalls persona release ~30s instead of ~2s.
# Accepted — a leaked persona name is re-granted to a later worker and misdirects
# them, which outlasts a slow teardown. Not free.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30


def _classify_server_probe_error( exc, server_url, timeout_seconds ):
    """
    Map a `/docs` probe exception onto the server status string for the SessionStart banner.

    The wording matters: a flat "unreachable" made readers think the server was down
    when `:7999` was only mid-reload. A stopped server refuses at once (fix: start it).
    A restarting server accepts and stalls until the probe times out (fix: wait).

    Requires:
        - exc is the exception raised by the probe
        - server_url is a non-empty string
        - timeout_seconds is the positive budget the probe was given

    Ensures:
        - returns a status string that names the condition whenever this
          function can identify it, never a bare "unreachable"
        - a refused connection (nothing holds the port) reads "not running"
        - a timeout reads "may be restarting", because `uvicorn --reload` keeps the
          listening socket bound in the reloader parent and the kernel queues requests
        - treats an HTTP error status as reachable, because the server answered
        - falls back to "unreachable" only for conditions it cannot identify,
          and names the exception type even then
    """
    # The server ANSWERED, just not with 2xx — a HEAD on /docs may legitimately
    # return 405. Answering at all is the thing this banner is asking about.
    if isinstance( exc, urllib.error.HTTPError ):
        return f"reachable ({server_url})"

    # A timeout arrives in two shapes: urllib wraps connect-phase OSErrors in
    # URLError, but a timeout while READING the response propagates bare (that
    # is the C1 shape, and the reload case). Unwrap once, then test.
    reason = exc.reason if isinstance( exc, urllib.error.URLError ) else exc

    if isinstance( reason, TimeoutError ):
        return f"no response in {timeout_seconds}s — may be restarting ({server_url})"

    if isinstance( reason, ConnectionRefusedError ):
        return f"not running — connection refused ({server_url})"

    return f"unreachable — {type( reason ).__name__} ({server_url})"


def _check_cosa_voice_status():
    """
    Quick non-blocking checks for cosa-voice prerequisites.

    Requires:
        - Called from within a SessionStart hook context

    Ensures:
        - Returns a formatted status block string (never raises)
        - The reachability probe is capped at _BANNER_PROBE_TIMEOUT_SECONDS
          so it cannot block session start; a reload is labelled as a
          possible reload rather than reported as "unreachable"
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
    # The budget stays SHORT on purpose. Covering the 18.76s observed reload
    # maximum here would stall EVERY SessionStart boot by that much whenever the
    # server is genuinely down — a bad trade for one status line. 3s absorbs
    # ordinary jitter, and a reload is now NAMED as a possible reload instead of
    # being mislabelled. The WORDING, not the budget, is the fix at this site;
    # see _classify_server_probe_error.
    server_url = os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
    try:
        req = urllib.request.Request( f"{server_url}/docs", method="HEAD" )
        urllib.request.urlopen( req, timeout=_BANNER_PROBE_TIMEOUT_SECONDS )
        server_status = f"reachable ({server_url})"
    except Exception as e:
        server_status = _classify_server_probe_error(
            e, server_url, _BANNER_PROBE_TIMEOUT_SECONDS
        )

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


# Transport-budget retry ladder for voice-persona allocation (candidate A1,
# 2026-07-19; resized for the reload window 2026-07-20, row 204911ca).
#
# SIZING: each RUNG is sized against the observed maximum reload window of
# 18.76s. `:7999` runs `uvicorn --reload`; the reloader parent holds the
# listening socket across a restart, so the kernel ACCEPTS a request that
# nothing is there to answer. The client sees a late answer or a bare
# TimeoutError, never ConnectionRefused. Measured over 8.4 days of container
# logs (current-config clean-reload class, n=143): min 6.59s, median 6.91s,
# max 18.76s — all 143 exceed 5s.
#
# 🔴 WALL-CLOCK CEILING IS 60s, NOT 30s. EACH ATTEMPT MAKES **TWO** CALLS —
# `/auth/login` (:889) then `/allocate` (:920) — and BOTH take the SAME rung's
# timeout. So the worst case is 2x the tuple sum: (5+5) + (10+10) + (15+15) =
# **60s**, not the 30s an earlier revision of this comment claimed.
#
# There is NO backoff sleep between attempts (the loop re-enters immediately on
# failure), so 60s is the true ceiling and not merely the sum of the budgets.
# 60s sits far under the 600s harness allowance below, so nothing breaks.
#
# ⚠️ THE CONTRACT IS "COVER AN 18.76s WINDOW", NOT "FINISH INSIDE 30s".
# The first attempt-pair alone spends 10s, and by the second pair the elapsed
# time exceeds the observed maximum — so the window is covered well before the
# ladder is spent. No per-attempt total deadline is enforced; if anyone wants
# <=30s as a REAL contract, that is new control-flow and belongs on its own row
# with its own control, not bolted on here.
#
# 🔴 CORRECTION TO THE PLAN'S PREMISE, RECORDED BECAUSE IT FLATTERED THIS CHANGE.
# The plan argued the old (2, 4, 8) ladder "= 14s cumulative, under 18.76s" and
# therefore could not cover the window. **That arithmetic was wrong the same
# way**: two calls per attempt makes the old ladder **28s**, which already
# exceeded 18.76s. The old ladder was not as broken as the premise claimed.
# What the resize actually buys is per-rung headroom — under (2, 4, 8) no single
# call could outlast a 6.59s minimum window, so success depended on the window
# happening to end during a later rung. That is a real improvement, and it is a
# smaller one than the plan asserted. Do not restate the 14s figure.
#
# HARNESS HEADROOM: SessionStart carries no `timeout` field in
# ~/.claude/settings.json, so it runs at Claude Code's default for a command
# handler — 600s. ⚠️ That 600s is DOC-DERIVED (code.claude.com/docs/en/hooks.md,
# "Common fields"), NOT measured here; if it ever becomes load-bearing, measure
# it. The `SYNC_TIMEOUT_SECONDS = 25  # 5s headroom under CC's 30s hook timeout`
# comment in permission_request.py describes PermissionRequest's OWN configured
# 30000ms and does not bind this caller.
#
# THE TRADE, stated plainly: a genuinely hung server now takes **~60s** to give
# up, against ~28s before (both figures doubled for the two calls per attempt).
# That cost was accepted knowingly — Arnold's ruling, 2026-07-20 — to stop
# losing personas to a routine ~7s reload. It is not free, and the number is
# 60s, not the 30s the tuple's sum suggests at a glance.
#
# 🔴 SCORE THIS HEDGE HONESTLY. On the incident that motivated the original
# ladder (86aa79ac) it buys NOTHING: the server was flatly unreachable and no
# budget saves a down server. It pays against a reload window.
# ⚠️ THE TRAP: if nulls stop recurring after this lands, that is NOT evidence the
# ladder fixed anything. The loud give-up below landed in commit 77d64647 and
# makes the same nulls visible. Do not credit the hedge with the alarm's result.
_ALLOCATE_TIMEOUT_LADDER_SECONDS = ( 5, 10, 15 )


def _allocate_voice_persona_via_http(
    server_url, project, stable_session_id,
    previous_persona_name = None,
    persona_chain         = None,
    declared_managers     = None
):
    """
    Allocate a voice persona for a session through the cosa-voice HTTP allocate endpoint.

    The server picks a free persona atomically, writes the bridge file and broadcasts voice_persona_assigned.
    Failure is soft but never silent: it returns ( None, failure_dict ).

    Requires:
        - server_url is a non-empty string (e.g. http://localhost:7999)
        - project is a non-empty string used to look up hook credentials
        - stable_session_id is a non-empty string

    Ensures:
        - Returns ( persona_dict, None ) on success
        - Returns ( None, failure_dict ) on any failure; failure_dict carries stage / exception / message / attempts / server_url
        - persona is None if and only if failure is not None
        - On failure the session goes on persona-less; the speech router falls back to Sam
          (the global default voice). Never raises exceptions
        - Retries transport failures on the _ALLOCATE_TIMEOUT_LADDER_SECONDS budget
          (5s, 10s, 15s per rung). Each attempt makes two calls, login then /allocate, both
          on the rung's timeout, so the worst case is 60s. A wrong or empty answer is not retried
        - When previous_persona_name is non-empty, sends it as a query param so the
          server announces the re-assignment after the assigned broadcast
        - When persona_chain is non-empty, sends it as a query param so the server
          walks the chain strictly: the first free element wins, `*` means take anything free,
          and exhaustion without `*` is a 409 that the fail-soft except path turns into None (persona-less).
          The chain is mutually exclusive with the strict swap endpoint
        - When declared_managers is a non-empty list, sends it as a CSV query param on every
          allocate call, with or without a chain, so the server reserves those names out of random and
          `*` draws; named elements still claim them

    Args:
        server_url: Lupin server URL
        project: Project key (for credential lookup)
        stable_session_id: Stable session ID to allocate for
        previous_persona_name: Optional display_name of the outgoing persona
        persona_chain: Optional ordered persona-chain expression
        declared_managers: Optional list of declared-manager persona names

    Returns:
        tuple: ( persona dict or None, failure dict or None )
    """
    def _fail( stage, exception_name, message, attempts ):
        """Build the structured give-up and log it to stderr (forensic copy)."""
        print( f"[register_session] WARNING: voice persona allocate failed ({exception_name}: {message})",
               file=sys.stderr )
        return None, {
            "stage"      : stage,
            "exception"  : exception_name,
            "message"    : str( message ),
            "attempts"   : attempts,
            "server_url" : server_url
        }

    # ── Credentials: read OUTSIDE the transport try (candidate A3) ────────
    # A missing/blank credential file and a down server used to produce the
    # IDENTICAL silent None while demanding opposite fixes. They are now
    # distinguishable by `stage` before a single byte goes over the wire.
    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        email, password = get_hook_credentials( project )
    except ( OSError, KeyError, ValueError ) as e:
        return _fail( "credentials", type( e ).__name__, e, 0 )

    # ── Transport: retried on the budget ladder ───────────────────────────
    # The except stays BROAD on purpose. Its breadth was never the defect —
    # the missing reader was. Narrowing it risks an UNCAUGHT exception on the
    # SessionStart boot path, which is a worse bug than the one being fixed.
    # (Verified py3.13: URLError/HTTPError/TimeoutError/FileNotFoundError all
    # subclass OSError and JSONDecodeError subclasses ValueError, so the old
    # seven-name tuple was already effectively these three.)
    last_error = None
    for attempt, timeout_seconds in enumerate( _ALLOCATE_TIMEOUT_LADDER_SECONDS, start=1 ):
        try:
            # Step 1: login to get JWT
            login_body = json.dumps( { "email": email, "password": password } ).encode()
            login_req  = urllib.request.Request(
                f"{server_url}/auth/login",
                data    = login_body,
                method  = "POST",
                headers = { "Content-Type": "application/json" }
            )
            with urllib.request.urlopen( login_req, timeout=timeout_seconds ) as resp:
                login_data = json.loads( resp.read().decode() )
            access_token = login_data.get( "tokens", {} ).get( "access_token" )
            if not access_token:
                # The server ANSWERED and the answer was wrong — not a
                # transport problem, so do not spend the remaining ladder.
                return _fail( "login_no_token", "MissingAccessToken",
                              "login response carried no tokens.access_token", attempt )

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
            with urllib.request.urlopen( alloc_req, timeout=timeout_seconds ) as resp:
                alloc_data = json.loads( resp.read().decode() )
            persona = alloc_data.get( "voice_persona" )
            if persona is None:
                # Mr Radio enumerated every 200-return site on /allocate
                # (voice_persona.py :268 :296 :344 :527) and each carries a
                # non-None persona; every None path RAISES instead. So this
                # branch should be unreachable — and if it ever fires it must
                # ALARM, not hand back the silent None this whole row exists
                # to delete.
                return _fail( "empty_response", "MissingVoicePersona",
                              "allocate returned 200 with no voice_persona", attempt )
            return persona, None

        except ( OSError, ValueError, KeyError ) as e:
            last_error = e
            print( f"[register_session] WARNING: voice persona allocate attempt "
                   f"{attempt}/{len( _ALLOCATE_TIMEOUT_LADDER_SECONDS )} failed at "
                   f"timeout={timeout_seconds}s ({type( e ).__name__}: {e})",
                   file=sys.stderr )

    return _fail( "transport", type( last_error ).__name__, last_error,
                  len( _ALLOCATE_TIMEOUT_LADDER_SECONDS ) )


def _build_persona_failure_block( failure, stable_session_id ):
    """
    Render the voice-persona give-up as an additionalContext block the session reads at boot.

    The stderr line lands only in a hook_success attachment inside the session's own
    transcript, where nobody looks. This block puts the give-up where the model reads it,
    at no interrupt cost to the user. The session can then announce why it has no persona.

    Requires:
        - failure is None, or a dict carrying stage/exception/message/
          attempts/server_url
        - stable_session_id is a string or None

    Ensures:
        - Returns "" when failure is None (no alarm when nothing failed)
        - Otherwise returns a block naming the cause and the session_id
        - Never raises
    """
    if not failure: return ""

    sid = stable_session_id or "unknown"
    return (
        "\n"
        "════════════════════════════════════════════════════════════════\n"
        "  ⚠️  VOICE PERSONA ALLOCATION FAILED — THIS SESSION IS UNATTRIBUTED\n"
        "════════════════════════════════════════════════════════════════\n"
        f"  stage      : {failure.get( 'stage' )}\n"
        f"  cause      : {failure.get( 'exception' )}: {failure.get( 'message' )}\n"
        f"  attempts   : {failure.get( 'attempts' )}\n"
        f"  server     : {failure.get( 'server_url' )}\n"
        f"  session id : {sid}\n"
        "\n"
        "  You have NO persona name, NO persona badge on your notification\n"
        "  cards, and NO distinct TTS voice — you speak in the fallback voice\n"
        "  alongside every other session. Announce this at your first\n"
        "  opportunity and SPEAK THE SESSION ID ABOVE: it is the only thing\n"
        "  that identifies you, precisely because the two channels that\n"
        "  normally carry your identity are the ones that went missing.\n"
        "════════════════════════════════════════════════════════════════\n"
    )


_MEMENTO_AMENDMENT_MARKER = "<!-- memento-amendment:"
_MEMENTO_HEADER_MARKER    = "<!-- memento-record:"
_MEMENTO_FILE_PREFIX      = ".claude-memento-"
_MEMENTO_MAX_BYTES        = 8000
# 🔴 A TAIL LONG ENOUGH TO FILL THE BUDGET LEAVES NO ROOM FOR WHO YOU ARE — 2026-09-05
# (Krishna 🦚) on Tiberius 👑's corpus measurement. The amendment branch quoted the tail
# and ONLY the tail, so a seat with a big tail rehydrated with its owed work and no
# identity. MEASURED on the live `.claude-memento-maria-21979045.md`: 37,584-byte record,
# 27,365-byte tail, 8,617 delivered, and `# 1. WHO I AM / SEAT` NOT among it.
# Tiberius's corpus: 56 of 129 tailed records carry a tail over 8,000 bytes — 43% — and
# across 161 bodies the first load-bearing marker sits at a median 0.166 of the way in,
# with 111 of 161 in the FIRST QUARTER. The lead is where the identity lives.
# ⇒ Reserve a slice for the body's opening. The total budget is unchanged, so boot
# context does not grow; what changes is that some of it is spent on who the seat is.
# ⚠️ 3,000 NOT 2,000, AND THE FIGURE IS TIBERIUS 👑'S, NOT A ROUND NUMBER I LIKED.
# Measured on the corpus: a 2,000-byte lead reaches the opening in 80% of records; 3,000
# reaches 90%. The extra 1,000 comes out of the tail's share, and that is the cheap side
# of the trade — 43% of tails already exceed the whole budget and are truncated either
# way, so 5,000 against 6,000 changes little for them, while the head gains ten points.
_MEMENTO_BODY_LEAD_BYTES  = 3000


def _persona_slugs( persona_name ):
    """
    Every slug a persona's mementos might be filed under, best first.

    Accents are why this returns a list: "María" naively slugs to "mar-a", which
    misses the accent-folded files writers produce. The folded form (maria) comes
    first, and the mangled form is also returned so legacy records stay reachable.

    Requires:
        - persona_name is a string or None

    Ensures:
        - Returns [ ascii_slug, … ] with the accent-folded form first, the
          naive form appended only when it differs
        - Returns [] for an empty/None name or a name with no alphanumerics
        - Never raises
    """
    if not persona_name: return []

    lowered = persona_name.strip().lower()

    # Accent-folded: "maría" -> "maria". NFKD splits the letter from its accent;
    # dropping combining marks leaves the base letter.
    folded  = "".join( ch for ch in unicodedata.normalize( "NFKD", lowered )
                       if not unicodedata.combining( ch ) )

    out = []
    for candidate in ( folded, lowered ):
        slug = re.sub( r"[^a-z0-9]+", "-", candidate ).strip( "-" )
        if slug and slug not in out: out.append( slug )

    return out


def _written_at_of( header ):
    """
    Pull the `written_at=<ISO>` stamp out of a memento-record header.

    This is the honest recency key, unlike mtime: mirroring, copies and rsync reset
    mtime, so the newest mtime can be the oldest memento. The header stamp travels
    with the content.

    Requires:
        - header is a header line, or None

    Ensures:
        - Returns the ISO string when the stamp is present
        - Returns None when header is None or carries no stamp; this is not an
          error, because real records exist without one. The caller ranks those
          last rather than crashing or dropping them.
        - Never raises
    """
    if not header: return None
    match = re.search( r"written_at=(\S+)", header )
    return match.group( 1 ) if match else None


def _memento_dirs( repo_root ):
    """
    Every directory a memento record can live in, for this repo.

    There are four, because writers moved between slots and old records stay put.
    A directory does not tell you its naming convention, so enumerate all four and
    let the header decide. A resolver that backs the wrong one rehydrates a seat blank.

    Requires:
        - repo_root is a directory path

    Ensures:
        - Returns [ repo root, in-repo io slot, mirror root, mirror io slot ]
        - The mirror carries both the dotted repo-root filename shape at its top
          level and the bare `<persona>-<sid8>.md` shape under `io/mementos`
        - Never raises
    """
    project = os.path.basename( os.path.normpath( repo_root ) )
    mirror  = os.path.join( os.path.expanduser( "~/.claude/mementos" ), project )
    return [
        repo_root,
        os.path.join( repo_root, "io", "mementos" ),
        mirror,                                      # `.claude-memento-<persona>-<sid8>.md`
        os.path.join( mirror, "io", "mementos" ),    # `<persona>-<sid8>.md`
    ]


def _names_this_seat( name, sid8, slugs ):
    """
    Cheap filename test: could this file belong to this seat at all?

    A pre-filter, because opening every io-slot header would put hundreds of file
    reads on every session's boot path. The filename picks the candidates and the
    header still confirms the survivors: cheap test first, honest test second.

    Requires:
        - name is a bare filename; sid8 is an 8-char id or None; slugs is a list

    Ensures:
        - True when the name carries this seat's id or leads with its persona
        - Accepts both slot shapes: `.claude-memento-<persona>-<sid8>.md` at the
          repo root and `<persona>[-<anything>].md` in an io slot
        - Never raises
    """
    if not name.endswith( ".md" ): return False

    stem = name[ :-3 ]
    if stem.startswith( _MEMENTO_FILE_PREFIX ): stem = stem[ len( _MEMENTO_FILE_PREFIX ): ]

    if sid8 and sid8 in stem: return True
    for slug in slugs:
        if stem == slug or stem.startswith( f"{slug}-" ): return True
    return False


def _stamp_instant( stamp ):
    """
    The instant an ISO `written_at` names, as epoch seconds.

    Compare instants, never the strings: ISO text orders chronologically only when every
    stamp shares one UTC offset, and mixed offsets inverted real pairs. A naive stamp is
    refused rather than assumed local, as `reap_memento._parse_iso_aware` also does.

    Requires:
        - stamp is an ISO-8601 string, or None

    Ensures:
        - returns epoch seconds (float) for an aware stamp
        - returns None for None, a naive stamp, or anything unparseable; the caller
          demotes such a stamp to the mtime tier, so it ranks low and is never dropped
        - never raises
    """
    if not stamp: return None
    try:
        parsed = datetime.fromisoformat( stamp )
    except ( ValueError, TypeError ):
        return None
    if parsed.tzinfo is None: return None
    return parsed.timestamp()


def _recency_key( path, stamp ):
    """
    Rank one memento record: ( tier, instant ), newest first, tier 1 over tier 0.

    Tier 1 is a record with an orderable `written_at`; tier 0 is the rest, by mtime.
    The header stamp travels with the content while mirroring resets mtime. So a dated
    record must outrank an undated one, even when the undated file is newer on disk.

    Requires:
        - path is a filesystem path; stamp is an ISO string or None

    Ensures:
        - ( 1, epoch_seconds ) when the stamp names an instant
        - ( 0, mtime ) when it does not — undated, naive, or unparseable
        - ( 0, -inf ) when mtime is unreadable, so the record ranks last and is
          still never dropped
        - both tiers carry a float, so the second element is always comparable
        - never raises
    """
    instant = _stamp_instant( stamp )
    if instant is not None: return ( 1, instant )
    try:
        return ( 0, os.path.getmtime( path ) )
    except OSError:
        return ( 0, float( "-inf" ) )


def _memento_candidates( repo_root, sid8=None, slugs=() ):
    """
    Memento records visible to this seat, across both slot families, newest first.

    It excludes `.claude-memento.md`: that pointer is single-occupancy and names whichever
    seat wrote last, so using it would hand one persona another's state. Ordering uses the
    instant of `written_at`, then mtime; a record with neither ranks last and is never dropped.

    Requires:
        - repo_root is a directory path
        - sid8 / slugs identify the seat; both empty means "no pre-filter",
          which is only safe on the small repo-root slot

    Ensures:
        - Returns [ (path, header, sort_key), … ] newest-first, records only
        - Returns [] when no directory is readable
        - Never raises
    """
    out  = []
    seen = set()
    for directory in _memento_dirs( repo_root ):
        try:
            names = os.listdir( directory )
        except OSError:
            continue

        at_root = os.path.normpath( directory ) == os.path.normpath( repo_root )
        for name in sorted( names ):
            # The repo root holds unrelated files; only the prefixed ones are records.
            if at_root and not name.startswith( _MEMENTO_FILE_PREFIX ): continue
            if not name.endswith( ".md" ):                              continue
            if ( sid8 or slugs ) and not _names_this_seat( name, sid8, slugs ): continue

            path = os.path.join( directory, name )
            real = os.path.realpath( path )
            if real in seen: continue      # the mirror and the repo can hold the same record
            seen.add( real )

            header   = _header_of( path )
            sort_key = _recency_key( path, _written_at_of( header ) )
            out.append( ( path, header, sort_key ) )

    return sorted( out, key=lambda row: row[2], reverse=True )


def _header_of( path ):
    """
    Read the first line of a memento file and return it only if it is a record header.

    Ensures: returns the memento's first line when it is a memento-record
    header, else None. Never raises.
    """
    try:
        with open( path, "r", encoding="utf-8", errors="replace" ) as fh:
            first = fh.readline()
    except OSError:
        return None
    return first if _MEMENTO_HEADER_MARKER in first else None


def _persona_of( path, header ):
    """
    Determine which persona a memento belongs to.

    The header's `persona=` field is authoritative when present. Real records often lack
    it, so the filename slug is the fallback and keeps them reachable. Both sources are
    persona-scoped, so neither can leak one seat's memento to another.

    Requires:
        - path is a memento path; header is its header line or None

    Ensures:
        - Returns the persona slug, or None when neither source yields one
        - Never raises
    """
    if header:
        match = re.search( r"persona=([^\s]+)", header )
        if match: return match.group( 1 ).strip().lower()

    # Two shapes: `.claude-memento-<slug>-<sid8>.md` at the repo root, and
    # `<slug>[-<sid8>|-<anything>].md` in an io slot. Strip the optional prefix,
    # then take the leading segment — the io slot's `rachel-9eb9253c.md` and the
    # bare `arnold.md` both resolve, and neither can leak across personas.
    stem = os.path.basename( path )
    if stem.endswith( ".md" ):                  stem = stem[ :-3 ]
    if stem.startswith( _MEMENTO_FILE_PREFIX ): stem = stem[ len( _MEMENTO_FILE_PREFIX ): ]
    if not stem: return None
    return stem.split( "-", 1 )[0].strip().lower() or None


def _resolve_memento_path( stable_session_id, persona_name, repo_root ):
    """
    Find this seat's memento at the repo root, trying three matches in order.

    The order is the design. First comes an exact session-id match, because a self-re-spin
    keeps its id. Second is the live slot `io/mementos/<slug>.md` in this repo. Third is the
    best-ranked record for this persona, which survives dismiss-then-spawn.

    Requires:
        - stable_session_id is a string (full uuid) or None
        - persona_name is this seat's allocated persona, or None
        - repo_root is a directory path

    Ensures:
        - Returns a memento path, or None when nothing resolves
        - The session-id match uses `session_id=<sid8>` in the header or a `-<sid8>.md`
          filename suffix. It needs no header and does not check persona; the id is the identity
        - Never returns a record belonging to a different persona, except by session-id match,
          where the id is the identity: handing a seat another persona's state is worse than none
        - Those two matches accept a header-less file: real records often start with a
          human heading, and the live slot is a bare name that often has no header
        - The live slot beats any historical sibling, including one with a `written_at` the
          bare slot lacks, because the persona match ranks an unstamped record below every stamped one
        - Never prefers the mirror's copy of the live-slot name, which goes stale on its own
        - The persona match picks the first record in recency order (see _recency_key),
          trying accent-folded slugs first
        - A slot pointer can be returned, and that is intended: `_names_this_seat`
          admits `stem == slug`, and the live-slot match depends on it
        - A returned pointer is not empty: `memento_io.py` writes the header plus the whole
          record body. It is stale by at most one amendment, and is reached only when no
          record is readable at all
        - Never raises
    """
    sid8  = stable_session_id[:8] if stable_session_id and len( stable_session_id ) >= 8 else None
    slugs = _persona_slugs( persona_name )

    candidates = _memento_candidates( repo_root, sid8=sid8, slugs=slugs )
    if not candidates: return None

    # 1. Exact session-id match — a self-re-spin keeps its id, so a record
    #    naming it is unambiguously ours. Match on the header when there is
    #    one, else on the filename's trailing id.
    if sid8:
        for path, header, _ in candidates:
            if header and f"session_id={sid8}" in header:      return path
            if os.path.basename( path ).endswith( f"-{sid8}.md" ): return path

    # 1.5 THE CANONICAL LIVE SLOT OUTRANKS EVERY HISTORICAL SIBLING (row f99bed95).
    #     `<repo_root>/io/mementos/<slug>.md` is the slot the fleet's writers target and
    #     the one `reap_memento.seat_memento_slot` verifies. It is a BARE name, so it
    #     frequently carries no `written_at` header — and step 2's ranking demotes an
    #     unstamped record below EVERY stamped one, regardless of age. Measured against
    #     the live tree on 2026-08-29: Rio's fresh 18:35 `io/mementos/rio.md` ranked 44th
    #     of 79 and the resolver returned `rio-ea46bc1a.md`, 2.8 days old. The successor's
    #     boot receipt then named that file and the wake check alarmed STALE_MEMENTO
    #     against a seat that was fine.
    #
    #     Only the REPO's slot qualifies. The mirror holds a same-named `<slug>.md` whose
    #     copy goes stale on its own schedule — that is what respin_wake_check's
    #     SLOT_MIRROR alarm exists to catch, so it must not be promoted here.
    #
    #     Persona is still confirmed before the slot is accepted: a bare name is a claim,
    #     and handing a seat another persona's state stays worse than handing it none.
    for slug in slugs:
        slot = os.path.normpath( os.path.join( repo_root, "io", "mementos", f"{slug}.md" ) )
        for path, header, _ in candidates:
            if os.path.normpath( path ) == slot and _persona_of( path, header ) == slug:
                return path

    # 2. Newest record for this persona — survives dismiss-then-spawn, where
    #    the seat is new but the persona carried over. Slugs are tried in
    #    order, accent-folded first.
    for slug in slugs:
        for path, header, _ in candidates:
            if _persona_of( path, header ) == slug:
                return path

    return None


# The "is there anything here at all" floor for a memento body — see
# `_memento_body_after_header` for why it is a presence floor and NOT a
# population split, and why tuning it to separate two clusters is a mistake.
_MEMENTO_PRESENCE_FLOOR_BYTES = 200


def _extract_amendment_tail( content ):
    """
    Return the memento's whole amendment tail, from the first amendment marker to the end.

    It uses `find`, not `rfind`. `self_respin` appends a tiny nonce amendment, so the last
    marker is often plumbing. The block before it (held merge, crew) is the content.
    The tail is the unit: everything after the first amendment is not yet acted on.

    Requires:
        - content is the memento text, or None

    Ensures:
        - Returns the full trailing amendment region when a marker exists
        - Returns None when content is empty or carries no amendment marker
          (the caller then points at the file without quoting a section)
        - Never raises
    """
    if not content: return None
    idx = content.find( _MEMENTO_AMENDMENT_MARKER )
    if idx == -1: return None
    return content[ idx: ].strip()


_MEMENTO_COMMENT_BLOCK = re.compile( r"<!--.*?-->", re.DOTALL )


def _substantive_body( content ):
    """
    Return the memento body with HTML comment blocks and blank lines removed.

    This is what a reader would read, not what the file weighs. The near-blank warning must
    ask whether prose exists at all, not key on the amendment tail, because a body-only
    memento has no tail. It is a predicate, not a byte cutoff, since no threshold is needed.

    Requires:
        - content is the memento text, or None

    Ensures:
        - returns the body with comment blocks and blank lines removed
        - returns "" for None, for empty content, and for a pointer file whose
          entire content is comment lines
        - never raises
    """
    if not content: return ""
    stripped = _MEMENTO_COMMENT_BLOCK.sub( "", content )
    return "\n".join( line for line in stripped.splitlines() if line.strip() )


def _truncate_visibly( text, path, max_bytes=_MEMENTO_MAX_BYTES, keep="tail" ):
    """
    Cap `text` at max_bytes, keeping the tail by default, and announce any cut in the text.

    The tail is kept because amendments accrete oldest-first, so the newest is the state not
    yet acted on. A silent cut would hand over partial state that reads as complete, so the
    cut marker counts the dropped bytes and names the file. `keep="head"` quotes the opening.

    Requires:
        - text is a string; path is the memento path the text came from
        - max_bytes is a positive int

    Ensures:
        - Returns text unchanged when it fits
        - Otherwise returns an explicit marker naming the omitted byte
          count and the full path, followed by the newest max_bytes of text
          (or, when keep is "head", the first max_bytes of text and a trailing marker)
        - Never raises
    """
    raw = text.encode( "utf-8" )
    if len( raw ) <= max_bytes: return text

    # 🔴 WHICH END SURVIVES IS NOT ONE ANSWER — 2026-09-05 (Krishna 🦚) on Tiberius 👑's
    # question, MEASURED against a real 20,765-byte record before it was believed. Keeping
    # the TAIL is right for AMENDMENTS, which accrete oldest-first. It is WRONG for a
    # BODY-ONLY memento, where the opening IS the state: on `clayton-d34333a9.md` the tail
    # rule delivered 8,745 bytes and dropped the first line — the who-am-I the seat needs
    # first. ⇒ The caller says which end it is quoting, because only the caller knows.
    if keep == "head":
        head    = raw[ :max_bytes ].decode( "utf-8", errors="ignore" )
        omitted = len( raw ) - len( head.encode( "utf-8" ) )
        return (
            f"{head}\n"
            f"──── CUT HERE — {omitted} later bytes omitted ────\n"
            f"The rest of the body was dropped to keep boot context cheap; what you have\n"
            f"is the OPENING and is INCOMPLETE. Read the full record before acting on it:\n"
            f"  {path}\n"
            f"────────────────────────────────────────────────────"
        )

    tail    = raw[ -max_bytes: ].decode( "utf-8", errors="ignore" )
    omitted = len( raw ) - len( tail.encode( "utf-8" ) )
    return (
        f"──── CUT HERE — {omitted} earlier bytes omitted ────\n"
        f"Older amendments were dropped to keep boot context cheap; what follows\n"
        f"is the NEWEST portion and is INCOMPLETE. Read the full record before\n"
        f"acting on it:\n"
        f"  {path}\n"
        f"────────────────────────────────────────────────────\n"
        f"{tail}"
    )


def _repo_root_owning( start ):
    """
    Lazy seam onto lupin_mcp.memento_repo_root.repo_root_owning.

    Imported inside the call rather than at module scope because this hook runs on
    every SessionStart fleet-wide, in repos that may not have lupin_mcp importable.
    An ImportError here must degrade to the walk below, never take SessionStart down.

    Ensures:
        - the repo root owning `start`, or None when it cannot be resolved
        - never raises
    """
    try:
        from lupin_mcp.memento_repo_root import repo_root_owning
        return repo_root_owning( start )
    except Exception:
        return None


def _resolve_repo_root( cwd=None, repo_root_fn=None ):
    """
    Find the repo whose mementos this seat should read, from the session's own cwd.

    LUPIN_ROOT is wrong here: the hook runs fleet-wide, so it sent non-lupin seats to lupin's
    directory. A `.git` walk is the codebase's convention for which project am I in (`detect_project`).
    A linked worktree's `.git` is a file, so git's `repo_root_owning` answers first.

    Requires:
        - cwd is the session's working directory, or None
        - repo_root_fn( start ) -> the repo root owning `start`, or None

    Ensures:
        - Returns the repo root that owns cwd: the main checkout when cwd is in a linked
          worktree, and that tree's own root for a plain repo, subdirectory, nested repo
          or submodule. Repo identity is never crossed: a lupin-mobile worktree resolves
          to lupin-mobile
        - When git cannot answer or raises, falls back to the nearest `.git` ancestor
          of cwd. The walk stays because the hook runs where git or lupin_mcp may be
          missing, and a hook that raises takes SessionStart down
        - Falls back to LUPIN_ROOT, then os.getcwd(), when neither resolves
        - Each fallback prints a warning naming the cause to stderr, never stdout
        - Never raises
    """
    start   = cwd or os.getcwd()
    resolve = repo_root_fn if repo_root_fn is not None else _repo_root_owning

    # 🔴 THE CAUSE IS CARRIED, NOT SWALLOWED (maya 🌻's review finding, 2026-09-04).
    # This was `except Exception: pass`, and the fallback below then announced "git
    # could not resolve the repo root" — which is a LIE when the resolver RAISED.
    # A wrong number gets re-derived by the next reader; a wrong MECHANISM sends them
    # into innocent code, and git was the innocent party named here.
    cause = None
    try:
        owned = resolve( start )
        if owned: return str( owned )
        cause = "git could not resolve a repo root"
    except Exception as error:
        cause = f"the repo-root resolver RAISED ({type( error ).__name__}: {error})"

    # 🔴 BOTH FALLBACKS BELOW ANNOUNCE THEMSELVES (Rio ⚡, 2026-09-04). They were
    # silent, and a silent fallback here does not merely lose precision — the walk
    # is WRONG IN A WORKTREE by this function's own docstring, so reaching it IS the
    # defect returning, reported as a normal boot. STDERR, never stdout: the hook
    # pipes listener stdout into a shared 130 MB log where nobody would see it.
    try:
        path = os.path.abspath( start )
        while True:
            if os.path.exists( os.path.join( path, ".git" ) ):
                print( f"[register_session] WARNING: {cause} for {start!r}; fell back to the "
                       f"nearest .git ancestor and SETTLED FOR {path!r}. If that is a linked "
                       f"worktree this is the WRONG tree — the memento writer uses its MAIN "
                       f"checkout.", file=sys.stderr )
                return path
            parent = os.path.dirname( path )
            if parent == path: break          # reached filesystem root
            path = parent
    except OSError as error:
        # Same misattribution hazard one level down: without this the message below
        # would report "no .git ancestor" when the WALK ITSELF errored — a different
        # fault sending the reader somewhere else innocent.
        cause = f"{cause}, then the .git-ancestor walk FAILED (OSError: {error})"

    settled = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    print( f"[register_session] WARNING: {cause} for {start!r} and no .git ancestor was found; "
           f"SETTLED FOR {settled!r} from LUPIN_ROOT/cwd. This is the ambient root and it "
           f"describes the HOST, not this seat — a non-lupin seat resolves to lupin here.",
           file=sys.stderr )
    return settled


def _stamp_respin_boot_receipt( stable_session_id, persona_name, tmux_session,
                                memento_path, memento_written_at, repo_root,
                                memento_persona=None, block=None, block_error=None ):
    """
    Leave the boot receipt a re-spin's wake check reads, on every boot.

    It fires even when no memento resolved: "woke but consumed nothing" and "never woke"
    are different failures with different fixes. `memento_path=None` is a finding, not a
    reason to stay quiet.

    Requires:
        - stable_session_id is this seat's session id, or None
        - memento_path is the file the boot path actually opened, or None

    Ensures:
        - writes the receipt best-effort; returns the path written, or None
        - places it under this repo_root's fleet data root, never the ambient one:
          `write_boot_receipt` would otherwise read the ambient project root, and a
          caller in a temp tree would write real receipts into the live fleet directory
        - never raises and never blocks the boot; a diagnostic that can break a
          SessionStart is worse than the failure it reports. An unimportable
          module (a partially-installed tree) is swallowed the same way.
    """
    try:
        from cosa.agents.heartbeat_arbiter.respin_wake_check import write_boot_receipt
        from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
        return write_boot_receipt(
            session_id         = stable_session_id,
            persona            = persona_name,
            tmux_session       = tmux_session,
            memento_path       = memento_path,
            memento_written_at = memento_written_at,
            memento_persona    = memento_persona,
            repo_root          = repo_root,
            base_dir           = str( fleet_data_root( repo_root ) ),
            block              = block,
            block_error        = block_error,
        )
    except Exception:
        return None


def _memento_body_after_header( content ):
    """
    Return the record's body after the header line and before the amendment tail, or None.

    A record written whole by `memento_io.py write` keeps its state in the body, with no
    amendment marker, so it must not be called near-blank. The presence floor only separates
    nothing from something. Never tune it to split populations, or the next record shape misfiles.

    Requires:
        - content is the memento text, or None

    Ensures:
        - Returns the body with the header line and any amendment tail removed
        - Returns None when content is empty, or the remaining body is under the
          presence floor, which sits an order of magnitude below the smallest real
          record; the caller then emits the near-blank warning
        - Never raises
    """
    if not content: return None

    body = content
    idx  = body.find( _MEMENTO_AMENDMENT_MARKER )
    if idx != -1: body = body[ :idx ]

    lines = body.split( "\n" )
    if lines and _MEMENTO_HEADER_MARKER in lines[ 0 ]: lines = lines[ 1: ]
    body = "\n".join( lines ).strip()

    return body if len( body.encode( "utf-8" ) ) >= _MEMENTO_PRESENCE_FLOOR_BYTES else None


def _build_memento_block( stable_session_id, persona_name, repo_root=None, cwd=None,
                          tmux_session=None ):
    """
    Render this seat's memento pointer and newest amendment as additionalContext for boot.

    A self-re-spin types `/clear` and must find its memento in boot context, not wait to be
    reminded. The lookup is not gated on `source == "clear"`: dismiss-then-spawn arrives as a
    new `startup` session, so gating would skip the paths that need it. A miss costs one listing.

    Requires:
        - stable_session_id is a string or None
        - persona_name is this seat's allocated persona, or None
        - repo_root is a directory path, or None to resolve from `cwd`
        - cwd is the session's working directory (the hook payload's `cwd`),
          used to find the repo this seat actually sits in

    Ensures:
        - Returns "" when no memento resolves for this seat (no noise on the
          overwhelmingly common boot that has none)
        - Otherwise returns a block naming the path and quoting the newest
          amendment, visibly truncated if it exceeds the byte cap
        - Stamps the boot receipt exactly once, on every path that reaches the
          try, including the empty one and every failing one
        - Never raises. Every failure — including a repo-root resolution that
          throws — is recorded in the receipt's `block_error` and returns "".
    """
    # 🔴 THIS CALL WAS OUTSIDE THE try AND MY REASON FOR LEAVING IT THERE WAS
    # FALSE. I argued that wiring it in risked a receipt landing in the AMBIENT
    # repo's fleet directory, and that a misplaced receipt is worse than a
    # missing one. The second half is still true; the first is not an argument
    # for anything, because `_resolve_repo_root` DOES NOT RAISE — its contract
    # says "Never raises" and it means it, falling back to LUPIN_ROOT and then
    # cwd with a stderr warning.
    #
    # Clayton 😎 caught it (2026-09-06); the measurement is his claim confirmed:
    #     cwd            /tmp/other-repo-…     (not a git repo)
    #     resolved root  …/lupin-wt-…          <- the AMBIENT root
    #     fleet dir      …/projects-data/lupin
    #     correct dir    …/projects-data/other-repo-…
    # ⇒ THE MISPLACED RECEIPT ALREADY HAPPENS on the ordinary SUCCESS path, via
    # that silent settle, so leaving this outside prevented nothing. And moving
    # it in adds no risk: if it ever did raise, repo_root stays None and
    # fleet_data_root( None ) resolves to the SAME ambient directory the settle
    # would have chosen. The objection was void, not merely weak.
    #
    # ⚠️ THE SETTLE IS A SEPARATE AND LARGER FINDING, NOT FIXED HERE: a seat in a
    # non-lupin repo gets a healthy-looking receipt written into LUPIN's fleet
    # directory — a false green for a wake check that is not its own. It is the
    # ambient-root hazard this repo's CLAUDE.md already documents, arriving in
    # the boot receipt. Do not fold it into this fix.
    # 🔴 THIS SHAPE IS CLAYTON 😎's, NOT MINE (2026-09-06). All three parts are
    # his and each is load-bearing: PRE-INITIALISE every name above the try,
    # COMPUTE the argument expressions into locals INSIDE it, and let the
    # finally's stamp evaluate NOTHING BUT BARE NAMES. He specified it after
    # killing the fix I was about to write, which had none of the three.
    # Attributed at the site deliberately — a variant credited to whoever typed
    # it tells the next reader the review seat contributed nothing.
    #
    # A name bound INSIDE the try is unbound in the finally when the try failed
    # before the binding, so a naive finally raises UnboundLocalError — and that
    # error REPLACES the real fault, so the caller at :2445 swallows a message
    # naming a variable instead of the actual failure. Measured:
    #     naive           -> UnboundLocalError: cannot access local variable 'path'
    #     pre-initialised -> RuntimeError: THE REAL FAULT   (survives)
    # That is worse than the bug it fixes: a red herring pointing at innocent
    # code, where today a reader at least gets a real exception name.
    #
    # And an ARGUMENT EXPRESSION in the finally re-opens the whole defect one
    # level down — `_written_at_of( header )` and `_persona_of( path, header )`
    # used to be evaluated in the stamp call itself, which is why four call
    # sites still left NO RECEIPT AT ALL after the first fix covered the render.
    path = header = written = memento_persona = None
    block, block_error      = "", None
    try:
        repo_root       = repo_root if repo_root is not None else _resolve_repo_root( cwd )
        path            = _resolve_memento_path( stable_session_id, persona_name, repo_root )
        header          = _header_of( path ) if path else None
        written         = _written_at_of( header ) if path else None
        memento_persona = _persona_of( path, header ) if path else None
        block           = _render_memento_block( path )
    except Exception as error:
        block           = ""
        block_error     = type( error ).__name__
    finally:
        # THE ONLY WRITE, AND IT CANNOT BE SKIPPED. A missing receipt file is
        # indistinguishable from "the hook never ran" — the exact silence this
        # receipt exists to end — so the instrument must not be able to
        # reproduce its own target defect.
        _stamp_respin_boot_receipt(
            stable_session_id, persona_name, tmux_session,
            path, written, repo_root,
            memento_persona = memento_persona,
            block           = block,
            block_error     = block_error,
        )

    return block


def _render_memento_block( path ):
    """
    Render the block for a resolved memento path, with no side effects.

    Split out of `_build_memento_block` so the receipt can be stamped with what
    this actually produced. Keeping the render pure is the point: the stamp is
    the only write, and it happens once, after this has returned.

    Requires:
        - path is the memento file the boot path resolved, or None

    Ensures:
        - returns "" when path is None or the file cannot be read
        - never raises
    """
    if not path: return ""

    try:
        with open( path, "r", encoding="utf-8", errors="replace" ) as fh:
            content = fh.read()
    except OSError:
        return ""

    written   = _written_at_of( _header_of( path ) )
    stamp     = f"  written {written}\n" if written else "  written: UNDATED — this record carries no timestamp\n"

    amendment = _extract_amendment_tail( content )
    if amendment:
        # The tail is what you had not yet acted on; the body's opening is who you are.
        # A seat needs both, and before this the tail could consume the whole budget.
        head_src = _substantive_body( content[ : content.find( amendment ) ] )
        lead     = _truncate_visibly( head_src, path, max_bytes=_MEMENTO_BODY_LEAD_BYTES,
                                      keep="head" ) if head_src else ""
        body     = _truncate_visibly( amendment, path,
                                      max_bytes=_MEMENTO_MAX_BYTES - _MEMENTO_BODY_LEAD_BYTES )
        headline = "  🧠  YOU HAVE A MEMENTO — YOU WROTE IT BEFORE THIS CONTEXT RESET"
        section = (
            "  Who you are, from the top of the record:\n"
            "\n"
            f"{lead}\n"
            "\n"
            "  Your amendments — what you wrote down but had not yet acted on —\n"
            "  follow. The full record is one read away at the path above.\n"
            "\n"
            f"{body}\n"
        ) if lead else (
            "  Your amendments — what you wrote down but had not yet acted on —\n"
            "  follow. The full record is one read away at the path above.\n"
            "\n"
            f"{body}\n"
        )
    elif _memento_body_after_header( content ) and _substantive_body( content ):
        # 🔴 THE THIRD CASE, AND ITS ABSENCE WAS THE BUG (row 508449b7).
        # This branch did not exist: a record with no amendment tail fell
        # straight to the near-blank warning below, and a memento written WHOLE
        # by `memento_io.py write` has ALL its state in the body and no
        # amendment marker anywhere. Measured: 213 of 341 records took the
        # warning, and 210 of those were >= 2000 bytes of real state — the
        # largest, at 21,025 bytes, was announced to its seat as carrying none.
        #
        # ⇒ A seat told its full record is blank does not read it. That is the
        # same failure Rachel's warning was written to prevent, arrived at from
        # the opposite direction: she stopped a thin record wearing a green
        # banner; this stops a FULL record wearing a red one. Both mislead about
        # what is in the file, and the fix for one must not reintroduce the other
        # — which is why the warning below is kept, not replaced.
        #
        # 🔴 THIRD STATE, ADDED 2026-09-05 (Krishna 🦚) ON TIBERIUS 👑'S REPORT.
        # The branch below is RIGHT about a genuinely empty record and was being
        # reached by full ones, because the test was `has an amendment tail` while
        # the message said `carries no state`. Those are different questions, and a
        # memento written the way the workflow prescribes — one `write` at
        # prepare-for-re-spin — answers YES to the second and NO to the first.
        #
        # MEASURED over io/mementos/: 656 records, 517 with no tail. 516 of those
        # carry real prose (smallest 1,315 bytes); exactly ONE strips to nothing,
        # and it is `chloe.md`, a POINTER rather than a record. So the warning was
        # firing on 517 records and was correct about none of them.
        #
        # ⚠️ THE WARNING IS NOT WEAKENED — it is narrowed to the case it describes.
        # Tiberius asked for exactly that and explicitly did not ask for a revert.
        #
        # ⚠️ MERGED (triage staging line, row ef0fa72b): the two fixes above landed
        # separately and disagree on ONE thing — row 508449b7 uses a 200-byte presence
        # floor after the header, Krishna's 2026-09-05 fix a comment-stripped prose predicate
        # with no byte cutoff. Both are required here, so every case either side's tests
        # pin keeps its answer. Between them sits an untested zone neither corpus contains
        # (a record with 1-199 bytes of prose, or 200+ bytes of comments only): it takes
        # the near-blank warning. The body is quoted from its OPENING (Krishna's
        # measured finding that the tail rule dropped the who-am-I line).
        body     = _truncate_visibly( _memento_body_after_header( content ), path, keep="head" )
        headline = "  🧠  YOU HAVE A MEMENTO — ALL OF ITS STATE IS IN THE BODY"
        section = (
            "  This record was written WHOLE — its state is in the body, and it has no\n"
            "  amendment tail, which is NORMAL: a memento written once at prepare-for-re-spin\n"
            "  puts everything in the body. It follows; the full record is at the path above.\n"
            "\n"
            f"{body}\n"
        )
    else:
        # 🔴 SAY IT LOUDLY. Measured 2026-08-15 (Rachel 🕊️): three seats
        # re-spun; two of their records carried no amendment, and the block
        # they got was ~440 bytes against ~8,700 for a record with a tail.
        # Under the old wording that arrived inside a "YOU HAVE A MEMENTO"
        # banner, which reads as success — a seat gets a pointer, no state, and
        # no signal that anything is missing. A near-blank rehydrate wearing a
        # green banner is worse than a red one, because nobody goes looking.
        #
        # ⚠️ STILL REACHED, AND STILL RIGHT — but for a NARROWER population than
        # when it was written. It now means "no amendment tail AND no body worth
        # the name", which is what Rachel actually measured. The 213 records that
        # used to land here wrongly take the branch above.
        #
        # ⚠️ NARROWED 2026-09-05: this now fires only when the body carries no
        # prose at all. Rachel's finding stands — what changed is that a record
        # WITH state no longer lands here.
        headline = "  ⚠️  MEMENTO FOUND BUT IT CARRIES NO STATE — TREAT AS A NEAR-BLANK RETURN"
        section = (
            "  The record exists and is yours, but it has NO amendment block and\n"
            "  no substantive body — so there is nothing here about what you were\n"
            "  doing.\n"
            "\n"
            "  Read the full record before acting, and expect it to be thin.\n"
            "  If you owe anyone work, the store is the authority, not this file:\n"
            "  query it, and re-derive rather than trusting this to be current.\n"
        )

    return (
        "\n"
        "════════════════════════════════════════════════════════════════\n"
        f"{headline}\n"
        "════════════════════════════════════════════════════════════════\n"
        f"  {path}\n"
        f"{stamp}"
        "\n"
        f"{section}"
        "════════════════════════════════════════════════════════════════\n"
    )


def _release_voice_persona_via_http( server_url, project, stable_session_id ):
    """
    Release the session's voice persona through the cosa-voice HTTP release endpoint.

    The server clears voice_persona on the bridge file and broadcasts voice_persona_released,
    so the frontend drops the stale persona. Any failure logs a warning to stderr and returns
    False; the hook continues with its bridge write either way.

    Requires:
        - server_url is a non-empty string (e.g. http://localhost:7999)
        - project is a non-empty string used to look up hook credentials
        - stable_session_id is a non-empty string

    Ensures:
        - Returns True on successful POST /release (HTTP 2xx)
        - Returns False on any failure (logged to stderr)
        - Never raises exceptions
        - Uses _SERVER_TRANSPORT_TIMEOUT_SECONDS on both /auth/login and
          /release — sized to outlast a `:7999` reload window rather than
          fail inside one

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
        with urllib.request.urlopen( login_req, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS ) as resp:
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
        with urllib.request.urlopen( rel_req, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS ) as resp:
            resp.read()  # drain
        return True

    except ( urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
             KeyError, FileNotFoundError, OSError, ValueError ) as e:
        print( f"[register_session] WARNING: voice persona release failed ({type( e ).__name__}: {e})",
               file=sys.stderr )
        return False


def _resolve_window_tokens():
    """
    Return the context-window size in tokens to pin into the bridge at spawn.

    The assessor needs the true window as its denominator; occupancy cannot show it (a 1M and a
    200k worker at 138k look identical). So it reads LUPIN_CC_WINDOW_TOKENS, set at spawn, default 1M.
    See: src/rnd/v0.1.8/2026.06.07-managing-context-memory/2026.06.08-context-pressure-revised-plan.md, section 4.

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


def emit_context_clear_marker( payload ):
    """
    Emit one JSONL context-clear marker when the payload reports source == "clear".

    payload["source"] (startup, resume, clear or compact) is the authoritative lifecycle
    signal, exact where the UUID-rotation heuristic under-reports. The DM-verbosity pilot
    reads this marker to match a context reset with a change in DM length.

    Requires:
        - payload is a dict (the SessionStart hook input)

    Ensures:
        - writes a {"marker":"context_cleared","source":"clear"} line via
          log_to_stream when payload["source"] == "clear"
        - does nothing for any other source (startup/resume/compact/absent)
        - returns True when a marker was emitted, False otherwise
    """
    source = payload.get( "source", "" )
    if source == "clear":
        log_to_stream( "session_start", payload, extra={ "marker": "context_cleared", "source": source } )
        return True
    return False


def main():

    # ── Phase 1: Read hook input ──────────────────────────────────────────
    payload = read_hook_input()
    if not payload:
        # 🔎 WITNESS FOR THE FIRST NO-BRIDGE EXIT (row e9822f8d). This return
        # leaves NO bridge, NO lockfile and NO env file, and the seat that comes
        # up behind it is healthy, invisible and unaddressable: list_spawned_sessions
        # says alive, dm_send says recipient_unresolved, and the session itself works
        # fine and DMs OUT. Exiting quietly on an unreadable payload is CORRECT — a
        # raising SessionStart is itself how you get a seat with no bridge — but the
        # SILENCE is what left that row undiagnosed for four days.
        #
        # The row's own body names stderr as the first place to look, because hook
        # stderr lands in the session's OWN transcript as a hook_success attachment
        # (the 86aa79ac method). This is the line that will be there next time.
        print( "[register_session] WARNING: hook payload was empty or unreadable — "
               "NO session bridge written. This seat will have no voice persona, "
               "cannot set a session topic, and cannot receive DMs (row e9822f8d).",
               file=sys.stderr )
        emit_json( {} )
        sys.exit( 0 )

    session_id      = payload.get( "session_id", "" )
    transcript_path = payload.get( "transcript_path", "" )
    cwd             = payload.get( "cwd", "" )

    # ── Context-clear marker (DM-verbosity pilot) ─────────────────────────
    emit_context_clear_marker( payload )

    # 🔎 WITNESS FOR THE SECOND NO-BRIDGE EXIT (row e9822f8d). EVERYTHING in
    # Phase 2 — the lockfile, the /clear detection, the bridge write itself — is
    # guarded by `if session_id:` below. A payload that parses but carries no
    # session_id therefore falls straight through to Phase 3 having written
    # nothing, and until now said nothing either.
    #
    # ⚠️ THIS IS THE HALF THE EXISTING INSTRUMENTS CANNOT SEE. The persona-alloc
    # give-up got a witness in 99589967 and the bridge WRITE got one inside
    # atomic_write_json — but both live DOWNSTREAM of this branch. A witness
    # bolted onto a later step cannot fire when the hook never reaches that step,
    # which is exactly why two commits naming e9822f8d did not close it.
    if not session_id:
        print( "[register_session] WARNING: hook payload carried no session_id "
               f"(keys: {sorted( payload )}) — NO session bridge written. Same "
               "consequence as an empty payload: persona-less, topic-less, "
               "unaddressable by DM (row e9822f8d).", file=sys.stderr )

    # ── Phase 2: Write session bridge file ────────────────────────────────
    # Row 8ccc20ab: this line used to be a bare expanduser of the real bridge
    # directory — the write that merged a fixture into three LIVE seats. It now
    # resolves through the one seam, so LUPIN_SESSIONS_DIR redirects it.
    session_dir  = str( sessions_dir() )
    session_file = None
    old_data     = None
    is_context_clear      = False
    previous_persona_name = None  # Set when /clear preservation fails AND old bridge had a persona; threaded into Phase 4.5 alloc

    if session_id:
        os.makedirs( session_dir, exist_ok=True )
        # Enforce setgid + group-rwx EXPLICITLY: makedirs' mode arg is umask-masked
        # and ignored entirely when the dir already exists, so it cannot guarantee
        # 2770. The setgid bit makes bridges written here inherit THIS dir's group,
        # so a cross-uid writer (container uid 1001 ⇄ host) and reader share access
        # regardless of who wrote last. See
        # src/rnd/v0.1.9/2026.07.24-vm-persona-bridge-mount-uid-divergence.md.
        try:
            os.chmod( session_dir, 0o2770 )
        except OSError as e:
            print( f"[register_session] WARNING: could not set 2770 on {session_dir}: {e!r} "
                   f"— cross-uid bridge sharing may fail", file=sys.stderr )

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

        # ── sender_id: computed HERE, on the host, and carried in the bridge ──
        # Row 2184bebb, Option B (Mr. Radio's ruling 2026-09-19). The server used to
        # re-derive this in `_sender_id_for_bridge` by walking `detect_project_for_path(
        # bridge["cwd"] )` INSIDE the lupin-rest container — where host paths do not
        # exist. The `.git` walk found nothing, fell back to the cwd BASENAME, and every
        # worktree seat was served as `claude.code@seat-cc-author-<name>.deepily.ai#<hash>`
        # while its own notifications said `claude.code@lupin.deepily.ai#<hash>`. Two
        # identities for one seat; Krishna, Rio and Rachel each appeared TWICE on Rick's
        # focus rail. Main-checkout seats looked right only by accident — their basename
        # happens to be "lupin".
        #
        # The session is the only party that KNOWS its identity. Path-parsing INFERS it,
        # and an inference that reads `/lupin/.claude/worktrees/seat-…` correctly today
        # breaks the day someone nests a worktree or renames a repo. So the host writes
        # what it knows and the server stops guessing.
        #
        # ⚠️ NOT `build_sender_id_for_cc()` HERE, DELIBERATELY. That helper anchors the
        # project on the bridge file's cwd snapshot — and at THIS point in Phase 2 the
        # bridge has not been written yet, so it would read an absent or PREVIOUS
        # session's bridge. The payload's `cwd` is the SessionStart cwd, which is exactly
        # the value that snapshot exists to preserve, so we resolve from it directly and
        # get the same answer without the ordering hazard.
        #
        # On any failure this stays ABSENT rather than becoming a guess or a sentinel:
        # Option A (infer from the path segment before `/.claude/worktrees/`) is BANNED,
        # including as a silent fallback — "or we re-create the exact defect you just
        # found, a wrong identity that looks like a right one."
        sender_id = None
        if cwd:
            try:
                from cosa.agents.utils.sender_id import build_sender_id, detect_project_for_path
                sender_id = build_sender_id(
                    "claude.code",
                    project = detect_project_for_path( cwd ),
                    suffix  = str( stable_session_id )[ :8 ],
                )
            except Exception as e:
                print( f"[register_session] WARNING: could not compute sender_id for the bridge "
                       f"({e!r}) — the bridge will carry none and /api/commons/active-sessions "
                       f"will report sender_id null for this seat rather than guess it.",
                       file=sys.stderr )

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
        # Only when we actually have one: an ABSENT key and a null both mean "the server
        # must not guess", and absent keeps the bridge free of fields that carry nothing.
        if sender_id:
            session_data[ "sender_id" ] = sender_id

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
        # 🔴 REBIND, not decoration (row from Clayton 😎's measurement, 2026-08-30).
        # The write two dozen lines below persists `merged` correctly — and then
        # `_record_listener_pid()` at the end of main() writes THIS dict WHOLESALE
        # over the same path (atomic_write_json, not read-modify-write), so every
        # on-disk key main() does not itself carry was erased ~180 lines later.
        # `session_topic` is a confirmed production victim: silently dropped on
        # every /clear. Same mechanism as the manager-figure stamp at row 6325123c,
        # which was fixed by keeping the in-memory dict in sync; this closes it at
        # the source instead of one field at a time.
        session_data = merged
        # Atomic (row 49b2c80b). The stable-id lockfile twelve lines above
        # is already O_EXCL against "the documented double-fire on
        # --continue (two concurrent SessionStart hooks)" — that same
        # concurrency reaches THIS write, which had no guard at all. The
        # lock went on the id; the bridge got nothing.
        #
        # ⚠️ NO try/except HERE — deliberately, row 0f10ff75. There WAS an
        # `except OSError: pass` wrapping this block and it was DEAD:
        # `atomic_write_json` catches ( OSError, TypeError, ValueError )
        # itself, unlinks its temp file, prints a stderr witness naming the
        # path, and returns False. Its contract says "Never raises" and the
        # BODY agrees. The only other statement the wrapper covered was
        # `os.path.exists`, which swallows OSError and returns False.
        # ⇒ The guard for a failed bridge write lives INSIDE the callee, at
        # the mechanism — one witness rather than one per call site, six of
        # which ignore the return entirely. A dead handler here read as
        # "handled locally" and cost the next reader the trail.
        atomic_write_json( session_file, merged )

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
    # Give-up record for Phase 7. None means "no failure to report" — either
    # allocation succeeded or it was never attempted (persona carried forward).
    voice_persona_failure = None
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
            allocated, voice_persona_failure = _allocate_voice_persona_via_http(
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
            voice_persona_failure = {
                "stage"      : "phase",
                "exception"  : type( e ).__name__,
                "message"    : str( e ),
                "attempts"   : 0,
                "server_url" : os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
            }

    # ── Phase 4.6: Stamp the implicit manager-figure answer (bug e5d600bd) ──
    # is_manager_figure()'s IMPLICIT source — "is this session's allocated
    # persona one of the repo's NAMED standing personas
    # (COSA_VOICE_PREFERRED_PERSONA__<PROJECT>)?" — can ONLY be resolved HERE,
    # where the caller's real env lives. The server (tasks.py:652 G1 blocked-mint
    # guard, and any future v2-experiment manager-vs-worker stratum classifier)
    # runs in the lupin-rest-dev container, whose env carries ZERO
    # COSA_VOICE_PREFERRED_PERSONA__* vars and LUPIN_ROOT=/var/lupin — so a
    # server-side re-derive fails closed for EVERY caller (Rick's Option A,
    # 2026-08-15). Compute the answer with os.environ AFTER allocation (the
    # persona name is now known — freshly allocated OR carried forward across a
    # /clear) and stamp it as a static bridge field the server reads directly.
    #
    # Only the IMPLICIT answer is stamped: the EXPLICIT source (role=="manager")
    # stays a live bridge field is_manager_figure() checks first. Fail-soft — a
    # stamp failure leaves the field absent and is_manager_figure() falls back to
    # the (server-empty) env compute: the exact pre-fix behavior, no regression,
    # and the bridge self-heals on its next SessionStart.
    if session_id:
        try:
            from lupin_cli.claude_code.hooks.lib.manager_figure import resolve_implicit_manager_figure
            from lupin_cli.claude_code.hooks.lib.session_bridge import (
                MANAGER_FIGURE_BRIDGE_FIELD, set_manager_figure_implicit )
            _mf_persona  = ( session_data.get( "voice_persona" ) or {} ).get( "name" )
            _mf_implicit = resolve_implicit_manager_figure( _mf_persona, os.environ )
            # Keep the IN-MEMORY dict in sync with the disk stamp (row 6325123c).
            # set_manager_figure_implicit() writes the FILE; _record_listener_pid()
            # at the end of main() then writes this dict WHOLESALE over that same
            # file (atomic_write_json, not read-modify-write), so a stamp that only
            # reached disk was erased ~45 lines later on every real session — 0 of
            # 47 bridges carried the field. Measured 2026-08-30: reproduced with a
            # stamp-then-_record_listener_pid sequence; the field vanishes. The
            # out-of-band drive never saw it because the test monkeypatches
            # _spawn_listener, so the clobbering write never runs.
            session_data[ MANAGER_FIGURE_BRIDGE_FIELD ] = _mf_implicit
            if not set_manager_figure_implicit( stable_session_id, _mf_implicit ):
                print( "[register_session] WARNING: manager-figure stamp not written "
                       "(bridge unresolved); is_manager_figure will fall back to the "
                       "server-empty env compute for this session (row e5d600bd)",
                       file=sys.stderr )
        except Exception as e:
            print( f"[register_session] WARNING: manager-figure stamp phase failed "
                   f"({type( e ).__name__}: {e})", file=sys.stderr )

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
        alarm_block = _build_persona_failure_block( voice_persona_failure, stable_session_id )
        try:
            allocated_persona = ( session_data.get( "voice_persona" ) or {} ).get( "name" )
            memento_block     = _build_memento_block( stable_session_id, allocated_persona, cwd=cwd,
                                                      tmux_session=session_data.get( "tmux_session" ) )
        except Exception as e:
            print( f"[register_session] WARNING: memento block failed ({type( e ).__name__}: {e})",
                   file=sys.stderr )
            memento_block = ""
        # ── Manager-roster drift check (row a1a84682) ───────────────────────
        # COSA_VOICE_MANAGERS__<P> (who APPEARS to be a manager) and
        # COSA_VOICE_PREFERRED_PERSONA__<P> (who may WRITE to the task store,
        # via manager_figure) are supposed to name the same people. The
        # launcher now DERIVES the second from the first, so this is the belt
        # for the paths it does not own — a hand-exported chain, a bare
        # terminal, a session alive across a roster edit. Rendered into
        # additionalContext because a drift printed only to stderr is a drift
        # nobody reads: that is exactly how the 2026-08-18 one survived.
        try:
            from lupin_cli.claude_code.hooks.lib.roster_consistency import (
                find_roster_disagreements, format_roster_drift_block
            )
            _drift      = find_roster_disagreements( os.environ )
            drift_block = format_roster_drift_block( _drift )
            if _drift:
                print( f"[register_session] WARNING: manager roster drift on {[ d[ 'project' ] for d in _drift ]}",
                       file=sys.stderr )
        except Exception as e:
            print( f"[register_session] WARNING: roster drift check failed ({type( e ).__name__}: {e})",
                   file=sys.stderr )
            drift_block = ""
        emit_json( {
            "additionalContext": f"Session ID: {session_id}\n\n{status_block}{alarm_block}{drift_block}{memento_block}"
        } )
    else:
        emit_json( {} )


if __name__ == "__main__":
    main()
