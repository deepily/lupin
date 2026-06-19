from typing import Any

import cosa.utils.util as du

from cosa.agents.agent_base import AgentBase
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory

class BugInjector( AgentBase ):
    """
    Agent that intentionally injects bugs into code for testing purposes.
    
    This agent uses an LLM to intelligently modify working code by introducing
    bugs that would realistically occur during development.
    """
    
    def __init__( self, code: list[str], example: str="", debug: bool=True, verbose: bool=True ) -> None:
        """
        Initialize a bug injector with code to modify.
        
        Requires:
            - code is a non-empty list of code lines
            - routing command 'agent router go to bug injector' exists in config
            
        Ensures:
            - Initializes with bug injector routing command
            - Sets up prompt_response_dict with provided code and example
            - Generates initial prompt for bug injection
            
        Raises:
            - KeyError if bug injector config is missing
        """
        
        super().__init__( df_path_key=None, debug=debug, verbose=verbose, routing_command="agent router go to bug injector", question="Inject bug into code" )
        
        self.prompt_response_dict   = {
            "code"   : code,
            "example": example
        }
        self.prompt                 = self._get_prompt()
        
    def _get_prompt( self ) -> str:
        """
        Generate prompt for bug injection with line numbers.
        
        Requires:
            - self.prompt_response_dict contains 'code' list
            - self.prompt_template is loaded from config
            
        Ensures:
            - Returns formatted prompt with numbered code lines
            - Code is properly formatted for LLM processing
            
        Raises:
            - None
        """
        
        code_with_line_numbers = du.get_source_code_with_line_numbers( self.prompt_response_dict[ "code" ].copy(), join_str="\n" )
        
        return self.prompt_template.format( code_with_line_numbers=code_with_line_numbers )
    
    def run_prompt( self, **kwargs ) -> dict[str, Any]:
        """
        Execute bug injection prompt and modify code.
        
        Requires:
            - self.prompt is set with valid bug injection prompt
            - LLM response contains 'line-number' and 'bug' XML tags
            
        Ensures:
            - Returns updated prompt_response_dict with modified code
            - Injects bug at specified line number if valid
            - Prepends blank line to align with 1-based line numbers
            - Prints debug info if debug=True
            
        Raises:
            - None (invalid responses are handled gracefully)
        """
        
        if self.debug: print( "BugInjector.run_prompt() called..." )
        
        factory = LlmClientFactory()
        llm = factory.get_client( self.model_name, debug=self.debug, verbose=self.verbose )
        response = llm.run( self.prompt )
        
        # Use factory-based XML parsing with Pydantic - no fallback
        xml_factory = XmlParserFactory( self.config_mgr )
        parsed_response = xml_factory.parse_agent_response(
            response,
            self.routing_command,
            [ "line-number", "bug" ],
            debug=self.debug,
            verbose=self.verbose
        )
        line_number = int( parsed_response.get( "line_number", -1 ) )  # Pydantic uses line_number
        bug = parsed_response.get( "bug", "" )

        if self.debug: print( f"  Parsed via Pydantic factory: line_number={line_number}, bug='{bug}'" )
        
        if line_number == -1:
            du.print_banner( f"Invalid response from [{self.model_name}]", expletive=True )
            print( response )
        elif line_number > len( self.prompt_response_dict[ "code" ] ):
            du.print_banner( f"Invalid response from [{self.model_name}]", expletive=True )
            print( f"Line number [{line_number}] out of bounds, code[] length is [{len(self.prompt_response_dict[ 'code' ])}]" )
            print( response )
        elif line_number == 0:
            du.print_banner( f"Invalid response from [{self.model_name}]", expletive=True )
            print( f"Line number [{line_number}] is invalid, line numbers SHOULD start at 1" )
            print( response )
        else:
            if self.debug:
                du.print_banner( "BEFORE: untouched code", prepend_nl=True, end="\n" )
                du.print_list( self.prompt_response_dict[ "code" ] )
                
            if self.debug: print( f"Bug generated for line_number: [{line_number}], bug: [{bug}]" )
            # prepend a blank line to the code, so that the line numbers align with the line numbers in the prompt
            self.prompt_response_dict[ "code" ] = [ "" ] + self.prompt_response_dict[ "code" ]
            # todo: do i need to handle possibly mangled preceding white space? if so see: https://chat.openai.com/c/59098430-c164-482e-a82e-01d6c6769978
            self.prompt_response_dict[ "code" ][ line_number ] = bug

        if self.debug:
            du.print_banner( "AFTER: updated code", prepend_nl=True, end="\n" )
            du.print_list( self.prompt_response_dict[ "code" ] )
            
        return self.prompt_response_dict
    
    def restore_from_serialized_state( self, file_path: str ) -> None:
        """
        Restore bug injector state from JSON file.
        
        Requires:
            - file_path points to valid JSON file
            
        Ensures:
            - Raises NotImplementedError (not implemented)
            
        Raises:
            - NotImplementedError always
        """
        
        raise NotImplementedError( "BugInjector.restore_from_serialized_state() not implemented" )

def quick_smoke_test():
    """Quick smoke test to validate BugInjector functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "BugInjector Smoke Test", prepend_nl=True )
    
    # Test with simple code for bug injection
    test_code = [
        "def greet(name):",
        "    return f'Hello, {name}!'",
        "",
        "result = greet('World')",
        "print(result)"
    ]
    test_example = "result = greet('World')"
    
    try:
        print( "Testing bug injection with simple function" )
        bug_injector = BugInjector(
            code=test_code.copy(),
            example=test_example,
            debug=True,
            verbose=False
        )
        print( "✓ BugInjector created successfully" )
        
        # Show original code
        print( "Original code:" )
        bug_injector.print_code()
        
        # Run complete bug injection workflow
        print( "Running bug injection..." )
        response_dict = bug_injector.run_prompt()
        print( "✓ Bug injection completed" )
        
        # Show modified code
        print( "Code with injected bug:" )
        bug_injector.print_code()
        
        # Try to run the buggy code
        print( "Running buggy code..." )
        code_response = bug_injector.run_code()
        print( "✓ Code execution completed" )
        
        if code_response["success"]:
            print( f"✓ Output: {code_response['output']}" )
        else:
            print( f"✓ Error (as expected from bug): {code_response['output']}" )
        
    except Exception as e:
        print( f"✗ Error during bug injection: {e}" )
    
    print( "\n✓ BugInjector smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()