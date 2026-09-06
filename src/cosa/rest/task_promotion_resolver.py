"""
The half of an asynchronous promotion that happens AFTER the caller has been answered.

Design of record: `src/rnd/v0.2.1/2026.09.06-asynchronous-promotion-approval-and-its-
observable-resolution.md` (row `3493ae9b`). Mr. Radio's conditional ruling of
2026-09-06: option (b) ships ONLY with a resolution path the caller can observe. María
🌸's binding requirement, in her words as relayed: a 202 that leaves the manager unable
to learn the outcome is the same defect with the waiting moved somewhere nobody looks.

🔴 THE ONE THING THIS MODULE EXISTS TO BUY BACK. Today's synchronous door holds a row
lock for the WHOLE ask, so the row cannot move between the decision and the apply. That
is genuinely worth something, and letting go of the lock is what makes the 202 possible.
So the lock has to be bought back rather than lost: every apply here RE-VALIDATES under
a fresh lock, and a ticket whose transition is no longer legal resolves `superseded`
carrying the validator's own words. Replaying a stale intent onto a moved row is the
defect this design would otherwise introduce.

⚠️ WHAT IS DELIBERATELY NOT HERE, SAID OUT LOUD SO NOBODY READS IT AS ARMED. Design §6.3
recovers a bounce-orphaned answer by reading the notification's `responded_at` off the
stored `notification_id`. **That recovery is NOT built.** `NotificationResponse` does not
carry the id — `notify_user_sync` captures it off the opening ack frame into a local
capture dict and never surfaces it, across fifteen construction sites — so the ticket's
`notification_id` column stays NULL in this landing. The consequence is stated rather
than hidden: after a bounce, a pending ticket goes `stalled` and fires the urgent notify,
and a HUMAN is told. Nothing is lost silently. What is missing is the automatic recovery
of a keypress Rick made just before the bounce, and that is a named follow-up, not an
omission somebody forgot.
"""

from dataclasses import dataclass
from datetime    import datetime, timedelta, timezone
from typing      import Optional
import uuid

from cosa.rest.db.database                       import get_db
from cosa.rest.db.repositories.task_repository   import TaskRepository
from cosa.rest.postgres_models                   import TaskPromotionTicket
from cosa.rest import task_store_rules   as rules
from cosa.rest import task_promotion_gate as promotion_gate


# ── THE STATE VOCABULARY ────────────────────────────────────────────────────────────
#
# ⚠️ THESE ARE THE MODEL DOCSTRING'S FIVE WORDS, GIVEN NAMES SO THE RESOLVER AND THE
# SCHEMA CANNOT DRIFT APART IN THE ONE DIRECTION A CHECK CONSTRAINT CANNOT SEE. The two
# CHECKs on the table are STRUCTURAL — "a resolved ticket has a timestamp", "a refused
# ticket has a reason" — and neither is a membership test, exactly as `TaskItem.status`
# is governed by `task_store_rules.VALID_STATUSES` rather than by an enum column. So a
# typo'd state would be written happily. Naming them here is what makes a typo a
# NameError instead of a row.
TICKET_PENDING    = "pending"
TICKET_APPROVED   = "approved"
TICKET_REFUSED    = "refused"
TICKET_SUPERSEDED = "superseded"
TICKET_STALLED    = "stalled"

TICKET_TERMINAL_STATES = frozenset( {
    TICKET_APPROVED, TICKET_REFUSED, TICKET_SUPERSEDED, TICKET_STALLED
} )

# The room between "the ask can no longer be running" and "this ticket is an orphan".
#
# 🔴 IT IS NOT A GUESS ABOUT HOW LONG RICK TAKES — that is the ask timeout's job and it
# is an operator dial. This covers only the work AFTER his answer lands: one short
# transaction that re-locks the row, re-validates and applies. Sizing it off his answer
# latency would be pricing the wrong thing.
#
# ⚠️ TOO SMALL AND A HEALTHY TICKET IS DECLARED AN ORPHAN WHILE ITS RESOLVER IS STILL
# COMMITTING — a false alarm that fires an urgent notify at a human. Too large and a real
# orphan sits quiet for longer. The asymmetry favours the larger value: a late alarm is
# late, an alarm that cries wolf is the one that stops being read.
ASK_GRACE_SECONDS = 60


