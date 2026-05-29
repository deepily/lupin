#!/usr/bin/env python3
"""
Unit Tests: XML Parsing Baseline Validation

Comprehensive unit tests to capture the current behavior of util_xml.py
before migrating to Pydantic models. This establishes a baseline for 
comparison after the Pydantic migration is complete.

This test module validates:
- Current get_value_by_xml_tag_name() behavior with all patterns
- get_xml_tag_and_value_by_name() functionality
- get_nested_list() for code line extraction
- remove_xml_escapes() processing
- rescue_code_using_tick_tick_tick_syntax() fallback behavior
- Error handling for malformed XML and missing tags
"""

import os
import sys
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from typing import Dict, Any, Optional, List, Tuple

# Import test infrastructure
try:
    from cosa.tests.unit.infrastructure.mock_manager import MockManager
    from cosa.tests.unit.infrastructure.test_fixtures import CoSATestFixtures
    from cosa.tests.unit.infrastructure.unit_test_utilities import UnitTestUtilities
except ImportError as e:
    print( f"Failed to import test infrastructure: {e}" )
    sys.exit( 1 )

# Import the XML utilities being tested
try:
    import cosa.utils.util_xml as dux
    import cosa.utils.util as du
except ImportError as e:
    print( f"Failed to import XML utilities: {e}" )
    sys.exit( 1 )


class XMLParsingBaselineUnitTests:
    """
    Unit test suite to establish baseline behavior of current XML parsing.
    
    This class captures the exact current behavior of util_xml.py functions
    to ensure that the Pydantic migration maintains compatibility and to
    document any quirks or limitations that need to be addressed.
    
    Requires:
        - MockManager for external dependency isolation
        - CoSATestFixtures for standardized test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All util_xml.py functions are thoroughly tested
        - Current behavior is documented and saved as baseline
        - Edge cases and error conditions are captured
        - Results are serializable for comparison after migration
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize XML parsing baseline unit tests.
        
        Args:
            debug: Enable debug output for troubleshooting
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.baseline_results = {}
        
        # Sample XML patterns from actual prompts
        self.simple_xml_samples = {
            "gist_response": "<response><gist>Brief summary of the main point</gist></response>",
            "yes_no_response": "<response><answer>yes</answer></response>",
            "summary_response": "<response><summary>Detailed summary text here</summary></response>",
            "command_response": "<response><command>math</command><args>2+2</args></response>"
        }
        
        self.code_xml_samples = {
            "simple_code": """<response>
                <thoughts>I need to write a function</thoughts>
                <code>
                    <line>def add_numbers(a, b):</line>
                    <line>    return a + b</line>
                </code>
                <returns>int</returns>
                <example>result = add_numbers(2, 3)</example>
                <explanation>Simple addition function</explanation>
            </response>""",
            
            "complex_code": """<response>
                <thoughts>Complex math problem solving</thoughts>
                <code>
                    <line>import math</line>
                    <line>import numpy as np</line>
                    <line></line>
                    <line>def calculate_distance(x1, y1, x2, y2):</line>
                    <line>    dx = x2 - x1</line>
                    <line>    dy = y2 - y1</line>
                    <line>    return math.sqrt(dx**2 + dy**2)</line>
                </code>
                <returns>float</returns>
                <example>distance = calculate_distance(0, 0, 3, 4)</example>
                <explanation>Calculates Euclidean distance between two points</explanation>
            </response>"""
        }
        
        self.nested_xml_samples = {
            "brainstorm_response": """<response>
                <thoughts>Need to brainstorm approaches</thoughts>
                <brainstorm>
                    <idea1>Use dynamic programming</idea1>
                    <idea2>Try recursive approach</idea2>
                    <idea3>Consider iterative solution</idea3>
                </brainstorm>
                <evaluation>Dynamic programming seems most efficient</evaluation>
                <solution>Implement DP solution</solution>
            </response>"""
        }
        
        self.malformed_xml_samples = {
            "missing_close_tag": "<response><gist>Missing close tag</response>",
            "missing_open_tag": "<response>gist>Missing open tag</gist></response>",
            "empty_tag": "<response><gist></gist></response>",
            "non_existent_tag": "<response><summary>Content</summary></response>"  # Asking for 'gist'
        }
        
        self.escaped_xml_samples = {
            "basic_escapes": "<response><code><line>if x &lt; 5 and y &gt; 3:</line><line>    result = a &amp; b</line></code></response>",
            "mixed_escapes": "<response><explanation>Use &lt;tag&gt; for XML &amp; &lt;/tag&gt; to close</explanation></response>"
        }
        
        self.markdown_fallback_samples = {
            "valid_python": """```python
def hello_world():
    print("Hello, World!")
    return True
```""",
            "invalid_format": "Some random text without markdown blocks",
            "partial_markdown": "```python\ndef incomplete("
        }

    def test_get_value_by_xml_tag_name_baseline( self ) -> bool:
        """
        Test current behavior of get_value_by_xml_tag_name() function.
        
        Captures baseline behavior for:
        - Simple tag extraction
        - Missing tags with default values
        - Missing tags without default values
        - Empty tag content
        - Malformed XML handling
        
        Returns:
            True if all baseline tests complete successfully
        """
        self.utils.print_test_banner( "Testing get_value_by_xml_tag_name() Baseline" )
        
        test_results = {}
        
        try:
            # Test simple successful cases
            for name, xml in self.simple_xml_samples.items():
                try:
                    if name == "gist_response":
                        result = dux.get_value_by_xml_tag_name( xml, "gist" )
                        expected = "Brief summary of the main point"
                        assert result == expected, f"Expected '{expected}', got '{result}'"
                        test_results[f"{name}_gist"] = {"status": "pass", "value": result}
                        
                    elif name == "yes_no_response":
                        result = dux.get_value_by_xml_tag_name( xml, "answer" )
                        expected = "yes"
                        assert result == expected, f"Expected '{expected}', got '{result}'"
                        test_results[f"{name}_answer"] = {"status": "pass", "value": result}
                        
                    elif name == "command_response":
                        command_result = dux.get_value_by_xml_tag_name( xml, "command" )
                        args_result = dux.get_value_by_xml_tag_name( xml, "args" )
                        assert command_result == "math", f"Expected 'math', got '{command_result}'"
                        assert args_result == "2+2", f"Expected '2+2', got '{args_result}'"
                        test_results[f"{name}_command"] = {"status": "pass", "value": command_result}
                        test_results[f"{name}_args"] = {"status": "pass", "value": args_result}
                        
                except Exception as e:
                    test_results[f"{name}_error"] = {"status": "fail", "error": str(e)}
            
            # Test with default values
            try:
                result_with_default = dux.get_value_by_xml_tag_name( 
                    self.simple_xml_samples["gist_response"], "nonexistent", "default_value" 
                )
                assert result_with_default == "default_value"
                test_results["default_value_test"] = {"status": "pass", "value": result_with_default}
            except Exception as e:
                test_results["default_value_error"] = {"status": "fail", "error": str(e)}
            
            # Test missing tags without default (should return error message)
            try:
                result_no_default = dux.get_value_by_xml_tag_name( 
                    self.simple_xml_samples["gist_response"], "nonexistent" 
                )
                # Current implementation returns error string
                expected_error = "Error: `nonexistent` not found in xml_string"
                assert result_no_default == expected_error
                test_results["missing_tag_no_default"] = {"status": "pass", "value": result_no_default}
            except Exception as e:
                test_results["missing_tag_error"] = {"status": "fail", "error": str(e)}
            
            # Test malformed XML cases
            for name, xml in self.malformed_xml_samples.items():
                try:
                    if name == "missing_close_tag":
                        result = dux.get_value_by_xml_tag_name( xml, "gist" )
                        test_results[f"malformed_{name}"] = {"status": "captured", "value": result}
                    elif name == "empty_tag":
                        result = dux.get_value_by_xml_tag_name( xml, "gist" )
                        assert result == ""  # Empty tag should return empty string
                        test_results[f"malformed_{name}"] = {"status": "pass", "value": result}
                except Exception as e:
                    test_results[f"malformed_{name}_error"] = {"status": "fail", "error": str(e)}
            
            self.baseline_results["get_value_by_xml_tag_name"] = test_results
            self.utils.print_test_status( "get_value_by_xml_tag_name baseline captured", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"get_value_by_xml_tag_name baseline failed: {e}", "FAIL" )
            return False

    def test_get_nested_list_baseline( self ) -> bool:
        """
        Test current behavior of get_nested_list() function.
        
        Captures baseline behavior for:
        - Code line extraction from <line> tags
        - Custom tag name handling
        - XML escape processing within lines
        - Empty code blocks
        - Multiline content handling
        
        Returns:
            True if all baseline tests complete successfully
        """
        self.utils.print_test_banner( "Testing get_nested_list() Baseline" )
        
        test_results = {}
        
        try:
            # Test simple code extraction
            for name, xml in self.code_xml_samples.items():
                try:
                    code_lines = dux.get_nested_list( xml, tag_name="code" )
                    test_results[f"{name}_lines"] = {
                        "status": "pass", 
                        "value": code_lines,
                        "line_count": len(code_lines)
                    }
                    
                    # Validate expected content
                    if name == "simple_code":
                        assert "def add_numbers(a, b):" in code_lines[0]
                        assert "return a + b" in code_lines[1]
                    elif name == "complex_code":
                        assert "import math" in code_lines[0]
                        assert "import numpy as np" in code_lines[1]
                        # Should have empty line
                        assert "" in code_lines  # Empty lines preserved
                        
                except Exception as e:
                    test_results[f"{name}_error"] = {"status": "fail", "error": str(e)}
            
            # Test with escaped XML content
            try:
                escaped_lines = dux.get_nested_list( 
                    self.escaped_xml_samples["basic_escapes"], tag_name="code" 
                )
                test_results["escaped_content"] = {
                    "status": "pass",
                    "value": escaped_lines,
                    "unescaped_correctly": "if x < 5" in str(escaped_lines) and "a & b" in str(escaped_lines)
                }
            except Exception as e:
                test_results["escaped_content_error"] = {"status": "fail", "error": str(e)}
            
            # Test empty code block
            try:
                empty_xml = "<response><code></code></response>"
                empty_lines = dux.get_nested_list( empty_xml, tag_name="code" )
                test_results["empty_code_block"] = {
                    "status": "pass",
                    "value": empty_lines,
                    "is_empty": len(empty_lines) == 0
                }
            except Exception as e:
                test_results["empty_code_error"] = {"status": "fail", "error": str(e)}
            
            self.baseline_results["get_nested_list"] = test_results
            self.utils.print_test_status( "get_nested_list baseline captured", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"get_nested_list baseline failed: {e}", "FAIL" )
            return False

    def test_remove_xml_escapes_baseline( self ) -> bool:
        """
        Test current behavior of remove_xml_escapes() function.
        
        Captures baseline behavior for:
        - Standard XML escape sequences (&lt;, &gt;, &amp;)
        - Multiple escapes in single string
        - Escape processing order
        - Edge cases and malformed escapes
        
        Returns:
            True if all baseline tests complete successfully
        """
        self.utils.print_test_banner( "Testing remove_xml_escapes() Baseline" )
        
        test_results = {}
        
        try:
            # Test individual escape sequences
            escape_test_cases = [
                ("&lt;", "<"),
                ("&gt;", ">"),
                ("&amp;", "&"),
                ("x &lt; 5", "x < 5"),
                ("if a &gt; b:", "if a > b:"),
                ("Tom &amp; Jerry", "Tom & Jerry"),
            ]
            
            for escaped, expected in escape_test_cases:
                try:
                    result = dux.remove_xml_escapes( escaped )
                    assert result == expected, f"Expected '{expected}', got '{result}' for input '{escaped}'"
                    test_results[f"escape_{escaped.replace('&', 'amp')}"] = {
                        "status": "pass",
                        "input": escaped,
                        "expected": expected,
                        "result": result
                    }
                except Exception as e:
                    test_results[f"escape_error_{escaped}"] = {"status": "fail", "error": str(e)}
            
            # Test multiple escapes in one string
            try:
                complex_escaped = "&lt;tag&gt; contains &amp; symbol"
                complex_expected = "<tag> contains & symbol"
                complex_result = dux.remove_xml_escapes( complex_escaped )
                assert complex_result == complex_expected
                test_results["multiple_escapes"] = {
                    "status": "pass",
                    "input": complex_escaped,
                    "expected": complex_expected,
                    "result": complex_result
                }
            except Exception as e:
                test_results["multiple_escapes_error"] = {"status": "fail", "error": str(e)}
            
            # Test escape processing order (important for preventing double-unescaping)
            try:
                order_test = "&amp;lt;"  # Should become &lt; then <
                order_result = dux.remove_xml_escapes( order_test )
                test_results["escape_order"] = {
                    "status": "captured",
                    "input": order_test,
                    "result": order_result,
                    "note": "Documents current escape processing order"
                }
            except Exception as e:
                test_results["escape_order_error"] = {"status": "fail", "error": str(e)}
            
            self.baseline_results["remove_xml_escapes"] = test_results
            self.utils.print_test_status( "remove_xml_escapes baseline captured", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"remove_xml_escapes baseline failed: {e}", "FAIL" )
            return False

    def test_rescue_code_fallback_baseline( self ) -> bool:
        """
        Test current behavior of rescue_code_using_tick_tick_tick_syntax() fallback.
        
        Captures baseline behavior for:
        - Markdown code block extraction
        - Conversion to XML line format
        - Invalid format handling
        - Edge cases with partial markdown
        
        Returns:
            True if all baseline tests complete successfully
        """
        self.utils.print_test_banner( "Testing rescue_code_using_tick_tick_tick_syntax() Baseline" )
        
        test_results = {}
        
        try:
            # Test valid markdown code extraction
            for name, markdown in self.markdown_fallback_samples.items():
                try:
                    result = dux.rescue_code_using_tick_tick_tick_syntax( markdown, debug=False )
                    test_results[f"markdown_{name}"] = {
                        "status": "captured",
                        "input": markdown,
                        "result": result,
                        "has_line_tags": "<line>" in result if result else False
                    }
                    
                    if name == "valid_python":
                        # Should convert to XML line format
                        assert "<line>" in result, "Should contain line tags"
                        assert "def hello_world():" in result
                        assert 'print("Hello, World!")' in result
                        
                except Exception as e:
                    test_results[f"markdown_{name}_error"] = {"status": "fail", "error": str(e)}
            
            self.baseline_results["rescue_code_fallback"] = test_results
            self.utils.print_test_status( "rescue_code_fallback baseline captured", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"rescue_code_fallback baseline failed: {e}", "FAIL" )
            return False

    def test_get_xml_tag_and_value_by_name_baseline( self ) -> bool:
        """
        Test current behavior of get_xml_tag_and_value_by_name() function.
        
        Captures how this function wraps get_value_by_xml_tag_name results
        in complete XML tags.
        
        Returns:
            True if all baseline tests complete successfully
        """
        self.utils.print_test_banner( "Testing get_xml_tag_and_value_by_name() Baseline" )
        
        test_results = {}
        
        try:
            # Test tag reconstruction
            for name, xml in self.simple_xml_samples.items():
                try:
                    if name == "gist_response":
                        result = dux.get_xml_tag_and_value_by_name( xml, "gist" )
                        expected = "<gist>Brief summary of the main point</gist>"
                        assert result == expected
                        test_results[f"{name}_reconstruction"] = {
                            "status": "pass",
                            "input_xml": xml,
                            "tag_name": "gist",
                            "result": result
                        }
                        
                except Exception as e:
                    test_results[f"{name}_reconstruction_error"] = {"status": "fail", "error": str(e)}
            
            # Test with default value
            try:
                result_default = dux.get_xml_tag_and_value_by_name( 
                    self.simple_xml_samples["gist_response"], "nonexistent", "default_value" 
                )
                test_results["reconstruction_with_default"] = {
                    "status": "captured",
                    "result": result_default,
                    "note": "Documents behavior with default values"
                }
            except Exception as e:
                test_results["reconstruction_default_error"] = {"status": "fail", "error": str(e)}
            
            self.baseline_results["get_xml_tag_and_value_by_name"] = test_results
            self.utils.print_test_status( "get_xml_tag_and_value_by_name baseline captured", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"get_xml_tag_and_value_by_name baseline failed: {e}", "FAIL" )
            return False

    def save_baseline_results( self, filepath: Optional[str] = None ) -> str:
        """
        Save baseline test results to JSON file for future comparison.
        
        Args:
            filepath: Optional custom filepath, defaults to temp directory
            
        Returns:
            Path to saved baseline file
        """
        if not filepath:
            timestamp = str(int(time.time()))
            filepath = f"/tmp/xml_parsing_baseline_{timestamp}.json"
        
        try:
            with open( filepath, 'w' ) as f:
                json.dump( self.baseline_results, f, indent=2 )
            
            print( f"✓ Baseline results saved to: {filepath}" )
            return filepath
            
        except Exception as e:
            print( f"✗ Failed to save baseline: {e}" )
            return ""

    def run_all_baseline_tests( self ) -> Tuple[bool, float, str]:
        """
        Execute all baseline tests and save results.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        self.utils.print_test_banner( "XML PARSING BASELINE UNIT TESTS" )
        
        start_time = time.time()
        errors = []
        
        try:
            # Run all baseline tests
            tests = [
                self.test_get_value_by_xml_tag_name_baseline,
                self.test_get_nested_list_baseline,
                self.test_remove_xml_escapes_baseline,
                self.test_rescue_code_fallback_baseline,
                self.test_get_xml_tag_and_value_by_name_baseline
            ]
            
            passed = 0
            for test in tests:
                try:
                    if test():
                        passed += 1
                    else:
                        errors.append( f"{test.__name__} failed" )
                except Exception as e:
                    errors.append( f"{test.__name__} exception: {e}" )
            
            # Save baseline results
            baseline_file = self.save_baseline_results()
            
            duration = time.time() - start_time
            success = passed == len(tests)
            
            self.utils.print_test_banner( 
                f"BASELINE COMPLETE: {passed}/{len(tests)} tests passed" 
            )
            
            if success:
                print( f"✓ All baseline tests completed successfully" )
                print( f"✓ Results saved to: {baseline_file}" )
            else:
                print( f"✗ {len(errors)} test failures" )
                for error in errors:
                    print( f"  - {error}" )
            
            return success, duration, "; ".join(errors) if errors else ""
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Baseline test suite failed: {e}"
            self.utils.print_test_status( error_msg, "FAIL" )
            return False, duration, error_msg


def isolated_unit_test( debug: bool = False ) -> Tuple[bool, float, str]:
    """
    Execute XML parsing baseline unit tests in isolation.
    
    This function follows the CoSA unit testing pattern for standalone
    test execution with complete external dependency mocking.
    
    Args:
        debug: Enable debug output
        
    Returns:
        Tuple of (success, duration, error_message)
    """
    try:
        # Create test instance
        test_suite = XMLParsingBaselineUnitTests( debug=debug )
        
        # Run all baseline tests
        return test_suite.run_all_baseline_tests()
        
    except Exception as e:
        return False, 0.0, f"Test suite initialization failed: {e}"


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} XML parsing baseline unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )