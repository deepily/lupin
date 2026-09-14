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

import asyncio
import json
import os
import time
from typing import Any, Optional

import torch
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.auth import get_current_user, identity_or_401
from cosa.rest.routers import speech

router = APIRouter( tags=[ "v2-ask" ] )

# The ask tasks /api/v2/ask-audio has started and not yet settled. A strong reference is
# defence in depth, not what keeps an ask alive across a disconnect — that is creating the
# task before the StreamingResponse exists (see ask_audio). Deliberately NOT
# speech.get_active_tasks: that dict's one consumer, websocket.py, cancels by bare
# session_id when the audio WebSocket drops, which would kill exactly the ask this door
# promises survives a disconnect.
_INFLIGHT_ASKS: set = set()


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
    replayed_snapshot_id : Optional[ str ] = Field( None, description="id_hash of the cached row this request REPLAYED (set on both the served and the failed replay); null when nothing was replayed. Distinct from `snapshot_id`, which is the WRITE-BACK id and is null on a warm pass by construction, and from `job_id`, which means a queue job on the agent path" )
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
    display_name   : str             = Field( ..., description="What to SHOW the user — the dropdown's option text, a proper name ('Date & Time'). CRUD-forked, so it names the agent that will actually run" )
    label          : str             = Field( ..., description="What the user HEARS — lowercase prose for spoken text ('date and time'). A different register from display_name, not a duplicate of it; CRUD-forked too" )
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

    def _source_document_scopes() -> dict:
        """The scopes a `source_document` may name — Rick's Q1 ruling, 2026-09-08.

        THE DOC-VIEWER'S REGISTRY PLUS THE TWO BUILT-INS, and deliberately not a second
        allowlist: the set of files a research job may READ is then the same set a human
        may BROWSE at /api/docs/file and /api/io/file. Two allowlists that disagree about
        which files are reachable is the failure this avoids, and it is the reason this
        resolves through build_scope_registry rather than listing directories here.

        `docs` and `io` are added by hand because build_scope_registry SKIPS them by name
        (_RESERVED_SCOPE_NAMES) — they are built-ins served from the project root rather
        than entries in the `external repos` INI block, so the registry that describes
        external repos legitimately does not carry them.

        Called per request rather than cached: the registry is cheap to rebuild and a
        cached copy would freeze whatever was mounted when the flow was constructed.
        """
        import cosa.utils.util as cu
        from cosa.rest.routers._scope_registry import ScopeConfig, build_scope_registry

        project_root = cu.get_project_root()
        scopes       = dict( build_scope_registry( config_mgr ) )
        scopes[ "io" ]   = ScopeConfig( name="io",   root=os.path.join( project_root, "io" ),   allowed_prefixes=( ) )
        scopes[ "docs" ] = ScopeConfig( name="docs", root=os.path.join( project_root, "src" ),  allowed_prefixes=( ) )
        return scopes

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
        scope_registry_fn = _source_document_scopes,
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
            # BOTH user-facing strings, because they are different registers: one is
            # read in a dropdown, one is spoken. A command with neither
            # (`agent router go to automatic`, `none`) falls back to its own command
            # string — nobody renders those, and an invented name would be the one
            # string in this response that came from nowhere.
            display_name   = effective.display_name or command,
            label          = effective.label or effective.display_name or command,
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
    user_id, user_email = identity_or_401( current_user )

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


def _ndjson( obj: dict ) -> str:
    """
    One NDJSON line: a compact JSON object and its newline.

    Ensures:
        - no space after ':' or ',' and exactly one trailing "\\n", so the body is
          byte-comparable with the committed contract fixture
    """
    return json.dumps( obj, separators=( ",", ":" ) ) + "\n"


