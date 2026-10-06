"""
FCM token-registration endpoints, the mobile silent-relay wake channel.

The mobile app registers its FCM device token here. The parent can then summon the app
with a content-free `ws_wake` push when notifications arrive and no live mobile
WebSocket exists (see `cosa.rest.fcm_wake_service`). Tokens persist in the `fcm_tokens`
table, durable across restarts.

Endpoints:
    POST /api/fcm/register-token   (JWT) — body { token, platform, user_email } → { "status": "ok" }.
    POST /api/fcm/push-pause       (admin) — body { paused, minutes? } → pause state.
    GET  /api/fcm/push-pause       (admin) — → pause state.
    POST /api/fcm/unregister-token (JWT) — body { token } → { "status": "ok" }.
        (a POST, not a DELETE with a body. Some proxies and load balancers drop
        a DELETE body on the GCP cutover path.)

Handlers are sync `def`. They hold sync DB sessions, and FastAPI runs sync handlers on
the threadpool. An `async def` with a sync `get_db()` inside would block the event loop.

The push-pause handlers are the exception and are `async def`. They touch no database,
only an in-memory flag. The auto-resume timer is armed with `loop.call_later`, which is
not thread-safe and needs the server's running event loop. A threadpool handler has none.
"""

import asyncio
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cosa.rest.auth_middleware import require_admin
from cosa.rest.fcm_push_pause import MAX_PAUSE_MINUTES, get_controller
from ..db.database import get_db
from ..db.repositories.fcm_token_repository import FcmTokenRepository
from ..middleware.api_key_auth import require_api_key_or_jwt


router = APIRouter( prefix="/api/fcm", tags=[ "fcm" ] )


class RegisterTokenRequest( BaseModel ):
    token      : str = Field( min_length=1, max_length=512 )
    platform   : Literal[ "android" ] = "android"   # spec-pinned enum (S6 §3.1; iOS/APNs out of milestone scope)
    user_email : str = Field( min_length=3, max_length=255 )


class UnregisterTokenRequest( BaseModel ):
    token : str = Field( min_length=1, max_length=512 )


@router.post(
    "/register-token",
    summary     = "Register a mobile device's FCM token for the silent-relay wake channel",
    description = "Upsert keyed on token (S6 §3.1): re-registering a known token refreshes its user binding instead of duplicating it. Multiple devices per user allowed. The mobile app calls this on login, onTokenRefresh, and every WS reconnect (idempotent belt for parent-restart registry loss)."
)
def register_fcm_token(
    body                 : RegisterTokenRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> JSONResponse:
    """
    Persist (upsert) an FCM device token for the authenticated user.

    Requires:
        - body.token is a non-empty FCM registration token
        - caller is authenticated (JWT or API key)

    Ensures:
        - exactly one fcm_tokens row exists for the token afterwards
        - returns 200 { "status": "ok" } (contract response shape)

    Raises:
        - None beyond auth/validation middleware (422 on malformed body)

    The user binding stored with the token is the authenticated uid, because the wake trigger
    resolves tokens by the same uid notifications target. The body's user_email is the
    contract field, stored alongside for operator legibility.
    """
    with get_db() as session:
        repo = FcmTokenRepository( session )
        repo.upsert_token(
            token      = body.token,
            user_id    = authenticated_user_id,
            user_email = body.user_email,
            platform   = body.platform
        )

    print( f"[FCM] Registered token …{body.token[ -8: ]} for user {authenticated_user_id} ({body.platform})" )
    return JSONResponse( content={ "status": "ok" } )


@router.post(
    "/unregister-token",
    summary     = "Unregister a mobile device's FCM token (best-effort logout path)",
    description = "Idempotent: unregistering an unknown token still returns 200 (S6 §3.1 amended 2026-06-12 — POST replaces the proxy-fragile DELETE-with-JSON-body shape)."
)
def unregister_fcm_token(
    body                 : UnregisterTokenRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> JSONResponse:
    """
    Remove an FCM device token registration.

    Requires:
        - body.token is a non-empty string
        - caller is authenticated (JWT or API key)

    Ensures:
        - no fcm_tokens row exists for the token afterwards
        - returns 200 { "status": "ok" } whether or not a row was removed

    Raises:
        - None beyond auth/validation middleware (422 on malformed body)

    This is best-effort by contract. Logout flows fire it without awaiting guarantees, so
    an unknown token is a success. The end state, token not registered, already holds.
    """
    with get_db() as session:
        repo    = FcmTokenRepository( session )
        removed = repo.delete_token( body.token )

    print( f"[FCM] Unregistered token …{body.token[ -8: ]} for user {authenticated_user_id} (removed={removed})" )
    return JSONResponse( content={ "status": "ok" } )


class PushPauseRequest( BaseModel ):
    paused  : bool
    minutes : Optional[ int ] = None   # range-checked in the handler so an over-cap value is a 400, not a 422


def _who( user: dict ) -> str:
    """The admin's label for the audit line and the read-back."""
    return user.get( "email" ) or user.get( "uid" ) or "unknown"


@router.post(
    "/push-pause",
    summary     = "Admin: pause (or resume) ALL mobile wake pushes, in memory only",
    description = "Sets `fcm wake push enabled` False in the ConfigurationManager's memory — never the INI — and, with `minutes`, arms a timer that restores the boot-time value. A second pause replaces the first timer; `paused: false` resumes now. `minutes` is capped at 24 h (400 above it). A server restart clears the pause (row 7df08e59, Rick's R1.4 ruling)."
)
async def set_push_pause(
    body : PushPauseRequest,
    user : Annotated[ dict, Depends( require_admin ) ]
) -> JSONResponse:
    """
    Pause or resume every mobile wake push, globally.

    Requires:
        - caller has the admin role (403 otherwise)
        - body.minutes, when given with paused=true, is 1..1440

    Ensures:
        - paused=true: pushes are off in memory until the timer, an explicit resume, or a restart
        - paused=false: pushes are back at their boot-time value and no timer remains
        - the INI file is never written
        - returns 200 with the pause state

    Raises:
        - HTTPException 400 when minutes is outside 1..1440
    """
    controller = get_controller()
    if not body.paused:
        return JSONResponse( content=controller.resume( _who( user ) ) )
    try:
        state = controller.pause( body.minutes, _who( user ), asyncio.get_running_loop() )
    except ValueError as e:
        raise HTTPException( status_code=400, detail=str( e ) )
    return JSONResponse( content=state )


@router.get(
    "/push-pause",
    summary     = "Admin: read the mobile push pause state",
    description = "Returns { paused, resumes_at, set_by, set_at, push_enabled }. `push_enabled` is the live key, so the answer is never a guess."
)
async def get_push_pause(
    user : Annotated[ dict, Depends( require_admin ) ]
) -> JSONResponse:
    """
    Report whether mobile pushes are paused.

    Requires:
        - caller has the admin role (403 otherwise)

    Ensures:
        - returns 200 with the pause state, changing nothing
    """
    return JSONResponse( content=get_controller().status() )
