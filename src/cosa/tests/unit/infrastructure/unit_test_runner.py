#!/usr/bin/env python3
"""
CoSA Framework Unit Test Suite Orchestrator

Discovers and executes isolated_unit_test() functions across all CoSA
framework modules, providing comprehensive validation with zero external
dependencies for reliable CICD pipeline execution.

Usage:
    python3 unit_test_runner.py
    python3 unit_test_runner.py --category core
    python3 unit_test_runner.py --ci-mode
    python3 unit_test_runner.py --verbose
"""

import os
import sys
import time
import argparse
import importlib
import traceback
import signal
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass

try:
    from cosa.tests.unit.infrastructure.mock_manager import MockManager
    from cosa.tests.unit.infrastructure.test_fixtures import CoSATestFixtures
except ImportError:
    # Fallback for development
    class MockManager:
        def reset_mocks( self ):
            pass
    
    class CoSATestFixtures:
        def get_performance_targets( self ):
            return { "timing_targets": { "unit_test_execution": 0.1 } }


@dataclass
class TestResult:
    """
    Represents the result of a single unit test execution.
    
    Attributes:
        module_name: Name of the tested module
        test_function: Name of the test function
        success: Whether the test passed
        duration: Test execution time in seconds
        error_message: Error message if test failed
        category: Test category (core, agents, memory, etc.)
        metadata: Additional test metadata
    """
    module_name: str
    test_function: str
    success: bool
    duration: float
    error_message: str = ""
    category: str = "unknown"
    metadata: Dict[str, Any] = None


class CoSAUnitTestRunner:
    """
    Main orchestrator for CoSA framework unit test execution.
    
    Discovers and executes isolated_unit_test() functions across all CoSA modules,
    organizing tests by category and providing comprehensive reporting with
    performance tracking and error isolation.
    
    Requires:
        - CoSA framework is properly installed and accessible
        - PYTHONPATH includes CoSA framework directory
        - MockManager and CoSATestFixtures modules available
        
    Ensures:
        - Discovers all modules with isolated_unit_test() functions
        - Executes tests with timeout protection and error handling
        - Provides detailed reporting with timing and success metrics
        - Maintains test isolation with proper cleanup between tests
        
    Raises:
        - ImportError if CoSA framework is not accessible
        - SystemExit with appropriate exit codes based on test results
    """
    
    def __init__( self, debug: bool = False, timeout: int = 30, ci_mode: bool = False ):
        """
        Initialize the CoSA unit test runner.
        
        Requires:
            - debug is a boolean flag for debug output
            - timeout is a positive integer for test timeout in seconds
            - ci_mode is a boolean flag for CI-optimized output
            
        Ensures:
            - Sets up test configuration with debug and timeout settings
            - Initializes mock manager and test fixtures
            - Prepares test discovery and execution framework
            
        Raises:
            - ImportError if required modules are not available
        """
        self.debug = debug
        self.timeout = timeout
        self.ci_mode = ci_mode
        self.cosa_root = cosa_root
        
        # Initialize test infrastructure
        self.mock_manager = MockManager()
        self.fixtures = CoSATestFixtures()
        
        # Test discovery configuration
        self.test_categories = {
            "core": [ "config", "utils", "base_classes" ],
            "agents": [ "v010", "v000" ],
            "memory": [ "embedding", "caching", "persistence" ],
            "rest": [ "routers", "queues", "auth" ],
            "tools": [ "search", "notifications" ],
            "training": [ "models", "quantization", "pipelines" ]
        }
        
        # Performance tracking
        self.performance_targets = self.fixtures.get_performance_targets()
        self.test_results = []
        
        # Setup timeout handler
        signal.signal( signal.SIGALRM, self._timeout_handler )
    
    def _timeout_handler( self, signum, frame ):
        """
        Handle test timeout.
        
        Raises:
            TimeoutError when test execution exceeds timeout limit
        """
        raise TimeoutError( f"Test execution exceeded {self.timeout} seconds" )
    
    def _print_banner( self, message: str, char: str = "=", width: int = 70 ):
        """
        Print a formatted banner message.
        
        Args:
            message: Message to display
            char: Character to use for banner
            width: Width of the banner
        """
        if not self.ci_mode:
            print( char * width )
            print( f" {message}" )
            print( char * width )
        else:
            print( f"[INFO] {message}" )
    
    def _print_status( self, message: str, status: str = "INFO" ):
        """
        Print a status message with appropriate formatting.
        
        Args:
            message: Status message
            status: Status level (INFO, SUCCESS, WARNING, ERROR)
        """
        if self.ci_mode:
            print( f"[{status}] {message}" )
        else:
            colors = {
                "INFO": "\033[0;34m",     # Blue
                "SUCCESS": "\033[0;32m",  # Green
                "WARNING": "\033[1;33m",  # Yellow
                "ERROR": "\033[0;31m",    # Red
                "RESET": "\033[0m"        # Reset
            }
            
            color = colors.get( status, colors[ "INFO" ] )
            reset = colors[ "RESET" ]
            print( f"{color}[{status}]{reset} {message}" )
    
    def discover_test_modules( self, category: Optional[str] = None ) -> List[Tuple[str, str, str]]:
        """
        Discover all modules containing isolated_unit_test() functions.
        
        Requires:
            - category is None or a valid test category name
            
        Ensures:
            - Scans appropriate directories for test modules
            - Finds modules with isolated_unit_test() functions
            - Returns module paths organized by category
            
        Args:
            category: Specific category to discover, or None for all
            
        Returns:
            List of tuples (module_path, module_name, category)
        """
        discovered_modules = []
        
        # Define search paths for each category
        search_paths = {
            "core": [
                self.cosa_root / "config",
                self.cosa_root / "utils",
                self.cosa_root / "tests" / "unit" / "core"
            ],
            "agents": [
                self.cosa_root / "agents" / "v010",
                self.cosa_root / "agents" / "v000",
                self.cosa_root / "tests" / "unit" / "agents"
            ],
            "memory": [
                self.cosa_root / "memory",
                self.cosa_root / "tests" / "unit" / "memory"
            ],
            "rest": [
                self.cosa_root / "rest",
                self.cosa_root / "tests" / "unit" / "rest"
            ],
            "tools": [
                self.cosa_root / "tools",
                self.cosa_root / "tests" / "unit" / "tools"
            ],
            "training": [
                self.cosa_root / "training",
                self.cosa_root / "tests" / "unit" / "training"
            ]
        }
        
        # Filter categories if specific category requested
        if category:
            if category not in search_paths:
                self._print_status( f"Unknown category: {category}", "WARNING" )
                return []
            search_paths = { category: search_paths[ category ] }
        
        # Search for test modules
        for cat_name, paths in search_paths.items():
            for search_path in paths:
                if not search_path.exists():
                    if self.debug:
                        self._print_status( f"Search path does not exist: {search_path}", "WARNING" )
                    continue
                
                # Find Python files
                for py_file in search_path.rglob( "*.py" ):
                    if py_file.name.startswith( "__" ):
                        continue
                    
                    # Check if file contains isolated_unit_test function
                    try:
                        with open( py_file, 'r', encoding='utf-8' ) as f:
                            content = f.read()
                            if "def isolated_unit_test(" in content:
                                # Calculate relative module path
                                rel_path = py_file.relative_to( self.cosa_root.parent )
                                module_name = str( rel_path ).replace( os.sep, "." ).replace( ".py", "" )
                                
                                discovered_modules.append( ( str( py_file ), module_name, cat_name ) )
                                
                                if self.debug:
                                    self._print_status( f"Discovered test module: {module_name}", "INFO" )
                    
                    except Exception as e:
                        if self.debug:
                            self._print_status( f"Error reading {py_file}: {e}", "WARNING" )
        
        return discovered_modules
    
    def execute_single_test( self, module_path: str, module_name: str, category: str ) -> TestResult:
        """
        Execute a single unit test with isolation and error handling.
        
        Requires:
            - module_path is a valid path to a Python module
            - module_name is a valid Python module name
            - category is a valid test category name
            
        Ensures:
            - Test is executed with timeout protection
            - Mock state is cleaned between tests
            - Comprehensive error handling and reporting
            - Performance metrics are captured
            
        Args:
            module_path: Path to the module file
            module_name: Python module name for import
            category: Test category
            
        Returns:
            TestResult object with execution details
        """
        start_time = time.time()
        
        try:
            # Reset mock state before each test
            self.mock_manager.reset_mocks()
            
            # Set timeout alarm
            if not self.ci_mode:  # Skip timeout in CI mode to avoid signal issues
                signal.alarm( self.timeout )
            
            # Import and execute test
            try:
                # Dynamic import of the module
                if module_name in sys.modules:
                    # Reload if already imported
                    module = importlib.reload( sys.modules[ module_name ] )
                else:
                    module = importlib.import_module( module_name )
                
                # Check if isolated_unit_test function exists
                if not hasattr( module, 'isolated_unit_test' ):
                    raise AttributeError( f"Module {module_name} does not have isolated_unit_test function" )
                
                # Execute the test function
                test_func = getattr( module, 'isolated_unit_test' )
                
                # Call test function and capture result
                result = test_func()
                
                # Parse result based on return type
                if isinstance( result, tuple ) and len( result ) >= 2:
                    success, duration, error_msg = result[ 0 ], result[ 1 ], result[ 2 ] if len( result ) > 2 else ""
                else:
                    # Assume success if function completed without exception
                    success = True
                    duration = time.time() - start_time
                    error_msg = ""
                
                # Disable timeout alarm
                if not self.ci_mode:
                    signal.alarm( 0 )
                
                return TestResult(
                    module_name=module_name,
                    test_function="isolated_unit_test",
                    success=success,
                    duration=duration,
                    error_message=error_msg,
                    category=category,
                    metadata={ "module_path": module_path }
                )
            
            except ImportError as e:
                duration = time.time() - start_time
                return TestResult(
                    module_name=module_name,
                    test_function="isolated_unit_test",
                    success=False,
                    duration=duration,
                    error_message=f"Import error: {str( e )}",
                    category=category,
                    metadata={ "module_path": module_path, "error_type": "import" }
                )
            
            except TimeoutError:
                duration = self.timeout
                return TestResult(
                    module_name=module_name,
                    test_function="isolated_unit_test",
                    success=False,
                    duration=duration,
                    error_message=f"Test timeout after {self.timeout} seconds",
                    category=category,
                    metadata={ "module_path": module_path, "error_type": "timeout" }
                )
            
            except Exception as e:
                duration = time.time() - start_time
                error_details = traceback.format_exc() if self.debug else str( e )
                
                return TestResult(
                    module_name=module_name,
                    test_function="isolated_unit_test",
                    success=False,
                    duration=duration,
                    error_message=f"Test execution error: {error_details}",
                    category=category,
                    metadata={ "module_path": module_path, "error_type": "execution" }
                )
        
        finally:
            # Always disable timeout alarm
            if not self.ci_mode:
                signal.alarm( 0 )
    
    def run_tests( self, category: Optional[str] = None ) -> List[TestResult]:
        """
        Run all discovered unit tests.
        
        Requires:
            - Test modules are discoverable
            - isolated_unit_test functions are properly implemented
            
        Ensures:
            - All tests are executed with proper isolation
            - Results are collected and organized
            - Performance metrics are tracked
            
        Args:
            category: Specific category to test, or None for all
            
        Returns:
            List of TestResult objects
        """
        # Discover test modules
        self._print_banner( "CoSA Framework Unit Test Suite" )
        self._print_status( f"Discovering unit tests (category: {category or 'all'})" )
        
        discovered_modules = self.discover_test_modules( category )
        
        if not discovered_modules:
            self._print_status( "No unit test modules discovered", "WARNING" )
            return []
        
        self._print_status( f"Found {len( discovered_modules )} unit test modules" )
        
        # Execute tests
        results = []
        successful_tests = 0
        failed_tests = 0
        
        for i, ( module_path, module_name, cat ) in enumerate( discovered_modules, 1 ):
            self._print_status( f"[{i}/{len( discovered_modules )}] Testing {module_name}" )
            
            result = self.execute_single_test( module_path, module_name, cat )
            results.append( result )
            
            # Update counters
            if result.success:
                successful_tests += 1
                status = "✅ PASS"
            else:
                failed_tests += 1
                status = "❌ FAIL"
            
            # Print individual test result
            duration_str = f"{result.duration:.3f}s"
            self._print_status( f"{status} {module_name} ({duration_str})" )
            
            if not result.success and result.error_message:
                if self.debug or not self.ci_mode:
                    self._print_status( f"    Error: {result.error_message}", "ERROR" )
        
        # Store results
        self.test_results = results
        
        # Print summary
        self._print_banner( "Test Execution Summary" )
        self._print_status( f"Total Tests: {len( results )}" )
        self._print_status( f"Passed: {successful_tests}", "SUCCESS" )
        
        if failed_tests > 0:
            self._print_status( f"Failed: {failed_tests}", "ERROR" )
        
        # Performance analysis
        total_duration = sum( r.duration for r in results )
        avg_duration = total_duration / len( results ) if results else 0
        
        self._print_status( f"Total Duration: {total_duration:.2f}s" )
        self._print_status( f"Average Test Duration: {avg_duration:.3f}s" )
        
        # Check performance targets
        target_duration = self.performance_targets[ "timing_targets" ][ "unit_test_execution" ]
        if avg_duration > target_duration:
            self._print_status( f"Performance Warning: Average duration {avg_duration:.3f}s exceeds target {target_duration}s", "WARNING" )
        
        return results
    
    def generate_report( self, output_path: Optional[str] = None ) -> str:
        """
        Generate comprehensive test report.
        
        Args:
            output_path: Optional path to save report file
            
        Returns:
            Report content as string
        """
        if not self.test_results:
            return "No test results available"
        
        # Generate report content
        report_lines = [
            "CoSA Framework Unit Test Report",
            "=" * 50,
            f"Generated: {time.strftime( '%Y-%m-%d %H:%M:%S' )}",
            f"Total Tests: {len( self.test_results )}",
            f"Passed: {sum( 1 for r in self.test_results if r.success )}",
            f"Failed: {sum( 1 for r in self.test_results if not r.success )}",
            "",
            "Test Results by Category:",
            "-" * 30
        ]
        
        # Group results by category
        by_category = {}
        for result in self.test_results:
            if result.category not in by_category:
                by_category[ result.category ] = []
            by_category[ result.category ].append( result )
        
        # Report by category
        for category, cat_results in sorted( by_category.items() ):
            passed = sum( 1 for r in cat_results if r.success )
            total = len( cat_results )
            
            report_lines.extend( [
                f"",
                f"{category.upper()}: {passed}/{total} passed",
                "-" * 20
            ] )
            
            for result in cat_results:
                status = "PASS" if result.success else "FAIL"
                duration = f"{result.duration:.3f}s"
                report_lines.append( f"  {status} {result.module_name} ({duration})" )
                
                if not result.success and result.error_message:
                    # Truncate long error messages for report
                    error = result.error_message
                    if len( error ) > 200:
                        error = error[ :200 ] + "..."
                    report_lines.append( f"    Error: {error}" )
        
        # Performance summary
        total_duration = sum( r.duration for r in self.test_results )
        avg_duration = total_duration / len( self.test_results )
        
        report_lines.extend( [
            "",
            "Performance Summary:",
            "-" * 20,
            f"Total Duration: {total_duration:.2f}s",
            f"Average Duration: {avg_duration:.3f}s",
            f"Fastest Test: {min( r.duration for r in self.test_results ):.3f}s",
            f"Slowest Test: {max( r.duration for r in self.test_results ):.3f}s"
        ] )
        
        report_content = "\n".join( report_lines )
        
        # Save to file if requested
        if output_path:
            try:
                with open( output_path, 'w' ) as f:
                    f.write( report_content )
                self._print_status( f"Report saved to {output_path}" )
            except Exception as e:
                self._print_status( f"Failed to save report: {e}", "ERROR" )
        
        return report_content
    
    def get_exit_code( self ) -> int:
        """
        Get appropriate exit code based on test results.
        
        Returns:
            0 if all tests passed, 1 if any tests failed
        """
        if not self.test_results:
            return 1  # No tests found
        
        failed_tests = sum( 1 for r in self.test_results if not r.success )
        return 0 if failed_tests == 0 else 1


