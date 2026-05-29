from typing import Optional, Dict, Any

class LlmError( Exception ):
    """
    Base exception for all LLM client errors.
    
    Requires:
        - message is a descriptive error message
        - error_code is optional error identifier
        - metadata is optional additional context
        
    Ensures:
        - exception includes message and optional context
        - metadata is always a dictionary
    """
    
    def __init__( self, message: str, error_code: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None ):
        """
        Initialize LLM error.
        
        Requires:
            - message is non-empty string
            
        Ensures:
            - error is properly initialized with message and context
        """
        super().__init__( message )
        self.error_code = error_code
        self.metadata   = metadata or {}

class LlmConfigError( LlmError ):
    """
    Configuration-related errors.
    
    Used for:
        - Invalid model configurations
        - Missing required configuration parameters
        - Invalid parameter values in configuration
    """
    pass

class LlmAPIError( LlmError ):
    """
    API communication errors.
    
    Requires:
        - message describes the API error
        - status_code is HTTP status if available
        - response_body is API response if available
        
    Ensures:
        - error includes API-specific context
    """
    
    def __init__( self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None, **kwargs ):
        """
        Initialize API error with HTTP context.
        
        Requires:
            - message is descriptive error message
            - status_code is valid HTTP status code if provided
            
        Ensures:
            - error includes HTTP status and response context
        """
        super().__init__( message, **kwargs )
        self.status_code   = status_code
        self.response_body = response_body

class LlmTimeoutError( LlmError ):
    """
    Timeout errors.
    
    Used for:
        - Request timeouts
        - Connection timeouts
        - Read timeouts
    """
    pass

class LlmAuthenticationError( LlmAPIError ):
    """
    Authentication/authorization errors.
    
    Used for:
        - Invalid API keys
        - Expired tokens
        - Insufficient permissions
    """
    pass

class LlmRateLimitError( LlmAPIError ):
    """
    Rate limiting errors.
    
    Requires:
        - message describes the rate limit error
        - retry_after is seconds to wait if provided by API
        
    Ensures:
        - error includes retry timing information
    """
    
    def __init__( self, message: str, retry_after: Optional[int] = None, **kwargs ):
        """
        Initialize rate limit error with retry timing.
        
        Requires:
            - message describes the rate limit
            - retry_after is positive integer if provided
            
        Ensures:
            - error includes retry timing context
        """
        super().__init__( message, **kwargs )
        self.retry_after = retry_after

class LlmModelError( LlmError ):
    """
    Model-specific errors.
    
    Used for:
        - Unsupported model parameters
        - Model not found
        - Model capacity exceeded
        - Invalid model responses
    """
    pass

class LlmStreamingError( LlmError ):
    """
    Streaming-related errors.
    
    Used for:
        - Stream connection failures
        - Invalid stream data
        - Stream parsing errors
        - Incomplete streams
    """
    pass

class LlmValidationError( LlmError ):
    """
    Request/response validation errors.
    
    Used for:
        - Invalid request parameters
        - Malformed requests
        - Response validation failures
    """
    pass