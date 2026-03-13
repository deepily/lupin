#!/usr/bin/env python3
"""
SessionEnd hook: gracefully stops the CC Notification Listener.

Reads the listener PID from the session bridge file and sends SIGTERM
for a clean shutdown. Cleans up buffer file if empty.

Actions:
    1. Read session bridge file to get listener PID
    2. Send SIGTERM to listener subprocess
    3. Wait briefly for graceful exit
    4. Clean up empty buffer files
    5. Log payload

Install in ~/.claude/settings.json:
    "hooks": {
        "SessionEnd": [{
            "hooks": [{
                "type": "command",
                "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/test_session_end.py\""
            }]
        }]
    }
"""

import json
import os
import signal
import sys
import time

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, get_buffer_path
)


def _find_listener_pid( session_id, session_dir=None ):
    """
    Find the listener PID from the session bridge file.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns listener PID as int if found in session bridge file
        - Returns None if no bridge file or no listener_pid key

    Args:
        session_id: Claude Code session ID (full or truncated)
        session_dir: Optional override for session directory (for testing)

    Returns:
        int or None: Listener PID if found
    """
    if session_dir is None:
        session_dir = os.path.expanduser( "~/.claude/sessions" )

    if not os.path.isdir( session_dir ):
        return None

    for entry in os.listdir( session_dir ):
        if entry.startswith( "cc-" ) and entry.endswith( ".json" ):
            fpath = os.path.join( session_dir, entry )
            try:
                with open( fpath ) as f:
                    data = json.load( f )
                if data.get( "session_id" ) == session_id:
                    return data.get( "listener_pid" )
            except ( json.JSONDecodeError, OSError ):
                continue

    return None


def _stop_listener( pid ):
    """
    Send SIGTERM to listener subprocess and wait for exit.

    Requires:
        - pid is a valid process ID

    Ensures:
        - Sends SIGTERM for graceful shutdown
        - Waits up to 5 seconds for process to exit
        - Falls back to SIGKILL if still running
        - Never raises exceptions

    Args:
        pid: Listener process ID
    """
    try:
        os.kill( pid, signal.SIGTERM )
    except ProcessLookupError:
        return  # Already dead
    except PermissionError:
        return  # Can't signal

    # Wait briefly for graceful exit
    for _ in range( 10 ):
        try:
            os.kill( pid, 0 )  # Check if still alive
            time.sleep( 0.5 )
        except ProcessLookupError:
            return  # Clean exit
        except PermissionError:
            return

    # Still running — force kill
    try:
        os.kill( pid, signal.SIGKILL )
    except ( ProcessLookupError, PermissionError ):
        pass


def main():

    # ── Phase 1: Read hook input ──────────────────────────────────────────
    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    session_id = payload.get( "session_id", "" )

    # ── Phase 2: Stop CC Notification Listener ────────────────────────────
    if session_id:
        listener_pid = _find_listener_pid( session_id )
        if listener_pid:
            _stop_listener( listener_pid )

    # ── Phase 3: Clean up empty buffer files ──────────────────────────────
    if session_id:
        buffer_path = get_buffer_path( session_id )
        try:
            if buffer_path.exists() and buffer_path.stat().st_size == 0:
                buffer_path.unlink()
        except OSError:
            pass  # Best-effort

    # ── Phase 4: Log payload ──────────────────────────────────────────────
    log_payload( "session_end", payload )

    # ── Phase 5: Emit response ────────────────────────────────────────────
    emit_json( {} )


if __name__ == "__main__":
    main()
