"""
The lean podcast proxy's two doors: ask, then start.

A seat asks for a podcast of a document on Rick's behalf. The server judges the file, then writes the
yes/no card itself, so nothing on the card comes from the seat's own words. After Rick answers yes, the
same seat calls start with the card id. The server re-checks the stored card and the file, spends the
card once, and builds the job for Rick through the existing v2 submit path.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from cosa.rest import podcast_proxy as proxy
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest import task_store_rules as rules
import cosa.utils.util as cu
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.db.repositories.podcast_proxy_spent_repository import PodcastProxySpentRepository
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.routers.notifications import get_notification_queue, get_websocket_manager
from cosa.rest.routers.v2_ask import get_ask_flow
from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id, get_voice_persona

router = APIRouter( prefix="/api/podcast-proxy", tags=[ "podcast-proxy" ] )


def _refuse( status, code, message ):
    """An HTTP error whose detail is { code, message }, so a client can tell the refusals apart."""
    return HTTPException( status_code=status, detail=proxy.refusal_detail( code, message ) )


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
        - every refusal has the body { detail: { code, message } }, and a client matches on the code
        - 400 bad_actor when the actor carries no session id; 400 with the door's code (bad_path, not_found,
          viewer_refused, wrong_kind, too_large, credential, unreadable) when the check refuses the file, and the message names the path
        - 404 no_operator when the operator's account is not found
        - 409 waiting_card, with card_id beside the code, when a card for this file and these bytes still waits for an answer
        - otherwise inserts one card whose `payload` is `proxy.card_payload( ... )`, whose default answer is "no",
          and returns { card_id, name, size, sha256, asked_by, expires_at, pushed }
        - the card is pushed only after the insert has committed, so an answer cannot arrive for a card the table lacks
    """
    session_id = rules.session_id_from_created_by( payload.actor )
    if session_id is None:
        raise _refuse( 400, "bad_actor", "The actor must end with the caller's session id, so the card can say who asks." )
    try:
        facts = proxy.check_source( payload.path )
    except proxy.DoorRefusal as refusal:
        raise _refuse( 400, refusal.code, refusal.message )

    from cosa.rest.user_service import get_user_by_email
    from lupin_cli.notifications.notification_models import resolve_target_user
    operator = get_user_by_email( resolve_target_user() )
    if not operator:
        raise _refuse( 404, "no_operator", "The operator's account was not found, so no card can be sent." )

    persona    = get_voice_persona( session_id )
    seat       = find_session_by_id( session_id, check_pid=False ) or { }
    asker      = proxy.asker_label( session_id, persona.get( "name" ) if persona is not None else None )
    ask_payload = proxy.card_payload( facts, asker, proxy.binding_id( session_id, seat ) )
    question, abstract = proxy.card_text( ask_payload )
    age        = proxy.max_age_seconds()
    now        = datetime.now( timezone.utc )
    with get_db() as session:
        cards   = NotificationRepository( session )
        waiting = cards.find_live_podcast_card( proxy.CARD_KIND, ask_payload[ "scope_path" ], facts[ "sha256" ], now )
        if waiting is not None:
            raise HTTPException( status_code=409, detail={ **proxy.refusal_detail( "waiting_card", f"A podcast card for this file is already waiting for an answer: {waiting.id}. Use it, or let it expire." ), "card_id": str( waiting.id ) } )
        # The card files beside the asking seat's own cards: its sender id comes from its bridge, and its persona rides along.
        sender_id  = seat.get( "sender_id" ) or promotion_gate.promotion_ask_sender_id( session_id )
        expires_at = now + timedelta( seconds=age )
        card = cards.create_notification(
            sender_id          = sender_id,
            sender_persona     = persona.get( "name" ) if persona is not None else None,
            sender_icon        = persona.get( "icon" ) if persona is not None else None,
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
            voice_persona      = persona,
            sender_persona     = persona.get( "name" ) if persona is not None else None,
            sender_icon        = persona.get( "icon" ) if persona is not None else None,
            abstract           = abstract,
            payload            = ask_payload,
        )
    except Exception as e:
        # The card is saved, so the seat still gets its id; the operator can find it in history.
        pushed = False
        print( f"[podcast-proxy] card {card_id} saved but the push failed: {type( e ).__name__}: {e}" )
    return { "card_id": card_id, "name": facts[ "name" ], "size": facts[ "size" ], "sha256": facts[ "sha256" ],
             "asked_by": asker, "expires_at": expires_at.isoformat(), "pushed": pushed }


