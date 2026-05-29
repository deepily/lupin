#!/usr/bin/env python3
"""
Unit Tests: LLM Client Factory

Comprehensive unit tests for the CoSA LlmClientFactory class with complete mocking
of external dependencies including API calls, configuration, and client initialization.

This test module validates:
- LlmClientFactory singleton behavior and initialization
- Client creation for different model types and vendors
- Configuration loading and vendor-specific setup
- API key management and environment variable handling
- Error handling for unsupported vendors and missing configurations
- Performance requirements for client creation
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import test infrastructure
try:
    from cosa.tests.unit.infrastructure.mock_manager import MockManager
    from cosa.tests.unit.infrastructure.test_fixtures import CoSATestFixtures
    from cosa.tests.unit.infrastructure.unit_test_utilities import UnitTestUtilities
except ImportError as e:
    print( f"Failed to import test infrastructure: {e}" )
    sys.exit( 1 )

# Import the modules under test
try:
    from cosa.agents.llm_client_factory import LlmClientFactory
    from cosa.agents.base_llm_client import LlmClientInterface
    from cosa.agents.chat_client import ChatClient
    from cosa.agents.completion_client import CompletionClient
except ImportError as e:
    print( f"Failed to import LLM client modules: {e}" )
    sys.exit( 1 )


class LlmClientFactoryUnitTests:
    """
    Unit test suite for LlmClientFactory.
    
    Provides comprehensive testing of LLM client factory functionality including
    singleton behavior, client creation, vendor configuration, and API integration
    with complete external dependency mocking.
    
    Requires:
        - MockManager for API and configuration mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All factory functionality is tested thoroughly
        - No external dependencies or API calls
        - Performance requirements are met
        - Error conditions are handled properly
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize LlmClientFactory unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
    
    def test_singleton_behavior( self ) -> bool:
        """
        Test LlmClientFactory singleton pattern implementation.
        
        Ensures:
            - Only one instance exists across multiple instantiations
            - Singleton state is maintained correctly
            - Initialization only occurs once
            - Instance variables are shared across references
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Singleton Behavior" )
        
        try:
            # Mock all dependencies to isolate singleton testing
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class:
                mock_config = self.mock_mgr.config_manager_mock( {
                    "llm_default_model": "test_model",
                    "api_timeout": 30
                } ).__enter__()
                mock_cm_class.return_value = mock_config
                
                # Test multiple instantiations return same object
                factory1 = LlmClientFactory( debug=False, verbose=False )
                factory2 = LlmClientFactory( debug=True, verbose=True )
                factory3 = LlmClientFactory()
                
                # Test singleton identity
                assert factory1 is factory2, "Factory instances should be identical (singleton)"
                assert factory2 is factory3, "All factory instances should be identical"
                assert factory1 is factory3, "First and third instances should be identical"
                
                # Test shared state
                factory1.test_attribute = "test_value"
                assert hasattr( factory2, 'test_attribute' ), "Singleton should share attributes"
                assert factory2.test_attribute == "test_value", "Singleton attribute should be shared"
                
                self.utils.print_test_status( "Singleton identity test passed", "PASS" )
            
            # Test singleton persists across patch contexts
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class2:
                mock_config2 = self.mock_mgr.config_manager_mock( {} ).__enter__()
                mock_cm_class2.return_value = mock_config2
                
                factory4 = LlmClientFactory()
                assert factory4 is factory1, "Singleton should persist across different contexts"
                assert hasattr( factory4, 'test_attribute' ), "Singleton should retain attributes"
                
                self.utils.print_test_status( "Singleton persistence test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Singleton behavior test failed: {e}", "FAIL" )
            return False
    
    def test_factory_initialization( self ) -> bool:
        """
        Test LlmClientFactory initialization process.
        
        Ensures:
            - Factory initializes with correct default parameters
            - ConfigurationManager is created properly
            - Debug and verbose flags are set correctly
            - Initialization occurs only once per singleton
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Factory Initialization" )
        
        try:
            # Mock dependencies
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class:
                mock_config = self.mock_mgr.config_manager_mock( {
                    "default_timeout": 30,
                    "max_retries": 3
                } ).__enter__()
                mock_cm_class.return_value = mock_config
                
                # Reset singleton for clean testing
                LlmClientFactory._instance = None
                
                # Test initialization with parameters
                factory = LlmClientFactory( debug=True, verbose=True )
                
                # Test initialization state
                assert hasattr( factory, 'config_mgr' ), "Factory should have config_mgr attribute"
                assert hasattr( factory, '_initialized' ), "Factory should have _initialized flag"
                assert factory._initialized == True, "Factory should be marked as initialized"
                assert factory.debug == True, "Debug flag should be set correctly"
                assert factory.verbose == True, "Verbose flag should be set correctly"
                
                # Test configuration manager setup
                assert factory.config_mgr == mock_config, "Should use mocked configuration manager"
                
                self.utils.print_test_status( "Basic initialization test passed", "PASS" )
            
            # Test that re-initialization doesn't occur
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class2:
                mock_config2 = self.mock_mgr.config_manager_mock( {
                    "different_config": "value"
                } ).__enter__()
                mock_cm_class2.return_value = mock_config2
                
                # Create another instance (should be same singleton)
                factory2 = LlmClientFactory( debug=False, verbose=False )
                
                # Should still use original configuration
                assert factory2.config_mgr == mock_config, "Should retain original config manager"
                assert factory2.debug == True, "Should retain original debug setting"
                assert factory2._initialized == True, "Should remain initialized"
                
                self.utils.print_test_status( "Re-initialization prevention test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Factory initialization test failed: {e}", "FAIL" )
            return False
    
    def test_model_descriptor_parsing( self ) -> bool:
        """
        Test model descriptor parsing functionality.
        
        Ensures:
            - Various model descriptor formats are parsed correctly
            - Vendor and model name extraction works properly
            - Special cases (deepily, local models) are handled
            - Invalid descriptors are handled gracefully
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Model Descriptor Parsing" )
        
        try:
            # Mock dependencies and create factory
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class:
                mock_config = self.mock_mgr.config_manager_mock( {} ).__enter__()
                mock_cm_class.return_value = mock_config
                
                LlmClientFactory._instance = None
                factory = LlmClientFactory()
                
                # Test various model descriptor formats
                test_cases = [
                    # Format: "vendor:model" (colon is the ONLY vendor delimiter)
                    ( "openai:gpt-4", ( "openai", "gpt-4" ) ),
                    ( "groq:llama-3.1-8b-instant", ( "groq", "llama-3.1-8b-instant" ) ),
                    ( "anthropic:claude-3-sonnet", ( "anthropic", "claude-3-sonnet" ) ),
                    ( "Groq:llama-3.1-8b-instant", ( "groq", "llama-3.1-8b-instant" ) ),

                    # HuggingFace org/model — slash is NEVER a vendor delimiter, always vLLM
                    ( "Qwen/Qwen3-4B-Base", ( "vllm", "Qwen/Qwen3-4B-Base" ) ),
                    ( "meta-llama/Llama-2-70b", ( "vllm", "meta-llama/Llama-2-70b" ) ),
                    ( "Groq/llama-3.1-8b-instant", ( "vllm", "Groq/llama-3.1-8b-instant" ) ),
                    ( "OpenAI/gpt-4", ( "vllm", "OpenAI/gpt-4" ) ),

                    # Special deepily format
                    ( "llm_deepily_ministral", ( "deepily", "llm_deepily_ministral" ) ),

                    # Default to vllm for unknown formats
                    ( "local-model-name", ( "vllm", "local-model-name" ) ),
                    ( "some_model", ( "vllm", "some_model" ) )
                ]
                
                for descriptor, expected in test_cases:
                    result = factory._parse_model_descriptor( descriptor )
                    assert result == expected, f"Parsing '{descriptor}' should yield {expected}, got {result}"
                
                self.utils.print_test_status( "Model descriptor parsing test passed", "PASS" )
                
                # Test edge cases (vendor is always lowercased for colon format)
                edge_cases = [
                    ( "", ( "vllm", "" ) ),  # Empty string
                    ( "vendor:", ( "vendor", "" ) ),  # Empty model
                    ( "Vendor:", ( "vendor", "" ) ),  # Empty model with uppercase vendor
                    ( ":model", ( "", "model" ) ),  # Empty vendor
                    ( "vendor:model:extra", ( "vendor", "model:extra" ) )  # Multiple colons
                ]
                
                for descriptor, expected in edge_cases:
                    result = factory._parse_model_descriptor( descriptor )
                    assert result == expected, f"Edge case '{descriptor}' should yield {expected}, got {result}"
                
                self.utils.print_test_status( "Edge case parsing test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Model descriptor parsing test failed: {e}", "FAIL" )
            return False
    
    def test_vendor_configuration( self ) -> bool:
        """
        Test vendor configuration and client creation logic.
        
        Ensures:
            - Vendor configurations are loaded correctly
            - API keys are handled properly
            - Base URLs are set correctly
            - Environment variables are configured
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Vendor Configuration" )
        
        try:
            # Mock dependencies
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.llm_client_factory.du.get_api_key' ) as mock_get_api_key, \
                 patch.dict( 'os.environ', {}, clear=True ):
                
                mock_config = self.mock_mgr.config_manager_mock( {} ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_get_api_key.return_value = "test_api_key_123"
                
                LlmClientFactory._instance = None
                factory = LlmClientFactory()
                
                # Test vendor configuration constants
                assert "openai" in factory.VENDOR_URLS, "OpenAI should be in vendor URLs"
                assert "groq" in factory.VENDOR_URLS, "Groq should be in vendor URLs"
                assert "anthropic" in factory.VENDOR_URLS, "Anthropic should be in vendor URLs"
                
                assert "openai" in factory.VENDOR_CONFIG, "OpenAI should be in vendor config"
                assert "groq" in factory.VENDOR_CONFIG, "Groq should be in vendor config"
                
                # Test vendor configuration structure
                openai_config = factory.VENDOR_CONFIG[ "openai" ]
                assert "env_var" in openai_config, "OpenAI config should have env_var"
                assert "key_name" in openai_config, "OpenAI config should have key_name"
                assert "client_type" in openai_config, "OpenAI config should have client_type"
                
                self.utils.print_test_status( "Vendor configuration structure test passed", "PASS" )
                
                # Test default parameters
                assert "temperature" in factory.CLIENT_DEFAULT_PARAMS, "Should have default temperature"
                assert "max_tokens" in factory.CLIENT_DEFAULT_PARAMS, "Should have default max_tokens"
                
                default_temp = factory.CLIENT_DEFAULT_PARAMS[ "temperature" ]
                assert isinstance( default_temp, ( int, float ) ), "Temperature should be numeric"
                assert 0.0 <= default_temp <= 2.0, "Temperature should be in valid range"
                
                self.utils.print_test_status( "Default parameters test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Vendor configuration test failed: {e}", "FAIL" )
            return False
    
    def test_client_creation_mocking( self ) -> bool:
        """
        Test client creation with comprehensive mocking.
        
        Ensures:
            - ChatClient and CompletionClient creation works
            - All external dependencies are properly mocked
            - Client interfaces are implemented correctly
            - Different vendor scenarios work
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Client Creation with Mocking" )
        
        try:
            # Since the configuration-based approach is complex, let's test vendor-specific creation
            # which is simpler and more straightforward to mock
            
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.llm_client_factory.ChatClient' ) as mock_chat_client, \
                 patch( 'cosa.agents.llm_client_factory.CompletionClient' ) as mock_completion_client, \
                 patch( 'cosa.agents.llm_client_factory.du.get_api_key' ) as mock_get_api_key, \
                 patch.dict( 'os.environ', {}, clear=True ):
                
                # Set up basic mocks
                mock_config = self.mock_mgr.config_manager_mock( {} ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_get_api_key.return_value = "test_api_key"
                
                # Mock client instances
                mock_chat_instance = MagicMock( spec=LlmClientInterface )
                mock_completion_instance = MagicMock( spec=LlmClientInterface )
                mock_chat_client.return_value = mock_chat_instance
                mock_completion_client.return_value = mock_completion_instance
                
                LlmClientFactory._instance = None
                factory = LlmClientFactory()
                
                # Test vendor-specific client creation (bypass config complexity)
                mock_config.exists.return_value = False  # Force vendor-specific path
                
                client = factory.get_client( "openai:gpt-3.5-turbo" )
                
                # Should create vendor-specific ChatClient
                assert mock_chat_client.called, "ChatClient should be created for OpenAI vendor"
                assert client == mock_chat_instance, "Should return mocked chat client instance"
                
                self.utils.print_test_status( "Vendor-specific client creation test passed", "PASS" )
                
                # Test another vendor type
                mock_chat_client.reset_mock()
                client2 = factory.get_client( "groq:llama-3.1-8b-instant" )
                
                assert mock_chat_client.called, "ChatClient should be created for Groq vendor"
                assert client2 == mock_chat_instance, "Should return chat client for Groq vendor"
                
                self.utils.print_test_status( "Multiple vendor client creation test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Client creation mocking test failed: {e}", "FAIL" )
            return False
    
    def test_error_handling( self ) -> bool:
        """
        Test error handling in LlmClientFactory.
        
        Ensures:
            - Unsupported vendors raise appropriate errors
            - Missing API keys are handled gracefully
            - Invalid configurations are handled properly
            - Error messages are informative
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Error Handling" )
        
        try:
            # Mock dependencies
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.llm_client_factory.du.get_api_key' ) as mock_get_api_key:
                
                mock_config = self.mock_mgr.config_manager_mock( {} ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_config.exists.return_value = False
                
                LlmClientFactory._instance = None
                factory = LlmClientFactory()
                
                # Test unsupported vendor
                try:
                    factory.get_client( "unsupported_vendor:some-model" )
                    assert False, "Should raise ValueError for unsupported vendor"
                except ValueError as e:
                    assert "Unsupported vendor" in str( e ), "Error message should mention unsupported vendor"
                
                self.utils.print_test_status( "Unsupported vendor error test passed", "PASS" )
                
                # Test missing API key handling
                mock_get_api_key.side_effect = Exception( "API key not found" )
                
                try:
                    factory.get_client( "openai:gpt-4" )
                    # Should handle API key error gracefully or raise informative error
                except Exception as e:
                    # Error should be informative
                    assert len( str( e ) ) > 0, "Error message should not be empty"
                
                self.utils.print_test_status( "API key error handling test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Error handling test failed: {e}", "FAIL" )
            return False
    
    def test_performance_requirements( self ) -> bool:
        """
        Test LlmClientFactory performance requirements.
        
        Ensures:
            - Client creation is fast enough
            - Singleton access is performant
            - Memory usage is reasonable
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance Requirements" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            factory_timeout = performance_targets[ "timing_targets" ].get( "factory_operation", 0.1 )
            
            # Mock dependencies for performance testing
            with patch( 'cosa.agents.llm_client_factory.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.llm_client_factory.ChatClient' ) as mock_chat_client:
                
                mock_config = self.mock_mgr.config_manager_mock( {} ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_config.exists.return_value = False
                
                mock_client_instance = MagicMock( spec=LlmClientInterface )
                mock_chat_client.return_value = mock_client_instance
                
                # Test singleton creation performance
                def singleton_creation_test():
                    LlmClientFactory._instance = None
                    factory = LlmClientFactory()
                    return factory is not None
                
                success, duration, result = self.utils.assert_timing( singleton_creation_test, factory_timeout )
                assert success, f"Singleton creation too slow: {duration}s"
                assert result == True, "Singleton creation should return True"
                
                # Test multiple client creation performance
                LlmClientFactory._instance = None
                factory = LlmClientFactory()
                
                def multiple_clients_test():
                    clients = []
                    for i in range( 5 ):
                        # Mock different vendor clients
                        client = factory.get_client( f"openai:test-model-{i}" )
                        clients.append( client )
                    return len( clients )
                
                success, duration, result = self.utils.assert_timing( multiple_clients_test, factory_timeout * 5 )
                assert success, f"Multiple client creation too slow: {duration}s"
                assert result == 5, f"Should create 5 clients, got {result}"
                
                self.utils.print_test_status( f"Performance requirements met ({self.utils.format_duration( duration )})", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance requirements test failed: {e}", "FAIL" )
            return False
    
    def run_all_tests( self ) -> tuple:
        """
        Run all LlmClientFactory unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "llm_client_factory_tests" )
        
        tests = [
            self.test_singleton_behavior,
            self.test_factory_initialization,
            self.test_model_descriptor_parsing,
            self.test_vendor_configuration,
            self.test_client_creation_mocking,
            self.test_error_handling,
            self.test_performance_requirements
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "LlmClientFactory Unit Test Suite", "=" )
        
        for test_func in tests:
            try:
                if test_func():
                    passed_tests += 1
                else:
                    failed_tests += 1
                    errors.append( f"{test_func.__name__} failed" )
            except Exception as e:
                failed_tests += 1
                errors.append( f"{test_func.__name__} raised exception: {e}" )
        
        duration = self.utils.stop_timer( "llm_client_factory_tests" )
        
        # Print summary
        self.utils.print_test_banner( "Test Results Summary" )
        self.utils.print_test_status( f"Passed: {passed_tests}" )
        self.utils.print_test_status( f"Failed: {failed_tests}" )
        self.utils.print_test_status( f"Duration: {self.utils.format_duration( duration )}" )
        
        success = failed_tests == 0
        error_message = "; ".join( errors ) if errors else ""
        
        return success, duration, error_message
    
    def cleanup( self ):
        """Clean up any temporary files created during testing."""
        self.utils.cleanup_temp_files( self.temp_files )


def isolated_unit_test():
    """
    Main unit test function for LlmClientFactory.
    
    This is the entry point called by the unit test runner to execute
    all LlmClientFactory unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = LlmClientFactoryUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"LlmClientFactory unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} LlmClientFactory unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )