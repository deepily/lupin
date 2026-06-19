from cosa.utils import util     as du

from cosa.config.configuration_manager   import ConfigurationManager
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory

class RawOutputFormatter:
    """
    Formatter for converting raw agent output to conversational responses.
    
    Uses LLM to rephrase technical output into natural language.
    """
    
    def __init__(self, question: str, raw_output: str, routing_command: str, thoughts: str="", code: str="", debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize output formatter with context.
        
        Requires:
            - question and raw_output are non-empty strings
            - routing_command maps to valid formatter config
            - Config has formatter template and LLM spec
            
        Ensures:
            - Loads appropriate formatter template
            - Initializes LLM client for formatting
            - Wraps optional thoughts/code in XML tags
            - Removes XML declarations from raw_output
            
        Raises:
            - KeyError if formatter config missing
            - FileNotFoundError if template missing
        """
        
        self.debug       = debug
        self.verbose     = verbose
        
        self.question    = question
        if thoughts != "":
            self.thoughts = f"<thoughts>{thoughts}</thoughts>"
        else:
            self.thoughts = ""
        if code != "":
            self.code = f"<code>{code}</code>"
        else:
            self.code = ""
        self.raw_output  = raw_output.replace( "<?xml version='1.0' encoding='utf-8'?>", "" )

        self.config_mgr            = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", debug=self.debug, verbose=self.verbose, silent=True )

        # Store both agent routing and formatter routing commands
        self.routing_command       = routing_command  # For config lookups (e.g., "agent router go to math")
        self.formatter_routing_command = f"formatter for {routing_command}"  # For XML parsing (e.g., "formatter for agent router go to math")
        template_path              = self.config_mgr.get( f"formatter template for {routing_command}" )
        model_name                 = self.config_mgr.get( f"formatter llm spec for {routing_command}" )

        self.formatting_template   = du.get_file_as_string( du.get_project_root() + template_path )
        self.prompt                = self._get_prompt()

        factory                    = LlmClientFactory( debug=self.debug, verbose=self.verbose )
        self.llm                   = factory.get_client( model_name, debug=self.debug, verbose=self.verbose )
        
        # Initialize XML parser factory for structured parsing
        self.xml_parser_factory    = XmlParserFactory( self.config_mgr )
    
    def run_formatter( self ) -> str:
        """
        Execute formatter prompt to rephrase output.
        
        Requires:
            - self.prompt is set with formatting prompt
            - LLM is accessible via self.llm
            
        Ensures:
            - Returns rephrased answer from 'rephrased-answer' XML tag
            - Natural language response suitable for users
            - Uses factory-based XML parsing with fallback to baseline
            
        Raises:
            - LLM exceptions if formatting fails
            - XML parsing errors if response malformed
        """

        # Debug logging: Show complete prompt being sent to formatter LLM
        if self.debug and self.verbose:
            du.print_banner( "FORMATTER LLM PROMPT", prepend_nl=True )
            print( self.prompt )
            print()

        response = self.llm.run( self.prompt )

        # Debug logging: Show raw XML response from formatter LLM (before parsing)
        if self.debug and self.verbose:
            du.print_banner( "FORMATTER LLM RAW RESPONSE", prepend_nl=True )
            print( response )
            print()

        # Use factory-based XML parsing with Pydantic - no fallback
        parsed_response = self.xml_parser_factory.parse_agent_response(
            response,
            self.formatter_routing_command,  # Use formatter routing, not agent routing
            [ "rephrased-answer" ],
            debug=self.debug,
            verbose=self.verbose
        )
        output = parsed_response.get( "rephrased_answer", "" )  # Pydantic field name

        if self.debug and self.verbose:
            print( f"RawOutputFormatter: parsed via Pydantic factory: {output}" )

        return output
    
    def _get_prompt( self ) -> str:
        """
        Generate formatting prompt based on routing command.
        
        Requires:
            - self.formatting_template is loaded
            - Question and raw_output are set
            
        Ensures:
            - Returns prompt with appropriate context
            - Includes thoughts/code for certain routing commands
            - Formatted according to template requirements
            
        Raises:
            - None
        """

        if self.routing_command in [ "agent router go to receptionist", "agent router go to math" ]:
            return self.formatting_template.format( question=self.question, raw_output=self.raw_output, thoughts=self.thoughts, code=self.code )
        else:
            return self.formatting_template.format( question=self.question, raw_output=self.raw_output )
    
def quick_smoke_test():
    """Quick smoke test to validate RawOutputFormatter functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "RawOutputFormatter Smoke Test", prepend_nl=True )
    
    try:
        # Test with appropriate professional content
        routing_command = "agent router go to receptionist"
        question = "What's your favorite programming language?"
        thoughts = "The user is asking about programming language preferences. I should provide a helpful response about different languages and their use cases."
        raw_output = "There are many excellent programming languages, each with their own strengths. Python is great for beginners and data science, JavaScript for web development, and Rust for systems programming."
        
        print( f"Testing formatter with routing command: {routing_command}" )
        formatter = RawOutputFormatter( 
            question, 
            raw_output, 
            routing_command, 
            thoughts=thoughts, 
            debug=True, 
            verbose=False 
        )
        print( "✓ RawOutputFormatter created successfully" )
        
        # Run complete formatting workflow
        print( "Running formatter..." )
        formatted_response = formatter.run_formatter()
        print( "✓ Formatting execution completed" )
        
        print( f"✓ Formatted response: {formatted_response[:100]}..." if len( formatted_response ) > 100 else f"✓ Formatted response: {formatted_response}" )
        
    except Exception as e:
        print( f"✗ Error during formatter test: {e}" )
    
    print( "\n✓ RawOutputFormatter smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()