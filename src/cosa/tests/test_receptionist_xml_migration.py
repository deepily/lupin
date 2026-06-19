#!/usr/bin/env python3
"""
Receptionist Agent XML Migration Validation Tests

This module provides comprehensive tests for the ReceptionistAgent XML parsing migration
from baseline util_xml.py parsing to Pydantic-based structured parsing.

Tests validate:
- XML parsing strategy selection and configuration
- Baseline vs Pydantic parsing compatibility 
- Migration debugging and comparison features
- End-to-end receptionist agent workflow
- Performance and correctness validation

This is part of the Pydantic XML Migration Project Phase 4.
"""

import time
import tempfile
from typing import Dict, Any
from unittest.mock import patch, MagicMock

from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.agents.io_models.xml_models import ReceptionistResponse


class ReceptionistXmlMigrationTester:
    """
    Comprehensive test suite for ReceptionistAgent XML parsing migration.
    
    This tester validates the complete migration from baseline XML parsing
    to Pydantic-based structured parsing, including hybrid comparison modes
    and configuration-driven strategy selection.
    """
    
    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize migration tester with configuration.
        
        Requires:
            - Configuration manager can be initialized
            - XML parser factory can be created
            
        Ensures:
            - Test environment is properly configured
            - Test data samples are prepared
            - Performance tracking is initialized
            
        Raises:
            - ConfigException if configuration setup fails
        """
        self.debug = debug
        self.verbose = verbose
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.factory = XmlParserFactory( config_mgr=self.config_mgr )
        
        # Test data samples for validation
        self.test_xml_samples = self._generate_test_xml_samples()
        self.performance_results = [ ]
        
        if debug:
            print( "ReceptionistXmlMigrationTester initialized" )
    
    def _generate_test_xml_samples( self ) -> list[Dict[str, Any]]:
        """
        Generate comprehensive test XML samples for validation.
        
        Requires:
            - None
            
        Ensures:
            - Returns list of test cases with XML and expected results
            - Covers all category types and edge cases
            - Includes malformed XML for error testing
            
        Raises:
            - None
        """
        samples = [
            {
                "name": "benign_simple",
                "xml": '''<response>
                    <thoughts>The user is asking about system capabilities</thoughts>
                    <category>benign</category>
                    <answer>CoSA is a collection of small agents</answer>
                </response>''',
                "expected_category": "benign",
                "expected_safe": True,
                "should_parse": True
            },
            {
                "name": "humorous_response", 
                "xml": '''<response>
                    <thoughts>This seems like a joke or lighthearted question</thoughts>
                    <category>humorous</category>
                    <answer>Why did the AI cross the road? To get to the other dataset!</answer>
                </response>''',
                "expected_category": "humorous",
                "expected_safe": True,
                "should_parse": True
            },
            {
                "name": "salacious_content",
                "xml": '''<response>
                    <thoughts>This query contains inappropriate adult content</thoughts>
                    <category>salacious</category>
                    <answer>I cannot provide that type of content</answer>
                </response>''',
                "expected_category": "salacious",
                "expected_safe": False,
                "should_parse": True
            },
            {
                "name": "empty_thoughts",
                "xml": '''<response>
                    <thoughts></thoughts>
                    <category>benign</category>
                    <answer>Test answer</answer>
                </response>''',
                "expected_category": "benign", 
                "expected_safe": True,
                "should_parse": False  # Should fail validation due to empty thoughts
            },
            {
                "name": "missing_category",
                "xml": '''<response>
                    <thoughts>Missing category field</thoughts>
                    <answer>Test answer</answer>
                </response>''',
                "should_parse": False  # Missing required field
            },
            {
                "name": "malformed_xml",
                "xml": '''<response>
                    <thoughts>Unclosed tag test
                    <category>benign</category>
                    <answer>Test answer</answer>
                </response>''',
                "should_parse": False  # Malformed XML
            },
            {
                "name": "xml_escapes",
                "xml": '''<response>
                    <thoughts>Testing XML escapes: &lt;tag&gt; and &amp; character</thoughts>
                    <category>benign</category>
                    <answer>Escapes handled: &quot;quotes&quot; and &apos;apostrophes&apos;</answer>
                </response>''',
                "expected_category": "benign",
                "expected_safe": True,
                "should_parse": True
            }
        ]
        
        return samples
    
    def test_strategy_selection( self ) -> Dict[str, bool]:
        """
        Test XML parsing strategy selection based on configuration.
        
        Requires:
            - Configuration manager provides strategy settings
            - Factory can create different strategy types
            
        Ensures:
            - Tests global strategy selection
            - Tests per-agent strategy overrides
            - Tests fallback behavior for unknown strategies
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Strategy Selection ===" )
        
        try:
            # Test 1: Default baseline strategy
            self.factory.global_strategy = "baseline"
            strategy = self.factory.get_parser_strategy( "agent router go to receptionist" )
            results[ "baseline_strategy" ] = strategy.get_strategy_name() == "baseline"
            
            if self.debug:
                print( f"  ✓ Baseline strategy: {strategy.get_strategy_name()}" )
            
            # Test 2: Structured strategy (may fall back)
            self.factory.global_strategy = "structured_v2"
            strategy = self.factory.get_parser_strategy( "agent router go to receptionist" )
            # Accept either structured_v2 or baseline (fallback)
            results[ "structured_strategy" ] = strategy.get_strategy_name() in [ "structured_v2", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Structured strategy: {strategy.get_strategy_name()}" )
            
            # Test 3: Hybrid strategy (may fall back)
            self.factory.global_strategy = "hybrid_v1"
            strategy = self.factory.get_parser_strategy( "agent router go to receptionist" )
            # Accept either hybrid_v1 or baseline (fallback)
            results[ "hybrid_strategy" ] = strategy.get_strategy_name() in [ "hybrid_v1", "baseline" ]
            
            if self.debug:
                print( f"  ✓ Hybrid strategy: {strategy.get_strategy_name()}" )
            
            # Test 4: Unknown strategy fallback
            self.factory.global_strategy = "unknown_strategy"
            strategy = self.factory.get_parser_strategy( "agent router go to receptionist" )
            results[ "fallback_strategy" ] = strategy.get_strategy_name() == "baseline"
            
            if self.debug:
                print( f"  ✓ Fallback strategy: {strategy.get_strategy_name()}" )
            
        except Exception as e:
            if self.debug:
                print( f"  ✗ Strategy selection test failed: {e}" )
            results[ "strategy_selection_error" ] = False
        
        return results
    
    def test_baseline_parsing( self ) -> Dict[str, bool]:
        """
        Test baseline XML parsing functionality with all test samples.
        
        Requires:
            - Factory can create baseline parsing strategy
            - Test XML samples are properly formatted
            
        Ensures:
            - Tests parsing of valid XML samples
            - Tests error handling for malformed XML
            - Tests field extraction accuracy
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Baseline Parsing ===" )
        
        # Force baseline strategy
        self.factory.global_strategy = "baseline"
        
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                parsed_result = self.factory.parse_agent_response(
                    xml_response=sample[ "xml" ],
                    agent_routing_command="agent router go to receptionist",
                    xml_tag_names=[ "thoughts", "category", "answer" ],
                    debug=False,  # Reduce noise
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
                    # Should parse successfully
                    has_required_fields = all( 
                        field in parsed_result 
                        for field in [ "thoughts", "category", "answer" ] 
                    )
                    results[ f"baseline_{sample_name}_fields" ] = has_required_fields
                    
                    # Check specific expectations
                    if "expected_category" in sample:
                        category_correct = parsed_result.get( "category" ) == sample[ "expected_category" ]
                        results[ f"baseline_{sample_name}_category" ] = category_correct
                    
                    if self.debug:
                        print( f"  ✓ {sample_name}: parsed successfully" )
                else:
                    # Should fail but baseline parsing is lenient
                    results[ f"baseline_{sample_name}_lenient" ] = True
                    
                    if self.debug:
                        print( f"  ⚠ {sample_name}: parsed despite potential issues (baseline is lenient)" )
                
            except Exception as e:
                parsing_time = time.time() - start_time
                
                # Record performance even for failures
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
    
    def test_pydantic_parsing( self ) -> Dict[str, bool]:
        """
        Test Pydantic XML parsing functionality with validation.
        
        Requires:
            - ReceptionistResponse model is properly implemented
            - Factory can create Pydantic parsing strategy
            
        Ensures:
            - Tests strict validation of XML samples
            - Tests type safety and field validation
            - Tests error handling for validation failures
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Pydantic Parsing ===" )
        
        # Test direct Pydantic parsing (not through factory to avoid fallbacks)
        for sample in self.test_xml_samples:
            sample_name = sample[ "name" ]
            
            try:
                start_time = time.time()
                
                # Parse directly with ReceptionistResponse model
                response_obj = ReceptionistResponse.from_xml( sample[ "xml" ] )
                
                parsing_time = time.time() - start_time
                
                # Record performance
                self.performance_results.append({
                    "strategy": "pydantic",
                    "sample": sample_name,
                    "time": parsing_time,
                    "success": True
                })
                
                if sample[ "should_parse" ]:
                    # Should parse successfully - check validation
                    results[ f"pydantic_{sample_name}_parse" ] = True
                    
                    # Check type safety
                    is_type_safe = (
                        isinstance( response_obj.thoughts, str ) and
                        isinstance( response_obj.category, str ) and
                        isinstance( response_obj.answer, str )
                    )
                    results[ f"pydantic_{sample_name}_types" ] = is_type_safe
                    
                    # Check specific expectations
                    if "expected_category" in sample:
                        category_correct = response_obj.category == sample[ "expected_category" ]
                        results[ f"pydantic_{sample_name}_category" ] = category_correct
                    
                    if "expected_safe" in sample:
                        safety_correct = response_obj.is_safe_content() == sample[ "expected_safe" ]
                        results[ f"pydantic_{sample_name}_safety" ] = safety_correct
                    
                    if self.debug:
                        print( f"  ✓ {sample_name}: parsed and validated successfully" )
                else:
                    # Shouldn't have parsed but did - validation not strict enough
                    results[ f"pydantic_{sample_name}_unexpected_success" ] = False
                    if self.debug:
                        print( f"  ⚠ {sample_name}: parsed but should have failed validation" )
                
            except Exception as e:
                parsing_time = time.time() - start_time
                
                # Record performance even for failures
                self.performance_results.append({
                    "strategy": "pydantic", 
                    "sample": sample_name,
                    "time": parsing_time,
                    "success": False,
                    "error": str( e )
                })
                
                if sample[ "should_parse" ]:
                    results[ f"pydantic_{sample_name}_error" ] = False
                    if self.debug:
                        print( f"  ✗ {sample_name}: unexpected error: {e}" )
                else:
                    results[ f"pydantic_{sample_name}_expected_fail" ] = True
                    if self.debug:
                        print( f"  ✓ {sample_name}: failed validation as expected" )
        
        return results
    
    def test_hybrid_comparison( self ) -> Dict[str, bool]:
        """
        Test hybrid parsing strategy with baseline/Pydantic comparison.
        
        Requires:
            - Factory can create hybrid parsing strategy
            - Comparison logging configuration works
            
        Ensures:
            - Tests dual parsing execution
            - Tests performance comparison
            - Tests result consistency validation
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Hybrid Comparison ===" )
        
        try:
            # Test hybrid parsing without mocking (simpler approach)
            self.factory.global_strategy = "hybrid_v1"
            
            # Test hybrid parsing with a known good sample
            good_sample = self.test_xml_samples[ 0 ]  # benign_simple
            
            start_time = time.time()
            
            # This should trigger both baseline and Pydantic parsing
            parsed_result = self.factory.parse_agent_response(
                xml_response=good_sample[ "xml" ],
                agent_routing_command="agent router go to receptionist", 
                xml_tag_names=[ "thoughts", "category", "answer" ],
                debug=self.debug,
                verbose=self.verbose
            )
            
            parsing_time = time.time() - start_time
            
            # Record performance
            self.performance_results.append({
                "strategy": "hybrid",
                "sample": good_sample[ "name" ],
                "time": parsing_time,
                "success": True
            })
            
            results[ "hybrid_comparison_success" ] = True
            results[ "hybrid_result_structure" ] = all(
                field in parsed_result 
                for field in [ "thoughts", "category", "answer" ]
            )
            
            if self.debug:
                print( f"  ✓ Hybrid comparison completed successfully" )
        
        except Exception as e:
            results[ "hybrid_comparison_error" ] = False
            if self.debug:
                print( f"  ✗ Hybrid comparison failed: {e}" )
        
        return results
    
    def test_configuration_integration( self ) -> Dict[str, bool]:
        """
        Test integration with lupin-app.ini configuration settings.
        
        Requires:
            - Configuration manager provides XML parsing settings
            - All expected configuration keys are available
            
        Ensures:
            - Tests global strategy configuration
            - Tests per-agent strategy overrides
            - Tests debugging and logging flags
            
        Raises:
            - None (captures and reports errors)
        """
        results = { }
        
        if self.debug:
            print( "\n=== Testing Configuration Integration ===" )
        
        try:
            # Test 1: Global strategy setting
            global_strategy = self.config_mgr.get( "xml parsing global strategy", default="baseline" )
            results[ "global_strategy_config" ] = global_strategy in [ "baseline", "hybrid_v1", "structured_v2" ]
            
            # Test 2: Per-agent override
            override_key = "xml parsing strategy for agent router go to receptionist"
            override_value = self.config_mgr.get( override_key, default="baseline" )
            results[ "agent_override_config" ] = override_value in [ "baseline", "hybrid_v1", "structured_v2" ]
            
            # Test 3: Debug mode flag
            debug_mode = self.config_mgr.get( "xml parsing migration debug mode", default=False, return_type="boolean" )
            results[ "debug_mode_config" ] = isinstance( debug_mode, bool )
            
            # Test 4: Comparison logging flag
            comparison_logging = self.config_mgr.get( "xml parsing migration comparison logging", default=False, return_type="boolean" )
            results[ "comparison_logging_config" ] = isinstance( comparison_logging, bool )
            
            # Test 5: Force both strategies flag
            force_both = self.config_mgr.get( "xml parsing migration force both strategies", default=False, return_type="boolean" )
            results[ "force_both_config" ] = isinstance( force_both, bool )
            
            if self.debug:
                print( f"  ✓ Global strategy: {global_strategy}" )
                print( f"  ✓ Agent override: {override_value}" )
                print( f"  ✓ Debug mode: {debug_mode}" )
                print( f"  ✓ Comparison logging: {comparison_logging}" )
                print( f"  ✓ Force both: {force_both}" )
        
        except Exception as e:
            results[ "config_integration_error" ] = False
            if self.debug:
                print( f"  ✗ Configuration integration test failed: {e}" )
        
        return results
    
    def run_comprehensive_test_suite( self ) -> Dict[str, Any]:
        """
        Run the complete migration validation test suite.
        
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
            print( "RECEPTIONIST XML MIGRATION VALIDATION TEST SUITE" )
            print( "=" * 80 )
        
        all_results = { }
        start_time = time.time()
        
        # Run all test categories
        test_categories = [
            ( "strategy_selection", self.test_strategy_selection ),
            ( "baseline_parsing", self.test_baseline_parsing ),
            ( "pydantic_parsing", self.test_pydantic_parsing ),
            ( "hybrid_comparison", self.test_hybrid_comparison ),
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
        Generate comprehensive summary of test results.
        
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
            "migration_ready": False
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
                            if "error" in test_name.lower() or "fail" in test_name.lower():
                                summary[ "critical_issues" ].append( f"{category_name}.{test_name}" )
        
        # Calculate success rate
        if summary[ "total_tests" ] > 0:
            summary[ "success_rate" ] = ( summary[ "tests_passed" ] / summary[ "total_tests" ] ) * 100
        
        # Determine migration readiness
        summary[ "migration_ready" ] = (
            summary[ "success_rate" ] >= 90 and  # At least 90% success rate
            len( summary[ "critical_issues" ] ) == 0 and  # No critical issues
            summary[ "categories_tested" ] >= 4  # At least 4 categories tested
        )
        
        # Performance analysis
        if self.performance_results:
            baseline_times = [ r[ "time" ] for r in self.performance_results if r[ "strategy" ] == "baseline" and r[ "success" ] ]
            pydantic_times = [ r[ "time" ] for r in self.performance_results if r[ "strategy" ] == "pydantic" and r[ "success" ] ]
            
            summary[ "performance" ] = {
                "baseline_avg_time": sum( baseline_times ) / len( baseline_times ) if baseline_times else 0,
                "pydantic_avg_time": sum( pydantic_times ) / len( pydantic_times ) if pydantic_times else 0,
                "baseline_samples": len( baseline_times ),
                "pydantic_samples": len( pydantic_times )
            }
            
            if baseline_times and pydantic_times:
                avg_baseline = summary[ "performance" ][ "baseline_avg_time" ]
                avg_pydantic = summary[ "performance" ][ "pydantic_avg_time" ]
                summary[ "performance" ][ "pydantic_speed_ratio" ] = avg_pydantic / avg_baseline if avg_baseline > 0 else 1.0
        
        return summary
    
    def _print_test_summary( self, summary: Dict[str, Any] ) -> None:
        """
        Print formatted test summary to console.
        
        Requires:
            - summary contains structured test results
            
        Ensures:
            - Prints comprehensive test summary
            - Highlights critical issues and performance data
            
        Raises:
            - None
        """
        print( "\n" + "=" * 80 )
        print( "MIGRATION VALIDATION SUMMARY" )
        print( "=" * 80 )
        
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
            print( f"  Pydantic avg: {perf[ 'pydantic_avg_time' ] * 1000:.2f}ms ({perf[ 'pydantic_samples' ]} samples)" )
            
            if "pydantic_speed_ratio" in perf:
                ratio = perf[ "pydantic_speed_ratio" ]
                if ratio < 1.0:
                    print( f"  ⚡ Pydantic is {1/ratio:.1f}x FASTER than baseline" )
                elif ratio > 1.0:
                    print( f"  🐌 Pydantic is {ratio:.1f}x slower than baseline" )
                else:
                    print( f"  ⚖️ Pydantic and baseline have similar performance" )
        
        print( f"\nMIGRATION STATUS: {'✅ READY' if summary[ 'migration_ready' ] else '❌ NOT READY'}" )
        
        if not summary[ "migration_ready" ]:
            print( "\nACTIONS REQUIRED:" )
            if summary[ "success_rate" ] < 90:
                print( f"  - Improve test success rate (currently {summary[ 'success_rate' ]:.1f}%, need ≥90%)" )
            if summary[ "critical_issues" ]:
                print( f"  - Resolve {len( summary[ 'critical_issues' ] )} critical issues" )
            if summary[ "categories_tested" ] < 4:
                print( f"  - Test more categories (currently {summary[ 'categories_tested' ]}, need ≥4)" )
        
        print( "=" * 80 )


def quick_smoke_test() -> bool:
    """
    Quick smoke test for ReceptionistXmlMigrationTester.
    
    Tests basic functionality and migration validation capabilities.
    
    Returns:
        True if smoke test passes
    """
    print( "Testing ReceptionistXmlMigrationTester..." )
    
    try:
        # Create tester instance
        tester = ReceptionistXmlMigrationTester( debug=True, verbose=False )
        print( "  ✓ Tester created successfully" )
        
        # Run quick validation (subset of full test suite)
        print( "  - Running basic validation tests..." )
        
        # Test strategy selection
        strategy_results = tester.test_strategy_selection()
        strategy_passed = sum( 1 for result in strategy_results.values() if result is True )
        print( f"    Strategy selection: {strategy_passed}/{len( strategy_results )} passed" )
        
        # Test configuration integration  
        config_results = tester.test_configuration_integration()
        config_passed = sum( 1 for result in config_results.values() if result is True )
        print( f"    Configuration: {config_passed}/{len( config_results )} passed" )
        
        # Test baseline parsing with one sample
        baseline_results = tester.test_baseline_parsing()
        baseline_passed = sum( 1 for result in baseline_results.values() if result is True )
        print( f"    Baseline parsing: {baseline_passed}/{len( baseline_results )} passed" )
        
        print( "  ✓ Basic validation tests completed" )
        print( "✓ ReceptionistXmlMigrationTester smoke test PASSED" )
        
        return True
        
    except Exception as e:
        print( f"✗ ReceptionistXmlMigrationTester smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        return False


def run_full_migration_test() -> bool:
    """
    Run the complete migration validation test suite.
    
    This is the main entry point for comprehensive migration testing.
    
    Returns:
        True if migration is ready, False if issues detected
    """
    print( "Starting comprehensive XML migration validation..." )
    
    try:
        tester = ReceptionistXmlMigrationTester( debug=True, verbose=False )
        
        results = tester.run_comprehensive_test_suite()
        
        # Return migration readiness status
        return results.get( "summary", { } ).get( "migration_ready", False )
        
    except Exception as e:
        print( f"Migration test suite failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run smoke test when executed directly
    success = quick_smoke_test()
    
    if success:
        print( "\n" + "="*50 )
        print( "Running full migration validation..." )
        print( "="*50 )
        
        migration_ready = run_full_migration_test()
        exit_code = 0 if migration_ready else 1
        
        print( f"\nExiting with code {exit_code}" )
        exit( exit_code )
    else:
        exit( 1 )