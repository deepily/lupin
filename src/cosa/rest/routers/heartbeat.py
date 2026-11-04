"""
Heartbeat router — the fleet on/off switch for the Stop poke.

    GET /api/heartbeat/poke-mute   (any authenticated caller) → { muted, set_by, set_at }
    PUT /api/heartbeat/poke-mute   (admin role only) body { muted } → same shape

A plain switch: no timer, no expiry. It stays as set until an admin flips
it back. Clients are the multiplexer, the legacy notification client and the phone.

A Claude session authenticates with X-API-Key. It may read the switch and may not flip
it: the poke is what keeps seats working, so a seat cannot silence it for itself.

The state is a file the Stop hook reads directly (hooks/lib/heartbeat_poke_mute.py), so
the handlers touch no database and are `async def`.
"""

from typing import Annotated, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictBool

from cosa.rest.auth_middleware import require_admin
from lupin_mcp import skeleton_crew
from lupin_cli.claude_code.hooks.lib.heartbeat_poke_mute import read_poke_mute, write_poke_mute
from ..middleware.api_key_auth import require_api_key_or_jwt


router = APIRouter( prefix="/api/heartbeat", tags=[ "heartbeat" ] )


class PokeMuteRequest( BaseModel ):
    muted : StrictBool


def derived_poke_mute_state() -> dict:
    """
    The mute state a client should show: the fleet file's state combined with skeleton crew.

    Ensures:
        - `muted` is true when the file says muted or skeleton crew is on
        - `source` is "file", "skeleton_crew", "both" or "none"
        - set_by and set_at are the file's own record, unchanged
        - the file is not written and nothing is retired
    """
    state    = read_poke_mute()
    skeleton = skeleton_crew.is_on_quietly()
    file_on  = bool( state[ "muted" ] )
    if file_on and skeleton:
        source = "both"
    elif skeleton:
        source = "skeleton_crew"
    elif file_on:
        source = "file"
    else:
        source = "none"
    return { **state, "muted": file_on or skeleton, "source": source }


async def refuse_api_key_writer(
    x_api_key     : Annotated[ str | None, Header() ] = None,
    authorization : Annotated[ str | None, Header() ] = None
) -> None:
    """
    Turn away a caller that presents only an API key, before the admin check runs.

    Ensures:
        - raises 403 when X-API-Key is present and Authorization is not: that is how a
          Claude session calls, and a session may read the switch but not flip it
        - otherwise returns None and the admin check decides (401 with no token, 403
          for a signed-in user without the admin role)
    """
    if x_api_key and not authorization:
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "The poke switch is flipped by an admin from a notification client. "
                          "An API-key caller may read it (GET) and may not change it."
        )


@router.get(
    "/poke-mute",
    summary     = "Read the fleet switch for the heartbeat Stop poke",
    description = "Returns { muted, set_by, set_at }. A missing or unreadable switch file reads as not muted."
)
async def get_poke_mute(
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> JSONResponse:
    """
    Report whether the Stop poke is muted fleet-wide.

    Requires:
        - caller is authenticated by API key or JWT (401 otherwise)

    Ensures:
        - returns 200 with the derived state, changing nothing: the file's own fields plus
          `muted` combined with skeleton crew and a `source`
    """
    return JSONResponse( content=derived_poke_mute_state() )


@router.put(
    "/poke-mute",
    summary     = "Admin: turn the heartbeat Stop poke off or back on, fleet-wide",
    description = "Body { muted: bool }. Takes effect on each seat's next stop. No timer: it stays as set until an admin flips it. API-key callers and non-admin users get 403."
)
async def put_poke_mute(
    body      : PokeMuteRequest,
    _no_key   : Annotated[ None, Depends( refuse_api_key_writer ) ],
    user      : Annotated[ Dict, Depends( require_admin ) ]
) -> JSONResponse:
    """
    Flip the switch.

    Requires:
        - caller holds the admin role on a user token (403 otherwise; 403 as well for a
          caller presenting only an API key)
        - body.muted is a JSON boolean (422 otherwise)

    Ensures:
        - the switch file holds the new value, who set it and when
        - one line is appended to the audit log beside it
        - returns 200 with the derived state, which is the file's state combined with skeleton crew
    """
    who = user.get( "email" ) or user.get( "uid" ) or "unknown"
    write_poke_mute( body.muted, who )
    return JSONResponse( content=derived_poke_mute_state() )
