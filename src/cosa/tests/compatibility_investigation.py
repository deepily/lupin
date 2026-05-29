#!/usr/bin/env python3
"""
XML Compatibility Investigation: Baseline vs Pydantic Comparison

This script analyzes the differences between baseline util_xml.get_nested_list()
and Pydantic CodeResponse parsing to understand why Pydantic extracts all code 
lines correctly while baseline may miss some lines.
"""

import sys
from typing import List, Dict, Any, Tuple

# Import both parsing approaches
import cosa.utils.util_xml as dux
from cosa.agents.io_models.xml_models import CodeResponse

def create_test_cases() -> Dict[str, str]:
    """
    Create test XML cases that might expose parsing differences.
    
    Returns:
        Dictionary of test case names to XML strings
    """
    test_cases = {
        "simple_multiline": '''<response>
            <thoughts>Simple code example</thoughts>
            <code>
                <line>import math</line>
                <line>def square(x):</line>
                <line>    return x * x</line>
            </code>
            <returns>int</returns>
            <example>result = square(5)</example>
            <explanation>Basic function</explanation>
        </response>''',
        
        "compact_format": '''<response>
            <thoughts>Compact XML</thoughts>
            <code><line>import os</line><line>print("hello")</line><line>exit()</line></code>
            <returns>None</returns>
            <example>run_script()</example>
            <explanation>Compact format</explanation>
        </response>''',
        
        "mixed_spacing": '''<response>
            <thoughts>Mixed spacing</thoughts>
            <code>
                <line>import sys</line>

                <line>def main():</line>
                <line>    pass</line>
            </code>
            <returns>None</returns>
            <example>main()</example>
            <explanation>Mixed spacing example</explanation>
        </response>''',
        
        "single_line_tags": '''<response>
            <thoughts>Single line tags</thoughts>
            <code><line>x = 1</line>
<line>y = 2</line>
<line>print(x + y)</line></code>
            <returns>None</returns>
            <example>execute()</example>
            <explanation>Each tag on separate line</explanation>
        </response>''',
        
        "empty_lines": '''<response>
            <thoughts>Code with empty lines</thoughts>
            <code>
                <line>def function():</line>
                <line></line>
                <line>    return True</line>
            </code>
            <returns>bool</returns>
            <example>result = function()</example>
            <explanation>Contains empty line</explanation>
        </response>''',
        
        "complex_nesting": '''<response>
            <thoughts>Complex nested example</thoughts>
            <code>
                <line>import json</line>
                <line>data = {</line>
                <line>    "key": "value",</line>
                <line>    "number": 42</line>
                <line>}</line>
                <line>print(json.dumps(data))</line>
            </code>
            <returns>None</returns>
            <example>process_data()</example>
            <explanation>Multi-line dictionary</explanation>
        </response>'''
    }
    
    return test_cases

def compare_parsers(test_name: str, xml_string: str, debug: bool = False) -> Dict[str, Any]:
    """
    Compare baseline and Pydantic parsing results.
    
    Args:
        test_name: Name of the test case
        xml_string: XML content to parse
        debug: Enable debug output
        
    Returns:
        Dictionary with comparison results
    """
    results = {
        "test_name": test_name,
        "baseline_lines": [],
        "pydantic_lines": [],
        "baseline_success": False,
        "pydantic_success": False,
        "lines_match": False,
        "count_match": False,
        "differences": []
    }
    
    # Test baseline parser
    try:
        baseline_lines = dux.get_nested_list(xml_string, tag_name="code", debug=debug)
        results["baseline_lines"] = baseline_lines
        results["baseline_success"] = True
        
        if debug:
            print(f"Baseline extracted {len(baseline_lines)} lines:")
            for i, line in enumerate(baseline_lines):
                print(f"  [{i}]: '{line}'")
                
    except Exception as e:
        results["baseline_error"] = str(e)
        if debug:
            print(f"Baseline parser failed: {e}")
    
    # Test Pydantic parser
    try:
        pydantic_response = CodeResponse.from_xml(xml_string)
        results["pydantic_lines"] = pydantic_response.code
        results["pydantic_success"] = True
        
        if debug:
            print(f"Pydantic extracted {len(pydantic_response.code)} lines:")
            for i, line in enumerate(pydantic_response.code):
                print(f"  [{i}]: '{line}'")
                
    except Exception as e:
        results["pydantic_error"] = str(e)
        if debug:
            print(f"Pydantic parser failed: {e}")
    
    # Compare results
    if results["baseline_success"] and results["pydantic_success"]:
        baseline_lines = results["baseline_lines"]
        pydantic_lines = results["pydantic_lines"]
        
        results["count_match"] = len(baseline_lines) == len(pydantic_lines)
        results["lines_match"] = baseline_lines == pydantic_lines
        
        # Find differences
        if not results["lines_match"]:
            max_len = max(len(baseline_lines), len(pydantic_lines))
            for i in range(max_len):
                baseline_line = baseline_lines[i] if i < len(baseline_lines) else "<MISSING>"
                pydantic_line = pydantic_lines[i] if i < len(pydantic_lines) else "<MISSING>"
                
                if baseline_line != pydantic_line:
                    results["differences"].append({
                        "index": i,
                        "baseline": baseline_line,
                        "pydantic": pydantic_line
                    })
    
    return results

