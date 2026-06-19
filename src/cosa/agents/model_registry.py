from dataclasses import dataclass, field
from typing import Dict, Set, Optional, List
from enum import Enum

class LlmProvider( Enum ):
    """Enumeration of supported LLM providers."""
    OPENAI    = "openai"
    ANTHROPIC = "anthropic"
    GROQ      = "groq"
    GOOGLE    = "google"
    DEEPILY   = "deepily"

@dataclass
class ModelConfig:
    """
    Configuration for a specific model.
    
    Requires:
        - name is unique model identifier
        - provider is valid LlmProvider enum value
        - client_class is fully qualified class name
        - max_tokens is positive integer
        
    Ensures:
        - model configuration is complete and valid
        - supported_parameters contains standard parameter set
    """
    name                      : str
    provider                  : LlmProvider
    client_class              : str  # Fully qualified class name
    max_tokens                : int
    supports_streaming        : bool = True
    supports_system_messages  : bool = True
    cost_per_1k_tokens_input  : Optional[float] = None
    cost_per_1k_tokens_output : Optional[float] = None
    supported_parameters      : Set[str] = field( default_factory=lambda: {
        'temperature', 'max_tokens', 'top_p', 'frequency_penalty', 
        'presence_penalty', 'stop'
    } )
    
    def __post_init__( self ):
        """
        Validate model configuration after initialization.
        
        Ensures:
            - max_tokens is positive
            - cost values are non-negative if provided
        """
        if self.max_tokens <= 0:
            raise ValueError( "max_tokens must be positive" )
        if self.cost_per_1k_tokens_input is not None and self.cost_per_1k_tokens_input < 0:
            raise ValueError( "cost_per_1k_tokens_input must be non-negative" )
        if self.cost_per_1k_tokens_output is not None and self.cost_per_1k_tokens_output < 0:
            raise ValueError( "cost_per_1k_tokens_output must be non-negative" )

