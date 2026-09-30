"""
Authorization for routes that name a user in the URL — in the PATH (row d90baf3d) or in a
QUERY parameter (row 44d8e89c).

`require_api_key_or_jwt` answers "may this caller in at all". A route such as
`DELETE /api/notifications/bulk/{user_email}` needs a second answer: "is the user named in the
path THIS caller". Without it any valid credential reads or deletes any user's history by
writing someone else's email into the URL.

THE RULE (Mr. Radio's ruling, 2026-09-16): owner-only, no admin bypass. The path key must equal
the caller's user id, or — compared without regard to case — the caller's account email. An API
key is resolved to the user who owns it, so a key and a login token for the same person are
treated alike. No caller needs an admin bypass: the admin "Not Mine" mode sends the admin's own
email plus `exclude_own_jobs`, never another user's email.

WHERE THE NAME SITS IS NOT A DIFFERENT RULE, so both guards live here and share
`_key_is_owned`. What differs is what they read and what they RETURN:

  `require_path_identity_owner`   reads `request.path_params`, returns the caller's user id.
  `require_query_identity_owner`  reads `request.query_params`, returns the caller's ACCOUNT
                                  EMAIL — the audit identity. Row 44d8e89c: `POST
                                  /api/proxy/ratify/{decision_id}` and `DELETE
                                  /api/proxy/decision/{decision_id}` wrote `ratified_by` /
                                  `deleted_by` from the query string the caller typed, so the
                                  audit trail recorded a claim rather than a fact. Passing the
                                  ownership check is not enough to make the typed string the
                                  right thing to STORE: `_key_is_owned` also accepts the
                                  caller's bare user id, and it compares email without regard
                                  to case, so two callers who are the same person can write two
                                  different strings into the same column. The credential is the
                                  one source that cannot disagree with itself.

⚠️ A ROUTE-LEVEL `Depends` RAISING 401 PREEMPTS THE HANDLER'S OWN 422 — measured with a
TestClient on 2026-09-26, both for a request carrying the query parameter and for one omitting
it. That ordering is what the query guard needs to be worth anything on these two routes: a
BARE uncredentialed call to either used to answer 422 for the missing `user_email`, which reads
like a refusal and is not one (row 2d6f2221 measured the well-formed call reaching the
database). Now the credential is what answers first.
"""

import asyncio
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt


# The path parameter names that name a user. A route carrying any of them must use the guard;
# the router-enumerating unit test reads this tuple, so a new spelling is added here, once.
PATH_IDENTITY_PARAMS = ( "user_id", "user_email" )

# The same, for a user named in the QUERY STRING. Kept as its own tuple rather than shared with
# the tuple above: the path tuple is read by a router-enumerating test whose denominator is
# "routes that must carry the path guard", and a query spelling added to it would enlarge that
# population with routes the path guard deliberately refuses to serve (it raises 500 for a route
# naming no user in its path).
QUERY_IDENTITY_PARAMS = ( "user_id", "user_email" )


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

    if all( key == authenticated_user_id for key in keys ): return authenticated_user_id

    from cosa.rest.user_service import get_user_by_id
    user = await asyncio.to_thread( get_user_by_id, authenticated_user_id )

    if user is None or not all( _key_is_owned( key, authenticated_user_id, user[ "email" ] ) for key in keys ):
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "The user named in this path is not the authenticated caller"
        )
    return authenticated_user_id


async def require_query_identity_owner(
    request: Request,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> str:
    """
    FastAPI dependency: refuse a caller who is not the user named in the QUERY STRING, and
    return the caller's account email for the handler to record.

    Requires:
        - authenticated_user_id comes from `require_api_key_or_jwt`, which has already rejected
          an absent or bad credential (FastAPI caches it, so the credential is checked once)

    Ensures:
        - returns the caller's account email when every identity key in the query names the caller
        - raises 403 when any key names someone else, or the caller's user record is gone
        - returns the email when the query names NO user, leaving the handler's own required-
          parameter validation to answer 422. A missing query parameter is a malformed REQUEST,
          unlike the path case, where a route declaring no identity parameter is a WIRING error
          and gets a 500 — so this guard has no 500 arm and must not invent one
        - never trusts the key it was given as the identity: the email comes from the user record
          the credential resolved to, so a caller who passes the check by sending their bare user
          id, or their email in different case, still writes ONE canonical string to the audit
          column

    Raises:
        - HTTPException 403 as above
    """
    keys = [ request.query_params[ name ] for name in QUERY_IDENTITY_PARAMS if name in request.query_params ]

    # Unlike the path guard there is no "every key already equals the caller's id" shortcut: the
    # email is the return value, not just the comparand, so the lookup happens either way.
    from cosa.rest.user_service import get_user_by_id
    user = await asyncio.to_thread( get_user_by_id, authenticated_user_id )

    if user is None or not all( _key_is_owned( key, authenticated_user_id, user[ "email" ] ) for key in keys ):
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "The user named in this request is not the authenticated caller"
        )
    return user[ "email" ]
