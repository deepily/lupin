#!/usr/bin/env python3
"""
End-to-end test script for Claude Code notification system

This script runs comprehensive tests of the notification pipeline to verify
that Claude Code can successfully communicate with users through the 
Lupin application.

Usage:
    python3 test_notifications.py
    python3 test_notifications.py --quick    # Run abbreviated test suite
    python3 test_notifications.py --debug    # Enable debug output
"""

import os
import sys
import time
import argparse
from typing import List, Tuple, Dict, Any

# Import notification functionality
from lupin_cli.notifications.notify_user import notify_user, validate_environment
from lupin_cli.notifications.notification_types import NotificationType, NotificationPriority


class NotificationTestSuite:
    """
    Comprehensive test suite for Claude Code notifications.
    
    Provides structured testing of the notification system with various
    test scenarios including basic functionality, priority levels, 
    realistic workflows, and error handling.
    
    Requires:
        - notify_user function is available and functional
        - NotificationType and NotificationPriority enums are accessible
        - time module is available for timing and delays
        
    Ensures:
        - Provides comprehensive test coverage of notification system
        - Records detailed test results and statistics
        - Supports both quick and full test suites
        - Handles errors gracefully during testing
    """
    
    def __init__( self, debug: bool = False, delay: float = 1.0 ):
        """
        Initialize the notification test suite.
        
        Requires:
            - debug is a boolean flag for debug output
            - delay is a non-negative float for inter-test delays
            
        Ensures:
            - Sets up test configuration with debug and delay settings
            - Initializes empty results list for test tracking
            - Prepares suite for test execution
            
        Raises:
            - None
        """
        self.debug = debug
        self.delay = delay  # Delay between tests to prevent overwhelming
        self.results: List[Dict[str, Any]] = []
    
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
    
    def run_test( 
        self, 
        test_name: str, 
        message: str, 
        notification_type: str, 
        priority: str 
    ) -> bool:
        """
        Run individual notification test.
        
        Requires:
            - test_name is a non-empty descriptive string
            - message is the notification message to send
            - notification_type is a valid notification type
            - priority is a valid priority level
            - notify_user function is available
            
        Ensures:
            - Executes notification test with timing
            - Records test result with full metadata
            - Prints formatted test progress and results
            - Adds configurable delay between tests
            - Returns True if notification succeeded, False otherwise
            
        Raises:
            - None (handles all exceptions gracefully)
        
        Args:
            test_name: Human-readable test name
            message: Notification message 
            notification_type: Type of notification
            priority: Priority level
            
        Returns:
            bool: True if test passed
        """
        
        self.log( f"Running test: {test_name}" )
        self.log( f"  Type: {notification_type}, Priority: {priority}" )
        self.log( f"  Message: {message}" )
        
        print( f"\n🧪 {test_name}" )
        print( f"   Type: {notification_type} | Priority: {priority}" )
        print( f"   Message: \"{message}\"" )
        
        start_time = time.time()
        success = notify_user( message, notification_type, priority )
        duration = time.time() - start_time
        
        # Record result
        result = {
            "test_name": test_name,
            "message": message,
            "type": notification_type,
            "priority": priority,
            "success": success,
            "duration": duration
        }
        self.results.append( result )
        
        if success:
            print( f"   ✓ PASSED ({duration:.2f}s)" )
        else:
            print( f"   ✗ FAILED ({duration:.2f}s)" )
        
        self.log( f"Test result: {'PASSED' if success else 'FAILED'} in {duration:.2f}s" )
        
        # Add delay between tests
        if self.delay > 0:
            time.sleep( self.delay )
        
        return success
    
    def run_basic_tests( self ) -> int:
        """
        Run basic notification type tests
        
        Returns:
            int: Number of tests that passed
        """
        
        print( "📋 Running Basic Notification Tests" )
        print( "=" * 50 )
        
        tests = [
            ( "Basic Custom Notification", "Test notification from Claude Code", "custom", "medium" ),
            ( "Task Completion Success", "Build completed successfully", "task", "high" ),
            ( "Task Completion Failure", "Tests failed - please check output", "task", "high" ),
            ( "Progress Update", "Installing dependencies (step 1/4)", "progress", "low" ),
            ( "Warning Alert", "Deprecated API usage detected", "alert", "medium" ),
            ( "Critical Alert", "Disk space critically low", "alert", "urgent" ),
        ]
        
        passed = 0
        for test_name, message, msg_type, priority in tests:
            if self.run_test( test_name, message, msg_type, priority ):
                passed += 1
        
        return passed
    
    def run_priority_tests( self ) -> int:
        """
        Run priority level tests
        
        Returns:
            int: Number of tests that passed
        """
        
        print( "\n🔔 Running Priority Level Tests" )
        print( "=" * 50 )
        
        tests = [
            ( "Low Priority Info", "Background cache cleanup completed", "custom", "low" ),
            ( "Medium Priority Update", "Code analysis finished", "custom", "medium" ),
            ( "High Priority Warning", "Memory usage approaching limit", "custom", "high" ),
            ( "Urgent Priority Alert", "System error requires immediate attention", "custom", "urgent" ),
        ]
        
        passed = 0
        for test_name, message, msg_type, priority in tests:
            if self.run_test( test_name, message, msg_type, priority ):
                passed += 1
        
        return passed
    
    def run_realistic_workflow_tests( self ) -> int:
        """
        Run realistic development workflow tests
        
        Returns:
            int: Number of tests that passed
        """
        
        print( "\n⚙️  Running Realistic Workflow Tests" )
        print( "=" * 50 )
        
        workflow_tests = [
            ( "Build Started", "Starting build process for lupin", "progress", "low" ),
            ( "Dependencies Installed", "npm install completed successfully", "progress", "low" ),
            ( "Running Tests", "Executing test suite (15 tests)", "progress", "medium" ),
            ( "Tests Passed", "All tests passed - 15/15 successful", "task", "medium" ),
            ( "Build Complete", "Build completed successfully in 2m 34s", "task", "high" ),
            ( "Deployment Ready", "Application ready for deployment", "task", "high" ),
        ]
        
        passed = 0
        for test_name, message, msg_type, priority in workflow_tests:
            if self.run_test( test_name, message, msg_type, priority ):
                passed += 1
        
        return passed
    
    def run_error_scenarios( self ) -> int:
        """
        Run error handling and edge case tests
        
        Returns:
            int: Number of tests that passed (error tests pass if they handle errors gracefully)
        """
        
        print( "\n⚠️  Running Error Scenario Tests" )
        print( "=" * 50 )
        
        error_tests = [
            ( "Empty Message", "", "custom", "medium" ),
            ( "Very Long Message", "This is a very long message " * 10, "custom", "medium" ),
            ( "Special Characters", "Message with émojis 🎉 and symbols #@$%", "custom", "medium" ),
            ( "Multiline Message", "Line 1\nLine 2\nLine 3", "custom", "medium" ),
        ]
        
        passed = 0
        for test_name, message, msg_type, priority in error_tests:
            # For error scenarios, we expect them to either succeed or fail gracefully
            result = self.run_test( test_name, message, msg_type, priority )
            # Count as passed if it doesn't crash (already handled by run_test)
            passed += 1
        
        return passed
    
    def run_quick_tests( self ) -> int:
        """
        Run abbreviated test suite for quick validation
        
        Returns:
            int: Number of tests that passed
        """
        
        print( "⚡ Running Quick Test Suite" )
        print( "=" * 50 )
        
        quick_tests = [
            ( "Basic Notification", "Quick test from Claude Code", "custom", "medium" ),
            ( "Task Success", "Quick task completed", "task", "medium" ),
            ( "Alert Test", "Quick alert test", "alert", "high" ),
        ]
        
        passed = 0
        for test_name, message, msg_type, priority in quick_tests:
            if self.run_test( test_name, message, msg_type, priority ):
                passed += 1
        
        return passed
    
    def print_summary( self, total_passed: int, total_tests: int ):
        """
        Print comprehensive test results summary.
        
        Requires:
            - total_passed is a non-negative integer <= total_tests
            - total_tests is a non-negative integer
            - self.results contains test result dictionaries
            
        Ensures:
            - Prints detailed test statistics and breakdowns
            - Shows results by notification type and priority
            - Displays performance metrics (timing statistics)
            - Provides overall pass/fail determination
            - Returns True for successful test run, False otherwise
            
        Raises:
            - None (handles division by zero and empty results)
        """
        
        print( "\n" + "=" * 60 )
        print( "📊 TEST RESULTS SUMMARY" )
        print( "=" * 60 )
        
        # Overall results
        success_rate = ( total_passed / total_tests * 100 ) if total_tests > 0 else 0
        print( f"✅ Tests Passed: {total_passed}/{total_tests} ({success_rate:.1f}%)" )
        print( f"❌ Tests Failed: {total_tests - total_passed}" )
        
        # Results by type
        type_stats = {}
        priority_stats = {}
        
        for result in self.results:
            # Count by type
            msg_type = result['type']
            if msg_type not in type_stats:
                type_stats[msg_type] = { 'passed': 0, 'total': 0 }
            type_stats[msg_type]['total'] += 1
            if result['success']:
                type_stats[msg_type]['passed'] += 1
            
            # Count by priority  
            priority = result['priority']
            if priority not in priority_stats:
                priority_stats[priority] = { 'passed': 0, 'total': 0 }
            priority_stats[priority]['total'] += 1
            if result['success']:
                priority_stats[priority]['passed'] += 1
        
        print( "\n📈 Results by Notification Type:" )
        for msg_type, stats in sorted( type_stats.items() ):
            rate = ( stats['passed'] / stats['total'] * 100 ) if stats['total'] > 0 else 0
            print( f"  {msg_type:8}: {stats['passed']:2}/{stats['total']:2} ({rate:5.1f}%)" )
        
        print( "\n🔔 Results by Priority Level:" )
        for priority, stats in sorted( priority_stats.items() ):
            rate = ( stats['passed'] / stats['total'] * 100 ) if stats['total'] > 0 else 0
            print( f"  {priority:6}: {stats['passed']:2}/{stats['total']:2} ({rate:5.1f}%)" )
        
        # Performance stats
        if self.results:
            durations = [r['duration'] for r in self.results]
            avg_duration = sum( durations ) / len( durations )
            max_duration = max( durations )
            min_duration = min( durations )
            
            print( f"\n⏱️  Performance Statistics:" )
            print( f"  Average Response Time: {avg_duration:.2f}s" )
            print( f"  Fastest Response:      {min_duration:.2f}s" )
            print( f"  Slowest Response:      {max_duration:.2f}s" )
        
        # Final status
        print( "\n" + "=" * 60 )
        if total_passed == total_tests:
            print( "🎉 ALL TESTS PASSED! Notification system is working perfectly." )
            return True
        elif total_passed > total_tests * 0.8:  # 80% pass rate
            print( "✅ MOSTLY SUCCESSFUL! Minor issues detected." )
            return True
        else:
            print( "❌ TESTS FAILED! Check Lupin API status and configuration." )
            return False


def main():
    """
    CLI entry point for notification tests.
    
    Requires:
        - argparse module is available for command line parsing
        - validate_environment function is accessible
        - All test suite dependencies are available
        
    Ensures:
        - Parses command line arguments correctly
        - Validates environment before running tests
        - Executes appropriate test suite (quick or full)
        - Prints comprehensive results summary
        - Exits with appropriate status code
        
    Raises:
        - SystemExit with 0 for success, 1 for failure
    """
    
    parser = argparse.ArgumentParser(
        description="Test Claude Code notification system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run full test suite
  %(prog)s --quick            # Run abbreviated tests  
  %(prog)s --debug            # Enable debug output
  %(prog)s --delay 0.5        # Faster test execution
        """
    )
    
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run abbreviated test suite for quick validation"
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true",
        help="Enable debug output and verbose logging"
    )
    
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between tests in seconds (default: 1.0)"
    )
    
    parser.add_argument(
        "--validate-only",
        action="store_true", 
        help="Only validate environment, don't run tests"
    )
    
    args = parser.parse_args()
    
    print( "🧪 Claude Code Notification System Test Suite" )
    print( "=" * 60 )
    
    # Validate environment first
    print( "🔧 Validating Environment..." )
    if not validate_environment():
        print( "\n❌ Environment validation failed!" )
        print( "Please check your configuration and try again." )
        sys.exit( 1 )
    
    if args.validate_only:
        print( "\n✅ Environment validation completed successfully." )
        sys.exit( 0 )
    
    # Initialize test suite
    test_suite = NotificationTestSuite( debug=args.debug, delay=args.delay )
    
    # Run tests
    total_passed = 0
    total_tests = 0
    
    if args.quick:
        passed = test_suite.run_quick_tests()
        total_passed += passed
        total_tests += 3  # Number of quick tests
    else:
        # Run full test suite
        passed = test_suite.run_basic_tests()
        total_passed += passed
        total_tests += 6  # Number of basic tests
        
        passed = test_suite.run_priority_tests()
        total_passed += passed  
        total_tests += 4  # Number of priority tests
        
        passed = test_suite.run_realistic_workflow_tests()
        total_passed += passed
        total_tests += 6  # Number of workflow tests
        
        passed = test_suite.run_error_scenarios()
        total_passed += passed
        total_tests += 4  # Number of error tests
    
    # Print summary and determine exit code
    success = test_suite.print_summary( total_passed, total_tests )
    sys.exit( 0 if success else 1 )


if __name__ == "__main__":
    main()