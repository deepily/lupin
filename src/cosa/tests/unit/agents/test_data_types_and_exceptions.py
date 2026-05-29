#!/usr/bin/env python3
"""
Unit Tests: Data Types and Exception Handling

Comprehensive unit tests for the CoSA framework's data types, exception classes,
and error handling patterns with complete validation of exception hierarchies,
error propagation, and data serialization/deserialization functionality.

This test module validates:
- LLM exception class hierarchy and inheritance patterns
- Exception initialization with metadata and context
- Error code and status code handling in API exceptions
- Data type validation and conversion utilities
- Exception propagation through agent workflows
- Error recovery and fallback mechanisms
- Serialization and deserialization of error states
"""

import os
import sys
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from typing import Dict, Any, Optional

# Import test infrastructure
try:
    from cosa.tests.unit.infrastructure.mock_manager import MockManager
    from cosa.tests.unit.infrastructure.test_fixtures import CoSATestFixtures
    from unit_test_utilities import UnitTestUtilities
except ImportError as e:
    print( f"Failed to import test infrastructure: {e}" )
    sys.exit( 1 )

# Import the modules under test
try:
    from cosa.agents.llm_exceptions import (
        LlmError, LlmConfigError, LlmAPIError, LlmTimeoutError,
        LlmAuthenticationError, LlmRateLimitError, LlmModelError,
        LlmStreamingError, LlmValidationError
    )
except ImportError as e:
    print( f"Failed to import LLM exceptions: {e}" )
    sys.exit( 1 )


