import os
import json
from typing import Optional, Any

import cosa.utils.util as du
import cosa.utils.util_code_runner as ucr

from cosa.agents.agent_base import AgentBase
from cosa.agents.io_models.utils.util_xml_pydantic import remove_xml_escapes


class IterativeDebuggingAgent( AgentBase ):
    """
    Agent that iteratively debugs code using multiple LLMs until a solution is found.
    
    This agent attempts to fix code errors by using different language models in sequence,
    testing the fixes until the code runs successfully or all models have been tried.
    """
    
    def __init__( self, error_message: str, path_to_code: str, example: Optional[str]=None, returns: Optional[str]=None, minimalist: bool=True, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize the iterative debugging agent.
        
        Requires:
            - error_message is a non-empty string with the error to debug
            - path_to_code is a valid relative path to the code file
            - The code file exists at project_root + path_to_code
            - Config has 'llm model keys for debugger' setting
            
        Ensures:
            - Loads the available LLM models for debugging
            - Formats the code with line numbers
            - Sets up appropriate prompt based on minimalist mode
            - Initializes XML response tags based on mode
            
        Raises:
            - FileNotFoundError if the code file doesn't exist
            - ConfigException if required config settings missing
        """
        
        super().__init__( routing_command="agent router go to debugger", debug=debug, verbose=verbose, question="Debug code error" )
        
        self.code                   = []
        self.example                = example
        self.returns                = returns
        self.project_root           = du.get_project_root()
        self.path_to_code           = path_to_code
        self.formatted_code         = du.get_file_as_source_code_with_line_numbers( self.project_root + self.path_to_code )
        self.error_message          = error_message
        self.minimalist             = minimalist
        self.prompt                 = self._get_prompt()
        self.prompt_response_dict   = { }
        self.available_llms         = self._load_available_llm_specs()
        self.successfully_debugged  = False
        if self.minimalist:
            self.xml_response_tag_names = [ "thoughts", "line-number", "one-line-of-code", "success" ]
        else:
            self.xml_response_tag_names = [ "thoughts", "code", "example", "returns", "explanation" ]
        
        # this is already set in the parent class: agent base
        # self.do_not_serialize       = [ "config_mgr" ]
        
    def _load_available_llm_specs( self ) -> list[dict[str, Any]]:
        """
        Load LLM specifications from configuration.
        
        Requires:
            - Config has 'llm model keys for debugger' as valid JSON
            - Each key in model_keys exists in configuration as JSON
            
        Ensures:
            - Returns list of LLM specification dictionaries
            - Each spec dict contains model configuration details
            - Prints loading status for each model
            
        Raises:
            - ConfigException if required settings not found
            - JSONDecodeError if invalid JSON in config
        """
        
        model_keys = self.config_mgr.get( "llm model keys for debugger", return_type="json" )
        
        available_llms = []
        for key in model_keys:
            print( f"Loading debugger LLM: {key}... ", end="" )
            llm_spec = self.config_mgr.get( key )
            available_llms.append( llm_spec )
            print( llm_spec )
        
        return available_llms
    
    def _get_prompt( self ) -> str:
        """
        Create debugging prompt based on mode.
        
        Requires:
            - self.error_message is set
            - self.formatted_code contains code with line numbers
            - Config has 'agent prompt for debugger minimalist' if minimalist=True
            
        Ensures:
            - Returns formatted prompt string
            - If minimalist, loads minimalist template
            - Otherwise uses existing prompt_template
            - Sets self.prompt_template for non-minimalist first call
            
        Raises:
            - FileNotFoundError if prompt template file missing
            - ConfigException if required config not found
        """
        
        if self.debug: print( f"IterativeDebuggingAgent._get_prompt() minimalist: {self.minimalist}", end="\n" )
        if self.minimalist:
            self.prompt_template  = du.get_file_as_string( du.get_project_root() + self.config_mgr.get_required( "agent prompt for debugger minimalist" ) )
            prompt                = self.prompt_template.format( error_message=self.error_message, formatted_code=self.formatted_code )
            if self.debug and self.verbose: print( f"Prompt: {prompt}" )
            return prompt
        else:
            return self.prompt_template.format( error_message=self.error_message, formatted_code=self.formatted_code )
    
    def run_prompts( self, debug: Optional[bool]=None ) -> dict[str, Any]:
        """
        Run debugging prompts through available LLMs until success.
        
        Requires:
            - self.available_llms has at least one LLM spec
            - Each LLM spec has required 'model' field
            - self.prompt is set
            
        Ensures:
            - Attempts debugging with each LLM in sequence
            - Updates self.successfully_debugged on success
            - Updates self.code only if debugging succeeds
            - Returns final code_response_dict
            - Serializes each attempt to log
            
        Raises:
            - LLM-specific exceptions from run_prompt
            - RuntimeError if code execution fails
        """
        
        if debug is not None: self.debug = debug
        
        idx = 1
        self.successfully_debugged = False
        
        for llm in self.available_llms:
            
            run_descriptor = f"Run {idx} of {len( self.available_llms )}"
            
            if self.successfully_debugged:
                break
                
            # model_id       = llm[ "model_id"       ] if "model_id"       in llm else model_name.split("/")[-1]
            # temperature    = llm[ "temperature"    ] if "temperature"    in llm else 0.50
            # top_p          = llm[ "top_p"          ] if "top_p"          in llm else 0.25
            # top_k          = llm[ "top_k"          ] if "top_k"          in llm else 10
            # max_new_tokens = llm[ "max_new_tokens" ] if "max_new_tokens" in llm else 1024
            # stop_sequences = llm[ "stop_sequences" ] if "stop_sequences" in llm else []
            
            du.print_banner( f"{run_descriptor}: Executing debugging prompt using model [{llm}]...", end="\n" )
            
            # prompt_response_dict = self.run_prompt( model_name=model_name, temperature=temperature, top_p=top_p, top_k=top_k, max_new_tokens=max_new_tokens, stop_sequences=stop_sequences )
            prompt_response_dict = self.run_prompt()
            
            # TODO: debug and reinstate if/when needed in the future
            #  Serialize the prompt response
            # topic = "code-debugging-minimalist" if self.minimalist else "code-debugging"
            # self.serialize_to_json( topic, du.get_current_datetime_raw(), run_descriptor=run_descriptor, model_id=model_id )
            
            du.print_banner( f"{run_descriptor}: Prompt response dictionary" )
            print( json.dumps( prompt_response_dict, indent=4 ) )
            
            # Test for minimalist success
            if self.minimalist and prompt_response_dict.get( "success", "False" ) == "True":
                self._patch_code_in_response_dict( prompt_response_dict )
                self.prompt_response_dict[ "example" ] = self.example
                self.prompt_response_dict[ "returns" ] = self.returns
            elif self.minimalist:
                print( "Minimalist prompt failed, updating code to []..." )
                self.prompt_response_dict[ "code" ] = []
            
            code_response_dict = ucr.initialize_code_response_dict()
            if self.is_code_runnable():
                
                code_response_dict         = self.run_code()
                self.successfully_debugged = self.code_ran_to_completion()
                
                # Only update the code if it was successfully debugged and run to completion
                if self.successfully_debugged:
                    self.code = prompt_response_dict[ "code" ]
                    print( f"Successfully debugged? 😊¡Sí! 😊 Exiting LLM loop..." )
                else:
                    print( f"Successfully debugged? 😢¡Nooooooo! 😢 ", end="" )
                    
                    # test for the last llm in this list
                    if llm == self.available_llms[ -1 ]:
                        print( "No more LLMs to try. Exiting LLM loop..." )
                    else:
                        print( "Moving on to the next LLM..." )
            else:
                print( "Skipping code execution step because the prompt did not produce any code to run." )
                code_response_dict[ "output" ] = "Code was deemed un-runnable by iterative debugging agent"
                
            idx += 1
            
        return code_response_dict
    
    def _patch_code_in_response_dict( self, prompt_response_dict: dict[str, Any] ) -> None:
        """
        Patch a single line of code in the response dictionary.
        
        Requires:
            - prompt_response_dict has 'line-number' as string int
            - prompt_response_dict has 'one-line-of-code' field
            - self.path_to_code is a valid file path
            
        Ensures:
            - Updates self.prompt_response_dict with full code
            - Replaces specified line with patched code
            - Removes XML escapes from the patched line
            - Updates 'code' field in self.prompt_response_dict
            
        Raises:
            - KeyError if required fields missing from dict
            - ValueError if line-number is not valid integer
        """
        
        print( "Patching code in response dictionary..." )
        formatted_code = du.get_file_as_source_code_with_line_numbers( self.project_root + self.path_to_code )
        print( formatted_code )
        
        # Get raw code 1st
        code = du.get_file_as_list( self.project_root + self.path_to_code, strip_newlines=True )
        self.prompt_response_dict[ "code" ] = code
        if self.debug: self.print_code( msg="BEFORE patching code in response dictionary" )
        
        # Get the patched code - handle both Pydantic (line_number) and baseline (line-number) field names
        if "line_number" in prompt_response_dict:
            # Pydantic structured parsing (line-number → line_number)
            line_number = int( prompt_response_dict[ "line_number" ] ) - 1
        else:
            # Baseline parsing (line-number)
            line_number = int( prompt_response_dict[ "line-number" ] ) - 1
            
        if "one_line_of_code" in prompt_response_dict:
            # Pydantic structured parsing (one-line-of-code → one_line_of_code)
            line_of_code = prompt_response_dict[ "one_line_of_code" ]
        else:
            # Baseline parsing (one-line-of-code)
            line_of_code = prompt_response_dict[ "one-line-of-code" ]
        line_of_code = remove_xml_escapes( line_of_code )
        print( f"Patching line {line_number} with [{line_of_code}]")
        
        # insert the patched line of code into the code list
        self.prompt_response_dict[ "code" ][ line_number ] = line_of_code
        if self.debug: self.print_code( msg="AFTER patching code in response dictionary" )

    def was_successfully_debugged( self ) -> bool:
        """
        Check if debugging attempt was successful.
        
        Requires:
            - self.successfully_debugged is initialized
            
        Ensures:
            - Returns True if code was successfully debugged
            - Returns False otherwise
            
        Raises:
            - None
        """
        
        return self.successfully_debugged
    
    def serialize_to_json( self, topic: str, now: Any, run_descriptor: str="Run 1 of 1", model_id: str="phi_4" ) -> None:
        """
        Serialize agent state to JSON file.
        
        Requires:
            - topic is a non-empty string
            - now has year, month, day, hour, minute, second attributes
            - /io/log/ directory exists at project root
            
        Ensures:
            - Saves agent state to JSON file
            - Excludes fields in self.do_not_serialize
            - Creates filename with timestamp and descriptor
            - Sets file permissions to 0o666
            
        Raises:
            - OSError if file cannot be written
            - AttributeError if now lacks required attributes
        """

        # Convert object's state to a dictionary
        state_dict = self.__dict__

        # Convert object's state to a dictionary, omitting specified fields
        state_dict = { key: value for key, value in self.__dict__.items() if key not in self.do_not_serialize }

        # Constructing the filename, format: "topic-run-on-year-month-day-at-hour-minute-run-1-of-3-using-llm-model_id-step-N-of-M.json"
        run_descriptor = run_descriptor.replace( " ", "-" ).lower()
        file_path       = f"{du.get_project_root()}/io/log/{topic}-on-{now.year}-{now.month}-{now.day}-at-{now.hour}-{now.minute}-{now.second}-{run_descriptor}-using-llm-{model_id}.json"

        # Serialize and save to file
        with open( file_path, 'w' ) as file:
            json.dump( state_dict, file, indent=4 )
        os.chmod( file_path, 0o666 )
        
        print( f"Serialized to {file_path}" )
    
    @staticmethod
    def restore_from_serialized_state( file_path: str ) -> 'IterativeDebuggingAgent':
        """
        Restore agent instance from serialized JSON file.
        
        Requires:
            - file_path is a valid path to existing JSON file
            - JSON contains required fields: error_message, path_to_code
            - JSON structure matches IterativeDebuggingAgent state
            
        Ensures:
            - Returns new IterativeDebuggingAgent instance
            - Restores all attributes from JSON
            - Skips reinitializing constructor parameters
            
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
        restored_agent = IterativeDebuggingAgent(
            data[ "error_message" ], data[ "path_to_code" ],
            debug=data[ "debug" ], verbose=data[ "verbose" ]
        )
        # Set the remaining attributes from the parsed data, skipping the ones that we've already set
        keys_to_skip = [ "error_message", "path_to_code", "debug", "verbose" ]
        for k, v in data.items():
            if k not in keys_to_skip:
                setattr( restored_agent, k, v )
            else:
                print( f"Skipping key [{k}], it's already been set" )
        
        return restored_agent
    
    def is_code_runnable( self ) -> bool:
        """
        Check if there is code available to run.
        
        Requires:
            - self.prompt_response_dict is initialized
            
        Ensures:
            - Returns True if code field exists and is non-empty
            - Returns False otherwise
            - Prints diagnostic message if no code found
            
        Raises:
            - None
        """
        
        if self.prompt_response_dict is not None and len( self.prompt_response_dict[ "code" ] ) > 0:
            return True
        else:
            print( "No code to run: self.response_dict[ 'code' ] = [ ]" )
            return False
        
def quick_smoke_test():
    """Quick smoke test to validate IterativeDebuggingAgent functionality."""
    import cosa.utils.util as du
    import os
    from cosa.config.configuration_manager import ConfigurationManager
    
    du.print_banner( "IterativeDebuggingAgent Smoke Test", prepend_nl=True )
    
    try:
        # Set up test scenario
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        code_file_path = config_mgr.get("path to code execution file")
        test_file_path = du.get_project_root() + code_file_path
        
        error_message = f'''File "{test_file_path}", line 3
        print("Hello World"
             ^
    SyntaxError: unexpected EOF while parsing'''
        
        # Create test file with syntax error
        test_code = '''def greeting():
    print("Hello World"
'''
        
        print( f"Creating test file with syntax error: {test_file_path}" )
        with open( test_file_path, 'w' ) as f:
            f.write( test_code )
        
        # Initialize debugging agent
        debugging_agent = IterativeDebuggingAgent(
            error_message=error_message,
            path_to_code=code_file_path,
            example="greeting()",
            returns="None",
            minimalist=True,
            debug=True,
            verbose=False
        )
        print( "✓ IterativeDebuggingAgent created successfully" )
        
        # Run complete debugging workflow
        print( "Running debugging process..." )
        result = debugging_agent.run_prompts()
        print( "✓ Debugging process completed" )
        
        # Check results
        if debugging_agent.was_successfully_debugged():
            print( "✓ Debugging successful!" )
            print( "Fixed code:" )
            debugging_agent.print_code()
        else:
            print( "⚠ Debugging failed (may require LLM server)" )
            print( f"Result: {result.get('output', 'No output')}" )
        
        # Clean up
        if os.path.exists( test_file_path ):
            os.remove( test_file_path )
            print( "✓ Test file cleaned up" )
        
    except Exception as e:
        print( f"✗ Error during debugging test: {e}" )
        # Ensure cleanup
        try:
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            code_file_path = config_mgr.get("path to code execution file")
            test_file_path = du.get_project_root() + code_file_path
            if os.path.exists( test_file_path ):
                os.remove( test_file_path )
        except:
            pass
    
    print( "\n✓ IterativeDebuggingAgent smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
    