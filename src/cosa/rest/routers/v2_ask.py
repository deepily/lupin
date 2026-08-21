"""CJ Flow v2 — the /api/v2/ask endpoint (unit D, plan §5, §8).

One authenticated POST routes a question through AskFlow's four branches and
returns the §8 result dict as a typed body. The endpoint never waits for a human
(a missing argument parks the request and returns the first question at once) and
never 500s for an agent/replay/router/extract failure — AskFlow degrades each to
the receptionist. The only 4xx paths are auth (401, via get_current_user), body
validation (422, via the Pydantic Field constraints), and the feature gate (503,
when `v2 flow enabled` is off).

The real collaborator stack (V2Cache, RouterClient, RuntimeArgumentExpeditor,
InlineExecutor, PendingRequests) is imported lazily inside build_ask_flow so this
module stays importable without a live Postgres/model server, and is built once
per process. Unit tests override get_ask_flow with a fake flow via
app.dependency_overrides — no real stack is touched on :7999.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.auth import get_current_user

router = APIRouter( tags=[ "v2-ask" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic contract (§8)
# ═══════════════════════════════════════════════════════════════════════════════

class AskRequest( BaseModel ):
    """Request body for POST /api/v2/ask."""
    question     : str            = Field( ..., min_length=1, max_length=4000,
                                           description="The user's natural-language question" )
    websocket_id : Optional[ str ] = Field( None, description="WebSocket session ID for TTS routing" )
    speak        : bool           = Field( True, description="Dispatch the answer as a TTS notification" )
    interactive  : bool           = Field( True, description="Park + resume on a missing argument (else return needs_input)" )


class ResumeRequest( BaseModel ):
    """Request body for POST /api/v2/resume — the second turn of a parked flow."""
    pending_id   : str            = Field( ..., min_length=1,
                                           description="The parked-request id returned by a prior needs_input response" )
    answer       : str            = Field( ..., min_length=1, max_length=4000,
                                           description="The human's reply to the parked question" )
    websocket_id : Optional[ str ] = Field( None, description="WebSocket session ID for TTS routing" )
    speak        : bool           = Field( True, description="Dispatch the answer as a TTS notification" )


class AskResponse( BaseModel ):
    """The §8 terminal result of one v2 request."""
    path           : str                 = Field( ..., description="replay | agent | needs_input | receptionist" )
    status         : str                 = Field( ..., description="done | waiting | parked | needs_input | expired | failed" )
    route_reason   : str                 = Field( ..., description="Why this branch was taken" )
    answer         : Optional[ str ]     = Field( None, description="The conversational answer (or first question)" )
    answer_raw     : Optional[ str ]     = Field( None, description="The unformatted answer" )
    command        : Optional[ str ]     = Field( None, description="The resolved routing command" )
    args_known     : list                = Field( default_factory=list, description="Argument names successfully extracted" )
    args_missing   : list                = Field( default_factory=list, description="Argument names still required" )
    pending_id     : Optional[ str ]     = Field( None, description="Parked-request id when interactive + needs_input" )
    job_id         : Optional[ str ]     = Field( None, description="Executor job id (replay id_hash, etc.)" )
    snapshot_id    : Optional[ str ]     = Field( None, description="Written-back snapshot id, or null" )
    similarity     : Optional[ float ]   = Field( None, description="Best cache-candidate similarity" )
    wrote_snapshot : bool                = Field( False, description="Whether a snapshot was written back" )
    cache_hit      : bool                = Field( False, description="Whether this was a tier-1 exact replay" )
    spoke          : bool                = Field( False, description="Whether a TTS notification was dispatched" )
    timings_ms     : dict                = Field( default_factory=dict, description="Per-stage millisecond offsets" )
    trace_id       : str                 = Field( ..., description="The request's trace id" )
    error          : Optional[ str ]     = Field( None, description="Degradation error string, when a stage failed" )


# ═══════════════════════════════════════════════════════════════════════════════
# Factory + dependency seam
# ═══════════════════════════════════════════════════════════════════════════════

_ASK_FLOW_CACHE: dict = {}   # id(config_mgr) -> ( AskFlow, enabled: bool )


def build_ask_flow( config_mgr: Any ) -> tuple:
    """
    Build the v2 AskFlow with its real collaborator stack from INI.

    Requires:
        - config_mgr exposes .get( key, default, return_type ) for the v2 keys.

    Ensures:
        - returns ( AskFlow, enabled ) where enabled reflects `v2 flow enabled`.
        - imports the cache/router/expeditor/executor/pending stack lazily so
          this module is importable with no live Postgres or model server.
        - writeback ships ON when `v2 snapshot writeback enabled` is true, wired
          through AskFlow's own fail-loud construction guard (row 41333974).
    """
    # Lazy — heavy singletons (embedding provider, LLM factory) build only here.
    from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
    from cosa.rest.v2.cache          import V2Cache
    from cosa.rest.v2.executor       import make_executor
    from cosa.rest.v2.flow           import AskFlow
    from cosa.rest.v2.pending        import PendingRequests
    from cosa.rest.v2.router_client  import RouterClient

    enabled           = config_mgr.get( "v2 flow enabled",              default=False,    return_type="boolean" )
    executor_name     = config_mgr.get( "v2 executor",                  default="inline", return_type="string"  )
    writeback_enabled = config_mgr.get( "v2 snapshot writeback enabled", default=False,   return_type="boolean" )
    similarity_floor  = config_mgr.get( "v2 similarity floor",          default=100.0,    return_type="float"   )
    trace_dir         = config_mgr.get( "v2 trace dir",                 default=None,     return_type="string"  ) or None

    flow = AskFlow(
        cache             = V2Cache(),
        router            = RouterClient( config_mgr ),
        expeditor         = RuntimeArgumentExpeditor( config_mgr ),
        executor          = make_executor( executor_name ),
        pending           = PendingRequests(),
        similarity_floor  = similarity_floor,
        writeback_enabled = writeback_enabled,
        trace_dir         = trace_dir,
    )
    return flow, enabled


def get_ask_flow() -> Any:
    """
    FastAPI dependency: the process-wide AskFlow, built once from INI.

    Ensures:
        - builds the flow on first use and caches it keyed by config-mgr identity.
        - raises HTTP 503 when `v2 flow enabled` is off — the feature gate.
    """
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    key        = id( config_mgr )
    if key not in _ASK_FLOW_CACHE:
        _ASK_FLOW_CACHE[ key ] = build_ask_flow( config_mgr )
    flow, enabled = _ASK_FLOW_CACHE[ key ]
    if not enabled:
        raise HTTPException( status_code=503, detail="CJ Flow v2 is disabled (v2 flow enabled = False)." )
    return flow


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post( "/api/v2/ask", response_model=AskResponse )
async def v2_ask(
    request      : AskRequest,
    current_user : dict = Depends( get_current_user ),
    flow         : Any  = Depends( get_ask_flow ),
) -> AskResponse:
    """
    Route one question through CJ Flow v2 and return the §8 result.

    Requires:
        - an authenticated user (get_current_user) carrying uid + email.
        - request.question is a non-empty string ≤ 4000 chars (Field-validated).

    Ensures:
        - returns AskResponse; never 500 for an agent/replay/router/extract
          failure — AskFlow degrades each to the receptionist.
        - user_id / user_email come from the token, never the client body.
    """
    user_id    = current_user.get( "uid" )
    user_email = current_user.get( "email" )
    if not user_id:
        raise HTTPException( status_code=401, detail="User id not found in authentication token." )
    if not user_email:
        raise HTTPException( status_code=401, detail="User email not found in authentication token." )

    session_id = request.websocket_id or f"api-{user_id[ :8 ]}"
    # flow.run() is SYNCHRONOUS and takes as long as the agent takes — measured at
    # ~70s for a single ask on :8000, of which routing is ~1s (row 1c36199e). Called
    # directly from this coroutine it holds the event loop for that whole span, and
    # with workers=1 that means /health times out and every other request waits. Off
    # the loop it holds a worker thread instead, which is what a slow call should hold.
    result = await run_in_threadpool(
        lambda: flow.run(
            question    = request.question,
            user_id     = user_id,
            user_email  = user_email,
            session_id  = session_id,
            websocket_id= request.websocket_id or session_id,
            speak       = request.speak,
            interactive = request.interactive,
        )
    )
    return AskResponse( **result )


@router.post( "/api/v2/resume", response_model=AskResponse )
async def v2_resume(
    request      : ResumeRequest,
    current_user : dict = Depends( get_current_user ),
    flow         : Any  = Depends( get_ask_flow ),
) -> AskResponse:
    """
    Resume a parked v2 flow with the human's answer — the second turn.

    Requires:
        - an authenticated user (get_current_user).
        - request.pending_id is a parked id; request.answer is the reply (Field-validated).

    Ensures:
        - returns AskResponse; an expired/unknown pending_id degrades to a
          needs_input refusal (status='expired'), never a 500.
        - resume runs OFF the event loop, in a worker thread. It used to run on
          the loop itself; that is what made /health time out during a call.
    """
    user_id    = current_user.get( "uid" )
    user_email = current_user.get( "email" )
    if not user_id:
        raise HTTPException( status_code=401, detail="User id not found in authentication token." )
    if not user_email:
        raise HTTPException( status_code=401, detail="User email not found in authentication token." )

    session_id = request.websocket_id or f"api-{user_id[ :8 ]}"
    # Same shape as v2_ask above, and the same reason. resume is the SECOND turn of
    # every disambiguation, so a blocked loop here stalls exactly the conversations a
    # user is already waiting on.
    result = await run_in_threadpool(
        lambda: flow.resume(
            pending_id   = request.pending_id,
            answer       = request.answer,
            websocket_id = request.websocket_id or session_id,
            speak        = request.speak,
        )
    )
    return AskResponse( **result )
