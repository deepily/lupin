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
planning-is-prompting/src/rnd/2026.06.11-unified-task-store-design.md (v0.4, Rick-ruled §3.1).
"""

from datetime import datetime, timezone, timedelta
from typing import Annotated, Dict, Optional
import json
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email
from cosa.rest.task_actor_identity import identity_for_account, recorded_actor
from cosa.rest import task_priority_firewall as priority_firewall
from cosa.rest.auth_middleware import require_admin
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest import task_store_rules as rules
from cosa.rest import flow_ratio_settings as frs
from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest import task_promotion_resolver as promotion_resolver
from cosa.rest.postgres_models import TaskItem, TaskPromotionTicket
from cosa.rest import task_request_lifecycle as request_lifecycle
from cosa.rest.task_store_owed import blocker_is_terminal, item_blocker_ids, park_reason_is_stale
from cosa.agents.utils.sender_id import canonicalize_project_name
import cosa.utils.util as cu
from lupin_mcp.persona_normalization import canonical_persona_key
# Manager-only blocked-mint guard (Rick 2026-07-20). REUSE the ONE canonical
# manager-figure predicate — never a second copy of the role logic (G1). In the
# server CONTAINER only its EXPLICIT source (bridge role=="manager") resolves: the
# IMPLICIT source (the COSA_VOICE_PREFERRED_PERSONA__<PROJECT> env chain) is UNSET
# in-container, so a session that is a manager ONLY by named-standing-persona is
# treated here as a non-manager. Acceptable — the crew/fleet Managers who mint
# blocked rows are spawned INTO role=manager (the explicit source). The bridge dir
# is bind-mounted into the container (docker-compose ~/.claude/sessions), so the
# explicit lookup is reachable server-side.
from lupin_cli.claude_code.hooks.lib.manager_figure import (
    is_manager_figure, classify_manager_figure_denial,
    DENIAL_STALE_BRIDGE, DENIAL_NO_SESSION_ID,
)
# The persona a manager seat's bridge carries, for the identity a manager attestation
# records (row adaf7698). Same bridge the manager check above reads.
from lupin_cli.claude_code.hooks.lib.session_bridge import get_voice_persona

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

    Creation DEFAULTS to status=queued (the creation event stamps "->queued");
    enum membership for item_class/gate_class/priority/authority is validated
    by task_store_rules.validate_create in the handler (one rules home, not
    per-layer duplication).

    ONE-CALL BLOCKED MINT (Rick's ruling 2026-07-20): `status` may also be
    "blocked", minting an already-blocked row in a single call. A blocked mint
    carries `blocked_by` (>=1 typed ref) and `next_chase_ts` (kind-aware — a
    persona blocker requires it), enforced by rules.validate_create_status which
    REUSES the same ->blocked invariant a transition applies. A blocked mint is
    additionally MANAGER-ONLY (guarded in the handler via is_manager_figure).
    `status` is otherwise whitelisted to queued|blocked — done/dropped/parked/
    claimed/in_progress/review are NOT mintable.
    """
    # `extra='forbid'` — row 98854a4b. This model shipped on pydantic's DEFAULT
    # (IGNORE), so an undeclared field vanished on a 201: measured live, a POST
    # carrying `park_reason` + `nonsense` returned 201 with both gone and no
    # warning. That is 9bb4debe's shape one level up — the caller who cared
    # enough to send a field is the one least likely to re-read the response for
    # it. SWEPT BEFORE FLIPPING: every in-repo write caller (6 MCP verbs, the
    # hook-lane mirror + drain, the multiplexer's patch/transition) sends ONLY
    # declared keys, so this turns no silence into an outage.
    model_config = ConfigDict( extra="forbid" )

    item_class          : str                = Field( ..., min_length=1 )
    title               : str                = Field( ..., min_length=1 )
    project             : str                = Field( ..., min_length=1, max_length=255 )
    created_by          : str                = Field( ..., min_length=1, max_length=255, description="persona + session id of the creator" )
    authority           : str                = Field( default="standing" )
    body                : Optional[str]      = None
    owner_persona       : Optional[str]      = Field( default=None, max_length=255 )
    accountable_manager : Optional[str]      = Field( default=None, max_length=255 )
    gate_class          : str                = Field( default="none" )
    priority            : str                = Field( default="P5" )   # P5 default per Rick's broadcast e254ec7d, 2026-09-07: "The default Priority from here on now will be P5."
    urgency             : str                = Field( default="normal" )
    status              : str                = Field( default="queued", description="mint status — queued (default) or blocked (manager-only, one-call blocked mint)" )
    blocked_by          : Optional[list]     = Field( default=None, description="typed refs [{kind, id}] — REQUIRED (>=1) for a blocked mint; ignored for queued" )
    next_chase_ts       : Optional[datetime] = Field( default=None, description="ISO-8601 chase time — REQUIRED for a blocked mint whose blocked_by names a {kind:persona} ref (I3)" )
    source_qid          : Optional[str]      = Field( default=None, max_length=64 )
    correlation_key     : Optional[str]      = Field( default=None, max_length=255 )
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
    # `extra='forbid'` — row 98854a4b, same rationale + same caller sweep as
    # TaskCreateIn above: the store already treated this as a HARD wire-level
    # invariant on TaskPatchIn, and applied it to ONE write surface in five.
    model_config = ConfigDict( extra="forbid" )

    to_status     : str                 = Field( ..., min_length=1 )
    actor         : str                 = Field( ..., min_length=1, max_length=255, description="persona + session id performing the transition" )
    authority     : str                 = Field( default="standing" )
    receipt_refs  : Optional[dict]      = None
    next_chase_ts : Optional[datetime]  = None
    blocked_by    : Optional[list]      = None
    reason        : Optional[str]       = Field( default=None, max_length=4000, description="free-text justification; REQUIRED non-blank for ->dropped (C12)" )
    park_reason   : Optional[str]       = Field( default=None, max_length=4000, description="REQUIRED non-blank for ->parked; MUST quote the row's OWN decisive sentence, not a paraphrase" )

    # 🔴 `StrictBool`, NOT `bool`, AND THE DIFFERENCE IS THE WHOLE SAFETY OF THE OPT-IN
    # (row 3493ae9b, design §5.5.2 — Tiffany 💍's finding in review).
    #
    # This field is what asks for the ASYNCHRONOUS promotion path: a `202` carrying a
    # ticket instead of a request held open while Rick thinks. It must never arrive by
    # accident, because a 202 is a FALSE GREEN in every browser client — `fetch`'s
    # `response.ok` is `status >= 200 && < 300`, so `TaskListStore` would leave its
    # optimistic "approved" row state in place for a promotion Rick has not been asked
    # about yet.
    #
    # ⚠️ THE ARGUMENT THAT THIS COULD NOT HAPPEN WAS WRONG, WHICH IS WHY THE TYPE IS
    # STRICT. It ran: the browser stores spread `...extras` into the body, `extras` is
    # typed `Record<string, string>`, and a boolean cannot go into one. TRUE ABOUT THE
    # TYPE AND IRRELEVANT — that map carries the STRING "true" perfectly well. Measured
    # on pydantic 2.13.3, one variable:
    #
    #     value      Optional[bool]        Optional[StrictBool]
    #     'true'     ACCEPTED -> True      REJECTED (422)
    #     'True'     ACCEPTED -> True      REJECTED (422)
    #     '1' / 1    ACCEPTED -> True      REJECTED (422)
    #     'yes'      ACCEPTED -> True      REJECTED (422)
    #
    # A plain `bool` COERCES all five. So a browser sending `extras = { asynchronous:
    # "true" }` would have opted itself in silently.
    #
    # ⚠️ AND THE GUARANTEE HAD TO CHANGE LAYERS, not just tighten. The original defence
    # lived in the CLIENT'S type system — and `notifications.js` is vanilla JS with no
    # type system at all, so it covered one of the two client layers and left the other
    # bare. This field is the server-side check, and it covers both identically. A
    # guarantee belongs where every caller must pass.
    #
    # `extra="forbid"` above means that until this field existed, an `asynchronous` key
    # was a 422 for everybody. That protection ends the moment the field is declared,
    # which is exactly why `StrictBool` lands in the same edit rather than after it.
    asynchronous  : Optional[StrictBool] = Field( default=None, description="opt in to the asynchronous promotion path (202 + ticket). Boolean ONLY — a string is refused. Ignored unless the operator flag 'task approval promotion ask asynchronous' is on." )


class TaskCorrelateIn( BaseModel ):
    """
    Body for POST /api/tasks/{id}/correlate (Phase 2 — cross-session respawn
    adoption: re-stamp an item's correlation_key onto a successor session's
    harness task id instead of forking a duplicate item).

    Terminal items are rejected in the handler (no re-keying closed history);
    authority enum membership is validated there too (one rules home).
    """
    # `extra='forbid'` — row 98854a4b, same rationale + same caller sweep as
    # TaskCreateIn above: the store already treated this as a HARD wire-level
    # invariant on TaskPatchIn, and applied it to ONE write surface in five.
    model_config = ConfigDict( extra="forbid" )

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
    # `extra='forbid'` — row 98854a4b, same rationale + same caller sweep as
    # TaskCreateIn above: the store already treated this as a HARD wire-level
    # invariant on TaskPatchIn, and applied it to ONE write surface in five.
    model_config = ConfigDict( extra="forbid" )

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

