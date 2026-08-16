"""
Podcast Generator API router for CJ Flow queue-based podcast generation.

Provides smart input parsing that handles both direct file paths and
natural language descriptions with LLM-powered fuzzy matching.

Endpoints:
    POST /api/podcast-generator/submit - Submit podcast generation job

Example:
    # Direct path mode (immediate job creation)
    POST /api/podcast-generator/submit
    {"research_source": "/io/deep-research/user@email/2026.01.26-topic.md"}

    # Description mode (fuzzy matching with notification confirmation)
    POST /api/podcast-generator/submit
    {"research_source": "my Claude Code research"}
"""

import os
import uuid
import difflib
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.queue_util import emit_job_state_transition
from cosa.rest.job_state import JobState
from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.agents.podcast_generator.job import PodcastGeneratorJob
import cosa.utils.util as cu


router = APIRouter(
    prefix="/api/podcast-generator",
    tags=[ "podcast-generator" ]
)


class PodcastSubmitRequest( BaseModel ):
    """
    Request body for podcast generation submission.

    The research_source field is overloaded:
    - If it looks like a path → direct mode (immediate job creation)
    - If it looks like text → description mode (fuzzy match + confirmation)
    """
    research_source    : str
    target_languages   : Optional[ List[ str ] ] = None
    max_segments       : Optional[ int ]         = None
    dry_run            : bool                    = False
    force_failure_mode : Optional[ str ]         = Field( None, description="Phase 6 dry-run repair loop: 'code_bug' | 'infra_timeout' | 'rate_limit' to inject a failure at the end of dry-run" )
    audience           : Optional[ str ]         = None
    audience_context   : Optional[ str ]         = None
    scheduled_at      : Optional[ str ]         = Field( None, description="ISO datetime for deferred execution (None = immediate)" )
    monopolize        : bool                    = Field( False, description="Run exclusively, block all other jobs until complete" )
    parent_id_hash    : Optional[ str ]         = Field( None, description="Lineage token (bug 5ed4f187, mirrors 3a14292b): id_hash of a monopolize job that SPAWNED this child. When it matches the pool's active monopolizer, the consumer's Gate B (queue_consumer.py) uses this lineage to admit the child through the intake hold rather than defer it as a foreign writer. That admit-through behaviour is exercised by the swe_team monopolize sweep, NOT by this router's unit test — the unit test asserts only that the stamp lands on the job. Set from LUPIN_TEST_MONOPOLIZE_PARENT_ID." )


class PodcastSubmitResponse( BaseModel ):
    """Response for successful job submission."""
    job_id         : str
    queue_position : int
    status         : str = "queued"


class PodcastMatchingResponse( BaseModel ):
    """Response when fuzzy matching is triggered."""
    status  : str
    message : str


# ═══════════════════════════════════════════════════════════════════════════════
# Dependencies
# ═══════════════════════════════════════════════════════════════════════════════

def get_todo_queue():
    """
    Dependency to get todo queue from main module.

    Returns:
        RunningFifoQueue: The todo queue instance
    """
    import lupin_app.main as main_module
    return main_module.jobs_todo_queue


def get_websocket_mgr():
    """
    Dependency to get WebSocket manager from main module.

    Returns:
        WebSocketManager: The WebSocket manager instance
    """
    import lupin_app.main as main_module
    return main_module.websocket_manager


# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

def is_research_path( input_text: str, user_email: str ) -> bool:
    """
    Detect if input is a research path (direct mode) or description (fuzzy match mode).

    Path patterns detected:
    - /io/deep-research/{user_email}/filename.md
    - io/deep-research/{user_email}/filename.md
    - Contains user_email AND ends with .md

    Requires:
        - input_text is a non-empty string
        - user_email is a valid email address

    Ensures:
        - Returns True if input looks like a file path
        - Returns False if input looks like a natural language description

    Args:
        input_text: The user's input (path or description)
        user_email: The authenticated user's email

    Returns:
        bool: True if input is a path, False if description
    """
    from cosa.config.configuration_manager import ConfigurationManager

    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    research_root = config_mgr.get( "deep research output path" )
    expected_prefix = f"{research_root}/{user_email}/"

    input_clean = input_text.strip()

    # Check for deep-research path patterns
    if (
        input_clean.startswith( expected_prefix ) or
        input_clean.startswith( expected_prefix.lstrip( "/" ) ) or
        ( user_email in input_clean and input_clean.endswith( ".md" ) )
    ):
        return True

    # Check for general file paths: contains "/" AND ends with a document extension
    if "/" in input_clean and input_clean.endswith( ( ".md", ".txt", ".html" ) ):
        return True

    return False


def validate_source_path( path: str ) -> bool:
    """
    Validate that a source path stays within the project root (directory traversal prevention).

    Requires:
        - path is a non-empty string

    Ensures:
        - Returns True if the resolved path is within cu.get_project_root()
        - Returns False if the path escapes the project root (e.g., ../../etc/passwd)

    Args:
        path: The file path to validate (absolute or project-relative)

    Returns:
        bool: True if path is safe, False otherwise
    """
    project_root = os.path.realpath( cu.get_project_root() )

    # Normalize: if relative, prepend project root
    if path.startswith( "/" ):
        full_path = cu.get_project_root() + path
    else:
        full_path = cu.get_project_root() + "/" + path

    resolved = os.path.realpath( full_path )
    return resolved.startswith( project_root + "/" ) or resolved == project_root


async def match_research_docs( user_email: str, description: str, debug: bool = False ) -> List[ dict ]:
    """
    Match user description against docs using LLM (kaitchup/phi_4_14b).

    Searches the user's deep research directory AND additional directories
    from the 'podcast generator source search paths' config key.

    Uses the CoSA XML I/O pattern with PromptTemplateProcessor.
    Response is parsed via FuzzyFileMatchResponse.from_xml() - proper Pydantic XML I/O.

    Requires:
        - user_email is a valid email address
        - description is a non-empty string

    Ensures:
        - Returns list of 0-5 matching dicts with 'filename' and 'relative_path' keys
        - Returns empty list if no documents found

    Args:
        user_email: The user's email (determines research directory)
        description: Natural language description of desired research
        debug: Enable debug output

    Returns:
        List[ dict ]: Matching documents with 'filename' and 'relative_path' keys
    """
    from cosa.agents.llm_client_factory import LlmClientFactory
    from cosa.config.configuration_manager import ConfigurationManager
    from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
    from cosa.agents.io_models.utils.fuzzy_file_prefilter import prefilter_docs_map_by_keywords
    from cosa.agents.io_models.xml_models import FuzzyFileMatchResponse

    config_mgr    = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    project_root  = cu.get_project_root()

    # Build docs_map: { relative_path → abs_path } from all search dirs
    docs_map = {}

    # Source 1: Deep research directory
    research_dir = f"{project_root}/io/deep-research/{user_email}"
    if os.path.exists( research_dir ):
        for f in os.listdir( research_dir ):
            if f.endswith( ".md" ):
                rel_path = f"io/deep-research/{user_email}/{f}"
                docs_map[ rel_path ] = f"{research_dir}/{f}"

    # Source 2: Additional search paths from config
    search_paths_raw = config_mgr.get( "podcast generator source search paths", default="/src" )
    search_dirs = [ d.strip() for d in search_paths_raw.split( "," ) if d.strip() ]

    for search_dir in search_dirs:
        abs_search_dir = project_root + search_dir
        if not os.path.exists( abs_search_dir ):
            if debug: print( f"[match_research_docs] Search dir not found: {abs_search_dir}" )
            continue
        for root, _dirs, files in os.walk( abs_search_dir ):
            for f in files:
                if f.endswith( ".md" ):
                    abs_path = os.path.join( root, f )
                    rel_path = os.path.relpath( abs_path, project_root )
                    if rel_path not in docs_map:
                        docs_map[ rel_path ] = abs_path

    if not docs_map:
        if debug: print( f"[match_research_docs] No markdown files found in any search directory" )
        return []

    if debug:
        print( f"[match_research_docs] Found {len( docs_map )} documents across all search dirs" )
        print( f"[match_research_docs] Description: {description}" )

    # Pre-filter the candidate list by keyword overlap before the LLM call.
    # Voice transcriptions produce noisy descriptions and a repo can hold
    # thousands of markdown files; sending them all overwhelms the local LLM.
    # Shared with the expeditor path so there is one behaviour instead of two.
    docs_map, arbitrary = prefilter_docs_map_by_keywords( docs_map, description, debug=debug )
    if arbitrary:
        # The narrowing was too weak or lossy to trust: too many candidates to
        # send whole AND either no keyword overlap, a thin single-keyword best
        # match (a zero-overlap target could beat it), or a truncated scored list.
        # Returning no matches surfaces a visible "no document matched" to the
        # user (404) rather than letting the model pick confidently from a
        # shortlist the target may never have entered (rows c143fd84 / 888711f0).
        if debug: print( f"[match_research_docs] Weak/lossy narrowing on {len( docs_map )}-file cap — returning no matches so the user is asked for an exact path" )
        return []

    # Load prompt template
    template_path = config_mgr.get( "prompt template for fuzzy file matching" )
    template = cu.get_file_as_string( project_root + template_path )

    # Process template to inject XML example
    processor = PromptTemplateProcessor( debug=debug )
    template = processor.process_template( template, 'fuzzy file matching' )

    # Format with description and file list (send relative paths for better LLM context)
    file_list = "\n".join( f"- {rel}" for rel in sorted( docs_map.keys() ) )
    prompt = template.format( description=description, file_list=file_list )

    # Call LLM
    llm_factory  = LlmClientFactory()
    llm_spec_key = config_mgr.get( "llm spec key for fuzzy file matching" )
    llm_client   = llm_factory.get_client( llm_spec_key, debug=debug, verbose=False )

    try:
        response = llm_client.run( prompt )

        if debug: print( f"[match_research_docs] LLM response: {response[ :200 ]}..." )

        # Parse XML response using proper Pydantic XML I/O (NOT deprecated util_xml)
        parsed_response = FuzzyFileMatchResponse.from_xml( response )
        matches = parsed_response.get_matches_list()

        # Validate matches exist in docs_map (3-tier: exact path → bare filename → fuzzy)
        valid_matches = []
        all_rel_paths  = list( docs_map.keys() )
        all_basenames  = [ os.path.basename( p ) for p in all_rel_paths ]

        for m in matches:
            # Tier 1: Direct relative path match
            if m in docs_map:
                valid_matches.append( { "filename": os.path.basename( m ), "relative_path": m } )
                continue

            # Tier 2: Bare filename exact match
            tier2_found = False
            for rel_path in all_rel_paths:
                if os.path.basename( rel_path ) == m:
                    valid_matches.append( { "filename": m, "relative_path": rel_path } )
                    tier2_found = True
                    break
            if tier2_found:
                continue

            # Tier 3: Fuzzy match against both relative paths and bare filenames
            # This handles LLM responses with slight variations or partial paths
            fuzzy_path_hits = difflib.get_close_matches( m, all_rel_paths, n=1, cutoff=0.6 )
            if fuzzy_path_hits:
                best = fuzzy_path_hits[ 0 ]
                if debug: print( f"[match_research_docs] Fuzzy path match: '{m}' → '{best}'" )
                valid_matches.append( { "filename": os.path.basename( best ), "relative_path": best } )
                continue

            fuzzy_name_hits = difflib.get_close_matches( m, all_basenames, n=1, cutoff=0.6 )
            if fuzzy_name_hits:
                best_name = fuzzy_name_hits[ 0 ]
                # Find the corresponding relative path
                for rel_path in all_rel_paths:  # pragma: no branch - loop always breaks: best_name (L351) comes from get_close_matches(all_basenames) so by difflib's contract it is a member of all_basenames = [basename(p) for p in all_rel_paths]; some rel_path therefore matches at L354 → break (L356) always fires → natural exhaustion (353->324) is unreachable. The L350 `if fuzzy_name_hits:` guard rules out the empty-list [0] IndexError.
                    if os.path.basename( rel_path ) == best_name:
                        if debug: print( f"[match_research_docs] Fuzzy name match: '{m}' → '{best_name}'" )
                        valid_matches.append( { "filename": best_name, "relative_path": rel_path } )
                        break

        if debug: print( f"[match_research_docs] Matches: {valid_matches}" )

        return valid_matches

    except Exception as e:
        if debug: print( f"[match_research_docs] Error during fuzzy matching: {e}" )
        return []


async def get_user_document_selection(
    user_email: str,
    session_id: str,
    matches: List[ dict ],
    debug: bool = False
) -> Optional[ dict ]:
    """
    Present document options to user and wait for selection (BLOCKING).

    Uses voice_io.present_choices() which blocks until user responds.

    Requires:
        - user_email is a valid email
        - session_id is a valid WebSocket session
        - matches is a non-empty list of dicts with 'filename' and 'relative_path' keys

    Ensures:
        - Returns selected dict with 'filename' and 'relative_path' keys
        - Returns None if user cancels or times out

    Args:
        user_email: The user's email for notification routing
        session_id: WebSocket session ID
        matches: List of matching document dicts
        debug: Enable debug output

    Returns:
        dict: Selected document dict, or None if cancelled
    """
    from cosa.agents.podcast_generator import voice_io
    from cosa.agents.podcast_generator import cosa_interface

    # Re-establish core voice_io binding
    voice_io.reconfigure()

    # Set target_user so notifications route to the correct WebSocket session
    cosa_interface.TARGET_USER = user_email

    options = []
    for m in matches:
        rel  = m[ "relative_path" ]
        label = rel[ -45: ] if len( rel ) > 45 else rel
        if len( rel ) > 45:
            label = "..." + label
        options.append( { "label": label, "description": rel } )
    options.append( { "label": "Cancel", "description": "Don't create podcast" } )

    if debug:
        print( f"[get_user_document_selection] Presenting {len( options )} options" )

    # Use present_choices() which BLOCKS until user responds
    questions = [ {
        "question"    : "Which document should I use for the podcast?",
        "header"      : "Document",
        "multiSelect" : False,
        "options"     : options
    } ]

    result = await voice_io.present_choices(
        questions = questions,
        timeout   = 120,
        title     = "Select Source Document"
    )

    selection = result.get( "answers", {} ).get( "Document" )

    if debug:
        print( f"[get_user_document_selection] User selected: {selection}" )

    # User cancelled
    if selection == "Cancel" or not selection:
        return None

    # Find matching doc from truncated label or full relative_path
    for m in matches:
        rel   = m[ "relative_path" ]
        label = rel[ -45: ] if len( rel ) > 45 else rel
        if len( rel ) > 45:
            label = "..." + label
        if label == selection or rel == selection:
            return m

    return None


@router.post(
    "/submit",
    response_model=PodcastSubmitResponse | PodcastMatchingResponse,
    summary="Submit podcast generation job",
    description="Submit a podcast generation job. Accepts either a direct file path or a natural language description."
)
async def submit_podcast_job(
    request: PodcastSubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue ),
    websocket_mgr = Depends( get_websocket_mgr ),
):
    """
    Submit a podcast generation job with smart input parsing.

    Flow A (Direct Path):
        - Input looks like a file path
        - Validate path exists
        - Create job immediately
        - Return job_id and queue_position

    Flow B (Description):
        - Input looks like natural language
        - Fuzzy match against user's research documents
        - Send multiple choice notification for selection
        - Return status="matching" with instructions

    Requires:
        - Valid authentication token
        - research_source is non-empty

    Ensures:
        - Returns PodcastSubmitResponse if direct path mode
        - Returns PodcastMatchingResponse if description mode
        - Raises 404 if path not found (direct mode)
        - Raises 404 if no research documents match (description mode)
    """
    user_email = current_user.get( "email" )
    user_id    = current_user.get( "uid", user_email )
    session_id = current_user.get( "session_id", "unknown" )
    debug      = current_user.get( "debug", False )

    research_source = request.research_source.strip()

    if not research_source:
        raise HTTPException( status_code=400, detail="research_source cannot be empty" )

    # Smart input detection
    if is_research_path( research_source, user_email ):
        # Flow A: Direct path mode
        if debug:
            print( f"[submit_podcast_job] Direct path mode: {research_source}" )

        # Security: validate path stays within project root
        if not validate_source_path( research_source ):
            raise HTTPException(
                status_code=403,
                detail="Source path escapes project root. Access denied."
            )

        # Normalize path
        if research_source.startswith( "/" ):
            full_path = cu.get_project_root() + research_source
        else:
            full_path = cu.get_project_root() + "/" + research_source

        # Validate path exists
        if not os.path.exists( full_path ):
            raise HTTPException(
                status_code=404,
                detail=f"Research file not found: {research_source}"
            )

        # Create job using shared factory
        args_dict = { "research": full_path }
        if request.target_languages:
            args_dict[ "languages" ] = ",".join( request.target_languages )
        if request.dry_run:
            args_dict[ "dry_run" ] = True
        if request.force_failure_mode:
            args_dict[ "force_failure_mode" ] = request.force_failure_mode
        if request.audience:
            args_dict[ "audience" ] = request.audience
        if request.audience_context:
            args_dict[ "audience_context" ] = request.audience_context

        job = create_agentic_job(
            command    = "agent router go to podcast generator",
            args_dict  = args_dict,
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id,
            debug      = debug
        )

        if job is None:
            raise HTTPException( status_code=500, detail="Failed to create podcast job" )

        # Apply max_segments if specified (factory doesn't handle this)
        if request.max_segments:
            job.max_segments = request.max_segments

        # Scheduling attributes pass-through (CJ Flow timed execution + monopolize)
        if request.scheduled_at: job.scheduled_at = request.scheduled_at
        if request.monopolize:   job.monopolize   = request.monopolize
        # Lineage pass-through (bug 5ed4f187, mirrors swe_team 3a14292b): stamp the
        # spawning monopolizer's id so Gate B admits this child through the monopoly hold.
        if request.parent_id_hash: job.spawned_by_id_hash = request.parent_id_hash

        # Atomic: scope ID + index for user filtering BEFORE push (race condition prevention)
        job.id_hash = user_job_tracker.register_scoped_job( job.id_hash, user_id, session_id )

        # Push to todo queue
        todo_queue.push( job )

        # Get queue position (approximate - queue length after push)
        queue_position = todo_queue.size()

        return PodcastSubmitResponse(
            job_id         = job.id_hash,
            queue_position = queue_position,
            status         = "queued"
        )

    else:
        # Flow B: Description mode (fuzzy matching with blocking selection)
        if debug:
            print( f"[submit_podcast_job] Description mode: {research_source}" )

        # ── Step 0: Generate speculative job ID for notification routing ──
        # Mirrors the speculative ID pattern from todo_fifo_queue.py:1056-1117.
        # Notifications during fuzzy matching and user selection need a job_id
        # to route to, but the real job doesn't exist until after selection.
        from cosa.agents.podcast_generator import voice_io
        from cosa.agents.podcast_generator import cosa_interface

        # Re-establish core voice_io binding for description mode notifications
        voice_io.reconfigure()

        spec_id = f"pg-{uuid.uuid4().hex[ :8 ]}"
        spec_id = user_job_tracker.register_scoped_job( spec_id, user_id, session_id )

        spec_metadata = {
            'question_text' : research_source,
            'agent_type'    : 'Podcast Generator',
            'timestamp'     : cu.get_current_time(),
            'status'        : 'pending',
            'expediting'    : True
        }
        emit_job_state_transition( websocket_mgr, spec_id, JobState.PENDING, JobState.QUEUED, user_id, spec_metadata )

        # Set voice_io job_id so notifications during selection auto-route to spec card
        cosa_interface.TARGET_USER = user_email
        voice_io.set_job_id( spec_id )

        if debug:
            print( f"[submit_podcast_job] Speculative card emitted: {spec_id}" )

        try:
            # ── Resolve + collect args (row 7c46fdde, Rick's instruction: the
            # agentic card must USE the runtime argument facilitator) ──
            #
            # Default path: the Runtime Argument Expeditor owns BOTH document
            # resolution (fuzzy_file_match) AND missing-argument collection, and its
            # question flow surfaces on the SAME notification-answer surface this
            # endpoint already used for document selection — so it is reachable from
            # WITHIN this card, no new UI. Reach, not rebuild.
            #
            # The legacy endpoint-owned path (match_research_docs +
            # get_user_document_selection) is PRESERVED behind the config flag as a
            # same-day fallback for the demo — flip the flag off to restore it
            # without a code change.
            use_expeditor = todo_queue.config_mgr.get(
                "podcast card uses runtime argument expeditor",
                default=True, return_type="boolean"
            )

            if use_expeditor:
                from cosa.agents.runtime_argument_expeditor.expeditor import (
                    RuntimeArgumentExpeditor,
                    user_message_for_expedite_reason,
                )

                expeditor = RuntimeArgumentExpeditor(
                    config_mgr = todo_queue.config_mgr,
                    debug      = debug
                )
                # The RAE resolves "research" via fuzzy_file_match and batch-collects
                # any missing metadata (languages/audience/audience_context). The
                # card's typed description IS the original question.
                args_dict = expeditor.expedite(
                    command           = "agent router go to podcast generator",
                    raw_args          = "",
                    user_email        = user_email,
                    session_id        = session_id,
                    user_id           = user_id,
                    original_question = research_source,
                    job_id            = spec_id,
                )

                if args_dict is None:
                    # Say WHY it failed — only a genuine decline blames the user
                    # (bug 68198c9f); undeliverable / timed-out / unresolved do not.
                    spoken, _log = user_message_for_expedite_reason( expeditor._last_expedite_reason )
                    emit_job_state_transition( websocket_mgr, spec_id, JobState.QUEUED, JobState.CANCELLED, user_id )
                    user_job_tracker.remove_job( spec_id )
                    return PodcastMatchingResponse( status="cancelled", message=spoken )

                # Runtime/test-hook fields the RAE does not manage (research +
                # metadata already came from the expeditor).
                if request.dry_run:
                    args_dict[ "dry_run" ] = True
                if request.force_failure_mode:
                    args_dict[ "force_failure_mode" ] = request.force_failure_mode

            else:
                # ── Legacy fallback (preserved): endpoint owns resolution ──
                matches = await match_research_docs( user_email, research_source, debug=debug )

                if not matches:
                    emit_job_state_transition( websocket_mgr, spec_id, JobState.QUEUED, JobState.FAILED, user_id )
                    user_job_tracker.remove_job( spec_id )
                    raise HTTPException(
                        status_code=404,
                        detail="No matching research documents found. Please check your research library or provide a direct file path."
                    )

                selected_doc = await get_user_document_selection(
                    user_email = user_email,
                    session_id = session_id,
                    matches    = matches,
                    debug      = debug
                )

                if not selected_doc:
                    emit_job_state_transition( websocket_mgr, spec_id, JobState.QUEUED, JobState.CANCELLED, user_id )
                    user_job_tracker.remove_job( spec_id )
                    return PodcastMatchingResponse(
                        status  = "cancelled",
                        message = "Podcast generation cancelled by user."
                    )

                full_path = cu.get_project_root() + "/" + selected_doc[ "relative_path" ]

                if not validate_source_path( selected_doc[ "relative_path" ] ):
                    emit_job_state_transition( websocket_mgr, spec_id, JobState.QUEUED, JobState.FAILED, user_id )
                    user_job_tracker.remove_job( spec_id )
                    raise HTTPException(
                        status_code=403,
                        detail="Selected path escapes project root. Access denied."
                    )

                if not os.path.exists( full_path ):
                    emit_job_state_transition( websocket_mgr, spec_id, JobState.QUEUED, JobState.FAILED, user_id )
                    user_job_tracker.remove_job( spec_id )
                    raise HTTPException(
                        status_code=404,
                        detail=f"Selected file not found: {selected_doc[ 'relative_path' ]}"
                    )

                args_dict = { "research": full_path }
                if request.target_languages:
                    args_dict[ "languages" ] = ",".join( request.target_languages )
                if request.dry_run:
                    args_dict[ "dry_run" ] = True
                if request.force_failure_mode:
                    args_dict[ "force_failure_mode" ] = request.force_failure_mode
                if request.audience:
                    args_dict[ "audience" ] = request.audience
                if request.audience_context:
                    args_dict[ "audience_context" ] = request.audience_context

            # ── Shared job creation (both paths) ──
            job = create_agentic_job(
                command    = "agent router go to podcast generator",
                args_dict  = args_dict,
                user_id    = user_id,
                user_email = user_email,
                session_id = session_id,
                debug      = debug
            )

            if job is None:
                emit_job_state_transition( websocket_mgr, spec_id, JobState.QUEUED, JobState.FAILED, user_id )
                user_job_tracker.remove_job( spec_id )
                raise HTTPException( status_code=500, detail="Failed to create podcast job" )

            # Apply max_segments if specified
            if request.max_segments:
                job.max_segments = request.max_segments

            # Scheduling attributes pass-through (CJ Flow timed execution + monopolize)
            if request.scheduled_at: job.scheduled_at = request.scheduled_at
            if request.monopolize:   job.monopolize   = request.monopolize
            # Lineage pass-through (bug 5ed4f187, mirrors swe_team 3a14292b): stamp the
            # spawning monopolizer's id so Gate B admits this child through the monopoly hold.
            if request.parent_id_hash: job.spawned_by_id_hash = request.parent_id_hash

            # Inherit speculative ID (already registered with user_job_tracker)
            job.id_hash = spec_id

            # Push to todo queue (re-emits pending→todo — JS dedup Set drops it)
            todo_queue.push( job )

            # Get queue position
            queue_position = todo_queue.size()

            return PodcastSubmitResponse(
                job_id         = job.id_hash,
                queue_position = queue_position,
                status         = "queued"
            )

        finally:
            voice_io.clear_job_id()


