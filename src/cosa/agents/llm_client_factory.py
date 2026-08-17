import json
import os
import asyncio
from typing import Any, Optional, Union

from pydantic_ai import Agent

import cosa.utils.util as du
# from cosa.utils.util_stopwatch import Stopwatch

from cosa.agents.llm_client import LlmClient
from cosa.agents.chat_client import ChatClient
from cosa.agents.completion_client import CompletionClient
from cosa.agents.base_llm_client import LlmClientInterface
from cosa.config.configuration_manager import ConfigurationManager

class LlmClientFactory:
    """
    Singleton factory for creating LLM clients.
    
    This factory provides a unified interface to create clients for different LLM providers
    (OpenAI, Groq, Anthropic, Google, etc.) while handling the specifics of authentication,
    API endpoints, and client implementation details.
    
    Requires:
        - ConfigurationManager instance to read configuration values
        - API keys for requested providers set in environment variables or available via du.get_api_key()
        
    Ensures:
        - Only one instance of the factory exists at runtime (singleton pattern)
        - Returns appropriate LLM client instances based on model descriptors
        - Handles authentication and API endpoints transparently
        - Provides consistent interface across different LLM providers
        
    TODO:
        - Add comprehensive error handling and retry logic
        - Support fallback models when primary models are unavailable
        - Implement caching of responses for identical prompts
        - Add support for model-specific parameter validation
        - Develop monitoring and telemetry for LLM usage metrics
        - Implement cost tracking and budget management features
    """
    _instance: Optional['LlmClientFactory'] = None
    
    def __new__( cls, debug: bool=False, verbose: bool=False ):
        """
        Create or return the singleton instance of LlmClientFactory.
        
        Requires:
            - Class is LlmClientFactory or a subclass
            
        Ensures:
            - Only one instance of the factory exists at runtime
            - Returns existing instance if already created
            - Creates new instance if first call
            - Initializes _initialized flag on new instance
            
        Raises:
            - None
        """
        if cls._instance is None:
            cls._instance = super( LlmClientFactory, cls ).__new__( cls )
            # Initialize the instance
            cls._instance._initialized = False
        return cls._instance
    
    def __init__( self, debug: bool=False, verbose: bool=False ):
        """
        Initialize the singleton factory.
        
        Requires:
            - self._initialized attribute exists
            
        Ensures:
            - Initializes only once (subsequent calls are no-ops)
            - Creates ConfigurationManager instance
            - Sets debug and verbose flags
            - Sets _initialized to True
            
        Raises:
            - ConfigException if configuration manager initialization fails
        """
        # Only initialize once
        if self._initialized:
            return

        # Instantiate the global config manager
        self.config_mgr   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._initialized = True
        self.debug        = debug
        self.verbose      = verbose

        # Load vendor config from INI (with hardcoded fallbacks). The API-key env-var
        # NAME is a provider constant (e.g. pydantic-ai hardcodes GEMINI_API_KEY), not a
        # per-deployment axis like the URL — so it stays in VENDOR_CONFIG, not the INI.
        self.VENDOR_URLS           = self._load_vendor_urls()
        self.CLIENT_DEFAULT_PARAMS = self._load_client_defaults()
    
    def get_client( self, model_config_key: str, debug: bool=None, verbose: bool=None ) -> LlmClientInterface:
        """
        Get an LLM client for the given model descriptor.
        
        This method first tries to find the model in the configuration manager.
        If found, it uses the configuration settings to create the client.
        If not found, it parses the model descriptor to determine the vendor
        and creates a vendor-specific client.
        
        Now returns ChatClient or CompletionClient instances that implement
        the LlmClientInterface, ensuring all clients have a run() method.
        
        Requires:
            - model_config_key: A string identifying the model, which can be either:
                1. A configuration key (e.g., "deepily/ministral_8b_2410_ft_lora")
                2. A vendor prefixed model name (e.g., "openai:gpt-4", "groq:llama-3.1-8b-instant")
            - Valid API keys for the requested vendor if using cloud APIs
            
        Ensures:
            - Returns an LlmClientInterface implementation (ChatClient or CompletionClient)
            - All returned clients support the run() method
            - Handles authentication and API endpoint selection transparently
            - Provides debug information when debug=True
            
        Raises:
            - ValueError if the vendor is not supported
            - Various API errors if authentication fails or the model is unavailable
        """
        if debug   is not None: self.debug   = debug
        if verbose is not None: self.verbose = verbose
        
        # test to see if the key exists
        if self.debug: print( f"Checking if '{model_config_key}' exists in config_mgr..." )
        
        if not self.config_mgr.exists( model_config_key ):
            
            print( f"Configuration key '{model_config_key}' not found in config_mgr, getting vendor specific client...")
            return self._get_vendor_specific_client( model_config_key, debug, verbose )
        
        else:
            
            model_spec   = self.config_mgr.get( model_config_key, default=None )
            model_params = self.config_mgr.get( f"{model_config_key}_params", default="{}", return_type="dict" )
            
            model_tokenizer_map = self.config_mgr.get( "model tokenizer map", default="{}", return_type="json" )
            if debug and verbose:
                du.print_banner( f"Model params for '{model_config_key}':" )
                print( json.dumps( model_params, indent=4, sort_keys=True ) )
            
            default_prompt_format = self.config_mgr.get( "prompt format default", default="json_message" )
            prompt_format         = model_params.get( "prompt_format", default_prompt_format )
            completion_mode       = prompt_format in [ "instruction_completion", "special_token" ]
            
            # Extract stream parameter if present (will be used in run() calls)
            self.stream_enabled   = model_params.get( "stream", False )
            
            # Remove parameters that will be passed explicitly, so that **model_params doesn't complain about multiple values
            model_params.pop( "prompt_format", None )
            model_params.pop( "model_name", None )
            
            if model_spec.startswith( "vllm://" ):
                
                # Format: vllm://host:port@model_id
                body = model_spec[ len( "vllm://" ): ]
                host_port, model_name = body.split( "@", 1 )
                if completion_mode:
                    base_url = f"http://{host_port}/v1/completions"
                else:
                    base_url = f"http://{host_port}/v1"
                
                if self.debug and self.verbose: print( f"Creating {'Completion' if completion_mode else 'Chat'} client for {model_name} with base URL {base_url}" )
                
                if completion_mode:
                    return CompletionClient(
                        base_url=base_url,
                        model_name=model_name,
                        prompt_format=prompt_format,
                        model_tokenizer_map=model_tokenizer_map,
                        debug=self.debug,
                        verbose=self.verbose,
                        **model_params
                    )
                else:
                    # ChatClient hands model_name straight to pydantic_ai's Agent, which
                    # resolves it against a registry of KNOWN providers — a bare vLLM id
                    # like "kaitchup/Phi-4-AutoRound-GPTQ-4bit" raises UserError "Unknown
                    # model". A local vLLM speaks the OpenAI protocol, so the "openai:"
                    # prefix is what makes it resolvable; base_url (set into
                    # OPENAI_BASE_URL by ChatClient) points that provider at our own box
                    # rather than api.openai.com. Spike-verified 2026-08-01: bare name
                    # raises, prefixed name returns a real completion.
                    #
                    # This branch had NO callers before the DM Quality Judge v2 key —
                    # every vllm:// spec in lupin-app.ini was instruction_completion, so
                    # nothing reached it and the defect was never visible.
                    #
                    # api_key="EMPTY" is required, not cosmetic: a local vLLM wants no
                    # credential, but the OpenAI SDK underneath refuses to construct
                    # without one. CompletionClient already defaults it to "EMPTY" for
                    # every vllm:// client in this file (completion_client.py:82-84);
                    # ChatClient only sets it when passed (chat_client.py:59-60), so the
                    # factory has to supply it. Passing it here keeps the two vLLM paths
                    # behaving identically rather than editing the shared client.
                    return ChatClient(
                        model_name=f"openai:{model_name}",
                        api_key="EMPTY",
                        base_url=base_url,
                        model_tokenizer_map=model_tokenizer_map,
                        set_openai_env=True,   # openai:-prefixed local vLLM genuinely needs OPENAI_BASE_URL/KEY
                        debug=self.debug,
                        verbose=self.verbose,
                        **model_params
                    )
            else:
                # Assume chat-based model (OpenAI, Groq, Google, etc.)
                return ChatClient(
                    model_name=model_spec,
                    model_tokenizer_map=model_tokenizer_map,
                    debug=self.debug,
                    verbose=self.verbose,
                    **model_params
                )
    
    def _load_vendor_urls( self ) -> dict[ str, str ]:
        """
        Load vendor API URLs from ConfigManager, falling back to hardcoded defaults.

        Ensures:
            - Returns dict mapping vendor name to API endpoint URL
            - INI keys override hardcoded defaults
        """
        defaults = {
            "openai"    : "https://api.openai.com/v1",
            "groq"      : "https://api.groq.com/openai/v1",
            "anthropic" : "https://api.anthropic.com/v1",
            "google-gla": "https://generativelanguage.googleapis.com/v1",
            "vllm"      : "http://192.168.1.21:3001/v1",
            "deepily"   : "http://192.168.1.21:3001/v1",
            "mistralai" : "https://api.mistral.ai/v1",
        }
        result = {}
        for vendor, default_url in defaults.items():
            result[ vendor ] = self.config_mgr.get(
                f"llm vendor url {vendor}", default=default_url, silent=True
            )
        return result

    def _load_client_defaults( self ) -> dict[ str, Any ]:
        """
        Load default client parameters from ConfigManager.

        Ensures:
            - Returns dict with temperature and max_tokens defaults
        """
        return {
            "temperature" : self.config_mgr.get( "llm client default temperature", default="0.7", silent=True, return_type="float" ),
            "max_tokens"  : self.config_mgr.get( "llm client default max tokens",  default="1024", silent=True, return_type="int" ),
        }
    # Comprehensive vendor configuration
    VENDOR_CONFIG: dict[str, dict[str, Any]] = {
        "openai"    : {
            "env_var"       : "OPENAI_API_KEY",
            "key_name"      : "openai",
            "client_type"   : "chat",
            "set_openai_env": True,   # OpenAI IS the OpenAI protocol — must reclaim OPENAI_BASE_URL
            # OPENAI_API_KEY doubles as the shared compat target other vendors write, so an
            # in-process value cannot be trusted as openai's OWN key — always resolve fresh.
            "env_var_is_shared_compat_target": True,
        },
        "groq"      : {
            "env_var"       : "GROQ_API_KEY",
            "key_name"      : "groq",
            "client_type"   : "chat",
            "set_openai_env": True,  # Also set OPENAI_API_KEY for compatibility
        },
        "anthropic" : {
            "env_var"     : "ANTHROPIC_API_KEY",
            "key_name"    : "claude",
            "client_type" : "chat",
        },
        "google-gla": {
            "env_var"     : "GEMINI_API_KEY",
            "key_name"    : "gemini",
            "client_type" : "chat",
        },
        "mistralai" : {
            "env_var"       : "MISTRAL_API_KEY",
            "key_name"      : "mistral",
            "client_type"   : "chat",
            "set_openai_env": True,  # Also set OPENAI_API_KEY for compatibility
        },
        "vllm"      : {
            "client_type": "completion",  # Default to completion for local models
        },
        "deepily"   : {
            "client_type": "completion",  # Default to completion for local models
        }
    }
    
    class AgentWrapper:
        """
        A wrapper class that provides a synchronous interface to the async Agent class.
        This allows the Agent to be used like other LLM clients.
        
        The wrapper handles the async/await logic internally, so clients can use
        a synchronous run() method without worrying about async handling.
        
        Requires:
            - agent: A valid pydantic_ai Agent instance
            - asyncio module available for async/await handling
            
        Ensures:
            - Provides a synchronous run() method that matches the interface of other clients
            - Handles async/await logic internally
            - Returns the response data directly, not wrapped in a Response object
            - Provides debug output when debug=True
        """
        
        def __init__( self, agent: Agent, debug: bool=False ):
            """
            Initialize the wrapper with an async Agent.
            
            Requires:
                - agent is a valid pydantic_ai Agent instance
                
            Ensures:
                - Stores agent reference
                - Sets debug flag
                
            Raises:
                - TypeError if agent is not a valid Agent instance
            """
            self.agent = agent
            self.debug = debug
        
        def run( self, prompt: str, **kwargs: Any ) -> str:
            """
            Synchronous version of agent.run that handles the async/await internally.
            
            This method provides a synchronous interface to the async Agent.run() method,
            handling all the event loop and async/await logic transparently.
            
            Requires:
                - prompt: A non-empty string containing the prompt to send to the LLM
                - self.agent: A valid pydantic_ai Agent instance with a run() method
                
            Ensures:
                - Executes the prompt against the LLM in a synchronous manner
                - Handles event loop creation/reuse automatically
                - Extracts and returns the response data directly
                - Provides debug output when self.debug=True
                
            Raises:
                - Any exceptions from the underlying Agent.run() method
                - RuntimeError if async event loop issues occur
                
            Returns:
                - String response from the LLM
            """
            if self.debug:
                print( f"Running prompt through AgentWrapper..." )
            
            try:
                # Create a new event loop if one is not available
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop( loop )
                
                # Run the coroutine in the event loop
                response = loop.run_until_complete( self.agent.run( prompt, **kwargs ) )
                
                # Extract data attribute if present (pydantic_ai sometimes wraps responses)
                if hasattr( response, 'data' ):
                    return response.data
                return response
            
            except Exception as e:
                if self.debug:
                    print( f"Error in AgentWrapper.run: {str( e )}" )
                raise
    
    def _parse_model_descriptor( self, model_descriptor: str ) -> tuple[str, str]:
        """
        Parse a model descriptor to extract vendor and model name.

        Requires:
            - model_descriptor: A non-empty string in one of the following formats:
                1. "vendor:model-name" (e.g., "groq:llama-3.1-8b-instant")
                   Colon is the ONLY vendor delimiter.
                2. "llm_deepily_*" legacy format for Deepily models
                3. Any other string — treated as a HuggingFace model ID or
                   local model identifier for vLLM (e.g., "Qwen/Qwen3-4B-Base")

        Ensures:
            - Returns a tuple of (vendor, model_name)
            - Slash is NEVER interpreted as a vendor delimiter
            - Vendor is always lowercased for consistency with VENDOR_CONFIG keys
            - Unknown formats default to vLLM
        """
        if ":" in model_descriptor:
            vendor, model_name = model_descriptor.split( ":", 1 )
            return vendor.strip().lower(), model_name.strip()

        elif model_descriptor.startswith( "llm_deepily_" ):
            return "deepily", model_descriptor

        else:
            # No colon = not vendor-prefixed.
            # Treat as HuggingFace model ID or local model for vLLM.
            if "/" in model_descriptor:
                left = model_descriptor.split( "/", 1 )[ 0 ].strip().lower()
                if left in self.VENDOR_CONFIG:
                    print( f"DEPRECATION WARNING: '{model_descriptor}' uses slash as vendor delimiter. "
                           f"Use '{left}:{model_descriptor.split( '/', 1 )[ 1 ].strip()}' instead." )
            return "vllm", model_descriptor
            
    def _get_vendor_specific_client( self, model_descriptor: str, debug: bool=False, verbose: bool=False ) -> LlmClientInterface:
        """
        Create vendor-specific client based on model descriptor.
        
        Now returns ChatClient or CompletionClient instances based on vendor
        configuration, ensuring all clients implement LlmClientInterface.
        
        Requires:
            - model_descriptor: String in format "vendor:model" (colon is the only vendor delimiter)
            - VENDOR_CONFIG map with complete vendor-specific configuration
            - Valid API keys for the requested vendor available in environment or via du.get_api_key()
            
        Ensures:
            - Returns ChatClient or CompletionClient based on vendor configuration
            - All returned clients implement LlmClientInterface with run() method
            - Sets all required environment variables for API access
            - Handles authentication consistently across vendors
            - Provides debug output when debug=True
            
        Raises:
            - ValueError if vendor is not supported in VENDOR_CONFIG
            - NotImplementedError for certain vendor types that are not yet implemented
            - API-specific errors if authentication fails
        """
        # Parse the vendor and model name
        vendor, model_name = self._parse_model_descriptor( model_descriptor )
        vendor_key = vendor.lower()
        
        # Get vendor configuration or default
        config = self.VENDOR_CONFIG.get( vendor_key, {} )
        if not config: raise ValueError( f"Unsupported vendor: {vendor}" )
            
        # Get base URL from vendor URLs map
        base_url = self.VENDOR_URLS.get( vendor_key )
        
        # Handle API keys if needed. The env-var NAME is a provider constant, so it lives
        # in VENDOR_CONFIG (authoritative) — not an INI knob that could only ever be set
        # wrong (bug 7f361ccf, fix b).
        if "env_var" in config:
            env_var  = config[ "env_var" ]
            key_name = config[ "key_name" ]

            # Get API key from environment or utility function. The env-first shortcut is
            # safe ONLY for a vendor whose env var nobody else writes. openai's env var
            # (OPENAI_API_KEY) doubles as the shared compat target that set_openai_env
            # vendors (groq/mistralai) write process-global, so an in-process value there
            # may be another vendor's leaked key — always resolve openai's key fresh.
            trust_env = not config.get( "env_var_is_shared_compat_target", False )
            if trust_env and env_var in os.environ:
                if debug: print( f"Using {env_var} from environment" )
                api_key = os.environ[env_var]
            else:
                if debug: print( f"{env_var} not read from environment, using du.get_api_key()..." )
                api_key = du.get_api_key( key_name )

            # du.get_api_key() returns None when the key file is missing; assigning None to
            # os.environ raises an opaque TypeError. Fail with a readable auth error instead.
            if api_key is None:
                raise ValueError(
                    f"No API key for vendor '{vendor_key}': environment variable '{env_var}' "
                    f"is unset and du.get_api_key( '{key_name}' ) returned None "
                    f"(missing key file src/conf/keys/{key_name})"
                )

            # Set environment variable
            os.environ[env_var] = api_key
            
            # Set additional keys if needed (for compatibility)
            if config.get( "set_openai_env" ):
                os.environ["OPENAI_API_KEY"] = api_key
                os.environ["OPENAI_BASE_URL"] = base_url
                if debug: print( f"Set OPENAI_BASE_URL={base_url} and OPENAI_API_KEY" )
                
        # Create client based on vendor configuration
        client_type = config.get( "client_type", "chat" )
        
        if client_type == "completion":
            # For vendors using completion API
            if debug: print( f"Creating CompletionClient with base_url={base_url}, model={model_name}" )
            
            if vendor_key in ["vllm", "deepily"]:
                # Local vLLM model — append /completions to the already-resolved VENDOR_URLS base_url
                base_url = f"{base_url}/completions"
                if debug: print( f"Creating CompletionClient for local vLLM: base_url={base_url}, model={model_name}" )
                return CompletionClient(
                    base_url=base_url,
                    model_name=model_name,
                    prompt_format="instruction_completion",
                    debug=debug,
                    verbose=verbose,
                    **self.CLIENT_DEFAULT_PARAMS
                )
            
            return CompletionClient(
                base_url=base_url,
                model_name=model_name,
                api_key=api_key,
                debug=debug,
                verbose=verbose,
                **self.CLIENT_DEFAULT_PARAMS
            )
        else:
            # For vendors using chat API
            full_model_string = f"{vendor}:{model_name}"
            
            if debug: print( f"Creating ChatClient with model string: {full_model_string}" )
            
            return ChatClient(
                model_name=full_model_string,
                api_key=api_key,
                base_url=base_url,
                set_openai_env=config.get( "set_openai_env", False ),
                debug=debug,
                verbose=verbose,
                **self.CLIENT_DEFAULT_PARAMS
            )


