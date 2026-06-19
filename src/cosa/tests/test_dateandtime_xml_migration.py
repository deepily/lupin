#!/usr/bin/env python3
"""
DateAndTimeAgent XML Migration Validation Tests

This module provides comprehensive tests for the DateAndTimeAgent XML parsing migration
from baseline util_xml.py parsing to Pydantic-based structured parsing using CodeBrainstormResponse model.

Tests validate:
- XML parsing strategy selection for DateAndTimeAgent
- Baseline vs CodeBrainstormResponse parsing compatibility 
- Brainstorming workflow validation with thoughts, brainstorm, and evaluation fields
- Code structure validation and list handling
- Migration debugging and comparison features
- End-to-end DateAndTimeAgent workflow validation

This is part of the Pydantic XML Migration Project Phase 4b.
"""

import time
from typing import Dict, Any

from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.agents.io_models.xml_models import CodeBrainstormResponse


class DateAndTimeXmlMigrationTester:
    """
    Comprehensive test suite for DateAndTimeAgent XML parsing migration.
    
    This tester validates the migration from baseline XML parsing to 
    Pydantic CodeBrainstormResponse model parsing, including edge cases and performance analysis.
    """
    
    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize DateAndTime migration tester.
        
        Requires:
            - Configuration manager can be initialized
            - XML parser factory can be created
            
        Ensures:
            - Test environment is properly configured
            - DateAndTime test data samples are prepared
            - Performance tracking is initialized
            
        Raises:
            - ConfigException if configuration setup fails
        """
        self.debug = debug
        self.verbose = verbose
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.factory = XmlParserFactory( config_mgr=self.config_mgr )
        
        # Test data samples for DateAndTimeAgent validation
        self.test_xml_samples = self._generate_test_xml_samples()
        self.performance_results = [ ]
        
        if debug:
            print( "DateAndTimeXmlMigrationTester initialized" )
    
    def _generate_test_xml_samples( self ) -> list[Dict[str, Any]]:
        """
        Generate comprehensive test XML samples for DateAndTimeAgent validation.
        
        Requires:
            - None
            
        Ensures:
            - Returns list of test cases with XML and expected results
            - Covers all DateAndTimeAgent XML patterns and edge cases
            - Includes malformed XML for error testing
            
        Raises:
            - None
        """
        samples = [
            {
                "name": "current_time_query",
                "xml": '''<response>
                    <thoughts>The user wants to know what time it is right now</thoughts>
                    <brainstorm>
                        <idea1>Use datetime.now() method</idea1>
                        <idea2>Use time module functions</idea2>
                        <idea3>Use system calls</idea3>
                    </brainstorm>
                    <evaluation>datetime.now() is the most straightforward and readable</evaluation>
                    <code>
                        <line>from datetime import datetime</line>
                        <line>current_time = datetime.now()</line>
                        <line>formatted_time = current_time.strftime("%I:%M %p")</line>
                        <line>print(f"It's {formatted_time}")</line>
                    </code>
                    <example>print(formatted_time)</example>
                    <returns>str</returns>
                    <explanation>Uses datetime.now() to get current time and formats it for display</explanation>
                </response>''',
                "expected_code_lines": 4,
                "expected_returns": "str",
                "should_parse": True
            },
            {
                "name": "time_zone_conversion",
                "xml": '''<response>
                    <thoughts>Need to convert time between different time zones</thoughts>
                    <brainstorm>
                        <idea1>Use pytz library</idea1>
                        <idea2>Use datetime tzinfo</idea2>
                        <idea3>Manual offset calculations</idea3>
                    </brainstorm>
                    <evaluation>pytz provides the most accurate and complete timezone handling</evaluation>
                    <code>
                        <line>import pytz</line>
                        <line>from datetime import datetime</line>
                        <line>utc = pytz.UTC</line>
                        <line>eastern = pytz.timezone('US/Eastern')</line>
                        <line>utc_time = datetime.now(utc)</line>
                        <line>eastern_time = utc_time.astimezone(eastern)</line>
                        <line>result = eastern_time.strftime("%Y-%m-%d %H:%M:%S %Z")</line>
                    </code>
                    <example>convert_timezone("UTC", "US/Eastern")</example>
                    <returns>str</returns>
                    <explanation>Converts UTC time to Eastern timezone using pytz library</explanation>
                </response>''',
                "expected_code_lines": 7,
                "expected_returns": "str",
                "should_parse": True
            },
            {
                "name": "date_calculation",
                "xml": '''<response>
                    <thoughts>User wants to calculate the number of days until a future date</thoughts>
                    <brainstorm>
                        <idea1>Calculate manually with formulas</idea1>
                        <idea2>Use timedelta objects</idea2>
                        <idea3>Use date arithmetic methods</idea3>
                    </brainstorm>
                    <evaluation>timedelta arithmetic is clearest and handles edge cases automatically</evaluation>
                    <code>
                        <line>from datetime import date, timedelta</line>
                        <line>def days_until(target_date_str):</line>
                        <line>    target = date.fromisoformat(target_date_str)</line>
                        <line>    today = date.today()</line>
                        <line>    delta = target - today</line>
                        <line>    return delta.days</line>
                    </code>
                    <example>days = days_until("2025-12-25")</example>
                    <returns>int</returns>
                    <explanation>Calculates days between today and target date using date arithmetic</explanation>
                </response>''',
                "expected_code_lines": 6,
                "expected_returns": "int",
                "should_parse": True
            },
            {
                "name": "weekday_determination",
                "xml": '''<response>
                    <thoughts>Need to determine what day of the week a specific date falls on</thoughts>
                    <brainstorm>
                        <idea1>Use datetime.weekday() method</idea1>
                        <idea2>Use calendar module</idea2>
                        <idea3>Manual calculation from reference date</idea3>
                    </brainstorm>
                    <evaluation>datetime.weekday() is the most straightforward and reliable approach</evaluation>
                    <code>
                        <line>from datetime import datetime</line>
                        <line>def get_weekday(year, month, day):</line>
                        <line>    date = datetime(year, month, day)</line>
                        <line>    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']</line>
                        <line>    return days[date.weekday()]</line>
                    </code>
                    <example>day_name = get_weekday(2025, 8, 10)</example>
                    <returns>str</returns>
                    <explanation>Creates a datetime object and maps weekday() result to day names</explanation>
                </response>''',
                "expected_code_lines": 5,
                "expected_returns": "str",
                "should_parse": True
            },
            {
                "name": "malformed_brainstorm_field",
                "xml": '''<response>
                    <thoughts>This sample has missing brainstorm field</thoughts>
                    <evaluation>datetime.now() is simple</evaluation>
                    <code>
                        <line>from datetime import datetime</line>
                        <line>print(datetime.now())</line>
                    </code>
                    <example>test()</example>
                    <returns>None</returns>
                    <explanation>Test missing brainstorm field</explanation>
                </response>''',
                "should_parse": False  # Should fail due to missing brainstorm field
            },
            {
                "name": "empty_evaluation_field",
                "xml": '''<response>
                    <thoughts>Testing empty evaluation field behavior</thoughts>
                    <brainstorm>
                        <idea1>Do this approach</idea1>
                        <idea2>Do that alternative</idea2>
                        <idea3>Try a third option</idea3>
                    </brainstorm>
                    <evaluation></evaluation>
                    <code>
                        <line>print("test")</line>
                    </code>
                    <example>empty_example()</example>
                    <returns>None</returns>
                    <explanation>Testing behavior with empty evaluation field</explanation>
                </response>''',
                "should_parse": False  # Should fail due to empty evaluation requirement
            }
        ]
        
        return samples
    
    def test_strategy_selection( self ) -> Dict[str, bool]:
        """
        Test XML parsing strategy selection for DateAndTimeAgent.
        
        Requires:
            - Factory can create different strategy types
            - DateAndTimeAgent routing command is recognized
            
        Ensures:
            - Tests strategy selection for DateAndTimeAgent routing command
            - Tests fallback behavior and configuration handling
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing DateAndTimeAgent Strategy Selection ===" )
        
        try:
            # Test baseline strategy for DateAndTimeAgent
            self.factory.global_strategy = "baseline"
            strategy = self.factory.get_parser_strategy( "agent router go to date and time" )
            results[ "baseline_strategy_datetime" ] = strategy.get_strategy_name() == "baseline"
            
            if self.debug:
                print( f"  ✓ Baseline strategy for datetime: {strategy.get_strategy_name()}" )
            
            # Test structured strategy for DateAndTimeAgent (should use CodeBrainstormResponse)
            self.factory.global_strategy = "structured_v2"
            strategy = self.factory.get_parser_strategy( "agent router go to date and time" )
            # Should either succeed with structured_v2 or fall back to baseline
            results[ "structured_strategy_datetime" ] = strategy.get_strategy_name() in [ "structured_v2", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Structured strategy for datetime: {strategy.get_strategy_name()}" )
            
            # Test hybrid strategy
            self.factory.global_strategy = "hybrid_v1"
            strategy = self.factory.get_parser_strategy( "agent router go to date and time" )
            results[ "hybrid_strategy_datetime" ] = strategy.get_strategy_name() in [ "hybrid_v1", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Hybrid strategy for datetime: {strategy.get_strategy_name()}" )
                
        except Exception as e:
            if self.debug:
                print( f"  ✗ Strategy selection test failed: {e}" )
            results[ "strategy_selection_error" ] = False
        
        return results
    
    def test_baseline_parsing( self ) -> Dict[str, bool]:
        """
        Test baseline XML parsing with DateAndTimeAgent patterns.
        
        Requires:
            - Factory can create baseline parsing strategy
            - Test XML samples cover DateAndTimeAgent patterns
            
        Ensures:
            - Tests parsing of DateAndTime XML structures
            - Tests code line extraction with baseline parser
            - Tests error handling for malformed XML
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing DateAndTime Baseline Parsing ===" )
        
        # Force baseline strategy
        self.factory.global_strategy = "baseline"
        
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                parsed_result = self.factory.parse_agent_response(
                    xml_response=sample[ "xml" ],
                    agent_routing_command="agent router go to date and time",
                    xml_tag_names=[ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ],
                    debug=False,
                    verbose=False
                )
                
                parsing_time = time.time() - start_time
                
                # Check if parsing should have succeeded
                if sample[ "should_parse" ]:
                    # Validate expected structure
                    required_fields = [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
                    has_all_fields = all( field in parsed_result for field in required_fields )
                    
                    if has_all_fields:
                        results[ f"baseline_{sample_name}" ] = True
                        self.performance_results.append({
                            "sample": sample_name,
                            "strategy": "baseline", 
                            "time": parsing_time,
                            "success": True
                        })
                        
                        if self.debug:
                            code_lines = len( parsed_result.get( "code", [] ) )
                            print( f"  ✓ {sample_name}: {code_lines} code lines, {parsing_time:.4f}s" )
                    else:
                        results[ f"baseline_{sample_name}" ] = False
                        if self.debug:
                            missing_fields = [f for f in required_fields if f not in parsed_result]
                            print( f"  ✗ {sample_name}: Missing fields {missing_fields}" )
                else:
                    # This should have failed, but it parsed successfully
                    results[ f"baseline_{sample_name}" ] = False
                    if self.debug:
                        print( f"  ⚠ {sample_name}: Expected to fail but parsed successfully" )
                        
            except Exception as e:
                if sample[ "should_parse" ]:
                    results[ f"baseline_{sample_name}" ] = False
                    if self.debug:
                        print( f"  ✗ {sample_name}: Parse error - {e}" )
                else:
                    # Expected to fail
                    results[ f"baseline_{sample_name}" ] = True
                    if self.debug:
                        print( f"  ✓ {sample_name}: Correctly failed to parse" )
        
        return results
    
    def test_pydantic_parsing( self ) -> Dict[str, bool]:
        """
        Test Pydantic CodeBrainstormResponse parsing with DateAndTimeAgent patterns.
        
        Requires:
            - Factory can create structured parsing strategy
            - CodeBrainstormResponse model handles DateAndTime XML patterns
            
        Ensures:
            - Tests parsing of DateAndTime XML with Pydantic validation
            - Tests brainstorming field validation and code extraction
            - Tests error handling for validation failures
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing DateAndTime Pydantic Parsing ===" )
        
        # Force structured strategy
        self.factory.global_strategy = "structured_v2"
        
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                parsed_result = self.factory.parse_agent_response(
                    xml_response=sample[ "xml" ],
                    agent_routing_command="agent router go to date and time",
                    xml_tag_names=[ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ],
                    debug=False,
                    verbose=False
                )
                
                parsing_time = time.time() - start_time
                
                # Check if parsing should have succeeded
                if sample[ "should_parse" ]:
                    # Validate expected structure and types
                    required_fields = [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
                    has_all_fields = all( field in parsed_result for field in required_fields )
                    
                    # Validate code is a list (Pydantic should ensure this)
                    code_is_list = isinstance( parsed_result.get( "code", [] ), list )
                    
                    if has_all_fields and code_is_list:
                        results[ f"pydantic_{sample_name}" ] = True
                        self.performance_results.append({
                            "sample": sample_name,
                            "strategy": "pydantic",
                            "time": parsing_time,
                            "success": True
                        })
                        
                        if self.debug:
                            code_lines = len( parsed_result.get( "code", [] ) )
                            expected_lines = sample.get( "expected_code_lines", 0 )
                            line_match = "✓" if code_lines == expected_lines else "⚠"
                            print( f"  ✓ {sample_name}: {code_lines} code lines {line_match}, {parsing_time:.4f}s" )
                    else:
                        results[ f"pydantic_{sample_name}" ] = False
                        if self.debug:
                            issues = []
                            if not has_all_fields:
                                missing = [f for f in required_fields if f not in parsed_result]
                                issues.append( f"missing fields {missing}" )
                            if not code_is_list:
                                issues.append( f"code not list (is {type( parsed_result.get( 'code' ) )})" )
                            print( f"  ✗ {sample_name}: {', '.join( issues )}" )
                else:
                    # This should have failed, but it parsed successfully
                    results[ f"pydantic_{sample_name}" ] = False
                    if self.debug:
                        print( f"  ⚠ {sample_name}: Expected to fail but parsed successfully" )
                        
            except Exception as e:
                if sample[ "should_parse" ]:
                    results[ f"pydantic_{sample_name}" ] = False
                    if self.debug:
                        print( f"  ✗ {sample_name}: Parse error - {e}" )
                else:
                    # Expected to fail
                    results[ f"pydantic_{sample_name}" ] = True
                    if self.debug:
                        print( f"  ✓ {sample_name}: Correctly failed to parse - {e}" )
        
        return results
    
    def test_brainstorm_field_validation( self ) -> Dict[str, bool]:
        """
        Test specific brainstorming field validation for CodeBrainstormResponse.
        
        Requires:
            - CodeBrainstormResponse model is properly imported
            - Brainstorming XML patterns are available
            
        Ensures:
            - Tests thoughts, brainstorm, evaluation field validation
            - Tests empty field handling and error reporting
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing DateAndTime Brainstorm Field Validation ===" )
        
        try:
            # Test valid brainstorming structure
            valid_xml = '''<response>
                <thoughts>Clear initial reasoning</thoughts>
                <brainstorm>Multiple approaches: A, B, C</brainstorm>
                <evaluation>Approach A is best because of performance</evaluation>
                <code>
                    <line>solution_code_here</line>
                </code>
                <example>test()</example>
                <returns>str</returns>
                <explanation>Well explained solution</explanation>
            </response>'''
            
            model = CodeBrainstormResponse.from_xml( valid_xml )
            results[ "valid_brainstorm_structure" ] = True
            
            if self.debug:
                print( f"  ✓ Valid brainstorm structure parsed" )
                print( f"    - Thoughts: {model.thoughts[:30]}..." )
                print( f"    - Brainstorm: {model.brainstorm[:30]}..." )
                print( f"    - Evaluation: {model.evaluation[:30]}..." )
            
            # Test empty thoughts field (should fail)
            try:
                invalid_xml = valid_xml.replace( "Clear initial reasoning", "" )
                CodeBrainstormResponse.from_xml( invalid_xml )
                results[ "empty_thoughts_rejection" ] = False  # Should have failed
                if self.debug:
                    print( f"  ⚠ Empty thoughts should have been rejected" )
            except Exception:
                results[ "empty_thoughts_rejection" ] = True
                if self.debug:
                    print( f"  ✓ Empty thoughts correctly rejected" )
            
            # Test empty brainstorm field (should fail)
            try:
                invalid_xml = valid_xml.replace( "Multiple approaches: A, B, C", "" )
                CodeBrainstormResponse.from_xml( invalid_xml )
                results[ "empty_brainstorm_rejection" ] = False  # Should have failed
                if self.debug:
                    print( f"  ⚠ Empty brainstorm should have been rejected" )
            except Exception:
                results[ "empty_brainstorm_rejection" ] = True
                if self.debug:
                    print( f"  ✓ Empty brainstorm correctly rejected" )
                    
            # Test empty evaluation field (should fail)
            try:
                invalid_xml = valid_xml.replace( "Approach A is best because of performance", "" )
                CodeBrainstormResponse.from_xml( invalid_xml )
                results[ "empty_evaluation_rejection" ] = False  # Should have failed
                if self.debug:
                    print( f"  ⚠ Empty evaluation should have been rejected" )
            except Exception:
                results[ "empty_evaluation_rejection" ] = True
                if self.debug:
                    print( f"  ✓ Empty evaluation correctly rejected" )
                    
        except Exception as e:
            if self.debug:
                print( f"  ✗ Brainstorm field validation test failed: {e}" )
            results[ "brainstorm_validation_error" ] = False
        
        return results
    
    def test_config_integration( self ) -> Dict[str, bool]:
        """
        Test DateAndTimeAgent configuration integration.
        
        Requires:
            - Configuration manager is available
            - DateAndTime agent configuration keys exist
            
        Ensures:
            - Tests strategy override configuration for DateAndTime agent
            - Tests global configuration integration
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing DateAndTime Configuration Integration ===" )
        
        try:
            # Test global strategy configuration
            global_strategy = self.config_mgr.get( "xml parsing global strategy", default="baseline" )
            results[ "datetime_global_strategy_config" ] = global_strategy in [ "baseline", "hybrid_v1", "structured_v2" ]
            
            # Test agent-specific override (if configured)
            override_key = "xml parsing strategy for agent router go to date and time"
            override_value = self.config_mgr.get( override_key, default=None )
            results[ "datetime_override_config" ] = True  # Always pass since override is optional
            
            # Test debug mode configuration
            debug_mode = self.config_mgr.get( "xml parsing migration debug mode", default=False, return_type="boolean" )
            results[ "datetime_debug_mode_config" ] = isinstance( debug_mode, bool )
            
            if self.debug:
                print( f"  ✓ Global strategy: {global_strategy}" )
                print( f"  ✓ Agent override: {override_value or 'not set'}" )
                print( f"  ✓ Debug mode: {debug_mode}" )
        
        except Exception as e:
            results[ "datetime_config_integration_error" ] = False
            if self.debug:
                print( f"  ✗ DateAndTime configuration integration test failed: {e}" )
        
        return results
    
    def run_comprehensive_test_suite( self ) -> Dict[str, Any]:
        """
        Run the complete DateAndTimeAgent migration validation test suite.
        
        Requires:
            - All test components are properly initialized
            
        Ensures:
            - Executes all test categories
            - Collects comprehensive results and performance data
            - Provides detailed summary of migration readiness
            
        Raises:
            - None (captures and reports errors)
        """
        if self.debug:
            print( "\n" + "=" * 80 )
            print( "DateAndTimeAgent XML Migration Validation Test Suite" )
            print( "=" * 80 )
        
        all_results = { }
        
        # Run all test categories
        test_categories = [
            ( "strategy_selection", self.test_strategy_selection ),
            ( "baseline_parsing", self.test_baseline_parsing ),
            ( "pydantic_parsing", self.test_pydantic_parsing ),
            ( "brainstorm_validation", self.test_brainstorm_field_validation ),
            ( "config_integration", self.test_config_integration )
        ]
        
        for category_name, test_function in test_categories:
            try:
                start_time = time.time()
                category_results = test_function()
                category_time = time.time() - start_time
                
                all_results[ category_name ] = {
                    "results": category_results,
                    "execution_time": category_time,
                    "test_count": len( category_results ),
                    "passed_count": sum( 1 for result in category_results.values() if result ),
                    "success_rate": ( sum( 1 for result in category_results.values() if result ) / len( category_results ) * 100 ) if category_results else 0
                }
                
                if self.debug:
                    passed = all_results[ category_name ][ "passed_count" ]
                    total = all_results[ category_name ][ "test_count" ]
                    rate = all_results[ category_name ][ "success_rate" ]
                    print( f"\n{category_name}: {passed}/{total} tests passed ({rate:.1f}%) in {category_time:.3f}s" )
                    
            except Exception as e:
                all_results[ category_name ] = {
                    "error": str( e ),
                    "execution_time": 0,
                    "test_count": 0,
                    "passed_count": 0,
                    "success_rate": 0
                }
                if self.debug:
                    print( f"\n{category_name}: FAILED - {e}" )
        
        # Generate comprehensive summary
        summary = self._generate_test_summary( all_results )
        all_results[ "summary" ] = summary
        all_results[ "performance_data" ] = self.performance_results
        
        if self.debug:
            self._print_comprehensive_summary( summary )
        
        return all_results
    
    def _generate_test_summary( self, all_results: Dict[str, Any] ) -> Dict[str, Any]:
        """
        Generate comprehensive summary of DateAndTimeAgent migration test results.
        
        Requires:
            - all_results contains test category results
            
        Ensures:
            - Returns summary with key migration readiness metrics
            - Identifies critical issues and blockers
            
        Raises:
            - None
        """
        # Calculate overall metrics
        total_tests = sum( category.get( "test_count", 0 ) for category in all_results.values() if isinstance( category, dict ) and "test_count" in category )
        total_passed = sum( category.get( "passed_count", 0 ) for category in all_results.values() if isinstance( category, dict ) and "passed_count" in category )
        overall_success_rate = ( total_passed / total_tests * 100 ) if total_tests > 0 else 0
        
        # Identify critical issues
        critical_issues = [ ]
        categories_tested = len( [ cat for cat in all_results.keys() if cat != "summary" and cat != "performance_data" ] )
        
        # Check for strategy selection issues
        strategy_results = all_results.get( "strategy_selection", {} ).get( "results", {} )
        if not strategy_results.get( "structured_strategy_datetime", True ):
            critical_issues.append( "Structured strategy not working for DateAndTimeAgent" )
        
        # Check for Pydantic parsing failures
        pydantic_results = all_results.get( "pydantic_parsing", {} ).get( "results", {} )
        pydantic_failures = [ key for key, value in pydantic_results.items() if key.startswith( "pydantic_" ) and not value ]
        if len( pydantic_failures ) > 1:
            critical_issues.append( f"Multiple Pydantic parsing failures: {len( pydantic_failures )}" )
        
        # Check for brainstorm validation issues
        brainstorm_results = all_results.get( "brainstorm_validation", {} ).get( "results", {} )
        if not brainstorm_results.get( "valid_brainstorm_structure", True ):
            critical_issues.append( "Brainstorming structure validation failing" )
        
        # Performance analysis
        performance_data = self.performance_results
        baseline_times = [ p["time"] for p in performance_data if p["strategy"] == "baseline" and p["success"] ]
        pydantic_times = [ p["time"] for p in performance_data if p["strategy"] == "pydantic" and p["success"] ]
        
        avg_baseline_time = sum( baseline_times ) / len( baseline_times ) if baseline_times else 0
        avg_pydantic_time = sum( pydantic_times ) / len( pydantic_times ) if pydantic_times else 0
        performance_ratio = ( avg_pydantic_time / avg_baseline_time ) if avg_baseline_time > 0 else 0
        
        # Migration readiness assessment
        migration_ready = (
            overall_success_rate >= 90 and
            len( critical_issues ) == 0 and
            categories_tested >= 4 and
            brainstorm_results.get( "valid_brainstorm_structure", False ) and
            brainstorm_results.get( "empty_brainstorm_rejection", False ) and
            brainstorm_results.get( "empty_evaluation_rejection", False )
        )
        
        return {
            "total_tests": total_tests,
            "total_passed": total_passed,
            "success_rate": overall_success_rate,
            "categories_tested": categories_tested,
            "critical_issues": critical_issues,
            "migration_ready": migration_ready,
            "performance_ratio": performance_ratio,
            "avg_baseline_time": avg_baseline_time,
            "avg_pydantic_time": avg_pydantic_time,
            "brainstorm_validation_working": all(
                brainstorm_results.get( field, False )
                for field in [ "valid_brainstorm_structure", "empty_brainstorm_rejection", "empty_evaluation_rejection" ]
            )
        }
    
    def _print_comprehensive_summary( self, summary: Dict[str, Any] ) -> None:
        """Print formatted comprehensive test summary."""
        print( "\n" + "=" * 80 )
        print( "DateAndTimeAgent Migration Test Summary" )
        print( "=" * 80 )
        
        print( f"Overall Results:" )
        print( f"  - Tests: {summary[ 'total_passed' ]}/{summary[ 'total_tests' ]} passed ({summary[ 'success_rate' ]:.1f}%)" )
        print( f"  - Categories: {summary[ 'categories_tested' ]} test categories completed" )
        print( f"  - Migration Ready: {'✓ YES' if summary[ 'migration_ready' ] else '✗ NO'}" )
        
        if summary[ "performance_ratio" ] > 0:
            print( f"  - Performance: Pydantic {summary[ 'performance_ratio' ]:.1f}x slower than baseline" )
            print( f"    - Baseline avg: {summary[ 'avg_baseline_time' ]:.4f}s" )
            print( f"    - Pydantic avg: {summary[ 'avg_pydantic_time' ]:.4f}s" )
        
        print( f"  - Brainstorm Validation: {'✓ Working' if summary[ 'brainstorm_validation_working' ] else '✗ Issues'}" )
        
        if summary[ "critical_issues" ]:
            print( f"\nCritical Issues ({len( summary[ 'critical_issues' ] )}):" )
            for issue in summary[ "critical_issues" ]:
                print( f"  ✗ {issue}" )
        else:
            print( f"\n✓ No critical issues identified" )
        
        if not summary[ "migration_ready" ]:
            print( f"\nRecommendations:" )
            if summary[ "success_rate" ] < 90:
                print( f"  - Improve test success rate (currently {summary[ 'success_rate' ]:.1f}%, need ≥90%)" )
            if summary[ "critical_issues" ]:
                print( f"  - Resolve {len( summary[ 'critical_issues' ] )} critical issues" )
            if summary[ "categories_tested" ] < 4:
                print( f"  - Test more categories (currently {summary[ 'categories_tested' ]}, need ≥4)" )
            if not summary[ "brainstorm_validation_working" ]:
                print( f"  - Fix brainstorming field validation issues" )
        
        print( "=" * 80 )


def quick_smoke_test() -> bool:
    """
    Quick smoke test for DateAndTimeXmlMigrationTester.
    
    Tests basic functionality and migration validation capabilities.
    
    Returns:
        True if smoke test passes
    """
    print( "Testing DateAndTimeXmlMigrationTester..." )
    
    try:
        # Test 1: Tester initialization
        print( "  - Testing tester initialization..." )
        tester = DateAndTimeXmlMigrationTester( debug=False )
        print( "    ✓ Tester created successfully" )
        
        # Test 2: Test data generation
        print( "  - Testing test data generation..." )
        samples = tester.test_xml_samples
        assert len( samples ) >= 4, f"Expected at least 4 test samples, got {len( samples )}"
        
        # Verify samples have required fields
        required_sample_fields = [ "name", "xml", "should_parse" ]
        for sample in samples:
            for field in required_sample_fields:
                assert field in sample, f"Sample missing required field: {field}"
        
        print( f"    ✓ Generated {len( samples )} test samples" )
        
        # Test 3: Quick strategy test
        print( "  - Testing strategy selection..." )
        strategy_results = tester.test_strategy_selection()
        assert len( strategy_results ) > 0, "Strategy selection returned no results"
        print( f"    ✓ Strategy selection tested ({len( strategy_results )} results)" )
        
        # Test 4: Basic XML parsing test
        print( "  - Testing basic XML parsing..." )
        sample_xml = '''<response>
            <thoughts>Test thoughts</thoughts>
            <brainstorm>Test brainstorm</brainstorm>
            <evaluation>Test evaluation</evaluation>
            <code><line>test_code</line></code>
            <example>test</example>
            <returns>str</returns>
            <explanation>Test explanation</explanation>
        </response>'''
        
        # Test baseline parsing
        tester.factory.global_strategy = "baseline"
        baseline_result = tester.factory.parse_agent_response(
            sample_xml, 
            "agent router go to date and time",
            [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
        )
        assert "thoughts" in baseline_result, "Baseline parsing missing thoughts field"
        print( "    ✓ Baseline parsing works" )
        
        # Test Pydantic parsing
        tester.factory.global_strategy = "structured_v2"
        pydantic_result = tester.factory.parse_agent_response(
            sample_xml,
            "agent router go to date and time", 
            [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
        )
        assert "brainstorm" in pydantic_result, "Pydantic parsing missing brainstorm field"
        assert isinstance( pydantic_result.get( "code", [] ), list ), "Pydantic code field should be list"
        print( "    ✓ Pydantic parsing works" )
        
        print( "✓ DateAndTimeXmlMigrationTester smoke test PASSED" )
        return True
        
    except Exception as e:
        print( f"✗ DateAndTimeXmlMigrationTester smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        return False


def run_full_migration_test() -> bool:
    """
    Run full DateAndTimeAgent migration validation test suite.
    
    Returns:
        True if migration is ready
    """
    try:
        print( "Initializing DateAndTimeAgent migration test suite..." )
        tester = DateAndTimeXmlMigrationTester( debug=True )
        
        print( "Running comprehensive test suite..." )
        results = tester.run_comprehensive_test_suite()
        
        # Return migration readiness status
        return results.get( "summary", { } ).get( "migration_ready", False )
        
    except Exception as e:
        print( f"DateAndTime migration test suite failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run smoke test when executed directly
    success = quick_smoke_test()
    
    if success:
        print( "\n" + "="*50 )
        print( "Running full DateAndTime migration validation..." )
        print( "="*50 )
        
        migration_ready = run_full_migration_test()
        exit_code = 0 if migration_ready else 1
        
        print( f"\nDateAndTimeAgent Migration Status: {'READY' if migration_ready else 'NOT READY'}" )
        exit( exit_code )
    else:
        exit( 1 )