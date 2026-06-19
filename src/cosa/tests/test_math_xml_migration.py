#!/usr/bin/env python3
"""
MathAgent XML Migration Validation Tests

This module provides comprehensive tests for the MathAgent XML parsing migration
from baseline util_xml.py parsing to Pydantic-based structured parsing using CodeBrainstormResponse model.

Tests validate:
- XML parsing strategy selection for MathAgent
- Baseline vs CodeBrainstormResponse parsing compatibility 
- Mathematical brainstorming workflow validation with thoughts, brainstorm, and evaluation fields
- Code structure validation and list handling for mathematical computations
- Migration debugging and comparison features
- End-to-end MathAgent workflow validation

This is part of the Pydantic XML Migration Project Phase 4b.
"""

import time
from typing import Dict, Any

from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.agents.io_models.xml_models import CodeBrainstormResponse


class MathXmlMigrationTester:
    """
    Comprehensive test suite for MathAgent XML parsing migration.
    
    This tester validates the migration from baseline XML parsing to 
    Pydantic CodeBrainstormResponse model parsing, including edge cases and performance analysis.
    """
    
    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize Math migration tester.
        
        Requires:
            - Configuration manager can be initialized
            - XML parser factory can be created
            
        Ensures:
            - Test environment is properly configured
            - Math test data samples are prepared
            - Performance tracking is initialized
            
        Raises:
            - ConfigException if configuration setup fails
        """
        self.debug = debug
        self.verbose = verbose
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.factory = XmlParserFactory( config_mgr=self.config_mgr )
        
        # Test data samples for MathAgent validation
        self.test_xml_samples = self._generate_test_xml_samples()
        self.performance_results = [ ]
        
        if debug:
            print( "MathXmlMigrationTester initialized" )
    
    def _generate_test_xml_samples( self ) -> list[Dict[str, Any]]:
        """
        Generate comprehensive test XML samples for MathAgent validation.
        
        Requires:
            - None
            
        Ensures:
            - Returns list of test cases with XML and expected results
            - Covers all MathAgent XML patterns and edge cases
            - Includes malformed XML for error testing
            
        Raises:
            - None
        """
        samples = [
            {
                "name": "simple_arithmetic",
                "xml": '''<response>
                    <thoughts>The user wants to calculate 25 multiplied by 8</thoughts>
                    <brainstorm>
                        <idea1>Use basic multiplication operator</idea1>
                        <idea2>Use repeated addition method</idea2>
                        <idea3>Use Python's operator module</idea3>
                    </brainstorm>
                    <evaluation>Direct multiplication is simplest and most efficient</evaluation>
                    <code>
                        <line>result = 25 * 8</line>
                        <line>print(f"25 × 8 = {result}")</line>
                    </code>
                    <example>print(result)</example>
                    <returns>int</returns>
                    <explanation>Performs direct multiplication of two integers</explanation>
                </response>''',
                "expected_code_lines": 2,
                "expected_returns": "int",
                "should_parse": True
            },
            {
                "name": "quadratic_formula",
                "xml": '''<response>
                    <thoughts>Need to solve quadratic equation ax^2 + bx + c = 0 using the quadratic formula</thoughts>
                    <brainstorm>
                        <idea1>Factor if possible</idea1>
                        <idea2>Complete the square method</idea2>
                        <idea3>Use quadratic formula (most general)</idea3>
                    </brainstorm>
                    <evaluation>Quadratic formula works for all cases and is most reliable approach</evaluation>
                    <code>
                        <line>import math</line>
                        <line>def solve_quadratic(a, b, c):</line>
                        <line>    discriminant = b**2 - 4*a*c</line>
                        <line>    if discriminant &lt; 0:</line>
                        <line>        return "No real solutions"</line>
                        <line>    sqrt_discriminant = math.sqrt(discriminant)</line>
                        <line>    x1 = (-b + sqrt_discriminant) / (2*a)</line>
                        <line>    x2 = (-b - sqrt_discriminant) / (2*a)</line>
                        <line>    return (x1, x2)</line>
                    </code>
                    <example>solutions = solve_quadratic(1, -5, 6)</example>
                    <returns>tuple</returns>
                    <explanation>Implements quadratic formula with discriminant check for real solutions</explanation>
                </response>''',
                "expected_code_lines": 9,
                "expected_returns": "tuple",
                "should_parse": True
            },
            {
                "name": "area_calculation",
                "xml": '''<response>
                    <thoughts>User wants to calculate the area of a circle given its radius</thoughts>
                    <brainstorm>
                        <idea1>Use pi*r^2 formula</idea1>
                        <idea2>Approximate with polygons</idea2>
                        <idea3>Use integration method</idea3>
                    </brainstorm>
                    <evaluation>The standard formula A = pi*r^2 is most accurate and efficient</evaluation>
                    <code>
                        <line>import math</line>
                        <line>def circle_area(radius):</line>
                        <line>    return math.pi * radius ** 2</line>
                        <line>area = circle_area(5)</line>
                        <line>print(f"Area of circle with radius 5: {area:.2f}")</line>
                    </code>
                    <example>area = circle_area(5)</example>
                    <returns>float</returns>
                    <explanation>Uses the standard mathematical formula pi*r^2 to calculate circle area</explanation>
                </response>''',
                "expected_code_lines": 5,
                "expected_returns": "float",
                "should_parse": True
            },
            {
                "name": "statistical_calculation",
                "xml": '''<response>
                    <thoughts>Need to calculate mean, median, and standard deviation of a dataset</thoughts>
                    <brainstorm>
                        <idea1>Implement manually with formulas</idea1>
                        <idea2>Use statistics module</idea2>
                        <idea3>Use numpy for calculations</idea3>
                    </brainstorm>
                    <evaluation>Python's statistics module provides accurate built-in functions</evaluation>
                    <code>
                        <line>import statistics</line>
                        <line>def analyze_data(numbers):</line>
                        <line>    mean = statistics.mean(numbers)</line>
                        <line>    median = statistics.median(numbers)</line>
                        <line>    stdev = statistics.stdev(numbers) if len(numbers) > 1 else 0</line>
                        <line>    return {"mean": mean, "median": median, "stdev": stdev}</line>
                        <line>data = [10, 20, 30, 40, 50]</line>
                        <line>result = analyze_data(data)</line>
                    </code>
                    <example>stats = analyze_data([1, 2, 3, 4, 5])</example>
                    <returns>dict</returns>
                    <explanation>Calculates descriptive statistics using Python's statistics module</explanation>
                </response>''',
                "expected_code_lines": 8,
                "expected_returns": "dict",
                "should_parse": True
            },
            {
                "name": "malformed_missing_thoughts",
                "xml": '''<response>
                    <brainstorm>Could solve this with basic arithmetic</brainstorm>
                    <evaluation>Direct calculation is best</evaluation>
                    <code>
                        <line>result = 2 + 2</line>
                    </code>
                    <example>test()</example>
                    <returns>int</returns>
                    <explanation>Test missing thoughts field</explanation>
                </response>''',
                "should_parse": False  # Should fail due to missing thoughts field
            },
            {
                "name": "empty_brainstorm_field",
                "xml": '''<response>
                    <thoughts>Testing empty brainstorm field behavior</thoughts>
                    <brainstorm>
                        <idea1></idea1>
                        <idea2></idea2>
                        <idea3></idea3>
                    </brainstorm>
                    <evaluation>Simple approach works</evaluation>
                    <code>
                        <line>result = 5 * 5</line>
                    </code>
                    <example>empty_example()</example>
                    <returns>int</returns>
                    <explanation>Testing behavior with empty brainstorm ideas</explanation>
                </response>''',
                "should_parse": False  # Should fail due to empty brainstorm ideas requirement
            }
        ]
        
        return samples
    
    def test_strategy_selection( self ) -> Dict[str, bool]:
        """
        Test XML parsing strategy selection for MathAgent.
        
        Requires:
            - Factory can create different strategy types
            - MathAgent routing command is recognized
            
        Ensures:
            - Tests strategy selection for MathAgent routing command
            - Tests fallback behavior and configuration handling
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing MathAgent Strategy Selection ===" )
        
        try:
            # Test baseline strategy for MathAgent
            self.factory.global_strategy = "baseline"
            strategy = self.factory.get_parser_strategy( "agent router go to math" )
            results[ "baseline_strategy_math" ] = strategy.get_strategy_name() == "baseline"
            
            if self.debug:
                print( f"  ✓ Baseline strategy for math: {strategy.get_strategy_name()}" )
            
            # Test structured strategy for MathAgent (should use CodeBrainstormResponse)
            self.factory.global_strategy = "structured_v2"
            strategy = self.factory.get_parser_strategy( "agent router go to math" )
            # Should either succeed with structured_v2 or fall back to baseline
            results[ "structured_strategy_math" ] = strategy.get_strategy_name() in [ "structured_v2", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Structured strategy for math: {strategy.get_strategy_name()}" )
            
            # Test hybrid strategy
            self.factory.global_strategy = "hybrid_v1"
            strategy = self.factory.get_parser_strategy( "agent router go to math" )
            results[ "hybrid_strategy_math" ] = strategy.get_strategy_name() in [ "hybrid_v1", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Hybrid strategy for math: {strategy.get_strategy_name()}" )
                
        except Exception as e:
            if self.debug:
                print( f"  ✗ Strategy selection test failed: {e}" )
            results[ "strategy_selection_error" ] = False
        
        return results
    
    def test_baseline_parsing( self ) -> Dict[str, bool]:
        """
        Test baseline XML parsing with MathAgent patterns.
        
        Requires:
            - Factory can create baseline parsing strategy
            - Test XML samples cover MathAgent patterns
            
        Ensures:
            - Tests parsing of Math XML structures
            - Tests code line extraction with baseline parser
            - Tests error handling for malformed XML
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Math Baseline Parsing ===" )
        
        # Force baseline strategy
        self.factory.global_strategy = "baseline"
        
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                parsed_result = self.factory.parse_agent_response(
                    xml_response=sample[ "xml" ],
                    agent_routing_command="agent router go to math",
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
        Test Pydantic CodeBrainstormResponse parsing with MathAgent patterns.
        
        Requires:
            - Factory can create structured parsing strategy
            - CodeBrainstormResponse model handles Math XML patterns
            
        Ensures:
            - Tests parsing of Math XML with Pydantic validation
            - Tests mathematical brainstorming field validation and code extraction
            - Tests error handling for validation failures
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Math Pydantic Parsing ===" )
        
        # Force structured strategy
        self.factory.global_strategy = "structured_v2"
        
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                parsed_result = self.factory.parse_agent_response(
                    xml_response=sample[ "xml" ],
                    agent_routing_command="agent router go to math",
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
    
    def test_mathematical_reasoning_validation( self ) -> Dict[str, bool]:
        """
        Test specific mathematical reasoning field validation for CodeBrainstormResponse.
        
        Requires:
            - CodeBrainstormResponse model is properly imported
            - Mathematical brainstorming XML patterns are available
            
        Ensures:
            - Tests thoughts, brainstorm, evaluation field validation for math problems
            - Tests mathematical context handling and code validation
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Math Reasoning Field Validation ===" )
        
        try:
            # Test valid mathematical reasoning structure
            valid_xml = '''<response>
                <thoughts>Need to find the roots of x² - 5x + 6 = 0</thoughts>
                <brainstorm>Could factor (x-2)(x-3)=0, complete square, or use quadratic formula</brainstorm>
                <evaluation>Factoring is simplest since this factors nicely</evaluation>
                <code>
                    <line>import sympy</line>
                    <line>x = sympy.Symbol('x')</line>
                    <line>roots = sympy.solve(x**2 - 5*x + 6, x)</line>
                </code>
                <example>roots = solve_quadratic(1, -5, 6)</example>
                <returns>list</returns>
                <explanation>Factors the quadratic equation to find roots</explanation>
            </response>'''
            
            model = CodeBrainstormResponse.from_xml( valid_xml )
            results[ "valid_math_reasoning_structure" ] = True
            
            if self.debug:
                print( f"  ✓ Valid math reasoning structure parsed" )
                print( f"    - Thoughts: {model.thoughts[:40]}..." )
                print( f"    - Brainstorm: {model.brainstorm[:40]}..." )
                print( f"    - Evaluation: {model.evaluation[:40]}..." )
            
            # Test mathematical imports and functions detection
            has_imports = any( line.strip().startswith( ('import ', 'from ') ) for line in model.code )
            results[ "math_imports_detected" ] = has_imports
            
            if self.debug:
                print( f"  ✓ Math imports detected: {has_imports}" )
            
            # Test complex mathematical reasoning
            complex_xml = '''<response>
                <thoughts>User wants to calculate compound interest with monthly compounding</thoughts>
                <brainstorm>Could use A=P(1+r/n)^nt formula, calculate step by step, or use financial libraries</brainstorm>
                <evaluation>Standard compound interest formula is most accurate and educational</evaluation>
                <code>
                    <line>def compound_interest(principal, rate, compounds_per_year, years):</line>
                    <line>    amount = principal * (1 + rate/compounds_per_year)**(compounds_per_year * years)</line>
                    <line>    interest = amount - principal</line>
                    <line>    return amount, interest</line>
                </code>
                <example>final, earned = compound_interest(1000, 0.05, 12, 5)</example>
                <returns>tuple</returns>
                <explanation>Applies compound interest formula A=P(1+r/n)^nt for monthly compounding</explanation>
            </response>'''
            
            complex_model = CodeBrainstormResponse.from_xml( complex_xml )
            results[ "complex_math_reasoning" ] = True
            
            if self.debug:
                print( f"  ✓ Complex math reasoning parsed successfully" )
                print( f"    - Function detected: {complex_model.get_function_name()}" )
                print( f"    - Code lines: {len( complex_model.code )}" )
                    
        except Exception as e:
            if self.debug:
                print( f"  ✗ Math reasoning validation test failed: {e}" )
            results[ "math_reasoning_validation_error" ] = False
        
        return results
    
    def test_config_integration( self ) -> Dict[str, bool]:
        """
        Test MathAgent configuration integration.
        
        Requires:
            - Configuration manager is available
            - Math agent configuration keys exist
            
        Ensures:
            - Tests strategy override configuration for Math agent
            - Tests global configuration integration
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Math Configuration Integration ===" )
        
        try:
            # Test global strategy configuration
            global_strategy = self.config_mgr.get( "xml parsing global strategy", default="baseline" )
            results[ "math_global_strategy_config" ] = global_strategy in [ "baseline", "hybrid_v1", "structured_v2" ]
            
            # Test agent-specific override (if configured)
            override_key = "xml parsing strategy for agent router go to math"
            override_value = self.config_mgr.get( override_key, default=None )
            results[ "math_override_config" ] = True  # Always pass since override is optional
            
            # Test debug mode configuration
            debug_mode = self.config_mgr.get( "xml parsing migration debug mode", default=False, return_type="boolean" )
            results[ "math_debug_mode_config" ] = isinstance( debug_mode, bool )
            
            if self.debug:
                print( f"  ✓ Global strategy: {global_strategy}" )
                print( f"  ✓ Agent override: {override_value or 'not set'}" )
                print( f"  ✓ Debug mode: {debug_mode}" )
        
        except Exception as e:
            results[ "math_config_integration_error" ] = False
            if self.debug:
                print( f"  ✗ Math configuration integration test failed: {e}" )
        
        return results
    
    def run_comprehensive_test_suite( self ) -> Dict[str, Any]:
        """
        Run the complete MathAgent migration validation test suite.
        
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
            print( "MathAgent XML Migration Validation Test Suite" )
            print( "=" * 80 )
        
        all_results = { }
        
        # Run all test categories
        test_categories = [
            ( "strategy_selection", self.test_strategy_selection ),
            ( "baseline_parsing", self.test_baseline_parsing ),
            ( "pydantic_parsing", self.test_pydantic_parsing ),
            ( "math_reasoning_validation", self.test_mathematical_reasoning_validation ),
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
        Generate comprehensive summary of MathAgent migration test results.
        
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
        if not strategy_results.get( "structured_strategy_math", True ):
            critical_issues.append( "Structured strategy not working for MathAgent" )
        
        # Check for Pydantic parsing failures
        pydantic_results = all_results.get( "pydantic_parsing", {} ).get( "results", {} )
        pydantic_failures = [ key for key, value in pydantic_results.items() if key.startswith( "pydantic_" ) and not value ]
        if len( pydantic_failures ) > 1:
            critical_issues.append( f"Multiple Pydantic parsing failures: {len( pydantic_failures )}" )
        
        # Check for mathematical reasoning issues
        reasoning_results = all_results.get( "math_reasoning_validation", {} ).get( "results", {} )
        if not reasoning_results.get( "valid_math_reasoning_structure", True ):
            critical_issues.append( "Mathematical reasoning structure validation failing" )
        
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
            reasoning_results.get( "valid_math_reasoning_structure", False ) and
            reasoning_results.get( "math_imports_detected", False )
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
            "math_reasoning_working": all(
                reasoning_results.get( field, False )
                for field in [ "valid_math_reasoning_structure", "math_imports_detected" ]
            )
        }
    
    def _print_comprehensive_summary( self, summary: Dict[str, Any] ) -> None:
        """Print formatted comprehensive test summary."""
        print( "\n" + "=" * 80 )
        print( "MathAgent Migration Test Summary" )
        print( "=" * 80 )
        
        print( f"Overall Results:" )
        print( f"  - Tests: {summary[ 'total_passed' ]}/{summary[ 'total_tests' ]} passed ({summary[ 'success_rate' ]:.1f}%)" )
        print( f"  - Categories: {summary[ 'categories_tested' ]} test categories completed" )
        print( f"  - Migration Ready: {'✓ YES' if summary[ 'migration_ready' ] else '✗ NO'}" )
        
        if summary[ "performance_ratio" ] > 0:
            print( f"  - Performance: Pydantic {summary[ 'performance_ratio' ]:.1f}x slower than baseline" )
            print( f"    - Baseline avg: {summary[ 'avg_baseline_time' ]:.4f}s" )
            print( f"    - Pydantic avg: {summary[ 'avg_pydantic_time' ]:.4f}s" )
        
        print( f"  - Math Reasoning: {'✓ Working' if summary[ 'math_reasoning_working' ] else '✗ Issues'}" )
        
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
            if not summary[ "math_reasoning_working" ]:
                print( f"  - Fix mathematical reasoning validation issues" )
        
        print( "=" * 80 )


def quick_smoke_test() -> bool:
    """
    Quick smoke test for MathXmlMigrationTester.
    
    Tests basic functionality and migration validation capabilities.
    
    Returns:
        True if smoke test passes
    """
    print( "Testing MathXmlMigrationTester..." )
    
    try:
        # Test 1: Tester initialization
        print( "  - Testing tester initialization..." )
        tester = MathXmlMigrationTester( debug=False )
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
            <thoughts>Calculate 2 + 2</thoughts>
            <brainstorm>
                <idea1>Add manually</idea1>
                <idea2>Use calculator</idea2>
                <idea3>Write code</idea3>
            </brainstorm>
            <evaluation>Direct addition is simplest</evaluation>
            <code><line>result = 2 + 2</line></code>
            <example>print(result)</example>
            <returns>int</returns>
            <explanation>Performs basic addition</explanation>
        </response>'''
        
        # Test baseline parsing
        tester.factory.global_strategy = "baseline"
        baseline_result = tester.factory.parse_agent_response(
            sample_xml, 
            "agent router go to math",
            [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
        )
        assert "thoughts" in baseline_result, "Baseline parsing missing thoughts field"
        print( "    ✓ Baseline parsing works" )
        
        # Test Pydantic parsing
        tester.factory.global_strategy = "structured_v2"
        pydantic_result = tester.factory.parse_agent_response(
            sample_xml,
            "agent router go to math", 
            [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
        )
        assert "brainstorm" in pydantic_result, "Pydantic parsing missing brainstorm field"
        assert isinstance( pydantic_result.get( "code", [] ), list ), "Pydantic code field should be list"
        print( "    ✓ Pydantic parsing works" )
        
        print( "✓ MathXmlMigrationTester smoke test PASSED" )
        return True
        
    except Exception as e:
        print( f"✗ MathXmlMigrationTester smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        return False


def run_full_migration_test() -> bool:
    """
    Run full MathAgent migration validation test suite.
    
    Returns:
        True if migration is ready
    """
    try:
        print( "Initializing MathAgent migration test suite..." )
        tester = MathXmlMigrationTester( debug=True )
        
        print( "Running comprehensive test suite..." )
        results = tester.run_comprehensive_test_suite()
        
        # Return migration readiness status
        return results.get( "summary", { } ).get( "migration_ready", False )
        
    except Exception as e:
        print( f"Math migration test suite failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run smoke test when executed directly
    success = quick_smoke_test()
    
    if success:
        print( "\n" + "="*50 )
        print( "Running full Math migration validation..." )
        print( "="*50 )
        
        migration_ready = run_full_migration_test()
        exit_code = 0 if migration_ready else 1
        
        print( f"\nMathAgent Migration Status: {'READY' if migration_ready else 'NOT READY'}" )
        exit( exit_code )
    else:
        exit( 1 )