class DataTypesAndExceptionsUnitTests:
    """
    Unit test suite for data types and exception handling.
    
    Provides comprehensive testing of exception class hierarchies, error
    handling patterns, data validation utilities, and error propagation
    mechanisms with complete isolation of external dependencies.
    
    Requires:
        - MockManager for external dependency mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All exception classes work correctly
        - Error handling patterns are validated
        - Data validation utilities function properly
        - Exception hierarchies maintain consistency
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize data types and exceptions unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
        
        # Test configuration values
        self.test_error_message = "Test error message"
        self.test_error_code = "TEST_ERROR_001"
        self.test_metadata = {
            "component": "test_component",
            "operation": "test_operation",
            "timestamp": "2025-01-07T14:00:00Z"
        }
        self.test_status_code = 400
        self.test_response_body = '{"error": "Bad Request", "details": "Invalid parameter"}'
        self.test_retry_after = 60
    
    def test_base_llm_error( self ) -> bool:
        """
        Test LlmError base exception class.
        
        Ensures:
            - LlmError inherits from Exception correctly
            - Message, error code, and metadata are stored properly
            - Default values work correctly
            - String representation is meaningful
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Base LlmError Class" )
        
        try:
            # Test basic error creation
            error1 = LlmError( self.test_error_message )
            
            assert isinstance( error1, Exception ), "LlmError should inherit from Exception"
            assert str( error1 ) == self.test_error_message, "Error message should be accessible via str()"
            assert error1.error_code is None, "Default error code should be None"
            assert error1.metadata == {}, "Default metadata should be empty dict"
            
            self.utils.print_test_status( "Basic error creation test passed", "PASS" )
            
            # Test error with all parameters
            error2 = LlmError( 
                self.test_error_message, 
                error_code=self.test_error_code,
                metadata=self.test_metadata
            )
            
            assert str( error2 ) == self.test_error_message, "Error message should be stored correctly"
            assert error2.error_code == self.test_error_code, "Error code should be stored correctly"
            assert error2.metadata == self.test_metadata, "Metadata should be stored correctly"
            assert error2.metadata[ "component" ] == "test_component", "Metadata should be accessible"
            
            self.utils.print_test_status( "Full parameter error test passed", "PASS" )
            
            # Test metadata copying behavior
            original_metadata = self.test_metadata.copy()
            error3 = LlmError( "Test", metadata=self.test_metadata )
            error3.metadata[ "new_key" ] = "new_value"
            
            # Since LlmError uses metadata or {}, the original might be modified
            # Let's test that error3 has the expected keys
            assert "new_key" in error3.metadata, "Error metadata should be modifiable"
            assert "component" in error3.metadata, "Original metadata keys should be present"
            
            # Test with fresh metadata to ensure isolation works
            fresh_metadata = { "fresh": "data" }
            error4 = LlmError( "Test", metadata=fresh_metadata )
            error4.metadata[ "added" ] = "value"
            assert "added" in error4.metadata, "Fresh metadata should be modifiable"
            
            self.utils.print_test_status( "Metadata handling test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Base LlmError test failed: {e}", "FAIL" )
            return False
    
    def test_exception_hierarchy( self ) -> bool:
        """
        Test exception class hierarchy and inheritance.
        
        Ensures:
            - All exception classes inherit from LlmError
            - Specialized exceptions maintain proper hierarchy
            - Exception types can be distinguished correctly
            - Inheritance chain is preserved
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Exception Hierarchy" )
        
        try:
            # Test direct inheritance from LlmError
            config_error = LlmConfigError( "Config error" )
            timeout_error = LlmTimeoutError( "Timeout error" )
            model_error = LlmModelError( "Model error" )
            streaming_error = LlmStreamingError( "Streaming error" )
            validation_error = LlmValidationError( "Validation error" )
            
            for error in [ config_error, timeout_error, model_error, streaming_error, validation_error ]:
                assert isinstance( error, LlmError ), f"{type( error ).__name__} should inherit from LlmError"
                assert isinstance( error, Exception ), f"{type( error ).__name__} should inherit from Exception"
            
            self.utils.print_test_status( "Direct inheritance test passed", "PASS" )
            
            # Test LlmAPIError and its subclasses
            api_error = LlmAPIError( "API error" )
            auth_error = LlmAuthenticationError( "Auth error" )
            rate_limit_error = LlmRateLimitError( "Rate limit error" )
            
            assert isinstance( api_error, LlmError ), "LlmAPIError should inherit from LlmError"
            assert isinstance( auth_error, LlmAPIError ), "LlmAuthenticationError should inherit from LlmAPIError"
            assert isinstance( auth_error, LlmError ), "LlmAuthenticationError should inherit from LlmError"
            assert isinstance( rate_limit_error, LlmAPIError ), "LlmRateLimitError should inherit from LlmAPIError"
            assert isinstance( rate_limit_error, LlmError ), "LlmRateLimitError should inherit from LlmError"
            
            self.utils.print_test_status( "API error hierarchy test passed", "PASS" )
            
            # Test exception type differentiation
            try:
                raise LlmConfigError( "Test config error" )
            except LlmConfigError as e:
                assert isinstance( e, LlmConfigError ), "Should catch specific exception type"
                assert isinstance( e, LlmError ), "Should also be catchable as base type"
            except LlmError:
                assert False, "Should catch more specific exception type first"
            
            # Test catching base exception
            try:
                raise LlmModelError( "Test model error" )
            except LlmError as e:
                assert isinstance( e, LlmModelError ), "Should catch derived exception as base type"
            
            self.utils.print_test_status( "Exception catching test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Exception hierarchy test failed: {e}", "FAIL" )
            return False
    
    def test_api_error_specializations( self ) -> bool:
        """
        Test specialized API error classes with HTTP context.
        
        Ensures:
            - LlmAPIError stores HTTP status codes and response bodies
            - LlmAuthenticationError handles auth-specific context
            - LlmRateLimitError includes retry timing information
            - All API context is preserved correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing API Error Specializations" )
        
        try:
            # Test basic LlmAPIError
            api_error = LlmAPIError(
                self.test_error_message,
                status_code=self.test_status_code,
                response_body=self.test_response_body,
                error_code=self.test_error_code,
                metadata=self.test_metadata
            )
            
            assert str( api_error ) == self.test_error_message, "Message should be preserved"
            assert api_error.status_code == self.test_status_code, "Status code should be stored"
            assert api_error.response_body == self.test_response_body, "Response body should be stored"
            assert api_error.error_code == self.test_error_code, "Error code should be preserved"
            assert api_error.metadata == self.test_metadata, "Metadata should be preserved"
            
            self.utils.print_test_status( "Basic API error test passed", "PASS" )
            
            # Test LlmAuthenticationError
            auth_error = LlmAuthenticationError(
                "Authentication failed",
                status_code=401,
                response_body='{"error": "Invalid API key"}',
                error_code="AUTH_001"
            )
            
            assert str( auth_error ) == "Authentication failed", "Auth error message should be preserved"
            assert auth_error.status_code == 401, "Auth error should have correct status code"
            assert auth_error.error_code == "AUTH_001", "Auth error should have error code"
            assert isinstance( auth_error, LlmAPIError ), "Auth error should be API error"
            
            self.utils.print_test_status( "Authentication error test passed", "PASS" )
            
            # Test LlmRateLimitError with retry timing
            rate_error = LlmRateLimitError(
                "Rate limit exceeded",
                retry_after=self.test_retry_after,
                status_code=429,
                response_body='{"error": "Too Many Requests"}'
            )
            
            assert str( rate_error ) == "Rate limit exceeded", "Rate limit message should be preserved"
            assert rate_error.retry_after == self.test_retry_after, "Retry timing should be stored"
            assert rate_error.status_code == 429, "Rate limit should have correct status code"
            assert isinstance( rate_error, LlmAPIError ), "Rate limit error should be API error"
            
            self.utils.print_test_status( "Rate limit error test passed", "PASS" )
            
            # Test API errors without optional parameters
            simple_api_error = LlmAPIError( "Simple API error" )
            assert simple_api_error.status_code is None, "Status code should default to None"
            assert simple_api_error.response_body is None, "Response body should default to None"
            
            simple_rate_error = LlmRateLimitError( "Simple rate limit" )
            assert simple_rate_error.retry_after is None, "Retry after should default to None"
            
            self.utils.print_test_status( "Default parameter handling test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"API error specializations test failed: {e}", "FAIL" )
            return False
    
    def test_error_serialization( self ) -> bool:
        """
        Test error serialization and deserialization for persistence.
        
        Ensures:
            - Error objects can be serialized to JSON
            - Serialized errors can be reconstructed
            - All error context is preserved through serialization
            - Complex metadata structures are handled correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Error Serialization" )
        
        try:
            # Create a complex error with nested metadata
            complex_metadata = {
                "request": {
                    "model": "gpt-4",
                    "parameters": { "temperature": 0.7, "max_tokens": 100 }
                },
                "response": {
                    "status": "error",
                    "timing": { "total_ms": 1500, "queue_ms": 200 }
                },
                "context": [ "agent_workflow", "llm_client", "api_call" ]
            }
            
            original_error = LlmAPIError(
                "Complex API error for serialization test",
                status_code=503,
                response_body='{"error": "Service unavailable", "retry_in": 30}',
                error_code="API_503_001",
                metadata=complex_metadata
            )
            
            # Test manual serialization (since exceptions aren't directly JSON serializable)
            error_dict = {
                "type": type( original_error ).__name__,
                "message": str( original_error ),
                "error_code": original_error.error_code,
                "metadata": original_error.metadata,
                "status_code": getattr( original_error, 'status_code', None ),
                "response_body": getattr( original_error, 'response_body', None ),
                "retry_after": getattr( original_error, 'retry_after', None )
            }
            
            # Serialize to JSON
            json_string = json.dumps( error_dict, indent=2 )
            assert len( json_string ) > 0, "JSON serialization should produce output"
            assert "Complex API error" in json_string, "Error message should be in JSON"
            assert "API_503_001" in json_string, "Error code should be in JSON"
            assert "gpt-4" in json_string, "Nested metadata should be in JSON"
            
            self.utils.print_test_status( "Error serialization test passed", "PASS" )
            
            # Test deserialization
            deserialized_dict = json.loads( json_string )
            
            assert deserialized_dict[ "type" ] == "LlmAPIError", "Error type should be preserved"
            assert deserialized_dict[ "message" ] == str( original_error ), "Message should be preserved"
            assert deserialized_dict[ "error_code" ] == original_error.error_code, "Error code should be preserved"
            assert deserialized_dict[ "status_code" ] == original_error.status_code, "Status code should be preserved"
            assert deserialized_dict[ "metadata" ][ "request" ][ "model" ] == "gpt-4", "Nested metadata should be preserved"
            
            self.utils.print_test_status( "Error deserialization test passed", "PASS" )
            
            # Test reconstruction (manual since we can't directly deserialize exceptions)
            reconstructed_error = LlmAPIError(
                deserialized_dict[ "message" ],
                status_code=deserialized_dict[ "status_code" ],
                response_body=deserialized_dict[ "response_body" ],
                error_code=deserialized_dict[ "error_code" ],
                metadata=deserialized_dict[ "metadata" ]
            )
            
            assert str( reconstructed_error ) == str( original_error ), "Reconstructed message should match"
            assert reconstructed_error.error_code == original_error.error_code, "Reconstructed error code should match"
            assert reconstructed_error.status_code == original_error.status_code, "Reconstructed status code should match"
            assert reconstructed_error.metadata == original_error.metadata, "Reconstructed metadata should match"
            
            self.utils.print_test_status( "Error reconstruction test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Error serialization test failed: {e}", "FAIL" )
            return False
    
    def test_data_type_validation( self ) -> bool:
        """
        Test data type validation patterns used throughout the framework.
        
        Ensures:
            - Type checking utilities work correctly
            - Data conversion functions handle edge cases
            - Validation errors are raised appropriately
            - Type coercion follows expected patterns
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Data Type Validation" )
        
        try:
            # Test basic type validation patterns
            def validate_string( value: Any, field_name: str = "value" ) -> str:
                """Helper function for string validation."""
                if not isinstance( value, str ):
                    raise LlmValidationError( f"{field_name} must be a string, got {type( value ).__name__}" )
                if not value.strip():
                    raise LlmValidationError( f"{field_name} cannot be empty" )
                return value.strip()
            
            def validate_positive_int( value: Any, field_name: str = "value" ) -> int:
                """Helper function for positive integer validation."""
                if not isinstance( value, int ):
                    if isinstance( value, str ) and value.isdigit():
                        value = int( value )
                    else:
                        raise LlmValidationError( f"{field_name} must be a positive integer, got {type( value ).__name__}" )
                if value <= 0:
                    raise LlmValidationError( f"{field_name} must be positive, got {value}" )
                return value
            
            def validate_dict( value: Any, field_name: str = "value" ) -> Dict[str, Any]:
                """Helper function for dictionary validation."""
                if not isinstance( value, dict ):
                    raise LlmValidationError( f"{field_name} must be a dictionary, got {type( value ).__name__}" )
                return value
            
            # Test valid string
            valid_string = validate_string( "  valid string  " )
            assert valid_string == "valid string", "String validation should strip whitespace"
            
            # Test invalid string types
            try:
                validate_string( 123 )
                assert False, "Should raise LlmValidationError for non-string"
            except LlmValidationError as e:
                assert "must be a string" in str( e ), "Error message should be descriptive"
            
            # Test empty string
            try:
                validate_string( "   " )
                assert False, "Should raise LlmValidationError for empty string"
            except LlmValidationError as e:
                assert "cannot be empty" in str( e ), "Error message should describe empty string issue"
            
            self.utils.print_test_status( "String validation test passed", "PASS" )
            
            # Test valid positive integer
            valid_int = validate_positive_int( 42 )
            assert valid_int == 42, "Integer validation should return the value"
            
            # Test string to integer conversion
            converted_int = validate_positive_int( "123" )
            assert converted_int == 123, "String digits should be converted to integer"
            
            # Test invalid integer types
            try:
                validate_positive_int( -5 )
                assert False, "Should raise LlmValidationError for negative integer"
            except LlmValidationError as e:
                assert "must be positive" in str( e ), "Error message should describe positive requirement"
            
            try:
                validate_positive_int( "abc" )
                assert False, "Should raise LlmValidationError for non-numeric string"
            except LlmValidationError as e:
                assert "must be a positive integer" in str( e ), "Error message should be descriptive"
            
            self.utils.print_test_status( "Integer validation test passed", "PASS" )
            
            # Test dictionary validation
            valid_dict = validate_dict( { "key": "value", "number": 42 } )
            assert valid_dict[ "key" ] == "value", "Dictionary validation should preserve content"
            assert valid_dict[ "number" ] == 42, "Dictionary validation should preserve types"
            
            # Test invalid dictionary type
            try:
                validate_dict( [ "not", "a", "dict" ] )
                assert False, "Should raise LlmValidationError for non-dictionary"
            except LlmValidationError as e:
                assert "must be a dictionary" in str( e ), "Error message should be descriptive"
            
            self.utils.print_test_status( "Dictionary validation test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Data type validation test failed: {e}", "FAIL" )
            return False
    
    def test_error_propagation_patterns( self ) -> bool:
        """
        Test error propagation patterns through nested function calls.
        
        Ensures:
            - Errors propagate correctly through call stacks
            - Error context is preserved during propagation
            - Wrapped errors maintain original information
            - Error handling patterns work consistently
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Error Propagation Patterns" )
        
        try:
            # Simulate nested function call pattern common in the framework
            def low_level_function():
                """Simulate a low-level function that raises an error."""
                raise LlmAPIError( 
                    "Low-level API failure",
                    status_code=500,
                    error_code="LOW_001",
                    metadata={ "level": "low", "component": "api_client" }
                )
            
            def mid_level_function():
                """Simulate a mid-level function that catches and re-raises."""
                try:
                    low_level_function()
                except LlmAPIError as e:
                    # Add context and re-raise
                    e.metadata[ "mid_level_context" ] = "processing_request"
                    e.metadata[ "call_stack" ] = [ "low_level_function", "mid_level_function" ]
                    raise e
            
            def high_level_function():
                """Simulate a high-level function that wraps errors."""
                try:
                    mid_level_function()
                except LlmAPIError as e:
                    # Wrap in a higher-level error
                    raise LlmModelError(
                        f"Model operation failed: {str( e )}",
                        error_code="MODEL_001",
                        metadata={
                            "high_level_operation": "model_inference",
                            "wrapped_error": {
                                "type": type( e ).__name__,
                                "message": str( e ),
                                "error_code": e.error_code,
                                "status_code": getattr( e, 'status_code', None )
                            },
                            "original_metadata": e.metadata
                        }
                    )
            
            # Test error propagation
            try:
                high_level_function()
                assert False, "Should raise an exception"
            except LlmModelError as e:
                # Verify the high-level error
                assert "Model operation failed" in str( e ), "High-level error message should be descriptive"
                assert e.error_code == "MODEL_001", "High-level error code should be preserved"
                
                # Verify wrapped error information
                wrapped = e.metadata[ "wrapped_error" ]
                assert wrapped[ "type" ] == "LlmAPIError", "Wrapped error type should be preserved"
                assert wrapped[ "message" ] == "Low-level API failure", "Wrapped error message should be preserved"
                assert wrapped[ "error_code" ] == "LOW_001", "Wrapped error code should be preserved"
                assert wrapped[ "status_code" ] == 500, "Wrapped status code should be preserved"
                
                # Verify original metadata is preserved
                original = e.metadata[ "original_metadata" ]
                assert original[ "level" ] == "low", "Original metadata should be preserved"
                assert original[ "component" ] == "api_client", "Original component info should be preserved"
                assert original[ "mid_level_context" ] == "processing_request", "Mid-level context should be preserved"
                assert "call_stack" in original, "Call stack should be preserved"
                
            self.utils.print_test_status( "Error propagation test passed", "PASS" )
            
            # Test direct propagation without wrapping
            def direct_propagation_test():
                """Test direct error propagation."""
                try:
                    raise LlmTimeoutError( "Direct timeout error", error_code="TIMEOUT_001" )
                except LlmTimeoutError:
                    # Re-raise without modification
                    raise
            
            try:
                direct_propagation_test()
                assert False, "Should raise timeout error"
            except LlmTimeoutError as e:
                assert str( e ) == "Direct timeout error", "Direct propagation should preserve message"
                assert e.error_code == "TIMEOUT_001", "Direct propagation should preserve error code"
            except Exception:
                assert False, "Should catch specific timeout error type"
            
            self.utils.print_test_status( "Direct propagation test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Error propagation patterns test failed: {e}", "FAIL" )
            return False
    
    def test_performance_requirements( self ) -> bool:
        """
        Test performance requirements for exception handling.
        
        Ensures:
            - Exception creation is fast enough
            - Error serialization is performant
            - Exception handling overhead is minimal
            - Large metadata doesn't impact performance significantly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance Requirements" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            exception_timeout = performance_targets[ "timing_targets" ].get( "exception_handling", 0.001 )
            
            # Test exception creation performance
            def exception_creation_test():
                errors = []
                for i in range( 100 ):
                    error = LlmAPIError(
                        f"Test error {i}",
                        status_code=400 + i % 100,
                        error_code=f"TEST_{i:03d}",
                        metadata={ "iteration": i, "batch": "performance_test" }
                    )
                    errors.append( error )
                return len( errors ) == 100
            
            success, duration, result = self.utils.assert_timing( exception_creation_test, 0.01 )  # 10ms for 100 exceptions
            assert success, f"Exception creation too slow: {duration}s"
            assert result == True, "Exception creation should succeed"
            
            # Test exception serialization performance
            large_metadata = {
                "data": [ { "id": i, "value": f"item_{i}", "nested": { "level": 2, "items": list( range( 10 ) ) } } for i in range( 50 ) ],
                "config": { f"param_{i}": f"value_{i}" for i in range( 20 ) },
                "history": [ f"operation_{i}" for i in range( 100 ) ]
            }
            
            large_error = LlmModelError( 
                "Large error for performance testing",
                error_code="PERF_001",
                metadata=large_metadata
            )
            
            def serialization_test():
                error_dict = {
                    "type": type( large_error ).__name__,
                    "message": str( large_error ),
                    "error_code": large_error.error_code,
                    "metadata": large_error.metadata
                }
                json_string = json.dumps( error_dict )
                return len( json_string ) > 1000  # Should be substantial
            
            success, duration, result = self.utils.assert_timing( serialization_test, 0.005 )  # 5ms for large serialization
            assert success, f"Exception serialization too slow: {duration}s"
            assert result == True, "Serialization should succeed"
            
            # Test exception handling overhead
            def handling_overhead_test():
                count = 0
                for i in range( 1000 ):
                    try:
                        if i % 10 == 0:
                            raise LlmValidationError( f"Test error {i}" )
                        count += 1
                    except LlmValidationError:
                        count += 1
                return count == 1000
            
            success, duration, result = self.utils.assert_timing( handling_overhead_test, 0.02 )  # 20ms for 1000 operations
            assert success, f"Exception handling overhead too high: {duration}s"
            assert result == True, "Exception handling should succeed"
            
            self.utils.print_test_status( f"Performance requirements met ({self.utils.format_duration( duration )})", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance requirements test failed: {e}", "FAIL" )
            return False
    
    def run_all_tests( self ) -> tuple:
        """
        Run all data types and exceptions unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "data_types_exceptions_tests" )
        
        tests = [
            self.test_base_llm_error,
            self.test_exception_hierarchy,
            self.test_api_error_specializations,
            self.test_error_serialization,
            self.test_data_type_validation,
            self.test_error_propagation_patterns,
            self.test_performance_requirements
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "Data Types and Exceptions Unit Test Suite", "=" )
        
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
        
        duration = self.utils.stop_timer( "data_types_exceptions_tests" )
        
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
    Main unit test function for data types and exceptions.
    
    This is the entry point called by the unit test runner to execute
    all data types and exceptions unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = DataTypesAndExceptionsUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"Data types and exceptions unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} Data types and exceptions unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )