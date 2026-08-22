import random
import threading
import uuid
from typing import Any, Optional, Dict, Type, List

import requests

from cosa.rest.fifo_queue import FifoQueue  # CJ Flow ingress queue — receives all incoming jobs

from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.agents.receptionist_agent import ReceptionistAgent
from cosa.agents.weather_agent import WeatherAgent
from cosa.agents.todo_list_agent import TodoListAgent
from cosa.agents.calendaring_agent import CalendaringAgent
from cosa.agents.math_agent import MathAgent
from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent
from cosa.agents.calculator.agent import CalculatorAgent
from cosa.rest.salutations import SALUTATIONS, parse_salutations
from cosa.rest.v2.registry import resolve   # the command->agent table (row 10ef4b64)
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.memory.gister import Gister
from cosa.memory.gist_normalizer import GistNormalizer
from cosa.memory.normalizer import Normalizer
from cosa.memory.query_log_table import QueryLogTable
from cosa.memory.embedding_manager import EmbeddingManager
from cosa.memory.embedding_provider import get_embedding_provider
from cosa.tools.search_lupin_v010 import LupinSearch

# from app       import emit_audio
from cosa.utils import util     as du
from cosa.agents.io_models.xml_models import CommandResponse
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError


from datetime import datetime
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.job_state import JobState
from cosa.rest.queue_util import emit_job_state_transition
from cosa.rest.queue_protocol import is_queueable_job

# Notification service imports for TTS migration (Session 97)
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    ResponseType
)

# Runtime Argument Expeditor imports for agentic job routing
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    ExpediteContext,
    user_message_for_expedite_reason,
)

# Mode-to-Agent mapping for direct routing (bypasses LLM router)
MODE_TO_AGENT = {
    "math"        : MathAgent,
    "calendar"    : CalendaringAgent,
    "weather"     : WeatherAgent,
    "receptionist": ReceptionistAgent,
    "todo"        : TodoListAgent,
    "datetime"    : DateAndTimeAgent,
    "calculator"  : CalculatorAgent,
}

# Mode metadata for UI display
MODE_METADATA = {
    "system"      : { "display_name": "System",        "description": "Normal LLM-based routing" },
    "math"        : { "display_name": "Math Agent",    "description": "Direct math calculations" },
    "calendar"    : { "display_name": "Calendar",      "description": "Calendar management" },
    "weather"     : { "display_name": "Weather",       "description": "Weather queries" },
    "receptionist": { "display_name": "Receptionist",  "description": "General assistance" },
    "todo"        : { "display_name": "Todo List",     "description": "Task management" },
    "datetime"    : { "display_name": "Date & Time",   "description": "Date/time queries" },
    "calculator"  : { "display_name": "Calculator",    "description": "Unit conversions, price comparison, mortgage" },
    # Agentic process modes (route through AGENTIC_MODE_MAP, not MODE_TO_AGENT)
    "deep_research"      : { "display_name": "Deep Research",       "description": "Investigate a topic in depth" },
    "podcast"            : { "display_name": "Podcast Generator",   "description": "Create a podcast from an existing document" },
    "research_to_podcast": { "display_name": "Research to Podcast", "description": "Research a topic and create a podcast" },
    "claude_code"        : { "display_name": "Claude Code",         "description": "Run a coding task" },
    "swe_team"           : { "display_name": "SWE Team",            "description": "Multi-agent engineering team" },
    "presentation"              : { "display_name": "Presentation",              "description": "Generate slides from a document" },
    "research_to_presentation"  : { "display_name": "Research to Presentation",  "description": "Research a topic and create slides" },
    "test_suite"                : { "display_name": "Test Suite",                "description": "Run integration and E2E tests" },
}

# Agentic mode keys → JOB_ARG_CONTRACTS routing command strings
# When user selects an agentic mode, this maps directly to the command
# that enters the `elif command in JOB_ARG_CONTRACTS:` branch
AGENTIC_MODE_MAP = {
    "deep_research"            : "agent router go to deep research",
    "podcast"                  : "agent router go to podcast generator",
    "research_to_podcast"      : "agent router go to research to podcast",
    "claude_code"              : "agent router go to claude code",
    "swe_team"                 : "agent router go to swe team",
    "presentation"             : "agent router go to presentation generator",
    "research_to_presentation" : "agent router go to research to presentation",
    "test_suite"               : "agent router go to test suite",
}


def get_routing_command( question, config_mgr, llm_factory, debug=False, verbose=False ):
    """
    Determine the routing command for a question via the LLM agent router.

    Requires:
        - question is a non-empty string
        - config_mgr exposes .get( "prompt template for agent router" ) and
          .get( "llm spec key for agent router" )
        - llm_factory exposes .get_client( spec_key, debug=, verbose= )

    Ensures:
        - Returns a ( command, args ) tuple of strings
        - Uses the LLM to determine the appropriate agent
        - Parses the XML response for command and args
        - Returns ( "unknown", "" ) on any XML parse failure

    Raises:
        - FileNotFoundError if prompt template missing
        - LLM errors propagated
    """
    router_prompt_template_path = config_mgr.get( "prompt template for agent router" )
    router_prompt_template = du.get_file_as_string( du.get_project_root() + router_prompt_template_path )

    prompt = router_prompt_template.format( voice_command=question )
    if debug and verbose: print( f"\n===== ROUTER PROMPT START =====\n{prompt}\n===== ROUTER PROMPT END =====\n" )

    llm_spec_key = config_mgr.get( "llm spec key for agent router" )
    llm_client = llm_factory.get_client( llm_spec_key, debug=debug, verbose=verbose )
    response = llm_client.run( prompt )
    if debug: print( f"LLM response: [{response}]" )

    # Parse results using Pydantic CommandResponse model
    try:
        parsed = CommandResponse.from_xml( response )
        command = parsed.command
        args    = parsed.args or ""
        if debug: print( f"Pydantic parsing extracted: command='{command}', args='{args}'" )
    except XMLParsingError as e:
        if debug: print( f"XML parsing failed: {e}" )
        command, args = "unknown", ""
    except Exception as e:
        if debug: print( f"Unexpected error during XML parsing: {e}" )
        command, args = "unknown", ""

    return command, args


