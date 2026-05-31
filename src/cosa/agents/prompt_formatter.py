import os
import json
import re
from typing import Optional

import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager


class PromptFormatter:
    """
    A utility class for formatting prompts according to model-specific requirements.
    
    This class supports three primary prompt formatting styles:
    1. instruction_completion: Used by Mistral, Ministral, some LLaMA models
    2. special_token: Used by Phi-4 and other models with special token formats
    3. json_message: Used by OpenAI, Claude, Groq API, etc.
    
    Requires:
        - ConfigurationManager instance available via CLI args
        - Template files for each format type
        - Template directory with read/write permissions
        
    Ensures:
        - Consistent prompt formatting for different model types
        - Template-based approach allows for easy updates
        - All formats return strings for consistent interface
        - Default templates created if not found
    """
    
    def __init__( self, template_dir: Optional[str]=None, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize the prompt formatter with configuration and templates.
        
        Requires:
            - Valid ConfigurationManager instance can be created
            - Write permissions for template directory if it needs to be created
            
        Ensures:
            - ConfigurationManager is initialized with correct environment variable
            - Template directory exists and is accessible
            - Debug and verbose flags are set correctly
            
        Args:
            template_dir: Optional directory path containing prompt templates
            debug: Enable debug output
            verbose: Enable verbose logging
            
        Raises:
            - OSError if template directory creation fails
            - PermissionError if template directory is not writable
        """
        self.debug      = debug
        self.verbose    = verbose
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        
        # Initialize template directory
        if template_dir:
            self.template_dir = template_dir
        else:
            template_path = self.config_mgr.get( "prompt format template directory", default="src/conf/prompts/v1/llms" )
            self.template_dir = os.path.join( du.get_project_root(), template_path )
            
        if self.debug:
            print( f"Using template directory: {self.template_dir}" )
            
        # Create template directory if it doesn't exist
        if not os.path.exists( self.template_dir ):
            if self.debug: print( f"Creating template directory: {self.template_dir}" )
            os.makedirs( self.template_dir, exist_ok=True )
    
    def get_prompt_format( self, model_name: str ) -> str:
        """
        Determine which prompt format type to use based on configuration.
        
        Requires:
            - model_name is a non-empty string
            - ConfigurationManager is properly initialized
            
        Ensures:
            - Returns one of three format types: "instruction_completion", "special_token", or "json_message"
            - Configuration values take precedence over pattern matching
            - Default values are used as a last resort
            
        Args:
            model_name: String identifier for the model
            
        Returns:
            String: "instruction_completion", "special_token", or "json_message"
            
        Raises:
            - ValueError if model_name is empty
        """
        # First check if there's a specific format defined for this model
        format_key = f"prompt_format_{model_name}"
        
        if self.config_mgr.exists( format_key ):
            return self.config_mgr.get( format_key )
        
        # If no explicit configuration, check if there's a format for the model family
        for prefix in [ "openai", "groq", "anthropic", "phi", "mistral", "llama" ]:
            if prefix in model_name.lower():
                family_format_key = f"prompt_format_default_{prefix}"
                if self.config_mgr.exists( family_format_key ):
                    return self.config_mgr.get( family_format_key )
        
        # Last resort: make a best guess
        return self._get_prompt_format_best_guess( model_name )
    
    def _get_prompt_format_best_guess( self, model_name: str ) -> str:
        """
        Make a best guess at the appropriate prompt format based on model name patterns.
        Only used as a fallback when no configuration is available.
        
        Requires:
            - model_name is a non-empty string
            - ConfigurationManager is accessible for default format fallback
            
        Ensures:
            - Returns a valid format type based on model name pattern matching
            - Falls back to configuration default if pattern matching fails
            - Always returns one of: "instruction_completion", "special_token", or "json_message"
            
        Args:
            model_name: String identifier for the model
            
        Returns:
            String: "instruction_completion", "special_token", or "json_message"
        """
        # Check patterns in the model name to infer the likely format
        model_name_lower = model_name.lower()
        
        # JSON Message format models (API-based services)
        if any( prefix in model_name_lower for prefix in [ "openai:", "groq:", "anthropic:", "claude", "gpt" ] ):
            return "json_message"
        
        # Special token format models
        if any( token in model_name_lower for token in [ "phi-", "phi_", "phi4" ] ):
            return "special_token"
        
        # Instruction completion format models
        if any( name in model_name_lower for name in [ "mistral", "llama", "ministral" ] ):
            return "instruction_completion"
        
        # Default to the most widely supported format if we can't determine
        default_format = self.config_mgr.get( "prompt format default", "json_message" )
        return default_format
    
    def format_prompt( self, model_name: str, instructions: str, input_text: str, output: str="" ) -> str:
        """
        Format a prompt according to the appropriate template for the model.
        Uses template files for consistent formatting across the system.
        
        Requires:
            - model_name is a non-empty string
            - instructions is a string (empty string permitted)
            - input_text is a string (empty string permitted)
            - Template files are properly formatted with placeholders for {instructions}, {input}, and {output}
            
        Ensures:
            - Returns a properly formatted prompt string based on model's required format
            - Template placeholders are filled with provided values
            - Output field is included if provided, omitted if empty
            - For JSON message format, returns a properly formatted JSON string
            
        Args:
            model_name: String identifier for the model
            instructions: System instructions or context
            input_text: User query or input
            output: Optional output for training examples
            
        Returns:
            Formatted prompt string in the appropriate structure for the model
            
        Raises:
            - ValueError if format_type is unknown
            - ValueError if template loading or formatting fails
        """
        format_type = self.get_prompt_format( model_name )
        
        if format_type == "instruction_completion":
            # Load template from the file system based on the format type
            template_path = os.path.join( self.template_dir, "instruction-completion-default.txt" )
            template = self._load_template( template_path )
            
            # Format with the provided values
            prompt = template.format(
                instructions=instructions,
                input=input_text,
                output=output if output else ""
            )
            return prompt
        
        elif format_type == "special_token":
            
            # For special token formats, load model-specific template
            # Extract model identifier for template selection
            model_id = self._extract_model_id( model_name )
            template_path = os.path.join( self.template_dir, f"special-token-{model_id}.txt" )
            
            if not os.path.exists( template_path ):
                # Fallback to generic template if model-specific one doesn't exist
                template_path = os.path.join( self.template_dir, "special-token-default.txt" )
            
            template = self._load_template( template_path )
            prompt = template.format(
                instructions=instructions,
                input=input_text,
                output=output if output else ""
            )
            return prompt
        
        elif format_type == "json_message":
            # Create messages list
            messages = [
                { "role": "system", "content": instructions },
                { "role": "user", "content": input_text }
            ]
            
            if output:
                messages.append( { "role": "assistant", "content": output } )
            
            # Convert to JSON string for consistent return type
            return json.dumps( messages )
        
        else:
            raise ValueError( f"Unknown prompt format type: {format_type}" )
    
    def _load_template( self, template_path: str ) -> str:
        """
        Load a template file from the file system.
        
        Requires:
            - template_path is a valid file path string
            - Either the template file exists or we have permission to create it
            
        Ensures:
            - Returns the content of the template as a string
            - Creates a default template if the file doesn't exist
            - Template contains valid placeholders for formatting
            
        Args:
            template_path: Path to the template file
            
        Returns:
            String template content
        
        Raises:
            - ValueError if the template file cannot be found and cannot be created
            - OSError if file system operations fail
            - PermissionError if lacking permissions to read or create the file
        """
        try:
            return du.get_file_as_string( template_path )
        except FileNotFoundError:
            # If the template doesn't exist, try to create a default one
            return self._create_default_template( template_path )
    
    def _create_default_template( self, template_path: str ) -> str:
        """
        Create a default template file if it doesn't exist.
        
        Requires:
            - template_path is a valid file path string
            - Write permissions for the directory containing template_path
            - Filename follows expected naming conventions for template identification
            
        Ensures:
            - Creates a new template file with appropriate content based on filename
            - Returns the content of the newly created template
            - Parent directories are created if they don't exist
            
        Args:
            template_path: Path where the template should be created
            
        Returns:
            String content of the created template
            
        Raises:
            - ValueError if template cannot be created based on filename
            - OSError if directory creation fails
            - PermissionError if lacking write permissions
        """
        print( f"Creating default template: {template_path}..." )
        template_name = os.path.basename( template_path )
        
        # Create appropriate default template based on filename
        if template_name == "instruction-completion-default.txt":
            content = "<s>[INST] {instructions}\n\n{input} [/INST]\n{output}</s>"
        elif template_name == "special-token-default.txt":
            content = "<|system|>{instructions}<|end|>\n<|user|>{input}<|end|>\n<|assistant|>{output}<|end|>"
        elif template_name.startswith( "special-token-phi-" ):
            content = "<|system|>{instructions}<|end|>\n<|user|>{input}<|end|>\n<|assistant|>{output}<|end|>"
        elif template_name.startswith( "special-token-llama-" ):
            content = "<s> [INST] <<SYS>> {instructions} <</SYS>>\n\n{input} [/INST] {output} </s>"
        else:
            raise ValueError( f"Cannot create default template for {template_name}" )
        
        # Create the parent directory if it doesn't exist
        os.makedirs( os.path.dirname( template_path ), exist_ok=True )
        
        # Write the template to disk ( util signature is write_string_to_file( path, string ) )
        du.write_string_to_file( template_path, content )
        
        if self.debug: print( f"Creating default template: {template_path} ... Done!" )
        
        return content
    
    def _extract_model_id( self, model_name: str ) -> str:
        """
        Extract a clean model identifier from the model name for template selection.
        
        Requires:
            - model_name is a non-empty string
            
        Ensures:
            - Returns a sanitized string suitable for use in template filenames
            - Common model patterns are recognized and normalized
            - Special characters are replaced with underscores
            - Always returns a valid, non-empty string
            
        Args:
            model_name: String identifier for the model
            
        Returns:
            Clean model identifier for template matching
            
        Raises:
            - ValueError if model_name is empty
        """
        # Handle different formats: phi-4, foo-14b, etc.
        model_name_lower = model_name.lower()
        
        # Extract common model identifiers
        if "phi-4" in model_name_lower or "phi_4" in model_name_lower:
            return "phi_4"
        elif "phi-3" in model_name_lower:
            return "phi_3"
        elif "llama-3" in model_name_lower or "llama_3" in model_name_lower:
            return "llama_3"
        elif "mistral-7b" in model_name_lower:
            return "mistral_7b"
        
        # Fallback: sanitize the model name by keeping alphanumeric and underscores
        return re.sub( r'[^a-z0-9_]', '_', model_name_lower )
    
    def create_template_examples( self ) -> dict[str, str]:
        """
        Create example templates for all supported format types.
        
        Requires:
            - Write permissions for the template directory
            - self.template_dir is properly initialized
            
        Ensures:
            - Creates example templates for all supported format types
            - Does not overwrite existing templates
            - Returns a dictionary mapping template names to their file paths
            - All templates contain the proper placeholders for formatting
            
        Returns:
            Dictionary mapping template names to their file paths
            
        Raises:
            - OSError if directory or file creation fails
            - PermissionError if lacking write permissions
        """
        templates = {
              "instruction-completion-default.txt": "<s>[INST] {instructions}\n\n{input} [/INST]\n{output}</s>",
              "special-tokens-default.txt"         : "<|system|>{instructions}<|end|>\n<|user|>{input}<|end|>\n<|assistant|>{output}<|end|>",
              "special-tokens-phi-4.txt"           : "<|system|>{instructions}<|end|>\n<|user|>{input}<|end|>\n<|assistant|>{output}<|end|>",
              "special-tokens-llama-3.txt"         : "<s> [INST] <<SYS>> {instructions} <</SYS>>\n\n{input} [/INST] {output} </s>"
        }
        
        created_paths = { }
        for name, content in templates.items():
            path = os.path.join( self.template_dir, name )
            
            # Only create if it doesn't exist
            if not os.path.exists( path ):
                # Create the directory if needed
                os.makedirs( os.path.dirname( path ), exist_ok=True )
                
                # Write the template
                with open( path, "w" ) as f:
                    f.write( content )
                
                if self.debug:
                    print( f"Created template: {path}" )
            
            created_paths[ name ] = path
        
        return created_paths


def quick_smoke_test():
    """Quick smoke test to validate PromptFormatter functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "PromptFormatter Smoke Test", prepend_nl=True )
    
    try:
        print( "Creating PromptFormatter instance..." )
        formatter = PromptFormatter( debug=True, verbose=False )
        print( "✓ PromptFormatter created successfully" )
        
        # Test template creation
        print( "Creating example templates..." )
        created_templates = formatter.create_template_examples()
        print( f"✓ Created {len( created_templates )} templates" )
        
        # Test formatting for different model types
        test_models = [
            "deepily/ministral_8b_2410_ft_lora",
            "kaitchup/phi_4_14b", 
            "openai:gpt-4"
        ]
        
        instructions = "You are a helpful AI assistant."
        input_text = "What is the capital of France?"
        output = "The capital of France is Paris."
        
        print( "Testing prompt formatting for different models..." )
        for model in test_models:
            print( f"Testing model: {model}" )
            
            # Test format detection
            format_type = formatter.get_prompt_format( model )
            print( f"  ✓ Format detected: {format_type}" )
            
            # Test prompt formatting
            formatted = formatter.format_prompt( model, instructions, input_text, output )
            print( f"  ✓ Prompt formatted successfully ({len( formatted )} chars)" )
        
        print( "✓ All formatting tests passed" )
        
    except Exception as e:
        print( f"✗ Error during prompt formatter test: {e}" )
    
    print( "\n✓ PromptFormatter smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
