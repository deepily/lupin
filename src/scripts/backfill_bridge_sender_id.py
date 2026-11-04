#!/usr/bin/env python3
"""
Backfill `sender_id` into session bridges written before the host wrote it itself.

Run on the host. One-shot, idempotent, re-runnable. Report-only by default: it writes
nothing unless you pass `--write`. `--dry-run` is accepted and does nothing, because
that is what a careful operator types first and erroring on it would be the wrong answer.

Why this exists:
    The SessionStart hook computes the sender id on the host and writes it into the bridge. `routers/commons.py::_sender_id_for_bridge` serves it verbatim instead of re-deriving it inside a container where host paths do not exist. That closes the defect where every worktree seat was served under a second identity (`claude.code@seat-cc-author-<name>.deepily.ai#<hash>`).
    A session already running before that change has a bridge with no `sender_id`. Nothing rewrites that bridge until its next SessionStart, because `touch_bridge_mtime` moves the mtime, not the content.
    Until then the server serves null and the phone skips the seat. So a live seat vanishes from the focus rail instead of showing up cold.

Clause 3, described in `classify()`, keeps this script from generating bugs.

Read the skipped counts, not the written count:
    `skipped_cwd_missing` and `skipped_no_git_ancestor` are the interesting numbers: they are
    the bridges this script refused to guess for. A run that writes many and skips none on a
    box with deleted worktrees would mean clause 3 is not firing.

Never a sentinel, never an overwrite:
    - Inferring the project from the path segment before `/.claude/worktrees/` is banned,
      including as a silent fallback.
    - A bridge that already carries a `sender_id` is authoritative and never overwritten.
      It came from that session's own SessionStart, on the host, with its cwd real.
    - The string "unknown" is never written. It has no "#", so `sessionHashOf` returns null
      on the phone, the hash-merge never fires, and every unidentified seat would collapse
      onto one bogus rail row.

Usage:
    python src/scripts/backfill_bridge_sender_id.py              # report only
    python src/scripts/backfill_bridge_sender_id.py --write      # actually backfill
    python src/scripts/backfill_bridge_sender_id.py --write -v   # name every bridge

Exit codes:
    0  ran; see the table. Zero written is a normal, healthy outcome.
    2  the sessions directory could not be resolved or read.
    3  a required import failed: wrong interpreter or PYTHONPATH
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
    from cosa.agents.utils.sender_id import build_sender_id, resolve_project_for_path
except ImportError as err:
    print( f"FATAL: import failed ({err!r}). Run with the repo's interpreter and "
           f"PYTHONPATH=<tree>/src.", file=sys.stderr )
    sys.exit( 3 )


def classify( bridge: dict ) -> tuple[ str, str | None ]:
    """
    Decide what to do with one bridge, and why.

    Ensures:
        - Returns ( outcome, sender_id_or_None ) where outcome is one of:
          "already_has_one", "skipped_no_cwd", "skipped_cwd_missing",
          "skipped_no_git_ancestor", "eligible"
        - A sender_id is returned only for "eligible", and only after both halves of
          clause 3 pass
        - Never raises

    Notes:
        Clause 3 keeps this script from generating bugs.
            Backfill a bridge only when both hold:
            (i)  `os.path.isdir( cwd )`: the recorded directory still exists.
            (ii) `resolve_project_for_path( cwd )` returns a name rather than None: a real `.git`
                 ancestor was found by walking up from it. That function refuses, so the check and
                 the name are one call.
            `detect_project_for_path` falls back to the basename when it finds no `.git` ancestor,
            and it never raises. That fallback is documented policy for `os.getcwd()`.
            Measured results.
                detect_project_for_path( "/mnt/.../lupin/.claude/worktrees/seat-DELETED" ) -> "lupin".
                detect_project_for_path( "/no/such/place/at/all/seat-x" )                  -> "seat-x".
                detect_project_for_path( "/tmp" )                                          -> "tmp".
            That basename fallback is the mechanism of the original defect.
            It is how the container produced `@seat-cc-author-<name>`.
            A backfill trusting the return value would compute `claude.code@seat-x.deepily.ai#<hash>`
            for any bridge whose cwd is gone, and write it into the bridge.
            There it becomes durable and authoritative, because the server may not question it.
            Today the defect is contained by being recomputed on every read.
            Backfilling without clause 3 would make it permanent.
            When either half fails, write nothing. Absent is the correct answer: the server serves
            null and the phone skips the seat (`focus_chat_bloc.dart:444`, pinned by
            `focus_live_seat_roster_test.dart:81`). A skipped seat is a visible gap.
            A wrong identity is an invisible lie.
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
    #
    # 🔴 THIS IS NOW ONE CALL, AND THAT IS THE POINT (row 1ca233ae). It used to be two:
    # a local `git_ancestor` walk to corroborate, then `detect_project_for_path` to name
    # — because the naming function could not refuse, so its answer needed a second
    # opinion. `resolve_project_for_path` refuses, so the corroboration IS the answer.
    #
    # ⚠️ AND THE SECOND OPINION WAS NEVER INDEPENDENT. `git_ancestor`'s own docstring
    # said it "mirrors it deliberately — same order, same `.git`-exists test". Two
    # derivations that agree only by careful copying are COINCIDING, not agreeing, and
    # they diverge the first time somebody edits one. That is row 6597cea9, which the
    # deleted docstring itself cited. One walk cannot disagree with itself.
    project = resolve_project_for_path( cwd )
    if project is None:
        return "skipped_no_git_ancestor", None

    session_id = bridge.get( "stable_session_id" ) or bridge.get( "session_id" ) or ""
    if not session_id:
        return "skipped_no_cwd", None   # no id to suffix with; nothing honest to write

    try:
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
