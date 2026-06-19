import json
from typing import Any

import cosa.utils.util as du

from cosa.agents.agent_base import AgentBase
from cosa.agents.raw_output_formatter import RawOutputFormatter
from cosa.memory.input_and_output_table import InputAndOutputTable

class ReceptionistAgent( AgentBase ):
    """
    Agent that handles general conversation and memory retrieval.
    
    This agent acts as a receptionist, answering questions based on
    previous conversations stored in the input/output table memory.
    """
    
    def __init__( self, question: str="", question_gist: str="", last_question_asked: str="", push_counter: int=-1, routing_command: str="agent router go to receptionist", user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="", debug: bool=False, verbose: bool=False, auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize the receptionist agent with memory access.
        
        Requires:
            - InputAndOutputTable can be initialized
            - Config has necessary prompt templates
            
        Ensures:
            - Initializes memory table for Q&A storage
            - Loads appropriate prompt template
            - Sets up XML response tags for category and answer
            
        Raises:
            - ConfigException if required config missing
        """
        
        super().__init__( df_path_key=None, question=question, question_gist=question_gist, last_question_asked=last_question_asked, routing_command=routing_command, push_counter=push_counter, user_id=user_id, user_email=user_email, session_id=session_id, debug=debug, verbose=verbose, auto_debug=auto_debug, inject_bugs=inject_bugs )
        
        self.io_tbl                   = InputAndOutputTable( debug=self.debug, verbose=self.verbose )
        self.prompt                   = self._get_prompt()
        self.xml_response_tag_names   = [ "thoughts", "category", "answer" ]
        self.serialize_prompt_to_json = self.config_mgr.get( "agent receptionist serialize prompt to json", default=False, return_type="boolean" )
        # self.serialize_code_to_json   = self.config_mgr.get( "agent_receptionist_serialize_code_to_json",   default=False, return_type="boolean" )
    
    def _get_prompt( self ) -> str:
        """
        Generate prompt with memory entries.
        
        Requires:
            - self.last_question_asked is set
            - self.prompt_template has query, date_today, entries placeholders
            
        Ensures:
            - Returns formatted prompt with current date and memory entries
            - Memory entries formatted as XML fragments
            
        Raises:
            - KeyError if template missing required placeholders
        """
        
        # ¡OJO!: this call is fundamentally in elegant because it grabs a bunch of previous QnQ handled by the receptionist and throws them in.
        # there is zero look up of semantically related content... This is not even RAG, it's pre-rag force. You can do better!
        date_today, entries = self._get_df_metadata()
        
        return self.prompt_template.format( query=self.last_question_asked, date_today=date_today, entries=entries )
    
    def _get_df_metadata( self ) -> tuple[str, str]:
        """
        Retrieve memory entries and current date.
        
        Requires:
            - self.io_tbl is initialized
            - Memory table has date, input, output_final columns
            
        Ensures:
            - Returns tuple of (current_date, formatted_entries)
            - Each entry formatted as XML memory fragment
            - All entries joined with newlines
            
        Raises:
            - KeyError if expected columns missing from rows
        """
        
        entries    = []
        rows       = self.io_tbl.get_all_qnr()
        for row in rows:
            entries.append( f"<memory-fragment> <date>{row['date']}</date/> <human-queried>{row['input']}</human-queried> <ai-answered>{row['output_final']}</ai-answered> </memory-fragment>" )
            
        entries    = "\n".join( entries )
        date_today = du.get_current_date()
        
        return date_today, entries
    
    def run_prompt( self, **kwargs ) -> dict[str, Any]:
        """
        Execute prompt and extract conversational answer.
        
        Requires:
            - Parent class run_prompt works correctly
            - Response contains 'answer' field
            
        Ensures:
            - Sets self.answer_conversational from response
            - Optionally serializes prompt to JSON
            - Returns complete response dictionary
            
        Raises:
            - KeyError if response missing 'answer' field
        """
        
        results = super().run_prompt( **kwargs )
        
        self.prompt_response_dict = results
        
        self.answer_conversational = self.prompt_response_dict[ "answer" ]
        
        if self.serialize_prompt_to_json: self.serialize_to_json( "prompt" )
        
        return results
    
    def is_code_runnable( self ) -> bool:
        """
        Check if agent has runnable code.
        
        Requires:
            - None
            
        Ensures:
            - Always returns False (receptionist doesn't run code)
            
        Raises:
            - None
        """
        
        return False
    
    def run_code( self, auto_debug: Any=None, inject_bugs: Any=None ) -> dict[str, Any]:
        """
        Placeholder code execution (not used by receptionist).
        
        Requires:
            - None
            
        Ensures:
            - Returns success response with informative message
            - Sets self.code_response_dict
            - Prints informative message
            
        Raises:
            - None
        """
        
        print( "NOT Running code, this is a receptionist agent" )
        self.code_response_dict = {
            "return_code": 0,
            "output": "No code to run, this is a receptionist agent"
        }
        return self.code_response_dict
    
    def code_ran_to_completion( self ) -> bool:
        """
        Check if code ran successfully (always true for receptionist).
        
        Requires:
            - None
            
        Ensures:
            - Always returns True to satisfy interface
            
        Raises:
            - None
        """
        
        # This is a necessary lie to satisfy the interface
        return True
    
    def run_formatter( self ) -> str:
        """
        Format output based on content category.
        
        Requires:
            - self.prompt_response_dict has 'category' and 'thoughts' fields
            - self.answer_conversational is set
            
        Ensures:
            - Applies formatter only for non-benign content
            - Updates self.answer_conversational if formatted
            - Returns final conversational answer
            
        Raises:
            - KeyError if required fields missing from response dict
        """
        
        # Only reformat the output if it's humorous or salacious
        if self.prompt_response_dict[ "category" ] != "benign":
            
            formatter = RawOutputFormatter(
                self.last_question_asked, self.answer_conversational, self.routing_command,
                thoughts=self.prompt_response_dict[ "thoughts" ], debug=self.debug, verbose=self.verbose
            )
            self.answer_conversational = formatter.run_formatter()
            
        else:
            print( "Not reformatting the output, it's benign" )
        
        return self.answer_conversational
   
    
    @staticmethod
    def restore_from_serialized_state( file_path: str ) -> 'ReceptionistAgent':
        """
        Restore agent from serialized JSON state.
        
        Requires:
            - file_path points to valid JSON file
            - JSON contains required constructor parameters
            
        Ensures:
            - Returns new ReceptionistAgent with restored state
            - All attributes restored from JSON
            - Constructor parameters handled correctly
            
        Raises:
            - FileNotFoundError if file doesn't exist
            - JSONDecodeError if invalid JSON
            - KeyError if required fields missing
        """
        
        print( f"Restoring from {file_path}..." )
        
        # Read the file and parse JSON
        with open( file_path, 'r' ) as file:
            data = json.load( file )
        
        # Create a new object instance with the parsed data
        restored_agent = ReceptionistAgent(
            data[ "question" ], debug=data[ "debug" ], verbose=data[ "verbose" ], auto_debug=data[ "auto_debug" ], inject_bugs=data[ "inject_bugs" ]
        )
        # Set the remaining attributes from the parsed data, skipping the ones that we've already set
        keys_to_skip = [ "question", "debug", "verbose", "auto_debug", "inject_bugs"]
        for k, v in data.items():
            if k not in keys_to_skip:
                setattr( restored_agent, k, v )
            else:
                print( f"Skipping key [{k}], it's already been set" )
        
        return restored_agent
    
def quick_smoke_test():
    """Quick smoke test to validate ReceptionistAgent functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "ReceptionistAgent Smoke Test", prepend_nl=True )
    
    # Test with a simple question for completion
    question = "What's your name?"
    
    try:
        print( f"Testing question: '{question}'" )
        receptionist_agent = ReceptionistAgent( question=question, debug=True, verbose=False )
        print( "✓ ReceptionistAgent created successfully" )
        
        # Run through the complete agent workflow
        print( "Running prompt..." )
        receptionist_agent.run_prompt()
        print( "✓ Prompt execution completed" )
        
        # Receptionist doesn't run code, but we test the interface
        print( "Testing code interface..." )
        code_result = receptionist_agent.run_code()
        print( "✓ Code interface tested (returns no-op)" )
        
        print( "Running formatter..." )
        response = receptionist_agent.run_formatter()
        print( "✓ Formatter execution completed" )
        
        print( f"✓ Final response: {response}" )
        
    except Exception as e:
        print( f"✗ Error during receptionist agent execution: {e}" )
    
    print( "\n✓ ReceptionistAgent smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()