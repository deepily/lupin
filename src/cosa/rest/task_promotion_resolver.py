"""
Resolves a pending promotion ticket after the caller has already been answered.

The caller gets a 202 first. This module then asks the owner, re-validates, applies the
transition and records an outcome the caller can poll. A 202 that left the manager unable to
learn the outcome would only move the waiting somewhere nobody looks.

The synchronous door holds a row lock for the whole ask, so the row cannot move between the
decision and the apply. Letting go of that lock is what makes the 202 possible, so the lock is
bought back here: every apply re-validates under a fresh lock. A ticket whose transition is no
longer legal resolves `superseded` and carries the validator's own words. Replaying a stale
intent onto a moved row is the defect this design would otherwise introduce.

Not built: recovery of an answer orphaned by a bounce. The design would read the notification's
`responded_at` off the stored `notification_id`. `NotificationResponse` does not carry the id.
`notify_user_sync` captures it from the opening ack frame into a local dict and never surfaces
it. That holds across fifteen construction sites, so the ticket's `notification_id` column
stays `NULL`.
After a bounce a pending ticket therefore goes `stalled` and fires the urgent notify. A human
is told and nothing is lost silently. Automatic recovery of an answer given just before the
bounce is a named follow-up.
"""

from dataclasses import dataclass
from datetime    import datetime, timedelta, timezone
from typing      import Optional
import uuid

from cosa.rest.db.database                       import get_db
from cosa.rest.db.repositories.task_repository   import TaskRepository
from cosa.rest.postgres_models                   import TaskPromotionTicket
from cosa.rest.task_approval_settings            import _ini_value
from cosa.rest import task_store_rules   as rules
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest import task_approval_settings as approval_settings
# For OPERATOR_ONLY_PRIORITY only — the resolver pins a petition's priority against the
# firewall's own constant rather than a literal "P0", so the two cannot drift apart.
from cosa.rest import task_priority_firewall as firewall


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

# ── HOW LONG AN ANSWER CAN STILL ARRIVE, AND HOW LONG APPLYING IT TAKES ─────────────
#
# 🔴 THESE ARE TWO DISJOINT INTERVALS AND THE ORIGINAL CODE HAD ONLY ONE OF THEM.
# `ASK_GRACE_SECONDS = 60` used to carry the whole distance between "the ask can no
# longer be running" and "this ticket is an orphan", on the premise that the ask stops
# being answerable when it times out. THAT PREMISE IS FALSE. Tiffany 💍 found the gap
# and Mr. Radio ruled the fix: derive it from the notification grace, at mint time.
#
# The notification API accepts a LATE answer for `notification grace period seconds`
# after the ask expired — `routers/notifications.py:616-629`, which reads that same INI
# key. With the shipped values that answer stayed valid until requested_at + 420 while
# this deadline stalled the ticket at requested_at + 180: a 240-second window in which a
# real keypress was still being accepted by one half of the system and the other half had
# already declared the ticket an orphan and fired an urgent alarm at a human.
#
# ⚠️ WHY DERIVED AND NOT SIMPLY RAISED TO 300. Mr. Radio refused the raise, and the
# reason is this repo's own rule rather than taste: two independently-configured numbers
# pinned by convention agree until somebody edits one, and nothing fires when they stop.
# An operator lowering `notification grace period seconds` to 30 would silently re-open
# the window against a constant nobody thought to move. So the deadline READS the key the
# notification router reads. One decider, not two numbers that happen to match today.
INI_KEY_NOTIFICATION_GRACE          = "notification grace period seconds"
FALLBACK_NOTIFICATION_GRACE_SECONDS = 300


def get_notification_grace_seconds():
    """
    How long after an ask expires the notification API will still take an answer.

    This setting belongs to the notification subsystem. The router reads the same key, so one
    setting decides both sides, where two constants that happen to be equal would drift apart.

    Ensures:
        - returns the configured int, or the fallback when absent/unreadable
        - never raises
        - the fallback matches the router's own default of 300, so an unreadable key leaves both
          halves on the same assumption instead of a deadline that disagrees with the late window
    """
    return _ini_value( INI_KEY_NOTIFICATION_GRACE, int, FALLBACK_NOTIFICATION_GRACE_SECONDS )


# The resolver's OWN room — one short transaction that re-locks the row, re-validates
# and applies, AFTER the answer has landed.
#
# 🔴 IT SURVIVED THE DERIVATION AS A SEPARATE NUMBER ON PURPOSE, AND IT IS NOT A SECOND
# COPY OF ANYTHING. It prices work this module does; the grace above prices how long the
# world may still speak. Collapsing them — letting 300 stand in for both because 300 is
# comfortably larger than 60 — would delete the only stated reason this margin exists,
# and the next operator to lower the notification grace to 5 would re-create the original
# defect: a healthy ticket declared an orphan while its resolver is still committing.
#
# ⚠️ TOO SMALL AND A HEALTHY TICKET IS DECLARED AN ORPHAN MID-COMMIT — a false alarm that
# fires an urgent notify at a human. Too large and a real orphan sits quiet for longer.
# The asymmetry favours the larger value: a late alarm is late, an alarm that cries wolf
# is the one that stops being read.
APPLY_MARGIN_SECONDS = 60


def resolves_by_for( requested_at, timeout_fn=promotion_gate.get_ask_timeout_seconds,
                     grace_fn=get_notification_grace_seconds,
                     apply_margin_seconds=APPLY_MARGIN_SECONDS ):
    """
    When a ticket minted at `requested_at` must have resolved by.

    The deadline adds three intervals. The ask timeout is the operator's setting. The notification
    grace is how long a late answer is still taken. The apply margin is this module's own re-lock
    and apply.

    Requires:
        - requested_at is a timezone-aware datetime
        - timeout_fn returns the ask timeout in seconds
        - grace_fn returns the notification grace in seconds

    Ensures:
        - returns a timezone-aware datetime strictly after requested_at
        - the result clears the late-answer window the notification API will honour
        - never raises for a well-formed input
        - the deadline is read at mint time and stored on the row, because both settings are live; a
          sweeper that re-derived it would judge tickets against changed numbers and declare
          in-flight tickets overdue
        - a window remains that no finite deadline closes: the router's grace check applies only once
          the notification is marked `expired`, and only the live ask sets that; after a bounce the
          notification stays `delivered` and /respond accepts an answer at any later time; closing
          it needs the late-answer recovery named in the module docstring
        - it measures from `requested_at` while the answer window runs from when the ask fires, one
          short transaction later; the apply margin absorbs that skew, so the result errs safe
    """
    return deadlines_for( requested_at, timeout_fn=timeout_fn, grace_fn=grace_fn,
                          apply_margin_seconds=apply_margin_seconds ).resolves_by


# What a caller holding both stamps is told they mean (row dbe42964). One string, carried
# by every surface that hands out a deadline, so the 201, the 202 and the poll cannot
# explain the pair three different ways.
DEADLINES_NOTE = (
    "answer_by is when Rick's answer window closes (the ask timeout). resolves_by is the "
    "stall deadline (ask timeout + notification grace + apply margin): a ticket still "
    "pending after it is an orphan. An ask unanswered by answer_by is refused, never granted."
)


@dataclass( frozen=True )
class PromotionDeadlines:
    """
    The two times a ticket is stamped with, which are different facts.

    Ensures:
        - answer_by   is when Rick's answer window closes
        - resolves_by is when an unresolved ticket becomes an orphan
        - answer_by <= resolves_by
    """
    answer_by   : datetime
    resolves_by : datetime


