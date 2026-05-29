import json
from typing import Any, Optional

import cosa.utils.util as du

from cosa.agents.agent_base import AgentBase

class TodoListAgent( AgentBase ):
    """
    Agent that manages and queries todo lists stored in DataFrames.
    
    This agent provides functionality to read, manipulate, and answer
    questions about todo lists stored in a pandas DataFrame.
    """
    
    def __init__( self, question: str="", question_gist: str="", last_question_asked: str="", push_counter: int=-1, routing_command: str="agent router go to todo", user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="", debug: bool=False, verbose: bool=False, auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize the todo list agent.
        
        Requires:
            - DataFrame at path specified by path_to_todolist_df_wo_root config exists
            - DataFrame has columns: list_name and expected todo columns
            
        Ensures:
            - Loads todo list DataFrame from configured path
            - Sets up prompt with DataFrame metadata
            - Configures XML response tags for code generation
            
        Raises:
            - FileNotFoundError if DataFrame file doesn't exist
            - ConfigException if required config missing
        """
        
        super().__init__( df_path_key="path to todolist df wo root", question=question, question_gist=question_gist, last_question_asked=last_question_asked, routing_command=routing_command, push_counter=push_counter, user_id=user_id, user_email=user_email, session_id=session_id, debug=debug, verbose=verbose, auto_debug=auto_debug, inject_bugs=inject_bugs )
        
        self.prompt = self._get_prompt()
        self.xml_response_tag_names   = [ "thoughts", "code", "example", "returns", "explanation" ]
        self.serialize_prompt_to_json = self.config_mgr.get( "agent todo list serialize prompt to json", default=False, return_type="boolean" )
        self.serialize_code_to_json   = self.config_mgr.get( "agent todo list serialize code to json",   default=False, return_type="boolean" )
        
    def _get_prompt( self ) -> str:
        """
        Generate prompt with todo list metadata.
        
        Requires:
            - self.last_question_asked is set
            - self.prompt_template has placeholders: question, column_names, list_names, head
            - DataFrame is loaded and accessible
            
        Ensures:
            - Returns formatted prompt with current DataFrame metadata
            - Includes column names, list names, and sample data
            
        Raises:
            - KeyError if template missing required placeholders
        """
        
        column_names, list_names, head = self._get_df_metadata()
        
        return self.prompt_template.format( question=self.last_question_asked, column_names=column_names, list_names=list_names, head=head )
    
    def _get_df_metadata( self ) -> tuple[list[str], list[str], str]:
        """
        Extract metadata from the todo list DataFrame.
        
        Requires:
            - self.df is a valid pandas DataFrame
            - DataFrame has 'list_name' column
            - DataFrame has at least one row
            
        Ensures:
            - Returns tuple of (column_names, list_names, sample_data)
            - Sample data includes first 2 and last 2 rows as CSV
            - list_names contains unique values from list_name column
            
        Raises:
            - AttributeError if DataFrame missing expected columns
            - ValueError if DataFrame is empty
        """
        
        # head = self.df.head( 2 ).to_xml( index=False )
        # head = head.replace( "<?xml version='1.0' encoding='utf-8'?>", "" )
        # head = head.replace( "data>", "todo>" )
        #
        # head = head + self.df.tail( 2 ).to_xml( index=False )
        # head = head.replace( "<?xml version='1.0' encoding='utf-8'?>", "" )
        # head = head.replace( "data>", "todo>" )
        
        head = self.df.head( 2 ).to_csv( index=False )
        head = head + self.df.tail( 2 ).to_csv( index=False )
        
        column_names = self.df.columns.tolist()
        list_names   = self.df.list_name.unique().tolist()
        
        return column_names, list_names, head
    
    def run_prompt( self, **kwargs ) -> dict[str, Any]:
        """
        Execute the prompt and optionally serialize results.
        
        Requires:
            - Parent class run_prompt works correctly
            
        Ensures:
            - Executes prompt via parent class
            - Serializes to JSON if configured
            - Returns prompt response dictionary
            
        Raises:
            - Any exceptions from parent run_prompt
        """
        
        results = super().run_prompt( **kwargs )
        
        if self.serialize_prompt_to_json: self.serialize_to_json( "prompt" )
        
        return results
        
    def run_code( self, auto_debug: Optional[bool]=None, inject_bugs: Optional[bool]=None ) -> dict[str, Any]:
        """
        Execute generated code and optionally serialize results.
        
        Requires:
            - Parent class run_code works correctly
            - Code is available to run
            
        Ensures:
            - Executes code via parent class
            - Serializes to JSON if configured
            - Returns code execution results
            
        Raises:
            - Any exceptions from parent run_code
        """
        
        results = super().run_code( auto_debug=auto_debug, inject_bugs=inject_bugs )
        
        if self.serialize_code_to_json: self.serialize_to_json( "code" )
        
        return results
    
    @staticmethod
    def restore_from_serialized_state( file_path: str ) -> 'TodoListAgent':
        """
        Restore agent instance from serialized JSON state.
        
        Requires:
            - file_path points to valid JSON file
            - JSON contains required constructor parameters
            - JSON has structure matching TodoListAgent state
            
        Ensures:
            - Returns new TodoListAgent with restored state
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
        restored_agent = TodoListAgent(
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
    """Quick smoke test to validate TodoListAgent functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "TodoListAgent Smoke Test", prepend_nl=True )
    
    # Test with a todo list question for completion
    question = "What's on my to do list for today?"
    
    try:
        print( f"Testing question: '{question}'" )
        todolist_agent = TodoListAgent( 
            question=question, 
            debug=True, 
            verbose=False, 
            auto_debug=False, 
            inject_bugs=False 
        )
        print( "✓ TodoListAgent created successfully" )
        
        # Run through the complete agent workflow
        print( "Running prompt..." )
        todolist_agent.run_prompt()
        print( "✓ Prompt execution completed" )
        
        if todolist_agent.is_code_runnable():
            print( "Running code..." )
            results = todolist_agent.run_code()
            print( "✓ Code execution completed" )
            
            print( "Running formatter..." )
            answer = todolist_agent.run_formatter()
            print( "✓ Formatter execution completed" )
            
            print( f"✓ Final response: {answer}" )
        else:
            print( "⚠ No runnable code generated" )
        
    except Exception as e:
        print( f"✗ Error during todo list agent execution: {e}" )
    
    print( "\n✓ TodoListAgent smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
    