def resolves_by_for( requested_at, timeout_fn=promotion_gate.get_ask_timeout_seconds,
                     grace_seconds=ASK_GRACE_SECONDS ):
    """
    When a ticket minted at `requested_at` must have resolved by.

    🔴 READ AT MINT TIME, NOT AT SWEEP TIME, AND THAT IS THE WHOLE REASON IT IS STORED
    ON THE ROW. The timeout is a live operator dial; a sweeper that re-derived this
    deadline would be judging a ticket against a number that may have changed since the
    ask went out, and an operator lowering the dial would retroactively declare
    in-flight tickets overdue. The row carries the deadline it was actually issued
    under — the same reason the design serializes the response body once rather than
    re-reading it.

    Requires:
        - requested_at is a timezone-aware datetime
        - timeout_fn returns the ask timeout in seconds

    Ensures:
        - returns a timezone-aware datetime strictly after requested_at
        - never raises for a well-formed input
    """
    return requested_at + timedelta( seconds=int( timeout_fn() ) + int( grace_seconds ) )


@dataclass( frozen=True )
class TransitionIntent:
    """
    The caller's transition, in the shape the resolver needs to replay it.

    🔴 ONE CLASS THAT KNOWS THE SHAPE IN BOTH DIRECTIONS, WHICH IS THE POINT. The mint
    site writes this dict and the resolve site reads it, in two different processes-worth
    of time apart. A writer and a reader that each know the shape independently are two
    derivations of one value, and they agree until somebody adds a field to one of them.

    ⚠️ WHAT IS DELIBERATELY ABSENT: the caller's account identity, and therefore the
    ask-exempt decision and the manager decision. Those were settled synchronously by
    `promotion_gate.promotion_precheck` before the 202 was sent. Persisting a resolved
    authorization decision and replaying it later makes it forgeable by anyone who can
    write this JSON; not persisting it is cheaper than guarding it, and the resolver
    never needs it because it never re-decides who may promote.
    """
    to_status     : str
    actor         : str
    recorded_actor: str
    authority     : str
    receipt_refs  : Optional[ dict ]
    blocked_by    : Optional[ list ]
    reason        : Optional[ str ]
    park_reason   : Optional[ str ]
    next_chase_ts : Optional[ datetime ]
    title         : str
    session_id    : Optional[ str ]

    def as_payload( self ):
        """
        The JSONB-safe dict stored on the ticket.

        Ensures:
            - every value is JSON-serializable (datetimes become ISO strings)
            - `from_payload` of this result reproduces this intent
        """
        return {
            "to_status"      : self.to_status,
            "actor"          : self.actor,
            "recorded_actor" : self.recorded_actor,
            "authority"      : self.authority,
            "receipt_refs"   : self.receipt_refs,
            "blocked_by"     : self.blocked_by,
            "reason"         : self.reason,
            "park_reason"    : self.park_reason,
            "next_chase_ts"  : self.next_chase_ts.isoformat() if self.next_chase_ts else None,
            "title"          : self.title,
            "session_id"     : self.session_id,
        }

    @classmethod
    def from_payload( cls, payload ):
        """
        Rebuild an intent from a stored ticket payload.

        Requires:
            - payload is the dict `as_payload` produced

        Ensures:
            - returns a TransitionIntent
            - `next_chase_ts` comes back as a timezone-aware datetime or None
        """
        raw = ( payload or {} ).get( "next_chase_ts" )
        return cls(
            to_status      = ( payload or {} ).get( "to_status" ),
            actor          = ( payload or {} ).get( "actor" ),
            recorded_actor = ( payload or {} ).get( "recorded_actor" ),
            authority      = ( payload or {} ).get( "authority" ),
            receipt_refs   = ( payload or {} ).get( "receipt_refs" ),
            blocked_by     = ( payload or {} ).get( "blocked_by" ),
            reason         = ( payload or {} ).get( "reason" ),
            park_reason    = ( payload or {} ).get( "park_reason" ),
            next_chase_ts  = datetime.fromisoformat( raw ) if raw else None,
            title          = ( payload or {} ).get( "title" ),
            session_id     = ( payload or {} ).get( "session_id" ),
        )


def _default_serialize( item, event ):
    """
    The `{ item, event }` body a synchronous 200 would have carried.

    🔴 IMPORTED LAZILY, AND NOT OUT OF TIDINESS. `routers.tasks` imports THIS module to
    hand off the ask, so a module-level import here would be a cycle. The same shape
    `task_promotion_gate._default_ask` already uses for `notify_user_sync`.

    ⚠️ IT CALLS THE ROUTER'S OWN SERIALIZERS RATHER THAN REBUILDING THE SHAPE. A second
    serializer would be a second derivation of the response body, and the whole reason
    this body is stored at all is that a re-derived answer is not the same answer
    (design §5.4.1).
    """
    from cosa.rest.routers.tasks import _serialize_item, _serialize_event
    return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


def _now():
    return datetime.now( timezone.utc )


def resolve_ticket( ticket_id,
                    db_fn        = get_db,
                    approval_fn  = promotion_gate.approval_from_the_ask,
                    ask_fn       = None,
                    serialize_fn = _default_serialize,
                    now_fn       = _now,
                    alarm_fn     = None ):
    """
    Ask Rick about one pending ticket, then apply or refuse it — in THREE phases,
    and the phase boundaries are the whole design.

    🔴 PHASE 2 HOLDS NO DATABASE CONNECTION, AND THAT IS THE ENTIRE POINT OF THE ROW.
    Today's synchronous door opens a transaction, takes `SELECT … FOR UPDATE`, and
    then asks Rick — holding a threadpool worker AND a pooled connection AND a lock on
    the row for up to the ask timeout, with no commit in between. Splitting the read
    from the apply is what puts the human's thinking time outside the transaction. A
    resolver that kept the session open across the ask would have moved the waiting
    without removing any of its cost.

    🔴 AND PHASE 3 RE-VALIDATES RATHER THAN REPLAYING. Between the 202 and the answer
    the row may have moved, gone terminal, or been dropped. The synchronous door cannot
    have that problem because it never lets the lock go; this one gives the lock up, so
    it has to buy back the guarantee by checking again under a fresh lock. A ticket
    whose transition is no longer legal resolves `superseded` carrying the validator's
    own words, and NOT `refused` — Rick did not refuse anything, the world moved.

    ⚠️ IDEMPOTENT BY CONSTRUCTION, WHICH IS WHAT LETS THE SWEEPER BE SUSPENDERS RATHER
    THAN A SECOND OPINION. Both phase 1 and phase 3 refuse to act on a ticket that is
    no longer `pending`, and phase 3 re-reads that state UNDER THE TICKET'S OWN LOCK.
    So whoever arrives first applies the transition and the other finds it applied.
    Design §6.2.

    Requires:
        - ticket_id identifies a `task_promotion_tickets` row
        - the caller has ALREADY passed `promotion_gate.promotion_precheck` — this
          function never re-decides who may promote, and deliberately cannot (see
          `TransitionIntent`, which does not persist the account identity)

    Ensures:
        - returns the ticket's terminal state, or the state it already held
        - returns None when no such ticket exists — never a silent success
        - a ticket that is not `pending` is returned UNCHANGED, no ask fired
        - `approved` carries `response_body` — the exact `{ item, event }` a
          synchronous 200 would have returned, serialized inside the transaction that
          wrote it
        - `refused` carries `refusal`, satisfying the table's own CHECK
        - `superseded` carries the validator's words in `refusal`
        - an apply that BLOWS UP marks the ticket `stalled` in a fresh transaction and
          names the exception, rather than leaving a pending row that looks healthy
        - never leaves a ticket `pending` on any path it completed
    """
    # ── PHASE 1 · read the intent, then LET GO ──────────────────────────────────
    with db_fn() as session:
        ticket = session.get( TaskPromotionTicket, ticket_id )
        if ticket is None: return None
        if ticket.state != TICKET_PENDING: return ticket.state
        intent  = TransitionIntent.from_payload( ticket.payload )
        item_id = ticket.item_id
    # The connection is back in the pool here. Nothing below phase 3 touches the DB.

    # ── PHASE 2 · the ask. No connection, no lock, no transaction. ──────────────
    kwargs = {}
    if ask_fn is not None: kwargs[ "ask_fn" ] = ask_fn
    approval = approval_fn(
        session_id = intent.session_id,
        actor      = intent.actor,
        task_id    = item_id,
        title      = intent.title,
        **kwargs
    )

    # ── PHASE 3 · a SHORT transaction: re-lock, re-validate, apply. ─────────────
    try:
        return _apply_resolution( ticket_id, item_id, intent, approval,
                                  db_fn=db_fn, serialize_fn=serialize_fn, now_fn=now_fn )
    except Exception as e:
        # 🔴 DECLINE RATHER THAN NO-OP. The transaction above rolled back, so the
        # ticket is still `pending` and looks exactly like a healthy in-flight ask.
        # Leaving it that way would hand the sweeper a row it can only ever call an
        # orphan, minutes later, with the actual exception long gone. This writes the
        # failure down where the caller polling the ticket will find it.
        #
        # ⚠️ AND IF THIS WRITE FAILS TOO, the ticket stays `pending` and the sweeper
        # gets it — belt, suspenders, and a floor. That is the correct residue for a
        # database that is itself unreachable, and it is why this does not re-raise
        # into a background task nobody is reading.
        stall_kwargs = { "alarm_fn": alarm_fn } if alarm_fn is not None else {}
        _mark_stalled( ticket_id, db_fn=db_fn, now_fn=now_fn, detail=(
            f"the promotion could not be applied after the ask: "
            f"{type( e ).__name__}: {e}"
        ), **stall_kwargs )
        return TICKET_STALLED


