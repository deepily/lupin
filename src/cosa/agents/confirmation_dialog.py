from typing import Optional

import cosa.utils.util as du

from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.llm_client import LlmClient
from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.io_models.xml_models import YesNoResponse
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError

class ConfirmationDialogue:
    """
    A utility class for confirming yes/no responses using LLMs.
    
    This class does not inherit from AgentBase as it's designed to be
    a lightweight utility for confirmation dialogs rather than a full agent.
    
    Configuration:
        - "prompt template for confirmation dialog": Path to the prompt template file (required)
        - "llm_spec_key_for_confirmation_dialog": LLM model specification (required when model_name not provided)
        
    Requires:
        - Valid configuration with required keys
        - Access to LLM via factory
        
    Ensures:
        - Provides consistent yes/no/ambiguous classification
        - Handles different phrasings of affirmative/negative responses
        
    Raises:
        - Configuration errors if setup fails
    """
    
    def __init__( self, model_name: Optional[str]=None, config_mgr: Optional[ConfigurationManager]=None, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize confirmation dialogue utility.
        
        Requires:
            - Either model_name or 'llm_spec_key_for_confirmation_dialog' in config
            - 'prompt template for confirmation dialog' exists in config
            
        Ensures:
            - Sets up config_mgr if not provided
            - Loads prompt template from configured path
            - Model name is set from parameter or config
            
        Raises:
            - KeyError if required config keys missing
            - FileNotFoundError if template file missing
        """
        
        self.config_mgr = config_mgr or ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        
        # Use provided model_name, or get from config
        if model_name is None: model_name = self.config_mgr.get( "llm spec key for confirmation dialog" )
        
        self.model_name = model_name
        self.debug = debug
        self.verbose = verbose
        self.prompt = None

        if self.debug:
            print( "ConfirmationDialogue initialized with Pydantic XML parsing" )
        
        # Get prompt template path from config
        prompt_template_path = self.config_mgr.get( "prompt template for confirmation dialog" )
        self.prompt_template = du.get_file_as_string( du.get_project_root() + prompt_template_path )
    
    def confirmed( self, utterance: str, default: Optional[bool]=None ) -> bool:
        """
        Determines if the response is a confirmed 'yes' or 'no'.
        
        Requires:
            - utterance is a non-empty string
            - self.prompt_template exists and contains {utterance} placeholder
            - LLM is accessible via factory.get_client
            
        Ensures:
            - Returns True for affirmative responses
            - Returns False for negative responses
            - Returns default for ambiguous responses (if provided)
            - Response is parsed from 'answer' XML tag
            
        Raises:
            - ValueError if response is ambiguous and no default provided
            - LLM-specific exceptions if prompt execution fails
        """
        self.prompt = self.prompt_template.format( utterance=utterance )
        
        # Use v010 LLM client factory pattern
        factory = LlmClientFactory()
        llm = factory.get_client( self.model_name, debug=self.debug, verbose=self.verbose )
        results = llm.run( self.prompt )
        
        # Use Pydantic YesNoResponse model for structured parsing
        try:
            response_model = YesNoResponse.from_xml( results )
            response = response_model.answer.strip().lower()
            if self.debug and self.verbose: print( f"Pydantic parsing extracted response: '{response}'" )
        except XMLParsingError as e:
            if self.debug: print( f"XML parsing failed: {e}" )
            raise ValueError( f"Failed to parse confirmation response: {e}" )
        except Exception as e:
            if self.debug: print( f"Unexpected error during XML parsing: {e}" )
            raise ValueError( f"Failed to parse confirmation response: {e}" )
        
        if response == "yes":
            return True
        elif response == "no":
            return False
        elif default is not None:
            return default
        else:
            raise ValueError( f"Ambiguous response '{response}' has no default value provided. Ask the user for clarification." )
        
def quick_smoke_test():
    """Quick smoke test to validate ConfirmationDialogue functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "ConfirmationDialogue Smoke Test", prepend_nl=True )
    
    # Test a clear yes/no case for completion
    test_utterance = "Yes, please proceed."
    
    try:
        print( f"Testing utterance: '{test_utterance}'" )
        confirmation_dialogue = ConfirmationDialogue(
            model_name=LlmClient.GROQ_LLAMA_3_1_8B,
            debug=True,
            verbose=False
        )
        print( "✓ ConfirmationDialogue created successfully" )
        
        # Run complete confirmation workflow
        print( "Running confirmation..." )
        result = confirmation_dialogue.confirmed( test_utterance, default=None )
        print( "✓ Confirmation execution completed" )
        
        result_text = "Yes" if result else "No"
        print( f"✓ Confirmation result: {result_text}" )
        
    except Exception as e:
        print( f"✗ Error during confirmation: {e}" )
    
    print( "\n✓ ConfirmationDialogue smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
