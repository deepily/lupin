"""
Idle-aware Stop hook deferred-ask helper.

Spawned as a detached background subprocess by the Stop hook (and
respawned by itself on "no" response). Sleeps for `backoff_minutes[index]`
minutes, then re-checks the bridge file for reset signals. If still idle,
fires the "Anything else?" ask via the shared helper. On "no"/timeout,
spawns a successor at the next backoff index (capped at the schedule's
last entry).

Design: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md

Invocation:
    python -m lupin_cli.claude_code.hooks.lib.idle_waiter \\
        --session-id  <session-id> \\
        --ppid        <claude-code-ppid> \\
        --backoff-index <int>

Test mode (override sleep duration for smoke tests):
    LUPIN_IDLE_WAITER_TEST_SLEEP_SECS=5 python -m ...
    OR --sleep-secs 5 (CLI flag wins over env)
"""

import argparse
import datetime
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_lupin_root = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_src_path   = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.session_bridge import (
    find_session_path_by_id, get_idle_detection, set_idle_detection_field,
    get_conversation_mode,
)
from lupin_cli.claude_code.hooks.lib.idle_settings import load_idle_settings
from lupin_cli.claude_code.hooks.lib.anything_else_ask import (
    fire_anything_else_ask, AnythingElseResult,
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_DIR = Path( os.path.expanduser( "~/.claude/sessions" ) )


def _log( session_id: str, msg: str ) -> None:
    """
    Append a timestamped line to the per-session waiter log.

    Best-effort — never raises. Two log files: per-session at
    cc-idle-waiter-{short_id}.log, plus a centralized cc-idle-waiters.log.
    """
    short    = session_id[ :8 ] if session_id else "unknown"
    ts       = datetime.datetime.now().astimezone().isoformat( timespec="seconds" )
    line     = f"[{ts}] [pid={os.getpid()}] {msg}\n"
    per_path = _LOG_DIR / f"cc-idle-waiter-{short}.log"
    cen_path = _LOG_DIR / "cc-idle-waiters.log"

    for path in ( per_path, cen_path ):
        try:
            with open( path, "a" ) as f:
                f.write( line )
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Wall-clock ISO8601 with timezone offset."""
    return datetime.datetime.now().astimezone().isoformat( timespec="seconds" )


def _is_pid_alive( pid: int ) -> bool:
    """Return True iff `pid` is alive and signalable from this process."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill( pid, 0 )
        return True
    except ( ProcessLookupError, PermissionError ):
        return False
    except OSError:
        return False


def _claim_waiter_slot( session_id: str ) -> bool:
    """
    Atomically claim the bridge waiter_pid slot for this process.

    Returns True if we got the slot (no other waiter was registered, OR the
    registered one was dead). Returns False if a live waiter already holds
    the slot — the caller should exit immediately to avoid double-prompts.
    """
    state    = get_idle_detection( session_id ) or { }
    prior    = state.get( "waiter_pid" )

    if prior is not None and _is_pid_alive( int( prior ) ):
        _log( session_id, f"slot held by live pid={prior}; aborting spawn" )
        return False

    set_idle_detection_field(
        session_id,
        waiter_pid        = os.getpid(),
        waiter_started_at = _now_iso(),
    )
    return True


def _release_waiter_slot( session_id: str ) -> None:
    """Clear our PID from the bridge if we still own it. Best-effort."""
    state = get_idle_detection( session_id ) or { }
    if state.get( "waiter_pid" ) == os.getpid():
        set_idle_detection_field( session_id, waiter_pid=None )


def _was_reset_during_sleep( session_id: str, started_at_iso: str ) -> bool:
    """
    Return True if `last_interaction_at` advanced past our sleep-start.

    A reset means a hook (UserPromptSubmit, Stop, PostToolUse cosa-voice) ran
    while we were sleeping and bumped the timestamp — we should exit silently
    rather than fire a phantom prompt.
    """
    state = get_idle_detection( session_id ) or { }
    last  = state.get( "last_interaction_at" )
    if not last:
        return False
    try:
        last_dt    = datetime.datetime.fromisoformat( last )
        started_dt = datetime.datetime.fromisoformat( started_at_iso )
    except ValueError:
        return False
    return last_dt > started_dt


def _spawn_successor( session_id: str, ppid: int, backoff_index: int, sleep_secs_override: int = None ) -> int:
    """
    Spawn a successor idle_waiter at the next backoff index (detached).

    Mirrors the `_spawn_listener` pattern from register_session.py: detached
    subprocess with start_new_session=True, stdout/stderr redirected to log
    files, PID returned (caller stores it on the bridge).
    """
    short    = session_id[ :8 ] if session_id else "unknown"
    log_path = _LOG_DIR / f"cc-idle-waiter-{short}.log"
    cmd      = [
        sys.executable, "-m", "lupin_cli.claude_code.hooks.lib.idle_waiter",
        "--session-id"   , session_id,
        "--ppid"         , str( ppid ),
        "--backoff-index", str( backoff_index ),
    ]
    if sleep_secs_override is not None:
        cmd.extend( [ "--sleep-secs", str( sleep_secs_override ) ] )

    env = os.environ.copy()
    env[ "PYTHONUNBUFFERED" ] = "1"
    if _src_path and _src_path not in env.get( "PYTHONPATH", "" ):
        env[ "PYTHONPATH" ] = _src_path + ":" + env.get( "PYTHONPATH", "" )

    try:
        log_file = open( log_path, "a" )
    except OSError:
        log_file = subprocess.DEVNULL

    proc = subprocess.Popen(
        cmd,
        stdout            = log_file if log_file is not subprocess.DEVNULL else subprocess.DEVNULL,
        stderr            = log_file if log_file is not subprocess.DEVNULL else subprocess.DEVNULL,
        env               = env,
        start_new_session = True,
    )
    return proc.pid


# ---------------------------------------------------------------------------
# Main waiter loop
# ---------------------------------------------------------------------------

def run_waiter(
    session_id    : str,
    ppid          : int,
    backoff_index : int,
    sleep_secs_override : int = None,
) -> None:
    """
    Top-level waiter execution. Exits cleanly on every termination path.

    1. Validate session bridge exists; if not, exit (session ended).
    2. Atomically claim waiter_pid slot. If lost, exit.
    3. Compute sleep duration from settings (or override for tests).
    4. Sleep in 30-second chunks, polling PPID liveness.
    5. On wake: re-check reset signals + conv mode + PPID.
    6. If clear to fire: invoke fire_anything_else_ask.
    7. Branch on response → exit / spawn successor.
    """
    settings = load_idle_settings()
    schedule = settings[ "backoff_minutes" ]

    # Clamp backoff_index to schedule range
    capped_index = min( backoff_index, len( schedule ) - 1 )
    sleep_secs   = sleep_secs_override if sleep_secs_override is not None else schedule[ capped_index ] * 60

    bridge_path = find_session_path_by_id( session_id )
    if bridge_path is None:
        _log( session_id, "bridge file gone; exiting" )
        return

    if not _claim_waiter_slot( session_id ):
        return

    try:
        state          = get_idle_detection( session_id ) or { }
        started_at_iso = state.get( "waiter_started_at" )
        if not started_at_iso:
            # Should be set by _claim_waiter_slot — if absent, abort cleanly
            _log( session_id, "no waiter_started_at on bridge; aborting" )
            return

        _log( session_id, f"sleep {sleep_secs}s (backoff_index={capped_index} schedule={schedule})" )

        # Chunked sleep — wake periodically to check PPID liveness so a dead
        # CC parent doesn't keep a stale waiter alive for the full schedule.
        elapsed = 0
        chunk   = 30
        while elapsed < sleep_secs:
            time.sleep( min( chunk, sleep_secs - elapsed ) )
            elapsed += chunk

            if not _is_pid_alive( ppid ):
                _log( session_id, f"ppid {ppid} dead during sleep; exiting" )
                return

        # Wake-time predicates
        if _was_reset_during_sleep( session_id, started_at_iso ):
            _log( session_id, "reset detected during sleep; exiting" )
            return

        if get_conversation_mode( session_id ):
            _log( session_id, "conversation mode active; exiting" )
            return

        if find_session_path_by_id( session_id ) is None:
            _log( session_id, "bridge file gone at wake; exiting" )
            return

        # Fire the ask
        gist   = state.get( "last_task_gist" )
        cwd    = os.environ.get( "CC_HOOK_CWD" ) or os.getcwd()
        result = fire_anything_else_ask(
            session_id      = session_id,
            gist            = gist,
            cwd             = cwd,
            timeout_seconds = 60,
        )

        _log( session_id, f"ask result: answer={result.answer!r} qualifier={result.qualifier!r} error={result.error!r}" )

        if result.answer == "error":
            # Don't reschedule on transport errors — next user activity
            # will respawn the chain. No retry storm.
            return

        # Inject qualifier (with or without "yes") if present
        if result.qualifier:
            try:
                from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux
                inject_qualifier_via_tmux( session_id, result.qualifier )
                _log( session_id, f"injected qualifier via tmux: {result.qualifier!r}" )
            except Exception as e:
                _log( session_id, f"qualifier inject failed: {e}" )

        if result.answer == "yes":
            # User wants to continue — they'll provide input via tmux/voice;
            # UserPromptSubmit will fire and reset backoff_index. We just exit.
            return

        # answer is "no" or "timeout" — schedule successor at next index
        next_index = min( capped_index + 1, len( schedule ) - 1 )
        set_idle_detection_field( session_id, backoff_index=next_index )

        # Release our slot BEFORE spawning successor (so the successor's
        # _claim_waiter_slot doesn't see us as a stale incumbent)
        _release_waiter_slot( session_id )

        succ_pid = _spawn_successor( session_id, ppid, next_index, sleep_secs_override )

        # Successor will set its own waiter_pid via _claim_waiter_slot
        _log( session_id, f"spawned successor pid={succ_pid} at backoff_index={next_index}" )

    finally:
        # Best-effort slot release on any exit path (covers exceptions, normal
        # exits where successor wasn't spawned, etc.)
        _release_waiter_slot( session_id )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser( prog="idle_waiter", description="Idle-aware Stop hook deferred ask" )
    parser.add_argument( "--session-id"   , required=True, help="CC session ID" )
    parser.add_argument( "--ppid"         , required=True, type=int, help="CC parent process ID" )
    parser.add_argument( "--backoff-index", required=True, type=int, help="Index into settings backoff_minutes" )
    parser.add_argument( "--sleep-secs"   , type=int, default=None, help="Override sleep duration in seconds (test mode)" )
    args = parser.parse_args()

    # Test-mode override via env if --sleep-secs not supplied
    sleep_override = args.sleep_secs
    if sleep_override is None:
        env_val = os.environ.get( "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS" )
        if env_val:
            try:
                sleep_override = int( env_val )
            except ValueError:
                pass

    # Ignore SIGTERM gracefully — caller wants us dead, just exit cleanly
    def _on_term( signum, frame ):
        _log( args.session_id, f"received signal {signum}; exiting" )
        # _release_waiter_slot best-effort via finally in run_waiter
        sys.exit( 0 )

    signal.signal( signal.SIGTERM, _on_term )
    signal.signal( signal.SIGINT,  _on_term )

    _log( args.session_id, f"start backoff_index={args.backoff_index} ppid={args.ppid} sleep_override={sleep_override}" )

    try:
        run_waiter(
            session_id          = args.session_id,
            ppid                = args.ppid,
            backoff_index       = args.backoff_index,
            sleep_secs_override = sleep_override,
        )
    except Exception as e:
        _log( args.session_id, f"unhandled exception: {e!r}" )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit( main() )
