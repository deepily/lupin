"""
Per-session voice persona endpoints.

Each new Claude Code session is uniformly randomly assigned a voice/persona
at SessionStart from a 6-voice allocatable pool so the user can audibly
distinguish parallel sessions in the notifications UI accordion. Sam (the
global ElevenLabs default) is reserved as the system-wide TTS default voice
and is NOT in the allocatable pool.

The bridge file at ~/.claude/sessions/cc-{PPID}.json is the canonical state.
This module mirrors `speakerphone.py` structurally:
    - module-level asyncio.Lock for atomic scan→pick→write
    - dependency-injected ConfigurationManager + WebSocketManager
    - bridge file is ground truth, WS broadcast is best-effort confirmation
    - dead-PID bridges are filtered on every read (implicit sweeper)

Endpoints:
    GET  /api/cosa-voice/voice-persona/{session_id}            — read current persona
    POST /api/cosa-voice/voice-persona/{session_id}/allocate   — atomic claim
    POST /api/cosa-voice/voice-persona/{session_id}/release    — clear bridge field
    GET  /api/cosa-voice/voice-persona/pool                    — diagnostics snapshot

Orthogonal to speakerphone mode (Phase 3 of solo/chorus refactor): a session
can have a persona regardless of speakerphone_on state, and solo-mode's
displacement scan does NOT touch the voice_persona field.

See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md
"""

import asyncio
from typing import Annotated, Optional

import httpx
from fastapi          import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic         import BaseModel

import cosa.utils.util as du

from ..middleware.api_key_auth import require_api_key_or_jwt
from ..notification_fifo_queue import NotificationFifoQueue

from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_voice_persona, set_voice_persona, find_active_voice_persona_sessions,
    find_session_path_by_id, build_sender_id_for_cc
)

from ..voice_persona_helpers import (
    load_persona_pool_from_config, allocate_persona_for_session,
    load_overflow_persona_from_config, allocate_requested_persona_for_session,
    allocate_persona_chain_for_session, parse_declared_managers
)
from lupin_mcp.persona_normalization import canonical_persona_key


router = APIRouter( prefix="/api/cosa-voice", tags=[ "cosa-voice" ] )

# Module-level lock serializes scan→pick→write so two parallel /allocate
# calls can't both pick the same persona. Single-process uvicorn assumed
# (same caveat as `speakerphone.py` `_speakerphone_lock`). On /release there is
# nothing to coordinate, so we skip the lock for that path.
_voice_persona_lock = asyncio.Lock()


def _resolve_manager_persona( worker_session_id ):
    """
    Resolve the spawning manager's persona for the focus-bar manager badge
    (2026-06-08, Rick). A worker's bridge carries `spawned_by` = the MANAGER's
    session_id (set by session_spawner at spawn). We read that, then read the
    manager's own voice_persona, and shape a compact badge dict (glyph + color +
    initial) the client superimposes on the worker's focus-bar avatar.

    Requires:
        - worker_session_id is a non-empty session_id string

    Ensures:
        - returns { "icon", "color", "name", "initial" } when the worker was
          spawned by a manager whose persona is resolvable
        - returns None for a top-level / root session (no `spawned_by`), an
          unresolvable manager persona, or any read failure (NEVER raises — this
          runs inside the best-effort voice_persona_assigned emit path)
    """
    import json
    try:
        path = find_session_path_by_id( worker_session_id )
        if not path:
            return None
        with open( path ) as f:
            data = json.load( f )
        manager_session_id = data.get( "spawned_by" )
        if not manager_session_id:
            return None
        manager_persona = get_voice_persona( manager_session_id )
        if not isinstance( manager_persona, dict ) or not manager_persona:
            return None
        name = manager_persona.get( "name" ) or ""
        return {
            "icon"    : manager_persona.get( "icon" ),
            "color"   : manager_persona.get( "color" ),
            "name"    : name,
            "initial" : name[ :1 ].upper() if name else "",
        }
    except Exception:
        return None


# ── Dependency injection ─────────────────────────────────────────────────────

def get_notification_queue():
    """Dependency to get the singleton NotificationFifoQueue from main module."""
    import lupin_app.main as main_module
    return main_module.jobs_notification_queue


def get_config_manager():
    """Dependency to get a ConfigurationManager with the standard env var."""
    from cosa.config.configuration_manager import ConfigurationManager
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "/voice-persona/pool",
    summary     = "Pool snapshot — allocatable pool, occupied names, free slots",
    description = "Returns the configured pool plus current occupancy. Diagnostics endpoint; does not allocate."
)
async def get_voice_persona_pool(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    config_mgr = Depends( get_config_manager )
) -> JSONResponse:
    """
    Return the configured pool, the set of currently-occupied persona names,
    and the names that are free for allocation right now.

    Live-PID dead-bridge filter applies (so a stale persona on a dead-PID
    bridge counts as free).
    """
    pool   = load_persona_pool_from_config( config_mgr )
    stale_seconds = config_mgr.get(
        "cc session voice persona stale threshold seconds",
        default=43200, return_type="int", silent=True
    )
    active = find_active_voice_persona_sessions( stale_threshold_seconds=stale_seconds )

    occupied_names = sorted( {
        p[ "name" ] for _path, _sid, p in active
        if isinstance( p, dict ) and p.get( "name" )
    } )
    free_names = [ p[ "name" ] for p in pool if p[ "name" ] not in occupied_names ]

    return JSONResponse( content={
        "pool"           : pool,
        "occupied_names" : occupied_names,
        "free_names"     : free_names,
        "active_sessions": [
            { "session_id": sid, "persona_name": p.get( "name" ), "borrowed": p.get( "borrowed", False ), "assigned_at": p.get( "assigned_at" ) }
            for _path, sid, p in active
            if isinstance( p, dict )
        ]
    } )


