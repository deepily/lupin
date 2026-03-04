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
import signal
import subprocess
import sys
import time

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts
)
from lupin_cli.claude_code.hooks.lib.session_bridge import build_sender_id_for_cc


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


def _spawn_listener( session_id, session_data, session_file ):
    """
    Spawn the CC Notification Listener as a background subprocess.

    The listener connects via WebSocket and buffers user_initiated_message
    notifications targeted at this CC session.

    Requires:
        - session_id is a non-empty string
        - LUPIN_ROOT environment variable is set (for PYTHONPATH)

    Ensures:
        - Spawns listener subprocess in background (detached from hook lifecycle)
        - Records listener PID in session bridge file for SessionEnd cleanup
        - Always writes log file to ~/.claude/sessions/cc-listener-{hash}.log
        - Respects LUPIN_CC_HOOK_LISTENER_DEBUG/VERBOSE env vars
        - Returns listener PID on success, None on failure
        - Never raises exceptions (spawn failure is non-fatal)

    Args:
        session_id: Full CC session ID
        session_data: Session bridge data dict (updated in-place with listener_pid)
        session_file: Path to session bridge JSON file

    Returns:
        int or None: Listener subprocess PID, or None on failure
    """
    if not session_id:
        return None

    # Check if listener spawning is disabled
    if os.environ.get( "LUPIN_CC_HOOK_LISTENER_ENABLED", "true" ).strip().lower() == "false":
        return None

    short_id = session_id[:8]

    cmd = [
        sys.executable, "-m",
        "lupin_cli.claude_code.hooks.lib.cc_notification_listener",
        "--session-id", short_id,
    ]

    # Pass debug/verbose/log flags from env vars
    if os.environ.get( "LUPIN_CC_HOOK_LISTENER_DEBUG", "" ).strip().lower() == "true":
        cmd.append( "--debug" )

    if os.environ.get( "LUPIN_CC_HOOK_LISTENER_VERBOSE", "" ).strip().lower() == "true":
        cmd.append( "--verbose" )

    # Always write log files — enables tail-cc-listeners.sh aggregator
    log_dir  = os.path.expanduser( "~/.claude/sessions" )
    log_path = os.path.join( log_dir, f"cc-listener-{short_id}.log" )
    cmd.extend( [ "--log-file", log_path ] )

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

        # Spawn detached — listener outlives the hook subprocess
        proc = subprocess.Popen(
            cmd,
            stdout = subprocess.DEVNULL,
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
        if session_data is not None and session_file:
            session_data[ "listener_pid" ] = listener_pid
            try:
                with open( session_file, "w" ) as f:
                    json.dump( session_data, f, indent=2 )
            except OSError:
                pass  # Best-effort

        return listener_pid

    except Exception:
        return None  # Spawn failure is non-fatal


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
    is_context_clear = False

    if session_id:
        os.makedirs( session_dir, exist_ok=True )

        hook_ppid    = os.getppid()
        cc_pid       = _resolve_cc_pid( hook_ppid )
        session_file = os.path.join( session_dir, f"cc-{cc_pid}.json" )

        # ── Context clear detection ──────────────────────────────────
        # Same PID but different session ID → context clear happened
        if os.path.exists( session_file ):
            try:
                with open( session_file ) as f:
                    old_data = json.load( f )
                old_session_id = old_data.get( "session_id", "" )
                if old_session_id and old_session_id != session_id:
                    is_context_clear = True
                    _cleanup_old_listener( old_data, session_id )
            except ( json.JSONDecodeError, OSError ):
                pass  # Can't read old data, proceed normally

        session_data = {
            "session_id"      : session_id,
            "transcript_path" : transcript_path,
            "cwd"             : cwd,
            "ppid"            : cc_pid,
            "hook_ppid"       : hook_ppid
        }

        try:
            with open( session_file, "w" ) as f:
                json.dump( session_data, f, indent=2 )
        except OSError:
            pass  # Best-effort

    # ── Phase 3: Write to CLAUDE_ENV_FILE (for Bash commands) ─────────────
    if session_id:
        env_file = os.getenv( "CLAUDE_ENV_FILE" )
        if env_file:
            try:
                with open( env_file, "a" ) as f:
                    f.write( f"export CLAUDE_SESSION_ID='{session_id}'\n" )
                    f.write( f"export CLAUDE_TRANSCRIPT_PATH='{transcript_path}'\n" )
            except OSError:
                pass  # Best-effort

    # ── Phase 4: Purge stale session files (>24h old) ─────────────────────
    try:
        now = time.time()
        for entry in os.listdir( session_dir ) if os.path.isdir( session_dir ) else []:
            if entry.startswith( "cc-" ) and entry.endswith( ".json" ):
                fpath = os.path.join( session_dir, entry )
                if fpath != session_file and ( now - os.path.getmtime( fpath ) ) > 86400:
                    os.remove( fpath )
    except Exception:
        pass  # Best-effort cleanup

    # ── Phase 5: Send TTS notification (with explicit sender_id) ────────
    short_id = session_id[:8] if session_id else "unknown"
    # SessionStart hook has session_id from payload — build sender_id directly
    # (can't rely on session file yet; this hook is the one writing it)
    hook_sender_id = build_sender_id_for_cc( session_id=session_id ) if session_id else None
    if is_context_clear:
        send_tts( f"Hook fired: SessionStart (context clear) — new session {short_id}", sender_id=hook_sender_id )
    else:
        send_tts( f"Hook fired: SessionStart — session {short_id}", sender_id=hook_sender_id )

    # ── Phase 5.5: Spawn CC Notification Listener ──────────────────────
    listener_pid = _spawn_listener( session_id, session_data if session_id else None, session_file )

    # ── Phase 6: Log full payload ─────────────────────────────────────────
    log_payload( "session_start", payload )

    # ── Phase 7: Emit response ────────────────────────────────────────────
    if session_id:
        emit_json( {
            "additionalContext": f"Session ID: {session_id}"
        } )
    else:
        emit_json( {} )


if __name__ == "__main__":
    main()
