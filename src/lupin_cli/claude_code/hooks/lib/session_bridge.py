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
    - CWD fallback is a best-guess from another session → not cached
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
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple
from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir


# Row 8ccc20ab: DERIVED from the one seam so LUPIN_SESSIONS_DIR governs any
# freshly-started process. Still a module-level NAME because ~200 in-process
# tests patch it directly; the env var is the out-of-process half.
SESSION_DIR = sessions_dir()


def atomic_write_json( path, data ):
    """
    Write `data` as JSON to `path` so a reader sees only a whole old or whole new document.

    Two racing writers can splice a file. Both fds truncate at open and keep their own offsets, leaving one valid document plus a longer one's tail.
    A spliced bridge will not parse, so every persona resolver ignores it. The seat then becomes unaddressable by `dm_send`; the racers are often one seat.
    `os.replace` is atomic on POSIX, so concurrent writers degrade to last-writer-wins, and no writer has to remember anything: a mechanism, not a rule.

    Requires:
        - path is a str or Path whose parent directory exists and is writable
        - data is JSON-serializable

    Requires:
        - path is a str or Path whose parent directory exists and is writable
        - data is JSON-serializable

    Ensures:
        - Returns True when the new document is fully in place at path
        - Returns False on any OSError/TypeError/ValueError, leaving whatever
          was already at path untouched; a failed write never truncates
        - Names the path and the error on stderr when it returns False, and
          emits nothing on success (a witness that fires on success is noise)
        - A concurrent reader sees the complete old or the complete new
          document; it never observes a partial or spliced file
        - Leaves no temp file behind on the failure path
        - Never raises
        - The temp file is created in the same directory as the target, because a temp file elsewhere may sit on another
          filesystem, where `os.replace` raises OSError instead of being atomic
        - The failure witness lives here and not at the call sites: six hook sites ignore the return, so without it a failed
          write leaves no log, no counter and no exit code, and the seat looks healthy while blind
        - The exception is swallowed because a raising SessionStart hook leaves a seat with no bridge at all; the silence
          was what needed a witness, and stderr is the channel that does not pollute Claude's context

    Args:
        path: destination file
        data: JSON-serializable object

    Returns:
        bool: True on success, False on failure
    """
    import tempfile

    path = str( path )
    tmp  = None
    try:
        fd, tmp = tempfile.mkstemp( dir=os.path.dirname( path ) or ".", suffix=".tmp" )
        with os.fdopen( fd, "w" ) as f:
            json.dump( data, f, indent=2 )
            f.flush()
            # Widen to group-rw BEFORE the atomic replace so perms land with the
            # swap (fchmod on the fd, not chmod on the path after os.replace — a
            # post-replace failure would fire the stderr witness AFTER the doc
            # already landed, and mkstemp's hardcoded 0600 masks any dir ACL to
            # ---). Group-rw lets a cross-uid reader (container uid 1001 ⇄ host
            # OS-Login uid, sharing the sessions dir's setgid group) read+rewrite
            # the bridge. See src/rnd/v0.1.9/2026.07.24-vm-persona-bridge-mount-uid-divergence.md.
            os.fchmod( f.fileno(), 0o660 )
        os.replace( tmp, path )
        return True
    except ( OSError, TypeError, ValueError ) as e:
        if tmp is not None:
            try: os.unlink( tmp )
            except OSError: pass
        print( f"[atomic_write_json] WARNING: bridge write FAILED for {path}: {e!r} "
               f"— the field did NOT persist; this seat may look healthier than it is",
               file=sys.stderr )
        return False

# Cache to avoid repeated file reads
_cached_session_id: Optional[str] = None
# The source `_cached_session_id` was resolved under. Only definitive sources are
# ever cached, so this is never SOURCE_CWD_FALLBACK — a guess is re-resolved every call.
_cached_session_source: Optional[str] = None
_fallback_session_id: str = uuid.uuid4().hex[:8]

# Resolution source constants
#
# 🔴 THESE ARE NOT DECORATION — `cwd_fallback` MEANS "THIS MIGHT BE SOMEBODY ELSE".
# Tiers 2 and 3 identify a session by its own process tree and cannot name another seat.
# Tier 4 identifies it by working directory, and on this fleet every seat shares one
# checkout, so the filter excludes nobody: it returns whichever colleague touched their
# bridge last. The tier is KEPT deliberately (María's ruling, 2026-09-03) — removing it
# turns a wrong-seat into a fail-to-resolve — so the source is how a caller tells the two
# apart. `get_claude_session_id_with_source` / `wait_for_session_id_with_source` are the
# doors that carry it; the bare twins remain byte-for-byte compatible for every existing
# caller.
SOURCE_PPID         = "ppid"
SOURCE_GRANDPARENT  = "grandparent"
SOURCE_CWD_FALLBACK = "cwd_fallback"
SOURCE_ENV          = "env"                 # CLAUDE_SESSION_ID — definitive, set by the host
SOURCE_GENERATED    = "generated_fallback"  # invented here; wrong, but nobody else's

# The sources a caller may act on as ITS OWN identity. A generated fallback is wrong and
# harmless — it names no real seat. A cwd_fallback is wrong and harmful — it names a
# colleague, so work filed under it lands on their board.
DEFINITIVE_SOURCES = ( SOURCE_ENV, SOURCE_PPID, SOURCE_GRANDPARENT )


