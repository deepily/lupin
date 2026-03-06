#!/usr/bin/env python3
"""
Session bridge for Claude Code session_id resolution.

Provides three-tier resolution for obtaining the Claude Code session_id
from hook scripts and MCP server processes:

    1. $CLAUDE_SESSION_ID env var (future-proof: when Anthropic implements #17188)
    2. Session file written by SessionStart hook (~/.claude/sessions/cc-{ppid}.json)
    3. Fallback to self-generated UUID (backward compatible)

CWD fallback safety:
    - PPID/grandparent matches are the definitive session file → cached
    - CWD fallback is a best-guess from another session → NOT cached
    - Dead PIDs (from exited CC processes) are skipped in CWD fallback

Adapted from research at:
    src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/
    creating-unique-session-id/session_bridge.py

Usage from hook scripts:
    from lupin_cli.claude_code.hooks.lib.session_bridge import (
        get_claude_session_id, wait_for_session_id, get_session_metadata,
        build_sender_id_for_cc, clear_cached_session_id
    )

    # Non-blocking (returns fallback immediately if not yet available)
    session_id = get_claude_session_id()

    # Blocking with timeout (waits for SessionStart hook to fire)
    session_id = wait_for_session_id( timeout=10.0 )

    # Force re-resolution (e.g., after context clear)
    clear_cached_session_id()
"""
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple


SESSION_DIR = Path.home() / ".claude" / "sessions"

# Cache to avoid repeated file reads
_cached_session_id: Optional[str] = None
_fallback_session_id: str = uuid.uuid4().hex[:8]

# Resolution source constants
SOURCE_PPID         = "ppid"
SOURCE_GRANDPARENT  = "grandparent"
SOURCE_CWD_FALLBACK = "cwd_fallback"


def _is_pid_alive( pid: int ) -> bool:
    """
    Check if a process with the given PID is alive.

    Requires:
        - pid is a positive integer

    Ensures:
        - Returns True if the process exists and is signalable
        - Returns False if the process is dead or inaccessible

    Args:
        pid: Process ID to check

    Returns:
        bool: True if process is alive
    """
    try:
        os.kill( pid, 0 )
        return True
    except ( ProcessLookupError, PermissionError, OSError ):
        return False


def _extract_pid_from_filename( filename: str ) -> Optional[int]:
    """
    Extract PID from a session bridge filename like 'cc-12345.json'.

    Requires:
        - filename is a string

    Ensures:
        - Returns int PID if filename matches cc-{digits}.json pattern
        - Returns None if filename doesn't match

    Args:
        filename: Session file name (not full path)

    Returns:
        int or None: Extracted PID
    """
    match = re.match( r"^cc-(\d+)\.json$", filename )
    if match:
        return int( match.group( 1 ) )
    return None


def clear_cached_session_id():
    """
    Reset the cached session ID, forcing re-resolution on next call.

    Use this when the session bridge file has been overwritten (e.g.,
    after a context clear) and the MCP server needs to pick up the
    new session ID.

    Ensures:
        - _cached_session_id is set to None
        - Next call to get_claude_session_id() will re-read from file
    """
    global _cached_session_id
    _cached_session_id = None


def _find_session_file() -> Optional[ Tuple[ Path, str ] ]:
    """
    Find the session file for the current process's parent (Claude Code).

    Strategy: Walk up the process tree to find a cc-{pid}.json file.
    Hook scripts are spawned by Claude Code, so PPID points to CC.
    MCP servers may have an intermediate wrapper, so grandparent is checked too.

    Returns a (path, source) tuple where source indicates how the file was
    found. This distinction is critical for caching safety:
        - "ppid" / "grandparent": definitive match → safe to cache
        - "cwd_fallback": best-guess from another session → NOT cached

    Requires:
        - SESSION_DIR may or may not exist

    Ensures:
        - Returns ( Path, source_str ) if a session file is found
        - Returns None if no matching file exists
        - Checks: own PPID → grandparent PID → CWD-matching file (fallback)
        - CWD fallback skips files from dead PIDs

    Returns:
        Tuple[ Path, str ] or None: ( path, source ) or None
    """
    if not SESSION_DIR.exists():
        return None

    # Try own PPID first (hook script → Claude Code)
    ppid = os.getppid()
    direct = SESSION_DIR / f"cc-{ppid}.json"
    if direct.exists():
        return ( direct, SOURCE_PPID )

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
            return ( grandparent, SOURCE_GRANDPARENT )
    except ( FileNotFoundError, IndexError, ValueError, PermissionError, OSError ):
        pass

    # Fallback: find most recent session file scoped to same CWD (project)
    # Skip files whose PID is dead (stale bridge files from exited CC processes)
    my_cwd = os.getcwd()
    for path in sorted( SESSION_DIR.glob( "cc-*.json" ),
                        key=lambda p: p.stat().st_mtime, reverse=True ):
        try:
            # PID liveness check: skip bridge files from dead processes
            file_pid = _extract_pid_from_filename( path.name )
            if file_pid is not None and not _is_pid_alive( file_pid ):
                continue

            with open( path ) as f:
                data = json.load( f )
            if data.get( "cwd", "" ) == my_cwd:
                return ( path, SOURCE_CWD_FALLBACK )
        except ( json.JSONDecodeError, OSError ):
            continue

    return None


def _read_session_file( path: Path ) -> Optional[str]:
    """
    Read the stable session_id from a session file.

    Prefers stable_session_id (survives context clears) over session_id.
    Falls back to session_id for backward compatibility with bridge files
    written before stable_session_id was introduced.

    Requires:
        - path is a valid Path to a JSON file

    Ensures:
        - Returns stable_session_id if present, else session_id
        - Returns None on any read/parse error

    Args:
        path: Path to session file

    Returns:
        str or None: Stable session ID from file
    """
    try:
        with open( path ) as f:
            data = json.load( f )
        # Prefer stable ID (survives context clears)
        return data.get( "stable_session_id", data.get( "session_id" ) )
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

    Caching safety:
        - Tier 1 (env var) and Tier 2 (PPID/grandparent match) → cached
        - CWD fallback → NOT cached (could be from another session)

    Ensures:
        - Always returns a string (never None)
        - Caches resolved value for PPID/grandparent matches only

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
    result = _find_session_file()
    if result:
        session_file, source = result
        file_id = _read_session_file( session_file )
        if file_id:
            # Only cache definitive matches — CWD fallback is a guess
            if source != SOURCE_CWD_FALLBACK:
                _cached_session_id = file_id
            return file_id

    # Tier 3: Fallback
    return _fallback_session_id


def wait_for_session_id( timeout: float = 10.0, poll_interval: float = 0.5 ) -> str:
    """
    Wait for the real Claude Code session_id to become available.

    Blocks until SessionStart hook writes the session file, or timeout.
    Useful for MCP server initialization where you want the real ID.

    Always bypasses the cache to ensure fresh resolution — this function
    is specifically for waiting on the real session file to appear.

    Requires:
        - timeout is a positive float
        - poll_interval is a positive float less than timeout

    Ensures:
        - Returns real session ID if found within timeout
        - Returns fallback UUID if timeout expires
        - Caches resolved value (PPID/grandparent matches only)

    Args:
        timeout: Max seconds to wait (default 10)
        poll_interval: Seconds between file checks (default 0.5)

    Returns:
        str: Real session ID if found within timeout, else fallback
    """
    global _cached_session_id

    # Always check env var first (no polling needed)
    env_id = os.getenv( "CLAUDE_SESSION_ID" )
    if env_id:
        _cached_session_id = env_id
        return env_id

    # Poll for session file — bypass cache for fresh resolution
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _find_session_file()
        if result:
            session_file, source = result
            file_id = _read_session_file( session_file )
            if file_id:
                if source != SOURCE_CWD_FALLBACK:
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
        - resolution_source indicates how the file was found (ppid, grandparent, cwd_fallback)

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

    result = _find_session_file()
    if result:
        session_file, resolution_source = result
        try:
            with open( session_file ) as f:
                data = json.load( f )
            data["source"]            = "session_file"
            data["resolution_source"] = resolution_source
            # Ensure stable_session_id is always present (backward compat)
            if "stable_session_id" not in data:
                data["stable_session_id"] = data.get( "session_id" )
            return data
        except ( json.JSONDecodeError, OSError ):
            pass

    return {
        "session_id"        : _fallback_session_id,
        "stable_session_id" : _fallback_session_id,
        "source"            : "fallback"
    }


def find_session_by_id( session_id ):
    """
    Scan ~/.claude/sessions/cc-*.json for a session_id match.

    Supports both full UUID and 8-char prefix matching. Skips files
    from dead PIDs to avoid returning stale sessions.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns full session data dict if a match is found
        - Returns None if no match or session_id is empty
        - Skips bridge files whose PID is dead
        - Never raises exceptions

    Args:
        session_id: Full session UUID or 8-char prefix to match

    Returns:
        dict or None: Session data dict, or None
    """
    if not session_id or not SESSION_DIR.exists():
        return None

    for path in SESSION_DIR.glob( "cc-*.json" ):
        # Skip non-bridge files (buffers, listeners, etc.)
        if "buffer" in path.name or "listener" in path.name:
            continue

        # PID liveness check
        file_pid = _extract_pid_from_filename( path.name )
        if file_pid is not None and not _is_pid_alive( file_pid ):
            continue

        try:
            with open( path ) as f:
                data = json.load( f )

            file_sid = data.get( "session_id", "" )
            # Full match or 8-char prefix match
            if file_sid == session_id or file_sid[:8] == session_id[:8]:
                return data
        except ( json.JSONDecodeError, OSError ):
            continue

    return None


def find_session_by_tmux( tmux_session ):
    """
    Scan ~/.claude/sessions/cc-*.json for a tmux_session match.

    Finds the session bridge file whose tmux_session field matches
    the given tmux session name. Skips dead PIDs.

    Requires:
        - tmux_session is a non-empty string

    Ensures:
        - Returns full session data dict if a match is found
        - Returns None if no match or tmux_session is empty
        - Skips bridge files whose PID is dead
        - Never raises exceptions

    Args:
        tmux_session: tmux session name to match

    Returns:
        dict or None: Session data dict, or None
    """
    if not tmux_session or not SESSION_DIR.exists():
        return None

    for path in SESSION_DIR.glob( "cc-*.json" ):
        if "buffer" in path.name or "listener" in path.name:
            continue

        file_pid = _extract_pid_from_filename( path.name )
        if file_pid is not None and not _is_pid_alive( file_pid ):
            continue

        try:
            with open( path ) as f:
                data = json.load( f )

            if data.get( "tmux_session" ) == tmux_session:
                return data
        except ( json.JSONDecodeError, OSError ):
            continue

    return None


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print( f"Session ID (non-blocking): {get_claude_session_id()}" )
    print( f"Sender ID (auto-resolve): {build_sender_id_for_cc()}" )
    print( f"Sender ID (explicit):     {build_sender_id_for_cc( 'bbd0e94b-cdf0-4766-a16d-16fe116125ef' )}" )
    print( f"Metadata: {json.dumps( get_session_metadata(), indent=2 )}" )
    print( f"Session dir: {SESSION_DIR}" )
    print( f"Fallback ID: {_fallback_session_id}" )
