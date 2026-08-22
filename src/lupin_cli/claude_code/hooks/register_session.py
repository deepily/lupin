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
# `notify_user_async.py:197-201` as a bare `requests.post( timeout=request.timeout )`.
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
    Map a `/docs` probe exception onto the status string the SessionStart banner
    shows for the server.

    🔴 THE WORDING IS THE POINT HERE, NOT DECORATION. The flat "unreachable"
    string this replaces is what misdirected row 204911ca across two sessions: a
    reader saw it and concluded the server was DOWN, when `:7999` was mid-reload
    and would have answered a few seconds later.

    The two conditions are genuinely distinguishable at the client, and they
    demand opposite fixes:

      - A STOPPED server REFUSES. Nothing holds the port, the kernel replies
        RST, and urlopen raises URLError(ConnectionRefusedError) essentially
        instantly. The fix is "start the server."
      - A RESTARTING server ACCEPTS AND STALLS. `uvicorn --reload` keeps the
        listening socket bound in the reloader PARENT across the restart, so the
        kernel completes the handshake and queues a request that nothing is
        there to answer yet. The probe exhausts its budget and raises
        TimeoutError. The fix is "wait a few seconds."

    Both behaviours were measured as controls on row 204911ca (§3), which is why
    this split is observable rather than aspirational: C2 (a genuinely closed
    port) refused in 0.0003s, and C1 (a blackhole socket — bound and listening,
    never accept()ing) timed out at 15.02s with a bare TimeoutError.

    Requires:
        - exc is the exception raised by the probe
        - server_url is a non-empty string
        - timeout_seconds is the positive budget the probe was given

    Ensures:
        - returns a status string that NAMES the condition whenever this
          function can identify it, never a bare "unreachable"
        - treats an HTTP error status as REACHABLE — the server answered
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
          so it cannot block session start; a reload is LABELLED as a
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
    Allocate a voice persona for the given session by calling the cosa-voice
    HTTP endpoint at /api/cosa-voice/voice-persona/{sid}/allocate.

    The server endpoint atomically picks an unallocated persona from the pool
    (under asyncio.Lock), writes it to the bridge file, and broadcasts a
    voice_persona_assigned WebSocket event.

    Fail-soft, but NEVER SILENT (candidate A, 2026-07-19): any failure returns
    ( None, failure_dict ) instead of a bare None, so the caller can route the
    give-up into the session's own boot context rather than leaving it in a
    stderr line with no reader. The session still continues without a persona;
    the speech router falls back to Sam (the global default voice).

    Diagnosis this implements: 86aa79ac. The server at localhost:7999 was
    unreachable at SessionStart, the 2s urlopen budget expired, the broad
    except swallowed it to one stderr line, and the session ran unattributed
    for hours. The trigger was a down server; THE DEFECT WAS THAT THE GIVE-UP
    HAD NO READER.

    Requires:
        - server_url is a non-empty string (e.g. http://localhost:7999)
        - project is a non-empty string used to look up hook credentials
        - stable_session_id is a non-empty string

    Ensures:
        - Returns ( persona_dict, None ) on success
        - Returns ( None, failure_dict ) on any failure, where failure_dict
          carries stage / exception / message / attempts / server_url
        - persona is None IFF failure is not None — there is no silent-None
          return left in this function
        - Never raises exceptions
        - Retries transport failures on the _ALLOCATE_TIMEOUT_LADDER_SECONDS
          budget (5s, 10s, 15s per rung). Each attempt makes TWO calls — login
          then /allocate — and both take the rung's timeout, so the worst-case
          wall clock is 2x the tuple sum = 60s, not 30s. A server that ANSWERS
          with a wrong or empty body is NOT retried, because retrying a
          definite answer is noise
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
    def _fail( stage, exception_name, message, attempts ):
        """Build the structured give-up AND log it to stderr (forensic copy)."""
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
    Render the voice-persona give-up as a block for the SessionStart hook's
    `additionalContext` — the channel the SESSION ITSELF reads at boot.

    This is the whole point of candidate A. The except path already printed to
    stderr and had been doing so all along; locating that stderr took a
    dedicated hunt (it lands as a hook_success attachment inside the session's
    own transcript, not any file under ~/.claude/sessions). A give-up printed
    where nobody reads it is not an alarm. This function puts it where the
    model will read it, at boot, at zero interrupt cost to the user.

    Composes with candidate D (7b2db462): D tells a null session to announce
    itself; this block is what lets that announcement say WHY.

    Requires:
        - failure is None, or a dict carrying stage/exception/message/
          attempts/server_url
        - stable_session_id is a string or None

    Ensures:
        - Returns "" when failure is None (no alarm when nothing failed)
        - Otherwise returns a block naming the cause AND the session_id
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


def _persona_slugs( persona_name ):
    """
    Every slug a persona's mementos might be filed under, best first.

    ACCENTS ARE THE WHOLE REASON THIS RETURNS A LIST. "María" naively slugs to
    "mar-a", because a non-ASCII letter falls into the punctuation class and
    becomes a separator. That is not hypothetical: planning-is-prompting holds
    18 records named `.claude-memento-maria-*.md` and exactly one named
    `.claude-memento-mar-a-3bd9e86c.md`. A resolver keyed on the naive slug
    matches the single broken file and misses all 18 good ones — confidently
    wrong, which is the failure mode this whole block exists to prevent.

    So we fold accents first (María -> maria), which is what writers produce,
    and ALSO return the mangled form so records already written under it stay
    reachable. Normalizing on write is the real fix; until every legacy file is
    renamed, the resolver has to know both.

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

    This is the honest recency key. mtime is NOT: mementos are mirrored to
    ~/.claude/mementos/<project>/ and moved around by copies and rsync, every
    one of which resets mtime, so the newest mtime can easily be the oldest
    memento. The header stamp travels with the content.

    Requires:
        - header is a header line, or None

    Ensures:
        - Returns the ISO string when the stamp is present
        - Returns None when header is None or carries no stamp — NOT an error;
          real records exist without one (measured: 3 in planning-is-prompting,
          including .claude-memento-maria-350ac4c2.md). The caller ranks those
          last rather than crashing or silently dropping them.
        - Never raises
    """
    if not header: return None
    match = re.search( r"written_at=(\S+)", header )
    return match.group( 1 ) if match else None


def _memento_dirs( repo_root ):
    """
    Every directory a memento RECORD can live in, for this repo.

    FOUR of them, and the first cut knew about one (Rachel 🕊️, 2026-08-15,
    reproduced against 8b9a10e9). Her record sat at
    `io/mementos/rachel-9eb9253c.md` — a real 23KB memento whose own header
    declares `slot=io` — and the resolver never looked there, so she rehydrated
    blank for the third time tonight on the third distinct cause. She then
    named a fourth, `~/.claude/mementos/<project>/.claude-memento-<persona>-
    <sid8>.md`, which holds four more of her records.

    Note the two filename shapes do NOT line up with the two roots: the mirror
    carries BOTH the dotted repo-root shape at its top level and the bare
    `<persona>-<sid8>.md` shape under `io/mementos`. So a directory does not
    tell you its naming convention — enumerate all four and let the header
    decide, rather than reasoning about which slot is "current". Writers have
    moved between these over time and old records stay put; a resolver that
    backs the wrong one rehydrates a seat blank while its state sits on disk.

    Requires:
        - repo_root is a directory path

    Ensures:
        - Returns [ repo root, in-repo io slot, mirror root, mirror io slot ]
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

    WHY A PRE-FILTER AND NOT JUST HEADER CONFIRMATION. The io slot holds 337
    files in the mirror and 338 in the repo. Opening every one to read its
    header would put ~675 file reads on the boot path of every session in the
    fleet, to find one record. So the filename decides who is even a candidate,
    and the header still confirms the survivors — cheap test first, honest test
    second.

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


def _memento_candidates( repo_root, sid8=None, slugs=() ):
    """
    Memento RECORDS visible to this seat, across both slot families, newest first.

    Deliberately excludes `.claude-memento.md` — that file is a POINTER, not a
    record, and it is single-occupancy for the entire repo. It currently names
    whichever seat wrote last, so resolving a seat's memento through it would
    hand one persona another persona's state. Empty is a safe answer; another
    seat's held merge and crew is not.

    Ordering key is the header's `written_at` stamp, falling back to mtime only
    when a record carries none. A record with neither still appears — it ranks
    last, but it is never silently dropped.

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

            header = _header_of( path )
            stamp  = _written_at_of( header )
            if stamp:
                # ISO strings sort lexicographically; the "1" tier outranks mtime.
                sort_key = ( 1, stamp )
            else:
                try:
                    sort_key = ( 0, str( os.path.getmtime( path ) ) )
                except OSError:
                    sort_key = ( 0, "" )
            out.append( ( path, header, sort_key ) )

    return sorted( out, key=lambda row: row[2], reverse=True )


def _header_of( path ):
    """
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

    Two sources, header first. The header's `persona=` field is authoritative
    when present; when it is absent — and it is absent on real records, e.g.
    `.claude-memento-maria-350ac4c2.md`, whose first line is a human heading
    rather than a machine header — the FILENAME carries the persona slug
    unambiguously. Falling back to the filename keeps those records reachable.

    Both sources are persona-scoped, so neither can leak one seat's memento to
    another. That is the property that matters here; recency is secondary.

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
    Find THIS seat's memento at the repo root.

    Two-step, and the ORDER is the whole design:

      1. Exact session-id match. A self-re-spin types `/clear` into its own
         pane and keeps its session id, so when a record names this id it is
         unambiguously ours — the strongest signal available.
      2. Newest record for this PERSONA. A re-spin done as dismiss-then-spawn
         arrives as a brand-new session, so step 1 finds nothing while the
         memento sits right there named for the OLD id. The persona is what
         actually carries across that boundary, so it is what we match on.
         Newest-mtime breaks the tie when a persona has several.

    Every candidate is confirmed by its `<!-- memento-record: … -->` header
    before it is accepted. A filename that merely matches is a guess, and a
    memento is the one artifact a rehydrating seat cannot afford to be wrong
    about — handing it someone else's state is worse than handing it none.

    Requires:
        - stable_session_id is a string (full uuid) or None
        - persona_name is this seat's allocated persona, or None
        - repo_root is a directory path

    Ensures:
        - Returns a confirmed memento path, or None when nothing resolves
        - Never returns a record belonging to a different persona
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

    # 2. Newest record for this persona — survives dismiss-then-spawn, where
    #    the seat is new but the persona carried over. Slugs are tried in
    #    order, accent-folded first.
    for slug in slugs:
        for path, header, _ in candidates:
            if _persona_of( path, header ) == slug:
                return path

    return None


def _extract_amendment_tail( content ):
    """
    Return the memento's whole AMENDMENT TAIL — everything from the FIRST
    `<!-- memento-amendment:` marker to the end of the file.

    Note `find`, not `rfind`, and the reason is empirical: the last marker in a
    real memento is frequently NOT the substantive one. `self_respin` appends a
    tiny bookkeeping amendment carrying only the nonce stamp it needs to prove
    freshness, so "the last block" resolves to four lines of plumbing while the
    block before it — the held merge, the crew, the correction owed — is
    dropped. Measured on cheech/80c17315: last-marker yielded 4 lines of nonce;
    first-marker yielded the 3.5KB that actually mattered.

    So the tail is the unit, not the block. A memento accretes: body written
    once, then amended before each re-spin. Everything after the first
    amendment is the part written but not yet acted on.

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


def _truncate_visibly( text, path, max_bytes=_MEMENTO_MAX_BYTES ):
    """
    Cap `text` at max_bytes KEEPING THE END, and say so IN BAND when it bites.

    Two decisions, both deliberate:

    - We keep the TAIL and drop the head. Amendments accrete oldest-first, so
      cutting from the end would discard the newest — precisely the state the
      seat has not yet acted on. Recency is the whole reason this block exists.
    - The cut announces itself. A silent cut hands the seat partial state it
      cannot tell is partial, which is worse than no state at all, because
      partial state reads as complete. So it counts the bytes it dropped and
      names the file holding them.

    Requires:
        - text is a string; path is the memento path the text came from
        - max_bytes is a positive int

    Ensures:
        - Returns text unchanged when it fits
        - Otherwise returns an explicit CUT marker naming the omitted byte
          count and the full path, followed by the NEWEST max_bytes of text
        - Never raises
    """
    raw = text.encode( "utf-8" )
    if len( raw ) <= max_bytes: return text

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


def _resolve_repo_root( cwd=None ):
    """
    Find the repo whose mementos this seat should read: the nearest `.git`
    ancestor of the session's own cwd.

    WHY NOT `LUPIN_ROOT` (María 🌸, 2026-08-15, reproduced against 8ff014e2).
    This hook is installed fleet-wide, not just in lupin. Reading the root from
    `LUPIN_ROOT` sent every non-lupin seat looking in lupin's directory, where
    its memento does not live — so a planning-is-prompting session resolved to
    nothing and rehydrated blank while its own record sat beside it. Her repro:
    `_resolve_memento_path(sid, "maria", $LUPIN_ROOT)` -> None, the same call
    against her repo root -> `.claude-memento-maria-e02f9c93.md`.

    Walking up to the nearest `.git` is the convention this codebase already
    uses to answer "which project am I in" (`detect_project`), so this follows
    the house rule rather than inventing a second one. `LUPIN_ROOT` survives
    only as the last fallback, for the case where cwd is absent or unrooted.

    Requires:
        - cwd is the session's working directory, or None

    Ensures:
        - Returns the nearest ancestor of cwd containing `.git`
        - Falls back to LUPIN_ROOT, then os.getcwd(), when no ancestor has one
        - Never raises
    """
    start = cwd or os.getcwd()
    try:
        path = os.path.abspath( start )
        while True:
            if os.path.exists( os.path.join( path, ".git" ) ): return path
            parent = os.path.dirname( path )
            if parent == path: break          # reached filesystem root
            path = parent
    except OSError:
        pass

    return os.environ.get( "LUPIN_ROOT", os.getcwd() )


def _stamp_respin_boot_receipt( stable_session_id, persona_name, tmux_session,
                                memento_path, memento_written_at, repo_root ):
    """
    Leave the boot receipt a re-spin's wake check reads (row b0570b67).

    THE ONE THING TO GET RIGHT: this fires on EVERY boot, including the boot
    where no memento resolved. "It woke but consumed nothing" and "it never woke
    at all" are different failures with different fixes, and skipping the write
    on the empty path would collapse them into the same silence — which is the
    bug this receipt exists to end. `memento_path=None` is a finding, not a
    reason to stay quiet.

    Requires:
        - stable_session_id is this seat's session id, or None
        - memento_path is the file the boot path actually opened, or None

    Ensures:
        - writes the receipt best-effort; returns the path written, or None
        - NEVER raises and never blocks the boot — a diagnostic that can break a
          SessionStart is worse than the failure it reports. An unimportable
          module (a partially-installed tree) is swallowed the same way.
    """
    try:
        from cosa.agents.heartbeat_arbiter.respin_wake_check import write_boot_receipt
        return write_boot_receipt(
            session_id         = stable_session_id,
            persona            = persona_name,
            tmux_session       = tmux_session,
            memento_path       = memento_path,
            memento_written_at = memento_written_at,
            repo_root          = repo_root,
        )
    except Exception:
        return None


def _build_memento_block( stable_session_id, persona_name, repo_root=None, cwd=None,
                          tmux_session=None ):
    """
    Render this seat's memento pointer + newest amendment as a block for the
    SessionStart hook's `additionalContext` — the channel the SESSION ITSELF
    reads at boot.

    WHY THIS EXISTS (2026-08-15, rows cc5477c9 / 9e0678f6). A self-re-spin
    typed `/clear` into a manager's own pane and nothing else. The seat came
    back with a fresh context and no idea a memento existed — the boot path had
    the session id, had the persona, had a derivable filename sitting at the
    repo root, and walked straight past it. Rick saw it twice in one day; one
    of those seats lost a held merge, a two-worker crew mid-lane, and a
    correction it owed a peer. The fix is not to type a reminder at the seat
    after the fact — it is for the boot path to carry the memento itself, so
    the state is present before the first turn rather than dependent on someone
    thinking to ask for it.

    Deliberately NOT gated on `source == "clear"`. The hook's own docstring
    says source is startup|resume|clear|compact, and a re-spin done as
    dismiss-then-spawn arrives as a NEW session — i.e. `startup`, not `clear`.
    Gating on the source would silently skip exactly the paths most likely to
    need it, so we attempt the lookup on every boot and emit only when one
    actually resolves. The cost of the miss case is one directory listing.

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
        - Never raises
    """
    repo_root = repo_root if repo_root is not None else _resolve_repo_root( cwd )

    path = _resolve_memento_path( stable_session_id, persona_name, repo_root )

    # The wake check's witness (row b0570b67). Stamped HERE because this is the
    # one place that knows WHICH file the boot path actually opened — the fact
    # that answers "did it wake?" and "did it read the right memento?" at once.
    # Written before the early return so a blank rehydrate is recorded too.
    _stamp_respin_boot_receipt(
        stable_session_id, persona_name, tmux_session,
        path, _written_at_of( _header_of( path ) ) if path else None, repo_root,
    )

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
        body    = _truncate_visibly( amendment, path )
        headline = "  🧠  YOU HAVE A MEMENTO — YOU WROTE IT BEFORE THIS CONTEXT RESET"
        section = (
            "  Your amendments — what you wrote down but had not yet acted on —\n"
            "  follow. The full record is one read away at the path above.\n"
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
        headline = "  ⚠️  MEMENTO FOUND BUT IT CARRIES NO STATE — TREAT AS A NEAR-BLANK RETURN"
        section = (
            "  The record exists and is yours, but it has NO amendment block —\n"
            "  nothing was written down since it was first created, so there is\n"
            "  nothing here about what you were doing.\n"
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


def emit_context_clear_marker( payload ):
    """
    Emit one JSONL context-clear marker when the payload reports source == "clear".

    payload["source"] ∈ startup|resume|clear|compact is the authoritative
    lifecycle signal the hook already receives but never read — exact where the
    downstream UUID-rotation heuristic under-reports. The DM-verbosity pilot reads
    this marker to correlate a session's context reset with a reset in its
    DM-length behaviour.

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
            from lupin_cli.claude_code.hooks.lib.session_bridge import set_manager_figure_implicit
            _mf_persona  = ( session_data.get( "voice_persona" ) or {} ).get( "name" )
            _mf_implicit = resolve_implicit_manager_figure( _mf_persona, os.environ )
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