def _apply_resolution( ticket_id, item_id, intent, approval,
                       db_fn=get_db, serialize_fn=_default_serialize, now_fn=_now ):
    """
    Phase 3 in one transaction: the ticket's lock, the row's lock, the validator, the
    apply.

    Ensures:
        - takes the TICKET's lock before the ITEM's, and re-reads the ticket state
          under it — two resolvers racing cannot both apply
        - returns the resulting ticket state
    """
    with db_fn() as session:
        repo   = TaskRepository( session )
        ticket = session.get( TaskPromotionTicket, ticket_id, with_for_update=True )
        if ticket is None: return None
        if ticket.state != TICKET_PENDING: return ticket.state

        ticket.approval_source = approval.approval_source
        ticket.resolved_at     = now_fn()

        if not approval.allowed:
            # Rick said no, or the ask never reached him. Either way the gate has
            # already written the sentence that says which; storing our own would be a
            # second account of one event.
            ticket.state   = TICKET_REFUSED
            ticket.refusal = approval.refusal
            return TICKET_REFUSED

        item = repo.get_by_id_for_update( item_id )
        if item is None:
            # The row was deleted while Rick was thinking. Not a refusal — he said yes
            # to something that no longer exists.
            ticket.state   = TICKET_SUPERSEDED
            ticket.refusal = (
                f"Rick approved this promotion, but task {item_id} no longer exists, "
                f"so there was nothing to promote."
            )
            return TICKET_SUPERSEDED

        errors = rules.validate_transition(
            from_status           = item.status,
            to_status             = intent.to_status,
            authority             = intent.authority,
            receipt_refs          = intent.receipt_refs,
            next_chase_ts         = intent.next_chase_ts,
            blocked_by            = intent.blocked_by,
            reason                = intent.reason,
            park_reason           = intent.park_reason,
            current_blocked_by    = item.blocked_by,
            current_next_chase_ts = item.next_chase_ts,
        )
        if errors:
            # 🔴 `superseded`, NOT `refused`, AND THE DISTINCTION IS THE WHOLE VALUE OF
            # THIS BRANCH. A reader of a refused ticket learns that Rick or the gate
            # said no. A reader of a superseded one learns that the answer was fine and
            # the WORLD moved — which is the only reading that tells them to look at
            # what else touched the row. Collapsing the two would put a decision in
            # Rick's mouth that he did not make, the one thing this gate forbids.
            ticket.state   = TICKET_SUPERSEDED
            ticket.refusal = (
                f"Rick approved this promotion, but it was no longer legal when the "
                f"answer landed (the row is now '{item.status}'): {'; '.join( errors )}"
            )
            return TICKET_SUPERSEDED

        event = repo.apply_transition(
            item          = item,
            to_status     = intent.to_status,
            actor         = intent.recorded_actor,
            authority     = intent.authority,
            receipt_refs  = intent.receipt_refs,
            next_chase_ts = intent.next_chase_ts,
            blocked_by    = intent.blocked_by,
            reason        = approval.reason_with_suffix( intent.reason ),
            park_reason   = intent.park_reason,
        )

        # 🔴 SERIALIZED HERE, INSIDE THE TRANSACTION THAT WROTE IT, AND THIS LINE IS
        # THE REASON THE COLUMN EXISTS (design §5.4.1). A poll that re-read the row
        # instead would get a moved `updated_ts`, an event looked up rather than handed
        # over, and — under a concurrent writer — an item describing a LATER state than
        # the event beside it. Equality with today's 200 holds by construction here and
        # by hope anywhere else.
        ticket.response_body = serialize_fn( item, event )
        ticket.state         = TICKET_APPROVED
        return TICKET_APPROVED


