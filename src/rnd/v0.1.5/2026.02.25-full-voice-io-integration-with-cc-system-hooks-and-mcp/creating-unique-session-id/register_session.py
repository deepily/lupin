#!/usr/bin/env python3
"""
SessionStart hook: registers Claude Code session_id with CoSA Voice MCP.

Two-phase handshake:
  1. Claude Code spawns MCP server (gets its own ephemeral SESSION_ID)
  2. SessionStart hook fires → extracts real session_id → pushes to MCP

Install in ~/.claude/settings.json:
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "python3 ~/.claude/hooks/register_session.py"
      }]
    }]
  }
}

Also writes CLAUDE_SESSION_ID to CLAUDE_ENV_FILE so Bash commands
can reference it as $CLAUDE_SESSION_ID.
"""
import json
import os
import sys
import urllib.request

def main():
    # ── Phase 1: Extract session_id from hook stdin ──────────────────────
    try:
        hook_input = json.load( sys.stdin )
    except ( json.JSONDecodeError, EOFError ):
        sys.exit( 0 )  # Non-blocking: don't fail the session

    session_id      = hook_input.get( "session_id", "" )
    transcript_path = hook_input.get( "transcript_path", "" )
    cwd             = hook_input.get( "cwd", "" )

    if not session_id:
        sys.exit( 0 )

    # ── Phase 2: Write to CLAUDE_ENV_FILE (for Bash commands) ────────────
    env_file = os.getenv( "CLAUDE_ENV_FILE" )
    if env_file:
        with open( env_file, "a" ) as f:
            f.write( f"export CLAUDE_SESSION_ID='{session_id}'\n" )
            f.write( f"export CLAUDE_TRANSCRIPT_PATH='{transcript_path}'\n" )

    # ── Phase 3: Write to well-known file (for MCP server polling) ───────
    #
    # Each project gets its own session file keyed by CWD hash.
    # MCP server can poll this or read on-demand via get_session_info().
    #
    session_dir = os.path.expanduser( "~/.claude/sessions" )
    os.makedirs( session_dir, exist_ok=True )

    # Use PID of parent (Claude Code process) for multi-instance isolation
    ppid = os.getppid()
    session_file = os.path.join( session_dir, f"cc-{ppid}.json" )

    session_data = {
        "session_id"      : session_id,
        "transcript_path" : transcript_path,
        "cwd"             : cwd,
        "ppid"            : ppid
    }

    with open( session_file, "w" ) as f:
        json.dump( session_data, f )

    # ── Phase 4: Push to MCP server via HTTP (if Lupin is running) ───────
    #
    # The MCP server exposes no HTTP endpoint itself (it's stdio-based),
    # but we can notify the Lupin app server which routes to the right
    # MCP instance. Alternatively, write to a shared file the MCP reads.
    #
    server_url = os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
    try:
        payload = json.dumps( session_data ).encode()
        req = urllib.request.Request(
            f"{server_url}/api/register-session",
            data    = payload,
            headers = { "Content-Type": "application/json" },
            method  = "POST"
        )
        urllib.request.urlopen( req, timeout=2 )
    except Exception:
        pass  # Best-effort; MCP can also read the session file

    # ── Phase 5: Inject context so Claude knows its session_id ───────────
    output = {
        "hookSpecificOutput": {
            "hookEventName"   : "SessionStart",
            "additionalContext": f"Session ID: {session_id}"
        }
    }
    print( json.dumps( output ) )

if __name__ == "__main__":
    main()