def deadlines_for( requested_at, timeout_fn=promotion_gate.get_ask_timeout_seconds,
                   grace_fn=get_notification_grace_seconds,
                   apply_margin_seconds=APPLY_MARGIN_SECONDS ):
    """
    Both deadlines of a ticket minted at `requested_at`, from one read of the ask timeout.

    The timeout setting is live. Two reads, one per stamp, could straddle an operator's edit and
    leave a row with two deadlines computed under different timeouts. Deriving `resolves_by` from
    `answer_by` makes their gap the notification grace plus the apply margin.

    Requires:
        - requested_at is a timezone-aware datetime
        - timeout_fn returns the ask timeout in seconds
        - grace_fn returns the notification grace in seconds

    Ensures:
        - answer_by   == requested_at + ask timeout
        - resolves_by == answer_by + notification grace + apply margin
        - timeout_fn is called exactly once
        - `answer_by` counts from `requested_at` and the ask fires one short transaction later, so
          the stamp is early by the length of the mint transaction, never late
    """
    answer_by   = requested_at + timedelta( seconds=int( timeout_fn() ) )
    resolves_by = answer_by + timedelta( seconds = int( grace_fn() )
                                                 + int( apply_margin_seconds ) )
    return PromotionDeadlines( answer_by=answer_by, resolves_by=resolves_by )


