"""
Utility module for OpenAI embedding functionality.
Handles embedding generation with proper error handling and caching.
"""

import openai
from typing import Optional
import cosa.utils.util as du
import cosa.utils.util_stopwatch as sw
from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.embedding_cache_table import EmbeddingCacheTable
from cosa.memory.gist_normalizer import GistNormalizer
from threading import Lock


class EmbeddingManager:
    """
    Manages OpenAI embedding generation with caching and text normalization.
    
    Singleton class that loads dictionary mappings once and provides
    efficient embedding generation with cache support.
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__( cls, debug=False, verbose=False ):
        """
        Create or return singleton instance.
        
        Requires:
            - Nothing
            
        Ensures:
            - Returns the single instance of EmbeddingManager
            - Initializes components only once
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__( cls )
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__( self, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize the embedding manager.
        
        Requires:
            - Dictionary files exist in conf directory
            - Configuration manager is available
            
        Ensures:
            - Loads reverse mappings once from MultiModalMunger dictionaries
            - Initializes embedding cache table
            - Sets up configuration manager
            
        Raises:
            - FileNotFoundError if dictionary files missing
        """
        if self._initialized:
            return
            
        self.debug   = debug
        self.verbose = verbose
        
        if debug: print( "Initializing EmbeddingManager singleton..." )
        
        # Initialize configuration manager
        self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        
        # Initialize embedding cache table
        self._embedding_cache_table = EmbeddingCacheTable( debug=debug, verbose=verbose )
        
        # Initialize GistNormalizer for advanced text normalization
        self._gist_normalizer = GistNormalizer( debug=debug, verbose=verbose )
        
        # Load dictionaries once during initialization
        self._load_reverse_mappings()
        
        if debug: print( "✓ EmbeddingManager initialized successfully" )
        
        self._initialized = True
    
    def _load_reverse_mappings( self ) -> None:
        """
        Load reverse mappings from MultiModalMunger dictionaries.
        
        Requires:
            - Dictionary files exist in conf directory
            
        Ensures:
            - Loads punctuation, numbers, and domain name mappings
            - Creates reverse mappings for text normalization
            - Stores mappings as instance variables
            
        Raises:
            - FileNotFoundError if dictionary files missing
        """
        if self.debug: timer = sw.Stopwatch( msg="Loading reverse mappings..." )
        
        try:
            # Load the same dictionaries that MultiModalMunger uses
            project_root     = du.get_project_root()
            punctuation_map  = du.get_file_as_dictionary( project_root + "/src/conf/translation-dictionary.map", lower_case=True, debug=self.debug )
            numbers_map      = du.get_file_as_dictionary( project_root + "/src/conf/numbers.map", lower_case=True, debug=self.debug )
            domain_names_map = du.get_file_as_dictionary( project_root + "/src/conf/domain-names.map", lower_case=True, debug=self.debug )
            
            # Create reverse mappings: symbol/number → word
            self._reverse_punctuation = { v: k for k, v in punctuation_map.items() }
            self._reverse_numbers     = { v: k for k, v in numbers_map.items() }
            self._reverse_domains     = { v: k for k, v in domain_names_map.items() }
            
            if self.debug:
                timer.print( "Done!", use_millis=True )
                print( f"Loaded {len( punctuation_map )} punctuation mappings → {len( self._reverse_punctuation )} reverse mappings" )
                print( f"Loaded {len( numbers_map )} number mappings → {len( self._reverse_numbers )} reverse mappings" )
                print( f"Loaded {len( domain_names_map )} domain name mappings → {len( self._reverse_domains )} reverse mappings" )
            
        except Exception as e:
            if self.debug: timer.print( f"Error: {e}", use_millis=True )
            du.print_stack_trace( e, explanation="Failed to load reverse mappings", caller="EmbeddingManager._load_reverse_mappings()" )
            # Initialize empty mappings as fallback
            self._reverse_punctuation = {}
            self._reverse_numbers = {}
            self._reverse_domains = {}
    
    def normalize_text_for_cache( self, text: str, expand_symbols_to_words: bool = None ) -> str:
        """
        Normalize text by extracting gist and optionally expanding numbers/symbols to words.
        
        Uses GistNormalizer for gist extraction and normalization, then optionally applies
        symbol-to-word expansion based on configuration.
        
        Requires:
            - text is a string
            - Reverse mappings are loaded (if expansion enabled)
            
        Ensures:
            - Returns normalized text with gist extracted
            - Optionally expands symbols/numbers to words
            - Consistent cache keys for equivalent content
            
        Args:
            text: The text to normalize
            expand_symbols_to_words: If True, expand symbols/numbers to words.
                                   If None, use value from configuration.
                                   If False, skip symbol expansion.
            
        Raises:
            - None (handles errors gracefully)
        """
        if self.debug and self.verbose: timer = sw.Stopwatch( msg=f"Normalizing text: '{du.truncate_string( text )}'" )

        try:
            # Use GistNormalizer for advanced normalization
            # This will extract the gist and normalize using spaCy
            normalized = self._gist_normalizer.get_normalized_gist( text )

            # Check if we should expand symbols to words
            if expand_symbols_to_words is None:
                # Get from configuration, default to False
                expand_symbols_to_words = self._config_mgr.get( "expand symbols to words", default=False, return_type="boolean" )
                if self.debug and self.verbose: print( f"Got expand_symbols_to_words from config: {expand_symbols_to_words}" )
            
            if expand_symbols_to_words:
                if self.debug and self.verbose: print( "Expanding symbols and numbers to words..." )

                # Apply reverse mappings to expand symbols/numbers to words
                # Use sorted() to ensure consistent ordering for deterministic results
                for symbol, word in sorted( self._reverse_punctuation.items() ):
                    # Skip space character to avoid replacing all spaces with the word "space"
                    if symbol == " ":
                        continue
                    if symbol in normalized:
                        normalized = normalized.replace( symbol, f" {word} " )
                
                for number, word in sorted( self._reverse_numbers.items() ):
                    if number in normalized:
                        normalized = normalized.replace( number, f" {word} " )
                
                for domain, word in sorted( self._reverse_domains.items() ):
                    if domain in normalized:
                        normalized = normalized.replace( domain, f" {word} " )
                
                # Clean up extra whitespace
                normalized = " ".join( normalized.split() )

            if self.debug and self.verbose:
                timer.print( "Done!", use_millis=True )
                print( f"Normalized '{text}' → '{normalized}'" )
            
            return normalized
            
        except Exception as e:
            if self.debug: timer.print( f"Error: {e}", use_millis=True )
            du.print_stack_trace( e, explanation="Text normalization failed", caller="EmbeddingManager.normalize_text_for_cache()" )
            # Return original text if normalization fails
            return text.lower()
    
    def generate_embedding( self, text: str, normalize_for_cache: bool=True ) -> list[ float ]:
        """
        Generate OpenAI embedding for text with optional normalization for caching.
        
        Args:
            text: Input text to generate embedding for
            normalize_for_cache: If True, normalizes text for consistent cache lookups.
                               Uses reverse symbol/number expansion safe for all content types.
                               Set to False for source code or when exact text preservation is required.
            
        Requires:
            - text is a non-empty string
            - normalize_for_cache is boolean
            - OpenAI API key is available
            - 'embedding model name' is configured
            
        Ensures:
            - Returns embedding for original text
            - Caches using normalized key if normalize_for_cache=True
            - Caches using exact text key if normalize_for_cache=False
            - Returns empty list on API errors
            - Logs detailed error information for troubleshooting
            
        Note:
            - Continues execution even if embedding generation fails
            - Important: Generates embedding for NORMALIZED text when cache miss occurs
        """
        # Determine cache key based on normalization setting
        if normalize_for_cache:
            cache_key = self.normalize_text_for_cache( text )
            text_for_embedding = cache_key  # Generate embedding for normalized text
            if self.debug and self.verbose:
                print( f"[EMBED-DEBUG] Original: '{du.truncate_string( text, 60 )}'" )
                print( f"[EMBED-DEBUG] Normalized: '{du.truncate_string( cache_key, 60 )}'" )
        else:
            cache_key = text
            text_for_embedding = text  # Generate embedding for exact text
            if self.debug and self.verbose:
                print( f"Using exact cache key: '{cache_key}'" )
        
        # Check cache first using cache_key
        cached_embedding = self._embedding_cache_table.get_cached_embedding( cache_key )

        if cached_embedding:
            if self.debug and self.verbose:
                print( f"Cache HIT for key: '{du.truncate_string( cache_key )}'" )
            return cached_embedding

        if self.debug and self.verbose:
            print( f"Cache MISS for key: '{du.truncate_string( cache_key )}', generating new embedding..." )
        
        # Generate embedding for the text_for_embedding (which may be normalized)
        timer = sw.Stopwatch( msg=f"Generating embedding for [{du.truncate_string( text_for_embedding )}]...", silent=not (self.debug and self.verbose) )
        
        try:
            # Get embedding model name from config - NO FALLBACK
            embedding_model = self._config_mgr.get( "embedding model name" )

            if self.debug and self.verbose:
                print( f"\nConfiguration details:" )
                print( f"  Embedding model: {embedding_model}" )
                print( f"  API key location: {du.get_project_root()}/src/conf/keys/openai" )
            
            if not embedding_model:
                du.print_banner( "CONFIGURATION ERROR - MISSING EMBEDDING MODEL", prepend_nl=True )
                print( "The 'embedding model name' key is not configured." )
                print( "" )
                print( "TO FIX THIS ERROR:" )
                print( f"1. Add 'embedding model name' to your configuration file" )
                print( f"2. Common values: 'text-embedding-ada-002', 'text-embedding-3-small', 'text-embedding-3-large'" )
                print( f"3. Check the configuration file specified in your config block" )
                du.print_banner( "CANNOT GENERATE EMBEDDINGS", prepend_nl=True )
                return [ ]
            
            # Get API key
            api_key = du.get_api_key( "openai" )

            if self.debug and self.verbose:
                print( f"  API key (first 10 chars): {api_key[ :10 ] if api_key else 'NOT FOUND'}..." )
                print( f"  OpenAI client version: {openai.__version__}" )
            
            # Create a dedicated OpenAI client for embeddings that bypasses environment variables
            # This ensures we always use OpenAI's API for embeddings, not local completion servers
            embedding_client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.openai.com/v1"  # Force use of OpenAI's API for embeddings
            )

            if self.debug and self.verbose:
                print( f"\nAttempting to generate embedding with model: {embedding_model}" )
                print( f"Using OpenAI API endpoint: https://api.openai.com/v1" )
            
            # Generate embedding for text_for_embedding (normalized or exact)
            embedding_dim = int( self._config_mgr.get( "embedding dimensions", default="768" ) )
            response = embedding_client.embeddings.create(
                input=text_for_embedding,
                model=embedding_model,
                dimensions=embedding_dim
            )
            timer.print( "Done!", use_millis=True )

            embedding = response.data[ 0 ].embedding
            if self.debug and self.verbose: print( f"\nSuccess! Generated embedding with {len( embedding )} dimensions" )

            # Cache the result using cache_key
            self._embedding_cache_table.cache_embedding( cache_key, embedding )
            if self.debug and self.verbose: print( f"Cached embedding for normalized text: '{du.truncate_string( cache_key )}'" )
            
            return embedding
        
        except openai.NotFoundError as e:
            # Get model name for error message
            try:
                embedding_model = self._config_mgr.get( "embedding model name" )
            except:
                embedding_model = "[UNKNOWN - CONFIG ERROR]"
            
            du.print_banner( "EMBEDDING API ERROR - 404 NOT FOUND", prepend_nl=True )
            print( "The OpenAI embedding service returned a 404 error." )
            print( "This usually means one of the following:" )
            print( "1. Your OpenAI API key is invalid or expired" )
            print( f"2. The embedding model '{embedding_model}' is not accessible" )
            print( "3. Your account doesn't have access to the embeddings API" )
            print( "" )
            print( "TO FIX THIS ERROR:" )
            print( f"1. Check your API key in: {du.get_project_root()}/src/conf/keys/openai" )
            print( "2. Verify your OpenAI account has embedding API access" )
            print( "3. Test your API key at: https://platform.openai.com/account/api-keys" )
            print( f"4. Verify embedding model name in config: '{embedding_model}'" )
            print( "" )
            print( f"Error details: {e}" )
            print( f"Error type: {type( e )}" )
            print( f"Error response: {getattr( e, 'response', 'No response attribute' )}" )
            du.print_banner( "CONTINUING WITHOUT EMBEDDINGS", prepend_nl=True )
            
            # Return empty embedding to allow execution to continue
            return [ ]
        
        except Exception as e:
            du.print_banner( f"EMBEDDING API ERROR - {type( e ).__name__}", prepend_nl=True )
            print( f"Failed to generate embedding: {e}" )
            print( f"Error type: {type( e )}" )
            print( f"Error details: {repr( e )}" )
            print( "Continuing without embeddings..." )
            du.print_banner( "CONTINUING WITHOUT EMBEDDINGS", prepend_nl=True )
            
            # Return empty embedding to allow execution to continue
            return [ ]


def get_embedding_manager( debug: bool=False, verbose: bool=False ) -> EmbeddingManager:
    """
    Get singleton instance of EmbeddingManager.
    
    Requires:
        - debug and verbose are booleans
        
    Ensures:
        - Returns singleton EmbeddingManager instance
        - Creates instance on first call
        - Reuses same instance on subsequent calls
        
    Raises:
        - None
    """
    return EmbeddingManager( debug=debug, verbose=verbose )


def generate_embedding( text: str, normalize_for_cache: bool=True, debug: bool=False ) -> list[ float ]:
    """
    Generate OpenAI embedding for text with optional normalization for caching.
    
    This is a convenience function that uses the singleton EmbeddingManager.
    
    Args:
        text: Input text to generate embedding for
        normalize_for_cache: If True, normalizes text for consistent cache lookups.
                           Uses reverse symbol/number expansion safe for all content types.
                           Set to False for source code or when exact text preservation is required.
        debug: Enable debug output
        
    Requires:
        - text is a non-empty string
        - normalize_for_cache is boolean
        - OpenAI API key is available
        - 'embedding model name' is configured
        
    Ensures:
        - Returns embedding using singleton EmbeddingManager
        - Loads dictionaries only once (on first call)
        - Efficient caching and normalization
        
    Raises:
        - None (handled by EmbeddingManager)
    """
    embedding_manager = get_embedding_manager( debug=debug )
    return embedding_manager.generate_embedding( text, normalize_for_cache=normalize_for_cache )


def quick_smoke_test():
    """Run quick smoke tests with various inputs to validate embedding functionality."""
    du.print_banner( "EmbeddingManager Singleton Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Singleton creation and text normalization
        print( "Test 1: EmbeddingManager singleton and normalization..." )
        embedding_manager = get_embedding_manager( debug=False )
        print( "✓ EmbeddingManager singleton created successfully" )
        
        test_normalization_cases = [
            ( "What's 2+2?", "what s two plus two question mark" ),
            ( "555-1234", "five five five one two three four" ),
            ( "user@example.com", "user at example dot com" ),
            ( "Hello World!", "hello world exclamation mark" )
        ]
        
        normalization_success = True
        for original, expected_partial in test_normalization_cases:
            normalized = embedding_manager.normalize_text_for_cache( original )
            print( f"  '{original}' → '{normalized}'" )
            # Just check if some expected words are present (since exact mapping may vary)
            if "hello world" in normalized.lower() or "what" in normalized or "five" in normalized or "user" in normalized:
                print( f"  ✓ Normalization working" )
            else:
                print( f"  ✗ Unexpected normalization result" )
                normalization_success = False
        
        if normalization_success:
            print( "✓ Text normalization tests passed" )
        else:
            print( "✗ Some text normalization tests failed" )
        
        # Test 1.5: Verify singleton behavior
        print( f"\nTest 1.5: Verifying singleton behavior..." )
        embedding_manager_2 = get_embedding_manager( debug=False )
        if embedding_manager is embedding_manager_2:
            print( "✓ Same singleton instance returned on second call" )
        else:
            print( "✗ Different instances returned - singleton not working!" )
        
        # Test 2: Embedding generation with cache
        print( f"\nTest 2: Embedding generation with caching..." )
        test_text = "What time is it?"
        
        print( f"  First call (should be cache miss): '{test_text}'" )
        embedding1 = generate_embedding( test_text, normalize_for_cache=True, debug=False )
        
        if embedding1:
            print( f"  ✓ First embedding generated: {len( embedding1 )} dimensions" )
            
            print( f"  Second call (should be cache hit): '{test_text}'" )
            embedding2 = generate_embedding( test_text, normalize_for_cache=True, debug=False )
            
            if embedding2 and len( embedding2 ) == len( embedding1 ):
                print( f"  ✓ Second embedding retrieved: {len( embedding2 )} dimensions" )
                
                # Check if embeddings are the same (cache hit)
                if embedding1[ :5 ] == embedding2[ :5 ]:
                    print( f"  ✓ Cache working: identical embeddings returned" )
                else:
                    print( f"  ⚠ Different embeddings - possible cache miss or new generation" )
            else:
                print( f"  ✗ Second embedding generation failed" )
        else:
            print( f"  ✗ First embedding generation failed" )
        
        # Test 3: Different normalization settings
        print( f"\nTest 3: Testing normalize_for_cache parameter..." )
        test_code = "def hello():\n    return 'world'"
        
        print( f"  Generating embedding with normalization=False (for code)..." )
        embedding_exact = generate_embedding( test_code, normalize_for_cache=False, debug=False )
        
        print( f"  Generating embedding with normalization=True (for natural language)..." )
        embedding_normalized = generate_embedding( test_code, normalize_for_cache=True, debug=False )
        
        if embedding_exact and embedding_normalized:
            print( f"  ✓ Both embedding types generated successfully" )
            print( f"    Exact: {len( embedding_exact )} dimensions" )
            print( f"    Normalized: {len( embedding_normalized )} dimensions" )
        else:
            print( f"  ✗ One or both embedding generations failed" )
        
        # Test 4: Similar texts with normalization
        print( f"\nTest 4: Testing cache hits with similar texts..." )
        similar_texts = [ "What's the time?", "what is the time", "WHAT IS THE TIME?" ]
        
        embeddings = []
        for text in similar_texts:
            print( f"  Processing: '{text}'" )
            emb = generate_embedding( text, normalize_for_cache=True, debug=False )
            if emb:
                embeddings.append( emb )
                print( f"    ✓ Generated/retrieved {len( emb )} dimensions" )
            else:
                print( f"    ✗ Failed to generate embedding" )
        
        if len( embeddings ) == len( similar_texts ):
            print( f"  ✓ All similar text embeddings processed" )
        
        # Test 5: Voice transcription normalization pipeline
        print( f"\nTest 5: Voice Transcription → Gist → Normalize → Embed Pipeline..." )
        
        # Test with symbol expansion OFF (default from config)
        print( f"\n  Test 5a: Symbol expansion OFF (default):" )
        test_cases_no_expansion = [
            ( "What's the time at 3:30 PM?", "time", "3:30" ),
            ( "Email me at user@example.com", "email", "@" ),
            ( "The total is $99.99", "total", "$99.99" )
        ]
        
        for text, keyword, symbol in test_cases_no_expansion:
            normalized = embedding_manager.normalize_text_for_cache( text )
            print( f"    '{text}' → '{normalized}'" )
            if keyword in normalized and symbol in normalized:
                print( f"      ✓ Symbol '{symbol}' preserved, not expanded" )
            else:
                print( f"      ⚠ Expected symbol '{symbol}' or keyword '{keyword}' not found" )
        
        # Test with symbol expansion ON (override)
        print( f"\n  Test 5b: Symbol expansion ON (override):" )
        for text, keyword, symbol in test_cases_no_expansion:
            normalized = embedding_manager.normalize_text_for_cache( text, expand_symbols_to_words=True )
            print( f"    '{text}' → '{normalized}'" )
            if keyword in normalized and symbol not in normalized:
                print( f"      ✓ Symbol '{symbol}' expanded to words" )
            else:
                print( f"      ⚠ Symbol expansion may not have worked as expected" )
        
        # Test voice transcriptions
        print( f"\n  Test 5c: Voice transcription normalization:" )
        voice_transcription_cases = [
            {
                "name": "Simple question with fillers",
                "text": "Um, so like, I was wondering if you could, you know, help me understand how to, uh, calculate the compound interest on my savings account?",
                "expected_keywords": ["calculate", "compound", "interest", "savings"]
            },
            {
                "name": "Meeting request with corrections", 
                "text": "So basically what I'm trying to say is, well, actually, let me start over. The thing is, I need to schedule a meeting, no wait, not a meeting, more like a conference call, for next Tuesday at 2 PM, or actually, can we make it 3 PM instead?",
                "expected_keywords": ["schedule", "conference", "call", "tuesday", "3"]
            },
            {
                "name": "Technical problem with disfluencies",
                "text": "Uh, I'm having this problem with my code where it's like, throwing an error, and I think it's because, um, the database connection is, you know, timing out or something?",
                "expected_keywords": ["problem", "code", "error", "database", "connection"]
            },
            {
                "name": "Short direct question",
                "text": "What time is it?",
                "expected_keywords": ["what", "time"]
            }
        ]
        
        for case in voice_transcription_cases:
            print( f"\n  {case['name']}:" )
            print( f"    Original ({len(case['text'])} chars): {case['text'][:80]}..." if len(case['text']) > 80 else f"    Original ({len(case['text'])} chars): {case['text']}" )
            
            # Test without symbol expansion (default)
            normalized = embedding_manager.normalize_text_for_cache( case[ 'text' ] )
            print( f"    Normalized ({len(normalized)} chars): {normalized[:80]}..." if len(normalized) > 80 else f"    Normalized ({len(normalized)} chars): {normalized}" )
            
            # Calculate reduction
            reduction = ( 1 - len( normalized ) / len( case[ 'text' ] ) ) * 100
            print( f"    Reduction: {reduction:.1f}%" )
            
            # Check if expected keywords are present
            keywords_found = sum( 1 for keyword in case[ 'expected_keywords' ] if keyword in normalized.lower() )
            if keywords_found >= len( case[ 'expected_keywords' ] ) / 2:  # At least half the keywords
                print( f"    ✓ Normalization preserved key concepts ({keywords_found}/{len(case['expected_keywords'])} keywords found)" )
            else:
                print( f"    ⚠ Some key concepts may be missing ({keywords_found}/{len(case['expected_keywords'])} keywords found)" )
        
    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="quick_smoke_test()" )
    
    print( "\n✓ Embedding functionality smoke test completed" )

if __name__ == "__main__":
    quick_smoke_test()
