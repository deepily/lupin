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
    interactive  : bool           = Field( True,
                                           description="Whether a human is there to answer. Two effects: a missing "
                                                       "argument parks and asks (else the call returns needs_input), and a "
                                                       "near-match cache hit is confirmed before it is replayed (else the "
                                                       "match is declined and the question is routed normally)" )


class SubmitRequest( BaseModel ):
    """Request body for POST /api/v2/submit — work whose command is already decided.

    `question` is OPTIONAL here and required on `ask`, which is the whole difference
    between the two doors. `ask` is handed prose and has to work out what it means;
    `submit` is handed the answer to that question up front, so the text is only carried
    along for the record and for anything downstream that shows the user what ran.

    THE LAST THREE FIELDS ARE QUEUE DIRECTIVES, NOT ARGUMENTS, and that is why they are
    top-level fields rather than keys inside `args`. `args` is checked against the
    command's own argument contract, so a scheduling instruction put in there would have
    to be written into some agent's contract as though the agent took it — and no agent
    does. Each retiring door declared these same three on its own request model and set
    them on the job after building it; they arrive here for the same reason and are
    passed on only when the caller actually set one.
    """
    command        : str            = Field( ..., min_length=1, max_length=200,
                                             description="The routing command, e.g. 'agent router go to weather'" )
    args           : dict           = Field( default_factory=dict,
                                             description="Every argument the command requires — no extraction is performed" )
    question       : Optional[ str ] = Field( None, max_length=4000,
                                             description="Optional human-readable text for the record" )
    websocket_id   : Optional[ str ] = Field( None, description="WebSocket session ID for TTS routing" )
    speak          : bool           = Field( True, description="Dispatch the answer as a TTS notification" )
    scheduled_at   : Optional[ str ] = Field( None, description="ISO datetime to defer execution to (None = run when the queue reaches it). The off-peak scheduling rule is built on this field" )
    monopolize     : bool           = Field( False, description="Run exclusively, holding every other job until this one finishes" )
    parent_id_hash : Optional[ str ] = Field( None, description="id_hash of the monopolize job that SPAWNED this one. When it matches the pool's active monopolizer, the consumer's Gate B admits this child THROUGH the intake hold instead of deferring it as a foreign writer (bugs 3a14292b, 5ed4f187). Reaches the job as spawned_by_id_hash" )


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


class AgentOption( BaseModel ):
    """One registry command, projected for a client that has to render it."""
    command        : str             = Field( ..., description="The full routing string — the value a client sends back as `command` on /api/v2/submit" )
    label          : str             = Field( ..., description="What to show the user. CRUD-forked when the fork is on, so it names the agent that will actually run" )
    cls            : str             = Field( ..., description="conversational | agentic | control | none" )
    description    : Optional[ str ] = Field( None, description="One-line help text; None for commands nobody picks by hand" )
    speakable      : bool            = Field( ..., description="Belongs in the voice router prompt" )
    user_initiable : bool            = Field( ..., description="A person may start this by typing into the Q&A card. NOT derived from `speakable` — see registry.AgentSpec" )
    aliases        : list            = Field( default_factory=list, description="Registered short forms" )
    required_args  : list            = Field( default_factory=list, description="Argument names this command needs before it can run" )
    arg_questions  : dict            = Field( default_factory=dict, description="Per-argument question text, for an inline argument interview" )
    job_prefix     : Optional[ str ] = Field( None, description="Agentic job-id prefix (dr, pg, cc, swe, …); None for non-agentic" )


class AutoRouteOption( BaseModel ):
    """The dropdown's 'no command named — let the router decide' entry.

    Carried in the RESPONSE rather than hand-written into the page, so the front end
    holds no agent list of its own at all — not even the one legitimate option. See
    registry.AUTO_ROUTE_VALUE for why that is a named sentinel and not an exemption
    written into a guard.
    """
    value       : str = Field( ..., description="Sentinel option value; never a registry command" )
    label       : str = Field( ..., description="What to show the user" )
    description : str = Field( ..., description="One-line help text" )


class AgentsResponse( BaseModel ):
    """Response for GET /api/v2/agents."""
    auto_route : AutoRouteOption
    agents     : list[ AgentOption ]


# ═══════════════════════════════════════════════════════════════════════════════
# Factory + dependency seam
# ═══════════════════════════════════════════════════════════════════════════════

_ASK_FLOW_CACHE: dict = {}   # id(config_mgr) -> ( AskFlow, enabled: bool )

# The process-wide flow the SERVER runs on, handed here by lifespan (step 12).
# None until install_ask_flow() is called, which is the state every unit-test app
# is in: those build their own bare FastAPI and never run lifespan, so get_ask_flow
# falls back to building from INI exactly as it did before step 12.
_INSTALLED_FLOW: Optional[ tuple ] = None   # ( AskFlow, enabled: bool )


def install_ask_flow( flow: Any, enabled: bool ) -> None:
    """
    Hand `get_ask_flow` the flow lifespan built, so the door and the in-process
    callers share ONE object.

    WHY THIS EXISTS AT ALL. Before step 12 the flow was built by the request-time
    dependency and memoised per config-manager. That is one flow per process only
    because ConfigurationManager is a @singleton — an accident that happened to
    hold, not a guarantee. It also meant the flow did not exist until the first
    HTTP request, and the boot-time catch-up restore runs long before that. Step 12
    builds it in lifespan instead; this is how the already-built object reaches the
    route rather than being rebuilt behind it.

    Requires:
        - flow is the AskFlow lifespan constructed, enabled is `v2 flow enabled`.

    Ensures:
        - get_ask_flow() serves this flow, and applies the same 503 gate to it.
    """
    global _INSTALLED_FLOW
    _INSTALLED_FLOW = ( flow, enabled )


def build_ask_flow( config_mgr: Any, todo_queue: Any=None ) -> tuple:
    """
    Build the v2 AskFlow with its real collaborator stack from INI.

    Requires:
        - config_mgr exposes .get( key, default, return_type ) for the v2 keys.
        - todo_queue is the live TodoFifoQueue when `v2 executor` is "queued";
          make_executor raises by name if it is missing, rather than building an
          executor that fails later on the live path.

    Ensures:
        - returns ( AskFlow, enabled ) where enabled reflects `v2 flow enabled`.
        - imports the cache/router/expeditor/executor/pending stack lazily so
          this module is importable with no live Postgres or model server.
        - writeback ships ON when `v2 snapshot writeback enabled` is true, wired
          through AskFlow's own fail-loud construction guard (row 41333974).
    """
    # Lazy — heavy singletons (embedding provider, LLM factory) build only here.
    from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
    from cosa.memory.query_log_table import QueryLogTable
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
    # The SAME key and the SAME default the v1 queue reads (todo_fifo_queue._crud_agents_enabled):
    # missing means enabled. resolve() applies the CRUD fork for every caller now, so the
    # flow has to know, and reading it anywhere else would let the two surfaces disagree.
    crud_enabled      = config_mgr.get( "crud for dataframes agents enabled", default="true", return_type="string" ).strip().lower() == "true"
    # The same two keys the queue reads (todo_fifo_queue.__init__), so an agent built
    # by the flow gets the debug flags it would have got via push_job.
    auto_debug        = config_mgr.get( "debug auto",        default=False, return_type="boolean" )
    inject_bugs       = config_mgr.get( "debug inject bugs", default=False, return_type="boolean" )
    # The near-match ask (step 6b), from the SAME two keys the queue reads
    # (todo_fifo_queue push_job's confirmation branch) and with the same defaults, so
    # the prompt a user hears does not change with the door they came through. The
    # threshold is what ARMS the branch: AskFlow treats None as "no near-match
    # behaviour at all", which is what an app that never reads INI keeps getting.
    confirmation_threshold = config_mgr.get( "similarity threshold confirmation", default=90.0, return_type="float"   )
    confirmation_enabled   = config_mgr.get( "similarity confirmation enabled",   default=True, return_type="boolean" )

    flow = AskFlow(
        cache             = V2Cache(),
        router            = RouterClient( config_mgr ),
        expeditor         = RuntimeArgumentExpeditor( config_mgr ),
        executor          = make_executor( executor_name, todo_queue=todo_queue ),
        pending           = PendingRequests(),
        crud_enabled      = crud_enabled,
        confirmation_threshold = confirmation_threshold,
        confirmation_enabled   = confirmation_enabled,
        query_log         = QueryLogTable(),
        auto_debug        = auto_debug,
        inject_bugs       = inject_bugs,
        similarity_floor  = similarity_floor,
        writeback_enabled = writeback_enabled,
        trace_dir         = trace_dir,
    )
    return flow, enabled


