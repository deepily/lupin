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
import urllib.request
import urllib.error

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


def _release_voice_persona( session_id ):
    """
    Best-effort POST /api/cosa-voice/voice-persona/{stable_session_id}/release.

    Uses the stable_session_id from the bridge file (not the transient
    session_id passed to the hook) so the release matches what was
    originally allocated. Resolves credentials via hook_credentials and
    obtains a JWT for the auth-gated endpoint.

    Fail-soft: any failure (server unreachable, auth issue, missing
    credentials, missing bridge) logs to stderr and continues. The
    background dead-PID filter on subsequent /allocate calls will reclaim
    the slot anyway.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns True on a successful release HTTP 200
        - Returns False on any failure (logged to stderr)
        - Never raises exceptions
        - 2-second timeouts on each HTTP call
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import (
            find_session_path_by_id, get_voice_persona
        )
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        from cosa.agents.utils.sender_id import detect_project

        path = find_session_path_by_id( session_id )
        if not path:
            return False

        with open( path ) as f:
            data = json.load( f )
        sid = data.get( "stable_session_id" ) or data.get( "session_id" )
        if not sid:
            return False

        # Skip the HTTP roundtrip if there's no persona to release
        if get_voice_persona( sid ) is None:
            return False

        try:
            project = detect_project()
        except Exception:
            project = "lupin"

        email, password = get_hook_credentials( project )
        server_url      = os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )

        # Step 1: login
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
            return False

        # Step 2: release
        release_req = urllib.request.Request(
            f"{server_url}/api/cosa-voice/voice-persona/{sid}/release",
            data    = b"",
            method  = "POST",
            headers = {
                "Content-Type"  : "application/json",
                "Authorization" : f"Bearer {access_token}"
            }
        )
        with urllib.request.urlopen( release_req, timeout=2 ):
            pass
        return True

    except ( urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
             KeyError, FileNotFoundError, OSError, ValueError ) as e:
        print( f"[session_end] WARNING: voice persona release failed ({type( e ).__name__}: {e})",
               file=sys.stderr )
        return False


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

    # ── Phase 1.5: Release voice persona (best-effort) ────────────────────
    # Returns the allocated voice slot to the pool so other sessions can
    # claim it. Fail-soft: if the server is unreachable, the dead-PID
    # filter on subsequent /allocate calls reclaims the slot anyway.
    # See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md §4.4
    if session_id:
        try:
            _release_voice_persona( session_id )
        except Exception as e:
            print( f"[session_end] WARNING: voice persona release wrapper failed ({type( e ).__name__}: {e})",
                   file=sys.stderr )

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
