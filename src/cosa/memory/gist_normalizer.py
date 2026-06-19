"""
Module for extracting and normalizing the gist of voice transcriptions.

Combines gist extraction with text normalization to handle verbose voice-to-text
output, producing concise, normalized summaries ideal for embedding generation.
"""

import cosa.utils.util as du
from cosa.memory.gister import Gister
from cosa.memory.normalizer import Normalizer
from threading import Lock


class GistNormalizer:
    """
    Singleton class for extracting and normalizing the gist of voice transcriptions.
    
    This class is particularly useful for voice transcriptions that contain
    verbose explanations, disfluencies, and spoken language patterns.
    
    Requires:
        - Gister and Normalizer classes are available
        - LLM configuration for gist extraction
        
    Ensures:
        - Returns normalized gist of input text
        - Handles voice transcription artifacts
        - Produces consistent output for embeddings
        - Maintains singleton instance
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__( cls, debug=False, verbose=False ):
        """
        Create or return singleton instance.
        
        Requires:
            - Nothing
            
        Ensures:
            - Returns the single instance of GistNormalizer
            - Initializes components only once
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__( cls )
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__( self, debug=False, verbose=False ):
        """
        Initialize the GistNormalizer with component services.
        
        Requires:
            - Configuration for Gister is available
            - spaCy model for Normalizer is installed
            
        Ensures:
            - Initializes Gister and Normalizer instances
            - Sets debug and verbose flags
        """
        if self._initialized:
            return
            
        self.debug   = debug
        self.verbose = verbose
        
        if self.debug: print( "Initializing GistNormalizer..." )
        
        # Initialize components
        self.gister     = Gister( debug=debug, verbose=verbose )
        self.normalizer = Normalizer()  # Singleton, gets config from ConfigurationManager
        
        if self.verbose: du.print_banner( "GistNormalizer initialized" )
        
        self._initialized = True
    
    def get_normalized_gist( self, text ):
        """
        Extract gist from text and normalize it.
        
        Requires:
            - text is a non-empty string
            
        Ensures:
            - Returns normalized gist of the input
            - Removes voice transcription artifacts
            - Produces consistent, concise output
        """
        if not text or not text.strip():
            return ""
        
        if self.debug and self.verbose:
            du.print_banner( f"Processing text ({len(text)} chars)" )
            print( f"Input: {text[:100]}..." )
        
        # Step 1: Extract the gist
        gist = self.gister.get_gist( text )
        
        if self.debug: 
            print( f"Extracted gist: {gist}" )
        
        # Step 2: Normalize the gist
        normalized_gist = self.normalizer.normalize( gist )
        
        if self.debug and self.verbose:
            du.print_banner( f"Result: {normalized_gist}" )
        
        return normalized_gist
    
    def process_batch( self, texts ):
        """
        Process multiple texts efficiently.
        
        Requires:
            - texts is a list of strings
            
        Ensures:
            - Returns list of normalized gists
            - Processes efficiently in batch where possible
        """
        if self.verbose: 
            du.print_banner( f"Batch processing {len(texts)} texts" )
        
        # Extract gists for all texts
        gists = []
        for i, text in enumerate( texts ):
            if self.debug: print( f"Processing text {i+1}/{len(texts)}" )
            gist = self.gister.get_gist( text )
            gists.append( gist )
        
        # Normalize all gists in batch
        normalized_gists = self.normalizer.normalize_batch( gists )
        
        return normalized_gists


def quick_smoke_test():
    """Run comprehensive smoke test for GistNormalizer functionality."""
    print( "\n" + "="*60 )
    print( "GistNormalizer Smoke Test" )
    print( "="*60 )
    
    try:
        # Initialize GistNormalizer
        du.print_banner( "Initializing GistNormalizer..." )
        gn = GistNormalizer( debug=True, verbose=True )
        print( "✓ GistNormalizer initialized successfully" )
        
        # Test cases with realistic voice transcriptions
        test_cases = [
            # Simple question with filler words
            "Um, so like, I was wondering if you could, you know, help me understand how to, uh, calculate the compound interest on my savings account?",
            
            # Verbose explanation with corrections
            "So basically what I'm trying to say is, well, actually, let me start over. The thing is, I need to schedule a meeting, no wait, not a meeting, more like a conference call, for next Tuesday at 2 PM, or actually, can we make it 3 PM instead?",
            
            # Technical question with disfluencies
            "Uh, I'm having this problem with my code where it's like, throwing an error, and I think it's because, um, the database connection is, you know, timing out or something? But I'm not really sure because sometimes it works and sometimes it doesn't, which is really frustrating.",
            
            # Stream of consciousness with topic changes
            "Okay so I went to the store today and I was looking for apples, but then I remembered that I also needed to get milk, oh and speaking of milk, did you know that almond milk has less calories? Anyway, I ended up forgetting the apples but I did get the milk and some bread too.",
            
            # Meeting request with uncertainty
            "Hi, um, I was hoping we could, like, set up a time to discuss the, uh, the project proposal? I'm thinking maybe sometime next week would work, but I'm pretty flexible, so really whenever works for you is fine with me. Oh, and if Jane could join us that would be great, but it's not absolutely necessary.",
            
            # Complex technical explanation
            "So the way I understand it is that, um, machine learning models, they basically learn patterns from data, right? And like, neural networks are just one type of model that uses, uh, these layers of nodes that are connected, and each connection has a weight, and through training, these weights get adjusted to minimize error. Does that make sense? I mean, that's the basic idea anyway.",
            
            # Customer service complaint
            "I'm really frustrated because I've been trying to reach customer service for like an hour and I keep getting put on hold and then disconnected. This is the third time I'm calling about the same issue with my order that was supposed to arrive last week but still hasn't shown up and nobody seems to know where it is."
        ]
        
        # Test individual processing
        du.print_banner( "Testing individual gist normalization..." )
        
        for i, text in enumerate( test_cases ):
            print( f"\n{'='*50}" )
            print( f"Test Case {i+1}:" )
            print( f"Original ({len(text)} chars): {text}" )
            
            result = gn.get_normalized_gist( text )
            
            print( f"Normalized Gist: {result}" )
            print( f"Reduction: {len(text)} → {len(result)} chars ({(1-len(result)/len(text))*100:.1f}% reduction)" )
        
        # Test batch processing
        du.print_banner( "Testing batch processing..." )
        
        batch_results = gn.process_batch( test_cases[:3] )
        
        print( "\nBatch Results:" )
        for i, (original, normalized) in enumerate( zip( test_cases[:3], batch_results ) ):
            print( f"\n{i+1}. Original: {original[:80]}..." )
            print( f"   Normalized: {normalized}" )
        
        # Test edge cases
        du.print_banner( "Testing edge cases..." )
        
        edge_cases = [
            "",  # Empty string
            "   ",  # Whitespace only
            "Hi.",  # Very short
            "Um, uh, like, you know?",  # Only filler words
        ]
        
        for text in edge_cases:
            result = gn.get_normalized_gist( text )
            print( f"Input: '{text}' → Output: '{result}'" )
        
        print( "\n✓ All smoke tests passed!" )
        
    except Exception as e:
        print( f"\n✗ Smoke test failed: {str(e)}" )
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    quick_smoke_test()