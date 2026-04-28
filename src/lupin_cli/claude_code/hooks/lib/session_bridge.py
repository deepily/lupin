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
        build_sender_id_for_cc, clear_cached_session_id,
        resolve_stable_session_id
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


def _can_trust_host_pids() -> bool:
    """
    Whether the current process shares its PID namespace with the bridge writers.

    Bridge files are written by Claude Code hooks running on the host, named
    cc-{HOST_PID}.json. When the reader runs inside a Docker container, those
    host PIDs are invisible — every kill(host_pid, 0) raises ProcessLookupError,
    so a naive _is_pid_alive() filter discards every bridge file as "dead."

    The Lupin FastAPI server reads bridge files for the conversation-mode
    endpoint while running inside the lupin-rest-dev container; this helper lets
    that path skip the liveness filter while preserving it for host-side callers
    (hook scripts, MCP server) that genuinely need staleness pruning.

    Ensures:
        - Returns False when running inside a Docker container (/.dockerenv exists)
        - Returns True otherwise — host-side callers can trust kill(pid, 0)

    Returns:
        bool: True if PID-liveness checks against bridge filenames are meaningful
    """
    return not Path( "/.dockerenv" ).exists()


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


def resolve_stable_session_id( transient_id: str ) -> str:
    """
    Resolve a transient CC session_id to its stable counterpart.

    Looks up the session bridge file by PPID/grandparent, reads stable_session_id.
    If the bridge file exists and contains a stable_session_id, returns that.
    Otherwise returns the transient_id unchanged (safe fallback).

    Requires:
        - transient_id is a non-empty string

    Ensures:
        - Returns stable_session_id if bridge file found and contains it
        - Returns transient_id unchanged if no bridge file or no stable field

    Args:
        transient_id: The session_id from Claude Code payload

    Returns:
        str: Stable session ID, or transient_id as fallback
    """
    if not transient_id:
        return transient_id

    result = _find_session_file()
    if result:
        path, _source = result
        try:
            with open( path ) as f:
                data = json.load( f )
            stable = data.get( "stable_session_id" )
            if stable:
                return stable
        except ( json.JSONDecodeError, OSError ):
            pass

    return transient_id


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


def _resolve_project_from_bridge_cwd() -> Optional[str]:
    """
    Resolve project name from the bridge file's SessionStart cwd field.

    The bridge file is written once at SessionStart and its `cwd` snapshot
    represents where the `claude` CLI was launched. That value is stable
    for the lifetime of the CC session. By contrast, `os.getcwd()` inside
    a hook process can drift across hook invocations because Claude Code
    preserves the Bash subshell's cwd across tool calls — running
    `cd src/cosa && git status` once mutates the cwd Claude Code passes
    to subsequent hook spawns, and `detect_project()` (which uses
    `os.getcwd()`) starts returning "cosa" instead of "lupin." That
    pivot duplicates the user's notification UI panes (one per
    sender_id) for what should be a single session.

    Walks up from the bridge's `cwd` looking for a `.git` ancestor.
    Returns the lowercase basename of that ancestor with the
    `_PROJECT_ALIASES` normalization applied (matches `detect_project()`
    semantics exactly, just sourced from the bridge instead of live cwd).

    Ensures:
        - Returns the project name from the bridge file's SessionStart cwd
        - Returns None if no bridge file resolves, the bridge has no cwd
          field, the cwd path doesn't exist, or no .git ancestor is found
        - Never raises exceptions
    """
    result = _find_session_file()
    if not result:
        return None
    path, _source = result
    try:
        with open( path ) as f:
            data = json.load( f )
        bridge_cwd = data.get( "cwd" )
        if not bridge_cwd:
            return None

        from cosa.agents.utils.sender_id import _PROJECT_ALIASES

        candidate = Path( bridge_cwd ).resolve()
        for parent in [ candidate, *candidate.parents ]:
            if ( parent / ".git" ).exists():
                name = parent.name.lower()
                return _PROJECT_ALIASES.get( name, name )
        # No .git ancestor — fall back to the basename so callers always
        # get a sensible default rather than None.
        basename = candidate.name.lower()
        return _PROJECT_ALIASES.get( basename, basename )
    except ( json.JSONDecodeError, OSError, ValueError, ImportError ):
        return None


def build_sender_id_for_cc( session_id: Optional[str] = None ) -> Optional[str]:
    """
    Build a Claude Code sender_id for notification routing.

    Uses the CC session_id (truncated to first 8 hex chars) as the suffix,
    producing sender_ids like: claude.code@lupin.deepily.ai#a1b2c3d4

    The project segment is resolved from the bridge file's SessionStart cwd
    snapshot (via `_resolve_project_from_bridge_cwd`), NOT live `os.getcwd()`.
    The bridge is stable for the session lifetime; live cwd drifts across
    hook invocations once the user runs `cd` inside a Bash tool call. Without
    this stabilization, the same CC session produces sender_ids alternating
    between e.g. `claude.code@lupin.deepily.ai#abc12345` and
    `claude.code@cosa.deepily.ai#abc12345` depending on where the bash
    subshell happens to be standing — which the notifications UI renders
    as duplicate sender cards for what is logically one session.

    Falls back to live-cwd detection (the legacy behavior) only if the
    bridge can't be resolved.

    Requires:
        - cosa.agents.utils.sender_id must be importable

    Ensures:
        - Returns sender_id string if session_id can be resolved
        - Returns None on any failure (import error, resolution failure)
        - When session_id arg is provided, uses it directly (for SessionStart hook)
        - When session_id arg is None, resolves via get_claude_session_id()
        - Project segment is bridge-cwd-anchored (stable across hook spawns)

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

        # Stable: resolve project from bridge's SessionStart cwd snapshot.
        # If the bridge can't be resolved (env-var path, no bridge file, etc.)
        # the helper returns None and build_sender_id falls back to live cwd.
        project = _resolve_project_from_bridge_cwd()

        return build_sender_id( "claude.code", project=project, suffix=suffix )

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
            data["_bridge_path"]      = str( session_file )
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

            # Check all known IDs: session_ids list (preferred), plus legacy fields
            all_ids = list( data.get( "session_ids", [] ) )
            # Backward compat: also check session_id and stable_session_id directly
            for field in ( "session_id", "stable_session_id" ):
                val = data.get( field, "" )
                if val and val not in all_ids:
                    all_ids.append( val )

            # Full match or 8-char prefix match against any known ID
            for known_id in all_ids:
                if known_id == session_id or known_id[:8] == session_id[:8]:
                    return data

        except ( json.JSONDecodeError, OSError ):
            continue

    return None


def find_session_path_by_id( session_id ):
    """
    Scan ~/.claude/sessions/cc-*.json for a session_id match and return the file path.

    Sibling of find_session_by_id() that returns the Path instead of the data dict,
    enabling read-modify-write workflows (e.g., conversation_mode toggle).

    Supports both full UUID and 8-char prefix matching. Skips files from dead PIDs.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns Path if a match is found
        - Returns None if no match or session_id is empty
        - Skips bridge files whose PID is dead
        - Never raises exceptions

    Args:
        session_id: Full session UUID or 8-char prefix to match

    Returns:
        Path or None: Bridge file path on match, or None
    """
    if not session_id or not SESSION_DIR.exists():
        return None

    trust_host_pids = _can_trust_host_pids()

    for path in SESSION_DIR.glob( "cc-*.json" ):
        if "buffer" in path.name or "listener" in path.name:
            continue

        if trust_host_pids:
            file_pid = _extract_pid_from_filename( path.name )
            if file_pid is not None and not _is_pid_alive( file_pid ):
                continue

        try:
            with open( path ) as f:
                data = json.load( f )

            all_ids = list( data.get( "session_ids", [] ) )
            for field in ( "session_id", "stable_session_id" ):
                val = data.get( field, "" )
                if val and val not in all_ids:
                    all_ids.append( val )

            for known_id in all_ids:
                if known_id == session_id or known_id[:8] == session_id[:8]:
                    return path

        except ( json.JSONDecodeError, OSError ):
            continue

    return None


def find_active_conversation_sessions( exclude_session_id=None ):
    """
    Scan all bridge files for sessions whose conversation_mode_active=true.

    Used by the conversation-mode HTTP endpoint to enforce the "at most one
    active conversation mode session at a time" invariant — when a session
    activates, all OTHER active sessions are deactivated atomically.

    Honors the same staleness filtering as find_session_path_by_id:
    skips buffer/listener files, skips bridges whose host PID is dead
    (when host PIDs are trustworthy — see _can_trust_host_pids).

    Requires:
        - exclude_session_id is None or a non-empty string

    Ensures:
        - Returns a list of (Path, session_id) tuples for every bridge with
          conversation_mode_active=true (never None; empty list if none)
        - When exclude_session_id is provided, bridges matching that id
          (full UUID OR 8-char prefix, mirroring find_session_path_by_id)
          are NOT included in the returned list
        - session_id in each tuple is the canonical id from the bridge file
          (prefers stable_session_id, falls back to session_id)
        - Never raises exceptions
        - Skips bridge files that fail to parse or open

    Args:
        exclude_session_id: Optional session id (full UUID or 8-char prefix)
            to exclude from results — typically the session that's about to
            be activated, so it isn't displaced by its own enable call

    Returns:
        list[ tuple[ Path, str ] ]: List of (bridge_path, session_id) tuples
    """
    if not SESSION_DIR.exists():
        return []

    trust_host_pids = _can_trust_host_pids()
    results = []

    for path in SESSION_DIR.glob( "cc-*.json" ):
        if "buffer" in path.name or "listener" in path.name:
            continue

        if trust_host_pids:
            file_pid = _extract_pid_from_filename( path.name )
            if file_pid is not None and not _is_pid_alive( file_pid ):
                continue

        try:
            with open( path ) as f:
                data = json.load( f )

            if not bool( data.get( "conversation_mode_active", False ) ):
                continue

            sid = data.get( "stable_session_id" ) or data.get( "session_id" )
            if not sid:
                continue

            if exclude_session_id:
                # Match either full id or 8-char prefix (mirrors find_session_path_by_id)
                all_ids = list( data.get( "session_ids", [] ) )
                for field in ( "session_id", "stable_session_id" ):
                    val = data.get( field, "" )
                    if val and val not in all_ids:
                        all_ids.append( val )
                excluded = any(
                    known_id == exclude_session_id or known_id[:8] == exclude_session_id[:8]
                    for known_id in all_ids
                )
                if excluded:
                    continue

            results.append( ( path, sid ) )

        except ( json.JSONDecodeError, OSError ):
            continue

    return results


def get_conversation_mode( session_id ):
    """
    Read conversation_mode_active flag from the bridge file for a given session_id.

    Conversation mode is the session-level toggle that, when True, makes Claude
    auto-call notify(full_text, suppress_ding=True) after every assistant turn.
    Default state is False (notification mode — current selective TTS behavior).

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)

    Ensures:
        - Returns True only if bridge file exists and conversation_mode_active is truthy
        - Returns False on any failure (missing bridge, parse error, missing field)
        - Never raises exceptions

    Args:
        session_id: Session ID to look up

    Returns:
        bool: True if conversation mode is active, False otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return False

    try:
        with open( path ) as f:
            data = json.load( f )
        return bool( data.get( "conversation_mode_active", False ) )
    except ( json.JSONDecodeError, OSError ):
        return False


