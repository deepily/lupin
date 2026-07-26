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
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest import task_store_rules as rules
from cosa.rest.task_store_owed import blocker_is_terminal, item_blocker_ids, park_reason_is_stale
from cosa.agents.utils.sender_id import canonicalize_project_name
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
from lupin_cli.claude_code.hooks.lib.manager_figure import is_manager_figure

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
    priority            : str                = Field( default="P2" )
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
        "created_ts"          : item.created_ts.isoformat(),
        "updated_ts"          : item.updated_ts.isoformat(),
    }


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
        - returns a JSON-safe dict with EXACTLY the eight glance keys; nullable
          next_chase_ts serializes as None
        - park_reason_stale is DERIVED (never stored) and ADVISORY — identical
          semantics to the full shape's, computed by the same predicate, so the
          two projections can never disagree about staleness
        - blocker_terminal is likewise DERIVED and ADVISORY, computed by the same
          predicate as the full shape's, for the same reason
    """
    return {
        "id"                : str( item.id ),
        "title"             : item.title,
        "status"            : item.status,
        "blocked_by"        : item.blocked_by,
        "next_chase_ts"     : item.next_chase_ts.isoformat() if item.next_chase_ts is not None else None,
        "priority"          : item.priority,
        "project"           : item.project,
        # body_changed_ts, matching _serialize_item — see the note there (54924128).
        "park_reason_stale" : park_reason_is_stale( item.status, item.park_reason_captured_at, item.body_changed_ts ),
        "blocker_terminal"  : blocker_is_terminal( item.status, item.blocked_by, blocker_statuses or { } ),
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

    # Mint-status whitelist (Rick 2026-07-20): a create may mint queued OR blocked.
    # blocked_by persona refs are canonicalized to the store key BEFORE validate +
    # persist (identity parity, same as the transition seam), so the value validated
    # is the value written. A queued mint carries neither field — validate_create_status
    # ignores them, and the repository forces []/None for a non-blocked mint.
    blocked_by = _canon_blocked_by( payload.blocked_by )
    _reject_if_errors( rules.validate_create_status( payload.status, blocked_by, payload.next_chase_ts ) )

    # Manager-only guard for a blocked MINT — scoped ENTIRELY to status=="blocked"
    # (G2): the queued default path never parses created_by, so existing queued
    # creates (migration-test rows, HTTP callers with no parseable session id) do
    # NOT regress. A blocked row is a deliberate hold minted on someone's behalf —
    # ONLY a manager may mint one. Resolution REUSES the ONE canonical predicate
    # is_manager_figure (G1), fail-CLOSED: a caller whose manager-hood cannot be
    # established (predicate False OR no parseable session id) is REJECTED with 403
    # (authenticated but not authorized — distinct from the 422 validation lane).
    if payload.status == "blocked":
        session_id = rules.session_id_from_created_by( payload.created_by )
        if session_id is None or not is_manager_figure( session_id ):
            raise HTTPException(
                status_code = 403,
                detail      = (
                    "only a manager may mint a 'blocked' task at create — "
                    "is_manager_figure is false or unresolved for the caller. Create "
                    "the item queued and transition it to blocked, or have a manager "
                    "mint it directly."
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

    with get_db() as session:
        repo = TaskRepository( session )
        # A blocked MINT can be born stranded exactly like a transition (row 00a6bde2).
        # Inside the transaction, and BEFORE create_item, so a rejected mint writes
        # nothing at all.
        _reject_unsatisfiable_blockers( repo, blocked_by )
        item = repo.create_item(
            item_class          = payload.item_class,
            title               = guarded_title,
            project             = _canon_project( payload.project ),
            created_by          = payload.created_by,
            authority           = payload.authority,
            body                = guarded_body,
            owner_persona       = owner_persona,
            accountable_manager = accountable_manager,
            gate_class          = payload.gate_class,
            priority            = payload.priority,
            urgency             = payload.urgency,
            status              = payload.status,
            blocked_by          = blocked_by,
            next_chase_ts       = payload.next_chase_ts,
            source_qid          = payload.source_qid,
            correlation_key     = payload.correlation_key,
            flag_suffix         = flag_marker,
        )
        result = _serialize_item( item )
        result[ "title_guard" ]  = title_guard
        result[ "persona_flag" ] = persona_flag
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

        event = repo.apply_transition(
            item          = item,
            to_status     = payload.to_status,
            actor         = payload.actor,
            authority     = payload.authority,
            receipt_refs  = payload.receipt_refs,
            next_chase_ts = payload.next_chase_ts,
            blocked_by    = blocked_by,
            reason        = payload.reason,
            park_reason   = payload.park_reason,
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
        - an over-cap `title` is soft-guarded by the SAME rules.soft_guard_title
          create uses (bug 28fc1fb4): trimmed to the cap with the overflow
          relocated into the body being written — never discarded, never a
          rejection. `title_guard` carries the advisory (None when the title was
          not touched, exactly as create reports it)
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
        if item.status in rules.TERMINAL_STATUSES:
            _reject_if_errors( [ f"item is terminal ('{item.status}') — no edits to closed history" ] )

        # ONE HELPER, BOTH DOORS (bug 28fc1fb4, 2026-07-21). This path used to set
        # `title` with NO cap, NO guard and NO advisory, while create silently cut
        # the identical string at 60 — two write paths with two contradictory
        # contracts, neither announced, and the rules-module comment claiming one
        # cap "at every layer" was false for as long as both existed. The door
        # widened when task_edit (3ac79d1d, 2026-07-21) shipped over PATCH.
        #
        # The overflow relocates into the body the PATCH is actually writing: the
        # incoming body when this same call sets one, else the row's current body.
        # Guarding against a body the caller is simultaneously replacing would file
        # the overflow into text about to be overwritten — a relocation that loses
        # the thing it just saved.
        title_guard = None
        if "title" in fields:
            effective_body = fields[ "body" ] if "body" in fields else item.body
            fields[ "title" ], guarded_body, title_guard = rules.soft_guard_title(
                fields[ "title" ], effective_body
            )
            # Only write the body back when the guard actually moved something.
            # An untouched PATCH must not manufacture a body delta in the audit
            # event — a `patched` row claiming a body change that never happened
            # is the audit trail lying about what it recorded.
            if title_guard is not None:
                fields[ "body" ] = guarded_body

        event = repo.apply_patch(
            item, fields, actor=payload.actor, authority=payload.authority,
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
            )
            return { "count": count, "breakdown": breakdown }
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
        )
        warnings = [ ]
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
