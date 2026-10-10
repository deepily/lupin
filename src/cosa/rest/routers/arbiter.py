#!/usr/bin/env python3
"""
Heartbeat-arbiter fleet-snapshot and fleet-size-cap endpoints.

Mirrors `GET /api/queue/pool-status`: one queryable HTTP surface on `:7999` that returns
the arbiter's latest fleet snapshot. The snapshot holds every session's direct state and
honest last-seen liveness ages. An operator, a manager or a peer can then read true fleet
state from a distance. State is seen, never inferred.

Endpoints, all authenticated through `require_api_key_or_jwt` (an `X-API-Key` or a Bearer
JWT, the canonical machine-or-human credential):
    - GET  /api/arbiter/fleet-state    — the authoritative surface: a thin reverse-proxy
      that pulls the single-pane composite from the standalone lupin-arbiter-app service at
      `:8001/state`. `:8001` never pushes here.
    - GET  /api/arbiter/context-pressure — read-only per-persona context-headroom service.
      It pulls `:8001/state` and returns just the `context_pressure` section, a
      persona-keyed budget-headroom map.
    - GET  /api/arbiter/fleet-size-cap — the fleet-size dial: the enforced cap, the
      configured ceiling, and the live manager/worker split occupying it.
    - PUT  /api/arbiter/fleet-size-cap — set the cap. It writes through to the
      configuration file and returns what it re-read from disk, never an echo of the
      request, because the values are serialized and reused the next time.
    - GET  /api/arbiter/fleet-snapshot — legacy: read the cached snapshot.
    - POST /api/arbiter/fleet-snapshot — legacy: the in-process arbiter pushes its latest
      snapshot here, which updates the server singleton directly.

The standalone host-side lupin-arbiter-app service on `:8001` is authoritative. It exposes
`GET /state` (the single pane), and the `:7999` reverse-proxy `GET /api/arbiter/fleet-state`
pulls from it. The legacy in-process GET and POST `/api/arbiter/fleet-snapshot` pair stays
until the cutover, and both coexist behind a feature flag. After the cutover,
`/api/arbiter/fleet-state` wins. The in-process snapshot pair retires with the in-process
arbiter, which is gated off by the `arbiter in-process bootstrap enabled` flag. The old
rule that there is no standalone arbiter HTTP server is retired with it.
"""
from typing import Annotated, Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from cosa.rest.auth_middleware import require_admin
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest import arbiter_snapshot_store as snapshot_store


def _pull_arbiter_state( url: str, timeout: int ) -> Dict[ str, Any ]:   # pragma: no cover - literal httpx call boundary (live :8001 pull)
    """The one external IO boundary: GET `:8001/state` and return its JSON body."""
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
        - pulls :8001/state (:7999 never pushes to :8001) and returns its
          composite body verbatim when reachable
        - on any httpx failure (connect refused / timeout / non-2xx) returns an
          explicit { status: "unreachable", ... } envelope with null sections —
          a HTTP 200 (mirroring the awaiting idiom: the proxy is up, the upstream
          watcher is not), never a 5xx or a hung request
        - reads the upstream URL and timeout lazily from the shared config singleton
          (no module-scope ConfigurationManager, so import and collection never touch
          `LUPIN_CONFIG_MGR_CLI_ARGS`)
        - injects one top-level `app_timezone` field (the configured IANA zone,
          e.g. "America/New_York") into the otherwise-verbatim composite. This is the
          single deviation from verbatim-proxy, local to :7999 (no :8001 change). The
          client feeds it to Intl.DateTimeFormat to render the last-updated stamp in
          the operator's DST-aware zone. Omitted on the unreachable envelope by
          design, so the client falls back to the browser-local zone (display-only,
          never blocks the table).
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
    Reverse-proxy only the `context_pressure` section of :8001/state.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)

    Ensures:
        - pulls :8001/state (:7999 never pushes) and returns the
          `context_pressure` section verbatim when present
        - returns the explicit { status: "awaiting", personas: {} } placeholder
          when the upstream composite lacks the section (e.g. the deployed
          arbiter predates the writer) — never a bare null
        - on any httpx failure returns an explicit { status: "unreachable", ... }
          envelope with a null personas map — an HTTP 200 (the proxy is up, the
          upstream watcher is not), never a 5xx or a hung request
        - reads the upstream URL and timeout lazily from the shared config singleton
          (same keys as /arbiter/fleet-state)

    This is the dedicated public surface for the section. The section also rides the
    /fleet-state composite.
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
    Body for PUT /api/arbiter/fleet-size-cap, the one number the operator is setting.

    `ge=1` is declared here rather than hand-rolled in the handler, so Pydantic refuses
    a nonsense value with a 422 naming the field. The upper bound is not declared here
    and cannot be. The ceiling is `cc session fleet size cap maximum`, read at call time,
    so the handler checks it against the live key.
    """
    cap : int = Field( ge=1, description="The fleet-wide session cap to persist." )


def _live_fleet_counts():
    """
    The manager/worker split, counted the same way the spawn gate counts it.

    Ensures:
        - returns a fleet_size_cap.census() dict, or None when the fleet cannot be read
        - never raises

    It uses the gate's own census and classifier. A pane that counted the fleet by a
    second route would agree with the gate on an ordinary day and disagree on the day
    somebody needed it. An operator would read "6 of 8" while the spawn path refused at 8.
    One derivation is the rule, since two would coincide until they do not.
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_sessions
        from lupin_mcp import fleet_size_cap
        # 🔴 THE COUNTING PREDICATE, NOT THE AUTHORIZATION ONE — and this call site was
        # the SECOND place the defect lived. `is_manager_figure` classifies by persona
        # NAME and lets that name win over an explicit declared role, so the pane
        # reported a name-based split while the spawn gate reported a declaration-based
        # one. The docstring above promises exactly one derivation; until 2026-09-04 it
        # was true only in the sense that both call sites used the same WRONG one.
        # Same population as the gate, by the same call — row 9c3b817a. `require_persona`
        # is the POOL-OCCUPANCY filter and answers an allocation question; the pane is
        # showing who occupies the CAP, so it must count live seats including the ones
        # mid-boot with no persona yet. The docstring above promises one derivation, and
        # a differently-filtered second reading would break that quietly.
        unreadable = [ ]
        sessions   = find_active_sessions( require_persona=False, unreadable_out=unreadable )
        return fleet_size_cap.census( sessions, fleet_size_cap.counting_classifier_for( sessions ),
                                      unreadable=len( unreadable ) )
    except Exception:
        return None


def _fleet_size_cap_payload():
    """
    The dial's whole state: what is enforced, what the ceiling is, who is occupying it.

    Ensures:
        - returns { cap, ceiling, live, skeleton_crew } where `live` is the census dict or None
        - `skeleton_crew` is the switch state: on, since, set_by, settings_mute_while_off
        - `cap` prefers the value on disk over the cached configuration singleton
        - never raises
    """
    from cosa.rest.dependencies.config import get_config_manager
    from lupin_mcp import fleet_size_cap

    try:
        config_mgr = get_config_manager()
    except Exception:
        config_mgr = None

    from lupin_mcp import skeleton_crew
    return {
        "cap"           : fleet_size_cap.resolve_fleet_cap(
                              config_mgr, disk_fn=fleet_size_cap.default_disk_cap_reader ),
        "ceiling"       : fleet_size_cap.resolve_fleet_ceiling( config_mgr ),
        "live"          : _safe_live_counts(),
        "skeleton_crew" : skeleton_crew.describe(),
    }