def _serialize_item( item, blocker_statuses=None ) -> dict:
    """
    Serialize a TaskItem to the wire shape (field names identical to the
    model — one name at every layer).

    Requires:
        - item is a flushed TaskItem (id/created_ts/updated_ts populated)
        - blocker_statuses maps blocker-id -> status (or None for looked-up-and-absent);
          omitted/None means NO blocker was resolved, and every row then reports
          blocker_terminal False — a caller that did not look cannot make a finding

    Ensures:
        - returns a JSON-safe dict; nullable timestamps serialize as None
        - `park_reason_stale` is DERIVED, never stored: the frozen-quote
          divergence flag (design §3.3). ADVISORY ONLY — it changes no
          owed-ness, unparks nothing, blocks nothing; it marks the quote
          untrustworthy and stops there.
          ⚠️ TRUE means "the body changed since capture"; FALSE means "it did
          not" — NEVER "the reason is still true" (row aa543525 §2). A park
          reason whose basis lived OUTSIDE the row dies without touching the
          row and so reads FRESH forever; four such rows were measured
          2026-07-25, each quoting a stand-down that had already evaporated.
          The chase is the backstop for that class, not this flag.
        - `blocker_terminal` is DERIVED, never stored (row 00a6bde2): the row is
          `blocked` on an item that can never transition again, so the wait is
          unsatisfiable. ADVISORY, exactly like park_reason_stale — the DISPOSITION
          of a stranded row is split (a `done` blocker means the precondition
          happened; a `dropped` one means somebody decided otherwise) and neither
          arm is a serializer's business.
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
        "park_reason"         : item.park_reason,
        "park_reason_captured_at" : item.park_reason_captured_at.isoformat() if item.park_reason_captured_at is not None else None,
        # THIRD ARG IS body_changed_ts, NOT updated_ts (bug 54924128). Both call
        # sites — here and the terse projection — must pass the same column, or the
        # flag means different things depending on how the caller queried.
        "park_reason_stale"   : park_reason_is_stale( item.status, item.park_reason_captured_at, item.body_changed_ts ),
        "blocker_terminal"    : blocker_is_terminal( item.status, item.blocked_by, blocker_statuses or { } ),
        "gate_class"          : item.gate_class,
        "priority"            : item.priority,
        "urgency"             : item.urgency,
        "source_qid"          : item.source_qid,
        "correlation_key"     : item.correlation_key,
        # The manager's promote/demote request, riding on the ticket by ruling (row
        # c9fafb9d). All three or none — three CHECKs enforce that below Pydantic.
        # NULL request_state means NO REQUEST, which is where almost every row stays.
        #
        # ⚠️ FULL SHAPE ONLY, DELIBERATELY. The terse projection's key set is asserted
        # as TERSE_DATA_FIELDS | TERSE_ADVISORY_FIELDS, so a key cannot join it without
        # being classified — and nobody has ruled whether a board glance should carry a
        # request. Adding it there is a decision, not a completion.
        "request_state"       : item.request_state,
        "request_move"        : item.request_move,
        "request_ts"          : item.request_ts.isoformat() if item.request_ts is not None else None,
        "created_ts"          : item.created_ts.isoformat(),
        "updated_ts"          : item.updated_ts.isoformat(),
    }


# The terse projection's two halves, declared rather than remembered (row 9dbffefb,
# 2026-08-31). A DATA field is carried off the row; an ADVISORY field is DERIVED by a
# predicate at serialize time. The split exists because the two fail differently: a
# data field that goes wrong is visibly wrong, while an advisory field wired to a
# constant looks exactly like a correct one that happens to be False.
#
# Measured on `title_trimmed` (row f3230576): replacing its predicate call with a bare
# `False` left all 471 tests green. Its key was asserted; its value was read by nothing.
# `park_reason_stale` arrived the same way and, until this row, had no True arm anywhere
# on the terse path either.
#
# The test side builds its exact-set key assertion as TERSE_DATA_FIELDS |
# TERSE_ADVISORY_FIELDS, so a new key cannot join the projection without being
# classified into one of them, and classifying it advisory demands a two-value recipe
# on the spot. See test_tasks_router.py :: the advisory-field registry.
#
# ⚠️ THE RESIDUAL, NAMED: a genuinely derived field declared as DATA still slips
# through. A declaration-based guard cannot close that — what it buys is that the
# mistake is a visible act in the diff rather than an omission nobody had to make.
TERSE_DATA_FIELDS = frozenset( {
    "id", "title", "status", "blocked_by", "next_chase_ts", "priority", "project",
    "created_by",
    # Row c9fafb9d: a manager's `task_query( terse=True )` shows a pending promote/demote
    # request without a `task_get` per row. Carried straight off the columns.
    "request_state", "request_move",
} )

TERSE_ADVISORY_FIELDS = frozenset( {
    "park_reason_stale", "blocker_terminal", "title_trimmed",
} )


def _serialize_item_terse( item, blocker_statuses=None ) -> dict:
    """
    Serialize a TaskItem to the TERSE projection (§G token win).

    The on-demand "see my list" query (a manager board glance, a worker's
    owed-work peek) needs the at-a-glance fields, NOT the full row — `body` in
    particular can be multi-paragraph, and the audit trail (/events) is already
    a separate surface. This projection drops `body` and every non-glance field,
    keeping ONLY id / title / status / blocked_by / next_chase_ts / priority /
    park_reason_stale — so a list query over MCP costs a fraction of the
    full-row token weight (cosa-voice token-efficiency is goal #1). Field names
    are IDENTICAL to the full shape (one name at every layer) — a terse row is a
    strict subset.

    `park_reason_stale` is here DELIBERATELY, against the projection's own
    minimalism: the terse shape is what a board glance actually reads, so a
    staleness flag omitted from it is a flag nobody sees — which is design
    option 3 (document the defect, detect nothing) wearing option 1's clothes
    (§3.3). It costs one boolean per row. A row that was never parked reports
    False, so the flag is silent on the overwhelming majority of rows.

    `project` rides here for a different reason, and it is a cost argument (row d23147e8,
    2026-07-25). It was ABSENT from terse, and there is no distinct-project-values endpoint — so
    answering "what project strings actually exist in this store?" required pulling 1,227 FULL
    rows. María ran exactly that census once: 9 distinct values, ONE of them an orphan alias
    (`google-skills-distillation` vs `skills-distillation`) that had hidden a live row from a
    project-scoped partition BY CONSTRUCTION. A census that expensive is never routine, which is
    precisely why the NEXT orphan also gets found by accident. `project` is a short string; adding
    it makes the check habitual instead of heroic.

    `title_trimmed` rides here on the SAME argument again, and it is the fourth
    application of it rather than a new policy (row a6cb24e8, 2026-08-31). The store
    trims a title at 60 chars and files the tail into `body` — and THIS projection
    drops `body`. So on the one surface where a reader meets a title alone, the
    recovered tail is invisible, and the trim leaves no ellipsis or any other mark:
    a truncated title simply stops, indistinguishable from a short one. Rio ⚡
    measured a live P1 whose 60-char title asserts a diagnosis the row's own
    amendment retracts — a board glance returns a claim the row disproves.

    ⚠️ IT OVER-REPORTS BY CONSTRUCTION, and that is the deliberate direction. The
    predicate is length-only, so a title that is NATURALLY exactly 60 chars reports
    True. A false positive costs a reader one look at a body with nothing missing;
    a false negative is the defect this exists to surface. Erring the other way
    would need a stored flag and a migration — worth doing, and not this change.

    `blocker_terminal` rides here on the SAME argument, and the argument is stronger:
    blocked rows are EXCLUDED from the workable-now count by design, so a stranded row
    is invisible in exactly the way a finished row is — it costs nothing to look at and
    yields nothing when looked at. The board's burn-down silently includes work that can
    never move. A flag that is not in the projection a board glance reads is a flag
    nobody sees. It costs one boolean per row, and every non-blocked row reports False.

    Requires:
        - item is a flushed TaskItem (id populated)
        - blocker_statuses as per _serialize_item; omitted means no finding is possible

    Ensures:
        - returns a JSON-safe dict with EXACTLY the keys in the literal below; nullable
          next_chase_ts serializes as None
        - park_reason_stale is DERIVED (never stored) and ADVISORY — identical
          semantics to the full shape's, computed by the same predicate, so the
          two projections can never disagree about staleness
        - blocker_terminal is likewise DERIVED and ADVISORY, computed by the same
          predicate as the full shape's, for the same reason
        - title_trimmed is STORED and ADVISORY: it is what soft_guard_title
          actually did to this row's title on its last write, read straight off the
          column. It is NOT re-derived from length, so it does not move when the
          cap moves (bug 769b3574) and it clears when a retitle repairs a title.
          Backfilled rows may over-report — see migration 47513717b7e5 — which is
          the harmless direction: one wasted look at a body with nothing missing
    """
    return {
        "id"                : str( item.id ),
        "title"             : item.title,
        "status"            : item.status,
        "blocked_by"        : item.blocked_by,
        "next_chase_ts"     : item.next_chase_ts.isoformat() if item.next_chase_ts is not None else None,
        "priority"          : item.priority,
        "project"           : item.project,
        # STORED DATA, not advisory. Rick asked by voice 2026-09-02 for the FILER's
        # name on every board row, and specifically on the ones he was blocking, so
        # he could follow up with a person rather than a row id. It was already on
        # every row — populated on 13 of 13 live rows at the time — and invisible
        # for exactly one reason: it was not in THIS projection, which is what the
        # board reads. Rendering alone would have produced blanks.
        #
        # ⚠️ FILER IS NOT OWNER. They differ on 3 of 13 live rows (María's census,
        # planning-is-prompting cdae439), so a UI that merges them into one "who"
        # column reports the wrong person on a quarter of the board.
        "created_by"        : item.created_by,
        # body_changed_ts, matching _serialize_item — see the note there (54924128).
        "park_reason_stale" : park_reason_is_stale( item.status, item.park_reason_captured_at, item.body_changed_ts ),
        "blocker_terminal"  : blocker_is_terminal( item.status, item.blocked_by, blocker_statuses or { } ),
        # STORED, not re-derived (bug 769b3574). This used to be
        # `rules.title_may_be_trimmed( item.title )`, which is len(title)==cap
        # against the CURRENT cap — so raising the cap to 120 would have flipped
        # 1,606 rows to False, 951 of them provably trimmed. The flag is now a
        # record of what the write did and is immune to the cap moving.
        "title_trimmed"     : item.title_trimmed,
        # A pending promote/demote request (row c9fafb9d), so a manager's terse board glance
        # shows what is waiting on Rick without a task_get per row. None on almost every row.
        "request_state"     : item.request_state,
        "request_move"      : item.request_move,
    }


def _reject_unsatisfiable_blockers( repo, blocked_by ):
    """
    422 a `blocked_by` naming an item that can NEVER satisfy the wait (row 00a6bde2).

    THE CHEAP HALF OF THE FIX, at the seam where the mistake is made. Two ways an
    item-kind edge is born dead:

        TERMINAL  — the blocker is already `done`/`dropped`. Terminal is terminal: it
                    can never transition again, so nothing will ever release this row.
        ABSENT    — the id resolves to no row at all. Nothing can transition it either,
                    and unlike the prose arm of this defect there is no ambiguity about
                    what an unresolvable id in a TYPED `{kind:"item"}` field is.

    ⚠️ THIS REACHES NONE OF THE SIX LIVE INSTANCES, and saying so is the point. All six
    blockers went terminal LONG AFTER their edge was written — write-side validation is
    structurally incapable of catching that, which is why the READ-side `blocker_terminal`
    flag is the load-bearing half and this is the convenience. A fix that shipped only
    this half would close the door on new instances while every existing one stayed
    invisible, and would look complete.

    PERSONA AND USER REFS ARE UNTOUCHED. Neither has a resolvable lifecycle — persona
    liveness has no registry at all (rows 6f8fd858 / 91067e47) and `commons_who` reports
    silence, not absence. Rejecting on an unresolvable persona would block legitimate
    writes on the strength of an instrument that does not exist.

    Requires:
        - repo is a TaskRepository bound to the live session
        - blocked_by is the caller's post-canonicalization value (any type)

    Ensures:
        - raises HTTPException(422) naming EVERY offending id and its reason, never
          just the first — a caller fixing one edge should not have to submit again to
          discover the next
        - returns None when every item-kind ref resolves to a non-terminal row
        - a value carrying no item-kind refs issues NO query and always passes
    """
    ref_ids = item_blocker_ids( blocked_by )
    if not ref_ids: return

    statuses = repo.statuses_for_ids( ref_ids )
    offences = [ ]
    for ref_id in ref_ids:
        ref_status = statuses.get( ref_id )
        if ref_status is None:
            offences.append( f"{ref_id} (no such item)" )
        elif ref_status in rules.TERMINAL_STATUSES:
            offences.append( f"{ref_id} (already {ref_status})" )

    if offences:
        raise HTTPException(
            status_code = 422,
            detail      = (
                f"blocked_by names {len( offences )} item(s) that can never satisfy the "
                f"wait: {', '.join( offences )}. A terminal item cannot transition again, "
                f"and an absent one cannot transition at all — a row blocked on either "
                f"reads 'waiting' forever. Point the edge at a live row, or mint the "
                f"precondition as its own item first."
            ),
        )


def _resolve_blocker_statuses( repo, items ):
    """
    Resolve every item-kind blocker across a PAGE of rows in one query (row 00a6bde2).

    ONE QUERY FOR THE PAGE. The alternative — resolving per row inside the serializer —
    puts an N+1 on the board glance that the terse projection exists to make cheap.
    Collected here, asked once, handed to the serializers as a plain dict.

    SCOPED TO WHAT WAS ASKED, and that scoping is load-bearing rather than an
    optimization: `statuses_for_ids` answers with an explicit None for an id it looked
    up and did not find, and `blocker_is_terminal` reads a MISSING key as "no evidence".
    So resolving only the page's own blockers keeps every un-asked id correctly silent
    instead of accidentally flagged.

    Requires:
        - repo is a TaskRepository bound to the live session
        - items is an iterable of TaskItem (may be empty)

    Ensures:
        - returns { blocker_id_str: status_or_None } covering every item-kind blocker id
          appearing in `items`, and nothing else
        - returns {} — issuing no query — when no row carries an item-kind blocker
    """
    ref_ids = [ ]
    for item in items:
        ref_ids.extend( item_blocker_ids( item.blocked_by ) )
    return repo.statuses_for_ids( ref_ids )


def _serialize_within_char_budget( items, serialize, budget: int ):
    """
    Serialize rows until the accumulated payload reaches a CHARACTER budget.

    THE SECOND BOUND (mini-plan 02 T3). `limit` caps ROWS, and a row cap is not a
    size cap: the same 100-row page measured 21,379 chars terse and 424,209 chars
    full on 2026-07-21, because rows carry multi-KB bodies. This bound governs the
    quantity that actually costs the caller — bytes — and it is INDEPENDENT of the
    row bound: whichever binds first wins, and the caller is TOLD which.

    A stop is NEVER silent: the second return value is the flag the response
    publishes as `truncated`, and the caller always also receives the honest
    `total`. A degraded response that does not announce its degradation is worse
    than an error.

    The FIRST row is admitted unconditionally, even when it alone exceeds the
    budget. A budget that can return zero rows for a non-empty result set is a
    pagination dead end — the caller advances `offset` forever and never makes
    progress. One oversized row plus `truncated: true` is honest AND advanceable.

    Requires:
        - items is an iterable of TaskItem
        - serialize is a callable TaskItem -> JSON-safe dict
        - budget is a non-negative integer character count (0 == unbounded)

    Ensures:
        - budget == 0 means UNBOUNDED (the explicit caller opt-out); every item is
          serialized and truncated is False
        - returns ( rows, truncated ) where rows is a prefix of the serialized
          items, in the order given
        - truncated is True IFF at least one item was left unserialized
        - len( rows ) >= 1 whenever items is non-empty
        - truncated is False whenever every item was serialized
    """
    rows      = [ ]
    truncated = False
    used      = 0

    for item in items:
        row  = serialize( item )
        size = len( json.dumps( row, default=str ) )
        # budget == 0 is UNBOUNDED, not "a budget of zero". A zero-char budget can
        # only ever mean "one row, then truncate", which is useless as a setting
        # and useful as an escape — so 0 is the caller's explicit opt-out, and the
        # `truncated` it reports is then honestly False.
        if budget and rows and used + size > budget:
            truncated = True
            break
        rows.append( row )
        used += size

    return rows, truncated


def _serialize_event( event ) -> dict:
    """
    Serialize a TaskEvent to the wire shape.

    Requires:
        - event is a flushed TaskEvent (id/ts populated)

    `title` rides here because an event stream WITHOUT it is unreadable by a human (row
    2c6a87f3). The completed-work accordion's design measured the gap: this projection returned
    `item_id` and nothing else identifying, so the single most important at-a-glance column was
    not on the wire and a client would have needed one extra fetch PER EVENT to recover it.

    🔴 IT IS READ THROUGH THE RELATIONSHIP, WHICH MAKES EAGER LOADING A CONTRACT AND NOT AN
    OPTIMISATION. Both repository readers (`query_events`, `get_events`) attach
    `joinedload( TaskEvent.item )`; drop either and this line becomes one SELECT per event,
    across a page capped at 500. A guard counts the queries rather than trusting the comment.

    ⚠️ NOT `getattr`-guarded, deliberately. `item_id` is NOT NULL with an ON DELETE CASCADE, so
    an event without its item cannot exist — a missing relationship is a torn read that should
    fail loudly here, not render as a blank title somebody later reports as a UI bug.

    Requires:
        - event is a flushed TaskEvent (id/ts populated)
        - event.item is loaded (both repository readers eager-load it)

    Ensures:
        - returns a JSON-safe dict mirroring the audit-trail row, plus the owning item's title
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
        "title"        : event.item.title,
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


def _blocked_mint_denial_detail( reason: str ) -> str:
    """
    Build the 403 detail for a rejected blocked-MINT, keyed on the classifier
    reason (bug dd3b3666). The old single message asserted "you are not a
    manager" even when the truth was "your bridge predates the stamp field the
    check reads — restart" — misdiagnosing every session alive across a future
    bridge-schema addition.

    Requires:
        - reason is one of the manager_figure.DENIAL_* constants

    Ensures:
        - DENIAL_STALE_BRIDGE → names the ABSENT stamp field and prescribes a
          session RESTART (which re-stamps the bridge at SessionStart). It states
          the OBSERVATION and not a cause: on 2026-08-30 (row 6325123c) the message
          asserted "this session started before the stamp existed" to a session
          started that same day — Phase 4.6 stamped the file and _record_listener_pid
          then wrote a pre-stamp dict over it, so the field was absent for a reason
          the message ruled out. A message must not assert a cause it never checked.
        - DENIAL_NO_SESSION_ID / DENIAL_DENIED → the permission message, unchanged
          in intent (a genuinely-denied caller is still told it is not a manager)
    """
    if reason == DENIAL_STALE_BRIDGE:
        return (
            "cannot verify manager status to mint a 'blocked' task: the caller's "
            "session bridge is missing the 'manager_figure_implicit' stamp that the "
            "manager-figure check reads (field ABSENT, not false). This states what "
            "was OBSERVED, not why: the bridge may predate the stamp field, or the "
            "stamp may have been written and then lost. RESTART the session to "
            "re-stamp the bridge, then retry. (If you are intentionally a non-manager: create the "
            "item queued and transition it to blocked, or have a manager mint it directly.)"
        )
    if reason == DENIAL_NO_SESSION_ID:
        return (
            "only a manager may mint a 'blocked' task at create — no parseable session "
            "id in created_by, so manager status cannot be established. Create the item "
            "queued and transition it to blocked, or have a manager mint it directly."
        )
    return (
        "only a manager may mint a 'blocked' task at create — the caller resolved and "
        "is not a manager figure ('manager_figure_implicit' is false and role is not "
        "'manager'). Create the item queued and transition it to blocked, or have a "
        "manager mint it directly."
    )


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
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    # THE PETITION NEEDS A RESOLVER LANE (row 9c26bf04). Same shape the transition
    # door already uses: the ticket is minted inside the request's transaction and
    # resolved after the response, so the create never blocks waiting on Rick.
    # Harmless on every non-petition create — nothing is scheduled.
    background_tasks: BackgroundTasks,
    # ATTRIBUTION (row: authenticated_user_id bound 12x, read 0x). This door WRITES,
    # so the ledger has to name whoever actually stood at it. Same helper as the other
    # write doors — one mechanism, never a second identity scheme.
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
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

    # ── THE PRIORITY FIREWALL, RULES 1 AND 3 (Rick's broadcast e254ec7d, row b8205986) ──
    #
    # "workers can file tickets, but they can only file a P5 ticket. That's the only
    # kind." And, unconditionally: "The only way a ticket will ever get upgraded to P0
    # is through me. Full stop."
    #
    # 🔴 SERVER-SIDE, BECAUSE A DISABLED DROPDOWN IS A COURTESY AND NOT A FIREWALL.
    # The row says the test that matters drives THIS door with a worker actor and
    # asserts the refusal; the UI guard is worth having and is not the control.
    #
    # 403 rather than 422, matching the admission gate below: this is an authorization
    # answer, not a malformed request. The caller's payload is well-formed and they are
    # not entitled to it.
    #
    # ⚠️ RUNS AFTER `validate_create`, on the shape-first-policy-second ordering every
    # other gate on this router follows. A caller sending an unknown priority should be
    # told it is unknown, not told they lack authority for a value that does not exist.
    priority_refusal = priority_firewall.refusal_for_priority_create(
        requested     = payload.priority,
        # `created_by` is the caller-declared "persona + session id" — the same string
        # shape every other gate here reads as `actor`. It buys the BRIDGE LOOKUP, not
        # a proof; rule 1 below ignores it entirely and consults the account.
        actor         = payload.created_by,
        account_email = account_email,
    )
    # ── THE PETITION: A REFUSAL WITH SOMEWHERE TO GO (Rick's ruling 2026-09-09, row 9c26bf04) ──
    #
    # 🔴 THE REFUSAL ABOVE STILL FIRED AND IS STILL CORRECT. Nothing here re-decides it.
    # `petition_is_available` answers a DIFFERENT question — may this refusal be carried
    # to Rick instead of returned — and only the DESTINATION changes. The caller leaves
    # with no authority it did not arrive with.
    #
    # ⚠️ `payload.authority` IS CALLER-DECLARED AND PROVES NOTHING. It ROUTES; it never
    # GRANTS. If a later edit makes it grant anything on its own, row b8205986 reopens —
    # that is the hole Rick closed on 2026-09-07 because a caller-supplied string can
    # name anyone.
    #
    # 🔴 A LOCAL, NEVER A MUTATION OF `payload`. This router already argues the case for
    # `receipt_refs`: the payload is the caller's evidence of what they SENT, and an
    # in-place downgrade would rewrite the record of the request we are adjudicating.
    petition_pending   = False
    effective_priority = payload.priority
    if priority_refusal is not None:
        if priority_firewall.petition_is_available(
            requested     = payload.priority,
            authority     = payload.authority,
            actor         = payload.created_by,
            account_email = account_email,
        ):
            petition_pending   = True
            effective_priority = priority_firewall.PETITION_HOLDING_PRIORITY
            # ⚠️ NO "P0 PETITION opened" LINE HERE (row d2b1b59a, 4b). It used to print at
            # this point, BEFORE the ratio gate — so a create the gate then refused logged
            # a petition that never existed (measured 21:31Z: the line, then a 422, and no
            # row and no ticket). It now prints where the ticket is actually minted.
        else:
            raise HTTPException( status_code=403, detail=priority_refusal )

    # Mint-status whitelist (Rick 2026-07-20): a create may mint queued OR blocked.
    # blocked_by persona refs are canonicalized to the store key BEFORE validate +
    # persist (identity parity, same as the transition seam), so the value validated
    # is the value written. A queued mint carries neither field — validate_create_status
    # ignores them, and the repository forces []/None for a non-blocked mint.
    blocked_by = _canon_blocked_by( payload.blocked_by )
    # ── PHASE 4: NEW TICKETS START IN THE HOLDING AREA (Rick's P0, 2026-09-02) ──
    #
    # Substituted here rather than as a Pydantic field default, because a field
    # default is evaluated at IMPORT: the flag would freeze at boot and an operator's
    # flip would need a restart. That is the exact asymmetry Rick objected to in the
    # ratio gate — the dials he could turn were the ones that changed nothing.
    #
    # ONLY when the caller did not name a status. `model_fields_set` is what makes
    # that distinguishable: an explicit `status="queued"` and an omitted one both
    # arrive as the string "queued", so without this a caller who deliberately asked
    # for a queued mint would be silently overridden — and would have no way to say
    # what they meant. Explicit intent always wins over a default.
    mint_status = payload.status
    if "status" not in payload.model_fields_set:
        mint_status = approval.default_mint_status()

    # 🔴 A PETITIONED ROW ALWAYS MINTS INTO THE HOLDING AREA, WHATEVER THE DEFAULT SAYS
    # AND WHATEVER THE CALLER ASKED FOR. Two reasons, and the second is mechanical:
    #
    #   1. Semantically it is already true — a petition IS a request Rick has not
    #      answered, and `not_approved` is precisely where unanswered rows live.
    #   2. The petition's approval carries `to_status="queued"`, and a row minted
    #      straight into "queued" would make that a queued->queued no-op, which
    #      `validate_transition` REJECTS. The priority raise rides in the SAME
    #      transaction as that transition, so a rejected edge would silently drop the
    #      P0 as well — the petition would resolve "approved" and grant nothing.
    #
    # This is the one place the petition overrides explicit caller intent, and it
    # overrides it DOWNWARD (into holding, never out of it), which is the safe
    # direction for a request that has not been granted.
    if petition_pending:
        mint_status = rules.NOT_APPROVED_STATUS

    _reject_if_errors( rules.validate_create_status( mint_status, blocked_by, payload.next_chase_ts ) )
    # ── THE CREATE DOOR (Rick's P0, row 0ef62dfd, 2026-09-08) ──
    #
    # The substitution ABOVE applies the holding default only when `status` was
    # omitted. Naming it explicitly wins — and that is how three rows reached
    # Rick's live board without ever generating a request he could deny. This is
    # the refusal that closes it; the predicate lives in task_approval_settings so
    # it can be tested alone and so the wiring test below can prove it is called.
    #
    # `payload.status` and `model_fields_set`, NOT `mint_status`: the question is
    # what the CALLER asked for, and mint_status has already had the default
    # substituted into it. Reading the substituted value here would make an omitted
    # status look explicit on exactly the deployments where the gate is on.
    live_mint_refusal = approval.refusal_for_live_mint(
        requested_status    = payload.status,
        status_was_explicit = "status" in payload.model_fields_set,
        priority            = payload.priority,
    )
    if live_mint_refusal is not None:
        raise HTTPException( status_code=403, detail=live_mint_refusal )


    # Manager-only guard for a blocked MINT — scoped ENTIRELY to status=="blocked"
    # (G2): the queued default path never parses created_by, so existing queued
    # creates (migration-test rows, HTTP callers with no parseable session id) do
    # NOT regress. A blocked row is a deliberate hold minted on someone's behalf —
    # ONLY a manager may mint one. Resolution REUSES the ONE canonical predicate
    # is_manager_figure (G1), fail-CLOSED: a caller whose manager-hood cannot be
    # established (predicate False OR no parseable session id) is REJECTED with 403
    # (authenticated but not authorized — distinct from the 422 validation lane).
    # `mint_status`, not `payload.status` — the two are equivalent TODAY (the
    # holding-area default never yields "blocked"), and reading the substituted
    # value is what keeps them equivalent. A future default that could mint blocked
    # would otherwise route around this guard silently; reading mint_status makes it
    # refuse instead, which is the safe direction for an authorization check.
    if mint_status == "blocked":
        session_id = rules.session_id_from_created_by( payload.created_by )
        if session_id is None or not is_manager_figure( session_id ):
            raise HTTPException(
                status_code = 403,
                detail      = _blocked_mint_denial_detail(
                    classify_manager_figure_denial( session_id )
                ),
            )

    # Soft title guard (design 2026.06.29 §4.3 / handoff #1): trim an over-long
    # title to the shared cap and move the overflow into an empty body — at the
    # SERVER write path so EVERY caller (MCP wrapper, hook, raw POST) is covered.
    # Fail-open: the write is never rejected for title length.
    guarded_title, guarded_body, title_guard = rules.soft_guard_title( payload.title, payload.body )

    owner_persona       = _canon_persona( payload.owner_persona )
    accountable_manager = _canon_persona( payload.accountable_manager )

    # Class-scoped owner default (policy 2, task c03d1870): an owned-work class
    # created WITHOUT an owner_persona defaults to the creator's persona (derived
    # from the bridge-stamped created_by) — forgiving, never a 422. decision/gate
    # operator-queue rows are NOT in DEFAULT_OWNER_CLASSES, so they stay ownerless.
    if owner_persona is None and payload.item_class in rules.DEFAULT_OWNER_CLASSES:
        owner_persona = rules.persona_from_created_by( payload.created_by ) or None

    # Unknown-persona soft-flag (policy 1): an off-roster owner/manager earns a
    # log-warn + a persona_flag response advisory + a compact marker folded into
    # the ->queued event reason — NEVER a rejection (cross-project personas are
    # legitimately absent from the local roster).
    persona_flag, flag_marker = rules.build_persona_advisory( owner_persona, accountable_manager )
    if persona_flag:
        print(
            f"[task WARN] off-roster persona on {payload.item_class} create: {persona_flag} — "
            f"not in known roster; advisory attached, write NOT blocked"
        )

    # Epic-key guard (row 5246bb67, Rick ruled twice: 2026-08-31 ~19:40 then again
    # ~20:35 with Maya's evidence, keeping reject-on-creation and FIXING the
    # predicate to startswith("epic:") with the cc-task: mirror lane exempt).
    #
    # WARN-ONLY until EPIC_KEY_ENFORCEMENT_ACTIVE flips — his ramp, so no caller
    # breaks by surprise. Deliberately placed HERE, beside soft_guard_title and
    # build_persona_advisory: repo.create_item has exactly one non-test caller, so
    # this line is the chokepoint every door goes through (MCP task_create, the
    # hook mirror, a raw POST).
    epic_advisory = rules.epic_key_advisory( payload.correlation_key )
    if epic_advisory:
        if rules.EPIC_KEY_ENFORCEMENT_ACTIVE:
            raise HTTPException( status_code=422, detail=epic_advisory )
        print(
            f"[task WARN] epic-key guard on {payload.item_class} create: {epic_advisory} "
            f"(WARN-ONLY until {rules.EPIC_KEY_ENFORCEMENT_STARTS}; write NOT blocked)"
        )

    with get_db() as session:
        repo = TaskRepository( session )

        # Closed-vs-new ratio gate (María's design; Rick's mechanical replacement for the
        # ticket moratorium). Shares this chokepoint with the epic-key guard above — one
        # door, so the two cannot be reasoned about separately by mistake.
        #
        # WARN-ONLY until RATIO_GATE_ENFORCEMENT_ACTIVE flips, his ruled ramp. Read INSIDE
        # the session because it needs the counts; evaluated BEFORE create_item so a
        # refusal writes nothing at all.
        # Both numbers read HERE, at request time, from the one module the header also
        # reads — so an operator's slider move reaches the gate and the board together.
        # Reading them once and passing both keeps ratio_gate_advisory pure.
        ratio_window = frs.get_window_hours()
        ratio_counts = repo.count_created_and_closed(
            since = datetime.now( timezone.utc ) - timedelta( hours=ratio_window )
        )
        # 🔴 `effective_priority`, SO A PETITION BUYS NO RATIO EXEMPTION. P0 is exempt
        # from this gate; a petition is a P0 that has been REQUESTED and not granted, so
        # reading `payload.priority` here would let any caller skip the throughput gate
        # by declaring authority="user_direct" — a caller-declared string GRANTING
        # something, which is the one thing the petition must never become.
        #
        # 🔴 AND THIS LINE IS WHAT COMPLETES THE ARGUMENT, WHICH IS STRONGER THAN CAUTION.
        # María 🌸 enumerated where `authority` could still buy something real, and the
        # answer is nowhere else — the claim routes and never grants at BOTH ends:
        #   · AT MINT   — the row persists at PETITION_HOLDING_PRIORITY (P1), the ceiling
        #                 the caller already had; the refusal above still fired.
        #   · AT RESOLVE — `_apply_resolution` PINS the priority to OPERATOR_ONLY_PRIORITY
        #                 and REFUSES a ticket carrying any other value as malformed, and
        #                 silence grants nothing: an unanswered ticket goes TICKET_STALLED
        #                 with an alarm rather than defaulting to approved.
        # ⇒ The ratio gate was the SINGLE REMAINING PLACE where `payload.priority` would
        #   have let the caller-declared string buy something. Reading `effective_priority`
        #   here closes the last one. (Verified 2026-09-09 against the resolver's own code.)
        #
        # ⚠️ THE COST IS REAL AND IS DELIBERATE: a petition can still be refused 422 by
        # the ratio gate, and the caller is then told about throughput rather than
        # authority. That is the honest answer — the two gates are independent and this
        # row only ever claimed to fix the authority one. Flagged to Rick as a follow-up
        # rather than settled here, because exempting on a claim is his call, not mine.
        # 🔨 THE OPERATOR SKIPS THIS GATE, AND EVERY USE IS LOGGED (Rick, by keypress,
        # 2026-09-10, row c9895403): "Yes my own tickets should skip the ratio gate and get
        # logged." The gate throttles the FLEET's filing; the tickets he files himself from
        # his New Ticket card are the direction the fleet is being steered in, not traffic
        # to meter. Keyed on `caller_is_operator` — a validated login, never a typed name —
        # so no seat can claim it. The logging is the condition, as it is for P0 below.
        operator_exempt = priority_firewall.caller_is_operator( account_email )
        ratio_refusal   = None if operator_exempt else rules.ratio_gate_advisory(
            created         = ratio_counts[ "created" ],
            closed          = ratio_counts[ "closed" ],
            priority        = effective_priority,
            correlation_key = payload.correlation_key,
            allow_below     = frs.get_allow_below(),
            # The VERDICT still reads `effective_priority` above; this only stops the
            # refusal telling a petitioner "A P0 is exempt" (row d2b1b59a, Finding 4).
            petition        = petition_pending,
        )
        # 🔨 ENFORCEMENT IS A SETTING, NOT A CONSTANT (Rick, 2026-09-02). It used to read
        # `rules.RATIO_GATE_ENFORCEMENT_ACTIVE` — a module-level literal needing a code
        # edit and a deploy — while the window and threshold two lines up were already
        # live-adjustable. Read HERE at request time from the same module, so all three
        # move together and an operator's change reaches the gate on the next create.
        if ratio_refusal:
            if frs.get_enforcement_active():
                raise HTTPException( status_code=422, detail=ratio_refusal )
            print(
                f"[task WARN] ratio gate on {payload.item_class} create: {ratio_refusal} "
                f"(enforcement OFF — set 'task flow ratio enforcement active'; write NOT blocked)"
            )
        elif operator_exempt:
            print(
                f"[task INFO] ratio-gate OPERATOR EXEMPTION used by "
                f"{recorded_actor( payload.created_by, account_email )}: "
                f"{payload.item_class} '{payload.title[ :60 ]}' at {effective_priority} "
                f"(window created={ratio_counts[ 'created' ]} closed={ratio_counts[ 'closed' ]})"
            )
        elif ( effective_priority or "" ).upper() in rules.RATIO_GATE_EXEMPT_PRIORITIES:
            # Rick's Q4: P0 is exempt AND every use is LOGGED. The logging is the whole
            # condition of the exemption — an unlogged escape hatch is just a hole.
            print(
                f"[task INFO] ratio-gate P0 EXEMPTION used by {payload.created_by}: "
                f"{payload.item_class} '{payload.title[ :60 ]}' "
                f"(window created={ratio_counts[ 'created' ]} closed={ratio_counts[ 'closed' ]})"
            )
        elif not ( payload.correlation_key or "" ).strip().startswith( rules.MIRROR_KEY_PREFIX ):
            # 🔴 THE PERMISSIVE PATH NOW REPORTS ITS READING (row aba30387, defect 1).
            # It printed NOTHING here, while created / closed / ratio / threshold all sat
            # in hand a dozen lines up. So a permit was indistinguishable from an absent
            # gate, which is exactly how this row came to say the gate was "armed and
            # inert" — the permits were correct and left no trace to prove it.
            #
            # Measured cost: settling that needed the ratio AT THE TIME of three permits,
            # and nothing had recorded it. Mr Radio reconstructed what he could and
            # reported the deciding value "remains INFERRED, NOT MEASURED". Unrecoverable.
            #
            # The P0-exemption branch directly above has printed its counts since Rick's
            # Q4 ruling — "an unlogged escape hatch is just a hole." This is the same
            # argument one branch over: an unlogged PERMIT is an unfalsifiable gate.
            #
            # ⚠️ THE MIRROR LANE IS CARVED OUT DELIBERATELY. `cc-task:` is harness traffic
            # writing where no human is present; it is already exempt from the gate itself
            # a few lines up, and it is the one path whose volume would drown the signal
            # this line exists to create. Every other permit reports.
            print( rules.ratio_gate_reading(
                created     = ratio_counts[ "created" ],
                closed      = ratio_counts[ "closed" ],
                allow_below = frs.get_allow_below(),
                verdict     = "allow",
            ) )

        # A blocked MINT can be born stranded exactly like a transition (row 00a6bde2).
        # Inside the transaction, and BEFORE create_item, so a rejected mint writes
        # nothing at all.
        _reject_unsatisfiable_blockers( repo, blocked_by )
        item = repo.create_item(
            item_class          = payload.item_class,
            title               = guarded_title,
            project             = _canon_project( payload.project ),
            created_by          = recorded_actor( payload.created_by, account_email ),
            authority           = payload.authority,
            body                = guarded_body,
            owner_persona       = owner_persona,
            accountable_manager = accountable_manager,
            gate_class          = payload.gate_class,
            # `effective_priority`, not `payload.priority` — a petition mints at P1 and
            # is raised to P0 only by Rick's answer, inside the resolver's transaction.
            priority            = effective_priority,
            urgency             = payload.urgency,
            status              = mint_status,
            blocked_by          = blocked_by,
            next_chase_ts       = payload.next_chase_ts,
            source_qid          = payload.source_qid,
            correlation_key     = payload.correlation_key,
            flag_suffix         = flag_marker,
            # RECORD the trim rather than re-deriving it from length later
            # (bug 769b3574). The guard's third return value is None exactly
            # when it did not cut, so this is the guard's own verdict rather
            # than a second opinion that can drift from it.
            title_trimmed       = title_guard is not None,
        )
        result = _serialize_item( item )
        result[ "title_guard" ]  = title_guard
        result[ "persona_flag" ] = persona_flag

        # ── RAISE THE PETITION AGAINST THE REAL ROW (row 9c26bf04) ──
        #
        # 🔴 AFTER `create_item` AND INSIDE THE SAME `with get_db()` BLOCK. The ticket
        # names `item.id`, so it cannot be minted before the row exists — and if the
        # create rolls back, the ticket goes with it. There is no state where Rick is
        # asked about a row that was never written.
        #
        # 🔴 THE RESPONSE IS 201, NOT 202, AND THAT IS NOT A COSMETIC CHOICE. Tiffany
        # measured it: `fetch`'s `response.ok` is true for ANY 2xx and `TaskListStore`
        # writes its optimistic state BEFORE the call, so a 2xx-that-means-"pending"
        # renders an unanswered petition as landed. Here 201 is also just TRUE: a row
        # was created, at P1, and it is the caller's. The petition is reported as a
        # FIELD on that row rather than as the status of the request.
        if petition_pending:
            requested_at = datetime.now( timezone.utc )
            intent = promotion_resolver.TransitionIntent(
                to_status      = "queued",   # literal — there is no rules.QUEUED_STATUS
                actor          = payload.created_by,
                recorded_actor = recorded_actor( payload.created_by, account_email ),
                authority      = payload.authority,
                receipt_refs   = None,
                blocked_by     = None,
                reason         = (
                    f"P0 petition: {payload.created_by} relayed an operator instruction. "
                    f"Minted at {effective_priority} in the holding area pending Rick's answer."
                ),
                park_reason    = None,
                next_chase_ts  = None,
                title          = guarded_title,
                session_id     = rules.session_id_from_created_by( payload.created_by ),
                # THE PETITION'S SECOND EFFECT — one approval RAISES and ADMITS, which is
                # what Rick chose when asked ("reprioritized and then pushed into the live
                # queue"). The resolver PINS this to P0 rather than trusting it, and
                # refuses any other value as malformed.
                priority       = priority_firewall.OPERATOR_ONLY_PRIORITY,
            )
            # Stamped from the timeout in force AT MINT TIME, never re-derived by the
            # sweeper — same contract as the transition door. ONE call, so the answer
            # window and the stall deadline come off one read of the timeout (dbe42964).
            deadlines = promotion_resolver.deadlines_for( requested_at )
            ticket = TaskPromotionTicket(
                item_id      = item.id,
                to_status    = "queued",
                requested_by = payload.created_by,
                requested_at = requested_at,
                answer_by    = deadlines.answer_by,
                resolves_by  = deadlines.resolves_by,
                payload      = intent.as_payload(),
                state        = promotion_resolver.TICKET_PENDING,
            )
            session.add( ticket )
            session.flush()          # assigns the id we are about to hand out
            # Logged HERE, after every gate and against the real row — see 4b above.
            print(
                f"[task INFO] P0 PETITION opened by {payload.created_by}: row {item.id} "
                f"'{payload.title[ :60 ]}' minted at {effective_priority}, ticket {ticket.id}, "
                f"pending Rick's answer"
            )
            background_tasks.add_task( promotion_resolver.resolve_ticket, ticket.id )

            result[ "petition" ] = {
                "ticket_id"   : str( ticket.id ),
                "minted_at"   : effective_priority,
                "requesting"  : priority_firewall.OPERATOR_ONLY_PRIORITY,
                "answer_by"   : ticket.answer_by.isoformat(),
                "resolves_by" : ticket.resolves_by.isoformat(),
                "deadlines"   : promotion_resolver.DEADLINES_NOTE,
                "check_with"  : "task_promotion_status",
            }

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
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    # 🔴 THE ONLY WAY THE ASK LEAVES THE REQUEST (row 3493ae9b). FastAPI runs these
    # AFTER the response has been sent, which is also after this function's `with
    # get_db()` block has exited and COMMITTED — so the worker cannot race the ticket
    # it was handed. Unused on every synchronous path, which is every path today.
    background_tasks: BackgroundTasks,
    # The approver gate's SECOND door (row 9d3a975e). `require_api_key_or_jwt` above
    # returns a user UUID, which the gate's configuration cannot speak about; this is
    # the same caller's login email, or None for an API-key caller. It authenticates
    # nothing on its own — the dependency above is what refuses a bad credential.
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
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

        return _apply_transition_under_lock(
            session, repo, item, task_id, payload, background_tasks, account_email,
        )


def _apply_transition_under_lock( session, repo, item, task_id, payload, background_tasks, account_email ):
    """
    Everything the transition door does once it holds the row lock — its whole gate order.

    🔴 EXTRACTED, NOT COPIED (row c9fafb9d, Rick's Q2 2026-09-10: "Approval moves it").
    Approving a manager's request must PERFORM the move through the same path as Rick's
    own board click, so the transition door and the request-verdict door both call this.
    The body is the handler's, moved verbatim; a second copy of the gate order would
    drift from the first the day either is edited.

    Requires:
        - session / repo are the caller's open transaction; item is row-locked in it
        - task_id is item's id; payload validates against TaskTransitionIn
        - account_email is the caller's VALIDATED login email, or None

    Ensures:
        - exactly what `transition_task` documents after its 404: every refusal raises
          HTTPException inside the caller's transaction, so `get_db` rolls it back
        - returns { item, event } serialized, or the asynchronous path's 202 response
    """

    # Identity parity (Phase 2): persona-typed blocked_by ids are stored
    # canonical so a "blocked on María/Mr. Radio" ref matches that persona's
    # owner_persona rows. Done before BOTH validate and apply so the value
    # validated is the value persisted.
    blocked_by = _canon_blocked_by( payload.blocked_by )

    # Structural rules first (shape), then the DB-backed liveness gate below (row
    # 00a6bde2). Order matters: a malformed ref must report as malformed, not as
    # an unresolvable id — the shape error is the one the caller can act on.
    _reject_if_errors( rules.validate_transition(
        from_status   = item.status,
        to_status     = payload.to_status,
        authority     = payload.authority,
        receipt_refs  = payload.receipt_refs,
        next_chase_ts = payload.next_chase_ts,
        blocked_by    = blocked_by,
        reason        = payload.reason,
        park_reason   = payload.park_reason,
        # bee6856a — the row's CURRENT coupled fields, so a genuine
        # blocked->blocked RE-POINT is legal while a true no-op stays
        # rejected. Read off the SAME row-locked item as from_status, so the
        # values compared are the committed ones; passing VALUES (not the
        # item) keeps task_store_rules free of any model import.
        current_blocked_by    = item.blocked_by,
        current_next_chase_ts = item.next_chase_ts,
    ) )

    # ->blocked onto a dead edge (row 00a6bde2). Runs on the SAME row-locked
    # transaction as the status validation, so the blocker statuses read here are
    # the committed ones — a blocker going terminal concurrently cannot slip a
    # stranded edge past this the way a read-then-write would.
    _reject_unsatisfiable_blockers( repo, blocked_by )

    # ── THE HOLDING-AREA APPROVAL GATE (Rick's P0, 2026-09-02) ──────────────
    #
    # Admission OUT of `not_approved` onto a board is the one transition that
    # turns a filed row into somebody's owed work. Rick: "either a manager or
    # him, for now" — so the allowlist is CONFIGURATION, editable without a
    # deploy, exactly as he corrected the ratio gate's flag the same day.
    #
    # It runs AFTER the structural rules on purpose: a caller with a malformed
    # payload should be told the payload is malformed, not that they lack
    # permission to send a malformed payload. Shape first, policy second — the
    # same ordering the blocker gate above is placed by.
    #
    # 🔴 TWO DOORS OF DIFFERENT STRENGTH, AND THE DIFFERENCE IS WORTH KNOWING.
    # `payload.actor` is caller-DECLARED and every seat carries the same fleet
    # credential, so THAT door refuses an honest non-approver and cannot stop a
    # dishonest one — policy control, not a security boundary. `account_email`
    # comes off a signature-validated access token and is not something a caller
    # can type. Reading the 403 as "authorization failed" is right for the second
    # door and an overclaim for the first.
    #
    # ⚠️ THE SECOND DOOR IS WHY THIS ENDPOINT WORKS FROM A BROWSER AT ALL (row
    # 9d3a975e). The client's actor is minted per websocket session — "operator
    # foolish goat" — so no allowlist entry could ever match it, and Rick could
    # not approve his own board. The endpoint had resolved his identity the whole
    # time; nothing had ever handed it to the gate.
    # ── THE OPERATOR ATTESTATION (Rick's ruling, 2026-09-04, row 1e12cc08) ──
    #
    # Placed HERE for the same reason the approval gate below is: shape first,
    # policy second. `validate_transition` above has already ruled on whether the
    # receipt is well-formed, so a caller who is both malformed AND unauthorised
    # hears about the malformation — the error they can act on.
    #
    # The result REPLACES the caller's value on the way to the ledger; see
    # `_resolved_operator_attestation` for why approving a string and then storing
    # the caller's own string would be an authorization check nothing consumes.
    operator_attestation = _resolved_operator_attestation( payload.receipt_refs, account_email )

    # ── THE MANAGER CLOSE (Rick's ruling 2026-09-10, row adaf7698) ─────────────
    #
    # "A manager should be able to close a ticket. That is not a matter of state
    # security." Scope, ruled ~17:28 EDT: close only, and a manager's close COUNTS
    # toward the create/close ratio — so nothing here touches the ratio.
    #
    # 🔴 MANAGER-HOOD IS RESOLVED ONCE, HERE, and handed to every gate that needs it:
    # the attestation, the approver gate, the throttle and the promotion gate. Four
    # derivations of one fact would agree only until their inputs diverged.
    #
    # ⚠️ RESOLVED ONLY WHERE IT CAN MATTER (Mr. Radio's review, 2026-09-10): a close,
    # or a request that claims the manager key. A pull, a block or a park reads no
    # bridge and hands every gate `closer_is_manager=False`.
    #
    # 🔴 SO THIS DOOR NEVER HANDS THE APPROVER GATE A MANAGER ON A PROMOTE, and the
    # carve-out's own `to_status == done` test cannot be reached as False from here.
    # It is still the clause that decides, and a pure test on `refusal_for_admission`
    # guards it — a door test cannot.
    #
    # ⚠️ THE CREDENTIAL IS THE ONE RICK CALLED "NOT QUITE FOOLPROOF" FOR PROMOTION: the
    # session bridge behind a caller-typed session id. He calls closing "not a matter
    # of state security", so the same check is in proportion here.
    closer_session_id      = rules.session_id_from_created_by( payload.actor )
    closer_manager_refusal = None
    closer_is_manager      = False
    claims_manager_key     = ( isinstance( payload.receipt_refs, dict )
                               and rules.MANAGER_ATTESTATION_KEY in payload.receipt_refs )
    if payload.to_status == approval.DONE_STATUS or claims_manager_key:
        closer_manager_refusal = promotion_gate.manager_refusal(
            closer_session_id, payload.actor,
            # Named on THIS module and looked up when the line runs, so a test can
            # stand in for the bridge. `manager_refusal` binds its own defaults at def
            # time, and no patch reaches those.
            is_manager_fn   = is_manager_figure,
            classify_fn     = classify_manager_figure_denial,
            account_persona = approval.approver_persona_for_account( account_email ),
            move            = promotion_gate.MOVE_MANAGER_CLOSE,
        )
        closer_is_manager = closer_manager_refusal is None
    manager_close = payload.to_status == approval.DONE_STATUS and closer_is_manager

    manager_attestation = _resolved_manager_attestation(
        payload.receipt_refs, closer_session_id, account_email,
        closer_is_manager, closer_manager_refusal,
    )

    # HOISTED so the ledger below and the promotion ticket beside it cannot become
    # two derivations of one value (row 3493ae9b). A copy is made rather than
    # mutating `payload.receipt_refs` in place — the payload is the caller's
    # evidence of what they SENT, and overwriting it would destroy the one record
    # that distinguishes a claim from a ruling.
    recorded_receipt_refs = payload.receipt_refs
    if operator_attestation is not None:
        recorded_receipt_refs = { **recorded_receipt_refs, rules.OPERATOR_ATTESTATION_KEY: operator_attestation }
    if manager_attestation is not None:
        recorded_receipt_refs = { **recorded_receipt_refs, rules.MANAGER_ATTESTATION_KEY: manager_attestation }

    approval_refusal = approval.refusal_for_admission(
        from_status       = item.status,
        to_status         = payload.to_status,
        actor             = payload.actor,
        account_email     = account_email,
        closer_is_manager = closer_is_manager,
    )
    if approval_refusal is not None:
        raise HTTPException( status_code=403, detail=approval_refusal )

    # ── NO MANAGER BATCHES (Rick, 2026-09-04) ──────────────────────────────
    #
    # "A manager should never be able to fire a batch. They should only ever
    # request 1 ticket at a time."
    #
    # 🔴 IT IS COUNTED, NOT INSPECTED, BECAUSE THERE IS NOTHING IN THE REQUEST
    # TO INSPECT. There is no batch endpoint — measured 2026-09-04, 14 task
    # routes and zero bulk doors — and the UI's batch approve is a client-side
    # loop firing single-row transitions that are byte-identical to a lawful
    # one-ticket request. Cardinality over time is the only thing that tells
    # them apart, and the event trail already records it.
    #
    # Runs AFTER the approver gate, for the reason every gate here runs after
    # the one before it: a caller who may not approve at all should be told
    # that, not told they are going too fast.
    # ── THE MANAGER PULL TOGGLE (Rick's P0, row 458e9947, 2026-09-06) ──────
    #
    # Placed with the other policy gates, after the structural rules, for the
    # reason they all are: shape first, policy second.
    #
    # 🔴 IT IS A SEPARATE GATE BECAUSE NOTHING HERE COULD HAVE CARRIED IT. Both
    # gates below key on `item.status == NOT_APPROVED_STATUS`, so both fire only
    # on admission OUT of the holding area. A pull is `queued -> in_progress`,
    # where that clause is False — so a toggle wired to either of them would have
    # shipped, looked correct, and disabled nothing. Measured at b6031094 before
    # this was written; the predicate tests one literal and cannot match.
    #
    # 409, not 403. The caller is not forbidden and has not misbehaved: this edge
    # is lawful and will be lawful again the moment Rick flips the switch back. A
    # 403 would tell a manager they lack permission they actually have, which is
    # the mislabelled-failure shape the throttle below is careful to avoid too.
    pull_refusal = approval.refusal_for_pull(
        from_status   = item.status,
        to_status     = payload.to_status,
        actor         = payload.actor,
        account_email = account_email,
        # 🔨 THE SELF-CLAIM EXEMPTION (María 🌸, 2026-09-07, row 1ec67228). The row
        # itself decides, so the row has to be handed over: a worker starting work
        # a DIFFERENT manager already assigned them is not the manager pull Rick
        # rescinded. Passed from the locked `item`, never from the payload — the
        # caller must not get to declare whose row it is.
        item_owner    = item.owner_persona,
        item_manager  = item.accountable_manager,
        # Rick's terms for the self-claim exemption: permitted WITH A RECEIPT.
        # The "who" half is already written by `recorded_actor` below; this is
        # the "why", and the gate refuses the exemption without it.
        reason        = payload.reason,
    )
    if pull_refusal is not None:
        raise HTTPException( status_code=409, detail=pull_refusal )

    admission_window = approval.get_admission_window_seconds()
    # A manager's close is not an admission, so it does not spend an admission slot
    # (row adaf7698). The event it writes still reads `not_approved->done`, so it is
    # still COUNTED by later admissions, exactly as before.
    if ( admission_window > 0
         and item.status == approval.NOT_APPROVED_STATUS
         and payload.to_status != approval.NOT_APPROVED_STATUS
         and not manager_close ):
        batch_refusal = approval.refusal_for_batch(
            actor             = payload.actor,
            account_persona   = approval.approver_persona_for_account( account_email ),
            recent_admissions = repo.count_admissions_since(
                actor = payload.actor,
                since = datetime.now( timezone.utc ) - timedelta( seconds=admission_window ),
            ),
        )
        if batch_refusal is not None:
            # 429, not 403. It is a THROTTLE — the same request succeeds shortly.
            # A 403 would tell a manager they lack permission they actually have,
            # which is the mislabelled-failure shape this router already avoids.
            raise HTTPException( status_code=429, detail=batch_refusal,
                                 headers={ "Retry-After": str( admission_window ) } )

    # ── PROMOTION OUT OF THE HOLDING AREA: MANAGER-ONLY, AND RICK IS ASKED ──
    #
    # Rick, by voice 2026-09-04: "the caller's credentials are checked to make
    # sure they're actually a manager. And if they are, the next thing that
    # happens is that the method you call asks, on your behalf, me, if you can
    # take a task out of the holding area and promote it into the queue."
    #
    # 🔴 THE ASK LIVES INSIDE THE CALL, WHICH IS THE WHOLE DESIGN. There is no
    # path from here to `apply_transition` that leaves him un-asked, so the
    # policy stops depending on anyone remembering it.
    #
    # It runs AFTER the approver allowlist for the same reason that gate runs
    # after the structural rules: a caller who cannot promote at all should not
    # cost Rick an interruption to find that out.
    #
    # ⚠️ THE TWO CHECKS AGREE BY COINCIDENCE, NOT BY CONSTRUCTION. The allowlist
    # above is configuration and reads ['cheech','maria','mr radio','rick']
    # today — the managers plus Rick. Nothing keeps it in step with manager-hood:
    # a NEW manager absent from that list is refused above, before this gate is
    # ever reached. Two predicates answering one question by different routes
    # agree right up until their inputs diverge.
    # ⚠️ THE SAME SWITCH AS THE ALLOWLIST ABOVE, AND NOT A SEPARATE ONE. With
    # holding-area enforcement OFF the room is not being policed at all, so
    # asking Rick to bless a promotion nobody is restricting is pure noise —
    # and worse, it is noise an operator cannot turn off from the one dial
    # that is supposed to control this door. Two gates on one door with two
    # switches is how a "disabled" feature keeps interrupting somebody.
    #
    # 🔴 A MANAGER'S CLOSE NEVER REACHES THIS GATE (row adaf7698, Mr. Radio's review
    # ruling 2026-09-10). Without the last clause a manager closing a held row would
    # pass the approver gate and then cause Rick to be asked whether to PROMOTE a row
    # that is being closed. The exclusion covers the asynchronous fork too, so no
    # ticket is minted for a close either.
    promotion_approval = None
    if ( approval.get_enforcement_active()
         and item.status == approval.NOT_APPROVED_STATUS
         and payload.to_status != approval.NOT_APPROVED_STATUS
         and not manager_close ):
        # 🔴 THE ACCOUNT REACHES BOTH DOORS, NOT JUST THE FIRST (row 998c7529).
        # Handing it only to the approver allowlist is what left Rick refused by
        # THIS gate after that one had already let him through: a browser resolves
        # no session id, so the manager-figure leg saw nothing to resolve. Same
        # fact, both doors, resolved once.
        promotion_session_id = rules.session_id_from_created_by( payload.actor )
        promotion_persona    = approval.approver_persona_for_account( account_email )

        # ── THE ASYNCHRONOUS FORK (row 3493ae9b, design 5.1) ───────────────
        #
        # 🔴 THE CREDENTIAL HALF STAYS INSIDE THE REQUEST ON BOTH PATHS, WHICH IS
        # RICK'S OWN SENTENCE ORDER AND NOT A PERFORMANCE CHOICE. A non-manager
        # still gets an immediate 403 and still costs him nothing. What moves out
        # of the request is only the part that waits on a human.
        #
        # ⚠️ `promotion_precheck` RETURNING None IS THE ONLY THING THAT MEANS "the
        # ask must fire", which is why the ticket is minted under it and nowhere
        # else. A settled answer — refused, or Rick promoting his own row — has
        # nobody to wait for, and a ticket promising an answer that is never coming
        # would be an orphan minted on purpose.
        if promotion_gate.promotion_is_asynchronous( payload.asynchronous ):
            settled = promotion_gate.promotion_precheck(
                session_id      = promotion_session_id,
                actor           = payload.actor,
                account_persona = promotion_persona,
            )
            if settled is not None and not settled.allowed:
                raise HTTPException( status_code=403, detail=settled.refusal )

            if settled is None:
                requested_at = datetime.now( timezone.utc )
                intent = promotion_resolver.TransitionIntent(
                    to_status      = payload.to_status,
                    actor          = payload.actor,
                    recorded_actor = recorded_actor( payload.actor, account_email ),
                    authority      = payload.authority,
                    receipt_refs   = recorded_receipt_refs,
                    blocked_by     = blocked_by,
                    reason         = payload.reason,
                    park_reason    = payload.park_reason,
                    next_chase_ts  = payload.next_chase_ts,
                    title          = item.title,
                    session_id     = promotion_session_id,
                )
                # Stamped from the timeout in force AT MINT TIME, never re-derived
                # by the sweeper - see `deadlines_for`. One call, one timeout read.
                deadlines = promotion_resolver.deadlines_for( requested_at )
                ticket = TaskPromotionTicket(
                    item_id      = task_id,
                    to_status    = payload.to_status,
                    requested_by = payload.actor,
                    requested_at = requested_at,
                    answer_by    = deadlines.answer_by,
                    resolves_by  = deadlines.resolves_by,
                    payload      = intent.as_payload(),
                    state        = promotion_resolver.TICKET_PENDING,
                )
                session.add( ticket )
                session.flush()          # assigns the id we are about to hand out
                background_tasks.add_task( promotion_resolver.resolve_ticket, ticket.id )

                # 🔴 202 GOES ONLY TO A CALLER THAT ASKED FOR IT, AND THIS RETURN IS
                # WHY THAT MATTERS. Tiffany measured it: `fetch`'s `response.ok`
                # is true for any 2xx, and `TaskListStore.transitionTask` writes its
                # optimistic "approved" row state BEFORE the call and restores only
                # on failure. A 202 never fails, so an un-opted-in browser would
                # render a promotion Rick has not been asked about as APPROVED - a
                # false FACT, not a false red, which is the species nobody
                # investigates. `promotion_is_asynchronous` is what keeps this line
                # unreachable for every caller that did not send a real boolean.
                return JSONResponse( status_code=202, content={
                    "status"      : "awaiting_human_approval",
                    "ticket_id"   : str( ticket.id ),
                    "task_id"     : str( task_id ),
                    "to_status"   : payload.to_status,
                    "answer_by"   : ticket.answer_by.isoformat(),
                    "resolves_by" : ticket.resolves_by.isoformat(),
                    "deadlines"   : promotion_resolver.DEADLINES_NOTE,
                    "check_with"  : "task_promotion_status",
                } )

            promotion_approval = settled
        else:
            promotion_approval = promotion_gate.approval_for_promotion(
                session_id      = promotion_session_id,
                actor           = payload.actor,
                task_id         = task_id,
                title           = item.title,
                account_persona = promotion_persona,
            )

        if not promotion_approval.allowed:
            raise HTTPException( status_code=403, detail=promotion_approval.refusal )

    # Rick's third requirement: a keypress and a timed-out default MUST NOT look
    # identical on the row, or nobody can later tell which promotions he actually
    # blessed. The suffix rides on `authority`, which is the field that already
    # means "the authority for this transition" — and his answer IS that authority.
    # 🔴 THE PROSE GOES IN `reason`, NOT IN `authority`. This block used to read
    # `transition_authority = f"{payload.authority} · {…authority_suffix()}"`, which
    # put a descriptive sentence into a String(32) enum column while leaving `reason`
    # — Text, unbounded — NULL. Measured: EVERY combination overflows, 58 to 65
    # characters, not merely the one row that surfaced it.
    #
    # AND THE CONCATENATION HAPPENED DOWNSTREAM OF THE CHECK THAT WOULD HAVE CAUGHT
    # IT. `payload.authority` is validated against rules.VALID_AUTHORITIES above; the
    # f-string then appended prose to the already-validated value, so validation
    # passed and the column still received 60+ characters. A guard that only checks
    # the input cannot see a field the code lengthens afterwards.
    #
    # Rick's third requirement is UNCHANGED and still met: a keypress, a timed-out
    # default and a self-promotion remain distinguishable on the row. They are simply
    # recorded in the field that is meant to carry a sentence.
    transition_authority = payload.authority
    transition_reason    = payload.reason
    if promotion_approval is not None and promotion_approval.allowed:
        # 🔴 THE COMPOSITION MOVED ONTO THE DATACLASS, AND THAT IS NOT A TIDY-UP.
        # The asynchronous resolver needs this identical string minutes later in
        # another call stack (row 3493ae9b). Composed at each door, the two would
        # agree until somebody changed a separator here — and an asynchronous
        # promotion would then be distinguishable from a synchronous one on the
        # row, for no reason any reader could guess. One method, two callers.
        transition_reason = promotion_approval.reason_with_suffix( payload.reason )

    event = repo.apply_transition(
        item          = item,
        to_status     = payload.to_status,
        # THE GATE READ THE TOKEN; THE LEDGER DID NOT. Door 1 (row 9d3a975e) let
        # Rick through on his authenticated account and then recorded the click
        # under "operator foolish goat" — the very string the gate had just
        # declined to trust. The same helper the edit door uses closes it.
        #
        # 🔴 MERGE RESOLUTION, 2026-09-04: the two sides of this conflict changed
        # DIFFERENT FIELDS and neither was reverting the other, so "both" is the
        # only correct answer rather than a compromise between two.
        #   HEAD  changed `authority` -> transition_authority, so a keypress and a
        #         timed-out default stop looking identical on the row (Rick's third
        #         requirement on the promotion gate).
        #   door1 changed `actor` -> recorded_actor(), so the ledger names the
        #         login account instead of a per-session "operator <adjective noun>".
        # door 1's `authority = payload.authority` is NOT a deliberate revert: its
        # branch is ~90 commits behind and `transition_authority` does not exist
        # there. Taking that side verbatim would have silently un-shipped the
        # keypress-vs-default distinction — a merge that compiles, passes, and
        # quietly returns a landed behaviour to the state it was fixed from.
        #
        # ⚠️ AUTHORIZATION IS UNAFFECTED BY THIS LINE, and that separation is the
        # whole point of door 1 (Mr Radio's ruling, 2026-09-04): the LOGIN ACCOUNT
        # off the validated token is the only trusted source for the gate above,
        # and `actor` is ATTRIBUTION ONLY. This is the ledger, downstream of every
        # decision — nothing here can widen who may pass.
        actor         = recorded_actor( payload.actor, account_email ),
        authority     = transition_authority,
        # THE SERVER'S ANSWER, NOT THE CALLER'S CLAIM. When an attestation was
        # asserted, `_resolved_operator_attestation` has already refused every
        # caller without a login account and resolved the survivors to a real
        # identity; that identity is what the ledger records. A copy is made
        # rather than mutating `payload.receipt_refs` in place — the payload is
        # the caller's evidence of what they SENT, and overwriting it would
        # destroy the one record that distinguishes a claim from a ruling.
        receipt_refs  = recorded_receipt_refs,
        next_chase_ts = payload.next_chase_ts,
        blocked_by    = blocked_by,
        reason        = transition_reason,
        park_reason   = payload.park_reason,
    )
    return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


def _resolved_operator_attestation( receipt_refs, account_email ):
    """
    The value the server will record for an `operator_attestation` receipt, or None
    when the caller did not claim one.

    Requires:
        - receipt_refs is the caller's receipts value (any type; non-dict is treated
          as "no attestation claimed", because shape errors belong to the rules layer)
        - account_email is the email off a VALIDATED access token, or None

    Ensures:
        - returns None when no `operator_attestation` key is present
        - raises HTTPException(403) when the key IS present and the caller has no
          resolvable login identity — that is every API-key caller, which is every
          agent seat in the fleet
        - otherwise returns the SERVER-RESOLVED identity, never the caller's string

    🔴 WHY THIS IS A FUNCTION IN THE ROUTER AND NOT A RULE IN task_store_rules.

    Rick ruled his click IS the receipt (row 1e12cc08), and María attached one
    non-negotiable to that ruling: "An agent must never be able to mint one." The
    only unforgeable fact available anywhere in this request is `account_email`,
    which comes off a signature-validated token. `payload.actor` cannot do this job
    — it is caller-DECLARED and `is_approver` is a string match, so a seat can type
    an approver's persona. The approval gate's own comment says as much: it "refuses
    an honest non-approver and cannot stop a dishonest one".

    ⇒ The rules module is pure and has no account to read, so a check placed there
    would validate shape and enforce nothing while LOOKING like enforcement. That
    is the one failure mode this design has, and it is why the check lives here.

    🔴 AND THE RETURN VALUE IS OVERWRITTEN, NOT MERELY APPROVED. `identity_for_account`
    resolves the account to a persona (or the email itself), and THAT is what gets
    recorded. A logged-in non-approver therefore cannot attest as "rick": the string
    they sent never reaches the ledger. Checking the caller's value and then storing
    the caller's value would leave the ledger saying whatever they typed — an
    authorization check whose result nothing downstream uses.

    ⚠️ THIS IS AN IDENTITY GATE, NOT AN APPROVER GATE, AND THE DIFFERENCE IS
    DELIBERATE. Any logged-in human may attest; only an accountless caller is
    refused. Narrowing it to the approver allowlist is a POLICY question that is
    Rick's to rule, and it is not smuggled in here — the row asked that agents be
    unable to mint one, which is exactly what this refuses.
    """
    if not isinstance( receipt_refs, dict ):        return None
    if rules.OPERATOR_ATTESTATION_KEY not in receipt_refs: return None

    identity = identity_for_account( account_email )
    if identity is None:
        raise HTTPException(
            status_code = 403,
            detail      = (
                f"'{rules.OPERATOR_ATTESTATION_KEY}' is a HUMAN OPERATOR's assertion and cannot be "
                f"minted by an API-key caller (row 1e12cc08, Rick's ruling 2026-09-04: his "
                f"click is the receipt). You authenticated without a login account, so the "
                f"server has no identity to record. An agent-side close still cites a commit "
                f"or a test_run — that rule is unchanged and was deliberately not weakened to "
                f"make this door work."
            ),
        )
    return identity


def _resolved_manager_attestation( receipt_refs, session_id, account_email, closer_is_manager, manager_refusal_detail ):
    """
    The value the server will record for a `manager_attestation` receipt, or None when
    the caller did not claim one (row adaf7698).

    Requires:
        - receipt_refs is the caller's receipts value (any type; non-dict is treated as
          "no attestation claimed", because shape errors belong to the rules layer)
        - session_id is the session id parsed from the caller's actor, or None
        - account_email is the email off a VALIDATED access token, or None
        - closer_is_manager is the router's ONE manager check for this request, and
          manager_refusal_detail is that check's refusal text (None when it passed).
          The router always runs the check when the key is present, so a claim can
          never arrive here with the check skipped

    Ensures:
        - returns None when no `manager_attestation` key is present
        - raises HTTPException(403) when the key IS present and the caller is not a
          manager, naming why and what to do instead
        - otherwise returns the SERVER-RESOLVED identity, never the caller's string:
          the login account's identity when there is one, else the manager seat's
          bridge persona plus its session id

    Modelled on `_resolved_operator_attestation`, and it is placed in the router for
    that function's reason: the rules module is pure and cannot tell a manager from a
    worker typing the key. It differs in WHO passes. The operator door wants a login
    account; this one wants a manager, which for an agent seat means the bridge.

    🔴 THE VALUE IS OVERWRITTEN, NOT MERELY APPROVED. A manager typing "rick" records
    their own seat. Checking the caller and then storing the caller's string would
    leave the ledger saying whatever they typed.
    """
    if not isinstance( receipt_refs, dict ):              return None
    if rules.MANAGER_ATTESTATION_KEY not in receipt_refs: return None

    if not closer_is_manager:
        raise HTTPException(
            status_code = 403,
            detail      = (
                f"'{rules.MANAGER_ATTESTATION_KEY}' is a MANAGER's word, and the server could "
                f"not establish that you are a manager: {manager_refusal_detail} "
                f"To proceed: ask your manager to close this row, or cite a commit or a "
                f"test_run (row adaf7698, Rick's ruling 2026-09-10: a manager may close a "
                f"ticket; a worker's close rule is unchanged)."
            ),
        )

    identity = identity_for_account( account_email )
    if identity is not None: return identity

    persona = get_voice_persona( session_id )
    name    = persona.get( "name" ) if persona is not None else None
    return f"{canonical_persona_key( name )} {session_id}" if name else f"manager seat {session_id}"


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
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    # ATTRIBUTION (row: authenticated_user_id bound 12x, read 0x). This door WRITES,
    # so the ledger has to name whoever actually stood at it. Same helper as the other
    # write doors — one mechanism, never a second identity scheme.
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
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
            actor           = recorded_actor( payload.actor, account_email ),
            authority       = payload.authority,
        )
        return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