def _stream_headers() -> dict:
    """
    Headers for a streamed NDJSON reply.

    Ensures:
        - exactly Cache-Control: no-cache and X-Accel-Buffering: no — not the SSE set,
          which would also claim text/event-stream, keep-alive and a wildcard CORS origin
    """
    return { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" }


@router.post( "/api/v2/ask-audio" )
async def ask_audio(
    file             : UploadFile       = File( ... ),
    websocket_id     : Optional[ str ]  = None,
    speak            : bool             = True,
    interactive      : bool             = True,
    current_user     : dict             = Depends( get_current_user ),
    flow             : Any              = Depends( get_ask_flow ),
    provider         : Any              = Depends( speech.get_speech_provider ),
    whisper_pipeline : Any              = Depends( speech.get_whisper_pipeline ),
    config_mgr       : Any              = Depends( speech.get_config_manager ),
) -> StreamingResponse:
    """
    Transcribe a spoken question and ask it, in one request with a two-part reply.

    Requires:
        - an authenticated user carrying uid + email
        - file is audio the transcriber reads; websocket_id, when given, is a QUERY parameter

    Ensures:
        - a non-200 means nothing was asked: 401 identity, 503 flow disabled or GPU OOM,
          500 any other failure reading, saving or transcribing the audio, 422 empty speech
        - a 200 body is NDJSON: a transcript line, then exactly one ask or error line
        - the ask is started BEFORE the response exists, so a client that disconnects after
          line 1 does not cancel it; its answer still reaches the session's WebSocket
        - the uploaded audio is removed on every path

    Raises:
        - HTTPException 401 / 422 / 500 / 503 as above
    """
    user_id, user_email = identity_or_401( current_user )
    session_id = websocket_id or f"api-{user_id[ :8 ]}"
    temp_path  = None
    try:
        # The read and the save are inside the try, as in both existing audio doors: a full
        # disk or a bad upload dir must come back as the shaped 500 below, not a bare one.
        content   = await file.read()
        suffix    = speech.audio_suffix_from_filename( file.filename, fallback=".wav" )
        temp_path = speech.save_audio_upload( content, user_id, suffix, speech.resolve_stt_upload_dir( config_mgr ) )
        # Before the stream opens, so a failure is a real HTTP status.
        started = time.perf_counter()
        text    = ( await run_in_threadpool( lambda: provider.transcribe( temp_path, whisper_pipeline=whisper_pipeline ) ) ).strip()
        stt_ms  = round( ( time.perf_counter() - started ) * 1000, 1 )
        if not text: raise HTTPException( status_code=422, detail="No speech was recognised, so nothing was asked." )
        # Inside the try too, as both existing doors keep their io-row insert (J-A2): a database
        # failure here is the shaped 500, never a bare one.
        await run_in_threadpool( lambda: speech.insert_stt_io_row(
            input_type="stt_wav_ask", input=text, output_raw=text, output_final=text ) )
    except torch.cuda.OutOfMemoryError:
        # The same status, message and header both existing audio doors send.
        print( "[ERROR] ask-audio transcription failed: CUDA out of memory (after retry)" )
        raise HTTPException( status_code=503, detail="Server GPU memory temporarily unavailable. Please retry in a few seconds.", headers={ "Retry-After": "5" } )
    except HTTPException:
        # A refusal raised on purpose above (the 422). HTTPException is an Exception, so without
        # this clause the generic handler below would turn it into a 500 — the MP3 door's precedent.
        raise
    except Exception as e:
        # One fixed message and no exception text, following the MP3 door's correction:
        # naming every failure "transcription failed" once sent a config fault to the model
        # server for debugging. Everything before the ask is one thing to the client.
        print( f"[ERROR] ask-audio failed before the ask: {e}" )
        raise HTTPException( status_code=500, detail="Could not accept the audio. Nothing was asked." )
    finally:
        # A bare call, as the WAV door's: remove_audio_upload does nothing for None.
        speech.remove_audio_upload( temp_path )

    # START THE ASK HERE, before the StreamingResponse exists. Starlette cancels the
    # response's scope on disconnect, and anyio checks for cancellation before its worker
    # thread starts, so an ask created inside lines() could be killed after a 200 and a
    # transcript had already gone out. A plain task created now is outside that scope.
    ask_task = asyncio.create_task(
        run_in_threadpool( lambda: flow.ask( question=text, user_id=user_id, user_email=user_email,
                                             session_id=session_id, websocket_id=session_id,
                                             speak=speak, interactive=interactive ) ) )
    _INFLIGHT_ASKS.add( ask_task )

    def _release( task ):
        # Drop the reference, and retrieve the exception so an ask that fails after the
        # client left is not reported as "Task exception was never retrieved".
        _INFLIGHT_ASKS.discard( task )
        # Two lines, not one: on one line coverage cannot tell the cancelled arm from the other
        # (both end on this line), so a 100%-branch gate would pass with that arm never run.
        if not task.cancelled():
            task.exception()
    ask_task.add_done_callback( _release )

    trace = { "stt_ms": stt_ms, "upload_bytes": len( content ) }

    async def lines():
        yield _ndjson( { "type": "transcript", "transcription": text, "trace": trace } )
        try:
            result = await asyncio.shield( ask_task )
            # The full AskResponse body /api/v2/ask returns: every field, in model order.
            yield _ndjson( { "type": "ask", "result": AskResponse( **result ).model_dump( mode="json" ) } )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield _ndjson( { "type": "error", "stage": "ask", "detail": str( e ) } )

    return StreamingResponse( lines(), media_type="application/x-ndjson", headers=_stream_headers() )


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
    user_id, user_email = identity_or_401( current_user )

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
    user_id, user_email = identity_or_401( current_user )

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