def canonical_persona_key( name ) -> str:
    """
    Return the canonical persona key used to match task-store rows across seams.

    The owed-work read seam (stop hook `_owed_count_from_store`) and the task-store write seam must share this one normalizer, so `owner_persona` rows are always found.
    The store holds voice-pool names: accent- and punctuation-stripped, lowercased, internal spaces kept ("María" is "maria", "Mr. Radio" is "mr radio"); a bare `.lower()` matched zero rows.
    `follow_through_escalation_watcher._norm_persona` is no substitute: it also strips spaces ("mrradio") and would not match the store.

    Requires:
        - name is a string or None

    Ensures:
        - None, a non-string, an empty string or a whitespace-only string returns "" (unmatchable sentinel)
        - otherwise: NFKD-decomposed, combining marks dropped, lowercased,
          reduced to [a-z0-9 ] (punctuation/emoji removed, single spaces kept),
          internal runs of whitespace collapsed to one space, ends trimmed
        - idempotent: canonical_persona_key( canonical_persona_key( x ) ) == canonical_persona_key( x )

    Args:
        name: A persona name in display or already-normalized form

    Returns:
        str: the canonical store key
    """
    # Implementation moved to the centralized home lupin_mcp.persona_normalization
    # (2026-06-19) so there is exactly ONE algorithm across the codebase. Delegated
    # here to preserve existing `from ...session_bridge import canonical_persona_key`
    # call sites (stop.py read seam, hook write seam, tests).
    from lupin_mcp.persona_normalization import canonical_persona_key as _impl
    return _impl( name )


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
    Say whether this process shares its PID namespace with the bridge writers.

    Bridge files are written by hooks on the host and named cc-{host pid}.json. Inside a Docker container those host pids are invisible. Every `kill( host_pid, 0 )` then raises ProcessLookupError, so a naive `_is_pid_alive()` filter discards every bridge as dead.
    The Lupin FastAPI server reads bridges for the conversation-mode endpoint inside the lupin-rest-dev container, so that path skips the liveness filter. Host-side callers (hook scripts, MCP server) keep it, since they need staleness pruning.

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

    Use this when the session bridge file has been overwritten (for example after a context clear) and the MCP server needs the new session ID.

    Ensures:
        - `_cached_session_id` is set to None
        - Next call to get_claude_session_id() will re-read from file
    """
    global _cached_session_id, _cached_session_source
    _cached_session_id     = None
    _cached_session_source = None


def _find_session_file() -> Optional[ Tuple[ Path, str ] ]:
    """
    Find the session file for the current process's parent (Claude Code).

    Walks up the process tree for a cc-{pid}.json file. Hooks are spawned by Claude Code, so PPID points to it. MCP servers may have a wrapper, so the grandparent is checked too.
    Returns ( path, source ). The source matters for caching. "ppid" and "grandparent" are definitive and safe to cache. "cwd_fallback" is a best guess from another session and is not cached.

    Requires:
        - SESSION_DIR may or may not exist

    Ensures:
        - Returns ( Path, source_str ) if a session file is found
        - Returns None if no matching file exists
        - Checks: own PPID, then grandparent PID, then CWD-matching file (fallback)
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

    Resolution order: the cached value, then the CLAUDE_SESSION_ID env var, then the session file from the SessionStart hook, then a self-generated fallback UUID.
    Tier 1 (env var) and tier 2 (PPID or grandparent match) are cached. A CWD fallback is not cached, because it could come from another session.

    Ensures:
        - Always returns a string (never None)
        - Caches resolved value for PPID/grandparent matches only

    Returns:
        str: Session ID (8-char hex fallback, or full ID from Claude Code)
    """
    return get_claude_session_id_with_source()[ 0 ]


def get_claude_session_id_with_source() -> Tuple[ str, str ]:
    """
    Get the Claude Code session_id and how it was reached.

    `_find_session_file` computes a source and refuses to cache a `cwd_fallback`. A bare `str` return loses that distinction, so a guess and a certainty reached callers in the same shape.
    This door keeps them apart so downstream code can refuse one and accept the other. The bare twin above is unchanged for every existing caller.

    Requires:
        - nothing

    Ensures:
        - Always returns a ( str, str ) pair — never None, never a bare id
        - source is one of `SOURCE_ENV` / `SOURCE_PPID` / `SOURCE_GRANDPARENT` /
          `SOURCE_CWD_FALLBACK` / `SOURCE_GENERATED` — never empty
        - Caches definitive matches only; a cwd_fallback is re-resolved every call
        - A cached value reports the source it was cached under

    Returns:
        Tuple[ str, str ]: ( session_id, resolution_source )
    """
    global _cached_session_id, _cached_session_source

    if _cached_session_id:
        return ( _cached_session_id, _cached_session_source )

    # Tier 1: Environment variable (future-proof)
    env_id = os.getenv( "CLAUDE_SESSION_ID" )
    if env_id:
        _cached_session_id     = env_id
        _cached_session_source = SOURCE_ENV
        return ( env_id, SOURCE_ENV )

    # Tier 2: Session file from hook
    result = _find_session_file()
    if result:
        session_file, source = result
        file_id = _read_session_file( session_file )
        if file_id:
            # Only cache definitive matches — CWD fallback is a guess
            if source != SOURCE_CWD_FALLBACK:
                _cached_session_id     = file_id
                _cached_session_source = source
            return ( file_id, source )

    # Tier 3: Fallback
    return ( _fallback_session_id, SOURCE_GENERATED )


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

    Blocks until the SessionStart hook writes the session file, or until timeout. Useful for MCP server initialization where the real ID is wanted.
    Always bypasses the cache for fresh resolution, because this function waits for the real session file to appear.

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
    return wait_for_session_id_with_source( timeout=timeout, poll_interval=poll_interval )[ 0 ]


def wait_for_session_id_with_source( timeout: float = 10.0, poll_interval: float = 0.5 ) -> Tuple[ str, str ]:
    """
    Wait for the real Claude Code session_id, and report how it was reached.

    This is the door the MCP server's session watcher uses. A source exposed only on the non-blocking twin would leave the server as blind as before, so both doors carry it.

    Requires:
        - timeout is a positive float
        - poll_interval is a positive float less than timeout

    Ensures:
        - Always returns a ( str, str ) pair
        - source is never empty; `SOURCE_GENERATED` when the timeout expires
        - Caches definitive matches only — a cwd_fallback is never cached
        - Bypasses the cache on entry, as the bare twin always has

    Args:
        timeout: Max seconds to wait (default 10)
        poll_interval: Seconds between file checks (default 0.5)

    Returns:
        Tuple[ str, str ]: ( session_id, resolution_source )
    """
    global _cached_session_id, _cached_session_source

    # Always check env var first (no polling needed)
    env_id = os.getenv( "CLAUDE_SESSION_ID" )
    if env_id:
        _cached_session_id     = env_id
        _cached_session_source = SOURCE_ENV
        return ( env_id, SOURCE_ENV )

    # Poll for session file — bypass cache for fresh resolution
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _find_session_file()
        if result:
            session_file, source = result
            file_id = _read_session_file( session_file )
            if file_id:
                if source != SOURCE_CWD_FALLBACK:
                    _cached_session_id     = file_id
                    _cached_session_source = source
                return ( file_id, source )
        time.sleep( poll_interval )

    return ( _fallback_session_id, SOURCE_GENERATED )


def _resolve_project_from_bridge_cwd() -> Optional[str]:
    """
    Resolve the project name from the bridge file's SessionStart cwd field.

    The bridge `cwd` is written once and names where `claude` was launched, so it is stable for the session. `os.getcwd()` in a hook drifts, because Claude Code keeps the Bash subshell's cwd across tool calls. One `cd src/cosa` makes `detect_project()` return "cosa" instead of "lupin".
    That drift duplicates the notification UI panes, one per sender_id, for a single session. The walk goes up from the bridge `cwd` to a `.git` ancestor, resolves a gitlink to its main repo, and applies `_PROJECT_ALIASES`.
    It must agree with `detect_project()`. The two once diverged because a docstring claimed equivalence and nobody checked. A unit test now drives both resolvers over one real `git worktree add`.

    Ensures:
        - Returns the project name from the bridge file's SessionStart cwd
        - Returns None if no bridge file resolves or the bridge has no cwd
          field, and also on a JSON, OS, value or import error
        - Returns the lowercased cwd basename, alias-normalized, when the cwd path does not exist or no .git ancestor is found
        - Never raises exceptions
        - A `.git` that is a file (worktree or submodule) is resolved through `_worktree_owner_basename`, falling back to
          `_dangling_gitlink_owner_basename` when live git cannot answer, because the bare walk named a worktree by its directory
        - The equivalence with `detect_project()` is reached by calling its own helpers and not by copying its logic, since two
          derivations that agree only by careful copying diverge the first time someone edits one
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

        from cosa.agents.utils.sender_id import (
            _PROJECT_ALIASES,
            _worktree_owner_basename,
            _dangling_gitlink_owner_basename,
        )

        candidate = Path( bridge_cwd ).resolve()
        for parent in [ candidate, *candidate.parents ]:
            git_entry = parent / ".git"
            if git_entry.exists():
                # 🔴 WORKTREE-AWARE, MIRRORING detect_project() — row 6597cea9.
                # `.git` is a FILE in a worktree AND in a submodule, and
                # `.exists()` is True for both, so the bare walk above stopped at
                # the worktree root and took its DIRECTORY name. A seat in
                # /…/lupin-wt-cc-author-maria-4 then emitted
                # `claude.code@lupin-wt-cc-author-maria-4.deepily.ai#950b26f1`
                # while every other emitter used `…@lupin.deepily.ai#950b26f1` —
                # SAME session hash, two project segments, and the focus bar
                # (keyed on sender_id, correctly) rendered one seat as two rows.
                # Rick reported it for five workers, every one of them in a
                # worktree.
                #
                # ⚠️ THE DOCSTRING ABOVE ALREADY CLAIMED THIS. It says this helper
                # "matches detect_project() semantics exactly, just sourced from
                # the bridge instead of live cwd" — true when written, false the
                # day the gitlink branch was added to detect_project() (the
                # 2026-06-11 dangling-gitlink incident) and not mirrored here. A
                # reader trusting that sentence had no reason to look, which is
                # why it took a report from the operator to find.
                #
                # ⚠️ AND IT IS NOT A CANONICALISATION GAP. ~/.lupin/config maps
                # [lupin], [plan], [lupin-mobile] and carries no [lupin-wt-*]
                # section, and the canonicaliser returns an unmapped name
                # unchanged — so reaching for it would have changed nothing.
                #
                # The submodule/worktree disambiguation is git's own
                # (`--git-common-dir`), inside the shared helper; a submodule
                # still answers with its own basename, which is what keeps
                # src/cosa resolving to "cosa".
                if git_entry.is_file():
                    owner = _worktree_owner_basename( parent )
                    if owner is None:
                        # Live git could not answer — the worktree's admin dir
                        # was deleted while the directory survived. Parse the
                        # gitlink's `gitdir:` target statically rather than
                        # degrading to this directory's own name.
                        owner = _dangling_gitlink_owner_basename( git_entry )
                    if owner is not None:
                        return _PROJECT_ALIASES.get( owner, owner )
                name = parent.name.lower()
                return _PROJECT_ALIASES.get( name, name )
        # No .git ancestor — fall back to the basename so callers always
        # get a sensible default rather than None.
        basename = candidate.name.lower()
        return _PROJECT_ALIASES.get( basename, basename )
    except ( json.JSONDecodeError, OSError, ValueError, ImportError ):
        return None


