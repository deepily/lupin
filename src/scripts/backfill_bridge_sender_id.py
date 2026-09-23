#!/usr/bin/env python3
"""
Backfill `sender_id` into session bridges written BEFORE row 2184bebb's Option B.

Run on the HOST. One-shot, idempotent, re-runnable. REPORT-ONLY BY DEFAULT — it writes
nothing unless you pass `--write`. `--dry-run` is accepted and does nothing, because
that is what a careful operator types first and erroring on it at that exact moment is
the wrong answer.

WHY THIS EXISTS
---------------
Option B moved the sender_id computation to the SessionStart hook: the host writes the
id it already knows into the bridge, and `routers/commons.py::_sender_id_for_bridge`
serves it verbatim instead of re-deriving it inside a container where host paths do not
exist. That closes the defect where every worktree seat was served under a second
identity (`claude.code@seat-cc-author-<name>.deepily.ai#<hash>`).

It leaves a MIGRATION GAP. A session already running when Option B ships has a bridge
with no `sender_id`, and nothing rewrites that bridge until its next SessionStart —
`touch_bridge_mtime` moves the mtime, not the content. Until then the server serves
null and the phone skips the seat, so a live seat VANISHES from the focus rail rather
than showing up cold, which is the requirement Tiffany's 2026-09-17 ask pins.

🔴 CLAUSE 3 — THE LOAD-BEARING ONE. WITHOUT IT THIS SCRIPT IS A BUG GENERATOR.
------------------------------------------------------------------------------
A bridge is backfilled ONLY when BOTH hold:

    (i)  `os.path.isdir( cwd )` — the recorded directory STILL EXISTS, and
    (ii) a REAL `.git` ancestor is actually FOUND by walking up from it —
         not merely that `detect_project_for_path` RETURNED something.

(ii) is not a restatement of (i) and it is not paranoia. `detect_project_for_path`
FALLS BACK TO THE BASENAME when it finds no `.git` ancestor, and it never raises.
Measured 2026-09-22 against the real function:

    detect_project_for_path( "/mnt/.../lupin/.claude/worktrees/seat-DELETED" ) -> "lupin"
    detect_project_for_path( "/no/such/place/at/all/seat-x" )                  -> "seat-x"   🔴
    detect_project_for_path( "/tmp" )                                          -> "tmp"

That basename fallback IS the original defect's mechanism — it is exactly how the
container produced `@seat-cc-author-<name>`. So a backfill that trusts the return value
would compute `claude.code@seat-x.deepily.ai#<hash>` for any bridge whose cwd is gone
and WRITE IT INTO THE BRIDGE, where it becomes durable, authoritative, and
un-second-guessable — because the server is now contractually forbidden from
questioning it.

⇒ Today the defect is CONTAINED by being recomputed on every read. Backfilling without
clause 3 would make it PERMANENT, laundering the bug into the one place nothing checks.
That is worse than the gap this script closes.

⇒ When either half of clause 3 fails: WRITE NOTHING. Absent is already the correct
answer — the server serves null and the phone skips the seat
(`focus_chat_bloc.dart:444`, pinned by `focus_live_seat_roster_test.dart:81`). A
skipped seat is a visible gap; a wrong identity is an invisible lie.

NEVER A SENTINEL, NEVER AN OVERWRITE
------------------------------------
- Option A — inferring the project from the path segment before `/.claude/worktrees/`
  — is BANNED by Mr. Radio's ruling (2026-09-19), including as a silent fallback.
- A bridge that ALREADY carries a `sender_id` is authoritative: it came from that
  session's own SessionStart, on the host, with its cwd real. Never overwritten.
- The string "unknown" is never written. It has no "#", so `sessionHashOf` returns null
  on the phone, the hash-merge never fires, and every unidentified seat would collapse
  onto one bogus rail row.

READ THE SKIPPED COUNTS, NOT THE WRITTEN COUNT
----------------------------------------------
`skipped_cwd_missing` and `skipped_no_git_ancestor` are the interesting numbers: they
are the bridges this script REFUSED to guess for. A run that writes many and skips none
on a box with deleted worktrees would mean clause 3 is not firing.

Usage:
    python src/scripts/backfill_bridge_sender_id.py              # report only
    python src/scripts/backfill_bridge_sender_id.py --write      # actually backfill
    python src/scripts/backfill_bridge_sender_id.py --write -v   # name every bridge

Exit codes:
    0  ran; see the table (0 written is a normal, healthy outcome)
    2  the sessions directory could not be resolved or read
    3  a required import failed — wrong interpreter or PYTHONPATH
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir
    from lupin_cli.claude_code.hooks.lib.session_bridge import atomic_write_json, _is_pid_alive
    from cosa.agents.utils.sender_id import build_sender_id, detect_project_for_path
except ImportError as err:
    print( f"FATAL: import failed ({err!r}). Run with the repo's interpreter and "
           f"PYTHONPATH=<tree>/src.", file=sys.stderr )
    sys.exit( 3 )


def git_ancestor( start_path ) -> Path | None:
    """
    The nearest ancestor of `start_path` that actually contains a `.git` entry.

    CLAUSE 3(ii). This is the corroboration `detect_project_for_path`'s return value
    cannot give, because that function falls back to the basename rather than failing.
    The walk mirrors it deliberately — same order, same `.git`-exists test — so the two
    agree about WHETHER a repo was found, while the NAME stays that function's job
    alone. Resolving the name twice is how row 6597cea9 happened.

    Requires:
        - start_path is path-like; it need not exist

    Ensures:
        - Returns the first ancestor (starting at start_path itself) holding a `.git`
          entry of any kind — a directory, or the FILE a worktree uses
        - Returns None when no such ancestor exists, which is the refusal signal
        - Never raises
    """
    try:
        start = Path( start_path ).resolve()
    except ( OSError, ValueError ):
        return None
    for candidate in [ start, *start.parents ]:
        try:
            if ( candidate / ".git" ).exists():
                return candidate
        except OSError:
            return None
    return None


def classify( bridge: dict ) -> tuple[ str, str | None ]:
    """
    Decide what to do with one bridge, and why.

    Ensures:
        - Returns ( outcome, sender_id_or_None ) where outcome is one of:
          "already_has_one", "skipped_no_cwd", "skipped_cwd_missing",
          "skipped_no_git_ancestor", "eligible"
        - A sender_id is returned ONLY for "eligible", and only after BOTH halves of
          clause 3 pass
        - Never raises
    """
    existing = bridge.get( "sender_id" )
    if isinstance( existing, str ) and existing:
        return "already_has_one", None

    cwd = bridge.get( "cwd" )
    if not isinstance( cwd, str ) or not cwd:
        return "skipped_no_cwd", None

    # CLAUSE 3(i) — the directory still exists.
    if not os.path.isdir( cwd ):
        return "skipped_cwd_missing", None

    # CLAUSE 3(ii) — a real .git ancestor was FOUND, not merely a name returned.
    if git_ancestor( cwd ) is None:
        return "skipped_no_git_ancestor", None

    session_id = bridge.get( "stable_session_id" ) or bridge.get( "session_id" ) or ""
    if not session_id:
        return "skipped_no_cwd", None   # no id to suffix with; nothing honest to write

    try:
        project = detect_project_for_path( cwd )
        return "eligible", build_sender_id( "claude.code", project=project,
                                            suffix=str( session_id )[ :8 ] )
    except Exception:                                    # noqa: BLE001
        return "skipped_no_git_ancestor", None


def main() -> int:
    parser = argparse.ArgumentParser( description="Backfill sender_id into pre-Option-B bridges." )
    parser.add_argument( "--write",   action="store_true", help="actually modify bridges (default: report only)" )
    # An explicit no-op. Report-only is already the default, but `--dry-run` is what
    # someone types when they want to be SURE, and argparse's "unrecognized arguments"
    # error is a bad answer to a cautious instinct. It is accepted and means what the
    # default already does; passing it with --write is refused below rather than
    # silently letting one win.
    parser.add_argument( "--dry-run", action="store_true", help="explicit no-op: report only, which is the default" )
    parser.add_argument( "-v", "--verbose", action="store_true", help="name every bridge and its outcome" )
    parser.add_argument( "--include-dead", action="store_true",
                         help="also backfill bridges whose cc_pid is gone (default: skip them)" )
    args = parser.parse_args()

    if args.dry_run and args.write:
        print( "FATAL: --dry-run and --write contradict each other. Refusing to guess "
               "which you meant; pass exactly one (or neither, which reports only).",
               file=sys.stderr )
        return 2

    try:
        sdir = Path( sessions_dir() )
        bridges = sorted( sdir.glob( "cc-*.json" ) )
    except Exception as err:                             # noqa: BLE001
        print( f"FATAL: could not read the sessions directory ({err!r}).", file=sys.stderr )
        return 2

    counts = { "already_has_one": 0, "skipped_no_cwd": 0, "skipped_cwd_missing": 0,
               "skipped_no_git_ancestor": 0, "skipped_dead": 0, "written": 0,
               "eligible_not_written": 0, "unreadable": 0 }

    print( f"sessions dir : { sdir }" )
    print( f"bridges found: { len( bridges ) }" )
    print( f"mode         : { 'WRITE' if args.write else 'REPORT ONLY (pass --write to apply)' }\n" )

    for path in bridges:
        try:
            data = json.loads( path.read_text( encoding="utf-8" ) )
            if not isinstance( data, dict ):
                raise ValueError( "bridge is not an object" )
        except Exception as err:                         # noqa: BLE001
            counts[ "unreadable" ] += 1
            if args.verbose: print( f"  unreadable              { path.name }: { err!r }" )
            continue

        pid = data.get( "cc_pid" )
        if not args.include_dead and isinstance( pid, int ) and not _is_pid_alive( pid ):
            counts[ "skipped_dead" ] += 1
            if args.verbose: print( f"  skipped_dead            { path.name } (pid { pid })" )
            continue

        outcome, sender_id = classify( data )

        if outcome != "eligible":
            counts[ outcome ] += 1
            if args.verbose: print( f"  { outcome.ljust( 23 ) } { path.name }" )
            continue

        if not args.write:
            counts[ "eligible_not_written" ] += 1
            print( f"  WOULD WRITE             { path.name } -> { sender_id }" )
            continue

        data[ "sender_id" ] = sender_id
        if atomic_write_json( str( path ), data ):
            counts[ "written" ] += 1
            print( f"  written                 { path.name } -> { sender_id }" )
        else:
            counts[ "unreadable" ] += 1
            print( f"  WRITE FAILED            { path.name } (atomic_write_json returned False)" )

    print( "\n" + "=" * 62 )
    for key in ( "written", "eligible_not_written", "already_has_one", "skipped_dead",
                 "skipped_no_cwd", "skipped_cwd_missing", "skipped_no_git_ancestor",
                 "unreadable" ):
        print( f"  { key.ljust( 24 ) } { counts[ key ] }" )
    print( "=" * 62 )
    print( "READ THE SKIPPED COUNTS. `skipped_cwd_missing` and `skipped_no_git_ancestor`\n"
           "are the bridges this script REFUSED to guess an identity for — clause 3 doing\n"
           "its job. Those seats serve sender_id null and the phone skips them, which is\n"
           "the correct answer: a visible gap beats an invisible wrong identity." )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
