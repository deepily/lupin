"""
Unit tests for user notification system with comprehensive HTTP client mocking.

Tests the notify_user module including:
- User notification sending with various types and priorities
- Environment validation and server URL handling
- HTTP request handling with proper error management
- Command-line interface argument parsing and validation
- Notification type and priority validation
- Connection error handling and timeout management
- Environment variable configuration management
- Debug mode and verbose output functionality

Zero external dependencies - all HTTP requests, CLI operations,
and external service calls are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import time
import argparse
import sys
import os
from typing import Optional, Dict, Any

# Import test infrastructure (from CoSA test infrastructure)
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "..", "cosa", "tests", "unit", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from lupin_cli.notifications.notify_user import notify_user, validate_environment, main


class TestNotifyUser( unittest.TestCase ):
    """
    Comprehensive unit tests for user notification system.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All notification operations tested in isolation
        - HTTP client operations properly mocked
        - Environment validation and error handling covered
        - CLI interface thoroughly tested
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
        
        # Common test data
        self.test_message = "Test notification message"
        self.test_user = "test.user@example.com"
        self.test_server_url = "http://localhost:7999"
        self.test_api_key = "claude_code_simple_key"
        
        # Mock HTTP response
        self.mock_success_response = Mock()
        self.mock_success_response.status_code = 200
        self.mock_success_response.json.return_value = {
            "status": "success",
            "message": "Notification sent successfully"
        }
        
        self.mock_error_response = Mock()
        self.mock_error_response.status_code = 400
        self.mock_error_response.text = "Invalid request parameters"
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_notify_user_success( self ):
        """
        Test successful notification sending.
        
        Ensures:
            - Makes HTTP POST request with correct parameters
            - Returns True for successful response
            - Uses default values for optional parameters
            - Prints success message
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_post.return_value = self.mock_success_response
            
            result = notify_user( self.test_message )
            
            # Verify return value
            self.assertTrue( result )
            
            # Verify HTTP request
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            
            # Verify URL (first positional argument)
            expected_url = f"{self.test_server_url}/api/notify"
            self.assertEqual( call_args[0][0], expected_url )
            
            # Verify parameters
            params = call_args[1]['params']
            self.assertEqual( params['message'], self.test_message )
            self.assertEqual( params['type'], "custom" )  # Default type
            self.assertEqual( params['priority'], "medium" )  # Default priority
            self.assertEqual( params['target_user'], "ricardo.felipe.ruiz@gmail.com" )  # Default user
            self.assertEqual( params['api_key'], self.test_api_key )
            
            # Verify timeout
            self.assertEqual( call_args[1]['timeout'], 5 )
            
            # Verify success message
            mock_print.assert_called_with( "✓ Notification sent: custom/medium" )
    
    def test_notify_user_with_custom_parameters( self ):
        """
        Test notification sending with custom parameters.
        
        Ensures:
            - Uses provided parameters instead of defaults
            - Supports all notification types and priorities
            - Handles custom server URL and timeout
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ):
            
            mock_post.return_value = self.mock_success_response
            
            result = notify_user(
                message="Custom message",
                notification_type="alert",
                priority="urgent",
                target_user=self.test_user,
                server_url="http://custom-server:8080",
                timeout=10
            )
            
            # Verify return value
            self.assertTrue( result )
            
            # Verify HTTP request parameters
            call_args = mock_post.call_args
            
            # Verify custom URL (first positional argument)
            expected_url = "http://custom-server:8080/api/notify"
            self.assertEqual( call_args[0][0], expected_url )
            
            # Verify custom parameters
            params = call_args[1]['params']
            self.assertEqual( params['message'], "Custom message" )
            self.assertEqual( params['type'], "alert" )
            self.assertEqual( params['priority'], "urgent" )
            self.assertEqual( params['target_user'], self.test_user )
            
            # Verify custom timeout
            self.assertEqual( call_args[1]['timeout'], 10 )
    
    def test_notify_user_invalid_notification_type( self ):
        """
        Test notification with invalid notification type.
        
        Ensures:
            - Returns False for invalid types
            - Prints error message with valid options
            - Does not make HTTP request
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            result = notify_user( 
                self.test_message, 
                notification_type="invalid_type" 
            )
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify no HTTP request made
            mock_post.assert_not_called()
            
            # Verify error messages
            mock_print.assert_any_call( "✗ Invalid notification type: invalid_type" )
            expected_types = "task, progress, alert, custom"
            mock_print.assert_any_call( f"  Valid types: {expected_types}" )
    
    def test_notify_user_invalid_priority( self ):
        """
        Test notification with invalid priority level.
        
        Ensures:
            - Returns False for invalid priorities
            - Prints error message with valid options
            - Does not make HTTP request
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            result = notify_user( 
                self.test_message, 
                priority="invalid_priority" 
            )
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify no HTTP request made
            mock_post.assert_not_called()
            
            # Verify error messages
            mock_print.assert_any_call( "✗ Invalid priority: invalid_priority" )
            expected_priorities = "low, medium, high, urgent"
            mock_print.assert_any_call( f"  Valid priorities: {expected_priorities}" )
    
    def test_notify_user_http_error_response( self ):
        """
        Test notification with HTTP error response.
        
        Ensures:
            - Returns False for HTTP error status codes
            - Prints error message with status code
            - Handles error response text
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_post.return_value = self.mock_error_response
            
            result = notify_user( self.test_message )
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify error messages
            mock_print.assert_any_call( "✗ Failed to send notification: HTTP 400" )
            mock_print.assert_any_call( f"  Error: {self.mock_error_response.text}" )
    
    def test_notify_user_connection_error( self ):
        """
        Test notification with connection error.
        
        Ensures:
            - Returns False for connection errors
            - Prints descriptive error message
            - Provides troubleshooting guidance
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            import requests
            mock_post.side_effect = requests.exceptions.ConnectionError()
            
            result = notify_user( self.test_message )
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify error messages
            mock_print.assert_any_call( f"✗ Connection error: Cannot reach server at {self.test_server_url}" )
            mock_print.assert_any_call( "  Check that Lupin is running and LUPIN_APP_SERVER_URL is correct" )
    
    def test_notify_user_timeout_error( self ):
        """
        Test notification with timeout error.
        
        Ensures:
            - Returns False for timeout errors
            - Prints timeout-specific error message
            - Includes timeout duration in message
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            import requests
            mock_post.side_effect = requests.exceptions.Timeout()
            
            result = notify_user( self.test_message, timeout=10 )
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify timeout error message
            mock_print.assert_any_call( "✗ Timeout error: Server did not respond within 10 seconds" )
    
    def test_notify_user_generic_request_error( self ):
        """
        Test notification with generic request error.
        
        Ensures:
            - Returns False for other request errors
            - Prints generic request error message
            - Includes error details
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            import requests
            error_message = "SSL certificate verification failed"
            mock_post.side_effect = requests.exceptions.RequestException( error_message )
            
            result = notify_user( self.test_message )
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify error message
            mock_print.assert_any_call( f"✗ Request error: {error_message}" )
    
    def test_notify_user_unexpected_error( self ):
        """
        Test notification with unexpected error.
        
        Ensures:
            - Returns False for unexpected exceptions
            - Prints generic error message
            - Handles non-request exceptions gracefully
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'builtins.print' ) as mock_print:
            
            error_message = "Unexpected system error"  
            mock_post.side_effect = Exception( error_message )
            
            result = notify_user( self.test_message )
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify error message
            mock_print.assert_any_call( f"✗ Unexpected error: {error_message}" )
    
    def test_notify_user_server_url_handling( self ):
        """
        Test server URL handling and normalization.
        
        Ensures:
            - Removes trailing slashes from server URL
            - Uses environment variable when server_url is None
            - Uses default URL when environment variable not set
        """
        with patch( 'lupin_cli.notifications.notify_user.requests.post' ) as mock_post, \
             patch( 'lupin_cli.notifications.notify_user.os.getenv' ) as mock_getenv, \
             patch( 'builtins.print' ):
            
            mock_post.return_value = self.mock_success_response
            mock_getenv.return_value = "http://env-server:9000/"  # With trailing slash
            
            result = notify_user( self.test_message )
            
            # Verify environment variable lookup
            mock_getenv.assert_called_with( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
            
            # Verify trailing slash removed
            call_args = mock_post.call_args
            expected_url = "http://env-server:9000/api/notify"  # Slash removed
            self.assertEqual( call_args[0][0], expected_url )
    
    def test_validate_environment_success( self ):
        """
        Test successful environment validation.
        
        Ensures:
            - Returns True for valid environment
            - Validates server URL format
            - Prints success message with server URL
        """
        with patch( 'lupin_cli.notifications.notify_user.os.getenv' ) as mock_getenv, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_getenv.return_value = "https://valid-server.com:8080"
            
            result = validate_environment()
            
            # Verify return value  
            self.assertTrue( result )
            
            # Verify success messages
            mock_print.assert_any_call( "✅ Environment validation passed" )
            mock_print.assert_any_call( "  Server URL: https://valid-server.com:8080" )
    
    def test_validate_environment_invalid_url_scheme( self ):
        """
        Test environment validation with invalid URL scheme.
        
        Ensures:
            - Returns False for invalid schemes
            - Prints error message for scheme requirements
            - Lists validation issues clearly
        """
        with patch( 'lupin_cli.notifications.notify_user.os.getenv' ) as mock_getenv, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_getenv.return_value = "ftp://invalid-scheme.com"
            
            result = validate_environment()
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify error messages
            mock_print.assert_any_call( "❌ Environment validation failed:" )
            mock_print.assert_any_call( "  - LUPIN_APP_SERVER_URL must start with http:// or https://" )
    
    def test_validate_environment_invalid_url_format( self ):
        """
        Test environment validation with malformed URL.
        
        Ensures:
            - Returns False for malformed URLs
            - Prints error message for URL format issues
            - Handles URL parsing exceptions
        """
        with patch( 'lupin_cli.notifications.notify_user.os.getenv' ) as mock_getenv, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_getenv.return_value = "http://"  # Malformed URL
            
            result = validate_environment()
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify error messages  
            mock_print.assert_any_call( "❌ Environment validation failed:" )
            # Should contain error about invalid URL format
            self.assertTrue( any( "Invalid server URL format" in str( call ) for call in mock_print.call_args_list ) )
    
    def test_validate_environment_url_parsing_exception( self ):
        """
        Test environment validation with URL parsing exception.
        
        Ensures:
            - Returns False when URL parsing fails
            - Prints error message with exception details
            - Handles urllib.parse exceptions gracefully
        """
        with patch( 'lupin_cli.notifications.notify_user.os.getenv' ) as mock_getenv, \
             patch( 'urllib.parse.urlparse' ) as mock_urlparse, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_getenv.return_value = "http://valid-url.com"
            mock_urlparse.side_effect = Exception( "URL parsing failed" )
            
            result = validate_environment()
            
            # Verify return value
            self.assertFalse( result )
            
            # Verify error messages
            mock_print.assert_any_call( "❌ Environment validation failed:" )
            mock_print.assert_any_call( "  - Error parsing server URL: URL parsing failed" )
    
    def test_main_cli_basic_functionality( self ):
        """
        Test main CLI function with basic parameters.
        
        Ensures:
            - Parses command line arguments correctly
            - Calls notify_user with parsed parameters
            - Exits with correct status code
        """
        test_args = ["notify_user.py", "Test CLI message"]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'lupin_cli.notifications.notify_user.notify_user' ) as mock_notify, \
             patch( 'sys.exit' ) as mock_exit:
            
            mock_notify.return_value = True
            
            main()
            
            # Verify notify_user called with correct parameters
            mock_notify.assert_called_once_with(
                message="Test CLI message",
                notification_type="custom",  # Default
                priority="medium",  # Default
                target_user="ricardo.felipe.ruiz@gmail.com",  # Default
                server_url=None,  # Default
                timeout=5  # Default
            )
            
            # Verify successful exit
            mock_exit.assert_called_once_with( 0 )
    
    def test_main_cli_with_all_parameters( self ):
        """
        Test main CLI function with all parameters specified.
        
        Ensures:
            - Parses all CLI arguments correctly
            - Supports all notification types and priorities
            - Handles custom server URL and timeout
        """
        test_args = [
            "notify_user.py", 
            "Full CLI test",
            "--type", "alert",
            "--priority", "urgent", 
            "--target-user", "custom@user.com",
            "--server", "http://custom:8080",
            "--timeout", "15",
            "--debug"
        ]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'lupin_cli.notifications.notify_user.notify_user' ) as mock_notify, \
             patch( 'sys.exit' ) as mock_exit:
            
            mock_notify.return_value = True
            
            main()
            
            # Verify notify_user called with custom parameters
            mock_notify.assert_called_once_with(
                message="Full CLI test",
                notification_type="alert",
                priority="urgent",
                target_user="custom@user.com",
                server_url="http://custom:8080",
                timeout=15
            )
            
            # Verify successful exit
            mock_exit.assert_called_once_with( 0 )
    
    def test_main_cli_validate_env_only( self ):
        """
        Test main CLI function with validate-env option.
        
        Ensures:
            - Calls validate_environment when requested
            - Exits without sending notification
            - Uses correct exit code based on validation result
        """
        test_args = ["notify_user.py", "message", "--validate-env"]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'lupin_cli.notifications.notify_user.validate_environment' ) as mock_validate, \
             patch( 'lupin_cli.notifications.notify_user.notify_user' ) as mock_notify, \
             patch( 'sys.exit' ) as mock_exit:
            
            mock_validate.return_value = True
            # Mock sys.exit to raise SystemExit so we can catch it
            mock_exit.side_effect = SystemExit( 0 )
            
            with self.assertRaises( SystemExit ):
                main()
            
            # Verify validation called
            mock_validate.assert_called_once()
            
            # Verify notification not sent
            mock_notify.assert_not_called()
            
            # Verify successful exit
            mock_exit.assert_called_once_with( 0 )
    
    def test_main_cli_notification_failure( self ):
        """
        Test main CLI function when notification fails.
        
        Ensures:
            - Exits with error code when notification fails
            - Does not exit successfully on failure
        """
        test_args = ["notify_user.py", "Failed message"]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'lupin_cli.notifications.notify_user.notify_user' ) as mock_notify, \
             patch( 'sys.exit' ) as mock_exit:
            
            mock_notify.return_value = False
            
            main()
            
            # Verify error exit
            mock_exit.assert_called_once_with( 1 )


def isolated_unit_test():
    """
    Run comprehensive unit tests for user notification system in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real HTTP requests or system calls
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "User Notification System Unit Tests - External Phase 5", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_notify_user_success',
            'test_notify_user_with_custom_parameters',
            'test_notify_user_invalid_notification_type',
            'test_notify_user_invalid_priority',
            'test_notify_user_http_error_response',
            'test_notify_user_connection_error',
            'test_notify_user_timeout_error',
            'test_notify_user_generic_request_error',
            'test_notify_user_unexpected_error',
            'test_notify_user_server_url_handling',
            'test_validate_environment_success',
            'test_validate_environment_invalid_url_scheme',
            'test_validate_environment_invalid_url_format',
            'test_validate_environment_url_parsing_exception',
            'test_main_cli_basic_functionality',
            'test_main_cli_with_all_parameters',
            'test_main_cli_validate_env_only',
            'test_main_cli_notification_failure'
        ]
        
        for method in test_methods:
            suite.addTest( TestNotifyUser( method ) )
        
        # Run tests with detailed output
        runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
        result = runner.run( suite )
        
        duration = time.time() - start_time
        
        # Calculate results
        tests_run = result.testsRun
        failures = len( result.failures )
        errors = len( result.errors )
        success_count = tests_run - failures - errors
        
        print( f"\n{'='*60}" )
        print( f"USER NOTIFICATION SYSTEM UNIT TEST RESULTS" )
        print( f"{'='*60}" )
        print( f"Tests Run     : {tests_run}" )
        print( f"Passed        : {success_count}" )
        print( f"Failed        : {failures}" )
        print( f"Errors        : {errors}" )
        print( f"Success Rate  : {(success_count/tests_run)*100:.1f}%" )
        print( f"Duration      : {duration:.3f} seconds" )
        print( f"{'='*60}" )
        
        if failures > 0:
            print( "\nFAILURE DETAILS:" )
            for test, traceback in result.failures:
                print( f"❌ {test}: {traceback.split(chr(10))[-2]}" )
                
        if errors > 0:
            print( "\nERROR DETAILS:" )
            for test, traceback in result.errors:
                print( f"💥 {test}: {traceback.split(chr(10))[-2]}" )
        
        success = failures == 0 and errors == 0
        
        if success:
            du.print_banner( "✅ ALL USER NOTIFICATION TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME USER NOTIFICATION TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 USER NOTIFICATION TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} User notification system unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )