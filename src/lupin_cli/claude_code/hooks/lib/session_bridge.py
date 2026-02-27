#!/usr/bin/env python3
"""
Session bridge for Claude Code session_id resolution.

Provides three-tier resolution for obtaining the Claude Code session_id
from hook scripts and MCP server processes:

    1. $CLAUDE_SESSION_ID env var (future-proof: when Anthropic implements #17188)
    2. Session file written by SessionStart hook (~/.claude/sessions/cc-{ppid}.json)
    3. Fallback to self-generated UUID (backward compatible)

Adapted from research at:
    src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/
    creating-unique-session-id/session_bridge.py

Usage from hook scripts:
    from lupin_cli.claude_code.hooks.lib.session_bridge import (
        get_claude_session_id, wait_for_session_id, get_session_metadata
    )

    # Non-blocking (returns fallback immediately if not yet available)
    session_id = get_claude_session_id()

    # Blocking with timeout (waits for SessionStart hook to fire)
    session_id = wait_for_session_id( timeout=10.0 )
"""
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional


SESSION_DIR = Path.home() / ".claude" / "sessions"

# Cache to avoid repeated file reads
_cached_session_id: Optional[str] = None
_fallback_session_id: str = uuid.uuid4().hex[:8]


def _find_session_file() -> Optional[Path]:
    """
    Find the session file for the current process's parent (Claude Code).

    Strategy: Walk up the process tree to find a cc-{pid}.json file.
    Hook scripts are spawned by Claude Code, so PPID points to CC.
    MCP servers may have an intermediate wrapper, so grandparent is checked too.

    Requires:
        - SESSION_DIR may or may not exist

    Ensures:
        - Returns Path to session file if found
        - Returns None if no matching file exists
        - Checks: own PPID → grandparent PID → most recent file (fallback)

    Returns:
        Path or None: Path to session file
    """
    if not SESSION_DIR.exists():
        return None

    # Try own PPID first (hook script → Claude Code)
    ppid = os.getppid()
    direct = SESSION_DIR / f"cc-{ppid}.json"
    if direct.exists():
        return direct

    # Try grandparent (hook script → wrapper → Claude Code)
    try:
        with open( f"/proc/{ppid}/stat" ) as f:
            fields = f.read().split()
            gppid = int( fields[3] )  # 4th field = parent PID
        grandparent = SESSION_DIR / f"cc-{gppid}.json"
        if grandparent.exists():
            return grandparent
    except ( FileNotFoundError, IndexError, ValueError, PermissionError ):
        pass

    # Fallback: find most recent session file (for single-instance case)
    session_files = sorted(
        SESSION_DIR.glob( "cc-*.json" ),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if session_files:
        return session_files[0]

    return None


def _read_session_file( path: Path ) -> Optional[str]:
    """
    Read session_id from a session file.

    Requires:
        - path is a valid Path to a JSON file

    Ensures:
        - Returns session_id string if file is valid JSON with session_id key
        - Returns None on any read/parse error

    Args:
        path: Path to session file

    Returns:
        str or None: Session ID from file
    """
    try:
        with open( path ) as f:
            data = json.load( f )
        return data.get( "session_id" )
    except ( json.JSONDecodeError, OSError ):
        return None


def get_claude_session_id() -> str:
    """
    Get the Claude Code session_id, non-blocking.

    Resolution order:
        1. Cached value (from previous successful lookup)
        2. CLAUDE_SESSION_ID env var (future Anthropic implementation)
        3. Session file from SessionStart hook
        4. Self-generated fallback UUID

    Ensures:
        - Always returns a string (never None)
        - Caches resolved value for subsequent calls

    Returns:
        str: Session ID (8-char hex fallback, or full ID from Claude Code)
    """
    global _cached_session_id

    if _cached_session_id:
        return _cached_session_id

    # Tier 1: Environment variable (future-proof)
    env_id = os.getenv( "CLAUDE_SESSION_ID" )
    if env_id:
        _cached_session_id = env_id
        return env_id

    # Tier 2: Session file from hook
    session_file = _find_session_file()
    if session_file:
        file_id = _read_session_file( session_file )
        if file_id:
            _cached_session_id = file_id
            return file_id

    # Tier 3: Fallback
    return _fallback_session_id


def wait_for_session_id( timeout: float = 10.0, poll_interval: float = 0.5 ) -> str:
    """
    Wait for the real Claude Code session_id to become available.

    Blocks until SessionStart hook writes the session file, or timeout.
    Useful for MCP server initialization where you want the real ID.

    Requires:
        - timeout is a positive float
        - poll_interval is a positive float less than timeout

    Ensures:
        - Returns real session ID if found within timeout
        - Returns fallback UUID if timeout expires
        - Caches resolved value

    Args:
        timeout: Max seconds to wait (default 10)
        poll_interval: Seconds between file checks (default 0.5)

    Returns:
        str: Real session ID if found within timeout, else fallback
    """
    global _cached_session_id

    # Already resolved?
    if _cached_session_id:
        return _cached_session_id

    env_id = os.getenv( "CLAUDE_SESSION_ID" )
    if env_id:
        _cached_session_id = env_id
        return env_id

    # Poll for session file
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session_file = _find_session_file()
        if session_file:
            file_id = _read_session_file( session_file )
            if file_id:
                _cached_session_id = file_id
                return file_id
        time.sleep( poll_interval )

    return _fallback_session_id


def get_session_metadata() -> dict:
    """
    Get full session metadata (session_id + transcript_path + cwd + source).

    Ensures:
        - Returns dict with at least session_id and source keys
        - source indicates resolution tier: "env_var", "session_file", or "fallback"

    Returns:
        dict: Session metadata with session_id, transcript_path, cwd, source
    """
    env_id = os.getenv( "CLAUDE_SESSION_ID" )
    if env_id:
        return {
            "session_id"      : env_id,
            "transcript_path" : os.getenv( "CLAUDE_TRANSCRIPT_PATH", "" ),
            "cwd"             : os.getcwd(),
            "source"          : "env_var"
        }

    session_file = _find_session_file()
    if session_file:
        try:
            with open( session_file ) as f:
                data = json.load( f )
            data["source"] = "session_file"
            return data
        except ( json.JSONDecodeError, OSError ):
            pass

    return {
        "session_id" : _fallback_session_id,
        "source"     : "fallback"
    }


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print( f"Session ID (non-blocking): {get_claude_session_id()}" )
    print( f"Metadata: {json.dumps( get_session_metadata(), indent=2 )}" )
    print( f"Session dir: {SESSION_DIR}" )
    print( f"Fallback ID: {_fallback_session_id}" )