def resolve_project_name( environ=None ) -> str:
    """
    Resolve the current session's project name for hook consumers.

    Its consumers are the task-store write gate's manager-figure predicate, the per-repo persona-chain env-key lookup and hook credential resolution; it replaced two duplicate derivers.
    It is not the only resolver: `build_sender_id_for_cc`, which stamps identity onto every peer DM, calls `_resolve_project_from_bridge_cwd()` and falls through to `detect_project()` and the live cwd.
    The two disagree when a seat's cwd and `LUPIN_ROOT` name different repos. Merging them is deferred because it could mask the `@lupin` DM stamp, so no layer should be assumed to share one name.

    Requires:
        - environ is a Mapping or None (None means os.environ)

    Ensures:
        - Returns a lowercase, non-empty project name string
        - Prefers the bridge-cwd-anchored project; only falls back to
          `LUPIN_ROOT`/cwd when the bridge cannot resolve one
        - Never raises
        - Resolves in order: first the bridge file's SessionStart cwd, taken to the nearest `.git` ancestor through
          `_resolve_project_from_bridge_cwd` and alias-normalized
        - That source is anchored to where `claude` was launched, so a non-lupin session resolves to its own project; the
          old `LUPIN_ROOT` basename rule returned "lupin" for every session and misled the persona-chain and credential lookups
        - Falls back only when no bridge resolves (no bridge file, no `cwd` field): the `LUPIN_ROOT` basename, then the live
          cwd basename, a degraded last resort so the name is never empty
    """
    project = _resolve_project_from_bridge_cwd()
    if project:
        return project
    if environ is None:
        environ = os.environ
    lupin_root = environ.get( "LUPIN_ROOT", "" )
    if lupin_root:
        return Path( lupin_root ).name.lower()
    return Path.cwd().name.lower()


