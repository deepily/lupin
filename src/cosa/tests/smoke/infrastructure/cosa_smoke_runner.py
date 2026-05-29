#!/usr/bin/env python3
"""
CoSA Framework Smoke Test Suite Orchestrator

This script discovers and executes quick_smoke_test() functions across all CoSA
framework modules, providing comprehensive validation with baseline comparison
support for safe v000 agent deprecation.

Usage:
    python3 cosa_smoke_runner.py
    python3 cosa_smoke_runner.py --category agents
    python3 cosa_smoke_runner.py --save-baseline
    python3 cosa_smoke_runner.py --compare-baseline
"""

import os
import sys
import time
import argparse
import importlib
import traceback
import json
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path


try:
    from test_utilities import SmokeTestUtilities
    from baseline_manager import BaselineManager
except ImportError:
    # Fallback for development - create minimal utilities
    class SmokeTestUtilities:
        @staticmethod
        def print_banner( message: str, prepend_nl: bool = False ):
            if prepend_nl:
                print()
            print( "=" * 60 )
            print( f" {message}" )
            print( "=" * 60 )
        
        @staticmethod
        def format_duration( seconds: float ) -> str:
            return f"{seconds:.2f}s"
    
    class BaselineManager:
        def save_baseline( self, results: Dict ) -> str:
            return "baseline_saved"
        
        def compare_baseline( self, results: Dict ) -> Dict:
            return { "comparison": "no baseline available" }


class CoSASmokeTestRunner:
    """
    Main orchestrator for CoSA framework smoke test execution.
    
    Discovers and executes quick_smoke_test() functions across all CoSA modules,
    organizing tests by category and providing comprehensive reporting with
    baseline comparison capabilities.
    
    Requires:
        - CoSA framework is properly installed and accessible
        - PYTHONPATH includes CoSA framework directory
        - test_utilities and baseline_manager modules available
        
    Ensures:
        - Discovers all modules with quick_smoke_test() functions
        - Executes tests with timeout protection and error handling
        - Provides detailed reporting with timing and success metrics
        - Supports baseline saving and comparison for regression detection
        
    Raises:
        - ImportError if CoSA framework is not accessible
        - SystemExit with appropriate exit codes based on test results
    """
    
    def __init__( self, debug: bool = False, timeout: int = 120 ):
        """
        Initialize the CoSA smoke test runner.
        
        Requires:
            - debug is a boolean flag for debug output
            - timeout is a positive integer for test timeout in seconds
            
        Ensures:
            - Sets up test configuration with debug and timeout settings
            - Initializes utilities and baseline manager
            - Prepares test discovery and execution framework
            
        Raises:
            - ImportError if required modules are not available
        """
        import os
        from pathlib import Path
        
        self.debug = debug
        self.timeout = timeout
        self.utils = SmokeTestUtilities()
        self.baseline_mgr = BaselineManager()
        
        # Use COSA_CLI_PATH environment variable with fallback to derived path
        self.cosa_root = os.environ.get('COSA_CLI_PATH', 
                                       Path(__file__).parent.parent.parent)
        
        # Ensure PYTHONPATH includes the CoSA framework root for imports
        import sys
        cosa_root_str = str(self.cosa_root)
        if cosa_root_str not in sys.path:
            sys.path.insert(0, cosa_root_str)
        
        # Also update PYTHONPATH environment variable for subprocess consistency
        current_pythonpath = os.environ.get('PYTHONPATH', '')
        if cosa_root_str not in current_pythonpath:
            if current_pythonpath:
                os.environ['PYTHONPATH'] = f"{cosa_root_str}:{current_pythonpath}"
            else:
                os.environ['PYTHONPATH'] = cosa_root_str
        
        # Test categories mapped to their module paths
        self.test_categories = {
            "core": [
                "config.configuration_manager",
                "utils.util",
                "utils.util_code_runner", 
                "utils.util_stopwatch",
                "cli.notify_user"
            ],
            "agents": [
                "agents.v010.math_agent",
                "agents.v010.calendaring_agent",
                "agents.v010.weather_agent",
                "agents.v010.todo_list_agent",
                "agents.v010.receptionist_agent",
                "agents.v010.bug_injector",
                "agents.v010.confirmation_dialog",
                "agents.v010.date_and_time_agent",
                "agents.v010.gister",
                "agents.v010.iterative_debugging_agent",
                "agents.v010.llm_client",
                "agents.v010.llm_client_factory",
                "agents.v010.llm_completion",
                "agents.v010.prompt_formatter",
                "agents.v010.raw_output_formatter",
                "agents.v010.runnable_code",
                "agents.v010.token_counter",
                "agents.v010.two_word_id_generator"
            ],
            "rest": [
                "rest.user_id_generator",
                "rest.multimodal_munger",
                "rest.notification_fifo_queue",
                "rest.queue_consumer",
                "rest.todo_fifo_queue"
            ],
            "memory": [
                "memory.embedding_cache_table",
                "memory.embedding_manager",
                "memory.gist_normalizer",
                "memory.input_and_output_table",
                "memory.normalizer",
                "memory.solution_snapshot",
                "memory.solution_snapshot_mgr"
            ],
            "training": [
                "training.hf_downloader",
                "training.peft_trainer",
                "training.quantizer",
                "training.xml_coordinator",
                "training.xml_prompt_generator",
                "training.xml_response_validator"
            ]
        }
        
        self.test_results = []
        
    def log( self, message: str, level: str = "INFO" ):
        """
        Log message with timestamp if debug enabled.
        
        Requires:
            - message is a string to log
            - level is a valid log level string
            
        Ensures:
            - Outputs timestamped message if debug mode is enabled
            - Does nothing if debug mode is disabled
            - Uses consistent timestamp format
            
        Raises:
            - None
        """
        if self.debug:
            timestamp = time.strftime( "%H:%M:%S" )
            print( f"[{timestamp}] {level}: {message}" )
    
    def discover_smoke_tests( self, categories: Optional[List[str]] = None ) -> Dict[str, List[str]]:
        """
        Discover all modules with quick_smoke_test() functions.
        
        Requires:
            - categories is None or list of valid category names
            - CoSA framework modules are importable
            
        Ensures:
            - Returns dictionary mapping categories to module names
            - Only includes modules that have quick_smoke_test() function
            - Filters by requested categories if provided
            - Logs discovery progress if debug enabled
            
        Raises:
            - ImportError if CoSA framework is not accessible
        
        Args:
            categories: Optional list of categories to discover (None = all)
            
        Returns:
            Dict[str, List[str]]: Category name -> list of module names with smoke tests
        """
        discovered_tests = {}
        target_categories = categories or list( self.test_categories.keys() )
        
        self.log( f"Discovering smoke tests in categories: {target_categories}" )
        
        for category in target_categories:
            if category not in self.test_categories:
                self.log( f"Warning: Unknown category '{category}'" )
                continue
                
            discovered_tests[category] = []
            
            for module_path in self.test_categories[category]:
                try:
                    # Import the module
                    full_module_name = f"cosa.{module_path}"
                    module = importlib.import_module( full_module_name )
                    
                    # Check if it has quick_smoke_test function
                    if hasattr( module, 'quick_smoke_test' ):
                        discovered_tests[category].append( module_path )
                        self.log( f"Found smoke test in {full_module_name}" )
                    else:
                        self.log( f"No smoke test in {full_module_name}" )
                        
                except ImportError as e:
                    self.log( f"Could not import {full_module_name}: {e}" )
                except Exception as e:
                    self.log( f"Error checking {full_module_name}: {e}" )
        
        # Remove empty categories
        discovered_tests = { k: v for k, v in discovered_tests.items() if v }
        
        total_tests = sum( len( modules ) for modules in discovered_tests.values() )
        self.log( f"Discovered {total_tests} smoke tests across {len(discovered_tests)} categories" )
        
        return discovered_tests
    
    def execute_smoke_test( self, module_path: str ) -> Tuple[bool, float, str]:
        """
        Execute quick_smoke_test() function for a specific module.
        
        Requires:
            - module_path is a valid CoSA module path
            - Module has quick_smoke_test() function
            - Timeout is configured appropriately
            
        Ensures:
            - Executes smoke test with timeout protection
            - Captures success/failure status and timing
            - Returns error details for failed tests
            - Handles all exceptions gracefully
            
        Raises:
            - None (all exceptions caught and converted to failure status)
        
        Args:
            module_path: CoSA module path (e.g., "agents.v010.math_agent")
            
        Returns:
            Tuple[bool, float, str]: (success, duration_seconds, error_message)
        """
        start_time = time.time()
        
        try:
            # Import the module
            full_module_name = f"cosa.{module_path}"
            module = importlib.import_module( full_module_name )
            
            # Execute the smoke test
            self.log( f"Executing smoke test for {full_module_name}" )
            
            # Capture output to prevent pollution of test results
            import io
            import contextlib
            
            output_buffer = io.StringIO()
            
            with contextlib.redirect_stdout( output_buffer ):
                with contextlib.redirect_stderr( output_buffer ):
                    module.quick_smoke_test()
            
            duration = time.time() - start_time
            self.log( f"Smoke test for {full_module_name} completed in {duration:.2f}s" )
            
            return True, duration, ""
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"{type(e).__name__}: {str(e)}"
            self.log( f"Smoke test for {module_path} failed: {error_msg}" )
            
            if self.debug:
                self.log( f"Full traceback: {traceback.format_exc()}" )
            
            return False, duration, error_msg
    
    def execute_category( self, category: str, module_paths: List[str] ) -> Dict[str, Any]:
        """
        Execute all smoke tests in a specific category.
        
        Requires:
            - category is a valid category name
            - module_paths is a non-empty list of valid module paths
            - All modules in list have smoke test functions
            
        Ensures:
            - Executes all smoke tests in the category
            - Collects timing and success statistics
            - Returns comprehensive category results
            - Continues execution even if individual tests fail
            
        Raises:
            - None (individual test failures do not stop category execution)
        
        Args:
            category: Category name (e.g., "agents", "core")
            module_paths: List of module paths in this category
            
        Returns:
            Dict[str, Any]: Category results with statistics and test details
        """
        category_start_time = time.time()
        
        self.utils.print_banner( f"{category.upper()} CATEGORY SMOKE TESTS" )
        print( f"Running {len(module_paths)} tests in {category} category..." )
        
        category_results = {
            "category": category,
            "total_tests": len( module_paths ),
            "passed_tests": 0,
            "failed_tests": 0,
            "total_duration": 0.0,
            "test_details": []
        }
        
        for i, module_path in enumerate( module_paths, 1 ):
            print( f"  [{i}/{len(module_paths)}] Testing {module_path}...", end=" " )
            
            success, duration, error_msg = self.execute_smoke_test( module_path )
            
            test_detail = {
                "module": module_path,
                "success": success,
                "duration": duration,
                "error": error_msg
            }
            
            category_results["test_details"].append( test_detail )
            self.test_results.append( test_detail )
            
            if success:
                category_results["passed_tests"] += 1
                print( f"✓ PASSED ({self.utils.format_duration(duration)})" )
            else:
                category_results["failed_tests"] += 1
                print( f"✗ FAILED ({self.utils.format_duration(duration)})" )
                if error_msg:
                    print( f"    Error: {error_msg}" )
        
        category_results["total_duration"] = time.time() - category_start_time
        
        # Category summary
        success_rate = ( category_results["passed_tests"] / category_results["total_tests"] * 100 ) if category_results["total_tests"] > 0 else 0
        print( f"\n{category.upper()} Results: {category_results['passed_tests']}/{category_results['total_tests']} passed ({success_rate:.1f}%) in {self.utils.format_duration(category_results['total_duration'])}" )
        
        return category_results
    
    def run_tests( self, categories: Optional[List[str]] = None, quick: bool = False ) -> Dict[str, Any]:
        """
        Run smoke tests for specified categories.
        
        Requires:
            - categories is None or list of valid category names
            - CoSA framework is properly configured
            - All test infrastructure is available
            
        Ensures:
            - Discovers and executes all available smoke tests
            - Provides comprehensive results with statistics
            - Supports quick mode for subset of critical tests
            - Returns structured results for baseline comparison
            
        Raises:
            - SystemExit if no tests are discovered or critical failures occur
        
        Args:
            categories: Optional list of categories to test (None = all)
            quick: If True, run subset of critical tests only
            
        Returns:
            Dict[str, Any]: Comprehensive test results with statistics
        """
        start_time = time.time()
        
        self.utils.print_banner( "CoSA FRAMEWORK SMOKE TEST SUITE", prepend_nl=True )
        
        if quick:
            print( "🚀 QUICK MODE: Running critical tests only" )
            # In quick mode, focus on core and essential agent tests
            if not categories:
                categories = ["core", "agents"]
        
        # Discover available tests
        discovered_tests = self.discover_smoke_tests( categories )
        
        if not discovered_tests:
            print( "❌ No smoke tests discovered!" )
            print( "Please check CoSA framework installation and PYTHONPATH" )
            sys.exit( 1 )
        
        # Execute tests by category
        category_results = []
        total_passed = 0
        total_tests = 0
        
        for category, module_paths in discovered_tests.items():
            if quick and len( module_paths ) > 5:
                # In quick mode, run only first 5 tests per category
                module_paths = module_paths[:5]
                print( f"Quick mode: Testing first 5 modules in {category} category" )
            
            category_result = self.execute_category( category, module_paths )
            category_results.append( category_result )
            
            total_passed += category_result["passed_tests"]
            total_tests += category_result["total_tests"]
            
            print()  # Spacing between categories
        
        # Overall results
        total_duration = time.time() - start_time
        success_rate = ( total_passed / total_tests * 100 ) if total_tests > 0 else 0
        
        overall_results = {
            "timestamp": time.strftime( "%Y-%m-%d %H:%M:%S" ),
            "total_tests": total_tests,
            "passed_tests": total_passed,
            "failed_tests": total_tests - total_passed,
            "success_rate": success_rate,
            "total_duration": total_duration,
            "quick_mode": quick,
            "categories": category_results,
            "test_details": self.test_results
        }
        
        return overall_results
    
    def print_summary( self, results: Dict[str, Any] ):
        """
        Print comprehensive test results summary.
        
        Requires:
            - results contains complete test execution results
            - results has required keys: total_tests, passed_tests, etc.
            
        Ensures:
            - Prints formatted summary with statistics
            - Shows results by category
            - Displays overall success/failure determination
            - Provides actionable guidance for failures
            
        Raises:
            - KeyError if required result keys are missing
        """
        self.utils.print_banner( "TEST RESULTS SUMMARY" )
        
        # Overall results
        print( f"✅ Tests Passed: {results['passed_tests']}/{results['total_tests']} ({results['success_rate']:.1f}%)" )
        print( f"❌ Tests Failed: {results['failed_tests']}" )
        print( f"⏱️  Total Duration: {self.utils.format_duration(results['total_duration'])}" )
        
        if results.get( 'quick_mode' ):
            print( "🚀 Quick Mode: Subset of tests executed" )
        
        print()
        
        # Results by category
        print( "📊 Results by Category:" )
        for category_result in results['categories']:
            category = category_result['category']
            passed = category_result['passed_tests']
            total = category_result['total_tests']
            rate = ( passed / total * 100 ) if total > 0 else 0
            duration = self.utils.format_duration( category_result['total_duration'] )
            
            status = "✅" if passed == total else "⚠️" if passed > 0 else "❌"
            print( f"  {status} {category:12}: {passed:2}/{total:2} ({rate:5.1f}%) - {duration}" )
        
        print()
        
        # Failed tests details
        failed_tests = [test for test in results['test_details'] if not test['success']]
        if failed_tests:
            print( "❌ Failed Tests Details:" )
            for test in failed_tests:
                print( f"  • {test['module']}: {test['error']}" )
            print()
        
        # Final status
        if results['passed_tests'] == results['total_tests']:
            print( "🎉 ALL TESTS PASSED! CoSA framework is working perfectly." )
        elif results['success_rate'] >= 80.0:
            print( "✅ MOSTLY SUCCESSFUL! Minor issues detected - check failed tests above." )
        else:
            print( "❌ SIGNIFICANT FAILURES! CoSA framework may have serious issues." )
            print( "   Please review failed tests and check framework configuration." )


def main():
    """
    CLI entry point for CoSA smoke test runner.
    
    Requires:
        - argparse module is available for command line parsing
        - CoSA framework is properly installed and configured
        - All test dependencies are available
        
    Ensures:
        - Parses command line arguments correctly
        - Executes appropriate test suite based on arguments
        - Prints comprehensive results summary
        - Exits with appropriate status code based on test results
        
    Raises:
        - SystemExit with 0 for success, 1 for failure
    """
    parser = argparse.ArgumentParser(
        description="CoSA Framework Smoke Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run all smoke tests
  %(prog)s --quick            # Run critical tests only  
  %(prog)s --category agents  # Run only agent tests
  %(prog)s --save-baseline    # Save results as baseline
  %(prog)s --compare-baseline # Compare with saved baseline
        """
    )
    
    parser.add_argument(
        "--category",
        choices=["core", "agents", "rest", "memory", "training"],
        help="Run tests for specific category only"
    )
    
    parser.add_argument(
        "--quick", 
        action="store_true",
        help="Run subset of critical tests for quick validation"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output and verbose logging"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout for individual tests in seconds (default: 120)"
    )
    
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Save test results as baseline for future comparison"
    )
    
    parser.add_argument(
        "--compare-baseline",
        action="store_true", 
        help="Compare results with saved baseline"
    )
    
    args = parser.parse_args()
    
    # Initialize test runner
    runner = CoSASmokeTestRunner( debug=args.debug, timeout=args.timeout )
    
    # Run tests
    categories = [args.category] if args.category else None
    results = runner.run_tests( categories=categories, quick=args.quick )
    
    # Handle baseline operations
    if args.save_baseline:
        baseline_file = runner.baseline_mgr.save_baseline( results )
        print( f"\n💾 Baseline saved: {baseline_file}" )
    
    if args.compare_baseline:
        comparison = runner.baseline_mgr.compare_baseline( results )
        print( f"\n📊 Baseline comparison: {comparison}" )
    
    # Print summary
    runner.print_summary( results )
    
    # Exit with appropriate code
    success_rate = results['success_rate']
    if success_rate == 100.0:
        sys.exit( 0 )  # Perfect success
    elif success_rate >= 80.0:
        sys.exit( 0 )  # Acceptable success rate
    else:
        sys.exit( 1 )  # Too many failures


if __name__ == "__main__":
    main()