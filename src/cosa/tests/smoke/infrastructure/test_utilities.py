#!/usr/bin/env python3
"""
CoSA Framework Smoke Test Utilities

Shared utility functions for the CoSA smoke test suite providing consistent
formatting, timing, output capture, and common test operations.

This module provides:
- Consistent banner and message formatting
- Timeout protection for test execution
- Output capture and redirection utilities
- Duration formatting and timing helpers
- Test result aggregation functions
"""

import os
import sys
import time
import signal
import contextlib
import io
from typing import Any, Callable, Optional, Tuple, Dict, List
from pathlib import Path


class SmokeTestUtilities:
    """
    Shared utilities for CoSA smoke test suite.
    
    Provides consistent formatting, timing, and output handling across
    all smoke test components with timeout protection and standardized
    reporting capabilities.
    
    Requires:
        - Standard library modules (time, signal, contextlib, io)
        
    Ensures:
        - Consistent output formatting across test suite
        - Reliable timeout protection for test execution
        - Standardized duration and result formatting
        - Output capture without interfering with test results
        
    Raises:
        - None (all methods handle errors gracefully)
    """
    
    @staticmethod
    def print_banner( message: str, prepend_nl: bool = False, width: int = 60 ):
        """
        Print formatted banner with message.
        
        Requires:
            - message is a non-empty string
            - prepend_nl is a boolean flag for leading newline
            - width is a positive integer for banner width
            
        Ensures:
            - Prints consistently formatted banner
            - Centers message within banner width
            - Adds leading newline if requested
            - Uses standard formatting across test suite
            
        Raises:
            - None
        
        Args:
            message: Text to display in banner
            prepend_nl: Add newline before banner
            width: Width of banner in characters
        """
        if prepend_nl:
            print()
        
        print( "=" * width )
        # Center the message in the banner
        padding = ( width - len( message ) - 2 ) // 2
        centered_message = " " * padding + message + " " * padding
        if len( centered_message ) < width - 2:
            centered_message += " "  # Add extra space if needed
        print( f" {centered_message}" )
        print( "=" * width )
    
    @staticmethod
    def format_duration( seconds: float ) -> str:
        """
        Format duration in human-readable format.
        
        Requires:
            - seconds is a non-negative float
            
        Ensures:
            - Returns formatted duration string
            - Uses appropriate precision based on duration
            - Consistent formatting across test suite
            
        Raises:
            - None
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            str: Formatted duration (e.g., "1.25s", "2m 30s")
        """
        if seconds < 0:
            return "0.00s"
        elif seconds < 60:
            return f"{seconds:.2f}s"
        elif seconds < 3600:
            minutes = int( seconds // 60 )
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds:.1f}s"
        else:
            hours = int( seconds // 3600 )
            remaining_minutes = int( ( seconds % 3600 ) // 60 )
            return f"{hours}h {remaining_minutes}m"
    
    @staticmethod
    def format_timestamp( timestamp: Optional[float] = None ) -> str:
        """
        Format timestamp in consistent format.
        
        Requires:
            - timestamp is None or valid unix timestamp
            
        Ensures:
            - Returns formatted timestamp string
            - Uses current time if timestamp is None
            - Consistent format across test suite
            
        Raises:
            - None
        
        Args:
            timestamp: Unix timestamp (None = current time)
            
        Returns:
            str: Formatted timestamp (YYYY-MM-DD HH:MM:SS)
        """
        if timestamp is None:
            timestamp = time.time()
        
        return time.strftime( "%Y-%m-%d %H:%M:%S", time.localtime( timestamp ) )
    
    @staticmethod
    def capture_output( func: Callable, *args, **kwargs ) -> Tuple[Any, str, str]:
        """
        Execute function with stdout/stderr capture.
        
        Requires:
            - func is a callable function
            - args and kwargs are valid for the function
            
        Ensures:
            - Executes function with output capture
            - Returns function result and captured output
            - Restores original stdout/stderr after execution
            - Handles exceptions without affecting output capture
            
        Raises:
            - Any exceptions raised by the wrapped function
        
        Args:
            func: Function to execute with output capture
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Tuple[Any, str, str]: (result, stdout_text, stderr_text)
        """
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        with contextlib.redirect_stdout( stdout_capture ):
            with contextlib.redirect_stderr( stderr_capture ):
                result = func( *args, **kwargs )
        
        return result, stdout_capture.getvalue(), stderr_capture.getvalue()
    
    @staticmethod
    def with_timeout( func: Callable, timeout_seconds: int = 120, *args, **kwargs ) -> Tuple[bool, Any, str]:
        """
        Execute function with timeout protection.
        
        Requires:
            - func is a callable function
            - timeout_seconds is a positive integer
            - Signal handling is available (Unix-like systems)
            
        Ensures:
            - Executes function with timeout protection
            - Returns success status, result, and error message
            - Cleans up timeout handler after execution
            - Handles both timeout and function exceptions
            
        Raises:
            - None (all exceptions converted to failure status)
        
        Args:
            func: Function to execute with timeout
            timeout_seconds: Maximum execution time in seconds
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Tuple[bool, Any, str]: (success, result, error_message)
        """
        def timeout_handler( signum, frame ):
            raise TimeoutError( f"Function execution exceeded {timeout_seconds} seconds" )
        
        # Set up timeout handler (Unix only)
        if hasattr( signal, 'SIGALRM' ):
            old_handler = signal.signal( signal.SIGALRM, timeout_handler )
            signal.alarm( timeout_seconds )
        
        try:
            result = func( *args, **kwargs )
            return True, result, ""
            
        except TimeoutError as e:
            return False, None, str( e )
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            return False, None, error_msg
        finally:
            # Clean up timeout handler
            if hasattr( signal, 'SIGALRM' ):
                signal.alarm( 0 )
                signal.signal( signal.SIGALRM, old_handler )
    
    @staticmethod
    def safe_import( module_name: str ) -> Tuple[bool, Any, str]:
        """
        Safely import module with error handling.
        
        Requires:
            - module_name is a valid Python module path
            
        Ensures:
            - Attempts to import specified module
            - Returns success status, module object, and error message
            - Handles all import errors gracefully
            - Provides detailed error information for debugging
            
        Raises:
            - None (all exceptions converted to failure status)
        
        Args:
            module_name: Python module path to import
            
        Returns:
            Tuple[bool, Any, str]: (success, module_object, error_message)
        """
        try:
            import importlib
            module = importlib.import_module( module_name )
            return True, module, ""
        except ImportError as e:
            return False, None, f"ImportError: {str(e)}"
        except Exception as e:
            return False, None, f"{type(e).__name__}: {str(e)}"
    
    @staticmethod
    def check_function_exists( module: Any, function_name: str ) -> bool:
        """
        Check if module has specified function.
        
        Requires:
            - module is a valid Python module object
            - function_name is a string
            
        Ensures:
            - Returns True if function exists and is callable
            - Returns False otherwise
            - Handles module inspection safely
            
        Raises:
            - None
        
        Args:
            module: Python module object
            function_name: Name of function to check
            
        Returns:
            bool: True if function exists and is callable
        """
        try:
            if hasattr( module, function_name ):
                func = getattr( module, function_name )
                return callable( func )
            return False
        except:
            return False
    
    @staticmethod
    def aggregate_test_results( test_results: List[Dict[str, Any]] ) -> Dict[str, Any]:
        """
        Aggregate individual test results into summary statistics.
        
        Requires:
            - test_results is a list of test result dictionaries
            - Each result has keys: success, duration, module
            
        Ensures:
            - Returns comprehensive aggregated statistics
            - Calculates success rates, timing statistics
            - Identifies fastest/slowest tests
            - Provides breakdown by success/failure
            
        Raises:
            - None (handles empty or malformed results gracefully)
        
        Args:
            test_results: List of individual test results
            
        Returns:
            Dict[str, Any]: Aggregated statistics and analysis
        """
        if not test_results:
            return {
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
                "success_rate": 0.0,
                "total_duration": 0.0,
                "average_duration": 0.0,
                "fastest_test": None,
                "slowest_test": None,
                "failed_modules": []
            }
        
        total_tests = len( test_results )
        passed_tests = sum( 1 for result in test_results if result.get( "success", False ) )
        failed_tests = total_tests - passed_tests
        
        durations = [result.get( "duration", 0.0 ) for result in test_results]
        total_duration = sum( durations )
        average_duration = total_duration / total_tests if total_tests > 0 else 0.0
        
        # Find fastest and slowest tests
        fastest_test = None
        slowest_test = None
        
        if durations:
            min_duration = min( durations )
            max_duration = max( durations )
            
            for result in test_results:
                if result.get( "duration", 0.0 ) == min_duration and fastest_test is None:
                    fastest_test = {
                        "module": result.get( "module", "unknown" ),
                        "duration": min_duration
                    }
                if result.get( "duration", 0.0 ) == max_duration and slowest_test is None:
                    slowest_test = {
                        "module": result.get( "module", "unknown" ),
                        "duration": max_duration
                    }
        
        # Collect failed modules
        failed_modules = [
            {
                "module": result.get( "module", "unknown" ),
                "error": result.get( "error", "Unknown error" )
            }
            for result in test_results
            if not result.get( "success", False )
        ]
        
        success_rate = ( passed_tests / total_tests * 100 ) if total_tests > 0 else 0.0
        
        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "success_rate": success_rate,
            "total_duration": total_duration,
            "average_duration": average_duration,
            "fastest_test": fastest_test,
            "slowest_test": slowest_test,
            "failed_modules": failed_modules
        }
    
    @staticmethod
    def print_test_summary( summary: Dict[str, Any], title: str = "Test Summary" ):
        """
        Print formatted test summary with statistics.
        
        Requires:
            - summary contains aggregated test statistics
            - title is a string for the summary header
            
        Ensures:
            - Prints formatted summary with key statistics
            - Uses consistent formatting and colors
            - Includes performance and failure details
            - Provides actionable information
            
        Raises:
            - None
        
        Args:
            summary: Aggregated test statistics
            title: Header title for the summary
        """
        SmokeTestUtilities.print_banner( title )
        
        # Overall results
        print( f"Total Tests:    {summary['total_tests']}" )
        print( f"Passed:         {summary['passed_tests']} ✓" )
        print( f"Failed:         {summary['failed_tests']} ✗" )
        print( f"Success Rate:   {summary['success_rate']:.1f}%" )
        print()
        
        # Timing information
        print( f"Total Duration: {SmokeTestUtilities.format_duration(summary['total_duration'])}" )
        print( f"Average:        {SmokeTestUtilities.format_duration(summary['average_duration'])}" )
        
        if summary['fastest_test']:
            print( f"Fastest Test:   {summary['fastest_test']['module']} ({SmokeTestUtilities.format_duration(summary['fastest_test']['duration'])})" )
        
        if summary['slowest_test']:
            print( f"Slowest Test:   {summary['slowest_test']['module']} ({SmokeTestUtilities.format_duration(summary['slowest_test']['duration'])})" )
        
        # Failed tests
        if summary['failed_modules']:
            print( "\nFailed Tests:" )
            for failed in summary['failed_modules']:
                print( f"  ✗ {failed['module']}: {failed['error']}" )
        
        print()


def quick_smoke_test():
    """Quick smoke test to validate SmokeTestUtilities functionality."""
    try:
        # Import CoSA utils for banner printing
        import cosa.utils.util as du
    except ImportError:
        # Fallback if CoSA utils not available
        class MockUtils:
            @staticmethod
            def print_banner( message, prepend_nl=False ):
                if prepend_nl:
                    print()
                print( "=" * 60 )
                print( f" {message}" )
                print( "=" * 60 )
        du = MockUtils()
    
    du.print_banner( "SmokeTestUtilities Smoke Test", prepend_nl=True )
    
    utils = SmokeTestUtilities()
    
    try:
        # Test banner printing
        utils.print_banner( "Test Banner" )
        print( "✓ Banner printing works" )
        
        # Test duration formatting
        duration_tests = [0.5, 65.0, 3725.0]
        for duration in duration_tests:
            formatted = utils.format_duration( duration )
            print( f"✓ Duration formatting: {duration}s -> {formatted}" )
        
        # Test timestamp formatting
        timestamp = utils.format_timestamp()
        print( f"✓ Timestamp formatting: {timestamp}" )
        
        # Test output capture
        def test_function():
            print( "Test output" )
            return "test_result"
        
        result, stdout, stderr = utils.capture_output( test_function )
        if result == "test_result" and "Test output" in stdout:
            print( "✓ Output capture works" )
        else:
            print( "✗ Output capture failed" )
        
        # Test safe import
        success, module, error = utils.safe_import( "os" )
        if success and module:
            print( "✓ Safe import works" )
        else:
            print( f"✗ Safe import failed: {error}" )
        
        # Test function existence check
        import os
        if utils.check_function_exists( os, "path" ):
            print( "✓ Function existence check works" )
        else:
            print( "✗ Function existence check failed" )
        
        # Test result aggregation
        mock_results = [
            { "success": True, "duration": 1.0, "module": "test1" },
            { "success": False, "duration": 2.0, "module": "test2", "error": "Test error" },
            { "success": True, "duration": 0.5, "module": "test3" }
        ]
        
        summary = utils.aggregate_test_results( mock_results )
        if summary["total_tests"] == 3 and summary["passed_tests"] == 2:
            print( "✓ Result aggregation works" )
        else:
            print( "✗ Result aggregation failed" )
        
        # Test summary printing
        utils.print_test_summary( summary, "Mock Test Summary" )
        print( "✓ Summary printing works" )
        
    except Exception as e:
        print( f"✗ Error during utilities testing: {e}" )
    
    print( "\n✓ SmokeTestUtilities smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()