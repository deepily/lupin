#!/usr/bin/env python3
"""
Report peer DMs that were accepted, buffered, and never delivered to anyone.

WHAT THIS EXISTS FOR (row 298af249). When a session is busy the notification
listener appends inbound messages to a per-session JSONL buffer, and a hook
drains that buffer on the session's next turn. If the session ENDS before any
hook drains it, the messages simply stay on disk. Nobody is told: the sender
already received `dispatched: true`, and the recipient never existed long enough
to notice an absence.

MEASURED 2026-08-30: 45 buffer files were holding 67 such messages, the oldest
last written 2026-07-02 — nine weeks of mail nobody will ever read, invisible at
both ends.

THIS REPORTS, IT DOES NOT DELETE. The file on disk is the only surviving copy of
what a sender said, so a sweeper that tidied it away would convert a findable
loss into a permanent one — the same trade this row exists to argue against.
Finding an orphan is this script's job; deciding its fate is a person's.

Usage:
    python3 src/scripts/report-orphaned-dm-buffers.py
    python3 src/scripts/report-orphaned-dm-buffers.py --min-age-hours 24
    python3 src/scripts/report-orphaned-dm-buffers.py --json

Exit codes:
    0  no orphaned messages found
    1  orphaned messages found
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


# 🔴 RESOLVE THE SESSIONS DIR THROUGH THE SEAM, NEVER BY HAND (row 8ccc20ab).
# The first cut of this script built the path from the home directory by hand,
# which reads the REAL fleet directory even when a test has redirected the seam —
# so a test could report on, or deposit into, live sessions. `sessions_dir()`
# honours LUPIN_HOOK_SESSIONS_DIR and falls back to the identical default, so
# production behaviour is unchanged and the lever actually works.
#
# (The guard that caught this matches on TEXT, so it flagged an earlier version of
# this very comment for quoting the expression it forbids. It cannot tell a use
# from a mention — worth knowing before assuming a hit is a real one.)
# DELIBERATE DEPARTURE from the LUPIN_ROOT bootstrap the other eight scripts in
# this directory use (CLAUDE.md § PATH MANAGEMENT). Resolving from __file__ is
# safer HERE: run from a worktree while LUPIN_ROOT still names the main repo, the
# prescribed pattern would import the MAIN repo's sessions_dir — the wrong-tree
# hazard CLAUDE.md spends a section on. Noted so nobody "corrects" it back.
_SRC = Path( __file__ ).resolve().parents[ 1 ]
if str( _SRC ) not in sys.path:
    sys.path.insert( 0, str( _SRC ) )

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir


def read_buffer( path ):
    """
    Read one buffer file into a list of message dicts.

    Requires:
        - path is a Path to a JSONL buffer file

    Ensures:
        - returns a list of dicts, one per parseable line
        - a malformed line is SKIPPED, never fatal — one bad line must not hide
          the readable messages sitting beside it in the same file
        - returns [] if the file cannot be read at all
        - never raises

    Args:
        path: Path to a cc-buffer-*.jsonl file

    Returns:
        list[dict]: the parsed entries
    """
    entries = []
    try:
        with open( path, errors="replace" ) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append( json.loads( line ) )
                except ValueError:
                    continue
    except OSError:
        return []
    return entries


LIVE_THRESHOLD_SECONDS = 600.0


def is_session_live( session_hash, session_dir, now=None, threshold=LIVE_THRESHOLD_SECONDS ):
    """
    Decide whether the session owning a buffer is still running.

    A buffer belonging to a LIVE session is NOT an orphan — it is mail waiting for
    the next turn, which is the mechanism working. Only a buffer whose owner is
    gone holds messages nobody will ever read.

    🔴 THE FIRST VERSION OF THIS CHECK COULD ONLY EVER SAY "LIVE", and running it
    is the only reason that is not still true. It tested for the presence of
    `cc-listener-<hash>.spawn-lock`. Measured: that file is EMPTY, carries no pid,
    and survives the session that made it — **44 of 45 dead sessions still had
    one**. The report came back "1 orphaned message" against a true 67, and it
    looked like good news. An instrument whose signal is always present cannot
    fail, and its clean answer is worth nothing.

    What replaced it is FRESHNESS, not presence, over either of the two files a
    live seat actually touches — its spawn bridge or its listener log. Both are
    checked because neither alone covers every seat: a session spawned by a
    manager has a bridge, and a session started another way has only the log.

    Requires:
        - session_hash is the 8-char id from the buffer filename
        - session_dir is a Path
        - now is epoch seconds or None (None -> read the clock)
        - threshold is seconds of staleness tolerated

    Ensures:
        - returns True when a spawn bridge OR a listener log for that session was
          modified within `threshold` seconds
        - returns False when both are absent or both are stale
        - never raises

    Args:
        session_hash: 8-char session id
        session_dir: directory holding the session files
        now: clock seam
        threshold: seconds within which a touched file counts as live

    Returns:
        bool: True when the owning session still appears to be running
    """
    now = time.time() if now is None else now
    for pattern in ( f"spawned-{session_hash}*.json", f"cc-listener-{session_hash}.log" ):
        try:
            for candidate in session_dir.glob( pattern ):
                if ( now - os.path.getmtime( candidate ) ) < threshold:
                    return True
        except OSError:
            continue
    return False


def collect_orphans( session_dir=None, min_age_hours=0.0, now_fn=time.time ):
    """
    Find every buffered message whose owning session is gone.

    Requires:
        - session_dir is a Path or None (None -> ~/.claude/sessions)
        - min_age_hours is a non-negative float
        - now_fn is a 0-arg callable returning epoch seconds

    Ensures:
        - returns one record per orphaned BUFFER carrying session, path, message
          count, age in hours and the distinct senders stranded there
        - a buffer owned by a LIVE session is excluded — in-flight, not lost
        - an EMPTY buffer file is excluded: nothing is stranded in it, and
          counting it would inflate the total with files holding no message
        - returns [] when the directory does not exist
        - never raises

    Args:
        session_dir: where the buffers live
        min_age_hours: ignore buffers touched more recently than this
        now_fn: clock seam

    Returns:
        list[dict]: the orphan records, youngest first
    """
    session_dir = Path( session_dir ) if session_dir is not None else sessions_dir()
    if not session_dir.is_dir():
        return []

    now     = now_fn()
    orphans = []
    for path in sorted( session_dir.glob( "cc-buffer-*.jsonl" ) ):
        session_hash = path.stem.replace( "cc-buffer-", "" )
        if is_session_live( session_hash, session_dir, now=now ):
            continue
        entries = read_buffer( path )
        if not entries:
            continue
        try:
            age_hours = ( now - os.path.getmtime( path ) ) / 3600.0
        except OSError:
            continue
        if age_hours < min_age_hours:
            continue
        senders = sorted( { str( e.get( "sender_persona" ) or "unknown" ) for e in entries } )
        orphans.append( {
            "session"   : session_hash,
            "path"      : str( path ),
            "messages"  : len( entries ),
            "age_hours" : round( age_hours, 1 ),
            "senders"   : senders,
        } )
    orphans.sort( key=lambda o: o[ "age_hours" ] )
    return orphans


def format_report( orphans ):
    """
    Render the orphan list for a terminal.

    Requires:
        - orphans is the list from collect_orphans

    Ensures:
        - names the TOTAL MESSAGE count, not merely the file count — the file
          count understates the loss, and the number that matters is how many
          messages nobody will read
        - an empty list renders as an explicit all-clear, because silence and
          success must never look alike
        - never raises

    Args:
        orphans: orphan records

    Returns:
        str: the report
    """
    if not orphans:
        return "No orphaned DM buffers — every buffered message belongs to a live session."

    total = sum( o[ "messages" ] for o in orphans )
    lines = [
        f"{total} buffered message(s) across {len( orphans )} dead session(s) were "
        f"accepted and never delivered.",
        "Every sender was told the send succeeded. These files are the only surviving copy.",
        "",
        f"{'SESSION':<10} {'MSGS':>5} {'AGE(h)':>9}  SENDERS",
    ]
    for o in orphans:
        lines.append(
            f"{o[ 'session' ]:<10} {o[ 'messages' ]:>5} {o[ 'age_hours' ]:>9.1f}  "
            f"{', '.join( o[ 'senders' ] )}"
        )
    return "\n".join( lines )


def main( argv=None ):
    """
    CLI entry point.

    Ensures:
        - exit 0 when nothing is orphaned, 1 when something is
        - --json emits the records verbatim for a caller that wants to act
        - never raises

    Returns:
        int: the exit code
    """
    parser = argparse.ArgumentParser(
        description="Report peer DMs buffered for sessions that never drained them."
    )
    parser.add_argument( "--session-dir", default=None,
                         help="where the buffers live (default: the sessions-dir seam)" )
    parser.add_argument( "--min-age-hours", type=float, default=0.0,
                         help="ignore buffers touched more recently than this" )
    parser.add_argument( "--json", action="store_true", help="emit JSON records" )
    args = parser.parse_args( argv )

    orphans = collect_orphans(
        session_dir   = args.session_dir,
        min_age_hours = args.min_age_hours,
    )
    if args.json:
        print( json.dumps( orphans, indent=2 ) )
    else:
        print( format_report( orphans ) )
    return 1 if orphans else 0


if __name__ == "__main__":
    sys.exit( main() )