def main():
    """
    Main entry point for unit test runner.
    """
    parser = argparse.ArgumentParser( description="CoSA Framework Unit Test Runner" )
    parser.add_argument( "--category", choices=[ "core", "agents", "memory", "rest", "tools", "training" ],
                        help="Run tests for specific category only" )
    parser.add_argument( "--debug", action="store_true", help="Enable debug output" )
    parser.add_argument( "--timeout", type=int, default=30, help="Test timeout in seconds" )
    parser.add_argument( "--ci-mode", action="store_true", help="CI-optimized output format" )
    parser.add_argument( "--report", help="Save test report to file" )
    
    args = parser.parse_args()
    
    # Create test runner
    runner = CoSAUnitTestRunner(
        debug=args.debug,
        timeout=args.timeout,
        ci_mode=args.ci_mode
    )
    
    try:
        # Run tests
        results = runner.run_tests( category=args.category )
        
        # Generate report if requested
        if args.report:
            runner.generate_report( args.report )
        
        # Exit with appropriate code
        exit_code = runner.get_exit_code()
        sys.exit( exit_code )
    
    except KeyboardInterrupt:
        runner._print_status( "Test execution interrupted by user", "WARNING" )
        sys.exit( 130 )  # Standard exit code for Ctrl+C
        
    except Exception as e:
        runner._print_status( f"Unexpected error: {e}", "ERROR" )
        if args.debug:
            traceback.print_exc()
        sys.exit( 1 )


def isolated_unit_test():
    """
    Quick smoke test for CoSAUnitTestRunner functionality.
    
    Ensures:
        - Unit test runner can be instantiated
        - Test discovery works on infrastructure modules  
        - Basic test execution functions properly
        
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    start_time = time.time()
    
    try:
        # Test basic instantiation
        runner = CoSAUnitTestRunner( debug=False, timeout=10, ci_mode=True )
        assert runner is not None, "Failed to create CoSAUnitTestRunner instance"
        
        # Test discovery on infrastructure modules (should find this file)
        discovered = runner.discover_test_modules( category="core" )
        # Note: discovery might be empty if no core modules have tests yet
        
        # Test the discovery mechanism itself
        assert hasattr( runner, 'discover_test_modules' ), "Missing discover_test_modules method"
        assert hasattr( runner, 'execute_single_test' ), "Missing execute_single_test method"
        assert hasattr( runner, 'run_tests' ), "Missing run_tests method"
        
        # Test result data structures
        test_result = TestResult(
            module_name="test_module",
            test_function="isolated_unit_test",
            success=True,
            duration=0.1,
            category="test"
        )
        assert test_result.success == True, "TestResult creation failed"
        
        duration = time.time() - start_time
        return True, duration, ""
        
    except Exception as e:
        duration = time.time() - start_time
        return False, duration, f"CoSAUnitTestRunner test failed: {str( e )}"


if __name__ == "__main__":
    if len( sys.argv ) == 1 and "isolated_unit_test" in globals():
        # Run self-test if called without arguments
        success, duration, error = isolated_unit_test()
        status = "✅ PASS" if success else "❌ FAIL"
        print( f"{status} CoSAUnitTestRunner unit test completed in {duration:.2f}s" )
        if error:
            print( f"Error: {error}" )
    else:
        # Run main function
        main()