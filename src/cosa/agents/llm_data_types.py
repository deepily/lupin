from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, AsyncIterator
from enum import Enum

class MessageRole( Enum ):
    """Enumeration of message roles in conversation."""
    SYSTEM    = "system"
    USER      = "user"
    ASSISTANT = "assistant"

@dataclass
class LlmMessage:
    """
    Single message in a conversation.
    
    Requires:
        - role is a valid MessageRole enum value
        - content is a non-empty string
        
    Ensures:
        - message contains valid role and content
        - metadata is always a dictionary
    """
    role     : MessageRole
    content  : str
    metadata : Dict[str, Any] = field( default_factory=dict )
    
    def __post_init__( self ):
        """Validate message after initialization."""
        if not self.content.strip():
            raise ValueError( "Message content cannot be empty" )

@dataclass
class LlmRequest:
    """
    Standardized request object for LLM completions.
    
    Requires:
        - prompt or messages must be provided (not both)
        - model must be valid model identifier if provided
        - temperature must be between 0.0 and 2.0
        - max_tokens must be positive integer if provided
        - top_p must be between 0.0 and 1.0
        
    Ensures:
        - exactly one of prompt or messages is provided
        - all parameters are within valid ranges
        - metadata is always a dictionary
    """
    
    # Core content (exactly one must be provided)
    prompt   : Optional[str] = None
    messages : Optional[List[LlmMessage]] = None
    
    # Model configuration
    model : Optional[str] = None
    
    # Generation parameters
    temperature        : float = 0.7
    max_tokens         : Optional[int] = None
    top_p              : float = 1.0
    frequency_penalty  : float = 0.0
    presence_penalty   : float = 0.0
    stop               : Optional[List[str]] = None
    
    # Streaming and output control
    stream : bool = False
    
    # Metadata and context
    metadata   : Dict[str, Any] = field( default_factory=dict )
    request_id : Optional[str] = None
    
    def __post_init__( self ):
        """
        Validate request after initialization.
        
        Requires:
            - all parameters have been set
            
        Ensures:
            - validation rules are enforced
            
        Raises:
            - ValueError for invalid parameter combinations or values
        """
        if not self.prompt and not self.messages:
            raise ValueError( "Either prompt or messages must be provided" )
        if self.prompt and self.messages:
            raise ValueError( "Cannot provide both prompt and messages" )
        if self.temperature < 0.0 or self.temperature > 2.0:
            raise ValueError( "Temperature must be between 0.0 and 2.0" )
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError( "max_tokens must be positive" )
        if self.top_p < 0.0 or self.top_p > 1.0:
            raise ValueError( "top_p must be between 0.0 and 1.0" )
        if abs( self.frequency_penalty ) > 2.0:
            raise ValueError( "frequency_penalty must be between -2.0 and 2.0" )
        if abs( self.presence_penalty ) > 2.0:
            raise ValueError( "presence_penalty must be between -2.0 and 2.0" )

@dataclass
class LlmResponse:
    """
    Standardized response object for LLM completions.
    
    Requires:
        - text is the completion text from the model
        - token counts are non-negative integers
        - duration_ms is non-negative float
        
    Ensures:
        - Always contains completion text
        - Includes token usage information
        - Provides timing and performance metrics
        - Contains metadata for debugging and analysis
    """
    
    # Core response
    text : str
    
    # Token usage
    prompt_tokens     : int = 0
    completion_tokens : int = 0
    total_tokens      : int = 0
    
    # Performance metrics
    duration_ms       : float = 0.0
    tokens_per_second : float = 0.0
    
    # Model and provider info
    model    : Optional[str] = None
    provider : Optional[str] = None
    
    # Streaming support
    stream_data : Optional[AsyncIterator[str]] = None
    
    # Cost estimation
    estimated_cost_usd : Optional[float] = None
    
    # Metadata and debugging
    metadata   : Dict[str, Any] = field( default_factory=dict )
    request_id : Optional[str] = None
    
    # API response details
    api_response_headers : Dict[str, str] = field( default_factory=dict )
    finish_reason        : Optional[str] = None
    
    def __post_init__( self ):
        """
        Validate response after initialization.
        
        Ensures:
            - token counts are consistent
            - performance metrics are valid
        """
        if self.prompt_tokens < 0 or self.completion_tokens < 0:
            raise ValueError( "Token counts must be non-negative" )
        if self.duration_ms < 0:
            raise ValueError( "Duration must be non-negative" )
        if self.total_tokens == 0 and ( self.prompt_tokens > 0 or self.completion_tokens > 0 ):
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        if self.duration_ms > 0 and self.completion_tokens > 0:
            self.tokens_per_second = ( self.completion_tokens / self.duration_ms ) * 1000

@dataclass
class LlmStreamChunk:
    """
    Single chunk in a streaming response.
    
    Requires:
        - text is the chunk content (can be empty for metadata chunks)
        - chunk_index is non-negative integer
        
    Ensures:
        - chunk contains text and metadata
        - chunk_index tracks order in stream
    """
    text         : str
    is_final     : bool = False
    chunk_index  : int = 0
    metadata     : Dict[str, Any] = field( default_factory=dict )
    
    def __post_init__( self ):
        """Validate chunk after initialization."""
        if self.chunk_index < 0:
            raise ValueError( "chunk_index must be non-negative" )