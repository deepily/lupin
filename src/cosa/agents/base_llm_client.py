from abc import ABC, abstractmethod
from typing import Optional, Any
import asyncio

import cosa.utils.util as du


def format_duration_ms( seconds: float ) -> str:
    """
    Format a duration in seconds as whole milliseconds.

    Requires:
        - seconds is a number

    Ensures:
        - returns a string such as "1500ms"
        - the fraction of a millisecond is cut, not rounded
    """
    return f"{int( seconds * 1000 )}ms"


async def collect_stream_text( stream_context, debug, verbose, newline_after=False ):
    """
    Join the text deltas of one streamed model reply, showing progress as they arrive.

    Requires:
        - stream_context is an async context manager whose result has stream_text( delta=True )
        - debug and verbose are booleans

    Ensures:
        - returns the deltas joined in arrival order
        - with debug and verbose, each delta is echoed as it arrives
        - otherwise prints one dot per delta, and a line break after every 128th
        - with newline_after, one more line break is printed once the stream ends
    """
    output = [ ]
    async with stream_context as result:
        counter = 0
        async for chunk in result.stream_text( delta=True ):
            if debug and verbose:
                print( chunk, end="", flush=True )
            else:
                counter += 1
                if counter % 128 == 0: print()
                print( ".", end="", flush=True )
            output.append( chunk )
    if newline_after: print()
    return "".join( output )


class LlmClientInterface( ABC ):
    """
    Common interface for all LLM client implementations.
    
    This interface ensures all clients provide a consistent run() method
    that can be used interchangeably regardless of whether they use
    chat or completion APIs.
    
    Requires:
        - Subclasses must implement run() and run_async() methods
        
    Ensures:
        - Consistent interface across ChatClient and CompletionClient
        - Both sync and async support
        - Stream support in both modes
    """
    
    @abstractmethod
    async def run_async( self, prompt: str, stream: bool = False, **kwargs: Any ) -> str:
        """
        Async method to send a prompt and get response.
        
        Requires:
            - prompt is a non-empty string
            - stream is a boolean value
            
        Ensures:
            - returns string response from the model
            - handles streaming if requested
            
        Raises:
            - LlmError for client-specific errors
            - LlmAPIError for API communication errors
        """
        pass
    
    @abstractmethod
    def run( self, prompt: str, stream: bool = False, **kwargs: Any ) -> str:
        """
        Synchronous method to send a prompt and get response.
        
        Requires:
            - prompt is a non-empty string
            - stream is a boolean value
            
        Ensures:
            - returns string response from the model
            - handles streaming if requested
            - works in both sync and async contexts
            
        Raises:
            - LlmError for client-specific errors
            - LlmAPIError for API communication errors
        """
        pass
    
    def _print_metadata( self, prompt_tokens: int, completion_tokens: int, duration: Optional[ float ], client_type: str = "LLM" ):
        """
        Print performance metadata about an LLM request.
        
        Requires:
            - prompt_tokens: Number of tokens in the prompt
            - completion_tokens: Number of tokens in the completion
            - duration: Time taken for the request (optional)
            - client_type: Type of client for display (e.g., "Chat", "Completion")
            
        Ensures:
            - Prints formatted performance metrics
            - Calculates tokens per second
            - Handles missing duration gracefully
        """
        total_tokens = prompt_tokens + completion_tokens
        tps = completion_tokens / duration if ( duration and duration > 0 ) else float( 'inf' )
        duration_str = format_duration_ms( duration ) if duration is not None else "N/A"
        
        du.print_banner( f"📊 {client_type} Summary", prepend_nl=True )
        print( f"🧠 Model              : {self.model_name}" )
        print( f"⏱️ Duration           : {duration_str}" )
        print( f"🔢 Prompt tokens      : {prompt_tokens}" )
        print( f"💬 Completion tokens  : {completion_tokens}" )
        print( f"🧮 Total tokens       : {total_tokens}" )
        print( f"⚡ Tokens/sec         : {tps:.2f}" )
        print( "=" * 40 )


class BaseLlmClient( ABC ):
    """
    Abstract base class for all LLM clients.
    
    Requires:
        - Subclasses must implement complete() method
        - Client must be configured with valid model and credentials
        
    Ensures:
        - Consistent interface across all LLM providers
        - Both async and sync support
        - Standardized request/response objects
        
    Raises:
        - LlmError for client-specific errors
        - LlmAPIError for API communication errors
    """
    
    def __init__( self, model: str, debug: bool = False, verbose: bool = False ):
        """
        Initialize base LLM client.
        
        Requires:
            - model is a valid model identifier string
            - debug and verbose are boolean values
            
        Ensures:
            - client is initialized with provided parameters
            - _initialized flag is set to False
        """
        self.model        = model
        self.debug        = debug
        self.verbose      = verbose
        self._initialized = False
    
    @abstractmethod
    async def complete( self, request: 'LlmRequest' ) -> 'LlmResponse':
        """
        Generate completion for the given request.
        
        Requires:
            - request is a valid LlmRequest object
            - client is properly configured
            
        Ensures:
            - returns LlmResponse with completion text
            - response includes token counts and metadata
            - handles streaming if requested
            
        Raises:
            - LlmError for client-specific errors
            - LlmAPIError for API communication errors
            - LlmTimeoutError for timeout errors
        """
        pass
    
    def complete_sync( self, request: 'LlmRequest' ) -> 'LlmResponse':
        """
        Synchronous wrapper for complete() method.
        
        Requires:
            - request is a valid LlmRequest object
            
        Ensures:
            - returns same result as complete()
            - handles async-to-sync conversion properly
            
        Raises:
            - Same exceptions as complete()
            - RuntimeError if event loop cannot be created
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop( loop )
        
        return loop.run_until_complete( self.complete( request ) )
    
    @abstractmethod
    async def validate_config( self ) -> bool:
        """
        Validate client configuration.
        
        Requires:
            - client has been initialized
            
        Ensures:
            - returns True if configuration is valid
            - raises LlmConfigError if invalid
            
        Raises:
            - LlmConfigError if configuration is invalid
        """
        pass
    
    @abstractmethod
    def get_supported_parameters( self ) -> set[str]:
        """
        Get list of parameters supported by this client.
        
        Requires:
            - client has been initialized
            
        Ensures:
            - returns set of parameter names
            - includes standard parameters (temperature, max_tokens, etc.)
        """
        pass
    
    def __str__( self ) -> str:
        """String representation of the client."""
        return f"{self.__class__.__name__}(model={self.model})"
    
    def __repr__( self ) -> str:
        """Detailed string representation of the client."""
        return f"{self.__class__.__name__}(model='{self.model}', debug={self.debug}, verbose={self.verbose})"