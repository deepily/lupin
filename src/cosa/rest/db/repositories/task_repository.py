"""
Task repository for the unified task store.

This layer only persists. Structural validation lives in cosa.rest.task_store_rules,
as pure functions the router calls before any repository write.
Every state change writes one append-only TaskEvent row in the same session that updates the TaskItem.
The caller's get_db() transaction makes the pair atomic. The design lives in the planning-is-prompting repository.
"""

from datetime import datetime, timezone
from typing import Optional, List
import uuid

from sqlalchemy import func, select, cast, String, and_, or_
from sqlalchemy.orm import Session, joinedload

from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.db.repositories.base import BaseRepository

# ---------------------------------------------------------------------------
# Closed-vs-new ratio gate — the two SQL LIKE patterns, exported so they can be
# tested against a real LIKE engine rather than asserted through a mock.
# ---------------------------------------------------------------------------
#
# A creation stamp has an EMPTY left side ("->queued", "->blocked"); a closure
# has any left side and "done" on the right. Census, whole board, lupin_db_dev,
# 2026-09-01 — these are matched patterns, NOT an enumerated status list, because
# a list is something somebody has to keep current:
#
#   created  ->queued 2292 · ->blocked 4
#   closed   in_progress->done 941 · queued->done 659 · blocked->done 210
#            review->done 56 · parked->done 24
#
# Neither pattern matches the non-arrow events (amended 2086, patched 1123,
# amended_post_terminal 188, re-correlated 108), and "%->dropped" is deliberately
# NOT a closure — see count_created_and_closed's docstring for why that exclusion
# is the load-bearing choice.
CREATED_TRANSITION_LIKE = "->%"
CLOSED_TRANSITION_LIKE  = "%->done"
# Rows under this correlation-key prefix are excluded from both counts — the worktree
# janitor's straggler tickets (cosa.agents.shared.worktree_straggler_tickets).
FLOW_EXCLUDED_KEY_PREFIX = "worktree:"
from cosa.rest.task_store_rules import (
    BOARD_INVISIBLE_STATUSES,
    TERMINAL_STATUSES,
    UNSCOPED_QUERY_THRESHOLD,
    UnscopedQueryError,
    is_unscoped,
    hyphenate_compact_prefix,
    normalize_status_fields,
    compose_drop_marker,
)
# PARKED-STATUS (2026-07-19) — the ONE canonical owed definition. This repository
# is the choke point all three readers funnel through (task_query / the Stop-hook
# COUNT(*) seam / the :8001 arbiter), so applying the clause HERE is what makes
# "three readers, one definition" true rather than aspirational. NEVER re-derive
# park-expiry locally — import it. Design: src/rnd/v0.1.9/2026.07.19-parked-status-board-hygiene.md
from cosa.rest.task_store_owed import (
    NOT_APPROVED_STATUS,
    PARK_STATUS,
    holding_is_active_clause,
    owed_clause,
    owed_status_clause,
)

# Whether a pending request survives a move is the lifecycle module's rule, asked here
# rather than restated (row c9fafb9d, design §7).
from cosa.rest import task_request_lifecycle as request_lifecycle
from cosa.rest import task_store_change_notifier as change_notifier


