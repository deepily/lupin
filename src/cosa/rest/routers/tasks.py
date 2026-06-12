"""
Unified task store REST surface — /api/tasks/* (Phase 1).

The deterministic owed-work API (design R4): arbiter, managers, workers, and
Rick all query the SAME store through these endpoints. Receipts are
first-class: a ->done transition without valid receipt_refs is REJECTED
(design T3 / §4.1 AC1 — the mechanical no-confabulation enforcement).

Endpoints (all authenticated via require_api_key_or_jwt — X-API-Key OR Bearer
JWT, §4.1 AC2; hook writers use the host API-key file, same lane as
cascade_heartbeat_scheduler):
    - POST /api/tasks                  — create item (always status=queued)
    - POST /api/tasks/{id}/transition  — state change; structural rules enforced
    - GET  /api/tasks                  — filtered query (owner/status/gate/manager/project/class)
    - GET  /api/tasks/{id}             — one item
    - GET  /api/tasks/{id}/events      — the append-only audit trail (R3)

DEBT-CLEAN MANDATE (design §2.2 C4): every handler here is a sync `def` —
FastAPI runs them in its threadpool. The DB layer is sync SQLAlchemy via
get_db(); sync work NEVER runs inside an `async def` handler (the legacy
notifications.py starvation pattern this surface must not grow).

Canonical design: planning-is-prompting ->
src/rnd/2026.06.11-unified-task-store-design.md (v0.4, Rick-ruled §3.1).
"""

from datetime import datetime
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest import task_store_rules as rules

router = APIRouter( prefix="/api", tags=[ "tasks" ] )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TaskCreateIn( BaseModel ):
    """
    Create body for POST /api/tasks.

    Creation is ALWAYS status=queued (the creation event stamps "->queued");
    enum membership for item_class/gate_class/priority/authority is validated
    by task_store_rules.validate_create in the handler (one rules home, not
    per-layer duplication).
    """
    item_class          : str            = Field( ..., min_length=1 )
    title               : str            = Field( ..., min_length=1 )
    project             : str            = Field( ..., min_length=1 )
    created_by          : str            = Field( ..., min_length=1, description="persona + session id of the creator" )
    authority           : str            = Field( default="standing" )
    body                : Optional[str]  = None
    owner_persona       : Optional[str]  = None
    accountable_manager : Optional[str]  = None
    gate_class          : str            = Field( default="none" )
    priority            : str            = Field( default="P2" )
    source_qid          : Optional[str]  = None
    correlation_key     : Optional[str]  = None


class TaskTransitionIn( BaseModel ):
    """
    Transition body for POST /api/tasks/{id}/transition.

    Structural rules (terminal states, receipts on ->done, next_chase_ts +
    typed blocked_by on ->blocked) are validated by
    task_store_rules.validate_transition in the handler.
    """
    to_status     : str                 = Field( ..., min_length=1 )
    actor         : str                 = Field( ..., min_length=1, description="persona + session id performing the transition" )
    authority     : str                 = Field( default="standing" )
    receipt_refs  : Optional[dict]      = None
    next_chase_ts : Optional[datetime]  = None
    blocked_by    : Optional[list]      = None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_item( item ) -> dict:
    """
    Serialize a TaskItem to the wire shape (field names identical to the
    model — one name at every layer).

    Requires:
        - item is a flushed TaskItem (id/created_ts/updated_ts populated)

    Ensures:
        - returns a JSON-safe dict; nullable timestamps serialize as None
    """
    return {
        "id"                  : str( item.id ),
        "item_class"          : item.item_class,
        "title"               : item.title,
        "body"                : item.body,
        "project"             : item.project,
        "owner_persona"       : item.owner_persona,
        "accountable_manager" : item.accountable_manager,
        "created_by"          : item.created_by,
        "status"              : item.status,
        "blocked_by"          : item.blocked_by,
        "next_chase_ts"       : item.next_chase_ts.isoformat() if item.next_chase_ts is not None else None,
        "gate_class"          : item.gate_class,
        "priority"            : item.priority,
        "source_qid"          : item.source_qid,
        "correlation_key"     : item.correlation_key,
        "created_ts"          : item.created_ts.isoformat(),
        "updated_ts"          : item.updated_ts.isoformat(),
    }


def _serialize_event( event ) -> dict:
    """
    Serialize a TaskEvent to the wire shape.

    Requires:
        - event is a flushed TaskEvent (id/ts populated)

    Ensures:
        - returns a JSON-safe dict mirroring the audit-trail row
    """
    return {
        "id"           : event.id,
        "item_id"      : str( event.item_id ),
        "ts"           : event.ts.isoformat(),
        "actor"        : event.actor,
        "transition"   : event.transition,
        "receipt_refs" : event.receipt_refs,
        "authority"    : event.authority,
    }


def _reject_if_errors( errors: list ) -> None:
    """
    Map a non-empty rules-violation list to HTTP 422.

    Requires:
        - errors is the list returned by a task_store_rules validator

    Ensures:
        - raises HTTPException(422, {errors: [...]}) when errors is non-empty
        - no-op when errors is empty

    Raises:
        - HTTPException 422 carrying EVERY violation (caller sees all at once)
    """
    if errors:
        raise HTTPException( status_code=422, detail={ "errors": errors } )


# ---------------------------------------------------------------------------
# Endpoints (ALL sync `def` — threadpool lane, C4 debt-clean)
# ---------------------------------------------------------------------------

@router.post(
    "/tasks",
    status_code = 201,
    summary     = "Create a task-store item",
    description = "Creates one obligation row (always status=queued) plus its "
                  "'->queued' creation event. Auth: X-API-Key or Bearer JWT. "
                  "Design §2.2 (v0.4, Rick-ruled F4: managers-first writes)."
)
def create_task(
    payload: TaskCreateIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Create a task item.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - payload validates against TaskCreateIn

    Ensures:
        - enum fields validated via rules.validate_create (422 on violation)
        - item + creation event written atomically (one get_db() transaction)
        - returns the serialized item (201)
    """
    _reject_if_errors( rules.validate_create( payload.item_class, payload.gate_class, payload.priority, payload.authority ) )

    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.create_item(
            item_class          = payload.item_class,
            title               = payload.title,
            project             = payload.project,
            created_by          = payload.created_by,
            authority           = payload.authority,
            body                = payload.body,
            owner_persona       = payload.owner_persona,
            accountable_manager = payload.accountable_manager,
            gate_class          = payload.gate_class,
            priority            = payload.priority,
            source_qid          = payload.source_qid,
            correlation_key     = payload.correlation_key,
        )
        return _serialize_item( item )


@router.post(
    "/tasks/{task_id}/transition",
    summary     = "Transition a task-store item",
    description = "Applies one state change + appends one audit event. "
                  "->done REJECTS without valid receipt_refs (T3, §4.1 AC1); "
                  "->blocked REQUIRES next_chase_ts (I3) + typed blocked_by refs; "
                  "done/dropped are terminal. Auth: X-API-Key or Bearer JWT."
)
def transition_task(
    task_id: uuid.UUID,
    payload: TaskTransitionIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Apply a state transition to an item.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - task_id is a valid UUID (FastAPI 422s malformed ids)
        - payload validates against TaskTransitionIn

    Ensures:
        - 404 when the item does not exist
        - structural rules validated against the CURRENT status inside the
          same transaction that applies the change (no read-then-write race)
        - item update + event append are atomic (one get_db() transaction)
        - returns { item, event } serialized
    """
    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )

        _reject_if_errors( rules.validate_transition(
            from_status   = item.status,
            to_status     = payload.to_status,
            authority     = payload.authority,
            receipt_refs  = payload.receipt_refs,
            next_chase_ts = payload.next_chase_ts,
            blocked_by    = payload.blocked_by,
        ) )

        event = repo.apply_transition(
            item          = item,
            to_status     = payload.to_status,
            actor         = payload.actor,
            authority     = payload.authority,
            receipt_refs  = payload.receipt_refs,
            next_chase_ts = payload.next_chase_ts,
            blocked_by    = payload.blocked_by,
        )
        return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


@router.get(
    "/tasks",
    summary     = "Query task-store items",
    description = "The deterministic owed-work query (R4): exact-match filters, "
                  "AND semantics, newest first. Junk enum filter values are "
                  "rejected (422), never silently empty. Auth: X-API-Key or Bearer JWT."
)
def query_tasks(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    owner_persona       : Optional[str] = None,
    status              : Optional[str] = None,
    gate_class          : Optional[str] = None,
    accountable_manager : Optional[str] = None,
    project             : Optional[str] = None,
    item_class          : Optional[str] = None,
    limit               : int = 100,
    offset              : int = 0,
):
    """
    Query items with exact-match filters.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - provided enum filters (status/gate_class/item_class) are members of
          their enums — a typo'd filter is a caller bug surfaced as 422, not
          an honest-looking empty result

    Ensures:
        - returns { tasks: [...], count } matching ALL provided filters
        - ordered created_ts descending, stable tiebreak on id
    """
    errors = [ ]
    if status is not None and status not in rules.VALID_STATUSES:
        errors.append( f"status filter '{status}' must be one of {rules.VALID_STATUSES}" )
    if gate_class is not None and gate_class not in rules.VALID_GATE_CLASSES:
        errors.append( f"gate_class filter '{gate_class}' must be one of {rules.VALID_GATE_CLASSES}" )
    if item_class is not None and item_class not in rules.VALID_ITEM_CLASSES:
        errors.append( f"item_class filter '{item_class}' must be one of {rules.VALID_ITEM_CLASSES}" )
    _reject_if_errors( errors )

    with get_db() as session:
        repo  = TaskRepository( session )
        items = repo.query_tasks(
            owner_persona       = owner_persona,
            status              = status,
            gate_class          = gate_class,
            accountable_manager = accountable_manager,
            project             = project,
            item_class          = item_class,
            limit               = limit,
            offset              = offset,
        )
        tasks = [ _serialize_item( item ) for item in items ]
        return { "tasks": tasks, "count": len( tasks ) }


@router.get(
    "/tasks/{task_id}",
    summary     = "Get one task-store item",
    description = "Returns one item by UUID. Auth: X-API-Key or Bearer JWT."
)
def get_task(
    task_id: uuid.UUID,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Get one item by id.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - task_id is a valid UUID

    Ensures:
        - 404 when the item does not exist
        - returns the serialized item otherwise
    """
    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )
        return _serialize_item( item )


@router.get(
    "/tasks/{task_id}/events",
    summary     = "Get a task-store item's audit trail",
    description = "Returns the append-only per-item event trail (R3): every "
                  "transition with actor, authority, and receipt refs. "
                  "Auth: X-API-Key or Bearer JWT."
)
def get_task_events(
    task_id: uuid.UUID,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Get the audit trail for one item.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - task_id is a valid UUID

    Ensures:
        - 404 when the item does not exist (a missing item has no trail —
          distinguish from an existing item with only its creation event)
        - returns { events: [...], count } ordered by event id ascending
    """
    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )
        events = [ _serialize_event( event ) for event in repo.get_events( task_id ) ]
        return { "events": events, "count": len( events ) }