@router.get(
    "/voice-persona/{session_id}",
    summary     = "Read voice persona for a session",
    description = "Returns the voice_persona dict from the cosa-voice session bridge file, or null when none is set."
)
async def get_voice_persona_endpoint(
    session_id           : str,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> JSONResponse:
    """
    Read voice_persona from the bridge for the given session_id.
    """
    if not find_session_path_by_id( session_id ):
        raise HTTPException( status_code=404, detail=f"No active session bridge found for session_id={session_id}" )

    persona = get_voice_persona( session_id )
    return JSONResponse( content={ "session_id": session_id, "voice_persona": persona } )


@router.post(
    "/voice-persona/{session_id}/allocate",
    summary     = "Allocate a voice persona for a session",
    description = "Idempotent: if a persona is already set on the bridge and no `requested_persona_name`/`persona_chain` query param is supplied, returns it without re-allocating. When `requested_persona_name` is supplied: atomically allocates the named persona with strict 422/409 errors on miss. When `persona_chain` is supplied: STRICT ordered-fallback walk — comma-separated names tried in order, first FREE one allocated; a `*` element means 'then take anything free'; a chain exhausted without `*` is a LOUD fail (409 + `voice_persona_conflict` notification, NO silent random fallback). Used by the SessionStart hook for both spawn-injected and per-repo env-var chains. Mutually exclusive with `requested_persona_name`. `declared_managers` (CSV, optional — the hook threads its project's COSA_VOICE_MANAGERS__<PROJECT> roster) reserves those names OUT of the random and chain-`*` draws; explicit `requested_persona_name` and NAMED chain elements can still claim them."
)
async def allocate_voice_persona_endpoint(
    session_id            : str,
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ],
    previous_persona_name : Optional[ str ] = None,
    requested_persona_name: Annotated[ Optional[ str ], Query( min_length=1, max_length=64 ) ] = None,
    persona_chain         : Annotated[ Optional[ str ], Query( min_length=1, max_length=256 ) ] = None,
    declared_managers     : Annotated[ Optional[ str ], Query( min_length=1, max_length=256 ) ] = None,
    notification_queue    : NotificationFifoQueue = Depends( get_notification_queue ),
    config_mgr            = Depends( get_config_manager )
) -> JSONResponse:
    """
    Atomically allocate a persona for the given session.

    Four operating modes, selected by `requested_persona_name` / `persona_chain`:

    1. **No request** (legacy SessionStart hook contract). Idempotent: if
       the bridge already has a non-null voice_persona, return it as-is.
       Otherwise pick uniformly at random from the unallocated pool.

    2. **Request matches existing** (idempotent same-name request). Return
       existing as-is, `newly_allocated=False`, `swapped=False`.

    3. **Request differs from existing OR no existing** (request-or-swap).
       Atomically (a) verify the requested name is in the pool (else 422)
       (b) verify it is not held by another session (else 409 with holding
       persona name + available pool names in the response body) (c) write
       the new persona to the bridge, releasing the prior allocation if
       any. Broadcasts `voice_persona_assigned` + (on detected swap) a
       "Voice re-assigned: X → Y" announcement.

    4. **Chain** (`persona_chain`, SessionStart hook path — replaced the
       retired `preferred_persona_name` soft path 2026-06-11). STRICT
       ordered-fallback walk: each named element tried in order, first FREE
       one wins; `*` means "then take anything free"; misses before the
       satisfying element are reported via a `voice_persona_conflict`
       notification only when the wildcard had to fire. A chain exhausted
       without `*` raises 409 AND pushes the conflict notification — the
       session stays persona-less (Sam TTS fallback), predictable-fail by
       design (Rick, 2026-06-11). Like the old soft path, a chain does NOT
       override an existing allocation (idempotent across /clear).
       See: src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md

    When `previous_persona_name` is supplied AND a new persona is actually
    allocated, the "Voice re-assigned" announcement uses that name. When a
    swap is detected via the bridge's prior persona, that name is used
    instead. Used by the SessionStart hook on /clear-with-overwrite and by
    the /plan-session-start slash command to make voice changes audible.

    Returns 409 Conflict body shape (per Rachel's R1 design):
        { "detail": {
            "message": "...", "requested": "...",
            "holding_session_id": "...", "holding_persona_name": "...",
            "available": [<pool names not in use>]
        } }

    Returns 422 Unprocessable Entity body shape (requested name not in pool):
        { "detail": {
            "message": "...", "requested": "...",
            "available": [<pool names not in use>]
        } }
    """
    if not find_session_path_by_id( session_id ):
        raise HTTPException( status_code=404, detail=f"No active session bridge found for session_id={session_id}" )

    # Strict single-name + chain are mutually exclusive — the strict path
    # surfaces 422/409 to a user who typed `/plan-session-start María`,
    # while the chain path encodes its own ordered-fallback error semantics.
    # Mixing them would conflate error surfaces.
    if requested_persona_name is not None and persona_chain is not None:
        raise HTTPException(
            status_code=422,
            detail="`requested_persona_name` and `persona_chain` are mutually exclusive — supply exactly one"
        )

    # Outer fast-path: no request + already allocated → legacy idempotency
    # contract holds; return existing without acquiring the lock.
    # Note: `persona_chain` does NOT override an existing allocation
    # (Path A — preserve persona across /clear for narrative continuity).
    existing = get_voice_persona( session_id )
    if existing is not None and requested_persona_name is None:
        return JSONResponse( content={
            "session_id"          : session_id,
            "voice_persona"       : existing,
            "newly_allocated"     : False,
            "swapped"             : False,
            "broadcast_delivered" : False
        } )

    # Set early so the post-lock notification block can always reference it.
    # Only the chain branch ever populates it (wildcard fired after named
    # misses); the strict-request and plain-allocation paths leave it None.
    chain_conflict: Optional[ dict ] = None

    # The chain walk's per-entry outcomes, threaded onto the SUCCESS result so a
    # caller can tell a clean first-element hit from a degraded landing — a named
    # element skipped because it is nonexistent (not_in_pool) or occupied. Reuses
    # the list allocate_persona_chain_for_session already computed (row 462b985c);
    # NOT a second derivation. Distinct from chain_conflict: that is wildcard-only
    # and drives the human notification; this is the full outcomes on every chain
    # success, so a nonexistent name that lands on a later NAMED element (silent
    # under chain_conflict, by design) is still visible to the caller. An outcome
    # you cannot see is the same as one that did not happen (session_spawner.py:1004).
    # None on the non-chain paths.
    chain_outcomes: Optional[ dict ] = None

    async with _voice_persona_lock:
        # Re-read bridge under the lock — another request may have written
        # between the outer check and acquisition.
        existing = get_voice_persona( session_id )

        if requested_persona_name is not None:
            # Request-or-swap path. Identity parity (Phase 2): compare the two
            # persona identity values by the one canonical key so a re-request of
            # the SAME persona under accented/punctuated spelling ("María",
            # "Mr. Radio") is recognized as idempotent rather than a swap. Both
            # compare sides moved in lockstep.
            normalized_request = canonical_persona_key( requested_persona_name )

            if existing is not None and canonical_persona_key( existing.get( "name", "" ) ) == normalized_request:
                # Same-as-existing → idempotent return
                return JSONResponse( content={
                    "session_id"          : session_id,
                    "voice_persona"       : existing,
                    "newly_allocated"     : False,
                    "swapped"             : False,
                    "broadcast_delivered" : False
                } )

            result = allocate_requested_persona_for_session( config_mgr, session_id, requested_persona_name )

            if result is None:
                raise HTTPException(
                    status_code=500,
                    detail="Voice persona pool is empty or misconfigured (check `cc session voice persona pool` in lupin-app.ini)"
                )

            if result[ "status" ] == "not_in_pool":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message"   : f"Requested persona '{requested_persona_name}' is not in the configured pool",
                        "requested" : requested_persona_name,
                        "available" : result[ "available" ]
                    }
                )

            if result[ "status" ] == "occupied":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message"              : f"Requested persona '{result[ 'holding_persona_name' ]}' is currently held by another session",
                        "requested"            : requested_persona_name,
                        "holding_session_id"   : result[ "holding_session_id" ],
                        "holding_persona_name" : result[ "holding_persona_name" ],
                        "available"            : result[ "available" ]
                    }
                )

            persona   = result[ "persona" ]
            swap_from = existing.get( "name" ) if existing else None

            ok = set_voice_persona( session_id, persona )
            if not ok:  # pragma: no branch - async-with __aexit__ trailing-if artifact: last stmt in the requested-path branch inside the `async with` lock, so the ok=True false-arc exit (278->346) routes through the implicit __aexit__ and is not a markable bytecode edge though the swap-success path is exercised; both arms (swap-success + 500) are tested
                raise HTTPException( status_code=500, detail=f"Bridge write failed for session_id={session_id}" )

        else:
            # No-request path. Existing might have appeared during the
            # outer-check → lock-acquire window (race protection).
            if existing is not None:
                return JSONResponse( content={
                    "session_id"          : session_id,
                    "voice_persona"       : existing,
                    "newly_allocated"     : False,
                    "swapped"             : False,
                    "broadcast_delivered" : False
                } )

            # Chain branch (SessionStart hook path — spawn-injected or per-repo
            # env-var chain). STRICT ordered-fallback walk: first FREE element
            # wins; `*` = "then take anything free"; exhaustion without `*` is
            # a LOUD predictable fail (409 + conflict notify, NO silent random).
            # See: src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md
            # Reserve-from-random (Rick, 2026-06-11): the SessionStart hook
            # threads its project's COSA_VOICE_MANAGERS__<PROJECT> roster as
            # a CSV `declared_managers` query param on BOTH the chain and the
            # plain-random calls; the same parser as the env reader keeps the
            # two carriers from drifting. Declared names are excluded from
            # random + `*` draws only — the strict path above stays
            # reservation-blind (that is how managers claim their names).
            declared = parse_declared_managers( declared_managers ) or None

            if persona_chain is not None:
                chain_result = allocate_persona_chain_for_session(
                    config_mgr, session_id, persona_chain, declared_managers=declared
                )
                if chain_result[ "status" ] == "pool_error":
                    raise HTTPException(
                        status_code=500,
                        detail="Voice persona pool is empty or misconfigured (check `cc session voice persona pool` in lupin-app.ini)"
                    )
                if chain_result[ "status" ] == "empty_chain":
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "message" : "`persona_chain` parsed to zero elements — supply comma-separated persona names and/or `*`",
                            "chain"   : persona_chain
                        }
                    )
                if chain_result[ "status" ] == "exhausted":
                    # LOUD predictable fail: every named element missed and no
                    # wildcard was present. Push the conflict notification
                    # BEFORE raising — the 409 alone would be invisible to a
                    # user listening at a distance.
                    try:
                        missed = "; ".join(
                            f"{o[ 'name' ]} held by session {o[ 'holding_session_id' ][ :8 ]}"
                            if o[ "status" ] == "occupied"
                            else f"{o[ 'name' ]} not in pool"
                            for o in chain_result[ "outcomes" ]
                        )
                        notification_queue.push_notification(
                            message            = (
                                f"Persona chain '{persona_chain}' exhausted — no element could be allocated "
                                f"({missed}). Session {session_id[ :8 ]} has NO persona; falling back to Sam for TTS."
                            ),
                            type               = "voice_persona_conflict",
                            priority           = "high",
                            user_id            = authenticated_user_id,
                            sender_id          = build_sender_id_for_cc( session_id ),
                            voice_persona      = None,
                            suppress_ding      = False,
                            response_requested = False,
                            payload            = {
                                "kind"     : "chain_exhausted",
                                "chain"    : persona_chain,
                                "outcomes" : chain_result[ "outcomes" ],
                                "available": chain_result[ "available" ]
                            }
                        )
                    except Exception as ws_err:
                        print( f"[VOICE-PERSONA] ⚠️ Chain-exhausted notification push failed for session {session_id}: {ws_err}" )
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message"  : f"Persona chain '{persona_chain}' exhausted — no element could be allocated",
                            "chain"    : persona_chain,
                            "outcomes" : chain_result[ "outcomes" ],
                            "available": chain_result[ "available" ]
                        }
                    )
                persona = chain_result[ "persona" ]
                # Thread the walk's EXISTING per-entry outcomes onto the result,
                # regardless of whether the wildcard fired — this is what lets a
                # caller distinguish a degraded landing (a nonexistent/occupied
                # named element was skipped) from a clean first-element hit.
                chain_outcomes = {
                    "satisfied_by"  : chain_result.get( "satisfied_by" ),
                    "wildcard_used" : chain_result[ "wildcard_used" ],
                    "outcomes"      : chain_result[ "outcomes" ],
                }
                if chain_result[ "wildcard_used" ] and chain_result[ "outcomes" ]:
                    # Named elements missed and the wildcard had to fire —
                    # surface WHO is holding the preferred names so the user
                    # can reclaim them. Landing on a later NAMED element is
                    # expressed intent and stays silent.
                    chain_conflict = {
                        "kind"     : "wildcard_fallback",
                        "chain"    : persona_chain,
                        "outcomes" : chain_result[ "outcomes" ]
                    }
            else:
                persona = allocate_persona_for_session( config_mgr, session_id, declared_managers=declared )
                if persona is None:
                    raise HTTPException(
                        status_code=500,
                        detail="Voice persona pool is empty or misconfigured (check `cc session voice persona pool` in lupin-app.ini)"
                    )

            ok = set_voice_persona( session_id, persona )
            if not ok:
                raise HTTPException( status_code=500, detail=f"Bridge write failed for session_id={session_id}" )

            swap_from = None

    # Route through the canonical notification subsystem with a custom type
    # value rather than inventing a new top-level WS event. The notification
    # arrives at the client as `notification_queue_update` carrying
    # notification.type = "voice_persona_assigned"; the client dispatches
    # inside handleNotificationUpdate.
    # See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
    broadcast_delivered = False
    try:
        notification_queue.push_notification(
            message            = "",
            type               = "voice_persona_assigned",
            user_id            = authenticated_user_id,
            sender_id          = build_sender_id_for_cc( session_id ),
            voice_persona      = persona,
            suppress_ding      = True,
            response_requested = False,
            payload            = { "session_id"     : session_id,
                                   "manager_persona": _resolve_manager_persona( session_id ) }
        )
        broadcast_delivered = True
    except Exception as ws_err:
        print( f"[VOICE-PERSONA] ⚠️ Notification push failed for session {session_id}: {ws_err}" )

    # Chain wildcard-fallback notification. Fired only when the caller
    # supplied `persona_chain`, every NAMED element missed, and the `*`
    # wildcard fired — the user hears which sessions hold their preferred
    # names (so they can reclaim them) or that the chain names are unknown.
    # Landing on a later NAMED chain element is expressed intent → silent.
    # Chain EXHAUSTION (no wildcard) is handled inside the lock above: 409
    # + its own conflict notification, no persona allocated.
    if chain_conflict is not None:
        try:
            missed_parts = []
            for outcome in chain_conflict[ "outcomes" ]:
                if outcome[ "status" ] == "occupied":
                    missed_parts.append( f"{outcome[ 'name' ]} is held by session {outcome[ 'holding_session_id' ][ :8 ]}" )
                else:  # "not_in_pool"
                    missed_parts.append( f"{outcome[ 'name' ]} is not in the configured pool" )
            conflict_msg = (
                f"Persona chain '{chain_conflict[ 'chain' ]}': {'; '.join( missed_parts )}. "
                f"Allocated {persona[ 'display_name' ]} via the wildcard instead."
            )
            notification_queue.push_notification(
                message            = conflict_msg,
                type               = "voice_persona_conflict",
                priority           = "high",
                user_id            = authenticated_user_id,
                sender_id          = build_sender_id_for_cc( session_id ),
                voice_persona      = persona,
                suppress_ding      = False,
                response_requested = False,
                payload            = chain_conflict
            )
        except Exception as ws_err:
            print( f"[VOICE-PERSONA] ⚠️ Chain conflict notification push failed for session {session_id}: {ws_err}" )

    # "Voice re-assigned" audible handoff. Either source — the hook's
    # previous_persona_name query param OR a detected bridge-side swap —
    # triggers the announcement so the voice change is audible.
    announce_previous = previous_persona_name or swap_from
    if announce_previous and announce_previous != persona[ "name" ]:
        try:
            notification_queue.push_notification(
                message            = f"Voice re-assigned: {announce_previous} → {persona[ 'display_name' ]}",
                type               = "task",
                priority           = "medium",
                user_id            = authenticated_user_id,
                sender_id          = build_sender_id_for_cc( session_id ),
                voice_persona      = persona,
                suppress_ding      = False,
                response_requested = False
            )
        except Exception as ws_err:
            print( f"[VOICE-PERSONA] ⚠️ Re-assigned announcement push failed for session {session_id}: {ws_err}" )

    return JSONResponse( content={
        "session_id"          : session_id,
        "voice_persona"       : persona,
        "newly_allocated"     : True,
        "swapped"             : swap_from is not None,
        "broadcast_delivered" : broadcast_delivered,
        "chain_conflict"      : chain_conflict,
        "chain_outcomes"      : chain_outcomes
    } )