@router.post(
    "/tasks/{task_id}/amend",
    summary     = "Append an amendment to a task-store item's body",
    description = "Phase-2.2 append-only body amendment: appends a persona-stamped "
                  "+ UTC-timestamped block to an item's body WITHOUT rewriting the "
                  "existing text (distinct from PATCH body, which overwrites) and "
                  "appends an 'amended' audit event. status / the oracle fields are "
                  "never touched. A TERMINAL item is ALLOWED (Rick 2026-08-02): the "
                  "block is marked a post-terminal addendum and the event is stamped "
                  "'amended_post_terminal' — a closed row stays closed. A blank note "
                  "and a bad authority are rejected (every violation at once). "
                  "Auth: X-API-Key or Bearer JWT."
)
def amend_task(
    task_id: uuid.UUID,
    payload: TaskAmendIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    # ATTRIBUTION (row: authenticated_user_id bound 12x, read 0x). This door WRITES,
    # so the ledger has to name whoever actually stood at it. Same helper as the other
    # write doors — one mechanism, never a second identity scheme.
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
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
        - 422 when authority is not a valid enum member or the note is blank after
          strip — every violation reported at once
        - a TERMINAL item is NOT rejected (Rick's ruling 2026-08-02, row
          3c569786): amend is the ONE write verb allowed on a closed row, so a
          gate verdict written after a worker self-closes has a durable home. The
          repository marks it a post-terminal addendum + stamps an
          'amended_post_terminal' event; status is never moved. transition / edit
          / correlate stay refused on a terminal row (unchanged)
        - row-locked read (N3 parity) so the status read that SELECTS the
          post-terminal marker cannot be raced by a concurrent ->done/->dropped
          transition
        - the router owns the clock (datetime.now(utc)) so the repo stays
          deterministic; body append + 'amended'/'amended_post_terminal' event
          are atomic (one get_db() transaction)
        - returns { item, event } serialized
    """
    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )

        # NO terminal rejection here (Rick's ruling 2026-08-02, row 3c569786):
        # amend is the ONE write verb allowed on a closed row, so a gate verdict
        # written after a worker self-closes has a durable home. The repository
        # marks the appended block as a post-terminal addendum and stamps a
        # distinct 'amended_post_terminal' event; status is never moved. The row
        # lock below still matters — the status read that SELECTS that marker must
        # not be raced by a concurrent ->done/->dropped. Transition / edit /
        # correlate stay refused on a terminal row (unchanged).
        errors = [ ]
        if payload.authority not in rules.VALID_AUTHORITIES:
            errors.append( f"authority '{payload.authority}' must be one of {rules.VALID_AUTHORITIES}" )
        if not payload.note.strip():
            errors.append( "note must be a non-blank string" )
        # Envelope-tail refusal, row 91ccbc26. The amend path is the THIRD carrier
        # the probe measured — a `note` stored the canary verbatim exactly as
        # park_reason did. Its `reason` rides the same payload and is the same
        # field by name and shape, so it is covered here too. Appended to the SAME
        # errors list, so a blank note and a captured tag report together rather
        # than one at a time.
        errors.extend( rules.validate_no_envelope_tail( {
            "note"   : payload.note,
            "reason" : payload.reason,
        } ) )
        _reject_if_errors( errors )

        event = repo.apply_amendment(
            item      = item,
            note      = payload.note,
            actor     = recorded_actor( payload.actor, account_email ),
            authority = payload.authority,
            now       = datetime.now( timezone.utc ),
            reason    = payload.reason,
        )
        return { "item": _serialize_item( item ), "event": _serialize_event( event ) }


# 🔴 REGISTERED ABOVE `PATCH /tasks/{task_id}` DELIBERATELY, AND MEASURED RATHER THAN
# ASSUMED. Starlette matches on path AND method and takes the FIRST full match, so a
# literal registered after a parameterised sibling with the same method is unreachable.
# Placed after it, `PATCH /api/tasks/manager-pull` resolved to `patch_task` and answered
# 422 "invalid UUID" — the identical defect `/api/tasks/flow-ratio` shipped with. The GET
# happened to be safe because its `{task_id}` twin is registered later; the PATCH was not.
# `test_the_manager_pull_routes_are_not_shadowed` pins BOTH verbs against the assembled
# router, so moving this block back down reddens by name instead of failing in production.

class ManagerPullRequest( BaseModel ):
    """
    A flip of Rick's manager-pull toggle. One field, and it is REQUIRED.

    🔴 `StrictBool`, NOT `bool`. Pydantic's lenient bool accepts the STRING "true", and
    `bool( "false" )` is True — so a lenient field would let a caller sending "false"
    switch the toggle ON while believing they had turned it off. That is the exact
    defect this endpoint exists to make unreachable, and accepting it here would put it
    back one layer up. The reader still PARSES strings, deliberately, for the operator
    who hand-edits the file; nothing should ever ARRIVE as one.
    """
    model_config = ConfigDict( extra="forbid" )

    disabled : StrictBool = Field(
        description="True switches pulling into in_progress OFF for everyone but an approver."
    )


class ApprovalSettingsRequest( BaseModel ):
    """
    One or more approval settings to write. Every field is optional; omitted means
    LEAVE UNCHANGED, which is what makes this a patch rather than a replace.

    🔴 `StrictBool`, NOT `bool`, AND IT IS THE WHOLE SAFETY OF THE DOOR. Pydantic's
    lenient bool coerces the string "false", and "false" is exactly the value this
    module has been bitten by twice — `bool( "false" )` is True, so a lenient model
    would let a caller switch a gate ON by sending the word "off".

    ⚠️ `extra="forbid"` IS DELIBERATE AND IS A CHOICE, not a default. Pydantic IGNORES
    unknown fields unless told otherwise, so a typo'd key — `enforcment_active` — would
    return 200 having changed nothing, and the operator would conclude the switch is
    broken. The alternative (ignore extras, as the rest of this router does) was
    rejected for exactly that reason: a setting ignored in SILENCE is the failure mode
    this file documents at length.
    """
    model_config = ConfigDict( extra="forbid" )

    enforcement_active    : Optional[ StrictBool ]      = Field( default=None, description="True makes the approval gate REFUSE; False makes it advise only." )
    default_to_holding    : Optional[ StrictBool ]      = Field( default=None, description="True mints new tickets into the holding area." )
    manager_pull_disabled : Optional[ StrictBool ]      = Field( default=None, description="True switches pulling into in_progress OFF for everyone but an approver." )
    approvers             : Optional[ list[ str ] ]     = Field( default=None, description="Persona names permitted to admit out of the holding area." )
    approver_accounts     : Optional[ dict[ str, str ] ] = Field( default=None, description="login email -> approver persona." )


@router.get(
    "/tasks/approval-settings",
    summary     = "Read every approval setting in force, and where each came from",
    description = "Same auth as /api/tasks. Values are the EFFECTIVE ones the gates "
                  "will use, not the raw file contents."
)
def get_approval_settings(
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ],
):
    """
    Serve the live settings and their provenance.

    ⚠️ THE READ IS NOT OPERATOR-GATED AND THE WRITE IS, WHICH IS A DELIBERATE
    ASYMMETRY. Reading which gates are on is how a seat understands a refusal it just
    got; hiding it would make every refusal unexplainable and send people to the file.
    Nothing here is secret either — these values already appear verbatim in the refusal
    messages this module emits to any caller who trips one.
    """
    return approval.current_settings()


@router.patch(
    "/tasks/approval-settings",
    summary     = "Write an approval setting — Rick only",
    description = "Rick's ruling 2026-09-08: \"Only the server writes it.\" Gated on a "
                  "signature-validated login account, never on a caller-declared name. "
                  "Booleans must be REAL booleans: the string \"false\" is truthy and is "
                  "refused at the model rather than coerced."
)
def patch_approval_settings(
    request_body          : ApprovalSettingsRequest,
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ],
    account_email         : Annotated[ Optional[ str ], Depends( authenticated_account_email ) ] = None,
):
    """
    Write the settings the caller named, and report what actually took effect.

    Ensures:
        - a non-operator is refused 403, INCLUDING every agent seat holding only the
          shared fleet API key — that is the cost Rick accepted when he closed the
          actor door
        - a body naming no setting is 422 rather than a silent no-op
        - a bad value is 422 and NOTHING is written: `set_overrides` validates every
          key before touching the file, so a two-key call cannot half-apply
        - returns the settings READ BACK after the write, never the values asked for

    🔴 WHY `caller_is_operator` AND NOT `require_admin`. `caller_is_operator` takes no
    `actor` parameter, so there is no typed-name path to leave open by accident — it
    resolves a signature-validated token and consults nothing a caller declares.
    `require_admin` is a WIDER set, and this file decides WHO MAY APPROVE; the door to
    it must not be wider than the thing it guards. The sibling `PATCH
    /tasks/manager-pull` uses `require_admin` and is deliberately NOT changed here —
    narrowing an existing door is a policy change and Rick's call, not a side effect of
    adding a new one.
    """
    if not priority_firewall.caller_is_operator( account_email ):
        raise HTTPException(
            status_code = 403,
            detail      = (
                "Approval settings are Rick's alone. This door is keyed on the login "
                "account on your token, never on a name you send — an API-key-only "
                "caller has no account and is refused here whatever it calls itself. "
                "Ask him to make the change."
            ),
        )

    updates = request_body.model_dump( exclude_none=True )
    if not updates:
        raise HTTPException(
            status_code = 422,
            detail      = "Name at least one setting to write. An empty body changes "
                          "nothing, and returning 200 for it would report a write that "
                          "never happened."
        )

    try:
        live = approval.set_overrides( **updates )
    except ValueError as error:
        raise HTTPException( status_code=422, detail=str( error ) )
    except OSError as error:
        raise HTTPException(
            status_code = 500,
            detail      = f"could not persist the approval settings ({error}). The live "
                          f"values are UNCHANGED — nothing was applied."
        )

    print( f"[task-approval] settings written by {account_email}: {sorted( updates )}" )
    return live


@router.get(
    "/tasks/manager-pull",
    summary     = "Read whether pulling work into in_progress is currently switched off",
    description = "Returns the live toggle state and where it came from. Same auth as /api/tasks."
)
def get_manager_pull( authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ] ):
    """
    Serve the live toggle and its provenance.

    Ensures:
        - returns { disabled, source } where source is "override" or "config"
        - the SOURCE is included for the reason the ratio endpoint includes its own: the
          value alone cannot tell an operator whether the INI is in force or is being
          masked by a saved override, which is the one confusion a two-layer scheme
          reliably creates
    """
    return {
        "disabled" : approval.get_manager_pull_disabled(),
        "source"   : ( "override"
                       if approval._read_overrides()[ "manager_pull_disabled" ] is not None
                       else "config" ),
    }


@router.patch(
    "/tasks/manager-pull",
    summary     = "Switch pulling work into in_progress on or off",
    description = "Rick's control (row 458e9947). Admin only. The body must carry a REAL "
                  "boolean — the string \"false\" is refused rather than coerced, because "
                  "it is truthy and would switch the toggle the wrong way."
)
def set_manager_pull(
    request_body : ManagerPullRequest,
    admin_user   : Annotated[ dict, Depends( require_admin ) ],
):
    """
    Flip the toggle, and report what actually took effect.

    Ensures:
        - a non-boolean is refused by the model at 422 before this body runs
        - returns the value read back AFTER the write, never the value asked for
        - a write failure is a 500 that says the live value is UNCHANGED, so an operator
          is never left believing a failed flip took
    """
    try:
        live = approval.set_manager_pull_disabled( request_body.disabled )
    except ValueError as error:
        raise HTTPException( status_code=422, detail=str( error ) )
    except OSError as error:
        raise HTTPException(
            status_code = 500,
            detail      = f"could not persist the manager-pull toggle ({error}). The live "
                          f"value is UNCHANGED — nothing was applied."
        )

    print( f"[task] manager-pull toggle set by {admin_user.get( 'email', admin_user )}: "
           f"disabled={live}" )
    return { "disabled": live, "source": "override" }


# ═══════════════════════════════════════════════════════════════════════════════
# THE REQUEST QUEUE'S TWO READ/WRITE DOORS (row c9fafb9d, rules 3 and 4)
#
# 🔴 THESE ARE REGISTERED HERE, ABOVE `PATCH /tasks/{task_id}`, AND THE POSITION IS
# LOAD-BEARING RATHER THAN TIDY. A literal path registered AFTER a parameterised
# sibling resolves to the sibling: `/api/tasks/manager-pull` shipped that way once and
# `/api/tasks/flow-ratio` answered 422 "invalid UUID" in production for an evening.
# `/tasks/flow-ratio` currently survives at line ~2794 only because its VERB differs
# from the PATCH above it — which is protection by coincidence, not by design. Sitting
# above the sibling makes the ordering irrelevant to the verb.
#
# ⚠️ WHAT IS NOT HERE, AND WHY ITS ABSENCE IS DELIBERATE: the door that FILES a request.
# Rick was asked on 2026-09-09 whether a refused promote should file the request itself
# or whether filing is a separate act; the ask TIMED OUT with no answer, and a timeout is
# not a ruling. Decision row 8c83d7ce carries that deferral. Building the filing door on
# a guess would ship the shape he did not pick, and the two shapes are not adjustable
# afterwards — one lives on the refusal path, the other is its own endpoint.
# ⇒ Until he answers, a request can be ANSWERED and COUNTED but not yet FILED through
#   the API. That is a half-built feature on purpose, and saying so here beats a future
#   reader concluding somebody forgot.
# ═══════════════════════════════════════════════════════════════════════════════

class RequestVerdictIn( BaseModel ):
    """
    The operator's answer to a pending promote/demote request.

    `verdict` is validated for MEMBERSHIP in the lifecycle module rather than here — a
    second copy of the legal set is a second thing to keep in sync, and the refusal it
    produces there already explains why 'pending' is not a verdict.
    """
    model_config = ConfigDict( extra="forbid" )

    verdict: str = Field( ..., min_length=1, description="approved | denied" )

    # Only read when APPROVING — the approval performs the move (Rick's Q2, 2026-09-10), and
    # these are what Rick's own board click would send with it. A demote's "Triage this by"
    # date rides here, exactly as his demote control asks for one.
    next_chase_ts : Optional[datetime] = None
    reason        : Optional[str]      = Field( default=None, max_length=4000, description="Rick's note on the move; the transition records it beside the request" )


class RequestFileIn( BaseModel ):
    """
    A manager's request that Rick promote or demote one row (row c9fafb9d, rule 3).

    `move` is validated for membership in the lifecycle module, for the reason
    `RequestVerdictIn` gives. `actor` carries the session id the manager check reads; it
    is recorded beside the authenticated identity and confers nothing on its own.
    """
    model_config = ConfigDict( extra="forbid" )

    move   : str = Field( ..., min_length=1, max_length=32, description="admit | demote" )
    reason : str = Field( ..., min_length=1, max_length=4000, description="why this row should move — Rick reads it on his board" )
    actor  : str = Field( ..., min_length=1, max_length=255, description="persona + session id filing the request" )


@router.get(
    "/tasks/request-badges",
    summary     = "How many pending promote/demote requests each board badge shows",
    description = "TWO INDEPENDENT COUNTS, NEVER A SUM (Rick via Mr. Radio, 2026-09-09). "
                  "The task-area badge counts DEMOTE requests and the holding-area badge "
                  "counts PROMOTE requests, because a badge sits on the list the row is in "
                  "NOW, not the list it is asking to reach. Both keys are always present, "
                  "so a caller never has to tell zero from absent. Auth: X-API-Key or "
                  "Bearer JWT — a manager may file a request and READ its state; only the "
                  "verdict is the operator's."
)
def get_request_badges(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
):
    """
    Count the pending requests, split by the badge each one belongs to.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)

    Ensures:
        - returns { "task_area": int, "holding_area": int }, BOTH keys always present
        - counts ONLY pending requests — a denied one is finished and a manager must
          re-file, so counting it would keep an answered question pulsing at Rick forever
        - the two counts are never added together: no list holds both kinds, so a combined
          total would be a number true of nothing
        - a row whose `request_move` is not a ruled move RAISES rather than being dropped
          from a count a human reads as complete (badge_for_move's contract)

    ⚠️ THE QUERY FILTERS ON `request_state` IN THE DATABASE, not in Python. The board
    renders this on every paint, and a scan that pulls every row to discard almost all of
    them is the shape that looks fine on a hundred rows and is the reason the store's own
    query guard exists.
    """
    with get_db() as session:
        pending = session.query( TaskItem.request_move, TaskItem.request_state ).filter(
            TaskItem.request_state == request_lifecycle.REQUEST_PENDING
        ).all()

    try:
        counts = request_lifecycle.badge_counts( pending )
    except ValueError as error:
        # badge_for_move refuses an unruled move rather than guessing. Surfacing it as a
        # 500 with its own words is right: the row is already in the database, so this is
        # a data fault nobody can fix by re-sending the request, and a silent zero would
        # understate a badge Rick reads as complete.
        raise HTTPException(
            status_code = 500,
            detail      = f"a stored request names a move with no ruled badge, so the counts "
                          f"cannot be completed: {error}"
        )

    return counts


@router.post(
    "/tasks/{task_id}/request",
    summary     = "File a manager's request that Rick promote or demote one row",
    description = "MANAGERS ONLY, ONE ROW PER CALL (row c9fafb9d, rule 3; Rick 2026-09-04, no "
                  "batches). A request ASKS and never moves: the row's status is untouched, "
                  "it waits on Rick's board with no expiry, and no answer means no. Body "
                  "`{move: admit|demote, reason, actor}`. 404 no row · 422 not a requestable "
                  "move or a blank reason · 409 the row cannot make that move from where it is, "
                  "or a request is already pending · 403 not a manager. Auth: X-API-Key or "
                  "Bearer JWT."
)
def file_request(
    task_id: uuid.UUID,
    payload: RequestFileIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
):
    """
    File a promote/demote request on a row, as the manager's own act.

    Requires:
        - authenticated caller; task_id a valid UUID (FastAPI 422s a malformed one)

    Ensures:
        - 404 when the item does not exist
        - 422 when `move` is not requestable, or `reason` is blank
        - 409 when the row cannot make `move` from its current status, naming where it is
        - 403 when the caller is not a manager, via `task_promotion_gate.manager_refusal` —
          the same check the close door asks, fail-closed on an unreadable bridge
        - 409 when a request is already pending on the row
        - otherwise: request_state 'pending', request_move, request_ts written under a row
          lock with a `request_filed` event; the row's status is NOT touched
        - returns the serialized item

    ⚠️ THE CHECK ORDER IS THE DESIGN'S (§2): where the row is before who is asking, so a
    worker asking the wrong question learns that first; who is asking before whether a
    request is pending, so the queue's contents are not disclosed to a non-manager.
    """
    if not payload.reason.strip():
        raise HTTPException( status_code=422, detail="`reason` is blank. Rick reads it on his board to decide — say why this row should move." )

    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )

        # The status code is projected from a FACT the router holds — whether the move is
        # requestable at all — never parsed out of the refusal's wording.
        refusal = request_lifecycle.refusal_for_filing( payload.move, item.status )
        if refusal is not None:
            raise HTTPException( status_code=422 if payload.move not in approval.REQUESTABLE_MOVES else 409, detail=refusal )

        manager_refusal = promotion_gate.manager_refusal(
            rules.session_id_from_created_by( payload.actor ), payload.actor,
            # Looked up on THIS module when the line runs, so a test can stand in for the
            # bridge — `manager_refusal` binds its own defaults at def time.
            is_manager_fn   = is_manager_figure,
            classify_fn     = classify_manager_figure_denial,
            account_persona = approval.approver_persona_for_account( account_email ),
            move            = promotion_gate.MOVE_REQUEST_FILING,
        )
        if manager_refusal is not None:
            raise HTTPException(
                status_code = 403,
                detail      = f"{manager_refusal} A worker asks its manager, who may file this request.",
            )

        refusal = request_lifecycle.refusal_for_refiling( item.request_state, item.request_move )
        if refusal is not None:
            raise HTTPException( status_code=409, detail=refusal )

        repo.apply_request_filing(
            item      = item,
            move      = payload.move,
            actor     = recorded_actor( payload.actor, account_email ),
            authority = "standing",
            reason    = payload.reason,
        )
        serialized = _serialize_item( item )

    print( f"[task] {payload.move} request filed on {task_id} by {payload.actor} ({authenticated_user_id})" )
    return serialized


@router.post(
    "/tasks/{task_id}/request-verdict",
    summary     = "Record the operator's verdict on a pending promote/demote request",
    description = "RICK ALONE (row c9fafb9d, rules 1 and 2 one layer over). A manager may "
                  "FILE a request and read its state; the answer is his — if a manager "
                  "could answer their own request, the request door would BE a way to "
                  "promote without him, which is the thing it exists to prevent. A verdict "
                  "is FINAL: to ask again, file a new request. `approved` PERFORMS the move "
                  "through the transition door's own gates (admit -> queued; demote -> "
                  "not_approved with `next_chase_ts`); `denied` leaves the row exactly where it "
                  "is. Auth: X-API-Key or Bearer "
                  "JWT, but the operator check binds to the AUTHENTICATED ACCOUNT — a "
                  "typed name confers nothing."
)
def record_request_verdict(
    task_id: uuid.UUID,
    payload: RequestVerdictIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    # Only because an approval runs the transition door's own body, which takes it. The
    # verdict never opts into the asynchronous path, so nothing is ever scheduled here.
    background_tasks: BackgroundTasks,
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
):
    """
    Write the operator's approved/denied onto a pending request.

    Requires:
        - authenticated caller; task_id a valid UUID (FastAPI 422s a malformed one)

    Ensures:
        - 404 when the item does not exist
        - 409 when the item carries NO request — there is nothing to answer, and that is a
          different mistake from being refused permission to answer
        - 403 / 422 exactly as `refusal_for_verdict` rules: not the operator, not a
          verdict, or already answered — each with its own sentence naming what to do next
        - the verdict is written with a row lock, so two callers cannot both read
          `pending` and both write
        - ⚠️ A DENIAL DOES NOT TOUCH THE TICKET. It finishes the REQUEST; it does not move,
          close, or alter the row (Mr. Radio's reading A, 2026-09-09; Rick 2026-09-10, "No
          means take no action whatsoever").
        - 🔨 AN APPROVAL PERFORMS THE MOVE (Rick's Q2, 2026-09-10): an admit lands in
          'queued', a demote in 'not_approved' carrying the verdict's `next_chase_ts`,
          through `_apply_transition_under_lock` — the transition door's own gate order. Any
          refusal on that path returns that gate's status and detail, and rolls back the
          verdict with it, so the request stays pending
        - returns the serialized item (after the move, when approved)

    🔴 WHO COUNTS AS THE OPERATOR, AND THE ALTERNATIVE I DID NOT TAKE. This binds to
    `approver_persona_for_account`, so it tracks the approver allowlist — which Rick
    emptied, leaving `UNCONDITIONAL_APPROVERS = ( "rick", )` as the only resolution. The
    alternative was to hardcode against UNCONDITIONAL_APPROVERS so that re-adding a
    manager to the allowlist could never let them answer.
    ⇒ I took the allowlist because it opens NO new path: anyone Rick puts back on that
      list may already promote and demote directly, so letting them answer a request adds
      nothing they could not do more simply. Binding to the allowlist also keeps ONE place
      that says who approves, which is the property `approver_persona_for_account`'s own
      docstring is built around.
    ⇒ Recorded rather than assumed, because the two behave identically TODAY and diverge
      the moment anyone edits that config — which is exactly when nobody re-reads this.
    """
    # ONE FACT, RESOLVED ONCE, FROM THE VALIDATED ACCOUNT. `refusal_for_verdict` says in
    # its own docstring that callers must pass a FACT and never a claim — row b8205986
    # records what happened when a caller-declared string got to answer this question.
    is_operator = approval.approver_persona_for_account( account_email ) is not None

    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )

        if item.request_state is None:
            raise HTTPException(
                status_code = 409,
                detail      = f"task {task_id} carries no promote/demote request, so there is "
                              f"nothing to answer. This is not a permissions refusal — filing a "
                              f"request is a separate act, and none has been filed on this row."
            )

        # 🔴 ONE CALL, UNDER THE LOCK, WITH THE ROW'S REAL STATE — never a pre-check
        # against an assumed one. An earlier draft answered the operator and not-a-verdict
        # refusals before the round trip by passing `REQUEST_PENDING` as a placeholder;
        # that is a fabricated input, and a gate fed a fabricated fact is not the gate.
        #
        # THE STATUS CODE COMES FROM A FACT I ALREADY HOLD, NOT FROM READING THE REFUSAL
        # TEXT. Mapping `is_operator` to 403 and everything else to 409 keeps this a
        # PROJECTION of the gate rather than a second copy of its rule — two pieces of code
        # deciding one rule agree until they do not.
        refusal = request_lifecycle.refusal_for_verdict(
            state             = item.request_state,
            verdict           = payload.verdict,
            actor_is_operator = is_operator,
        )
        if refusal is not None:
            raise HTTPException( status_code=403 if not is_operator else 409, detail=refusal )

        # 🔴 WHO ANSWERED IS RECORDED FROM WHAT THE SERVER KNOWS. The body carries no actor,
        # and a successful verdict has already proved an operator ACCOUNT above — so the
        # declared half is the authenticated user id, not a string the caller typed.
        repo.apply_request_verdict(
            item      = item,
            verdict   = payload.verdict,
            actor     = recorded_actor( authenticated_user_id, account_email ),
            authority = "user_direct",
        )

        # 🔨 AN APPROVAL PERFORMS THE MOVE (Rick's Q2, 2026-09-10 ~19:44, "Approval moves it").
        # Through `_apply_transition_under_lock` — the transition door's own gate order, not a
        # copy — with Rick's account, so a promote by approval is a promote by click.
        #
        # 🔴 THE VERDICT IS WRITTEN FIRST, ON PURPOSE. Once the request reads 'approved' it is
        # no longer pending, so the move does not withdraw it as stranded (design §7). And if
        # any gate on that path refuses, its HTTPException leaves this `with get_db()` block,
        # which rolls back the verdict with it: the request stays pending, the row stays put.
        if payload.verdict == request_lifecycle.REQUEST_APPROVED:
            move       = item.request_move
            transition = TaskTransitionIn(
                to_status     = request_lifecycle.LANDING_STATUS[ move ],
                actor         = authenticated_user_id,
                authority     = "user_direct",
                next_chase_ts = payload.next_chase_ts,
                reason        = ( f"approved a manager's '{move}' request"
                                  + ( f": {payload.reason}" if payload.reason else
                                      " — the manager's reason is on the request_filed event" ) ),
            )
            result     = _apply_transition_under_lock( session, repo, item, task_id, transition,
                                                        background_tasks, account_email )
            serialized = result[ "item" ]
        else:
            serialized = _serialize_item( item )

    print( f"[task] request verdict '{payload.verdict}' recorded on {task_id} by {account_email}" )
    return serialized



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
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    # ATTRIBUTION ONLY — this door still refuses nobody (row 77f4e1d3, María's ruling
    # 2026-09-04: "correct the attribution … leave the 404 behaviour exactly as it is").
    # The edit door's ONLY HTTPException is the 404 below, and that is unchanged.
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
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
        - 422 when `title` exceeds rules.TITLE_SOFT_CAP, naming the actual length
          and the cap (Rick's ruling 2026-09-01, bug 6ce252e7). The EDIT door
          rejects where the CREATE door trims fail-open: a create is unattended
          and losing it loses the filing, while an editor is present to shorten
          the string and is the only party who knows which half is the qualifier
        - `title_guard` is consequently ALWAYS None on this path — an edit that
          cannot trim cannot relocate an overflow either. The key stays in the
          response because it is part of the PATCH contract
        - `title_trimmed` is written on EVERY title edit and is always False —
          a retitle that repairs a previously-trimmed row must clear the flag
        - field update + 'patched' event append are atomic (one transaction)
        - returns { item, event, persona_flag, title_guard } serialized
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

    # Unknown-persona soft-flag (policy 1) on the reassign path: a PATCH re-owning
    # an item to an off-roster persona earns the same log-warn + persona_flag
    # advisory + folded marker as create — NEVER a rejection. The fields are
    # already canonical (normalize_patch_fields above); an absent persona field
    # (a non-reassign PATCH) canonicalizes to None and is not flagged.
    persona_flag, flag_marker = rules.build_persona_advisory(
        fields.get( "owner_persona" ), fields.get( "accountable_manager" )
    )
    if persona_flag:
        print(
            f"[task WARN] off-roster persona on task {task_id} patch: {persona_flag} — "
            f"not in known roster; advisory attached, write NOT blocked"
        )

    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_id} not found" )
        # 🔴 CLOSED HISTORY IS STILL IMMUTABLE — WITH ONE CARVE-OUT: A TITLE MAY BE
        # PREFIXED. Rick's ruling, 2026-09-01, decision 45c4c932: "Prefix only."
        #
        # The wall stands for every other field, and for any title change that is not
        # a prefix. What it was accidentally protecting was the wrong thing: a closed
        # row accepts only `amend`, which writes to `body`, and `_serialize_item_terse`
        # DROPS body — so a correction filed there is invisible to every routine board
        # glance. Measured live: `82ec60be` still reads "APPROVED 757820dd + 08fce017"
        # while its own body records that the 08fce017 approval is WITHDRAWN.
        #
        # A prefix restates nothing. The original title survives byte-for-byte after
        # the marker, so the board can say both what the row said and that it no longer
        # stands — the same add-never-overwrite rule the store already applies to
        # bodies, which is why this needs no new trust model.
        if item.status in rules.TERMINAL_STATUSES:
            _reject_if_errors( rules.validate_terminal_edit_fields( fields, item.title, item.status ) )

        # ── THE PRIORITY FIREWALL, RULES 1 AND 2 (Rick's broadcast e254ec7d, row b8205986) ──
        #
        # "the only way a ticket gets an upgrade from P5 to P4 through P1 is through a
        # me or a manager" — and P0 through him alone, "full stop".
        #
        # 🔴 THE CURRENT PRIORITY COMES FROM THE LOCKED `item`, NEVER FROM THE PAYLOAD.
        # This is a RAISE check, so it needs to know where the row is now; letting the
        # caller state that would let them declare "it was already P0" and walk in.
        # Same reason `refusal_for_pull` above takes `item_owner` from the locked row.
        #
        # ⚠️ IT RUNS INSIDE THE ROW LOCK, so the priority it compares against cannot be
        # moved by a concurrent PATCH between the read and the check. A gate that reads
        # an unlocked value is deciding on a state that may already be gone.
        #
        # 403, matching the create door and the admission gate: an authorization
        # answer, not a malformed request.
        if "priority" in fields:
            priority_refusal = priority_firewall.refusal_for_priority_change(
                current       = item.priority,
                requested     = fields[ "priority" ],
                actor         = payload.actor,
                account_email = account_email,
            )
            if priority_refusal is not None:
                raise HTTPException( status_code=403, detail=priority_refusal )

        # 🔴 THE EDIT DOOR REJECTS; THE CREATE DOOR TRIMS. Rick's ruling, 2026-09-01
        # (bug 6ce252e7): "Raise to 120 with a 422 over it."
        #
        # THIS IS NOT A RETURN OF BUG 28fc1fb4, and the difference is worth stating
        # because the two look alike from a distance. That bug was the two doors
        # disagreeing SILENTLY and by accident — capped at 60 through create,
        # unbounded through PATCH, neither announced. Here they disagree LOUDLY and
        # on purpose: both read the same TITLE_SOFT_CAP, and above it a create trims
        # fail-open while an edit answers 422 naming the length.
        #
        # The reason is who is standing at each door. A create is unattended — a
        # hook, the MCP wrapper, an agent filing mid-task — and a rejected create
        # loses the filing. An edit is somebody retyping a title with their hands on
        # the keys, and they are the only party who knows which half of the string
        # is the qualifier. The trim cuts the TAIL, which is exactly where the
        # qualifier lives.
        #
        # A rejection here also means an edit can never trim, so it can never
        # relocate an overflow into a body either. `title_guard` is therefore always
        # None on this path — kept in the response because the key is part of the
        # PATCH contract, and its constancy is now a FACT about the door rather than
        # an oversight.
        title_guard = None
        if "title" in fields:
            _reject_if_errors( rules.validate_edit_title_length( fields[ "title" ] ) )

            # 🔴 WRITTEN ON EVERY TITLE EDIT (bug 769b3574). A row trimmed once and
            # later REPAIRED by a shorter retitle has a complete title, so False is
            # the correct answer — six live rows are exactly that case, and the old
            # length-derived flag got them right only by accident of length. A
            # set-only flag would get them wrong on purpose.
            #
            # Every title that reaches this line is within the cap (the reject above
            # is the only other exit), so False is not a shortcut — it is the only
            # answer an edit can produce now.
            #
            # It rides `fields` (post-validation) so apply_patch writes it through
            # the same equality that composes the audit delta — the flag and the
            # event can never disagree about whether it moved.
            fields[ "title_trimmed" ] = False

        event = repo.apply_patch(
            item, fields, actor=recorded_actor( payload.actor, account_email ), authority=payload.authority,
            reason=payload.reason, flag_suffix=flag_marker,
        )
        return {
            "item"        : _serialize_item( item ),
            "event"       : _serialize_event( event ),
            "persona_flag": persona_flag,
            "title_guard" : title_guard,
        }


@router.get(
    "/tasks",
    summary     = "Query task-store items",
    description = "The deterministic owed-work query (R4): exact-match filters, "
                  "AND semantics, newest first. Junk enum filter values are "
                  "rejected (422), never silently empty. count_only=true returns "
                  "{count} as a true COUNT(*) without serializing any rows (the "
                  "owed-count token win, §G). terse=true returns the at-a-glance "
                  "projection (id/title/status/blocked_by/next_chase_ts/priority/"
                  "park_reason_stale — drops body) for cheap 'see my list' "
                  "queries. Auth: X-API-Key "
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
    id_prefix           : Optional[str] = None,
    count_only          : bool = False,
    terse               : bool = False,
    include_terminal    : bool = False,
    unscoped_audit      : bool = False,
    owed_only           : bool = False,
    hide_parked         : bool = True,
    # Activity window (row 0107c19e / Rick's Finished-Tasks P0, 2026-09-07).
    # Same since/until shape as `query_event_stream` rather than a second
    # convention on one page — but bound to `updated_ts`, not `created_ts`: a row
    # minted three weeks ago and closed this afternoon belongs in "the last 24
    # hours", and keying on creation would answer a different question.
    updated_since       : Optional[datetime] = None,
    updated_until       : Optional[datetime] = None,
    limit               : int = Query( default=100, ge=0, le=500 ),
    offset              : int = Query( default=0, ge=0 ),
    char_budget         : Optional[int] = Query( default=None, ge=0 ),
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
        - count_only=False (default): returns
          { tasks, count, total, has_more, truncated, warnings } matching ALL
          provided filters, ordered created_ts descending, stable tiebreak on id.
          `count` is the PAGE length (len(tasks)) — UNCHANGED meaning, it
          saturates at `limit`. The four keys beside it (mini-plan 02, 2026-07-21)
          exist because `count` alone was being read as the SIZE OF THE RESULT and
          never was: measured, a scoped query reported count:100 while offset=100
          returned 100 more rows, with no total / has_more / truncated to say so.
          `total` is a true COUNT(*) over the SAME filters, page-independent (NOT
          derived from len(tasks)); `has_more` = offset + count < total;
          `truncated` is True when the RESPONSE_CHAR_BUDGET bound stopped
          serialization before the row bound did; `warnings` carries the
          heavy-pull nudge and the truncation notice to the CALLER (they were
          stdout-only, an audience that cannot act on them). ADDED keys only —
          the multiplexer parses this shape (see the count_only branch comment).
        - count_only=True (O2 / §G token win): returns { count, breakdown } —
          `count` is a true SQL COUNT(*) over the SAME filters, NO rows
          serialized, independent of limit/offset (those params are ignored in
          this mode). The owed source reads this so a session with >100 owed
          rows is counted exactly. count_only takes precedence over terse (a
          count needs no rows at all).
          `breakdown` (c191be39, 2026-07-20) is { status: count } over that same
          admitted set via ONE GROUP BY — the status that used to die at this
          seam, which made the Stop hook report every `queued` row as
          "in-progress". Statuses with no rows are OMITTED, never zero-filled.
          Under owed_only=true the `parked` key IS the expired-parked set (park-
          active rows never survive admission). ALWAYS returned — no opt-in flag,
          because a flag a caller can forget is the shape that caused the bug.
          It appears ONLY in this branch: the full-row response is UNCHANGED, and
          the multiplexer parses that one.
        - terse=True (§G token win, count_only=False): returns { tasks: [...],
          count } where each row is the at-a-glance projection (id / title /
          status / blocked_by / next_chase_ts / priority / park_reason_stale —
          `body` and the other full-row fields dropped), so an on-demand "see my
          list" query over MCP costs a fraction of the full-row token weight.
          park_reason_stale rides the TERSE shape deliberately: a staleness flag
          carried only by the full row is a flag nobody reads (§3.3).
        - owed_only=True (PARKED-STATUS 2026-07-19) selects the OWED set —
          queued U in_progress U (parked AND NOT park-active) — computed
          SERVER-SIDE. Park-expiry is evaluated at READ time and never written
          back, so a status-enumerating caller CANNOT reconstruct this: an
          expired parked row still carries status="parked" in the column.
          Callers pass this ONE flag and never put "parked" in a status tuple;
          that is what makes it fail-CLOSED (there is no second thing to forget).
          Honors an explicit `status` filter by narrowing within it.
        - hide_parked=True (DEFAULT — the board-hygiene behavior) suppresses
          park-ACTIVE rows without touching the status set, so blocked/claimed/
          review rows stay on the board exactly as today. EXPIRED parked rows
          remain VISIBLE: they have rejoined, and a row that pokes you while
          staying invisible on the board is the incoherence this build removes.
          Pass status="parked" (or hide_parked=false) to surface the parked set —
          that is the audit surface.
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

    # id_prefix (row f45b37a9 remedy 2, closing 4288dd53) — the fleet writes 8-hex
    # everywhere and no read verb accepted it as a FILTER. Classified, never passed
    # through: a LIKE built from arbitrary caller text turns an id lookup into a
    # search surface, so junk 422s here and never reaches SQL. A FULL uuid is
    # accepted and normalized to its compact form, because refusing the exact
    # spelling of the thing you are filtering on would be a gratuitous trap.
    if id_prefix is not None:
        kind, value = rules.classify_task_ref( id_prefix )
        if kind == rules.TASK_REF_INVALID:
            errors.append(
                f"id_prefix '{id_prefix}' is not a task reference — expect a full UUID or "
                f"at least {rules.MIN_TASK_REF_PREFIX_LEN} hex characters (hyphens optional)"
            )
        else:
            id_prefix = value.hex if kind == rules.TASK_REF_FULL else value
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
                id_prefix           = id_prefix,
                include_terminal    = include_terminal,
                owed_only           = owed_only,
                hide_parked         = hide_parked,
                updated_since       = updated_since,
                updated_until       = updated_until,
            )
            # PER-STATUS BREAKDOWN (c191be39, 2026-07-20) — ALWAYS returned, no
            # opt-in flag: a flag a caller can forget is the same failure shape
            # that produced the bug this fixes (the Stop hook reported N `queued`
            # rows as N in-progress because the status died at this seam).
            #
            # ⛔ SCOPED TO THIS BRANCH ON PURPOSE. /api/tasks is NOT internal-only —
            # the multiplexer parses the FULL-ROW shape (render/taskListModel.ts,
            # render/TaskListRenderer.ts, notifications.js:386, a 60s poll at
            # multiplexer/boot.ts:586). This branch returns BEFORE any row is
            # materialized, so `breakdown` provably cannot reach that shape.
            # count_only has exactly ONE non-test consumer in the tree (the hook's
            # query_owed), which is what makes always-return safe HERE and only here.
            #
            # A SECOND aggregate, deliberately NOT derived from `count` above:
            # count == sum( breakdown.values() ) is then a real cross-check between
            # two independent computations. Deriving one from the other would make
            # the invariant unfalsifiable — a green assertion that could never fail
            # and therefore never reports anything.
            breakdown = repo.count_tasks_by_status(
                owner_persona       = owner_persona,
                status              = status,
                gate_class          = gate_class,
                urgency             = urgency,
                accountable_manager = accountable_manager,
                project             = project,
                item_class          = item_class,
                correlation_key     = correlation_key,
                id_prefix           = id_prefix,
                include_terminal    = include_terminal,
                owed_only           = owed_only,
                hide_parked         = hide_parked,
                updated_since       = updated_since,
                updated_until       = updated_until,
            )
            # Priority breakdown rides the SAME count_only branch as `breakdown`
            # (Rick 2026-07-27): the poke needs to say WHICH rows matter, not only
            # how many. Scoped to this branch for the identical reason the status
            # breakdown is — it returns before any row is materialized, so it
            # provably cannot reach the multiplexer's full-row shape.
            priority_breakdown = repo.count_tasks_by_priority(
                owner_persona       = owner_persona,
                status              = status,
                gate_class          = gate_class,
                urgency             = urgency,
                accountable_manager = accountable_manager,
                project             = project,
                item_class          = item_class,
                correlation_key     = correlation_key,
                id_prefix           = id_prefix,
                include_terminal    = include_terminal,
                owed_only           = owed_only,
                hide_parked         = hide_parked,
                updated_since       = updated_since,
                updated_until       = updated_until,
            )
            return { "count": count, "breakdown": breakdown,
                     "priority_breakdown": priority_breakdown }
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
                id_prefix           = id_prefix,
                limit               = limit,
                offset              = offset,
                include_terminal    = include_terminal,
                unscoped_audit      = unscoped_audit,
                owed_only           = owed_only,
                hide_parked         = hide_parked,
                updated_since       = updated_since,
                updated_until       = updated_until,
            )
        except rules.UnscopedQueryError as e:
            raise HTTPException(
                status_code = 400,
                detail      = (
                    f"unscoped task_query would return {e.count} non-terminal rows "
                    f"(> {e.threshold}). Narrow it with a filter (owner_persona / "
                    f"status / item_class / project / gate_class / accountable_manager "
                    f"/ correlation_key / id_prefix), or pass unscoped_audit=true for a deliberate "
                    f"full-store audit."
                ),
            )
        # terse → the at-a-glance projection (§G); else the full wire shape.
        # Blocker statuses resolve ONCE for the page (row 00a6bde2) and are bound into
        # the serializer, so `_serialize_within_char_budget` keeps its one-arg contract.
        base_serialize    = _serialize_item_terse if terse else _serialize_item
        blocker_statuses  = _resolve_blocker_statuses( repo, items )
        serialize         = lambda item: base_serialize( item, blocker_statuses )
        # THE DELIBERATE-SWEEP ESCAPE, mirroring unscoped_audit. The byte budget
        # protects the caller who did not know to ask — an agent pulling 97k tokens
        # into a context. It must NOT quietly shrink a caller who asked for the
        # whole board ON PURPOSE: the multiplexer's dashboard poll (limit=500 +
        # unscoped_audit=true) documents its own invariant in TaskListStore.ts as
        # "the human's view is never silently truncated", and the default budget
        # cut it from 1100 available rows to 30 (measured 2026-07-21). An explicit
        # char_budget=0 opts out; any other value overrides. Same shape as the
        # unscoped-size guard: protective by default, escapable by a caller who
        # names the escape, never escapable by accident.
        budget           = rules.RESPONSE_CHAR_BUDGET if char_budget is None else char_budget
        tasks, truncated = _serialize_within_char_budget( items, serialize, budget )
        # T1 (mini-plan 02): `total` is a TRUE COUNT(*) over the same filters, NOT
        # len(tasks) and NOT derived from the page. Two independent computations
        # keep `total` vs the count_only branch's `count` a real cross-check; a
        # `total` derived from the page could never disagree with it, which is an
        # unfalsifiable green — an assertion that can never fail reports nothing.
        # limit/offset are deliberately NOT forwarded: a total is page-independent.
        total = repo.count_tasks(
            owner_persona       = owner_persona,
            status              = status,
            gate_class          = gate_class,
            urgency             = urgency,
            accountable_manager = accountable_manager,
            project             = project,
            item_class          = item_class,
            correlation_key     = correlation_key,
            id_prefix           = id_prefix,
            include_terminal    = include_terminal,
            owed_only           = owed_only,
            hide_parked         = hide_parked,
            updated_since       = updated_since,
            updated_until       = updated_until,
        )
        warnings = [ ]
        # APERTURE DISCLOSURE (bug d23147e8, item 3) — a project-scoped query must
        # declare what it did NOT match.
        #
        # `project` is free text: TaskCreateIn validates only min_length=1/
        # max_length=255 and `_canon_project` passes non-aliased names through
        # unchanged, so a typo mints a project silently and permanently. The alias
        # table is NOT the defence and item 2 of this row was struck on that ground —
        # you cannot enumerate aliases for names nobody has agreed on. What scales is
        # the query publishing its own blind spot.
        #
        # THE FAILURE THIS ANSWERS: a wrong `project=` value returns a clean,
        # plausible, SMALLER number and nothing says a row was excluded. `52c1c41e`
        # was invisible to a census by construction — the row lived under
        # "google-skills-distillation" while the census asked for
        # "skills-distillation" — and Rick's drop order was executed against that
        # census. It survived only because its owner happened to see it on her own
        # owner-scoped board.
        #
        # Computed ONLY when a project filter is active: with no filter the caller
        # already sees every project, so there is no aperture to declare and no
        # second query worth paying for.
        if project is not None:
            by_project = repo.count_tasks_by_project(
                owner_persona       = owner_persona,
                status              = status,
                gate_class          = gate_class,
                urgency             = urgency,
                accountable_manager = accountable_manager,
                item_class          = item_class,
                correlation_key     = correlation_key,
                id_prefix           = id_prefix,
                include_terminal    = include_terminal,
                owed_only           = owed_only,
                hide_parked         = hide_parked,
                updated_since       = updated_since,
                updated_until       = updated_until,
            )
            # Compare on the CANONICAL form so an alias that legitimately resolves to
            # the queried project is NOT reported as unmatched — `_canon_project` is
            # the same function the filter itself went through, so a bucket is
            # "unmatched" here iff the filter genuinely could not have matched it.
            # The reported KEY stays the RAW stored string: canonicalizing the output
            # would hide the orphan spelling, which IS the finding.
            unmatched = {
                stored : n for stored, n in by_project.items()
                if _canon_project( stored ) != project
            }
            if unmatched:
                excluded = sum( unmatched.values() )
                # ⚠️ RANK BY SUSPICION, NOT BY SIZE. The first cut of this sorted by
                # count descending — which buries the finding by construction. An
                # orphan spelling is RARE (that is what makes it an orphan), so a
                # count-descending list puts the one value worth seeing dead last,
                # behind every large unrelated project, and the top-N cut drops it
                # first. On the live store that ordered the actual defect
                # ('google-skills-distillation'=1) at position 8 of 8, under
                # 'lupin'=838. A disclosure whose ordering hides its own signal is
                # the `park_reason_stale` failure — a flag readers learn to skip,
                # which disarms it permanently.
                #
                # NEAR = one name contains the other (case-folded). That is exactly
                # the shape an alias takes: a prefix/suffix qualifier on a shared
                # stem ("google-" + "skills-distillation"). Deliberately NOT edit
                # distance — it would rank 'lookml' near 'lupin' on 3 shared letters
                # and rank the real 8-character prefix pair as far.
                def _is_near( stored ):
                    a, b = ( stored or "" ).casefold(), ( project or "" ).casefold()
                    return bool( a ) and bool( b ) and ( a in b or b in a )
                ranked = sorted(
                    unmatched.items(),
                    key = lambda kv: ( not _is_near( kv[ 0 ] ), -kv[ 1 ] )
                )
                near     = [ s for s, _ in ranked if _is_near( s ) ]
                shown    = ", ".join( f"{stored!r}={n}" for stored, n in ranked[ :10 ] )
                more     = "" if len( unmatched ) <= 10 else f" (+{len( unmatched ) - 10} more)"
                # The near-miss callout leads, because it is the actionable half. When
                # nothing is near, say so rather than leaving the reader to scan the
                # list and conclude it themselves.
                lead = (
                    f"⚠️ LIKELY SAME PROJECT, DIFFERENT SPELLING: {', '.join( repr( n ) for n in near )}. "
                    if near else "No near-miss spelling detected. "
                )
                aperture_notice = (
                    f"project={project!r} matched {total} row(s). {lead}"
                    f"{excluded} row(s) under {len( unmatched )} OTHER project value(s) were "
                    f"excluded by this filter and are NOT in `total` (nearest-first): "
                    f"{shown}{more}"
                )
                print( f"[task_query APERTURE] {aperture_notice}" )
                warnings.append( aperture_notice )
        # Warn-not-fail (María #3): a heavy NON-terse pull earns an OBSERVABLE log
        # line nudging toward terse=True — never a rejection, rows still returned.
        if not terse and len( tasks ) > rules.NONTERSE_WARN_THRESHOLD:
            heavy_notice = (
                f"non-terse pull returned {len( tasks )} full rows "
                f"(> {rules.NONTERSE_WARN_THRESHOLD}) — pass terse=true for the "
                f"at-a-glance projection to cut token weight"
            )
            # T2 (mini-plan 02): the log line SURVIVES, but stdout was the wrong
            # audience — the server operator is not the party paying the token
            # weight, and the caller about to be charged for it never saw this.
            # Same trigger, audience corrected: it now ALSO rides the response body.
            print( f"[task_query WARN] {heavy_notice}" )
            warnings.append( heavy_notice )
        if truncated:
            truncation_notice = (
                f"response truncated at the {rules.RESPONSE_CHAR_BUDGET}-char budget — "
                f"{len( tasks )} of {total} matching rows serialized; page with "
                f"offset, or pass terse=true"
            )
            print( f"[task_query WARN] {truncation_notice}" )
            warnings.append( truncation_notice )
        # ROW-CAP overflow — the OTHER truncation mode, which signalled NOTHING until
        # now (row a5f4eb3f). `/api/tasks` has two ways to drop rows and only the
        # char-budget one announced itself: exceed `limit` and the caller gets a full
        # page, `truncated: false`, and an empty `warnings[]`.
        #
        # THE ROW CAP IS THE MODE THAT ACTUALLY BIT. The notifications dashboard polled
        # with include_terminal=true, inflating the board to 1,171 rows against the 500
        # cap: 671 rows dropped, no flag, no warning — and newest-first ordering meant
        # the EVICTED rows were the OPEN ones the panel exists to display. Both call
        # sites carried a comment promising the human's view was "never silently
        # truncated." It was truncated by 57%.
        #
        # ⚠️ `truncated` IS DELIBERATELY NOT SET HERE. It means "stopped at the char
        # budget" to every existing consumer, and overloading it would silently change
        # a live signal's meaning — the same class of defect as `count` being read as a
        # total. `has_more` already carries the fact; what was missing is that nothing
        # NAMED it, and both consumers ignored a bare boolean. A warning names it.
        elif offset + len( tasks ) < total:
            row_cap_notice = (
                f"row-cap truncation — {len( tasks )} of {total} matching rows returned "
                f"(limit={limit}, offset={offset}); {total - offset - len( tasks )} rows "
                f"not shown. Ordering is newest-first, so the omitted rows are the "
                f"OLDEST matches. Page with offset, or narrow the filter"
            )
            print( f"[task_query WARN] {row_cap_notice}" )
            warnings.append( row_cap_notice )
        # ⚠️ ADDED KEYS ONLY. `count` KEEPS ITS EXACT PRIOR MEANING (the length of
        # THIS page) — /api/tasks is NOT internal-only and the multiplexer parses
        # this shape on a 60s poll (see the standing comment on the count_only
        # branch). Renaming or removing `count` breaks a live consumer; adding
        # beside it does not. What changes is that the page length is no longer the
        # ONLY number published — it was being read as the size of the result, and
        # it never was.
        return {
            "tasks"     : tasks,
            "count"     : len( tasks ),
            "total"     : total,
            "has_more"  : offset + len( tasks ) < total,
            "truncated" : truncated,
            "warnings"  : warnings,
        }


@router.get(
    "/tasks/events",
    summary     = "Query the cross-item event stream",
    description = "Fleet-wide audit (design backlog): the append-only event "
                  "trail across ALL items, filtered by actor / transition / "
                  "to_status / project / time range (since/until on event ts), "
                  "newest first. Each event carries the owning item's `title`, "
                  "eager-loaded. `to_status=done` matches every *->done event "
                  "whatever the source status, which the exact-match "
                  "`transition` filter cannot express; an unknown value is a "
                  "422 naming the valid set, never an empty result. Distinct "
                  "from /tasks/{id}/events (one item). Declared "
                  "BEFORE /tasks/{task_id} so the static path wins over the "
                  "UUID path converter. Auth: X-API-Key or Bearer JWT."
)
def query_event_stream(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    actor      : Optional[str]      = None,
    transition : Optional[str]      = None,
    to_status  : Optional[str]      = None,
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
        - each event carries the owning item's `title`, eager-loaded (never N+1)
        - `to_status` matches the target of the transition — `to_status=done` returns every
          `*->done` event whatever the source status, which the exact-match `transition`
          filter cannot express without 21 separate calls
        - an unknown `to_status` is a 422 naming the valid set, never an empty result
    """
    # Junk enum filters 422 here rather than reaching SQL — the same contract `query_tasks`
    # already keeps, and for the same reason: an unknown value must be a CALLER ERROR, never an
    # honest-looking empty result the caller reads as "nothing reached that status".
    # ⚠️ AND IT IS LOAD-BEARING BEYOND TIDINESS: the repository matches this value with LIKE, so
    # an unvalidated `%` would silently widen the query instead of failing.
    errors = []
    if to_status is not None and to_status not in rules.VALID_STATUSES:
        errors.append( f"to_status filter '{to_status}' must be one of {rules.VALID_STATUSES}" )
    _reject_if_errors( errors )

    with get_db() as session:
        repo   = TaskRepository( session )
        events = repo.query_events(
            actor      = actor,
            transition = transition,
            to_status  = to_status,
            project    = project,
            since      = since,
            until      = until,
            limit      = limit,
            offset     = offset,
        )
        rows = [ _serialize_event( event ) for event in events ]
        return { "events": rows, "count": len( rows ) }


def _resolve_task_ref( repo, task_ref: str ):
    """
    Resolve a caller-supplied task reference — a full UUID or an 8-hex prefix —
    to exactly one item, or raise the HTTPException the caller should see.

    THE DEFECT THIS CLOSES (f45b37a9 leg 1): every brief, DM and cross-reference
    in this fleet names rows by 8-hex prefix, and no read verb accepted that
    form — `task_get("86ce4c43")` 422'd on uuid parsing. The identifier the
    fleet communicates in could not fetch the thing it names.

    Requires:
        - repo is a TaskRepository
        - task_ref is the raw path value

    Ensures:
        - a full UUID goes STRAIGHT to get_by_id and never prefix-scans, so
          every existing caller's behavior is unchanged
        - a hex prefix resolving to exactly one item returns that item
        - AMBIGUITY IS AN ERROR, NEVER A SILENT FIRST-MATCH: >1 match raises 422
          NAMING every candidate id, so the caller can disambiguate. Picking one
          silently would resolve an identifier to something other than what the
          caller meant with nothing saying so — the very defect class this came
          from
        - no match raises 404 quoting the ref the caller actually typed
        - an unparseable ref raises 422 WITHOUT touching the database
    """
    kind, value = rules.classify_task_ref( task_ref )

    if kind == rules.TASK_REF_INVALID:
        raise HTTPException(
            status_code = 422,
            detail      = f"task reference '{task_ref}' is neither a UUID nor a hex id prefix "
                          f"of at least {rules.MIN_TASK_REF_PREFIX_LEN} characters"
        )

    if kind == rules.TASK_REF_FULL:
        item = repo.get_by_id( value )
        if item is None:
            raise HTTPException( status_code=404, detail=f"task {task_ref} not found" )
        return item

    matches = repo.find_by_id_prefix( value )
    if not matches:
        raise HTTPException( status_code=404, detail=f"task {task_ref} not found" )
    if len( matches ) > 1:
        candidates = ", ".join( str( m.id ) for m in matches )
        raise HTTPException(
            status_code = 422,
            detail      = f"task id prefix '{task_ref}' is ambiguous — it matches "
                          f"{len( matches )} items: {candidates}. Supply more characters "
                          f"or the full UUID."
        )
    return matches[ 0 ]


# ---------------------------------------------------------------------------
# 🔴 REGISTERED ABOVE `/tasks/{task_id}` ON PURPOSE — DO NOT MOVE IT DOWN.
#
# FastAPI matches routes in REGISTRATION ORDER, so a literal path parked below a
# parameterised sibling is never reached: `/tasks/flow-ratio` was swallowed by
# `/tasks/{task_id}` and answered 422 — "task reference 'flow-ratio' is neither a
# UUID nor a hex id prefix" — for as long as it shipped.
#
# It was INVISIBLE because the client hides it by design: `fetchFlowRatio` returns
# null on any non-2xx and the header omits the clause, so a broken endpoint and a
# quiet board render identically. Rick found it by looking at the page.
#
# `/tasks/events` already sat above the parameterised route for this exact reason;
# this one did not, and no test could see the difference — the unit test calls the
# handler directly, and the Playwright test `route.fulfill`s this very path.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Closed-vs-new ratio (María's design, planning-is-prompting
# planning-is-prompting/src/rnd/2026.09.01-closed-vs-new-ratio-gate.md @ 845a34b)
# ---------------------------------------------------------------------------

# 🔴 THE WINDOW AND THE THRESHOLD NOW LIVE IN cosa.rest.flow_ratio_settings.
# Both were hardcoded here (24) and in task_store_rules.py (the literal 1.0), which is
# two copies of a number this endpoint's own docstring promises is computed in ONE place
# "so the header and the gate cannot drift apart". They now come from one module, backed
# by INI defaults and an operator-writable persisted override.
#
# ⚠️ DO NOT REINTRODUCE A MODULE-LEVEL CONSTANT FOR EITHER. A constant is read once at
# import, so a runtime change would not reach a running server — which is the whole
# reason the operator's slider exists. Call the getters at REQUEST time.
RATIO_DEFAULT_WINDOW_HOURS = frs.FALLBACK_WINDOW_HOURS   # retained for existing importers


@router.get(
    "/tasks/flow-ratio",
    summary     = "Closed-vs-new ratio over a rolling window",
    description = (
        "Returns { created, closed, ratio, verdict, room_for, close_needed, headroom, "
        "window_hours, allow_below, window_start, project } counted in SQL. The board's "
        "header and the creation gate are both thin consumers of this ONE payload, which "
        "is what stops them disagreeing with each other."
        "\n\n"
        "**TWO CAPACITY NUMBERS, AND THEY DIFFER BY EXACTLY ONE. RENDER `room_for`.**"
        "\n\n"
        "- `room_for` — **the display number, and the ruled one.** How many more creates "
        "leave the ratio still under the threshold AFTER they land (LOOP semantics). "
        "`0` means AT CAPACITY BUT STILL LEGAL and is rendered as the word `FULL`. "
        "`null` when the gate already refuses — that case is `close_needed`, not zero.\n"
        "- `headroom` — **the gate boundary. Diagnostic only, do NOT display.** The exact "
        "count the gate would admit, which is ALWAYS EXACTLY ONE MORE than `room_for` "
        "wherever there is any room, because the gate judges each create against the "
        "counts BEFORE it lands.\n"
        "- `close_needed` — closures required before the gate would admit again; `0` when "
        "it already admits, `null` when no number of closures opens it (a zero threshold).\n"
        "\n"
        "**Worked example \u2014 created 10, closed 13, allow_below 1.00:**\n\n"
        "| field | value | meaning |\n"
        "|---|---|---|\n"
        "| `room_for` | **2** | render this: `\u00b7 Room for 2 more` |\n"
        "| `headroom` | **3** | the gate really would admit 3 |\n"
        "\n"
        "The gate takes 3 because it judges create #3 at 12/13 = 0.92 BEFORE that row "
        "lands; only create #4, judged at 13/13 = 1.00, is refused. The display says 2 "
        "because after 3 creates the ratio is no longer under the threshold. "
        "**`headroom` is always `room_for` + 1 wherever there is any room** \u2014 they "
        "agree only when both are 0."
        "\n"
        "The one-lower display is Rick's ruling of 2026-09-05 13:11:13 EDT, by keypress, on "
        "the option labelled \"Keep your three states - badge under-reports by one\" "
        "(receipt: notifications row `819dc891`, `state = responded`, `source = ui`, and "
        "the time above is **`responded_at`** \u2014 that table also carries `created_at` "
        "(when the question went out) and `expires_at`, and reading either as the answer "
        "time is how this stamp got mis-stated twice). It "  
        "is deliberate: the display errs toward saying there is no room while the gate "
        "would still accept one, which is the safer error for a moratorium. A consumer "
        "that renders `headroom` to \"fix\" the off-by-one also destroys the `FULL` state, "
        "which he ratified separately — the number and the word are one choice, not two."
        "\n\n"
        "Auth: X-API-Key or Bearer JWT (same guard as /api/tasks)."
    )
)
def get_flow_ratio(
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ],
    window_hours          : Optional[ int ] = Query( default=None, ge=1, le=8760 ),
                                          # None = "use the operator's live window".
                                          # A literal default here would be bound at
                                          # IMPORT and freeze the boot value forever.
    project               : Optional[ str ] = Query( default=None ),
):
    """
    Serve the closed-vs-new ratio for a rolling window.

    Rick's durable, mechanical replacement for the ticket moratorium he declared by
    voice on 2026-09-01: "It's way too easy for you guys to add tickets to the list and
    way too hard to get them removed."

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - window_hours in [ 1, 8760 ]; project is None (fleet-wide, Rick's Q5) or an
          exact project name

    Ensures:
        - returns { created, closed, ratio, verdict, room_for, close_needed, headroom,
          window_hours, allow_below, window_start, project }
        - 🔴 `room_for` IS THE DISPLAY NUMBER AND `headroom` IS NOT. They differ by
          exactly one wherever there is any room, and that is Rick's ruling of
          2026-09-05 13:11:13 EDT by keypress, not a defect:
              `room_for`  LOOP semantics — how many more leave the ratio under the
                          threshold AFTER they land. 0 means AT CAPACITY, STILL LEGAL and
                          renders as `FULL`; None when the gate already refuses, because
                          the honest answer past the line is negative rather than zero
              `headroom`  GATE boundary, DIAGNOSTIC ONLY — the exact count the gate
                          admits, always exactly one MORE, because the gate judges each
                          create against the counts BEFORE it lands
          WORKED EXAMPLE — created 10, closed 13, allow_below 1.00:
              `room_for` = 2   <- rendered. After 3 creates the ratio is no longer under
              `headroom` = 3   <- the gate really admits 3: create #3 is judged at
                                  12/13 = 0.92 BEFORE it lands; #4 is judged at 13/13
                                  = 1.00 and refused
          ⇒ `headroom` == `room_for` + 1 wherever there is any room. They agree ONLY when
            both are 0. Re-derive rather than trusting the sentence — it is pinned by
            test_the_badge_under_reports_the_gate_by_exactly_one.
          ⚠️ An earlier version of this docstring said the number "cannot disagree with
          the behaviour it describes". That is now true of `headroom` ONLY. The DISPLAY
          disagrees by one, deliberately and by ruling — it errs toward reporting no room
          while the gate would still accept one, which is the safer error for a
          moratorium. A consumer that switches to `headroom` also destroys the `FULL`
          state; the number and the word are one choice, not two
        - both are obtained by ASKING `ratio_gate_advisory` and counting, never by
          re-deriving its comparison here, so neither can drift from the gate's rules —
          the ruled offset is a stated constant applied to the gate's own answer
        - None means no bound was found; P0 and the mirror lane are exempt from the gate
          and so are not described by either number at all
        - `close_needed` is closures required before the gate would admit again; 0 when it
          already admits, None when no number of closures opens it (a zero threshold is
          shut for everything, so naming a target would name one that does not exist)
        - `ratio` is created ÷ closed to 2dp, or None when closed == 0 — None rather than
          a sentinel number, so a consumer cannot accidentally compare it. The header
          renders None as an em dash
        - `verdict` is computed HERE, not by each consumer, so the header and the gate
          cannot drift apart:
              closed == 0 and created == 0  -> "idle"    an idle window is not a failing
                                                         window
              closed == 0 and created  > 0  -> "refuse"  a window where nothing was
                                                         finished is exactly what the gate
                                                         is for. This is the COMMON case on
                                                         a quiet day, not an exotic
                                                         divide-by-zero
              ratio < allow_below           -> "allow"   the operator's live threshold,
                                                         echoed back in the payload
              otherwise                     -> "refuse"
        - counts come from SQL COUNT, never a page length — see
          TaskRepository.count_created_and_closed for why that is the whole reason this
          endpoint exists rather than a frontend paging the event stream

    ⚠️ THE WINDOW SIZE CAN FLIP THE VERDICT, which is why it is echoed back rather than
    assumed. Measured on the live board 2026-09-01, minutes apart:

        24h    created  10 / closed  13    ratio 0.77    allow
        168h   created 211 / closed 191    ratio 1.10    refuse

    Over a day the fleet closes faster than it files; over a week it does not. 24h is
    Rick's ruling and it stands — he holds the threshold as an operator dial and tunes it
    on criteria of his own. Recorded so a consumer showing a number also shows which
    window produced it.

    ⚠️ `dropped` IS NOT A CLOSURE (Rick's Q2), excluded in the repository. Named again
    here only so a reader of this endpoint is not surprised that clearing dead rows moves
    nothing — that exclusion is what stops the gate being defeated by deleting evidence.
    """
    # Resolved per-request so an operator move takes effect without a bounce. An
    # explicit ?window_hours= still wins — the caller asked a specific question.
    if window_hours is None: window_hours = frs.get_window_hours()
    allow_below = frs.get_allow_below()

    since = datetime.now( timezone.utc ) - timedelta( hours=window_hours )

    with get_db() as session:
        counts = TaskRepository( session ).count_created_and_closed(
            since   = since,
            project = project,
        )

    created = counts[ "created" ]
    closed  = counts[ "closed" ]

    if closed == 0:
        ratio   = None
        verdict = "idle" if created == 0 else "refuse"
    else:
        ratio   = round( created / closed, 2 )
        verdict = "allow" if ratio < allow_below else "refuse"

    # 🔴 A PROJECTION OF THE GATE, NEVER A SECOND GATE (Mr. Radio 🦉, 2026-09-05). Fed the
    # counts and the threshold THIS handler already read — not re-read, not re-counted —
    # and it asks `ratio_gate_advisory` itself rather than re-deriving the comparison.
    # Computing this in the browser, or from a second settings read, is what would let the
    # displayed number and the gate's behaviour drift apart.
    headroom     = rules.ratio_gate_headroom( created, closed, allow_below )
    close_needed = rules.ratio_gate_close_needed( created, closed, allow_below )
    room_for     = rules.ratio_loop_headroom( created, closed, allow_below )

    return {
        "created"      : created,
        "closed"       : closed,
        "ratio"        : ratio,
        "verdict"      : verdict,
        "close_needed" : close_needed,    # closures needed before the gate would admit
                                          # again; 0 when it already admits, None when no
                                          # number of closures opens it (a zero threshold
                                          # is shut for everything, so naming a target
                                          # would name one that does not exist)
        "room_for"     : room_for,        # THE BADGE RENDERS THIS ONE, and it is the
                                          # gate's number MINUS ONE by Rick's keypress
                                          # 2026-09-05 13:11:13 EDT ("Keep your three
                                          # states — badge under-reports by one").
                                          # LOOP semantics: how many more leave the
                                          # ratio under threshold AFTER they land.
                                          # 0 is the FULL state (at capacity, still
                                          # legal); None when the gate already
                                          # refuses, which is close_needed's CLOSE N.
                                          # See ratio_loop_headroom for the ruling.
        "headroom"     : headroom,        # 🔴 GATE BOUNDARY — NOT FOR DISPLAY. The exact
                                          # count of ordinary creates the gate would admit.
                                          # THE BADGE MUST NOT RENDER THIS. Rick ruled on
                                          # 2026-09-05 at 13:11:13 EDT, by keypress, on the
                                          # option labelled "Keep your three states — badge
                                          # under-reports by one": the display uses LOOP
                                          # semantics and is one LOWER than this number.
                                          # Render `room_for`. A renderer switched to this
                                          # field would also delete the `FULL` state, which
                                          # he ratified separately — the two are one choice.
                                          # KEPT RATHER THAN DROPPED because it is the only
                                          # place the gate's exact boundary is observable to
                                          # a caller, and a diagnostic that disappears is
                                          # how the next investigation starts from scratch.
                                          # None means no bound was found. NOT (created+N)
                                          # /closed < allow_below — the gate judges a
                                          # create against the counts BEFORE it lands, so
                                          # it admits one more than that algebra. See
                                          # ratio_gate_headroom for the worked example.
        "window_hours" : window_hours,
        "allow_below"  : allow_below,     # echoed for the same reason window_hours is:
                                          # a verdict cannot be checked without the
                                          # threshold that produced it
        "window_start" : since.isoformat(),
        "project"      : project,
    }


# ---------------------------------------------------------------------------
# Operator controls for the ratio: the window and the threshold.
#
# 🔴 REGISTERED ABOVE `/tasks/{task_id}` FOR THE SAME REASON `/tasks/flow-ratio` IS.
# These are 4-segment paths and that route is 3, so it cannot swallow them today — but
# the habit is the control, not the arithmetic. `test_no_literal_route_is_shadowed_by_a_
# parameterised_sibling.py` checks the whole route table on every run.
# ---------------------------------------------------------------------------

class FlowRatioSettingsRequest( BaseModel ):
    """
    A PATCH of the operator's ratio controls. Every field is optional.

    ⚠️ OMITTING A FIELD LEAVES IT ALONE — it does not reset it. An operator dragging the
    threshold slider must not silently revert a window someone else set, so this is a
    partial update rather than a replace.
    """
    model_config = ConfigDict( extra="forbid" )

    window_hours : Optional[ int ]   = Field(
        default=None, ge=frs.MIN_WINDOW_HOURS, le=frs.MAX_WINDOW_HOURS,
        description="Rolling window the ratio is counted over, in hours."
    )
    allow_below  : Optional[ float ] = Field(
        default=None, ge=frs.MIN_ALLOW_BELOW, le=frs.MAX_ALLOW_BELOW,
        description="The gate opens on a ratio STRICTLY BELOW this number."
    )


@router.get(
    "/tasks/flow-ratio/settings",
    summary     = "Read the operator's live ratio window + threshold",
    description = "Returns the live { window_hours, allow_below } and, for each, whether it "
                  "comes from an operator override or from config. Same auth as /api/tasks."
)
def get_flow_ratio_settings(
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ],
):
    """
    Serve the live ratio controls and their provenance.

    Ensures:
        - returns { window_hours, allow_below, window_source, threshold_source }
        - the SOURCE fields are included deliberately: a number alone cannot tell an
          operator whether the INI is in force or is being masked by a saved override,
          which is the one confusion a two-layer scheme reliably creates
    """
    return frs.current_settings()


@router.patch(
    "/tasks/flow-ratio/settings",
    summary     = "Set the operator's ratio window + threshold",
    description = "Persists an override for either value. ADMIN ONLY — this moves the "
                  "threshold the CREATE gate refuses on, fleet-wide, so it is a policy "
                  "change and not a display preference."
)
def patch_flow_ratio_settings(
    request_body : FlowRatioSettingsRequest,
    admin_user   : Dict = Depends( require_admin ),
):
    """
    Persist an operator override for the ratio window and/or threshold.

    🔴 ADMIN-GATED ON PURPOSE, AND THIS IS A JUDGEMENT CALL WORTH CHALLENGING. The READ
    above uses the same guard as the board itself, because anyone who can see the ratio
    should see the threshold that produced it. The WRITE moves the number that refuses
    other people's creates, so it is gated harder. If the operator who needs the slider
    turns out not to hold the admin role, this answers 403 — loudly, and fixable by
    granting the role. The alternative failure, a quietly open door onto the fleet's
    gate, is the one you cannot see.

    Requires:
        - an authenticated ADMIN
        - at least one of window_hours / allow_below

    Ensures:
        - a supplied value is persisted so it survives a bounce and is visible to every
          server sharing this data root; an omitted one is left alone (PATCH, not replace)
        - returns the LIVE settings after the write, never an echo of the request — the
          two differ whenever a value clamps, and a UI echoing its own request would then
          display a number the gate is not using
        - 422 on a body naming neither field, rather than a silent no-op reported as
          success

    Raises:
        - HTTPException 422 when the body changes nothing, or a value is not a number
        - HTTPException 500 when the override cannot be persisted. NOT swallowed: a
          slider that reports success while saving nothing is the exact failure this
          endpoint exists to prevent
    """
    if request_body.window_hours is None and request_body.allow_below is None:
        raise HTTPException(
            status_code = 422,
            detail      = "supply window_hours, allow_below, or both — a body naming "
                          "neither would change nothing, and reporting success for that "
                          "is how a slider appears to work while doing nothing."
        )

    try:
        settings = frs.set_overrides(
            window_hours = request_body.window_hours,
            allow_below  = request_body.allow_below,
        )
    except ValueError as error:
        raise HTTPException( status_code=422, detail=str( error ) )
    except OSError as error:
        raise HTTPException(
            status_code = 500,
            detail      = f"could not persist the ratio settings ({error}). The live values "
                          f"are UNCHANGED — nothing was applied."
        )

    print(
        f"[task] flow-ratio settings set by {admin_user.get( 'email', admin_user )}: "
        f"window={settings[ 'window_hours' ]}h allow_below={settings[ 'allow_below' ]}"
    )
    return settings


@router.delete(
    "/tasks/flow-ratio/settings",
    summary     = "Clear the operator override, returning to config",
    description = "Removes the persisted override so the INI defaults govern again. ADMIN ONLY."
)
def delete_flow_ratio_settings(
    admin_user : Dict = Depends( require_admin ),
):
    """
    Drop the persisted override so the INI values govern again.

    Ensures:
        - clearing an already-clear setting is a no-op, not an error
        - returns the live settings after the reset, so the caller sees what the INI
          actually says rather than assuming it matches the shipped fallback
    """
    settings = frs.clear_overrides()
    print( f"[task] flow-ratio override cleared by {admin_user.get( 'email', admin_user )}" )
    return settings



def _serialize_ticket( ticket ):
    """
    One promotion ticket, as the caller polling it needs to see it.

    Ensures:
        - `state` is always present — it is the whole answer
        - `response_body` is included ONLY when it exists, and is the EXACT
          `{ item, event }` a synchronous 200 would have carried, serialized inside the
          transaction that wrote it rather than re-read here (design 5.4.1)
        - `refusal` carries the reason for BOTH `refused` and `superseded`, which are
          different facts and must not be collapsed by a reader
        - `answer_by` (Rick's answer window) and `resolves_by` (the stall deadline) ride
          together with `deadlines` saying which is which (row dbe42964); `answer_by` is
          null on a ticket minted before the column existed
    """
    return {
        "ticket_id"       : str( ticket.id ),
        "task_id"         : str( ticket.item_id ),
        "to_status"       : ticket.to_status,
        "requested_by"    : ticket.requested_by,
        "requested_at"    : ticket.requested_at.isoformat() if ticket.requested_at else None,
        "answer_by"       : ticket.answer_by.isoformat()    if ticket.answer_by    else None,
        "resolves_by"     : ticket.resolves_by.isoformat()  if ticket.resolves_by  else None,
        "deadlines"       : promotion_resolver.DEADLINES_NOTE,
        "state"           : ticket.state,
        "approval_source" : ticket.approval_source,
        "ask_status"      : ticket.ask_status,
        "refusal"         : ticket.refusal,
        "resolved_at"     : ticket.resolved_at.isoformat()  if ticket.resolved_at  else None,
        "response_body"   : ticket.response_body,
    }


@router.get(
    "/tasks/promotions",
    summary     = "List promotion tickets - the visibility surface for pending asks",
    description = "Defaults to state=pending: what is waiting on Rick right now. The "
                  "task row itself cannot provide this - a row awaiting promotion is "
                  "still not_approved, which task_store_rules puts outside every board "
                  "query BY DESIGN. Auth: X-API-Key or Bearer JWT."
)
def list_promotion_tickets(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    state: Optional[ str ] = Query( default=promotion_resolver.TICKET_PENDING,
                                    description="ticket state, or 'all'" ),
    limit: int             = Query( default=50, ge=1, le=500 ),
):
    """
    The pending listing that design 4 says the task row cannot be.

    🔴 IT IS THE SUPPLEMENT, NEVER THE MECHANISM. Mr. Radio's measurement on this row is
    why: all three rows Rick was listed on had already passed their chase times and
    rejoined the owed count silently, and nothing fired at him. A state that expires into
    a list is a state nobody looks at. The stalled path PUSHES an urgent notification;
    this endpoint is for somebody who came to ask.

    Ensures:
        - returns { tickets, count }, newest first
        - state='all' lists every state; any other value filters exactly
    """
    with get_db() as session:
        query = session.query( TaskPromotionTicket )
        if state and state != "all":
            query = query.filter( TaskPromotionTicket.state == state )
        rows = ( query.order_by( TaskPromotionTicket.requested_at.desc() )
                      .limit( limit ).all() )
        tickets = [ _serialize_ticket( row ) for row in rows ]
    return { "tickets": tickets, "count": len( tickets ) }


@router.get(
    "/tasks/promotions/{ticket_id}",
    summary     = "Get one promotion ticket - the caller's poll target",
    description = "The outcome of an asynchronous promotion. A resolved ticket carries "
                  "response_body, the exact { item, event } a synchronous 200 would "
                  "have returned. Auth: X-API-Key or Bearer JWT."
)
def get_promotion_ticket(
    ticket_id: uuid.UUID,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
):
    """
    🔴 THIS ENDPOINT IS THE CONDITION OF THE RULING, NOT A CONVENIENCE. Maria's binding
    requirement on going asynchronous: the caller must be able to OBSERVE the resolution.
    A 202 whose ticket id nothing can read is the same defect with the waiting moved
    somewhere nobody looks - so the 202 and this door are one feature, and shipping the
    first without the second would have met the letter of the ruling and none of it.

    Ensures:
        - 404 when no such ticket exists - never an empty success
        - returns the ticket's full state including response_body when resolved
    """
    with get_db() as session:
        ticket = session.get( TaskPromotionTicket, ticket_id )
        if ticket is None:
            raise HTTPException( status_code=404,
                                 detail=f"promotion ticket {ticket_id} not found" )
        return _serialize_ticket( ticket )


# 🔴 REGISTERED ABOVE `/tasks/{task_id}` ON PURPOSE, AND THE ORDER IS LOAD-BEARING.
# Starlette matches on path AND method in registration order, so a literal
# `/tasks/promotions` declared AFTER the parameterised `/tasks/{task_id}` would be
# swallowed by it and answer 422 on a ticket_id that is not a task UUID - which is
# exactly how `/api/tasks/flow-ratio` answered 422 for an evening. The two-segment
# `/tasks/promotions/{ticket_id}` could not be shadowed by a one-segment sibling, but it
# sits here with its twin so the pair cannot be split by a later edit.
@router.get(
    "/tasks/{task_id}",
    summary     = "Get one task-store item",
    description = "Returns one item by full UUID or by an 8-hex id prefix (the form every "
                  "brief and cross-reference uses). An ambiguous prefix returns 422 naming "
                  "every candidate — never a silent first match. Prefix resolution is READ-"
                  "ONLY; mutating routes require a full UUID. Auth: X-API-Key or Bearer JWT."
)
def get_task(
    task_id: str,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Get one item by full UUID or hex id prefix.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - task_id is a full UUID or a hex prefix of >= 4 characters

    Ensures:
        - 404 when nothing matches, 422 when the ref is junk or the prefix is
          ambiguous (naming every candidate)
        - returns the serialized item otherwise
    """
    with get_db() as session:
        repo = TaskRepository( session )
        item = _resolve_task_ref( repo, task_id )
        # Blocker resolution for the single-row read too (row 00a6bde2). `task_get` is
        # what the row's own body tells a builder to use to re-derive a blocker's status
        # by hand; a flag present on the list surface and absent here would send exactly
        # that reader to the one projection that cannot answer the question.
        return _serialize_item( item, _resolve_blocker_statuses( repo, [ item ] ) )


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


# ---------------------------------------------------------------------------
# Epic story text — GET /api/epic-stories
#
# Rick's ruling 2026-08-24 (mini-plan §5): the hand-maintained epic-story file
# MOVES into this repo and is served from the router that already serves the
# rows. The task store is this repo's; `correlation_key` — where the epic lives
# — is a field on this repo's rows; twelve of the fourteen epics are lupin work.
# The file sat in planning-is-prompting because that is where the board
# generator happened to be written, not because anything about it belonged
# there.
#
# One consumer today is the notifications client's Epic Board accordion; the
# board generator (planning-is-prompting workflow/scripts/generate_epic_board.py)
# repoints at this endpoint separately — until it does, the JSON exists in BOTH
# places, which is stated here rather than left for a reader to discover.
#
# Plan: src/rnd/v0.2.0/2026.08.24-epic-accordion-mini-plan.md §5
# ---------------------------------------------------------------------------

EPIC_STORIES_REL_PATH = "/src/conf/epic-stories.json"


@router.get(
    "/epic-stories",
    summary     = "Get the hand-maintained epic story text",
    description = "Returns src/conf/epic-stories.json as-is: a map of "
                  "`epic:<slug>` -> { title, story }, plus a `_README` key. "
                  "Hand-maintained — a manager minting a new epic adds its line "
                  "in the same turn. An epic with NO entry is not an error: the "
                  "consumer renders a de-slugged key and no story, which is the "
                  "visible nudge to write one. Auth: X-API-Key or Bearer JWT "
                  "(the same guard as /api/tasks)."
)
def get_epic_stories(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Serve the epic story text that annotates the epic-grouped board.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT — same guard as /api/tasks)

    Ensures:
        - returns { stories: {...}, count } where `stories` is the file verbatim
          and `count` counts the real epic keys (the `_README` key excluded)
        - a MISSING file returns { stories: {}, count: 0 } with 200, NEVER a 5xx:
          a missing story file must degrade the board to de-slugged names, not
          take the panel down. The absence is the nudge, and the nudge must not
          be an outage
        - an UNPARSEABLE file raises 500 — that is a real defect a human edited
          into the file, and it must be loud rather than silently empty
    """
    path = cu.get_project_root() + EPIC_STORIES_REL_PATH
    if not os.path.exists( path ):
        return { "stories": {}, "count": 0 }
    try:
        with open( path, "r", encoding="utf-8" ) as handle:
            stories = json.load( handle )
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code = 500,
            detail      = f"epic-stories.json is not valid JSON: {error}"
        )
    if not isinstance( stories, dict ):
        raise HTTPException(
            status_code = 500,
            detail      = "epic-stories.json must contain a JSON object at its root"
        )
    real_keys = [ key for key in stories.keys() if not key.startswith( "_" ) ]
    return { "stories": stories, "count": len( real_keys ) }