def _safe_live_counts():
    """
    `_live_fleet_counts` with a second guard, so a broken census costs the split only.

    A patched or broken census never costs the cap. The pane degrades to a number,
    never to an error.
    """
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
def get_fleet_size_cap(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Serve the fleet-size dial's two numbers, read fresh on every call.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)

    Ensures:
        - returns { cap, ceiling } from resolve_fleet_cap / resolve_fleet_ceiling
        - reads the configuration manager lazily, inside the handler, so the values
          move when the INI moves rather than being frozen at import
        - `ceiling` is `cc session fleet size cap maximum` and is never clamped to
          anything else — see below
        - never raises: an unreadable config falls back to the module defaults, the
          same fail-soft the spawn path uses, so the pane degrades to a number rather
          than to an error

    The ceiling is served verbatim and is not clamped to the persona pool, to the live
    session count, or to anything else. The maximum must be configurable so the operator
    can tweak it over time. A dial silently trimmed below the number typed cannot be told
    apart from a key that was ignored. The control shows what the key says.

    The dial is writable, through PUT below. The container and the host process
    read and write one file: the checkout's `src` is bind-mounted read-write in
    the container, and the host MCP process carries `LUPIN_ROOT` with the same
    `Lupin: Development` block. No compose change, environment variable or recreate is
    needed. `ConfigurationManager` is a process-lifetime singleton with no reload, so a
    write alone would reach the file while a long-running process kept its boot-time cap.
    `resolve_fleet_cap` therefore takes a `disk_fn` and prefers the value on disk.

    `live` may be None. A census that cannot be taken costs the split, never the cap.
    The pane degrades to a number rather than to an error.
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
def put_fleet_size_cap(
    body                  : FleetSizeCapIn,
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Persist the operator's new fleet cap and report what the file now says.

    Requires:
        - authenticated caller (X-API-Key or Bearer JWT)
        - body.cap >= 1 (enforced by the model, not here)

    Ensures:
        - a cap above the live ceiling is refused with 422 naming both numbers
        - on success the value is written to the configuration file, not only to
          the in-process singleton, and survives a restart
        - the in-process configuration manager is updated too, so this container's
          own next GET agrees with the disk instead of serving its boot-time value
        - returns { cap, ceiling, live } built by re-reading the file — the `cap`
          in the response is what the file says, never what the request said
        - a refusal by the INI writer (key absent, or defined twice) surfaces as a
          409 carrying the writer's own message verbatim

    The response is a re-read, not an echo, which is what the endpoint exists for. An echo
    makes the response unfalsifiable. It looks identical whether the write reached the
    disk, landed in a section nobody reads, or never happened. The client repaints the dial
    from this body. An echo would move the slider to a number the spawn path is not
    enforcing, a dial that appears to work and governs nothing.

    The 409 is a refusal, not a crash. `locate_key` declines when the key is absent or
    defined twice, and its message names every line it found. Passing that through
    verbatim lets an operator fix the file. Swallowing it and returning the old cap would
    report a successful no-op.
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
                          f"ceiling is {ceiling}, which is the operator's decision. "
                          f"Nothing was written. The value is deliberately not clamped here, "
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


class SkeletonCrewIn( BaseModel ):
    """
    Body for PUT /api/arbiter/skeleton-crew.

    `on` is a bare JSON boolean. Any other field, and any other type, is a 422.
    """
    model_config = ConfigDict( extra="forbid" )
    on : StrictBool = Field( description="True turns skeleton crew on, false turns it off." )


async def refuse_api_key_flipper(
    x_api_key     : Annotated[ Optional[ str ], Header() ] = None,
    authorization : Annotated[ Optional[ str ], Header() ] = None
) -> None:
    """
    Turn away a caller that presents only an API key, before the admin check runs.

    Ensures:
        - raises 403 when X-API-Key is present and Authorization is not, which is how a
          Claude session calls. A manager's own key therefore cannot flip the switch
        - otherwise returns None, and the admin check decides
    """
    if x_api_key and not authorization:
        raise HTTPException(
            status_code = 403,
            detail      = "Only an administrator may change the skeleton crew switch."
        )


def _flip_message( on: bool ) -> str:
    """
    The words the live sessions receive when the switch flips.

    Ensures:
        - on: tells workers to finish the step and stop, and managers to reap them
        - off: tells managers they may spawn inside the cap
    """
    if on:
        return ( "Skeleton crew is ON. No spawning and no asking for seats. Each worker: finish "
                 "your current step, write your memento and stop. Each manager: reap your "
                 "workers once they are done and take over what is left." )
    return ( "Skeleton crew is OFF. Managers may spawn the seats they need inside the cap, and "
             "may ask the operator to raise the cap by just enough for the work in hand." )


async def _announce_flip( on: bool, authenticated_user_id: str, notification_queue: Any = None ) -> None:
    """
    Tell every live session the switch flipped, and never fail the flip because of it.

    Requires:
        - the flip is already written to the file

    Ensures:
        - posts one acknowledged broadcast through the commons broadcast route's handler
        - resolves the notification queue itself when none is given
        - a failure is printed and swallowed
    """
    try:
        from cosa.rest.routers import commons
        queue = notification_queue if notification_queue is not None else commons.get_notification_queue()
        body  = commons.BroadcastRequestBody( message=_flip_message( on ), require_ack=True )
        await commons.post_broadcast_to_cc_sessions( body, authenticated_user_id, queue )
    except Exception as error:
        print( f"[SKELETON-CREW] flip broadcast failed: {type( error ).__name__}: {error}", flush=True )


@router.put(
    "/arbiter/skeleton-crew",
    summary     = "Admin: turn skeleton crew on or off",
    description = "Body { on: bool }. Writes `cc session skeleton crew enabled` to the "
                  "configuration file, tells the live sessions, and returns the same body as "
                  "GET /api/arbiter/fleet-size-cap, re-read from the file. Admin login only: "
                  "an API-key caller is refused with 403 and nothing changes."
)
async def put_skeleton_crew(
    body                  : SkeletonCrewIn,
    _no_key               : Annotated[ None, Depends( refuse_api_key_flipper ) ],
    user                  : Annotated[ Dict, Depends( require_admin ) ],
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ]
):
    """
    Flip the switch and report what the file now says.

    Requires:
        - an administrator login (403 for an API key alone or a non-admin user)
        - body.on is a bare boolean (422 otherwise)

    Ensures:
        - the attribution record is written first and the configuration file second
        - a missing key is inserted after the cap maximum line instead of refused
        - a key defined twice answers 409 with the writer's own message, writing nothing
        - an OS error answers 500 naming the cause, and nothing is announced
        - on success the live sessions are told, and a failed broadcast does not fail the flip
        - returns { cap, ceiling, live, skeleton_crew } read back from the file
        - never copies the value into the configuration manager. The file is the one value
    """
    from lupin_mcp import fleet_cap_ini_io, fleet_size_cap, skeleton_crew
    who = user.get( "email" ) or user.get( "uid" ) or "unknown"
    try:
        skeleton_crew.write_state_file( body.on, who )
        fleet_cap_ini_io.write_bool_to_disk(
            skeleton_crew.ini_path(), skeleton_crew.SKELETON_CREW_KEY, body.on,
            insert_after=fleet_size_cap.FLEET_CEILING_KEY )
    except ( fleet_cap_ini_io.KeyNotFound, fleet_cap_ini_io.KeyDefinedTwice ) as refusal:
        raise HTTPException( status_code=409, detail=str( refusal ) )
    except OSError as failure:
        raise HTTPException(
            status_code = 500,
            detail      = f"The skeleton crew switch could not be written: {failure}. "
                          f"Nothing is guaranteed to have changed; read "
                          f"GET /api/arbiter/fleet-size-cap to see what it says now."
        )
    await _announce_flip( body.on, authenticated_user_id, None )
    return _fleet_size_cap_payload()
