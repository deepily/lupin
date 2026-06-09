#!/usr/bin/env python3
"""
Heartbeat-Arbiter fleet-snapshot endpoints — v2.1 direct-state visibility
(arbiter design `03` §10.4, redline C2).

Mirrors `GET /api/queue/pool-status`: a single queryable HTTP surface on
`:7999` that returns the arbiter's latest fleet snapshot (every session's
direct state + honest last-seen liveness ages), so Rick / the manager / a peer
can read true fleet state from a distance — seen, never inferred.

Endpoints (all authenticated via `require_api_key_or_jwt` — X-API-Key OR
Bearer JWT, the canonical machine-or-human credential, C2):
    - GET  /api/arbiter/fleet-state    — NEW authoritative surface (L4): a thin
      reverse-proxy that PULLS the single-pane composite from the standalone
      lupin-arbiter-app service at :8001/state (R3 — :8001 NEVER pushes here).
    - GET  /api/arbiter/fleet-snapshot — LEGACY v2.1: read the cached snapshot.
    - POST /api/arbiter/fleet-snapshot — LEGACY v2.1: the in-process arbiter
      PUSHES its latest snapshot here (updates the server singleton directly).

SUPERSEDED (2026-06-07, R0/R3): the standalone host-side **lupin-arbiter-app
service on :8001** is now authoritative — it exposes `GET /state` (the single
pane) and the :7999 reverse-proxy `GET /api/arbiter/fleet-state` PULLS from it
(deploy doc R3). The legacy in-process GET/POST `/api/arbiter/fleet-snapshot`
pair STAYS until the R0 cutover (feature-flag preservation — both coexist);
**post-cutover `/api/arbiter/fleet-state` WINS** and the in-process snapshot
pair retires with the in-process arbiter, which is gated OFF by the
`arbiter in-process bootstrap enabled` flag (R0). The former redline-C2
("there is NO standalone arbiter HTTP server") is retired with it.
"""
from typing import Annotated, Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest import arbiter_snapshot_store as snapshot_store


def _pull_arbiter_state( url: str, timeout: int ) -> Dict[ str, Any ]:   # pragma: no cover - literal httpx call boundary (live :8001 pull)
    """The ONE external IO boundary: GET :8001/state and return its JSON body."""
    return httpx.get( url, timeout=timeout ).raise_for_status().json()


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


@router.get(
    "/arbiter/fleet-state",
    summary     = "Lupin Arbiter App single-pane (reverse-proxy to :8001/state)",
    description = "NEW authoritative surface (L4): PULLS the single-pane composite "
                  "(health watcher + fleet arbiter snapshot) from the standalone "
                  "lupin-arbiter-app service at :8001/state (R3 — :8001 never pushes). "
                  "Auth: X-API-Key or Bearer JWT. Supersedes /api/arbiter/fleet-snapshot."
)
async def get_fleet_state(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Reverse-proxy the standalone lupin-arbiter-app composite from :8001/state.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)

    Ensures:
        - PULLS :8001/state (R3 — :7999 never pushes to :8001) and returns its
          composite body verbatim when reachable
        - on any httpx failure (connect refused / timeout / non-2xx) returns an
          explicit { status: "unreachable", ... } envelope with null sections —
          a HTTP 200 (mirroring the awaiting idiom: the proxy is up, the upstream
          watcher is not), never a 5xx or a hung request
        - reads the upstream URL + timeout LAZILY from the shared config singleton
          (no module-scope ConfigurationManager → import/collection never touches
          LUPIN_CONFIG_MGR_CLI_ARGS)
    """
    from cosa.rest.dependencies.config import get_config_manager
    config_mgr = get_config_manager()
    url     = config_mgr.get( "arbiter vigilance state url", default="http://127.0.0.1:8001/state" )
    timeout = config_mgr.get( "arbiter vigilance state timeout seconds", default=5, return_type="int" )
    try:
        return _pull_arbiter_state( url, timeout )
    except httpx.HTTPError as e:
        return {
            "status"         : "unreachable",
            "service"        : "lupin-arbiter-app",
            "detail"         : f"{type( e ).__name__}: {e}",
            "health_watcher" : None,
            "fleet_arbiter"  : None,
        }
