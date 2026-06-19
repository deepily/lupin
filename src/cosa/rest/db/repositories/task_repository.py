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

from datetime import datetime
from typing import Optional, List
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.db.repositories.base import BaseRepository


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
        source_qid          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
    ) -> TaskItem:
        """
        Create a new task item plus its "->queued" creation event.

        Requires:
            - item_class/gate_class/priority/authority already validated by
              task_store_rules.validate_create (router responsibility)
            - title, project, created_by are non-empty strings

        Ensures:
            - item created with status='queued' (creation is ALWAYS queued;
              transitions move it from there)
            - exactly one TaskEvent with transition='->queued' appended,
              actor = created_by (the creator IS the creation actor)
            - flush() called so item.id is populated
            - commit NOT called (caller's get_db() commits)

        Returns:
            Created TaskItem instance (with id populated)
        """
        item = self.create(
            item_class          = item_class,
            title               = title,
            body                = body,
            project             = project,
            owner_persona       = owner_persona,
            accountable_manager = accountable_manager,
            created_by          = created_by,
            status              = "queued",
            blocked_by          = [ ],
            gate_class          = gate_class,
            priority            = priority,
            source_qid          = source_qid,
            correlation_key     = correlation_key,
        )
        self._append_event( item.id, created_by, "->queued", authority, receipt_refs=None )
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
    ) -> TaskEvent:
        """
        Apply an ALREADY-VALIDATED transition: update the item + append the event.

        Requires:
            - item is a TaskItem loaded in THIS session
            - the transition has passed task_store_rules.validate_transition
              (router responsibility — this method never re-validates)

        Ensures:
            - item.status set to to_status
            - to_status == 'blocked': item.next_chase_ts + item.blocked_by set
            - to_status != 'blocked': item.next_chase_ts cleared and
              item.blocked_by emptied (an unblocked item is blocked on nothing)
            - exactly one TaskEvent ("from->to") appended with receipt_refs
              + authority + reason (reason non-None for ->dropped by rule)
            - flush() called; commit NOT called (caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        transition_label = f"{item.status}->{to_status}"

        item.status = to_status
        if to_status == "blocked":
            item.next_chase_ts = next_chase_ts
            item.blocked_by    = blocked_by
        else:
            item.next_chase_ts = None
            item.blocked_by    = [ ]

        return self._append_event( item.id, actor, transition_label, authority, receipt_refs, reason=reason )

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
        item      : TaskItem,
        fields    : dict,
        actor     : str,
        authority : str,
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

        Ensures:
            - each provided field whose value differs is written onto the item
            - exactly one TaskEvent appended: transition='patched',
              receipt_refs=None, reason = the field delta ("k: old -> new; ...")
              or a no-op marker when nothing actually changed (R3 — the edit is
              auditable either way)
            - flush() called; commit NOT called (caller's get_db() commits)

        Returns:
            The appended TaskEvent instance
        """
        changes = [ ]
        for key, new_value in fields.items():
            old_value = getattr( item, key )                 # key is whitelist-validated, never arbitrary — fails loud if absent
            if old_value != new_value:
                setattr( item, key, new_value )
                changes.append( f"{key}: {old_value!r} -> {new_value!r}" )

        reason = "; ".join( changes ) if changes else "no-op patch (no field changed)"
        return self._append_event( item.id, actor, "patched", authority, receipt_refs=None, reason=reason )

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
        accountable_manager : Optional[str] = None,
        project             : Optional[str] = None,
        item_class          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
        limit               : int = 100,
        offset              : int = 0,
    ) -> List[TaskItem]:
        """
        The deterministic owed-work query (design R4) — identical for every caller.

        Requires:
            - each filter is either None (no constraint) or an exact-match value
            - limit/offset are non-negative ints

        Ensures:
            - returns items matching ALL provided filters (AND semantics)
            - ordered by created_ts descending (newest first), then id for
              a stable total order
            - paginated via limit/offset

        Returns:
            List of TaskItem instances (may be empty)
        """
        query = self.session.query( TaskItem )

        if owner_persona is not None:       query = query.filter( TaskItem.owner_persona == owner_persona )
        if status is not None:              query = query.filter( TaskItem.status == status )
        if gate_class is not None:          query = query.filter( TaskItem.gate_class == gate_class )
        if accountable_manager is not None: query = query.filter( TaskItem.accountable_manager == accountable_manager )
        if project is not None:             query = query.filter( TaskItem.project == project )
        if item_class is not None:          query = query.filter( TaskItem.item_class == item_class )
        if correlation_key is not None:     query = query.filter( TaskItem.correlation_key == correlation_key )

        return query.order_by( TaskItem.created_ts.desc(), TaskItem.id ).limit( limit ).offset( offset ).all()

    def count_tasks(
        self,
        owner_persona       : Optional[str] = None,
        status              : Optional[str] = None,
        gate_class          : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        project             : Optional[str] = None,
        item_class          : Optional[str] = None,
        correlation_key     : Optional[str] = None,
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
            - returns the integer count of items matching ALL provided filters
            - no ORDER BY / LIMIT / OFFSET — a count is order- and page-independent
        """
        query = self.session.query( func.count( TaskItem.id ) )

        if owner_persona is not None:       query = query.filter( TaskItem.owner_persona == owner_persona )
        if status is not None:              query = query.filter( TaskItem.status == status )
        if gate_class is not None:          query = query.filter( TaskItem.gate_class == gate_class )
        if accountable_manager is not None: query = query.filter( TaskItem.accountable_manager == accountable_manager )
        if project is not None:             query = query.filter( TaskItem.project == project )
        if item_class is not None:          query = query.filter( TaskItem.item_class == item_class )
        if correlation_key is not None:     query = query.filter( TaskItem.correlation_key == correlation_key )

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

    def _append_event(
        self,
        item_id      : uuid.UUID,
        actor        : str,
        transition   : str,
        authority    : str,
        receipt_refs : Optional[dict],
        reason       : Optional[str] = None,
    ) -> TaskEvent:
        """
        Append one audit-trail event row (internal helper).

        Requires:
            - item_id references an item present in this session
            - actor/transition/authority are non-empty strings

        Ensures:
            - TaskEvent added + flushed (id populated); commit NOT called

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
        self.session.add( event )
        self.session.flush()
        return event
