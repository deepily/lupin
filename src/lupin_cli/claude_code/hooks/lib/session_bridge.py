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
import signal as signal_mod
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
    enabling read-modify-write workflows (e.g., speakerphone toggle).

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


BRIDGE_FORMAT_VERSION = 2


def _get_default_speakerphone():
    """
    Return the mode-aware default for `speakerphone_on` when a bridge has no
    explicit field (i.e., v1 bridges from before the Phase 2 rename, OR
    freshly-created bridges that haven't been touched by set_speakerphone yet).

    Solo  → False (today's monopoly-mode default: sessions opt in to TTS render)
    Chorus → True (at-distance is the default in chorus mode)

    Defers the cosa.utils.util import to break any circular-import risk and to
    keep this function side-effect-free at import time.
    """
    try:
        from cosa.utils import util as cu
        return cu.get_tts_interaction_mode() == "chorus"
    except Exception:
        return False  # solo default if anything blows up


def find_active_speakerphone_sessions( exclude_session_id=None ):
    """
    Scan all bridge files for sessions whose speakerphone_on=true.

    Used by the speakerphone HTTP endpoint's SOLO branch to enforce the
    "at most one active speakerphone session at a time" invariant — when a
    session activates, all OTHER active sessions are deactivated atomically.
    In CHORUS mode this scan is not invoked (no displacement enforcement).

    Honors the same staleness filtering as find_session_path_by_id:
    skips buffer/listener files, skips bridges whose host PID is dead
    (when host PIDs are trustworthy — see _can_trust_host_pids).

    Requires:
        - exclude_session_id is None or a non-empty string

    Ensures:
        - Returns a list of (Path, session_id) tuples for every bridge with
          speakerphone_on=true (never None; empty list if none)
        - When exclude_session_id is provided, bridges matching that id
          (full UUID OR 8-char prefix, mirroring find_session_path_by_id)
          are NOT included in the returned list
        - session_id in each tuple is the canonical id from the bridge file
          (prefers stable_session_id, falls back to session_id)
        - Never raises exceptions
        - Skips bridge files that fail to parse or open
        - v1 bridges (without `speakerphone_on` field) treated as inactive
          (no destructive discard — Phase 2 uses upgrade-on-write semantics)

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

            if not bool( data.get( "speakerphone_on", False ) ):
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


def get_speakerphone( session_id ):
    """
    Read `speakerphone_on` flag from the bridge file for a given session_id.

    Speakerphone mode is the per-session toggle that, when True, makes Claude
    auto-call notify(full_text, suppress_ding=True) after every assistant turn.
    The default state when the bridge has no `speakerphone_on` field is
    mode-aware: False in solo mode (today's monopoly behavior), True in chorus
    mode (at-distance default). See _get_default_speakerphone.

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)

    Ensures:
        - Returns True only if bridge file exists and speakerphone_on is truthy
        - Returns mode-aware default if bridge exists but field is missing
          (v1 bridges, freshly-created bridges)
        - Returns False on any failure (missing bridge, parse error)
        - Never raises exceptions

    Args:
        session_id: Session ID to look up

    Returns:
        bool: True if speakerphone is on, False otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return False

    try:
        with open( path ) as f:
            data = json.load( f )
        return bool( data.get( "speakerphone_on", _get_default_speakerphone() ) )
    except ( json.JSONDecodeError, OSError ):
        return False


def set_speakerphone( session_id, on ):
    """
    Write `speakerphone_on` flag to the bridge file for a given session_id.

    Read-modify-write the bridge JSON to set the flag, preserving all other
    fields and stamping `format_version=2` on the bridge for future schema
    evolution. Does NOT create a new bridge file if missing — bridge must
    already exist (created by SessionStart hook).

    Upgrade-on-write semantics: a v1 bridge (with `conversation_mode_active`
    but no `speakerphone_on`) gets `speakerphone_on` + `format_version` added
    on the first set_speakerphone call. The stale `conversation_mode_active`
    key is removed in the same write to avoid two-source-of-truth confusion.

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - on is a bool

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge not found or write failed
        - Never raises exceptions
        - Preserves all existing fields in the bridge JSON except the
          legacy `conversation_mode_active` key, which is removed if present
        - Stamps `format_version=2` (BRIDGE_FORMAT_VERSION)

    Args:
        session_id: Session ID to look up
        on: Target state for speakerphone_on

    Returns:
        bool: True on successful write, False otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return False

    try:
        with open( path ) as f:
            data = json.load( f )
        data[ "speakerphone_on" ] = bool( on )
        data[ "format_version" ] = BRIDGE_FORMAT_VERSION
        # Drop the v1 field if it lingers from a pre-Phase-2 bridge, to avoid
        # two-source-of-truth ambiguity. The v2 field is now authoritative.
        data.pop( "conversation_mode_active", None )
        with open( path, "w" ) as f:
            json.dump( data, f, indent=2 )
        return True
    except ( json.JSONDecodeError, OSError ):
        return False


def get_last_autonarrated_turn_id( session_id ):
    """
    Read last_autonarrated_turn_id from the bridge file for dedup.

    Used by the Stop-hook auto-narrate (Phase 4 of conv-mode-three-layer-
    enforcement plan) to avoid re-narrating the same assistant turn if the
    Stop hook fires twice on the same turn (which can happen).

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns the stamped turn id (string) if present in bridge
        - Returns None if bridge missing, field absent, or any error
        - Never raises

    Args:
        session_id: Session ID to look up

    Returns:
        str or None: Last auto-narrated turn id, or None
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return None
    try:
        with open( path ) as f:
            data = json.load( f )
        return data.get( "last_autonarrated_turn_id" )
    except ( json.JSONDecodeError, OSError ):
        return None


def set_last_autonarrated_turn_id( session_id, turn_id ):
    """
    Write last_autonarrated_turn_id to the bridge file.

    Stamps the turn id after the Stop-hook auto-narrate fires so subsequent
    Stop-hook invocations on the same turn don't re-narrate.

    Requires:
        - session_id is a non-empty string
        - turn_id is a non-empty string

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge missing or write failed
        - Never raises
        - Preserves all other bridge fields

    Args:
        session_id: Session ID to look up
        turn_id:    Turn identifier to stamp

    Returns:
        bool: True on successful write
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return False
    try:
        with open( path ) as f:
            data = json.load( f )
        data[ "last_autonarrated_turn_id" ] = str( turn_id )
        with open( path, "w" ) as f:
            json.dump( data, f, indent=2 )
        return True
    except ( json.JSONDecodeError, OSError ):
        return False


def set_user_id( session_id, user_id ):
    """
    Write `user_id` to the bridge file for a given session_id.

    Phase 3 — Option 2 fix per
    `src/rnd/v0.1.7/2026.05.13-broadcast-ui-no-active-sessions-bug.md`. The
    inter-session-commons broadcast surface filters active sessions by
    `bridge["user_id"] == authenticated_user_id` (T7 + Q9 same-user scoping).
    Without this stamp every bridge fails the filter and the broadcast UI
    shows "no active sessions". Pairs with Option 1's graceful-degradation
    fallback in `routers/commons.py`: once `set_user_id` lands, the fallback
    branch becomes inactive for new bridges and full cross-user isolation
    is enforced.

    Called from `cc_notification_listener._stamp_user_id_on_bridge()` once
    at listener startup, after the authenticated user_id has been resolved
    via `/auth/login`.

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - user_id is a non-empty string (canonical user UUID from
          `/auth/login` response at `user.id`)

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge missing, parse-fail, or write-fail
        - Never raises
        - Preserves all other bridge fields (mirrors `set_last_autonarrated_turn_id`)

    Args:
        session_id: Session ID to look up (full UUID or 8-char prefix)
        user_id:    Canonical user UUID to stamp on the bridge

    Returns:
        bool: True on successful write
    """
    if not session_id or not user_id:
        return False
    path = find_session_path_by_id( session_id )
    if not path:
        return False
    try:
        with open( path ) as f:
            data = json.load( f )
        data[ "user_id" ] = str( user_id )
        with open( path, "w" ) as f:
            json.dump( data, f, indent=2 )
        return True
    except ( json.JSONDecodeError, OSError ):
        return False


def get_voice_persona( session_id ):
    """
    Read voice_persona dict from the bridge file for a given session_id.

    The voice_persona is a per-session voice/persona allocation written by the
    SessionStart hook (via the /api/cosa-voice/voice-persona/{sid}/allocate
    endpoint). Each new Claude Code session is uniformly randomly assigned a
    voice from a 6-voice pool so the user can audibly distinguish parallel
    sessions. Sam (the global default) is reserved as the system-wide voice
    for any TTS request lacking a voice_id and is NOT in the allocatable pool.

    See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)

    Ensures:
        - Returns the voice_persona dict if the bridge exists and the field is
          a non-empty dict
        - Returns None on any failure (missing bridge, parse error, missing
          field, field is null/empty/non-dict)
        - Never raises exceptions

    Args:
        session_id: Session ID to look up

    Returns:
        dict or None: The persona dict (with keys voice_id, name, icon, color,
            borrowed, assigned_at) when present; None otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return None

    try:
        with open( path ) as f:
            data = json.load( f )
        persona = data.get( "voice_persona" )
        if isinstance( persona, dict ) and persona:
            return persona
        return None
    except ( json.JSONDecodeError, OSError ):
        return None


def set_voice_persona( session_id, persona ):
    """
    Write voice_persona to the bridge file for a given session_id.

    Read-modify-write the bridge JSON to set the field, preserving all other
    fields. Pass `persona=None` to clear the field (release the slot).

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - persona is a dict (to set) or None (to clear)

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge not found or write failed
        - Never raises exceptions
        - Preserves all existing fields in the bridge JSON
        - When persona is None, the voice_persona key is set to null (not
          deleted) so consumers can distinguish "explicitly released" from
          "field never existed"

    Args:
        session_id: Session ID to look up
        persona: dict to write, or None to clear

    Returns:
        bool: True on successful write, False otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return False

    try:
        with open( path ) as f:
            data = json.load( f )
        data[ "voice_persona" ] = persona
        with open( path, "w" ) as f:
            json.dump( data, f, indent=2 )
        return True
    except ( json.JSONDecodeError, OSError ):
        return False


def get_idle_detection( session_id ):
    """
    Read the idle_detection block from the bridge file for a given session_id.

    The idle_detection block tracks per-session state for the deferred
    "Anything else?" prompt with exponential backoff. See:
        src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md

    Schema:
        {
          "last_interaction_at" : ISO8601 with tz,
          "backoff_index"       : int (index into settings backoff_minutes),
          "waiter_pid"          : int (detached helper PID) or None,
          "waiter_started_at"   : ISO8601 (set by waiter on sleep-start)
        }

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)

    Ensures:
        - Returns the idle_detection dict if the bridge exists and the field is
          a non-empty dict
        - Returns None on any failure (missing bridge, parse error, missing
          field, field is null/empty/non-dict)
        - Never raises exceptions

    Args:
        session_id: Session ID to look up

    Returns:
        dict or None: The idle_detection dict when present; None otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return None

    try:
        with open( path ) as f:
            data = json.load( f )
        block = data.get( "idle_detection" )
        if isinstance( block, dict ) and block:
            return block
        return None
    except ( json.JSONDecodeError, OSError ):
        return None


def set_idle_detection_field( session_id, **fields ):
    """
    Merge fields into the idle_detection block on the bridge file.

    Read-modify-write: reads the bridge, merges `fields` into the existing
    idle_detection sub-dict (creating the sub-dict if absent), writes back.
    Other top-level fields and other idle_detection sub-fields are preserved.

    Race semantics: same as `set_voice_persona` and other writers in this
    module — no fcntl, no tmpfile+rename. Two concurrent set_*_field calls
    on the same bridge could lose one update (read-modify-write window). For
    the idle-detection use case this is acceptable: resets are idempotent,
    the worst case is one missed bump that the next event replays.

    Requires:
        - session_id is a non-empty string
        - fields contains only JSON-serializable values

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge not found or write failed
        - Never raises exceptions
        - Other top-level bridge fields preserved
        - Existing idle_detection fields not mentioned in `fields` preserved

    Args:
        session_id: Session ID to look up
        **fields: keyword args; each becomes a field in idle_detection

    Returns:
        bool: True on successful write, False otherwise
    """
    if not fields:
        return True  # Nothing to do — caller passed no updates

    path = find_session_path_by_id( session_id )
    if not path:
        return False

    try:
        with open( path ) as f:
            data = json.load( f )
        block = data.get( "idle_detection" )
        if not isinstance( block, dict ):
            block = { }
        block.update( fields )
        data[ "idle_detection" ] = block
        with open( path, "w" ) as f:
            json.dump( data, f, indent=2 )
        return True
    except ( json.JSONDecodeError, OSError ):
        return False


def clear_idle_waiter_pid( session_id ):
    """
    Atomically clear the waiter_pid field and return the old PID.

    Used by callers that want to kill the waiter — they get the PID to
    SIGTERM, AND the bridge field is cleared so a concurrent spawn knows
    the slot is free. The kill itself is the caller's responsibility (see
    `kill_idle_waiter` for the convenience wrapper).

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns the prior waiter_pid value (int) if there was one
        - Returns None if there was no waiter_pid, or the bridge couldn't
          be read/written
        - Never raises exceptions
        - On success: idle_detection.waiter_pid is set to None in the bridge

    Args:
        session_id: Session ID to look up

    Returns:
        int or None: The prior waiter_pid (for the caller to kill), or None
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return None

    try:
        with open( path ) as f:
            data = json.load( f )
        block = data.get( "idle_detection" )
        if not isinstance( block, dict ):
            return None
        old_pid = block.get( "waiter_pid" )
        if old_pid is None:
            return None
        block[ "waiter_pid" ] = None
        data[ "idle_detection" ] = block
        with open( path, "w" ) as f:
            json.dump( data, f, indent=2 )
        return int( old_pid ) if isinstance( old_pid, int ) else None
    except ( json.JSONDecodeError, OSError, ValueError ):
        return None


def kill_idle_waiter( session_id, signal=None ):
    """
    Kill any live idle-waiter helper for this session.

    Convenience wrapper: calls `clear_idle_waiter_pid` to atomically claim
    the prior PID, then sends SIGTERM (or the supplied signal) to it. PID
    liveness is checked first to avoid signaling unrelated processes that
    may have inherited the PID.

    Requires:
        - session_id is a non-empty string
        - signal is None (defaults to SIGTERM) or a valid signal int

    Ensures:
        - Returns True if a waiter was killed
        - Returns False if there was no waiter or the kill failed
        - Never raises exceptions

    Args:
        session_id: Session ID to look up
        signal: Signal to send (default SIGTERM)

    Returns:
        bool: True if a waiter PID was found and signal-sent, False otherwise
    """
    sig = signal if signal is not None else signal_mod.SIGTERM

    pid = clear_idle_waiter_pid( session_id )
    if pid is None:
        return False

    if not _is_pid_alive( pid ):
        return False

    try:
        os.kill( pid, sig )
        return True
    except ( ProcessLookupError, PermissionError, OSError ):
        return False


def prune_dead_persona_bridges():
    """
    Null the voice_persona field on any bridge file whose host PID is dead.

    Runs from the SessionStart hook on the host side, where host PIDs are
    visible and _is_pid_alive() returns a meaningful answer. The function
    short-circuits to no-op when called from a context where host PIDs are
    NOT trustworthy (i.e., inside a container) — pruning under that
    condition would mark every bridge dead and is the opposite of what we
    want.

    Why this exists: the in-container scan in find_active_voice_persona_sessions
    intentionally skips the dead-PID filter (host PIDs are invisible inside
    the container), so leftover personas from prior days accumulate as
    "occupied" and exhaust the allocation pool at day-start. A host-side
    prune at every SessionStart hook scrubs those leftovers before /allocate
    runs.

    See: src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md

    Ensures:
        - Returns 0 when SESSION_DIR doesn't exist, when called from a
          non-host context (_can_trust_host_pids() is False), or when no
          bridges need pruning
        - Bridges with isinstance(voice_persona, dict) == False are left
          untouched (no spurious writes)
        - Buffer/listener files (cc-*-buffer.json, cc-*-listener.json) are
          skipped (same convention as find_active_voice_persona_sessions)
        - Returns the count of bridges actually pruned (voice_persona set
          to None)
        - Never raises — per-file errors are swallowed and the next file
          is processed

    Returns:
        int: Number of bridges pruned
    """
    if not SESSION_DIR.exists():
        return 0
    if not _can_trust_host_pids():
        return 0

    pruned = 0
    for path in SESSION_DIR.glob( "cc-*.json" ):
        if "buffer" in path.name or "listener" in path.name:
            continue

        file_pid = _extract_pid_from_filename( path.name )
        if file_pid is None or _is_pid_alive( file_pid ):
            continue

        try:
            with open( path ) as f:
                data = json.load( f )
        except ( json.JSONDecodeError, OSError ):
            continue

        persona = data.get( "voice_persona" )
        if not isinstance( persona, dict ) or not persona:
            continue

        data[ "voice_persona" ] = None
        try:
            with open( path, "w" ) as f:
                json.dump( data, f, indent=2 )
            pruned += 1
        except OSError:
            continue

    return pruned


def find_active_voice_persona_sessions( stale_threshold_seconds: int = 43200 ):
    """
    Scan all bridge files for sessions whose voice_persona is non-null.

    Used by the voice-persona HTTP endpoints to compute pool occupancy:
    `/allocate` excludes occupied persona names so each session gets a
    unique voice; `/pool` returns a snapshot for diagnostics.

    Two staleness filters apply, in order:

    1. **PID liveness** (host-side only) — when `_can_trust_host_pids()` is
       True (host context), bridges whose extracted host PID is dead are
       skipped. Inside a container this check is bypassed because host PIDs
       are invisible from the container's PID namespace.

    2. **mtime TTL** (both host and container) — bridges whose file mtime
       is older than `stale_threshold_seconds` are skipped regardless of
       context. Belt-and-suspenders against the residual case where the
       host-side prune at SessionStart didn't fire (e.g., server bounced
       mid-day with no new sessions). The cc-notification-listener
       heartbeat updates bridge mtime periodically, so an actively-used
       session keeps its mtime fresh within this window.

    A dead-PID OR stale-mtime bridge with a non-null voice_persona is
    treated as "free" — its slot is implicitly reclaimed by being
    filtered out here.

    See: src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md

    Requires:
        - stale_threshold_seconds is a positive integer (default 12 hours)

    Ensures:
        - Returns a list of (Path, session_id, persona) tuples for every
          bridge with a non-null voice_persona dict whose liveness checks pass
        - session_id is the canonical id (stable_session_id preferred)
        - persona is the dict as stored in the bridge
        - Never raises exceptions
        - Skips bridge files that fail to parse or open
        - Skips bridge files whose stat() fails

    Returns:
        list[ tuple[ Path, str, dict ] ]: (bridge_path, session_id, persona)
    """
    if not SESSION_DIR.exists():
        return []

    trust_host_pids = _can_trust_host_pids()
    now             = time.time()
    results         = []

    for path in SESSION_DIR.glob( "cc-*.json" ):
        if "buffer" in path.name or "listener" in path.name:
            continue

        if trust_host_pids:
            file_pid = _extract_pid_from_filename( path.name )
            if file_pid is not None and not _is_pid_alive( file_pid ):
                continue

        try:
            mtime_age = now - path.stat().st_mtime
            if mtime_age > stale_threshold_seconds:
                continue
        except OSError:
            continue

        try:
            with open( path ) as f:
                data = json.load( f )

            persona = data.get( "voice_persona" )
            if not isinstance( persona, dict ) or not persona:
                continue

            sid = data.get( "stable_session_id" ) or data.get( "session_id" )
            if not sid:
                continue

            results.append( ( path, sid, persona ) )

        except ( json.JSONDecodeError, OSError ):
            continue

    return results


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
            assert get_speakerphone( _sid ) is False, "Default should be False"
            assert set_speakerphone( _sid, True ) is True, "Set True should succeed"
            assert get_speakerphone( _sid ) is True, "Read after set True should be True"
            assert set_speakerphone( _sid, False ) is True, "Set False should succeed"
            assert get_speakerphone( _sid ) is False, "Read after set False should be False"
            assert get_speakerphone( "nonexistent" ) is False, "Missing session_id returns False"
            assert set_speakerphone( "nonexistent", True ) is False, "Set on missing bridge returns False"
            print( "Conversation mode smoke: ✓ all assertions passed" )

            # Voice persona smoke (round-trip + active-scan)
            _persona = {
                "name"        : "Tiberius",
                "voice_id"    : "pNInz6obpgDQGcFmaJgB",
                "icon"        : "🌑",
                "color"       : "#3F51B5",
                "borrowed"    : False,
                "assigned_at" : "2026-04-28T20:30:00Z"
            }
            assert get_voice_persona( _sid ) is None, "Default persona is None"
            assert set_voice_persona( _sid, _persona ) is True, "Set persona should succeed"
            assert get_voice_persona( _sid ) == _persona, "Round-trip persona equals original"
            _active = find_active_voice_persona_sessions()
            assert len( _active ) >= 1, "Should find at least our session"
            assert any( p[ "name" ] == "Tiberius" for _, _, p in _active ), "Tiberius should be in active set"
            assert set_voice_persona( _sid, None ) is True, "Clear persona should succeed"
            assert get_voice_persona( _sid ) is None, "Cleared persona reads as None"
            assert get_voice_persona( "nonexistent" ) is None, "Missing session returns None"
            assert set_voice_persona( "nonexistent", _persona ) is False, "Set on missing bridge returns False"
            print( "Voice persona smoke: ✓ all assertions passed" )
        finally:
            globals()[ "SESSION_DIR" ] = _orig_dir