@router.post(
    "/voice-persona/{session_id}/release",
    summary     = "Release the voice persona allocated to a session",
    description = "Clears the voice_persona field on the bridge and broadcasts a voice_persona_released event."
)
async def release_voice_persona_endpoint(
    session_id           : str,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    notification_queue   : NotificationFifoQueue = Depends( get_notification_queue )
) -> JSONResponse:
    """
    Release the persona for the given session (clear bridge field).

    Idempotent: clearing an already-empty slot returns 200 with released=False.
    """
    if not find_session_path_by_id( session_id ):
        raise HTTPException( status_code=404, detail=f"No active session bridge found for session_id={session_id}" )

    existing = get_voice_persona( session_id )
    if existing is None:
        return JSONResponse( content={
            "session_id"          : session_id,
            "released"            : False,
            "broadcast_delivered" : False
        } )

    ok = set_voice_persona( session_id, None )
    if not ok:
        raise HTTPException( status_code=500, detail=f"Bridge write failed for session_id={session_id}" )

    # Route through the canonical notification subsystem with a custom type value.
    # See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
    broadcast_delivered = False
    try:
        notification_queue.push_notification(
            message            = "",
            type               = "voice_persona_released",
            user_id            = authenticated_user_id,
            sender_id          = build_sender_id_for_cc( session_id ),
            voice_persona      = { "name": existing.get( "name" ), "released": True },
            suppress_ding      = True,
            response_requested = False,
            payload            = { "session_id": session_id }
        )
        broadcast_delivered = True
    except Exception as ws_err:
        print( f"[VOICE-PERSONA] ⚠️ Notification push failed for session {session_id}: {ws_err}" )

    return JSONResponse( content={
        "session_id"          : session_id,
        "released"            : True,
        "released_persona"    : existing,
        "broadcast_delivered" : broadcast_delivered
    } )


# ── Voice sample endpoint (reference page) ───────────────────────────────────

class VoicePersonaSampleRequest( BaseModel ):
    voice_id: str
    text    : str


@router.post(
    "/voice-persona/sample",
    summary     = "Synthesize a voice sample for the persona-reference page",
    description = "Returns audio/mpeg bytes inline. The voice_id MUST belong to the configured persona pool — arbitrary voice_ids are rejected so this endpoint cannot be used as a general-purpose TTS oracle.",
    responses   = {
        200: { "content": { "audio/mpeg": {} } },
        400: { "description": "voice_id is not in the configured persona pool" },
        503: { "description": "ElevenLabs API unavailable or returned an error" }
    }
)
async def voice_persona_sample(
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    body                 : VoicePersonaSampleRequest = Body( ... ),
    config_mgr           = Depends( get_config_manager )
) -> Response:
    """
    Synthesize a short voice sample for the dev-tools persona-reference page.

    Why a separate endpoint (vs. /api/get-speech-elevenlabs): the existing
    streaming TTS path delivers PCM chunks over WebSocket and requires an
    open audio session — appropriate for the live notification UI but heavy
    for a static reference page that just needs to play six sample clips.
    This endpoint calls the ElevenLabs HTTP TTS API and returns the audio
    as a single response body, so the page can `<audio>.src = blobURL` it.

    Pool-membership check: the voice_id must match an entry in the
    configured persona pool (`cc session voice persona pool` in
    lupin-app.ini). This prevents the endpoint from being used to burn
    ElevenLabs quota on arbitrary voice_ids.

    Requires:
        - body.voice_id is a non-empty string
        - body.text is a non-empty string
        - voice_id matches an entry in load_persona_pool_from_config(config_mgr)
        - ElevenLabs API key is reachable via du.get_api_key("eleven11")

    Ensures:
        - Returns 200 + audio/mpeg bytes on success
        - Returns 400 if voice_id is not in pool
        - Returns 503 if ElevenLabs upstream fails
        - Never raises (all paths return Response or JSONResponse)
    """
    if not body.voice_id or not body.text:
        raise HTTPException( status_code=400, detail="voice_id and text are both required" )

    pool      = load_persona_pool_from_config( config_mgr )
    pool_ids  = { p[ "voice_id" ] for p in pool if p.get( "voice_id" ) }
    # Sam is the overflow persona — accept his voice_id (system TTS default) too,
    # so the persona-reference page can play a Sam sample alongside pool samples.
    overflow_persona = load_overflow_persona_from_config( config_mgr )
    if overflow_persona and overflow_persona.get( "voice_id" ):
        pool_ids.add( overflow_persona[ "voice_id" ] )
    if body.voice_id not in pool_ids:
        raise HTTPException(
            status_code=400,
            detail=f"voice_id {body.voice_id!r} is not in the configured persona pool. Allowed: {sorted( pool_ids )}"
        )

    api_key = du.get_api_key( "eleven11" )
    if not api_key:
        raise HTTPException( status_code=503, detail="ElevenLabs API key not available on server" )

    # Match the streaming path's defaults so the reference samples sound
    # representative of what the live notification UI plays. Profile keys
    # mirror the "balanced" profile from speech.py:846-855.
    model_id          = config_mgr.get( "elevenlabs tts default model",          default="eleven_turbo_v2_5", silent=True )
    stability         = config_mgr.get( "elevenlabs tts profile balanced stability",         default=0.5, return_type="float", silent=True )
    similarity_boost  = config_mgr.get( "elevenlabs tts profile balanced similarity boost",  default=0.8, return_type="float", silent=True )

    url     = f"https://api.elevenlabs.io/v1/text-to-speech/{body.voice_id}"
    headers = {
        "xi-api-key"   : api_key,
        "accept"       : "audio/mpeg",
        "Content-Type" : "application/json"
    }
    payload = {
        "text"           : body.text,
        "model_id"       : model_id,
        "voice_settings" : {
            "stability"        : stability,
            "similarity_boost" : similarity_boost
        }
    }

    try:
        async with httpx.AsyncClient( timeout=30.0 ) as client:
            r = await client.post( url, headers=headers, json=payload )
    except httpx.HTTPError as e:
        raise HTTPException( status_code=503, detail=f"ElevenLabs request failed: {e}" )

    if r.status_code != 200:
        # Surface a redacted snippet of the upstream body so the user can
        # diagnose (e.g., quota exceeded, voice not found) without exposing
        # internal headers.
        snippet = r.text[ :200 ] if r.text else "(empty)"
        raise HTTPException(
            status_code=503,
            detail=f"ElevenLabs returned {r.status_code}: {snippet}"
        )

    return Response(
        content    = r.content,
        media_type = "audio/mpeg",
        headers    = { "Cache-Control": "no-store" }
    )
