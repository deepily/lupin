from typing import Optional

from pydantic_ai.models.openai import OpenAIModel  # New import


class TokenCounter:
    """
    Utility for counting tokens in prompts and responses.
    
    This class provides methods to count tokens for different LLM models,
    with support for both OpenAI-compatible and custom tokenizers.
    It handles fallback strategies when specific tokenizers are not available.
    
    Requires:
        - tiktoken package available (optional, falls back to approximation)
        - Valid model names or mappings to tokenizer identifiers
        
    Ensures:
        - Accurate token counting for supported models
        - Graceful fallback for unsupported models
        - Consistent interface regardless of underlying tokenizer
        
    TODO:
        - Improve token counting accuracy for non-OpenAI models
        - Add caching for better performance
        - Support custom tokenizers beyond tiktoken
        - Add comprehensive model-to-tokenizer mappings
        - Add validation for token count limits per model
    """
    
    def __init__( self, model_tokenizer_map: Optional[dict[str, str]] = None ) -> None:
        """
        Initialize the token counter with a mapping from model names to tokenizer identifiers.

        Requires:
            - model_tokenizer_map (optional): Dictionary mapping model names to tokenizer identifiers
              If provided, keys should be model names and values should be valid tokenizer identifiers
              
        Ensures:
            - Sets up tiktoken if available
            - Initializes model_tokenizer_map (empty dict if none provided)
            - Provides warning if tiktoken is not available
            
        Args:
            model_tokenizer_map: Optional dictionary mapping model names to tokenizer identifiers.
                                If None, tiktoken's default mapping will be used.
        """
        self.model_tokenizer_map = model_tokenizer_map or { }
        # Import here to avoid requiring tiktoken for all users
        try:
            import tiktoken
            self.tiktoken = tiktoken
        except ImportError:
            print( "Warning: tiktoken not installed. Token counting will be approximate." )
            self.tiktoken = None
    
    def count_tokens( self, model_name: str, text: str ) -> int:
        """
        Count the number of tokens in the given text for the specified model.
        
        This method attempts to use the appropriate tokenizer for the given model,
        with fallback mechanisms if the ideal tokenizer is not available.
        
        Requires:
            - model_name: A string identifying the model to count tokens for
            - text: A string containing the text to tokenize
            
        Ensures:
            - Returns a positive integer count of tokens
            - Uses the most accurate available tokenizer for the model
            - Falls back to approximation if needed
            
        Raises:
            - May print warnings but will not raise exceptions
            
        Returns:
            - Integer representing the token count

        Args:
            model_name: Name of the model to count tokens for
            text: Text to count tokens in

        Returns:
            Number of tokens in the text
        """
        if not self.tiktoken:
            # Fallback if tiktoken not available: estimate 4 chars per token
            return len( text ) // 4
        
        try:
            # Map the model name to a tokenizer if needed
            tokenizer_name = self.model_tokenizer_map.get( model_name, model_name )
            
            try:
                # Try to get the encoding for the model directly
                encoding = self.tiktoken.encoding_for_model( tokenizer_name )
            except KeyError:
                # Fallback to cl100k_base for newer models not in tiktoken
                encoding = self.tiktoken.get_encoding( "cl100k_base" )
            
            # Count the tokens
            return len( encoding.encode( text ) )
        
        except Exception as e:
            print( f"Error counting tokens: {e}" )
            # Fallback to character-based estimation
            return len( text ) // 4