def build_sender_id_for_cc( session_id: Optional[str] = None ) -> Optional[str]:
    """
    Build a Claude Code sender_id for notification routing.

    The suffix is the first 8 hex chars of the CC session_id, giving ids like claude.code@lupin.deepily.ai#a1b2c3d4. The project segment comes from the bridge file's SessionStart cwd snapshot (via `_resolve_project_from_bridge_cwd`), not live `os.getcwd()`.
    The bridge is stable for the session, but live cwd drifts once the user runs `cd` in a Bash tool call. Without this, one session alternates between the project segments `lupin` and `cosa` under one suffix.
    The notifications UI renders those as duplicate sender cards. It falls back to live-cwd detection, the legacy behavior, only if the bridge cannot be resolved.

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


def find_session_by_id( session_id, exact=False, check_pid=True ):
    """
    Scan ~/.claude/sessions/cc-*.json for a session_id match and return its data.

    Pid liveness is meaningful only in the host's pid namespace. Inside a container every host seat reads dead and every bridge is skipped, so the console roster marked every live seat unwatchable.
    A caller that may run in a container passes `check_pid=False`. With no pid to tell stale from live, the newest file by mtime among the matches wins. Matching takes a full UUID or an 8-char prefix.
    Exact mode (`exact=True`, opt-in) compares full UUIDs only. Callers of an irreversible self-aimed action, such as self_respin's `/clear`, must use it. Two seats sharing a first-8-char prefix would otherwise aim the clear at someone else's session. The default stays prefix-tolerant for existing callers (arbiter poke, manager_resolver, arbiter_job).

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns full session data dict if a match is found
        - Returns None if no match or session_id is empty
        - exact=True: matches only on full-id equality (no prefix fallback)
        - exact=False (default): full-id or 8-char-prefix equality (legacy)
        - Skips bridge files whose PID is dead, unless check_pid is False
        - Never raises exceptions

    Args:
        session_id: Full session UUID (or, when exact=False, an 8-char prefix) to match
        exact: when True, require a full-id match — no 8-char prefix fallback
        check_pid: when False, skip the liveness check and prefer the newest match

    Returns:
        dict or None: Session data dict, or None
    """
    if not session_id or not SESSION_DIR.exists():
        return None

    paths = SESSION_DIR.glob( "cc-*.json" )
    if not check_pid:
        # Newest first, so the first match is the most recently written bridge.
        paths = sorted( paths, key=_mtime_or_zero, reverse=True )

    for path in paths:
        # Skip non-bridge files (buffers, listeners, etc.)
        if "buffer" in path.name or "listener" in path.name:
            continue

        # PID liveness check
        file_pid = _extract_pid_from_filename( path.name )
        if check_pid and file_pid is not None and not _is_pid_alive( file_pid ):
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

            # Full match always; 8-char prefix match ONLY when not in exact mode
            for known_id in all_ids:
                if known_id == session_id or ( not exact and known_id[:8] == session_id[:8] ):
                    return data

        except ( json.JSONDecodeError, OSError ):
            continue

    return None


def _mtime_or_zero( path ):
    """
    A bridge file's mtime, for newest-first ordering.

    Ensures:
        - returns the file's st_mtime, or 0.0 when it vanished between glob and stat
          (a racing SessionEnd delete), so the sort never raises
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_session_path_by_id( session_id, exact=False ):
    """
    Scan ~/.claude/sessions/cc-*.json for a session_id match and return the file path.

    Sibling of `find_session_by_id()` that returns the Path instead of the data dict, enabling read-modify-write workflows such as the speakerphone toggle. It takes a full UUID or an 8-char prefix.
    Exact mode (`exact=True`, opt-in) compares full UUIDs only, as in `find_session_by_id`. Callers of an irreversible self-aimed action must use it. self_respin polls this seat's bridge mtime after `/clear`. A prefix collision with another live seat would poll the wrong bridge. It would read that write as reset proven and type the wake into the un-cleared pane.
    The sibling tmux resolver uses exact for the same reason. The default stays prefix-tolerant so the existing caller (speakerphone toggle) is unchanged.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns Path if a match is found
        - Returns None if no match or session_id is empty
        - exact=True: matches only on full-id equality (no prefix fallback)
        - exact=False (default): full-id or 8-char-prefix equality (legacy)
        - Skips bridge files whose PID is dead, unless host pids cannot be trusted (inside a container)
        - Never raises exceptions

    Args:
        session_id: Full session UUID (or, when exact=False, an 8-char prefix) to match
        exact: when True, require a full-id match — no 8-char prefix fallback

    Returns:
        Path or None: Bridge file path on match, or None
    """
    if not session_id or not SESSION_DIR.exists():
        return None

    hit = find_in_bridge_index( iter_live_bridges(), session_id, exact=exact )
    return hit[ 0 ] if hit else None


def iter_live_bridges():
    """
    Yield every live bridge in `SESSION_DIR` as ( path, data, all_ids ), lazily.

    One scan is shared. The sessions directory is mostly not bridges (thousands of cc-listener leftovers beside a few bridges), so a per-id scan is slow. A caller resolving many ids once blocked the dev server.
    Such a caller takes one `build_live_bridge_index()` and matches against it instead.
    It is lazy so that `find_session_path_by_id` stops at the first match and reads only the files before its hit. The skip rules live here once, so they cannot drift between two loops.

    Ensures:
        - skips names containing "buffer" or "listener"
        - skips a cc-{pid}.json whose pid is dead, when host pids can be trusted
        - skips a file that is unreadable or not JSON
        - all_ids = session_ids, then session_id, then stable_session_id, de-duplicated
        - yields in glob order
    """
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

        except ( json.JSONDecodeError, OSError ):
            continue

        yield path, data, all_ids


def build_live_bridge_index():
    """
    Snapshot every live bridge once, for a caller about to resolve many ids.

    Ensures:
        - returns a list of ( path, data, all_ids ), in glob order
        - returns [] when `SESSION_DIR` does not exist
    """
    if not SESSION_DIR.exists():
        return []
    return list( iter_live_bridges() )


def find_in_bridge_index( index, session_id, exact=False ):
    """
    Match a session id against bridges from `iter_live_bridges` / `build_live_bridge_index`.

    The same match rule `find_session_path_by_id` has always used: full-id equality, or,
    unless `exact`, equality of the first 8 characters. The first bridge that matches wins.

    Requires:
        - index is an iterable of ( path, data, all_ids )

    Ensures:
        - returns ( path, data ) for the first matching bridge
        - returns None when session_id is empty or nothing matches
    """
    if not session_id:
        return None
    for path, data, all_ids in index:
        for known_id in all_ids:
            if known_id == session_id or ( not exact and known_id[:8] == session_id[:8] ):
                return path, data
    return None


