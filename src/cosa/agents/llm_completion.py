import os
import asyncio
from typing import Optional, Any, AsyncGenerator

import requests
import json
import aiohttp

import cosa.utils.util as du
from cosa.agents.token_counter import TokenCounter
from cosa.utils.util_stopwatch import Stopwatch

class LlmCompletion:
    """
    Client for interacting with LLM completion APIs.
    
    This class provides a simplified interface for making completion requests
    to LLM APIs that follow the OpenAI-compatible completions format.
    
    Requires:
        - Valid base_url for a completions API endpoint
        - Valid model_name compatible with the API
        - TokenCounter for tracking token usage
        
    Ensures:
        - Makes HTTP requests to the completions API
        - Formats requests according to the completions API spec
        - Processes responses into usable text output
        - Provides performance metrics
    """
    
    def __init__( self,
        base_url: str = "http://192.168.1.21:3000/v1/completions",
        model_name: str = "/mnt/DATA01/include/www.deepily.ai/projects/models/Ministral-8B-Instruct-2410.lora/merged-on-2025-02-12-at-02-05/autoround-4-bits-sym.gptq/2025-02-12-at-02-27",
        api_key: Optional[str] = "EMPTY",
        model_tokenizer_map: Optional[dict[str, str]] = None,
        debug: bool = False,
        verbose: bool = False,
        **generation_args: Any
    ) -> None:
        """
        Initialize a completion API client.
        
        Requires:
            - base_url: A valid URL for an OpenAI-compatible completions API
            - model_name: A valid model name or path
            
        Ensures:
            - Sets up client configuration for API requests
            - Initializes TokenCounter for token counting
            - Stores generation parameters
            
        Args:
            base_url: URL of the completions API endpoint
            model_name: Name or path of the model to use
            api_key: Optional API key for authentication
            model_tokenizer_map: Optional mapping from model to tokenizer names
            debug: Enable debug output
            verbose: Enable verbose output
            **generation_args: Additional arguments for generation
        """
        self.base_url = base_url
        self.model_name = model_name
        self.api_key = api_key
        self.token_counter = TokenCounter( model_tokenizer_map )
        self.generation_args = generation_args
        self.debug = debug
        self.verbose = verbose
        self.generation_args = generation_args

    def run( self, prompt: str, stream: bool=False, **kwargs: Any ) -> str:
        """
        Send a prompt to the LLM and get a completion response.
        
        This method sends a request to the completions API and processes
        the response. It handles timing, token counting, and error handling.
        
        Requires:
            - prompt: A non-empty string to send to the LLM
            - self.base_url: A valid API endpoint URL
            - self.model_name: A valid model name or path
            
        Ensures:
            - Sends a properly formatted request to the completions API
            - Measures performance metrics
            - Processes and returns the response text
            - Provides debug information if enabled
            
        Raises:
            - May raise HTTP exceptions for API errors
            
        Args:
            prompt: The text prompt to send to the LLM
            stream: Whether to stream the response
            **generation_args: Additional arguments for generation
            
        Returns:
            String response from the LLM
        """
        
        headers = {
            'Content-Type' : 'application/json',
            # 'Authorization': f'Bearer {api_key}',
        }
        
        # Request a completion
        data = {
            "model"      : self.model_name,
            "prompt"     : prompt,
            # override the object's generation arguments if they're present in this method's kwargs
            "max_tokens" : kwargs.get( "max_tokens", self.generation_args.get( "max_tokens", 64 ) ),
            "temperature": kwargs.get( "temperature", self.generation_args.get( "temperature", 0.25 ) ),
            "top_p"      : kwargs.get( "top_p", self.generation_args.get( "top_p", 1.0 ) ),
            "stop"       : kwargs.get( "stop", self.generation_args.get( "stop", None ) ),
            "stream"     : stream,
        }
        
        if stream:
            # For streaming, we return a generator that the caller can iterate over
            # This will be used by run_stream
            return self._prepare_streaming_request(prompt, data, headers)
        
        # Non-streaming request
        if self.debug: timer = Stopwatch( msg="Requesting completion..." )
        response = requests.post( self.base_url, headers=headers, data=json.dumps( data ) )
        if self.debug: timer.print( msg="Done!", use_millis=True )
        
        if response.status_code == 200:
            completion = response.json()
            return completion[ 'choices' ][ 0 ][ 'text' ].replace( "```", "" ).strip()
        else:
            print( f"Error: {response.status_code}" )
            raise Exception( f"Error requesting completion: {response.text}" )
            
    def _prepare_streaming_request(self, prompt: str, data: dict[str, Any], headers: dict[str, str]) -> str:
        """
        Prepare a streaming request (stub method for compatibility).
        
        This is just a stub method that returns the prompt back for compatibility
        with the streaming interface. The actual streaming is handled by run_stream.
        
        Requires:
            - prompt is a non-empty string
            - data is a dict with request parameters
            - headers is a dict with HTTP headers
            
        Ensures:
            - Returns the original prompt unchanged
            - Used as a placeholder for the streaming API
            
        Raises:
            - None
        """
        # This method exists for compatibility with the API used by LlmClient
        # The actual streaming implementation is in run_stream
        return prompt
        
    async def _stream_async(self, prompt: str, **generation_args: Any) -> AsyncGenerator[str, None]:
        """
        Stream a completion response asynchronously.
        
        This method sends a streaming request to the completions API and yields
        chunks of the response as they arrive.
        
        Requires:
            - prompt is a non-empty string
            - self.base_url is a valid API endpoint
            - self.model_name is a valid model identifier
            
        Ensures:
            - Sends streaming request to completions API
            - Yields text chunks as they arrive
            - Handles JSON parsing of streamed data
            - Processes Server-Sent Events format
            
        Raises:
            - Exception if API returns non-200 status
            - aiohttp exceptions for network errors
            
        Yields:
            Chunks of the response text
        """
        headers = {
            'Content-Type': 'application/json',
        }
        
        data = {
            "model"      : self.model_name,
            "prompt"     : prompt,
            "max_tokens" : generation_args.get("max_tokens", self.generation_args.get("max_tokens", 64)),
            "temperature": generation_args.get("temperature", self.generation_args.get("temperature", 0.25)),
            "top_p"      : generation_args.get("top_p", self.generation_args.get("top_p", 1.0)),
            "stop"       : generation_args.get("stop", self.generation_args.get("stop", None)),
            "stream"     : True,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.base_url, headers=headers, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Error requesting completion stream: {error_text}")
                
                # Stream the response chunks
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        break
                    
                    if line.startswith("data: "):
                        try:
                            chunk_data = json.loads(line[6:])  # Skip "data: " prefix
                            if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("text", "")
                                if delta:
                                    yield delta
                        except json.JSONDecodeError:
                            # Skip invalid JSON lines
                            continue
    
    def run_stream(self, prompt: str, **generation_args: Any) -> 'CompletionStreamingContext':
        """
        Stream a completion response with a context manager interface.
        
        This method returns a context manager compatible with the async with statement,
        allowing for consistent streaming interface across different model types.
        
        Requires:
            - prompt is a non-empty string
            
        Ensures:
            - Returns CompletionStreamingContext instance
            - Context manager handles async streaming
            - Compatible with async with syntax
            
        Raises:
            - None
            
        Returns:
            A context manager for streaming the response
        """
        # Return a simple context manager that yields a stream_text method
        return CompletionStreamingContext(self, prompt, **generation_args)


class CompletionStreamingContext:
    """
    A context manager for streaming completions.
    
    This class provides a context manager interface for streaming completions,
    compatible with the async with statement.
    """
    
    def __init__(self, client: 'LlmCompletion', prompt: str, **generation_args: Any) -> None:
        """
        Initialize the streaming context.
        
        Requires:
            - client is a valid LlmCompletion instance
            - prompt is a non-empty string
            
        Ensures:
            - Stores client reference
            - Stores prompt and generation args
            
        Raises:
            - None
        """
        self.client = client
        self.prompt = prompt
        self.generation_args = generation_args
        
    async def __aenter__(self) -> 'CompletionStreamingContext':
        """
        Enter the context manager.
        
        Requires:
            - Context manager is properly initialized
            
        Ensures:
            - Returns self for async with usage
            
        Raises:
            - None
        """
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit the context manager.
        
        Requires:
            - Context manager is in use
            
        Ensures:
            - Cleans up any resources (currently none)
            
        Raises:
            - None
        """
        pass
        
    async def stream_text(self, delta: bool=False) -> AsyncGenerator[str, None]:
        """
        Stream the response text.
        
        Requires:
            - self.client has _stream_async method
            - self.prompt is set
            
        Ensures:
            - Yields text chunks from the streaming response
            - Delta parameter is currently ignored (always yields deltas)
            
        Raises:
            - Any exceptions from the underlying streaming method
            
        Yields:
            Chunks of the response text
        """
        async for chunk in self.client._stream_async(self.prompt, **self.generation_args):
            yield chunk


def quick_smoke_test():
    """Quick smoke test to validate LlmCompletion functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "LlmCompletion Smoke Test", prepend_nl=True )
    
    try:
        # Load a prompt template for testing
        template_path = du.get_project_root() + "/src/conf/prompts/agent-router-template-completion.txt"
        prompt_template = du.get_file_as_string( template_path )
        voice_command = "can I please talk to a human?"
        prompt = prompt_template.format( voice_command=voice_command )
        
        print( "Testing LlmCompletion with agent router prompt" )
        llm_completion = LlmCompletion( debug=True, verbose=False )
        print( "✓ LlmCompletion created successfully" )
        
        # Run complete LLM completion workflow
        print( "Running completion..." )
        response = llm_completion.run( prompt )
        print( "✓ Completion execution completed" )
        
        print( f"✓ Response received: {response[:100]}..." if len( response ) > 100 else f"✓ Response: {response}" )
        
        # Test streaming context manager creation
        print( "Testing streaming context creation..." )
        stream_context = llm_completion.run_stream( prompt )
        print( "✓ Streaming context created successfully" )
        
    except Exception as e:
        print( f"✗ Error during completion test: {e}" )
    
    print( "\n✓ LlmCompletion smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()