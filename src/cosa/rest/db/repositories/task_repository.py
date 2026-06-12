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
              + authority
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

        return self._append_event( item.id, actor, transition_label, authority, receipt_refs )

    def query_tasks(
        self,
        owner_persona       : Optional[str] = None,
        status              : Optional[str] = None,
        gate_class          : Optional[str] = None,
        accountable_manager : Optional[str] = None,
        project             : Optional[str] = None,
        item_class          : Optional[str] = None,
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

        return query.order_by( TaskItem.created_ts.desc(), TaskItem.id ).limit( limit ).offset( offset ).all()

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

    def _append_event(
        self,
        item_id      : uuid.UUID,
        actor        : str,
        transition   : str,
        authority    : str,
        receipt_refs : Optional[dict],
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
        )
        self.session.add( event )
        self.session.flush()
        return event
