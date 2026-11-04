"""
Sweeper that marks orphaned response-required notifications expired after a grace delay.

Only one writer marks such a notification `state='expired'`. It is the `except asyncio.TimeoutError`
branch of the SSE generator in routers/notifications.py, and it fires when the generator reaches
its own deadline. When the asking client walks away, the close raises `asyncio.CancelledError`
at the generator's `await asyncio.wait_for( ... )`. That is not an `Exception` subclass.
So the router's `except Exception` cannot catch it. The `finally` clears the in-memory entry and leaves
the row `delivered` past its `expires_at`, forever. `get_expired_notifications()` had no caller
to sweep them; this module is that caller.

The grace delay is the /notify/response contract, not a safety margin. `expires_at` is not when the
human stopped caring. Of 58 answers that landed after it, 57 came within 300s (highest 298s).
None came between 301s and 600s, and one came 1,109s late from a 600s ask. So the 300s default
is not arbitrary: it falls in a real gap in the data and does not cut through a cluster. A row marked expired the
instant `expires_at` passes would turn a real answer into a 400.
`POST /api/notify/response` accepts a late answer against an `expired` row for
`notification grace period seconds` past `expires_at`, and against a `delivered` row forever.
So this sweeper narrows the honoured window from forever to expires_at plus grace, which costs
one keypress in that population. The lever is that one key, which the caller passes as
`grace_seconds`; a second delay knob would eventually disagree with it.

The sweeper never applies `response_default`. On the timeout path that default is returned to
a waiting caller. On the sweep path nobody is waiting, so writing it would assert an answer
that never reached anyone. The sweeper passes `apply_default=False` and leaves `response_value`
NULL, which also tells a swept row from a timed-out one with no schema change.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing  import Callable, Dict, List, Optional


def _partition( candidates, grace_seconds, now ):
    """
    Split candidate rows into (sweepable ids, count still inside grace).

    This is the single place the grace rule is expressed, so the dry run and the live pass
    cannot disagree about it.

    Requires:
        - candidates is an iterable of rows carrying .id and .expires_at
        - now is an aware datetime

    Ensures:
        - a row is sweepable iff expires_at <= now - grace_seconds
        - rows with a NULL expires_at are neither swept nor counted in-grace;
          get_expired_notifications() already excludes them, so one appearing
          here is a contract change rather than a normal case

    Raises:
        - TypeError on a naive expires_at, rather than silently comparing it wrong
    """
    cutoff    = now - timedelta( seconds=grace_seconds )
    sweepable = []
    in_grace  = 0

    for n in candidates:
        expires_at = n.expires_at
        if expires_at is None: continue
        if expires_at.tzinfo is None:
            raise TypeError(
                f"notification {n.id} carries a NAIVE expires_at; refusing to "
                "compare it against an aware cutoff — see row 3b4002fe"
            )
        if expires_at <= cutoff: sweepable.append( str( n.id ) )
        else:                    in_grace += 1

    return sweepable, in_grace


def find_sweepable_ids( repo, grace_seconds, now=None ):
    """
    The rows this sweeper is allowed to close, as id strings. Read-only.

    It has no production caller; only a unit test calls it. A search for `sweep_once` finds
    unrelated hits from the heartbeat arbiter's own `sweep_once`.

    Requires:
        - repo exposes get_expired_notifications() -> list of Notification
        - grace_seconds is a non-negative number
        - now is an aware datetime, or None to read the wall clock

    Ensures:
        - kept despite having no caller: the sweeper ships disabled behind its INI flag, and this
          is the dry-run form of the decision to arm it, answering "which rows would this close
          right now" without writing anything
        - cannot drift from the live pass, because both express the grace rule through
          `_partition` and nowhere else; without that it would be a second copy and should go
        - returns only rows whose expires_at is at least grace_seconds in the
          past; a row still inside its /notify/response grace window is never
          returned, however far past expires_at it is
        - returns ids as strings, in the repository's own order
        - returns [] when nothing qualifies (an empty list is a finding here,
          not an error)

    Raises:
        - TypeError if a candidate row carries a naive expires_at
    """
    if now is None: now = datetime.now( timezone.utc )
    sweepable, _ = _partition( repo.get_expired_notifications(), grace_seconds, now )
    return sweepable


def sweep_once( session_factory, grace_seconds, batch_limit=200, now=None, debug=False ):
    """
    One sweep pass: mark every orphaned notification expired.

    Requires:
        - session_factory is a context manager yielding a DB session
        - grace_seconds is a non-negative number
        - batch_limit is a positive integer

    Ensures:
        - marks at most batch_limit rows per call, oldest expiry first
        - never applies response_default; see this module's docstring
        - never overwrites a row that stopped being 'delivered' between the
          scan and the mark; that row is counted under "refused", never
          under "swept"
        - returns {"scanned", "swept", "refused", "skipped_in_grace"} so the
          caller has the sweeper's own account of what it touched, rather
          than having to read a return code
        - "swept" counts rows actually written, not rows attempted
        - a pass that finds nothing returns swept=0 and is not an error

    Raises:
        - propagates DB errors to the caller
    """
    from cosa.rest.db.repositories.notification_repository import NotificationRepository

    if now is None: now = datetime.now( timezone.utc )

    with session_factory() as session:
        repo       = NotificationRepository( session )
        candidates = repo.get_expired_notifications()

        sweepable, in_grace = _partition( candidates, grace_seconds, now )
        targets             = sweepable[ :batch_limit ]

        # expected_state="delivered" is the CONTROL against the scan-then-mark
        # race (row bf4f65c3): every id here was 'delivered' when the scan ran,
        # and a /notify/response that lands before this loop reaches it makes the
        # UPDATE match zero rows rather than stamping 'expired' over a real
        # human answer.
        #
        # COUNT what was actually written, never what was attempted. Reporting
        # len( targets ) would report a refused row as a sweep, which is the
        # one number that would have told us this race is real.
        swept = 0
        for notification_id in targets:
            if repo.mark_expired(
                uuid.UUID( notification_id ), apply_default=False, expected_state="delivered"
            ) is not None:
                swept += 1

        result = {
            "scanned"          : len( candidates ),
            "swept"            : swept,
            "refused"          : len( targets ) - swept,
            "skipped_in_grace" : in_grace
        }

    if debug and ( result[ "swept" ] or result[ "refused" ] ):
        print( f"[NOTIFY-SWEEP] swept {result['swept']} orphaned notification(s) "
               f"(scanned {result['scanned']}, {result['skipped_in_grace']} still in grace, "
               f"{result['refused']} refused — answered between scan and mark)" )

    return result
