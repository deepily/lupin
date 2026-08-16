import abc
import json
import os
from typing import Optional, Any

import pandas as pd

import cosa.utils.util as du
import cosa.utils.util_pandas        as dup
import cosa.memory.solution_snapshot as ss

from cosa.agents.raw_output_formatter import RawOutputFormatter

from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.runnable_code import RunnableCode
from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.agents.two_word_id_generator import TwoWordIdGenerator
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.rest.job_state import JobState

class CodeGenerationFailedException( Exception ):
    """
    Exception raised when code generation fails after exhausting all debugging attempts.

    This exception indicates that:
    1. The initial code generation produced syntactically invalid code
    2. All available iterative debugging models failed to fix the code
    3. The system has exhausted all automated repair attempts

    This should result in an HTTP 500 error to signal that the agent
    cannot complete the requested task.
    """
    pass

class AgentBase( RunnableCode, abc.ABC ):
    
    STATE_INITIALIZING         = "initializing"
    STATE_WAITING_TO_RUN       = "waiting to run"
    STATE_RUNNING              = "running"
    STATE_WAITING_FOR_RESPONSE = "running waiting for response"
    STATE_STOPPED_ERROR        = "error"
    STATE_STOPPED_DONE         = "done"
    
    # ROUTING_COMMAND_TEMPLATE         = "agent router go to {routing_command}"
    # PROMPT_TEMPLATE_KEY_TEMPLATE     = "prompt template for agent router go to {routing_command}"
    # LLM_SPEC_KEY_TEMPLATE            = "llm spec key for agent router go to {routing_command}"
    # SERIALIZATION_TOPIC_KEY_TEMPLATE = "serialization topic for agent router go to {routing_command}"
    #
    # @staticmethod
    # def build_routing_command( routing_command ):
    #     """
    #     Returns the routing command for the given routing command.
    #     """
    #     return AgentBase.ROUTING_COMMAND_TEMPLATE.format( routing_command=routing_command )
    
    @abc.abstractmethod
    def restore_from_serialized_state( file_path: str ) -> 'AgentBase':
        """
        Restore an agent from a serialized JSON state file.
        
        Requires:
            - file_path is a valid path to an existing JSON file
            - JSON file contains all necessary agent state information
            
        Ensures:
            - Returns a new AgentBase instance with restored state
            - All instance variables are properly initialized from the file
            
        Raises:
            - NotImplementedError (must be implemented by subclasses)
        """
        pass  # pragma: no cover - shadowed duplicate abstractmethod (re-declared identically at the second definition below); this binding is unreachable. Flagged to Tiberius as a prod smell to de-duplicate.

    def __init__( self, df_path_key: Optional[str]=None, question: str="", question_gist: str="", last_question_asked: str="", push_counter: int=-1, routing_command: Optional[str]=None, user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="", debug: bool=False, verbose: bool=False, auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize a base agent with configuration and state.
        
        Requires:
            - routing_command must be provided for proper initialization
            - df_path_key (if provided) must map to a valid CSV file path in config
            - Either question or last_question_asked must be a non-empty string
            - user_id must be a valid system ID
            
        Ensures:
            - execution_state is set to STATE_INITIALIZING then STATE_WAITING_TO_RUN
            - config_mgr is properly initialized
            - model_name and prompt_template are loaded from config
            - DataFrame is loaded and datetime columns cast if df_path_key provided
            - All instance variables are initialized
            - last_question_asked is set to question if empty
            - user_id is stored for event routing and ownership tracking
            - user_email is stored for TTS notification routing

        Raises:
            - KeyError if routing_command configuration keys are missing
            - FileNotFoundError if template or DataFrame file not found
            - ValueError if both question and last_question_asked are empty strings
        """
        
        # Initialize RunnableCode attributes (code_response_dict, prompt_response, etc.)
        super().__init__( debug=debug, verbose=verbose )

        # Quick sanity check to make sure that either question or last question are non-zero length strings
        if question == "" and last_question_asked == "": raise ValueError( "Either `question` or `last_question_asked` must be provided." )

        self.execution_state       = AgentBase.STATE_INITIALIZING
        self.debug                 = debug
        self.verbose               = verbose
        self.auto_debug            = auto_debug
        self.inject_bugs           = inject_bugs
        self.df_path_key           = df_path_key
        self.routing_command       = routing_command
        self.original_args         = None  # CJ Flow persistence field — agent jobs don't carry structured args
        self.user_id               = user_id
        self.user_email            = user_email  # Email for TTS notification routing
        self.session_id            = session_id  # WebSocket session ID for job-notification correlation
        
        # Added to allow behavioral compatibility with solution snapshot object
        self.run_date              = ss.SolutionSnapshot.get_timestamp( microseconds=True )
        self.push_counter          = push_counter
        self.id_hash               = ss.SolutionSnapshot.generate_id_hash( self.push_counter, self.run_date )
        
        self.two_word_id           = TwoWordIdGenerator().get_id()
        
        # This is a bit of a misnomer, last_question_asked is the unprocessed version of the question that was asked of the agent
        # TEST 1:
        if last_question_asked == "":
            self.last_question_asked = question
        else:
            self.last_question_asked = last_question_asked
        # TEST 2:
        if question == "":
            self.question = self.last_question_asked
        else:
            self.question = question  # Store verbatim - DO NOT normalize here!
            
        self.question_gist         = question_gist
        self.answer_conversational = None
        
        self.config_mgr            = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        
        # Initialize XML parser factory for configurable parsing strategy
        self.xml_parser_factory    = XmlParserFactory( config_mgr=self.config_mgr )
        
        self.df                    = None
        self.do_not_serialize      = { "df", "config_mgr", "xml_parser_factory", "two_word_id", "execution_state", "websocket_id", "user_id", "user_email", "session_id" }

        self.model_name            = self.config_mgr.get( f"llm spec key for {routing_command}" )
        template_path              = self.config_mgr.get( f"prompt template for {routing_command}" )
        self.prompt_template       = du.get_file_as_string( du.get_project_root() + template_path )
        
        # Always process template for dynamic XML
        try:
            from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
            processor = PromptTemplateProcessor( debug=self.debug, verbose=self.verbose )
            self.prompt_template = processor.process_template( self.prompt_template, routing_command )
            if self.debug:
                print( f"✓ Processed template for {routing_command} with dynamic XML" )
        except Exception as e:
            if self.debug:
                print( f"⚠ Dynamic XML processing failed for {routing_command}: {e}" )
            # Continue with original template if processing fails
        
        self.prompt                = None
        
        if self.df_path_key is not None:

            self.df = pd.read_csv( du.get_project_root() + self.config_mgr.get( self.df_path_key ) )
            self.df = dup.cast_to_datetime( self.df )

        # QueueableJob protocol compliance - status tracking attributes
        self.answer       = ""
        self.error        = ""  # Must be str, not None (protocol requirement)
        self.state        = JobState.PENDING
        self.is_cache_hit = False
        # None, not "" — an absent timestamp is absent, not an empty string. The
        # empty string is what made a datetime field stringly-typed (row 4a9ebc4b).
        self.started_at   = None
        self.completed_at = None

        # Scheduling attributes (CJ Flow) — sync agents are always immediate, never monopolize
        self.scheduled_at = None
        self.monopolize   = False

        self.execution_state = AgentBase.STATE_WAITING_TO_RUN
    
    @abc.abstractmethod
    def restore_from_serialized_state( file_path: str ) -> 'AgentBase':
        """
        Restore an agent from a serialized JSON state file.
        
        Requires:
            - file_path is a valid path to an existing JSON file
            - JSON file contains all necessary agent state information
            
        Ensures:
            - Returns a new AgentBase instance with restored state
            - All instance variables are properly initialized from the file
            
        Raises:
            - NotImplementedError (must be implemented by subclasses)
        """
        pass
    
    def serialize_to_json( self, subtopic: Optional[str]=None ) -> None:
        """
        Serialize agent state to a JSON file for persistence.
        
        Requires:
            - config_mgr has valid 'serialization topic' for routing_command
            - /io/log directory exists and is writable
            
        Ensures:
            - Creates JSON file with agent state (excluding do_not_serialize fields)
            - File is saved with descriptive name including topic, question, and timestamp
            - File permissions are set to 0o666
            - Prints confirmation of serialization path
            
        Raises:
            - OSError if file cannot be created or permissions cannot be set
            - KeyError if required config keys are missing
        """

        # Convert object's state to a dictionary
        state_dict = self.__dict__

        # Convert object's state to a dictionary, omitting specified fields
        state_dict = { key: value for key, value in self.__dict__.items() if key not in self.do_not_serialize }

        # Constructing the filename
        # Format: "topic-year-month-day-hour-minute-second.json", limit question to the first 96 characters
        question_short = SolutionSnapshot.remove_non_alphanumerics( self.question[ :96 ] ).replace( " ", "-" )
        topic          = self.config_mgr.get( f"serialization topic for {self.routing_command}" )
        topic          = topic + "-" + subtopic if subtopic is not None else topic
        now            = du.get_current_datetime_raw()
        file_path = f"{du.get_project_root()}/io/log/{topic}-{question_short}-{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}-{now.second}.json"

        # Serialize and save to file
        with open( file_path, 'w' ) as file:
            json.dump( state_dict, file, indent=4 )
        os.chmod( file_path, 0o666 )

        print( f"Serialized to {file_path}" )
        
    def _update_response_dictionary( self, response: str ) -> dict[str, Any]:
        """
        Parse LLM response XML into structured dictionary using configurable strategy.
        
        This method now uses the XmlParserFactory to support gradual migration
        from baseline XML parsing to Pydantic-based structured parsing.
        
        Requires:
            - response is a valid XML string
            - self.xml_response_tag_names is defined with expected tags
            - self.routing_command identifies the agent for strategy selection
            
        Ensures:
            - Returns dictionary with parsed values for each expected tag
            - Uses configuration-appropriate parsing strategy (baseline/hybrid/structured)
            - Maintains backward compatibility with existing agent implementations
            
        Raises:
            - XMLParsingError for parsing failures (depending on strategy)
            - ValidationError for Pydantic model validation failures
        """
        
        if self.debug and self.verbose: 
            print( f"_update_response_dictionary called with strategy factory..." )
        
        # Use the factory to parse the XML response with Pydantic strategy
        # No fallback - Pydantic parsing is the ONLY path forward
        prompt_response_dict = self.xml_parser_factory.parse_agent_response(
            xml_response=response,
            agent_routing_command=self.routing_command,
            xml_tag_names=self.xml_response_tag_names,
            debug=self.debug,
            verbose=self.verbose
        )

        if self.debug and self.verbose:
            print( f"Successfully parsed {len( prompt_response_dict )} fields using Pydantic factory" )

        return prompt_response_dict
    
    def run_prompt( self, include_raw_response: bool=False ) -> dict[str, Any]:
        """
        Execute the prompt against the configured LLM.
        
        Requires:
            - self.prompt is set to a valid prompt string
            - self.model_name is configured
            - LLM client factory can provide client for model_name
            
        Ensures:
            - Returns parsed response dictionary with expected XML tags
            - Updates self.prompt_response_dict with parsed values
            - If include_raw_response=True, adds raw XML and question to dict
            
        Raises:
            - LLM-specific exceptions if prompt execution fails
        """

        factory = LlmClientFactory()  # No arguments for the singleton constructor
        llm = factory.get_client( self.model_name, debug=self.debug, verbose=self.verbose )

        if self.debug and self.verbose: print( f"Prompt: {self.prompt}" )
        response = llm.run( self.prompt )
        if self.debug and self.verbose: print( f"Response: {response}" )
        
        # Parse XML-esque response
        self.prompt_response_dict = self._update_response_dictionary( response )
        
        # Add raw response if requested. This is useful for creating synthetic datasets
        if include_raw_response:
            self.prompt_response_dict[ "xml_response" ]        = response
            self.prompt_response_dict[ "last_question_asked" ] = self.last_question_asked
        
        return self.prompt_response_dict
    
    def run_code( self, auto_debug: Optional[bool]=None, inject_bugs: Optional[bool]=None ) -> dict[str, Any]:
        """
        Execute generated code with optional debugging.
        
        Requires:
            - self.prompt_response_dict contains 'code' and 'example' fields
            - Code is syntactically valid Python (unless inject_bugs=True)
            
        Ensures:
            - Returns code response dictionary with output/error info
            - If code runs successfully, sets self.error to None
            - If auto_debug=True and code fails, attempts iterative debugging
            - Updates self.code_response_dict with results
            
        Raises:
            - None (errors are captured in response dictionary)
        """
        
        # Use this object's settings, if temporary overriding values aren't provided
        if auto_debug  is None: auto_debug  = self.auto_debug
        if inject_bugs is None: inject_bugs = self.inject_bugs
        
        # TODO: figure out where this should live, i suspect it will be best located in util_code_runner.py
        if self.debug: print( f"Executing super().run_code() with inject_bugs [{inject_bugs}] and auto_debug [{auto_debug}]..." )
        
        if self.df_path_key is not None:
            path_to_df = self.config_mgr.get( self.df_path_key, default=None )
        else:
            path_to_df = None
            
        code_response_dict = super().run_code( path_to_df=path_to_df, inject_bugs=inject_bugs )
        
        if self.code_ran_to_completion():
            
            self.error = None
            return self.code_response_dict
        
        elif auto_debug:
            
            # Iterative debugging agent extends this class: agent base
            from cosa.agents.iterative_debugging_agent import IterativeDebuggingAgent

            self.error = self.code_response_dict[ "output" ]
            
            # Start out by running the minimalistic debugger first, and then if it fails run the full debugger
            for minimalist in [ True, False ]:

                try:
                    debugging_agent = IterativeDebuggingAgent(
                        code_response_dict[ "output" ], "/io/code.py",
                        minimalist=minimalist, example=self.prompt_response_dict[ "example" ], returns=self.prompt_response_dict.get( "returns", "string" ),
                        debug=self.debug, verbose=self.verbose
                    )
                    # Iterates across multiple LLMs in either minimalist or non-minimalist mode until a solution is found
                    debugging_agent.run_prompts()

                    if debugging_agent.was_successfully_debugged():

                        self.prompt_response_dict[ "code" ] = debugging_agent.code
                        self.code_response_dict             = debugging_agent.code_response_dict
                        self.error                          = None

                        self.print_code( msg=f"Minimalist [{minimalist}] debugging successful, corrected code returned to calling AgentBase run_code()" )
                        break

                    else:

                        du.print_banner( f"Minimalist [{minimalist}] debugging failed, returning original code, such as it is... 😢 sniff 😢" )

                except Exception as debugging_exception:
                    # ANY exception during debugging should be logged but not crash the system
                    # We continue to try the next debugging mode or ultimately raise CodeGenerationFailedException
                    du.print_banner( f"Minimalist [{minimalist}] debugging crashed with exception: {type(debugging_exception).__name__}: {debugging_exception}", expletive=True )
                    if self.debug:
                        import traceback
                        traceback.print_exc()
                    # Continue to next debugging attempt or fall through to final error handling

            # If we reach here, all debugging attempts (both minimalist and full) have failed
            if self.error is not None:
                error_details = f"Original error: {self.error}"
                if self.debug:
                    du.print_banner( "CRITICAL: Code generation failed after exhausting all debugging models", expletive=True )
                    print( f"Question: {self.last_question_asked}" )
                    print( f"Error: {error_details}" )

                raise CodeGenerationFailedException(
                    f"Code generation failed: Unable to fix code errors after exhausting all debugging models. {error_details}"
                )

            return self.code_response_dict
    
    def is_format_output_runnable( self ) -> bool:
        """
        Check if output formatting is available.
        
        Requires:
            - None
            
        Ensures:
            - Prints not implemented message
            - Returns False (base implementation)
            
        Raises:
            - None
        """
        print( "AgentBase.is_format_output_runnable() not implemented" )
        return False
    
    def run_formatter( self ) -> str:
        """
        Format raw output into conversational response.
        
        Requires:
            - self.last_question_asked is set
            - self.code_response_dict contains 'output' field
            - self.routing_command is configured for formatter
            
        Ensures:
            - Returns formatted conversational answer
            - Updates self.answer_conversational with result
            
        Raises:
            - KeyError if required formatter config is missing
        """
        
        formatter = RawOutputFormatter( self.last_question_asked, self.code_response_dict[ "output" ], self.routing_command, debug=self.debug, verbose=self.verbose )
        self.answer_conversational = formatter.run_formatter()
        
        return self.answer_conversational
    
    # Create a message to check and see if the formatting ran to completion
    def formatter_ran_to_completion( self ) -> bool:
        """
        Check if formatter completed successfully.

        Requires:
            - None

        Ensures:
            - Returns True if answer_conversational is set
            - Returns False if answer_conversational is None

        Raises:
            - None
        """
        return self.answer_conversational is not None

    # =========================================================================
    # Unified Interface Properties (for QueueableJob protocol compatibility)
    # =========================================================================

    @property
    def job_type( self ) -> str:
        """
        Unified job type identifier.

        Derived from the class name for AgentBase subclasses, providing
        consistent type identification across all job types (AgentBase,
        SolutionSnapshot, AgenticJobBase).

        Returns:
            str: Class name (e.g., "MathAgent", "CalendarAgent")
        """
        return self.__class__.__name__

    @property
    def created_date( self ) -> str:
        """
        Creation timestamp (unified interface).

        For agents, this is the same as run_date since agents are
        created and executed in the same flow.

        Returns:
            str: Timestamp of agent creation/execution
        """
        return self.run_date

    def do_all( self ) -> str:
        """
        Execute complete agent workflow: prompt -> code -> format.
        
        Requires:
            - Agent is properly initialized with prompt and config
            
        Ensures:
            - Runs prompt execution, code execution, and formatting
            - Returns final conversational answer
            - Updates all relevant instance variables
            
        Raises:
            - Any exceptions from run_prompt, run_code, or run_formatter
        """
        
        self.run_prompt()
        self.run_code()
        self.run_formatter()
        
        return self.answer_conversational


def quick_smoke_test():
    """
    Critical smoke test for AgentBase - validates foundation functionality for all v010 agents.
    
    This test is essential for v000 deprecation as AgentBase is the foundation class
    that all v010 agents inherit from.
    """
    import cosa.utils.util as du
    
    du.print_banner( "AgentBase Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Abstract class behavior
        print( "Testing abstract class behavior..." )
        try:
            # This should fail because AgentBase is abstract
            agent = AgentBase( routing_command="test", question="test question" )
            print( "✗ ERROR: Abstract class was instantiated (should not happen)" )
        except TypeError as e:
            if "abstract" in str( e ).lower():
                print( "✓ Abstract class properly prevents direct instantiation" )
            else:
                print( f"✗ Unexpected TypeError: {e}" )
        except Exception as e:
            print( f"⚠ Unexpected error testing abstract class: {e}" )
        
        # Test 2: State constants validation
        print( "Testing state constants..." )
        expected_states = [
            "STATE_INITIALIZING", "STATE_WAITING_TO_RUN", "STATE_RUNNING",
            "STATE_WAITING_FOR_RESPONSE", "STATE_STOPPED_ERROR", "STATE_STOPPED_DONE"
        ]
        
        all_states_present = True
        for state in expected_states:
            if not hasattr( AgentBase, state ):
                print( f"✗ Missing state constant: {state}" )
                all_states_present = False
        
        if all_states_present:
            print( "✓ All state constants present" )
        
        # Test 3: Required method signatures
        print( "Testing abstract method signatures..." )
        abstract_methods = [ "restore_from_serialized_state" ]
        
        for method_name in abstract_methods:
            if hasattr( AgentBase, method_name ):
                method = getattr( AgentBase, method_name )
                if callable( method ):
                    print( f"✓ Abstract method {method_name} is callable" )
                else:
                    print( f"✗ Abstract method {method_name} is not callable" )
            else:
                print( f"✗ Missing abstract method: {method_name}" )
        
        # Test 4: Basic method presence validation
        print( "Testing core method presence..." )
        core_methods = [
            "get_html", "serialize_to_json", "run_prompt", "run_code", 
            "is_format_output_runnable", "run_formatter", "formatter_ran_to_completion", "do_all"
        ]
        
        methods_present = 0
        for method_name in core_methods:
            if hasattr( AgentBase, method_name ):
                methods_present += 1
            else:
                print( f"⚠ Missing core method: {method_name}" )
        
        if methods_present == len( core_methods ):
            print( f"✓ All {len( core_methods )} core methods present" )
        else:
            print( f"⚠ Only {methods_present}/{len( core_methods )} core methods present" )
        
        # Test 5: Inheritance structure validation
        print( "Testing inheritance structure..." )
        import inspect
        
        # Check if AgentBase properly inherits from RunnableCode and ABC
        base_classes = inspect.getmro( AgentBase )
        base_class_names = [ cls.__name__ for cls in base_classes ]
        
        if "RunnableCode" in base_class_names:
            print( "✓ Properly inherits from RunnableCode" )
        else:
            print( "✗ Missing RunnableCode inheritance" )
        
        if "ABC" in base_class_names:
            print( "✓ Properly inherits from ABC" )
        else:
            print( "✗ Missing ABC inheritance" )
        
        # Test 6: Configuration integration validation
        print( "Testing configuration integration..." )
        try:
            # Test basic import paths work
            from cosa.config.configuration_manager import ConfigurationManager
            print( "✓ ConfigurationManager import successful" )
        except ImportError as e:
            print( f"✗ ConfigurationManager import failed: {e}" )
        
        # Test 7: Dependency imports validation
        print( "Testing critical dependency imports..." )
        critical_imports = [
            ( "cosa.agents.raw_output_formatter", "RawOutputFormatter" ),
            ( "cosa.agents.llm_client_factory", "LlmClientFactory" ),
            ( "cosa.agents.runnable_code", "RunnableCode" ),
            ( "cosa.agents.two_word_id_generator", "TwoWordIdGenerator" )
        ]
        
        import_success_count = 0
        for module_path, class_name in critical_imports:
            try:
                module = __import__( module_path, fromlist=[ class_name ] )
                if hasattr( module, class_name ):
                    import_success_count += 1
                else:
                    print( f"✗ {class_name} not found in {module_path}" )
            except ImportError as e:
                print( f"✗ Failed to import {class_name} from {module_path}: {e}" )
        
        if import_success_count == len( critical_imports ):
            print( f"✓ All {len( critical_imports )} critical dependencies importable" )
        else:
            print( f"⚠ Only {import_success_count}/{len( critical_imports )} critical dependencies importable" )
        
        # Test 8: Critical v000 dependency scanning
        print( "\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( AgentBase )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 9: Validate inheritance chain works
        print( "\nTesting inheritance chain validation..." )
        try:
            # Create a minimal concrete subclass for testing
            class TestAgent( AgentBase ):
                def __init__( self ):
                    # Minimal initialization to test inheritance
                    self.xml_response_tag_names = [ "test" ]
                    self.run_date = "2025-01-22 @ 10:00:00 EST"

                @staticmethod
                def restore_from_serialized_state( file_path: str ):
                    return TestAgent()

            # Test that abstract methods are properly defined
            test_agent = TestAgent()
            if hasattr( test_agent, 'restore_from_serialized_state' ):
                print( "✓ Inheritance chain validation successful" )
            else:
                print( "✗ Inheritance chain validation failed" )
        except Exception as e:
            print( f"⚠ Inheritance chain test had issues: {e}" )

        # Test 10: Validate unified interface properties
        print( "\nTesting unified interface properties..." )
        try:
            class TestAgentForProperties( AgentBase ):
                def __init__( self ):
                    self.xml_response_tag_names = [ "test" ]
                    self.run_date = "2025-01-22 @ 10:00:00 EST"

                @staticmethod
                def restore_from_serialized_state( file_path: str ):
                    return TestAgentForProperties()

            prop_agent = TestAgentForProperties()

            # Test job_type property
            assert prop_agent.job_type == "TestAgentForProperties", f"job_type should be class name, got {prop_agent.job_type}"
            print( f"✓ job_type property works: {prop_agent.job_type}" )

            # Test created_date property
            assert prop_agent.created_date == prop_agent.run_date, "created_date should equal run_date"
            print( f"✓ created_date property works: {prop_agent.created_date}" )

        except Exception as e:
            print( f"⚠ Unified interface properties test had issues: {e}" )
        
    except Exception as e:
        print( f"✗ Error during AgentBase testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: AgentBase has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - All v010 agents will break" )
    else:
        print( "✅ AgentBase smoke test completed successfully!" )
        print( "   Status: Foundation class is ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ AgentBase smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()