def run_compatibility_investigation(debug: bool = False) -> None:
    """
    Run the complete compatibility investigation.
    
    Args:
        debug: Enable debug output
    """
    print("=" * 80)
    print("XML COMPATIBILITY INVESTIGATION: Baseline vs Pydantic")  
    print("=" * 80)
    print()
    
    test_cases = create_test_cases()
    all_results = []
    
    for test_name, xml_string in test_cases.items():
        print(f"Testing: {test_name}")
        print("-" * 40)
        
        results = compare_parsers(test_name, xml_string, debug=debug)
        all_results.append(results)
        
        # Print summary
        if results["baseline_success"] and results["pydantic_success"]:
            baseline_count = len(results["baseline_lines"])
            pydantic_count = len(results["pydantic_lines"])
            
            print(f"Baseline: {baseline_count} lines")
            print(f"Pydantic: {pydantic_count} lines")
            
            if results["lines_match"]:
                print("✓ Results MATCH")
            else:
                print("✗ Results DIFFER")
                print(f"  Count match: {results['count_match']}")
                print(f"  Differences: {len(results['differences'])}")
                
                for diff in results["differences"]:
                    print(f"    Line {diff['index']}:")
                    print(f"      Baseline: '{diff['baseline']}'")
                    print(f"      Pydantic: '{diff['pydantic']}'")
        else:
            if not results["baseline_success"]:
                print(f"✗ Baseline failed: {results.get('baseline_error', 'Unknown error')}")
            if not results["pydantic_success"]:
                print(f"✗ Pydantic failed: {results.get('pydantic_error', 'Unknown error')}")
        
        print()
    
    # Summary analysis
    print("=" * 80)
    print("SUMMARY ANALYSIS")
    print("=" * 80)
    
    total_tests = len(all_results)
    matching_tests = sum(1 for r in all_results if r.get("lines_match", False))
    pydantic_more_lines = 0
    baseline_more_lines = 0
    
    for result in all_results:
        if result["baseline_success"] and result["pydantic_success"]:
            baseline_count = len(result["baseline_lines"])
            pydantic_count = len(result["pydantic_lines"])
            
            if pydantic_count > baseline_count:
                pydantic_more_lines += 1
            elif baseline_count > pydantic_count:
                baseline_more_lines += 1
    
    print(f"Total tests: {total_tests}")
    print(f"Matching results: {matching_tests}")
    print(f"Pydantic extracted more lines: {pydantic_more_lines} tests")
    print(f"Baseline extracted more lines: {baseline_more_lines} tests")
    
    if pydantic_more_lines > 0:
        print("\n⚠️  FINDING: Pydantic extracts more lines than baseline in some cases")
        print("   This confirms the reported compatibility issue.")
    
    return all_results

def quick_smoke_test() -> bool:
    """Quick smoke test for compatibility investigation."""
    try:
        test_cases = create_test_cases()
        simple_test = list(test_cases.values())[0]  # Get first test case
        
        # Test both parsers work
        baseline_lines = dux.get_nested_list(simple_test, tag_name="code")
        pydantic_response = CodeResponse.from_xml(simple_test)
        
        print("✓ Compatibility investigation smoke test PASSED")
        return True
        
    except Exception as e:
        print(f"✗ Compatibility investigation smoke test FAILED: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="XML Compatibility Investigation")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test only")
    
    args = parser.parse_args()
    
    if args.smoke:
        success = quick_smoke_test()
        sys.exit(0 if success else 1)
    else:
        run_compatibility_investigation(debug=args.debug)