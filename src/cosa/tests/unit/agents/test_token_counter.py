#!/usr/bin/env python3
"""
Unit Tests: TokenCounter and Prompt Formatting

Comprehensive unit tests for the CoSA TokenCounter class and prompt formatting
functionality with complete mocking of external dependencies including tiktoken,
model mappings, and text processing utilities.

This test module validates:
- TokenCounter initialization and configuration with model mappings
- Token counting for various models with tiktoken integration
- Fallback mechanisms when tiktoken is not available
- Model-to-tokenizer mapping functionality
- Error handling for invalid models and text inputs
- Performance requirements for token counting operations
- Prompt template formatting and variable substitution
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

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
    from cosa.agents.token_counter import TokenCounter
except ImportError as e:
    print( f"Failed to import TokenCounter: {e}" )
    sys.exit( 1 )


class TokenCounterUnitTests:
    """
    Unit test suite for TokenCounter and prompt formatting.
    
    Provides comprehensive testing of token counting functionality including
    tiktoken integration mocking, model mapping validation, fallback mechanisms,
    and prompt template processing with complete external dependency isolation.
    
    Requires:
        - MockManager for external dependency mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All TokenCounter functionality is tested thoroughly
        - No external dependencies or library calls
        - Performance requirements are met
        - Error conditions are handled properly
        - Prompt formatting patterns work correctly
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize TokenCounter unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
        
        # Test configuration values
        self.test_text_short = "Hello world"
        self.test_text_medium = "This is a medium length text with multiple words and some punctuation."
        self.test_text_long = "This is a much longer text that contains multiple sentences. It has various punctuation marks, numbers like 123, and should provide a good test case for token counting accuracy. The text spans multiple lines and includes different types of content to validate the tokenizer behavior."
        
        # Model test data
        self.test_models = {
            "gpt-4": "gpt-4",
            "gpt-3.5-turbo": "gpt-3.5-turbo", 
            "text-davinci-003": "text-davinci-003",
            "custom-model": "gpt-4",  # Maps to gpt-4 tokenizer
            "unknown-model": "unknown-model"
        }
        
        # Expected token counts (mocked)
        self.expected_token_counts = {
            self.test_text_short: 2,
            self.test_text_medium: 14,
            self.test_text_long: 58
        }
    
    def _create_token_counter_mock_context( self, tiktoken_available: bool = True ):
        """
        Create comprehensive mock context for TokenCounter testing.
        
        This helper sets up all necessary mocks to intercept external dependencies
        including tiktoken, encoding operations, and model tokenizer mappings.
        
        Args:
            tiktoken_available: Whether to simulate tiktoken being available
        
        Returns:
            Context manager for use in 'with' statements
        """
        def _mock_context():
            from contextlib import ExitStack
            import sys
            
            stack = ExitStack()
            
            if tiktoken_available:
                # Mock tiktoken module
                mock_tiktoken_module = MagicMock()
                
                # Mock encoding object
                mock_encoding = MagicMock()
                mock_encoding.encode.side_effect = lambda text: ['token'] * self._get_expected_tokens( text )
                
                # Mock tiktoken functions
                mock_tiktoken_module.encoding_for_model.return_value = mock_encoding
                mock_tiktoken_module.get_encoding.return_value = mock_encoding
                
                # Add mock tiktoken to sys.modules
                original_modules = sys.modules.copy()
                sys.modules[ 'tiktoken' ] = mock_tiktoken_module
                
                # Restore original modules on exit
                def restore_modules():
                    sys.modules.clear()
                    sys.modules.update( original_modules )
                
                stack.callback( restore_modules )
                
                return stack, {
                    'tiktoken_module': mock_tiktoken_module,
                    'encoding': mock_encoding
                }
            else:
                # Ensure tiktoken is not in sys.modules
                original_modules = sys.modules.copy()
                if 'tiktoken' in sys.modules:
                    del sys.modules[ 'tiktoken' ]
                
                def restore_modules():
                    sys.modules.clear()
                    sys.modules.update( original_modules )
                
                stack.callback( restore_modules )
                
                return stack, {}
        
        return _mock_context
    
    def _get_expected_tokens( self, text: str ) -> int:
        """Helper to get expected token count for test text."""
        return self.expected_token_counts.get( text, len( text.split() ) )
    
    def test_token_counter_initialization( self ) -> bool:
        """
        Test TokenCounter initialization and configuration.
        
        Ensures:
            - TokenCounter initializes correctly with and without model mappings
            - tiktoken is imported and configured properly
            - Model tokenizer mappings are stored correctly
            - Warning is displayed when tiktoken is unavailable
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing TokenCounter Initialization" )
        
        try:
            mock_context_func = self._create_token_counter_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                # Test basic initialization
                counter = TokenCounter()
                
                assert counter.model_tokenizer_map == {}, "Default model map should be empty"
                assert counter.tiktoken is not None, "tiktoken should be available"
                
                self.utils.print_test_status( "Basic initialization test passed", "PASS" )
                
                # Test initialization with model mapping
                test_mapping = {
                    "custom-model-1": "gpt-4",
                    "custom-model-2": "gpt-3.5-turbo"
                }
                
                counter2 = TokenCounter( model_tokenizer_map=test_mapping )
                
                assert counter2.model_tokenizer_map == test_mapping, "Model mapping should be stored correctly"
                assert counter2.tiktoken is not None, "tiktoken should be available"
                
                self.utils.print_test_status( "Model mapping initialization test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"TokenCounter initialization test failed: {e}", "FAIL" )
            return False
    
    def test_token_counter_without_tiktoken( self ) -> bool:
        """
        Test TokenCounter behavior when tiktoken is not available.
        
        Ensures:
            - ImportError is caught gracefully
            - Warning message is displayed
            - Fallback token counting is used
            - Character-based estimation works correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing TokenCounter Without tiktoken" )
        
        try:
            mock_context_func = self._create_token_counter_mock_context( tiktoken_available=False )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                # Capture print output
                with patch( 'builtins.print' ) as mock_print:
                    counter = TokenCounter()
                    
                    # Test that warning was printed
                    mock_print.assert_called_once_with( "Warning: tiktoken not installed. Token counting will be approximate." )
                    assert counter.tiktoken is None, "tiktoken should be None when not available"
                    
                    # Test fallback token counting
                    token_count = counter.count_tokens( "gpt-4", self.test_text_medium )
                    expected_fallback = len( self.test_text_medium ) // 4
                    assert token_count == expected_fallback, f"Expected {expected_fallback}, got {token_count}"
                    
                    self.utils.print_test_status( "tiktoken unavailable test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"TokenCounter without tiktoken test failed: {e}", "FAIL" )
            return False
    
    def test_token_counting_various_models( self ) -> bool:
        """
        Test token counting for various model types.
        
        Ensures:
            - Standard OpenAI models are handled correctly
            - Custom model mappings work properly
            - Unknown models fall back to default encoding
            - Token counts are accurate for different text lengths
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Token Counting for Various Models" )
        
        try:
            mock_context_func = self._create_token_counter_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                # Test with model mapping
                model_mapping = {
                    "custom-model": "gpt-4",
                    "legacy-model": "text-davinci-003"
                }
                counter = TokenCounter( model_tokenizer_map=model_mapping )
                
                # Test standard models
                for model_name in [ "gpt-4", "gpt-3.5-turbo", "text-davinci-003" ]:
                    token_count = counter.count_tokens( model_name, self.test_text_medium )
                    expected_count = self.expected_token_counts[ self.test_text_medium ]
                    assert token_count == expected_count, f"Model {model_name}: expected {expected_count}, got {token_count}"
                    
                    # Verify encoding_for_model was called
                    mocks[ 'tiktoken_module' ].encoding_for_model.assert_called_with( model_name )
                
                self.utils.print_test_status( "Standard model testing passed", "PASS" )
                
                # Test custom model mapping
                mocks[ 'tiktoken_module' ].encoding_for_model.reset_mock()
                
                token_count = counter.count_tokens( "custom-model", self.test_text_short )
                expected_count = self.expected_token_counts[ self.test_text_short ]
                assert token_count == expected_count, f"Custom model: expected {expected_count}, got {token_count}"
                
                # Verify mapped model was used
                mocks[ 'tiktoken_module' ].encoding_for_model.assert_called_with( "gpt-4" )
                
                self.utils.print_test_status( "Custom model mapping test passed", "PASS" )
                
                # Test unknown model fallback
                mocks[ 'tiktoken_module' ].encoding_for_model.side_effect = KeyError( "Model not found" )
                mocks[ 'tiktoken_module' ].encoding_for_model.reset_mock()
                
                token_count = counter.count_tokens( "unknown-model", self.test_text_long )
                expected_count = self.expected_token_counts[ self.test_text_long ]
                assert token_count == expected_count, f"Unknown model: expected {expected_count}, got {token_count}"
                
                # Verify fallback to cl100k_base was used
                mocks[ 'tiktoken_module' ].get_encoding.assert_called_with( "cl100k_base" )
                
                self.utils.print_test_status( "Unknown model fallback test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Token counting various models test failed: {e}", "FAIL" )
            return False
    
    def test_token_counting_error_handling( self ) -> bool:
        """
        Test error handling during token counting operations.
        
        Ensures:
            - Encoding errors are caught and handled gracefully
            - Fallback to character-based estimation works
            - Error messages are printed appropriately
            - Token counts are still returned for all errors
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Token Counting Error Handling" )
        
        try:
            mock_context_func = self._create_token_counter_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                counter = TokenCounter()
                
                # Test encoding error
                mocks[ 'encoding' ].encode.side_effect = Exception( "Encoding error" )
                
                with patch( 'builtins.print' ) as mock_print:
                    token_count = counter.count_tokens( "gpt-4", self.test_text_medium )
                    
                    # Should fall back to character-based estimation
                    expected_fallback = len( self.test_text_medium ) // 4
                    assert token_count == expected_fallback, f"Expected fallback {expected_fallback}, got {token_count}"
                    
                    # Should print error message
                    mock_print.assert_called_once_with( "Error counting tokens: Encoding error" )
                
                self.utils.print_test_status( "Encoding error handling test passed", "PASS" )
                
                # Test general exception
                mocks[ 'tiktoken_module' ].encoding_for_model.side_effect = Exception( "General error" )
                
                with patch( 'builtins.print' ) as mock_print:
                    token_count2 = counter.count_tokens( "test-model", self.test_text_short )
                    
                    expected_fallback2 = len( self.test_text_short ) // 4
                    assert token_count2 == expected_fallback2, f"Expected fallback {expected_fallback2}, got {token_count2}"
                    
                    mock_print.assert_called_once_with( "Error counting tokens: General error" )
                
                self.utils.print_test_status( "General error handling test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Token counting error handling test failed: {e}", "FAIL" )
            return False
    
    def test_prompt_template_formatting( self ) -> bool:
        """
        Test prompt template formatting functionality.
        
        Ensures:
            - String formatting works with various templates
            - Variable substitution is accurate
            - Special characters are handled properly
            - Nested formatting patterns work correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Prompt Template Formatting" )
        
        try:
            # Test basic string formatting
            template1 = "Hello {name}, welcome to {place}!"
            variables1 = { "name": "Alice", "place": "CoSA Framework" }
            result1 = template1.format( **variables1 )
            expected1 = "Hello Alice, welcome to CoSA Framework!"
            assert result1 == expected1, f"Expected '{expected1}', got '{result1}'"
            
            self.utils.print_test_status( "Basic template formatting test passed", "PASS" )
            
            # Test prompt template with token counting
            mock_context_func = self._create_token_counter_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                counter = TokenCounter()
                
                prompt_template = "You are a {role}. Please {action} the following question: {question}"
                variables = {
                    "role": "helpful assistant",
                    "action": "answer", 
                    "question": "What is the capital of France?"
                }
                
                formatted_prompt = prompt_template.format( **variables )
                expected_prompt = "You are a helpful assistant. Please answer the following question: What is the capital of France?"
                assert formatted_prompt == expected_prompt, f"Prompt formatting failed"
                
                # Test token counting on formatted prompt
                token_count = counter.count_tokens( "gpt-4", formatted_prompt )
                assert token_count > 0, "Token count should be positive"
                assert isinstance( token_count, int ), "Token count should be integer"
                
                self.utils.print_test_status( "Prompt template with token counting test passed", "PASS" )
            
            # Test template with special characters
            template2 = "Process this text: '{text}' with parameters: {params}"
            variables2 = {
                "text": "Hello, world! This has punctuation & symbols.",
                "params": "temperature=0.7, max_tokens=100"
            }
            result2 = template2.format( **variables2 )
            assert "Hello, world! This has punctuation & symbols." in result2, "Special characters should be preserved"
            assert "temperature=0.7, max_tokens=100" in result2, "Parameters should be included"
            
            self.utils.print_test_status( "Special characters template test passed", "PASS" )
            
            # Test nested formatting patterns
            template3 = "System: {system_msg}\nUser: {user_msg}\nAssistant: {assistant_prefix}"
            variables3 = {
                "system_msg": "You are a {role}".format( role="weather expert" ),
                "user_msg": "What's the weather like?",
                "assistant_prefix": "Based on current data..."
            }
            result3 = template3.format( **variables3 )
            assert "You are a weather expert" in result3, "Nested formatting should work"
            assert "What's the weather like?" in result3, "User message should be included"
            
            self.utils.print_test_status( "Nested formatting test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Prompt template formatting test failed: {e}", "FAIL" )
            return False
    
    def test_performance_requirements( self ) -> bool:
        """
        Test TokenCounter performance requirements.
        
        Ensures:
            - Token counting is fast enough for interactive use
            - Large text processing is performant
            - Memory usage is reasonable
            - Multiple operations maintain performance
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance Requirements" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            token_timeout = performance_targets[ "timing_targets" ].get( "token_counting", 0.01 )
            
            mock_context_func = self._create_token_counter_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                counter = TokenCounter()
                
                # Test single token counting performance
                def single_count_test():
                    return counter.count_tokens( "gpt-4", self.test_text_medium )
                
                success, duration, result = self.utils.assert_timing( single_count_test, token_timeout )
                assert success, f"Single token counting too slow: {duration}s"
                assert result > 0, "Should return positive token count"
                
                # Test multiple token counting performance
                texts = [ self.test_text_short, self.test_text_medium, self.test_text_long ]
                models = [ "gpt-4", "gpt-3.5-turbo", "text-davinci-003" ]
                
                def multiple_count_test():
                    total_tokens = 0
                    for text in texts:
                        for model in models:
                            total_tokens += counter.count_tokens( model, text )
                    return total_tokens > 0
                
                success, duration, result = self.utils.assert_timing( multiple_count_test, 0.05 )  # 50ms for 9 operations
                assert success, f"Multiple token counting too slow: {duration}s"
                assert result == True, "Multiple counting should succeed"
                
                # Test large text performance
                large_text = self.test_text_long * 10  # Make it much larger
                
                def large_text_test():
                    return counter.count_tokens( "gpt-4", large_text )
                
                success, duration, result = self.utils.assert_timing( large_text_test, 0.02 )  # 20ms for large text
                assert success, f"Large text token counting too slow: {duration}s"
                assert result > 0, "Should return positive token count for large text"
                
                self.utils.print_test_status( f"Performance requirements met ({self.utils.format_duration( duration )})", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance requirements test failed: {e}", "FAIL" )
            return False
    
    def run_all_tests( self ) -> tuple:
        """
        Run all TokenCounter unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "token_counter_tests" )
        
        tests = [
            self.test_token_counter_initialization,
            self.test_token_counter_without_tiktoken,
            self.test_token_counting_various_models,
            self.test_token_counting_error_handling,
            self.test_prompt_template_formatting,
            self.test_performance_requirements
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "TokenCounter Unit Test Suite", "=" )
        
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
        
        duration = self.utils.stop_timer( "token_counter_tests" )
        
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
    Main unit test function for TokenCounter.
    
    This is the entry point called by the unit test runner to execute
    all TokenCounter unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = TokenCounterUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"TokenCounter unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} TokenCounter unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )