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
    - GET  /api/arbiter/context-pressure — read-only per-persona context-headroom
      service: PULLS :8001/state and returns JUST the `context_pressure` section
      (persona-keyed budget-headroom map, design 2026.06.09 Decisions 1-5).
    - GET  /api/arbiter/fleet-size-cap — the fleet-size dial: the enforced cap, the
      configured ceiling, and the live manager/worker split occupying it.
    - PUT  /api/arbiter/fleet-size-cap — SET the cap. Writes through to the
      configuration FILE and returns what it re-read from disk, never an echo of the
      request (Rick: "those values are serialized and reused the next time").
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
        - injects ONE top-level `app_timezone` field (the configured IANA zone,
          e.g. "America/New_York") into the otherwise-verbatim composite — the
          SINGLE deviation from verbatim-proxy, :7999-local (no :8001 change). The
          client feeds it to Intl.DateTimeFormat to render the last-updated stamp
          in the operator's DST-aware zone (Fleet-Status design §4.1). Omitted on
          the unreachable envelope by design → the client falls back to browser-
          local zone (display-only, never blocks the table).
    """
    from cosa.rest.dependencies.config import get_config_manager
    config_mgr = get_config_manager()
    url     = config_mgr.get( "arbiter vigilance state url", default="http://127.0.0.1:8001/state" )
    timeout = config_mgr.get( "arbiter vigilance state timeout seconds", default=5, return_type="int" )
    try:
        result = _pull_arbiter_state( url, timeout )
    except httpx.HTTPError as e:
        return {
            "status"         : "unreachable",
            "service"        : "lupin-arbiter-app",
            "detail"         : f"{type( e ).__name__}: {e}",
            "health_watcher" : None,
            "fleet_arbiter"  : None,
        }
    if isinstance( result, dict ):
        result[ "app_timezone" ] = config_mgr.get( "app timezone", default="America/New_York" )
    return result


@router.get(
    "/arbiter/context-pressure",
    summary     = "Published per-persona context-headroom service (read-only)",
    description = "Returns the persona-keyed context-headroom map: per worker, the "
                  "tokens remaining before its soft budget line (1M window → 50%, "
                  "200K → 75%; config-tunable). Thin reverse-proxy that PULLS "
                  ":8001/state and returns JUST the `context_pressure` section. "
                  "Pure sensor read — no side effects. Auth: X-API-Key or Bearer JWT. "
                  "Design: src/rnd/v0.1.8/2026.06.07-managing-context-memory/"
                  "2026.06.09-context-pressure-published-headroom-service-design.md §4-5."
)
async def get_context_pressure(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Reverse-proxy ONLY the `context_pressure` section of :8001/state (Decision 3:
    the dedicated public surface; the section also rides the /fleet-state composite).

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)

    Ensures:
        - PULLS :8001/state (R3 — :7999 never pushes) and returns the
          `context_pressure` section verbatim when present
        - returns the explicit { status: "awaiting", personas: {} } placeholder
          when the upstream composite lacks the section (e.g. the deployed
          arbiter predates the writer) — never a bare null
        - on any httpx failure returns an explicit { status: "unreachable", ... }
          envelope with a null personas map — an HTTP 200 (the proxy is up, the
          upstream watcher is not), never a 5xx or a hung request
        - reads the upstream URL + timeout LAZILY from the shared config singleton
          (same keys as /arbiter/fleet-state)
    """
    from cosa.rest.dependencies.config import get_config_manager
    config_mgr = get_config_manager()
    url     = config_mgr.get( "arbiter vigilance state url", default="http://127.0.0.1:8001/state" )
    timeout = config_mgr.get( "arbiter vigilance state timeout seconds", default=5, return_type="int" )
    try:
        result = _pull_arbiter_state( url, timeout )
    except httpx.HTTPError as e:
        return {
            "status"   : "unreachable",
            "service"  : "lupin-arbiter-app",
            "detail"   : f"{type( e ).__name__}: {e}",
            "personas" : None,
        }
    section = result.get( "context_pressure" ) if isinstance( result, dict ) else None
    return section if section is not None else { "status": "awaiting", "personas": { } }


class FleetSizeCapIn( BaseModel ):
    """
    Body for PUT /api/arbiter/fleet-size-cap — the one number the operator is setting.

    `ge=1` is declared here rather than hand-rolled in the handler, so a nonsense
    value is refused by Pydantic with a 422 naming the field. The UPPER bound is NOT
    declared here and cannot be: the ceiling is `cc session fleet size cap maximum`,
    read at call time, so the handler checks it against the live key.
    """
    cap : int = Field( ge=1, description="The fleet-wide session cap to persist." )


def _live_fleet_counts():
    """
    The manager/worker split, counted the SAME way the spawn gate counts it.

    Ensures:
        - returns a fleet_size_cap.census() dict, or None when the fleet cannot be read
        - never raises

    🔴 IT USES THE GATE'S OWN CENSUS AND CLASSIFIER ON PURPOSE. A pane that counted
    the fleet by a second route would agree with the gate on every ordinary day and
    disagree on exactly the day somebody needed it — an operator would read "6 of 8"
    while the spawn path refused at 8. One derivation, or the two silently coincide
    until they do not.
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import (
            find_active_voice_persona_sessions )
        from lupin_cli.claude_code.hooks.lib.manager_figure import is_manager_figure
        from lupin_mcp import fleet_size_cap
        return fleet_size_cap.census( find_active_voice_persona_sessions(), is_manager_figure )
    except Exception:
        return None


def _fleet_size_cap_payload():
    """
    The dial's whole state: what is enforced, what the ceiling is, who is occupying it.

    Ensures:
        - returns { cap, ceiling, live } where `live` is the census dict or None
        - `cap` prefers the value ON DISK over the cached configuration singleton
        - never raises
    """
    from cosa.rest.dependencies.config import get_config_manager
    from lupin_mcp import fleet_size_cap

    try:
        config_mgr = get_config_manager()
    except Exception:
        config_mgr = None

    return {
        "cap"     : fleet_size_cap.resolve_fleet_cap(
                        config_mgr, disk_fn=fleet_size_cap.default_disk_cap_reader ),
        "ceiling" : fleet_size_cap.resolve_fleet_ceiling( config_mgr ),
        "live"    : _safe_live_counts(),
    }


def _safe_live_counts():
    """`_live_fleet_counts` with a second belt, so a patched-or-broken census costs the
    SPLIT and never the cap. The pane degrades to a number, never to an error."""
    try:
        return _live_fleet_counts()
    except Exception:
        return None


@router.get(
    "/arbiter/fleet-size-cap",
    summary     = "The fleet-size dial: the live cap and the configured ceiling",
    description = "Read-only. Returns { cap, ceiling } computed AT CALL TIME from the "
                  "configuration manager, so the operator control renders 1..ceiling "
                  "against the number the spawn path is actually enforcing. "
                  "Auth: X-API-Key or Bearer JWT — the same guard as the fleet pane, "
                  "because anyone who can see the fleet should see the cap governing it."
)
async def get_fleet_size_cap(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Serve the fleet-size dial's two numbers, read fresh on every call.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)

    Ensures:
        - returns { cap, ceiling } from resolve_fleet_cap / resolve_fleet_ceiling
        - reads the configuration manager LAZILY, inside the handler, so the values
          move when the INI moves rather than being frozen at import
        - `ceiling` is `cc session fleet size cap maximum` and is NEVER clamped to
          anything else — see below
        - never raises: an unreadable config falls back to the module defaults, the
          same fail-soft the spawn path uses, so the pane degrades to a number rather
          than to an error

    🔴 THE CEILING IS SERVED VERBATIM AND IS DELIBERATELY NOT CLAMPED — not to the
    persona pool, not to the live session count, not to anything. Rick ruled the maximum
    must be configurable so he can tweak it over time; a dial silently trimmed below the
    number he typed cannot be told apart from a key that was ignored. The control shows
    what the key says.

    🔨 IT IS NO LONGER READ-ONLY — CORRECTED 2026-09-04, AND THE OLD CLAIM IS NAMED
    RATHER THAN DELETED BECAUSE HALF OF IT WAS RIGHT. This docstring used to say a write
    "needs shared storage (a compose mount and an env var) and a change to the resolver".

    · THE STORAGE HALF WAS WRONG, and it was reasoned rather than measured. `docker
      inspect lupin-rest-dev` reports the checkout's `src` bind-mounted at
      `/var/lupin/src` with `rw=true`, and the host MCP process carries
      `LUPIN_ROOT=<the checkout>` with the same `Lupin: Development` block. Container
      and host already read and write ONE file. No compose change, no env var, no
      recreate.
    · THE RESOLVER HALF WAS RIGHT. `ConfigurationManager` is a process-lifetime
      singleton with no reload, so a write would have reached the file while the
      long-running MCP kept its boot-time cap. `resolve_fleet_cap` now takes a `disk_fn`
      and prefers the value on disk — see PUT below.

    ⚠️ `live` MAY BE None. A census that cannot be taken costs the SPLIT, never the cap:
    the pane degrades to a number rather than to an error.
    """
    return _fleet_size_cap_payload()


@router.put(
    "/arbiter/fleet-size-cap",
    summary     = "Set the fleet-size cap — writes through to configuration and persists",
    description = "Writes `cc session fleet size cap` to the configuration FILE and "
                  "returns what it ACTUALLY PERSISTED, re-read from disk. Refuses a "
                  "value outside 1..`cc session fleet size cap maximum`. "
                  "Auth: X-API-Key or Bearer JWT — the same guard as the GET."
)
async def put_fleet_size_cap(
    body                  : FleetSizeCapIn,
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Persist the operator's new fleet cap and report what the file now says.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - body.cap >= 1 (enforced by the model, not here)

    Ensures:
        - a cap above the live ceiling is REFUSED with 422 naming both numbers
        - on success the value is written to the configuration FILE, not only to
          the in-process singleton, and survives a restart
        - the in-process configuration manager is updated too, so this container's
          own next GET agrees with the disk instead of serving its boot-time value
        - RETURNS { cap, ceiling, live } built by re-reading the file — the `cap`
          in the response is what the FILE says, never what the request said
        - a refusal by the INI writer (key absent, or defined twice) surfaces as a
          409 carrying the writer's own message verbatim

    🔴 THE RESPONSE IS A RE-READ AND NOT AN ECHO, AND THAT IS THE POINT OF THE
    ENDPOINT. An echo makes the response unfalsifiable: it looks identical whether
    the write reached the disk, landed in a section nobody reads, or never happened.
    The client repaints the dial from this body, so an echo would move the slider to
    a number the spawn path is not enforcing — which is a dial that appears to work
    and governs nothing, the exact defect this endpoint exists to close.

    ⚠️ THE 409 IS A REFUSAL, NOT A CRASH. `locate_key` declines when the key is
    absent or defined twice, and its message names every line it found. Passing that
    through verbatim is what lets an operator fix the file; swallowing it and
    returning the old cap would report a successful no-op.
    """
    from fastapi import HTTPException
    from cosa.rest.dependencies.config import get_config_manager
    from lupin_mcp import fleet_size_cap
    from lupin_mcp import fleet_cap_ini_io

    try:
        config_mgr = get_config_manager()
    except Exception:
        config_mgr = None

    ceiling = fleet_size_cap.resolve_fleet_ceiling( config_mgr )
    if body.cap > ceiling:
        raise HTTPException(
            status_code = 422,
            detail      = f"Refusing to set the fleet cap to {body.cap}: the configured "
                          f"ceiling is {ceiling} (`{fleet_size_cap.FLEET_CEILING_KEY}`). "
                          f"Nothing was written. Raise that key first if {body.cap} is "
                          f"really what you want — it is deliberately not clamped here, "
                          f"because a value silently trimmed to {ceiling} cannot be told "
                          f"apart from a request that was ignored."
        )

    try:
        persisted = fleet_cap_ini_io.write_int_to_disk(
            fleet_size_cap.config_file_path(), fleet_size_cap.FLEET_CAP_KEY, body.cap )
    except ( fleet_cap_ini_io.KeyNotFound, fleet_cap_ini_io.KeyDefinedTwice ) as refusal:
        raise HTTPException( status_code=409, detail=str( refusal ) )
    except OSError as failure:
        raise HTTPException(
            status_code = 500,
            detail      = f"The fleet cap could not be written to the configuration "
                          f"file: {failure}. Nothing is guaranteed to have changed; "
                          f"read GET /api/arbiter/fleet-size-cap to see what it says now."
        )

    # Keep THIS process's cached singleton in step with the file it just wrote.
    # Without it the container would serve its boot-time cap from the very next GET
    # while the disk carried the new one — two numbers, one dial.
    if config_mgr is not None:
        try:
            config_mgr.set_config( fleet_size_cap.FLEET_CAP_KEY, persisted )
        except Exception:
            pass                      # the FILE is the source of truth; this is a cache

    return _fleet_size_cap_payload()
