"""
The lean podcast proxy's two doors: ask, then start.

A seat asks for a podcast of a document on Rick's behalf. The server judges the file, then writes the
yes/no card itself, so nothing on the card comes from the seat's own words. This module holds the ask
door. The start door is added by the next commit.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from cosa.rest import podcast_proxy as proxy
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest import task_store_rules as rules
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.routers.notifications import get_notification_queue, get_websocket_manager
from lupin_cli.claude_code.hooks.lib.session_bridge import get_voice_persona

router = APIRouter( prefix="/api/podcast-proxy", tags=[ "podcast-proxy" ] )


class AskIn( BaseModel ):
    """
    Body for POST /api/podcast-proxy/ask.

    `path` is the document in the doc viewer's form, `<scope>/<path within scope>`. `actor` is the
    caller's persona and session id; only the id is used, and the card names the seat from the bridge.
    """
    model_config = ConfigDict( extra="forbid" )

    path  : str = Field( ..., min_length=1, max_length=1024 )
    actor : str = Field( ..., min_length=1, max_length=255 )


@router.post(
    "/ask",
    summary     = "Ask Rick to approve a podcast of a document",
    description = "A seat names a document as <scope>/<path>. The server judges the file with the doc viewer's whole "
                  "read check, then makes the yes/no card itself, from the file's measured name, size and SHA-256, "
                  "and pushes it to the operator. After the operator answers yes, the seat calls start with the card id. "
                  "One waiting card per file and content. Auth: X-API-Key or Bearer JWT."
)
def ask_for_a_podcast(
    payload: AskIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
    notification_queue = Depends( get_notification_queue ),
    ws_manager = Depends( get_websocket_manager ),
):
    """
    Judge the document, make the card, push it.

    Requires:
        - payload.actor ends with the caller's session id
        - payload.path names a file the doc viewer would serve and a podcast can read

    Ensures:
        - 400 when the actor carries no session id, or when the door check refuses the file; the message names the path
        - 404 when the operator's account is not found
        - 409, naming the waiting card, when a card for this file and these bytes still waits for an answer
        - otherwise inserts one card whose `payload` is `proxy.card_payload( ... )`, whose default answer is "no",
          and returns { card_id, name, size, sha256, asked_by, expires_at, pushed }
        - the card is pushed only after the insert has committed, so an answer cannot arrive for a card the table lacks
    """
    session_id = rules.session_id_from_created_by( payload.actor )
    if session_id is None:
        raise HTTPException( status_code=400, detail="The actor must end with the caller's session id, so the card can say who asks." )
    try:
        facts = proxy.check_source( payload.path )
    except proxy.DoorRefusal as refusal:
        raise HTTPException( status_code=400, detail=str( refusal ) )

    from cosa.rest.user_service import get_user_by_email
    from lupin_cli.notifications.notification_models import resolve_target_user
    operator = get_user_by_email( resolve_target_user() )
    if not operator:
        raise HTTPException( status_code=404, detail="The operator's account was not found, so no card can be sent." )

    persona    = get_voice_persona( session_id )
    asker      = proxy.asker_label( session_id, persona.get( "name" ) if persona is not None else None )
    ask_payload = proxy.card_payload( facts, asker, session_id )
    question, abstract = proxy.card_text( ask_payload )
    age        = proxy.max_age_seconds()
    now        = datetime.now( timezone.utc )
    with get_db() as session:
        cards   = NotificationRepository( session )
        waiting = cards.find_live_podcast_card( proxy.CARD_KIND, ask_payload[ "scope_path" ], facts[ "sha256" ], now )
        if waiting is not None:
            raise HTTPException( status_code=409, detail=f"A podcast card for this file is already waiting for an answer: {waiting.id}. Use it, or let it expire." )
        sender_id  = promotion_gate.promotion_ask_sender_id( session_id )
        expires_at = now + timedelta( seconds=age )
        card = cards.create_notification(
            sender_id          = sender_id,
            recipient_id       = uuid.UUID( str( operator[ "id" ] ) ),
            message            = question,
            type               = "custom",
            priority           = "high",
            title              = "Make a podcast",
            abstract           = abstract,
            response_requested = True,
            response_type      = "yes_no",
            response_default   = "no",
            timeout_seconds    = age,
            expires_at         = expires_at,
            payload            = ask_payload,
        )
        card_id      = str( card.id )
        recipient_id = str( card.recipient_id )
        connected    = ws_manager.is_user_connected( recipient_id )
        cards.update_state( card.id, "delivered" if connected else "created" )
    pushed = True
    try:
        notification_queue.push_notification(
            message            = question,
            type               = "custom",
            priority           = "high",
            source             = "claude_code",
            user_id            = recipient_id,
            id                 = card_id,
            title              = "Make a podcast",
            response_requested = True,
            response_type      = "yes_no",
            response_default   = "no",
            timeout_seconds    = age,
            human_only         = True,
            sender_id          = sender_id,
            abstract           = abstract,
            payload            = ask_payload,
        )
    except Exception as e:
        # The card is saved, so the seat still gets its id; the operator can find it in history.
        pushed = False
        print( f"[podcast-proxy] card {card_id} saved but the push failed: {type( e ).__name__}: {e}" )
    return { "card_id": card_id, "name": facts[ "name" ], "size": facts[ "size" ], "sha256": facts[ "sha256" ],
             "asked_by": asker, "expires_at": expires_at.isoformat(), "pushed": pushed }