def _pid_confirmed_dead( pid ):
    """
    Return True only when `pid` is definitively gone (ProcessLookupError on kill -0).

    The bias-to-alive companion to `_is_pid_alive`, which asks whether we can signal the process (EPERM reads as dead); this asks whether the process is confirmed gone.
    A non-int, an EPERM (exists but not ours) or any other OSError returns False, so death is never confirmed on ambiguity. The fleet-status force-offline path uses it, where a false dead would hide a live session.

    Requires:
        - pid is an int or anything else (a non-int is not confirmed dead)

    Ensures:
        - True iff os.kill( pid, 0 ) raises ProcessLookupError
        - False for non-int, alive pid, EPERM, or any other OSError
        - pure (stdlib only); never raises
    """
    if not isinstance( pid, int ):
        return False
    try:
        os.kill( pid, 0 )
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def find_dead_sessions( candidate_ids ):
    """
    Return the subset of `candidate_ids` whose worker process is confirmed dead.

    Unlike `find_session_path_by_id` and `find_active_voice_persona_sessions`, which skip dead-pid bridges and so never surface a dead session, this scans bridges unfiltered and confirms death with kill -0.
    It serves the fleet-status offline override, which drops an exited session in about one poll instead of about an hour. A candidate is dead iff its bridge is found and it carries at least one known pid. The pids are the filename pid, listener_pid and cc_pid, and every one must be `_pid_confirmed_dead`.

    Requires:
        - candidate_ids is an iterable of session-id strings (full uuid or 8-char prefix)

    Ensures:
        - returns a set[str], a subset of the truthy candidate_ids
        - never raises (a bad bridge file is skipped)
        - biased to alive, so it never over-reports death: it returns empty inside a container, where host pids are
          invisible and kill -0 would read the whole fleet as dead
        - a candidate with no readable or matching bridge is not dead, because absence is not death
        - a bridge with no known int pid is not dead, for lack of evidence, and an EPERM or ambiguous kill -0 counts as alive
    """
    if not _can_trust_host_pids() or not SESSION_DIR.exists():
        return set()
    candidates = { c for c in ( candidate_ids or () ) if c }
    if not candidates:
        return set()

    dead = set()
    for path in SESSION_DIR.glob( "cc-*.json" ):
        if "buffer" in path.name or "listener" in path.name:
            continue
        try:
            with open( path ) as f:
                data = json.load( f )
        except ( json.JSONDecodeError, OSError ):
            continue

        all_ids = list( data.get( "session_ids", [] ) )
        for field in ( "session_id", "stable_session_id" ):
            val = data.get( field, "" )
            if val and val not in all_ids:
                all_ids.append( val )

        matched = None
        for known_id in all_ids:
            for cand in candidates:
                if known_id == cand or known_id[ :8 ] == cand[ :8 ]:
                    matched = cand
                    break
            if matched:
                break
        if matched is None:
            continue

        pids = [ p for p in ( _extract_pid_from_filename( path.name ),
                              data.get( "listener_pid" ),
                              data.get( "cc_pid" ) ) if isinstance( p, int ) ]
        if pids and all( _pid_confirmed_dead( p ) for p in pids ):
            dead.add( matched )

    return dead


# ── v2.1 liveness-stamp observability (arbiter design 03 §10.6 rider) ──────────
# A swallowed bridge-touch failure must be DIAGNOSABLE, never silently dropped —
# a dropped stamp would read as false-idle in the arbiter, the exact dishonesty
# the C4 state/liveness split exists to prevent. Two cheap, hot-path-safe
# signals (both fire ONLY on the failure path, never on success):
#   • a monotonic in-memory counter — persists in long-lived processes (the
#     cosa-voice MCP server middleware, the arbiter) for a debug surface to read;
#   • a ONE-SHOT-per-process stderr line — the diagnosable signal for the
#     SHORT-LIVED PostToolUse hook (a fresh process per tool call, so the counter
#     resets each run; the one-shot stderr surfaces a persistent fleet-wide break
#     as one line per failing invocation without per-call spam within a process).
_bridge_touch_failure_count  = 0
_bridge_touch_failure_logged = False


def get_bridge_touch_failure_count() -> int:
    """
    Return the count of swallowed `touch_bridge_mtime()` failures in this process.

    Ensures:
        - returns the count of swallowed touch_bridge_mtime() failures since
          process start (observability rider); meaningful in long-lived
          processes, and it resets per process for the ephemeral hook. Never raises.
    """
    return _bridge_touch_failure_count


def _record_bridge_touch_failure() -> None:
    """
    Record a swallowed liveness-stamp failure (counter plus one-shot stderr).

    Ensures:
        - increments the in-memory failure counter (always)
        - writes a single stderr diagnostic on the first failure of this process
          only (bounded, no per-call spam); subsequent failures count silently
        - never raises (it runs inside touch_bridge_mtime's except and must not
          re-break the no-throw guarantee, so the stderr write is itself guarded)
    """
    global _bridge_touch_failure_count, _bridge_touch_failure_logged
    _bridge_touch_failure_count += 1
    if not _bridge_touch_failure_logged:
        _bridge_touch_failure_logged = True
        try:
            sys.stderr.write(
                "[session_bridge] touch_bridge_mtime liveness stamp dropped "
                "(bridge unreachable); further failures counted, not logged\n"
            )
        except Exception:
            pass


def touch_bridge_mtime() -> bool:
    """
    Bump this session's bridge-file mtime to now, the direct-state liveness stamp.

    It is the one host-side liveness clock. The idle-waiter re-arm, the Stop hook and the cosa-voice server already bump the same bridge mtime, and this tool-use hook is a fourth writer. A heads-down worker therefore refreshes liveness on every tool call. The clock survives a server wedge because the file is written host-side, never through `:7999`.
    See: src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md (sections 10.1 and 10.6)

    Requires:
        - nothing (resolves the current process's own bridge file)

    Ensures:
        - bumps the resolved bridge file's mtime to the current time via
          os.utime( path, None ), metadata-only, no content write
        - returns True if a bridge file was found and successfully touched
        - returns False if no bridge file resolves or the touch fails
        - never raises (a hook must never break a tool call)
        - performs no transcript read, no server POST and no heavy logic, because the PostToolUse hook fires on every tool call. A one-byte content write would also corrupt the bridge JSON.
        - resolves the path through `_find_session_file()`, a single `cc-{ppid}.json` stat in the common PPID-hit case
        - the catch is broad (`Exception`), not only OSError, so it is a no-op on any error. Realistic failures are OSError subtypes: a missing sessions directory, a permission flip, a bridge unlinked mid-touch, or a deleted cwd. No unforeseen error class may propagate out of a tool call.
    """
    try:
        result = _find_session_file()
        if not result:
            return False
        path, _source = result
        os.utime( path, None )
        return True
    except Exception:
        _record_bridge_touch_failure()
        return False


def get_bridge_mtime( session_id ) -> Optional[ float ]:
    """
    Read a session's bridge-file mtime in epoch seconds, looked up by session id.

    It is the arbiter's direct liveness reader and the consumer-side counterpart to `touch_bridge_mtime()`. The fleet render shows liveness as an honest age (`bridge 4s ago`), never an inferred boolean, so state and liveness stay separate columns.
    It resolves the path through `find_session_path_by_id()`. That is heavier than the touch, but it runs about once per session per 60 s poll, well outside the hot hook path.
    See: src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md (sections 10.1 and 10.2)

    Requires:
        - session_id is a string (full UUID or 8-char prefix); empty or None
          yields None

    Ensures:
        - returns the bridge file's mtime in epoch seconds if the session
          resolves to a live bridge file
        - returns None if no bridge file matches or the stat fails
        - never raises (broad catch; the arbiter poll must survive any single
          session's bridge-read failure under live FS conditions)
    """
    try:
        path = find_session_path_by_id( session_id )
        if path is None:
            return None
        return path.stat().st_mtime
    except Exception:
        return None


BRIDGE_FORMAT_VERSION = 2


# Bridge field carrying the IMPLICIT manager-figure answer, resolved at
# registration time and stamped here (bug e5d600bd, Rick's Option A 2026-08-15).
#
# 🔴 WHY A STATIC FIELD AND NOT A SERVER-SIDE COMPUTE. The implicit source of
# is_manager_figure — "is this session's allocated persona one of the repo's
# NAMED standing personas (COSA_VOICE_PREFERRED_PERSONA__<PROJECT>)?" — can ONLY
# be answered where the caller's real environment lives: the SessionStart hook.
# The server (tasks.py:652 G1 guard, and any future v2 experiment stratum
# classifier) runs in the lupin-rest-dev container, whose env carries ZERO
# COSA_VOICE_PREFERRED_PERSONA__* vars and LUPIN_ROOT=/var/lupin — so a
# server-side compute resolved every caller to project "lupin" with an empty
# persona chain and the implicit source was universally dead. register_session
# has the real env; it computes the answer and stamps it here, and the server
# reads this static field instead of trying (and failing) to re-derive it.
#
# Value is a bool (the implicit answer only — the EXPLICIT source, role=="manager",
# is a separate live bridge field is_manager_figure() still checks first). Absent
# on legacy bridges written before this fix; is_manager_figure() falls back to the
# env-based compute for those, so a pre-fix bridge self-heals on its next
# SessionStart re-registration. See src/lupin_cli/.../lib/manager_figure.py.
MANAGER_FIGURE_BRIDGE_FIELD = "manager_figure_implicit"


def _get_default_speakerphone():
    """
    Return the mode-aware default for `speakerphone_on` when a bridge has no explicit field.

    That is a v1 bridge from before the speakerphone rename, or a fresh bridge that `set_speakerphone` has not touched. Solo mode gives False (sessions opt in to TTS render) and chorus mode gives True (at-distance is the default).
    The `cosa.utils.util` import is deferred to avoid circular-import risk and to keep the function free of import-time side effects. Any error returns False, the solo default.
    """
    try:
        from cosa.utils import util as cu
        return cu.get_tts_interaction_mode() == "chorus"
    except Exception:
        return False  # solo default if anything blows up


def find_active_speakerphone_sessions( exclude_session_id=None ):
    """
    Scan all bridge files for sessions whose speakerphone_on is true.

    The speakerphone HTTP endpoint's solo branch uses it to enforce at most one active speakerphone session at a time. When a session activates, all other active sessions are deactivated atomically. Chorus mode never invokes this scan.
    It honors the same staleness filtering as `find_session_path_by_id`. It skips buffer and listener files. It also skips bridges whose host PID is dead when host PIDs are trustworthy (see `_can_trust_host_pids`).

    Requires:
        - exclude_session_id is None or a non-empty string

    Ensures:
        - Returns a list of (Path, session_id) tuples for every bridge with
          speakerphone_on=true (never None; empty list if none)
        - When exclude_session_id is provided, bridges matching that id
          (full UUID or 8-char prefix, mirroring find_session_path_by_id)
          are not included in the returned list
        - session_id in each tuple is the canonical id from the bridge file
          (prefers stable_session_id, falls back to session_id)
        - Never raises exceptions
        - Skips bridge files that fail to parse or open
        - v1 bridges (without `speakerphone_on` field) treated as inactive
          (no destructive discard; the upgrade to v2 happens on write)

    Args:
        exclude_session_id: Optional session id (full UUID or 8-char prefix)
            to exclude from results, typically the session that is about to
            be activated, so it is not displaced by its own enable call

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
    Read the `speakerphone_on` flag from the bridge file for a given session_id.

    Speakerphone mode is the per-session toggle that makes Claude auto-call notify(full_text, suppress_ding=True) after every assistant turn when it is True.
    The default when the bridge has no `speakerphone_on` field is mode-aware: False in solo mode (monopoly behavior), True in chorus mode (at-distance default). See `_get_default_speakerphone`.

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
    Write the `speakerphone_on` flag to the bridge file for a given session_id.

    Read-modify-write of the bridge JSON, preserving all other fields and stamping `format_version=2` for future schema evolution. It does not create a missing bridge: the bridge must already exist (created by the SessionStart hook).
    A v1 bridge (with `conversation_mode_active` but no `speakerphone_on`) gains `speakerphone_on` and `format_version` on the first call. The stale `conversation_mode_active` key is removed in the same write to avoid two sources of truth.

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
        return atomic_write_json( path, data )
    except ( json.JSONDecodeError, OSError ):
        return False


def set_manager_figure_implicit( session_id, flag ):
    """
    Stamp the implicit manager-figure answer onto the bridge.

    Read-modify-write of the bridge JSON to set `MANAGER_FIGURE_BRIDGE_FIELD`, preserving all other fields; it does not create a missing bridge. The SessionStart hook of register_session calls it after voice-persona allocation, using the caller's real environment.
    That is the only place the `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` chain is visible. The server-side is_manager_figure() reads this static field instead of re-deriving it from the container env, where the chain is empty.

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - flag is a bool (the implicit-source answer)

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge not found or write failed
        - Never raises exceptions
        - Preserves all existing fields in the bridge JSON (read-modify-write)

    Args:
        session_id: Session ID to look up
        flag:       Implicit manager-figure answer to stamp

    Returns:
        bool: True on successful write, False otherwise
    """
    path = find_session_path_by_id( session_id )
    if not path:
        return False

    try:
        with open( path ) as f:
            data = json.load( f )
        data[ MANAGER_FIGURE_BRIDGE_FIELD ] = bool( flag )
        return atomic_write_json( path, data )
    except ( json.JSONDecodeError, OSError ):
        return False


def get_last_autonarrated_turn_id( session_id ):
    """
    Read last_autonarrated_turn_id from the bridge file for dedup.

    The Stop-hook auto-narrate uses it to avoid re-narrating the same assistant turn when the Stop hook fires twice on one turn, which can happen.

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
        return atomic_write_json( path, data )
    except ( json.JSONDecodeError, OSError ):
        return False


def set_owner_user_id( session_id, owner_user_id ):
    """
    Write `owner_user_id` to the bridge file for a given session_id.

    The inter-session-commons broadcast surface filters active sessions by `bridge["owner_user_id"] == authenticated_user_id`. A listener calls this setter once at startup from `_stamp_owner_user_id_on_bridge()` in cc_notification_listener.
    It differs from `set_user_id`, which stamps the service-account identity of the listener. This stamps the human owner's identity, which the broadcast UI's same-user filter compares against.
    See: src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - owner_user_id is a non-empty string (canonical user UUID from
          /auth/login response at user.id for the human owner)

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge missing, parse-fail, or write-fail
        - Never raises
        - Preserves all other bridge fields (read-modify-write)

    Args:
        session_id:    Session ID to look up (full UUID or 8-char prefix)
        owner_user_id: Canonical human owner UUID to stamp on the bridge

    Returns:
        bool: True on successful write
    """
    if not session_id or not owner_user_id:
        return False
    path = find_session_path_by_id( session_id )
    if not path:
        return False
    try:
        with open( path ) as f:
            data = json.load( f )
        data[ "owner_user_id" ] = str( owner_user_id )
        return atomic_write_json( path, data )
    except ( json.JSONDecodeError, OSError ):
        return False


def set_user_id( session_id, user_id ):
    """
    Write `user_id` to the bridge file for a given session_id.

    The inter-session-commons broadcast surface filters active sessions by `bridge["user_id"] == authenticated_user_id` (same-user scoping). Without this stamp every bridge fails the filter and the broadcast UI shows no active sessions.
    It pairs with the graceful-degradation fallback in `routers/commons.py`: once the stamp lands, the fallback goes inactive for new bridges and full cross-user isolation applies.
    `cc_notification_listener._stamp_user_id_on_bridge()` calls it once at listener startup, after the user_id is resolved via `/auth/login`.

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
        return atomic_write_json( path, data )
    except ( json.JSONDecodeError, OSError ):
        return False


def get_voice_persona( session_id ):
    """
    Read the voice_persona dict from the bridge file for a given session_id.

    The voice_persona is a per-session voice allocation written by the SessionStart hook, through the /api/cosa-voice/voice-persona/{sid}/allocate endpoint. Each new session gets a voice picked uniformly at random from a 6-voice pool, so the user can tell parallel sessions apart.
    Sam, the global default, is reserved as the system-wide voice for any TTS request lacking a voice_id and is not in the allocatable pool.
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
        return atomic_write_json( path, data )
    except ( json.JSONDecodeError, OSError ):
        return False


def get_idle_detection( session_id ):
    """
    Read the idle_detection block from the bridge file for a given session_id.

    The block tracks per-session state for the deferred "Anything else?" prompt with exponential backoff.
    See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)

    Ensures:
        - Returns the idle_detection dict if the bridge exists and the field is
          a non-empty dict
        - Returns None on any failure (missing bridge, parse error, missing
          field, field is null/empty/non-dict)
        - Never raises exceptions
        - The dict keys are as follows. last_interaction_at is ISO8601 with tz. backoff_index is an int index into settings backoff_minutes. waiter_pid is the int PID of the detached helper, or None. waiter_started_at is ISO8601, set by the waiter on sleep-start.

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

    Read-modify-write: reads the bridge, merges `fields` into the existing idle_detection sub-dict (creating it if absent), and writes back through `atomic_write_json`. Other top-level fields and other idle_detection sub-fields are preserved.
    Two concurrent calls on one bridge can still lose an update, because of the read-modify-write window. That is acceptable here: resets are idempotent, so the worst case is one missed bump that the next event replays.

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
        return atomic_write_json( path, data )
    except ( json.JSONDecodeError, OSError ):
        return False


def clear_idle_waiter_pid( session_id ):
    """
    Clear the waiter_pid field and return the old PID.

    Callers that want to kill the waiter get the PID to SIGTERM. The bridge field is cleared so a concurrent spawn knows the slot is free. The kill itself is the caller's job; see `kill_idle_waiter` for the convenience wrapper.

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
        if not atomic_write_json( path, data ):
            return None
        return int( old_pid ) if isinstance( old_pid, int ) else None
    except ( json.JSONDecodeError, OSError, ValueError ):
        return None


def kill_idle_waiter( session_id, signal=None ):
    """
    Kill any live idle-waiter helper for this session.

    A convenience wrapper: it calls `clear_idle_waiter_pid` to claim the prior PID, then sends SIGTERM (or the supplied signal) to it. PID liveness is checked first, to avoid signaling an unrelated process that inherited the PID.

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

    It runs from the SessionStart hook on the host, where host PIDs are visible. It is a no-op where host PIDs are not trustworthy (inside a container), because pruning there would mark every bridge dead.
    The in-container scan in `find_active_voice_persona_sessions` skips the dead-PID filter. Leftover personas from prior days therefore pile up as occupied and exhaust the allocation pool at day start. A host-side prune at every SessionStart scrubs them before /allocate runs.

    Ensures:
        - Returns 0 when SESSION_DIR doesn't exist, when called from a
          non-host context (_can_trust_host_pids() is False), or when no
          bridges need pruning
        - Bridges with isinstance(voice_persona, dict) == False are left
          untouched (no spurious writes), as are bridges with an empty dict
        - Buffer/listener files (cc-*-buffer.json, cc-*-listener.json) are
          skipped (same convention as find_active_voice_persona_sessions)
        - Returns the count of bridges actually pruned (voice_persona set
          to None)
        - Never raises; per-file errors are swallowed and the next file
          is processed
        - Bridges whose host PID is alive, or whose filename carries no PID, are skipped

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
        if atomic_write_json( path, data ):
            pruned += 1

    return pruned


def _append_stale_bridge( stale_out, path, mtime_age, pid_alive ):
    """
    Record an aged-out bridge in the caller's visibility bucket.

    Requires:
        - stale_out is a list the caller owns
        - mtime_age is the bridge's age in seconds

    Ensures:
        - appends a dict naming the bridge, its age, whether its PID is alive, and
          whether it was kept, so an exclusion is never invisible
        - never raises; a bridge that cannot be read still gets an entry, because a
          silently-dropped unreadable bridge is the same failure this bucket exists
          to prevent

    Raises:
        - nothing
    """
    session_id = None
    try:
        with open( path ) as handle:
            data       = json.load( handle )
        session_id = data.get( "stable_session_id" ) or data.get( "session_id" )
    except ( json.JSONDecodeError, OSError ):
        pass

    stale_out.append( {
        "bridge"        : path.name,
        "session_id"    : session_id,
        "mtime_age_s"   : round( mtime_age, 1 ),
        "mtime_age_h"   : round( mtime_age / 3600.0, 2 ),
        "pid_alive"     : pid_alive,
        # The whole point of the bucket: say which way it went.
        "included"      : pid_alive,
        "why"           : ( "bridge aged out but the PROCESS IS ALIVE — kept, because PID "
                            "liveness outranks mtime (bug 6afc8b3e)" if pid_alive else
                            "bridge aged out and liveness could not be confirmed — excluded" ),
    } )


def find_active_sessions( stale_threshold_seconds: int = 43200, require_persona: bool = True,
                          stale_out=None, unreadable_out=None ):
    """
    Scan all bridge files for live CC sessions, with an optional persona filter.

    The general session-discovery scanner. `find_active_voice_persona_sessions` delegates here with `require_persona=True`, the pool-occupancy view that `/allocate` and `/pool` rely on.
    With `require_persona=False` persona-less live sessions are also returned. A worker booted with an exhausted pool then stays reachable by session_id; otherwise it is a black hole for inbound DMs.

    Requires:
        - stale_threshold_seconds is a positive integer (default 12 hours)

    Ensures:
        - When require_persona is True: returns a (Path, session_id, persona)
          tuple for every live bridge with a non-null voice_persona dict;
          persona is the dict as stored in the bridge.
        - When require_persona is False: also returns live persona-less
          bridges, with persona projected to `{}` so consumers that call p.get( ... ) stay safe.
        - session_id is the canonical id (stable_session_id preferred)
        - Never raises exceptions
        - Skips bridge files that fail to parse or open, but reports them into
          `unreadable_out` when one is supplied, because a live seat we cannot read still occupies a seat
        - Skips bridge files whose stat() fails
        - PID liveness is checked first, when host pids can be trusted: a bridge whose host PID is dead is skipped. Inside a container the check is bypassed.
        - The mtime TTL is a fallback only: a bridge older than `stale_threshold_seconds` is skipped unless its PID is proven alive.
        - PID liveness outranks mtime. An unconditional TTL once hid live but idle seats from every roster, and raising the constant only moves the cliff.
        - A dead-PID bridge, or an aged-out bridge whose liveness cannot be confirmed, is free, and its slot is reclaimed.
        - `stale_out`, a list, receives every aged-out bridge including kept ones, each saying why. A monitor that returns fewer sessions than exist is a monitor that lies.
        - `unreadable_out`, a list, receives the path of every live bridge that could not be identified (unparseable JSON, or no session id).
        - Liveness is decided first, so a dead corrupt bridge appears in neither the results nor `unreadable_out`. An unreadable ghost counted against the fleet cap could never be reaped.

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

        pid_is_alive = False
        if trust_host_pids:
            file_pid = _extract_pid_from_filename( path.name )
            if file_pid is not None and not _is_pid_alive( file_pid ):
                continue
            pid_is_alive = file_pid is not None

        try:
            mtime_age = now - path.stat().st_mtime
        except OSError:
            continue

        # 🔴 PID LIVENESS OUTRANKS mtime (bug 6afc8b3e, Rio). The mtime TTL used to run
        # unconditionally, so a session whose PROCESS IS PROVEN ALIVE vanished from every
        # roster once its bridge went 12h without a rewrite — and the monitor exists to
        # catch exactly the long-lived seat that ages out. Two real seats were invisible
        # for 14h+ while `ps` showed them running.
        #
        # Raising the constant is the DIAGNOSTIC, not the fix: a bigger number only moves
        # the cliff. The TTL keeps its real job — bridges we CANNOT check, i.e. inside a
        # container where host PIDs are invisible, or a filename carrying no PID.
        if mtime_age > stale_threshold_seconds:
            if not pid_is_alive:
                if stale_out is not None:
                    _append_stale_bridge( stale_out, path, mtime_age, pid_alive=False )
                continue
            # Alive but aged out: KEPT, and also surfaced so the anomaly is visible
            # rather than merely survived.
            if stale_out is not None:
                _append_stale_bridge( stale_out, path, mtime_age, pid_alive=True )

        try:
            with open( path ) as f:
                data = json.load( f )

            persona     = data.get( "voice_persona" )
            has_persona = isinstance( persona, dict ) and bool( persona )
            if require_persona and not has_persona:
                continue

            sid = data.get( "stable_session_id" ) or data.get( "session_id" )
            if not sid:
                # Same case as the parse failure below: the file opened, the seat is
                # live, and it cannot be identified. Reported rather than dropped.
                if unreadable_out is not None:
                    unreadable_out.append( path )
                continue

            results.append( ( path, sid, persona if has_persona else {} ) )

        except ( json.JSONDecodeError, OSError ):
            # 🔴 A LIVE SEAT WE CANNOT READ IS NOT AN ABSENT SEAT (row 9c3b817a). This
            # branch used to drop the bridge silently, so a corrupt file made a RUNNING
            # session vanish from every count derived here — including the fleet cap,
            # which then permitted a spawn it should have refused.
            #
            # ⚠️ It is REPORTED, not returned: the tuple has no session id to carry, so
            # inventing one would put a fictional seat into every consumer's list. The
            # caller gets the PATH and decides what the absence is worth. Liveness is
            # already decided above, so a DEAD corrupt bridge never reaches here.
            if unreadable_out is not None:
                unreadable_out.append( path )
            continue

    return results


def find_active_voice_persona_sessions( stale_threshold_seconds: int = 43200 ):
    """
    Scan all bridge files for sessions whose voice_persona is non-null.

    A thin delegate over `find_active_sessions( require_persona=True )`, the persona-required view the voice-persona HTTP endpoints use for pool occupancy. `/allocate` excludes occupied persona names so each session gets a unique voice, and `/pool` returns a diagnostics snapshot.
    The liveness filters and return shape are documented on `find_active_sessions`.

    Returns:
        list[ tuple[ Path, str, dict ] ]: (bridge_path, session_id, persona)
        for every live bridge with a non-null voice_persona dict.
    """
    return find_active_sessions( stale_threshold_seconds=stale_threshold_seconds, require_persona=True )


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
            # Default is mode-aware (solo→False, chorus→True). Round-trip via
            # _get_default_speakerphone rather than hardcoding False so the
            # smoke works regardless of the host's current TTS interaction mode.
            _expected_default = _get_default_speakerphone()
            assert get_speakerphone( _sid ) is _expected_default, (
                f"Default should match _get_default_speakerphone() (got "
                f"{get_speakerphone( _sid )!r}, expected {_expected_default!r})"
            )
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

            # owner_user_id round-trip smoke (Phase 3 of writer-side stamper plan)
            _owner_uuid = "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"  # example human owner UUID
            assert set_owner_user_id( _sid, _owner_uuid ) is True, "Set owner_user_id should succeed"
            with open( _bridge ) as _f:
                _data = json.load( _f )
            assert _data.get( "owner_user_id" ) == _owner_uuid, "Round-trip owner_user_id equals original"
            assert set_owner_user_id( _sid, "0cf47e2d-DIFFERENT" ) is True, "Overwrite should succeed"
            with open( _bridge ) as _f:
                _data = json.load( _f )
            assert _data.get( "owner_user_id" ) == "0cf47e2d-DIFFERENT", "Overwrite reads back new value"
            assert set_owner_user_id( "nonexistent", _owner_uuid ) is False, "Missing bridge returns False"
            assert set_owner_user_id( _sid, "" ) is False, "Empty owner_user_id returns False"
            assert set_owner_user_id( "", _owner_uuid ) is False, "Empty session_id returns False"
            print( "Owner user_id smoke: ✓ all assertions passed" )
        finally:
            globals()[ "SESSION_DIR" ] = _orig_dir
