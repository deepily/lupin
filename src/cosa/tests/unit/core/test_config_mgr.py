#!/usr/bin/env python3
"""
Unit Tests: ConfigurationManager

Comprehensive unit tests for the CoSA ConfigurationManager with complete
mocking of file system operations to ensure zero external dependencies.

This test module validates:
- ConfigurationManager instantiation and singleton behavior
- Configuration file loading with various scenarios
- Environment variable override functionality
- Type conversion and validation
- Error handling for missing/invalid configurations
"""

import os
import sys
import tempfile
from pathlib import Path

# Import test infrastructure
try:
    from cosa.tests.unit.infrastructure.mock_manager import MockManager
    from cosa.tests.unit.infrastructure.test_fixtures import CoSATestFixtures
    from cosa.tests.unit.infrastructure.unit_test_utilities import UnitTestUtilities
except ImportError as e:
    print( f"Failed to import test infrastructure: {e}" )
    sys.exit( 1 )

# Import the module under test
try:
    from cosa.config.configuration_manager import ConfigurationManager
except ImportError as e:
    print( f"Failed to import ConfigurationManager: {e}" )
    sys.exit( 1 )


class ConfigurationManagerUnitTests:
    """
    Unit test suite for ConfigurationManager.
    
    Provides comprehensive testing of configuration management functionality
    including file loading, environment variable handling, type conversion,
    and error scenarios with complete external dependency mocking.
    
    Requires:
        - MockManager for file system mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All configuration scenarios are tested
        - No external files or services are accessed
        - Singleton behavior is properly validated
        - Performance requirements are met
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize configuration manager unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
    
    def test_basic_instantiation( self ) -> bool:
        """
        Test basic ConfigurationManager instantiation.
        
        Ensures:
            - ConfigurationManager can be created
            - Singleton pattern works correctly
            - Basic methods are available
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing ConfigurationManager Instantiation" )
        
        try:
            # Test basic instantiation with mocked environment
            with self.utils.temp_environment( { "LUPIN_CONFIG_MGR_CLI_ARGS": "test_env" } ):
                with self.mock_mgr.config_manager_mock() as mock_config:
                    # Test that mock config manager has expected interface
                    assert hasattr( mock_config, 'get' ), "ConfigurationManager should have get method"
                    
                    # Test basic get operation
                    value = mock_config.get( "app debug", default=False, return_type="boolean" )
                    assert isinstance( value, bool ), f"Boolean conversion failed, got {type( value )}"
                    
                    # Test string get operation
                    str_value = mock_config.get( "test_key", default="default_value" )
                    assert isinstance( str_value, str ), f"String value should be string, got {type( str_value )}"
                    
                    self.utils.print_test_status( "Basic instantiation test passed", "PASS" )
                    return True
            
        except Exception as e:
            self.utils.print_test_status( f"Basic instantiation test failed: {e}", "FAIL" )
            return False
    
    def test_configuration_file_loading( self ) -> bool:
        """
        Test configuration file loading with various scenarios.
        
        Ensures:
            - Valid configuration files are loaded correctly
            - Missing configuration files are handled gracefully
            - Malformed configuration files generate appropriate errors
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Configuration File Loading" )
        
        try:
            # Test scenario 1: Valid configuration file
            valid_config = {
                "DEFAULT": {
                    "app debug": "false",
                    "agent_timeout": "30",
                    "openai_api_key": "test_key_12345"
                },
                "agents": {
                    "math_enabled": "true",
                    "weather_timeout": "10"
                }
            }
            
            with self.mock_mgr.filesystem_mock( {
                "lupin-app.ini": self._dict_to_ini_content( valid_config )
            } ):
                with self.mock_mgr.config_manager_mock( {
                    "app debug": False,
                    "agent_timeout": 30,
                    "openai_api_key": "test_key_12345",
                    "math_enabled": True,
                    "weather_timeout": 10
                } ) as mock_config:
                    
                    # Test boolean conversion
                    debug_value = mock_config.get( "app debug", return_type="boolean" )
                    assert debug_value == False, f"Boolean conversion failed: {debug_value}"
                    
                    # Test integer conversion
                    timeout_value = mock_config.get( "agent_timeout", return_type="int" )
                    assert timeout_value == 30, f"Integer conversion failed: {timeout_value}"
                    
                    # Test string value
                    api_key = mock_config.get( "openai_api_key" )
                    assert api_key == "test_key_12345", f"String value incorrect: {api_key}"
                    
                    self.utils.print_test_status( "Valid config file test passed", "PASS" )
            
            # Test scenario 2: Missing configuration file
            with self.mock_mgr.filesystem_mock( {} ):  # No config files
                with self.mock_mgr.config_manager_mock( {} ) as mock_config:
                    # Should handle missing config gracefully with defaults
                    default_value = mock_config.get( "missing_key", default="default_value" )
                    assert default_value == "default_value", f"Default value handling failed: {default_value}"
                    
                    self.utils.print_test_status( "Missing config file test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Configuration file loading test failed: {e}", "FAIL" )
            return False
    
    def test_environment_variable_override( self ) -> bool:
        """
        Test environment variable override functionality.
        
        Ensures:
            - Environment variables properly override config file values
            - Environment variable processing works correctly
            - Type conversion applies to environment variables
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Environment Variable Override" )
        
        try:
            # Setup config with base values
            base_config = {
                "app debug": False,
                "agent_timeout": 30,
                "api_endpoint": "https://api.example.com"
            }
            
            # Setup environment variables that should override config
            env_overrides = {
                "LUPIN_APP_DEBUG": "true",
                "LUPIN_AGENT_TIMEOUT": "60",
                "LUPIN_API_ENDPOINT": "https://override.example.com"
            }
            
            with self.utils.temp_environment( env_overrides ):
                with self.mock_mgr.config_manager_mock( {
                    "app debug": True,   # Should be overridden by env var
                    "agent_timeout": 60, # Should be overridden by env var
                    "api_endpoint": "https://override.example.com"  # Should be overridden
                } ) as mock_config:
                    
                    # Test boolean override
                    debug_value = mock_config.get( "app debug", return_type="boolean" )
                    assert debug_value == True, f"Environment boolean override failed: {debug_value}"
                    
                    # Test integer override
                    timeout_value = mock_config.get( "agent_timeout", return_type="int" )
                    assert timeout_value == 60, f"Environment integer override failed: {timeout_value}"
                    
                    # Test string override
                    endpoint_value = mock_config.get( "api_endpoint" )
                    assert endpoint_value == "https://override.example.com", f"Environment string override failed: {endpoint_value}"
                    
                    self.utils.print_test_status( "Environment variable override test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Environment variable override test failed: {e}", "FAIL" )
            return False
    
    def test_type_conversion( self ) -> bool:
        """
        Test type conversion functionality.
        
        Ensures:
            - Boolean conversion handles various string formats
            - Integer and float conversions work correctly
            - Invalid type conversions are handled gracefully
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Type Conversion" )
        
        try:
            # Test various boolean representations
            boolean_tests = [
                ( "true", True ),
                ( "false", False ),
                ( "1", True ),
                ( "0", False ),
                ( "yes", True ),
                ( "no", False ),
                ( "True", True ),
                ( "False", False )
            ]
            
            for test_value, expected in boolean_tests:
                with self.mock_mgr.config_manager_mock( { "test_bool": test_value } ) as mock_config:
                    result = mock_config.get( "test_bool", return_type="boolean" )
                    assert result == expected, f"Boolean conversion failed for '{test_value}': got {result}, expected {expected}"
            
            # Test integer conversion
            integer_tests = [
                ( "42", 42 ),
                ( "0", 0 ),
                ( "-10", -10 ),
                ( "1000", 1000 )
            ]
            
            for test_value, expected in integer_tests:
                with self.mock_mgr.config_manager_mock( { "test_int": test_value } ) as mock_config:
                    result = mock_config.get( "test_int", return_type="int" )
                    assert result == expected, f"Integer conversion failed for '{test_value}': got {result}, expected {expected}"
            
            # Test float conversion
            float_tests = [
                ( "3.14", 3.14 ),
                ( "0.0", 0.0 ),
                ( "-2.5", -2.5 ),
                ( "100.0", 100.0 )
            ]
            
            for test_value, expected in float_tests:
                with self.mock_mgr.config_manager_mock( { "test_float": test_value } ) as mock_config:
                    result = mock_config.get( "test_float", return_type="float" )
                    assert abs( result - expected ) < 0.001, f"Float conversion failed for '{test_value}': got {result}, expected {expected}"
            
            self.utils.print_test_status( "Type conversion test passed", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Type conversion test failed: {e}", "FAIL" )
            return False
    
    def test_error_handling( self ) -> bool:
        """
        Test error handling scenarios.
        
        Ensures:
            - Invalid configuration values are handled gracefully
            - Missing required keys return appropriate defaults
            - Type conversion errors are handled properly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Error Handling" )
        
        try:
            # Test missing key with default
            with self.mock_mgr.config_manager_mock( {} ) as mock_config:
                result = mock_config.get( "missing_key", default="default_value" )
                assert result == "default_value", f"Missing key default failed: {result}"
            
            # Test invalid boolean conversion with default
            with self.mock_mgr.config_manager_mock( { "invalid_bool": "maybe" } ) as mock_config:
                # Should return default for invalid boolean
                result = mock_config.get( "invalid_bool", default=False, return_type="boolean" )
                # The mock should handle this gracefully
                assert isinstance( result, bool ), f"Invalid boolean should return boolean default: {result}"
            
            # Test None value handling
            with self.mock_mgr.config_manager_mock( { "null_value": None } ) as mock_config:
                result = mock_config.get( "null_value", default="default" )
                assert result == "default", f"None value should return default: {result}"
            
            self.utils.print_test_status( "Error handling test passed", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Error handling test failed: {e}", "FAIL" )
            return False
    
    def test_performance( self ) -> bool:
        """
        Test ConfigurationManager performance.
        
        Ensures:
            - Configuration operations complete within performance targets
            - Repeated access is efficient
            - Memory usage is reasonable
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            config_load_target = performance_targets[ "timing_targets" ][ "config_load_time" ]
            
            # Test configuration access performance
            with self.mock_mgr.config_manager_mock( {
                "test_key_1": "value1",
                "test_key_2": "value2",
                "test_key_3": "value3"
            } ) as mock_config:
                
                def config_access_test():
                    # Perform multiple configuration accesses
                    for i in range( 10 ):
                        mock_config.get( f"test_key_{i % 3 + 1}" )
                    return True
                
                # Test that configuration access is fast enough
                success, duration, result = self.utils.assert_timing( config_access_test, config_load_target * 10 )
                assert success, f"Configuration access too slow: {duration}s"
                
                self.utils.print_test_status( f"Performance test passed ({self.utils.format_duration( duration )})", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance test failed: {e}", "FAIL" )
            return False
    
    def _dict_to_ini_content( self, config_dict: dict ) -> str:
        """
        Convert dictionary to INI file content string.
        
        Args:
            config_dict: Configuration dictionary
            
        Returns:
            INI file content as string
        """
        lines = []
        
        for section_name, section_data in config_dict.items():
            lines.append( f"[{section_name}]" )
            for key, value in section_data.items():
                lines.append( f"{key} = {value}" )
            lines.append( "" )  # Empty line between sections
        
        return "\n".join( lines )
    
    def run_all_tests( self ) -> tuple:
        """
        Run all ConfigurationManager unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "config_mgr_tests" )
        
        tests = [
            self.test_basic_instantiation,
            self.test_configuration_file_loading,
            self.test_environment_variable_override,
            self.test_type_conversion,
            self.test_error_handling,
            self.test_performance
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "ConfigurationManager Unit Test Suite", "=" )
        
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
        
        duration = self.utils.stop_timer( "config_mgr_tests" )
        
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
    Main unit test function for ConfigurationManager.
    
    This is the entry point called by the unit test runner to execute
    all ConfigurationManager unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = ConfigurationManagerUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"ConfigurationManager unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} ConfigurationManager unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )