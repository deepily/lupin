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
from typing import Optional, Annotated
import asyncio
import uuid
from datetime import datetime

# Import dependencies and services
from ..notification_fifo_queue import NotificationFifoQueue
from ..middleware.api_key_auth import require_api_key_or_jwt
from ..db.database import get_db
from ..db.repositories.notification_repository import NotificationRepository
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
):
    """
    Pure-logic core for POST /api/dm/send — notification-native AI↔AI DM.

    Resolves the recipient (same-user scoped), persists the DM to the
    notifications table (direction='ai_to_ai' + body inline + sender provenance
    + threading), then pushes it to the recipient session's listener via job_id
    routing. No commons board, no claim-check, no watcher.

    Requires:
        - body is a DmSendRequest
        - resolve_recipient_fn( recipient_session_id, recipient_persona,
          authenticated_user_id ) -> {"http_status":200,"session_id","persona_name"}
          OR {"http_status":422,"detail"}
        - build_sender_id( sender_session_id ) -> sender_id str
        - persist_fn( ... ) -> db notification id str

    Ensures:
        - 422 (recipient unresolved) is returned unchanged for AI self-correction
        - 201 persists + pushes the ai_to_ai notification and returns
          {http_status, message_id, thread_id, recipient_session, recipient_persona, dispatched}
        - thread_id defaults to the fresh message_id when not supplied (new thread)

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

    db_id = persist_fn(
        sender_id         = sender_id,
        recipient_user_id = authenticated_user_id,
        message           = body.body,
        direction         = "ai_to_ai",
        sender_persona    = body.sender_persona,
        sender_icon       = body.sender_icon,
        reply_to          = body.reply_to,
        thread_id         = thread_id,
        job_id            = job_id,
    )

    notification_queue.push_notification(
        message        = body.body,
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
async def post_dm_send(   # pragma: no cover
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
async def post_dm_respond(   # pragma: no cover
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
    """
    return {
        "message_id"     : str( notification.id ),
        "thread_id"      : notification.thread_id,
        "reply_to"       : notification.reply_to,
        "sender_id"      : notification.sender_id,
        "sender_persona" : notification.sender_persona,
        "sender_icon"    : notification.sender_icon,
        "body"           : notification.message,
        "direction"      : notification.direction,
        "state"          : notification.state,
        "job_id"         : notification.job_id,
        "created_at"     : notification.created_at.isoformat() if notification.created_at is not None else None,
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


def execute_dm_list( *, thread_id, since, limit, authenticated_user_id, thread_fn, inbox_fn ):
    """
    Pure-logic core for GET /api/dm/list — list/poll a thread or the inbox.

    Requires:
        - thread_id: a conversation id (thread view) OR None/"" (inbox view)
        - since: None, or an ISO-8601 timestamp string (poll — rows strictly newer)
        - limit: requested row cap (clamped to [1, 200])
        - authenticated_user_id: the caller's user uuid (string)
        - thread_fn(thread_id, recipient_id, since, limit) -> List[Notification]  (asc)
        - inbox_fn(recipient_id, since, limit) -> List[Notification]  (desc)

    Ensures:
        - 400 if `since` is a non-ISO string
        - thread view when thread_id is truthy, else inbox view
        - 200 with {thread_id, since, count, messages:[serialized...]}

    Raises:
        - None (DB errors propagate from the fns to the route)
    """
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat( since )
        except ValueError:
            return { "http_status": 400, "detail": f"invalid 'since' timestamp: {since!r} (expected ISO 8601)" }

    effective_limit = max( 1, min( int( limit ), _DM_LIST_MAX_LIMIT ) )
    recipient_uuid  = uuid.UUID( authenticated_user_id )

    if thread_id:
        rows = thread_fn(
            thread_id    = thread_id,
            recipient_id = recipient_uuid,
            since        = since_dt,
            limit        = effective_limit,
        )
    else:
        rows = inbox_fn(
            recipient_id = recipient_uuid,
            since        = since_dt,
            limit        = effective_limit,
        )

    messages = [ _serialize_dm( row ) for row in rows ]
    return {
        "http_status" : 200,
        "thread_id"   : thread_id,
        "since"       : since,
        "count"       : len( messages ),
        "messages"    : messages,
    }


@router.get(
    "/list",
    summary     = "List or poll peer DMs — a thread (thread_id) or the inbox",
    description = "With `thread_id`, returns that conversation oldest-first; without it, returns the caller's peer-DM inbox newest-first. `since` (ISO 8601) tails only newer messages (poll); `limit` is clamped to [1, 200]. 400 if `since` is malformed.",
)
async def list_dms(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    thread_id: Optional[ str ] = None,
    since: Optional[ str ] = None,
    limit: int = 50,
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
            )

    result = await asyncio.to_thread( _work )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )
