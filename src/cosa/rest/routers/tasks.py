"""
Unified task store REST surface — /api/tasks/* (Phase 1).

The deterministic owed-work API (design R4): arbiter, managers, workers, and
Rick all query the SAME store through these endpoints. Receipts are
first-class: a ->done transition without valid receipt_refs is REJECTED
(design T3 / §4.1 AC1 — the mechanical no-confabulation enforcement).

Endpoints (all authenticated via require_api_key_or_jwt — X-API-Key OR Bearer
JWT, §4.1 AC2; hook writers use the host API-key file, same lane as the
Arbiter + Stop-hook liveness path):
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

from datetime import datetime, timezone
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest import task_store_rules as rules
from cosa.agents.utils.sender_id import canonicalize_project_name
from lupin_mcp.persona_normalization import canonical_persona_key

router = APIRouter( prefix="/api", tags=[ "tasks" ] )


def _canon_persona( value ):
    """
    Canonicalize an OPTIONAL persona-identity string to the store key.

    The single API-boundary choke point that guarantees the store invariant —
    every `owner_persona` / `accountable_manager` value the store holds (and
    every value any caller queries it by) is the SAME canonical key, so a
    persona whose name carries an accent/punctuation ("María", "Mr. Radio") can
    never split into mismatched "maría"/"maria"/"mr. radio"/"mr radio" rows
    (the 2026-06-18 false-idle bug-class).

    Requires:
        - value is a str or None

    Ensures:
        - None / "" / whitespace-only / all-punctuation -> None (a falsy filter
          stays falsy: an absent owner filter must keep matching every row, and
          a blank create field stays blank rather than becoming "")
        - otherwise returns canonical_persona_key( value ) (store-key parity)
    """
    if value is None:
        return None
    return canonical_persona_key( value ) or None


def _canon_project( value ):
    """
    Canonicalize a project name to the store's single alias form — the
    project-axis twin of `_canon_persona` (bug de653086 / its sibling c6751cf8).

    The owed-work oracle scopes by `resolve_project_name()`, which alias-
    normalizes through the ONE `_PROJECT_ALIASES` table (e.g.
    "planning-is-prompting" -> "plan"). A row written under the RAW repo name
    therefore splits OUT of the oracle's `project=` filter, and the owning
    session false-idles while genuinely owing work (the alias-axis sibling of
    the 2026-06-18 persona-drift P0). The MCP client wrappers already alias on
    write, but a NON-wrapper POST (or a future caller) would store raw — so this
    is the SERVER-side choke point, symmetric with persona canonicalization,
    that makes read and write agree on ONE canonical form regardless of which
    client wrote the row. Reuses the single shared `canonicalize_project_name`
    (no second alias map) and is idempotent on already-canonical names.

    Requires:
        - value is a str or None

    Ensures:
        - None -> None (an absent project filter must keep matching every row)
        - a known alias key -> its canonical short name
          ("planning-is-prompting" -> "plan")
        - any other name -> returned unchanged (already-canonical / non-aliased)
    """
    return canonicalize_project_name( value )


def _canon_blocked_by( blocked_by ):
    """
    Canonicalize persona-typed refs inside a blocked_by list (identity parity).

    A typed ref is { "kind": item|persona|user, "id": ... }. Only kind=="persona"
    ids name a persona, so only those are routed through canonical_persona_key;
    item/user refs (and any malformed/non-dict entry) pass through untouched so
    this helper never changes what task_store_rules.validate_blocked_by_refs
    sees structurally — it only normalizes the persona id's spelling.

    Requires:
        - blocked_by is the candidate value (any type; only a list of dict refs
          is transformed)

    Ensures:
        - non-list / None -> returned unchanged (validation still rejects it)
        - each persona-kind ref's id -> canonical_persona_key( id ) when the id
          canonicalizes to a non-empty key; left verbatim otherwise (so an
          un-canonicalizable id still hits the rules' non-empty-string check)
        - item / user / malformed refs unchanged
    """
    if not isinstance( blocked_by, list ):
        return blocked_by
    out = [ ]
    for ref in blocked_by:
        if isinstance( ref, dict ) and ref.get( "kind" ) == "persona" and isinstance( ref.get( "id" ), str ):
            canon = canonical_persona_key( ref[ "id" ] )
            out.append( { **ref, "id": canon } if canon else ref )
        else:
            out.append( ref )
    return out


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
    project             : str            = Field( ..., min_length=1, max_length=255 )
    created_by          : str            = Field( ..., min_length=1, max_length=255, description="persona + session id of the creator" )
    authority           : str            = Field( default="standing" )
    body                : Optional[str]  = None
    owner_persona       : Optional[str]  = Field( default=None, max_length=255 )
    accountable_manager : Optional[str]  = Field( default=None, max_length=255 )
    gate_class          : str            = Field( default="none" )
    priority            : str            = Field( default="P2" )
    urgency             : str            = Field( default="normal" )
    source_qid          : Optional[str]  = Field( default=None, max_length=64 )
    correlation_key     : Optional[str]  = Field( default=None, max_length=255 )
    # max_length values mirror the VARCHAR widths in postgres_models.TaskItem
    # (cold-review N5): overlong input is a 422 at the wire, never a DB
    # DataError surfacing as an authenticated 500.


class TaskTransitionIn( BaseModel ):
    """
    Transition body for POST /api/tasks/{id}/transition.

    Structural rules (terminal states, receipts on ->done, next_chase_ts +
    typed blocked_by on ->blocked, non-blank reason on ->dropped) are
    validated by task_store_rules.validate_transition in the handler.
    """
    to_status     : str                 = Field( ..., min_length=1 )
    actor         : str                 = Field( ..., min_length=1, max_length=255, description="persona + session id performing the transition" )
    authority     : str                 = Field( default="standing" )
    receipt_refs  : Optional[dict]      = None
    next_chase_ts : Optional[datetime]  = None
    blocked_by    : Optional[list]      = None
    reason        : Optional[str]       = Field( default=None, max_length=4000, description="free-text justification; REQUIRED non-blank for ->dropped (C12)" )


class TaskCorrelateIn( BaseModel ):
    """
    Body for POST /api/tasks/{id}/correlate (Phase 2 — cross-session respawn
    adoption: re-stamp an item's correlation_key onto a successor session's
    harness task id instead of forking a duplicate item).

    Terminal items are rejected in the handler (no re-keying closed history);
    authority enum membership is validated there too (one rules home).
    """
    correlation_key : str = Field( ..., min_length=1, max_length=255 )
    actor           : str = Field( ..., min_length=1, max_length=255, description="persona + session id performing the re-correlation" )
    authority       : str = Field( default="standing" )


class TaskAmendIn( BaseModel ):
    """
    Body for POST /api/tasks/{id}/amend (Phase 2.2 — append-only body amendment).

    Appends a persona-stamped + UTC-timestamped block to a NON-terminal item's
    body WITHOUT rewriting the existing text — the durable-record seam for a
    live item whose scope is legitimately reframed mid-flight (Krishna's
    2026-07-02 friction). Distinct from PATCH `body`, which OVERWRITES: an amend
    can NEVER lose prior spec history. `note` is the text appended; `reason`
    stamps the audit event (mirrors the PATCH reason discipline), falling back to
    an auto-marker when absent. `actor`/`authority` stamp the event, not the item.
    """
    note      : str           = Field( ..., min_length=1, max_length=4000, description="the amendment text appended to the item body (original preserved verbatim)" )
    actor     : str           = Field( ..., min_length=1, max_length=255, description="persona + session id performing the amendment" )
    authority : str           = Field( default="standing" )
    reason    : Optional[str] = Field( default=None, max_length=4000, description="free-text justification stamping the 'amended' audit event; falls back to an auto-marker when absent" )


class TaskPatchIn( BaseModel ):
    """
    Body for PATCH /api/tasks/{id} (Phase 2.1 — item-field edit).

    Edits the mutable presentation/ownership fields of a NON-terminal item.
    `status` / `blocked_by` / `next_chase_ts` / `receipt_refs` /
    `correlation_key` are DELIBERATELY ABSENT — they ride the transition oracle
    (validate_transition) and the /correlate seam, NEVER an item-PATCH.
    `extra='forbid'` makes that a HARD wire-level invariant: naming any of them
    is a 422, not a silent drop (reviewer ruling 2026-06-15 — PATCH can never
    bypass the oracle). `actor`/`authority`/`reason` stamp the audit event, not
    the item — `reason` is NOT an editable field (the manager-supplied "why" for
    a reassignment); when absent the event records the auto-generated field delta.
    """
    model_config = ConfigDict( extra="forbid" )

    title               : Optional[str] = Field( default=None, min_length=1 )
    body                : Optional[str] = Field( default=None )
    priority            : Optional[str] = Field( default=None )
    owner_persona       : Optional[str] = Field( default=None, max_length=255 )
    accountable_manager : Optional[str] = Field( default=None, max_length=255 )
    gate_class          : Optional[str] = Field( default=None )
    urgency             : Optional[str] = Field( default=None )
    actor               : str           = Field( ..., min_length=1, max_length=255, description="persona + session id performing the edit" )
    authority           : str           = Field( default="standing" )
    reason              : Optional[str] = Field( default=None, max_length=4000, description="free-text justification for the edit (e.g. why a task was reassigned); stamps the 'patched' audit event, falling back to the field delta when absent" )


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
        "urgency"             : item.urgency,
        "source_qid"          : item.source_qid,
        "correlation_key"     : item.correlation_key,
        "created_ts"          : item.created_ts.isoformat(),
        "updated_ts"          : item.updated_ts.isoformat(),
    }


def _serialize_item_terse( item ) -> dict:
    """
    Serialize a TaskItem to the TERSE projection (§G token win).

    The on-demand "see my list" query (a manager board glance, a worker's
    owed-work peek) needs the at-a-glance fields, NOT the full row — `body` in
    particular can be multi-paragraph, and the audit trail (/events) is already
    a separate surface. This projection drops `body` and every non-glance field,
    keeping ONLY id / title / status / blocked_by / next_chase_ts / priority —
    so a list query over MCP costs a fraction of the full-row token weight
    (cosa-voice token-efficiency is goal #1). Field names are IDENTICAL to the
    full shape (one name at every layer) — a terse row is a strict subset.

    Requires:
        - item is a flushed TaskItem (id populated)

    Ensures:
        - returns a JSON-safe dict with EXACTLY the six glance keys; nullable
          next_chase_ts serializes as None
    """
    return {
        "id"            : str( item.id ),
        "title"         : item.title,
        "status"        : item.status,
        "blocked_by"    : item.blocked_by,
        "next_chase_ts" : item.next_chase_ts.isoformat() if item.next_chase_ts is not None else None,
        "priority"      : item.priority,
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
        "reason"       : event.reason,
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
        - an over-long title is SOFT-guarded (non-destructive, never rejected):
          trimmed to the cap, with the overflow moved into an empty body
          (rules.soft_guard_title, design 2026.06.29 §4.3 / handoff #1)
        - item + creation event written atomically (one get_db() transaction)
        - returns the serialized item (201) plus a `title_guard` advisory field
          (None when the title was under the cap)
    """
    _reject_if_errors( rules.validate_create( payload.item_class, payload.gate_class, payload.priority, payload.authority, payload.urgency ) )

    # Soft title guard (design 2026.06.29 §4.3 / handoff #1): trim an over-long
    # title to the shared cap and move the overflow into an empty body — at the
    # SERVER write path so EVERY caller (MCP wrapper, hook, raw POST) is covered.
    # Fail-open: the write is never rejected for title length.
    guarded_title, guarded_body, title_guard = rules.soft_guard_title( payload.title, payload.body )

    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.create_item(
            item_class          = payload.item_class,
            title               = guarded_title,
            project             = _canon_project( payload.project ),
            created_by          = payload.created_by,
            authority           = payload.authority,
            body                = guarded_body,
            owner_persona       = _canon_persona( payload.owner_persona ),
            accountable_manager = _canon_persona( payload.accountable_manager ),
            gate_class          = payload.gate_class,
            priority            = payload.priority,
            urgency             = payload.urgency,
            source_qid          = payload.source_qid,
            correlation_key     = payload.correlation_key,
        )
        result = _serialize_item( item )
        result[ "title_guard" ] = title_guard
        return result


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
        # Row-locked read (cold-review N3): serializes concurrent transitions
        # per item so validation always sees the COMMITTED from_status —
        # the terminal lockout cannot be raced.
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )

        # Identity parity (Phase 2): persona-typed blocked_by ids are stored
        # canonical so a "blocked on María/Mr. Radio" ref matches that persona's
        # owner_persona rows. Done before BOTH validate and apply so the value
        # validated is the value persisted.
        blocked_by = _canon_blocked_by( payload.blocked_by )

        _reject_if_errors( rules.validate_transition(
            from_status   = item.status,
            to_status     = payload.to_status,
            authority     = payload.authority,
            receipt_refs  = payload.receipt_refs,
            next_chase_ts = payload.next_chase_ts,
            blocked_by    = blocked_by,
            reason        = payload.reason,
        ) )

        event = repo.apply_transition(
            item          = item,
            to_status     = payload.to_status,
            actor         = payload.actor,
            authority     = payload.authority,
            receipt_refs  = payload.receipt_refs,
            next_chase_ts = payload.next_chase_ts,
            blocked_by    = blocked_by,
            reason        = payload.reason,
        )
        return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


@router.post(
    "/tasks/{task_id}/correlate",
    summary     = "Re-stamp a task-store item's correlation key",
    description = "Phase-2 cross-session respawn adoption: a successor session "
                  "re-registers its harness task id onto an inherited item "
                  "instead of forking a duplicate. Appends an audited "
                  "'re-correlated' event (R3). Terminal items are rejected. "
                  "Auth: X-API-Key or Bearer JWT."
)
def correlate_task(
    task_id: uuid.UUID,
    payload: TaskCorrelateIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Re-stamp an item's correlation_key (audited).

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - task_id is a valid UUID (FastAPI 422s malformed ids)
        - payload validates against TaskCorrelateIn

    Ensures:
        - 404 when the item does not exist
        - 422 when the item is terminal (no re-keying closed history) or
          authority is not a valid enum member
        - row-locked read (N3 parity) so the terminal check cannot be raced
          by a concurrent ->done/->dropped transition
        - correlation_key update + 're-correlated' event append are atomic
          (one get_db() transaction)
        - returns { item, event } serialized
    """
    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )

        errors = [ ]
        if payload.authority not in rules.VALID_AUTHORITIES:
            errors.append( f"authority '{payload.authority}' must be one of {rules.VALID_AUTHORITIES}" )
        if item.status in rules.TERMINAL_STATUSES:
            errors.append( f"item is terminal ('{item.status}') — correlation keys of closed history are immutable" )
        _reject_if_errors( errors )

        event = repo.apply_correlation(
            item            = item,
            correlation_key = payload.correlation_key,
            actor           = payload.actor,
            authority       = payload.authority,
        )
        return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


@router.post(
    "/tasks/{task_id}/amend",
    summary     = "Append an amendment to a task-store item's body",
    description = "Phase-2.2 append-only body amendment: appends a persona-stamped "
                  "+ UTC-timestamped block to a NON-terminal item's body WITHOUT "
                  "rewriting the existing text (distinct from PATCH body, which "
                  "overwrites) and appends an 'amended' audit event. status / the "
                  "oracle fields are never touched. Terminal items, a blank note, "
                  "and a bad authority are rejected (every violation at once). "
                  "Auth: X-API-Key or Bearer JWT."
)
def amend_task(
    task_id: uuid.UUID,
    payload: TaskAmendIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Append an amendment to an item's body (audited).

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - task_id is a valid UUID (FastAPI 422s malformed ids)
        - payload validates against TaskAmendIn (min_length=1 lets a
          whitespace-only note through the wire — the handler strip-guards it)

    Ensures:
        - 404 when the item does not exist
        - 422 when authority is not a valid enum member, the note is blank after
          strip, or the item is terminal (no amending closed history) — every
          violation reported at once
        - row-locked read (N3 parity) so the terminal check cannot be raced by a
          concurrent ->done/->dropped transition
        - the router owns the clock (datetime.now(utc)) so the repo stays
          deterministic; body append + 'amended' event are atomic (one
          get_db() transaction)
        - returns { item, event } serialized
    """
    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )

        errors = [ ]
        if payload.authority not in rules.VALID_AUTHORITIES:
            errors.append( f"authority '{payload.authority}' must be one of {rules.VALID_AUTHORITIES}" )
        if not payload.note.strip():
            errors.append( "note must be a non-blank string" )
        if item.status in rules.TERMINAL_STATUSES:
            errors.append( f"item is terminal ('{item.status}') — no amendments to closed history" )
        _reject_if_errors( errors )

        event = repo.apply_amendment(
            item      = item,
            note      = payload.note,
            actor     = payload.actor,
            authority = payload.authority,
            now       = datetime.now( timezone.utc ),
            reason    = payload.reason,
        )
        return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


@router.patch(
    "/tasks/{task_id}",
    summary     = "Edit a task-store item's mutable fields",
    description = "Phase-2.1 item edit: PATCH whitelisted fields (title/body/"
                  "priority/owner_persona/accountable_manager/gate_class) on a "
                  "NON-terminal item; appends a 'patched' audit event with the "
                  "field delta. status/blocked_by/next_chase_ts/receipt_refs/"
                  "correlation_key can NEVER be PATCHed (they ride the transition "
                  "oracle — naming one is a 422). Auth: X-API-Key or Bearer JWT."
)
def patch_task(
    task_id: uuid.UUID,
    payload: TaskPatchIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Edit an item's mutable fields (audited).

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - task_id is a valid UUID (FastAPI 422s malformed ids)
        - payload validates against TaskPatchIn (extra='forbid' rejects any
          non-editable field at the wire — the hard no-oracle-bypass invariant)

    Ensures:
        - 422 when no editable field is set, an enum field is invalid, or
          authority is not a valid enum member (every violation at once)
        - 404 when the item does not exist
        - 422 when the item is terminal (no edits to closed history)
        - row-locked read (N3 parity) so the terminal check cannot be raced
          by a concurrent ->done/->dropped transition
        - field update + 'patched' event append are atomic (one transaction)
        - returns { item, event } serialized
    """
    fields = payload.model_dump( exclude_unset=True, exclude={ "actor", "authority", "reason" } )

    # Identity parity (Phase 2 / reassign §4.1): a PATCH that re-owns an item must
    # store the canonical key, same as create — otherwise a re-owned item drifts
    # out of the new persona's owed-row set (the 2026-06-18 false-idle class).
    # The normalization is a dedicated, 100%-testable rules helper delegating to
    # the ONE global persona normalizer (canonical_persona_key); an explicit None
    # (clear-the-owner) is preserved rather than collapsed.
    fields = rules.normalize_patch_fields( fields )

    errors = list( rules.validate_patch( fields ) )
    if payload.authority not in rules.VALID_AUTHORITIES:
        errors.append( f"authority '{payload.authority}' must be one of {rules.VALID_AUTHORITIES}" )
    _reject_if_errors( errors )

    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )
        if item.status in rules.TERMINAL_STATUSES:
            _reject_if_errors( [ f"item is terminal ('{item.status}') — no edits to closed history" ] )

        event = repo.apply_patch( item, fields, actor=payload.actor, authority=payload.authority, reason=payload.reason )
        return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


@router.get(
    "/tasks",
    summary     = "Query task-store items",
    description = "The deterministic owed-work query (R4): exact-match filters, "
                  "AND semantics, newest first. Junk enum filter values are "
                  "rejected (422), never silently empty. count_only=true returns "
                  "{count} as a true COUNT(*) without serializing any rows (the "
                  "owed-count token win, §G). terse=true returns the at-a-glance "
                  "projection (id/title/status/blocked_by/next_chase_ts/priority "
                  "— drops body) for cheap 'see my list' queries. Auth: X-API-Key "
                  "or Bearer JWT."
)
def query_tasks(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    owner_persona       : Optional[str] = None,
    status              : Optional[str] = None,
    gate_class          : Optional[str] = None,
    urgency             : Optional[str] = None,
    accountable_manager : Optional[str] = None,
    project             : Optional[str] = None,
    item_class          : Optional[str] = None,
    correlation_key     : Optional[str] = None,
    count_only          : bool = False,
    terse               : bool = False,
    include_terminal    : bool = False,
    unscoped_audit      : bool = False,
    limit               : int = Query( default=100, ge=0, le=500 ),
    offset              : int = Query( default=0, ge=0 ),
):
    # limit/offset bounds (cold-review N4): Postgres rejects a negative LIMIT
    # with InvalidRowCountInLimitClause — unbounded params turned that into an
    # authenticated 500; le=500 also caps result-set size at the wire.
    """
    Query items with exact-match filters.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - provided enum filters (status/gate_class/item_class) are members of
          their enums — a typo'd filter is a caller bug surfaced as 422, not
          an honest-looking empty result

    Ensures:
        - count_only=False (default): returns { tasks: [...], count } matching
          ALL provided filters, ordered created_ts descending, stable tiebreak
          on id. NOTE: `count` here is the PAGE length (len(tasks)) — it
          saturates at `limit`; use count_only for a true total.
        - count_only=True (O2 / §G token win): returns { count } as a true
          SQL COUNT(*) over the SAME filters — NO rows serialized, independent
          of limit/offset (those params are ignored in this mode). The owed
          source reads this so a session with >100 owed rows is counted exactly.
          count_only takes precedence over terse (a count needs no rows at all).
        - terse=True (§G token win, count_only=False): returns { tasks: [...],
          count } where each row is the at-a-glance projection (id / title /
          status / blocked_by / next_chase_ts / priority — `body` and the other
          full-row fields dropped), so an on-demand "see my list" query over MCP
          costs a fraction of the full-row token weight.
    """
    errors = [ ]
    if status is not None and status not in rules.VALID_STATUSES:
        errors.append( f"status filter '{status}' must be one of {rules.VALID_STATUSES}" )
    if gate_class is not None and gate_class not in rules.VALID_GATE_CLASSES:
        errors.append( f"gate_class filter '{gate_class}' must be one of {rules.VALID_GATE_CLASSES}" )
    if urgency is not None and urgency not in rules.VALID_URGENCIES:
        errors.append( f"urgency filter '{urgency}' must be one of {rules.VALID_URGENCIES}" )
    if item_class is not None and item_class not in rules.VALID_ITEM_CLASSES:
        errors.append( f"item_class filter '{item_class}' must be one of {rules.VALID_ITEM_CLASSES}" )
    _reject_if_errors( errors )

    # Identity parity (Phase 2): canonicalize the persona-typed filters so the
    # READ seam queries by the SAME key the WRITE seam stored — the direct fix
    # for the 2026-06-18 false-idle (owed-oracle queried "maría"/"mr. radio",
    # store held "maria"/"mr radio", zero rows matched). A blank/absent filter
    # canonicalizes to None and keeps matching every row.
    owner_persona       = _canon_persona( owner_persona )
    accountable_manager = _canon_persona( accountable_manager )
    # Alias parity (bug de653086): canonicalize the project filter through the
    # SAME alias table the WRITE seam now uses, so a query by the raw repo name
    # ("planning-is-prompting") still matches rows stored canonically ("plan") —
    # read and write agree on one form at the server choke point.
    project             = _canon_project( project )

    with get_db() as session:
        repo = TaskRepository( session )
        if count_only:
            # True COUNT(*) — no row materialization (§G). limit/offset are
            # deliberately NOT forwarded: a count is page-independent. A count
            # returns no rows, so the unscoped-size guard does not apply here.
            count = repo.count_tasks(
                owner_persona       = owner_persona,
                status              = status,
                gate_class          = gate_class,
                urgency             = urgency,
                accountable_manager = accountable_manager,
                project             = project,
                item_class          = item_class,
                correlation_key     = correlation_key,
                include_terminal    = include_terminal,
            )
            return { "count": count }
        # The unscoped-query guard (design 2026.07.07) is a repository-layer raise;
        # map it to an educational HTTP 400 that names the two fixes (mirrors the
        # ?scope= teach-while-enforcing 400). A legitimate full sweep passes
        # unscoped_audit=true (the arbiter + the two UI board cards).
        try:
            items = repo.query_tasks(
                owner_persona       = owner_persona,
                status              = status,
                gate_class          = gate_class,
                urgency             = urgency,
                accountable_manager = accountable_manager,
                project             = project,
                item_class          = item_class,
                correlation_key     = correlation_key,
                limit               = limit,
                offset              = offset,
                include_terminal    = include_terminal,
                unscoped_audit      = unscoped_audit,
            )
        except rules.UnscopedQueryError as e:
            raise HTTPException(
                status_code = 400,
                detail      = (
                    f"unscoped task_query would return {e.count} non-terminal rows "
                    f"(> {e.threshold}). Narrow it with a filter (owner_persona / "
                    f"status / item_class / project / gate_class / accountable_manager "
                    f"/ correlation_key), or pass unscoped_audit=true for a deliberate "
                    f"full-store audit."
                ),
            )
        # terse → the at-a-glance projection (§G); else the full wire shape.
        serialize = _serialize_item_terse if terse else _serialize_item
        tasks = [ serialize( item ) for item in items ]
        # Warn-not-fail (María #3): a heavy NON-terse pull earns an OBSERVABLE log
        # line nudging toward terse=True — never a rejection, rows still returned.
        if not terse and len( tasks ) > rules.NONTERSE_WARN_THRESHOLD:
            print(
                f"[task_query WARN] non-terse pull returned {len( tasks )} full rows "
                f"(> {rules.NONTERSE_WARN_THRESHOLD}) — pass terse=true for the "
                f"at-a-glance projection to cut token weight"
            )
        return { "tasks": tasks, "count": len( tasks ) }


@router.get(
    "/tasks/events",
    summary     = "Query the cross-item event stream",
    description = "Fleet-wide audit (design backlog): the append-only event "
                  "trail across ALL items, filtered by actor / transition / "
                  "project / time range (since/until on event ts), newest "
                  "first. Distinct from /tasks/{id}/events (one item). Declared "
                  "BEFORE /tasks/{task_id} so the static path wins over the "
                  "UUID path converter. Auth: X-API-Key or Bearer JWT."
)
def query_event_stream(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    actor      : Optional[str]      = None,
    transition : Optional[str]      = None,
    project    : Optional[str]      = None,
    since      : Optional[datetime] = None,
    until      : Optional[datetime] = None,
    limit      : int = Query( default=100, ge=0, le=500 ),
    offset     : int = Query( default=0, ge=0 ),
):
    # limit/offset bounds (cold-review N4 parity): an unbounded negative LIMIT
    # is an authenticated 500 on Postgres — bound at the wire, cap result size.
    """
    Query the cross-item audit trail with exact-match + time-range filters.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - since/until are ISO-8601 datetimes (FastAPI parses them; a malformed
          value is a 422 request-validation error, surfaced by the framework)

    Ensures:
        - returns { events: [...], count } matching ALL provided filters
        - ordered ts descending, stable tiebreak on id descending (newest first)
    """
    with get_db() as session:
        repo   = TaskRepository( session )
        events = repo.query_events(
            actor      = actor,
            transition = transition,
            project    = project,
            since      = since,
            until      = until,
            limit      = limit,
            offset     = offset,
        )
        rows = [ _serialize_event( event ) for event in events ]
        return { "events": rows, "count": len( rows ) }


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