# ── THE ORPHAN PATH: STALLED, AND LOUD ABOUT IT ─────────────────────────────────────
#
# 🔴 IT PUSHES. IT DOES NOT JUST BECOME QUERYABLE. Mr. Radio's measurement on this very
# row is the reason: all three rows Rick was listed on had already passed their chase
# times — 14:00Z, 15:00Z, 18:00Z — and rejoined the owed count SILENTLY. Nothing fired at
# him. A state that expires into a list is a state nobody looks at, so the stalled path
# notifies and the pending listing is the supplement, never the mechanism. Design §6.3.

def _default_alarm( ticket_id, item_id, requested_by, resolves_by, detail, now ):
    """
    Tell a human that a promotion ask died without an answer.

    Ensures:
        - fires at `urgent`, which is the one priority that reaches somebody who is not
          already looking at the screen
        - never raises — an alarm that takes the sweeper down with it would silence
          every LATER orphan to report this one
    """
    try:
        from lupin_cli.notifications.notify_user_async import notify_user_async
        from lupin_cli.notifications.notification_models import (
            AsyncNotificationRequest, NotificationType, NotificationPriority
        )
        overdue_by = now - resolves_by if resolves_by is not None else None
        minutes    = int( overdue_by.total_seconds() // 60 ) if overdue_by is not None else 0
        notify_user_async( AsyncNotificationRequest(
            message           = (
                f"A promotion out of the holding area was never answered. "
                f"{requested_by} asked about a task {minutes} minutes past its deadline, "
                f"and the row has not moved."
            ),
            notification_type = NotificationType.ALERT,
            priority          = NotificationPriority.URGENT,
            sender_id         = promotion_gate.promotion_ask_sender_id( None ),
            abstract          = (
                f"**Stalled promotion ticket**\n\n"
                f"- ticket: `{ticket_id}`\n"
                f"- task: `{item_id}`\n"
                f"- requested by: {requested_by}\n"
                f"- should have resolved by: {resolves_by}\n"
                f"- why: {detail}\n\n"
                f"Nothing was promoted. Re-issue the promotion if it is still wanted."
            ),
        ) )
    except Exception as e:
        # Deliberately swallowed and NAMED. See the docstring: the sweeper's job is to
        # report every orphan, and a raise here would abandon the rest of the batch.
        print( f"[ERROR] stalled-ticket alarm failed for {ticket_id}: {type( e ).__name__}: {e}" )


def _mark_stalled( ticket_id, db_fn=get_db, now_fn=_now, alarm_fn=_default_alarm,
                   require_overdue=False,
                   detail="the ask did not resolve before its deadline" ):
    """
    Move one pending ticket to `stalled` and fire the alarm.

    🔴 EVERY WRITER OF `stalled` GOES THROUGH HERE, WHICH IS WHAT KEEPS THEM TO ONE
    CONTRACT. Pocholo 📣's point, 2026-09-06: the sweeper and startup reconciliation are
    two callers, and two callers each holding their own idempotency rule are two writers
    that can disagree about a settled ticket. They do not have their own rule. They have
    this one, and the ticket's own lock enforces it.

    🔴 `require_overdue` RE-CHECKS THE DEADLINE IN PYTHON, UNDER THE LOCK, AND IT IS NOT
    REDUNDANT WITH THE SWEEPER'S SQL FILTER. The filter chooses CANDIDATES; this decides.
    A safety property that lives only in a query is invisible to every reader of this
    function and untestable without a database — and a third caller added later would
    inherit the state check and silently NOT inherit the deadline check, which is exactly
    the shape of defect the paragraph above is about.

    ⚠️ Startup passes False DELIBERATELY, and that is a different claim rather than a
    weaker one: its evidence is the PROCESS BOUNDARY, not the clock. See
    `reconcile_on_startup`.

    Requires:
        - ticket_id identifies a ticket

    Ensures:
        - a ticket that is not `pending` is left alone and NO alarm fires — this is what
          makes the sweeper safe to run beside a live resolver
        - with `require_overdue`, a ticket whose deadline has NOT passed is left alone
          and NO alarm fires
        - `resolved_at` is stamped, satisfying the table's CHECK
        - the alarm fires OUTSIDE the transaction, so a slow notification surface cannot
          hold a connection open, which is the defect this whole row is about
        - returns True when it stalled a ticket, False when there was nothing to do
    """
    now = now_fn()
    with db_fn() as session:
        ticket = session.get( TaskPromotionTicket, ticket_id, with_for_update=True )
        if ticket is None:                     return False
        if ticket.state != TICKET_PENDING:     return False
        # 🔴 A NULL DEADLINE IS NOT OVERDUE — Tiffany 💍's finding, 2026-09-06, and the
        # first cut of this line had it backwards. It read `resolves_by is not None and
        # resolves_by >= now`, so a NULL deadline fell THROUGH the guard and the ticket
        # was stalled. SQL's `resolves_by < now` is NULL for that row, which is not TRUE,
        # so the sweeper's own query would never have selected it. Two layers, one
        # question, opposite answers — the exact defect this re-check was added to close,
        # committed inside the fix for it.
        #
        # ⚠️ AND IT DIVERGED IN THE UNSAFE DIRECTION FOR AN ALARM. Every stall pushes an
        # urgent notification, so the Python side would have woken a human about a ticket
        # the SQL side considers permanently out of scope. `resolves_by` is NOT NULL in
        # the schema, so this is unreachable from the database today — but a check that
        # disagrees with the query it is paired with is wrong whether or not the input
        # that exposes it can arrive.
        if require_overdue and ( ticket.resolves_by is None or ticket.resolves_by >= now ):
            return False
        ticket.state       = TICKET_STALLED
        ticket.resolved_at = now
        ticket.refusal     = detail
        alarm_args = ( ticket.id, ticket.item_id, ticket.requested_by, ticket.resolves_by )

    alarm_fn( *alarm_args, detail=detail, now=now )
    return True


def sweep_stalled_tickets( db_fn=get_db, now_fn=_now, alarm_fn=_default_alarm ):
    """
    The suspenders: find pending tickets past their deadline, stall them, and shout.

    🔴 THE DEADLINE COMES OFF THE ROW, NOT OFF TODAY'S CONFIG. `resolves_by` was written
    when the ticket was minted, under the timeout in force AT THAT MOMENT. Re-deriving
    it here would let an operator lowering the dial retroactively declare in-flight
    tickets overdue — see `resolves_by_for`.

    ⚠️ IT MUST DISCRIMINATE, NOT MERELY FIRE. A sweeper that stalled every pending
    ticket would satisfy "the alarm fires" and be worthless: the in-flight ask is the
    common case and it is the one that must stay silent. The guard for this carries both
    arms for that reason — past the deadline fires, inside it says nothing.

    Ensures:
        - returns the list of ticket ids it stalled (possibly empty)
        - touches no ticket whose `resolves_by` is in the future
        - touches no ticket that is not `pending`
        - one ticket's failure does not abandon the rest of the batch
    """
    now = now_fn()
    with db_fn() as session:
        overdue = [
            t.id for t in session.query( TaskPromotionTicket )
                                 .filter( TaskPromotionTicket.state       == TICKET_PENDING )
                                 .filter( TaskPromotionTicket.resolves_by <  now )
                                 .all()
        ]

    stalled = []
    for ticket_id in overdue:
        try:
            if _mark_stalled( ticket_id, db_fn=db_fn, now_fn=now_fn, alarm_fn=alarm_fn,
                              require_overdue=True ):
                stalled.append( ticket_id )
        except Exception as e:
            print( f"[ERROR] could not stall promotion ticket {ticket_id}: "
                   f"{type( e ).__name__}: {e}" )
    return stalled


def reconcile_on_startup( db_fn=get_db, now_fn=_now, alarm_fn=_default_alarm ):
    """
    Every ticket left `pending` by a dead process is an orphan, and startup is when we
    know that for free.

    🔴 THE PROCESS BOUNDARY IS THE EVIDENCE, AND IT IS STRONGER THAN THE DEADLINE. An
    ask runs on a background worker inside THIS process. So a ticket that is `pending`
    while this function runs was minted by a process that no longer exists, and its
    worker died with it — no timer needs to expire for that to be true. Waiting for
    `resolves_by` would leave a known-dead ask looking healthy for up to the ask timeout
    plus the grace.

    ⚠️ THIS IS WHERE THE MISSING RECOVERY BITES, AND IT IS NAMED RATHER THAN HIDDEN.
    Design §6.3 wanted this function to read the notification's `responded_at` off the
    ticket's `notification_id` and APPLY an answer Rick gave in the seconds before the
    bounce. `notification_id` is not populated in this landing — see the module
    docstring — so that answer cannot be recovered here and the ticket goes `stalled`
    with a human told. Loud and lossy beats quiet and lossy; it does not beat correct,
    and this is not claimed to be correct yet.

    Ensures:
        - returns the list of ticket ids it stalled
        - fires the same urgent alarm the sweeper does, for the same reason
        - is safe to run when the table is empty, and reports zero rather than nothing
    """
    with db_fn() as session:
        orphans = [
            t.id for t in session.query( TaskPromotionTicket )
                                 .filter( TaskPromotionTicket.state == TICKET_PENDING )
                                 .all()
        ]

    stalled = []
    for ticket_id in orphans:
        try:
            if _mark_stalled(
                ticket_id, db_fn=db_fn, now_fn=now_fn, alarm_fn=alarm_fn,
                detail=( "the server restarted while this ask was out, so the worker "
                         "that would have applied the answer no longer exists" ),
            ):
                stalled.append( ticket_id )
        except Exception as e:
            print( f"[ERROR] could not reconcile promotion ticket {ticket_id}: "
                   f"{type( e ).__name__}: {e}" )
    return stalled
