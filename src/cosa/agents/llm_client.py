import os
import time
from typing import Optional, Any

import cosa.utils.util as du
from cosa.agents.llm_completion import LlmCompletion

from cosa.agents.token_counter import TokenCounter

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
# from pydantic_ai.models.openai import OpenAIModel
# from pydantic_ai.providers.openai import OpenAIProvider

from cosa.config.configuration_manager import ConfigurationManager


class LlmClient:
    """
    A flexible client for interacting with local and remote LLM services.
    
    This client provides a unified interface for both chat and completion modes,
    handles token counting, supports streaming, and collects performance metrics.
    
    Requires:
        - Valid base_url for the LLM API endpoint
        - Valid model_name compatible with the API
        - API key if required by the service
        - TokenCounter for tracking token usage
        
    Ensures:
        - Consistent interface for both completion and chat-based models
        - Token counting for prompt and completion
        - Performance metrics (tokens/second, duration)
        - Proper environment variable configuration for API access
        - Streaming and non-streaming response options
    
    Usage:
        client = LlmClient(base_url="https://api.endpoint.com/v1", 
                          model_name="model-name",
                          completion_mode=False)
        response = client.run("Your prompt here", stream=True)
    """
    # for ad hoc use when creating the ephemeral models
    DEEPILY_PREFIX                    = "deepily"
    # Model identifier constants
    PHI_4_14B                         = "kaitchup/phi_4_14b"
    DEEPILY_MINISTRAL_8B_2410_FT_LORA = "deepily/ministral_8b_2410_ft_lora"
    MINISTRAL_8B_2410                 = "mistralai/Ministral-8B-Instruct-2410"
    GROQ_LLAMA_3_1_8B                 = "groq:llama-3.1-8b-instant"
    GROQ_LLAMA_3_3_70B                = "groq:llama-3.3-70b-versatile"
    OPENAI_GPT_01_MINI                = "openai:o1-mini-2024-09-12"
    GOOGLE_GEMINI_1_5_FLASH           = "google-gla:gemini-1.5-flash"
    ANTHROPIC_CLAUDE_SONNET_3_5       = "anthropic:claude-3-5-sonnet-latest"
    
    # QWEN_2_5_32B = "kaitchup/Qwen2.5-Coder-32B-Instruct-AutoRound-GPTQ-4bit"
    
    @staticmethod
    def get_model( mnt_point: str, prefix: str=DEEPILY_PREFIX ) -> str:
        """
        Construct a model identifier in the required format.
        
        Requires:
            - mnt_point is a non-empty string
            - prefix is a non-empty string
            
        Ensures:
            - Returns model string in 'prefix//mnt_point' format
            - Validates that '//' is present in the constructed model
            
        Raises:
            - ValueError if the constructed model doesn't contain '//'
        """
        
        model = f"{prefix}/{mnt_point}"
        if "//" not in model:
            raise ValueError( f"ERROR: Model [{model}] not in 'prefix//mnt/point' format!" )
        return model
    
    def __init__( self,
        
        base_url: str = "http://192.168.1.21:3001/v1",
        model_name: str = "F00",
        completion_mode: bool = False,
        prompt_format: str = "",
        api_key: Optional[ str ] = "EMPTY",
        model_tokenizer_map: Optional[dict[str, str]] = None,
        debug: bool = False,
        verbose: bool = False,
        **generation_args: Any
    ) -> None:
        """
        Initialize an LLM client with the given configuration.
        
        Requires:
            - base_url: A valid API endpoint URL
            - model_name: A valid model identifier for the service
            - api_key: If required, a valid API key for the service
            
        Ensures:
            - Sets up environment variables for API access
            - Initializes appropriate client based on completion_mode
            - Creates TokenCounter for usage tracking
            - Stores generation parameters for use with LLM calls
            
        Raises:
            - Various initialization errors depending on client type and parameters
        """
        os.environ[ "OPENAI_API_KEY" ]  = api_key or "EMPTY"
        os.environ[ "OPENAI_BASE_URL" ] = base_url
        
        self.model_name      = model_name
        self.completion_mode = completion_mode
        self.prompt_format   = prompt_format
        self.token_counter   = TokenCounter( model_tokenizer_map )
        self.generation_args = generation_args
        self.debug           = debug
        self.verbose         = verbose
        
        if completion_mode:
            if self.debug:
                du.print_banner( f"TODO: Fetch COMPLETION style prompt formatter HERE", prepend_nl=True, expletive=True, chunk="¿?"  )
                print( f"¿? '{model_name}'" )
                print( f"Using LlmCompletion with prompt_format: '{prompt_format}'" )
            self.model = LlmCompletion( base_url=base_url, model_name=model_name, api_key=api_key, **generation_args )
        else:
            # For normal chat mode, use the Agent class
            # if self.debug: print( f"Using Agent with model: 'openai:{model_name}'" )
            du.print_banner( f"TODO: fetch and set system prompt HERE! for model 'openai:{model_name}'", prepend_nl=True, expletive=True )
            # Wrap generation parameters in ModelSettings for pydantic_ai API
            model_settings = ModelSettings( **generation_args )
            self.model = Agent( f"openai:{model_name}", model_settings=model_settings )
    
    async def _stream_async( self, prompt: str, **generation_args: Any ) -> str:
        """
        Internal method to handle async streaming.
        
        This asynchronous method handles streaming responses from the LLM,
        capturing chunks as they arrive and returning the combined result.
        It works with both Agent (Chat) and LlmCompletion modes.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.model: An initialized model with async streaming capability
            - self.completion_mode: Boolean indicating whether to use completion API
            
        Ensures:
            - Streams response chunks from the LLM
            - Displays progress if self.debug is True
            - Collects all chunks into a single response
            - Handles both chat and completion API formats
            
        Returns:
            - Complete response string from the LLM
        """
        output = [ ]
        
        if self.completion_mode:
            # Use run_stream for LlmCompletion
            # Wrap generation parameters in ModelSettings for pydantic_ai API
            runtime_settings = ModelSettings( **generation_args )
            async with self.model.run_stream( prompt, model_settings=runtime_settings ) as result:
                # Stream text as deltas
                counter = 0
                async for chunk in result.stream_text( delta=True ):
                    if self.debug and self.verbose:
                        print( chunk, end="", flush=True )
                    else:
                        counter += 1
                        if counter % 128 == 0: print()
                        print( ".", end="", flush=True )
                    output.append( chunk )
        else:
            # Use run_stream for Agent (Chat)
            # Wrap generation parameters in ModelSettings for pydantic_ai API
            runtime_settings = ModelSettings( **generation_args )
            async with self.model.run_stream( prompt, model_settings=runtime_settings ) as result:
                # Stream text as deltas
                async for chunk in result.stream_text( delta=True ):
                    counter = 0
                    if self.debug and self.verbose:
                        print( chunk, end="", flush=True )
                    else:
                        counter += 1
                        if counter % 128 == 0: print()
                        print( ".", end="", flush=True )
                    output.append( chunk )
        
        return "".join( output )
    
    async def run_async( self, prompt: str, stream: bool=False, **kwargs: Any ) -> str:
        """
        Async version to send a prompt to the LLM and get the response.
        
        This method is designed for use in async contexts (like FastAPI).
        It handles both streaming and non-streaming responses, measures
        performance metrics, and provides debugging information.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.model: An initialized model with async run capability
            - self.token_counter: An initialized TokenCounter
            
        Ensures:
            - Sends the prompt to the LLM and receives a response
            - Counts tokens for both prompt and completion
            - Measures performance metrics (duration, tokens/sec)
            - Handles both streaming and non-streaming modes
            - Displays performance metrics
            
        Args:
            - prompt: The text to send to the LLM
            - stream: Whether to stream the response (default: False)
            
        Returns:
            - String response from the LLM
        """
        
        prompt_tokens = self.token_counter.count_tokens( self.model_name, prompt )
        
        # update generation arguments
        if self.debug: print( "Updating generation arguments..." )
        updated_gen_args = {
            "temperature": kwargs.get( "temperature", self.generation_args.get( "temperature", 0.7 ) ),
            "max_tokens" : kwargs.get( "max_tokens", self.generation_args.get( "max_tokens", 64 ) ),
            "stop"       : kwargs.get( "stop", self.generation_args.get( "stop", None ) ),
            "top_p"      : kwargs.get( "top_p", self.generation_args.get( "top_p", 1.0 ) ),
            # Allow stream to be set from generation_args if not explicitly provided
            "stream"     : stream or self.generation_args.get( "stream", False ),
        }
        
        # Check both the explicit parameter and the updated_gen_args
        if not updated_gen_args["stream"]:

            # Add timing for non-streaming mode too
            start_time = time.perf_counter()

            if not self.completion_mode:
                # For Agent, use async run
                # Wrap generation parameters in ModelSettings for pydantic_ai API
                runtime_settings = ModelSettings( **updated_gen_args )
                response = await self.model.run( prompt, model_settings=runtime_settings )
                response = response.output
            else:
                # For LlmCompletion, need to await the async version
                # TODO: Check if LlmCompletion has async support
                response = self.model.run( prompt, **updated_gen_args )

            duration = time.perf_counter() - start_time
            completion_tokens = self.token_counter.count_tokens( self.model_name, response )
            if self.debug and self.verbose: self._print_metadata( prompt_tokens, completion_tokens, duration=duration )
            return response
        
        # Streaming mode
        output = ""
        if self.debug and self.verbose: print( f"🔄 Streaming from model: {self.model_name}\n" )
        start_time = time.perf_counter()
        
        # Direct async call - no event loop needed here
        output = await self._stream_async( prompt, **updated_gen_args )
        
        duration = time.perf_counter() - start_time
        completion_tokens = self.token_counter.count_tokens( self.model_name, output )
        
        if self.debug and self.verbose: self._print_metadata( prompt_tokens, completion_tokens, duration )
        return output
    
    def run( self, prompt: str, stream: bool=False, **kwargs: Any ) -> str:
        """
        Send a prompt to the LLM and get the response.
        
        This method now supports both sync and async contexts. When called
        from an async context (like FastAPI), it runs the async operation
        in a separate thread to avoid event loop conflicts. When called from a 
        sync context, it handles the event loop creation automatically.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.model: An initialized model with run capability
            - self.token_counter: An initialized TokenCounter
            
        Ensures:
            - Sends the prompt to the LLM and receives a response
            - Counts tokens for both prompt and completion
            - Measures performance metrics (duration, tokens/sec)
            - Handles both streaming and non-streaming modes
            - Displays performance metrics
            - Works in both sync and async contexts
            
        Args:
            - prompt: The text to send to the LLM
            - stream: Whether to stream the response (default: False)
            
        Returns:
            - String response from the LLM (works in both sync and async contexts)
            
        TODO:
            - Add support for distinguishing between system and user messages
            - Improve handling of chat vs completion formats
            - Develop more sophisticated message history management
        """
        
        # Import asyncio at function level to avoid issues
        import asyncio
        import concurrent.futures
        import threading
        
        def run_in_new_loop():
            """Helper function to run async code in a new event loop in a thread"""
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop( new_loop )
            try:
                return new_loop.run_until_complete( self.run_async( prompt, stream, **kwargs ) )
            finally:
                new_loop.close()
        
        try:
            # Check if we're in an existing event loop
            loop = asyncio.get_running_loop()
            # We're in async context - run in a separate thread to avoid blocking
            with concurrent.futures.ThreadPoolExecutor( max_workers=1 ) as executor:
                future = executor.submit( run_in_new_loop )
                return future.result()
        except RuntimeError:
            # No event loop running - we're in sync context
            # Can run directly with a new event loop
            return run_in_new_loop()
    
    # def _format_duration( self, seconds: float ) -> str:
    #     """
    #     Format a duration in seconds to a readable string.
    #
    #     Requires:
    #         - seconds: A float representing seconds
    #
    #     Ensures:
    #         - Returns a formatted string in milliseconds
    #
    #     Returns:
    #         - String in the format "XXXms"
    #     """
    #     # return f"{seconds:.3f}" if seconds > 1 else f"{seconds * 1000:.3f} ms"
    #     return f"{int( seconds * 1000 )}ms"
    #
    # def _print_metadata( self, prompt_tokens: int, completion_tokens: int, duration: Optional[ float ] ):
    #     """
    #     Print performance metadata about an LLM request.
    #
    #     This method calculates and displays key metrics about the LLM interaction,
    #     including token counts, duration, and tokens per second.
    #
    #     Requires:
    #         - prompt_tokens: Integer count of tokens in the prompt
    #         - completion_tokens: Integer count of tokens in the completion
    #         - duration: Float representing seconds taken, or None
    #
    #     Ensures:
    #         - Calculates total tokens and tokens per second
    #         - Formats duration appropriately
    #         - Displays a formatted summary of metrics
    #
    #     TODO:
    #         - Add cost estimation based on token usage and model pricing
    #         - Implement more detailed performance metrics
    #         - Add optional logging to file for performance tracking
    #         - Fix potential division by zero issues in TPS calculation
    #         - Support different output formats (JSON, CSV, etc.)
    #     """
    #
    #     total_tokens = prompt_tokens + completion_tokens
    #     tps = completion_tokens / duration if (duration and duration > 0) else float( 'inf' )
    #     duration_str = self._format_duration( duration ) if duration is not None else "N/A"
    #
    #     du.print_banner( "📊 Stream Summary", prepend_nl=True )
    #     print( f"🧠 Model              : {self.model_name}" )
    #     print( f"⏱️ Duration           : {duration_str}" )
    #     print( f"🔢 Prompt tokens      : {prompt_tokens}" )
    #     print( f"💬 Completion tokens  : {completion_tokens}" )
    #     print( f"🧮 Total tokens       : {total_tokens}" )
    #     print( f"⚡ Tokens/sec          : {tps:.2f}" )
    #     print( "=" * 40 )


