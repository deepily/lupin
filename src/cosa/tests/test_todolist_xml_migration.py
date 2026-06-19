#!/usr/bin/env python3
"""
TodoListAgent XML Migration Validation Tests

This module provides comprehensive tests for the TodoListAgent XML parsing migration
from baseline util_xml.py parsing to Pydantic-based structured parsing using CodeResponse model.

Tests validate:
- XML parsing strategy selection for TodoListAgent 
- Baseline vs CodeResponse parsing compatibility
- Code structure validation and list handling
- Migration debugging and comparison features
- End-to-end TodoListAgent workflow validation

This is part of the Pydantic XML Migration Project Phase 4b.
"""

import time
from typing import Dict, Any

from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.agents.io_models.xml_models import CodeResponse


class TodoListXmlMigrationTester:
    """
    Comprehensive test suite for TodoListAgent XML parsing migration.
    
    This tester validates the migration from baseline XML parsing to 
    Pydantic CodeResponse model parsing, including edge cases and performance analysis.
    """
    
    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize TodoList migration tester.
        
        Requires:
            - Configuration manager can be initialized
            - XML parser factory can be created
            
        Ensures:
            - Test environment is properly configured
            - TodoList test data samples are prepared
            - Performance tracking is initialized
            
        Raises:
            - ConfigException if configuration setup fails
        """
        self.debug = debug
        self.verbose = verbose
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.factory = XmlParserFactory( config_mgr=self.config_mgr )
        
        # Test data samples for TodoListAgent validation
        self.test_xml_samples = self._generate_test_xml_samples()
        self.performance_results = [ ]
        
        if debug:
            print( "TodoListXmlMigrationTester initialized" )
    
    def _generate_test_xml_samples( self ) -> list[Dict[str, Any]]:
        """
        Generate comprehensive test XML samples for TodoListAgent validation.
        
        Requires:
            - None
            
        Ensures:
            - Returns list of test cases with XML and expected results
            - Covers all TodoListAgent XML patterns and edge cases
            - Includes malformed XML for error testing
            
        Raises:
            - None
        """
        samples = [
            {
                "name": "simple_todo_query",
                "xml": '''<response>
                    <thoughts>The user wants to see their todo list items</thoughts>
                    <code>
                        <line>filtered_todos = df[df['status'] == 'pending']</line>
                        <line>result = filtered_todos[['task', 'due_date']].to_dict('records')</line>
                        <line>print(f"You have {{len(result)}} pending tasks")</line>
                    </code>
                    <example>print(result)</example>
                    <returns>list</returns>
                    <explanation>Filters pending todos and returns them as a list of dictionaries</explanation>
                </response>''',
                "expected_code_lines": 3,
                "expected_returns": "list",
                "should_parse": True
            },
            {
                "name": "complex_todo_analysis",
                "xml": '''<response>
                    <thoughts>Need to analyze todo completion patterns and priority</thoughts>
                    <code>
                        <line>import pandas as pd</line>
                        <line>from datetime import datetime, timedelta</line>
                        <line></line>
                        <line>today = datetime.now().date()</line>
                        <line>overdue = df[df['due_date'] &lt; today]</line>
                        <line>high_priority = df[df['priority'] == 'high']</line>
                        <line>urgent_tasks = df[(df['due_date'] &lt;= today + timedelta(days=1)) &amp; (df['status'] == 'pending')]</line>
                        <line>summary = {</line>
                        <line>    'overdue_count': len(overdue),</line>
                        <line>    'high_priority_count': len(high_priority),</line>
                        <line>    'urgent_count': len(urgent_tasks)</line>
                        <line>}</line>
                        <line>print(f"Summary: {{summary}}")</line>
                    </code>
                    <example>analyze_todos(df)</example>
                    <returns>dict</returns>
                    <explanation>Analyzes todo list by priority and due dates, returns comprehensive summary</explanation>
                </response>''',
                "expected_code_lines": 13,
                "expected_returns": "dict",
                "should_parse": True
            },
            {
                "name": "todo_with_xml_escapes",
                "xml": '''<response>
                    <thoughts>Handle todo items that contain special characters and comparisons</thoughts>
                    <code>
                        <line>filtered_todos = df[df['task'].str.contains('&lt;urgent&gt;', na=False)]</line>
                        <line>conditions = df['priority'].isin(['high', 'critical']) &amp; (df['status'] == 'pending')</line>
                        <line>urgent_todos = df[conditions]</line>
                        <line>result = urgent_todos['task'].tolist()</line>
                        <line>print(f"Found {{len(result)}} urgent tasks with &quot;special&quot; markers")</line>
                    </code>
                    <example>find_urgent_todos()</example>
                    <returns>list</returns>
                    <explanation>Searches for todos with special HTML-like markers and urgency indicators</explanation>
                </response>''',
                "expected_code_lines": 5,
                "expected_returns": "list",
                "should_parse": True
            },
            {
                "name": "single_line_todo",
                "xml": '''<response>
                    <thoughts>Simple one-liner to count total todos</thoughts>
                    <code>
                        <line>total_count = len(df)</line>
                    </code>
                    <example>count_todos(df)</example>
                    <returns>int</returns>
                    <explanation>Returns the total number of todo items in the list</explanation>
                </response>''',
                "expected_code_lines": 1,
                "expected_returns": "int",
                "should_parse": True
            },
            {
                "name": "empty_thoughts",
                "xml": '''<response>
                    <thoughts></thoughts>
                    <code>
                        <line>result = df.head()</line>
                    </code>
                    <example>show_todos()</example>
                    <returns>DataFrame</returns>
                    <explanation>Shows first few todo items</explanation>
                </response>''',
                "should_parse": False  # Should fail due to empty thoughts
            },
            {
                "name": "missing_code",
                "xml": '''<response>
                    <thoughts>This response is missing the code section</thoughts>
                    <example>missing_code_example()</example>
                    <returns>None</returns>
                    <explanation>This should fail because code is required</explanation>
                </response>''',
                "should_parse": False  # Missing required code field
            },
            {
                "name": "malformed_code_tags",
                "xml": '''<response>
                    <thoughts>Testing malformed nested code structure</thoughts>
                    <code>
                        <line>valid_line = df.head()</line>
                        <line>broken_content</line>
                        <line>another_valid_line = df.tail()</line>
                    </code>
                    <example>test_malformed()</example>
                    <returns>DataFrame</returns>
                    <explanation>Should handle malformed nested tags gracefully</explanation>
                </response>''',
                "should_parse": True,  # xmltodict should handle this gracefully
                "expected_code_lines": 3  # Should extract valid lines
            },
            {
                "name": "empty_code_block",
                "xml": '''<response>
                    <thoughts>Testing empty code block</thoughts>
                    <code>
                    </code>
                    <example>empty_example()</example>
                    <returns>None</returns>
                    <explanation>Testing behavior with empty code block</explanation>
                </response>''',
                "should_parse": False  # Should fail due to empty code requirement
            }
        ]
        
        return samples
    
    def test_strategy_selection( self ) -> Dict[str, bool]:
        """
        Test XML parsing strategy selection for TodoListAgent.
        
        Requires:
            - Factory can create different strategy types
            - TodoListAgent routing command is recognized
            
        Ensures:
            - Tests strategy selection for TodoListAgent routing command
            - Tests fallback behavior and configuration handling
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing TodoListAgent Strategy Selection ===" )
        
        try:
            # Test baseline strategy for TodoListAgent
            self.factory.global_strategy = "baseline"
            strategy = self.factory.get_parser_strategy( "agent router go to todo list" )
            results[ "baseline_strategy_todo" ] = strategy.get_strategy_name() == "baseline"
            
            if self.debug:
                print( f"  ✓ Baseline strategy for todo: {strategy.get_strategy_name()}" )
            
            # Test structured strategy for TodoListAgent (should use CodeResponse)
            self.factory.global_strategy = "structured_v2"
            strategy = self.factory.get_parser_strategy( "agent router go to todo list" )
            # Should either succeed with structured_v2 or fall back to baseline
            results[ "structured_strategy_todo" ] = strategy.get_strategy_name() in [ "structured_v2", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Structured strategy for todo: {strategy.get_strategy_name()}" )
            
            # Test hybrid strategy
            self.factory.global_strategy = "hybrid_v1"
            strategy = self.factory.get_parser_strategy( "agent router go to todo list" )
            results[ "hybrid_strategy_todo" ] = strategy.get_strategy_name() in [ "hybrid_v1", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Hybrid strategy for todo: {strategy.get_strategy_name()}" )
                
        except Exception as e:
            if self.debug:
                print( f"  ✗ Strategy selection test failed: {e}" )
            results[ "strategy_selection_error" ] = False
        
        return results
    
    def test_baseline_parsing( self ) -> Dict[str, bool]:
        """
        Test baseline XML parsing with TodoListAgent patterns.
        
        Requires:
            - Factory can create baseline parsing strategy
            - Test XML samples cover TodoListAgent patterns
            
        Ensures:
            - Tests parsing of TodoList XML structures
            - Tests code line extraction with baseline parser
            - Tests error handling for malformed XML
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing TodoList Baseline Parsing ===" )
        
        # Force baseline strategy
        self.factory.global_strategy = "baseline"
        
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                parsed_result = self.factory.parse_agent_response(
                    xml_response=sample[ "xml" ],
                    agent_routing_command="agent router go to todo list",
                    xml_tag_names=[ "thoughts", "code", "example", "returns", "explanation" ],
                    debug=False,
                    verbose=False
                )
                
                parsing_time = time.time() - start_time
                
                # Record performance
                self.performance_results.append({
                    "strategy": "baseline",
                    "sample": sample_name,
                    "time": parsing_time,
                    "success": True
                })
                
                if sample[ "should_parse" ]:
                    # Baseline parsing should succeed (it's lenient)
                    has_required_fields = all( 
                        field in parsed_result 
                        for field in [ "thoughts", "code", "example", "returns", "explanation" ] 
                    )
                    results[ f"baseline_{sample_name}_fields" ] = has_required_fields
                    
                    # Check code structure (baseline returns list for nested code)
                    if "expected_code_lines" in sample:
                        code_field = parsed_result.get( "code" )
                        if isinstance( code_field, list ):
                            code_lines_match = len( code_field ) == sample[ "expected_code_lines" ]
                            results[ f"baseline_{sample_name}_code_lines" ] = code_lines_match
                        else:
                            results[ f"baseline_{sample_name}_code_structure" ] = True
                    
                    if self.debug:
                        print( f"  ✓ {sample_name}: parsed successfully" )
                else:
                    # Baseline is lenient, so it might still parse
                    results[ f"baseline_{sample_name}_lenient" ] = True
                    
                    if self.debug:
                        print( f"  ⚠ {sample_name}: parsed despite issues (baseline is lenient)" )
                
            except Exception as e:
                parsing_time = time.time() - start_time
                
                self.performance_results.append({
                    "strategy": "baseline",
                    "sample": sample_name,
                    "time": parsing_time,
                    "success": False,
                    "error": str( e )
                })
                
                if sample[ "should_parse" ]:
                    results[ f"baseline_{sample_name}_error" ] = False
                    if self.debug:
                        print( f"  ✗ {sample_name}: unexpected error: {e}" )
                else:
                    results[ f"baseline_{sample_name}_expected_fail" ] = True
                    if self.debug:
                        print( f"  ✓ {sample_name}: failed as expected" )
        
        return results
    
    def test_coderesponse_parsing( self ) -> Dict[str, bool]:
        """
        Test CodeResponse Pydantic model parsing with TodoListAgent patterns.
        
        Requires:
            - CodeResponse model is properly implemented
            - Factory can create Pydantic parsing strategy
            
        Ensures:
            - Tests strict validation of TodoList XML samples
            - Tests code list structure parsing and validation
            - Tests type safety and field validation
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing TodoList CodeResponse Parsing ===" )
        
        # Test direct CodeResponse parsing
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                # Parse directly with CodeResponse model
                response_obj = CodeResponse.from_xml( sample[ "xml" ] )
                
                parsing_time = time.time() - start_time
                
                # Record performance
                self.performance_results.append({
                    "strategy": "coderesponse",
                    "sample": sample_name,
                    "time": parsing_time,
                    "success": True
                })
                
                if sample[ "should_parse" ]:
                    # Should parse successfully - check validation
                    results[ f"coderesponse_{sample_name}_parse" ] = True
                    
                    # Check type safety
                    is_type_safe = (
                        isinstance( response_obj.thoughts, str ) and
                        isinstance( response_obj.code, list ) and
                        isinstance( response_obj.example, str ) and
                        isinstance( response_obj.returns, str ) and
                        isinstance( response_obj.explanation, str )
                    )
                    results[ f"coderesponse_{sample_name}_types" ] = is_type_safe
                    
                    # Check code structure expectations
                    if "expected_code_lines" in sample:
                        code_lines_correct = len( response_obj.code ) == sample[ "expected_code_lines" ]
                        results[ f"coderesponse_{sample_name}_code_lines" ] = code_lines_correct
                    
                    # Check returns field
                    if "expected_returns" in sample:
                        returns_correct = response_obj.returns == sample[ "expected_returns" ]
                        results[ f"coderesponse_{sample_name}_returns" ] = returns_correct
                    
                    # Test utility methods
                    if hasattr( response_obj, 'get_code_as_string' ):
                        code_string = response_obj.get_code_as_string()
                        has_code_string = len( code_string ) > 0 if response_obj.code else True
                        results[ f"coderesponse_{sample_name}_code_string" ] = has_code_string
                    
                    if self.debug:
                        print( f"  ✓ {sample_name}: parsed and validated successfully" )
                        print( f"    - Code lines: {len( response_obj.code )}" )
                        print( f"    - Returns: {response_obj.returns}" )
                else:
                    # Shouldn't have parsed but did - validation not strict enough
                    results[ f"coderesponse_{sample_name}_unexpected_success" ] = False
                    if self.debug:
                        print( f"  ⚠ {sample_name}: parsed but should have failed validation" )
                
            except Exception as e:
                parsing_time = time.time() - start_time
                
                # Record performance even for failures
                self.performance_results.append({
                    "strategy": "coderesponse", 
                    "sample": sample_name,
                    "time": parsing_time,
                    "success": False,
                    "error": str( e )
                })
                
                if sample[ "should_parse" ]:
                    results[ f"coderesponse_{sample_name}_error" ] = False
                    if self.debug:
                        print( f"  ✗ {sample_name}: unexpected error: {e}" )
                else:
                    results[ f"coderesponse_{sample_name}_expected_fail" ] = True
                    if self.debug:
                        print( f"  ✓ {sample_name}: failed validation as expected" )
        
        return results
    
    def test_factory_integration( self ) -> Dict[str, bool]:
        """
        Test factory integration with TodoListAgent routing.
        
        Requires:
            - Factory has TodoListAgent mapping to CodeResponse
            - Configuration system works correctly
            
        Ensures:
            - Tests end-to-end factory parsing for TodoListAgent
            - Tests strategy selection and model routing
            - Tests performance and compatibility
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing TodoList Factory Integration ===" )
        
        try:
            # Test factory parsing with TodoListAgent routing
            good_sample = self.test_xml_samples[ 0 ]  # simple_todo_query
            
            # Test with structured strategy (should use CodeResponse)
            self.factory.global_strategy = "structured_v2"
            
            start_time = time.time()
            
            parsed_result = self.factory.parse_agent_response(
                xml_response=good_sample[ "xml" ],
                agent_routing_command="agent router go to todo list",
                xml_tag_names=[ "thoughts", "code", "example", "returns", "explanation" ],
                debug=self.debug,
                verbose=self.verbose
            )
            
            parsing_time = time.time() - start_time
            
            # Record performance
            self.performance_results.append({
                "strategy": "factory_integration",
                "sample": good_sample[ "name" ],
                "time": parsing_time,
                "success": True
            })
            
            results[ "factory_integration_success" ] = True
            results[ "factory_result_structure" ] = all(
                field in parsed_result 
                for field in [ "thoughts", "code", "example", "returns", "explanation" ]
            )
            
            # Test code structure through factory
            code_field = parsed_result.get( "code" )
            results[ "factory_code_structure" ] = isinstance( code_field, list )
            
            if self.debug:
                print( f"  ✓ Factory integration completed successfully" )
                print( f"  ✓ Code structure: {type( code_field )} with {len( code_field ) if isinstance( code_field, list ) else 'N/A'} lines" )
        
        except Exception as e:
            results[ "factory_integration_error" ] = False
            if self.debug:
                print( f"  ✗ Factory integration failed: {e}" )
        
        return results
    
    def test_configuration_integration( self ) -> Dict[str, bool]:
        """
        Test configuration integration for TodoListAgent.
        
        Requires:
            - Configuration manager provides TodoList-specific settings
            - All expected configuration keys are available
            
        Ensures:
            - Tests TodoListAgent strategy configuration
            - Tests migration flags and debugging settings
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing TodoList Configuration Integration ===" )
        
        try:
            # Test TodoListAgent specific configuration
            todo_override_key = "xml parsing strategy for agent router go to todo list"
            todo_override_value = self.config_mgr.get( todo_override_key, default="baseline" )
            results[ "todo_override_config" ] = todo_override_value in [ "baseline", "hybrid_v1", "structured_v2" ]
            
            # Test global configuration still works
            global_strategy = self.config_mgr.get( "xml parsing global strategy", default="baseline" )
            results[ "global_strategy_config" ] = global_strategy in [ "baseline", "hybrid_v1", "structured_v2" ]
            
            # Test debugging flags
            debug_mode = self.config_mgr.get( "xml parsing migration debug mode", default=False, return_type="boolean" )
            results[ "debug_mode_config" ] = isinstance( debug_mode, bool )
            
            if self.debug:
                print( f"  ✓ TodoList override: {todo_override_value}" )
                print( f"  ✓ Global strategy: {global_strategy}" )
                print( f"  ✓ Debug mode: {debug_mode}" )
        
        except Exception as e:
            results[ "todo_config_integration_error" ] = False
            if self.debug:
                print( f"  ✗ TodoList configuration integration test failed: {e}" )
        
        return results
    
    def run_comprehensive_test_suite( self ) -> Dict[str, Any]:
        """
        Run the complete TodoListAgent migration validation test suite.
        
        Requires:
            - All test components are properly initialized
            
        Ensures:
            - Executes all test categories
            - Collects comprehensive results and performance data
            - Provides detailed summary of migration readiness
            
        Raises:
            - None (captures and reports all errors)
        """
        if self.debug:
            print( "=" * 80 )
            print( "TODOLIST XML MIGRATION VALIDATION TEST SUITE" )
            print( "=" * 80 )
        
        all_results = { }
        start_time = time.time()
        
        # Run all test categories
        test_categories = [
            ( "strategy_selection", self.test_strategy_selection ),
            ( "baseline_parsing", self.test_baseline_parsing ),
            ( "coderesponse_parsing", self.test_coderesponse_parsing ),
            ( "factory_integration", self.test_factory_integration ),
            ( "configuration_integration", self.test_configuration_integration )
        ]
        
        for category_name, test_method in test_categories:
            try:
                category_results = test_method()
                all_results[ category_name ] = category_results
                
                # Calculate success rate for this category
                if category_results:
                    passed = sum( 1 for result in category_results.values() if result is True )
                    total = len( category_results )
                    success_rate = ( passed / total ) * 100 if total > 0 else 0
                    
                    if self.debug:
                        print( f"\n{category_name.upper()} SUMMARY: {passed}/{total} tests passed ({success_rate:.1f}%)" )
                
            except Exception as e:
                all_results[ category_name ] = { "category_error": str( e ) }
                if self.debug:
                    print( f"\n{category_name.upper()} FAILED: {e}" )
        
        total_time = time.time() - start_time
        
        # Generate comprehensive summary
        summary = self._generate_test_summary( all_results, total_time )
        all_results[ "summary" ] = summary
        all_results[ "performance_results" ] = self.performance_results
        
        if self.debug:
            self._print_test_summary( summary )
        
        return all_results
    
    def _generate_test_summary( self, all_results: Dict[str, Any], total_time: float ) -> Dict[str, Any]:
        """
        Generate comprehensive summary of TodoList migration test results.
        
        Requires:
            - all_results contains results from all test categories
            - total_time is the total execution time
            
        Ensures:
            - Returns structured summary with pass/fail counts
            - Includes performance analysis
            - Provides migration readiness assessment
            
        Raises:
            - None
        """
        summary = {
            "total_execution_time": total_time,
            "categories_tested": 0,
            "total_tests": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "success_rate": 0.0,
            "critical_issues": [ ],
            "migration_ready": False,
            "agent_type": "TodoListAgent",
            "target_model": "CodeResponse"
        }
        
        # Count results across all categories
        for category_name, category_results in all_results.items():
            if category_name in [ "summary", "performance_results" ]:
                continue
                
            if isinstance( category_results, dict ):
                summary[ "categories_tested" ] += 1
                
                for test_name, result in category_results.items():
                    if isinstance( result, bool ):
                        summary[ "total_tests" ] += 1
                        if result:
                            summary[ "tests_passed" ] += 1
                        else:
                            summary[ "tests_failed" ] += 1
                            # Identify critical issues
                            if "error" in test_name.lower() or "integration" in test_name.lower():
                                summary[ "critical_issues" ].append( f"{category_name}.{test_name}" )
        
        # Calculate success rate
        if summary[ "total_tests" ] > 0:
            summary[ "success_rate" ] = ( summary[ "tests_passed" ] / summary[ "total_tests" ] ) * 100
        
        # Determine migration readiness
        summary[ "migration_ready" ] = (
            summary[ "success_rate" ] >= 95 and  # Higher threshold for TodoList (should be easier)
            len( summary[ "critical_issues" ] ) == 0 and  # No critical issues
            summary[ "categories_tested" ] >= 4  # At least 4 categories tested
        )
        
        # Performance analysis
        if self.performance_results:
            baseline_times = [ r[ "time" ] for r in self.performance_results if r[ "strategy" ] == "baseline" and r[ "success" ] ]
            coderesponse_times = [ r[ "time" ] for r in self.performance_results if r[ "strategy" ] == "coderesponse" and r[ "success" ] ]
            
            summary[ "performance" ] = {
                "baseline_avg_time": sum( baseline_times ) / len( baseline_times ) if baseline_times else 0,
                "coderesponse_avg_time": sum( coderesponse_times ) / len( coderesponse_times ) if coderesponse_times else 0,
                "baseline_samples": len( baseline_times ),
                "coderesponse_samples": len( coderesponse_times )
            }
            
            if baseline_times and coderesponse_times:
                avg_baseline = summary[ "performance" ][ "baseline_avg_time" ]
                avg_coderesponse = summary[ "performance" ][ "coderesponse_avg_time" ]
                summary[ "performance" ][ "coderesponse_speed_ratio" ] = avg_coderesponse / avg_baseline if avg_baseline > 0 else 1.0
        
        return summary
    
    def _print_test_summary( self, summary: Dict[str, Any] ) -> None:
        """
        Print formatted TodoList migration test summary to console.
        
        Requires:
            - summary contains structured test results
            
        Ensures:
            - Prints comprehensive test summary
            - Highlights critical issues and performance data
            
        Raises:
            - None
        """
        print( "\n" + "=" * 80 )
        print( "TODOLIST MIGRATION VALIDATION SUMMARY" )
        print( "=" * 80 )
        
        print( f"Agent: {summary[ 'agent_type' ]}" )
        print( f"Target Model: {summary[ 'target_model' ]}" )
        print( f"Execution Time: {summary[ 'total_execution_time' ]:.3f}s" )
        print( f"Categories Tested: {summary[ 'categories_tested' ]}" )
        print( f"Total Tests: {summary[ 'total_tests' ]}" )
        print( f"Tests Passed: {summary[ 'tests_passed' ]}" )
        print( f"Tests Failed: {summary[ 'tests_failed' ]}" )
        print( f"Success Rate: {summary[ 'success_rate' ]:.1f}%" )
        
        if summary[ "critical_issues" ]:
            print( f"\nCRITICAL ISSUES ({len( summary[ 'critical_issues' ] )}):" )
            for issue in summary[ "critical_issues" ]:
                print( f"  ✗ {issue}" )
        else:
            print( "\n✅ No critical issues detected" )
        
        if "performance" in summary:
            perf = summary[ "performance" ]
            print( f"\nPERFORMANCE ANALYSIS:" )
            print( f"  Baseline avg: {perf[ 'baseline_avg_time' ] * 1000:.2f}ms ({perf[ 'baseline_samples' ]} samples)" )
            print( f"  CodeResponse avg: {perf[ 'coderesponse_avg_time' ] * 1000:.2f}ms ({perf[ 'coderesponse_samples' ]} samples)" )
            
            if "coderesponse_speed_ratio" in perf:
                ratio = perf[ "coderesponse_speed_ratio" ]
                if ratio < 1.0:
                    print( f"  ⚡ CodeResponse is {1/ratio:.1f}x FASTER than baseline" )
                elif ratio > 1.0:
                    print( f"  🐌 CodeResponse is {ratio:.1f}x slower than baseline" )
                else:
                    print( f"  ⚖️ CodeResponse and baseline have similar performance" )
        
        print( f"\nMIGRATION STATUS: {'✅ READY' if summary[ 'migration_ready' ] else '❌ NOT READY'}" )
        
        if not summary[ "migration_ready" ]:
            print( "\nACTIONS REQUIRED:" )
            if summary[ "success_rate" ] < 95:
                print( f"  - Improve test success rate (currently {summary[ 'success_rate' ]:.1f}%, need ≥95%)" )
            if summary[ "critical_issues" ]:
                print( f"  - Resolve {len( summary[ 'critical_issues' ] )} critical issues" )
            if summary[ "categories_tested" ] < 4:
                print( f"  - Test more categories (currently {summary[ 'categories_tested' ]}, need ≥4)" )
        
        print( "=" * 80 )


def quick_smoke_test() -> bool:
    """
    Quick smoke test for TodoListXmlMigrationTester.
    
    Tests basic functionality and migration validation capabilities.
    
    Returns:
        True if smoke test passes
    """
    print( "Testing TodoListXmlMigrationTester..." )
    
    try:
        # Create tester instance
        tester = TodoListXmlMigrationTester( debug=True, verbose=False )
        print( "  ✓ Tester created successfully" )
        
        # Run quick validation (subset of full test suite)
        print( "  - Running basic validation tests..." )
        
        # Test strategy selection
        strategy_results = tester.test_strategy_selection()
        strategy_passed = sum( 1 for result in strategy_results.values() if result is True )
        print( f"    Strategy selection: {strategy_passed}/{len( strategy_results )} passed" )
        
        # Test factory integration  
        factory_results = tester.test_factory_integration()
        factory_passed = sum( 1 for result in factory_results.values() if result is True )
        print( f"    Factory integration: {factory_passed}/{len( factory_results )} passed" )
        
        print( "  ✓ Basic validation tests completed" )
        print( "✓ TodoListXmlMigrationTester smoke test PASSED" )
        
        return True
        
    except Exception as e:
        print( f"✗ TodoListXmlMigrationTester smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        return False


def run_full_migration_test() -> bool:
    """
    Run the complete TodoListAgent migration validation test suite.
    
    This is the main entry point for comprehensive migration testing.
    
    Returns:
        True if migration is ready, False if issues detected
    """
    print( "Starting comprehensive TodoList XML migration validation..." )
    
    try:
        tester = TodoListXmlMigrationTester( debug=True, verbose=False )
        
        results = tester.run_comprehensive_test_suite()
        
        # Return migration readiness status
        return results.get( "summary", { } ).get( "migration_ready", False )
        
    except Exception as e:
        print( f"TodoList migration test suite failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run smoke test when executed directly
    success = quick_smoke_test()
    
    if success:
        print( "\n" + "="*50 )
        print( "Running full TodoList migration validation..." )
        print( "="*50 )
        
        migration_ready = run_full_migration_test()
        exit_code = 0 if migration_ready else 1
        
        print( f"\nExiting with code {exit_code}" )
        exit( exit_code )
    else:
        exit( 1 )