@dataclass( frozen=True )
class TransitionIntent:
    """
    The caller's transition, in the shape the resolver needs to replay it.

    One class knows the shape in both directions. The mint site writes this dict and the resolve
    site reads it, far apart in time and in another process. A writer and a reader that each know
    the shape separately agree only until someone adds a field to one of them.

    The caller's account identity is absent, and so are the ask-exempt and manager decisions.
    `promotion_gate.promotion_precheck` settled those before the 202 was sent. A stored
    authorization decision could be forged by anyone able to write this JSON, so it is not
    persisted. The resolver never re-decides who may promote.
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
    # THE PETITION'S SECOND EFFECT (row 9c26bf04). None on every ordinary admission —
    # this field exists only for a P0 petition, and `_apply_resolution` pins it to
    # OPERATOR_ONLY_PRIORITY rather than trusting whatever the payload carries.
    #
    # ⚠️ DEFAULTED so every existing construction site keeps working unchanged. A
    # required field here would have made this a breaking change to a shape written in
    # one process and read in another, which is exactly what this class's own docstring
    # warns about.
    priority      : Optional[ str ] = None

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
            "priority"       : self.priority,
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
            # Read back unvalidated, exactly like every field above it — this method
            # has never validated anything. The check lives at the APPLY site, where a
            # non-P0 value refuses the ticket outright. Validating here as well would
            # put the same rule in two places, and two pieces of code deciding one rule
            # agree until they do not.
            priority       = ( payload or {} ).get( "priority" ),
        )


def _default_serialize( item, event ):
    """
    The `{ item, event }` body a synchronous 200 would have carried.

    The router module is imported lazily. `routers.tasks` imports this module to hand off the ask,
    so a module-level import here would be a cycle. `task_promotion_gate._default_ask` does the
    same for `notify_user_sync`.
    It calls the router's own serializers instead of rebuilding the shape. A second serializer
    would derive the response body twice, and a re-derived answer is not the stored answer.
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
    Ask the owner about one pending ticket, then apply or refuse it, in three phases.

    The first step reads the intent and releases the connection. The ask step holds no connection,
    lock or transaction, so the human's thinking time stays outside the database. The apply step
    re-locks and re-validates, because the row may have moved since the 202.

    Requires:
        - ticket_id identifies a `task_promotion_tickets` row
        - the caller has already passed `promotion_gate.promotion_precheck`; this function
          never re-decides who may promote, and cannot (see `TransitionIntent`, which does not
          persist the account identity)

    Ensures:
        - returns the ticket's terminal state, or the state it already held
        - returns None when no such ticket exists, never a silent success
        - a ticket that is not `pending` is returned unchanged, no ask fired
        - `approved` carries `response_body`, the exact `{ item, event }` a synchronous 200
          would have returned, serialized inside the transaction that wrote it
        - `refused` carries `refusal`, satisfying the table's own `CHECK`
        - `superseded` carries the validator's words in `refusal`
        - an apply that raises marks the ticket `stalled` in a fresh transaction and names the
          exception, rather than leaving a pending row that looks healthy
        - never leaves a ticket `pending` on any path it completed
        - a transition no longer legal resolves `superseded`, not `refused`: the owner refused
          nothing, the row moved
        - the first and apply steps both skip a ticket that is no longer `pending`, and the apply step re-reads the
          state under the ticket's own lock, so the first arrival applies and the other finds it
          applied; that is why the sweeper is a backstop and not a second opinion
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
    #
    # 🔴 THE ASK HAS TO NAME THE DIRECTION, BECAUSE ONE TICKET NOW CARRIES TWO VERBS
    # (Rick's ruling 2026-09-08, row c9fafb9d — managers may REQUEST a promote or a
    # demote). Without this the card would tell him a demote request wanted to
    # "promote this row out of the holding area", which is the opposite of what his
    # keypress would do. A false fact in the one surface where a false fact IS the
    # decision.
    #
    # ⚠️ DERIVED FROM `intent.to_status`, NOT PERSISTED AS A NEW FIELD, AND THAT IS
    # DELIBERATE. `TransitionIntent` is written by the mint site and read here, so a
    # new field would have to be defaulted for every ticket already in flight — and a
    # default is exactly where a two-verb bug hides. `move_for_ticket` answers it from
    # a field the ticket has always carried, so an OLD payload classifies correctly
    # with no migration. It is the approval module's own rule, not a copy of it.
    kwargs = {}
    if ask_fn is not None: kwargs[ "ask_fn" ] = ask_fn
    approval = approval_fn(
        session_id = intent.session_id,
        actor      = intent.actor,
        task_id    = item_id,
        title      = intent.title,
        move       = approval_settings.move_for_ticket( intent.to_status ),
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
    The apply step of a promotion, in one transaction: lock, re-validate, apply.

    The fresh session is the guarantee, not the lock. `SELECT ... FOR UPDATE` serializes the row
    at the database but does not refresh objects the session already holds. A session that had
    loaded this ticket or task would re-validate stale values under a lock that looks careful.

    Requires:
        - db_fn yields a session whose identity map is empty

    Ensures:
        - takes the ticket's lock before the item's, and re-reads the ticket state
          under it, so two resolvers racing cannot both apply
        - returns the resulting ticket state
        - the identity-map check runs before the first read, because every later read legitimately
          fills the map; `get_db` builds a new session per call, so production never trips it, but
          a caller threading an existing session through for efficiency would

    Raises:
        - RuntimeError if handed a session that has already loaded objects, naming the
          count rather than failing somewhere later as a stale read
    """
    with db_fn() as session:
        if session.identity_map:
            raise RuntimeError(
                f"_apply_resolution was handed a session already holding "
                f"{len( session.identity_map )} object(s). Phase 3 must re-validate "
                f"against a FRESH session: FOR UPDATE serializes the row at the database "
                f"but does not refresh attributes this session already has, so the "
                f"re-validation would read stale values under a correct-looking lock. "
                f"Pass `db_fn=get_db` (the default) rather than an open session."
            )

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

        # Safe for populate_existing: the identity-map refusal above proves this session
        # loaded nothing before the ticket, and the ticket is a different row. The static
        # guard (test_every_locked_read_is_the_first_load_in_its_session.py) reads that refusal.
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

        # ── THE PETITION'S SECOND EFFECT (Rick's ruling 2026-09-09, row 9c26bf04) ──
        #
        # He was asked whether ONE approval should raise the priority AND admit the
        # row, and chose both: "reprioritized and then pushed into the live queue."
        # When he orders a P0 by voice he means do this now, not file it politely.
        #
        # 🔴 IT IS WRITTEN INSIDE THE SAME TRANSACTION AS THE TRANSITION, and that is
        # not tidiness. A partial application — raised but not admitted, or admitted
        # but not raised — is the invisible-work state twice over: a P0 nobody can see
        # in the holding area, or a live row wearing the wrong urgency. One keypress,
        # one atomic write, or neither.
        #
        # 🔴 THE VALUE IS PINNED, NOT VALIDATED, AND THE DIFFERENCE IS THE CONTROL.
        # `from_payload` performs NO validation — it is a bare `.get()` per field — so
        # whatever sits in the JSONB arrives here unchecked, and unlike `to_status`
        # there is no `validate_transition` downstream to catch a priority. A petition
        # ticket can only ever mean P0; accepting any *valid* priority would widen this
        # into a general priority-setting channel, which is not what Rick approved.
        # So a ticket carrying anything else is malformed or tampered and REFUSES.
        # (María 🌸 found the missing validation; pinning rather than validating is
        # what her finding sharpened into.)
        if intent.priority is not None:
            if intent.priority != firewall.OPERATOR_ONLY_PRIORITY:
                ticket.state   = TICKET_REFUSED
                ticket.refusal = (
                    f"petition ticket carries priority '{intent.priority}', but a "
                    f"petition may only ever grant {firewall.OPERATOR_ONLY_PRIORITY}. "
                    "Nothing was applied — this ticket is malformed."
                )
                return TICKET_REFUSED
            item.priority = intent.priority

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
        - never raises, because an alarm that took the sweeper down with it would silence
          every later orphan to report this one
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

    Every writer of `stalled` goes through here, so they all share one idempotency rule, enforced
    by the ticket's own lock. Two callers with rules of their own could disagree about a settled
    ticket, and the sweeper and startup reconciliation are two callers.

    Requires:
        - ticket_id identifies a ticket

    Ensures:
        - a ticket that is not `pending` is left alone and no alarm fires, which is what
          makes the sweeper safe to run beside a live resolver
        - with `require_overdue`, a ticket whose deadline has not passed is left alone
          and no alarm fires
        - `resolved_at` is stamped, satisfying the table's `CHECK`
        - the alarm fires outside the transaction, so a slow notification surface cannot
          hold a connection open
        - returns True when it stalled a ticket, False when there was nothing to do
        - `require_overdue` re-checks the deadline in Python under the lock. The sweeper's SQL
          filter only chooses candidates; a rule living only in the query would be invisible to
          readers, untestable without a database, and a third caller would inherit the state check
          but not the deadline check
        - a `NULL` deadline is not overdue: SQL's `resolves_by < now` is `NULL` for it, so the
          sweeper's query never selects it, and the Python check agrees; disagreeing would wake a
          human about a ticket the query treats as out of scope
        - startup passes False because its evidence is the process boundary, not the clock (see
          `reconcile_on_startup`)
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
    The backstop: find pending tickets past their deadline, stall them, and raise the alarm.

    The deadline comes off the row, not today's config. `resolves_by` was written at mint time
    under the timeout then in force. Re-deriving it here would let an operator lowering the
    setting declare in-flight tickets overdue (see `resolves_by_for`).

    Ensures:
        - returns the list of ticket ids it stalled (possibly empty)
        - touches no ticket whose `resolves_by` is in the future
        - touches no ticket that is not `pending`
        - one ticket's failure does not abandon the rest of the batch
        - it discriminates: an in-flight ask is the common case and must stay silent, so a sweeper
          that stalled every pending ticket would fire the alarm and still be wrong
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
    Stall every ticket still `pending` at startup, since a dead process left it orphaned.

    An ask runs on a background worker inside this process. A ticket that is `pending` while this
    runs was therefore minted by a process that no longer exists. That evidence is stronger than
    the deadline, which would leave a known-dead ask looking healthy for the ask timeout plus grace.

    Ensures:
        - returns the list of ticket ids it stalled
        - fires the same urgent alarm the sweeper does, for the same reason
        - is safe to run when the table is empty, and reports zero rather than nothing
        - an answer given just before a bounce is not recovered: the design would read the
          notification's `responded_at` off the ticket's `notification_id`, but this module never
          populates that column (see the module docstring), so the ticket goes `stalled` and a human
          is told; that is loud and lossy, not yet correct
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
