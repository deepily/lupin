"""
Unit Test Utilities for CoSA Framework

Provides utility functions and classes specifically designed for unit testing
including timing, formatting, assertion helpers, and test data management.

Usage:
    from unit_test_utilities import UnitTestUtilities
    
    utils = UnitTestUtilities()
    utils.print_test_banner( "Testing ConfigurationManager" )
    assert utils.assert_timing( some_function, max_duration=0.1 )
"""

import time
import sys
import os
import json
import tempfile
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from pathlib import Path
from contextlib import contextmanager
import configparser


class UnitTestUtilities:
    """
    Utility functions and helpers for CoSA unit testing.
    
    Provides consistent formatting, timing utilities, assertion helpers,
    and test data management functions optimized for unit testing scenarios.
    
    Requires:
        - Standard library modules (time, sys, os, etc.)
        
    Ensures:
        - Consistent output formatting across all tests
        - Accurate timing and performance measurement
        - Helpful assertion and validation functions
        - Clean test data management
        
    Raises:
        - AssertionError for failed assertions
        - ValueError for invalid parameters
    """
    
    def __init__( self, ci_mode: bool = False, debug: bool = False ):
        """
        Initialize unit test utilities.
        
        Requires:
            - ci_mode is a boolean flag for CI-optimized output
            - debug is a boolean flag for debug output
            
        Ensures:
            - Configures output formatting based on mode
            - Sets up timing and measurement infrastructure
        """
        self.ci_mode = ci_mode
        self.debug = debug
        self.start_times = {}
        self.performance_data = []
    
    def print_test_banner( self, message: str, char: str = "=", width: int = 60, prepend_nl: bool = False ):
        """
        Print a formatted test banner message.
        
        Requires:
            - message is a non-empty string
            - char is a single character for banner decoration
            - width is a positive integer for banner width
            
        Ensures:
            - Consistent banner formatting across tests
            - Appropriate output for CI vs interactive modes
            
        Args:
            message: Test message to display
            char: Character to use for banner decoration
            width: Width of the banner
            prepend_nl: Whether to prepend a newline
        """
        if prepend_nl:
            print()
        
        if self.ci_mode:
            print( f"[TEST] {message}" )
        else:
            print( char * width )
            print( f" {message}" )
            print( char * width )
    
    def print_test_status( self, message: str, status: str = "INFO" ):
        """
        Print a test status message with appropriate formatting.
        
        Args:
            message: Status message
            status: Status level (INFO, PASS, FAIL, WARNING, ERROR)
        """
        if self.ci_mode:
            print( f"[{status}] {message}" )
        else:
            colors = {
                "INFO": "\033[0;34m",     # Blue
                "PASS": "\033[0;32m",     # Green
                "FAIL": "\033[0;31m",     # Red
                "WARNING": "\033[1;33m",  # Yellow
                "ERROR": "\033[0;31m",    # Red
                "RESET": "\033[0m"        # Reset
            }
            
            color = colors.get( status, colors[ "INFO" ] )
            reset = colors[ "RESET" ]
            print( f"{color}[{status}]{reset} {message}" )
    
    def start_timer( self, label: str ):
        """
        Start a named timer for performance measurement.
        
        Requires:
            - label is a non-empty string identifier
            
        Ensures:
            - Timer is recorded with current timestamp
            - Multiple timers can run concurrently
            
        Args:
            label: Unique identifier for the timer
        """
        self.start_times[ label ] = time.time()
    
    def stop_timer( self, label: str ) -> float:
        """
        Stop a named timer and return elapsed time.
        
        Requires:
            - label corresponds to a previously started timer
            
        Ensures:
            - Returns accurate elapsed time in seconds
            - Timer data is recorded for later analysis
            
        Args:
            label: Timer identifier
            
        Returns:
            Elapsed time in seconds
            
        Raises:
            ValueError if timer was not started
        """
        if label not in self.start_times:
            raise ValueError( f"Timer '{label}' was not started" )
        
        elapsed = time.time() - self.start_times[ label ]
        del self.start_times[ label ]
        
        # Record performance data
        self.performance_data.append( {
            "label": label,
            "duration": elapsed,
            "timestamp": time.time()
        } )
        
        return elapsed
    
    def format_duration( self, seconds: float ) -> str:
        """
        Format duration in human-readable form.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted duration string
        """
        if seconds < 0.001:
            return f"{seconds * 1000000:.0f}μs"
        elif seconds < 1.0:
            return f"{seconds * 1000:.1f}ms"
        else:
            return f"{seconds:.2f}s"
    
    def assert_timing( self, func: Callable, max_duration: float, *args, **kwargs ) -> Tuple[bool, float, Any]:
        """
        Assert that a function executes within specified time limit.
        
        Requires:
            - func is a callable function
            - max_duration is a positive float in seconds
            
        Ensures:
            - Function is executed and timed
            - Assertion passes if within time limit
            - Returns timing data and function result
            
        Args:
            func: Function to test
            max_duration: Maximum allowed duration in seconds
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function
            
        Returns:
            Tuple of (success, actual_duration, function_result)
            
        Raises:
            AssertionError if function exceeds time limit
        """
        start_time = time.time()
        
        try:
            result = func( *args, **kwargs )
            duration = time.time() - start_time
            
            success = duration <= max_duration
            
            if not success:
                raise AssertionError( 
                    f"Function {func.__name__} took {self.format_duration( duration )}, "
                    f"exceeding limit of {self.format_duration( max_duration )}"
                )
            
            return success, duration, result
            
        except Exception as e:
            duration = time.time() - start_time
            raise AssertionError( f"Function {func.__name__} failed after {self.format_duration( duration )}: {e}" )
    
    def assert_no_exceptions( self, func: Callable, *args, **kwargs ) -> Any:
        """
        Assert that a function executes without raising exceptions.
        
        Args:
            func: Function to test
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function
            
        Returns:
            Function result
            
        Raises:
            AssertionError if function raises any exception
        """
        try:
            return func( *args, **kwargs )
        except Exception as e:
            error_details = traceback.format_exc() if self.debug else str( e )
            raise AssertionError( f"Function {func.__name__} raised exception: {error_details}" )
    
    def assert_raises( self, expected_exception: type, func: Callable, *args, **kwargs ):
        """
        Assert that a function raises a specific exception.
        
        Args:
            expected_exception: Expected exception type
            func: Function to test
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function
            
        Raises:
            AssertionError if function doesn't raise expected exception
        """
        try:
            result = func( *args, **kwargs )
            raise AssertionError( 
                f"Function {func.__name__} was expected to raise {expected_exception.__name__} "
                f"but completed successfully with result: {result}"
            )
        except expected_exception:
            # Expected exception was raised - test passes
            pass
        except Exception as e:
            raise AssertionError( 
                f"Function {func.__name__} raised {type( e ).__name__} instead of expected {expected_exception.__name__}: {e}"
            )
    
    def create_temp_file( self, content: str = "", suffix: str = ".tmp" ) -> str:
        """
        Create a temporary file with specified content.
        
        Args:
            content: Content to write to file
            suffix: File suffix/extension
            
        Returns:
            Path to temporary file
        """
        fd, temp_path = tempfile.mkstemp( suffix=suffix )
        try:
            with os.fdopen( fd, 'w' ) as f:
                f.write( content )
        except:
            os.close( fd )
            raise
        
        return temp_path
    
    def create_temp_config( self, config_dict: Dict[str, Dict[str, Any]] ) -> str:
        """
        Create a temporary configuration file from dictionary.
        
        Args:
            config_dict: Configuration data organized by sections
            
        Returns:
            Path to temporary configuration file
        """
        config = configparser.ConfigParser()
        
        for section_name, section_data in config_dict.items():
            config.add_section( section_name )
            for key, value in section_data.items():
                config.set( section_name, key, str( value ) )
        
        temp_path = self.create_temp_file( suffix=".ini" )
        with open( temp_path, 'w' ) as f:
            config.write( f )
        
        return temp_path
    
    @contextmanager
    def temp_environment( self, env_vars: Dict[str, str] ):
        """
        Temporarily set environment variables for testing.
        
        Args:
            env_vars: Dictionary of environment variables to set
            
        Yields:
            Environment context with temporary variables
        """
        original_env = {}
        
        # Save original values and set new ones
        for key, value in env_vars.items():
            original_env[ key ] = os.environ.get( key )
            os.environ[ key ] = value
        
        try:
            yield os.environ
        finally:
            # Restore original environment
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop( key, None )
                else:
                    os.environ[ key ] = original_value
    
    def validate_test_result( self, result: Tuple, expected_format: str = "success_duration_error" ) -> bool:
        """
        Validate that a test result follows expected format.
        
        Args:
            result: Test result tuple
            expected_format: Expected format ("success_duration_error" or "custom")
            
        Returns:
            True if result format is valid
            
        Raises:
            AssertionError if result format is invalid
        """
        if not isinstance( result, tuple ):
            raise AssertionError( f"Test result must be a tuple, got {type( result )}" )
        
        if expected_format == "success_duration_error":
            if len( result ) < 2:
                raise AssertionError( f"Test result must have at least 2 elements (success, duration), got {len( result )}" )
            
            success, duration = result[ 0 ], result[ 1 ]
            
            if not isinstance( success, bool ):
                raise AssertionError( f"First element (success) must be boolean, got {type( success )}" )
            
            if not isinstance( duration, ( int, float ) ) or duration < 0:
                raise AssertionError( f"Second element (duration) must be non-negative number, got {duration}" )
            
            if len( result ) > 2:
                error_msg = result[ 2 ]
                if not isinstance( error_msg, str ):
                    raise AssertionError( f"Third element (error_message) must be string, got {type( error_msg )}" )
        
        return True
    
    def get_performance_summary( self ) -> Dict[str, Any]:
        """
        Get performance summary of all recorded timings.
        
        Returns:
            Dictionary with performance statistics
        """
        if not self.performance_data:
            return { "total_tests": 0, "message": "No performance data recorded" }
        
        durations = [ data[ "duration" ] for data in self.performance_data ]
        
        return {
            "total_tests": len( self.performance_data ),
            "total_duration": sum( durations ),
            "average_duration": sum( durations ) / len( durations ),
            "min_duration": min( durations ),
            "max_duration": max( durations ),
            "tests": self.performance_data.copy()
        }
    
    def cleanup_temp_files( self, file_paths: List[str] ):
        """
        Clean up temporary files created during testing.
        
        Args:
            file_paths: List of file paths to remove
        """
        for file_path in file_paths:
            try:
                if os.path.exists( file_path ):
                    os.remove( file_path )
                    if self.debug:
                        self.print_test_status( f"Cleaned up temp file: {file_path}" )
            except Exception as e:
                if self.debug:
                    self.print_test_status( f"Failed to clean up {file_path}: {e}", "WARNING" )