def get_ask_flow() -> Any:
    """
    FastAPI dependency: the process-wide AskFlow.

    Ensures:
        - serves the flow lifespan installed, when there is one. On the server there
          always is, and it is the SAME object the in-process callers submit to —
          which is the point: one flow means one guarded write-back path.
        - otherwise builds from INI and caches it keyed by config-mgr identity. That
          is the pre-step-12 behaviour, kept for apps that never run lifespan (every
          unit-test app builds a bare FastAPI and overrides this dependency anyway).
        - raises HTTP 503 when `v2 flow enabled` is off — the feature gate, applied
          to both paths.
    """
    if _INSTALLED_FLOW is not None:
        flow, enabled = _INSTALLED_FLOW
    else:
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

@router.get( "/api/v2/agents", response_model=AgentsResponse )
async def v2_agents(
    current_user : dict = Depends( get_current_user ),
    flow         : Any  = Depends( get_ask_flow ),
) -> AgentsResponse:
    """List every command the registry knows — a PURE PROJECTION of REGISTRY.

    The read endpoint the front end was missing (2026.08.22 plan §5.1). The Q&A
    card's agent list used to be sixteen hand-typed `<option>` tags in
    notifications.html, one of five hand-maintained lists describing the same set;
    this door is how that list stops being written by hand.

    PURE PROJECTION means: every registry command appears, exactly once, carrying
    its own fields. Nothing is filtered here — not the two expediters, not the
    control command, not `none`. A client renders what it should render by reading
    `user_initiable` (the Q&A dropdown) or `speakable` (a voice surface); the door
    does not decide that for them, because the moment it filters, the set-equality
    that proves the door matches the table stops being checkable.

    WHY IT DEPENDS ON THE FLOW. It needs `crud_enabled` — the labels must name the
    agent that will ACTUALLY run, so `todo` reads "todo (CRUD)" when the fork is on.
    Reading the INI key here would be a FOURTH read of `crud for dataframes agents
    enabled`, and a fourth read is a fourth thing to drift. The flow already holds
    the value it will itself route with, so the label a user picks and the agent
    they get cannot disagree. The 503 that comes with the dependency is coherent:
    when `v2 flow enabled` is off, /api/v2/submit is off too, and a dropdown that
    drives it has nothing to drive.

    Requires:
        - an authenticated user (get_current_user).

    Ensures:
        - `agents` carries one entry per REGISTRY command — set-equal to REGISTRY,
          which is the §6 gate 1 assertion.
        - the CRUD fork is applied exactly as resolve() applies it, by calling
          resolve() itself rather than reimplementing the fork.
        - `auto_route` carries the sentinel option, so the page hand-writes no
          option at all.
        - never 500s for an unknown-shaped spec: every field read is declared on
          AgentSpec or on the command's JOB_ARG_CONTRACTS entry.
    """
    from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
    from cosa.rest.v2.registry import (
        AUTO_ROUTE_DESCRIPTION, AUTO_ROUTE_LABEL, AUTO_ROUTE_VALUE, REGISTRY, resolve,
    )

    agents = []
    for command, spec in REGISTRY.items():
        # resolve() returns the CRUD-forked spec for a conversational command and
        # None for every other class — so `or spec` is the fork for the six that
        # have one and identity for the rest. Calling resolve() instead of copying
        # its `if crud_enabled and spec.crud_factory` test is the whole point: one
        # implementation of the fork, not two that can disagree.
        effective = resolve( command, flow.crud_enabled ) or spec
        entry     = JOB_ARG_CONTRACTS.get( command, {} )
        agents.append( AgentOption(
            command        = command,
            # The agentic set carries its display name in its contract; the
            # conversational set and the receptionist carry a `label`. A command with
            # neither (`agent router go to automatic`, `none`) falls back to its own
            # command string — nobody renders those, and an invented label would be
            # the one string in this response that came from nowhere.
            label          = effective.label or entry.get( "display_name" ) or command,
            cls            = effective.cls.value,
            description    = effective.description,
            speakable      = effective.speakable,
            user_initiable = effective.user_initiable,
            aliases        = list( effective.aliases ),
            required_args  = list( effective.required_args ),
            arg_questions  = dict( entry.get( "fallback_questions", {} ) ),
            job_prefix     = entry.get( "job_prefix" ),
        ) )

    return AgentsResponse(
        auto_route = AutoRouteOption(
            value       = AUTO_ROUTE_VALUE,
            label       = AUTO_ROUTE_LABEL,
            description = AUTO_ROUTE_DESCRIPTION,
        ),
        agents = agents,
    )


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
    # flow.ask() is SYNCHRONOUS and takes as long as the agent takes — measured at
    # ~70s for a single ask on :8000, of which routing is ~1s (row 1c36199e). Called
    # directly from this coroutine it holds the event loop for that whole span, and
    # with workers=1 that means /health times out and every other request waits. Off
    # the loop it holds a worker thread instead, which is what a slow call should hold.
    result = await run_in_threadpool(
        lambda: flow.ask(
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


@router.post( "/api/v2/submit", response_model=AskResponse )
async def v2_submit(
    request      : SubmitRequest,
    current_user : dict = Depends( get_current_user ),
    flow         : Any  = Depends( get_ask_flow ),
) -> AskResponse:
    """Run work whose command is already decided — the door beside /api/v2/ask.

    Rick's entry-point ruling, 2026-08-21: two doors survive at v2. `ask` takes a bare
    question and works out what it is; `submit` takes work whose command the caller has
    already chosen, so it skips routing and argument extraction entirely.

    Requires:
        - an authenticated user (get_current_user) carrying uid + email.
        - request.command is a non-empty routing command (Field-validated), and
          request.args carries every argument that command requires.

    Ensures:
        - returns AskResponse; never 500 for a routing or agent failure — the flow
          degrades to the receptionist exactly as it does on `ask`.
        - user_id / user_email come from the token, never the client body.
        - a command missing arguments comes back status='needs_input' with args_missing
          filled in, and is NEVER parked: there is no human behind a submit to answer it.
        - scheduled_at / monopolize / parent_id_hash reach the built job only on the
          agentic path, which is the only path that builds one; on the other paths the
          flow records that they were dropped rather than discarding them in silence.
    """
    user_id    = current_user.get( "uid" )
    user_email = current_user.get( "email" )
    if not user_id:
        raise HTTPException( status_code=401, detail="User id not found in authentication token." )
    if not user_email:
        raise HTTPException( status_code=401, detail="User email not found in authentication token." )

    session_id = request.websocket_id or f"api-{user_id[ :8 ]}"
    # Same reason as /api/v2/ask: submit skips the head (no routing, no cache read)
    # but still RUNS THE AGENT, so it holds the caller for the agent's full span.
    # On the loop that starves /health with workers=1 (row 1c36199e); off it, it
    # holds a worker thread instead.
    result = await run_in_threadpool(
        lambda: flow.submit(
            command        = request.command,
            args           = request.args,
            question       = request.question,
            user_id        = user_id,
            user_email     = user_email,
            session_id     = session_id,
            websocket_id   = request.websocket_id or session_id,
            speak          = request.speak,
            scheduled_at   = request.scheduled_at,
            monopolize     = request.monopolize,
            parent_id_hash = request.parent_id_hash,
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