def set_conversation_mode( session_id, active ):
    """
    Write conversation_mode_active flag to the bridge file for a given session_id.

    Read-modify-write the bridge JSON to set the flag, preserving all other fields.
    Does NOT create a new bridge file if missing — bridge must already exist
    (created by SessionStart hook).

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - active is a bool

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge not found or write failed
        - Never raises exceptions
        - Preserves all existing fields in the bridge JSON

    Args:
        session_id: Session ID to look up
        active: Target state for conversation_mode_active

    Returns:
        bool: True on successful write, False otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return False

    try:
        with open( path ) as f:
            data = json.load( f )
        data[ "conversation_mode_active" ] = bool( active )
        with open( path, "w" ) as f:
            json.dump( data, f, indent=2 )
        return True
    except ( json.JSONDecodeError, OSError ):
        return False


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

    # Conversation mode smoke (round-trip on tmpdir, no real bridge mutation)
    import tempfile
    with tempfile.TemporaryDirectory() as _tmp:
        _tmp_dir = Path( _tmp )
        _sid = "smoketst-1234-5678-9abc-def012345678"
        _bridge = _tmp_dir / f"cc-{os.getpid()}.json"
        with open( _bridge, "w" ) as _f:
            json.dump( { "session_id": _sid, "stable_session_id": _sid, "cwd": "/tmp" }, _f )
        _orig_dir = SESSION_DIR
        try:
            globals()[ "SESSION_DIR" ] = _tmp_dir
            assert get_conversation_mode( _sid ) is False, "Default should be False"
            assert set_conversation_mode( _sid, True ) is True, "Set True should succeed"
            assert get_conversation_mode( _sid ) is True, "Read after set True should be True"
            assert set_conversation_mode( _sid, False ) is True, "Set False should succeed"
            assert get_conversation_mode( _sid ) is False, "Read after set False should be False"
            assert get_conversation_mode( "nonexistent" ) is False, "Missing session_id returns False"
            assert set_conversation_mode( "nonexistent", True ) is False, "Set on missing bridge returns False"
            print( "Conversation mode smoke: ✓ all assertions passed" )
        finally:
            globals()[ "SESSION_DIR" ] = _orig_dir