class TodoFifoQueue( FifoQueue ):
    """
    Queue for managing todo items with agent routing capabilities.
    
    Handles question parsing, agent routing, and snapshot management for
    conversational AI tasks.
    """
    def __init__( self, websocket_mgr: Any, snapshot_mgr: Any, app: Any, config_mgr: Optional[Any]=None, emit_speech_callback: Optional[Any]=None, debug: bool=False, verbose: bool=False, silent: bool=False ) -> None:
        """
        Initialize the todo FIFO queue.
        
        Requires:
            - websocket_mgr is a valid WebSocketManager instance or None for testing
            - snapshot_mgr is a valid snapshot manager or None for testing
            - app is a Flask application instance or None for testing
            - config_mgr is None or a valid ConfigurationManager
            - emit_speech_callback is None or a callable function
            
        Ensures:
            - Sets up queue management components
            - Initializes salutations and filler phrase lists
            - Configures debug settings from config_mgr
            
        Raises:
            - None
        """
        
        super().__init__( websocket_mgr=websocket_mgr, queue_name="todo", emit_enabled=True )
        self.debug               = debug
        self.verbose             = verbose
        self.silent              = silent
        
        self.snapshot_mgr        = snapshot_mgr
        self.app                 = app
        self.push_counter        = 0
        self.config_mgr          = config_mgr
        self.emit_speech_callback = emit_speech_callback
        
        self.auto_debug   = False if config_mgr is None else config_mgr.get( "debug auto",  default=False, return_type="boolean" )
        self.inject_bugs  = False if config_mgr is None else config_mgr.get( "debug inject bugs", default=False, return_type="boolean" )
        
        # Initialize LLM client factory for v010 compatibility
        self.llm_factory = LlmClientFactory( debug=debug, verbose=verbose )

        # Initialize Gister for extracting question gists (backward compatibility)
        self.gister = Gister( debug=debug, verbose=verbose )

        # Initialize both text processors for runtime selection
        self.gist_normalizer = GistNormalizer( debug=debug, verbose=verbose )
        self.normalizer = Normalizer()

        # Initialize three-level architecture components
        self.query_log = QueryLogTable( debug=debug, verbose=verbose )
        self.embedding_manager  = EmbeddingManager( debug=debug, verbose=verbose )
        self._embedding_provider = get_embedding_provider( debug=debug, verbose=verbose )

        if self.debug: print( "TodoFifoQueue: Text processors and three-level architecture components initialized" )
        
        # Salutations to be stripped by a brute force method until the router parses
        # them off for us. The list moved to cosa.rest.salutations so the v2 flow reads
        # the SAME one — two copies is how two surfaces disagree about what a greeting is.
        self.salutations = SALUTATIONS
        self.hemming_and_hawing = [
            "", "", "", "umm...", "hmm...", "hmm...", "well...", "ahem..."
        ]
        self.thinking = [
            "interesting...", "thinking...", "let me see...", "let me think...", "let's see...",
            "let me think about that...", "let me think about it...", "let me check...", "checking..."
        ]
        
        # Producer-consumer coordination
        self.condition = threading.Condition()
        self.consumer_running = False

        # User mode state for direct agent routing (bypasses LLM router)
        # Key: user_id (str), Value: mode name (str) or None for system mode
        self.user_mode_state: Dict[str, Optional[str]] = {}
        
    def parse_salutations( self, transcription: str ) -> tuple[str, str]:
        """
        Parse salutations from the beginning of a transcription.
        
        Requires:
            - transcription is a string
            - self.salutations list is initialized
            
        Ensures:
            - Returns tuple of (salutations, remaining_text)
            - Salutations are extracted based on self.salutations list
            - Punctuation is handled properly
            
        Raises:
            - None
        """
        # The implementation moved to cosa.rest.salutations; this stays as the queue's
        # door onto it, and honours self.salutations so a test can still swap the list.
        return parse_salutations( transcription, self.salutations )

    # ========================================================================
    # User Mode Management Methods
    # ========================================================================

    def get_user_mode( self, user_id: str ) -> Optional[str]:
        """
        Get the current mode for a user.

        Requires:
            - user_id is a non-empty string

        Ensures:
            - Returns mode string if set, None if in system mode

        Raises:
            - None
        """
        return self.user_mode_state.get( user_id )

    def set_user_mode( self, user_id: str, mode: Optional[str] ) -> Optional[str]:
        """
        Set the mode for a user.

        Requires:
            - user_id is a non-empty string
            - mode is None (system) or a valid mode key from MODE_TO_AGENT or AGENTIC_MODE_MAP

        Ensures:
            - User's mode is updated in state dictionary
            - Returns the previous mode (or None)

        Raises:
            - ValueError if mode is not a valid mode key
        """
        if mode is not None and mode not in MODE_TO_AGENT and mode not in AGENTIC_MODE_MAP:
            valid_modes = list( MODE_TO_AGENT.keys() ) + list( AGENTIC_MODE_MAP.keys() )
            raise ValueError( f"Invalid mode '{mode}'. Available modes: {valid_modes}" )

        previous = self.user_mode_state.get( user_id )

        if mode is None:
            self.user_mode_state.pop( user_id, None )
        else:
            self.user_mode_state[ user_id ] = mode

        if self.debug:
            prev_display = previous or "system"
            new_display  = mode or "system"
            print( f"[MODE] User {user_id}: {prev_display} -> {new_display}" )

        return previous

    def clear_user_mode( self, user_id: str ) -> Optional[str]:
        """
        Clear the mode for a user (return to system mode).

        Requires:
            - user_id is a non-empty string

        Ensures:
            - User is removed from mode state dictionary
            - Returns the previous mode (or None)

        Raises:
            - None
        """
        previous = self.user_mode_state.pop( user_id, None )

        if self.debug:
            prev_display = previous or "system"
            print( f"[MODE] User {user_id}: {prev_display} -> system (cleared)" )

        return previous

    def get_available_modes( self ) -> List[Dict[str, str]]:
        """
        Get list of available modes with display names and descriptions.

        Ensures:
            - Returns list of mode dictionaries with key, display_name, description
            - Includes "system" mode as first option

        Raises:
            - None
        """
        modes = []
        for key, metadata in MODE_METADATA.items():
            modes.append( {
                "key"         : key,
                "display_name": metadata[ "display_name" ],
                "description" : metadata[ "description" ]
            } )
        return modes

    # ========================================================================
    # End User Mode Management Methods
    # ========================================================================

    def _is_fit( self, question: str ) -> bool:
        """
        Validate if job is suitable for processing.
        
        Requires:
            - question is a string
            
        Ensures:
            - Returns True if job meets processing criteria
            - Returns False if job should be rejected
            
        Raises:
            - None
        """
        if not question or not question.strip():
            return False
        if len( question ) > 1000:  # Example length limit
            return False
        if question.lower().startswith( "invalid" ):  # Example content filter
            return False
        return True
    
    def _notify_rejection( self, question: str, websocket_id: str, reason: str ) -> None:
        """
        Send rejection notification via WebSocket.
        
        Requires:
            - question is the rejected question
            - websocket_id is a valid websocket identifier  
            - reason is a descriptive rejection reason
            
        Ensures:
            - Sends job_rejected event to specific websocket session
            - Includes question, reason, and timestamp
            
        Raises:
            - None (handles errors gracefully)
        """
        if self.websocket_mgr:
            rejection_data = {
                "type": "job_rejected",
                "question": question,
                "reason": reason,
                "timestamp": du.get_current_time()
            }
            try:
                # Use emit_to_session if available, fallback to general emit
                if hasattr( self.websocket_mgr, 'emit_to_session_sync' ):
                    self.websocket_mgr.emit_to_session_sync( websocket_id, "job_rejected", rejection_data )
                else:
                    self.websocket_mgr.emit( "job_rejected", rejection_data )
                    
                if self.debug:
                    print( f"[TODO-QUEUE] Sent rejection notification for: {question[:50]}..." )
            except Exception as e:
                if self.debug:
                    print( f"[TODO-QUEUE] Failed to send rejection notification: {e}" )
    
    def push_job( self, question: str, websocket_id: str, user_id: str, user_email: str ) -> Dict:
        """
        Push a new job onto the queue based on the question.

        🔴 DEAD AS OF STEP 6c (2026-08-21) — NOTHING IN PRODUCTION CALLS THIS.

        This was the live voice path: a question came in, and everything below decided
        what to do with it — fitness, cache, confirmation, routing, agent construction,
        the queue push. All of that now lives in `AskFlow` (`cosa/rest/v2/flow.py`), and
        the switch happened by CUTOVER rather than by this method delegating to it:

            · 11a / 11b retired the router doors that called it; they answer 410.
            · step 12 moved the seven internal callers to flow.submit() / flow.ask().
            · door 8 — /api/upload-and-transcribe-mp3, the SPOKEN way in — hands the
              transcription to the flow in-process (routers/speech.py).

        The body survives only because steps 7b and 7c delete its internals next, and
        the queue's own coverage suite still drives it. Do not add a caller: a sweep
        (`src/tests/unit/test_6c_push_job_has_no_production_caller.py`) fails if any
        production module calls `push_job(` again.

        THE REASON THIS PARAGRAPH EXISTS rather than the deadness just being true: the
        plan's step 0 closed a trap where `grep "def save_snapshot"` returned the
        DEPRECATED manager first, and a reader followed it into code nobody runs. A
        440-line `push_job` that still reads as the live voice path is that same trap,
        set for the next person who greps for how a spoken question is handled.

        Requires:
            - question is a non-empty string
            - websocket_id is a non-empty string
            - user_id is a valid system ID
            - user_email is a valid email address for TTS routing
            - Queue and snapshot manager are initialized

        Ensures:
            - Handles blocking objects for confirmation
            - Searches for similar snapshots if applicable
            - Routes to appropriate agent or snapshot
            - Returns status message
            - Associates websocket_id and user_id with the job
            - Passes user_id to agent creation for event routing
            - Sets user_email on agent/job for TTS notification routing
            - Returns dict with "message" (str) and "job_id" (str or None)

        Raises:
            - None (exceptions handled internally)
        """
        similar_snapshots = [ ]
        
        # NEW: Pre-processing and validation
        if not self._is_fit( question ):
            reason = "Question does not meet processing criteria"
            if not question or not question.strip():
                reason = "Question cannot be empty"
            elif len( question ) > 1000:
                reason = "Question too long (max 1000 characters)"
            elif question.lower().startswith( "invalid" ):  # pragma: no branch - mirror of _is_fit's startswith-invalid false-condition (L329); the block is entered only when _is_fit is False, and not-empty + not->1000 above force this True → the elif False arc (a 4th rejection reason) is unreachable
                reason = "Question contains invalid content"
                
            self._notify_rejection( question, websocket_id, reason )
            return { "message": f"Job rejected: {reason}", "job_id": None }

        # THREE-LEVEL ARCHITECTURE: Generate representations and embeddings early
        # This needs to be available for all code paths, so do it before conditionals
        salutations, parsed_question = self.parse_salutations( question )

        # Process the question for gist generation
        enable_gisting = self.config_mgr.get( "fifo todo queue enable input gisting", default=True, return_type="boolean" )
        if enable_gisting:
            question_gist = self.gist_normalizer.get_normalized_gist( parsed_question )
        else:
            question_gist = self.normalizer.normalize( parsed_question )

        # Generate three-level representation
        query_verbatim   = question  # Exact user input
        query_normalized = self.normalizer.normalize( parsed_question )  # Always normalize for consistency
        query_gist       = question_gist  # Use the gist computed above

        # Generate embeddings using cache-first strategy
        embedding_verbatim = self._embedding_provider.generate_embedding(
            query_verbatim, content_type="prose"
        )
        embedding_normalized = self._embedding_provider.generate_embedding(
            query_normalized, content_type="prose"
        )
        # Track cache hits for analytics
        cache_hits = {
            'verbatim'   : len( embedding_verbatim ) > 0,
            'normalized' : len( embedding_normalized ) > 0
        }

        if self.debug and self.verbose:
            print( f"Three-level representation:" )
            print( f"  Verbatim:   '{query_verbatim}'" )
            print( f"  Normalized: '{query_normalized}'" )
            print( f"  Gist:       '{query_gist}'" )
            print( f"Embeddings generated - V:{len( embedding_verbatim )} N:{len( embedding_normalized )}" )

        # ⚰️ REMOVED — step 7c, 2026-08-21: the two-turn confirmation dialogue.
        #
        # WHAT WAS HERE: an `is_accepting_jobs()` gate, and behind it a `ConfirmationDialogue`
        # LLM call that read the user's NEXT spoken question as a yes/no answer about the
        # PREVIOUS one, then replayed a stashed "blocking object" snapshot at a hard-coded
        # score of 100.0. It depended on `FifoQueue.push_blocking_object()` setting
        # `_accepting_jobs = False`, which is why that method, `pop_blocking_object()` and
        # `is_accepting_jobs()` were deleted with it.
        #
        # WHY IT WAS BAD: nothing in the running system ever armed a blocking object, so the
        # gate never went false and the branch never ran — but everyone who touched push_job
        # still had to read it and reason about it. And on the paths where it WOULD have run
        # it was wrong twice over: it treated a fresh question as an answer to an older one,
        # and it recorded a guessed match as a perfect 100.0.
        #
        # WHAT CARRIES CONFIRMATION NOW: AskFlow's near-match ask (step 6b) — a targeted
        # yes/no about one named snapshot, where both "no" and a timeout fall through to
        # ordinary routing.
        #
        # PROVED UNREACHABLE BEFORE DELETING, not just argued: a probe recorded every trip of
        # the gate and the branch over 2026-08-21 16:30Z–23:07Z — six boots, 65
        # /api/upload-and-transcribe-mp3 + 2 /api/v2/ask + 1 /api/push — and logged nothing,
        # with a positive control proving the probe could fire. Caveat the window does not
        # cover: both probes sat inside `push_job`, which step 6c pinned as having zero
        # production callers, so the silence re-proves the cutover at least as much as the
        # branch. The probe module retired with this block.

        # DEMO KLUDGE: if the question doesn't start with "refactor", then we're going to search for similar snapshots
        if not question.lower().strip().startswith( "refactor " ):

            # salutations, question = self.parse_salutations( question )
            # question_gist = self.get_gist( question )

            du.print_banner( f"push_job( '{( salutations + ' ' + question ).strip()}' )", prepend_nl=True )
            # Top-1 + confirm strategy: no threshold filtering — all results returned by manager
            # threshold_question = self.config_mgr.get( "similarity_threshold_question",      default=98.0, return_type="float" )  # OBSOLETE
            # threshold_gist     = self.config_mgr.get( "similarity_threshold_question_gist", default=95.0, return_type="float" )  # OBSOLETE
            threshold_confirmation = self.config_mgr.get( "similarity threshold confirmation", default=90.0, return_type="float" )
            print( f"push_job(): Top-1 + confirm strategy (ask floor: {threshold_confirmation}%)" )

            # We're searching for similar snapshots without any salutations prepended to the question.
            # The snapshot manager internally handles hierarchical search (exact matches first, then similarity)
            similar_snapshots = self.snapshot_mgr.get_snapshots_by_question( parsed_question, question_gist=question_gist )
            print()
        else:
            print( "push_job(): Skipping snapshot search..." )
            similar_snapshots = [ ]
        
        # Flag to track if we need LLM routing (set when no cache match or user declines confirmation)
        needs_llm_routing = False

        # Top-1 + confirm strategy: 3-tier decision on best match
        if len( similar_snapshots ) > 0:

            best_score    = similar_snapshots[ 0 ][ 0 ]
            best_snapshot = similar_snapshots[ 0 ][ 1 ]

            # A similarity percentage outside [0,100] is not a strong match, it is a
            # BROKEN MEASUREMENT — and the old code read it as maximum confidence.
            # Bug 78f21b1b: query embeddings moved to a model that does not return
            # unit vectors, so `dot * 100` produced 1024.15% for a true cosine of
            # 0.517, and that landed in the `>= 100.0` perfect-match branch. Every
            # voice request was answered from cache and agent routing became
            # unreachable — silently, in 0 ms, which reads like success.
            #
            # Refuse the value rather than trusting it. Falling through to LLM
            # routing is the safe direction: the worst case is doing the work
            # instead of replaying a cached answer.
            if best_score < 0.0 or best_score > 100.0:
                print( f"push_job(): REJECTING out-of-range similarity {best_score:.1f}% "
                       f"(expected 0-100) — treating as NO cache match and routing normally. "
                       f"This means the scorer is misconfigured; see bug 78f21b1b." )
                # Set the flag DIRECTLY. Emptying similar_snapshots here would NOT
                # reach the outer `else` (the length check has already passed), so
                # needs_llm_routing would stay False and the request would fall
                # through doing nothing at all — a worse failure than the one being
                # fixed. Caught by tracing the control flow rather than assuming it.
                needs_llm_routing = True

            elif best_score >= 100.0:
                # Perfect match (L1/L2 exact or L4 at 100%) — auto-accept, no prompt
                print( f"push_job(): Perfect match (score: {best_score:.1f}%) — auto-accepting" )
                best_snapshot.last_question_asked = ( salutations + ' ' + question ).strip()
                self._dump_code( best_snapshot )

                match_result = {
                    'snapshot_id' : best_snapshot.id_hash,
                    'type'        : 'exact_match',
                    'confidence'  : best_score
                }
                embeddings = {
                    'verbatim'   : embedding_verbatim,
                    'normalized' : embedding_normalized
                }
                self._log_query_with_results(
                    query_verbatim, query_normalized, query_gist,
                    user_id, websocket_id, embeddings, cache_hits, match_result
                )

                return self._queue_best_snapshot( best_snapshot, best_score, user_id, user_email )

            elif best_score >= threshold_confirmation:
                # Good enough to ask — confirm with user (score >= 90%)
                confirmation_enabled = self.config_mgr.get( "similarity confirmation enabled", default=True, return_type="boolean" )

                if confirmation_enabled:

                    msg = f"Is that the same as: {best_snapshot.question}?"
                    du.print_banner( msg )
                    print( f"Asking user for confirmation (score: {best_score:.1f}%)..." )

                    request = NotificationRequest(
                        message          = msg,
                        response_type    = ResponseType.YES_NO,
                        response_default = "no",
                        timeout_seconds  = 30,
                        priority         = "high",
                        suppress_ding    = True,  # Queue TTS - no ding
                        target_user      = user_email,
                        sender_id        = f"queue.{self.queue_name or 'todo'}@lupin.deepily.ai"
                    )

                    response = notify_user_sync(
                        request,
                        retry_on_timeout = True,    # Enable exponential backoff
                        max_attempts     = 3,       # 30s → 60s → 120s
                        backoff_multiplier = 2.0
                    )

                    if response.status == "responded" and response.response_value == "yes":
                        print( f"User confirmed cached result match (score: {best_score:.1f}%)" )
                        best_snapshot.last_question_asked = ( salutations + ' ' + question ).strip()
                        self._dump_code( best_snapshot )

                        match_result = {
                            'snapshot_id' : best_snapshot.id_hash,
                            'type'        : 'user_confirmed_similarity_match',
                            'confidence'  : best_score
                        }
                        embeddings = {
                            'verbatim'   : embedding_verbatim,
                            'normalized' : embedding_normalized
                        }
                        self._log_query_with_results(
                            query_verbatim, query_normalized, query_gist,
                            user_id, websocket_id, embeddings, cache_hits, match_result
                        )

                        return self._queue_best_snapshot( best_snapshot, best_score, user_id, user_email )
                    else:
                        print( f"User response: '{response.status}:{response.response_value}' - routing as new question..." )
                        needs_llm_routing = True

                else:
                    # Confirmation disabled — auto-accept the best semantic match
                    print( f"Similarity confirmation disabled, auto-accepting match (score: {best_score:.1f}%)" )
                    best_snapshot.last_question_asked = ( salutations + ' ' + question ).strip()
                    self._dump_code( best_snapshot )

                    match_result = {
                        'snapshot_id' : best_snapshot.id_hash,
                        'type'        : 'auto_accepted_similarity_match',
                        'confidence'  : best_score
                    }
                    embeddings = {
                        'verbatim'   : embedding_verbatim,
                        'normalized' : embedding_normalized
                    }
                    self._log_query_with_results(
                        query_verbatim, query_normalized, query_gist,
                        user_id, websocket_id, embeddings, cache_hits, match_result
                    )

                    return self._queue_best_snapshot( best_snapshot, best_score, user_id, user_email )

            else:
                # Below ask threshold — log and skip, route to LLM
                print( f"push_job(): Ignoring low-similarity match (score: {best_score:.1f}%) for: '{best_snapshot.question}'" )
                needs_llm_routing = True
        else:
            # No similar snapshots found
            needs_llm_routing = True

        # Route through LLM if no cache match or user declined confirmation
        if needs_llm_routing:  # pragma: no branch - always True here: every non-returning path sets it True (out-of-range rejection / declined confirmation / below-threshold / no-snapshots); all cache-hit paths return before this → the False arc is unreachable

            print( "Routing through LLM (no cache match or user declined)..." )
            
            # Note the distinction between salutation and the question: all agents except the receptionist get the question only.
            # The receptionist gets the salutation plus the question to help it decide how it will respond.
            salutation_plus_question = ( salutations + " " + question ).strip()

            # NEW: Check user mode BEFORE LLM routing
            user_mode = self.get_user_mode( user_id )

            # AGENTIC_MODE_MAP is checked before MODE_TO_AGENT for deterministic
            # precedence. The two maps are DISJOINT by invariant — MODE_TO_AGENT
            # holds only the direct single-token agents, AGENTIC_MODE_MAP the 8
            # agentic modes; their key sets do not overlap (guarded by
            # test_todo_fifo_queue_mode_routing.py::test_agentic_and_direct_dicts_disjoint_today,
            # with a must-fail control). If a future change ever lets an agentic key
            # into MODE_TO_AGENT, this order keeps the canonical "agent router go to
            # <name>" (with spaces) winning over f-string synthesis, which would emit
            # an underscore command ("...test_suite") that matches no registered command.
            if user_mode and user_mode in AGENTIC_MODE_MAP:
                # Agentic mode - bypass LLM router, produce agentic routing command
                command = AGENTIC_MODE_MAP[ user_mode ]
                args = ""
                if self.debug:
                    print( f"[MODE] User {user_id} in '{user_mode}' agentic mode - bypassing LLM router" )
                    print( f"[MODE] Agentic routing to: {command}" )
            elif user_mode and user_mode in MODE_TO_AGENT:
                # Direct routing - bypass LLM router when user is in agent mode
                # (single-token modes: calculator, todo, calendar, weather, datetime)
                command = f"agent router go to {user_mode}"
                args = ""
                if self.debug:
                    print( f"[MODE] User {user_id} in '{user_mode}' mode - bypassing LLM router" )
                    print( f"[MODE] Direct routing to: {command}" )
            else:
                # Normal LLM-based routing (system mode)
                # We're going to give the routing function maximum information, hence including the salutation with the question
                # ¡OJO! I know this is a tad adhoc-ish, but it's what we want... for the moment at least
                command, args = self._get_routing_command( salutation_plus_question )
                if self.debug:
                    print( f"[ROUTER] LLM selected: {command}" )
            
            starting_a_new_job = "New {agent_type} job..."
            ding_for_new_job   = False
            agent              = None
            self.push_counter += 1
            
            # TODO: implement search and summarize training and routing
            if question.lower().strip().startswith( "search and summarize" ):

                msg = du.print_banner( f"TO DO: train and implement 'agent router go to search and summary' command {command}" )
                print( msg )
                # TTS Migration (Session 97): Use notification service instead of _emit_speech
                self._notify( f"{self.hemming_and_hawing[ random.randint( 0, len( self.hemming_and_hawing ) - 1 ) ]} I'm gonna ask our research librarian about that", target_user=user_email )
                msg = self._search_and_summarize_safely( question_gist )
            
            elif resolve( command, self._crud_agents_enabled() ) is not None:
                # ─── ONE TABLE LOOKUP, replacing six hand-written elif branches (row 10ef4b64) ───
                # Rick, 2026-08-20: "those agents could be instantiated using a string key
                # referencing a dictionary of prototypical Agent Objects... that doesn't take
                # 10 elif branches." The dictionary already existed — cosa/rest/v2/registry.py —
                # and only the HTTP route was asking it. ADDING A SEVENTH CONVERSATIONAL COMMAND
                # NOW REQUIRES NO EDIT HERE; it is one AgentSpec row.
                #
                # ONE resolver, and it applies the CRUD fork itself (2b). The flag is read
                # HERE rather than at the top of the chain so a non-conversational command
                # still costs no config lookup, exactly as before.
                voice_spec = resolve( command, self._crud_agents_enabled() )
                factory, agent_label, ding_for_new_job = voice_spec.factory, voice_spec.label, voice_spec.dings
                agent = factory(
                    question=question, question_gist=question_gist, last_question_asked=salutation_plus_question,
                    push_counter=self.push_counter, user_id=user_id, user_email=user_email,
                    session_id=websocket_id, debug=True, verbose=False,
                    auto_debug=self.auto_debug, inject_bugs=self.inject_bugs
                )
                msg = starting_a_new_job.format( agent_type=agent_label )
                # ⚠️ MathAgent used to receive `salutation_plus_question` as its `question` while
                # every other agent received the bare `question`. Rick ruled 2026-08-20 to DROP the
                # quirk (it matches the registry's own risk-10 ruling), so math now gets the bare
                # question like everything else. This IS a behaviour change and is deliberate — if a
                # math regression ever appears, look here first.
            elif command in ( "agent router go to automatic", "agent router go to automatic routing mode" ):
                previous_mode = self.clear_user_mode( user_id )
                if previous_mode:
                    msg = f"Switching back to automatic routing mode. Was in {previous_mode} mode."  # pragma: no cover - unreachable: previous_mode is always falsy here. set_user_mode (L248-249) rejects modes not in MODE_TO_AGENT/AGENTIC_MODE_MAP, so a truthy user_mode is always map-routed (L643/650); the LLM "automatic" command only arises in the L658 else (user_mode None) → clear_user_mode (L715) returns None
                else:
                    msg = "Automatic routing is already active."
                print( f"[AUTO-ROUTE] User {user_id} returning to automatic routing (was: {previous_mode})" )
                self._notify( msg, target_user=user_email )
                return { "message": msg, "job_id": None }
            elif command == "agent router go to receptionist" or command == "none":
                print( f"Routing '{command}' to receptionist..." )
                agent = ReceptionistAgent( question=question, question_gist=question_gist, last_question_asked=salutation_plus_question, push_counter=self.push_counter, user_id=user_id, user_email=user_email, session_id=websocket_id, debug=True, verbose=False, auto_debug=self.auto_debug, inject_bugs=self.inject_bugs )
                # Randomly grab hemming and hawing string and prepend it to a randomly chosen thinking string
                msg = f"{self.hemming_and_hawing[ random.randint( 0, len( self.hemming_and_hawing ) - 1 ) ]} {self.thinking[ random.randint( 0, len( self.thinking ) - 1 ) ]}".strip()
                # ding_for_new_job = False
            elif command in JOB_ARG_CONTRACTS:
                # Skip disambiguation if user explicitly selected this agentic mode from dropdown
                if user_mode and user_mode in AGENTIC_MODE_MAP:
                    msg = self._handle_agentic_command(
                        command, args, user_id, user_email, websocket_id, salutation_plus_question
                    )
                else:
                    # Disambiguation confirmation for LLM-routed agentic commands
                    confirmed_command = self._confirm_agentic_routing(
                        command, args, user_id, user_email, salutation_plus_question
                    )
                    if confirmed_command is None:
                        # None now covers explicit Cancel AND timeout/error abort (row cad45cf1)
                        msg = "Command cancelled — no confirmation received."
                    else:
                        msg = self._handle_agentic_command(
                            confirmed_command, args, user_id, user_email, websocket_id, salutation_plus_question
                        )
                # _handle_agentic_command handles push + notify internally; skip fallthrough
                return { "message": msg, "job_id": None }
            elif command == "unknown":
                # 720ce725: a GENUINE non-resolution — XML parse failure / gibberish
                # (_get_routing_command returns ("unknown","") on any parse failure) —
                # hands off to the receptionist instead of silently WEB-SEARCHING the
                # user's question (the old else did self._search_and_summarize_safely,
                # answering a different question with no signal the route missed).
                print( f"[ROUTER-MISS] unresolved command '{command}' → receptionist hand-off (reason=unknown_command)" )
                agent = ReceptionistAgent( question=question, question_gist=question_gist, last_question_asked=salutation_plus_question, push_counter=self.push_counter, user_id=user_id, user_email=user_email, session_id=websocket_id, debug=True, verbose=False, auto_debug=self.auto_debug, inject_bugs=self.inject_bugs )
                msg = f"{self.hemming_and_hawing[ random.randint( 0, len( self.hemming_and_hawing ) - 1 ) ]} {self.thinking[ random.randint( 0, len( self.thinking ) - 1 ) ]}".strip()
            else:
                # 720ce725 (María's design): the router EMITTED a command that resolves
                # NOWHERE — not conversational, not receptionist/none, not in
                # JOB_ARG_CONTRACTS. That is a routing/wiring bug, so FAIL LOUDLY:
                # never a silent web-search (the old defect), never a receptionist
                # smoothing a real bug into a friendly non-answer.
                # Mechanism = loud error banner + honest user notify + no job (job_id
                # None). Chosen over `raise` because push_job runs on the LIVE speech
                # API path (routers/speech.py) where an unhandled raise would 500 the
                # request; flagged for María/Tiberius in the landing report.
                print( du.print_banner( f"ROUTER-MISS LOUD FAIL: router emitted unwired command {command!r} — no agent/factory handles it (720ce725)" ) )
                self._notify( f"I heard a command I don't know how to run: {command}. That's a routing bug on my side, not your question.", target_user=user_email )
                return { "message": f"Unroutable command (no wiring): {command}", "job_id": None }
                
            if ding_for_new_job:
                self.websocket_mgr.emit( 'notification_sound_update', { 'soundFile': '/static/gentle-gong.mp3' } )
            if agent is not None:
                # Atomic: scope ID + index for user filtering BEFORE push (race condition prevention)
                agent.id_hash = self.user_job_tracker.register_scoped_job( agent.id_hash, user_id, websocket_id )
                self.push( agent )
            
            # TTS Migration (Session 98): Use notification service instead of emit_speech_callback
            self._notify( msg, job=agent )

            # Log query with no match results (new agent created)
            match_result = {
                'snapshot_id': '',
                'type': 'no_match_new_agent',
                'confidence': 0.0
            }
            embeddings = {
                'verbatim'   : embedding_verbatim,
                'normalized' : embedding_normalized
            }
            self._log_query_with_results(
                query_verbatim, query_normalized, query_gist,
                user_id, websocket_id, embeddings, cache_hits, match_result
            )

            return { "message": msg, "job_id": agent.id_hash if agent else None }

    def _log_query_with_results( self,
                               query_verbatim: str,
                               query_normalized: str,
                               query_gist: str,
                               user_id: str,
                               websocket_id: str,
                               embeddings: dict,
                               cache_hits: dict,
                               match_result: dict = None,
                               processing_time_ms: int = 0 ) -> None:
        """
        Log query with three-level representation and results.

        This is called at the end of push_job to capture the complete query processing
        including match results and performance metrics.
        """
        try:
            if self.debug:
                print( f"Logging query: '{du.truncate_string( query_verbatim )}'" )

            self.query_log.log_query(
                query_verbatim=query_verbatim,
                query_normalized=query_normalized,
                query_gist=query_gist,
                user_id=user_id,
                session_id=websocket_id,
                input_type="api",  # Could be enhanced to detect voice vs text
                embeddings=embeddings,
                match_result=match_result,
                processing_time_ms=processing_time_ms,
                cache_hits=cache_hits
            )

        except Exception as e:
            if self.debug:
                print( f"Error logging query: {e}" )

    def _dump_code( self, best_snapshot: SolutionSnapshot ) -> None:
        """
        Debug helper to print snapshot code.
        
        Requires:
            - best_snapshot is a valid SolutionSnapshot
            - best_snapshot.code exists
            
        Ensures:
            - Prints code if debug and verbose are True
            - Formats output with banner
            
        Raises:
            - None
        """
        if self.debug and self.verbose:
            lines_of_code = best_snapshot.code
            if len( lines_of_code ) > 0:
                du.print_banner( f"Code for [{best_snapshot.question}]:" )
            else:
                du.print_banner( "Code: NONE found?" )
            for line in lines_of_code:
                print( line )
            if len( lines_of_code ) > 0:
                print()
                
    def _queue_best_snapshot( self, best_snapshot: SolutionSnapshot, best_score: float, user_id: str, user_email: str ) -> Dict:
        """
        Queue the best matching snapshot for execution.

        Requires:
            - best_snapshot is a valid SolutionSnapshot
            - best_score is between 0 and 100
            - user_id is a valid system ID
            - user_email is a valid email address for TTS routing
            - Queue is initialized

        Ensures:
            - Creates a copy of the snapshot with user_email for TTS routing
            - Configures job with current settings
            - Pushes job to queue
            - Emits socket updates
            - Returns dict with "message" (str) and "job_id" (str)

        Raises:
            - None
        """
        job = best_snapshot.get_copy( user_email=user_email )
        print( "Python object ID for copied job: " + str( id( job ) ) )
        job.debug   = self.debug
        job.verbose = self.verbose
        job.add_synonymous_question( best_snapshot.last_question_asked, score=best_score )

        job.run_date     = du.get_current_datetime()
        job.push_counter = self.push_counter + 1

        # Atomic: scope ID + index for user filtering
        job.id_hash = self.user_job_tracker.register_scoped_job( best_snapshot.id_hash, user_id )

        print()

        if self.size() != 0:
            suffix = "s" if self.size() > 1 else ""
            # TTS Migration (Session 98): Use notification service instead of emit_speech_callback
            self._notify( f"{self.size()} job{suffix} ahead of this one", job=job )
        else:
            print( "No jobs ahead of this one in the todo Q" )

        self.push( job )  # Auto-emits 'todo_update' via parent class

        msg = f'Job added to queue. Queue size [{self.size()}]'
        return { "message": msg, "job_id": job.id_hash }
    
    def _search_and_summarize_safely( self, question_gist: str ) -> str:
        """
        Run a web search, returning a spoken message even when the search backend is down.

        The push path calls this synchronously, so an unhandled transport error here
        surfaces to the user as an HTTP 500 from /api/push with a stack trace and no
        explanation. Two unrelated conditions — "we could not route your request" and
        "a third-party search API is unavailable" — must not both present as a 500.

        Requires:
            - question_gist is a non-empty string

        Ensures:
            - returns a non-empty string suitable for speaking to the user
            - never raises on a search-backend transport or HTTP failure

        Raises:
            - nothing for search-backend failures; unrelated exceptions propagate
        """
        try:
            search = LupinSearch( query=question_gist )
            search.search_and_summarize_the_web()
            return search.get_results( scope="summary" )

        except requests.exceptions.RequestException as e:
            print( f"[SEARCH] Web search backend unavailable: {e}" )
            return "I couldn't work out which agent handles that, and the web search I fall back on isn't answering right now. Could you rephrase it?"

    def _get_routing_command( self, question: str ) -> tuple[str, str]:
        """
        Thin delegating shim over the module-level get_routing_command.

        Requires:
            - question is a non-empty string
            - self.config_mgr, self.llm_factory, self.debug, self.verbose are set

        Ensures:
            - Returns a ( command, args ) tuple by delegating to
              get_routing_command with this queue's config + LLM factory
            - Behavior is identical to the former inline implementation

        Raises:
            - FileNotFoundError if prompt template missing
            - LLM errors propagated
        """
        return get_routing_command( question, self.config_mgr, self.llm_factory, debug=self.debug, verbose=self.verbose )

    def _crud_agents_enabled( self ):
        """
        Check if CRUD DataFrame agents are enabled via feature flag.

        Requires:
            - self.config_mgr is a valid ConfigurationManager

        Ensures:
            - Returns True if 'crud for dataframes agents enabled' is 'true'
            - Returns True by default (flag missing = enabled)
        """
        return self.config_mgr.get( "crud for dataframes agents enabled", default="true" ).strip().lower() == "true"

    # Product name mapping for agentic command disambiguation
    CARD_LABELS = {
        "agent router go to deep research"             : "Deep Dive (investigate a topic)",
        "agent router go to podcast generator"         : "Doc-to-Pod (create a podcast from an existing document)",
        "agent router go to research to podcast"       : "PodMaker (research a topic and create a podcast)",
        "agent router go to claude code"               : "Claude Code (run a coding task)",
        "agent router go to presentation generator"    : "SlideCraft (create a presentation from a document)",
        "agent router go to research to presentation"  : "Research-to-Slides (research a topic and create a presentation)",
        "agent router go to swe team"                  : "SWE Team (multi-agent engineering team)",
        "agent router go to bug fix expediter"         : "Bug Fix Expediter (diagnose and fix a failed job)",
        "agent router go to test suite"                : "TestRunner (run integration and E2E test suites)",
        "agent router go to test fix expediter resume" : "Test Fix Expediter Resume (resume a stalled TFE job)",
    }

    def _confirm_agentic_routing( self, command, args, user_id, user_email, original_question ):
        """
        Confirm agentic command routing with user via voice prompt.
        Shows what was detected and offers alternatives from the same confusable group.

        Requires:
            - command is a valid JOB_ARG_CONTRACTS key
            - user_email is set for notification routing

        Ensures:
            - Returns confirmed command string, or None if cancelled
            - User sees product name, not internal command string
            - On timeout or notification error, returns None (ABORTS): a silent
              timeout must not masquerade as a confirmation of a possibly-wrong
              detection, so the detected command is NOT auto-run. Row cad45cf1.
            - The wait window is read from config key
              "agentic routing confirm timeout seconds" (default 30), not a literal.
        """
        detected_name = self.CARD_LABELS.get( command, command )

        timeout_seconds = self.config_mgr.get( "agentic routing confirm timeout seconds", default=30, return_type="int" )

        # Build multiple choice options: detected option always first, then alternatives, then cancel
        options = []
        options.append( { "label": detected_name, "description": "This is what I detected" } )
        for cmd, name in self.CARD_LABELS.items():
            if cmd != command:
                options.append( { "label": name, "description": "Switch to this instead" } )
        options.append( { "label": "Cancel", "description": "Nevermind, cancel this command" } )

        request = NotificationRequest(
            message         = f"I think you want {detected_name}. Is that right?",
            response_type   = ResponseType.MULTIPLE_CHOICE,
            target_user     = user_email,
            timeout_seconds = timeout_seconds,
            sender_id       = "agentic.router@lupin.deepily.ai",
            priority        = "high",
            title           = "Confirm Command",
            suppress_ding   = True,
            response_options = {
                "questions": [ {
                    "question"     : f"I think you want {detected_name}. Is that right?",
                    "header"       : "Command",
                    "multi_select" : False,
                    "options"      : options
                } ]
            }
        )

        response = notify_user_sync( request, debug=self.debug )

        if response.is_timeout or response.is_error:
            if self.debug: print( f"Confirmation timeout/error — ABORTING, not auto-running detected command [{command}]" )
            return None  # No confirmation received: abort rather than masquerade a silent timeout as a "yes"

        # Parse response — handle both raw string and JSON formats
        selected = response.response_value
        if self.debug: print( f"User selected (raw): [{selected}]" )

        # MULTIPLE_CHOICE may return JSON: {"answers": {"Command": "Deep Dive ..."}}
        if selected and selected.startswith( "{" ):
            import json
            try:
                parsed   = json.loads( selected )
                answers  = parsed.get( "answers", {} )
                selected = answers.get( "Command", answers.get( "0", selected ) )
            except ( json.JSONDecodeError, AttributeError ):
                pass  # Use raw value as-is

        if self.debug: print( f"User selected (parsed): [{selected}]" )

        if selected is None or selected == "Cancel":
            return None

        # Reverse lookup: product name → command
        for cmd, name in self.CARD_LABELS.items():
            if name == selected:
                return cmd

        # Fallback: proceed with original
        return command

    def _handle_agentic_command( self, command, raw_args, user_id, user_email, session_id, original_question ):
        """
        Handle an agentic agent command via the Runtime Argument Expeditor.

        Creates a speculative job card in the UI BEFORE the expeditor runs,
        so the user sees immediate visual feedback. The expeditor's notifications
        route to this card via job_id. On success the real job inherits the
        speculative ID; on cancel/failure the card moves to the dead queue.

        Requires:
            - command is a key in JOB_ARG_CONTRACTS
            - raw_args is a string (may be empty)
            - user_id, user_email, session_id are non-empty strings
            - original_question is the full voice command string

        Ensures:
            - Returns human-readable status message
            - Creates and queues an agentic job if expeditor succeeds
            - Cleans up speculative card on cancellation or failure

        Args:
            command: Routing command key
            raw_args: LORA-extracted arguments
            user_id: System user ID
            user_email: User's email address
            session_id: WebSocket session ID
            original_question: Full voice command transcription

        Returns:
            str: Status message
        """
        # Check if expeditor is enabled
        enabled = self.config_mgr.get(
            "runtime argument expeditor enabled", default=True, return_type="boolean"
        )
        if not enabled:
            return f"Runtime argument expeditor is disabled. Cannot process command: {command}"

        # ── Step 1: Generate speculative job ID ──────────────────────────
        agent_entry = JOB_ARG_CONTRACTS.get( command, {} )
        job_prefix  = agent_entry.get( "job_prefix", "aj" )
        spec_id     = f"{job_prefix}-{uuid.uuid4().hex[ :8 ]}"
        spec_id     = self.user_job_tracker.register_scoped_job( spec_id, user_id, session_id )

        # ── Step 2: Emit speculative pending→todo with expediting flag ───
        display_name = agent_entry.get( "display_name", command.replace( "agent router go to ", "" ) )
        spec_metadata = {
            'question_text' : original_question,
            'agent_type'    : display_name,
            'timestamp'     : du.get_current_time(),
            'status'        : 'pending',
            'expediting'    : True,
            'user_email'    : user_email
        }
        emit_job_state_transition( self.websocket_mgr, spec_id, JobState.PENDING, JobState.QUEUED, user_id, spec_metadata )

        if self.debug:
            print( f"[TODO-QUEUE] Speculative card emitted: {spec_id} (expediting=True)" )

        # ── Step 3: Run expeditor with speculative job_id ────────────────
        expeditor = RuntimeArgumentExpeditor(
            config_mgr = self.config_mgr,
            debug      = self.debug,
            verbose    = self.verbose
        )

        # The reason this call fails comes back on OUR context, not on the shared
        # expeditor (row 10c60712) — two callers in flight at once each read their
        # own.
        expedite_context = ExpediteContext()
        args_dict = expeditor.expedite(
            command           = command,
            raw_args          = raw_args,
            user_email        = user_email,
            session_id        = session_id,
            user_id           = user_id,
            original_question = original_question,
            job_id            = spec_id,
            context           = expedite_context
        )

        # ── Step 4: Handle failure — say WHY, and only blame the user for a real "no" ──
        # expedite() records the cause on the caller's context (bug 68198c9f). A
        # prompt that could not be delivered, or timed out, is a machine failure — it
        # must never be reported as the user cancelling a job they never saw.
        if args_dict is None:
            spoken, log_line = user_message_for_expedite_reason( expedite_context.reason )
            emit_job_state_transition( self.websocket_mgr, spec_id, JobState.QUEUED, JobState.CANCELLED, user_id )
            self.user_job_tracker.remove_job( spec_id )
            self._notify( spoken, target_user=user_email )
            return log_line

        # ── Step 4.5: Extract runtime scheduling args (not agent-specific) ──
        scheduled_at_raw = args_dict.pop( "scheduled_at", None )
        monopolize_raw   = args_dict.pop( "monopolize", None )

        # Normalize voice-path defaults: "immediately" → None, "no"/"yes" → bool
        if scheduled_at_raw and str( scheduled_at_raw ).lower() in ( "immediately", "now", "none" ):
            scheduled_at_raw = None

        if isinstance( monopolize_raw, str ):
            monopolize_raw = monopolize_raw.lower() in ( "yes", "true", "1" )
        else:
            monopolize_raw = bool( monopolize_raw ) if monopolize_raw else False

        # ── Step 5: Create real job and inherit speculative ID ────────────
        job = create_agentic_job(
            command    = command,
            args_dict  = args_dict,
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id,
            debug      = self.debug,
            verbose    = self.verbose
        )

        if job is None:
            emit_job_state_transition( self.websocket_mgr, spec_id, JobState.QUEUED, JobState.FAILED, user_id )
            self.user_job_tracker.remove_job( spec_id )
            self._notify( "Failed to create job.", target_user=user_email )
            return "Failed to create agentic job."

        # Override the job's auto-generated ID with the speculative ID
        job.id_hash = spec_id

        # Apply runtime scheduling attributes (CJ Flow timed execution + monopolize)
        if scheduled_at_raw: job.scheduled_at = scheduled_at_raw
        if monopolize_raw:   job.monopolize   = monopolize_raw

        # Ding for new job
        self.websocket_mgr.emit( 'notification_sound_update', { 'soundFile': '/static/gentle-gong.mp3' } )

        # push() re-emits pending→todo — JS dedup Set silently drops it
        self.push( job )

        msg = f"New {job.JOB_TYPE} job submitted."
        self._notify( msg, job=job )
        return msg

    def push_job_agentic(
        self,
        routing_command : str,
        args_dict       : Dict,
        websocket_id    : str,
        user_id         : str,
        user_email      : str,
        question        : Optional[ str ] = None,
        scheduled_at    : Optional[ str ] = None,
        monopolize      : bool = False,
    ) -> Dict:
        """
        Submit an agentic job with explicit routing_command + args, bypassing
        the runtime argument expeditor entirely.

        Designed for unattended / service-to-service job submission (E2E test
        harnesses, CLI tools, downstream agents). The caller supplies all
        required args up-front; no interactive Q&A is triggered. If the agent
        constructor rejects the args, the factory returns None and this method
        returns an error result.

        Contrast with `push_job` (the voice/UI /api/push path) which runs the
        expeditor to fill arg gaps interactively.

        Requires:
            - routing_command matches one of the branches in create_agentic_job
            - args_dict is a dict (may be empty; agent constructor validates)
            - websocket_id, user_id, user_email are non-empty strings

        Ensures:
            - Returns dict with "message" (str) and "job_id" (str or None)
            - On success: job is pushed to the todo queue and UI state transitions
              are emitted (pending→todo) with the same flow as _handle_agentic_command
            - On unknown command or construction failure: returns error message
              with job_id=None and emits no state transitions
        """
        agent_entry = JOB_ARG_CONTRACTS.get( routing_command, {} )
        job_prefix  = agent_entry.get( "job_prefix", "aj" )

        # Speculative card for UI consistency with /api/push flow
        spec_id      = f"{job_prefix}-{uuid.uuid4().hex[ :8 ]}"
        spec_id      = self.user_job_tracker.register_scoped_job( spec_id, user_id, websocket_id )
        display_name = agent_entry.get( "display_name", routing_command.replace( "agent router go to ", "" ) )
        display_text = question or routing_command

        spec_metadata = {
            'question_text' : display_text,
            'agent_type'    : display_name,
            'timestamp'     : du.get_current_time(),
            'status'        : 'pending',
            'expediting'    : False,
            'user_email'    : user_email,
        }
        emit_job_state_transition(
            self.websocket_mgr, spec_id, JobState.PENDING, JobState.QUEUED, user_id, spec_metadata
        )

        # Inject system args the factory relies on (mirrors expeditor behavior)
        args_dict = dict( args_dict ) if args_dict else { }
        args_dict.setdefault( "no_confirm", True )

        try:
            job = create_agentic_job(
                command    = routing_command,
                args_dict  = args_dict,
                user_id    = user_id,
                user_email = user_email,
                session_id = websocket_id,
                debug      = self.debug,
                verbose    = self.verbose,
            )
        except Exception as e:
            emit_job_state_transition( self.websocket_mgr, spec_id, JobState.QUEUED, JobState.FAILED, user_id )
            self.user_job_tracker.remove_job( spec_id )
            err = f"Agent construction failed: {type( e ).__name__}: {e}"
            self._notify( err, target_user=user_email )
            return { "message": err, "job_id": None }

        if job is None:
            emit_job_state_transition( self.websocket_mgr, spec_id, JobState.QUEUED, JobState.FAILED, user_id )
            self.user_job_tracker.remove_job( spec_id )
            msg = f"Unknown routing_command: {routing_command!r}"
            self._notify( msg, target_user=user_email )
            return { "message": msg, "job_id": None }

        # Override the job's auto-generated id_hash with the speculative ID so
        # the UI card that was already emitted matches the real job.
        job.id_hash = spec_id

        # Runtime scheduling attributes (CJ Flow timed execution + monopolize)
        if scheduled_at: job.scheduled_at = scheduled_at
        if monopolize:   job.monopolize   = True

        # Ding for new job (same UX as voice path)
        self.websocket_mgr.emit( 'notification_sound_update', { 'soundFile': '/static/gentle-gong.mp3' } )

        self.push( job )

        msg = f"New {job.JOB_TYPE} job submitted via /api/push-agentic (no expeditor)."
        self._notify( msg, job=job )
        return { "message": msg, "job_id": spec_id }

    def push( self, item: Any ) -> None:
        """
        Override parent's push to add producer-consumer coordination and emit pending→todo transition.

        Requires:
            - item must implement QueueableJob protocol

        Ensures:
            - Item is added to queue via parent method
            - Emits pending→todo state transition for UI rendering
            - Consumer thread is notified of new work

        Raises:
            - TypeError if item doesn't implement QueueableJob protocol (via parent)
        """
        # Use condition variable for producer-consumer coordination
        with self.condition:
            # Call parent's push method (includes Protocol validation)
            super().push( item )
            # Notify consumer thread that work is available
            self.condition.notify()

        # Emit pending → todo state transition for UI rendering
        user_id = item.user_id

        metadata = {
            'question_text'    : item.last_question_asked,
            'agent_type'       : item.job_type,
            'timestamp'        : item.created_date,
            'scheduled_at'     : item.scheduled_at,
            'monopolize'       : item.monopolize,
            'paused'           : item.state == JobState.PAUSED,
            'user_email'       : item.user_email,
            'session_id'       : item.session_id,
            'routing_command'  : item.routing_command,
            'original_args'    : item.original_args,
        }
        emit_job_state_transition( self.websocket_mgr, item.id_hash, JobState.PENDING, JobState.QUEUED, user_id, metadata )

        if self.debug:
            print( f"[TODO-QUEUE] Added job, emitted pending→todo, and notified consumer: {item.id_hash}" )

    def delete_by_id_hash( self, id_hash: str ) -> bool:
        """
        Override parent's delete to notify consumer thread when a job is removed.

        When a timed job is deleted while the consumer is sleeping until its
        scheduled_at, the consumer needs to wake up and recalculate its timeout.

        Requires:
            - id_hash is a string

        Ensures:
            - Item is removed via parent method
            - Consumer thread is notified to recalculate eligibility

        Returns:
            - bool: True if item was found and deleted, False otherwise
        """
        with self.condition:
            result = super().delete_by_id_hash( id_hash )
            if result:
                self.condition.notify()  # Wake consumer to recalculate
            return result

