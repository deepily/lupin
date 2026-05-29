import os
import time
from typing import Optional, Any
import asyncio
import concurrent.futures

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

import cosa.utils.util as du
from cosa.agents.base_llm_client import LlmClientInterface
from cosa.agents.token_counter import TokenCounter


class ChatClient( LlmClientInterface ):
    """
    Client for chat-based LLM interactions using pydantic-ai Agent.
    
    This client provides a unified interface for chat-based models that use
    message history and system prompts. It wraps pydantic-ai's Agent class
    to provide consistent behavior with other LLM clients.
    
    Requires:
        - Valid model_name compatible with pydantic-ai Agent
        - API key if required by the service
        - TokenCounter for tracking token usage
        
    Ensures:
        - Consistent interface with other LLM clients via run() method
        - Token counting for prompt and completion
        - Performance metrics (tokens/second, duration)
        - Proper environment variable configuration for API access
        - Streaming and non-streaming response options
    """
    
    def __init__( self,
        model_name: str,
        api_key: Optional[ str ] = None,
        base_url: Optional[ str ] = None,
        model_tokenizer_map: Optional[dict[str, str]] = None,
        debug: bool = False,
        verbose: bool = False,
        **generation_args: Any
    ) -> None:
        """
        Initialize a chat-based LLM client.
        
        Requires:
            - model_name: A valid model identifier for pydantic-ai
            - api_key: If required, a valid API key for the service
            
        Ensures:
            - Sets up environment variables for API access if needed
            - Initializes Agent with the specified model
            - Creates TokenCounter for usage tracking
            - Stores generation parameters for use with LLM calls
        """
        # Set environment variables if provided
        if api_key:
            os.environ[ "OPENAI_API_KEY" ] = api_key
        if base_url:
            os.environ[ "OPENAI_BASE_URL" ] = base_url
        
        self.model_name      = model_name
        self.token_counter   = TokenCounter( model_tokenizer_map )
        self.generation_args = generation_args
        self.debug           = debug
        self.verbose         = verbose
        
        # Initialize the Agent with the model
        if self.debug:
            du.print_banner( f"Initializing ChatClient with model: {model_name}" )

        # Wrap generation parameters in ModelSettings for pydantic_ai API
        model_settings = ModelSettings( **generation_args )
        self.model = Agent( model_name, model_settings=model_settings )
    
    async def _stream_async( self, prompt: str, **generation_args: Any ) -> str:
        """
        Internal method to handle async streaming for chat models.

        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.model: An initialized Agent with async streaming capability

        Ensures:
            - Streams response chunks from the LLM
            - Displays progress if self.debug is True
            - Collects all chunks into a single response

        Returns:
            - Complete response string from the LLM
        """
        output = [ ]

        # Wrap generation parameters in ModelSettings for pydantic_ai API
        runtime_settings = ModelSettings( **generation_args )
        async with self.model.run_stream( prompt, model_settings=runtime_settings ) as result:
            counter = 0
            async for chunk in result.stream_text( delta=True ):
                if self.debug and self.verbose:
                    print( chunk, end="", flush=True )
                else:
                    counter += 1
                    if counter % 128 == 0: print()
                    print( ".", end="", flush=True )
                output.append( chunk )

        return "".join( output )
    
    async def run_async( self, prompt: str, stream: bool = False, **kwargs: Any ) -> str:
        """
        Async version to send a prompt to the chat model and get the response.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.model: An initialized Agent with async run capability
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
            "max_tokens" : kwargs.get( "max_tokens", self.generation_args.get( "max_tokens", 1024 ) ),
            "stop"       : kwargs.get( "stop", self.generation_args.get( "stop", None ) ),
            "top_p"      : kwargs.get( "top_p", self.generation_args.get( "top_p", 1.0 ) ),
            "stream"     : stream or self.generation_args.get( "stream", False ),
        }
        
        if not updated_gen_args["stream"]:
            # Non-streaming mode
            start_time = time.perf_counter()
            # Wrap generation parameters in ModelSettings for pydantic_ai API
            runtime_settings = ModelSettings( **updated_gen_args )
            response = await self.model.run( prompt, model_settings=runtime_settings )
            response = response.output
            duration = time.perf_counter() - start_time

            completion_tokens = self.token_counter.count_tokens( self.model_name, response )
            if self.debug and self.verbose:
                self._print_metadata( prompt_tokens, completion_tokens, duration, client_type="Chat" )
            return response
        
        # Streaming mode
        if self.debug and self.verbose: print( f"🔄 Streaming from chat model: {self.model_name}\n" )
        start_time = time.perf_counter()
        
        output = await self._stream_async( prompt, **updated_gen_args )
        
        duration = time.perf_counter() - start_time
        completion_tokens = self.token_counter.count_tokens( self.model_name, output )
        
        if self.debug and self.verbose:
            self._print_metadata( prompt_tokens, completion_tokens, duration, client_type="Chat" )
        return output
    
    def run( self, prompt: str, stream: bool = False, **kwargs: Any ) -> str:
        """
        Send a prompt to the chat model and get the response.
        
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