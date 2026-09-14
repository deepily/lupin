"""
Make a janitor refusal VISIBLE: a ledger of the current refused set, plus one notify
whenever that set changes.

A reap refuses a tree holding ignored files that are somebody's data (row 033538f6,
2026-09-14). A refusal nobody sees is just the old pile, moved to `.claude/worktrees/`,
where nobody looks either (Mr. Radio's review). So each janitor poll:

  1. computes the refused set { tree path: [ blocking entries ] };
  2. compares it with the set recorded in the ledger file; and
  3. only when they differ, REPLACES the ledger and sends ONE notify carrying the count
     in the message, with each tree and its blockers in the abstract.

An unchanged set sends nothing and writes nothing. The ledger is REPLACED each time, never
appended, so it cannot itself become a pile. A failed notify is logged, never swallowed.

Why not a store row per tree (considered and set aside with Mr. Radio, 2026-09-14): row
creation is throughput-gated and closing needs a receipt the arbiter cannot mint. Writing
rows through the repository directly would get around two of the operator's gates. That
decision is the operator's, and is out of this change.
"""

import json
import os
from datetime import datetime, timezone
from typing import Callable, Optional

REFUSAL_REASONS  = ( "ignored_files_present", "ignored_check_failed" )
# The escalation channel's outcome vocabulary (fleet_arbiter_loop.make_escalation_notify_fn
# + arbiter_live_notify.parse_notify_outcome). Anything else — post_error, http_error,
# unexpected_response, user_not_available — is logged as a failed notify.
OK_OUTCOMES      = ( "posted", "queued", "delivered_via_listener", "disabled" )
UNLISTABLE_MARK  = "(could not list the ignored files — refused because nothing could be proven safe)"
MAX_ABSTRACT_ROWS    = 25
MAX_BLOCKERS_PER_ROW = 5


def refused_set( reconcile_out: dict, previous: Optional[ dict ] = None ) -> dict:
    """
    The trees the janitor refused to remove, keyed by path.

    Requires:
        - reconcile_out is a reconcile_worktrees result ({ swept, skipped, errors })
        - previous is the last recorded set, or None

    Ensures:
        - every swept entry whose result has a REFUSAL_REASONS skipped_reason maps to its
          sorted ignored_blockers (or [ UNLISTABLE_MARK ] when they could not be listed)
        - a tree in `previous` that this poll SKIPPED (so was not re-judged: freshly
          touched, seat alive, locked) keeps its previous entry, so a set does not flap
          in and out on every mtime change
        - a tree that is gone, or was removed this poll, drops out
        - never raises on a well-formed input
    """
    current = {}
    for entry in reconcile_out.get( "swept", [] ):
        result = entry.get( "result" ) or {}
        if result.get( "skipped_reason" ) in REFUSAL_REASONS:
            blockers = sorted( result.get( "ignored_blockers" ) or [] ) or [ UNLISTABLE_MARK ]
            current[ entry[ "path" ] ] = blockers
    skipped_paths = { s.get( "path" ) for s in reconcile_out.get( "skipped", [] ) }
    for path, blockers in ( previous or {} ).items():
        if path not in current and path in skipped_paths:
            current[ path ] = blockers
    return current


def load_ledger( ledger_path: str ) -> dict:
    """
    The refused set last recorded at `ledger_path`.

    Ensures:
        - returns the recorded { path: [ blockers ] }, or {} when the file is absent
        - a corrupt or unreadable file returns {} (the next change rewrites it), never raises
    """
    try:
        with open( ledger_path, "r", encoding="utf-8" ) as fh:
            data = json.load( fh )
        refused = data.get( "refused" ) if isinstance( data, dict ) else None
        return refused if isinstance( refused, dict ) else {}
    except ( OSError, ValueError ):
        return {}


def write_ledger( ledger_path: str, refused: dict, now: datetime ) -> None:
    """
    Replace the ledger atomically with the current refused set.

    Ensures:
        - the file holds { updated_at, count, refused } and is replaced whole (temp file +
          os.replace), so a reader never sees a half-written ledger
        - the parent directory is created if missing
    Raises:
        - OSError when the ledger cannot be written (the caller logs it)
    """
    os.makedirs( os.path.dirname( ledger_path ), exist_ok=True )
    tmp = f"{ledger_path}.tmp"
    with open( tmp, "w", encoding="utf-8" ) as fh:
        json.dump( { "updated_at": now.isoformat(), "count": len( refused ), "refused": refused },
                   fh, indent=2, sort_keys=True )
        fh.write( "\n" )
    os.replace( tmp, ledger_path )


def compose_notice( refused: dict, ledger_path: str ) -> tuple:
    """
    The ( message, abstract ) for a changed refused set.

    Ensures:
        - message is one short spoken sentence carrying the count (or the all-clear)
        - abstract is a markdown table, one row per tree with its first blockers, and the
          ledger path; rows beyond MAX_ABSTRACT_ROWS are counted rather than dropped silently
    """
    count = len( refused )
    if count == 0:
        return ( "Worktree janitor: no worktrees are being refused any more.",
                 f"The refused set is now empty. Ledger: `{ledger_path}`" )
    noun    = "worktree" if count == 1 else "worktrees"
    message = f"Worktree janitor: {count} {noun} refused removal because they hold ignored files."
    lines   = [ "| Worktree | Blocking ignored entries |", "|---|---|" ]
    for path in sorted( refused )[ :MAX_ABSTRACT_ROWS ]:
        blockers = refused[ path ]
        shown    = ", ".join( f"`{b}`" for b in blockers[ :MAX_BLOCKERS_PER_ROW ] )
        extra    = len( blockers ) - MAX_BLOCKERS_PER_ROW
        lines.append( f"| `{os.path.basename( path )}` | {shown}{f' (+{extra} more)' if extra > 0 else ''} |" )
    if count > MAX_ABSTRACT_ROWS:
        lines.append( f"| … | {count - MAX_ABSTRACT_ROWS} more trees in the ledger |" )
    lines += [ "", f"Full set: `{ledger_path}`. Move the data somewhere durable, or remove the files, and the next poll reaps the tree." ]
    return message, "\n".join( lines )


def report_refusals(
    reconcile_out : dict,
    ledger_path   : str,
    notify_fn     : Callable,
    log_fn        : Callable,
    now           : Optional[ datetime ] = None,
) -> dict:
    """
    Record the refused set and notify ONLY when it changed.

    Requires:
        - notify_fn( message, abstract ) -> list of outcome dicts, or raises
        - log_fn( event, **fields )

    Ensures:
        - returns { changed, count, notified, outcomes }
        - unchanged set (compared as dicts, order-insensitive) → no ledger write, no notify
        - changed set → ledger replaced, then notify_fn called once
        - a ledger write failure is logged (`worktree_refusal_ledger_write_failed`) and the
          notify is STILL sent — the operator hearing about it matters more than the file
        - a notify that raises, or returns any outcome whose "outcome" is not a delivery
          or a disabled channel, is logged (`worktree_refusal_notify_failed`), never swallowed
        - never raises
    """
    now      = now if now is not None else datetime.now( timezone.utc )
    previous = load_ledger( ledger_path )
    current  = refused_set( reconcile_out, previous )
    out      = { "changed": False, "count": len( current ), "notified": False, "outcomes": [] }
    if current == previous:
        return out

    out[ "changed" ] = True
    try:
        write_ledger( ledger_path, current, now )
    except OSError as e:
        log_fn( "worktree_refusal_ledger_write_failed", path=ledger_path, error=str( e ) )

    message, abstract = compose_notice( current, ledger_path )
    try:
        outcomes = notify_fn( message, abstract ) or []
    except Exception as e:
        log_fn( "worktree_refusal_notify_failed", count=len( current ), error=str( e ) )
        return out
    out[ "outcomes" ] = outcomes
    failed = [ o for o in outcomes if isinstance( o, dict ) and o.get( "outcome" ) not in OK_OUTCOMES ]
    if failed:
        log_fn( "worktree_refusal_notify_failed", count=len( current ), outcomes=failed )
    out[ "notified" ] = not failed
    log_fn( "worktree_refusal_set_changed", count=len( current ), previous_count=len( previous ) )
    return out