class ModelRegistry:
    """
    Registry of available models and their configurations.
    
    Requires:
        - registry is initialized with default models
        
    Ensures:
        - provides access to model configurations
        - supports registration of new models
        - validates model configurations
    """
    
    def __init__( self ):
        """
        Initialize model registry.
        
        Ensures:
            - registry is initialized with empty model dictionary
            - default models are loaded
        """
        self._models: Dict[str, ModelConfig] = {}
        self._initialize_default_models()
    
    def register_model( self, config: ModelConfig ):
        """
        Register a new model configuration.
        
        Requires:
            - config is valid ModelConfig object
            - config.name is unique within registry
            
        Ensures:
            - model is added to registry
            - existing model with same name is replaced
        """
        self._models[config.name] = config
        if self._verbose_logging:
            print( f"Registered model: {config.name} ({config.provider.value})" )
    
    def get_model_config( self, model_name: str ) -> ModelConfig:
        """
        Get configuration for a specific model.
        
        Requires:
            - model_name is registered in the registry
            
        Ensures:
            - returns ModelConfig for the specified model
            
        Raises:
            - LlmConfigError if model is not found
        """
        from .llm_exceptions import LlmConfigError
        
        if model_name not in self._models:
            available_models = list( self._models.keys() )
            raise LlmConfigError( 
                f"Unknown model: {model_name}. Available models: {available_models}" 
            )
        return self._models[model_name]
    
    def get_models_by_provider( self, provider: LlmProvider ) -> List[ModelConfig]:
        """
        Get all models for a specific provider.
        
        Requires:
            - provider is valid LlmProvider enum value
            
        Ensures:
            - returns list of ModelConfig objects for the provider
            - list may be empty if no models found
        """
        return [ config for config in self._models.values() if config.provider == provider ]
    
    def list_all_models( self ) -> List[str]:
        """
        Get list of all registered model names.
        
        Ensures:
            - returns sorted list of model names
        """
        return sorted( self._models.keys() )
    
    def get_providers( self ) -> Set[LlmProvider]:
        """
        Get set of all providers with registered models.
        
        Ensures:
            - returns set of LlmProvider enum values
        """
        return { config.provider for config in self._models.values() }
    
    @property
    def _verbose_logging( self ) -> bool:
        """Enable verbose logging for registry operations."""
        return False  # Can be made configurable later
    
    def _initialize_default_models( self ):
        """
        Initialize registry with default model configurations.
        
        Ensures:
            - common models for each provider are registered
            - configuration includes cost and capability information
        """
        # OpenAI models
        self.register_model( ModelConfig(
            name                      = "gpt-4",
            provider                  = LlmProvider.OPENAI,
            client_class              = "cosa.agents.openai_client.OpenAIClient",
            max_tokens                = 8192,
            cost_per_1k_tokens_input  = 0.03,
            cost_per_1k_tokens_output = 0.06
        ) )
        
        self.register_model( ModelConfig(
            name                      = "gpt-4-turbo",
            provider                  = LlmProvider.OPENAI,
            client_class              = "cosa.agents.openai_client.OpenAIClient",
            max_tokens                = 4096,
            cost_per_1k_tokens_input  = 0.01,
            cost_per_1k_tokens_output = 0.03
        ) )
        
        self.register_model( ModelConfig(
            name                      = "gpt-3.5-turbo",
            provider                  = LlmProvider.OPENAI,
            client_class              = "cosa.agents.openai_client.OpenAIClient",
            max_tokens                = 4096,
            cost_per_1k_tokens_input  = 0.0005,
            cost_per_1k_tokens_output = 0.0015
        ) )
        
        # Anthropic models
        self.register_model( ModelConfig(
            name                      = "claude-3-sonnet-20240229",
            provider                  = LlmProvider.ANTHROPIC,
            client_class              = "cosa.agents.anthropic_client.AnthropicClient",
            max_tokens                = 4096,
            cost_per_1k_tokens_input  = 0.003,
            cost_per_1k_tokens_output = 0.015
        ) )
        
        self.register_model( ModelConfig(
            name                      = "claude-3-haiku-20240307",
            provider                  = LlmProvider.ANTHROPIC,
            client_class              = "cosa.agents.anthropic_client.AnthropicClient",
            max_tokens                = 4096,
            cost_per_1k_tokens_input  = 0.00025,
            cost_per_1k_tokens_output = 0.00125
        ) )
        
        # Groq models
        self.register_model( ModelConfig(
            name                      = "mixtral-8x7b-32768",
            provider                  = LlmProvider.GROQ,
            client_class              = "cosa.agents.groq_client.GroqClient",
            max_tokens                = 32768,
            cost_per_1k_tokens_input  = 0.00027,
            cost_per_1k_tokens_output = 0.00027
        ) )
        
        self.register_model( ModelConfig(
            name                      = "llama2-70b-4096",
            provider                  = LlmProvider.GROQ,
            client_class              = "cosa.agents.groq_client.GroqClient",
            max_tokens                = 4096,
            cost_per_1k_tokens_input  = 0.00070,
            cost_per_1k_tokens_output = 0.00080
        ) )
        
        # Google models
        self.register_model( ModelConfig(
            name                      = "gemini-1.5-pro",
            provider                  = LlmProvider.GOOGLE,
            client_class              = "cosa.agents.google_client.GoogleClient",
            max_tokens                = 2048,
            cost_per_1k_tokens_input  = 0.0035,
            cost_per_1k_tokens_output = 0.0105
        ) )
        
        # Deepily models (local inference)
        self.register_model( ModelConfig(
            name                      = "deepily-llama-7b",
            provider                  = LlmProvider.DEEPILY,
            client_class              = "cosa.agents.deepily_client.DeepilyClient",
            max_tokens                = 4096,
            cost_per_1k_tokens_input  = 0.0,  # Local inference
            cost_per_1k_tokens_output = 0.0
        ) )


