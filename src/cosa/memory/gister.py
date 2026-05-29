import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.io_models.xml_models import SimpleResponse
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
from cosa.memory.gist_cache_table import GistCacheTable
from cosa.memory.normalizer import Normalizer


class Gister:
    """
    Extracts concise gists from text using LLM.

    This class handles the extraction of main intents from user questions
    by using prompt templates and LLM processing. Supports multiple prompt
    templates via the `prompt_key` parameter.

    Caching Behavior:
        Caching is ONLY enabled when using the default prompt template
        (gist generation for short utterances). Non-default prompts
        bypass the cache entirely. This design:

        - Maintains high cache hit rates for the original use case
          (short, repetitive utterances like "What's the weather?")
        - Prevents cache pollution from unique content like session messages
        - Avoids key collisions (same input text, different prompt → different output)

        If you need caching for a new prompt type, consider whether the
        input text will be repetitive enough to benefit from caching.
    """

    # Default prompt key - only this prompt uses caching
    DEFAULT_PROMPT_KEY = "prompt template for gist generation"

    def __init__( self, debug=False, verbose=False ):
        """
        Initialize the Gister with its own configuration and LLM factory.

        Requires:
            - debug is a boolean
            - verbose is a boolean

        Ensures:
            - Creates internal ConfigurationManager instance
            - Creates internal LlmClientFactory instance
            - Sets debug and verbose flags
            - Uses Pydantic XML parsing for structured responses
        """
        self.debug       = debug
        self.verbose     = verbose
        self.config_mgr  = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.llm_factory = LlmClientFactory()

        # Initialize normalizer for cache key generation
        self._normalizer = Normalizer()

        # Initialize gist cache if enabled
        self.cache_enabled = self.config_mgr.get( "gister cache enabled", default=True, return_type="boolean" )
        self._gist_cache = None

        if self.cache_enabled:
            db_uri      = du.get_project_root() + self.config_mgr.get( "solution snapshots lancedb path" )
            table_name  = self.config_mgr.get( "gister cache table name", default="gist_cache" )
            self._gist_cache = GistCacheTable( db_uri, table_name=table_name, debug=self.debug, verbose=self.verbose )

        if self.debug:
            cache_status = "enabled" if self.cache_enabled else "disabled"
            print( f"Gister initialized with Pydantic XML parsing, cache {cache_status}" )

    def get_gist( self, utterance: str, prompt_key: str = None ) -> str:
        """
        Extract the gist of text using LLM.

        Requires:
            - utterance is a non-empty string
            - prompt_key (if provided) must exist in config

        Ensures:
            - Returns a concise gist/summary of the input
            - Uses cache for default prompt only (see Caching Behavior below)
            - Returns utterance directly if it contains no spaces
            - Returns empty string if extraction fails

        Args:
            utterance: Text to extract gist from
            prompt_key: Config key for prompt template. Defaults to
                       DEFAULT_PROMPT_KEY for backward compatibility.
                       Non-default prompts bypass cache entirely.

        Caching Behavior:
            - DEFAULT prompt (gist generation): Cache ENABLED
              Designed for short, repetitive utterances with high hit rates.

            - CUSTOM prompts (session titles, etc.): Cache BYPASSED
              Prevents pollution and collisions. Custom prompts typically
              process unique content where caching provides no benefit.

        Raises:
            - FileNotFoundError if prompt template missing

        Performance:
            - Cache hit (default prompt): ~5ms
            - Cache miss or custom prompt: ~500ms (LLM latency)
        """
        # Shortcut: if utterance has no spaces, return it directly
        if " " not in utterance.strip():
            if self.debug: print( f"Shortcut: returning single word/token '{utterance}' without LLM" )
            return utterance.strip()

        # Determine which prompt to use
        if prompt_key is None:
            prompt_key = self.DEFAULT_PROMPT_KEY

        # Cache only for default prompt - avoids collisions and pollution
        use_cache = ( prompt_key == self.DEFAULT_PROMPT_KEY ) and self.cache_enabled

        if self.debug and self.verbose:
            if use_cache:
                print( f"Gister: cache ENABLED (default prompt)" )
            else:
                print( f"Gister: cache BYPASSED (custom prompt: {prompt_key})" )

        # Check cache (only for default prompt)
        if use_cache and self._gist_cache is not None:
            cached_gist = self._gist_cache.get_cached_gist( utterance )
            if cached_gist is not None:
                if self.debug and self.verbose: print( f"Cache HIT for '{du.truncate_string( utterance )}' → '{cached_gist}'" )
                return cached_gist

            if self.debug and self.verbose: print( f"Cache MISS for '{du.truncate_string( utterance )}' - calling LLM" )

        # Generate via LLM
        gist = self._generate_gist_via_llm( utterance, prompt_key )

        # Store in cache (only for default prompt)
        if use_cache and self._gist_cache is not None and gist:
            normalized = self._normalizer.normalize( utterance )
            self._gist_cache.cache_gist( utterance, gist, normalized=normalized )

        return gist

    def _generate_gist_via_llm( self, utterance: str, prompt_key: str ) -> str:
        """
        Generate gist by calling LLM (internal helper method).

        Requires:
            - utterance is a non-empty string with spaces
            - prompt_key is a valid config key for a prompt template

        Ensures:
            - Returns gist extracted from LLM response
            - Returns empty string if extraction fails

        Args:
            utterance: Text to summarize
            prompt_key: Config key for prompt template to use

        Raises:
            - FileNotFoundError if prompt template missing

        Performance:
            - ~500ms per call (LLM latency)
        """
        prompt_template_path = self.config_mgr.get( prompt_key )
        prompt_template = du.get_file_as_string( du.get_project_root() + prompt_template_path )

        # Process the template to replace {{PYDANTIC_XML_EXAMPLE}} with actual XML
        processor = PromptTemplateProcessor( debug=self.debug, verbose=self.verbose )
        prompt_template = processor.process_template( prompt_template, 'gist generation' )

        # Now format with the utterance
        prompt = prompt_template.format( utterance=utterance )

        # Add debug to see actual prompt
        if self.debug and self.verbose:
            print( f"Gister prompt being sent to LLM:\n{prompt[:500]}..." )

        llm_spec_key = self.config_mgr.get( "llm spec key for gist generation" )
        llm_client = self.llm_factory.get_client( llm_spec_key, debug=self.debug, verbose=self.verbose )
        results = llm_client.run( prompt )

        # Use Pydantic SimpleResponse model for structured parsing
        try:
            response_model = SimpleResponse.from_xml( results )
            gist = response_model.get_content()
            if gist is None:
                gist = ""
                if self.debug: print( "Warning: Pydantic parsing returned None content" )
            gist = gist.strip()
            if self.debug and self.verbose: print( f"Pydantic parsing extracted gist: '{gist}'" )
        except XMLParsingError as e:
            if self.debug: print( f"XML parsing failed: {e}" )
            gist = ""
        except Exception as e:
            if self.debug: print( f"Unexpected error during XML parsing: {e}" )
            gist = ""

        return gist


def quick_smoke_test():
    """
    Quick smoke test for Gister functionality.

    Tests the complete workflow of extracting a gist from a question.
    """
    du.print_banner( "Gister Smoke Test", prepend_nl=True )

    try:
        # Initialize Gister
        print( "Creating Gister instance..." )
        gister = Gister( debug=False, verbose=False )
        print( "✓ Gister created successfully" )

        # Test gist extraction with multiple utterances
        test_utterances = [
            "What's the date?",
            "What is today's date?",
            "What is the date today?",
            "It's hot in here.",
            "It is hot in here!",
            "I'm too hot!",
            "I am too hot!",
            "I am hot!",
            "I'm hot",
            "202-409-4959",
            "foo@bar.com"
        ]

        print( f"\nTesting {len(test_utterances)} utterances:" )
        print( "=" * 60 )

        for i, utterance in enumerate( test_utterances, 1 ):
            print( f"\n{i}. Input: '{utterance}'" )

            try:
                gist = gister.get_gist( utterance )
                if gist:
                    print( f"   ✓ Gist: '{gist}'" )
                else:
                    print( f"   ✗ No gist extracted" )
            except Exception as e:
                print( f"   ✗ Error: {str(e)}" )

        du.print_banner( "Smoke Test Complete", prepend_nl=True )

    except Exception as e:
        print( f"✗ Smoke test failed: {str(e)}" )
        du.print_banner( "Smoke Test Failed", prepend_nl=True )


if __name__ == "__main__":
    quick_smoke_test()