def isolated_unit_test():
    """
    Quick smoke test for UnitTestUtilities functionality.
    
    Ensures:
        - Utilities can be instantiated
        - Basic timing functions work
        - Assertion helpers function properly
        - Temporary file creation works
        
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    start_time = time.time()
    
    try:
        # Test basic instantiation
        utils = UnitTestUtilities( ci_mode=True, debug=False )
        assert utils is not None, "Failed to create UnitTestUtilities instance"
        
        # Test timing functions
        utils.start_timer( "test_timer" )
        time.sleep( 0.001 )  # Very short sleep
        elapsed = utils.stop_timer( "test_timer" )
        assert elapsed > 0, "Timer should measure positive elapsed time"
        
        # Test duration formatting
        formatted = utils.format_duration( 0.001234 )
        assert "ms" in formatted or "μs" in formatted, f"Duration formatting failed: {formatted}"
        
        # Test assertion helpers
        def successful_function():
            return "success"
        
        success, duration, result = utils.assert_timing( successful_function, 1.0 )
        assert success == True, "Timing assertion should succeed"
        assert result == "success", "Function result should be returned"
        
        # Test no exception assertion  
        result = utils.assert_no_exceptions( successful_function )
        assert result == "success", "No exception assertion should return result"
        
        # Test exception assertion
        def failing_function():
            raise ValueError( "test error" )
        
        utils.assert_raises( ValueError, failing_function )
        
        # Test temporary file creation
        temp_file = utils.create_temp_file( "test content" )
        assert os.path.exists( temp_file ), "Temporary file should be created"
        
        with open( temp_file, 'r' ) as f:
            content = f.read()
        assert content == "test content", "Temporary file should contain correct content"
        
        # Test temp config creation
        config_data = {
            "section1": { "key1": "value1", "key2": "value2" }
        }
        temp_config = utils.create_temp_config( config_data )
        assert os.path.exists( temp_config ), "Temporary config file should be created"
        
        # Test cleanup
        utils.cleanup_temp_files( [ temp_file, temp_config ] )
        
        # Test performance summary
        perf_summary = utils.get_performance_summary()
        assert "total_tests" in perf_summary, "Performance summary should contain test count"
        
        duration = time.time() - start_time
        return True, duration, ""
        
    except Exception as e:
        duration = time.time() - start_time
        return False, duration, f"UnitTestUtilities test failed: {str( e )}"


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} UnitTestUtilities unit test completed in {duration:.2f}s" )
    if error:
        print( f"Error: {error}" )