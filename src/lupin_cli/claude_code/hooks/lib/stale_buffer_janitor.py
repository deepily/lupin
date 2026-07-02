#!/usr/bin/env python3
"""
Stale cc-buffer janitor — bug 59f355e0 follow-up (task 18603e57).

The store-backed DM inbox reconcile (dm_inbox_reconcile.py, commit 4cfc9ddc)
stops FUTURE peer-DM orphans, but pre-existing orphans already sit undrained in
~/.claude/sessions/cc-buffer-*.jsonl files owned by DEAD sessions (84 across 46
files at triage). This janitor ARCHIVES those stale files — it does NOT delete
and NEVER replays a DM into any session.

Doctrine (Mr. Radio ruling 2026-07-02):
    - DRY-RUN by DEFAULT: list what WOULD move, move nothing. --apply is a
      SEPARATE, explicitly-granted go (dry-run-before-destructive).
    - REVERSIBLE: --apply MOVEs stale files to a quarantine dir (never `rm`).
    - BIAS-TO-KEEP: a buffer is archived ONLY when its owning session is
      definitively NOT live (no running listener AND no fresh/pid-live bridge)
      AND the file is older than a grace window. Any ambiguity keeps it.
    - NO REPLAY: this is archival only — orphaned DMs are never re-injected.

Design authority: src/rnd/v0.1.9/2026.07.02-dm-loss-surfacing-leg-triage.md
(Orphan inventory + proposed janitor sweep).

    python -m lupin_cli.claude_code.hooks.lib.stale_buffer_janitor            # DRY-RUN
    python -m lupin_cli.claude_code.hooks.lib.stale_buffer_janitor --apply    # MOVE (separate go)
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

BUFFER_GLOB              = "cc-buffer-*.jsonl"
BRIDGE_GLOB              = "cc-*.json"
QUARANTINE_DIRNAME       = "cc-buffer-quarantine"
DEFAULT_MIN_AGE_HOURS    = 1.0        # grace window — never sweep a just-orphaned buffer
DEFAULT_BRIDGE_FRESH_SEC = 43200      # 12h; matches session_bridge.find_active_sessions default
_BUFFER_NAME_RE          = re.compile( r"^cc-buffer-([^.]+)\.jsonl$" )
_SESSION_ID_ARG_RE       = re.compile( r"--session-id\s+([A-Za-z0-9]+)" )


# ── Pure helpers ──────────────────────────────────────────────────────────────

def parse_hash_from_buffer_name( name ):
    """Return the 8-char session hash from a 'cc-buffer-<hash>.jsonl' name, else None."""
    m = _BUFFER_NAME_RE.match( name or "" )
    return m.group( 1 ) if m else None


def parse_listener_hashes( ps_output ):
    """
    Extract the set of session hashes from `ps`-style listener process lines.

    Each running cc_notification_listener carries `--session-id <hash>`; a line
    without that flag (e.g. the grep itself) contributes nothing.
    """
    return set( _SESSION_ID_ARG_RE.findall( ps_output or "" ) )


def count_buffer_lines( text ):
    """
    Count ( total_valid_rows, ai_to_ai_rows ) in a JSONL buffer's text.

    Blank lines and malformed JSON are skipped (mirrors drain_voice_buffer's
    lenient read). Pure — no IO.
    """
    total = 0
    ai    = 0
    for line in ( text or "" ).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads( line )
        except json.JSONDecodeError:
            continue
        total += 1
        if isinstance( row, dict ) and row.get( "direction" ) == "ai_to_ai":
            ai += 1
    return total, ai


def classify_buffer( meta, live_hashes, now_epoch, min_age_hours ):
    """
    Classify ONE buffer as archive-eligible ('dead') or keep, with a reason.

    BIAS-TO-KEEP: dead is True ONLY when the session hash is NOT in live_hashes
    AND the file's age >= min_age_hours (a dead-but-just-orphaned buffer is kept
    through the grace window). Everything else is kept.

    Requires:
        - meta: {hash8, path, total, ai_to_ai, mtime_epoch}
        - live_hashes: set of definitively-live 8-char hashes
        - now_epoch: reference time; min_age_hours: grace window

    Ensures:
        - Returns meta + {age_hours, dead: bool, reason}
    """
    age_hours = max( 0.0, ( now_epoch - meta[ "mtime_epoch" ] ) / 3600.0 )
    hash8     = meta[ "hash8" ]

    if hash8 in live_hashes:
        dead, reason = False, "KEEP: session live (running listener / fresh bridge)"
    elif age_hours < min_age_hours:
        dead, reason = False, f"KEEP: too recent (age {age_hours:.1f}h < {min_age_hours}h grace)"
    else:
        dead, reason = True, f"ARCHIVE: session dead (not in live-set), age {age_hours / 24:.1f}d"

    return { **meta, "age_hours": age_hours, "dead": dead, "reason": reason }


def build_plan( classified ):
    """Partition classified buffers into {'archive': [...dead...], 'keep': [...]}."""
    archive = [ c for c in classified if c[ "dead" ] ]
    keep    = [ c for c in classified if not c[ "dead" ] ]
    return { "archive": archive, "keep": keep }


def plan_move_dst( src_path, quarantine_dir ):
    """Compute the quarantine destination path for a src buffer (keeps basename)."""
    return Path( quarantine_dir ) / Path( src_path ).name


def format_report( plan, apply, quarantine_dir ):
    """
    Render a human-readable inventory report of the plan.

    Lists every archive candidate (dead-session proof + counts) and every kept
    file (reason). The header states DRY-RUN vs APPLY so the mode is unmistakable.
    """
    archive = plan[ "archive" ]
    keep    = plan[ "keep" ]
    dm_total = sum( c[ "ai_to_ai" ] for c in archive )

    mode = "APPLY (moving)" if apply else "DRY-RUN (no changes)"
    verb = "MOVED" if apply else "WOULD MOVE"
    lines = [
        f"=== stale cc-buffer janitor — {mode} ===",
        f"quarantine dir : {quarantine_dir}",
        f"{verb}: {len( archive )} file(s), {dm_total} orphaned ai_to_ai DM(s)",
        f"kept          : {len( keep )} file(s) (live or within grace window)",
        "",
    ]
    if archive:
        lines.append( f"--- {verb} ({len( archive )}) ---" )
        for c in archive:
            lines.append(
                f"  {c[ 'hash8' ]}  lines={c[ 'total' ]} dm={c[ 'ai_to_ai' ]} "
                f"age={c[ 'age_hours' ] / 24:.1f}d  {c[ 'reason' ]}"
            )
        lines.append( "" )
    if keep:
        lines.append( f"--- KEPT ({len( keep )}) ---" )
        for c in keep:
            lines.append( f"  {c[ 'hash8' ]}  {c[ 'reason' ]}" )
    return "\n".join( lines )


# ── IO shell ──────────────────────────────────────────────────────────────────

def is_pid_alive( pid ):
    """True iff `pid` is a live process (os.kill sig 0). Non-positive/bogus → False."""
    try:
        pid = int( pid )
    except ( TypeError, ValueError ):
        return False
    if pid <= 0:
        return False
    try:
        os.kill( pid, 0 )
    except ( ProcessLookupError, OverflowError ):
        return False
    except PermissionError:
        return True                                        # exists, not ours → alive
    return True


def list_listener_hashes( run_fn=None ):
    """
    Set of session hashes with a RUNNING cc_notification_listener process.

    run_fn (injectable) returns the raw `ps`-style output; the default shells out
    to `ps` and greps. Propagates errors to the caller so run() can BIAS-TO-KEEP
    (a failed live-scan must never let a live session's buffer be swept).
    """
    if run_fn is None:
        def run_fn():
            import subprocess
            out = subprocess.run(
                [ "ps", "-eo", "args" ], capture_output=True, text=True, timeout=10
            ).stdout
            return "\n".join( l for l in out.splitlines() if "cc_notification_listener" in l )
    return parse_listener_hashes( run_fn() )


def list_bridge_live_hashes( sessions_dir, now_epoch, fresh_seconds, is_pid_alive=is_pid_alive ):
    """
    Set of session hashes considered live from the bridge files: a bridge counts
    as live when its file mtime is fresh (< fresh_seconds) OR its listener_pid is
    a running process. Both session_id and stable_session_id (8-char) are added.

    BIAS-TO-KEEP: a malformed / unreadable bridge is skipped (contributes no
    'dead' signal — the buffer stays keepable unless positively dead elsewhere).
    """
    live = set()
    base = Path( sessions_dir )
    if not base.exists():
        return live
    for bridge in base.glob( BRIDGE_GLOB ):
        try:
            mtime = bridge.stat().st_mtime
            data  = json.loads( bridge.read_text() )
        except ( OSError, json.JSONDecodeError ):
            continue
        if not isinstance( data, dict ):
            continue
        fresh    = ( now_epoch - mtime ) < fresh_seconds
        pid      = data.get( "listener_pid" )
        pid_live = pid is not None and is_pid_alive( pid )
        if fresh or pid_live:
            for key in ( "session_id", "stable_session_id" ):
                val = data.get( key )
                if isinstance( val, str ) and val:
                    live.add( val[ :8 ] )
    return live


def collect_live_hashes( sessions_dir, now_epoch, fresh_seconds=DEFAULT_BRIDGE_FRESH_SEC ):
    """
    Union of live hashes from running listeners AND live bridges — the widest
    possible live-set (BIAS-TO-KEEP). Raises if the listener scan fails, so run()
    aborts rather than sweep against an incomplete live-set.
    """
    listeners = list_listener_hashes()
    bridges   = list_bridge_live_hashes( sessions_dir, now_epoch, fresh_seconds )
    return listeners | bridges


def gather_buffer_meta( path, now_epoch ):
    """
    Read one buffer file into a classify()-ready meta dict. An unreadable file
    still yields a meta (counts 0) so it remains classifiable (never crashes the
    sweep). mtime falls back to now_epoch (→ within grace → kept) on stat error.
    """
    p = Path( path )
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = now_epoch
    try:
        text = p.read_text()
    except OSError:
        text = ""
    total, ai = count_buffer_lines( text )
    return {
        "hash8"       : parse_hash_from_buffer_name( p.name ),
        "path"        : str( p ),
        "total"       : total,
        "ai_to_ai"    : ai,
        "mtime_epoch" : mtime,
    }


def run( sessions_dir, quarantine_dir=None, apply=False, now_epoch=None,
         live_hashes=None, min_age_hours=DEFAULT_MIN_AGE_HOURS, move_fn=None ):
    """
    Scan `sessions_dir` for cc-buffer files, classify each (BIAS-TO-KEEP), and
    (only when apply=True) MOVE the dead ones to the quarantine dir.

    Requires:
        - sessions_dir: dir holding cc-buffer-*.jsonl
        - now_epoch: reference time (defaults to real now)
        - live_hashes: injected live-set, or None → collect_live_hashes()
        - move_fn(src, dst): injectable mover (default shutil.move) for testing

    Ensures:
        - DRY-RUN (apply=False) MOVES NOTHING (moved == [])
        - apply=True moves ONLY dead-classified files, into quarantine (reversible)
        - Returns {plan, report, moved:[dst,...]}
    """
    base = Path( sessions_dir )
    if now_epoch is None:
        now_epoch = __import__( "time" ).time()
    if quarantine_dir is None:
        quarantine_dir = base / QUARANTINE_DIRNAME
    if live_hashes is None:
        live_hashes = collect_live_hashes( base, now_epoch )
    if move_fn is None:
        move_fn = shutil.move

    classified = []
    for buf in sorted( base.glob( BUFFER_GLOB ) ):
        meta = gather_buffer_meta( str( buf ), now_epoch )
        classified.append( classify_buffer( meta, live_hashes, now_epoch, min_age_hours ) )

    plan  = build_plan( classified )
    moved = []
    if apply and plan[ "archive" ]:
        Path( quarantine_dir ).mkdir( parents=True, exist_ok=True )
        for c in plan[ "archive" ]:
            dst = plan_move_dst( c[ "path" ], quarantine_dir )
            move_fn( c[ "path" ], str( dst ) )
            moved.append( str( dst ) )

    report = format_report( plan, apply, quarantine_dir )
    return { "plan": plan, "report": report, "moved": moved }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main( argv=None ):
    """CLI entry: DRY-RUN by default; --apply performs reversible MOVEs."""
    parser = argparse.ArgumentParser(
        description = "Archive stale cc-buffer files from DEAD sessions (dry-run by default; "
                      "--apply MOVEs reversibly to a quarantine dir; never deletes, never replays)."
    )
    parser.add_argument( "--sessions-dir",
                         default = str( Path.home() / ".claude" / "sessions" ),
                         help    = "Dir holding cc-buffer-*.jsonl (default: ~/.claude/sessions)" )
    parser.add_argument( "--quarantine-dir", default=None,
                         help = "Move target for --apply (default: <sessions-dir>/cc-buffer-quarantine)" )
    parser.add_argument( "--apply", action="store_true",
                         help = "Perform the MOVEs (default: dry-run — list only)" )
    parser.add_argument( "--min-age-hours", type=float, default=DEFAULT_MIN_AGE_HOURS,
                         help = f"Grace window; never sweep newer files (default: {DEFAULT_MIN_AGE_HOURS})" )
    parser.add_argument( "--now-epoch", type=float, default=None,
                         help = "Override reference time (test seam)" )
    args = parser.parse_args( argv )

    result = run(
        sessions_dir   = args.sessions_dir,
        quarantine_dir = args.quarantine_dir,
        apply          = args.apply,
        now_epoch      = args.now_epoch,
        min_age_hours  = args.min_age_hours,
    )
    print( result[ "report" ] )
    return 0


if __name__ == "__main__":                                # pragma: no cover - CLI dispatch
    sys.exit( main() )
