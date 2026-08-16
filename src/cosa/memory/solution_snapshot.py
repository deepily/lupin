import hashlib
import os
import glob
import json
import copy
import regex as re
from collections import OrderedDict
from typing import Optional, Union, Any

import cosa.utils.util as du
import cosa.utils.util_stopwatch as sw
import cosa.utils.util_code_runner as ucr

from cosa.agents.runnable_code import RunnableCode
from cosa.agents.raw_output_formatter import RawOutputFormatter

import numpy as np
from cosa.memory.embedding_manager import EmbeddingManager
from cosa.memory.embedding_provider import get_embedding_provider
from cosa.memory.normalizer import Normalizer
from cosa.rest.job_state import JobState

class SolutionSnapshot( RunnableCode ):
    """
    Captures and persists a complete solution to a question.
    
    Stores question, code, embeddings, and execution results for
    future reuse and similarity matching.
    """
    @staticmethod
    def get_timestamp( microseconds: bool = False ) -> str:
        """
        Get current timestamp with optional microsecond precision.
        
        Requires:
            - None
            
        Ensures:
            - Returns formatted datetime string
            - Default format: "YYYY-MM-DD @ HH:MM:SS TZ" 
            - Microsecond format: "YYYY-MM-DD @ HH:MM:SS.ffffff TZ"
            
        Args:
            microseconds: If True, include microseconds for unique IDs (default: False)
            
        Raises:
            - None
        """
        if microseconds:
            return du.get_current_datetime( format_str='%Y-%m-%d @ %H:%M:%S.%f %Z' )
        else:
            return du.get_current_datetime()
    
    @staticmethod
    def remove_non_alphanumerics( input: str, replacement_char: str="" ) -> str:
        """
        ╔══════════════════════════════════════════════════════════════════════════════╗
        ║  🔥🔥🔥 DEPRECATED - DO NOT USE THIS FUNCTION! 🔥🔥🔥                         ║
        ║                                                                              ║
        ║  This function DESTROYS mathematical operators (+, -, *, /) and punctuation! ║
        ║  It caused HOURS of debugging pain. Use Normalizer.normalize() instead.      ║
        ║                                                                              ║
        ║  Example of destruction:                                                     ║
        ║    "What's 4 + 4?" → "whats 4 4"  (CORRUPTED!)                              ║
        ║                                                                              ║
        ║  Use instead: cosa.memory.normalizer.Normalizer.normalize()                  ║
        ║  The Normalizer preserves MATH_OPERATORS and expands contractions properly.  ║
        ╚══════════════════════════════════════════════════════════════════════════════╝
        """
        # 🚨🚨🚨 SCREAM DEPRECATION WARNING TO CONSOLE 🚨🚨🚨
        print( "" )
        print( "╔" + "═" * 78 + "╗" )
        print( "║" + " 🔥🔥🔥 DEPRECATED FUNCTION CALLED: remove_non_alphanumerics() 🔥🔥🔥 ".center( 78 ) + "║" )
        print( "║" + "═" * 78 + "║" )
        print( "║" + " WARNING: This function DESTROYS math operators and punctuation!".ljust( 78 ) + "║" )
        print( "║" + f" Input:  '{input[:50]}...'".ljust( 78 ) + "║" ) if len( input ) > 50 else print( "║" + f" Input:  '{input}'".ljust( 78 ) + "║" )
        print( "║" + "".ljust( 78 ) + "║" )
        print( "║" + " USE INSTEAD: cosa.memory.normalizer.Normalizer.normalize()".ljust( 78 ) + "║" )
        print( "║" + "".ljust( 78 ) + "║" )
        print( "║" + " Stack trace to find the caller:".ljust( 78 ) + "║" )
        print( "╚" + "═" * 78 + "╝" )

        import traceback
        traceback.print_stack( limit=5 )

        print( "" )
        print( "🔥" * 40 )
        print( "" )

        # Still execute for backward compatibility, but they'll know it happened!
        regex = re.compile( "[^a-zA-Z0-9 ]" )
        cleaned_output = regex.sub( replacement_char, input ).lower()

        return cleaned_output
    
    @staticmethod
    def escape_single_quotes( input: str ) -> str:
        """
        Remove single quotes from input.
        
        Requires:
            - input is a string
            
        Ensures:
            - Returns string with single quotes removed
            
        Raises:
            - None
        """
        return input.replace( "'", "" )
    
    
    @staticmethod
    def generate_id_hash( push_counter: int, run_date: str ) -> str:
        """
        Generate unique ID hash for snapshot using microsecond-precision timestamp.
        
        Requires:
            - push_counter is an integer (ignored - kept for backward compatibility)
            - run_date is a string with microsecond precision
            
        Ensures:
            - Returns SHA256 hash as hex string
            - Uses only run_date for uniqueness (microsecond precision eliminates collisions)
            - Maintains API compatibility with existing code
            
        Raises:
            - None
        """
        # Use only timestamp for uniqueness - microsecond precision eliminates collisions
        # push_counter parameter kept for backward compatibility but ignored
        return hashlib.sha256( run_date.encode() ).hexdigest()
    
    @staticmethod
    def get_default_stats_dict() -> dict:
        """
        Get default runtime statistics dictionary.
        
        Requires:
            - None
            
        Ensures:
            - Returns dict with all required stats fields
            - Initial values set appropriately
            
        Raises:
            - None
        """
        return {
           "first_run_ms": 0,
            "run_count"  : -1,
            "total_ms"   : 0,
            "mean_run_ms": 0,
            "last_run_ms": 0,
          "time_saved_ms": 0
        }
    
    @staticmethod
    def get_embedding_similarity( this_embedding: list[float], that_embedding: list[float] ) -> float:
        """
        Calculate similarity between two embeddings.
        
        Requires:
            - Both embeddings are lists of floats
            - Both embeddings have same length
            
        Ensures:
            - Returns similarity score as percentage (0-100)
            - Uses dot product calculation
            
        Raises:
            - None
        """
        return np.dot( this_embedding, that_embedding ) * 100
    
    def __init__( self, push_counter: int=-1, question: str="", question_normalized: str="", question_gist: str="", synonymous_questions: OrderedDict=OrderedDict(), synonymous_question_gists: OrderedDict=OrderedDict(), non_synonymous_questions: list=[],
                  last_question_asked: str="", answer: str="", answer_conversational: str="", error: str="", routing_command: str="", agent_class_name: Optional[str]=None,
                  created_date: str=None, updated_date: str=None, run_date: str=None,
                  runtime_stats: dict=get_default_stats_dict(),
                  id_hash: str="", solution_summary: str="", code: list[str]=[], solution_summary_gist: str="", code_returns: str="", code_example: str="", code_type: str="raw", thoughts: str="",
                  programming_language: str="Python", language_version: str="3.10",
                  question_embedding: list[float]=[ ], question_normalized_embedding: list[float]=[ ], question_gist_embedding: list[float]=[ ], solution_embedding: list[float]=[ ], code_embedding: list[float]=[ ], thoughts_embedding: list[float]=[ ], solution_gist_embedding: list[float]=[ ],
                  solution_directory: str="/src/conf/long-term-memory/solutions/", solution_file: Optional[str]=None, user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="",
                  replay_history: list=None, replay_stats: dict=None, is_cache_hit: bool=False,
                  answer_is_correct: bool=None,
                  debug: bool=False, verbose: bool=False
                  ) -> None:
        """
        Initialize a solution snapshot.
        
        Requires:
            - All string parameters are strings or empty
            - All list parameters are lists or empty
            - Embeddings are lists of floats when provided
            - user_id must be a valid system ID
            
        Ensures:
            - Initializes all fields with provided or default values
            - Generates missing embeddings if content provided
            - Creates unique ID hash if not provided
            - Writes to file if embeddings were generated
            - user_id is stored for ownership tracking but excluded from serialization
            - user_email is stored for TTS notification routing but excluded from serialization

        Raises:
            - None (handles errors internally)
        """
        
        super().__init__( debug=debug, verbose=verbose )

        # Initialize embedding provider (routes to OpenAI or local GPU engines)
        self._embedding_mgr = EmbeddingManager( debug=debug, verbose=verbose )
        self._embedding_provider = get_embedding_provider( debug=debug, verbose=verbose )

        # Initialize normalizer for consistent question normalization
        from cosa.memory.normalizer import Normalizer
        self._normalizer = Normalizer()

        # track updates to internal state as the object is instantiated
        dirty                      = False

        self.push_counter          = push_counter
        # Store verbatim question (don't normalize - that destroys original operators like +, -, etc.)
        self.question              = question if question else ""
        # Populate normalized version (with operators preserved via MATH_OPERATORS in Normalizer)
        self.question_normalized   = question_normalized if question_normalized else (
            self._normalizer.normalize( question ) if question else ""
        )
        self.question_gist         = question_gist
        self.thoughts              = thoughts
        
        self.answer                = answer
        self.answer_conversational = answer_conversational
        self.error                 = error
        self.routing_command       = routing_command
        self.original_args         = None  # CJ Flow persistence field — snapshots replay prior runs, no args needed
        self.agent_class_name      = agent_class_name  # e.g., "MathAgent", "CalendarAgent", etc.
        self.user_id               = user_id
        self.user_email            = user_email  # Email for TTS notification routing
        self.session_id            = session_id  # WebSocket session ID for job-notification correlation

        # Replay tracking for Time Saved Dashboard analytics
        self.replay_history        = replay_history if replay_history is not None else []
        self.replay_stats          = replay_stats if replay_stats is not None else {
            "total_replays"       : 0,
            "total_time_saved_ms" : 0,
            "unique_users"        : [],           # List of user_ids who replayed
            "first_replayed"      : None,
            "last_replayed"       : None
        }
        self.is_cache_hit          = is_cache_hit
        self.answer_is_correct     = answer_is_correct

        # QueueableJob protocol compliance - status tracking attributes
        self.state                 = JobState.PENDING
        # None, not "" — see agent_base.py and row 4a9ebc4b.
        self.started_at            = None
        self.completed_at          = None

        # Scheduling attributes (CJ Flow) — snapshots are always immediate, never monopolize/pause
        self.scheduled_at          = None
        self.monopolize            = False

        # Is there is no synonymous questions to be found then just recycle the current question
        # Handle corrupted data: ensure synonymous_questions is a valid dict/OrderedDict
        if not isinstance( synonymous_questions, dict ):
            if self.debug: print( f"WARNING: synonymous_questions is invalid type {type(synonymous_questions)}, defaulting to empty OrderedDict" )
            synonymous_questions = OrderedDict()
            
        if len( synonymous_questions ) == 0:
            synonymous_questions[ question ] = 100.0
            self.synonymous_questions = synonymous_questions
        else:
            self.synonymous_questions = synonymous_questions
            
        # Is there is no synonymous gists to be found then just recycle the current gist
        # Handle corrupted data: ensure synonymous_question_gists is a valid dict/OrderedDict
        if not isinstance( synonymous_question_gists, dict ):
            if self.debug: print( f"WARNING: synonymous_question_gists is invalid type {type(synonymous_question_gists)}, defaulting to empty OrderedDict" )
            synonymous_question_gists = OrderedDict()
            
        if len( synonymous_question_gists ) == 0:
            synonymous_question_gists[ question_gist ] = 100.0
            self.synonymous_question_gists = synonymous_question_gists
        else:
            self.synonymous_question_gists = synonymous_question_gists
            
        self.non_synonymous_questions = non_synonymous_questions
            
        self.last_question_asked   = last_question_asked
        
        self.solution_summary      = solution_summary

        self.code                  = code
        self.solution_summary_gist = solution_summary_gist  # Gist of solution_summary (generated after first successful execution)
        self.code_returns          = code_returns
        self.code_example          = code_example
        self.code_type             = code_type
        
        # metadata surrounding the question and the solution
        # NOTE: These timestamps use None defaults to avoid Python's mutable default argument bug
        # where get_timestamp() would be evaluated ONCE at module load time, causing all snapshots
        # to share the same timestamp and generate identical id_hash values (collision bug).
        self.updated_date          = updated_date if updated_date else self.get_timestamp()
        self.created_date          = created_date if created_date else self.get_timestamp()
        self.run_date              = run_date if run_date else self.get_timestamp( microseconds=True )
        self.runtime_stats         = runtime_stats
        
        if id_hash == "":
            self.id_hash           = SolutionSnapshot.generate_id_hash( self.push_counter, self.run_date )
        else:
            self.id_hash           = id_hash
        self.programming_language  = programming_language
        self.language_version      = language_version
        self.solution_directory    = solution_directory
        self.solution_file         = solution_file
        
        # If the question embedding is empty, generate it
        if question != "" and not question_embedding:
            self.question_embedding = self._embedding_provider.generate_embedding( question, content_type="prose" )
            dirty = True
        else:
            self.question_embedding = question_embedding

        # If the normalized embedding is empty, generate it
        if question_normalized != "" and not question_normalized_embedding:
            self.question_normalized_embedding = self._embedding_provider.generate_embedding( question_normalized, content_type="prose" )
            dirty = True
        else:
            self.question_normalized_embedding = question_normalized_embedding

        # Gist embedding generation removed (dead code — gist text still used for L3 matching)
        self.question_gist_embedding = question_gist_embedding if question_gist_embedding else []

        # If the code embedding is empty, generate it
        if len( code ) > 0 and not code_embedding:
            self.code_embedding = self._embedding_provider.generate_embedding( " ".join( code ), content_type="code" )
            dirty = True
        else:
            self.code_embedding = code_embedding

        # If the solution embedding is empty, generate it
        if solution_summary and not solution_embedding:
            self.solution_embedding = self._embedding_provider.generate_embedding( solution_summary, content_type="prose" )
            dirty = True
        else:
            self.solution_embedding = solution_embedding

        # If the thoughts embedding is empty, generate it
        if thoughts and not thoughts_embedding:
            self.thoughts_embedding = self._embedding_provider.generate_embedding( thoughts, content_type="prose" )
            dirty = True
        else:
            self.thoughts_embedding = thoughts_embedding

        # Solution gist embedding generation removed (dead code — gist text still used for display)
        self.solution_gist_embedding = solution_gist_embedding if solution_gist_embedding else []

        # Note: Auto-save removed - serialization is now handled by managers
        # If embeddings were generated during loading, they will be persisted
        # when the manager calls add_snapshot() or equivalent method
        
    @classmethod
    def from_json_file( cls, filename: str, debug: bool=False ) -> 'SolutionSnapshot':
        """
        DEPRECATED: Load snapshot from JSON file.

        This method is deprecated as of 2025.09.17. Deserialization should be handled
        by the manager, not the snapshot object.

        Use: manager.get_snapshots_by_question() or similar manager methods instead.

        Load snapshot from JSON file.
        
        Requires:
            - filename is a valid file path
            - File contains valid JSON data
            
        Ensures:
            - Returns new SolutionSnapshot instance
            - All fields populated from JSON data
            
        Raises:
            - FileNotFoundError if file doesn't exist
            - JSONDecodeError if invalid JSON
        """
        import warnings
        warnings.warn(
            "from_json_file() is deprecated. Use manager methods for loading snapshots.",
            DeprecationWarning,
            stacklevel=2
        )

        if debug: print( f"Reading {filename}..." )
        with open( filename, "r" ) as f:
            data = json.load( f )

        return cls( **data )
    
    @classmethod
    def create( cls, agent: Any ) -> 'SolutionSnapshot':
        """
        Create snapshot from agent instance.

        Requires:
            - agent has required attributes (question, code, etc.)
            - agent.prompt_response_dict is populated

        Ensures:
            - Returns new SolutionSnapshot with agent data
            - Copies all relevant fields from agent
            - Populates all three question representations (verbatim, normalized, gist)
            - Preserves agent's id_hash if available (for user job tracking)

        Raises:
            - AttributeError if agent missing required fields
        """
        print( "(create_solution_snapshot) TODO: Reconcile how we're going to get a dynamic path to the solution file's directory" )

        # Get normalizer to create normalized representation
        from cosa.memory.normalizer import Normalizer
        normalizer = Normalizer()

        # Extract all three question representations
        verbatim_question = agent.last_question_asked  # Original user input
        normalized_question = normalizer.normalize( verbatim_question )  # Normalized with operators preserved

        # Capture the agent's class name for formatting logic preservation
        agent_class_name = type( agent ).__name__  # e.g., "MathAgent", "CalendarAgent", etc.

        # Preserve agent's id_hash if available (maintains user job tracking association)
        agent_id_hash = getattr( agent, 'id_hash', '' )

        # Instantiate a new SolutionSnapshot object using the contents of the calendaring or function mapping agent
        return SolutionSnapshot(
                          id_hash=agent_id_hash,
                         question=verbatim_question,
               question_normalized=normalized_question,
                    question_gist=agent.question_gist,
              last_question_asked=agent.last_question_asked,
                  routing_command=agent.routing_command,
               agent_class_name=agent_class_name,  # NEW: Preserve agent type for formatting
             synonymous_questions=OrderedDict( { agent.question: 100.0 } ),
        synonymous_question_gists=OrderedDict( { agent.question_gist: 100.0 } ),
                            error=agent.prompt_response_dict.get( "error", "" ),
                 solution_summary=agent.prompt_response_dict.get( "explanation", "N/A" ),
                             code=agent.prompt_response_dict.get( "code", [ "" ] ),
                     code_returns=agent.prompt_response_dict.get( "returns", "N/A" ),
                     code_example=agent.prompt_response_dict.get( "example", "N/A" ),
                         thoughts=agent.prompt_response_dict.get( "thoughts", "N/A" ),
                           answer=str( agent.code_response_dict.get( "output", "N/A" ) ),
            answer_conversational=agent.answer_conversational,
            # User context pass-through from agent (AgentBase guarantees these attributes)
                          user_id=agent.user_id,
                       user_email=agent.user_email,
                       session_id=agent.session_id

               # TODO: Reconcile how we're going to get a dynamic path to the solution file's directory
               # solution_directory=calendaring_agent.solution_directory
        )
    
    def add_synonymous_question( self, question: str, salutation: str="", score: float=100.0 ) -> None:
        """
        Add a synonymous question to the snapshot.

        Requires:
            - question is a non-empty string
            - score is between 0 and 100

        Ensures:
            - Adds question to synonymous_questions if not present
            - Updates last_question_asked with full text
            - Updates timestamp if question added

        Raises:
            - None
        """
        # We're doing a mechanical peel off of the salutation before it even gets here, and adding it back in for conversationality sake here
        # Also: Add last question in unmodified form before cleaning it
        if len( salutation ) > 0:
            self.last_question_asked = salutation + " " + question
        else:
            self.last_question_asked = question

        # Store verbatim question - normalization causes signal loss
        if question not in self.synonymous_questions:
            self.synonymous_questions[ self.last_question_asked ] = score
            self.updated_date = self.get_timestamp()
        else:
            print( f"Question [{self.last_question_asked}] is already listed as a synonymous question." )
        
    def get_last_synonymous_question( self ) -> str:
        """
        Get the most recently added synonymous question.
        
        Requires:
            - synonymous_questions is not empty
            
        Ensures:
            - Returns last question in ordered dict
            
        Raises:
            - IndexError if no synonymous questions
        """
        return list( self.synonymous_questions.keys() )[ -1 ]
        
    def complete( self, answer: str, code: list[str]=[ ], solution_summary: str="" ) -> None:
        """
        Complete the snapshot with execution results.
        
        Requires:
            - answer is a string
            - code is a list of strings
            - solution_summary is a string
            
        Ensures:
            - Sets answer, code, and solution summary
            - Generates embeddings for code and summary
            
        Raises:
            - None
        """
        self.answer = answer
        self.set_code( code )
        self.set_solution_summary( solution_summary )
        # self.completion_date  = SolutionSnapshot.get_current_datetime()
        
    def set_solution_summary( self, solution_summary: str ) -> None:
        """
        Set solution summary and generate embedding.
        
        Requires:
            - solution_summary is a string
            
        Ensures:
            - Updates solution_summary field
            - Generates new embedding
            - Updates timestamp
            
        Raises:
            - None
        """
        self.solution_summary = solution_summary
        self.solution_embedding = self._embedding_provider.generate_embedding( solution_summary, content_type="prose" )
        self.updated_date = self.get_timestamp()

    def set_code( self, code: list[str] ) -> None:
        """
        Set code and generate embedding.
        
        Requires:
            - code is a list of strings
            
        Ensures:
            - Updates code field
            - Generates embedding from joined code
            - Updates timestamp
            
        Raises:
            - None
        """
        # ¡OJO! code is a list of strings, not a string!
        self.code           = code
        self.code_embedding = self._embedding_provider.generate_embedding( " ".join( code ), content_type="code" )
        self.updated_date   = self.get_timestamp()

    def get_question_similarity( self, other_snapshot: 'SolutionSnapshot' ) -> float:
        """
        Calculate question similarity with another snapshot.
        
        Requires:
            - Both snapshots have question embeddings
            
        Ensures:
            - Returns similarity score as percentage (0-100)
            - Uses dot product calculation
            
        Raises:
            - ValueError if either embedding is missing
        """
        if not self.question_embedding or not other_snapshot.question_embedding:
            raise ValueError( "Both snapshots must have a question embedding to compare." )
        return np.dot( self.question_embedding, other_snapshot.question_embedding ) * 100
    
    def get_solution_summary_similarity( self, other_snapshot: 'SolutionSnapshot' ) -> float:
        """
        Calculate solution summary similarity with another snapshot.
        
        Requires:
            - Both snapshots have solution embeddings
            
        Ensures:
            - Returns similarity score as percentage (0-100)
            - Uses dot product calculation
            
        Raises:
            - ValueError if either embedding is missing
        """
        if not self.solution_embedding or not other_snapshot.solution_embedding:
            raise ValueError( "Both snapshots must have a solution summary embedding to compare." )
        
        return np.dot( self.solution_embedding, other_snapshot.solution_embedding ) * 100
    
    def get_code_similarity( self, other_snapshot: 'SolutionSnapshot' ) -> float:
        """
        Calculate code similarity with another snapshot.
        
        Requires:
            - Both snapshots have code embeddings
            
        Ensures:
            - Returns similarity score as percentage (0-100)
            - Uses dot product calculation
            
        Raises:
            - ValueError if either embedding is missing
        """
        if not self.code_embedding or not other_snapshot.code_embedding:
            raise ValueError( "Both snapshots must have a code embedding to compare." )
        
        return np.dot( self.code_embedding, other_snapshot.code_embedding ) * 100
    
    def to_jsons( self, verbose: bool=True ) -> str:
        """
        DEPRECATED: Serialize snapshot to JSON string.

        This method is deprecated as of 2025.09.17. Serialization should be handled
        by the manager, not the snapshot object.
        """
        import warnings
        warnings.warn(
            "to_jsons() is deprecated. Serialization should be handled by managers.",
            DeprecationWarning,
            stacklevel=2
        )

        # Original method logic continues (keeping functionality for now)
        # TODO: decide what we're going to exclude from serialization, and why or why not!
        # Right now I'm just doing this for the sake of expediency as I'm playing with class inheritance for agents
        fields_to_exclude = [ "prompt_response", "prompt_response_dict", "code_response_dict", "phind_tgi_url", "config_mgr", "_embedding_mgr", "_embedding_provider", "_normalizer", "websocket_id", "user_id", "user_email" ]
        data = { field: value for field, value in self.__dict__.items() if field not in fields_to_exclude }
        return json.dumps( data )
        
    def get_copy( self, user_email: str = "" ) -> 'SolutionSnapshot':
        """
        Create a copy of this snapshot for queue execution.

        Note: user_email is passed here (not in constructor) because snapshots
        are loaded from storage without user context. The requesting user's
        email is injected at copy time for TTS notification routing.

        Requires:
            - None

        Ensures:
            - Returns new instance with same values
            - Shallow copy (references shared)
            - user_email is set on copy if provided

        Raises:
            - None
        """
        snapshot_copy = copy.copy( self )
        if user_email:
            snapshot_copy.user_email = user_email
        return snapshot_copy
    
    def write_current_state_to_file( self ) -> None:
        """
        DEPRECATED: Write snapshot to JSON file.

        This method is deprecated as of 2025.09.17. Serialization should be handled
        by the manager, not the snapshot object.

        Use: manager.add_snapshot(snapshot) instead.

        Requires:
            - solution_directory is valid path
            - All required fields populated

        Ensures:
            - Creates JSON file with snapshot data
            - Generates unique filename if needed
            - Sets file permissions to 0o666

        Raises:
            - OSError if file operations fail
        """
        import warnings
        warnings.warn(
            "write_current_state_to_file() is deprecated. Use manager.add_snapshot() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        # Get the project root directory
        project_root = du.get_project_root()
        # Define the directory where the file will be saved
        directory = f"{project_root}{self.solution_directory}"
        
        if self.solution_file is None:
            
            print( "NO solution_file value provided (Must be a new object). Generating a unique file name..." )
            # Generate filename based on the first 64 characters of the question
            # filename_base = du.truncate_string( self.question, max_len=64 ).replace( " ", "-" )
            filename_base = du.truncate_string( self.remove_non_alphanumerics( self.question, replacement_char="_" ), max_len=64 ).replace( " ", "-" )
            # Get a list of all files that start with the filename base
            existing_files = glob.glob( f"{directory}{filename_base}-*.json" )
            # The count of existing files will be used to make the filename unique
            file_count = len( existing_files )
            # generate the file name
            filename = f"{filename_base}-{file_count}.json"
            self.solution_file = filename
        
        else:
            
            print( f"solution_file value provided: [{self.solution_file}]..." )
        
        # Generate the full file path
        file_path = f"{directory}{self.solution_file}"
        # Print the file path for debugging purposes
        print( f"File path: {file_path}", end="\n\n" )
        # Write the JSON string to the file
        with open( file_path, "w" ) as f:
            f.write( self.to_jsons() )
        
        # Set the file permissions to world-readable and writable
        os.chmod( file_path, 0o666 )
        
    def delete_file( self ) -> None:
        """
        DEPRECATED: Delete snapshot file from filesystem.

        This method is deprecated as of 2025.09.17. File management should be handled
        by the manager, not the snapshot object.

        Use: manager.delete_snapshot(question, delete_physical=True) instead.

        Requires:
            - solution_file and solution_directory are set

        Ensures:
            - Removes file if it exists
            - Prints status message

        Raises:
            - None (handles errors internally)
        """
        import warnings
        warnings.warn(
            "delete_file() is deprecated. Use manager.delete_snapshot() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        file_path = f"{du.get_project_root()}{self.solution_directory}{self.solution_file}"
        
        if os.path.isfile( file_path ):
            os.remove( file_path )
            print( f"Deleted file [{file_path}]" )
        else:
            print( f"File [{file_path}] does not exist" )
            
    def update_runtime_stats( self, timer ) -> None:
        """
        Updates the runtime stats for this object

        Uses the timer object to calculate the delta between now and when this object was instantiated

        :return: None
        """
        delta_ms = timer.get_delta_ms()

        # We're now tracking the first time which is expensive to calculate, after that we're tracking all subsequent cashed runs
        if self.runtime_stats[ "run_count" ] == -1:
            self.runtime_stats[ "first_run_ms"  ]  = delta_ms
            self.runtime_stats[ "run_count"     ]  = 0
        else:
            self.runtime_stats[ "run_count"     ] += 1
            self.runtime_stats[ "total_ms"      ] += delta_ms
            self.runtime_stats[ "mean_run_ms"   ]  = int( self.runtime_stats[ "total_ms" ] / self.runtime_stats[ "run_count" ] )
            self.runtime_stats[ "last_run_ms"   ]  = delta_ms
            self.runtime_stats[ "time_saved_ms" ]  = ( self.runtime_stats[ "first_run_ms" ] * self.runtime_stats[ "run_count" ] ) - self.runtime_stats[ "total_ms" ]

    def record_replay( self, user_id: str, session_id: str, time_saved_ms: int, max_history: int = 100 ) -> None:
        """
        Record a replay event for analytics tracking.

        Requires:
            - user_id is a non-empty string
            - session_id is a non-empty string
            - time_saved_ms is a non-negative integer

        Ensures:
            - Adds entry to replay_history (bounded by max_history)
            - Updates aggregate replay_stats
            - Tracks unique users without duplicates
        """
        timestamp = self.get_timestamp()

        entry = {
            "user_id"       : user_id,
            "session_id"    : session_id,
            "timestamp"     : timestamp,
            "time_saved_ms" : time_saved_ms
        }

        # Update aggregates (permanent)
        self.replay_stats[ "total_replays" ] += 1
        self.replay_stats[ "total_time_saved_ms" ] += time_saved_ms
        self.replay_stats[ "last_replayed" ] = timestamp

        if not self.replay_stats[ "first_replayed" ]:
            self.replay_stats[ "first_replayed" ] = timestamp

        if user_id not in self.replay_stats[ "unique_users" ]:
            self.replay_stats[ "unique_users" ].append( user_id )

        # Update rolling history (bounded)
        self.replay_history.append( entry )
        if len( self.replay_history ) > max_history:
            self.replay_history.pop( 0 )  # Remove oldest

    def for_current_user( self, user_id: str, session_id: str ) -> 'SolutionSnapshot':
        """
        Create a shallow copy with current user context for done queue display.

        Requires:
            - user_id is the current requesting user's ID
            - session_id is the current WebSocket session

        Ensures:
            - Returns a copy with updated user_id, session_id, run_date
            - Original snapshot remains unchanged
            - Copy is suitable for done queue filtering
        """
        # Shallow copy - embeddings and large fields are shared (memory efficient)
        user_copy = copy.copy( self )

        # Override user context
        user_copy.user_id    = user_id
        user_copy.session_id = session_id
        user_copy.run_date   = self.get_timestamp()

        # Mark as cache hit for UI display
        user_copy.is_cache_hit = True

        return user_copy

    def run_code( self, debug: bool=False, verbose: bool=False ) -> dict:
        """
        Execute stored code, OR replay a codeless agent's cached answer.

        Most agents (MathAgent, CrudForDataFramesAgent, etc.) generate Python at
        first-run time and save it on the snapshot's `code` field; replay then
        re-executes that code. CalculatorAgent and similar deterministic-dispatch
        agents have no Python to save — their `run_code()` dispatches a parsed
        intent struct to pure-Python helpers — so their snapshots persist with
        `code = ['']` BY DESIGN. On replay, those snapshots' answers come from
        the cached `self.answer` field, not from re-execution.

        2026-04-28 fix: prior to this, replay of a codeless-agent snapshot raised
        ValueError on the empty-code guard, which the consumer thread caught and
        dead-lettered. The fix mirrors the existing CalculatorAgent special-case
        in run_formatter() (lines 943-953 of this file).

        Requires:
            - code, code_example, code_returns are populated for code-generating agents
            - For codeless agents (CalculatorAgent): answer is populated
            - routing_command determines data file path

        Ensures:
            - For codeless agents: returns synthesized code_response_dict from cached answer
            - For code-generating agents: executes code via code runner, updates answer
            - Returns code response dictionary

        Raises:
            - ValueError if both code and answer are empty (truly broken snapshot)
            - Code execution errors propagated for code-generating agents
        """
        # Codeless agent replay: CalculatorAgent (and any future deterministic-dispatch
        # agent) saves snapshots with empty code by design — its answer was computed by
        # pure-Python helpers, not Python source we can re-run. Short-circuit to return
        # the cached answer in the code_response_dict shape that downstream code expects.
        if self.agent_class_name == "CalculatorAgent":
            if self.answer:
                self.code_response_dict = { "return_code": 0, "output": self.answer }
                return self.code_response_dict
            # CalculatorAgent snapshot with neither code nor answer: data corruption.
            raise ValueError(
                f"CalculatorAgent snapshot has no answer — corrupted snapshot: "
                f"id_hash={getattr( self, 'id_hash', '?' )}"
            )

        # Guard: Reject empty code lists — nothing to execute (and not a known codeless agent)
        if not self.code or all( line.strip() == "" for line in self.code ):
            raise ValueError( "Cannot execute empty code list — snapshot has no executable code" )

        if self.routing_command == "agent router go to todo list":
            path_to_df = "/src/conf/long-term-memory/todo.csv"
        elif self.routing_command == "agent router go to calendar":
            path_to_df = "/src/conf/long-term-memory/events.csv"
        else:
            path_to_df = None
            
        self.code_response_dict = ucr.assemble_and_run_solution(
            self.code, self.code_example, solution_code_returns=self.code_returns, path_to_df=path_to_df, debug=debug
        )
        self.answer             = self.code_response_dict[ "output" ]
        
        if debug and verbose:
            du.print_banner( "Code output", prepend_nl=True )
            for line in self.code_response_dict[ "output" ].split( "\n" ):
                print( line )
        
        return self.code_response_dict
    
    def run_formatter( self ) -> str:
        """
        Format raw output using the same logic as the original agent.

        This method preserves agent-specific formatting behavior during replay.
        For example, MathAgent's terse mode skips LLM formatting to prevent
        hallucination of mathematical facts.

        Requires:
            - last_question_asked, answer, routing_command are set
            - agent_class_name may be set (for agent-specific formatting)

        Ensures:
            - Uses agent-specific formatting logic if agent_class_name is set
            - Falls back to default LLM formatter if not set or on error
            - Returns formatted conversational answer
            - Updates self.answer_conversational

        Raises:
            - None (handles errors gracefully with fallback)
        """

        # Try agent-specific formatting if we know the agent type
        if self.agent_class_name == "MathAgent":
            try:
                # Import MathAgent to use its formatting logic
                from cosa.agents.math_agent import MathAgent
                from cosa.config.configuration_manager import ConfigurationManager

                # Create config manager to check terse flag
                config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

                # Use MathAgent's formatting logic (checks terse flag)
                formatted = MathAgent.apply_formatting(
                    self.answer,  # Raw output like "4" or "99"
                    config_mgr,
                    self.debug,
                    self.verbose
                )

                if formatted is not None:
                    # Terse mode: Use raw output directly, skip LLM formatting
                    self.answer_conversational = formatted
                    if self.debug and self.verbose:
                        print( f"SolutionSnapshot: Used MathAgent terse formatting. Result: [{self.answer_conversational}]" )
                    return self.answer_conversational

                # Verbose mode: Fall through to default LLM formatter
                if self.debug and self.verbose:
                    print( "SolutionSnapshot: MathAgent signaled to use default LLM formatter." )

            except Exception as e:
                if self.debug:
                    print( f"⚠ Failed to apply MathAgent formatting: {e}" )
                    print( "  Falling back to default LLM formatter" )

        # CalculatorAgent: already formatted during agent pipeline — no LLM reformatting needed
        if self.agent_class_name == "CalculatorAgent":
            if self.answer_conversational:
                if self.debug and self.verbose:
                    print( f"SolutionSnapshot: CalculatorAgent already formatted. Result: [{self.answer_conversational}]" )
                return self.answer_conversational
            # Fallback: return raw answer if conversational not set
            if self.debug:
                print( "SolutionSnapshot: CalculatorAgent has no answer_conversational, using raw answer" )
            self.answer_conversational = self.answer if self.answer else "N/A"
            return self.answer_conversational

        # Default LLM formatter (for unknown agents, non-terse mode, or errors)
        formatter = RawOutputFormatter(
            self.last_question_asked,
            self.answer,
            self.routing_command,
            debug=self.debug,
            verbose=self.verbose
        )
        self.answer_conversational = formatter.run_formatter()  # Already returns extracted string via Pydantic XML parsing

        if self.debug and self.verbose:
            print( f"SolutionSnapshot: Used default LLM formatter. Result: [{self.answer_conversational}]" )

        return self.answer_conversational
    
    def formatter_ran_to_completion( self ) -> bool:
        """
        Check if formatter completed successfully.

        Requires:
            - None

        Ensures:
            - Returns True if answer_conversational is set
            - Returns False otherwise

        Raises:
            - None
        """
        return self.answer_conversational is not None

    def do_all( self ) -> str:
        """
        Execute snapshot code and format result.

        This is required by QueueableJob protocol. For snapshots,
        it runs the cached code and formats the output.

        Requires:
            - code, code_example, code_returns are populated

        Ensures:
            - Executes stored code
            - Formats output
            - Returns conversational answer

        Raises:
            - Code execution errors propagated
        """
        self.run_code( debug=self.debug, verbose=self.verbose )
        self.run_formatter()
        return self.answer_conversational

    # =========================================================================
    # Unified Interface Properties (for QueueableJob protocol compatibility)
    # =========================================================================

    @property
    def job_type( self ) -> str:
        """
        Unified job type identifier.

        Maps to agent_class_name for SolutionSnapshots, providing consistent
        type identification across all job types (AgentBase, SolutionSnapshot,
        AgenticJobBase).

        Returns:
            str: Agent class name (e.g., "MathAgent", "CalendarAgent") or "unknown"
        """
        return self.agent_class_name or "unknown"

def quick_smoke_test():
    """Quick smoke test to validate SolutionSnapshot functionality."""
    du.print_banner( "SolutionSnapshot Smoke Test", prepend_nl=True )
    
    # Test embedding generation
    print( "Testing embedding generation..." )
    embedding_mgr = EmbeddingManager( debug=True )
    embedding = embedding_mgr.generate_embedding( "what time is it", normalize_for_cache=True )
    if embedding:
        print( f"✓ Generated embedding with {len( embedding )} dimensions" )
    else:
        print( "✗ Failed to generate embedding" )
    
    # Test basic snapshot creation
    print( "\nTesting snapshot creation..." )
    today = SolutionSnapshot( question="what day is today" )
    print( f"✓ Created snapshot with ID: {today.id_hash}" )
    
    # Test similarity scoring between snapshots
    print( "\nTesting similarity scoring..." )
    tomorrow = SolutionSnapshot( question="what day is tomorrow" )
    blah = SolutionSnapshot( question="i feel so blah today" )
    
    snapshots = [ today, tomorrow, blah ]
    
    for snapshot in snapshots:
        if today.question_embedding and snapshot.question_embedding:
            score = today.get_question_similarity( snapshot )
            print( f"Score: [{score:.1f}] for '{snapshot.question}' vs '{today.question}'" )

    # Test unified interface property: job_type
    print( "\nTesting unified interface property: job_type..." )
    snapshot_with_agent = SolutionSnapshot( question="test", agent_class_name="MathAgent" )
    assert snapshot_with_agent.job_type == "MathAgent", "job_type should equal agent_class_name"
    print( f"✓ job_type with agent_class_name: {snapshot_with_agent.job_type}" )

    snapshot_without_agent = SolutionSnapshot( question="test" )
    assert snapshot_without_agent.job_type == "unknown", "job_type should be 'unknown' when agent_class_name is None"
    print( f"✓ job_type without agent_class_name: {snapshot_without_agent.job_type}" )

    # Test do_all() method exists (QueueableJob protocol requirement)
    print( "\nTesting do_all() method (QueueableJob protocol)..." )
    assert hasattr( snapshot_with_agent, 'do_all' ), "SolutionSnapshot must have do_all() method"
    assert callable( snapshot_with_agent.do_all ), "do_all must be callable"
    print( "✓ do_all() method exists and is callable" )

    # Test QueueableJob protocol compliance
    print( "\nTesting QueueableJob protocol compliance..." )
    try:
        from cosa.rest.queue_protocol import is_queueable_job
        test_snapshot = SolutionSnapshot(
            question="test question",
            agent_class_name="TestAgent",
            user_id="test_user",
            user_email="test@example.com",
            session_id="test_session"
        )
        # Protocol requires all these attributes
        assert hasattr( test_snapshot, 'id_hash' ), "Missing id_hash"
        assert hasattr( test_snapshot, 'push_counter' ), "Missing push_counter"
        assert hasattr( test_snapshot, 'user_id' ), "Missing user_id"
        assert hasattr( test_snapshot, 'user_email' ), "Missing user_email"
        assert hasattr( test_snapshot, 'session_id' ), "Missing session_id"
        assert hasattr( test_snapshot, 'status' ), "Missing status"
        assert hasattr( test_snapshot, 'do_all' ), "Missing do_all method"
        assert hasattr( test_snapshot, 'code_ran_to_completion' ), "Missing code_ran_to_completion method"
        assert hasattr( test_snapshot, 'formatter_ran_to_completion' ), "Missing formatter_ran_to_completion method"

        is_valid = is_queueable_job( test_snapshot )
        print( f"✓ QueueableJob protocol check: {is_valid}" )
    except ImportError:
        print( "⚠ Could not import queue_protocol for protocol check (skipped)" )

    # Test answer_is_correct tri-state field
    print( "\nTesting answer_is_correct tri-state field..." )
    snap_none  = SolutionSnapshot( question="test", answer_is_correct=None )
    snap_true  = SolutionSnapshot( question="test", answer_is_correct=True )
    snap_false = SolutionSnapshot( question="test", answer_is_correct=False )
    assert snap_none.answer_is_correct is None, "Default should be None"
    assert snap_true.answer_is_correct is True, "Should accept True"
    assert snap_false.answer_is_correct is False, "Should accept False"
    print( f"✓ answer_is_correct: None={snap_none.answer_is_correct}, True={snap_true.answer_is_correct}, False={snap_false.answer_is_correct}" )

    # Verify for_current_user preserves answer_is_correct
    snap_verified = SolutionSnapshot( question="test", answer_is_correct=True )
    user_copy = snap_verified.for_current_user( user_id="other_user", session_id="other_session" )
    assert user_copy.answer_is_correct is True, "for_current_user should preserve answer_is_correct"
    print( "✓ for_current_user preserves answer_is_correct" )

    print( "\n✓ SolutionSnapshot smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
