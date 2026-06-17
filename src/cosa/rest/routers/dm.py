"""
DM API — `/api/dm/<verb>` notification-native AI↔AI direct messaging.

One coherent `/api/dm` namespace whose verb sub-routes each mirror a `dm_<verb>`
cosa-voice MCP tool 1:1. Phase 1 ships `POST /api/dm/send` (the relocated,
renamed legacy peer-DM endpoint); siblings `/respond`, `/get`, `/list` are added
in Phase 2 against the same router.

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
    asker_session_id     : str             = Field( ..., min_length=1, max_length=128 )
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
        - build_sender_id( asker_session_id ) -> sender_id str
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
    sender_id         = build_sender_id( body.asker_session_id )
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
        find_active_voice_persona_sessions, build_sender_id_for_cc,
    )

    def _resolve( recipient_session_id, recipient_persona, authenticated_user_id ):
        return _commons._resolve_dm_recipient(
            recipient_session_id             = recipient_session_id,
            recipient_persona                = recipient_persona,
            authenticated_user_id            = authenticated_user_id,
            raw_sessions_fn                  = find_active_voice_persona_sessions,
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