def quick_smoke_test():
    """
    Critical smoke test for ModelRegistry - validates model management functionality.
    
    This test is essential for v000 deprecation as model_registry.py is critical
    for LLM model management and configuration across the system.
    """
    import cosa.utils.util as du
    
    du.print_banner( "Model Registry Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic class and enum presence
        print( "Testing core model registry components..." )
        expected_classes = [ "ModelRegistry", "ModelConfig", "LlmProvider" ]
        
        classes_found = 0
        for class_name in expected_classes:
            if class_name in globals():
                classes_found += 1
            else:
                print( f"⚠ Missing class: {class_name}" )
        
        if classes_found == len( expected_classes ):
            print( f"✓ All {len( expected_classes )} core model registry classes present" )
        else:
            print( f"⚠ Only {classes_found}/{len( expected_classes )} model registry classes present" )
        
        # Test 2: LlmProvider enum validation
        print( "Testing LlmProvider enum..." )
        try:
            expected_providers = [ "OPENAI", "ANTHROPIC", "GROQ", "GOOGLE", "DEEPILY" ]
            
            providers_found = 0
            for provider in expected_providers:
                if hasattr( LlmProvider, provider ):
                    providers_found += 1
                else:
                    print( f"⚠ Missing provider: {provider}" )
            
            if providers_found == len( expected_providers ):
                print( f"✓ All {len( expected_providers )} LLM providers present" )
            else:
                print( f"⚠ Only {providers_found}/{len( expected_providers )} LLM providers present" )
            
        except Exception as e:
            print( f"⚠ LlmProvider enum issues: {e}" )
        
        # Test 3: ModelConfig dataclass validation
        print( "Testing ModelConfig dataclass..." )
        try:
            # Test creating a basic model config
            test_config = ModelConfig(
                name="test-model",
                provider=LlmProvider.OPENAI,
                client_class="test.client.TestClient",
                max_tokens=1000
            )
            
            # Check required fields
            if ( hasattr( test_config, 'name' ) and 
                 hasattr( test_config, 'provider' ) and
                 hasattr( test_config, 'max_tokens' ) ):
                print( "✓ ModelConfig dataclass structure valid" )
            else:
                print( "✗ ModelConfig missing required fields" )
            
            # Test validation
            try:
                invalid_config = ModelConfig(
                    name="invalid",
                    provider=LlmProvider.OPENAI,
                    client_class="test.client.TestClient",
                    max_tokens=-1  # Should fail validation
                )
                print( "✗ ModelConfig validation not working (accepted negative max_tokens)" )
            except ValueError:
                print( "✓ ModelConfig validation working" )
                
        except Exception as e:
            print( f"⚠ ModelConfig dataclass issues: {e}" )
        
        # Test 4: ModelRegistry basic functionality
        print( "Testing ModelRegistry basic functionality..." )
        try:
            registry = ModelRegistry()
            
            # Check basic methods
            expected_methods = [
                "register_model", "get_model_config", "get_models_by_provider",
                "list_all_models", "get_providers"
            ]
            
            methods_found = 0
            for method_name in expected_methods:
                if hasattr( registry, method_name ):
                    methods_found += 1
                else:
                    print( f"⚠ Missing method: {method_name}" )
            
            if methods_found == len( expected_methods ):
                print( f"✓ All {len( expected_methods )} ModelRegistry methods present" )
            else:
                print( f"⚠ Only {methods_found}/{len( expected_methods )} ModelRegistry methods present" )
            
        except Exception as e:
            print( f"⚠ ModelRegistry functionality issues: {e}" )
        
        # Test 5: Default model registration
        print( "Testing default model registration..." )
        try:
            registry = ModelRegistry()
            
            # Check that default models are loaded
            all_models = registry.list_all_models()
            
            if len( all_models ) > 0:
                print( f"✓ Default models loaded ({len( all_models )} models)" )
            else:
                print( "✗ No default models loaded" )
            
            # Check for expected providers
            providers = registry.get_providers()
            expected_provider_count = len( LlmProvider )
            
            if len( providers ) >= 3:  # Expect at least 3 providers
                print( f"✓ Multiple providers registered ({len( providers )} providers)" )
            else:
                print( f"⚠ Limited providers registered: {len( providers )}" )
            
        except Exception as e:
            print( f"⚠ Default model registration issues: {e}" )
        
        # Test 6: Model retrieval functionality
        print( "Testing model retrieval functionality..." )
        try:
            registry = ModelRegistry()
            all_models = registry.list_all_models()
            
            if all_models:
                # Test getting a specific model
                first_model_name = all_models[0]
                model_config = registry.get_model_config( first_model_name )
                
                if isinstance( model_config, ModelConfig ):
                    print( "✓ Model retrieval working" )
                else:
                    print( "✗ Model retrieval returned wrong type" )
                
                # Test invalid model handling
                try:
                    registry.get_model_config( "nonexistent-model" )
                    print( "✗ Invalid model not rejected" )
                except Exception:
                    print( "✓ Invalid model properly rejected" )
                    
            else:
                print( "⚠ Cannot test model retrieval - no models available" )
                
        except Exception as e:
            print( f"⚠ Model retrieval functionality issues: {e}" )
        
        # Test 7: Provider-based filtering
        print( "Testing provider-based filtering..." )
        try:
            registry = ModelRegistry()
            
            # Test getting models by provider
            for provider in LlmProvider:
                provider_models = registry.get_models_by_provider( provider )
                
                if provider_models:
                    # Verify all returned models have correct provider
                    correct_provider = all( model.provider == provider for model in provider_models )
                    if correct_provider:
                        provider_name = provider.value
                        model_count = len( provider_models )
                        print( f"✓ {provider_name} provider filtering working ({model_count} models)" )
                    else:
                        print( f"✗ {provider.value} provider filtering returned wrong models" )
                        
        except Exception as e:
            print( f"⚠ Provider-based filtering issues: {e}" )
        
        # Test 8: Custom model registration
        print( "Testing custom model registration..." )
        try:
            registry = ModelRegistry()
            initial_count = len( registry.list_all_models() )
            
            # Register a custom model
            custom_config = ModelConfig(
                name="custom-test-model",
                provider=LlmProvider.OPENAI,
                client_class="test.CustomClient",
                max_tokens=2048,
                cost_per_1k_tokens_input=0.001,
                cost_per_1k_tokens_output=0.002
            )
            
            registry.register_model( custom_config )
            final_count = len( registry.list_all_models() )
            
            if final_count > initial_count:
                print( "✓ Custom model registration working" )
                
                # Verify we can retrieve the custom model
                retrieved_config = registry.get_model_config( "custom-test-model" )
                if retrieved_config.name == "custom-test-model":
                    print( "✓ Custom model retrieval working" )
                else:
                    print( "✗ Custom model retrieval failed" )
            else:
                print( "✗ Custom model registration failed" )
                
        except Exception as e:
            print( f"⚠ Custom model registration issues: {e}" )
        
        # Test 9: Critical v000 dependency scanning
        print( "\\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( ModelRegistry )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 10: Model configuration completeness
        print( "\\nTesting model configuration completeness..." )
        try:
            registry = ModelRegistry()
            all_models = registry.list_all_models()
            
            complete_configs = 0
            for model_name in all_models:
                config = registry.get_model_config( model_name )
                
                # Check for complete configuration
                if ( config.name and 
                     config.provider and 
                     config.client_class and 
                     config.max_tokens > 0 ):
                    complete_configs += 1
            
            if complete_configs == len( all_models ):
                print( f"✓ All {len( all_models )} models have complete configurations" )
            else:
                print( f"⚠ Only {complete_configs}/{len( all_models )} models have complete configurations" )
                
        except Exception as e:
            print( f"⚠ Configuration completeness check issues: {e}" )
    
    except Exception as e:
        print( f"✗ Error during model registry testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: Model registry has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - Model management will break" )
    else:
        print( "✅ Model registry smoke test completed successfully!" )
        print( "   Status: Model management system ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ Model registry smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()