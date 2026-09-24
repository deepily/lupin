"""
Authorization for routes keyed by a user in the URL path (row d90baf3d).

`require_api_key_or_jwt` answers "may this caller in at all". A route such as
`DELETE /api/notifications/bulk/{user_email}` needs a second answer: "is the user named in the
path THIS caller". Without it any valid credential reads or deletes any user's history by
writing someone else's email into the URL.

THE RULE (Mr. Radio's ruling, 2026-09-16): owner-only, no admin bypass. The path key must equal
the caller's user id, or — compared without regard to case — the caller's account email. An API
key is resolved to the user who owns it, so a key and a login token for the same person are
treated alike. No caller needs an admin bypass: the admin "Not Mine" mode sends the admin's own
email plus `exclude_own_jobs`, never another user's email.
"""

import asyncio
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt


# The path parameter names that name a user. A route carrying any of them must use the guard;
# the router-enumerating unit test reads this tuple, so a new spelling is added here, once.
PATH_IDENTITY_PARAMS = ( "user_id", "user_email" )


def _key_is_owned( key, user_id, email ):
    """
    Whether one path key names the caller.

    Requires:
        - key is the decoded path value; user_id is the caller's id; email is the caller's email

    Ensures:
        - True when key equals user_id exactly, or equals email ignoring case
        - False otherwise
    """
    return key == user_id or key.casefold() == email.casefold()


async def require_path_identity_owner(
    request: Request,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> str:
    """
    FastAPI dependency: refuse a caller who is not the user named in the path.

    Requires:
        - the route declares at least one parameter named in PATH_IDENTITY_PARAMS
        - authenticated_user_id comes from `require_api_key_or_jwt`, which has already rejected an
          absent or bad credential (FastAPI caches it, so the credential is checked once)

    Ensures:
        - returns authenticated_user_id when every identity key in the path names the caller
        - skips the user lookup when every key already equals the caller's id
        - raises 403 when any key names someone else, or the caller's user record is gone
        - raises 500 when the route has no identity parameter — a wiring error, refused rather
          than waved through

    Raises:
        - HTTPException 403 or 500 as above
    """
    keys = [ request.path_params[ name ] for name in PATH_IDENTITY_PARAMS if name in request.path_params ]
    if not keys:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Route uses the path-owner guard but names no user in its path"
        )
    return await _refuse_unless_owned( keys, authenticated_user_id, "path" )


async def require_query_identity_owner(
    request: Request,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> str:
    """
    FastAPI dependency: the path-owner rule for a user named in the QUERY string (row 2d6f2221).

    `POST /api/proxy/ratify/{decision_id}?user_email=…` records who ratified. Taken on trust, any
    caller could ratify in someone else's name, so the same owner-only rule applies there.

    Requires:
        - the route declares a query parameter named in PATH_IDENTITY_PARAMS

    Ensures:
        - returns authenticated_user_id when every identity key in the query names the caller
        - raises 403 when any key names someone else, or the caller's user record is gone
        - raises 500 when the query names no user — a wiring error, as for the path guard

    Raises:
        - HTTPException 403 or 500 as above
    """
    keys = [ request.query_params[ name ] for name in PATH_IDENTITY_PARAMS if name in request.query_params ]
    if not keys:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Route uses the query-owner guard but names no user in its query"
        )
    return await _refuse_unless_owned( keys, authenticated_user_id, "query" )


async def _refuse_unless_owned( keys, authenticated_user_id, where ):
    """
    The owner-only rule shared by the path and query guards.

    Requires:
        - keys is a non-empty list of user keys taken from the request
        - where names where they came from ("path" or "query"), for the refusal message

    Ensures:
        - returns authenticated_user_id when every key names the caller
        - skips the user lookup when every key already equals the caller's id

    Raises:
        - HTTPException 403 when any key names someone else, or the caller's user record is gone
    """
    if all( key == authenticated_user_id for key in keys ): return authenticated_user_id

    from cosa.rest.user_service import get_user_by_id
    user = await asyncio.to_thread( get_user_by_id, authenticated_user_id )

    if user is None or not all( _key_is_owned( key, authenticated_user_id, user[ "email" ] ) for key in keys ):
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = f"The user named in this {where} is not the authenticated caller"
        )
    return authenticated_user_id
