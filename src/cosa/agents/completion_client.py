import os
import time
import re
from typing import Optional, Any
import asyncio
import concurrent.futures

import cosa.utils.util as du
from cosa.agents.base_llm_client import LlmClientInterface
from cosa.agents.llm_completion import LlmCompletion
from cosa.agents.token_counter import TokenCounter


def clean_llm_response( response: str ) -> str:
    """
    Remove extraneous backticks from LLM completion response.
    
    Requires:
        - response is a string containing the LLM output
        
    Ensures:
        - Returns cleaned response without surrounding backticks
        - Preserves the actual content between backticks
        
    Raises:
        - None
    """
    # Remove backticks at start (with optional language identifier) and end
    cleaned = re.sub( r'^```(?:\w+)?\n?', '', response.strip() )
    cleaned = re.sub( r'\n?```$', '', cleaned )
    return cleaned.strip()


class CompletionClient( LlmClientInterface ):
    """
    Client for completion-based LLM interactions.
    
    This client provides a unified interface for completion-based models that
    generate text based on prompts without message history. It wraps the
    LlmCompletion class to provide consistent behavior with other LLM clients.
    
    Requires:
        - Valid base_url for the LLM API endpoint
        - Valid model_name compatible with the completion API
        - API key if required by the service
        - TokenCounter for tracking token usage
        
    Ensures:
        - Consistent interface with other LLM clients via run() method
        - Token counting for prompt and completion
        - Performance metrics (tokens/second, duration)
        - Proper environment variable configuration for API access
        - Streaming and non-streaming response options
        - Support for special prompt formats (instruction_completion, special_token)
    """
    
    def __init__( self,
        base_url: str,
        model_name: str,
        prompt_format: str = "",
        api_key: Optional[ str ] = None,
        model_tokenizer_map: Optional[dict[str, str]] = None,
        debug: bool = False,
        verbose: bool = False,
        **generation_args: Any
    ) -> None:
        """
        Initialize a completion-based LLM client.
        
        Requires:
            - base_url: A valid API endpoint URL for completions
            - model_name: A valid model identifier for the service
            - api_key: If required, a valid API key for the service
            
        Ensures:
            - Sets up environment variables for API access
            - Initializes LlmCompletion with the specified configuration
            - Creates TokenCounter for usage tracking
            - Stores generation parameters for use with LLM calls
        """
        # Set environment variables if provided
        if api_key:
            os.environ[ "OPENAI_API_KEY" ] = api_key
        os.environ[ "OPENAI_BASE_URL" ] = base_url
        
        self.base_url        = base_url
        self.model_name      = model_name
        self.prompt_format   = prompt_format
        self.token_counter   = TokenCounter( model_tokenizer_map )
        self.generation_args = generation_args
        self.debug           = debug
        self.verbose         = verbose
        
        # Initialize the LlmCompletion model
        if self.debug and self.verbose:
            du.print_banner( f"Initializing CompletionClient", prepend_nl=True )
            print( f"Model: {model_name}" )
            print( f"Base URL: {base_url}" )
            print( f"Prompt format: '{prompt_format}'" )
        
        self.model = LlmCompletion( 
            base_url=base_url, 
            model_name=model_name, 
            api_key=api_key, 
            **generation_args 
        )
    
    async def _stream_async( self, prompt: str, **generation_args: Any ) -> str:
        """
        Internal method to handle async streaming for completion models.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.model: An initialized LlmCompletion with async streaming capability
            
        Ensures:
            - Streams response chunks from the LLM
            - Displays progress if self.debug is True
            - Collects all chunks into a single response
            
        Returns:
            - Complete response string from the LLM
        """
        output = [ ]
        
        # Note: LlmCompletion may not have the same streaming interface as Agent
        # This would need to be adapted based on the actual LlmCompletion implementation
        async with self.model.run_stream( prompt, **generation_args ) as result:
            counter = 0
            async for chunk in result.stream_text( delta=True ):
                if self.debug and self.verbose:
                    print( chunk, end="", flush=True )
                else:
                    counter += 1
                    if counter % 128 == 0: print()
                    print( ".", end="", flush=True )
                output.append( chunk )
            print()
        return "".join( output )
    
    async def run_async( self, prompt: str, stream: bool = False, **kwargs: Any ) -> str:
        """
        Async version to send a prompt to the completion model and get the response.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.model: An initialized LlmCompletion
            - self.token_counter: An initialized TokenCounter
            
        Ensures:
            - Sends the prompt to the LLM and receives a response
            - Counts tokens for both prompt and completion
            - Measures performance metrics (duration, tokens/sec)
            - Handles both streaming and non-streaming modes
            - Displays performance metrics if verbose
            
        Returns:
            - String response from the LLM
        """
        prompt_tokens = self.token_counter.count_tokens( self.model_name, prompt )
        
        # Update generation arguments
        updated_gen_args = {
            "temperature": kwargs.get( "temperature", self.generation_args.get( "temperature", 0.7 ) ),
            "max_tokens" : kwargs.get( "max_tokens", self.generation_args.get( "max_tokens", 64 ) ),
            "stop"       : kwargs.get( "stop", self.generation_args.get( "stop", None ) ),
            "top_p"      : kwargs.get( "top_p", self.generation_args.get( "top_p", 1.0 ) ),
            "stream"     : stream or self.generation_args.get( "stream", False ),
        }
        
        if not updated_gen_args["stream"]:
            # Non-streaming mode
            start_time = time.perf_counter()
            # Note: LlmCompletion might not have async support yet
            # This may need to be adapted based on the actual implementation
            response = self.model.run( prompt, **updated_gen_args )
            duration = time.perf_counter() - start_time
            
            # Clean the response to remove extraneous backticks
            cleaned_response = clean_llm_response( response )
            
            completion_tokens = self.token_counter.count_tokens( self.model_name, cleaned_response )
            if self.debug and self.verbose:
                self._print_metadata( prompt_tokens, completion_tokens, duration, client_type="Completion" )
            return cleaned_response
        
        # Streaming mode
        if self.debug and self.verbose: print( f"🔄 Streaming from completion model: {self.model_name}\n" )
        start_time = time.perf_counter()
        
        output = await self._stream_async( prompt, **updated_gen_args )
        
        # Clean the response to remove extraneous backticks
        cleaned_output = clean_llm_response( output )
        
        duration = time.perf_counter() - start_time
        completion_tokens = self.token_counter.count_tokens( self.model_name, cleaned_output )
        
        if self.debug and self.verbose:
            self._print_metadata( prompt_tokens, completion_tokens, duration, client_type="Completion" )
        return cleaned_output
    
    def run( self, prompt: str, stream: bool = False, **kwargs: Any ) -> str:
        """
        Send a prompt to the completion model and get the response.
        
        Works in both sync and async contexts by handling event loop management.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            
        Ensures:
            - Works in both sync and async contexts
            - Returns string response from the model
            
        Returns:
            - String response from the LLM
        """
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
            return run_in_new_loop()