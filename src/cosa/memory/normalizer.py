import spacy
import re
from threading import Lock

import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager


class Normalizer:
    """
    Singleton class for normalizing transcribed voice text using spaCy.
    
    Requires:
        - spacy and en_core_web_sm model are installed
        - ConfigurationManager is available
        
    Ensures:
        - Returns normalized text with lemmatized words
        - Removes filler words and expands contractions
        - Preserves sentence boundaries
        - Maintains singleton instance
    """
    
    _instance = None
    _lock = Lock()
    
    # Common filler words in transcribed speech
    FILLER_WORDS = {
        "um", "uh", "umm", "uhh", "hmm", "mm", "mhm", 
        "like", "you know", "i mean", "sort of", "kind of",
        "basically", "actually", "literally", "right"
    }
    
    # Common contractions mapping
    CONTRACTIONS = {
        "don't": "do not",
        "won't": "will not",
        "can't": "cannot",
        "couldn't": "could not",
        "shouldn't": "should not",
        "wouldn't": "would not",
        "didn't": "did not",
        "doesn't": "does not",
        "haven't": "have not",
        "hasn't": "has not",
        "hadn't": "had not",
        "isn't": "is not",
        "aren't": "are not",
        "wasn't": "was not",
        "weren't": "were not",
        "i'm": "i am",
        "you're": "you are",
        "he's": "he is",
        "she's": "she is",
        "it's": "it is",
        "we're": "we are",
        "they're": "they are",
        "i've": "i have",
        "you've": "you have",
        "we've": "we have",
        "they've": "they have",
        "i'd": "i would",
        "you'd": "you would",
        "he'd": "he would",
        "she'd": "she would",
        "we'd": "we would",
        "they'd": "they would",
        "i'll": "i will",
        "you'll": "you will",
        "he'll": "he will",
        "she'll": "she will",
        "we'll": "we will",
        "they'll": "they will",
        "let's": "let us",
        "that's": "that is",
        "there's": "there is",
        "here's": "here is",
        "what's": "what is",
        "where's": "where is",
        "who's": "who is",
        "how's": "how is",
        "ain't": "am not",  # or "is not" depending on context
        # STT-friendly variants (no apostrophe) - common in speech-to-text output
        "whats": "what is",
        "thats": "that is",
        "theres": "there is",
        "heres": "here is",
        "wheres": "where is",
        "whos": "who is",
        "hows": "how is",
        "dont": "do not",
        "wont": "will not",
        "cant": "cannot",
        "didnt": "did not",
        "doesnt": "does not",
        "isnt": "is not",
        "arent": "are not",
        "wasnt": "was not",
        "werent": "were not",
        "youre": "you are",
        "theyre": "they are",
        "youve": "you have",
        "theyve": "they have",
        "youd": "you would",
        "theyd": "they would",
        "youll": "you will",
        "theyll": "they will"
    }

    # Math and comparison operators that should be preserved during normalization
    # These are punctuation in spaCy but carry semantic meaning in queries
    MATH_OPERATORS = {'+', '-', '*', '/', '=', '>', '<', '>=', '<=', '!=', '==', '%', '^', '(', ')'}

    def __new__( cls ):
        """
        Create or return singleton instance.
        
        Requires:
            - Nothing
            
        Ensures:
            - Returns the single instance of Normalizer
            - Loads spaCy model only once
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__( cls )
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__( self ):
        """
        Initialize the normalizer with spaCy pipeline.
        
        Requires:
            - spacy and configured model are available
            - ConfigurationManager is available
            
        Ensures:
            - spaCy pipeline is loaded and ready
            - Debug and verbose flags are set from config
        """
        if self._initialized:
            return
            
        # Initialize configuration manager
        self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        
        # Get debug and verbose from config (must specify return_type="boolean")
        self.debug   = self._config_mgr.get( "app debug", False, return_type="boolean" )
        self.verbose = self._config_mgr.get( "app verbose", False, return_type="boolean" )
        
        # Get spaCy model name from config
        model_name = self._config_mgr.get( "spacy model name", "en_core_web_sm" )
        
        if self.debug: print( f"Loading spaCy pipeline: {model_name}..." )
        
        try:
            self.nlp = spacy.load( model_name )
            # Disable unnecessary pipeline components for speed
            # Only disable components that actually exist in the pipeline
            components_to_disable = []
            if 'ner' in self.nlp.pipe_names:
                components_to_disable.append( 'ner' )
            if 'textcat' in self.nlp.pipe_names:
                components_to_disable.append( 'textcat' )
            
            if components_to_disable:
                self.nlp.disable_pipes( components_to_disable )
                
            self._initialized = True
            
            if self.verbose: du.print_banner( f"Normalizer initialized with model: {model_name}" )
            
        except OSError:
            raise RuntimeError( 
                f"spaCy model '{model_name}' not found. "
                f"Install with: python -m spacy download {model_name}"
            )
    
    def expand_contractions( self, text ):
        """
        Expand contractions in the text.
        
        Requires:
            - text is a string
            
        Ensures:
            - Returns text with contractions expanded
            - Preserves original capitalization where possible
        """
        # Create a pattern that matches whole words only
        for contraction, expansion in self.CONTRACTIONS.items():
            # Case-insensitive replacement while preserving original case pattern
            pattern = re.compile( r'\b' + re.escape( contraction ) + r'\b', re.IGNORECASE )
            text = pattern.sub( expansion, text )
            
        return text
    
    def remove_filler_words( self, doc ):
        """
        Remove filler words from spaCy Doc object.
        
        Requires:
            - doc is a spaCy Doc object
            
        Ensures:
            - Returns list of tokens without filler words
            - Preserves sentence structure
        """
        tokens = []
        
        for token in doc:
            # Check if token text (lowercased) is a filler word
            if token.text.lower() not in self.FILLER_WORDS:
                tokens.append( token )
            elif self.debug and self.verbose:
                print( f"Removing filler: '{token.text}'" )
                
        return tokens
    
    def normalize( self, text ):
        """
        Normalize transcribed voice text.
        
        Requires:
            - text is a non-empty string
            
        Ensures:
            - Returns normalized text with:
              - Expanded contractions
              - Removed filler words
              - Lemmatized words
              - Lowercase
              - Preserved sentence boundaries
        """
        if not text or not text.strip():
            return ""
            
        if self.debug and self.verbose: print( f"Normalizing: {text[:50]}..." )
        
        # Step 1: Expand contractions
        text = self.expand_contractions( text )
        if self.debug and self.verbose: print( f"After contractions: {text}" )
        
        # Step 2: Process with spaCy
        doc = self.nlp( text.lower() )
        
        # Step 3: Process sentences to preserve boundaries
        normalized_sentences = []
        
        for sent in doc.sents:
            # Get tokens for this sentence without fillers
            sent_tokens = []
            
            for token in sent:
                # Preserve math operators even though they're punctuation
                is_math_operator = token.text in self.MATH_OPERATORS
                should_keep = (token.text.lower() not in self.FILLER_WORDS and
                               (not token.is_punct or is_math_operator))

                if should_keep:
                    # Use lemma for content words, original for function words and operators
                    if token.pos_ in ['NOUN', 'VERB', 'ADJ', 'ADV']:
                        sent_tokens.append( token.lemma_ )
                    else:
                        sent_tokens.append( token.text )
                        
            if sent_tokens:
                normalized_sentences.append( ' '.join( sent_tokens ) )

        result = ' '.join( normalized_sentences )

        # Ensure consistent spacing around math operators (handles cases like "2+2" -> "2 + 2")
        result = re.sub( r'(\d)([+\-*/=<>])(\d)', r'\1 \2 \3', result )

        if self.debug and self.verbose: print( f"Normalized result: {result}" )

        return result
    
    def normalize_batch( self, texts ):
        """
        Normalize multiple texts efficiently.
        
        Requires:
            - texts is a list of strings
            
        Ensures:
            - Returns list of normalized texts
            - Processes texts in batch for efficiency
        """
        if self.verbose: du.print_banner( f"Batch normalizing {len(texts)} texts" )
        
        # Expand contractions first
        expanded_texts = [ self.expand_contractions( text ) for text in texts ]
        
        # Process with spaCy pipe for efficiency
        normalized_texts = []
        
        for doc in self.nlp.pipe( expanded_texts, batch_size=50 ):
            # Same normalization logic as single normalize
            normalized_sentences = []
            
            for sent in doc.sents:
                sent_tokens = []
                
                for token in sent:
                    if token.text.lower() not in self.FILLER_WORDS and not token.is_punct:
                        if token.pos_ in ['NOUN', 'VERB', 'ADJ', 'ADV']:
                            sent_tokens.append( token.lemma_ )
                        else:
                            sent_tokens.append( token.text )
                    elif token.is_punct and token.text in '.!?':
                        if sent_tokens:
                            sent_tokens[-1] += token.text
                            
                if sent_tokens:
                    normalized_sentences.append( ' '.join( sent_tokens ) )
            
            normalized_texts.append( ' '.join( normalized_sentences ) )
        
        return normalized_texts


def quick_smoke_test():
    """Run smoke test for Normalizer functionality."""
    print( "\n" + "="*60 )
    print( "Normalizer Smoke Test" )
    print( "="*60 )
    
    try:
        # Test singleton behavior
        du.print_banner( "Testing singleton pattern..." )
        norm1 = Normalizer()
        norm2 = Normalizer()
        assert norm1 is norm2, "Singleton pattern failed"
        print( "✓ Singleton pattern works correctly" )
        
        # Test samples
        test_cases = [
            "Um, I don't think we're gonna make it to the meeting.",
            "So like, you know, I was literally just thinking about it.",
            "She's hasn't been here, right? I mean, basically, she won't come.",
            "Let's see if we can't fix this issue, you know?",
            ""
        ]
        
        du.print_banner( "Testing individual normalization..." )
        for text in test_cases:
            if text:
                result = norm1.normalize( text )
                print( f"\nOriginal: {text}" )
                print( f"Normalized: {result}" )
        
        # Test batch processing
        du.print_banner( "Testing batch normalization..." )
        batch_results = norm1.normalize_batch( test_cases[:-1] )  # Exclude empty string
        for original, normalized in zip( test_cases[:-1], batch_results ):
            print( f"\nOriginal: {original}" )
            print( f"Normalized: {normalized}" )
        
        print( "\n✓ All smoke tests passed!" )
        
    except Exception as e:
        print( f"\n✗ Smoke test failed: {str(e)}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()