def quick_smoke_test():
    """Quick smoke test to validate TodoFifoQueue functionality."""
    import cosa.utils.util as du

    du.print_banner( "TodoFifoQueue Smoke Test", prepend_nl=True )

    # Test salutation parsing functionality
    test_cases = [
        "Good morning, my dearest receptionist. How are you feeling today?",
        "Greetings little buddy! What's your name?",
        "Hello there! Can you help me with my schedule?",
        "What's the weather like today?"  # No salutation case
    ]

    try:
        queue = TodoFifoQueue( None, None, None, debug=True )
        print( "✓ TodoFifoQueue instantiated successfully" )

        # Test 1: Salutation parsing
        print( "\n--- Salutation Parsing Tests ---" )
        for i, input_string in enumerate( test_cases, 1 ):
            print( f"\nTest {i}: '{input_string}'" )
            salutations, question = queue.parse_salutations( input_string )
            print( f"  Salutations: '{salutations}'" )
            print( f"  Question: '{question}'" )

        # Test 2: Mode management
        print( "\n--- Mode Management Tests ---" )
        test_user = "test_user_123"

        # Test get mode (should be None/system by default)
        mode = queue.get_user_mode( test_user )
        assert mode is None, f"Expected None, got {mode}"
        print( f"✓ Default mode is None (system)" )

        # Test set mode
        previous = queue.set_user_mode( test_user, "math" )
        assert previous is None, f"Expected previous=None, got {previous}"
        mode = queue.get_user_mode( test_user )
        assert mode == "math", f"Expected 'math', got {mode}"
        print( f"✓ Set mode to 'math' successfully" )

        # Test change mode
        previous = queue.set_user_mode( test_user, "calendar" )
        assert previous == "math", f"Expected previous='math', got {previous}"
        mode = queue.get_user_mode( test_user )
        assert mode == "calendar", f"Expected 'calendar', got {mode}"
        print( f"✓ Changed mode to 'calendar' successfully" )

        # Test invalid mode
        try:
            queue.set_user_mode( test_user, "invalid_mode" )
            print( "✗ Should have raised ValueError for invalid mode" )
        except ValueError as e:
            print( f"✓ Correctly rejected invalid mode: {e}" )

        # Test clear mode
        previous = queue.clear_user_mode( test_user )
        assert previous == "calendar", f"Expected previous='calendar', got {previous}"
        mode = queue.get_user_mode( test_user )
        assert mode is None, f"Expected None after clear, got {mode}"
        print( f"✓ Cleared mode successfully" )

        # Test get_available_modes
        available = queue.get_available_modes()
        assert len( available ) > 0, "Expected at least one mode"
        assert any( m[ "key" ] == "system" for m in available ), "Expected 'system' in available modes"
        print( f"✓ get_available_modes() returns {len( available )} modes" )
        for m in available:
            print( f"    - {m[ 'key' ]}: {m[ 'display_name' ]}" )

    except Exception as e:
        print( f"✗ Error testing TodoFifoQueue: {e}" )
        import traceback
        traceback.print_exc()

    print( "\n✓ TodoFifoQueue smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()