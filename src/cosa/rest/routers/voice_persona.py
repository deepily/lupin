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
    load_overflow_persona_from_config, allocate_requested_persona_for_session
)


router = APIRouter( prefix="/api/cosa-voice", tags=[ "cosa-voice" ] )

# Module-level lock serializes scan→pick→write so two parallel /allocate
# calls can't both pick the same persona. Single-process uvicorn assumed
# (same caveat as `speakerphone.py` `_speakerphone_lock`). On /release there is
# nothing to coordinate, so we skip the lock for that path.
_voice_persona_lock = asyncio.Lock()


# ── Dependency injection ─────────────────────────────────────────────────────

def get_notification_queue():
    """Dependency to get the singleton NotificationFifoQueue from main module."""
    import fastapi_app.main as main_module
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
            { "session_id": sid, "persona_name": p.get( "name" ), "borrowed": p.get( "borrowed", False ) }
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
    description = "Idempotent: if a persona is already set on the bridge and no `requested_persona_name`/`preferred_persona_name` query param is supplied, returns it without re-allocating. When `requested_persona_name` is supplied: atomically allocates the named persona with strict 422/409 errors on miss. When `preferred_persona_name` is supplied: graceful-fallback semantics — on miss, allocates random and pushes a `voice_persona_conflict` notification (used by the per-repo env-var default path). Mutually exclusive with `requested_persona_name`."
)
async def allocate_voice_persona_endpoint(
    session_id            : str,
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ],
    previous_persona_name : Optional[ str ] = None,
    requested_persona_name: Annotated[ Optional[ str ], Query( min_length=1, max_length=64 ) ] = None,
    preferred_persona_name: Annotated[ Optional[ str ], Query( min_length=1, max_length=64 ) ] = None,
    notification_queue    : NotificationFifoQueue = Depends( get_notification_queue ),
    config_mgr            = Depends( get_config_manager )
) -> JSONResponse:
    """
    Atomically allocate a persona for the given session.

    Three operating modes, selected by `requested_persona_name`:

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

    # Strict + soft preference are mutually exclusive — the strict path
    # surfaces 422/409 to a user who typed `/plan-session-start María`,
    # while the soft path silently falls back to random + a conflict notify
    # so the SessionStart hook never blocks. Mixing them would conflate
    # error semantics.
    if requested_persona_name is not None and preferred_persona_name is not None:
        raise HTTPException(
            status_code=422,
            detail="`requested_persona_name` and `preferred_persona_name` are mutually exclusive — supply exactly one"
        )

    # Outer fast-path: no request + already allocated → legacy idempotency
    # contract holds; return existing without acquiring the lock.
    # Note: `preferred_persona_name` does NOT override an existing allocation
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
    # Only the soft-preference branch ever populates it; the strict-request
    # and plain-allocation paths leave it None.
    preference_conflict: Optional[ dict ] = None

    async with _voice_persona_lock:
        # Re-read bridge under the lock — another request may have written
        # between the outer check and acquisition.
        existing = get_voice_persona( session_id )

        if requested_persona_name is not None:
            # Request-or-swap path
            normalized_request = requested_persona_name.strip().lower()

            if existing is not None and existing.get( "name", "" ).lower() == normalized_request:
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
            if not ok:
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

            # Soft-preference branch (env-var default). On miss, fall back
            # to random allocation and queue a voice_persona_conflict notify
            # so the user knows their preference was honored or rejected.
            # See: planning-is-prompting/src/rnd/2026.05.19-cosa-voice-preferred-persona-env-var.md
            if preferred_persona_name is not None:
                pref_result = allocate_requested_persona_for_session(
                    config_mgr, session_id, preferred_persona_name
                )
                if pref_result is None:
                    raise HTTPException(
                        status_code=500,
                        detail="Voice persona pool is empty or misconfigured (check `cc session voice persona pool` in lupin-app.ini)"
                    )
                if pref_result[ "status" ] == "ok":
                    persona = pref_result[ "persona" ]
                else:
                    # Persona requested via env var is not in pool OR is held
                    # by another session — record conflict details, then fall
                    # through to random allocation below.
                    preference_conflict = {
                        "kind"      : pref_result[ "status" ],
                        "requested" : preferred_persona_name,
                        "available" : pref_result.get( "available", [] )
                    }
                    if pref_result[ "status" ] == "occupied":
                        preference_conflict[ "holding_session_id" ]   = pref_result[ "holding_session_id" ]
                        preference_conflict[ "holding_persona_name" ] = pref_result[ "holding_persona_name" ]
                    persona = allocate_persona_for_session( config_mgr, session_id )
                    if persona is None:
                        raise HTTPException(
                            status_code=500,
                            detail="Voice persona pool is empty or misconfigured (check `cc session voice persona pool` in lupin-app.ini)"
                        )
            else:
                persona = allocate_persona_for_session( config_mgr, session_id )
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
            payload            = { "session_id": session_id }
        )
        broadcast_delivered = True
    except Exception as ws_err:
        print( f"[VOICE-PERSONA] ⚠️ Notification push failed for session {session_id}: {ws_err}" )

    # Soft-preference conflict notification (option α from the env-var
    # default design). Fired only when the caller supplied
    # `preferred_persona_name` AND the requested persona was either missing
    # from the pool or held by another live session, AND we fell back to a
    # random allocation. The user sees a high-priority TTS alert telling
    # them which session is holding their preference (so they can release
    # it manually) or that their env var contains an unknown name.
    if preference_conflict is not None:
        try:
            if preference_conflict[ "kind" ] == "occupied":
                holding_short = preference_conflict[ "holding_session_id" ][ :8 ]
                conflict_msg = (
                    f"Preferred persona '{preference_conflict[ 'requested' ]}' is held by "
                    f"session {holding_short}. Allocated {persona[ 'display_name' ]} instead. "
                    f"Kill that session and restart this one to claim {preference_conflict[ 'holding_persona_name' ]}."
                )
            else:  # "not_in_pool"
                avail_preview = ", ".join( preference_conflict[ "available" ][ :6 ] ) if preference_conflict[ "available" ] else "(none free)"
                conflict_msg = (
                    f"Preferred persona '{preference_conflict[ 'requested' ]}' is not in the configured pool. "
                    f"Allocated {persona[ 'display_name' ]} instead. Available: {avail_preview}."
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
                payload            = preference_conflict
            )
        except Exception as ws_err:
            print( f"[VOICE-PERSONA] ⚠️ Preference conflict notification push failed for session {session_id}: {ws_err}" )

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
        "preference_conflict" : preference_conflict
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
