"""
Unit tests for notification types and constants with comprehensive validation.

Tests the notification_types module including:
- NotificationType enum with all valid values
- NotificationPriority enum with proper hierarchy
- Default value configuration and constants
- API configuration constants validation
- Environment variable name definitions
- Enum value extraction and list conversion
- Type safety and validation support
- Constants consistency across the notification system

Zero external dependencies - all enum operations and constant validations
are performed in isolation for comprehensive testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import time
from typing import List
import sys
import os

# Import test infrastructure (from CoSA test infrastructure)
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "..", "cosa", "tests", "unit", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from lupin_cli.notifications.notification_types import (
    NotificationType, NotificationPriority,
    DEFAULT_TYPE, DEFAULT_PRIORITY,
    DEFAULT_API_KEY, DEFAULT_SERVER_URL,
    ENV_CLI_PATH, ENV_SERVER_URL
)


class TestNotificationTypes( unittest.TestCase ):
    """
    Comprehensive unit tests for notification types and constants.
    
    Requires:
        - MockManager for consistency (though not needed for pure constants)
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All notification type enums tested thoroughly
        - Constants and defaults validated
        - Enum behavior and values verified
        - Integration constants confirmed
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available for consistency
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset (for consistency)
        """
        self.mock_manager.reset_mocks()
    
    def test_notification_type_enum_values( self ):
        """
        Test NotificationType enum contains all expected values.
        
        Ensures:
            - All required notification types are defined
            - Enum values match expected string representations
            - No unexpected values are present
        """
        # Test individual enum values
        self.assertEqual( NotificationType.TASK.value, "task" )
        self.assertEqual( NotificationType.PROGRESS.value, "progress" )
        self.assertEqual( NotificationType.ALERT.value, "alert" )
        self.assertEqual( NotificationType.CUSTOM.value, "custom" )
        
        # Test enum completeness
        expected_types = {"task", "progress", "alert", "custom"}
        actual_types = {item.value for item in NotificationType}
        self.assertEqual( actual_types, expected_types )
        
        # Verify enum count
        self.assertEqual( len( NotificationType ), 4 )
    
    def test_notification_type_values_method( self ):
        """
        Test NotificationType.values() class method returns correct list.
        
        Ensures:
            - Returns list of all enum values as strings
            - Order matches enum declaration order
            - Contains exactly 4 elements
            - All values are strings
        """
        values = NotificationType.values()
        
        # Test return type and content
        self.assertIsInstance( values, list )
        self.assertEqual( len( values ), 4 )
        
        # Test expected values in order
        expected_values = ["task", "progress", "alert", "custom"]
        self.assertEqual( values, expected_values )
        
        # Test all values are strings
        for value in values:
            self.assertIsInstance( value, str )
    
    def test_notification_priority_enum_values( self ):
        """
        Test NotificationPriority enum contains all expected values.
        
        Ensures:
            - All required priority levels are defined
            - Enum values match expected string representations
            - Priority hierarchy is maintained in declaration order
        """
        # Test individual enum values
        self.assertEqual( NotificationPriority.LOW.value, "low" )
        self.assertEqual( NotificationPriority.MEDIUM.value, "medium" )
        self.assertEqual( NotificationPriority.HIGH.value, "high" )
        self.assertEqual( NotificationPriority.URGENT.value, "urgent" )
        
        # Test enum completeness
        expected_priorities = {"low", "medium", "high", "urgent"}
        actual_priorities = {item.value for item in NotificationPriority}
        self.assertEqual( actual_priorities, expected_priorities )
        
        # Verify enum count
        self.assertEqual( len( NotificationPriority ), 4 )
    
    def test_notification_priority_values_method( self ):
        """
        Test NotificationPriority.values() class method returns correct list.
        
        Ensures:
            - Returns list of all enum values as strings
            - Order reflects priority hierarchy (low to urgent)
            - Contains exactly 4 elements
            - All values are strings
        """
        values = NotificationPriority.values()
        
        # Test return type and content
        self.assertIsInstance( values, list )
        self.assertEqual( len( values ), 4 )
        
        # Test expected values in priority order
        expected_values = ["low", "medium", "high", "urgent"]
        self.assertEqual( values, expected_values )
        
        # Test all values are strings
        for value in values:
            self.assertIsInstance( value, str )
    
    def test_notification_priority_hierarchy( self ):
        """
        Test notification priority hierarchy and ordering.
        
        Ensures:
            - Priority levels are in logical ascending order
            - Enum supports comparison operations
            - Priority semantics are preserved
        """
        # Test priority order (conceptually, not enum comparison)
        priorities = list( NotificationPriority )
        priority_values = [p.value for p in priorities]
        
        # Verify logical order from low to urgent
        expected_order = ["low", "medium", "high", "urgent"]
        self.assertEqual( priority_values, expected_order )
        
        # Test individual priority semantics
        self.assertEqual( priorities[0].value, "low" )      # Lowest priority
        self.assertEqual( priorities[-1].value, "urgent" )  # Highest priority
    
    def test_default_constants( self ):
        """
        Test default value constants are correctly defined.
        
        Ensures:
            - DEFAULT_TYPE uses appropriate default notification type
            - DEFAULT_PRIORITY uses appropriate default priority level
            - Defaults match enum values
            - Constants are strings
        """
        # Test default type
        self.assertEqual( DEFAULT_TYPE, "custom" )
        self.assertIn( DEFAULT_TYPE, NotificationType.values() )
        self.assertIsInstance( DEFAULT_TYPE, str )
        
        # Test default priority
        self.assertEqual( DEFAULT_PRIORITY, "medium" )
        self.assertIn( DEFAULT_PRIORITY, NotificationPriority.values() )
        self.assertIsInstance( DEFAULT_PRIORITY, str )
        
        # Verify defaults are reasonable choices
        self.assertEqual( DEFAULT_TYPE, NotificationType.CUSTOM.value )
        self.assertEqual( DEFAULT_PRIORITY, NotificationPriority.MEDIUM.value )
    
    def test_api_configuration_constants( self ):
        """
        Test API configuration constants are properly defined.
        
        Ensures:
            - DEFAULT_API_KEY contains expected authentication key
            - DEFAULT_SERVER_URL contains valid localhost URL
            - Constants are non-empty strings
            - URL format is correct for local development
        """
        # Test API key constant
        self.assertEqual( DEFAULT_API_KEY, "claude_code_simple_key" )
        self.assertIsInstance( DEFAULT_API_KEY, str )
        self.assertGreater( len( DEFAULT_API_KEY ), 0 )
        
        # Test server URL constant
        self.assertEqual( DEFAULT_SERVER_URL, "http://localhost:7999" )
        self.assertIsInstance( DEFAULT_SERVER_URL, str )
        self.assertTrue( DEFAULT_SERVER_URL.startswith( "http://" ) )
        self.assertIn( "localhost", DEFAULT_SERVER_URL )
        self.assertIn( "7999", DEFAULT_SERVER_URL )
    
    def test_environment_variable_constants( self ):
        """
        Test environment variable name constants are properly defined.
        
        Ensures:
            - ENV_CLI_PATH contains correct environment variable name
            - ENV_SERVER_URL contains correct environment variable name
            - Constants follow standard environment variable naming
            - Variable names are descriptive and consistent
        """
        # Test CLI path environment variable
        self.assertEqual( ENV_CLI_PATH, "COSA_CLI_PATH" )
        self.assertIsInstance( ENV_CLI_PATH, str )
        self.assertTrue( ENV_CLI_PATH.startswith( "COSA_" ) )
        
        # Test server URL environment variable
        self.assertEqual( ENV_SERVER_URL, "LUPIN_APP_SERVER_URL" )
        self.assertIsInstance( ENV_SERVER_URL, str )
        self.assertTrue( ENV_SERVER_URL.startswith( "LUPIN_" ) )

        # Test naming consistency
        self.assertTrue( ENV_CLI_PATH.isupper() )
        self.assertTrue( ENV_SERVER_URL.isupper() )
    
    def test_enum_type_safety( self ):
        """
        Test enum type safety and validation support.
        
        Ensures:
            - Enums provide type safety for notification system
            - Enum values can be validated against allowed types
            - Invalid values are not present in enum values
        """
        # Test NotificationType validation support
        valid_types = NotificationType.values()
        self.assertIn( "task", valid_types )
        self.assertIn( "progress", valid_types )
        self.assertIn( "alert", valid_types )
        self.assertIn( "custom", valid_types )
        
        # Test invalid types are not in enum
        invalid_types = ["invalid", "error", "debug", "info", "warning"]
        for invalid_type in invalid_types:
            self.assertNotIn( invalid_type, valid_types )
        
        # Test NotificationPriority validation support
        valid_priorities = NotificationPriority.values()
        self.assertIn( "low", valid_priorities )
        self.assertIn( "medium", valid_priorities )
        self.assertIn( "high", valid_priorities )
        self.assertIn( "urgent", valid_priorities )
        
        # Test invalid priorities are not in enum
        invalid_priorities = ["critical", "normal", "severe", "minor", "emergency"]
        for invalid_priority in invalid_priorities:
            self.assertNotIn( invalid_priority, valid_priorities )
    
    def test_enum_string_consistency( self ):
        """
        Test enum string values are consistent with attribute names.
        
        Ensures:
            - Enum attribute names correspond to their string values
            - Case conversion is consistent (UPPER attribute -> lower value)
            - No naming mismatches between attributes and values
        """
        # Test NotificationType string consistency
        type_mappings = {
            "TASK": "task",
            "PROGRESS": "progress", 
            "ALERT": "alert",
            "CUSTOM": "custom"
        }
        
        for attr_name, expected_value in type_mappings.items():
            enum_item = getattr( NotificationType, attr_name )
            self.assertEqual( enum_item.value, expected_value )
        
        # Test NotificationPriority string consistency
        priority_mappings = {
            "LOW": "low",
            "MEDIUM": "medium",
            "HIGH": "high", 
            "URGENT": "urgent"
        }
        
        for attr_name, expected_value in priority_mappings.items():
            enum_item = getattr( NotificationPriority, attr_name )
            self.assertEqual( enum_item.value, expected_value )
    
    def test_constants_integration_compatibility( self ):
        """
        Test constants work correctly with notification system integration.
        
        Ensures:
            - Constants can be used with enum validation
            - Default values are compatible with enum types
            - API and environment constants support system integration
        """
        # Test default type compatibility
        self.assertIn( DEFAULT_TYPE, NotificationType.values() )
        default_type_enum = NotificationType( DEFAULT_TYPE )
        self.assertEqual( default_type_enum.value, DEFAULT_TYPE )
        
        # Test default priority compatibility  
        self.assertIn( DEFAULT_PRIORITY, NotificationPriority.values() )
        default_priority_enum = NotificationPriority( DEFAULT_PRIORITY )
        self.assertEqual( default_priority_enum.value, DEFAULT_PRIORITY )
        
        # Test API configuration format
        self.assertIsInstance( DEFAULT_API_KEY, str )
        self.assertGreater( len( DEFAULT_API_KEY ), 5 )  # Reasonable minimum length
        
        # Test server URL format  
        self.assertTrue( DEFAULT_SERVER_URL.startswith( ("http://", "https://") ) )
        self.assertNotIn( " ", DEFAULT_SERVER_URL )  # No spaces in URL


def isolated_unit_test():
    """
    Run comprehensive unit tests for notification types in complete isolation.
    
    Ensures:
        - All enum operations tested without external dependencies
        - Constants and values validated thoroughly
        - Type safety and integration compatibility confirmed
        - Fast execution with deterministic results
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "Notification Types Unit Tests - External Phase 5", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_notification_type_enum_values',
            'test_notification_type_values_method',
            'test_notification_priority_enum_values',
            'test_notification_priority_values_method',
            'test_notification_priority_hierarchy',
            'test_default_constants',
            'test_api_configuration_constants',
            'test_environment_variable_constants',
            'test_enum_type_safety',
            'test_enum_string_consistency',
            'test_constants_integration_compatibility'
        ]
        
        for method in test_methods:
            suite.addTest( TestNotificationTypes( method ) )
        
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
        print( f"NOTIFICATION TYPES UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL NOTIFICATION TYPES TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME NOTIFICATION TYPES TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 NOTIFICATION TYPES TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Notification types unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )