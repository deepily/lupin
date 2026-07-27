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

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir
from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, get_buffer_path
)

# Transport budget for out-of-process HTTP calls to `:7999` (row 204911ca).
# ~30s = 1.60x the observed maximum reload window of 18.76s — a multiplier with
# explicit headroom, NOT a coverage guarantee. `:7999` runs `uvicorn --reload`
# and the reloader parent holds the listening socket across a restart, so the
# kernel ACCEPTS a request nothing is there to answer and the caller hangs
# instead of getting a fast ConnectionRefused. The prior 2s failed every reload
# it landed in (measured min 6.59s, n=143).
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
# Accepted — a leaked persona name gets re-granted to a later worker and
# misdirects them, which outlasts a slow teardown. Not free.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30


def _find_all_listener_pids( session_id, session_dir=None ):
    """
    Find EVERY live listener serving this session — bridge PID + cmdline matches.

    Reap-all fix (F2, 2026-06-11): the bridge remembers only the LAST spawned
    listener's PID, so when the `--continue` double-fire produced duplicates,
    killing just the bridge PID orphaned the other listener permanently (the
    broadcast-miss root cause). This collects the union of:
        1. The bridge-recorded listener_pid (if any)
        2. Live processes whose cmdline matches `--session-id <hash>` for ANY
           hash associated with the session (session_id, stable_session_id,
           every session_ids[] entry — the listener is started with the STABLE
           hash while this hook receives the transient ID)
    See: src/rnd/v0.1.8/2026.06.10-broadcast-miss-duplicate-listener-root-cause.md §4

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns a sorted list of unique int PIDs (possibly empty)
        - Falls back to a cmdline scan on session_id[:8] when no bridge matches
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID (full or truncated)
        session_dir: Optional override for session directory (for testing)

    Returns:
        list[int]: sorted unique listener PIDs, [] if none
    """
    from lupin_cli.claude_code.hooks.lib.listener_processes import find_live_listener_pids

    if session_dir is None:
        session_dir = str( sessions_dir() )   # row 8ccc20ab: the one seam

    pids   = set()
    hashes = set()

    if os.path.isdir( session_dir ):
        for entry in os.listdir( session_dir ):
            if entry.startswith( "cc-" ) and entry.endswith( ".json" ):
                fpath = os.path.join( session_dir, entry )
                try:
                    with open( fpath ) as f:
                        data = json.load( f )
                except ( json.JSONDecodeError, OSError ):
                    continue
                if data.get( "session_id" ) != session_id:
                    continue
                listener_pid = data.get( "listener_pid" )
                if isinstance( listener_pid, int ):
                    pids.add( listener_pid )
                for sid in [ data.get( "session_id" ), data.get( "stable_session_id" ), *( data.get( "session_ids" ) or [ ] ) ]:
                    if isinstance( sid, str ) and sid:
                        hashes.add( sid[ :8 ] )

    # No bridge match → still sweep by the hook's own session hash so a
    # bridge-less orphan is reapable.
    if not hashes:
        hashes.add( session_id[ :8 ] )

    for session_hash in hashes:
        pids.update( find_live_listener_pids( session_hash ) )

    return sorted( pids )


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
        - _SERVER_TRANSPORT_TIMEOUT_SECONDS on each HTTP call — sized to
          outlast a `:7999` reload window rather than fail inside one
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
        with urllib.request.urlopen( login_req, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS ) as resp:
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
        with urllib.request.urlopen( release_req, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS ):
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
    reason     = payload.get( "reason", "" )

    # ── Phase 1.5: Release voice persona (best-effort) ────────────────────
    # Returns the allocated voice slot to the pool so other sessions can
    # claim it. Fail-soft: if the server is unreachable, the dead-PID
    # filter on subsequent /allocate calls reclaims the slot anyway.
    #
    # Only release on actual session termination — NOT on /clear or
    # /compact. SessionEnd fires for those intra-session lifecycle events
    # too, and releasing on them would null the bridge's voice_persona
    # before the post-/clear SessionStart hook can carry it forward,
    # giving the user a randomly-different voice mid-session.
    # See: src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md §0
    # See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md §4.4
    if session_id and reason not in ( "clear", "compact" ):
        try:
            _release_voice_persona( session_id )
        except Exception as e:
            print( f"[session_end] WARNING: voice persona release wrapper failed ({type( e ).__name__}: {e})",
                   file=sys.stderr )

    # ── Phase 1.6: Kill any pending idle-detection waiter ─────────────────
    # The waiter is a detached subprocess that may be sleeping for many
    # minutes; without explicit cleanup it would orphan-fire its prompt
    # against a session that no longer exists. The waiter's own dead-PPID
    # check would catch it eventually, but explicit kill at SessionEnd is
    # cleaner. See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
    if session_id:
        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import kill_idle_waiter
            kill_idle_waiter( session_id )
        except Exception as e:
            print( f"[session_end] WARNING: idle waiter kill failed ({type( e ).__name__}: {e})",
                   file=sys.stderr )

    # ── Phase 2: Stop CC Notification Listener(s) ─────────────────────────
    # Reap-all (F2): kill every listener serving this session's hashes, not
    # just the single bridge-recorded PID — duplicates from the SessionStart
    # double-fire would otherwise outlive the session as orphans.
    if session_id:
        for listener_pid in _find_all_listener_pids( session_id ):
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