def quick_smoke_test():
    """Quick smoke test to validate LlmClient functionality."""
    du.print_banner( "LlmClient Smoke Test", prepend_nl=True )
    
    # Test different client initialization methods
    test_cases = [
        {
            "name": "Local completion model",
            "config": {
                "base_url": "http://192.168.1.21:3000/v1/completions",
                "model_name": "/mnt/DATA01/include/www.deepily.ai/projects/models/Ministral-8B-Instruct-2410.lora/merged-on-2025-02-12-at-02-05/autoround-4-bits-sym.gptq/2025-02-12-at-02-27",
                "completion_mode": True
            }
        },
        {
            "name": "Groq API model",
            "config": {
                "model_name": LlmClient.GROQ_LLAMA_3_3_70B
            }
        }
    ]
    
    # Simple test prompt
    test_prompt = "What is 2 + 2?"
    
    for i, test_case in enumerate( test_cases, 1 ):
        print( f"\nTest {i}: {test_case['name']}" )
        
        try:
            # Create client with test configuration
            client = LlmClient( debug=False, verbose=False, **test_case["config"] )
            print( f"✓ LlmClient created successfully for {test_case['name']}" )
            
            # For smoke test, we'll just validate client creation to avoid API costs
            # In a full test, you could uncomment the line below:
            # response = client.run( test_prompt, stream=False, max_tokens=50 )
            # print( f"✓ Response received: {response[:50]}..." )
            print( f"✓ Client is ready for LLM requests" )
            
        except Exception as e:
            print( f"✗ Error with {test_case['name']}: {str( e )}" )
    
    # Test prompt template loading
    print( f"\nTesting prompt template loading:" )
    try:
        template_path = du.get_project_root() + "/src/conf/prompts/agent-router-template-completion.txt"
        prompt_template = du.get_file_as_string( template_path )
        formatted_prompt = prompt_template.format( voice_command="test command" )
        print( f"✓ Prompt template loaded and formatted successfully" )
    except Exception as e:
        print( f"⚠ Warning: Could not load prompt template: {e}" )
    
    print( "\n✓ LlmClient smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()