class StartIn( BaseModel ):
    """
    Body for POST /api/podcast-proxy/start.

    `card_id` is the id the ask door returned. `actor` is the caller's persona and session id; only the id
    is used, and it must be the session that asked.
    """
    model_config = ConfigDict( extra="forbid" )

    card_id : uuid.UUID
    actor   : str = Field( ..., min_length=1, max_length=255 )


def copy_directory():
    """The folder of job copies: io/podcast-proxy under the server's project root."""
    return os.path.join( cu.get_project_root(), "io", "podcast-proxy" )


@router.post(
    "/start",
    summary     = "Start the podcast Rick said yes to",
    description = "The seat that asked cites the card id. The server re-reads the stored card (a question, answered yes by "
                  "a person on the operator's own login, written by the server, asked by this session, not older than "
                  "the INI age), re-reads the file and refuses if its bytes changed, spends the card once, copies the "
                  "judged bytes, and builds the podcast job for the operator through the v2 submit path. "
                  "Auth: X-API-Key or Bearer JWT."
)
def start_a_podcast(
    payload: StartIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    flow = Depends( get_ask_flow ),
):
    """
    Check the card and the file, spend the card, queue the job.

    Requires:
        - payload.actor ends with the caller's session id

    Ensures:
        - every refusal has the body { detail: { code, message } }, and a client matches on the code
        - 400 bad_actor when the actor carries no session id
        - 404 no_card, 403 bad_card / not_answered / default_answer / not_yes / wrong_login / wrong_session / too_old,
          exactly as `proxy.start_refusal` judges the stored card
        - 409 file_refused when the door now refuses the file, 409 hash_mismatch when its bytes are not those of the yes
        - 409 spent when the card already started a job, however many starts raced
        - 409 claimed_no_job when an earlier start claimed the card and recorded no job: that start is still under way,
          or it did not finish. The claim is not released here, because a release racing a slow queue call could start two jobs
        - the spent record is committed before the job is queued; when queuing fails it is released and the answer
          is 502 queue_failed with a fixed sentence, the cause going to the server log. A crash between the claim and
          the release leaves the claim, which the next start answers as claimed_no_job
        - otherwise returns { card_id, job_id, status, name, queue_position } for a job built for the card's
          recipient from a copy of the judged bytes
    """
    session_id = rules.session_id_from_created_by( payload.actor )
    if session_id is None:
        raise _refuse( 400, "bad_actor", "The actor must end with the caller's session id, so the card can tell who is starting it." )
    now = datetime.now( timezone.utc )

    with get_db() as session:
        card    = NotificationRepository( session ).get_by_id( payload.card_id )
        refusal = proxy.start_refusal( card, proxy.binding_id( session_id, find_session_by_id( session_id, check_pid=False ) ), now, proxy.max_age_seconds() )
        stored       = dict( card.payload ) if refusal is None else { }
        recipient_id = str( card.recipient_id ) if refusal is None else ""
    if refusal is not None: raise _refuse( refusal.status, refusal.code, refusal.message )

    try:
        facts = proxy.check_source( stored[ "scope_path" ], keep_content=True )
    except proxy.DoorRefusal as refused:
        raise _refuse( 409, "file_refused", str( refused ) )
    changed = proxy.file_changed_refusal( stored, facts )
    if changed is not None: raise _refuse( changed.status, changed.code, changed.message )

    from cosa.rest.user_service import get_user_by_id
    operator = get_user_by_id( recipient_id )
    if not operator:
        raise _refuse( 404, "no_operator", "The operator's account was not found, so the job cannot be built." )

    with get_db() as session:
        spent_rows = PodcastProxySpentRepository( session )
        won        = spent_rows.claim( payload.card_id, payload.actor, stored[ "scope_path" ], stored[ "sha256" ] )
        earlier    = None if won else spent_rows.get( payload.card_id )
        no_job     = earlier is not None and earlier.job_id is None
    if not won and no_job:
        raise _refuse( 409, "claimed_no_job", "A start of that card is under way, or one did not finish. Read the card status again before asking Rick." )
    if not won:
        raise _refuse( 409, "spent", "That card has already started a podcast, and a yes covers one, so it is refused." )

    try:
        path   = proxy.write_copy( copy_directory(), payload.card_id, facts[ "name" ], facts[ "content" ] )
        result = flow.submit(
            command      = proxy.COMMAND,
            args         = { "research": path },
            user_id      = recipient_id,
            user_email   = operator[ "email" ],
            session_id   = f"podcast-proxy-{str( payload.card_id )[ :8 ]}",
            websocket_id = f"podcast-proxy-{str( payload.card_id )[ :8 ]}",
            speak        = False,
        )
        if result.get( "status" ) != "waiting" or not result.get( "job_id" ):
            raise RuntimeError( f"the queue answered status {result.get( 'status' )!r}: {result.get( 'error' ) or result.get( 'route_reason' )}" )
    except Exception as failure:
        proxy.remove_copy( copy_directory(), payload.card_id )
        with get_db() as session:
            PodcastProxySpentRepository( session ).release( payload.card_id )
        print( f"[podcast-proxy] queue failed for card {payload.card_id}: {failure!r}" )
        raise _refuse( 502, "queue_failed", "The job could not be queued. The yes is still good; start the same card again." )

    with get_db() as session:
        PodcastProxySpentRepository( session ).record_job( payload.card_id, result[ "job_id" ] )
    return { "card_id": str( payload.card_id ), "job_id": result[ "job_id" ], "status": result[ "status" ],
             "name": facts[ "name" ], "queue_position": result.get( "queue_position" ) }


@router.get(
    "/card/{card_id}",
    summary     = "Where a podcast card stands",
    description = "A client that holds only a card id reads the file it was made for, whether Rick has answered, and whether it "
                  "already started a job. The client compares scope_path with the path it expects. Auth: X-API-Key or Bearer JWT."
)
def podcast_card_status(
    card_id: uuid.UUID,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
):
    """
    Describe one podcast card from what the server stored.

    Ensures:
        - 404 no_card when the id names no card, or a card this feature did not write
        - otherwise returns { card_id, scope_path, name, size, sha256, asked_by_session, state, expires_at, spent, job_id }
          with state one of waiting, yes, no, default_answer, expired, wrong_login, claimed_no_job
        - state is claimed_no_job when a start claimed the card and no job is recorded yet: a start is under way, or one did not finish
        - spent is True once a start claimed the card; job_id is that start's job, or None before it exists
        - every value comes from the stored payload, the stored answer and the spent record
    """
    with get_db() as session:
        card = NotificationRepository( session ).get_by_id( card_id )
        if card is None or not isinstance( card.payload, dict ) or card.payload.get( "kind" ) != proxy.CARD_KIND:
            raise _refuse( 404, "no_card", "No podcast card has that id." )
        stored  = dict( card.payload )
        state   = proxy.card_state( card, datetime.now( timezone.utc ) )
        expires = card.expires_at.isoformat() if card.expires_at is not None else None
        spent   = PodcastProxySpentRepository( session ).get( card_id )
        job_id  = spent.job_id if spent is not None else None
        if spent is not None and job_id is None: state = "claimed_no_job"
    return { "card_id": str( card_id ), "scope_path": stored[ "scope_path" ], "name": stored[ "name" ], "size": stored[ "size" ],
             "sha256": stored[ "sha256" ], "asked_by_session": stored[ "asked_by_session" ], "state": state,
             "expires_at": expires, "spent": spent is not None, "job_id": job_id }