def quick_smoke_test():
    """Quick smoke test to validate LlmClientFactory functionality."""
    du.print_banner( "LlmClientFactory Smoke Test", prepend_nl=True )
    
    try:
        # Initialize factory
        factory = LlmClientFactory()
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        print( "✓ LlmClientFactory initialized successfully" )
        
        # Prepare simple test prompt
        question = "What time is it?"
        try:
            prompt_template = du.get_file_as_string( du.get_project_root() + config_mgr.get( "prompt template for agent router go to datetime" ) )
            prompt = prompt_template.format( question=question )
            print( "✓ Test prompt prepared successfully" )
        except Exception as e:
            print( f"⚠ Warning: Could not load prompt template, using simple prompt: {e}" )
            prompt = f"Question: {question}\nAnswer:"
        
        # Test a subset of available models (to keep smoke test quick)
        models_to_test = [
            LlmClient.GROQ_LLAMA_3_3_70B  # Just test one reliable model for smoke test
        ]
        
        print( f"\nTesting {len( models_to_test )} model(s):" )
        
        for model in models_to_test:
            print( f"\nTesting model: {model}" )
            try:
                client = factory.get_client( model, debug=False, verbose=False )
                print( f"✓ Client created successfully for {model}" )
                
                # For smoke test, we'll just validate client creation, not actual LLM calls
                # to avoid API costs and timeouts
                print( f"✓ Model {model} is ready for use" )
                
            except Exception as e:
                print( f"✗ Error with {model}: {str( e )}" )
        
    except Exception as e:
        print( f"✗ Error initializing LlmClientFactory: {e}" )
    
    print( "\n✓ LlmClientFactory smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()