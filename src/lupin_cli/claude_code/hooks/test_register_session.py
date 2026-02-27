#!/usr/bin/env python3
"""
SessionStart hook: registers Claude Code session with the session bridge.

Phase 0 test hook — validates SessionStart payload, writes session bridge file,
and sends hello-world TTS notification.

Actions:
    1. Extract session_id, transcript_path, cwd from stdin
    2. Write ~/.claude/sessions/cc-{PPID}.json (for MCP server polling)
    3. Write CLAUDE_SESSION_ID to CLAUDE_ENV_FILE (for Bash access)
    4. Send TTS notification: "Hook fired: SessionStart"
    5. Emit additionalContext with session ID
    6. Log full payload

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
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts
)


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
    if session_id:
        session_dir = os.path.expanduser( "~/.claude/sessions" )
        os.makedirs( session_dir, exist_ok=True )

        ppid = os.getppid()
        session_file = os.path.join( session_dir, f"cc-{ppid}.json" )

        session_data = {
            "session_id"      : session_id,
            "transcript_path" : transcript_path,
            "cwd"             : cwd,
            "ppid"            : ppid
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

    # ── Phase 4: Send TTS notification ────────────────────────────────────
    short_id = session_id[:8] if session_id else "unknown"
    send_tts( f"Hook fired: SessionStart — session {short_id}" )

    # ── Phase 5: Log full payload ─────────────────────────────────────────
    log_payload( "session_start", payload )

    # ── Phase 6: Emit response ────────────────────────────────────────────
    if session_id:
        emit_json( {
            "additionalContext": f"Session ID: {session_id}"
        } )
    else:
        emit_json( {} )


if __name__ == "__main__":
    main()
