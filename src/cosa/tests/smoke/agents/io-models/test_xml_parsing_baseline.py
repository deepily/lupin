#!/usr/bin/env python3
"""
Smoke Tests: XML Parsing Baseline Integration Testing

Integration smoke tests to capture the current real-world behavior of
XML parsing in the CoSA framework before migrating to Pydantic models.
These tests use actual prompt files and agent configurations.

This test module validates:
- Real XML patterns from actual prompt files
- Integration with existing agents and workflows
- Performance characteristics of current parsing
- Error handling in real-world scenarios
- Compatibility with the existing CoSA smoke test framework
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Import CoSA utilities
try:
    import cosa.utils.util_xml as dux
    import cosa.utils.util as du
except ImportError as e:
    print( f"Failed to import CoSA utilities: {e}" )
    sys.exit( 1 )


class TestXMLParsingBaseline:
    """
    Smoke test suite for XML parsing baseline validation.
    
    This class captures real-world integration behavior of XML parsing
    with actual prompt files and agent interactions to establish a
    comprehensive baseline before Pydantic migration.
    
    Follows CoSA smoke testing patterns with integration focus rather
    than isolated unit testing.
    """
    
    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize XML parsing baseline smoke tests.
        
        Args:
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.debug = debug
        self.verbose = verbose
        self.baseline_results = {}
        self.prompt_base_path = Path( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/conf/prompts" )
        
        # Sample XML responses that would come from actual LLM calls
        self.realistic_xml_responses = {
            "math_agent_response": """<response>
                <thoughts>I need to calculate the square root of 16</thoughts>
                <brainstorm>
                    <idea1>Use math.sqrt() function</idea1>
                    <idea2>Use exponentiation with 0.5</idea2>
                    <idea3>Use numpy.sqrt() for numerical stability</idea3>
                </brainstorm>
                <evaluation>math.sqrt() is the most straightforward approach</evaluation>
                <code>
                    <line>import math</line>
                    <line></line>
                    <line>def calculate_square_root(number):</line>
                    <line>    if number < 0:</line>
                    <line>        raise ValueError("Cannot calculate square root of negative number")</line>
                    <line>    return math.sqrt(number)</line>
                </code>
                <returns>float</returns>
                <example>result = calculate_square_root(16)</example>
                <explanation>This function calculates the square root using Python's built-in math.sqrt function with error checking for negative numbers.</explanation>
            </response>""",
            
            "command_router_response": """<response>
                <command>math</command>
                <args>calculate the square root of 25</args>
            </response>""",
            
            "calendar_agent_response": """<response>
                <question>What events do I have next Tuesday?</question>
                <thoughts>Need to filter the dataframe for next Tuesday's events</thoughts>
                <code>
                    <line>import pandas as pd</line>
                    <line>from datetime import datetime, timedelta</line>
                    <line></line>
                    <line>def get_tuesday_events(df):</line>
                    <line>    next_tuesday = datetime.now() + timedelta(days=(1-datetime.now().weekday()+7)%7)</line>
                    <line>    tuesday_str = next_tuesday.strftime('%Y-%m-%d')</line>
                    <line>    return df[df['date'] == tuesday_str]</line>
                </code>
                <returns>pandas.DataFrame</returns>
                <example>events = get_tuesday_events(calendar_df)</example>
                <explanation>Filters the calendar dataframe to show only events occurring next Tuesday.</explanation>
            </response>""",
            
            "simple_gist_response": """<response>
                <gist>User wants to know how to calculate compound interest with monthly contributions</gist>
            </response>""",
            
            "yes_no_response": """<response>
                <answer>yes</answer>
            </response>""",
        }
        
        # Edge cases that might occur in real usage
        self.edge_case_responses = {
            "malformed_xml": """<response>
                <thoughts>This is missing a close tag
                <code>
                    <line>def broken_function():</line>
                </code>
            </response>""",
            
            "empty_fields": """<response>
                <thoughts></thoughts>
                <code>
                    <line></line>
                </code>
                <returns></returns>
            </response>""",
            
            "special_characters": """<response>
                <explanation>This function handles special chars: &lt;tag&gt; and &amp; symbols</explanation>
                <code>
                    <line>if x &lt; 5 and y &gt; 3:</line>
                    <line>    result = "less than &amp; greater than"</line>
                </code>
            </response>""",
            
            "markdown_fallback": """```python
def fallback_function():
    print("This should be converted to XML format")
    return True
```"""
        }

    def test_realistic_xml_parsing( self ) -> bool:
        """
        Test XML parsing with realistic LLM responses.
        
        Uses XML patterns that would actually be generated by LLMs
        following the prompt templates in the CoSA framework.
        
        Returns:
            True if all realistic parsing tests pass
        """
        if self.debug:
            du.print_banner( "Testing Realistic XML Response Parsing" )
        
        test_results = {}
        
        try:
            # Test math agent response (complex nested structure)
            math_xml = self.realistic_xml_responses["math_agent_response"]
            
            # Extract key components
            thoughts = dux.get_value_by_xml_tag_name( math_xml, "thoughts" )
            evaluation = dux.get_value_by_xml_tag_name( math_xml, "evaluation" )
            code_lines = dux.get_nested_list( math_xml, tag_name="code" )
            returns = dux.get_value_by_xml_tag_name( math_xml, "returns" )
            explanation = dux.get_value_by_xml_tag_name( math_xml, "explanation" )
            
            # Validate brainstorm extraction
            idea1 = dux.get_value_by_xml_tag_name( math_xml, "idea1" )
            idea2 = dux.get_value_by_xml_tag_name( math_xml, "idea2" )
            idea3 = dux.get_value_by_xml_tag_name( math_xml, "idea3" )
            
            test_results["math_agent_parsing"] = {
                "thoughts": thoughts,
                "evaluation": evaluation,
                "code_lines_count": len(code_lines),
                "code_has_imports": "import math" in str(code_lines),
                "code_has_function": "def calculate_square_root" in str(code_lines),
                "returns": returns,
                "explanation_length": len(explanation),
                "brainstorm_ideas": {
                    "idea1": idea1,
                    "idea2": idea2,
                    "idea3": idea3
                }
            }
            
            # Test command router (simple structure)
            command_xml = self.realistic_xml_responses["command_router_response"]
            command = dux.get_value_by_xml_tag_name( command_xml, "command" )
            args = dux.get_value_by_xml_tag_name( command_xml, "args" )
            
            test_results["command_router_parsing"] = {
                "command": command,
                "args": args,
                "valid_command": command in ["math", "calendar", "weather", "todo"]
            }
            
            # Test calendar agent (DataFrame code generation)
            calendar_xml = self.realistic_xml_responses["calendar_agent_response"]
            question = dux.get_value_by_xml_tag_name( calendar_xml, "question" )
            calendar_code = dux.get_nested_list( calendar_xml, tag_name="code" )
            
            test_results["calendar_agent_parsing"] = {
                "question": question,
                "code_lines_count": len(calendar_code),
                "has_pandas_import": "import pandas" in str(calendar_code),
                "has_datetime_logic": "datetime" in str(calendar_code)
            }
            
            # Test simple responses
            gist_xml = self.realistic_xml_responses["simple_gist_response"]
            gist = dux.get_value_by_xml_tag_name( gist_xml, "gist" )
            
            yes_no_xml = self.realistic_xml_responses["yes_no_response"]
            answer = dux.get_value_by_xml_tag_name( yes_no_xml, "answer" )
            
            test_results["simple_responses"] = {
                "gist": gist,
                "gist_contains_keywords": "compound interest" in gist.lower(),
                "yes_no_answer": answer,
                "is_valid_yes_no": answer.lower() in ["yes", "no", "y", "n"]
            }
            
            self.baseline_results["realistic_parsing"] = test_results
            
            if self.debug:
                print( "✓ Realistic XML parsing baseline captured" )
            
            return True
            
        except Exception as e:
            if self.debug:
                print( f"✗ Realistic XML parsing failed: {e}" )
            return False

    def test_edge_case_handling( self ) -> bool:
        """
        Test XML parsing behavior with edge cases and malformed input.
        
        Captures how the current system handles:
        - Malformed XML
        - Empty fields
        - Special characters and escapes
        - Markdown fallback behavior
        
        Returns:
            True if edge case handling is documented
        """
        if self.debug:
            du.print_banner( "Testing Edge Case XML Handling" )
        
        test_results = {}
        
        try:
            # Test malformed XML (missing close tags)
            malformed = self.edge_case_responses["malformed_xml"]
            try:
                thoughts = dux.get_value_by_xml_tag_name( malformed, "thoughts" )
                test_results["malformed_xml"] = {
                    "status": "handled",
                    "thoughts_result": thoughts,
                    "graceful_degradation": True
                }
            except Exception as e:
                test_results["malformed_xml"] = {
                    "status": "error",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            
            # Test empty fields
            empty = self.edge_case_responses["empty_fields"]
            empty_thoughts = dux.get_value_by_xml_tag_name( empty, "thoughts" )
            empty_returns = dux.get_value_by_xml_tag_name( empty, "returns" )
            empty_code = dux.get_nested_list( empty, tag_name="code" )
            
            test_results["empty_fields"] = {
                "empty_thoughts": empty_thoughts == "",
                "empty_returns": empty_returns == "",
                "empty_code_lines": len(empty_code),
                "handles_empty_gracefully": True
            }
            
            # Test special character handling
            special = self.edge_case_responses["special_characters"]
            explanation = dux.get_value_by_xml_tag_name( special, "explanation" )
            special_code = dux.get_nested_list( special, tag_name="code" )
            
            test_results["special_characters"] = {
                "explanation_has_escapes": "&lt;" in explanation or "&gt;" in explanation,
                "code_unescaped_properly": "<" in str(special_code) and ">" in str(special_code),
                "handles_ampersands": "&" in str(special_code)
            }
            
            # Test markdown fallback
            markdown = self.edge_case_responses["markdown_fallback"]
            fallback_result = dux.rescue_code_using_tick_tick_tick_syntax( markdown )
            
            test_results["markdown_fallback"] = {
                "fallback_triggered": len(fallback_result) > 0,
                "converted_to_xml": "<line>" in fallback_result,
                "preserves_function": "def fallback_function" in fallback_result
            }
            
            self.baseline_results["edge_cases"] = test_results
            
            if self.debug:
                print( "✓ Edge case handling baseline captured" )
            
            return True
            
        except Exception as e:
            if self.debug:
                print( f"✗ Edge case testing failed: {e}" )
            return False

    def test_performance_characteristics( self ) -> bool:
        """
        Test performance characteristics of current XML parsing.
        
        Measures:
        - Parsing speed for different XML complexity levels
        - Memory usage patterns
        - Scalability with large responses
        
        Returns:
            True if performance baseline is captured
        """
        if self.debug:
            du.print_banner( "Testing XML Parsing Performance" )
        
        test_results = {}
        
        try:
            # Test simple parsing performance
            simple_xml = self.realistic_xml_responses["simple_gist_response"]
            start_time = time.time()
            
            for _ in range(1000):  # 1000 iterations
                gist = dux.get_value_by_xml_tag_name( simple_xml, "gist" )
            
            simple_duration = time.time() - start_time
            
            # Test complex parsing performance
            complex_xml = self.realistic_xml_responses["math_agent_response"]
            start_time = time.time()
            
            for _ in range(100):  # 100 iterations for complex XML
                thoughts = dux.get_value_by_xml_tag_name( complex_xml, "thoughts" )
                code_lines = dux.get_nested_list( complex_xml, tag_name="code" )
                idea1 = dux.get_value_by_xml_tag_name( complex_xml, "idea1" )
                explanation = dux.get_value_by_xml_tag_name( complex_xml, "explanation" )
            
            complex_duration = time.time() - start_time
            
            # Test code extraction performance
            start_time = time.time()
            
            for _ in range(500):  # 500 iterations
                code_lines = dux.get_nested_list( complex_xml, tag_name="code" )
            
            code_extraction_duration = time.time() - start_time
            
            test_results["performance_metrics"] = {
                "simple_parsing_1000_ops": {
                    "duration_seconds": simple_duration,
                    "ops_per_second": 1000 / simple_duration,
                    "avg_ms_per_op": (simple_duration * 1000) / 1000
                },
                "complex_parsing_100_ops": {
                    "duration_seconds": complex_duration,
                    "ops_per_second": 100 / complex_duration,
                    "avg_ms_per_op": (complex_duration * 1000) / 100
                },
                "code_extraction_500_ops": {
                    "duration_seconds": code_extraction_duration,
                    "ops_per_second": 500 / code_extraction_duration,
                    "avg_ms_per_op": (code_extraction_duration * 1000) / 500
                }
            }
            
            self.baseline_results["performance"] = test_results
            
            if self.debug:
                print( f"✓ Simple parsing: {1000/simple_duration:.0f} ops/sec" )
                print( f"✓ Complex parsing: {100/complex_duration:.0f} ops/sec" )
                print( f"✓ Code extraction: {500/code_extraction_duration:.0f} ops/sec" )
            
            return True
            
        except Exception as e:
            if self.debug:
                print( f"✗ Performance testing failed: {e}" )
            return False

    def test_integration_with_prompts( self ) -> bool:
        """
        Test integration with actual prompt files.
        
        Validates that XML patterns in prompt files match what
        the parsing functions expect to handle.
        
        Returns:
            True if prompt integration is validated
        """
        if self.debug:
            du.print_banner( "Testing Integration with Prompt Files" )
        
        test_results = {}
        
        try:
            # Sample some key prompt files to verify XML patterns
            prompt_files_to_check = [
                "agents/math.txt",
                "agents/calendaring.txt", 
                "agents/confirmation-yes-no.txt",
                "agent-router-template.txt",
                "vox-command-template.txt"
            ]
            
            for prompt_file in prompt_files_to_check:
                prompt_path = self.prompt_base_path / prompt_file
                
                if prompt_path.exists():
                    try:
                        with open( prompt_path, 'r' ) as f:
                            prompt_content = f.read()
                        
                        # Analyze XML patterns in prompts
                        has_response_tag = "<response>" in prompt_content
                        has_line_tags = "<line>" in prompt_content
                        has_code_tags = "<code>" in prompt_content
                        has_thoughts_tags = "<thoughts>" in prompt_content
                        
                        test_results[prompt_file.replace("/", "_")] = {
                            "file_exists": True,
                            "has_response_wrapper": has_response_tag,
                            "has_line_structure": has_line_tags,
                            "has_code_blocks": has_code_tags,
                            "has_thoughts": has_thoughts_tags,
                            "file_size": len(prompt_content)
                        }
                        
                    except Exception as e:
                        test_results[prompt_file.replace("/", "_")] = {
                            "file_exists": True,
                            "read_error": str(e)
                        }
                else:
                    test_results[prompt_file.replace("/", "_")] = {
                        "file_exists": False,
                        "path_checked": str(prompt_path)
                    }
            
            self.baseline_results["prompt_integration"] = test_results
            
            if self.debug:
                found_files = sum( 1 for result in test_results.values() if result.get("file_exists", False) )
                print( f"✓ Analyzed {found_files}/{len(prompt_files_to_check)} prompt files" )
            
            return True
            
        except Exception as e:
            if self.debug:
                print( f"✗ Prompt integration testing failed: {e}" )
            return False

    def save_smoke_test_baseline( self, filepath: Optional[str] = None ) -> str:
        """
        Save smoke test baseline results to JSON file.
        
        Args:
            filepath: Optional custom filepath
            
        Returns:
            Path to saved baseline file
        """
        if not filepath:
            timestamp = str(int(time.time()))
            filepath = f"/tmp/xml_parsing_smoke_baseline_{timestamp}.json"
        
        try:
            with open( filepath, 'w' ) as f:
                json.dump( self.baseline_results, f, indent=2 )
            
            if self.debug:
                print( f"✓ Smoke test baseline saved to: {filepath}" )
            
            return filepath
            
        except Exception as e:
            if self.debug:
                print( f"✗ Failed to save smoke test baseline: {e}" )
            return ""

    def run_all_smoke_tests( self ) -> bool:
        """
        Execute all smoke tests and save baseline results.
        
        Returns:
            True if all smoke tests pass
        """
        if self.debug:
            du.print_banner( "XML PARSING SMOKE TEST BASELINE" )
        
        start_time = time.time()
        
        try:
            # Run all smoke tests
            tests = [
                self.test_realistic_xml_parsing,
                self.test_edge_case_handling,
                self.test_performance_characteristics,
                self.test_integration_with_prompts
            ]
            
            passed = 0
            for test in tests:
                try:
                    if test():
                        passed += 1
                    else:
                        if self.debug:
                            print( f"✗ {test.__name__} failed" )
                except Exception as e:
                    if self.debug:
                        print( f"✗ {test.__name__} exception: {e}" )
            
            # Save smoke test baseline
            baseline_file = self.save_smoke_test_baseline()
            
            duration = time.time() - start_time
            success = passed == len(tests)
            
            if self.debug:
                du.print_banner( f"SMOKE TESTS COMPLETE: {passed}/{len(tests)} passed in {duration:.2f}s" )
                if success:
                    print( f"✓ All smoke tests completed successfully" )
                    print( f"✓ Baseline saved to: {baseline_file}" )
                else:
                    print( f"✗ {len(tests) - passed} smoke test failures" )
            
            return success
            
        except Exception as e:
            if self.debug:
                print( f"✗ Smoke test suite failed: {e}" )
            return False


def quick_smoke_test() -> bool:
    """
    Quick smoke test for XML parsing baseline validation.
    
    Follows the CoSA convention for component self-testing.
    
    Returns:
        True if smoke test passes
    """
    print( "Testing XML Parsing Baseline (Smoke Test)..." )
    
    try:
        test_suite = TestXMLParsingBaseline( debug=False )
        success = test_suite.run_all_smoke_tests()
        
        if success:
            print( "✓ XML parsing baseline smoke test PASSED" )
        else:
            print( "✗ XML parsing baseline smoke test FAILED" )
        
        return success
        
    except Exception as e:
        print( f"✗ XML parsing baseline smoke test FAILED: {e}" )
        return False


if __name__ == "__main__":
    # Run smoke tests with debug output
    test_suite = TestXMLParsingBaseline( debug=True, verbose=True )
    success = test_suite.run_all_smoke_tests()
    
    status = "✅ PASS" if success else "❌ FAIL" 
    print( f"{status} XML parsing baseline smoke tests completed" )