def quick_smoke_test():
    """
    Quick smoke test for podcast_generator router.
    """
    cu.print_banner( "Podcast Generator Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.rest.routers.podcast_generator import router, is_research_path, validate_source_path
        print( "✓ Module imported successfully" )

        # Test 2: Router configuration
        print( "Testing router configuration..." )
        assert router.prefix == "/api/podcast-generator"
        assert "podcast-generator" in router.tags
        print( f"✓ Router prefix: {router.prefix}" )

        # Test 3: is_research_path function - deep-research path detection
        print( "Testing is_research_path() with deep-research paths..." )
        test_email = "test@example.com"

        # Should detect as path
        assert is_research_path( "/io/deep-research/test@example.com/report.md", test_email ) == True
        assert is_research_path( "io/deep-research/test@example.com/report.md", test_email ) == True
        print( "✓ Deep-research path patterns detected correctly" )

        # Test 4: is_research_path function - general path detection
        print( "Testing is_research_path() with general file paths..." )

        assert is_research_path( "src/rnd/2026.02.23-topic/overview.md", test_email ) == True
        assert is_research_path( "/src/rnd/report.md", test_email ) == True
        assert is_research_path( "src/docs/guide.txt", test_email ) == True
        assert is_research_path( "src/docs/page.html", test_email ) == True
        print( "✓ General file path patterns detected correctly" )

        # Test 5: is_research_path function - description detection
        print( "Testing is_research_path() with descriptions..." )

        # Should detect as description
        assert is_research_path( "my latest Claude Code research", test_email ) == False
        assert is_research_path( "research about AI safety", test_email ) == False
        assert is_research_path( "the trust proxy overview", test_email ) == False
        print( "✓ Description patterns detected correctly" )

        # Test 6: validate_source_path function
        print( "Testing validate_source_path()..." )

        assert validate_source_path( "/src/rnd/report.md" ) == True
        assert validate_source_path( "src/rnd/report.md" ) == True
        assert validate_source_path( "/io/deep-research/user@test.com/doc.md" ) == True
        # Traversal attack should fail
        assert validate_source_path( "../../etc/passwd" ) == False
        assert validate_source_path( "/src/../../etc/passwd" ) == False
        print( "✓ Path validation works correctly" )

        # Test 7: Request/Response models
        print( "Testing request/response models..." )
        req = PodcastSubmitRequest(
            research_source  = "test description",
            target_languages = [ "en" ],
            max_segments     = 5
        )
        assert req.research_source == "test description"
        assert req.target_languages == [ "en" ]
        assert req.max_segments == 5
        print( "✓ Request model works correctly" )

        resp = PodcastSubmitResponse(
            job_id         = "pg-abc123",
            queue_position = 1,
            status         = "queued"
        )
        assert resp.job_id == "pg-abc123"
        print( "✓ Response model works correctly" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
