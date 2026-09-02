"""
Task repository for the unified task store (Phase 1).

Persistence-only layer: structural validation lives in
cosa.rest.task_store_rules (pure functions, called by the router BEFORE any
repository write). Every state change writes exactly one append-only
TaskEvent row in the same session that updates the TaskItem — atomicity is
the caller's get_db() transaction.

Canonical design: planning-is-prompting ->
src/rnd/2026.06.11-unified-task-store-design.md (v0.4) §2.1-§2.2.
"""

from datetime import datetime, timezone
from typing import Optional, List
import uuid

from sqlalchemy import func, select, cast, String
from sqlalchemy.orm import Session

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
from cosa.rest.task_store_owed import PARK_STATUS, owed_clause, owed_status_clause


class TaskRepository( BaseRepository[TaskItem] ):
    """
    Repository for TaskItem with the task-store query + transition operations.

    Extends BaseRepository with:
        - create_item: item row + "->queued" creation event in one unit
        - apply_transition: status change + append-only event in one unit
        - query_tasks: the deterministic owed-work query (design R4)
        - get_events: the per-item audit trail (design R3)
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
        Load one item under a row lock (SELECT ... FOR UPDATE) for a
        read-validate-write transition.

        Cold-review N3: without the lock, two concurrent transitions both
        validate against the same stale from_status and the terminal lockout
        is bypassable under race — and concurrent multi-session writes are
        this store's reason to exist. The lock serializes transitions per
        item: the second transaction blocks until the first commits, then
        reads the COMMITTED status, so validation always sees fresh state.

        Requires:
            - id: TaskItem UUID
            - called inside the SAME get_db() transaction that will apply
              the transition (the lock lives and dies with that transaction)

        Ensures:
            - returns the row-locked entity, or None if not found

        Returns:
            TaskItem instance or None
        """
        return (
            self.session.query( TaskItem )
            .filter( TaskItem.id == id )
            .with_for_update()
            .first()
        )

    def find_by_id_prefix( self, compact_prefix: str, limit: int = 10 ) -> List[ TaskItem ]:
        """
        Find items whose id starts with a compact (hyphen-free) hex prefix.

        Supports the 8-hex form every brief in this fleet writes (f45b37a9 leg 1).
        READ path only — the mutating routes keep strict UUID typing, because a
        prefix that resolves wrong on a read is merely wrong while on a write it
        would move a row nobody named.

        Requires:
            - compact_prefix is lowercase hex with hyphens ALREADY stripped
              (task_store_rules.classify_task_ref produces exactly this shape);
              this method does not re-validate caller text
            - limit bounds the scan

        Ensures:
            - returns items whose canonical hyphenated id starts with the
              prefix, at most `limit` of them. BOUNDED deliberately: the caller
              only needs to distinguish none / one / more-than-one, and an
              unbounded LIKE on a table that only grows is the unscoped-query
              defect in another costume
            - the compact prefix is re-hyphenated to canonical UUID positions
              before matching, so a prefix longer than 8 chars (which spans a
              hyphen) still matches the stored rendering
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
        Resolve blocker ids to statuses in ONE query — the read-side half of row 00a6bde2.

        ONE QUERY PER PAGE, NOT ONE PER ROW. This runs on the read path of every
        `task_query`, so a per-row lookup would put an N+1 on the board glance that the
        terse projection exists to make cheap. The caller collects every item-kind blocker
        id across the whole page and asks once.

        ⚠️ AN ID THAT DOES NOT RESOLVE IS RETURNED AS AN EXPLICIT None, NOT OMITTED — and
        that distinction is the entire contract. `blocker_is_terminal` treats a key present
        with None as "looked up and ABSENT" (a finding: the edge points at nothing) and a
        key MISSING as "never looked up" (no finding). Collapsing the two would make a
        failed resolution indistinguishable from a blocker nobody asked about, which is the
        same silent-bucket shape the row was filed about.

        MALFORMED IDS ARE PART OF THE ANSWER, not an exception. `blocked_by` is app-typed
        JSON, so an id that is not a UUID at all reached the column and must resolve to
        None like any other dead reference — raising here would take down the whole query
        over one bad edge.

        Requires:
            - ref_ids is an iterable of candidate id strings (duplicates fine, order
              irrelevant, empty fine)

        Ensures:
            - returns { id_str: status_str_or_None } with EXACTLY one key per distinct
              input id — every id asked about is answered
            - a full-UUID id that matches no row maps to None (a genuinely dead edge)
            - an 8-hex-style PREFIX id resolves by prefix, exactly as `task_get` does, and
              maps to that row's status when the prefix matches EXACTLY ONE row
            - an AMBIGUOUS or unmatched prefix maps to None; the caller must not read that
              as "dead" for a non-canonical id (see `blocker_is_terminal`)
            - never raises; an empty input returns {} and issues NO query
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
        priority            : str = "P2",
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
            - item_class/gate_class/priority/authority already validated by
              task_store_rules.validate_create (router responsibility)
            - status is queued or blocked, already whitelist-validated by
              task_store_rules.validate_create_status (router responsibility); a
              blocked mint's blocked_by / next_chase_ts already satisfy the
              ->blocked invariant (>=1 typed ref + kind-aware chase) — this method
              never re-validates
            - title, project, created_by are non-empty strings
            - flag_suffix is an OPTIONAL advisory marker (e.g. the persona-flag
              "[persona_flag: … off-roster]") the router folds into the creation
              event's reason; None means no marker (the reason stays None)

        Ensures:
            - item created with the given status (DEFAULT 'queued' — today's
              behavior). Per-status field consistency is DELEGATED to
              task_store_rules.normalize_status_fields, which apply_transition
              also calls — ONE implementation, so the two write paths cannot
              drift (86ce4c43 #2). This method no longer owns those rules:
                * status == 'blocked' -> blocked_by is the given list (or [] when
                  None)
                * any other status -> blocked_by := [], dropping stray refs (a
                  non-blocked row waits on nothing)
                * next_chase_ts is the caller's value on EVERY status — a chase is
                  a SCHEDULE, not a WAIT, and is no longer nulled outside
                  blocked/parked
            - exactly one TaskEvent with transition='->{status}' appended (so a
              blocked mint stamps '->blocked'), actor = created_by (the creator IS
              the creation actor), reason = flag_suffix, EXTENDED with a
              "[dropped: …]" marker naming any field the normalizer discarded, so
              a discard is disclosed in the audit trail rather than swallowed on a
              200 (zero schema, zero new events; both markers ride the existing
              event reason)
            - flush() called so item.id is populated
            - commit NOT called (caller's get_db() commits)

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
        Apply an ALREADY-VALIDATED transition: update the item + append the event.

        Requires:
            - item is a TaskItem loaded in THIS session
            - the transition has passed task_store_rules.validate_transition
              (router responsibility — this method never re-validates)

        Ensures:
            - item.status set to to_status
            - to_status == 'blocked': item.next_chase_ts + item.blocked_by set;
              park_reason + park_reason_captured_at cleared
            - to_status == 'parked': item.next_chase_ts set (the chase IS the
              un-park — read-time expiry) + item.park_reason set; blocked_by
              emptied (a parked item waits on nothing; a human ruled it not-now);
              item.park_reason_captured_at AND item.updated_ts both stamped with
              ONE DB-clock instant in a SINGLE statement, so they are equal by
              construction (see _park_capture_ts — the §3.4 ordering, and why
              the design's read-back sequence cannot commit)
            - any OTHER status: item.next_chase_ts cleared, item.blocked_by
              emptied, item.park_reason + item.park_reason_captured_at cleared
              (an unblocked item is blocked on nothing; an unparked item carries
              no park justification, and a capture time must not outlive the
              quote it dates)
            - exactly one TaskEvent ("from->to") appended with receipt_refs
              + authority + reason (reason non-None for ->dropped by rule); on
              ->parked that event's `ts` IS park_reason_captured_at, so the
              column and the audit row record ONE instant, not two (AC10)
            - flush() called; commit NOT called (caller's get_db() commits)

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
            return self._append_event(
                item.id, actor, transition_label, authority, receipt_refs, reason=reason, ts=captured
            )

        return self._append_event( item.id, actor, transition_label, authority, receipt_refs, reason=reason )

    def _db_clock_now( self ) -> datetime:
        """
        Read the DATABASE clock, tz-normalized. **The one clock every timestamp
        that gets COMPARED to another must come from.**

        Two columns are compared by `task_store_owed.park_reason_is_stale`:
        `park_reason_captured_at` (stamped at park) and `body_changed_ts` (stamped
        on a real body change). Both come from here. Take either from
        `datetime.now()` instead and the comparison becomes cross-clock, where skew
        surfaces as a **false FRESH** — a parked row silently failing to report an
        expired quote. That is the feature's own defect arriving in the direction
        nobody notices, which is why the source is centralized here rather than
        re-decided at each writer.

        Requires:
            - an open session/transaction (the caller's; this reads, never writes)

        Ensures:
            - returns a tz-aware UTC datetime from the DB clock
            - a naive return is converted to tz-aware UTC, so the value compares
              correctly against the tz-aware column on every backend
            - commit NOT called; nothing is written here

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
        Read the DATABASE clock for the park write's single timestamp — the one
        instant stamped into `updated_ts`, `park_reason_captured_at`, and the
        park event's `ts`.

        WHY NOT THE POST-WRITE READ-BACK THE DESIGN DESCRIBES (§3.4). The design
        says "capture the post-write `updated_ts`, read back in the same
        transaction," which reads as: flush the park, read `updated_ts`, then
        UPDATE `park_reason_captured_at` to match. THAT SEQUENCE CANNOT COMMIT.
        The first flush writes status='parked' with `park_reason_captured_at`
        still NULL, and `ck_task_items_parked_requires_captured_at` is evaluated
        PER STATEMENT, not at commit — so the park 500s on its own CHECK before
        the second statement is ever reached. PostgreSQL cannot defer a CHECK
        (only UNIQUE/PK/FK/EXCLUDE take DEFERRABLE), so there is no version of
        the two-step that works. Verified end-to-end, not reasoned about: the
        read-back implementation passed 156 unit tests and then 500'd on the
        first real park through the API.

        So the write is SINGLE-STATEMENT: take the timestamp first, assign it to
        both columns, flush once. `updated_ts` is assigned EXPLICITLY, which
        suppresses its `onupdate=func.now()` for this statement — otherwise the
        column would advance past the capture we just wrote and every parked row
        would be BORN STALE, which is the trap §3.4 exists to name.

        This satisfies §3.4's INTENT exactly — `park_reason_captured_at` equals
        the `updated_ts` this write leaves on the row — and pins it harder than
        a read-back could: the equality is true by construction rather than by
        the two values happening to agree.

        WHY THE DB CLOCK AND NOT `datetime.now()`. Every other `updated_ts` in
        this table is written by `onupdate=func.now()`, i.e. the DATABASE's
        clock. Staleness compares a capture against a LATER `updated_ts` written
        by that path, so a capture taken from the APPLICATION's clock would make
        the comparison cross-clock, and any skew would show up as a false FRESH
        — a parked row quietly failing to report a quote that has expired, which
        is the exact defect this build exists to detect. One clock, one value.

        On PostgreSQL `now()` is `transaction_timestamp()` and is stable across
        the transaction, so this returns precisely the value `onupdate` would
        have written — the explicit assignment changes the mechanism, not the
        number.

        Requires:
            - an open session/transaction (the caller's; this reads, never writes)

        Ensures:
            - returns a tz-aware UTC datetime from the DB clock
            - a naive return is converted to tz-aware UTC, so the value compares
              correctly against the tz-aware column on every backend
            - commit NOT called; nothing is written here

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
        Re-stamp an item's correlation_key + append the audit event (Phase 2 —
        the cross-session respawn adoption seam: a successor session
        re-registers its harness task id onto the inherited item instead of
        forking a duplicate).

        Requires:
            - item is a TaskItem loaded in THIS session (row-locked by the
              router, N3 parity) and NOT terminal (router-validated)
            - correlation_key / actor / authority already validated (router)

        Ensures:
            - item.correlation_key set to correlation_key (status untouched)
            - exactly one TaskEvent appended: transition='re-correlated',
              receipt_refs=None, reason='correlation_key: <old> -> <new>'
              (R3 — the adoption is auditable)
            - flush() called; commit NOT called (caller's get_db() commits)

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
        Apply an ALREADY-VALIDATED item-field edit + append a 'patched' event.

        Touches ONLY the editable presentation/ownership fields the caller set;
        status / blocked_by / next_chase_ts / receipt_refs / correlation_key are
        NEVER written here — they ride apply_transition / apply_correlation, so
        the transition oracle is never bypassed (reviewer ruling 2026-06-15).

        Requires:
            - item is a TaskItem loaded in THIS session (row-locked by the
              router, N3 parity) and NOT terminal (router-validated)
            - fields keys are whitelist-validated editable field names
              (router validated via task_store_rules.validate_patch); values
              already wire-checked by the TaskPatchIn Pydantic model
            - reason is an OPTIONAL caller-supplied justification (e.g. why a
              task was reassigned); None / "" means "no justification given".
              It is APPENDED to the field delta, never substituted for it
            - flag_suffix is an OPTIONAL advisory marker (the persona-flag
              "[persona_flag: … off-roster]") appended to the resolved event
              reason; None means no marker (the reason is unchanged)

        ⚠️ STAMPS `body_changed_ts` — ONLY when `body` is in `fields` AND its value
        actually DIFFERS (bug 54924128, 2026-07-26). That condition IS the fix. The
        other four free-edit fields (title / priority / gate_class / urgency) cannot
        make a park quote untrue, so they must leave the marker alone; before this,
        `park_reason_is_stale` read `updated_ts`, which every write bumps, and a
        priority-only edit during a routine board recut defamed correct quotes —
        0 of 2 live parked rows correctly flagged when it was found.

        A no-op body write (same text) stamps NOTHING: the quote cannot have been
        invalidated by text that did not change, and stamping there would re-import
        the false-positive class through a narrower door.

        ⚠️ THE DELTA IS NEVER SUBSTITUTED (bug a01e4e2a, 2026-08-28). This used to
        read `reason if reason else <delta>`: a caller-supplied reason REPLACED the
        computed before/after, so a `task_edit` overwriting a 60,000-character body
        with a polite justification recorded only the justification and the prior
        text was unrecoverable from the event log. That rewarded the careless caller
        with the better audit trail. The delta now always leads and the caller's
        reason rides after it.

        Ensures:
            - each provided field whose value differs is written onto the item
            - body_changed_ts stamped from the DB clock IFF `body` changed value
            - exactly one TaskEvent appended: transition='patched',
              receipt_refs=None, reason ALWAYS opens with the field delta
              ("k: old -> new; ...") — or the no-op marker when nothing actually
              changed — and the caller-supplied `reason`, when non-empty, is
              APPENDED after " | reason: " rather than replacing it (bug
              a01e4e2a). flag_suffix is appended last when present, so delta +
              caller reason + off-roster marker all survive on the one event
              (R3 — zero schema churn)
            - flush() called; commit NOT called (caller's get_db() commits)

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
        Append a persona-stamped + timestamped amendment block to a live item's
        body + append an 'amended' audit event — the APPEND-ONLY body-amend seam
        (Krishna's mid-flight scope-reframe friction, 2026-07-02).

        Unlike apply_patch (which OVERWRITES item.body destructively), this NEVER
        rewrites the existing body: the original text is preserved verbatim and
        the note is appended below a `[amendment · <actor> · <utc>]` divider, so
        a successor rehydrating from the store reads the FULL amendment history
        inline — closing the gap where the durable record of the CURRENT spec
        leaked outside the store (scratchpad checklists / code comments /
        transition reasons).

        POST-TERMINAL ADDENDUM (Rick's ruling 2026-08-02, row 3c569786). Amend is
        the ONE write verb the store allows on a TERMINAL row: a gate verdict
        written after a worker self-closes their row has nowhere durable to go
        otherwise. On a done/dropped item the divider reads `[post-terminal
        addendum · <actor> · <utc> · row was '<status>' at write — added after
        close, not a reopening]` and the audit event's transition is
        'amended_post_terminal' (not 'amended'), so the addendum is unmistakable
        from the original body and queryable in history. Status is NOT changed —
        transition / edit / correlate remain refused on a terminal row.

        Requires:
            - item is a TaskItem loaded in THIS session (row-locked by the router,
              N3 parity). It MAY be terminal — a post-terminal amend is legal
              (Rick 2026-08-02); the status read here selects the divider + event
            - note is the caller's amendment text (wire-checked 1..4000 + the
              router rejects a whitespace-only note)
            - now is a timezone-aware datetime (the router owns the clock so this
              method stays deterministic — mirrors apply_chase's injected time)
            - reason is an OPTIONAL justification stamping the audit event; None /
              "" means "auto-describe the amendment"

        Ensures:
            - item.body := the original body (verbatim) + a blank line + the
              stamped block when the body was non-empty; the stamped block ALONE
              when the body was empty/None (no leading blank lines on a first
              amendment)
            - item.body_changed_ts stamped from the DB clock UNCONDITIONALLY — an
              amend only ever APPENDS, so the body always changed. This is the
              other half of bug 54924128's fix: the marker must still go TRUE on a
              genuine body change, or the fix is indistinguishable from deleting
              the feature. ⚠️ The DB clock, never datetime.now(): this value is
              compared against park_reason_captured_at, and a cross-clock compare
              would surface skew as a false FRESH (see _db_clock_now)
            - the divider is the ordinary `[amendment · …]` on a non-terminal
              row, and the distinct `[post-terminal addendum · … · row was
              '<status>' at write — added after close, not a reopening]` on a
              done/dropped row
            - item.status is NEVER touched (an amend is not a transition) — a
              terminal row stays terminal; nothing here reads as a reopening
            - exactly one TaskEvent appended: transition='amended' on a live row,
              'amended_post_terminal' on a terminal row (so late verdicts are
              queryable), receipt_refs=None, reason = the caller-supplied `reason`
              when it is non-empty, else an auto-marker naming the appended length
              (R3 — the amendment is auditable either way)
            - flush() called; commit NOT called (caller's get_db() commits)

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
        Return blocked items whose next_chase_ts is at/before `now` (design I3 —
        the chase consumer's due-list; "no 'pending X' graves" made operational).

        Requires:
            - now is a timezone-aware datetime (the chase cutoff)
            - limit is a non-negative int

        Ensures:
            - returns items with status='blocked' AND next_chase_ts IS NOT NULL
              AND next_chase_ts <= now
            - ordered by next_chase_ts ascending (longest-overdue first)
            - read-only — NEVER mutates (the consumer re-arms via apply_chase)

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
        Record a chase on a blocked item: re-arm next_chase_ts (backoff) + append
        a 'chased' audit event. NEVER changes status (the consumer chases, it
        does not auto-transition — design: chasing is a nudge, not a decision).

        Requires:
            - item is a blocked TaskItem loaded in THIS session
            - next_chase_ts is the re-armed (future) chase time

        Ensures:
            - item.next_chase_ts set to next_chase_ts; item.status UNTOUCHED
            - exactly one TaskEvent appended: transition='chased',
              receipt_refs=None, reason names the re-armed time (R3 — auditable)
            - flush() called; commit NOT called (caller's get_db() commits)

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
    ) -> List[TaskItem]:
        """
        The deterministic owed-work query (design R4) — identical for every caller.

        The unscoped-query guard (design 2026.07.07) lives HERE at the repository
        layer so it is universal + un-bypassable by any repo-direct caller (the
        arbiter, the in-process watchers) — not just the REST/MCP surface.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - limit/offset are non-negative ints

        Ensures:
            - EXCLUDES terminal (done/dropped) rows by DEFAULT (include_terminal=
              False) UNLESS an explicit terminal `status` filter is set (you asked
              for terminal, you get it) — the 89->2 payload collapse. Pass
              include_terminal=True to include terminal rows on an un-status'd query.
            - HARD-FAILS with UnscopedQueryError when the query is UNSCOPED (no
              narrowing filter — see task_store_rules.is_unscoped) AND would return
              more than UNSCOPED_QUERY_THRESHOLD non-terminal rows AND
              unscoped_audit is False. The count is a cheap COUNT(*) (count_tasks),
              never a row materialization. A SCOPED query skips the guard entirely
              (zero overhead on the common path).
            - owed_only=True (PARKED-STATUS 2026-07-19) selects the OWED set:
              queued U in_progress U (parked AND NOT park-active). It REPLACES the
              status filter rather than narrowing it — see _apply_owed_filter.
            - returns items matching ALL provided filters (AND semantics)
            - ordered by created_ts descending (newest first), then id for
              a stable total order
            - paginated via limit/offset

        Raises:
            - UnscopedQueryError when the unscoped-over-threshold-not-audit
              conjunction holds (the router maps it to HTTP 400; the MCP verb to
              an error-dict)

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
            non_terminal = self.count_tasks( include_terminal=False, owed_only=owed_only, hide_parked=hide_parked, now=now, **filters )
            if non_terminal > UNSCOPED_QUERY_THRESHOLD:
                raise UnscopedQueryError( non_terminal, UNSCOPED_QUERY_THRESHOLD )

        query = self.session.query( TaskItem )

        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix
        )
        query = self._apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now )

        return query.order_by( TaskItem.created_ts.desc(), TaskItem.id ).limit( limit ).offset( offset ).all()

    @staticmethod
    def _apply_scalar_filters( query, owner_persona, status, gate_class, urgency,
                               accountable_manager, project, item_class, correlation_key,
                               id_prefix ):
        """
        The ONE place the exact-match filters are applied — shared by query_tasks,
        count_tasks and status_breakdown.

        EXTRACTED FOR THE SAME REASON `_apply_owed_filter` WAS, and the reason had
        already come true here. That helper's own docstring says the two methods
        "carried byte-identical filter blocks maintained by copy-paste" — and this
        block was carried in THREE copies at the time `id_prefix` was added. Adding a
        fourth by hand would have put the new filter on the page seam, the COUNT(*)
        seam and the breakdown seam as three independent edits, any one of which
        could be forgotten: the page would then narrow while the count did not, and
        `has_more` would be computed against a different population than the rows it
        describes. One helper means the three CANNOT disagree about which rows a
        filter admits.

        Requires:
            - query is a TaskItem query; every filter is None or an exact value
            - id_prefix, when present, is COMPACT lowercase hex (hyphens stripped)
              exactly as `classify_task_ref` returns — this method does NOT
              re-validate caller text, because a LIKE built from arbitrary input
              turns an id lookup into a search surface

        Ensures:
            - returns the query with one AND-ed filter per non-None argument
            - id_prefix matches on the id's canonical HYPHENATED rendering via the
              shared `hyphenate_compact_prefix` rule, so a prefix spanning a hyphen
              still matches
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
        return query

    @staticmethod
    def _apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now ):
        """
        The ONE place status/terminal/park selection is decided — shared VERBATIM by
        query_tasks and count_tasks (PARKED-STATUS 2026-07-19).

        Extracted deliberately. These two methods carried byte-identical filter
        blocks maintained by copy-paste; the COUNT(*) seam is precisely where the
        Stop-hook oracle diverges from what the UI shows, and a divergence there is
        invisible to every predicate-level test. One helper means the count and the
        page CANNOT disagree about what "owed" means.

        TWO selection policies, ONE clause. Both call owed_clause; they differ only
        in whether the STATUS ADMISSION also happens. The distinction is real and
        each reader genuinely needs its own:

          hide_parked=True (task_query R1, arbiter R3) — SUPPRESSION ONLY. These
            readers already select "all non-terminal", which ALREADY contains parked
            rows, so suppressing park-active ones is sufficient and an admission
            would WRONGLY narrow them (it would drop blocked/claimed/review off the
            board entirely).
          owed_only=True (Stop-hook R2) — SUPPRESSION **plus** STATUS ADMISSION.
            R2 selects only queued/in_progress, which never contained parked rows at
            all, so suppression alone can NEVER re-admit an expired one: parking
            MOVED the status out of "queued", and subtraction cannot restore a row
            that was never in the set. That asymmetry is the defect that made the
            purely-additive shape unbuildable.

        Requires:
            - query is a SQLAlchemy Query over TaskItem
            - owed_only / hide_parked are bools; status is a status string or None
            - now is a tz-aware datetime, or None to resolve it here (the IO
              boundary owns the clock so the predicates never read one — Rachel's
              boundary test needs `now` injectable without patching module state)

        Ensures:
            - owed_only=True selects queued U in_progress U (parked AND NOT
              park-active). Exact RESTORATION, never a widening: park is legal ONLY
              from OWED_BASE_STATUSES, so every expired-parked row provably came
              from that same set. An explicit `status` filter is applied upstream
              and is honored — owed_only then narrows within it.
            - hide_parked=True suppresses park-active rows WITHOUT touching the
              status set. Expired-parked rows stay VISIBLE — they have rejoined, and
              a row that pokes you while staying invisible on the board is the exact
              incoherence this build exists to remove.
            - an EXPLICIT status="parked" filter DISABLES suppression entirely: you
              asked for parked, you get all of them. This is the audit surface.
            - owed_only takes precedence over hide_parked (it is the stricter,
              fail-CLOSED policy); neither flag preserves the pre-existing
              terminal-exclusion default EXACTLY when both are False
            - never mutates the caller's query in place
        """
        if owed_only or ( hide_parked and status != PARK_STATUS ):
            if now is None:
                now = datetime.now( timezone.utc )
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
                query = query.filter( TaskItem.status.notin_( BOARD_INVISIBLE_STATUSES ) )
            return query.filter( owed_clause( TaskItem, now ) )
        # Terminal-exclusion default: an un-status'd query drops done/dropped unless
        # the caller opts in via include_terminal. An explicit `status` filter (incl.
        # status=done/dropped) governs on its own — no double-filtering.
        if not include_terminal and status is None:
            query = query.filter( TaskItem.status.notin_( BOARD_INVISIBLE_STATUSES ) )
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
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> dict:
        """
        The PER-STATUS breakdown of the SAME admitted set count_tasks totals — ONE
        GROUP BY, never N queries (c191be39, 2026-07-20).

        WHY THIS EXISTS: the Stop-hook store-count seam collapsed a multi-status owed
        set into one integer and the IO shell re-inflated it as all-in_progress, so
        every `queued` row reported to its owner as "in-progress" and the oracle's
        `todo_unstarted` signal became unreachable dead code. The status has to
        survive the seam, and the ONLY safe place to recover it is HERE — server-side,
        over the already-admitted set.

        ⛔ THIS IS NOT A LICENSE TO ENUMERATE STATUSES CLIENT-SIDE. The retired
        per-status client loop (deleted 2026-07-19) is forbidden for two independent
        reasons that this method does NOT reintroduce: it could not see a park-expiry
        rejoin, and it DOUBLE-COUNTED expired-parked rows. A GROUP BY partitions one
        admitted set — every row lands in exactly one bucket by construction, so the
        double-count is structurally unreachable rather than merely avoided.

        `parked` IS the expired-parked bucket, with no extra filtering: park-ACTIVE
        rows are already excluded by owed_status_clause, so every parked row that
        survives admission has provably rejoined. The key carries the RAW status
        string the column holds — inventing a `parked_expired` key here would imply a
        derivation that does not happen.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - the filter set is applied IDENTICALLY to count_tasks (same helper)

        Ensures:
            - returns { status: count } over ONLY the statuses actually present —
              absent statuses are OMITTED, never zero-filled (a zero-filled key is a
              claim about a status the query never saw)
            - sum( result.values() ) == count_tasks( <same filters> ) — asserted as a
              REAL parity gate between two independent computations, deliberately NOT
              derived one from the other (an invariant true by construction cannot
              fail, so it can never tell you anything)
            - {} when nothing matches
            - no ORDER BY / LIMIT / OFFSET — a breakdown is order- and page-independent
        """
        query = self.session.query( TaskItem.status, func.count( TaskItem.id ) )

        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix
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
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> dict:
        """
        The PER-PRIORITY breakdown of the SAME admitted set count_tasks totals —
        ONE GROUP BY, never N queries (Rick, 2026-07-27).

        WHY: the Stop-hook poke reported HOW MANY rows a seat owed and never WHICH
        ones mattered. Rick's standing instruction is to work in descending priority,
        and the poke that fires on every Stop had no priority in it at all — twelve
        owed rows read as one undifferentiated pile whether six were P1 or none were.

        Mirrors `count_tasks_by_status` exactly, including the sum-parity property:
        sum( result.values() ) == count_tasks( <same filters> ), two independent
        computations rather than one derived from the other.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - the filter set is applied IDENTICALLY to count_tasks (same helpers)

        Ensures:
            - returns { priority: count } over ONLY the priorities actually present —
              an absent priority is absent, never a 0 bucket, so a caller cannot
              mistake "no P0 rows" for "P0 was not measured"
            - keys are the RAW stored priority strings (P0..P3)
        """
        query = self.session.query( TaskItem.priority, func.count( TaskItem.id ) )
        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix
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
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> dict:
        """
        The PER-PROJECT breakdown of the admitted set WITH THE PROJECT FILTER
        DELIBERATELY ABSENT — the aperture a project-scoped query can report
        (bug `d23147e8`, item 3).

        WHY THIS EXISTS: `project` is free text. `TaskCreateIn.project` validates
        only `min_length=1, max_length=255`, and `_canon_project` passes any
        non-aliased name through unchanged, so a typo mints a project silently and
        permanently. A caller who queries `project="skills-distillation"` while a
        row sits under `"google-skills-distillation"` gets a clean, plausible,
        SMALLER number and no indication anything was excluded. That is how
        `52c1c41e` survived a census Rick's drop order was executed against.

        ⛔ THE PROJECT FILTER IS NOT A PARAMETER HERE, AND ITS ABSENCE IS THE POINT.
        Accepting one would let a caller scope the aperture to the very value whose
        blind spot it exists to reveal — the buckets it must report are precisely
        the ones the caller's `project=` did NOT match. A signature that cannot
        express the wrong question cannot be asked it.

        Every OTHER filter is applied, through the SAME two helpers `count_tasks`
        and `query_tasks` use. That is what makes the result comparable: the buckets
        answer "under my other constraints, what project values exist?" — not
        "what exists in the store," which would report projects the caller's own
        owner/status filters had already ruled out and read as a bigger blind spot
        than there is.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - the filter set is applied IDENTICALLY to count_tasks, minus project

        Ensures:
            - returns { project: count } over ONLY the projects actually present in
              the admitted set — an absent project is absent, never a 0 bucket
            - the key is the RAW stored string, NOT alias-canonicalized: reporting
              a canonical form would hide the orphan spelling that IS the finding
            - sum( result.values() ) == count_tasks( <same filters, project=None> )
            - a row whose project is NULL lands under the None key rather than being
              dropped — a row with no project is exactly the case a census must see
        """
        query = self.session.query( TaskItem.project, func.count( TaskItem.id ) )
        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, None, item_class, correlation_key, id_prefix
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
        include_terminal    : bool = False,
        owed_only           : bool = False,
        hide_parked         : bool = False,
        now                 : Optional[datetime] = None,
    ) -> int:
        """
        True COUNT(*) over the SAME filter set as query_tasks — no row materialization.

        The O2 token win (cascade review §G): the owed-count callers (the Stop-hook
        store-count seam) need a CARDINALITY, not the rows. query_tasks caps at
        limit<=500 and the endpoint reports len(page) as its "count" — a page-length
        that SATURATES once the true total exceeds the page size, so a session with
        >100 owed rows would read exactly 100. This computes the genuine total via a
        SQL COUNT(*) with identical AND-semantics filters, independent of any page
        bound (and without serializing a single row).

        Requires:
            - each filter is either None (no constraint) or an exact-match value

        Ensures:
            - EXCLUDES terminal (done/dropped) rows by DEFAULT (include_terminal=
              False) UNLESS an explicit terminal `status` filter is set — parity
              with query_tasks so the guard's count matches the payload it guards.
              The Stop-hook owed-count seam always passes a (non-terminal) `status`
              filter, so this default is behavior-neutral for it.
            - owed_only=True applies the IDENTICAL selection as query_tasks via the
              shared _apply_owed_filter, so the COUNT can never disagree with the
              page it counts (PARKED-STATUS 2026-07-19). This is the seam the
              Stop-hook oracle reads and the one place a silent divergence between
              "what pokes you" and "what you can see" would live.
            - returns the integer count of items matching ALL provided filters
            - no ORDER BY / LIMIT / OFFSET — a count is order- and page-independent
        """
        query = self.session.query( func.count( TaskItem.id ) )

        query = self._apply_scalar_filters(
            query, owner_persona, status, gate_class, urgency,
            accountable_manager, project, item_class, correlation_key, id_prefix
        )
        # The SAME helper query_tasks uses — this is the COUNT(*)/page parity seam
        # the Stop-hook oracle reads. Rachel's gate asserts
        # count_tasks(owed_only=True) == len(query_tasks(owed_only=True)).
        query = self._apply_owed_filter( query, owed_only, hide_parked, status, include_terminal, now )

        return query.scalar()

    def get_events( self, item_id: uuid.UUID ) -> List[TaskEvent]:
        """
        Return the append-only audit trail for one item (design R3).

        Requires:
            - item_id: TaskItem UUID (existence checked by the caller — a
              missing item simply has no events)

        Ensures:
            - returns events ordered by id ascending (insertion == audit order)

        Returns:
            List of TaskEvent instances (may be empty)
        """
        return (
            self.session.query( TaskEvent )
            .filter( TaskEvent.item_id == item_id )
            .order_by( TaskEvent.id )
            .all()
        )

    def query_events(
        self,
        actor      : Optional[str] = None,
        transition : Optional[str] = None,
        project    : Optional[str] = None,
        since      : Optional[datetime] = None,
        until      : Optional[datetime] = None,
        limit      : int = 100,
        offset     : int = 0,
    ) -> List[TaskEvent]:
        """
        The cross-item event stream (design backlog — Rick's fleet-wide audit):
        the append-only trail across ALL items, filtered + newest-first.
        Distinct from get_events, which is one item's trail.

        Requires:
            - each filter is None (no constraint) or an exact-match value;
              since/until bound TaskEvent.ts inclusively
            - limit/offset are non-negative ints

        Ensures:
            - returns events matching ALL provided filters (AND semantics)
            - project filters via a join to the owning TaskItem — events carry
              no project column of their own (one name, no denormalized copy)
            - ordered by ts descending then id descending (newest first, stable
              total order)
            - paginated via limit/offset

        Returns:
            List of TaskEvent instances (may be empty)
        """
        query = self.session.query( TaskEvent )

        if project is not None:
            query = query.join( TaskItem, TaskEvent.item_id == TaskItem.id ).filter( TaskItem.project == project )
        if actor is not None:      query = query.filter( TaskEvent.actor == actor )
        if transition is not None: query = query.filter( TaskEvent.transition == transition )
        if since is not None:      query = query.filter( TaskEvent.ts >= since )
        if until is not None:      query = query.filter( TaskEvent.ts <= until )

        return query.order_by( TaskEvent.ts.desc(), TaskEvent.id.desc() ).limit( limit ).offset( offset ).all()

    def count_created_and_closed(
        self,
        since   : datetime,
        until   : Optional[datetime] = None,
        project : Optional[str]      = None,
    ) -> dict:
        """
        Count creations and closures in a time window — SERVER-SIDE, in SQL.

        Feeds the closed-vs-new ratio gate (María's design,
        planning-is-prompting/src/rnd/2026.09.01-closed-vs-new-ratio-gate.md), which is
        Rick's durable, mechanical replacement for the ticket moratorium he declared by
        voice: "It's way too easy for you guys to add tickets to the list and way too hard
        to get them removed."

        🔴 WHY THIS EXISTS RATHER THAN A CALLER PAGING query_events. Two reasons, both
        measured rather than argued:

        1. `query_events` filters are EXACT-MATCH ("each filter is None or an exact-match
           value" — its own contract, one method up). Neither half of this question is an
           exact match. Closures arrive as several distinct strings, and an enumeration is
           a list somebody has to keep current: add a status, and the closure count
           silently undercounts with nothing failing.

        2. `query_events` returns a PAGE, and a caller counting `len( rows )` gets a number
           that is right until it quietly is not. The endpoint caps `limit` at 500. This
           returns a COUNT from the database, so there is no page to cap.

        SUFFIX AND PREFIX MATCHING, and the census behind each (whole board,
        `lupin_db_dev`, 2026-09-01):

            created  = transition LIKE '->%'      an EMPTY left side is the creation stamp
                       ->queued   2292
                       ->blocked     4
            closed   = transition LIKE '%->done'
                       in_progress->done  941   queued->done  659   blocked->done  210
                       review->done        56   parked->done   24

        ⚠️ A HARDCODED '->queued' WOULD UNDERCOUNT, and the rate depends entirely on the
        window you measure. María measured 2 of 10 creations as `->blocked` in one 24-hour
        window — 20%. Across the whole board it is 4 of 2296 — 0.17%. Both numbers are
        correct about different populations; neither is the rate. That is exactly why this
        matches a PREFIX instead of a status list.

        🔴 `dropped` IS EXCLUDED FROM `closed`, BY RULING, AND IT IS THE LOAD-BEARING
        CHOICE. If dropping counted, the gate is trivially defeated: drop three stale rows,
        mint three new ones, ratio holds at 1.0 forever and the list never shrinks — the
        exact asymmetry this was filed against, wearing a green light. The cost is that
        legitimate board hygiene earns no credit, accepted deliberately: the alternative is
        a gate satisfied by deleting the evidence.

        ⚠️ THE TWO PATTERNS CAN OVERLAP IN PRINCIPLE. A `->done` stamp — a row created
        directly into done — matches BOTH, and would count once in each. That is the right
        answer (a row really was created, and it really was closed), not a bug to suppress.
        Measured today: ZERO such events exist, and no `->dropped` either. Pinned by
        `test_a_row_born_done_would_count_as_both` so the assumption fails loudly rather
        than drifting.

        Requires:
            - since is a datetime bounding TaskEvent.ts inclusively (>=)
            - until is None (meaning "up to now") or a datetime bounding it inclusively
            - project is None (fleet-wide, which is Rick's ruling) or an exact project name

        Ensures:
            - returns { "created": int, "closed": int, "window_start": datetime,
                        "window_end": datetime | None, "project": str | None }
            - counts come from SQL COUNT, never from len() of a page, so no cap applies
            - the caller computes the ratio — division by zero is a POLICY question
              (`closed == 0` with creations is a DENY, `0/0` is an ALLOW showing "—"),
              and policy does not belong in a repository

        Returns:
            dict as described above; both counts are 0 on an empty window, never None
        """
        created_pattern = CREATED_TRANSITION_LIKE
        closed_pattern  = CLOSED_TRANSITION_LIKE

        def _scoped( pattern ):
            q = self.session.query( func.count( TaskEvent.id ) )
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
            - actor/transition/authority are non-empty strings
            - ts is an explicit event timestamp, or None for the column default
              (func.now()). ONLY the park path passes it: the park event must
              carry the SAME instant as park_reason_captured_at, because
              rejecting design option 4 left us with two records of one fact and
              AC10 requires them to AGREE. Passing the value rather than letting
              both default to now() makes that agreement structural — it holds
              on any backend, instead of riding PostgreSQL's transaction-stable
              now(), which is the only reason the defaults would have matched.

        Ensures:
            - TaskEvent added + flushed (id populated); commit NOT called
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
        return event