class TaskRepository( BaseRepository[TaskItem] ):
    """
    Repository for TaskItem with the task-store query and transition operations.

    Extends BaseRepository with:
        - create_item: item row plus "->queued" creation event in one unit
        - apply_transition: status change plus append-only event in one unit
        - query_tasks: the deterministic owed-work query, identical for every caller
        - get_events: the per-item audit trail
    """

    def __init__( self, session: Session ):
        """
        Initialize TaskRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                repo = TaskRepository( session )
                item = repo.create_item( ... )
        """
        super().__init__( TaskItem, session )

    def get_by_id_for_update( self, id: uuid.UUID ) -> Optional[TaskItem]:
        """
        Load one item with `SELECT ... FOR UPDATE` for read-validate-write, refreshing its row.

        The lock makes the second of two concurrent transitions wait, so the terminal lockout cannot be bypassed. The lock alone does not refresh a row the session already holds. populate_existing does, so never remove it. Without it, a session still holding a live reference to the row keeps its old attribute values. Guards: test_the_for_update_read_refreshes_a_row_the_session_already_holds, test_every_locked_read_is_the_first_load_in_its_session.

        Requires:
            - id is a TaskItem UUID
            - called inside the same get_db() transaction that will apply the transition,
              since the lock lives and dies with that transaction
            - the caller has not edited that instance earlier in this session and left it unflushed.
              Both session factories are built with autoflush off, on every construction path, so populate_existing
              overwrites a pending edit with the database row.
              This method is for load-validate-write, never for re-reading a row already edited in memory.

        Ensures:
            - returns the row-locked entity, or None if not found
            - the row is locked against concurrent writers for the life of the transaction
            - the returned instance's attributes are repopulated from that read even when
              this session already held the row, so a caller validating on item.status
              sees the committed value

        Returns:
            TaskItem instance or None
        """
        return (
            self.session.query( TaskItem )
            .filter( TaskItem.id == id )
            .populate_existing()
            .with_for_update()
            .first()
        )

    def find_by_id_prefix( self, compact_prefix: str, limit: int = 10 ) -> List[ TaskItem ]:
        """
        Find items whose id starts with a compact (hyphen-free) hex prefix.

        Supports the 8-hex form that fleet briefs use. This is a read path only.
        The mutating routes keep strict UUID typing. A prefix that resolves wrong on a read is merely wrong.
        On a write it would move a row nobody named.

        Requires:
            - compact_prefix is lowercase hex with the hyphens already stripped
              (task_store_rules.classify_task_ref produces exactly this shape);
              this method does not re-validate caller text
            - limit bounds the scan

        Ensures:
            - returns items whose canonical hyphenated id starts with the prefix, at most
              `limit` of them. The bound is deliberate: the caller only needs to tell none
              from one from more than one, and an unbounded `LIKE` on a growing table is an unscoped query
            - the compact prefix is re-hyphenated to canonical UUID positions before matching,
              so a prefix longer than 8 characters (which spans a hyphen) still matches
        """
        # Re-hyphenation via the SHARED rule — a bare LIKE on the compact form would
        # never match a prefix long enough to cross a hyphen. Single-sourced with the
        # `id_prefix` query filter (`_apply_scalar_filters`) so the two read paths
        # cannot drift about which rows a prefix names.
        hyphened = hyphenate_compact_prefix( compact_prefix )

        return (
            self.session.query( TaskItem )
            .filter( cast( TaskItem.id, String ).like( f"{hyphened}%" ) )
            .limit( limit )
            .all()
        )

    def statuses_for_ids( self, ref_ids ) -> dict:
        """
        Resolve blocker ids to statuses in one query for the whole page.

        This runs on every task_query read, so a per-row lookup would put an N+1 on the board glance. An id that does not resolve is returned as an explicit None, never omitted. `blocker_is_terminal` reads a present key with None as looked up and absent, and a missing key as never looked up. Malformed ids resolve to None too, because blocked_by is app-typed JSON and raising would fail the whole query.

        Requires:
            - ref_ids is an iterable of candidate id strings (duplicates, any order and empty are all fine)

        Ensures:
            - returns { id_str: status_str_or_None } with exactly one key per distinct input id,
              so every id asked about is answered
            - a full-UUID id that matches no row maps to None (a dead edge)
            - an 8-hex-style prefix id resolves by prefix, as `task_get` does, and maps to that
              row's status when the prefix matches exactly one row
            - an ambiguous or unmatched prefix maps to None; the caller must not read that
              as dead for a non-canonical id (see `blocker_is_terminal`)
            - never raises; an empty input returns {} and issues no query
        """
        wanted = { str( ref_id ) for ref_id in ref_ids if ref_id }
        if not wanted: return { }

        resolved = { ref_id: None for ref_id in wanted }

        parsed    = { }
        unparsed  = [ ]
        for ref_id in wanted:
            try:
                parsed[ uuid.UUID( ref_id ) ] = ref_id
            except ( ValueError, AttributeError, TypeError ):
                unparsed.append( ref_id )

        if parsed:
            rows = (
                self.session.query( TaskItem.id, TaskItem.status )
                .filter( TaskItem.id.in_( list( parsed.keys() ) ) )
                .all()
            )
            for row_id, row_status in rows:
                resolved[ parsed[ row_id ] ] = row_status

        # PREFIX EDGES ARE REAL AND ALREADY IN THE DATA (María 🌸, 2026-07-25). `91067e47`
        # stores its blocker as the 8-char `"e2f11f6f"` while the row's id is
        # `e2f11f6f-f3f8-4e73-ac94-e573f45da3ea`. Resolving only the exact string made that
        # LIVE, `queued` blocker resolve to nothing — and `blocker_is_terminal` reads
        # looked-up-and-missing as DEAD, so it condemned a row genuinely waiting on Rick.
        #
        # ⚠️ A PREFIX BLOCKER ID IS INDISTINGUISHABLE FROM A DELETED ONE by string alone.
        # The fleet's own verbs disagree about what an id is — `task_get` resolves an 8-char
        # prefix, `task_transition` 422s on one — so a seat that READS with prefixes
        # eventually WRITES one into a blocked_by, and that edge is the proof it happened.
        #
        # An AMBIGUOUS prefix stays None here and is handled at the predicate, which does not
        # flag a non-canonical id it could not resolve: "I cannot tell" must never render as
        # "it is dead".
        for ref_id in unparsed:
            matches = self.find_by_id_prefix( ref_id.replace( "-", "" ), limit=2 )
            if len( matches ) == 1:
                resolved[ ref_id ] = matches[ 0 ].status

        return resolved

    def create_item(
        self,
        item_class          : str,
        title               : str,
        project             : str,
        created_by          : str,
        authority           : str,
        body                : Optional[str] = None,
        owner_persona       : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        gate_class          : str = "none",
        priority            : str = "P5",                             # P5 default per Rick's broadcast e254ec7d, 2026-09-07: "The default Priority from here on now will be P5."
        urgency             : str = "normal",
        status              : str = "queued",
        blocked_by          : Optional[list] = None,
        next_chase_ts       : Optional[datetime] = None,
        source_qid          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
        flag_suffix         : Optional[str] = None,
        title_trimmed       : bool = False,
    ) -> TaskItem:
        """
        Create a new task item plus its "->{status}" creation event.

        Requires:
            - item_class, gate_class, priority and authority are already validated by
              task_store_rules.validate_create (router responsibility)
            - status is queued or blocked, already whitelist-validated by
              task_store_rules.validate_create_status (router responsibility); a blocked mint's
              blocked_by and next_chase_ts already satisfy the ->blocked invariant
              (>=1 typed ref and a kind-aware chase); this method never re-validates
            - title, project and created_by are non-empty strings
            - flag_suffix is an optional advisory marker (such as the persona flag "[persona_flag: ... off-roster]")
              the router folds into the creation event's reason; None means no marker

        Ensures:
            - item created with the given status (default 'queued'). Per-status field consistency is
              delegated to task_store_rules.normalize_status_fields, which apply_transition also calls,
              so the two write paths cannot drift. This method no longer owns those rules:
                * status == 'blocked' -> blocked_by is the given list (or [] when None)
                * any other status -> blocked_by is [], dropping stray refs (a non-blocked row waits on nothing)
                * next_chase_ts is the caller's value on every status, because a chase is a schedule, not a wait, and is no longer nulled outside blocked or parked
            - exactly one TaskEvent with transition='->{status}' appended, actor = created_by,
              reason = flag_suffix extended with a "[dropped: ...]" marker naming any field the
              normalizer discarded, so a discard is disclosed in the audit trail rather than swallowed on a 200
            - flush() called so item.id is populated
            - commit is not called (the caller's get_db() commits)

        Returns:
            Created TaskItem instance (with id populated)
        """
        # SINGLE SOURCE (86ce4c43 #2): this method no longer implements the
        # per-status rules itself — it and apply_transition route through ONE
        # normalizer, so the two paths cannot drift into disagreeing about what
        # a status implies. See normalize_status_fields for the full rationale.
        resolved, dropped = normalize_status_fields( status, blocked_by, next_chase_ts )
        resolved_blocked_by    = resolved[ "blocked_by" ]
        resolved_next_chase_ts = resolved[ "next_chase_ts" ]
        # A discard lands in the AUDIT TRAIL, not in a docstring. Reporting a
        # dropped value to a caller that throws the report away is the same
        # silence one layer up — this is what makes the no-silent-drop rule a
        # mechanism rather than a convention. Rides the existing event reason:
        # zero new schema, zero new events.
        creation_reason = compose_drop_marker( dropped, flag_suffix )

        item = self.create(
            item_class          = item_class,
            title               = title,
            body                = body,
            project             = project,
            owner_persona       = owner_persona,
            accountable_manager = accountable_manager,
            created_by          = created_by,
            status              = status,
            blocked_by          = resolved_blocked_by,
            next_chase_ts       = resolved_next_chase_ts,
            gate_class          = gate_class,
            priority            = priority,
            urgency             = urgency,
            source_qid          = source_qid,
            correlation_key     = correlation_key,
            # A RECORD of what soft_guard_title did on THIS write, never a
            # read-time re-derivation from length (bug 769b3574). The CREATE
            # router passes `title_guard is not None`; it defaults False so every
            # other caller and every test fixture keeps its current shape.
            # (The EDIT door writes it through apply_patch instead, and always
            # False since 2026-09-01 — an over-cap edit is a 422, bug 6ce252e7.)
            title_trimmed       = title_trimmed,
        )
        self._append_event( item.id, created_by, f"->{status}", authority, receipt_refs=None, reason=creation_reason )
        return item

    def apply_transition(
        self,
        item          : TaskItem,
        to_status     : str,
        actor         : str,
        authority     : str,
        receipt_refs  : Optional[dict] = None,
        next_chase_ts : Optional[datetime] = None,
        blocked_by    : Optional[list] = None,
        reason        : Optional[str] = None,
        park_reason   : Optional[str] = None,
    ) -> TaskEvent:
        """
        Apply an already-validated transition: update the item and append the event.

        Requires:
            - item is a TaskItem loaded in this session
            - the transition has passed task_store_rules.validate_transition
              (router responsibility); this method never re-validates

        Ensures:
            - item.status set to to_status
            - to_status == 'blocked': item.next_chase_ts and item.blocked_by set;
              park_reason and park_reason_captured_at cleared
            - to_status == 'parked': item.next_chase_ts set (the chase is the un-park, by read-time expiry)
              and item.park_reason set; blocked_by emptied (a parked item waits on nothing; it is not-now, not blocked).
              item.park_reason_captured_at and item.updated_ts are stamped with one DB-clock instant
              in a single statement, so they are always equal (see _park_capture_ts, which explains why the design's read-back sequence cannot commit)
            - any other status: item.blocked_by emptied, item.next_chase_ts is the caller's value as on every status,
              and park_reason and park_reason_captured_at cleared (an unblocked item is blocked on nothing; an unparked item carries no park
              justification, and a capture time must not outlive the quote it dates)
            - exactly one TaskEvent ("from->to") appended with receipt_refs, authority and reason
              (reason is non-None for ->dropped by rule); on ->parked that event's ts equals
              park_reason_captured_at, so the column and the audit row record one instant, not two
            - flush() called; commit is not called (the caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        transition_label = f"{item.status}->{to_status}"

        item.status = to_status
        # SINGLE SOURCE (86ce4c43 #2): blocked_by / next_chase_ts are resolved by
        # the SAME normalizer create_item uses, so the two write paths cannot
        # drift into disagreeing about what a status implies. The park-only
        # columns below stay here — they are park bookkeeping, not per-status
        # field consistency, and one of them needs the DB clock.
        _resolved, _dropped = normalize_status_fields( to_status, blocked_by, next_chase_ts )
        item.blocked_by    = _resolved[ "blocked_by" ]
        item.next_chase_ts = _resolved[ "next_chase_ts" ]
        # Same disclosure as the create path — a discarded value is NAMED in the
        # audit trail, never swallowed on a 200.
        reason = compose_drop_marker( _dropped, reason )

        if to_status == "blocked":
            item.park_reason             = None
            item.park_reason_captured_at = None
        elif to_status == PARK_STATUS:
            # PARK KEEPS ITS CHASE — now by the normalizer above, which returns
            # the caller's chase on EVERY status. The parked CHECK constraint
            # requires it (ck_task_items_parked_requires_chase_ts), and the chase
            # IS the un-park (read-time expiry, task_store_owed), so losing it
            # would destroy the one field that makes a park self-expiring.
            item.park_reason   = park_reason
            # ONE instant, written to BOTH columns in THIS statement — see
            # _park_capture_ts for why it cannot be a read-back-then-update.
            captured                     = self._park_capture_ts()
            item.updated_ts              = captured     # explicit => onupdate suppressed
            item.park_reason_captured_at = captured
        else:
            # LEAVING parked CLEARS the quote. A park_reason surviving an unpark
            # is a stale justification on a row that is no longer parked, and
            # NEITHER CHECK fires in that direction (both are guarded by
            # `status != 'parked' OR ...`, vacuously true once the status moves).
            # The capture time goes with it: a date on a deleted quote dates
            # nothing, and leaving it would make a later re-park's equality
            # invariant unreadable.
            item.park_reason             = None
            item.park_reason_captured_at = None

        if to_status == PARK_STATUS:
            event = self._append_event(
                item.id, actor, transition_label, authority, receipt_refs, reason=reason, ts=captured
            )
        else:
            event = self._append_event( item.id, actor, transition_label, authority, receipt_refs, reason=reason )

        # 🔨 A PENDING REQUEST THE MOVE HAS MADE IMPOSSIBLE IS WITHDRAWN (row c9fafb9d, design
        # §7, Mr. Radio's D2). Rick moving the row himself, a close, a drop, a park — each can
        # leave a request asking for a move the row can no longer make, and the badge would
        # keep counting a question with no subject. HERE rather than in a router, because
        # every status change in the store comes through this method, the promotion
        # resolver's included. After the transition's own event, so the trail reads cause
        # then consequence.
        self._withdraw_stale_request( item, actor, authority, transition_label )
        return event

    def _withdraw_stale_request( self, item: TaskItem, actor: str, authority: str, transition_label: str ) -> None:
        """
        Clear a pending request the row's new status has made impossible, with its own event.

        Every status change comes through apply_transition, so the withdrawal lives here and not in a router.
        It runs after the transition's own event, so the trail reads cause and then consequence.

        Requires:
            - item.status is already the new status

        Ensures:
            - when `task_request_lifecycle.request_is_stale` holds: request_state, request_move and
              request_ts go to NULL and one 'request_withdrawn' event is appended naming the move
              and the transition that stranded it
            - otherwise nothing is written: an answered request, no request, or a pending request
              the row can still make (a demote from queued -> in_progress) stays
            - a withdrawal is neither a denial nor an approval, so it writes neither state
        """
        if not request_lifecycle.request_is_stale( item.request_state, item.request_move, item.status ): return
        move               = item.request_move
        item.request_state = None
        item.request_move  = None
        item.request_ts    = None
        self._append_event(
            item.id, actor, "request_withdrawn", authority, receipt_refs=None,
            reason = f"a pending {move!r} request no longer fits: the row moved {transition_label}. "
                     f"Not a denial — the question lost its subject.",
        )

    def _db_clock_now( self ) -> datetime:
        """
        Read the database clock: the one clock every compared timestamp must come from.

        Every timestamp that gets compared to another must come from this one clock.
        `task_store_owed.park_reason_is_stale` compares park_reason_captured_at with body_changed_ts, and both come from here.
        Taking either from datetime.now() makes the comparison cross-clock, and skew then shows up as a false fresh result.

        Requires:
            - an open session/transaction (the caller's; this reads, never writes)

        Ensures:
            - returns a tz-aware UTC datetime from the DB clock
            - a naive return is converted to tz-aware UTC, so the value compares
              correctly against the tz-aware column on every backend
            - commit is not called; nothing is written here

        Returns:
            The database clock's current instant
        """
        captured = self.session.execute( select( func.now() ) ).scalar_one()

        # MEASURED, both backends, 2026-07-19 — not assumed:
        #   PostgreSQL -> datetime(..., tzinfo=UTC)   (tz-aware)
        #   SQLite     -> datetime(...)               (NAIVE, and a datetime —
        #                                              NOT the string it is easy
        #                                              to assume it returns)
        # So exactly one normalization is needed and it is load-bearing on
        # SQLite: a naive value compared against the tz-aware column raises
        # TypeError. An earlier draft also carried an `isinstance( captured, str )`
        # branch written on the ASSUMPTION that SQLite returns a string. It does
        # not, so that branch was unreachable — a hedge marking where its author
        # had declined to find out, and an uncoverable line under the 100% gate.
        # Verified, then deleted.
        if captured.tzinfo is None:
            captured = captured.replace( tzinfo=timezone.utc )

        return captured

    def _park_capture_ts( self ) -> datetime:
        """
        Read the database clock for the park write's single timestamp.

        That one instant goes into updated_ts, park_reason_captured_at and the park event's ts, in one statement. A flush-then-read-back cannot commit: the first flush writes status='parked' with park_reason_captured_at still NULL. The per-statement `CHECK` named ck_task_items_parked_requires_captured_at rejects that. PostgreSQL cannot defer a `CHECK`. The updated_ts column is assigned explicitly. That suppresses its onupdate, so a parked row is not born stale. Every other updated_ts in this table is written by onupdate=func.now(), the database's clock. The staleness comparison must therefore not cross clocks. A false fresh result would be a parked row quietly failing to report an expired quote. On PostgreSQL now() is transaction_timestamp(), stable across the transaction. The explicit assignment returns the same value onupdate would have written.

        Requires:
            - an open session/transaction (the caller's; this reads, never writes)

        Ensures:
            - returns a tz-aware UTC datetime from the DB clock
            - a naive return is converted to tz-aware UTC, so the value compares
              correctly against the tz-aware column on every backend
            - commit is not called; nothing is written here

        Returns:
            The single timestamp for this park write
        """
        # ONE clock for every compared timestamp — see _db_clock_now. This wrapper
        # exists for its NAME and its §3.4 reasoning above, not for a second
        # implementation: `body_changed_ts` is compared against what this returns,
        # so the two must not be able to drift to different clocks.
        return self._db_clock_now()

    def apply_correlation(
        self,
        item            : TaskItem,
        correlation_key : str,
        actor           : str,
        authority       : str,
    ) -> TaskEvent:
        """
        Re-stamp an item's correlation_key and append the audit event.

        This is the adoption seam for a respawned session. A successor re-registers its harness task id
        onto the inherited item instead of forking a duplicate.

        Requires:
            - item is a TaskItem loaded in this session (row-locked by the router) and not terminal (router-validated)
            - correlation_key, actor and authority are already validated (router)

        Ensures:
            - item.correlation_key set to correlation_key (status untouched)
            - exactly one TaskEvent appended: transition='re-correlated', receipt_refs=None,
              reason='correlation_key: <old> -> <new>', so the adoption is auditable
            - flush() called; commit is not called (the caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        old_key              = item.correlation_key
        item.correlation_key = correlation_key
        return self._append_event(
            item.id, actor, "re-correlated", authority, receipt_refs=None,
            reason = f"correlation_key: {old_key} -> {correlation_key}",
        )

    def apply_patch(
        self,
        item        : TaskItem,
        fields      : dict,
        actor       : str,
        authority   : str,
        reason      = None,
        flag_suffix = None,
    ) -> TaskEvent:
        """
        Apply an already-validated item-field edit and append a 'patched' event.

        Touches only the editable presentation and ownership fields the caller set.
        status, blocked_by, next_chase_ts, receipt_refs and correlation_key are never written here.
        They go through apply_transition and apply_correlation, so the transition rules are never bypassed.

        Requires:
            - item is a TaskItem loaded in this session (row-locked by the router) and not terminal (router-validated)
            - fields keys are whitelist-validated editable field names (router validated via
              task_store_rules.validate_patch); values are already wire-checked by the TaskPatchIn model
            - reason is an optional caller-supplied justification; None or "" means no justification given.
              It is appended to the field delta, never substituted for it
            - flag_suffix is an optional advisory marker (the persona flag "[persona_flag: ... off-roster]")
              appended to the resolved event reason; None means no marker

        Ensures:
            - each provided field whose value differs is written onto the item
            - body_changed_ts is stamped from the DB clock only when body is in fields and its value
              differs. The other free-edit fields cannot make a park quote untrue, and a same-text body write
              changes nothing, so neither may move the marker
            - exactly one TaskEvent appended: transition='patched', receipt_refs=None, reason always
              opens with the field delta ("k: old -> new; ...") or the no-op marker when nothing changed.
              A non-empty caller reason is appended after " | reason: " rather than replacing the delta,
              so an overwritten body stays recoverable. flag_suffix is appended last when present, so all three parts survive on the one event
            - flush() called; commit is not called (the caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        changes      = [ ]
        body_changed = False
        for key, new_value in fields.items():
            old_value = getattr( item, key )                 # key is whitelist-validated, never arbitrary — fails loud if absent
            if old_value != new_value:
                setattr( item, key, new_value )
                changes.append( f"{key}: {old_value!r} -> {new_value!r}" )
                if key == "body": body_changed = True

        # THE FIX FOR 54924128, in one condition: the content-change marker moves
        # for a body edit and for nothing else. Keyed off the SAME equality the
        # audit delta uses, so the marker and the event can never disagree about
        # whether the body changed.
        if body_changed: item.body_changed_ts = self._db_clock_now()

        # The field delta ALWAYS leads (bug a01e4e2a) — a caller "why" is additive,
        # never a substitute, so an overwrite can no longer erase what it overwrote.
        event_reason = "; ".join( changes ) if changes else "no-op patch (no field changed)"
        if reason: event_reason = f"{event_reason} | reason: {reason}"
        # Fold the persona-flag marker into the resolved reason (policy 1) —
        # AFTER the field-delta is composed, so both survive on the one event.
        if flag_suffix:
            event_reason = f"{event_reason} {flag_suffix}"
        return self._append_event( item.id, actor, "patched", authority, receipt_refs=None, reason=event_reason )

    def apply_request_filing(
        self,
        item      : TaskItem,
        move        : str,
        actor       : str,
        authority   : str,
        reason      : str,
        deletion_id : Optional[uuid.UUID] = None,
        pledged_by  : Optional[str]       = None,
    ) -> TaskEvent:
        """
        File a manager's promote or demote request on a row and append its event.

        The row's status is never touched here: a request asks, it does not move.
        There is one request per row. A re-file over an answered request overwrites the three columns,
        and the verdict it replaces survives as its own event in the audit trail.

        Requires:
            - item is a TaskItem loaded in this session, row-locked by the router
            - move has already passed `task_request_lifecycle.refusal_for_filing` and
              `refusal_for_refiling` against the row's real state; this method decides nothing
            - actor is the router's `recorded_actor(...)` result; reason is non-blank
            - deletion_id, when given, has already passed `task_request_pledge.refusal_for_pledge`
              under a lock on the pledged row
            - pledged_by is the persona that rule resolved for the requester when deletion_id
              is given, else None

        Ensures:
            - request_state := 'pending', request_move := move, request_ts := the DB clock
            - request_deletion_id := deletion_id, including None, so a re-file replaces the
              old pledge rather than inheriting it and a demote never carries one
            - request_pledged_by := pledged_by, replaced the same way
            - item.status untouched
            - exactly one TaskEvent appended: transition='request_filed', receipt_refs=None,
              reason naming the move, the prior request state, the pledged row when there is one,
              and the caller's reason
            - flush() called; commit is not called (the caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        before                   = item.request_state
        item.request_state       = "pending"
        item.request_move        = move
        item.request_ts          = self._db_clock_now()
        item.request_deletion_id = deletion_id
        item.request_pledged_by  = pledged_by
        pledge                   = f" | pledged for deletion: {deletion_id}" if deletion_id is not None else ""
        event_reason             = f"move: {move!r} (prior request: {before!r}){pledge} | reason: {reason}"
        return self._append_event( item.id, actor, "request_filed", authority, receipt_refs=None, reason=event_reason )

    def find_pending_admit_pledging( self, pledge_id: uuid.UUID, excluding_id: uuid.UUID ) -> Optional[uuid.UUID]:
        """
        Find the row whose pending admit request already pledges `pledge_id` for deletion, if any.

        One pledge pays for one admit.
        The filing door calls this while it holds the lock on the pledged row.
        Two requests racing to pledge the same row therefore serialize on that lock, and the second sees the first.

        Requires:
            - pledge_id and excluding_id are UUIDs; excluding_id is the row being filed on,
              so a re-file over its own stranded request does not count against itself

        Ensures:
            - returns the id of one other row with request_state 'pending', request_move
              'admit' and request_deletion_id == pledge_id, or None
            - an answered request does not count, because its pledge was consumed or released
        """
        row = (
            self.session.query( TaskItem.id )
            .filter( TaskItem.request_deletion_id == pledge_id )
            .filter( TaskItem.request_state == "pending" )
            .filter( TaskItem.request_move == "admit" )
            .filter( TaskItem.id != excluding_id )
            .first()
        )
        return row[ 0 ] if row is not None else None

    def pledge_facts_for_id( self, id: uuid.UUID ) -> tuple:
        """
        Read one pledged row's ( status, owner_persona ) without locking it.

        The filing door uses this for its stranding check: a pending admit whose pledge died or changed hands may be re-filed.
        That permission only re-files the manager's own request. The verdict re-reads both facts under its lock before anything is dropped.

        Ensures:
            - returns ( status, owner_persona ) of the row, or ( None, None ) when it does not exist
        """
        row = self.session.query( TaskItem.status, TaskItem.owner_persona ).filter( TaskItem.id == id ).first()
        return ( row[ 0 ], row[ 1 ] ) if row is not None else ( None, None )

    def peek_request_deletion_id( self, id: uuid.UUID ) -> Optional[uuid.UUID]:
        """
        Read a row's pledged deletion id without locking it.

        The verdict door uses it to learn which second row to lock before it locks the first.
        It then takes both locks in id order, the same order the filing door uses, so the two doors cannot deadlock on a crossed pair.
        The caller re-reads the value under the lock and refuses if it moved.

        Ensures:
            - returns the stored request_deletion_id, or None when the row has none or does
              not exist
        """
        row = self.session.query( TaskItem.request_deletion_id ).filter( TaskItem.id == id ).first()
        return row[ 0 ] if row is not None else None

    def apply_request_verdict(
        self,
        item      : TaskItem,
        verdict   : str,
        actor     : str,
        authority : str,
    ) -> TaskEvent:
        """
        Write the operator's verdict onto a pending promote/demote request and append its event.

        The verdict door used to set request_state inline and append nothing, so an answer left no record of who gave it.
        Routing the write through here records the actor and makes the door visible to the identity census.

        Requires:
            - item is a TaskItem loaded in this session, row-locked by the router
            - verdict has already passed `task_request_lifecycle.refusal_for_verdict`
              against the row's real state; this method decides nothing
            - actor is the router's `recorded_actor(...)` result, never a typed string

        Ensures:
            - item.request_state := verdict; request_move, request_ts and the ticket's
              status are untouched (a denial finishes the request, not the row)
            - exactly one TaskEvent appended: transition='request_<verdict>',
              receipt_refs=None, reason naming the before and after state and the move
            - flush() called; commit is not called (the caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        before             = item.request_state
        item.request_state = verdict
        reason             = f"request_state: {before!r} -> {verdict!r} (move: {item.request_move!r})"
        return self._append_event( item.id, actor, f"request_{verdict}", authority, receipt_refs=None, reason=reason )

    def apply_amendment(
        self,
        item      : TaskItem,
        note      : str,
        actor     : str,
        authority : str,
        now       : datetime,
        reason    = None,
    ) -> TaskEvent:
        """
        Append a stamped amendment block to a live item's body and append an 'amended' event.

        Unlike apply_patch, which overwrites the body, this never rewrites existing text. The original body is kept verbatim and the note goes below a divider naming the actor and the UTC time. A successor reading the store therefore sees the full amendment history inline. On a terminal row the divider and event read post-terminal addendum, and the status stays unchanged. Post-terminal amend exists because a gate verdict written after a worker self-closes its row has nowhere durable to go otherwise.

        Requires:
            - item is a TaskItem loaded in this session (row-locked by the router).
              It may be terminal, because amend is the one write verb the store allows on a terminal row.
              The status selects the divider and event
            - note is the caller's amendment text (wire-checked for length, 1..4000; the router rejects a whitespace-only note)
            - now is a timezone-aware datetime (the router owns the clock so this method stays deterministic)
            - reason is an optional justification stamping the audit event; None or "" means auto-describe the amendment

        Ensures:
            - item.body := the original body (verbatim), a blank line and the stamped block when the body was non-empty;
              the stamped block alone, with no leading blank lines, when the body was empty or None
            - item.body_changed_ts is stamped from the DB clock unconditionally, because an amend only appends, so the body always changed and the marker must still go true on a real body change.
              It uses the DB clock, never datetime.now(), since it is compared against park_reason_captured_at (see _db_clock_now)
            - the divider is "[amendment . actor . utc]" on a non-terminal row, and
              "[post-terminal addendum . actor . utc . row was '<status>' at write - added after close, not a reopening]" on a done or dropped row
            - item.status is never touched (an amend is not a transition); a terminal row stays terminal and nothing here reads as a reopening
            - exactly one TaskEvent appended: transition='amended' on a live row, 'amended_post_terminal'
              on a terminal row, receipt_refs=None, reason = the caller's reason when non-empty,
              else an auto-marker naming the appended length
            - flush() called; commit is not called (the caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        # POST-TERMINAL ADDENDUM (Rick's ruling 2026-08-02, row 3c569786). A gate
        # verdict is written AFTER the worker self-closed the row: amend is the ONE
        # write verb the store now allows on a terminal row (transition / edit /
        # correlate stay refused — a closed row stays closed). The block is stamped
        # DISTINCTLY so a reader sees at a glance that this text arrived after the
        # close and never mistakes it for the original body OR for a reopening, and
        # the audit event carries a DISTINCT transition ('amended_post_terminal')
        # so the history can be queried for late verdicts later. Status is NEVER
        # touched here — that is true for a live amend and stays true post-terminal.
        post_terminal = item.status in TERMINAL_STATUSES
        if post_terminal:
            block            = f"[post-terminal addendum · {actor} · {now.isoformat()} · row was '{item.status}' at write — added after close, not a reopening]\n{note}"
            transition_label = "amended_post_terminal"
        else:
            block            = f"[amendment · {actor} · {now.isoformat()}]\n{note}"
            transition_label = "amended"
        if item.body:
            item.body = f"{item.body}\n\n{block}"
        else:
            item.body = block

        # The body ALWAYS changed here (append-only, and the router rejects a blank
        # note). Stamped from the DB clock, NOT the injected `now` — `now` is the
        # ROUTER's application clock, deliberately injected to keep this method
        # deterministic for the event stamp, and it is the wrong clock for a value
        # that gets COMPARED to park_reason_captured_at.
        item.body_changed_ts = self._db_clock_now()

        # Caller-supplied reason wins (the "why" for the amendment); otherwise
        # auto-describe the appended length so the event is never blank.
        event_reason = reason if reason else f"body amended (+{len( note )} chars)"
        return self._append_event( item.id, actor, transition_label, authority, receipt_refs=None, reason=event_reason )

    def query_chase_due( self, now: datetime, limit: int = 100 ) -> List[TaskItem]:
        """
        Return blocked items whose next_chase_ts is at or before `now`.

        This is the chase consumer's due list, so a blocked row never waits in silence.

        Requires:
            - now is a timezone-aware datetime (the chase cutoff)
            - limit is a non-negative int

        Ensures:
            - returns items with status='blocked' and next_chase_ts `IS NOT NULL` and next_chase_ts <= now
            - ordered by next_chase_ts ascending (longest-overdue first)
            - read-only: never mutates (the consumer re-arms via apply_chase)

        Returns:
            List of TaskItem instances (may be empty)
        """
        return (
            self.session.query( TaskItem )
            .filter(
                TaskItem.status == "blocked",
                TaskItem.next_chase_ts.isnot( None ),
                TaskItem.next_chase_ts <= now,
            )
            .order_by( TaskItem.next_chase_ts )
            .limit( limit )
            .all()
        )

    def apply_chase( self, item: TaskItem, actor: str, authority: str, next_chase_ts: datetime ) -> TaskEvent:
        """
        Record a chase on a blocked item: re-arm next_chase_ts and append a 'chased' event.

        Chasing is a nudge, not a decision, so this never changes the status.

        Requires:
            - item is a blocked TaskItem loaded in this session
            - next_chase_ts is the re-armed (future) chase time

        Ensures:
            - item.next_chase_ts set to next_chase_ts; item.status untouched
            - exactly one TaskEvent appended: transition='chased', receipt_refs=None,
              reason names the re-armed time, so the chase is auditable
            - flush() called; commit is not called (the caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        item.next_chase_ts = next_chase_ts
        return self._append_event(
            item.id, actor, "chased", authority, receipt_refs=None,
            reason = f"chase re-armed -> {next_chase_ts.isoformat()}",
        )

    def query_tasks(
        self,
        owner_persona       : Optional[str] = None,
        status              : Optional[str] = None,
        gate_class          : Optional[str] = None,
        urgency             : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        project             : Optional[str] = None,
        item_class          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
        id_prefix           : Optional[str] = None,
        limit               : int = 100,
        offset              : int = 0,
        include_terminal    : bool = False,
        unscoped_audit      : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
        updated_since       : Optional[datetime] = None,
        updated_until       : Optional[datetime] = None,
    ) -> List[TaskItem]:
        """
        The deterministic owed-work query, identical for every caller.

        The unscoped-query guard lives here at the repository layer, so no repo-direct caller can bypass it.
        That covers the arbiter and the in-process watchers, not just the REST and MCP surface.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - limit and offset are non-negative ints

        Ensures:
            - excludes terminal (done/dropped) rows by default (include_terminal=False) unless an explicit terminal `status` filter is set (an 89->2 payload collapse is why the default exists). Pass include_terminal=True to include
              terminal rows on a query with no status
            - hard-fails with UnscopedQueryError when the query is unscoped (no narrowing filter,
              see task_store_rules.is_unscoped) and would return more than UNSCOPED_QUERY_THRESHOLD
              non-terminal rows and unscoped_audit is False. The count is a cheap `COUNT(*)`
              (count_tasks), never a row materialization. A scoped query skips the guard
            - owed_only=True selects the owed set: queued, in_progress, and parked rows that are not park-active.
              With no status filter it replaces the status selection rather than narrowing it; with an explicit status
              it narrows within that status (see _apply_owed_filter)
            - returns items matching all provided filters (every filter must match)
            - ordered by created_ts descending (newest first), then id for a stable total order
            - paginated via limit and offset

        Raises:
            - UnscopedQueryError when the query is unscoped, over the threshold and not an audit
              (the router maps it to HTTP 400; the MCP verb to an error dict)

        Returns:
            List of TaskItem instances (may be empty)
        """
        filters = {
            "owner_persona"       : owner_persona,
            "status"              : status,
            "gate_class"          : gate_class,
            "urgency"             : urgency,
            "accountable_manager" : accountable_manager,
            "project"             : project,
            "item_class"          : item_class,
            "correlation_key"     : correlation_key,
            "id_prefix"           : id_prefix,
        }

        # The guard: a bare unscoped pull over-threshold, with no deliberate-audit
        # opt-in, is rejected BEFORE any row is fetched. Count is always NON-terminal
        # (the default payload shape) via the cheap COUNT(*) — no rows materialized.
        if not unscoped_audit and is_unscoped( filters ):
            # owed_only/now are threaded into the guard's count so it measures the
            # payload this query will ACTUALLY return (PARKED-STATUS 2026-07-19).
            # Without them the guard counts every non-terminal row and could reject
            # an owed_only query whose real result is well under threshold —
            # rejecting a small answer because a big one was hypothetically possible.
            # Window threaded in for the SAME reason owed_only/now are, one comment
            # up: the guard must measure the payload this query will ACTUALLY
            # return. Counting every row outside a 24h window and then refusing
            # would reject a small answer because a big one was hypothetically
            # possible. Deliberately NOT added to `filters` — that dict feeds
            # `is_unscoped`, and whether a date window counts as a NARROWING filter
            # is a separate ruling nobody has made. A windowed-but-otherwise-bare
            # query still meets the guard, exactly as it did before.
            non_terminal = self.count_tasks(
                include_terminal=False, owed_only=owed_only, hide_parked=hide_parked, now=now,
                updated_since=updated_since, updated_until=updated_until, **filters
            )
            if non_terminal > UNSCOPED_QUERY_THRESHOLD:
                raise UnscopedQueryError( non_terminal, UNSCOPED_QUERY_THRESHOLD )

        query = self.session.query( TaskItem )

        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix,
            updated_since=updated_since, updated_until=updated_until
        )
        query = self._apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now )

        return query.order_by( TaskItem.created_ts.desc(), TaskItem.id ).limit( limit ).offset( offset ).all()

    @staticmethod
    def _apply_scalar_filters( query, owner_persona, status, gate_class, urgency,
                               accountable_manager, project, item_class, correlation_key,
                               id_prefix, updated_since=None, updated_until=None ):
        """
        Apply the exact-match filters in one place, shared by every count and page query.

        One helper means the page, the count and the breakdown cannot disagree about which rows a filter admits.
        Separate copies would let one forgotten edit narrow the page but not the count.
        Then has_more would describe a different population than the rows.

        Requires:
            - query is a TaskItem query; every filter is None or an exact value
            - id_prefix, when present, is compact lowercase hex (hyphens stripped) exactly as
              `classify_task_ref` returns it; this method does not re-validate caller text,
              because a `LIKE` built from arbitrary input turns an id lookup into a search surface

        Ensures:
            - returns the query with one filter per non-None argument, all combined with and
            - id_prefix matches on the id's canonical hyphenated rendering via the shared
              `hyphenate_compact_prefix` rule, so a prefix spanning a hyphen still matches
            - updated_since and updated_until bound updated_ts inclusively; they filter on
              updated_ts and not created_ts, so a row closed inside the window is included
            - never raises
        """
        if owner_persona is not None:       query = query.filter( TaskItem.owner_persona == owner_persona )
        if status is not None:              query = query.filter( TaskItem.status == status )
        if gate_class is not None:          query = query.filter( TaskItem.gate_class == gate_class )
        if urgency is not None:             query = query.filter( TaskItem.urgency == urgency )
        if accountable_manager is not None: query = query.filter( TaskItem.accountable_manager == accountable_manager )
        if project is not None:             query = query.filter( TaskItem.project == project )
        if item_class is not None:          query = query.filter( TaskItem.item_class == item_class )
        if correlation_key is not None:     query = query.filter( TaskItem.correlation_key == correlation_key )
        if id_prefix is not None:
            hyphened = hyphenate_compact_prefix( id_prefix )
            query    = query.filter( cast( TaskItem.id, String ).like( f"{hyphened}%" ) )
        # Activity window (row 0107c19e / Rick's Finished-Tasks P0, 2026-09-07).
        #
        # KEYED ON `updated_ts`, NOT `created_ts`, AND THE CHOICE IS THE WHOLE
        # POINT: a row minted three weeks ago and closed this afternoon belongs
        # in "the last 24 hours". Keying on creation would show the rows that
        # were BORN in the window — a different question, and not the one a
        # finished-work view asks. `created_ts` remains the ORDER (see
        # query_tasks); this is the FILTER. Two different columns doing two
        # different jobs is deliberate.
        #
        # Bounds are INCLUSIVE on both ends, matching the events stream's
        # since/until at `query_event_stream` rather than inventing a second
        # convention on the same page.
        #
        # Landing here rather than at the five call sites is this helper's own
        # stated reason for existing: the page seam, the COUNT(*) seam and the
        # breakdown seam cannot disagree about the window if there is only one
        # window. A caller that passes neither argument is byte-identical to
        # its behaviour before this block existed.
        if updated_since is not None:       query = query.filter( TaskItem.updated_ts >= updated_since )
        if updated_until is not None:       query = query.filter( TaskItem.updated_ts <= updated_until )
        return query

    @staticmethod
    def _apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now ):
        """
        Decide status, terminal and park selection in one place, for page and count alike.

        One helper means the count and the page cannot disagree about what owed means.
        The hide_parked flag only suppresses park-active rows from a selection that already holds every non-terminal row.
        The owed_only flag also admits expired-parked rows, because suppression alone cannot restore a row that parking moved out of queued.

        Requires:
            - query is a SQLAlchemy Query over TaskItem
            - owed_only and hide_parked are bools; status is a status string or None
            - now is a tz-aware datetime, or None to resolve it here (the IO boundary owns the clock,
              so the predicates never read one and tests can inject it without patching module state)

        Ensures:
            - owed_only=True selects queued, in_progress, and parked rows that are not park-active.
              This is an exact restoration, never a widening, because park is legal only from the owed base statuses, so every expired-parked row provably came from that set.
              An explicit `status` filter is applied upstream and honored; owed_only then narrows within it
            - hide_parked=True suppresses park-active rows without touching the status set.
              Expired-parked rows stay visible, since they have rejoined owed work
            - an explicit status="parked" filter disables hide_parked suppression: you asked for parked, you get all of them, so the audit surface returns every parked row.
              owed_only still suppresses park-active rows even then
            - owed_only takes precedence over hide_parked (the stricter, fail-closed policy);
              with both flags False the terminal-exclusion default applies exactly
            - never mutates the caller's query in place
        """
        # HOISTED out of the owed/park branch (2026-09-02). It used to be defaulted
        # only inside that branch, which was correct while `now` was read there and
        # nowhere else. The holding-area chase made the terminal-exclusion default
        # read it too, on a path the branch never covers — so a plain un-statused
        # query arrived with now=None and raised. Defaulting once, up front, is what
        # makes "read time" mean the same thing on every path through this function.
        if now is None:
            now = datetime.now( timezone.utc )

        if owed_only or ( hide_parked and status != PARK_STATUS ):
            if owed_only and status is None:
                # owed_status_clause is the CANONICAL one-call admission:
                # queued U in_progress U (parked AND NOT park-active). Composing
                # it here from parts would re-derive the rule in a reader, which
                # is precisely what this build removes.
                return query.filter( owed_status_clause( TaskItem, now ) )
            # hide_parked (or owed_only narrowed by an explicit status): SUPPRESS
            # park-active rows without touching the status set. owed_clause alone
            # on a queued/in_progress filter would NOT re-admit expired-parked
            # rows — correct here precisely because these callers already select
            # the parked status themselves (all-non-terminal / explicit filter).
            if not include_terminal and status is None:
                query = query.filter( or_(
                TaskItem.status.notin_( BOARD_INVISIBLE_STATUSES ),
                # 🔨 Rick 2026-09-02: the holding area is SELF-EXPIRING. A
                # `not_approved` row hides only while its triage chase is still
                # in the future; once it comes due the row stops hiding itself,
                # which is the whole point of the chase. Terminal rows have no
                # chase and are unaffected — this widens the visible set for one
                # status only.
                and_( TaskItem.status == NOT_APPROVED_STATUS,
                      # 🔴 `isnot( None )` ADDED 2026-09-03 (P0 46799ba3, Rick). Without
                      # it a held row carrying NO chase at all was re-admitted here, and
                      # NOTHING sets a chase when a row is minted into holding — so every
                      # held row was born chase-less and came straight back onto the
                      # board. The gate was inert by construction, not for one row.
                      #
                      # Rick's self-expiry ruling is UNCHANGED and is what the next line
                      # still implements: a held row hides until its triage chase comes
                      # due. This conjunct only says that COMING DUE REQUIRES A DUE DATE.
                      # A row with no chase has no expiry to reach, so it keeps holding.
                      TaskItem.next_chase_ts.isnot( None ),
                      ~holding_is_active_clause( TaskItem, now ) ),
            ) )
            return query.filter( owed_clause( TaskItem, now ) )
        # Terminal-exclusion default: an un-status'd query drops done/dropped unless
        # the caller opts in via include_terminal. An explicit `status` filter (incl.
        # status=done/dropped) governs on its own — no double-filtering.
        if not include_terminal and status is None:
            query = query.filter( or_(
                TaskItem.status.notin_( BOARD_INVISIBLE_STATUSES ),
                # 🔨 Rick 2026-09-02: the holding area is SELF-EXPIRING. A
                # `not_approved` row hides only while its triage chase is still
                # in the future; once it comes due the row stops hiding itself,
                # which is the whole point of the chase. Terminal rows have no
                # chase and are unaffected — this widens the visible set for one
                # status only.
                and_( TaskItem.status == NOT_APPROVED_STATUS,
                      # 🔴 `isnot( None )` ADDED 2026-09-03 (P0 46799ba3, Rick). Without
                      # it a held row carrying NO chase at all was re-admitted here, and
                      # NOTHING sets a chase when a row is minted into holding — so every
                      # held row was born chase-less and came straight back onto the
                      # board. The gate was inert by construction, not for one row.
                      #
                      # Rick's self-expiry ruling is UNCHANGED and is what the next line
                      # still implements: a held row hides until its triage chase comes
                      # due. This conjunct only says that COMING DUE REQUIRES A DUE DATE.
                      # A row with no chase has no expiry to reach, so it keeps holding.
                      TaskItem.next_chase_ts.isnot( None ),
                      ~holding_is_active_clause( TaskItem, now ) ),
            ) )
        return query

    def count_tasks_by_status(
        self,
        owner_persona       : Optional[str] = None,
        status              : Optional[str] = None,
        gate_class          : Optional[str] = None,
        urgency             : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        project             : Optional[str] = None,
        item_class          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
        id_prefix           : Optional[str] = None,
        updated_since       : Optional[datetime] = None,
        updated_until       : Optional[datetime] = None,
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> dict:
        """
        Count the admitted set per status in one `GROUP BY`, over count_tasks's set.

        The Stop-hook count seam once collapsed a multi-status owed set into one integer, so every queued row looked in progress. The status has to survive the seam, and the safe place to recover it is here, server-side. A per-status client loop cannot see a park-expiry rejoin and double-counts expired-parked rows. Grouping puts each row in exactly one bucket. Park-active rows are already excluded by owed_status_clause, so every parked row that survives admission has provably rejoined and needs no extra filtering. The `parked` bucket holds expired-parked rows, and keys are raw stored statuses.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - the filter set is applied identically to count_tasks (same helper)

        Ensures:
            - returns { status: count } over only the statuses actually present;
              absent statuses are omitted, never zero-filled, since a zero key claims a status the query never saw
            - sum( result.values() ) == count_tasks( <same filters> ). The two are computed independently and not derived from each other,
              because a check derived from the other side could never fail
            - {} when nothing matches
            - no `ORDER BY`, `LIMIT` or `OFFSET`; a breakdown is order- and page-independent
        """
        query = self.session.query( TaskItem.status, func.count( TaskItem.id ) )

        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix,
            updated_since=updated_since, updated_until=updated_until
        )
        # The SAME helper count_tasks and query_tasks use — the breakdown MUST select
        # the identical admitted set, or the sum-parity gate is comparing two
        # different populations and its green means nothing.
        query = self._apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now )

        return { row_status : row_count for row_status, row_count in query.group_by( TaskItem.status ).all() }

    def count_tasks_by_priority(
        self,
        owner_persona       : Optional[str] = None,
        status              : Optional[str] = None,
        gate_class          : Optional[str] = None,
        urgency             : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        project             : Optional[str] = None,
        item_class          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
        id_prefix           : Optional[str] = None,
        updated_since       : Optional[datetime] = None,
        updated_until       : Optional[datetime] = None,
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> dict:
        """
        Count the admitted set per priority in one `GROUP BY`, over count_tasks's set.

        The Stop-hook poke reported how many rows a seat owed and never which ones mattered.
        Work goes in descending priority, so the poke needs the priority mix.
        This mirrors count_tasks_by_status, including the sum parity with count_tasks.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - the filter set is applied identically to count_tasks (same helpers)

        Ensures:
            - returns { priority: count } over only the priorities actually present;
              an absent priority is absent, never a 0 bucket, so "no P0 rows" cannot be mistaken for "P0 was not measured"
            - keys are the raw stored priority strings; VALID_PRIORITIES is the authority on which exist
        """
        query = self.session.query( TaskItem.priority, func.count( TaskItem.id ) )
        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix,
            updated_since=updated_since, updated_until=updated_until
        )
        query = self._apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now )

        return { row_priority : row_count for row_priority, row_count in query.group_by( TaskItem.priority ).all() }

    def count_tasks_by_project(
        self,
        owner_persona       : Optional[str] = None,
        status              : Optional[str] = None,
        gate_class          : Optional[str] = None,
        urgency             : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        item_class          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
        id_prefix           : Optional[str] = None,
        updated_since       : Optional[datetime] = None,
        updated_until       : Optional[datetime] = None,
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> dict:
        """
        Count the admitted set per project, with no project filter in the signature.

        `project` is free text, so a typo mints a project silently and permanently. A caller querying one project name gets a clean, smaller number while rows sit under a variant spelling. So project is not a parameter here: the buckets must show the values the caller's own `project=` did not match. Every other filter goes through the same helpers as count_tasks and query_tasks, so the buckets stay comparable. The buckets answer "under my other constraints, what projects exist". They do not answer what exists in the whole store, which would report projects the owner and status filters had already ruled out.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - the filter set is applied identically to count_tasks, minus project

        Ensures:
            - returns { project: count } over only the projects actually present in the admitted set;
              an absent project is absent, never a 0 bucket
            - the key is the raw stored string, not alias-canonicalized, because a canonical form would hide the orphan spelling
            - sum( result.values() ) == count_tasks( <same filters, project=None> )
            - a row whose project is NULL lands under the None key rather than being dropped, since a row with no project is the case a census must see
        """
        query = self.session.query( TaskItem.project, func.count( TaskItem.id ) )
        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, None, item_class, correlation_key, id_prefix,
            updated_since=updated_since, updated_until=updated_until
        )
        query = self._apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now )

        return { row_project : row_count for row_project, row_count in query.group_by( TaskItem.project ).all() }

    def count_tasks(
        self,
        owner_persona       : Optional[str] = None,
        status              : Optional[str] = None,
        gate_class          : Optional[str] = None,
        urgency             : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        project             : Optional[str] = None,
        item_class          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
        id_prefix           : Optional[str] = None,
        updated_since       : Optional[datetime] = None,
        updated_until       : Optional[datetime] = None,
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> int:
        """
        Count rows over the same filter set as query_tasks, with `COUNT(*)` and no row loading.

        The owed-count callers, such as the Stop-hook store-count seam, need a cardinality, not the rows.
        A page length saturates at the page size, so a seat with more than 100 owed rows would read exactly 100.
        This computes the true total, independent of any page bound (query_tasks and the endpoint cap limit at 500).

        Requires:
            - each filter is either None (no constraint) or an exact-match value

        Ensures:
            - excludes terminal (done/dropped) rows by default (include_terminal=False) unless an
              explicit terminal `status` filter is set, in parity with query_tasks so the guard's count matches the payload it guards.
              The Stop-hook seam always passes a non-terminal status, so the default is neutral for it
            - owed_only=True applies the identical selection as query_tasks through the shared _apply_owed_filter,
              so the count can never disagree with the page it counts
            - returns the integer count of items matching all provided filters
            - no `ORDER BY`, `LIMIT` or `OFFSET`; a count is order- and page-independent
        """
        query = self.session.query( func.count( TaskItem.id ) )

        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix,
            updated_since=updated_since, updated_until=updated_until
        )
        # The SAME helper query_tasks uses — this is the COUNT(*)/page parity seam
        # the Stop-hook oracle reads. Rachel's gate asserts
        # count_tasks(owed_only=True) == len(query_tasks(owed_only=True)).
        query = self._apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now )

        return query.scalar()

    def get_events( self, item_id: uuid.UUID ) -> List[TaskEvent]:
        """
        Return the append-only audit trail for one item.

        Requires:
            - item_id is a TaskItem UUID (existence is checked by the caller; a missing item simply has no events)

        Ensures:
            - returns events ordered by id ascending (insertion == audit order)

        Returns:
            List of TaskEvent instances (may be empty)
        """
        # joinedload for the SAME reason as query_events: `_serialize_event` reads
        # `event.item.title`. Here every event shares one item, so the cost avoided is one
        # query rather than N — but the serializer's requirement must hold at EVERY call site,
        # not only the one where the saving is large.
        return (
            self.session.query( TaskEvent )
            .options( joinedload( TaskEvent.item ) )
            .filter( TaskEvent.item_id == item_id )
            .order_by( TaskEvent.id )
            .all()
        )

    def query_events(
        self,
        actor      : Optional[str] = None,
        transition : Optional[str] = None,
        to_status  : Optional[str] = None,
        project    : Optional[str] = None,
        since      : Optional[datetime] = None,
        until      : Optional[datetime] = None,
        limit      : int = 100,
        offset     : int = 0,
    ) -> List[TaskEvent]:
        """
        Return the cross-item event stream, filtered and newest first.

        This is the fleet-wide audit: the append-only trail across all items. get_events is one item's trail.

        Requires:
            - each filter is None (no constraint) or an exact-match value;
              since and until bound TaskEvent.ts inclusively
            - limit and offset are non-negative ints

        Ensures:
            - returns events matching all provided filters (every filter must match)
            - project filters via a join to the owning TaskItem, since events carry no project column of their own
            - to_status matches transitions ending in "->{to_status}"; the router's validation of that value is required,
              because % and _ are `LIKE` wildcards that would silently widen the match
            - ordered by ts descending then id descending (newest first, stable total order)
            - paginated via limit and offset

        Returns:
            List of TaskEvent instances (may be empty)
        """
        # EAGER-LOAD THE ITEM. `_serialize_event` puts the item's TITLE on the wire, and a
        # lazy relationship would emit one SELECT per event — N+1 across a page capped at 500.
        # The fix that creates a worse problem than it solves is not a fix (row 2c6a87f3).
        query = self.session.query( TaskEvent ).options( joinedload( TaskEvent.item ) )

        if project is not None:
            query = query.join( TaskItem, TaskEvent.item_id == TaskItem.id ).filter( TaskItem.project == project )
        if actor is not None:      query = query.filter( TaskEvent.actor == actor )
        if transition is not None: query = query.filter( TaskEvent.transition == transition )
        # `to_status` asks the question the CALLER means — "which rows reached `done`?" — which
        # the exact-match `transition` filter cannot express: transitions are "from->to" strings
        # and 7 non-terminal sources x 3 terminal targets is 21 separate calls. The suffix is
        # exact because a transition carries exactly one "->" (creation stamps "->queued", which
        # this matches deliberately).
        # ⚠️ THE ROUTER'S VALIDATION IS LOAD-BEARING, NOT COSMETIC: `%` and `_` are LIKE
        # wildcards, so an unvalidated value would silently widen the match instead of erroring.
        if to_status is not None:  query = query.filter( TaskEvent.transition.like( f"%->{to_status}" ) )
        if since is not None:      query = query.filter( TaskEvent.ts >= since )
        if until is not None:      query = query.filter( TaskEvent.ts <= until )

        return query.order_by( TaskEvent.ts.desc(), TaskEvent.id.desc() ).limit( limit ).offset( offset ).all()

    def approval_card_ids_used( self, card_id: uuid.UUID ) -> set:
        """
        The cited card id as a one-element set if an event already carries it, else an empty set.

        It is the single-use check for an un-park card. The event trail is the record, so no
        second table can drift from it. A card is used when any event, on any row, names it.

        Requires:
            - card_id is the UUID of the card the caller cited

        Ensures:
            - returns { str( card_id ) } when at least one event names it, else an empty set
            - reads the trail in SQL, one round trip, and writes nothing
        """
        found = (
            self.session.query( func.count( TaskEvent.id ) )
                .filter( TaskEvent.receipt_refs[ "approval_card" ].astext == str( card_id ) )
                .scalar()
        ) or 0
        return { str( card_id ) } if found else set()

    def count_admissions_since( self, actor: str, since: datetime ) -> int:
        """
        Count the rows this caller has admitted out of the holding area since `since`.

        This backs the rule that a manager requests one ticket at a time and never fires a batch. There is no batch endpoint to refuse. The UI's batch approve is a client-side loop of single-row transitions. Only how many arrived, and how fast, tells a batch from a ticket. The event trail already records that, in the same transaction that moved the row. This is a query rather than a counter. It adds no new state. There is no in-memory counter to lose on a bounce. The evidence for any refusal is a row somebody can read. It is a policy control, not a security boundary: actor is caller-declared, so varying it splits the count.

        Requires:
            - actor is the caller-declared actor string; since is a tz-aware datetime

        Ensures:
            - counts only admissions out of the holding area, meaning events whose transition
              begins "not_approved->", never every transition the caller made
            - excludes the not_approved->not_approved no-op, which admits nothing
            - counts in SQL, so a long window costs one round trip rather than N rows
            - returns 0 for an actor with no such events

        Returns:
            int, the admissions by this actor at or after `since`
        """
        return (
            self.session.query( func.count( TaskEvent.id ) )
                .filter( TaskEvent.actor == actor )
                .filter( TaskEvent.ts >= since )
                .filter( TaskEvent.transition.like( "not_approved->%" ) )
                .filter( TaskEvent.transition != "not_approved->not_approved" )
                .scalar()
        ) or 0

    def count_created_and_closed(
        self,
        since   : datetime,
        until   : Optional[datetime] = None,
        project : Optional[str]      = None,
    ) -> dict:
        """
        Count creations and closures in a time window, in SQL.

        This feeds the closed-vs-new ratio gate. query_events cannot answer it. Its filters are exact-match, closures arrive as several strings, and a page length caps at 500, the limit of query_tasks and the endpoint. Created matches the prefix pattern "->%" (an empty left side). Closed matches "%->done". Patterns replace status lists, so a new status cannot undercount silently. The dropped status is excluded from closed, and the accepted cost is that legitimate board hygiene earns no credit. Otherwise dropping stale rows and minting new ones would hold the ratio forever. A row created directly into done matches both patterns and counts once in each (pinned by test_a_row_born_done_would_count_as_both).

        Requires:
            - since is a datetime bounding TaskEvent.ts inclusively (>=)
            - until is None (meaning up to now) or a datetime bounding it inclusively
            - project is None (fleet-wide) or an exact project name

        Ensures:
            - returns { "created": int, "closed": int, "window_start": datetime,
                        "window_end": datetime | None, "project": str | None }
            - counts come from a SQL `COUNT`, never from len() of a page, so no cap applies
            - items whose correlation_key starts with FLOW_EXCLUDED_KEY_PREFIX are excluded from both counts
            - the caller computes the ratio, because division by zero is a policy question and policy does not belong in a repository:
              closed == 0 with creations is a deny, and 0/0 is an allow

        Returns:
            dict as described above; both counts are 0 on an empty window, never None
        """
        created_pattern = CREATED_TRANSITION_LIKE
        closed_pattern  = CLOSED_TRANSITION_LIKE

        def _scoped( pattern ):
            q = self.session.query( func.count( TaskEvent.id ) )
            # The janitor's straggler lane is not flow (Rick's keypress, 2026-09-29): its
            # rows are minted by the arbiter and close as `dropped`, which this count never
            # credits, so counting their creation would tax every other create forever.
            # A NOT IN over that lane's (few) ids keeps fleet-wide free of the join.
            q = q.filter( ~TaskEvent.item_id.in_(
                select( TaskItem.id ).where( TaskItem.correlation_key.startswith( FLOW_EXCLUDED_KEY_PREFIX ) ) ) )
            if project is not None:
                q = q.join( TaskItem, TaskEvent.item_id == TaskItem.id ).filter( TaskItem.project == project )
            q = q.filter( TaskEvent.transition.like( pattern ) )
            q = q.filter( TaskEvent.ts >= since )
            if until is not None: q = q.filter( TaskEvent.ts <= until )
            return q.scalar() or 0

        return {
            "created"      : _scoped( created_pattern ),
            "closed"       : _scoped( closed_pattern ),
            "window_start" : since,
            "window_end"   : until,
            "project"      : project,
        }

    def _append_event(
        self,
        item_id      : uuid.UUID,
        actor        : str,
        transition   : str,
        authority    : str,
        receipt_refs : Optional[dict],
        reason       : Optional[str] = None,
        ts           : Optional[datetime] = None,
    ) -> TaskEvent:
        """
        Append one audit-trail event row (internal helper).

        Requires:
            - item_id references an item present in this session
            - actor, transition and authority are non-empty strings
            - ts is an explicit event timestamp, or None for the column default (func.now()).
              Only the park path passes it, because the park event must carry the same instant as
              park_reason_captured_at on any backend

        Ensures:
            - TaskEvent added and flushed (id populated); commit is not called
            - the event is parked on the session so that its `COMMIT` (never a rollback)
              emits one task_store_changed (task_store_change_notifier)
            - event.ts == ts when supplied, else the func.now() default

        Returns:
            The appended TaskEvent instance
        """
        event = TaskEvent(
            item_id      = item_id,
            actor        = actor,
            transition   = transition,
            receipt_refs = receipt_refs,
            authority    = authority,
            reason       = reason,
        )
        if ts is not None: event.ts = ts
        self.session.add( event )
        self.session.flush()
        change_notifier.record_appended_event( self.session, event )
        return event
