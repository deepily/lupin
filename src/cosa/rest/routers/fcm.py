"""
FCM token-registration endpoints — the mobile silent-relay wake channel (S6 §3.1).

The mobile app registers its FCM device token here so the parent can summon it
with a content-free `ws_wake` push when notifications arrive and no live mobile
WebSocket exists (see `cosa.rest.fcm_wake_service`). Tokens persist in the
`fcm_tokens` table (durable across restarts, F-S6-S2-1a).

Endpoints (cascade-ratified contract, amended 2026-06-12 under OSQ-6):
    POST /api/fcm/register-token   (JWT) — body { token, platform, user_email } → { "status": "ok" }
    POST /api/fcm/unregister-token (JWT) — body { token } → { "status": "ok" }
        (was DELETE /api/fcm/register-token with JSON body — switched because
        DELETE-with-body is dropped by some proxies/LBs on the GCP cutover path)

See: src/lupin-mobile/src/rnd/2026.06.11-focus-mode-voice-chat/15-section-s6-fcm-backend-interface.md
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..db.database import get_db
from ..db.repositories.fcm_token_repository import FcmTokenRepository
from ..middleware.api_key_auth import require_api_key_or_jwt


router = APIRouter( prefix="/api/fcm", tags=[ "fcm" ] )


class RegisterTokenRequest( BaseModel ):
    token      : str = Field( min_length=1, max_length=512 )
    platform   : str = Field( default="android", max_length=32 )
    user_email : str = Field( min_length=3, max_length=255 )


class UnregisterTokenRequest( BaseModel ):
    token : str = Field( min_length=1, max_length=512 )


@router.post(
    "/register-token",
    summary     = "Register a mobile device's FCM token for the silent-relay wake channel",
    description = "Upsert keyed on token (S6 §3.1): re-registering a known token refreshes its user binding instead of duplicating it. Multiple devices per user allowed. The mobile app calls this on login, onTokenRefresh, and every WS reconnect (idempotent belt for parent-restart registry loss)."
)
async def register_fcm_token(
    body                 : RegisterTokenRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> JSONResponse:
    """
    Persist (upsert) an FCM device token for the authenticated user.

    The user binding stored with the token is the AUTHENTICATED uid — the wake
    trigger resolves tokens by the same uid notifications target. The body's
    user_email is the S6 §3.1 contract field, stored alongside for operator
    legibility.

    Requires:
        - body.token is a non-empty FCM registration token
        - caller is authenticated (JWT or API key)

    Ensures:
        - exactly one fcm_tokens row exists for the token afterwards
        - returns 200 { "status": "ok" } (contract response shape)

    Raises:
        - None beyond auth/validation middleware (422 on malformed body)
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
async def unregister_fcm_token(
    body                 : UnregisterTokenRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> JSONResponse:
    """
    Remove an FCM device token registration.

    Best-effort by contract: logout flows fire this without awaiting guarantees,
    so an unknown token is a success (the end state — token not registered —
    already holds).

    Requires:
        - body.token is a non-empty string
        - caller is authenticated (JWT or API key)

    Ensures:
        - no fcm_tokens row exists for the token afterwards
        - returns 200 { "status": "ok" } whether or not a row was removed

    Raises:
        - None beyond auth/validation middleware (422 on malformed body)
    """
    with get_db() as session:
        repo    = FcmTokenRepository( session )
        removed = repo.delete_token( body.token )

    print( f"[FCM] Unregistered token …{body.token[ -8: ]} for user {authenticated_user_id} (removed={removed})" )
    return JSONResponse( content={ "status": "ok" } )
