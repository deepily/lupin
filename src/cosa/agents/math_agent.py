import cosa.utils.util as du

from cosa.utils.util_stopwatch import Stopwatch
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.agents.agent_base import AgentBase

class MathAgent( AgentBase ):
    """
    Agent for solving mathematical problems and calculations.
    
    This agent generates Python code to solve math questions,
    using the last_question_asked for maximum specificity.
    """
    
    def __init__( self, question: str="", question_gist: str="", last_question_asked: str="", push_counter: int=-1, routing_command: str="agent router go to math", user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="", debug: bool=False, verbose: bool=False, auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize math agent for mathematical computations.
        
        Requires:
            - Math routing command exists in config
            - Valid prompt template for math queries
            
        Ensures:
            - Uses last_question_asked for specificity from voice transcription
            - Sets up prompt with full question text
            - Defines expected XML response tags
            
        Raises:
            - KeyError if required config missing
        """
        
        super().__init__( df_path_key=None, question=question, question_gist=question_gist, last_question_asked=last_question_asked, routing_command=routing_command, push_counter=push_counter, user_id=user_id, user_email=user_email, session_id=session_id, debug=debug, verbose=verbose, auto_debug=auto_debug, inject_bugs=inject_bugs )

        # du.print_banner( "MathAgent.__init__()" )
        if self.debug and self.verbose: print( "¡OJO! MathAgent is using last_question_asked because it wants all the specificity contained within the voice to text transcription" )

        self.prompt = self.prompt_template.format( question=self.last_question_asked )
        self.xml_response_tag_names   = [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
    
        # self.serialize_prompt_to_json = self.config_mgr.get( "agent todo list serialize prompt to json", default=False, return_type="boolean" )
        # self.serialize_code_to_json   = self.config_mgr.get( "agent todo list serialize code to json",   default=False, return_type="boolean" )
    
    def restore_from_serialized_state( self, file_path: str ) -> None:
        """
        Restore math agent state from JSON file.

        Requires:
            - file_path points to valid JSON file

        Ensures:
            - Raises NotImplementedError (not implemented)

        Raises:
            - NotImplementedError always
        """

        raise NotImplementedError( "MathAgent.restore_from_serialized_state() not implemented" )

    @staticmethod
    def apply_formatting( raw_output: str, config_mgr, debug: bool = False, verbose: bool = False ):
        """
        Apply math-specific formatting logic.

        This method contains the core formatting decision for math outputs.
        Both MathAgent instances and SolutionSnapshot replays use this logic
        to ensure consistent formatting behavior.

        Requires:
            - raw_output is the raw computational result (e.g., "4")
            - config_mgr has 'formatter prompt for math terse' setting

        Ensures:
            - Returns raw output if terse mode enabled
            - Returns None if should use default LLM formatter (verbose mode)

        Args:
            raw_output: Raw result from code execution (e.g., "4", "99")
            config_mgr: ConfigurationManager instance for accessing settings
            debug: Debug flag for logging
            verbose: Verbose flag for detailed logging

        Returns:
            - str: Formatted output if terse mode (returns raw_output as-is)
            - None: Signal to use default LLM formatter (verbose mode)
        """
        terse_output = config_mgr.get( "formatter prompt for math terse", default=False, return_type="boolean" )

        if terse_output:
            # Terse mode: Return raw output directly, skip LLM formatting
            if debug and verbose:
                print( "MathAgent.apply_formatting: terse_output=True. Returning raw output without LLM formatting." )
            return raw_output
        else:
            # Verbose mode: Signal caller to use default LLM formatter
            if debug and verbose:
                print( "MathAgent.apply_formatting: terse_output=False. Signaling to use default LLM formatter." )
            return None

    def run_formatter( self ) -> str:
        """
        Format math output using agent-specific formatting logic.

        Requires:
            - self.code_response_dict contains 'output' field
            - Config has 'formatter prompt for math terse' setting

        Ensures:
            - Returns formatted answer
            - If terse_output=True, returns raw output
            - Otherwise uses parent formatter (default LLM formatter)
            - Updates self.answer_conversational

        Raises:
            - KeyError if output missing from response
        """

        # Use static formatting logic (shared with SolutionSnapshot)
        raw_output = self.code_response_dict[ "output" ]
        formatted = MathAgent.apply_formatting(
            raw_output,
            self.config_mgr,
            self.debug,
            self.verbose
        )

        if formatted is not None:
            # Terse mode: Use raw output directly
            self.answer_conversational = formatted
        else:
            # Verbose mode: Use default LLM formatter
            super().run_formatter()

        return self.answer_conversational

def quick_smoke_test():
    """Quick smoke test to validate MathAgent functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "MathAgent Smoke Test", prepend_nl=True )
    
    # Test with a math question for completion
    question = "What's the square root of 144?"
    
    try:
        print( f"Testing question: '{question}'" )
        math_agent = MathAgent( question=question, debug=True, verbose=False, auto_debug=False )
        print( "✓ MathAgent created successfully" )
        
        # Run through the complete agent workflow
        print( "Running prompt..." )
        math_agent.run_prompt()
        print( "✓ Prompt execution completed" )
        
        print( "Running code..." )
        math_agent.run_code()
        print( "✓ Code execution completed" )
        
        print( "Running formatter..." )
        math_agent.run_formatter()
        print( "✓ Formatter execution completed" )
        
        print( f"✓ Final response: {math_agent.answer_conversational}" )
        
    except Exception as e:
        print( f"✗ Error during math agent execution: {e}" )
    
    print( "\n✓ MathAgent smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()