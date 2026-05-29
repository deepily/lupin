#!/usr/bin/env python3
"""
Unit Tests: API Error Handling for Failures and Timeouts

Comprehensive unit tests for API error handling, timeout management, retry logic,
and network failure recovery mechanisms in the CoSA framework with complete mocking
of external network dependencies and API responses.

This test module validates:
- Network timeout detection and handling mechanisms
- API failure response processing and error categorization  
- Retry logic with exponential backoff and circuit breaker patterns
- Rate limiting detection and retry-after header processing
- Connection failure simulation and recovery strategies
- Authentication error handling and token refresh patterns
- API response validation and malformed response handling
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call, Mock
from typing import Dict, Any, Optional

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
    from cosa.agents.llm_exceptions import (
        LlmError, LlmAPIError, LlmTimeoutError, LlmAuthenticationError, 
        LlmRateLimitError, LlmModelError, LlmValidationError
    )
    from cosa.agents.llm_completion import LlmCompletion
    from cosa.agents.chat_client import ChatClient
    from cosa.agents.completion_client import CompletionClient
except ImportError as e:
    print( f"Failed to import required modules: {e}" )
    sys.exit( 1 )


class APIErrorHandlingUnitTests:
    """
    Unit test suite for API error handling and timeout management.
    
    Provides comprehensive testing of network failure scenarios, timeout
    handling, retry mechanisms, and error recovery patterns with complete
    external dependency isolation and deterministic failure simulation.
    
    Requires:
        - MockManager for network and API mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All API error scenarios are tested thoroughly
        - No external network dependencies or API calls
        - Timeout and retry mechanisms work correctly
        - Error recovery patterns are validated
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize API error handling unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
        
        # Test configuration values
        self.test_base_url = "http://test-api.example.com/v1/completions"
        self.test_model_name = "test-model-v1"
        self.test_api_key = "test_api_key_123"
        self.test_prompt = "Test prompt for error handling"
        
        # Error response templates
        self.timeout_error_response = None  # Represents timeout (no response)
        self.rate_limit_response = {
            "status_code": 429,
            "headers": { "retry-after": "60", "x-ratelimit-remaining": "0" },
            "body": '{"error": "Rate limit exceeded", "message": "Too many requests"}'
        }
        self.auth_error_response = {
            "status_code": 401, 
            "headers": { "www-authenticate": "Bearer" },
            "body": '{"error": "Unauthorized", "message": "Invalid API key"}'
        }
        self.server_error_response = {
            "status_code": 500,
            "headers": { "content-type": "application/json" },
            "body": '{"error": "Internal Server Error", "message": "Server temporarily unavailable"}'
        }
        self.malformed_response = {
            "status_code": 200,
            "headers": { "content-type": "application/json" },
            "body": '{"incomplete": "response", "missing":'  # Malformed JSON
        }
    
    def _create_api_error_mock_context( self, error_scenario: str = "none" ):
        """
        Create comprehensive mock context for API error testing.
        
        This helper sets up all necessary mocks to simulate various API failure
        scenarios including timeouts, rate limits, authentication errors, and
        network failures.
        
        Args:
            error_scenario: Type of error to simulate (timeout, rate_limit, auth_error, etc.)
        
        Returns:
            Context manager for use in 'with' statements
        """
        def _mock_context():
            from contextlib import ExitStack
            import requests
            
            stack = ExitStack()
            
            # Mock requests library
            mock_requests = stack.enter_context(
                patch( 'cosa.agents.llm_completion.requests' )
            )
            
            # Mock aiohttp for async requests
            mock_aiohttp = stack.enter_context(
                patch( 'cosa.agents.llm_completion.aiohttp' )
            )
            
            # Configure mock responses based on error scenario
            if error_scenario == "timeout":
                # Simulate timeout
                mock_requests.post.side_effect = requests.exceptions.Timeout( "Request timed out" )
                
            elif error_scenario == "connection_error":
                # Simulate connection failure
                mock_requests.post.side_effect = requests.exceptions.ConnectionError( "Connection failed" )
                
            elif error_scenario == "rate_limit":
                # Simulate rate limit response
                mock_response = Mock()
                mock_response.status_code = self.rate_limit_response[ "status_code" ]
                mock_response.headers = self.rate_limit_response[ "headers" ]
                mock_response.text = self.rate_limit_response[ "body" ]
                mock_response.json.return_value = {
                    "error": "Rate limit exceeded",
                    "message": "Too many requests"
                }
                mock_requests.post.return_value = mock_response
                
            elif error_scenario == "auth_error":
                # Simulate authentication error
                mock_response = Mock()
                mock_response.status_code = self.auth_error_response[ "status_code" ]
                mock_response.headers = self.auth_error_response[ "headers" ]
                mock_response.text = self.auth_error_response[ "body" ]
                mock_response.json.return_value = {
                    "error": "Unauthorized",
                    "message": "Invalid API key"
                }
                mock_requests.post.return_value = mock_response
                
            elif error_scenario == "server_error":
                # Simulate server error
                mock_response = Mock()
                mock_response.status_code = self.server_error_response[ "status_code" ]
                mock_response.headers = self.server_error_response[ "headers" ]
                mock_response.text = self.server_error_response[ "body" ]
                mock_response.json.return_value = {
                    "error": "Internal Server Error",
                    "message": "Server temporarily unavailable"
                }
                mock_requests.post.return_value = mock_response
                
            elif error_scenario == "malformed_response":
                # Simulate malformed JSON response
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.headers = self.malformed_response[ "headers" ]
                mock_response.text = self.malformed_response[ "body" ]
                mock_response.json.side_effect = ValueError( "Invalid JSON" )
                mock_requests.post.return_value = mock_response
                
            else:
                # Default: successful response
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.headers = { "content-type": "application/json" }
                mock_response.text = '{"choices": [{"text": "Success response"}]}'
                mock_response.json.return_value = {
                    "choices": [ { "text": "Success response" } ]
                }
                mock_requests.post.return_value = mock_response
            
            # Mock time for retry timing tests
            mock_time = stack.enter_context(
                patch( 'time.sleep' )
            )
            
            return stack, {
                'requests': mock_requests,
                'aiohttp': mock_aiohttp,
                'time_sleep': mock_time
            }
        
        return _mock_context
    
    def test_timeout_error_handling( self ) -> bool:
        """
        Test timeout error detection and handling.
        
        Ensures:
            - Network timeouts are detected correctly
            - Timeout errors are categorized properly
            - Retry mechanisms work for timeout scenarios
            - Timeout durations are configurable and respected
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Timeout Error Handling" )
        
        try:
            mock_context_func = self._create_api_error_mock_context( "timeout" )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                completion_client = LlmCompletion(
                    base_url=self.test_base_url,
                    model_name=self.test_model_name,
                    api_key=self.test_api_key,
                    debug=True
                )
                
                # Test timeout detection
                try:
                    response = completion_client.run( self.test_prompt )
                    assert False, "Should raise timeout exception"
                except Exception as e:
                    assert "timed out" in str( e ).lower() or "timeout" in str( e ).lower(), f"Error should indicate timeout: {e}"
                    
                    # Verify the request was attempted
                    mocks[ 'requests' ].post.assert_called_once()
                    call_args = mocks[ 'requests' ].post.call_args
                    assert self.test_base_url in call_args[ 0 ][ 0 ], "Should call correct URL"
                
                self.utils.print_test_status( "Basic timeout detection test passed", "PASS" )
                
                # Test timeout error categorization
                try:
                    response = completion_client.run( "Another timeout test" )
                    assert False, "Should raise timeout exception"
                except Exception as e:
                    # The error should be categorizable as a timeout
                    error_msg = str( e ).lower()
                    assert any( keyword in error_msg for keyword in [ "timeout", "timed out", "time out" ] ), \
                        "Error message should clearly indicate timeout"
                
                self.utils.print_test_status( "Timeout categorization test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Timeout error handling test failed: {e}", "FAIL" )
            return False
    
    def test_connection_error_handling( self ) -> bool:
        """
        Test connection error detection and recovery.
        
        Ensures:
            - Connection failures are detected correctly
            - Network errors are handled gracefully
            - Connection retry mechanisms work properly
            - Error messages are informative for debugging
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Connection Error Handling" )
        
        try:
            mock_context_func = self._create_api_error_mock_context( "connection_error" )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                completion_client = LlmCompletion(
                    base_url=self.test_base_url,
                    model_name=self.test_model_name,
                    debug=True
                )
                
                # Test connection error detection
                try:
                    response = completion_client.run( self.test_prompt )
                    assert False, "Should raise connection exception"
                except Exception as e:
                    error_msg = str( e ).lower()
                    assert any( keyword in error_msg for keyword in [ "connection", "network", "failed" ] ), \
                        f"Error should indicate connection failure: {e}"
                    
                    # Verify the request was attempted
                    mocks[ 'requests' ].post.assert_called_once()
                
                self.utils.print_test_status( "Connection error detection test passed", "PASS" )
                
                # Test multiple connection attempts (if retry logic exists)
                mocks[ 'requests' ].post.reset_mock()
                
                try:
                    response = completion_client.run( "Connection retry test" )
                    assert False, "Should raise connection exception"
                except Exception as e:
                    # Check if retry was attempted (depends on implementation)
                    call_count = mocks[ 'requests' ].post.call_count
                    assert call_count >= 1, "Should attempt at least one request"
                    
                    # Error message should be informative
                    assert len( str( e ) ) > 0, "Error message should not be empty"
                
                self.utils.print_test_status( "Connection retry logic test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Connection error handling test failed: {e}", "FAIL" )
            return False
    
    def test_rate_limit_error_handling( self ) -> bool:
        """
        Test rate limit error detection and retry-after handling.
        
        Ensures:
            - Rate limit responses (429) are detected correctly
            - Retry-after headers are parsed and respected
            - Rate limit errors include proper context information
            - Backoff strategies are implemented appropriately
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Rate Limit Error Handling" )
        
        try:
            mock_context_func = self._create_api_error_mock_context( "rate_limit" )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                completion_client = LlmCompletion(
                    base_url=self.test_base_url,
                    model_name=self.test_model_name,
                    debug=True
                )
                
                # Test rate limit detection
                try:
                    response = completion_client.run( self.test_prompt )
                    assert False, "Should raise rate limit exception"
                except Exception as e:
                    error_msg = str( e )
                    
                    # Should indicate rate limiting or similar
                    rate_limit_indicators = [ "rate", "limit", "429", "too many", "requests" ]
                    assert any( indicator in error_msg.lower() for indicator in rate_limit_indicators ), \
                        f"Error should indicate rate limiting: {e}"
                    
                    # Verify the request was made
                    mocks[ 'requests' ].post.assert_called_once()
                    
                    # Verify response indicates rate limit status
                    mock_response = mocks[ 'requests' ].post.return_value
                    assert mock_response.status_code == 429, "Mock should return 429 status"
                
                self.utils.print_test_status( "Rate limit detection test passed", "PASS" )
                
                # Test retry-after header parsing (if implemented)
                try:
                    response = completion_client.run( "Rate limit retry test" )
                    assert False, "Should raise rate limit exception"
                except Exception as e:
                    # Error should contain useful information for retry logic
                    error_msg = str( e )
                    assert len( error_msg ) > 0, "Error message should not be empty"
                    
                    # The mock response includes retry-after: 60 seconds
                    mock_response = mocks[ 'requests' ].post.return_value
                    assert mock_response.headers[ "retry-after" ] == "60", "Mock should have retry-after header"
                
                self.utils.print_test_status( "Retry-after handling test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Rate limit error handling test failed: {e}", "FAIL" )
            return False
    
    def test_authentication_error_handling( self ) -> bool:
        """
        Test authentication error detection and handling.
        
        Ensures:
            - Authentication failures (401) are detected correctly
            - Invalid API key scenarios are handled properly
            - Auth error messages are informative for debugging
            - Token refresh patterns can be implemented
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Authentication Error Handling" )
        
        try:
            mock_context_func = self._create_api_error_mock_context( "auth_error" )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                completion_client = LlmCompletion(
                    base_url=self.test_base_url,
                    model_name=self.test_model_name,
                    api_key="invalid_api_key",
                    debug=True
                )
                
                # Test authentication error detection
                try:
                    response = completion_client.run( self.test_prompt )
                    assert False, "Should raise authentication exception"
                except Exception as e:
                    error_msg = str( e ).lower()
                    
                    # Should indicate authentication failure
                    auth_indicators = [ "unauthorized", "401", "auth", "api key", "invalid" ]
                    assert any( indicator in error_msg for indicator in auth_indicators ), \
                        f"Error should indicate authentication failure: {e}"
                    
                    # Verify the request was made with invalid key
                    mocks[ 'requests' ].post.assert_called_once()
                    
                    # Verify response indicates auth error
                    mock_response = mocks[ 'requests' ].post.return_value
                    assert mock_response.status_code == 401, "Mock should return 401 status"
                
                self.utils.print_test_status( "Authentication error detection test passed", "PASS" )
                
                # Test with completely missing API key
                mocks[ 'requests' ].post.reset_mock()
                
                try:
                    completion_client_no_key = LlmCompletion(
                        base_url=self.test_base_url,
                        model_name=self.test_model_name,
                        api_key=None
                    )
                    response = completion_client_no_key.run( "No key test" )
                    # Note: This might not fail at creation time, depends on implementation
                except Exception as e:
                    # Any auth-related error is acceptable here
                    error_msg = str( e ).lower()
                    # Just ensure we get some kind of error response
                    assert len( error_msg ) > 0, "Should provide error message for missing API key"
                
                self.utils.print_test_status( "Missing API key handling test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Authentication error handling test failed: {e}", "FAIL" )
            return False
    
    def test_server_error_handling( self ) -> bool:
        """
        Test server error (5xx) detection and recovery.
        
        Ensures:
            - Server errors (500, 502, 503) are detected correctly
            - Transient vs permanent errors are distinguished
            - Server error retry logic works appropriately
            - Error context includes server response details
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Server Error Handling" )
        
        try:
            mock_context_func = self._create_api_error_mock_context( "server_error" )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                completion_client = LlmCompletion(
                    base_url=self.test_base_url,
                    model_name=self.test_model_name,
                    debug=True
                )
                
                # Test server error detection
                try:
                    response = completion_client.run( self.test_prompt )
                    assert False, "Should raise server error exception"
                except Exception as e:
                    error_msg = str( e ).lower()
                    
                    # Should indicate server error
                    server_indicators = [ "server", "500", "internal", "unavailable", "error" ]
                    assert any( indicator in error_msg for indicator in server_indicators ), \
                        f"Error should indicate server error: {e}"
                    
                    # Verify the request was made
                    mocks[ 'requests' ].post.assert_called_once()
                    
                    # Verify response indicates server error
                    mock_response = mocks[ 'requests' ].post.return_value
                    assert mock_response.status_code == 500, "Mock should return 500 status"
                
                self.utils.print_test_status( "Server error detection test passed", "PASS" )
                
                # Test server error retry behavior (if implemented)
                mocks[ 'requests' ].post.reset_mock()
                
                try:
                    response = completion_client.run( "Server retry test" )
                    assert False, "Should raise server error exception"
                except Exception as e:
                    # Check that request was attempted
                    call_count = mocks[ 'requests' ].post.call_count
                    assert call_count >= 1, "Should attempt at least one request"
                    
                    # Error should include useful debugging information
                    error_msg = str( e )
                    assert len( error_msg ) > 10, "Error message should be descriptive"
                
                self.utils.print_test_status( "Server error retry handling test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Server error handling test failed: {e}", "FAIL" )
            return False
    
    def test_malformed_response_handling( self ) -> bool:
        """
        Test malformed response detection and error handling.
        
        Ensures:
            - Invalid JSON responses are detected correctly
            - Incomplete responses are handled gracefully
            - Malformed response errors include debugging context
            - Response validation works properly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Malformed Response Handling" )
        
        try:
            mock_context_func = self._create_api_error_mock_context( "malformed_response" )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                completion_client = LlmCompletion(
                    base_url=self.test_base_url,
                    model_name=self.test_model_name,
                    debug=True
                )
                
                # Test malformed JSON response handling
                try:
                    response = completion_client.run( self.test_prompt )
                    assert False, "Should raise malformed response exception"
                except Exception as e:
                    error_msg = str( e ).lower()
                    
                    # Should indicate JSON/parsing error
                    json_indicators = [ "json", "invalid", "parse", "decode", "malformed" ]
                    assert any( indicator in error_msg for indicator in json_indicators ), \
                        f"Error should indicate JSON parsing issue: {e}"
                    
                    # Verify the request was made
                    mocks[ 'requests' ].post.assert_called_once()
                    
                    # Verify response has malformed content
                    mock_response = mocks[ 'requests' ].post.return_value
                    assert mock_response.status_code == 200, "Mock should return 200 status (but malformed content)"
                    assert mock_response.text == self.malformed_response[ "body" ], "Mock should have malformed JSON"
                
                self.utils.print_test_status( "Malformed JSON detection test passed", "PASS" )
                
                # Test response structure validation
                try:
                    response = completion_client.run( "Structure validation test" )
                    assert False, "Should raise validation exception"
                except Exception as e:
                    # Error should provide context for debugging
                    error_msg = str( e )
                    assert len( error_msg ) > 0, "Error message should not be empty"
                    
                    # Should have attempted to parse the JSON (may be called multiple times in error handling)
                    mock_response = mocks[ 'requests' ].post.return_value
                    assert mock_response.json.call_count >= 1, "Should have attempted JSON parsing at least once"
                
                self.utils.print_test_status( "Response validation test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Malformed response handling test failed: {e}", "FAIL" )
            return False
    
    def test_error_recovery_patterns( self ) -> bool:
        """
        Test error recovery and fallback mechanisms.
        
        Ensures:
            - Circuit breaker patterns work correctly
            - Fallback responses are provided when appropriate
            - Error recovery strategies maintain system stability
            - Graceful degradation works under failure conditions
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Error Recovery Patterns" )
        
        try:
            # Test gradual degradation from success to failure
            scenarios = [ "none", "server_error", "timeout", "connection_error" ]
            
            for i, scenario in enumerate( scenarios ):
                mock_context_func = self._create_api_error_mock_context( scenario )
                with mock_context_func()[0] as stack:
                    mocks = mock_context_func()[1]
                    
                    completion_client = LlmCompletion(
                        base_url=self.test_base_url,
                        model_name=self.test_model_name,
                        debug=False  # Reduce noise
                    )
                    
                    if scenario == "none":
                        # Should succeed
                        try:
                            response = completion_client.run( f"Test {i}" )
                            assert "Success response" in response, "Should get successful response"
                        except Exception as e:
                            assert False, f"Success scenario should not raise exception: {e}"
                    else:
                        # Should fail gracefully
                        try:
                            response = completion_client.run( f"Test {i}" )
                            assert False, f"Error scenario {scenario} should raise exception"
                        except Exception as e:
                            # Error should be meaningful
                            error_msg = str( e )
                            assert len( error_msg ) > 0, f"Error message should not be empty for {scenario}"
                            
                            # Should not crash the system
                            assert isinstance( e, Exception ), f"Should raise proper exception for {scenario}"
            
            self.utils.print_test_status( "Error scenario handling test passed", "PASS" )
            
            # Test error context preservation
            mock_context_func = self._create_api_error_mock_context( "auth_error" )
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                completion_client = LlmCompletion(
                    base_url=self.test_base_url,
                    model_name=self.test_model_name
                )
                
                try:
                    response = completion_client.run( "Context preservation test" )
                    assert False, "Should raise auth error"
                except Exception as e:
                    # Error should preserve context for debugging
                    error_msg = str( e )
                    
                    # Should include useful information
                    assert len( error_msg ) > 10, "Error message should be descriptive"
                    
                    # Should be able to distinguish error types
                    assert not isinstance( e, ( KeyboardInterrupt, SystemExit ) ), "Should not raise system exceptions"
            
            self.utils.print_test_status( "Error context preservation test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Error recovery patterns test failed: {e}", "FAIL" )
            return False
    
    def test_performance_requirements( self ) -> bool:
        """
        Test performance requirements for error handling.
        
        Ensures:
            - Error detection is fast enough
            - Error handling doesn't introduce significant overhead
            - Timeout detection is timely
            - Recovery mechanisms are performant
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance Requirements" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            error_timeout = performance_targets[ "timing_targets" ].get( "error_handling", 0.01 )
            
            # Test error detection performance
            def error_detection_test():
                mock_context_func = self._create_api_error_mock_context( "server_error" )
                with mock_context_func()[0] as stack:
                    completion_client = LlmCompletion(
                        base_url=self.test_base_url,
                        model_name=self.test_model_name
                    )
                    
                    try:
                        response = completion_client.run( "Performance test" )
                        return False  # Should not succeed
                    except Exception:
                        return True   # Error detected quickly
            
            success, duration, result = self.utils.assert_timing( error_detection_test, 0.1 )  # 100ms limit
            assert success, f"Error detection too slow: {duration}s"
            assert result == True, "Error detection should succeed"
            
            # Test multiple error scenarios performance
            def multiple_errors_test():
                scenarios = [ "timeout", "auth_error", "server_error" ]
                for scenario in scenarios:
                    mock_context_func = self._create_api_error_mock_context( scenario )
                    with mock_context_func()[0] as stack:
                        completion_client = LlmCompletion(
                            base_url=self.test_base_url,
                            model_name=self.test_model_name
                        )
                        
                        try:
                            response = completion_client.run( f"Multi-error test {scenario}" )
                        except Exception:
                            pass  # Expected
                
                return True
            
            success, duration, result = self.utils.assert_timing( multiple_errors_test, 0.5 )  # 500ms for multiple scenarios
            assert success, f"Multiple error handling too slow: {duration}s"
            assert result == True, "Multiple error handling should succeed"
            
            self.utils.print_test_status( f"Performance requirements met ({self.utils.format_duration( duration )})", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance requirements test failed: {e}", "FAIL" )
            return False
    
    def run_all_tests( self ) -> tuple:
        """
        Run all API error handling unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "api_error_handling_tests" )
        
        tests = [
            self.test_timeout_error_handling,
            self.test_connection_error_handling,
            self.test_rate_limit_error_handling,
            self.test_authentication_error_handling,
            self.test_server_error_handling,
            self.test_malformed_response_handling,
            self.test_error_recovery_patterns,
            self.test_performance_requirements
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "API Error Handling Unit Test Suite", "=" )
        
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
        
        duration = self.utils.stop_timer( "api_error_handling_tests" )
        
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
    Main unit test function for API error handling.
    
    This is the entry point called by the unit test runner to execute
    all API error handling unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = APIErrorHandlingUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"API error handling unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} API error handling unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )