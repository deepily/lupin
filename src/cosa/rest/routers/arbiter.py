#!/usr/bin/env python3
"""
Heartbeat-Arbiter fleet-snapshot endpoints — v2.1 direct-state visibility
(arbiter design `03` §10.4, redline C2).

Mirrors `GET /api/queue/pool-status`: a single queryable HTTP surface on
`:7999` that returns the arbiter's latest fleet snapshot (every session's
direct state + honest last-seen liveness ages), so Rick / the manager / a peer
can read true fleet state from a distance — seen, never inferred.

Endpoints (both authenticated via `require_api_key_or_jwt` — X-API-Key OR
Bearer JWT, the canonical machine-or-human credential, C2):
    - GET  /api/arbiter/fleet-snapshot — read the cached snapshot.
    - POST /api/arbiter/fleet-snapshot — the standalone arbiter PUSHES its
      latest snapshot here (the in-pool arbiter updates the singleton directly).

Per redline C2 there is NO standalone arbiter HTTP server — the arbiter pushes
into this existing surface; the cache lives in `arbiter_snapshot_store`.
"""
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest import arbiter_snapshot_store as snapshot_store


router = APIRouter( prefix="/api", tags=[ "arbiter" ] )


class FleetSnapshotIn( BaseModel ):
    """
    Push body for POST /api/arbiter/fleet-snapshot (the standalone-arbiter path).

    Shape mirrors fleet_render.build_snapshot output. Validated by Pydantic
    (constraints declared here, never hand-rolled if/raise) — `session_count`
    is coerced to a non-negative int; `sessions` defaults to an empty list.
    """
    generated_at  : Optional[ str ]           = None
    session_count : int                       = Field( default=0, ge=0 )
    sessions      : List[ Dict[ str, Any ] ]  = Field( default_factory=list )


@router.get(
    "/arbiter/fleet-snapshot",
    summary     = "Heartbeat-arbiter fleet snapshot (direct-state visibility)",
    description = "Returns the arbiter's latest full-fleet snapshot: per-session "
                  "STATE + orthogonal LIVENESS (honest last-seen ages + verdict). "
                  "Mirrors GET /api/queue/pool-status. v2.1 (arbiter design 03 §10.4)."
)
async def get_fleet_snapshot(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Return the cached fleet snapshot.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)

    Ensures:
        - returns the latest pushed snapshot dict if present
        - returns an explicit "awaiting" placeholder (status + empty fleet) when
          the arbiter has not pushed a snapshot yet — never a bare null, so a
          cold start is distinguishable from a zero-session fleet
    """
    snap = snapshot_store.get_snapshot()
    if snap is None:
        return {
            "status"        : "awaiting",
            "generated_at"  : None,
            "session_count" : 0,
            "sessions"      : [ ],
        }
    return snap


@router.post(
    "/arbiter/fleet-snapshot",
    summary     = "Push a fleet snapshot (standalone-arbiter ingress)",
    description = "The standalone Heartbeat Arbiter pushes its latest snapshot "
                  "here; the in-pool arbiter updates the server singleton directly. "
                  "Auth: X-API-Key or Bearer JWT. v2.1 (arbiter design 03 §10.4 C2)."
)
async def push_fleet_snapshot(
    payload: FleetSnapshotIn,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Cache a pushed fleet snapshot.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - payload validates against FleetSnapshotIn

    Ensures:
        - stores the snapshot (as a plain dict) in arbiter_snapshot_store
        - returns { status: "ok", session_count } acknowledging the push
    """
    snapshot_store.set_snapshot( payload.model_dump() )
    return { "status": "ok", "session_count": payload.session_count }
