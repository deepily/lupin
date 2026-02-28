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
        get_claude_session_id, wait_for_session_id, get_session_metadata,
        build_sender_id_for_cc
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
        - Checks: own PPID → grandparent PID → CWD-matching file (fallback)

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
            stat_line = f.read()
        # Safe parsing: comm field is in parens and may contain spaces/parens
        # Format: pid (comm) state ppid ...
        # Find the LAST ")" to skip past comm field safely
        comm_end = stat_line.rindex( ")" )
        fields_after_comm = stat_line[comm_end + 2:].split()
        # fields_after_comm[0] = state, fields_after_comm[1] = ppid
        gppid = int( fields_after_comm[1] )
        grandparent = SESSION_DIR / f"cc-{gppid}.json"
        if grandparent.exists():
            return grandparent
    except ( FileNotFoundError, IndexError, ValueError, PermissionError, OSError ):
        pass

    # Fallback: find most recent session file scoped to same CWD (project)
    my_cwd = os.getcwd()
    for path in sorted( SESSION_DIR.glob( "cc-*.json" ),
                        key=lambda p: p.stat().st_mtime, reverse=True ):
        try:
            with open( path ) as f:
                data = json.load( f )
            if data.get( "cwd", "" ) == my_cwd:
                return path
        except ( json.JSONDecodeError, OSError ):
            continue

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


def build_sender_id_for_cc( session_id: Optional[str] = None ) -> Optional[str]:
    """
    Build a Claude Code sender_id for notification routing.

    Uses the CC session_id (truncated to first 8 hex chars) as the suffix,
    producing sender_ids like: claude.code@lupin.deepily.ai#a1b2c3d4

    This ensures hooks and MCP server produce identical sender_ids when
    they share the same CC session.

    Requires:
        - cosa.agents.utils.sender_id must be importable

    Ensures:
        - Returns sender_id string if session_id can be resolved
        - Returns None on any failure (import error, resolution failure)
        - When session_id arg is provided, uses it directly (for SessionStart hook)
        - When session_id arg is None, resolves via get_claude_session_id()

    Args:
        session_id: Optional explicit CC session_id (full UUID from hook payload).
                    If None, resolves via 3-tier get_claude_session_id().

    Returns:
        str or None: Fully-qualified sender_id, or None on failure
    """
    try:
        from cosa.agents.utils.sender_id import build_sender_id

        if session_id is None:
            session_id = get_claude_session_id()

        # Truncate to first 8 chars — UUID hex guarantees [a-f0-9]
        suffix = session_id[:8] if session_id else None

        return build_sender_id( "claude.code", suffix=suffix )

    except Exception:
        return None


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
    print( f"Sender ID (auto-resolve): {build_sender_id_for_cc()}" )
    print( f"Sender ID (explicit):     {build_sender_id_for_cc( 'bbd0e94b-cdf0-4766-a16d-16fe116125ef' )}" )
    print( f"Metadata: {json.dumps( get_session_metadata(), indent=2 )}" )
    print( f"Session dir: {SESSION_DIR}" )
    print( f"Fallback ID: {_fallback_session_id}" )
