"""
Sweeper for ORPHANED response-required notifications.

THE DEFECT THIS CLOSES (row bf4f65c3)
-------------------------------------
A response-required notification is marked `state='expired'` by exactly ONE
writer: the SSE generator's `except asyncio.TimeoutError` branch in
routers/notifications.py. That branch fires only when the generator reaches
its own deadline.

When the asking client WALKS AWAY, it never does. Measured at the real layer
(real uvicorn, real Starlette StreamingResponse, real TCP close): the
generator is suspended at `await asyncio.wait_for( ... )`, and the close
raises `asyncio.CancelledError` there ~1 ms later. `CancelledError` is not a
subclass of `Exception`, so the router's `except Exception` clause cannot
catch it either. The `finally` runs, clears the in-memory pending entry, and
does NOT touch the row.

Result: the row stays `delivered` past its `expires_at` FOREVER. Nothing
swept them, because `get_expired_notifications()` — which has existed and
been correct the whole time — had ZERO callers. This module is its caller.

🔴 THE GRACE DELAY IS NOT A SAFETY MARGIN — IT IS THE /respond CONTRACT
-------------------------------------------------------------------
`expires_at` IS NOT WHEN THE HUMAN STOPPED CARING. 58 real keypresses landed
after it. A sweeper that marks a row expired the instant `expires_at` passes
would convert a genuine human answer into a 400 — manufacturing a non-answer
out of an answer, which is the exact inverse of the e5f21fff defect this
whole epic exists for. Meet that sentence before you simplify this away.

The mechanism: `POST /api/notifications/{id}/respond` accepts a LATE answer
against an `expired` row for `notification grace period seconds` past
`expires_at` (routers/notifications.py, the `state == "expired"` branch).
Against a `delivered` row it accepts one FOREVER. So marking early NARROWS
the window in which a keypress is honoured.

THE MEASUREMENT, WITH ITS POPULATION AND ITS MOMENT
---------------------------------------------------
Taken 2026-09-05 ~22:00 UTC against lupin_db_dev, named explicitly via
`docker exec lupin-postgres psql -d lupin_db_dev` rather than a host shell
inheriting the dev config. Population: every response-required notification
that reached state='responded' with a non-null expires_at.

    answers landing AFTER expires_at            58
    answers landing BEFORE it (CONTROL)      3,070   <- the scan reaches the population

    of the 58, by how late:
        <= 300s  (inside the grace window)       57      highest of them: 298s
        301-600s                                  0      <- THE GAP
        >  600s                                   1      1,109s

⚠️ THE 58th, NAMED RATHER THAN AVERAGED AWAY — because 57-of-58 must not be
read as if it were 58-of-58. It is notification 33311818, created 2026-07-13,
`response_value.source = "ui"` (a real keypress, not a default), answered
1,109s after an expires_at set by a 600s ask timeout — the longest ask in the
set, where every other late answer came from a 60s or 300s ask.

⇒ IT IS NOT 301s, SO THE WINDOW IS NOT ARBITRARY. The dense cluster tops out
at 298s and NOTHING sits between 301s and 600s. 300 lands in a real gap in
the data rather than cutting through a cluster.

⇒ AND IT IS NOT FREE, SAID PLAINLY: this sweeper narrows the honoured window
from FOREVER to expires_at + grace, and on this population that costs exactly
one keypress in 58 — that one. It is a cost, not a rounding error, and the
right lever for a reader who wants it back is `notification grace period
seconds` itself, which widens the sweeper and /respond TOGETHER. Do not add a
second delay knob: two numbers that must agree will eventually not.

This module reads that SAME key, so the sweeper closes a row at precisely the
moment /respond would refuse it anyway, and the two cannot drift apart when
somebody retunes it.

WHY IT DOES NOT APPLY response_default
--------------------------------------
`NotificationRepository.mark_expired()` applies `response_default` as a
`response_value` stamped `source: "timeout_default"`. On the TIMEOUT path
that default is real — it is returned to the caller that was waiting. On the
SWEEP path nobody is waiting and nothing consumes it, so writing it would
assert that an answer was supplied when none ever reached anyone. The
sweeper passes `apply_default=False` and leaves `response_value` NULL, which
is also what distinguishes a swept row from a timed-out one with no schema
change.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing  import Callable, Dict, List, Optional


def _partition( candidates, grace_seconds, now ):
    """
    Split candidate rows into (sweepable ids, count still inside grace).

    The SINGLE place the grace rule is expressed, so the pure helper and the
    live pass can never disagree about it.

    Requires:
        - candidates is an iterable of rows carrying .id and .expires_at
        - now is an AWARE datetime

    Ensures:
        - a row is sweepable iff expires_at <= now - grace_seconds
        - rows with a NULL expires_at are neither swept nor counted in-grace;
          get_expired_notifications() already excludes them, so one appearing
          here is a contract change rather than a normal case

    Raises:
        - TypeError on a NAIVE expires_at, rather than silently comparing it
          wrong — row 3b4002fe was exactly that comparison going unnoticed
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
    The rows this sweeper is allowed to close, as id strings.

    Requires:
        - repo exposes get_expired_notifications() -> list of Notification
        - grace_seconds is a non-negative number
        - now is an AWARE datetime, or None to read the wall clock

    Ensures:
        - returns only rows whose expires_at is at least grace_seconds in the
          past — a row still inside its /respond grace window is NEVER
          returned, however far past expires_at it is
        - returns ids as strings, in the repository's own order
        - returns [] when nothing qualifies (an empty list is a finding here,
          not an error)

    Raises:
        - TypeError if a candidate row carries a NAIVE expires_at
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
        - NEVER applies response_default — see this module's docstring
        - NEVER overwrites a row that stopped being 'delivered' between the
          scan and the mark; that row is counted under "refused", never
          under "swept"
        - returns {"scanned", "swept", "refused", "skipped_in_grace"} so the
          caller has the sweeper's OWN account of what it touched, rather
          than having to read a return code
        - "swept" counts rows actually WRITTEN, not rows attempted
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
        # and a /respond that lands before this loop reaches it makes the
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
