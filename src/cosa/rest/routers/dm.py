"""
DM API — `/api/dm/<verb>` notification-native AI↔AI direct messaging.

One coherent `/api/dm` namespace whose verb sub-routes each mirror a `dm_<verb>`
cosa-voice MCP tool 1:1. Phase 1 ships `POST /api/dm/send` (the relocated,
renamed legacy peer-DM endpoint); Phase 2 adds the siblings `/respond`, `/get`,
`/list` against the same router.

A peer DM is an ordinary notification carrying the body INLINE with
direction="ai_to_ai" — no commons board, no claim-check, no commons_read
re-fetch. Resolution reuses the commons same-user persona→session resolver;
delivery rides job_id routing to the recipient's cc-listener.

Design:
    src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md (namespace)
    src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md (send semantics)
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Annotated, Literal
import asyncio
import uuid
from datetime import datetime

# Import dependencies and services
from ..notification_fifo_queue import NotificationFifoQueue
from ..middleware.api_key_auth import require_api_key_or_jwt
from ..db.database import get_db
from ..db.repositories.notification_repository import NotificationRepository
# Central EDT-stamp formatter (2026-06-24): the ONE owner of Rick's bracketed
# outreach prefix "[YYYY.MM.DD at HH:MM:SS]", shared with the arbiter ping path so a
# reader cannot tell a DM's stamp from an arbiter ping's stamp.
from cosa.utils.edt_timestamp import format_edt_timestamp, is_already_stamped
# The notification queue dependency lives with the notifications router; reuse it
# so /api/dm/send pushes onto the same FIFO queue as /api/notify.
from .notifications import get_notification_queue

router = APIRouter( prefix="/api/dm", tags=["dm"] )


class DmSendRequest( BaseModel ):
    """
    POST /api/dm/send request body — notification-native AI↔AI DM.

    The recipient is addressed by persona name (preferred) or explicit session
    id; resolution is same-user scoped. The message body travels INLINE (no
    claim-check). Threading is carried by `reply_to` (the message being answered)
    and `thread_id` (conversation correlation; defaults to a fresh id server-side
    when omitted). `sender_persona`/`sender_icon` carry the SENDER's identity so
    the recipient can frame it as "[DM from <persona> <icon>]".
    """
    sender_session_id    : str             = Field( ..., min_length=1, max_length=128 )
    body                 : str             = Field( ..., min_length=1 )
    recipient_session_id : Optional[ str ] = Field( default=None, min_length=1, max_length=128 )
    recipient_persona    : Optional[ str ] = Field( default=None, min_length=1, max_length=64 )
    sender_persona       : Optional[ str ] = Field( default=None, max_length=64 )
    sender_icon          : Optional[ str ] = Field( default=None, max_length=16 )
    reply_to             : Optional[ str ] = Field( default=None, max_length=64 )
    thread_id            : Optional[ str ] = Field( default=None, max_length=64 )


def _persist_dm_send_sync(
    sender_id, recipient_user_id, message, direction,
    sender_persona, sender_icon, reply_to, thread_id, job_id
):
    """
    Synchronous DB persist for a peer DM — run OFF the event loop via
    asyncio.to_thread. The notifications table IS the audit substrate (no commons
    board mirror), so the body + direction + provenance + threading land in
    first-class columns.

    Requires:
        - recipient_user_id is a UUID string (same-user scoping → the sender's user)

    Ensures:
        - creates the Notification row with direction='ai_to_ai' + DM fields
        - returns the new notification id (str)

    Raises:
        - propagates DB errors to the caller (handled there as non-fatal)
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        db_notification = repo.create_notification(
            sender_id      = sender_id,
            recipient_id   = uuid.UUID( recipient_user_id ),
            message        = message,
            type           = "user_initiated_message",
            priority       = "medium",
            job_id         = job_id,
            direction      = direction,
            sender_persona = sender_persona,
            sender_icon    = sender_icon,
            reply_to       = reply_to,
            thread_id      = thread_id,
        )
        return str( db_notification.id )


def execute_dm_send(
    *,
    authenticated_user_id,
    body,
    notification_queue,
    resolve_recipient_fn,
    build_sender_id,
    persist_fn,
    new_id_fn = None,
    now_fn    = None,
):
    """
    Pure-logic core for POST /api/dm/send — notification-native AI↔AI DM.

    Resolves the recipient (same-user scoped), persists the DM to the
    notifications table (direction='ai_to_ai' + body inline + sender provenance
    + threading), then pushes it to the recipient session's listener via job_id
    routing. No commons board, no claim-check, no watcher.

    The outbound body is prefixed with Rick's central EDT stamp
    "[YYYY.MM.DD at HH:MM:SS] " (2026-06-24) — the SAME bracketed prefix the arbiter
    pings carry, sourced from the shared cosa.utils.edt_timestamp formatter. This is
    the single server-side DM chokepoint (send AND respond reuse this core), so the
    stamp lands on EVERY peer DM in every direction. The arbiter pings ride a
    DISJOINT path (CommonsStore, not /api/dm/send) and are NOT re-stamped here.

    Requires:
        - body is a DmSendRequest
        - resolve_recipient_fn( recipient_session_id, recipient_persona,
          authenticated_user_id ) -> {"http_status":200,"session_id","persona_name"}
          OR {"http_status":422,"detail"}
        - build_sender_id( sender_session_id ) -> sender_id str
        - persist_fn( ... ) -> db notification id str
        - now_fn (if given) is a 0-arg callable returning an aware datetime — a
          TEST-ONLY seam for a deterministic stamp; production leaves it None and
          the central formatter stamps the real UTC-now instant

    Ensures:
        - 422 (recipient unresolved) is returned unchanged for AI self-correction
        - 201 persists + pushes the ai_to_ai notification (body EDT-prefixed in BOTH
          the persisted row and the pushed message) and returns
          {http_status, message_id, thread_id, recipient_session, recipient_persona, dispatched}
        - thread_id defaults to the fresh message_id when not supplied (new thread)
        - threading / reply_to / sender persona+icon metadata are UNTOUCHED — only
          the body string is prefixed

    Raises:
        - None (DB/push errors propagate to the route)
    """
    if new_id_fn is None:
        new_id_fn = lambda: str( uuid.uuid4() )

    resolution = resolve_recipient_fn(
        recipient_session_id  = body.recipient_session_id,
        recipient_persona     = body.recipient_persona,
        authenticated_user_id = authenticated_user_id,
    )
    if resolution[ "http_status" ] != 200:
        return { "http_status": resolution[ "http_status" ], "detail": resolution[ "detail" ] }

    target_session_id = resolution[ "session_id" ]
    target_persona    = resolution.get( "persona_name" )
    sender_id         = build_sender_id( body.sender_session_id )
    job_id            = target_session_id[ :8 ]

    message_id = new_id_fn()
    thread_id  = body.thread_id or message_id

    # Central EDT prefix on the outbound body — identical bracketed shape to the
    # arbiter pings (f"[{stamp}] {body}"). now_fn is the test-only deterministic seam.
    # IDEMPOTENT (bug f49a8b34 / bc8d9d82): skip the prepend when the body ALREADY
    # leads with a bracketed stamp (an arbiter ping pre-stamped via _route, then
    # pushed through this chokepoint) — else we'd produce a "[push-ts] [compose-ts]"
    # double. An un-stamped body (human dm_send) still gets the central stamp.
    stamped_body = body.body if is_already_stamped( body.body ) else \
        f"{format_edt_timestamp( dt=now_fn() if now_fn is not None else None )} {body.body}"

    db_id = persist_fn(
        sender_id         = sender_id,
        recipient_user_id = authenticated_user_id,
        message           = stamped_body,
        direction         = "ai_to_ai",
        sender_persona    = body.sender_persona,
        sender_icon       = body.sender_icon,
        reply_to          = body.reply_to,
        thread_id         = thread_id,
        job_id            = job_id,
    )

    notification_queue.push_notification(
        message        = stamped_body,
        type           = "user_initiated_message",
        priority       = "medium",
        id             = db_id or message_id,
        sender_id      = sender_id,
        job_id         = job_id,
        user_id        = authenticated_user_id,
        suppress_ding  = True,
        direction      = "ai_to_ai",
        sender_persona = body.sender_persona,
        sender_icon    = body.sender_icon,
        reply_to       = body.reply_to,
        thread_id      = thread_id,
    )

    return {
        "http_status"       : 201,
        "message_id"        : db_id or message_id,
        "thread_id"         : thread_id,
        "recipient_session" : target_session_id,
        "recipient_persona" : target_persona,
        "dispatched"        : True,
    }


@router.post(
    "/send",
    summary     = "Send a notification-native AI↔AI direct message (body inline)",
    description = "Notification-native peer DM: resolves the recipient persona/session (same-user scoped) and delivers the message body INLINE via a direction='ai_to_ai' notification — no commons board, no claim-check, no commons_read re-fetch. Returns 201 with {message_id, thread_id}, or 422 (RecipientResolutionError) if the recipient can't be resolved.",
)
async def post_dm_send(
    body: DmSendRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    notification_queue: NotificationFifoQueue = Depends( get_notification_queue ),
) -> JSONResponse:
    # Lazy import to avoid a commons<->notifications import cycle and to read the
    # commons module's runtime-initialized active-session threshold.
    from cosa.rest.routers import commons as _commons
    from lupin_cli.claude_code.hooks.lib.session_bridge import (
        find_active_sessions, build_sender_id_for_cc,
    )

    def _resolve( recipient_session_id, recipient_persona, authenticated_user_id ):
        return _commons._resolve_dm_recipient(
            recipient_session_id             = recipient_session_id,
            recipient_persona                = recipient_persona,
            authenticated_user_id            = authenticated_user_id,
            # require_persona=False so a null-persona worker (pool exhausted /
            # allocation raced) is still addressable by its session_id — it has
            # no persona name to resolve by, so excluding it makes it a black
            # hole for inbound DMs (bug d57dbfea). The persona-name resolution
            # path inside _resolve_dm_recipient skips persona-less candidates.
            raw_sessions_fn                  = lambda: find_active_sessions( require_persona=False ),
            bridge_loader                    = _commons._load_bridge_fields,
            active_session_threshold_seconds = getattr( _commons, "_active_session_threshold_seconds", 600.0 ),
        )

    # FM-7 mitigation: recipient resolution + DB persist are blocking I/O — run
    # OFF the shared event loop (mirrors register-question / notify).
    result = await asyncio.to_thread(
        execute_dm_send,
        authenticated_user_id = authenticated_user_id,
        body                  = body,
        notification_queue    = notification_queue,
        resolve_recipient_fn  = _resolve,
        build_sender_id       = build_sender_id_for_cc,
        persist_fn            = _persist_dm_send_sync,
    )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )


# ═════════════════════════════════════════════════════════════════════════════
# Phase 2 — DM verb family: /respond, /get, /list (Clayton 😎)
#
# Additive routes on the SAME `/api/dm` router. `respond` reuses the send
# execution core verbatim (it is send-with-mandatory-threading); `get`/`list`
# are read-path cores backed by NotificationRepository.get_by_id /
# get_dm_thread / get_dm_inbox. Design: 2026.06.16-dm-api-namespace-design.md §3.
# ═════════════════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/dm/respond — threaded reply (reply_to + thread_id REQUIRED)
#
# A "respond" is a "send" whose threading is mandatory: you cannot reply without
# naming the message you answer (reply_to) and the conversation it belongs to
# (thread_id). The send execution core (execute_dm_send) is reused verbatim —
# DmRespondRequest duck-types as the DmSendRequest `body` it consumes.
# ─────────────────────────────────────────────────────────────────────────────

class DmRespondRequest( BaseModel ):
    """
    POST /api/dm/respond request body — a threaded peer-DM reply.

    Identical to DmSendRequest except `reply_to` and `thread_id` are REQUIRED:
    a reply must name the message it answers and the conversation it continues.
    """
    sender_session_id    : str             = Field( ..., min_length=1, max_length=128 )
    body                 : str             = Field( ..., min_length=1 )
    reply_to             : str             = Field( ..., min_length=1, max_length=64 )
    thread_id            : str             = Field( ..., min_length=1, max_length=64 )
    recipient_session_id : Optional[ str ] = Field( default=None, min_length=1, max_length=128 )
    recipient_persona    : Optional[ str ] = Field( default=None, min_length=1, max_length=64 )
    sender_persona       : Optional[ str ] = Field( default=None, max_length=64 )
    sender_icon          : Optional[ str ] = Field( default=None, max_length=16 )


@router.post(
    "/respond",
    summary     = "Reply to a peer DM in-thread (body inline, reply_to + thread_id required)",
    description = "Threaded peer-DM reply: a /api/dm/send whose `reply_to` (message answered) and `thread_id` (conversation) are mandatory. Resolves the recipient (same-user scoped), persists a direction='ai_to_ai' notification carrying the body inline + threading, and pushes it to the recipient session. Returns 201 with {message_id, thread_id}, or 422 if the recipient can't be resolved.",
)
async def post_dm_respond(
    body: DmRespondRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    notification_queue: NotificationFifoQueue = Depends( get_notification_queue ),
) -> JSONResponse:
    # Mirrors post_dm_send exactly — respond shares send's resolution + execution
    # core; only the request model differs (threading mandatory).
    from cosa.rest.routers import commons as _commons
    from lupin_cli.claude_code.hooks.lib.session_bridge import (
        find_active_sessions, build_sender_id_for_cc,
    )

    def _resolve( recipient_session_id, recipient_persona, authenticated_user_id ):
        return _commons._resolve_dm_recipient(
            recipient_session_id             = recipient_session_id,
            recipient_persona                = recipient_persona,
            authenticated_user_id            = authenticated_user_id,
            # require_persona=False — null-persona workers stay reachable by
            # session_id on the reply path too (bug d57dbfea); see post_dm_send.
            raw_sessions_fn                  = lambda: find_active_sessions( require_persona=False ),
            bridge_loader                    = _commons._load_bridge_fields,
            active_session_threshold_seconds = getattr( _commons, "_active_session_threshold_seconds", 600.0 ),
        )

    result = await asyncio.to_thread(
        execute_dm_send,
        authenticated_user_id = authenticated_user_id,
        body                  = body,
        notification_queue    = notification_queue,
        resolve_recipient_fn  = _resolve,
        build_sender_id       = build_sender_id_for_cc,
        persist_fn            = _persist_dm_send_sync,
    )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )


# ─────────────────────────────────────────────────────────────────────────────
# Shared serialization for the read verbs (get / list)
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_dm( notification ):
    """
    Serialize a peer-DM Notification row to the wire shape returned by get/list.

    Requires:
        - notification has the ai_to_ai notification columns (id, thread_id,
          reply_to, sender_*, message, direction, state, job_id, created_at)

    Ensures:
        - returns a JSON-safe dict; created_at is ISO 8601 (or None)
        - the body is exposed as "body" (the message column) to match the
          dm_send/dm_respond request vocabulary
        - `recipient_session_hash8` names the ADDRESSEE explicitly. It is the same
          value as `job_id` (which on an ai_to_ai row IS the recipient's 8-char
          session hash), surfaced under a name that says what it is. Before this,
          a reader had to know that a field called "job_id" meant "who this was
          sent to" — and a reader who did NOT know it could conclude only that a
          DM was VISIBLE to them, never that it was ADDRESSED to them. That gap
          produced a false cross-session finding on 2026-07-16 (row 2565956b).
        - 🔴 THE NAME CARRIES ITS SHAPE ON PURPOSE. `execute_dm_send` returns a
          key called `recipient_session` holding the FULL session id, while what
          is PERSISTED is `target_session_id[ :8 ]`. Calling this field
          `recipient_session` too would have given one well-chosen name two value
          shapes — a consumer comparing them would never match, and feeding the
          send receipt back as a list filter would silently return zero rows.
          This row exists because a column named `recipient_id` does not hold a
          recipient; shipping a second name that means two things would have been
          the same defect in miniature. The `_hash8` suffix makes the shape part
          of the name. (The send response is deliberately NOT truncated to match:
          narrowing a field this fix does not own would discard information its
          consumers may rely on.)
        - `job_id` is retained unchanged for the existing consumers that already
          filter on it; this is an added name, not a rename.
    """
    return {
        "message_id"              : str( notification.id ),
        "thread_id"               : notification.thread_id,
        "reply_to"                : notification.reply_to,
        "sender_id"               : notification.sender_id,
        "sender_persona"          : notification.sender_persona,
        "sender_icon"             : notification.sender_icon,
        "body"                    : notification.message,
        "direction"               : notification.direction,
        "state"                   : notification.state,
        "job_id"                  : notification.job_id,
        "recipient_session_hash8" : notification.job_id,
        "created_at"              : notification.created_at.isoformat() if notification.created_at is not None else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/dm/get — fetch one DM by id (same-user scoped, DM-only)
# ─────────────────────────────────────────────────────────────────────────────

def execute_dm_get( *, message_id, authenticated_user_id, fetch_fn ):
    """
    Pure-logic core for GET /api/dm/get — fetch a single peer DM by id.

    Requires:
        - message_id: the DM's notification id (string; must parse as a UUID)
        - authenticated_user_id: the caller's user uuid (string) — scoping anchor
        - fetch_fn(uuid.UUID) -> Notification | None

    Ensures:
        - 400 if message_id is not a valid UUID
        - 404 if no row, or the row belongs to another user, or is not a peer DM
          (direction != 'ai_to_ai') — never leaks non-DM / cross-user rows
        - 200 with the serialized DM otherwise

    Raises:
        - None (DB errors propagate from fetch_fn to the route)
    """
    try:
        mid = uuid.UUID( message_id )
    except ( ValueError, AttributeError, TypeError ):
        return { "http_status": 400, "detail": f"invalid message_id: {message_id!r} (expected a UUID)" }

    notification = fetch_fn( mid )
    if notification is None:
        return { "http_status": 404, "detail": "DM not found" }

    # Same-user scope + DM-only: do not leak another user's row or a non-DM row.
    if str( notification.recipient_id ) != authenticated_user_id or notification.direction != "ai_to_ai":
        return { "http_status": 404, "detail": "DM not found" }

    return { "http_status": 200, **_serialize_dm( notification ) }


@router.get(
    "/get",
    summary     = "Fetch a single peer DM by message id",
    description = "Returns one direction='ai_to_ai' DM by its message id, scoped to the caller. 404 if it does not exist, is not a DM, or belongs to another user; 400 if message_id is not a UUID.",
)
async def get_dm(   # pragma: no cover
    message_id: str,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
) -> JSONResponse:
    def _work():
        # Run the core INSIDE the session so _serialize_dm reads live (non-expired)
        # ORM attributes.
        with get_db() as session:
            repo = NotificationRepository( session )
            return execute_dm_get(
                message_id            = message_id,
                authenticated_user_id = authenticated_user_id,
                fetch_fn              = repo.get_by_id,
            )

    result = await asyncio.to_thread( _work )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/dm/list — list / poll a thread (thread_id) or the inbox (no thread_id)
# ─────────────────────────────────────────────────────────────────────────────

_DM_LIST_MAX_LIMIT = 200


DM_LIST_SCOPES = ( "session", "account" )

# The persisted addressee is `target_session_id[ :8 ]`, so every predicate built
# from a caller-supplied id must be cut to the same width before it is compared.
_SESSION_HASH_WIDTH = 8


def resolve_dm_list_scope( session_id, scope ):
    """
    Decide the effective addressee filter for a /api/dm/list read.

    The route authenticates a USER, not a session — that is the whole reason this
    resolution exists. The caller must TELL us which session it is; the server
    cannot derive it from the credential. Absence therefore means "I did not ask
    to be scoped", which must stay account-wide so the pre-existing
    client-side-filtering consumer keeps working untouched.

    🔴 NORMALIZES THE WIDTH, AND THAT IS THE POINT. The addressee is persisted as
    an 8-char prefix, but the most natural thing a caller has in hand is a FULL
    session id — `execute_dm_send` hands one back under `recipient_session`.
    Comparing a full uuid against an 8-char column matches nothing, so the
    obvious move (feed the send receipt back in) would return ZERO ROWS and look
    like "no DMs" rather than like a mistake. Truncating here makes both widths
    work. A filter that silently returns nothing for a well-formed input is worse
    than one that rejects it, and this one cannot tell the difference — so it
    accepts both instead of failing quietly on one.

    🔴 AND WHAT IT CANNOT NORMALIZE, IT REJECTS OUT LOUD. An id SHORTER than the
    persisted width can never equal an 8-char column value, so filtering on it
    would return zero rows — and a silent zero is indistinguishable from "you
    have no messages." That is the same failure shape as the row itself: a
    plausible small answer to a question the resolver never understood. So a
    too-short id is a 400, not an empty list. The caller learns it asked wrong
    instead of concluding its inbox is empty.

    Requires:
        - session_id: the caller's session id (full or 8-char), or None/""
        - scope: "session" (default), "account", or None

    Ensures:
        - Returns ( recipient_session|None, effective_scope_label, error|None )
        - a supplied session_id is stripped and TRUNCATED to 8 chars, so a full
          uuid and its own 8-char prefix resolve identically
        - a stripped session_id SHORTER than 8 chars returns an error string —
          it cannot match, and must not fail as an empty result
        - scope="account" ALWAYS yields None — an explicit, auditable wide read
        - a missing/blank session_id yields None regardless of scope, and the
          label reports "account", never a session scope the server did not apply
          (the label must never claim a narrowing that did not happen)
        - Never raises

    Args:
        session_id: caller-supplied session id, any width
        scope: requested scope label

    Returns:
        tuple: ( recipient_session|None, "session"|"account", error|None )
    """
    if scope == "account":                       return None, "account", None
    if session_id is None or not str( session_id ).strip(): return None, "account", None

    cleaned = str( session_id ).strip()
    if len( cleaned ) < _SESSION_HASH_WIDTH:
        return None, "session", (
            f"invalid 'session_id': {session_id!r} is shorter than the {_SESSION_HASH_WIDTH}-char "
            f"session hash addressees are stored under, so it can never match. Pass a full session "
            f"id or its first {_SESSION_HASH_WIDTH} characters."
        )
    return cleaned[ :_SESSION_HASH_WIDTH ], "session", None


def execute_dm_list( *, thread_id, since, limit, authenticated_user_id, thread_fn, inbox_fn,
                     session_id=None, scope="session" ):
    """
    Pure-logic core for GET /api/dm/list — list/poll a thread or the inbox.

    ⚠️ SCOPING, STATED PLAINLY BECAUSE THE OLD DOCSTRING'S "INBOX" WAS FALSE.
    `authenticated_user_id` scopes to a SERVICE ACCOUNT, not a session: peer DMs
    persist with `recipient_user_id = <the sender's own account>`, so every
    session on one account shares one pool — and since the write path currently
    stamps one and the same account for the entire fleet, that pool is the whole
    fleet's traffic. Passing `session_id` narrows to the DMs actually ADDRESSED
    to that session (see get_dm_inbox for the job_id overload + 8-char-prefix
    caveats). Omitting it keeps the legacy account-wide read, which is what the
    existing client-side-filtering hook relies on.

    Requires:
        - thread_id: a conversation id (thread view) OR None/"" (inbox view)
        - since: None, or an ISO-8601 timestamp string (poll — rows strictly newer)
        - limit: requested row cap (clamped to [1, 200])
        - authenticated_user_id: the caller's user uuid (string)
        - thread_fn(thread_id, recipient_id, since, limit, recipient_session) (asc)
        - inbox_fn(recipient_id, since, limit, recipient_session) (desc)
        - session_id: caller's 8-char session hash, or None
        - scope: "session" (default) or "account" (explicit wide read)

    Ensures:
        - 400 if `since` is a non-ISO string
        - thread view when thread_id is truthy, else inbox view
        - 400 if `session_id` is too short to ever match an addressee — a filter
          that cannot match must say so, not return an empty list that reads as
          "no messages"
        - 400 if `scope` is not one of DM_LIST_SCOPES — an unrecognized scope is
          REJECTED, never silently treated as "session". A caller who spells the
          wide read "all" must not receive a narrow one under a label saying
          "session"; that would be a quiet wrong answer to a well-formed request
        - the addressee filter is resolved by resolve_dm_list_scope; an
          account-wide read requires either scope="account" or an absent
          session_id — a wide view is never the silent outcome of a session read
        - the response ECHOES the scope actually applied, so a caller can tell
          whether it was narrowed rather than assuming it was
        - 200 with {thread_id, since, count, scope, recipient_session_hash8,
          messages}

    Raises:
        - None (DB errors propagate from the fns to the route)
    """
    if scope is not None and scope not in DM_LIST_SCOPES:
        return { "http_status": 400,
                 "detail": f"invalid 'scope': {scope!r} (expected one of {list( DM_LIST_SCOPES )})" }

    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat( since )
        except ValueError:
            return { "http_status": 400, "detail": f"invalid 'since' timestamp: {since!r} (expected ISO 8601)" }

    effective_limit = max( 1, min( int( limit ), _DM_LIST_MAX_LIMIT ) )
    recipient_uuid  = uuid.UUID( authenticated_user_id )

    recipient_session, effective_scope, scope_error = resolve_dm_list_scope( session_id, scope )
    if scope_error is not None:
        return { "http_status": 400, "detail": scope_error }

    if thread_id:
        rows = thread_fn(
            thread_id         = thread_id,
            recipient_id      = recipient_uuid,
            since             = since_dt,
            limit             = effective_limit,
            recipient_session = recipient_session,
        )
    else:
        rows = inbox_fn(
            recipient_id      = recipient_uuid,
            since             = since_dt,
            limit             = effective_limit,
            recipient_session = recipient_session,
        )

    messages = [ _serialize_dm( row ) for row in rows ]
    return {
        "http_status"             : 200,
        "thread_id"               : thread_id,
        "since"                   : since,
        "count"                   : len( messages ),
        "scope"                   : effective_scope,
        "recipient_session_hash8" : recipient_session,
        "messages"                : messages,
    }


@router.get(
    "/list",
    summary     = "List or poll peer DMs — a thread (thread_id) or the inbox",
    description = (
        "With `thread_id`, returns that conversation oldest-first; without it, returns peer DMs newest-first. "
        "SCOPING: the credential authenticates a USER (a per-project service account), NOT a session — pass "
        "`session_id` (your 8-char session hash) to narrow to DMs actually ADDRESSED to you. WITHOUT it the read "
        "is ACCOUNT-WIDE and returns every DM sent by any session on that account, including conversations you "
        "are not party to. `scope=account` explicitly requests that wide read. The response echoes the `scope` "
        "actually applied. `session_id` may be a FULL session id OR its 8-char prefix — it is normalized "
        "server-side, so the `recipient_session` from a send receipt can be fed straight back. `since` "
        "(ISO 8601) tails only newer messages (poll); `limit` is clamped to [1, 200]. "
        "400 if `since` is malformed; 422 if `scope` is not session|account."
    ),
)
async def list_dms(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    thread_id: Optional[ str ] = None,
    since: Optional[ str ] = None,
    limit: int = 50,
    session_id: Optional[ str ] = None,
    scope: Literal[ "session", "account" ] = "session",
) -> JSONResponse:
    def _work():
        with get_db() as session:
            repo = NotificationRepository( session )
            return execute_dm_list(
                thread_id             = thread_id,
                since                 = since,
                limit                 = limit,
                authenticated_user_id = authenticated_user_id,
                thread_fn             = repo.get_dm_thread,
                inbox_fn              = repo.get_dm_inbox,
                session_id            = session_id,
                scope                 = scope,
            )

    result = await asyncio.to_thread( _work )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )
